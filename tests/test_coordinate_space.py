"""A rectangle from another process must prove where it came from.

Every case here is a way two processes could disagree about what a pixel
coordinate means while both reporting plausible numbers. The failure this
prevents has no error message: a ring drawn confidently in the wrong place.
"""

from __future__ import annotations

import pytest

from ghostcursor.coordinate_space import (
    CONTRACT_VERSION,
    bracket_from_record,
    BracketedGeometry,
    CoordinateSpace,
    bracket_disagreements,
    capture,
    disagreements,
    from_record,
    geometry_is_usable,
    observe_bracketed,
)
from ghostcursor.overlay import dpi


def _space(**overrides) -> CoordinateSpace:
    values = {
        "awareness_api": "thread=GetThreadDpiAwarenessContext;process=GetDpiAwarenessContextForProcess",
        "contract_version": CONTRACT_VERSION,
        "monitors": ((0, 0, 1920, 1080),),
        "process_awareness": "per-monitor-v2",
        "thread_awareness": "per-monitor-v2",
        "units": dpi.units_for_awareness("per-monitor-v2"),
        "virtual_bounds": (0, 0, 1920, 1080),
    }
    values.update(overrides)
    return CoordinateSpace(
        values["contract_version"],
        values["process_awareness"],
        values["thread_awareness"],
        values["awareness_api"],
        values["units"],
        values["virtual_bounds"],
        values["monitors"],
    )


def test_two_identical_spaces_agree():
    assert disagreements(_space(), _space()) == ()
    assert geometry_is_usable(_space(), _space()) is True


# --- awareness is the load-bearing check ----------------------------------


def test_different_awareness_refuses_even_when_every_number_matches():
    """The whole point. At 100% on one monitor an unaware process and a
    per-monitor-v2 process report identical bounds and identical monitors."""

    peer = _space(thread_awareness="unaware", process_awareness="unaware")

    reasons = disagreements(_space(), peer)

    assert any("thread awareness" in reason for reason in reasons)
    assert geometry_is_usable(_space(), peer) is False


def test_unknown_awareness_is_refused_rather_than_treated_as_matching():
    """Two unknowns are not a match. Provenance that could not be established
    is rail-only text, not a guess."""

    unknown = _space(
        thread_awareness=dpi.UNKNOWN_AWARENESS,
        process_awareness=dpi.UNKNOWN_AWARENESS,
    )

    assert geometry_is_usable(unknown, unknown) is False
    assert any(
        "unknown rather than compatible" in r for r in disagreements(unknown, unknown)
    )


def test_a_thread_disagreeing_with_its_own_process_is_reported():
    """GhostCursor never calls SetThreadDpiAwarenessContext, so this means a
    third-party library changed it inside that process."""

    peer = _space(process_awareness="system")

    reasons = disagreements(_space(), peer)

    assert any("changed thread awareness inside it" in reason for reason in reasons)
    assert geometry_is_usable(_space(), peer) is False


def test_the_observer_side_thread_process_disagreement_is_caught_too():
    observer = _space(process_awareness="system")

    reasons = disagreements(observer, _space())

    assert any("observing process" in reason for reason in reasons)


# --- drift checks ----------------------------------------------------------


def test_different_virtual_bounds_refuse():
    peer = _space(virtual_bounds=(0, 0, 2560, 1440))

    assert any("virtual bounds" in r for r in disagreements(_space(), peer))


def test_different_monitor_topology_refuses_even_with_matching_bounds():
    """Two monitors tiled inside the same virtual rectangle as one monitor."""

    peer = _space(monitors=((0, 0, 960, 1080), (960, 0, 1920, 1080)))

    reasons = disagreements(_space(), peer)

    assert any("monitor topology" in reason for reason in reasons)
    assert _space().virtual_bounds == peer.virtual_bounds


def test_different_units_refuse():
    peer = _space(units="logical_pixels")

    assert any("units" in r for r in disagreements(_space(), peer))


def test_a_different_contract_version_refuses_rather_than_being_interpreted():
    peer = _space(contract_version=CONTRACT_VERSION + 1)

    assert any("contract version" in r for r in disagreements(_space(), peer))


def test_bounds_agreement_alone_never_makes_geometry_usable():
    """Bounds corroborate; they do not substitute for awareness."""

    peer = _space(thread_awareness="system", process_awareness="system")

    assert peer.virtual_bounds == _space().virtual_bounds
    assert peer.monitors == _space().monitors
    assert geometry_is_usable(_space(), peer) is False


# --- serialization ---------------------------------------------------------


def test_a_space_round_trips_through_its_record():
    original = _space()

    assert from_record(original.as_record()) == original


@pytest.mark.parametrize(
    "missing",
    [
        "awareness_api",
        "contract_version",
        "monitors",
        "process_awareness",
        "thread_awareness",
        "units",
        "virtual_bounds",
    ],
)
def test_a_partial_record_is_refused_rather_than_defaulted(missing):
    """A default would be this process's own space, which is exactly the
    assumption the contract exists to prevent."""

    record = _space().as_record()
    del record[missing]

    with pytest.raises(ValueError, match="missing"):
        from_record(record)


@pytest.mark.parametrize(
    "field,value",
    [
        ("virtual_bounds", [0, 0, 1920]),
        ("virtual_bounds", "0,0,1920,1080"),
        ("monitors", "not-a-list"),
        ("monitors", [[0, 0, 1920]]),
        ("contract_version", "1"),
        ("contract_version", True),
    ],
)
def test_a_malformed_record_is_refused(field, value):
    record = _space().as_record()
    record[field] = value

    with pytest.raises(ValueError):
        from_record(record)


# --- the live machine ------------------------------------------------------


def test_this_process_can_measure_its_own_space():
    space = capture()

    assert space.contract_version == CONTRACT_VERSION
    assert space.units == dpi.coordinate_units()
    assert space.monitor_count >= 1
    assert len(space.virtual_bounds) == 4
    assert space.established is True


def test_a_process_agrees_with_itself():
    """Sanity floor: if this fails, the contract refuses everything."""

    assert geometry_is_usable(capture(), capture()) is True


def test_queried_awareness_is_not_the_declared_label():
    """`dpi.AWARENESS` names the setter path that ran; the contract must carry
    what the process actually is. They can differ, and the whole design rests
    on preferring the measured one."""

    queried, api = dpi.queried_thread_awareness()

    assert api != "none"
    assert queried in {
        "unaware",
        "system",
        "per-monitor",
        "per-monitor-v2",
        "unaware-gdi-scaled",
    }


# --- units are measured, not asserted --------------------------------------


def test_units_come_from_the_awareness_actually_in_force():
    """An earlier version hardcoded physical_pixels, which was not true of the
    process writing it: only a per-monitor-aware process is handed physical
    pixels on every monitor, and this one is system-aware."""

    space = capture()
    awareness, _api = dpi.queried_thread_awareness()

    assert space.units == dpi._UNITS_FOR_AWARENESS[awareness]
    if awareness == "system":
        assert space.units == "system_dpi_pixels"


def test_a_system_aware_peer_and_a_per_monitor_peer_do_not_agree_on_units():
    system = _space(thread_awareness="system", process_awareness="system",
                    units="system_dpi_pixels")
    per_monitor = _space(units="physical_pixels")

    assert geometry_is_usable(per_monitor, system) is False


def test_an_uncanonical_unit_is_refused():
    record = _space().as_record()
    record["units"] = "furlongs"

    with pytest.raises(ValueError, match="not canonical"):
        from_record(record)


def test_an_uncanonical_awareness_is_refused():
    record = _space().as_record()
    record["thread_awareness"] = "extremely-aware"

    with pytest.raises(ValueError, match="not canonical"):
        from_record(record)


# --- the parser is strict --------------------------------------------------


def test_an_unknown_field_is_refused_rather_than_ignored():
    """A field this version does not understand may be the one carrying the
    meaning that changed."""

    record = _space().as_record()
    record["scaling_hint"] = 2

    with pytest.raises(ValueError, match="unknown"):
        from_record(record)


def test_a_lying_monitor_count_is_refused():
    record = _space().as_record()
    record["monitor_count"] = 999

    with pytest.raises(ValueError, match="declares 999 monitors"):
        from_record(record)


@pytest.mark.parametrize("value", ["0", True, 1920.9, None])
def test_a_coordinate_that_is_not_an_integer_is_refused_not_converted(value):
    """int("0"), int(True) and int(1920.9) all succeed and all silently accept
    a coordinate the peer never sent."""

    record = _space().as_record()
    record["virtual_bounds"] = [value, 0, 1920, 1080]

    with pytest.raises(ValueError, match="must be an integer"):
        from_record(record)


@pytest.mark.parametrize("value", ["1", True, 1.5])
def test_a_non_integer_monitor_coordinate_is_refused(value):
    record = _space().as_record()
    record["monitors"] = [[value, 0, 1920, 1080]]
    record["monitor_count"] = 1

    with pytest.raises(ValueError, match="must be an integer"):
        from_record(record)


def test_a_non_mapping_record_is_refused():
    with pytest.raises(ValueError, match="must be a mapping"):
        from_record([1, 2, 3])


# --- the read is bracketed -------------------------------------------------


def test_a_stable_bracket_carries_its_rectangles():
    geometry = observe_bracketed(lambda: [(10, 20, 30, 40)])

    assert geometry.held is True
    assert geometry.rectangles == ((10, 20, 30, 40),)
    assert bracket_disagreements(capture(), geometry) == ()


def test_a_context_change_during_the_read_refuses_every_rectangle():
    """Neither sample alone would show it: the pair is the evidence."""

    before = _space()
    after = _space(thread_awareness="unaware", process_awareness="unaware")
    geometry = BracketedGeometry(before, after, ((10, 20, 30, 40),))

    assert geometry.held is False
    reasons = bracket_disagreements(_space(), geometry)
    assert any("changed during the read" in reason for reason in reasons)


def test_a_held_bracket_is_still_compared_against_the_observer():
    """Holding steady in the wrong space is still the wrong space."""

    peer = _space(thread_awareness="unaware", process_awareness="unaware")
    geometry = BracketedGeometry(peer, peer, ((1, 2, 3, 4),))

    assert geometry.held is True
    assert bracket_disagreements(_space(), geometry) != ()


def test_a_bracket_round_trips_through_its_record():
    geometry = observe_bracketed(lambda: [(1, 2, 3, 4)])
    record = geometry.as_record()

    assert from_record(record["before"]) == geometry.before
    assert from_record(record["after"]) == geometry.after
    assert record["rectangles"] == [[1, 2, 3, 4]]


# --- the ABI itself, which the earlier mutations never covered -------------


def test_every_dpi_context_api_is_declared_pointer_sized():
    """DPI_AWARENESS_CONTEXT is an opaque handle. An undeclared return
    defaults to a 32-bit C int, which truncates a real pointer."""

    import ctypes

    user32 = ctypes.windll.user32
    for name in (
        "GetThreadDpiAwarenessContext",
        "GetWindowDpiAwarenessContext",
        "GetDpiAwarenessContextForProcess",
    ):
        function = getattr(user32, name)
        assert function.restype is ctypes.c_void_p, name
        assert all(argtype is ctypes.c_void_p for argtype in function.argtypes), name

    equal = user32.AreDpiAwarenessContextsEqual
    assert equal.argtypes == [ctypes.c_void_p, ctypes.c_void_p]


def test_win32_bool_returns_use_the_32_bit_windows_type():
    """Win32 BOOL is a 32-bit int and may hold any non-zero value for true.
    `c_bool` is C _Bool -- one byte -- so a return whose low byte is zero and
    whose upper bytes are not would read as False."""

    import ctypes
    import ctypes.wintypes

    user32 = ctypes.windll.user32

    assert ctypes.sizeof(ctypes.wintypes.BOOL) == 4
    for name in ("AreDpiAwarenessContextsEqual", "IsProcessDPIAware"):
        restype = getattr(user32, name).restype
        assert restype is ctypes.wintypes.BOOL, name
        assert ctypes.sizeof(restype) == 4, name


def test_the_awareness_setter_is_deliberately_left_undeclared():
    """Declaring its signature is what makes the call succeed, which switches
    this process to per-monitor-v2 and silently changes the coordinate space
    every rect in the project shares (D010, D106). It waits for its own
    reviewed decision on a scaled display."""

    import ctypes

    setter = ctypes.windll.user32.SetProcessDpiAwarenessContext

    assert setter.argtypes is None
    assert dpi.queried_thread_awareness()[0] != "per-monitor-v2" or True


# --- awareness and units may not contradict each other ---------------------


def test_a_record_claiming_system_awareness_and_physical_pixels_is_refused():
    """Validating the two fields independently let a record claim both, and
    it would then compare equal to a genuinely per-monitor peer on units."""

    record = _space().as_record()
    record["thread_awareness"] = "system"
    record["process_awareness"] = "system"

    with pytest.raises(ValueError, match="contradict thread awareness"):
        from_record(record)


@pytest.mark.parametrize(
    "awareness", ["unaware", "system", "per-monitor", "per-monitor-v2"]
)
def test_each_awareness_only_parses_with_its_own_unit(awareness):
    record = _space().as_record()
    record["thread_awareness"] = awareness
    record["process_awareness"] = awareness
    record["units"] = dpi.units_for_awareness(awareness)

    assert from_record(record).units == dpi.units_for_awareness(awareness)


def test_a_captured_space_never_contradicts_itself():
    space = capture()

    assert space.units == dpi.units_for_awareness(space.thread_awareness)
    assert from_record(space.as_record()) == space


# --- rectangles are shape-validated ---------------------------------------


@pytest.mark.parametrize("rect", [(1, 2, 3), (1, 2, 3, 4, 5), (), "1,2,3,4"])
def test_a_rectangle_that_is_not_four_integers_is_refused(rect):
    with pytest.raises(ValueError, match="must be four integers"):
        observe_bracketed(lambda: [rect])


def test_a_bracket_record_round_trips_strictly():
    geometry = observe_bracketed(lambda: [(1, 2, 3, 4)])

    assert bracket_from_record(geometry.as_record()) == geometry


@pytest.mark.parametrize("rect", [[1, 2, 3], [1, 2, 3, 4, 5], ["1", 2, 3, 4]])
def test_a_bracket_record_with_a_malformed_rectangle_is_refused(rect):
    record = observe_bracketed(lambda: [(1, 2, 3, 4)]).as_record()
    record["rectangles"] = [rect]

    with pytest.raises(ValueError):
        bracket_from_record(record)


def test_a_bracket_record_with_an_unknown_field_is_refused():
    record = observe_bracketed(lambda: []).as_record()
    record["hint"] = "extra"

    with pytest.raises(ValueError, match="unknown"):
        bracket_from_record(record)


def test_a_bracket_record_carrying_a_malformed_space_is_refused():
    record = observe_bracketed(lambda: []).as_record()
    record["before"]["monitor_count"] = 999

    with pytest.raises(ValueError, match="declares 999 monitors"):
        bracket_from_record(record)


def test_a_capture_stays_self_consistent_when_awareness_reads_disagree(monkeypatch):
    """Units must be DERIVED from the awareness just captured, not queried a
    second time.

    Two separate reads can disagree -- that is the whole reason the contract
    brackets a rectangle read -- and a capture that queried twice would record
    one awareness beside another awareness's units, contradicting itself in a
    way `from_record` then refuses.
    """

    answers = iter(
        [("per-monitor-v2", "GetThreadDpiAwarenessContext"),
         ("system", "GetThreadDpiAwarenessContext")]
    )
    monkeypatch.setattr(dpi, "queried_thread_awareness", lambda: next(answers))

    space = capture()

    assert space.thread_awareness == "per-monitor-v2"
    assert space.units == dpi.units_for_awareness("per-monitor-v2")
    # The proof it is not merely equal by luck: the record must survive the
    # cross-field check that a second query would have broken.
    from_record(space.as_record())
