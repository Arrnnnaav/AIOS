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

import atexit
import getpass
import hashlib
import json
import ntpath
import os
import queue
import shutil
import sys
import threading
import time
from pathlib import Path

#: event -> the only fields it may carry.
EVENTS = {
    "plan_approved": {"via", "steps", "app", "plugin"},
    "act_step": {"via", "action", "control_type", "app", "outcome"},
    "act_run": {"via", "plugin", "app", "code", "completed", "steps"},
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


def _locked(path: Path):
    """An exclusive lock shared with every Orbyn process on this PC, so two
    writers never read the same ``prev`` and look like tampering."""

    import contextlib
    import msvcrt

    @contextlib.contextmanager
    def held():
        with path.with_name(path.name + ".lock").open("a+b") as handle:
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)  # retries ~10 s
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    return held()


def _write(path: Path, entry: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _locked(path):  # never _lock: record() must not wait behind a slow disk
            line = {**entry, "prev": _last_hash(path)}
            with path.open("ab") as handle:
                handle.write(json.dumps(line, sort_keys=True).encode("utf-8") + b"\n")
    except Exception:  # an audit failure never stops the user's work
        global dropped
        dropped += 1


#: Lines that could not be written (disk full, folder gone), for doctor.
dropped = 0
#: Bounded: a writer stuck on a dead disk must not grow memory without end.
_queue: "queue.Queue[tuple[Path, dict] | None]" = queue.Queue(maxsize=10_000)
_writer: threading.Thread | None = None
#: Lines queued but not yet written, per file, so verify waits only for its own.
_pending: dict[Path, int] = {}


def _drain() -> None:
    while True:
        item = _queue.get()
        try:
            if item is not None:
                _write(*item)
        finally:
            if item is not None:
                with _lock:
                    _pending[item[0]] = _pending.get(item[0], 1) - 1
            _queue.task_done()


def flush(timeout_s: float = 2.0) -> bool:
    """Wait until queued lines are on disk (tests, export, exit)."""

    deadline = time.monotonic() + timeout_s
    while _queue.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.005)
    return not _queue.unfinished_tasks


def record(event: str, *, path: Path | None = None, clock=time.time, **fields) -> bool:
    """Queue one event; False if it was refused (an unknown event or field, so
    content cannot slip in). The write happens on a writer thread, so a step
    or Stop never waits on the disk (rule 4); never raises."""

    global _writer
    try:
        clean = _clean(event, fields)
    except (KeyError, ValueError):
        return False
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    entry = {"at": round(clock(), 3), "user": user[:MAX_FIELD], "event": event, **clean}
    try:
        with _lock:
            if _writer is None or not _writer.is_alive():
                # Daemon, with an exit flush below: a stuck disk must not keep
                # the process alive after the user closed Orbyn.
                _writer = threading.Thread(
                    target=_drain, name="audit-writer", daemon=True
                )
                _writer.start()
        target = path or default_path()
        _queue.put_nowait((target, entry))
        with _lock:
            _pending[target] = _pending.get(target, 0) + 1
        return True
    except queue.Full:
        global dropped
        dropped += 1
        return False
    except Exception:
        return False


def _at_exit() -> None:
    """Give queued lines a moment at exit; count any that never landed."""

    global dropped
    if not flush():
        dropped += _queue.unfinished_tasks


atexit.register(_at_exit)


def verify(path: Path | None = None) -> tuple[bool, int, int | None]:
    """(intact, lines read, first broken line number or None)."""

    path = path or default_path()
    if _pending.get(path):
        flush()  # lines this process queued for this file land first
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
        if not isinstance(entry, dict) or entry.get("prev") != prev or entry.get("event") not in EVENTS:
            return False, len(lines), number
        prev = hashlib.sha256(raw).hexdigest()
    return True, len(lines), None


def export(dest: Path, path: Path | None = None) -> tuple[bool, int, int | None]:
    """Copy the log for the owner, with the result of verifying it."""

    flush()
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
