"""Runs a counted campaign of Act attempts, and refuses to miscount one.

The 3/3 acceptance policy is a claim about consecutive clean runs, so the
thing that counts them has to be at least as careful as the thing that runs
them. What this exists to prevent:

**A probe counted as an attempt.** `act_acceptance` can inject a Stop for
interruption testing, and stamps such a run `interrupt_probe` instead of
`result`. This counts `result` records only, and refuses outright if it sees
an `interrupt_probe` — not because one is invalid, but because its presence
means the campaign was configured to interrupt itself, which is never what a
counted campaign wants.

**A reused store or output path.** Each attempt gets its own store root and
its own output path. Reusing either would let one attempt's state decide the
next one's outcome, and "three consecutive" would stop meaning three
independent runs.

**A minimised target failing obscurely.** Measured on 3 September 2026: a
build refused with `no window matches pack powerpoint` because PowerPoint had
minimised itself, and `live_windows_for` excludes minimised windows
deliberately — a hint drawn over a window nobody can see points at nothing.
That is correct behaviour and a terrible campaign failure, because the
message names the pack rather than the cause. This restores minimised
windows explicitly before each attempt and says that it did.

**A campaign that continues past a failure.** The first non-clean attempt
ends it. Continuing would produce "3 of 5 passed", which is not what the
policy asks and reads like a pass rate.

Serial only. D025 forbids two desktop/UIA sessions at once, so attempts never
overlap and the runner does not offer a parallel mode to be tempted by.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

#: Record type that counts. Anything else is not an attempt outcome.
RESULT_RECORD = "result"

#: Record type that must never be counted, and whose presence ends a campaign.
PROBE_RECORD = "interrupt_probe"


class CampaignError(RuntimeError):
    """A campaign that must not start, or must not continue.

    ``attempts`` holds every attempt that ran before the refusal, the failing
    one included, so a report can retain them rather than silently dropping
    the attempt that ended the campaign.
    """

    def __init__(self, message: str, attempts: tuple = ()) -> None:
        super().__init__(message)
        self.attempts = tuple(attempts)


#: Keys that would publish a raw window handle or process id if retained.
FORBIDDEN_RECORD_KEYS = frozenset(
    {"hwnd", "target_hwnd", "pid", "process_id", "window_handle"}
)


@dataclass(frozen=True)
class Attempt:
    """One run's outcome, as read from its own records."""

    index: int
    completed: bool
    code: str
    nodes: int
    published_sha256: str | None
    output_path: str | None
    seconds: float
    records: tuple = field(default=())

    @property
    def clean(self) -> bool:
        """A clean attempt completed AND published. A run that verified every
        node but could not publish is not a clean attempt: the artifact the
        campaign is about does not exist."""

        return self.completed and bool(self.published_sha256)


def restore_target_windows(class_name: str) -> tuple[int, ...]:
    """Bring minimised windows of this class back, and report what was found.

    Returns every visible window handle of the class, minimised ones having
    been restored. The caller decides whether the count is acceptable —
    choosing a target is never this function's job (D075).
    """

    import win32con
    import win32gui

    found: list[int] = []

    def visit(hwnd, _):
        if win32gui.GetClassName(hwnd) == class_name and win32gui.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    win32gui.EnumWindows(visit, None)
    for hwnd in found:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    return tuple(found)


def read_records(stdout: str) -> tuple[dict, ...]:
    """Every JSON record a run emitted, in order."""

    records = []
    for line in stdout.splitlines():
        if not line.startswith("{"):
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return tuple(records)


def attempt_from(index: int, records, seconds: float) -> Attempt:
    """Read one attempt's outcome, or refuse to read one.

    Refuses rather than defaulting. A run with no result record has an
    unknown outcome, and an unknown outcome counted as anything at all is
    how a campaign reports a pass it did not observe.
    """

    probes = [r for r in records if r.get("type") == PROBE_RECORD]
    if probes:
        raise CampaignError(
            "attempt emitted an interrupt_probe record; a campaign configured "
            "to interrupt itself cannot count its own attempts"
        )
    results = [r for r in records if r.get("type") == RESULT_RECORD]
    if len(results) != 1:
        raise CampaignError(
            f"attempt emitted {len(results)} result records, expected exactly one"
        )
    result = results[0]
    return Attempt(
        index=index,
        completed=bool(result.get("completed")),
        code=str(result.get("code")),
        nodes=int(result.get("completed_nodes") or 0),
        published_sha256=result.get("published_sha256"),
        output_path=result.get("output_path"),
        seconds=round(seconds, 3),
        records=records,
    )


def run_campaign(
    *,
    attempts: int,
    build_command,
    workspace: Path,
    window_class: str,
    restore=restore_target_windows,
    launch=None,
    settle_s: float = 2.0,
) -> tuple[Attempt, ...]:
    """Run attempts serially, stopping at the first that is not clean.

    ``build_command`` is given (index, store_root, output_path) and returns
    the argv for one attempt. Passing the paths in rather than letting the
    command choose them is what makes "fresh per attempt" a property of the
    runner rather than a habit of the caller.
    """

    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 1:
        raise CampaignError("a campaign needs at least one attempt")
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    runner = subprocess.run if launch is None else launch

    # One scope and one salt for the whole campaign, inherited by every
    # attempt. Each attempt runs in its own process, so a label derived from a
    # process-local counter would be identical in all of them regardless of
    # which window they bound -- which is how the equality check the evidence
    # rests on became a tautology (D129). The salt is never written down: it
    # lives in this process and its children, and dies with the campaign.
    scope_environment = dict(os.environ)
    scope_environment["GHOSTCURSOR_CAMPAIGN_SCOPE"] = uuid.uuid4().hex[:12]
    scope_environment["GHOSTCURSOR_CAMPAIGN_SALT"] = secrets.token_bytes(32).hex()

    completed: list[Attempt] = []
    for index in range(1, attempts + 1):
        windows = restore(window_class)
        if len(windows) != 1:
            # The count only: a handle in this message would reach the
            # retained report (D128), which is the pressure behind D139.
            raise CampaignError(
                f"attempt {index} needs exactly one visible {window_class} window, "
                f"found {len(windows)}",
                completed,
            )
        if settle_s:
            time.sleep(settle_s)

        token = uuid.uuid4().hex[:10]
        store = workspace / f"store-{index:02d}-{token}"
        output = workspace / "out" / f"attempt-{index:02d}-{token}.pptx"
        output.parent.mkdir(parents=True, exist_ok=True)

        started = time.monotonic()
        proc = runner(
            build_command(index, store, output),
            capture_output=True,
            text=True,
            timeout=1800,
            env=scope_environment,
        )
        seconds = time.monotonic() - started

        try:
            attempt = attempt_from(index, read_records(proc.stdout), seconds)
        except CampaignError as exc:
            raise CampaignError(
                f"{exc}; child exit {proc.returncode}, last stderr line: "
                f"{redacted_last_line(getattr(proc, 'stderr', '') or '')}",
                completed,
            ) from exc
        completed.append(attempt)
        if not attempt.clean:
            raise CampaignError(
                f"attempt {index} was not clean ({attempt.code}, "
                f"{attempt.nodes} nodes, published="
                f"{bool(attempt.published_sha256)}); the campaign ends here "
                f"rather than reporting a pass rate",
                completed,
            )
    return tuple(completed)


_LONG_NUMBER = re.compile(r"(?<![0-9a-fA-F])[0-9]{4,}(?![0-9a-fA-F])")
_HANDLE_TEXT = re.compile(r"(?i)\b(hwnd|handle|pid|process id)\b\W{0,3}[0-9]{3,}")


def redacted_last_line(text: str) -> str:
    """The last non-empty line of a child's stderr, with every standalone
    number of four or more digits replaced. A crash's cause is kept; a window
    handle or process id quoted in a refusal (D075 names every candidate) is
    not."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "(none)"
    return _LONG_NUMBER.sub("<n>", lines[-1])[:400]


def record_leaks(value, path="") -> list[str]:
    """Every forbidden key or handle-shaped string anywhere in ``value``."""

    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_RECORD_KEYS:
                found.append(f"{path}{key}")
            found.extend(record_leaks(item, f"{path}{key}."))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(record_leaks(item, f"{path}{index}."))
    elif isinstance(value, str) and _HANDLE_TEXT.search(value):
        found.append(f"{path}<text>")
    return found


def retained_records(records) -> list[dict]:
    """An attempt's records as they will be retained, or a refusal.

    Refuses rather than scrubbing: a record that carries a raw handle means
    the harness emitted one, and quietly deleting the key would hide that the
    tool publishing evidence regressed (D128, D139).
    """

    kept = []
    for record in records:
        leaked = record_leaks(record)
        if leaked:
            raise CampaignError(
                f"a {record.get('type')!r} record carries {sorted(leaked)}; "
                "the harness must not emit raw handles or process ids"
            )
        kept.append(dict(record))
    return kept


def campaign_report(
    *,
    status: str,
    detail: str | None,
    attempts,
    attempts_requested: int,
    binding: dict,
) -> dict:
    """The whole campaign as one retainable record.

    ``binding`` names what ran: commit, pinned manifest, bundle and plan
    digests, and mode. Every attempt that ran is present with its full record
    stream, so the renderer checks consecutiveness and that nothing was
    dropped, rather than trusting a summary line.
    """

    return {
        "attempts": [
            {
                "code": a.code,
                "completed": a.completed,
                "index": a.index,
                "nodes": a.nodes,
                "published_sha256": a.published_sha256,
                "records": retained_records(a.records),
                "seconds": a.seconds,
            }
            for a in attempts
        ],
        "attempts_requested": attempts_requested,
        "binding": dict(binding),
        "campaign": status,
        "detail": detail,
        "path": "harness",
        "schema_version": 2,
    }


def main() -> int:  # pragma: no cover - thin CLI over run_campaign
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--window-class", default="PPTFrameClass")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--bundle-sha256", required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--plan-id", default="build-investor-deck-v1")
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--mode", choices=("quick", "watch"), default="quick")
    parser.add_argument(
        "--campaign-id",
        required=True,
        help="declared in the committed campaign ledger before attempt 1 (D152)",
    )
    arguments = parser.parse_args()

    from ghostcursor.devtools.campaign_pins import (
        CampaignPreflightError,
        bundle_manifest_sha256,
        campaign_directory,
        repository_commit,
        require_ledgered,
        require_pinned_manifest,
    )

    try:
        report_path = campaign_directory(arguments.campaign_id) / "report.json"
    except CampaignPreflightError as exc:
        print(json.dumps({"campaign": "refused", "detail": str(exc)}))
        return 3
    if report_path.exists():
        print(json.dumps({"campaign": "refused", "detail": "report exists; never overwrite a campaign"}))
        return 3
    try:
        manifest = bundle_manifest_sha256(arguments.bundle.resolve())
        require_pinned_manifest(manifest)
        commit = repository_commit()
        require_ledgered(arguments.campaign_id, path="harness", plan_id=arguments.plan_id)
    except (CampaignPreflightError, OSError, KeyError) as exc:
        print(json.dumps({"campaign": "refused", "detail": str(exc)}, sort_keys=True))
        return 3

    def build(index, store, output):
        return [
            sys.executable,
            "-m",
            "ghostcursor.devtools.act_acceptance",
            "--bundle",
            str(arguments.bundle.resolve()),
            "--bundle-sha256",
            arguments.bundle_sha256,
            "--public-key",
            str(arguments.public_key.resolve()),
            "--key-id",
            arguments.key_id,
            "--store-root",
            str(store),
            "--owned-root",
            str(output.parent),
            "--output",
            str(output),
            "--plan-id",
            arguments.plan_id,
            "--plan-sha256",
            arguments.plan_sha256,
            "--mode",
            arguments.mode,
            # Used only by a plan with a pointer-drawing node; the measured
            # policy is checked against its records by the hermetic lane.
            "--measured-deadlines",
        ]

    binding = {
        "bundle_sha256": arguments.bundle_sha256,
        "campaign_id": arguments.campaign_id,
        "commit": commit,
        "manifest_sha256": manifest,
        "mode": arguments.mode,
        "plan_id": arguments.plan_id,
        "plan_sha256": arguments.plan_sha256,
    }
    status, detail, code = "clean", None, 0
    try:
        attempts = run_campaign(
            attempts=arguments.attempts,
            build_command=build,
            workspace=arguments.workspace,
            window_class=arguments.window_class,
        )
    except CampaignError as exc:
        attempts, status, detail, code = exc.attempts, "refused", str(exc), 3

    try:
        report = campaign_report(
            status=status,
            detail=detail,
            attempts=attempts,
            attempts_requested=arguments.attempts,
            binding=binding,
        )
    except CampaignError as exc:
        report = campaign_report(
            status="refused",
            detail=str(exc),
            attempts=(),
            attempts_requested=arguments.attempts,
            binding=binding,
        )
        code = 3
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(
        (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    print(json.dumps({"campaign": report["campaign"], "report": str(report_path)}))
    return code

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "Attempt",
    "CampaignError",
    "FORBIDDEN_RECORD_KEYS",
    "attempt_from",
    "campaign_report",
    "retained_records",
    "read_records",
    "restore_target_windows",
    "run_campaign",
]
