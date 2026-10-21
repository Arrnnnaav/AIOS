"""Local, off-by-default, events-not-content telemetry (D141).

NOTHING leaves the device (rule 6). This module has NO network dependency of any
kind -- it only increments a count per ALLOWLISTED event NAME in a local file.
It never records content, arguments, text, window titles, paths, identifiers, or
even a timestamp payload -- just name -> count. It is off unless
`policy.telemetry_enabled()` (an opt-in DWORD, default off, off when unreadable).
The counts are for the owner's own local view (e.g. `/stats`); they are never
synced and no code here sends them anywhere.

The event name is checked against a fixed allowlist, so no caller can smuggle
free-text content in through the "event" argument.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

#: The only event names that may be counted. Names only -- never content.
EVENTS = frozenset(
    {
        "teach_run",
        "act_run",
        "deck_made",
        "deck_build_proposed",
        "research_done",
        "crew_run",
        "notes_made",
        "skill_drafted",
        "dictation_saved",
        "convert_done",
        "critique_run",
    }
)


def _default_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "GhostCursor" / "telemetry.json"


def _load(path: Path) -> dict[str, int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: int(v) for k, v in data.items() if k in EVENTS and isinstance(v, int)}


def record(
    event: str, *, path: Path | None = None, enabled: bool | None = None
) -> bool:
    """Count one occurrence of an allowlisted ``event``. No-op (returns False)
    when telemetry is off or the name is not allowlisted. Local only; nothing
    is sent. ``enabled``/``path`` are injectable for tests."""

    from ghostcursor import policy

    if not (policy.telemetry_enabled() if enabled is None else enabled):
        return False
    if event not in EVENTS:
        return False  # names only -- content cannot enter here
    path = path or _default_path()
    counts = _load(path)
    counts[event] = counts.get(event, 0) + 1
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(dict(sorted(counts.items())), indent=1),
            encoding="utf-8",
            newline="\n",
        )
    except OSError:
        return False  # a read-only FS just means no local counts; never fatal
    return True


def counts(path: Path | None = None) -> dict[str, int]:
    """The local event counts (owner's view); empty when none/off."""

    return _load(path or _default_path())


if __name__ == "__main__":  # ponytail: off-by-default, allowlist, local round-trip
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.json"
        assert record("teach_run", path=p, enabled=False) is False  # off -> no-op
        assert record("teach_run", path=p, enabled=True) is True
        assert record("teach_run", path=p, enabled=True) is True
        assert record("not_an_event", path=p, enabled=True) is False  # allowlist
        assert record("rm -rf /; secret", path=p, enabled=True) is False  # no content
        assert counts(p) == {"teach_run": 2}
    print("telemetry ok")
