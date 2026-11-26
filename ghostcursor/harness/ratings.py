"""The person's verdict on each pointer Teach shows ("right control" /
"wrong control"), kept on this computer. Everyday use becomes the counted
live evidence Teach lacked (only offline replays had numbers), and a wrong
verdict makes Teach look again without that control.

Rule 6: no control name, window title or screen text is stored -- only the
app's executable name, the control type, the step number and the verdict.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

VERDICTS = ("right", "wrong")
_LOCK = threading.Lock()


def _path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "GhostCursor" / "teach-ratings.jsonl"


def record(
    verdict: str, *, app: str, control_type: str, step: int, path: Path | None = None
) -> None:
    if verdict not in VERDICTS:
        raise ValueError(f"a verdict is one of {VERDICTS}")
    line = {
        "at": round(time.time()),
        "app": str(app or "").lower()[:80],
        "control_type": str(control_type or "")[:40],
        "step": int(step),
        "verdict": verdict,
    }
    target = path or _path()
    with _LOCK:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(line) + "\n")


def summary(path: Path | None = None) -> dict[str, dict[str, int]]:
    """Per app: how many pointers were rated right and wrong."""

    out: dict[str, dict[str, int]] = {}
    target = path or _path()
    if not target.exists():
        return out
    for raw in target.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(raw)
        except ValueError:
            continue  # a torn line from a crash is skipped, not fatal
        if not isinstance(row, dict) or row.get("verdict") not in VERDICTS:
            continue
        counts = out.setdefault(
            str(row.get("app") or "unknown"), {"right": 0, "wrong": 0}
        )
        counts[row["verdict"]] += 1
    return out
