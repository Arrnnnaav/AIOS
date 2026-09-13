"""Measures how long a cue actually takes to start and to finish presenting.

`ReceiptPolicy` refuses to default its two deadlines, for the same reason
`CueBudget` refuses to default `frame_budget_ms`: a plausible constant is the
placeholder measurement exists to replace, and it is also the number every
test would silently agree with. This is the thing that produces those numbers.

Two independent deadlines, measured separately because they run from
different instants:

- **first paint** — from the presentation REQUEST to the first receipt
  (`geometry_started`). This is the overlay proving it drew trustworthy
  geometry. A travelled cue emits it on its first traversal frame; the first
  cue has no previous rectangle and emits it on its settled paint. Both paths
  are measured because production gives them one shared deadline.
- **completion** — from that START receipt to `presentation_completed`, which
  is the settle. It does NOT run from the first-paint deadline; the protocol
  is explicit that the two are unordered relative to each other.

Read-only with respect to the user's machine, and deliberately so: it creates
its own overlay, presents into it, and destroys it. It moves no cursor and
synthesizes no input, exactly like `paint_budget`. A Phase A/B measuring tool
may never change what a run would have done (D105).

    py -3.12 -m ghostcursor.devtools.receipt_budget --cues 60 \
      --independent-first-cues 60

The reported deadline is the p99 rounded up with a stated margin, not the
mean. A deadline is the thing a slow presentation misses, and the mean is
exactly what hides those.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from types import SimpleNamespace

from ghostcursor.act_overlay import CueBudget, overlay_presenter
from ghostcursor.act_protocol import (
    PresentationRequest,
    ReceiptKind,
    ReceiptPolicy,
    TrustClass,
)
from ghostcursor.coordinate_space import observe_bracketed
from ghostcursor.overlay import dpi  # noqa: F401 - declares DPI awareness (D010)
from ghostcursor.overlay import window as overlay_window


def _permissive_policy() -> ReceiptPolicy:
    """A policy too large to censor the measurement it exists to enable."""

    return ReceiptPolicy(
        first_paint_deadline_ms=600_000, completion_deadline_ms=600_000
    )


def _observation(
    index: int,
    width: int,
    height: int,
    *,
    bracket=observe_bracketed,
):
    """A synthetic control rectangle that moves every cue.

    Moving matters: after the first settled cue, later cues take the traversal
    path. Both that path and the first cue's settled path are governed by the
    same receipt deadlines.
    """

    left = 80 + (index * 137) % max(width - 400, 1)
    top = 80 + (index * 89) % max(height - 300, 1)
    rectangle = (left, top, left + 160, top + 40)
    return SimpleNamespace(
        rectangle=rectangle,
        # The production overlay refuses an unproven rectangle. This tool
        # used to pass only four integers, so after D115/D116 every cue was a
        # RENDER_REJECTED receipt and the benchmark measured 0/N cues. A
        # synthetic rectangle still needs a real bracket around the read.
        geometry=bracket(lambda: (rectangle,)),
        identity={"name": "New Slide", "control_type": "Button"},
        semantic=(),
        match_count=1,
    )


def measure(cues: int, budget: CueBudget) -> dict:
    left, top, width, height = dpi.virtual_screen_rect()
    hwnd = overlay_window.create_overlay_window()

    #: Deliberately enormous, so the MEASUREMENT is never truncated by the
    #: deadline it exists to derive. Presenting under a policy that could
    #: refuse would measure the policy instead of the machine.
    permissive = _permissive_policy()

    first_paint: list[float] = []
    completion: list[float] = []
    settled_first_paint: list[float] = []
    settled_completion: list[float] = []
    rejected = 0

    # ONE presenter for every cue, because a presenter keeps the pointer's
    # position between presentations and that is what makes the next cue
    # TRAVEL. An earlier version of this tool built a fresh presenter per cue,
    # so `state["position"]` was always None and -- in `act_overlay`'s own
    # words -- "every cue becomes a single settled frame and the pointer never
    # travels at all". It measured sixty first cues and reported a first-paint
    # median of 0.0ms and a completion equal to `settle_ms` exactly, with the
    # 300ms traversal nowhere in the numbers.
    #
    # The first cue of a real run has nothing to travel from either, so it is
    # measured and reported SEPARATELY rather than averaged into a different
    # path. It still contributes to both shared production deadlines.
    #
    # Timed on `perf_counter`, NOT on the presenter's default clock. That
    # default is `time.monotonic`, whose granularity on this platform is
    # ~15ms -- so every receipt timestamp is quantised to it, first paint
    # read 0.0ms for all 59 travelled cues, and the derived deadline came out
    # as 0, which `ReceiptPolicy` would refuse. A measurement cannot be finer
    # than the clock it is taken on, and that clock was hiding the entire
    # first-paint distribution.
    presenter = overlay_presenter(
        hwnd,
        budget=budget,
        policy=permissive,
        label_for=lambda _observation: "New Slide",
        backend_trust=TrustClass.LIVE_STATE,
        keep_running=lambda: True,
        clock=lambda: time.perf_counter() * 1000.0,
    )
    try:
        for index in range(cues):
            marks: dict[str, float] = {}

            def sink(receipt, at_ms, marks=marks):
                marks.setdefault(receipt.kind.value, at_ms)

            request = PresentationRequest(
                session_id="receipt-budget",
                cue_id=f"cue:{index}",
                nonce=f"{index:032x}",
                presentation_generation=1,
                frame_generation=1,
                geometry_required=True,
            )
            requested_ms = time.perf_counter() * 1000.0
            receipts = presenter.present(
                request, _observation(index, width, height), sink
            )
            kinds = {receipt.kind for receipt in receipts}

            if ReceiptKind.RENDER_REJECTED in kinds:
                # Recorded, not discarded. A rejected render is a real outcome
                # and a run of them would mean the measurement is describing
                # something other than a cue.
                rejected += 1
                continue
            started = marks.get(ReceiptKind.GEOMETRY_STARTED.value)
            finished = marks.get(ReceiptKind.PRESENTATION_COMPLETED.value)
            if started is None or finished is None:
                rejected += 1
                continue
            # Index 0 travels from nothing; every later cue travels from
            # where the previous one left the pointer.
            if index == 0:
                settled_first_paint.append(started - requested_ms)
                settled_completion.append(finished - started)
            else:
                first_paint.append(started - requested_ms)
                completion.append(finished - started)
    finally:
        overlay_window.clear_cue(hwnd)
        overlay_window.destroy_overlay_window(hwnd)

    return {
        "cues_requested": cues,
        "cues_measured": len(first_paint),
        "cues_without_both_receipts": rejected,
        "budget": {
            "traversal_ms": budget.traversal_ms,
            "settle_ms": budget.settle_ms,
            "frame_budget_ms": budget.frame_budget_ms,
            "poll_interval_ms": budget.poll_interval_ms,
        },
        "virtual_screen": [left, top, left + width, top + height],
        # What PRODUCTION times receipts on, measured rather than assumed.
        # A deadline finer than this cannot be enforced by the clock that
        # checks it, however precisely it was measured.
        "enforcement_clock_granularity_ms": _clock_granularity(),
        "first_paint_ms": _summary(first_paint),
        "completion_ms": _summary(completion),
        # The first cue of a run, which has no previous position and so does
        # not travel. Reported so the difference is visible rather than
        # averaged away.
        "settled_first_cue": {
            "first_paint_ms": _summary(settled_first_paint),
            "completion_ms": _summary(settled_completion),
        },
    }


def measure_independent_first_cues(
    count: int,
    budget: CueBudget,
    *,
    create_overlay=overlay_window.create_overlay_window,
    destroy_overlay=overlay_window.destroy_overlay_window,
    presenter_factory=overlay_presenter,
    observation_factory=_observation,
    screen=dpi.virtual_screen_rect,
    clock_ms=lambda: time.perf_counter() * 1000.0,
) -> dict:
    """Measure first cues across independently created overlay sessions.

    A 60-cue run contains 59 travelled cues but only one first cue. Three
    retained runs therefore supplied only three samples for the shared
    first-paint deadline. This path creates a fresh overlay and presenter for
    every sample, matching the cold path a new Act run takes instead of
    repeatedly measuring a presenter whose GDI resources are already warm.

    The collaborators are injectable so hermetic tests can prove that every
    sample really receives a distinct session without opening desktop windows.
    """

    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("independent first-cue measurement needs at least one cue")

    _left, _top, width, height = screen()
    first_paint: list[float] = []
    completion: list[float] = []
    rejected = 0

    for index in range(count):
        hwnd = create_overlay()
        presenter = None
        try:
            presenter = presenter_factory(
                hwnd,
                budget=budget,
                policy=_permissive_policy(),
                label_for=lambda _observation: "New Slide",
                backend_trust=TrustClass.LIVE_STATE,
                keep_running=lambda: True,
                clock=clock_ms,
            )
            marks: dict[str, float] = {}

            def sink(receipt, at_ms):
                marks.setdefault(receipt.kind.value, at_ms)

            request = PresentationRequest(
                session_id="receipt-budget-independent-first-cue",
                cue_id=f"first:{index}",
                nonce=f"{index:032x}",
                presentation_generation=1,
                frame_generation=1,
                geometry_required=True,
            )
            requested_ms = clock_ms()
            receipts = presenter.present(
                request, observation_factory(index, width, height), sink
            )
            kinds = {receipt.kind for receipt in receipts}
            started = marks.get(ReceiptKind.GEOMETRY_STARTED.value)
            finished = marks.get(ReceiptKind.PRESENTATION_COMPLETED.value)
            if (
                ReceiptKind.RENDER_REJECTED in kinds
                or started is None
                or finished is None
            ):
                rejected += 1
                continue
            first_paint.append(started - requested_ms)
            completion.append(finished - started)
        finally:
            try:
                if presenter is not None:
                    presenter.release()
            finally:
                # A full-virtual-desktop overlay must not survive a failed
                # presenter constructor or release path.
                destroy_overlay(hwnd)

    return {
        "cues_requested": count,
        "cues_measured": len(first_paint),
        "cues_without_both_receipts": rejected,
        "first_paint_ms": _summary(first_paint),
        "completion_ms": _summary(completion),
    }


def _clock_granularity(samples: int = 200) -> float:
    """The smallest change `time.monotonic` can report, measured.

    `act_overlay` defaults its clock to monotonic, so this is the resolution
    a receipt timestamp actually has in production. On this platform it is
    about 15ms, which is larger than the entire first-paint cost.
    """

    ticks = []
    for _ in range(samples):
        start = time.monotonic()
        while time.monotonic() == start:
            pass
        ticks.append((time.monotonic() - start) * 1000.0)
    return round(min(ticks), 4)


def _summary(values: list[float]) -> dict:
    if not values:
        return {"samples": 0}
    ordered = sorted(values)
    return {
        "samples": len(ordered),
        "mean": round(statistics.fmean(ordered), 3),
        "median": round(statistics.median(ordered), 3),
        "p99": round(ordered[max(0, math.ceil(len(ordered) * 0.99) - 1)], 3),
        "max": round(ordered[-1], 3),
    }


def _derived(summary: dict, margin: float, granularity: float = 0.0) -> "int | None":
    """A deadline from a distribution: the p99 with a stated margin, rounded up.

    The margin is a CHOICE and is reported as one, so nobody later cites it as
    though something had been measured (D034). What is measured is the
    distribution; what is chosen is how much headroom a deadline leaves over
    its p99.
    """

    if not summary.get("samples"):
        return None
    derived = int(math.ceil(summary["p99"] * margin))
    # A deadline below the enforcement clock's granularity is not a deadline:
    # the clock that checks it cannot tell that value from zero. Floored to
    # one tick, and the report states both numbers so the floor is visible
    # rather than folded into a figure that looks measured.
    return max(derived, int(math.ceil(granularity)))


def _first_paint_basis(report: dict) -> dict:
    """Combine both presentation paths governed by the shared deadline."""

    return _combined_basis(report, "first_paint_ms")


def _completion_basis(report: dict) -> dict:
    """Combine completion samples from travelled and first-cue paths."""

    return _combined_basis(report, "completion_ms")


def _combined_basis(report: dict, field: str) -> dict:
    """Return one p99 basis for a deadline production applies to every cue."""

    basis = dict(report[field])
    first_cue = report["settled_first_cue"][field]
    if not first_cue.get("samples"):
        raise ValueError(f"the first cue has no {field} measurement")
    basis["p99"] = max(basis["p99"], first_cue["p99"])
    independent = report.get("independent_first_cues")
    if independent is not None:
        summary = independent[field]
        if not summary.get("samples"):
            raise ValueError(f"the independent first cues have no {field} measurement")
        if independent["cues_measured"] != independent["cues_requested"]:
            raise ValueError("not every independent first cue was measured")
        if independent["cues_without_both_receipts"]:
            raise ValueError("an independent first cue was rejected")
        basis["p99"] = max(basis["p99"], summary["p99"])
    return basis


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cues", type=int, default=60)
    parser.add_argument("--independent-first-cues", type=int, required=True)
    parser.add_argument("--traversal-ms", type=int, required=True)
    parser.add_argument("--settle-ms", type=int, required=True)
    parser.add_argument(
        "--frame-budget-ms",
        type=int,
        required=True,
        help="the measured per-frame paint cost; see docs/evidence/act-paint-budget.md",
    )
    parser.add_argument(
        "--margin",
        type=float,
        default=2.0,
        help="headroom over the measured p99; a choice, reported as one",
    )
    args = parser.parse_args(argv)

    if args.cues < 2:
        parser.error("a measurement needs a first cue and at least one travelled cue")
    if args.independent_first_cues < 1:
        parser.error("a measurement needs at least one independent first cue")

    report = measure(
        args.cues,
        CueBudget(
            traversal_ms=args.traversal_ms,
            settle_ms=args.settle_ms,
            frame_budget_ms=args.frame_budget_ms,
        ),
    )
    report["independent_first_cues"] = measure_independent_first_cues(
        args.independent_first_cues,
        CueBudget(
            traversal_ms=args.traversal_ms,
            settle_ms=args.settle_ms,
            frame_budget_ms=args.frame_budget_ms,
        ),
    )
    granularity = report["enforcement_clock_granularity_ms"]
    report["margin_over_p99"] = args.margin
    first_paint_basis = _first_paint_basis(report)
    report["derived"] = {
        "first_paint_deadline_ms": _derived(
            first_paint_basis, args.margin, granularity
        ),
        "completion_deadline_ms": _derived(
            _completion_basis(report), args.margin, granularity
        ),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    independent = report["independent_first_cues"]
    independent_clean = (
        independent["cues_measured"] == independent["cues_requested"]
        and not independent["cues_without_both_receipts"]
    )
    return 0 if report["cues_measured"] and independent_clean else 2


if __name__ == "__main__":
    raise SystemExit(main())
