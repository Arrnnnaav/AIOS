"""Phase B: measure whether a control can be acted on, without acting on it.

This module reads. It never invokes, selects, toggles, sets a value, or calls
``DoDefaultAction``. Reading ``LegacyIAccessible.DefaultAction`` returns the
name of an action; calling ``DoDefaultAction`` performs it. Those are one
letter apart in the source and worlds apart in effect, so the distinction is
asserted by a test that scans this file rather than left to review.

Two questions decide the second-application proof:

**Can the control be driven by a true UIA pattern?**  Pattern availability is
a property read, so it is answerable without dispatching anything. The answer
is recorded per pattern rather than collapsed into a yes/no, because
``LegacyIAccessible`` availability is a weaker result than ``Invoke`` and
must never be reported as if it were the same finding.

**Does the control keep a stable identity across the cue?**  D037 measured VS
Code's element set churning roughly 10% in steady state with no user action at
all, so a RuntimeId that will be compared across a 650 ms cue has to earn that
role by measurement. The stability probe re-resolves the selector across the
same dwell the real cue will impose, and a single failed cycle is enough to
disqualify: 100/100 means 100 of 100.

A cycle is a genuine PAIR -- observe, dwell, re-resolve -- not one observation
with a gap before the next. An earlier version resolved once per iteration and
slept between iterations, producing 100 samples across 99 intervals. That
measures whether the control drifts over a long run; it does not measure what
a single cue's dwell does to it, which is the claim the identity policy
actually rests on.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

# The one implementation of this rule lives with the schema that enforces it;
# a second copy here is how D069's refusal would drift out of agreement.
from ghostcursor.reasoning.schema import is_positional_automation_id


#: Patterns the generic UIA backend may use, and the property that reports
#: availability.  The literals are fallbacks: the live probe prefers the
#: constant published by the UIA type library and records which source
#: answered, so a wrong number here shows up as a disagreement rather than as
#: a confident wrong answer.
PATTERN_AVAILABILITY_PROPERTIES: Mapping[str, tuple[str, int]] = {
    "Invoke": ("UIA_IsInvokePatternAvailablePropertyId", 30031),
    "SelectionItem": ("UIA_IsSelectionItemPatternAvailablePropertyId", 30036),
    "Toggle": ("UIA_IsTogglePatternAvailablePropertyId", 30041),
    "Value": ("UIA_IsValuePatternAvailablePropertyId", 30043),
    "LegacyIAccessible": (
        "UIA_IsLegacyIAccessiblePatternAvailablePropertyId",
        30090,
    ),
}

#: Ranked exactly as the plan's backend ladder ranks them.  Order is meaning:
#: a weaker backend must never be reported where a stronger one was found.
PATTERN_PREFERENCE: tuple[str, ...] = (
    "Invoke",
    "SelectionItem",
    "Toggle",
    "Value",
    "LegacyIAccessible",
)


@dataclass(frozen=True)
class ObservedTarget:
    """One read-only observation of a candidate control."""

    name: str
    normalised_name: str
    control_type: str
    automation_id: str
    runtime_id: tuple[int, ...] | None
    native_window_handle: int | None
    bbox: tuple[int, int, int, int] | None
    patterns: Mapping[str, bool] = field(default_factory=dict)
    legacy_default_action: str | None = None
    match_count: int = 1
    #: Where each pattern constant came from (type library or literal
    #: fallback), so a wrong fallback shows up as a disagreement, not as
    #: "no pattern available".
    pattern_sources: Mapping[str, str] = field(default_factory=dict)

    @property
    def preferred_backend(self) -> str | None:
        """The strongest available backend, or None when nothing can drive it."""

        for pattern in PATTERN_PREFERENCE:
            if self.patterns.get(pattern):
                return pattern
        return None


@dataclass(frozen=True)
class StabilityResult:
    """What N observe -> dwell -> re-resolve PAIRS measured.

    ``cycles`` counts pairs. ``observations`` counts individual reads, which
    is ``2 * cycles`` when nothing failed. ``dwell_intervals`` counts the gaps
    actually slept -- one per cycle, inside it. Reporting these separately is
    the point: "100 cycles" and "100 samples" are different measurements and
    only one of them covers a cue's dwell.
    """

    cycles: int
    resolved_cycles: int
    observations: int
    dwell_intervals: int
    faults: tuple[str, ...]
    distinct_runtime_ids: tuple[tuple[int, ...] | None, ...]
    distinct_automation_ids: tuple[str, ...]
    distinct_names: tuple[str, ...]
    distinct_match_counts: tuple[int, ...]
    #: Cycles whose two halves disagreed about RuntimeId. This is the direct
    #: measurement of what one cue's dwell does, rather than an inference from
    #: how many distinct ids appeared across the whole run.
    cycles_with_identity_change: int = 0

    @property
    def fully_resolved(self) -> bool:
        return self.cycles > 0 and self.resolved_cycles == self.cycles

    @property
    def runtime_id_stable(self) -> bool:
        """True only when every cycle resolved to one identical RuntimeId.

        A cycle that failed to resolve is instability, not a missing sample:
        the control the cue pointed at was not there when the action would
        have fired. A ``None`` RuntimeId is likewise not stable -- identity
        that could not be read is not identity (D069).
        """

        return (
            self.fully_resolved
            and self.cycles_with_identity_change == 0
            and len(self.distinct_runtime_ids) == 1
            and self.distinct_runtime_ids[0] is not None
        )

    @property
    def semantic_identity_stable(self) -> bool:
        """The fallback identity: one name, one control, every cycle.

        This is what the signed ``exactly_one`` selector rests on when
        RuntimeId cannot be required.
        """

        return (
            self.fully_resolved
            and len(self.distinct_names) == 1
            and self.distinct_match_counts == (1,)
        )


def probe_stability(
    resolve: Callable[[], ObservedTarget],
    *,
    cycles: int = 100,
    dwell_s: float = 0.65,
    sleep: Callable[[float], None] = time.sleep,
) -> StabilityResult:
    """Run ``cycles`` complete observe -> dwell -> re-resolve pairs.

    ``resolve`` and ``sleep`` are injected so the sequence can be driven by an
    ordered fake rather than by wall time (D026). The dwell defaults to the
    650 ms cue budget because a stability claim measured over a shorter gap
    would not cover the window it is used to justify.

    Both halves of a cycle must resolve for the cycle to count. A half that
    faulted is the control being absent at a moment the real action could have
    fired, which is instability rather than a missing sample.
    """

    resolved_cycles = 0
    observations = 0
    dwell_intervals = 0
    identity_changes = 0
    faults: list[str] = []
    runtime_ids: list[tuple[int, ...] | None] = []
    automation_ids: list[str] = []
    names: list[str] = []
    match_counts: list[int] = []

    def observe(cycle: int, half: str) -> ObservedTarget | None:
        nonlocal observations
        try:
            value = resolve()
        except Exception as exc:  # noqa: BLE001 - every failure is a datum
            faults.append(f"cycle {cycle} {half}: {type(exc).__name__}: {exc}")
            return None
        observations += 1
        runtime_ids.append(value.runtime_id)
        automation_ids.append(value.automation_id)
        names.append(value.normalised_name)
        match_counts.append(value.match_count)
        return value

    for index in range(cycles):
        before = observe(index, "before")
        sleep(dwell_s)
        dwell_intervals += 1
        after = observe(index, "after")
        if before is None or after is None:
            continue
        resolved_cycles += 1
        if before.runtime_id != after.runtime_id:
            identity_changes += 1

    def unique(values: Sequence[Any]) -> tuple:
        seen: list[Any] = []
        for value in values:
            if value not in seen:
                seen.append(value)
        return tuple(seen)

    return StabilityResult(
        cycles,
        resolved_cycles,
        observations,
        dwell_intervals,
        tuple(faults),
        unique(runtime_ids),
        unique(automation_ids),
        unique(names),
        unique(match_counts),
        identity_changes,
    )


@dataclass(frozen=True)
class FeasibilityVerdict:
    """What the probe concluded, and what it refuses to conclude."""

    backend: str | None
    identity_mode: str
    usable: bool
    reasons: tuple[str, ...]


def decide_feasibility(
    observed: ObservedTarget, stability: StabilityResult
) -> FeasibilityVerdict:
    """Apply the plan's identity policy to one measured candidate.

    Never widens: an unstable RuntimeId demotes identity to the signed
    semantic selector, and a candidate with neither is refused rather than
    driven on a positional id or on cardinality alone.
    """

    reasons: list[str] = []
    backend = observed.preferred_backend
    if backend is None:
        reasons.append("no reviewed UIA pattern is available on this control")
    if observed.match_count != 1:
        reasons.append(
            f"selector matched {observed.match_count} controls, not exactly one"
        )
    if is_positional_automation_id(observed.automation_id):
        reasons.append(
            f"AutomationId {observed.automation_id!r} is positional and is "
            "refused as identity"
        )

    if stability.runtime_id_stable:
        identity_mode = "runtime_id_required"
    elif stability.semantic_identity_stable:
        identity_mode = "semantic_exactly_one"
        reasons.append(
            "RuntimeId was not stable across "
            f"{stability.cycles} cycles; it is evidence-only"
        )
    else:
        identity_mode = "none"
        reasons.append(
            "neither a stable RuntimeId nor a stable exactly-one semantic "
            "identity was measured"
        )

    usable = (
        backend is not None
        and observed.match_count == 1
        and identity_mode != "none"
        and not is_positional_automation_id(observed.automation_id)
    )
    if usable and backend == "LegacyIAccessible":
        reasons.append(
            "only LegacyIAccessible is available; targeting semantics are "
            "weaker than a true UIA pattern and this requires explicit "
            "signed permission"
        )
    return FeasibilityVerdict(backend, identity_mode, usable, tuple(reasons))


def verdict_record(
    application: str,
    observed: ObservedTarget,
    stability: StabilityResult,
    verdict: FeasibilityVerdict,
) -> dict[str, Any]:
    """A D034-shaped record: every claim beside the measurement behind it."""

    return {
        "application": application,
        "automation_id": observed.automation_id,
        "backend": verdict.backend,
        "control_type": observed.control_type,
        "cycles": stability.cycles,
        "cycles_with_identity_change": stability.cycles_with_identity_change,
        "dwell_intervals": stability.dwell_intervals,
        "observations": stability.observations,
        "distinct_automation_ids": len(stability.distinct_automation_ids),
        "distinct_match_counts": list(stability.distinct_match_counts),
        "distinct_names": len(stability.distinct_names),
        "distinct_runtime_ids": len(stability.distinct_runtime_ids),
        "faults": list(stability.faults),
        "identity_mode": verdict.identity_mode,
        "legacy_default_action": observed.legacy_default_action,
        "match_count": observed.match_count,
        "name": observed.name,
        "normalised_name": observed.normalised_name,
        "patterns": dict(sorted(observed.patterns.items())),
        "pattern_sources": dict(sorted(observed.pattern_sources.items())),
        "reasons": list(verdict.reasons),
        "resolved_cycles": stability.resolved_cycles,
        "runtime_id_stable": stability.runtime_id_stable,
        "semantic_identity_stable": stability.semantic_identity_stable,
        "type": "uia_feasibility",
        "usable": verdict.usable,
    }


# ---------------------------------------------------------------------------
# Live shim.  Everything above is decided by the tested core; everything below
# only reads the desktop and hands values to it.  comtypes is imported lazily
# so the hermetic lane can import this module on any machine.
#
# These functions are unverified until they run against a real desktop.  They
# are written to report what they could not read rather than to substitute a
# default, so a wrong property id or an unavailable pattern surfaces as a
# named fault instead of a confident wrong answer.
# ---------------------------------------------------------------------------

#: UIA_LegacyIAccessiblePatternId.  Reading this pattern's DefaultAction
#: property names the action; it does not perform it.
_LEGACY_PATTERN_ID = 10018


def _automation_and_module():
    import comtypes.client

    module = comtypes.client.GetModule("UIAutomationCore.dll")
    automation = comtypes.client.CreateObject(
        "{ff48dba4-60ef-4201-aa87-54103eef594e}", interface=module.IUIAutomation
    )
    return automation, module


def _property_id(module, constant_name: str, fallback: int) -> tuple[int, str]:
    """Prefer the type library's own constant; say which source answered."""

    value = getattr(module, constant_name, None)
    if isinstance(value, int):
        return value, "type-library"
    return fallback, "literal-fallback"


def read_pattern_availability(
    element, module
) -> tuple[dict[str, bool], dict[str, str]]:
    """Read each reviewed pattern's availability property. No pattern is used."""

    available: dict[str, bool] = {}
    sources: dict[str, str] = {}
    for pattern, (constant, fallback) in PATTERN_AVAILABILITY_PROPERTIES.items():
        property_id, source = _property_id(module, constant, fallback)
        sources[pattern] = source
        try:
            available[pattern] = bool(element.GetCurrentPropertyValue(property_id))
        except Exception as exc:  # noqa: BLE001 - an unreadable property is not a False
            available[pattern] = False
            sources[pattern] = f"{source}/unreadable:{type(exc).__name__}"
    return available, sources


def read_legacy_default_action(element, module) -> str | None:
    """The NAME of the legacy default action, read as a property.

    ``CurrentDefaultAction`` is a string property. ``DoDefaultAction`` is the
    effect and is never called here.
    """

    try:
        pattern = element.GetCurrentPattern(_LEGACY_PATTERN_ID)
        if pattern is None:
            return None
        legacy = pattern.QueryInterface(module.IUIAutomationLegacyIAccessiblePattern)
        return str(legacy.CurrentDefaultAction)
    except Exception:  # noqa: BLE001 - absence and unreadability are both "no name"
        return None


def observe_live_target(hwnd: int, control_type: str, name: str) -> ObservedTarget:
    """One read-only observation of the named control inside one window.

    The query itself is ``provider_query_for``: provider-side FindAll, scoped
    to this window's subtree, by control type and exact name. Reusing it keeps
    one implementation of the query strategy -- a second copy here would drift
    from the reviewed one, and the scope choice in particular is deliberate.

    The provider's own cardinality answer is kept as ``match_count`` and
    refused downstream, never narrowed here (D069/D070).
    """

    from ghostcursor.perception.uia import ProviderQueryFault, provider_query_for

    results = provider_query_for(hwnd, control_type, name)
    if not results:
        raise ProviderQueryFault(f"no {control_type} named {name!r} in window {hwnd}")
    _automation, module = _automation_and_module()
    return _read_target(results[0], module, control_type, name, len(results))


def _read_target(element, module, control_type, requested_name, match_count):
    """Read every identity property, reporting what could not be read.

    Each read is separate on purpose: an unreadable RuntimeId must not cost us
    the bounding rectangle, and a property that could not be read is recorded
    as absent rather than defaulted (D069 -- presence needs a successful read).
    """

    from ghostcursor.perception.uia import normalise_accessible_name

    patterns, sources = read_pattern_availability(element, module)
    try:
        runtime_id = tuple(int(part) for part in element.GetRuntimeId())
    except Exception:  # noqa: BLE001
        runtime_id = None
    try:
        native = int(element.CurrentNativeWindowHandle) or None
    except Exception:  # noqa: BLE001
        native = None
    try:
        rect = element.CurrentBoundingRectangle
        bbox = (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    except Exception:  # noqa: BLE001
        bbox = None
    try:
        observed_name = str(element.CurrentName)
    except Exception:  # noqa: BLE001
        observed_name = requested_name
    try:
        automation_id = str(element.CurrentAutomationId)
    except Exception:  # noqa: BLE001
        automation_id = ""
    return ObservedTarget(
        name=observed_name,
        normalised_name=normalise_accessible_name(observed_name),
        control_type=control_type,
        automation_id=automation_id,
        runtime_id=runtime_id,
        native_window_handle=native,
        bbox=bbox,
        patterns=patterns,
        legacy_default_action=read_legacy_default_action(element, module),
        match_count=match_count,
        pattern_sources=sources,
    )


def list_candidates(hwnd: int, control_type: str) -> list[dict[str, Any]]:
    """Enumerate one window's controls of one type, with their patterns.

    Discovery, not acceptance. Excel's accessible name for its sheet-insert
    control was measured here rather than guessed, and the guesses would have
    been wrong: it is `Add Sheet`, not "New sheet" or "Insert Worksheet".
    Putting an invented name in a signed selector points a recipe at nothing.

    Uses the same provider-side FindAll the action path uses. An earlier
    version walked the tree with pywinauto and reported 3 Buttons where the
    provider reports 28 -- `Add Sheet` among the missing ones.
    """

    from ghostcursor.perception.uia import provider_type_query_for

    _automation, module = _automation_and_module()
    found: list[dict[str, Any]] = []
    for raw in provider_type_query_for(hwnd, control_type):
        try:
            target = _read_target(raw, module, control_type, "", 1)
        except Exception:  # noqa: BLE001 - an unreadable control is not a finding
            continue
        found.append(
            {
                "automation_id": target.automation_id,
                "bbox": list(target.bbox) if target.bbox else None,
                "control_type": control_type,
                "legacy_default_action": target.legacy_default_action,
                "name": target.name,
                "normalised_name": target.normalised_name,
                "patterns": dict(sorted(target.patterns.items())),
                "preferred_backend": target.preferred_backend,
                "runtime_id": list(target.runtime_id) if target.runtime_id else None,
            }
        )
    return found


def resolve_single_window(executable: str, title_re: str = ".*") -> int:
    """Exactly one matching window, or refuse and name every candidate (D075)."""

    from ghostcursor.perception.uia import windows_matching_executable

    handles = windows_matching_executable(title_re, executable)
    if len(handles) != 1:
        raise RuntimeError(
            f"expected exactly one {executable} window, found {len(handles)}: "
            + repr(handles)
        )
    return handles[0]


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Read-only UIA feasibility probe (Phase B). Never acts."
    )
    parser.add_argument("--executable", required=True, help="e.g. excel.exe, Code.exe")
    parser.add_argument("--title-re", default=".*")
    parser.add_argument("--control-type", default="Button")
    parser.add_argument(
        "--name",
        default=None,
        help="Exact accessible name. Omit it to list candidates instead.",
    )
    parser.add_argument("--cycles", type=int, default=100)
    parser.add_argument("--dwell-s", type=float, default=0.65)
    parser.add_argument("--out", type=str, default=None)
    args = parser.parse_args(argv)

    import comtypes

    comtypes.CoInitializeEx()
    try:
        hwnd = resolve_single_window(args.executable, args.title_re)
        if args.name is None:
            payload: dict[str, Any] = {
                "candidates": list_candidates(hwnd, args.control_type),
                "control_type": args.control_type,
                "executable": args.executable,
                "type": "uia_candidates",
            }
        else:

            def resolve() -> ObservedTarget:
                return observe_live_target(hwnd, args.control_type, args.name)

            observed = resolve()
            stability = probe_stability(
                resolve, cycles=args.cycles, dwell_s=args.dwell_s
            )
            payload = verdict_record(
                args.executable,
                observed,
                stability,
                decide_feasibility(observed, stability),
            )
            payload["dwell_s"] = args.dwell_s
    finally:
        comtypes.CoUninitialize()

    text = json.dumps(payload, indent=2, sort_keys=True)
    print(text)
    if args.out:
        from pathlib import Path

        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        if Path(args.out).exists():  # never replace captured evidence
            raise SystemExit(f"refused: output already exists: {args.out}")
        Path(args.out).write_text(text + "\n", encoding="utf-8", newline="\n")
    return 0


__all__ = [
    "FeasibilityVerdict",
    "ObservedTarget",
    "PATTERN_AVAILABILITY_PROPERTIES",
    "PATTERN_PREFERENCE",
    "StabilityResult",
    "decide_feasibility",
    "list_candidates",
    "observe_live_target",
    "probe_stability",
    "read_legacy_default_action",
    "read_pattern_availability",
    "resolve_single_window",
    "verdict_record",
]


if __name__ == "__main__":
    raise SystemExit(main())
