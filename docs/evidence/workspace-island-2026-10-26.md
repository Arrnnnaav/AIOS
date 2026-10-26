# Workspace island: implementation and local desktop check

26 October 2026. The default `ghostcursor.workspace.app` launch now creates
`ghostcursor/workspace/island.py` instead of opening Edge immediately. The
native topmost capsule starts compact; a running workspace task expands it,
and a new terminal research job keeps it expanded for twelve seconds. Open
launches the same token-protected full workspace used before this change.
Stop sets the existing worker Stop event. Quit uses `App.handle("quit", {})`.
The capsule title and painting use only generic state labels; it does not show
the research question or answer, model text, goal, credentials or target identity.
Drag uses normal Windows caption hit testing. The Teach overlay remains a
separate click-through window and no input synthesis was added.

Local check: a temporary fake App displayed the native island on this desktop,
changed from Ready to Researching, and produced `.tmp/island-probe.png` (ignored;
cropped desktop image). The first paint attempt exposed a pywin32 `DrawText`
argument error, which was fixed before this record. A focused interactive test
created the real Win32 island, verified its topmost window and buttons, changed
worker and job state with an injected clock, and called the island command
handler for Open, Stop and Quit. The test passed. A separate real launch of
`py -3.12 -m ghostcursor.workspace.app island-acceptance` showed one visible
`OrbynWorkspaceIsland` window and a live loopback server; its token-protected
Quit API returned 200 and the process exited 0. No full Edge window opened at
startup. This was a desktop launch check, not Teach acceptance.

Focused checks: `tests/test_workspace_island.py`, `tests/test_workspace_app.py`
and `tests/test_no_input_synthesis.py` passed 68 tests. The full hermetic lane
(`py -3.12 -m pytest tests -m "not interactive and not pixel and not hung"
--basetemp=.tmp\pytest-hermetic-island -p no:cacheprovider -q`) passed 3,643
tests with 86 deselected in 332.53 seconds. A D018 privacy mutation removed
the fixed-label guard and the generic-state test failed; the source was restored.

`pwsh -File tools/build_orbyn.ps1` built the onedir `dist/Orbyn/Orbyn.exe`.
The frozen app was launched with a fresh topic. An on-desktop script used the
native island's Open command and checked actual top-level windows, then called
the token-protected Quit endpoint. Its retained output is:

```text
packaged_island=visible_default
packaged_open=one_full_edge_window
packaged_quit=server_and_island_closed
```

The script observed no full Edge window before Open. This checks the packaged
launcher and window lifecycle; the earlier packaged Chat/Plan/Brain/Work and
GitHub run is in `workspace-live-acceptance-2026-10-26.md`. Teach/Act release
acceptance and multi-monitor placement were not rerun here.

A relaunch check then found that running the default launcher again while the
island was already visible opened a full window. The live-instance branch now
leaves the visible island in place; `--window` still opens the full workspace.
Focused tests for both branches passed. This follow-up source change has not
yet been rebuilt into the packaged artifact above.

Independent D032 review found that Open's five-second Edge positioning wait
ran inside the capsule window procedure. If the user pressed Open during work,
Stop could be delayed until Edge appeared. Open now starts that wait on a
background thread. An interactive injected-blocking-open test called Stop
before releasing Open and observed the existing Stop event set within the
test's half-second bound. Review also found `Orbyn.cmd`'s old “nothing leaves
the box” comment contradicted the configured provider and connector paths;
it now describes the local UI and possible chosen outbound requests separately.
The native buttons now have Tab stops, Windows dialog-key dispatch and a
spoken-text Quit name. Keyboard navigation was not measured with a physical
keyboard in this run.

The repaired slice passed 73 focused tests, including the interactive blocked
Open check and signed-byte/no-input-synthesis gates. The full hermetic lane
passed 3,644 tests with 87 deselected in 372.95 seconds; its local output is
`.tmp/hermetic-island-review.log` (ignored). The packaged acceptance lines
above predate the repaired Open and relaunch code.

After commit `004d625`, the D018 mutation check changed the island's Stop
event setter to a clear and its Quit command to a wrong action, one mutation
at a time. The native handler test failed on each mutant. The committed bytes
were restored after each run. The earlier privacy-label mutation was also
killed by its generic-state test.

The frozen app was rebuilt (`.tmp/build-island-review.log`, ignored). The same
packaged lifecycle check passed on the repaired bytes: one island at startup,
one full Edge window after Open, then no island or server after Quit. A second
default executable launch while the island was already up left one island and
zero full Edge windows; an explicit `--window` launch then opened one full
workspace window. Those windows were closed and the token-protected Quit API
returned 200. This confirms the frozen entry and lifecycle, not a live model,
Teach or Act session.

After `island.py` became tracked, the first post-commit hermetic rerun found a
stale workspace module count in `test_devtools_stay_out_of_production.py` and
the signed-bytes gate correctly flagged this unstaged evidence edit. The count
was updated and the follow-up files staged. Both focused gates passed (7
tests), then the full hermetic lane passed 3,643 tests with 86 deselected in
327.13 seconds. Its local output is `.tmp/hermetic-island-final.log` (ignored).
