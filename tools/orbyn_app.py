"""Desktop entry point for Orbyn.

Double-click ``Orbyn.cmd`` (or run ``py -3.12 tools\\orbyn_app.py``) to open the
Orbyn workspace in a movable Edge app-mode window -- the local-first desktop app.
No arguments: opens the default workspace. The local server listens only on
127.0.0.1 behind a per-launch token (ghostcursor/workspace/app.py). Configured
model, search, and GitHub requests may leave under user choice and policy.

This is also the PyInstaller entry (tools/orbyn.spec, tools/build_orbyn.ps1) for
a packaged Orbyn.exe.
"""

import sys
from pathlib import Path

# Running this file by path puts tools/ on sys.path, not the repo root, so a
# source checkout cannot import ghostcursor. Add the repo root (parent of tools/)
# so `Orbyn.cmd` / `py -3.12 tools/orbyn_app.py` work without installing the
# package. Harmless when frozen by PyInstaller (the bundled modules win).
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from ghostcursor.workspace.app import main

if __name__ == "__main__":
    # Windowed build has no console, so an unhandled crash is invisible. Log it
    # (redacted, local) and show a message box instead of vanishing.
    try:
        _code = main()  # read sys.argv so --version / --help / a topic work
    except SystemExit:
        raise
    except BaseException as _exc:  # noqa: BLE001 -- last-resort visibility
        from ghostcursor.workspace.crashlog import report

        report(_exc)
        _code = 1
    raise SystemExit(_code)
