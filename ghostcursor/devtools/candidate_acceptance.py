"""Exercise quarantined candidate bytes before they gain any authority.

D070 requires acceptance evidence committed *before* installation and
activation, which means a human has to be able to run bytes that nothing yet
trusts. That is what this is for, and the shape of it is what keeps it from
becoming a second way in:

* **exactly one graph, named by full digest.** A pack path, an intent path, a
  recipe path, and a SHA-256 for each. No scanning, no globbing, no directory
  input, no filename convention, no "there is only one recipe here so it must
  be the one" fallback. Every one of those is how a candidate could be run
  while a different candidate was the one reviewed.
* **quarantine is enforced, not assumed.** The candidate root must be outside
  `ghostcursor/packs/`. Merely committing a candidate must not make it
  discoverable, and pointing this at the trusted root would make the harness a
  way to run installed artifacts under acceptance framing.
* **it cannot activate anything.** There is no code path here that writes
  `activation.json`. Acceptance produces a run record; installation and the
  activation swap are separate, later, human steps.
* **identity is resolved, never supplied.** `--expect-app-identity` asserts
  equality against what the pack's own D073 resolver returns. An operator may
  state what they believe they are testing; they may not tell the harness what
  it is testing.
* **no second compiler.** After verification this hands off to
  `compile_recipe()` and `CompiledWorkflow`, the same objects production uses.
  A parallel implementation would let acceptance pass against semantics
  production does not have.

Reachability is asserted by test, not left to convention: nothing in
`ghostcursor/run.py`'s parser, planning, or Ask may import this module.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

from ghostcursor.packs.activation import (
    AdoptionRecord,
    IntentAvailability,
    VerifiedCatalog,
    VerifiedIntent,
    VerifiedPack,
)
from ghostcursor.packs.compile import CompiledRecipe, compile_recipe
from ghostcursor.reasoning.compiled_tour import (
    GroundingProvenance,
    RunOutcome,
    TourResult,
    execute_compiled_workflow,
)
from ghostcursor.packs.trusted import (
    ArtifactRef,
    ArtifactSchema,
    LoadedArtifact,
    load_trusted_artifact,
)
from ghostcursor.packs.workflow import (
    AppSnapshot,
    TargetContext,
    WindowCandidate,
    WorkflowUnavailable,
    live_window_reader,
    resolve_target,
)

#: Installed artifacts live here. A candidate that resolves inside it is not a
#: candidate -- it is something already installed, and running it through an
#: acceptance harness would produce evidence that says "quarantined bytes were
#: tested" about bytes that were never quarantined.
TRUSTED_PACK_ROOT = "ghostcursor/packs"


class CandidateRejected(Exception):
    """The named candidate graph cannot be accepted as given."""


@dataclass(frozen=True)
class CandidateRequest:
    """Exactly how a candidate was named, kept so it can be named again.

    Revalidation repeats the ORIGINAL request rather than re-reading whatever
    now sits at the resolved paths. Re-reading a path checks the bytes and
    nothing else -- containment, symlinks, schema, and cross-file agreement
    all went unchecked, so a resolved path replaced by a same-byte symlink
    passed while violating the trusted-artifact boundary outright.
    """

    root: Path
    pack_path: Path
    pack_sha256: str
    intent_path: Path
    intent_sha256: str
    recipe_path: Path
    recipe_sha256: str
    project_root: Path


@dataclass(frozen=True)
class CandidateGraph:
    """One explicitly named pack + intent + recipe, all digest-verified."""

    root: Path
    pack: LoadedArtifact
    intent: LoadedArtifact
    recipe: LoadedArtifact
    compiled: CompiledRecipe
    request: CandidateRequest

    @property
    def digests(self) -> Mapping[str, str]:
        return {
            "pack": self.pack.sha256,
            "intent": self.intent.sha256,
            "recipe": self.recipe.sha256,
        }


@dataclass(frozen=True)
class PreparationRecord:
    """A candidate was loaded and bound. **This is not acceptance evidence.**

    Useful for checking that a graph resolves and finds its window before
    anyone stands in front of a screen for two minutes. It says nothing about
    whether the workflow works, so it carries no outcome and no provenance,
    and it names itself as non-evidence in its own payload -- a record whose
    status depends on the reader knowing which function produced it is one
    that will eventually be cited by someone who does not.
    """

    pack_id: str
    intent_id: str
    digests: Mapping[str, str]
    application_identity_kind: str
    application_identity_value: str
    target_hwnd: int
    target_title: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "record_kind": "preparation",
                "is_acceptance_evidence": False,
                "pack_id": self.pack_id,
                "intent_id": self.intent_id,
                "digests": dict(self.digests),
                "application_identity": {
                    "kind": self.application_identity_kind,
                    "value": self.application_identity_value,
                },
                "target": {"hwnd": self.target_hwnd, "title": self.target_title},
            },
            indent=2,
            sort_keys=True,
        )


@dataclass(frozen=True)
class RunRecord:
    """What one acceptance RUN is allowed to claim.

    Constructed only by `record_for()`, and only from a `TourResult` the
    executor returned. Nothing here is a caller-supplied string: a record that
    could be told its own outcome can say "passed" with no tour having
    happened, which makes it worthless as evidence however carefully the rest
    of the harness is bounded.

    Raw logs stay under `.artifacts/` and never become the durable reference --
    an ignored file cannot be cited, and evidence naming an uncommitted file
    names nothing (D034).
    """

    pack_id: str
    intent_id: str
    digests: Mapping[str, str]
    application_identity_kind: str
    application_identity_value: str
    target_hwnd: int
    target_title: str
    target_executable: str
    outcome: RunOutcome
    grounding_provenance: tuple[GroundingProvenance, ...]
    steps_completed: int
    steps_total: int
    detail: str = ""
    #: Landmarks in seconds from the run's start, straight from the executor.
    #: A timeout record that says only "timed out" is what left this
    #: milestone unable to explain an Open Folder failure after the fact.
    timing: Mapping[str, float] = field(default_factory=dict)

    @property
    def grounded_by_uia_only(self) -> bool:
        return bool(self.grounding_provenance) and set(self.grounding_provenance) == {
            GroundingProvenance.UIA
        }

    def to_json(self) -> str:
        return json.dumps(
            {
                "record_kind": "run",
                "is_acceptance_evidence": True,
                "pack_id": self.pack_id,
                "intent_id": self.intent_id,
                "digests": dict(self.digests),
                "application_identity": {
                    "kind": self.application_identity_kind,
                    "value": self.application_identity_value,
                },
                "target": {
                    "hwnd": self.target_hwnd,
                    "title": self.target_title,
                    "executable": self.target_executable,
                },
                "outcome": self.outcome.value,
                "grounding_provenance": [p.value for p in self.grounding_provenance],
                "grounded_by_uia_only": self.grounded_by_uia_only,
                "steps": {
                    "completed": self.steps_completed,
                    "total": self.steps_total,
                },
                "detail": self.detail,
                "timing": {k: round(v, 3) for k, v in sorted(self.timing.items())},
            },
            indent=2,
            sort_keys=True,
        )


# ---------------------------------------------------------------------------
# Loading exactly one named graph
# ---------------------------------------------------------------------------


def _candidate_ref(root: Path, path: Path, sha256: str, label: str) -> ArtifactRef:
    """Turn an explicit file path into a root-relative, digest-bound reference.

    A directory is refused rather than searched. `load_trusted_artifact()` would
    fail on one anyway, but the message it gives describes a missing file, and
    the thing actually being refused here is the idea that the harness picks a
    file at all.
    """
    if not sha256:
        raise CandidateRejected(f"{label} requires an explicit sha256")
    if path.is_dir():
        raise CandidateRejected(
            f"{label} must name one file; the harness never searches a directory"
        )
    try:
        relative = path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        raise CandidateRejected(
            f"{label} must live inside the candidate root {root}"
        ) from None
    return ArtifactRef(path=relative.as_posix(), sha256=sha256)


def _assert_quarantined(root: Path, project_root: Path) -> None:
    resolved = root.resolve()
    trusted = (project_root / TRUSTED_PACK_ROOT).resolve()
    if resolved == trusted or trusted in resolved.parents:
        raise CandidateRejected(
            f"the candidate root {root} is inside the trusted pack root; "
            "quarantined candidates must live outside it"
        )


def load_candidate(
    root: Path,
    *,
    pack_path: Path,
    pack_sha256: str,
    intent_path: Path,
    intent_sha256: str,
    recipe_path: Path,
    recipe_sha256: str,
    project_root: Path,
) -> CandidateGraph:
    """Verify one named candidate graph. Every part is explicit."""
    root = Path(root)
    _assert_quarantined(root, project_root)

    pack = load_trusted_artifact(
        root,
        _candidate_ref(root, Path(pack_path), pack_sha256, "--pack"),
        ArtifactSchema.PACK,
        project_root=project_root,
    )
    intent = load_trusted_artifact(
        root,
        _candidate_ref(root, Path(intent_path), intent_sha256, "--intent"),
        ArtifactSchema.INTENT,
        project_root=project_root,
    )
    recipe = load_trusted_artifact(
        root,
        _candidate_ref(root, Path(recipe_path), recipe_sha256, "--recipe"),
        ArtifactSchema.RECIPE,
        project_root=project_root,
    )

    # Cross-file agreement. Three separately valid artifacts that disagree
    # about which intent they describe are not one graph, and acceptance would
    # then be recorded against a combination nobody assembled deliberately.
    if intent.value["intent_id"] != recipe.value["intent_id"]:
        raise CandidateRejected(
            f"intent artifact names {intent.value['intent_id']!r} but the recipe "
            f"names {recipe.value['intent_id']!r}"
        )
    if pack.value["pack_kind"] != "application":
        raise CandidateRejected(
            "only an application pack can be accepted against a live window"
        )

    return CandidateGraph(
        root=root,
        pack=pack,
        intent=intent,
        recipe=recipe,
        compiled=compile_recipe(recipe.value),
        request=CandidateRequest(
            root=root,
            pack_path=Path(pack_path),
            pack_sha256=pack_sha256,
            intent_path=Path(intent_path),
            intent_sha256=intent_sha256,
            recipe_path=Path(recipe_path),
            recipe_sha256=recipe_sha256,
            project_root=Path(project_root),
        ),
    )


# ---------------------------------------------------------------------------
# Binding the candidate to a live target
# ---------------------------------------------------------------------------


def _as_verified_pack(graph: CandidateGraph) -> VerifiedPack:
    """A pack value shaped for the production resolvers, with no activation.

    The generation and activation digest are deliberately absent-looking
    sentinels: this graph has no activation record, and giving it plausible
    ones would let a candidate be mistaken for something adopted.
    """
    return VerifiedPack(
        pack_id=graph.pack.value["pack_id"],
        directory=graph.root,
        activation_generation=0,
        activation_sha256="",
        pack=graph.pack.ref,
        pack_value=graph.pack.value,
        intents={},
        declared_intents=(graph.intent.value["intent_id"],),
    )


def bind_candidate_target(
    graph: CandidateGraph,
    *,
    windows: Sequence[WindowCandidate],
    project_root: Path,
    target_title_re: str | None = None,
    expected_identity: str | None = None,
) -> TargetContext:
    """Resolve the live target through the production resolver.

    `expected_identity` asserts, it does not supply. The value compared against
    comes from the pack's own declared D073 strategy; the operator's string is
    only allowed to agree with it. An operator who could name the identity
    could accept a workflow against a version they never ran.
    """
    pack = _as_verified_pack(graph)
    target = resolve_target(
        pack,
        list(windows),
        target_title_re=target_title_re,
        project_root=project_root,
    )
    if expected_identity is not None and target.identity.value != expected_identity:
        raise CandidateRejected(
            f"expected application identity {expected_identity!r} but the pack "
            f"resolver reports {target.identity.value!r}"
        )
    return target


def candidate_workflow(
    graph: CandidateGraph,
    goal: str,
    target: TargetContext,
    *,
    project_root: Path,
):
    """Build the SAME `CompiledWorkflow` production would run.

    Acceptance has to exercise production semantics or it certifies something
    else. So this reuses `materialize()` rather than assembling a workflow by
    hand, and constructs the one thing `materialize()` needs that a candidate
    does not have: an adoption record. That record is synthesised HERE, from
    the digests just verified, and is never written anywhere -- it exists for
    the duration of one acceptance run.
    """
    from ghostcursor.packs.workflow import materialize

    intent_id = graph.intent.value["intent_id"]
    adoption = AdoptionRecord(
        adoption_id="candidate",
        recipe=graph.recipe.ref,
        recipe_value=graph.recipe.value,
        accepted_pack=graph.pack.ref,
        accepted_intent=graph.intent.ref,
        accepted_application_identity=target.identity,
        evidence=ArtifactRef(path="docs/evidence/candidate.md", sha256="0" * 64),
        adopted_at="candidate",
        reviewer_id="candidate",
        review_commit="0" * 40,
        supersedes_adoption_id=None,
        supersedes_recipe_sha256=None,
    )
    verified_intent = VerifiedIntent(
        intent_id=intent_id,
        intent=graph.intent.ref,
        intent_value=graph.intent.value,
        availability=IntentAvailability.ACTIVE,
        active_adoption=adoption,
        adoptions={adoption.adoption_id: adoption},
    )
    pack = _as_verified_pack(graph)
    pack = VerifiedPack(
        pack_id=pack.pack_id,
        directory=pack.directory,
        activation_generation=pack.activation_generation,
        activation_sha256=pack.activation_sha256,
        pack=pack.pack,
        pack_value=pack.pack_value,
        intents={intent_id: verified_intent},
        declared_intents=pack.declared_intents,
    )
    catalog = VerifiedCatalog(
        root_valid=True, packs={pack.pack_id: pack}, index_sha256="0" * 64
    )
    return materialize(catalog, pack, verified_intent, goal, target)


def preparation_record(
    graph: CandidateGraph, target: TargetContext
) -> PreparationRecord:
    return PreparationRecord(
        pack_id=graph.pack.value["pack_id"],
        intent_id=graph.intent.value["intent_id"],
        digests=graph.digests,
        application_identity_kind=target.identity.kind,
        application_identity_value=target.identity.value,
        target_hwnd=target.hwnd,
        target_title=target.title,
    )


def record_for(
    graph: CandidateGraph, target: TargetContext, result: TourResult
) -> RunRecord:
    """Assemble the durable record of one acceptance run.

    Takes the executor's `TourResult` and nothing else. There is no parameter
    an operator could use to state an outcome, because an outcome that can be
    stated can be stated falsely, and a record that can be stated falsely is
    not evidence.

    Provenance is not defaulted either: `TourResult` carries what actually
    grounded each step, so a run that grounded nothing reports nothing and a
    run that fell back to OCR says so. An outcome-only record cannot see a
    perception tier going dark, because fallback OCR preserves the outcome
    (D069).
    """
    return RunRecord(
        pack_id=graph.pack.value["pack_id"],
        intent_id=graph.intent.value["intent_id"],
        digests=graph.digests,
        application_identity_kind=target.identity.kind,
        application_identity_value=target.identity.value,
        target_hwnd=target.hwnd,
        target_title=target.title,
        target_executable=target.app.executable_name,
        outcome=result.outcome,
        grounding_provenance=result.provenance,
        steps_completed=result.steps_completed,
        steps_total=result.steps_total,
        detail=result.detail,
        timing=result.timing,
    )


def revalidate_candidate(graph: CandidateGraph) -> CandidateGraph:
    """Re-run the ENTIRE trusted load immediately before launch.

    Not a rehash. Re-reading the resolved paths and comparing digests checks
    the bytes and nothing else: containment, symlink refusal, strict schema,
    and cross-file id agreement all go unchecked, so an artifact replaced by a
    same-byte symlink -- or by a file that now resolves outside the candidate
    root -- passes while violating the boundary the load exists to enforce.

    Repeating `load_candidate()` with the original request is what makes the
    check equal to the one that granted the bytes their standing in the first
    place. Anything less is a weaker gate running later, which is the worst
    possible ordering.

    The returned graph is the freshly verified one. It is discarded unless it
    is byte-identical to the original, but returning it keeps the caller from
    having to decide which of two graphs it now holds.
    """
    request = graph.request
    try:
        reloaded = _reload(request)
    except ValueError as exc:
        # At load time a failure means "this candidate is not loadable". Here
        # it means "the bytes that were reviewed are no longer what is on
        # disk", which is a different fact and deserves to say so.
        raise CandidateRejected(
            f"the candidate no longer verifies since it was loaded: {exc}"
        ) from exc

    # No per-artifact comparison afterwards. `load_candidate()` verifies each
    # artifact against the digest the ORIGINAL request named, so a reload that
    # returns at all has already proved the bytes are the reviewed ones -- and
    # a comparison that cannot fail reads as a safety check while enforcing
    # nothing (D031). The reload is the check.
    return reloaded


def _reload(request: CandidateRequest) -> CandidateGraph:
    return load_candidate(
        request.root,
        pack_path=request.pack_path,
        pack_sha256=request.pack_sha256,
        intent_path=request.intent_path,
        intent_sha256=request.intent_sha256,
        recipe_path=request.recipe_path,
        recipe_sha256=request.recipe_sha256,
        project_root=request.project_root,
    )


def accept_candidate(
    graph: CandidateGraph,
    workflow,
    *,
    start_perception,
    make_renderer,
    make_controls=None,
    read_window,
    project_root: Path,
    clock=None,
    sleeper=None,
    seconds: float = 120.0,
    should_abort=None,
    confirmation_requested=None,
    pump=None,
) -> RunRecord:
    """Run one candidate through the production executor and record the result.

    Ordered deliberately: re-run the full trusted load of the explicit files,
    revalidate the live target, and only then execute. Each step invalidates
    something the one before it cannot see -- an artifact edited or replaced,
    a window that closed or updated, and finally whether the workflow works.

    `execute_compiled_workflow()` is the same executor the production entry
    point calls. Acceptance that ran anything else would certify something
    production does not do.
    """
    from ghostcursor.packs.workflow import validate_live_target

    revalidate_candidate(graph)
    validate_live_target(
        workflow,
        _as_verified_pack(graph),
        workflow.adoption,
        read_window=read_window,
        project_root=project_root,
    )

    # The renderer is built HERE, after both gates, and never passed in
    # already-constructed. Python evaluates arguments before the call, so a
    # caller writing `accept_candidate(..., renderer=_live_renderer())` had
    # already put a full-screen topmost window on the user's screen before
    # this function could refuse the run.
    # Perception starts HERE, after both gates. Starting it earlier means the
    # worker can publish an observation taken while the artifacts were still
    # unverified and the window unchecked -- and the run would then be free to
    # consume it, so the gates would have bounded nothing.
    #
    # `ExitStack`, not two calls in one `finally`. Each teardown is registered
    # the moment its resource exists, so the worker is stopped even when the
    # renderer never got built, and stopping still happens when disposing the
    # overlay raises. Two statements in one `finally` gave neither guarantee:
    # a `make_renderer()` that raised left the worker walking UIA forever, and
    # a `dispose()` that raised skipped the line after it.
    with contextlib.ExitStack() as cleanup:
        observe, on_grounding, stop_perception = start_perception()
        cleanup.callback(stop_perception)

        renderer, dispose = make_renderer()
        cleanup.callback(dispose)

        controls = make_controls() if make_controls is not None else None
        if controls is not None:
            cleanup.callback(controls.dispose)

        def _pump_ui():
            if controls is not None:
                controls.poll()
            elif pump is not None:
                pump()

        def _should_abort():
            requested = should_abort is not None and should_abort()
            return requested or (
                controls is not None and controls.should_abort()
            )

        kwargs = {
            "observe": observe,
            "renderer": renderer,
            "seconds": seconds,
            "pump": _pump_ui,
            "on_grounding": on_grounding,
            "should_abort": _should_abort,
        }
        if clock is not None:
            kwargs["clock"] = clock
        if sleeper is not None:
            kwargs["sleeper"] = sleeper
        if controls is not None:
            kwargs["should_pause"] = controls.should_pause
            kwargs["on_step"] = controls.report_step
        if confirmation_requested is not None:
            kwargs["confirmation_requested"] = confirmation_requested
        result = execute_compiled_workflow(workflow, **kwargs)
    return record_for(graph, workflow.target, result)


# ---------------------------------------------------------------------------
# The developer command
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ghostcursor.devtools.candidate_acceptance",
        description=(
            "Exercise one explicitly named quarantined candidate graph. "
            "Developer instrument: it grants no authority and cannot activate "
            "anything."
        ),
    )
    parser.add_argument("--candidate-root", required=True, type=Path)
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--pack-sha256", required=True)
    parser.add_argument("--intent", required=True, type=Path)
    parser.add_argument("--intent-sha256", required=True)
    parser.add_argument("--recipe", required=True, type=Path)
    parser.add_argument("--recipe-sha256", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument(
        "--expect-app-identity",
        default=None,
        help=(
            "assert the pack resolver reports this identity. It ASSERTS; it "
            "never supplies. A mismatch is a refusal, not an override."
        ),
    )
    parser.add_argument("--target", default=None, help="narrow the title set")
    parser.add_argument(
        "--seconds",
        type=float,
        default=120.0,
        help="how long the run may take before it is recorded as timed out",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help=(
            "load and bind the candidate without running it. Emits a "
            "PREPARATION record, which is explicitly not acceptance evidence."
        ),
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    project_root: Path | None = None,
    list_windows: Callable[[], Sequence[WindowCandidate]] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    project_root = project_root or Path(__file__).resolve().parents[2]

    try:
        graph = load_candidate(
            args.candidate_root,
            pack_path=args.pack,
            pack_sha256=args.pack_sha256,
            intent_path=args.intent,
            intent_sha256=args.intent_sha256,
            recipe_path=args.recipe,
            recipe_sha256=args.recipe_sha256,
            project_root=project_root,
        )
    except (CandidateRejected, ValueError) as exc:
        print(f"candidate rejected: {exc}", file=sys.stderr)
        return 2

    windows = list(list_windows() if list_windows is not None else _live_windows(graph))
    try:
        target = bind_candidate_target(
            graph,
            windows=windows,
            project_root=project_root,
            target_title_re=args.target,
            expected_identity=args.expect_app_identity,
        )
    except (CandidateRejected, WorkflowUnavailable) as exc:
        print(f"no acceptable target: {exc}", file=sys.stderr)
        return 3

    workflow = candidate_workflow(graph, args.goal, target, project_root=project_root)

    if args.prepare_only:
        # A preparation record, and it says so. It proves the graph resolves
        # and finds its window; it proves nothing about the workflow, so it
        # must never be mistaken for the run record acceptance cites.
        print(preparation_record(graph, target).to_json())
        return 0

    import time

    start_perception, ladder, pump = _live_acceptance_seams(workflow, time.monotonic)
    from ghostcursor.run import (
        create_compiled_tour_controls,
        space_confirmation_requested,
    )

    try:
        record = accept_candidate(
            graph,
            workflow,
            start_perception=start_perception,
            make_renderer=_live_renderer_factory(ladder),
            make_controls=create_compiled_tour_controls,
            read_window=live_window_reader(),
            project_root=project_root,
            seconds=args.seconds,
            pump=pump,
            confirmation_requested=lambda: space_confirmation_requested(
                workflow.target.hwnd
            ),
        )
    except (CandidateRejected, WorkflowUnavailable) as exc:
        print(f"run refused: {exc}", file=sys.stderr)
        return 4

    print(record.to_json())
    return 0 if record.outcome is RunOutcome.PASSED else 1


def _live_renderer_factory(ladder):  # pragma: no cover - needs a real desktop
    """A factory, never a renderer.

    Returns `(renderer, dispose)` and creates nothing until called, so the
    overlay cannot come into existence while Python is still evaluating the
    arguments of the call that was going to refuse the run.
    """

    def _make():
        from ghostcursor.overlay import window as overlay_window
        from ghostcursor.reasoning.renderer import OverlayRenderer

        hwnd = overlay_window.create_overlay_window()
        renderer = OverlayRenderer(hwnd, freshness_source=ladder.freshness)

        def _dispose():
            try:
                import win32gui

                win32gui.DestroyWindow(hwnd)
            except Exception:
                pass

        return renderer, _dispose

    return _make


def _live_acceptance_seams(workflow, clock):  # pragma: no cover - real desktop
    """The same composition production uses, started only when asked.

    Acceptance that observed differently from production would certify
    something production does not do -- the same objection that forbids a
    second executor, one layer down. So this returns the production wiring and
    a `start()` the harness calls after its gates, never a running worker.
    """
    from ghostcursor.perception import tier2 as tier2_module
    from ghostcursor.perception.compiled import build_compiled_perception
    from ghostcursor.run import pump_messages

    perception = build_compiled_perception(
        workflow, clock, tier2=tier2_module.build_controller(clock)
    )
    # `perception.start` IS the seam. The harness calls it after its gates,
    # and the composition arms the health grace at that moment rather than at
    # construction -- a slow gate would otherwise spend the whole grace before
    # the worker existed, and its first read would restart something that had
    # never run.
    return perception.start, perception.source.ladder, pump_messages


def _live_windows(graph: CandidateGraph) -> list[WindowCandidate]:  # pragma: no cover
    """The PRODUCTION enumerator, applied to the candidate pack.

    Not a copy. A second enumerator here would let acceptance see a different
    set of candidate windows than production does -- the same objection that
    forbids a second executor one layer up.
    """
    from ghostcursor.packs.workflow import live_windows_for

    return live_windows_for(_as_verified_pack(graph))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
