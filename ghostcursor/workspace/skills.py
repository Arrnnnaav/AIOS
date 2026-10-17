"""Per-app guide files for the planner (D182; the Skills pattern Anthropic,
Gemini and HeyClicky all ship). Each ``skills/<name>.md`` starts with a
``triggers:`` line of comma-separated keywords; a goal that mentions one pulls
that guide into the plan request as trusted, author-controlled guidance --
never screen text, never model output.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).with_name("skills")
MAX_SKILLS = 2  # keep the plan request small; the person pays for it


@lru_cache(maxsize=1)
def _loaded() -> tuple[tuple[str, frozenset[str], str], ...]:
    out = []
    for path in sorted(_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        match = re.search(r"(?m)^triggers:\s*(.+)$", text)
        triggers = frozenset(
            t.strip().casefold()
            for t in (match.group(1) if match else "").split(",")
            if t.strip()
        )
        body = re.sub(r"(?s)^---.*?---\s*", "", text).strip()
        if triggers and body:
            out.append((path.stem, triggers, body))
    return tuple(out)


def relevant(goal: str) -> list[tuple[str, str]]:
    """``(name, body)`` for each skill whose trigger words appear in ``goal``,
    the best matches first, at most ``MAX_SKILLS``. Word-boundary matched so
    "cell" does not fire on "excellent"."""

    low = goal.casefold()
    words = set(re.findall(r"[a-z0-9]+", low))
    scored = []
    for name, triggers, body in _loaded():
        # single words match whole words; multi-word triggers match as a phrase
        hits = sum(
            1
            for t in triggers
            if (t in words if " " not in t else re.search(rf"\b{re.escape(t)}\b", low))
        )
        if hits:
            scored.append((hits, name, body))
    scored.sort(key=lambda s: -s[0])
    return [(name, body) for _, name, body in scored[:MAX_SKILLS]]
