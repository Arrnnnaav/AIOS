# Live interruption — Stop and Pause on a running deck build

**Date:** 3 September 2026
**Plan:** `build-investor-deck-v1`, 255 nodes, digest `84e39d0d…`
**Bundle:** `9af59719132cfa941090175dc43ec9a1db1b0555e3103b50396449c4c7b551de`
**Application:** PowerPoint `16.0.20326.20112`
**Harness:** `act_acceptance --interrupt-on … --interrupt-after-node …`
**Raw records:** `.artifacts/act-live/deck/interrupt-matrix.json` (ignored path)

Every run here fires the same `controls.stop()` / `controls.pause()` a rail
click fires. Each is stamped `interrupt_probe`, never `result`, so none can be
counted as acceptance evidence.

## What "no post-stop action" can mean, precisely

Stop reaches `AdapterHost._next_cancellable`, which polls the cancel event
every 50 ms and then terminates the adapter subprocess. But the COM call that
subprocess issued is executing inside **PowerPoint's** process. Killing the
adapter cannot un-issue it.

So the guarantee is **no new node starts after Stop**. The in-flight node's
effect may still land, and may land unsaved. This is stated before the numbers
because it is the property the numbers measure; claiming "no effect lands
after Stop" would be claiming something unachievable across a process
boundary.

The run record stays conservative about this: a node whose effect landed but
was not confirmed is **not** added to `completed`. That is why a resumed plan
must re-observe rather than trust the list (D110).

## Stop — measured

| Mode | Fired during | Response | Nodes started after | Result |
|---|---|---|---|---|
| Quick | execution (`action_started`, node 40) | **0.187 s** | **0** | `stopped` |
| Quick | after a node (`action_completed`, node 60) | **0.094 s** | **0** | `stopped` |
| Watch | pacing (`action_completed`, node 8) | **0.094 s** | **0** | `stopped` |
| Watch | execution (`action_started`, node 12) | **0.172 s** | **0** | `stopped` |

**All four are inside D020's 0.5 s ceiling**, worst case 0.187 s — a 2.7×
margin. **Zero nodes started after the request in every case.**

The two "in execution" cases are the slower pair, which is what should
happen: they wait out the ≤50 ms cancel poll plus adapter process teardown.
The two caught between nodes return in half that.

Watch Build is not slower to stop than Quick Build. That was the risk the
sliced waiting in `act_pacing` exists to prevent, and the numbers say it
worked: 0.094 s stopping inside a pacing wait is the same as stopping between
nodes in Quick.

## Pause — measured

| Mode | Requested hold | Actual hold | Then |
|---|---|---|---|
| Watch | 4.0 s | **4.468 s** | resumed, completed 255/255 |
| Quick | 4.0 s | **4.062 s** | resumed, completed 255/255 |

"Hold" is the gap from the pause being requested to the next node starting. A
pause the executor ignored would show a gap near zero; both show the full
requested hold, so the run genuinely sat still and then continued to
completion.

Note that `response_s` for a pause is meaningless — it measures request to
run-return, which for a resumed run is the whole build (272.9 s and 63.7 s).
It is recorded but is not the measurement.

## A real gap this exposed: stopped runs published a partial deck — FIXED

Every stopped run left a `.pptx` at its approved output path: 36 902, 37 760,
47 676, 47 742 and 52 919 bytes, against ~94 400 for a complete deck.

The cause is that the adapter calls `SaveAs` on `create_presentation` and
`Save()` after every subsequent operation, so the file exists from node 1 and
grows. Transactional output — same-volume staging, final path absent until
fully verified, atomic publish — was ROADMAP item 6 and was **not built at the
time these runs were taken**.

**Fixed the same day** by `ghostcursor/act_staging.py`. Re-measured with
staging active, same interrupt at node 45:

```
staged        .staging/3bcd21901879-stopped-deck.pptx  (+ .incomplete.json)
not_published stopped-deck.pptx
result        stopped, 44 nodes, response 0.157s, started_after []
on disk       49437 bytes  .staging/3bcd21901879-stopped-deck.pptx
                395 bytes  .staging/…-stopped-deck.pptx.incomplete.json
```

**The approved path does not exist.** The partial work is kept, in the
staging directory, explicitly labelled.

And the success path, with PowerPoint holding the staging file open:

```
published     good-deck.pptx  sha256 896bdaf16d7cf2b0…
result        completed, 255 nodes, published_sha256 matches
on disk       94371 bytes  good-deck.pptx
```

10 slides, 191 shapes, digest matches the record, marker cleared, no
`.partial` left behind, and the earlier stopped run's staging file still
marked incomplete.

## The presenter's stop points — measured on the UIA vehicle

All 255 deck nodes are object-model, so nothing above can reach the
presenter. These were taken with `act_live_node` against `powerpoint.new_slide_uia`,
traversal 900 ms, settle 1200 ms.

| Stop landed | Response | Dispatches after | Lifecycle reached |
|---|---|---|---|
| traversal, 350 ms in | **0.0310 s** | **0** | preparing → presenting |
| settle, 1100 ms in | **0.0310 s** | **0** | preparing → presenting |
| confirmation boundary | **0.0310 s** | **0** | preparing → presenting |
| dispatch boundary | **0.0160 s** | **0** | preparing → presenting → **confirming** |

Independently confirmed: `live.pptx` was reopened from disk holding one
slide, and holds one slide after all four runs. No effect landed.

The traversal and settle cases refuse with *"the presentation for this node
was never acknowledged"* rather than an explicit stop. That is the receipt
mechanism doing the work rather than a check someone remembered to add: an
aborted cue emits no completion receipt, so `PresentationWait.may_execute`
never becomes true and no effect can follow.

The dispatch case is the only one that reaches `confirming` — identity was
compared, then the run stopped before the effect. That is the last boundary
at which stopping costs nothing.

### A gap this found before it was measured

`execute_node` had **no stop awareness at all**, and `act_uia_session` passed
no cancel event anywhere. A Stop landing after the cue completed went
unnoticed while confirmation, authorization, dispatch and verification all
ran — seconds, against D020's half second. Fixed by asking the operator's
Stop at the two boundaries where stopping is free.

It is deliberately **not** asked after the dispatch. Once an effect has been
issued the run owes it a verification; skipping one because someone pressed
Stop would leave an effect that happened and was never checked. Mutation
testing confirms this: adding a stop check before verification fails a test.

## Not measured here
- **Stop during verification.** By design not honoured: after a dispatch the
  verification runs to completion. How long that takes is now measured —
  **max 0.188 s** over 765 invocations
  (`docs/evidence/act-diagnostic-rerun.md`) — which bounds how late a stop
  can be observed on a node that already acted.
- **ESC**, as opposed to a rail Stop. The rail path is what these exercise.
