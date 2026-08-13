import pytest

from ghostcursor.reasoning.schema import (
    ClaimedDescriptor,
    Recipe,
    Risk,
    Step,
    TargetDescriptor,
    UserAction,
    VerificationKind,
    VerificationRule,
    validate_step,
)


def _step(**overrides):
    base = dict(
        user_action=UserAction.CLICK,
        target_descriptor=TargetDescriptor(
            claimed=ClaimedDescriptor(name="Export", name_synonyms=["Export As"]),
        ),
        instruction_text="Click Export.",
        verification_rule=VerificationRule(
            kind=VerificationKind.ELEMENT_APPEARS,
            args={"target_descriptor": {"name": "Save"}},
        ),
        risk=Risk.NORMAL,
    )
    base.update(overrides)
    return Step(**base)


def test_valid_step_has_no_errors():
    assert validate_step(_step()) == []


def test_elevated_risk_cannot_use_any_meaningful_change():
    step = _step(
        risk=Risk.ELEVATED,
        verification_rule=VerificationRule(
            kind=VerificationKind.ANY_MEANINGFUL_CHANGE, args={"scope": {}}
        ),
    )
    errors = validate_step(step)
    assert any("elevated" in e for e in errors)


def test_normal_risk_may_use_any_meaningful_change():
    step = _step(
        verification_rule=VerificationRule(
            kind=VerificationKind.ANY_MEANINGFUL_CHANGE, args={"scope": {}}
        )
    )
    assert validate_step(step) == []


def test_element_appears_requires_target_descriptor_arg():
    step = _step(
        verification_rule=VerificationRule(
            kind=VerificationKind.ELEMENT_APPEARS, args={}
        )
    )
    assert any("target_descriptor" in e for e in validate_step(step))


def test_window_title_matches_requires_pattern_arg():
    step = _step(
        verification_rule=VerificationRule(
            kind=VerificationKind.WINDOW_TITLE_MATCHES, args={}
        )
    )
    assert any("pattern" in e for e in validate_step(step))


def test_step_with_no_claimed_identity_is_rejected():
    step = _step(target_descriptor=TargetDescriptor(claimed=ClaimedDescriptor()))
    assert any("identify" in e for e in validate_step(step))


def test_observe_step_needs_no_target():
    step = _step(
        user_action=UserAction.OBSERVE,
        target_descriptor=TargetDescriptor(claimed=ClaimedDescriptor()),
        verification_rule=VerificationRule(
            kind=VerificationKind.USER_CONFIRMS, args={}
        ),
    )
    assert validate_step(step) == []


def test_recipe_round_trips_through_json(tmp_path):
    recipe = Recipe(app_id="notepad", intent="export a file", steps=[_step()])
    path = tmp_path / "r.json"
    recipe.save(path)
    loaded = Recipe.load(path)
    assert loaded == recipe
    assert loaded.steps[0].target_descriptor.claimed.name == "Export"


def test_recipe_rejects_a_step_that_stores_coordinates():
    with pytest.raises(ValueError, match="coordinates"):
        Recipe.from_dict(
            {
                "app_id": "notepad",
                "intent": "x",
                "steps": [{**_step().to_dict(), "bbox": [1, 2, 3, 4]}],
            }
        )


def test_recipe_rejects_coordinates_nested_in_verification_rule_args():
    step_dict = _step().to_dict()
    step_dict["verification_rule"]["args"]["bbox"] = [1, 2, 3, 4]
    with pytest.raises(ValueError, match="coordinates"):
        Recipe.from_dict(
            {
                "app_id": "notepad",
                "intent": "x",
                "steps": [step_dict],
            }
        )


def test_recipe_rejects_coordinates_nested_in_provenance():
    step_dict = _step().to_dict()
    step_dict["provenance"]["rect"] = [1, 2, 3, 4]
    with pytest.raises(ValueError, match="coordinates"):
        Recipe.from_dict(
            {
                "app_id": "notepad",
                "intent": "x",
                "steps": [step_dict],
            }
        )


def test_recipe_rejects_coordinates_nested_in_confirmed_observation():

    step_dict = _step().to_dict()
    step_dict["target_descriptor"]["confirmed"] = [
        {
            "app_version": "1.0",
            "automation_id": "Save",
            "accessibility_path_hint": {"x": 100},
        }
    ]
    with pytest.raises(ValueError, match="coordinates"):
        Recipe.from_dict(
            {
                "app_id": "notepad",
                "intent": "x",
                "steps": [step_dict],
            }
        )


def test_recipe_rejects_invalid_step_elevated_risk_with_any_meaningful_change():
    step_dict = _step(
        risk=Risk.ELEVATED,
        verification_rule=VerificationRule(
            kind=VerificationKind.ANY_MEANINGFUL_CHANGE, args={"scope": {}}
        ),
    ).to_dict()
    with pytest.raises(ValueError, match="invalid"):
        Recipe.from_dict(
            {
                "app_id": "notepad",
                "intent": "x",
                "steps": [step_dict],
            }
        )
