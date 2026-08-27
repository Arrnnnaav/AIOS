# Declarative Workflow Compiler and Recipe Schema v2 — Design

Date: 2026-08-27
Status: **approved after independent D032 re-review; implementation not started**
Decisions: D069 (+ later-measurement amendment), D070, D072, D073
Evidence: `docs/evidence/provider-findall-spike.md`,
`docs/evidence/d072-compatibility-corpus.md`,
`docs/evidence/workflow3-uia-feasibility.md`

---

## 1. Why

Adding a workflow to GhostCursor currently requires new Python: a bespoke UIA
walker, a branch in `perception_walker_for()`, and an entry in the hardcoded
`registry()` dict in `ghostcursor/reasoning/planner.py`. Every application pack
therefore costs engineering time proportional to the number of workflows, which
is the constraint that keeps the product at two certified workflows in one
application.

**The product-defining proof is adding Open Extensions through data alone** —
manifest and recipe artifacts, with no workflow-specific change under
`ghostcursor/**/*.py`.

Two discoveries shaped this design.

**There are already two intent→recipe mappings, and only one of them executes.**
`registry()` is a hardcoded dict and is the real execution authority.
`PackRegistry` plus the JSON manifests is consumed only by `daemon.py` and
tests, so it never executes anything. That is why its `recipe_for_intent()` can
get away with globbing the recipe directory, matching `path.stem` against the
intent id, and falling back to "the only recipe in a one-intent pack" — all
three forbidden by D070. The compiler's job is not to invent a mapping. It is to
**make the manifest path authoritative and harden it in the same move**,
because the moment it executes, those three shortcuts become authority holes.

**`bounded_descendants` has a live defect.** `uia.py:368` breaks out of its loop
at `len(selected) >= limit`, so a small limit truncates the result before the
`EXACTLY_ONE` ambiguity check can observe a second match. Shipped in `c7a85ab`;
fixed as part of this work.

---

## 2. Artifact layout

```
ghostcursor/packs/
  index.json                          # names pack dirs explicitly; no glob
  vscode/
    pack/vscode.<digest>.json         # pack_kind: "application"
    intents/open_folder.<digest>.json
    intents/open_terminal.<digest>.json
    recipes/open_folder.<digest>.json
    recipes/open_terminal.<digest>.json
    activation.json                   # the ONLY mutable file in a pack
  synthetic/ …   notepad/ …           # pack_kind: "application"
  common/
    pack/common.<digest>.json         # pack_kind: "planner_only"
    intents/create_document.<digest>.json
    intents/open_settings.<digest>.json
    activation.json                   # both indexed, active adoption null
```

Every immutable executable artifact — pack identity, intent, and recipe — uses a
whole-file content-addressed name. One hashing rule, no JSON canonicalisation to
specify. Filenames carry a readable name plus 12–16 hex characters of the
artifact's SHA-256 for reviewability; **the full 64-hex digest recorded in
`activation.json` is the authority**, and the filename fragment is never parsed
or trusted. Mutable `activation.json`, mutable `packs/index.json`, and committed
evidence are also bound by SHA-256 over their exact bytes where this design names
a digest, but do not pretend to contain their own address.

`activation.json` binds the pack, intent, and recipe digests together, so
broadening a title pattern or an intent phrase after acceptance cannot retain
authority over the accepted recipe.

### Complete artifact schemas

All schema-v2 JSON objects carry `"schema_version": 2`, reject unknown fields,
reject duplicate object keys during parsing, and validate types before any
cross-file lookup. Standard `json.loads()` duplicate-key last-write-wins
behaviour is forbidden at this trust boundary.

`packs/index.json` has exactly `schema_version` and `packs`. `packs` is a list of
objects with exactly `pack_id` and `path`; both are non-empty canonical strings,
and IDs and resolved directories are unique after case-folding.

A pack artifact has exactly:

```json
{
  "schema_version": 2,
  "pack_id": "vscode",
  "pack_kind": "application",
  "display_name": "Visual Studio Code",
  "executable_names": ["code.exe"],
  "title_patterns": [".*Visual Studio Code.*", ".* - Code$"],
  "tier2_capture": "executable_bounded",
  "version_identity": { "kind": "executable_version" },
  "aliases": {
    "vscode_names": ["vs code", "vscode", "visual studio code"]
  }
}
```

Every string and list member is non-empty. Executable names are canonical
case-folded basenames. Title patterns are compilable regular
expressions used only for window discovery. Alias names and members obey D072's
canonical-literal rules. The v1 `recipe_directory`, `intent_ids`, and empty
`version_constraints` fields do not survive: the root index names the pack,
`activation.json` is the intent index, and exact accepted application identity
lives on each adoption record. Keeping the old fields would create duplicate
sources of authority.

`tier2_capture` is exactly `executable_bounded` or `disabled`. It is explicit
because deriving it from a non-empty executable list would newly enable OCR for
Synthetic Export, whose v1 `app_id: "synthetic"` deliberately produces no tier-2
capture. The migrated synthetic pack declares `disabled`; VS Code declares
`executable_bounded`. A `planner_only` pack must declare `disabled`.

`version_identity` is explicit under D073. An application pack declares exactly
one of:

```json
{ "kind": "executable_version" }
{ "kind": "content_sha256", "path": "ghostcursor/demo/synthetic_export_app.py" }
```

VS Code uses `executable_version`, resolved from the matched executable's
`AppInfo.version`. Synthetic Export uses `content_sha256`, resolved from the
exact stored bytes of its checked-in application module; a Python interpreter
patch is not the demo application's version. The content path is forward-slash,
repository-relative, contains no `..`, is not a symlink, and must resolve under
the allowlisted `ghostcursor/demo/` application-source root. A `planner_only`
pack declares `version_identity: null`. There is no command, plugin, arbitrary
path, or operator-supplied strategy.

An intent artifact has exactly `schema_version`, `intent_id`,
`canonical_target`, and `rules`. `canonical_target` is either `null` or a
non-empty display string; it may help the CLI identify a synthetic target but
does not grant execution authority. `rules` is exactly the D072 grammar in §5.

A recipe artifact has exactly `schema_version`, `intent_id`,
`step_key_namespace`, `selectors`, `context_selectors`, and `steps`. It has no `app_id`: activation
binds it to one pack. `step_key_namespace` is the stable string passed as the
first argument to D016's `step_key()`; each migrated recipe preserves its v1
`recipe.intent` value byte-for-semantic-value so existing SQLite learning stays
attached. New workflows default it to their canonical intent ID, and changing it
is an explicit learning invalidation. `selectors` is an object keyed by
canonical selector ID and follows §6. Every step retains the v1
instruction contract—`user_action`, `target_descriptor`, `instruction_text`,
`verification_rule`, `risk`, `preconditions`, and `provenance`—and adds
`target_selector`, which is either a selector ID or `null`.

`context_selectors` is a list of selector IDs needed for explicit world-change
or wrong-action observation but not directly referenced by an action or
verification rule. It is how Synthetic Export preserves its certified
wrong-action surface without reverting to an unbounded full-window walk. Every
declared selector must be referenced by a step, verification rule, or this list;
unused selectors are rejected.

`target_descriptor.claimed` remains distinct from the selector intentionally.
The selector bounds which backend candidates perception may publish; the
claimed descriptor grounds and describes a target within that bounded set and
continues to supply D016's `step_key()` fields. Open Folder demonstrates why the
two cannot be collapsed: its observation selector must exclude the plain
sidebar `Open Folder`, while its human-facing descriptor may retain broader
synonyms. `target_descriptor.confirmed` must be empty in trusted JSON; confirmed
observations are hydrated from `kb.sqlite`, never authored into an artifact.

The step-level `provenance` object remains mandatory and keeps the existing
pre-acceptance fields (`source_urls`, `source_tier`, `model`, `prompt_version`,
`created_at`). Artifact digest and post-acceptance facts do not move into it;
they belong to the adoption record in `activation.json` per D070.

For `element_appears`, `element_disappears`, and `property_changes`, the
serialized verification rule names a `selector` and does not duplicate a
`target_descriptor` inside `args`; the compiler derives the runtime descriptor
from that verified selector. `window_title_matches` uses §7. The remaining four
verification kinds retain their existing strict arguments and options. All
coordinate-like keys remain recursively forbidden.

### `pack_kind` is explicit, never inferred from empty arrays

| Kind | Meaning |
|---|---|
| `application` | Executable names and title patterns are both non-empty; validated executable-plus-title identity participates in window matching |
| `planner_only` | Executable names, title patterns, and aliases **must** be empty; tier-2 capture is `disabled`; version identity is `null`; never matches a window; every intent has active adoption `null` and empty adoption history |

`CREATE_DOCUMENT` and `OPEN_SETTINGS` belong to no application but are
load-bearing: the certified never-fabricate matrix depends on them returning
`KNOWN_INTENT_RECIPE_UNAVAILABLE` rather than `UNSUPPORTED_GOAL`. They live in a
`planner_only` pack. Per D072 they carry **no deterministic matcher rules** —
`_fallback()` never checks them today, so adding rules would change
deterministic-null results and break migration parity.

`OPEN_NEW_TAB` is **deleted and not indexed**. It has zero planner references
today, so indexing it even as inactive would make it planner- and
model-visible and change current behaviour.

### Encoding — split responsibility

`.gitattributes` pins **every digest-bound text file** to LF: pack JSON
(including `index.json` and `activation.json`), D073 content-identity source,
and committed Markdown under `docs/evidence/`. **UTF-8 without BOM is enforced
by the trusted loaders and by tests**, not by `.gitattributes`, which cannot
express it. A BOM is a load
failure, never a silent strip.

This is latent today, not hypothetical: `.gitattributes` is absent and
`core.autocrlf=input`, so recipe JSON happens to be LF in the working tree while
nothing enforces it. One save from a Windows editor and stored bytes diverge
from working-tree bytes, and every digest fails after checkout with no code
change.

---

## 3. `activation.json`

```json
{
  "schema_version": 2,
  "activation_generation": 7,
  "pack": { "path": "pack/vscode.<d>.json", "sha256": "<64 hex>" },
  "intents": {
    "OPEN_FOLDER": {
      "intent": { "path": "intents/open_folder.<d>.json", "sha256": "<64 hex>" },
      "active_adoption_id": "<stable adoption id> | null",
      "adoptions": {
        "<stable adoption id>": {
          "recipe": { "path": "recipes/open_folder.<d>.json", "sha256": "<64 hex>" },
          "accepted_pack": { "path": "pack/vscode.<d>.json", "sha256": "<64 hex>" },
          "accepted_intent": { "path": "intents/open_folder.<d>.json", "sha256": "<64 hex>" },
          "accepted_application_identity": {
            "kind": "executable_version",
            "value": "1.134.0"
          },
          "evidence": { "path": "docs/evidence/<committed>.md", "sha256": "<64 hex>" },
          "adopted_at": "<ISO-8601 UTC>",
          "reviewer_id": "<repository-defined id>",
          "review_commit": "<40 hex>",
          "supersedes_adoption_id": "<stable adoption id> | null",
          "supersedes_recipe_sha256": "<64 hex> | null"
        }
      }
    }
  }
}
```

`schema_version`, `activation_generation`, `pack`, and `intents` are always
required. Each intent entry always binds one intent artifact and contains an
`adoptions` object keyed by a stable, unique adoption ID. Every adoption record
carries the complete acceptance facts for that immutable recipe. The recipe
reference's digest and the digest of the recipe's bytes must agree. Pack and
intent acceptance bindings are full path-plus-digest references too, so old
semantic inputs remain auditable without globbing or filename inference. An
active record's accepted pack and intent references must equal the currently
bound pack and intent artifacts. Editing a title matcher, alias, phrase, or rule
therefore invalidates the old acceptance rather than silently widening where the
recipe applies.

A **preserved** record is held to a different rule, and deliberately so. It
describes what was accepted *then*, so requiring it to equal today's binding
would erase the entire history on the next pack update — exactly the audit
D070's rollback check depends on. Its own referenced pack, intent, recipe, and
evidence artifacts must still resolve and verify against their recorded digests,
and its pack and intent must still be the ones this entry belongs to; a record
whose artifacts no longer verify is a diagnostic and is not rollback-eligible.

Because pack identity and aliases are global, changing the top-level pack
reference requires a fresh accepted adoption for **every intent that remains
active** in the same atomic activation swap. Per-intent phrase or rule changes
invalidate only that intent. This is the deliberate invalidation boundary that
motivated separate intent files.

`active_adoption_id` is the executable mapping. It is either `null` or the
key of one adoption record in the same entry. Therefore:

- **registered but never adopted** — active is `null`, adoptions is empty;
- **active** — active names one complete adoption record;
- **withdrawn** — active is `null`, prior adoption records remain;
- **superseded or rolled back** — active names the selected record and every
  predecessor remains available for audit and version-aware rollback.

This history is required, not decorative. A lone predecessor recipe digest on
the current recipe loses the predecessor's evidence and accepted application
version when `activation.json` is replaced, making D070's rollback check
impossible. History remains inside the manifest entry rather than a sidecar or
`knowledge.sqlite`, so deleting the future knowledge store cannot erase the
minimum audit record. A `planner_only` entry must have active `null` and an empty
adoptions object.

Adoption identity is deliberately separate from recipe identity. Identical
recipe bytes may be re-accepted against a new application identity, producing a
second record with the same recipe SHA-256 and different evidence and scope.
Keying history by recipe digest would overwrite the first acceptance and make
version-aware rollback impossible.

Every non-null `supersedes_adoption_id` must name another record in the same
intent entry, and `supersedes_recipe_sha256` must equal that predecessor's
recipe digest. Self-reference and cycles are invalid; first adoption alone uses
both fields as `null`. Adoption IDs are stable canonical identifiers unique
within the intent; they grant no authority outside the manifest bytes that bind
them. Review commits are lowercase 40-hex identifiers in this SHA-1
repository, recipe/evidence digests are lowercase 64-hex SHA-256, and timestamps
are UTC ISO-8601. The strict duplicate-key parser runs before these checks.

**Acceptance evidence is bound immutably.** `evidence` carries a path *and* the
document's SHA-256. A path alone names a mutable file and cannot prove which
bytes were reviewed — the same failure shape as an unbound recipe.
The document records the tested recipe, intent, and pack digests plus the exact
application identity, so it identifies the complete semantic input graph rather
than only the step payload.
`review_commit` is kept for provenance but is not the binding; verifying it
would require git at load time, whereas a digest is checkable from the artifacts
alone.

`reviewer_id` is a stable repository identity (the same class of identity used
for commit attribution), not an arbitrary display name or personal-data field
typed into JSON.

**`activation_generation` is an audit sequence, not authority.** It starts at
`1` and increments by exactly one on every adoption, supersession, rollback, or
withdrawal that changes `activation.json`. The loader rejects zero, negative,
and non-integer generations always.

**The sequence is checked against the bytes it describes.** When the loader has
a previous catalog to compare, it compares the previous activation digest too:
unchanged bytes must keep the same generation, because reloading one file is
not an audit event; changed bytes must carry exactly the previous generation
plus one. Rejecting only *decreasing* generations would be too weak — a
withdrawal that edits `activation.json` while reusing its old number is neither
decreasing nor a reload, and would pass unnoticed. A gap is rejected for the
same reason: it means an activation change happened that this loader never saw.

A generation may help cache invalidation and audit ordering, but only the digest
of the exact activation bytes binds content.

**Application identity scope is exact in v2.** The adoption record's kind must
equal the trusted pack's `version_identity.kind`, and its value must equal the
resolver's exact result. `executable_version` stores the exact observed version;
`content_sha256` stores the exact lowercase 64-hex module digest. Version ranges
and additional identity strategies need comparison and trust semantics of their
own and are deferred rather than half-specified.

**`unknown` cannot activate an executable recipe** — acceptance always happened
against a resolved application identity, so recording `unknown` would falsify
what was tested.

**Runtime behaviour is fail-closed.** If identity resolution returns `unknown`,
the strategy differs, or the resolved value does not equal the active record's
`accepted_application_identity.value`,
that intent is `KNOWN_INTENT_RECIPE_UNAVAILABLE`. It does not launch on the hope
that the recipe still fits, and it does not silently widen its own scope.

Acceptance, planning, pre-launch revalidation, and rollback all obtain this
value through the same pack-selected resolver. An acceptance document may
record the observed value, but may not supply or override it. This prevents two
identity paths from assigning different scopes to the same application build.

For **rollback**, the same equality applies: D070 permits repointing to an older
adoption only when that preserved record covers the current application identity.
Deliberately strict — the alternative makes an unversioned or loosely-scoped
entry a universal rollback target, which is how Open Folder's cross-version
degradation would return.

An invalid inactive history record is a loud registry diagnostic and that digest
is not rollback-eligible, but it does not disable a different, fully valid active
record. An invalid active record makes the intent
`KNOWN_INTENT_RECIPE_UNAVAILABLE`. This keeps fail-closed execution from turning
damage to an unused rollback artifact into an outage of the current workflow.

**Paths — three distinct rules, because three different kinds of file are named.**

*Artifact paths* (`pack`, `intent`, `recipe`) are **pack-relative**: forward
slashes, no `..`, no absolute paths, no symlinks, and must resolve **inside the
pack directory**.

*Evidence paths* are **repository-relative** and must resolve inside committed
`docs/evidence/`. They are deliberately outside the pack: acceptance evidence is
a reviewed document shared across packs and referenced by digest, not a pack
artifact. Applying the pack-containment rule to it would make the field
unsatisfiable.

*Content-identity paths* are **repository-relative** and must resolve inside the
allowlisted `ghostcursor/demo/` application-source root. They are read only to
derive the exact D073 identity of a checked-in application, never to load a
recipe or grant authority. They reject absolute paths, `..`, backslashes,
symlinks, missing files, and containment escape.

All roots are derived from the installed project/package location supplied to
the catalog, never from the process working directory. Any distributable build
must include every evidence document referenced by an active adoption and every
content-identity source named by an active pack; omission fails closed like a
local deletion.

**Digest prefix collisions are an install-time concern, not a load-time one.**
The loader resolves by exact path; installation extends the prefix rather than
overwriting when a filename already holds different bytes.

---

## 4. Verification and failure scoping

### Root index — all fail closed

| Condition | Result |
|---|---|
| `packs/index.json` missing or structurally invalid | no pack loads |
| index path is absolute, escapes the packs root, or resolves through a symlink | no pack loads |
| duplicate pack ID or duplicate pack directory | no pack loads |
| duplicate case-folded intent ID across packs | no pack loads |
| duplicate normalized exact phrase across intents | no pack loads |

Duplicate intent IDs make the registry ill-defined. Duplicate normalized exact
phrases are a static configuration defect: they guarantee ambiguity for that
entire phrase, so the catalog rejects them at load rather than waiting to return
`UNSUPPORTED_GOAL` for every user who says it. Heuristic collisions cannot be
enumerated statically and continue to use D072's runtime ambiguity rule.

Every index entry is a forward-slash path relative to `ghostcursor/packs/`: no
absolute path, no `..`, no symlink, and the resolved directory must remain under
that root. An unindexed pack directory is inert. For a newly installed pack,
its valid `activation.json` is written first and the atomic root-index swap is
the pack-discovery commit point; for an already indexed pack, the per-pack
`activation.json` swap remains the intent activation commit point.

### Per pack

| Condition | Result |
|---|---|
| `activation.json` structurally invalid | whole pack fails closed |
| pack digest mismatch | whole pack unavailable |
| `planner_only` pack with an active adoption or adoption history | whole pack fails closed |
| intent not indexed | `UNSUPPORTED_GOAL` |
| intent artifact invalid | excluded from matching + registry diagnostic |
| active adoption is `null`, missing, or has a recipe digest mismatch | `KNOWN_INTENT_RECIPE_UNAVAILABLE` |
| active adoption's accepted pack or intent digest differs from the current bound artifact | `KNOWN_INTENT_RECIPE_UNAVAILABLE` |
| acceptance evidence missing or digest mismatch | `KNOWN_INTENT_RECIPE_UNAVAILABLE` |
| accepted application identity missing, unknown, strategy-mismatched, or unequal to the pack-selected resolver | `KNOWN_INTENT_RECIPE_UNAVAILABLE` |
| inactive adoption record invalid | registry diagnostic; that digest cannot be rolled back to; valid active adoption remains available |

An unverifiable intent artifact cannot safely classify a goal, so it is excluded
from both deterministic matching and the model-visible `IntentSpec` registry;
the diagnostic names the indexed ID and validation failure. It is not treated as
a known match because its phrases cannot be trusted. No globbing, no filename
inference, no one-intent fallback. Unreferenced artifacts are inert.

---

## 5. The matcher — D072, carried verbatim

Intent artifacts carry `rules: []`. Grammar is fixed, nonrecursive, conjunctive
normal form at depth three:

```json
{
  "intent_id": "OPEN_FOLDER",
  "rules": [
    { "tier": "exact",
      "phrases": ["open a folder in vs code", "open a folder in vscode"] },
    { "tier": "heuristic",
      "all_of": [
        { "any_of": [ {"token": "open"} ] },
        { "any_of": [ {"alias": "vscode_names"} ] },
        { "any_of": [ {"token": "folder"}, {"path": true} ] }
      ] }
  ]
}
```

A heuristic rule is `all_of: [clause…]`; a clause is `any_of: [term…]`; a term is
exactly one of `{"token": …}`, `{"alias": …}`, `{"path": true}`. No recursion, no
fourth form, no negation.

- **Matching** is by normalized literal substring for tokens and alias members —
  not whole-word, not equality. `exact_phrase` matches by equality.
- **Literals are stored canonical** (lowercased, whitespace collapsed); the
  loader validates and rejects rather than normalizing, because artifacts are
  content-addressed and silent normalization would let two digests mean the same
  thing.
- **Non-empty after normalization** for every phrase, token, alias name, and
  **alias member**; every exact rule needs a phrase, every `all_of` a clause,
  every `any_of` a term, every alias group a member. An empty `all_of` is
  vacuously true and matches every goal; an empty `any_of` matches none; a
  whitespace-only alias member normalizes to the empty string, which is a
  substring of everything.
- **Two tiers only** — exact 0.95, heuristic 0.85. Confidence is a property of
  the tier; artifacts never declare a number.
- **Tier by tier, not intent by intent.** Every exact rule across all intents
  evaluates before any heuristic rule. Two different intents matching within a
  tier fail closed to `UNSUPPORTED_GOAL`.
- **Path predicate** recognizes Windows-shaped forms only: drive-rooted with
  either slash, UNC with two leading backslashes, relative backslash paths
  defined as non-whitespace segments joined by a backslash, and explicit
  `./ ../ .\ ..\`. A bare forward-slash pair is not a path.

Migration is gated by the D072 compatibility corpus: 86 rows, 14 divergences in
three declared classes, zero UNCLASSIFIED, zero v2 confidences outside
{0.0, 0.85, 0.95}.

---

## 6. Selectors

A recipe declares a top-level `selectors` block; steps and verification rules
reference entries by id. Every selector has exactly `strategy`, `control_type`,
`names`, `normalise`, `cardinality`, and `result_limit`. Selector IDs,
`control_type`, and names are non-empty; `names` is non-empty and
`result_limit` is a positive integer. `strategy` is exactly `provider_exact` or
`bounded_descendants`; there is no plugin or inferred third strategy.

```json
"selectors": {
  "extensions_tab": {
    "strategy": "provider_exact",
    "control_type": "TabItem",
    "names": ["Extensions (Ctrl+Shift+X)"],
    "normalise": "none",
    "cardinality": "exactly_one",
    "result_limit": 8
  }
}
```

- **Action targets must be `exactly_one`**, even when a verification rule
  references the same selector. Verification may be `at_least_one`. Enforced at
  schema level, not discovered at runtime.
- Every non-null step `target_selector` must resolve. Targeted actions require
  one; non-targeted actions may declare one when the hint intentionally points
  at an identifying control, as Open Terminal does for `press_keys`.
- Context selectors must use `at_least_one`; they observe state and never select
  a control for the user. The observation plan is the deduplicated union of all
  action, verification, and context selectors.
- **A v2 `provider_exact` selector must declare exactly one name.** Multi-name
  provider union identity is not yet measured, so the loader rejects a longer
  list. This restriction does not apply to `bounded_descendants`, whose names
  filter one already-shared traversal. A later measurement may relax the rule;
  v2 does not guess meanwhile.
- `provider_exact` requires `normalise: "none"`; provider conditions perform
  exact backend matching and have no normalization hook. `bounded_descendants`
  accepts `none` or `strip_leading_private_use`. The normalization affects
  matching only: the published `Element.name` remains the raw accessible name,
  preserving the screen-derived provenance measured in D069.
- **`result_limit` raises when exceeded; it never truncates.** It bounds trusted
  results, not traversal latency — `descendants()` completes before filtering.
  Silent truncation can hide a second match from `exactly_one`, which is the
  `uia.py:368` defect.
- **Selector required** for `element_appears`, `element_disappears`,
  `property_changes`. **No selector** for `window_title_matches`,
  `focus_moves_to`, `any_meaningful_change`, `user_confirms`.
- A recipe using `any_meaningful_change` must declare at least one
  `context_selector`; otherwise "meaningful" would mean only whichever action
  target happened to be published and would silently narrow the rule.

### `provider_exact` uses `FindAll`, never `FindFirst`

Measured on VS Code 1.134.0: `FindFirst` returns at most one element and cannot
detect a second, so it **cannot prove `exactly_one`**; on a genuine absence it
returns a non-`None` object whose property access raises `NULL COM pointer
access`. `FindAll` reports absence as `Length = 0` and counts correctly.

```
Length == 0  -> absent
Length == 1  -> read required properties; success = present;
                NULL COM pointer = clean absence; any other failure = fault
Length  > 1  -> SelectorAmbiguityFault for exactly_one
```

The same property-read classification applies during bounded traversal: a
control that dies before its properties are read is absent; any other read or
provider exception faults the whole selector and therefore the whole tick. No
strategy may flatten an unknown exception into an empty observation.

**`Extensions (Ctrl+Shift+X)` requires `control_type: "TabItem"`.** Without it
the query matches **two** elements — a `TabItem` and a `Group` spatially
contained within it, sharing the accessible name. `FindFirst` returned only the
first, which is why Spike B recorded this selector as unambiguous. With the
control type it resolves to one, measured 3/3.

`provider_exact` **cannot serve Open Folder**: `build_condition(title=…)` is an
exact match with no normalisation hook, so reaching that element through a
provider query would require writing the version-sensitive Codicon glyph into
the recipe.

### Observation plan — grouping is strategy-specific

- **`bounded_descendants`** — one traversal per unique `control_type` per tick;
  every selector of that control type evaluates over the shared result.
- **`provider_exact`** — one provider call per unique query. It performs no
  traversal, so grouping it by control type is meaningless.

Cardinality is evaluated **per selector, before** publishing the deduplicated
union. **Any non-absence selector fault invalidates the entire tick** — never
publish a partial observation. A clean absence is not a fault.

**Deduplication is worker-side only, while backend handles are live.** Shared
traversal candidates dedupe by backend candidate identity; provider results
dedupe only when a stable backend runtime identity proves the same control. If
identity is unavailable, retain both. **Never** dedupe by name, AutomationId,
bounds, or serialized `Element` equality — `Element` carries no backend identity
(D021), and nothing guarantees two distinct controls differ in the fields it
does carry.

`GetRuntimeId()` was measured stable across three consecutive calls within one
live observation session and distinguished two same-named controls. Stability
across ticks, worker generations, or a tree rebuild was **not** measured.

### Migration must not broaden certified behaviour

Open Terminal's walker accepts exactly `Toggle Panel (Ctrl+J)` and
`Terminal Section` — no synonym, no normalisation. Its v2 selectors use
`normalise: "none"`. Codicon normalisation was measured for Open Folder only.
The migration also preserves the existing promotion guard that rejects
positional AutomationIds matching `list_id_<number>_<number>`; selector
compilation must not create a route around that store boundary.

---

## 7. Goal-derived title verification

`run.py:630` currently hardcodes
`recipe.app_id == "code.exe" and rule.args.get("vscode_workspace_title")`. That
becomes a declarative `window_title_matches` contract. **Migration parity is the
constraint** — the current behaviour lives in
`ghostcursor/reasoning/vscode.py::verify_open_folder`, and v2 must reproduce it,
not approximate it.

### Verification gets its own title patterns

The verification rule declares its own normalized literal
`completion_title_suffixes`; it **must not** reuse the pack's `title_patterns`.
The list must be non-empty and every suffix must remain non-empty after
normalization.
The migrated Open Folder rule declares `visual studio code` and ` - code`, which
are exactly the two suffixes accepted by the current
`(?:visual studio code|\s-\s*code)$` check after whitespace normalization. This
avoids adding an author-controlled regular-expression language to recipes.

Those two serve different jobs. A pack's patterns are *window-discovery*
patterns — `.*Visual Studio Code.*` is deliberately broad, because it has to
find the window at all. The completion check today is
`is_valid_vscode_workspace_title()`, which tests a specific **suffix** pattern
on the normalized title. Substituting the discovery pattern would weaken
verification to "the window is still VS Code", which every failed run also
satisfies.

### The three conditions

1. the normalized title **must change** from the pre-action baseline;
2. the normalized new title **must end with** one of the rule's non-empty,
   normalized `completion_title_suffixes`;
3. if the derived reference is **specific**, the normalized new title **must
   contain** it.

### Reference extraction — the exact algorithm

The rule declares a `goal_reference` object using only compiler-owned generic
operations: `strip_leading_token`, `nonspecific_templates`,
`strip_trailing_alias_clause`, `basename_separators`, and `minimum_length`.
Its values bind the pack alias group and the literal words used by this intent;
the recipe supplies no executable pattern or plugin. The Open Folder declaration
reproduces `folder_reference_from_goal()` step for step:

```json
"goal_reference": {
  "strip_leading_token": "open",
  "alias": "vscode_names",
  "nonspecific_templates": ["a folder in {alias}", "folder in {alias}"],
  "strip_trailing_alias_clause": { "preposition": "in" },
  "basename_separators": ["/", "\\"],
  "minimum_length": 2
}
```

`{alias}` is the only template placeholder and expands to one normalized member
of the named pack alias group. All other values are non-empty normalized
lowercase literals validated under D072's literal rules. All fields shown are
required, extra fields are rejected, and `minimum_length` is an integer of at
least 2.

The compiler implements the strip operations by escaping configured literals
and comparing words case-insensitively with flexible whitespace; recipe data is
never interpreted as a regular expression. Transformations apply to the
original remainder so separator splitting preserves punctuation, and only the
final value is normalized. This is what makes goals with repeated spaces match
the current verifier without opening a regex extension point.

1. strip surrounding whitespace;
2. remove a leading `open` word boundary, case-insensitively;
3. remove a **whole-remainder** match of
   `(?:a\s+)?folder\s+in\s+<alias>\s*$`;
4. remove a **trailing** match of `\s+in\s+<alias>\s*$`;
5. **if the remainder contains `\` or `/` anywhere**, split on `[\/]+` and
   keep the last non-empty segment;
6. normalize.

A reference is **specific** only when it is **≥ 2 characters**. Shorter or empty
references are nonspecific and condition 3 does not apply — `.` appears in
ordinary titles and must not self-satisfy.

**Step 5 deliberately uses bare separator containment, not D072's path
predicate.** An earlier draft of this spec said the matcher and verifier share
one path definition. That is wrong for parity: D072's predicate rejects a bare
forward slash, so `open my folder a/b in vs code` — which still grounds under
v2 through its `folder` token — would yield the reference `my folder a/b`
instead of today's `b`, silently changing what gets verified. The two predicates
answer different questions: D072 asks *is this goal about a path*, and step 5
asks *does this reference have a final segment*. They are allowed to differ, and
here they must.

The extractor result is computed once during planning and carried on
`CompiledWorkflow`; verification does not reinterpret the goal with a second
implementation.

## 8. Modules and runtime integration

```
packs/index.json ─┐
pack.<d>.json     ├─→ trusted.py ──→ activation.py ──→ compile_planner()
intents/*.json    │   (load + verify   (verify the      compile_observation_plan()
recipes/*.json    ┘    one artifact)    bound graph)          ↓
activation.json                                        CompiledWorkflow
```

- **`packs/trusted.py`** — the single trust-boundary module. Its artifact loader
  enforces pack-relative paths; its evidence loader enforces repository-relative
  containment under committed `docs/evidence/`. Both enforce no symlink, exact
  digest, UTF-8 without BOM, and read bytes once before hashing and parsing.
  Pack, intent, and recipe additionally receive strict schema and cross-file id
  validation, so the validated bytes are provably the compiled bytes.
- **`packs/activation.py`** — reads each mutable authority file (`index.json` and
  `activation.json`) once, hashes and parses those same bytes, verifies the
  complete bound graph, and applies the failure scoping in §4. It knows nothing
  about planners or walkers.
- **`packs/compile.py`** — pure functions over a verified pack:
  `compile_planner()` produces `IntentSpec`s, replacing `registry()` and
  emitting specs for every valid indexed intent, including inactive ones;
  `compile_observation_plan()` produces the bounded plan replacing
  `perception_walker_for()`'s branches.
- **`CompiledWorkflow`** replaces the bare `Recipe` on `PlanResult`, carrying
  verified pack identity, intent, recipe, observation plan, every bound artifact
  digest, **the full digest of `activation.json` itself, the full digest of
  `packs/index.json`, the bound acceptance-evidence digest, the exact accepted
  application identity kind/value, the activation generation, and the bound
  target HWND plus `AppInfo` identity. Required because recipe `app_id`
  is **removed** — activation already binds a recipe to exactly one pack and
  intent, so restating identity inside the artifact creates a second source that
  can disagree. Runtime still needs the executable filter for
  `perception_hwnd_source_for()` and `tier2_capture_for()`; that now comes from
  the pack's `executable_names`, which is where D046's executable-bounded
  identity already lives.
- **`PackRegistry`** consumes verified pack identities and performs **no
  independent scanning or loading**. Its `recipe_for_intent()`,
  `recipe_paths()`, and one-intent fallback are deleted; window matching for
  `daemon.py` remains.

### Planning and materialization are separate authority stages

Classification is pure: deterministic and model-advisory matching select an
intent from verified intent artifacts. It does not load a recipe. Materializing
that selected intent then requires its active adoption plus a trusted live
application context.

For an application pack, the production resolver returns a `TargetContext`
containing the chosen HWND, `AppInfo`, and pack-resolved application identity.
The window must match the verified
pack's executable name **and** title pattern; an optional user `--target` may
narrow the title set but can never replace the executable check. The chosen HWND
is captured, not rediscovered by title later. Resolution is deterministic:
filter by pack identity, apply optional title narrowing, choose the foreground
window if it is in the remaining set, otherwise require exactly one. No matching
window, more than one non-foreground candidate, unresolved application
identity, or an exact identity mismatch yields
`KNOWN_INTENT_RECIPE_UNAVAILABLE` and no `CompiledWorkflow`.

`CompiledWorkflow` therefore also carries the chosen target HWND, executable
identity, `AppInfo` snapshot, and resolved application identity kind/value.
Hermetic planner/model tests inject a fake trusted resolver; production callers
cannot supply an identity value directly.
The model remains advice only: it can select only an indexed intent, and an
active adoption materializes only when the deterministic authority policy and
live application checks allow it.

Production guided-tour execution accepts a `CompiledWorkflow`, not a recipe
path. `--goal` and Ask pass the exact object returned by planning directly into
the tour; they never call a second `recipe_path_for()` lookup. The production
`--recipe <path>` option is removed. A path-based candidate loader exists only
inside the developer acceptance harness constrained by D070 and is unreachable
from the production parser, planning, Ask, and `run_tour` entry points. The
non-recipe raw overlay mode is unaffected because it grants no workflow
authority.

### Pre-launch revalidation

Immediately before tour launch, reload and revalidate **all** of:

1. the `packs/index.json` digest, **and that the index still names this pack** —
   a withdrawn pack must abort a launch, not merely fail later;
2. the `activation.json` digest;
3. every bound artifact digest — pack, intent, recipe — and the bound committed
   acceptance-evidence digest;
4. the activation generation;
5. the current value from the trusted pack's `version_identity` resolver, which
   must still exactly equal the accepted kind/value carried by the plan;
6. the recorded HWND still exists, still belongs to the recorded process and
   executable, and still satisfies the verified pack title identity.

**The generation is not content binding.** It is a counter, and a counter can
stay put while the file it labels changes — an edited digest, a changed
acceptance record, a removed entry. Revalidating the generation alone would let
activation metadata change under a running plan. The digests are what bind
content; the generation is a cheap ordering hint kept alongside them, not a
substitute.

On any change: **abort before overlay creation**, do not substitute new
artifacts transparently, do not execute the old in-memory workflow, and require
a fresh plan or Ask submission.

The manifest mapping is the activation commit point. No cache is assumed; any
future cache must invalidate synchronously on adoption, withdrawal, or
supersession or rollback, and may never serve an inactive mapping. Revalidation happens at
activation and launch — **not on every perception tick**.

### Fail-closed behaviour, including after a crash mid-adoption

- active adoption names a missing recipe, or the digest mismatches →
  `KNOWN_INTENT_RECIPE_UNAVAILABLE` (the existing status; no new one)
- an installed artifact with no manifest reference → **inert orphan**
- registry or cache failure → **no new workflow launch**

---

## 9. Migration scope

Three packs, four pack recipes, two legacy recipes. Atomic: all migrate to a
single root, and `ghostcursor/reasoning/recipes/` is deleted along with the
`planner.py:231-232` special case that exists only to paper over its duplication.
No v1 loader, no `schema_version` dual path.

The implementation may land the v2 parser/compiler and candidate harness while
production still runs only v1, because candidates must be accepted before they
can be activated. It may **not** expose both v1 and v2 as production authority.
After the three migrated candidates have committed evidence, one cutover commit
installs their content-addressed artifacts, activates them, switches every
production caller to the v2 catalog, and deletes every v1 loader and root. At
each commit there is one production authority path, never a compatibility
fallback chosen from file contents.

The `uia.py:368` `result_limit` truncation defect is fixed as part of this work.

### Adoption sequence

D070 requires acceptance evidence committed **before** installation and
activation, so no workflow can be drafted, accepted, evidenced, installed, and
activated in one commit. Every executable workflow follows:

1. quarantined candidate;
2. acceptance run against a **developer-only candidate harness** — unreachable
   from production planning, the CLI goal path, and Ask; loads exactly one named
   quarantined recipe digest together with explicitly named pack and intent
   digests; performs **no scanning, fallback, or input synthesis**. It is an
   acceptance instrument, never a second authority path;
3. committed acceptance evidence recording the full tested pack, intent, and
   recipe digests plus the exact pack-resolved application identity;
4. content-addressed installation of the accepted pack, intent, and recipe
   bytes, each re-read and re-hashed;
5. append the complete adoption record and atomically swap `activation.json`,
   pointing `active_adoption_id` at that exact accepted record while
   retaining every previous record and artifact for rollback.

Quarantined candidates live outside `ghostcursor/packs/` and are named
explicitly by full digest. Merely committing a candidate does not make it
discoverable by `packs/index.json` or production planning.

Supersession performs the same sequence and records the predecessor digest.
Withdrawal atomically sets `active_adoption_id` to `null` without deleting
the intent, adoption history, evidence, or artifacts. Rollback is another atomic
activation change: it may point at a preserved record only after that record's
recipe, evidence, and exact application-identity scope revalidate. Each operation
increments `activation_generation`; none rewrites immutable artifacts.

Artifact identity does not replace learned-step identity. Compilation passes the
recipe's stable `step_key_namespace` into D016's existing `step_key()` with the
claimed name, OCR text, and visual description; it never substitutes the new
intent ID or includes recipe digest, selector ID, file path, or step index. A
trivial supersession therefore keeps applicable observations, a real descriptor
or namespace change creates a new key, and rollback behaves like the original
accepted recipe.

**The proof is the entire diff from the compiler baseline through adopted Open
Extensions containing no workflow-specific Python** — not a single commit's
diff.

**Acceptance is 12 runs**: Synthetic Export, Open Folder, Open Terminal, and
Open Extensions, 3/3 each. All four receive new artifact bytes, so D070 requires
fresh acceptance for each unless a separate decision grants migration parity.
Open Folder's gate must assert **UIA provenance**, not merely that the workflow
completed — fallback OCR preserves the outcome while the preferred tier is dark.

---

## 10. Testing

Hermetic tests carry the weight; every unit above is pure or fake-driven.

- Each root-index and per-pack failure row in §4 gets a test, mutation-verified
  per D018.
- A `planner_only` pack with any active adoption or adoption history fails closed.
- Strict schema tests cover every required/unknown field, duplicate JSON object
  keys, cross-file ID mismatch, path escape, symlink, digest mismatch, and the
  strategy-specific selector constraints.
- Adoption-history tests cover first adoption, supersession, withdrawal,
  identity-valid rollback, identity-invalid rollback, and a corrupt inactive
  record that cannot be selected but does not disable a valid active record.
- Planner integration tests prove classification alone never loads a recipe;
  materialization requires a pack-matched HWND and exact pack-resolved
  application identity; and
  pre-launch changes to the index, activation, evidence, artifact, process,
  HWND, or resolved application identity abort before overlay creation.
- The production parser has no `--recipe` path, `run_tour` rejects bare recipe
  paths, and CLI/Ask consume the original `CompiledWorkflow` without a second
  registry lookup. The only path-based recipe loader is the isolated candidate
  harness.
- Recipe compilation preserves mandatory step provenance and D016 `step_key()`
  identity across digest-only supersession and rollback.
- Existing positional-AutomationId rejection and the dead-pointer/other-fault
  split remain mutation-covered through both selector strategies.
- The loader rejects a BOM; `.gitattributes` LF enforcement is tested.
- Both legacy recipe paths and every v1 loader and fallback are gone — asserted,
  not assumed.
- The D072 differential corpus runs as a gate: agreement on intent **and**
  confidence, each divergence in a declared class with the stated outcome, zero
  UNCLASSIFIED.
- That gate reads a committed machine-readable fixture under `tests/data/`, not
  ignored `.artifacts/` and not a second hand-written matcher. A consistency
  check proves its 86 goals, expected outcomes, and divergence classes agree
  with the full table in the committed D072 evidence document.
- `result_limit` raises rather than truncating, including at limits small enough
  that truncation would hide a second match.
- The frozen three-lane model gate runs because planner, parser, and schema
  contracts change. It must retain the two matching baseline passes and the
  never-fabricate guarantee; model advice still cannot alter executed recipe
  authority (D068).
- The live eight-cell never-fabricate matrix runs independently of the frozen
  corpus. The corpus preserves matcher expectations; it is not a substitute for
  exercising the live planner/model boundary.
- Existing interactive, pixel, isolated hung-window, and standalone pixel
  harnesses pass, together with the synthetic wrong-action regression.
- The four real workflows complete the **12 acceptance runs** in §9, including
  Open Folder's UIA-provenance assertion.
- The repository records a mechanical diff check from the compiler baseline
  through adopted Open Extensions proving that no workflow-specific change
  under `ghostcursor/**/*.py` was required for that workflow.

---

## 11. Deferred measurements and fixed v2 behaviour

- **Multi-name union cardinality** across two different names resolving to one
  control is unmeasured. Therefore v2 rejects multi-name `provider_exact`
  selectors. `bounded_descendants` continues to allow multiple names because it
  filters them after one walk and does not union provider queries.
- **A cold Chromium tree reports zero for every query.** An observation plan run
  once against a cold window sees an empty screen, which the presence rule alone
  cannot distinguish from a clean absence. v2 preserves D035's existing
  per-HWND two-second `WarmUp` and grounding grace: a clean zero during that
  interval neither becomes a provider fault nor triggers immediate OCR. The
  observation plan may not weaken or bypass that behaviour. Distinguishing a
  persistently cold tree from genuine absence remains follow-up work.
- **Rung 3 versus rung 2 for Open Folder** remains triggered follow-up work, not
  a migration choice. v2 preserves the certified migration's raw published UIA
  name, normalised selector matching, and current grounding ladder, including
  its present rung. Moving it to rung 2 requires its own evidence and gate; the
  compiler does not broaden the global ladder while migrating it.

---

## 12. Independent review — Step 4

Reviewed on 2026-08-27 by Codex, independently of the Claude authoring session,
against D069, D070, D072, the three cited evidence documents, and the live
contracts in `schema.py`, `planner.py`, `packs/registry.py`, `run.py`,
`verification.py`, `vscode.py`, `uia.py`, and the four v1 pack recipes.

The first pass rejected the draft rather than approving around gaps. Corrections
made before approval:

1. adoption history now preserves complete pack, intent, recipe, evidence, and
   exact application-identity facts; withdrawal and rollback are representable;
2. adoption identity is distinct from recipe digest, so unchanged bytes can be
   re-accepted for a new application identity without overwriting history;
3. all schema-v2 JSON contracts and their cross-file constraints are explicit,
   including duplicate-key rejection, provenance, selector references, and
   stable D016 `step_key_namespace` migration;
4. production `--recipe` and `run_tour(recipe_path)` are removed as a second
   authority path; CLI and Ask carry one verified `CompiledWorkflow`;
5. planning binds a deterministic target HWND and the same pack-selected
   application-identity resolver used at pre-launch, with all changes aborting
   before overlay creation;
6. Synthetic Export's disabled OCR policy and explicit context selectors preserve
   v1 behavior rather than inheriting broader VS Code behavior from the compiler;
7. D069's dead-pointer/other-fault split, positional-ID guard, raw-name
   provenance, and fixed safe behavior for unmeasured provider unions and cold
   trees are explicit and testable.

**Verdict: approved for Step 5.** The remaining items in §11 have fixed safe v2
behavior and do not require implementation-time design choices. This review
approves a plan to implement the contract; it does not approve any code or waive
the later acceptance gates.

---

## 13. D073 amendment from implementation-plan review

The independent implementation-plan review found that the approved draft used
`AppInfo.version` for every application pack. That is meaningful for VS Code but
wrong-shaped for Synthetic Export: its matched executable is `python.exe`, so an
interpreter patch would invalidate acceptance while not directly identifying a
change to the checked-in demo UI.

D073 corrects the schema and runtime contract before implementation:
`version_identity` is explicit and closed; VS Code uses
`executable_version`; Synthetic uses the SHA-256 of
`ghostcursor/demo/synthetic_export_app.py`; every authority stage resolves and
compares the same kind/value. This is a substantive amendment and requires
independent re-review. No implementation may start on the strength of §12's
earlier verdict alone.
