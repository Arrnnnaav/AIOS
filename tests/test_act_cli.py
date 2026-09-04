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

