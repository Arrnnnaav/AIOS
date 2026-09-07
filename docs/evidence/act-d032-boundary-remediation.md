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

## First re-review findings and second remediation

The first independent re-review still withheld approval. It confirmed the
original five findings were closed, then found four additional boundary gaps:

1. `python -m ghostcursor.verified_python` could resolve a payload-local shadow
   module before trusted bootstrap code ran, and a verified main file could
   still import mutable sibling Python.
2. The public executor accepted an arbitrary presentation object, so a caller
   could manufacture correctly bound receipts without painting.
3. Pause could arrive while the one-use authorization was being minted, after
   the last runnable check but before dispatch.
4. The manager bridge tests did not pass a real receipt through its sink and
   did not call the manager's production presentation factory.

Commit `fec9826` closes those findings:

- The host invokes the bootstrap by absolute path under Python `-I` mode.
  `PYTHONHOME`, `PYTHONPATH`, `PYTHONSTARTUP`, and the payload directory are
  excluded; disabled user-site `.pth` files are not processed. The bootstrap
  adds only the trusted project root and explicit interpreter dependency
  directories after the main-file hash.
  Unsigned plugin-sibling imports are refused.
- `PresentationSurface` is sealed. The private binding edge accepts only the
  reviewed `OverlaySession` and `UiThreadPresentationBridge` implementations;
  a duck-typed receipt producer is refused before an adapter starts.
- `execute_node` performs one final non-blocking Pause/Stop read after
  authorization and immediately before dispatch. A late Pause consumes no
  effect and requires a fresh run; a dispatch already in flight remains owed
  verification.
- A bridge test transports a real receipt and timestamp through the supplied
  sink, and a manager test invokes `_create_manager_act_presentation` itself.

## Second-remediation test and mutation evidence

- Focused protocol/runtime/bridge lane: **135 passed**.
- Broader adapter/plugin/manager/no-input lane: **288 passed**.
- Full hermetic lane: **2,445 passed in 162.92 s**.
- Five new intentional mutations were killed: replacing the absolute isolated
  bootstrap with payload-CWD module resolution, adding the payload directory to
  `sys.path`, bypassing the sealed-presentation check, bypassing the final
  Pause gate, and dropping the bridge receipt sink.

The first full attempt had two fixture failures caused by old tests returning
duck-typed fake overlays, plus one desktop ring observation that passed on its
isolated rerun. The fixtures were changed to return the real `OverlaySession`
type and the entire suite was rerun from the beginning; only that complete
green run is cited above.

This remains authored implementation evidence. D032 still requires a fresh
independent verdict on `a4a4441..fec9826` and this reconciliation before paint
remeasurement, release signing, or counted live acceptance.
