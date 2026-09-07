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

### Plugin signing-key rotation and revocation are deferred

Plugin v1 has one project-controlled signer and no third-party distribution.
The trusted-key map can name more than one public key, but no policy yet says
when an old key stops being trusted, how a compromised key is revoked, or how
an installed bundle is reported after revocation.

**Trigger:** before adding a second signer, marketplace, external plugin
author, network update channel, or customer deployment that requires key
rotation. Define signed revocation metadata and startup behavior through one
reviewed decision; do not scatter date/key checks across installer and runtime.

### Legacy observation quarantine has no retention policy

The plugin-store migration moves pre-plugin observation rows into
`legacy_observations` and never reads them as current authority. This is safe,
but the rows are retained indefinitely and have no inspection/export surface.

**Trigger:** before a storage-retention promise, privacy policy, support export,
or cleanup UI. Decide whether to export, age out, or explicitly retain these
rows; never infer a plugin id/version and silently promote them.

### Plugin installer, manager UI, and pilot packaging remain follow-on work

The v1 CLI and `PluginStore` own lifecycle semantics, but there is no polished
installer, tray/manager surface, or enterprise deployment package.

**Trigger:** after the signed Excel plugin is independently accepted and
activated. Every surface must call `PluginStore` and
`check_core_compatibility()` rather than implementing validation, conflict, or
state transitions itself.

### The Act campaign harness cannot restore a minimized approved window

PowerPoint minimized itself between window resolution and the Phase A launch,
putting its rect at `(-25600, -25600, -25441, -25573)`. `is_on_screen` returned
False and `resolve_target` refused with `no window matches pack powerpoint`
while the process was alive and the title correct. Restoring it manually with
`ShowWindow(SW_RESTORE)` let the run proceed and produced 255/255.

Observed twice: PowerPoint during Phase A and Excel during Phase B, in both
cases between window resolution and the next command. This is the
environment's normal behaviour, not a one-off.

**Trigger:** when the acceptance runner is built (Act v1 completion plan, the
runner section). It already specifies "restores a minimized approved window
without input synthesis"; nothing implements it, so every counted run
currently depends on a human noticing. `ShowWindow` is a window-manager call,
not input synthesis, and is not on the `test_no_input_synthesis` banned list.
Measured in `docs/evidence/act-phase-a-diagnostic.md`.

### The transition postcondition proves presence, not the approved effect

The verifier accepts any slide-level `p:transition`. The saved XML carries the
effect name (`<p:fade/>`) and duration (`p14:dur="550"`), so the check could
assert that the approved transition was applied instead — the D031 difference
between an invariant that implies a property and one that correlates with it.

**Trigger:** after the animation-catalog campaign produces a `morph` sample.
Morph is a later extension whose element shape has not been measured on build
16.0.20326, and asserting an unmeasured shape is what let `msoTrue` pass a
contract test while failing in production. Measure first, then tighten.

### GhostCursor runs system-aware while dpi.py intends per-monitor-v2 — CLOSED 7 Sep 2026

`_ensure_dpi_awareness()` calls `SetProcessDpiAwarenessContext(-4)` with a
plain Python int. ctypes marshals that as a 32-bit C int while the parameter
is a pointer-sized `DPI_AWARENESS_CONTEXT`, so the call fails and the process
falls through to `SetProcessDPIAware()` and runs SYSTEM aware.

Measured 2 September 2026, first call in a fresh process on the same machine:
`SetProcessDpiAwarenessContext(-4)` returns 0 with `GetLastError 87`
(ERROR_INVALID_PARAMETER); `SetProcessDpiAwarenessContext(c_void_p(-4))`
returns True and `GetThreadDpiAwarenessContext` then reports
`per-monitor-v2`. The module's own docstring previously attributed the
failure to the machine; that was wrong and has been corrected in place.

**Original trigger:** a reviewed decision with a scaled or mixed-DPI display available.
On one monitor at 100% the two modes are indistinguishable, so neither the
pixel lane nor any test on this desktop can validate the change -- which is
also why nothing caught it. Correcting it changes the coordinate space shared
by every window rect, UIA rect, hint and screen capture (D010), so it must not
ride along with unrelated work. `AWARENESS` is read nowhere outside
`ghostcursor/overlay/dpi.py`, so the blast radius is the coordinate space
itself, not the call sites.

**Closed by D116 after independent review changed the safety premise.** UIA
`BoundingRectangle` is always physical screen pixels. Remaining system-aware
was therefore not neutral: it allowed a physical UIA rectangle to be consumed
as system-DPI geometry. The setter now uses its pointer-sized ABI and production
must measure per-monitor-v2; adapter, host, and overlay all refuse non-physical
UIA geometry. Mixed-DPI live acceptance remains required, but the unsafe mode
is no longer kept as the production default while waiting for that machine.

### The accepted Excel ADD_WORKSHEET recipe assumes the new sheet is named Sheet2

`plugins/sources/excel/payload/ghostcursor/packs/excel/recipes/add_worksheet.json`
verifies with `element_appears` on a `TabItem` named exactly `Sheet2`. That
holds only for a workbook whose sheets are `Sheet1` alone. Add a worksheet to a
workbook that already has a `Sheet2`, or run a localized Excel, and the new tab
is named something else: the step is reported unsatisfied although the user did
exactly what was asked.

The Act v1 plan names this explicitly -- "record the actual generated name;
never assume Sheet2" -- and `docs/evidence/act-phase-b-uia-feasibility.md`
measured the separation needed to do it properly: worksheet tabs carry
AutomationId `SheetTab` while ribbon tabs carry `TabHome`/`TabInsert`, so the
postcondition can be "the SheetTab set grew by exactly one" instead of a
literal name.

This is Teach data, so the consequence is a false negative in guidance rather
than an unsafe action, and the three acceptance runs are still valid for the
workbook state they were measured on.

**Trigger:** when the Act UIA operation for Add Worksheet is authored. Its
postcondition must use the set difference, and the Teach recipe should be
migrated to the same rule in the same slice so the two do not disagree about
what "a worksheet was added" means. Changing the recipe changes signed plugin
bytes and needs fresh acceptance runs (D032, D070).

## A live-state verifier for `uia_pattern` operations — CLOSED 3 Sep 2026

**Trigger:** before any `uia_pattern` operation can be verified, adopted, or
counted toward acceptance evidence.

The signed PowerPoint verifier reads a saved `.pptx` and counts slides in the
package. That is the right shape for an `object_model` operation whose effect
is a file, and it is the wrong shape for a `uia_pattern` operation, whose
effect is live application state that no file reflects until someone saves.

Measured on 3 September 2026 (`docs/evidence/act-live-pointer-run.md`): the
`New Slide` Invoke landed — `Slide 1 of 1` became `Slide 3 of 3` across two
dispatches — and every run still reported `verified: False`. The system failed
closed on a verification it genuinely could not perform, which is correct
behaviour and not a usable end state.

What this needs:

- A separately signed, read-only live-state verifier that reads the running
  application rather than a package. For PowerPoint the reading already used
  by hand is the status bar's `View Indicator Slide N of M` through UIA.
- A manifest slot for it. `adapter_api` declares one `verifier`; this needs a
  second, mirroring the `uia_entrypoint` slot D108 added, with the same bundle
  validation and the same prohibition on it calling any effect API.
- The postcondition to be expressible as a comparison rather than a bare
  `slide.exists`, since "a slide exists" is satisfied by a deck that was
  already non-empty. The before-reading is already taken — `observe_before`
  and `confirm_before` both call the verifier — so the shape exists; what is
  missing is the operation declaring what change it expects.

**Closed 3 September 2026** by `powerpoint_live_verifier.py`, the
`live_verifier` slot in `adapter_api`, and the postcondition change from
`slide.exists` to `slide.count.increased_by_one`. Run 4 in
`docs/evidence/act-live-pointer-run.md` verifies, and the non-vacuity matrix
there shows seven distinct ways it refuses.

The adoption bar is unchanged and still unmet: acceptance needs 3/3 through a
real approval, which this harness does not mint.

## The UIA vertical is not wired into production — CLOSED 4 Sep 2026

**Trigger:** before any `uia_pattern` operation is adopted, or any claim is
made that production verifies a UIA effect.

Found by the D032 review of 4 September 2026 (F10, F11, F12).

`bundle.py` validates and requires a `live_verifier`, then `AdapterDescriptor`
(`ghostcursor/plugins/store.py`) carries no field for it and drops it.
`execute_approved_graph` always constructs `VerifierHost(descriptor)` on the
ARTIFACT verifier — the one whose own docstring says it can only decline a
UIA effect. `uia_entrypoint` has the same problem: outside
`devtools/act_live_node.py`, nothing consumes either.

This is latent rather than dangerous only because `act_cli` never passes a
`uia_session`, so production refuses every UIA node before reaching a
verifier. That is a refusal by accident, not by design.

What this needs:

- `live_verifier` on `AdapterDescriptor`, resolved from the manifest the same
  way `verifier` and `uia_entrypoint` are.
- `execute_approved_graph` routing by the operation's signed `backend` — the
  artifact verifier for `object_model`, the live verifier for `uia_pattern`.
  `AdapterDescriptor.uia_entrypoint`'s comment already claims core does this.
- The live verifier's `main()` validates its request field set at module
  level, BEFORE its `try:`. A frame missing `baseline`/`postconditions` exits
  non-zero, and the resulting `AdapterProtocolError` escapes
  `_execute_approved_graph` rather than becoming an `ActRunResult`.
- Staging wired into `act_cli`, which currently passes the caller's real
  output path straight to the approval (F1).

**Closed 4 September 2026.** `AdapterDescriptor` carries `live_verifier` and
its digest; `choose_verifier` routes by the operation's signed backend and
REFUSES a control-driving operation with no live verifier rather than falling
back; the live verifier's field-set and authority checks moved inside its
`try` so a malformed frame refuses at exit 0; and `act_cli` stages, publishes
after verification and abandons otherwise.

**Corrected 4 September 2026.** This closure said what remains "is not code".
That is wrong, and it was written by the author of the change it describes.
`build_uia_session` is called only from `ghostcursor/devtools/act_live_node.py`;
neither `act_cli` nor `manager` passes a `uia_session`, so
`act_runtime.py`'s `if uia_session is None` branch refuses every
control-driving node in production. The refusal is correct by design -- no
presentation surface means no UIA effect (D109) -- but it means the UIA
vertical is exercised only by a devtool.

So what remains is code AND process:

- **Code:** build a `uia_session` on the production path so `act_cli` and the
  manager can run a control-driving node at all.
- **Process, unchanged:** an independent D032 review of these changes, an
  external release key, and a counted acceptance campaign on the signed bytes.

**Closure corrected 7 September 2026.** The public CLI already composes the
UIA session. The normal manager now does too through
`UiThreadPresentationBridge`; its UI thread owns/pumps the overlay and returns
receipts to the worker. The remaining work is process and live evidence: D032
re-review of D116-D118, paint-budget remeasurement, and a manager-owned live
pointer run before activation.

**Boundary correction later 7 September 2026.** The first re-review withheld
approval: the Python bootstrap could be shadowed from the payload CWD, verified
main code could import mutable plugin siblings, an arbitrary presentation
object could forge receipts, Pause could arrive during authorization, and the
manager tests did not transport a real receipt. Commit `fec9826` closes all
five implementation gaps with an absolute isolated bootstrap, single-file
plugin execution, sealed presentation values, a final pre-dispatch Pause/Stop
gate, and real bridge/factory tests. The fresh D032 verdict, amended paint
measurement, and live manager run are still open.

## A hermetic test was reading the real ESC key — CLOSED 4 Sep 2026

`tests/test_run.py::test_run_tour_creates_overlay_only_after_live_revalidation`
failed twice on a full hermetic lane on 4 September 2026 and passed in
isolation and on the lanes either side. It was recorded as unexplained rather
than as a flake, because this project has twice misattributed a real failure
to flakiness. That was the right call: it was not a flake.

**Cause.** `escape_pressed()` calls `key_was_pressed(VK_ESCAPE)`, which reads
`GetAsyncKeyState`. Its low bit means *pressed since the previous call*, so any
ESC tap anywhere on the machine since the last poll makes it true.
`_run_compiled_tour` checks it and returns 0 **before** creating the overlay —
correct for production, since an abort already waiting must stop a full-screen
topmost window from existing at all. The test does not pin `escape_pressed`, so
whenever ESC had been pressed the run returned early, `create_overlay` was
never reached, and `pytest.raises` failed with DID NOT RAISE at
`tests/test_run.py:295`.

ESC is the documented abort key for the acceptance harness, so a campaign day
is exactly when this fires. The neighbouring test passes only because it pins
`escape_pressed` to True and asserts the early return.

**Reproduced on demand.** Forcing `GetAsyncKeyState` to report ESC down
produces `tests/test_run.py:295: Failed`, the exact observed signature; with
the fix it passes.

**Fix.** An autouse fixture in `tests/conftest.py` pins `escape_pressed` to
False for the hermetic lane, leaving the interactive, pixel and hung lanes
alone. A test that cares about ESC still sets it itself and wins, because
`monkeypatch.setattr` in the test body runs after the fixture. Four other
hermetic tests reached the same check unpinned and had the same latent
exposure.

**What this cost, and the lesson.** The first occurrence was lost because the
lane output was piped through `tail`. The second was nearly lost the same way.
A failure that cannot be read is a failure that gets called a flake — capture
the full output to a file before rerunning anything.

## ADD_SLIDE run recorded no `verification_started_s`

On 4 September 2026, two passing ADD_SLIDE runs recorded no
`verification_started_s` — `attempt-set-01-run-02.json` and
`attempt-set-02-run-03.json` — while every other passing run did, on
identical bytes and one HWND. Records are committed under
`plugins/sources/powerpoint/acceptance-records/`.

An independent D032 review found the second occurrence; this entry originally
said one run, which understated it.

**Counts live in the rendered evidence, not here.** It states them derived
from the committed records, so they cannot go stale; this entry twice carried
a hardcoded "six" that a later attempt set had already made wrong.

**A measured number, and the wrong story about it.** Where the mark is
present, `ended_s - verification_started_s` is 0.500s or 0.516s in every
record. This entry first read that as "exactly one tick", and concluded that
arming and satisfaction fell on *different* ticks. An independent review
traced it and that is wrong.

The 0.500s is fixed drain, not a gap between two events. `compiled_tour`'s
driver sleeps `tick_interval_s` (0.25s) at the end of every iteration, and
after the rule is satisfied the run still passes through `VERIFYING` (which
advances the step index and returns to `OBSERVING`) and then `OBSERVING`
(which sees no current step and reaches `DONE`, where `_timing()` is read).
That is two sleeps -- 0.500s exactly -- and the two records at 0.516s carry
about 16ms of ordinary per-tick overhead on top.

So arming and satisfaction happen on the **same** tick, which makes the
absence *more* surprising rather than less: on the satisfying tick the
selector union changes, so `elements_changed` should be true at the moment
`satisfied` becomes true.

Recorded as a D031 failure of my own: a numeric coincidence was promoted to a
causal story without tracing the code that produces the number.

**Static reading does not explain it, and contradicts it.** In
`reasoning/loop.py`'s `AWAITING_USER_ACTION`, the arming branch
(`if self._verification_started_at is None and action_detected`) runs *before*
the `elif satisfied` branch on the same tick, and nothing on the completion
path clears the mark: `VERIFYING` does not reset it, and `OBSERVING`
re-baselines only while it is unset. The union published into
`Snapshot.elements` also changes on the satisfying tick, because the recipe's
`slide1_before` selector stops matching and `slide2_after` starts — so
`elements_changed(previous, after)` should be true exactly when the rule is
satisfied.

So a run appears to have satisfied `element_appears` on a tick where
`action_detected` was false. Either `elements` does not carry what the above
assumes for this plan shape, or the step completed by a path that does not
pass through that branch.

**One hypothesis is already refuted.** It looked like `Snapshot.elements`
might exclude selectors answered by a `provider_exact` query, which would make
`elements_changed` blind to this recipe's effect. It does not:
`run_observation_plan` extends the same `observed` list from the query loop as
from the traversal loop (`perception/service.py`, the `for query in
plan.queries` block), and the union is built from it.

**What is not in doubt:** the run's pass is sound independently of the mark.
`element_appears` is `not was and bool(now)`, so the view indicator did not
read `"View Indicator Slide 2 of 2"` at the last observation before the
verification clock armed, and read exactly that when the rule fired.

**Not** "when the run started": `reasoning/loop.py:196-198` re-assigns
`self._before` on every `OBSERVING` pass while the clock is unarmed, and the
loop re-enters `OBSERVING` on an unexpected-change interrupt, so the baseline
is the last observation before arming.

The harness synthesizes no input — `tests/test_no_input_synthesis.py` scans
`devtools/` explicitly — and makes no COM call, so the change came from
outside the harness. That the person who made it was the supervising operator
rests on procedure. The cited scan establishes the absence of input synthesis;
it does not by itself establish the absence of COM, and "not the harness"
therefore does not on its own mean "a person".

**Corrected 4 September 2026, twice.** This paragraph previously said that
selector was reachable only from a one-slide deck. A later review found that
the correction itself had left two more retracted claims standing in the very
paragraph above it — the run-start baseline and "so a person did it" — which
the rendered evidence had already withdrawn. Fourth recurrence of one
retracted claim surviving into another tracked copy; the lesson recorded here
is to grep every tracked file for the exact retracted sentence, not to fix the
copy that prompted the review. It is not: navigating to slide 2 of
an existing two-slide deck, or deleting a slide from a three-slide deck viewed
at slide 2, both satisfy the same absent-then-present rule with no slide
added. The rendered evidence retracted that claim in commit `b3cc294`; this
copy was missed, so two tracked documents disagreed until an independent
review found it.

The recipe sets no `fail_after_timeout`, so the mark bounds nothing here.

**Why this still blocks that record as evidence.** Not because the mark is
universally required — `tools/render_excel_plugin_evidence.py` declares it
per workflow (`verification_started: False` for `SELECT_CELL_B2`, `True` for
`ADD_WORKSHEET`) and enforces that by exact set equality, so for some
workflows its ABSENCE is what the gate demands. The bar is **consistency**:
whichever expectation ADD_SLIDE declares, a set that produces the mark in two
runs and not the third violates it, on identical bytes and one HWND. That is
a nondeterministic landmark, which is a finding in its own right.

`Step.preconditions` is parsed in `reasoning/schema.py` and never read by the
reasoning path, so the declared `slide1_before` precondition gates nothing —
noted here because it removes the other structural check one might reach for.

Admitting the record by declaring the mark optional would mean widening a
gate to fit an unexplained result, the shape of failure D031 and D032 exist
to catch.

**The one hypothesis still standing.** A worker-thread publish race: the
`satisfied` tick comparing against a `previous` that is not truly the
immediately-prior published snapshot. Constructed but not confirmed.

Next: reproduce with the loop instrumented (not on an acceptance run), logging
`_verification_started_at`, `action_detected` and `elements_changed` per tick,
and determine which possibility holds before either explaining the gate away
or tightening the arming condition.

**Not cosmetic.** The mark bounds nothing for *this* recipe because it sets no
`fail_after_timeout`. But the cause is unattributed, and if it is a perception
publish race then the same race could reach the satisfaction check itself on a
recipe that does set a timeout. Keep this open until the mechanism is found,
not until the evidence is accepted.

## Two writers on one overlay window during a paced Act run

Found by the D032 wiring review, 4 September 2026. With `--rail --regions`
and a control-driving plan, `devtools/act_acceptance.py` shares one overlay
window between the region highlighter and the cue presenter, and neither owns
it. The region sink calls `overlay_window.clear_cue(hwnd)` on every
`action_started` and `set_cue()` on every region event, directly on the window
the presenter is animating, while the presenter keeps `state["position"]` and
`state["scene"]` in its own closure (`act_overlay.py`).

After an external clear the two diverge. A VERIFIED node's pointer -- which
D112 deliberately keeps on screen *so the next cue can travel from it* -- is
wiped by the next node's `action_started`, and the following cue then animates
from a position nothing is painted at. Nothing crashes and no effect is
unshown; the cue simply starts from a place the user cannot see.

Sharing one window is right: a second topmost full-screen window would fight
the first for the same pixels. What is missing is an owner. Either the
presenter exposes the region highlight as one of its own scene layers, or the
region sink is suppressed for the duration of a presentation. Both change what
the user sees during a paced run, so this wants a decision rather than a patch.

Not urgent: the combination needs `--regions` AND a control-driving plan, and
no `uia_pattern` operation is adopted.

## `act_live_node` still dispatches under invented receipt deadlines

`ghostcursor/devtools/act_live_node.py` hardcodes
`ReceiptPolicy(first_paint_deadline_ms=2000, completion_deadline_ms=8000)` --
verbatim the constants removed from `act_cli` and never added to
`act_acceptance`, for having nothing measured behind them (D034).

It is a declared diagnostic that bypasses `execute_approved_graph` and mints
no real approval, so it is off the reviewed authority paths. But it does
dispatch a real UIA effect, and it does so under deadlines nobody derived.
Once `ghostcursor.devtools.receipt_budget` has run, this should take the
measured numbers as arguments like every other caller; until then its report
should say the deadlines are invented rather than leaving a reader to assume
Phase E produced them.
