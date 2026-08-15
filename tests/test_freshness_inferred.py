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
