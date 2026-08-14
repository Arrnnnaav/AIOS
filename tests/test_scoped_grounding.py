from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.grounding import (
    RUNG_AUTOMATION_ID,
    RUNG_TYPE_AND_NAME,
    ground,
    select_observations,
)
from ghostcursor.reasoning.schema import (
    ClaimedDescriptor,
    ConfirmedObservation,
    Risk,
    Step,
    TargetDescriptor,
    UserAction,
    VerificationKind,
    VerificationRule,
)


def _obs(version, automation_id="1001", ctype="Button"):
    return ConfirmedObservation(
        app_version=version,
        locales_observed=["en-US"],
        automation_id=automation_id,
        control_type=ctype,
    )


def _step(confirmed, name="Export"):
    return Step(
        user_action=UserAction.CLICK,
        target_descriptor=TargetDescriptor(
            claimed=ClaimedDescriptor(name=name), confirmed=list(confirmed)
        ),
        instruction_text="Click Export.",
        verification_rule=VerificationRule(kind=VerificationKind.USER_CONFIRMS),
        risk=Risk.NORMAL,
    )


BUTTON = [Element("Export", "Button", "1001", (10, 10, 110, 40))]


def test_exact_version_wins_and_is_marked_exact():
    chosen = select_observations([_obs("1.0.0"), _obs("2.0.0")], "2.0.0")
    assert [(o.app_version, exact) for o, exact in chosen] == [("2.0.0", True)]


def test_nearest_lower_version_is_used_when_no_exact_match():
    chosen = select_observations([_obs("1.0.0"), _obs("1.5.0"), _obs("3.0.0")], "2.0.0")
    assert [o.app_version for o, _ in chosen] == ["1.5.0"]
    assert all(exact is False for _, exact in chosen)


def test_newer_observations_are_never_used_for_an_older_app():
    # An id learned on 3.0.0 says nothing about what 2.0.0 shows.
    chosen = select_observations([_obs("3.0.0")], "2.0.0")
    assert chosen == []


def test_unknown_app_version_uses_every_observation_inexactly():
    chosen = select_observations([_obs("1.0.0"), _obs("2.0.0")], None)
    assert len(chosen) == 2
    assert all(exact is False for _, exact in chosen)


def test_a_patch_bump_still_reuses_what_was_learned():
    step = _step([_obs("151.0.7922.110")])
    result = ground(step, ".*", elements=BUTTON, app_version="151.0.7923.5")
    assert result is not None and result.rung == RUNG_AUTOMATION_ID


def test_exact_version_match_skips_the_cross_check():
    # control_type disagrees, but the version matches exactly, so the
    # observation is trusted.
    step = _step([_obs("1.0.0", ctype="Hyperlink")])
    result = ground(step, ".*", elements=BUTTON, app_version="1.0.0")
    assert result is not None and result.rung == RUNG_AUTOMATION_ID


def test_stale_id_from_an_older_version_does_not_misground():
    # The id was learned on 1.0.0 as a Hyperlink; on 2.0.0 that same id is a
    # Button, i.e. it now belongs to something else. Rung 1 must be rejected
    # and grounding must fall through to the name.
    step = _step([_obs("1.0.0", ctype="Hyperlink")])
    result = ground(step, ".*", elements=BUTTON, app_version="2.0.0")
    assert result is not None
    assert result.rung == RUNG_TYPE_AND_NAME, "stale observation was trusted"


def test_cross_check_allows_a_match_when_control_type_agrees():
    step = _step([_obs("1.0.0", ctype="Button")])
    result = ground(step, ".*", elements=BUTTON, app_version="2.0.0")
    assert result is not None and result.rung == RUNG_AUTOMATION_ID


def test_observation_without_control_type_cannot_be_cross_checked():
    # Nothing to compare against; allowed, and noted in the module docs.
    step = _step([_obs("1.0.0", ctype=None)])
    result = ground(step, ".*", elements=BUTTON, app_version="2.0.0")
    assert result is not None and result.rung == RUNG_AUTOMATION_ID


def test_grounding_without_an_app_version_still_works():
    # Existing callers that pass no version keep working.
    step = _step([_obs("1.0.0")])
    result = ground(step, ".*", elements=BUTTON)
    assert result is not None and result.rung == RUNG_AUTOMATION_ID


def test_first_matching_observation_wins_when_several_apply():
    """Pins current behaviour rather than changing it.

    Rung 1 iterates the selected observations and returns on the first whose
    automation_id matches a live element, instead of gathering matches across
    all of them and disambiguating once. Both ids here were legitimately
    learned by promote() for this same step, so choosing the first is
    arbitrary rather than wrong — but it is a real narrowing of what
    _disambiguate sees, and it was previously untested in either direction.

    If this ever becomes a problem, the fix is to aggregate matches across
    tied observations before disambiguating; this test is what will notice
    the behaviour changing.
    """
    elements = [
        Element("First", "Button", "1001", (10, 10, 110, 40)),
        Element("Second", "Button", "2002", (10, 50, 110, 80)),
    ]
    step = _step([_obs("1.0.0", automation_id="1001"), _obs("1.0.0", automation_id="2002")])

    result = ground(step, ".*", elements=elements, app_version="1.0.0")

    assert result is not None
    assert result.rung == RUNG_AUTOMATION_ID
    assert result.automation_id == "1001", (
        "rung 1 no longer returns on the first matching observation; if that "
        "was deliberate, update this test and say why"
    )
