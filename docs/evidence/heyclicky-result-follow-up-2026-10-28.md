# Saved-result follow-up

28 October 2026. The installed HeyClicky 1.1.1 `HeyClicky.Agents.dll`
(SHA-256 `3aef8bd7019bd4a2e44f102f65046dfd5d84a009760aac19cd5e735d366d5809`)
was inspected with REA 6.5.0 managed-member analysis. Evidence
`ev_918d14226bfa74d6ab9a35e32cfbd9eea653cd5b4606902af4f0953fa6b619b7`
names `AgentService.SubmitThreadFollowUpAsync`, `StartFollowUpTurnAsync` and
`SteerAsync`. The retained ILSpy decompilation of `ClickyJobStore` shows
`RecordThreadId` associating a finished job and its last run with a thread.
This is code evidence for a follow-up path; no HeyClicky job or live follow-up
was run, and the method names alone do not establish its UI semantics.

Orbyn now offers an explicit follow-up on a saved finished research result.
The server selects the saved answer by job ID and passes its first 8,000
characters to the existing one-off Ask path. The path performs full-material
DLP before tainted chunking, uses the configured model and Stop event, and
does not record the question or reply in the inbox, Brief or Brain. The UI
states the context limit and egress before the user asks. There is no thread
resume, research rerun, scheduled follow-up, or Act authority.

The focused backend and Edge run passed 2 tests with 51 deselected
(`.tmp/pytest-job-followup-final`). Edge exercised the result-sheet question,
reply focus and Close, then confirmed the existing Markdown download still
worked. The full hermetic lane passed 3,649 tests with 93 deselected in
371.10 seconds (`.tmp/hermetic-job-followup.log`). The backend test checked
server-side material selection, the 8,000-character bound, lack of persisted
question/reply, invalid IDs and running-job refusal. The test gateway returned
a stub reply; no live model provider was exercised.

D018 mutation: removing the finished-state guard from `job_ask` let a seeded
running row with a premature answer through. The focused test failed because
the API returned 200 instead of the required 400. Restoring the guard made
the same test pass (1 passed, 52 deselected); the mutant was not committed.

An independent D032 reader inspected `7adf9fc` in a detached worktree and
returned READY with no blocking safety finding. The reader verified the REA
method evidence and installed assembly hash, server-side result selection,
bounded full-material DLP, tainted egress, Stop wiring, lack of persistence,
and text-only UI rendering. The reader did not rerun pytest under D025.
Nonblocking limits: only the first 8,000 characters can answer a follow-up;
the result sheet has no visible Stop button during the request, although the
page's Escape/global Stop path remains available.
