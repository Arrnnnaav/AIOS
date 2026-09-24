# MP6 — Skills, Agents, Connectors, and Marketplace

## Purpose and phase grouping

Package repeatable work and third-party capabilities without creating a second authority system. Detailed phases:

- **Phase 18 — Verified Workflow Distillation**
- **Phase 19 — Skills, Experts, and generic agent runtime**
- **Phase 20 — Connectors, MCP, marketplace, and browser app**

## Phase 18: Verified Workflow Distillation

Use reviewed `ActionEvidence` and repeated verified runs to suggest stable workflow structure, parameters, preconditions, and postconditions. Suggestion is a draft only. The owner reviews procedure, data boundaries, permissions, version scope, expiry, failure handling, and verification before it can become a Skill. Do not infer a reusable workflow from one success, an interrupted run, or a run with incomplete evidence. Do not silently self-heal a changed target or workflow.

The result is a signed, versioned declarative Skill tied to a plugin/capability scope, with a deterministic path for known states and an explicit agent/Teach/escalation path for drift. Review licensing before reusing external workflow code; learn architectural patterns only where license permits.

## Phase 19: Skills, Experts, and agent runtime

- **Plugin**: app-specific signed executable/data contract and capabilities.
- **Connector**: scoped API/service access, credential reference, and audit policy.
- **Skill**: signed procedure, preconditions, allowed tools/capabilities, verification, and escalation.
- **Expert**: domain knowledge, evidence standards, and content quality criteria; no authority.
- **Agent**: signed data selecting reviewed Skills and capability IDs under requested scopes; generic core executor.
- **Executor**: deterministic orchestration through the existing approval and per-node authority path.

An agent may plan, choose among registered tools, ask the user, wait, or report blocked. Its data cannot load executable Python, add a capability, bypass permissions, call an unsigned connector, or self-approve. Multi-agent work begins with two bounded workstreams, typed handoff payloads, ownership, and single-user resource claims. Shared resource conflict and idempotency are evaluated before more concurrency.

## Phase 20: connectors, MCP, marketplace, and browser

Build one connector contract for MCP/API integrations with per-service scopes, least-privilege tokens in an OS-secure vault, domain/resource restrictions, audit, revocation, rate limits, and effect verification. MCP is a protocol/connector surface; it is not the internal authority core. Avoid exposing arbitrary browser CDP or shell methods to model/agent data.

Marketplace prerequisites: D144 key manifest, revocation checks, publisher identity, version provenance, compatibility, permission declaration, independent review record, deterministic install/upgrade/rollback, and re-sign trace. Marketplace agents/skills remain data validated by the generic runtime. Unreviewed third-party executable bundles are refused.

Browser capability begins with read-only structured DOM/accessibility extraction. Then add bounded operations through a signed browser adapter backed by Playwright/CDP. Use JEV-style indexed targets and Playwright accessibility snapshots as references. Browser operations have domain scopes; navigation, read, fill, submit, upload/download, account changes, and payment effects have distinct policies. High-impact submit/payment/account changes require explicit user approval. Page content is untrusted. Reobserve before mutation and never blindly retry.

## Continuous tests and exit criteria

- Signature, revocation, downgrade, wrong publisher, stale catalog, scope widening, connector credential leak, cross-plugin graph, and unsupported tool mutations.
- Workflow replay tests for deterministic success, drift, new UI, changed precondition, and unsafe retry.
- Browser injection corpus, domain-boundary tests, target freshness, form side-effect classes, duplicate submit, uncertain completion, and independent postcondition checks.
- Marketplace pilot uses allowlisted reviewed first-party packages before third-party publishing.
- Exit: a Skill and Agent can be installed, inspected, authorized, revoked, and replayed through one canonical runtime with source/evidence provenance and no policy bypass.

