"""Retain a bounded transcript of one real native-manager Act run.

This harness does not prepare, approve, or execute a proposal itself.  It opens
the production manager loop with a write-only audit file, then the operator:

1. selects Act and enters the goal;
2. clicks Start so the signed proposal is prepared and displayed;
3. reviews the complete plan;
4. clicks the real ``Approve & run`` button once;
5. closes the manager after the terminal result is visible.

The JSONL transcript contains hashes, lifecycle event names, node ordinals and
the terminal result.  It deliberately excludes goal text, rectangles, pointer
paths, screenshots, window layout, selectors, tokens, and verifier readings.
It is evidence, never execution authority, and still needs independent D032
review before it can count as acceptance evidence.

Example:

    py -3.12 -m ghostcursor.devtools.act_live_manager ^
      --transcript .artifacts/act-live-manager-2026-09-09.jsonl
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ghostcursor.manager import launch_manager


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--transcript",
        type=Path,
        required=True,
        help="new .jsonl path in an existing directory",
    )
    arguments = parser.parse_args()

    print("GhostCursor live manager proof")
    print("Use the visible manager: Act -> enter goal -> Start -> review -> Approve & run.")
    print("Close the manager only after its terminal result is visible.")
    print(f"Transcript: {arguments.transcript.resolve()}")
    return launch_manager(act_audit_path=arguments.transcript)


if __name__ == "__main__":
    raise SystemExit(main())
