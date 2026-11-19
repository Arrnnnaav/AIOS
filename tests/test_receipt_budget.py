"""The receipt-deadline measurement refuses to invent what it exists to derive.

`ReceiptPolicy` has no defaults on purpose: Phase E derives its two deadlines
from measurement, and a plausible constant is the placeholder that derivation
exists to replace. This devtool is what produces them, so the things it must
not do are: default its inputs, report a deadline from no samples, or measure
under a policy that could truncate the very numbers being measured.

The window-creating path needs a real desktop and is not exercised here.
"""

from __future__ import annotations

import pytest

from ghostcursor.coordinate_space import BracketedGeometry
from ghostcursor.devtools import receipt_budget


def test_the_synthetic_rectangle_has_real_bracketed_coordinate_provenance():
    sentinel = object()
    reads = []

    def bracket(read):
        rectangles = tuple(read())
        reads.append(rectangles)
        return sentinel

    observation = receipt_budget._observation(0, 1920, 1080, bracket=bracket)

    assert reads == [(observation.rectangle,)]
    assert observation.geometry is sentinel


def test_the_real_default_produces_a_bracket_the_overlay_can_validate():
    observation = receipt_budget._observation(0, 1920, 1080)

    assert isinstance(observation.geometry, BracketedGeometry)
    assert observation.geometry.held
    assert observation.geometry.rectangles == (observation.rectangle,)


def test_the_measurement_inputs_are_all_required():
    """A budget nobody supplied is a budget nobody measured. `--frame-budget-ms`
    especially: it is a measured paint cost with its own evidence file."""

    for missing in (
        "--independent-first-cues",
        "--traversal-ms",
        "--settle-ms",
        "--frame-budget-ms",
    ):
        argv = [
            "--independent-first-cues",
            "60",
            "--traversal-ms",
            "300",
            "--settle-ms",
            "250",
            "--frame-budget-ms",
            "2",
        ]
        index = argv.index(missing)
        del argv[index : index + 2]
        with pytest.raises(SystemExit):
            receipt_budget.main(argv)


def test_a_run_of_no_cues_is_refused():
    with pytest.raises(SystemExit):
        receipt_budget.main(
            [
                "--cues",
                "0",
                "--independent-first-cues",
                "60",
                "--traversal-ms",
                "300",
                "--settle-ms",
                "250",
                "--frame-budget-ms",
                "2",
            ]
        )


def test_a_run_of_no_independent_first_cues_is_refused():
    with pytest.raises(SystemExit):
        receipt_budget.main(
            [
                "--cues",
                "60",
                "--independent-first-cues",
                "0",
                "--traversal-ms",
                "300",
                "--settle-ms",
                "250",
                "--frame-budget-ms",
                "2",
            ]
        )


def test_a_run_with_no_travelled_cue_is_refused_cleanly():
    with pytest.raises(SystemExit):
        receipt_budget.main(
            [
                "--cues",
                "1",
                "--independent-first-cues",
                "60",
                "--traversal-ms",
                "300",
                "--settle-ms",
                "250",
                "--frame-budget-ms",
                "2",
            ]
        )


def test_no_samples_derives_no_deadline():
    """Returning a number here would be inventing one from nothing, which is
    the exact failure this tool exists to prevent."""

    assert receipt_budget._derived({"samples": 0}, 2.0) is None
    assert receipt_budget._derived({}, 2.0) is None


def test_a_sustained_slow_tail_moves_the_deadline():
    """A deadline is the thing a slow presentation misses, so a tail that
    happens one time in ten has to reach it. The mean would bury it."""

    values = [10.0] * 90 + [500.0] * 10
    summary = receipt_budget._summary(values)

    assert summary["p99"] == 500.0
    assert summary["mean"] < summary["p99"]
    assert receipt_budget._derived(summary, 1.0) >= summary["p99"]


def test_one_outlier_does_not_move_the_deadline():
    """p99, not max, and this is the difference. A single first-paint or
    allocator spike makes one presentation late; it is not the cost the
    deadline should be built around -- `act-paint-budget.md` records the same
    reasoning for the frame budget, where one 16ms frame sat among 5-6ms
    peaks and the median did not move."""

    values = [10.0] * 99 + [500.0]
    summary = receipt_budget._summary(values)

    assert summary["max"] == 500.0
    assert summary["p99"] == 10.0
    assert receipt_budget._derived(summary, 2.0) == 20


def test_the_margin_is_applied_and_rounded_up():
    summary = receipt_budget._summary([10.0, 10.0, 10.5])

    assert receipt_budget._derived(summary, 2.0) == 21
    # Rounded UP: a deadline truncated downward is one presentations miss.
    assert receipt_budget._derived(summary, 1.0) == 11


def test_a_summary_of_nothing_says_so_rather_than_reporting_zero():
    assert receipt_budget._summary([]) == {"samples": 0}


def test_the_measurement_policy_cannot_truncate_what_it_measures():
    """Presenting under a deadline that could refuse would measure the policy
    instead of the machine, and would quietly derive a deadline from the
    presentations that happened to fit inside the guess."""

    import inspect

    source = inspect.getsource(receipt_budget._permissive_policy)
    assert "600_000" in source


def test_independent_first_cues_each_get_a_fresh_overlay_and_presenter():
    from ghostcursor.act_overlay import CueBudget
    from ghostcursor.act_protocol import Receipt, ReceiptKind

    created = []
    destroyed = []
    presenters = []
    policies = []

    def create():
        hwnd = 100 + len(created)
        created.append(hwnd)
        return hwnd

    class Presenter:
        def __init__(self, hwnd):
            self.hwnd = hwnd
            self.released = False
            presenters.append(self)

        def present(self, request, _observation, sink):
            start = Receipt(
                ReceiptKind.GEOMETRY_STARTED,
                request.session_id,
                request.cue_id,
                request.nonce,
                request.presentation_generation,
                request.frame_generation,
            )
            complete = Receipt(
                ReceiptKind.PRESENTATION_COMPLETED,
                request.session_id,
                request.cue_id,
                request.nonce,
                request.presentation_generation,
                request.frame_generation,
            )
            sink(start, 15.0)
            sink(complete, 25.0)
            return (start, complete)

        def release(self):
            self.released = True

    def presenter_factory(hwnd, **kwargs):
        policies.append(kwargs["policy"])
        return Presenter(hwnd)

    report = receipt_budget.measure_independent_first_cues(
        3,
        CueBudget(traversal_ms=300, settle_ms=250, frame_budget_ms=2),
        create_overlay=create,
        destroy_overlay=lambda hwnd: destroyed.append(hwnd),
        presenter_factory=presenter_factory,
        observation_factory=lambda *_args: object(),
        screen=lambda: (0, 0, 1920, 1080),
        clock_ms=lambda: 10.0,
    )

    assert created == [100, 101, 102]
    assert destroyed == created
    assert [presenter.hwnd for presenter in presenters] == created
    assert all(presenter.released for presenter in presenters)
    assert [policy.first_paint_deadline_ms for policy in policies] == [
        600_000,
        600_000,
        600_000,
    ]
    assert [policy.completion_deadline_ms for policy in policies] == [
        600_000,
        600_000,
        600_000,
    ]
    assert report["cues_requested"] == 3
    assert report["cues_measured"] == 3
    assert report["cues_without_both_receipts"] == 0
    assert report["first_paint_ms"]["p99"] == 5.0
    assert report["completion_ms"]["p99"] == 10.0


def test_the_independent_measurement_refuses_a_zero_count_at_its_own_boundary():
    from ghostcursor.act_overlay import CueBudget

    with pytest.raises(ValueError, match="at least one"):
        receipt_budget.measure_independent_first_cues(
            0,
            CueBudget(traversal_ms=300, settle_ms=250, frame_budget_ms=2),
        )


@pytest.mark.parametrize("mode", ["rejected", "missing_completion"])
def test_rejected_or_incomplete_first_cues_are_not_counted_as_samples(mode):
    from ghostcursor.act_overlay import CueBudget
    from ghostcursor.act_protocol import Receipt, ReceiptKind

    class Presenter:
        def present(self, request, _observation, sink):
            kinds = (
                (
                    ReceiptKind.RENDER_REJECTED,
                    ReceiptKind.GEOMETRY_STARTED,
                    ReceiptKind.PRESENTATION_COMPLETED,
                )
                if mode == "rejected"
                else (ReceiptKind.GEOMETRY_STARTED,)
            )
            receipts = tuple(
                Receipt(
                    kind,
                    request.session_id,
                    request.cue_id,
                    request.nonce,
                    request.presentation_generation,
                    request.frame_generation,
                )
                for kind in kinds
            )
            for offset, receipt in enumerate(receipts, start=1):
                sink(receipt, 10.0 + offset * 5.0)
            return receipts

        def release(self):
            pass

    report = receipt_budget.measure_independent_first_cues(
        1,
        CueBudget(traversal_ms=300, settle_ms=250, frame_budget_ms=2),
        create_overlay=lambda: 100,
        destroy_overlay=lambda _hwnd: None,
        presenter_factory=lambda _hwnd, **_kwargs: Presenter(),
        observation_factory=lambda *_args: object(),
        screen=lambda: (0, 0, 1920, 1080),
        clock_ms=lambda: 10.0,
    )

    assert report["cues_measured"] == 0
    assert report["cues_without_both_receipts"] == 1
    assert report["first_paint_ms"] == {"samples": 0}
    assert report["completion_ms"] == {"samples": 0}


def test_presenter_construction_failure_still_destroys_the_overlay():
    from ghostcursor.act_overlay import CueBudget

    destroyed = []

    def fail(_hwnd, **_kwargs):
        raise RuntimeError("presenter failed")

    with pytest.raises(RuntimeError, match="presenter failed"):
        receipt_budget.measure_independent_first_cues(
            1,
            CueBudget(traversal_ms=300, settle_ms=250, frame_budget_ms=2),
            create_overlay=lambda: 100,
            destroy_overlay=lambda hwnd: destroyed.append(hwnd),
            presenter_factory=fail,
            screen=lambda: (0, 0, 1920, 1080),
        )

    assert destroyed == [100]


def test_release_failure_cannot_prevent_overlay_destruction():
    from ghostcursor.act_overlay import CueBudget

    destroyed = []

    class Presenter:
        def present(self, *_args):
            raise RuntimeError("presentation failed")

        def release(self):
            raise RuntimeError("release failed")

    with pytest.raises(RuntimeError, match="release failed"):
        receipt_budget.measure_independent_first_cues(
            1,
            CueBudget(traversal_ms=300, settle_ms=250, frame_budget_ms=2),
            create_overlay=lambda: 100,
            destroy_overlay=lambda hwnd: destroyed.append(hwnd),
            presenter_factory=lambda _hwnd, **_kwargs: Presenter(),
            observation_factory=lambda *_args: object(),
            screen=lambda: (0, 0, 1920, 1080),
        )

    assert destroyed == [100]


def test_the_tool_synthesizes_no_input():
    """A Phase A/B measuring tool may never change what a run would have done
    (D105), and core may never synthesize input at all (D006). The package
    scan enforces the second; this states the first."""

    import inspect

    source = inspect.getsource(receipt_budget)
    for banned in ("SendInput", "mouse_event", "SetCursorPos", "keybd_event"):
        assert banned not in source


def test_both_deadlines_are_measured_from_their_own_instant():
    """They are independent and deliberately unordered relative to each other:
    first paint runs from the REQUEST, completion runs from the START RECEIPT
    -- not from the first-paint deadline."""

    import inspect

    source = inspect.getsource(receipt_budget.measure)
    assert "started - requested_ms" in source
    assert "finished - started" in source


# --- the measured numbers, and where they came from -----------------------


def test_the_measured_policy_matches_the_rendered_evidence():
    """D034: a measured number in code must name where it is recorded, and
    the two must agree. A constant that drifts from its evidence is worse
    than one with no evidence at all -- it looks checked."""

    import re
    from pathlib import Path

    from ghostcursor.act_cli import measured_receipt_policy

    document = Path("docs/evidence/act-receipt-budget.md").read_text(encoding="utf-8")
    match = re.search(
        r"`first_paint_deadline_ms = (\d+)`, `completion_deadline_ms = (\d+)`",
        document,
    )
    assert match, "the evidence document states no derived deadlines"

    policy = measured_receipt_policy()
    assert policy.first_paint_deadline_ms == int(match.group(1))
    assert policy.completion_deadline_ms == int(match.group(2))


def test_the_code_names_the_evidence_file():
    from pathlib import Path

    source = Path("ghostcursor/act_cli.py").read_text(encoding="utf-8")
    assert "act-receipt-budget.md" in source
    assert Path("docs/evidence/act-receipt-budget.md").is_file()


def test_a_measured_deadline_clears_the_enforcement_clock():
    """A deadline below the clock's granularity cannot be enforced by the
    clock that checks it, however precisely it was measured."""

    import json
    from pathlib import Path

    from ghostcursor.act_cli import measured_receipt_policy

    record = json.loads(
        (Path("docs/evidence/receipt-budget/run-1.json")).read_text(encoding="utf-8")
    )
    granularity = record["enforcement_clock_granularity_ms"]
    policy = measured_receipt_policy()

    assert policy.first_paint_deadline_ms >= granularity
    assert policy.completion_deadline_ms >= granularity


def test_the_first_cue_is_load_bearing_in_the_shared_first_paint_deadline():
    """Production applies one deadline to travelled and first-cue paints."""

    report = {
        "first_paint_ms": {"samples": 59, "p99": 5.0},
        "settled_first_cue": {
            "first_paint_ms": {"samples": 1, "p99": 14.234}
        },
    }

    basis = receipt_budget._first_paint_basis(report)

    assert basis["p99"] == 14.234
    assert receipt_budget._derived(basis, 2.0, 15.0) == 29


def test_independent_first_cues_are_load_bearing_in_the_shared_deadline():
    report = {
        "first_paint_ms": {"samples": 59, "p99": 5.0},
        "settled_first_cue": {
            "first_paint_ms": {"samples": 1, "p99": 14.0}
        },
        "independent_first_cues": {
            "cues_requested": 60,
            "cues_measured": 60,
            "cues_without_both_receipts": 0,
            "first_paint_ms": {"samples": 60, "p99": 40.0},
        },
    }

    basis = receipt_budget._first_paint_basis(report)

    assert basis["p99"] == 40.0
    assert receipt_budget._derived(basis, 2.0, 15.0) == 80


def test_independent_first_cue_completion_is_load_bearing_too():
    report = {
        "completion_ms": {"samples": 59, "p99": 550.0},
        "settled_first_cue": {
            "completion_ms": {"samples": 1, "p99": 250.0}
        },
        "independent_first_cues": {
            "cues_requested": 60,
            "cues_measured": 60,
            "cues_without_both_receipts": 0,
            "completion_ms": {"samples": 60, "p99": 700.0},
        },
    }

    basis = receipt_budget._completion_basis(report)

    assert basis["p99"] == 700.0
    assert receipt_budget._derived(basis, 2.0, 15.0) == 1400


def test_the_first_cue_is_load_bearing_in_the_shared_completion_deadline():
    report = {
        "completion_ms": {"samples": 59, "p99": 500.0},
        "settled_first_cue": {
            "completion_ms": {"samples": 1, "p99": 1000.0}
        },
    }

    basis = receipt_budget._completion_basis(report)

    assert basis["p99"] == 1000.0
    assert receipt_budget._derived(basis, 2.0, 15.0) == 2000


def test_the_measured_policy_is_never_a_default():
    """An operator on another machine has not measured these -- the paint
    cost scales with desktop area. It is a value to pass, not one that
    appears on its own."""

    import inspect

    from ghostcursor.act_cli import run_act_goal

    parameters = inspect.signature(run_act_goal).parameters
    assert parameters["receipt_policy"].default is None


def test_the_measured_deadlines_flag_actually_supplies_them():
    """The flag existing is not the flag working. Returning None instead
    would put the CLI straight back on the refusal branch while advertising
    a way off it."""

    from types import SimpleNamespace

    import pytest

    import ghostcursor.run as run_module

    def fail(message):
        raise SystemExit(message)

    parser = SimpleNamespace(error=fail)
    policy = run_module._receipt_policy(
        parser,
        SimpleNamespace(
            measured_deadlines=True,
            first_paint_deadline_ms=None,
            completion_deadline_ms=None,
        ),
    )
    assert policy is not None, "--measured-deadlines supplied no policy"
    assert policy.first_paint_deadline_ms > 0
    assert policy.completion_deadline_ms > 0

    # ...and it is not two answers to the same question.
    with pytest.raises(SystemExit):
        run_module._receipt_policy(
            parser,
            SimpleNamespace(
                measured_deadlines=True,
                first_paint_deadline_ms=2000,
                completion_deadline_ms=8000,
            ),
        )


def test_a_rejected_cue_still_prints_the_report_with_its_counts(monkeypatch, capsys):
    import json

    monkeypatch.setattr(
        receipt_budget, "measure",
        lambda *a, **k: {"enforcement_clock_granularity_ms": 1, "cues_measured": 60},
    )
    monkeypatch.setattr(
        receipt_budget, "measure_independent_first_cues",
        lambda *a, **k: {
            "cues_measured": 60, "cues_requested": 60, "cues_without_both_receipts": 1
        },
    )

    def rejected(report):
        raise ValueError("an independent first cue was rejected")

    monkeypatch.setattr(receipt_budget, "_first_paint_basis", rejected)
    argv = ["--cues", "60", "--independent-first-cues", "60", "--traversal-ms",
            "300", "--settle-ms", "250", "--frame-budget-ms", "2"]  # fmt: skip
    assert receipt_budget.main(argv) == 2
    printed = json.loads(capsys.readouterr().out)
    assert printed["derived"] is None
    assert printed["independent_first_cues"]["cues_without_both_receipts"] == 1
