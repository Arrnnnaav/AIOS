from ghostcursor.reasoning.identity import step_key, _normalize
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


def test_ocr_text_participates_in_the_key():
    # ocr_text must affect the key, or different visual text on the same button
    # would share observations, mis-grounding the hint.
    assert step_key("export a file", _step(ocr_text="Export")) != step_key(
        "export a file", _step(ocr_text="Save")
    )


def test_key_normalizes_whitespace_and_case():
    assert step_key("export a file", _step(name="Export")) == step_key(
        "export a file", _step(name="  export  ")
    )


def test_normalize_strips_the_field_separator_so_the_join_stays_injective():
    """The key's collision resistance depends on _normalize stripping \x1f.

    \x1f (unit separator) is treated as whitespace by str.split(), so
    _normalize removes it. If someone later changes normalization to preserve
    control characters, the separator would appear in normalized fields,
    different field combinations could produce identical concatenations, and
    two different steps would silently share learned observations.
    This test ensures the stripping invariant is maintained.
    """
    assert "\x1f" not in _normalize("a\x1fb")
    assert "\x1f" not in _normalize("test\x1fvalue")
    assert "\x1f" not in _normalize("\x1f")
    assert "\x1f" not in _normalize("x\x1fy\x1fz")


def test_cross_field_distribution_distinguishes_steps():
    """Text distributed across fields differently must produce different keys.

    The field separator \x1f is what makes field boundaries meaningful. If someone
    changes the join character or drops the separator entirely, text moved between
    fields could merge two genuinely different steps' observations. This test uses
    non-empty trailing fields so that changing the separator to a space would produce
    identical digest inputs (e.g., "i a b c d" vs "i a b c d" are the same when joined
    with space but differ with \x1f). An empty trailing field version would pass even
    with space join due to trailing spaces, so this pair is necessary.
    """
    step_a = _step(name="a", ocr_text="b c", visual_description="d")
    step_b = _step(name="a b", ocr_text="c", visual_description="d")
    # Same text distributed differently across fields, no empty trailing fields
    # Must produce different keys (requires \x1f separator; space join would collide)
    assert step_key("intent", step_a) != step_key("intent", step_b)


def test_separator_characters_in_input_are_normalized_away():
    """Separator characters in field values are stripped by normalization.

    This is a side effect of using str.split() as the normalizer. When a field
    contains the separator character, it is treated as whitespace. This test
    documents that the invariant (test 8) is sufficient: because the separator
    is stripped, two steps with the separator in different field positions
    normalize identically, even though the cross-field distribution test ensures
    genuinely different distributions remain distinct.
    """
    # Separator at the end of name
    step1 = _step(name="a\x1f", ocr_text="b")
    # Same normalized result, separator in ocr_text
    step2 = _step(name="a", ocr_text="\x1fb")
    # They normalize to the same fields, so they produce the same key
    assert step_key("intent", step1) == step_key("intent", step2)
