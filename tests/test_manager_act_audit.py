"""Fixed-schema evidence emitted by the real manager path."""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
from types import SimpleNamespace

import pytest

from ghostcursor.manager import (
    ManagerActAuditRecord,
    _manager_act_audit_line,
    _proposal_audit_facts,
    _run_result_audit_facts,
    _runtime_event_audit_facts,
    launch_manager,
)


def _proposal(
    *,
    validation: str = "1" * 64,
    target_hwnd: int = 100,
    output_path: str | None = None,
):
    return SimpleNamespace(
        intent_id="ADD_SLIDE",
        plugin_id="ghostcursor.powerpoint",
        active_index_sha256="2" * 64,
        catalog_generation=7,
        output_path=output_path,
        target=SimpleNamespace(
            executable="POWERPNT.EXE",
            executable_version="16.0",
            hwnd=target_hwnd,
            pid=200,
        ),
        validated=SimpleNamespace(
            plugin_version="1.0.0",
            graph_sha256="3" * 64,
            validation_sha256=validation,
        ),
        descriptor=SimpleNamespace(
            manifest_sha256="4" * 64,
            adapter_sha256="5" * 64,
            uia_adapter_sha256="a" * 64,
            live_verifier_sha256="b" * 64,
        ),
    )


def test_proposal_audit_binding_changes_with_goal_or_validated_graph():
    first = _proposal_audit_facts("Add one slide", _proposal())
    changed_goal = _proposal_audit_facts("Add two slides", _proposal())
    changed_graph = _proposal_audit_facts(
        "Add one slide", _proposal(validation="6" * 64)
    )
    changed_target = _proposal_audit_facts(
        "Add one slide", _proposal(target_hwnd=101)
    )
    changed_output = _proposal_audit_facts(
        "Add one slide", _proposal(output_path="another-deck.pptx")
    )

    assert first["proposal_sha256"] != changed_goal["proposal_sha256"]
    assert first["proposal_sha256"] != changed_graph["proposal_sha256"]
    assert first["proposal_sha256"] != changed_target["proposal_sha256"]
    assert first["proposal_sha256"] != changed_output["proposal_sha256"]
    assert first["plugin_id"] == "ghostcursor.powerpoint"
    assert first["validation_sha256"] == "1" * 64
    assert first["catalog_generation"] == 7
    assert first["target_sha256"] not in {None, "POWERPNT.EXE", "100", "200"}
    assert first["uia_adapter_sha256"] == "a" * 64
    assert first["live_verifier_sha256"] == "b" * 64


def test_audit_json_is_fixed_schema_and_excludes_private_live_geometry():
    record = ManagerActAuditRecord(
        schema_version=1,
        sequence=7,
        type="act_runtime_event",
        at_ns=123,
        proposal_sha256="1" * 64,
        node_id="n001",
        operation_id="powerpoint.new_slide_uia",
        ordinal=1,
        total=1,
        code="action_completed",
        detail_sha256="2" * 64,
    )

    value = json.loads(_manager_act_audit_line(record))

    assert value["sequence"] == 7
    assert value["code"] == "action_completed"
    assert set(value) == set(ManagerActAuditRecord.__dataclass_fields__)
    assert not ({"goal", "region", "rectangle", "geometry", "screenshot"} & set(value))


def test_audit_serializer_rejects_open_or_lookalike_values():
    with pytest.raises(TypeError, match="fixed-schema"):
        _manager_act_audit_line(SimpleNamespace(type="act_runtime_event"))


def test_runtime_event_audit_uses_executor_ordinals_and_hashes_detail_only():
    event = SimpleNamespace(
        type="action_completed",
        node_id="n001",
        operation_id="powerpoint.new_slide_uia",
        ordinal=1,
        total=1,
        detail="the declared postcondition was independently observed",
        region=(100, 200, 300, 400),
    )

    facts = _runtime_event_audit_facts("7" * 64, event)

    assert facts["proposal_sha256"] == "7" * 64
    assert facts["code"] == "action_completed"
    assert facts["ordinal"] == 1
    assert facts["total"] == 1
    assert facts["detail_sha256"] != event.detail
    assert "region" not in facts


def test_terminal_result_audit_binds_validation_and_completion_truth():
    result = SimpleNamespace(
        validated=SimpleNamespace(
            graph_sha256="8" * 64,
            validation_sha256="9" * 64,
        ),
        code=SimpleNamespace(value="completed"),
        completed=True,
        completed_node_ids=("n001",),
        detail="all actions verified",
        output_path="private-output-path.pptx",
    )

    facts = _run_result_audit_facts("7" * 64, result)

    assert facts["proposal_sha256"] == "7" * 64
    assert facts["graph_sha256"] == "8" * 64
    assert facts["validation_sha256"] == "9" * 64
    assert facts["code"] == "completed"
    assert facts["completed"] is True
    assert facts["completed_nodes"] == 1
    assert "output_path" not in facts


def test_failed_worker_result_is_recorded_without_exception_text():
    error = RuntimeError("secret local path")

    facts = _run_result_audit_facts("7" * 64, error)

    assert facts["code"] == "RuntimeError"
    assert facts["completed"] is False
    assert facts["detail_sha256"] != str(error)


def test_production_manager_loop_wires_every_load_bearing_audit_transition():
    tree = ast.parse(textwrap.dedent(inspect.getsource(launch_manager)))
    record_kinds = set()
    helper_calls = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "_record_act_audit":
            if node.args and isinstance(node.args[0], ast.Constant):
                record_kinds.add(node.args[0].value)
        if isinstance(node.func, ast.Name):
            helper_calls.add(node.func.id)

    assert {
        "execution_request_dequeued",
        "act_worker_started",
        "act_runtime_event",
        "act_run_result",
    } <= record_kinds
    assert {"_runtime_event_audit_facts", "_run_result_audit_facts"} <= helper_calls
