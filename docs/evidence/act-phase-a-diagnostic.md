# Act v1 Phase A — PowerPoint diagnose-fix-rerun loop

**PRIMARY RECORD.** Every number below was measured here on 2 September 2026
and is not restated from any earlier document. Where a figure contradicts an
earlier claim, the contradiction is stated rather than quietly corrected.

Desktop: Windows 11, PowerPoint `16.0.20326.20112`, single POWERPNT process,
one matching window after the pack's title filter. No other test lane running
(D025).

## Run 1 — reproduction

Candidate bundle `48abc20087813420130e8ff909d626ef6f5495ead63392176ec7b192be025950`.
Plan `build-investor-deck-v1`, 255 nodes, plan digest
`84e39d0d2987e153923c537587380e9eeecccfae0a50ede5be586e0238e4fe79`.

| | |
|---|---|
| Result | `verification_failed` |
| Nodes verified | 24 |
| Failing node | `n025-slide-01-transition` (`powerpoint.set_transition`) |
| Elapsed to failure | 20.39 s |

Boundary classification from `ghostcursor.devtools.act_diagnosis`:

```
classifications: {"verified": 24, "written_and_verified_false": 1}
adapter_wrote_parts: ["docProps/core.xml", "ppt/slides/slide1.xml"]
verifier_seconds: 0.234
```

`written_and_verified_false` eliminated five competing explanations in one
pass: the save **did** change the expected part, two full reads of the package
agreed, it opened cleanly as an archive, and nothing rewrote it across
verification. That left the verifier's lookup or the content of what was
written.

Records: `.artifacts/powerpoint-act/diagnostics/phaseA-01.jsonl` (26 records,
ignored path).

## Root cause

The saved slide placed the transition at:

```
p:sld -> mc:AlternateContent -> mc:Choice -> p:transition
```

with an `mc:Fallback` sibling carrying the plain form. Measured element:

```xml
<p:transition spd="med" p14:dur="550"><p:fade/></p:transition>
```

The verifier used `root.find("{...presentationml...}transition")`, which
matches **direct children only**, so it saw `None`. A transition carrying the
`p14:dur` extension attribute must be wrapped this way, and every transition
in this plan declares a duration — so every one of them was invisible.

The adapter was correct throughout. Six defects had previously been found in
the adapter; this is the first found in the verifier, and it is the first
direct evidence that the separate signed verifier is load-bearing: an adapter
reporting its own success would have called this node a pass.

## Run 2 — after the fix

Candidate rebuilt and test-signed:
`8d458961a01e394176407785219de541f58ae2109a8f6e51a3fd5ee82c467578`.
Fresh store, fresh output, restarted from action 1.

| | |
|---|---|
| Result | `completed` |
| Nodes verified | **255 / 255** |
| Wall clock | 171.125 s |
| Verifier time, total | 63.529 s |
| Verifier time, max for one node | 0.328 s |
| Classifications | `{"verified": 255}` |

Produced artifact `deck-phaseA-02.pptx`, 94 392 bytes:

- 10 slides, named `slide-01` … `slide-10`
- 10 of 10 slides carry a transition
- 10 notes parts
- 21 animation elements across the deck

Records: `.artifacts/powerpoint-act/diagnostics/phaseA-02.jsonl` (256 records).

**Phase A's exit condition is met: one complete 255/255 diagnostic run.** It
does not count toward acceptance, and cannot: adding signed stages will change
the plan bytes and every digest above.

## A prediction of mine that was wrong

Reviewing revisions 3 and 4 of the completion plan, I argued that assuming
zero further defects across the 230 never-executed actions was as wrong as
assuming many, and that the schedule should read as a repeated loop. Actions
26–255 executed and verified clean on their first attempt. One defect existed
beyond node 25 and it was the one already visible at node 25.

The loop structure was still right for a different reason — the single defect
took a rebuild and a full restart — but the expectation of a long defect tail
was not supported.

## Two harness gaps the run exposed

**Approval lifetime is capped at 3600 s.** `approve_action_graph` refuses
anything larger. The first launch used 7200 and died before touching
PowerPoint. A 255-node run takes 171 s, so the cap is not close to binding;
the gap was in the instruction, not the code.

**A minimized approved window is filtered out.** PowerPoint minimized itself
between window resolution and launch. Its rect became `(-25600, -25600,
-25441, -25573)`, `is_on_screen` returned False, and `resolve_target` refused
with `no window matches pack powerpoint` while the process was alive and the
title correct. Restoring it with `ShowWindow(SW_RESTORE)` — a window-manager
call, not input synthesis, and not on the banned list — returned it to
`(-7, -7, 1543, 823)` and the run proceeded.

The completion plan's campaign runner already requires "restores a minimized
approved window without input synthesis". Nothing implements it yet, so this
is currently a manual step. Recorded in `docs/superpowers/FOLLOWUPS.md`.

## Open, not closed here

The transition postcondition remains **existence only**. The saved XML carries
the effect name (`<p:fade/>`) and the duration (`p14:dur="550"`), so it could
assert that the approved transition was applied rather than that some
transition is present — the D031 difference between an invariant that implies
a property and one that merely correlates with it.

It was not strengthened in this slice because `morph` is a later extension
whose element shape has not been measured on this build, and asserting an
unmeasured shape is what allowed `msoTrue` to pass a contract test while
failing in production. The animation-catalog campaign produces the sample
needed; until then the weaker check stands and is recorded as weaker.
