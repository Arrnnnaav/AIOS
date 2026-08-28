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
from ghostcursor.reasoning.compiled_tour import GroundingProvenance, RunOutcome

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


def _reader(window=None, *, missing=False):
    """A fake SCREEN, never a fake verdict."""

    def _read(hwnd):
        if missing:
            return None
        live = window if window is not None else _window()
        return WindowCandidate(hwnd=hwnd, title=live.title, app=live.app)

    return _read


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
    with pytest.raises(WorkflowUnavailable, match="narrow to exactly one"):
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


def test_acceptance_compiles_the_same_workflow_production_would(candidate) -> None:
    """A second compiler would certify semantics production does not have."""
    from ghostcursor.packs.compile import compile_recipe
    from ghostcursor.packs.workflow import CompiledWorkflow

    graph = _load(candidate)
    target = bind_candidate_target(graph, windows=[_window()], project_root=PROJECT_ROOT)
    workflow = candidate_workflow(
        graph, r"Open C:\Projects\Demo in VS Code", target, project_root=PROJECT_ROOT
    )
    assert isinstance(workflow, CompiledWorkflow)
    assert workflow.recipe == compile_recipe(graph.recipe.value)
    assert workflow.goal_reference_for(0) == "demo"


def test_the_synthesised_adoption_never_reaches_disk(candidate) -> None:
    """A candidate has no adoption record; one is built for the run and dropped."""
    graph = _load(candidate)
    target = bind_candidate_target(graph, windows=[_window()], project_root=PROJECT_ROOT)
    workflow = candidate_workflow(
        graph, "Open a folder in VS Code", target, project_root=PROJECT_ROOT
    )
    assert workflow.adoption.adoption_id == "candidate"
    assert workflow.activation_generation == 0
    assert not list(candidate["root"].rglob("activation.json"))


# ---------------------------------------------------------------------------
# Running the candidate through the production executor
# ---------------------------------------------------------------------------


def _perception(observe, *, started=None):
    """A `start_perception` seam: nothing runs until the gates have passed."""
    stopped = []

    def _start():
        if started is not None:
            started.append(True)
        return observe, None, lambda: stopped.append(True)

    _start.stopped = stopped
    return _start


def _factory(renderer=None):
    """A renderer FACTORY, plus the disposal the harness must always call.

    Passing a constructed renderer is what let the overlay exist before the
    gates ran: Python evaluates arguments before the call.
    """
    made = renderer if renderer is not None else _Renderer()
    disposed = []

    def _make():
        made.created = True
        return made, lambda: disposed.append(True)

    _make.disposed = disposed
    _make.renderer = made
    return _make


class _Renderer:
    """Counts what was drawn. The executor must actually reach the hint."""

    created = False

    def __init__(self):
        self.shown = []
        self.cleared = 0

    def show(self, grounded, instruction_text):
        self.shown.append((grounded, instruction_text))

    def clear(self):
        self.cleared += 1

    def settle(self):
        pass


def _element(name="Open Folder...", source="uia", bbox=(10, 20, 110, 60)):
    from ghostcursor.perception.uia import Element

    return Element(
        name=name,
        control_type="Button",
        automation_id="",
        bbox=bbox,
        path=("Button",),
        source=source,
    )


def _screen(titles, *, present=True, source="uia"):
    """A published SLOT, not a fresh walk per read.

    The executor reads what the worker last published and never takes an
    observation itself, so a fake that produced a new screen on every read
    would model the very thing this design forbids. The slot advances when the
    worker would publish -- between ticks -- which is what `_accept` wires the
    sleeper to.

    Returns `(observe, publish)`. `observe()` may return `None`, meaning
    nothing has been published yet.
    """
    from ghostcursor.reasoning.compiled_tour import TickInput

    sequence = list(titles)
    slot = {"value": None}

    def _publish():
        title = sequence.pop(0) if len(sequence) > 1 else sequence[0]
        matched = (_element(source=source),) if present else ()
        slot["value"] = TickInput(
            title=title, selectors={"open_folder": matched}, union=matched
        )

    def _observe():
        return slot["value"]

    _publish()  # the worker completes one walk before the tour starts
    return _observe, _publish


def _clock():
    now = [0.0]

    def _read():
        return now[0]

    def _sleep(seconds):
        now[0] += seconds

    return _read, _sleep


def _accept(candidate, *, screen, renderer=None, controls=None, seconds=120.0,
            read_window=None, goal=r"Open C:\Projects\Demo in VS Code"):
    from ghostcursor.devtools.candidate_acceptance import accept_candidate

    observe, publish = screen
    graph = _load(candidate)
    target = bind_candidate_target(graph, windows=[_window()], project_root=PROJECT_ROOT)
    workflow = candidate_workflow(graph, goal, target, project_root=PROJECT_ROOT)
    read, sleep = _clock()

    def _between_ticks(seconds_slept):
        # The worker publishes between ticks, exactly as the real one does.
        sleep(seconds_slept)
        publish()

    return graph, accept_candidate(
        graph,
        workflow,
        start_perception=_perception(observe),
        make_renderer=_factory(renderer),
        make_controls=(lambda: controls) if controls is not None else None,
        read_window=read_window or _reader(),
        project_root=PROJECT_ROOT,
        clock=read,
        sleeper=_between_ticks,
        seconds=seconds,
    )


def test_acceptance_wires_and_disposes_the_compiled_control_bar(candidate) -> None:
    """The human acceptance path must exercise the same safety UI it certifies."""
    class _Controls:
        def __init__(self):
            self.polls = 0
            self.disposed = False
            self.steps_reported = []

        def poll(self):
            self.polls += 1

        def should_abort(self):
            return False

        def should_pause(self):
            # Hold the state machine for one pumped turn, then release it.
            return self.polls == 1

        def report_step(self, index, total):
            self.steps_reported.append((index, total))

        def dispose(self):
            self.disposed = True

    controls = _Controls()
    _graph, record = _accept(
        candidate,
        screen=_screen(
            [
                "Welcome - Visual Studio Code",
                "Welcome - Visual Studio Code",
                "demo - Visual Studio Code",
            ]
        ),
        controls=controls,
    )

    assert record.outcome is RunOutcome.PASSED
    assert controls.polls >= 2
    assert controls.disposed is True
    # Acceptance runs the rail production runs, progress reporting included.
    assert controls.steps_reported == [(0, 1)]


def test_acceptance_actually_runs_the_workflow_and_records_what_happened(
    candidate,
) -> None:
    """The record has to come from a run, not from a caller's description.

    A harness that compiles a candidate and then asks the operator to type an
    outcome certifies nothing: the same record could be produced with no tour
    having happened at all.
    """
    renderer = _Renderer()
    graph, record = _accept(
        candidate,
        screen=_screen(
            [
                "Welcome - Visual Studio Code",
                "Welcome - Visual Studio Code",
                "demo - Visual Studio Code",
            ]
        ),
        renderer=renderer,
    )

    assert record.outcome is RunOutcome.PASSED
    assert record.grounding_provenance == (GroundingProvenance.UIA,)
    assert record.steps_completed == record.steps_total == 1
    assert renderer.shown, "the executor never rendered a hint"
    assert record.digests == dict(graph.digests)


def test_a_workflow_that_never_completes_is_recorded_as_timed_out(candidate) -> None:
    """A timeout is its own finding.

    "The user did not finish in two minutes" and "the workflow cannot work"
    are different things, and a record that conflated them would report a
    working workflow as broken.
    """
    _graph, record = _accept(
        candidate,
        screen=_screen(["Welcome - Visual Studio Code"]),
        seconds=5.0,
    )
    assert record.outcome is RunOutcome.TIMED_OUT
    assert record.steps_completed == 0
    assert "within 5s" in record.detail


def test_a_target_that_never_appears_is_recorded_as_failed(candidate) -> None:
    """FAILED specifically, not "one of the unhappy outcomes".

    Accepting either FAILED or TIMED_OUT here made the test pass no matter
    what the executor did with a loop that gave up -- including reporting it
    as a pass, which is a different bug entirely.
    """
    _graph, record = _accept(
        candidate,
        screen=_screen(["Welcome - Visual Studio Code"], present=False),
        seconds=600.0,
    )
    assert record.outcome is RunOutcome.FAILED
    assert record.grounding_provenance == ()
    assert record.steps_completed == 0


def test_a_failed_loop_is_never_reported_as_a_pass(candidate) -> None:
    """The two unhappy outcomes are distinguishable from each other and from
    a pass."""
    _graph, failed = _accept(
        candidate,
        screen=_screen(["Welcome - Visual Studio Code"], present=False),
        seconds=600.0,
    )
    _graph2, timed_out = _accept(
        candidate,
        screen=_screen(["Welcome - Visual Studio Code"]),
        seconds=5.0,
    )
    assert failed.outcome is RunOutcome.FAILED
    assert timed_out.outcome is RunOutcome.TIMED_OUT
    assert failed.outcome is not timed_out.outcome


def test_the_executor_refuses_to_ground_an_ambiguous_selector(candidate) -> None:
    """An action selector naming two controls is not a target.

    `run_observation_plan` would have faulted before this, so the guard is
    unreachable through the normal path -- and that is exactly why it is
    tested directly. The executor is what points a user at a rectangle, and it
    does not get to pick one of two when it was told there would be one.
    """
    from ghostcursor.reasoning.compiled_tour import (
        TickInput,
        execute_compiled_workflow,
    )

    graph = _load(candidate)
    target = bind_candidate_target(graph, windows=[_window()], project_root=PROJECT_ROOT)
    workflow = candidate_workflow(
        graph, "Open a folder in VS Code", target, project_root=PROJECT_ROOT
    )

    two = (_element(bbox=(0, 0, 10, 10)), _element(bbox=(50, 50, 60, 60)))

    def _observe():
        return TickInput(
            title="Welcome - Visual Studio Code",
            selectors={"open_folder": two},
            union=two,
        )

    read, sleep = _clock()
    result = execute_compiled_workflow(
        workflow,
        observe=_observe,
        renderer=_Renderer(),
        clock=read,
        sleeper=sleep,
        seconds=600.0,
    )
    assert result.outcome is RunOutcome.FAILED
    assert result.provenance == (), "an ambiguous match must not be grounded"


def test_the_run_verifies_against_the_workflows_own_goal_reference(
    candidate,
) -> None:
    """The reference is what makes verification about THIS goal.

    Without it the title check falls back to conditions 1 and 2 -- the title
    changed and still looks like VS Code -- which any other folder opening
    also satisfies. A run that opened the wrong folder would be recorded as a
    pass.
    """
    _graph, wrong_folder = _accept(
        candidate,
        screen=_screen(
            [
                "Welcome - Visual Studio Code",
                "Welcome - Visual Studio Code",
                "unrelated - Visual Studio Code",
            ]
        ),
        seconds=30.0,
        goal=r"Open C:\Projects\Demo in VS Code",
    )
    assert wrong_folder.outcome is not RunOutcome.PASSED

    _graph2, right_folder = _accept(
        candidate,
        screen=_screen(
            [
                "Welcome - Visual Studio Code",
                "Welcome - Visual Studio Code",
                "demo - Visual Studio Code",
            ]
        ),
        seconds=30.0,
        goal=r"Open C:\Projects\Demo in VS Code",
    )
    assert right_folder.outcome is RunOutcome.PASSED


def test_the_record_reports_the_tier_that_actually_grounded(candidate) -> None:
    """Outcome alone cannot see a perception tier going dark.

    Fallback OCR completes the workflow exactly as UIA would, so an
    outcome-only record shows a passing run in both cases. Open Folder's gate
    turns on this field, not on the outcome (D069).
    """
    _graph, uia_run = _accept(
        candidate,
        screen=_screen(
            [
                "Welcome - Visual Studio Code",
                "Welcome - Visual Studio Code",
                "demo - Visual Studio Code",
            ]
        ),
    )
    _graph2, ocr_run = _accept(
        candidate,
        screen=_screen(
            [
                "Welcome - Visual Studio Code",
                "Welcome - Visual Studio Code",
                "demo - Visual Studio Code",
            ],
            source="ocr",
        ),
    )

    assert uia_run.outcome is ocr_run.outcome is RunOutcome.PASSED
    assert uia_run.grounded_by_uia_only
    assert not ocr_run.grounded_by_uia_only
    assert ocr_run.grounding_provenance == (GroundingProvenance.OCR,)


def test_a_record_cannot_be_told_its_own_outcome(candidate) -> None:
    """There is no parameter for it, by construction.

    An outcome that can be stated can be stated falsely, and the reviewer's
    objection was exactly this: a record accepting arbitrary strings can say
    "passed" with nothing having run.
    """
    import inspect

    from ghostcursor.devtools.candidate_acceptance import record_for

    parameters = list(inspect.signature(record_for).parameters)
    assert parameters == ["graph", "target", "result"]

    outcomes = {member.value for member in RunOutcome}
    assert outcomes == {"passed", "failed", "timed_out", "aborted"}
    with pytest.raises(ValueError):
        RunOutcome("prepared")
    with pytest.raises(ValueError):
        GroundingProvenance("pending")


def test_the_candidate_files_are_rehashed_immediately_before_launch(
    candidate,
) -> None:
    """Evidence has to name the bytes that RAN.

    The digests were checked at load. Between then and the launch a human is
    arranging windows, and an editor left open on the candidate is the ordinary
    way those bytes change.
    """
    from ghostcursor.devtools.candidate_acceptance import accept_candidate

    graph = _load(candidate)
    target = bind_candidate_target(graph, windows=[_window()], project_root=PROJECT_ROOT)
    workflow = candidate_workflow(
        graph, "Open a folder in VS Code", target, project_root=PROJECT_ROOT
    )

    candidate["paths"]["recipe"].write_bytes(
        candidate["paths"]["recipe"].read_bytes() + b"\n"
    )
    with pytest.raises(CandidateRejected, match="since it was loaded"):
        accept_candidate(
            graph,
            workflow,
            start_perception=_perception(_screen(["Welcome - Visual Studio Code"])[0]),
            make_renderer=_factory(),
            read_window=_reader(),
            project_root=PROJECT_ROOT,
        )


def test_the_live_target_is_revalidated_before_the_run(candidate) -> None:
    """A window that closed or updated between binding and launch aborts."""
    from ghostcursor.devtools.candidate_acceptance import accept_candidate

    graph = _load(candidate)
    target = bind_candidate_target(graph, windows=[_window()], project_root=PROJECT_ROOT)
    workflow = candidate_workflow(
        graph, "Open a folder in VS Code", target, project_root=PROJECT_ROOT
    )
    with pytest.raises(WorkflowUnavailable):
        accept_candidate(
            graph,
            workflow,
            start_perception=_perception(_screen(["Welcome - Visual Studio Code"])[0]),
            make_renderer=_factory(),
            read_window=_reader(missing=True),
            project_root=PROJECT_ROOT,
        )


def test_nothing_runs_when_the_rehash_or_revalidation_fails(candidate) -> None:
    """Order matters: neither failure may reach the executor.

    A run that started and then aborted has already put an overlay on the
    user's screen and already begun producing observations a record could be
    built from.
    """
    from ghostcursor.devtools.candidate_acceptance import accept_candidate

    graph = _load(candidate)
    target = bind_candidate_target(graph, windows=[_window()], project_root=PROJECT_ROOT)
    workflow = candidate_workflow(
        graph, "Open a folder in VS Code", target, project_root=PROJECT_ROOT
    )
    started = []

    def _observe():
        raise AssertionError("the executor ran despite a failed precondition")

    candidate["paths"]["pack"].write_bytes(
        candidate["paths"]["pack"].read_bytes() + b"\n"
    )
    with pytest.raises(CandidateRejected):
        accept_candidate(
            graph,
            workflow,
            start_perception=_perception(_observe, started=started),
            make_renderer=_factory(),
            read_window=_reader(),
            project_root=PROJECT_ROOT,
        )
    assert started == [], "perception started before the gates passed"


def test_a_preparation_record_names_itself_as_non_evidence(candidate) -> None:
    """It proves the graph resolves and nothing else.

    A record whose status depends on the reader knowing which function produced
    it will eventually be cited by someone who does not.
    """
    from ghostcursor.devtools.candidate_acceptance import preparation_record

    graph = _load(candidate)
    target = bind_candidate_target(graph, windows=[_window()], project_root=PROJECT_ROOT)
    payload = json.loads(preparation_record(graph, target).to_json())

    assert payload["record_kind"] == "preparation"
    assert payload["is_acceptance_evidence"] is False
    assert "outcome" not in payload
    assert "grounding_provenance" not in payload


def test_a_run_record_names_all_three_digests_and_the_identity(candidate) -> None:
    _graph, record = _accept(
        candidate,
        screen=_screen(
            [
                "Welcome - Visual Studio Code",
                "Welcome - Visual Studio Code",
                "demo - Visual Studio Code",
            ]
        ),
    )
    payload = json.loads(record.to_json())

    assert payload["record_kind"] == "run"
    assert payload["is_acceptance_evidence"] is True
    assert set(payload["digests"]) == {"pack", "intent", "recipe"}
    assert payload["application_identity"] == {
        "kind": "executable_version",
        "value": "1.134.0",
    }
    assert payload["target"]["executable"] == "code.exe"
    assert payload["outcome"] == "passed"
    assert payload["grounding_provenance"] == ["uia"]
    assert payload["grounded_by_uia_only"] is True


def test_the_record_is_the_durable_reference_not_a_log_path(candidate) -> None:
    """Evidence that names an uncommitted file names nothing (D034)."""
    _graph, record = _accept(
        candidate,
        screen=_screen(
            [
                "Welcome - Visual Studio Code",
                "Welcome - Visual Studio Code",
                "demo - Visual Studio Code",
            ]
        ),
    )
    assert ".artifacts" not in record.to_json()


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
    """The harness's explicit-path options must have no production counterpart.

    Checked by building the real parser and reading its options. An earlier
    version grepped run.py's source, which meant a docstring mentioning the
    word "candidate" failed the test while a genuine `--candidate` flag added
    beside an existing mention would have passed it -- a check keyed on prose
    rather than on behaviour.
    """
    import argparse
    from unittest import mock

    import ghostcursor.run as run

    built = []

    def _capture(self, *args, **kwargs):
        built.append(self)
        raise SystemExit(0)

    with mock.patch.object(argparse.ArgumentParser, "parse_args", _capture):
        with pytest.raises(SystemExit):
            run.main()

    assert built, "run.main() built no parser"
    options = {action.dest for action in built[0]._actions}
    assert not any("candidate" in name for name in options), sorted(options)
    assert not any("pack" in name for name in options)
    assert not any("sha256" in name for name in options)
    assert "recipe" in options, "the v1 recipe path is still present until Task 9"


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
            "--prepare-only",
        ],
        project_root=PROJECT_ROOT,
        list_windows=lambda: [_window()],
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["record_kind"] == "preparation"
    assert payload["is_acceptance_evidence"] is False
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


def test_a_same_byte_symlink_swapped_in_after_loading_is_refused(
    candidate, tmp_path
) -> None:
    """The rehash could not see this; the full reload can.

    Comparing digests at the resolved path checks the BYTES and nothing else.
    An artifact replaced by a symlink to identical bytes has the same digest
    and violates the trusted-artifact boundary outright -- containment,
    symlink refusal, schema, and cross-file agreement all went unchecked
    because none of them were re-run.
    """
    from ghostcursor.devtools.candidate_acceptance import revalidate_candidate

    graph = _load(candidate)
    recipe = candidate["paths"]["recipe"]
    identical = tmp_path / "identical.json"
    identical.write_bytes(recipe.read_bytes())

    recipe.unlink()
    try:
        recipe.symlink_to(identical)
    except (OSError, NotImplementedError):
        pytest.skip("this environment cannot create symlinks")

    assert (
        hashlib.sha256(recipe.read_bytes()).hexdigest()
        == candidate["digests"]["recipe"]
    ), "the bytes are identical, so a digest-only check cannot see this"

    with pytest.raises(CandidateRejected):
        revalidate_candidate(graph)


def test_an_artifact_that_now_resolves_outside_the_root_is_refused(
    candidate, tmp_path
) -> None:
    """Containment is re-checked, not assumed to still hold."""
    from ghostcursor.devtools.candidate_acceptance import revalidate_candidate

    graph = _load(candidate)
    outside = tmp_path / "outside"
    outside.mkdir()
    moved = outside / "recipe.json"
    moved.write_bytes(candidate["paths"]["recipe"].read_bytes())

    candidate["paths"]["recipe"].unlink()
    try:
        candidate["paths"]["recipe"].symlink_to(moved)
    except (OSError, NotImplementedError):
        pytest.skip("this environment cannot create symlinks")

    with pytest.raises(CandidateRejected):
        revalidate_candidate(graph)


def test_an_unchanged_candidate_revalidates(candidate) -> None:
    from ghostcursor.devtools.candidate_acceptance import revalidate_candidate

    graph = _load(candidate)
    reloaded = revalidate_candidate(graph)
    assert reloaded.digests == graph.digests


# ---------------------------------------------------------------------------
# Live-path architecture
# ---------------------------------------------------------------------------


def test_the_executor_never_observes_on_its_own_thread() -> None:
    """Perception belongs on the worker (D021).

    A "Not Responding" target blocks one UIA walk for 41 seconds measured, and
    this loop is what polls ESC and pumps messages -- so a walk performed here
    is 41 seconds in which the user cannot dismiss a window covering their
    whole screen. `observe()` must READ a published slot, never take one.
    """
    import ast

    source = (
        PROJECT_ROOT / "ghostcursor" / "reasoning" / "compiled_tour.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]

    walking = {"pywinauto", "comtypes", "win32gui"}
    assert not any(name.split(".")[0] in walking for name in imported), imported
    assert "Desktop" not in source
    assert "control_type_walk" not in source
    assert "provider_query_for" not in source


#: The only definitions in `compiled.py` that may touch a window API. Everything
#: they build runs on the perception worker; everything else in the module runs
#: on the reasoning tick, which polls ESC and pumps messages.
WORKER_SIDE = {"live_walk", "compiled_plan_runner", "compiled_perception_service"}

WINDOW_APIS = {"win32gui", "win32api", "Desktop", "pywinauto", "comtypes"}


#: The only definitions in `compiled.py` that may touch a window API. Everything
#: they build runs on the perception worker; everything else in the module runs
#: on the reasoning tick, which polls ESC and pumps messages.
WORKER_SIDE = {"live_walk", "compiled_plan_runner", "compiled_perception_service"}

WINDOW_APIS = {"win32gui", "win32api", "Desktop", "pywinauto", "comtypes"}


def window_api_offenders(source: str, allowlist: set) -> list:
    """Every window-API reference outside `allowlist`, in one module's source.

    ONE detector, shared by the real-source assertion and by the synthetic
    near-misses below. Two copies would let a weakening survive twice: the real
    module happens to satisfy the weakened copy, and the near-miss cases
    exercise the untouched one.

    Four import spellings reach the same API and each needs its own branch --
    `win32gui.GetWindowText(...)`, `import win32gui as w` then `w.…`,
    `from win32gui import GetWindowText`, and a bare name already in scope.
    """
    import ast

    offenders = []
    for node in ast.parse(source).body:
        if not isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            continue
        if node.name in allowlist:
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id in WINDOW_APIS:
                offenders.append((node.name, child.id, child.lineno))
            elif isinstance(child, ast.Attribute) and child.attr in WINDOW_APIS:
                offenders.append((node.name, child.attr, child.lineno))
            elif isinstance(child, ast.Import):
                offenders += [
                    (node.name, alias.name, child.lineno)
                    for alias in child.names
                    if alias.name.split(".")[0] in WINDOW_APIS
                ]
            elif isinstance(child, ast.ImportFrom) and child.module:
                if child.module.split(".")[0] in WINDOW_APIS:
                    offenders.append((node.name, child.module, child.lineno))
    return offenders


def test_only_the_worker_side_of_the_composition_touches_a_window_api() -> None:
    """A reader BUILT on the control side is the bypass a thread test can miss.

    `test_the_composed_stack_never_walks_on_the_calling_thread` observes the
    injected walk and title doubles, so it catches the control thread calling
    *those*. It cannot see a fresh `win32gui` reader created inside
    `build_compiled_perception` and closed over by the observation source --
    the doubles are simply never called, and the assertion passes while the
    control thread reads a cross-process window on every tick.

    `GetWindowText` is documented as not sending `WM_GETTEXT` across processes,
    so such a read may well be safe. It has not been measured here, this
    module's own plan-runner docstring says the opposite, and the thread that
    would pay for a wrong answer is the one holding the user's only escape from
    a full-screen overlay. Measure it before moving it, not after.
    """
    source = (
        PROJECT_ROOT / "ghostcursor" / "perception" / "compiled.py"
    ).read_text(encoding="utf-8")
    assert not window_api_offenders(source, WORKER_SIDE)


@pytest.mark.parametrize(
    "body,flagged",
    [
        ("    return snapshot.title", False),
        # The four spellings that reach the same API.
        ("    import win32gui\n    return win32gui.GetWindowText(h)", True),
        ("    import win32gui as w\n    return w.GetWindowText(h)", True),
        ("    from win32gui import GetWindowText\n    return GetWindowText(h)", True),
        ("    return Desktop(backend='uia').window(handle=h)", True),
        # Reached through a module this package DOES legitimately import, so
        # the bare name is innocent and only the attribute gives it away.
        ("    return uia.Desktop(backend='uia')", True),
        # A dotted module is judged by its root package.
        ("    from pywinauto.controls import uiawrapper\n    return uiawrapper", True),
        # A name or module that merely CONTAINS one is not one.
        ("    return win32gui_free_title(h)", False),
        ("    import win32gui_shim\n    return win32gui_shim.read(h)", False),
        ("    from win32gui_shim import read\n    return read(h)", False),
    ],
)
def test_the_window_api_guard_catches_every_import_spelling(body, flagged) -> None:
    """Mutation-verify the detector ITSELF (D018).

    Runs `window_api_offenders()` -- the same function the real-source
    assertion runs -- over synthetic near-misses, one per branch. Without
    these, three of the four branches are unexercised: the real module reaches
    `win32gui` through an attribute, so dropping import handling entirely
    leaves the real assertion green.
    """
    for source in (
        f"def observe(h):\n{body}\n",
        # The observation source is a CLASS. A function-only scan would walk
        # straight past the one definition this guard exists to cover.
        f"class CompiledObservationSource:\n    def __call__(self, h):\n"
        + "".join(f"    {line}\n" for line in body.splitlines()),
    ):
        assert bool(window_api_offenders(source, set())) is flagged, source


def test_the_worker_side_allowlist_names_only_definitions_that_exist() -> None:
    """An allowlist entry that matches nothing exempts nothing, silently.

    A rename would otherwise leave the guard passing over a definition it no
    longer covers, or -- worse -- leave a stale name behind that a future
    control-side function could be given.
    """
    import ast

    source = (
        PROJECT_ROOT / "ghostcursor" / "perception" / "compiled.py"
    ).read_text(encoding="utf-8")
    defined = {
        node.name
        for node in ast.parse(source).body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    assert WORKER_SIDE <= defined, sorted(WORKER_SIDE - defined)


def test_an_unpublished_slot_is_waited_through_not_blocked_on(candidate) -> None:
    """`None` means "nothing published yet", and the loop stays responsive.

    The deadline keeps running and the abort signal keeps being polled, which
    is the whole reason the read is non-blocking.
    """
    from ghostcursor.devtools.candidate_acceptance import accept_candidate

    graph = _load(candidate)
    target = bind_candidate_target(graph, windows=[_window()], project_root=PROJECT_ROOT)
    workflow = candidate_workflow(
        graph, "Open a folder in VS Code", target, project_root=PROJECT_ROOT
    )
    pumped = []
    read, sleep = _clock()

    record = accept_candidate(
        graph,
        workflow,
        start_perception=_perception(lambda: None),
        make_renderer=_factory(),
        read_window=_reader(),
        project_root=PROJECT_ROOT,
        clock=read,
        sleeper=sleep,
        seconds=5.0,
        pump=lambda: pumped.append(True),
    )
    assert record.outcome is RunOutcome.TIMED_OUT
    assert "no observation published" in record.detail
    assert pumped, "the loop stopped pumping while waiting for an observation"


def test_the_abort_signal_is_polled_before_the_first_observation(candidate) -> None:
    from ghostcursor.reasoning.compiled_tour import execute_compiled_workflow

    graph = _load(candidate)
    target = bind_candidate_target(graph, windows=[_window()], project_root=PROJECT_ROOT)
    workflow = candidate_workflow(
        graph, "Open a folder in VS Code", target, project_root=PROJECT_ROOT
    )
    read, sleep = _clock()
    result = execute_compiled_workflow(
        workflow,
        observe=lambda: None,
        renderer=_Renderer(),
        clock=read,
        sleeper=sleep,
        seconds=600.0,
        should_abort=lambda: True,
    )
    assert result.outcome is RunOutcome.ABORTED


def test_the_overlay_is_created_only_after_both_gates_pass(candidate) -> None:
    """Python evaluates arguments before the call.

    Passing a constructed renderer meant the overlay already covered the
    user's screen by the time `accept_candidate()` could refuse the run. It
    takes a factory, and the factory is called after the reload and the
    live-target check.
    """
    from ghostcursor.devtools.candidate_acceptance import accept_candidate

    graph = _load(candidate)
    target = bind_candidate_target(graph, windows=[_window()], project_root=PROJECT_ROOT)
    workflow = candidate_workflow(
        graph, "Open a folder in VS Code", target, project_root=PROJECT_ROOT
    )
    factory = _factory()

    candidate["paths"]["recipe"].write_bytes(
        candidate["paths"]["recipe"].read_bytes() + b"\n"
    )
    with pytest.raises(CandidateRejected):
        accept_candidate(
            graph,
            workflow,
            start_perception=_perception(_screen(["Welcome - Visual Studio Code"])[0]),
            make_renderer=factory,
            read_window=_reader(),
            project_root=PROJECT_ROOT,
        )
    assert factory.renderer.created is False, "the overlay was created anyway"


def test_the_overlay_is_disposed_on_every_outcome(candidate) -> None:
    """Pass, fail, timeout, abort, exception.

    An overlay is full-screen, topmost, click-through and has no title bar, so
    one left behind is one the user cannot close.
    """
    for screen, seconds in (
        (
            _screen(
                [
                    "Welcome - Visual Studio Code",
                    "Welcome - Visual Studio Code",
                    "demo - Visual Studio Code",
                ]
            ),
            60.0,
        ),
        (_screen(["Welcome - Visual Studio Code"], present=False), 600.0),
        (_screen(["Welcome - Visual Studio Code"]), 5.0),
    ):
        factory = _factory()
        graph = _load(candidate)
        target = bind_candidate_target(
            graph, windows=[_window()], project_root=PROJECT_ROOT
        )
        workflow = candidate_workflow(
            graph, r"Open C:\Projects\Demo in VS Code", target,
            project_root=PROJECT_ROOT,
        )
        from ghostcursor.devtools.candidate_acceptance import accept_candidate

        observe, publish = screen
        read, sleep = _clock()
        accept_candidate(
            graph,
            workflow,
            start_perception=_perception(observe),
            make_renderer=factory,
            read_window=_reader(),
            project_root=PROJECT_ROOT,
            clock=read,
            sleeper=lambda s: (sleep(s), publish()),
            seconds=seconds,
        )
        assert factory.disposed, "the overlay outlived the run"


def test_the_overlay_is_disposed_when_the_executor_raises(candidate) -> None:
    from ghostcursor.devtools.candidate_acceptance import accept_candidate

    graph = _load(candidate)
    target = bind_candidate_target(graph, windows=[_window()], project_root=PROJECT_ROOT)
    workflow = candidate_workflow(
        graph, "Open a folder in VS Code", target, project_root=PROJECT_ROOT
    )
    factory = _factory()

    def _boom():
        raise RuntimeError("perception exploded")

    with pytest.raises(RuntimeError):
        accept_candidate(
            graph,
            workflow,
            start_perception=_perception(_boom),
            make_renderer=factory,
            read_window=_reader(),
            project_root=PROJECT_ROOT,
        )
    assert factory.disposed, "an exception left the overlay on screen"


def test_the_provider_query_is_findall_not_a_filtered_walk() -> None:
    """The measured Step 0 contract.

    A descendant walk with a Python name filter pays the traversal this
    project narrowed away from and throws away the provider's own cardinality
    answer -- which is the only thing that makes `exactly_one` provable.
    """
    import ast

    source = (PROJECT_ROOT / "ghostcursor" / "perception" / "uia.py").read_text(
        encoding="utf-8"
    )
    body = source.split("def provider_query_for(")[1].split("\ndef ")[0]
    assert "FindAll" in body
    assert "descendants(" not in body, "provider_query_for is walking, not querying"
    assert "CreatePropertyCondition" in body
    ast.parse(source)


@pytest.mark.parametrize("artifact", ["pack", "intent", "recipe"])
def test_every_artifact_is_revalidated_not_just_the_recipe(
    candidate, artifact
) -> None:
    """All three, or the ones left out can be swapped after review.

    A revalidation that only covered the recipe would let an edited pack --
    which decides the executable filter, the aliases, and the version identity
    strategy -- reach a run under evidence naming the reviewed digest.
    """
    from ghostcursor.devtools.candidate_acceptance import revalidate_candidate

    graph = _load(candidate)
    path = candidate["paths"][artifact]
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(CandidateRejected):
        revalidate_candidate(graph)


def test_the_worker_is_stopped_when_the_renderer_cannot_be_built(candidate) -> None:
    """Registered teardown, not two statements in one `finally`.

    A `make_renderer()` that raises left the worker walking UIA against the
    user's application forever, because the only `stop` was on a line the
    exception skipped.
    """
    from ghostcursor.devtools.candidate_acceptance import accept_candidate

    graph = _load(candidate)
    target = bind_candidate_target(graph, windows=[_window()], project_root=PROJECT_ROOT)
    workflow = candidate_workflow(
        graph, "Open a folder in VS Code", target, project_root=PROJECT_ROOT
    )
    perception = _perception(_screen(["Welcome - Visual Studio Code"])[0])

    def _explode():
        raise RuntimeError("no overlay today")

    with pytest.raises(RuntimeError):
        accept_candidate(
            graph,
            workflow,
            start_perception=perception,
            make_renderer=_explode,
            read_window=_reader(),
            project_root=PROJECT_ROOT,
        )
    assert perception.stopped, "the worker outlived a failed renderer build"


def test_the_worker_is_stopped_when_disposing_the_overlay_raises(candidate) -> None:
    """Teardown order must not let one failure skip another.

    `dispose()` and `stop_perception()` as two statements in one `finally`
    meant a raising dispose skipped the stop entirely.
    """
    from ghostcursor.devtools.candidate_acceptance import accept_candidate

    graph = _load(candidate)
    target = bind_candidate_target(graph, windows=[_window()], project_root=PROJECT_ROOT)
    workflow = candidate_workflow(
        graph, r"Open C:\Projects\Demo in VS Code", target, project_root=PROJECT_ROOT
    )
    perception = _perception(_screen(["Welcome - Visual Studio Code"])[0])

    def _bad_factory():
        def _dispose():
            raise RuntimeError("the overlay refused to close")

        return _Renderer(), _dispose

    read, sleep = _clock()
    with pytest.raises(RuntimeError):
        accept_candidate(
            graph,
            workflow,
            start_perception=perception,
            make_renderer=_bad_factory,
            read_window=_reader(),
            project_root=PROJECT_ROOT,
            clock=read,
            sleeper=sleep,
            seconds=2.0,
        )
    assert perception.stopped, "a raising dispose skipped the worker shutdown"
def test_the_record_carries_the_executors_timing_verbatim(candidate) -> None:
    """The marks are evidence, and evidence that stops at the executor is none.

    `record_for` is the only thing that builds a `RunRecord`, so a timing the
    executor measured and the record dropped would be measured nowhere a
    reviewer can reach.
    """
    from ghostcursor.devtools.candidate_acceptance import record_for
    from ghostcursor.reasoning.compiled_tour import (
        GroundingProvenance,
        RunOutcome,
        TourResult,
    )

    graph = _load(candidate)
    target = bind_candidate_target(
        graph, windows=[_window()], project_root=PROJECT_ROOT
    )
    result = TourResult(
        outcome=RunOutcome.TIMED_OUT,
        provenance=(GroundingProvenance.UIA,),
        steps_completed=0,
        steps_total=1,
        detail="no terminal state within 90s",
        timing={"first_observation_s": 0.5, "first_hint_s": 1.25, "ended_s": 90.0},
    )

    record = record_for(graph, target, result)
    assert record.timing == {
        "first_observation_s": 0.5,
        "first_hint_s": 1.25,
        "ended_s": 90.0,
    }

    payload = json.loads(record.to_json())
    assert payload["timing"] == {
        "ended_s": 90.0,
        "first_hint_s": 1.25,
        "first_observation_s": 0.5,
    }


def test_a_run_with_no_marks_still_carries_a_timing_object(candidate) -> None:
    """An empty object reads as "nothing happened"; a missing key reads as
    "this harness does not record timing", and a reader cannot tell which
    failure they are looking at."""
    from ghostcursor.devtools.candidate_acceptance import record_for
    from ghostcursor.reasoning.compiled_tour import RunOutcome, TourResult

    graph = _load(candidate)
    target = bind_candidate_target(
        graph, windows=[_window()], project_root=PROJECT_ROOT
    )
    record = record_for(
        graph,
        target,
        TourResult(
            outcome=RunOutcome.ABORTED,
            provenance=(),
            steps_completed=0,
            steps_total=1,
        ),
    )
    assert json.loads(record.to_json())["timing"] == {}
