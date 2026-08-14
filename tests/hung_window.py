"""A window whose owner deliberately stops pumping messages.

Used as a test fixture: this is what an ordinary "Not Responding" application
looks like to UIA. Creating the window requires a pump; after that we stop,
which is precisely the state that makes a UIA tree walk block for tens of
seconds.

Prints `ready` once the window exists so the parent can synchronise, then
sleeps without servicing its message queue until killed.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.uia_app import SyntheticApp


def main() -> int:
    title = sys.argv[1] if len(sys.argv) > 1 else "GhostCursorHungApp"
    app = SyntheticApp(title=title)
    app.__enter__()
    print("ready", flush=True)
    # Deliberately never pump again. The parent kills this process.
    time.sleep(600)
    return 0


if __name__ == "__main__":
    sys.exit(main())
