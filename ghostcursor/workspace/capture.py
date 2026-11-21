"""A global capture hotkey (D186): Bear's most-requested feature -- one
system-wide shortcut to grab the clipboard without switching to Orbyn.

Press the hotkey anywhere; the current clipboard text is appended to a capture
log you review later. Rule 1: this only READS the clipboard and writes a file;
it never types into any app and never sends anything off the machine. The log
is the safe sink (like dictation), not the Company Brain -- the owner moves
entries into the Brain by hand after reviewing them.

Default hotkey is Ctrl+Alt+C (MOD_CONTROL|MOD_ALT, 'C'). The win32 listener
runs on its own daemon thread with its own message loop (the only thread that
may own the RegisterHotKey), independent of the blocking console prompt.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path


def _default_log() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "GhostCursor" / "captures.md"


def append_capture(
    text: str | None, *, log: Path | None = None, clock=time.time
) -> bool:
    """Append a non-blank clipboard grab to the capture log as one dated bullet.
    Returns True when something was written. Pure enough to test: no win32."""

    text = " ".join((text or "").split())
    if not text:
        return False
    from ghostcursor import redact

    # A copied password or key must not land in a plain-text file.
    text = redact.scrub(text, redact.SECRETS)[0]
    path = log or _default_log()
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(clock()))
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(f"- [{stamp}] {text}\n")
    return True


def start(*, log: Path | None = None) -> Path:
    """Start the global-hotkey listener on a daemon thread; return the log path.

    Thin win32 shell (excluded from the hermetic lane like other win32 code);
    the logic it calls -- append_capture -- is tested. ponytail: fixed hotkey
    Ctrl+Alt+C; make it configurable only if someone actually needs to.
    """

    log = log or _default_log()

    def _loop() -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
        WM_HOTKEY = 0x0312
        if not user32.RegisterHotKey(
            None, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("C")
        ):
            return  # another app owns the combo; give up quietly
        from ghostcursor.harness import act

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                try:
                    append_capture(act.get_clipboard_text(), log=log)
                except Exception:
                    pass  # a locked clipboard must not kill the listener

    threading.Thread(target=_loop, name="orbyn-capture", daemon=True).start()
    return log


if __name__ == "__main__":  # ponytail: the sink logic (win32 shell untested)
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        log = Path(d) / "captures.md"
        assert append_capture("hello world", log=log)
        assert not append_capture("   ", log=log)  # blank -> nothing
        assert not append_capture(None, log=log)
        assert append_capture("second", log=log)
        body = log.read_text(encoding="utf-8")
        assert sum(ln.startswith("- [") for ln in body.splitlines()) == 2
        assert "hello world" in body and "second" in body
    print("capture ok")
