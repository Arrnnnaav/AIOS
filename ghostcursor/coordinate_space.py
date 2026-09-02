"""The cross-process coordinate contract a rectangle must satisfy to be drawn.

Act's verification runs in a separate signed process. When that process starts
returning screen rectangles for the session to point at, two processes have to
agree about what a pixel coordinate means -- and they can disagree silently.
A rectangle is four integers; nothing about it says which coordinate space it
came from, so a mismatch produces a ring drawn confidently in the wrong place
rather than an error.

**Declared awareness is not measured awareness.** `dpi.AWARENESS` records
which setter path ran, and awareness cannot be changed once set, so a process
where something already declared it reports the fallback label whatever it
actually is. Two processes can print the same label from different coordinate
spaces. Every value here is QUERIED, and each carries the API that answered so
a fallback is visible instead of silent.

**Units are measured, not asserted.** An earlier version of this module
hardcoded `physical_pixels`, which was not true of the process writing it:
only a per-monitor-aware process is handed physical pixels on every monitor,
and this one is system-aware. `dpi.coordinate_units()` derives the unit from
the awareness actually in force, so a system-aware process says
`system_dpi_pixels` and cannot claim a precision it does not have.

**Bounds and topology are drift checks, not substitutes.** Two processes on
one desktop that disagree about the virtual-desktop rectangle are certainly in
different spaces. Agreeing about it proves much less: at 100% scaling on a
single monitor, an unaware process and a per-monitor-v2 process report
identical numbers. Awareness equality is the load-bearing check and the bounds
comparison is the cheap corroboration, never the other way round.

**Unknown is refused, never assumed compatible.** A machine where no API could
answer produces `UNKNOWN_AWARENESS`, and two unknowns do not match. Geometry
whose provenance cannot be established is rail-only text, not a guess.

**A read is bracketed.** Thread awareness is sampled before and after every
rectangle observation, because a context that changes mid-read leaves
rectangles from two different spaces in one response, and neither sample alone
would show it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from ghostcursor.overlay import dpi

#: Bumped whenever the meaning of any field below changes. Two processes
#: running different contract versions are not comparable, and the mismatch is
#: reported rather than resolved -- a newer reader guessing at an older
#: producer's meaning is how a silent coordinate error gets reintroduced.
CONTRACT_VERSION = 2

#: Every unit an honest producer may name, derived from the awareness modes
#: that produce them. An arbitrary string is refused: a peer naming a unit
#: that does not exist would compare equal to itself.
CANONICAL_UNITS = frozenset(dpi._UNITS_FOR_AWARENESS.values()) | {dpi.UNKNOWN_AWARENESS}

_FIELDS = (
    "awareness_api",
    "contract_version",
    "monitor_count",
    "monitors",
    "process_awareness",
    "thread_awareness",
    "units",
    "virtual_bounds",
)


def _exact_int(value: object, label: str) -> int:
    """An int, and not a bool, a float, or a string that looks like one.

    `int("0")`, `int(True)` and `int(1920.9)` all succeed and all silently
    accept a coordinate the peer did not send. A wire value that is not
    already the right type is a malformed record, not an input to convert.
    """

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"coordinate space {label} must be an integer")
    return value


def _rectangle(value: object, label: str) -> tuple[int, int, int, int]:
    """Exactly four integers. Not three, not five, not coerced.

    Validating each coordinate's type while never counting them let a
    three-coordinate rectangle through, and a renderer handed one would either
    raise deep inside a paint or silently draw something else.
    """

    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"coordinate space {label} must be four integers")
    return tuple(_exact_int(part, label) for part in value)


@dataclass(frozen=True)
class CoordinateSpace:
    """One process's measured account of the space its rectangles live in."""

    contract_version: int
    process_awareness: str
    thread_awareness: str
    awareness_api: str
    units: str
    virtual_bounds: tuple[int, int, int, int]
    monitors: tuple[tuple[int, int, int, int], ...]

    @property
    def monitor_count(self) -> int:
        return len(self.monitors)

    @property
    def established(self) -> bool:
        """False when awareness could not be read on this machine."""

        return (
            self.thread_awareness != dpi.UNKNOWN_AWARENESS
            and self.process_awareness != dpi.UNKNOWN_AWARENESS
            and self.units != dpi.UNKNOWN_AWARENESS
        )

    @property
    def thread_matches_process(self) -> bool:
        """GhostCursor never calls SetThreadDpiAwarenessContext.

        Threads inherit the process default, so a disagreement here means a
        third-party library changed it inside this process. That is a finding
        about the environment, not a detail to reconcile.
        """

        return self.thread_awareness == self.process_awareness

    def as_record(self) -> dict[str, Any]:
        return {
            "awareness_api": self.awareness_api,
            "contract_version": self.contract_version,
            "monitor_count": self.monitor_count,
            "monitors": [list(rect) for rect in self.monitors],
            "process_awareness": self.process_awareness,
            "thread_awareness": self.thread_awareness,
            "units": self.units,
            "virtual_bounds": list(self.virtual_bounds),
        }


def capture() -> CoordinateSpace:
    """Measure this process's coordinate space right now."""

    thread_awareness, thread_api = dpi.queried_thread_awareness()
    process_awareness, process_api = dpi.queried_process_awareness()
    return CoordinateSpace(
        CONTRACT_VERSION,
        process_awareness,
        thread_awareness,
        f"thread={thread_api};process={process_api}",
        # Derived from the awareness just captured, not queried again: two
        # separate reads could disagree and the record would then contradict
        # itself.
        dpi.units_for_awareness(thread_awareness),
        dpi.virtual_screen_rect(),
        dpi.monitor_topology(),
    )


def from_record(value: Mapping[str, Any]) -> CoordinateSpace:
    """Rebuild a peer's contract from its serialized form, strictly.

    Nothing here is repaired, coerced, or defaulted. A default would be this
    process's own space, which is exactly the assumption the contract exists
    to prevent, and a coercion would accept a value the peer never sent.
    Unknown fields are refused too: a field this version does not understand
    may be the one carrying the meaning that changed.
    """

    if not isinstance(value, Mapping):
        raise ValueError("coordinate space must be a mapping")
    present = set(value)
    missing = set(_FIELDS) - present
    if missing:
        raise ValueError("coordinate space is missing " + ", ".join(sorted(missing)))
    extra = present - set(_FIELDS)
    if extra:
        raise ValueError("coordinate space has unknown " + ", ".join(sorted(extra)))

    version = _exact_int(value["contract_version"], "contract_version")

    for label in ("thread_awareness", "process_awareness"):
        if value[label] not in dpi.AWARENESS_VALUES:
            raise ValueError(
                f"coordinate space {label} {value[label]!r} is not canonical"
            )
    if value["units"] not in CANONICAL_UNITS:
        raise ValueError(f"coordinate space units {value['units']!r} is not canonical")
    expected_units = dpi.units_for_awareness(value["thread_awareness"])
    if value["units"] != expected_units:
        # Validating the two fields independently let a record claim
        # system awareness AND physical pixels, which D106 says cannot both be
        # true -- and which would compare equal to a genuinely per-monitor
        # peer on the units check.
        raise ValueError(
            f"coordinate space units {value['units']!r} contradict thread "
            f"awareness {value['thread_awareness']!r}, which reports "
            f"{expected_units!r}"
        )
    if not isinstance(value["awareness_api"], str):
        raise ValueError("coordinate space awareness_api must be a string")

    parsed_bounds = _rectangle(value["virtual_bounds"], "virtual_bounds")

    monitors = value["monitors"]
    if not isinstance(monitors, (list, tuple)):
        raise ValueError("coordinate space monitors is invalid")
    parsed = [_rectangle(rect, "monitor rectangle") for rect in monitors]

    declared = _exact_int(value["monitor_count"], "monitor_count")
    if declared != len(parsed):
        raise ValueError(
            f"coordinate space declares {declared} monitors but carries {len(parsed)}"
        )

    return CoordinateSpace(
        version,
        value["process_awareness"],
        value["thread_awareness"],
        value["awareness_api"],
        value["units"],
        parsed_bounds,
        tuple(parsed),
    )


@dataclass(frozen=True)
class BracketedGeometry:
    """Rectangles read between two awareness samples.

    A thread context that changes mid-read leaves rectangles from two
    different spaces in one response, and neither sample on its own would show
    it. The pair is the evidence; the rectangles are only usable if it holds.
    """

    before: CoordinateSpace
    after: CoordinateSpace
    rectangles: tuple[tuple[int, int, int, int], ...] = ()

    @property
    def held(self) -> bool:
        """True when the space did not move across the read."""

        return self.before == self.after

    def as_record(self) -> dict[str, Any]:
        return {
            "after": self.after.as_record(),
            "before": self.before.as_record(),
            "rectangles": [list(rect) for rect in self.rectangles],
        }


def bracket_from_record(value: Mapping[str, Any]) -> "BracketedGeometry":
    """Rebuild a peer's bracketed read, as strictly as a CoordinateSpace.

    Reconstructing this from arbitrary fields would reintroduce every
    permissiveness `from_record` was hardened against, one level up.
    """

    if not isinstance(value, Mapping):
        raise ValueError("bracketed geometry must be a mapping")
    fields = {"after", "before", "rectangles"}
    missing = fields - set(value)
    if missing:
        raise ValueError("bracketed geometry is missing " + ", ".join(sorted(missing)))
    extra = set(value) - fields
    if extra:
        raise ValueError("bracketed geometry has unknown " + ", ".join(sorted(extra)))
    rectangles = value["rectangles"]
    if not isinstance(rectangles, (list, tuple)):
        raise ValueError("bracketed geometry rectangles is invalid")
    return BracketedGeometry(
        from_record(value["before"]),
        from_record(value["after"]),
        tuple(_rectangle(rect, "rectangle") for rect in rectangles),
    )


def observe_bracketed(read: Callable[[], Sequence[Sequence[int]]]) -> BracketedGeometry:
    """Sample the space, run one rectangle read, sample it again."""

    before = capture()
    rectangles = tuple(_rectangle(rect, "rectangle") for rect in read())
    return BracketedGeometry(before, capture(), rectangles)


def disagreements(observer: CoordinateSpace, peer: CoordinateSpace) -> tuple[str, ...]:
    """Every reason these two accounts are not comparable, strongest first.

    Returns an empty tuple only when a rectangle produced by ``peer`` may be
    drawn in ``observer``'s space.
    """

    reasons: list[str] = []
    if observer.contract_version != peer.contract_version:
        reasons.append(
            f"contract version {peer.contract_version} does not match "
            f"{observer.contract_version}"
        )
    if not observer.established or not peer.established:
        reasons.append(
            "DPI awareness could not be established, so the coordinate space "
            "is unknown rather than compatible"
        )
    if observer.thread_awareness != peer.thread_awareness:
        reasons.append(
            f"thread awareness {peer.thread_awareness!r} does not match "
            f"{observer.thread_awareness!r}"
        )
    if not observer.thread_matches_process:
        reasons.append(
            "the observing process's thread and process awareness disagree, "
            "which means something changed thread awareness inside it"
        )
    if not peer.thread_matches_process:
        reasons.append(
            "the producing process's thread and process awareness disagree, "
            "which means something changed thread awareness inside it"
        )
    if observer.units != peer.units:
        reasons.append(f"units {peer.units!r} do not match {observer.units!r}")
    if observer.virtual_bounds != peer.virtual_bounds:
        reasons.append(
            f"virtual bounds {peer.virtual_bounds} do not match "
            f"{observer.virtual_bounds}"
        )
    if observer.monitors != peer.monitors:
        reasons.append(
            f"monitor topology {peer.monitors} does not match {observer.monitors}"
        )
    return tuple(reasons)


def bracket_disagreements(
    observer: CoordinateSpace, geometry: BracketedGeometry
) -> tuple[str, ...]:
    """Whether a bracketed read may be drawn in ``observer``'s space.

    Checks the bracket itself first: rectangles read across a context change
    are not merely suspect, they may individually belong to different spaces,
    so no comparison against the observer can rescue them.
    """

    if not geometry.held:
        return (
            "the producing thread's DPI awareness changed during the read, so "
            "these rectangles may not share one coordinate space",
        )
    return disagreements(observer, geometry.before)


def geometry_is_usable(observer: CoordinateSpace, peer: CoordinateSpace) -> bool:
    """Whether a rectangle from ``peer`` may be drawn by ``observer``."""

    return not disagreements(observer, peer)


def window_agrees(space: CoordinateSpace, hwnd: int) -> tuple[str, ...]:
    """Check the overlay WINDOW was created under the thread's awareness.

    A window keeps the awareness of the thread that created it, so a process
    can hold a window whose space differs from the thread now painting into
    it. Checked separately from :func:`disagreements` because it is a property
    of one process's window rather than of two processes' agreement.
    """

    awareness, _api = dpi.queried_window_awareness(hwnd)
    if awareness == dpi.UNKNOWN_AWARENESS:
        return ("the overlay window's DPI awareness could not be read",)
    if awareness != space.thread_awareness:
        return (
            f"the overlay window was created under {awareness!r} but the "
            f"painting thread is {space.thread_awareness!r}",
        )
    return ()


__all__ = [
    "CANONICAL_UNITS",
    "CONTRACT_VERSION",
    "BracketedGeometry",
    "CoordinateSpace",
    "bracket_disagreements",
    "bracket_from_record",
    "capture",
    "disagreements",
    "from_record",
    "geometry_is_usable",
    "observe_bracketed",
    "window_agrees",
]
