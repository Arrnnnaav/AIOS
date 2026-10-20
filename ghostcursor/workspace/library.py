"""Find across everything you've saved (D186): one query over snippets, crews,
agents and task skills, so a growing library stays discoverable.

Pure and local: it only reads the names each store already lists, matches by
substring or a close fuzzy match, and returns (kind, name) pairs. Each store is
read defensively -- one missing or odd store never breaks the search.
"""

from __future__ import annotations

import difflib
from pathlib import Path


def _matches(name: str, query: str) -> bool:
    low = name.casefold()
    return query in low or bool(difflib.get_close_matches(query, [low], cutoff=0.6))


def _safe(fn):
    try:
        return list(fn())
    except Exception:
        return []


def find(root: Path, query: str) -> list[tuple[str, str]]:
    """(kind, name) for every saved item whose name matches ``query`` (substring
    or close fuzzy), across snippets, crews, agents and task skills."""

    query = " ".join(str(query).split()).casefold()
    if not query:
        return []
    from ghostcursor.workspace import agents, crew, snippets, task_skills

    sources = (
        ("snippet", lambda: snippets.names(root)),
        ("crew", lambda: crew.list_crews(root)),
        ("agent", lambda: [s.name for s in agents.list_specs(root)]),
        ("skill", lambda: task_skills.list_skills()),
    )
    out = []
    for kind, lister in sources:
        for name in _safe(lister):
            if _matches(name, query):
                out.append((kind, name))
    return out


if __name__ == "__main__":  # ponytail: matching logic (store reads need files)
    assert _matches("pitch-builder", "pitch")
    assert _matches("invoice", "invoce")  # fuzzy (one transposition)
    assert not _matches("weekly-sync", "deploy")
    print("library ok")
