"""Collect live confirmation-to-request timing without calling it acceptance.

Each sample runs the existing one-node PowerPoint diagnostic in a fresh Python
process. That path launches the verifier on the working-tree payload (not the
signed bundle), confirms the UIA control,
mints its diagnostic stand-in authorization, writes the real UIA request, and
independently verifies that exactly one slide was added. This orchestrator
only aggregates the two durations observed at that boundary.

This tool performs real effects: every successful sample adds one slide to the
single visible PowerPoint presentation. It therefore refuses to start unless
``--acknowledge-live-effects`` is supplied. Its output is D034 measurement
material, never acceptance evidence; the diagnostic still bypasses the real
PlanApproval boundary.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import uuid
from typing import Callable, Mapping


class MeasurementRefused(RuntimeError):
    """The requested measurement could not produce trustworthy samples."""


def _exact_positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MeasurementRefused(f"{label} must be a positive integer")
    return value


def _timing_from(record: object) -> dict[str, float]:
    if not isinstance(record, dict):
        raise MeasurementRefused("the live diagnostic emitted no JSON object")
    if record.get("verified") is not True or record.get("failure") is not None:
        raise MeasurementRefused("the live diagnostic did not verify its effect")
    timing = record.get("confirmation_timing")
    expected = {
        "confirmation_round_trip_ms",
        "confirmation_to_request_write_ms",
    }
    if not isinstance(timing, dict) or set(timing) != expected:
        raise MeasurementRefused("the live diagnostic timing fields are invalid")
    clean: dict[str, float] = {}
    for name in sorted(expected):
        value = timing[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or float(value) < 0.0
        ):
            raise MeasurementRefused(f"the live diagnostic {name} is invalid")
        clean[name] = float(value)
    return clean


def _failure(index: int, completed, child_record: object) -> dict[str, object]:
    detail = None
    if isinstance(child_record, dict):
        value = child_record.get("failure")
        if isinstance(value, str) and value:
            detail = value.split(":", 1)[0][:80]
    return {
        "sample": index,
        "returncode": int(getattr(completed, "returncode", -1)),
        "record_present": isinstance(child_record, dict),
        "failure_class": detail,
    }


def collect(
    *,
    samples: int,
    frame_budget_ms: int,
    traversal_ms: int,
    settle_ms: int,
    sample_timeout_s: int = 60,
    operation: str = "powerpoint.new_slide_uia",
    launch: Callable[..., object] = subprocess.run,
    executable: str = sys.executable,
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Run serial live samples and retain failure instead of selecting it out."""

    samples = _exact_positive_int(samples, "samples")
    frame_budget_ms = _exact_positive_int(frame_budget_ms, "frame_budget_ms")
    traversal_ms = _exact_positive_int(traversal_ms, "traversal_ms")
    settle_ms = _exact_positive_int(settle_ms, "settle_ms")
    sample_timeout_s = _exact_positive_int(sample_timeout_s, "sample_timeout_s")
    if not isinstance(operation, str) or not operation:
        raise MeasurementRefused("operation must be a non-empty string")

    env = dict(os.environ if environment is None else environment)
    env["GHOSTCURSOR_CAMPAIGN_SCOPE"] = uuid.uuid4().hex[:12]
    env["GHOSTCURSOR_CAMPAIGN_SALT"] = secrets.token_bytes(32).hex()

    timings: list[dict[str, float]] = []
    target_refs: set[str] = set()
    target_scopes: set[str] = set()
    versions: set[str] = set()
    selector_digests: set[str] = set()
    expected_context: tuple[str, str, str, str] | None = None
    failure = None

    with tempfile.TemporaryDirectory(prefix="ghostcursor-confirmation-budget-") as raw:
        temp = Path(raw)
        for index in range(1, samples + 1):
            child_path = temp / f"sample-{index:03d}.json"
            command = [
                executable,
                "-m",
                "ghostcursor.devtools.act_live_node",
                "--operation",
                operation,
                "--frame-budget-ms",
                str(frame_budget_ms),
                "--traversal-ms",
                str(traversal_ms),
                "--settle-ms",
                str(settle_ms),
                "--json",
                str(child_path),
            ]
            try:
                completed = launch(
                    command,
                    capture_output=True,
                    cwd=Path(__file__).resolve().parents[2],
                    env=env,
                    text=True,
                    timeout=sample_timeout_s,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                failure = {
                    "sample": index,
                    "returncode": -1,
                    "record_present": child_path.is_file(),
                    "failure_class": type(exc).__name__,
                }
                break
            child_record = None
            if child_path.is_file():
                try:
                    child_record = json.loads(child_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    child_record = None
            if getattr(completed, "returncode", -1) != 0:
                failure = _failure(index, completed, child_record)
                break
            try:
                timing = _timing_from(child_record)
                if child_record.get("operation") != operation:
                    raise MeasurementRefused("the diagnostic operation changed")
                target_ref = child_record.get("target_ref")
                target_scope = child_record.get("target_scope")
                version = child_record.get("executable_version")
                selector = child_record.get("selector")
                selector_sha = (
                    selector.get("sha256") if isinstance(selector, dict) else None
                )
                if not all(
                    isinstance(value, str) and value
                    for value in (target_ref, target_scope, version, selector_sha)
                ):
                    raise MeasurementRefused(
                        "the diagnostic applicability fields are invalid"
                    )
            except MeasurementRefused:
                failure = _failure(index, completed, child_record)
                break
            context = (target_ref, target_scope, version, selector_sha)
            if expected_context is None:
                expected_context = context
            elif context != expected_context:
                failure = {
                    "sample": index,
                    "returncode": 0,
                    "record_present": True,
                    "failure_class": "applicability_drifted",
                }
                break
            timings.append(timing)
            target_refs.add(target_ref)
            target_scopes.add(target_scope)
            versions.add(version)
            selector_digests.add(selector_sha)

    return {
        "schema_version": 1,
        "record_kind": "confirmation_budget_diagnostic",
        "is_acceptance_evidence": False,
        "operation": operation,
        "samples_requested": samples,
        "samples_completed": len(timings),
        "failure": failure,
        "sample_timeout_s": sample_timeout_s,
        "visual_budget": {
            "frame_budget_ms": frame_budget_ms,
            "traversal_ms": traversal_ms,
            "settle_ms": settle_ms,
        },
        "application_version": next(iter(versions), None),
        "selector_sha256": next(iter(selector_digests), None),
        "target_ref": next(iter(target_refs), None),
        "target_scope": next(iter(target_scopes), None),
        "samples": timings,
    }


def _parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=60)
    parser.add_argument("--frame-budget-ms", type=int, required=True)
    parser.add_argument("--traversal-ms", type=int, default=300)
    parser.add_argument("--settle-ms", type=int, default=250)
    parser.add_argument("--sample-timeout-s", type=int, default=60)
    parser.add_argument("--operation", default="powerpoint.new_slide_uia")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--acknowledge-live-effects", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    arguments = _parse_arguments(argv)
    if not arguments.acknowledge_live_effects:
        raise SystemExit(
            "refused: this diagnostic adds one real slide per successful sample; "
            "pass --acknowledge-live-effects"
        )
    if arguments.out.exists():
        raise SystemExit(f"refused: output already exists: {arguments.out}")
    try:
        record = collect(
            samples=arguments.samples,
            frame_budget_ms=arguments.frame_budget_ms,
            traversal_ms=arguments.traversal_ms,
            settle_ms=arguments.settle_ms,
            sample_timeout_s=arguments.sample_timeout_s,
            operation=arguments.operation,
        )
    except MeasurementRefused as exc:
        raise SystemExit(f"refused: {exc}") from None
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    clean = (
        record["failure"] is None
        and record["samples_completed"] == record["samples_requested"]
    )
    return 0 if clean else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
