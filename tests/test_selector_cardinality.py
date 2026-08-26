"""Selector cardinality is part of the contract, not an accident (D069).

`provider_exact` returns a FIRST match; `bounded_descendants` returns a SET. On
live VS Code 1.134.0 that difference was not theoretical: two on-screen controls
matched the trusted Open Folder names — the Explorer sidebar button at
(39, 263, 359, 297) and the Welcome-page action at (527, 238, 677, 277) — and
silently taking the first would have pointed the user at the wrong one.

So an ACTION selector must be `exactly_one`:

    0 matches  -> absent (empty, so OCR can escalate)
    1 match    -> usable target
    >1 matches -> ambiguity fault; never silently select the first

A VERIFICATION selector may be `at_least_one`, because "an Installed Section
exists" does not require choosing one control on the user's behalf.
"""

import pytest

from ghostcursor.perception.uia import (
    AT_LEAST_ONE,
    EXACTLY_ONE,
    ProviderQueryFault,
    SelectorAmbiguityFault,
    bounded_descendants,
)

GLYPH = ""  # the Codicon VS Code 1.134.0 prefixes
ALLOWED = ("Open Folder...", "Open Folder…")


class _Ctl:
    def __init__(self, name, bbox=(10, 10, 110, 40)):
        self._name = name
        self._bbox = bbox

    def window_text(self):
        return self._name

    def rectangle(self):
        class _R:
            pass

        r = _R()
        r.left, r.top, r.right, r.bottom = self._bbox
        return r

    @property
    def element_info(self):
        class _Info:
            control_type = "Button"
            automation_id = ""

        return _Info()


def _walk(controls):
    return lambda: list(controls)


# --- exactly_one: the action-selector contract -----------------------------


def test_exactly_one_returns_the_single_match():
    controls = [_Ctl("Minimize"), _Ctl(f"{GLYPH} Open Folder...")]
    elements = bounded_descendants(_walk(controls), ALLOWED, cardinality=EXACTLY_ONE)
    assert [e.name for e in elements] == [f"{GLYPH} Open Folder..."]


def test_exactly_one_treats_no_match_as_absence():
    """Absence stays empty and successful so OCR can still escalate."""
    elements = bounded_descendants(
        _walk([_Ctl("Minimize")]), ALLOWED, cardinality=EXACTLY_ONE
    )
    assert elements == []


def test_exactly_one_raises_on_two_matches_rather_than_picking_the_first():
    """The live failure this rule exists for."""
    controls = [
        _Ctl("Open Folder...", bbox=(39, 263, 359, 297)),
        _Ctl(f"{GLYPH} Open Folder...", bbox=(527, 238, 677, 277)),
    ]
    with pytest.raises(SelectorAmbiguityFault):
        bounded_descendants(_walk(controls), ALLOWED, cardinality=EXACTLY_ONE)


def test_an_ambiguity_fault_is_a_provider_query_fault():
    """Existing fault handling must catch it without knowing the subtype."""
    assert issubclass(SelectorAmbiguityFault, ProviderQueryFault)


def test_the_ambiguity_message_names_every_candidate():
    """A fault the operator cannot diagnose is barely better than silence."""
    controls = [
        _Ctl("Open Folder...", bbox=(39, 263, 359, 297)),
        _Ctl(f"{GLYPH} Open Folder...", bbox=(527, 238, 677, 277)),
    ]
    with pytest.raises(SelectorAmbiguityFault) as caught:
        bounded_descendants(_walk(controls), ALLOWED, cardinality=EXACTLY_ONE)
    message = str(caught.value)
    assert "39" in message and "527" in message


# --- at_least_one: the verification-selector contract ----------------------


def test_at_least_one_allows_several_matches():
    controls = [_Ctl("Open Folder..."), _Ctl(f"{GLYPH} Open Folder...")]
    elements = bounded_descendants(_walk(controls), ALLOWED, cardinality=AT_LEAST_ONE)
    assert len(elements) == 2


def test_at_least_one_still_treats_no_match_as_absence():
    elements = bounded_descendants(
        _walk([_Ctl("Minimize")]), ALLOWED, cardinality=AT_LEAST_ONE
    )
    assert elements == []


def test_at_least_one_is_the_default_so_existing_callers_are_unchanged():
    controls = [_Ctl("Open Folder..."), _Ctl(f"{GLYPH} Open Folder...")]
    assert len(bounded_descendants(_walk(controls), ALLOWED)) == 2
