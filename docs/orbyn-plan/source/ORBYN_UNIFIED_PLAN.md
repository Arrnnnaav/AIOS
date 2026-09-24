# ORBYN (GhostCursor) — Unified Plan: Origin → Current Build → Scale

Source: `C:\Users\user\Desktop\idea build\addons.md` (all ~16,460 lines, read in full)
reconciled against the repository (`CLAUDE.md`, `ROADMAP.md`, `FLOW.md`, `DECISIONS.md`
D001–D140, `docs/evidence/`). Date: 16 September 2026.

Nothing in the repo was changed. Where `addons.md` and the repo disagree, the repo
wins for *status* and the addons file wins for *intent*; each disagreement is called
out explicitly in §9.

---

## 0. One-page summary

**Thesis (locked in addons.md, final form):**
> Orbyn is the trusted execution layer where people and AI agents work together
> across the software a company already uses.

**Internal equation:**
> Apps provide capabilities. Skills provide expertise. The Brain provides context.
> Agents pursue goals. Multiplayer coordinates people and agents. The Runtime
> controls authority and verifies outcomes.

**Category line:** *From digital adoption to verified digital execution.*

**Four pillars** (every feature lands under one):

| Pillar | Contents |
|---|---|
| Intelligence | Personal Brain, Company Brain / Context Graph, Experts, Model Router |
| Capabilities | Connected Apps, Plugins, Skills, Packages, Marketplace |
| Execution | Runtime, permissions, Needs You, Act, verification, sandbox, audit, rollback |
| Collaboration | Missions, Workstreams, presence, Join, handoffs, Coordination Engine, Mission Control |

**Where we are (repo truth):** Phase 1 (Teach runtime) built and gated. Phase 3
"PowerPoint Limited Act v1" (D140) implemented but **activation NOT READY** — two
activation reviews refused, both 11-Sep campaigns reclassified diagnostic (D139).
Everything in addons.md beyond a single-app, single-user, single-agent loop is
**not built**.

**Four YC RFS ideas were adopted, as layers of one runtime, not as separate
products:** Self-Maintaining APIs (first B2B wedge candidate), Multiplayer AI
(Collaboration Kernel), Dynamic Software Interfaces (side panel ↔ Mission Control),
Company Brain (Context Graph — the intelligence layer every other layer consumes).
Two non-YC sources were also adopted: HeyClicky's spatial context (→ core primitive
"Spatial Context") and Amoeba (→ Missions, Workstreams, Mission Control, Coordination
Engine, staleness-aware Brain).

---

## 1. How the idea evolved (the lineage, in order)

| Stage | Trigger | What changed |
|---|---|---|
| 1. GhostCursor | "AI explains, human still executes" | Desktop overlay that watches screen, points where to click, verifies. Hard rule D006: never acts for the user (Teach). |
| 2. Mode continuum | Users want different authority levels | IDEATE → DISCUSS → TEACH → ASSIST → ACT → AUTOPILOT → WATCH. Principle: *appropriate authority, not maximum autonomy.* Repo implements Ideate/Plan/Teach/Assist/Act only. |
| 3. Core + Plugins | LLM pixel-guessing unreliable | Application knowledge leaves the core. Signed, data-only plugins; `observe/act/verify/rollback` contract. |
| 4. GitHub-repo plugins → **Apps** | Non-technical users can't pick repos | Repo Analyzer becomes *developer-side* SDK tooling. User sees "Connect PowerPoint / GitHub / Slack". |
| 5. Trust stack | Enterprise won't trust agents | Signed capabilities, authority levels 0–5, Needs You, independent verifier, audit, rollback, sandbox, credential vault. |
| 6. Company Brain | Agents can't operate without org context | Knowledge with provenance/owner/scope/review status. Rejected "PDFs in a vector DB". |
| 7. BusinessOS / GrowthOS | ABizCreator (Jaipur printing) real test | SEO / Search Console / WordPress-staging / GBP workflows. Proved the loop is industry-agnostic. **Not Orbyn itself**; a package on the runtime. |
| 8. Expert agents, packages, voice, Personal Brain | B2C distribution | Developer / Designer / Learning packages; experts ≠ plugins ("plugins provide capability, experts provide intelligence"). |
| 9. Spatial Context (HeyClicky) | Language is bad at spatial intent | Core interaction primitive, bidirectional, *reference not authority*. |
| 10. Connected Apps contract | Marketplace clarity | Every App exposes Observe / Act / Verify / Events / Permissions. |
| 11. Self-Maintaining APIs (YC RFS) | Need a concrete wedge | "Software that adapts when APIs change" → Self-Maintaining Software → Self-Maintaining Company. |
| 12. Multiplayer AI (YC RFS + Amoeba) | Work must be a shared object | Mission, Workstream, Join, handoff, presence, Coordination Engine, Mission Control, staleness-aware Context Graph. "Chats belong to Missions." |
| 13. Rename → Orbyn | "Cursor" too narrow | GhostCursor = historical name. |
| 14. Final fixed model | Stop changing architecture | Seven primitives, six phases, four pillars (§2, §6). |

---

## 2. Canonical object model (vocabulary is frozen — do not add user-facing primitives)

| Primitive | Meaning | Repo today |
|---|---|---|
| **Workspace** | Person/team/company boundary; holds humans, agents, apps, Brain, permissions, missions, policies | Not modelled (single local user) |
| **Mission** | Persistent outcome pursued by humans + agents together; owns goal, participants, plan, workstreams, resources, artifacts, decisions, approvals, evidence, memory, state | Partial: `session.py`, `SessionSnapshot`, `sessions.sqlite`, `brief.py` (a brief = stored conversation, hashed bytes bound to proposal, never authority — D113) |
| **Workstream** | Parallel subdivision of a Mission with owner, agent(s), objective, resources, permissions, deps, status | Not modelled |
| **Human** | Accountable participant; *work belongs to humans, agents execute it* | Implicit (one operator) |
| **Agent** | Goal-driven AI worker; uses Skills + Apps; never holds direct software control | Not modelled (program stage 5) |
| **Skill** | Declarative expertise / approved procedure with knowledge + workflow + permissions + tools + verification | Not modelled (stage 4) |
| **App** (Connected App) | Software Orbyn can observe/operate; exposes Observe/Act/Verify/Events/Permissions; behind it: API / MCP / signed plugin / UIA / vision fallback | Partial: signed `.ghostplugin` bundles (`PluginStore`), capability registry (`capabilities.json`, D087/D089), operation registry, adapters + verifiers. No connector/MCP/events layer. |
| **Resource** | Specific object being touched (slide, cell range, CRM record, branch, page…) | Partial: exact HWND/PID/executable binding; output-path binding; no generic resource model |
| **Artifact** | Produced/modified output with provenance | Partial: transactional staging + atomic publish (`act_staging.py`); artifact verifier |
| **Brain** | Personal/Company contextual intelligence → **Context Graph** internally | Partial: `kb.sqlite` (erasable screen-derived), `knowledge.sqlite` reserved by D070; no graph, no provenance model |
| **Needs You** | Human decision/approval queue; action-specific card (what / why / resource / requested-by / risk / rollback / verification; Allow Once / Modify / Reject) | Partial: `Approve & run` in native manager mints one-use `ActExecutionRequest` (D121); approval binds digest, plugin/version, manifest, catalog generation, exact HWND/PID/exe, output path, expiry (D100–D104). No risk/rollback fields. |
| **Mission Control** | Expanded operational UI: people, agents, workstreams, plan, activity, apps, artifacts, brain, approvals, evidence, collisions | Partial: D124 manager — compact right panel expands same HWND into centred workspace for planning/review/recovery. Single mission, single user. |
| **Runtime** | Planning, execution, trust, verification | Built (the bulk of the repo) |
| **Coordination Engine** | Ownership, scheduling, dependency resolution, resource claims, collision detection, handoffs | Not started; dependency ordering exists inside `task_graph.py` for one plugin's DAG |

Additional internal (non-user-facing) contracts named in addons.md:
`SpatialContextReference`, App Capability Contract, Universal Plugin Contract,
Event Bus, Model Router, Credential Vault, Sandbox, Policy & Risk Engine, Audit Log,
Health System, Test Lab, Artifact System, Capability Registry.

---

## 3. Target architecture (final form from addons.md)

```
ORBYN UI ............ Side Panel • Expanded HQ / Mission Control • Voice • Dynamic UI • Spatial Context
        │
COLLABORATION KERNEL  Missions • Humans • Agents • Workstreams • Presence • Ownership
                      Join • Redirect • Take Control • Handoffs • Comments • Resource claims
        │
CORE RUNTIME ........ Planner • Task Graph • Workflow • Event Bus • Policy/Risk • Permissions
                      Needs You • Verification • Sandbox • Audit • Rollback • Credential Vault
                      Coordination Engine • Model Router (local / workhorse / frontier / vision / embeddings)
        │                                   │
BRAINS ..............                       CAPABILITY LAYER
  Personal • Project • Company (Context     Connected Apps → { Connector(API/OAuth/MCP) • Signed plugin •
  Graph w/ provenance & staleness) •        UIA adapter • Vision fallback } • Skills • Experts • Packages
  Expert knowledge • Shared team memory     • Capability Registry • Event Sources • Permission Policy
        │
REAL SOFTWARE ....... PowerPoint • Excel • VS Code • GitHub • Slack • Salesforce • SAP • WordPress • …
```

**Execution preference order (locked):**
Structured API/connector → signed application plugin → bounded UIA → Teach/Assist fallback → refusal.
Vision-driven mouse manipulation is a fallback, never the architecture (and D006 forbids
input synthesis today).

**Authority chain (locked):**
Global Safety → Organization Policy → User Policy → App Permission → Mission Permission →
Action Authorization. A generated plan has zero execution authority. LLM output is a
proposal; deterministic code decides.

**Authority levels:** 0 Observe · 1 Teach/Highlight · 2 Safe navigation · 3 Reversible
modification · 4 External side effect · 5 Sensitive/high-risk.

**Verification rule:** *Execution is not completion. Verification is completion.* Verifier
is independent from the actor; deterministic checks first, semantic/LLM checks only for
qualitative outputs.

**Repo already enforces the strict version of this chain** — see §7.

---

## 4. YC RFS ideas: which, where, why

addons.md states explicitly: *"don't say you're building four YC RFS ideas simultaneously"*.
They are layers of one runtime. Positioning hierarchy from addons.md:

```
LONG-TERM CATEGORY   Shared Execution Layer for Human + AI Companies
PLATFORM             Company Brain • Coordination Engine • Mission Control • Trusted Runtime • Plugin Ecosystem
FIRST PRODUCT        Self-Maintaining Software
INITIAL WEDGE        Self-Maintaining APIs / Integrations
```

### 4.1 Self-Maintaining APIs (YC RFS by Harsha Gaddipati / Slashy)

| | |
|---|---|
| **RFS ask** | Detect external API change → find affected code → modify → test → open PR. Per-provider "update agents" or a neutral Dependabot-for-APIs. |
| **Verdict in addons.md** | Standalone company 4/10 · as Orbyn plugin 9/10 · as B2B dev wedge 9.5/10 · as path to self-maintaining software 10/10 |
| **Why adopted** | Fixes Orbyn's biggest story problem: "powerful but sounds broad". Gives a measurable, painful entry point. Maps 1:1 onto existing components (Repo Analyzer, Company Brain, Plugins, Event Bus, Model Router, Sandbox, Policy, Needs You, Audit, Rollback, Marketplace). |
| **Why NOT copied literally** | Category already crowded (Patchwork, Patchline, APISynQ, Repairo, KeelCat, mendapi). Dependabot does versions; Orbyn does *behaviour* ("Stripe changed PaymentIntent semantics → checkout.ts, subscriptions.ts, refund.ts"). |
| **Where it lives** | Marketplace category **Maintenance Agents** (Stripe, OpenAI, Shopify, AWS, PostgreSQL, WordPress, GitHub). Agent pipeline: Change Agent → Impact Agent → Planner Agent → Coding Agent → Verify Agent → Needs You → PR. Company Brain gains a **System Graph / Software Brain** (Checkout → uses → Stripe PaymentIntent → feeds → Order Service → writes → Postgres). |
| **Progression** | Stage 1 self-maintaining APIs → 2 integrations → 3 software → 4 company ("Google changes SEO guidelines → SEO agent → WordPress drafts → Needs You"). |
| **Scope discipline** | PoC = OpenAI + Stripe + one generic OpenAPI source; TS/Python repos; GitHub; sandboxed tests; PR. The demo is one real repo, not "we monitor 100 APIs". |
| **Metrics** | changes detected, affected resources correctly identified, repairs proposed, tests passed, PRs generated/approved, detection→resolution time, intervention rate, weekly repeat, paid conversion. **North star:** % of detected external changes resolved through a verified Orbyn workflow. |
| **ICP for this wedge** | API-heavy SaaS, dev-tool startups, vertical SaaS, infra companies, integration/platform teams. Buyers: CTO / VP Eng / EM / Platform Lead / Integration Lead. 5–10 design partners → observe real maintenance events → first provider agents → paid pilots. |
| **Repo status** | Not started. Requires: GitHub connector, code sandbox, network access (**blocked by D017 local-only**), Company Brain, agent executor (stage 5). |

### 4.2 Multiplayer AI (YC RFS) — via Amoeba

| | |
|---|---|
| **RFS ask** | Multiple humans + their agents share one piece of work, one context, one plan, one live state; extend beyond engineering to sales, support, legal, marketing. |
| **Verdict** | Use Amoeba's ideas inside Orbyn 9.5/10 · compete as multiplayer coding IDE 3/10 · "Amoeba for the whole company" literally 7/10 · make Missions + Mission Control + Coordination Engine fundamental runtime pieces 10/10 |
| **Why adopted** | AI work must stop being private conversations. Companies will run 5 people × 20 agents × 15 apps; without shared state → chaos, duplicate edits, trapped knowledge. |
| **Differentiation** | NOT "another multiplayer workspace" (Dock, Mosaic, Sila, Gumloop crowd it). Orbyn = **multiplayer execution across the software a company already uses, with governed authority, live human participation, company knowledge, verified outcomes.** Amoeba collaborates around code; Orbyn around work. |
| **Five primitives taken from Amoeba** | Shared Missions · Workstreams (their "lanes") · Live Presence + Join · Handoffs · Resource Awareness (their file-collision, generalised to slides/CRM records/pages/branches/campaigns). |
| **Also taken** | Mission Control (their screen); "work belongs to people, agents execute it" (human sponsor per agent turn); per-action approval cards; **memory pinned to real objects that goes stale when the object changes** (→ Context Graph). |
| **What NOT to copy** | Provider choice as a selling point; real-time CRDT/cursors before PMF; competing on coding. |
| **Where it lives** | New horizontal layer **Collaboration Kernel** between UI and Core Runtime. Data contracts made multiplayer-capable *now* (Mission, Workstream, Participant, Agent, App, Resource, Artifact, Action, Approval, Evidence, Handoff, ContextReference) even while V1 has 1/1/1/1/1. |
| **Build order** | V1: Shared Session → Shared Plan → Agent Lanes → Shared Brain → Needs You → Mission Control. Then handoffs + collisions. Then live presence/cursors. |
| **Pricing boundary** | Free (1 user, 1 agent, 2 plugins) → Pro (parallel agents, 5+ plugins, expert teams, voice) → Team (multi-human, shared brain, handoffs, audit) → Business (+Company Brain, RBAC, connectors, private models, governance). |
| **Repo status** | Not started. D124 single-HWND manager is the seed of Mission Control; `session_events`/`session_commands` with `session_id` are the seed of per-session control. |

### 4.3 Dynamic Software Interfaces (YC idea)

| | |
|---|---|
| **Idea** | Applications shouldn't show everyone the same UI; interface adapts to user, task, expertise, participants, authority, risk. |
| **Where it lives** | Side panel ↔ expanded Mission Control is *the* expression. Beginner: step guidance. Expert: compact controls. Manager: approvals/status. Agent: structured capabilities. Support: failure context. Task-shaped panels: SEO (queries/pages/CTR/drafts/approve), code maintenance (files/diff/tests/PR/approve), presentation (slides/narrative/comments/design/apply). Combined with Multiplayer: solo view vs PEOPLE / WORK / AGENTS columns. |
| **Repo status** | Partial: D124 compact→expanded manager; vertical Ask rail 148×192 → 520×260. No task-shaped or role-shaped variants. Phase 6 in ROADMAP. |

### 4.4 Company Brain / Context Graph (YC RFS — the fourth; owner-confirmed 16 Sep 2026)

| | |
|---|---|
| **RFS ask** | Company knowledge that agents can actually use: organisational context, decisions, policies, procedures — structured, owned, current — instead of scattered docs, chats, heads. |
| **Note on source** | addons.md refers to "four YC RFS ideas" (l.2162) but names only three. Owner confirms Company Brain is the fourth. Recorded here so the count reconciles. |
| **Why adopted** | Agents cannot operate a company on fragmented context (Problem 2 + 7 in §8). Every other layer consumes it: Skills need approved knowledge, Agents need policy, Self-Maintaining needs the System Graph, Multiplayer needs shared memory, Needs You needs risk/policy context. |
| **Why NOT positioned as the company** | Category crowded (Mosaic, Glen, RAG/search vendors). addons.md §50 explicitly lists "Company Brain" among positionings to avoid as *identity*. It is a platform layer above Apps/Agents/Skills, "not another app". |
| **How it differs from RAG** | Knowledge is **pinned to real objects** (page, CRM product, deck, proposal template, billing config) with source / owner / provenance / confidence / scope / review status / last-verified. When the object changes → `⚠ CONTEXT MAY BE STALE` naming affected memories, workflows, pages, campaigns. Answers "what does this change affect?" not "what does this document say?" |
| **Internal name** | **Context Graph** (nodes: People • Agents • Apps • APIs • Code • Services • Customers • Products • Goals • Tasks • Decisions • Permissions • Policies • Memories • Actions • Verification • Failures • Recovery). **Company Brain** stays customer-facing. **Personal Brain** = same infra for individuals. |
| **Scopes** | GLOBAL → COMPANY → TEAM → PROJECT → PERSONAL. Memory types: working / episodic / semantic / procedural / preference; some decay. |
| **Learning loop** | Human resolves exception → candidate knowledge → owner review → approved Skill → future Missions need less intervention. Documents never become executable authority without review. |
| **Where it lives** | Phase 7 (full Context Graph, provenance, staleness, expert-resolution capture); seeds earlier: Phase 4 Personal Brain, Phase 5 System Graph for API impact. Enterprise premium module in pricing. Contributes the moat (Verified Interaction / Execution Graph). |
| **Repo status** | Designed. D070 reserves `knowledge.sqlite` (curated, local, never authority) separate from erasable `kb.sqlite`. No graph, provenance, or staleness code. Ingestion prototypes in the separate GrowthOS repo, not here. |
| **Constraint** | Local-first by D017; company-wide shared Brain needs the D017 amendment (Phase 3 gate). |

### 4.5 Non-YC sources adopted

| Source | Taken as | Rule attached |
|---|---|---|
| **HeyClicky "spatial context"** | Core primitive **Spatial Context / Point & Ask** — hotkey, draw/circle on screen, mark resolves via plugin to `Slide 4 → Shape 12 → Chart (0.97)`, not pixels. Bidirectional (human→AI, AI→human, human→AI→agent with SOURCE/TARGET roles, AI→human verification highlight). `SpatialContextReference {id, app, window, ts, marks[], screen_region, frame/crop refs, candidate_objects[], confidence, utterance, sensitivity_class}`. | **Context, not authority.** Circling DELETE never authorises deletion. Privacy modes: local / enterprise (prefer UIA semantics over pixels) / cloud (policy chooses full / crop / redacted / none). Not a plugin, not an agent, not student-only. P1 right after core loop. |
| **Amoeba** | See 4.2 | |
| **ABizCreator / GrowthOS** | Proof that the loop is industry-agnostic; Business/Growth *package* | Production publish hard-disabled; staging + environment fingerprint |

---

## 5. Complete feature catalogue — what, how, for what, status

Status key: **Built** (evidence/decision cited in repo) · **Partial** · **Designed** (in addons.md, not in repo) · **Blocked** (a standing decision forbids it until amended).

### 5.1 Experience layer

| Feature | What / how | For what | Status |
|---|---|---|---|
| Ask / Pause / Stop rail | Vertical 148×192 rail; executor-reported `Step N of M`; Ask expands left to 520×260 with prompt column; Stop ≤0.5s (D020), measured 0.094–0.187s | User never trapped by automation | **Built** (D020, `act_rail.py`, `docs/evidence/act-interruption-live.md`) |
| Compact panel ↔ expanded workspace | One resizable HWND; expands for planning/review/recovery; collapses on approved execution or success | Planning needs room, execution doesn't | **Built candidate** (D124; visual inspection + D032 review pending) |
| Mission Control | Expanded view: people, agents, workstreams, plan, activity, apps, artifacts, brain, approvals, evidence, collisions | "What are all humans/agents doing right now?" | Designed (single-mission seed exists) |
| Needs You card | what / why / resource / requested-by / risk / rollback / verification / evidence; Allow Once · Allow for Session/Mission (low-risk only) · Modify · Reject; never "allow everything forever" | Accountable, action-specific approval | Partial (approval binds digests/identity, one-use request; no risk/rollback/why fields) |
| Spatial Context | see 4.4 | Pointing beats describing | Designed |
| Bidirectional pointing (AI→human) | Overlay ring/arrow/callout; trust-coloured (cyan object-model, violet UIA, neutral in flight); "a pointer shown is a pointer acted on" | Shared spatial language; honesty about what the runtime touched | **Built** (D109/D112, `overlay/cue.py`, `pointer_path.py`) |
| Watch Build vs Quick Build | Paced, interruptible, view follows node; region highlight on changing area | Work visibly in front of the user | **Built** (3 Sep 2026, `act-deck-build-with-rail.md`) |
| Voice | Continuous talk while agent works ("keep layout, shorter headline") | Hands-free redirect | Designed |
| Dynamic / task-shaped panels | See 4.3 | Right controls for the task/role | Designed |
| Join the Agent | Enter a live agent workstream; redirect without restart; agent does not stop when human enters | Live collaboration vs post-hoc correction | Designed |
| Presence | 🟢 Arnav 🟢 Coding Agent 🟡 Design Agent; click → Open/Ask/Pause/Redirect/Take Over/View Work | Per-agent controls | Designed |

### 5.2 Interaction modes

| Mode | Meaning | Status |
|---|---|---|
| Ideate | Thinking partner; goal → discussion → research → alternatives → final goal → Mission | Preview-only contract; program stage 1 |
| Discuss | Trade-offs | Not modelled (deliberate) |
| Teach | Explain + point + verify; never acts | **Built**, gated (D048–D057 VS Code; PowerPoint) |
| Assist | Human acts, AI helps | Preview-only contract |
| Act | Signed API-v2 action plans; inert proposal → one explicit approval → per-node authorization | **Implemented, activation NOT READY** |
| Autopilot | Previously approved bounded workflow | Not modelled |
| Watch | Observe, intervene when useful | Not modelled |
| Collaborate | Multi-human, multi-agent | Designed |

### 5.3 Mission engine

| Feature | What | Status |
|---|---|---|
| Mission object | Persistent work object; "chats belong to missions" | Partial (session + brief) |
| Task Graph | Nodes with owner/executor/deps/permissions/expected result/verification/artifacts/resources/context/status; inert until authorised | **Built** for one plugin's capabilities (`task_graph.py`, D087/D090); no owner/executor/human fields |
| Brief / Ideation loop | Goal → clarification → persistent brief → capability-scoped graph → flattened plan → one approval | Partial (`brief.py`, `planning_session.py`, `task_planner.py`; clarification loop unbuilt) |
| Workstreams | Parallel lanes with own context, model, owner | Designed |
| Handoffs | Agent↔Agent, Agent↔Human, Human↔Human, local model→frontier; payload = goal, state, done work, decisions, apps touched, pending actions, evidence, approvals, next steps | Designed |
| Resume with edited plan | Re-validate, re-approve remainder; never replay completed side-effecting nodes; fresh observation | Designed, ordered (D110, stage 3) |
| Async continuation | Mission survives sessions/people | Designed |
| Artifacts | Attached to mission with provenance | Partial (staging/publish) |
| Artifact Intelligence + Critics | What exists / changed / missing / satisfies goal; Presentation Critic, Code Reviewer, Design Critic, Writing Critic | Partial (artifact verifier only) |

### 5.4 Trusted runtime

| Feature | What | Status |
|---|---|---|
| Signed capabilities | Only signed `.ghostplugin` via `PluginStore`; `authorize_intent()` sole minting function; distinct Teach/Act tokens | **Built** (D100–D104, D120) |
| Capability registry | `capabilities.json`: one ID → one intent → exact phrase → bounded scalars → pre/postconditions → `safe_to_repeat` | **Built** (D087/D089) |
| Whole-graph validation before any effect | Cycles, unknown ops, unmet preconditions, schema, repeated non-idempotent effects | **Built** |
| Per-node fresh authorization + bind | Reload catalog epoch, re-bind exact HWND, recheck Pause/Stop after mint | **Built** (D090, D118) |
| Independent verifier | Separately signed read-only verifier; live verifier for UIA (change vs baseline), artifact verifier for object-model; AST-scanned no-effect | **Built** (D114–D117) |
| Presentation receipts | Sealed overlay surface, UI-thread bridge, receipt deadlines 28 ms / 1100 ms measured | **Built** (D118, `act-receipt-budget.md`) |
| Coordinate-space contract | Physical pixels, bracketed paint, DPI awareness match | **Built** (D115/D116) |
| Process-identity binding | Adapter checks owning PID; no `Application.HWND`, no caption matching | **Built** (D075) |
| Verified Python bootstrap | `-I -S`, hash payload bytes, execute in-memory | **Built** (D117) |
| Transactional output | Staging + atomic publish; never overwrite | **Built** (`act_staging.py`) |
| Audit log | Keyed HMAC commitments; events not content; no goal/HWND/paths | **Built** (D122, opt-in) |
| Rollback | Restore prior state | Designed; "in-place editing of user files" deferred |
| Sandbox (code) | Repo copy → change → build/lint/test → verify → PR | Designed |
| Credential Vault | Scoped secrets; model never sees raw credential | Designed |
| Policy & Risk Engine / RBAC | Owner / Admin / Manager / Employee / Agent / Plugin roles | Designed (Phase 4/6) |
| Confidence & recovery | High → proceed; Medium → confirm; Low → reobserve/fallback/ask/stop; recovery knows prev/expected/actual state, retry, alternate capability, rollback, escalation owner | Partial (fail-closed refusals; no retry/alternate strategy) |
| Event Bus | `mission.created`, `plan.approved`, `action.completed`, `verification.failed`, `api.changed`, `resource.locked`… | Partial (`session_events`/`session_commands`) |
| Deterministic authority | Permissions, hashes, schemas, workflow state, audit never overridden by model wording | **Built** (D058, D068) |

### 5.5 Perception

| Feature | Status |
|---|---|
| Tier 1 UIA (worker thread, single-slot publish) | **Built** (D021/D022) |
| Tier 2 Windows.Media.Ocr (95 floor, 20-run ceiling, warm-up) | **Built** (D028–D030, D035) |
| Tier 3 VLM | Deferred; Teach-only when it lands |
| Wrong-action detection via focus | **Built** (D037) |
| Foreground watcher, perception health | **Built** |

### 5.6 Intelligence

| Feature | What | Status |
|---|---|---|
| Model Router | `reason/plan/converse/vision/critique/summarize/classify`; local ↔ workhorse ↔ frontier ↔ vision ↔ embeddings by privacy/cost/latency/complexity/policy | Partial: local `qwen3:4b-instruct` via Ollama, `resolve_model_decision()`, three-lane gate (D064–D067). Cloud **blocked by D017**. |
| Personal Brain | Preferences, projects, decisions, expertise, workflows; working/episodic/semantic/procedural/preference memory; session/personal/project/team/company scopes; decay | Partial: `kb.sqlite` (learned UIA ids), `sessions.sqlite` |
| Company Brain → Context Graph | Knowledge pinned to real objects with source/owner/provenance/review/validity/scope; staleness detection ("₹49K → ₹59K affects 3 workflows, 2 templates, 1 page, 4 memories"); System Graph for software | Designed; `knowledge.sqlite` reserved (D070) |
| Expert-resolution capture → approved Skill | Human fixes exception → candidate knowledge → owner review → Skill | Designed |
| Experts | SWE / Designer / Finance / Marketing / ML / Tutor; "expertise never silently creates authority" | Designed |
| Verified Interaction / Execution Graph (moat) | App states, verified workflows, failure/recovery patterns, corrections, permissions | Partial (per-plugin learned observations only) |
| Local-first privacy | Local by default; cloud only under policy with redaction/minimisation; modes local / private cloud / air-gapped / hybrid | **Built strict** (D017: no network at all) |
| Telemetry "events not content" | Blocked by D017 |
| Consent-based behaviour sync (24–48 h) | Blocked by D017 |

### 5.7 Capability layer

| Feature | What | Status |
|---|---|---|
| Connected App contract | Observe / Act / Verify / Events / Permissions; hybrid backends | Partial (plugin side only) |
| Application plugins | PowerPoint (active, manifest `28dbaf2d`), Synthetic (active), Excel + VS Code (installed, **disabled**, cannot be re-signed) | **Built** narrow |
| Shared UIA adapter | One canonical source, copied + signed per plugin | **Built** (D108) |
| Connectors (API/OAuth/MCP) | GitHub, Slack, Discord, Salesforce, Drive… | Designed (stage 6; needs D017 amendment) |
| Skills | Declarative; retrieved per mission; org skill library | Designed (stage 4) |
| Agents | Presentation, Research, Sales, Coding, Support, Design Critic, Maintenance agents | Designed (stage 5) |
| Packages | Student / Developer / Designer / Professional / Team / Enterprise; Business-Growth (GrowthOS) | Designed |
| Marketplace | Apps · Agents · Skills · (Experts); first-party signed only until signing/rotation/revocation/sandbox/review exist | Designed (stage 7); key rotation deferred |
| Repo Analyzer / Plugin SDK | Repo → capabilities → contract → validation → signed manifest | Designed (developer-side only) |
| Suggested missions from connected apps | "Investor meeting tomorrow + deck edited today → I can review it" | Designed |

### 5.8 Collaboration kernel

All Designed, none built: shared sessions, lanes, presence, Join, redirect, take control,
handoffs, comments on artifact/resource/task/spatial region, shared plan, notifications,
resource claims, collision detection (file / semantic / resource), agent↔agent under human
ownership, per-lane model choice.

---

## 6. Unified phased plan — origin to scale

Reconciles addons.md's six-phase roadmap, its "build now / architect now / build next /
build later" split, the repo's `ROADMAP.md` phases, and the 10-stage agent/skills/marketplace
program. Each phase lists its **gate** (what must be true before the next starts).

### Phase 0 — Guided runtime (Teach) — DONE
Core, overlay, Ask/Pause/Stop, UIA→OCR perception, deterministic planner, declarative
compiler, VS Code + PowerPoint Teach recipes, verification, session truth, local memory.
Evidence: D001–D077, `docs/evidence/`. Gate passed.

### Phase 1 — Trusted single-app Act (PowerPoint Limited Act v1, D140) — IN FLIGHT
Object-model + `New Slide` UIA, Quick/Watch pacing, reviewed-plan approval, `Step N of M`,
truthful pointer, Pause/Stop, live verification, transactional publish, native manager
approval → one-use request → D123 focus handoff.

**Open gates (CLAUDE.md + ROADMAP, kept identical here):**
1. Fresh counted campaign, both paths — after an independent READY verdict (11-Sep runs are diagnostic, D139)
2. UIA slice `add-slide-uia-v1` — independent D032 review, externally signed bytes, own counted campaign
3. Animation-catalog campaign — never counted
4. Independent lane runs — interactive / pixel / hung green alone (D025)
5. D032 review of derived budgets (receipt READY at `63c5ca5`; confirmation-to-invoke has no retained records; interruption matrix unmeasured)
6. D032 activation review — fresh verdict after 1–5

**Architect-now (per addons.md) without building:** name the session object `Mission`;
make data contracts carry `Participant`, `Workstream`, `Resource`, `Artifact`, `Handoff`,
`ContextReference` fields even at cardinality 1. Do this only as schema, in a reviewed slice,
so Phase 4 does not require a rebuild. Do **not** widen the execution boundary.

### Phase 2 — Ideate / Plan + Spatial Context + semantic deck (program stages 1–3)
Start only after activation READY.
- Stage 1: goal → clarification (`ClarificationRequired` vs `PlanProposal`) → persistent brief → capability-scoped graph → flattened plan → one approval → Act. Reuses `task_planner.py`, `planning_session.py`, `brief.py`, `inference/ollama.py`.
- **Spatial Context v1** (addons.md: P1 immediately after core loop): hotkey + mark → `SpatialContextReference` → plugin resolves to object-model shape → attaches to brief/proposal as *context only*. Fits D113 (brief carries no selector/authority). Rendering reuses overlay; resolution reuses PowerPoint plugin. Two-mark SOURCE/TARGET for "move this here".
- Stage 2: semantic PowerPoint capabilities (`create_deck`, `apply_theme`, `create_*_slide`, `add_speaker_notes`, `apply_restrained_motion`, `inspect_deck`, `publish_deck`), each expanding deterministically into reviewed low-level ops; local model composes a 10-slide deck from the brief. **Conflict to resolve first:** a "Deck Agent" named for an application vs the no-application-code-in-core rule (ROADMAP conflict 4).
- Stage 3: resume-with-edit, recovery, edited-plan re-approval (D110). Undo/rollback design decision.
- Artifact Critic (Presentation Critic) as a read-only reviewer over `inspect_deck`.
- Needs You card gains why / risk / rollback / verification fields.
**Gate:** repeat-user validation — does the same person bring a second real Mission? Installer/onboarding (FOLLOWUPS) needed for this.

### Phase 3 — Capability platform (Connected Apps, Skills, Agents; program stages 4–7)
- Stage 4 Skills: declarative expertise files, signed, retrieved per Mission; "knowledge → agent interpretation → proposed skill → human review → approved skill".
- Stage 5 Structured agent executor: Agent = Skills + Apps + goal; orchestrator is never an authority shortcut (D087/D090/D100–D104 restated).
- Connected Apps framework: formal Observe/Act/Verify/Events/Permissions contract; per-app permission scoping ("#product ✓, DMs ○, send ○"); "things I can now help with" suggestions.
- Stage 6 Connectors (API/OAuth/MCP) and opt-in cloud reasoning — **requires reviewed D017 amendment** with a privacy design (redaction, minimisation, explicit consent, provider/model/version tracking, local/private-cloud/air-gapped/hybrid modes). Credential Vault lands here.
- Stage 7 First-party marketplace (Apps · Agents · Skills) — **requires key rotation + revocation** (Excel/VS Code quarantine is the proof of cost, D128).
- Model Router beyond local: routing by privacy/cost/latency/complexity/policy.
- Packages: Developer, Designer, Student (Study Agent + tutor skills + PDF/browser app), Professional.
**Gate:** ≥2 Apps beyond PowerPoint through the same contract; one agent completing a Mission across Skills; marketplace install/disable/uninstall with revocation exercised.

### Phase 4 — Personal multi-agent work (addons Phase 3)
Mission Control (one user, several agents), multiple Workstreams, parallel agents,
agent→agent handoff, Personal Brain with memory types/scopes/decay, Verified Interaction
Graph accumulation. Resource claims (single user) as precursor to collisions.
**Gate:** Missions with ≥2 workstreams completed with verified outcomes; handoff payload proven lossless.

### Phase 5 — Self-Maintaining APIs wedge (first B2B product category)
Depends on Phase 3 (GitHub connector, sandbox, cloud policy) and Phase 4 (agent lanes).
- Providers: OpenAI + Stripe + generic OpenAPI. Repos: TS/Python.
- Pipeline: Change Agent → Impact Agent (System Graph) → Planner → Coding Agent (sandbox: build/lint/test) → Verify Agent → Needs You (diff, tests, risk) → PR → post-merge verification → Company Brain learns migration pattern.
- Design partners 5–10; north-star metric = % detected changes resolved via verified workflow.
- Marketplace category Maintenance Agents.
**Gate:** one real repo, real provider change, independently discovered impact, ≥3 call sites repaired, suite green, passing PR — repeated weekly by a design partner.

### Phase 6 — Multiplayer (addons Phase 4)
Multiple humans in a Workspace, Join the Agent, shared Missions, presence, comments
(attachable to spatial regions), resource awareness, per-lane models, team Brain,
Team pricing tier. Ask/Pause/Stop per agent.
**Gate:** two humans + ≥2 agents complete one Mission with handoff and one detected collision.

### Phase 7 — Organizational intelligence (addons Phase 5)
Company Brain as Context Graph with provenance, ownership, review status, staleness
detection tied to real objects; expert-resolution capture → reviewed Skills; workflow
learning; enterprise onboarding & pre-diagnosed support packages.
**Gate:** a stale-memory alert triggered by a real object change; one human correction promoted to an approved Skill through review.

### Phase 8 — Enterprise execution (addons Phase 6)
Coordination Engine (ownership, scheduling, dependency resolution, semantic + resource
collision), RBAC/policy engine, full audit, cross-app Missions (**requires reviewed
D087/D090 amendment**), self-maintaining workflows, private/air-gapped deployment,
Business tier, workflow analytics. Pilot shape: 50 employees / 2 apps / 3 workflows;
measure completion, support requests, intervention, handling time, error rate,
verification success, time-to-productivity.

### Phase 9 — Long-term
Self-maintaining company (regulation / SEO / supplier / pricing changes → Missions),
dynamic interfaces everywhere, voice, third-party marketplace with SDK + Repo Analyzer,
restricted general computer use (**requires reviewed D006 amendment**), VLM tier 3,
cross-company runtime. Thesis, not schedule.

---

## 7. What is already built (repo evidence) vs what addons.md claims

addons.md §38/§58/§65 lists the "demonstrated" set. Repo-accurate version:

| addons.md claim | Repo truth |
|---|---|
| Windows-native runtime, live observation, planning, local inference | **True** |
| Signed application capabilities, bounded approved execution | **True** (D100–D104, D117, D120–D123) |
| Pause / Stop / intervention | **True**, measured |
| Independent verification | **True** (signed read-only verifiers, live + artifact) |
| "Application proof in PowerPoint, VS Code, Excel" | PowerPoint: Act implemented, **not accepted**. VS Code: Teach gates closed (D048–D057), plugin now **disabled**. Excel: historical feasibility only (16.0.20326), bundle **disabled**, cannot be re-signed. |
| "Nine tests passing, Docker, PWA, Company Brain ingestion, EmbeddingGemma, Pricing-Agent bridge, sandbox connectors" | Belongs to the separate BusinessOS/GrowthOS codebase, **not this repo**. Do not cite as this product's evidence. |
| Audit | Opt-in keyed manager audit exists (D122); enterprise audit log not built |
| Verified Interaction Graph | Per-plugin learned UIA ids only |

**Hard rules the addons plan must honour (they are not negotiable without a reviewed decision):**
D006 no input synthesis · D017 local-only, no telemetry/network/sync · D025 one desktop lane at a time · D032 nothing self-authored is truth until independently read · D034 every number names its record · D058 model output is advice · D075 one matching window or none · D087/D090 one plugin per graph, no app names in core · D100–D104 single authority path · D109/D112 shown pointer is acted-on pointer · D113 brief is never authority · D125 LF bytes canonical · D128 no raw HWND/PID in tracked docs · D139 never edit captured output · D140 release boundary.

---

## 8. Business layer (from addons.md, consolidated)

**Problem stack:** intent→execution gap · fragmented context · tool fragmentation ·
trust · coordination · software changes continuously · organizational knowledge
disappears. Ten enterprise pains (stuck in workflows, slow onboarding, SME interruptions,
expensive repetitive mistakes, trapped knowledge, too many apps, SOPs disconnected from
work, context-less tickets, invisible process breakage, distrust of agent authority).

**ICPs, ranked:** (1) Operations-heavy enterprises — GCC / BPO / shared services / finance & customer ops (need the *whole* stack). (2) Mid-market ops/IT/enablement. (3) Consulting/professional services. (4) Engineering teams. (5) Enterprise sales. (6) Individual professionals (distribution, low ACV). For the Self-Maintaining wedge: API-heavy SaaS / dev-tool / infra / integration teams.

**Pricing (hybrid, not final):** Individual freemium → subscription (India experiments ₹0 / ₹299–499 / ₹799–999 / ₹1,499–2,499, UPI). Pro adds execution allowance, parallel agents, experts, voice. Team = multi-human + shared Brain + handoffs + audit. Enterprise = platform fee + active users/workflow volume + modules (Company Brain, Multiplayer, private deploy, analytics, governance, custom Apps, policy, audit). Marketplace rev-share later. Four dimensions sold: Breadth (capabilities), Intelligence (experts/models), Continuity (memory), Labour (execution). Users never think in tokens.

**GTM:** founder-led beta → real Mission usage → design partners → paid bounded pilots (50 employees / 2 apps / 3 workflows) → annual. Optimise for *second voluntary Mission*, not signups. Validation metrics: supported-Mission completion, repeat usage, intervention rate, verification success, time saved, WTP, second-Mission creation.

**Positioning to avoid:** "AI Operating System", "computer-use agent", "AI employee", "plugin marketplace", "multiplayer workspace". Use: *trusted execution layer where people and AI agents work together across the software a company already uses.*

**Moat:** not the model — the Verified Interaction / Execution Graph (states, verified workflows, failure/recovery, corrections, permissions, approvals, org context). Explicitly *not yet* a moat.

---

## 8b. B2C / D2C surface of the same plan

addons.md treats B2C as **packages on the same runtime**, not a second product. Same
Core, same trust stack; Company Brain becomes Personal Brain, Mission Control becomes a
one-user command center. Role: distribution + word-of-mouth + freemium funnel; lower
willingness to pay than enterprise (ranked 4th of 4 in the spatial-context use-case list,
"individual professionals" last of six ICPs).

### Packages (each = Agents + Skills + Apps + Brain + Spatial Context on the Core)

| Package | Agents / Experts | Skills | Apps | Killer interaction | Phase |
|---|---|---|---|---|---|
| **Student / Learning** | Study Agent, Tutor Agent, Research Agent, Coding Agent | Explain-Like-a-Tutor (diagnose misconception, don't dump answer), Socratic Tutor, Exam Prep (question gen, spaced repetition), Research Paper Reader (equations/charts/citations/method), Coding Tutor (explain, don't fix) | PDF / Browser, VS Code | Circle muscle → "what is this?" → "what nerve?" → "quiz me later" → mastery updated. Circle circuit capacitor / derivation step / code block / paper table: "explain assuming I know Section 2". Learn-while-doing: tutor sees what coding agent did. | 3 (packages) + 4 |
| **Developer** | SWE Expert, Architecture, Coding, Testing, Research, Documentation agents | code review, debugging, docs | VS Code, Terminal, Git/GitHub, Docker, Browser | Teach/Assist/Act per task; "why is this causing the race condition?" via circle | 3–4 |
| **Designer** | Design Expert, Visual/Design Critic, Research Agent, Asset Agent, Implementation Agent | visual hierarchy, chart simplification, brand consistency | Figma, Photoshop, Blender, KiCad, CAD, video editors | Circle A + circle B → "move this here" / "make these match" / "use this style on these" (SOURCE/TARGET marks); Artifact Critic on output | 3–4 |
| **Creator** | (named, not detailed) | — | image/video tools, browser | — | later |
| **Professional** (Office user) | Presentation Agent, Presentation Critic | investor storytelling, presentation design, financial analysis | PowerPoint, Excel, Drive, Browser | Circle competitor table → "too dense, simplify, keep all five" → approve → verifier: ✓5 competitors ✓3 dimensions ✓theme. **This is the current PowerPoint MVP.** | 1–2 |
| **Individual "personal AI team"** | any of above in parallel | — | — | Mission "Launch my startup" → Product / Research / Deck / Landing page / Funding workstreams, one person + several agents; Mission Control solo view | 4 |

### B2C-specific features in the plan

| Feature | B2C use |
|---|---|
| Spatial Context / Point & Ask | Primary B2C hook; "best viral B2C use case"; excellent demo |
| Personal Brain | preferences, projects, decisions, expertise level, routines, learning progress, mastery; memory types + decay |
| Long-context continuity | last month's Mission needs no re-explaining (paid value prop) |
| Expert agents | SWE / Designer / Marketing / ML / Finance experts that teach, review, critique, implement |
| Voice | talk while agent works |
| Teach mode | learn Photoshop/VS Code/etc. inside the app — original GhostCursor |
| Ideate | thinking partner before execution ("I want to launch this product") |
| Artifact Critic | presentation / code / design / writing review before "done" |
| Behaviour sync (24–48 h, consent) | personalisation, plugin/workflow suggestions — **blocked by D017** |
| Local-first | privacy answer for screen capture on personal machines |

### B2C monetisation (planning figures, not final)

- Free ₹0: 1 user, 1 active agent, 2 plugin slots, basic Personal Brain
- Student/Starter ₹299–499 · Plus ₹799–999 · Pro ₹1,499–2,499 (INR/UPI)
- Pro adds: parallel agents, 5+ plugins, advanced memory, expert teams, voice, long-running Missions, execution allowance
- Extra plugin slots as add-on (older idea; packages preferred)
- Four sold dimensions: Breadth (plugins) · Intelligence (experts) · Continuity (memory) · Labour (execution)
- Commercial trajectory: Individual Missions → expert packages + plugins → shared team Missions → enterprise

### Repo reality for B2C

Only the Professional/PowerPoint slice exists (Teach + Limited Act). Student, Developer
(VS Code Teach exists but plugin disabled), Designer packages, experts, voice, Personal
Brain beyond `kb.sqlite`: not built. B2C packages start Phase 3.

## 9. Open decisions the unified plan surfaces (owner calls, not agent calls)

| # | Decision | Options | Recommendation |
|---|---|---|---|
| 1 | **Which wedge is the commercial first product?** addons.md contains both: PowerPoint validation wedge (canonical master, §36–37) and Self-Maintaining APIs as Techstars wedge (§43, §68–69). | (a) PowerPoint proves loop → Connected Apps → then Self-Maintaining; (b) pivot now to Self-Maintaining APIs | (a). The repo has no GitHub connector, no code sandbox, no network, and Act is not yet activated. Self-Maintaining APIs needs Phases 3–4 first. Keep it as *the* Phase 5 category and say so in the pitch ("proven runtime in PowerPoint; first product category self-maintaining software"). |
| 2 | **D017 amendment** for connectors, cloud reasoning, telemetry, sync | amend with reviewed privacy design / keep local-only and drop Phase 2/4 telemetry items | Amend at Phase 3 entry, scoped: connectors + opt-in cloud escalation with redaction; telemetry stays "events not content" and off by default. |
| 3 | **Application-named agents** (Deck Agent, Presentation Agent) vs no-application-code-in-core | agent = signed data (skills + capability refs) inside the plugin bundle / agent in core | Agents are signed plugin-scoped data, never core Python. Names live in bundle metadata. |
| 4 | **Rename to Orbyn in the repo** | now / at Phase 3 / never in code | Code stays `ghostcursor` (signed payload paths, digests, evidence all reference it — a rename invalidates pins, D125). Product/docs name Orbyn at Phase 2. |
| 5 | **Spatial Context priority** | P1 after activation / later | P1 after activation, as planning context only (no authority), PowerPoint-resolved first. |
| 6 | **Excel / VS Code** re-enablement | re-key to `-2026-3` / new signing design / leave disabled | Leave disabled until the marketplace signing decision (rotation + revocation) — D128. |
| 7 | **Cross-app Missions** | amend D087/D090 at Phase 8 | Amend only with a reviewed design for cross-plugin authority; until then "general agent" = route intent to one plugin. |

---

## 9b. Decisions RESOLVED (owner direction 16 Sep 2026: earlier decisions are mouldable; amend what is needed so everything works, break nothing)

Rule kept from `CLAUDE.md`: an amendment names the prior decision, states what changed
and why, keeps the history, and updates rules in the same reviewed slice. Nothing below
is silently rewritten. Numbers D141+ are **proposed**; assign on recording.

| # | Decision | Resolution |
|---|---|---|
| 1 | Wedge | **PowerPoint first.** Self-Maintaining APIs = Phase 5 product category, pitched as "runtime proven in PowerPoint; first product category self-maintaining software". No amendment needed. |
| 2 | D017 | **Amend (D141 below).** Local-only stays the default and the hermetic baseline; a consented network tier is added for connectors, cloud escalation, and events-only telemetry. |
| 3 | App-named agents | **Amend D087/D089 by clarification (D142).** Agents and Skills are signed, plugin-scoped *data*; core runs a generic agent executor. |
| 4 | Orbyn rename | **Product/docs name = Orbyn from Phase 2. Code package stays `ghostcursor`.** Renaming payload paths invalidates every digest pin (D125) and all retained evidence. No amendment; a note in `CLAUDE.md` orientation. |
| 5 | Spatial Context | **P1 after activation; amend D113 by clarification (D143).** A `SpatialContextReference` is brief content — hashed bytes, never a selector or authority. |
| 6 | Excel / VS Code | **Stay disabled** until D144 (signing identity design: rotation + revocation). Then re-key deliberately. |
| 7 | Cross-app Missions | **Deferred to Phase 8.** Amend D087/D090 only with a reviewed cross-plugin authority design. Until then "general agent" = route intent to exactly one plugin. |
| 8 | D006 input synthesis | **Unchanged.** Not needed for anything in Phases 1–8. Restricted raw input is Phase 9 with its own review. |
| 9 | D139 / D032 / D025 / D034 evidence discipline | **Unchanged.** These are how "does not break anything" is proven; loosening them is what produced the falsified transcripts. |

### Draft amendment texts (ready to paste into `DECISIONS.md` after owner review)

**D141 — Consented network tier (amends D017).**
*Prior:* D017 — local-only; no telemetry, no network, no cloud sync.
*What changes:* D017's default is unchanged: a fresh install makes no network call, the
hermetic lane stays offline, and Teach/Act authority never depends on the network. Three
opt-in capabilities are added, each behind its own explicit, revocable consent stored
locally: (a) **App connectors** (API/OAuth/MCP) scoped per App to declared
Observe/Act/Verify/Events/Permissions, credentials held in a local vault and never
exposed to a model; (b) **cloud model escalation** only when a policy permits it, with
secrets/paths/credentials redacted, screenshots excluded unless separately permitted,
context minimised, and provider/model/version recorded; (c) **telemetry**, off by
default, events not content — never goals, screen text, HWNDs, paths, credentials,
source, documents. Enterprise modes: local-only, private cloud, air-gapped, hybrid.
*Why:* Connected Apps, Self-Maintaining APIs, Company Brain sharing, and Multiplayer are
impossible without a network path; D017 was adopted for a single-machine Teach product.
*What stays:* everything D017 forbids stays forbidden by default; `resolve_model_decision()`
and the three-lane model gate still govern any model change; kb/sessions never sync.
*Breaks nothing because:* no existing code path changes behaviour; all current tests run
offline; the tier is additive and gated at Phase 3 entry.

**D142 — Agents and Skills are signed plugin-scoped data (clarifies D087/D089).**
*Prior:* core must never carry application names or capability-specific branches; core
never imports an adapter or learns an object model.
*What changes:* nothing in the prohibition. Clarification: an Agent (goal + Skills +
capability references + permissions) and a Skill (declarative expertise/procedure with
preconditions, tools, verification, escalation) are signed data files inside a plugin
bundle or a signed skill bundle. A "Deck Agent" is a filename and metadata, not Python.
Core ships one generic agent executor that composes only registered capabilities and
still passes every node through `authorize_intent()`, fresh bind, and independent
verification.
*Why:* the activation review named application-named agents as the likeliest place the
rule breaks; naming the boundary before stage 2 prevents it.

**D143 — Spatial context is brief content (clarifies D113).**
*Prior:* a brief is planning context, never authority; carries no selector, capability,
parameter or plan.
*What changes:* a `SpatialContextReference` (marks, screen region, frame/crop refs,
plugin-resolved candidate objects with confidence, utterance, sensitivity class) is
appended to the brief as bytes and hashed with it. It may inform which registered
capability and which scalar parameters the planner proposes; it may never be a selector,
a target identity, or an action. Resolution to an application object runs in the signed
plugin, not core. Circling a control never authorises acting on it. Pixel data never
leaves the machine unless D141(b) permits it.
*Why:* pointing is faster than describing; must not become a second authority path.

**D144 — Signing identity design (unblocks D128 quarantine).**
*Prior:* D128 — Excel/VS Code signed by unavailable keys; re-keying onto `-2026-3`
refused because it collapses signing identities with no rotation/revocation.
*What changes:* before any marketplace stage: a signed key manifest with key ids,
validity windows, successor keys, and a revocation list that `PluginStore` checks on
every catalog load and that the runtime authority monitor rechecks within D020's ceiling;
a re-sign procedure that records the old key id and digest in the bundle's provenance.
Only then re-key Excel/VS Code deliberately, with fresh D032 review and their own counted
campaigns.
*Why:* first-party marketplace (stage 7) distributes bundles to machines that must be able
to reject a withdrawn one.

**Note in `CLAUDE.md` (no decision):** product name Orbyn; package/paths remain
`ghostcursor`; Orbyn appears in docs and UI strings only.

## 10. Immediate next actions (this week, in repo order)

1. Close the confirmation-to-invoke budget: review `ghostcursor.devtools.confirmation_budget`, retain records, derive deadline, add production refusal (Phase E gate).
2. Measure the interruption-latency matrix.
3. Run each desktop lane alone; retain outputs (D025).
4. Count the animation-catalog campaign.
5. Request independent D032 review of budgets → READY → fresh counted campaign (harness + manager path) → activation review.
6. In parallel, docs-only: record in `ROADMAP.md` the Phase 2–9 sequence above (owner-approved), the seven open decisions in §9, and the multiplayer-capable schema intent as an "architect now, build later" note — so the phases exist somewhere other than conversation.

Nothing in 1–6 widens the execution boundary; all of it is inside D140.
