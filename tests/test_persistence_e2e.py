"""Two real processes, one shared database.

Reopening a connection in-process proves the storage layer. It does not prove
a second LAUNCH works, because module state and DPI awareness are already
warm. This spawns actual subprocesses so the claim being made — a recipe grows
stronger across restarts — is the claim being tested.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHILD = REPO / "tests" / "persistence_child.py"


def _run_child(db_path: Path) -> dict:
    env = dict(os.environ, GHOSTCURSOR_KB_PATH=str(db_path), PYTHONPATH=str(REPO))
    result = subprocess.run(
        [sys.executable, "-B", str(CHILD)],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(REPO),
    )
    assert result.returncode == 0, f"child failed:\n{result.stdout}\n{result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_second_process_grounds_by_the_id_the_first_one_learned(tmp_path):
    db = tmp_path / "kb.sqlite"

    first = _run_child(db)
    assert first["grounded"] is True
    assert first["hydrated"] == 0, "nothing should exist before the first run"
    assert first["rung"] in (2, 3), (
        f"first run must learn by name, got rung {first['rung']}"
    )
    assert first["automation_id"] == "1001"

    assert db.exists(), "the first run did not create the database"

    second = _run_child(db)
    assert second["grounded"] is True
    assert second["hydrated"] >= 1, "the second run loaded nothing from disk"
    assert second["rung"] == 1, (
        f"second run should ground by AutomationId, got rung {second['rung']}"
    )
    assert second["automation_id"] == "1001"


def test_deleting_the_database_makes_the_system_relearn(tmp_path):
    db = tmp_path / "kb.sqlite"
    _run_child(db)
    assert _run_child(db)["rung"] == 1

    db.unlink()  # the documented user-facing erase path

    relearned = _run_child(db)
    assert relearned["hydrated"] == 0
    assert relearned["rung"] in (2, 3), "learning survived deletion of the store"
