"""Local unified diff (D186): stdlib, nothing uploaded."""

from __future__ import annotations

from ghostcursor.workspace import diffs


def test_unified_shows_changes_and_headers():
    out = diffs.unified("one\ntwo\nthree", "one\n2\nthree", "old", "new")
    assert "--- old" in out and "+++ new" in out
    assert "-two" in out and "+2" in out


def test_identical_is_flagged():
    assert diffs.unified("same\ntext", "same\ntext") == "(identical)"
