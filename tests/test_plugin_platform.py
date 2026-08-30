from __future__ import annotations

import hashlib
import json

from ghostcursor.packs.compile import compile_matcher, compile_planner
from ghostcursor.plugins import platform
from ghostcursor.plugins.bundle import verify_bundle
from ghostcursor.plugins.store import PluginStore
from ghostcursor.reasoning.planner import (
    CandidateSource,
    IntentCandidate,
    authorize_intent,
)


def test_every_bundled_plugin_matches_the_pinned_index_and_release_key():
    index = json.loads((platform._BUNDLED_ROOT / "index.json").read_text())
    trusted = platform.trusted_release_keys()
    for entry in index["bundles"]:
        path = platform._BUNDLED_ROOT / entry["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["bundle_sha256"]
        bundle = verify_bundle(
            path,
            trusted_keys=trusted,
            core_version=platform.CORE_VERSION,
        )
        assert bundle.plugin_id == entry["plugin_id"]
        assert bundle.version == entry["version"]
        assert bundle.manifest_sha256 == entry["manifest_sha256"]


def test_bootstrap_happens_once_and_never_reenables_an_operator_choice(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(platform.ENV_PLUGIN_ROOT, str(tmp_path / "plugins"))
    store = platform.production_store()
    assert set(store.load_active_catalog().plugins) == {
        "ghostcursor.synthetic",
        "ghostcursor.vscode",
    }
    store.disable("ghostcursor.vscode")

    restarted = platform.production_store()

    assert tuple(restarted.load_active_catalog().plugins) == ("ghostcursor.synthetic",)


def test_an_initialized_store_with_no_plugins_has_zero_executable_knowledge(tmp_path):
    store = PluginStore(
        tmp_path / "plugins",
        trusted_keys=platform.trusted_release_keys(),
        core_version=platform.CORE_VERSION,
    )
    # Creating the empty indexes is an explicit initialized-empty state, so
    # first-run defaults cannot be confused with an operator disabling all.
    assert store.list_installed() == ()
    catalog = store.load_verified_catalog()

    assert compile_planner(catalog) == ()
    assert compile_matcher(catalog).classify("open a fictional editor command").intent_id is None
    authorization = authorize_intent(
        catalog,
        "open a fictional editor command",
        IntentCandidate(
            CandidateSource.MODEL,
            "FICTIONAL_EDITOR_COMMAND",
            0.99,
            "screen text looked command-like",
        ),
    )
    assert authorization.authorized is None


def test_no_plugin_means_no_plan_target_or_renderer_from_either_classifier(
    monkeypatch, tmp_path
):
    from ghostcursor.plugins import platform as platform_module
    from ghostcursor.reasoning import planner
    from ghostcursor.reasoning.planner import IntentDecision

    store = PluginStore(
        tmp_path / "empty",
        trusted_keys=platform.trusted_release_keys(),
        core_version=platform.CORE_VERSION,
    )
    store.list_installed()
    catalog = store.load_verified_catalog()
    monkeypatch.setattr(platform_module, "load_runtime_catalog", lambda: catalog)
    monkeypatch.setattr(
        "ghostcursor.packs.workflow.live_windows_for",
        lambda _pack: (_ for _ in ()).throw(AssertionError("target grounded")),
    )

    deterministic = planner.plan_compiled_goal("open a folder", use_model=False)
    monkeypatch.setattr(
        planner,
        "infer_intent",
        lambda *_args, **_kwargs: type(
            "Inference",
            (),
            {"decision": IntentDecision("FICTIONAL_EDITOR_COMMAND", 0.99, "invented")},
        )(),
    )
    modeled = planner.plan_compiled_goal("open a folder")

    assert deterministic.plan is None
    assert modeled.plan is None


def test_disabling_a_plugin_invalidates_the_running_authority_epoch(
    monkeypatch, tmp_path
):
    from types import SimpleNamespace

    monkeypatch.setenv(platform.ENV_PLUGIN_ROOT, str(tmp_path / "plugins"))
    store = platform.production_store()
    workflow = SimpleNamespace(index_sha256=store.current_active_index_sha256())

    assert platform.runtime_authority_status(workflow) is None
    store.disable("ghostcursor.vscode")
    assert (
        platform.runtime_authority_status(workflow)
        == "active plugin authority changed during the tour"
    )
