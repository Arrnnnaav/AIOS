"""Runs ONE control-driving node against a live application, end to end.

This is the smallest thing that exercises the whole path: read the document,
read the control, show the pointer travelling to it, hold it there, dispatch
the pattern on the control the pointer is on, and verify the result from a
separate signed process. Every one of those has been tested in isolation;
this is the first caller that makes them run together against real UIA.

It is a DIAGNOSTIC, not the product runner and not an acceptance harness.
It takes one node, not a graph, and it prints what happened at each stage so
a failure names the stage it failed at rather than producing a bare refusal.
Nothing it writes is acceptance evidence.

    py -3.12 -m ghostcursor.devtools.act_live_node ^
        --operation powerpoint.new_slide_uia ^
        --frame-budget-ms 2

Safety: the run is stoppable. ESC is polled between every cue frame and
during the settle, on the same callback that pumps messages, so a stuck
presentation cannot outlive the key. The pointer this draws is an OVERLAY —
the real cursor is never moved and no input is synthesized.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Callable

from ghostcursor.devtools.candidate_acceptance import window_reference, window_scope
from types import SimpleNamespace

import win32api
import win32con
import win32gui
import win32process

from ghostcursor.act_node import NodeRefused, execute_node
from ghostcursor.act_cli import default_cue_budget, measured_receipt_policy
from ghostcursor.act_overlay import CueBudget, overlay_presenter
from ghostcursor.act_protocol import (
    PresentationRequest,
    TrustClass,
)
from ghostcursor.act_uia_session import UiaSessionError, build_uia_session
from ghostcursor.action import load_operation_registry
from ghostcursor.adapter_host import AdapterHost, VerifierHost
from ghostcursor.overlay import window as overlay_window
from ghostcursor.selectors import load_action_selector

PAYLOAD = Path(__file__).resolve().parents[2] / "plugins/sources/powerpoint/payload"
PLUGIN_ID = "ghostcursor.powerpoint"
PLUGIN_VERSION = "1.0.0"


@dataclass
class _ConfirmationTiming:
    """Measure the freshness window without becoming part of authority.

    The two marks bracket exactly the interval the future production policy
    must bound: the signed verifier/control confirmation has returned, then
    the adapter's UIA ``execute`` frame is written to its private pipe. Raw
    monotonic timestamps are deliberately not persisted; only durations are.
    """

    clock_ns: Callable[[], int] = time.monotonic_ns
    confirmation_started_ns: int | None = None
    confirmation_completed_ns: int | None = None
    execute_written_ns: int | None = None

    def confirmation_started(self) -> None:
        if self.confirmation_started_ns is not None:
            raise RuntimeError("confirmation timing was started twice")
        self.confirmation_started_ns = self.clock_ns()

    def confirmation_completed(self) -> None:
        if self.confirmation_started_ns is None:
            raise RuntimeError("confirmation timing completed before it started")
        if self.confirmation_completed_ns is not None:
            raise RuntimeError("confirmation timing completed twice")
        self.confirmation_completed_ns = self.clock_ns()

    def request_written(self, frame) -> None:
        if not (
            isinstance(frame, dict)
            and frame.get("type") == "execute"
            and "pattern" in frame
        ):
            return
        if self.confirmation_completed_ns is None:
            raise RuntimeError("UIA request was written before confirmation completed")
        if self.execute_written_ns is not None:
            raise RuntimeError("more than one UIA request was written for one node")
        self.execute_written_ns = self.clock_ns()

    def record(self) -> dict[str, float]:
        if (
            self.confirmation_started_ns is None
            or self.confirmation_completed_ns is None
            or self.execute_written_ns is None
        ):
            raise RuntimeError("confirmation timing is incomplete")
        return {
            "confirmation_round_trip_ms": round(
                (self.confirmation_completed_ns - self.confirmation_started_ns)
                / 1_000_000.0,
                3,
            ),
            "confirmation_to_request_write_ms": round(
                (self.execute_written_ns - self.confirmation_completed_ns)
                / 1_000_000.0,
                3,
            ),
        }


def _measured_write(timing: _ConfirmationTiming, write, frame) -> None:
    """Observe a successful protocol write; never replace its behavior."""

    write(frame)
    timing.request_written(frame)


def _default_visual_durations() -> tuple[int, int]:
    """Use the durations for which the production receipt policy was measured."""

    budget = default_cue_budget()
    return budget.traversal_ms, budget.settle_ms


def find_window(class_name: str):
    """The one visible window of that class, or refuse.

    One or none, never the foreground (D075). Two open decks is an ambiguity
    a diagnostic must not resolve on the operator's behalf either.
    """

    found: list[tuple[int, int]] = []

    def visit(hwnd, _acc):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetClassName(hwnd) == class_name:
            _thread, pid = win32process.GetWindowThreadProcessId(hwnd)
            found.append((hwnd, pid))
        return True

    win32gui.EnumWindows(visit, None)
    if len(found) != 1:
        raise SystemExit(
            f"expected exactly one visible {class_name} window, found {len(found)}: "
            + ", ".join(f"hwnd={h} pid={p}" for h, p in found)
        )
    return found[0]


def executable_of(pid: int) -> tuple[str, str]:
    import psutil

    process = psutil.Process(pid)
    path = process.exe()
    version = ""
    try:
        info = win32api.GetFileVersionInfo(path, "\\")
        version = "{}.{}.{}.{}".format(
            info["FileVersionMS"] >> 16,
            info["FileVersionMS"] & 0xFFFF,
            info["FileVersionLS"] >> 16,
            info["FileVersionLS"] & 0xFFFF,
        )
    except Exception:  # noqa: BLE001 - version is descriptive here, not authority
        version = "unknown"
    return path, version


def main() -> int:
    default_traversal_ms, default_settle_ms = _default_visual_durations()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", default="powerpoint.new_slide_uia")
    parser.add_argument("--window-class", default="PPTFrameClass")
    parser.add_argument(
        "--frame-budget-ms",
        type=int,
        required=True,
        help="measured paint cost; see docs/evidence/act-paint-budget.md",
    )
    parser.add_argument(
        "--stop-after-ms",
        type=int,
        default=None,
        help="DIAGNOSTIC. Stop the run this many ms after the first paint, "
        "so a Stop can be landed inside the traversal or the settle.",
    )
    parser.add_argument(
        "--stop-before",
        choices=("confirmation", "dispatch"),
        default=None,
        help="DIAGNOSTIC. Stop at a phase boundary rather than on a clock.",
    )
    parser.add_argument("--traversal-ms", type=int, default=default_traversal_ms)
    parser.add_argument("--settle-ms", type=int, default=default_settle_ms)
    parser.add_argument("--json", type=Path, default=None)
    arguments = parser.parse_args()

    stages: list[tuple[str, str]] = []

    def note(stage: str, detail: str = "") -> None:
        stages.append((stage, detail))
        print(f"  {stage:22s} {detail}")

    print("--- target ---")
    hwnd, pid = find_window(arguments.window_class)
    executable, version = executable_of(pid)
    note("window", f"hwnd={hwnd} pid={pid}")
    note("executable", f"{executable} {version}")

    print("--- signed data ---")
    operations_bytes = (PAYLOAD / "ghostcursor/operations.json").read_bytes()
    uia_entry = PAYLOAD / "ghostcursor/adapter/uia_adapter.py"
    # The LIVE-state verifier. The other one in this payload reads a saved
    # .pptx, which is the wrong evidence for an effect that exists only in
    # the running application.
    verifier_entry = PAYLOAD / "ghostcursor/adapter/powerpoint_live_verifier.py"
    adapter_sha = hashlib.sha256(uia_entry.read_bytes()).hexdigest()
    registry = load_operation_registry(
        operations_bytes,
        plugin_id=PLUGIN_ID,
        plugin_version=PLUGIN_VERSION,
        adapter_sha256=hashlib.sha256(
            (PAYLOAD / "ghostcursor/adapter/powerpoint_adapter.py").read_bytes()
        ).hexdigest(),
    )
    spec = registry.operations[arguments.operation]
    if not spec.draws_a_pointer:
        raise SystemExit(f"{arguments.operation} is an object-model operation")
    selector = load_action_selector(
        PAYLOAD,
        spec.identity.selector_id,
        spec.identity.selector_sha256,
        control_type=spec.identity.control_type,
    )
    note("operation", f"{spec.operation_id} backend={spec.backend} {spec.uia_pattern}")
    note(
        "selector", f"{selector.control_type} {selector.name!r} {selector.sha256[:12]}"
    )
    note("uia adapter", f"{adapter_sha[:12]} ({uia_entry.name})")

    descriptor = SimpleNamespace(
        plugin_id=PLUGIN_ID,
        plugin_version=PLUGIN_VERSION,
        payload_root=PAYLOAD,
        entrypoint=uia_entry,
        adapter_sha256=adapter_sha,
    )
    # The session context is an AdapterHost constructor argument, not a
    # descriptor field. Putting it on the descriptor sent the adapter an
    # empty context, which it refuses -- and the refusal arrived as
    # `OSError: [Errno 22]` from reading the pipe of a child that had already
    # exited, naming nothing about the actual cause.
    session_context = {
        "target": {
            "executable": executable,
            "executable_version": version,
            "hwnd": hwnd,
            "pid": pid,
        }
    }
    verifier_descriptor = SimpleNamespace(
        plugin_id=PLUGIN_ID,
        plugin_version=PLUGIN_VERSION,
        payload_root=PAYLOAD,
        verifier=verifier_entry,
        verifier_sha256=hashlib.sha256(verifier_entry.read_bytes()).hexdigest(),
    )

    node = SimpleNamespace(
        node_id="live-001", operation_id=arguments.operation, parameters={}
    )
    session_id = uuid.uuid4().hex

    print("--- overlay ---")
    overlay_hwnd = overlay_window.create_overlay_window()
    note("overlay", f"hwnd={overlay_hwnd}")

    stopped = {"at": None, "first_poll": None}

    def keep_running() -> bool:
        # ESC, polled on the same callback that pumps messages, so a cue that
        # is still drawing is always a cue that can still be stopped.
        now = time.monotonic()
        if stopped["first_poll"] is None:
            stopped["first_poll"] = now
        if arguments.stop_after_ms is not None and stopped["at"] is None:
            if (now - stopped["first_poll"]) * 1000.0 >= arguments.stop_after_ms:
                stopped["at"] = now
                note("stop requested", f"{arguments.stop_after_ms}ms after first poll")
                return False
        if stopped["at"] is not None:
            return False
        return not (win32api.GetAsyncKeyState(win32con.VK_ESCAPE) & 0x8000)

    def should_continue() -> bool:
        """The phase-boundary Stop. Fires once, at the named boundary."""

        if arguments.stop_before is None:
            return True
        reached = stopped.setdefault("boundaries", [])
        boundary = "confirmation" if len(reached) == 0 else "dispatch"
        reached.append(boundary)
        if boundary == arguments.stop_before:
            stopped["at"] = time.monotonic()
            note("stop requested", f"at the {boundary} boundary")
            return False
        return True

    receipts: list[tuple[str, float]] = []
    lifecycle: list[str] = []
    confirmation_timing = _ConfirmationTiming()
    receipt_policy = measured_receipt_policy()

    overlay = overlay_presenter(
        overlay_hwnd,
        budget=CueBudget(
            traversal_ms=arguments.traversal_ms,
            settle_ms=arguments.settle_ms,
            frame_budget_ms=arguments.frame_budget_ms,
        ),
        policy=receipt_policy,
        label_for=lambda _observation: selector.name,
        backend_trust=TrustClass.LIVE_STATE,
        keep_running=keep_running,
        on_state=lambda _node, state: lifecycle.append(state.value),
        on_receipt=lambda receipt, at: receipts.append((receipt.kind.value, at)),
    )

    started = time.monotonic()
    elapsed_at_stop = {"end": None}
    dispatched = {"count": 0}
    outcome = None
    failure = None
    try:
        with AdapterHost(
            descriptor,
            session_nonce=uuid.uuid4().hex,
            session_context=session_context,
        ) as host:
            note("adapter", "started")
            original_write = host._write

            def measured_write(frame) -> None:
                # Diagnostic observation only. The original write remains the
                # sole protocol path and its return value is not replaced.
                _measured_write(confirmation_timing, original_write, frame)

            host._write = measured_write
            session = build_uia_session(
                host=host,
                verifier=VerifierHost(verifier_descriptor),
                payload_root=PAYLOAD,
                overlay=overlay,
                policy=receipt_policy,
                session_id=session_id,
                operation_for=lambda _n: spec,
                target={
                    "executable": executable,
                    "executable_version": version,
                    "hwnd": hwnd,
                    "pid": pid,
                },
                validation_sha256=hashlib.sha256(operations_bytes).hexdigest(),
                output_path=str(PAYLOAD),
            )

            request = PresentationRequest(
                session_id=session_id,
                cue_id="live-001:1",
                nonce=uuid.uuid4().hex,
                presentation_generation=1,
                frame_generation=1,
                geometry_required=True,
            )

            print("--- node ---")

            def observe(mode):
                if mode == "confirm_before":
                    confirmation_timing.confirmation_started()
                observation = session.observe(node, mode)
                if mode == "confirm_before":
                    confirmation_timing.confirmation_completed()
                return observation

            outcome = execute_node(
                node,
                spec,
                request=request,
                policy=session.policy,
                observe=observe,
                present=session.present,
                # This diagnostic mints no real approval. It stands in for
                # the `AuthorizedAction` core would mint, carrying only the
                # field the dispatch reads. That is exactly why this is not
                # an acceptance harness: the authority boundary is stubbed
                # here and is not stubbed in `_execute_approved_graph`.
                authorize=lambda facts: SimpleNamespace(
                    authorization_sha256=hashlib.sha256(
                        f"{session_id}:live-001".encode()
                    ).hexdigest()
                ),
                dispatch=lambda token, confirmed: (
                    dispatched.__setitem__("count", dispatched["count"] + 1),
                    session.dispatch(node, token, confirmed),
                )[1],
                verify=lambda _node, baseline: _verify(
                    VerifierHost(verifier_descriptor),
                    node,
                    hashlib.sha256(operations_bytes).hexdigest(),
                    str(PAYLOAD),
                    {
                        "executable": executable,
                        "executable_version": version,
                        "hwnd": hwnd,
                        "pid": pid,
                    },
                    baseline=baseline.semantic,
                    postconditions=spec.postconditions,
                ),
                clock=lambda: time.monotonic() * 1000.0,
                should_continue=should_continue,
                on_state=session.on_state and (lambda s: session.on_state(node, s)),
            )
    except (NodeRefused, UiaSessionError) as exc:
        failure = f"{type(exc).__name__}: {getattr(exc, 'detail', exc)}"
        note("refused", failure)
    except Exception as exc:  # noqa: BLE001 - a diagnostic reports, never hides
        failure = f"{type(exc).__name__}: {exc}"
        note("error", failure)
    finally:
        elapsed = time.monotonic() - started
        elapsed_at_stop["end"] = time.monotonic()
        overlay.release()
        overlay_window.destroy_overlay_window(overlay_hwnd)

    print("--- result ---")
    if stopped["at"] is not None:
        note("stop response", f"{(elapsed_at_stop['end'] - stopped['at']):.4f}s")
        note("dispatched after stop", str(dispatched["count"]))
    if outcome is not None:
        note("verified", str(outcome.verified))
        note("trust", outcome.trust.value)
        note("detail", outcome.detail)
        note("identity", json.dumps(outcome.identity_record or {}))
        timing_record = confirmation_timing.record()
        note(
            "confirmation timing",
            f"read={timing_record['confirmation_round_trip_ms']:.3f}ms "
            f"to-write={timing_record['confirmation_to_request_write_ms']:.3f}ms",
        )
    else:
        timing_record = None
    note("lifecycle", " -> ".join(lifecycle))
    note("receipts", ", ".join(f"{k}@{at:.0f}ms" for k, at in receipts))
    note("elapsed", f"{elapsed:.2f}s")

    if arguments.json is not None:
        arguments.json.write_text(
            json.dumps(
                {
                    "elapsed_s": round(elapsed, 3),
                    "executable": executable,
                    "executable_version": version,
                    "failure": failure,
                    # The runtime bindings above need the real handle; this
                    # artifact does not, and a diagnostic file is exactly where
                    # a raw handle escapes into the repository (D128).
                    "target_ref": window_reference(hwnd),
                    "target_scope": window_scope(),
                    "identity": dict(outcome.identity_record or {})
                    if outcome
                    else None,
                    "lifecycle": lifecycle,
                    "operation": arguments.operation,
                    "receipts": [[k, round(at, 1)] for k, at in receipts],
                    "selector": {
                        "control_type": selector.control_type,
                        "name": selector.name,
                        "sha256": selector.sha256,
                    },
                    "verified": bool(outcome.verified) if outcome else False,
                    "confirmation_timing": timing_record,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
            newline="\n",
        )
        print(f"\nwrote {arguments.json}")

    return 0 if outcome is not None and outcome.verified else 1


def _verify(
    verifier,
    node,
    validation_sha256,
    output_path,
    target,
    *,
    baseline=None,
    postconditions=(),
) -> bool:
    answer = verifier.verify(
        node=node,
        validation_sha256=validation_sha256,
        output_path=output_path,
        target=target,
        timeout_s=15.0,
        baseline=baseline,
        postconditions=postconditions,
    )
    print(f"  {'verifier':22s} {answer.detail} observed={dict(answer.observed)}")
    return bool(answer.verified)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
