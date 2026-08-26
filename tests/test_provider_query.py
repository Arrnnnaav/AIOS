"""Provider-query presence rule (D069).

Measured on VS Code 1.134.0 with the installed UIA provider and comtypes 1.4.16:
`FindFirst` returns a non-`None` object with a dead COM pointer when the
condition matches nothing, rather than returning `None`. So a non-`None` return
carries no information, and presence is established only by successfully reading
the required properties.

Three branches, and the third is the one the old code got wrong by flattening
every exception into an empty result:

    required properties read      -> PRESENT (an Element)
    NULL COM pointer ValueError   -> ABSENT  (None)
    any other query/read failure  -> ProviderQueryFault (raised)

The fault must be raised rather than returned so a future caller cannot
accidentally treat it like a false or empty result.
"""

import pytest

from ghostcursor.perception.uia import (
    ProviderQueryFault,
    provider_exact,
)


class _FakeRect:
    left, top, right, bottom = 107, 450, 257, 488


class _GoodInfo:
    """An element whose properties read cleanly."""

    def __init__(self, _raw):
        self.name = " Open Folder..."
        self.control_type = "Button"
        self.automation_id = ""
        self.rectangle = _FakeRect()


def _raising_info(exc):
    class _Info:
        def __init__(self, _raw):
            raise exc

    return _Info


DEAD_POINTER = ValueError("NULL COM pointer access")


def test_successful_property_read_establishes_presence():
    element = provider_exact(lambda: object(), _GoodInfo)

    assert element is not None
    assert element.name == " Open Folder..."
    assert element.control_type == "Button"
    assert element.automation_id == ""
    assert element.bbox == (107, 450, 257, 488)


def test_findfirst_returning_none_is_absence():
    assert provider_exact(lambda: None, _GoodInfo) is None


def test_non_none_dead_pointer_is_absence_not_presence():
    """The whole point: a non-None object is not evidence of existence."""
    assert provider_exact(lambda: object(), _raising_info(DEAD_POINTER)) is None


def test_other_property_read_failure_is_a_fault():
    boom = OSError("provider went away")
    with pytest.raises(ProviderQueryFault):
        provider_exact(lambda: object(), _raising_info(boom))


def test_a_value_error_that_is_not_a_dead_pointer_is_a_fault():
    """Guards against the lazy `except ValueError: return None`.

    Collapsing every ValueError into absence would make a real provider defect
    indistinguishable from an empty screen -- the exact failure shape that let
    Open Folder's tier-1 perception go dark unnoticed.
    """
    with pytest.raises(ProviderQueryFault):
        provider_exact(lambda: object(), _raising_info(ValueError("bad argument")))


def test_findfirst_itself_raising_is_a_fault():
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
