# Model-driven Teach — design

**Status:** design, not built. Decision: D159. Independent D032 review of this
document is required before the first implementation slice.

## 1. What it is

The user states a goal in any Windows application. Orbyn shows where to click,
one step at a time; the user clicks; Orbyn observes that the step happened and
moves on. No hand-written pack, recipe or selector is needed for the
application. A large model plans the steps; a fast System-One model (TypeSafe
Jev) chooses, for each step, one control from the controls the harness actually
observed on screen.

It is Teach, not Act. **Orbyn never clicks, types or moves the cursor** (D006
unchanged). The human performs every action.

Out of scope here: Act (model-driven execution), cross-application goals,
Skills/marketplace, screenshots sent to a model by default.

## 2. Why

Hand-curated packs did not scale: one application took weeks, and its only
accepted Teach recipe was invalidated by an Office update (D151). The plan
already describes the replacement -- `ObservationFrame`, a bounded System-One
choice, and a dual-speed executor (MP5, phases 15-17) -- but sequenced it last.
This design brings it forward for Teach only, where nothing executes and the
risk is a wrong pointer, not a wrong effect.

## 3. Flow

```text
goal (manager Ask / CLI --goal, no pack match)
  -> target window: user chooses (TARGET_CHOICE_REQUIRED path); never foreground (D075)
  -> perception worker publishes observations (UIA tier 1, OCR tier 2) as today (D021/D022)
  -> ObservationFrame: frame id, app identity/version, candidates c1..cn
       (name, control type, normalized role path, coarse region, tier/provenance)
  -> System Two (large model): goal + app identity + frame summary
       -> TeachPlan: ordered steps, each {instruction, expected_change}
  -> per step:
       System One (Jev): "which listed candidate does this step act on?"
         options = frame candidate ids + ABSTAIN
       deterministic gate: id in THIS frame, frame fresh, confidence >= floor,
         control enabled/visible -> else re-observe, re-ask, or ask the user
       overlay draws the ring on that candidate's observed rectangle
         (INFERRED colour: model-selected, never the confirmed-recipe colour)
       user acts
       verify: re-observe; expected_change checked by deterministic signals
         (element appeared/disappeared, focus moved, value changed) and, only
         when those are silent, a System-One judgment over the before/after
         frame digests; the user may also confirm "done"
       wrong action: existing focus-visited signal (D037) re-asserts the hint
  -> terminal: completed / stopped / failed-with-reason (SessionSnapshot)
```

The executor, rail, `SessionSnapshot`, Stop/Pause and session store are reused
unchanged. The new parts are the frame, the two model calls, and the gate.

## 4. The boundary that keeps it safe

- The model may choose **only a candidate id present in the current frame**,
  or abstain. It never emits coordinates, selectors, AutomationIds, keystrokes
  or tool names; the response schema is closed and validated deterministically.
- A frame's ids expire with the frame. A choice against an older frame is
  refused, not mapped.
- The pointer is drawn at the chosen candidate's **observed** rectangle,
  re-read from the frame -- never at a model-supplied position (D109 spirit:
  the pointer points at a real, observed control).
- No step completes on a model's say-so alone when a deterministic signal is
  available; "done" without an observed change requires the user to confirm.
- Screen text is **untrusted content** (MP2 phase 5): it is passed as quoted,
  typed data in its own field, never concatenated into instructions; length
  and character class are bounded; an instruction found in screen text is
  data. Adversarial cases (button labels that say "ignore previous
  instructions", "click OK to continue") are in the test corpus from slice 1.
- Model output is advice (D058): it selects among observed options for
  **guidance**; it never authorizes an Act effect. Act stays on the signed
  plugin path.

## 5. Providers

- **System Two:** pluggable gateway; trial default NVIDIA NIM (key exists on
  this machine for Spatial) or OpenRouter free models, under D147. A local
  Ollama model remains a supported configuration.
- **System One:** TypeSafe Jev (`TYPESAFE_API_KEY` in the git-ignored `.env`).
- Port Spatial's `system_one.py` (kept-alive client, hard time budget, one
  retry) and the OpenAI-compatible streaming path of `providers.py` into
  `ghostcursor/inference/`, with attribution; they know nothing about Spatial.
- No provider reachable: Teach says so and offers nothing. It never falls back
  to guessing a target.
- What leaves the machine: goal text, application name/version, candidate
  names/types/role paths/coarse regions. Never HWND, PID, executable paths,
  window titles containing file paths, or screenshots (a vision fallback is a
  later, separately consented option).

## 6. Accuracy is measured before it is claimed

1. A read-only capture tool records real frames and goals from PowerPoint,
   Excel, VS Code, Notepad and a browser, with the correct candidate per step
   labelled by the owner. Frames are scrubbed of handles before retention.
2. An offline replay harness scores deterministic baseline, System Two alone,
   and System Two + Jev on that corpus: top-1 target accuracy, abstention,
   wrong-but-confident rate, latency p50/p95, cost per step.
3. Recorded cassettes make the harness hermetic; live provider runs are a
   separate, explicitly named lane (D025).
4. User-facing release requires a recorded result on that corpus (D034) and an
   independent review. No accuracy number is quoted before it is measured.

## 7. Slices

1. Provider gateway + Jev transport, cassette-tested; closed response schemas.
2. `ObservationFrame` built from the existing perception publication.
3. Corpus capture tool (read-only) and offline replay harness.
4. Model-driven Teach executor behind `--model-teach`, reusing the compiled
   tour's rendering, verification, session and control plumbing.
5. Manager integration: a goal with no pack match offers model-driven Teach.
6. Later: verified runs drafted into reviewable Skills (MP6 phase 18).

Each slice: hermetic tests, D018 mutations on every boundary in section 4,
evidence for any number, independent review before the next.

## 8. Rules this changes (to be applied in the slice that implements them)

- CLAUDE.md "No enabled compatible plugin means no executable UI knowledge":
  amended for **Teach guidance only** -- a model may select an observed
  candidate in the current frame to draw a guidance pointer. Act, task graphs
  and capabilities are unchanged.
- D058: model output may choose among observed candidates for guidance; it
  still never selects what executes.
