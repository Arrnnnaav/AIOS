"""Provider-query presence rule (D069).

Measured on VS Code 1.134.0 with the installed UIA provider and comtypes 1.4.16:
`FindFirst` returns a non-`None` object with a dead COM pointer when the
condition matches nothing, rather than returning `None`. So a non-`None` return
carries no information, and presence is established only by successfully reading
the required properties. `FindFirst` also cannot report that a *second* match
exists, which makes `exactly_one` unprovable with it, so the query is built on
`FindAll`: `Length = 0` is an honest absence and the count is real.

Four branches, and the third is the one the old code got wrong by flattening
every exception into an empty result:

    required properties read      -> PRESENT (an Element in the list)
    NULL COM pointer ValueError   -> ABSENT  (that result is dropped)
    any other query/read failure  -> ProviderQueryFault (raised)
    several matches, exactly_one  -> SelectorAmbiguityFault (raised)

The fault must be raised rather than returned so a future caller cannot
accidentally treat it like a false or empty result.
"""

import pytest

from ghostcursor.perception.uia import (
    AT_LEAST_ONE,
    EXACTLY_ONE,
    ProviderQueryFault,
    SelectorAmbiguityFault,
    element_array_items,
    provider_exact,
)


class _FakeRect:
    left, top, right, bottom = 107, 450, 257, 488


class _GoodInfo:
    """An element whose properties read cleanly."""

    def __init__(self, _raw):
        self.name = " Open Folder..."
        self.control_type = "Button"
        self.automation_id = ""
        self.rectangle = _FakeRect()


def _raising_info(exc):
    class _Info:
        def __init__(self, _raw):
            raise exc

    return _Info


DEAD_POINTER = ValueError("NULL COM pointer access")


def _results(*raws):
    """A `find_all` returning exactly these raw results."""
    return lambda: list(raws)


def test_successful_property_read_establishes_presence():
    found = provider_exact(_results(object()), _GoodInfo)

    assert len(found) == 1
    element = found[0]
    assert element.name == " Open Folder..."
    assert element.control_type == "Button"
    assert element.automation_id == ""
    assert element.bbox == (107, 450, 257, 488)


def test_an_empty_result_set_is_a_clean_absence():
    """`Length = 0` is the honest absence `FindFirst` could not report."""
    assert provider_exact(_results(), _GoodInfo) == []


def test_a_dead_pointer_result_is_absence_not_presence():
    """The whole point: a non-None object is not evidence of existence."""
    assert provider_exact(_results(object()), _raising_info(DEAD_POINTER)) == []


def test_a_dead_result_does_not_count_toward_cardinality():
    """Presence requires a successful read, so a dead result is not a match.

    Counting it would let a control that no longer exists make a live one look
    ambiguous, and an action selector would fault instead of pointing at the
    single control actually on screen.
    """
    reads = iter([_GoodInfo, _raising_info(DEAD_POINTER)])

    def _make_info(raw):
        return next(reads)(raw)

    found = provider_exact(
        _results(object(), object()), _make_info, cardinality=EXACTLY_ONE
    )
    assert len(found) == 1


def test_two_matches_fault_an_exactly_one_selector():
    """The reason the query cannot be built on `FindFirst`.

    `FindFirst` would have answered with the first of these and no caller
    could ever have known a second existed.
    """
    with pytest.raises(SelectorAmbiguityFault) as caught:
        provider_exact(_results(object(), object()), _GoodInfo, cardinality=EXACTLY_ONE)
    assert "matched 2 controls" in str(caught.value)


def test_two_matches_are_allowed_for_a_verification_selector():
    found = provider_exact(
        _results(object(), object()), _GoodInfo, cardinality=AT_LEAST_ONE
    )
    assert len(found) == 2


def test_results_without_identity_are_both_retained():
    """Two results agreeing on every published field are still two controls.

    Value equality cannot separate them: VS Code publishes empty AutomationIds
    and repeats accessible names, so collapsing on value would hide a real
    second match from the ambiguity check.
    """
    found = provider_exact(
        _results(object(), object()), _GoodInfo, cardinality=AT_LEAST_ONE
    )
    assert len(found) == 2


def test_results_deduplicate_when_backend_identity_proves_equality():
    class _SameIdentity(_GoodInfo):
        runtime_id = (42, 7)

    found = provider_exact(
        _results(object(), object()), _SameIdentity, cardinality=EXACTLY_ONE
    )
    assert len(found) == 1, "one control reached twice is one result"


def test_distinct_backend_identities_are_not_collapsed():
    identities = iter([(42, 7), (42, 8)])

    def _make_info(raw):
        info = _GoodInfo(raw)
        info.runtime_id = next(identities)
        return info

    found = provider_exact(
        _results(object(), object()), _make_info, cardinality=AT_LEAST_ONE
    )
    assert len(found) == 2


def test_element_array_items_reads_length_and_each_index():
    class _Array:
        Length = 3

        def __init__(self):
            self.requested = []

        def GetElement(self, index):
            self.requested.append(index)
            return f"raw-{index}"

    array = _Array()
    assert element_array_items(array) == ["raw-0", "raw-1", "raw-2"]
    assert array.requested == [0, 1, 2]


def test_other_property_read_failure_is_a_fault():
    boom = OSError("provider went away")
    with pytest.raises(ProviderQueryFault):
        provider_exact(_results(object()), _raising_info(boom))


def test_a_value_error_that_is_not_a_dead_pointer_is_a_fault():
    """Guards against the lazy `except ValueError: return None`.

    Collapsing every ValueError into absence would make a real provider defect
    indistinguishable from an empty screen -- the exact failure shape that let
    Open Folder's tier-1 perception go dark unnoticed.
    """
    with pytest.raises(ProviderQueryFault):
        provider_exact(_results(object()), _raising_info(ValueError("bad argument")))


def test_the_query_itself_raising_is_a_fault():
    def _boom():
        raise OSError("RPC server unavailable")

    with pytest.raises(ProviderQueryFault):
        provider_exact(_boom, _GoodInfo)


def test_fault_preserves_the_original_error_as_its_cause():
    original = OSError("RPC server unavailable")

    def _boom():
        raise original

    with pytest.raises(ProviderQueryFault) as caught:
        provider_exact(_boom, _GoodInfo)
    assert caught.value.__cause__ is original
