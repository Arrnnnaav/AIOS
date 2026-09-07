"""Wires the presenter to a real overlay window and the real Stop button.

`act_presenter` knows how to walk a cue on a clock; `overlay.window` knows how
to paint one. This is the seam between them, and it is the only place in Act
that touches both a HWND and a `PresentationRequest`.

It supplies the `present` and `on_state` edges a `UiaNodeSession` needs.
Everything here is an edge — paint, clock, poll — so the authority checks stay
in `act_node.execute_node`, which the runtime calls itself. Nothing in this
module can declare a node verified.

**How long a cue lives, and why.** `present_cue` leaves a completed
presentation on screen, because `execute_node` dispatches AFTER the completion
receipt and a click landing on a blank screen is what D109 forbids. This
module then keeps it up past the node's end and lets the next node's cue
travel from it.

That last part is a deliberate reading of D109, and worth stating plainly. The
rule is that a pointer shown at a location means the next effect happens
there. Between nodes the pointer sits on the control that was just acted on,
which is a statement about the past — so it is REPAINTED in the trust class
the node actually earned the moment the outcome is known. A neutral pointer
means "about to act here"; a verified-coloured one means "acted here". The
alternative is clearing between nodes, and that is not a small cosmetic
difference: with no previous position every cue becomes a single settled frame
and the pointer never travels at all, which removes the thing the user watches
to know where the run is going.

A REFUSED node clears immediately. Nothing follows it, so there is no honest
reading of a pointer left behind.

**Message pumping happens in `poll`.** The overlay is a Win32 window on the
calling thread, and a cue that never pumps is a cue whose Stop button never
responds and whose paints may never reach the screen. Putting the pump in the
same callback that reads Stop means the two cannot drift apart: any code path
that keeps the presentation interruptible also keeps it drawn.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence
import weakref

from ghostcursor.act_presenter import (
    CuePlan,
    PresentationAborted,
    plan_cue,
    present_cue,
    receipts_for_scene_error,
)
from ghostcursor.act_protocol import (
    LifecycleState,
    PresentationRequest,
    Receipt,
    ReceiptPolicy,
    TrustClass,
)
from ghostcursor.coordinate_space import (
    BracketedGeometry,
    bracket_disagreements,
    observe_bracketed,
    window_agrees,
)
from ghostcursor.overlay import window as overlay_window
from ghostcursor.overlay.cue import CueLayoutError, CueScene
from ghostcursor.pointer_path import PointerPathError


class CueBudget:
    """The four numbers one cue's timing is made of.

    A plain class with an explicit `__init__` rather than a dataclass with
    defaults, because there must not BE defaults: `frame_budget_ms` is a
    measured paint cost, and a plausible constant is the placeholder that
    measurement exists to replace (D034 -- a number presented as a budget must
    name where it is recorded).
    """

    __slots__ = ("traversal_ms", "settle_ms", "frame_budget_ms", "poll_interval_ms")

    def __init__(
        self,
        *,
        traversal_ms: int,
        settle_ms: int,
        frame_budget_ms: int,
        poll_interval_ms: int = 50,
    ) -> None:
        self.traversal_ms = traversal_ms
        self.settle_ms = settle_ms
        self.frame_budget_ms = frame_budget_ms
        self.poll_interval_ms = poll_interval_ms


_OVERLAY_SESSION_SEAL = object()
_TRUSTED_OVERLAY_SESSIONS: "weakref.WeakSet[OverlaySession]" = weakref.WeakSet()


@dataclass(frozen=True, slots=True, weakref_slot=True, eq=False, init=False)
class OverlaySession:
    """The two callables a `UiaNodeSession` needs, sharing one pointer.

    They have to share state -- where the pointer was left, and what was last
    drawn -- so they are one object rather than two closures a caller could
    accidentally build from different presenters.
    """

    present: Callable[[PresentationRequest, object], Sequence[Receipt]]
    on_node_state: Callable[[object, LifecycleState], None]
    #: Clears whatever is on screen. Call it when the whole run ends: the
    #: per-node lifecycle deliberately leaves a verified pointer up.
    release: Callable[[], None]

    def __init__(
        self,
        *,
        present: Callable[[PresentationRequest, object], Sequence[Receipt]],
        on_node_state: Callable[[object, LifecycleState], None],
        release: Callable[[], None],
        _seal=None,
    ) -> None:
        if _seal is not _OVERLAY_SESSION_SEAL:
            raise TypeError("overlay sessions come from overlay_presenter")
        object.__setattr__(self, "present", present)
        object.__setattr__(self, "on_node_state", on_node_state)
        object.__setattr__(self, "release", release)


def _trusted_overlay_session(value: object) -> bool:
    """True only for an instance registered by ``overlay_presenter``."""

    return type(value) is OverlaySession and value in _TRUSTED_OVERLAY_SESSIONS


def overlay_presenter(
    hwnd: int,
    *,
    budget: CueBudget,
    policy: ReceiptPolicy,
    label_for: Callable[[object], str],
    backend_trust: TrustClass,
    keep_running: Callable[[], bool],
    bounds: tuple[int, int, int, int] | None = None,
    clock: Callable[[], float] | None = None,
    on_state: Callable[[object, LifecycleState], None] | None = None,
    on_receipt: Callable[[Receipt, float], None] | None = None,
    pump: Callable[[], None] | None = None,
    geometry_check: Callable[
        [int, object, tuple[int, int, int, int]], Sequence[str]
    ] | None = None,
) -> OverlaySession:
    """Build the overlay edges for one Act run.

    ``label_for`` turns the observation into the words shown beside the
    pointer. It takes the observation rather than a fixed string so the label
    names what was actually found, not what was hoped for.

    ``backend_trust`` is what a node of this kind earns ONCE VERIFIED --
    `TrustClass.LIVE_STATE` for a true UIA pattern, `LEGACY_LIVE_STATE` for a
    default action. It is never used during the cue: presentation always draws
    NEUTRAL, because at that point nothing has been proven and D109 forbids an
    unproven node wearing a verified colour. Passing the earned class in here
    rather than deriving a colour anywhere else keeps `trust_for()` the single
    source of what may be claimed.

    ``keep_running`` is the run's Stop/Pause state, consulted through `poll`
    alongside the message pump.

    ``on_state`` still receives every lifecycle state; it is wrapped, not
    replaced.
    """

    if bounds is None:
        left, top, width, height = overlay_window.dpi.virtual_screen_rect()
        bounds = (left, top, left + width, top + height)
    if clock is None:
        clock = _monotonic_ms
    if pump is None:
        pump = overlay_window.pump_messages_nonblocking
    if geometry_check is None:
        geometry_check = _coordinate_disagreements

    # Where the pointer currently is, so the next node's cue travels from it
    # rather than teleporting. None until the first cue and after any clear:
    # a pointer arriving from an arbitrary corner would suggest it had been
    # somewhere it was not.
    state: dict[str, object] = {
        "position": None,
        "scene": None,
        "geometry": None,
        "rectangle": None,
    }

    def clear() -> None:
        state["position"] = None
        state["scene"] = None
        state["geometry"] = None
        state["rectangle"] = None
        overlay_window.clear_cue(hwnd)

    def paint(scene: CueScene | None) -> None:
        if scene is None:
            clear()
            return
        geometry = state.get("geometry")
        rectangle = state.get("rectangle")
        if geometry is None or rectangle is None:
            raise CueLayoutError("paint has no accepted coordinate contract")
        reasons = tuple(geometry_check(hwnd, geometry, rectangle))
        if reasons:
            clear()
            raise CueLayoutError(
                "coordinate space changed before paint: " + "; ".join(reasons)
            )
        overlay_window.set_cue(hwnd, scene)
        reasons = tuple(geometry_check(hwnd, geometry, rectangle))
        if reasons:
            clear()
            raise CueLayoutError(
                "coordinate space changed during paint: " + "; ".join(reasons)
            )
        state["scene"] = scene

    def poll() -> bool:
        # Pump first. A Stop read from a queue nothing drained is a Stop that
        # was pressed and never delivered.
        pump()
        return keep_running()

    def on_node_state(node: object, lifecycle: LifecycleState) -> None:
        if lifecycle is LifecycleState.REFUSED:
            # Nothing follows a refusal, so a pointer left behind would point
            # at a control that is not going to be touched.
            clear()
        elif lifecycle is LifecycleState.VERIFIED:
            try:
                _recolour(state, backend_trust, paint)
            except CueLayoutError:
                # Verification remains true, but stale geometry is no longer
                # allowed to stay on screen as a success marker.
                clear()
        if on_state is not None:
            on_state(node, lifecycle)

    def present(
        request: PresentationRequest,
        observation: object,
        sink: Callable[[Receipt, float], None] | None = None,
    ) -> Sequence[Receipt]:
        def report(receipt: Receipt, at_ms: float) -> None:
            # Both, in this order. The caller's wait must see the receipt at
            # the moment it happened; the run's own recorder is secondary and
            # must not be able to suppress it.
            if sink is not None:
                sink(receipt, at_ms)
            if on_receipt is not None:
                on_receipt(receipt, at_ms)

        rectangle = getattr(observation, "rectangle", None)
        geometry = getattr(observation, "geometry", None)
        if rectangle is None or geometry is None:
            # No geometry was observed, so there is nothing honest to point
            # at. Reported as a rejection rather than drawn at a guessed
            # position (D109).
            return present_cue(
                request,
                policy,
                None,
                paint=paint,
                clock=clock,
                poll=poll,
                on_receipt=report,
            )

        rectangle = tuple(rectangle)
        reasons = tuple(geometry_check(hwnd, geometry, rectangle))
        if reasons:
            if state["scene"] is not None:
                clear()
            return receipts_for_scene_error(
                request,
                CueLayoutError("coordinate space refused: " + "; ".join(reasons)),
            )

        label = label_for(observation)
        try:
            plan = plan_cue(
                rectangle,
                label,
                TrustClass.NEUTRAL,
                start=state["position"],
                bounds=bounds,
                metrics=overlay_window.measure_label(hwnd, label),
                traversal_ms=budget.traversal_ms,
                settle_ms=budget.settle_ms,
                frame_budget_ms=budget.frame_budget_ms,
                poll_interval_ms=budget.poll_interval_ms,
            )
        except (CueLayoutError, PointerPathError) as error:
            # A machine whose paint cannot hold the poll interval, or a
            # rectangle with no area. Both mean this cue cannot be drawn
            # honestly, and both become a rejection the run record shows.
            clear()
            return receipts_for_scene_error(request, error)

        try:
            state["geometry"] = geometry
            state["rectangle"] = rectangle
            receipts = present_cue(
                request,
                policy,
                plan,
                paint=paint,
                clock=clock,
                poll=poll,
                on_receipt=report,
            )
        except (CueLayoutError, PointerPathError) as error:
            clear()
            return receipts_for_scene_error(request, error)
        except PresentationAborted as aborted:
            # The user stopped it. The partial receipts are RETURNED rather
            # than raised onward: they contain no completion, so the wait
            # cannot reach may_execute and the node refuses on its own.
            # Re-raising would make the refusal depend on somebody catching an
            # exception; the absence of a receipt is the stronger mechanism.
            # `present_cue` already cleared, so the position is gone with it.
            return aborted.receipts

        state["position"] = _final_position(plan)
        return receipts

    session = OverlaySession(
        present=present,
        on_node_state=on_node_state,
        release=clear,
        _seal=_OVERLAY_SESSION_SEAL,
    )
    _TRUSTED_OVERLAY_SESSIONS.add(session)
    return session


def _coordinate_disagreements(
    hwnd: int,
    geometry: object,
    rectangle: tuple[int, int, int, int],
) -> tuple[str, ...]:
    """Refuse a producer rectangle unless the painting thread agrees.

    The overlay samples its thread/process/topology immediately around this
    acceptance read.  The overlay HWND is checked separately because a window
    retains the awareness of the thread that created it.  These checks happen
    on the presenter/UI thread, immediately before layout and paint.
    """

    if not isinstance(geometry, BracketedGeometry):
        return ("the producer supplied no valid bracketed coordinate contract",)
    if geometry.rectangles != (rectangle,):
        return ("the producer rectangle disagrees with its coordinate contract",)
    if not geometry.held or geometry.before.units != "physical_pixels":
        return (
            "the producer did not hold one physical-pixel coordinate space",
        )

    observer = observe_bracketed(lambda: [rectangle])
    reasons = list(bracket_disagreements(observer.before, observer))
    if observer.before.units != "physical_pixels":
        reasons.append("the overlay is not painting in physical pixels")
    reasons.extend(bracket_disagreements(observer.before, geometry))
    reasons.extend(window_agrees(observer.after, hwnd))
    return tuple(dict.fromkeys(reasons))


def _recolour(
    state: dict,
    trust: TrustClass,
    paint: Callable[[CueScene | None], None],
) -> None:
    """Repaint the standing cue in the class the node actually earned.

    This is the whole reason a pointer may outlive its node: a NEUTRAL pointer
    says "about to act here" and a verified-coloured one says "acted here".
    Without the repaint, a pointer left on screen would keep claiming the
    former.
    """

    scene = state.get("scene")
    if scene is None:
        return
    updated = CueScene(
        pointer=scene.pointer,
        target=scene.target,
        label=scene.label,
        trust=trust,
        final=True,
        label_rect=scene.label_rect,
    )
    paint(updated)


def _final_position(plan: CuePlan) -> tuple[int, int]:
    """Where the pointer was left. Read from the plan rather than tracked
    during the walk, so a replay and a live run agree."""

    final = plan.schedule.frames[-1]
    return (final.x, final.y)


def _monotonic_ms() -> float:
    import time

    return time.monotonic() * 1000.0


__all__ = ["CueBudget", "OverlaySession", "overlay_presenter"]
