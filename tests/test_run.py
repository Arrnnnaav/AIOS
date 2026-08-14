"""Covers findings 2 and 4 from the whole-branch review of run.py:

- finding 2: the grounder wired into a live run_tour must call
  grounding.promote() after a successful grounding, or spec §5's promotion
  mechanism never runs outside the test suite.
- finding 4: ESC/SPACE must be detected on a tap, not just while held, and
  SPACE must only be polled while the current step is actually waiting on a
  user confirmation.
"""

from ghostcursor.perception.uia import Element
from ghostcursor.reasoning import grounding
from ghostcursor.reasoning.schema import (
    ClaimedDescriptor,
    Risk,
    Step,
    TargetDescriptor,
    UserAction,
    VerificationKind,
    VerificationRule,
)
from ghostcursor.run import key_was_pressed, make_grounder, should_poll_space

EN = [Element("Export", "Button", "1001", (10, 10, 110, 40))]

VK_ESCAPE = 0x1B
_CURRENTLY_DOWN = 0x8000
_PRESSED_SINCE_LAST_CALL = 0x0001


def _step(kind=VerificationKind.USER_CONFIRMS, args=None):
    return Step(
        user_action=UserAction.CLICK,
        target_descriptor=TargetDescriptor(claimed=ClaimedDescriptor(name="Export")),
        instruction_text="Click Export.",
        verification_rule=VerificationRule(kind=kind, args=args or {}),
        risk=Risk.NORMAL,
    )


# --- finding 4: key-state predicate against both bits -----------------------


def test_key_was_pressed_true_when_currently_down():
    assert key_was_pressed(VK_ESCAPE, key_state=lambda vk: _CURRENTLY_DOWN) is True


def test_key_was_pressed_true_when_only_tapped_since_last_call():
    # The key is UP right now but was pressed at some point since the last
    # poll. A single tick can exceed a second (three UIA tree walks, each
    # able to block), so this bit is what makes a tapped ESC reliable.
    assert (
        key_was_pressed(VK_ESCAPE, key_state=lambda vk: _PRESSED_SINCE_LAST_CALL)
        is True
    )


def test_key_was_pressed_false_when_neither_bit_set():
    assert key_was_pressed(VK_ESCAPE, key_state=lambda vk: 0x0000) is False


def test_key_was_pressed_forwards_the_right_virtual_key_code():
    seen = []

    def fake_key_state(vk):
        seen.append(vk)
        return 0

    key_was_pressed(VK_ESCAPE, key_state=fake_key_state)
    assert seen == [VK_ESCAPE]


# --- finding 4: SPACE only polled for user_confirms steps -------------------


def test_should_poll_space_true_for_a_user_confirms_step():
    assert should_poll_space(_step(kind=VerificationKind.USER_CONFIRMS)) is True


def test_should_poll_space_false_for_a_non_user_confirms_step():
    # Otherwise a space typed into some other application would silently
    # advance the tour -- inventing progress the user never made.
    step = _step(
        kind=VerificationKind.ELEMENT_APPEARS,
        args={"target_descriptor": {"name": "Save"}},
    )
    assert should_poll_space(step) is False


def test_should_poll_space_false_when_there_is_no_current_step():
    assert should_poll_space(None) is False


# --- finding 2: the live grounder promotes after a successful grounding -----


def test_make_grounder_promotes_after_a_successful_grounding(monkeypatch):
    monkeypatch.setattr(grounding, "iter_elements", lambda title_re: EN)
    step = _step()
    assert step.target_descriptor.confirmed == []

    grounder = make_grounder(".*")
    result = grounder(step, 0)

    assert result is not None
    assert step.target_descriptor.confirmed, (
        "grounding succeeded but promote() never ran -- rung 1 stays "
        "unreachable outside the test suite"
    )
    observation = step.target_descriptor.confirmed[0]
    assert observation.automation_id == "1001"
    # app_version="unknown" is deliberate here: real version detection is
    # spec §9, deferred knowledge-base scope.
    assert observation.app_version == "unknown"


def test_make_grounder_does_not_promote_on_a_failed_grounding(monkeypatch):
    monkeypatch.setattr(grounding, "iter_elements", lambda title_re: [])
    step = _step()

    grounder = make_grounder(".*")
    result = grounder(step, 0)

    assert result is None
    assert step.target_descriptor.confirmed == []
