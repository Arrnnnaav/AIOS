"""One canonical intent gate, with non-interchangeable Teach and Act authority."""

from __future__ import annotations

import hashlib
import inspect
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
from ghostcursor.plugins.store import (
    AdapterDescriptor,
    CompositionContext,
    PluginStore,
)
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


def _issuing_store(tmp_path, context):
    store = PluginStore(
        tmp_path / "authority-store",
        trusted_keys={},
        core_version="0.1.0",
    )
    # Unit tests below exercise downstream provenance combinations with an
    # already-issued context.  A separate test proves an exact-type context
    # that this store did not issue is refused.
    store._remember_composition_context(context)
    return store


def _authorize_action(context, tmp_path):
    store = _issuing_store(tmp_path, context)
    return authorize_intent(
        context.catalog,
        "add a slide in powerpoint",
        _candidate(context),
        action_context=context,
        action_store=store,
    )


def test_unadopted_recipe_stays_unavailable_while_signed_action_plan_authorizes(
    tmp_path,
):
    context = _context(tmp_path)
    candidate = _candidate(context)

    teach = authorize_intent(context.catalog, "add a slide in powerpoint", candidate)
    act = _authorize_action(context, tmp_path)

    assert teach.status is PlanStatus.KNOWN_INTENT_RECIPE_UNAVAILABLE
    assert teach.authorized is None
    assert act.status is PlanStatus.SUPPORTED
    assert isinstance(act.authorized, AuthorizedActionIntent)
    assert act.authorized.plan_id == "add-slide-uia-v1"
    assert act.authorized.plan_sha256 == context.adapters[PLUGIN_ID].plans[
        "add-slide-uia-v1"
    ].plan_sha256
    assert act.authorized.plugin_manifest_sha256 == MANIFEST
    assert act.authorized.adapter_sha256 == context.adapters[PLUGIN_ID].adapter_sha256
    assert act.authorized.catalog_sha256 == context.catalog.index_sha256
    assert act.authorized.catalog_generation == context.catalog.generation
    assert act.authorized.activation_sha256 == context.catalog.packs[
        "powerpoint"
    ].activation_sha256
    assert act.authorized.intent_sha256 == context.catalog.packs[
        "powerpoint"
    ].intents["ADD_SLIDE"].intent.sha256


def test_act_authority_refuses_a_context_that_does_not_own_the_catalog(tmp_path):
    context = _context(tmp_path)
    other_catalog = replace(context.catalog)
    foreign = replace(context, catalog=other_catalog)
    store = _issuing_store(tmp_path, foreign)

    result = authorize_intent(
        context.catalog,
        "add a slide in powerpoint",
        _candidate(context),
        action_context=foreign,
        action_store=store,
    )

    assert result.status is PlanStatus.KNOWN_INTENT_ACTION_PLAN_UNAVAILABLE
    assert result.authorized is None


def test_act_authority_refuses_a_lookalike_instead_of_the_context_type(tmp_path):
    context = _context(tmp_path)
    store = _issuing_store(tmp_path, context)
    lookalike = SimpleNamespace(
        catalog=context.catalog,
        adapters=context.adapters,
    )

    result = authorize_intent(
        context.catalog,
        "add a slide in powerpoint",
        _candidate(context),
        action_context=lookalike,
        action_store=store,
    )

    assert result.status is PlanStatus.KNOWN_INTENT_ACTION_PLAN_UNAVAILABLE
    assert result.authorized is None


def test_act_authority_refuses_an_exact_context_not_issued_by_the_store(tmp_path):
    context = _context(tmp_path)
    store = PluginStore(
        tmp_path / "unrelated-store",
        trusted_keys={},
        core_version="0.1.0",
    )

    result = authorize_intent(
        context.catalog,
        "add a slide in powerpoint",
        _candidate(context),
        action_context=context,
        action_store=store,
    )

    assert result.status is PlanStatus.KNOWN_INTENT_ACTION_PLAN_UNAVAILABLE
    assert result.authorized is None


@pytest.mark.parametrize("missing", ("store", "context"))
def test_act_authority_requires_the_store_and_its_issued_context_together(
    tmp_path, missing
):
    context = _context(tmp_path)
    store = _issuing_store(tmp_path, context)

    result = authorize_intent(
        context.catalog,
        "add a slide in powerpoint",
        _candidate(context),
        action_context=None if missing == "context" else context,
        action_store=None if missing == "store" else store,
    )

    assert result.status is PlanStatus.KNOWN_INTENT_ACTION_PLAN_UNAVAILABLE
    assert result.authorized is None


def test_context_issued_by_one_real_store_is_not_owned_by_another(tmp_path):
    context = _context(tmp_path)
    issuer = _issuing_store(tmp_path / "issuer", context)
    other = PluginStore(
        tmp_path / "other",
        trusted_keys={},
        core_version="0.1.0",
    )

    assert issuer.owns_composition_context(context)
    assert not other.owns_composition_context(context)


def test_act_authority_refuses_a_store_lookalike_even_if_it_claims_ownership(
    tmp_path,
):
    context = _context(tmp_path)
    lookalike = SimpleNamespace(owns_composition_context=lambda _context: True)

    result = authorize_intent(
        context.catalog,
        "add a slide in powerpoint",
        _candidate(context),
        action_context=context,
        action_store=lookalike,
    )

    assert result.status is PlanStatus.KNOWN_INTENT_ACTION_PLAN_UNAVAILABLE
    assert result.authorized is None


def test_production_prepare_does_not_accept_a_caller_supplied_store():
    from ghostcursor.act_cli import prepare_act_goal

    assert "store" not in inspect.signature(prepare_act_goal).parameters


@pytest.mark.parametrize(
    ("descriptor_field", "changed_value"),
    (
        ("plugin_id", "ghostcursor.other"),
        ("plugin_version", "9.0.0"),
        ("manifest_sha256", "9" * 64),
    ),
)
def test_act_authority_refuses_descriptor_provenance_drift(
    tmp_path, descriptor_field, changed_value
):
    context = _context(tmp_path)
    descriptor = replace(
        context.adapters[PLUGIN_ID],
        **{descriptor_field: changed_value},
    )
    changed = replace(
        context,
        adapters=MappingProxyType({PLUGIN_ID: descriptor}),
    )

    result = _authorize_action(changed, tmp_path)

    assert result.status is PlanStatus.KNOWN_INTENT_ACTION_PLAN_UNAVAILABLE
    assert result.authorized is None


@pytest.mark.parametrize(
    ("field", "changed_value"),
    (
        ("plugin_id", "ghostcursor.other"),
        ("plugin_version", "9.0.0"),
    ),
)
def test_act_authority_refuses_coordinated_descriptor_and_plan_drift(
    tmp_path, field, changed_value
):
    """Agreement between two changed plugin artifacts is not pack provenance."""

    context = _context(tmp_path)
    descriptor = context.adapters[PLUGIN_ID]
    changed_plans = MappingProxyType({
        plan_id: replace(plan, **{field: changed_value})
        for plan_id, plan in descriptor.plans.items()
    })
    changed_descriptor = replace(
        descriptor,
        **{field: changed_value},
        plans=changed_plans,
    )
    changed = replace(
        context,
        adapters=MappingProxyType({PLUGIN_ID: changed_descriptor}),
    )

    result = _authorize_action(changed, tmp_path)

    assert result.status is PlanStatus.KNOWN_INTENT_ACTION_PLAN_UNAVAILABLE
    assert result.authorized is None


@pytest.mark.parametrize(
    ("plan_field", "changed_value"),
    (
        ("intent_id", "FICTIONAL_INTENT"),
        ("plugin_id", "ghostcursor.other"),
        ("plugin_version", "9.0.0"),
        ("adapter_sha256", "8" * 64),
    ),
)
def test_act_authority_refuses_plan_provenance_drift(
    tmp_path, plan_field, changed_value
):
    context = _context(tmp_path)
    descriptor = context.adapters[PLUGIN_ID]
    plan = descriptor.plans["add-slide-uia-v1"]
    changed_plan = replace(plan, **{plan_field: changed_value})
    changed_descriptor = replace(
        descriptor,
        plans=MappingProxyType({changed_plan.plan_id: changed_plan}),
    )
    changed = replace(
        context,
        adapters=MappingProxyType({PLUGIN_ID: changed_descriptor}),
    )

    result = _authorize_action(changed, tmp_path)

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

    result = _authorize_action(changed, tmp_path)

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
        action_store=_issuing_store(tmp_path, context),
    )

    assert result.status is PlanStatus.INVALID_MODEL_OUTPUT
    assert result.authorized is None


def test_signed_plan_authority_cannot_be_consumed_as_a_teach_recipe(
    tmp_path, monkeypatch
):
    context = _context(tmp_path)
    result = _authorize_action(context, tmp_path)
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
    store = _issuing_store(tmp_path, context)
    monkeypatch.setattr(store, "load_composition_context", lambda: context)
    monkeypatch.setattr("ghostcursor.act_cli.production_store", lambda: store)
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
    proposal = prepare_act_goal(
        "add a slide in powerpoint",
        output_path=None,
        target_hwnd=101,
    )

    assert proposal.intent_id == "ADD_SLIDE"
    assert proposal.plugin_id == PLUGIN_ID
    assert proposal.output_path is None
    assert len(proposal.validated.ordered_nodes) == 1
    assert proposal.validated.ordered_nodes[0].operation_id == "powerpoint.new_slide_uia"


@pytest.mark.parametrize(
    ("token_field", "changed_value"),
    (
        ("plan_sha256", "1" * 64),
        ("adapter_sha256", "2" * 64),
        ("plugin_manifest_sha256", "3" * 64),
    ),
)
def test_prepare_act_goal_refuses_authority_drift_before_target_resolution(
    tmp_path, monkeypatch, token_field, changed_value
):
    from ghostcursor import act_cli

    context = _context(tmp_path)
    authorized = _authorize_action(context, tmp_path)
    changed = replace(
        authorized,
        authorized=replace(
            authorized.authorized,
            **{token_field: changed_value},
        ),
    )
    monkeypatch.setattr(act_cli, "authorize_intent", lambda *_a, **_k: changed)
    monkeypatch.setattr(
        act_cli,
        "live_windows_for",
        lambda _pack: (_ for _ in ()).throw(AssertionError("target resolved")),
    )
    store = _issuing_store(tmp_path, context)
    monkeypatch.setattr(store, "load_composition_context", lambda: context)
    monkeypatch.setattr(act_cli, "production_store", lambda: store)

    with pytest.raises(RuntimeError, match="authority changed"):
        act_cli.prepare_act_goal(
            "add a slide in powerpoint",
            output_path=None,
            target_hwnd=101,
        )
