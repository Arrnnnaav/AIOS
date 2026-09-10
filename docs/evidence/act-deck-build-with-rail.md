# Investor deck built with the safety rail on screen

**Date:** 3 September 2026
**Plan:** `build-investor-deck-v1`, 255 nodes, 254 edges, digest
`84e39d0d2987e153923c537587380e9eeecccfae0a50ede5be586e0238e4fe79`
**Bundle:** `d68be5498446b14bfd031d0cf95c059738bae52f0564df19bed62674ee0fcd49`
(rebuilt from current source; manifest `b0deb920…`)
**Application:** PowerPoint `16.0.20326.20112`, hwnd [redacted 10 Sep 2026, D122]
**Harness:** `ghostcursor.devtools.act_acceptance --rail`

## Why the rail matters here, specifically

D109: an object-model node draws **no pointer**. There is no control it is
clicking, so a cursor over one would show an action where it did not happen.
What it shows instead is the rail step, a label, and the document changing.

All 255 nodes of this plan are object-model. Before this, the entire deck
build ran with **nothing on screen at all** — a 65-second batch job with no
visible surface and no way to stop it from the UI. The rail is not a companion
to the ghost pointer for this plan; it is the whole product.

## The path this used

Not the diagnostic harness. `act_acceptance` runs the production path:

1. `PluginStore.install()` a signed `.ghostplugin`, signature verified
2. `enable()` and `load_composition_context()`
3. `materialize_action_plan()` against the reviewed plan digest
4. `resolve_target()` — one matching window or none, never the foreground
5. `approve_action_graph()` — a real digest-bound `PlanApproval`
6. `execute_approved_graph()`

Approval `b54e99a446d854cc…`, graph `0a3f57b5f9dc7f05…`, 255 nodes,
target hwnd [redacted 10 Sep 2026, D122].

## Runs

Four consecutive builds, each with a fresh store root and a distinct output
path. Every one completed.

| Run | Output | Result | Nodes | Last rail status |
|---|---|---|---|---|
| 01 | `deck-rail-01.pptx` | completed | 255/255 | `Step 255 of 255` ¹ |
| 02 | `deck-rail-02.pptx` | completed | 255/255 | `all actions verified` |
| 03 | `deck-rail-03.pptx` | completed | 255/255 | `all actions verified` |
| 04 | `deck-rail-04.pptx` | completed | 255/255 | `all actions verified` |

¹ Run 01 exposed the first defect below; runs 02–04 are after the fix.

511 rail events per run, `stop_requested: false`, ~65 s elapsed.

Artifacts: 10 slides, 191 shapes, ~94.4 KB each. Slide titles: GOAL, PROBLEM,
SURFACE, PRODUCT, EVIDENCE, WEDGE, EXPANSION, COMMERCIAL PATH, DEFENSIBILITY,
NEXT PROOF.

## Two defects the live run found

Both were invisible to the unit tests, and the reason each was invisible is
the interesting part.

### The terminal event names were invented

The rail treated `run_completed` and `run_failed` as terminal. The executor
publishes `completed`, `refused`, `stopped`, `action_failed` and
`verification_failed`. So a finished run kept displaying `Step 255 of 255`
instead of its outcome.

**Every unit test passed**, because they fed the invented names back in. A
closed loop between a module and its tests, agreeing with each other about a
vocabulary neither had read from the executor. The set is now compared against
the names `act_runtime` actually publishes, extracted from its source, so the
two cannot drift apart again without failing.

### The status was clipped, not wrapped

`Step 103 of 255 · done` overflows the 148 px compact rail. Win32 clips rather
than wraps, so it rendered as the step number on one line and a cut-off
`· done` beneath it — actively misleading, since the text could not be read to
the end.

The step number is the contract; `· done` is an adornment. Dropped it rather
than lose legibility of the thing that must be readable. `Paused` now replaces
rather than prefixes, for the same reason: a clipped `Paused — Step 103 of 2`
reads as a smaller deck than exists.

Confirmed by screenshot at step 88 of 255, fitting on one line.

## What the rail does not do

- **It never counts.** `Step N of M` is `ActEvent.ordinal` / `.total`,
  published by the executor. A rail that counted its own events could
  disagree with the executor about which node is running.
- **It never reinterprets.** No event after a terminal one rewords the
  outcome; it cannot turn a finished run back into a running one.
- **A requested stop stays requested.** `Stopping…` holds rather than
  reverting to a step number, because the run is still finishing its node.

## Not established here

- **Stop and Pause were never exercised on these runs.** `stop_requested` is
  false in all four. That they are wired is covered hermetically on an
  injected clock; that they interrupt a live 255-node build inside D020's
  0.5 s ceiling is **not** measured. That is the next thing.
- These are diagnostic builds, not acceptance runs: the signing key is the
  ephemeral development pair, not a reviewed release key.
- No independent review of this evidence has happened (D032).

---

# Watch Build and slide-follow — 3 September 2026

Bundle rebuilt after the adapter gained view-follow:
`9af59719132cfa941090175dc43ec9a1db1b0555e3103b50396449c4c7b551de`,
manifest `cae796d0…`. Plan digest unchanged.

## Two modes, measured

| Mode | Elapsed | Nodes | Pacing added |
|---|---|---|---|
| Quick Build | ~65 s | 255/255 | none |
| Watch Build (`watch-01`) | 226.7 s | 255/255 | 255 × 550 ms |
| Watch Build (`watch-03`) | 222.4 s | 255/255 | 255 × 550 ms |

3.4× slower, which is the point: Watch Build exists to be followed.

The pacing numbers (300 ms before a node, 250 ms after) are a **choice about
legibility, not a measurement**, and are labelled as such in
`ghostcursor/act_pacing.py` so nobody later cites them as though something had
been measured (D034).

## The visible slide follows the node

Observed live during `watch-03`, read from the object model while the run was
at node ~143 of 255:

```
view on slide 6 of 6
view on slide 7 of 7
view on slide 8 of 8
view on slide 9 of 9
```

**UIA could not answer this.** The newly created presentation's window has a
cold accessibility tree — 8 descendants, no status bar, no view indicator —
the same phenomenon D035 documents for a cold Chromium tree. The reading was
taken through COM instead. Worth recording, because a future check that
assumed UIA could see a background PowerPoint window would silently observe
nothing and report it as "the view never moved".

## What did not change

No ghost cursor is drawn for any of these 255 nodes. They are object-model
operations; nothing is clicked, and D109 forbids a pointer over a control the
runtime did not invoke. The visible surface is the rail step plus the document
region genuinely changing — which is what slide-follow now provides.

## Consequences to carry forward

- **Phase A's 255/255 no longer describes the shipped adapter.** The follow
  changed `adapter_sha256`. That run must be redone before any acceptance
  claim rests on it.
- **Stop and Pause are still unexercised.** `stop_requested` is false on every
  run recorded here, Quick and Watch alike. Watch Build is where interruption
  matters most — it is the mode a person watches, and the mode with waiting in
  it — and no live measurement exists yet.
- PowerPoint exited between runs at one point and a subsequent build refused
  at target resolution with `TargetNotRunning`, correctly, rather than
  proceeding. An unattended runner must restore or refuse explicitly rather
  than fail obscurely.

---

# Region highlight — 3 September 2026

Bundle `3fb104f62c6f4974f1d0d4a7882ec2762b3c5e5557546efe0879ad3152b7e80a`,
manifest `5ba2cdc3…`. Plan digest unchanged.

## The geometry was probed, not assumed

`Application.HWND` and every sibling window handle raise
`DISP_E_MEMBERNOTFOUND` on Office 16.0.20326. `PointsToScreenPixelsX/Y` is a
sibling of those, so it was probed on the same build before anything relied
on it.

It works. A shape at `(48.96, 30.24)` sized `417.6 × 16.96` points converted
to screen rect `(581, 310, 1086, 331)`. Computed rects for five shapes were
drawn over a screenshot and land exactly on their shapes.

## What is shown, and what is not

No cursor. These are object-model nodes; nothing is clicked, and D109 forbids
a pointer over a control the runtime did not invoke. What is drawn is the
ring and the label — "the document region genuinely changing", which is what
the rule prescribes instead.

Shown in the ARTIFACT trust class, because an object-model effect is verified
by reading the saved file. Showing it as LIVE_STATE would claim evidence
nothing gathered.

Observed together at node 103 of 255: the rail reading `Step 103 of 255`, a
cyan ring around the trust strip labelled `add shape`, PowerPoint on slide 4
where that node was working, and no cursor anywhere on screen.

## Coverage, accounted for exactly

**221 of 255 nodes carry a region.** The 34 without are every operation that
touches no shape:

| Operation | Count | Region |
|---|---|---|
| `add_text` | 117 | yes |
| `add_shape` | 56 | yes |
| `add_animation` | 30 | yes |
| `add_line` | 18 | yes |
| `add_slide` | 10 | no shape |
| `add_notes` | 10 | no shape |
| `set_transition` | 10 | no shape |
| `create_presentation`, `set_theme`, `save_presentation`, `inspect_presentation` | 4 | no shape |

117 + 56 + 30 + 18 = 221.

An earlier run reported 209. The difference is **12 nodes, not 10**, and the
first version of this paragraph explained only the 10 — recomputed from the
logs during the D032 review of 4 September 2026, the missing set was 10
`add_line` **and 2 `add_animation`**.

The cause is the same for both: a perfectly horizontal or vertical shape has
a zero-area bounding box and the degenerate check dropped it. The two
animations target flat line shapes, so they inherited the same rect. A flat
line is still a region that changed, so the flat axis is now opened to a
visible minimum.

Recording this because the original explanation accounted for 10 of 12 and
read as though it accounted for all of them.

## The channel

The event carries a **typed** region — four integers — not an open data bag.
A general dict on the event would be a channel for anything an adapter felt
like sending, and presentation is all this may carry (D106). It is validated
in core rather than trusted, because it crosses a process boundary, and a
malformed rect is dropped rather than raised: a highlight that cannot be
drawn must never fail an effect that already happened.
