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
        return self.get(cur.lastrowid)

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
        """Usable facts for ``scope`` matching ``query`` by word overlap, best
        first, freshest-verified as the tiebreak. Candidates and retired facts
        are never returned; stale (past validity) facts are excluded."""

        want = _words(query)
        now = self.clock()
        scored = []
        for f in self.list(scope=scope):
            if f.status not in USABLE or f.stale(now):
                continue
            overlap = len(want & _words(f.text))
            if overlap:
                scored.append((overlap, f.last_verified, f))
        scored.sort(key=lambda s: (-s[0], -s[1]))
        return [f for _o, _v, f in scored[:k]]

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
                (parts[0], parts[1], parts[2], parts[3], scope.strip(), "candidate", self.clock()),
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
