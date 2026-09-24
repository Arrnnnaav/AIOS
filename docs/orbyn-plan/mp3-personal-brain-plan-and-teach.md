# MP3 — Personal Brain, Ideate/Plan, and Teach

## Purpose and phase grouping

Complete the solo-user product loop from durable context to an editable plan and actionable guidance. Detailed phases:

- **Phase 9 — Personal Brain v1**
- **Phase 10 — Ideate/Plan and proposal revisions**
- **Phase 11 — Teach tied to plan steps**

## Phase 9: Personal Brain v1

### Memory lifecycle

```text
session event or user statement
→ candidate extraction
→ deterministic eligibility/privacy checks
→ confidence and provenance checks
→ silent durable promotion OR session-only/expiry
→ retrieval with source and freshness
→ correction/supersession/deletion
```

Persist only a compact useful memory, not raw conversation or whole screens by default. Memory classes are preference, goal/project context, decision, recurring fact, and verified procedural insight.

Promotion rules for v1: an explicit, non-sensitive user statement that clearly expresses a durable preference or decision may be saved immediately; inferred preferences require the same signal in at least three distinct sessions; project context must link to a saved Brief or recur in at least two sessions; procedural insight requires at least two independently verified successful runs. Replay-test these initial rules for false promotion and missed useful memory before release. A candidate with conflict, weak provenance, uncertain scope, sensitivity, or an expiration condition remains session-scoped or expires; it does not silently become a durable fact. Repeated untrusted page text never counts as user endorsement.

Never durably promote credentials, payment/auth secrets, raw screen content, untrusted instructions, speculative model assumptions, temporary directions, or abandoned plans. Explicit user statements and corrections outrank inferred facts. Derived facts link to source-session or EvidenceGraph/ResearchTrace identifiers and expire/recheck when time-sensitive.

Durable storage is local in v1, with owner/scope/version fields designed for future opt-in sync. Memory records are separate from the existing UI-grounding `ObservationStore`; do not overload that store or its deletion semantics. Add a separate Personal Brain repository or a clearly isolated schema and migration. The user can inspect sources, correct, forget individual items, pause learning, export, and erase all memory. No modal approval per eligible item; expose a quiet activity/history view.

### Retrieval

Retrieve a small, relevant subset based on the current goal and provenance. Do not inject the entire Brain into every prompt. Tag retrieved content as user memory data; it cannot override current user instructions, policy, or permission. Show which memories materially influenced a plan when the user inspects its context.

## Phase 10: Ideate and Plan

Use existing brief persistence and task-graph/planning primitives where current code supports them. Goal flow: clarify intent, write/update the human-readable brief, select relevant Spatial/evidence/memory references, propose a capability-scoped plan, expose assumptions and unknowns, then allow editing/discussion. The plan can name capabilities only from the verified current catalog; it cannot introduce selectors, parameters, postconditions, or authority based on model text.

Every proposal binds exact brief bytes, evidence/reference digests, catalog generation, and plan graph digest. Any edit that changes executable content invalidates prior approval. Review shows the complete flattened plan and its effects before approval. MVP deliberately omits enterprise scheduling, dependencies across plugins, delegated workstreams, and agent teams.

## Phase 11: Teach connected to plans

Each plan step can be opened in Teach when a supported guidance recipe exists. Teach receives a step reference and context, then uses the existing human-operated overlay path. It does not click, type, or acquire Act authority. Completion is recorded only from the recipe’s verified observation or explicit user confirmation policy; a guidance pointer or answer alone does not imply a completed outcome.

Teach outcome can update the brief and create a memory candidate. Procedural memory is durable only after the workflow result is verified and the extraction rule identifies reusable user-specific procedure; application-wide procedure becomes a candidate Skill only in MP6 with review/signing.

## Interfaces

- `PersonalMemoryCandidate`: proposed type/value, source refs, confidence, sensitivity result, expiry proposal, and promotion status.
- `PersonalMemory`: durable user-owned value with provenance, scope, freshness, correction/supersession, and deletion status.
- `GoalBrief`: exact readable bytes plus digest and referenced `SpatialContextReference`, `EvidenceGraph`, and `ResearchTrace` digests.
- `PlanProposal`: complete versioned graph plus catalog/provenance binding; no approval field that can be forged by model output.
- `TeachStepReference`: plan/step identity only; Teach resolves through existing signed declarative catalog.

## Continuous tests and exit gates

- Golden memory candidates: explicit preference, one-session instruction, contradicted inference, stale fact, sensitive string, hostile page instruction, abandoned plan, verified procedure, correction, expiration, and deletion.
- Mutations prove weak-confidence promotion, source-link removal, hidden capture, failure to erase, provider payload contamination, and old proposal reuse are detected.
- Plan replay covers revision, brief byte changes, evidence digest changes, capability catalog drift, unsupported step, approval invalidation, and unavailable Act state.
- Teach replay proves no input synthesis and correct step/recipe binding.
- Exit: a new user can complete a persistent goal discussion and editable plan; the Brain learns only eligible items and is controllable; Teach guides a selected plan step; no plan executes without MP0 activation.
