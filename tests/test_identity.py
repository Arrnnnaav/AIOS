from ghostcursor.reasoning.identity import step_key
from ghostcursor.reasoning.schema import (
    ClaimedDescriptor,
    Risk,
    Step,
    TargetDescriptor,
    UserAction,
    VerificationKind,
    VerificationRule,
)


def _step(**claimed):
    base = dict(name="Export", ocr_text="Export", visual_description="top left button")
    base.update(claimed)
    return Step(
        user_action=UserAction.CLICK,
        target_descriptor=TargetDescriptor(claimed=ClaimedDescriptor(**base)),
        instruction_text="Click Export.",
        verification_rule=VerificationRule(kind=VerificationKind.USER_CONFIRMS),
        risk=Risk.NORMAL,
    )


def test_key_is_stable_across_calls():
    assert step_key("export a file", _step()) == step_key("export a file", _step())


def test_key_ignores_step_position_and_instruction_text():
    a = _step()
    b = _step()
    b.instruction_text = "Totally different wording."
    assert step_key("export a file", a) == step_key("export a file", b)


def test_key_is_namespaced_by_intent():
    assert step_key("export a file", _step()) != step_key("crop an image", _step())


def test_adding_a_synonym_does_not_orphan_learning():
    # Synonyms are alternate spellings of the SAME target.
    plain = _step()
    with_synonym = _step()
    with_synonym.target_descriptor.claimed.name_synonyms = ["Save As"]
    assert step_key("export a file", plain) == step_key("export a file", with_synonym)


def test_visual_description_distinguishes_same_named_targets():
    # "Delete in the toolbar" vs "Delete in the dialog" must not collide.
    toolbar = _step(name="Delete", visual_description="in the toolbar")
    dialog = _step(name="Delete", visual_description="in the confirmation dialog")
    assert step_key("delete a file", toolbar) != step_key("delete a file", dialog)


def test_renaming_the_target_orphans_learning():
    # Correct: the step now describes a different target.
    assert step_key("export a file", _step()) != step_key(
        "export a file", _step(name="Publish")
    )


def test_key_normalizes_whitespace_and_case():
    assert step_key("export a file", _step(name="Export")) == step_key(
        "export a file", _step(name="  export  ")
    )
