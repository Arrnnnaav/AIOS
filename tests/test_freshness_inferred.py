"""INFERRED, and the rule that stops a pixel guess laundering into a fact."""

from ghostcursor.reasoning.staleness import Freshness, display_freshness


def test_a_uia_hint_that_is_current_is_fresh():
    assert display_freshness(Freshness.FRESH, "uia") is Freshness.FRESH


def test_a_current_ocr_hint_is_inferred_not_fresh():
    assert display_freshness(Freshness.FRESH, "ocr") is Freshness.INFERRED


def test_staleness_dominates_source():
    """'Possibly outdated' subsumes 'possibly misread'."""
    assert display_freshness(Freshness.DIMMED, "ocr") is Freshness.DIMMED
    assert display_freshness(Freshness.DIMMED, "uia") is Freshness.DIMMED


def test_hidden_dominates_everything():
    assert display_freshness(Freshness.HIDDEN, "ocr") is Freshness.HIDDEN
    assert display_freshness(Freshness.HIDDEN, "uia") is Freshness.HIDDEN


def test_a_recovered_ocr_hint_returns_to_inferred_never_to_fresh():
    """The laundering guard.

    A tier-2 hint that goes stale shows DIMMED. If recovery returned FRESH, a
    round trip through staleness would silently convert a pixel guess into a
    confirmed control -- the same shape as the verification-baseline
    laundering bug found in the previous milestone.
    """
    assert display_freshness(Freshness.FRESH, "ocr") is Freshness.INFERRED
    assert display_freshness(Freshness.DIMMED, "ocr") is Freshness.DIMMED
    assert display_freshness(Freshness.FRESH, "ocr") is Freshness.INFERRED


def test_precedence_is_total():
    """HIDDEN > DIMMED > INFERRED > FRESH, for every combination."""
    expected = {
        (Freshness.HIDDEN, "uia"): Freshness.HIDDEN,
        (Freshness.HIDDEN, "ocr"): Freshness.HIDDEN,
        (Freshness.DIMMED, "uia"): Freshness.DIMMED,
        (Freshness.DIMMED, "ocr"): Freshness.DIMMED,
        (Freshness.FRESH, "uia"): Freshness.FRESH,
        (Freshness.FRESH, "ocr"): Freshness.INFERRED,
    }
    for (state, source), want in expected.items():
        assert display_freshness(state, source) is want, (state, source)


def test_unrecognized_source_vlm_returns_inferred():
    """An unrecognized source is deliberately treated as inferred, not trusted.

    Tier 3 (VLM pointing model) is planned. If someone adds source="vlm" and
    forgets to touch this function, FRESH here would render a model guess as
    a confirmed control. The fail-safe default is to treat unknowns as
    INFERRED rather than FRESH.
    """
    assert display_freshness(Freshness.FRESH, "vlm") is Freshness.INFERRED


def test_case_mismatched_ocr_returns_inferred():
    """Case-sensitive matching: "OCR" (uppercase) is not recognized as "ocr"."""
    assert display_freshness(Freshness.FRESH, "OCR") is Freshness.INFERRED


def test_empty_string_source_returns_inferred():
    """An empty or missing source is treated as inferred, never trusted."""
    assert display_freshness(Freshness.FRESH, "") is Freshness.INFERRED


def test_uia_source_still_returns_fresh():
    """Explicitly recognized 'uia' source still returns FRESH (unchanged)."""
    assert display_freshness(Freshness.FRESH, "uia") is Freshness.FRESH
