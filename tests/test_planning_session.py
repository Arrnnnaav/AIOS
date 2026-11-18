"""Asking until there is a plan, and stopping when there will not be one.

The failure this guards against is reporting progress that did not happen:
a clarification returned as though it were an answer, an empty plan as though
the questions had been resolved, or a plan built from information the model
said it did not have.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ghostcursor.brief import append_turn, brief_path, load_brief
from ghostcursor.planning_session import (
    MAX_PLANNING_ROUNDS,
    PlanningExhausted,
    plan_from_brief,
)
from ghostcursor.task_planner import ClarificationRequired, TaskGraphProposal


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "briefs"
    append_turn(folder, "deck", "user", "Build me a deck.")
    return folder


def _clarify(*questions):
    return ClarificationRequired(
        questions=tuple(questions),
        summary="need more",
        generation=SimpleNamespace(payload={}),
    )


def _plan():
    return TaskGraphProposal(
        graph=SimpleNamespace(nodes=()),
        validated=SimpleNamespace(ordered_nodes=()),
        summary="a plan",
        generation=SimpleNamespace(payload={}),
        steps=(),
    )


def _proposer(*outcomes):
    """Returns a proposer yielding one outcome per round, recording the brief
    text it was given each time."""

    seen = []
    remaining = list(outcomes)

    def propose(goal, plugin_id, *, initial_facts=(), brief=None):
        seen.append(brief.text if brief is not None else goal)
        return remaining.pop(0)

    propose.seen = seen
    return propose


# --- the conversation converges --------------------------------------------


def test_a_plan_on_the_first_round_asks_nothing(root):
    proposal, rounds = plan_from_brief(
        "deck",
        "p",
        "Build a deck.",
        brief_root=root,
        answer=lambda q: pytest.fail("must not ask"),
        propose=_proposer(_plan()),
    )

    assert isinstance(proposal, TaskGraphProposal)
    assert rounds == ()


def test_answers_are_appended_to_the_brief_and_reach_the_next_round(root):
    """The answers go into the brief, not into a variable. That is what makes
    the conversation survive the session, and what lets a plan proposed three
    rounds later bind one byte sequence covering everything said."""

    propose = _proposer(_clarify("Who is the audience?"), _plan())

    plan_from_brief(
        "deck",
        "p",
        "Build a deck.",
        brief_root=root,
        answer=lambda q: "Seed investors.",
        propose=propose,
    )

    assert "Seed investors." not in propose.seen[0]
    assert "Seed investors." in propose.seen[1]
    assert "Who is the audience?" in propose.seen[1]


def test_the_question_is_recorded_even_when_nobody_answers(root):
    """A brief read later must show what was asked, or the record shows a
    conversation that jumped."""

    with pytest.raises(PlanningExhausted):
        plan_from_brief(
            "deck",
            "p",
            "Build a deck.",
            brief_root=root,
            answer=lambda q: None,
            propose=_proposer(_clarify("Who is the audience?")),
        )

    text = load_brief(brief_path(root, "deck")).text
    assert "Who is the audience?" in text


def test_several_rounds_accumulate_in_order(root):
    propose = _proposer(_clarify("One?"), _clarify("Two?"), _plan())
    answers = iter(["first answer", "second answer"])

    _proposal, rounds = plan_from_brief(
        "deck",
        "p",
        "Build a deck.",
        brief_root=root,
        answer=lambda q: next(answers),
        propose=propose,
    )

    assert [r.index for r in rounds] == [1, 2]
    assert [r.questions for r in rounds] == [("One?",), ("Two?",)]
    assert all(r.answered for r in rounds)
    text = load_brief(brief_path(root, "deck")).text
    assert text.index("first answer") < text.index("second answer")


# --- running out is not a plan --------------------------------------------


def test_exhausting_the_rounds_raises_rather_than_returning_anything(root):
    """Returning the last clarification as though it were an answer, or an
    empty plan as though the questions had been resolved, would both report
    progress that did not happen."""

    propose = _proposer(_clarify("a?"), _clarify("b?"), _clarify("c?"))

    with pytest.raises(PlanningExhausted) as raised:
        plan_from_brief(
            "deck",
            "p",
            "Build a deck.",
            brief_root=root,
            answer=lambda q: "still vague",
            propose=propose,
            max_rounds=3,
        )

    assert raised.value.rounds == 3
    assert raised.value.questions == ("c?",)


def test_giving_up_stops_immediately_and_says_so(root):
    """Proceeding with unanswered questions would plan from information the
    model said it did not have."""

    propose = _proposer(_clarify("Who?"), _plan())

    with pytest.raises(PlanningExhausted) as raised:
        plan_from_brief(
            "deck",
            "p",
            "Build a deck.",
            brief_root=root,
            answer=lambda q: None,
            propose=propose,
        )

    assert raised.value.rounds == 1
    assert len(propose.seen) == 1, "the second round must not have run"


@pytest.mark.parametrize("reply", ["", "   ", "\n", None])
def test_an_empty_answer_counts_as_giving_up(root, reply):
    with pytest.raises(PlanningExhausted):
        plan_from_brief(
            "deck",
            "p",
            "Build a deck.",
            brief_root=root,
            answer=lambda q: reply,
            propose=_proposer(_clarify("Who?")),
        )


def test_exhaustion_is_an_exception_not_a_return_value():
    """So no caller can mistake it for a plan by forgetting to check a flag."""

    assert issubclass(PlanningExhausted, Exception)


# --- the loop decides nothing about the application -----------------------


def test_the_brief_text_is_what_the_model_is_asked_about(root):
    """Not a summary of it. A summary would be this module deciding what
    mattered in the conversation."""

    propose = _proposer(_plan())

    plan_from_brief("deck", "p", "Build a deck.", brief_root=root, answer=lambda q: "x", propose=propose)

    assert propose.seen[0] == load_brief(brief_path(root, "deck")).text


def test_the_brief_is_re_read_every_round(root):
    """Not cached. The file is the conversation, and a cached copy would make
    the second round plan from a brief that no longer exists."""

    propose = _proposer(_clarify("Who?"), _plan())

    plan_from_brief(
        "deck",
        "p",
        "Build a deck.",
        brief_root=root,
        answer=lambda q: "Seed investors.",
        propose=propose,
    )

    assert propose.seen[0] != propose.seen[1]


def test_an_unexpected_outcome_type_is_refused(root):
    with pytest.raises(TypeError, match="proposal or a clarification"):
        plan_from_brief(
            "deck",
            "p",
            "Build a deck.",
            brief_root=root,
            answer=lambda q: "x",
            propose=_proposer({"nodes": []}),
        )


@pytest.mark.parametrize("rounds", [0, -1, True, 1.5])
def test_a_malformed_round_budget_is_refused(root, rounds):
    with pytest.raises(ValueError, match="at least one round"):
        plan_from_brief(
            "deck",
            "p",
            "Build a deck.",
            brief_root=root,
            answer=lambda q: "x",
            propose=_proposer(_plan()),
            max_rounds=rounds,
        )


def test_the_round_budget_is_small_enough_that_a_person_finishes():
    """Four questions a round, three rounds. Past that the conversation is
    not converging and a person is better served by being told so."""

    assert 1 <= MAX_PLANNING_ROUNDS <= 5


def test_the_goal_is_short_and_the_brief_is_the_context(root):
    """The D032 review found the brief text being passed AS the goal. A goal
    is capped at 1024 characters and `idea.txt` alone is 10 831, so every
    real multi-turn brief would have been refused before reaching the
    model."""

    from ghostcursor.task_planner import MAX_TASK_GOAL_CHARS

    propose = _proposer(_plan())

    plan_from_brief(
        "deck", "p", "Build an investor deck.", brief_root=root,
        answer=lambda q: "x", propose=propose,
    )

    # `_proposer` records the BRIEF it was handed, which stays whole...
    assert "Build me a deck." in propose.seen[0]
    # ...and the goal it was called with is short enough to be accepted.
    assert len("Build an investor deck.") < MAX_TASK_GOAL_CHARS


@pytest.mark.parametrize("goal", ["", "   ", None, 7])
def test_a_missing_goal_is_refused(root, goal):
    with pytest.raises(ValueError, match="needs a goal"):
        plan_from_brief(
            "deck", "p", goal, brief_root=root,
            answer=lambda q: "x", propose=_proposer(_plan()),
        )



def test_the_last_round_does_not_ask_a_question_it_cannot_use(root):
    asked = []
    with pytest.raises(PlanningExhausted) as raised:
        plan_from_brief(
            "deck",
            "p",
            "Build a deck.",
            brief_root=root,
            answer=lambda q: asked.append(q) or "still vague",
            propose=_proposer(_clarify("a?"), _clarify("b?")),
            max_rounds=2,
        )
    assert len(asked) == 1  # round 2 gives up instead of taking a reply
    assert raised.value.questions == ("b?",)
