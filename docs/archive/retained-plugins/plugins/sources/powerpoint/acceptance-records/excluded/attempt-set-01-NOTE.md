# Attempt set 1 — NOT acceptance evidence

4 September 2026. Two passes then an abort, so this set does not satisfy the
three-consecutive-clean policy.

| Run | Outcome | Steps | UIA-only | Ended | `verification_started_s` |
|---|---|---|---|---|---|
| `attempt-set-01-run-01.json` | passed | 1/1 | yes | 4.547 s | 4.047 s |
| `attempt-set-01-run-02.json` | passed | 1/1 | yes | 4.016 s | **absent** |
| `attempt-set-01-run-03.json` | **aborted** | 0/1 | no | 0.0 s | absent |

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

**Added 4 September 2026, after an independent D032 review.** This note
originally listed run 02 as a clean pass and said nothing about its timing.
Run 02 records no `verification_started_s`, the same gap that later caused
attempt set 2 to be refused. So the anomaly occurred **twice**, not once, and
this set would have failed the timing gate independently of the abort. The
omission mattered: describing run 02 as clean made the anomaly look like a
single event in set 2 rather than a recurring one. See
`docs/superpowers/FOLLOWUPS.md`.
