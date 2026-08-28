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
from dataclasses import dataclass, field

from ghostcursor.perception import uia
from ghostcursor.perception.health import PerceptionUnhealthy
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


def live_walk(hwnd: int, control_type):
    """The one live traversal seam: type-scoped when asked, full when not.

    `control_type is None` means the caller wants ONE shared enumeration for a
    plan with several traversals. Anything else is the certified type-scoped
    walk -- byte-identical to `_vscode_button_walk`, which is what both VS Code
    workflows were accepted against.
    """
    if control_type is None:
        return uia.descendant_walk(hwnd)
    return uia.control_type_walk(hwnd, control_type)


def compiled_plan_runner(
    workflow,
    *,
    walk=live_walk,
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

    **The traversal shape is chosen by traversal COUNT, from the plan.** One
    backend enumeration is the unit of cost, so:

    - one traversal  -> one type-scoped walk. Strictly narrower than the full
      tree for the same single enumeration, so there is nothing to trade.
    - two or more    -> one shared full enumeration, which every traversal then
      filters by its declared control type. Live Synthetic measurement put two
      type-scoped calls over eight seconds against about four for one
      enumeration.

    Both VS Code recipes declare Button alone, so both take the type-scoped
    walk and reproduce `_vscode_button_walk` exactly -- the walk their v1
    acceptance was measured against. Applying the Synthetic result to them
    instead bought back no enumeration and paid the whole Electron tree for it:
    the generic full-tree descent this project measured and narrowed away from,
    and which CLAUDE.md forbids for these targets by name.

    The count comes from the compiled plan, so a new workflow still needs no
    new Python -- the rule reads data, exactly like every other plan decision.

    Returns `(selector_results, elements, title)`. The title is read HERE, on
    the worker, never from the reasoning tick: that thread polls ESC and pumps
    messages, and a bounded walk is what keeps the title arriving promptly
    enough that a second channel is not worth putting there.
    """
    if read_title is None:  # pragma: no cover - needs a real desktop
        import win32gui

        read_title = win32gui.GetWindowText

    hwnd = workflow.target.hwnd
    plan = workflow.recipe.plan
    # Decided ONCE, from the plan, not per tick: the shape cannot drift between
    # ticks of a single run, and the reason it was chosen stays inspectable.
    shared = len(plan.traversals) > 1

    def _run(_resolved_hwnd: int):
        observation = run_observation_plan(
            plan,
            walk_all=(lambda: walk(hwnd, None)) if shared else None,
            walk_for=(
                None
                if shared
                else lambda control_type: (lambda: walk(hwnd, control_type))
            ),
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


def merge_ocr(plan, selectors, ocr_elements, selector_id):
    """Escalate ONE selector -- the one the read was requested for.

    Scoped deliberately. A tier-2 read is requested because a specific
    selector could not be grounded, so answering every selector in the recipe
    with it lets an action target's failure populate a verification or context
    selector before the action has happened. An `accept_if_already_present`
    verification fed that way completes a step the user never performed, which
    is the worst possible direction for this to be wrong in.

    Matching uses the selector's own declared names and normalisation, so an
    escalation is bounded by the same trusted vocabulary as the walk. The
    published element keeps `source="ocr"`, which is what renders the hint in
    the inferred colour and what stops `promote()` persisting it (D006, D030).

    Cardinality and the result limit bind exactly as they do for UIA: an
    ambiguous read FAULTS and an over-limit read FAULTS. Neither may become a
    clean absence, which would report "the control is not on screen" about a
    screen that showed it twice, and neither may truncate.
    """
    if not ocr_elements or not selector_id:
        return selectors

    selector = plan.selectors.get(selector_id)
    if selector is None or selectors.get(selector_id):
        # A selector that already matched has no failure to escalate from, and
        # OCR must never displace a confirmed control.
        return selectors

    matches = [
        uia.Candidate(identity=None, element=element)
        for element in ocr_elements
        if uia.matches_trusted_name(
            element.name, selector.names, normalise=selector.normalise
        )
    ]
    if not matches:
        return selectors

    chosen = uia.apply_cardinality(
        matches,
        cardinality=selector.cardinality,
        limit=selector.result_limit,
        label=f"ocr selector {selector_id!r}",
    )
    merged = dict(selectors)
    merged[selector_id] = tuple(candidate.element for candidate in chosen)
    return merged


class CompiledObservationSource:
    """Everything the UI thread must do with a published observation.

    Reading the slot is the smallest part. This also ages the staleness ladder,
    escalates to tier 2 when grounding fails and cancels when it succeeds, and
    checks worker health -- all obligations the v1 driver already met and the
    compiled path had simply not been given.
    """

    def __init__(
        self, service, ladder, health=None, plan=None, clock=None, started_at=None
    ) -> None:
        self.service = service
        self.ladder = ladder
        self.health = health
        self.plan = plan
        self.clock = clock or ladder.clock
        #: When the WORKER started, for the startup grace below. `ladder.age()`
        #: is infinite until the first observation lands, and the health policy
        #: reads that age as a stall -- so an unguarded check restarts a
        #: perfectly healthy worker on the very first read and ends the tour on
        #: the second, before perception has answered once.
        #:
        #: `None` until `arm()` is called. Construction time is the wrong epoch:
        #: the candidate harness builds this composition BEFORE its pre-launch
        #: gates and starts the worker only after they pass, so a slow gate --
        #: a large reload, a human at a dialog -- spends the whole grace before
        #: the worker exists, and its first read restarts something that has
        #: never run.
        self._started_at = started_at
        self._last_observed_at: float | None = None
        self._step = -1
        #: The selector the current tier-2 request was made FOR. A request
        #: carries a step index across the worker boundary; which selector
        #: failed is known only here, and it is what scopes the answer.
        self._requested_selector: str | None = None

    def __call__(self):
        from ghostcursor.reasoning.compiled_tour import TickInput

        if self.health is not None and self._health_may_report():
            # A dead worker leaves its last slot in place, and a slot that
            # never ages looks exactly like a screen that never changes.
            #
            # The VERDICT is what matters, not the call. `check()` returning a
            # reason means the allowed restart has already been spent and the
            # tour is over; discarding it left the source publishing the last
            # stale observation forever, so a dead worker looked like a static
            # screen and the run timed out instead of failing with a cause.
            reason = self.health.check()
            if reason is not None:
                raise PerceptionUnhealthy(reason)

        observation = self.service.latest()
        if observation is None:
            return None

        snapshot = observation.snapshot
        if observation.observed_at != self._last_observed_at:
            self._last_observed_at = observation.observed_at
            self.ladder.observed()

        selectors = dict(snapshot.selector_results)
        if self.plan is not None and observation.tier2_step == self._step:
            selectors = merge_ocr(
                self.plan,
                selectors,
                observation.ocr_elements,
                self._requested_selector,
            )

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
            focus_visited=observation.focus_visited,
        )

    def arm(self, now: float | None = None) -> None:
        """Start the health grace from THIS moment.

        Called when the worker starts, never when this object is built. The
        two are the same instant in production and are not in the candidate
        harness, where the composition is assembled before the pre-launch
        gates and started after them.
        """
        self._started_at = self.clock() if now is None else now

    def _health_may_report(self) -> bool:
        """The startup grace, matching the v1 driver exactly.

        Suppressed only until the first observation lands OR the same
        `dead_after_s` budget has elapsed since the worker started. A worker
        that never produces anything at all is still caught -- just from a
        start time that exists, rather than from an infinite age that was
        never about this worker.
        """
        if self.ladder.age() != float("inf"):
            return True
        if self._started_at is None:
            # Nothing has started, so nothing can be stalling. Judging a
            # worker that does not exist yet is how a healthy one gets
            # restarted before its first read.
            return False
        budget = getattr(self.health, "dead_after_s", 0.0)
        return self.clock() - self._started_at > budget

    def note_grounding(
        self, step_index: int, grounded: bool, selector_id: str | None = None
    ) -> None:
        """The decision half of tier 2 (D035).

        Only the tick loop knows which step is current, which selector it was
        trying to ground, and whether that just failed -- so it is the only
        thing that can ask. The worker does the reading, on its own thread,
        publishing the answer on a LATER observation.

        `selector_id` is what scopes the answer. Absence of a request means
        "not wanted": there is no `wanted` flag, so a success and a step
        boundary must both cancel, or OCR keeps running for a step that no
        longer needs it -- and its result would then be merged into whatever
        selector asked most recently.
        """
        if step_index != self._step:
            self.service.cancel_tier2()
            self._step = step_index
            self._requested_selector = None
        if grounded:
            self.service.report_tier2_grounded(step_index)
            self.service.cancel_tier2()
            self._requested_selector = None
        else:
            self._requested_selector = selector_id
            self.service.request_tier2(step_index)


@dataclass(frozen=True)
class CompiledPerception:
    """The wired stack, plus the one way to start and stop it.

    `start()` exists so no caller has to remember that starting the worker and
    arming the health grace are the same event. They were two steps once, and
    the candidate harness -- which builds this before its pre-launch gates and
    starts it after -- spent the entire grace between them, so its first read
    restarted a worker that had never run.
    """

    service: PerceptionService
    source: CompiledObservationSource
    #: Whether a start has succeeded and not yet been stopped. A dict because
    #: the dataclass is frozen: the identity of this composition never changes,
    #: but whether it is currently running does.
    _running: dict = field(default_factory=dict, repr=False, compare=False)

    def start(self):
        """Start the worker and arm the grace, as one transaction.

        Returns the seams a tour needs: the observation source, the grounding
        hook, and the stop.

        **Atomic.** `PerceptionService.start()` brings up more than one thread,
        so it can fail having already started something -- and a `start()` that
        raises never returns its stop seam, leaving the caller with a partly
        running worker it has no handle on. Anything partially started is torn
        down here before the failure propagates.

        **One-shot while running.** A second call returns the same seams and
        does NOT re-arm. `PerceptionService.start()` treats it as a no-op, so
        re-arming would move the health epoch for a worker that never
        restarted, handing a possibly-stalled one a fresh budget it did not
        earn. After `stop()`, starting again is a genuinely new worker era and
        does arm afresh.
        """
        if self._running.get("started"):
            return self.source, self.source.note_grounding, self.stop

        try:
            self.service.start()
            self.source.arm()
        except BaseException:
            # Tear down before propagating. `stop()` on a service that never
            # got as far as starting must be harmless, and is -- but a failure
            # in teardown must not replace the failure being reported, which
            # is the one that says what actually went wrong.
            try:
                self.service.stop()
            except Exception:
                pass
            raise

        self._running["started"] = True
        return self.source, self.source.note_grounding, self.stop

    def stop(self) -> None:
        """Stop the worker. Safe to call twice, and safe before any start."""
        self._running["started"] = False
        self.service.stop()


def build_compiled_perception(
    workflow,
    clock,
    *,
    tier2=None,
    service=None,
    ladder=None,
    health=None,
) -> CompiledPerception:
    """Wire the whole stack for one workflow and start nothing.

    Starting is the caller's decision, and deliberately so: the candidate
    harness must not have a worker running before its pre-launch gates pass,
    or the run can consume an observation taken while the artifacts were still
    unverified. It is `start()` on the returned object, so the decision of
    WHEN stays with the caller while the mechanics of what starting means stay
    here.
    """
    from ghostcursor.perception.health import WorkerHealth
    from ghostcursor.reasoning.staleness import StalenessLadder

    service = service or compiled_perception_service(workflow, clock, tier2=tier2)
    ladder = ladder or StalenessLadder(clock=clock)
    health = health or WorkerHealth(service=service, ladder=ladder)
    source = CompiledObservationSource(
        service, ladder, health=health, plan=workflow.recipe.plan, clock=clock
    )
    return CompiledPerception(service=service, source=source)
