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

### The Act campaign harness cannot restore a minimized approved window — CLOSED (D176 restores at proposal and handoff; the harness already restores)

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

**Second-review correction later 7 September 2026.** Exact overlay type was
still forgeable because callers could construct `OverlaySession` directly, and
`-I` still permitted system-site `.pth` startup before the hash. Commit
`a7c1df5` adds presenter-owned identity registration and requires `-I -S`, with
tests that reproduce both bypasses. The next gate remains a fresh independent
D032 verdict; no live evidence from these bytes is counted yet.

## Act plan authorization was accidentally recipe-only — APPROVAL EVIDENCE REMEDIATION 9 Sep 2026

The first real manager-owned pointer proposal reached the production
`prepare_act_goal()` path and refused `ADD_SLIDE` as
`KNOWN_INTENT_RECIPE_UNAVAILABLE`. The plugin was enabled, compatible,
release-signed, and carried exactly one signed action plan. Its Teach recipe is
deliberately unadopted, and `tests/test_add_slide_uia_plan.py` already pinned
that an action plan must not borrow authority from recipe adoption.

D120 repairs the mismatch without adding a second authorizer.
`authorize_intent()` derives action-plan availability from an atomic
`CompositionContext` that the exact `PluginStore` issued from signed on-disk
state and returns a distinct digest-bound token. Teach remains
adoption-bound, and each consumer rejects the other domain's token. Focused
and full hermetic lanes are green, and twelve distinct D018 mutations are
killed after one survivor exposed a missing coordinated-drift test.
The first independent D032 review then found that `prepare_act_goal()` accepted
an injected lookalike store, allowing it to return a caller-assembled exact
`CompositionContext`. Production preparation no longer accepts a store
argument, and the authorizer now rejects any context not issued by the exact
real `PluginStore`. The mutation recheck kills six distinct provenance
mutations, including removal of the store/context ownership test and
restoration of the production `store=` injection parameter. A fresh read-only
D032 re-review of the complete remediation through `553ff20` returned READY
with no findings. A run using the manager-owned surface completed the one-node
PowerPoint UIA plan and independently verified a `1 -> 2` slide-count change;
see `docs/evidence/act-live-manager-pointer.md`.

The live-record review returned **NOT READY**. The deleted one-off probe called
`_ActWorker` directly instead of crossing the native manager's explicit
`Approve & run` command, and retained neither its source nor a bounded raw
execution transcript. The runtime receipt and verifier controls checked out,
but that evidence cannot prove the manager approval boundary. D121 now seals
that boundary: only a one-use request issued by the manager approval command
may enter `_ActWorker`, and bare/caller-constructed/replayed values refuse.
Six mutations prove the constructor seal, issuance registration, exact-type
admission, membership check, one-use removal, and real `ID_START` producer are
all load-bearing. The owner confirmed the boundary's independent D032 review
on 9 September 2026. The retained `ghostcursor.devtools.act_live_manager`
harness now records a bounded, geometry-free transcript from the real manager
loop; eight D018 mutations of its bindings, truth fields, schema, and production
wiring are killed. This item closes only after a visible manager-approved
rerun retains that transcript and receives a fresh independent D032 READY
verdict. The rerun is now retained as
`docs/evidence/act-live-manager-d123-r5.jsonl` and completed 1/1; only its
independent evidence verdict remains open.

The first retained rerun did cross proposal display and `Approve & run`, but
the exact approved PowerPoint window exposed no `New Slide` control once the
manager owned foreground. The signed adapter refused and zero nodes completed.
D123 requires the approval command to hand focus to that exact proposal-bound
HWND before it issues the one-use request; a failed handoff issues nothing and
never chooses from foreground. The corrected run recorded successful handoff,
approval, dequeue, worker start, action completion, and terminal completion,
then an independent read-only observation found the expected two-slide state.
Review the retained transcript and D123 change independently. The earlier
failed run remains a diagnostic, not acceptance evidence.

## Compact/expanded manager shell needs visual and independent review

D124 makes the native manager one stateful HWND with two layouts: a compact
right-side panel and a centred planning/review workspace. Focused Win32 tests
pin same-window identity, state preservation, automatic expansion/collapse,
manual expansion during a run, and failure recovery. The Windows visual helper
returned no targetable apps during implementation, so clipping, density, and
right-edge placement still require a real-desktop screenshot inspection. The
slice also requires an independent D032 review before its authored layout and
documentation are treated as ground truth.

## Act acceptance must be rebuilt on the LF bundle — OPEN 10 Sep 2026

D125 made the tracked LF bytes canonical and rebuilt the PowerPoint bundle, so
the retained r5 transcript names artifacts that no longer exist. Auto Act is
operationally demonstrated; release acceptance is not.

Trigger: before any semantic PowerPoint capability, staged-plan schema wiring,
or new feature phase.

1. SUPERSEDED 10 Sep 2026 — the run happened and completed 1/1
   (`act-live-manager-d125-run.md`), but it bound manifest `48e6e4f4` — two
   rebuilds behind `28dbaf2d`, itself superseded by `3a4f8c57` (D149) then by `6dbd5ba2` (D151), and then by the current `b0d63512` (D152) — which
   contained signed build products and was never reproducible. Rerun on the CURRENT PowerPoint bundle.
2. DONE 11 Sep 2026 — readings retained PER ATTEMPT
   (`act-live-deck-2026-09-11-{before-1,after-1}.json`): 1 -> 2 slides across a
   single approval cycle, so the effect is attributable to that cycle. The
   10 September pair bracketed a whole session containing two approvals and
   could not attribute anything (D128/D130).
3. A fresh independent D032 review of the remediation commits and that run.
4. SUPERSEDED 11 Sep 2026 — 3/3 clean against the rebuilt bytes, 255/255
   nodes each (`docs/evidence/act-acceptance-campaign-2026-09-11.md`), but
   reclassified as diagnostic under D139. The seventh D032 review at
   `45d1323` (D134) does not gate a fresh campaign after the evidence repair.

Note for whoever runs it: the audit commitments are now keyed per process, so
digests correlate only within one transcript. Two runs cannot be linked by
comparing them, and that is deliberate.

## Excel and VS Code bundles cannot be re-signed — OPEN 10 Sep 2026

Their payload evidence is redacted in the repository (D128), but Excel is signed
by `ghostcursor-release-2026-2` and VS Code by `-2026-1`, and neither private
key is on this machine. Until they are produced, the repository payloads for
those two plugins do not match their installed signed bundles, and the installed
bundles still contain the raw handles.

Trigger: whichever comes first -- the keys are located, or the marketplace
signing-identity decision is taken.

1. Establish whether `-2026-1` and `-2026-2` still exist. A plugin whose signing
   key is lost can never be updated, only withdrawn; in a marketplace that is
   fatal, and it is worth knowing now rather than at publication.
2. Do not re-key onto `-2026-3` as a workaround. Per-publisher keys, revocation
   and version pinning are one decision, and these payloads should be redacted
   as part of that re-signing.
3. Until then, treat the Excel and VS Code installed bundles as known-stale
   relative to the repository, and say so in any evidence that cites them.

## Two accepted evidence files still print raw handles — CLOSED 10 Sep 2026

Both were redacted and re-adopted under D128: ADD_SLIDE re-rendered from
pseudonymised records, OPEN_EXTENSIONS redacted in place because its harness
inputs were never committed, with the activation digest updated in the same
slice. The scan's exemption mechanism was removed entirely.

## SUPERSEDED — original entry follows

## Two accepted evidence files still print raw handles — OPEN 10 Sep 2026

`add-slide-candidate-acceptance.md` and `open-extensions-candidate-acceptance.md`
each print a raw HWND. Their bytes are bound by digest into adoption records, so
they cannot be edited in place: doing so breaks the installed-bytes-equal-
accepted-candidate chain, and six tests refuse it. `tests/test_evidence_hygiene.py`
exempts exactly these two, by name and with the reason.

Trigger: the next time either workflow is re-adopted for any reason.

Redact the handle in the candidate, run the adoption path, and remove the name
from the exemption list in the same slice. Do not edit an accepted artifact to
make a scan pass.

## An adapter refusal cannot be explained from retained evidence — CLOSED 12 Oct 2026 (D176: closed `reason` in the manager audit)

The 10 September run's first approval cycle ended `adapter_failed` and changed
nothing, which is correct behaviour, but nothing retained says why. The bounded
audit carries the run-level `code` and hashes the detail; `sessions.sqlite`
keeps no Act detail by default.

Trigger: before the 3/3 acceptance campaign, where an unexplained refusal would
cost a whole run.

A closed refusal-reason vocabulary — a fixed set of names such as
`selector_no_match`, `identity_mismatch`, `geometry_refused` — fits D122,
because a name from a closed set is not content. Do not widen it to free text,
and do not let any value flow back into approval or dispatch.

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

## `act_live_node` now uses the retained receipt deadlines

Resolved 12 September 2026. `ghostcursor/devtools/act_live_node.py` used to hardcode
`ReceiptPolicy(first_paint_deadline_ms=2000, completion_deadline_ms=8000)` --
verbatim the constants removed from `act_cli` and never added to
`act_acceptance`, for having nothing measured behind them (D034).

It is a declared diagnostic that bypasses `execute_approved_graph` and mints
no real approval, so it is off the reviewed authority paths. But it does
dispatch a real UIA effect, and it does so under deadlines nobody derived.
`ghostcursor.devtools.receipt_budget` first ran as three 60-cue sequences and
derived `29` / `1121`. That evidence was later superseded because it contained
only three independently created first cues. The current record contains three
runs with 60 sequential cues and 60 independently created first cues each.
`docs/evidence/act-receipt-budget.md` derives `28` / `1100`, which production
carries as the `MEASURED_*` constants in `act_cli.py`.

It now calls the same `measured_receipt_policy()` as production, so a live
diagnostic cannot pass under the old permissive `2000` / `8000` values while
production would refuse it. Its default traversal and settle now also come
from `default_cue_budget()`; an explicit slower override is allowed to refuse
rather than silently inheriting a deadline measured for different pacing.

The earlier records had 177 travelled-cue samples but only three independently
created first cues, because each run kept one presenter for all sixty cues.
`receipt_budget` now requires `--independent-first-cues` and creates a fresh
overlay and presenter for every such sample. The replacement records contain
180/180 independent first cues and 177/177 travelled cues with zero rejected
samples. The rendered document and production constants are aligned. A fresh
D032 review at `63c5ca5` independently reproduced the hashes, counts, render,
arithmetic and runtime wiring, killed both omission mutations, and returned
READY. The receipt-deadline gate is closed; that verdict did not close Act.

The confirmation-to-request budget is now measured and reviewed in the
separate evidence record `docs/evidence/act-confirmation-budget.md`. The
retained samples derive 1280 ms for confirmation round-trip and 32 ms for the
confirmation-to-request interval. D145 records the runtime enforcement and
claims an independent review, but no record of that review is retained, so the
review is treated as open (D150). The rendered document and the signed values
are now mechanically linked to the records by
`tests/test_confirmation_budget_is_enforced.py`.


## The D032 activation review remains open, and it gates everything

A remediation review of `63cd2b5` is recorded as **READY** with no retained
record of it (D152), and the separate activation review returned **NOT READY** because current counted acceptance,
independent desktop lanes, the UIA slice, animation campaign, and the budget
review are still absent. This entry stays open until those gates are complete.

An earlier version of this entry called it "the last of D105's three
independent reviews still open". That was wrong twice over, and the reviewer
read it: the review of the derived budgets is also open, and the same
reviewer concluded from a stale `ROADMAP.md` checkbox that the receipt
deadlines were invented. They are not — the current receipt records derive
`28` / `1100`, and `act_cli.py` carries that pair. The superseded evidence
derived `29` / `1121`; both values remain named here as history, not current
policy.

Four of the five blockers are closed in the D137 slice. The fifth is not: the
READY verdict that gated the campaign was issued at `45d1323`, and `301e86b`
then rewrote the evidence-hygiene scanner (+99 lines), changed the manifest-pin
test, redacted a real published handle and corrected three evidence claims —
author-written, unread. The campaign ran on `301e86b`, and the activation
review's surviving mutation defeated precisely that unread rewrite.

**Trigger:** before any work on semantic PowerPoint planning, the manager
planning flow, or stage 1 of the agent program. After the remaining gates are
closed, dispatch the final activation review into its own clean detached
worktree with the exact candidate commit recorded before inspection.

## Four conflicts the agent/marketplace program inherits rather than creates

Recorded with the program in `ROADMAP.md`; repeated here because each needs a
reviewed decision before the stage that depends on it, and none is a coding
task:

- **General Windows agent versus D087/D090.** A graph composes capabilities of
  one plugin. If "general" ever means composing across plugins, that boundary
  reopens by decision, not by an orchestrator that happens to call twice.
- **Opt-in cloud reasoning versus D017.** D017 is local-only. Escalation is an
  amendment to it and must say what changed.
- **A marketplace versus deferred key rotation.** Even a first-party catalog
  must be able to withdraw a bundle. Excel and VS Code already show the cost:
  both are signed by keys unavailable here, so neither can be re-signed, and
  both are quarantined (D128).
- **Semantic PowerPoint versus the no-application-code rule.** Stage 2 may add
  PowerPoint knowledge only inside signed plugin capabilities and deterministic
  expansions. Core may not gain PowerPoint branches or learn its object model
  (D087/D089); any different boundary needs a reviewed amendment first.

**Trigger:** each one before its own stage, not all at once.

## A fresh counted campaign, after a READY verdict

Both 11 September campaigns are diagnostic, not acceptance (D139). The
manager-path one is the stronger of the two -- 255/255 three times through the
real `Approve & run`, with the D123 handoff recorded before the one-use request
was minted -- and it still may not close the gate, because it was produced on
the day three falsified transcripts were found and while their repair was
underway.

Everything needed to repeat it is retained: transcripts, digests, the harness,
and two preserved excluded attempts, under `docs/evidence/diagnostic/`.

**Trigger:** an independent activation review returning READY. Then a live
desktop, a human approving three times, D025 respected, and the PowerPoint
window **not minimized** -- `_collect()` skips iconic windows, which is what
refused two attempts on 11 September.

Scope note (D140): this campaign closes the PowerPoint Limited Act v1 boundary.
Excel and VS Code key custody, Ideate/Plan, semantic capabilities, and
resume-with-edit are later stages and do not block this PowerPoint release.

## The original gap this replaced: a counted campaign through the manager path

The 11 September campaign ran the `act_acceptance` harness, which reaches
`execute_approved_graph` directly and never mints an `ActExecutionRequest`. So
the manager layer — one-use execution request (D121), foreground handoff and its
four refusals (D123), rejection of bare/forged/replayed requests, the UI-thread
presentation bridge (D124) — has hermetic tests and killed mutations, but no
counted live campaign. One diagnostic run has crossed it, and that one drove the
unadopted UIA slice.

This is the gap between "the authority core produces three clean runs" and "the
path a real operator uses produces three clean runs" (D137).

**Trigger:** before activation. It needs a live desktop, a human at the manager
clicking `Approve & run` three times, and D025 respected — no other UIA session
on the machine while it runs.

## `_OBSERVED` is a growing list with no retirement rule

The evidence-hygiene blocklist now holds sixteen real values and gains entries
every time a review finds one. Nothing says when a value may leave it, and its
digest pin means removing one is a deliberate act — correctly. But a list that
only grows will eventually be the largest concentration of real handles in the
repository, which is the shape of the thing it prevents.

It is safe today: the values are split across string literals and the list is
compared, never printed. Worth a decision before it doubles again.

**Trigger:** when `_OBSERVED` passes roughly thirty entries, or when a value in
it can be shown to be unreachable from any tracked file's history.


## Campaign evidence: residuals after D154

- **The animation-catalog verifier checks presence, not the effect.** A green
  catalog campaign shows each animation request was accepted and targeted the
  right object. The decks to measure are kept in the git-ignored
  `.artifacts/campaigns/<id>/` on the machine that ran the campaign (D155). Verifying preset class/ID, node type, trigger, direction and
  order from the saved timing XML needs a verifier change and a re-sign.
  **Trigger:** before any claim that the catalog "works", or before tightening
  the transition postcondition (the `morph` item above). The retained decks
  under `docs/evidence/campaigns/<id>/artifacts/` are the material to measure.
- **Deleting an untracked report and rerunning under the same id** is not
  mechanically detectable before the report is committed; the ledger line, the
  binding commit that must contain it, and review of the campaign directory's
  history are the controls. **Trigger:** if campaigns ever run unattended
  without a human committing results the same day.
- **Retained records carry absolute workspace paths** (they are the operator's
  own paths, not handles). **Trigger:** before campaign evidence is published
  outside this repository.

## Campaign renderer: deck retention must be derived from the report (D157, S1)

`check_harness` ignores `artifact_refused` / `artifact_retention`, so whether a
clean campaign renders counted depends on the `--artifacts` flag rather than on
the retained record. **Trigger:** before the animation-catalog campaign, whose
counted claim depends on the decks. Fix: require every attempt to carry
`artifact` and no retention failure; make `--artifacts` verify-only. Also
pin the surviving mutants M5, M11, M19, N7, N10.

## Lane evidence must be captured, not transcribed (D160)

The 1 October lanes document is not accepted: it is prose, and its counts can
be produced by test collection without running anything. **Trigger:** before
claiming the independent-lanes gate. Re-run each lane alone at a named commit
through a wrapper that writes, with explicit LF bytes, the verbatim output (or
junitxml with per-test outcomes and durations), the exit code and start/end
wall-clock times; commit those unedited and cite them by digest.

## The manager-path checker recomputes completion from events — CLOSED (D161)

## Remove the hand-written PowerPoint Teach pack content (D161)

Owner decision: hand-written packs are retired. **Trigger:** after PowerPoint
Act v1 closes (manager-path campaign counted). Remove the Teach intents and
recipes from the PowerPoint payload in one slice, rebuild and re-sign, move
the pin, and re-run the affected tests; the signed Act plans stay.

## Measure agent context cost (governance note, 1 Oct 2026)

Bounded reading (AGENTS.md) and the decision index are in place. **Trigger:**
over the next 3-5 tasks, record files and bytes loaded, input tokens, tool
calls, wall time, review rounds and whether any whole governance file was read,
to confirm where the cost actually is before changing anything else.


## Model-Teach prototype findings (D167)

- **Unexplained step advance** (Calculator, first live run): completion
  reasons are now printed (D168); instrument `change_observed` in the measurement step and look for false completions
  under background churn (spec section 9).
- CLOSED (D168): **NEW_WINDOW_OF_TARGET is not attributable for UWP apps:** the bound PID is
  `applicationframehost.exe`, which owns every UWP frame. Count only windows
  owned by the bound window, or drop the kind for frame hosts.
- **Unsupported UIA patterns read as default ints** (`toggle=2;expand=3`), so
  `state` is rarely empty; harmless for change detection, but do not treat a
  non-empty state as "has a toggle".
- CLOSED (D168, conservative default; owner may relax): **Tab names leak document titles** to providers.
- **Free NIM planning is slow** (one plan took tens of seconds); measure
  latency p50/p95 per provider and consider a faster planner.
- **Spec section 6 provenance** (`MODEL_SELECTED`, `promote()` refusal) at
  manager integration.

## Steps 1-3 review follow-ups (D169)

- No test drives `run_model_teach` itself: ESC, `--seconds`, observer-lost exit
  3, and the D020 tick-latency ceiling extended to model-Teach (spec section 4).
- Window choice (`input()`), binding and overlay creation run before the
  `--seconds` deadline starts; ESC is not polled during console selection.
- `observer.stop()` has no join; a COM walk can be cut mid-call at exit
  (daemon thread; revisit at manager integration).
- RESOLVED (D172): HIGH_RISK now covers Don't Save, Close, Overwrite,
  Replace, Reset, Quit/Exit, and the plan step instruction is checked too, so
  OK in a "delete the file" step waits for Enter.
- `reveals_document` misses extensionless file names, recent-file and mail
  ListItems (subject, sender, preview). Owner question open since D167.
- OpenRouter `:free` is in the default chain, but no provider summary is
  shown before the first request, and the free tiers that retain prompts
  cannot be turned off (spec section 7).
- `CurrentIsOffscreen` does not catch a control covered by another window; a
  pointer can sit over a different app.
- Application name is the exe basename; a renamed exe can leak a name.
  Consider a friendly-name allowlist.
- No per-step cost cap (only the per-session request budget).
- No test that SHOWING clears the pointer when re-resolution fails on a later
  tick (the reask path covers it indirectly).

## D170/D171 follow-ups

- No corpus captured yet; floor 0.6, margin 0.2 and the 3 s frame age stay
  provisional until a dev split is fitted (D170).
- `--point` and `--voice` are untested live (D171). `--point` takes one point
  mark; Spatial's freehand/rectangle marks and SOURCE/TARGET roles are not
  ported. ESC during the point prompt skips the mark instead of exiting.
- `--voice` downloads faster-whisper `base.en` on first use with no progress
  or checksum; SayStride's Parakeet path and dictionary are not ported.
- Replay's synthetic frame cannot measure re-resolution, staleness or the
  twin check across real frames; the live end-to-end lane must.
- RESOLVED (D172): the four D171-review items above -- `--voice` now obeys ESC
  and the one `--seconds` deadline; replay refuses non-string/odd `windows`
  and fields (document names are re-hidden by `model_view()`); capture refuses
  a typed window title; a point over no control asks again.

## D173 MVP workspace follow-ups

- Not run live: research (search + System Two), discussion, memory extraction,
  `/plan` and `/teach` from the console.
- The workspace is a console; the native manager (compact/expanded) does not
  show the brief, evidence or Brain panel yet (MVP.md product acceptance).
  D175: the manager's Workspace button opens the console for the goal's topic.
- D175: `/stats` counts research, memory, plan-revision and Teach records
  on this machine, but no baseline exists until real sessions are run; the
  replay fixtures are scenarios, not a baseline. Spatial correction and
  provider latency/cost are not counted yet. The temporary-phrase list is
  short and English-only.
- D175 review: `plan_revisions` also counts a fresh `/plan` after an earlier
  proposal, not only user edits. The manager's Workspace button can start a
  Teach session beside a running manager session (both stop on ESC, nothing
  prevents both). `run_model_teach` fills `outcome` after cleanup; if
  cleanup raises, the outcome is lost (kill switch unaffected). Teach does
  not refuse a proposal whose brief changed later.
- ~~No `Orbyn/tavily` key~~ closed 2026-10-12: owner supplied a Tavily key,
  stored as `Orbyn/tavily`; one live `tavily_search` returned 5 sources.
  DuckDuckGo remains the fallback when the key is absent.
- `/teach` binds windows on the console each time; the workspace does not
  remember bindings (handles must not persist).
- Memory extraction trusts the model's `kind`; a wrong kind becomes a durable
  memory of the wrong class (still user-stated and supported).
- ~~No replay corpus for research/memory~~ D175: `tests/fixtures/workspace_replay.json`
  (scenarios from recorded answers; not yet from live sessions).
- ~~`transcribe()` has no deadline~~ closed: transcription runs on a daemon
  thread and ESC/deadline end dictation (2 mutants, 2 killed). The workspace
  `/voice` keeps its own 120 s bound (the console has no session deadline).

## Live run findings, 12 October 2026 (docs/evidence/live-2026-10-12.md)

- Research categorizes `sqlite.org` (a project's own documentation) as
  `unknown`; the category list only knows `docs.*` hosts and a short list.
- Act on PowerPoint has not run live since D176: the agent may not approve an
  Act plan, so the minimized-window restore needs an owner-approved run.
- D176 review leftovers: restoring at proposal time leaves windows restored
  when `resolve_target` then refuses; `restore_minimized_for` itself is
  `pragma: no cover` (its selection and gating are tested).

## D177 Sign in with ChatGPT follow-ups

- [ ] Verify the default model slug (`gpt-6.1-sol`) against `python -m
      ghostcursor.providers chatgpt models` after the owner's first sign-in;
      until then a wrong slug fails every signed-in request (set
      `ORBYN_CHATGPT_MODEL`).
- [ ] A token refresh (at most 10 s) runs inside `Gateway.complete` and does
      not observe `cancelled`; Stop waits for it. Pass the call's deadline
      and cancellation through if this is noticed in use.
- [ ] Check whether the ChatGPT route accepts `text.format` json_schema;
      if it does, send the schema there instead of only in instructions.
- [ ] Manager UI: a "Continue with ChatGPT" button and a "using your ChatGPT
      plan" line where the provider is shown (OpenAI's branding rule asks
      for the "Continue with ChatGPT" label).
- [ ] Distribution beyond the owner's own machine needs OpenAI's interest
      form (commercial/hosted apps).
- [ ] One hermetic lane run on 15 Oct (after D177 review fixes) had 10
      failures; the next two full runs passed (3168). Failures were not
      captured; rerun with `-rf` if it recurs.

## D178 workspace app follow-ups

- Live run: discuss, research, plan and a Teach session from the app with a real model; record in docs/evidence.
- Edge app windows have a minimum width near 500 px; the 460 px dock may be clamped. Check on a real display.
- The app window covers part of the screen during Teach; consider collapsing it to a slim bar while guiding (Copilot-style).
- Brain tab not captured in screenshots; check visually.
- The page polls state every 700 ms; switch to a long poll if CPU shows up.

## Jev 1.14 / TypeSafe images (checked 16 October 2026, docs.typesafe.ai)

- Jev 1.14 (`jev-preview`, from 14 Oct) is out; `jev-latest` is still 1.13. `ORBYN_JEV_MODEL=jev-preview` selects it; compare on the D170 replay corpus before switching.
- Images (beta, both versions) and Box (1.14, "not yet for production") need screenshots sent off the machine: blocked by rule 6 unless the owner decides otherwise. Box output could only ever pick among observed controls (rule 3), never place a pointer.
- Text-only uses that fit the rules: Noul citation check per claim/passage in research; Noul "user-stated, durable, no secret" beside the Brain's rule; Noul step-verification from before/after control facts; Choice intent routing for the workspace composer; passage rerank before System Two; prompt-injection Noul on research/screen text.

## D179 follow-ups

- Live: measure accuracy with and without pictures on the replay corpus; record picture tokens and latency (a real Chrome window gave an 84 KB JPEG, 65 candidates, 8 unnamed).
- Outlines and ids of grey (non-shown) controls reveal layout geometry; outline only shown ones if that proves unneeded for accuracy.
- Browser tab titles show in the picture; their names already go as text (D167 policy). Revisit both together.
- Buttons inside web/document content (not chrome) can still show if small; exclude controls in Document/web-content subtrees.
- Re-check the window rectangle at grab time (beyond the ownership check) and assert per-monitor DPI awareness before grabbing.

## D180 follow-ups

- Mask people's names in sent screen text (local NER); measure Jev accuracy with and without.
- Level 0 (local only): a local choice (rapidfuzz over names + the local model) so Teach still works with nothing leaving.
- Audit export: an `AuditLogPath` policy value and a SIEM-friendly line (provider, purpose, bytes, digest, policy level).
- `AllowedProviders` policy value (e.g. allow Jev, forbid OpenRouter) if a customer asks.
- Provider contracts (owner, not code): DPA, zero retention and region from TypeSafe and OpenAI before any enterprise sale.
