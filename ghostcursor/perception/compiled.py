"""Compose the production perception stack for one compiled workflow.

The compiled path has the same obligations as the v1 driver and had been
meeting only some of them. This module is the single place they are met, so
"the compiled tour observes correctly" is one composition with one test rather
than a claim spread across two call sites.

What it owns, and why each is not optional:

* **the captured HWND.** Perception is pinned to `workflow.target.hwnd` and
  never re-finds a window by title. Open Folder CHANGES the title as its
  verified outcome, so a title search loses the target at precisely the moment
  verification needs it -- and could attach to a different matching window,
  which is the captured-target contract broken outright.
* **raw provider results.** `FindAll` returns `IUIAutomationElement`, not a
  pywinauto control. The two have entirely different property surfaces, so one
  adapter cannot serve both and the query path needs its own.
* **tier 2.** The UI thread decides and requests; the worker executes and
  publishes (D035). Without the request half a tier-2 controller is inert, and
  a workflow that can only ground through OCR never grounds at all.
* **staleness.** A hint drawn from an ageing observation must dim and then
  hide. A hardcoded `FRESH` says every hint is confirmed-current, which is the
  one thing the ladder exists to deny.
* **worker health.** A dead worker leaves its last slot in place, and a slot
  that never ages looks exactly like a screen that never changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ghostcursor.perception import uia
from ghostcursor.perception.service import PerceptionService, run_observation_plan


class RawElementInfo:
    """Property reads for one raw `IUIAutomationElement`.

    `provider_exact()` takes a `make_info` because presence is established by a
    successful property READ and never by a result existing (D069). This is
    that read for a provider result, and it is deliberately separate from the
    pywinauto adapter the bounded walk uses: `FindAll` hands back COM elements
    with `CurrentName` and `CurrentBoundingRectangle`, while a walk hands back
    controls with `window_text()` and `rectangle()`. Feeding either shape to
    the other's adapter raises on the first live query.
    """

    def __init__(self, element) -> None:
        self.name = element.CurrentName or ""
        self.control_type = _CONTROL_TYPE_NAMES.get(
            element.CurrentControlType, str(element.CurrentControlType)
        )
        self.automation_id = element.CurrentAutomationId or ""
        rect = element.CurrentBoundingRectangle
        self.rectangle = _Rect(rect.left, rect.top, rect.right, rect.bottom)
        try:
            runtime_id = element.GetRuntimeId()
        except Exception:
            runtime_id = None
        if runtime_id:
            self.runtime_id = tuple(runtime_id)


@dataclass(frozen=True)
class _Rect:
    left: int
    top: int
    right: int
    bottom: int


_CONTROL_TYPE_NAMES = {value: name for name, value in uia._CONTROL_TYPE_IDS.items()}


class PywinautoElementInfo:
    """Property reads for one pywinauto control, for the bounded walk."""

    def __init__(self, control) -> None:
        info = control.element_info
        self.name = info.name or ""
        self.control_type = info.control_type or ""
        self.automation_id = info.automation_id or ""
        self.rectangle = control.rectangle()
        runtime_id = getattr(info, "runtime_id", None)
        if runtime_id:
            self.runtime_id = tuple(runtime_id)


def compiled_plan_runner(
    workflow,
    *,
    walk=uia.control_type_walk,
    query=uia.provider_query_for,
    read_title=None,
    make_info=RawElementInfo,
):
    """Run one compiled observation plan against the CAPTURED window.

    Every UIA call it makes happens on the worker thread, because this is what
    `PerceptionService(plan_runner=...)` invokes. The 41-second measured block
    on a "Not Responding" target is why (D021).

    The target HWND comes from the workflow, never from the `target_hwnd` the
    service resolved: the service's own source is pinned to the same handle, so
    the two agree, and taking it from the workflow makes the pinning explicit
    at the place that would otherwise be free to drift.

    Returns `(selector_results, elements, title)`. The title is read HERE, on
    the worker: `GetWindowText` against another process is a `SendMessage` and
    can block on a hung window, which on the UI thread is the freeze again.
    """
    if read_title is None:  # pragma: no cover - needs a real desktop
        import win32gui

        read_title = win32gui.GetWindowText

    hwnd = workflow.target.hwnd

    def _run(_resolved_hwnd: int):
        observation = run_observation_plan(
            workflow.recipe.plan,
            walk_for=lambda control_type: lambda: walk(hwnd, control_type),
            query_for=lambda control_type, name: (
                lambda: query(hwnd, control_type, name)
            ),
            make_info=make_info,
        )
        return tuple(observation.selectors.items()), observation.union, read_title(hwnd)

    return _run


def compiled_perception_service(
    workflow,
    clock,
    *,
    tier2=None,
    plan_runner=None,
    interval_s=None,
) -> PerceptionService:
    """A worker pinned to the workflow's captured window.

    `hwnd_source` ignores the title entirely and answers with the bound handle.
    Re-finding by title is what the captured-target contract exists to forbid,
    and Open Folder is the workflow that proves why: the title it verifies
    against is the one the search would no longer match.
    """
    kwargs = {}
    if interval_s is not None:
        kwargs["interval_s"] = interval_s
    return PerceptionService(
        title_re=re.escape(workflow.target.title or ""),
        hwnd_source=lambda _title_re: workflow.target.hwnd,
        clock=clock,
        tier2=tier2,
        plan_runner=plan_runner or compiled_plan_runner(workflow),
        **kwargs,
    )


def merge_ocr(plan, selectors, ocr_elements):
    """Escalate a selector that UIA could not see to what OCR read.

    Only where tier 1 found NOTHING. OCR never displaces a confirmed control:
    a pixel guess must not overwrite a real one, and a selector that already
    matched has no failure to escalate from.

    Matching uses the selector's own declared names and normalisation, so an
    OCR escalation is bounded by the same trusted vocabulary as the walk. The
    published element keeps `source="ocr"`, which is what makes the hint render
    in the inferred colour and what stops `promote()` persisting it (D006,
    D030).
    """
    if not ocr_elements:
        return selectors

    merged = dict(selectors)
    for selector_id, selector in plan.selectors.items():
        if merged.get(selector_id):
            continue
        matches = tuple(
            element
            for element in ocr_elements
            if uia.matches_trusted_name(
                element.name, selector.names, normalise=selector.normalise
            )
        )
        if not matches:
            continue
        # The declared cardinality still binds. An ambiguous OCR read is not a
        # target, and silently taking the first is exactly what the rule
        # forbids for a confirmed control.
        if selector.cardinality == uia.EXACTLY_ONE and len(matches) > 1:
            continue
        merged[selector_id] = matches
    return merged


class CompiledObservationSource:
    """Everything the UI thread must do with a published observation.

    Reading the slot is the smallest part. This also ages the staleness ladder,
    escalates to tier 2 when grounding fails and cancels when it succeeds, and
    checks worker health -- all obligations the v1 driver already met and the
    compiled path had simply not been given.
    """

    def __init__(self, service, ladder, health=None, plan=None) -> None:
        self.service = service
        self.ladder = ladder
        self.health = health
        self.plan = plan
        self._last_observed_at: float | None = None
        self._step = -1

    def __call__(self):
        from ghostcursor.reasoning.compiled_tour import TickInput

        if self.health is not None:
            # A dead worker leaves its last slot in place, and a slot that
            # never ages looks exactly like a screen that never changes.
            self.health.check()

        observation = self.service.latest()
        if observation is None:
            return None

        snapshot = observation.snapshot
        if observation.observed_at != self._last_observed_at:
            self._last_observed_at = observation.observed_at
            self.ladder.observed()

        selectors = dict(snapshot.selector_results)
        if self.plan is not None and observation.tier2_step == self._step:
            selectors = merge_ocr(self.plan, selectors, observation.ocr_elements)

        union = tuple(snapshot.elements)
        extra = tuple(
            element
            for matched in selectors.values()
            for element in matched
            if element.source != "uia" and element not in union
        )
        return TickInput(
            title=snapshot.title,
            selectors=selectors,
            union=union + extra,
            focused_automation_id=snapshot.focused_automation_id,
        )

    def note_grounding(self, step_index: int, grounded: bool) -> None:
        """The decision half of tier 2 (D035).

        Only the tick loop knows which step is current and whether grounding
        just failed, so it is the only thing that can ask -- and the worker
        does the reading, on its own thread, publishing the answer on a LATER
        observation. Absence of a request means "not wanted": there is no
        `wanted` flag, so a success and a step boundary must both cancel or
        OCR keeps running for a step that no longer needs it.
        """
        if step_index != self._step:
            self.service.cancel_tier2()
            self._step = step_index
        if grounded:
            self.service.report_tier2_grounded(step_index)
            self.service.cancel_tier2()
        else:
            self.service.request_tier2(step_index)


def build_compiled_perception(
    workflow,
    clock,
    *,
    tier2=None,
    service=None,
    ladder=None,
    health=None,
) -> tuple[PerceptionService, CompiledObservationSource]:
    """Wire the whole stack for one workflow and start nothing.

    Starting is the caller's decision, and deliberately so: the candidate
    harness must not have a worker running before its pre-launch gates pass,
    or the run can consume an observation taken while the artifacts were still
    unverified.
    """
    from ghostcursor.perception.health import WorkerHealth
    from ghostcursor.reasoning.staleness import StalenessLadder

    service = service or compiled_perception_service(workflow, clock, tier2=tier2)
    ladder = ladder or StalenessLadder(clock=clock)
    health = health or WorkerHealth(service=service, ladder=ladder)
    source = CompiledObservationSource(
        service, ladder, health=health, plan=workflow.recipe.plan
    )
    return service, source
