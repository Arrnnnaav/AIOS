"""Drives one cue: paints its frames on a clock and returns its receipts.

This is the half of presentation that has to be *watched* rather than
computed. `pointer_path` decides where the pointer is at each moment and
`overlay.cue` decides what one frame looks like; this walks the schedule in
real time, keeps the user able to stop it, and reports what actually happened.

The receipts are the point. Under D109 an effect may not be dispatched unless
the user was shown where it was going to land, and "was shown" cannot be an
assumption the worker makes about itself — it is a fact the surface reports
back. So the presenter emits `GEOMETRY_STARTED` only after a paint has
returned, and `PRESENTATION_COMPLETED` only after the settle has actually
elapsed on the clock. Every receipt is bound to the request's session, cue,
nonce and generations, so a receipt from an earlier cue cannot satisfy a
later one.

**An interrupted presentation completes nothing.** Stop, Pause and ESC end
the walk wherever it is, and the completion receipt is simply not emitted —
which means `PresentationWait.may_execute` stays false and no effect follows.
That is the mechanism, not a check someone has to remember: the absence of a
receipt is what withholds the authority.

The clock and the paint are injected. A presenter that could only be tested
against a real desktop would be a presenter whose timing was never tested at
all, and the timing is where it fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from ghostcursor.act_protocol import (
    LifecycleState,
    PresentationRequest,
    ProtocolError,
    Receipt,
    ReceiptKind,
    ReceiptPolicy,
    RefusalCode,
    TrustClass,
)
from ghostcursor.overlay.cue import CueLayoutError, CueScene, LabelMetrics, label_box
from ghostcursor.pointer_path import PointerPathError, Schedule, schedule_for


class PresentationAborted(Exception):
    """The user stopped this cue. Carries the receipts emitted so far.

    An exception rather than a return value because every caller must handle
    it: silently returning a short receipt list would let a caller that only
    checks `receipts[0]` proceed to dispatch after a Stop.
    """

    def __init__(self, receipts: tuple[Receipt, ...], detail: str) -> None:
        super().__init__(detail)
        self.receipts = receipts
        self.detail = detail


@dataclass(frozen=True)
class CuePlan:
    """Everything one cue needs, resolved before the clock starts.

    Built by the worker from the observation it just took, so the rectangle
    here is the rectangle that was read — not one re-resolved at paint time,
    which could move between the two and put the pointer somewhere the
    verifier never looked.
    """

    target: tuple[int, int, int, int]
    label: str
    trust: TrustClass
    schedule: Schedule
    label_rect: tuple[int, int, int, int] | None = None


def plan_cue(
    target: tuple[int, int, int, int],
    label: str,
    trust: TrustClass,
    *,
    start: tuple[int, int] | None,
    bounds: tuple[int, int, int, int],
    metrics: LabelMetrics,
    traversal_ms: int,
    settle_ms: int,
    frame_budget_ms: int,
    poll_interval_ms: int = 50,
) -> CuePlan:
    """Lay one cue out completely, or refuse it.

    Refusal is a real outcome, not an error: a machine whose paint cost cannot
    hold the interrupt poll interval, or a rectangle with no area, means
    geometry is not presentable here. The caller answers that with
    `RENDER_REJECTED` and a rail fallback, and the run continues without ever
    drawing a pointer it could not keep honest.
    """

    schedule = schedule_for(
        start,
        target,
        traversal_ms=traversal_ms,
        settle_ms=settle_ms,
        frame_budget_ms=frame_budget_ms,
        poll_interval_ms=poll_interval_ms,
    )
    final = schedule.frames[-1]
    box = label_box((final.x, final.y), label, metrics, bounds=bounds, avoid=target)
    return CuePlan(target, label, trust, schedule, box)


def present_cue(
    request: PresentationRequest,
    policy: ReceiptPolicy,
    plan: CuePlan | None,
    *,
    paint: Callable[[CueScene | None], None],
    clock: Callable[[], float],
    poll: Callable[[], bool],
    on_state: Callable[[LifecycleState], None] | None = None,
    on_receipt: Callable[[Receipt, float], None] | None = None,
) -> tuple[Receipt, ...]:
    """Show one cue and return the receipts it earned.

    ``poll`` is asked whether to keep going, densely enough that no gap
    exceeds the schedule's poll interval. It returning False is a Stop.

    ``paint`` is called with a scene, and with None to clear. An ABORTED cue
    is cleared here, because nothing follows it. A completed one is not: the
    dispatch happens after the completion receipt, and the pointer has to
    still be at the control while the control is invoked. The caller clears it
    when the node ends.

    ``on_receipt`` is handed each receipt AND the clock reading at which it
    was emitted, which is what a `PresentationWait` needs to enforce its two
    deadlines. Returning the receipts alone would leave a caller feeding them
    all at the final timestamp, where a start that arrived promptly at 3ms
    looks like one that arrived at 650 and times out. The return value stays
    for the record; the callback is what makes the deadlines real.
    """

    if not isinstance(request, PresentationRequest):
        raise ProtocolError(
            "a presentation needs a PresentationRequest",
            RefusalCode.UNSUPPORTED_ACTION_SURFACE,
        )
    if not isinstance(policy, ReceiptPolicy):
        raise ProtocolError(
            "a presentation needs a ReceiptPolicy",
            RefusalCode.UNSUPPORTED_ACTION_SURFACE,
        )

    def receipt(kind: ReceiptKind, *, at: float | None = None) -> Receipt:
        issued = Receipt(
            kind,
            request.session_id,
            request.cue_id,
            request.nonce,
            request.presentation_generation,
            request.frame_generation,
        )
        if on_receipt is not None:
            on_receipt(issued, clock() if at is None else at)
        return issued

    if plan is None:
        # No presentable geometry. Reported, never silently downgraded: the
        # caller decides whether a rail fallback is acceptable for this node,
        # and for a geometry_required cue it is not.
        return (receipt(ReceiptKind.RENDER_REJECTED),)
    if not isinstance(plan, CuePlan):
        raise ProtocolError(
            "a presentation needs a CuePlan", RefusalCode.UNSUPPORTED_ACTION_SURFACE
        )

    if on_state is not None:
        on_state(LifecycleState.PRESENTING)

    started_ms = clock()
    schedule = plan.schedule
    receipts: list[Receipt] = []

    def scene_for(frame) -> CueScene:
        return CueScene(
            pointer=(frame.x, frame.y),
            target=plan.target,
            label=plan.label,
            trust=plan.trust,
            final=frame.final,
            label_rect=plan.label_rect,
        )

    def stop(detail: str) -> None:
        paint(None)
        raise PresentationAborted(tuple(receipts), detail)

    # The first frame, then its receipt. This order is the whole claim: the
    # receipt says a paint returned, so it cannot be emitted before one did.
    paint(scene_for(schedule.frames[0]))
    receipts.append(receipt(ReceiptKind.GEOMETRY_STARTED))
    if not poll():
        stop("stopped during the first frame")

    for frame in schedule.frames[1:]:
        if not _wait_until(started_ms + frame.at_ms, clock, poll, schedule):
            stop("stopped during the traversal")
        paint(scene_for(frame))

    # The settle. Nothing is painted here, which makes it the longest stretch
    # of the cue with no other reason to check the controls -- so it is
    # exactly the stretch where an unpolled wait would swallow a Stop.
    if not _wait_until(started_ms + schedule.settled_until_ms, clock, poll, schedule):
        stop("stopped during the settle")

    receipts.append(receipt(ReceiptKind.PRESENTATION_COMPLETED))
    # The cue STAYS. `execute_node` dispatches after this receipt, so clearing
    # here would land the click on a blank screen -- a pointer shown at the
    # control, removed, and then the control invoked. D109 is that the pointer
    # is shown where the effect happens, and the effect has not happened yet.
    # The caller clears it when the node reaches VERIFIED or REFUSED.
    return tuple(receipts)


def _wait_until(
    deadline_ms: float,
    clock: Callable[[], float],
    poll: Callable[[], bool],
    schedule: Schedule,
) -> bool:
    """Advance to ``deadline_ms``, asking ``poll`` at least every interval.

    Returns False the moment poll does. The loop polls BEFORE checking the
    deadline so that a wait already past its deadline still asks once: a Stop
    pressed during a slow paint would otherwise be read only on the next
    frame, and the last frame has no next.
    """

    while True:
        if not poll():
            return False
        now = clock()
        if now >= deadline_ms:
            return True
        # The clock is real time; the caller's sleep is what actually advances
        # it. This yields in interval-sized pieces so the next poll is never
        # further away than the interval.
        remaining = deadline_ms - now
        _sleep(min(remaining, float(schedule.poll_interval_ms)))


def _sleep(milliseconds: float) -> None:
    """Injected in tests by replacing the module attribute.

    A separate function rather than an inline `time.sleep` so a test can drive
    a full schedule without spending its duration, and so the production path
    has no branch that only exists for tests.
    """

    import time

    time.sleep(milliseconds / 1000.0)


def receipts_for_scene_error(
    request: PresentationRequest, error: Exception
) -> Sequence[Receipt]:
    """A layout or path failure reported as a rejection, not a crash.

    `CueLayoutError` and `PointerPathError` both mean the same thing to the
    run: this cue cannot be drawn honestly. They reach the caller as
    `RENDER_REJECTED` so the run record shows a refused presentation rather
    than an exception with no receipt at all.
    """

    if not isinstance(error, (CueLayoutError, PointerPathError)):
        raise error
    return (
        Receipt(
            ReceiptKind.RENDER_REJECTED,
            request.session_id,
            request.cue_id,
            request.nonce,
            request.presentation_generation,
            request.frame_generation,
        ),
    )


__all__ = [
    "CuePlan",
    "PresentationAborted",
    "plan_cue",
    "present_cue",
    "receipts_for_scene_error",
]
