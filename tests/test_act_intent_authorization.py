"""One canonical intent gate, with non-interchangeable Teach and Act authority."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from ghostcursor.action import load_operation_registry
from ghostcursor.action_plans import load_action_plan_templates
from ghostcursor.packs.activation import VerifiedCatalog, load_catalog
from ghostcursor.packs.authority import AuthorizedActionIntent
from ghostcursor.packs.compile import compile_matcher
from ghostcursor.packs.workflow import (
    AppSnapshot,
    WindowCandidate,
    WorkflowUnavailable,
    bind_workflow,
)
from ghostcursor.plugins.store import AdapterDescriptor, CompositionContext
from ghostcursor.reasoning.planner import (
    CandidateSource,
    IntentCandidate,
    PlanStatus,
    authorize_intent,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "plugins" / "sources" / "powerpoint"
PAYLOAD = SOURCE / "payload" / "ghostcursor"
PLUGIN_ID = "ghostcursor.powerpoint"
VERSION = "1.0.0"
MANIFEST = "a" * 64


def _context(tmp_path) -> CompositionContext:
    project = tmp_path / "candidate"
    packs = project / "ghostcursor" / "packs"
    packs.mkdir(parents=True)
    shutil.copy2(SOURCE / "index.json", packs / "index.json")
    shutil.copytree(PAYLOAD / "packs" / "powerpoint", packs / "powerpoint")
    raw = load_catalog(project)
    pack = replace(
        raw.packs["powerpoint"],
        plugin_id=PLUGIN_ID,
        plugin_version=VERSION,
        plugin_manifest_sha256=MANIFEST,
    )
    catalog = VerifiedCatalog(
        root_valid=True,
        packs=MappingProxyType({"powerpoint": pack}),
        diagnostics=raw.diagnostics,
        index_sha256="b" * 64,
        generation=7,
    )

    adapter = PAYLOAD / "adapter" / "powerpoint_adapter.py"
    adapter_sha = hashlib.sha256(adapter.read_bytes()).hexdigest()
    registry = load_operation_registry(
        (PAYLOAD / "operations.json").read_bytes(),
        plugin_id=PLUGIN_ID,
        plugin_version=VERSION,
        adapter_sha256=adapter_sha,
    )
    files = {
        "ghostcursor/action-plans.json": (PAYLOAD / "action-plans.json").read_bytes(),
        **{
            f"ghostcursor/action-plans/{path.name}": path.read_bytes()
            for path in (PAYLOAD / "action-plans").glob("*.json")
        },
    }
    plans = load_action_plan_templates(
        files["ghostcursor/action-plans.json"],
        files,
        plugin_id=PLUGIN_ID,
        plugin_version=VERSION,
        adapter_sha256=adapter_sha,
    )
    descriptor = AdapterDescriptor(
        plugin_id=PLUGIN_ID,
        plugin_version=VERSION,
        manifest_sha256=MANIFEST,
        payload_root=PAYLOAD,
        entrypoint=adapter,
        adapter_sha256=adapter_sha,
        verifier=PAYLOAD / "adapter" / "powerpoint_verifier.py",
        verifier_sha256="c" * 64,
        registry=registry,
        plans=MappingProxyType(plans),
        uia_entrypoint=PAYLOAD / "adapter" / "uia_adapter.py",
        live_verifier=PAYLOAD / "adapter" / "powerpoint_live_verifier.py",
        live_verifier_sha256="d" * 64,
        uia_adapter_sha256=hashlib.sha256(
            (PAYLOAD / "adapter" / "uia_adapter.py").read_bytes()
        ).hexdigest(),
    )
    return CompositionContext(
        catalog,
        MappingProxyType({}),
        MappingProxyType({PLUGIN_ID: descriptor}),
    )


def _candidate(context, goal="add a slide in powerpoint"):
    match = compile_matcher(context.catalog).classify(goal)
    return IntentCandidate(
        CandidateSource.DETERMINISTIC,
        match.intent_id,
        match.confidence,
        match.reason,
    )


def test_unadopted_recipe_stays_unavailable_while_signed_action_plan_authorizes(
    tmp_path,
):
    context = _context(tmp_path)
    candidate = _candidate(context)

    teach = authorize_intent(context.catalog, "add a slide in powerpoint", candidate)
    act = authorize_intent(
        context.catalog,
        "add a slide in powerpoint",
        candidate,
        action_context=context,
    )

    assert teach.status is PlanStatus.KNOWN_INTENT_RECIPE_UNAVAILABLE
    assert teach.authorized is None
    assert act.status is PlanStatus.SUPPORTED
    assert isinstance(act.authorized, AuthorizedActionIntent)
    assert act.authorized.plan_id == "add-slide-uia-v1"
    assert act.authorized.plan_sha256 == context.adapters[PLUGIN_ID].plans[
        "add-slide-uia-v1"
    ].plan_sha256


def test_act_authority_refuses_a_context_that_does_not_own_the_catalog(tmp_path):
    context = _context(tmp_path)
    other_catalog = replace(context.catalog)
    foreign = replace(context, catalog=other_catalog)

    result = authorize_intent(
        context.catalog,
        "add a slide in powerpoint",
        _candidate(context),
        action_context=foreign,
    )

    assert result.status is PlanStatus.KNOWN_INTENT_ACTION_PLAN_UNAVAILABLE
    assert result.authorized is None


def test_act_authority_refuses_two_signed_plans_for_one_intent(tmp_path):
    context = _context(tmp_path)
    descriptor = context.adapters[PLUGIN_ID]
    plan = descriptor.plans["add-slide-uia-v1"]
    duplicate = replace(plan, plan_id="add-slide-uia-copy")
    ambiguous = replace(
        descriptor,
        plans=MappingProxyType({
            plan.plan_id: plan,
            duplicate.plan_id: duplicate,
        }),
    )
    changed = replace(
        context,
        adapters=MappingProxyType({PLUGIN_ID: ambiguous}),
    )

    result = authorize_intent(
        changed.catalog,
        "add a slide in powerpoint",
        _candidate(changed),
        action_context=changed,
    )

    assert result.status is PlanStatus.KNOWN_INTENT_ACTION_PLAN_UNAVAILABLE
    assert result.authorized is None


def test_fictional_action_intent_never_receives_signed_plan_authority(tmp_path):
    context = _context(tmp_path)

    result = authorize_intent(
        context.catalog,
        "perform the fictional moon slide command",
        IntentCandidate(
            CandidateSource.MODEL,
            "MOON_SLIDE",
            0.99,
            "looks plausible",
        ),
        action_context=context,
    )

    assert result.status is PlanStatus.INVALID_MODEL_OUTPUT
    assert result.authorized is None


def test_signed_plan_authority_cannot_be_consumed_as_a_teach_recipe(
    tmp_path, monkeypatch
):
    context = _context(tmp_path)
    result = authorize_intent(
        context.catalog,
        "add a slide in powerpoint",
        _candidate(context),
        action_context=context,
    )
    monkeypatch.setattr(
        "ghostcursor.plugins.platform.load_runtime_catalog",
        lambda: (_ for _ in ()).throw(AssertionError("catalog loaded")),
    )

    with pytest.raises(WorkflowUnavailable, match="adopted-recipe"):
        bind_workflow(result.authorized, "add a slide in powerpoint")


def test_prepare_act_goal_uses_the_recipe_free_signed_plan_authority(
    tmp_path, monkeypatch
):
    from ghostcursor.act_cli import prepare_act_goal

    context = _context(tmp_path)
    monkeypatch.setattr(
        "ghostcursor.act_cli.live_windows_for",
        lambda _pack: [
            WindowCandidate(
                101,
                "Presentation1 - PowerPoint",
                AppSnapshot("powerpnt.exe", "16.0.20326.20132", 4242),
            )
        ],
    )
    store = SimpleNamespace(load_composition_context=lambda: context)

    proposal = prepare_act_goal(
        "add a slide in powerpoint",
        output_path=None,
        target_hwnd=101,
        store=store,
    )

    assert proposal.intent_id == "ADD_SLIDE"
    assert proposal.plugin_id == PLUGIN_ID
    assert proposal.output_path is None
    assert len(proposal.validated.ordered_nodes) == 1
    assert proposal.validated.ordered_nodes[0].operation_id == "powerpoint.new_slide_uia"
