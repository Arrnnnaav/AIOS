# ORBYN — MASTER BUILD PLAN

**Canonical implementation document for coding agents**  
**Merged from:** `ORBYN_UNIFIED_PLAN.md` + `ORBYN_JEV_SYSTEM_ONE_ADDENDUM.md`  
**Product name:** **Orbyn**  
**Historical/internal package name:** `ghostcursor` unless and until a reviewed rename slice explicitly changes it  
**Date:** 18 September 2026  
**Purpose:** Give a coding agent one source of truth for what Orbyn is, what is already built, what must remain invariant, what must be added, and the exact phase order for implementation.

---

# HOW TO USE THIS FILE

This is not a brainstorming document. It is an **implementation program**.

A coding agent receiving this file should treat it as the product/architecture contract and proceed **phase by phase**. Do not jump ahead because a later feature looks easier or more exciting.

At the beginning of every implementation session:

1. Read this file.
2. Read the repository's current `CLAUDE.md`, `ROADMAP.md`, `FLOW.md`, `DECISIONS.md`, `FOLLOWUPS.md`, and relevant `docs/evidence/` files.
3. Reconcile this plan against actual repository state.
4. Repository truth wins for **what already exists**.
5. This plan wins for **owner intent and future architecture**, unless a newer owner-approved decision explicitly supersedes it.
6. Never rewrite history. If a standing decision must change, add an amendment naming the prior decision, what changed, why, what remains, and how the change is proven not to break prior safety guarantees.
7. Do not claim a phase is READY if it requires independent review and that review has not actually happened.
8. Do not widen the execution boundary while doing unrelated work.

## Core coding-agent operating rule

> **Implement the smallest reviewed slice that advances the current phase, retain evidence, then stop at the phase gate.**

Do not treat this plan as permission to implement all future features at once.

---

# PART I — LOCKED COMPANY / PRODUCT THESIS

## 1. What Orbyn is

> **Orbyn is the trusted execution layer where people and AI agents work together across the software a company already uses.**

Orbyn converts a desired outcome into a persistent **Mission**, coordinates people and agents around that Mission, uses connected software through governed capabilities, asks for approval when required, executes bounded actions, and independently verifies whether the intended result actually occurred.

### Internal equation

> **Apps provide capabilities. Skills provide expertise. The Brain provides context. Agents pursue goals. Multiplayer coordinates people and agents. The Runtime controls authority and verifies outcomes.**

### Category line

> **From digital adoption to verified digital execution.**

### Four pillars

| Pillar | Contents |
|---|---|
| **Intelligence** | Personal Brain, Company Brain / Context Graph, Experts, Model Router, System-One Decision Layer |
| **Capabilities** | Connected Apps, signed plugins, connectors, Skills, Packages, Marketplace |
| **Execution** | Runtime, permissions, Needs You, Act, verification, sandbox, audit, rollback |
| **Collaboration** | Missions, Workstreams, humans, agents, presence, Join, handoffs, Coordination Engine, Mission Control |

---

# 2. The problem Orbyn solves

Modern work is fragmented across applications, people, documents, chat systems, and AI tools.

A person may know the outcome they want but still has to:

- discover how each tool works;
- carry context between applications;
- translate AI advice into UI actions;
- remember company-specific procedures;
- decide what can safely be automated;
- handle exceptions;
- ask experts for help;
- inspect whether the requested outcome actually happened;
- coordinate several people and AI agents touching the same work.

The recurring enterprise pain stack is:

1. Employees get stuck in multi-step workflows.
2. New employees take too long to become productive.
3. Senior employees repeatedly answer the same questions.
4. Repetitive workflows produce expensive mistakes.
5. Institutional knowledge remains trapped in people's heads.
6. Work spans too many disconnected applications.
7. SOPs exist but are disconnected from the live moment of work.
8. Support tickets lack enough diagnostic context.
9. Managers know processes are inefficient but cannot see where they break.
10. Organizations want AI agents but do not trust them with real authority.
11. As companies deploy more agents, duplicate work, conflicting edits, unclear ownership, and context fragmentation become new problems.
12. External software, APIs, interfaces, policies, and workflows continuously change.

Orbyn's answer is neither static guidance nor blind autonomy.

The intended continuum is:

```text
IDEATE → DISCUSS → TEACH → ASSIST → ACT → AUTOPILOT → WATCH → COLLABORATE
```

The principle is:

> **Appropriate authority, not maximum autonomy.**

---

# 3. Architecture lineage — how the product reached the current model

| Stage | Trigger | Architectural result |
|---|---|---|
| GhostCursor | AI explains, human still executes | Desktop overlay observes software, points to controls, verifies. Teach-only boundary. |
| Mode continuum | Users want different authority | Ideate/Teach/Assist/Act/Autopilot/Watch. |
| Core + Plugins | Pixel guessing is unreliable | Application-specific behavior moved out of core into signed bounded integrations. |
| GitHub repo plugin idea | Nontechnical users should not manage repos | Developer-side repo tooling remains possible; user-facing abstraction becomes **Apps**. |
| Trust stack | Enterprises cannot trust unconstrained agents | Signed capabilities, authority levels, Needs You, independent verifier, audit, sandbox, rollback. |
| Company Brain | Agents need organizational context | Context with source, owner, scope, review, provenance, freshness. |
| GrowthOS / ABizCreator | Need proof runtime can support real domain workflows | Business/Growth package concept, not the Orbyn identity. |
| Experts / Packages / Personal Brain | B2C and professional distribution | Experts provide intelligence; Apps provide capability; packages compose them. |
| Spatial Context | Natural language is poor for spatial intent | Point & Ask becomes a core context primitive, never authority. |
| Connected Apps contract | Marketplace must be understandable | Every App exposes Observe / Act / Verify / Events / Permissions. |
| Self-Maintaining APIs | Need a concrete future B2B wedge | Self-maintaining integrations/software becomes Phase 5 product category. |
| Multiplayer AI / Amoeba | Work must be shared, not private chats | Missions, Workstreams, Join, handoffs, resource awareness, Mission Control. |
| Rename to Orbyn | Cursor metaphor became too narrow | Product name Orbyn; historical package paths remain `ghostcursor` for now. |
| Jev / System One | Structured candidates still need semantic target selection | System-One decision layer + Semantic Target Resolver. |

---

# PART II — NON-NEGOTIABLE SYSTEM PRINCIPLES

# 4. Canonical object model

The user-facing vocabulary is frozen. Do not casually add new primitives.

| Primitive | Meaning | Current state |
|---|---|---|
| **Workspace** | Person/team/company boundary; humans, agents, apps, Brain, permissions, Missions, policies | Not yet modeled |
| **Mission** | Persistent outcome pursued by humans and agents; owns goal, participants, plan, workstreams, resources, artifacts, decisions, approvals, evidence, memory, state | Partial via sessions/brief/planning |
| **Workstream** | Parallel subdivision of a Mission | Designed |
| **Human** | Accountable participant; work belongs to humans, agents execute it | Implicit single operator today |
| **Agent** | Goal-driven AI worker using Skills + Apps; never direct uncontrolled software authority | Designed |
| **Skill** | Declarative expertise/procedure with knowledge, workflow guidance, permissions, tools, verification | Designed |
| **App** | Connected software Orbyn can observe/operate through connector/plugin/UIA/vision | Partial through signed plugin layer |
| **Resource** | Specific object touched: slide, range, CRM record, branch, page, etc. | Partial via exact process/window/output bindings |
| **Artifact** | Produced/modified output with provenance | Partial transactional staging/publish |
| **Brain** | Personal/company contextual intelligence; internally Context Graph | Early local stores only |
| **Needs You** | Human decision/approval queue | Partial through explicit approval / one-use execution request |
| **Mission Control** | Operational UI for Mission state, people, agents, workstreams, apps, approvals, evidence, collisions | Seed exists as compact/expanded manager |
| **Runtime** | Planning, execution, trust, verification | Core is the most mature part |
| **Coordination Engine** | Ownership, scheduling, dependencies, resource claims, collisions, handoffs | Designed |

Internal non-user-facing contracts may include:

- `SpatialContextReference`
- `CandidateObject`
- `SemanticTargetResolver`
- `SystemOneProvider`
- App Capability Contract
- Universal Plugin Contract
- Event Bus
- Model Router
- Credential Vault
- Sandbox
- Policy & Risk Engine
- Audit Log
- Health System
- Test Lab
- Artifact System
- Capability Registry

---

# 5. Canonical target architecture

```text
ORBYN UI
Side Panel • Expanded Mission Control • Voice • Dynamic UI • Spatial Context
        │
        ▼
COLLABORATION KERNEL
Missions • Humans • Agents • Workstreams • Presence • Ownership
Join • Redirect • Take Control • Handoffs • Comments • Resource claims
        │
        ▼
CORE RUNTIME
Planner • Task Graph • Workflow • Event Bus • Policy/Risk • Permissions
Needs You • Verification • Sandbox • Audit • Rollback • Credential Vault
Coordination Engine • Model Router
        │
        ├───────────────────────────────┐
        ▼                               ▼
INTELLIGENCE / BRAINS                  CAPABILITY LAYER
Personal Brain                         Connected Apps
Project Brain                          ├─ API / OAuth / MCP connector
Company Brain / Context Graph          ├─ signed plugin
Experts                                ├─ UIA adapter
System-One Decision Layer              └─ vision fallback
Semantic Target Resolver               Skills • Packages • Marketplace
        │                               │
        └──────────────┬────────────────┘
                       ▼
REAL SOFTWARE
PowerPoint • Excel • VS Code • GitHub • Slack • Salesforce • SAP • Browser • WordPress • …
```

---

# 6. Execution preference order

Locked order:

```text
Structured API / connector
        ↓
signed application plugin / object model
        ↓
bounded UIA / accessibility
        ↓
Teach / Assist fallback
        ↓
refusal
```

Vision-driven raw mouse manipulation is a fallback research direction, **never the base architecture**.

Current D006 no-input-synthesis boundary stays in force through the planned near/mid-term phases.

---

# 7. Authority chain

Locked:

```text
Global Safety
    ↓
Organization Policy
    ↓
User Policy
    ↓
App Permission
    ↓
Mission Permission
    ↓
Action Authorization
```

A generated plan has **zero execution authority**.

Model output is proposal/advice.

Deterministic code decides whether an action may occur.

### Authority levels

| Level | Meaning |
|---|---|
| 0 | Observe |
| 1 | Teach / Highlight |
| 2 | Safe Navigation |
| 3 | Reversible Modification |
| 4 | External Side Effect |
| 5 | Sensitive / High Risk |

---

# 8. Verification rule

> **Execution is not completion. Verification is completion.**

Rules:

1. The actor must not grade itself when an independent check is possible.
2. Deterministic verification comes first.
3. Semantic/model verification is used only where exact checks cannot answer the criterion.
4. A qualitative verifier remains read-only.
5. High-risk uncertain verification triggers human review.

Examples of deterministic verification:

- file exists;
- slide exists;
- exact field value changed;
- branch exists;
- record status changed;
- expected application state is present.

---

# 9. System-One + System-Two intelligence architecture

This is now a locked Orbyn principle.

## 9.1 System Two

Used for open-ended reasoning:

- ideation;
- clarification;
- planning;
- research;
- decomposition;
- complex recovery;
- critique;
- long context;
- multimodal interpretation.

Providers may include local models, workhorse LLMs, frontier LLMs, vision models, and expert models.

## 9.2 System One

Initial provider: **TypeSafe Jev**.

Used for fast bounded decisions over **closed runtime-provided option sets**:

- target selection;
- candidate ranking;
- narrow intent classification;
- capability routing among registered capabilities;
- event routing;
- recovery-branch ranking;
- semantic graph relation scoring;
- staleness triage;
- semantic collision scoring;
- structured artifact judgments;
- read-only semantic verification evidence.

## 9.3 Foundational intelligence rule

> **Perception discovers what exists. System Two understands what the user wants. System One chooses among real bounded options. Deterministic policy decides what is allowed. Apps perform the action. Independent verification proves what happened.**

## 9.4 Jev is never an authority path

Jev must never decide:

- RBAC;
- permission;
- action authorization;
- credential exposure;
- signature validity;
- process identity;
- approval bypass;
- purchase/spending permission;
- destructive authority;
- arbitrary selector creation;
- arbitrary capability ids;
- whether Needs You may be skipped;
- deterministic completion when code can check directly.

---

# 10. Anti-hallucination rule for executable targets

Locked:

> **Models may choose among registered objects; models may never invent executable object identities.**

Reject:

- invented XPath;
- invented CSS selectors;
- invented automation IDs;
- invented HWND/PID;
- arbitrary coordinates;
- invented plugin/capability IDs;
- stale candidate IDs;
- arbitrary object handles.

Models can reason about semantics, but local deterministic code owns the mapping from a candidate ID to the live object.

---

# PART III — PERCEPTION, TARGETING, AND SPATIAL CONTEXT

# 11. Perception hierarchy

Preferred source quality:

```text
application plugin / object model
        >
structured API / connector / DOM
        >
UIA / accessibility
        >
OCR candidate extraction
        >
VLM / vision candidate extraction
```

Current repo has:

- Tier 1 UIA: built.
- Tier 2 Windows OCR: built.
- VLM Tier 3: deferred / future Teach-first path.
- foreground watcher / perception health: built.
- wrong-action detection via focus: built.

---

# 12. Candidate registry

Add a runtime-minted `CandidateObject` representation.

Conceptual contract:

```typescript
type CandidateObject = {
  candidateId: string;
  source: "plugin" | "connector" | "dom" | "uia" | "ocr" | "vision";
  appId: string;
  resourceId?: string;
  objectType?: string;
  role?: string;
  label?: string;
  semanticDescription?: string;
  parentContext?: string[];
  nearbyText?: string[];
  visible?: boolean;
  enabled?: boolean;
  bounds?: { x: number; y: number; width: number; height: number };
  spatialRelation?: "inside" | "overlap" | "near" | "outside";
  capabilityRefs?: string[];
  observationEpoch: string;
};
```

Rules:

- candidate IDs are ephemeral to an observation epoch;
- external providers should receive aliases/semantic descriptions, not raw live handles where possible;
- only local runtime code can map the candidate back to the actual object;
- stale candidates are rejected before execution.

---

# 13. Semantic Target Resolver

New internal component:

```python
resolve_target(
    intent,
    candidates,
    app_context,
    spatial_context=None,
    mission_context=None,
) -> TargetResolution
```

Result concept:

```python
TargetResolution = {
    "candidate_id": "...",
    "distribution": {...},
    "confidence": 0.0,
    "abstain": False,
    "provider": "typesafe-jev",
}
```

It never executes, authorizes, or invents selectors.

---

# 14. Canonical target-resolution pipeline

```text
USER / AGENT INTENT
        ↓
SYSTEM-TWO REASONING
        ↓
APP / SCREEN OBSERVATION
        ├─ plugin object model
        ├─ connector/API
        ├─ DOM
        ├─ UIA/accessibility
        ├─ OCR
        └─ VLM candidate generation
        ↓
DETERMINISTIC PREFILTER
        ├─ correct app/window
        ├─ visible/enabled
        ├─ valid role/type
        ├─ capability compatibility
        ├─ spatial region
        └─ stale objects removed
        ↓
SEMANTIC TARGET RESOLVER
        ├─ Jev Choice
        ├─ Jev Noul
        └─ Jev Score
        ↓
TARGET + DISTRIBUTION + CONFIDENCE
        ↓
DETERMINISTIC RE-BIND
        ├─ same epoch?
        ├─ same HWND/PID/process?
        ├─ object still exists?
        ├─ enabled/actionable?
        └─ capability still registered?
        ↓
AUTHORITY CHAIN
        ↓
TEACH / ASSIST / ACT
        ↓
INDEPENDENT VERIFICATION
```

---

# 15. Confidence policy

Do not hard-code permanent confidence thresholds until Orbyn-specific evaluation exists.

Use policy bands:

```text
HIGH       → proceed to deterministic validation
MEDIUM     → highlight / confirm / gather more context
LOW        → fallback perception / Spatial Context / abstain
```

Bands may differ by:

- app;
- mode;
- authority level;
- candidate source;
- enterprise policy;
- action risk.

Teach can tolerate lower target confidence because it is non-executing.

High confidence never removes required human approval for higher-risk actions.

---

# 16. Spatial Context

Spatial Context / Point & Ask is a **core interaction primitive**, not an Agent or Plugin.

It represents:

- points;
- circles;
- polygons;
- arrows;
- source/target marks;
- associated app/window;
- screenshot/frame references;
- candidate objects;
- confidence;
- utterance;
- sensitivity classification.

Locked rule:

> **Spatial context provides reference, never authority.**

Circling a Delete control never grants permission to delete.

---

# 17. Jev + Spatial Context

They solve different parts of the same problem:

- Spatial Context narrows **where**.
- Jev helps resolve **what**.

```text
user circles region
        ↓
SpatialContextReference
        ↓
geometry filter
        ↓
plugin/UIA/DOM candidates
        ↓
Jev semantic choice/ranking
        ↓
best candidate + confidence
        ↓
fresh re-bind
        ↓
normal authority chain
```

Two-mark form:

```text
SOURCE mark A + TARGET mark B
```

supports:

- move this here;
- make this match this;
- apply this style to these;
- connect this to this.

---

# 18. Browser and generic Windows behavior

## Browser

```text
DOM / browser connector
→ real nodes
→ deterministic filter
→ Jev semantic resolution
→ DOM action
→ verification
```

Never let a model invent a CSS selector if a real node already exists.

## Generic Windows

```text
UIA
→ real accessible elements
→ process/visibility/role filter
→ Jev
→ fresh UIA re-bind
→ pointer or permitted UIA action
→ verification
```

## Legacy/inaccessible app

```text
screenshot
→ OCR/VLM candidate generation
→ Jev candidate selection
→ Teach/Assist unless reviewed execution boundary exists
```

Jev is not a universal visual grounding model.

---

# PART IV — APPS, SKILLS, AGENTS, BRAINS, COLLABORATION

# 19. Connected App contract

User-facing concept: **Connect an App**.

Each App exposes:

```text
Observe
Act
Verify
Events
Permissions
```

Internally an App may be backed by:

- API;
- OAuth;
- MCP;
- signed native plugin;
- UIA/accessibility adapter;
- vision fallback.

Apps may additionally expose internal semantic hints:

- candidate descriptions;
- aliases;
- parent context;
- object type;
- capability compatibility;
- resource identity;
- stability metadata.

These improve Semantic Target Resolution without adding a user-facing primitive.

---

# 20. Skills

A Skill is signed declarative expertise/procedure, not executable authority.

A Skill may contain:

- domain knowledge;
- workflow guidance;
- examples;
- constraints;
- required Apps;
- capability references;
- verification requirements;
- escalation guidance;
- risk metadata.

A Skill never bypasses the capability registry or `authorize_intent()` path.

---

# 21. Agents

An Agent is:

```text
goal + Skills + Apps + context + policy
```

The core must remain generic.

Application-named Agents are signed data/metadata, not application-specific Python in core.

Examples:

- Presentation Agent;
- Research Agent;
- Coding Agent;
- Sales Agent;
- Support Agent;
- Design Critic;
- Maintenance Agent.

Agent execution must still pass every node through normal authorization and verification.

---

# 22. Personal Brain and Company Brain

## Personal Brain

Future memory types:

- working;
- episodic;
- semantic;
- procedural;
- preference.

Scopes:

- session;
- personal;
- project;
- team;
- company.

Some memories must decay or expire.

## Company Brain / Context Graph

This is **not** PDFs in a vector database.

Knowledge is pinned to real objects with:

- source;
- owner;
- provenance;
- review state;
- validity;
- scope;
- last verified time;
- dependencies;
- staleness.

Graph may contain:

```text
People • Agents • Apps • APIs • Code • Services • Customers • Products
Goals • Tasks • Decisions • Permissions • Policies • Memories • Actions
Verification • Failures • Recovery
```

Learning loop:

```text
human resolves exception
→ candidate knowledge
→ owner review
→ approved Skill
→ future Missions need less intervention
```

Documents never become executable authority automatically.

---

# 23. Jev inside the Brain

Allowed:

- candidate relation scoring;
- staleness triage;
- candidate impact classification;
- context relevance ranking.

Not allowed:

- silently promoting facts to approved truth;
- creating executable policy;
- bypassing provenance/review.

---

# 24. Mission and Task Graph

A Mission owns persistent work.

A Task Graph node may eventually include:

```text
owner
executor
dependencies
permissions
expected result
verification
artifacts
resources
context
status
```

The graph is inert until authorized.

Chats belong to Missions; Missions do not belong to chats.

---

# 25. Workstreams and handoffs

Workstreams are parallel subdivisions of a Mission.

Each contains:

- owner;
- agents;
- objective;
- resources;
- permissions;
- dependencies;
- status;
- artifacts;
- context.

Handoff payload:

- goal;
- current state;
- completed work;
- decisions;
- Apps touched;
- pending actions;
- evidence;
- approvals;
- next steps.

Handoffs must be lossless enough that the recipient does not need a complete re-explanation.

---

# 26. Mission Control

Compact side panel remains the always-available execution surface.

Expanded Mission Control eventually shows:

- Mission;
- humans;
- agents;
- Workstreams;
- shared plan;
- status;
- Apps;
- resources;
- artifacts;
- Brain/context;
- approvals;
- evidence;
- activity;
- errors;
- handoffs;
- collisions.

Mission Control is not just a larger chat.

---

# 27. Needs You

Target form:

```text
NEEDS YOU

Agent wants to: <action>
Why: <reason>
Resource: <resource>
Requested by: <human sponsor>
Risk: <risk class>
Rollback: <available / unavailable>
Verification: <how success will be checked>
Evidence: <relevant evidence>

[Allow Once] [Modify] [Reject]
```

Later low-risk scoped option may be:

```text
Allow for Mission
```

Never provide "allow everything forever".

---

# 28. Coordination Engine

Primary deterministic jobs:

- ownership;
- resource claims;
- scheduling;
- dependency resolution;
- exact resource collisions;
- handoff coordination.

Jev may add advisory semantic collision scoring where exact resources differ but meaning overlaps.

Example:

```text
Marketing Agent edits homepage headline
SEO Agent changes positioning language
→ semantic collision score
→ policy decides warn/wait/coordinate
```

Jev never directly cancels or authorizes actions outside deterministic Mission policy.

---

# PART V — TRUSTED RUNTIME FEATURES

# 29. Current built / partial trust stack

According to current repo truth in the source plan:

### Built

- signed `.ghostplugin` bundles;
- sole authority minting path;
- distinct Teach/Act tokens;
- capability registry;
- whole-graph validation;
- per-node fresh authorization;
- exact process identity binding;
- signed read-only verifiers;
- UIA live verification;
- artifact verification;
- presentation receipts;
- coordinate-space contract;
- verified Python bootstrap;
- transactional output staging/publish;
- keyed/HMAC-style opt-in audit commitments;
- deterministic authority boundary;
- Ask/Pause/Stop rail;
- measured interruption path;
- UIA perception;
- OCR perception;
- pointer truth contract.

### Partial

- Mission/session abstraction;
- expanded Mission Control seed;
- Needs You fields;
- recovery;
- Personal Brain;
- Event Bus;
- Model Router;
- Connected App contract;
- Artifact Intelligence;
- confidence/recovery strategy.

### Designed, not built

- Skills;
- Agents;
- Connectors/API/OAuth/MCP;
- full Spatial Context;
- Jev/System-One layer;
- Workstreams;
- Multiplayer;
- Company Brain graph;
- Coordination Engine;
- RBAC;
- Credential Vault;
- code sandbox;
- third-party marketplace;
- dynamic interfaces;
- voice;
- general computer-use fallback.

---

# 30. Critical repo truth / claims discipline

Do not misstate historical evidence.

Current source says:

- Windows-native runtime / live observation / planning / local inference: true.
- signed capabilities / bounded approved execution: implemented.
- Pause/Stop/intervention: built and measured.
- independent verification: built.
- PowerPoint Act: implemented but activation **NOT READY** until outstanding gates close.
- VS Code Teach gates historically closed, but plugin currently disabled.
- Excel historical feasibility exists, but bundle disabled.
- GrowthOS Docker/PWA/EmbeddingGemma/Pricing-Agent evidence belongs to a separate codebase and must not be claimed as Orbyn repo evidence.

Never upgrade "implemented" into "accepted/READY" without the retained evidence and required independent review.

---

# PART VI — NETWORK / JEV DECISION AMENDMENTS

# 31. D141-R1 — consented network intelligence and connector tier

This amends D017 while preserving its original purpose.

## Default remains

- local-only fresh install;
- hermetic offline test baseline;
- air-gapped option;
- safe offline Teach behavior.

## New explicit opt-in capabilities

1. Connected App networking: API/OAuth/MCP/events.
2. System-Two cloud escalation under policy.
3. **System-One decision providers, initial provider TypeSafe Jev.**
4. Events-only telemetry, off by default.

## Jev network rules

May receive minimum necessary:

- intent;
- candidate semantics;
- role/type/name;
- minimal app context;
- spatial relation.

Prefer not to send:

- full accessibility trees;
- raw screenshots;
- full documents;
- credentials;
- secrets;
- unnecessary source code;
- unrelated customer content.

Never send:

- authority token;
- signing key;
- credential vault secret;
- approval token.

Provider failure must fall back safely.

---

# 32. D142 — Agents and Skills are signed plugin-scoped data

Clarifies the existing no-app-specific-core rule.

- Core never imports application adapters.
- Core never gains application-specific branches.
- Application-named Agent/Skill definitions are signed data/metadata.
- Generic executor composes only registered capabilities.
- Every node still passes authorization and independent verification.

---

# 33. D143 — Spatial Context is brief content

Clarifies the brief boundary.

- SpatialContextReference is hashed context.
- It may inform a proposed capability and scalar parameters.
- It is never an executable selector, target identity, or action.
- Plugin resolves spatial reference to application objects.
- Circling a control never authorizes acting on it.

---

# 34. D144 — signing identity / rotation / revocation

Before marketplace/re-enabling quarantined bundles, implement:

- key IDs;
- validity windows;
- successor keys;
- revocation list;
- catalog-load revocation checks;
- runtime authority rechecks;
- provenance for re-signing.

Then Excel/VS Code may be deliberately re-keyed with new evidence/review.

---

# 35. D145 — System-One decision boundary

System-One models may make semantic decisions over **closed runtime-provided options**.

Allowed:

- target selection;
- ranking;
- classification;
- registered capability routing;
- event routing;
- recovery ranking;
- graph relation scoring;
- semantic collision scoring;
- semantic verification evidence.

Forbidden:

- authority;
- permission;
- approval bypass;
- arbitrary selectors;
- resource invention;
- capability invention;
- signature validation;
- credential exposure;
- RBAC override;
- policy override;
- replacing deterministic verification.

Every selected object must be:

1. known to current runtime;
2. represented by current candidate ID;
3. freshly re-bound;
4. passed through full authority chain;
5. independently verified after execution.

---

# PART VII — SYSTEM-ONE IMPLEMENTATION DETAILS

# 36. Provider abstraction

Do not scatter provider-specific calls through core.

```python
class SystemOneProvider:
    def choose(self, state, question, options): ...
    def noul(self, state, question): ...
    def score(self, state, question, scale): ...
```

Result should record:

- value;
- distribution;
- confidence;
- provider;
- model version;
- latency;
- request digest;
- schema version.

Initial provider:

```text
TypeSafeJevProvider
```

Fallbacks:

```text
DeterministicHeuristicProvider
LocalStructuredModelProvider
SystemTwoStructuredFallback
```

---

# 37. Jev primitive mapping

## Choice

Use for finite candidates:

- UI target;
- DOM node;
- capability;
- event destination;
- recovery branch;
- owner/workstream;
- resource.

## Noul

Use for probabilistic propositions:

- candidate semantic match;
- event belongs to Mission;
- context item likely stale;
- recovery branch applicable;
- observed state semantically consistent.

## Score

Use for:

- relevance;
- ambiguity;
- candidate fit;
- recovery suitability;
- context relevance;
- artifact quality;
- semantic conflict severity.

---

# 38. High-cardinality candidate handling

Do not send huge raw trees.

Example:

```text
1,800 UIA nodes
→ bound window
→ 430
→ visible/actionable
→ 122
→ role/geometry/capability filter
→ 54
→ Jev Choice
```

For larger sets:

```text
all candidates
→ Score/Noul relevance
→ top N
→ Choice
```

Keep provider cardinality constraints behind the adapter.

---

# 39. Jev outage behavior

Fallback ladder:

```text
deterministic exact/fuzzy match
→ local structured model / embeddings
→ System-Two structured fallback
→ Spatial Context / user confirmation
→ Teach/Assist / refusal
```

Never:

```text
Jev unavailable → guess coordinate
```

---

# 40. Jev security

1. Store API key in OS-secure storage / future Credential Vault.
2. Only `SystemOneProvider` layer may access it.
3. Plugins, Skills, Agents never receive it.
4. Minimize request state.
5. Redact secrets and personal data.
6. Use ephemeral aliases for candidates when practical.
7. Validate provider response schema.
8. Resolve selected alias locally.
9. Never send authority tokens.
10. Active calls must respect Pause/Stop where they affect the live workflow.

---

# 41. Jev decision audit

For consequential semantic decisions, record locally:

- provider;
- model/version;
- request schema version;
- candidate-set digest;
- question digest;
- selected candidate ID;
- distribution/confidence;
- latency;
- decision-policy version;
- fallback used;
- eventual action;
- verification outcome.

Do not log sensitive full candidate content by default.

---

# 42. Target-resolution evaluation program

Build `Orbyn Target Resolution Eval`.

Initial apps:

- PowerPoint;
- Browser/DOM;
- VS Code;
- Excel;
- Windows Settings;
- later one legacy app.

Each test case stores:

```text
user_intent
candidate set
ground-truth target
candidate source
spatial mark if present
```

Compare:

1. deterministic matching;
2. embeddings;
3. local Qwen structured choice;
4. Jev;
5. frontier System-Two model.

Measure:

- Top-1 accuracy;
- Top-3 accuracy;
- calibration;
- abstention quality;
- false-high-confidence rate;
- latency;
- cost;
- repeated-run stability;
- accuracy by perception source;
- accuracy with/without Spatial Context.

Most important metric:

> **When the semantic resolver is wrong, does confidence allow Orbyn to avoid acting?**

---

# PART VIII — COMPLETE FEATURE CATALOGUE

# 43. Experience layer

| Feature | Purpose | Status / phase |
|---|---|---|
| Ask / Pause / Stop rail | User is never trapped | Built |
| Compact panel ↔ expanded workspace | Planning/review need room; execution stays compact | Built candidate / review pending |
| Mission Control | Shared operational view | Later |
| Needs You rich card | Action-specific accountable approval | Partial → expand |
| Spatial Context | Pointing beats describing | Phase 2 |
| Bidirectional pointing | Human↔AI shared spatial language | Pointer side built; full context later |
| Watch Build / Quick Build | Visible paced execution | Built |
| Voice | Redirect while work continues | Later |
| Dynamic task-shaped UI | Role/task-specific interfaces | Later |
| Join Agent | Human enters active workstream | Multiplayer phase |
| Presence | See people/agents/status | Multiplayer phase |

---

# 44. Modes

| Mode | Meaning | Status |
|---|---|---|
| Ideate | thinking partner → Mission | preview/partial |
| Discuss | trade-offs | conceptual |
| Teach | explain + point + verify; no action | built |
| Assist | human acts, AI helps | preview/partial |
| Act | approved signed execution | implemented, activation not ready |
| Autopilot | approved bounded workflow | future |
| Watch | observe, intervene when useful | future |
| Collaborate | multi-human / multi-agent | future |

---

# 45. Mission engine

| Feature | Status |
|---|---|
| Mission object | Partial |
| Task Graph | Built for bounded single-plugin capabilities |
| Brief / Ideation loop | Partial |
| Workstreams | Designed |
| Handoffs | Designed |
| Resume with edited plan | Designed / ordered |
| Async continuation | Designed |
| Artifacts + provenance | Partial |
| Artifact Intelligence / Critics | Partial |

---

# 46. Trusted runtime

| Feature | Status |
|---|---|
| Signed capabilities | Built |
| Capability registry | Built |
| Whole-graph validation | Built |
| Per-node fresh authorization | Built |
| Independent verifier | Built |
| Receipts | Built |
| Coordinate-space contract | Built |
| Process identity binding | Built |
| Verified Python bootstrap | Built |
| Transactional output | Built |
| Audit commitments | Built, limited/opt-in |
| Rollback | Designed |
| Code sandbox | Designed |
| Credential Vault | Designed |
| Policy/Risk/RBAC | Designed |
| Confidence & recovery | Partial |
| Event Bus | Partial |
| Deterministic authority | Built |

---

# 47. Intelligence

| Feature | Status |
|---|---|
| Model Router | Partial local |
| System-One Provider abstraction | Phase 2 |
| TypeSafe Jev Provider | Phase 2 |
| Semantic Target Resolver | Phase 2 |
| Candidate Registry | Phase 2 |
| Personal Brain | Partial seeds |
| Company Brain / Context Graph | Designed |
| Expert-resolution → approved Skill | Designed |
| Experts | Designed |
| Verified Interaction / Execution Graph | Early partial |
| Local-first privacy | Strict current baseline |
| Telemetry | blocked until D141-R1 path |
| Behaviour sync | later / consented |

---

# 48. Capability layer

| Feature | Status |
|---|---|
| Connected App contract | Partial plugin side |
| PowerPoint plugin | Narrow built implementation |
| Excel plugin | disabled / quarantine |
| VS Code plugin | disabled / quarantine |
| Connectors | Designed |
| Skills | Designed |
| Agents | Designed |
| Packages | Designed |
| First-party Marketplace | Designed |
| Repo Analyzer / Plugin SDK | Designed |
| Suggested Missions from connected Apps | Designed |

---

# 49. Collaboration kernel

Designed, not built:

- shared Missions;
- workstreams;
- multiple humans;
- multiple agents;
- presence;
- Join;
- Redirect;
- Take Control;
- comments;
- shared plan;
- notifications;
- handoffs;
- resource claims;
- exact collision detection;
- semantic collision scoring;
- per-workstream model selection;
- Team Brain.

---

# PART IX — PHASED IMPLEMENTATION PROGRAM

The coding agent must implement in this order unless the owner explicitly changes priorities with a recorded amendment.

Each Mega Phase includes:

- objective;
- prerequisites;
- build slices;
- files/contracts likely affected;
- tests/evidence;
- exit gate;
- forbidden shortcuts.

---

# MEGA PHASE 0 — CLOSE THE EXISTING TRUST / ACTIVATION GATES

## Objective

Finish the current PowerPoint Limited Act v1 evidence and activation program **before widening the product**.

This phase is about proving the current trust boundary, not adding product scope.

## Current state

Source plan says:

- Teach runtime is built/gated.
- PowerPoint Limited Act v1 is implemented.
- Activation is **NOT READY**.
- prior diagnostic campaigns do not count as READY evidence.

## Workstreams

### 0A. Confirmation-to-invoke budget

Tasks:

1. Review `ghostcursor.devtools.confirmation_budget` or current equivalent.
2. Retain raw records.
3. Derive budget from records.
4. Add production refusal/ceiling if required by standing decisions.
5. Request independent D032 review.

Deliverable:

- retained measurement records;
- derived budget document;
- production check;
- independent review status.

### 0B. Interruption latency matrix

Measure required interruption paths.

Include:

- normal execution;
- pending operation;
- slow path;
- UI state changes;
- any current documented lanes.

Retain raw evidence.

Do not self-certify D032.

### 0C. Desktop lanes

Run each required desktop lane alone as required by D025.

Retain output separately.

Do not combine them into one misleading campaign.

### 0D. Animation catalog

Run and count the animation-catalog campaign that has never been counted.

### 0E. UIA slice

For `add-slide-uia-v1` or current named slice:

- independent review;
- externally signed bytes as required;
- own counted campaign;
- no scope widening.

### 0F. Fresh counted campaign

Only after independent READY verdict on prerequisites:

- run fresh harness path;
- run manager path;
- retain exact outputs;
- do not edit captured evidence.

### 0G. Activation review

Request fresh D032 activation review.

## Phase 0 tests/evidence

- all existing trust tests;
- signed capability path;
- one-use authorization;
- exact HWND/PID binding;
- Pause/Stop timing;
- verifier independence;
- receipt budgets;
- transactional output;
- no evidence mutation.

## Exit gate

Phase 0 ends only when the actual repo/decision process records an acceptable activation state.

If review says NOT READY, fix only the findings and rerun required evidence.

## Forbidden shortcuts

- no Jev integration in Act;
- no new network path;
- no cross-app Missions;
- no Agents/Skills marketplace;
- no raw input synthesis;
- no claim that PowerPoint Act is accepted before the review says so.

---

# MEGA PHASE 1 — ARCHITECT-NOW SCHEMA + ORBYN PRODUCT IDENTITY

## Objective

Prepare the data model so later Missions/Multiplayer do not require a rewrite, without widening execution authority.

This phase can partly run as docs/schema work alongside Phase 0 if it does not touch the execution boundary.

## 1A. Product naming

- Product/docs/UI strings: **Orbyn**.
- Python/package paths remain `ghostcursor` unless a future reviewed migration is explicitly approved.
- Do not rename signed payload paths casually; digests/evidence depend on them.

## 1B. Mission schema intent

Extend schemas/interfaces to be capable of carrying cardinality-one versions of:

- `Mission`
- `Participant`
- `Workstream`
- `Resource`
- `Artifact`
- `Handoff`
- `ContextReference`

Important:

- schema only;
- do not add multi-user execution;
- do not add cross-plugin execution;
- do not make context fields authority-bearing.

## 1C. Persisted versioning

Every new schema requires:

- version number;
- migration strategy;
- backwards compatibility plan;
- tests loading older current state.

## 1D. Decision records

Record owner-approved decisions/amendments in repository decision documents rather than leaving them only in this file.

Likely:

- Orbyn naming note;
- D141-R1 draft planned for Phase 2/3 network entry;
- D142 clarification;
- D143 clarification;
- D145 after System-One design review.

## Exit gate

- current execution behavior unchanged;
- existing tests remain green;
- new schemas round-trip;
- no new authority path;
- Mission naming/schema is available to Phase 2.

---

# MEGA PHASE 2 — IDEATE / PLAN + SPATIAL CONTEXT + SYSTEM-ONE FOUNDATION

## Objective

Create the first complete **intent → plan → semantic target → safe execution context** pipeline while keeping Jev outside authority.

This is the phase where the System-One + System-Two split becomes real.

## Prerequisite

Phase 0 activation gate must be satisfied before Jev affects Act. Teach-mode development/evaluation can begin earlier only if it does not alter Act authority.

## 2A. Clarification vs PlanProposal

Implement explicit result types:

```text
ClarificationRequired
PlanProposal
```

Planner must not blur them.

Flow:

```text
goal
→ clarification if needed
→ persistent brief
→ capability-scoped graph
→ flattened plan
→ explicit approval
```

The brief remains context, not authority.

## 2B. Candidate registry

Implement:

- `CandidateObject`;
- observation epoch;
- candidate lifecycle;
- stale candidate rejection;
- source quality metadata;
- candidate digesting;
- ephemeral provider aliases.

Tests:

- candidate cannot cross epoch;
- candidate from wrong process rejected;
- hidden/disabled filtering;
- alias maps to exactly one local candidate;
- serialization contains no raw authority token.

## 2C. `SystemOneProvider`

Implement generic interface first.

Providers:

1. deterministic heuristic baseline;
2. optional local structured fallback;
3. `TypeSafeJevProvider`.

Core code should not import Jev client directly outside provider layer.

## 2D. D141-R1 network tier

Implement explicit consented networking for Jev only after decision record is approved.

Requirements:

- off by default;
- revocable;
- API key secure storage;
- context minimization;
- no raw authority tokens;
- provider/model/version recorded;
- timeout/cancellation;
- safe fallback;
- hermetic tests remain offline.

## 2E. SemanticTargetResolver

Implement provider-neutral resolver.

Input:

- intent;
- candidate set;
- app context;
- optional Spatial Context;
- optional Mission context digest.

Output:

- selected candidate;
- distribution;
- confidence;
- abstention;
- provider metadata.

No action execution inside resolver.

## 2F. PowerPoint Teach target resolution

First field integration:

```text
user request
→ PowerPoint/UIA candidates
→ deterministic filter
→ Jev Choice
→ fresh re-bind
→ pointer highlight
→ human acts
→ existing verifier observes result
```

This is intentionally Teach-first.

## 2G. Spatial Context v1

Implement:

- hotkey/start gesture;
- point/circle/polygon mark;
- `SpatialContextReference`;
- screen region;
- frame/crop ref;
- sensitivity class;
- candidate narrowing;
- brief hashing;
- plugin resolution.

No action identity is stored as authority.

## 2H. Spatial Context + Jev

Use geometry to reduce candidates, Jev to resolve semantic ambiguity.

Add SOURCE/TARGET two-mark support if feasible after single-mark passes.

## 2I. Orbyn Target Resolution Eval

Build evaluation harness before Act semantic selection.

Dataset should start with PowerPoint and later browser/other apps.

Required metrics:

- top-1;
- top-3;
- calibration;
- false-high-confidence;
- abstention;
- latency;
- repeatability;
- source breakdown;
- with/without spatial context.

## 2J. Confidence policy

Do not hard-code universal numeric thresholds until eval exists.

Implement policy bands and configuration.

## 2K. Act integration

Only after Teach eval/review:

- resolver supplies candidate;
- runtime freshly re-binds;
- existing authorization path mints authority;
- execution uses registered capability;
- verifier checks result.

## Exit gate

- Jev target selection works in Teach with retained eval evidence;
- stale/wrong-process candidates fail closed;
- Spatial Context narrows candidates;
- provider outage falls back safely;
- no authority token leaves the machine/provider boundary;
- Act integration, if enabled, uses the unchanged authority chain;
- independent verification still decides completion.

---

# MEGA PHASE 3 — SEMANTIC POWERPOINT MISSION / PRESENTATION AGENT

## Objective

Turn the low-level PowerPoint runtime into the first user-meaningful Mission product without violating plugin/core boundaries.

This is the first place Orbyn should feel like a product rather than a technical substrate.

## 3A. Semantic PowerPoint capabilities

Add reviewed plugin-scoped capabilities such as:

- `inspect_deck`
- `create_deck`
- `apply_theme`
- `create_title_slide`
- `create_content_slide`
- `create_comparison_slide`
- `create_process_slide`
- `add_speaker_notes`
- `publish_deck`
- `apply_restrained_motion` if evidence supports it.

Each semantic capability must expand deterministically into reviewed lower-level operations.

Core stays application-neutral.

## 3B. Presentation Agent as signed data

Presentation Agent is:

```text
goal + presentation skills + PowerPoint capability refs + policy + verification requirements
```

It is not application-specific core Python.

## 3C. Brief-to-deck Mission

Flow:

```text
user goal
→ clarify audience/objective/constraints/evidence
→ persistent brief
→ System Two creates narrative/plan
→ user reviews plan
→ semantic plugin capabilities execute
→ user can Pause/Stop/Take Control
→ artifact critic reviews
→ independent verification
→ Mission summary/evidence
```

## 3D. Existing-deck refinement

Support:

- inspect existing deck;
- preserve theme;
- propose changes;
- apply feedback;
- spatially reference slide objects;
- verify requested changes.

## 3E. Resume with edited plan

Requirements:

- completed side-effecting nodes never blindly replay;
- observe fresh state;
- revalidate remaining graph;
- require reapproval where material plan changed.

## 3F. Artifact Critic

Read-only Presentation Critic.

Deterministic checks first, semantic critique second.

Jev may be used for narrow structured judgments; System Two handles deeper critique.

## 3G. Rich Needs You

Add:

- what;
- why;
- resource;
- requested-by;
- risk;
- rollback availability;
- verification plan;
- evidence.

## 3H. User validation instrumentation

Track events, not sensitive content:

- Mission started;
- plan approved/rejected;
- intervention;
- Stop/Pause;
- verification pass/fail;
- second Mission;
- time-to-usable-result.

If D141 network telemetry is not yet enabled, retain locally.

## Exit gate

- user can complete one real presentation Mission end-to-end;
- same user can bring a second Mission;
- no founder-only manual repair required for supported path;
- verification and intervention paths are truthful;
- app-specific code remains outside core.

---

# MEGA PHASE 4 — CAPABILITY PLATFORM: CONNECTED APPS, SKILLS, AGENTS, MODEL ROUTING

## Objective

Generalize from one PowerPoint Mission into the platform contract that can host many Apps and Agents.

## 4A. Connected App contract

Formalize:

```text
Observe
Act
Verify
Events
Permissions
```

Include internal candidate semantic hints.

Every App declares:

- capabilities;
- permissions;
- risk class;
- verification methods;
- event sources;
- resource types;
- candidate semantics.

## 4B. Skills

Implement signed declarative Skill files.

Lifecycle:

```text
knowledge
→ proposed Skill
→ human review
→ signed approved Skill
→ Mission retrieval
```

## 4C. Generic Agent executor

Agent executor:

- loads Agent/Skill data;
- sees only registered App capabilities;
- may use System Two planning;
- may use Jev for bounded routing;
- never bypasses authorization;
- never imports application adapters into core.

## 4D. Capability routing with Jev

Use Jev only among registered candidate capabilities.

Example:

```text
intent
→ capability candidates
→ Jev rank/Choice
→ planner proposes
→ deterministic authorization later
```

## 4E. Connectors

Implement API/OAuth/MCP framework under D141-R1.

Requirements:

- explicit scopes;
- per-App permissions;
- credential vault;
- no model-visible raw secrets;
- event subscription framework;
- verification callbacks.

## 4F. Model Router expansion

Support:

```text
System Two:
local / workhorse / frontier / vision / embeddings

System One:
Jev / local / deterministic
```

Routing factors:

- privacy;
- cost;
- latency;
- complexity;
- enterprise policy;
- availability.

## 4G. Signing rotation/revocation

Implement D144 before first-party marketplace.

Then deliberately re-evaluate Excel/VS Code bundle re-enablement.

## 4H. First-party marketplace

Categories:

- Apps;
- Agents;
- Skills;
- later Experts.

Lifecycle:

- install;
- enable;
- disable;
- upgrade;
- remove;
- revoke.

Only Orbyn-authored/signed packages initially.

## 4I. Packages

Initial package definitions may include:

- Professional;
- Developer;
- Student/Learning;
- Designer.

Packages compose the same runtime; they are not separate products.

## Exit gate

- at least two Apps beyond PowerPoint through same contract;
- one Agent completes a Mission using Skills;
- connector credential path does not expose secrets;
- Jev routing stays bounded to candidates;
- package install/disable/uninstall works;
- revocation is exercised, not theoretical.

---

# MEGA PHASE 5 — PERSONAL MULTI-AGENT MISSIONS / MISSION CONTROL

## Objective

Move from one user + one agent to one user + several agents working on one persistent Mission.

## 5A. Mission Control v1

One user, multiple Workstreams.

Show:

- Mission;
- Workstreams;
- agents;
- plan;
- status;
- Apps;
- artifacts;
- approvals;
- evidence.

No need for multi-human presence yet.

## 5B. Workstream model

Implement:

- workstream ID;
- owner;
- agent list;
- objective;
- resource claims;
- dependencies;
- status;
- context digest;
- artifacts.

## 5C. Parallel agents

Allow parallel read-only/research work first.

Gradually allow bounded concurrent action only where resource claims prevent conflicts.

## 5D. Agent-to-agent handoff

Implement structured handoff payload.

Test that context survives without hidden chat dependency.

## 5E. Personal Brain

Add:

- memory types;
- scopes;
- decay/TTL;
- explicit correction priority;
- deletion/reset/export controls later.

## 5F. Jev in multi-agent flow

Use for:

- event routing;
- workstream routing;
- recovery branch ranking;
- agent-trace observability.

Never for ownership/authority.

## 5G. Resource claims

Before full collision engine, implement single-user resource claim tracking as precursor.

## Exit gate

- Mission with at least two Workstreams completes;
- at least two agents contribute;
- handoff payload is lossless enough for continuation;
- resource claims prevent obvious duplicate edits;
- final outcome is verified.

---

# MEGA PHASE 6 — SELF-MAINTAINING APIs / SOFTWARE WEDGE

## Objective

Build the first high-value B2B Mission category using the platform built in Phases 0–5.

This is not a standalone architecture. It is an Orbyn package/category.

## Target wedge

API-heavy SaaS, dev-tool, infra, vertical SaaS, platform/integration teams.

Initial providers:

- OpenAI;
- Stripe;
- one generic OpenAPI source.

Initial repos:

- TypeScript;
- Python.

## 6A. GitHub connector

Needs:

- repo read;
- branch/PR operations under explicit scopes;
- webhook/events;
- verification of branch/PR state.

## 6B. Code sandbox

Pipeline:

```text
repo copy
→ isolated change
→ build
→ lint
→ test
→ evidence
```

No unreviewed production modification.

## 6C. System Graph seed

Company Brain subset for software relationships:

```text
service
→ uses API
→ affects endpoint
→ affects customer workflow
→ owned by team
```

## 6D. Maintenance Agent pipeline

```text
Change Agent
→ Impact Agent
→ Planner
→ Coding Agent
→ Verify Agent
→ Needs You
→ PR
→ post-merge verification
```

## 6E. Jev uses

Good:

- provider-change classification;
- affected-resource candidate scoring;
- service/workstream routing;
- narrow semantic verification evidence.

Forbidden:

- merge authority;
- repo credential access;
- bypassing PR approval;
- arbitrary code execution permission.

## 6F. Metrics

- changes detected;
- affected resources identified correctly;
- repairs proposed;
- tests passed;
- PRs generated;
- PRs approved;
- detection→verified-resolution time;
- intervention rate;
- repeat use;
- paid conversion.

North star:

> **% of detected external changes resolved through a verified Orbyn workflow.**

## Exit gate

One real repo + real provider change where Orbyn:

- independently discovers impact;
- identifies at least several affected call sites;
- proposes repair;
- sandbox tests pass;
- human approves;
- PR is created;
- outcome verifies;
- workflow repeats for a design partner.

---

# MEGA PHASE 7 — MULTIPLAYER: MULTIPLE HUMANS + MULTIPLE AGENTS

## Objective

Turn Missions into shared team work objects.

## 7A. Workspace model

Add:

- organization/team identity;
- members;
- roles;
- Mission access;
- shared Brain scope.

## 7B. Presence

Show:

- active humans;
- active agents;
- workstream status;
- waiting/blocked/Needs You.

Presence is informational, not authority.

## 7C. Join Agent

Human can enter an active Workstream and:

- ask;
- redirect;
- modify remaining plan;
- pause;
- take control;
- hand back.

When agent resumes, it must re-observe state.

## 7D. Shared plan / comments

Comments attach to:

- Mission;
- Workstream;
- artifact;
- resource;
- task;
- Spatial Context region.

## 7E. Multi-human handoffs

Support:

- human→human;
- human→agent;
- agent→human;
- agent→agent.

## 7F. Collision detection

Start deterministic:

- same file;
- same slide;
- same range;
- same CRM record;
- same branch.

Then add Jev semantic collision scoring for non-identical but overlapping changes.

## 7G. Per-agent controls

Ask/Pause/Stop/Take Control should apply to individual agents/workstreams as well as Mission-wide control.

## Exit gate

- at least two humans + two agents complete one Mission;
- one handoff occurs;
- one collision is detected and resolved;
- shared state remains coherent;
- verified outcome is produced.

---

# MEGA PHASE 8 — ORGANIZATIONAL INTELLIGENCE / CONTEXT GRAPH

## Objective

Make the Brain a governed organizational context system tied to real objects, not generic RAG.

## 8A. Graph data model

Nodes may include:

- people;
- agents;
- Apps;
- APIs;
- code;
- services;
- customers;
- products;
- goals;
- tasks;
- decisions;
- policies;
- permissions;
- memories;
- actions;
- verification;
- failures;
- recovery.

Edges carry:

- source/provenance;
- owner;
- confidence;
- review state;
- scope;
- last verified;
- staleness.

## 8B. Object-linked memory

Memory is pinned to the real object it describes.

Example:

```text
pricing decision
↔ pricing page
↔ CRM product
↔ sales deck
↔ proposal template
```

When object changes, dependent knowledge may become stale.

## 8C. Staleness engine

Inputs:

- deterministic dependencies;
- observed object changes;
- Jev candidate impact scoring.

Outputs:

- affected memories;
- affected workflows;
- review queue;
- confidence.

Jev does not auto-promote semantic guesses to truth.

## 8D. Expert-resolution capture

```text
human fixes exception
→ capture candidate knowledge
→ owner reviews
→ approve Skill
→ future Mission uses it
```

## 8E. Pre-diagnosed support

When escalation happens, package:

- goal;
- failed step;
- expected result;
- actual result;
- retries;
- evidence;
- likely owner;
- permissions context.

## Exit gate

- a real object change triggers stale-context detection;
- one human correction is reviewed into an approved Skill;
- future Mission uses that Skill without bypassing authority;
- provenance/ownership remain visible.

---

# MEGA PHASE 9 — ENTERPRISE EXECUTION / COORDINATION ENGINE

## Objective

Make Orbyn deployable for operations-heavy companies with governed cross-app work.

## 9A. Coordination Engine

Add:

- ownership;
- scheduling;
- dependency resolution;
- resource claims;
- exact collisions;
- semantic collisions;
- handoff orchestration;
- queueing;
- escalation.

## 9B. RBAC / policy engine

Roles may include:

- Owner;
- Admin;
- Manager;
- Employee;
- Agent;
- Plugin/App identity.

Authority still flows through the canonical chain.

## 9C. Cross-app Missions

This requires an explicit reviewed amendment to the current one-plugin-per-graph authority rules.

Do not implement by simply allowing a graph to name two plugins.

The design must define:

- per-App authorization;
- resource ownership;
- handoff boundaries;
- multi-App verification;
- failure semantics;
- rollback/recovery;
- audit ordering;
- approval scope.

## 9D. Enterprise deployment modes

Support policy-selectable:

- local-only;
- hybrid;
- private cloud;
- air-gapped;
- external Jev disabled;
- private/local System-One provider.

## 9E. Workflow analytics

Events, not content.

Measure:

- Mission completion;
- error rate;
- human intervention;
- support requests;
- handling time;
- time-to-productivity;
- verification failures;
- collision rate;
- recovery rate.

## 9F. Pilot shape

Example target:

```text
50 employees
2 Apps
3 workflows
```

Measure before/after.

## Exit gate

- real enterprise pilot;
- cross-app authority is reviewed and evidenced;
- RBAC works;
- private deployment mode works;
- audit/verification is complete enough for buyer review;
- measurable workflow ROI exists.

---

# MEGA PHASE 10 — LONG-TERM PLATFORM EXPANSION

This is thesis, not near-term schedule.

Possible directions:

- self-maintaining company workflows;
- dynamic interfaces by role/task/risk;
- voice during live work;
- third-party marketplace;
- Repo Analyzer / developer SDK;
- broader VLM perception;
- restricted general computer use under a new reviewed D006 amendment;
- cross-company workflows;
- organizational agents operating under human ownership;
- automated policy/change response Missions.

Nothing in this phase should be used to justify skipping earlier evidence gates.

---

# PART X — PRODUCT / CUSTOMER STRATEGY

# 50. ICPs

Full-platform ranking from the source plan:

1. Operations-heavy enterprises: GCC / BPO / shared services / finance & customer ops.
2. Mid-market ops / IT / enablement.
3. Consulting / professional services.
4. Engineering teams.
5. Enterprise sales / solutions.
6. Individual professionals.

Self-maintaining APIs wedge:

- API-heavy SaaS;
- dev-tool startups;
- infra companies;
- integration/platform teams.

---

# 51. B2C packages

Same runtime, different package composition.

## Student / Learning

Agents:

- Study Agent;
- Tutor Agent;
- Research Agent;
- Coding Agent.

Skills:

- Explain Like a Tutor;
- Socratic Tutor;
- Exam Prep;
- Research Paper Reader;
- Coding Tutor.

Apps:

- PDF/Browser;
- VS Code.

Killer interaction:

- point/circle a diagram/equation/code region;
- ask;
- get explanation;
- continue into quiz/mastery.

## Developer

- VS Code;
- Terminal;
- Git/GitHub;
- Docker;
- Browser;
- SWE/Architecture/Coding/Testing/Research/Documentation agents.

## Designer

- Figma/Photoshop/Blender/CAD/video tools;
- Design Expert;
- Critic;
- Spatial Context SOURCE/TARGET interactions.

## Professional

Current PowerPoint validation slice.

## Personal AI Team

One user + multiple agents + Mission Control.

---

# 52. Pricing thesis

Hybrid, not final.

Four monetized dimensions:

- **Breadth** — Apps/capabilities;
- **Intelligence** — experts/models;
- **Continuity** — memory/Brain;
- **Labour** — execution/agent usage.

Likely structure:

- Free;
- individual subscription;
- Pro with execution allowance / parallel agents;
- Team with shared Missions/Brain/handoffs/audit;
- Enterprise with platform fee + users/workflow volume + premium modules.

Users should not need to think in LLM tokens.

---

# 53. GTM / validation

Near-term:

```text
founder-led beta
→ real Mission usage
→ repeat use
→ design partners
→ paid bounded pilots
→ annual contracts
```

Optimize for:

> **second voluntary Mission**

rather than raw signup count.

Measure:

- supported Mission completion;
- repeat usage;
- intervention rate;
- verification success;
- time saved;
- willingness to pay;
- second Mission creation.

---

# 54. Competitive positioning

Do not lead with:

- AI Operating System;
- computer-use agent;
- AI employee;
- plugin marketplace;
- multiplayer workspace;
- Company Brain as the entire company.

Preferred:

> **Trusted execution layer where people and AI agents work together across the software a company already uses.**

Strategic white space:

```text
Digital Adoption
Teach users
        ↓
Orbyn
Teach → Assist → Act → Verify → Escalate → Learn
        ↓
Blind / rigid automation
```

---

# 55. Defensibility thesis

The model is not the moat.

Potential compounding asset:

> **Verified Interaction / Execution Graph**

It accumulates:

- application states;
- verified workflows;
- failures;
- recovery patterns;
- corrections;
- permissions;
- approvals;
- organizational context;
- expert resolutions.

Do not call it a moat before sufficient usage exists.

---

# PART XI — CODING AGENT PHASE PROTOCOL

# 56. Required behavior before starting a phase

For each Mega Phase, the coding agent must produce a **Phase Preflight** before code changes:

```text
Phase:
Current repo commit:
Relevant standing decisions:
Existing implementation:
Files likely touched:
Execution boundary impact:
Network impact:
Data migration impact:
Security/privacy impact:
Independent review required?:
Planned smallest slice:
```

If there is a conflict between repository decisions and this document, stop and surface it rather than silently choosing.

---

# 57. Required behavior during a phase

1. Implement one slice at a time.
2. Keep application-specific logic outside core.
3. Add tests with the slice.
4. Preserve fail-closed behavior.
5. Never introduce hidden authority through model prompts.
6. Never bypass signing/authorization for convenience.
7. Do not mix unrelated refactors with authority changes.
8. Record schema migrations.
9. Keep provider-specific code behind interfaces.
10. Retain evidence required by standing decisions.

---

# 58. Required phase checkpoint

At the end of each slice, record:

```text
What changed
What did not change
Files modified
Decisions added/amended
Tests run
Evidence retained
Known limitations
Security implications
Privacy implications
Activation status
Next slice
```

Do not say READY when the relevant independent review has not occurred.

---

# 59. Required phase exit report

Before moving to the next Mega Phase:

```text
PHASE EXIT

Objective achieved?:
Gate satisfied?:
Independent review satisfied?:
Regression suite status:
Authority boundary unchanged or amended?:
Evidence locations:
Open risks:
Deferred items:
Owner decisions needed:
```

If any mandatory gate is false, remain in the phase.

---

# 60. General test strategy

Every new capability should be tested across:

## Functional

- expected positive path;
- invalid input;
- missing capability;
- stale state;
- user interruption;
- retry/recovery where supported.

## Authority

- no token → no action;
- wrong plugin → no action;
- wrong process/window → no action;
- expired request → no action;
- changed catalog epoch → no action;
- model cannot mint authority.

## Semantic targeting

- correct candidate;
- ambiguous candidate;
- wrong high-confidence candidate;
- provider outage;
- stale candidate;
- Spatial Context narrowing;
- wrong process candidate;
- candidate removed between choice and action.

## Verification

- action succeeds / verifier passes;
- action fails / verifier fails;
- actor claims success but verifier disagrees;
- qualitative criterion uncertain;
- verifier remains read-only.

## Privacy

- credentials absent from provider request;
- authority tokens absent;
- screen content minimized;
- logs do not contain forbidden content.

## Multiplayer later

- resource collision;
- handoff;
- concurrent read;
- concurrent write conflict;
- human takeover;
- agent resumes from fresh observation.

---

# 61. System-One acceptance checklist

Before Jev can influence Act target selection:

- [ ] target eval dataset retained;
- [ ] eval harness reviewed;
- [ ] latency measured;
- [ ] calibration measured;
- [ ] false-high-confidence cases characterized;
- [ ] exact candidate rebind proven;
- [ ] stale observation rejection proven;
- [ ] wrong process/window rejection proven;
- [ ] Pause/Stop pending request proven;
- [ ] outage fallback proven;
- [ ] no authority token leakage;
- [ ] privacy/redaction tests green;
- [ ] verification independent;
- [ ] Teach-mode field trial completed.

---

# 62. Connected App acceptance checklist

For every App:

- [ ] Observe contract documented;
- [ ] Act capabilities registered;
- [ ] Verify paths defined;
- [ ] Events defined or explicitly unsupported;
- [ ] Permission scopes defined;
- [ ] candidate semantics defined;
- [ ] resource types defined;
- [ ] rollback semantics defined where possible;
- [ ] risk levels assigned;
- [ ] provider secrets protected;
- [ ] plugin/connector identity signed/verified;
- [ ] disable/revoke path tested.

---

# 63. Agent acceptance checklist

For every Agent:

- [ ] signed/declarative definition;
- [ ] Skills enumerated;
- [ ] Apps/capabilities enumerated;
- [ ] no direct adapter import;
- [ ] no authority shortcut;
- [ ] planning output inert until authorized;
- [ ] verification requirements specified;
- [ ] escalation behavior specified;
- [ ] Pause/Stop works;
- [ ] Mission owner/human sponsor identified.

---

# 64. Skill acceptance checklist

For every Skill:

- [ ] scope defined;
- [ ] knowledge source defined;
- [ ] provenance where applicable;
- [ ] preconditions defined;
- [ ] allowed tools/capabilities referenced, not invented;
- [ ] verification expectations defined;
- [ ] escalation defined;
- [ ] version/signature defined;
- [ ] disable/revoke path works.

---

# 65. Mission acceptance checklist

- [ ] explicit desired outcome;
- [ ] success criteria;
- [ ] human owner;
- [ ] participants;
- [ ] Apps;
- [ ] plan;
- [ ] permissions;
- [ ] resources;
- [ ] artifacts;
- [ ] approvals;
- [ ] evidence;
- [ ] verification;
- [ ] interruption controls;
- [ ] completion summary.

---

# 66. Company Brain acceptance checklist

- [ ] source;
- [ ] owner;
- [ ] scope;
- [ ] provenance;
- [ ] confidence;
- [ ] review status;
- [ ] last verified;
- [ ] linked real object;
- [ ] staleness handling;
- [ ] no automatic executable authority;
- [ ] human correction requires review before becoming Skill.

---

# PART XII — IMPLEMENTATION MODULE GUIDANCE

# 67. Suggested new internal modules

Adapt to repository conventions rather than forcing this exact tree.

```text
ghostcursor/
  intelligence/
    system_one/
      provider.py
      types.py
      policy.py
      resolver.py
      calibration.py
      providers/
        deterministic.py
        local.py
        typesafe_jev.py

  perception/
    candidates.py
    candidate_registry.py
    observation_epoch.py

  spatial/
    context.py
    resolver.py
```

Do not put PowerPoint-specific extraction in `system_one/`.

PowerPoint semantics belong in PowerPoint plugin/adapter code.

---

# 68. Event vocabulary direction

Potential events:

```text
mission.created
mission.completed
mission.failed
workstream.created
workstream.blocked
plan.created
plan.approved
plan.modified
action.proposed
action.approved
action.executed
action.refused
verification.passed
verification.failed
user.interrupted
user.took_control
handoff.created
resource.claimed
resource.collision
app.connected
app.disconnected
context.stale
skill.proposed
skill.approved
```

Do not add all at once. Add only as the corresponding phase lands.

---

# 69. Logging principle

> **Events, not content.**

Prefer:

- state transitions;
- hashes/digests;
- status;
- timing;
- capability IDs;
- verification outcome;
- error category.

Avoid:

- passwords;
- credentials;
- raw source code;
- arbitrary screenshots;
- private document contents;
- customer data;
- unredacted paths/handles where standing decisions forbid them.

---

# PART XIII — IMMEDIATE NEXT ACTIONS

# 70. What the coding agent should do first, today

Do **not** start Jev integration by editing the current Act runtime immediately.

Proceed in this order:

## First

Close the existing Phase 0 gates from the repository:

1. confirmation-to-invoke budget;
2. interruption-latency matrix;
3. desktop lanes;
4. animation-catalog campaign;
5. independent budget/UIA reviews;
6. fresh counted campaigns;
7. activation review.

## In parallel, docs/schema only

- record Orbyn product-name note;
- record the phase sequence;
- add architect-now Mission schema intent;
- prepare D141-R1/D145 proposals for owner review.

## After current Act boundary is READY

Start Mega Phase 2:

1. `CandidateObject`;
2. candidate registry;
3. observation epoch;
4. `SystemOneProvider`;
5. deterministic provider;
6. `TypeSafeJevProvider`;
7. `SemanticTargetResolver`;
8. PowerPoint Teach target resolution;
9. Spatial Context;
10. target-resolution eval;
11. calibration;
12. only then Act semantic target selection.

---

# 71. The one architecture statement every future coding agent must preserve

> **Observe → Structure → Reason → Choose → Authorize → Execute → Verify.**

Expanded:

> **Perception discovers what exists. System Two understands what the user wants. System One chooses among real bounded options. Deterministic policy decides what is allowed. Apps perform the action. Independent verification proves what happened.**

Any implementation that collapses these responsibilities into one unconstrained model call is architecturally wrong for Orbyn unless the owner explicitly changes the trust model in a reviewed decision.

---

# 72. Final non-negotiable constraint

The goal of new intelligence is to make Orbyn **more reliable**, not to create hidden autonomy shortcuts.

> **Jev may help Orbyn know which real option is probably the right one. Jev may never decide that Orbyn is allowed to act.**

> **System Two may propose a plan. The plan itself never has authority.**

> **A successful action is not a completed Mission until the result is independently verified.**

---

# APPENDIX A — PHASE DEPENDENCY MAP

```text
PHASE 0
Current trust / activation gates
        ↓
PHASE 1
Schema + Orbyn product identity
        ↓
PHASE 2
Ideate/Plan + Candidate Registry + Jev + Spatial Context
        ↓
PHASE 3
Semantic PowerPoint Mission / Presentation Agent
        ↓
PHASE 4
Connected Apps + Skills + Agents + Connectors + Marketplace
        ↓
PHASE 5
Personal multi-agent Missions + Mission Control
        ↓
PHASE 6
Self-maintaining APIs / software wedge
        ↓
PHASE 7
Multiple humans + Multiplayer collaboration
        ↓
PHASE 8
Company Brain / Context Graph
        ↓
PHASE 9
Enterprise Coordination + RBAC + cross-app Missions
        ↓
PHASE 10
Self-maintaining company / dynamic interfaces / third-party ecosystem
```

---

# APPENDIX B — WHAT NOT TO BUILD EARLY

Until the relevant phase:

- unrestricted computer-use agent;
- raw mouse/keyboard synthesis;
- cross-app action graphs;
- open third-party marketplace;
- full CRDT/live cursor multiplayer;
- huge Company Brain ingestion system;
- enterprise RBAC before team workflow value;
- general VLM-driven clicking;
- voice before core workflow retention;
- dozens of Apps before the App contract proves itself;
- complex pricing/billing before repeat use;
- model-provider UI as a primary product feature.

---

# APPENDIX C — SOURCE COVERAGE / MERGE NOTES

This master file intentionally integrates the two input documents rather than merely concatenating them.

Coverage from `ORBYN_UNIFIED_PLAN.md` includes:

- locked thesis / four pillars;
- lineage;
- canonical object model;
- target architecture;
- execution preference;
- authority chain;
- verification rule;
- YC RFS integrations;
- Spatial Context / Amoeba concepts;
- feature catalogue;
- current repo truth;
- current hard decisions;
- phased plan;
- business/ICP/pricing/GTM layer;
- B2C packages;
- resolved decisions / amendments;
- immediate repo actions.

Coverage from `ORBYN_JEV_SYSTEM_ONE_ADDENDUM.md` includes:

- System-One/System-Two split;
- Jev positioning;
- Semantic Target Resolver;
- CandidateObject / observation epoch;
- anti-hallucination target rule;
- Choice/Noul/Score mapping;
- confidence policy;
- Jev + Spatial Context;
- high-cardinality resolution;
- Jev in routing/recovery/Brain/Coordination/verification;
- prohibited Jev authority roles;
- Model Router provider abstraction;
- D141-R1 network amendment;
- D145 System-One boundary;
- security/logging/outage behavior;
- target-resolution evaluation and activation criteria;
- exact roadmap insertion points.

This file should therefore be sufficient as the single high-level implementation brief supplied to a coding agent, while repository files remain the ground truth for current code/evidence state.
