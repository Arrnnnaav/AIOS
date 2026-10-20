"""Unified find across saved stores (D186): snippets, crews, agents, skills.

Pins the matching (substring + close fuzzy) and that find reads the real stores
under a tmp root and returns (kind, name) pairs. Skills live in a default dir,
so the test only asserts on the stores it writes under root.
"""

from __future__ import annotations

from ghostcursor.workspace import crew, library, snippets


def test_find_matches_snippets_and_crews(tmp_path):
    snippets.save(tmp_path, "pitch-intro", "Hello investors")
    snippets.save(tmp_path, "weekly-sync", "notes")
    crew.save_crew(tmp_path, "pitch-builder", (("research", "market"),))

    hits = dict((name, kind) for kind, name in library.find(tmp_path, "pitch"))
    assert hits.get("pitch-intro") == "snippet"
    assert hits.get("pitch-builder") == "crew"
    assert "weekly-sync" not in hits  # does not match


def test_find_is_fuzzy_and_empty_query_returns_nothing(tmp_path):
    snippets.save(tmp_path, "invoice", "...")
    names = [n for _k, n in library.find(tmp_path, "invoce")]  # one transposition
    assert "invoice" in names
    assert library.find(tmp_path, "   ") == []
