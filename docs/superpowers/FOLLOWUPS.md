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

## Resolved scoped items from 2026-08-19

The former wrong-action, control-bar/goal-input, and recipe-pack entries are
implemented and no longer follow-ups. Wrong-action feedback is D037-backed;
the separate focusable Stop/Pause/Ask rail and `--goal` entry point are active;
and schema-v2 packs now use an explicit root index, digest-bound artifacts, and
reviewed adoption history. Their remaining measured risks are tracked below or
in the declarative compiler section, not preserved as stale "not started"
work.

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

### Resolved — OPEN_FOLDER's UIA tier yielded nothing on VS Code 1.134.0

The original spike measured `iter_vscode_elements()` returning 0 elements
against the live Welcome page, 8/8 repeats. The workflow still completed because
an empty successful observation let executable-bounded OCR escalate, so an
outcome-only acceptance gate did not expose the degradation.

The same target read cleanly under strategy 2, 5/5, at a stable bbox
`(107, 450, 257, 488)`, under the accessible name `' Open Folder...'` — a
Codicon private-use glyph prefixed to the label. The recipe asks for
`'Open Folder...'`.

The earlier name-mismatch hypothesis remains **unverified**. The repair did not
confirm it: Open Folder was instead migrated to `bounded_descendants()` with
normalised trusted-name matching and `EXACTLY_ONE` cardinality. Gate 1 then
passed 5/5, and gate 2 passed 3/3 with in-tour `source=uia` grounding and zero
OCR. The hypothesis is now moot, not confirmed; describing it as verified would
launder an inference into evidence.

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


### Compiled claimed-name grounding remains coupled to selector normalisation

The walker publishes the raw accessible name `' Open Folder...'`, which is
correct — a cleaned-up name would make the observation disagree with the screen.
But rung 2 is byte-exact name equality, so the glyph makes it miss, and
grounding lands on rung 3, the case-insensitive substring rung. Measured live:
`rung 3 substring, source='uia'`, 5/5, and pinned by the compiled grounding
regression.

Accepted for now rather than widening the global grounding ladder in that slice,
because the risk is bounded on three independent counts: the element is
UIA-sourced, the walker has already reduced the candidate set to exactly one
trusted target (`EXACTLY_ONE`), and the only difference between observed and
claimed name is the measured leading Codicon.

The Task 13 D079 repair makes the coupling explicit: the selector first reduces
the live controls to exactly one, then the existing grounding ladder must still
accept that same raw element against `claimed.name` or its synonyms. The ladder
cannot substitute another element, so failure is safe, but schema validation
does not currently prove that a selector-normalised match is also groundable.
A future normalisation that transforms rather than strips a prefix could
therefore produce a valid selector observation and an ungrounded step.

**Trigger:** before accepting a recipe whose normalised selector name is not
also exact, synonymous, or a measured substring of the raw accessible name, or
before adding another `normalise` mode. Make the relationship declarative and
load-time validated, or carry both raw and normalised names into grounding;
do not widen rung 2 globally or add workflow-specific Python.


## Declarative workflow compiler (Tasks 1-13 implemented; release merge gated)

Moved out of `CLAUDE.md` under D071: unresolved work is owned here, not by the
rules file.

**Approved artifacts — read these; do not redesign the milestone:**

- [Design spec](specs/2026-08-27-declarative-workflow-compiler-design.md)
- [Implementation plan](plans/2026-08-27-declarative-workflow-compiler.md)
- [Task 9/10 recertification evidence](../evidence/schema-v2-task9-recertification.md)

The design and plan passed independent D032 review through `af47bcf`. Task 10
was closed by owner direction after the full recertification reproduced on
`1ba371a` and was recorded in `41682ee`. Task 11's data-only Open Extensions
candidate is committed at `d26d2d8`; its 3/3 evidence and D032 approval are at
`9af7cb9`. Do not redesign or restart Tasks 1-12. Task 13's final regression,
documentation, and handoff are implemented; the durable result is
[`schema-v2-final-milestone.md`](../evidence/schema-v2-final-milestone.md).
The exact closing tree still requires D032 approval before its commit, and that
commit does not authorize a release or `main` merge.

### Recipe schema v2 and the declarative workflow compiler

Built around the two measured selector strategies, `provider_exact` and
`bounded_descendants`. Recipes declare strategy; the compiler never infers it.

**State/trigger:** compiler and all four workflows are active under schema v2;
the milestone implementation and final gates are complete. Release integration
remains owner-gated.

### Declarative intent registration

The legacy hardcoded planner dictionary and Python matcher are gone. The
installed v2 catalog and compiled matcher are the production registration
authority.

**State/trigger:** complete in plan Tasks 1-3 and activated by Task 9.

### Migrate the existing workflows, then add Open Extensions

Synthetic Export, Open Folder, Open Terminal, and Open Extensions are installed
and active under schema v2. Open Extensions was added through pack, intent,
recipe, evidence, and activation data with no workflow-specific change under
`ghostcursor/**/*.py`. The proof is the fixed diff from independently approved
compiler baseline `41682ee` through adopted Open Extensions `2736d1b`.

**State/trigger:** complete. Task 13 verified the complete
baseline-to-adoption proof. Any release merge remains a separate owner action.

### Acceptance budget

At least twelve successful human-driven real-desktop runs: 3/3 each for
Synthetic Export, Open Folder, Open Terminal, and Open Extensions. The first
nine are recorded in `docs/evidence/schema-v2-candidate-acceptance.md`; Open
Extensions' 3/3 is recorded in
`docs/evidence/open-extensions-candidate-acceptance.md`. All twelve ran against
the exact bytes and application identities ultimately adopted. Application
identity drift resets affected campaigns and may increase the total.

**State/trigger:** complete and audited by Task 13. Reopen only on artifact or
application-identity drift that requires reacceptance.

### Open Extensions action-visibility support boundary

Task 12 demonstrated Open Extensions on VS Code `1.135.0.0` with Extensions
pinned in the Activity Bar, no temporary restart badge in its accessible name,
and Explorer selected before each run. The schema has no declarative
precondition that expresses those UI-configuration facts, so the adoption
record binds the exact executable version and evidence digest while this entry
owns the narrower measured support boundary.

The two excluded configurations fail closed. When Extensions is unpinned, the
bounded TabItem walk exposes `Additional Views` but no Extensions control. When
a restart badge expands the accessible name, the exact provider query returns
no match. Neither state grounds a different action.

**Trigger:** reopen when a supported deployment needs hidden/unpinned Activity
Bar items or badge-bearing dynamic accessible names. Add a reviewed,
declarative way to express the prerequisite or stable selector property; do
not add one observed badge string as a synonym or workflow-specific Python.

### Unresolved — the original OPEN_FOLDER acceptance timeout

Three OPEN_FOLDER attempts failed before the Task 8 runs, each with the folder
title having already changed while the cursor stayed on Open Folder until the
20-second verification timeout. Nine runs later passed 3/3 with UIA-only
grounding, so the workflow works; **why the earlier attempts failed is still
not known.**

The first explanation offered — that the unbounded full-tree walk was too slow
— was measured and withdrawn: on live VS Code the full tree takes 0.093-0.110s
and a whole plan tick 0.063s, which cannot produce a 20-second timeout
(`docs/evidence/compiled-walk-latency.md`, D074).

Two differences between the failing and passing attempts were never controlled:
the passing runs pinned the window with `--target`, and the failing ones bound
whichever VS Code window the resolver picked. The failing session also recorded
no timings, so operator pacing — the confirmed cause of the one OPEN_TERMINAL
failure in Task 8 — cannot be ruled out or in.

**Containment now in place (D075).** Ambiguous target binding fails closed, so
the resolver can no longer choose a window silently. Every run record carries
its landmarks, so a recurrence arrives with the timeline that was missing.

**Update, same day.** The trigger below fired on its first live use: a smoke
run failed with `title_changed_s` present and earlier than `ended_s`. The cause
is recorded in the entry that follows this one. Whether it is also the cause of
the original three failures is still unproven — their symptom differed and no
record of them survives.

**Trigger.** Reopen if any compiled run times out with a `title_changed_s` mark
present and earlier than `ended_s`, or with `verification_started_s` absent
while the step rendered a hint. Either shape says the verification clock armed
on the wrong event rather than the operator being slow, which would be a real
defect and not pacing. Until then this is an accepted operational risk, not a
known bug.

### Resolved (D076) — a step's action can remove the step's own target

Reproduced live, 2026-08-28, with the D075 timing landmarks:
`docs/evidence/open-folder-target-disappearance.md`.

Opening a folder replaces VS Code's Welcome page, so `Open Folder...` stops
existing the moment the step succeeds. The grounding grace — 10s, meant for a
minimised window or an alt-tab **before** the action — then counts down against
a step whose goal has already been met, and reports `cannot find 'Open
Folder...' on screen` ten seconds after the title already changed.

Two runs, same setup: a 0.25s gap between action detection and title change
passed; a 0.5s gap failed. **A certified workflow's outcome currently depends
on a sub-second race.**

**Proposed direction.** Once a step's verification clock has armed
(`_verification_started_at` is set), stop counting grounding failure against
it: after the action, the verification rule is the authority on success, and a
vanished target is an expected consequence of many actions rather than evidence
of a lost window. The step stays bounded — by `timeout_s` where
`fail_after_timeout` is set, and by the run deadline otherwise.

Both alternatives were considered and are worse: evaluating verification from
`DECIDING` duplicates the rule in a second place, and re-checking verification
before declaring grounding failure leaves the same race, only narrower.

**This changes the shared `GuidedTour` loop, so it affects the certified v1
workflows too** and needs their regression runs, not only the compiled ones.

**Resolved by D076.** `_before` is now the verification baseline alone and
stops moving once an action is detected; `_observed` carries the latest
snapshot for grounding, interrupt detection and the newness gate. After the
clock arms, a grounding failure no longer counts against the step.

**Completed before Task 9:** Open Folder acceptance was re-run 3/3 after D076,
followed by the complete isolated regression lanes recorded in `bae0cee`.

### Open — identical window titles cannot be narrowed, so fail-closed can strand the user

Hit live during the post-D076 acceptance runs. Two Synthetic Export demo
windows were up and the resolver refused, correctly:

```
no acceptable target: 2 windows match pack synthetic; narrow to exactly one
with a more specific title pattern: 3607180 'Synthetic Export', 328996 'Synthetic Export'
```

Before D075 this would have bound whichever window was focused, silently. The
refusal is the right behaviour and listing the handles is what made it
actionable.

But **the two titles are byte-identical**, so the narrowing the message asks
for does not exist. `target_title_re` cannot separate them at any level of
specificity. For this shape the operator's only recourse is to close one
window.

That is the case D075 deferred: "prompting the operator to choose is a
reasonable future improvement". It is now a demonstrated gap rather than a
hypothetical one, because a user cannot always close the other window — two
projects open in the same editor is ordinary.

**Trigger.** Implement window selection by handle before shipping to anyone who
is not the author: either a `--target-hwnd` that takes a handle from the
refusal message verbatim, or the pick-a-window prompt. The refusal already
prints the handles, so the data is there.

**Not urgent for the milestone.** Every workflow in Task 8 was accepted with
one window per application, and the refusal is safe. This blocks a usable
product, not the compiler proof.
