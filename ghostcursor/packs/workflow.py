"""Bind a classified intent to one live application window.

Classification is pure and lives in the matcher: it reads verified intent
artifacts and names an intent. Nothing about it touches the screen. This module
is the second authority stage, and it is where the pure world ends -- an intent
becomes executable only against a real window, owned by a real process, running
an application whose identity exactly equals the one acceptance was recorded
against.

Three things live here because none of the existing modules can own them:
`trusted.py` is the artifact trust boundary, `activation.py` verifies the bound
graph, and `compile.py` is pure by construction (Design section 8). Live target
resolution is none of those, so it gets its own module rather than being
smuggled into a module whose contract says it does not do this.

The whole module fails closed to `KNOWN_INTENT_RECIPE_UNAVAILABLE`. There is no
partial success: a workflow either binds completely -- artifacts, activation,
application identity, window, process -- or it does not bind at all.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from ghostcursor.packs.activation import (
    AdoptionRecord,
    ApplicationIdentity,
    VerifiedCatalog,
    VerifiedIntent,
    VerifiedPack,
)
from ghostcursor.packs.compile import (
    CompiledRecipe,
    GoalReferenceSpec,
    compile_goal_reference,
    compile_recipe,
    derive_goal_reference,
)

#: The one status this module reports. Deliberately an existing status: every
#: failure here means "this intent is known but its recipe cannot run now",
#: which is what that status already says. A new status would have to be
#: handled by every caller to mean the same thing.
KNOWN_INTENT_RECIPE_UNAVAILABLE = "KNOWN_INTENT_RECIPE_UNAVAILABLE"


class WorkflowUnavailable(Exception):
    """This intent cannot be materialized right now.

    Carries a reason for logs and a status for callers. Raised rather than
    returned so a caller cannot accidentally proceed with a half-bound
    workflow -- the same rule `ProviderQueryFault` follows.
    """

    status = KNOWN_INTENT_RECIPE_UNAVAILABLE

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# D073 -- the one application-identity resolver
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AppSnapshot:
    """What the live application reported about itself, as frozen values."""

    executable_name: str
    version: str
    process_id: int


def resolve_application_identity(
    pack: VerifiedPack,
    app: AppSnapshot | None,
    *,
    project_root: Path,
) -> ApplicationIdentity:
    """The single resolver every stage uses (D073).

    Acceptance, planning, pre-launch revalidation, rollback, and drift
    detection all call THIS, selected by the trusted pack's declared strategy.
    One resolver is the point: if acceptance recorded an identity by one rule
    and pre-launch recomputed it by another, the comparison would be between
    two different questions and could never fail honestly.

    An operator may record what this returns; nothing may supply or override
    it.
    """
    declared = pack.pack_value.get("version_identity")
    if not declared:
        raise WorkflowUnavailable(f"pack {pack.pack_id} declares no version identity")

    kind = declared["kind"]
    if kind == "executable_version":
        # The installed application's own release identity. VS Code's shipped
        # UI genuinely changes with this, and the Open Folder degradation is
        # what proved exact equality is required.
        if app is None or not app.version:
            raise WorkflowUnavailable(
                f"pack {pack.pack_id} needs an executable version and none was read"
            )
        return ApplicationIdentity(kind=kind, value=app.version)

    if kind == "content_sha256":
        # A checked-in application's identity is its bytes. Synthetic Export is
        # hosted by python.exe, but the interpreter's patch version is not the
        # demo's release identity: binding to it would invalidate accepted runs
        # after an unrelated Python update while still failing to notice a
        # change to the script those runs actually exercised.
        source = _content_identity_path(project_root, declared["path"])
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        return ApplicationIdentity(kind=kind, value=digest)

    raise WorkflowUnavailable(f"unknown version identity strategy {kind!r}")


def _content_identity_path(project_root: Path, declared: str) -> Path:
    """Resolve a declared content path, refusing everything but a real file.

    The schema already constrains this path to the allowlisted application
    source root. This re-checks containment after resolution, because the
    schema validated a STRING and a symlink turns a contained string into an
    uncontained file at read time.
    """
    root = project_root.resolve()

    # Check each component for a symlink BEFORE resolving, never after.
    # `resolve()` follows links, so a resolved path is never itself a symlink
    # and a check placed after it can never fire -- it reads like a guard and
    # enforces nothing. Walking the components is what actually refuses one.
    candidate = project_root
    for part in PurePosixPath(declared).parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise WorkflowUnavailable("content identity path contains a symlink")

    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        raise WorkflowUnavailable(f"content identity path does not exist: {declared}")
    try:
        resolved.relative_to(root)
    except ValueError:
        raise WorkflowUnavailable("content identity path escapes the project root")
    if not resolved.is_file():
        raise WorkflowUnavailable(f"content identity path is not a file: {declared}")
    return resolved


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WindowCandidate:
    """One live top-level window, as the resolver sees it."""

    hwnd: int
    title: str
    app: AppSnapshot


@dataclass(frozen=True)
class TargetContext:
    """The one window a compiled workflow is bound to.

    The HWND is CAPTURED, never rediscovered by title later. Titles are free
    text: VS Code's changes the moment a folder opens, which is the very event
    Open Folder verifies, so re-finding the window by title mid-run could
    silently move to a different window at exactly the wrong moment.
    """

    hwnd: int
    title: str
    app: AppSnapshot
    identity: ApplicationIdentity


def resolve_target(
    pack: VerifiedPack,
    candidates: Mapping[int, WindowCandidate] | list[WindowCandidate],
    *,
    foreground_hwnd: int = 0,
    target_title_re: str | None = None,
    project_root: Path,
) -> TargetContext:
    """Choose exactly one window, deterministically, or refuse.

    Order is fixed: filter by the pack's verified identity, apply the optional
    user narrowing, then prefer the foreground window if it survived, else
    require exactly one.

    `target_title_re` may only NARROW. It cannot replace the executable check,
    because a title is free text that collides with browser tabs and terminals
    -- a `--target` of `Visual Studio Code` matches a Chrome tab reading about
    VS Code, and pointing a trusted recipe at that is how identity-bounded
    grounding was made mandatory in the first place (D046).
    """
    if pack.pack_value.get("pack_kind") != "application":
        raise WorkflowUnavailable(f"pack {pack.pack_id} matches no window")

    windows = (
        list(candidates.values())
        if isinstance(candidates, Mapping)
        else list(candidates)
    )
    executables = {name.casefold() for name in pack.pack_value["executable_names"]}
    patterns = [re.compile(p) for p in pack.pack_value["title_patterns"]]

    matching = [
        window
        for window in windows
        if window.app.executable_name.casefold() in executables
        and any(pattern.search(window.title) for pattern in patterns)
    ]
    if target_title_re is not None:
        narrowing = re.compile(target_title_re)
        matching = [w for w in matching if narrowing.search(w.title)]

    if not matching:
        raise WorkflowUnavailable(f"no window matches pack {pack.pack_id}")

    chosen = next((w for w in matching if w.hwnd == foreground_hwnd), None)
    if chosen is None:
        if len(matching) > 1:
            titles = ", ".join(repr(w.title) for w in matching)
            raise WorkflowUnavailable(
                f"{len(matching)} windows match pack {pack.pack_id} and none is "
                f"in the foreground: {titles}"
            )
        chosen = matching[0]

    identity = resolve_application_identity(pack, chosen.app, project_root=project_root)
    return TargetContext(
        hwnd=chosen.hwnd, title=chosen.title, app=chosen.app, identity=identity
    )


# ---------------------------------------------------------------------------
# The bound workflow
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompiledWorkflow:
    """Everything one guided tour is allowed to rely on, bound together.

    Replaces the bare `Recipe` that used to travel on a plan result. A recipe
    alone could not say which pack authorized it, which acceptance record it
    ran under, or which window it meant; each of those was recovered later by
    a second lookup that could disagree with the first.

    `recipe.app_id` is gone on purpose. Activation already binds a recipe to
    exactly one pack and intent, so an identity restated inside the artifact
    is a second source that can drift from the binding. The executable filter
    runtime still needs comes from the pack's `executable_names`, which is
    where identity-bounded grounding already lives (D046).
    """

    pack_id: str
    intent_id: str
    goal: str
    recipe: CompiledRecipe
    target: TargetContext
    adoption: AdoptionRecord
    activation_generation: int
    # Every digest a launch is bound to. Revalidation compares against these,
    # so they must be captured at plan time and never recomputed from a file
    # that may already have changed.
    index_sha256: str
    activation_sha256: str
    pack_sha256: str
    intent_sha256: str
    recipe_sha256: str
    evidence_sha256: str
    tier2_capture: str
    executable_names: tuple[str, ...]
    #: The goal reference derived ONCE, per step index. Verification reads it
    #: rather than re-extracting from the goal, so there is one extractor.
    goal_references: Mapping[int, str]

    def goal_reference_for(self, step_index: int) -> str | None:
        return self.goal_references.get(step_index)


def _goal_reference_specs(
    recipe: CompiledRecipe, aliases: Mapping[str, Any]
) -> dict[int, GoalReferenceSpec]:
    specs: dict[int, GoalReferenceSpec] = {}
    for index, step in enumerate(recipe.steps):
        declared = step.verification.args.get("goal_reference")
        if declared is not None:
            specs[index] = compile_goal_reference(declared, aliases)
    return specs


def materialize(
    catalog: VerifiedCatalog,
    pack: VerifiedPack,
    intent: VerifiedIntent,
    goal: str,
    target: TargetContext,
) -> CompiledWorkflow:
    """Turn a classified intent plus a live target into an executable workflow.

    Classification never reaches here on its own: naming an intent is what the
    model is allowed to influence, and it grants nothing. Materialization
    requires an ACTIVE adoption whose recorded application identity exactly
    equals the identity just resolved from the live window -- so a model can
    name an intent all it likes and still get no workflow (D058).
    """
    adoption = intent.active_adoption
    if adoption is None:
        raise WorkflowUnavailable(f"intent {intent.intent_id} has no active adoption")
    if not adoption.accepts_identity(target.identity):
        accepted = adoption.accepted_application_identity
        raise WorkflowUnavailable(
            f"intent {intent.intent_id} was accepted against "
            f"{accepted.kind}={accepted.value!r}, live target is "
            f"{target.identity.kind}={target.identity.value!r}"
        )
    if catalog.index_sha256 is None:
        raise WorkflowUnavailable("catalog carries no index digest")

    recipe = compile_recipe(adoption.recipe_value)
    aliases = pack.pack_value.get("aliases", {})
    references = {
        index: derive_goal_reference(spec, goal)
        for index, spec in _goal_reference_specs(recipe, aliases).items()
    }

    return CompiledWorkflow(
        pack_id=pack.pack_id,
        intent_id=intent.intent_id,
        goal=goal,
        recipe=recipe,
        target=target,
        adoption=adoption,
        activation_generation=pack.activation_generation,
        index_sha256=catalog.index_sha256,
        activation_sha256=pack.activation_sha256,
        pack_sha256=pack.pack.sha256,
        intent_sha256=intent.intent.sha256,
        recipe_sha256=adoption.recipe.sha256,
        evidence_sha256=adoption.evidence.sha256,
        tier2_capture=pack.pack_value["tier2_capture"],
        executable_names=tuple(pack.pack_value["executable_names"]),
        goal_references=dict(references),
    )


# ---------------------------------------------------------------------------
# Pre-launch revalidation
# ---------------------------------------------------------------------------


def revalidate(
    workflow: CompiledWorkflow,
    *,
    reload_catalog: Callable[[], VerifiedCatalog],
    window_still_valid: Callable[[CompiledWorkflow], bool],
    project_root: Path,
) -> None:
    """Re-verify every bound input immediately before a tour launches.

    Called AFTER planning and BEFORE overlay creation. Everything a plan bound
    is re-read from disk and compared; on any difference this raises and the
    launch aborts. Runtime never substitutes new bytes transparently and never
    falls back to the old in-memory workflow -- both would run something the
    operator did not accept, one silently newer and one silently withdrawn.

    **The generation is not content binding.** It is a counter, and a counter
    can sit still while the file it labels changes: an edited digest, a
    rewritten acceptance record, a removed entry. Revalidating it alone would
    let activation metadata change under a running plan. The digests bind
    content; the generation is a cheap ordering hint kept beside them.
    """
    catalog = reload_catalog()

    if catalog.index_sha256 != workflow.index_sha256:
        raise WorkflowUnavailable("packs/index.json changed since planning")

    pack = catalog.packs.get(workflow.pack_id)
    if pack is None:
        # A withdrawn pack must abort the launch, not fail somewhere later
        # with a confusing perception error.
        raise WorkflowUnavailable(f"pack {workflow.pack_id} is no longer indexed")

    if pack.activation_sha256 != workflow.activation_sha256:
        raise WorkflowUnavailable("activation.json changed since planning")
    if pack.activation_generation != workflow.activation_generation:
        raise WorkflowUnavailable("activation generation changed since planning")
    if pack.pack.sha256 != workflow.pack_sha256:
        raise WorkflowUnavailable("pack artifact changed since planning")

    intent = pack.intents.get(workflow.intent_id)
    if intent is None:
        raise WorkflowUnavailable(f"intent {workflow.intent_id} is no longer indexed")
    if intent.intent.sha256 != workflow.intent_sha256:
        raise WorkflowUnavailable("intent artifact changed since planning")

    adoption = intent.active_adoption
    if adoption is None:
        raise WorkflowUnavailable(f"intent {workflow.intent_id} is no longer adopted")
    if adoption.recipe.sha256 != workflow.recipe_sha256:
        raise WorkflowUnavailable("recipe artifact changed since planning")
    if adoption.evidence.sha256 != workflow.evidence_sha256:
        raise WorkflowUnavailable("acceptance evidence changed since planning")

    # The live application identity, through the SAME resolver acceptance used.
    current = resolve_application_identity(
        pack, workflow.target.app, project_root=project_root
    )
    if current != workflow.target.identity:
        raise WorkflowUnavailable(
            f"application identity changed from {workflow.target.identity.value!r} "
            f"to {current.value!r} since planning"
        )
    if not adoption.accepts_identity(current):
        raise WorkflowUnavailable("live application identity is no longer accepted")

    # The window itself: still there, still the same process and executable,
    # still satisfying the pack's title identity.
    if not window_still_valid(workflow):
        raise WorkflowUnavailable("the bound window is gone or is no longer the target")
