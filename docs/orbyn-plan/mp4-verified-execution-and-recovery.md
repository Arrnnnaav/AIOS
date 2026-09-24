# MP4 — Verified App Execution and Recovery

## Purpose and phase grouping

Turn a reviewed plan into reliable, observable work inside supported signed applications. Detailed phases:

- **Phase 12 — PowerPoint semantic workflow**
- **Phase 13 — Resume, recovery, and reapproval**
- **Phase 14 — EffectAwaiter and ActionEvidence**

## Phase 12: PowerPoint and first-party app workflows

Begin with the PowerPoint wedge already present in the repo. Separate content understanding/generation from application execution. System Two may draft slide outline/text; a user reviews it. The signed PowerPoint adapter performs only declared object-model or accepted UIA operations. Live slide selection, visual state, and artifact postconditions are independently observed.

Each workflow declares preconditions, postconditions, side-effect class, safe-to-repeat status, and verifier kind in signed plugin data. Capability IDs and exact phrases remain plugin-scoped. Do not add PowerPoint-specific branches to generic core validation/execution. Later Excel and VS Code workflows require their own signed data, review, and acceptance evidence.

## Phase 13: interruptions and recovery

Pause/Stop remain responsive throughout presentation, dwell, confirmation, pacing, dispatch, and verification. On interruption, record exactly which nodes started, which effects may have landed, which verifier observations exist, and which suffix remains. Never silently continue a stale suffix or mint a new authorization from old observation data.

Resume is a new proposal epoch. Re-observe the application, compare the live state with durable execution evidence, ask the user where the world diverged, create an edited plan, invalidate the previous approval, and require fresh review/approval. If an effect may have happened, verify before retry. No blind mutation retry.

Partial output artifacts must be staged/labelled so a stopped or failed run cannot be mistaken for a finished deck. Publication is a deliberate commit step after verification. Preserve diagnostic and excluded attempts with their reason; acceptance renderer must not silently choose only successful attempts.

## Phase 14: state-aware waiting and evidence

Replace arbitrary fixed sleeps where a meaningful state signal exists with an `EffectAwaiter` that waits for app events, object-model changes, DOM/UIA state transitions, navigation, or declared postcondition, with bounded timeout, cancellation, and fresh-observation rules. Keep measured sliced waits where no event exists. A wait never grants authority or implies success.

`ActionEvidence` links action ID, proposal/approval digest, observation frame, target identity, payload digest, dispatch result, expected effect, post-state digest, verifier identity/result, timing, side-effect class, repeat-safety, and recovery. Evidence is audit/provenance, not a bearer token.

## Interfaces and gates

- `EffectAwaiter.await(effect_spec, fresh_observer, deadline, cancellation) -> observed transition or explicit timeout/cancel`.
- `ActionEvidence` immutable records with content-digest references; no raw secret payloads.
- `RecoveryProposal` references the interrupted proposal/evidence but needs fresh observations and new approval.
- Verify artifact and live state according to operation semantics; one verifier cannot answer a different trust claim.

## Continuous tests and exit criteria

- Injected-clock ordered sequences for stop/pause at every phase, delayed event, timeout, repeated state, state drift, and deadline race.
- Mutation tests remove fresh re-observation, turn uncertainty into success, retry a mutation blindly, accept old approval after edit, or publish a partial artifact.
- Replay realistic application sessions for success, refusal, partial effect, app close, minimize, window switch, verifier outage, and save/reload boundary.
- Interactive/pixel/hung-window lanes are serial under D025; retain exact bundle digest, app version, evidence, and excluded attempts.
- Exit: supported operations are re-bindable, interruptible, independently verifiable, recoverable through a new approval, and leave no ambiguous artifact labelled complete.

