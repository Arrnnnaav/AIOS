"""Backlinks view (D186, Reflect/Mem): /related shows matching facts plus
facts one hop away over reviewed relations, with the bridging entity.

Pins: only reviewed facts/edges surface, the bridge is shown, and no Brain
means a clear message (not a crash).
"""

from __future__ import annotations

from ghostcursor.workspace.brain import Brain
from ghostcursor.workspace.knowledge import Knowledge
from ghostcursor.workspace.session import Workspace


def test_related_shows_matches_and_one_hop_connections(tmp_path):
    kb = Knowledge(tmp_path / "k.sqlite")
    a = kb.add_candidate("Prod runs in us-east-1.", source="runbook", scope="acme")
    b = kb.add_candidate(
        "us-east-1 is the primary region.", source="runbook", scope="acme"
    )
    kb.approve(a.fid)
    kb.approve(b.fid)
    e = kb.relate("Prod", "runs in", "us-east-1", source="runbook", scope="acme")
    kb.review_edge(e.eid)

    brain = Brain(tmp_path / "b.sqlite")
    ws = Workspace(
        "w", object(), brain, knowledge=kb, kb_scope="acme", root=tmp_path / "br"
    )
    out = ws.related("prod")
    assert "Prod runs in us-east-1." in out
    assert "Connected" in out and "via" in out  # one-hop with a bridge entity
    brain.close()
    kb.close()


def test_related_without_brain_or_query(tmp_path):
    brain = Brain(tmp_path / "b.sqlite")
    ws_no_kb = Workspace("w", object(), brain, root=tmp_path / "br1")
    assert "no Company Brain" in ws_no_kb.related("x")

    kb = Knowledge(tmp_path / "k.sqlite")
    ws = Workspace(
        "w", object(), brain, knowledge=kb, kb_scope="acme", root=tmp_path / "br2"
    )
    assert "related to what" in ws.related("   ")
    kb.close()
    brain.close()
