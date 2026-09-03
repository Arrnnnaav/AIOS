# First live pointer-driven node — PowerPoint `New Slide`

**Date:** 3 September 2026
**Application:** Microsoft PowerPoint 16.0.20326.20112,
`C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE`
**Window:** hwnd 2885152, pid 17856, `live.pptx - PowerPoint`
**Harness:** `py -3.12 -m ghostcursor.devtools.act_live_node --frame-budget-ms 2`
**Operation:** `powerpoint.new_slide_uia`, backend `uia_pattern`, pattern `Invoke`
**Selector:** `powerpoint.new-slide`, `Button` named `New Slide`,
sha256 `0721bf8c…`
**Adapter:** `ghostcursor/adapter/uia_adapter.py`, sha256 `0752ebc2…`

## What this is and is not

This is a **diagnostic**, not acceptance evidence. It runs one node rather
than a validated graph, and it mints no real `PlanApproval` — the authority
token is stubbed, and the harness says so at the stub. No claim here counts
toward the 3/3 acceptance policy, and `powerpoint.new_slide_uia` remains
unadopted.

What it establishes is narrower and still worth recording: the pointer path,
cue layout, presenter, overlay, receipt protocol, adapter host, signed
selector loading, and the read-only UIA adapter all work together against a
real application, and the parts that are not finished fail closed rather than
claiming success.

## Runs

| Run | traversal | settle | Reached | Dispatched | Slides after |
|---|---|---|---|---|---|
| 1 | 700 ms | 900 ms | verifying | yes | 2 |
| 2 | 900 ms | 4000 ms | presenting (refused) | **no** | 2 |
| 3 | 900 ms | 4000 ms | verifying | yes | 3 |

Slide count read live from the status bar `View Indicator Slide N of N`
through read-only UIA. The deck opened with one slide.

**The consistency check is the point of the table.** Three runs, two
dispatches, two slides added — and the run that refused added nothing. The
refusal path did not perform a hidden effect.

## What worked

- **The Invoke landed.** `Slide 1 of 1` → `Slide 2 of 2` after run 1, and
  `Slide 3 of 3` after run 3.
- **The pointer was drawn on the control it clicked.** Captured mid-settle:
  ghost pointer tip on the `New Slide` button, `New Slide` callout above it,
  ring around the control, PowerPoint's own UI visible through the overlay.
- **Identity was real and stable.** RuntimeId
  `[42, 10553270, 4, -1564011424, 572]` read before the cue and again at
  confirmation, compared by `compare_identity` under
  `runtime_id_required`, with `automation_id` empty as expected — PowerPoint's
  ribbon exposes none, which is why the identity mode requires RuntimeId.
- **The signed selector resolved.** The control name came from a
  digest-checked file, not from the harness.
- **Lifecycle ran in order:** `preparing → presenting → confirming →
  executing → verifying → refused`.

## Two defects this found

### 1. The presentation deadlines measured the wrong interval

Run 2 refused with `render_timeout` at a 4000 ms settle where run 1 passed at
900 ms, though both painted their first frame immediately.

`present()` returns only once the whole presentation is over, and
`execute_node` timestamped its results in the consuming loop. So a first
paint that happened at 0 ms was judged against the moment the settle ended.
Any dwell longer than the first-paint deadline would have refused every node,
and every dwell shorter than it would have passed regardless of when the
paint actually happened.

Fixed by passing the wait's own `accept` into `present` as a sink, so each
receipt is recorded at the instant it is emitted. Run 3 is the same
configuration as run 2 after the fix and reaches `verifying`.

### 2. There was no live-state verifier — CLOSED, same day

Every run reports `verified: False`, `the declared postcondition was not
observed`. The cause is not the action:
`plugins/sources/powerpoint/payload/ghostcursor/adapter/powerpoint_verifier.py`
opens a **saved `.pptx` on disk** and counts slides in the package. It is an
**artifact** verifier, which is the right shape for an `object_model`
operation whose effect is a file.

A `uia_pattern` operation changes **live application state**. Nothing is
written to disk until someone saves, so the artifact verifier cannot answer
the postcondition, and it correctly declines to.

That is the trust-class split doing its job:
`trust_for(UIA_PATTERN, VERIFIED)` is `LIVE_STATE`, "verified from fresh live
UI state" — evidence the artifact verifier does not have and never claimed to.
The node reporting `refused` rather than `verified` is the system failing
closed on a verification it genuinely could not perform.

**Closed by `powerpoint_live_verifier.py`** and a `live_verifier` slot in
`adapter_api`, mirroring the `uia_entrypoint` slot D108 added. See the
"Run 4" section below.

## Not established here

- That the effect is *correct* — only that a slide count increased. The
  postcondition remains unverified by any signed verifier.
- Anything about repeated or unattended execution.
- Anything about `_execute_approved_graph`, which this harness bypasses.
- Any acceptance claim whatsoever.

---

## Run 4 — verified, with the live-state verifier

Same harness, same window, after `powerpoint_live_verifier.py` landed.

```
verifier   live application state independently confirms the change
           observed={'slide_count': 4, 'slide_current': 4}
verified   True
trust      live_state
detail     the declared postcondition was independently observed
lifecycle  preparing -> presenting -> confirming -> executing -> verifying -> verified
receipts   geometry_started@100173921ms, presentation_completed@100175109ms
elapsed    2.98s
```

The deck went 3 → 4 slides and the postcondition
`slide.count.increased_by_one` held against the reading taken before the cue.

`slide.exists` — the previous postcondition — would have passed here too, and
would equally have passed had nothing happened at all. Naming a change rather
than a state is what makes the verification mean something.

## Non-vacuity of the live verifier

A verifier that always says yes is worth nothing, so it was run directly
against the same live PowerPoint with baselines chosen so the declared
relation could not hold:

| Case | Outcome |
|---|---|
| baseline == now (nothing happened) | refused |
| baseline two behind (two slides added, not one) | refused |
| count went **down** against `slide.count.increased` | refused |
| baseline one behind, `increased_by_one` — **control** | verified |
| `slide.count.unchanged`, and it was — **control** | verified |
| postcondition nobody can answer (`slide.teleported`) | refused |
| no postcondition declared at all | refused |
| baseline carrying no slide count | refused |
| no baseline, as on an observation | refused |

Seven refusals and two verifications, and both verifications are true
statements about the deck at that moment. The two that matter most are the
last three refusals: an unanswerable postcondition, an empty postcondition
list, and a missing baseline all fail closed rather than passing by being
skipped — which is the shape of a check that looks present in the record and
enforces nothing.

## Still not established

- Repeatability. One verified run is not the 3/3 acceptance policy, and this
  harness still mints no real approval.
- Anything about `_execute_approved_graph`, which it bypasses.
- The `legacy_iaccessible` backend, which has no operation and no evidence.
