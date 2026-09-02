"""A cue is only presented if it was actually painted, and only completed if
it was actually held.

D109 makes the receipt the authority: an effect may not be dispatched unless
the surface reported showing where it would land. So the cases that matter
here are the ones where a receipt could be emitted for something that did not
happen -- a completion before the settle elapsed, a start before any paint
returned, a completion after the user pressed Stop -- and the ones where the
user's Stop could go unnoticed.

Ordered-sequence on an injected clock (D026): every assertion is about what
happened in what order, never about the state at the end.
"""

from __future__ import annotations

import pytest

from ghostcursor import act_presenter
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
    PresentationWait,
    ProtocolError,
    ReceiptKind,
    ReceiptPolicy,
    TrustClass,
    receipt_answers,
)
from ghostcursor.overlay.cue import CueLayoutError, LabelMetrics
from ghostcursor.pointer_path import PointerPathError

SCREEN = (0, 0, 1920, 1080)
TARGET = (400, 300, 520, 340)
METRICS = LabelMetrics(char_width=8, line_height=16)
REQUEST = PresentationRequest(
    session_id="s1",
    cue_id="n001:1",
    nonce="a" * 32,
    presentation_generation=1,
    frame_generation=1,
    geometry_required=True,
)
POLICY = ReceiptPolicy(first_paint_deadline_ms=500, completion_deadline_ms=2000)


class Recorder:
    """A clock, a paint sink and an interrupt in one, recording their order.

    One object rather than three fakes because the property under test is the
    INTERLEAVING -- a paint before a receipt, a poll before a wait ends -- and
    three separate logs cannot express that.
    """

    #: The recorder whose clock the patched sleep advances. Set on
    #: construction, so a test that builds its own recorder drives its own
    #: clock. Without this the patched sleep advanced the FIXTURE's clock
    #: while the test read a different one, and those tests terminated only
    #: because their poll said stop -- so a mutation that stopped consulting
    #: poll inside a wait hung the suite instead of failing it.
    current: "Recorder | None" = None

    def __init__(self, *, stop_after_polls: int | None = None):
        Recorder.current = self
        self.now = 0.0
        self.events: list[tuple[str, object]] = []
        self.polls = 0
        self._stop_after = stop_after_polls

    def clock(self) -> float:
        return self.now

    def sleep(self, milliseconds: float) -> None:
        self.now += milliseconds
        self.events.append(("sleep", round(milliseconds, 3)))

    def paint(self, scene) -> None:
        if scene is None:
            self.events.append(("clear", self.now))
        else:
            self.events.append(("paint", (scene.pointer, self.now)))

    def receipt(self, receipt, at: float) -> None:
        self.events.append(("receipt", (receipt.kind.value, at)))

    def poll(self) -> bool:
        self.polls += 1
        self.events.append(("poll", self.now))
        if self._stop_after is not None and self.polls > self._stop_after:
            return False
        return True

    def kinds(self) -> list[str]:
        return [name for name, _ in self.events]


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch, recorder):
    """The presenter's own sleep is replaced, so a 650ms cue costs nothing.

    A test that spent the schedule's real duration would be a test nobody runs
    often enough to catch a regression in.

    It dispatches to whichever recorder was built last rather than binding the
    fixture's, so the clock that advances is always the clock the test reads.
    """

    monkeypatch.setattr(
        act_presenter, "_sleep", lambda ms: Recorder.current.sleep(ms)
    )


@pytest.fixture
def recorder():
    return Recorder()


def _plan(**overrides):
    kwargs = dict(
        start=(0, 0),
        bounds=SCREEN,
        metrics=METRICS,
        traversal_ms=400,
        settle_ms=250,
        frame_budget_ms=25,
    )
    kwargs.update(overrides)
    return plan_cue(TARGET, "New Slide", TrustClass.NEUTRAL, **kwargs)


# --- the plan is laid out before the clock starts --------------------------


def test_the_pointer_ends_on_the_centre_of_the_rectangle_that_was_observed():
    """Not one re-resolved at paint time: a control that moved between the
    read and the paint would put the cue somewhere the verifier never looked
    (D109)."""

    plan = _plan()

    assert (plan.schedule.frames[-1].x, plan.schedule.frames[-1].y) == (460, 320)


def test_the_label_is_laid_out_clear_of_the_control_it_names():
    plan = _plan()
    left, top, right, bottom = plan.label_rect

    assert not (
        left < TARGET[2]
        and TARGET[0] < right
        and top < TARGET[3]
        and TARGET[1] < bottom
    )


def test_a_machine_whose_paint_cannot_hold_the_poll_interval_cannot_plan():
    """Refusal is the outcome, not a slower cue: geometry that cannot keep the
    interrupt floor is geometry that must not be drawn."""

    with pytest.raises(PointerPathError, match="poll interval"):
        _plan(frame_budget_ms=200)


# --- a receipt follows the thing it reports, never precedes it -------------


def test_the_first_paint_happens_before_the_start_receipt_is_emitted(recorder):
    """The receipt's whole claim is that a paint returned.

    The receipt has to be IN the event log for this to mean anything. An
    earlier version asserted only that the first event was a paint, which
    stays true when the receipt is emitted first and simply never recorded --
    so swapping the two lines changed nothing the test could see.
    """

    receipts = present_cue(
        REQUEST,
        POLICY,
        _plan(),
        paint=recorder.paint,
        clock=recorder.clock,
        poll=recorder.poll,
        on_receipt=recorder.receipt,
    )

    assert recorder.kinds()[:2] == ["paint", "receipt"]
    assert receipts[0].kind is ReceiptKind.GEOMETRY_STARTED


def test_the_completion_receipt_is_emitted_only_after_the_settle_elapsed(recorder):
    """A completion at the last frame would authorize the effect 250ms before
    the label had been readable."""

    receipts = present_cue(
        REQUEST,
        POLICY,
        _plan(),
        paint=recorder.paint,
        clock=recorder.clock,
        poll=recorder.poll,
    )

    assert receipts[-1].kind is ReceiptKind.PRESENTATION_COMPLETED
    assert recorder.now == pytest.approx(650.0)


def test_the_last_paint_is_the_final_frame_and_the_settle_paints_nothing(recorder):
    present_cue(
        REQUEST,
        POLICY,
        _plan(),
        paint=recorder.paint,
        clock=recorder.clock,
        poll=recorder.poll,
    )
    paints = [
        when
        for name, (_pointer, when) in (
            (n, v) for n, v in recorder.events if n == "paint"
        )
    ]

    assert max(paints) == pytest.approx(400.0)


def test_every_receipt_answers_the_request_it_was_asked_for(recorder):
    """A receipt from an earlier cue must not satisfy a later one, which is
    what binding the nonce and both generations prevents."""

    receipts = present_cue(
        REQUEST,
        POLICY,
        _plan(),
        paint=recorder.paint,
        clock=recorder.clock,
        poll=recorder.poll,
    )

    assert all(receipt_answers(REQUEST, receipt) for receipt in receipts)


def test_the_receipts_satisfy_a_wait_and_authorize_the_effect(recorder):
    """The end-to-end claim: these receipts, fed to the protocol's own wait as
    they arrive, are what makes `may_execute` true."""

    wait = PresentationWait(REQUEST, POLICY, started_ms=0.0)
    present_cue(
        REQUEST,
        POLICY,
        _plan(),
        paint=recorder.paint,
        clock=recorder.clock,
        poll=recorder.poll,
        on_receipt=lambda receipt, at: wait.accept(receipt, now_ms=at),
    )

    assert wait.may_execute is True


def test_a_receipt_carries_the_moment_it_was_emitted(recorder):
    """Without the timestamp, a caller feeds every receipt at the final clock
    reading -- and a start that arrived promptly at 0ms is judged as if it had
    arrived at 650, which times out against a 500ms first-paint deadline. The
    deadlines would exist and enforce nothing."""

    seen: list[tuple[str, float]] = []

    present_cue(
        REQUEST,
        POLICY,
        _plan(),
        paint=recorder.paint,
        clock=recorder.clock,
        poll=recorder.poll,
        on_receipt=lambda receipt, at: seen.append((receipt.kind.value, at)),
    )

    assert seen[0] == ("geometry_started", 0.0)
    assert seen[-1] == ("presentation_completed", 650.0)


def test_a_stopped_presentation_still_reports_the_receipt_it_did_emit():
    """The record has to show that a cue started before the user stopped it,
    or a Stop looks identical to a presentation that never began."""

    stopper = Recorder(stop_after_polls=0)
    seen: list[str] = []

    with pytest.raises(PresentationAborted):
        present_cue(
            REQUEST,
            POLICY,
            _plan(),
            paint=stopper.paint,
            clock=stopper.clock,
            poll=stopper.poll,
            on_receipt=lambda receipt, _at: seen.append(receipt.kind.value),
        )

    assert seen == ["geometry_started"]


# --- Stop is heard, and withholds the authority ---------------------------


def test_a_stop_during_the_settle_yields_no_completion_receipt():
    """The mechanism is the ABSENCE of the receipt. Nothing has to remember to
    check a flag: without a completion the wait never reaches may_execute, so
    no effect can follow."""

    recorder = Recorder(stop_after_polls=9)
    plan = _plan()

    with pytest.raises(PresentationAborted) as raised:
        present_cue(
            REQUEST,
            POLICY,
            plan,
            paint=recorder.paint,
            clock=recorder.clock,
            poll=recorder.poll,
        )

    kinds = [receipt.kind for receipt in raised.value.receipts]
    assert ReceiptKind.PRESENTATION_COMPLETED not in kinds
    assert recorder.now < 650.0

    wait = PresentationWait(REQUEST, POLICY, started_ms=0.0)
    for receipt in raised.value.receipts:
        wait.accept(receipt, now_ms=recorder.now)
    assert wait.may_execute is False


def test_a_stop_during_the_traversal_stops_painting_immediately():
    recorder = Recorder(stop_after_polls=2)

    with pytest.raises(PresentationAborted):
        present_cue(
            REQUEST,
            POLICY,
            _plan(),
            paint=recorder.paint,
            clock=recorder.clock,
            poll=recorder.poll,
        )

    painted = recorder.kinds().count("paint")
    assert painted < len(_plan().schedule.frames)


def test_a_stop_at_the_very_first_poll_still_leaves_the_start_receipt():
    """The first frame WAS painted, so claiming it was not would be a
    different lie. What it must not have is a completion."""

    recorder = Recorder(stop_after_polls=0)

    with pytest.raises(PresentationAborted) as raised:
        present_cue(
            REQUEST,
            POLICY,
            _plan(),
            paint=recorder.paint,
            clock=recorder.clock,
            poll=recorder.poll,
        )

    assert [r.kind for r in raised.value.receipts] == [ReceiptKind.GEOMETRY_STARTED]


@pytest.mark.parametrize("stop_after", [0, 2, 5, 9, 13])
def test_the_cue_is_cleared_on_every_stopping_point(stop_after):
    """A cue left on screen points at a control nothing is about to click."""

    recorder = Recorder(stop_after_polls=stop_after)

    with pytest.raises(PresentationAborted):
        present_cue(
            REQUEST,
            POLICY,
            _plan(),
            paint=recorder.paint,
            clock=recorder.clock,
            poll=recorder.poll,
        )

    assert recorder.kinds()[-1] == "clear"


def test_the_cue_is_cleared_after_a_completed_presentation(recorder):
    present_cue(
        REQUEST,
        POLICY,
        _plan(),
        paint=recorder.paint,
        clock=recorder.clock,
        poll=recorder.poll,
    )

    assert recorder.kinds()[-1] == "clear"


def test_no_stretch_of_the_presentation_goes_unpolled(recorder):
    """The settle is the longest stretch with nothing else happening, and it
    is time in which Stop must still be noticed."""

    present_cue(
        REQUEST,
        POLICY,
        _plan(),
        paint=recorder.paint,
        clock=recorder.clock,
        poll=recorder.poll,
    )
    moments = [when for name, when in recorder.events if name == "poll"]
    gaps = [b - a for a, b in zip(moments, moments[1:])]

    assert max(gaps) <= 50


def test_a_poll_happens_before_any_wait_can_end(recorder):
    """A wait already past its deadline still asks once. Otherwise a Stop
    pressed during a slow paint is read only on the next frame -- and the last
    frame has no next."""

    recorder.now = 10_000.0
    stopper = Recorder(stop_after_polls=0)
    stopper.now = 10_000.0

    with pytest.raises(PresentationAborted):
        present_cue(
            REQUEST,
            POLICY,
            _plan(),
            paint=stopper.paint,
            clock=stopper.clock,
            poll=stopper.poll,
        )

    assert "poll" in stopper.kinds()


# --- refusal is an outcome, not a crash -----------------------------------


def test_no_plan_yields_a_rejection_and_paints_nothing(recorder):
    receipts = present_cue(
        REQUEST,
        POLICY,
        None,
        paint=recorder.paint,
        clock=recorder.clock,
        poll=recorder.poll,
    )

    assert [r.kind for r in receipts] == [ReceiptKind.RENDER_REJECTED]
    assert recorder.events == []


def test_a_rejection_cannot_satisfy_a_geometry_required_wait(recorder):
    """The protocol refuses it. Without that, "we could not draw it" would
    authorize the same effect as "we drew it and held it"."""

    wait = PresentationWait(REQUEST, POLICY, started_ms=0.0)
    receipts = present_cue(
        REQUEST,
        POLICY,
        None,
        paint=recorder.paint,
        clock=recorder.clock,
        poll=recorder.poll,
    )

    with pytest.raises(ProtocolError, match="geometry was required"):
        wait.accept(receipts[0], now_ms=1.0)
    assert wait.may_execute is False


@pytest.mark.parametrize(
    "error", [CueLayoutError("no area"), PointerPathError("bad budget")]
)
def test_a_layout_failure_becomes_a_rejection_receipt(error):
    """Both mean the same thing to the run: this cue cannot be drawn
    honestly. A bare exception would leave the record with no receipt at
    all."""

    receipts = receipts_for_scene_error(REQUEST, error)

    assert receipts[0].kind is ReceiptKind.RENDER_REJECTED
    assert receipt_answers(REQUEST, receipts[0])


def test_an_unrelated_exception_is_not_disguised_as_a_rejection():
    """A KeyError in the worker is a bug, and a rejection receipt would file it
    as a presentation problem and lose it."""

    with pytest.raises(KeyError):
        receipts_for_scene_error(REQUEST, KeyError("slides"))


@pytest.mark.parametrize(
    "bad", [("not a request", POLICY, None), (REQUEST, "not a policy", None)]
)
def test_a_malformed_presentation_is_refused(bad, recorder):
    request, policy, plan = bad

    with pytest.raises(ProtocolError):
        present_cue(
            request,
            policy,
            plan,
            paint=recorder.paint,
            clock=recorder.clock,
            poll=recorder.poll,
        )


def test_something_that_is_not_a_cue_plan_is_refused(recorder):
    with pytest.raises(ProtocolError, match="CuePlan"):
        present_cue(
            REQUEST,
            POLICY,
            object(),
            paint=recorder.paint,
            clock=recorder.clock,
            poll=recorder.poll,
        )


# --- the lifecycle the session surface shows ------------------------------


def test_the_surface_is_told_it_is_presenting_before_anything_is_painted(recorder):
    states: list[LifecycleState] = []

    present_cue(
        REQUEST,
        POLICY,
        _plan(),
        paint=recorder.paint,
        clock=recorder.clock,
        poll=recorder.poll,
        on_state=states.append,
    )

    assert states == [LifecycleState.PRESENTING]


def test_a_cue_plan_is_frozen():
    """It crosses from the worker that laid it out to the loop that paints
    it."""

    plan = _plan()

    with pytest.raises(Exception):
        plan.label = "Something Else"


def test_a_plan_built_by_hand_still_presents(recorder):
    """`plan_cue` is a convenience, not the only way in -- a rail-degraded or
    replayed cue may arrive already laid out."""

    plan = CuePlan(TARGET, "New Slide", TrustClass.NEUTRAL, _plan().schedule)

    receipts = present_cue(
        REQUEST,
        POLICY,
        plan,
        paint=recorder.paint,
        clock=recorder.clock,
        poll=recorder.poll,
    )

    assert receipts[-1].kind is ReceiptKind.PRESENTATION_COMPLETED
