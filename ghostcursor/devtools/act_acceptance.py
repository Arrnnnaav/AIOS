"""Unattended first-party Act campaign over one explicitly signed candidate.

This is not a production install path.  It uses a caller-owned store and
output root, requires exact reviewed digests, and still executes through the
same PluginStore, action-plan, approval, adapter, and verifier authorities.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

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
    bundle = args.bundle.resolve()
    output = args.output.resolve()
    owned_root = args.owned_root.resolve()
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
        )

    # Phase A instrumentation.  Absent --diagnostics, nothing is wrapped and
    # this run is byte-identical in behaviour to an uninstrumented one.
    probe = None
    diagnostics = None
    event_sink = emit_event
    verify_observer = None
    if args.diagnostics is not None:
        path = args.diagnostics.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        diagnostics = path.open("w", encoding="utf-8")

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

    controls = ActControls()
    rail = None
    if args.rail:
        # The rail is the ONLY visible surface for an object-model plan.
        # D109: such a node draws no pointer -- there is no control it is
        # clicking -- so what the user sees is the step, a label, and the
        # document changing. Without this a 255-node deck build is invisible.
        from ghostcursor import act_rail

        rail = act_rail.open_rail()
        _emit("rail_opened", hwnd=rail.hwnd)
        published = event_sink

        def event_sink(event):  # noqa: F811 - deliberately wraps the recorder
            # The recorder first: the run record must not depend on the rail
            # having accepted an event.
            if published is not None:
                published(event)
            rail.on_event(event)
            rail.poll(controls)

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
        )
    finally:
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
    _emit(
        "result",
        code=result.code.value,
        completed=result.completed,
        completed_nodes=len(result.completed_node_ids),
        detail=result.detail,
        failed_node_id=result.failed_node_id,
        output_path=result.output_path,
        phase=result.phase.value,
    )
    return 0 if result.completed else 3


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
        "--rail",
        action="store_true",
        help="show the Stop/Pause safety rail and the executor-reported step",
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
