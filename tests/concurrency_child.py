"""One concurrent writer, for the two-process contention test.

Records the SAME observation row repeatedly under its own locale, so two of
these running at once are both doing read-modify-write against one row. That
is the interleaving that silently loses data when the merge happens in Python
between two statements instead of inside one SQL statement.

Usage: concurrency_child.py <db_path> <locale> <iterations> <start_flag_path>

Waits for the start flag before writing so both processes overlap for real
rather than running one after the other — sequential calls cannot reproduce
the bug, which is exactly why it survived until now.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ghostcursor.memory.store import ObservationStore
from ghostcursor.reasoning.schema import ConfirmedObservation

STEP_KEY = "concurrent-step"
APP_ID = "concurrent.exe"


def main() -> int:
    db_path, locale, iterations, start_flag = sys.argv[1:5]
    flag = Path(start_flag)

    # Barrier: spin until the parent drops the flag, so both children hit the
    # database inside the same few milliseconds.
    deadline = time.monotonic() + 30
    while not flag.exists():
        if time.monotonic() > deadline:
            print("TIMEOUT waiting for start flag", file=sys.stderr)
            return 2
        time.sleep(0.001)

    with ObservationStore(db_path) as store:
        for _ in range(int(iterations)):
            store.record(
                STEP_KEY,
                APP_ID,
                ConfirmedObservation(
                    app_version="1.0.0",
                    locales_observed=[locale],
                    automation_id="1001",
                    control_type="Button",
                    last_seen_at="2026-08-14T00:00:00+00:00",
                ),
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
