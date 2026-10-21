"""Plan critique (D186): advisory review before Act. Strict parse; scrubs
secrets; never blocks.
"""

from __future__ import annotations

import json

import pytest

from ghostcursor.providers import ExpectedChange, PlanStep, TeachPlan
from ghostcursor.providers.errors import FailureKind, ProviderError
from ghostcursor.providers.schemas import parse_critique
from ghostcursor.workspace.brain import Brain
from ghostcursor.workspace.session import Workspace


def test_parse_critique_is_strict():
    c = parse_critique('{"verdict": "caution", "concerns": ["step 2 deletes a file"]}')
    assert c.verdict == "caution" and c.concerns == ("step 2 deletes a file",)
    for bad in (
        '{"verdict": "maybe", "concerns": []}',  # bad verdict
        '{"verdict": "ready"}',  # missing concerns
        '{"verdict": "ready", "concerns": "x"}',  # wrong type
    ):
        with pytest.raises(ProviderError):
            parse_critique(bad)


class CriticGateway:
    def __init__(self, fail=False):
        self.fail = fail
        self.envelopes = []

    def complete(self, envelope, system, schema, parse, **kw):
        self.envelopes.append(envelope)
        if self.fail:
            raise ProviderError(FailureKind.UNAVAILABLE, "no model")
        return parse(json.dumps({"verdict": "caution", "concerns": ["looks risky"]}))


def test_critique_scrubs_secrets_and_renders(tmp_path):
    brain = Brain(tmp_path / "b.sqlite")
    gw = CriticGateway()
    ws = Workspace("c", gw, brain, root=tmp_path / "br")
    assert "no plan" in ws.critique()  # none yet

    ws._propose(
        TeachPlan(
            (
                PlanStep(
                    "Send using token AKIA1234567890ABCDEF",
                    ExpectedChange.TITLE_CHANGES,
                ),
            )
        )
    )
    out = ws.critique()
    assert "caution" in out and "looks risky" in out
    sent = gw.envelopes[0].trusted["plan"][0]
    assert "AKIA1234567890ABCDEF" not in sent  # scrubbed before the model
    brain.close()


def test_critique_handles_no_model(tmp_path):
    brain = Brain(tmp_path / "b.sqlite")
    ws = Workspace("c", CriticGateway(fail=True), brain, root=tmp_path / "br")
    ws._propose(TeachPlan((PlanStep("Open the deck", ExpectedChange.TITLE_CHANGES),)))
    assert "not available" in ws.critique()
    brain.close()
