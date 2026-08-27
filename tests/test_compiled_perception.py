"""The compiled perception stack, composed for real.

Every other test in this area exercises one piece against a fake of its
neighbour, or scans source for a forbidden name. Both are useful and neither
catches an adapter that cannot consume what the layer beneath it produces --
which is exactly how a `FindAll` returning raw COM elements met a `make_info`
expecting pywinauto controls, with the whole suite green.

So here the real objects are wired to each other: the real
`PerceptionService`, the real plan runner, the real observation source, the
real staleness ladder, the real executor. Only the OS boundary is faked --
what a UIA walk returns, what a provider query returns, what a window is
titled. Nothing between those and the tour result is a stand-in.
"""

from __future__ import annotations

import ast
import threading

import pytest

from ghostcursor.perception.compiled import (
    CompiledObservationSource,
    CompiledPerception,
    PywinautoElementInfo,
    RawElementInfo,
    build_compiled_perception,
    compiled_perception_service,
    compiled_plan_runner,
    merge_ocr,
)
from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.compiled_tour import RunOutcome, execute_compiled_workflow

pytest_plugins = ()

TARGET_HWND = 4242


# ---------------------------------------------------------------------------
# The OS boundary, and nothing above it
# ---------------------------------------------------------------------------


class _Rect:
    def __init__(self, bbox):
        self.left, self.top, self.right, self.bottom = bbox


class _RawElement:
    """What `IUIAutomationElement` looks like to a property read.

    Deliberately NOT shaped like a pywinauto control: no `element_info`, no
    `rectangle()`. An adapter that assumed those would raise here, which is
    the failure this file exists to catch.
    """

    def __init__(
        self,
        name,
        control_type=50000,
        automation_id="",
        bbox=(1, 2, 3, 4),
        runtime_id=(7, 1),
    ):
        self.CurrentName = name
        self.CurrentControlType = control_type
        self.CurrentAutomationId = automation_id
        self.CurrentBoundingRectangle = _Rect(bbox)
        self._runtime_id = runtime_id

    def GetRuntimeId(self):
        return self._runtime_id


class _PywinautoControl:
    """What a bounded walk returns."""

    def __init__(self, name, control_type="Button", bbox=(10, 20, 110, 60)):
        self._name = name
        self._control_type = control_type
        self._bbox = bbox

    def window_text(self):
        return self._name

    def rectangle(self):
        return _Rect(self._bbox)

    @property
    def element_info(self):
        info = type("I", (), {})()
        info.name = self._name
        info.control_type = self._control_type
        info.automation_id = ""
        return info


def _workflow():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_compiled_workflow import _target, _window, _workflow as build

    workflow, catalog = build(target=_target(_window(hwnd=TARGET_HWND)))
    return workflow, catalog


# ---------------------------------------------------------------------------
# Adapters must match what the layer beneath actually returns
# ---------------------------------------------------------------------------


def test_the_provider_adapter_reads_a_raw_uia_element() -> None:
    """`FindAll` hands back COM elements, not pywinauto controls."""
    info = RawElementInfo(_RawElement(" Extensions", automation_id="ext"))
    assert info.name == " Extensions"
    assert info.control_type == "Button"
    assert info.automation_id == "ext"
    assert (info.rectangle.left, info.rectangle.bottom) == (1, 4)
    assert info.runtime_id == (7, 1)


def test_the_walk_adapter_reads_a_pywinauto_control() -> None:
    info = PywinautoElementInfo(_PywinautoControl("Open Folder..."))
    assert info.name == "Open Folder..."
    assert info.rectangle.right == 110


def test_the_two_adapters_are_not_interchangeable() -> None:
    """The point of having two.

    Each raises on the other's input, so a single adapter could not have
    served both -- and one that appeared to would be reading properties that
    are not there.
    """
    with pytest.raises(AttributeError):
        RawElementInfo(_PywinautoControl("Open Folder..."))
    with pytest.raises(AttributeError):
        PywinautoElementInfo(_RawElement("Extensions"))


def test_a_provider_query_flows_end_to_end_into_a_selector_result() -> None:
    """Raw element in, published `Element` out, through the real plan runner."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_compiled_workflow import _catalog, _recipe_value, _selector

    recipe = _recipe_value()
    recipe["selectors"] = {
        "open_folder": _selector(
            names=("Extensions",),
        )
    }
    recipe["selectors"]["open_folder"]["strategy"] = "provider_exact"
    recipe["selectors"]["open_folder"]["normalise"] = "none"
    recipe["steps"][0]["target_selector"] = "open_folder"

    from ghostcursor.packs.workflow import materialize
    from test_compiled_workflow import _adoption, _target, _window

    adoption = _adoption()
    object.__setattr__(adoption, "recipe_value", recipe)
    catalog, pack, intent = _catalog(adoption=adoption)
    workflow = materialize(
        catalog,
        pack,
        intent,
        "Open a folder in VS Code",
        _target(_window(hwnd=TARGET_HWND)),
    )

    runner = compiled_plan_runner(
        workflow,
        walk=lambda hwnd, control_type: [],
        query=lambda hwnd, control_type, name: (
            [_RawElement(name)] if hwnd == TARGET_HWND else []
        ),
        read_title=lambda hwnd: "demo - Visual Studio Code",
    )
    selector_results, union, title = runner(0)
    matched = dict(selector_results)["open_folder"]
    assert len(matched) == 1
    assert isinstance(matched[0], Element)
    assert matched[0].name == "Extensions"
    assert matched[0].bbox == (1, 2, 3, 4)
    assert title == "demo - Visual Studio Code"
    assert union == matched


# ---------------------------------------------------------------------------
# The captured HWND, never a title search
# ---------------------------------------------------------------------------


def test_perception_is_pinned_to_the_captured_window() -> None:
    """Open Folder changes the title as its verified outcome.

    A worker that re-finds its window by the initial title loses the target at
    exactly the moment verification needs it, and may attach to a different
    matching window -- the captured-target contract broken outright.
    """
    workflow, _catalog = _workflow()
    service = compiled_perception_service(workflow, lambda: 0.0)

    for title in (workflow.target.title, "demo - Visual Studio Code", "", ".*"):
        assert service.hwnd_source(title) == TARGET_HWND


def test_the_plan_runner_queries_the_captured_handle_not_the_resolved_one() -> None:
    workflow, _catalog = _workflow()
    seen = []
    runner = compiled_plan_runner(
        workflow,
        walk=lambda hwnd, control_type: seen.append(hwnd) or [],
        query=lambda hwnd, control_type, name: [],
        read_title=lambda hwnd: "t",
    )
    runner(999)  # a resolved handle that disagrees
    assert seen and set(seen) == {TARGET_HWND}


def test_the_published_title_is_the_bound_windows_not_the_foreground() -> None:
    """They agree while the target has focus and diverge when it does not.

    That divergence is the moment a title check would silently start reading
    somebody else's window.
    """
    workflow, _catalog = _workflow()
    runner = compiled_plan_runner(
        workflow,
        walk=lambda hwnd, control_type: [],
        query=lambda hwnd, control_type, name: [],
        read_title=lambda hwnd: f"title-of-{hwnd}",
    )
    _selectors, _union, title = runner(0)
    assert title == f"title-of-{TARGET_HWND}"


# ---------------------------------------------------------------------------
# Tier 2
# ---------------------------------------------------------------------------


def _ocr(name, bbox=(5, 5, 50, 20)):
    return Element(
        name=name, control_type="", automation_id="", bbox=bbox, path=(), source="ocr"
    )


def test_ocr_escalates_a_selector_uia_could_not_see() -> None:
    workflow, _catalog = _workflow()
    plan = workflow.recipe.plan
    merged = merge_ocr(
        plan, {"open_folder": ()}, (_ocr("Open Folder..."),), "open_folder"
    )
    assert len(merged["open_folder"]) == 1
    assert merged["open_folder"][0].source == "ocr"


def test_ocr_never_displaces_a_confirmed_control() -> None:
    """A pixel guess must not overwrite a real one (D006).

    A selector that already matched has no failure to escalate from, so there
    is nothing for OCR to answer.
    """
    workflow, _catalog = _workflow()
    confirmed = Element("Open Folder...", "Button", "", (1, 1, 2, 2), ("Button",))
    merged = merge_ocr(
        workflow.recipe.plan,
        {"open_folder": (confirmed,)},
        (_ocr("Open Folder..."),),
        "open_folder",
    )
    assert merged["open_folder"] == (confirmed,)


def test_ocr_matching_uses_the_selectors_own_trusted_names() -> None:
    workflow, _catalog = _workflow()
    merged = merge_ocr(
        workflow.recipe.plan, {"open_folder": ()}, (_ocr("Something Else"),), "open_folder"
    )
    assert merged["open_folder"] == ()


def test_an_ambiguous_ocr_read_faults_rather_than_reading_as_absence() -> None:
    """The declared cardinality binds, and it fails CLOSED.

    Returning an empty result would report "the control is not on screen"
    about a screen that showed it twice -- the flattening of a fault into an
    absence that D069 exists to prevent, arriving through the OCR door. A
    pixel guess does not get a weaker rule than a confirmed control.
    """
    from ghostcursor.perception.uia import SelectorAmbiguityFault

    workflow, _catalog = _workflow()
    with pytest.raises(SelectorAmbiguityFault):
        merge_ocr(
            workflow.recipe.plan,
            {"open_folder": ()},
            (
                _ocr("Open Folder...", (1, 1, 2, 2)),
                _ocr("Open Folder...", (9, 9, 10, 10)),
            ),
            "open_folder",
        )


def test_an_over_limit_ocr_read_faults_rather_than_truncating() -> None:
    """`result_limit` raises, never truncates -- for OCR exactly as for UIA."""
    from ghostcursor.perception.uia import ProviderQueryFault
    from test_compiled_workflow import _adoption, _catalog, _recipe_value, _selector

    recipe = _recipe_value()
    recipe["selectors"] = {"open_folder": _selector(cardinality="at_least_one")}
    recipe["selectors"]["open_folder"]["result_limit"] = 2
    recipe["steps"][0]["target_selector"] = None
    recipe["steps"][0]["verification_rule"] = {
        "kind": "element_appears",
        "selector": "open_folder",
        "args": {},
        "timeout_s": 20.0,
    }
    adoption = _adoption()
    object.__setattr__(adoption, "recipe_value", recipe)
    catalog, pack, intent = _catalog(adoption=adoption)

    from ghostcursor.packs.workflow import materialize
    from test_compiled_workflow import _target, _window

    workflow = materialize(
        catalog, pack, intent, "Open a folder in VS Code",
        _target(_window(hwnd=TARGET_HWND)),
    )
    three = tuple(
        _ocr("Open Folder...", (i, i, i + 1, i + 1)) for i in range(1, 4)
    )
    with pytest.raises(ProviderQueryFault):
        merge_ocr(workflow.recipe.plan, {"open_folder": ()}, three, "open_folder")


class _FakeService:
    """Records the tier-2 conversation, and nothing else."""

    def __init__(self, observations=()):
        self.observations = list(observations)
        self.requested = []
        self.cancelled = 0
        self.grounded = []

    def latest(self):
        if not self.observations:
            return None
        return self.observations[-1]

    def request_tier2(self, step_index):
        self.requested.append(step_index)

    def cancel_tier2(self, step_index=None):
        self.cancelled += 1

    def report_tier2_grounded(self, step_index):
        self.grounded.append(step_index)


class _Ladder:
    """A minimal ladder for the tier-2 tests, which are not about staleness.

    Carries a `clock` because the real `StalenessLadder` does and the source
    reads it for the health grace -- a fake missing it would only prove the
    source never asked.
    """

    def __init__(self, clock=None):
        self.clock = clock or (lambda: 0.0)
        self.observations = 0

    def observed(self):
        self.observations += 1

    def age(self):
        return 0.0

    def freshness(self):
        from ghostcursor.reasoning.staleness import Freshness

        return Freshness.FRESH


def test_a_failed_grounding_requests_tier_two_and_a_success_cancels_it() -> None:
    """The UI thread decides and requests; the worker executes (D035).

    Absence of a request means "not wanted" -- there is no `wanted` flag -- so
    a success that did not cancel would leave OCR running for a step that no
    longer needs it.
    """
    service = _FakeService()
    source = CompiledObservationSource(service, _Ladder())

    source.note_grounding(0, False, "open_folder")
    assert service.requested == [0]

    source.note_grounding(0, True, "open_folder")
    assert service.grounded == [0]
    assert service.cancelled >= 1


def test_a_step_boundary_cancels_the_previous_steps_request() -> None:
    """Stickiness resets at the step boundary, or one step's OCR answers
    another's question."""
    service = _FakeService()
    source = CompiledObservationSource(service, _Ladder())
    source.note_grounding(0, False, "open_folder")
    before = service.cancelled
    source.note_grounding(1, False, "open_folder")
    assert service.cancelled > before


# ---------------------------------------------------------------------------
# Staleness and worker health
# ---------------------------------------------------------------------------


class _Observation:
    def __init__(self, snapshot, observed_at, ocr_elements=(), tier2_step=-1):
        self.snapshot = snapshot
        self.observed_at = observed_at
        self.ocr_elements = ocr_elements
        self.tier2_step = tier2_step


def _snapshot(title="t", selectors=(), elements=()):
    from ghostcursor.reasoning.verification import Snapshot

    return Snapshot(title=title, elements=elements, selector_results=selectors)


def test_each_new_observation_ages_the_staleness_ladder() -> None:
    """A ladder nobody feeds reports HIDDEN forever, so no hint ever draws."""
    ladder = _Ladder()
    service = _FakeService([_Observation(_snapshot(), 1.0)])
    source = CompiledObservationSource(service, ladder)

    source()
    assert ladder.observations == 1

    source()  # the same slot, unchanged
    assert ladder.observations == 1, "an unchanged slot is not a new observation"

    service.observations.append(_Observation(_snapshot(), 2.0))
    source()
    assert ladder.observations == 2


class _AgeingLadder:
    """A real-enough ladder: `age()` is infinite until something is observed.

    That infinity is the whole reason the startup grace exists, so a fake that
    reported a finite age would hide the bug this section is about.
    """

    def __init__(self, clock):
        self.clock = clock
        self._last = None
        self.observations = 0

    def observed(self):
        self._last = self.clock()
        self.observations += 1

    def age(self):
        if self._last is None:
            return float("inf")
        return self.clock() - self._last

    def freshness(self):
        from ghostcursor.reasoning.staleness import Freshness

        return Freshness.FRESH


class _Progress:
    def __init__(self, last_completed_at=None, stage="walk", heartbeat=1):
        self.last_completed_at = last_completed_at
        self.stage = stage
        self.heartbeat = heartbeat


class _HealthService(_FakeService):
    """A service the REAL `WorkerHealth` can judge.

    Exposes what the policy actually reads -- liveness, progress, heartbeat --
    and records restarts, so the test observes the policy's decisions rather
    than a counter of how often it was consulted.
    """

    def __init__(self, observations=(), alive=True, last_completed_at=None):
        super().__init__(observations)
        self.alive = alive
        self.last_completed_at = last_completed_at
        self.restarts = 0
        self.heartbeat = 1

    def is_alive(self):
        return self.alive

    def progress(self):
        return _Progress(self.last_completed_at)

    def restart(self):
        self.restarts += 1
        self.alive = True


def _real_health(service, ladder, clock):
    from ghostcursor.perception.health import WorkerHealth

    return WorkerHealth(service=service, ladder=ladder, log=lambda _m: None)


def test_a_healthy_worker_is_not_restarted_on_the_first_empty_read() -> None:
    """The startup grace, against the real policy.

    `ladder.age()` is infinite until the first observation lands, and the
    policy reads that age as a stall. Unguarded, the very first empty-slot
    read restarts a perfectly healthy worker and the next one ends the tour --
    before perception has answered even once.
    """
    now = [0.0]
    clock = lambda: now[0]
    ladder = _AgeingLadder(clock)
    service = _HealthService()
    source = CompiledObservationSource(
        service, ladder, health=_real_health(service, ladder, clock), clock=clock
    )
    source.arm()

    assert source() is None
    assert service.restarts == 0, "a healthy worker was restarted before it answered"

    now[0] = 5.0
    assert source() is None
    assert service.restarts == 0


def test_a_worker_that_never_answers_is_still_caught_after_the_grace() -> None:
    """The grace bounds the wait; it does not remove the check.

    A worker that produces nothing at all is caught from a start time that
    exists, rather than from an infinite age that was never about this worker.
    """
    from ghostcursor.perception.health import PerceptionUnhealthy

    now = [0.0]
    clock = lambda: now[0]
    ladder = _AgeingLadder(clock)
    service = _HealthService()
    health = _real_health(service, ladder, clock)
    source = CompiledObservationSource(service, ladder, health=health, clock=clock)
    source.arm()

    source()
    now[0] = health.dead_after_s + 1.0
    source()  # the policy spends its one allowed restart here
    assert service.restarts == 1

    now[0] += health.dead_after_s + 1.0
    with pytest.raises(PerceptionUnhealthy):
        source()


def test_a_terminal_health_verdict_is_raised_not_discarded() -> None:
    """`check()` returning a reason is the END of the tour.

    The restart has already been spent. Discarding the reason left the source
    publishing its last stale observation forever -- a dead worker looking
    exactly like a screen that stopped changing.
    """
    from ghostcursor.perception.health import PerceptionUnhealthy

    now = [100.0]
    clock = lambda: now[0]
    ladder = _AgeingLadder(clock)
    service = _HealthService(
        [_Observation(_snapshot(title="stale"), 1.0)], last_completed_at=1.0
    )
    health = _real_health(service, ladder, clock)
    source = CompiledObservationSource(service, ladder, health=health, clock=clock)
    source.arm()

    ladder.observed()  # an observation HAS landed, so the grace is over
    now[0] += health.dead_after_s + 1.0

    source()  # restart spent
    assert service.restarts == 1
    now[0] += health.dead_after_s + 1.0

    with pytest.raises(PerceptionUnhealthy) as caught:
        source()
    assert "perception stopped working" in str(caught.value)


def test_a_dead_worker_never_publishes_a_normal_looking_tick() -> None:
    """The stale slot must not come back as an ordinary observation."""
    from ghostcursor.perception.health import PerceptionUnhealthy

    now = [0.0]
    clock = lambda: now[0]
    ladder = _AgeingLadder(clock)
    service = _HealthService(
        [_Observation(_snapshot(title="stale"), 1.0)], alive=False
    )
    health = _real_health(service, ladder, clock)
    source = CompiledObservationSource(service, ladder, health=health, clock=clock)
    source.arm()

    ladder.observed()
    source()  # restart spent; the fake comes back alive
    service.alive = False

    with pytest.raises(PerceptionUnhealthy):
        source()


def test_an_unhealthy_worker_ends_the_run_as_a_failure() -> None:
    """It has to reach the run record with a cause, not time out."""
    from ghostcursor.perception.health import PerceptionUnhealthy

    workflow, _catalog = _workflow()

    def _observe():
        raise PerceptionUnhealthy("perception stopped working (exited); ending the tour")

    class _Renderer:
        def show(self, grounded, instruction_text):
            pass

        def clear(self):
            pass

        def settle(self):
            pass

    now = [0.0]
    result = execute_compiled_workflow(
        workflow,
        observe=_observe,
        renderer=_Renderer(),
        clock=lambda: now[0],
        sleeper=lambda s: now.__setitem__(0, now[0] + s),
        seconds=5.0,
    )
    assert result.outcome is RunOutcome.FAILED
    assert "perception stopped working" in result.detail


def test_an_empty_slot_still_returns_none_while_healthy() -> None:
    now = [0.0]
    clock = lambda: now[0]
    ladder = _AgeingLadder(clock)
    service = _HealthService()
    source = CompiledObservationSource(
        service, ladder, health=_real_health(service, ladder, clock), clock=clock
    )
    source.arm()
    assert source() is None


# ---------------------------------------------------------------------------
# The whole stack, composed
# ---------------------------------------------------------------------------


def test_a_real_worker_drives_a_real_tour_to_completion() -> None:
    """Service, plan runner, source, ladder and executor, all real.

    The only fakes are what a walk returns, what a query returns, and what a
    window is titled. Everything between the OS and the tour result is the
    production object.
    """
    workflow, _catalog = _workflow()

    titles = ["Welcome - Visual Studio Code"]
    lock = threading.Lock()

    def _walk(hwnd, control_type):
        return [_PywinautoControl("Open Folder...")]

    def _read_title(hwnd):
        with lock:
            return titles[-1]

    service = compiled_perception_service(
        workflow,
        __import__("time").monotonic,
        plan_runner=compiled_plan_runner(
            workflow,
            walk=_walk,
            query=lambda hwnd, control_type, name: [],
            read_title=_read_title,
            make_info=PywinautoElementInfo,
        ),
        interval_s=0.01,
    )
    perception = build_compiled_perception(
        workflow, __import__("time").monotonic, service=service
    )

    source, on_grounding, stop_perception = perception.start()
    try:
        drawn = []

        class _Renderer:
            def show(self, grounded, instruction_text):
                drawn.append(grounded)

            def clear(self):
                pass

            def settle(self):
                pass

        def _sleeper(seconds):
            # The user acts: the folder opens and the title changes.
            if drawn:
                with lock:
                    titles.append("demo - Visual Studio Code")
            __import__("time").sleep(0.01)

        result = execute_compiled_workflow(
            workflow,
            observe=source,
            renderer=_Renderer(),
            seconds=2.0,
            tick_interval_s=0.01,
            sleeper=_sleeper,
            on_grounding=on_grounding,
        )
    finally:
        stop_perception()

    assert result.outcome is RunOutcome.PASSED, result
    assert result.provenance and result.provenance[0].value == "uia"
    assert drawn, "the tour never rendered a hint"


def test_the_composed_stack_never_walks_on_the_calling_thread() -> None:
    """Which thread the UIA calls happen on, observed rather than asserted.

    A source-level scan can say the executor imports nothing that walks. Only
    running it can say the walk actually happened somewhere else.
    """
    workflow, _catalog = _workflow()
    caller = threading.get_ident()
    walk_threads = set()

    def _walk(hwnd, control_type):
        walk_threads.add(threading.get_ident())
        return [_PywinautoControl("Open Folder...")]

    service = compiled_perception_service(
        workflow,
        __import__("time").monotonic,
        plan_runner=compiled_plan_runner(
            workflow,
            walk=_walk,
            query=lambda hwnd, control_type, name: [],
            read_title=lambda hwnd: "Welcome - Visual Studio Code",
            make_info=PywinautoElementInfo,
        ),
        interval_s=0.01,
    )
    perception = build_compiled_perception(
        workflow, __import__("time").monotonic, service=service
    )
    source, _hook, stop_perception = perception.start()
    try:
        deadline = __import__("time").monotonic() + 2.0
        while not walk_threads and __import__("time").monotonic() < deadline:
            source()
            __import__("time").sleep(0.01)
    finally:
        stop_perception()

    assert walk_threads, "the worker never walked"
    assert caller not in walk_threads, "UIA ran on the calling thread (D021)"


def test_the_source_merges_published_ocr_for_the_requested_step() -> None:
    """The merge has to happen where the observation is READ.

    `merge_ocr` being correct proves nothing if nothing calls it: the worker
    publishes `ocr_elements` and the source is the only thing that can fold
    them into the selector results the executor grounds from.
    """
    workflow, _catalog = _workflow()
    service = _FakeService()
    source = CompiledObservationSource(
        service, _Ladder(), plan=workflow.recipe.plan
    )
    source.note_grounding(0, False, "open_folder")

    service.observations.append(
        _Observation(
            _snapshot(selectors=(("open_folder", ()),)),
            observed_at=1.0,
            ocr_elements=(_ocr("Open Folder..."),),
            tier2_step=0,
        )
    )
    tick = source()
    assert len(tick.selectors["open_folder"]) == 1
    assert tick.selectors["open_folder"][0].source == "ocr"
    assert any(e.source == "ocr" for e in tick.union), (
        "an escalated element must reach the union too"
    )


def test_ocr_published_for_another_step_is_not_merged() -> None:
    """`tier2_step` exists so one step's read cannot answer another's question."""
    workflow, _catalog = _workflow()
    service = _FakeService()
    source = CompiledObservationSource(
        service, _Ladder(), plan=workflow.recipe.plan
    )
    source.note_grounding(1, False, "open_folder")

    service.observations.append(
        _Observation(
            _snapshot(selectors=(("open_folder", ()),)),
            observed_at=1.0,
            ocr_elements=(_ocr("Open Folder..."),),
            tier2_step=0,
        )
    )
    assert source().selectors["open_folder"] == ()


def test_the_executor_asks_for_tier_two_when_grounding_fails() -> None:
    """The request has to originate in the LOOP, not beside it.

    Only the tick loop knows which step is current and whether grounding just
    failed (D035), so a source with a correct `note_grounding` is inert until
    the executor calls it. Testing the source alone cannot see that.
    """
    workflow, _catalog = _workflow()
    requests = []
    grounded = []

    def _observe():
        from ghostcursor.reasoning.compiled_tour import TickInput

        return TickInput(
            title="Welcome - Visual Studio Code",
            selectors={"open_folder": ()},
            union=(),
        )

    class _Renderer:
        def show(self, grounded_target, instruction_text):
            pass

        def clear(self):
            pass

        def settle(self):
            pass

    now = [0.0]
    execute_compiled_workflow(
        workflow,
        observe=_observe,
        renderer=_Renderer(),
        clock=lambda: now[0],
        sleeper=lambda s: now.__setitem__(0, now[0] + s),
        seconds=5.0,
        on_grounding=lambda step, ok, sel: (
            (grounded if ok else requests).append((step, sel))
        ),
    )
    assert requests, "a failed grounding never asked for tier 2"
    assert set(requests) == {(0, "open_folder")}, requests
    assert grounded == []


def test_the_executor_reports_a_successful_grounding_too() -> None:
    workflow, _catalog = _workflow()
    reported = []

    def _observe():
        from ghostcursor.reasoning.compiled_tour import TickInput

        matched = (
            Element("Open Folder...", "Button", "", (1, 1, 2, 2), ("Button",)),
        )
        return TickInput(
            title="Welcome - Visual Studio Code",
            selectors={"open_folder": matched},
            union=matched,
        )

    class _Renderer:
        def show(self, grounded_target, instruction_text):
            pass

        def clear(self):
            pass

        def settle(self):
            pass

    now = [0.0]
    execute_compiled_workflow(
        workflow,
        observe=_observe,
        renderer=_Renderer(),
        clock=lambda: now[0],
        sleeper=lambda s: now.__setitem__(0, now[0] + s),
        seconds=2.0,
        on_grounding=lambda step, ok, sel: reported.append((step, ok, sel)),
    )
    assert (0, True, "open_folder") in reported


def _two_selector_workflow():
    """A recipe with an action target AND a separate verification selector."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ghostcursor.packs.workflow import materialize
    from test_compiled_workflow import (
        _adoption,
        _catalog,
        _recipe_value,
        _selector,
        _target,
        _window,
    )

    recipe = _recipe_value()
    recipe["selectors"] = {
        "open_folder": _selector(names=("Open Folder...",)),
        "folder_ready": _selector(
            names=("Open Folder...",), cardinality="at_least_one"
        ),
    }
    recipe["steps"][0]["target_selector"] = "open_folder"
    recipe["steps"][0]["verification_rule"] = {
        "kind": "element_appears",
        "selector": "folder_ready",
        "args": {"accept_if_already_present": True},
        "timeout_s": 20.0,
    }
    adoption = _adoption()
    object.__setattr__(adoption, "recipe_value", recipe)
    catalog, pack, intent = _catalog(adoption=adoption)
    return materialize(
        catalog, pack, intent, "Open a folder in VS Code",
        _target(_window(hwnd=TARGET_HWND)),
    )


def test_ocr_answers_only_the_selector_it_was_requested_for() -> None:
    """A read requested for the ACTION target must not fill a verification one.

    Both selectors here name the same control, so an unscoped merge populates
    both from one read. The verification selector uses
    `accept_if_already_present`, so filling it would complete a step the user
    never performed -- the worst direction for this to be wrong in.
    """
    workflow = _two_selector_workflow()
    plan = workflow.recipe.plan
    assert set(plan.selectors) == {"open_folder", "folder_ready"}

    merged = merge_ocr(
        plan,
        {"open_folder": (), "folder_ready": ()},
        (_ocr("Open Folder..."),),
        "open_folder",
    )
    assert len(merged["open_folder"]) == 1
    assert merged["folder_ready"] == (), "an unrequested selector was populated"


def test_the_source_scopes_the_merge_to_the_requesting_selector() -> None:
    workflow = _two_selector_workflow()
    service = _FakeService()
    source = CompiledObservationSource(
        service, _Ladder(), plan=workflow.recipe.plan
    )
    source.note_grounding(0, False, "open_folder")

    service.observations.append(
        _Observation(
            _snapshot(selectors=(("open_folder", ()), ("folder_ready", ()))),
            observed_at=1.0,
            ocr_elements=(_ocr("Open Folder..."),),
            tier2_step=0,
        )
    )
    tick = source()
    assert len(tick.selectors["open_folder"]) == 1
    assert tick.selectors["folder_ready"] == ()


def test_a_cancelled_request_leaves_no_selector_to_merge_into() -> None:
    """A stale request must not let a late OCR read answer for a step that
    already grounded."""
    workflow = _two_selector_workflow()
    service = _FakeService()
    source = CompiledObservationSource(
        service, _Ladder(), plan=workflow.recipe.plan
    )
    source.note_grounding(0, False, "open_folder")
    source.note_grounding(0, True, "open_folder")

    service.observations.append(
        _Observation(
            _snapshot(selectors=(("open_folder", ()), ("folder_ready", ()))),
            observed_at=1.0,
            ocr_elements=(_ocr("Open Folder..."),),
            tier2_step=0,
        )
    )
    tick = source()
    assert tick.selectors["open_folder"] == ()
    assert tick.selectors["folder_ready"] == ()


def test_an_ocr_fault_ends_the_run_as_a_failure_not_an_absence() -> None:
    """The fault has to reach the run record with a reason.

    Letting it escape as an exception loses the record entirely; swallowing it
    reports "the control is not there" about a screen that showed it twice.
    """
    from ghostcursor.perception.uia import SelectorAmbiguityFault

    workflow, _catalog = _workflow()

    def _observe():
        raise SelectorAmbiguityFault("ocr selector 'open_folder' matched 2 controls")

    class _Renderer:
        def show(self, grounded, instruction_text):
            pass

        def clear(self):
            pass

        def settle(self):
            pass

    now = [0.0]
    result = execute_compiled_workflow(
        workflow,
        observe=_observe,
        renderer=_Renderer(),
        clock=lambda: now[0],
        sleeper=lambda s: now.__setitem__(0, now[0] + s),
        seconds=5.0,
    )
    assert result.outcome is RunOutcome.FAILED
    assert "matched 2 controls" in result.detail


def test_a_fault_after_the_first_observation_also_ends_the_run() -> None:
    """The tick handler, not the pre-loop one.

    A fault on the very first read is caught while waiting for an observation
    to exist. A fault raised once the state machine is running takes a
    different path, and testing only the first left the second free to swallow
    it and keep re-observing until the deadline -- reporting a timeout where a
    screen showed the control twice.
    """
    from ghostcursor.perception.uia import SelectorAmbiguityFault
    from ghostcursor.reasoning.compiled_tour import TickInput

    workflow, _catalog = _workflow()
    reads = []

    def _observe():
        reads.append(True)
        if len(reads) == 1:
            matched = (
                Element("Open Folder...", "Button", "", (1, 1, 2, 2), ("Button",)),
            )
            return TickInput(
                title="Welcome - Visual Studio Code",
                selectors={"open_folder": matched},
                union=matched,
            )
        raise SelectorAmbiguityFault("ocr selector 'open_folder' matched 3 controls")

    class _Renderer:
        def show(self, grounded, instruction_text):
            pass

        def clear(self):
            pass

        def settle(self):
            pass

    now = [0.0]
    result = execute_compiled_workflow(
        workflow,
        observe=_observe,
        renderer=_Renderer(),
        clock=lambda: now[0],
        sleeper=lambda s: now.__setitem__(0, now[0] + s),
        seconds=5.0,
    )
    assert result.outcome is RunOutcome.FAILED, result
    assert "matched 3 controls" in result.detail
    assert len(reads) > 1, "the fault never reached the running loop"


def test_a_worker_that_dies_mid_run_fails_the_run_with_its_cause() -> None:
    """The tick handler, not the pre-loop one.

    A worker that was never healthy is caught while waiting for the first
    observation. A worker that dies once the tour is running takes a different
    path -- and that is the realistic one: the worker answered, the user began
    acting, and perception stopped. Testing only the first left the second
    free to keep re-observing a corpse until the deadline, reporting a timeout
    where the cause was known.
    """
    from ghostcursor.perception.health import PerceptionUnhealthy
    from ghostcursor.reasoning.compiled_tour import TickInput

    workflow, _catalog = _workflow()
    reads = []

    def _observe():
        reads.append(True)
        if len(reads) == 1:
            matched = (
                Element("Open Folder...", "Button", "", (1, 1, 2, 2), ("Button",)),
            )
            return TickInput(
                title="Welcome - Visual Studio Code",
                selectors={"open_folder": matched},
                union=matched,
            )
        raise PerceptionUnhealthy(
            "perception stopped working (exited); ending the tour"
        )

    class _Renderer:
        def show(self, grounded, instruction_text):
            pass

        def clear(self):
            pass

        def settle(self):
            pass

    now = [0.0]
    result = execute_compiled_workflow(
        workflow,
        observe=_observe,
        renderer=_Renderer(),
        clock=lambda: now[0],
        sleeper=lambda s: now.__setitem__(0, now[0] + s),
        seconds=5.0,
    )
    assert result.outcome is RunOutcome.FAILED, result
    assert "perception stopped working" in result.detail
    assert len(reads) > 1, "the fault never reached the running loop"


def test_the_grace_runs_from_worker_start_not_from_construction() -> None:
    """The candidate harness builds this before its gates and starts it after.

    A slow gate -- a large reload, a human at a dialog -- spends the whole
    grace between the two, and the first read then restarts a worker that has
    never run. Construction time is simply the wrong epoch; only the harness
    can tell them apart, because in production they are the same instant.
    """
    now = [0.0]
    clock = lambda: now[0]
    ladder = _AgeingLadder(clock)
    service = _HealthService()
    health = _real_health(service, ladder, clock)
    source = CompiledObservationSource(service, ladder, health=health, clock=clock)

    # The gates take longer than the whole grace.
    now[0] = health.dead_after_s + 1.0
    source.arm()

    assert source() is None
    assert service.restarts == 0, "a worker was restarted before it had run"

    # And the grace still expires, measured from the start that happened.
    now[0] += health.dead_after_s + 1.0
    source()
    assert service.restarts == 1


def test_an_unarmed_source_never_judges_the_worker() -> None:
    """Nothing has started, so nothing can be stalling."""
    now = [10_000.0]
    clock = lambda: now[0]
    ladder = _AgeingLadder(clock)
    service = _HealthService()
    source = CompiledObservationSource(
        service, ladder, health=_real_health(service, ladder, clock), clock=clock
    )
    assert source() is None
    assert service.restarts == 0


def test_the_composition_arms_the_grace_when_it_starts_the_worker() -> None:
    """`start()` is one event, so no caller can do half of it."""
    workflow, _catalog = _workflow()
    now = [0.0]
    service = compiled_perception_service(
        workflow,
        lambda: now[0],
        plan_runner=compiled_plan_runner(
            workflow,
            walk=lambda hwnd, control_type: [],
            query=lambda hwnd, control_type, name: [],
            read_title=lambda hwnd: "t",
            make_info=PywinautoElementInfo,
        ),
        interval_s=0.01,
    )
    perception = build_compiled_perception(workflow, lambda: now[0], service=service)
    assert perception.source._started_at is None

    now[0] = 500.0
    try:
        observe, on_grounding, stop = perception.start()
    finally:
        stop()
    assert perception.source._started_at == 500.0
    assert observe is perception.source
    assert on_grounding == perception.source.note_grounding


def _function(module: str, name: str):
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    tree = ast.parse((root / module).read_text(encoding="utf-8"))
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


#: Where each compiled entry point WIRES perception, and where it unpacks the
#: seams that start hands back. In production those are the same function; in
#: the harness the wiring returns `perception.start` and `accept_candidate()`
#: calls it after the pre-launch gates, which is the whole point of the split.
WIRING = {
    "ghostcursor/run.py": "_run_compiled_tour",
    "ghostcursor/devtools/candidate_acceptance.py": "_live_acceptance_seams",
}
UNPACKING = {
    "ghostcursor/run.py": "_run_compiled_tour",
    "ghostcursor/devtools/candidate_acceptance.py": "accept_candidate",
}


@pytest.mark.parametrize("module,function", sorted(WIRING.items()))
def test_no_compiled_entry_point_drives_the_worker_directly(module, function) -> None:
    """One lifecycle owner means one start AND one stop.

    `run_tour()` is deliberately out of scope: it is the v1 driver with its
    own inline grace and is not migrated until the cutover, so flagging it
    would assert something untrue about this milestone.
    """
    import ast

    node = _function(module, function)
    # Any lifecycle call on anything ending in `.service` -- `service.stop()`
    # and `perception.service.stop()` alike. Matching only a bare Name missed
    # the second, which is the more natural way to write the bypass once the
    # composition is in scope.
    reached_past = sorted(
        f"{ast.unparse(child.value)}.{child.attr}"
        for child in ast.walk(node)
        if isinstance(child, ast.Attribute)
        and child.attr in {"start", "stop", "restart"}
        and ast.unparse(child.value).split(".")[-1] == "service"
    )
    assert not reached_past, (
        f"{function} drives the worker directly ({reached_past}) instead of "
        "through the composition"
    )
    assert "perception.start" in ast.unparse(node), (
        f"{function} does not use the shared start"
    )


def bound_stop_seam(node) -> str:
    """The name the three start seams were unpacked into, third position."""
    bound = [
        target.elts[2].id
        for statement in ast.walk(node)
        if isinstance(statement, ast.Assign)
        for target in statement.targets
        if isinstance(target, ast.Tuple)
        and len(target.elts) == 3
        and all(isinstance(element, ast.Name) for element in target.elts)
    ]
    assert len(bound) == 1, "the start seams are not unpacked exactly once"
    return bound[0]


def stop_seam_registrations(node, stop_name: str) -> list:
    """Every registration of `stop_name` as a cleanup callback on this function.

    ONE detector, used by the real-source assertion and by the near-miss cases
    alike. Two copies would let a weakening survive twice over: the real source
    happens to satisfy the weakened copy, and the near-miss test exercises the
    untouched one -- so the self-check would prove a duplicate works and say
    nothing about the guard.

    The SHAPE of the cleanup, not a mention of the name. A guard reading
    `if stop_perception is not None` mentions it while stopping nothing;
    `other.callback(stop)` registers on a stack that does not unwind here; and
    `cleanup.callback(print, stop)` registers a print. All three leave the
    worker running.
    """
    stacks = {
        item.optional_vars.id
        for statement in ast.walk(node)
        if isinstance(statement, (ast.With, ast.AsyncWith))
        for item in statement.items
        if isinstance(item.optional_vars, ast.Name)
        and "ExitStack" in ast.unparse(item.context_expr)
    }
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == "callback"
        # The receiver must be the stack this function actually opened...
        and isinstance(child.func.value, ast.Name)
        and child.func.value.id in stacks
        # ...and the seam must be the CALLBACK, not an argument to one.
        and child.args
        and isinstance(child.args[0], ast.Name)
        and child.args[0].id == stop_name
    ]


def stop_seam_calls_in_finally(node, stop_name: str) -> list:
    """Every call of `stop_name` from a `finally` block on this function."""
    return [
        child
        for handler in ast.walk(node)
        if isinstance(handler, ast.Try)
        for statement in handler.finalbody
        for child in ast.walk(statement)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id == stop_name
    ]


@pytest.mark.parametrize("module,function", sorted(UNPACKING.items()))
def test_every_compiled_entry_point_keeps_the_stop_seam(module, function) -> None:
    """The RETURNED stop, neither reached past nor discarded.

    Stopping the service directly leaves the composition believing it is still
    running, so a later start is a no-op and the health grace is never armed
    for the worker that followed. Discarding the seam stops nothing at all.

    Two acceptable shapes, because the two paths genuinely differ: production
    owns its `finally`, while the harness registers on an `ExitStack` so the
    teardown survives a failure in the one beside it.
    """
    node = _function(module, function)
    stop_name = bound_stop_seam(node)
    assert not stop_name.startswith("_"), (
        f"{function} discards the stop seam it was handed ({stop_name})"
    )
    assert stop_seam_registrations(node, stop_name) or stop_seam_calls_in_finally(
        node, stop_name
    ), (
        f"{function} neither registers {stop_name!r} as a cleanup callback nor "
        "calls it from a finally block"
    )


class _StartableService(_HealthService):
    """A service whose start and stop are observable, and can be made to fail."""

    def __init__(self, fail_on_start=None):
        super().__init__()
        self.fail_on_start = fail_on_start
        self.calls = []

    def start(self):
        self.calls.append("start")
        if self.fail_on_start is not None:
            raise self.fail_on_start

    def stop(self):
        self.calls.append("stop")


def _composition(clock, service=None, arm_error=None):
    workflow, _catalog = _workflow()
    service = service or _StartableService()
    ladder = _AgeingLadder(clock)
    source = CompiledObservationSource(
        service, ladder, health=_real_health(service, ladder, clock), clock=clock
    )
    if arm_error is not None:
        def _boom(now=None):
            raise arm_error

        source.arm = _boom
    return service, source, CompiledPerception(service=service, source=source)


def test_a_partial_start_is_torn_down_before_the_failure_propagates() -> None:
    """`PerceptionService.start()` brings up more than one thread.

    It can fail having already started something, and a `start()` that raises
    never returns its stop seam -- so the caller is left with a partly running
    worker it has no handle on. Nothing else in the process will stop it.
    """
    now = [0.0]
    service, _source, perception = _composition(
        lambda: now[0],
        service=_StartableService(RuntimeError("focus thread failed to start")),
    )

    with pytest.raises(RuntimeError, match="focus thread"):
        perception.start()
    assert service.calls == ["start", "stop"], service.calls


def test_a_failure_while_arming_also_tears_the_worker_down() -> None:
    """Arming is part of the transaction, not a step after it."""
    now = [0.0]
    service, _source, perception = _composition(
        lambda: now[0], arm_error=RuntimeError("clock unavailable")
    )

    with pytest.raises(RuntimeError, match="clock"):
        perception.start()
    assert service.calls == ["start", "stop"], service.calls


def test_a_teardown_failure_does_not_replace_the_real_error() -> None:
    """The reported failure must be the one that says what went wrong."""
    now = [0.0]

    class _BadStop(_StartableService):
        def stop(self):
            self.calls.append("stop")
            raise RuntimeError("stop also failed")

    service, _source, perception = _composition(
        lambda: now[0], service=_BadStop(RuntimeError("focus thread failed to start"))
    )
    with pytest.raises(RuntimeError, match="focus thread"):
        perception.start()
    assert service.calls == ["start", "stop"]


def test_a_second_start_does_not_move_the_health_epoch() -> None:
    """The service treats it as a no-op, so the epoch must not move.

    Re-arming would hand a worker that never restarted a fresh budget it did
    not earn -- and a stalled one is exactly the worker most likely to be
    started again by a caller trying to recover.
    """
    now = [0.0]
    service, source, perception = _composition(lambda: now[0])

    perception.start()
    first = source._started_at

    now[0] = 500.0
    seams = perception.start()
    assert source._started_at == first, "the epoch moved for the same worker"
    assert seams == (source, source.note_grounding, perception.stop)


def test_a_second_start_is_harmless_and_returns_the_same_seams() -> None:
    now = [0.0]
    service, source, perception = _composition(lambda: now[0])
    first = perception.start()
    second = perception.start()
    assert first == second
    assert service.calls == ["start"], "the second start reached the service"


def test_starting_again_after_a_stop_is_a_new_worker_era() -> None:
    """A genuine restart DOES get a fresh grace, because it is a fresh worker."""
    now = [0.0]
    service, source, perception = _composition(lambda: now[0])

    perception.start()
    perception.stop()
    now[0] = 500.0
    perception.start()

    assert source._started_at == 500.0
    assert service.calls == ["start", "stop", "start"]


def test_a_failed_start_leaves_the_composition_startable() -> None:
    """A rolled-back transaction leaves no half-set state behind."""
    now = [0.0]
    service = _StartableService(RuntimeError("focus thread failed to start"))
    _svc, source, perception = _composition(lambda: now[0], service=service)

    with pytest.raises(RuntimeError):
        perception.start()
    assert source._started_at is None, "a failed start armed the grace anyway"

    service.fail_on_start = None
    now[0] = 42.0
    perception.start()
    assert source._started_at == 42.0


def test_stopping_before_any_start_is_harmless() -> None:
    now = [0.0]
    service, _source, perception = _composition(lambda: now[0])
    perception.stop()
    assert service.calls == ["stop"]


def test_the_composition_state_agrees_with_its_service_after_a_stop() -> None:
    """Stopping through the seam keeps one lifecycle owner honest.

    Reaching past it to `service.stop()` stops the worker and leaves the
    composition believing it is still running -- so the next start is treated
    as a no-op and the health grace is never armed for the worker that
    actually followed. The composition's state and its service's must not be
    able to disagree.
    """
    now = [0.0]
    service, source, perception = _composition(lambda: now[0])

    _observe, _hook, stop = perception.start()
    assert perception._running.get("started") is True

    stop()
    assert perception._running.get("started") is False
    assert service.calls == ["start", "stop"]

    now[0] = 500.0
    perception.start()
    assert source._started_at == 500.0, (
        "the worker that followed the stop never got its own grace"
    )


def test_the_returned_stop_is_the_compositions_own() -> None:
    """The seam is not a bare handle to the service."""
    now = [0.0]
    _service, _source, perception = _composition(lambda: now[0])
    _observe, _hook, stop = perception.start()
    assert stop == perception.stop


@pytest.mark.parametrize(
    "line,accepted",
    [
        ("cleanup.callback(stop_perception)", True),
        # A different object's stack does not unwind in this function.
        ("other.callback(stop_perception)", False),
        # Registers a `print`, with the seam as its argument.
        ("cleanup.callback(print, stop_perception)", False),
        ("print(stop_perception)", False),
        ("if stop_perception is not None:\n            pass", False),
        # `push` takes an EXIT callback -- called with exception details,
        # not with no arguments -- and `enter_context` expects a context
        # manager, so neither registers this teardown even though both are
        # ExitStack methods on the right receiver.
        ("cleanup.push(stop_perception)", False),
        ("cleanup.enter_context(stop_perception)", False),
    ],
)
def test_the_cleanup_check_accepts_only_the_real_registration(line, accepted) -> None:
    """Mutation-verify the detector ITSELF (D018).

    Runs `stop_seam_registrations()` -- the same function the real-source
    assertion runs -- over synthetic near-misses. A copy of its logic here
    would verify the copy: weakening the real one would then pass both,
    because production happens to satisfy the weakened form.
    """
    source = (
        "def accept_candidate(graph, workflow, *, start_perception, make_renderer):\n"
        "    with contextlib.ExitStack() as cleanup:\n"
        "        observe, on_grounding, stop_perception = start_perception()\n"
        f"        {line}\n"
        "        renderer, dispose = make_renderer()\n"
        "        cleanup.callback(dispose)\n"
        "        result = execute_compiled_workflow(workflow)\n"
        "    return result\n"
    )
    node = next(
        n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef)
    )
    stop_name = bound_stop_seam(node)
    assert bool(stop_seam_registrations(node, stop_name)) is accepted, line


def test_a_callback_on_a_non_exitstack_binding_is_not_a_registration() -> None:
    """The receiver must be an ExitStack, not merely something named `cleanup`.

    Deriving the stack from the `with` binding is what makes the receiver
    check mean anything. Without it, any context manager bound to any name
    would qualify -- and `.callback` on something that is not an ExitStack
    registers no teardown at all.
    """
    source = (
        "def accept_candidate(graph, workflow, *, start_perception, make_renderer):\n"
        "    with open_report() as cleanup:\n"
        "        observe, on_grounding, stop_perception = start_perception()\n"
        "        cleanup.callback(stop_perception)\n"
        "        result = execute_compiled_workflow(workflow)\n"
        "    return result\n"
    )
    node = next(
        n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef)
    )
    stop_name = bound_stop_seam(node)
    assert stop_seam_registrations(node, stop_name) == []


def test_an_exitstack_bound_under_any_name_still_counts() -> None:
    """The check is on the OBJECT, not on the identifier.

    Renaming the variable is not a weakening, so a check keyed on the literal
    name `cleanup` would fail an honest refactor while still passing the real
    bypasses above.
    """
    source = (
        "def accept_candidate(graph, workflow, *, start_perception, make_renderer):\n"
        "    with contextlib.ExitStack() as teardown:\n"
        "        observe, on_grounding, stop_perception = start_perception()\n"
        "        teardown.callback(stop_perception)\n"
        "        result = execute_compiled_workflow(workflow)\n"
        "    return result\n"
    )
    node = next(
        n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef)
    )
    stop_name = bound_stop_seam(node)
    assert stop_seam_registrations(node, stop_name)
