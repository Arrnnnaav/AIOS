# Declarative Workflow Compiler Implementation Plan

Date: 2026-08-27
Status: **draft, pending independent review before implementation**

**Goal:** Replace GhostCursor's hardcoded planner registry and workflow-specific
UIA walkers with one manifest-authorized schema-v2 compiler, migrate the three
executable workflows without weakening their certified behavior, and prove the
next workflow—Open Extensions—requires data and acceptance evidence but no
workflow-specific Python.

**Architecture:** Immutable content-addressed pack, intent, and recipe artifacts
are named by per-pack `activation.json` files, themselves discovered only through
`packs/index.json`. Strict loaders verify bytes, paths, schemas, IDs, digests,
acceptance history, evidence, and exact application version before pure compiler
functions produce planner intent specs and bounded observation plans. Planning
selects an intent first, then materializes one target-bound `CompiledWorkflow`;
the CLI, Ask, and guided tour carry that same verified object without a second
recipe lookup. Candidate acceptance is a developer-only, no-input-synthesis path
outside production authority.

**Tech stack:** Python 3.12, JSON, SHA-256, pywin32/pywinauto UI Automation,
pytest, the existing SQLite observation store, and the existing bounded Ollama
transport. No new runtime dependency.

**Design:**
`docs/superpowers/specs/2026-08-27-declarative-workflow-compiler-design.md`

**Decisions and evidence:** D016, D017, D018, D021, D030–D035, D040, D046,
D058, D062–D072; `docs/evidence/provider-findall-spike.md`;
`docs/evidence/d072-compatibility-corpus.md`;
`docs/evidence/workflow3-uia-feasibility.md`.

## Global constraints

- D070 is the authority boundary. A production workflow requires an indexed
  pack, a valid activation entry, immutable bound artifacts, valid committed
  evidence, and exact live application-version agreement. No subset suffices.
- Never glob for packs, intents, or recipes; never infer authority from a
  filename, directory membership, or a one-intent fallback. Unreferenced files
  are inert.
- There is never a dual production loader. New v2 modules and the isolated
  candidate harness may coexist with v1 during development, but production
  remains v1 until one atomic cutover replaces it and deletes every v1 path.
- Production exposes no `--recipe` option and accepts no bare recipe path after
  cutover. CLI and Ask pass the same `CompiledWorkflow` returned by planning.
- The model is advice, never authority. It may name only an indexed intent and
  cannot alter artifact selection, selectors, steps, verification, target HWND,
  or acceptance scope.
- No input synthesis is introduced. The candidate harness observes and guides;
  a human performs every acceptance action.
- Preserve D016 identity. Migrated recipes retain their v1
  `step_key_namespace`; artifact digest, selector ID, path, and step index never
  enter `step_key()`.
- Preserve D069: action selectors are `EXACTLY_ONE`; verification/context may be
  `AT_LEAST_ONE`; presence requires a successful property read; positional
  AutomationIds never promote; raw accessible names remain provenance.
- A selector fault invalidates the whole tick. Clean absence is not a fault.
  `result_limit` raises and never truncates.
- Candidate acceptance, evidence, installation, and activation are distinct
  stages. Evidence is committed before the accepted bytes enter trusted roots.
- Mutation-verify every safety invariant under D018. A test that still passes
  after deleting the guard does not close a task.
- Never run two test sessions concurrently. Hung-window lanes run alone.
- Commit each task after its focused and hermetic gates pass. Do not push or
  begin the next review-gated phase until the preceding diff is reviewed.

## Planned file ownership

| File | Responsibility |
|---|---|
| `.gitattributes` | LF policy for every digest-bound JSON/Markdown artifact |
| `ghostcursor/packs/trusted.py` *(new)* | One-read raw-byte loading, SHA-256, BOM/encoding, path, symlink, duplicate-key, and strict artifact schema validation |
| `ghostcursor/packs/activation.py` *(new)* | Root index and activation graph validation, adoption history, failure scoping, diagnostics, immutable verified catalog types |
| `ghostcursor/packs/compile.py` *(new)* | Pure D072 matcher compilation and pure recipe-to-observation-plan compilation |
| `ghostcursor/packs/registry.py` | Window matching over verified pack identities only; old scanning and recipe inference deleted at cutover |
| `ghostcursor/reasoning/schema.py` | Schema-v2 runtime recipe/selector structures and `CompiledWorkflow` boundary types |
| `ghostcursor/reasoning/planner.py` | Classification, model-advisory selection, target materialization, and `PlanResult` carrying `CompiledWorkflow` |
| `ghostcursor/perception/uia.py` | `FindAll` provider queries, ambiguity-safe bounded selection, worker-side backend identity handling |
| `ghostcursor/perception/service.py` | Execute compiled observation plans as one all-or-nothing tick |
| `ghostcursor/reasoning/verification.py` | Selector-referenced verification and declarative goal-derived title contract |
| `ghostcursor/run.py` | Consume one target-bound `CompiledWorkflow`; pre-launch revalidation; no direct recipe authority |
| `ghostcursor/daemon.py` | Consume verified pack window identities only |
| `ghostcursor/devtools/candidate_acceptance.py` *(new)* | Developer-only exact-graph candidate harness, unreachable from production parser/Ask |
| `tests/data/d072_compatibility_v1.json` *(new)* | Committed machine-readable form of the reviewed 86-row D072 corpus |
| `docs/superpowers/candidates/declarative-workflow-compiler/` *(new)* | Quarantined candidate artifacts, outside trusted roots |
| `ghostcursor/packs/index.json` and pack directories | Installed v2 catalog and activation authority after cutover |

---

### Task 1: Strict raw-byte artifact loading

**Files:**

- Create: `ghostcursor/packs/trusted.py`
- Create: `tests/test_trusted_artifacts.py`
- Modify: `.gitattributes`

**Produces:** `ArtifactRef`, immutable loaded pack/intent/recipe values, and
`load_trusted_artifact(root, ref, schema)` that validates the exact bytes it
hashes.

**Property:** validated values are derived from exactly the bytes attested by
the manifest.

**Invariant:** read once as bytes; reject BOM/non-UTF-8, duplicate keys, unknown
or missing fields, wrong schema version, noncanonical literals, invalid regex,
absolute/parent/backslash paths, symlinks, containment escape, and digest
mismatch before returning a value.

- [ ] Add `.gitattributes` rules that pin trusted JSON, candidate JSON, and
  committed acceptance/evidence Markdown to LF. Do not claim it enforces BOM;
  the loader and tests own that rule.
- [ ] Write failing tests for the complete index, pack, intent, recipe,
  selector, step, provenance, verification, and artifact-reference contracts in
  Design §§2–6.
- [ ] Include a duplicate-object-key fixture. Standard `json.loads()`
  last-write-wins behavior must never reach validation.
- [ ] Test exact 64-lowercase-hex digest comparison. Filename digest prefixes
  are never parsed.
- [ ] Test the two path roots separately: pack-relative immutable artifacts and
  repository-relative committed evidence.
- [ ] Test case-folded uniqueness and canonical values without silently
  normalizing invalid input.
- [ ] Implement the smallest loader that makes the tests pass. Do not connect it
  to production or `PackRegistry` yet.
- [ ] Mutation-check at least digest comparison, symlink rejection, duplicate
  key rejection, unknown-field rejection, and same-bytes hash/parse behavior.
- [ ] Run:

```powershell
py -3.12 -m pytest tests\test_trusted_artifacts.py -q `
  --basetemp=.tmp\pytest-trusted -p no:cacheprovider
py -3.12 -m pytest tests -m "not interactive and not pixel and not hung" `
  --basetemp=.tmp\pytest-hermetic -p no:cacheprovider
```

- [ ] Commit: `feat: add strict trusted artifact loader`

---

### Task 2: Root index, activation graph, and adoption history

**Files:**

- Create: `ghostcursor/packs/activation.py`
- Create: `tests/test_activation.py`
- Extend: `tests/test_trusted_artifacts.py`

**Produces:** `load_catalog(project_root) -> VerifiedCatalog`, per-pack
diagnostics, valid inactive intent specs, and version-eligible active adoption
records.

**Property:** only one complete, historically auditable activation graph can
authorize each executable intent.

**Invariant:** `packs/index.json` is the discovery commit point and each
`active_adoption_id` is the per-intent execution commit point. Full pack,
intent, recipe, evidence, version, reviewer, timestamp, review commit, and
predecessor facts remain in `activation.json` after supersession, withdrawal,
or rollback.

- [ ] Write root-failure tests: missing/invalid index, duplicate pack ID,
  duplicate resolved directory, duplicate intent ID, and duplicate normalized
  exact phrase all load no packs.
- [ ] Write per-pack failure tests for every Design §4 row, including the
  distinction between invalid active and invalid inactive adoption records.
- [ ] Test `planner_only`: no executables, titles, aliases, OCR, active adoption,
  or history; its valid intents remain model-visible but unavailable.
- [ ] Test adoption lifecycle: first adoption, same recipe reaccepted for a new
  version under a distinct adoption ID, supersession, withdrawal,
  version-valid rollback, and version-invalid rollback.
- [ ] Test predecessor ID/digest agreement, no cycles/self-reference, exact
  version only, evidence digest/root, and active accepted pack/intent refs equal
  current refs.
- [ ] Test global pack changes invalidate every still-active intent while an
  intent-only change invalidates only that intent.
- [ ] Treat `activation_generation` as a checked monotonic audit field, never as
  content authority.
- [ ] Implement immutable verified catalog/domain types. Keep planner and UIA
  imports out of this module.
- [ ] Mutation-check active-ID lookup, semantic digest binding, evidence digest,
  version equality, and inactive-history scoping.
- [ ] Run focused tests and the hermetic lane.
- [ ] Commit: `feat: verify manifest activation history`

---

### Task 3: Compile and differential-test the D072 matcher

**Files:**

- Create: `ghostcursor/packs/compile.py`
- Create: `tests/test_compiled_matcher.py`
- Create: `tests/data/d072_compatibility_v1.json`
- Modify: `tests/test_planner.py`

**Produces:** pure `compile_planner(catalog) -> tuple[IntentSpec, ...]` and a
pure deterministic classifier implementing D072's two-tier fixed-depth grammar.

**Property:** intent registration and deterministic goal matching come entirely
from verified artifacts while preserving every non-allowlisted v1 result.

**Invariant:** exact tier 0.95 is evaluated across all intents before heuristic
tier 0.85; multiple rules for one intent deduplicate; multiple intents in one
tier return `UNSUPPORTED_GOAL`; artifacts cannot declare confidence, negation,
recursion, or matcher plugins.

- [ ] Transcribe the reviewed 86-row corpus into committed JSON with goal,
  v1/v2 intent, confidence, kind, divergence class, and D072 reason.
- [ ] Add a consistency test that parses the full table in
  `docs/evidence/d072-compatibility-corpus.md` and proves the fixture has the
  same 86 goals, 14 divergences, and 5/3/6 class distribution. Do not maintain a
  second handwritten expectation set.
- [ ] Add deterministic bounded generation from each declared exact phrase and
  heuristic clause product.
- [ ] Implement normalized literal-substring token/alias matching and the
  tightened Windows-shaped path predicate exactly as D072 specifies.
- [ ] Prove the 30 frozen dataset rows agree, every non-allowlisted corpus row
  agrees with `_fallback()`, all divergence rows land in a declared class, no
  row is `UNCLASSIFIED`, and confidence is only 0.0/0.85/0.95.
- [ ] Test common-pack inactive intents are emitted as `IntentSpec`s without
  deterministic rules or recipe authority.
- [ ] Keep `_fallback()` as the production matcher until Task 9's atomic
  cutover. Tests may compare old and new; production may not choose between them.
- [ ] Mutation-check tier ordering, cross-intent ambiguity, alias lookup failure,
  path tightening, and confidence constants.
- [ ] Run focused tests, frozen dataset tests, planner tests, and hermetic.
- [ ] Commit: `feat: compile declarative intent matching`

---

### Task 4: Compile bounded observation plans

**Files:**

- Modify: `ghostcursor/reasoning/schema.py`
- Modify: `ghostcursor/perception/uia.py`
- Modify: `ghostcursor/perception/service.py`
- Modify: `ghostcursor/reasoning/verification.py`
- Extend: `ghostcursor/packs/compile.py`
- Create: `tests/test_observation_compiler.py`
- Modify: `tests/test_provider_query.py`
- Modify: `tests/test_bounded_descendants.py`
- Modify: `tests/test_perception_service.py`
- Modify: `tests/test_verification.py`
- Modify: `tests/test_positional_ids.py`

**Produces:** `CompiledRecipe`, named selectors, context selectors,
`ObservationPlan`, and `compile_observation_plan(recipe)`.

**Property:** a recipe declares every UI element needed by action, verification,
and wrong-action observation; one bounded worker tick observes that union without
workflow-specific Python.

**Invariant:** cardinality is evaluated per selector before publication;
non-absence failure invalidates the whole tick; candidate deduplication uses live
backend identity worker-side and never serialized value equality.

- [ ] Add schema/reference tests for selector fields, action/verification/context
  cardinality, unused or missing selector IDs, strategy-specific normalization,
  one-name `provider_exact`, and positive `result_limit`.
- [ ] Implement provider `FindAll`; never use `FindFirst`. Zero is absence, one
  requires successful property reads, and more than one faults an exactly-one
  selector.
- [ ] Preserve D069's `NULL COM pointer -> absence; every other provider/read
  failure -> fault` split for both provider and bounded strategies.
- [ ] Fix `bounded_descendants` so `result_limit` raises after filtering instead
  of truncating at `uia.py:368`; add a limit-one/two-match regression that fails
  if ambiguity is hidden.
- [ ] Group bounded traversal once per unique control type per tick. Evaluate
  each selector independently over the shared candidates. Provider queries group
  only by identical full query.
- [ ] Deduplicate bounded results by backend candidate identity while handles are
  live. Provider results deduplicate only when stable runtime identity proves
  equality; otherwise retain both.
- [ ] Publish raw accessible names even when matching strips a leading private-use
  glyph.
- [ ] Preserve the positional AutomationId rejection at compiler, promotion,
  and store boundaries.
- [ ] Compile selector-backed `element_appears`, `element_disappears`, and
  `property_changes`; preserve no-selector verification kinds.
- [ ] Preserve current v1 production walkers until Task 9. The compiled plan is
  exercised through tests and the candidate harness only.
- [ ] Mutation-check truncation, partial-tick publication, value-based dedupe,
  pointer-only presence, and positional promotion.
- [ ] Run all focused UIA/service/verification tests and hermetic.
- [ ] Commit: `feat: compile bounded observation plans`

---

### Task 5: Bind compiled workflows to one live target

**Files:**

- Modify: `ghostcursor/reasoning/schema.py`
- Modify: `ghostcursor/reasoning/planner.py`
- Modify: `ghostcursor/reasoning/verification.py`
- Modify: `ghostcursor/run.py`
- Modify: `ghostcursor/packs/registry.py`
- Create: `tests/test_compiled_workflow.py`
- Modify: `tests/test_planner.py`
- Modify: `tests/test_run.py`

**Produces:** `TargetContext`, `CompiledWorkflow`, pure classification followed
by trusted materialization, and pre-launch revalidation.

**Property:** the workflow planned, accepted, launched, perceived, and verified
is the same immutable graph against the same application window/version.

**Invariant:** materialization captures one HWND and `AppInfo`; before overlay
creation runtime rechecks index, activation, all artifact/evidence digests,
generation, process, executable, title identity, HWND existence, and exact
version. Any change aborts; runtime never substitutes either old or new bytes.

- [ ] Separate intent classification from recipe materialization. Classification
  must not load a recipe.
- [ ] Implement deterministic target resolution: verified executable plus title,
  optional `--target` narrowing, foreground preference, otherwise exactly one.
- [ ] Return `KNOWN_INTENT_RECIPE_UNAVAILABLE` for no target, ambiguous target,
  unknown version, version mismatch, inactive adoption, or graph failure.
- [ ] Inject the resolver in hermetic/model tests; production callers cannot
  supply an application version.
- [ ] Implement generic goal-reference derivation and declarative
  `window_title_matches` exactly as Design §7. Add parity tests for both current
  VS Code title suffixes and nonspecific `open a folder in VS Code`.
- [ ] Add explicit pack `tier2_capture`; Synthetic Export is `disabled`, VS Code
  is executable-bounded, planner-only is disabled.
- [ ] Add pre-launch mutation tests for each bound input and ensure overlay
  creation is never reached on failure.
- [ ] Define the production-facing `run_tour(compiled_workflow, ...)` API in
  tests, but do not switch the parser or remove v1 authority until Task 9.
- [ ] Mutation-check HWND reuse/process change, title-only matching, unknown
  version, and transparent artifact substitution.
- [ ] Run focused planner/run/title tests and hermetic.
- [ ] Commit: `feat: bind compiled workflows to live targets`

---

### Task 6: Build the isolated candidate acceptance harness

**Files:**

- Create: `ghostcursor/devtools/__init__.py`
- Create: `ghostcursor/devtools/candidate_acceptance.py`
- Create: `tests/test_candidate_acceptance.py`
- Modify: `tests/test_no_input_synthesis.py`

**Produces:** a developer command accepting explicit candidate pack, intent,
recipe paths and full SHA-256 values, plus expected app version and target.

**Property:** humans can test exact quarantined bytes before those bytes gain
production authority.

**Invariant:** the harness loads exactly one explicit pack-intent-recipe graph,
does not scan trusted roots, is absent from the production parser and Ask, cannot
write `activation.json`, and imports/calls no input-synthesis API.

- [ ] Write negative tests for missing digest, digest mismatch, unexpected file,
  glob/directory input, model-selected intent, activation write, and production
  parser reachability.
- [ ] Require exact `AppInfo.version` from the observed target, not an operator
  override. A command-line expected version may assert equality but never supply
  identity.
- [ ] Reuse `CompiledWorkflow` and the production observation/tour path after
  exact candidate verification. Do not implement a second compiler.
- [ ] Emit a run record containing all three digests, app identity/version,
  outcome, and UIA/OCR provenance; raw logs remain under `.artifacts/` and do not
  become the durable evidence reference.
- [ ] Preserve no-input-synthesis import scanning and add the devtools module to
  its scope.
- [ ] Run focused harness/safety tests and hermetic.
- [ ] Commit: `feat: add isolated candidate acceptance harness`

---

### Task 7: Author and validate the three migrated candidates

**Files:**

- Create under `docs/superpowers/candidates/declarative-workflow-compiler/`:
  pack, intent, and recipe artifacts for Synthetic Export, Open Folder, and Open
  Terminal
- Create: candidate-only index/activation fixtures with no production authority
- Create: `tests/test_migrated_candidates.py`

**Property:** v2 represents all certified v1 behavior before production changes.

**Invariant:** migration changes representation, not selectors, title behavior,
step identity, provenance, wrong-action surface, OCR policy, or verification
meaning.

- [ ] Generate content-addressed filenames from exact LF/UTF-8-no-BOM bytes and
  record full digests separately. Never trust the filename fragment.
- [ ] Preserve each v1 `step_key_namespace` exactly.
- [ ] Synthetic Export declares explicit action, verification, and context
  selectors sufficient for the certified wrong-action test and disables OCR.
- [ ] Open Folder uses bounded descendants, normalized matching, raw-name
  publication, current grounding rung, exact title-verification parity, and no
  positional-ID promotion.
- [ ] Open Terminal uses exactly `Toggle Panel (Ctrl+J)` and `Terminal Section`,
  `normalise: none`, and no broadened synonym.
- [ ] Compile all three through the candidate loader and compare their step,
  selector, verification, and observation-plan snapshots to reviewed fixtures.
- [ ] Confirm candidates remain unreachable from production `PackRegistry`,
  planner, CLI, and Ask.
- [ ] Run focused migration tests and hermetic.
- [ ] Commit: `test: add schema v2 migration candidates`

---

### Task 8: Human acceptance and committed evidence for migrated workflows

**Files:**

- Create/update committed documents under `docs/evidence/` for Synthetic Export,
  Open Folder, and Open Terminal schema-v2 acceptance
- Do not install or activate candidates in this task

**Gate:** stop if any workflow does not complete three consecutive runs against
the exact candidate graph and exact observed application version.

- [ ] Run Synthetic Export 3/3, including its wrong-control action and verified
  recovery/completion.
- [ ] Run Open Folder 3/3. Evidence must assert in-tour `source=uia` and zero OCR
  escalation, not completion alone.
- [ ] Run Open Terminal 3/3 with the exact migrated selector behavior.
- [ ] Preserve raw logs under `.artifacts/`, but write durable evidence with the
  exact pack, intent, and recipe SHA-256; exact `AppInfo.version`; run-by-run
  outcome; provenance; timestamps; and candidate-harness command.
- [ ] Independently review each evidence document under D032. The operator who
  ran or authored it cannot be its sole certifier.
- [ ] Rehash each evidence document after review and record the digest to be used
  by Task 9's activation records.
- [ ] Run hermetic to prove this evidence-only commit changed no code behavior.
- [ ] Commit: `docs: certify schema v2 migrated workflows`

---

### Task 9: Atomic production cutover to schema v2

**Files:**

- Create: `ghostcursor/packs/index.json`
- Create: content-addressed `vscode`, `synthetic`, `notepad`, and `common` pack
  directories with reviewed activations
- Modify: `ghostcursor/packs/registry.py`
- Modify: `ghostcursor/reasoning/planner.py`
- Modify: `ghostcursor/run.py`
- Modify: `ghostcursor/daemon.py`
- Modify affected tests and fixtures
- Delete: `ghostcursor/packs/manifests/`
- Delete: v1 `ghostcursor/packs/recipes/` layout after installing v2 artifacts
- Delete: `ghostcursor/reasoning/recipes/`
- Delete: hardcoded `registry()`, `perception_walker_for()` workflow branches,
  `PackRegistry.recipe_for_intent()`, `recipe_paths()`, filename/stem inference,
  one-intent fallback, and `planner.py:231-232` special case

**Property:** after this commit there is one production authority path and it is
the reviewed v2 catalog.

**Invariant:** all three accepted recipes activate only through manifest records
that bind the exact tested pack, intent, recipe, evidence, and app version.

- [ ] Install the accepted candidate bytes under content-addressed names; re-read
  and rehash every installed artifact.
- [ ] Build complete adoption records using Task 8 evidence digests and set their
  active adoption IDs. Add common-pack inactive `CREATE_DOCUMENT` and
  `OPEN_SETTINGS`. Omit inert `OPEN_NEW_TAB` entirely.
- [ ] Switch planner, daemon, CLI goal path, Ask, run, and perception to the
  verified catalog/compiled workflow APIs in one commit.
- [ ] Remove production `--recipe`; raw overlay mode remains.
- [ ] Delete all v1 loading roots, adapters, hardcoded walkers, and fallback
  branches. Add source scans that fail if any forbidden API or directory returns.
- [ ] Prove production cannot execute the quarantined candidate copies or any
  unreferenced installed orphan.
- [ ] Run focused catalog/planner/run/perception tests, D072 differential gate,
  model hermetic tests, and the full hermetic lane.
- [ ] Mutation-check at least one guard at every authority stage from index to
  pre-launch.
- [ ] Commit: `feat: activate declarative workflow compiler`

---

### Task 10: Re-certify the compiler baseline

**Files:**

- Create/update committed gate summaries under `docs/evidence/`
- Do not add workflow capability

- [ ] Run hermetic:

```powershell
py -3.12 -m pytest tests -m "not interactive and not pixel and not hung" `
  --basetemp=.tmp\pytest-hermetic -p no:cacheprovider
```

- [ ] Run interactive, pixel, and standalone pixel lanes exactly as documented
  in `CLAUDE.md`.
- [ ] Run each hung-window command alone, never beside another session.
- [ ] Run the synthetic wrong-action regression.
- [ ] Run the live eight-cell never-fabricate matrix independently of the D072
  corpus.
- [ ] Because planner/parser/schema changed, run the frozen three-lane model gate
  interactively. Require two consecutive non-draft full passes; preserve and
  classify any failure before restarting the count.
- [ ] Prove model output still cannot alter executed recipe authority; retain
  D068's zero-influence property.
- [ ] Record exact commits, commands, results, dataset/version/model/digests, and
  artifact locations in committed evidence. Do not cite ignored raw logs as the
  durable source.
- [ ] Independent evidence review under D032.
- [ ] Commit: `docs: certify declarative compiler baseline`

---

### Task 11: Add Open Extensions as a quarantined data-only candidate

**Files:**

- Create only Open Extensions intent/recipe candidate JSON and candidate
  activation data
- Create data-oriented tests/fixtures if needed; no workflow-specific production
  Python

**Property:** a fourth real workflow can be represented without changing the
compiler.

**Invariant:** `Extensions (Ctrl+Shift+X)` is `provider_exact`, exactly one name,
`control_type: "TabItem"`, `normalise: "none"`, and `exactly_one`; `Installed
Section` verification is declarative and `at_least_one`.

- [ ] Record the Task 9 cutover commit as the proof baseline.
- [ ] Add exact and heuristic D072 intent rules using only the frozen grammar;
  do not add a matcher primitive or plugin.
- [ ] Compile the candidate with the existing loader/compiler unchanged.
- [ ] Test bare-name ambiguity still fails and the TabItem-constrained selector
  resolves exactly one in the reviewed fixture.
- [ ] Source-scan the candidate diff and fail if it contains a workflow-specific
  change under `ghostcursor/**/*.py`.
- [ ] Run focused tests and hermetic.
- [ ] Commit: `test: add Open Extensions data-only candidate`

---

### Task 12: Accept, evidence, install, and activate Open Extensions

**Sequence requires two commits. Do not combine them.** Evidence must exist and
be reviewable before activation can reference it.

- [ ] Run the exact quarantined candidate 3/3 on the reviewed VS Code version.
  A run passes only when the Extensions target is UIA-grounded and `Installed
  Section` appears under the declarative verification selector.
- [ ] Write committed evidence with full pack, intent, recipe digests; exact app
  version; raw provider count/property-read result; 3/3 outcomes; and provenance.
- [ ] Independently review the evidence, then commit:
  `docs: certify Open Extensions workflow`.
- [ ] Rehash the reviewed evidence, install the exact intent/recipe bytes, append
  a complete adoption record, and atomically replace only the VS Code
  `activation.json` mapping last.
- [ ] Verify installed bytes/digests and pre-launch materialization.
- [ ] Run focused tests, hermetic, and a production materialization check proving
  the active graph's bytes equal the already accepted candidate bytes. Do not
  relabel extra smoke runs as part of the required 3/3 acceptance.
- [ ] Commit: `packs: activate Open Extensions workflow`.
- [ ] Compare the entire diff from Task 9's baseline through this activation.
  The proof fails if any workflow-specific Python was needed; generic bug fixes
  discovered during adoption must land separately and reset the baseline before
  repeating the proof.

---

### Task 13: Final regression, documentation, and handoff

**Files:**

- Modify only current-state rules/orientation in `CLAUDE.md`
- Update architecture in `FLOW.md` and `ARCHITECTURE.md`
- Record rationale/results in `DECISIONS.md` and `docs/evidence/`
- Close or update only genuinely resolved entries in `FOLLOWUPS.md`
- Update `README.md` only for user-visible commands/behavior

- [ ] Repeat the full Task 10 non-desktop gate set on final HEAD and verify the
  committed **12-run** acceptance record is complete: Synthetic Export, Open
  Folder, Open Terminal, and Open Extensions, each accepted 3/3 before
  activation against the exact installed bytes. Do not inflate the count with
  post-install smoke checks.
- [ ] Confirm `kb.sqlite` deletion semantics are unchanged and no
  `knowledge.sqlite` tables were introduced.
- [ ] Confirm durability branch remains exactly `5e771ca` at tag
  `durability-final` and submission remains `7cdf64c`.
- [ ] Apply D071 ownership: rules in CLAUDE, architecture in FLOW/ARCHITECTURE,
  decisions/measurements in DECISIONS/evidence, unresolved triggered work in
  FOLLOWUPS. Do not copy the compiler narrative into every file.
- [ ] Independently review code, evidence, and documentation under D032.
- [ ] Verify no placeholders, stale v1 commands, direct recipe authority, glob
  discovery, workflow walkers, or unexplained matcher divergence remain.
- [ ] Commit: `docs: close declarative workflow compiler milestone`
- [ ] Stop for owner approval before any merge to a release branch or `main`.

---

## Final acceptance checklist

- [ ] One indexed, digest-bound, schema-v2 authority path; no v1 loader or
  production candidate path.
- [ ] D072 fixture: 86 rows, 14 declared divergences, 5/3/6 classes, zero
  unclassified, expected intent/confidence/kind all enforced.
- [ ] Root and per-pack failure scopes mutation-covered.
- [ ] Adoption, supersession, withdrawal, rollback, and reacceptance preserve
  complete immutable history.
- [ ] Planning and pre-launch bind the same HWND, process, executable, title,
  `AppInfo.version`, index, activation, evidence, and artifact bytes.
- [ ] Observation plans cover action, verification, and context selectors with
  one all-or-nothing tick and no ambiguity-hiding truncation.
- [ ] Synthetic Export, Open Folder, Open Terminal, and Open Extensions each
  pass 3/3; Open Folder asserts UIA provenance.
- [ ] Frozen model gate has two consecutive non-draft passes; live never-fabricate
  matrix and zero model execution influence remain green.
- [ ] Interactive, pixel, standalone, hung-window-alone, wrong-action, and
  hermetic gates pass.
- [ ] Open Extensions is proven data-only relative to the compiler baseline.
- [ ] No knowledge-layer schema, Canva pack, startup watcher, tray, installer,
  or release merge is smuggled into this milestone.

## Explicitly remaining after this plan

This milestone does **not** build the future `knowledge.sqlite` schema, trusted
manual ingestion, retrieval-generated drafts, Canva, foreground watcher/tray,
installer/setup experience, participant study, demo recording, or release/main
merge. Those retain their existing roadmap order and external gates after the
compiler milestone closes.
