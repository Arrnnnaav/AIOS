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
STATES = ("candidate", "reviewed", "approved", "retired")
USABLE = ("reviewed", "approved")  # what retrieval may return as a fact
SENSITIVITIES = ("normal", "sensitive")


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
    added REAL NOT NULL, last_verified REAL NOT NULL, valid_until REAL
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
    added: float
    last_verified: float
    valid_until: float | None  # None = no expiry

    def stale(self, now: float) -> bool:
        return self.valid_until is not None and now >= self.valid_until


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
                "added, last_verified, valid_until) VALUES (?,?,?,?,?,?,?,?)",
                (text, source, scope, "candidate", sensitivity, now, now, valid_until),
            )
        return self.get(cur.lastrowid)

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
