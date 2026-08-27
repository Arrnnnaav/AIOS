from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from ghostcursor.packs.activation import (
    ApplicationIdentity,
    DiagnosticCode,
    IntentAvailability,
    load_catalog,
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_json(root: Path, relative: str, value: object) -> dict[str, str]:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    path.write_bytes(raw)
    return {"path": relative, "sha256": _sha(raw)}


def _write_authority(root: Path, relative: str, value: object) -> None:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _pack(
    pack_id: str = "vscode", *, planner_only: bool = False, display="Visual Studio Code"
) -> dict:
    if planner_only:
        return {
            "schema_version": 2,
            "pack_id": pack_id,
            "pack_kind": "planner_only",
            "display_name": display,
            "executable_names": [],
            "title_patterns": [],
            "tier2_capture": "disabled",
            "version_identity": None,
            "aliases": {},
        }
    return {
        "schema_version": 2,
        "pack_id": pack_id,
        "pack_kind": "application",
        "display_name": display,
        "executable_names": ["code.exe"],
        "title_patterns": [".*Visual Studio Code.*"],
        "tier2_capture": "executable_bounded",
        "version_identity": {"kind": "executable_version"},
        "aliases": {"vscode_names": ["vs code", "vscode", "visual studio code"]},
    }


def _intent(intent_id: str, *, phrase: str | None = None) -> dict:
    return {
        "schema_version": 2,
        "intent_id": intent_id,
        "canonical_target": "Visual Studio Code",
        "rules": [] if phrase is None else [{"tier": "exact", "phrases": [phrase]}],
    }


def _recipe(intent_id: str) -> dict:
    return {
        "schema_version": 2,
        "intent_id": intent_id,
        "step_key_namespace": intent_id.casefold().replace("_", " "),
        "selectors": {
            "action": {
                "strategy": "provider_exact",
                "control_type": "Button",
                "names": ["Action"],
                "normalise": "none",
                "cardinality": "exactly_one",
                "result_limit": 8,
            },
            "result": {
                "strategy": "provider_exact",
                "control_type": "Text",
                "names": ["Done"],
                "normalise": "none",
                "cardinality": "at_least_one",
                "result_limit": 8,
            },
        },
        "context_selectors": [],
        "steps": [
            {
                "user_action": "click",
                "target_selector": "action",
                "target_descriptor": {
                    "claimed": {
                        "name": "Action",
                        "name_synonyms": [],
                        "ocr_text": None,
                        "visual_description": None,
                    },
                    "confirmed": [],
                },
                "instruction_text": "Click Action.",
                "verification_rule": {
                    "kind": "element_appears",
                    "selector": "result",
                    "args": {"fail_after_timeout": True},
                    "timeout_s": 30.0,
                },
                "risk": "normal",
                "preconditions": [],
                "provenance": {
                    "source_urls": [],
                    "source_tier": "hand-authored",
                    "model": "none",
                    "prompt_version": "none",
                    "created_at": "2026-08-27",
                },
            }
        ],
    }


def _evidence(project: Path, name: str, body: str = "accepted\n") -> dict[str, str]:
    relative = f"docs/evidence/{name}.md"
    path = project.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = body.encode()
    path.write_bytes(raw)
    return {"path": relative, "sha256": _sha(raw)}


def _adoption(
    recipe_ref: dict[str, str],
    pack_ref: dict[str, str],
    intent_ref: dict[str, str],
    evidence_ref: dict[str, str],
    *,
    identity: str = "1.134.0",
    supersedes_id: str | None = None,
    supersedes_recipe: str | None = None,
    adopted_at: str = "2026-08-27T00:00:00Z",
) -> dict:
    # Copy every reference. Sharing one dict with the activation binding would
    # mutate the current binding and the acceptance record together, so a test
    # that intends "accepted digest differs from the bound artifact" would
    # silently exercise "bound artifact digest mismatch" instead.
    return {
        "recipe": dict(recipe_ref),
        "accepted_pack": dict(pack_ref),
        "accepted_intent": dict(intent_ref),
        "accepted_application_identity": {
            "kind": "executable_version",
            "value": identity,
        },
        "evidence": dict(evidence_ref),
        "adopted_at": adopted_at,
        "reviewer_id": "repository-owner",
        "review_commit": "a" * 40,
        "supersedes_adoption_id": supersedes_id,
        "supersedes_recipe_sha256": supersedes_recipe,
    }


def _make_pack(
    project: Path,
    *,
    directory: str = "vscode",
    pack_id: str = "vscode",
    intents: tuple[str, ...] = ("OPEN_FOLDER",),
    active: bool = True,
    planner_only: bool = False,
    phrases: dict[str, str] | None = None,
) -> dict:
    pack_root = project / "ghostcursor" / "packs" / directory
    pack_ref = _write_json(
        pack_root,
        f"pack/{pack_id}.json",
        _pack(pack_id, planner_only=planner_only, display=pack_id),
    )
    entries: dict[str, dict] = {}
    intent_refs: dict[str, dict[str, str]] = {}
    recipe_refs: dict[str, dict[str, str]] = {}
    for intent_id in intents:
        slug = intent_id.casefold()
        intent_ref = _write_json(
            pack_root,
            f"intents/{slug}.json",
            _intent(intent_id, phrase=(phrases or {}).get(intent_id)),
        )
        intent_refs[intent_id] = intent_ref
        if active and not planner_only:
            recipe_ref = _write_json(
                pack_root, f"recipes/{slug}.json", _recipe(intent_id)
            )
            recipe_refs[intent_id] = recipe_ref
            evidence_ref = _evidence(project, f"{pack_id}-{slug}")
            adoption_id = f"accept-{slug}-1"
            entries[intent_id] = {
                "intent": intent_ref,
                "active_adoption_id": adoption_id,
                "adoptions": {
                    adoption_id: _adoption(
                        recipe_ref, pack_ref, intent_ref, evidence_ref
                    )
                },
            }
        else:
            entries[intent_id] = {
                "intent": intent_ref,
                "active_adoption_id": None,
                "adoptions": {},
            }
    activation = {
        "schema_version": 2,
        "activation_generation": 1,
        "pack": pack_ref,
        "intents": entries,
    }
    _write_authority(pack_root, "activation.json", activation)
    return {
        "directory": directory,
        "root": pack_root,
        "pack_ref": pack_ref,
        "intent_refs": intent_refs,
        "recipe_refs": recipe_refs,
        "activation": activation,
    }


def _write_index(project: Path, packs: list[dict[str, str]]) -> None:
    _write_authority(
        project / "ghostcursor" / "packs",
        "index.json",
        {"schema_version": 2, "packs": packs},
    )


def _one_pack(project: Path, **kwargs) -> dict:
    built = _make_pack(project, **kwargs)
    _write_index(
        project,
        [{"pack_id": kwargs.get("pack_id", "vscode"), "path": built["directory"]}],
    )
    return built


@pytest.mark.parametrize(
    "mode", ["missing", "invalid", "duplicate-id", "duplicate-path"]
)
def test_root_index_failures_load_no_packs(tmp_path, mode):
    packs_root = tmp_path / "ghostcursor" / "packs"
    packs_root.mkdir(parents=True)
    if mode == "invalid":
        (packs_root / "index.json").write_text("not json", encoding="utf-8")
    elif mode == "duplicate-id":
        _write_index(
            tmp_path,
            [
                {"pack_id": "vscode", "path": "vscode"},
                {"pack_id": "vscode", "path": "other"},
            ],
        )
    elif mode == "duplicate-path":
        _write_index(
            tmp_path,
            [
                {"pack_id": "vscode", "path": "vscode"},
                {"pack_id": "other", "path": "VSCODE"},
            ],
        )

    catalog = load_catalog(tmp_path)
    assert not catalog.root_valid
    assert catalog.packs == {}
    assert any(
        item.code is DiagnosticCode.ROOT_INDEX_INVALID for item in catalog.diagnostics
    )


@pytest.mark.parametrize("duplicate", ["intent", "phrase"])
def test_global_registry_ambiguity_loads_no_packs(tmp_path, duplicate):
    first_intent = "OPEN_FOLDER"
    second_intent = "OPEN_FOLDER" if duplicate == "intent" else "OPEN_TERMINAL"
    phrase = "open a folder in vs code"
    one = _make_pack(
        tmp_path,
        directory="one",
        pack_id="one",
        intents=(first_intent,),
        active=False,
        phrases={first_intent: phrase},
    )
    two = _make_pack(
        tmp_path,
        directory="two",
        pack_id="two",
        intents=(second_intent,),
        active=False,
        phrases={second_intent: phrase},
    )
    _write_index(
        tmp_path,
        [
            {"pack_id": "one", "path": one["directory"]},
            {"pack_id": "two", "path": two["directory"]},
        ],
    )

    catalog = load_catalog(tmp_path)
    assert not catalog.root_valid
    assert catalog.packs == {}
    expected = (
        DiagnosticCode.DUPLICATE_INTENT
        if duplicate == "intent"
        else DiagnosticCode.DUPLICATE_EXACT_PHRASE
    )
    assert any(item.code is expected for item in catalog.diagnostics)


def test_invalid_activation_or_pack_binding_fails_only_that_pack(tmp_path):
    good = _make_pack(tmp_path, directory="good", pack_id="good", active=False)
    bad = _make_pack(tmp_path, directory="bad", pack_id="bad", active=False)
    (bad["root"] / "activation.json").write_text("{}", encoding="utf-8")
    _write_index(
        tmp_path,
        [
            {"pack_id": "good", "path": "good"},
            {"pack_id": "bad", "path": "bad"},
        ],
    )

    catalog = load_catalog(tmp_path)
    assert catalog.root_valid
    assert set(catalog.packs) == {"good"}
    assert any(item.code is DiagnosticCode.PACK_INVALID for item in catalog.diagnostics)

    bad["activation"] = _make_pack(
        tmp_path, directory="bad", pack_id="bad", active=False
    )["activation"]
    bad["activation"]["pack"]["sha256"] = "0" * 64
    _write_authority(bad["root"], "activation.json", bad["activation"])
    catalog = load_catalog(tmp_path)
    assert set(catalog.packs) == {"good"}


def test_planner_only_intents_are_visible_but_never_executable(tmp_path):
    built = _one_pack(
        tmp_path,
        directory="common",
        pack_id="common",
        intents=("CREATE_DOCUMENT", "OPEN_SETTINGS"),
        active=False,
        planner_only=True,
    )
    catalog = load_catalog(tmp_path)
    pack = catalog.packs["common"]
    assert set(pack.intents) == {"CREATE_DOCUMENT", "OPEN_SETTINGS"}
    assert all(
        intent.availability is IntentAvailability.KNOWN_INTENT_RECIPE_UNAVAILABLE
        for intent in pack.intents.values()
    )

    entry = built["activation"]["intents"]["CREATE_DOCUMENT"]
    entry["adoptions"]["forbidden"] = {}
    _write_authority(built["root"], "activation.json", built["activation"])
    catalog = load_catalog(tmp_path)
    assert "common" not in catalog.packs
    assert any(item.code is DiagnosticCode.PACK_INVALID for item in catalog.diagnostics)


def test_invalid_intent_is_excluded_with_a_diagnostic(tmp_path):
    built = _one_pack(tmp_path, active=False)
    built["activation"]["intents"]["OPEN_FOLDER"]["intent"]["sha256"] = "0" * 64
    _write_authority(built["root"], "activation.json", built["activation"])

    catalog = load_catalog(tmp_path)
    assert catalog.packs["vscode"].intents == {}
    assert any(
        item.code is DiagnosticCode.INTENT_INVALID for item in catalog.diagnostics
    )


@pytest.mark.parametrize(
    "failure", ["missing-active", "recipe", "pack", "intent", "evidence", "identity"]
)
def test_invalid_active_adoption_is_known_but_unavailable(tmp_path, failure):
    built = _one_pack(tmp_path)
    entry = built["activation"]["intents"]["OPEN_FOLDER"]
    adoption = next(iter(entry["adoptions"].values()))
    if failure == "missing-active":
        entry["active_adoption_id"] = "missing"
    elif failure == "identity":
        adoption["accepted_application_identity"]["kind"] = "content_sha256"
        adoption["accepted_application_identity"]["value"] = "b" * 64
    else:
        field = {
            "recipe": "recipe",
            "pack": "accepted_pack",
            "intent": "accepted_intent",
            "evidence": "evidence",
        }[failure]
        adoption[field]["sha256"] = "0" * 64
    _write_authority(built["root"], "activation.json", built["activation"])

    catalog = load_catalog(tmp_path)
    intent = catalog.packs["vscode"].intents["OPEN_FOLDER"]
    assert intent.availability is IntentAvailability.KNOWN_INTENT_RECIPE_UNAVAILABLE
    assert intent.active_adoption is None
    assert any(
        item.code is DiagnosticCode.ACTIVE_ADOPTION_INVALID
        for item in catalog.diagnostics
    )


def test_invalid_inactive_history_does_not_disable_valid_active_record(tmp_path):
    built = _one_pack(tmp_path)
    entry = built["activation"]["intents"]["OPEN_FOLDER"]
    active_id = entry["active_adoption_id"]
    bad = dict(entry["adoptions"][active_id])
    bad["recipe"] = {"path": "recipes/missing.json", "sha256": "0" * 64}
    bad["supersedes_adoption_id"] = active_id
    bad["supersedes_recipe_sha256"] = built["recipe_refs"]["OPEN_FOLDER"]["sha256"]
    entry["adoptions"]["broken-history"] = bad
    _write_authority(built["root"], "activation.json", built["activation"])

    catalog = load_catalog(tmp_path)
    intent = catalog.packs["vscode"].intents["OPEN_FOLDER"]
    assert intent.availability is IntentAvailability.ACTIVE
    assert intent.active_adoption.adoption_id == active_id
    assert "broken-history" not in intent.adoptions
    assert any(
        item.code is DiagnosticCode.INACTIVE_ADOPTION_INVALID
        for item in catalog.diagnostics
    )


def test_adoption_lifecycle_preserves_history_and_exact_identity_eligibility(tmp_path):
    built = _one_pack(tmp_path)
    entry = built["activation"]["intents"]["OPEN_FOLDER"]
    first_id = entry["active_adoption_id"]
    first = entry["adoptions"][first_id]
    second_id = "accept-open_folder-2"
    second_evidence = _evidence(tmp_path, "vscode-open_folder-v2", "accepted again\n")
    entry["adoptions"][second_id] = _adoption(
        built["recipe_refs"]["OPEN_FOLDER"],
        built["pack_ref"],
        built["intent_refs"]["OPEN_FOLDER"],
        second_evidence,
        identity="1.135.0",
        supersedes_id=first_id,
        supersedes_recipe=first["recipe"]["sha256"],
        adopted_at="2026-08-27T01:00:00Z",
    )
    entry["active_adoption_id"] = second_id
    built["activation"]["activation_generation"] = 2
    _write_authority(built["root"], "activation.json", built["activation"])

    catalog = load_catalog(tmp_path)
    intent = catalog.packs["vscode"].intents["OPEN_FOLDER"]
    assert set(intent.adoptions) == {first_id, second_id}
    assert intent.active_adoption.adoption_id == second_id
    assert intent.active_adoption.accepts_identity(
        ApplicationIdentity("executable_version", "1.135.0")
    )
    assert not intent.active_adoption.accepts_identity(
        ApplicationIdentity("executable_version", "1.134.0")
    )
    assert (
        intent.adoption_for_identity(
            first_id, ApplicationIdentity("executable_version", "1.134.0")
        ).adoption_id
        == first_id
    )
    assert (
        intent.adoption_for_identity(
            first_id, ApplicationIdentity("executable_version", "1.135.0")
        )
        is None
    )

    entry["active_adoption_id"] = None
    built["activation"]["activation_generation"] = 3
    _write_authority(built["root"], "activation.json", built["activation"])
    withdrawn = load_catalog(tmp_path)
    withdrawn_intent = withdrawn.packs["vscode"].intents["OPEN_FOLDER"]
    assert withdrawn_intent.active_adoption is None
    assert set(withdrawn_intent.adoptions) == {first_id, second_id}


@pytest.mark.parametrize("fault", ["missing", "digest", "self", "cycle"])
def test_predecessor_graph_faults_are_not_rollback_eligible(tmp_path, fault):
    built = _one_pack(tmp_path)
    entry = built["activation"]["intents"]["OPEN_FOLDER"]
    first_id = entry["active_adoption_id"]
    first = entry["adoptions"][first_id]
    second_id = "accept-open_folder-2"
    second = _adoption(
        built["recipe_refs"]["OPEN_FOLDER"],
        built["pack_ref"],
        built["intent_refs"]["OPEN_FOLDER"],
        _evidence(tmp_path, f"predecessor-{fault}"),
        supersedes_id=first_id,
        supersedes_recipe=first["recipe"]["sha256"],
        adopted_at="2026-08-27T01:00:00Z",
    )
    entry["adoptions"][second_id] = second
    if fault == "missing":
        second["supersedes_adoption_id"] = "does-not-exist"
    elif fault == "digest":
        second["supersedes_recipe_sha256"] = "0" * 64
    elif fault == "self":
        second["supersedes_adoption_id"] = second_id
    else:
        first["supersedes_adoption_id"] = second_id
        first["supersedes_recipe_sha256"] = second["recipe"]["sha256"]
    _write_authority(built["root"], "activation.json", built["activation"])

    catalog = load_catalog(tmp_path)
    intent = catalog.packs["vscode"].intents["OPEN_FOLDER"]
    assert second_id not in intent.adoptions
    assert (
        intent.adoption_for_identity(
            second_id, ApplicationIdentity("executable_version", "1.134.0")
        )
        is None
    )


def test_pack_and_intent_digest_changes_have_the_agreed_invalidation_scope(tmp_path):
    built = _one_pack(tmp_path, intents=("OPEN_FOLDER", "OPEN_TERMINAL"))
    new_pack_ref = _write_json(
        built["root"],
        "pack/vscode-new.json",
        _pack(display="VS Code changed"),
    )
    built["activation"]["pack"] = new_pack_ref
    built["activation"]["activation_generation"] = 2
    _write_authority(built["root"], "activation.json", built["activation"])
    catalog = load_catalog(tmp_path)
    assert all(
        intent.availability is IntentAvailability.KNOWN_INTENT_RECIPE_UNAVAILABLE
        for intent in catalog.packs["vscode"].intents.values()
    )

    built = _one_pack(tmp_path, intents=("OPEN_FOLDER", "OPEN_TERMINAL"))
    new_intent_ref = _write_json(
        built["root"],
        "intents/open_folder-new.json",
        _intent("OPEN_FOLDER", phrase="open a directory in vs code"),
    )
    built["activation"]["intents"]["OPEN_FOLDER"]["intent"] = new_intent_ref
    built["activation"]["activation_generation"] = 2
    _write_authority(built["root"], "activation.json", built["activation"])
    catalog = load_catalog(tmp_path)
    assert (
        catalog.packs["vscode"].intents["OPEN_FOLDER"].availability
        is IntentAvailability.KNOWN_INTENT_RECIPE_UNAVAILABLE
    )
    assert (
        catalog.packs["vscode"].intents["OPEN_TERMINAL"].availability
        is IntentAvailability.ACTIVE
    )


def test_activation_generation_is_checked_against_previous_catalog_not_used_as_authority(
    tmp_path,
):
    built = _one_pack(tmp_path, active=False)
    first = load_catalog(tmp_path)
    assert first.packs["vscode"].activation_generation == 1

    built["activation"]["activation_generation"] = 3
    _write_authority(built["root"], "activation.json", built["activation"])
    rejected = load_catalog(tmp_path, previous=first)
    assert "vscode" not in rejected.packs
    assert any(
        item.code is DiagnosticCode.GENERATION_INVALID for item in rejected.diagnostics
    )

    built["activation"]["activation_generation"] = 2
    _write_authority(built["root"], "activation.json", built["activation"])
    accepted = load_catalog(tmp_path, previous=first)
    assert accepted.packs["vscode"].activation_generation == 2


def test_preserved_history_survives_a_pack_update(tmp_path):
    """A superseded record describes what was accepted then, not what is bound now."""

    built = _one_pack(tmp_path)
    entry = built["activation"]["intents"]["OPEN_FOLDER"]
    first_id = entry["active_adoption_id"]
    new_pack_ref = _write_json(
        built["root"], "pack/vscode-v2.json", _pack(display="vscode v2")
    )
    second_id = "accept-open_folder-2"
    entry["adoptions"][second_id] = _adoption(
        built["recipe_refs"]["OPEN_FOLDER"],
        new_pack_ref,
        built["intent_refs"]["OPEN_FOLDER"],
        _evidence(tmp_path, "vscode-open_folder-repack"),
        identity="1.135.0",
        supersedes_id=first_id,
        supersedes_recipe=entry["adoptions"][first_id]["recipe"]["sha256"],
        adopted_at="2026-08-27T02:00:00Z",
    )
    entry["active_adoption_id"] = second_id
    built["activation"]["pack"] = new_pack_ref
    built["activation"]["activation_generation"] = 2
    _write_authority(built["root"], "activation.json", built["activation"])

    catalog = load_catalog(tmp_path)
    intent = catalog.packs["vscode"].intents["OPEN_FOLDER"]
    assert intent.availability is IntentAvailability.ACTIVE
    assert intent.active_adoption.adoption_id == second_id
    assert set(intent.adoptions) == {first_id, second_id}
    assert (
        intent.adoption_for_identity(
            first_id, ApplicationIdentity("executable_version", "1.134.0")
        ).adoption_id
        == first_id
    )


def test_historical_binding_must_still_verify_its_own_artifacts(tmp_path):
    built = _one_pack(tmp_path)
    entry = built["activation"]["intents"]["OPEN_FOLDER"]
    first_id = entry["active_adoption_id"]
    second_id = "accept-open_folder-2"
    entry["adoptions"][second_id] = _adoption(
        built["recipe_refs"]["OPEN_FOLDER"],
        built["pack_ref"],
        built["intent_refs"]["OPEN_FOLDER"],
        _evidence(tmp_path, "vscode-open_folder-history"),
        identity="1.135.0",
        supersedes_id=first_id,
        supersedes_recipe=entry["adoptions"][first_id]["recipe"]["sha256"],
        adopted_at="2026-08-27T02:00:00Z",
    )
    entry["active_adoption_id"] = second_id
    entry["adoptions"][first_id]["accepted_pack"]["sha256"] = "0" * 64
    built["activation"]["activation_generation"] = 2
    _write_authority(built["root"], "activation.json", built["activation"])

    catalog = load_catalog(tmp_path)
    intent = catalog.packs["vscode"].intents["OPEN_FOLDER"]
    assert intent.availability is IntentAvailability.ACTIVE
    assert first_id not in intent.adoptions
    assert any(
        item.code is DiagnosticCode.INACTIVE_ADOPTION_INVALID
        for item in catalog.diagnostics
    )


def test_unknown_application_identity_never_activates(tmp_path):
    built = _one_pack(tmp_path)
    entry = built["activation"]["intents"]["OPEN_FOLDER"]
    adoption = next(iter(entry["adoptions"].values()))
    adoption["accepted_application_identity"]["value"] = "unknown"
    _write_authority(built["root"], "activation.json", built["activation"])

    catalog = load_catalog(tmp_path)
    intent = catalog.packs["vscode"].intents["OPEN_FOLDER"]
    assert intent.availability is IntentAvailability.KNOWN_INTENT_RECIPE_UNAVAILABLE
    assert intent.active_adoption is None
    assert any(
        item.code is DiagnosticCode.ACTIVE_ADOPTION_INVALID
        for item in catalog.diagnostics
    )


def test_changed_activation_bytes_cannot_reuse_the_previous_generation(tmp_path):
    built = _one_pack(tmp_path)
    first = load_catalog(tmp_path)
    assert first.packs["vscode"].activation_generation == 1

    reloaded = load_catalog(tmp_path, previous=first)
    assert reloaded.packs["vscode"].activation_generation == 1

    built["activation"]["intents"]["OPEN_FOLDER"]["active_adoption_id"] = None
    _write_authority(built["root"], "activation.json", built["activation"])
    withdrawn = load_catalog(tmp_path, previous=first)
    assert "vscode" not in withdrawn.packs
    assert any(
        item.code is DiagnosticCode.GENERATION_INVALID for item in withdrawn.diagnostics
    )

    built["activation"]["activation_generation"] = 2
    _write_authority(built["root"], "activation.json", built["activation"])
    accepted = load_catalog(tmp_path, previous=first)
    assert accepted.packs["vscode"].activation_generation == 2


def test_two_independent_first_adoptions_are_rejected(tmp_path):
    built = _one_pack(tmp_path)
    entry = built["activation"]["intents"]["OPEN_FOLDER"]
    entry["adoptions"]["accept-open_folder-2"] = _adoption(
        built["recipe_refs"]["OPEN_FOLDER"],
        built["pack_ref"],
        built["intent_refs"]["OPEN_FOLDER"],
        _evidence(tmp_path, "vscode-open_folder-second-root"),
        identity="1.135.0",
        adopted_at="2026-08-27T02:00:00Z",
    )
    _write_authority(built["root"], "activation.json", built["activation"])

    catalog = load_catalog(tmp_path)
    intent = catalog.packs["vscode"].intents["OPEN_FOLDER"]
    assert intent.adoptions == {}
    assert intent.availability is IntentAvailability.KNOWN_INTENT_RECIPE_UNAVAILABLE
    assert any(
        item.code is DiagnosticCode.ACTIVE_ADOPTION_INVALID
        for item in catalog.diagnostics
    )


def test_duplicate_intent_is_detected_even_when_one_artifact_is_invalid(tmp_path):
    one = _make_pack(tmp_path, directory="one", pack_id="one", active=False)
    two = _make_pack(tmp_path, directory="two", pack_id="two", active=False)
    two["activation"]["intents"]["OPEN_FOLDER"]["intent"]["sha256"] = "0" * 64
    _write_authority(two["root"], "activation.json", two["activation"])
    _write_index(
        tmp_path,
        [
            {"pack_id": "one", "path": one["directory"]},
            {"pack_id": "two", "path": two["directory"]},
        ],
    )

    catalog = load_catalog(tmp_path)
    assert not catalog.root_valid
    assert catalog.packs == {}
    assert any(
        item.code is DiagnosticCode.DUPLICATE_INTENT for item in catalog.diagnostics
    )


def test_one_intent_may_repeat_a_phrase_across_its_own_rules(tmp_path):
    built = _one_pack(tmp_path, active=False)
    phrase = "open a folder in vs code"
    repeated = _write_json(
        built["root"],
        "intents/open_folder-repeated.json",
        {
            "schema_version": 2,
            "intent_id": "OPEN_FOLDER",
            "canonical_target": "Visual Studio Code",
            "rules": [
                {"tier": "exact", "phrases": [phrase]},
                {"tier": "exact", "phrases": [phrase]},
            ],
        },
    )
    built["activation"]["intents"]["OPEN_FOLDER"]["intent"] = repeated
    _write_authority(built["root"], "activation.json", built["activation"])

    catalog = load_catalog(tmp_path)
    assert catalog.root_valid
    assert set(catalog.packs["vscode"].intents) == {"OPEN_FOLDER"}
    assert not any(
        item.code is DiagnosticCode.DUPLICATE_EXACT_PHRASE
        for item in catalog.diagnostics
    )


def test_pack_directories_that_resolve_to_one_place_load_no_packs(tmp_path):
    built = _make_pack(tmp_path, directory="vscode", pack_id="vscode", active=False)
    alias = built["root"].parent / "vscode_alias"
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(alias), str(built["root"])],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or not alias.exists():
        pytest.skip(f"directory junction unavailable: {completed.stderr.strip()}")
    assert not alias.is_symlink(), "a junction must not be caught by the symlink rule"

    _write_index(
        tmp_path,
        [
            {"pack_id": "vscode", "path": "vscode"},
            {"pack_id": "alias", "path": "vscode_alias"},
        ],
    )
    catalog = load_catalog(tmp_path)
    assert not catalog.root_valid
    assert catalog.packs == {}
    assert any(
        item.code is DiagnosticCode.ROOT_INDEX_INVALID for item in catalog.diagnostics
    )


def test_a_rejected_ancestor_does_not_disable_a_valid_active_descendant(tmp_path):
    """The predecessor chain is walked over declared edges, not surviving ones.

    Walking the surviving set instead makes a rejected ancestor orphan every
    descendant, which would disable a fully valid active record -- the outcome
    Design section 3 forbids. This entry's only first adoption is the rejected
    one, so it also pins the legitimate zero-verified-roots case.
    """

    built = _one_pack(tmp_path)
    entry = built["activation"]["intents"]["OPEN_FOLDER"]
    first_id = entry["active_adoption_id"]
    second_id = "accept-open_folder-2"
    entry["adoptions"][second_id] = _adoption(
        built["recipe_refs"]["OPEN_FOLDER"],
        built["pack_ref"],
        built["intent_refs"]["OPEN_FOLDER"],
        _evidence(tmp_path, "vscode-open_folder-descendant"),
        identity="1.135.0",
        supersedes_id=first_id,
        supersedes_recipe=entry["adoptions"][first_id]["recipe"]["sha256"],
        adopted_at="2026-08-27T02:00:00Z",
    )
    entry["active_adoption_id"] = second_id
    # Break the ancestor only. Its own evidence document no longer verifies,
    # which leaves the descendant's facts untouched.
    entry["adoptions"][first_id]["evidence"]["sha256"] = "0" * 64
    built["activation"]["activation_generation"] = 2
    _write_authority(built["root"], "activation.json", built["activation"])

    catalog = load_catalog(tmp_path)
    intent = catalog.packs["vscode"].intents["OPEN_FOLDER"]
    assert intent.availability is IntentAvailability.ACTIVE
    assert intent.active_adoption.adoption_id == second_id
    assert set(intent.adoptions) == {second_id}
    assert all(
        record.supersedes_adoption_id is not None
        for record in intent.adoptions.values()
    ), "no verified first adoption remains, and that must stay legitimate"
    assert any(
        item.code is DiagnosticCode.INACTIVE_ADOPTION_INVALID
        for item in catalog.diagnostics
    )
    assert not any(
        item.code is DiagnosticCode.ACTIVE_ADOPTION_INVALID
        for item in catalog.diagnostics
    )


def test_history_keeps_the_identity_strategy_it_was_accepted_under(tmp_path):
    """A pack that switches identity strategy must not erase its own history."""

    source = tmp_path / "ghostcursor" / "demo" / "synthetic_export_app.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"APP_TITLE = 'Synthetic Export'\n")

    built = _one_pack(tmp_path)
    entry = built["activation"]["intents"]["OPEN_FOLDER"]
    first_id = entry["active_adoption_id"]

    switched = _pack(display="vscode")
    switched["version_identity"] = {
        "kind": "content_sha256",
        "path": "ghostcursor/demo/synthetic_export_app.py",
    }
    new_pack_ref = _write_json(built["root"], "pack/vscode-v2.json", switched)

    second_id = "accept-open_folder-2"
    second = _adoption(
        built["recipe_refs"]["OPEN_FOLDER"],
        new_pack_ref,
        built["intent_refs"]["OPEN_FOLDER"],
        _evidence(tmp_path, "vscode-open_folder-strategy"),
        identity=_sha(source.read_bytes()),
        supersedes_id=first_id,
        supersedes_recipe=entry["adoptions"][first_id]["recipe"]["sha256"],
        adopted_at="2026-08-27T02:00:00Z",
    )
    second["accepted_application_identity"]["kind"] = "content_sha256"
    entry["adoptions"][second_id] = second
    entry["active_adoption_id"] = second_id
    built["activation"]["pack"] = new_pack_ref
    built["activation"]["activation_generation"] = 2
    _write_authority(built["root"], "activation.json", built["activation"])

    catalog = load_catalog(tmp_path)
    intent = catalog.packs["vscode"].intents["OPEN_FOLDER"]
    assert intent.availability is IntentAvailability.ACTIVE
    assert set(intent.adoptions) == {first_id, second_id}
    assert (
        intent.adoption_for_identity(
            first_id, ApplicationIdentity("executable_version", "1.134.0")
        ).adoption_id
        == first_id
    )
    assert intent.active_adoption.accepts_identity(
        ApplicationIdentity("content_sha256", _sha(source.read_bytes()))
    )


def test_an_unresolvable_indexed_directory_loads_no_packs(tmp_path):
    good = _make_pack(tmp_path, directory="good", pack_id="good", active=False)
    _write_index(
        tmp_path,
        [
            {"pack_id": "good", "path": good["directory"]},
            {"pack_id": "missing", "path": "missing"},
        ],
    )

    catalog = load_catalog(tmp_path)
    assert not catalog.root_valid
    assert catalog.packs == {}
    assert any(
        item.code is DiagnosticCode.ROOT_INDEX_INVALID for item in catalog.diagnostics
    )


def test_catalog_binds_the_exact_index_bytes(tmp_path):
    _one_pack(tmp_path, active=False)
    index_path = tmp_path / "ghostcursor" / "packs" / "index.json"

    catalog = load_catalog(tmp_path)
    assert catalog.index_sha256 == _sha(index_path.read_bytes())

    missing = load_catalog(tmp_path / "empty")
    assert missing.index_sha256 is None
