# GhostCursor Plugin Platform v1 — design

## Purpose

Move application and workflow knowledge out of the GhostCursor core without
turning plugins into arbitrary executable code. The v1 proof is two independent
application plugins and two Excel workflows authored as data. A plugin that is
absent, disabled, incompatible, ambiguous, corrupt, or withdrawn contributes no
executable intent.

## Bundle and trust boundary

- Distribution unit: one local `.ghostplugin` ZIP bundle.
- Production accepts Ed25519-signed bundles only. Unsigned bundles are confined
  to a physically separate developer store with a visible developer-mode state.
- `plugin.json` is canonical JSON. The signed bytes contain the complete
  destination-path to SHA-256 inventory, plugin identity/version, compatible
  core range, application identities, API version, and signing-key id.
- Verification precedes extraction. Runtime reload re-verifies every extracted
  byte against that signed inventory and rejects missing, extra, symlinked,
  case-colliding, or changed files.
- Plugin v1 contains no executable adapter. `adapter_api` is `null`; application
  behavior is expressed only through the reviewed pack, intent, recipe, and
  activation schemas.

Key revocation and rotation policy are intentionally deferred while GhostCursor
is the only signer. Adding a second signer or distributing third-party bundles
triggers that decision before release.

## Lifecycle authority

`PluginStore` is the only lifecycle owner. Install, enable, disable, uninstall,
catalog load, and status display do not reimplement policy elsewhere.

The effective states are:

1. `disabled` — installed but not desired active;
2. `enabled_compatible` — desired active and compatible with this core;
3. `blocked_incompatible` — still desired active, but contributes nothing until
   the core returns to its declared compatible range.

Every compatibility consumer calls `check_core_compatibility()`. Enablement is
preserved through a temporarily incompatible core upgrade so a compatible
rollback restores the plugin without silently changing operator intent.

Install and update are side-by-side and atomic. Conflicting application
identities, pack IDs, intent IDs, exact phrases, or merged catalog authority
reject the prospective active set before `active.json` changes. Disable retains
learned observations; uninstall clears observations for the exact plugin
version. Legacy unscoped rows are quarantined and never silently attributed.

## Canonical authorization

Both deterministic and model-assisted classification end at
`authorize_intent(catalog, goal, candidate)`. Only this function can mint an
`AuthorizedIntent`; a model naming a registered, formerly registered, or wholly
fictional intent grants no authority by itself.

The token binds plugin/version/manifest, active-catalog digest and generation,
pack and activation digests/generations, intent, adoption, recipe, and evidence.
`bind_workflow()` reloads the active catalog and rechecks every bound fact before
it enumerates a window. Pre-overlay revalidation repeats the artifact and live
HWND/PID/executable/title/version checks. During execution, the read-only active
index digest is checked every 0.25 seconds; withdrawal or lifecycle change
aborts within D020's 0.5-second observation-tick ceiling.

With zero enabled compatible plugins, the planner compiles zero intent specs,
both classifiers produce no executable plan, no target is resolved, and no
renderer is created. Future vision tiers may explain a screen generically, but
executable guidance without plugin authority requires a new reviewed security
decision.

## Application proof

The signed built-ins are `ghostcursor.vscode` and `ghostcursor.synthetic`; they
preserve the four independently accepted declarative workflows from the schema
v2 milestone.

`ghostcursor.excel` is a quarantined candidate for Excel
`16.0.20326.20112` with two workflows:

- `SELECT_CELL_B2`: one `DataItem` named and identified as `B2`, verified by
  focus moving to AutomationId `B2`;
- `ADD_WORKSHEET`: one `Button` named `Add Sheet`, verified by a `TabItem`
  named `Sheet2` appearing.

Office exposes these stable controls through one full traversal of the already
authorized workbook HWND, but not through provider-side exact or type-filtered
queries. D080 therefore adds the generic, explicit `window_descendants`
strategy. It is never an automatic fallback and adds no Excel branch to core.

Excel remains inactive until each workflow passes three human desktop runs on
the reviewed bytes, run records are rendered into durable evidence, application
version and configuration limits are recorded, and an independent D032 review
approves activation. A feasibility measurement or timed-out readiness attempt
is not acceptance evidence.

## v1 gates

- signature/inventory tamper tests, including post-signing digest changes;
- install/enable/disable/uninstall and side-by-side update tests;
- synthetic application and catalog conflicts rejected atomically;
- all compatibility consumers mutation-bound to one function;
- no-plugin tests for deterministic, model-assisted, target, and renderer paths;
- authorize-to-bind catalog-race tests and live runtime-withdrawal bound;
- learned-observation version isolation, disable retention, uninstall purge;
- built-in bundle/index/public-key reproducibility checks;
- two Excel workflows, 3/3 human runs each, UIA-only, exact version;
- hermetic, interactive, pixel, standalone pixel, and hung-window lanes run
  serially under D025.

## Explicitly out of scope

Marketplace distribution, third-party executable adapters, sandboxing arbitrary
code, key revocation/rotation, automatic network updates, polished installer,
manager UI, and enterprise pilot deployment are follow-on work. They must use
the same `PluginStore` and compatibility/authorization functions rather than
creating parallel policy.
