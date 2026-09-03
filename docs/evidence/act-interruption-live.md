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

## A real gap this exposed: stopped runs publish a partial deck

Every stopped run left a `.pptx` at its approved output path: 36 902, 37 760,
47 676, 47 742 and 52 919 bytes, against ~94 400 for a complete deck.

The cause is that the adapter calls `SaveAs` on `create_presentation` and
`Save()` after every subsequent operation, so the file exists from node 1 and
grows. **Transactional output — same-volume staging, final path absent until
fully verified, atomic publish — is ROADMAP item 6 and is not built.**

So the honest summary is: Stop is clean at the executor level and not yet at
the artifact level. A stopped run leaves a partial deck a person could open
and mistake for a finished one.

This also interacts with "Act never overwrites an existing output artifact":
because the partial file is at the approved path, a retry to the same path is
refused. Correct in itself, but it means an unattended campaign must allocate
a fresh path per attempt rather than reusing one.

## Not measured here

- **The presenter's stop points.** Traversal, settle and confirmation exist
  only for a pointer-drawing node, and all 255 deck nodes are object-model.
  Those three need the single-node UIA vehicle, and are not covered by
  anything above. Any claim of full interruption coverage must exclude them
  until they are.
- **Stop during verification.** The verifier is a separate short-lived
  process; a stop landing inside it was not isolated as its own case.
- **ESC**, as opposed to a rail Stop. The rail path is what these exercise.
