"""Two Ghost Cursor processes touching one knowledge base at the same time.

Running two instances at once is a TOLERATED accident, not a supported mode:
the store must never silently lose what it learned, and a tour must never die
because another process held a lock. Throughput is explicitly not a goal.

THE BUG THESE EXIST FOR IS NOT A LOCKING FAILURE. Two writers can interleave
with no contention at all — both read the same row, both merge their own change
onto that stale read, and the second write silently discards the first one's
merge. `busy_timeout` cannot help, because nothing ever blocked.

That also makes it nearly impossible to catch by racing: the window is the few
microseconds of Python between the SELECT and the INSERT, so two processes
hammering the same row for tens of iterations will usually miss each other.
An earlier version of this file did exactly that and passed against the broken
implementation.

So the guard is structural rather than probabilistic: `record()` must touch the
row in ONE statement, leaving no window to interleave in. The concurrent tests
below still earn their place — they prove no corruption and no dead tour under
real overlap — but the single-statement test is what actually protects the
property.
"""

import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from ghostcursor.memory.store import ObservationStore
from ghostcursor.reasoning.schema import ConfirmedObservation

REPO = Path(__file__).resolve().parents[1]
CHILD = REPO / "tests" / "concurrency_child.py"

STEP_KEY = "concurrent-step"
APP_ID = "concurrent.exe"
ITERATIONS = 40


def _observation(locale: str) -> ConfirmedObservation:
    return ConfirmedObservation(
        app_version="1.0.0",
        locales_observed=[locale],
        automation_id="1001",
        control_type="Button",
        last_seen_at="2026-08-14T00:00:00+00:00",
    )


def _data_statements(store: ObservationStore, *record_args) -> list[str]:
    """The data-touching statements one record() call issues."""
    seen: list[str] = []
    store._conn.set_trace_callback(
        lambda sql: seen.append(sql.strip().split()[0].upper())
    )
    try:
        store.record(*record_args)
    finally:
        store._conn.set_trace_callback(None)
    return [s for s in seen if s in ("SELECT", "INSERT", "UPDATE", "DELETE")]


def test_record_touches_the_row_in_a_single_statement(tmp_path):
    """The real guard. One statement means no interleaving window exists.

    The broken implementation issued SELECT then INSERT, with the merge
    computed in Python in between — and the SELECT sat outside the write
    transaction entirely, so a second process could read the same row before
    either wrote. Merging inside the INSERT's ON CONFLICT clause removes the
    gap rather than narrowing it.
    """
    db = tmp_path / "kb.sqlite"
    with ObservationStore(db) as store:
        store.record(STEP_KEY, APP_ID, _observation("en-US"))  # seed the row
        statements = _data_statements(store, STEP_KEY, APP_ID, _observation("hi-IN"))

    assert statements == ["INSERT"], (
        f"record() issued {statements}; a read-modify-write across two "
        "statements leaves a window for another process to interleave in"
    )


def test_the_merge_still_works_through_the_single_statement(tmp_path):
    """Atomicity must not have been bought by dropping the merge."""
    db = tmp_path / "kb.sqlite"
    with ObservationStore(db) as store:
        store.record(STEP_KEY, APP_ID, _observation("en-US"))
        store.record(STEP_KEY, APP_ID, _observation("hi-IN"))
        store.record(STEP_KEY, APP_ID, _observation("en-US"))
        observations = store.observations_for(STEP_KEY, APP_ID)

    assert len(observations) == 1
    assert sorted(observations[0].locales_observed) == ["en-US", "hi-IN"]

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT ok_count FROM observations").fetchone()[0] == 3


def test_two_concurrent_writers_lose_nothing(tmp_path):
    """End-to-end overlap. Weak on its own — see the module docstring — but it
    is the only test that exercises two real processes against one file."""
    db = tmp_path / "kb.sqlite"
    start_flag = tmp_path / "go"

    children = [
        subprocess.Popen(
            [
                sys.executable,
                "-B",
                str(CHILD),
                str(db),
                locale,
                str(ITERATIONS),
                str(start_flag),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(REPO),
        )
        for locale in ("en-US", "hi-IN")
    ]
    time.sleep(0.6)  # let both reach the barrier before releasing them
    start_flag.write_text("go", encoding="utf-8")

    for child in children:
        out, err = child.communicate(timeout=120)
        assert child.returncode == 0, f"child failed:\n{out}\n{err}"

    with ObservationStore(db) as store:
        observations = store.observations_for(STEP_KEY, APP_ID)

    assert len(observations) == 1, f"expected one row, got {observations}"
    assert sorted(observations[0].locales_observed) == ["en-US", "hi-IN"]

    with sqlite3.connect(db) as conn:
        ok_count = conn.execute("SELECT ok_count FROM observations").fetchone()[0]
    assert ok_count == 2 * ITERATIONS, (
        f"ok_count is {ok_count}, expected {2 * ITERATIONS} — "
        f"{2 * ITERATIONS - ok_count} update(s) were silently lost"
    )


def test_a_blocked_writer_fails_in_a_way_the_caller_can_catch(tmp_path):
    """Contention must degrade, not crash uncatchably.

    A writer that cannot get the lock within busy_timeout must raise
    sqlite3.Error, which is what run.py's persist path catches to warn once and
    carry on. Anything else would end the tour on a traceback.
    """
    db = tmp_path / "kb.sqlite"
    with ObservationStore(db) as store:
        store.record(STEP_KEY, APP_ID, _observation("en-US"))

    blocker = sqlite3.connect(db, timeout=0)
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute(
        "UPDATE observations SET control_type='Held' WHERE step_key=?", (STEP_KEY,)
    )
    try:
        with ObservationStore(db) as store:
            with pytest_raises_sqlite_error():
                store.record(STEP_KEY, APP_ID, _observation("hi-IN"))
    finally:
        blocker.rollback()
        blocker.close()


def test_the_database_is_still_readable_after_concurrent_writes(tmp_path):
    """No corruption: SQLite's own integrity check must pass afterwards."""
    db = tmp_path / "kb.sqlite"
    start_flag = tmp_path / "go"

    children = [
        subprocess.Popen(
            [sys.executable, "-B", str(CHILD), str(db), locale, "20", str(start_flag)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(REPO),
        )
        for locale in ("en-US", "fr-FR")
    ]
    time.sleep(0.6)
    start_flag.write_text("go", encoding="utf-8")
    for child in children:
        child.communicate(timeout=120)

    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def pytest_raises_sqlite_error():
    import pytest

    return pytest.raises(sqlite3.Error)
