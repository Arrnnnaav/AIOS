from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.grounding import (
    RUNG_AUTOMATION_ID,
    RUNG_FUZZY_NAME,
    RUNG_TYPE_AND_NAME,
    ground,
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

ELEMENTS = [
    Element("Export", "Button", "1001", (10, 10, 110, 40)),
    Element("Delete", "Button", "1002", (10, 50, 110, 80)),
    Element("", "Edit", "1004", (200, 10, 300, 40)),
]


def _step(claimed=None, confirmed=None):
    return Step(
        user_action=UserAction.CLICK,
        target_descriptor=TargetDescriptor(
            claimed=claimed or ClaimedDescriptor(name="Export"),
            confirmed=confirmed or [],
        ),
        instruction_text="Click Export.",
        verification_rule=VerificationRule(kind=VerificationKind.USER_CONFIRMS),
        risk=Risk.NORMAL,
    )


def test_rung1_prefers_confirmed_automation_id():
    step = _step(
        claimed=ClaimedDescriptor(name="WrongName"),
        confirmed=[ConfirmedObservation(app_version="1.0", automation_id="1001")],
    )
    result = ground(step, ".*", elements=ELEMENTS)
    assert result.rung == RUNG_AUTOMATION_ID
    assert result.bbox == (10, 10, 110, 40)


def test_rung1_ignores_locale_mismatch():
    # AutomationId is language-independent: an observation recorded in en-US
    # must still ground for a hi-IN user, or promotion is pointless.
    step = _step(
        claimed=ClaimedDescriptor(name="Export"),
        confirmed=[
            ConfirmedObservation(
                app_version="1.0", automation_id="1001", locales_observed=["en-US"]
            )
        ],
    )
    result = ground(step, ".*", locale="hi-IN", elements=ELEMENTS)
    assert result.rung == RUNG_AUTOMATION_ID


def test_rung2_matches_control_type_and_exact_name():
    step = _step(claimed=ClaimedDescriptor(name="Delete"))
    result = ground(step, ".*", elements=ELEMENTS)
    assert result.rung == RUNG_TYPE_AND_NAME
    assert result.automation_id == "1002"


def test_rung3_matches_a_synonym():
    step = _step(claimed=ClaimedDescriptor(name="Save As", name_synonyms=["Export"]))
    result = ground(step, ".*", elements=ELEMENTS)
    assert result.rung == RUNG_FUZZY_NAME
    assert result.automation_id == "1001"


def test_returns_none_when_nothing_matches():
    step = _step(claimed=ClaimedDescriptor(name="Nonexistent"))
    assert ground(step, ".*", elements=ELEMENTS) is None


def test_path_hint_disambiguates_equal_matches():
    duplicates = [
        Element("Delete", "Button", "2001", (0, 0, 10, 10), path=("ToolBar",)),
        Element("Delete", "Button", "2002", (50, 0, 60, 10), path=("Dialog",)),
    ]
    step = _step(
        claimed=ClaimedDescriptor(name="Delete"),
        confirmed=[
            ConfirmedObservation(app_version="1.0", accessibility_path_hint=["Dialog"])
        ],
    )
    result = ground(step, ".*", elements=duplicates)
    assert result.automation_id == "2002"
