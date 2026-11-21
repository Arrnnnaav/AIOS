"""Sticky reference notes per workspace (D186): the handful of things you want
in view every time -- a staging URL, a ticket id, who's on call. Unlike todos
(tasks you tick off), a pin is reference you keep until you remove it.

One JSON file under the workspace root. Local only; shown once at startup. Ids
are small integers stable within a workspace so `/pin rm 2` keeps meaning.
"""

from __future__ import annotations

import json
from pathlib import Path
from ghostcursor.workspace import write_atomic

MAX_TEXT = 300
MAX_PINS = 20


def _store(root: Path) -> Path:
    return Path(root) / "pins.json"


def _load(root: Path) -> list[dict]:
    path = _store(root)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _save(root: Path, items: list[dict]) -> None:
    write_atomic(_store(root), json.dumps(items, indent=1, ensure_ascii=False))


def add(root: Path, text: str) -> int:
    text = " ".join(str(text).split())[:MAX_TEXT]
    if not text:
        raise ValueError("a pin needs some text")
    items = _load(root)
    if len(items) >= MAX_PINS:
        raise ValueError(f"too many pins (max {MAX_PINS}); remove one first")
    pid = max((i["id"] for i in items), default=0) + 1
    items.append({"id": pid, "text": text})
    _save(root, items)
    return pid


def remove(root: Path, pid: int) -> bool:
    items = _load(root)
    kept = [i for i in items if i["id"] != pid]
    if len(kept) == len(items):
        return False
    _save(root, kept)
    return True


def items(root: Path) -> list[tuple[int, str]]:
    return [(i["id"], i["text"]) for i in _load(root)]


def render(root: Path) -> str:
    rows = items(root)
    if not rows:
        return "(no pins -- /pin add <note>)"
    return "\n".join(f"  {pid}. {text}" for pid, text in rows)


if __name__ == "__main__":  # ponytail: ids stable, remove, bounds
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        assert add(r, "staging: https://x.test") == 1
        assert add(r, "on-call: Arnav") == 2
        assert remove(r, 1) and not remove(r, 1)
        assert add(r, "third") == 3  # ids keep climbing
        assert [t for _i, t in items(r)] == ["on-call: Arnav", "third"]
        assert "on-call" in render(r)
        try:
            add(r, "  ")
            raise SystemExit("empty must raise")
        except ValueError:
            pass
    print("pins ok")
