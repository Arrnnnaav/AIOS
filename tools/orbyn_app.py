"""Desktop entry point for Orbyn.

Double-click ``Orbyn.cmd`` (or run ``py -3.12 tools\\orbyn_app.py``) to open the
Orbyn workspace in a docked Edge app-mode window -- the local-first desktop app.
No arguments: opens the default workspace. Everything runs on 127.0.0.1 behind a
per-launch token (ghostcursor/workspace/app.py); nothing is exposed off-device.

This is also the PyInstaller entry (tools/orbyn.spec, tools/build_orbyn.ps1) for
a packaged Orbyn.exe.
"""

from ghostcursor.workspace.app import main

if __name__ == "__main__":
    raise SystemExit(main([]))
