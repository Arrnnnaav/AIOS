# Archive and restore saved research results

27 October 2026. REA 6.5.0 managed-member Evidence
`ev_ab2ed42c6bd010c5073c0a9c5e8862bb0b53a6ecb7eccead0b181eebd2d65d31`
for the installed HeyClicky 1.1.1 Agents assembly names
`ClickyJobStore.Archive`, `Unarchive`, `get_ArchivedJobs` and
`TrimKeptJobsLocked`. These are shipped method names, not proof of HeyClicky's
live archive behavior or storage guarantees. The supplied installer and
assembly identities are recorded in
[the preceding comparison](heyclicky-result-artifact-2026-10-27.md).

Orbyn's finished research cards now offer Archive and Restore. Work hides
archived cards by default and exposes them through Show archived. The archive
flag is stored beside the existing question, answer and kept flag in the local
per-topic `.jobs.json` file; earlier inbox rows migrate to `archived: false`.
Archived cards remain within the 20-job limit. Unkept archived cards can age
out as new jobs begin, while kept archived cards retain the five-result Keep
protection. Archive adds no model, connector, scheduler, Teach or Act action.

The focused backend and Edge checks cover old-inbox migration, archive state
across restart, Restore, invalid/running-job refusal, failed-save rollback,
hidden-by-default UI, Show archived, and continued Markdown download. Final
suite, mutation, frozen-package and independent review results follow below.
The focused three-test lane passed, as did 70 workspace/input-boundary tests
with one interactive test deselected; the separate interactive Edge test passed
and checked that a second Archive returns to hidden-by-default behavior.
The staged full hermetic lane passed 3,648 tests with 93 deselected in 354.02 s
(`.tmp/hermetic-archived-results.log`). The frozen-package and D032 review
checks follow after this code slice is committed.
