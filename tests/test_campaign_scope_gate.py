"""A counted campaign refuses to start without one shared scope.

A 3/3 campaign is three separate invocations of `act_acceptance`. A target
reference is only comparable inside one campaign scope, and a process that
inherits no scope derives its own -- so three runs produce three scopes, and
`render_add_slide_evidence` refuses the records as coming from three different
campaigns.

That refusal would arrive *after* all three runs had been performed, on a real
desktop, with a human clicking approvals. A sixth review found it by reading the
two tools together: `act_campaign.py` exports the scope, but CLAUDE.md names
`act_acceptance --diagnostics` as the campaign tool, and that one never did.

So the refusal moves to the front: no scope, no diagnostics, before the first
run rather than after the third (D133).
"""

from pathlib import Path

import pytest

from ghostcursor.devtools.act_acceptance import (
    CAMPAIGN_SALT_VARIABLE,
    CAMPAIGN_SCOPE_VARIABLE,
    campaign_scope_refusal,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {CAMPAIGN_SCOPE_VARIABLE: "abc123456789"},
        {CAMPAIGN_SALT_VARIABLE: "aa" * 32},
        {CAMPAIGN_SCOPE_VARIABLE: "", CAMPAIGN_SALT_VARIABLE: ""},
        {CAMPAIGN_SCOPE_VARIABLE: "abc", CAMPAIGN_SALT_VARIABLE: ""},
    ],
)
def test_an_incomplete_campaign_scope_is_refused(environment):
    """Half a scope is no scope: both variables, or neither."""

    refusal = campaign_scope_refusal(environment)

    assert refusal is not None
    assert "campaign scope" in refusal


def test_a_complete_scope_is_allowed():
    assert (
        campaign_scope_refusal(
            {CAMPAIGN_SCOPE_VARIABLE: "abc123456789", CAMPAIGN_SALT_VARIABLE: "aa" * 32}
        )
        is None
    )


def test_the_refusal_says_what_to_do_next():
    """A refusal that does not say how to satisfy it gets worked around."""

    refusal = campaign_scope_refusal({})

    assert CAMPAIGN_SCOPE_VARIABLE in refusal
    assert CAMPAIGN_SALT_VARIABLE in refusal
    # And that the salt is not an artifact anyone keeps.
    assert "never" in refusal and "written down" in refusal


def test_the_gate_guards_only_the_diagnostics_branch():
    """An uninstrumented run must stay byte-identical in behaviour: the scope
    matters for records that will later be compared, not for running at all."""

    source = (ROOT / "ghostcursor" / "devtools" / "act_acceptance.py").read_text(
        encoding="utf-8"
    )
    branch = source.index("if args.diagnostics is not None:")
    call = source.index("campaign_scope_refusal()")

    assert branch < call, "the scope check must sit inside the diagnostics branch"


def test_the_campaign_runner_and_the_acceptance_tool_agree_on_the_names():
    """Two tools, one contract. If `act_campaign` exported a different variable
    than `act_acceptance` reads, every campaign would refuse or -- worse --
    silently fall back to per-process scopes again."""

    campaign = (ROOT / "ghostcursor" / "devtools" / "act_campaign.py").read_text(
        encoding="utf-8"
    )
    acceptance_names = {CAMPAIGN_SCOPE_VARIABLE, CAMPAIGN_SALT_VARIABLE}

    for name in acceptance_names:
        assert name in campaign, f"{name} is not exported by act_campaign"
