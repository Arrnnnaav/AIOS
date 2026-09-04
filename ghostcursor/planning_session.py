"""Ask until the model knows enough to plan, then stop asking.

One planning round returns a question or a plan (`task_planner`). This is the
loop around that: put the answers into the brief, ask again, and stop when
either a plan arrives or the round budget runs out.

**The answers go into the brief, not into a variable.** That is what makes
the conversation survive the session. The brief is appended to, so the next
round reads the whole exchange rather than a summary of it, and a plan
proposed three rounds later still binds one specific byte sequence covering
everything that was said (D113).

**The loop is bounded, and running out is not a plan.** A model that keeps
asking gets stopped, and the caller is told it was stopped. Returning the
last clarification as though it were an answer, or an empty plan as though
the questions had been resolved, would both report progress that did not
happen.

**Nothing here decides anything about the application.** It moves text
between a file and a model and applies the same validator every round. No
capability, selector or parameter originates in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ghostcursor.brief import append_turn, load_brief
from ghostcursor.task_planner import ClarificationRequired, TaskGraphProposal

#: Most rounds one session may spend before it stops asking. Four questions a
#: round, three rounds: past that the conversation is not converging and a
#: person is better served by being told so than by being asked again.
MAX_PLANNING_ROUNDS = 3


class PlanningExhausted(RuntimeError):
    """The budget ran out with the model still asking.

    Carries the last questions so a caller can show them, and is an exception
    rather than a returned value so no caller can mistake it for a plan.
    """

    def __init__(self, rounds: int, questions: tuple[str, ...]) -> None:
        super().__init__(
            f"still asking after {rounds} rounds; the conversation is not "
            "converging on something that can be planned"
        )
        self.rounds = rounds
        self.questions = questions


@dataclass(frozen=True)
class PlanningRound:
    """What one round asked and what came back, for the record."""

    index: int
    questions: tuple[str, ...]
    answered: bool


def plan_from_brief(
    topic: str,
    plugin_id: str,
    goal: str,
    *,
    brief_root: Path,
    answer: Callable[[tuple[str, ...]], str | None],
    propose: Callable[..., object],
    initial_facts: tuple[str, ...] = (),
    max_rounds: int = MAX_PLANNING_ROUNDS,
) -> tuple[TaskGraphProposal, tuple[PlanningRound, ...]]:
    """Converse until there is a plan, appending every exchange to the brief.

    ``answer`` is handed the questions and returns the person's reply, or
    None to give up. Injected rather than read from a console so the loop can
    be tested without one, and so a caller can put the questions on any
    surface it likes.

    ``propose`` is the planning round — `task_planner.propose_task_graph` in
    production. Injected for the same reason.

    ``goal`` is required rather than derived from the brief. Deriving it
    would mean this module deciding which sentence of a conversation is the
    request, which is exactly the kind of judgement that belongs to the
    person or the model, not to the loop between them.
    """

    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("a planning session needs a goal")

    if (
        not isinstance(max_rounds, int)
        or isinstance(max_rounds, bool)
        or max_rounds < 1
    ):
        raise ValueError("a planning session needs at least one round")

    from ghostcursor.brief import brief_path

    rounds: list[PlanningRound] = []
    for index in range(1, max_rounds + 1):
        brief = load_brief(brief_path(Path(brief_root), topic))
        # The GOAL is a short request; the BRIEF is the conversation around
        # it. Passing the brief text as the goal looked tidy and was wrong:
        # a goal is capped at 1024 characters, `idea.txt` alone is 10 831,
        # and every real multi-turn brief would have been refused before it
        # reached the model (D032 review, 4 September 2026).
        outcome = propose(
            goal,
            plugin_id,
            initial_facts=initial_facts,
            brief=brief,
        )
        if isinstance(outcome, TaskGraphProposal):
            return outcome, tuple(rounds)
        if not isinstance(outcome, ClarificationRequired):
            raise TypeError(
                "a planning round must return a proposal or a clarification, "
                f"not {type(outcome).__name__}"
            )

        # The question is recorded before the answer, so a brief read later
        # shows what was asked even if nobody answered it.
        append_turn(
            Path(brief_root),
            topic,
            "assistant",
            "\n".join(f"- {question}" for question in outcome.questions),
        )
        reply = answer(outcome.questions)
        rounds.append(
            PlanningRound(
                index=index,
                questions=outcome.questions,
                answered=bool(reply and reply.strip()),
            )
        )
        if not reply or not reply.strip():
            # Giving up is a real outcome and is reported as one. Proceeding
            # with unanswered questions would plan from information the model
            # said it did not have.
            raise PlanningExhausted(index, outcome.questions)
        append_turn(Path(brief_root), topic, "user", reply)

    last = rounds[-1].questions if rounds else ()
    raise PlanningExhausted(len(rounds), last)


__all__ = [
    "MAX_PLANNING_ROUNDS",
    "PlanningExhausted",
    "PlanningRound",
    "plan_from_brief",
]
