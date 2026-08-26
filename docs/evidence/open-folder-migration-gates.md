# Open Folder migration — gates 1 and 2

Status: **both gates passed; migration closed**

Validates moving the Open Folder workflow from provider-side exact lookup to the
bounded-descendants strategy (D069). The migration exists because
`iter_vscode_elements()` had been returning zero elements against VS Code
1.134.0, so the certified workflow was completing on OCR alone with no gate
noticing — the end-to-end outcome still succeeded.

## Environment

- VS Code **1.134.0**, commit `110a328ea54b42367b803ec53ee0bf52ef26b419`, x64
- Windows 11, single `Code.exe` window, no folder open at the start of each run
- Raw logs: `.artifacts/gate2/run{1,2,3}.log` (ignored by design, per D065)

## Gate 1 — read-only live grounding, 5 consecutive

| Criterion | Result |
|---|---|
| Exactly one UIA element | PASS |
| Name normalises to `Open Folder...` | PASS |
| `source == "uia"` | PASS |
| Valid on-screen bounding box | PASS — `(527, 238, 677, 277)` |
| Grounds on a UIA name rung, never OCR | PASS — rung 3, substring |

Five consecutive runs, identical each time. The bbox confirms the **correct**
target: the Welcome-page action, not the Explorer sidebar button at
`(39, 263, 359, 297)`.

Gate 1 earned its keep. Its "exactly one element" criterion caught a real
defect the hermetic tests could not see: two on-screen controls matched the
recipe's trusted names, and grounding was silently taking the first — the
sidebar button, which is not the validated target. That produced the
`EXACTLY_ONE` action-selector rule and narrowed the walker's allowed names to
the ellipsis spellings.

## Gate 2 — three consecutive guided-tour completions

| Run | `Tour complete.` | In-tour provenance | OCR mentions in log | Pre-run capture |
|---|---|---|---|---|
| 1 | yes | `source=uia rung=3` | 0 | PASS |
| 2 | yes | `source=uia rung=3` | 0 | FAIL — cold tree |
| 3 | yes | `source=uia rung=3` | 0 | FAIL — cold tree |

**3/3 on the substantive criteria**: every run completed, every run grounded
through UIA rather than OCR, and no run mentions OCR anywhere in its log.

The in-tour provenance line is the authoritative measurement. It reports the
tier that actually grounded the step inside `ghostcursor.run`, which is what the
gate is about; gate 1 could only show that the walker *could* find the target.

### The pre-run capture is a flawed instrument, and this is why

It failed on runs 2 and 3 while those runs succeeded. Two reasons, both worth
keeping:

1. **It perturbs the run it measures.** The capture is itself a UIA probe, and
   Chromium enables its accessibility tree on demand (D035). So a "failed"
   pre-check is often what *warms* the tree for the run that follows. Run 2
   arguably succeeded because its pre-check ran.
2. **A genuinely cold VS Code window returns zero elements on the first probe.**
   That is a product-relevant fact independent of the gate: on a real cold start
   with nothing warming the tree first, a tour's early walks can return nothing
   and OCR can escalate — producing exactly the silent OCR-grounded run this
   gate exists to catch.

The in-tour provenance line measures the same property without perturbing
anything, so it should replace the pre-run capture in any future gate of this
shape.

### Incidental: all three runs exercised the deterministic path

Every run logged
`Planner: MODEL_UNAVAILABLE_FALLBACK (0.95) — matched exact phrase` with an
Ollama `HTTPError` or `TimeoutError`. The local model was installed and the
endpoint answered `200` between runs, so these were cold-model timeouts against
the production 15 s budget — consistent with the cold-start observation recorded
in `model-execution-influence.md`.

So the workflow was validated on the deterministic path, not the model path.
Under D068 that changes nothing about what the workflow can do — the model
cannot alter which recipe executes — but it should be stated rather than left
implicit, and it is further live evidence that the fallback behaves honestly
when the model is unavailable.

## Outcome

Both gates pass. The Open Folder workflow now grounds through tier 1 again,
against the correct control, with OCR available as an escalation path rather
than silently carrying the workflow.

Rung 3 rather than rung 2 remains open and is tracked in
`docs/superpowers/FOLLOWUPS.md`: the Codicon prefix defeats byte-exact name
equality, and the fix belongs in the declarative compiler, which can carry both
raw and normalised names on a selector without widening the global ladder.
