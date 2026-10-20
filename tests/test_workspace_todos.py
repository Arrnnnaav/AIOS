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


def test_todos_from_plan_scrubs_and_counts(tmp_path):
    from ghostcursor.providers import ExpectedChange, PlanStep, TeachPlan
    from ghostcursor.workspace.brain import Brain
    from ghostcursor.workspace.session import Workspace

    brain = Brain(tmp_path / "b.sqlite")
    ws = Workspace("p", object(), brain, root=tmp_path / "br")
    assert "no plan" in ws.todos_from_plan()  # none yet

    ws._propose(
        TeachPlan(
            (
                PlanStep("Open the deck", ExpectedChange.TITLE_CHANGES),
                PlanStep(
                    "Paste key AKIA1234567890ABCDEF", ExpectedChange.TITLE_CHANGES
                ),
            )
        )
    )
    msg = ws.todos_from_plan()
    assert "added 2" in msg
    texts = [t for _i, _d, t in todos.items(ws.root)]
    assert "Open the deck" in texts
    assert not any("AKIA1234567890ABCDEF" in t for t in texts)  # scrubbed
    brain.close()


def test_render_and_empty_text(tmp_path):
    assert "no todos" in todos.render(tmp_path)
    todos.add(tmp_path, "ship it")
    assert "[ ] ship it" in todos.render(tmp_path)
    todos.mark(tmp_path, 1)
    assert "[x] ship it" in todos.render(tmp_path)
    with pytest.raises(ValueError):
        todos.add(tmp_path, "   ")
