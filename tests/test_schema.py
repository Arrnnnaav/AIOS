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


def test_focus_moves_to_requires_automation_id_arg():
    step = _step(
        verification_rule=VerificationRule(
            kind=VerificationKind.FOCUS_MOVES_TO, args={"automation_id": "1004"}
        )
    )
    assert validate_step(step) == []


def test_focus_moves_to_with_target_descriptor_is_rejected():
    """Unlike its descriptor-based siblings, focus is observable only as a
    bare AutomationId string -- a target_descriptor's name half has nothing
    to match against, so it must not validate here."""
    step = _step(
        verification_rule=VerificationRule(
            kind=VerificationKind.FOCUS_MOVES_TO,
            args={"target_descriptor": {"name": "Save"}},
        )
    )
    errors = validate_step(step)
    assert any("automation_id" in e for e in errors)


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


def test_an_empty_required_arg_is_rejected_for_every_rule_kind():
    """Present-but-empty is worse than missing, because it VALIDATES.

    Found by an external review on FOCUS_MOVES_TO, then swept for siblings
    (D036) -- and the sibling is worse than the instance. Every kind
    degenerates on an empty required arg, in one of two directions, and both
    are silent:

      never satisfied -- element_appears/element_disappears with an empty
      descriptor match nothing; focus_moves_to with an empty automation_id
      can never match. The tour dwells forever without saying why, which is
      verbatim the failure focus_moves_to's old NotImplementedError guarded.

      always satisfied -- window_title_matches with an empty pattern is
      re.search("", title), which matches everything, so the step completes
      without the user doing anything. Auto-satisfying on no evidence is the
      worse direction for a system whose premise is verifying a real change.
    """
    empties = [
        (VerificationKind.FOCUS_MOVES_TO, {"automation_id": ""}, "automation_id"),
        (VerificationKind.FOCUS_MOVES_TO, {"automation_id": "   "}, "automation_id"),
        (VerificationKind.WINDOW_TITLE_MATCHES, {"pattern": ""}, "pattern"),
        (
            VerificationKind.ELEMENT_APPEARS,
            {"target_descriptor": {}},
            "target_descriptor",
        ),
        (
            VerificationKind.ELEMENT_DISAPPEARS,
            {"target_descriptor": {}},
            "target_descriptor",
        ),
    ]
    for kind, args, field in empties:
        step = _step(verification_rule=VerificationRule(kind=kind, args=args))
        errors = validate_step(step)
        assert any(field in e and "empty" in e for e in errors), (
            f"{kind.value} accepted an empty {field!r} -- the step would either "
            "never complete or complete on no evidence, and nothing would say why"
        )


def test_a_populated_required_arg_still_validates():
    """The emptiness check must not reject real recipes."""
    step = _step(
        verification_rule=VerificationRule(
            kind=VerificationKind.WINDOW_TITLE_MATCHES, args={"pattern": "Save As"}
        )
    )
    assert validate_step(step) == []
