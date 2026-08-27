from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ghostcursor.packs.trusted import (
    ArtifactRef,
    ArtifactSchema,
    load_authority_document,
    load_trusted_artifact,
    resolve_trusted_directory,
)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_json(root: Path, relative: str, value: object) -> ArtifactRef:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    path.write_bytes(raw)
    return ArtifactRef(path=relative, sha256=_digest(raw))


def _pack(**overrides) -> dict:
    value = {
        "schema_version": 2,
        "pack_id": "vscode",
        "pack_kind": "application",
        "display_name": "Visual Studio Code",
        "executable_names": ["code.exe"],
        "title_patterns": [".*Visual Studio Code.*", ".* - Code$"],
        "tier2_capture": "executable_bounded",
        "version_identity": {"kind": "executable_version"},
        "aliases": {
            "vscode_names": ["vs code", "vscode", "visual studio code"]
        },
    }
    value.update(overrides)
    return value


def _intent(**overrides) -> dict:
    value = {
        "schema_version": 2,
        "intent_id": "OPEN_FOLDER",
        "canonical_target": "Visual Studio Code",
        "rules": [
            {
                "tier": "exact",
                "phrases": ["open a folder in vs code", "open a folder in vscode"],
            },
            {
                "tier": "heuristic",
                "all_of": [
                    {"any_of": [{"token": "open"}]},
                    {"any_of": [{"alias": "vscode_names"}]},
                    {"any_of": [{"token": "folder"}, {"path": True}]},
                ],
            },
        ],
    }
    value.update(overrides)
    return value


def _selector(**overrides) -> dict:
    value = {
        "strategy": "provider_exact",
        "control_type": "Button",
        "names": ["Export"],
        "normalise": "none",
        "cardinality": "exactly_one",
        "result_limit": 8,
    }
    value.update(overrides)
    return value


def _claimed(name: str = "Export") -> dict:
    return {
        "name": name,
        "name_synonyms": [],
        "ocr_text": None,
        "visual_description": None,
    }


def _provenance() -> dict:
    return {
        "source_urls": [],
        "source_tier": "hand-authored",
        "model": "none",
        "prompt_version": "none",
        "created_at": "2026-08-14",
    }


def _step(**overrides) -> dict:
    value = {
        "user_action": "click",
        "target_selector": "export_button",
        "target_descriptor": {"claimed": _claimed(), "confirmed": []},
        "instruction_text": "Click Export.",
        "verification_rule": {
            "kind": "element_appears",
            "selector": "export_status",
            "args": {"fail_after_timeout": True},
            "timeout_s": 30.0,
        },
        "risk": "normal",
        "preconditions": [],
        "provenance": _provenance(),
    }
    value.update(overrides)
    return value


def _recipe(**overrides) -> dict:
    value = {
        "schema_version": 2,
        "intent_id": "EXPORT_DATA",
        "step_key_namespace": "export the current file",
        "selectors": {
            "export_button": _selector(),
            "export_status": _selector(
                names=["Export finished: table.csv"], cardinality="at_least_one"
            ),
        },
        "context_selectors": [],
        "steps": [_step()],
    }
    value.update(overrides)
    return value


def _load_json(
    tmp_path: Path,
    value: object,
    schema: ArtifactSchema,
    *,
    relative: str = "artifact.json",
    project_root: Path | None = None,
):
    ref = _write_json(tmp_path, relative, value)
    return load_trusted_artifact(
        tmp_path, ref, schema, project_root=project_root or tmp_path
    )


def test_valid_documents_load_as_immutable_values(tmp_path):
    loaded = _load_json(tmp_path, _pack(), ArtifactSchema.PACK)

    assert loaded.sha256 == loaded.ref.sha256
    assert loaded.value["pack_id"] == "vscode"
    with pytest.raises(TypeError):
        loaded.value["pack_id"] = "changed"
    with pytest.raises(TypeError):
        loaded.value["aliases"]["vscode_names"] = ("changed",)


@pytest.mark.parametrize("schema,value", [
    (
        ArtifactSchema.INDEX,
        {
            "schema_version": 2,
            "packs": [
                {"pack_id": "vscode", "path": "vscode"},
                {"pack_id": "synthetic", "path": "synthetic"},
            ],
        },
    ),
    (ArtifactSchema.PACK, _pack()),
    (ArtifactSchema.INTENT, _intent()),
    (ArtifactSchema.RECIPE, _recipe()),
])
def test_every_json_contract_has_a_valid_minimum(tmp_path, schema, value):
    assert _load_json(tmp_path, value, schema).schema is schema


def test_artifact_ref_requires_canonical_relative_path_and_full_lowercase_digest():
    good = "a" * 64
    assert ArtifactRef("pack/vscode.json", good).sha256 == good

    for path in (
        "",
        "/absolute.json",
        "C:/absolute.json",
        "C:drive-relative.json",
        "d:folder/file.json",
        "foo/C:bar.json",
        "intents/x:y.json",
        " leading.json",
        "trailing.json ",
        "foo/ leading.json",
        "foo/trailing.json ",
        "foo/trailing-dot.json.",
        "foo/control\tcharacter.json",
        "../escape.json",
        "a\\b.json",
        "a/./b.json",
    ):
        with pytest.raises(ValueError):
            ArtifactRef(path, good)
    for digest in ("a" * 12, "A" * 64, "g" * 64):
        with pytest.raises(ValueError):
            ArtifactRef("safe.json", digest)


def test_digest_is_full_authority_not_the_filename_prefix(tmp_path):
    value = _pack()
    ref = _write_json(tmp_path, "vscode.aaaaaaaaaaaa.json", value)
    wrong = ArtifactRef(ref.path, "a" * 64)

    with pytest.raises(ValueError, match="digest"):
        load_trusted_artifact(tmp_path, wrong, ArtifactSchema.PACK, project_root=tmp_path)


def test_bytes_are_read_once_then_the_same_bytes_are_hashed_and_parsed(tmp_path, monkeypatch):
    ref = _write_json(tmp_path, "pack.json", _pack())
    original = Path.read_bytes
    reads = 0

    def counted(path: Path) -> bytes:
        nonlocal reads
        reads += 1
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", counted)
    loaded = load_trusted_artifact(
        tmp_path, ref, ArtifactSchema.PACK, project_root=tmp_path
    )

    assert reads == 1
    assert _digest(loaded.raw_bytes) == loaded.sha256
    assert loaded.value["display_name"] == "Visual Studio Code"


def test_bom_and_invalid_utf8_fail_instead_of_being_repaired(tmp_path):
    for name, raw in (
        ("bom.json", b"\xef\xbb\xbf{}"),
        ("invalid.json", b'{"schema_version":2,"bad":"\xff"}'),
    ):
        path = tmp_path / name
        path.write_bytes(raw)
        ref = ArtifactRef(name, _digest(raw))
        with pytest.raises(ValueError, match="UTF-8|BOM"):
            load_trusted_artifact(tmp_path, ref, ArtifactSchema.PACK, project_root=tmp_path)


def test_duplicate_json_key_is_rejected_before_last_write_wins(tmp_path):
    raw = b'{"schema_version":2,"schema_version":1}'
    (tmp_path / "duplicate.json").write_bytes(raw)
    ref = ArtifactRef("duplicate.json", _digest(raw))

    with pytest.raises(ValueError, match="duplicate.*schema_version"):
        load_trusted_artifact(tmp_path, ref, ArtifactSchema.PACK, project_root=tmp_path)


def test_nonfinite_json_number_is_rejected(tmp_path):
    raw = b'{"schema_version":2,"timeout":1e999}'
    (tmp_path / "nonfinite.json").write_bytes(raw)
    ref = ArtifactRef("nonfinite.json", _digest(raw))

    with pytest.raises(ValueError, match="non-finite"):
        load_trusted_artifact(tmp_path, ref, ArtifactSchema.RECIPE, project_root=tmp_path)


@pytest.mark.parametrize("mutation,match", [
    (lambda p: {**p, "future": True}, "unknown"),
    (lambda p: {k: v for k, v in p.items() if k != "aliases"}, "missing"),
    (lambda p: {**p, "schema_version": 1}, "schema_version"),
])
def test_top_level_schema_is_exact(tmp_path, mutation, match):
    with pytest.raises(ValueError, match=match):
        _load_json(tmp_path, mutation(_pack()), ArtifactSchema.PACK)


@pytest.mark.parametrize("symlink_part", ["nested", "nested/pack.json"])
def test_final_or_parent_symlink_is_rejected_before_resolution(
    tmp_path, monkeypatch, symlink_part
):
    ref = _write_json(tmp_path, "nested/pack.json", _pack())
    original = Path.is_symlink

    def fake(path: Path) -> bool:
        return path == tmp_path.joinpath(*symlink_part.split("/")) or original(path)

    monkeypatch.setattr(Path, "is_symlink", fake)
    with pytest.raises(ValueError, match="symlink"):
        load_trusted_artifact(tmp_path, ref, ArtifactSchema.PACK, project_root=tmp_path)


def test_evidence_uses_repository_root_but_must_stay_under_docs_evidence(tmp_path):
    evidence = tmp_path / "docs" / "evidence" / "accepted.md"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("accepted\n", encoding="utf-8", newline="\n")
    ref = ArtifactRef("docs/evidence/accepted.md", _digest(evidence.read_bytes()))

    loaded = load_trusted_artifact(tmp_path, ref, ArtifactSchema.EVIDENCE)
    assert loaded.value == "accepted\n"

    outside = tmp_path / "docs" / "other.md"
    outside.write_text("no\n", encoding="utf-8", newline="\n")
    ref = ArtifactRef("docs/other.md", _digest(outside.read_bytes()))
    with pytest.raises(ValueError, match="docs/evidence"):
        load_trusted_artifact(tmp_path, ref, ArtifactSchema.EVIDENCE)

    wrong_type = tmp_path / "docs" / "evidence" / "accepted.txt"
    wrong_type.write_text("no\n", encoding="utf-8", newline="\n")
    ref = ArtifactRef("docs/evidence/accepted.txt", _digest(wrong_type.read_bytes()))
    with pytest.raises(ValueError, match="Markdown"):
        load_trusted_artifact(tmp_path, ref, ArtifactSchema.EVIDENCE)


def test_index_rejects_casefold_duplicate_ids_and_paths(tmp_path):
    for packs in (
        [
            {"pack_id": "vscode", "path": "vscode"},
            {"pack_id": "vscode", "path": "other"},
        ],
        [
            {"pack_id": "vscode", "path": "VSCode"},
            {"pack_id": "other", "path": "vscode"},
        ],
    ):
        with pytest.raises(ValueError, match="duplicate"):
            _load_json(
                tmp_path,
                {"schema_version": 2, "packs": packs},
                ArtifactSchema.INDEX,
            )


@pytest.mark.parametrize("field,value", [
    ("pack_id", "VSCode"),
    ("display_name", " Visual Studio Code"),
    ("executable_names", ["Code.exe"]),
    ("executable_names", ["bin/code.exe"]),
    ("title_patterns", ["["]),
    ("tier2_capture", "auto"),
    ("aliases", {"vscode_names": ["VS Code"]}),
    ("aliases", {"vscode_names": ["vs  code"]}),
])
def test_pack_rejects_noncanonical_or_invalid_fields(tmp_path, field, value):
    with pytest.raises(ValueError):
        _load_json(tmp_path, _pack(**{field: value}), ArtifactSchema.PACK)


def test_pack_kind_constraints_are_explicit(tmp_path):
    planner = _pack(
        pack_id="common",
        pack_kind="planner_only",
        display_name="Common intents",
        executable_names=[],
        title_patterns=[],
        tier2_capture="disabled",
        version_identity=None,
        aliases={},
    )
    assert _load_json(tmp_path, planner, ArtifactSchema.PACK).value["pack_kind"] == "planner_only"

    with pytest.raises(ValueError, match="planner_only"):
        _load_json(tmp_path, {**planner, "executable_names": ["host.exe"]}, ArtifactSchema.PACK)
    with pytest.raises(ValueError, match="planner_only"):
        _load_json(
            tmp_path,
            {**planner, "aliases": {"vscode_names": ["vs code"]}},
            ArtifactSchema.PACK,
        )
    with pytest.raises(ValueError, match="application"):
        _load_json(tmp_path, _pack(executable_names=[]), ArtifactSchema.PACK)


def test_content_identity_is_allowlisted_and_checked_without_hashing_python_version(tmp_path, monkeypatch):
    source = tmp_path / "ghostcursor" / "demo" / "synthetic_export_app.py"
    source.parent.mkdir(parents=True)
    source.write_text("APP_TITLE = 'Synthetic Export'\n", encoding="utf-8", newline="\n")
    synthetic = _pack(
        pack_id="synthetic",
        display_name="Synthetic Export",
        executable_names=["python.exe"],
        title_patterns=["^Synthetic Export$"],
        tier2_capture="disabled",
        version_identity={
            "kind": "content_sha256",
            "path": "ghostcursor/demo/synthetic_export_app.py",
        },
        aliases={},
    )

    loaded = _load_json(
        tmp_path / "pack-root",
        synthetic,
        ArtifactSchema.PACK,
        project_root=tmp_path,
    )
    assert loaded.value["version_identity"]["kind"] == "content_sha256"

    for bad in (
        "ghostcursor/demo/missing.py",
        "ghostcursor/other/app.py",
        "../outside.py",
        "C:/outside.py",
    ):
        with pytest.raises(ValueError):
            _load_json(
                tmp_path / ("bad-" + hashlib.sha1(bad.encode()).hexdigest()),
                {**synthetic, "version_identity": {"kind": "content_sha256", "path": bad}},
                ArtifactSchema.PACK,
                project_root=tmp_path,
            )

    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == source or original(path))
    with pytest.raises(ValueError, match="symlink"):
        _load_json(
            tmp_path / "symlink-source",
            synthetic,
            ArtifactSchema.PACK,
            project_root=tmp_path,
        )


@pytest.mark.parametrize("rules", [
    [{"tier": "exact", "phrases": []}],
    [{"tier": "exact", "phrases": ["Open Folder"]}],
    [{"tier": "heuristic", "all_of": []}],
    [{"tier": "heuristic", "all_of": [{"any_of": []}]}],
    [{"tier": "heuristic", "all_of": [{"any_of": [{"token": ""}]}]}],
    [{"tier": "heuristic", "all_of": [{"any_of": [{"path": False}]}]}],
    [{"tier": "heuristic", "all_of": [{"any_of": [{"plugin": "x"}]}]}],
])
def test_intent_rejects_matcher_extensions_and_vacuous_rules(tmp_path, rules):
    with pytest.raises(ValueError):
        _load_json(tmp_path, _intent(rules=rules), ArtifactSchema.INTENT)


def test_intent_allows_no_rules_for_model_visible_inactive_intent(tmp_path):
    loaded = _load_json(
        tmp_path,
        _intent(intent_id="OPEN_SETTINGS", canonical_target=None, rules=[]),
        ArtifactSchema.INTENT,
    )
    assert loaded.value["rules"] == ()


@pytest.mark.parametrize("selector", [
    _selector(strategy="plugin"),
    _selector(result_limit=0),
    _selector(result_limit=True),
    _selector(names=[]),
    _selector(names=["One", "Two"]),
    _selector(normalise="strip_leading_private_use"),
    _selector(cardinality="first"),
])
def test_provider_selector_contract_is_closed(tmp_path, selector):
    recipe = _recipe(selectors={"export_button": selector, "export_status": _selector(names=["Done"], cardinality="at_least_one")})
    with pytest.raises(ValueError):
        _load_json(tmp_path, recipe, ArtifactSchema.RECIPE)


def test_bounded_selector_may_have_multiple_names_and_normalise(tmp_path):
    bounded = _selector(
        strategy="bounded_descendants",
        names=["Open Folder...", "Open Folder…"],
        normalise="strip_leading_private_use",
    )
    recipe = _recipe(selectors={"export_button": bounded, "export_status": _selector(names=["Done"], cardinality="at_least_one")})
    assert _load_json(tmp_path, recipe, ArtifactSchema.RECIPE).value["selectors"]["export_button"]["strategy"] == "bounded_descendants"


def test_recipe_rejects_unknown_missing_unused_or_wrong_cardinality_references(tmp_path):
    cases = []
    cases.append(_recipe(steps=[_step(target_selector="missing")]))
    cases.append(_recipe(context_selectors=["missing"]))
    cases.append(_recipe(selectors={**_recipe()["selectors"], "unused": _selector()}))
    cases.append(
        _recipe(
            selectors={
                "export_button": _selector(cardinality="at_least_one"),
                "export_status": _selector(names=["Done"], cardinality="at_least_one"),
            }
        )
    )
    cases.append(_recipe(context_selectors=["export_button"]))

    for recipe in cases:
        with pytest.raises(ValueError):
            _load_json(tmp_path, recipe, ArtifactSchema.RECIPE)


def test_recipe_requires_target_selector_for_targeted_action(tmp_path):
    with pytest.raises(ValueError, match="target_selector"):
        _load_json(
            tmp_path,
            _recipe(steps=[_step(target_selector=None)]),
            ArtifactSchema.RECIPE,
        )


def test_confirmed_observations_and_coordinates_are_forbidden_in_trusted_recipe(tmp_path):
    confirmed = _step()
    confirmed["target_descriptor"] = {
        "claimed": _claimed(),
        "confirmed": [{"automation_id": "Export"}],
    }
    coordinate = _step()
    coordinate["verification_rule"]["args"]["bbox"] = [1, 2, 3, 4]

    for step in (confirmed, coordinate):
        with pytest.raises(ValueError):
            _load_json(tmp_path, _recipe(steps=[step]), ArtifactSchema.RECIPE)


def test_step_and_provenance_contracts_reject_unknown_or_empty_data(tmp_path):
    bad_step = _step(future=True)
    bad_provenance = _step(provenance={**_provenance(), "reviewer": "nobody"})
    empty_instruction = _step(instruction_text="   ")

    for step in (bad_step, bad_provenance, empty_instruction):
        with pytest.raises(ValueError):
            _load_json(tmp_path, _recipe(steps=[step]), ArtifactSchema.RECIPE)


@pytest.mark.parametrize("action", ["type_text", "execute", ""])
def test_recipe_rejects_actions_outside_the_frozen_step_contract(tmp_path, action):
    with pytest.raises(ValueError):
        _load_json(tmp_path, _recipe(steps=[_step(user_action=action)]), ArtifactSchema.RECIPE)


def test_targeted_action_requires_a_claimed_identity(tmp_path):
    empty_claim = {"name": None, "name_synonyms": [], "ocr_text": None, "visual_description": "button"}
    step = _step(target_descriptor={"claimed": empty_claim, "confirmed": []})
    with pytest.raises(ValueError, match="nothing to identify"):
        _load_json(tmp_path, _recipe(steps=[step]), ArtifactSchema.RECIPE)


def test_elevated_step_cannot_use_any_meaningful_change(tmp_path):
    step = _step(
        user_action="observe",
        target_selector=None,
        risk="elevated",
        verification_rule={
            "kind": "any_meaningful_change",
            "args": {"scope": {}},
            "timeout_s": 30.0,
        },
    )
    recipe = _recipe(
        context_selectors=["world_state"],
        selectors={"world_state": _selector(cardinality="at_least_one")},
        steps=[step],
    )
    with pytest.raises(ValueError, match="elevated-risk"):
        _load_json(tmp_path, recipe, ArtifactSchema.RECIPE)


def test_verification_options_retain_the_frozen_cross_kind_rules(tmp_path):
    step = _step(
        verification_rule={
            "kind": "element_disappears",
            "selector": "export_status",
            "args": {"timeout_from_hint": True, "fail_after_timeout": True},
            "timeout_s": 30.0,
        }
    )
    assert _load_json(tmp_path, _recipe(steps=[step]), ArtifactSchema.RECIPE)

    step["verification_rule"]["args"] = {"timeout_from_hint": True}
    with pytest.raises(ValueError, match="requires fail_after_timeout"):
        _load_json(tmp_path / "deadline", _recipe(steps=[step]), ArtifactSchema.RECIPE)

    step["verification_rule"]["args"] = {"accept_if_already_present": True}
    with pytest.raises(ValueError, match="limited"):
        _load_json(tmp_path / "already", _recipe(steps=[step]), ArtifactSchema.RECIPE)


def test_selector_required_and_selector_forbidden_verification_kinds(tmp_path):
    missing = _step()
    del missing["verification_rule"]["selector"]
    forbidden = _step(
        verification_rule={
            "kind": "user_confirms",
            "selector": "export_status",
            "args": {},
            "timeout_s": 30.0,
        }
    )

    for step in (missing, forbidden):
        with pytest.raises(ValueError):
            _load_json(tmp_path, _recipe(steps=[step]), ArtifactSchema.RECIPE)


def test_any_meaningful_change_requires_context_selector(tmp_path):
    step = _step(
        user_action="observe",
        target_selector=None,
        verification_rule={
            "kind": "any_meaningful_change",
            "args": {"scope": {}},
            "timeout_s": 30.0,
        },
    )
    with pytest.raises(ValueError, match="context_selector"):
        _load_json(tmp_path, _recipe(steps=[step]), ArtifactSchema.RECIPE)

    recipe = _recipe(
        context_selectors=["world_state"],
        selectors={"world_state": _selector(cardinality="at_least_one")},
        steps=[step],
    )
    assert _load_json(tmp_path, recipe, ArtifactSchema.RECIPE).value["context_selectors"] == ("world_state",)


def test_window_title_contract_has_no_regex_escape_hatch(tmp_path):
    title_rule = {
        "kind": "window_title_matches",
        "args": {
            "completion_title_suffixes": ["visual studio code", " - code"],
            "goal_reference": {
                "strip_leading_token": "open",
                "alias": "vscode_names",
                "nonspecific_templates": ["a folder in {alias}", "folder in {alias}"],
                "strip_trailing_alias_clause": {"preposition": "in"},
                "basename_separators": ["/", "\\"],
                "minimum_length": 2,
            },
            "fail_after_timeout": True,
        },
        "timeout_s": 20.0,
    }
    step = _step(verification_rule=title_rule)
    recipe = _recipe(
        selectors={"export_button": _selector()},
        steps=[step],
    )
    assert _load_json(tmp_path, recipe, ArtifactSchema.RECIPE).value["steps"][0]["verification_rule"]["kind"] == "window_title_matches"

    title_rule["args"]["pattern"] = ".+"
    with pytest.raises(ValueError, match="unknown"):
        _load_json(tmp_path / "bad", recipe, ArtifactSchema.RECIPE)


def test_gitattributes_pins_every_attested_text_class_to_lf():
    attributes = (Path(__file__).parents[1] / ".gitattributes").read_text(encoding="utf-8")
    assert set(attributes.splitlines()) == {
        "ghostcursor/packs/**/*.json text eol=lf",
        "docs/superpowers/candidates/**/*.json text eol=lf",
        "tests/data/*.json text eol=lf",
        "docs/evidence/**/*.md text eol=lf",
        "ghostcursor/demo/synthetic_export_app.py text eol=lf",
    }


def test_mutable_authority_document_is_read_once_hashed_parsed_and_frozen(
    tmp_path, monkeypatch
):
    path = tmp_path / "activation.json"
    path.write_text('{"schema_version":2}\n', encoding="utf-8", newline="\n")
    original = Path.read_bytes
    reads = 0

    def counted(candidate: Path) -> bytes:
        nonlocal reads
        reads += 1
        return original(candidate)

    monkeypatch.setattr(Path, "read_bytes", counted)
    loaded = load_authority_document(tmp_path, "activation.json")

    assert reads == 1
    assert loaded.sha256 == _digest(loaded.raw_bytes)
    assert loaded.value["schema_version"] == 2
    with pytest.raises(TypeError):
        loaded.value["schema_version"] = 1


def test_trusted_directory_resolution_rejects_files_and_symlink_components(
    tmp_path, monkeypatch
):
    directory = tmp_path / "packs" / "vscode"
    directory.mkdir(parents=True)
    assert resolve_trusted_directory(tmp_path, "packs/vscode") == directory.resolve()

    file_path = tmp_path / "packs" / "not-a-directory"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="directory"):
        resolve_trusted_directory(tmp_path, "packs/not-a-directory")

    original = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == tmp_path / "packs" or original(path),
    )
    with pytest.raises(ValueError, match="symlink"):
        resolve_trusted_directory(tmp_path, "packs/vscode")
