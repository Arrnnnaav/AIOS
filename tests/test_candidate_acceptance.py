"""The candidate harness is an instrument, never a second authority path.

D070 requires acceptance evidence committed before installation, so a human has
to be able to run bytes nothing yet trusts. Everything below exists to keep that
capability from becoming a way in:

* it loads exactly one graph, named by full digest, with no scanning and no
  fallback -- every convenience there is a way to run bytes other than the ones
  reviewed;
* quarantine is checked, not assumed;
* it cannot write `activation.json`;
* application identity is resolved by the pack's own strategy and may only be
  ASSERTED from the command line, never supplied;
* production cannot reach it.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

from ghostcursor.devtools import candidate_acceptance as harness
from ghostcursor.devtools.candidate_acceptance import (
    CandidateRejected,
    bind_candidate_target,
    candidate_workflow,
    load_candidate,
    record_for,
)
from ghostcursor.packs.workflow import AppSnapshot, WindowCandidate, WorkflowUnavailable

PROJECT_ROOT = Path(__file__).resolve().parents[1]

ALIASES = {"vscode_names": ["vs code", "vscode", "visual studio code"]}

GOAL_REFERENCE = {
    "strip_leading_token": "open",
    "alias": "vscode_names",
    "nonspecific_templates": ["a folder in {alias}", "folder in {alias}"],
    "strip_trailing_alias_clause": {"preposition": "in"},
    "basename_separators": ["/", "\\"],
    "minimum_length": 2,
}


def _pack(kind="application", executables=("code.exe",), patterns=None):
    if patterns is None:
        patterns = [".*Visual Studio Code.*"] if kind == "application" else []
    return {
        "schema_version": 2,
        "pack_id": "vscode_candidate",
        "pack_kind": kind,
        "display_name": "Visual Studio Code",
        "executable_names": list(executables),
        "title_patterns": list(patterns),
        "tier2_capture": "executable_bounded" if kind == "application" else "disabled",
        "version_identity": (
            {"kind": "executable_version"} if kind == "application" else None
        ),
        "aliases": dict(ALIASES) if kind == "application" else {},
    }


def _intent(intent_id="OPEN_FOLDER"):
    return {
        "schema_version": 2,
        "intent_id": intent_id,
        "canonical_target": "Open Folder...",
        "rules": [
            {"tier": "exact", "phrases": ["open a folder in vs code"]},
        ],
    }


def _recipe(intent_id="OPEN_FOLDER"):
    return {
        "schema_version": 2,
        "intent_id": intent_id,
        "step_key_namespace": "vscode.open_folder",
        "selectors": {
            "open_folder": {
                "strategy": "bounded_descendants",
                "control_type": "Button",
                "names": ["Open Folder..."],
                "normalise": "strip_leading_private_use",
                "cardinality": "exactly_one",
                "result_limit": 4,
            }
        },
        "context_selectors": [],
        "steps": [
            {
                "user_action": "click",
                "target_selector": "open_folder",
                "target_descriptor": {
                    "claimed": {
                        "name": "Open Folder...",
                        "name_synonyms": [],
                        "ocr_text": None,
                        "visual_description": None,
                    },
                    "confirmed": [],
                },
                "instruction_text": "Click Open Folder.",
                "verification_rule": {
                    "kind": "window_title_matches",
                    "args": {
                        "completion_title_suffixes": ["visual studio code", " - code"],
                        "goal_reference": GOAL_REFERENCE,
                        "fail_after_timeout": True,
                    },
                    "timeout_s": 20.0,
                },
                "risk": "normal",
                "preconditions": [],
                "provenance": {
                    "source_urls": [],
                    "source_tier": "trusted",
                    "model": "none",
                    "prompt_version": "none",
                    "created_at": "2026-08-27T00:00:00Z",
                },
            }
        ],
    }


def _write(path: Path, value) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, indent=2, sort_keys=True).encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def candidate(tmp_path):
    """One quarantined graph on disk, outside any trusted root."""
    root = tmp_path / "candidates" / "open-folder"
    paths = {
        "pack": root / "pack" / "vscode.json",
        "intent": root / "intents" / "open_folder.json",
        "recipe": root / "recipes" / "open_folder.json",
    }
    digests = {
        "pack": _write(paths["pack"], _pack()),
        "intent": _write(paths["intent"], _intent()),
        "recipe": _write(paths["recipe"], _recipe()),
    }
    return {"root": root, "paths": paths, "digests": digests}


def _load(candidate, **overrides):
    kwargs = {
        "pack_path": candidate["paths"]["pack"],
        "pack_sha256": candidate["digests"]["pack"],
        "intent_path": candidate["paths"]["intent"],
        "intent_sha256": candidate["digests"]["intent"],
        "recipe_path": candidate["paths"]["recipe"],
        "recipe_sha256": candidate["digests"]["recipe"],
        "project_root": PROJECT_ROOT,
    }
    kwargs.update(overrides)
    root = kwargs.pop("root", candidate["root"])
    return load_candidate(root, **kwargs)


def _window(
    hwnd=101,
    title="demo - Visual Studio Code",
    exe="code.exe",
    version="1.134.0",
    pid=4242,
):
    return WindowCandidate(
        hwnd=hwnd,
        title=title,
        app=AppSnapshot(executable_name=exe, version=version, process_id=pid),
    )


# ---------------------------------------------------------------------------
# Loading exactly one named graph
# ---------------------------------------------------------------------------


def test_a_complete_named_graph_loads(candidate) -> None:
    graph = _load(candidate)
    assert graph.pack.value["pack_id"] == "vscode_candidate"
    assert graph.intent.value["intent_id"] == "OPEN_FOLDER"
    assert graph.compiled.intent_id == "OPEN_FOLDER"
    assert set(graph.digests) == {"pack", "intent", "recipe"}


@pytest.mark.parametrize("artifact", ["pack", "intent", "recipe"])
def test_a_missing_digest_is_refused(candidate, artifact) -> None:
    """An unnamed digest is not a convenience, it is an unbound artifact.

    Accepting bytes without naming which bytes is exactly the failure the whole
    content-addressed scheme exists to prevent.
    """
    with pytest.raises(CandidateRejected, match="explicit sha256"):
        _load(candidate, **{f"{artifact}_sha256": ""})


@pytest.mark.parametrize("artifact", ["pack", "intent", "recipe"])
def test_a_digest_mismatch_is_refused(candidate, artifact) -> None:
    with pytest.raises(ValueError, match="digest mismatch"):
        _load(candidate, **{f"{artifact}_sha256": "9" * 64})


@pytest.mark.parametrize("artifact", ["pack", "intent", "recipe"])
def test_edited_bytes_are_refused_even_at_the_same_path(candidate, artifact) -> None:
    """The digest binds content, not a filename."""
    path = candidate["paths"][artifact]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="digest mismatch"):
        _load(candidate)


def test_a_directory_is_refused_rather_than_searched(candidate) -> None:
    """No globbing, at all.

    A harness that searches picks the file, and then acceptance evidence
    describes bytes chosen by a search rather than bytes chosen by a human.
    """
    with pytest.raises(CandidateRejected, match="never searches a directory"):
        _load(candidate, recipe_path=candidate["paths"]["recipe"].parent)


def test_a_file_outside_the_candidate_root_is_refused(candidate, tmp_path) -> None:
    stray = tmp_path / "elsewhere" / "recipe.json"
    digest = _write(stray, _recipe())
    with pytest.raises(CandidateRejected, match="inside the candidate root"):
        _load(candidate, recipe_path=stray, recipe_sha256=digest)


def test_an_unexpected_file_beside_the_candidate_changes_nothing(candidate) -> None:
    """Presence is not selection.

    A second recipe in the directory must not be reachable, and must not make
    the named one ambiguous either -- there is no search to confuse.
    """
    other = candidate["paths"]["recipe"].parent / "other.json"
    _write(other, _recipe(intent_id="OPEN_TERMINAL"))
    graph = _load(candidate)
    assert graph.recipe.path == candidate["paths"]["recipe"]


def test_a_candidate_inside_the_trusted_pack_root_is_refused(tmp_path) -> None:
    """Quarantine is enforced, not assumed.

    Pointed at the installed root, this would become a way to run adopted
    artifacts under acceptance framing -- producing evidence claiming
    quarantined bytes were tested about bytes that were never quarantined.
    """
    project_root = tmp_path
    root = project_root / harness.TRUSTED_PACK_ROOT / "vscode"
    root.mkdir(parents=True)
    with pytest.raises(CandidateRejected, match="quarantined"):
        load_candidate(
            root,
            pack_path=root / "pack.json",
            pack_sha256="a" * 64,
            intent_path=root / "intent.json",
            intent_sha256="a" * 64,
            recipe_path=root / "recipe.json",
            recipe_sha256="a" * 64,
            project_root=project_root,
        )


def test_artifacts_that_disagree_about_the_intent_are_not_one_graph(candidate) -> None:
    """Three valid artifacts are not automatically one workflow."""
    mismatched = candidate["paths"]["recipe"].parent / "terminal.json"
    digest = _write(mismatched, _recipe(intent_id="OPEN_TERMINAL"))
    with pytest.raises(CandidateRejected, match="but the recipe names"):
        _load(candidate, recipe_path=mismatched, recipe_sha256=digest)


def test_a_planner_only_pack_cannot_be_accepted_against_a_window(candidate) -> None:
    path = candidate["paths"]["pack"]
    digest = _write(path, _pack(kind="planner_only", executables=()))
    with pytest.raises(CandidateRejected, match="application pack"):
        _load(candidate, pack_sha256=digest)


def test_a_schema_invalid_candidate_is_refused(candidate) -> None:
    """The harness reuses the trust boundary rather than relaxing it."""
    broken = _recipe()
    broken["selectors"]["open_folder"]["cardinality"] = "first"
    digest = _write(candidate["paths"]["recipe"], broken)
    with pytest.raises(ValueError):
        _load(candidate, recipe_sha256=digest)


# ---------------------------------------------------------------------------
# Identity is resolved, never supplied
# ---------------------------------------------------------------------------


def test_the_expected_identity_asserts_and_never_supplies(candidate) -> None:
    """An operator who could name the identity could accept a version they
    never ran."""
    graph = _load(candidate)
    target = bind_candidate_target(
        graph,
        windows=[_window()],
        project_root=PROJECT_ROOT,
        expected_identity="1.134.0",
    )
    assert target.identity.value == "1.134.0"

    with pytest.raises(CandidateRejected, match="but the pack resolver reports"):
        bind_candidate_target(
            graph,
            windows=[_window()],
            project_root=PROJECT_ROOT,
            expected_identity="1.200.0",
        )


def test_the_identity_comes_from_the_live_window_not_the_assertion(candidate) -> None:
    graph = _load(candidate)
    target = bind_candidate_target(
        graph, windows=[_window(version="1.999.0")], project_root=PROJECT_ROOT
    )
    assert target.identity.value == "1.999.0"


def test_target_resolution_reuses_the_production_rules(candidate) -> None:
    """No second resolver: the same ambiguity and identity rules apply."""
    graph = _load(candidate)
    with pytest.raises(WorkflowUnavailable):
        bind_candidate_target(
            graph, windows=[_window(exe="chrome.exe")], project_root=PROJECT_ROOT
        )
    with pytest.raises(WorkflowUnavailable, match="none is in the foreground"):
        bind_candidate_target(
            graph,
            windows=[
                _window(hwnd=1, title="a - Visual Studio Code"),
                _window(hwnd=2, title="b - Visual Studio Code"),
            ],
            project_root=PROJECT_ROOT,
        )


# ---------------------------------------------------------------------------
# Reuse, not reimplementation
# ---------------------------------------------------------------------------


def test_acceptance_runs_the_same_compiled_workflow_production_would(candidate) -> None:
    """A second compiler would certify semantics production does not have."""
    from ghostcursor.packs.compile import compile_recipe
    from ghostcursor.packs.workflow import CompiledWorkflow

    graph = _load(candidate)
    target = bind_candidate_target(
        graph, windows=[_window()], project_root=PROJECT_ROOT
    )
    workflow = candidate_workflow(
        graph, r"Open C:\Projects\Demo in VS Code", target, project_root=PROJECT_ROOT
    )
    assert isinstance(workflow, CompiledWorkflow)
    assert workflow.recipe == compile_recipe(graph.recipe.value)
    assert workflow.goal_reference_for(0) == "demo"


def test_the_synthesised_adoption_never_reaches_disk(candidate, tmp_path) -> None:
    """A candidate has no adoption record; one is built for the run and dropped."""
    graph = _load(candidate)
    target = bind_candidate_target(
        graph, windows=[_window()], project_root=PROJECT_ROOT
    )
    workflow = candidate_workflow(
        graph, "Open a folder in VS Code", target, project_root=PROJECT_ROOT
    )
    assert workflow.adoption.adoption_id == "candidate"
    assert workflow.activation_generation == 0
    assert not list(candidate["root"].rglob("activation.json"))


# ---------------------------------------------------------------------------
# The run record
# ---------------------------------------------------------------------------


def test_a_run_record_names_all_three_digests_and_the_identity(candidate) -> None:
    graph = _load(candidate)
    target = bind_candidate_target(
        graph, windows=[_window()], project_root=PROJECT_ROOT
    )
    record = record_for(graph, target, outcome="passed", grounding_provenance=("uia",))
    payload = json.loads(record.to_json())

    assert payload["digests"] == dict(graph.digests)
    assert payload["application_identity"] == {
        "kind": "executable_version",
        "value": "1.134.0",
    }
    assert payload["target"]["executable"] == "code.exe"
    assert payload["outcome"] == "passed"
    assert payload["grounding_provenance"] == ["uia"]


def test_a_record_without_provenance_is_refused(candidate) -> None:
    """An outcome-only record cannot see a perception tier going dark.

    Fallback OCR preserves the outcome while the preferred tier is gone, so a
    record that does not name which tier grounded cannot support the claim the
    acceptance evidence has to make (D069).
    """
    graph = _load(candidate)
    target = bind_candidate_target(
        graph, windows=[_window()], project_root=PROJECT_ROOT
    )
    with pytest.raises(CandidateRejected, match="grounding provenance"):
        record_for(graph, target, outcome="passed", grounding_provenance=())


def test_the_record_is_the_durable_reference_not_a_log_path(candidate) -> None:
    """Evidence that names an uncommitted file names nothing (D034)."""
    graph = _load(candidate)
    target = bind_candidate_target(
        graph, windows=[_window()], project_root=PROJECT_ROOT
    )
    payload = record_for(
        graph, target, outcome="passed", grounding_provenance=("uia",)
    ).to_json()
    assert ".artifacts" not in payload


# ---------------------------------------------------------------------------
# Unreachable from production
# ---------------------------------------------------------------------------


PRODUCTION_MODULES = [
    "ghostcursor/run.py",
    "ghostcursor/daemon.py",
    "ghostcursor/reasoning/planner.py",
    "ghostcursor/reasoning/loop.py",
    "ghostcursor/packs/workflow.py",
    "ghostcursor/packs/activation.py",
    "ghostcursor/packs/compile.py",
    "ghostcursor/packs/trusted.py",
]


@pytest.mark.parametrize("module", PRODUCTION_MODULES)
def test_no_production_module_imports_the_harness(module) -> None:
    """Reachability asserted, not left to convention.

    The dependency has to point one way. The harness may use production code;
    production must not be able to reach the harness, or the acceptance
    instrument becomes a second authority path by import alone.
    """
    path = PROJECT_ROOT / module
    if not path.exists():
        pytest.skip(f"{module} does not exist")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not any("devtools" in name for name in imported), (
        f"{module} imports the developer harness"
    )


def test_the_production_parser_exposes_no_candidate_option() -> None:
    """`--recipe <path>` and the harness must not meet.

    The harness takes explicit candidate paths because that is its entire job.
    A production flag doing the same thing would be the path-based loader the
    v2 entry point exists to remove.
    """
    import ghostcursor.run as run

    parser = run.build_parser() if hasattr(run, "build_parser") else None
    if parser is None:
        source = (PROJECT_ROOT / "ghostcursor" / "run.py").read_text(encoding="utf-8")
        assert "candidate" not in source.lower()
        return
    options = {action.dest for action in parser._actions}
    assert not any("candidate" in name for name in options)


def test_the_harness_cannot_write_activation(candidate) -> None:
    """No code path here writes anything, least of all the manifest.

    Acceptance produces a record; installation and the activation swap are
    separate, later, human steps (D070). A harness that could activate would
    collapse the whole ordered sequence into one command, and the evidence
    D070 requires to exist BEFORE installation could then be written after it.

    Checked on the AST rather than the file text, so the module's own prose
    about not writing the manifest cannot make this pass or fail.
    """
    source = (
        PROJECT_ROOT / "ghostcursor" / "devtools" / "candidate_acceptance.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    writes = [
        f"{node.func.attr}:{node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr
        in {"write_text", "write_bytes", "rename", "replace", "unlink", "mkdir"}
    ]
    assert writes == [], f"the harness performs filesystem writes: {writes}"

    opened = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "open"
    ]
    assert opened == [], f"the harness opens files directly at lines {opened}"

    # A string literal naming the manifest would be a lookup or a write target.
    # Docstrings are `ast.Constant` too, so they are excluded by position: only
    # constants that are not a body's leading expression count as code.
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    literals = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "activation.json" in node.value
        and id(node) not in docstrings
    ]
    assert literals == [], (
        f"the harness names activation.json in code at lines {literals}"
    )

    assert not list(candidate["root"].rglob("activation.json"))


def test_the_harness_imports_no_input_synthesis_api() -> None:
    """The instrument runs on a real desktop against a real application.

    That is exactly where synthesizing one click would be least visible and
    most harmful, so D006 binds it as hard as it binds the agent loop.
    """
    from tests.test_no_input_synthesis import _BANNED_CALLS, _BANNED_IMPORTS

    source = (
        PROJECT_ROOT / "ghostcursor" / "devtools" / "candidate_acceptance.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in _BANNED_IMPORTS
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in _BANNED_IMPORTS
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in _BANNED_CALLS


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


def test_every_artifact_and_digest_is_a_required_option() -> None:
    parser = harness.build_parser()
    required = {
        action.dest for action in parser._actions if getattr(action, "required", False)
    }
    assert required == {
        "candidate_root",
        "pack",
        "pack_sha256",
        "intent",
        "intent_sha256",
        "recipe",
        "recipe_sha256",
        "goal",
    }


def test_the_command_prepares_a_record_for_a_valid_candidate(candidate, capsys) -> None:
    exit_code = harness.main(
        [
            "--candidate-root",
            str(candidate["root"]),
            "--pack",
            str(candidate["paths"]["pack"]),
            "--pack-sha256",
            candidate["digests"]["pack"],
            "--intent",
            str(candidate["paths"]["intent"]),
            "--intent-sha256",
            candidate["digests"]["intent"],
            "--recipe",
            str(candidate["paths"]["recipe"]),
            "--recipe-sha256",
            candidate["digests"]["recipe"],
            "--goal",
            r"Open C:\Projects\Demo in VS Code",
        ],
        project_root=PROJECT_ROOT,
        list_windows=lambda: [_window()],
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["digests"]["recipe"] == candidate["digests"]["recipe"]
    assert payload["application_identity"]["value"] == "1.134.0"


def test_the_command_refuses_a_mismatched_digest(candidate, capsys) -> None:
    exit_code = harness.main(
        [
            "--candidate-root",
            str(candidate["root"]),
            "--pack",
            str(candidate["paths"]["pack"]),
            "--pack-sha256",
            candidate["digests"]["pack"],
            "--intent",
            str(candidate["paths"]["intent"]),
            "--intent-sha256",
            candidate["digests"]["intent"],
            "--recipe",
            str(candidate["paths"]["recipe"]),
            "--recipe-sha256",
            "9" * 64,
            "--goal",
            "Open a folder in VS Code",
        ],
        project_root=PROJECT_ROOT,
        list_windows=lambda: [_window()],
    )
    assert exit_code == 2
    assert "digest mismatch" in capsys.readouterr().err


def test_the_command_refuses_when_no_window_matches(candidate, capsys) -> None:
    exit_code = harness.main(
        [
            "--candidate-root",
            str(candidate["root"]),
            "--pack",
            str(candidate["paths"]["pack"]),
            "--pack-sha256",
            candidate["digests"]["pack"],
            "--intent",
            str(candidate["paths"]["intent"]),
            "--intent-sha256",
            candidate["digests"]["intent"],
            "--recipe",
            str(candidate["paths"]["recipe"]),
            "--recipe-sha256",
            candidate["digests"]["recipe"],
            "--goal",
            "Open a folder in VS Code",
        ],
        project_root=PROJECT_ROOT,
        list_windows=lambda: [],
    )
    assert exit_code == 3
    assert "no acceptable target" in capsys.readouterr().err


def test_the_command_offers_no_intent_selection_option() -> None:
    """The model never picks what gets accepted.

    A model-selected intent reaching acceptance would mean bytes gained
    authority because a model named them, which is the exact inversion D058
    forbids one stage earlier.
    """
    options = {action.dest for action in harness.build_parser()._actions}
    assert "intent_id" not in options
    assert "model" not in options
    assert not any("model" in name for name in options)

    source = (
        PROJECT_ROOT / "ghostcursor" / "devtools" / "candidate_acceptance.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
    assert not any("inference" in name for name in imported)
    assert not any("planner" in name for name in imported)
