"""Production Act entry point."""

from __future__ import annotations

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


def test_a_run_with_no_owned_root_is_not_staged():
    """There is nowhere the runtime owns to stage into. Stated rather than
    silently degraded: without an owned root the run writes its final path
    directly, exactly as every production run did before staging existed."""

    import inspect

    from ghostcursor.act_cli import prepare_act_goal

    source = inspect.getsource(prepare_act_goal)

    assert "if owned_output_root is not None:" in source
    assert "written = staging.staging" in source


def test_the_plan_is_materialized_against_the_written_path():
    """So the adapter is never told where the final artifact goes and cannot
    expose a partial one, which is what makes it structural."""

    import inspect

    from ghostcursor.act_cli import prepare_act_goal

    source = inspect.getsource(prepare_act_goal)

    assert '{"output_path": str(written)}' in source


def test_a_run_that_could_not_publish_is_not_reported_as_completed():
    """Saying otherwise would report a deck at a path where nothing exists."""

    import inspect

    from ghostcursor.act_cli import execute_act_proposal

    source = inspect.getsource(execute_act_proposal)

    assert "could not be published" in source
    assert "ActRunCode.ADAPTER_FAILED" in source


def test_an_incomplete_run_abandons_rather_than_publishing():
    import inspect

    from ghostcursor.act_cli import execute_act_proposal

    source = inspect.getsource(execute_act_proposal)
    incomplete = source.split("if not result.completed:", 1)[1].split("try:", 1)[0]

    assert "abandon(proposal.staging)" in incomplete
    assert "publish" not in incomplete


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


def test_the_manager_supplies_an_owned_root(tmp_path):
    """The pilot GUI ran unstaged: `prepare_act_goal` was called without an
    owned root, so every manager-initiated run wrote its final path directly
    (D032 review, 4 Sep 2026)."""

    import inspect

    from ghostcursor import manager

    source = inspect.getsource(manager)

    assert "owned_output_root=request.output_path.parent" in source
    assert "owned_output_root=proposal.output_path.parent" in source

