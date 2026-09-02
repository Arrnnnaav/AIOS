"""Signed presentation stages and ordered cues.

A stage names a contiguous run of already-validated nodes and gives it a label
a person can read. A cue marks a point inside a stage where the session shows
something before the next nodes run.

**Neither carries authority.** A cue does not batch authorization: every node
inside a cue's group still reloads authority, binds its target, receives its
own one-use authorization, executes, and is verified independently. That rule
lives in the executor; what lives here is the guarantee that the shape the
executor is handed cannot express anything else -- a cue owns a span of nodes
for *display*, and the span is derived from declared anchors rather than
inferred at runtime.

Everything is declared. There is no catch-all stage, no "remaining nodes"
bucket, and no rule that assigns an unlisted node to a neighbour. A plan whose
stages do not cover its nodes exactly once is refused whole, before anything
runs, because a node nobody claimed would otherwise execute with no stage text
on screen -- the user watching would see the previous stage's label while a
different operation took effect.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Mapping, Sequence


class StagePlanError(ValueError):
    """A stage or cue declaration that must be refused before execution."""


#: Ceilings, from the plan's own limits. A stage larger than this is not a
#: stage but a phase, and it would show one label across dozens of effects.
MAX_NODES_PER_STAGE = 40
MAX_STAGES_PER_PLAN = 32
MAX_CUES_PER_STAGE = 6

#: The plan cap on cues is derived, never maintained as a second number that
#: could drift out of agreement with the two it comes from. Being derived from
#: exactly the two per-stage limits also makes the plan-level check
#: unreachable: no plan can pass those and exceed this. It is kept as a stated
#: bound rather than deleted, so a future change to either limit cannot
#: silently raise the total past what a session UI was designed to show.
MAX_CUES_PER_PLAN = MAX_STAGES_PER_PLAN * MAX_CUES_PER_STAGE

#: Backends a cue may claim, matching the executor's ladder. A cue that names
#: a backend the executor cannot select would promise a trust colour nothing
#: can deliver.
CUE_BACKENDS = frozenset(
    {"object_model", "uia_pattern", "legacy_iaccessible", "rail_only"}
)

#: An arrow points somewhere or it does not exist. An unconstrained string
#: would reach the renderer and be silently ignored, which looks the same as a
#: cue that meant to point and does not.
CUE_ARROW_DIRECTIONS = frozenset({"up", "down", "left", "right"})

#: Risk classes come from the signed operation registry, never from a stage
#: author's opinion; a stage records which class its nodes carry so the
#: approval preview can show planned pauses.  Ordered, because a stage's risk
#: is the strongest risk it contains: labelling a stage that holds one HIGH
#: node as "low" is exactly the mislabel the approval preview must not show.
STAGE_RISK_ORDER = ("low", "medium", "high")
STAGE_RISKS = frozenset(STAGE_RISK_ORDER)


@dataclass(frozen=True)
class Cue:
    """One point inside a stage where presentation happens before nodes run."""

    cue_id: str
    text: str
    backend: str
    before_node_id: str
    #: Opaque signed descriptor of what to point at, or None for rail-only
    #: text. Never coordinates: geometry is observed at runtime and is
    #: presentation-only, so a plan that carried a rectangle would be
    #: asserting a screen position months before the screen exists.
    target: Mapping[str, Any] | None = None
    arrow_direction: str | None = None


@dataclass(frozen=True)
class Stage:
    """A contiguous, explicitly declared run of nodes with a readable label."""

    stage_id: str
    label: str
    node_ids: tuple[str, ...]
    risk: str
    cues: tuple[Cue, ...] = ()


@dataclass(frozen=True)
class CueGroup:
    """One cue and the nodes it presents, derived from declared anchors."""

    cue: Cue
    node_ids: tuple[str, ...]


@dataclass(frozen=True)
class ValidatedStagePlan:
    stages: tuple[Stage, ...]
    groups: tuple[CueGroup, ...]
    #: Nodes in stages that declared no cue. They run under the stage label
    #: with no pointer, which is the honest presentation for an operation with
    #: no trustworthy screen rectangle.
    rail_only_node_ids: tuple[str, ...]

    @property
    def stage_count(self) -> int:
        return len(self.stages)

    @property
    def cue_count(self) -> int:
        return len(self.groups)


def _text(value: object, label: str, *, limit: int = 200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise StagePlanError(f"{label} is invalid")
    return value


def _deep_freeze(value):
    """Freeze a signed target descriptor all the way down.

    A frozen dataclass is shallow and so is one MappingProxyType: wrapping the
    outer mapping leaves every nested dict and list writable, so a caller that
    kept a reference could still rewrite what a cue points at after the plan
    was validated. Mappings become read-only views and sequences become tuples,
    recursively; scalars are already immutable.
    """

    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _freeze_cue(cue: Cue) -> Cue:
    if cue.target is None:
        return cue
    return replace(cue, target=_deep_freeze(cue.target))


def _freeze_stage(stage: Stage) -> Stage:
    return replace(
        stage,
        node_ids=tuple(stage.node_ids),
        cues=tuple(_freeze_cue(cue) for cue in stage.cues),
    )


def validate_stage_plan(
    stages: Sequence[Stage],
    ordered_node_ids: Sequence[str],
    *,
    node_risks: Mapping[str, str] | None = None,
) -> ValidatedStagePlan:
    """Refuse the whole declaration, or return its deterministic flattening.

    ``ordered_node_ids`` is the plan's own flattened node order. Stages are
    checked against it rather than against each other, so "contiguous" and
    "in order" mean what the executor will actually do, not what the stage
    list happens to say about itself.

    ``node_risks`` maps node id to the risk its signed operation carries. When
    supplied, a stage's declared risk must equal the strongest risk among its
    nodes: without this check a stage holding a HIGH node could be labelled
    "low" and the approval preview would show no planned pause where one is
    coming. It is optional only because the registry is not always in hand;
    a caller that has it must pass it, and a wired schema always will.
    """

    if not isinstance(stages, Sequence) or isinstance(stages, (str, bytes)):
        raise StagePlanError("stages must be a sequence")
    if not 1 <= len(stages) <= MAX_STAGES_PER_PLAN:
        raise StagePlanError(
            f"a plan declares 1 to {MAX_STAGES_PER_PLAN} stages, not {len(stages)}"
        )
    if not ordered_node_ids:
        raise StagePlanError("a stage plan needs nodes to describe")

    position = {node_id: index for index, node_id in enumerate(ordered_node_ids)}
    if len(position) != len(ordered_node_ids):
        raise StagePlanError("the plan's node order repeats a node id")

    seen_stage_ids: set[str] = set()
    seen_cue_ids: set[str] = set()
    claimed: dict[str, str] = {}
    groups: list[CueGroup] = []
    rail_only: list[str] = []
    expected_start = 0

    for stage in stages:
        if not isinstance(stage, Stage):
            raise StagePlanError("stage declaration is not a Stage")
        stage_id = _text(stage.stage_id, "stage_id", limit=64)
        _text(stage.label, f"stage {stage_id!r} label")
        if stage_id in seen_stage_ids:
            raise StagePlanError(f"stage {stage_id!r} is declared twice")
        seen_stage_ids.add(stage_id)
        if stage.risk not in STAGE_RISKS:
            raise StagePlanError(f"stage {stage_id!r} risk {stage.risk!r} is unknown")

        node_ids = tuple(stage.node_ids)
        if not 1 <= len(node_ids) <= MAX_NODES_PER_STAGE:
            raise StagePlanError(
                f"stage {stage_id!r} holds 1 to {MAX_NODES_PER_STAGE} nodes, "
                f"not {len(node_ids)}"
            )
        for node_id in node_ids:
            if node_id not in position:
                raise StagePlanError(
                    f"stage {stage_id!r} names unknown node {node_id!r}"
                )
            if node_id in claimed:
                raise StagePlanError(
                    f"node {node_id!r} is claimed by both {claimed[node_id]!r} "
                    f"and {stage_id!r}"
                )
            claimed[node_id] = stage_id

        indexes = [position[node_id] for node_id in node_ids]
        if indexes != sorted(indexes):
            raise StagePlanError(
                f"stage {stage_id!r} lists its nodes out of plan order"
            )
        if indexes[0] != expected_start:
            raise StagePlanError(
                f"stage {stage_id!r} starts at node {indexes[0]} but the "
                f"previous stage ended before {expected_start}; stages must be "
                "contiguous and may not interleave"
            )
        if indexes != list(range(indexes[0], indexes[0] + len(indexes))):
            raise StagePlanError(
                f"stage {stage_id!r} skips nodes; a stage is a contiguous run"
            )
        expected_start = indexes[-1] + 1

        if node_risks is not None:
            missing = [n for n in node_ids if n not in node_risks]
            if missing:
                raise StagePlanError(
                    f"stage {stage_id!r} names node {missing[0]!r}, which the "
                    "signed registry declares no risk for"
                )
            unknown = [r for r in (node_risks[n] for n in node_ids)
                       if r not in STAGE_RISKS]
            if unknown:
                raise StagePlanError(
                    f"stage {stage_id!r} node risk {unknown[0]!r} is unknown"
                )
            strongest = max(
                (node_risks[n] for n in node_ids),
                key=STAGE_RISK_ORDER.index,
            )
            if stage.risk != strongest:
                raise StagePlanError(
                    f"stage {stage_id!r} declares risk {stage.risk!r} but its "
                    f"strongest node risk is {strongest!r}"
                )

        groups.extend(_validate_cues(stage, node_ids, seen_cue_ids))
        if not stage.cues:
            rail_only.extend(node_ids)

    unassigned = [node_id for node_id in ordered_node_ids if node_id not in claimed]
    if unassigned:
        raise StagePlanError(
            f"{len(unassigned)} node(s) belong to no stage, first {unassigned[0]!r}; "
            "there is no catch-all stage"
        )
    if len(groups) > MAX_CUES_PER_PLAN:
        raise StagePlanError(
            f"a plan declares at most {MAX_CUES_PER_PLAN} cues, not {len(groups)}"
        )
    frozen = tuple(_freeze_stage(stage) for stage in stages)
    frozen_groups = tuple(
        CueGroup(_freeze_cue(group.cue), tuple(group.node_ids)) for group in groups
    )
    return ValidatedStagePlan(frozen, frozen_groups, tuple(rail_only))


def _validate_cues(
    stage: Stage, node_ids: tuple[str, ...], seen_cue_ids: set[str]
) -> list[CueGroup]:
    cues = tuple(stage.cues)
    if len(cues) > MAX_CUES_PER_STAGE:
        raise StagePlanError(
            f"stage {stage.stage_id!r} declares {len(cues)} cues, "
            f"more than {MAX_CUES_PER_STAGE}"
        )
    if not cues:
        return []
    if len(cues) > len(node_ids):
        raise StagePlanError(
            f"stage {stage.stage_id!r} declares more cues than it has nodes"
        )

    order = {node_id: index for index, node_id in enumerate(node_ids)}
    anchors: list[int] = []
    for cue in cues:
        if not isinstance(cue, Cue):
            raise StagePlanError(f"stage {stage.stage_id!r} cue is not a Cue")
        cue_id = _text(cue.cue_id, "cue_id", limit=64)
        _text(cue.text, f"cue {cue_id!r} text")
        if cue_id in seen_cue_ids:
            raise StagePlanError(f"cue {cue_id!r} is declared twice")
        seen_cue_ids.add(cue_id)
        if cue.backend not in CUE_BACKENDS:
            raise StagePlanError(f"cue {cue_id!r} backend {cue.backend!r} is unknown")
        if cue.backend == "rail_only" and cue.target is not None:
            raise StagePlanError(
                f"cue {cue_id!r} is rail-only but declares a visual target"
            )
        if cue.target is not None and not isinstance(cue.target, Mapping):
            # Refused here rather than left to blow up inside the freeze: a
            # caller catching StagePlanError would otherwise miss a bare
            # TypeError from a target that was never a mapping.
            raise StagePlanError(
                f"cue {cue_id!r} target must be a mapping, not "
                f"{type(cue.target).__name__}"
            )
        if (
            cue.arrow_direction is not None
            and cue.arrow_direction not in CUE_ARROW_DIRECTIONS
        ):
            raise StagePlanError(
                f"cue {cue_id!r} arrow direction {cue.arrow_direction!r} is unknown"
            )
        index = order.get(cue.before_node_id)
        if index is None:
            raise StagePlanError(
                f"cue {cue_id!r} anchors to {cue.before_node_id!r}, which is not "
                f"in stage {stage.stage_id!r}"
            )
        if anchors and index <= anchors[-1]:
            raise StagePlanError(
                f"cue {cue_id!r} anchors at or before the previous cue; anchors "
                "must increase through the stage"
            )
        anchors.append(index)

    if anchors[0] != 0:
        raise StagePlanError(
            f"stage {stage.stage_id!r} has cues but its first node "
            f"{node_ids[0]!r} is not anchored; those nodes would run with no "
            "presentation"
        )

    groups: list[CueGroup] = []
    for position, cue in enumerate(cues):
        start = anchors[position]
        end = anchors[position + 1] if position + 1 < len(anchors) else len(node_ids)
        groups.append(CueGroup(cue, node_ids[start:end]))
    return groups


__all__ = [
    "CUE_ARROW_DIRECTIONS",
    "CUE_BACKENDS",
    "Cue",
    "CueGroup",
    "MAX_CUES_PER_PLAN",
    "MAX_CUES_PER_STAGE",
    "MAX_NODES_PER_STAGE",
    "MAX_STAGES_PER_PLAN",
    "STAGE_RISKS",
    "STAGE_RISK_ORDER",
    "Stage",
    "StagePlanError",
    "ValidatedStagePlan",
    "validate_stage_plan",
]
