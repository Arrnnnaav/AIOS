"""Capture labelled model-Teach steps for offline replay (spec section 9, I10).

    py -3.12 -m ghostcursor.devtools.teach_capture --corpus <name> --split dev [--window HWND ...]

Binds the chosen windows (D166), observes them on a worker thread, and for each
step asks on the console for the step instruction and the candidate ids a
person would accept. Each record is built from the frame's model view, so it is
scrubbed before the first write; it is refused if a bound window's handle or
PID appears in it anyway. Records go only under the ignored ``.artifacts/``
and are never edited afterwards (D139). Nothing here acts on the screen.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from ghostcursor.evaluation.teach_replay import SPLITS, record_from_frame

CORPUS_DIR = Path(".artifacts") / "teach-corpus"


def leaks_identity(line: str, bindings) -> bool:
    """True if any bound window's HWND or PID appears as a number in ``line``."""

    numbers = {str(b.hwnd) for b in bindings} | {str(b.identity.pid) for b in bindings}
    return any(re.search(rf"(?<!\d){n}(?!\d)", line) for n in numbers if n != "0")


def append_record(path: Path, record: dict, bindings) -> None:
    line = json.dumps(record, sort_keys=True, ensure_ascii=False)
    if leaks_identity(line, bindings):
        raise ValueError("record refused: it contains a bound window's handle or PID")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture model-Teach replay steps")
    parser.add_argument("--corpus", required=True, help="corpus name (file stem)")
    parser.add_argument("--split", choices=SPLITS, required=True)
    parser.add_argument("--window", type=int, action="append", dest="windows")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.corpus):
        parser.error("corpus name: letters, digits, _ . - only")

    # No overlay window is created; only binding and the observer are used.
    from ghostcursor.harness.binding import bind
    from ghostcursor.harness.teach_live import Observer, choose_windows

    bindings = bind(args.windows or choose_windows())
    path = CORPUS_DIR / f"{args.corpus}.jsonl"
    goal = input("Goal for these steps: ").strip()
    observer = Observer(bindings)
    observer.start()
    count = 0
    try:
        while True:
            instruction = input("\nStep instruction (blank to finish): ").strip()
            if not instruction:
                break
            seen = observer.latest()
            started = time.monotonic()
            while observer.latest() is seen and time.monotonic() - started < 5:
                time.sleep(0.1)  # a frame observed after the instruction was typed
            frame = observer.latest()
            if observer.lost or frame is None:
                print("Window gone or not observed - stopping.")
                break
            for c in frame.candidates:
                print(f"  {c.cid:>5} {c.window} {c.control_type:<12} {c.name[:60]}")
            raw = input("Acceptable ids (space-separated; blank = none fits): ")
            try:
                record = record_from_frame(
                    frame,
                    step_id=f"{args.corpus}-{int(time.time() * 1000)}",
                    split=args.split,
                    goal=goal,
                    instruction=instruction,
                    labels=raw.split(),
                )
                append_record(path, record, bindings)
            except ValueError as exc:
                print(f"Not recorded: {exc}")
                continue
            count += 1
            print(f"Recorded ({count} this run) -> {path}")
    finally:
        observer.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
