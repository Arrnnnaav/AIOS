"""Startup status line (D186): a one-line reminder of what's waiting, shown
once when a workspace opens. Empty when nothing is saved."""

from __future__ import annotations

from ghostcursor.workspace import crew, snippets, todos
from ghostcursor.workspace.__main__ import _startup_status


def test_empty_workspace_has_no_status(tmp_path):
    assert _startup_status(tmp_path) == ""


def test_status_counts_pending_todos_snippets_and_crews(tmp_path):
    todos.add(tmp_path, "a")
    done = todos.add(tmp_path, "b")
    todos.mark(tmp_path, done)  # done items are not counted as pending
    snippets.save(tmp_path, "sig", "text")
    crew.save_crew(tmp_path, "pitch", (("research", "x"),))

    status = _startup_status(tmp_path)
    assert "1 todo to do" in status  # only the one still pending
    assert "1 snippet" in status
    assert "1 saved crew" in status
