"""Personal Brain v1 (MVP.md "Personal Brain v1 rules").

Learns without per-item prompts, but a deterministic rule -- not the model --
decides what becomes durable. Durable: a preference, goal, decision, recurring
fact or procedure the USER stated (its words are in the user's own turn), that
is not temporary, not sensitive, and confident enough. Everything else is
session-scoped and expires. An explicit user correction always wins.

Stored only at %LOCALAPPDATA%\\GhostCursor\\brain.sqlite (``ORBYN_BRAIN_PATH``
overrides). Never synced, never sent anywhere except as minimized, tainted
context of a request the user started. Separate from kb.sqlite (screen
observations) and sessions.sqlite (no goal text there).
"""

from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from ghostcursor import redact

ENV_PATH = "ORBYN_BRAIN_PATH"
CLASSES = ("preference", "goal", "decision", "fact", "procedure")
ORIGINS = ("user_stated", "model_inferred", "verified_workflow", "user_corrected")
#: Session-scoped memories expire after this long.
SESSION_TTL_S = 24 * 3600
#: Model confidence below this never becomes durable.
MIN_CONFIDENCE = 0.7
#: Share of a memory's content words that must appear in the user's turn.
MIN_SUPPORT = 0.6
MAX_TEXT = 300

_SENSITIVE = re.compile(
    r"(password|passcode|passphrase|\blog-?ins?\b|pin code|api[ _-]?key|secret|token|credential|"
    r"\bssn\b|social security|credit card|\bcvv\b|\bpins?\b|\bpwd?\b|"
    r"sk-[a-z0-9]|nvapi-|ghp_|\b\d{6,}\b)",
    re.IGNORECASE,
)
_TEMPORARY = re.compile(
    r"\b(for now|this time|for today|just today|today only|temporarily|right now|"
    r"for this (session|task)|just this once)\b",
    re.IGNORECASE,
)
_STOP = set(
    "i me my we our you your the a an of to in on for and or is are was were be "
    "this that it its as by with from at always never usually prefer like want".split()
)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']{2,}", text.lower()) if w not in _STOP}


@dataclass(frozen=True)
class PersonalMemory:
    mid: int | None
    kind: str  # one of CLASSES
    text: str
    origin: str  # one of ORIGINS
    confidence: float
    scope: str  # "durable" | "session"
    status: str  # "active" | "superseded"
    created: float
    expires: float | None  # None for durable
    source: str  # where it came from, e.g. "user turn 2026-10-12T..."; no screen text


def _supported(text: str, user_turn: str) -> bool:
    """Most of the memory's content words are in the user's own turn."""

    words = _words(text)
    return bool(words) and len(words & _words(user_turn)) / len(words) >= MIN_SUPPORT


def _unsafe(text: str) -> bool:
    """Never stored, never handed to the model: a credential by name, or a
    card, bank or ID number, a key or a token, however spaced."""

    return bool(_SENSITIVE.search(text)) or (
        redact.scrub(text, redact.SECRETS)[0] != text
    )


def eligibility(
    kind: str, text: str, origin: str, confidence: float, user_turn: str
) -> str:
    """'durable', 'session', or 'refused' -- the whole promotion rule."""

    if kind not in CLASSES or origin not in ORIGINS or not text.strip():
        return "refused"
    if _unsafe(text) or len(text) > MAX_TEXT or text == LOCKED:
        return "refused"
    if origin == "user_corrected":
        return "durable"
    if _TEMPORARY.search(text) or _TEMPORARY.search(user_turn):
        return "session"
    supported = _supported(text, user_turn)
    if (
        origin in ("user_stated", "verified_workflow")
        and supported
        and confidence >= MIN_CONFIDENCE
    ):
        return "durable"
    return "session"


#: A memory's text is stored sealed with Windows DPAPI: only this Windows
#: account on this computer can read it back, so a copied brain.sqlite (a
#: backup, a synced folder, another account) shows nothing.
SEALED = "dp1:"
LOCKED = "(locked: saved under another Windows account or computer)"


def _seal(text: str) -> str:
    import win32crypt

    blob = win32crypt.CryptProtectData(
        text.encode("utf-8"), "Orbyn memory", None, None, None, 0
    )
    return SEALED + base64.b64encode(blob).decode("ascii")


def _unseal(stored: str) -> str:
    if not stored.startswith(SEALED):
        return stored  # written before sealing; sealed when the Brain next opens
    try:
        import win32crypt

        blob = base64.b64decode(stored[len(SEALED) :])
        return win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1].decode(
            "utf-8"
        )
    except Exception:  # another account's, another computer's, or damaged
        return LOCKED


def _default_path() -> Path:
    if os.environ.get(ENV_PATH):
        return Path(os.environ[ENV_PATH])
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "GhostCursor" / "brain.sqlite"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    mid INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL, text TEXT NOT NULL, origin TEXT NOT NULL,
    confidence REAL NOT NULL, scope TEXT NOT NULL, status TEXT NOT NULL,
    created REAL NOT NULL, expires REAL, source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Brain:
    def __init__(self, path: Path | None = None, *, clock=time.time):
        self.path = path or _default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self._db = sqlite3.connect(self.path)
        # A forgotten or erased memory is overwritten on disk, not left in a
        # free page where a file-level read could still recover it.
        self._db.execute("PRAGMA secure_delete = ON")
        self._db.execute("PRAGMA temp_store = MEMORY")  # VACUUM's copy never in %TEMP%
        self._db.executescript(_SCHEMA)
        with self._db:  # seal what an older build stored as plain text
            for mid, text in self._db.execute(
                "SELECT mid, text FROM memories WHERE substr(text, 1, 4) != ?", (SEALED,)
            ).fetchall():
                try:
                    sealed = _seal(text)
                except Exception:
                    # Windows could not seal now (profile not loaded, a
                    # service account): the Brain still opens, the row
                    # stays readable, and the next open tries again.
                    break
                self._db.execute(
                    "UPDATE memories SET text=? WHERE mid=?", (sealed, mid)
                )

    def close(self) -> None:
        self._db.close()

    # --- learning ------------------------------------------------------------

    @property
    def paused(self) -> bool:
        row = self._db.execute("SELECT value FROM meta WHERE key='paused'").fetchone()
        return bool(row and row[0] == "1")

    def pause(self, paused: bool = True) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO meta VALUES ('paused', ?)",
                ("1" if paused else "0",),
            )

    def remember(
        self,
        kind: str,
        text: str,
        *,
        origin: str,
        confidence: float,
        user_turn: str = "",
        source: str = "",
    ) -> PersonalMemory | None:
        """Store a candidate under the promotion rule; None if paused or refused."""

        if self.paused:
            return None
        text = " ".join(text.split())
        scope = eligibility(kind, text, origin, confidence, user_turn)
        if scope == "refused":
            return None
        if origin == "user_stated" and not _supported(text, user_turn):
            origin = "model_inferred"  # the panel says honestly where it came from
        for old in self.list():  # restated each turn: keep one, unless now durable
            same = old.kind == kind and old.text.casefold() == text.casefold()
            if same and (old.scope == "durable" or scope != "durable"):
                return old
        with self._db:
            mid = self._insert(kind, text, origin, confidence, scope, source)
        return self.get(mid)

    def _insert(self, kind, text, origin, confidence, scope, source) -> int:
        """Write one memory inside the caller's transaction."""

        now = self.clock()
        expires = None if scope == "durable" else now + SESSION_TTL_S
        if scope == "durable":
            self._supersede(kind, text)
        cursor = self._db.execute(
            "INSERT INTO memories (kind, text, origin, confidence, scope, status, "
            "created, expires, source) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                kind,
                _seal(text),
                origin,
                float(confidence),
                scope,
                "active",
                now,
                expires,
                source[:120],
            ),
        )
        return cursor.lastrowid

    def _supersede(self, kind: str, text: str) -> None:
        """A new durable memory replaces an active one of the same kind that
        says mostly the same thing (contradicted or restated)."""

        new = _words(text)
        for mid, old in self._db.execute(
            "SELECT mid, text FROM memories WHERE kind=? AND status='active'", (kind,)
        ).fetchall():
            old = _unseal(old)
            if old == LOCKED:
                continue  # unreadable here: never replaced by guesswork
            words = _words(old)
            # Shared words over ALL words (Jaccard): over the shorter one, a
            # two-word memory "replaced" any longer one that mentioned them.
            if new and words and len(new & words) / len(new | words) >= 0.5:
                self._db.execute(
                    "UPDATE memories SET status='superseded' WHERE mid=?", (mid,)
                )

    # --- the Brain panel -------------------------------------------------------

    def _row(self, row) -> PersonalMemory:
        mid, kind, text, *rest = row
        return PersonalMemory(mid, kind, _unseal(text), *rest)

    def get(self, mid: int) -> PersonalMemory | None:
        row = self._db.execute("SELECT * FROM memories WHERE mid=?", (mid,)).fetchone()
        return self._row(row) if row else None

    def list(self, *, include_inactive: bool = False) -> list[PersonalMemory]:
        self.expire()
        sql = "SELECT * FROM memories" + (
            "" if include_inactive else " WHERE status='active'"
        )
        return [self._row(r) for r in self._db.execute(sql + " ORDER BY mid")]

    def search(self, query: str) -> list[PersonalMemory]:
        want = _words(query)
        return [m for m in self.list() if want & _words(m.text)]

    def relevant(self, goal: str, k: int = 5) -> list[PersonalMemory]:
        """Active memories for a request, best overlap first; minimized to k."""

        want = _words(goal)
        # Stored before a refusal rule existed (a card or ID number): it stays
        # in the panel to forget, but is never handed to the model.
        scored = [
            (len(want & _words(m.text)), m)
            for m in self.list()
            if not _unsafe(m.text) and m.text != LOCKED
        ]
        ranked = sorted(
            (s for s in scored if s[0] or s[1].kind == "preference"),
            key=lambda s: (-s[0], -s[1].mid),
        )
        return [m for _, m in ranked[:k]]

    def correct(self, mid: int, text: str) -> PersonalMemory | None:
        """The user's correction: overrides, durable, confidence 1.

        One transaction: the old memory is superseded only if its replacement
        is written, so a refused correction (e.g. sensitive text) loses
        nothing. An explicit edit applies even while learning is paused, as
        forgetting does.
        """

        old = self.get(mid)
        text = " ".join(text.split())
        if old is None or old.status != "active":
            return None  # a replaced memory stays replaced; correct its successor
        if eligibility(old.kind, text, "user_corrected", 1.0, "") == "refused":
            return None
        with self._db:
            self._db.execute(
                "UPDATE memories SET status='superseded' WHERE mid=?", (mid,)
            )
            new = self._insert(
                old.kind,
                text,
                "user_corrected",
                1.0,
                "durable",
                f"correction of #{mid}",
            )
        return self.get(new)

    def forget(self, mid: int) -> bool:
        with self._db:
            return (
                self._db.execute("DELETE FROM memories WHERE mid=?", (mid,)).rowcount
                == 1
            )

    def expire(self) -> int:
        with self._db:
            return self._db.execute(
                "DELETE FROM memories WHERE expires IS NOT NULL AND expires <= ?",
                (self.clock(),),
            ).rowcount

    def export(self) -> str:
        return json.dumps(
            [asdict(m) for m in self.list(include_inactive=True)], indent=1
        )

    def erase_all(self) -> None:
        with self._db:
            self._db.execute("DELETE FROM memories")
            self._db.execute("DELETE FROM meta")
        self._db.execute("VACUUM")
