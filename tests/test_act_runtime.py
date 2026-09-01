from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from ghostcursor.act_runtime import (
    ActControls,
    ActRunCode,
    ActTarget,
    _execute_approved_graph,
    approve_action_graph,
)
from ghostcursor.action import (
    ActionEdge,
    ActionGraph,
    ActionNode,
    ActionParameterSpec,
    ActionRisk,
    ActionValueKind,
    OperationRegistry,
    OperationSpec,
    validate_action_graph,
)


PLUGIN = "ghostcursor.powerpoint"
VERSION = "1.0.0"
ADAPTER = "a" * 64
MANIFEST = "c" * 64
ACTIVE = "d" * 64


def _registry(*, risk=ActionRisk.LOW):
    operations = {
        "powerpoint.create": OperationSpec(
            "powerpoint.create",
            risk,
            MappingProxyType({}),
            postconditions=("presentation.created",),
            timeout_s=2.0,
        ),
        "powerpoint.slide": OperationSpec(
            "powerpoint.slide",
            risk,
            MappingProxyType({"slide_id": ActionParameterSpec(ActionValueKind.STRING)}),
            preconditions=("presentation.created",),
            postconditions=("slide.created",),
            effect_key_fields=("slide_id",),
            timeout_s=2.0,
        ),
    }
    return OperationRegistry(
        PLUGIN,
        VERSION,
        ADAPTER,
        "b" * 64,
        MappingProxyType(operations),
    )


def _validated(registry=None):
    registry = registry or _registry()
    graph = ActionGraph(
        PLUGIN,
        VERSION,
        ADAPTER,
        (
            ActionNode("create", "powerpoint.create"),
            ActionNode(
                "slide-one",
                "powerpoint.slide",
                MappingProxyType({"slide_id": "s1"}),
            ),
        ),
        (ActionEdge("create", "slide-one"),),
    )
    return validate_action_graph(graph, registry)


def _adapter(path: Path, *, marker: Path | None = None):
    marker_line = ""
    if marker is not None:
        marker_line = f"Path({str(marker)!r}).write_text('started', encoding='utf-8')\n"
    path.write_text(
        "from pathlib import Path\n"
        "import json, sys\n"
        + marker_line
        + "hello = json.loads(sys.stdin.readline())\n"
        + "print(json.dumps({**hello, 'type': 'ready'}, sort_keys=True), flush=True)\n"
        + "for line in sys.stdin:\n"
        + "    value = json.loads(line)\n"
        + "    if value['type'] == 'stop': break\n"
        + "    if value['type'] == 'preflight':\n"
        + "        print(json.dumps({'detail': 'valid', 'outcome': 'accepted', "
        + "'request_id': value['request_id'], 'session_nonce': value['session_nonce'], "
        + "'type': 'preflight_result', 'validation_sha256': value['validation_sha256']}, sort_keys=True), flush=True)\n"
        + "        continue\n"
        + "    print(json.dumps({'data': {}, 'detail': 'done', 'facts': [], "
        + "'outcome': 'completed', 'request_id': value['request_id'], "
        + "'session_nonce': value['session_nonce'], 'type': 'result'}, sort_keys=True), flush=True)\n",
        encoding="utf-8",
        newline="\n",
    )


def _descriptor(tmp_path: Path, *, marker: Path | None = None):
    entrypoint = tmp_path / "adapter.py"
    _adapter(entrypoint, marker=marker)
    return SimpleNamespace(
        plugin_id=PLUGIN,
        plugin_version=VERSION,
        manifest_sha256=MANIFEST,
        payload_root=tmp_path,
        entrypoint=entrypoint,
        adapter_sha256=ADAPTER,
    )


def _target():
    return ActTarget(101, 202, "POWERPNT.EXE", "16.0.1")


def _approval(tmp_path, validated, registry, **changes):
    values = {
        "manifest_sha256": MANIFEST,
        "active_index_sha256": ACTIVE,
        "catalog_generation": 7,
        "target": _target(),
        "output_path": tmp_path / "owned" / "deck.pptx",
        "unattended": True,
        "owned_output_root": tmp_path / "owned",
        "now": 100.0,
    }
    values.update(changes)
    return approve_action_graph(validated, registry, **values)


def _authority():
    return ACTIVE, 7, VERSION, MANIFEST, ADAPTER


def test_unattended_approval_requires_low_risk_and_an_owned_output_root(tmp_path):
    registry = _registry(risk=ActionRisk.NORMAL)
    validated = _validated(registry)
    with pytest.raises(ValueError, match="low-risk"):
        _approval(tmp_path, validated, registry)

    registry = _registry()
    validated = _validated(registry)
    with pytest.raises(ValueError, match="owned output root"):
        approve_action_graph(
            validated,
            registry,
            manifest_sha256=MANIFEST,
            active_index_sha256=ACTIVE,
            catalog_generation=7,
            target=_target(),
            output_path=tmp_path / "deck.pptx",
            unattended=True,
        )
    with pytest.raises(ValueError, match="escapes"):
        _approval(
            tmp_path,
            validated,
            registry,
            output_path=tmp_path / "outside.pptx",
        )


def test_a_forged_or_stale_approval_never_starts_the_adapter(tmp_path):
    registry = _registry()
    validated = _validated(registry)
    approval = _approval(tmp_path, validated, registry)
    marker = tmp_path / "adapter-started"
    forged = replace(approval, output_path=str(tmp_path / "forged.pptx"))

    result = _execute_approved_graph(
        validated,
        registry,
        forged,
        descriptor=_descriptor(tmp_path, marker=marker),
        current_authority=_authority,
        revalidate_target=lambda _: None,
        verify=lambda *_: True,
        controls=ActControls(),
        wall_clock=lambda: 101.0,
    )

    assert result.code is ActRunCode.APPROVAL_STALE
    assert not marker.exists()


def test_authority_and_target_are_checked_before_adapter_process_creation(tmp_path):
    registry = _registry()
    validated = _validated(registry)
    approval = _approval(tmp_path, validated, registry)
    marker = tmp_path / "adapter-started"
    descriptor = _descriptor(tmp_path, marker=marker)

    stale = _execute_approved_graph(
        validated,
        registry,
        approval,
        descriptor=descriptor,
        current_authority=lambda: ("0" * 64, 7, VERSION, MANIFEST, ADAPTER),
        revalidate_target=lambda _: None,
        verify=lambda *_: True,
        controls=ActControls(),
        wall_clock=lambda: 101.0,
    )
    assert stale.code is ActRunCode.AUTHORITY_CHANGED
    assert not marker.exists()

    drifted = _execute_approved_graph(
        validated,
        registry,
        approval,
        descriptor=descriptor,
        current_authority=_authority,
        revalidate_target=lambda _: (_ for _ in ()).throw(
            RuntimeError("HWND recycled")
        ),
        verify=lambda *_: True,
        controls=ActControls(),
        wall_clock=lambda: 101.0,
    )
    assert drifted.code is ActRunCode.TARGET_CHANGED
    assert not marker.exists()


def test_every_node_is_reauthorized_and_independently_verified(tmp_path):
    registry = _registry()
    validated = _validated(registry)
    approval = _approval(tmp_path, validated, registry)
    target_reads = 0
    verified = []

    def target(_):
        nonlocal target_reads
        target_reads += 1

    result = _execute_approved_graph(
        validated,
        registry,
        approval,
        descriptor=_descriptor(tmp_path),
        current_authority=_authority,
        revalidate_target=target,
        verify=lambda node, *_: not verified.append(node.node_id),
        controls=ActControls(),
        wall_clock=lambda: 101.0,
    )

    assert result.code is ActRunCode.COMPLETED
    assert result.completed_node_ids == ("create", "slide-one")
    assert verified == ["create", "slide-one"]
    assert target_reads == 3  # one preflight plus one check per action


def test_target_drift_between_actions_stops_before_the_next_effect(tmp_path):
    registry = _registry()
    validated = _validated(registry)
    approval = _approval(tmp_path, validated, registry)
    target_reads = 0

    def target(_):
        nonlocal target_reads
        target_reads += 1
        if target_reads == 3:
            raise RuntimeError("PowerPoint window changed")

    result = _execute_approved_graph(
        validated,
        registry,
        approval,
        descriptor=_descriptor(tmp_path),
        current_authority=_authority,
        revalidate_target=target,
        verify=lambda *_: True,
        controls=ActControls(),
        wall_clock=lambda: 101.0,
    )

    assert result.code is ActRunCode.TARGET_CHANGED
    assert result.completed_node_ids == ("create",)
    assert result.failed_node_id == "slide-one"
