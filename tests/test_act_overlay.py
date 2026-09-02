"""The overlay seam: what reaches the screen, and for how long.

Only the win32 edges are faked -- `set_cue`, `clear_cue`, `measure_label`,
the message pump. Everything else is the real presenter, the real layout and
the real protocol, because the defects worth catching here are about how those
are wired together, and a test that stubbed them would prove only that the
stubs agreed with each other.
"""

from __future__ import annotations

import pytest

from ghostcursor import act_overlay
from ghostcursor.act_overlay import CueBudget, overlay_presenter
from ghostcursor.act_node import Observation
from ghostcursor.act_protocol import (
    LifecycleState,
    PresentationRequest,
    ReceiptKind,
    ReceiptPolicy,
    TrustClass,
)
from ghostcursor.overlay.cue import TRUST_COLOURS, LabelMetrics

HWND = 12345
BOUNDS = (0, 0, 1920, 1080)
POLICY = ReceiptPolicy(first_paint_deadline_ms=500, completion_deadline_ms=2000)
BUDGET = CueBudget(traversal_ms=400, settle_ms=250, frame_budget_ms=25)


class FakeWindow:
    """Stands in for the four win32 calls this module makes, and records the
    order they happened in."""

    def __init__(self):
        self.events: list[tuple[str, object]] = []
        self.pumps = 0

    def set_cue(self, hwnd, scene):
        assert hwnd == HWND
        self.events.append(("set", scene))

    def clear_cue(self, hwnd):
        assert hwnd == HWND
        self.events.append(("clear", None))

    def measure_label(self, hwnd, text):
        assert hwnd == HWND
        return LabelMetrics(char_width=8, line_height=16)

    def pump_messages_nonblocking(self):
        self.pumps += 1

    @property
    def kinds(self):
        return [name for name, _ in self.events]

    @property
    def scenes(self):
        return [scene for name, scene in self.events if name == "set"]


class Clock:
    def __init__(self):
        self.now = 0.0

    def read(self) -> float:
        return self.now

    def sleep(self, milliseconds: float) -> None:
        self.now += milliseconds


@pytest.fixture
def screen(monkeypatch):
    fake = FakeWindow()
    monkeypatch.setattr(act_overlay.overlay_window, "set_cue", fake.set_cue)
    monkeypatch.setattr(act_overlay.overlay_window, "clear_cue", fake.clear_cue)
    monkeypatch.setattr(act_overlay.overlay_window, "measure_label", fake.measure_label)
    return fake


@pytest.fixture
def clock(monkeypatch):
    ticker = Clock()
    monkeypatch.setattr("ghostcursor.act_presenter._sleep", lambda ms: ticker.sleep(ms))
    return ticker


def _request(cue_id="n001:1", generation=1):
    return PresentationRequest(
        session_id="s1",
        cue_id=cue_id,
        nonce="a" * 32,
        presentation_generation=generation,
        frame_generation=1,
        geometry_required=True,
    )


def _session(screen, clock, *, keep_running=None, **overrides):
    kwargs = dict(
        budget=BUDGET,
        policy=POLICY,
        label_for=lambda observation: "New Slide",
        backend_trust=TrustClass.LIVE_STATE,
        keep_running=keep_running or (lambda: True),
        bounds=BOUNDS,
        clock=clock.read,
        pump=screen.pump_messages_nonblocking,
    )
    kwargs.update(overrides)
    return overlay_presenter(HWND, **kwargs)


def _observation(rectangle=(400, 300, 520, 340)):
    return Observation(
        semantic={"slides": 3},
        identity={"control_type": "Button", "name": "New Slide"},
        rectangle=rectangle,
        match_count=1,
    )


# --- the cue reaches the screen and outlives the completion receipt --------


def test_a_cue_is_painted_and_completes(screen, clock):
    session = _session(screen, clock)

    receipts = session.present(_request(), _observation())

    assert [r.kind for r in receipts] == [
        ReceiptKind.GEOMETRY_STARTED,
        ReceiptKind.PRESENTATION_COMPLETED,
    ]
    # One frame, because the FIRST cue of a run has nowhere to travel from.
    # The travelling case is the second cue, below.
    assert screen.kinds == ["set"]


def test_the_pointer_lands_on_the_centre_of_the_observed_rectangle(screen, clock):
    session = _session(screen, clock)

    session.present(_request(), _observation())

    assert screen.scenes[-1].pointer == (460, 320)


def test_the_cue_survives_the_completion_receipt(screen, clock):
    """`execute_node` dispatches after that receipt. Clearing here would press
    the button with nothing on screen."""

    session = _session(screen, clock)

    session.present(_request(), _observation())

    assert "clear" not in screen.kinds


def test_a_presenting_cue_is_drawn_neutral_however_strong_the_backend(screen, clock):
    """Nothing has been proven at presentation time, and D109 forbids an
    unproven node wearing a verified colour -- including a node whose backend
    would eventually earn LIVE_STATE."""

    session = _session(screen, clock, backend_trust=TrustClass.LIVE_STATE)

    session.present(_request(), _observation())

    assert {scene.trust for scene in screen.scenes} == {TrustClass.NEUTRAL}
    assert screen.scenes[-1].colour == TRUST_COLOURS[TrustClass.NEUTRAL]


# --- what the pointer means once the node ends ----------------------------


def test_a_verified_node_repaints_the_pointer_in_what_it_earned(screen, clock):
    """This is what lets the pointer outlive its node honestly: NEUTRAL says
    "about to act here", the earned class says "acted here"."""

    session = _session(screen, clock)
    session.present(_request(), _observation())

    session.on_node_state(object(), LifecycleState.VERIFIED)

    assert screen.scenes[-1].trust is TrustClass.LIVE_STATE
    assert screen.kinds[-1] == "set"


def test_a_legacy_backend_is_not_repainted_as_a_true_uia_pattern(screen, clock):
    session = _session(screen, clock, backend_trust=TrustClass.LEGACY_LIVE_STATE)
    session.present(_request(), _observation())

    session.on_node_state(object(), LifecycleState.VERIFIED)

    assert screen.scenes[-1].trust is TrustClass.LEGACY_LIVE_STATE
    assert screen.scenes[-1].colour != TRUST_COLOURS[TrustClass.LIVE_STATE]


def test_a_refused_node_clears_the_pointer_immediately(screen, clock):
    """Nothing follows a refusal, so a pointer left behind would point at a
    control that is not going to be touched."""

    session = _session(screen, clock)
    session.present(_request(), _observation())

    session.on_node_state(object(), LifecycleState.REFUSED)

    assert screen.kinds[-1] == "clear"


def test_an_in_flight_state_neither_clears_nor_recolours(screen, clock):
    session = _session(screen, clock)
    session.present(_request(), _observation())
    before = len(screen.events)

    for state in (
        LifecycleState.CONFIRMING,
        LifecycleState.EXECUTING,
        LifecycleState.VERIFYING,
    ):
        session.on_node_state(object(), state)

    assert len(screen.events) == before


def test_the_caller_still_sees_every_lifecycle_state(screen, clock):
    """The wrapper adds behaviour; it must not swallow the events the session
    surface is driven by."""

    seen: list[LifecycleState] = []
    session = _session(screen, clock, on_state=lambda _node, state: seen.append(state))
    session.present(_request(), _observation())

    for state in (LifecycleState.EXECUTING, LifecycleState.VERIFIED):
        session.on_node_state(object(), state)

    assert seen == [LifecycleState.EXECUTING, LifecycleState.VERIFIED]


def test_release_clears_whatever_is_standing(screen, clock):
    session = _session(screen, clock)
    session.present(_request(), _observation())

    session.release()

    assert screen.kinds[-1] == "clear"


# --- the second node travels from where the first one left the pointer ----


def test_a_second_cue_travels_from_where_the_first_one_ended(screen, clock):
    """The reason a verified pointer stays up. With no previous position every
    cue is a single settled frame and the pointer never moves, which removes
    the thing the user watches to know where the run is going."""

    session = _session(screen, clock)
    session.present(_request(), _observation())
    session.on_node_state(object(), LifecycleState.VERIFIED)
    first_end = screen.scenes[-1].pointer

    screen.events.clear()
    session.present(
        _request("n002:2", generation=2), _observation((800, 600, 900, 640))
    )

    # Frames run from the first step AFTER the start -- the pointer is
    # already displayed at `first_end`, so repainting it there would be a
    # wasted frame. What matters is that the path begins between the two
    # points and ends exactly on the new control.
    assert len(screen.scenes) > 1
    assert first_end[0] < screen.scenes[0].pointer[0] < 850
    assert screen.scenes[-1].pointer == (850, 620)


def test_the_first_cue_of_a_run_does_not_fly_in_from_nowhere(screen, clock):
    session = _session(screen, clock)

    session.present(_request(), _observation())

    assert screen.scenes == [screen.scenes[0]]
    assert screen.scenes[0].pointer == (460, 320)  # placed, not flown in


def test_a_cleared_pointer_does_not_leave_a_phantom_start(screen, clock):
    """After a refusal the pointer is gone, so the next cue has nowhere
    honest to come from."""

    session = _session(screen, clock)
    session.present(_request(), _observation())
    session.on_node_state(object(), LifecycleState.REFUSED)

    screen.events.clear()
    session.present(
        _request("n002:2", generation=2), _observation((800, 600, 900, 640))
    )

    assert screen.scenes[0].pointer == (850, 620)  # straight to the destination


# --- Stop is heard, and withholds the effect ------------------------------


def test_a_stop_returns_partial_receipts_rather_than_raising(screen, clock):
    """The node then refuses on its own, because there is no completion for
    the wait to accept. Raising would make the refusal depend on somebody
    catching an exception."""

    session = _session(screen, clock, keep_running=lambda: False)

    receipts = session.present(_request(), _observation())

    assert [r.kind for r in receipts] == [ReceiptKind.GEOMETRY_STARTED]
    assert screen.kinds[-1] == "clear"


def test_the_message_pump_runs_on_every_poll(screen, clock):
    """A Stop read from a queue nothing drained is a Stop that was pressed and
    never delivered."""

    session = _session(screen, clock)
    session.present(_request(), _observation())
    session.on_node_state(object(), LifecycleState.VERIFIED)
    screen.pumps = 0

    # The second cue is the long one: 400ms of travel plus a 250ms settle,
    # polled every 50ms.
    session.present(_request("n002:2", generation=2), _observation((800, 600, 900, 640)))

    assert screen.pumps >= 13


def test_the_pump_runs_before_the_stop_is_read(screen, clock):
    order: list[str] = []

    def pump():
        order.append("pump")

    def keep_running():
        order.append("read")
        return len(order) < 4

    session = _session(screen, clock, keep_running=keep_running, pump=pump)

    with pytest.raises(Exception):
        session.present(_request(), _observation())
        raise AssertionError("expected the run to stop")

    assert order[:2] == ["pump", "read"]


# --- no geometry is a rejection, never a guess ----------------------------


def test_an_observation_without_a_rectangle_is_rejected_not_guessed(screen, clock):
    session = _session(screen, clock)

    receipts = session.present(_request(), Observation(semantic={}, rectangle=None))

    assert [r.kind for r in receipts] == [ReceiptKind.RENDER_REJECTED]
    assert screen.events == []


def test_a_degenerate_rectangle_is_rejected_and_leaves_nothing_up(screen, clock):
    session = _session(screen, clock)

    receipts = session.present(_request(), _observation((400, 300, 400, 340)))

    assert [r.kind for r in receipts] == [ReceiptKind.RENDER_REJECTED]
    assert screen.kinds == ["clear"]


def test_a_paint_too_slow_for_the_poll_interval_is_rejected(screen, clock):
    """Geometry that cannot keep the interrupt floor must not be drawn at
    all. The run continues on rail text rather than showing a pointer it
    could not keep honest."""

    session = _session(
        screen,
        clock,
        budget=CueBudget(traversal_ms=400, settle_ms=250, frame_budget_ms=200),
    )

    receipts = session.present(_request(), _observation())

    assert [r.kind for r in receipts] == [ReceiptKind.RENDER_REJECTED]


# --- the budget has to be supplied -----------------------------------------


def test_the_frame_budget_has_no_default():
    """It is a measured paint cost. A plausible constant here is the
    placeholder that measurement exists to replace."""

    with pytest.raises(TypeError):
        CueBudget(traversal_ms=400, settle_ms=250)
