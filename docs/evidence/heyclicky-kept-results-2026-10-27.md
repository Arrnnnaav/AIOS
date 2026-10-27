# Kept research results: REA comparison and Orbyn trial

27 October 2026. The supplied HeyClicky 1.1.1 installer and installed Agents
assembly were inspected in the preceding
[artifact record](heyclicky-result-artifact-2026-10-27.md). Focused REA 6.5.0
managed-member Evidence
`ev_ab2ed42c6bd010c5073c0a9c5e8862bb0b53a6ecb7eccead0b181eebd2d65d31`
for `HeyClicky.Agents.Jobs.ClickyJobStore` names `KeepOnDock`, `Dismiss`,
`Archive`, `Unarchive`, `TrimKeptJobsLocked`, and `SaveLocked`. These names
establish shipped code surfaces. They do not establish the runtime behavior,
storage limits, or user approval flow. No HeyClicky job was started.

Orbyn's existing per-topic job inbox previously retained only the latest 20
research jobs. A finished job with an answer now offers Keep/Unkeep in Work.
Up to five kept results sort ahead of unkept jobs and survive the 20-item trim;
starting a new job removes the oldest unkept entry. Existing inbox rows gain
`pinned: false` on read. Pin and unpin change only this local inbox. A save
failure reports an error and reverts the visible state. Remove still asks for
confirmation, naming a kept result explicitly. No connector, model, Teach,
Act or scheduler authority is added.

Focused checks cover migration from the old inbox shape, 20-item trimming,
restart persistence, five-result cap, invalid requests, failed-save rollback,
and a 500 px Edge Work view that can Keep a result and still download it. The
three focused checks passed (`.tmp/pytest-keep-results`), as did the 69-test
workspace/input-boundary lane. The staged full hermetic lane passed 3,647 tests
with 93 deselected in 371.35 s (`.tmp/hermetic-kept-results.log`). `node
--check` passed for the page script. The frozen-package and D032 review
records follow after the code commit.
