# Attempt set 1 — NOT acceptance evidence

4 September 2026. Two passes then an abort, so this set does not satisfy the
three-consecutive-clean policy.

| Run | Outcome | Steps | UIA-only | Ended |
|---|---|---|---|---|
| 01 | passed | 1/1 | yes | 4.547 s |
| 02 | passed | 1/1 | yes | 4.016 s |
| 03 | **aborted** | 0/1 | no | 0.0 s |

Run 3's detail: `aborted before the first observation`, with empty
`grounding_provenance`.

**Classification: operator abort, nothing exercised.** The first invocation of
run 3 was interrupted at the terminal; the immediate re-run aborted before its
first observation, consistent with the harness polling ESC and seeing the
interrupt still active. No hint was rendered and no verification ran, so this
is not evidence that the ADD_SLIDE workflow fails — it is evidence that
nothing was tested.

**Kept rather than deleted.** A failure is preserved and classified before
rerunning; discarding the inconvenient record and keeping the two passes would
turn 2-of-3 into a claim of consecutive success.

Runs 01 and 02 cannot be combined with a later set: consecutiveness does not
span an abort. Acceptance needs three clean runs in an unbroken sequence.
