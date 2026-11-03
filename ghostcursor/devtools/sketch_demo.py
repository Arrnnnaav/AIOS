"""Draw hand-drawn marks on a bound window's real controls (harness/sketch.py).

    py -3.12 -m ghostcursor.devtools.sketch_demo [--marks '<json>'] [--seconds 10]

Without ``--marks`` it circles the first named button, arrows to the second
and underlines the third. ESC or ``--seconds`` stops; the overlay only draws.
"""

from __future__ import annotations

import argparse
import json
import time

# overlay.window first: it imports overlay.dpi before any window exists.
from ghostcursor.overlay import window
from ghostcursor.overlay import cue
from ghostcursor.overlay.dpi import virtual_screen_rect
from ghostcursor.harness import sketch
from ghostcursor.harness.binding import bind
from ghostcursor.harness.teach_live import (
    TICK_S,
    Observer,
    _escape_pressed,
    choose_windows,
)


def _default_marks(frame) -> dict:
    buttons = [
        c.cid for c in frame.candidates if c.control_type == "Button" and c.name
    ][:3]
    if not buttons:
        raise SystemExit("no named buttons in that window")
    marks = [{"kind": "circle", "cid": buttons[0], "note": "start here"}]
    if len(buttons) > 1:
        marks.append(
            {"kind": "arrow", "cid": buttons[0], "to": buttons[1], "note": "then this"}
        )
    if len(buttons) > 2:
        marks.append({"kind": "underline", "cid": buttons[2]})
    return {"marks": marks}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--marks", help='{"marks": [{"kind": ..., "cid": ...}]}')
    parser.add_argument("--seconds", type=float, default=10.0)
    args = parser.parse_args(argv)

    hwnds = choose_windows()
    if not hwnds:
        return 2
    observer = Observer(bind(hwnds[:1]))
    observer.start()
    overlay = window.create_overlay_window()
    deadline = time.monotonic() + args.seconds
    try:
        while (frame := observer.latest()) is None:
            if observer.lost or time.monotonic() > deadline:
                return 1
            time.sleep(TICK_S)
        for c in frame.candidates:
            print(f"  {c.cid:5} {c.control_type:<12} {c.name[:40]}")
        raw = json.loads(args.marks) if args.marks else _default_marks(frame)
        current = sketch.start(raw, frame, time.monotonic())
        x, y, w, h = virtual_screen_rect()
        bounds = (x, y, x + w, y + h)
        while time.monotonic() < deadline and not _escape_pressed():
            latest = observer.latest()
            current = (
                sketch.follow(current, latest) if latest and not observer.lost else None
            )
            now = time.monotonic()
            if current is None or current.expired(now):
                break  # a marked control moved away or vanished: stop drawing
            boxes = []
            for text, rect in sketch.notes(current, now):
                tip = ((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
                metrics = window.measure_label(overlay, text)
                boxes.append(
                    (text, cue.label_box(tip, text, metrics, bounds=bounds, avoid=rect))
                )
            window.set_sketch(overlay, sketch.strokes(current, now), boxes)
            window.pump_messages_nonblocking()
            time.sleep(TICK_S / 2)
    finally:
        window.clear_sketch(overlay)
        window.destroy_overlay_window(overlay)
        observer.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
