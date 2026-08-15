"""Rung 4, and the guard that stops rung 3 bypassing its floor.

Every fixture below is a REAL read from the spike, with its real score.
"""

from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.grounding import (
    OCR_MATCH_FLOOR,
    RUNG_OCR_TEXT,
    ground,
)
from ghostcursor.reasoning.schema import Recipe


def _step(name, synonyms=()):
    recipe = Recipe.from_dict(
        {
            "app_id": "test",
            "intent": "t",
            "steps": [
                {
                    "user_action": "click",
                    "target_descriptor": {
                        "claimed": {"name": name, "name_synonyms": list(synonyms)},
                        "confirmed": [],
                    },
                    "instruction_text": "x",
                    "verification_rule": {"kind": "user_confirms", "args": {}},
                    "risk": "normal",
                }
            ],
        }
    )
    return recipe.steps[0]


def _ocr(text, bbox=(10, 20, 110, 44)):
    return Element(
        name=text, control_type="", automation_id="", bbox=bbox, path=(), source="ocr"
    )


def test_an_exact_ocr_read_grounds_at_rung_4():
    """Case-only difference: rung 2 is case-sensitive `==` and misses; rung 3
    excludes OCR; rung 4 casefolds and scores 100.0, clearing the floor."""
    target = ground(_step("Select area"), ".*", elements=[_ocr("Select Area")])
    assert target is not None and target.rung == RUNG_OCR_TEXT


def test_uploads_does_not_match_upload():
    """The binding case. Both are real Canva surfaces, and the spike measured 92.3,
    and 0.85 -- the value the OCR doc suggests -- would have pointed wrong."""
    assert ground(_step("Uploads"), ".*", elements=[_ocr("upload")]) is None


def test_magic_expand_does_not_match_magic_edit():
    """The dangerous case: a different real tool in the same grid (72.7)."""
    assert ground(_step("Magic Expand"), ".*", elements=[_ocr("Magic Edit")]) is None


def test_rung_3_never_sees_an_ocr_element():
    """Rung 3 is a SUBSTRING test. Unfiltered it would match 'Edit' against
    'Edit a PDF' with no floor at all, making 95 decorative."""
    assert ground(_step("Edit"), ".*", elements=[_ocr("Edit a PDF")]) is None


def test_rung_3_still_works_for_uia_elements():
    """The guard must not break the existing ladder."""
    uia = Element(
        name="Edit a PDF", control_type="Button", automation_id="", bbox=(0, 0, 10, 10)
    )
    target = ground(_step("Edit"), ".*", elements=[uia])
    assert target is not None and target.rung == 3


def test_ocr_elements_may_still_match_exactly_at_rung_2():
    """Exact equality is a strictly higher bar than a 95 fuzzy score."""
    target = ground(_step("Upscale"), ".*", elements=[_ocr("Upscale")])
    assert target is not None and target.rung in (2, RUNG_OCR_TEXT)


def test_the_floor_is_95():
    assert OCR_MATCH_FLOOR == 95
