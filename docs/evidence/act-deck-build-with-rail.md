# Investor deck built with the safety rail on screen

**Date:** 3 September 2026
**Plan:** `build-investor-deck-v1`, 255 nodes, 254 edges, digest
`84e39d0d2987e153923c537587380e9eeecccfae0a50ede5be586e0238e4fe79`
**Bundle:** `d68be5498446b14bfd031d0cf95c059738bae52f0564df19bed62674ee0fcd49`
(rebuilt from current source; manifest `b0deb920…`)
**Application:** PowerPoint `16.0.20326.20112`, hwnd 2885152
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
target hwnd 2885152.

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
