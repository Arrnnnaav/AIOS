"""The rail shows what the executor reported, and never anything else.

For a 255-node object-model deck build this is the whole visible product
(D109: an object-model node shows no pointer), so the ways it can lie are the
ways the run can appear to be doing something it is not — a step number the
rail worked out for itself, a Stop that reads as ignored, a status that keeps
updating after the run ended.

No window is created: `bar` is faked at the module boundary, so these run in
the hermetic lane.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from ghostcursor import act_rail
from ghostcursor.act_rail import RailSession, open_rail, rail_pump
from ghostcursor.act_runtime import ActControls

HWND = 999


@dataclass
class FakeBar:
    """Records every status the rail sets, in order."""

    statuses: list = None
    state: object = None
    cleared: int = 0
    pumps: int = 0
    destroyed: list = None

    def __post_init__(self):
        self.statuses = []
        self.destroyed = []
        self.state = SimpleNamespace(
            stop_requested=False, pause_requested=False, ask_requested=False
        )

    def create_bar_window(self):
        return HWND

    def set_status(self, hwnd, text):
        assert hwnd == HWND
        self.statuses.append(text)

    def bar_state(self, hwnd):
        return self.state

    def clear_requests(self, hwnd):
        self.cleared += 1
        self.state = SimpleNamespace(
            stop_requested=False, pause_requested=False, ask_requested=False
        )

    def pump_messages_nonblocking(self):
        self.pumps += 1

    def destroy_bar_window(self, hwnd):
        self.destroyed.append(hwnd)

    def press(self, which):
        setattr(self.state, f"{which}_requested", True)


@pytest.fixture
def rail(monkeypatch):
    fake = FakeBar()
    monkeypatch.setattr(act_rail, "bar", fake)
    return fake


def _event(kind, ordinal=0, total=0, detail=""):
    return SimpleNamespace(
        type=kind,
        node_id=f"n{ordinal:03d}",
        operation_id="powerpoint.add_text",
        ordinal=ordinal,
        total=total,
        detail=detail,
        at_s=0.0,
    )


# --- the step is reported, never counted ----------------------------------


def test_the_step_comes_from_the_executors_own_numbers(rail):
    session = open_rail()

    session.on_event(_event("action_started", 12, 255))

    assert rail.statuses[-1] == "Step 12 of 255 · running"


def test_the_rail_does_not_count_its_own_events(rail):
    """Three events all reporting node 7 must read as step 7, not step 3.
    A rail that counted could disagree with the executor about which node is
    running, and the number the user reads is then not the number the runtime
    is acting on."""

    session = open_rail()

    for kind in ("action_started", "action_completed", "action_started"):
        session.on_event(_event(kind, 7, 255))

    assert all("of 255" in text for text in rail.statuses[1:])
    assert rail.statuses[-1].startswith("Step 7 ")
    assert not any("Step 3" in text for text in rail.statuses)


def test_a_jump_backwards_is_shown_as_reported(rail):
    """The rail does not smooth, clamp or monotonically enforce the step. If
    the executor reports 4 after 9 that is what happened, and hiding it would
    hide a real defect."""

    session = open_rail()
    session.on_event(_event("action_started", 9, 255))
    session.on_event(_event("action_started", 4, 255))

    assert rail.statuses[-1].startswith("Step 4 of 255")


def test_no_step_is_shown_before_the_executor_reports_one(rail):
    """Guessing "1 of 255" before the first node event is the rail counting."""

    session = open_rail()

    assert rail.statuses == ["Preparing"]
    assert session.step is None


def test_an_event_with_no_ordinal_does_not_erase_the_step(rail):
    session = open_rail()
    session.on_event(_event("action_started", 12, 255))

    session.on_event(_event("something_else", 0, 0))

    assert rail.statuses[-1].startswith("Step 12 of 255")


# --- a requested stop stays requested -------------------------------------


def test_a_requested_stop_holds_its_message(rail):
    """The run is still finishing the node it is in. Reverting to a step
    number would read as the request having been dropped."""

    controls = ActControls()
    session = open_rail()
    session.on_event(_event("action_started", 12, 255))
    rail.press("stop")

    session.poll(controls)
    session.on_event(_event("action_completed", 12, 255))
    session.on_event(_event("action_started", 13, 255))

    assert rail.statuses[-1] == "Stopping…"
    assert controls.stop_event.is_set()


def test_one_click_is_one_request(rail):
    """Without clearing, a single press reads as a request on every later
    poll -- and a pause would toggle itself on and off forever."""

    controls = ActControls()
    session = open_rail()
    rail.press("pause")

    session.poll(controls)
    session.poll(controls)
    session.poll(controls)

    assert rail.cleared == 2  # once at open, once for the press
    assert session.paused is True


def test_pause_toggles_and_resumes(rail):
    controls = ActControls()
    session = open_rail()
    session.on_event(_event("action_started", 5, 255))

    rail.press("pause")
    session.poll(controls)
    assert controls.paused is True
    assert rail.statuses[-1] == "Paused — Step 5 of 255"

    rail.press("pause")
    session.poll(controls)
    assert controls.paused is False
    assert rail.statuses[-1].startswith("Step 5 of 255")


def test_a_stop_after_a_pause_still_stops(rail):
    """The dangerous ordering: paused, then Stop. A resume-only path would
    leave the run parked with the user believing they had ended it."""

    controls = ActControls()
    session = open_rail()
    rail.press("pause")
    session.poll(controls)

    rail.press("stop")
    session.poll(controls)

    assert controls.stop_event.is_set()
    assert rail.statuses[-1] == "Stopping…"


def test_polling_with_nothing_pressed_changes_nothing(rail):
    controls = ActControls()
    session = open_rail()
    session.on_event(_event("action_started", 5, 255))
    before = list(rail.statuses)

    session.poll(controls)

    assert rail.statuses == before
    assert controls.stop_event.is_set() is False


# --- the end is the end ---------------------------------------------------


@pytest.mark.parametrize("kind", ["run_completed", "run_failed", "refused"])
def test_a_terminal_event_shows_its_own_detail(rail, kind):
    session = open_rail()
    session.on_event(_event("action_started", 255, 255))

    session.on_event(_event(kind, 255, 255, detail="the deck was saved"))

    assert rail.statuses[-1] == "the deck was saved"


def test_nothing_after_the_end_rewords_the_outcome(rail):
    """A late event must not turn a finished run back into a running one --
    the session surface may not reinterpret published state."""

    session = open_rail()
    session.on_event(_event("run_failed", 12, 255, detail="verification failed"))

    session.on_event(_event("action_started", 13, 255))

    assert rail.statuses[-1] == "verification failed"


def test_a_long_detail_is_shortened_rather_than_dropped(rail):
    session = open_rail()

    session.on_event(_event("run_failed", 1, 2, detail="x" * 200))

    assert len(rail.statuses[-1]) <= 40
    assert rail.statuses[-1].endswith("…")


def test_a_terminal_event_with_no_detail_still_says_something(rail):
    session = open_rail()

    session.on_event(_event("run_completed", 255, 255, detail="   "))

    assert rail.statuses[-1] == "finished"


# --- the pump and the stop read live on one callback ----------------------


def test_the_keep_running_callback_pumps_and_reads_the_rail(rail):
    """Handed to the presenter, so the rail is serviced on the same callback
    that decides whether a cue may continue. Two loops could drift, and the
    one that drifts is the one holding Stop."""

    controls = ActControls()
    session = open_rail()
    keep_running = rail_pump(session, controls)

    assert keep_running() is True
    assert rail.pumps == 1

    rail.press("stop")
    assert keep_running() is False
    assert controls.stop_event.is_set()


def test_the_rail_is_torn_down(rail):
    session = open_rail()

    act_rail.close_rail(session)

    assert rail.destroyed == [HWND]


def test_the_session_keeps_every_event_for_the_record(rail):
    session = open_rail()
    for ordinal in (1, 2, 3):
        session.on_event(_event("action_started", ordinal, 3))

    assert [event.ordinal for event in session.events] == [1, 2, 3]
    assert isinstance(session, RailSession)
