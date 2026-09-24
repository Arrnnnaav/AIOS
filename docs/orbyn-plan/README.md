# Orbyn Evolution Plan

> **Status:** Draft plan set, not an implementation approval or release record.
>
> **Canonical tracker:** this file.
>
> **MVP definition:** [MVP.md](MVP.md)

## Product evolution

```text
POINT → UNDERSTAND → RESEARCH → REMEMBER → DISCUSS → PLAN → TEACH
      → CHOOSE → AUTHORIZE → EXECUTE → VERIFY → LEARN → REUSE
      → COLLABORATE → AUTOMATE
```

This plan set turns the existing Orbyn/GhostCursor architecture, the JEV/System-One addendum, the Spatial project, and the owner’s product direction into reviewable Mega Phases. It is a forward plan, not evidence that any listed feature is implemented or accepted.

The MVP is one solo-user Orbyn workspace. Before Act activation, the permitted forward work is standalone Spatial, read-only evaluation, and planning/documentation that does not wire manager Ideate/Plan, semantic app workflows, or Act authority. The integrated Orbyn workspace and its downstream product stages remain gated by the current roadmap until Act activation is READY. The MVP launch includes Act only after its exact signing, campaign, and independent review gates pass. Until then, execution must be rejected by the runtime, not merely hidden in the UI.

## Source documents and authority

- `docs/orbyn-plan/source/` preserves the master plan, JEV/System-One addendum, and Unified Plan with their source provenance and recorded digests. They are background material for this decomposition, not current implementation status.
- `ROADMAP.md`, `FLOW.md`, `CLAUDE.md`, and `DECISIONS.md` remain the current repository authorities for actual status, call paths, mandatory rules, and recorded decisions. This plan must not silently amend them.
- `D017`, `D032`, `D034`, `D087`–`D090`, `D100`–`D148`, and later reviewed amendments govern where applicable. A plan statement is not a decision amendment.
- Spatial remains independently usable and testable. Orbyn consumes Spatial context through a reference contract and owns all authority, approvals, execution, and verification.

## Mega Phases

| ID | Mega Phase | Detailed phase range | Plan | Status at planning baseline |
|---|---|---:|---|---|
| MP0 | Trust foundation and Act release | 1–2 | [mp0-trust-and-act-release.md](mp0-trust-and-act-release.md) | Act release open; non-executing work may proceed |
| MP1 | Solo Orbyn workspace and cloud intelligence | 3–4 | [mp1-solo-workspace-and-intelligence.md](mp1-solo-workspace-and-intelligence.md) | Existing shell/planning parts; integrated MVP not complete |
| MP2 | Spatial, research, and evidence | 5–8 | [mp2-spatial-research-and-evidence.md](mp2-spatial-research-and-evidence.md) | Separate Spatial project is under development; standalone trust boundary and Orbyn integration require their own review |
| MP3 | Personal Brain, Ideate/Plan, and Teach | 9–11 | [mp3-personal-brain-plan-and-teach.md](mp3-personal-brain-plan-and-teach.md) | Some primitives exist; product flow not complete |
| MP4 | Verified app execution and recovery | 12–14 | [mp4-verified-execution-and-recovery.md](mp4-verified-execution-and-recovery.md) | PowerPoint Act slice exists; activation remains gated |
| MP5 | System One and bounded action runtime | 15–17 | [mp5-system-one-and-action-runtime.md](mp5-system-one-and-action-runtime.md) | Spatial Jev prototype exists; universal runtime contracts are future work |
| MP6 | Skills, agents, connectors, and marketplace | 18–20 | [mp6-skills-agents-and-marketplace.md](mp6-skills-agents-and-marketplace.md) | Design decisions exist; product platform not built |
| MP7 | Company Brain, collaboration, and scaled automation | 21 | [mp7-company-brain-and-scale.md](mp7-company-brain-and-scale.md) | Not started; broad future scope |
| MP8 | Self-maintaining software (commercial wedge) | 22 | [mp8-self-maintaining-software.md](mp8-self-maintaining-software.md) | Not started; restored to a first-class track by D148, parallel to the product loop |

Detailed phase IDs are stable references for status and dependency discussions. They are grouped for navigation; grouping does not imply that all phases in a Mega Phase are one implementation batch.

## Phase tracker

Update this table only from repository-backed evidence. Each phase remains **Planned** until its plan is reviewed, **In progress** only after a scoped implementation starts, and **Complete** only after implementation, required tests/evidence, reconciliation, and independent D032 review are recorded.

| Phase | Deliverable | Depends on | Status | Continuous evaluation/replay | D032 review / evidence |
|---:|---|---|---|---|---|
| 1 | Reconcile baseline; close Act signing, counted campaigns, and activation | Current release key custody and ROADMAP gates | In progress per current ROADMAP; re-confirm before execution | Baseline, refusal, signed-byte, and campaign replay | Open; see ROADMAP |
| 2 | Shared authority, privacy, identity, and evidence contracts | 1 baseline inventory; contract design may proceed, implementation only within current ROADMAP scope | Planned | Contract, property, privacy, and provenance mutations | Pending |
| 3 | Goal-centric Orbyn workspace and session | 1 activation READY; current ROADMAP stage gate | Planned | UI journey replay | Pending |
| 4 | Provider gateway and System Two | 2–3; cloud provider implementation permitted under D147; Orbyn manager integration still requires Phase 1 activation READY and its roadmap stage | Planned | Mocked provider contract and failure replay | Pending |
| 5 | Untrusted Observation Boundary | Standalone Spatial project may implement this before model-facing web/PDF/OCR content; any Orbyn model-path integration requires Phase 1 activation READY and its roadmap stage | Planned | Prompt-injection adversarial corpus | Pending |
| 6 | Spatial project evolution and later Orbyn Spatial Context integration | 5; standalone project at `D:\PROJECTS\Spatial`; Orbyn Brief integration only after Phase 1 activation READY under ROADMAP Stage 1 / D143 | Planned | Geometry/source replay; integration contract replay | Pending |
| 7 | EvidenceGraph and ResearchTrace | 5–6; standalone fixtures may precede activation; Orbyn shared production contracts require Phase 1 activation READY and the applicable roadmap stage | Planned | Claim/citation/provenance graph replay | Pending |
| 8 | Research workflow and source presentation | 4, 7; network research permitted under D147 behind the Phase 5 boundary; Orbyn manager/research integration requires Phase 1 activation READY and its roadmap stage | Planned | Search/source/claim replay | Pending |
| 9 | Personal Brain v1 | 2–4, 7–8 | Planned | Memory promotion, correction, expiry, deletion replay | Pending |
| 10 | Ideate/Plan persistence and revisions | 3, 8–9 | Planned | Brief/task-graph golden replay | Pending |
| 11 | Teach tied to plan steps | Existing Teach; 10 | Planned | Teach/session workflow replay | Pending |
| 12 | PowerPoint semantic workflow | 1, 10; signed plugin authority | Planned | Artifact/live-state scenario replay | Pending |
| 13 | Resume, recovery, and reapproval | 12 | Planned | Ordered interruption and partial-effect replay | Pending |
| 14 | EffectAwaiter and ActionEvidence | 12–13 | Planned | Event/state transition replay | Pending |
| 15 | System-One provider boundary and Jev | 2, 6–8; offline interface/replay first; hosted Jev permitted under D147 through the provider gateway | Planned | Deterministic/Jev comparison corpus | Pending |
| 16 | ObservationFrame and Dynamic Typed Action Space | 6, 15 | Planned | Stale-frame and invalid-pairing replay | Pending |
| 17 | Dual-speed executor and payload generation | 10, 14–16 | Planned | Fast/slow path equivalence replay | Pending |
| 18 | Verified Workflow Distillation | 14, 17 | Planned | Record/replay and drift corpus | Pending |
| 19 | Skills, Experts, generic agent runtime | 2, 17–18; D142 | Planned | Signed-data and permission mutation suite | Pending |
| 20 | Connectors, MCP, marketplace, browser app | 2, 5, 16, 19; D144 | Planned | Connector/provider and browser adversarial replay | Pending |
| 21 | Company Brain, collaboration, OrbynBench, restricted visual automation | 8–20 | Planned | Multi-user isolation and mission benchmark replay | Pending |
| 22 | Self-maintaining software wedge: impact mapping, isolated repair, evidence, approved draft PR | Provider gateway (4), isolated execution environment, scoped repo access. **Not** gated on Spatial, Brain, Act activation, or marketplace (D148) | Planned | Historical provider-change corpus; hostile changelog/secret-leak adversarial replay | Pending |

### Continuous quality rule

Every phase owns replayable fixtures and regression criteria from its first implementation slice. The OrbynBench phase builds a common runner, datasets, dashboards, and cross-phase reporting; it is not the start of testing or evaluation. Every safety-critical invariant gets a mutation test under D018. Every claimed measurement points to durable evidence under D034. Hermetic, provider-live, interactive, pixel, and hung-window results are reported separately under D025.

## Shared contracts

These are first-class cross-subsystem contracts and must be versioned, documented, and tested before dependent integrations:

- **`SpatialContextReference`** — user mark, resolved object reference, confidence, question, and digest-bound context. It informs discussion and planning; it carries no selector, permission, or action authority.
- **`EvidenceGraph`** — typed nodes for claims, sources, passages, Spatial references, and derived answers; typed edges for supports, partially supports, contradicts, cites, and derives-from. A claim has a support state (`SUPPORTED`, `PARTIALLY_SUPPORTED`, `CONTRADICTED`, or `UNRESOLVED`) and retains source metadata rather than an unexplained numeric credibility score.
- **`ResearchTrace`** — replayable provenance for the question, context digest, routing decisions, search queries, source/passage IDs, claim links, citations, providers/models, privacy state, timing, and failures. It stores no screenshot bytes or secrets by default.
- **`ObservationFrame`** — immutable, time-bounded observation with frame identity, app/resource identity, observed candidates, valid operations, operation-specific target sets, and freshness material. Candidate IDs expire with their frame.
- **`ActionEvidence`** — links the approved operation and target to its observation frame, dispatch, expected effect, observed state, verifier result, side-effect class, and recovery. It does not itself grant authority.
- **`PersonalMemory`** — user-owned memory with type, content, source/provenance, confidence, scope, creation/update/expiry, and correction/deletion state. The MVP persists locally in a sync-ready schema.

The detailed documents own the proposed fields and migration sequencing. A contract change requires versioning, compatibility notes, fixtures, and independent review; no consumer may infer authority from a context or evidence object.

## Global implementation and review gates

- Preserve the canonical plugin authority path: signed catalog, compatibility checks, `authorize_intent()`, fresh binding, per-node authorization, and independent verification.
- Models propose, classify, rank, or generate bounded content. Deterministic code owns candidate identity, privacy policy, permissions, freshness, authorization, dispatch boundaries, and verification.
- Treat DOM, accessibility labels, PDF, OCR, search results, and application content as untrusted data from the first standalone Spatial or research implementation; no Orbyn web/document model path may precede that boundary.
- No raw HWND/PID, credentials, selectors, executable paths, or unapproved screenshots leave the device. Provider selection and content sent are visible and policy-controlled.
- Personal Brain performs no per-memory confirmation in v1, as requested. It silently promotes only eligible, sufficiently supported memory candidates; ambiguous or temporary candidates remain session-scoped/expire. The user can inspect, correct, pause learning, export, and erase the Brain.
- **Cloud-first is now the adopted trial-period policy (D147 / D141-R2, owner-approved 24 September 2026; its independent D032 review is outstanding).** A configured cloud provider may be the default System-One/System-Two reasoning provider; cloud reasoning is no longer Stage 6-gated and needs no per-session consent step. Local execution stays a supported, tested configuration, so shifting the default back later is a configuration change — a path that only works with a cloud key is a defect. Unchanged: cloud reasoning is never execution authority; provider failure never enables a fallback execution path; no credentials, keys, raw HWND/PID, selectors, executable paths or verifier readings leave the device; images leave only under the configured privacy policy; provider responses are not durably promoted to memory; telemetry stays off by default. **Side-effecting connectors did not move** and keep their scoped-token, vault, audit, revocation and approval gates (D144).
- Spatial is a separate product/project at `D:\PROJECTS\Spatial`. Build, evaluate, and review it independently first. Do not copy it into this repository or wire its schema into manager briefs before Act activation returns READY; then integrate through the D143 `SpatialContextReference` contract in ROADMAP Stage 1. Spatial references remain context, never authority.
- Do not claim a phase complete without tests/replay, required evidence, documentation reconciliation, and independent D032 review.
