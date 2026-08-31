"""Content-minimized local session history and explicit diagnostics export."""

from __future__ import annotations

import json
import os
import sqlite3
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from ghostcursor.session import SessionSnapshot

ENV_PATH = "GHOSTCURSOR_SESSION_DB_PATH"
RETENTION_DAYS = 30

_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_events (
    session_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    status TEXT NOT NULL,
    intent_id TEXT,
    plugin_id TEXT,
    plugin_version TEXT,
    application TEXT,
    current_step INTEGER NOT NULL,
    total_steps INTEGER NOT NULL,
    elapsed_s REAL NOT NULL,
    error_code TEXT,
    detail_code TEXT,
    provenance_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS session_events_age
ON session_events(occurred_at);
"""


def default_session_db_path() -> Path:
    override = os.environ.get(ENV_PATH)
    if override:
        return Path(override)
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(root) / "GhostCursor" / "sessions.sqlite"


@dataclass(frozen=True)
class DiagnosticExportOptions:
    include_goal: bool = False
    include_note: bool = False


class SessionStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_session_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.execute("PRAGMA busy_timeout = 2000")
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def __enter__(self) -> "SessionStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def record(self, snapshot: SessionSnapshot, *, occurred_at: datetime | None = None) -> None:
        """Persist identifiers and outcomes, never screen or free-text content."""

        timestamp = (occurred_at or datetime.now(UTC)).astimezone(UTC).isoformat()
        # `detail` may include a window title, path, provider error, or text
        # read from the screen. Persist only its stable classification.
        detail_code = "present" if snapshot.detail else None
        self._connection.execute(
            "INSERT INTO session_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                snapshot.session_id,
                timestamp,
                snapshot.status.value,
                snapshot.intent_id,
                snapshot.plugin_id,
                snapshot.plugin_version,
                snapshot.application,
                snapshot.current_step,
                snapshot.total_steps,
                snapshot.elapsed_s,
                snapshot.error_code,
                detail_code,
                json.dumps(list(snapshot.provenance), separators=(",", ":")),
            ),
        )
        self._connection.commit()

    def purge_expired(self, *, now: datetime | None = None) -> int:
        cutoff = (now or datetime.now(UTC)).astimezone(UTC) - timedelta(
            days=RETENTION_DAYS
        )
        cursor = self._connection.execute(
            "DELETE FROM session_events WHERE occurred_at < ?", (cutoff.isoformat(),)
        )
        self._connection.commit()
        return cursor.rowcount

    def clear(self) -> int:
        cursor = self._connection.execute("DELETE FROM session_events")
        self._connection.commit()
        return cursor.rowcount

    def events(self, session_id: str | None = None) -> list[dict[str, object]]:
        self._connection.row_factory = sqlite3.Row
        if session_id is None:
            rows = self._connection.execute(
                "SELECT * FROM session_events ORDER BY occurred_at, rowid"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM session_events WHERE session_id=? "
                "ORDER BY occurred_at, rowid",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def export(
        self,
        destination: str | Path,
        *,
        options: DiagnosticExportOptions = DiagnosticExportOptions(),
        goal: str | None = None,
        note: str | None = None,
    ) -> Path:
        """Create a user-chosen, previewable archive; nothing is uploaded."""

        payload: dict[str, object] = {
            "schema_version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "events": self.events(),
            "privacy": asdict(options),
        }
        if options.include_goal and goal is not None:
            payload["goal"] = goal
        if options.include_note and note is not None:
            payload["note"] = note
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("diagnostics.json", raw)
        return target
