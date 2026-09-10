"""Retain a read-only observation of PowerPoint's open decks.

The 9 September manager proof reported "one slide became two" from an
operator's reading that reached no file, so nothing in the repository
corroborated it and D034 does not accept it as measured evidence. The D122
audit cannot carry the reading either: verifier readings are explicitly
excluded from that transcript, and widening it to hold state would turn an
observation-only record into something a reader could mistake for authority.

So the reading gets its own artifact. Run this before the live run and again
after it, then keep both files beside the transcript:

    py -3.12 -m ghostcursor.devtools.act_deck_observation ^
      --out docs/evidence/act-live-deck-before.json --label before

This module observes and nothing else. It attaches to an already-running
PowerPoint with ``GetActiveObject`` and never ``Dispatch``, because Dispatch
would *launch* the application it claims to be observing -- the same reason
an adapter may not start the process it is verifying. If PowerPoint is not
running it fails rather than starting one.

Nothing here reaches authorization: the artifact is written for a human
reviewer, is never read back by the runtime, and no value in it flows into a
proposal, an approval, a bind, or a verification.
"""

from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path


class DeckObservationError(RuntimeError):
    """PowerPoint was not running, or refused a read."""


def observe(application: object, *, label: str, at_ns: int | None = None) -> dict:
    """Read open presentations and their slide counts.

    Takes the application object rather than fetching it, so the shape of the
    reading is exercised by tests without a live desktop.
    """

    if label not in {"before", "after"}:
        raise ValueError(f"label must be 'before' or 'after', not {label!r}")

    presentations = []
    for presentation in application.Presentations:
        presentations.append(
            {
                "name": str(presentation.Name),
                "slide_count": int(presentation.Slides.Count),
                "saved": bool(presentation.Saved),
            }
        )
    presentations.sort(key=lambda row: row["name"])
    return {
        "schema_version": 1,
        "label": label,
        "at_ns": time.time_ns() if at_ns is None else at_ns,
        "application": {
            "name": "Microsoft PowerPoint",
            "version": str(application.Version),
            "build": str(application.Build),
        },
        "host": {"os": platform.platform(terse=True)},
        "presentations": tuple(presentations),
        "presentation_count": len(presentations),
    }


def render(reading: dict) -> bytes:
    """The exact bytes retained for a reading: UTF-8, LF, trailing newline."""

    return (json.dumps(reading, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _running_application():
    """Attach to a running PowerPoint. Never start one."""

    import win32com.client

    try:
        return win32com.client.GetActiveObject("PowerPoint.Application")
    except Exception as exc:  # pywintypes.com_error and friends
        raise DeckObservationError(
            "PowerPoint is not running. Open the deck first -- this probe "
            "observes an existing instance and will not start one."
        ) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new .json path")
    parser.add_argument("--label", choices=("before", "after"), required=True)
    arguments = parser.parse_args()

    if arguments.out.exists():
        print(f"refusing to overwrite {arguments.out}")
        return 2

    try:
        reading = observe(_running_application(), label=arguments.label)
    except DeckObservationError as exc:
        print(str(exc))
        return 1

    # write_bytes, not write_text: on Windows the text path translates "\n"
    # to "\r\n", and this artifact is cited by SHA-256. An evidence file whose
    # bytes depend on the platform that wrote it is the D125 defect again.
    arguments.out.write_bytes(render(reading))
    print(f"{arguments.label}: {arguments.out.resolve()}")
    for row in reading["presentations"]:
        print(f"  {row['slide_count']:>3} slides  {row['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
