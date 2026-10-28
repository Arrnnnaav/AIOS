# ROADMAP

The phase index. **What we are building next and why, at the scale of phases.**

Extracted from the planning documents in `~/Downloads/` — principally
`01_final_architecture.md` §39 (Build Roadmap) and §2/§40, and
`02_modular_ideation_execution.md` §4 (Interaction Modes) and §11 (Capability
Modules). Those documents are the product intent; this file is that intent
reconciled against what the repository actually contains.

## How to use this file

- A phase's **Status** is measured against the repo, not asserted. If a line
  says "built", something in `docs/evidence/` or a cited decision backs it.
- When the owner says what a phase should contain, it is recorded **here**
  first, then built. A phase that exists only in conversation is not a phase.
- This file says *what and in what order*. It does not restate rules
  (`CLAUDE.md`), architecture (`FLOW.md`), rationale (`DECISIONS.md`),
  unresolved work (`docs/superpowers/FOLLOWUPS.md`) or measurements
  (`docs/evidence/`). Link to those instead of copying them.

## Where we are

**Current product surface (28 October 2026):** the workspace app (D178,
`ghostcursor/workspace/app.py`): a desktop island plus a full Edge workspace
with Chat, Plan, Brain and Work. Work runs read-only background research and
hourly/daily/weekly routines; a routine result lists the claims new since its
previous run. A user-level installer stages updates with rollback. Slash
commands belong to the console (`python -m ghostcursor.workspace`), not the
app window. Teach/Act release acceptance below is still open.

**Phase 1 is substantially complete. Phase 3's "limited Act" has an implemented
object-model boundary, but its 11 September 3/3 runs are diagnostic under D139.
Act acceptance remains open: the UIA slice, animation catalog, fresh counted
runs, independent desktop lanes, budget review, and D032 activation review
still gate closure.**
Phase 2 is partly built; its telemetry/sync conflict is resolved by D141 and
re-sequenced by D147 (see the note under it). The agent/skills/marketplace program is recorded
below, before Phase 4, and starts only after the activation review.

Interaction modes are canonical contracts in `ghostcursor/interaction.py`.
Of the seven modes the planning docs name, the repo implements a narrower
set — Ideate, Plan, Teach, Assist, Act — and Discuss, Autopilot and Watch are
not modelled at all. That is a deliberate narrowing, not an oversight, but it
means the mode list in `02_modular_ideation_execution.md` §4 is intent rather
than current design.

---

## Harness-first, model-driven modes (D159, D164) — the current track

**Status: step 1 (provider gateway, D164) and step 2 (multi-window binding and observation frame, D166) and step 3 (model-driven Teach behind `--model-teach`, D167) built; step 4 tooling (corpus capture + offline replay, D170) built, the measurement itself not yet run. Owner pulled Spatial `--point` and SayStride `--voice` into model-Teach early (D171). The solo MVP workspace (brief, research with cited evidence, Personal Brain, discuss, plan, Teach a plan step) is built as a console, `python -m ghostcursor.workspace` (D173); live runs and manager UI integration remain.** Teach and Act
are an application-agnostic harness driven by a model, across several
applications at once; PowerPoint is the test fixture (D164). Owner direction, 30 September 2026: guidance
for any application comes from a large model plus Jev choosing among the
controls the harness observed, instead of hand-curated per-application packs.
Teach only; Act stays on the signed plugin path. Design:
`docs/superpowers/specs/2026-10-01-model-driven-teach-design.md`.

Order: (1) provider gateway + Jev transport, (2) `ObservationFrame`, (3) corpus
capture + offline replay evaluation, (4) model-driven Teach executor behind a
flag, (5) manager integration, (6) later, verified runs drafted into Skills.
Each slice is reviewed before the next; no accuracy claim before the replay
corpus measures it.

---

## Owner build order, 16 October 2026 (D180 onward)

Owner: "make things leave less as much as possible, then work on the brain,
plan, ideate, act, multiplayer and the YC RFS ideas; check the end-to-end plan
and build". Reconciled against `docs/orbyn-plan/` (MVP, MP3, MP7, Unified Plan
section 4):

| # | Slice | Plan source | Status |
|---|---|---|---|
| 1 | Organisation policy + scrubbed screen text | MVP privacy; Unified 4.5 enterprise mode | built (D180) |
| 2 | Ideate: 2-4 approaches with assumptions and unknowns; plan from the chosen one; the plan shows which memories informed it | MP3 Phase 10, Phase 9 retrieval | built |
| 3 | Jev in the workspace: composer intent suggestion; Brain check beside the deterministic rule | D179 table | built |
| 4 | Multiplayer V1 seed: hand a mission (goal, plan, sources) to a teammate as a file; what arrives is data, never their goal or authority | Unified 4.2 (YC RFS Multiplayer), MP7 | built |
| 5 | Act from the workspace | MP0/MP4 | stays refused until the Act activation review is READY (tier 1) |
| 6 | Company Brain / Context Graph, self-maintaining APIs | Unified 4.1, 4.4; MP7, MP8 | later; needs D017-amendment and sandbox work first |

---

## Jev (System One) across the product (D179)

Jev answers typed questions fast and cheaply ($0.042 per million input
tokens, output free; docs.typesafe.ai/models, read 16 Oct 2026). Rule: Jev
selects or verifies; code decides; nothing Jev says becomes a position or an
action.

| Where | Jev question | Status |
|---|---|---|
| Teach: which observed control | Choice over candidate ids, or abstain | built (D167) |
| Teach: when text is not enough | same Choice with a redacted picture per window (opt-in) | built (D179) |
| Research: does the cited passage back the claim | Choice supports / contradicts / says nothing; only lowers | built (D179) |
| Teach: did the step happen | Noul from before/after control facts, beside `change_observed` | built (D179) |
| Brain: is this a lasting, self-stated fact with no secret | Choice beside the deterministic rule; only lowers | built |
| Workspace composer: chat, research, ideate or plan | Choice; shown as a one-tap suggestion, never automatic | built |
| Research: which passages matter | per-passage relevance before System Two | built (D179) |
| Any tainted text: does it try to give instructions | Noul injection screen (received handoffs) | built (D179) |
| Jev 1.14 (`jev-preview`) vs 1.13 | replay tool built (`devtools.jev_replay`); run pending | tool built |

---

## Phase 1 — Reliable Guided Runtime

> Core, VS Code plugin, intent normalization, declarative workflows, UI
> perception, overlay, Ask/Pause/Stop, verification, safe failure, basic
> WorkflowSession.

**Status: substantially built.**

| Piece | State |
|---|---|
| Core runtime, overlay, Ask/Pause/Stop rail | Built (D009, D010, D021, D022; control rail per CLAUDE.md) |
| VS Code plugin and workflows | Built; gates closed (D048–D057) |
| Intent normalization / deterministic planner | Built (D058, D072) |
| Declarative workflow compiler, schema v2 | Built; sole authority (D069–D077) |
| UI perception UIA → OCR | Built (D028–D030, D035) |
| Verification and safe failure | Built (D069, D076) |
| Session truth / `SessionSnapshot` | Built |

Remaining: nothing blocking. Packaging, installer and tray are deferred —
see `docs/superpowers/FOLLOWUPS.md`.

---

## Phase 2 — Interaction + Telemetry

> Improved UI, inline Ask, friction reporting, telemetry, sync, basic memory,
> more VS Code workflows, second plugin.

**Status: partly built; the D017 conflict is resolved by D141 and D147, not yet built.**

Built: inline Ask, the vertical control rail, entity-scoped memory
(`ghostcursor/memory/store.py`), additional workflows, and more than a second
plugin — Excel, Synthetic Export and VS Code ship signed and data-only, with
PowerPoint a quarantined candidate.

**Conflict resolved by D141, then re-sequenced by D147 (24 September 2026).**
D017 forbade telemetry, network and sync. D141 amended it additively. **D147
(D141-R2) then made a configured cloud provider the default reasoning
provider for the trial period**, so cloud reasoning is no longer stage-6
gated and no longer needs per-session consent; local stays a supported, tested
configuration. Side-effecting connectors and telemetry did **not** move:
connectors keep their scoped-token/vault/audit/revocation gates, telemetry
stays off by default and events-not-content, and `kb.sqlite`/`sessions.sqlite`
never sync. **Nothing is built yet**, and D147's independent D032 review is
outstanding.

---

## Phase 3 — B2C

> Voice, skill model, personal memory, Experts, Teach/Assist, plugin packs,
> limited Act, undo/recovery.

**Status: in flight. "Limited Act" is the current work.**

| Piece | State |
|---|---|
| Teach | Built and gated |
| Assist | Declared as a mode, Preview-only, not implemented |
| Personal memory | Built, local (D017) |
| Plugin packs | Built for four applications |
| **Limited Act** | **In progress — see the Act v1 program below** |
| Voice, skill model, Experts | Not started |
| Undo / recovery | Not started, and unspecified |

### The Act v1 completion program

Ordered by D105 as amended by **D107**. Phases A–J below are the program's
own internal phases, not the product phases above.

| | State |
|---|---|
| A — PowerPoint diagnose-fix-rerun | **Closed.** 255/255 diagnostic run; `docs/evidence/act-phase-a-diagnostic.md` |
| B — read-only UIA feasibility | **Closed.** Excel passes; `docs/evidence/act-phase-b-uia-feasibility.md` |
| C — freeze contracts | Partial. Receipt, identity, and coordinate-space contracts have production callers; signed stages remain unfinished |
| D — runtime implementation | In progress. The public executor routes object-model and UIA operations to separate signed adapters, carries the pre-cue baseline into live verification, rejects cross-process geometry drift, seals presentation receipts, and rechecks Pause after authorization (D114–D118) |
| E — measure budgets | Partial. Receipt budgets and the checked paint path are recorded in `docs/evidence/act-paint-budget.md`; confirmation/dispatch and interruption budget closure remains |
| F/H/J — three independent D032 reviews | Boundary re-review closed. Two cold reviews withheld approval, three remediation rounds landed through `a7c1df5`, and the fresh review returned READY after 120 focused + 2,447 full hermetic tests. Final activation review remains a separate gate |
| I — release signing and counted runs | Partial. PowerPoint has a non-ephemeral key; current counted runs are still pending under D139 |

### The owner's specification for this phase

Recorded 2 September 2026 and narrowed by **D140 on 12 September 2026**. The
PowerPoint Limited Act v1 release closes the deterministic execution boundary
first. Ideate/Plan, semantic deck composition, and resume-with-edit remain
product requirements, but no longer block this release; they are stages 1–3
below.

- The current panel must support the complete reviewed PowerPoint Act proposal
  and the compact execution surface. Full Ideate/Plan activation follows in
  stage 1.
- After one approval, the runtime **decomposes into steps and performs them
  one at a time**, showing `Step N of M` on the bar.
- It must **work in front of the user, live**. A result assembled invisibly
  and handed back is worth nothing.
- **A pointer that is shown is a pointer that is acted on (D109).** Where a
  control is clicked, the pointer travels there, the label appears, the dwell
  elapses, and the click lands where the pointer is. Where no control is
  clicked, no pointer is drawn.
- Pause and Stop are in v1. Resume with an edited plan follows in stage 3
  (D110).
- Semantic PowerPoint capabilities follow in stage 2 (D111).
- Planning context lives in **`idea.txt`**, hashed and bound to each proposal,
  never execution authority; its manager activation follows in stage 1.
- The stage-1 local planner is **`qwen3:4b-instruct`** over the Ollama REST API.
  Measured on this laptop: RTX 3050 with 4 GB VRAM, 15.7 GB RAM. An 8B at q4
  (~5.2 GB) does not fit VRAM and is unsuitable as a responsive planner here.
  A 7B may be benchmarked later as a slower deep-planning mode, and adopted
  only if it fits and measurably improves the result -- which requires
  re-running the three-lane model gate.
- The same deterministic campaign machinery becomes the **unattended test
  operator** for later phases, so a human is not needed to click through
  acceptance runs. It is a campaign system, not a model-controlled mouse.

**Build order for this phase, as specified:**

1. Finish the deterministic Act execution path.
2. Shared signed generic UIA adapter (D108).
3. PowerPoint `New Slide` UIA end-to-end vertical slice; Excel remains the
   historical feasibility vehicle and is non-gating under D140.
4. Visual receipts, verifier modes, interruption.
5. Unattended deterministic campaign runner.
6. Repeated PowerPoint object-model and UIA campaigns.
7. After activation: `idea.txt` and the local clarification/planning loop.
8. Then semantic PowerPoint capabilities and model-composed plans.
9. Then resume, recovery, and edited-plan reapproval.
10. Much later: VLM and restricted raw input under a reviewed D006 amendment.

**Test task for the phase:** a 10-slide investor deck for this product,
covering Problem, Value Proposition, Founders, Business Model, Traction,
Revenue Model and Fund Utilization, built live while the user watches.

### Why the UIA proof moved from Excel to PowerPoint

Excel entered because PowerPoint's Act path is COM object-model and never
exercises UIA, so the plan needed a second application to prove the generic
UIA backend. Phase B measured Excel's `Add Sheet` passing outright.

That reasoning was sound and no longer points at Excel. Under D109 a COM
operation draws no pointer, so a PowerPoint-only COM build never shows the
cursor -- which is the central thing this phase is for. PowerPoint has its own
UIA surface (ribbon, New Slide, Design tab, Animation Pane), so proving UIA
there keeps one application and puts the visible pointer inside the real deck
build.

Cost: re-run the read-only feasibility probe against PowerPoint's ribbon. The
probe exists and Phase B proved it works. Excel's measurement is not wasted --
it validated the probe and the identity-policy shape against real measured
data, and Excel remains a fallback if PowerPoint's ribbon does not expose a
usable pattern.

### Live checklist

Marked as work completes. `[x]` means done AND its tests pass; `[~]` means
built but not yet exercised by a caller or a live run.

**1. Deterministic execution path**
- [x] Operation schema: backend, selector, identity policy in `operations.json`
- [x] Receipt gating before each effect — wired: a UIA node with no presentation surface refuses
- [x] Identity check before each pattern call — repeated inside the signed UIA adapter against the same element it invokes (D114)
- [x] UIA observation and overlay call `coordinate_space`; malformed,
      unbracketed, cross-awareness, topology-drifted, and HWND-mismatched
      geometry is rejected before paint/dispatch. UIA geometry must be
      physical pixels, baseline/confirm contracts agree, and the overlay
      brackets each paint (D115/D116). Boundary D032 re-review is READY;
      paint remeasurement remains.
- [~] Before/confirm/after are sequenced and the real baseline reaches live verification; explicit verifier-mode wire vocabulary remains to be closed
- [x] Per-node authorization minted only after the identity check passes

**2. Shared signed generic UIA adapter (D108)**
- [x] `plugins/shared/uia_adapter.py` — Invoke, Select, Toggle, Value, LegacyIAccessible
- [x] Copied byte-identically into the PowerPoint payload and signed there
- [x] Input-synthesis scan covers it (`plugins/shared` added to ADAPTER_ROOTS)

**3. PowerPoint UIA feasibility and first pointer-visible action**
- [x] Read-only probe against PowerPoint's ribbon (live desktop)
- [x] Record evidence; chose `New Slide` — `docs/evidence/act-powerpoint-uia-feasibility.md`
- [x] Signed selector + identity policy — `powerpoint.new_slide_uia`
- [x] One end-to-end action: pointer travels, label appears, dwell, invoke,
      independent verification — run 4, 3 Sep 2026, verified/live_state
      (`docs/evidence/act-live-pointer-run.md`). Adoption still needs 3/3
      through a real approval, which the diagnostic does not mint.

**4. Visual layer, receipts and interruption**
- [ ] Rail mode selector: Ideate / Plan / Teach / Act
- [x] `Step N of M` wired to Act (executor-reported, never counted by the rail)
      — `ghostcursor/act_rail.py`, live on 4 deck builds
      (`docs/evidence/act-deck-build-with-rail.md`)
- [x] Ghost pointer, ring, callout, interpolation — all WM_PAINT-owned
      (`pointer_path.py`, `overlay/cue.py`, `overlay/window.py`)
- [x] Trust presentation: cyan object-model, violet UIA, neutral in flight
      (`overlay/cue.py` `TRUST_COLOURS`, sourced from `trust_for()`)
- [x] Presentation receipts wired to the worker (`act_overlay`, `act_uia_session`)
- [x] Manager UI-thread bridge owns/pumps the overlay and returns receipts to
      the Act worker (`act_ui_bridge.py`, D118). The surface is sealed against
      forged receipt producers, including unregistered instances of the exact
      overlay class, and Pause is rechecked after authorization;
      boundary D032 verdict is READY; live manager proof remains pending
- [~] Pause / Stop during a run — MEASURED live 3 Sep 2026:
      Stop 0.094-0.187s (D020 ceiling 0.5s), zero nodes started after,
      in Quick and Watch, during pacing and during execution.
      Pause held 4.06-4.47s then resumed to 255/255.
      (`docs/evidence/act-interruption-live.md`)
- [x] Presenter stop points measured on the UIA vehicle 3 Sep 2026:
      traversal/settle/confirmation/dispatch, 0.016-0.031s, zero dispatches.
      Found and fixed a real gap: execute_node had no stop awareness, so a
      Stop after the cue went unnoticed until the node ended.
- [ ] Resume-with-edit: re-plan, re-validate, re-approve remainder (D110)

**4b. Watch Build** — DONE 3 Sep 2026
- [x] Two modes: Quick Build (executor speed) and Watch Build (paced)
- [x] Pacing waits are sliced and interruptible, never a plain sleep
- [x] Visible slide follows the node being built (adapter view-follow)
- [x] Region highlight + label on the changing area, no cursor —
      `PointsToScreenPixelsX/Y` probed and working on 16.0.20326;
      221 of 255 nodes, the other 34 touching no shape
      (`docs/evidence/act-deck-build-with-rail.md`)

**5. Unattended campaign runner** — DONE 4 Sep 2026
      (`ghostcursor/devtools/act_campaign.py`)
- [x] Resolves exactly one approved window; restores it if minimized,
      re-checked before EVERY attempt, refuses on 0 or 2+ (D075)
- [x] Fresh store and output path per attempt, handed by the runner
- [x] Records code, nodes, published digest and timing per attempt
- [x] Stops at the first attempt that is not clean; an `interrupt_probe`
      record refuses the whole campaign
- [x] Serial only; a test asserts no parallel or thread path exists (D025)

**6. Transactional output** — DONE 3 Sep 2026 (`ghostcursor/act_staging.py`)
- [x] Same-volume staging; final path absent until fully verified
- [x] Atomic publish; failed runs never publish a partial file
- [x] Retained staging files carry an explicit `.incomplete.json` marker
      Verified live both ways: a Stop at node 45 leaves the approved path
      absent and a labelled 49437-byte partial in `.staging`; a complete run
      publishes 94371 bytes atomically with a matching digest.

**7. Measured budgets (Phase E)**
- [x] Checked paint cost remeasured after D116, including coordinate admission
      before and after every real `WM_PAINT`. Three 400-frame live runs retain
      the 2 ms budget (`docs/evidence/act-paint-budget.md`).
- [x] Verifier spawn-to-response — max 0.188s, mean ~0.142s over 765
      invocations (`docs/evidence/act-diagnostic-rerun.md`)
- [x] Receipt deadlines — the retained records derive
      `first_paint_deadline_ms = 28`,
      `completion_deadline_ms = 1100`, derived from three runs with 60
      sequential cues and 60 independently created first cues each
      (`docs/evidence/act-receipt-budget.md`, records under
      `docs/evidence/receipt-budget/`). Production carries them as
      `MEASURED_*` constants in `ghostcursor/act_cli.py`. This line was
      missing while the measurement existed, and an activation reviewer
      concluded from its absence that the deadlines were invented (D137).
      The live benchmark was repaired after D115/D116: its synthetic rectangle
      now carries a real bracketed coordinate contract, so it measures cues
      instead of receiving `render_rejected` for every one.
      The earlier records contained only three independent first-cue samples
      in total. The replacement records contain 180/180 independently created
      first cues and 177/177 travelled cues with zero rejected samples;
      production is aligned. A fresh independent D032 review at `63c5ca5`
      re-hashed the records, reproduced the render and arithmetic, killed both
      derivation omissions, and returned READY: this receipt gate is complete.
- [~] Confirmation-to-invoke deadline — measured and enforced (D145):
      three complete 60-sample runs derive 1280 ms round trip and 32 ms
      confirmation-to-request, signed into `operations.json` and refused at
      runtime. `docs/evidence/act-confirmation-budget.md` re-renders from its
      records, one failed run is retained and listed as excluded, and
      `tests/test_confirmation_budget_is_enforced.py` recomputes the signed
      values from the raw samples (D150). Its independent review has no
      retained record, so that review is still open.
- [ ] Interruption latency matrix — **not measured**
- [~] Independent D032 review of the derived budgets — the receipt budget is
      READY at `63c5ca5`; the confirmation budget has retained records and
      enforcement but no retained review record (D150).
      An activation
      re-reviewer recomputed them (p99 x 2.0, ceiling, floored at the 15 ms
      tick, highest applicable travelled/first-cue sample across three runs ->
      the superseded 29 and 1121) and called the earlier derivation
      document an unusually careful D034 record. That is a spot check inside
      another review, not the gating review, and it says so (D138).

**8. The brief and the local planning loop** (D113 — a brief is the
   stored conversation; `idea.txt` is one, and is not special-cased)
- [x] `idea.txt` written as the stand-in Ideate conversation
- [x] Brief store: append turns, load back, digest the exact bytes
      (`ghostcursor/brief.py`)
- [x] Bind a brief's digest to each proposal — re-read at bind time,
      so an appended-to brief refuses rather than binding a stale digest
- [x] `ClarificationRequired` vs `PlanProposal` as mutually exclusive outputs
      (`task_planner.py`: `ClarificationRequired` is a separate type from
      `TaskGraphProposal`, "impossible to confuse"; outcomes are "clarification"
      | "plan", validated exclusive)
- [x] Keep asking until required fields resolve (`planning_session.py`: "ask
      until the model knows enough to plan, then stop asking", capped at
      `MAX_CLARIFY_QUESTIONS`)
- [x] Pass only the active plugin's capability catalog to the model
      (`task_plan_steps(validated, registry)` is scoped to the given
      `CapabilityRegistry`)
- [x] Store proposal separately from approved plan (`TaskGraphProposal` vs
      `act_runtime.approve_action_graph`; proposal carries no authority)

**9. Semantic PowerPoint capabilities (D111) — SUPERSEDED by D161/D164/D186.**
These are the retired hand-written-pack deterministic ops. The model-driven path
replaces them: `ghostcursor.workspace` plans a grounded DeckSpec (`make_deck`) and
builds it in PowerPoint through the gated Act path (`build_deck`, D186), with
PowerPoint now a test fixture (D164), not a hand-authored capability set (D161
retired packs). Left unchecked as historical; building these would re-introduce
the retired approach.
- [ ] `create_deck`, `apply_theme`, `create_title_slide`, `create_problem_slide`,
      `create_comparison_slide`, `create_timeline_slide`, `create_metric_cards`,
      `create_chart_slide`, `add_speaker_notes`, `apply_restrained_motion`,
      `inspect_deck`, `publish_deck`
- [ ] Each expands deterministically into reviewed low-level operations
- [ ] Local model composes a 10-slide deck from `idea.txt`

**10. Acceptance and release**
- [ ] Three consecutive PowerPoint campaigns — two 3/3 clean campaigns ran on
      11 Sep 2026 (harness, and manager-path through the real `Approve & run`).
      **Both are reclassified diagnostic (D139)** and retained under
      `docs/evidence/diagnostic/`: three transcripts elsewhere were found edited
      after capture, and evidence produced during that repair cannot close the
      gate. A fresh campaign runs after a READY verdict. Prior wording: **3/3
      clean on 11 Sep 2026**
      against the rebuilt bundle (manifest `28dbaf2d`, plan `84e39d0d`),
      255/255 nodes each, three distinct published artifacts
      (`docs/evidence/act-acceptance-campaign-2026-09-11.md`). The 4 Sep runs
      are superseded: their bundle is no longer reproducible.
- [~] Animation-catalog campaign — the signed plan `animation-catalog-v1`
      (intent `BUILD_ANIMATION_CATALOG`) now exists, covering all 15
      category/effect pairs the adapter accepts, every trigger, and the
      none/fade/morph transitions (D151). It has not been run or counted.
      Scope (D152, corrected D154): the artifact verifier confirms that an
      animation was added to each target object and, for a `fade` or
      `morph` transition, that some transition was written; for `none` it
      checks nothing. It does not verify effect, category, trigger,
      direction or order in the saved file, so a green catalog campaign
      shows the adapter's requests were accepted and targeted the right
      objects, not that each effect landed as specified. The campaign
      retains the published decks so that can be examined afterwards.
- [ ] All lanes green independently
- [x] D032 pre-sign review — three independent cold passes; 26 + 4 + 3
      findings, all fixed. The blocking one was a COM retry that could
      duplicate a slide in a signed artifact.
- [x] External non-ephemeral signing key — `ghostcursor-release-2026-3`,
      generated outside the repo, public half committed, pair verified
      through the production PluginStore path
- [ ] D032 activation review — a remediation review of `63cd2b5` is
      recorded here as READY, but no record of it is retained (D152); the
      activation review is NOT READY pending the gates listed below

**Already built, awaiting a caller**
- [~] `ghostcursor/stages.py` — stage and cue validation
- [x] `ghostcursor/coordinate_space.py` — called by the signed UIA producer,
      strict host parser, overlay admission, and final pre-dispatch check (D115)
- [~] `ghostcursor/act_protocol.py` — receipts, refusal codes, trust classes
- [~] `ghostcursor/uia_identity.py` — signed per-operation identity policy
- [x] Phase A: 255/255 diagnostic run — `docs/evidence/act-phase-a-diagnostic.md`
- [x] Phase B: UIA feasibility probe — `docs/evidence/act-phase-b-uia-feasibility.md`

**Act acceptance remains open under D139.** The reproducibility defect
recorded here on 6 September was repaired. Its cause was real: the
signed payload bytes in the working copy were CRLF while git stored LF, so the
pin, the built bundle and every digest in the retained r5 transcript named a
file no clean checkout produced. LF is now canonical (D125), the PowerPoint
bundle was rebuilt and re-signed at manifest `28dbaf2d` after two further
rebuilds for signed build products (D127) and for redaction (D128), and again
at `3a4f8c57` when D145 added signed UIA timing fields (D149), and at
`6dbd5ba2` when the animation-catalog plan was added (D151), and at
`b0d63512` for the D152 review fixes, and
`tests/test_powerpoint_manifest_pin.py` recomputes that manifest from tracked
sources so the figure cannot drift unnoticed. The seventh independent D032
review returned READY at `45d1323` (D134), and the 3/3 campaign ran on 11
September (D135), but D139 subsequently reclassified both harness and manager
campaigns as diagnostic. The r5 and r1 transcripts stay uncitable.

**What is still open, with its own gate.** Completion requires the following:

| Open item | Gate before it moves |
|---|---|
| Fresh counted campaign | harness path ACCEPTED for its narrow claim (D160). Manager path: three real runs completed 255/255 but both campaigns were refused for procedure (D163, D165); a counted manager campaign is optional under D164 |
| UIA slice `add-slide-uia-v1` | **dropped as a release gate (D164)**: PowerPoint is a test fixture; generic UIA Act comes through the harness (ROADMAP harness track step 5) |
| Animation-catalog campaign | **dropped as a release gate (D164)**; the signed plan stays as a fixture |
| Independent lane runs | NOT accepted (D160): prose without retained output; re-run alone through a capture wrapper |
| D032 review of the derived budgets | receipt budget READY at `63c5ca5`; confirmation budget (D145) review open, no retained record (D150) |
| D032 activation review | PowerPoint-plan activation is no longer a goal in itself (D164). Generic Act activation is decided when the harness Act step exists (tier 1 review, D162) |
| Semantic PowerPoint capabilities | superseded by the model-driven harness (D161, D164) |
| Agent / skills / marketplace program | activation review READY, then its own phase entries here |

Do not read "acceptance closed" as permission to start semantic planning or the
agent program. **Activation has been reviewed and refused repeatedly** — at
`a1739aa` (D137), at `f19eaaf` (D138), in the third round recorded as D139, and
at `63cd2b5`. The pre-campaign READY review of `b1ba80a` (30 September) also
returned NOT READY (D150). No activation round has returned READY.

**The next integration milestone remains the live manager-approved pointer
action.**
Paint recertification and its independent boundary review are complete. The
first production proposal attempt exposed an integration contradiction: Act
plans were deliberately recipe-independent, while `prepare_act_goal()` called
the recipe-only form of `authorize_intent()` and therefore refused every
unadopted signed plan. D120 repairs the single gate with distinct,
non-interchangeable recipe and action-plan tokens. The first D032 review found
that an injected lookalike store could still supply an exact-type fabricated
context; production preparation no longer accepts a store argument, and Act
authority now requires the exact `PluginStore` to have issued the exact
context from signed on-disk state. Six focused provenance mutations are
killed, and the fresh D032 re-review returned READY with no findings. One live
run using the manager-owned presentation surface completed `ADD_SLIDE`, with
PowerPoint moving from one slide to two and the signed live verifier confirming
the change. Its D032 review returned **NOT READY**: the deleted one-off probe
called `_ActWorker` directly, so it did not prove the explicit manager
`Approve & run` event and left no independently inspectable transcript. D121
now makes that event structural: `_ActWorker` consumes only a one-use request
issued by the manager approval command and rejects bare, forged, or replayed
values. Six D018 mutations of that boundary are killed, and the owner confirmed
the boundary's independent D032 review on 9 September 2026. The replacement
run now crosses the visible approval event, exact-target focus handoff, worker,
signed UIA adapter, and independent live verifier, ending completed at 1/1.
Its bounded transcript is retained at
`docs/evidence/act-live-manager-d123-r5.jsonl`; the D122 audit and D123 handoff
mutation suites are green. Obtain a fresh D032 review of that code and evidence.
Only after that review passes should staged-plan schema wiring or semantic
PowerPoint capabilities move forward.

**Manager shell refinement (D124): implemented candidate.** The manager now
starts as a right-side compact panel and expands the same HWND into the centred
planning/review workspace. Planning, proposals, target recovery, and failures
expand it; issuing an approved execution request or completing successfully
collapses it; Stop/failure reopens it; ordinary executor events never override
a user's manual expansion during the run. Focused manager and
input-boundary tests are green. A real-desktop visual inspection and an
independent D032 review remain before this presentation change is treated as
accepted evidence.

The first retained native-manager attempt on 9 September crossed proposal
display and the real approval command, then failed closed at the signed UIA
adapter with zero completed nodes. A read-only probe reproduced the cause on
the exact approved `Presentation1` HWND: while the manager retained foreground,
PowerPoint exposed only title-bar controls and no `New Slide` button. D123 adds
the missing exact-HWND focus handoff before request issuance. The corrected
retained run completed and independently verified the one-slide increase. The
failed attempt remains diagnostic and cannot count toward acceptance; the
successful replacement remains pending D032 evidence review.

**Act v1 is deliberately not general computer use.** No mouse or keyboard
synthesis (D006), no VLM-driven clicking, no cross-application graphs, no
conversationally generated workflows. It acts through a signed object-model
adapter or a signed generic UIA adapter (D108), on approved applications.

---

## Agent, skills, and first-party marketplace program

**Source:** the owner's plan of 11 September 2026
(`ghostcursor_agent_skills_marketplace_plan.md`, kept outside the repo).
Recorded here because a phase that exists only in conversation is not a phase.
**Status: stage 0 in progress, stage 1 not started.** Later stages are not built.

The program's own ordering principle is that the Agent Orchestrator coordinates
work and never becomes an execution-authority shortcut — every effect still
goes through `authorize_intent()`, signed components, per-node authorization
and independent verification. That is a restatement of D087/D090/D100-D104, not
a new boundary, and it is the reason the program can be sequenced at all.

| Stage | What it is | State |
|---|---|---|
| 0 | Close PowerPoint Limited Act v1 | **In progress** — exact scope in D140; requires current budget/release reviews, counted campaigns, animation and independent lanes |
| 1 | Ideate and Plan in the manager | Not started; gated on PowerPoint Limited Act activation |
| 2 | Semantic PowerPoint capabilities and Deck Agent | Not started |
| 3 | Resume, recovery, and edited-plan reapproval | Not started |
| 4 | Skills and expert modules | Not started |
| 5 | Structured agent executor | Not started |
| 6 | MCP connectors and side-effecting integrations | Not started; cloud *reasoning* left this stage under D147 and may be built with the provider gateway; connectors that mutate external services stay here with scoped tokens, vault, audit and revocation |
| 7 | First-party marketplace | **MVP started (D186, owner lifted the hold 21 Oct 2026).** Read-only catalog built: `ghostcursor plugins catalog <dir>` verifies each `.ghostplugin` through the SAME `verify_bundle` the store installs through and lists what is installable (id, version, signed, compatible, digest) + a local revocation denylist check (refuse-only). Install stays `PluginStore.install`. **Still gated (D144, next, tier-1):** publisher-key identity in the manifest, a SIGNED revocation list (not just a local denylist), and re-sign provenance — each needs tests + D018 mutation + independent review before it changes the trust path. |
| 8 | Cross-application agents | Deferred; requires a reviewed D087/D090 amendment |
| 9 | Restricted general computer use | Deferred; requires a reviewed D006 amendment |

**Stage 1 reuses what exists** — `task_planner.py`, `planning_session.py`,
`task_graph.py`, `inference/ollama.py`, brief persistence, the manager proposal
UI — and adds the missing flow: goal → clarification → persistent brief →
capability-scoped graph → complete flattened plan → one approval → Act. Under
D113 the brief is planning context and never authority, and its exact bytes are
bound to any proposal made from it.

**Four conflicts this program had to resolve rather than inherit quietly.
Three are resolved by recorded decisions on 16 September 2026; one remains
deferred:**

1. **Stage 8's cross-application agent versus D087/D090 — still deferred.** A
   graph composes capabilities of one plugin. "General Windows agent" here
   means routing an intent to the right supported plugin, not composing across
   plugins. Cross-application graphs stay deferred under the row in the table
   below until a reviewed cross-plugin authority design exists.
2. **Stage 6's cloud reasoning versus D017 — resolved by D141, re-sequenced
   by D147.** A configured cloud provider is the default reasoning provider
   for the trial period and is no longer stage-6 gated. Local stays supported
   and tested. Side-effecting connectors and telemetry remain gated.
3. **Stage 7's marketplace versus deferred key rotation — resolved by D144.**
   A signed key manifest, a revocation list checked on every catalog load and
   within D020's ceiling by the authority monitor, and a re-sign procedure
   with provenance must exist before any bundle is re-keyed. Excel and VS Code
   stay quarantined until then (D128).
4. **Stage 2's application-named agent versus the no-application-code rule —
   resolved by D142.** Agents and Skills are signed, plugin-scoped data; core
   ships one generic agent executor and no application-named Python. Named by
   the activation review; it was missing from the first three (D137).

**Added to stage 1 by D143:** Spatial Context v1 — a `SpatialContextReference`
appended to the brief as bytes, resolved inside the signed plugin, never a
selector or authority. It is the first item after activation, not part of
Limited Act v1.
Stage 0 covers PowerPoint object-model execution plus the PowerPoint `New Slide`
UIA slice. Excel and VS Code are outside this release boundary under D140. The
animation catalog, independent lanes, counted campaigns, budget review, and
activation review remain open above; stage 1 does not start before the final
activation review returns READY.

---

## Self-maintaining software — commercial wedge track (D148)

> Detect an external API/SDK/spec change, map it onto a repository, repair it
> in an isolated checkout, run that repo's own build/lint/tests, and present a
> draft PR with its evidence for human approval.

**Status: not started.** Plan: `docs/orbyn-plan/mp8-self-maintaining-software.md`.

Restored from a sub-bullet of the final Mega Phase to a first-class track
(D148): it was adopted as the first commercial wedge, and a wedge that cannot
produce evidence until twenty other phases close is not a wedge.

**It does not depend on** Spatial, Personal Brain, Act activation, semantic
PowerPoint capabilities, the marketplace, or collaboration, and must not be
sequenced behind them. It depends on the provider gateway (cheaper under
D147), an isolated execution environment, and scoped repository access.

**Boundaries it inherits:** read-first scoped repo access; isolated
branch/worktree; no production write path; explicit human approval before PR,
merge or deploy; repository content, issues, changelogs and release notes are
untrusted content; every candidate patch carries its trace and evidence;
secret scanning before any diff leaves the isolated environment.

First proof is one repository, one provider, one real change, suite green, PR
opened only on approval. Breadth of provider coverage is not the demo.

---

## Phase 4 — B2B

> Company workflow packs, tenant separation, roles/permissions, shared
> WorkflowSessions, handoff, pre-diagnosed support, private telemetry.

**Status: not started.** "Private telemetry" stays off by default under
D141; cloud reasoning is available under D147. Tenant separation and roles have no design yet.

---

## Phase 5 — Organizational knowledge

> Company knowledge ingestion, reviewed skills, provenance, organizational
> memory, async multiplayer.

**Status: not started.** D070 already reserves the shape: curated knowledge
lives in a separate local `knowledge.sqlite`, distinct from erasable
screen-derived `kb.sqlite`, and neither is execution authority.

---

## Phase 6 — Dynamic interfaces and third parties

> Dynamic task interfaces, cross-app workflows, richer agent mode, expert
> marketplace, third-party plugin SDK.

**Status: not started.** Two constraints already bind it: a task graph may
compose only capabilities of **one** enabled plugin (D087/D090), so cross-app
workflows need that boundary reopened by a reviewed decision; and a
marketplace implies third-party signing, key rotation and revocation, all of
which are explicitly deferred today. The first-party marketplace is stage 7;
third-party publishing remains deferred beyond the numbered program until its
signing, revocation, sandboxing, and review model is separately approved.

---

## Phase 7 — Long term

> Human intent → person/org/software understanding → dynamic workflow and
> interface → human/agent collaboration → verified outcome → learning.

**Status: thesis, not a plan.** Recorded so the earlier phases can be checked
against it, not scheduled.

---

## Capability modules

`02_modular_ideation_execution.md` §11 lists attachable modules. Current state:

**Built:** Personal/Project Memory (local), Workflow Builder (declarative
compiler), Artifact Intelligence (verification of saved artifacts),
Ideation (`session.ideate`), Voice (`voice.py`, `/dictate`), Company Knowledge
(`workspace/knowledge.py` Company Brain + backlinks), Learning/Skill Tracking
(`workspace/usage.py` recurring-use), Agent Orchestration (`workspace/crew.py`,
`/crew` + saved crews), Multiplayer/Handoff (mission-file handoff, D180 slice 4),
Enterprise Policy (`policy.py`, D180), Critic/Evaluation (`workspace/critic.py`,
`/critique` — advisory plan review). See the D186 workspace section below.

**Partial:** Autonomous Execution (Act v1, in flight); Analytics (`/stats`
counts only).

**Not started:** Expert Reasoning (deep multi-step reasoning mode), Dynamic UI
(a generated interface surface) — neither specified yet.

**Available under D147:** cloud reasoning through the provider gateway.
**Still gated:** Telemetry, Sync, and side-effecting connectors — D141/D144
record those boundaries; build only in a reviewed slice.

---

## Workspace feature wave (D186) — built

The console workspace (`python -m ghostcursor.workspace`, D173) grew a full
solo-MVP feature set. All tier-2/3, each its own commit with tests, hermetic
lane green (~3550). None adds input synthesis or egress; the tier-1 Act
boundary is untouched (every slice verified against
`tests/test_no_input_synthesis.py`).

| Area | What | Entry |
|---|---|---|
| One-step | classify a task → run the right capability | `/do` |
| Orchestration | manager decomposes a goal into ordered capability steps, chained through the Brain; saved/replayable | `/crew`, `/crew save\|run\|list` |
| Deck | outline-first DeckSpec, Brain-grounded; propose a PowerPoint build plan (reviewed, propose-only) | `/deck`, `/deck build` |
| Research | decompose → cited per-part → file claims to Brain | `/deepresearch`, `/research` |
| Notes | tidy rough notes/file into a structured summary (Granola, no recording) | `/notes` |
| Attach-context Q&A | answer grounded on clipboard/file, records nothing (Highlight) | `/ask`, Work “Ask a file” for small text files |
| Company Brain | facts/edges, sensitivity, review gate, backlinks | `/know`, `/related` |
| Skills + learning | draft/replay skills; offer to save a recurring task (Attention Engineering) | `/skill`, recurring-use nudge |
| Checklist | per-workspace todos; from an approved plan | `/todo`, `/todo from plan` |
| Library + export | find across saved items; shareable Markdown snapshot (secrets scrubbed) | `/find`, `/export` |
| Local utilities | file convert (+PDF/subtitle/clipboard image), diff, b64/url/hex/uuid/pass/time/json/slug/sha256 | `/convert`, `/diff`, `/x` |
| Delight | fuzzy did-you-mean, inline calculator, clipboard history, snippets, global capture hotkey, tips, startup status, sticky pins | palette, `/clips`, `/snippet`, `/capture`, `/pin` |
| Work hub | Work card board previews the current run, newest visible finished research result, latest answer and plan with direct navigation/Stop; the latest 20 locally saved generic task states and reusable agents remain below it; stale running work becomes interrupted on restart | workspace app |
| Desktop island and full workspace | Small movable topmost capsule by default, grows for work/new result, idle Hide/shortcut recall and monitor clamping, direct Work result link, palette-matched native Open/Stop/Quit; `--window` opens the full floating Edge app and `--dock` its right-side layout. Chat, Plan and Brain have guided empty states and Brain section navigation | workspace app |
| Background research | Explicit read-only research on the existing single worker; local 20-job inbox with Markdown download, up to five kept results, reversible archive view and one-off follow-up on the first 8,000 saved-result characters, Stop, interrupted-on-restart; no automatic retry | workspace app |
| Research routines | Hourly/daily/weekly read-only research on the same worker; local schedules, pause/resume/run now/delete, one missed run after wake, explicit Quit; a rerun lists claims new since the previous run | workspace app |
| GitHub read-only connector | Explicit fine-grained token in Windows Credential Manager; bounded repository and issue views, local disconnect; no write authority or model/routine bridge | workspace app |

The packaged Work interface had a live Chat/Plan/Brain/Work and GitHub run on
26 October 2026 (`docs/evidence/workspace-live-acceptance-2026-10-26.md`). A
restart-and-time-jump test covered one missed routine after downtime; actual
PC sleep was not run at the user's choice. This does not close Teach/Act
release acceptance.

The user-level installer now stages a replacement build and rolls back a failed
switch (`docs/evidence/installer-update-2026-10-28.md`). App signing, an automatic
update channel, and observed novice onboarding remain release work. Chat now
has a one-time, local first-run guide to the composer and Brain Setup
(`docs/evidence/first-run-guide-2026-10-28.md`).

Critic/Evaluation (`/critique`) reviews the current plan for gaps and risks
before Act — advisory, read-only.

**Not yet (recorded, not built):** `/crew` emitting a `/deck build` step for a
one-goal research→outline→propose chain; dictation→`act.py` typing (tier-1,
D006 amendment); capture→steps recording. These stay named, not faked.

---

## Deferred, with the decision that defers them

| Item | Deferred by |
|---|---|
| Mouse/keyboard synthesis | D006 — needs its own reviewed amendment |
| VLM perception tier 3 | Teach-only when it lands; never action authority |
| Cross-application task graphs | D087/D090 single-plugin boundary |
| Telemetry, sync | D141 — off by default, events not content; not yet built |
| Cloud reasoning models | **Not deferred.** D147 makes a configured cloud provider the trial-period default; local stays supported |
| Side-effecting connectors | D141/D144 — scoped tokens, vault, audit, revocation first |
| Key rotation and revocation | D144 design required before any re-key or marketplace stage |
| In-place editing of user files | Needs backup/rollback/recovery decision |
| Installer, tray, startup, web retrieval | `docs/superpowers/FOLLOWUPS.md` |
