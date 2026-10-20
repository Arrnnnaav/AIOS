"""Recurring-use learning (D186): offer to save a repeated task, once.

Pins the behaviour that matters: the offer fires exactly at the threshold
(timely, not naggy), normalises so trivial differences still match, ignores
blanks, and -- the privacy point -- keeps nothing but in-memory counts.
"""

from __future__ import annotations

from ghostcursor.workspace.usage import Usage


def test_offer_fires_once_at_the_threshold():
    u = Usage(suggest_at=2)
    assert u.nudge("open the report") is None  # 1st: quiet
    offer = u.nudge("Open the   report")  # 2nd (normalised): offer
    assert offer and "/skill from" in offer
    assert u.nudge("open the report") is None  # 3rd: no nagging


def test_crew_wording_and_blanks():
    assert "crew save" in Usage(suggest_at=1).nudge("build a pitch", kind="crew")
    u = Usage()
    assert u.record("") == 0
    assert u.nudge("   ") is None


def test_counts_are_independent_per_task():
    u = Usage(suggest_at=2)
    u.record("task a")
    assert u.nudge("task b") is None  # different task, still first time
    assert u.nudge("task a") is not None  # task a now at 2
