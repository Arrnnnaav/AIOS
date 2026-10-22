"""Make a windowed-app crash visible instead of silent.

A PyInstaller windowed build (Orbyn.exe) has no console, so an unhandled
exception just vanishes -- the app "won't start" with nothing to show, which is
exactly the failure that is hardest to support. This writes a redacted traceback
to a local file and pops a message box pointing at it, so a crash is seen.

Rule 6: nothing leaves the device -- the log is local-only, and the traceback is
scrubbed of embedded secrets (keys/emails/cards) before it is written, in case a
variable repr in the stack carried one. File paths stay (it is the owner's own
machine and their own log); only secrets are masked.
"""

from __future__ import annotations

import os
import time
import traceback
from pathlib import Path

from ghostcursor import redact


def _log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "GhostCursor" / "logs"


def write_crash(exc: BaseException, *, when: float | None = None) -> Path:
    """Write a redacted traceback to a timestamped local file; return its path."""

    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    text = redact.scrub(text)[0]  # mask any embedded secrets before writing
    directory = _log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(when))
    path = directory / f"crash-{stamp}.log"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def report(exc: BaseException) -> Path | None:
    """Log the crash and best-effort show a message box. Returns the log path,
    or None if even the log could not be written (never raises)."""

    try:
        path = write_crash(exc)
    except OSError:
        return None
    try:
        import win32api
        import win32con

        win32api.MessageBox(
            0,
            f"Orbyn hit an error and had to close.\n\nDetails saved to:\n{path}",
            "Orbyn",
            win32con.MB_ICONERROR,
        )
    except Exception:
        pass  # headless / no win32: the local log still exists
    return path


if __name__ == "__main__":  # ponytail: redacted + local round-trip
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        globals()["_log_dir"] = lambda: Path(d)
        try:
            raise ValueError("boom key sk-ABCDEFGHIJKLMNOP1234 mail a@b.com")
        except ValueError as e:
            p = write_crash(e)
        body = p.read_text(encoding="utf-8")
        assert "ValueError" in body and "boom" in body
        assert "sk-ABCDEFGHIJKLMNOP1234" not in body and "a@b.com" not in body
    print("crashlog ok")
