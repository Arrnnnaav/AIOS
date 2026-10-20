"""Workspace Markdown snapshot (D186): goal, plan, todos, saved library.

Pins the sections render and that embedded secrets in a plan step are scrubbed
(same redaction as the guide) before they can land in a shared file.
"""

from __future__ import annotations

from ghostcursor.providers import ExpectedChange, PlanStep, TeachPlan
from ghostcursor.workspace import snippets, todos
from ghostcursor.workspace.brain import Brain
from ghostcursor.workspace.session import Workspace


def test_export_has_sections_and_scrubs_secrets(tmp_path):
    brain = Brain(tmp_path / "b.sqlite")
    ws = Workspace("launch-plan", object(), brain, root=tmp_path / "br")
    ws._propose(
        TeachPlan(
            (
                PlanStep(
                    "Log in with key AKIA1234567890ABCDEF", ExpectedChange.TITLE_CHANGES
                ),
            )
        )
    )
    todos.add(ws.root, "finish the deck")
    snippets.save(ws.root, "sig", "Best, Arnav")

    md = ws.export_md()
    assert "# Workspace: launch-plan" in md
    assert "## Plan" in md and "## Todos" in md and "## Saved" in md
    assert "finish the deck" in md
    assert "sig" in md
    assert "AKIA1234567890ABCDEF" not in md  # secret scrubbed before sharing
    brain.close()


def test_export_handles_an_empty_workspace(tmp_path):
    brain = Brain(tmp_path / "b.sqlite")
    ws = Workspace("empty", object(), brain, root=tmp_path / "br")
    md = ws.export_md()
    assert "_(no plan yet)_" in md and "no todos" in md
    brain.close()
