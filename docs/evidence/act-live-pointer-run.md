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

### 2. There is no live-state verifier — this is the remaining gap

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

**A live-state verifier does not exist yet.** `adapter_api` declares a single
`verifier`, so a separately signed read-only live-state verifier also needs a
manifest slot, mirroring the `uia_entrypoint` slot D108 added. Recorded in
`docs/superpowers/FOLLOWUPS.md`.

## Not established here

- That the effect is *correct* — only that a slide count increased. The
  postcondition remains unverified by any signed verifier.
- Anything about repeated or unattended execution.
- Anything about `_execute_approved_graph`, which this harness bypasses.
- Any acceptance claim whatsoever.
