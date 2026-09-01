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

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


class StagePlanError(ValueError):
    """A stage or cue declaration that must be refused before execution."""


#: Ceilings, from the plan's own limits. A stage larger than this is not a
#: stage but a phase, and it would show one label across dozens of effects.
MAX_NODES_PER_STAGE = 40
MAX_STAGES_PER_PLAN = 32
MAX_CUES_PER_STAGE = 6

#: The plan cap on cues is derived, never maintained as a second number that
#: could drift out of agreement with the two it comes from.
MAX_CUES_PER_PLAN = MAX_STAGES_PER_PLAN * MAX_CUES_PER_STAGE

#: Backends a cue may claim, matching the executor's ladder. A cue that names
#: a backend the executor cannot select would promise a trust colour nothing
#: can deliver.
CUE_BACKENDS = frozenset(
    {"object_model", "uia_pattern", "legacy_iaccessible", "rail_only"}
)

#: Risk classes come from the signed operation registry, never from a stage
#: author's opinion; a stage records which class its nodes carry so the
#: approval preview can show planned pauses.
STAGE_RISKS = frozenset({"low", "medium", "high"})


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


def validate_stage_plan(
    stages: Sequence[Stage], ordered_node_ids: Sequence[str]
) -> ValidatedStagePlan:
    """Refuse the whole declaration, or return its deterministic flattening.

    ``ordered_node_ids`` is the plan's own flattened node order. Stages are
    checked against it rather than against each other, so "contiguous" and
    "in order" mean what the executor will actually do, not what the stage
    list happens to say about itself.
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
    return ValidatedStagePlan(tuple(stages), tuple(groups), tuple(rail_only))


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
    "CUE_BACKENDS",
    "Cue",
    "CueGroup",
    "MAX_CUES_PER_PLAN",
    "MAX_CUES_PER_STAGE",
    "MAX_NODES_PER_STAGE",
    "MAX_STAGES_PER_PLAN",
    "STAGE_RISKS",
    "Stage",
    "StagePlanError",
    "ValidatedStagePlan",
    "validate_stage_plan",
]
