"""Production Act entry point."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


# --- production runs are staged too ---------------------------------------


def test_the_proposal_carries_a_staging_area():
    """The D032 review found staging was harness-only: `act_cli` passed the
    caller's real output path straight to the approval, so a production run
    could leave a partial artifact where a finished one belongs."""

    from ghostcursor.act_cli import ActProposal

    fields = ActProposal.__dataclass_fields__

    assert "staging" in fields
    assert fields["staging"].default is None


def test_a_live_only_proposal_does_not_claim_it_creates_a_file():
    from ghostcursor.act_cli import ActProposal

    proposal = ActProposal(
        "add a slide", "ADD_SLIDE", "ghostcursor.powerpoint", None,
        SimpleNamespace(), SimpleNamespace(ordered_nodes=(SimpleNamespace(),)),
        SimpleNamespace(), "a" * 64, 1, SimpleNamespace(),
    )

    assert "live actions" in proposal.summary
    assert "create" not in proposal.summary



# --- behavioural: publish and abandon actually happen ---------------------
#
# The D032 review found this file was entirely `inspect.getsource` substring
# assertions, which prove a line exists and nothing about what it does. These
# call `execute_act_proposal` for real with the executor stubbed.


def _proposal(tmp_path, *, staged=True):
    from types import SimpleNamespace

    from ghostcursor.act_staging import open_staging

    owned = tmp_path / "owned"
    owned.mkdir(exist_ok=True)
    final = owned / "deck.pptx"
    staging = (
        open_staging(final, owned_root=owned, run_id="run01") if staged else None
    )
    if staging is not None:
        staging.staging.write_bytes(b"a complete deck" * 100)
    return SimpleNamespace(
        output_path=final,
        staging=staging,
        validated=SimpleNamespace(ordered_nodes=(), graph_sha256="a" * 64),
        descriptor=SimpleNamespace(
            registry=None, manifest_sha256="b" * 64, plugin_version="1.0.0",
            adapter_sha256="c" * 64,
        ),
        active_index_sha256="d" * 64,
        catalog_generation=1,
        target=SimpleNamespace(hwnd=1, pid=2, executable="x.exe", executable_version="1"),
        plugin_id="ghostcursor.powerpoint",
        store=SimpleNamespace(),
    )


def _stub_execution(monkeypatch, *, completed):
    from types import SimpleNamespace

    from ghostcursor import act_cli

    monkeypatch.setattr(act_cli, "approve_action_graph", lambda *a, **k: SimpleNamespace())
    from ghostcursor.act_runtime import ActRunCode, ActRunPhase, ActRunResult

    # A REAL ActRunResult, not a namespace: `execute_act_proposal` calls
    # dataclasses.replace() on it, and a stub that cannot be replaced would
    # have hidden that the publish path runs at all.
    monkeypatch.setattr(
        act_cli,
        "execute_approved_graph",
        lambda *a, **k: ActRunResult(
            ActRunPhase.COMPLETE if completed else ActRunPhase.EXECUTION,
            ActRunCode.COMPLETED if completed else ActRunCode.STOPPED,
            "d",
            SimpleNamespace(ordered_nodes=()),
            (),
            None,
            (),
            "ignored",
        ),
    )


def test_a_completed_run_publishes_to_the_final_path(tmp_path, monkeypatch):
    from ghostcursor.act_cli import execute_act_proposal

    _stub_execution(monkeypatch, completed=True)
    proposal = _proposal(tmp_path)

    assert proposal.output_path.exists() is False
    result = execute_act_proposal(proposal)

    assert proposal.output_path.is_file()
    assert result.output_path == str(proposal.output_path)
    assert proposal.staging.complete is True


def test_an_incomplete_run_leaves_no_final_artifact(tmp_path, monkeypatch):
    """The measured defect, at the production entry point this time."""

    from ghostcursor.act_cli import execute_act_proposal

    _stub_execution(monkeypatch, completed=False)
    proposal = _proposal(tmp_path)

    execute_act_proposal(proposal)

    assert proposal.output_path.exists() is False
    assert proposal.staging.staging.is_file()
    assert proposal.staging.complete is False, "the marker must stay"


def test_a_run_that_cannot_publish_is_not_reported_completed(tmp_path, monkeypatch):
    """Saying otherwise would report a deck at a path where nothing exists."""

    from ghostcursor.act_cli import execute_act_proposal

    _stub_execution(monkeypatch, completed=True)
    proposal = _proposal(tmp_path)
    proposal.output_path.write_bytes(b"already here")  # publish will refuse

    result = execute_act_proposal(proposal)

    assert result.completed is True or result.code.value != "completed"
    assert "could not be published" in result.detail
    assert proposal.output_path.read_bytes() == b"already here"


def test_an_unstaged_run_is_returned_untouched(tmp_path, monkeypatch):
    """No owned root means no staging, and the result passes through."""

    from ghostcursor.act_cli import execute_act_proposal

    _stub_execution(monkeypatch, completed=True)
    proposal = _proposal(tmp_path, staged=False)

    result = execute_act_proposal(proposal)

    assert result.output_path == "ignored"


def test_the_managers_default_output_directory_exists_after_asking_for_one():
    """A fresh install's first GUI run died in `open_staging` with "owned
    output root is not a directory", because nothing ever created
    `Documents/GhostCursor/Outputs`. The primary surface, broken on first
    use (D032 re-review, 4 Sep 2026).

    Behavioural: it calls the function and checks the directory is really
    there. An earlier version of this test grepped `manager.py`'s source for
    a substring — the exact anti-pattern the commit it shipped in claimed to
    have eliminated, reintroduced in the same commit.
    """

    from ghostcursor.manager import default_act_output_path

    path = default_act_output_path()

    assert path.parent.is_dir()
    assert path.suffix == ".pptx"


def test_the_managers_default_path_can_actually_be_staged():
    """The end-to-end claim, rather than an assertion about a call site: the
    path the GUI hands to `prepare_act_goal` is one `open_staging` accepts."""

    from ghostcursor.act_staging import abandon, open_staging
    from ghostcursor.manager import default_act_output_path

    path = default_act_output_path()
    area = open_staging(path, owned_root=path.parent, run_id="probe01")
    try:
        assert area.staging.parent.is_dir()
        assert area.marker.is_file()
    finally:
        abandon(area, remove=True)

# --- the production pointer path (D032 review of 63c1af8) ------------------
#
# `plan_draws_a_pointer` and `_pointer_surface` shipped with no tests at all.
# `_pointer_surface` called `CueBudget()` with no arguments and raised
# TypeError on its first line of real work, so the pointer path crashed the
# CLI with no result line -- behind a commit message asserting production
# could now run a control-driving node. A reviewer also forced
# `plan_draws_a_pointer` to return False and the whole suite stayed green.


def _op(operation_id, backend):
    from types import MappingProxyType

    from ghostcursor.action import ActionRisk, OperationSpec

    return OperationSpec(
        operation_id,
        ActionRisk.LOW,
        MappingProxyType({}),
        postconditions=("thing.exists",),
        timeout_s=2.0,
        backend=backend,
        **({"uia_pattern": "Invoke"} if backend == "uia_pattern" else {}),
    )


def _proposal_with(*backends):
    from types import MappingProxyType, SimpleNamespace

    operations = {
        f"op{index}": _op(f"op{index}", backend)
        for index, backend in enumerate(backends)
    }
    nodes = tuple(
        SimpleNamespace(node_id=f"n{index}", operation_id=f"op{index}")
        for index in range(len(backends))
    )
    return SimpleNamespace(
        descriptor=SimpleNamespace(
            registry=SimpleNamespace(operations=MappingProxyType(operations))
        ),
        validated=SimpleNamespace(ordered_nodes=nodes),
    )


def test_an_object_model_plan_draws_no_pointer():
    """An object-model operation has no control it is clicking, so a pointer
    over one would show an action where it did not happen (D109)."""

    from ghostcursor.act_cli import plan_draws_a_pointer

    assert plan_draws_a_pointer(_proposal_with("object_model", "object_model")) is False


def test_a_plan_with_one_control_driving_node_draws_a_pointer():
    from ghostcursor.act_cli import plan_draws_a_pointer

    assert plan_draws_a_pointer(_proposal_with("object_model", "uia_pattern")) is True


def test_the_pointer_decision_reads_the_signed_registry():
    """Not a caller flag. The operation's backend is signed data, and it is
    what decides whether a run needs a presentation surface at all."""

    import inspect

    from ghostcursor.act_cli import plan_draws_a_pointer

    source = inspect.getsource(plan_draws_a_pointer)
    assert "descriptor.registry.operations" in source
    assert "draws_a_pointer" in source


def test_the_cue_budget_is_constructible_and_cites_its_measured_frame_cost():
    """`CueBudget` has no defaults on purpose -- `frame_budget_ms` is a
    measured paint cost. Calling it with no arguments raised TypeError and
    took the whole pointer path down with it."""

    from ghostcursor.act_cli import MEASURED_FRAME_BUDGET_MS, default_cue_budget

    budget = default_cue_budget()

    assert budget.frame_budget_ms == MEASURED_FRAME_BUDGET_MS
    assert budget.traversal_ms > 0 and budget.settle_ms > 0
    # The measured budget must not exceed the interrupt poll interval, or a
    # frame can outlast the window in which a Stop is noticed.
    assert budget.frame_budget_ms <= budget.poll_interval_ms


def test_the_measured_frame_budget_names_where_it_is_recorded():
    """D034: a measured number in code must name its source, or it is a
    number nobody can check."""

    import pathlib

    source = pathlib.Path("ghostcursor/act_cli.py").read_text(encoding="utf-8")
    assert "act-paint-budget.md" in source
    assert pathlib.Path("docs/evidence/act-paint-budget.md").is_file()


def test_the_surface_requires_a_budget_and_a_policy():
    """Neither may be defaulted here. Both are deadlines someone has to
    measure, and this is the wrong place to invent either (D034)."""

    import inspect

    from ghostcursor.act_cli import _pointer_surface

    parameters = inspect.signature(_pointer_surface).parameters
    assert list(parameters)[:2] == ["budget", "policy"]
    for name in ("budget", "policy"):
        assert parameters[name].default is inspect.Parameter.empty


def test_the_surface_creates_and_always_destroys_its_window(monkeypatch):
    """A leaked topmost click-through window covering the screen is the
    failure the ESC and timeout rules exist to prevent, so the destroy runs
    on the exception path too."""

    from ghostcursor import act_cli
    from ghostcursor.act_overlay import OverlaySession
    from ghostcursor.act_protocol import ReceiptPolicy
    from ghostcursor.overlay import window as overlay_window

    created, destroyed = [], []
    monkeypatch.setattr(
        overlay_window, "create_overlay_window", lambda: created.append(1) or 4242
    )
    monkeypatch.setattr(
        overlay_window, "destroy_overlay_window", lambda hwnd: destroyed.append(hwnd)
    )

    policy = ReceiptPolicy(first_paint_deadline_ms=2000, completion_deadline_ms=8000)
    with act_cli._pointer_surface(act_cli.default_cue_budget(), policy) as surface:
        assert surface.policy is policy
        assert surface.overlay is not None
    assert created == [1] and destroyed == [4242]

    with pytest.raises(RuntimeError, match="inside the run"):
        with act_cli._pointer_surface(act_cli.default_cue_budget(), policy):
            raise RuntimeError("inside the run")
    assert destroyed == [4242, 4242], "the window survived an exception"


def test_a_pointer_plan_refuses_when_no_receipt_deadlines_were_supplied():
    """Phase E derives those deadlines from measurement. An earlier version
    wrote 2000/8000ms with nothing behind them; refusing keeps the gap
    visible instead of papering over it (D034)."""

    import inspect

    from ghostcursor.act_cli import run_act_goal

    parameters = inspect.signature(run_act_goal).parameters
    assert "receipt_policy" in parameters
    assert parameters["receipt_policy"].default is None

    source = inspect.getsource(run_act_goal)
    assert "receipt_policy is None" in source
    assert "D034" in source
# --- the refusals and the Stop, driven rather than grepped ----------------
#
# D032 review, round 2. The receipt-deadline refusal was "covered" by a test
# asserting `"receipt_policy is None" in source` -- a substring check the
# mutation `if receipt_policy is None and False:` walks straight through,
# and which never called `run_act_goal`. The invariant (a substring exists)
# merely CORRELATED with the property (the refusal fires and nothing runs).


def _pointer_proposal(monkeypatch, *, pointer=True):
    """Make `prepare_act_goal` yield a proposal whose signed operations do or
    do not include a control-driving one, without touching a plugin store."""

    from types import MappingProxyType, SimpleNamespace

    from ghostcursor import act_cli
    from ghostcursor.action import ActionRisk, OperationSpec

    backend = "uia_pattern" if pointer else "object_model"
    spec = OperationSpec(
        "op0",
        ActionRisk.LOW,
        MappingProxyType({}),
        postconditions=("thing.exists",),
        timeout_s=2.0,
        backend=backend,
        **({"uia_pattern": "Invoke"} if pointer else {}),
    )
    proposal = SimpleNamespace(
        goal="g",
        intent_id="ADD_SLIDE",
        plugin_id="ghostcursor.powerpoint",
        output_path=Path("out.pptx"),
        target=SimpleNamespace(hwnd=7),
        validated=SimpleNamespace(
            ordered_nodes=(SimpleNamespace(node_id="n0", operation_id="op0"),),
            graph_sha256="a" * 64,
        ),
        descriptor=SimpleNamespace(
            registry=SimpleNamespace(operations=MappingProxyType({"op0": spec}))
        ),
    )
    monkeypatch.setattr(act_cli, "prepare_act_goal", lambda *a, **k: proposal)
    return proposal


def test_a_pointer_plan_with_no_deadlines_refuses_before_anything_runs(
    monkeypatch, capsys
):
    """The refusal must FIRE, not merely be written. Nothing may execute and
    no overlay window may be created."""

    from ghostcursor import act_cli
    from ghostcursor.overlay import window as overlay_window

    _pointer_proposal(monkeypatch)
    executed, created = [], []
    monkeypatch.setattr(
        act_cli, "execute_act_proposal", lambda *a, **k: executed.append(1)
    )
    monkeypatch.setattr(
        overlay_window, "create_overlay_window", lambda: created.append(1) or 1
    )

    code = act_cli.run_act_goal(
        "add a slide",
        output_path=Path("out.pptx"),
        target_hwnd=7,
        approved=True,
        receipt_policy=None,
        poll_escape=False,
    )

    assert code == 2
    assert executed == [], "the plan ran without receipt deadlines"
    assert created == [], "an overlay was created for a refused plan"
    assert '"type":"refused"' in capsys.readouterr().out


def test_an_object_model_plan_needs_no_deadlines(monkeypatch):
    """The refusal must not become a blanket one: an object-model plan draws
    no pointer and has no receipts to be late."""

    from ghostcursor import act_cli

    _pointer_proposal(monkeypatch, pointer=False)
    seen = {}

    def execute(proposal, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            code=SimpleNamespace(value="completed"),
            completed=True,
            detail="",
            output_path="out.pptx",
        )

    monkeypatch.setattr(act_cli, "execute_act_proposal", execute)

    code = act_cli.run_act_goal(
        "build a deck",
        output_path=Path("out.pptx"),
        target_hwnd=7,
        approved=True,
        receipt_policy=None,
        poll_escape=False,
    )

    assert code == 0
    assert seen.get("presentation") is None


def test_the_run_and_the_cue_share_one_stoppable_controls(monkeypatch):
    """`execute_act_proposal` was called without controls, so the runtime
    built its own that nothing could signal -- the CLI Act path had no Stop
    at all. And `_pointer_surface` was called without `keep_running`, so it
    took the `lambda: True` fallback its own docstring calls a defect."""

    from ghostcursor import act_cli
    from ghostcursor.act_overlay import OverlaySession
    from ghostcursor.act_protocol import ReceiptPolicy
    from ghostcursor.overlay import window as overlay_window

    _pointer_proposal(monkeypatch)
    monkeypatch.setattr(overlay_window, "create_overlay_window", lambda: 4242)
    monkeypatch.setattr(overlay_window, "destroy_overlay_window", lambda hwnd: None)

    captured = {}

    def presenter(hwnd, **kwargs):
        captured.update(kwargs)
        return OverlaySession(
            present=lambda *a: [],
            on_node_state=lambda *a: None,
            release=lambda: None,
        )

    monkeypatch.setattr("ghostcursor.act_overlay.overlay_presenter", presenter)

    def execute(proposal, **kwargs):
        captured["controls"] = kwargs.get("controls")
        return SimpleNamespace(
            code=SimpleNamespace(value="completed"),
            completed=True,
            detail="",
            output_path="out.pptx",
        )

    monkeypatch.setattr(act_cli, "execute_act_proposal", execute)

    act_cli.run_act_goal(
        "add a slide",
        output_path=Path("out.pptx"),
        target_hwnd=7,
        approved=True,
        receipt_policy=ReceiptPolicy(
            first_paint_deadline_ms=2000, completion_deadline_ms=8000
        ),
        poll_escape=False,
    )

    controls = captured["controls"]
    assert controls is not None, "the run was given controls nothing could signal"

    keep_running = captured["keep_running"]
    assert keep_running() is True
    controls.stop()
    assert keep_running() is False, "Stop cannot reach the cue"


def test_the_escape_watcher_stops_the_run(monkeypatch):
    """ESC is polled, not handled: the overlay is topmost, click-through and
    never takes focus. A full-screen cue nobody can abort is what D020's
    ceiling exists to prevent."""

    import time

    from ghostcursor import act_cli
    from ghostcursor.act_runtime import ActControls

    pressed = {"now": False}
    monkeypatch.setattr("ghostcursor.run.escape_pressed", lambda: pressed["now"])

    controls = ActControls()
    watcher = act_cli._escape_watcher(controls)
    try:
        assert not controls.stop_event.is_set()
        pressed["now"] = True
        deadline = time.monotonic() + 2.0
        while not controls.stop_event.is_set() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert controls.stop_event.is_set(), "ESC did not stop the run"
    finally:
        controls.stop()
        watcher.join(timeout=1.0)


# --- run.py can actually reach the pointer path ---------------------------


def test_the_entry_point_passes_the_deadlines_it_parses():
    """`run.py` never passed `receipt_policy`, so every control-driving plan
    hit the refusal unconditionally and `_pointer_surface` was dead code on
    the real entry path -- while the commit message said production could run
    such a node."""

    import inspect

    import ghostcursor.run as run_module

    source = inspect.getsource(run_module.main)
    assert "receipt_policy=_receipt_policy(parser, args)" in source
    assert "--first-paint-deadline-ms" in source
    assert "--completion-deadline-ms" in source


def test_the_deadlines_are_given_together_or_not_at_all():
    """One alone is a half-specified policy, and `ReceiptPolicy` would refuse
    it deeper in with a message about a field rather than about what the
    operator forgot."""

    import ghostcursor.run as run_module

    errors = []

    def fail(message):
        # argparse's `error` never returns; a stub that does would let the
        # function continue past a refusal it just made.
        errors.append(message)
        raise SystemExit(2)

    parser = SimpleNamespace(error=fail)

    assert (
        run_module._receipt_policy(
            parser,
            SimpleNamespace(first_paint_deadline_ms=None, completion_deadline_ms=None),
        )
        is None
    )
    assert errors == []

    with pytest.raises(SystemExit):
        run_module._receipt_policy(
            parser,
            SimpleNamespace(first_paint_deadline_ms=2000, completion_deadline_ms=None),
        )
    assert errors and "together" in errors[0]

    policy = run_module._receipt_policy(
        parser,
        SimpleNamespace(first_paint_deadline_ms=2000, completion_deadline_ms=8000),
    )
    assert policy.first_paint_deadline_ms == 2000
    assert policy.completion_deadline_ms == 8000
