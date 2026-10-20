"""DeckSpec -> Act build (D186): build_deck PROPOSES a plan to build a reviewed
deck in PowerPoint; it NEVER acts. The user approves and runs /act.

The safety property under test: build_deck sets a plan proposal and returns a
message pointing at /act -- it dispatches no Act, synthesises no input, and
mints no authority. The actual build goes through the existing gated Act path
(observed controls, approval, deny-list, ESC), which is unchanged here.
"""

from __future__ import annotations

import json

from ghostcursor.providers import ExpectedChange, PlanStep, TeachPlan
from ghostcursor.providers.errors import FailureKind, ProviderError
from ghostcursor.workspace.brain import Brain
from ghostcursor.workspace.session import Workspace

DECK = {
    "title": "Platform Review",
    "slides": [
        {"title": "Platform Review", "bullets": [], "layout": "title"},
        {"title": "Wins", "bullets": ["Shipped DLP"], "layout": "bullets"},
    ],
}

BUILD_PLAN = TeachPlan(
    (
        PlanStep("Insert a new slide", ExpectedChange.CHOSEN_STATE_CHANGES),
        PlanStep(
            "Type the title",
            ExpectedChange.CHOSEN_STATE_CHANGES,
            action="type",
            text="x",
        ),
    )
)


class DeckGateway:
    """Answers deck planning on complete() and build planning on plan()."""

    def __init__(self, plan_fails=False):
        self.plan_fails = plan_fails

    def complete(self, envelope, system, schema, parse, **kw):
        return parse(json.dumps(DECK))

    def plan(self, envelope, **kw):
        if self.plan_fails:
            raise ProviderError(FailureKind.UNAVAILABLE, "no model")
        return BUILD_PLAN


def test_build_deck_proposes_a_plan_and_does_not_act(tmp_path):
    brain = Brain(tmp_path / "b.sqlite")
    ws = Workspace("deck", DeckGateway(), brain, root=tmp_path / "briefs")
    deck, message = ws.build_deck("quarter review in PowerPoint")

    assert deck.title == "Platform Review"
    # a plan was PROPOSED (so /act can run it) -- but build_deck itself acted on nothing
    assert ws.proposal is not None and ws.plan is BUILD_PLAN
    assert "/act 1" in message and "ESC stops" in message
    brain.close()


def test_build_deck_without_a_build_planner_still_returns_the_deck(tmp_path):
    brain = Brain(tmp_path / "b.sqlite")
    ws = Workspace(
        "deck", DeckGateway(plan_fails=True), brain, root=tmp_path / "briefs"
    )
    deck, message = ws.build_deck("quarter review")

    assert deck.title == "Platform Review"
    assert ws.proposal is None  # nothing proposed -> nothing to /act
    assert "could not plan its build" in message
    brain.close()


def test_build_deck_reports_when_no_model_plans_the_deck(tmp_path):
    class NoDeck:
        def complete(self, *a, **k):
            raise ProviderError(FailureKind.UNAVAILABLE, "no model")

        def plan(self, *a, **k):
            raise AssertionError("must not plan a build with no deck")

    brain = Brain(tmp_path / "b.sqlite")
    ws = Workspace("deck", NoDeck(), brain, root=tmp_path / "briefs")
    deck, message = ws.build_deck("x")
    assert deck is None and "No deck" in message
    brain.close()
