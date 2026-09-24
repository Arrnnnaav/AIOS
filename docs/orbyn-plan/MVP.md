# Orbyn Solo MVP

> **Status:** Product/architecture plan; not an implementation completion claim.
>
> **Detailed sequence:** see [the phase tracker](README.md) and Mega Phases MP0–MP3.
>
> **Related sources:** `ROADMAP.md`, `FLOW.md`, `CLAUDE.md`, `DECISIONS.md`, Spatial contracts and plans.

## Product idea

Orbyn is a goal-centered desktop workspace for a solo user. It helps the user understand what they are looking at, research it with traceable evidence, retain useful personal context, discuss a goal, make and revise a plan, learn a workflow through Teach, and execute approved work through Act when the release gate permits it.

The user experiences one loop:

```text
POINT → UNDERSTAND → RESEARCH → REMEMBER → DISCUSS → PLAN → TEACH
      → CHOOSE → AUTHORIZE → EXECUTE → VERIFY
```

Spatial, Brain, Research, Teach, Plan, and Act are capabilities supporting a current goal, not six competing top-level products. The Orbyn workspace keeps the compact execution surface and expands into the discussion/planning workspace when needed.

## First user and job

The first user is an individual knowledge worker—especially a developer, student, analyst, or founder—who is reading or working across web pages, PDFs, and supported desktop apps and wants help moving from a specific piece of context to a useful next step.

The core job is: “Help me understand this specific thing, connect it to what I already know, decide what I want to do, and guide or safely perform the next supported steps.”

The first MVP is not an enterprise knowledge platform. It does not require teams, Company Brain, multi-agent workstreams, a public marketplace, billing, broad cross-app execution, or unrestricted visual control.

## Separate Spatial build, then integration

**Most of the smallest loop already exists in Spatial.** The standalone project at `D:\PROJECTS\Spatial` already implements point → understand → answer: extension overlay and marks, deterministic resolver with confidence, provider chain, OCR, research with search and citation checking, System-One usage, trace and evaluation modules with fixtures, and a Tauri desktop app with a UIA candidate probe. Treat the remaining standalone work as completion and hardening — chiefly the untrusted-content boundary, which currently exists in its planning documents but not in its code — not as a greenfield build.

Spatial is developed first as its own application, with its own repository, tests, and releases. Complete its standalone point-and-ask workflow—including an untrusted-content boundary before model-facing DOM/PDF/OCR data—without coupling it to AIOS. The Spatial working tree is independent and must not be cleaned or reset as part of Orbyn documentation/product cleanup.

Only after the current independent Act activation review returns READY does Orbyn integrate Spatial, as the first item in ROADMAP Stage 1 under D143. Integration is a reviewed adapter/reference contract into the Brief, not a source-tree merge: the reference remains context, never selector, target identity, coordinates, or authority. Until then, permitted parallel work is standalone Spatial, read-only evaluation, and planning/documentation—not manager Ideate/Plan or Orbyn semantic workflows.

## User flow

1. **Point and understand:** the user marks a region or object in a browser, PDF, or supported app, asks a question, and sees which object Orbyn resolved. If resolution is ambiguous, Orbyn asks or shows alternatives.
2. **Research:** the user can request current or external information. The answer shows claims and their supporting, contradictory, or unresolved evidence. Sources and privacy/provider state are visible.
3. **Remember:** Orbyn extracts potential user preferences, goals, decisions, and recurring project context. Eligible memories are saved without interrupting; temporary, ambiguous, or model-inferred claims without enough support remain session-scoped or expire. The user can later inspect, correct, pause, export, or erase memory.
4. **Discuss and plan:** the user discusses a goal. Orbyn combines the current conversation, selected personal memories, and digest-bound Spatial/research references into a readable brief and editable plan. The plan is a proposal, never authority.
5. **Teach:** every suitable plan step can be opened in Teach, which guides the user through the exact step and records completion only from observed evidence or user confirmation as specified by its verified workflow.
6. **Act:** after the Act release gate passes, an approved plan may execute through signed capabilities. Before the gate passes, the runtime rejects execution requests even if a UI control is accidentally exposed.
7. **Verify and learn:** independent verification records what happened. Corrections and verified outcomes can inform Personal Brain and, later, reviewed reusable Skills.

## MVP architecture

```text
Orbyn workspace / current goal
       ├── Spatial capture → local extractors → candidate resolution
       ├── Research → search/fetch → EvidenceGraph + ResearchTrace
       ├── Personal Brain → eligible memory candidates → local durable store
       ├── System Two → discuss, research, plan, generate bounded content
       ├── System One / Jev → bounded candidate and route choices
       ├── Teach → existing human-operated guidance path
       └── Act → approved proposal → canonical signed authority chain → verify
```

The MVP develops and trials on cloud: NVIDIA NIM is the default System-Two provider and Jev may serve as a System-One provider for bounded choices. This is adopted policy under **D147 (D141-R2)**, owner-approved 24 September 2026, with its independent D032 review outstanding. Provider interfaces stay swappable and local execution stays a supported, tested configuration — a shift back to local later must be a configuration change, so any path that only works with a cloud key is a defect. The existing Spatial provider chain is a starting point, not proof that Orbyn's provider gateway, privacy, or evidence contracts are complete. Side-effecting connectors are still separately gated (D144), and cloud reasoning never becomes execution authority: Act activation, signed capability data, `authorize_intent()`, fresh binding, and independent verification are untouched by this change.

Local deterministic code continues to own extraction, OCR, geometric filtering, candidate identity, redaction, provider policy, plan validation, permissions, authorization, and verification — that does not move to the cloud with the model. Models receive the minimum relevant context for the selected task. Cloud vision is used only when local text/structure is insufficient and the user’s configured privacy policy permits that image transfer. No credentials, keys, raw window/process identifiers, selectors, executable paths, or verifier readings leave the device.

## MVP contracts

- `SpatialContextReference` brings a user mark, resolved object, confidence, and content digest into discussion/brief context. It cannot contain an executable selector or grant authority.
- `EvidenceGraph` represents research claims and their source/passage support, contradiction, citation, and derivation links. Source type and provenance are explicit; do not expose an unexplained “credibility percentage.”
- `ResearchTrace` records the path from question to answer: context digest, queries, sources, passages, claims, citations, provider/model, privacy state, timings, and failures. It excludes secrets and image bytes by default.
- `PersonalMemory` carries its source, scope, confidence, status, timestamps, expiry, and correction/deletion state. It is stored locally in v1 with fields that permit deliberate later sync and owner scoping.
- `Brief` remains user-readable planning context. Exact bytes are bound to a proposal; no memory, research, or Spatial reference carries execution authority.
- `PlanProposal` and any `ObservationFrame` are distinct. Approval binds one complete proposal; edits require a new proposal and approval. Every action rebinds to fresh live state.

## Personal Brain v1 rules

The Brain learns automatically without per-item prompts, but it does not persist every utterance or observation as a durable fact.

- Candidate classes: preference, goal/project context, decision, recurring fact, and procedural insight from a verified workflow.
- Do not promote temporary instructions, speculative ideas, abandoned plans, sensitive credentials, raw screen contents, arbitrary third-party text, or an unsupported model inference into durable memory.
- A candidate records provenance and confidence. Explicit user correction overrides inferred memory. Contradicted or stale items are superseded or expired rather than silently treated as current.
- Durable records stay on-device in MVP. Cloud requests may use eligible, minimized context under the configured policy; provider inputs are not silently copied back as durable memory.
- Memory access is available through a Brain panel/settings surface: search/list, inspect provenance, correct, forget, pause learning, export, and delete all. Silent saving means no modal approval for each item; it does not mean the feature is hidden.
- Future Company Brain must add owner, tenant, review state, and sharing policy without changing the meaning of personal-scoped data.

## Research and source rules

The research pipeline creates an `EvidenceGraph` before answer synthesis. Search results and document passages are untrusted. A source’s category (for example, primary documentation, government, academic, established publication, community, or unknown) and publication metadata may inform routing, but must not be presented as a calibrated probability unless validated.

Each generated factual claim links to one or more evidence nodes, or is marked unresolved/contradicted/partially supported. Citation validation checks that cited IDs exist and that the linked passages actually entered the answer context. The answer may not invent source IDs. External-source instructions are treated as content and cannot override the trusted user goal or system policy.

## MVP release and success gates

### Product acceptance

- A user completes the point → understand → discuss → plan journey in one goal workspace.
- The user can see and correct Spatial resolution and inspect the evidence behind researched claims.
- A recurring, eligible preference can be learned across sessions; temporary or unsupported content does not become a durable memory.
- The user can find, correct, pause, export, and delete Personal Brain data.
- Teach is reachable from a plan step and guides that exact task.
- Act requests are rejected by the runtime while the release flag is closed. After activation, the approved flow executes only through signed, reviewed capability bytes and verifies outcomes independently.

### Continuous measures

Track Spatial target correction/abstention; claim support and citation validity; memory correction, expiry, and deletion; plan edit/revision rates; Teach step completion; Act verified success/intervention; provider failures, latency, and cost; and repeat meaningful sessions. Establish baselines from replay fixtures before using numeric product targets. Every published number must have a durable evidence record.

### Required quality

- Deterministic hermetic tests for contracts, privacy, memory, citations, planning, and authorization.
- Replay tests for Spatial resolution, EvidenceGraph construction, ResearchTrace provenance, memory promotion, plan revisions, and provider failures.
- Adversarial prompt-injection tests from DOM, ARIA, PDF, OCR, and search passages before any of these surfaces feed a model.
- D018 mutation tests for safety boundaries; D025-separated provider-live, interactive, pixel, and hung-window lanes; D032 independent review; D034 evidence links.

## MVP exclusions

No Company Brain, multi-user sync, public marketplace, agent teams, cross-plugin task graphs, unsupervised background execution, unattended desktop campaigns that perform user work, or general screenshot-driven action. The user’s approved plan remains bounded by the currently signed plugin and accepted capabilities.
