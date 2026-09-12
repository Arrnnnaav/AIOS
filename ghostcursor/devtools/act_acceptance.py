"""Unattended first-party Act campaign over one explicitly signed candidate.

This is not a production install path.  It uses a caller-owned store and
output root, requires exact reviewed digests, and still executes through the
same PluginStore, action-plan, approval, adapter, and verifier authorities.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
import uuid
import time
from pathlib import Path

from ghostcursor.act_staging import StagingError, abandon, open_staging, publish
from ghostcursor.act_runtime import (
    ActControls,
    ActTarget,
    approve_action_graph,
    execute_approved_graph,
)
from ghostcursor.action_plans import materialize_action_plan
from ghostcursor.packs.workflow import (
    live_window_reader,
    live_windows_for,
    resolve_target,
)
from ghostcursor.devtools.act_probe import ActBoundaryProbe
from ghostcursor.plugins.store import PluginStore


def _emit(kind: str, **values) -> None:
    print(
        json.dumps({"type": kind, **values}, sort_keys=True, separators=(",", ":")),
        flush=True,
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validated_measured_deadlines(args) -> tuple[int, int]:
    """Return production's measured constants; reject explicit policy drift.

    The constants are checked against measurement records by the hermetic
    budget lane. This helper does not itself certify those records or topology.
    """

    from ghostcursor.act_cli import (
        MEASURED_COMPLETION_DEADLINE_MS,
        MEASURED_FIRST_PAINT_DEADLINE_MS,
    )

    derived = (MEASURED_FIRST_PAINT_DEADLINE_MS, MEASURED_COMPLETION_DEADLINE_MS)
    supplied = (
        getattr(args, "first_paint_deadline_ms", None),
        getattr(args, "completion_deadline_ms", None),
    )
    if any(value is not None and type(value) is not int for value in supplied):
        raise ValueError("receipt deadline types disagree with the measured policy")
    if any(value is not None for value in supplied) and supplied != derived:
        raise ValueError(
            "caller-supplied receipt deadlines disagree with the measured policy"
        )
    return derived


def _live_target(target: ActTarget) -> None:
    current = live_window_reader()(target.hwnd)
    if current is None:
        raise RuntimeError("approved PowerPoint HWND no longer exists")
    if current.app.process_id != target.pid:
        raise RuntimeError("approved PowerPoint HWND was recycled")
    if current.app.executable_name.casefold() != target.executable.casefold():
        raise RuntimeError("approved PowerPoint executable changed")
    if current.app.version != target.executable_version:
        raise RuntimeError("approved PowerPoint executable version changed")


def run(args) -> int:
    # Reject explicit policy drift before staging, store setup or desktop work.
    # A pointer plan additionally requires the explicit measured-policy opt-in
    # after the signed operation registry establishes which backend it uses.
    try:
        derived_deadlines = _validated_measured_deadlines(args)
    except ValueError as exc:
        _emit("refused", detail=str(exc))
        return 2
    bundle = args.bundle.resolve()
    final_output = args.output.resolve()
    owned_root = args.owned_root.resolve()
    # The run writes a staging file the runtime owns; the approved final path
    # comes into existence once, atomically, after everything verified. The
    # adapter is handed the STAGING path and is never told where the final
    # deck goes, so it cannot expose a partial one even if asked.
    owned_root.mkdir(parents=True, exist_ok=True)
    area = open_staging(
        final_output, owned_root=owned_root, run_id=uuid.uuid4().hex[:12]
    )
    output = area.staging
    _emit(
        "staged",
        final_path=str(area.final),
        marker=str(area.marker),
        staging_path=str(area.staging),
    )
    if _sha(bundle) != args.bundle_sha256:
        raise RuntimeError("candidate bundle digest disagrees with reviewed bytes")
    public_key = args.public_key.read_bytes()
    store = PluginStore(
        args.store_root.resolve(),
        trusted_keys={args.key_id: public_key},
        core_version=args.core_version,
    )
    installed = store.install(bundle)
    store.enable(installed.plugin_id, installed.version)
    context = store.load_composition_context()
    descriptor = context.adapters[installed.plugin_id]
    template = descriptor.plans[args.plan_id]
    if template.plan_sha256 != args.plan_sha256:
        raise RuntimeError("candidate action plan digest disagrees with reviewed bytes")
    validated = materialize_action_plan(
        template, {"output_path": str(output)}, descriptor.registry
    )
    packs = [
        pack
        for pack in context.catalog.packs.values()
        if pack.plugin_id == installed.plugin_id
    ]
    if len(packs) != 1:
        raise RuntimeError("candidate must own exactly one application pack")
    target = resolve_target(
        packs[0],
        live_windows_for(packs[0]),
        target_hwnd=args.target_hwnd,
        project_root=Path(__file__).resolve().parents[2],
    )
    act_target = ActTarget(
        target.hwnd,
        target.app.process_id,
        target.app.executable_name,
        target.app.version,
    )
    approval = approve_action_graph(
        validated,
        descriptor.registry,
        manifest_sha256=descriptor.manifest_sha256,
        active_index_sha256=context.catalog.index_sha256,
        catalog_generation=context.catalog.generation,
        target=act_target,
        output_path=output,
        owned_output_root=owned_root,
        unattended=True,
        lifetime_s=args.approval_lifetime,
    )
    _emit(
        "approved",
        approval_sha256=approval.approval_sha256,
        graph_sha256=validated.graph_sha256,
        nodes=len(validated.ordered_nodes),
        output_path=str(output),
        target_hwnd=act_target.hwnd,
    )

    def current_authority():
        current = store.load_composition_context()
        adapter = current.adapters[installed.plugin_id]
        return (
            current.catalog.index_sha256,
            current.catalog.generation,
            adapter.plugin_version,
            adapter.manifest_sha256,
            adapter.adapter_sha256,
        )

    def emit_event(event) -> None:
        _emit(
            "event",
            event=event.type,
            node_id=event.node_id,
            operation_id=event.operation_id,
            ordinal=event.ordinal,
            total=event.total,
            detail=event.detail,
            at_s=round(event.at_s, 3),
            region=list(event.region) if event.region else None,
        )

    # Phase A instrumentation.  Absent --diagnostics, nothing is wrapped and
    # this run is byte-identical in behaviour to an uninstrumented one.
    probe = None
    diagnostics = None
    event_sink = emit_event
    verify_observer = None
    if args.diagnostics is not None:
        refusal = campaign_scope_refusal()
        if refusal is not None:
            print(refusal)
            return 2
        path = args.diagnostics.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        # newline="\n" is not optional here. Text mode on Windows translates
        # "\n" to "\r\n", and this file is the instrumented campaign's record:
        # a digest taken over it would reproduce only on the platform that
        # wrote it. Every peer writer in this repository passes it; this one
        # did not, and it is the tool CLAUDE.md names for the campaign -- the
        # sixth appearance of the same root cause (D125-D127, D130, D132).
        diagnostics = path.open("w", encoding="utf-8", newline="\n")

        def write_record(record) -> None:
            diagnostics.write(
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            )
            diagnostics.flush()

        probe = ActBoundaryProbe(output, write_record)
        event_sink = probe.event_sink(emit_event)
        verify_observer = probe.verify_observer()
        write_record(
            {
                "approval_sha256": approval.approval_sha256,
                "graph_sha256": validated.graph_sha256,
                "nodes": len(validated.ordered_nodes),
                "output_path": str(output),
                "type": "diagnostic_run_started",
            }
        )

    from ghostcursor.act_pacing import pace_by_name

    pace = pace_by_name(args.mode)
    controls = ActControls()
    rail = None
    overlay_hwnd = None
    overlay_bounds = None
    overlay_metrics = None
    presentation = None

    # --- a control-driving plan needs a presentation surface ---------------
    #
    # This harness produces the counted acceptance evidence CLAUDE.md requires
    # before a `uia_pattern` operation may be adopted. Without a surface the
    # runtime refuses every such node by construction (D109), so the harness
    # could never produce that evidence -- it was left on the refusal branch
    # while `act_cli` was wired, and an independent review found it.
    operations = descriptor.registry.operations
    draws_pointer = any(
        operations[node.operation_id].draws_a_pointer
        for node in validated.ordered_nodes
    )
    if draws_pointer:
        if not getattr(args, "measured_deadlines", False):
            # Not defaulted. `ReceiptPolicy` says it itself: Phase E derives
            # these from measurement, and a plausible constant here is the
            # placeholder derivation exists to replace (D034).
            _emit(
                "refused",
                detail=(
                    "this plan contains a control-driving operation, so it "
                    "needs the measured receipt policy; pass "
                    "--measured-deadlines "
                    "citing where they are recorded"
                ),
            )
            return 2
        args.first_paint_deadline_ms, args.completion_deadline_ms = derived_deadlines

    # --- interruption probe ------------------------------------------------
    #
    # Fires the SAME `controls.stop()` / `.pause()` a rail click fires, at a
    # named point in a named node, and records when. It exists because the
    # only evidence that Stop works on a live run is a live run that was
    # stopped.
    #
    # A run carrying an injected interrupt can NEVER be acceptance evidence:
    # the result record is stamped `interrupt_probe` instead of `result`, so
    # a campaign counting `result` records cannot pick one up by accident.
    # A flag that aborts a run has no business living unmarked in the harness
    # that produces acceptance evidence.
    interrupt = None
    if args.interrupt_on is not None:
        interrupt = {
            "fired_at": None,
            "kind": args.interrupt_kind,
            "node": args.interrupt_after_node,
            "on": args.interrupt_on,
            "resumed_at": None,
        }
        published_for_interrupt = event_sink

        def event_sink(event):  # noqa: F811 - deliberately wraps the recorder
            if published_for_interrupt is not None:
                published_for_interrupt(event)
            if (
                interrupt["fired_at"] is None
                and event.type == interrupt["on"]
                and event.ordinal == interrupt["node"]
            ):
                interrupt["fired_at"] = time.monotonic()
                _emit(
                    "interrupt_fired",
                    at_ordinal=event.ordinal,
                    # `interrupt_kind`, not `kind`: `_emit`'s own first
                    # parameter is named `kind`, so the obvious name collides
                    # with it and every probe run dies before firing.
                    interrupt_kind=interrupt["kind"],
                    on=event.type,
                )
                if interrupt["kind"] == "pause":
                    controls.pause()

                    # Resumed from a separate thread after a fixed hold, so
                    # the run really does sit paused rather than the pause
                    # being a no-op the main thread lifts immediately.
                    def _resume() -> None:
                        time.sleep(args.pause_hold_s)
                        interrupt["resumed_at"] = time.monotonic()
                        controls.resume()

                    threading.Thread(target=_resume, daemon=True).start()
                else:
                    controls.stop()

    if args.rail:
        # The rail is the ONLY visible surface for an object-model plan.
        # D109: such a node draws no pointer -- there is no control it is
        # clicking -- so what the user sees is the step, a label, and the
        # document changing. Without this a 255-node deck build is invisible.
        from ghostcursor import act_rail

        rail = act_rail.open_rail()
        _emit("rail_opened", hwnd=rail.hwnd, mode=pace.name)
        if args.regions:
            from ghostcursor.overlay import dpi
            from ghostcursor.overlay import window as overlay_window

            left, top, width, height = dpi.virtual_screen_rect()
            overlay_bounds = (left, top, left + width, top + height)
            overlay_hwnd = overlay_window.create_overlay_window()
            overlay_metrics = overlay_window.measure_label(overlay_hwnd, "Adding text")
            _emit("regions_shown", hwnd=overlay_hwnd)
        published = event_sink

        def event_sink(event):  # noqa: F811 - deliberately wraps the recorder
            # The recorder first: the run record must not depend on the rail
            # having accepted an event.
            if published is not None:
                published(event)
            rail.on_event(event)
            rail.poll(controls)
            if overlay_hwnd is not None and event.type == "action_started":
                # 34 of the 255 nodes touch no shape -- add_slide, add_notes,
                # set_transition and the rest. Leaving the previous node's
                # ring standing would point at a region THIS node did not
                # change, which is the same lie D109 forbids of a pointer.
                overlay_window.clear_cue(overlay_hwnd)
            if overlay_hwnd is not None and event.region is not None:
                # The other half of what an object-model node shows (D109):
                # the region genuinely changing, with a label and NO cursor,
                # because nothing was clicked.
                scene = act_rail.region_scene(
                    event.region,
                    (event.operation_id or "").rsplit(".", 1)[-1].replace("_", " "),
                    overlay_metrics,
                    bounds=overlay_bounds,
                )
                if scene is not None:
                    overlay_window.set_cue(overlay_hwnd, scene)

    started_events = []
    _started_sink = event_sink

    def event_sink(event):  # noqa: F811 - records starts for the measurement
        if _started_sink is not None:
            _started_sink(event)
        if event.type == "action_started":
            started_events.append(event)

    if draws_pointer:
        overlay_hwnd, presentation = presentation_for(
            args, controls, overlay_hwnd=overlay_hwnd
        )
        _emit("presentation_ready", hwnd=overlay_hwnd)

    run_started = time.monotonic()
    try:
        result = execute_approved_graph(
            validated,
            descriptor.registry,
            approval,
            descriptor=descriptor,
            current_authority=current_authority,
            revalidate_target=_live_target,
            controls=controls,
            event_sink=event_sink,
            verify_observer=verify_observer,
            presentation=presentation,
            pace=pace,
        )
    finally:
        finished = time.monotonic()
        if overlay_hwnd is not None:
            from ghostcursor.overlay import window as overlay_window

            overlay_window.clear_cue(overlay_hwnd)
            overlay_window.destroy_overlay_window(overlay_hwnd)
        if rail is not None:
            from ghostcursor import act_rail

            _emit(
                "rail_closed",
                stop_requested=rail.stopping,
                events=len(rail.events),
                last_status=act_rail.bar.get_status(rail.hwnd),
            )
            act_rail.close_rail(rail)
        if diagnostics is not None:
            if probe is not None and probe.probe_faults:
                _emit("probe_faults", count=probe.probe_faults)
            diagnostics.close()
    published_sha256 = None
    if result.completed:
        try:
            published_sha256 = publish(area)
            _emit(
                "published",
                final_path=str(area.final),
                sha256=published_sha256,
            )
        except StagingError as exc:
            # A run that verified but could not publish is NOT a completed
            # run. Reporting it as one would mean the record said a deck
            # exists at a path where nothing does.
            _emit("publish_refused", detail=str(exc), final_path=str(area.final))
            abandon(area)
            _emit(
                "interrupt_probe" if interrupt is not None else "result",
                code="publish_refused",
                completed=False,
                completed_nodes=len(result.completed_node_ids),
                detail=str(exc),
                failed_node_id=None,
                output_path=str(area.staging),
                phase=result.phase.value,
            )
            return 4
    else:
        # Stopped, refused or failed. The staging file stays, labelled, and
        # the final path was never created.
        abandon(area)
        _emit("not_published", final_path=str(area.final), staging=str(area.staging))

    _emit(
        "interrupt_probe" if interrupt is not None else "result",
        code=result.code.value,
        completed=result.completed,
        completed_nodes=len(result.completed_node_ids),
        detail=result.detail,
        failed_node_id=result.failed_node_id,
        output_path=str(area.final) if published_sha256 else result.output_path,
        published_sha256=published_sha256,
        phase=result.phase.value,
    )
    if interrupt is not None:
        fired = interrupt["fired_at"]
        _emit(
            "interrupt_measured",
            fired=fired is not None,
            interrupt_kind=interrupt["kind"],
            # Seconds from the interrupt being requested to the run returning.
            # This is the number D020's 0.5s ceiling applies to.
            response_s=None if fired is None else round(finished - fired, 4),
            resumed=interrupt["resumed_at"] is not None,
            # Every node that STARTED after the interrupt was requested. The
            # guarantee is that no NEW node begins; the in-flight one may
            # still land, because its COM call executes in the application's
            # process and killing the adapter cannot un-issue it.
            started_after=[
                event.ordinal
                for event in started_events
                if fired is not None and event.at_s > fired - run_started
            ],
            # For a PAUSE, stop-to-return is the whole run and says nothing.
            # What matters is that the run actually sat still: the gap from
            # the pause being requested to the next node starting. A pause
            # that the executor ignored would show a gap near zero.
            held_s=None
            if fired is None
            else next(
                (
                    round(event.at_s - (fired - run_started), 4)
                    for event in started_events
                    if event.at_s > fired - run_started
                ),
                None,
            ),
        )
    return 0 if result.completed else 3



#: A counted campaign is three separate invocations of this tool, and a target
#: reference is only comparable inside one campaign scope. With no scope
#: exported, each run derives its own, the three records disagree, and
#: `render_add_slide_evidence` refuses them as coming from three campaigns --
#: AFTER all three runs have been performed on a real desktop with a human
#: clicking approvals. The refusal belongs before the first run (D133).
CAMPAIGN_SCOPE_VARIABLE = "GHOSTCURSOR_CAMPAIGN_SCOPE"
CAMPAIGN_SALT_VARIABLE = "GHOSTCURSOR_CAMPAIGN_SALT"


def campaign_scope_refusal(environment=None) -> str | None:
    """The reason diagnostics may not be written, or None if they may."""

    import os

    environment = os.environ if environment is None else environment
    if environment.get(CAMPAIGN_SCOPE_VARIABLE) and environment.get(
        CAMPAIGN_SALT_VARIABLE
    ):
        return None
    return (
        "refusing to write diagnostics without a campaign scope.\n"
        "A counted campaign's runs must share one scope and salt, or their "
        "target references cannot be compared and the evidence renderer will "
        "reject all three after the fact. Export both before the first run, "
        "and discard the salt when the campaign ends -- it is never "
        "written down:\n"
        f"  $env:{CAMPAIGN_SCOPE_VARIABLE} = ...\n"
        f"  $env:{CAMPAIGN_SALT_VARIABLE}  = ..."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one reviewed GhostCursor Act candidate"
    )
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--bundle-sha256", required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--owned-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan-id", default="build-investor-deck-v1")
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument(
        "--target-hwnd",
        type=int,
        default=None,
        help=(
            "Optional narrowing when several PowerPoint windows are open. "
            "Omit it and resolve_target binds the single matching window or "
            "refuses and names every candidate (D075) -- a handle narrows, it "
            "never supplies identity."
        ),
    )
    parser.add_argument(
        "--interrupt-on",
        default=None,
        help="DIAGNOSTIC. Fire Stop/Pause when this event type is "
        "published for --interrupt-after-node. A run using this emits an "
        "interrupt_probe record, never a result, so it can never be "
        "counted as acceptance evidence.",
    )
    parser.add_argument("--interrupt-after-node", type=int, default=1)
    parser.add_argument("--interrupt-kind", choices=("stop", "pause"), default="stop")
    parser.add_argument("--pause-hold-s", type=float, default=3.0)
    parser.add_argument(
        "--mode",
        choices=("quick", "watch"),
        default="quick",
        help="quick runs at the executor's own speed; watch paces each "
        "node so a person can follow it, staying stoppable throughout",
    )
    parser.add_argument(
        "--regions",
        action="store_true",
        help="highlight the document region each node changes, with a "
        "label and no cursor (requires --rail)",
    )
    parser.add_argument(
        "--rail",
        action="store_true",
        help="show the Stop/Pause safety rail and the executor-reported step",
    )
    parser.add_argument(
        "--measured-deadlines",
        action="store_true",
        help="use the measured receipt policy for control-driving plans",
    )
    parser.add_argument(
        "--first-paint-deadline-ms",
        type=int,
        default=None,
        help=(
            "receipt deadline for the first painted frame; required for a "
            "plan containing a control-driving operation, and deliberately "
            "not defaulted (D034)"
        ),
    )
    parser.add_argument(
        "--completion-deadline-ms",
        type=int,
        default=None,
        help="receipt deadline from the start receipt to completion",
    )
    parser.add_argument("--core-version", default="1.0.0")
    parser.add_argument("--approval-lifetime", type=float, default=1800.0)
    parser.add_argument(
        "--diagnostics",
        type=Path,
        default=None,
        help=(
            "Write Phase A node-boundary records as JSONL. Diagnostic only: it "
            "adds package digests and verifier timing around each node and "
            "changes nothing about authorization or verification."
        ),
    )
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())


def presentation_for(args, controls, *, overlay_hwnd=None):
    """Build the cue surface a control-driving plan needs.

    Extracted so it can be tested. Inline, two properties this harness exists
    to hold were unprotected, and an independent review reverted both with the
    whole suite still green: passing `presentation=None` (a verbatim revert of
    the change that let the harness run such a node at all) and hardwiring
    `keep_running` to True (the precise defect the same change removed).

    Returns the window handle alongside the surface, because the caller owns
    destroying it and must not have to guess whether one was created here.
    """

    from ghostcursor.act_cli import default_cue_budget
    from ghostcursor.act_overlay import overlay_presenter
    from ghostcursor.act_protocol import ReceiptPolicy, TrustClass
    from ghostcursor.act_runtime import _bind_presentation_surface
    from ghostcursor.overlay import window as overlay_window

    # The POLICY first, then the window. `ReceiptPolicy` refuses a
    # non-positive deadline, and building the window first meant
    # `--first-paint-deadline-ms 0` created a topmost click-through window
    # covering the whole screen and then raised past every cleanup, leaving it
    # up with no way to close it.
    policy = ReceiptPolicy(
        first_paint_deadline_ms=args.first_paint_deadline_ms,
        completion_deadline_ms=args.completion_deadline_ms,
    )
    # One window for the run, shared with the region highlights when those are
    # on. A second topmost full-screen window would fight this one for the
    # same pixels.
    if overlay_hwnd is None:
        overlay_hwnd = overlay_window.create_overlay_window()
    surface = _bind_presentation_surface(
        overlay_presenter(
            overlay_hwnd,
            budget=default_cue_budget(),
            policy=policy,
            label_for=lambda observation: str(
                dict(getattr(observation, "identity", {}) or {}).get("name", "")
            ),
            backend_trust=TrustClass.LIVE_STATE,
            # Stop must reach the cue, or a presentation keeps painting after
            # the operator asked the run to stop.
            keep_running=lambda: not controls.stop_event.is_set(),
        ),
        policy,
    )
    return overlay_hwnd, surface
