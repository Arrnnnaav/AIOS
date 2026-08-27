"""Verify the trusted activation graph and expose an immutable catalog.

`packs/index.json` is the discovery commit point; each intent's
`active_adoption_id` is that intent's execution commit point. Nothing here
imports the planner, the reasoning loop, UIA, or any input-synthesis API: this
module reads committed bytes and decides what may authorize a workflow.

Failure scoping follows Design section 4. A root-index defect loads no pack; a
pack-level defect fails that pack closed; an unverifiable intent artifact is
excluded from the registry; an invalid active adoption leaves the intent known
but unavailable; an invalid inactive adoption is a loud diagnostic that never
takes a valid active record down with it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ghostcursor.packs.trusted import (
    ArtifactRef,
    ArtifactSchema,
    load_authority_document,
    load_trusted_artifact,
    resolve_trusted_directory,
)

PACKS_ROOT = ("ghostcursor", "packs")

_INTENT_ID_RE = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_ADOPTION_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class DiagnosticCode(str, Enum):
    """Why something in the graph was refused. Never a partial success."""

    ROOT_INDEX_INVALID = "root_index_invalid"
    DUPLICATE_INTENT = "duplicate_intent"
    DUPLICATE_EXACT_PHRASE = "duplicate_exact_phrase"
    PACK_INVALID = "pack_invalid"
    GENERATION_INVALID = "generation_invalid"
    INTENT_INVALID = "intent_invalid"
    ACTIVE_ADOPTION_INVALID = "active_adoption_invalid"
    INACTIVE_ADOPTION_INVALID = "inactive_adoption_invalid"


class IntentAvailability(str, Enum):
    """Whether a known intent may execute right now."""

    ACTIVE = "active"
    KNOWN_INTENT_RECIPE_UNAVAILABLE = "known_intent_recipe_unavailable"


@dataclass(frozen=True)
class Diagnostic:
    code: DiagnosticCode
    detail: str
    pack_id: str | None = None
    intent_id: str | None = None
    adoption_id: str | None = None


@dataclass(frozen=True)
class ApplicationIdentity:
    """One resolved application identity. Comparison is exact in v2 (D073)."""

    kind: str
    value: str


@dataclass(frozen=True)
class AdoptionRecord:
    """One complete, immutable acceptance fact for one recipe."""

    adoption_id: str
    recipe: ArtifactRef
    recipe_value: Any
    accepted_pack: ArtifactRef
    accepted_intent: ArtifactRef
    accepted_application_identity: ApplicationIdentity
    evidence: ArtifactRef
    adopted_at: str
    reviewer_id: str
    review_commit: str
    supersedes_adoption_id: str | None
    supersedes_recipe_sha256: str | None

    def accepts_identity(self, identity: ApplicationIdentity) -> bool:
        """Exact strategy and value equality. No ranges, no `unknown` (D073)."""

        return (
            identity.kind == self.accepted_application_identity.kind
            and identity.value == self.accepted_application_identity.value
        )


@dataclass(frozen=True)
class VerifiedIntent:
    intent_id: str
    intent: ArtifactRef
    intent_value: Any
    availability: IntentAvailability
    active_adoption: AdoptionRecord | None
    adoptions: Mapping[str, AdoptionRecord]

    def adoption_for_identity(
        self, adoption_id: str, identity: ApplicationIdentity
    ) -> AdoptionRecord | None:
        """A preserved record is rollback-eligible only for the identity it covers."""

        record = self.adoptions.get(adoption_id)
        if record is None or not record.accepts_identity(identity):
            return None
        return record


@dataclass(frozen=True)
class VerifiedPack:
    pack_id: str
    directory: Path
    activation_generation: int
    activation_sha256: str
    pack: ArtifactRef
    pack_value: Any
    intents: Mapping[str, VerifiedIntent]


@dataclass(frozen=True)
class VerifiedCatalog:
    root_valid: bool
    packs: Mapping[str, VerifiedPack]
    diagnostics: tuple[Diagnostic, ...] = field(default=())


class _PackRejected(Exception):
    """A pack-scoped failure. Carries the code the catalog should report."""

    def __init__(self, code: DiagnosticCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def load_catalog(
    project_root: Path, *, previous: VerifiedCatalog | None = None
) -> VerifiedCatalog:
    """Verify the whole activation graph beneath `project_root`.

    `previous` supplies the last observed activation generation per pack, which
    is an audit sequence only: it never decides content, and the digests in
    `activation.json` remain the sole binding.
    """

    project_root = Path(project_root)
    packs_root = project_root.joinpath(*PACKS_ROOT)
    diagnostics: list[Diagnostic] = []

    try:
        index = load_authority_document(packs_root, "index.json", ArtifactSchema.INDEX)
    except (ValueError, OSError) as exc:
        return _root_failure(DiagnosticCode.ROOT_INDEX_INVALID, str(exc), diagnostics)

    packs: dict[str, VerifiedPack] = {}
    for entry in index.value["packs"]:
        pack_id = entry["pack_id"]
        pack_diagnostics: list[Diagnostic] = []
        try:
            pack = _load_pack(
                project_root=project_root,
                packs_root=packs_root,
                pack_id=pack_id,
                relative=entry["path"],
                previous=previous,
                diagnostics=pack_diagnostics,
            )
        except _PackRejected as exc:
            diagnostics.append(
                Diagnostic(code=exc.code, detail=exc.detail, pack_id=pack_id)
            )
            continue
        diagnostics.extend(pack_diagnostics)
        packs[pack_id] = pack

    ambiguity = _global_ambiguity(packs)
    if ambiguity is not None:
        diagnostics.append(ambiguity)
        return _root_failure(ambiguity.code, ambiguity.detail, diagnostics, added=True)

    return VerifiedCatalog(
        root_valid=True,
        packs=MappingProxyType(packs),
        diagnostics=tuple(diagnostics),
    )


def _root_failure(
    code: DiagnosticCode,
    detail: str,
    diagnostics: list[Diagnostic],
    *,
    added: bool = False,
) -> VerifiedCatalog:
    if not added:
        diagnostics.append(Diagnostic(code=code, detail=detail))
    return VerifiedCatalog(
        root_valid=False,
        packs=MappingProxyType({}),
        diagnostics=tuple(diagnostics),
    )


def _global_ambiguity(packs: Mapping[str, VerifiedPack]) -> Diagnostic | None:
    """Duplicate intent IDs or exact phrases are static defects, not runtime ones."""

    owners: dict[str, str] = {}
    for pack_id, pack in packs.items():
        for intent_id in pack.intents:
            folded = intent_id.casefold()
            if folded in owners:
                return Diagnostic(
                    code=DiagnosticCode.DUPLICATE_INTENT,
                    detail=f"intent {intent_id} is declared by {owners[folded]} and {pack_id}",
                    pack_id=pack_id,
                    intent_id=intent_id,
                )
            owners[folded] = pack_id

    phrases: dict[str, str] = {}
    for pack_id, pack in packs.items():
        for intent_id, intent in pack.intents.items():
            for phrase in _exact_phrases(intent.intent_value):
                if phrase in phrases:
                    return Diagnostic(
                        code=DiagnosticCode.DUPLICATE_EXACT_PHRASE,
                        detail=(
                            f"exact phrase {phrase!r} is claimed by "
                            f"{phrases[phrase]} and {pack_id}/{intent_id}"
                        ),
                        pack_id=pack_id,
                        intent_id=intent_id,
                    )
                phrases[phrase] = f"{pack_id}/{intent_id}"
    return None


def _exact_phrases(intent_value: Any) -> tuple[str, ...]:
    collected: list[str] = []
    for rule in intent_value["rules"]:
        if rule["tier"] == "exact":
            collected.extend(
                " ".join(str(p).casefold().split()) for p in rule["phrases"]
            )
    return tuple(collected)


def _load_pack(
    *,
    project_root: Path,
    packs_root: Path,
    pack_id: str,
    relative: str,
    previous: VerifiedCatalog | None,
    diagnostics: list[Diagnostic],
) -> VerifiedPack:
    try:
        directory = resolve_trusted_directory(packs_root, relative)
    except (ValueError, OSError) as exc:
        raise _PackRejected(DiagnosticCode.PACK_INVALID, str(exc)) from exc

    try:
        activation = load_authority_document(directory, "activation.json")
        document = _validated_activation(activation.value)
    except (ValueError, OSError) as exc:
        raise _PackRejected(DiagnosticCode.PACK_INVALID, str(exc)) from exc

    generation = document["activation_generation"]
    _check_generation(pack_id, generation, previous)

    pack_ref = _artifact_ref(document["pack"], "activation.pack")
    try:
        pack_artifact = load_trusted_artifact(
            directory, pack_ref, ArtifactSchema.PACK, project_root=project_root
        )
    except (ValueError, OSError) as exc:
        raise _PackRejected(DiagnosticCode.PACK_INVALID, str(exc)) from exc
    if pack_artifact.value["pack_id"] != pack_id:
        raise _PackRejected(
            DiagnosticCode.PACK_INVALID,
            "pack artifact pack_id disagrees with the root index",
        )

    planner_only = pack_artifact.value["pack_kind"] == "planner_only"
    if planner_only:
        for intent_id, entry in document["intents"].items():
            if entry["active_adoption_id"] is not None or entry["adoptions"]:
                raise _PackRejected(
                    DiagnosticCode.PACK_INVALID,
                    f"planner_only intent {intent_id} carries adoption records",
                )

    intents: dict[str, VerifiedIntent] = {}
    for intent_id, entry in document["intents"].items():
        verified = _load_intent(
            project_root=project_root,
            directory=directory,
            pack_id=pack_id,
            pack_ref=pack_ref,
            pack_value=pack_artifact.value,
            intent_id=intent_id,
            entry=entry,
            diagnostics=diagnostics,
        )
        if verified is not None:
            intents[intent_id] = verified

    return VerifiedPack(
        pack_id=pack_id,
        directory=directory,
        activation_generation=generation,
        activation_sha256=activation.sha256,
        pack=pack_ref,
        pack_value=pack_artifact.value,
        intents=MappingProxyType(intents),
    )


def _check_generation(
    pack_id: str, generation: int, previous: VerifiedCatalog | None
) -> None:
    """An audit sequence: it may repeat on a reload, and advances by exactly one."""

    if previous is None:
        return
    known = previous.packs.get(pack_id)
    if known is None:
        return
    if not known.activation_generation <= generation <= known.activation_generation + 1:
        raise _PackRejected(
            DiagnosticCode.GENERATION_INVALID,
            f"activation_generation {generation} does not follow "
            f"{known.activation_generation}",
        )


def _load_intent(
    *,
    project_root: Path,
    directory: Path,
    pack_id: str,
    pack_ref: ArtifactRef,
    pack_value: Any,
    intent_id: str,
    entry: dict[str, Any],
    diagnostics: list[Diagnostic],
) -> VerifiedIntent | None:
    intent_ref = _artifact_ref(
        entry["intent"], f"activation.intents.{intent_id}.intent"
    )
    try:
        intent_artifact = load_trusted_artifact(
            directory, intent_ref, ArtifactSchema.INTENT, project_root=project_root
        )
        if intent_artifact.value["intent_id"] != intent_id:
            raise ValueError("intent artifact intent_id disagrees with activation")
    except (ValueError, OSError) as exc:
        diagnostics.append(
            Diagnostic(
                code=DiagnosticCode.INTENT_INVALID,
                detail=str(exc),
                pack_id=pack_id,
                intent_id=intent_id,
            )
        )
        return None

    raw_adoptions = entry["adoptions"]
    valid, rejected = _verify_adoptions(
        project_root=project_root,
        directory=directory,
        pack_ref=pack_ref,
        pack_value=pack_value,
        intent_id=intent_id,
        intent_ref=intent_ref,
        raw_adoptions=raw_adoptions,
    )

    active_id = entry["active_adoption_id"]
    active = valid.get(active_id) if active_id is not None else None
    for adoption_id, reason in rejected.items():
        code = (
            DiagnosticCode.ACTIVE_ADOPTION_INVALID
            if adoption_id == active_id
            else DiagnosticCode.INACTIVE_ADOPTION_INVALID
        )
        diagnostics.append(
            Diagnostic(
                code=code,
                detail=reason,
                pack_id=pack_id,
                intent_id=intent_id,
                adoption_id=adoption_id,
            )
        )
    if active_id is not None and active is None and active_id not in rejected:
        diagnostics.append(
            Diagnostic(
                code=DiagnosticCode.ACTIVE_ADOPTION_INVALID,
                detail=f"active_adoption_id {active_id!r} names no adoption record",
                pack_id=pack_id,
                intent_id=intent_id,
                adoption_id=active_id,
            )
        )

    availability = (
        IntentAvailability.ACTIVE
        if active is not None
        else IntentAvailability.KNOWN_INTENT_RECIPE_UNAVAILABLE
    )
    return VerifiedIntent(
        intent_id=intent_id,
        intent=intent_ref,
        intent_value=intent_artifact.value,
        availability=availability,
        active_adoption=active,
        adoptions=MappingProxyType(valid),
    )


def _verify_adoptions(
    *,
    project_root: Path,
    directory: Path,
    pack_ref: ArtifactRef,
    pack_value: Any,
    intent_id: str,
    intent_ref: ArtifactRef,
    raw_adoptions: dict[str, Any],
) -> tuple[dict[str, AdoptionRecord], dict[str, str]]:
    """Validate each record on its own, then the predecessor graph they form."""

    records: dict[str, AdoptionRecord] = {}
    rejected: dict[str, str] = {}
    for adoption_id, raw in raw_adoptions.items():
        try:
            records[adoption_id] = _adoption_record(
                project_root=project_root,
                directory=directory,
                pack_ref=pack_ref,
                pack_value=pack_value,
                intent_id=intent_id,
                intent_ref=intent_ref,
                adoption_id=adoption_id,
                raw=raw,
            )
        except (ValueError, OSError) as exc:
            rejected[adoption_id] = str(exc)

    for adoption_id in sorted(records):
        record = records[adoption_id]
        predecessor_id = record.supersedes_adoption_id
        if predecessor_id is None:
            continue
        predecessor_raw = raw_adoptions.get(predecessor_id)
        if not isinstance(predecessor_raw, Mapping):
            continue
        declared = predecessor_raw.get("recipe")
        actual = declared.get("sha256") if isinstance(declared, Mapping) else None
        if record.supersedes_recipe_sha256 != actual:
            rejected[adoption_id] = (
                f"supersedes_recipe_sha256 disagrees with adoption {predecessor_id!r}"
            )
    for adoption_id in list(rejected):
        records.pop(adoption_id, None)

    grounded = _grounded(records)
    for adoption_id in list(records):
        if adoption_id not in grounded:
            rejected.setdefault(
                adoption_id,
                "predecessor chain is dangling, self-referential, or cyclic",
            )
            records.pop(adoption_id)
    return records, rejected


def _grounded(records: Mapping[str, AdoptionRecord]) -> set[str]:
    """Records whose predecessor chain terminates at a first adoption."""

    state: dict[str, bool] = {}

    def walk(adoption_id: str, stack: set[str]) -> bool:
        if adoption_id in state:
            return state[adoption_id]
        if adoption_id in stack:
            return False
        predecessor_id = records[adoption_id].supersedes_adoption_id
        if predecessor_id is None:
            state[adoption_id] = True
            return True
        if predecessor_id not in records:
            state[adoption_id] = False
            return False
        stack.add(adoption_id)
        result = walk(predecessor_id, stack)
        stack.discard(adoption_id)
        state[adoption_id] = result
        return result

    return {adoption_id for adoption_id in records if walk(adoption_id, set())}


def _adoption_record(
    *,
    project_root: Path,
    directory: Path,
    pack_ref: ArtifactRef,
    pack_value: Any,
    intent_id: str,
    intent_ref: ArtifactRef,
    adoption_id: str,
    raw: Any,
) -> AdoptionRecord:
    label = f"adoption {adoption_id!r}"
    if _ADOPTION_ID_RE.fullmatch(adoption_id) is None:
        raise ValueError(f"{label} id is not canonical")
    _exact_fields(
        raw,
        {
            "recipe",
            "accepted_pack",
            "accepted_intent",
            "accepted_application_identity",
            "evidence",
            "adopted_at",
            "reviewer_id",
            "review_commit",
            "supersedes_adoption_id",
            "supersedes_recipe_sha256",
        },
        label,
    )

    recipe_ref = _artifact_ref(raw["recipe"], f"{label}.recipe")
    recipe = load_trusted_artifact(
        directory, recipe_ref, ArtifactSchema.RECIPE, project_root=project_root
    )
    if recipe.value["intent_id"] != intent_id:
        raise ValueError(f"{label} recipe intent_id disagrees with activation")

    accepted_pack = _artifact_ref(raw["accepted_pack"], f"{label}.accepted_pack")
    accepted_intent = _artifact_ref(raw["accepted_intent"], f"{label}.accepted_intent")
    if (accepted_pack.path, accepted_pack.sha256) != (pack_ref.path, pack_ref.sha256):
        raise ValueError(f"{label} accepted pack is not the currently bound pack")
    if (accepted_intent.path, accepted_intent.sha256) != (
        intent_ref.path,
        intent_ref.sha256,
    ):
        raise ValueError(f"{label} accepted intent is not the currently bound intent")

    identity = _application_identity(
        raw["accepted_application_identity"], pack_value, label
    )

    evidence_ref = _artifact_ref(raw["evidence"], f"{label}.evidence")
    load_trusted_artifact(
        directory, evidence_ref, ArtifactSchema.EVIDENCE, project_root=project_root
    )

    adopted_at = _timestamp(raw["adopted_at"], label)
    reviewer_id = _nonempty(raw["reviewer_id"], f"{label}.reviewer_id")
    review_commit = raw["review_commit"]
    if (
        not isinstance(review_commit, str)
        or _COMMIT_RE.fullmatch(review_commit) is None
    ):
        raise ValueError(f"{label}.review_commit must be a lowercase 40-hex commit")

    predecessor_id = raw["supersedes_adoption_id"]
    predecessor_digest = raw["supersedes_recipe_sha256"]
    if (predecessor_id is None) != (predecessor_digest is None):
        raise ValueError(f"{label} predecessor id and digest must both be set or null")
    if predecessor_id is not None:
        if (
            not isinstance(predecessor_id, str)
            or _ADOPTION_ID_RE.fullmatch(predecessor_id) is None
        ):
            raise ValueError(f"{label}.supersedes_adoption_id is not canonical")
        if (
            not isinstance(predecessor_digest, str)
            or _SHA256_RE.fullmatch(predecessor_digest) is None
        ):
            raise ValueError(f"{label}.supersedes_recipe_sha256 is not a SHA-256")
        if predecessor_id == adoption_id:
            raise ValueError(f"{label} supersedes itself")

    return AdoptionRecord(
        adoption_id=adoption_id,
        recipe=recipe_ref,
        recipe_value=recipe.value,
        accepted_pack=accepted_pack,
        accepted_intent=accepted_intent,
        accepted_application_identity=identity,
        evidence=evidence_ref,
        adopted_at=adopted_at,
        reviewer_id=reviewer_id,
        review_commit=review_commit,
        supersedes_adoption_id=predecessor_id,
        supersedes_recipe_sha256=predecessor_digest,
    )


def _application_identity(
    value: Any, pack_value: Any, label: str
) -> ApplicationIdentity:
    """The record's strategy must equal the pack's; `unknown` never activates."""

    _exact_fields(value, {"kind", "value"}, f"{label}.accepted_application_identity")
    declared = pack_value["version_identity"]
    if not isinstance(declared, Mapping):
        raise ValueError(f"{label} pack declares no application identity strategy")
    kind = value["kind"]
    if kind != declared["kind"]:
        raise ValueError(f"{label} identity strategy disagrees with the pack")
    identity_value = _nonempty(value["value"], f"{label}.accepted_application_identity")
    if kind == "content_sha256" and _SHA256_RE.fullmatch(identity_value) is None:
        raise ValueError(f"{label} content identity must be a lowercase SHA-256")
    return ApplicationIdentity(kind=kind, value=identity_value)


def _validated_activation(value: Any) -> dict[str, Any]:
    _exact_fields(
        value,
        {"schema_version", "activation_generation", "pack", "intents"},
        "activation",
    )
    if value["schema_version"] != 2 or isinstance(value["schema_version"], bool):
        raise ValueError("activation.schema_version must be 2")

    generation = value["activation_generation"]
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 1
    ):
        raise ValueError("activation_generation must be a positive integer")

    intents = value["intents"]
    if not isinstance(intents, Mapping):
        raise ValueError("activation.intents must be an object")
    for intent_id, entry in intents.items():
        if not isinstance(intent_id, str) or _INTENT_ID_RE.fullmatch(intent_id) is None:
            raise ValueError("activation intent id is not canonical")
        _exact_fields(
            entry,
            {"intent", "active_adoption_id", "adoptions"},
            f"activation.intents.{intent_id}",
        )
        active = entry["active_adoption_id"]
        if active is not None and (
            not isinstance(active, str) or _ADOPTION_ID_RE.fullmatch(active) is None
        ):
            raise ValueError(
                f"activation.intents.{intent_id}.active_adoption_id is invalid"
            )
        if not isinstance(entry["adoptions"], Mapping):
            raise ValueError(
                f"activation.intents.{intent_id}.adoptions must be an object"
            )
    return value


def _artifact_ref(value: Any, label: str) -> ArtifactRef:
    _exact_fields(value, {"path", "sha256"}, label)
    try:
        return ArtifactRef(path=value["path"], sha256=value["sha256"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not a valid artifact reference: {exc}") from exc


def _exact_fields(value: Any, required: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    missing = required - value.keys()
    unknown = value.keys() - required
    if missing:
        raise ValueError(f"{label} missing fields: {sorted(missing)}")
    if unknown:
        raise ValueError(f"{label} has unknown fields: {sorted(unknown)}")
    return value


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be a non-empty stripped string")
    return value


def _timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label}.adopted_at must be a string")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError(f"{label}.adopted_at must be UTC ISO-8601") from exc
    return value
