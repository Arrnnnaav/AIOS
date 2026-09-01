# Interaction Runtime Architecture Review

This review reconciles the six planning documents supplied on 2026-09-01 with
the production GhostCursor runtime.  The documents are a useful north star,
but they mix shipped behavior, near-term work, and long-term platform ideas.
They are therefore design inputs, not executable authority.

## File-by-file assessment

### `ghostcursor_final_architecture.md`

This is the most complete product thesis.  Its strongest decisions are the
stable application-independent core, explicit capability modules, separate
application plugins and experts, deterministic authorization/verification,
and interaction modes that describe the human/AI relationship.

It also contains the largest amount of future scope.  Persistent
`WorkflowSession`, an event bus for every module, memory, artifact intelligence,
critics, multiplayer, company knowledge, cross-application workflows, dynamic
interfaces, sync, and autonomous execution do not exist merely because the
diagram names them.  In particular, the current signed plugin format is
data-only and the current executor guides a human; `execute()` and `rollback()`
are future plugin/runtime contracts that require a separate security decision.

### `README (1).md`

This is a good map of the four documents and its classification rule is worth
keeping.  It is not a normative architecture specification.  It should point
to a capability-status matrix so a reader can distinguish current, next, and
long-term behavior.

### `01_final_architecture.md`

This is the best concise architecture overview.  The plugin/capability,
deterministic/LLM, and knowledge/provenance boundaries align with the current
runtime.  Its task graphs should remain DAGs in the present product, and its
Act, rollback, multiplayer, memory, sync, and cross-application sections are
roadmap contracts rather than current implementation descriptions.

### `02_modular_ideation_execution.md`

This document gives the clearest interaction-mode semantics.  Its key insight
is that Ideate must happen before execution and must not become an unrestricted
chat-to-mouse path.  Modes and authority are orthogonal: selecting Act cannot
grant a permission, and selecting Teach cannot weaken target or verification
requirements.  The manager uses Plan as a product operation even though the
document treats planning as a stage between Ideate and execution.

### `03_llm_model_strategy.md`

The durable content is the routing boundary: models handle ambiguity,
language, ideation, planning proposals, semantic fallback, and critique;
deterministic code owns capabilities, permissions, binding, workflow state,
verification, audit, and limits.  Named model rankings are evaluation inputs,
not architecture.  Providers and model versions change, so production routing
must depend on measured gates and replaceable interfaces rather than this
document's ordering.

### `04_github_repo_integration_map.md`

This is a research backlog, not a dependency list.  Its strongest instruction
is to reuse selectively and preserve GhostCursor's authority model.  Every
candidate still needs license, maintenance, security, Windows behavior, and
boundary-fit review before code is imported.  LangGraph, OpenAdapt, OPA, MCP,
Letta, Pipecat, and similar projects should remain references until a concrete
missing primitive justifies adopting one.

## Reconciled architecture

The current system already provides the reliable-guidance foundation:

- signed, data-only application plugins;
- one canonical intent authorization boundary and fresh bind-time authority;
- plugin-scoped DAG proposals validated before execution;
- exact HWND binding and revalidation;
- a compiled UIA/OCR/VLM perception ladder;
- user-performed Teach workflows with independent verification;
- immutable session snapshots, Pause/Stop, a safety rail, and a native manager;
- local, content-minimized history and diagnostics.

The next product layers should be added in this order:

1. **Interaction contract and panel.** Make mode choice explicit while keeping
   mode separate from authority.  This slice ships Teach and Plan and exposes
   future modes honestly.
2. **Ideate and Discuss.** Add a non-executing module that returns bounded,
   attributable options, questions, trade-offs, and candidate goals.  It must
   not mint an `AuthorizedIntent`, enumerate targets, or create overlays.
3. **Artifact intelligence and Critic.** Introduce read-only artifact adapters
   and typed evaluation results.  Application plugins describe the software;
   experts and critics assess the artifact against the goal.
4. **Assist.** Reuse authorized Teach workflows with a distinct, concise
   intervention policy.  Assist still leaves the user as operator.
5. **Act.** Start only after a separate reviewed security decision defines
   signed action schemas, permission levels, secret handling, input synthesis,
   rollback/recovery, per-action approval, and independent postconditions.
6. **Memory, telemetry, enterprise knowledge, and multiplayer.** Build these
   on provenance, minimization, explicit scopes, and the existing session
   event boundary.  Company documents remain knowledge until a human-approved
   workflow or skill grants authority.

Cross-plugin graphs, Autopilot, Watch, dynamic generated interfaces, cloud
sync, marketplaces, and commercial package composition remain later phases.

## Panel decision

The native manager now exposes one canonical mode selector:

| Mode | Current behavior |
|---|---|
| Teach | Starts the existing authorized, human-operated guided workflow. |
| Plan | Produces an inert plugin-scoped DAG, shows every flattened step, and requires a separate `Start plan` action. |
| Ideate | Visible preview; cannot plan, bind a target, create an overlay, or act. |
| Assist | Visible preview with the same fail-closed behavior. |
| Act | Visible preview; it describes the destination but grants no authority. |

The existing goal input, plan timeline, live guidance, visible verification,
Pause/Stop controls, plugin state, session details, and local-privacy statement
remain the useful parts of the earlier panel proposal.  Quick goals, free-form
console logs, feedback, settings, session summaries, and dynamic mode-specific
panels should be added only when backed by runtime state; the manager must not
invent them from presentation events.

## Non-negotiable boundary

An interaction mode is never an authority token.  A future Ideate result is a
proposal.  A future Act request must still cross signed capability lookup,
`authorize_intent()`, fresh `bind_workflow()`, deterministic permission and
safety policy, bounded execution, observation, and verification.  Until those
new boundaries are reviewed and tested, preview modes remain unable to start.
