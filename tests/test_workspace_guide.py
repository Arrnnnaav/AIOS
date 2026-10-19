"""Auto-guide (D186, rec #1): render a plan/observed sequence into a private,
DLP-redacted step-by-step SOP. Data only; secrets never survive the render."""

from __future__ import annotations

import pytest

from ghostcursor.providers import ExpectedChange, PlanStep, TeachPlan
from ghostcursor.workspace.guide import render_guide


def _plan():
    return TeachPlan(
        (
            PlanStep(
                "Open the billing page", ExpectedChange.TITLE_CHANGES, "click", ""
            ),
            PlanStep(
                "Enter the contact email",
                ExpectedChange.CHOSEN_STATE_CHANGES,
                "type",
                "ada@acme.io",
            ),
            PlanStep("Save", ExpectedChange.CHOSEN_DISAPPEARS, "keys", "ctrl+s"),
        )
    )


def test_render_guide_numbers_steps_and_annotates_actions():
    md = render_guide("file an invoice", _plan(), redact_pii=False)
    assert md.startswith("# How to: file an invoice")
    assert "1. Open the billing page" in md
    assert '- Type "ada@acme.io"' in md  # type action annotated with its text
    assert "- Press ctrl+s" in md  # keys action annotated
    # order preserved
    assert (
        md.index("Open the billing") < md.index("Enter the contact") < md.index("Save")
    )


def test_render_guide_redacts_embedded_secrets_by_default():
    md = render_guide("file an invoice", _plan())
    assert "ada@acme.io" not in md  # scrubbed before the guide can be shared
    assert "[EMAIL_1]" in md


def test_render_guide_refuses_an_empty_plan():
    with pytest.raises(ValueError):
        render_guide("x", TeachPlan(()))
