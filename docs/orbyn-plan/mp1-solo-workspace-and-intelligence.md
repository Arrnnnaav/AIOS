# MP1 — Solo Orbyn Workspace and Cloud Intelligence

## Purpose and phase grouping

Build the product shell and dependable model service boundary for the solo-user MVP. Detailed phases:

- **Phase 3 — Goal-centric workspace and session model**
- **Phase 4 — Provider gateway and System Two**

## Phase 3: one goal workspace

Use the current desktop manager and compact/expanded panel behavior as the initial shell only after the current roadmap’s Act activation dependency is satisfied. Before then, limit forward implementation to standalone Spatial, read-only evaluation, and offline design/documentation that does not wire manager Ideate/Plan, Spatial Context into a manager brief, research answer flow, or semantic execution. The workspace is organized around a current goal, with conversation, Spatial references, sources, relevant memories, editable plan steps, Teach/Act availability, and current progress. Do not create independent primary tabs for every subsystem.

The session is resumable and user-readable. It references persistent `Brief` bytes and versioned Spatial/evidence/memory identities; it does not turn chat or session state into execution authority. Compact mode shows current step/outcome and controls; expanded mode supports discussion, source inspection, memory review, and plan editing. Pause/Stop remain reachable during execution.

## Phase 4: provider gateway and System Two

Define one replaceable provider boundary for research, answers, ideation, planning, and payload generation. **Under D147 a configured cloud provider is the trial-period default**: NVIDIA NIM is the owner's chosen default, with OpenAI-compatible APIs, OpenAI, Anthropic, Bedrock, OpenRouter, and local Ollama as replaceable implementations behind the same gateway. Jev is a separate System-One contract and is not free-form answer generation. Local execution must stay supported and tested so the default can move back by configuration; a path that only works with a cloud key is a defect. Side-effecting network connectors are **not** covered by D147 and remain gated under D141/D144 with scoped tokens, vault, audit, and revocation. D147's independent D032 review is outstanding, so no phase closes on it.

The gateway owns provider configuration, credentials, timeouts, cancellation, rate/cost limits, privacy-policy enforcement, redaction, normalized errors, request metadata, and fallback. API keys remain server-side or in OS-secure storage, never in extension scripts or committed configuration. Local extraction/OCR/geometry/privacy filtering remain local. Every outbound request exposes a user-visible provider/data summary.

Fallback is task-specific and explicit: model failure returns a deterministic extraction/quote or asks the user; search failure allows a page-local answer labeled as such; Jev failure uses deterministic ranking and clarification; image denial does not silently retry with an image.

## Interfaces

- `SystemTwoProvider.answer/plan/generate`: task-specific input and structured output; all output validated before use.
- `ProviderGateway.request`: privacy-filtered request with request ID, provider/model identity, timeout/cancellation, usage/cost, and error class.
- All model prompts consume trust-labeled, bounded input envelopes; Spatial/research implementation and its adversarial gate are defined in MP2.

## Continuous tests and exit gates

- Offline provider contract fixtures; provider timeout, malformed response, auth failure, rate limit, partial-stream, cancellation, and fallback replay.
- Provider-boundary mutation tests: dropped privacy filter, direct gateway bypass, misreported fallback, or provider key leakage.
- Keep external NIM/Jev smoke tests in their own provider-live lane under D025, separate from hermetic tests (which must pass with no key); retain model/provider version, sanitized context digest, latency, and result-quality evidence.
- Phase 4 exit: all model calls use the provider gateway; provider failure preserves useful, accurately labelled degraded behavior.
