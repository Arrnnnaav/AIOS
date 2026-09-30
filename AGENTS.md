# GhostCursor agent guide

This is the first file Codex should read in a new GhostCursor thread. It gives
the working method and routes the agent to the relevant project evidence.
`CLAUDE.md` remains the canonical source of current mandatory rules and
commands. If this file and `CLAUDE.md` disagree, follow `CLAUDE.md` and repair
the drift in the same focused change.

## Model and thread strategy

- Prefer **GPT-5.6 Sol with medium reasoning** for ordinary implementation,
  tests, documentation, and contained debugging when model selection is
  available.
- Use **high reasoning** for plugin/runtime architecture, repository ingestion,
  permissions and security boundaries, concurrency, agent orchestration, or a
  difficult defect whose cause is still uncertain.
- Start a fresh Codex thread for each subsystem or review boundary. Do not make
  one thread carry the complete product history.
- Give each thread one concrete outcome and the relevant paths. Preserve
  completed work through commits and repository documentation, not chat memory.

## Begin every subsystem this way

1. Read this file and the relevant parts of `CLAUDE.md`.
2. Read `graphify-out/GRAPH_REPORT.md` when it exists, then query or inspect only
   the folders and files relevant to the task.
3. Read the matching section of `ROADMAP.md` for sequence and current status.
4. Read `FLOW.md` for the current call path being changed.
5. Read only the decisions cited by those files in `DECISIONS.md`. Decisions are
   history and may be explicitly amended as the product evolves.
6. Check `docs/superpowers/FOLLOWUPS.md` for unresolved constraints triggered by
   the proposed change.

Do not load the whole repository by default. Start with `rg` or Graphify, name
the smallest relevant file set, and expand only when dependencies require it.

## Work in focused slices

Use this order for each slice:

1. **Architecture:** state the property being protected, the invariant that
   enforces it, and the files that own the boundary.
2. **Implementation:** change the smallest coherent set of files. Preserve user
   changes and avoid unrelated cleanup.
3. **Tests:** run the narrow meaningful lane first. Add ordered injected-clock
   tests for state or time behavior. Mutation-test safety-critical checks under
   D018.
4. **Reconciliation:** update the document that owns each changed fact. Current
   architecture belongs in `FLOW.md`, current mandatory rules in `CLAUDE.md`,
   rationale and measurements in `DECISIONS.md` or `docs/evidence/`, unresolved
   work in `docs/superpowers/FOLLOWUPS.md`, and phase order in `ROADMAP.md`.
5. **Commit:** commit the green, reconciled slice before beginning mutation,
   independent review, or the next subsystem.

Keep commits focused on one concern. Do not mix architecture, unrelated fixes,
and speculative follow-up work in one batch.

## Gates that every thread inherits

- **D018:** deliberately mutate every safety-critical property and prove a test
  detects the break.
- **D025:** never run two test sessions at once. Interactive/UIA, pixel, and
  hung-window lanes are serial, and each hung-window command runs alone.
- **D032:** nothing an agent authored or asserted—code, documentation, a brief,
  or a claimed fact—is ground truth until an independent reader checks it.
  This applies to every task, not only release or activation evidence. A
  reviewer uses a separate worktree, or implementation pauses until review is
  complete.
- **D034:** every measured number cited as evidence names its durable record in
  `docs/evidence/`.
- Production authority flows through signed plugins, the canonical
  compatibility check, `authorize_intent()`, fresh binding, and per-node
  authorization. Do not create a parallel policy path.
- Teach and acceptance tools may not move the OS pointer, type, or import input
  synthesis APIs. Act adapters may not use cursor APIs or generic mouse or
  keyboard automation. Changing either boundary requires an explicit owner
  decision and reviewed architecture amendment.
- A pointer shown for an Act operation must identify the control that receives
  that operation. Geometry is presentation evidence and never authorization.

## Test lanes

Run the smallest relevant tests first. Use the canonical commands and isolation
requirements in `CLAUDE.md`. The standard hermetic lane is:

```powershell
py -3.12 -m pytest tests -m "not interactive and not pixel and not hung" `
  --basetemp=.tmp\pytest-hermetic -p no:cacheprovider
```

Interactive, pixel, and hung-window lanes must follow the separate commands in
`CLAUDE.md` and D025. Never call a desktop diagnostic acceptance evidence.

After a finalized build slice, follow the Knowledge Graph instructions in
`CLAUDE.md`. `graphify update .` refreshes code extraction only; do not treat it
as a document refresh when Markdown, documents, or evidence changed.

## Subsystem routing

| Area | Start here | Typical implementation paths |
|---|---|---|
| Product phase and priorities | `ROADMAP.md` | linked evidence and decisions |
| Runtime architecture | `FLOW.md` | `ghostcursor/act_*.py`, `ghostcursor/run.py` |
| Plugin authority | `CLAUDE.md` plugin-platform rules; D077–D082, D100, D108 | `ghostcursor/plugins/`, `ghostcursor/adapter_host.py`, `plugins/sources/<app>/`, `tests/test_plugin_*.py` |
| Perception | `CLAUDE.md` perception rules | `ghostcursor/perception/`, `ghostcursor/reasoning/grounding.py` |
| Overlay and pointer | D006, D009, D010, D109, D115–D118 | `ghostcursor/overlay/`, `ghostcursor/act_overlay.py` |
| Planning and local models | `ROADMAP.md` Phase 3 build-order items 7–8 | `idea.txt`, `ghostcursor/brief.py`, `ghostcursor/task_graph.py`, `ghostcursor/inference/ollama.py`, `tests/test_brief.py`, `tests/test_task_graph.py` |
| Manager/panel | `FLOW.md` manager section; D088, D098, D099, D118 | `ghostcursor/manager.py`, `ghostcursor/act_ui_bridge.py`, `tests/test_manager.py`, `tests/test_manager_window.py`, `tests/test_manager_act_bridge.py`, `tests/test_act_ui_bridge.py` |
| Evidence or release | D032, D034 and release rules | `docs/evidence/`, activation and acceptance tools |
| Product evolution plan | `docs/orbyn-plan/README.md`, `MVP.md`, and the relevant Mega Phase; current status still comes from `ROADMAP.md` | `docs/orbyn-plan/`, `DECISIONS.md` |

### Separate Spatial project and later integration

- Spatial is an independently developed project at `D:\PROJECTS\Spatial`, not a subdirectory or branch of this AIOS repository. Build, test, and review it in its own repository first. Do not clean, reset, move, or edit its working tree as part of an AIOS task unless the user explicitly scopes that project in.
- Before the current Act activation review returns READY, only standalone Spatial work, read-only evaluation, and documentation/design that does not wire manager Ideate/Plan, Spatial Context into a Brief, or semantic app workflows may proceed.
- After activation, Spatial Context integration is the first item of ROADMAP Stage 1 under D143. Pass a typed `SpatialContextReference` into the Brief as non-authoritative context; never convert a mark into a selector, target identity, coordinate, permission, or execution request.
- D147 (D141-R2) is the current provider policy: a configured cloud provider may be the default reasoning provider for the trial period, local execution stays supported and tested, and side-effecting connectors keep their D144 gates. D147's independent D032 review is outstanding; see `CLAUDE.md` for the binding rule.
- Keep regression/replay/evaluation continuous from the first standalone Spatial change. An OrbynBench phase consolidates infrastructure; it does not defer tests. External DOM, ARIA, PDF, OCR, search, and app text are untrusted input before any model sees them.

Add a smaller `AGENTS.md` inside a major module only when that module has
stable local commands, generated-file rules, or safety constraints that are not
clear from the root guide and its linked canonical docs. Keep local files short
and do not copy root rules into them.

## Handoff standard

At the end of a thread, leave the next thread a repository-backed handoff:

- outcome and behavior now present;
- files and commit(s) that contain it;
- exact tests and evidence that passed;
- remaining uncertainty or blocked gate;
- the next smallest action from `ROADMAP.md`.

Do not use conversation history as the only record of product state.
