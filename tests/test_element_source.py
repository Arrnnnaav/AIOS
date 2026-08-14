"""`source` is how the system knows a pixel guess from a confirmed control."""

from ghostcursor.perception.uia import Element


def _el(**kw):
    base = dict(
        name="Export", control_type="Button", automation_id="1001", bbox=(0, 0, 10, 10)
    )
    base.update(kw)
    return Element(**base)


def test_source_defaults_to_uia():
    assert _el().source == "uia"


def test_positional_construction_still_works():
    """`source` must be LAST: every existing call site builds Elements
    positionally, and inserting a field earlier would silently shift them."""
    element = Element("Export", "Button", "1001", (0, 0, 10, 10))
    assert element.source == "uia"


def test_an_ocr_element_is_marked_as_such():
    assert _el(source="ocr", automation_id="", control_type="").source == "ocr"


def test_element_stays_frozen_and_hashable():
    """Only frozen dataclasses of primitives cross the worker boundary (D021)."""
    assert len({_el(), _el()}) == 1
    import dataclasses

    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        _el().source = "ocr"
