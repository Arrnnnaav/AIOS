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
import json
import sys
from dataclasses import dataclass
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
class CandidateGraph:
    """One explicitly named pack + intent + recipe, all digest-verified."""

    root: Path
    pack: LoadedArtifact
    intent: LoadedArtifact
    recipe: LoadedArtifact
    compiled: CompiledRecipe

    @property
    def digests(self) -> Mapping[str, str]:
        return {
            "pack": self.pack.sha256,
            "intent": self.intent.sha256,
            "recipe": self.recipe.sha256,
        }


@dataclass(frozen=True)
class RunRecord:
    """What one acceptance attempt is allowed to claim.

    Deliberately small and deliberately explicit about provenance. Raw logs stay
    under `.artifacts/` and never become the durable evidence reference -- an
    ignored file cannot be cited, and evidence that names an uncommitted file
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
    outcome: str
    grounding_provenance: tuple[str, ...]
    notes: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {
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
                "outcome": self.outcome,
                "grounding_provenance": list(self.grounding_provenance),
                "notes": self.notes,
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
    foreground_hwnd: int = 0,
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
        foreground_hwnd=foreground_hwnd,
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


def record_for(
    graph: CandidateGraph,
    target: TargetContext,
    *,
    outcome: str,
    grounding_provenance: Sequence[str],
    notes: str = "",
) -> RunRecord:
    """Assemble the durable record of one acceptance attempt.

    `grounding_provenance` is required rather than defaulted, because an
    Open Folder gate that asserts only completion cannot see a tier going dark:
    fallback OCR preserves the outcome while the preferred tier is gone (D069).
    A record that does not say which tier grounded cannot support the claim the
    evidence needs to make.
    """
    provenance = tuple(grounding_provenance)
    if not provenance:
        raise CandidateRejected(
            "a run record must name the grounding provenance; a completed "
            "outcome alone cannot show which perception tier produced it"
        )
    return RunRecord(
        pack_id=graph.pack.value["pack_id"],
        intent_id=graph.intent.value["intent_id"],
        digests=graph.digests,
        application_identity_kind=target.identity.kind,
        application_identity_value=target.identity.value,
        target_hwnd=target.hwnd,
        target_title=target.title,
        target_executable=target.app.executable_name,
        outcome=outcome,
        grounding_provenance=provenance,
        notes=notes,
    )


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
    print(
        record_for(
            graph,
            target,
            outcome="prepared",
            grounding_provenance=("pending",),
            notes=(
                f"compiled {len(workflow.recipe.steps)} step(s); run the tour "
                "manually and record the observed outcome and provenance"
            ),
        ).to_json()
    )
    return 0


def _live_windows(graph: CandidateGraph) -> list[WindowCandidate]:  # pragma: no cover
    """Enumerate real windows for the candidate pack's executables."""
    import os

    import win32gui
    import win32process

    from ghostcursor.perception.appinfo import _exe_path_for_pid, _version_for

    wanted = {name.casefold() for name in graph.pack.value["executable_names"]}
    found: list[WindowCandidate] = []

    def _collect(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            return
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        exe_path = _exe_path_for_pid(pid)
        if not exe_path:
            return
        name = os.path.basename(exe_path).casefold()
        if name not in wanted:
            return
        kind = "appx" if "WindowsApps" in exe_path else "win32"
        found.append(
            WindowCandidate(
                hwnd=hwnd,
                title=win32gui.GetWindowText(hwnd),
                app=AppSnapshot(
                    executable_name=name,
                    version=_version_for(exe_path, kind),
                    process_id=pid,
                ),
            )
        )

    win32gui.EnumWindows(_collect, None)
    return found


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
