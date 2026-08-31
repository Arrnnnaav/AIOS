from __future__ import annotations

import inspect
from dataclasses import dataclass, replace
from types import MappingProxyType, SimpleNamespace

from ghostcursor.task_graph import (
    CapabilityRegistry,
    CapabilitySpec,
    TaskEdge,
    TaskGraph,
    TaskNode,
    ParameterKind,
    ParameterSpec,
)
from ghostcursor.session import GuidanceValue
from ghostcursor.task_runtime import (
    TaskRunCode,
    TaskRunPhase,
    _authorize_capability,
    _execute_task_graph,
    execute_task_graph,
)


SHA = "a" * 64
PLUGIN = "ghostcursor.presentation"


def _registry() -> CapabilityRegistry:
    return CapabilityRegistry(
        plugin_id=PLUGIN,
        plugin_version="1.0.0",
        catalog_sha256=SHA,
        catalog_generation=4,
        capabilities=MappingProxyType(
            {
                "CREATE_DECK": CapabilitySpec(
                    "CREATE_DECK",
                    "CREATE_DECK",
                    "create a presentation",
                    postconditions=("deck.exists",),
                    parameters=MappingProxyType(
                        {
                            "deck_title": ParameterSpec(
                                ParameterKind.STRING,
                                required=False,
                            )
                        }
                    ),
                ),
                "ADD_SLIDE": CapabilitySpec(
                    "ADD_SLIDE",
                    "ADD_SLIDE",
                    "add a slide",
                    preconditions=("deck.exists",),
                    postconditions=("slide.exists",),
                    safe_to_repeat=True,
                ),
            }
        ),
    )


def _graph() -> TaskGraph:
    return TaskGraph(
        PLUGIN,
        "1.0.0",
        (
            TaskNode(
                "create",
                PLUGIN,
                "CREATE_DECK",
                MappingProxyType({"deck_title": "GhostCursor"}),
            ),
            TaskNode("slide", PLUGIN, "ADD_SLIDE"),
        ),
        (TaskEdge("create", "slide"),),
    )


@dataclass(frozen=True)
class _Authorization:
    authorized: object | None
    explanation: str = ""


def _run(graph=None, *, contexts=None, authorize=None, bind=None, run=None):
    registry = _registry()
    contexts = contexts or [SimpleNamespace(catalog=object(), registries={PLUGIN: registry})]
    index = 0

    def load_context():
        nonlocal index
        value = contexts[min(index, len(contexts) - 1)]
        index += 1
        return value

    return _execute_task_graph(
        graph or _graph(),
        initial_facts=(),
        target_title_re="PowerPoint",
        target_hwnd=42,
        seconds_per_node=5.0,
        load_context=load_context,
        authorize=authorize or (lambda _catalog, capability: _Authorization(capability.intent_id)),
        bind=bind or (lambda token, goal, **kwargs: (token, goal, kwargs)),
        run=run or (lambda _workflow, **_kwargs: 0),
    )


def test_whole_graph_validation_rejects_before_any_node_effect_runs():
    calls = []
    graph = replace(_graph(), edges=(TaskEdge("create", "slide"), TaskEdge("slide", "create")))

    result = _run(
        graph,
        authorize=lambda *_: calls.append("authorize"),
        bind=lambda *_args, **_kwargs: calls.append("bind"),
        run=lambda *_args, **_kwargs: calls.append("run"),
    )

    assert result.phase is TaskRunPhase.VALIDATION
    assert result.code is TaskRunCode.VALIDATION_REJECTED
    assert calls == []


def test_every_node_reloads_authorizes_binds_and_runs_in_validated_order():
    events = []

    def authorize(_catalog, capability):
        events.append(("authorize", capability.capability_id, capability.authorization_goal))
        return _Authorization(capability.intent_id)

    def bind(token, goal, **kwargs):
        events.append(("bind", token, goal, kwargs))
        return goal

    def run(workflow, **kwargs):
        events.append(("run", workflow, kwargs))
        return 0

    result = _run(authorize=authorize, bind=bind, run=run)

    assert result.completed
    assert result.completed_node_ids == ("create", "slide")
    assert [event[0] for event in events] == [
        "authorize", "bind", "run", "authorize", "bind", "run"
    ]
    assert events[0][2] == "create a presentation"
    assert events[3][2] == "add a slide"
    assert events[1][3] == {"target_title_re": "PowerPoint", "target_hwnd": 42}
    assert events[2][2] == {
        "seconds": 5.0,
        "guidance_values": (GuidanceValue("deck_title", "GhostCursor"),),
    }
    assert events[5][2] == {"seconds": 5.0, "guidance_values": ()}


def test_first_node_captures_one_hwnd_for_every_remaining_node():
    bound = []

    def bind(_token, _goal, **kwargs):
        bound.append(kwargs["target_hwnd"])
        return SimpleNamespace(
            target=SimpleNamespace(hwnd=kwargs["target_hwnd"] or 404)
        )

    result = _run(bind=bind)

    assert result.completed
    # The operator-provided handle is already fixed in _run.
    assert bound == [42, 42]

    bound.clear()
    result = _execute_task_graph(
        _graph(),
        initial_facts=(),
        target_title_re=None,
        target_hwnd=None,
        seconds_per_node=5.0,
        load_context=lambda: SimpleNamespace(
            catalog=object(), registries={PLUGIN: _registry()}
        ),
        authorize=lambda _catalog, capability: _Authorization(capability.intent_id),
        bind=bind,
        run=lambda *_args, **_kwargs: 0,
    )

    assert result.completed
    assert bound == [None, 404]


def test_a_binder_cannot_return_a_different_hwnd_from_graph_narrowing():
    result = _run(
        bind=lambda *_args, **_kwargs: SimpleNamespace(
            target=SimpleNamespace(hwnd=999)
        )
    )

    assert result.code is TaskRunCode.NODE_FAILED
    assert "changed the graph target HWND" in result.detail


def test_catalog_or_registry_change_refuses_the_remaining_suffix_before_authorization():
    registry = _registry()
    changed = replace(registry, catalog_generation=5)
    contexts = [
        SimpleNamespace(catalog=object(), registries={PLUGIN: registry}),
        SimpleNamespace(catalog=object(), registries={PLUGIN: registry}),
        SimpleNamespace(catalog=object(), registries={PLUGIN: changed}),
    ]
    authorized = []

    result = _run(
        contexts=contexts,
        authorize=lambda _catalog, capability: (
            authorized.append(capability.capability_id) or _Authorization(object())
        ),
    )

    assert result.code is TaskRunCode.AUTHORITY_CHANGED
    assert result.failed_node_id == "slide"
    assert result.completed_node_ids == ("create",)
    assert authorized == ["CREATE_DECK"]


def test_authorization_refusal_and_runtime_failure_are_execution_results():
    refused = _run(authorize=lambda *_: _Authorization(None, "not authorized"))
    failed = _run(run=lambda *_args, **_kwargs: 7)

    assert refused.phase is TaskRunPhase.EXECUTION
    assert refused.code is TaskRunCode.AUTHORIZATION_REFUSED
    assert refused.failed_node_id == "create"
    assert failed.phase is TaskRunPhase.EXECUTION
    assert failed.code is TaskRunCode.NODE_FAILED
    assert failed.failed_node_id == "create"


def test_authority_load_and_bind_failures_are_classified_by_phase():
    def unavailable():
        raise RuntimeError("store is unavailable")

    before_start = _execute_task_graph(
        _graph(),
        initial_facts=(),
        target_title_re=None,
        target_hwnd=None,
        seconds_per_node=5.0,
        load_context=unavailable,
        authorize=lambda *_: _Authorization(object()),
        bind=lambda *_args, **_kwargs: object(),
        run=lambda *_args, **_kwargs: 0,
    )

    class WorkflowUnavailable(RuntimeError):
        pass

    during_bind = _run(
        bind=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            WorkflowUnavailable("catalog changed at bind")
        )
    )

    assert before_start.phase is TaskRunPhase.VALIDATION
    assert before_start.code is TaskRunCode.AUTHORITY_UNAVAILABLE
    assert during_bind.phase is TaskRunPhase.EXECUTION
    assert during_bind.code is TaskRunCode.AUTHORITY_CHANGED


def test_public_graph_executor_exposes_no_authority_injection_parameter():
    assert set(inspect.signature(execute_task_graph).parameters) == {
        "graph",
        "initial_facts",
        "target_title_re",
        "target_hwnd",
        "seconds_per_node",
    }


def test_zero_and_ambiguous_targets_remain_distinct_graph_outcomes():
    class TargetNotRunning(Exception):
        pass

    class TargetChoiceRequired(Exception):
        def __init__(self):
            self.candidates = (SimpleNamespace(hwnd=10), SimpleNamespace(hwnd=20))

    missing = _run(
        bind=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            TargetNotRunning("PowerPoint is not running")
        )
    )
    ambiguous = _run(
        bind=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            TargetChoiceRequired()
        )
    )

    assert missing.code is TaskRunCode.TARGET_NOT_RUNNING
    assert missing.target_candidates == ()
    assert ambiguous.code is TaskRunCode.TARGET_CHOICE_REQUIRED
    assert [candidate.hwnd for candidate in ambiguous.target_candidates] == [10, 20]


def test_capability_authorization_uses_its_signed_exact_goal(monkeypatch):
    captured = []

    def authorize(catalog, goal, candidate):
        captured.append((catalog, goal, candidate))
        return object()

    monkeypatch.setattr("ghostcursor.reasoning.planner.authorize_intent", authorize)
    capability = _registry().capabilities["ADD_SLIDE"]
    catalog = object()

    _authorize_capability(catalog, capability)

    assert captured[0][0] is catalog
    assert captured[0][1] == "add a slide"
    assert captured[0][2].intent_id == "ADD_SLIDE"
    assert captured[0][2].explanation == "signed capability exact phrase"
