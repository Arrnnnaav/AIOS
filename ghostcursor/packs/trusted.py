from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any


_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_PACK_ID_RE = re.compile(r"[a-z][a-z0-9_]*\Z")
_INTENT_ID_RE = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_SELECTOR_ID_RE = re.compile(r"[a-z][a-z0-9_]*\Z")
_UTF8_BOM = b"\xef\xbb\xbf"


class ArtifactSchema(str, Enum):
    INDEX = "index"
    PACK = "pack"
    INTENT = "intent"
    RECIPE = "recipe"
    EVIDENCE = "evidence"


@dataclass(frozen=True)
class ArtifactRef:
    path: str
    sha256: str

    def __post_init__(self) -> None:
        _validate_relative_path(self.path, "artifact path")
        if _SHA256_RE.fullmatch(self.sha256) is None:
            raise ValueError("artifact digest must be a full lowercase SHA-256")


@dataclass(frozen=True)
class LoadedArtifact:
    ref: ArtifactRef
    path: Path
    schema: ArtifactSchema
    sha256: str
    raw_bytes: bytes
    value: Any


@dataclass(frozen=True)
class AuthorityDocument:
    path: Path
    sha256: str
    raw_bytes: bytes
    value: Any


def load_authority_document(
    root: Path,
    relative: str,
    schema: ArtifactSchema | None = None,
    *,
    project_root: Path | None = None,
) -> AuthorityDocument:
    """Read one mutable authority file once and return its immutable JSON value."""

    path = _trusted_file(Path(root), relative)
    raw = path.read_bytes()
    value = _parse_json(_decode_utf8(raw))
    if schema is not None:
        validator = {
            ArtifactSchema.INDEX: _validate_index,
            ArtifactSchema.PACK: lambda document: _validate_pack(
                document, project_root=Path(project_root or root)
            ),
            ArtifactSchema.INTENT: _validate_intent,
            ArtifactSchema.RECIPE: _validate_recipe,
        }.get(schema)
        if validator is None:
            raise ValueError("evidence is not a JSON authority schema")
        validator(value)
    value = _freeze(value)
    return AuthorityDocument(
        path=path,
        sha256=hashlib.sha256(raw).hexdigest(),
        raw_bytes=raw,
        value=value,
    )


def resolve_trusted_directory(root: Path, relative: str) -> Path:
    """Resolve an explicitly named, non-symlinked directory beneath root."""

    return _trusted_path(Path(root), relative, require_directory=True)


def load_trusted_artifact(
    root: Path,
    ref: ArtifactRef,
    schema: ArtifactSchema,
    *,
    project_root: Path | None = None,
) -> LoadedArtifact:
    """Load, attest, and strictly validate one explicitly named artifact."""

    root = Path(root)
    project_root = Path(project_root) if project_root is not None else root
    if schema is ArtifactSchema.EVIDENCE:
        if not ref.path.startswith("docs/evidence/") or not ref.path.endswith(".md"):
            raise ValueError("acceptance evidence must be Markdown under docs/evidence")
        load_root = project_root
    else:
        load_root = root

    path = _trusted_file(load_root, ref.path)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != ref.sha256:
        raise ValueError("artifact digest mismatch")
    text = _decode_utf8(raw)

    if schema is ArtifactSchema.EVIDENCE:
        value: Any = text
    else:
        value = _parse_json(text)
        validator = {
            ArtifactSchema.INDEX: _validate_index,
            ArtifactSchema.PACK: lambda document: _validate_pack(
                document, project_root=project_root
            ),
            ArtifactSchema.INTENT: _validate_intent,
            ArtifactSchema.RECIPE: _validate_recipe,
        }[schema]
        validator(value)
        value = _freeze(value)

    return LoadedArtifact(
        ref=ref,
        path=path,
        schema=schema,
        sha256=digest,
        raw_bytes=raw,
        value=value,
    )


def _decode_utf8(raw: bytes) -> str:
    if raw.startswith(_UTF8_BOM):
        raise ValueError("UTF-8 BOM is forbidden")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("artifact is not valid UTF-8") from exc


def _parse_json(text: str) -> dict[str, Any]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number is forbidden: {value}")

    def finite_float(value: str) -> float:
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("non-finite JSON number is forbidden")
        return result

    try:
        value = json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=invalid_constant,
            parse_float=finite_float,
        )
    except json.JSONDecodeError as exc:
        raise ValueError("artifact is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("artifact root must be an object")
    return value


def freeze(value: Any) -> Any:
    """Deep-freeze one parsed artifact value.

    Every nesting level, not just the outer one. A shallow freeze looks
    identical from the outside and protects nothing that matters: the values a
    recipe actually decides behaviour with -- a verification's
    `goal_reference`, its `minimum_length` -- live one or two levels down, so
    an outer `MappingProxyType` over mutable interiors is a guarantee in shape
    only.

    Public because the compiler must be able to re-apply it. Anything that
    rebuilds part of an artifact and hands the result on has to freeze what it
    rebuilt, or it silently gives back the mutability the trust boundary
    removed.
    """
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value


_freeze = freeze


def _validate_relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    if "\\" in value or ":" in value or value.startswith("/"):
        raise ValueError(f"{label} must be a canonical relative POSIX path")
    path = PurePosixPath(value)
    if str(path) != value or any(
        part in {"", ".", ".."}
        or part != part.strip()
        or part.endswith(".")
        or any(ord(character) < 32 for character in part)
        for part in path.parts
    ):
        raise ValueError(f"{label} must be a canonical relative POSIX path")
    return value


def _trusted_file(root: Path, relative: str) -> Path:
    return _trusted_path(root, relative, require_directory=False)


def _trusted_path(root: Path, relative: str, *, require_directory: bool) -> Path:
    _validate_relative_path(relative, "artifact path")
    if root.is_symlink():
        raise ValueError("trusted root must not be a symlink")
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise ValueError("trusted root does not exist") from exc

    candidate = root
    for part in PurePosixPath(relative).parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("trusted artifact path must not contain a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError("trusted artifact does not exist") from exc
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("trusted artifact resolves outside its root") from exc
    if require_directory:
        if not resolved.is_dir():
            raise ValueError("trusted path must be a directory")
    elif not resolved.is_file():
        raise ValueError("trusted artifact must be a file")
    return resolved


def _exact_fields(
    value: Any,
    required: set[str],
    label: str,
    *,
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    optional = optional or set()
    missing = required - value.keys()
    unknown = value.keys() - required - optional
    if missing:
        raise ValueError(f"{label} missing fields: {sorted(missing)}")
    if unknown:
        raise ValueError(f"{label} has unknown fields: {sorted(unknown)}")
    return value


def _string(value: Any, label: str, *, stripped: bool = True) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    if stripped and value != value.strip():
        raise ValueError(f"{label} must not contain surrounding whitespace")
    return value


def _string_list(
    value: Any,
    label: str,
    *,
    nonempty: bool = False,
    canonical_literals: bool = False,
    stripped: bool = True,
) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(f"{label} must be {'a non-empty' if nonempty else 'a'} list")
    result: list[str] = []
    for index, item in enumerate(value):
        item = _string(item, f"{label}[{index}]", stripped=stripped)
        if not stripped and not item.strip():
            raise ValueError(f"{label}[{index}] must not be whitespace-only")
        if canonical_literals and item != " ".join(item.casefold().split()):
            raise ValueError(f"{label}[{index}] must already be normalized")
        result.append(item)
    if len(set(result)) != len(result):
        raise ValueError(f"{label} contains duplicates")
    return result


def _schema_v2(value: dict[str, Any], label: str) -> None:
    if value["schema_version"] != 2 or isinstance(value["schema_version"], bool):
        raise ValueError(f"{label}.schema_version must be 2")


def _validate_index(value: dict[str, Any]) -> None:
    _exact_fields(value, {"schema_version", "packs"}, "pack index")
    _schema_v2(value, "pack index")
    packs = value["packs"]
    if not isinstance(packs, list):
        raise ValueError("pack index.packs must be a list")
    ids: set[str] = set()
    paths: set[str] = set()
    for index, entry in enumerate(packs):
        _exact_fields(entry, {"pack_id", "path"}, f"pack index.packs[{index}]")
        pack_id = _string(entry["pack_id"], "pack_id")
        if _PACK_ID_RE.fullmatch(pack_id) is None:
            raise ValueError("pack_id is not canonical")
        path = _validate_relative_path(entry["path"], "pack path")
        folded_id = pack_id.casefold()
        folded_path = path.casefold()
        if folded_id in ids:
            raise ValueError("duplicate pack_id in pack index")
        if folded_path in paths:
            raise ValueError("duplicate pack path in pack index")
        ids.add(folded_id)
        paths.add(folded_path)


def _validate_pack(value: dict[str, Any], *, project_root: Path) -> None:
    _exact_fields(
        value,
        {
            "schema_version",
            "pack_id",
            "pack_kind",
            "display_name",
            "executable_names",
            "title_patterns",
            "tier2_capture",
            "version_identity",
            "aliases",
        },
        "pack",
    )
    _schema_v2(value, "pack")
    pack_id = _string(value["pack_id"], "pack.pack_id")
    if _PACK_ID_RE.fullmatch(pack_id) is None:
        raise ValueError("pack.pack_id is not canonical")
    _string(value["display_name"], "pack.display_name")
    kind = value["pack_kind"]
    if kind not in {"application", "planner_only"}:
        raise ValueError("pack.pack_kind is invalid")

    executables = _string_list(value["executable_names"], "pack.executable_names")
    for executable in executables:
        if (
            executable != executable.casefold()
            or "/" in executable
            or "\\" in executable
        ):
            raise ValueError("executable names must be lowercase basenames")
    patterns = _string_list(value["title_patterns"], "pack.title_patterns")
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError("pack title pattern is invalid") from exc

    if not isinstance(value["aliases"], dict):
        raise ValueError("pack.aliases must be an object")
    for alias, members in value["aliases"].items():
        if _SELECTOR_ID_RE.fullmatch(alias) is None:
            raise ValueError("alias id is not canonical")
        _string_list(
            members,
            f"pack.aliases.{alias}",
            nonempty=True,
            canonical_literals=True,
        )

    if kind == "planner_only":
        if (
            executables
            or patterns
            or value["aliases"]
            or value["tier2_capture"] != "disabled"
            or value["version_identity"] is not None
        ):
            raise ValueError("planner_only pack cannot carry application identity")
        return

    if not executables or not patterns:
        raise ValueError("application pack requires executable and title identity")
    if value["tier2_capture"] not in {"executable_bounded", "disabled"}:
        raise ValueError("application pack tier2_capture is invalid")
    identity = value["version_identity"]
    if not isinstance(identity, dict) or "kind" not in identity:
        raise ValueError("application pack requires version_identity")
    if identity["kind"] == "executable_version":
        _exact_fields(identity, {"kind"}, "version_identity")
    elif identity["kind"] == "content_sha256":
        _exact_fields(identity, {"kind", "path"}, "version_identity")
        source_path = _validate_relative_path(identity["path"], "version identity path")
        if not source_path.startswith("ghostcursor/demo/"):
            raise ValueError("content identity path is outside ghostcursor/demo")
        _trusted_file(project_root, source_path)
    else:
        raise ValueError("version_identity.kind is invalid")


def _validate_intent(value: dict[str, Any]) -> None:
    _exact_fields(
        value,
        {"schema_version", "intent_id", "canonical_target", "rules"},
        "intent",
    )
    _schema_v2(value, "intent")
    intent_id = _string(value["intent_id"], "intent.intent_id")
    if _INTENT_ID_RE.fullmatch(intent_id) is None:
        raise ValueError("intent_id is not canonical")
    if value["canonical_target"] is not None:
        _string(value["canonical_target"], "intent.canonical_target")
    if not isinstance(value["rules"], list):
        raise ValueError("intent.rules must be a list")
    for rule_index, rule in enumerate(value["rules"]):
        label = f"intent.rules[{rule_index}]"
        if not isinstance(rule, dict) or rule.get("tier") not in {"exact", "heuristic"}:
            raise ValueError(f"{label}.tier is invalid")
        if rule["tier"] == "exact":
            _exact_fields(rule, {"tier", "phrases"}, label)
            _string_list(
                rule["phrases"],
                f"{label}.phrases",
                nonempty=True,
                canonical_literals=True,
            )
            continue
        _exact_fields(rule, {"tier", "all_of"}, label)
        clauses = rule["all_of"]
        if not isinstance(clauses, list) or not clauses:
            raise ValueError(f"{label}.all_of must be non-empty")
        for clause_index, clause in enumerate(clauses):
            clause_label = f"{label}.all_of[{clause_index}]"
            _exact_fields(clause, {"any_of"}, clause_label)
            terms = clause["any_of"]
            if not isinstance(terms, list) or not terms:
                raise ValueError(f"{clause_label}.any_of must be non-empty")
            for term_index, term in enumerate(terms):
                term_label = f"{clause_label}.any_of[{term_index}]"
                if not isinstance(term, dict) or len(term) != 1:
                    raise ValueError(f"{term_label} must have exactly one primitive")
                primitive, primitive_value = next(iter(term.items()))
                if primitive in {"token", "alias"}:
                    literal = _string(primitive_value, term_label)
                    if literal != " ".join(literal.casefold().split()):
                        raise ValueError(f"{term_label} must already be normalized")
                elif primitive == "path":
                    if primitive_value is not True:
                        raise ValueError(f"{term_label}.path must be true")
                else:
                    raise ValueError(f"{term_label} uses an unknown matcher primitive")


def _validate_selector(selector_id: str, value: Any) -> None:
    label = f"recipe.selectors.{selector_id}"
    _exact_fields(
        value,
        {
            "strategy",
            "control_type",
            "names",
            "normalise",
            "cardinality",
            "result_limit",
        },
        label,
    )
    if value["strategy"] not in {"provider_exact", "bounded_descendants"}:
        raise ValueError(f"{label}.strategy is invalid")
    _string(value["control_type"], f"{label}.control_type")
    names = _string_list(value["names"], f"{label}.names", nonempty=True)
    if value["normalise"] not in {"none", "strip_leading_private_use"}:
        raise ValueError(f"{label}.normalise is invalid")
    if value["cardinality"] not in {"exactly_one", "at_least_one"}:
        raise ValueError(f"{label}.cardinality is invalid")
    limit = value["result_limit"]
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError(f"{label}.result_limit must be a positive integer")
    if value["strategy"] == "provider_exact" and (
        len(names) != 1 or value["normalise"] != "none"
    ):
        raise ValueError("provider_exact requires one exact, unnormalised name")


def _validate_recipe(value: dict[str, Any]) -> None:
    _exact_fields(
        value,
        {
            "schema_version",
            "intent_id",
            "step_key_namespace",
            "selectors",
            "context_selectors",
            "steps",
        },
        "recipe",
    )
    _schema_v2(value, "recipe")
    intent_id = _string(value["intent_id"], "recipe.intent_id")
    if _INTENT_ID_RE.fullmatch(intent_id) is None:
        raise ValueError("recipe.intent_id is not canonical")
    _string(value["step_key_namespace"], "recipe.step_key_namespace")
    if _contains_coordinate_key(value):
        raise ValueError("trusted recipes cannot contain coordinate observations")

    selectors = value["selectors"]
    if not isinstance(selectors, dict):
        raise ValueError("recipe.selectors must be an object")
    for selector_id, selector in selectors.items():
        if _SELECTOR_ID_RE.fullmatch(selector_id) is None:
            raise ValueError("selector id is not canonical")
        _validate_selector(selector_id, selector)

    context = _string_list(value["context_selectors"], "recipe.context_selectors")
    referenced: set[str] = set()
    for selector_id in context:
        _require_selector(selectors, selector_id, "context selector")
        if selectors[selector_id]["cardinality"] != "at_least_one":
            raise ValueError("context selectors must use at_least_one cardinality")
        referenced.add(selector_id)

    steps = value["steps"]
    if not isinstance(steps, list) or not steps:
        raise ValueError("recipe.steps must be a non-empty list")
    for step_index, step in enumerate(steps):
        referenced.update(_validate_step(step, step_index, selectors, context))

    unused = selectors.keys() - referenced
    if unused:
        raise ValueError(f"recipe has unused selectors: {sorted(unused)}")


_ACTIONS = {
    "click",
    "press_keys",
    "type",
    "drag",
    "select",
    "scroll",
    "observe",
    "wait",
}
_TARGETED_ACTIONS = {"click", "type", "drag", "select", "scroll"}
_SELECTOR_VERIFICATIONS = {"element_appears", "element_disappears", "property_changes"}
_NO_SELECTOR_VERIFICATIONS = {
    "window_title_matches",
    "focus_moves_to",
    "any_meaningful_change",
    "user_confirms",
}


def _validate_step(
    step: Any,
    step_index: int,
    selectors: dict[str, Any],
    context: list[str],
) -> set[str]:
    label = f"recipe.steps[{step_index}]"
    _exact_fields(
        step,
        {
            "user_action",
            "target_selector",
            "target_descriptor",
            "instruction_text",
            "verification_rule",
            "risk",
            "preconditions",
            "provenance",
        },
        label,
    )
    action = step["user_action"]
    if action not in _ACTIONS:
        raise ValueError(f"{label}.user_action is invalid")
    target = step["target_selector"]
    referenced: set[str] = set()
    if target is not None:
        target = _string(target, f"{label}.target_selector")
        _require_selector(selectors, target, "action target")
        if selectors[target]["cardinality"] != "exactly_one":
            raise ValueError("action target selectors must use exactly_one cardinality")
        referenced.add(target)
    elif action in _TARGETED_ACTIONS:
        raise ValueError(f"{label}.target_selector is required for {action}")

    descriptor = step["target_descriptor"]
    _exact_fields(descriptor, {"claimed", "confirmed"}, f"{label}.target_descriptor")
    if descriptor["confirmed"] != []:
        raise ValueError("trusted recipes cannot contain confirmed observations")
    claimed = descriptor["claimed"]
    _exact_fields(
        claimed,
        {"name", "name_synonyms", "ocr_text", "visual_description"},
        f"{label}.target_descriptor.claimed",
    )
    for field in ("name", "ocr_text", "visual_description"):
        if claimed[field] is not None:
            _string(claimed[field], f"{label}.claimed.{field}")
    _string_list(claimed["name_synonyms"], f"{label}.claimed.name_synonyms")
    _string(step["instruction_text"], f"{label}.instruction_text")
    if step["risk"] not in {"normal", "elevated"}:
        raise ValueError(f"{label}.risk is invalid")
    _string_list(step["preconditions"], f"{label}.preconditions")
    _validate_provenance(step["provenance"], label)
    verification_selector = _validate_verification(
        step["verification_rule"], label, selectors, context
    )
    if (
        step["risk"] == "elevated"
        and step["verification_rule"]["kind"] == "any_meaningful_change"
    ):
        raise ValueError("elevated-risk step cannot use any_meaningful_change")
    if action in _TARGETED_ACTIONS and not (
        claimed["name"] or claimed["name_synonyms"] or claimed["ocr_text"]
    ):
        raise ValueError(f"{label} has nothing to identify its target")
    if verification_selector is not None:
        referenced.add(verification_selector)
    return referenced


def _validate_provenance(value: Any, step_label: str) -> None:
    label = f"{step_label}.provenance"
    _exact_fields(
        value,
        {"source_urls", "source_tier", "model", "prompt_version", "created_at"},
        label,
    )
    _string_list(value["source_urls"], f"{label}.source_urls")
    for field in ("source_tier", "model", "prompt_version", "created_at"):
        _string(value[field], f"{label}.{field}")


def _validate_verification(
    value: Any,
    step_label: str,
    selectors: dict[str, Any],
    context: list[str],
) -> str | None:
    label = f"{step_label}.verification_rule"
    _exact_fields(value, {"kind", "args", "timeout_s"}, label, optional={"selector"})
    kind = value["kind"]
    if kind not in _SELECTOR_VERIFICATIONS | _NO_SELECTOR_VERIFICATIONS:
        raise ValueError(f"{label}.kind is invalid")
    selector = value.get("selector")
    if kind in _SELECTOR_VERIFICATIONS:
        if selector is None:
            raise ValueError(f"{label}.selector is required")
        selector = _string(selector, f"{label}.selector")
        _require_selector(selectors, selector, "verification selector")
        # `property_changes` is the one verification that must name a single
        # control. The others ask whether ANY match exists, which several
        # results answer as well as one. A property change has to be
        # attributed to a control, and nothing carries backend identity across
        # ticks -- so with several matches the rule can only compare the two
        # result sets positionally, and UIA guarantees no traversal order.
        # Two unchanged controls returned in the opposite order then read as a
        # change. `at_least_one` is not a weaker answer here, it is an
        # unanswerable question.
        if (
            kind == "property_changes"
            and selectors[selector]["cardinality"] != "exactly_one"
        ):
            raise ValueError(
                "property_changes selectors must use exactly_one cardinality"
            )
    elif selector is not None:
        raise ValueError(f"{label}.selector is forbidden for {kind}")

    timeout = value["timeout_s"]
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError(f"{label}.timeout_s must be positive")
    args = value["args"]
    if not isinstance(args, dict):
        raise ValueError(f"{label}.args must be an object")
    _validate_verification_args(kind, args, label)
    if kind == "any_meaningful_change" and not context:
        raise ValueError("any_meaningful_change requires a context_selector")
    return selector


def _validate_verification_args(kind: str, args: dict[str, Any], label: str) -> None:
    option_fields = {
        "fail_after_timeout",
        "timeout_from_hint",
        "accept_if_already_present",
    }
    if kind == "element_appears":
        required: set[str] = set()
    elif kind == "element_disappears":
        required = set()
    elif kind == "property_changes":
        required = {"property"}
    elif kind == "focus_moves_to":
        required = {"automation_id"}
    elif kind == "any_meaningful_change":
        required = {"scope"}
    elif kind == "user_confirms":
        required = set()
    else:
        required = {"completion_title_suffixes", "goal_reference"}
    allowed = required | option_fields
    missing = required - args.keys()
    if missing:
        raise ValueError(f"{label}.args missing fields: {sorted(missing)}")
    unknown = args.keys() - allowed
    if unknown:
        raise ValueError(f"{label}.args has unknown fields: {sorted(unknown)}")
    for option in option_fields & args.keys():
        if not isinstance(args[option], bool):
            raise ValueError(f"{label}.args.{option} must be boolean")
    if args.get("accept_if_already_present") is True and kind != "element_appears":
        raise ValueError("accept_if_already_present is limited to element_appears")
    if (
        args.get("timeout_from_hint") is True
        and args.get("fail_after_timeout") is not True
    ):
        raise ValueError("timeout_from_hint requires fail_after_timeout")
    if "property" in args:
        _string(args["property"], f"{label}.args.property")
    if "automation_id" in args:
        _string(args["automation_id"], f"{label}.args.automation_id")
    if "scope" in args and not isinstance(args["scope"], dict):
        raise ValueError(f"{label}.args.scope must be an object")
    if kind == "window_title_matches":
        suffixes = _string_list(
            args.get("completion_title_suffixes"),
            f"{label}.args.completion_title_suffixes",
            nonempty=True,
            stripped=False,
        )
        if any(
            suffix != suffix.casefold()
            or suffix != re.sub(r"\s+", " ", suffix)
            or suffix != suffix.rstrip()
            for suffix in suffixes
        ):
            raise ValueError("completion title suffixes must be normalized literals")
        _validate_goal_reference(args.get("goal_reference"), label)


def _validate_goal_reference(value: Any, verification_label: str) -> None:
    label = f"{verification_label}.args.goal_reference"
    _exact_fields(
        value,
        {
            "strip_leading_token",
            "alias",
            "nonspecific_templates",
            "strip_trailing_alias_clause",
            "basename_separators",
            "minimum_length",
        },
        label,
    )
    _normalized_literal(value["strip_leading_token"], f"{label}.strip_leading_token")
    alias = _string(value["alias"], f"{label}.alias")
    if _SELECTOR_ID_RE.fullmatch(alias) is None:
        raise ValueError(f"{label}.alias is not canonical")
    templates = _string_list(
        value["nonspecific_templates"], f"{label}.nonspecific_templates"
    )
    for index, template in enumerate(templates):
        remainder = template.replace("{alias}", "")
        if template.count("{alias}") != 1 or "{" in remainder or "}" in remainder:
            raise ValueError(
                f"{label}.nonspecific_templates[{index}] has invalid placeholder"
            )
        if template != " ".join(template.casefold().split()):
            raise ValueError(
                f"{label}.nonspecific_templates[{index}] is not normalized"
            )
    trailing = value["strip_trailing_alias_clause"]
    _exact_fields(trailing, {"preposition"}, f"{label}.strip_trailing_alias_clause")
    _normalized_literal(
        trailing["preposition"], f"{label}.strip_trailing_alias_clause.preposition"
    )
    separators = _string_list(
        value["basename_separators"], f"{label}.basename_separators", nonempty=True
    )
    if any(separator not in {"/", "\\"} for separator in separators):
        raise ValueError(f"{label}.basename_separators is invalid")
    minimum = value["minimum_length"]
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 2:
        raise ValueError(f"{label}.minimum_length must be at least 2")


def _require_selector(selectors: dict[str, Any], selector_id: str, label: str) -> None:
    if selector_id not in selectors:
        raise ValueError(f"unknown {label}: {selector_id}")


def _contains_coordinate_key(value: Any) -> bool:
    coordinate_keys = {
        "bbox",
        "bounds",
        "bounds_px",
        "click_point",
        "coordinates",
        "point",
        "rect",
        "x",
        "y",
    }
    if isinstance(value, Mapping):
        return any(
            key.casefold() in coordinate_keys or _contains_coordinate_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_coordinate_key(item) for item in value)
    return False


def _normalized_literal(value: Any, label: str) -> str:
    literal = _string(value, label)
    if literal != " ".join(literal.casefold().split()):
        raise ValueError(f"{label} must already be normalized")
    return literal
