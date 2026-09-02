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
spaces. Every value in this contract is therefore QUERIED
(`dpi.queried_thread_awareness()` and friends), and each carries the API that
answered so a fallback is visible instead of silent.

**Bounds and topology are drift checks, not substitutes.** Two processes on
one desktop that disagree about the virtual-desktop rectangle are certainly in
different spaces. Agreeing about it proves much less: at 100% scaling on a
single monitor, an unaware process and a per-monitor-v2 process report
identical numbers. Awareness equality is the load-bearing check and the bounds
comparison is the cheap corroboration, never the other way round.

**Unknown is refused, never assumed compatible.** A machine where no API could
answer produces `UNKNOWN_AWARENESS`, and two unknowns do not match. Geometry
whose provenance cannot be established is rail-only text, not a guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ghostcursor.overlay import dpi

#: Bumped whenever the meaning of any field below changes. Two processes
#: running different contract versions are not comparable, and the mismatch is
#: reported rather than resolved -- a newer reader guessing at an older
#: producer's meaning is how a silent coordinate error gets reintroduced.
CONTRACT_VERSION = 1

#: The only unit this contract carries. Named rather than assumed so a future
#: producer that starts reporting logical pixels fails the comparison instead
#: of being drawn.
PHYSICAL_PIXELS = "physical_pixels"


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
        PHYSICAL_PIXELS,
        dpi.virtual_screen_rect(),
        dpi.monitor_topology(),
    )


def from_record(value: Mapping[str, Any]) -> CoordinateSpace:
    """Rebuild a peer's contract from its serialized form.

    Deliberately strict. A malformed or partial contract is not repaired with
    defaults: a default would be this process's own space, which is exactly
    the assumption the contract exists to prevent.
    """

    required = {
        "awareness_api",
        "contract_version",
        "monitors",
        "process_awareness",
        "thread_awareness",
        "units",
        "virtual_bounds",
    }
    missing = required - set(value)
    if missing:
        raise ValueError("coordinate space is missing " + ", ".join(sorted(missing)))
    bounds = value["virtual_bounds"]
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        raise ValueError("coordinate space virtual_bounds is invalid")
    monitors = value["monitors"]
    if not isinstance(monitors, (list, tuple)):
        raise ValueError("coordinate space monitors is invalid")
    parsed: list[tuple[int, int, int, int]] = []
    for rect in monitors:
        if not isinstance(rect, (list, tuple)) or len(rect) != 4:
            raise ValueError("coordinate space monitor rectangle is invalid")
        parsed.append(tuple(int(part) for part in rect))
    if not isinstance(value["contract_version"], int) or isinstance(
        value["contract_version"], bool
    ):
        raise ValueError("coordinate space contract_version is invalid")
    return CoordinateSpace(
        value["contract_version"],
        str(value["process_awareness"]),
        str(value["thread_awareness"]),
        str(value["awareness_api"]),
        str(value["units"]),
        tuple(int(part) for part in bounds),
        tuple(parsed),
    )


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
    "CONTRACT_VERSION",
    "CoordinateSpace",
    "PHYSICAL_PIXELS",
    "capture",
    "disagreements",
    "from_record",
    "geometry_is_usable",
    "window_agrees",
]
