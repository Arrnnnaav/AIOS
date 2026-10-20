"""Per-workspace checklist (D186): add / mark / remove, ids stable, local JSON."""

from __future__ import annotations

import pytest

from ghostcursor.workspace import todos


def test_ids_climb_and_mark_and_remove(tmp_path):
    a = todos.add(tmp_path, "write the deck")
    b = todos.add(tmp_path, "email the team")
    assert (a, b) == (1, 2)
    assert todos.mark(tmp_path, 1) and not todos.mark(tmp_path, 99)
    assert todos.items(tmp_path) == [
        (1, True, "write the deck"),
        (2, False, "email the team"),
    ]
    assert todos.remove(tmp_path, 1) and not todos.remove(tmp_path, 1)
    assert todos.add(tmp_path, "third") == 3  # ids are not reused


def test_render_and_empty_text(tmp_path):
    assert "no todos" in todos.render(tmp_path)
    todos.add(tmp_path, "ship it")
    assert "[ ] ship it" in todos.render(tmp_path)
    todos.mark(tmp_path, 1)
    assert "[x] ship it" in todos.render(tmp_path)
    with pytest.raises(ValueError):
        todos.add(tmp_path, "   ")
