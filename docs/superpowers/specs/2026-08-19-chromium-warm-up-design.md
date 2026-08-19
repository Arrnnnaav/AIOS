# Chromium Warm-Up — Design

Date: 2026-08-19
Status: reviewed, pending implementation plan
Measurements: `2026-08-19-cold-electron-probe-findings.md` — every number below
comes from that document, not from estimation (D034)
Builds on: `2026-08-15-perception-tier-2-ocr-design.md`, which deliberately
excluded this and named it as its own milestone

---

## 1. Why — and the harm is sharper than first stated

The tier-2 design said a first walk returning window furniture but no document
content "reads as a successful observation", implying the bug is a mislabelled
observation. Tracing the code shows something more concrete.

`run.py:419` calls `service.request_tier2(i)` the moment grounding fails. On a
cold Chromium application grounding fails for the whole time the accessibility
tree is populating — measured at **~3.3 s to first content and ~5 s to a stable
tree** on VS Code. So a cold start escalates straight to OCR.

Two consequences, the second worse than the first:

1. **Wasted OCR.** Capture plus read costs 0.14–0.23 s and the tier-2 floor is
   1.0 s, so a 5 s ramp burns roughly four reads on a window that was about to
   answer for free.
2. **The user is shown a worse hint than the system could give.** OCR may
   *succeed* during the ramp and produce an amber `INFERRED` ring — a text match
   on pixels — when a cyan `FRESH` ring from a confirmed UIA control was three
   seconds away. The hint is not wrong, it is needlessly uncertain, and the ring
   colour is how the user calibrates trust (D006).

That is a direct violation of D003's cheapest-first tiering: reaching for the
expensive tier while the cheap one is still answering.

## 2. What the measurements rule out

**A readiness test on a single observation cannot work.** A snapshot threshold
is defeated by a case already measured in the tier-2 spike:

| | elements | meaning |
|---|---|---|
| cold VS Code, first read | 13–14, 0–1 content | **transient** — 94 content by ~5 s |
| Adobe Acrobat, permanently | 20 (17 anonymous Panes) | **terminal** — 0 of 16 tool labels, forever |

Same shape, opposite meaning, at any threshold.

**Comparing consecutive observations cannot work either.** The element count is
non-monotonic and unstable *in steady state*, not merely during startup —
reproduced across two VS Code runs, including drops long after the ramp
finished (288/83 → 231/64 at 13 s; 288/83 → 259/68 at 20 s). Chrome on a static
page showed zero drops over 64 samples, which locates the cause: **UI churn in
the application, not Chromium's accessibility tree.** A rule validated against a
quiet app would pass and then misfire against a busy one.

So neither "the count grew, we have converged" nor "the count stopped changing,
we are ready" is sound.

## 3. The design

**Do not detect readiness at all.** The system already has a perfect readiness
signal: *grounding succeeded*. What is missing is patience before escalating.

A **warm-up window** per target window:

- It opens at the first observation of a target.
- While it is open, **grounding failure does not request tier 2.** The loop
  keeps waiting, exactly as it does for any step it cannot yet ground.
- It closes permanently the first time grounding **succeeds** for that target —
  the tree is demonstrably usable and never needs the allowance again.
- It closes on expiry after `WARMUP_BUDGET_S`, after which grounding failure
  escalates to tier 2 as it does today.

This sidesteps the entire "what counts as content" question, reuses the
grounding-failure trigger tier 2 already uses, and is immune to the
non-monotonicity of §2 because it never compares two observations.

| Parameter | Value | Basis |
|---|---|---|
| `WARMUP_BUDGET_S` | **5.0 s** | Content first seen at 3.29 s, tree stable by ~5 s, across three cold VS Code starts |

### The cost, stated plainly

A genuinely UIA-blind application — the Acrobat case, which is tier 2's whole
reason for existing — now waits the full 5 s before OCR engages. Its first hint
arrives about five seconds later than it does today.

That is a real regression for the tier-2 target case, accepted because the
alternative is a readiness heuristic that §2 shows cannot be made sound. The
budget is a constructor parameter, and if the Acrobat delay proves worse in use
than the wasted-OCR problem it solves, lowering it is a one-line change with a
measurable trade-off in both directions.

**Not chosen:** ending warm-up early when the element count grows sharply (say
2×, which the ~10 % steady-state fluctuation could not fake). It would cut the
Acrobat delay, but it reintroduces exactly the consecutive-observation
comparison §2 rules out, for a saving the measurements do not yet justify.
Revisit if the 5 s delay is felt.

## 4. Staleness — a third case, and an honest note on its reach

A not-yet-ready observation is **not** treated as a confirmed-fresh walk (D023)
and **not** as staleness. It is a third case: walked, completed, not yet
meaningful. It does not feed the ladder.

The reasoning for keeping it separate rather than reusing D023: a cold ramp is a
legitimately-slow-but-not-stale event, and D023's successful-observation bucket
is the mechanism the whole display rests on. Adding a second class of event to
it makes "the ladder ages on real staleness" a weaker claim, for no gain.

**Where this matters less than it appears.** During warm-up on a tour's first
step there is no hint on screen, so DIMMED versus HIDDEN is unobservable — the
ladder governs the display of a hint that does not yet exist. The distinction
becomes real only if a target restarts mid-tour. This is specified for
correctness of the contract, not because a user would see the difference today,
and it is written that way rather than claiming a benefit it does not deliver.

## 5. Error handling

| Situation | Response |
|---|---|
| Target absent during warm-up | No observation; warm-up clock keeps running. An app that never appears is the existing absent-window case |
| Grounding succeeds during warm-up | Warm-up closes permanently for that target |
| Warm-up expires, grounding still failing | Tier 2 escalates exactly as today |
| Target genuinely has no UIA content (Acrobat) | Warm-up expires after 5 s, tier 2 engages, unchanged behaviour thereafter |
| Worker restarts mid-tour | Warm-up does NOT reopen — it is keyed to the target window, and the tree's readiness is a property of the application, not of our worker |

## 6. Testing

- A cold target that grounds at 3 s never requests tier 2.
- A target that never grounds requests tier 2 once the budget expires, and not
  before.
- Warm-up closes permanently on first successful grounding: a later step that
  fails to ground escalates immediately, with no second allowance.
- The non-monotonic element count cannot affect the decision — a fixture whose
  count rises and falls across the window changes nothing, because no comparison
  is made.
- Per D018, mutation-verify: removing the warm-up suppression must fail the
  first test; making warm-up permanent must fail the second.
- Per D026, the sequence is asserted on an injected clock, not end state.

## 7. Out of scope

Icon-only controls (tier 3). Any change to tier 2's cadence, caps or floor. The
slow-walk observation from probe 1 — 7.30 s and 6.46 s against a warm app — is
recorded in the probe findings as a watch item; a clean run showed a 0.413 s
median and zero walks over 5 s, so it is not treated here as a defect.

## 8. What the measurements do not establish

- One application was measured cold. Slack, Discord and Teams were unavailable
  and may ramp differently; the 5 s budget is fitted to VS Code.
- Chrome's steady-state result came from an already-loaded page with a cold
  accessibility tree, not a cold application start, so it speaks to fluctuation
  and not to ramp duration.
- A dynamic web application in Chromium was not measured for fluctuation and
  would plausibly behave like VS Code rather than like a static page.
