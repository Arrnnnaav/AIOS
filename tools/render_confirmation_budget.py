"""Derive the UIA confirmation deadlines from retained live records.

The collector records raw samples only. This renderer is the sole place that
turns them into policy numbers, and ``--check`` makes the rendered document
reproducible from the exact bytes on disk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


REQUIRED_RUNS = 3
MARGIN = 2.0
REQUIRED_SAMPLES = 60
REQUIRED_SCHEMA_VERSION = 1
TIMING_FIELDS = (
    "confirmation_round_trip_ms",
    "confirmation_to_request_write_ms",
)


class EvidenceRefused(Exception):
    """Raised when records cannot substantiate a complete derivation."""


def _load(path: Path, *, excluded: bool = False) -> dict:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw:
        raise EvidenceRefused(f"{path}: JSON must be UTF-8/LF without BOM")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceRefused(f"{path}: invalid JSON ({exc})") from exc
    if not isinstance(value, dict):
        raise EvidenceRefused(f"{path}: record is not an object")
    expected_keys = {
        "application_version", "failure", "is_acceptance_evidence", "operation",
        "record_kind", "sample_timeout_s", "samples", "samples_completed",
        "samples_requested", "schema_version", "selector_sha256", "target_ref",
        "target_scope", "visual_budget",
    }
    if set(value) != expected_keys:
        raise EvidenceRefused(f"{path}: record fields are not exact")
    if value.get("schema_version") != REQUIRED_SCHEMA_VERSION:
        raise EvidenceRefused(f"{path}: unsupported schema version")
    if value.get("record_kind") != "confirmation_budget_diagnostic":
        raise EvidenceRefused(f"{path}: wrong record kind")
    if value.get("is_acceptance_evidence") is not False:
        raise EvidenceRefused(f"{path}: record must be diagnostic-only")
    if excluded:
        failure = value.get("failure")
        if not isinstance(failure, dict) or not failure.get("failure_class"):
            raise EvidenceRefused(f"{path}: an excluded record must carry its failure")
        return value
    if value.get("failure") is not None:
        raise EvidenceRefused(f"{path}: failed record cannot derive policy")
    if value.get("samples_requested") != REQUIRED_SAMPLES:
        raise EvidenceRefused(f"{path}: expected {REQUIRED_SAMPLES} requested samples")
    samples = value.get("samples")
    if value.get("samples_completed") != REQUIRED_SAMPLES or not isinstance(samples, list):
        raise EvidenceRefused(f"{path}: incomplete sample set")
    if len(samples) != REQUIRED_SAMPLES:
        raise EvidenceRefused(f"{path}: sample count is not {REQUIRED_SAMPLES}")
    if not isinstance(value.get("operation"), str) or not value["operation"]:
        raise EvidenceRefused(f"{path}: operation is incomplete")
    if not all(isinstance(v, str) and v for v in (
        value.get("application_version"),
        value.get("target_ref"),
        value.get("target_scope"),
        value.get("selector_sha256"),
    )):
        raise EvidenceRefused(f"{path}: applicability identity is incomplete")
    for index, sample in enumerate(samples, 1):
        if not isinstance(sample, dict) or set(sample) != set(TIMING_FIELDS):
            raise EvidenceRefused(f"{path}: sample {index} fields are invalid")
        for field in TIMING_FIELDS:
            value_ = sample[field]
            if (
                isinstance(value_, bool)
                or not isinstance(value_, (int, float))
                or not math.isfinite(float(value_))
                or float(value_) < 0
            ):
                raise EvidenceRefused(f"{path}: sample {index} {field} is invalid")
    return value


def _p99(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.99) - 1)]


def derive(paths: list[Path], excluded: list[Path] | None = None) -> dict[str, object]:
    if len(paths) != REQUIRED_RUNS:
        raise EvidenceRefused(f"expected exactly {REQUIRED_RUNS} records")
    if len({path.resolve() for path in paths}) != len(paths):
        raise EvidenceRefused("the same record was given more than once")
    records = [(_load(path), path) for path in paths]
    contexts = {
        (
            record["application_version"],
            record["operation"],
            record["selector_sha256"],
        )
        for record, _ in records
    }
    if len(contexts) != 1:
        raise EvidenceRefused("records do not share application, operation, and selector")
    run_values = {
        field: [
            [float(sample[field]) for sample in record["samples"]]
            for record, _ in records
        ]
        for field in TIMING_FIELDS
    }
    summaries = {}
    for name in TIMING_FIELDS:
        per_run = run_values[name]
        p99 = max(_p99(values) for values in per_run)
        maximum = max(max(values) for values in per_run)
        summaries[name] = {
            "samples": sum(len(values) for values in per_run),
            "p99_ms": round(p99, 3),
            "max_ms": round(maximum, 3),
            "derived_deadline_ms": math.ceil(p99 * MARGIN),
        }
    return {
        "record_sources": [path.name for _, path in records],
        "record_digests": [hashlib.sha256(path.read_bytes()).hexdigest() for _, path in records],
        "application_version": records[0][0]["application_version"],
        "operation": records[0][0]["operation"],
        "selector_sha256": records[0][0]["selector_sha256"],
        "margin_over_p99": MARGIN,
        "confirmation_round_trip_ms": summaries["confirmation_round_trip_ms"],
        "confirmation_to_request_write_ms": summaries["confirmation_to_request_write_ms"],
        "excluded": [
            {
                "name": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "failure_class": record["failure"]["failure_class"],
                "sample": record["failure"].get("sample"),
                "completed": record["samples_completed"],
                "requested": record["samples_requested"],
            }
            for record, path in ((_load(path, excluded=True), path) for path in excluded or [])
        ],
    }


def render(report: dict[str, object]) -> str:
    rt = report["confirmation_round_trip_ms"]
    wr = report["confirmation_to_request_write_ms"]
    lines = [
        "# Confirmation-to-request budget",
        "",
        "Derived from three independent diagnostic runs; this is not acceptance evidence.",
        "",
        f"- Operation: `{report['operation']}`",
        f"- PowerPoint version: `{report['application_version']}`",
        f"- Selector digest: `{report['selector_sha256']}`",
        f"- Margin over p99: `{report['margin_over_p99']:.1f}x` (chosen headroom)",
        "",
        "| Measurement | Samples | p99 (ms) | Max (ms) | Derived deadline (ms) |",
        "|---|---:|---:|---:|---:|",
        f"| Confirmation round trip | {rt['samples']} | {rt['p99_ms']:.3f} | {rt['max_ms']:.3f} | **{rt['derived_deadline_ms']}** |",
        f"| Confirmation to request write | {wr['samples']} | {wr['p99_ms']:.3f} | {wr['max_ms']:.3f} | **{wr['derived_deadline_ms']}** |",
        "",
        "## Source records",
        "",
    ]
    lines.extend(f"- `{name}` — SHA-256 `{digest}`" for name, digest in zip(report["record_sources"], report["record_digests"]))
    lines.append("")
    if report["excluded"]:
        lines.extend([
            "## Excluded records",
            "",
            "Retained and not used in the derivation, because the run did not complete.",
            "A record keeps only its failure class and the sample it stopped at; the",
            "refusal code and detail are not retained, so the cause is not recorded.",
            "",
        ])
        lines.extend(
            f"- `{item['name']}` — SHA-256 `{item['sha256']}` — `{item['failure_class']}` "
            f"at sample {item['sample']}, {item['completed']}/{item['requested']} completed"
            for item in report["excluded"]
        )
        lines.append("")
    lines.append("The production policy must be derived from these values and refuse when either signed deadline is exceeded.")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, nargs=3, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--excluded", type=Path, nargs="*", default=[])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    report = derive(args.records, args.excluded)
    rendered = render(report)
    if args.check:
        if not args.out.is_file() or args.out.read_bytes() != rendered.encode("utf-8"):
            raise SystemExit("refused: rendered confirmation budget is stale")
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
