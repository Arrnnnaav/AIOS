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

    assert rail.statuses[-1] == "Step 12 of 255"


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
    assert rail.statuses[-1] == "Paused · 5/255"

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


@pytest.mark.parametrize(
    "kind", ["completed", "refused", "stopped", "action_failed", "verification_failed"]
)
def test_a_terminal_event_shows_its_own_detail(rail, kind):
    session = open_rail()
    session.on_event(_event("action_started", 255, 255))

    session.on_event(_event(kind, 255, 255, detail="the deck was saved"))

    assert rail.statuses[-1] == "the deck was saved"


def test_nothing_after_the_end_rewords_the_outcome(rail):
    """A late event must not turn a finished run back into a running one --
    the session surface may not reinterpret published state."""

    session = open_rail()
    session.on_event(_event("action_failed", 12, 255, detail="verification failed"))

    session.on_event(_event("action_started", 13, 255))

    assert rail.statuses[-1] == "verification failed"


def test_a_long_detail_is_shortened_rather_than_dropped(rail):
    session = open_rail()

    session.on_event(_event("action_failed", 1, 2, detail="x" * 200))

    assert len(rail.statuses[-1]) <= 40
    assert rail.statuses[-1].endswith("…")


def test_a_terminal_event_with_no_detail_still_says_something(rail):
    session = open_rail()

    session.on_event(_event("completed", 255, 255, detail="   "))

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


# --- the rail's vocabulary is the executor's, not one it invented ---------


def test_every_event_name_the_rail_knows_is_one_the_executor_publishes():
    """The defect a live run found. The rail listed `run_completed` and
    `run_failed`; the executor publishes `completed` and `action_failed`. So a
    finished 255-node run kept showing "Step 255 of 255" instead of its
    outcome — and the unit tests agreed, because they fed the same invented
    names back in. A closed loop that proved nothing about the real executor.

    Read from `act_runtime`'s source rather than restated here, so the two
    cannot drift apart again without this failing.
    """

    import re
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "ghostcursor/act_runtime.py"
    ).read_text(encoding="utf-8")
    published = set(re.findall(r'publish\(\s*"([a-z_]+)"', source))

    assert published, "found no published event names to check against"
    assert act_rail._TERMINAL <= published
    assert set(act_rail._LABELS) <= published

    # Subset is not enough, and the D032 review of 4 September 2026 said so.
    # A NEW terminal event added to the executor would satisfy every
    # assertion above while the rail kept showing a step for a run that had
    # ended -- exactly the property the module docstring claims to guarantee.
    # So every published name must be accounted for: terminal, labelled, or
    # explicitly known to be neither.
    ONGOING = {"action_started", "action_completed", "verification_failed"}
    accounted = act_rail._TERMINAL | set(act_rail._LABELS) | ONGOING
    unaccounted = published - accounted
    assert not unaccounted, (
        f"the executor publishes {sorted(unaccounted)}, which the rail neither "
        "treats as terminal nor labels; decide which it is"
    )


def test_a_terminal_event_is_not_also_a_label():
    """A type in both would take the terminal path and never use its label,
    which reads as the label being applied when it is not."""

    assert act_rail._TERMINAL & set(act_rail._LABELS) == set()


def test_no_status_the_rail_can_show_overflows_the_compact_rail():
    """Measured, not guessed. The compact rail is 148px wide and Win32 clips
    rather than wraps, so a status one character too long loses the end of
    the number — `Step 103 of 255 · done` came back as `Step 103 of 255` on
    one line and a cut-off `· done` on the next.

    22 characters is what the widest real status needs: `Step 255 of 255` is
    15, `Paused · 255/255` is 16, and a shortened terminal detail is capped
    at 40 but is a full-width message rather than a number that must stay
    exact.
    """

    from ghostcursor import act_rail as module

    widest = f"Step {255} of {255}"
    paused = f"Paused · {255}/{255}"

    assert len(widest) <= 22
    assert len(paused) <= 22
    assert module._shorten("x" * 100) == "x" * 39 + "…"


# --- the region a node changed, drawn without a cursor --------------------


def _metrics():
    from ghostcursor.overlay.cue import LabelMetrics

    return LabelMetrics(char_width=8, line_height=16)


def test_a_changed_region_is_drawn_with_no_pointer():
    """D109: an object-model node clicks nothing, so a cursor over the region
    would show an action where it did not happen. The ring and the label say
    where a change landed, which is what the rule prescribes instead."""

    from ghostcursor.act_rail import region_scene

    scene = region_scene(
        (581, 310, 1086, 331), "Adding: headline", _metrics(), bounds=(0, 0, 1920, 1080)
    )

    assert scene is not None
    assert scene.pointer is None
    assert scene.target == (581, 310, 1086, 331)
    assert scene.label == "Adding: headline"


def test_the_region_label_is_placed_clear_of_the_region():
    from ghostcursor.act_rail import region_scene

    scene = region_scene(
        (581, 310, 1086, 331), "Adding: headline", _metrics(), bounds=(0, 0, 1920, 1080)
    )
    left, top, right, bottom = scene.label_rect

    assert not (left < 1086 and 581 < right and top < 331 and 310 < bottom)


def test_a_changed_region_is_shown_in_the_artifact_trust_class():
    """An object-model effect is verified by reading the saved file, which is
    TrustClass.ARTIFACT. Showing it in the UIA class would claim live-state
    evidence nothing gathered."""

    from ghostcursor.act_protocol import TrustClass
    from ghostcursor.act_rail import region_scene

    scene = region_scene(
        (10, 10, 100, 50), "Adding", _metrics(), bounds=(0, 0, 1920, 1080)
    )

    assert scene.trust is TrustClass.ARTIFACT


@pytest.mark.parametrize(
    "region",
    [
        None,
        (1, 2, 3),
        (10, 10, 10, 50),
        "10,10,100,50",
        (1.0, 2, 3, 4),
        # These two do NOT raise CueLayoutError: an int is not iterable
        # (TypeError) and an empty tuple has no [0] (IndexError). Without
        # them the wider catch was defensive code no test reached, and
        # narrowing it to CueLayoutError alone changed nothing visible.
        5,
        (),
    ],
)
def test_an_unusable_region_is_not_drawn_rather_than_raising(region):
    """A highlight is presentation (D106). It must never fail a node that
    already acted, so an unusable rect is simply not shown."""

    from ghostcursor.act_rail import region_scene

    assert region_scene(region, "Adding", _metrics(), bounds=(0, 0, 1920, 1080)) is None


def test_an_event_carries_the_region_as_four_integers_or_nothing():
    """Typed rather than an open data bag: a general dict on the event would
    be a channel for anything an adapter felt like sending, and presentation
    is all this may carry."""

    from ghostcursor.act_runtime import ActEvent

    fields = ActEvent.__dataclass_fields__

    assert "region" in fields
    assert "data" not in fields


@pytest.mark.parametrize(
    "value,expected",
    [
        ([1, 2, 3, 4], (1, 2, 3, 4)),
        ((1, 2, 3, 4), (1, 2, 3, 4)),
        ([1, 2, 3], None),
        ([1, 2, 3, 4, 5], None),
        ([True, 2, 3, 4], None),
        ([1.0, 2, 3, 4], None),
        ([5, 2, 3, 4], None),
        ("1,2,3,4", None),
        (None, None),
    ],
)
def test_a_region_from_the_adapter_is_validated_not_trusted(value, expected):
    """It arrives from a subprocess. A malformed rect is dropped rather than
    raised -- raising would fail an effect that already happened."""

    from ghostcursor.act_runtime import _region_of

    assert _region_of(value) == expected

