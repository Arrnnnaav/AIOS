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

    # NOTE: this assertion does NOT protect the coordinate space, and an
    # earlier comment here claimed it did. `_declare_signatures()` runs after
    # `AWARENESS = _ensure_dpi_awareness()`, so declaring the setter there
    # cannot affect a call that already happened -- measured: the process
    # stays `system`. What guards the space is
    # `test_the_production_entry_point_still_runs_in_its_measured_space`,
    # which measures the awareness itself. This only pins that the deferred
    # change has not been started.
    assert setter.argtypes is None


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


def _awareness_in(preamble: str) -> tuple[str, str, str]:
    """Measure awareness in a FRESH process. It can only be set once, so an
    in-process assertion measures whatever the test lane imported first."""

    import json
    import subprocess
    import sys

    code = (
        preamble
        + "\n"
        "from ghostcursor.overlay import dpi\n"
        "import json\n"
        "print(json.dumps([dpi.queried_thread_awareness()[0], "
        "dpi.AWARENESS, dpi.coordinate_units()]))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    return tuple(json.loads(out.stdout.strip().splitlines()[-1]))


def test_the_production_entry_point_still_runs_in_its_measured_space():
    """The flip is the worst outcome in this module and was guarded by
    `assert ... or True`, which is a tautology.

    Measured in a fresh process, because awareness can only be set once and an
    in-process check measures whatever the test lane happened to import first.

    D106 defers correcting the malformed setter to its own reviewed decision
    on a scaled display. Until then `ghostcursor.run` must remain SYSTEM
    aware: if it silently became per-monitor-v2, every window rect, UIA rect,
    hint and capture would move at once, and on one monitor at 100% nothing
    else in the suite could tell.
    """

    awareness, declared, units = _awareness_in("import ghostcursor.run")

    assert awareness == "system"
    assert declared == "system"
    assert units == "system_dpi_pixels"


def test_importing_pywinauto_first_changes_the_coordinate_space():
    """Measured, and the reason `dpi.AWARENESS` cannot be trusted.

    pywinauto declares per-monitor awareness at import. Whichever of it and
    `ghostcursor.overlay.dpi` is imported first wins, because awareness is
    once-only -- and `dpi.AWARENESS` reports "system" in BOTH cases, since it
    records which setter path ran rather than what the process became.

    Production is safe only because `ghostcursor/run.py` imports
    `overlay.window` before `perception.uia`. Nothing enforces that ordering;
    this test is what makes a reordering visible.
    """

    awareness, declared, _units = _awareness_in("import pywinauto")

    assert awareness == "per-monitor"
    assert declared == "system"


def test_the_declared_label_and_the_measured_awareness_can_disagree():
    """The single fact the whole queried-awareness design rests on."""

    measured, declared, _units = _awareness_in("import pywinauto")

    assert measured != declared


def test_the_thread_accessor_never_answers_with_process_state():
    """D069's rule applied to this module: a gate must assert provenance, not
    mere completion.

    The older DPI APIs report the PROCESS default. Returning that labelled as
    thread awareness would make `thread_matches_process` trivially true
    exactly when a third-party library has set an exotic thread context --
    which is the one case that check exists to catch. A platform that cannot
    answer the thread question answers `unknown`, and unknown refuses.
    """

    import ctypes

    class _NoThreadApi:
        def __getattr__(self, name):
            if name == "GetThreadDpiAwarenessContext":
                raise AttributeError(name)
            return getattr(ctypes.windll.user32, name)

    original = ctypes.windll.user32
    try:
        ctypes.windll.user32 = _NoThreadApi()
        awareness, api = dpi.queried_thread_awareness()
    finally:
        ctypes.windll.user32 = original

    assert awareness == dpi.UNKNOWN_AWARENESS
    assert api == "none"


def test_a_dark_primary_query_is_visible_rather_than_masked():
    """If the context comparison stops working, the answer must become
    `unknown` -- not a plausible value from a weaker source."""

    import ctypes

    original = dpi._canonical_context
    try:
        dpi._canonical_context = lambda _handle: None
        awareness, api = dpi.queried_thread_awareness()
    finally:
        dpi._canonical_context = original

    assert awareness == dpi.UNKNOWN_AWARENESS
    assert api == "none"
    # And unknown must refuse, not agree with itself.
    unknown = _space(
        thread_awareness=dpi.UNKNOWN_AWARENESS,
        process_awareness=dpi.UNKNOWN_AWARENESS,
        units=dpi.UNKNOWN_AWARENESS,
    )
    assert geometry_is_usable(unknown, unknown) is False


# --- D2: the producer actually brackets ------------------------------------


def test_observe_bracketed_samples_the_space_twice_around_the_read():
    """`after = before` would always hold and never detect anything."""

    first = _space()
    second = _space(thread_awareness="unaware", process_awareness="unaware",
                    units="logical_pixels")
    samples = iter([first, second])
    order: list[str] = []

    def sample():
        order.append("sample")
        return next(samples)

    def read():
        order.append("read")
        return [(1, 2, 3, 4)]

    geometry = observe_bracketed(read, sample=sample)

    assert order == ["sample", "read", "sample"]
    assert geometry.before == first
    assert geometry.after == second
    assert geometry.held is False


def test_a_bracket_whose_samples_differ_refuses_every_rectangle():
    samples = iter(
        [
            _space(),
            _space(thread_awareness="unaware", process_awareness="unaware",
                   units="logical_pixels"),
        ]
    )
    geometry = observe_bracketed(lambda: [(1, 2, 3, 4)], sample=lambda: next(samples))

    assert bracket_disagreements(_space(), geometry) != ()


def test_the_bracket_notices_a_topology_change_not_only_an_awareness_one():
    """A monitor arriving mid-read moves the coordinate space too."""

    samples = iter(
        [_space(), _space(monitors=((0, 0, 960, 1080), (960, 0, 1920, 1080)))]
    )
    geometry = observe_bracketed(lambda: [(1, 2, 3, 4)], sample=lambda: next(samples))

    assert geometry.held is False


# --- D5: the version is pinned ---------------------------------------------


def test_the_contract_version_is_pinned_to_a_literal():
    """Every other test refers to the symbol, so reverting the bump passed
    them all. The bump exists so a peer still sending version 1
    `physical_pixels` cannot silently compare equal."""

    assert CONTRACT_VERSION == 2


def test_a_literal_version_one_record_is_refused():
    record = _space().as_record()
    record["contract_version"] = 1

    assert any("contract version" in r for r in disagreements(_space(), from_record(record)))


# --- D4: the window check is exercised -------------------------------------


def test_window_agrees_reports_a_window_built_in_another_space():
    from ghostcursor.coordinate_space import window_agrees

    original = dpi.queried_window_awareness
    try:
        dpi.queried_window_awareness = lambda _hwnd: ("unaware", "stub")
        reasons = window_agrees(_space(), 1234)
    finally:
        dpi.queried_window_awareness = original

    assert any("was created under" in reason for reason in reasons)


def test_window_agrees_accepts_a_window_in_the_same_space():
    from ghostcursor.coordinate_space import window_agrees

    original = dpi.queried_window_awareness
    try:
        dpi.queried_window_awareness = lambda _hwnd: ("per-monitor-v2", "stub")
        assert window_agrees(_space(), 1234) == ()
    finally:
        dpi.queried_window_awareness = original


def test_an_unreadable_window_awareness_is_refused_not_assumed_to_match():
    """Turning `unknown` into `matches` is exactly what the module forbids."""

    from ghostcursor.coordinate_space import window_agrees

    original = dpi.queried_window_awareness
    try:
        dpi.queried_window_awareness = lambda _hwnd: (dpi.UNKNOWN_AWARENESS, "none")
        reasons = window_agrees(_space(), 1234)
    finally:
        dpi.queried_window_awareness = original

    assert any("could not be read" in reason for reason in reasons)


def test_an_unreadable_window_handle_reports_unknown():
    assert dpi.queried_window_awareness(0)[0] == dpi.UNKNOWN_AWARENESS


# --- D6 and D8: topology ordering and serialization -------------------------


def test_monitor_topology_is_sorted_so_two_processes_agree():
    """Enumeration order is not guaranteed stable between processes, and an
    order difference is not a coordinate-space difference."""

    rects = [
        (None, None, (960, 0, 1920, 1080)),
        (None, None, (0, 0, 960, 1080)),
    ]
    original = dpi.win32api.EnumDisplayMonitors
    try:
        dpi.win32api.EnumDisplayMonitors = lambda: rects
        assert dpi.monitor_topology() == ((0, 0, 960, 1080), (960, 0, 1920, 1080))
        rects.reverse()
        assert dpi.monitor_topology() == ((0, 0, 960, 1080), (960, 0, 1920, 1080))
    finally:
        dpi.win32api.EnumDisplayMonitors = original


def test_a_record_reports_the_number_of_monitors_it_carries():
    two = _space(monitors=((0, 0, 960, 1080), (960, 0, 1920, 1080)))

    assert two.as_record()["monitor_count"] == 2
    assert from_record(two.as_record()) == two


# --- D7: a malformed bracket refuses as a ValueError ------------------------


@pytest.mark.parametrize("side", ["before", "after"])
def test_a_bracket_record_missing_a_side_refuses_rather_than_raising_keyerror(side):
    record = observe_bracketed(lambda: []).as_record()
    del record[side]

    with pytest.raises(ValueError, match="missing"):
        bracket_from_record(record)


@pytest.mark.parametrize("side", ["before", "after"])
def test_a_bracket_side_that_is_not_a_mapping_refuses(side):
    record = observe_bracketed(lambda: []).as_record()
    record[side] = "not-a-space"

    with pytest.raises(ValueError, match="must be a mapping"):
        bracket_from_record(record)


# --- what the ABI table actually covers ------------------------------------


def test_every_api_the_module_declares_is_pinned_by_a_test():
    """The GDI declarations were added with nothing enforcing them: deleting
    GetDC, ReleaseDC, GetDeviceCaps or GetProcessDpiAwareness all passed."""

    import ctypes

    user32 = ctypes.windll.user32
    for name, argtypes, restype in (
        ("GetDC", [ctypes.c_void_p], ctypes.c_void_p),
        ("ReleaseDC", [ctypes.c_void_p, ctypes.c_void_p], ctypes.c_int),
        ("SetProcessDPIAware", [], ctypes.wintypes.BOOL),
    ):
        function = getattr(user32, name)
        assert function.argtypes == argtypes, name
        assert function.restype is restype, name

    caps = ctypes.windll.gdi32.GetDeviceCaps
    assert caps.argtypes == [ctypes.c_void_p, ctypes.c_int]
    assert caps.restype is ctypes.c_int

    awareness = ctypes.windll.shcore.GetProcessDpiAwareness
    assert awareness.argtypes == [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int),
    ]


def test_scale_factor_reports_a_plausible_ratio_and_releases_its_dc():
    """It had zero callers and zero tests, so removing its ReleaseDC -- a real
    handle leak -- passed the suite."""

    import ctypes

    released = []
    real = ctypes.windll

    class _CountingUser32:
        def __getattr__(self, name):
            function = getattr(real.user32, name)
            if name != "ReleaseDC":
                return function

            def counting(hwnd, hdc):
                released.append(hdc)
                return function(hwnd, hdc)

            return counting

    class _Windll:
        def __getattr__(self, name):
            return _CountingUser32() if name == "user32" else getattr(real, name)

    ctypes.windll = _Windll()
    try:
        ratio = dpi.scale_factor()
    finally:
        ctypes.windll = real

    assert 0.5 <= ratio <= 4.0
    assert len(released) == 1, "scale_factor must release the DC it acquires"


# --- awareness_api may not contradict the awareness beside it --------------


def test_a_record_claiming_a_real_awareness_answered_by_no_api_is_refused():
    """Internally impossible: "none" is emitted only alongside unknown
    awareness. It parsed, and 120 of the usable-but-differing pairs a brute
    force found differed only in this field."""

    record = _space().as_record()
    record["awareness_api"] = "thread=none;process=none"

    with pytest.raises(ValueError, match="contradicts thread awareness"):
        from_record(record)


def test_a_record_claiming_unknown_awareness_answered_by_an_api_is_refused():
    record = _space(
        thread_awareness=dpi.UNKNOWN_AWARENESS,
        process_awareness=dpi.UNKNOWN_AWARENESS,
        units=dpi.UNKNOWN_AWARENESS,
    ).as_record()
    record["awareness_api"] = "thread=GetThreadDpiAwarenessContext;process=x"

    with pytest.raises(ValueError, match="contradicts thread awareness"):
        from_record(record)


def test_an_empty_awareness_api_is_refused():
    record = _space().as_record()
    record["awareness_api"] = ""

    with pytest.raises(ValueError, match="non-empty"):
        from_record(record)


# --- the legacy fallback is exercised --------------------------------------


class _FakeWinDLL:
    """A ctypes.windll stand-in that can hide named libraries and functions."""

    def __init__(self, hide_libraries=(), hide_functions=()):
        import ctypes

        self._real = ctypes.windll
        self._hidden_libraries = set(hide_libraries)
        self._hidden_functions = set(hide_functions)

    def __getattr__(self, name):
        if name in self._hidden_libraries:
            raise OSError(f"{name} unavailable")
        library = getattr(self._real, name)
        hidden = self._hidden_functions

        class _Library:
            def __getattr__(self, function):
                if function in hidden:
                    raise AttributeError(function)
                return getattr(library, function)

        return _Library()


def _process_awareness_without(hide_libraries=(), hide_functions=()):
    import ctypes

    original = ctypes.windll
    try:
        ctypes.windll = _FakeWinDLL(hide_libraries, hide_functions)
        return dpi.queried_process_awareness()
    finally:
        ctypes.windll = original


def test_the_first_legacy_rung_answers_when_the_modern_api_is_absent():
    """The fallback feeds process_awareness and therefore
    thread_matches_process, and it had no coverage at all."""

    awareness, api = _process_awareness_without(
        hide_functions={"GetDpiAwarenessContextForProcess"}
    )

    assert api == "GetProcessDpiAwareness"
    assert awareness in {"unaware", "system", "per-monitor"}


def test_the_second_legacy_rung_answers_when_shcore_is_absent_too():
    """Inverting this branch previously passed the entire suite."""

    awareness, api = _process_awareness_without(
        hide_libraries={"shcore"},
        hide_functions={"GetDpiAwarenessContextForProcess"},
    )
    modern, _api = dpi.queried_process_awareness()

    assert api == "IsProcessDPIAware"
    # Must AGREE with the modern reading on this machine. Asserting only
    # "one of {system, unaware}" passed with the branch inverted, which is a
    # rung reporting the opposite of the truth.
    assert awareness == ("system" if modern != "unaware" else "unaware")


def test_awareness_is_unknown_when_nothing_can_answer():
    awareness, api = _process_awareness_without(
        hide_libraries={"shcore"},
        hide_functions={
            "GetDpiAwarenessContextForProcess",
            "GetProcessDpiAwareness",
            "IsProcessDPIAware",
        },
    )

    assert awareness == dpi.UNKNOWN_AWARENESS
    assert api == "none"


# --- guards that must be distinguishable from their neighbours -------------


def test_a_bracket_side_that_is_not_a_mapping_names_the_side():
    """The old assertion matched "must be a mapping", which from_record's own
    top-level message also satisfies -- so the per-side check could be deleted
    and the test still passed."""

    record = observe_bracketed(lambda: []).as_record()
    record["before"] = "not-a-space"

    with pytest.raises(ValueError, match="bracketed geometry before"):
        bracket_from_record(record)


def test_a_monitors_field_that_is_not_a_list_is_refused_as_such():
    record = _space().as_record()
    record["monitors"] = "not-a-list"

    with pytest.raises(ValueError, match="monitors is invalid"):
        from_record(record)
