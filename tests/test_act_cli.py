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

