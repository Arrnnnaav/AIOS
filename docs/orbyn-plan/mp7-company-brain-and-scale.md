# MP7 — Company Brain, Collaboration, and Scaled Automation

## Purpose and phase grouping

Extend solo-user value to teams and organizations only after Personal Brain, EvidenceGraph, ResearchTrace, signed Skills, connectors, and authority boundaries are proven. Detailed phase 21 groups:

- **Phase 21 — Company Brain, collaboration, evaluation platform, and restricted visual automation** (the software/API wedge moved to MP8)

This is intentionally a broad Mega Phase with separately gated subprojects; it is not one release train. Its components can ship independently and must not be reported as one all-or-nothing “Company Brain” milestone.

### 21A. Company Brain and organizational Context Graph

Company Brain is not a dump of private documents into a vector store. Every durable organizational fact/edge needs source, owner, scope/tenant, provenance, review status, validity period, last-verified time, dependencies, sensitivity, and staleness behavior. Knowledge states distinguish raw/untrusted source, extracted candidate, reviewed fact, and approved reusable procedure. Organization owners govern promotion and removal.

Keep Personal Brain owner-scoped and private by default. Sharing a personal memory requires an explicit reviewed operation and a new organization-scoped record with provenance; never silently copy personal data into Company Brain. Tenant isolation is enforced at storage/query/provider boundaries.

Ingestion sources may include approved documents, code, APIs, support records, and verified execution evidence. Each connector declares scope and retention. Extraction produces candidates; it cannot publish a fact or Skill. Owners review high-impact knowledge, and facts with validity dates or dependencies are rechecked when their source changes. Graph retrieval returns the relevant provenance and conflicts, not an unattributed “answer.”

### 21B. Collaboration and multi-agent work

Add shared Workflows/Missions, handoffs, owner/resource claims, conflict detection, and activity history after single-user resume/recovery is reliable. Agent workstreams exchange typed, digest-bound task outputs rather than hidden conversation history. A coordinator may distribute and reconcile work but cannot authorize execution. Human approval, signed capabilities, per-node checks, verification, and resource locks remain authoritative.

Add role-based access controls only with a concrete team workflow and threat model. Specify who can read context, edit plans, approve effects, install Skills, manage keys, and release/revoke bundles. Test tenant and role isolation before enabling collaborative sessions.

Future coordination may add shared work queues, event routing, delegated experts, parallel workstreams, and durable collaboration history. Each is separately gated on idempotent handoff, resource conflict handling, interruption, and recovery. Voice, mobile clients, live cursors, CRDT editing, and dynamic interfaces are deferred until the core goal/plan/approval workflow shows repeat use; they must not be prerequisites for the solo product.

### 21C. OrbynBench and continuous evaluation platform

Build shared eval tooling after each subsystem already has fixtures. Consolidate target, decision, execution, and mission suites with replay, versioned datasets, negative/adversarial cases, provider comparison, model/version capture, quality dashboards, and regression CI. Keep the existing phase-level replay suites running throughout development; OrbynBench standardizes their runner, dataset identity, result format, and cross-product reporting.

Track target accuracy/correction/abstention; evidence support and citation validity; memory promotion/correction/expiry/deletion; plan revisions; Teach step completion; verified action outcomes; refusal quality; latency/cost; intervention; and repeat meaningful sessions. Report the distribution and failure classes, not only a top-line average. Separate hermetic results from live providers, interactive desktop, pixel, and hung-window runs.

Events-only telemetry remains off unless separately consented and D141 policy is satisfied. Evidence traces are user-controlled, minimized, redacted, retention-bounded, and never silently used as model-training data.

### 21D. Self-maintaining software — moved out of this phase

Moved to its own first-class track: [MP8](mp8-self-maintaining-software.md)
(D148). It was adopted as the first commercial wedge, and sequencing it behind
phases 8–20 meant it could produce no evidence for a very long time. It does
not depend on Company Brain, collaboration, or the marketplace and must not be
sequenced behind them.

### 21E. Restricted visual computer use

Only after structured APIs, signed app adapters, and browser capability are evaluated should Orbyn consider general screen-based interaction. Define the allowed platform, observation and coordinate freshness, prompt-injection isolation, user takeover, emergency stop, sensitive surface handling, and independent verification in a separate architecture amendment. Never make raw generic input synthesis the universal core or use an on-screen pointer as authorization. Teach and Act retain their existing distinct safety boundaries.

This phase is not an automatic consequence of marketplace or agent completion. It needs a separate threat model, user/product case, capability boundary, safety evaluation, refusal UX, and D032 architecture review. Keep sensitive surfaces and high-impact actions excluded until specific reviewed scopes exist.

## Continuous tests and exit gates

- Multi-tenant data isolation, cross-user memory retrieval, role escalation, stale/revoked signing keys, conflicting edits, resource-claim races, duplicate work, interrupted handoff, and data export/deletion.
- OrbynBench reproduces all phase-level fixtures and preserves each raw result, dataset/model/provider version, and exclusion reason.
- Visual automation remains disabled until its separate D032 architecture review and threat/evaluation results are READY.
- Company knowledge ingestion tests source provenance, conflicts, staleness, owner review, permission filtering, tenant isolation, and complete deletion/export.
- Collaboration tests duplicated work, lost/duplicated handoff, resource races, stale shared plans, owner changes, and interrupted coordination.
- Exit only by product slice: no all-at-once “Company Brain complete” claim. Each capability has its own owner, evidence, release gate, and review.
