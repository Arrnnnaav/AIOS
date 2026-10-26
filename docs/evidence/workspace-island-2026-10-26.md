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
startup. This was a desktop launch check, not Teach or packaged acceptance.

Focused checks: `tests/test_workspace_island.py`, `tests/test_workspace_app.py`
and `tests/test_no_input_synthesis.py` passed 68 tests. The full hermetic lane
(`py -3.12 -m pytest tests -m "not interactive and not pixel and not hung"
--basetemp=.tmp\pytest-hermetic-island -p no:cacheprovider -q`) passed 3,643
tests with 86 deselected in 332.53 seconds. Packaged GUI acceptance remains
to be recorded after the build.
