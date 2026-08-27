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

import threading

import pytest

from ghostcursor.perception.compiled import (
    CompiledObservationSource,
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
    def __init__(self):
        self.observations = 0

    def observed(self):
        self.observations += 1

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


def test_worker_health_is_checked_on_every_read() -> None:
    """A dead worker leaves its last slot in place.

    A slot that never ages looks exactly like a screen that never changes, so
    without this the tour waits out its whole timeout against a corpse.
    """
    checks = []

    class _Health:
        def check(self):
            checks.append(True)

    service = _FakeService([_Observation(_snapshot(), 1.0)])
    source = CompiledObservationSource(service, _Ladder(), health=_Health())
    source()
    source()
    assert len(checks) == 2


def test_an_empty_slot_still_checks_health_and_returns_none() -> None:
    checks = []

    class _Health:
        def check(self):
            checks.append(True)

    source = CompiledObservationSource(_FakeService(), _Ladder(), health=_Health())
    assert source() is None
    assert checks == [True]


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
    _service, source = build_compiled_perception(
        workflow, __import__("time").monotonic, service=service
    )

    service.start()
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
            on_grounding=source.note_grounding,
        )
    finally:
        service.stop()

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
    _service, source = build_compiled_perception(
        workflow, __import__("time").monotonic, service=service
    )
    service.start()
    try:
        deadline = __import__("time").monotonic() + 2.0
        while not walk_threads and __import__("time").monotonic() < deadline:
            source()
            __import__("time").sleep(0.01)
    finally:
        service.stop()

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
