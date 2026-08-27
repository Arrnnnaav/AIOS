"""The second declared selector strategy: a bounded descendant walk (D069).

Measured on VS Code 1.134.0: the Welcome-page Open Folder action reads cleanly
through a bounded Button walk (5/5, stable bbox) while provider-side exact
lookup returns a dead pointer for it. The two strategies are not
interchangeable, which is why a recipe must DECLARE which one it uses rather
than have the compiler infer it.

This strategy filters by normalised accessible name, so a Codicon prefix cannot
defeat it, and caps how many elements it will return so a pathological tree
cannot flood the observation.
"""

import pytest

from ghostcursor.perception.uia import (
    EXACTLY_ONE,
    ProviderQueryFault,
    SelectorAmbiguityFault,
    bounded_descendants,
)

GLYPH = ""


class _Ctl:
    """A minimal stand-in for a pywinauto control wrapper."""

    def __init__(
        self,
        name,
        automation_id="",
        bbox=(10, 10, 110, 40),
        raises=None,
        runtime_id=None,
    ):
        self._name = name
        self._automation_id = automation_id
        self._bbox = bbox
        self._raises = raises
        self._runtime_id = runtime_id

    def window_text(self):
        if self._raises is not None:
            raise self._raises
        return self._name

    def rectangle(self):
        left, top, right, bottom = self._bbox

        class _R:
            pass

        r = _R()
        r.left, r.top, r.right, r.bottom = left, top, right, bottom
        return r

    @property
    def element_info(self):
        class _Info:
            pass

        info = _Info()
        info.control_type = "Button"
        info.automation_id = self._automation_id
        # A real backend identity when the fixture supplies one; absent
        # otherwise, which is the "identity unavailable" case.
        if self._runtime_id is not None:
            info.runtime_id = self._runtime_id
        return info


ALLOWED = ("Open Folder...", "Open Folder…", "Open Folder")


def _walk(controls):
    return lambda: list(controls)


def test_a_glyph_prefixed_control_is_selected():
    elements = bounded_descendants(_walk([_Ctl(f"{GLYPH} Open Folder...")]), ALLOWED)

    assert [element.name for element in elements] == [f"{GLYPH} Open Folder..."]
    assert elements[0].bbox == (10, 10, 110, 40)
    assert elements[0].source == "uia"


def test_the_raw_observed_name_is_preserved_not_the_normalised_one():
    """Normalisation decides matching only. What is published is what was seen.

    Publishing a cleaned-up name would make the observation disagree with the
    screen, and every downstream trust decision keys off the observation.
    """
    elements = bounded_descendants(_walk([_Ctl(f"{GLYPH} Open Folder...")]), ALLOWED)
    assert elements[0].name == f"{GLYPH} Open Folder..."


def test_unrelated_controls_are_excluded():
    controls = [
        _Ctl(f"{GLYPH} Open File..."),
        _Ctl("Clone Git Repository..."),
        _Ctl(f"{GLYPH} Open Folder..."),
        _Ctl("Minimize"),
    ]
    elements = bounded_descendants(_walk(controls), ALLOWED)
    assert [element.name for element in elements] == [f"{GLYPH} Open Folder..."]


def test_offscreen_controls_are_excluded():
    controls = [_Ctl("Open Folder...", bbox=(-32000, -32000, -31900, -31960))]
    assert bounded_descendants(_walk(controls), ALLOWED) == []


def test_exceeding_the_result_limit_raises_instead_of_truncating():
    """The limit bounds what a recipe may claim, not how long a walk may run.

    Truncating produced a silently wrong answer: the extra matches were
    discarded before anything could notice them, so an over-broad filter
    looked like a correctly bounded one.
    """
    controls = [_Ctl("Open Folder...") for _ in range(50)]
    with pytest.raises(ProviderQueryFault) as caught:
        bounded_descendants(_walk(controls), ALLOWED, limit=8)
    assert "over the result limit of 8" in str(caught.value)


def test_a_one_limit_selector_matching_twice_reports_ambiguity():
    """The regression for the truncation defect.

    With truncation at the top of the loop, a limit of one stopped after the
    first match and the ambiguity check never saw the second -- so the caller
    received one element and no indication that the filter named two controls.
    Ambiguity is reported rather than the limit, because it is the more
    specific answer.
    """
    controls = [_Ctl("Open Folder...", bbox=(0, 0, 10, 10)),
                _Ctl("Open Folder...", bbox=(20, 20, 30, 30))]
    with pytest.raises(SelectorAmbiguityFault) as caught:
        bounded_descendants(_walk(controls), ALLOWED, limit=1, cardinality=EXACTLY_ONE)
    assert "matched 2 controls" in str(caught.value)


def test_a_result_count_at_the_limit_is_accepted():
    controls = [_Ctl("Open Folder...", bbox=(i, i, i + 10, i + 10)) for i in range(8)]
    elements = bounded_descendants(_walk(controls), ALLOWED, limit=8)
    assert len(elements) == 8


def test_candidates_deduplicate_on_backend_identity_never_on_value():
    """One control reached twice is one result; two look-alikes are two.

    `Element` equality compares name, control type, AutomationId and bbox, and
    VS Code publishes empty AutomationIds with repeated names -- so value
    equality would collapse two genuinely different controls into one and hide
    an ambiguity.
    """
    same = [_Ctl("Open Folder...", runtime_id=(7, 1)),
            _Ctl("Open Folder...", runtime_id=(7, 1))]
    assert len(bounded_descendants(_walk(same), ALLOWED)) == 1

    identical_values = [_Ctl("Open Folder..."), _Ctl("Open Folder...")]
    assert len(bounded_descendants(_walk(identical_values), ALLOWED)) == 2


def test_a_raising_walk_is_a_fault():
    def _boom():
        raise OSError("RPC server unavailable")

    with pytest.raises(ProviderQueryFault):
        bounded_descendants(_boom, ALLOWED)


def test_a_dead_pointer_on_one_control_skips_only_that_control():
    """One vanished control is absence, not a fault for the whole walk.

    Elements legitimately disappear mid-walk. That must not discard the
    elements that did read cleanly.
    """
    controls = [
        _Ctl("gone", raises=ValueError("NULL COM pointer access")),
        _Ctl(f"{GLYPH} Open Folder..."),
    ]
    elements = bounded_descendants(_walk(controls), ALLOWED)
    assert [element.name for element in elements] == [f"{GLYPH} Open Folder..."]


def test_another_error_on_one_control_is_a_fault_for_the_walk():
    """Anything that is not a clean absence must stay observable."""
    controls = [
        _Ctl("bad", raises=OSError("provider went away")),
        _Ctl(f"{GLYPH} Open Folder..."),
    ]
    with pytest.raises(ProviderQueryFault):
        bounded_descendants(_walk(controls), ALLOWED)
