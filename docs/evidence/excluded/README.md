# Excluded live attempts

> **Manifest superseded 30 September 2026 (D149).** The PowerPoint manifest
> `28dbaf2d` named in this record is superseded by `3a4f8c57`. D145 added two
> signed UIA confirmation-timing fields to `operations.json`, so the bundle was
> rebuilt from tracked sources and re-signed with the same
> `ghostcursor-release-2026-3` key; adapter and verifier bytes are unchanged.
> Nothing below is evidence for `3a4f8c57`, and the captured content is not edited.

Runs that happened and are **not** counted as evidence. They are retained here
rather than deleted, because an attempt that is dropped silently is
indistinguishable from an attempt that never happened, and a reader has no way
to tell whether the retained runs were selected for their outcome.

Each entry names what was run, why it does not count, and what the artifacts do
and do not show. Nothing here may be cited as acceptance evidence.

---

## `act-live-manager-2026-09-11-attempt-1.jsonl` — 11 September 2026

**Why excluded: no starting reading.** The manager was launched before its
`before-1` deck observation was taken, so the run has no bracket on the state it
began from. Its own transcript is complete and internally consistent, and the
run reached `completed 1/1` on its second approval cycle — this is not a
discarded failure.

| Artifact | SHA-256 |
|---|---|
| `act-live-manager-2026-09-11-attempt-1.jsonl` | `1ded3d8fe8cc2f30b05201e417b4d26cb86dbb273c71da67c119dabd4fd0418e` |
| `act-live-deck-2026-09-11-attempt-1-after.json` | `209b9c82eaeeb30935a90497373ff9bcb8c28421f5cdec85eb165bca2c5f5306` |

**What the transcript shows.** Nineteen records, two approval cycles. The first
ended `adapter_failed` with zero completed nodes; the second reached
`completed`, one node. Both cycles carry identical proposal and target digests.
It bound `catalog_generation 9`, manifest
`28dbaf2d372c55144e289316a1b92dd25185281351cd685a8e735ee9d759a836` — the same
authority as the retained run.

**What it cannot show.** The deck read 2 slides afterwards, and no reading exists
for the state before the manager opened. A blank presentation begins with one
slide by construction, but "by construction" is an assumption, and D034 does not
accept an assumption in place of a measurement. Nothing here establishes a
change, and the unpaired `after` reading is retained only so the exclusion can
be checked rather than taken on trust.

**Relationship to the retained run.** `act-live-manager-d131-run.md` was
performed afterwards on the same authority, with readings taken per attempt. The
exclusion is on the missing bracket alone, decided before the later run existed
and independent of either outcome.
