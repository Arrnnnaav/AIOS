# Act D032 boundary remediation — 7 September 2026

## Review findings addressed

An independent cold review of the first cross-process geometry integration
withheld approval and found five issues:

1. UIA `BoundingRectangle` is physical pixels even when its client is not
   per-monitor aware; the system-DPI contract could therefore paint the right
   integers in the wrong coordinate space.
2. Launching a Python plugin path allowed top-level code to run before the
   plugin's self-hash in `main()`.
3. Baseline and confirm-before rectangles were compared without comparing
   their coordinate contracts.
4. Overlay geometry was checked before layout, not around the paint request.
5. One disagreement test was vacuous because its assertions were accidentally
   nested below a helper's return.

## Implemented remediation

- Production requests and freshly measures per-monitor-v2 awareness. Signed
  UIA adapter, host, and overlay independently require physical-pixel geometry.
- `ghostcursor.verified_python` verifies target bytes before compiling any
  plugin statement and executes the bytes it read, not a second path read.
- `PluginStore` binds descriptors and parsers to signed `VerifiedBundle.files`.
- Nodes compare baseline and confirm-before coordinate contracts.
- Overlay checks thread/process/window space before and after each paint and
  withholds successful receipts on drift.
- The vacuous test was repaired and fails when admission is removed.

## Test and mutation evidence

- Focused safety lane: 237 passed.
- Broader adapter/plugin/manager/no-input lane: 204 passed.
- Full hermetic lane: **2,439 passed in 158.72 s**.
- Six intentional mutations were killed: pre-execution digest bypass,
  system-DPI host admission, per-node contract comparison bypass, post-paint
  comparison bypass, mutable store reread, and per-monitor-v2 downgrade.

## Limits and next gate

This document is implementation evidence, not the independent re-review that
D032 requires. No mixed-DPI live run was performed. The prior 2 ms paint budget
predates the new pre/post coordinate queries and is invalid for acceptance
until remeasured. No live PowerPoint/manager run should be counted from these
bytes before the re-review and remeasurement complete.
