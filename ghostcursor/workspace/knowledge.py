"""Company Brain: curated organizational knowledge, provenance-labelled
(MP7 phase 21A; D070's reserved `knowledge.sqlite`).

This is NOT the Personal Brain and NOT a dump of documents. It is distinct
from screen-derived `kb.sqlite`/`brain.sqlite`: a separate store with its own
lifecycle and no execution authority. Every fact carries source, scope
(tenant/owner), a review STATUS, when it was added and last verified, and a
sensitivity. Knowledge moves through states an owner governs:

    candidate  -- extracted/added, untrusted, not yet usable as a fact
    reviewed   -- an owner accepted it; may be retrieved as a fact with source
    approved   -- a reusable, blessed fact/procedure
    retired    -- removed from use (kept only as superseded history)

Ingestion produces candidates; it cannot publish a fact. Retrieval returns
facts WITH their provenance and any conflicts, never an unattributed answer.
Personal memories are never silently copied in -- sharing one is an explicit
reviewed add here, with its own provenance.
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

ENV_PATH = "ORBYN_KNOWLEDGE_PATH"
# superseded: replaced by a newer fact, kept as history (Graphiti/Zep's
# "invalidate, never delete"). retired: removed by an owner.
STATES = ("candidate", "reviewed", "approved", "superseded", "retired")
USABLE = ("reviewed", "approved")  # what retrieval may return as a fact
SENSITIVITIES = ("normal", "sensitive")
EDGE_STATES = ("candidate", "reviewed")


def _default_path() -> Path:
    if os.environ.get(ENV_PATH):
        return Path(os.environ[ENV_PATH])
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "GhostCursor" / "knowledge.sqlite"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    fid INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL, source TEXT NOT NULL, scope TEXT NOT NULL,
    status TEXT NOT NULL, sensitivity TEXT NOT NULL,
    added REAL NOT NULL, last_verified REAL NOT NULL, valid_until REAL,
    valid_from REAL NOT NULL DEFAULT 0, superseded_by INTEGER
);
CREATE TABLE IF NOT EXISTS edges (
    eid INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL, predicate TEXT NOT NULL, object TEXT NOT NULL,
    source TEXT NOT NULL, scope TEXT NOT NULL, status TEXT NOT NULL,
    added REAL NOT NULL
);
-- Full-text index over fact text for BM25-ranked recall (Zep/Mem0/Cognee all
-- rank by relevance, not word count). rowid = fid; Porter stemming so a query
-- 'deploy' matches 'deploys'. Rows are added on add_candidate and backfilled
-- for any pre-existing facts at open; status/validity are filtered after.
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts
    USING fts5(text, tokenize='porter unicode61');
"""


@dataclass(frozen=True)
class Fact:
    fid: int
    text: str
    source: str  # provenance: where it came from (never silently "the user")
    scope: str  # tenant/owner the fact belongs to
    status: str
    sensitivity: str
    added: float  # system time: when Orbyn learned it
    last_verified: float
    valid_until: float | None  # world time end; None = no expiry
    valid_from: float = 0.0  # world time start (bi-temporal)
    superseded_by: int | None = None  # the fact that replaced this one

    def stale(self, now: float) -> bool:
        return self.valid_until is not None and now >= self.valid_until


@dataclass(frozen=True)
class Edge:
    """One relationship in the Context Graph: subject --predicate--> object,
    with its own provenance and review status."""

    eid: int
    subject: str
    predicate: str
    object: str
    source: str
    scope: str
    status: str
    added: float


def _words(text: str) -> set[str]:
    import re

    return set(re.findall(r"[a-z0-9]{2,}", text.casefold()))


def _jaccard(a: set[str], b: set[str]) -> float:
    """Word-set overlap, 0..1. Used for ingest dedup (no embeddings: offline,
    deterministic). 1.0 = same words; near-1.0 = near-identical wording."""

    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _fts_query(query: str) -> str | None:
    """A safe FTS5 MATCH string: the query's alnum terms OR-ed together (any
    term may match, ranked by BM25). None when the query has no usable term,
    so the caller returns nothing rather than matching everything. Only alnum
    tokens are kept, so FTS operators and quotes cannot be injected."""

    terms = _words(query)
    return " OR ".join(sorted(terms)) if terms else None


class Knowledge:
    """The Company Brain store. Owner-governed: adding makes a *candidate*;
    only an explicit review/approve makes a fact retrievable."""

    def __init__(self, path: Path | None = None, *, clock=time.time):
        self.path = path or _default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self._db = sqlite3.connect(self.path)
        self._db.execute("PRAGMA secure_delete = ON")  # retire overwrites on disk
        self._db.executescript(_SCHEMA)
        with self._db:  # backfill the FTS index for facts added before it existed
            self._db.execute(
                "INSERT INTO facts_fts(rowid, text) SELECT fid, text FROM facts "
                "WHERE fid NOT IN (SELECT rowid FROM facts_fts)"
            )

    def close(self) -> None:
        self._db.close()

    # --- ingestion (candidates only) ------------------------------------

    def add_candidate(
        self,
        text: str,
        *,
        source: str,
        scope: str,
        sensitivity: str = "normal",
        valid_from: float | None = None,
        valid_until: float | None = None,
    ) -> Fact:
        """Record an untrusted candidate. It is NOT a usable fact until an
        owner reviews it. ``source`` is required provenance; empty is refused."""

        text = " ".join(str(text).split())
        source = " ".join(str(source).split())
        scope = str(scope).strip()
        if not text or not source or not scope:
            raise ValueError("a candidate needs text, a source and a scope")
        if sensitivity not in SENSITIVITIES:
            raise ValueError(f"sensitivity is one of {SENSITIVITIES}")
        now = self.clock()
        with self._db:
            cur = self._db.execute(
                "INSERT INTO facts (text, source, scope, status, sensitivity, "
                "added, last_verified, valid_until, valid_from, superseded_by) "
                "VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                (text, source, scope, "candidate", sensitivity, now, now,
                 valid_until, now if valid_from is None else valid_from),
            )  # fmt: skip
            self._db.execute(
                "INSERT INTO facts_fts(rowid, text) VALUES (?,?)", (cur.lastrowid, text)
            )
        return self.get(cur.lastrowid)

    #: Two incoming texts this similar (word Jaccard) are the same fact, so the
    #: second is not added again. High on purpose: only near-identical wording
    #: is a duplicate; a changed value is a new candidate for the owner to judge.
    DUP_THRESHOLD = 0.85

    def ingest(
        self,
        texts,
        *,
        source: str,
        scope: str,
        sensitivity: str = "normal",
    ) -> list[tuple[str, int]]:
        """Connector ingestion (Mem0's two-phase extract-then-reconcile, made
        owner-safe): each text that is not already present is added as a
        CANDIDATE; a near-duplicate of an existing fact or candidate in the
        scope is skipped (noop). Unlike Mem0, ingestion never updates or
        deletes an existing fact -- that stays the owner's decision (review,
        supersede, retire). Returns (action, fid) per input: 'added' with the
        new fid, 'duplicate' with the existing fid, or 'skipped' with 0."""

        existing = [
            f for f in self.list(scope=scope) if f.status != "retired"
        ]  # dedup against live candidates and facts, not retired history
        results: list[tuple[str, int]] = []
        for text in texts:
            norm = " ".join(str(text).split())
            words = _words(norm)
            if not norm or not words:
                results.append(("skipped", 0))
                continue
            match = max(
                existing,
                key=lambda f: _jaccard(words, _words(f.text)),
                default=None,
            )
            if match and _jaccard(words, _words(match.text)) >= self.DUP_THRESHOLD:
                results.append(("duplicate", match.fid))
                continue
            try:
                f = self.add_candidate(
                    norm, source=source, scope=scope, sensitivity=sensitivity
                )
            except ValueError:
                results.append(("skipped", 0))
                continue
            existing.append(f)  # later inputs dedup against it too
            results.append(("added", f.fid))
        return results

    def supersede(self, old_fid: int, by_fid: int) -> Fact | None:
        """A newer fact replaces an older one (Graphiti's invalidate, never
        delete): the old is marked superseded with a pointer to its successor,
        keeping its validity window and source as history. recall skips it."""

        if self.get(by_fid) is None:
            raise ValueError("the replacing fact does not exist")
        with self._db:
            self._db.execute(
                "UPDATE facts SET status='superseded', superseded_by=?, "
                "last_verified=? WHERE fid=?",
                (by_fid, self.clock(), old_fid),
            )
        return self.get(old_fid)

    # --- owner governance -----------------------------------------------

    def _set_status(self, fid: int, status: str) -> Fact | None:
        with self._db:
            self._db.execute(
                "UPDATE facts SET status=?, last_verified=? WHERE fid=?",
                (status, self.clock(), fid),
            )
        return self.get(fid)

    def review(self, fid: int) -> Fact | None:
        """An owner accepts a candidate as a fact (candidate -> reviewed)."""
        return self._set_status(fid, "reviewed")

    def approve(self, fid: int) -> Fact | None:
        """An owner blesses a fact as reusable (-> approved)."""
        return self._set_status(fid, "approved")

    def retire(self, fid: int) -> Fact | None:
        """Remove a fact from use; kept only as superseded history."""
        return self._set_status(fid, "retired")

    def verify(self, fid: int) -> Fact | None:
        """Mark a fact re-checked now (freshness)."""
        with self._db:
            self._db.execute(
                "UPDATE facts SET last_verified=? WHERE fid=?", (self.clock(), fid)
            )
        return self.get(fid)

    # --- reads ----------------------------------------------------------

    def get(self, fid: int) -> Fact | None:
        row = self._db.execute("SELECT * FROM facts WHERE fid=?", (fid,)).fetchone()
        return Fact(*row) if row else None

    def list(
        self, *, scope: str | None = None, status: str | None = None
    ) -> list[Fact]:
        sql, args = "SELECT * FROM facts", []
        where = []
        if scope is not None:
            where.append("scope=?")
            args.append(scope)
        if status is not None:
            where.append("status=?")
            args.append(status)
        if where:
            sql += " WHERE " + " AND ".join(where)
        return [Fact(*r) for r in self._db.execute(sql + " ORDER BY fid", args)]

    def recall(self, query: str, scope: str, *, k: int = 5) -> list[Fact]:
        """Usable facts for ``scope`` matching ``query``, ranked by BM25
        relevance (FTS5, Porter-stemmed), best first. Candidates and retired
        facts are never returned; stale (past validity) facts are excluded."""

        match = _fts_query(query)
        if match is None:
            return []
        now = self.clock()
        rows = self._db.execute(
            "SELECT f.* FROM facts f JOIN facts_fts x ON x.rowid = f.fid "
            "WHERE f.scope = ? AND facts_fts MATCH ? ORDER BY bm25(facts_fts)",
            (scope, match),
        )
        out = []
        for row in rows:
            f = Fact(*row)
            if f.status in USABLE and not f.stale(now):
                out.append(f)
            if len(out) >= k:
                break
        return out

    def conflicts(self, scope: str) -> list[tuple[Fact, Fact]]:
        """Pairs of usable facts in ``scope`` that look like they disagree:
        strong word overlap but one negates (no/not/never) and the other does
        not. Surfaced for an owner, never auto-resolved."""

        import re

        usable = [f for f in self.list(scope=scope) if f.status in USABLE]
        neg = re.compile(r"\b(no|not|never|cannot|can't|don't|isn't|aren't)\b", re.I)
        out = []
        for i, a in enumerate(usable):
            for b in usable[i + 1 :]:
                wa, wb = _words(a.text), _words(b.text)
                overlap = len(wa & wb) / max(1, min(len(wa), len(wb)))
                if overlap >= 0.6 and bool(neg.search(a.text)) != bool(
                    neg.search(b.text)
                ):
                    out.append((a, b))
        return out

    # --- Context Graph: entities and relationships ----------------------

    def relate(
        self, subject: str, predicate: str, obj: str, *, source: str, scope: str
    ) -> Edge:
        """Add a candidate relationship (subject --predicate--> object) with
        provenance. Like a fact, it is a candidate until an owner reviews it."""

        parts = [" ".join(str(x).split()) for x in (subject, predicate, obj, source)]
        if not all(parts) or not str(scope).strip():
            raise ValueError("an edge needs subject, predicate, object, source, scope")
        with self._db:
            cur = self._db.execute(
                "INSERT INTO edges (subject, predicate, object, source, scope, "
                "status, added) VALUES (?,?,?,?,?,?,?)",
                (
                    parts[0],
                    parts[1],
                    parts[2],
                    parts[3],
                    scope.strip(),
                    "candidate",
                    self.clock(),
                ),
            )
        return self.edge(cur.lastrowid)

    def edge(self, eid: int) -> Edge | None:
        row = self._db.execute("SELECT * FROM edges WHERE eid=?", (eid,)).fetchone()
        return Edge(*row) if row else None

    def review_edge(self, eid: int) -> Edge | None:
        with self._db:
            self._db.execute("UPDATE edges SET status='reviewed' WHERE eid=?", (eid,))
        return self.edge(eid)

    def neighbors(self, entity: str, scope: str) -> list[Edge]:
        """Reviewed edges in ``scope`` touching ``entity`` (as subject or
        object), for retrieval that follows connected entities, not just word
        overlap. Case-insensitive; candidate edges are never returned."""

        key = " ".join(str(entity).split()).casefold()
        rows = self._db.execute(
            "SELECT * FROM edges WHERE scope=? AND status='reviewed' ORDER BY eid",
            (scope,),
        )
        edges = [Edge(*r) for r in rows]
        return [e for e in edges if key in (e.subject.casefold(), e.object.casefold())]

    def related(self, query: str, scope: str, *, k: int = 5) -> list[Edge]:
        """Reviewed edges in ``scope`` whose subject or object shares a word
        with ``query``, best overlap first -- the query-driven counterpart to
        ``neighbors`` (which needs an exact entity)."""

        want = _words(query)
        if not want:
            return []
        rows = self._db.execute(
            "SELECT * FROM edges WHERE scope=? AND status='reviewed' ORDER BY eid",
            (scope,),
        )
        scored = []
        for r in rows:
            e = Edge(*r)
            overlap = len(want & (_words(e.subject) | _words(e.object)))
            if overlap:
                scored.append((overlap, e))
        scored.sort(key=lambda s: -s[0])
        return [e for _o, e in scored[:k]]

    def context(
        self, query: str, scope: str, *, k: int = 5
    ) -> tuple[list[Fact], list[Edge]]:
        """Curated org facts and relations for ``query`` in ``scope``, for a
        caller that wants both at once (plan/research retrieval). Each carries
        its own provenance; usable-state and scope rules already apply."""

        return self.recall(query, scope, k=k), self.related(query, scope, k=k)
