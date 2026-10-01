# Model-driven Teach — design (revision 2)

**Status:** design, not built. Decision: D159; owner retired hand-written packs
in D161. Revision 2 answers the first independent review
(`review-spec-d159.md`, branch `review-spec-d159`, verdict NOT READY: B1-B6,
I1-I12, M1-M5). It needs a second review before slice 1 starts.

## 1. What it is

The user states a goal in a Windows application. Orbyn shows where to click,
one step at a time; the user clicks; Orbyn observes the step happen and moves
on. No hand-written pack, recipe or selector is needed. A large model (System
Two) plans the steps; a fast model (System One, TypeSafe Jev) chooses, per
step, one control from the controls the harness observed, or abstains.

It is Teach, not Act. **Orbyn never clicks, types or moves the cursor** (D006).
`authorize_intent()` and `bind_workflow()` refuse a model-Teach session, and a
model-Teach session can never be converted into an `AuthorizedIntent` or an
`AuthorizedActionIntent`.

Out of scope: Act, cross-application goals, Skills/marketplace, screenshots to
a model, OCR candidates as model choices (v1).

## 2. Target binding without a pack (review B6)

- The user chooses the window from a list of visible top-level windows that are
  not Orbyn's own, not elevated above Orbyn, and not on a denylist (password
  managers, credential prompts, the Windows security desktop).
- Binding records the exact HWND, PID, executable name and file version.
  Perception walks **only that HWND's subtree**; there is no title-regex scope.
- Every tick revalidates HWND, PID, executable and version. Any change ends the
  session (`TARGET_LOST`); there is no rediscovery and no foreground read (D075).
- The overlay is created only after binding passes.

## 3. The observation frame and candidates (review B1, I5)

- `ObservationFrame` = frame id, monotonic time, bound target identity, and a
  **candidate set**: UIA elements only (tier 1), drawn from a control-type
  allowlist (Button, MenuItem, TabItem, ListItem, TreeItem, CheckBox,
  RadioButton, ComboBox, Hyperlink, SplitButton, Edit-as-target-only), capped
  at a measured number of candidates per frame (initial cap 150, to be fitted
  on the corpus with recorded prefilter recall).
- `Element` gains: UIA runtime id, `is_enabled`, `is_offscreen`,
  `is_password`, and a bounded ancestor path. Perception keeps its worker
  thread and single-slot publication (D021/D022) and its walk-time budget; a
  hung target produces no frame, never a stall.
- Each candidate gets a frame-local id `c1..cn` for the model, mapped by the
  harness to its runtime id. The model never sees runtime ids, rectangles or
  automation ids.
- **Freshness is by identity, not by frame id.** Just before drawing, the
  chosen runtime id is re-resolved to exactly one element in the latest
  published observation (D069 exactly-one), still enabled and on screen, with
  its rectangle within a tolerance of the one the choice was made on. Any
  failure re-observes and re-asks; it never draws at an old rectangle.

## 4. Plan, choose, draw, verify

```text
goal -> bind target -> first frame
 -> System Two: TeachPlan (bounded steps; each = instruction + expected_change)
 -> per step:
      System One: choose one candidate id or ABSTAIN (closed schema)
      gate (deterministic):
        membership in the frame; exactly-one re-resolution (section 3);
        not ambiguous: no other candidate with the same normalised name+type;
        confidence >= floor AND top-1 minus top-2 >= margin (both fitted on a
          dev split and frozen before evaluation);
        not a high-risk target (delete, remove, send, pay, purchase, sign in,
          password, uninstall, format) -- those need the user's explicit
          confirmation before the pointer is drawn;
        tainted candidates (document or web-page content) held to a stricter
          floor, or excluded in v1
      -> pass: draw the pointer at the re-resolved observed rectangle
      -> fail: re-observe / re-ask (capped) / ask the user / BLOCKED
      user acts -> verify (section 5)
 -> replan when a step's outcome reveals a new surface (menu, dialog), capped
    (MP5 outcomes: ACT, WAIT, REOBSERVE, NEEDS_USER, BLOCKED, DONE_CANDIDATE)
```

Model calls never run on the tick thread (review I4). They use the tier-2
pattern: a single overwritten request slot, executed on a worker, result
published into a later observation; cancelled on step change, Stop, Pause and
ESC. A request in flight when Stop arrives is abandoned and its result
discarded (M3). The D020 0.5 s tick ceiling is covered by the existing
tick-latency test, extended to model-Teach sessions.

## 5. Verification (review B2)

`expected_change` is a **closed enum** whose arguments refer only to things the
harness already observed:

- `CHOSEN_DISAPPEARS` — the chosen candidate's runtime id is gone;
- `CHOSEN_STATE_CHANGES` — its toggle/selection/expand state changed;
- `FOCUS_MOVES_TO_CHOSEN` — keyboard focus is on its runtime id;
- `NEW_WINDOW_OF_TARGET` — a new top-level window of the bound PID appeared;
- `TITLE_CHANGES` — the bound window's title changed.

A change that cannot be attributed to the chosen candidate does not complete a
step: background churn (D037 measured about 10% idle churn in VS Code) is not
evidence. The model may return only `DONE_CANDIDATE`, which completes a step
**only with the user's confirmation**. Wrong-action feedback (D037) works only
where controls expose stable identity; it is silent for most Electron and web
controls, and the UI says so.

## 6. Provenance and memory (review B3)

A new closed provenance value, `MODEL_SELECTED`:
- always rendered INFERRED, never the confirmed colour, never recoloured by
  D112 (D109/D112 remain Act rules and are not amended here, M2);
- refused by `promote()` and by `ObservationStore.record()`: nothing a model
  selected reaches `kb.sqlite` (D070, D147: provider output is not memory);
- makes `grounded_by_uia_only` false, so D069's UIA-provenance gates cannot
  count it as UIA.

Each of these gets a D018 mutation test.

## 7. Untrusted content and what leaves the machine (review B4, I2, I3, I7)

- A typed envelope separates trusted fields (goal, policy, schema, task) from
  tainted fields (every string read from the screen). No API accepts a
  pre-joined prompt string; tainted values are quoted, length-bounded,
  control-character-stripped, and never placed in instruction fields.
- Strict parsing: closed schemas, duplicate keys and extra fields rejected;
  empty, truncated or invalid output means "unavailable", never a guess, and
  never a fallback to the model's reasoning text (the Spatial streaming path
  does that, so only its transport is ported, M1).
- Outbound: goal text, application name/version, and per candidate its
  frame-local id, control type, normalised name and coarse region. **Excluded:**
  runtime ids, AutomationIds, rectangles, ancestor paths, values of Edit and
  Document controls, anything under a password field, window titles, HWND,
  PID, executable paths, screenshots. The name/type pair is closer to a
  selector than D147 anticipated; this slice amends D147's outbound list
  explicitly to permit it for Teach guidance only, and its D032 review covers
  that amendment.
- D147's user-visible provider summary and a per-request local record
  (provider, model, time, sanitised-context digest; no content) are built
  before any request is sent. Free tiers that retain or train on prompts are
  disclosed in that summary, and can be disabled.
- Keys live in Windows Credential Manager (DPAPI-backed), not in `.env`; the
  `.env` copy is migrated and deleted (review I3).
- Instruction text shown to the user is model-written from untrusted content:
  bounded, sanitised, labelled "suggested", and it never asks the user to type
  a secret (I7).
- Cost caps per step and per session; a rate-limit or quota response becomes
  NEEDS_USER, never a guess (M5).

## 8. Executor composition (review I12)

The compiled tour's grounder reads recipe selectors, its verifier calls
`workflow.goal_reference_for`, and the run path hydrates and promotes from the
knowledge base. Model-Teach therefore gets its own composition --
`ModelTeachSession` supplying grounding (section 4), verification (section 5)
and provenance (section 6) -- while reusing the overlay, rail,
`SessionSnapshot`, `session_events`, Stop/Pause and the session store as they
are. There is still one runtime loop; no second event model.

## 9. Evaluation, pre-registered (review section 6)

- **Primary harm metric:** a wrong pointer shown. Reported per application and
  for high-risk targets, where the threshold is zero.
- Pre-registered before measuring: metrics, dev/test split, floor and margin
  (fitted on dev only), thresholds.
- Size: at least 300 pointer-shown test steps per claimed application, so a
  zero-failure result bounds the wrong-pointer rate below about 1% at 95%.
- Multiple acceptable labels per step; a second labeller on a sample; goals
  written by people other than the owner.
- Separate adversarial set (prompt injection in labels, look-alike controls);
  injection success threshold zero.
- Also measured: prefilter recall, abstention, false completion under
  background churn, stale-render rate, latency p50/p95, cost, behaviour with
  the provider down.
- Baseline (M4): a deterministic lexical matcher between step instruction and
  candidate name, on the same corpus.
- Lanes: hermetic replay with recorded cassettes; a separately named live
  provider lane; a separately named live end-to-end lane on the desktop
  (D025). The replay harness lives in `ghostcursor/evaluation/` and obeys its
  read-only rules (D063-D067); a model or prompt change re-runs it.
- Corpus capture (I10): the capture tool scrubs before the first write, keeps
  raw frames only under ignored `.artifacts/`, and the HWND/PID scan runs on
  every retained frame and cassette. Nothing captured is edited afterwards
  (D139).

## 10. Slices

1. **Provider gateway** (no UI): Credential-Manager keys, time budgets,
   cancellation, normalised errors, rate and cost limits, D147 attribution
   record; the typed untrusted envelope and outbound redaction; closed schemas
   (System-One choice with abstain; TeachPlan with the closed
   `expected_change` enum) and a strict parser with no reasoning fallback;
   the non-blocking request-slot API; cassettes, a keyless hermetic lane, a
   named live lane, local Ollama parity; D018 mutations on schema membership,
   the reasoning-fallback ban, redaction and timeout.
2. `ObservationFrame` and the `Element` fields (section 3), plus binding
   without a pack (section 2).
3. Corpus capture and offline replay evaluation (section 9).
4. `ModelTeachSession` behind `--model-teach` (sections 4-8).
5. Manager integration.
6. Later: verified runs drafted into reviewable Skills (MP6 phase 18).

Each slice: hermetic tests, D018 mutations on each boundary it introduces,
evidence for any number, independent review before the next.

**Sequencing (review I11).** CLAUDE.md permits only read-only evaluation and
design before Act activation. Slices 1-3 add no UI and no effect; starting them
before activation needs an explicit owner decision recorded in DECISIONS.
Slices 4-5 wait for that decision and their own reviews.

## 11. Rules to amend (each in the slice that needs it, with review)

1. CLAUDE.md "No enabled compatible plugin means no executable UI knowledge"
   and "a vision tier ... cannot guide an action without plugin authority":
   Teach guidance may come from a model selecting an observed candidate.
2. D091 / CLAUDE.md "with no enabled capability registry, do not contact the
   model ... no target or overlay": not for model-Teach.
3. CLAUDE.md "Executable targets are identity-bounded by the compiled
   workflow": replaced for model-Teach by the binding in section 2.
4. D058 / "Model output is advice": it may choose among observed candidates for
   guidance, never what executes.
5. The Teach contract in `ghostcursor.interaction` and D088's rail
   precondition.
6. D069's UIA-provenance wording: add `MODEL_SELECTED`.
7. D147's outbound list (section 7).

**Preserved, unamended:** D006 and the input-synthesis scan; D009/D010; D020;
D021/D022; D025; D026; D030 (no OCR promotion; no OCR model choices in v1);
D034; D037 with its limits stated; D069 presence and exactly-one at render;
D070 (no model output in `kb.sqlite`); D075; D109/D112 for Act; D128 and the
HWND/PID scan; D139; session-store content rules; ESC and `--seconds`.
