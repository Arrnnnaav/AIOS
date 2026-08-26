# Tracked follow-ups

Small items deliberately deferred rather than forgotten. Each says what it is,
why it was not blocking, and what it would cost to leave.

## From perception tier 2 (merged 429a85e, 2026-08-19)

### 1. Merge-cap test counts words, not parts
`tests/test_ocr_reassembly.py::test_at_most_three_reads_merge_into_one_candidate`
asserts `len(read.text.split()) <= 3`, but `MERGE_MAX_PARTS` caps PARTS. The two
coincide only because that fixture uses single-word reads. A merge of three
multi-word reads would exceed three words and the test would not notice. The cap
itself is enforced in code and covered by the geometry tests, so this is a gap in
one assertion rather than in the behaviour. (Ruling P3.)

### 2. Vestigial parenthesised import in `run.py`
A single-name import wrapped in parentheses, left over from an earlier edit.
Cosmetic.

### 3. `_tier2_payload()` spends a run on a failed walk
Placement is correct — a raising UIA walk cannot suppress OCR — but publication is
gated on the walk having succeeded. So on a raising walk the OCR read happens, the
one-shot `grounded` flag is consumed and a fruitless run is spent from the budget,
and the result is discarded unpublished. Wasteful rather than wrong; the caps still
bound it. Documented accurately in FLOW.md.

### 4. Cancellation is a UI-thread convention, not worker-enforced
Absence of a `Tier2Request` means "not wanted", and the UI thread must cancel on
grounding success and at every step boundary. A future driver that forgets to
cancel reintroduces the defect where an abandoned step's request is serviced
forever (found and fixed as finding 1 of the threading review). The worker cannot
enforce it because it does not know the current step.

### 5. `test_persistence_e2e` allows rung 2 or 3 where FLOW says rung 2
FLOW.md states the second process grounds at rung 2; the test accepts rung 2 or 3.
One of the two should be tightened.

## Separate milestone, already scoped

### Chromium warm-up retry
Electron apps are blind-until-asked, not blind: Chromium enables its accessibility
tree on demand and the first UIA probe switches it on. A first walk returning window
furniture but no document content is NOT-YET-READY rather than empty, and currently
reads as a successful observation. Cheaper than OCR and fixes a real bug. Deliberately
excluded from tier 2 — see the tier-2 design doc section 1.

## Deferred infrastructure — revisit on a second occurrence

### Mechanical enforcement of D032 and D034
Both are currently rules that rely on being read. Real teeth would be a pre-commit
hook scanning documentation for figures with no cited source (D034), and the SDD
skill refusing to mark controller-authored work complete without an independent
read (D032).

Deliberately NOT built yet. One occurrence of a failure shape justifies writing the
rule down; it does not yet justify the build cost of automating enforcement. The
trigger for revisiting is a SECOND incident of this specific shape — evidence
laundering, a number entering the record with no durable source — as distinct from
ordinary documentation drift, which D032 already covers and which has occurred many
times. Do not count drift incidents toward this trigger; they are the other failure.

## Scoped, deliberately not started (2026-08-19)

Order fixed by the human partner. Each is a separate brainstorm, not a variation
on something built.

### 1. Wrong-action feedback — next after Chromium warm-up
The system verifies that the WORLD reached the expected state, never that the
USER did the expected thing. If the user clicks the wrong control and then the
right one, verification passes silently; on a wrong click today the loop simply
keeps dwelling and says nothing. Closing that needs no new perception tier —
before/after snapshots are already taken every tick — it needs the loop to
notice a change that is not the expected one and name it. Small, and it sharpens
the one thing this product exists to do.

Explicitly NOT the way to solve this: borrowing the perception half of a
computer-use agent (screenshot, ask a VLM "did that work"). That replaces a
structured UIA state-diff with a pixel guess, and D003 says reach for tier 3
last, not first.

### 2. Control bar and intent input — its own brainstorm
The only entry point today is `--target/--recipe/--seconds`. A user cannot say
what they want to learn. A visible bar with a stop button is also a SAFETY
improvement: ESC is currently the only escape from a full-screen click-through
overlay, and it is invisible.

Architecturally new territory, not a variation: the overlay is
`WS_EX_TRANSPARENT | WS_EX_NOACTIVATE` and must never take focus or receive
clicks (D006, D009), while a bar with a text box must do both. It has to be a
SECOND, focusable window coexisting with the click-through one. Nothing in this
codebase does that yet.

### 3. Recipe packs — last, and one decision comes before design
Per-app packs of pre-distilled recipes, downloaded at install. Strongest product
story: it solves cold-start latency and is a sellable unit.

One correction to the objection raised against video sources: the critique was
that transcripts give narration, not click coordinates. But `schema.py` forbids
storing coordinates at all — `_FORBIDDEN_KEYS` rejects bbox/x/y/rect/point
recursively, because a persisted pixel is a lie the moment a window moves. What
a recipe stores is `claimed.name`, `name_synonyms`, `control_type` and step
ORDER, which is close to what narration actually provides. Video is a poor
source for the thing we never keep and a fair source for the thing we do.

DECIDE BEFORE DESIGNING, not during: the licensing posture of deriving shipped
pack content from scraped video transcripts. A tool that works around a
platform's terms is one risk profile for personal research and another when
bundled into a product. The safer shape is likely distilled text steps derived
from a transcript, never redistributing the transcript or video — but that is a
decision to make deliberately, not to inherit by default.

Also unowned: pack staleness. `verified_on` version-scoping exists in the KB
schema, but a shipped offline pack needs its own refresh story.

## Unmeasured risks with named triggers

Risks accepted deliberately, with the evidence that would justify acting on
them stated up front. A risk recorded only in a spec's prose is one that
evaporates the moment implementation starts; these live here so they stay
findable. Do not act on the theoretical existence of the gap — each entry names
what evidence fires it.

### `GetFocusedElement` against a non-pumping window
From `2026-08-20-wrong-action-feedback-design.md` §9. Focus reads cost a 2.66 ms
median on an idle machine, but were **never tested against a "Not Responding"
window**. D025's hung-window tax — 6.28 s versus 100.13 s for the same two files
— applies to UIA calls generally, and whether focus reads pay it is unknown.

Worst case is contained by placement rather than by measurement: the read is on
the perception worker, never the UI thread, so a block degrades perception
exactly as a slow walk already does. The UI thread keeps pumping and polling ESC
(D021), and the staleness ladder ages the hint. It cannot produce a frozen
overlay the user cannot dismiss. That containment argument is why shipping the
unmeasured risk is acceptable — it is not a claim the risk is small.

**Trigger:** unexplained perception stalls with wrong-action feedback enabled,
particularly on Chromium-heavy or OCR-blind applications. Then measure
`GetFocusedElement` against a deliberately hung window, reusing
`tests/hung_window.py`.

### Native UIA focus-change events
From `2026-08-20-wrong-action-feedback-design.md` §7. `AddFocusChangedEventListener`
would remove the focus sampling gap entirely. Not built.

**Corrected 2026-08-20, post-implementation review.** An earlier version of
this entry (and of spec §7) said the missed window was 50 ms — that number was
the SLICE interval, not the blind window it leaves open, and understated the
real gap by roughly an order of magnitude (a D034 case: a documented figure
the implementation did not support, cited as the basis for a deferral
decision). Focus is sampled only during the inter-walk wait; it is not
sampled during the walk itself (0.18–0.70 s measured) or during tier 2 when
standing (0.14–0.23 s measured). The real blind window is walk plus tier 2,
**0.18–0.93 s**, giving roughly **18–53% coverage** of wall time, not a 50 ms
gap "faster than a human performs two deliberate clicks" — a wrong-then-right
round trip completing inside that window is ordinary human click speed.

Polling is kept anyway: the cost of native events is still real (COM
callbacks on RPC-managed threads marshalled into the worker's apartment, the
area D021 warns gives confusing intermittent failures rather than clean
errors), and this project has already paid once to avoid that area. But the
reason for keeping polling now has to be stated as "avoid a real
COM-marshalling risk", not "the gap is small".

**Trigger:** any report of a wrong action going unremarked — not "evidence
that real use is missing wrong actions" as this entry previously said, which
reads as a materially higher bar than a sub-second gap warrants. NOT the
theoretical existence of the gap, which is already known, measured, and
accepted.

### `focus_visited`'s cap keeps the earliest ids, not the latest
From `ghostcursor/perception/service.py`: `visited.append(focused)` is guarded
by `len(visited) < MAX_FOCUS_VISITED` (8), so once the cap is hit, later
distinct ids are silently dropped rather than evicting an earlier one — the
list keeps the EARLIEST ids seen, not the most recent. Combined with the fact
that `visited` survives a failed walk and is cleared only at a successful
publish, a long walk-failure streak can accumulate 8 ids from several seconds
ago, hit the cap, and publish those while the id the user just touched is the
one silently dropped.

Accepted rather than fixed here because at the shipped defaults
(`interval_s=0.2`, `focus_slice_s=0.05`) the cap is a backstop, not the
primary bound — about 4-5 samples accumulate per normal wait, well under 8 —
so it only does real work during an already-degraded walk-failure streak, a
case this milestone does not otherwise try to make correct.

**Trigger:** any report of a wrong action naming a control the user touched
some time ago rather than the one they just touched. Then check whether a
walk-failure streak was in progress, and consider evicting the oldest id
instead of refusing new ones once the cap is hit.

### Two real-desktop tests fail on a live machine
Discovered during the wrong-action feedback milestone, 2026-08-20, and verified
as PRE-EXISTING rather than assumed: it fails identically on `main`
(`1 failed, 7 passed`) and on the feature branch, and `appinfo.py` is byte-identical
between them. The test enumerates live Store-app windows, so it depends on what
happens to be running on the machine.

Verified by checking out `main` and running it there, not by inspection. This
project's CLAUDE.md records that timing-marginal failures have twice been
misreported here as pre-existing flakes when they were not, so "unrelated" is a
claim that has to be measured.

A SECOND one was found the same way during the wrong-action milestone:
`test_guided_tour.py::test_tour_grounds_renders_and_verifies_against_a_real_window`
also fails identically on `main` and on the feature branch. Both were verified
by checking out `main` and running them there — not by `git stash`, which only
tests uncommitted work and would have said nothing about a branch's committed
history.

So the real-desktop count is **two failures, not one**, and the fast suite's
"all passed" figure quoted anywhere in these docs is a figure measured with
both excluded.

**Trigger:** any work that touches `ghostcursor/perception/appinfo.py` or the
guided-tour pixel path, or the
next time the fast suite's pass count is quoted as authoritative — the suite is
not currently green on a real desktop, and a documented count that silently
excludes a failure is the kind of number D034 exists to stop.

### `ANY_MEANINGFUL_CHANGE` requires a `scope` that `verify()` never reads
Found while narrowing the empty-required-arg check (2026-08-21). `schema.py`'s
`_REQUIRED_ARGS` demands `scope` for this rule, but `verification.py`'s
`ANY_MEANINGFUL_CHANGE` arm ignores it entirely and compares whole-snapshot
element identity. So a recipe author must supply a field that does nothing, and
`{}` is the only honest thing to put in it.

That is why `scope` had to be exempted from the emptiness check: an empty value
there is legitimate precisely BECAUSE nothing reads it. The exemption is
correct, but it exists to accommodate a required argument that has no effect —
which is the actual defect.

Not fixed at the time because narrowing a validation check is not the place to
change what a verification rule accepts, and no shipped recipe uses the rule.

**Trigger:** the first recipe that needs `ANY_MEANINGFUL_CHANGE`, or any work
that touches `_REQUIRED_ARGS`. Decide then whether `scope` should be dropped
from the schema or actually honoured by `verify()` — today it is neither.

## From Spike B (2026-08-26)

### OPEN_FOLDER's UIA tier yields nothing on VS Code 1.134.0

`iter_vscode_elements()` returns 0 elements against the live Welcome page, 8/8
repeats. The workflow still completes: an empty successful observation lets
executable-bounded OCR escalate, which is the documented design. But the
cheapest and most-trusted perception tier contributes nothing, and OCR is
carrying a workflow that is documented as UIA-grounded.

The same target reads cleanly under strategy 2, 5/5, at a stable bbox
`(107, 450, 257, 488)`, under the accessible name `' Open Folder...'` — a
Codicon private-use glyph prefixed to the label. The recipe asks for
`'Open Folder...'`.

Most likely cause is therefore a name mismatch, which under D069's central
finding produces exactly the observed dead pointer. **Unverified**: confirming
it means querying the glyph-prefixed name and checking that a property read
succeeds, and VS Code was closed before that test could run. An earlier test
that appeared to confirm all three name variants "HIT" used non-`None` as the
predicate and is meaningless.

Not fixed here because Spike B's remit was feasibility, not repair, and because
the fix differs depending on the answer: name normalisation if the mismatch
hypothesis holds, a strategy change if it does not.

**Trigger:** before the Open Folder migration to the declarative compiler. That
gate must assert the hint was UIA-grounded rather than merely that the workflow
completed — otherwise it passes on OCR and proves nothing about the compiler's
strategy-1 path. Settle the hypothesis first; it is a sixty-second measurement
with VS Code open.

**Wider lesson worth keeping:** a degradation of this shape passes acceptance
silently, because the end-to-end outcome still succeeds on a fallback tier.
Acceptance gates that assert only the outcome cannot see a tier going dark.


### Repeated fast provider faults do not trigger the stalled-worker policy

Once `provider_exact()` raises `ProviderQueryFault`, a failed iteration is
diagnostic: it reaches `PerceptionService.progress().last_error` and publishes no
observation, so nothing false is rendered. But a failed iteration still updates
`last_completed_at`, so a *fast* fault repeating every tick keeps the heartbeat
healthy and never trips the stalled-worker policy. The tour therefore continues
indefinitely against a perception tier that is producing nothing.

That is strictly better than today, where the same condition is published as an
empty *successful* observation and is invisible. It is not a complete fix: the
fault is observable but does not end anything.

Not addressed in the presence-helper slice because bounding it is a policy
question — how many consecutive faults on the same step should end a step or a
tour — and that belongs with the existing tier-2 exhaustion ceiling, not inside
a provider query.

**Trigger:** the first workflow that depends on a provider query it can lose, or
any work touching the stalled-worker policy or the tier-2 fruitless-run ceiling.
Decide then whether consecutive faults get their own ceiling.


### Open Folder grounds at rung 3, not rung 2, because of the Codicon prefix

The walker publishes the raw accessible name `' Open Folder...'`, which is
correct — a cleaned-up name would make the observation disagree with the screen.
But rung 2 is byte-exact name equality, so the glyph makes it miss, and
grounding lands on rung 3, the case-insensitive substring rung. Measured live:
`rung 3 substring, source='uia'`, 5/5.

Accepted for now rather than widening the global grounding ladder in that slice,
because the risk is bounded on three independent counts: the element is
UIA-sourced, the walker has already reduced the candidate set to exactly one
trusted target (`EXACTLY_ONE`), and the only difference between observed and
claimed name is the measured leading Codicon.

Normalising inside the ladder would change matching for every application and
every rung, which deserves its own design rather than being folded into a
walker fix.

**Trigger:** the declarative compiler. It can carry both the raw and the
normalised name on a selector, which restores exact-rung semantics without
losing observation fidelity — a better fix than widening rung 2 globally.
