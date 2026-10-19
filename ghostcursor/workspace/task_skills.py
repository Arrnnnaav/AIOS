"""Record a demonstrated task once, replay it as a reusable skill (D186, rec #2):
Orbyn's safe answer to RPA-by-demonstration (UiPath Autopilot, Power Automate
record, Bardeen). A "task skill" is a saved, named step sequence (a TeachPlan)
the user demonstrated/planned; replaying it feeds the EXISTING gated Teach/Act
path -- observed controls, whole-plan approval, ESC still apply. This module
only SAVES/LOADS/LISTS; it grants no execution authority of its own.

A saved skill is loaded back through the closed parse_teach_plan, so a skill
file that was hand-edited into an out-of-schema or unknown-action shape is
refused rather than replayed.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ghostcursor.providers import TeachPlan, parse_teach_plan


def _dir(dest_dir: Path | None = None) -> Path:
    if dest_dir is not None:
        return dest_dir
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "GhostCursor" / "task-skills"


def _slug(name: str) -> str:
    """A safe filename stem from a skill name -- lowercase, alnum + dash only,
    so a name can never traverse out of the skills directory."""

    slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    if not slug:
        raise ValueError("a skill needs a name with letters or digits")
    return slug


def save_skill(name: str, plan: TeachPlan, *, dest_dir: Path | None = None) -> Path:
    """Persist a TeachPlan under ``name``. Overwrites an existing skill of the
    same slug. Returns the file path."""

    if not getattr(plan, "steps", None):
        raise ValueError("a skill needs at least one step")
    directory = _dir(dest_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "steps": [
            {
                "instruction": s.instruction,
                "expected_change": s.expected_change.value,
                "action": s.action,
                "text": s.text,
            }
            for s in plan.steps
        ]
    }
    path = directory / f"{_slug(name)}.json"
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8", newline="\n")
    return path


def load_skill(name: str, *, dest_dir: Path | None = None) -> TeachPlan | None:
    """Load a saved skill as a validated TeachPlan, or None if absent. The file
    is parsed through the closed parse_teach_plan, so a tampered/out-of-schema
    skill raises ProviderError rather than replaying something unexpected."""

    path = _dir(dest_dir) / f"{_slug(name)}.json"
    if not path.exists():
        return None
    return parse_teach_plan(path.read_text(encoding="utf-8"))


def list_skills(*, dest_dir: Path | None = None) -> list[str]:
    directory = _dir(dest_dir)
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))
