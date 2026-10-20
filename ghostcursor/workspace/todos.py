"""A tiny per-workspace checklist (D186): jot tasks, tick them off.

One JSON file under the workspace root. Local only; no sync, no model. Ids are
small integers stable within a workspace so `/todo done 3` keeps meaning the
same item. Done items stay (struck through) until removed, so a checklist reads
as a record of what got done, not just what's left.
"""

from __future__ import annotations

import json
from pathlib import Path

MAX_TEXT = 500


def _store(root: Path) -> Path:
    return Path(root) / "todos.json"


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
    _store(root).write_text(
        json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n"
    )


def add(root: Path, text: str) -> int:
    text = " ".join(str(text).split())[:MAX_TEXT]
    if not text:
        raise ValueError("a todo needs some text")
    items = _load(root)
    tid = max((i["id"] for i in items), default=0) + 1
    items.append({"id": tid, "text": text, "done": False})
    _save(root, items)
    return tid


def mark(root: Path, tid: int, done: bool = True) -> bool:
    items = _load(root)
    for item in items:
        if item["id"] == tid:
            item["done"] = done
            _save(root, items)
            return True
    return False


def remove(root: Path, tid: int) -> bool:
    items = _load(root)
    kept = [i for i in items if i["id"] != tid]
    if len(kept) == len(items):
        return False
    _save(root, kept)
    return True


def clear_done(root: Path) -> int:
    """Remove every done item; return how many were cleared."""

    kept = [i for i in _load(root) if not i.get("done")]
    cleared = len(_load(root)) - len(kept)
    if cleared:
        _save(root, kept)
    return cleared


def items(root: Path) -> list[tuple[int, bool, str]]:
    return [(i["id"], bool(i["done"]), i["text"]) for i in _load(root)]


def render(root: Path) -> str:
    rows = items(root)
    if not rows:
        return "(no todos -- /todo add <task>)"
    return "\n".join(
        f"  {tid}. [{'x' if done else ' '}] {text}" for tid, done, text in rows
    )


if __name__ == "__main__":  # ponytail: ids stable, mark/remove, render
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        a = add(r, "write the deck")
        b = add(r, "email the team")
        assert (a, b) == (1, 2)
        assert mark(r, 1) and not mark(r, 99)
        assert items(r) == [(1, True, "write the deck"), (2, False, "email the team")]
        assert "[x] write the deck" in render(r)
        assert remove(r, 1) and not remove(r, 1)
        assert add(r, "third") == 3  # ids keep climbing, not reused
        try:
            add(r, "  ")
            raise SystemExit("empty must raise")
        except ValueError:
            pass
    print("todos ok")
