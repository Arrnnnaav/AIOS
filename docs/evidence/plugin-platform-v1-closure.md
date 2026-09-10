# Plugin Platform v1 closure

This record closes the signed, data-only plugin-platform milestone. It is a
current-state audit record; the human-run source evidence remains in
`plugins/sources/excel/payload/docs/evidence/excel-plugin-acceptance.md`.

## Authority and signed artifact

- Activation commit: `a764c48e306f5587a7ae72d22bf96b6c82d862d9`
- Independently approved evidence commit:
  `381d97f5f376ee586260eb4430595fcff1e2668e`
- Plugin: `ghostcursor.excel` 1.0.0
- Application identity: `executable_version = 16.0.20326.20112`
- Signing key id: `ghostcursor-release-2026-2`
- Manifest SHA-256:
  `53122d6d37e99f1e18a5e236d8a2409bea9769c7e53d1e1be2a6eeefffacf3e2`
- Bundle SHA-256:
  `a5e4e9e9673696ffff459ba69d1dfaf435b56e60d3b55c415401a99f97dcf00e`
- Evidence SHA-256 **in the signed bundle**:
  `fcedf7188df76e1e4d85b8ccc24134130baa62d1524df772599a3adaac707e7e`
- Evidence SHA-256 **in the repository today**:
  `cce87d752f3fd5a4c2518a8874a2acff41ccc1057521c5d9552885554f0b0472`

These differ, and the difference is the point. The repository copy was
redacted and its target bindings pseudonymised under D128/D129; the signed
bundle still carries the pre-redaction bytes, because
`ghostcursor-release-2026-2` is not available and the bundle cannot be
re-signed. The bundle is inventoried in `plugins/bundled/legacy-exposure.json`
as `legacy_exposed` and is excluded from first-run enable. Treat the signed
artifact described here as **legacy**: it is not sanitised, and it is not
acceptance evidence for anything after 10 September 2026.

Only the public Ed25519 key is tracked. A scan found no private-key material in
the current tree or reachable history. The signing procedure reported deleting
its temporary release key after signing; that deletion event is not itself
reproducible from repository state. The bundle declares `adapter_api: null`;
no executable Python is present in the plugin.

The active merged catalog contains the signed Excel, Synthetic, and VS Code
plugins. Both Excel intents authorize from that catalog and carry active
adoptions. A fresh-store bootstrap installs all three plugins, but enables
only `ghostcursor.synthetic`: the Excel and VS Code bundles are quarantined
under D129 until sanitised bundles replace them.

## Human desktop acceptance

| Workflow | Counted runs | Steps | Grounding | Result |
|---|---:|---:|---|---|
| `SELECT_CELL_B2` | 3 | 1/1 each | UIA only | 3/3 passed |
| `ADD_WORKSHEET` | 3 | 1/1 each | UIA only | 3/3 passed |

Two earlier `ADD_WORKSHEET` attempts are retained as excluded operator aborts
at 0/1 after verification began. Their records do not establish an abort cause
and the evidence does not infer one.

## Independent review

The acceptance evidence was first reviewed at `ee66e79`; the reviewer rejected
unsupported statements about workbook reset/reopen behavior and abort causes.
Commit `381d97f` removed those inferences, retained the exact records, and was
approved. A separate reviewer then approved the signed activation tree at
`a764c48`; the focused review suite reproduced as 23 passed. The durable review
record is `docs/evidence/plugin-platform-v1-activation-review.md`.

The activation is therefore not byte-identical to the first evidence tree: it
contains only the approved evidence plus the signed bundle, trusted public key,
adoptions, bundle index entry, and their tests.

## Mutation audit

Mutations ran serially in a detached worktree at the exact activation commit.
Every mutation was killed by the named invariant and the restored tree matched
its original tree digest before the worktree was removed.

| Mutation | Required failure |
|---|---|
| Skip Ed25519 verification | signature-tamper test |
| Skip a signed file digest | inventory-tamper test |
| Make compatibility maximum inclusive | half-open range test |
| Skip model/deterministic agreement | canonical-authority tests |
| Skip catalog-digest comparison at bind | authorize-to-bind race test, before UIA |
| Ignore active-index change during a tour | runtime-withdrawal test |
| Ignore acceptance outcome while rendering | Excel evidence tests |
| Skip candidate-byte rehash while rendering | Excel evidence test |

Result: **8/8 killed**. Restored tree digest:
`3a50e8ea145be3d728fee904506600e5901ad607`.

## Serial regression gates

Every desktop, pixel, and hung lane ran alone under D025.

| Lane | Result |
|---|---|
| Hermetic | 1119 passed, 70 deselected |
| Interactive | 54 passed, 1135 deselected |
| Pixel | 3 passed, 1186 deselected |
| `python -m tests.test_overlay` | 16/16 checks |
| `python -m tests.test_end_to_end` | 8/8 checks |
| `test_hung_window.py` | 4 passed, 46.52s |
| `test_perception_service_hung.py` | 2 passed, 9.33s |
| `test_run_threaded.py` | 7 passed, 15.42s |

The first post-activation hermetic run exposed one stale explicit registry
expectation: it still listed the pre-Excel intent set. No production behavior
failed. The test was updated to name both active Excel intents, its focused
case passed, and the complete hermetic lane then passed as shown above.

## Closed claim

Plugin Platform v1 now proves that a second real desktop application can add
reviewed executable workflows through signed declarative data alone. It does
not claim support for another Excel version, arbitrary plugin code, third-party
signers, a marketplace, key revocation, or installer/manager UI.
