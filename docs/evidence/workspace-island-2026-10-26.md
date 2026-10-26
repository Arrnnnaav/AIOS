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

After `island.py` became tracked, the first post-commit hermetic rerun found a
stale workspace module count in `test_devtools_stay_out_of_production.py` and
the signed-bytes gate correctly flagged this unstaged evidence edit. The count
was updated and the follow-up files staged. Both focused gates passed (7
tests), then the full hermetic lane passed 3,643 tests with 86 deselected in
327.13 seconds. Its local output is `.tmp/hermetic-island-final.log` (ignored).
