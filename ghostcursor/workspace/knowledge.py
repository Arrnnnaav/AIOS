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
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

# Fact and source-document text is sealed to this Windows account (DPAPI),
# as the Personal Brain is: a copied knowledge.sqlite shows no fact.
# Relations (edges) stay plain: their merge compares text in SQL.
from ghostcursor.workspace.brain import LOCKED, SEALED, _seal, _unseal

from ghostcursor import redact

ENV_PATH = "ORBYN_KNOWLEDGE_PATH"
# superseded: replaced by a newer fact, kept as history (Graphiti/Zep's
# "invalidate, never delete"). retired: removed by an owner.
STATES = ("candidate", "reviewed", "approved", "superseded", "retired")
USABLE = ("reviewed", "approved")  # what retrieval may return as a fact
SENSITIVITIES = ("normal", "sensitive")
#: A usable fact not re-verified within this window is AGING: still valid, so
#: still recalled, but surfaced for a re-verify nudge (Zep's confidence decay).
#: ponytail: one global window; a per-fact TTL only if owners ask.
STALE_AFTER_S = 90 * 24 * 3600
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
    valid_from REAL NOT NULL DEFAULT 0, superseded_by INTEGER,
    episode_id INTEGER
);
-- The raw input a fact was extracted from (Graphiti's "episode": a non-lossy
-- record so a fact traces back to the document/message it came from, not just a
-- source string). D186. Episodes are never model-recalled; they are provenance
-- the owner can open.
CREATE TABLE IF NOT EXISTS episodes (
    eid INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL, source TEXT NOT NULL, scope TEXT NOT NULL,
    added REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS edges (
    eid INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL, predicate TEXT NOT NULL, object TEXT NOT NULL,
    source TEXT NOT NULL, scope TEXT NOT NULL, status TEXT NOT NULL,
    added REAL NOT NULL, valid_until REAL,
    sensitivity TEXT NOT NULL DEFAULT 'normal'
);
-- The full-text index (facts_fts) lives in memory only, built at open from
-- the unsealed text: an index on disk would hold every word in the clear.
-- Sources whose knowledge is private by default. A fact/edge whose provenance
-- matches one of these patterns enters 'sensitive' without the owner marking
-- it each time -- Orbyn's answer to Microsoft Recall's source-identity capture
-- exclusion (CaptureExclusion_ExcludeBasedOnAppIdTargetPath, D186). Marking,
-- not dropping: a sensitive source still records, it just stays off the model
-- path until the owner opts in.
CREATE TABLE IF NOT EXISTS sensitive_sources (pattern TEXT PRIMARY KEY);
-- Small owner-settable store flags. 'private_by_default'='1' makes every new
-- candidate sensitive at entry (deny-on-unknown) -- Orbyn's port of Recall's
-- EnterpriseContext::CaptureBlockedUnknownSensitivity (D186): max-privacy
-- posture where nothing reaches a model without an explicit unmark.
CREATE TABLE IF NOT EXISTS brain_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- Recall and review filter by scope (and edges by status) on every call.
CREATE INDEX IF NOT EXISTS facts_scope ON facts(scope, status);
CREATE INDEX IF NOT EXISTS edges_scope ON edges(scope, status);
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
    episode_id: int | None = None  # the raw input this fact was extracted from

    def stale(self, now: float) -> bool:
        return self.valid_until is not None and now >= self.valid_until

    def aging(self, now: float, *, max_age: float = STALE_AFTER_S) -> bool:
        """Not expired, but not re-verified within ``max_age`` -- surfaced for a
        re-verify nudge, never excluded (it is still valid)."""

        return not self.stale(now) and (now - self.last_verified) > max_age


@dataclass(frozen=True)
class Episode:
    """The raw input a fact was extracted from -- provenance the owner can open,
    never a model-recalled fact itself (D186)."""

    eid: int
    text: str
    source: str
    scope: str
    added: float


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
    valid_until: float | None = None  # world time end; None = never expires
    sensitivity: str = "normal"  # 'sensitive' edges stay off the model path

    def expired(self, now: float) -> bool:
        """Past its validity -- a relationship that stopped being true (e.g. an
        owner moved teams). Mirrors Fact.stale: excluded from every traversal,
        never deleted (Graphiti-style temporal edge, owner still governs it)."""

        return self.valid_until is not None and now >= self.valid_until


def _secret_free(text: str) -> str:
    """Credentials and card/ID numbers never rest in knowledge.sqlite, whichever path
    wrote them (a pasted clipboard, a typed note, an imported file, a source
    URL with a token). Replaced by a placeholder; the original is not kept."""

    return redact.scrub(text, redact.SECRETS)[0]


def _words(text: str) -> set[str]:
    import re

    return set(re.findall(r"[a-z0-9]{2,}", text.casefold()))


_NEG = re.compile(r"\b(no|not|never|cannot|can't|don't|isn't|aren't)\b", re.I)


def _disagree(a: str, b: str) -> bool:
    """Two fact texts look like they disagree: strong word overlap but exactly
    one negates. A heuristic surfaced for the owner, never an auto-resolution."""

    wa, wb = _words(a), _words(b)
    overlap = len(wa & wb) / max(1, min(len(wa), len(wb)))
    return overlap >= 0.6 and bool(_NEG.search(a)) != bool(_NEG.search(b))


#: A document chunks into at most this many facts, each at most this long, so
#: one big file cannot flood the Brain with thousands of candidates.
MAX_CHUNKS = 200
MAX_CHUNK_CHARS = 600


def chunk_document(text: str) -> list[str]:
    """Split a document into candidate-sized chunks on blank lines (the simple
    loader Mem0/Cognee use before extraction). Whitespace is collapsed, empties,
    lone Markdown headings and single-word fragments are dropped, each chunk is
    capped, and the count is bounded."""

    import re

    chunks = []
    for block in re.split(r"\n\s*\n", text or ""):
        if re.fullmatch(r"\s*#{1,6}\s[^\n]*\s*", block):
            continue  # a heading on its own is a title, not a fact
        chunk = " ".join(block.split())
        if len(chunk.split()) >= 2:  # a lone word is not a fact
            chunks.append(chunk[:MAX_CHUNK_CHARS])
        if len(chunks) >= MAX_CHUNKS:
            break
    return chunks


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


def _fact(row) -> Fact:
    """A row with its text unsealed (LOCKED when this account cannot)."""

    return Fact(row[0], _unseal(row[1]), *row[2:])


class Knowledge:
    """The Company Brain store. Owner-governed: adding makes a *candidate*;
    only an explicit review/approve makes a fact retrievable."""

    def __init__(self, path: Path | None = None, *, clock=time.time):
        self.path = path or _default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        # Shared across threads (the GUI reviews facts from HTTP handler
        # threads, not just the worker). Writes are serialized by _lock; reads
        # are short, materialized selects that sqlite handles concurrently.
        # ponytail: one RLock, writes only -- fine for a local single user;
        # guard reads too if contention ever shows.
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute("PRAGMA secure_delete = ON")  # retire overwrites on disk
        # The search index (temp.facts_fts) holds every fact in plain words;
        # SQLite would spill a large temp database to a file in %TEMP%
        # (review 15 Nov). Keep it in memory, always.
        self._db.execute("PRAGMA temp_store = MEMORY")
        self._db.executescript(_SCHEMA)
        # Migrate a pre-temporal-edge DB: add the edge validity column if absent.
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(edges)")}
        if "valid_until" not in cols:
            self._db.execute("ALTER TABLE edges ADD COLUMN valid_until REAL")
        if "sensitivity" not in cols:
            self._db.execute(
                "ALTER TABLE edges ADD COLUMN sensitivity TEXT NOT NULL DEFAULT 'normal'"
            )
        fact_cols = {r[1] for r in self._db.execute("PRAGMA table_info(facts)")}
        if "episode_id" not in fact_cols:  # pre-episode DB: add the provenance link
            self._db.execute("ALTER TABLE facts ADD COLUMN episode_id INTEGER")
        with self._lock, self._db:
            # An older build kept the index on disk, in plain words: drop it
            # (secure_delete overwrites its pages) and seal the plain rows.
            self._db.execute("DROP TABLE IF EXISTS main.facts_fts")
            for table, key in (("facts", "fid"), ("episodes", "eid")):
                for rid, text in self._db.execute(
                    f"SELECT {key}, text FROM {table} WHERE substr(text, 1, 4) != ?",
                    (SEALED,),
                ).fetchall():
                    try:
                        sealed = _seal(text)
                    except Exception:  # cannot seal now; next open tries again
                        break
                    self._db.execute(
                        f"UPDATE {table} SET text=? WHERE {key}=?", (sealed, rid)
                    )
        # ponytail: the index is rebuilt at every open, one unseal per fact;
        # fine for thousands of facts, a sealed on-disk index if it grows.
        self._db.execute(
            "CREATE VIRTUAL TABLE temp.facts_fts USING fts5(text, tokenize='porter unicode61')"
        )
        with self._lock, self._db:
            self._db.executemany(
                "INSERT INTO temp.facts_fts(rowid, text) VALUES (?,?)",
                [
                    (fid, _unseal(text))
                    for fid, text in self._db.execute("SELECT fid, text FROM facts")
                ],
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
        episode_id: int | None = None,
    ) -> Fact:
        """Record an untrusted candidate. It is NOT a usable fact until an
        owner reviews it. ``source`` is required provenance; empty is refused.
        ``episode_id`` links it to the raw input it was extracted from."""

        text = _secret_free(" ".join(str(text).split()))
        source = _secret_free(" ".join(str(source).split()))
        scope = str(scope).strip()
        if not text or not source or not scope:
            raise ValueError("a candidate needs text, a source and a scope")
        if sensitivity not in SENSITIVITIES:
            raise ValueError(f"sensitivity is one of {SENSITIVITIES}")
        sensitivity = self._resolve_sensitivity(source, sensitivity)
        now = self.clock()
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO facts (text, source, scope, status, sensitivity, "
                "added, last_verified, valid_until, valid_from, superseded_by, "
                "episode_id) VALUES (?,?,?,?,?,?,?,?,?,NULL,?)",
                (_seal(text), source, scope, "candidate", sensitivity, now, now,
                 valid_until, now if valid_from is None else valid_from, episode_id),
            )  # fmt: skip
            self._db.execute(
                "INSERT INTO temp.facts_fts(rowid, text) VALUES (?,?)",
                (cur.lastrowid, text),
            )
        return self.get(cur.lastrowid)

    def record_episode(self, text: str, *, source: str, scope: str) -> int:
        """Store a raw input (a document, message, meeting note) and return its
        eid, so facts extracted from it can link back to it. Never recalled to a
        model -- it is provenance the owner can open."""

        text = _secret_free(str(text).strip())
        source, scope = _secret_free(" ".join(str(source).split())), str(scope).strip()
        if not text or not source or not scope:
            raise ValueError("an episode needs text, a source and a scope")
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO episodes (text, source, scope, added) VALUES (?,?,?,?)",
                (_seal(text), source, scope, self.clock()),
            )
        return cur.lastrowid

    def episode(self, eid: int) -> Episode | None:
        row = self._db.execute("SELECT * FROM episodes WHERE eid=?", (eid,)).fetchone()
        return Episode(row[0], _unseal(row[1]), *row[2:]) if row else None

    def episode_of(self, fid: int) -> Episode | None:
        """The raw input a fact was extracted from, or None (older facts, or a
        fact added without an episode)."""

        fact = self.get(fid)
        if fact is None or fact.episode_id is None:
            return None
        return self.episode(fact.episode_id)

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
        episode: str | None = None,
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
        # Record the raw input once; every fact added from it links back (D186).
        episode_id = (
            self.record_episode(episode, source=source, scope=scope)
            if episode and str(episode).strip()
            else None
        )
        results: list[tuple[str, int]] = []
        for text in texts:
            norm = _secret_free(" ".join(str(text).split()))  # dedup on what is stored
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
                self.tighten(match.fid, source, sensitivity)
                results.append(("duplicate", match.fid))
                continue
            try:
                f = self.add_candidate(
                    norm, source=source, scope=scope, sensitivity=sensitivity,
                    episode_id=episode_id,
                )  # fmt: skip
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
        with self._lock, self._db:
            self._db.execute(
                "UPDATE facts SET status='superseded', superseded_by=?, "
                "last_verified=? WHERE fid=?",
                (by_fid, self.clock(), old_fid),
            )
        return self.get(old_fid)

    # --- owner governance -----------------------------------------------

    def _set_status(self, fid: int, status: str) -> Fact | None:
        old = self.get(fid)
        if old is not None and old.status == "superseded" and status != "retired":
            # Bringing it back would let recall return it beside its successor.
            raise ValueError("this fact was replaced; review or approve the newer one")
        with self._lock, self._db:
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
        with self._lock, self._db:
            self._db.execute(
                "UPDATE facts SET last_verified=? WHERE fid=?", (self.clock(), fid)
            )
        return self.get(fid)

    def expire(self, fid: int, when: float | None = None) -> Fact | None:
        """Set a fact's world-time end (the owner learned it stopped being true
        at ``when``, default now). It stays as history with its validity window;
        recall skips it once past ``when`` -- Graphiti temporal invalidation,
        not a delete. Unlike retire (an immediate drop), this keeps the fact
        valid for the window before ``when``."""

        now = self.clock()
        with self._lock, self._db:
            self._db.execute(
                "UPDATE facts SET valid_until=?, last_verified=? WHERE fid=?",
                (now if when is None else when, now, fid),
            )
        return self.get(fid)

    def expire_edge(self, eid: int, when: float | None = None) -> Edge | None:
        """Set a relationship's world-time end (default now); traversal skips it
        past ``when``. The counterpart to ``expire`` for the context graph."""

        with self._lock, self._db:
            self._db.execute(
                "UPDATE edges SET valid_until=? WHERE eid=?",
                (self.clock() if when is None else when, eid),
            )
        return self.edge(eid)

    def classify(self, fid: int, sensitivity: str) -> Fact | None:
        """Owner marks a fact sensitive/normal; sensitive keeps it off the
        model path (recall/connections) -- the only way to set the flag after
        the fact exists."""

        if sensitivity not in SENSITIVITIES:
            raise ValueError(f"sensitivity is one of {SENSITIVITIES}")
        if self.get(fid) is None:  # no row: no-op is a None signal, not a silent miss
            return None
        with self._lock, self._db:
            self._db.execute(
                "UPDATE facts SET sensitivity=? WHERE fid=?", (sensitivity, fid)
            )
        return self.get(fid)

    def classify_edge(self, eid: int, sensitivity: str) -> Edge | None:
        """Owner marks a relationship sensitive/normal; the edge counterpart of
        ``classify``."""

        if sensitivity not in SENSITIVITIES:
            raise ValueError(f"sensitivity is one of {SENSITIVITIES}")
        if self.edge(eid) is None:  # no row: no-op is a None signal, not a silent miss
            return None
        with self._lock, self._db:
            self._db.execute(
                "UPDATE edges SET sensitivity=? WHERE eid=?", (sensitivity, eid)
            )
        return self.edge(eid)

    # --- source-scoped sensitivity (private-by-default sources) ---------

    def mark_source_sensitive(self, pattern: str) -> None:
        """Register a source whose knowledge is private by default: any later
        candidate whose ``source`` contains ``pattern`` (case-insensitive)
        enters 'sensitive', so the owner need not mark each one. Ported from
        Recall's source-identity capture exclusion (D186)."""

        pattern = " ".join(str(pattern).split())
        if not pattern:
            raise ValueError("a sensitive-source pattern cannot be empty")
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO sensitive_sources (pattern) VALUES (?)",
                (pattern,),
            )

    def unmark_source_sensitive(self, pattern: str) -> bool:
        """Drop a sensitive-source pattern. Returns whether one was removed.
        Existing facts/edges keep whatever sensitivity they were given."""

        pattern = " ".join(str(pattern).split())
        with self._lock, self._db:
            cur = self._db.execute(
                "DELETE FROM sensitive_sources WHERE pattern=?", (pattern,)
            )
        return cur.rowcount > 0

    def sensitive_sources(self) -> list[str]:
        return [
            r[0]
            for r in self._db.execute(
                "SELECT pattern FROM sensitive_sources ORDER BY pattern"
            )
        ]

    def set_private_by_default(self, on: bool) -> None:
        """Owner posture: when on, every new candidate enters 'sensitive' (deny-
        on-unknown). Ported from Recall's CaptureBlockedUnknownSensitivity
        (D186) -- nothing reaches a model without an explicit unmark."""

        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO brain_meta (key, value) VALUES ('private_by_default', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("1" if on else "0",),
            )

    def private_by_default(self) -> bool:
        row = self._db.execute(
            "SELECT value FROM brain_meta WHERE key='private_by_default'"
        ).fetchone()
        return row is not None and row[0] == "1"

    def tighten(self, fid: int, source: str, requested: str = "normal") -> None:
        """A fact met again as a duplicate: if this arrival would have been
        sensitive (asked for, a private source, private by default), the
        existing fact becomes sensitive. Never loosens (rule 6)."""

        source = _secret_free(" ".join(str(source).split()))
        if self._resolve_sensitivity(source, requested) == "sensitive":
            self.classify(fid, "sensitive")

    def _resolve_sensitivity(self, source: str, requested: str) -> str:
        """Entry-time gate: an explicit 'sensitive' stays sensitive; otherwise a
        'normal' is lifted to 'sensitive' when the owner is private-by-default
        or the source matches a registered private source. Only ever tightens,
        never loosens -- matches rule 6."""

        if requested == "sensitive":
            return requested
        if self.private_by_default():
            return "sensitive"
        low = source.lower()
        for pat in self.sensitive_sources():
            if pat.lower() in low:
                return "sensitive"
        return requested

    # --- reads ----------------------------------------------------------

    def get(self, fid: int) -> Fact | None:
        row = self._db.execute("SELECT * FROM facts WHERE fid=?", (fid,)).fetchone()
        return _fact(row) if row else None

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
        return [_fact(r) for r in self._db.execute(sql + " ORDER BY fid", args)]

    def recall(
        self,
        query: str,
        scope: str,
        *,
        k: int = 5,
        include_sensitive: bool = False,
        since: float | None = None,
    ) -> list[Fact]:
        """Usable facts for ``scope`` matching ``query``, ranked by BM25
        relevance (FTS5, Porter-stemmed), best first. Candidates and retired
        facts are never returned; stale (past validity) facts are excluded.

        ``since`` (system time) keeps only facts Orbyn learned at or after it --
        time-scoped recall ("what did I learn last week"), the privacy-safe
        answer to always-on-capture rivals that time-travel over a screen log.

        Sensitive facts are excluded by default: this is the model-bound
        retrieval path, and sending a sensitive fact to a BYOK model is egress
        off the device (rule 6), so the owner opts in explicitly (as export
        does). The owner's own local ``/know recall`` passes True."""

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
            f = _fact(row)
            if (
                f.status in USABLE
                and f.text != LOCKED
                and not f.stale(now)
                and (include_sensitive or f.sensitivity != "sensitive")
                and (since is None or f.added >= since)
            ):
                out.append(f)
            if len(out) >= k:
                break
        return out

    def conflicts_among(self, facts: list[Fact]) -> list[tuple[Fact, Fact]]:
        """Pairs within ``facts`` that look like they disagree: strong word
        overlap but one negates (no/not/never) and the other does not. The
        retrieval path passes just the surfaced facts (cheap); ``conflicts``
        passes a whole scope. Surfaced for an owner, never auto-resolved."""

        out = []
        for i, a in enumerate(facts):
            for b in facts[i + 1 :]:
                if _disagree(a.text, b.text):
                    out.append((a, b))
        return out

    def aging_among(self, facts: list[Fact]) -> list[Fact]:
        """Usable facts not re-verified within ``STALE_AFTER_S`` -- surfaced so
        the owner can re-verify, never dropped. The retrieval path passes the
        surfaced facts; uses the store's own clock."""

        now = self.clock()
        return [f for f in facts if f.aging(now)]

    def conflicts(self, scope: str) -> list[tuple[Fact, Fact]]:
        """Pairs of usable facts in ``scope`` that look like they disagree.
        Surfaced for an owner, never auto-resolved."""

        return self.conflicts_among(
            [f for f in self.list(scope=scope) if f.status in USABLE]
        )

    def aging(self, scope: str) -> list[Fact]:
        """Usable facts in ``scope`` nobody has re-verified within the window.
        Surfaced so the owner can re-verify; never dropped."""

        return self.aging_among(
            [f for f in self.list(scope=scope) if f.status in USABLE]
        )

    # --- Context Graph: entities and relationships ----------------------

    def relate(
        self,
        subject: str,
        predicate: str,
        obj: str,
        *,
        source: str,
        scope: str,
        valid_until: float | None = None,
        sensitivity: str = "normal",
    ) -> Edge:
        """Add a candidate relationship (subject --predicate--> object) with
        provenance. Like a fact, it is a candidate until an owner reviews it.
        ``valid_until`` (world time) expires it from traversal after that time.
        A ``sensitive`` edge stays off the model path, like a sensitive fact."""

        if sensitivity not in SENSITIVITIES:
            raise ValueError(f"sensitivity is one of {SENSITIVITIES}")
        parts = [
            _secret_free(" ".join(str(x).split()))
            for x in (subject, predicate, obj, source)
        ]
        if not all(parts) or not str(scope).strip():
            raise ValueError("an edge needs subject, predicate, object, source, scope")
        sensitivity = self._resolve_sensitivity(parts[3], sensitivity)
        now = self.clock()
        with self._lock, self._db:
            rows = self._db.execute(
                "SELECT * FROM edges WHERE scope=? AND lower(subject)=? AND "
                "lower(predicate)=? AND lower(object)=? ORDER BY eid",
                (scope.strip(), *(part.lower() for part in parts[:3])),
            ).fetchall()
            for same in (Edge(*row) for row in rows):
                if same.expired(now):
                    continue
                # Already known: no second copy to review. A repeat may
                # only tighten it (rule 6): asked for private, it is.
                if sensitivity == "sensitive" != same.sensitivity:
                    self._db.execute(
                        "UPDATE edges SET sensitivity='sensitive' WHERE eid=?",
                        (same.eid,),
                    )
                    same = Edge(*self._db.execute(
                        "SELECT * FROM edges WHERE eid=?", (same.eid,)
                    ).fetchone())
                return same
            cur = self._db.execute(
                "INSERT INTO edges (subject, predicate, object, source, scope, "
                "status, added, valid_until, sensitivity) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    parts[0],
                    parts[1],
                    parts[2],
                    parts[3],
                    scope.strip(),
                    "candidate",
                    self.clock(),
                    valid_until,
                    sensitivity,
                ),
            )
        return self.edge(cur.lastrowid)

    def edge(self, eid: int) -> Edge | None:
        row = self._db.execute("SELECT * FROM edges WHERE eid=?", (eid,)).fetchone()
        return Edge(*row) if row else None

    def review_edge(self, eid: int) -> Edge | None:
        with self._lock, self._db:
            self._db.execute("UPDATE edges SET status='reviewed' WHERE eid=?", (eid,))
        return self.edge(eid)

    def list_edges(
        self, *, scope: str | None = None, status: str | None = None
    ) -> list[Edge]:
        """All edges (candidate and reviewed) for a review panel -- the edge
        counterpart to ``list``. Unlike the traversal readers it does not hide
        expired edges; the panel shows and tags them."""

        sql, args = "SELECT * FROM edges", []
        where = []
        if scope is not None:
            where.append("scope=?")
            args.append(scope)
        if status is not None:
            where.append("status=?")
            args.append(status)
        if where:
            sql += " WHERE " + " AND ".join(where)
        return [Edge(*r) for r in self._db.execute(sql + " ORDER BY eid", args)]

    # --- offline team sharing (export / import) -------------------------

    def export_scope(
        self, scope: str, *, include_sensitive: bool = False, redact_pii: bool = True
    ) -> dict:
        """A shareable snapshot of ``scope``: usable facts and reviewed edges
        with their provenance, for the owner's "offline files first" sharing.
        Sensitive facts are left out unless asked for, so sharing cannot leak
        them by accident. Candidates and retired/superseded facts are omitted.

        ``redact_pii`` (default on) additionally scrubs embedded secrets (email,
        card, SSN, key, IP, phone, IBAN) out of the free-text content before it
        leaves -- the enterprise "redact before egress" gate, so a *normal* fact
        that happens to quote a credential still cannot leak it. The snapshot
        carries a category-count ``redacted`` audit (never a raw value). Pass
        ``redact_pii=False`` for the owner's own verbatim backup."""

        tally: dict[str, int] = {}

        def _s(value: str) -> str:  # scrub a content field, add to the audit
            if not redact_pii:
                return value
            scrubbed, m = redact.scrub(value)
            for cat, n in redact.audit(m).items():
                tally[cat] = tally.get(cat, 0) + n
            return scrubbed

        facts = [
            {
                "text": _s(f.text),
                "source": _s(f.source),
                "sensitivity": f.sensitivity,
                "valid_from": f.valid_from,
                "valid_until": f.valid_until,
            }
            for f in self.list(scope=scope)
            if f.status in USABLE
            and (include_sensitive or f.sensitivity != "sensitive")
        ]
        rows = self._db.execute(
            "SELECT * FROM edges WHERE scope=? AND status='reviewed' ORDER BY eid",
            (scope,),
        )
        now = self.clock()
        edges = [
            {"subject": _s(e.subject), "predicate": _s(e.predicate),
             "object": _s(e.object), "source": _s(e.source)}
            for e in (Edge(*r) for r in rows)
            if not e.expired(now)
            and (include_sensitive or e.sensitivity != "sensitive")
        ]  # fmt: skip
        return {
            "version": 1, "scope": scope, "facts": facts, "edges": edges,
            "redacted": tally,
        }  # fmt: skip

    def export_markdown(
        self, scope: str, *, include_sensitive: bool = False, redact_pii: bool = True
    ) -> str:
        """``export_scope`` rendered as human-readable Markdown so the owner can
        READ exactly what a shared snapshot contains before sending it -- plain,
        diffable, git-friendly (Obsidian's plain-file portability applied to a
        governed store). Same privacy filter; sensitive excluded unless asked,
        embedded secrets redacted unless ``redact_pii=False``."""

        data = self.export_scope(
            scope, include_sensitive=include_sensitive, redact_pii=redact_pii
        )
        sens = "included" if include_sensitive else "excluded"
        redn = ", ".join(
            f"{n} {c.lower()}" for c, n in sorted(data["redacted"].items())
        )
        lines = [
            f"# Company Brain export: {scope}",
            "",
            f"_{len(data['facts'])} fact(s), {len(data['edges'])} relation(s); "
            f"sensitive {sens}._",
            *([f"_redacted before egress: {redn}._", ""] if redn else [""]),
            "## Facts",
            "",
        ]
        lines += [
            f"- {f['text']}  \n  _source: {f['source']}_" for f in data["facts"]
        ] or ["_(none)_"]
        lines += ["", "## Relations", ""]
        lines += [
            f"- {e['subject']} → {e['predicate']} → {e['object']}  \n  "
            f"_source: {e['source']}_"
            for e in data["edges"]
        ] or ["_(none)_"]
        return "\n".join(lines) + "\n"

    def import_scope(self, data: dict, scope: str) -> dict:
        """Load a snapshot into ``scope`` as CANDIDATES (a teammate's facts are
        untrusted until this owner reviews them, like a received mission).
        Near-duplicates are skipped; relations come in as candidate edges.
        Returns counts; raises ValueError on a snapshot it does not understand."""

        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("not a Company Brain export (version 1)")
        added = dup = edges = 0
        for item in data.get("facts", []):
            if not isinstance(item, dict) or not str(item.get("text", "")).strip():
                continue
            sensitivity = item.get("sensitivity")
            ((action, _fid),) = self.ingest(
                [item["text"]],
                source=f"shared: {item.get('source', 'unknown')}",
                scope=scope,
                sensitivity=sensitivity if sensitivity in SENSITIVITIES else "normal",
            )
            added += action == "added"
            dup += action == "duplicate"
        for e in data.get("edges", []):
            if not isinstance(e, dict):
                continue
            try:
                self.relate(
                    e.get("subject", ""), e.get("predicate", ""), e.get("object", ""),
                    source=f"shared: {e.get('source', 'unknown')}", scope=scope,
                )  # fmt: skip
                edges += 1
            except ValueError:
                continue
        return {"facts_added": added, "facts_duplicate": dup, "edges": edges}

    def neighbors(self, entity: str, scope: str) -> list[Edge]:
        """Reviewed edges in ``scope`` touching ``entity`` (as subject or
        object), for retrieval that follows connected entities, not just word
        overlap. Case-insensitive; candidate edges are never returned."""

        key = " ".join(str(entity).split()).casefold()
        rows = self._db.execute(
            "SELECT * FROM edges WHERE scope=? AND status='reviewed' ORDER BY eid",
            (scope,),
        )
        now = self.clock()
        edges = [Edge(*r) for r in rows]
        return [
            e
            for e in edges
            if key in (e.subject.casefold(), e.object.casefold())
            and not e.expired(now)
            and e.sensitivity != "sensitive"  # a sensitive edge stays off this path
        ]

    def related(self, query: str, scope: str, *, k: int = 5) -> list[Edge]:
        """Reviewed edges in ``scope`` whose subject or object shares a word
        with ``query``, best overlap first -- the query-driven counterpart to
        ``neighbors`` (which needs an exact entity)."""

        want = _words(query)
        if not want:
            return []
        now = self.clock()
        rows = self._db.execute(
            "SELECT * FROM edges WHERE scope=? AND status='reviewed' ORDER BY eid",
            (scope,),
        )
        scored = []
        for r in rows:
            e = Edge(*r)
            if e.expired(now) or e.sensitivity == "sensitive":
                continue
            overlap = len(want & (_words(e.subject) | _words(e.object)))
            if overlap:
                scored.append((overlap, e))
        scored.sort(key=lambda s: -s[0])
        return [e for _o, e in scored[:k]]

    def connections(
        self, query: str, scope: str, *, k: int = 5
    ) -> list[tuple[Fact, str]]:
        """``connected`` facts paired with the entity that bridged them in
        (Graphiti-style explainability): a plan can then say a fact surfaced
        because it links to <entity>, not because the query named it. Bounded
        to <=k; reviewed edges and usable facts only; same scope."""

        seeds = self.recall(query, scope, k=k)
        if not seeds:
            return []
        seen = {f.fid for f in seeds}
        now = self.clock()
        seed_words: set[str] = set()
        for f in seeds:
            seed_words |= _words(f.text)
        rows = self._db.execute(
            "SELECT * FROM edges WHERE scope=? AND status='reviewed' ORDER BY eid",
            (scope,),
        )
        frontier: list[str] = []
        for r in rows:
            e = Edge(*r)
            if e.expired(now) or e.sensitivity == "sensitive":  # off the model path
                continue
            subj, obj = _words(e.subject), _words(e.object)
            if subj and subj <= seed_words:  # subject named in a seed -> walk to object
                frontier.append(e.object)
            if obj and obj <= seed_words:  # object named in a seed -> walk to subject
                frontier.append(e.subject)
        out: list[tuple[Fact, str]] = []
        for entity in frontier:
            for f in self.recall(entity, scope, k=k):
                if f.fid not in seen:
                    seen.add(f.fid)
                    out.append((f, entity))
                    if len(out) >= k:
                        return out
        return out

    def connected(self, query: str, scope: str, *, k: int = 5) -> list[Fact]:
        """Facts one hop out from the top recall hits over reviewed edges
        (Graphiti/Zep n-hop), without the bridge. See ``connections``."""

        return [f for f, _bridge in self.connections(query, scope, k=k)]

    def context(
        self, query: str, scope: str, *, k: int = 5
    ) -> tuple[list[Fact], list[Edge]]:
        """Curated org facts and relations for ``query`` in ``scope``, for a
        caller that wants both at once (plan/research retrieval). Each carries
        its own provenance; usable-state and scope rules already apply. Direct
        BM25 hits come first, then n-hop ``connected`` facts the query words
        never named -- so a token-trimming caller keeps the direct matches."""

        facts = self.recall(query, scope, k=k)
        seen = {f.fid for f in facts}
        facts += [f for f in self.connected(query, scope, k=k) if f.fid not in seen]
        return facts, self.related(query, scope, k=k)
