# HeyClicky result artifact comparison and Orbyn Markdown download

27 October 2026. This is a static package comparison and one focused Orbyn
interaction slice. It does not claim that the HeyClicky artifact flow was run.

## Shipped-artifact observations

- Supplied `HeyClicky-Setup.exe`: SHA-256
  `3ccaedaee3cb6c3d4ed5b209fb9ab8a449501ab7d6181657c4eb6ad69ee70dfd`.
  REA 6.5.0 `inspect-artifact` returned Evidence
  `ev_6828982943a8d0bc9f94f173619ff63594588339472237c15352561f08867eb7`,
  a PE root with no decoded installer children. The installer was not run.
- The already installed 1.1.1 `HeyClicky.Agents.dll` has SHA-256
  `3aef8bd7019bd4a2e44f102f65046dfd5d84a009760aac19cd5e735d366d5809`.
  REA `inspect-managed-members` returned Evidence
  `ev_fa295ff92952ae9001e1fe4a336eae5d87f0f14f43a698ef08f82df7463d4ab1`.
  The managed metadata names `ClickyJobStore.SetResultCard` and
  `ClickyWorkPiece.ArtifactPaths`, `get_ExistingFilePaths`, and `get_Links`.
  These establish code surfaces for results and files, not successful export
  behavior or permission semantics. The earlier live UI record observed a
  document tile on an expanded result card.
- Codex's REA registration was healthy, but no REA MCP tools were attached to
  this active session. The version-pinned REA CLI read the same local artifacts;
  no registration, provider, or application setting was changed. Full CLI JSON
  stayed in ignored `.tmp/` files. Decompiled HeyClicky source was not copied.

## Orbyn slice

Work's saved research card now exposes **Download Markdown** when an answer is
available. The browser creates `orbyn-research.md` from the same bounded,
locally saved question and answer shown by View result. It makes no additional
API call, server-side file write, model request, connector call, or Act request.
The explicit click determines when the answer becomes a user download.

The focused Windows browser test seeds a completed local job, clicks Download
Markdown, checks that a Work redraw preserves keyboard focus on that button,
then checks the suggested filename and reads the downloaded bytes,
including Markdown and literal HTML-like text. The test passed (1 test) with
Edge headless. The source page script also passed `node --check` after extraction.
The staged full hermetic lane passed 3,645 tests with 93 deselected in 365.69 s
(`.tmp/hermetic-job-download-final.log`). The frozen `dist/Orbyn/Orbyn.exe`
was rebuilt. A packaged trial with an isolated local app-data directory and
seeded saved job passed filename/content download and clean Quit; its output is
`.tmp/packaged-job-download.log`. Neither browser trial called a model or
started a HeyClicky job.

An independent D032 reader reviewed commit `480a376` in a detached worktree
and returned READY with no blocking safety finding. The reader verified the
installer and assembly hashes, REA member names, explicit-click download,
focus preservation, and unchanged server/model/Act authority. The reader did
not rerun the tests. Restart persistence and fallback-browser downloads were
not retested in this slice. The exported Markdown preserves answer text, so
untrusted HTML or links in a result may be interpreted by another Markdown
renderer if the user opens the downloaded file there; Orbyn does not open it.
