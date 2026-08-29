# Declarative workflow compiler — final milestone evidence

Date: 2026-08-29 (Asia/Calcutta)

This is Task 13's durable summary. It binds measurements to committed artifacts
and distinguishes rerun gates from Task 10 desktop evidence. It does not
self-certify D032: the exact staged tree, this summary, and the commands below
must receive independent review before the closing commit is created.

## Bound history

- Compiler baseline: `41682ee` (`docs: certify declarative compiler baseline`).
- Data-only Open Extensions candidate: `d26d2d8`.
- Open Extensions acceptance evidence: `9af7cb9`.
- Installed and activated Open Extensions: `2736d1b`.
- Production-Python proof range: `41682ee..2736d1b`.
- Protected tips remained `post-submission/model-durability` at `5e771ca` and
  `submission/open-track` at `7cdf64c`; nothing was pushed or merged.

`git diff --name-only 41682ee 2736d1b -- ':(glob)ghostcursor/**/*.py'`
returned no path. The proof is deliberately byte-level: Open Extensions was
added through candidate, intent, recipe, evidence, installation, and activation
data without changing production Python.

## Twelve accepted runs and installed authority

The committed evidence contains exactly the required successful campaigns:

| Workflow | Successful runs | Steps | Grounding | Accepted identity |
|---|---:|---:|---|---|
| Synthetic Export | 3/3 | 2/2 each | UIA only | D073 content SHA-256 |
| Open Folder | 3/3 | 1/1 each | UIA only (required gate) | VS Code `1.135.0.0` |
| Open Terminal | 3/3 | 1/1 each | UIA only | VS Code `1.135.0.0` |
| Open Extensions | 3/3 | 1/1 each | UIA only | VS Code `1.135.0.0` |

- Migrated-candidate evidence:
  `docs/evidence/schema-v2-candidate-acceptance.md`, SHA-256
  `5222a3cb4fc8635fa92df98df754032b6574c1f1d5f1c2f21801a263cec4b937`.
- Open Extensions evidence:
  `docs/evidence/open-extensions-candidate-acceptance.md`, SHA-256
  `18710dc4500c8b372e2a28142b3daa5f6ca112e68f96140eb77a7ca504998a51`.

Both renderers reproduced their committed documents exactly from the local run
records with `--check`. Activation tests re-read installed artifacts and prove
they are byte-identical to the reviewed candidates. The production catalog has
four active workflows and materializes Open Extensions only through generation
2 adoption `accept-open-extensions-1`, whose evidence digest and review commit
bind the values above.

The Open Extensions support boundary is narrower than executable-version
identity: acceptance used Extensions pinned, no temporary restart badge, and
Explorer selected. Unpinned and badge-altered states produced clean absence,
not a different action. The unresolved trigger is owned by `FOLLOWUPS.md`.

## Final non-desktop gates

The first hermetic attempt under the restricted filesystem is not counted: it
ended with `PermissionError: [WinError 5]` while pytest enumerated
`.tmp/pytest-task13-hermetic`, after fixture setup errors. The identical lane
with ordinary test-filesystem access reached the suite. One later full run then
exposed a separate test-isolation defect: a hermetic compiled-launch helper
read the real global ESC key and could return before overlay creation if a
physical key state was pending. The helper now fixes ESC to false; dedicated
pre-launch and hung-runtime ESC tests still own the abort paths. Its focused
launch/ESC regression passed 126 tests with 7 hung tests deselected, and the
full final lane was restarted from zero.

The documentation pass then exposed a production regression that the green
cutover suite had not named: the compiled path retained
`step_key_namespace` as data but never opened `ObservationStore`, hydrated a
compiled step, or promoted a learned UIA identity. Compilation had also
dropped the rest of the authored claimed descriptor. That made
D013/D016/D017's disk-backed learning unreachable after Task 9. D079 restores
the existing identity without restoring recipe-path authority: full claimed
descriptors survive compilation; executable-version packs retain the
compatible executable app key while content-identity packs use their pack id;
and the exact accepted identity value scopes observations. A production-launch
regression runs the same compiled workflow twice against a scratch database:
run 1 grounds at rung 2 and persists, and run 2 hydrates the stable namespace
and grounds at rung 1. Separate tests refuse OCR persistence and prove the
store closes if overlay construction raises. Nine targeted mutations were
killed, including removal of promotion, hydration, descriptor retention,
namespace binding, each app-key branch, caller use of the app-key resolver,
hydrated-step use, and failure cleanup.

That shared-runtime repair occurred after Open Extensions activation. It does
not alter the data-only proof: the proof test and D078 now pin both immutable
endpoints, `41682ee..2736d1b`, instead of comparing the baseline to a moving
working tree.

D079 changes the internal rung recorded for a first, unlearned match, not the
accepted action or verification contract. The renderer receives the same
selector-bounded element and keys freshness on provenance source, while
promotion eligibility depends on UIA provenance and a non-positional
AutomationId rather than rung. Open Folder's Codicon-prefixed raw name therefore
lands on rung 3; Open Extensions, Open Terminal, and Synthetic Export land on
rung 2 before learning. No user-visible decision, hint target, action, or
completion rule changed, so the twelve evidence-bound acceptance runs were not
repeated.

| Gate | Command | Result |
|---|---|---|
| Hermetic, closing implementation tree | `py -3.12 -m pytest tests -m "not interactive and not pixel and not hung" --basetemp=.tmp\pytest-task13-d032-corrections -p no:cacheprovider -q` | 1055 passed, 70 deselected, 29.14 s |
| Compiled learning and persistence focus | `py -3.12 -m pytest tests\test_compiled_workflow.py tests\test_compiled_perception.py tests\test_observation_compiler.py tests\test_migrated_candidates.py tests\test_run_persistence.py tests\test_store.py -q` | 307 passed, 4.98 s |
| Compiled launch + ESC focus | `py -3.12 -m pytest tests\test_compiled_workflow.py tests\test_run.py tests\test_run_threaded.py -m "not hung" -q` | 126 passed, 7 deselected, 1.58 s |
| Isolated compiled hung-runtime safety | `py -3.12 -m pytest tests\test_run_threaded.py -q` | 7 passed, 15.66 s |
| Authority + activation + storage + D072 focus | `py -3.12 -m pytest tests\test_task9_cutover.py tests\test_open_extensions_activation.py tests\test_persistence_e2e.py tests\test_store.py tests\test_migrated_candidates.py tests\test_compiled_matcher.py -q` | 129 passed, 6.46 s |
| Open Extensions candidate + evidence + activation proof | `py -3.12 -m pytest tests\test_open_extensions_evidence.py tests\test_open_extensions_candidate.py tests\test_open_extensions_activation.py -q` | 40 passed, 1.17 s |
| `kb.sqlite` erase path | `py -3.12 -m pytest tests\test_persistence_e2e.py -q` | 2 passed, 2.63 s |
| Evidence regeneration | Task 8 renderer, Task 12 renderer, D072 renderer, and candidate builder in `--check` mode | all clean |

The focused persistence test creates observations, closes the store, deletes
`kb.sqlite`, opens a new store, and observes an empty database. Production has
one `CREATE TABLE IF NOT EXISTS observations` statement in
`ghostcursor/memory/store.py`; `knowledge.sqlite` appears in no production
path and no knowledge-layer table exists.

Task 10 already ran every desktop, pixel, standalone-pixel, and isolated
hung-window lane after the authority cutover; the independently reproduced
results are in `docs/evidence/schema-v2-task9-recertification.md`. Task 13's
plan requires the full non-desktop set on final HEAD, not another 12 human
acceptance runs or a redundant desktop campaign. No runtime code changed while
Open Extensions was added or activated; the later D079 repair is shared
compiled-memory infrastructure and is outside the fixed data-only proof range.

## Final frozen model gate

Activation changes the installed intent vocabulary, so Task 10's model reports
were not reused. The frozen owner-reviewed dataset `1.0.0` ran twice
consecutively, interactively, and without `--draft`:

```powershell
py -3.12 -m ghostcursor.evaluation.model_gate `
  --model qwen3:4b-instruct `
  --endpoint http://127.0.0.1:11434 `
  --unavailable-endpoint http://127.0.0.1:1 `
  --interactive
```

| Pass | Created at (UTC) | Report SHA-256 | Raw / exact-supported accuracy | Median / max latency |
|---|---|---|---|---|
| 1 | `2026-08-29T11:06:06.929366+00:00` | `083d7f9858d415fe4e5fc45b3ac09d7f6ca3095d2775be4bacb700ffeb45d376` | 90% / 100% | 2809.195 / 17843.909 ms |
| 2 | `2026-08-29T11:08:12.235029+00:00` | `8635cbfece953ff44cd89ee4fe0f0007b0dc1c732054e205b0e6bf05f8a0523e` | 90% / 100% | 2734.953 / 3497.813 ms |

Both reports have `trusted_baseline`, `passed`, and
`final_milestone_eligible` true. Ollama reported version `0.31.1` and model
manifest SHA-256
`0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`.
Every hard gate was true: all responses parsed, exact-supported raw intent was
100%, unsupported launch-eligible plans were zero, never-fabricate launches
were zero, supported controls launched, the hint selected only Export, and no
exact-supported response hit an unexplained length truncation. The interactive
lane made zero tour dispatch attempts and left its status sentinel unchanged.

The ignored reports are
`.artifacts/model-evaluation/model-gate-20260829-163803.json` and
`.artifacts/model-evaluation/model-gate-20260829-163950.json`. Their hashes are
recorded for local audit; this committed summary is the durable evidence.

## Independent live eight-cell matrix

This matrix separately called production `plan_compiled_goal()` on the
installed catalog. Available rows used `qwen3:4b-instruct` at
`127.0.0.1:11434`; unavailable rows used `127.0.0.1:1`. Supported VS Code
controls narrowed to the live AIOS window. No tour was launched.

| Goal | Model | Status | Intent | Bound plan |
|---|---|---|---|---|
| Create a Python file in VS Code | available | `KNOWN_INTENT_RECIPE_UNAVAILABLE` | `CREATE_DOCUMENT` | no |
| Create a Python file in VS Code | unavailable | `UNSUPPORTED_GOAL` | none | no |
| Deploy this project to production | available | `UNSUPPORTED_GOAL` | none | no |
| Deploy this project to production | unavailable | `UNSUPPORTED_GOAL` | none | no |
| Open a folder in VS Code | available | `SUPPORTED` | `OPEN_FOLDER` | yes |
| Open a folder in VS Code | unavailable | `MODEL_UNAVAILABLE_FALLBACK` | `OPEN_FOLDER` | yes |
| Open the integrated terminal in VS Code | available | `SUPPORTED` | `OPEN_TERMINAL` | yes |
| Open the integrated terminal in VS Code | unavailable | `MODEL_UNAVAILABLE_FALLBACK` | `OPEN_TERMINAL` | yes |

The four unsupported or unavailable cells materialized zero plans. The four
supported controls materialized only already-adopted recipes. Model output
changed classification metadata but supplied no artifact, selector, action,
step, or execution authority (D068).

## Authority and stale-path audit

- `ghostcursor/packs/index.json` is the only root index. Catalog and activation
  tests cover root, pack, intent, and adoption failure scopes.
- Production has no tracked `packs/manifests/`, v1 `packs/recipes/`, or
  `reasoning/recipes/` root.
- Production defines no hardcoded planner `registry()` or planner `_fallback`,
  `perception_walker_for()`, `perception_hwnd_source_for()`, legacy
  `run_tour()`, `recipe_for_intent()`, or `recipe_paths()` authority.
- Classification does not read recipe files. Candidate paths are accepted only
  by the isolated developer harness; production cannot execute quarantined or
  unreferenced artifacts.
- D072 remains frozen at 86 rows and 14 declared divergences in classes 5/3/6,
  with intent, confidence, and kind enforced and zero unclassified rows.
- `CLAUDE.md`, `FLOW.md`, `ARCHITECTURE.md`, and `README.md` describe the current
  schema-v2 command and authority path. Historical v1 descriptions in source
  comments or explicitly historical evidence are not callable interfaces.
- No placeholder, Canva pack, startup watcher/tray, installer, knowledge-layer
  schema, or release-branch merge was added.

## Review and handoff gate

Before the closing commit, an independent D032 reviewer must inspect the exact
staged tree, rerun or independently reproduce the authority and documentation
claims, and confirm that `HEAD^{tree}` after commit equals the reviewed tree.
The closing commit is documentation and evidence only; it does not authorize a
merge to `main` or any release branch.
