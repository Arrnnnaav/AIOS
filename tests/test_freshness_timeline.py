"""The staleness ladder as the USER experiences it, over time, inside run_tour.

Every piece of this behaviour is already unit-tested in isolation: the ladder's
thresholds and debounce in `test_staleness.py`, the dimmed ring's colour in the
`test_overlay` pixel harness, the health policy in `test_worker_health.py`. All
of those passed while the assembled system did nothing at all.

That is not hypothetical. Two bugs with exactly that signature — every
component correct, the composition wrong — shipped into review on this
milestone:

  * the tour's `snapshotter` called `ladder.observed()` on every slot read, so
    re-reading a hung target's stale observation re-confirmed it every tick and
    the clock never advanced. Nothing would ever dim, nothing would ever hide,
    and the health check (whose stall signal is the ladder's age) would never
    fire either;
  * `WorkerHealth` read `ladder.age()` as `inf` before the first observation
    and ended the tour on tick 2, before perception had answered once.

Both are reproduced below as named regression cases rather than left to a
generic happy path, because a happy-path test that merely ends in the right
state can pass while the sequence to get there was wrong.

Time is driven by hand through ONE shared clock — `run_tour`'s deadline, the
health budget and the ladder all read it, and the sleeper advances it. Nothing
here sleeps for real.
"""

from ghostcursor.overlay import dpi  # noqa: F401  DPI awareness before any window
from ghostcursor.perception.service import Observation
from ghostcursor.reasoning.staleness import Freshness
from ghostcursor.reasoning.verification import Snapshot
from ghostcursor.perception.uia import Element
from tests.test_run_threaded import _fake_overlay, _recipe_file

#: Matches the recipe's claimed target name, so grounding succeeds at rung 2.
EXPORT = Element(
    name="Export",
    control_type="Button",
    automation_id="1001",
    bbox=(100, 100, 200, 150),
    path=("Button",),
)


class FakeClock:
    """One clock. `sleeper` is the only thing that advances it, so the loop's
    notion of "now" and the ladder's cannot drift apart."""

    #: Deliberately not 0.0. `observed_at == 0.0` is the sentinel meaning
    #: "untimestamped", which the loop treats as always-fresh so synchronous
    #: and faked perception keep working (D023). A clock starting at zero would
    #: publish a real observation that reads as the sentinel, and the ladder
    #: would never be fed. Real `time.monotonic()` never returns 0 either.
    START = 1000.0

    def __init__(self):
        self.t = self.START

    def __call__(self) -> float:
        return self.t

    def sleeper(self, seconds: float) -> None:
        self.t += seconds


class ScriptedService:
    """A perception worker whose publishing the test controls exactly.

    `publishing` False models a wedged worker: the slot keeps its LAST
    observation, which is what a real hung target looks like — the worker is
    stuck inside a walk, so nothing new is ever published, but what it
    published before is still sitting there.
    """

    def __init__(self, clock, elements=(EXPORT,)):
        self._clock = clock
        self._elements = elements
        self.publishing = True
        self.heartbeat = 0
        self.restarts = 0
        self._slot = None

    def start(self):
        # Only seeds the slot if it is publishing — a worker wedged on FIRST
        # contact has never published anything, and `latest()` must return
        # None for that case rather than a fabricated observation.
        if self.publishing:
            self._observe()

    def stop(self):
        pass

    def restart(self):
        self.restarts += 1

    def is_alive(self):
        return True

    def _observe(self):
        now = self._clock()
        self._slot = Observation(
            snapshot=Snapshot(title="app", elements=self._elements, observed_at=now),
            elements=self._elements,
            observed_at=now,
            ok=True,
        )

    def latest(self):
        self.heartbeat += 1
        if self.publishing:
            self._observe()
        return self._slot


def _run(monkeypatch, tmp_path, clock, service, seconds, script=None):
    """Drive run_tour with a scripted service and a hand-driven clock.

    Returns the ordered list of overlay calls and everything printed.
    """
    import ghostcursor.run as run_module
    from ghostcursor.perception import appinfo, service as service_module

    calls = _fake_overlay(monkeypatch)
    monkeypatch.setattr(service_module, "PerceptionService", lambda *a, **k: service)
    monkeypatch.setattr(appinfo, "app_info_for_window", lambda _t: None)
    monkeypatch.setattr(run_module, "escape_pressed", lambda: False)
    monkeypatch.setattr(run_module, "key_was_pressed", lambda vk: False)

    printed = []
    monkeypatch.setattr(
        "builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a)))
    )

    def sleeper(duration):
        clock.sleeper(duration)
        if script is not None:
            script(clock.t)

    run_module.run_tour(
        _recipe_file(tmp_path),
        ".*app.*",
        seconds=seconds,
        clock=clock,
        sleeper=sleeper,
    )
    return calls, printed


def _freshness_sequence(calls):
    """The ordered story the overlay told, collapsing consecutive repeats.

    Repeats are collapsed because the tick rate is an implementation detail —
    what matters is the ORDER of the states the user passed through, not how
    many ticks each lasted.
    """
    story = []
    for call in calls:
        if call[0] == "set_hint":
            state = call[3] or Freshness.FRESH
        elif call[0] == "clear_hint":
            state = "CLEARED"
        else:
            continue
        if not story or story[-1] != state:
            story.append(state)
    return story


def _contains_in_order(story, expected):
    """True if `expected` appears in `story` in order, gaps allowed."""
    remaining = list(expected)
    for state in story:
        if remaining and state == remaining[0]:
            remaining.pop(0)
    return not remaining


def test_a_hang_dims_then_hides_then_restores_the_hint(tmp_path, monkeypatch):
    """The composed timeline, asserted as an ordered sequence.

    A hint is shown, the target hangs for ~10s, then recovers. The user must
    see: the hint -> the hint dimmed -> nothing -> the hint again. And the tour
    must NOT end: a momentary hang is not a reason to abandon a lesson.
    """
    clock = FakeClock()
    service = ScriptedService(clock)

    def script(now):
        # Hang from 2s to 12s. Before and after, the worker publishes normally.
        service.publishing = not (clock.START + 2.0 <= now < clock.START + 12.0)

    calls, printed = _run(
        monkeypatch, tmp_path, clock, service, seconds=20.0, script=script
    )
    story = _freshness_sequence(calls)

    # The whole point: assert the ORDER, not just that each state occurred.
    # A test that only checked membership would pass if the hint hid before it
    # dimmed, or never came back.
    #
    # An ordered subsequence rather than exact equality, because the loop emits
    # one no-op `clear_hint` on its very first tick: IDLE -> OBSERVING does not
    # snapshot, so the ladder has not been fed yet and reads HIDDEN. Clearing
    # an overlay that has never drawn anything is invisible to the user, so it
    # is not part of the story being asserted.
    assert _contains_in_order(
        story, [Freshness.FRESH, Freshness.DIMMED, "CLEARED", Freshness.FRESH]
    ), (
        "the user did not see hint -> dimmed -> nothing -> hint again over a "
        f"10s hang and recovery. Actual sequence: {story}"
    )

    assert not any(line.startswith("Stopped:") for line in printed), (
        f"a 10s hang ended the tour; it should only dim and recover: {printed}"
    )


def test_regression_feeding_the_ladder_on_every_read_never_dims(tmp_path, monkeypatch):
    """Named regression: the bug that would have shipped a silent no-op.

    The briefed `snapshotter` called `ladder.observed()` on every slot read.
    A wedged worker leaves its PREVIOUS observation in the slot, so every tick
    re-confirmed the same stale observation and reset the clock. Nothing ever
    dimmed, nothing ever hid, and health never fired — while every unit test
    of the ladder, the ring and the health policy still passed.

    This asserts the fix from the outside: the ladder must be fed only when
    the observation's timestamp actually ADVANCES.
    """
    clock = FakeClock()
    service = ScriptedService(clock)

    def script(now):
        service.publishing = now < clock.START + 2.0  # wedged forever after 2s

    calls, _ = _run(monkeypatch, tmp_path, clock, service, seconds=12.0, script=script)
    story = _freshness_sequence(calls)

    assert Freshness.DIMMED in story and "CLEARED" in story, (
        "a permanently wedged worker never dimmed or hid the hint. The "
        "staleness clock is being reset by re-reads of the same stale "
        f"observation, so the ladder does nothing in the assembled system: {story}"
    )


def test_regression_health_does_not_end_the_tour_before_the_first_observation(
    tmp_path, monkeypatch
):
    """Named regression: the tour dying on tick 2.

    `WorkerHealth`'s stall signal is `ladder.age()`, which is `inf` until the
    first observation lands. Wired literally, that restarts the worker on tick
    1 and ends the tour on tick 2 — before perception has answered even once,
    and while the application is merely slow rather than broken.
    """
    clock = FakeClock()
    service = ScriptedService(clock)
    service.publishing = False  # nothing in the slot yet at all

    def script(now):
        service.publishing = now >= clock.START + 3.0  # answers after a slow 3s start

    calls, printed = _run(
        monkeypatch, tmp_path, clock, service, seconds=12.0, script=script
    )

    assert not any("perception" in line.lower() for line in printed), (
        "a target that was merely slow to answer was reported as a dead "
        f"perception worker: {printed}"
    )
    assert service.restarts == 0, (
        f"the worker was restarted {service.restarts}x before it had a chance to answer"
    )
    assert Freshness.FRESH in _freshness_sequence(calls), (
        "no hint was ever shown after perception started answering: "
        f"{_freshness_sequence(calls)}"
    )
