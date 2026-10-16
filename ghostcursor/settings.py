"""The user's own switches, on this machine only (LOCALAPPDATA)."""

from __future__ import annotations

import json
import os
from pathlib import Path


def _path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "GhostCursor" / "settings.json"


def load(path: Path | None = None) -> dict:
    try:
        value = json.loads((path or _path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def jev_vision(path: Path | None = None) -> bool:
    """D179: may Jev see redacted pictures of the windows being guided?
    Off unless the user turned it on; anything but a literal true is off."""

    return load(path).get("jev_vision") is True


def set_jev_vision(on: bool, path: Path | None = None) -> None:
    path = path or _path()
    value = load(path) | {"jev_vision": bool(on)}
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value), encoding="utf-8")
    temp.replace(path)  # never a half-written file
