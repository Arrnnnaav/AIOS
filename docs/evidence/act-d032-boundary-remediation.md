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

## Second re-review findings and third remediation

The next independent cold review again returned **NOT READY**, while confirming
all earlier DPI, geometry, Pause/Stop, bridge, and mutable-payload findings were
closed. It found two narrower remaining gaps:

1. Exact type was not provenance. `OverlaySession` was publicly constructible,
   so a caller could build that exact type with receipt-forging callbacks and
   pass the binder's type check.
2. `-I` disables the user site but still allows system-site `.pth` startup code
   before the trusted bootstrap. The documentation had not named the system
   interpreter as trusted or excluded that code.

Commit `a7c1df5` resolves both without narrowing the visible-effect claim:

- `OverlaySession` is sealed and instances are tracked in a weak identity
  registry populated only by `overlay_presenter`. Both the surface binder and
  the final executor check require that registration, including when the
  session sits inside `UiThreadPresentationBridge`. An exact object created via
  `object.__new__` is refused. The boundary is explicitly scoped to the trusted
  in-process GhostCursor core; Python is not treated as a sandbox against
  malicious code already executing inside that process.
- Children start with `-I -S`, and the bootstrap checks `sys.flags.isolated`,
  `no_site`, and `safe_path` before reading payload bytes. Standard and Windows
  dependencies are added from explicit interpreter directories only after the
  payload hash, without processing `.pth` files.

Evidence for this remediation:

- Focused boundary lane: **195 passed**.
- Full hermetic lane: **2,447 passed in 155.71 s**.
- Two intentional mutations were killed: ignoring `no_site` made the pre-hash
  marker execute, and replacing registration with exact-type admission made
  the forged `OverlaySession` reproduction pass.

This is still authored evidence. A final independent re-review of
`a4a4441..a7c1df5` remains required before the paint benchmark or live manager
acceptance advances.

## Final cold re-review verdict — 8 September 2026

An independent reviewer returned **READY** with no blocking findings and made
no file changes. It rechecked the sealed/registered presentation boundary, the
absolute `-I -S` verified bootstrap, the post-authorization Pause/Stop gate,
the real receipt/timestamp bridge, and the manager's production presentation
factory. It also confirmed that the documentation describes registration as a
trusted in-process core boundary rather than a Python sandbox.

Independent validation:

- Focused boundary lane: **120 passed**.
- Full hermetic lane: **2,447 passed**.
- No desktop or GUI tests were run.

Commits `a7c1df5` and `ef4dbc2` are therefore cleared to proceed to paint
remeasurement and live acceptance. The historical 2 ms paint budget remains
invalid until the full checked paint transaction is measured, and this verdict
does not replace the later D032 activation review.
