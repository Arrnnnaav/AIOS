# MP5 — System One and Bounded Action Runtime

## Purpose and phase grouping

Generalize bounded semantic decisions and fresh, typed action spaces beyond Spatial. Detailed phases:

- **Phase 15 — System-One provider boundary and Jev**
- **Phase 16 — ObservationFrame and Dynamic Typed Action Space**
- **Phase 17 — Dual-speed executor and payload generation**

## Phase 15: System One

Jev is a horizontal System-One provider, not a browser plugin and not Orbyn authority. A `SystemOneProvider` accepts a bounded state plus typed questions/options and returns a validated choice/score/no-choice distribution. Start with standalone Spatial target selection and bounded task routing; expand to event/workstream/recovery routing only when fixed replay data shows benefit. Compare deterministic, Jev, and other provider implementations against the same corpus. Jev failure falls back to deterministic ranking or clarification; it never upgrades confidence by default. A hosted Jev provider is permitted under D147 through the provider gateway; keep offline cassettes so hermetic tests need no key, and keep deterministic/local options working so the default can move back by configuration.

The `jev-ultrafast` contribution to borrow is a runtime-generated indexed action space, joint operation/compatible-target choice, and fresh revalidation. Browser-specific internals remain reference architecture. Keep provider protocol swappable because Jev is new and latency varies by deployment/network.

## Phase 16: ObservationFrame and Dynamic Typed Action Space

Every decision uses one immutable `ObservationFrame`: frame ID/time, app/resource identity, observed objects, object provenance, state digest, allowed operation types, and operation-specific candidate sets. IDs are valid only within that frame. Model output must identify a listed option; deterministic code verifies type compatibility, membership, freshness, identity, focus/visibility, and policy before execution. A frame change invalidates its candidates and decisions.

Use adapters for each supported observation source (DOM/accessibility, UIA, object model, PDF/Spatial). Normalize only the shared object reference fields needed for candidate choice. Keep app-specific semantic details in signed plugin data. No model-produced selector, coordinate, arbitrary tool name, code, shell, or input event reaches execution.

## Phase 17: dual-speed executor and payload generation

Fast path: deterministic prefilter → bounded System One choice → canonical authorize/bind → execute → await effect → verify. Slow path: when goal ambiguity, unknown state, low confidence, or unexpected postcondition occurs, System Two explains/replans; runtime then creates a new frame and bounded options. System Two is not called for every routine action.

Separate action decision from free-form payload generation. System One may choose `EDIT_TEXT` and a listed title object; a specialized System-Two generator may propose the text content. Validate payload type/length/content policy, bind its digest to reviewed proposal, and never let generated payload alter the operation/target/permissions. This split is useful only for workloads where a separate payload is required.

Control outcomes include `ACT`, `WAIT`, `REOBSERVE`, `NEEDS_USER`, `BLOCKED`, and `DONE_CANDIDATE`. A `DONE_CANDIDATE` never marks the mission complete; only independent verification does.

## Interfaces and continuous verification

- `SystemOneProvider.decide(frame_digest, questions, options) -> DecisionDistribution` with listed IDs, calibrated probabilities/status, provider/version/latency, and explicit abstention.
- `ObservationFrame` and `OperationTargetSet` immutable, versioned, freshness-bound.
- `ActionChoice` references frame ID, one offered operation, and one operation-compatible listed target.
- `PayloadProposal` is separate, typed and digest-bound; it cannot widen action scope.

Replay invalid frame, duplicate/ambiguous options, operation-target mismatch, stale focus, changed resource digest, provider timeout, malformed probabilities, false high confidence, payload injection, and DONE-before-verification. Mutation tests remove target membership/freshness checks and must fail. Compare fast and slow path decisions with the same safety refusals. Gate expansion on demonstrated accuracy/latency/cost benefit, calibrated abstention, and independent D032 review.
