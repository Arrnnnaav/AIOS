"""Company Brain store (MP7 21A): curated, provenance-labelled facts in a
store distinct from the Personal Brain; candidates are not usable facts until
an owner reviews them; retrieval is scope-isolated, fresh, and provenance-
bearing; conflicts are surfaced, never auto-resolved."""

from __future__ import annotations

import pytest

from ghostcursor.workspace.knowledge import Knowledge


@pytest.fixture
def kn(tmp_path):
    k = Knowledge(tmp_path / "knowledge.sqlite")
    k.now = 1000.0
    k.clock = lambda: k.now  # tests advance time via kn.now
    yield k
    k.close()


def test_a_candidate_is_not_a_usable_fact_until_reviewed(kn):
    c = kn.add_candidate(
        "The deploy runbook lives in Notion.", source="wiki", scope="acme"
    )
    assert c.status == "candidate"
    assert kn.recall("deploy runbook", "acme") == []  # candidates never retrieved
    kn.review(c.fid)
    hits = kn.recall("deploy runbook", "acme")
    assert len(hits) == 1 and hits[0].source == "wiki" and hits[0].status == "reviewed"


def test_source_and_scope_are_required_provenance(kn):
    for bad in (dict(source="", scope="acme"), dict(source="wiki", scope="")):
        with pytest.raises(ValueError):
            kn.add_candidate("x", **bad)


def test_retrieval_is_isolated_by_scope(kn):
    a = kn.add_candidate("Acme ships on Fridays.", source="s", scope="acme")
    b = kn.add_candidate("Beta ships on Mondays.", source="s", scope="beta")
    kn.review(a.fid)
    kn.review(b.fid)
    assert [f.scope for f in kn.recall("ships", "acme")] == ["acme"]
    assert [f.scope for f in kn.recall("ships", "beta")] == ["beta"]


def test_retired_and_stale_facts_are_not_recalled(kn):
    old = kn.add_candidate(
        "Use the v1 API.", source="s", scope="acme", valid_until=1500.0
    )
    gone = kn.add_candidate("Office is in Berlin.", source="s", scope="acme")
    kn.approve(old.fid)
    kn.review(gone.fid)
    assert {f.text for f in kn.recall("api office", "acme")} == {
        "Use the v1 API.",
        "Office is in Berlin.",
    }
    kn.retire(gone.fid)
    kn.now = 2000.0  # past old's validity
    assert kn.recall("api office", "acme") == []  # one retired, one stale


def test_approve_and_verify_track_status_and_freshness(kn):
    f = kn.add_candidate("Prod region is us-east-1.", source="runbook", scope="acme")
    kn.now = 1100.0
    kn.review(f.fid)
    kn.now = 1200.0
    approved = kn.approve(f.fid)
    assert approved.status == "approved" and approved.last_verified == 1200.0
    kn.now = 1300.0
    assert kn.verify(f.fid).last_verified == 1300.0


def test_conflicts_are_surfaced_not_resolved(kn):
    a = kn.add_candidate("The database is encrypted at rest.", source="s", scope="acme")
    b = kn.add_candidate(
        "The database is not encrypted at rest.", source="t", scope="acme"
    )
    kn.review(a.fid)
    kn.review(b.fid)
    pairs = kn.conflicts("acme")
    assert len(pairs) == 1
    assert {pairs[0][0].text, pairs[0][1].text} == {a.text, b.text}
    # both remain usable; the owner decides
    assert len(kn.list(scope="acme", status="reviewed")) == 2
