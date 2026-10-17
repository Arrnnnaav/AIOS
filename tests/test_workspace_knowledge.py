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


def test_supersede_invalidates_but_keeps_history_and_provenance(kn):
    old = kn.add_candidate("Prod region is us-west-1.", source="runbook-v1", scope="acme")
    kn.approve(old.fid)
    assert [f.fid for f in kn.recall("prod region", "acme")] == [old.fid]
    new = kn.add_candidate("Prod region is us-east-1.", source="runbook-v2", scope="acme")
    kn.approve(new.fid)
    superseded = kn.supersede(old.fid, new.fid)
    assert superseded.status == "superseded" and superseded.superseded_by == new.fid
    assert superseded.source == "runbook-v1"  # history + provenance kept
    assert [f.fid for f in kn.recall("prod region", "acme")] == [new.fid]  # only the new one
    assert kn.supersede.__doc__  # supersede documented
    import pytest as _p
    with _p.raises(ValueError):
        kn.supersede(old.fid, 9999)  # successor must exist


def test_bitemporal_valid_from_defaults_to_added(kn):
    f = kn.add_candidate("x", source="s", scope="acme")
    assert f.valid_from == f.added == 1000.0
    g = kn.add_candidate("y", source="s", scope="acme", valid_from=500.0)
    assert g.valid_from == 500.0 and g.added == 1000.0  # world vs system time differ


def test_context_graph_relate_review_and_neighbors(kn):
    e = kn.relate("Acme", "uses", "PostgreSQL", source="arch-doc", scope="acme")
    assert e.status == "candidate"
    assert kn.neighbors("Acme", "acme") == []  # candidate edges not returned
    kn.review_edge(e.fid if hasattr(e, "fid") else e.eid)
    ns = kn.neighbors("postgresql", "acme")  # case-insensitive, matches object
    assert len(ns) == 1 and ns[0].predicate == "uses" and ns[0].source == "arch-doc"
    assert kn.neighbors("Acme", "beta") == []  # scope-isolated
    import pytest as _p
    with _p.raises(ValueError):
        kn.relate("", "p", "o", source="s", scope="acme")


def test_recall_ranks_by_bm25_and_stems(kn):
    """Retrieval is BM25-ranked (Zep/Mem0 parity), Porter-stemmed so a query
    term matches its inflections, not exact-word-only."""

    near = kn.add_candidate(
        "Production deploys happen every Friday afternoon.", source="s", scope="acme"
    )
    far = kn.add_candidate(
        "The Friday standup is at 9am.", source="s", scope="acme"
    )
    kn.approve(near.fid)
    kn.approve(far.fid)
    hits = kn.recall("friday deploy", "acme")  # both match friday; near also deploy
    assert [h.fid for h in hits] == [near.fid, far.fid]  # deploy fact ranks first
    assert kn.recall("deploying production", "acme")[0].fid == near.fid
    assert kn.recall("", "acme") == []  # no terms -> nothing, not everything


def test_fts_backfills_a_db_written_before_the_index_existed(tmp_path):
    """Opening an older store (facts present, no FTS rows) backfills the index
    so recall still works."""

    import sqlite3

    from ghostcursor.workspace.knowledge import Knowledge

    path = tmp_path / "old.sqlite"
    raw = sqlite3.connect(path)
    raw.executescript(
        "CREATE TABLE facts (fid INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, "
        "source TEXT, scope TEXT, status TEXT, sensitivity TEXT, added REAL, "
        "last_verified REAL, valid_until REAL, valid_from REAL DEFAULT 0, "
        "superseded_by INTEGER);"
    )
    raw.execute(
        "INSERT INTO facts VALUES (1,'Legacy fact about billing','s','acme',"
        "'approved','normal',0,0,NULL,0,NULL)"
    )
    raw.commit()
    raw.close()
    k = Knowledge(path)
    assert [f.fid for f in k.recall("billing", "acme")] == [1]
    k.close()


def test_know_command_owner_review_path(tmp_path):
    """The /know console path: add makes a candidate (not recalled), review
    makes it usable, supersede/conflicts/recall work, bad input is refused."""

    from ghostcursor.workspace.__main__ import know_command

    k = Knowledge(tmp_path / "k.sqlite")
    scope = "default"
    run = lambda *a: know_command(k, scope, list(a))

    assert "candidate #1" in run("add", "runbook", "|", "Prod is in us-east-1.")
    assert run("recall", "prod region") == "(nothing)"  # candidate not recalled
    assert run("review", "1").endswith("reviewed")
    assert "us-east-1" in run("recall", "prod region")  # now usable
    assert run("review", "99") == "no such fact"
    assert run("add", "runbook").startswith("usage")  # no '|' -> usage

    run("add", "doc", "|", "Prod is in us-west-2.")
    run("approve", "2")
    assert "superseded by #2" in run("supersede", "1", "2")
    assert "#2" in run("recall", "prod") and "#1 " not in run("recall", "prod")

    run("add", "a", "|", "The DB is encrypted at rest.")
    run("add", "b", "|", "The DB is not encrypted at rest.")
    run("review", "3")
    run("review", "4")
    assert "#3 <> #4" in run("conflicts")

    assert "edge #1 added" in run("relate", "Acme", "|", "uses", "|", "PG", "|", "doc")
    assert run("review-edge", "1").endswith("reviewed")
    k.close()


def test_ingest_dedups_but_never_edits_existing_facts(kn):
    """Mem0's two-phase idea, owner-safe: a new text is added as a candidate,
    a near-duplicate is a noop, and ingestion never touches existing facts'
    status (no auto-update/delete -- that stays the owner's)."""

    approved = kn.add_candidate("Prod runs in us-east-1.", source="doc", scope="acme")
    kn.approve(approved.fid)

    actions = kn.ingest(
        [
            "Prod runs in us-east-1.",          # exact dup of an approved fact -> noop
            "Prod   runs in us-east-1.",        # whitespace-only diff -> still dup
            "The office moved to Lisbon.",      # new -> candidate
            "The office moved to Lisbon.",      # dup of the one just added this batch
            "   ",                               # empty -> skipped
        ],
        source="wiki",
        scope="acme",
    )
    kinds = [a for a, _ in actions]
    assert kinds == ["duplicate", "duplicate", "added", "duplicate", "skipped"]
    assert actions[0][1] == approved.fid  # duplicate points at the existing fact

    # the approved fact is untouched; exactly one new candidate exists
    assert kn.get(approved.fid).status == "approved"
    cands = kn.list(scope="acme", status="candidate")
    assert len(cands) == 1 and cands[0].text == "The office moved to Lisbon."
    # ingestion is scope-isolated
    assert kn.ingest(["Prod runs in us-east-1."], source="x", scope="beta") == [
        ("added", cands[0].fid + 1)
    ]


def test_chunk_document_splits_on_blank_lines_and_bounds():
    from ghostcursor.workspace.knowledge import MAX_CHUNKS, chunk_document

    text = "First fact here.\n\n  \n\nSecond  fact\ntoo.\n\nx\n\nThird fact line."
    chunks = chunk_document(text)
    assert chunks == ["First fact here.", "Second fact too.", "Third fact line."]
    # lone-word block "x" dropped; whitespace collapsed
    big = "\n\n".join(f"fact number {i}" for i in range(MAX_CHUNKS + 50))
    assert len(chunk_document(big)) == MAX_CHUNKS  # count bounded


def test_know_ingest_loads_a_folder_as_candidates_deduped(tmp_path):
    from ghostcursor.workspace.__main__ import know_command

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "runbook.md").write_text(
        "Prod runs in us-east-1.\n\nDeploys happen on Fridays.", encoding="utf-8"
    )
    (docs / "notes.txt").write_text(
        "Deploys happen on Fridays.\n\nThe office is in Lisbon.", encoding="utf-8"
    )
    (docs / "ignore.pdf").write_text("binary-ish", encoding="utf-8")  # not loaded

    k = Knowledge(tmp_path / "k.sqlite")
    out = know_command(k, "default", ["ingest", str(docs)])
    assert "2 file(s)" in out and "3 new candidate(s)" in out and "1 already known" in out
    cands = k.list(scope="default", status="candidate")
    assert {c.text for c in cands} == {
        "Prod runs in us-east-1.",
        "Deploys happen on Fridays.",
        "The office is in Lisbon.",
    }
    assert {c.source for c in cands} == {"runbook.md", "notes.txt"}  # provenance = filename
    # candidates are not usable until reviewed
    assert k.recall("deploys fridays", "default") == []
    assert "no .md/.txt/.log" in know_command(k, "default", ["ingest", str(tmp_path / "nope")])
    k.close()
