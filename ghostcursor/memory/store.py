"""Local, on-disk memory of what grounding has learned (spec §10).

This is the first thing in the system to write screen-derived data to disk:
application identity and the names of UI elements read from the user's screen.
The §2 invariant governs data LEAVING the machine and is not weakened by this,
but the locality is deliberate and stated:

  - local only; no telemetry, no network, no cloud sync
  - stored at %LOCALAPPDATA%\\GhostCursor\\kb.sqlite and nowhere else
  - deleting that file fully erases it; the system re-learns from scratch

The primary key (step_key, app_id, app_version, automation_id) is what makes
promotion idempotent: re-observing the same id for the same step, app and
version updates one row instead of appending a duplicate forever.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from ghostcursor.reasoning.schema import ConfirmedObservation

#: Overriding the path is what lets tests — and a second process in the
#: end-to-end proof — share a database without touching the real one.
ENV_PATH = "GHOSTCURSOR_KB_PATH"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    step_key         TEXT NOT NULL,
    app_id           TEXT NOT NULL,
    app_version      TEXT NOT NULL,
    automation_id    TEXT NOT NULL,
    control_type     TEXT,
    locales_observed TEXT NOT NULL DEFAULT '[]',
    last_seen_at     TEXT,
    ok_count         INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (step_key, app_id, app_version, automation_id)
);
"""


def default_db_path() -> Path:
    override = os.environ.get(ENV_PATH)
    if override:
        return Path(override)
    local_app_data = os.environ.get("LOCALAPPDATA") or str(
        Path.home() / "AppData" / "Local"
    )
    return Path(local_app_data) / "GhostCursor" / "kb.sqlite"


class ObservationStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        # Explicit rather than sqlite3's implicit 5s default: two Ghost
        # Cursor processes (e.g. the two-process end-to-end proof, or a
        # second tour started against the same app) can legitimately share
        # this database, and a short, deliberate timeout here documents
        # that instead of leaving the concurrency behaviour to an implicit
        # library default.
        self._conn.execute("PRAGMA busy_timeout = 2000")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def __enter__(self) -> "ObservationStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def record(
        self, step_key: str, app_id: str, observation: ConfirmedObservation
    ) -> None:
        """Upsert one observation, merging locales with anything already known."""
        if not observation.automation_id:
            return  # nothing learned; never invent an id

        existing = self._conn.execute(
            "SELECT locales_observed, ok_count FROM observations "
            "WHERE step_key=? AND app_id=? AND app_version=? AND automation_id=?",
            (step_key, app_id, observation.app_version, observation.automation_id),
        ).fetchone()

        locales = set(observation.locales_observed)
        ok_count = 1
        if existing:
            locales |= set(json.loads(existing["locales_observed"]))
            ok_count = existing["ok_count"] + 1

        self._conn.execute(
            "INSERT INTO observations (step_key, app_id, app_version, automation_id,"
            " control_type, locales_observed, last_seen_at, ok_count)"
            " VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(step_key, app_id, app_version, automation_id) DO UPDATE SET"
            "   control_type=excluded.control_type,"
            "   locales_observed=excluded.locales_observed,"
            "   last_seen_at=excluded.last_seen_at,"
            "   ok_count=excluded.ok_count",
            (
                step_key,
                app_id,
                observation.app_version,
                observation.automation_id,
                observation.control_type,
                json.dumps(sorted(locales)),
                observation.last_seen_at,
                ok_count,
            ),
        )
        self._conn.commit()

    def observations_for(
        self, step_key: str, app_id: str
    ) -> list[ConfirmedObservation]:
        rows = self._conn.execute(
            "SELECT * FROM observations WHERE step_key=? AND app_id=?"
            " ORDER BY app_version, automation_id",
            (step_key, app_id),
        ).fetchall()
        return [
            ConfirmedObservation(
                app_version=row["app_version"],
                locales_observed=json.loads(row["locales_observed"]),
                automation_id=row["automation_id"],
                control_type=row["control_type"],
                accessibility_path_hint=[],
                last_seen_at=row["last_seen_at"],
            )
            for row in rows
        ]

    def forget_all(self) -> None:
        """Erase everything. The user-facing equivalent is deleting the file."""
        self._conn.execute("DELETE FROM observations")
        self._conn.commit()
