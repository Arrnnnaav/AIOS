from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.grounding import (
    RUNG_AUTOMATION_ID,
    ground,
    promote,
)
from ghostcursor.reasoning.schema import (
    ClaimedDescriptor,
    Risk,
    Step,
    TargetDescriptor,
    UserAction,
    VerificationKind,
    VerificationRule,
)

EN = [Element("Export", "Button", "1001", (10, 10, 110, 40))]
HI = [Element("निर्यात", "Button", "1001", (10, 10, 110, 40))]


def _step():
    return Step(
        user_action=UserAction.CLICK,
        target_descriptor=TargetDescriptor(claimed=ClaimedDescriptor(name="Export")),
        instruction_text="Click Export.",
        verification_rule=VerificationRule(kind=VerificationKind.USER_CONFIRMS),
        risk=Risk.NORMAL,
    )


def test_promotion_records_the_discovered_automation_id():
    step = _step()
    grounded = ground(step, ".*", elements=EN)
    assert promote(step, grounded, app_version="1.2.7", locale="en-US") is True

    observation = step.target_descriptor.confirmed[0]
    assert observation.automation_id == "1001"
    assert observation.control_type == "Button"
    assert observation.app_version == "1.2.7"
    assert observation.locales_observed == ["en-US"]
    assert observation.last_seen_at is not None


def test_promoted_step_grounds_on_rung_1_next_time():
    step = _step()
    promote(step, ground(step, ".*", elements=EN), "1.2.7", "en-US")
    assert ground(step, ".*", elements=EN).rung == RUNG_AUTOMATION_ID


def test_english_promotion_grounds_for_a_hindi_user():
    # The whole point: the Hindi UI shows a different name, same AutomationId.
    step = _step()
    promote(step, ground(step, ".*", elements=EN), "1.2.7", "en-US")

    result = ground(step, ".*", locale="hi-IN", elements=HI)
    assert result is not None
    assert result.rung == RUNG_AUTOMATION_ID


def test_second_locale_is_appended_not_duplicated():
    step = _step()
    promote(step, ground(step, ".*", elements=EN), "1.2.7", "en-US")
    promote(step, ground(step, ".*", elements=HI), "1.2.7", "hi-IN")

    assert len(step.target_descriptor.confirmed) == 1
    assert step.target_descriptor.confirmed[0].locales_observed == ["en-US", "hi-IN"]


def test_a_new_app_version_creates_a_separate_observation():
    step = _step()
    promote(step, ground(step, ".*", elements=EN), "1.2.7", "en-US")
    promote(step, ground(step, ".*", elements=EN), "2.0.0", "en-US")

    versions = {o.app_version for o in step.target_descriptor.confirmed}
    assert versions == {"1.2.7", "2.0.0"}


def test_promotion_is_a_noop_without_an_automation_id():
    step = _step()
    anonymous = [Element("Export", "Button", "", (10, 10, 110, 40))]
    assert (
        promote(step, ground(step, ".*", elements=anonymous), "1.0", "en-US") is False
    )
    assert step.target_descriptor.confirmed == []
