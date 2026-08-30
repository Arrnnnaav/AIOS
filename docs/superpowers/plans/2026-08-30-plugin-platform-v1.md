# GhostCursor Plugin Platform v1 — implementation plan

Source design:
`docs/superpowers/specs/2026-08-30-plugin-platform-v1-design.md`.

## Phase A — trust and lifecycle

- [x] Strict signed bundle verification and signed digest inventory.
- [x] Separate production/developer stores; production rejects unsigned data.
- [x] Atomic install, enable, disable, uninstall, conflict rejection, and three
  effective compatibility states.
- [x] Shared `check_core_compatibility()` across every consumer.
- [x] Plugin-version-scoped learned observations and legacy quarantine.

## Phase B — production authority

- [x] Merge enabled compatible plugin catalogs with plugin provenance.
- [x] Route deterministic and model-assisted candidates through one
  `authorize_intent()` checkpoint.
- [x] Recheck the active catalog at bind time before any target enumeration.
- [x] Bootstrap signed VS Code and Synthetic bundles once without re-enabling an
  operator-disabled plugin.
- [x] Prove zero enabled plugins means zero executable screen knowledge.
- [x] Abort a running tour within one observation tick after authority changes.

## Phase C — second-application proof

- [x] Measure Excel UIA on a dedicated workbook and record feasibility.
- [x] Add generic `DataItem` and explicit `window_descendants` grammar under
  D080, without application-specific Python.
- [x] Author inactive `SELECT_CELL_B2` and `ADD_WORKSHEET` candidate graphs.
- [x] Run three human desktop acceptances for `SELECT_CELL_B2`.
- [x] Run three human desktop acceptances for `ADD_WORKSHEET`.
- [x] Render the six passing records and retain the two excluded attempts.
- [ ] Obtain independent review, add adoptions, sign the Excel bundle, and
  activate it.

## Phase D — closure

- [ ] Run every regression lane serially under D025.
- [ ] Mutation-audit the new platform guards and restore sources by digest.
- [ ] Independent D032 review of the activation tree.
- [ ] Update final evidence, architecture, rules, decisions, and Graphify.

The candidate remains quarantined while any Phase C checkbox is open. Do not
replace a missing desktop action or independent review with generated evidence.
