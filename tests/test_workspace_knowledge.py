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
    old = kn.add_candidate(
        "Prod region is us-west-1.", source="runbook-v1", scope="acme"
    )
    kn.approve(old.fid)
    assert [f.fid for f in kn.recall("prod region", "acme")] == [old.fid]
    new = kn.add_candidate(
        "Prod region is us-east-1.", source="runbook-v2", scope="acme"
    )
    kn.approve(new.fid)
    superseded = kn.supersede(old.fid, new.fid)
    assert superseded.status == "superseded" and superseded.superseded_by == new.fid
    assert superseded.source == "runbook-v1"  # history + provenance kept
    assert [f.fid for f in kn.recall("prod region", "acme")] == [
        new.fid
    ]  # only the new one
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
    far = kn.add_candidate("The Friday standup is at 9am.", source="s", scope="acme")
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
    assert "expires now" in run("expire-edge", "1")  # owner ends a relationship
    assert "expires now" in run("expire", "2")  # owner expires a live fact
    assert "[expired]" in run("list")  # list tags it expired, not its old status
    assert "#2" not in run("recall", "prod")  # expired fact not recalled
    assert run("expire", "99") == "no such fact"

    # time-scoped recall: a valid since: window narrows; a malformed one errors
    run("add", "src", "|", "Cache uses Redis.")
    run("approve", "5")
    assert "#5" in run("recall", "cache", "since:1")  # learned now, in a 1-day window
    assert run("recall", "cache", "since:7d").startswith("since:")  # malformed -> error
    assert run("recall", "cache", "since:").startswith("since:")

    # classify a missing id is a visible no-op (None signal), not a silent miss
    assert run("private", "99") == "no such fact"
    assert run("private-edge", "99") == "no such edge"
    assert k.classify(99, "sensitive") is None
    assert k.classify_edge(99, "sensitive") is None

    # private-source: knowledge from a matching source is sensitive at entry
    assert "private" in run("private-source", "1Password")
    assert run("private-sources") == "1Password"
    run("add", "1Password vault", "|", "unlock is hunter2")
    assert k.get(6).sensitivity == "sensitive"  # matched source -> private at entry
    assert run("unmark-source", "1Password") == "removed"
    assert run("unmark-source", "1Password") == "no such sensitive-source pattern"
    assert run("private-sources") == "(no private sources)"

    # private-default posture: deny-on-unknown toggle
    assert run("private-default") == "private-by-default is off"
    assert run("private-default", "on") == "private-by-default is on"
    assert "candidate #7" in run("add", "chat", "|", "another note")  # candidate...
    assert k.get(7).sensitivity == "sensitive"  # ...sensitive at entry under posture
    assert run("private-default", "off") == "private-by-default is off"
    assert run("private-default", "maybe").startswith("private-default wants")
    k.close()


def test_ingest_dedups_but_never_edits_existing_facts(kn):
    """Mem0's two-phase idea, owner-safe: a new text is added as a candidate,
    a near-duplicate is a noop, and ingestion never touches existing facts'
    status (no auto-update/delete -- that stays the owner's)."""

    approved = kn.add_candidate("Prod runs in us-east-1.", source="doc", scope="acme")
    kn.approve(approved.fid)

    actions = kn.ingest(
        [
            "Prod runs in us-east-1.",  # exact dup of an approved fact -> noop
            "Prod   runs in us-east-1.",  # whitespace-only diff -> still dup
            "The office moved to Lisbon.",  # new -> candidate
            "The office moved to Lisbon.",  # dup of the one just added this batch
            "   ",  # empty -> skipped
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
    assert (
        "2 file(s)" in out and "3 new candidate(s)" in out and "1 already known" in out
    )
    cands = k.list(scope="default", status="candidate")
    assert {c.text for c in cands} == {
        "Prod runs in us-east-1.",
        "Deploys happen on Fridays.",
        "The office is in Lisbon.",
    }
    assert {c.source for c in cands} == {
        "runbook.md",
        "notes.txt",
    }  # provenance = filename
    # candidates are not usable until reviewed
    assert k.recall("deploys fridays", "default") == []
    assert "no .md/.txt/.log" in know_command(
        k, "default", ["ingest", str(tmp_path / "nope")]
    )
    k.close()


def test_remember_claim_promotes_research_into_the_company_brain(tmp_path):
    """A cited research claim becomes a Company Brain candidate with its source
    URLs as provenance; the owner still reviews before it is usable."""

    from ghostcursor.workspace.brain import Brain
    from ghostcursor.workspace.contracts import (
        Claim,
        ClaimStatus,
        EvidenceGraph,
        Passage,
        Source,
        categorize,
    )
    from ghostcursor.workspace.session import Workspace

    k = Knowledge(tmp_path / "k.sqlite")
    ws = Workspace(
        "topic",
        object(),
        Brain(tmp_path / "b.sqlite"),
        root=tmp_path / "briefs",
        knowledge=k,
        kb_scope="default",
    )
    assert ws.remember_claim(1) == "no research yet; /research first"

    src = Source(
        "s1",
        "https://example.com/runbook",
        "Runbook",
        categorize("https://example.com/runbook"),
    )
    graph = EvidenceGraph(
        "where does prod run",
        (src,),
        (Passage("p1", "s1", "Prod runs in us-east-1."),),
        (Claim("Prod runs in us-east-1.", ClaimStatus.SUPPORTED, ("p1",)),),
    )
    ws.research_graphs.append(graph)
    out = ws.remember_claim(1)
    assert "candidate #1" in out and "example.com/runbook" in out

    cand = k.list(scope="default", status="candidate")
    assert len(cand) == 1
    assert cand[0].text == "Prod runs in us-east-1."
    assert cand[0].source == "research: https://example.com/runbook"
    assert k.recall("prod", "default") == []  # candidate, not usable yet
    assert ws.remember_claim(9) == "no such claim"
    k.close()


def test_clip_to_brain_captures_clipboard_as_owner_reviewed_candidate(tmp_path):
    """Cross-app copy -> Company Brain candidate. The text stays local (never
    sent to a model) and is not usable until the owner reviews it."""

    from ghostcursor.workspace.brain import Brain
    from ghostcursor.workspace.session import Workspace

    k = Knowledge(tmp_path / "k.sqlite")
    ws = Workspace(
        "t",
        object(),
        Brain(tmp_path / "b.sqlite"),
        root=tmp_path / "briefs",
        knowledge=k,
        kb_scope="default",
    )
    out = ws.clip_to_brain(read=lambda: "  The prod DB password rotates monthly.  ")
    assert "candidate #1" in out
    cand = k.list(scope="default", status="candidate")
    assert len(cand) == 1 and cand[0].source == "clipboard"
    assert cand[0].text == "The prod DB password rotates monthly."
    assert k.recall("prod db", "default") == []  # not usable until reviewed

    assert ws.clip_to_brain(read=lambda: "   ") == "the clipboard has no text to save"
    assert ws.clip_to_brain(read=lambda: "word") == "the clipboard has no text to save"

    def boom():
        raise OSError("clipboard locked")

    assert ws.clip_to_brain(read=boom) == "could not read the clipboard"
    k.close()


def test_clip_to_brain_truncates_an_over_length_clip(tmp_path):
    from ghostcursor.workspace.brain import Brain
    from ghostcursor.workspace.session import Workspace

    k = Knowledge(tmp_path / "k.sqlite")
    ws = Workspace(
        "t",
        object(),
        Brain(tmp_path / "b.sqlite"),
        root=tmp_path / "briefs",
        knowledge=k,
        kb_scope="default",
    )
    huge = "word " * 5000  # ~25k chars
    ws.clip_to_brain(read=lambda: huge)
    cand = k.list(scope="default", status="candidate")
    assert len(cand) == 1
    assert len(cand[0].text) <= ws.MAX_CLIP_CHARS < len(huge)  # truncated
    k.close()


def test_export_then_import_shares_facts_as_reviewable_candidates(tmp_path):
    """Offline team sharing: export a scope's usable facts/edges (no sensitive
    ones), import them into another Brain as CANDIDATES a new owner must review
    before trusting -- a teammate's facts are not auto-trusted."""

    a = Knowledge(tmp_path / "a.sqlite")
    f1 = a.add_candidate("Deploys run on Fridays.", source="runbook", scope="team")
    a.approve(f1.fid)
    secret = a.add_candidate(
        "Root password is hunter2.",
        source="vault",
        scope="team",
        sensitivity="sensitive",
    )
    a.approve(secret.fid)
    a.add_candidate("A draft nobody reviewed.", source="x", scope="team")  # candidate
    e = a.relate("Team", "deploys", "Fridays", source="runbook", scope="team")
    a.review_edge(e.eid)

    snap = a.export_scope("team")
    texts = {f["text"] for f in snap["facts"]}
    assert texts == {
        "Deploys run on Fridays."
    }  # usable only; sensitive + candidate excluded
    assert len(snap["edges"]) == 1

    b = Knowledge(tmp_path / "b.sqlite")
    r = b.import_scope(snap, "team")
    assert r == {"facts_added": 1, "facts_duplicate": 0, "edges": 1}
    # imported as a CANDIDATE, not usable until reviewed, provenance preserved
    assert b.recall("deploys", "team") == []
    cand = b.list(scope="team", status="candidate")
    assert len(cand) == 1 and cand[0].source == "shared: runbook"
    # re-import dedups
    assert b.import_scope(snap, "team")["facts_duplicate"] == 1

    import pytest as _p

    with _p.raises(ValueError):
        b.import_scope({"nope": True}, "team")
    a.close()
    b.close()


def test_know_export_import_console_roundtrip(tmp_path):
    from ghostcursor.workspace.__main__ import know_command

    src = Knowledge(tmp_path / "src.sqlite")
    f = src.add_candidate("Office is in Lisbon.", source="wiki", scope="default")
    src.approve(f.fid)
    path = str(tmp_path / "brain.json")
    out = know_command(src, "default", ["export", path])
    assert "1 fact(s)" in out

    dst = Knowledge(tmp_path / "dst.sqlite")
    out = know_command(dst, "default", ["import", path])
    assert "1 new" in out
    assert (
        dst.list(scope="default", status="candidate")[0].text == "Office is in Lisbon."
    )
    assert "could not import" in know_command(
        dst, "default", ["import", str(tmp_path / "no.json")]
    )
    src.close()
    dst.close()


def test_connected_surfaces_an_n_hop_fact_the_query_never_named(kn):
    """Graph-walk (Graphiti/Zep n-hop): a fact linked to a recall hit through a
    reviewed edge is surfaced even when the query words never matched it, and
    only once the edge is reviewed."""

    a = kn.add_candidate("Project Zephyr ships in March.", source="s", scope="acme")
    b = kn.add_candidate("Dana leads the platform team.", source="s", scope="acme")
    kn.approve(a.fid)
    kn.approve(b.fid)
    e = kn.relate("Zephyr", "owned-by", "Dana", source="org", scope="acme")

    assert kn.connected("zephyr", "acme") == []  # candidate edge: no walk yet
    kn.review_edge(e.eid)

    hop = kn.connected("zephyr", "acme")
    assert [f.fid for f in hop] == [b.fid]  # reached Dana's fact via the edge
    # connections() names the entity that bridged the fact in (explainability).
    conns = kn.connections("zephyr", "acme")
    assert [(f.fid, bridge) for f, bridge in conns] == [(b.fid, "Dana")]
    assert kn.connected("zephyr", "beta") == []  # scope-isolated

    facts, _edges = kn.context("zephyr", "acme")
    assert [f.fid for f in facts] == [a.fid, b.fid]  # direct hit first, hop appended


def test_export_markdown_is_readable_and_hides_sensitive(kn):
    """Markdown export (Obsidian-style readable portability) renders usable
    facts and reviewed relations, and omits sensitive facts so the owner can
    read exactly what will be shared."""

    ok = kn.add_candidate("Prod deploys on Friday.", source="runbook", scope="acme")
    sec = kn.add_candidate(
        "Root password is hunter2.",
        source="vault",
        scope="acme",
        sensitivity="sensitive",
    )
    kn.approve(ok.fid)
    kn.approve(sec.fid)
    e = kn.relate("Acme", "uses", "PostgreSQL", source="arch", scope="acme")
    kn.review_edge(e.eid)

    md = kn.export_markdown("acme")
    assert "# Company Brain export: acme" in md
    assert "Prod deploys on Friday." in md and "runbook" in md
    assert "Acme → uses → PostgreSQL" in md
    assert "hunter2" not in md  # sensitive excluded
    assert "hunter2" in kn.export_markdown("acme", include_sensitive=True)
    assert "_(none)_" in kn.export_markdown("beta")  # empty scope renders cleanly


def test_aging_surfaces_unverified_facts_without_excluding_them(kn):
    """Zep-style decay: a usable fact not re-verified within STALE_AFTER_S is
    still recalled but flagged aging; re-verifying it clears the flag."""
    from ghostcursor.workspace.knowledge import STALE_AFTER_S

    f = kn.add_candidate("VPN gateway is 10.0.0.1.", source="net", scope="acme")
    kn.approve(f.fid)
    assert kn.aging_among(kn.recall("vpn gateway", "acme")) == []  # fresh

    kn.now = 1000.0 + STALE_AFTER_S + 1
    hits = kn.recall("vpn gateway", "acme")
    assert [h.fid for h in hits] == [f.fid]  # still recalled -- not expired
    assert [a.fid for a in kn.aging_among(hits)] == [f.fid]  # but flagged aging
    assert [a.fid for a in kn.aging("acme")] == [f.fid]  # scope sweep sees it too

    kn.verify(f.fid)  # re-verify resets last_verified to now
    assert kn.aging_among(kn.recall("vpn gateway", "acme")) == []
    assert kn.aging("acme") == []


def test_recall_since_scopes_to_recently_learned_facts(kn):
    """Time-scoped recall (the privacy-safe answer to always-on-capture rivals):
    ``since`` keeps only facts Orbyn learned at or after that system time."""

    kn.now = 1_000_000.0
    kn.clock = lambda: kn.now
    old = kn.add_candidate("Billing uses Stripe.", source="s", scope="acme")
    kn.approve(old.fid)
    kn.now += 14 * 86400.0  # two weeks later
    new = kn.add_candidate("Billing moved to Adyen.", source="s", scope="acme")
    kn.approve(new.fid)

    week_ago = kn.now - 7 * 86400.0
    assert [f.fid for f in kn.recall("billing", "acme", since=week_ago)] == [new.fid]
    got = {f.fid for f in kn.recall("billing", "acme")}  # no window: both
    assert got == {old.fid, new.fid}


def test_recall_excludes_sensitive_facts_from_the_model_path_by_default(kn):
    """A sensitive fact must not ride the model-bound retrieval path (sending it
    to a BYOK model is egress, rule 6): recall excludes it by default, the owner
    opts in, and the n-hop/context paths that reach the model never see it."""

    s = kn.add_candidate(
        "Root password is hunter2.", source="ops", scope="acme", sensitivity="sensitive"
    )
    n = kn.add_candidate("The office opens at nine.", source="hr", scope="acme")
    kn.approve(s.fid)
    kn.approve(n.fid)

    assert [f.fid for f in kn.recall("password office", "acme")] == [
        n.fid
    ]  # model path
    got = {f.fid for f in kn.recall("password office", "acme", include_sensitive=True)}
    assert got == {s.fid, n.fid}  # owner's explicit local view sees it
    facts, _edges = kn.context("password", "acme")  # context feeds the model
    assert s.fid not in {f.fid for f in facts}


def test_an_expired_edge_drops_out_of_every_traversal(kn):
    """Graphiti-style temporal edge (competitor research, Zep bi-temporal): a
    relationship past its valid_until stops being walked by related/connected/
    connections and leaves the export, mirroring how a stale fact drops from
    recall. The row is never deleted -- the owner still governs it."""

    kn.now = 1000.0
    kn.clock = lambda: kn.now
    a = kn.add_candidate("Project Zephyr ships in March.", source="s", scope="acme")
    b = kn.add_candidate("Dana leads the platform team.", source="s", scope="acme")
    kn.approve(a.fid)
    kn.approve(b.fid)
    e = kn.relate(
        "Zephyr", "owned-by", "Dana", source="org", scope="acme", valid_until=2000.0
    )
    kn.review_edge(e.eid)

    assert [f.fid for f in kn.connected("zephyr", "acme")] == [b.fid]  # still valid
    assert len(kn.related("zephyr", "acme")) == 1
    assert len(kn.export_scope("acme")["edges"]) == 1

    kn.now = 2001.0  # past the edge's validity -> relationship no longer true
    assert kn.connected("zephyr", "acme") == []  # no n-hop walk over a dead edge
    assert kn.connections("zephyr", "acme") == []
    assert kn.related("zephyr", "acme") == []
    assert kn.neighbors("Zephyr", "acme") == []
    assert kn.export_scope("acme")["edges"] == []
    assert kn.edge(e.eid) is not None  # not deleted: owner still governs it


def test_owner_can_expire_an_existing_fact_and_edge(kn):
    """The owner learns a fact/relationship stopped being true and expires it
    as of now, keeping the window before as history (unlike retire's drop).
    After expiry recall and traversal skip it; the rows survive."""

    kn.now = 1000.0
    kn.clock = lambda: kn.now
    a = kn.add_candidate("Project Zephyr ships in March.", source="s", scope="acme")
    b = kn.add_candidate("Dana leads the platform team.", source="s", scope="acme")
    kn.approve(a.fid)
    kn.approve(b.fid)
    e = kn.relate("Zephyr", "owned-by", "Dana", source="org", scope="acme")
    kn.review_edge(e.eid)

    assert [f.fid for f in kn.recall("ships", "acme")] == [a.fid]
    assert [f.fid for f in kn.connected("zephyr", "acme")] == [b.fid]

    kn.expire(a.fid)  # fact stopped being true as of now
    kn.expire_edge(e.eid)  # relationship ended
    assert kn.recall("ships", "acme") == []  # expired fact not recalled
    assert kn.connected("zephyr", "acme") == []  # dead edge not walked
    assert kn.get(a.fid) is not None and kn.edge(e.eid) is not None  # kept as history


def test_list_edges_returns_candidates_and_reviewed_including_expired(kn):
    """The edge review panel needs every edge (unlike the traversal readers,
    which hide candidate and expired ones)."""

    kn.now = 1000.0
    kn.clock = lambda: kn.now
    c = kn.relate("A", "x", "B", source="s", scope="acme")  # candidate
    r = kn.relate("C", "y", "D", source="s", scope="acme")
    kn.review_edge(r.eid)
    kn.expire_edge(r.eid)  # reviewed but expired
    eids = {e.eid for e in kn.list_edges(scope="acme")}
    assert eids == {c.eid, r.eid}  # both shown despite candidate + expired
    assert kn.related("C", "acme") == []  # traversal still hides the expired one


def test_a_sensitive_edge_stays_off_the_model_path(kn):
    """FOLLOWUP (temporal-layer review): a sensitive relationship must not reach
    the model via related/connected/connections/neighbors or a shared export,
    mirroring sensitive facts -- but the owner's local list_edges still shows it."""

    a = kn.add_candidate("Project Zephyr ships in March.", source="s", scope="acme")
    b = kn.add_candidate("Dana leads the platform team.", source="s", scope="acme")
    kn.approve(a.fid)
    kn.approve(b.fid)
    e = kn.relate(
        "Zephyr",
        "owned-by",
        "Dana",
        source="org",
        scope="acme",
        sensitivity="sensitive",
    )
    kn.review_edge(e.eid)

    assert kn.related("zephyr", "acme") == []  # not query-matched to the model
    assert kn.neighbors("Zephyr", "acme") == []
    assert kn.connected("zephyr", "acme") == []  # no n-hop walk over a sensitive edge
    assert kn.connections("zephyr", "acme") == []
    assert kn.export_scope("acme")["edges"] == []  # excluded from a shared snapshot
    assert kn.export_scope("acme", include_sensitive=True)["edges"]  # unless asked
    assert e.eid in {x.eid for x in kn.list_edges(scope="acme")}  # owner still sees it
    import pytest

    with pytest.raises(ValueError):
        kn.relate("A", "x", "B", source="s", scope="acme", sensitivity="bogus")


def test_owner_can_mark_a_fact_or_edge_sensitive_after_the_fact(kn):
    """classify/classify_edge are the only way to set the flag post-hoc; marking
    sensitive pulls the row off the model path, unmarking puts it back."""

    import pytest

    a = kn.add_candidate("Office wifi password is hunter2.", source="s", scope="acme")
    b = kn.add_candidate("Dana leads the platform team.", source="s", scope="acme")
    kn.approve(a.fid)
    kn.approve(b.fid)
    e = kn.relate("Zephyr", "owned-by", "Dana", source="org", scope="acme")
    kn.review_edge(e.eid)

    assert a.fid in {f.fid for f in kn.recall("password", "acme")}
    assert kn.related("zephyr", "acme")  # normal edge is walked

    kn.classify(a.fid, "sensitive")
    kn.classify_edge(e.eid, "sensitive")
    assert kn.recall("password", "acme") == []  # now off the model path
    assert kn.related("zephyr", "acme") == []
    assert kn.get(a.fid).sensitivity == "sensitive"
    assert kn.edge(e.eid).sensitivity == "sensitive"

    kn.classify(a.fid, "normal")  # unmark restores
    kn.classify_edge(e.eid, "normal")
    assert a.fid in {f.fid for f in kn.recall("password", "acme")}
    assert kn.related("zephyr", "acme")

    with pytest.raises(ValueError):
        kn.classify(a.fid, "bogus")
    with pytest.raises(ValueError):
        kn.classify_edge(e.eid, "bogus")


def test_sensitive_source_marks_new_knowledge_private_at_entry(kn):
    """A registered private source lifts a new fact/edge to 'sensitive' at
    ingestion (Recall's source-identity exclusion, D186) without the owner
    marking each one; it only tightens, and an explicit sensitivity is kept."""

    import pytest

    kn.mark_source_sensitive("1Password")
    assert kn.sensitive_sources() == ["1Password"]

    # Source contains the pattern (case-insensitive) -> sensitive at entry.
    f = kn.add_candidate(
        "Vault unlock is hunter2.", source="1password window", scope="acme"
    )
    assert f.sensitivity == "sensitive"
    e = kn.relate("Dana", "uses", "1Password", source="1Password app", scope="acme")
    assert e.sensitivity == "sensitive"

    # Unmatched source stays normal.
    g = kn.add_candidate("Dana leads platform.", source="chat", scope="acme")
    assert g.sensitivity == "normal"

    # Never loosens: an explicit sensitive request on an unmatched source holds.
    s = kn.add_candidate("secret", source="chat", scope="acme", sensitivity="sensitive")
    assert s.sensitivity == "sensitive"

    # Removing the pattern stops tightening future adds; the rule persists across
    # reopen until then.
    assert kn.unmark_source_sensitive("1Password") is True
    assert kn.unmark_source_sensitive("1Password") is False
    h = kn.add_candidate("later note", source="1password window", scope="acme")
    assert h.sensitivity == "normal"

    with pytest.raises(ValueError):
        kn.mark_source_sensitive("   ")


def test_private_by_default_denies_on_unknown(kn):
    """Deny-on-unknown posture (D186, Recall port): when on, every new candidate
    enters sensitive regardless of source; off restores normal. Only tightens --
    an explicit sensitive is unaffected either way."""

    assert kn.private_by_default() is False
    kn.set_private_by_default(True)
    assert kn.private_by_default() is True

    f = kn.add_candidate("anything", source="random chat", scope="acme")
    assert f.sensitivity == "sensitive"  # unmatched source, but posture is deny
    e = kn.relate("A", "rel", "B", source="random", scope="acme")
    assert e.sensitivity == "sensitive"

    kn.set_private_by_default(False)
    g = kn.add_candidate("later", source="random chat", scope="acme")
    assert g.sensitivity == "normal"  # posture off -> back to allow-by-default


def test_facts_trace_back_to_the_episode_they_came_from(kn):
    """Episodes (D186, Graphiti's non-lossy input layer): ingest records the raw
    input once and every fact extracted from it links back via episode_of."""

    doc = "Prod runs in us-east-1. The cache uses Redis."
    actions = kn.ingest(
        ["Prod runs in us-east-1.", "The cache uses Redis."],
        source="runbook",
        scope="acme",
        episode=doc,
    )
    fids = [fid for action, fid in actions if action == "added"]
    assert len(fids) == 2
    ep = kn.episode_of(fids[0])
    assert ep is not None and ep.text == doc and ep.source == "runbook"
    # both facts point at the SAME episode (recorded once)
    assert kn.episode_of(fids[0]).eid == kn.episode_of(fids[1]).eid

    # a plain add_candidate (no episode) has no episode link
    f = kn.add_candidate("standalone fact", source="chat", scope="acme")
    assert kn.episode_of(f.fid) is None
    # ingest without an episode links nothing
    (a,) = kn.ingest(["another"], source="chat", scope="acme")
    assert kn.get(a[1]).episode_id is None


def test_export_redacts_embedded_secrets_before_egress(kn):
    """A *normal* fact that quotes a secret must not leak it on export (the
    enterprise redact-before-egress gate, D186). Default redacts; the audit
    counts categories; redact_pii=False gives a verbatim owner backup."""

    f = kn.add_candidate("Billing email is ada@acme.io", source="doc", scope="acme")
    kn.approve(f.fid)

    data = kn.export_scope("acme")
    assert "ada@acme.io" not in data["facts"][0]["text"]  # scrubbed
    assert "[EMAIL_1]" in data["facts"][0]["text"]
    assert data["redacted"].get("EMAIL") == 1  # audited, count only

    md = kn.export_markdown("acme")
    assert "ada@acme.io" not in md and "redacted before egress" in md

    raw = kn.export_scope("acme", redact_pii=False)
    assert "ada@acme.io" in raw["facts"][0]["text"]  # owner's verbatim backup
    assert raw["redacted"] == {}


def test_a_superseded_fact_cannot_be_approved_back_beside_its_successor(kn):
    old = kn.add_candidate("Prod region is us-west-1.", source="v1", scope="acme")
    new = kn.add_candidate("Prod region is us-east-1.", source="v2", scope="acme")
    kn.approve(old.fid)
    kn.approve(new.fid)
    kn.supersede(old.fid, new.fid)
    with pytest.raises(ValueError, match="replaced"):
        kn.approve(old.fid)
    assert [f.fid for f in kn.recall("prod region", "acme")] == [new.fid]


def test_scope_lookups_use_an_index(tmp_path):
    k = Knowledge(tmp_path / "k.sqlite")
    try:
        plan = " ".join(
            str(r[-1])
            for r in k._db.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM edges WHERE scope=? AND status='reviewed'",
                ("s",),
            )
        )
        assert "INDEX" in plan
    finally:
        k.close()


_SECRET = "sk-live" + "A" * 24  # a provider-key shape (built so scans do not flag it)
_CARD = "4111 1111 1111 1111"  # Luhn-valid test card


def _dump(path) -> str:
    import sqlite3

    db = sqlite3.connect(path)
    try:
        return "\n".join(db.iterdump())  # every table, the FTS index included
    finally:
        db.close()


def test_a_pasted_secret_never_rests_in_the_brain(tmp_path):
    """Clipboard capture is the likeliest way a key or card lands in the
    Brain; it is scrubbed on write, and contact details stay."""

    from ghostcursor.workspace.brain import Brain
    from ghostcursor.workspace.session import Workspace

    k = Knowledge(tmp_path / "k.sqlite")
    ws = Workspace(
        "t", object(), Brain(tmp_path / "b.sqlite"), root=tmp_path / "briefs",
        knowledge=k, kb_scope="default",
    )  # fmt: skip
    ws.clip_to_brain(read=lambda: f"Billing key {_SECRET} card {_CARD}, ask ops@acme.example")
    (fact,) = k.list(scope="default", status="candidate")
    assert "[KEY_1]" in fact.text and "[CARD_1]" in fact.text
    assert "ops@acme.example" in fact.text  # a contact is a fact, not a secret
    k.close()
    dump = _dump(tmp_path / "k.sqlite")
    assert _SECRET not in dump and _CARD not in dump


def test_every_brain_write_path_scrubs_secrets(tmp_path):
    k = Knowledge(tmp_path / "k.sqlite")
    k.add_candidate(f"deploy token {_SECRET}", source=f"https://x.example/?t={_SECRET}", scope="s")
    k.record_episode(f"raw note with {_SECRET}", source="note", scope="s")
    k.relate(f"svc {_SECRET}", "uses", f"card {_CARD}", source="typed", scope="s")
    first = k.ingest([f"rotate {_SECRET} monthly"], source="doc", scope="s",
                     episode=f"episode {_CARD}")  # fmt: skip
    again = k.ingest([f"rotate {_SECRET} monthly"], source="doc", scope="s")
    assert first[0][0] == "added" and again == [("duplicate", first[0][1])]
    k.close()
    dump = _dump(tmp_path / "k.sqlite")
    assert _SECRET not in dump and _CARD not in dump


def test_a_repeat_never_loosens_and_can_only_tighten(kn):
    """Tier-1 review 14 Nov: a link or fact met again is not stored twice, but
    if this arrival is private (asked for, a private source, private by
    default) the one already there becomes private. Never the reverse."""

    first = kn.relate("Priya", "salary", "200k", source="note", scope="acme")
    assert first.sensitivity == "normal"
    again = kn.relate("PRIYA", "salary", "200k", source="note", scope="acme", sensitivity="sensitive")
    assert again.eid == first.eid and again.sensitivity == "sensitive"
    assert kn.edge(first.eid).sensitivity == "sensitive"
    assert len(kn.list_edges(scope="acme")) == 1
    back = kn.relate("Priya", "salary", "200k", source="note", scope="acme")  # normal again
    assert back.eid == first.eid and back.sensitivity == "sensitive"  # stays private
    other = kn.relate("Priya", "salary", "200k", source="note", scope="other")
    assert other.eid != first.eid and other.sensitivity == "normal"  # scopes apart

    kn.mark_source_sensitive("payroll")
    plain = kn.relate("Sam", "reports to", "Priya", source="wiki", scope="acme")
    lifted = kn.relate("Sam", "reports to", "Priya", source="payroll export", scope="acme")
    assert lifted.eid == plain.eid and lifted.sensitivity == "sensitive"

    fact = kn.add_candidate("Bonuses are paid in March", source="wiki", scope="acme")
    assert kn.ingest(["Bonuses are paid in March"], source="wiki", scope="acme") == [("duplicate", fact.fid)]
    assert kn.get(fact.fid).sensitivity == "normal"
    assert kn.ingest(["Bonuses are paid in March"], source="payroll.md", scope="acme") == [("duplicate", fact.fid)]
    assert kn.get(fact.fid).sensitivity == "sensitive"
    kn.tighten(fact.fid, "wiki")
    assert kn.get(fact.fid).sensitivity == "sensitive"  # a normal arrival changes nothing



def test_fact_and_document_text_are_sealed_on_disk_and_search_still_works(tmp_path):
    """A copied knowledge.sqlite shows no fact, no source document and no
    search index; only this Windows account reads it back (DPAPI)."""

    import sqlite3

    path = tmp_path / "k.sqlite"
    k = Knowledge(path)
    eid = k.record_episode("Minutes: refunds over 500 need Priya", source="meeting", scope="s")
    f = k.add_candidate("Refunds over 500 need Priya", source="meeting", scope="s", episode_id=eid)
    k.approve(f.fid)
    k.close()
    raw = path.read_bytes()
    assert b"Priya" not in raw and b"Refunds" not in raw and b"refund" not in raw
    names = {r[0] for r in sqlite3.connect(path).execute("SELECT name FROM sqlite_master")}
    assert not any("fts" in n for n in names)  # no index on disk
    k = Knowledge(path)
    assert [x.text for x in k.recall("refunds", "s")] == ["Refunds over 500 need Priya"]
    assert k.episode(eid).text == "Minutes: refunds over 500 need Priya"
    k.close()


def test_an_older_plain_brain_is_sealed_and_its_index_dropped_on_open(tmp_path):
    import sqlite3

    path = tmp_path / "k.sqlite"
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE facts (fid INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, source TEXT NOT NULL,"
        " scope TEXT NOT NULL, status TEXT NOT NULL, sensitivity TEXT NOT NULL, added REAL NOT NULL,"
        " last_verified REAL NOT NULL, valid_until REAL, valid_from REAL NOT NULL DEFAULT 0,"
        " superseded_by INTEGER, episode_id INTEGER);"
        "CREATE VIRTUAL TABLE facts_fts USING fts5(text, tokenize='porter unicode61');"
        "INSERT INTO facts VALUES (1,'Launch is in Q3 for Zeus','plan','s','approved','normal',0,0,NULL,0,NULL,NULL);"
        "INSERT INTO facts_fts(rowid, text) VALUES (1,'Launch is in Q3 for Zeus');"
    )
    db.commit()
    db.close()
    k = Knowledge(path)
    assert [x.text for x in k.recall("launch", "s")] == ["Launch is in Q3 for Zeus"]
    k.close()
    assert b"Zeus" not in path.read_bytes()


def test_a_fact_this_account_cannot_open_is_never_recalled(tmp_path):
    from ghostcursor.workspace.brain import LOCKED

    k = Knowledge(tmp_path / "k.sqlite")
    f = k.add_candidate("Refunds go to finance", source="x", scope="s")
    k.approve(f.fid)
    with k._db:
        k._db.execute("UPDATE facts SET text='dp1:AAAA' WHERE fid=?", (f.fid,))
    assert k.get(f.fid).text == LOCKED
    k.close()
    k = Knowledge(tmp_path / "k.sqlite")
    assert k.recall("locked account computer", "s") == [] and k.recall("refunds", "s") == []
    k.close()


def test_the_brain_opens_when_windows_cannot_seal(tmp_path, monkeypatch):
    import sqlite3

    from ghostcursor.workspace import knowledge as kmod

    path = tmp_path / "k.sqlite"
    Knowledge(path).close()
    db = sqlite3.connect(path)
    db.execute("INSERT INTO facts VALUES (1,'Plain fact about tea','x','s','approved','normal',0,0,NULL,0,NULL,NULL)")
    db.commit()
    db.close()

    def refuse(text):
        raise OSError("no profile")

    monkeypatch.setattr(kmod, "_seal", refuse)
    k = Knowledge(path)  # does not raise
    assert [x.text for x in k.recall("tea", "s")] == ["Plain fact about tea"]
    k.close()


def test_the_in_memory_index_never_spills_to_a_temp_file(tmp_path):
    """Tier-1 review 15 Nov (blocking): without temp_store=MEMORY a large
    index spilled to %TEMP%, plaintext and all."""

    k = Knowledge(tmp_path / "k.sqlite")
    assert k._db.execute("PRAGMA temp_store").fetchone()[0] == 2  # MEMORY
    k.close()


def test_ticket_and_slack_exports_become_one_passage_per_row_or_message():
    import json

    import pytest

    from ghostcursor.workspace.knowledge import chunk_export

    csv_text = "id,title,resolution\n1,Refund over 500,Needs a manager\n2,,\n3,Login loop,Clear the cache\n"
    assert chunk_export("tickets.csv", csv_text) == [
        "id: 1; title: Refund over 500; resolution: Needs a manager",
        "id: 3; title: Login loop; resolution: Clear the cache",
    ]
    slack = [
        {"type": "message", "text": "Pricing exceptions go to Sam"},
        {"type": "message", "subtype": "channel_join", "text": "<@U1> has joined the channel"},
        {"type": "message", "text": "ok"},
        "junk",
    ]
    assert chunk_export("2026-11-01.json", json.dumps(slack)) == ["Pricing exceptions go to Sam"]
    assert chunk_export("notes.md", "anything") is None
    for bad in ("{not json", '{"a": 1}'):
        with pytest.raises(ValueError):
            chunk_export("x.json", bad)
