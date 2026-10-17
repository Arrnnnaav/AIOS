"""Act on any application (D182): the user approves the whole plan first;
each step is performed once, at the centre of the freshly observed control;
risky controls still wait for the user; nothing acts before approval."""

from __future__ import annotations

import pytest

from ghostcursor.harness import act
from ghostcursor.harness.teach import ACT_SETTLE_S, ModelTeachSession, Phase
from ghostcursor.providers import ExpectedChange, PlanStep, TeachPlan
from ghostcursor.providers.schemas import parse_teach_plan
from tests.test_harness_teach import FakeGateway, SyncSlot, _c, _choice, _frame

E = ExpectedChange


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _session(steps, choices, plan_given=False):
    plan = TeachPlan(tuple(steps))
    done = []
    clock = Clock()
    session = ModelTeachSession(
        "fill the form",
        FakeGateway(plan, choices),
        SyncSlot(),
        clock=clock,
        plan=plan if plan_given else None,
        act=lambda step, target: done.append((step.action, target.name)) or "ok",
    )
    return session, done, clock


def test_nothing_acts_until_the_whole_plan_is_approved():
    session, done, _ = _session(
        [PlanStep("Click Insert", E.CHOSEN_STATE_CHANGES)], [_choice("c1")]
    )
    frame = _frame([_c(1)])
    shown = session.tick(frame)
    assert shown.phase is Phase.APPROVE and "Click Insert" in shown.message
    assert session.tick(frame).phase is Phase.APPROVE and done == []
    acted = session.tick(frame, confirm=True)
    assert acted.phase is Phase.SHOWING and done == [("click", "Insert")]


def test_a_reviewed_plan_still_needs_approval_to_act():
    session, done, _ = _session(
        [PlanStep("Click Insert", E.CHOSEN_STATE_CHANGES)],
        [_choice("c1")],
        plan_given=True,
    )
    assert session.tick(_frame([_c(1)])).phase is Phase.APPROVE and done == []


def test_each_step_acts_once_then_completes_on_change_or_settle():
    session, done, clock = _session(
        [
            PlanStep("Click Insert", E.CHOSEN_STATE_CHANGES),
            PlanStep("Type the title", E.CHOSEN_STATE_CHANGES, "type", "Q3"),
        ],
        [_choice("c1"), _choice("c2")],
    )
    title = _c(2, "Title", "Edit", rect=(10, 100, 200, 130))
    session.tick(_frame([_c(1, state="selected=0"), title]))
    session.tick(_frame([_c(1, state="selected=0"), title]), confirm=True)
    session.tick(_frame([_c(1, state="selected=0"), title]))  # no second click
    assert done == [("click", "Insert")]
    session.tick(_frame([_c(1, state="selected=1"), title], frame_id=2))
    assert session.completed[0] == (1, "observed chosen_state_changes")
    assert done[-1] == ("type", "Title")
    clock.now = ACT_SETTLE_S
    result = session.tick(_frame([_c(2, "Title", "Edit")], frame_id=4))
    assert result.phase is Phase.DONE
    assert session.completed[1] == (2, "acted (no change seen)")


def test_a_risky_control_waits_for_the_user_before_acting():
    session, done, _ = _session(
        [PlanStep("Delete the slide", E.CHOSEN_DISAPPEARS)], [_choice("c1")]
    )
    frame = _frame([_c(1, "Delete Slide", "Button")])
    session.tick(frame)
    session.tick(frame, confirm=True)  # approves the plan
    assert session.tick(frame).phase is Phase.CONFIRM_RISK and done == []
    session.tick(frame, confirm=True)
    assert done == [("click", "Delete Slide")]


def test_a_failed_action_blocks_instead_of_retrying_blind():
    plan = TeachPlan((PlanStep("Press", E.TITLE_CHANGES, "keys", "esc"),))
    session = ModelTeachSession(
        "x",
        FakeGateway(plan, [_choice("c1")]),
        SyncSlot(),
        clock=lambda: 0.0,
        plan=plan,
        act=lambda step, target: act.perform(
            step,
            target,
            send=lambda e: None,
            click=lambda x, y: None,
            check=lambda x, y: None,
        ),
    )
    frame = _frame([_c(1)])
    session.tick(frame, confirm=True)
    assert session.tick(frame).phase is Phase.BLOCKED


def test_perform_clicks_the_observed_centre_then_sends_the_action():
    clicks, sent = [], []
    target = _frame([_c(1, "Title", "Edit", rect=(100, 200, 300, 240))]).candidates[0]

    def run(action, text=""):
        clicks.clear(), sent.clear()
        return act.perform(
            PlanStep("s", E.TITLE_CHANGES, action, text),
            target,
            send=sent.append,
            click=lambda x, y: clicks.append((x, y)),
            pause=lambda s: None,
            check=lambda x, y: None,
        )

    assert run("click") == "clicked Title" and clicks == [(200, 220)] and not sent
    run("type", "hi\n")
    assert len(sent[0]) == 6  # h, i, enter: down+up each
    run("paste")
    assert [e.u.ki.wVk for e in sent[0]] == [0x11, 0x56, 0x56, 0x11]
    run("keys", "ctrl+shift+s")
    assert [e.u.ki.wVk for e in sent[0]][:3] == [0x11, 0x10, 0x53]
    assert run("none") == "nothing to do" and not clicks


@pytest.mark.parametrize("chord", ["esc", "ctrl+escape", "", "ctrl+banana"])
def test_bad_or_stop_key_chords_are_refused(chord):
    with pytest.raises(ValueError):
        act.chord_events(chord)


def test_plans_carry_an_action_and_old_plans_default_to_click():
    old = parse_teach_plan(
        '{"steps":[{"instruction":"Click Insert","expected_change":"title_changes"}]}'
    )
    assert old.steps[0].action == "click" and old.steps[0].text == ""
    new = parse_teach_plan(
        '{"steps":[{"instruction":"Type","expected_change":"title_changes",'
        '"action":"type","text":"Q3 deck"}]}'
    )
    assert (new.steps[0].action, new.steps[0].text) == ("type", "Q3 deck")
    with pytest.raises(Exception):
        parse_teach_plan(
            '{"steps":[{"instruction":"x","expected_change":"title_changes",'
            '"action":"format_disk","text":""}]}'
        )


def test_a_blocked_desktop_or_elevated_window_gets_no_input():
    target = _frame([_c(1)]).candidates[0]
    clicks = []
    with pytest.raises(PermissionError, match="administrator"):
        act.perform(
            PlanStep("s", E.TITLE_CHANGES),
            target,
            click=lambda x, y: clicks.append((x, y)),
            check=lambda x, y: "that window runs as administrator",
        )
    assert clicks == []


def test_this_process_can_ask_its_own_elevation():
    assert act._elevated() in (True, False)


def test_a_denied_control_is_never_acted_on_even_if_jev_picks_it():
    session, done, _ = _session(
        [PlanStep("Remove the row", E.CHOSEN_DISAPPEARS)], [_choice("c1")]
    )
    session.deny = ("delete",)
    frame = _frame([_c(1, "Delete row", "Button")])
    session.tick(frame)
    session.tick(frame, confirm=True)  # approve plan
    out = session.tick(frame, confirm=True)  # past risk gate
    assert out.phase is Phase.BLOCKED and "not to touch" in out.message
    assert done == []


def test_an_empty_deny_entry_blocks_nothing():
    session, done, _ = _session(
        [PlanStep("Click it", E.CHOSEN_STATE_CHANGES)], [_choice("c1")]
    )
    session.deny = ("",)  # must not match every control
    frame = _frame([_c(1, "Save", "Button")])
    session.tick(frame)
    session.tick(frame, confirm=True)
    assert done == [("click", "Save")]
