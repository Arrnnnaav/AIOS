# Attempt set 2 — NOT acceptance evidence

Three runs, 4 September 2026, all three `outcome: passed`, `1/1` steps,
`grounded_by_uia_only: true`, `record_kind: "run"`, identical pack/intent/recipe
digests, identical application identity `16.0.20326.20112`, and one shared
HWND `1050680` across all three.

| Record | End | verification_started_s |
|---|---|---|
| `attempt-set-02-run-01.json` | 5.797s | 5.281s |
| `attempt-set-02-run-02.json` | 3.531s | 3.015s |
| `attempt-set-02-run-03.json` | 2.782s | **absent** |

## Why this set does not close the gate

`attempt-set-02-run-03.json` records no `verification_started_s`. Per D075 an absent
timing mark means the event never happened, and that is the finding rather
than a formatting detail. `tools/render_open_extensions_evidence.py` — the
existing precedent for a single-intent candidate acceptance — requires the
full ordered landmark set and refuses a record without it.

The pass itself is sound: `element_appears` is absent-then-present against the
run-start baseline, and `"View Indicator Slide 2 of 2"` is reachable only from
a one-slide deck. What is missing is the loop's own record that it observed
evidence of the user's action. Static reading of `reasoning/loop.py` does not
explain the absence and in fact contradicts it — see
`docs/superpowers/FOLLOWUPS.md`, "ADD_SLIDE run recorded no
`verification_started_s`".

Kept, not deleted. Admitting this record would mean weakening a gate to fit an
unexplained result; discarding it and keeping the two complete runs would turn
2-of-3 into a claim of consecutive success. Runs 01 and 02 cannot be carried
into a later set: consecutiveness does not span a non-qualifying run.

## Also established here, and worth keeping

- The three artifact digests in every record match the bytes on disk at commit
  `8ff0c62`, which has no uncommitted change under the candidate root.
- `Step.preconditions` is parsed in `reasoning/schema.py` and never read by the
  reasoning path. The recipe's declared `slide1_before` precondition therefore
  gates nothing; the one-slide starting state is established by the
  verification selector's semantics, not by the precondition.
