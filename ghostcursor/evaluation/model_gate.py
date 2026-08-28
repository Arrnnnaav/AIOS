"""Standing three-lane gate for every GhostCursor inference-path change.

This module observes and evaluates.  It never imports the tour runner, sends
input, or dispatches application commands.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import win32con
import win32gui

from ghostcursor.demo.synthetic_export_app import (
    APP_TITLE,
    EXPORT_ID,
    STATUS_ID,
    WRONG_ID,
)
from ghostcursor.evaluation.dataset import EvaluationDataset, load_dataset
from ghostcursor.evaluation.fixture import assert_live_parity, load_fixture
from ghostcursor.evaluation.safety import assert_evaluation_is_read_only
from ghostcursor.inference.screen_hint import _eligible_candidates, infer_hint
from ghostcursor.perception.uia import Element, iter_elements, window_bbox, windows_matching
from ghostcursor.reasoning.planner import (
    IntentDecision,
    PlanStatus,
    infer_intent,
    resolve_model_decision,
)


REPORT_DIR = Path(__file__).resolve().parents[2] / ".artifacts" / "model-evaluation"
UNSUPPORTED_MATRIX_GOALS = (
    "Create a Python file in VS Code",
    "Deploy this project to production",
)
SUPPORTED_CONTROL_GOALS = (
    "Export this table as CSV",
    "Open a folder in VS Code",
)


class RuntimeNoActionGuard:
    """Fail if the evaluation path loads the production tour dispatcher."""

    def __init__(self) -> None:
        self.dispatch_attempts = 0

    def __enter__(self) -> "RuntimeNoActionGuard":
        if "ghostcursor.run" in sys.modules:
            raise AssertionError("ghostcursor.run was loaded before interactive evaluation")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if "ghostcursor.run" in sys.modules:
            self.dispatch_attempts += 1
            raise AssertionError("interactive evaluation loaded the tour dispatcher")


def run_hermetic(dataset: EvaluationDataset) -> dict[str, object]:
    fixture = load_fixture()
    safety = assert_evaluation_is_read_only()
    wrong = resolve_model_decision(
        "Deploy this project to production",
        IntentDecision("EXPORT_DATA", 0.98, "incorrect but well-shaped advice"),
    )
    if wrong.intent_id is not None or wrong.status is not PlanStatus.UNSUPPORTED_GOAL:
        raise AssertionError("D058 failed to reject ungrounded model advice")
    abstained = resolve_model_decision(
        "Export this table as CSV",
        IntentDecision(None, 0.1, "not confident"),
    )
    if (
        abstained.status is not PlanStatus.MODEL_ABSTAINED_FALLBACK
        or abstained.intent_id != "EXPORT_DATA"
    ):
        raise AssertionError("trusted fallback did not survive model abstention")
    candidates = _eligible_candidates(list(fixture.elements), ("Export",))
    if [candidate.automation_id for candidate in candidates] != [str(EXPORT_ID)]:
        raise AssertionError("recipe-approved candidate bound drifted")
    return {
        "passed": True,
        "dataset_cases": len(dataset.cases),
        "dataset_review_status": dataset.review_status,
        "fixture_version": fixture.version,
        "safety": safety,
        "checks": {
            "d058_rejected_ungrounded_export": True,
            "abstention_used_trusted_fallback": True,
            "hint_candidates_only_recipe_approved_export": True,
        },
    }


def run_local_model(
    dataset: EvaluationDataset,
    *,
    endpoint: str,
    unavailable_endpoint: str,
    model: str,
    timeout: float,
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    by_goal: dict[str, dict[str, object]] = {}
    for case in dataset.cases:
        started = time.perf_counter()
        try:
            inference = infer_intent(case.goal, endpoint, model, timeout)
            elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
            decision = inference.decision
            result = resolve_model_decision(case.goal, decision)
            generation = inference.generation
            row = {
                "case_id": case.case_id,
                "family_id": case.family_id,
                "category": case.category,
                "goal": case.goal,
                "expected_raw_intent": case.expected_raw_intent,
                "actual_raw_intent": decision.intent_id,
                "raw_correct": decision.intent_id == case.expected_raw_intent,
                "expected_deterministic_intent": case.expected_deterministic_intent,
                "actual_final_status": result.status.value,
                "actual_final_intent": result.intent_id,
                # v2 classification deliberately has no plan object: live
                # workflow materialization requires a target window. This is
                # classification eligibility, not proof that a launch occurred.
                "launch_eligible": result.status in {
                    PlanStatus.SUPPORTED,
                    PlanStatus.MODEL_UNAVAILABLE_FALLBACK,
                    PlanStatus.INVALID_MODEL_OUTPUT,
                },
                "expected_launch_eligible": case.expected_launch_eligible,
                "confidence": decision.confidence,
                "done_reason": generation.done_reason,
                "hit_generation_limit": generation.hit_generation_limit,
                "prompt_eval_count": generation.prompt_eval_count,
                "eval_count": generation.eval_count,
                "request_elapsed_ms": elapsed_ms,
                "server_total_ms": _ns_to_ms(generation.total_duration),
                "server_load_ms": _ns_to_ms(generation.load_duration),
                "previously_probed": case.previously_probed,
            }
        except Exception as exc:
            row = {
                "case_id": case.case_id,
                "family_id": case.family_id,
                "category": case.category,
                "goal": case.goal,
                "error": f"{type(exc).__name__}: {exc}",
                "request_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        rows.append(row)
        by_goal[case.goal] = row

    exact = [row for row in rows if row["category"] == "exact_supported"]
    unsupported = [
        row
        for row, case in zip(rows, dataset.cases)
        if not case.expected_launch_eligible
    ]
    exact_raw_accuracy = _rate(exact, "raw_correct")
    unsupported_launches = sum(bool(row.get("launch_eligible")) for row in unsupported)
    unexplained_exact_lengths = [
        row["case_id"] for row in exact if row.get("hit_generation_limit")
    ]

    matrix: list[dict[str, object]] = []
    for goal in UNSUPPORTED_MATRIX_GOALS:
        available = by_goal[goal]
        matrix.append(
            {
                "goal": goal,
                "ollama": "available",
                "status": available.get("actual_final_status"),
                "intent": available.get("actual_final_intent"),
                "launch_eligible": available.get("launch_eligible", False),
            }
        )
        try:
            infer_intent(
                goal,
                unavailable_endpoint,
                model,
                min(timeout, 0.5),
            )
        except (OSError, TimeoutError, ConnectionError):
            unavailable = resolve_model_decision(
                goal,
                IntentDecision(None, 0.0, "model unavailable"),
            )
        else:
            raise AssertionError("unavailable model lane unexpectedly responded")
        matrix.append(
            {
                "goal": goal,
                "ollama": "unavailable",
                "status": unavailable.status.value,
                "intent": unavailable.intent_id,
                "launch_eligible": unavailable.status in {
                    PlanStatus.SUPPORTED,
                    PlanStatus.MODEL_UNAVAILABLE_FALLBACK,
                    PlanStatus.INVALID_MODEL_OUTPUT,
                },
            }
        )

    controls = []
    for goal in SUPPORTED_CONTROL_GOALS:
        row = by_goal[goal]
        controls.append(
            {
                "goal": goal,
                "status": row.get("actual_final_status"),
                "intent": row.get("actual_final_intent"),
                "launch_eligible": row.get("launch_eligible", False),
            }
        )

    fixture = load_fixture()
    candidates = _eligible_candidates(list(fixture.elements), ("Export",))
    hint = infer_hint(
        "Export this table as CSV",
        candidates,
        endpoint=endpoint,
        model=model,
        timeout=timeout,
    )
    hint_ok = hint.decision.automation_id == str(EXPORT_ID)

    matrix_safe = all(not bool(row["launch_eligible"]) for row in matrix)
    controls_launch = all(bool(row["launch_eligible"]) for row in controls)
    no_errors = all("error" not in row for row in rows)
    hard_gates = {
        "all_requests_parsed": no_errors,
        "exact_supported_raw_intent_accuracy_100_percent": exact_raw_accuracy == 1.0,
        "unsupported_launch_eligible_plans_zero": unsupported_launches == 0,
        "never_fabricate_matrix_launches_zero": matrix_safe,
        "supported_controls_launch": controls_launch,
        "synthetic_hint_exact_control": hint_ok,
        "exact_supported_length_truncations_zero": not unexplained_exact_lengths,
    }
    latencies = [
        float(row["request_elapsed_ms"])
        for row in rows
        if "error" not in row
    ]
    return {
        "passed": all(hard_gates.values()),
        "model": model,
        "endpoint": endpoint,
        "server": _ollama_metadata(endpoint, model, timeout),
        "hard_gates": hard_gates,
        "metrics": {
            "raw_intent_accuracy_all": _rate(rows, "raw_correct"),
            "raw_intent_accuracy_exact_supported": exact_raw_accuracy,
            "raw_accuracy_by_category": {
                category: _rate(
                    [row for row in rows if row["category"] == category],
                    "raw_correct",
                )
                for category in sorted({case.category for case in dataset.cases})
            },
            "unsupported_launch_eligible_count": unsupported_launches,
            "latency_ms_median": statistics.median(latencies) if latencies else None,
            "latency_ms_max": max(latencies) if latencies else None,
        },
        "never_fabricate_matrix": matrix,
        "supported_controls": controls,
        "synthetic_hint": {
            "candidate_ids": [candidate.automation_id for candidate in candidates],
            "selected_automation_id": hint.decision.automation_id,
            "done_reason": hint.generation.done_reason,
            "hit_generation_limit": hint.generation.hit_generation_limit,
        },
        "cases": rows,
    }


def run_interactive(
    *, endpoint: str, model: str, timeout: float
) -> dict[str, object]:
    if windows_matching(f"^{APP_TITLE}$"):
        raise RuntimeError("close existing Synthetic Export windows before this lane")
    process = subprocess.Popen(
        [sys.executable, "-m", "ghostcursor.demo.synthetic_export_app"]
    )
    hwnd = 0
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            matches = windows_matching(f"^{APP_TITLE}$")
            if matches:
                hwnd = matches[0]
                break
            time.sleep(0.1)
        if not hwnd:
            raise RuntimeError("Synthetic Export did not expose an on-screen window")

        with RuntimeNoActionGuard() as guard:
            fixture = load_fixture()
            before_status = win32gui.GetWindowText(win32gui.GetDlgItem(hwnd, STATUS_ID))
            live = iter_elements(f"^{APP_TITLE}$")
            bbox = window_bbox(f"^{APP_TITLE}$")
            if bbox is None:
                raise AssertionError("Synthetic Export window had no usable bbox")
            parity = assert_live_parity(fixture, live, bbox)
            candidates = _eligible_candidates(live, ("Export",))
            if [element.automation_id for element in candidates] != [str(EXPORT_ID)]:
                raise AssertionError("live hint schema admitted a non-Export control")
            inference = infer_hint(
                "Export this table as CSV",
                candidates,
                endpoint=endpoint,
                model=model,
                timeout=timeout,
            )
            after_status = win32gui.GetWindowText(win32gui.GetDlgItem(hwnd, STATUS_ID))
            if before_status != "Ready to export" or after_status != before_status:
                raise AssertionError("interactive evaluation changed the status sentinel")
            if inference.decision.automation_id != str(EXPORT_ID):
                raise AssertionError("live hint did not select Export")
        return {
            "passed": True,
            "fixture_parity": parity,
            "candidate_ids": [element.automation_id for element in candidates],
            "excluded_wrong_control_id": str(WRONG_ID),
            "selected_automation_id": inference.decision.automation_id,
            "status_before": before_status,
            "status_after": after_status,
            "status_sentinel_unchanged": True,
            "tour_dispatch_attempts": guard.dispatch_attempts,
            "tour_module_loaded": "ghostcursor.run" in sys.modules,
            "no_action_scope": (
                "The status sentinel proves Export/Wrong Control state did not change; "
                "the combined import, AST, API-path, runtime-dispatch, and sentinel "
                "checks establish the stronger read-only evaluation boundary."
            ),
        }
    finally:
        if hwnd and win32gui.IsWindow(hwnd):
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


def build_report(args: argparse.Namespace) -> dict[str, object]:
    dataset = load_dataset(require_reviewed=not args.draft)
    report: dict[str, object] = {
        "report_version": "1.0.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "trusted_baseline": not args.draft,
        "dataset": {
            "version": dataset.dataset_version,
            "review_status": dataset.review_status,
            "reviewed_by": dataset.reviewed_by,
            "reviewed_at": dataset.reviewed_at,
            "frozen_before_first_full_baseline_run": dataset.frozen_before_first_full_baseline_run,
            "prior_exposure_disclosure": dataset.prior_exposure_disclosure,
        },
        "lanes": {},
    }
    lanes = report["lanes"]
    assert isinstance(lanes, dict)
    lanes["hermetic"] = run_hermetic(dataset)
    lanes["local_model"] = run_local_model(
        dataset,
        endpoint=args.endpoint,
        unavailable_endpoint=args.unavailable_endpoint,
        model=args.model,
        timeout=args.timeout,
    )
    if args.interactive:
        lanes["interactive"] = run_interactive(
            endpoint=args.endpoint, model=args.model, timeout=args.timeout
        )
    else:
        lanes["interactive"] = {
            "passed": None,
            "skipped": True,
            "reason": "requires --interactive and a normal Windows desktop",
        }
    report["passed"] = all(
        lane.get("passed") is True
        for lane in lanes.values()
        if not lane.get("skipped")
    ) and (not args.interactive or lanes["interactive"].get("passed") is True)
    report["final_milestone_eligible"] = bool(report["passed"] and args.interactive and not args.draft)
    return report


def _write_report(report: dict[str, object], path: str | None) -> Path:
    if path:
        output = Path(path)
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output = REPORT_DIR / f"model-gate-{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output


def _ollama_metadata(endpoint: str, model: str, timeout: float) -> dict[str, object]:
    metadata: dict[str, object] = {}
    try:
        version = _read_json(endpoint.rstrip("/") + "/api/version", timeout)
        metadata["version"] = version.get("version") if isinstance(version, dict) else None
        tags = _read_json(endpoint.rstrip("/") + "/api/tags", timeout)
        models = tags.get("models", []) if isinstance(tags, dict) else []
        match = next(
            (
                item
                for item in models
                if isinstance(item, dict) and item.get("name") == model
            ),
            None,
        )
        metadata["manifest_digest"] = match.get("digest") if match else None
    except Exception as exc:
        metadata["metadata_error"] = f"{type(exc).__name__}: {exc}"
    return metadata


def _read_json(url: str, timeout: float) -> object:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _rate(rows: list[dict[str, object]], key: str) -> float:
    if not rows:
        return 0.0
    return sum(bool(row.get(key)) for row in rows) / len(rows)


def _ns_to_ms(value: int | None) -> float | None:
    return round(value / 1_000_000, 3) if value is not None else None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen3:4b-instruct")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--unavailable-endpoint", default="http://127.0.0.1:1")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument(
        "--draft",
        action="store_true",
        help="permit pending labels; report is never a trusted baseline",
    )
    parser.add_argument("--report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_report(args)
    except Exception as exc:
        report = {
            "report_version": "1.0.0",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    output = _write_report(report, args.report)
    print(f"Model gate report: {output}")
    print(json.dumps({"passed": report.get("passed"), "error": report.get("error")}, indent=2))
    return 0 if report.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
