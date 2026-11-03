"""What Orbyn did on this PC, for the owner and their auditor (D187).

One append-only JSON line per event under ``%LOCALAPPDATA%\\GhostCursor\\
audit\\audit.jsonl``. Each line carries the SHA-256 of the line before it, so
an edited, removed or reordered line breaks the chain and ``verify`` names
where. Events, not content (D141): an allow-list of event names and fields,
numbers and short identifiers only -- never a goal, screen text, window title,
handle, PID or path (rule 6). Recording never raises: an audit failure must
not stop the user's work, and it never blocks Stop.

    py -3.12 -m ghostcursor.audit verify
    py -3.12 -m ghostcursor.audit export <file>
"""

from __future__ import annotations

import getpass
import hashlib
import json
import ntpath
import os
import shutil
import sys
import threading
import time
from pathlib import Path

#: event -> the only fields it may carry.
EVENTS = {
    "plan_approved": {"via", "steps", "app", "plugin"},
    "act_step": {"via", "action", "control_type", "app", "outcome"},
    "act_run": {"via", "plugin", "code", "completed", "steps"},
    "drive_approved": {"max_steps"},
    "egress": {"provider", "model", "failure", "images"},
    "team_publish": {"facts", "skills", "agents"},
    "team_sync": {"outcome", "facts", "skills", "agents"},
}
MAX_FIELD = 80
GENESIS = "0" * 64
_lock = threading.Lock()


def default_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "GhostCursor" / "audit" / "audit.jsonl"


def _clean(event: str, fields: dict) -> dict:
    allowed = EVENTS[event]  # KeyError: an unknown event is a programming error
    out = {}
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"{event} does not record {key!r}")
        if isinstance(value, str):
            if key == "app":  # an executable's name, never its path (rule 6)
                value = ntpath.basename(value)
            value = value[:MAX_FIELD]
        elif not (value is None or isinstance(value, (bool, int, float))):
            raise ValueError(f"{key} must be a number or short text")
        out[key] = value
    return out


def _last_hash(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 4096))
            lines = handle.read().splitlines()
    except FileNotFoundError:
        return GENESIS
    return hashlib.sha256(lines[-1]).hexdigest() if lines else GENESIS


def record(event: str, *, path: Path | None = None, clock=time.time, **fields) -> bool:
    """Append one event; False (never an exception) if it could not be written.
    An unknown event or field is refused, so content cannot slip in."""

    try:
        clean = _clean(event, fields)
    except (KeyError, ValueError):
        return False
    path = path or default_path()
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    try:
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            line = {
                "at": round(clock(), 3),
                "user": user[:MAX_FIELD],
                "event": event,
                **clean,
                "prev": _last_hash(path),
            }
            with path.open("ab") as handle:
                handle.write(json.dumps(line, sort_keys=True).encode("utf-8") + b"\n")
        return True
    except Exception:  # an audit failure never stops the user's work
        return False


def verify(path: Path | None = None) -> tuple[bool, int, int | None]:
    """(intact, lines read, first broken line number or None)."""

    path = path or default_path()
    try:
        lines = path.read_bytes().splitlines()
    except FileNotFoundError:
        return True, 0, None
    prev = GENESIS
    for number, raw in enumerate(lines, start=1):
        try:
            entry = json.loads(raw)
        except ValueError:
            return False, len(lines), number
        if entry.get("prev") != prev or entry.get("event") not in EVENTS:
            return False, len(lines), number
        prev = hashlib.sha256(raw).hexdigest()
    return True, len(lines), None


def export(dest: Path, path: Path | None = None) -> tuple[bool, int, int | None]:
    """Copy the log for the owner, with the result of verifying it."""

    path = path or default_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copyfile(path, dest)
    else:
        dest.write_bytes(b"")
    return verify(dest)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["verify"]:
        ok, n, bad = verify()
        print(f"{n} event(s); " + ("chain intact" if ok else f"broken at line {bad}"))
        return 0 if ok else 1
    if argv[:1] == ["export"] and len(argv) == 2:
        ok, n, bad = export(Path(argv[1]))
        print(
            f"exported {n} event(s) to {argv[1]}; "
            + ("chain intact" if ok else f"broken at line {bad}")
        )
        return 0 if ok else 1
    print("usage: python -m ghostcursor.audit verify | export <file>")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
