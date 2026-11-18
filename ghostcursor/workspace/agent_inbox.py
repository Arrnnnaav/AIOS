"""Goals another agent suggests, waiting for the person (MCP ``suggest_goal``).

The agent server and the app are separate processes, so suggestions pass
through one small file under %LOCALAPPDATA%\\GhostCursor, sealed to this
Windows account like the Brain. A suggestion never starts anything: the page
shows it, and only the person can put it in the message box, where it is read,
planned and approved like anything they type. At most ``MAX_WAITING`` wait.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path

MAX_WAITING, MAX_GOAL, MAX_WHY = 10, 300, 200
_lock = threading.Lock()


def _path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "GhostCursor" / "agent-goals.sealed"


def _read(path: Path) -> list[dict]:
    from ghostcursor.workspace.brain import LOCKED, _unseal

    try:
        text = _unseal(path.read_text(encoding="ascii"))
    except (OSError, ValueError):
        return []
    if text == LOCKED:
        return []
    try:
        rows = json.loads(text)
    except ValueError:
        return []
    return (
        [r for r in rows if isinstance(r, dict) and isinstance(r.get("id"), str)]
        if isinstance(rows, list)
        else []
    )


def _write(path: Path, rows: list[dict]) -> None:
    from ghostcursor.workspace.brain import _seal

    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(_seal(json.dumps(rows)), encoding="ascii")
    temp.replace(path)


def suggest(
    goal: str, why: str, source: str, *, path: Path | None = None, clock=time.time
) -> str:
    """Add one suggestion; returns its id. Raises ValueError when it is out of
    shape or too many are waiting."""

    goal, why = " ".join(str(goal).split()), " ".join(str(why).split())
    if not goal or len(goal) > MAX_GOAL:
        raise ValueError("goal must be 1 to 300 characters")
    if len(why) > MAX_WHY:
        raise ValueError("why must be at most 200 characters")
    path = path or _path()
    with _lock:
        rows = _read(path)
        if len(rows) >= MAX_WAITING:
            raise ValueError("too many suggestions are waiting for the person")
        if any(r.get("goal", "").casefold() == goal.casefold() for r in rows):
            raise ValueError("that goal is already waiting")
        row = {
            "id": secrets.token_hex(6),
            "goal": goal,
            "why": why,
            "source": source[:80],
            "at": round(clock(), 1),
        }
        _write(path, rows + [row])
    return row["id"]


def waiting(*, path: Path | None = None) -> list[dict]:
    return _read(path or _path())


def take(sid: str, *, path: Path | None = None) -> dict | None:
    """Remove one suggestion and return it (None if it is gone)."""

    path = path or _path()
    with _lock:
        rows = _read(path)
        found = next((r for r in rows if r.get("id") == sid), None)
        if found is not None:
            _write(path, [r for r in rows if r is not found])
    return found
