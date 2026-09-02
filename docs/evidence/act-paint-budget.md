# Overlay cue paint cost — measured

**Date:** 3 September 2026
**Machine:** Windows 11 Home Single Language 10.0.26200, i7-12650H, 15.7 GB RAM
**Display:** single monitor, virtual screen `(0, 0, 1920, 1080)`
**Harness:** `py -3.12 -m ghostcursor.devtools.paint_budget --frames 400`
**Code under measurement:** `ghostcursor/overlay/window.py` `set_cue` →
`WM_PAINT` (full-client colorkey fill, ring, glyph, label plate) at commit
`b222d7e` plus the `CreateFontIndirect` fix.

## Why this number has to exist

`pointer_path.frame_count()` and `act_overlay.CueBudget` both refuse a
`frame_budget_ms` they were not given. That is deliberate: a default would be
a number nobody measured, and it would also be the number every test silently
agreed with. This file is where the number comes from, so a budget cited
anywhere else can name its source (D034).

## What one frame pays for

`set_cue` invalidates the window and calls `UpdateWindow`, so `WM_PAINT` runs
synchronously inside the timed section. That handler fills the **entire**
virtual-screen client area with the colorkey — which is what makes the overlay
transparent — and then draws the ring, the glyph and the label plate. The fill
dominates and scales with desktop area, so this number is valid only for the
topology recorded above.

## Results

Three consecutive 400-frame runs, positions and label placement varying every
frame so no frame repaints an identical scene:

| Run | mean | median | p99 | max | budget (p99 ⌈⌉) |
|---|---|---|---|---|---|
| 1 | 0.534 ms | 0.453 ms | 0.945 ms | 16.630 ms | 1 ms |
| 2 | 0.500 ms | 0.452 ms | 0.865 ms | 5.059 ms | 1 ms |
| 3 | 0.496 ms | 0.452 ms | 1.077 ms | 5.996 ms | 2 ms |

The median is stable to 1 µs across all three runs. The p99 straddles 1 ms,
so the derived budget is 1–2 ms depending on the run.

**Recommended `frame_budget_ms` for this machine: 2.** The higher of the three
p99s, not the mean. A frame budget is a deadline, and the frames that overrun
the interrupt poll interval are precisely the ones a mean hides.

## The outliers

Run 1's 16.63 ms maximum is a single frame; runs 2 and 3 peak at ~5–6 ms.
These are first-paint and allocator effects, not a sustained cost — the median
does not move. A 16 ms frame makes one frame late; it does not approach the
50 ms interrupt poll interval, which is the only threshold with a safety
consequence.

## What this means for the animation

On this machine the paint is cheap enough that **the frame count is limited by
the 12-frame ceiling, not by the paint cost**: `frame_count(400, 2)` is
`min(12, 200)` = 12. The budget only becomes the binding constraint on a
machine where a paint costs more than ~33 ms for a 400 ms traversal.

`schedule_for` refuses geometry outright when `frame_budget_ms` exceeds the
50 ms poll interval. At 2 ms this machine is two orders of magnitude clear of
that, so the rail-text fallback is not exercised here and remains unverified
on real hardware.

## Visual confirmation

One cue was rendered at target `(700, 400, 860, 445)` with the pointer tip at
its centre `(780, 422)` and captured with `mss`:

- The colorkey does not survive anywhere in the captured region (0 pixels of
  `(255, 0, 255)`), so transparency is working and no cue element was painted
  in the key colour.
- 1325 pixels of the NEUTRAL cue colour `(200, 200, 200)` were drawn.
- The label plate landed at `(874, 400, 949, 427)` — beside the control,
  clear of it, from the target-anchored placement tier.
- Real font metrics measured `char_width=7, line_height=15` for "New Slide",
  against the `8`/`16` used in hermetic tests. The difference is why
  `label_box` takes measured metrics rather than assuming them.

## Not measured here

- Multi-monitor topologies. The colorkey fill scales with total desktop area,
  so a wider virtual screen will cost more and must be re-measured.
- Paint cost while a target application is redrawing heavily.
- The verifier spawn cost and the confirmation-to-invoke interval, which are
  separate Phase E budgets.
