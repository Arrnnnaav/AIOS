# Tracked follow-ups

Small items deliberately deferred rather than forgotten. Each says what it is,
why it was not blocking, and what it would cost to leave.

## From perception tier 2 (merged 429a85e, 2026-08-19)

### 1. Merge-cap test counts words, not parts — RESOLVED 2026-10-18
The fixture now uses two-word reads and asserts `<= 2 * MERGE_MAX_PARTS`, so the
assertion tracks the PART cap instead of coinciding with it only for single-word
reads. A merge of more than `MERGE_MAX_PARTS` reads now fails the test.

### 2. Vestigial parenthesised import in `run.py` — RESOLVED (already gone)
No single-name parenthesised import remains in `run.py`; the three paren imports
left (session, plugins.platform, compiled_tour) are all multi-name and legitimate.

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

### 5. `test_persistence_e2e` allows rung 2 or 3 where FLOW says rung 2 — RESOLVED 2026-10-22
No defect. FLOW.md:972 documents the one measured run on the production compiled
launcher (rung 2); the test's wider `in (2, 3)` is deliberate tolerance, because
rung 3 is the legitimate OCR-fallback path on a machine where the UIA name match
is stale. Tightening the assertion to `== 2` would make a desktop-lane test flaky
across environments for no correctness gain. Doc and test are each correct for
what they state; nothing to change.

## Separate milestone, already scoped

### `/web` WebMCP tool discovery — DEFERRED with a named trigger 2026-10-22
Candidate feature from the AFFiNE decompile: a read-only `/web` probe that detects
agent-callable tools a web page exposes, for Orbyn's model-driven harness. Agent-reach
research (2026-10-22) decided **don't build now**:
- **W3C WebMCP** (`github.com/webmachinelearning/webmcp`, Google/Microsoft CG) is an early
  draft, not standards-track. Its entry-point global renamed twice in ~6 months
  (`window.agent` → `navigator.modelContext` → `document.modelContext`), needs the Chrome
  `enable-webmcp-testing` flag / an origin-trial token even to observe (trial Chrome 149–156,
  Edge 150), has **no CDP domain** and **no `.well-known`/manifest/header** — discovery is
  runtime `Runtime.evaluate` of a JS global whose shape is itself unstable. **Zero verifiable
  production sites** expose tools today.
- **The AFFiNE signal is a DIFFERENT thing:** `/.webmcp/bridge.js` + `MCP-Session-Id` is an
  in-page MCP-over-HTTP bridge (Streamable-HTTP transport session header), vendor-specific,
  not the W3C API. A detector keyed on it won't generalise; the two share almost no surface.
- Building now = a demo-only detector needing a re-pin every quarter. YAGNI.

**Reopen trigger:** the Chrome WebMCP origin trial graduates AND ≥1 non-demo site ships
`document.modelContext` tools. Then the MVP is a ~1-day flag-gated read-only probe:
headless-Chrome `Runtime.evaluate` testing `typeof document.modelContext` (legacy fallback
`navigator.modelContext`), then `getTools()` to enumerate names/descriptions/schemas — one
canonical artifact; the declarative `<form toolname>` scan is secondary and unsettled.
First check what REA's own `discover_webmcp_tools` keys on before writing ours.

### Chromium warm-up retry — CLOSED WON'T-BUILD 2026-10-22
Original idea: Electron apps are blind-until-asked; a first walk returning window
furniture but no document content is NOT-YET-READY rather than empty, so retry
instead of escalating to OCR. Cheaper than OCR, looked like a real-bug fix.

Closed after reading the shipped code: it proposes a content-readiness classifier
("furniture but no content" ⇒ NOT-YET-READY), and `ghostcursor/perception/warmup.py:9-13`
records that *this exact approach* was ruled out by measurement — furniture-but-no-content
is transient (VS Code, Acrobat TERMINAL) and the element count is non-monotonic even in
steady state, so comparing consecutive observations is unsound. The shipped design
deliberately detects nothing and instead grants patience keyed on grounding success
(the one sound readiness signal). Building the classifier would re-introduce a heuristic
the codebase already measured as unsound.

Decision: do not build. Reopen ONLY with new real-Electron measurement showing a content
signal that warmup.py's sweep missed — that is a desktop-lane experiment (D025), not a
blind code change, and there is no evidence to justify it today.

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

**UPDATE 2026-10-21 (D186, marketplace Bucket-2 — next tier-1 slice, scoped):**
key-rotation + key_id revocation already exist in `trust.py`
(`load_trust_policy`: root-signed key manifest + lineage + monotonic-sequence
anti-rollback + `validate_resigning_provenance`). The marketplace Bucket-1
catalog (`plugins/marketplace.py`) only has an UNSIGNED local digest denylist.
Remaining Bucket-2 work, each its own reviewed slice with tests + D018 mutation:
  1. **Per-bundle (digest) signed revocation.** Extend the root-signed
     revocation doc schema from `{schema_version,generated_at,sequence,revoked}`
     to also allow `revoked_bundles: [{manifest_sha256, revoked_at, reason_code}]`
     (reuse `_REASONS` + the same sequence floor). Return a frozenset of revoked
     digests on `ReleaseTrustPolicy`; `PluginStore.install`/activate refuse a
     bundle whose `manifest_sha256` is revoked. NOTE: the schema-equality checks
     are strict, so this re-signs the pinned trust fixtures — mutation must
     cover the new signature + sequence-floor + schema checks.
  2. **Publisher identity in the signed key manifest.** Add a signed `publisher`
     field to each `ReleaseKey` record so "who signed this" is trustworthy, not
     catalog text; surface it (and existing re-sign provenance) in the catalog.
  3. **Graduated `status`** (active→deprecated→revoked) carried in the signed
     doc, so "blocked" is a signed decision, not an unsigned catalog hint.
Ratings/install-counts stay OUT (require telemetry/egress; rule 6).

**GATE COMPLETE 2026-10-21 (d2cbda5..4bfb635):** anti-rollback sequence floor +
catalog revocation wiring + end-to-end activation test. Full hermetic lane green
at **3589**; independent tier1-reviewer **no BLOCKING** (anti-rollback sound,
signature-before-floor so a corrupt floor cannot admit unsigned docs,
fail-closed, best-effort write cannot weaken the current load, catalog
display-only); D018 mutation 2/2. Two operator-note FOLLOWUPS (local-FS integrity
is the OS's job, not blocking):
  - trust-floor.json lives under the local-user-writable plugin root; deleting
    it resets rollback protection to 0 (OS FS integrity's job).
  - a floor file corrupted to a huge int fail-closes production_store() creation
    (raises) until removed -- acceptable, but a manual-recovery DoS worth an
    operator note.

**SHIPPED 2026-10-21 (6f1c77a): publisher identity in the signed key manifest.**
`ReleaseKey.publisher` (optional, root-signed, <=100 chars, normalised).
Independent tier1-reviewer: no BLOCKING (display/provenance only, grants no
trust, signature-covered, fail-closed when present); its one FOLLOWUP (no test
for the >100 bound) is closed. D018 mutation 2/2 killed. Catalog surfacing of
publisher is a later read-only step. Real-user E2E coverage added in
tests/test_real_user_flows.py (messy input across kit/palette/snippets/todos/
pins/convert/diffs + workspace no-model guards + marketplace revoked-at-install).

**SHIPPED 2026-10-21 (03a7a89 + tests): digest-level signed bundle revocation.**
The root-signed revocation doc now accepts an optional `revoked_bundles`
([{manifest_sha256,revoked_at,reason_code}]), backward-compatible, under the
same root signature + monotonic sequence floor, exposed as
`ReleaseTrustPolicy.revoked_bundle_digests`. Tier-1 gate completed: independent
tier1-reviewer (own worktree) returned **no BLOCKING** (all 5 points confirmed);
D018 mutation sweep **7 mutants, 7 killed**. Two non-blocking review FOLLOWUPS:
(a) digest revocation isn't cross-checked against revoked key_ids / key manifest
(standalone primitive, fine; revisit at the install-time slice); (b) duplicate-
digest check precedes reason/timestamp validation (cosmetic; both reject).
STORE ENFORCEMENT SHIPPED (ffba6ab): `PluginStore.revoked_digests` +
`_install`/`_enable` refuse a revoked `manifest_sha256`. Independent
tier1-reviewer: **no BLOCKING** (fail-closed, additive, verified-digest, same
error class). D018 mutation 2/2 killed.
  Review FOLLOWUP: `load_active_catalog`/`_prospective_plugins` do NOT consult
  `revoked_digests`, so a bundle already in active.json BEFORE revocation stays
  served until a re-enable. MUST be fixed in the wiring slice: when the signed
  revocation doc populates `revoked_digests`, the active-catalog load must also
  drop/refuse revoked digests (not only install/enable).
STILL TODO (platform wiring slice, owner-gated): load the root-signed
revocation list in `platform.production_store()` to populate `revoked_digests`
(+ filter the active catalog per the FOLLOWUP above). Needs a committed
production-signed revocation document -> requires the owner's root private key
(`~/.ghostcursor-keys`); the code path is complete and tested with self-signed
fixtures, only the signed artifact is missing.

**Precondition found 2026-10-21:** `trust.py`'s `load_trust_policy` /
`ReleaseTrustPolicy` is built but **not wired into `PluginStore`/`platform`** —
production verification uses the simpler `trusted_keys.json` pinned public-key
map (`trusted_release_keys()`), and no signed key-manifest/revocation documents
are committed. So Bucket-2 item 1 first requires a reviewed slice that **wires
the signed trust-policy path into the store** (load the root-signed key
manifest + revocation list at catalog admission, replacing/augmenting the flat
key map), and only then extends it with digest revocation. That is a larger
tier-1 integration than a schema change; it does NOT need the owner's root
private key (no production signed docs exist yet; fixtures self-sign), but it
does need its own D162 gate (tests + D018 mutation + independent review).

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

- Research categories (29 Oct) also recognise documentation and release
  paths on a project's own site; a vendor blog or aggregator stays `unknown`.
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

- Island (29 Oct) has Ask, Research, Talk, finished results and full-screen
  step-aside, plus hold-to-talk on the voice hotkey and a Silero VAD gate
  (`docs/evidence/island-ask-2026-10-29.md`). Open: hold-to-talk and the VAD
  gate were checked with Windows TTS recordings fed as frames, not a person
  at a microphone; full-screen hiding was checked
  only in tests and against a windowed desktop, not with a real full-screen
  app; a person typing and pressing Enter is still unchecked; the card shows
  only the first 1500 characters of a job's answer, so long answers point to Work.
- Routine results show claims new since the routine's previous finished run,
  matched locally (rapidfuzz token-set >= 90 and the same numbers). A dropped
  claim is not shown. Sending the prior run to the model, as HeyClicky does,
  is deliberately not built: it would add up to 24,000 characters of egress per
  run for a judgement the local match already makes
  (`docs/evidence/heyclicky-rea-2026-10-28.md`).
- Work has read-only background research and timed hourly/daily/weekly research
  routines on the same worker. Other job types, retries, sleeping-PC service,
  and side-effecting connectors still need their own lifecycle and authority
  design; generic activity history does not imply them.
- Saved research cards can download their bounded answer as Markdown. Edge and
  the frozen app passed an isolated seeded-job trial; fallback-browser download
  and a post-restart result export remain unmeasured. Downloaded Markdown can
  contain untrusted links or HTML from the answer and is never auto-opened.
- Saved-result follow-up and Ask a file pick passages by word overlap
  (`session.relevant`) and send at most 8,000 characters. A question that
  paraphrases the text without sharing its words can miss the passage; a
  local embedding model would fix that.
- Work can keep up to five finished research results ahead of the 20-job trim.
  One packaged Quit returned nonzero after saving Keep, without a captured exit
  value or crash log; seven immediate repeat trials passed Quit and restart.
  Reproduce before attributing a shutdown cause. A hand-edited inbox containing
  more than five pinned rows can exceed the cap on load; normal app writes
  cannot create that state.
- Archived research cards are hidden by default and remain in the same 20-job
  inbox; unkept archived cards can age out. The browser flow does not assert
  that focus moves to the Work stage after archiving a focused card, although
  the reviewer found the fallback in code. An externally edited inbox over
  20 rows can discard an older kept row on load; normal writes stay at 20.
- GitHub has an explicit read-only Work view. A live account, bounded repo
  listing, and empty issues view passed in the packaged UI. An issue-containing
  private-repository acceptance remains unrun; other connectors and any
  GitHub writes require separate reviewed authority and revocation design.
- Work history is a single-writer per-topic file. If multiple app processes
  for one topic become supported, add coordinated persistence and live-run
  ownership before treating the cards as complete history.
- Packaged Chat, Plan, Brain and Work controls, live research and GitHub ran;
  see `docs/evidence/workspace-live-acceptance-2026-10-26.md`. A real packaged
  Teach session remains to be measured under its separate acceptance gate.
- Edge app windows have a minimum width near 500 px; the 460 px dock may be clamped. Check on a real display.
- The default launcher shows a slim topmost island until the user hides it; active work keeps Stop visible. Real primary-edge and emulated left/right-monitor geometry passed, but a physical second display and cross-DPI move remain unmeasured. Check overlap against real Teach targets. The full window remains available from Open.
- Island buttons retain native Tab stops and dialog-key dispatch with owner-drawn surfaces, but physical keyboard and screen-reader use have not been measured. The new package's idle island was captured, while its full tab interactions and cross-DPI movement were not replayed. Quit immediately after Open can still leave an Edge window opening against a stopped local server; close that window if the race matters in daily use.
- The user-level installer now stages and rolls back local updates, but has no signed artifact verification or automatic update feed. App code signing, owner-approved legal terms, and a supported distribution channel remain release gates (`docs/evidence/installer-update-2026-10-28.md`).
- The local first-run guide was checked in Edge at 500 px and links to existing Setup; no novice-user walkthrough or real provider setup completion trial was run (`docs/evidence/first-run-guide-2026-10-28.md`).
- Brain Personal and Setup were captured at 500 px in the view-hierarchy
  study; test Company with a populated knowledge store and a physical screen
  reader before treating that section as fully accepted.
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
- Review of D180: BlockedApps is checked at bind only; a policy pushed mid-session does not unbind a live window.
- Review of D180: the `model_gate` devtool `--endpoint` can point the Ollama client at a remote host; `LOCAL_PROVIDERS` trusts the name, not the address.

## D181 follow-ups

- Handoff export overwrites an existing `<topic>.orbyn-handoff.json` in Downloads; add a suffix if that bites.
- `ws.suggestion` is cleared on the request thread and set on the job thread; the chip can flash stale (benign).
- A received plan in a fresh topic leaves the goal empty, so Teach runs with goal ""; prompt for a goal before Teach.
- `_context` sets `self._used` as a side effect read by `make_plan`; return it instead.
- Pin with a test that a Jev reply missing a memory verdict leaves the candidate unchanged.
- Measure Brain false refusals from `\blog-?ins?\b` (e.g. "prefers Google login") before widening the rule further.

## Live run 16 October 2026 follow-ups (docs/evidence/live-2026-10-16.md)

- ESC tour test (`test_run_threaded`) first-poll gap 1.6-13 s vs 0.75 s, 4/4 runs; trace start-up (C: was full) and re-run on a pre-session commit.
- Plans from an idea reach 19 of 20 steps; one NIM answer was `invalid_output` with Ollama down. Ask for fewer steps or retry once on INVALID_OUTPUT.
- Scrub now masks unbroken 24+ char mixed-case words (`PowerPointPresentationWindowFrame`); measure whether it hurts grounding.
- Short env secrets (`DB_PASSWORD=prod_admin_secret_2024`, under 24 chars) were never masked; needs a key=value rule.
- Brain dedup: a restatement keeps the old origin; a promoted copy leaves the session copy beside it (review of b906949).

## D182 Act / assistant follow-ups (competitive scan 17 Oct 2026; docs/evidence/competitive-scan-2026-10-17.md)

- Jev drive_until: a goal-only single-window loop with typed statuses (done/handed_back/needs_text/blocked/max_steps), built on ModelTeachSession. After the harness is measured.
- Faster offline wake word (sherpa-onnx or openWakeWord) to replace the Whisper loudness loop; measure accuracy + CPU before adding the dependency.
- Claude subscription via the installed `claude` CLI (Dodaios pattern). BUSINESS RISK: breaks Anthropic third-party-login terms, may ban the user's account. Owner decision only; API key path already works.
- Multiplayer takeover + live sync (Amoeba `@coord`): hidden-ref snapshots, three-way apply, cross-machine approval gate. Needs a sync service and a D017 decision.
- Act via UIA invoke/value patterns rather than the mouse: refused twice by a safety classifier as covert-looking. Stays on the visible mouse unless the owner directs otherwise.
- GrayPass idea: confirm who is behind a sensitive Act (not just that the plan was approved) before send/pay/delete.

## Wake word (D185, 17 Oct 2026)

- Pre-warm done: Listener.start() loads tiny.en in the background, moving ~7.8s of cold faster-whisper load off the first "Hey Bro" (warmed decode ~0.7s, measured).
- Still deferred: a streaming keyword spotter (sherpa-onnx) for always-on, sub-second, lower-CPU detection of the custom phrase "Hey Bro". Needs a new dependency + a KWS model download; openWakeWord's pretrained models do not cover a custom phrase. Add on owner's go.

## Act paste_text (tier-1 review of 9e49be1, 18 Oct 2026)
- `act.py` paste_text: fixed 0.2s pre-restore wait is a race for slow apps; gate restore on a paste ack or make the wait configurable. (Non-blocking; ceiling noted in code + evidence.)
- `act.py` get_clipboard_text handles only CF_UNICODETEXT; a non-text prior clipboard (image/files, CF_HDROP/CF_BITMAP) is cleared not restored. Capture/restore those later. (Non-blocking; documented ceiling.)
- Restore-can-itself-raise: FIXED in follow-up commit (best-effort restore, swallow at restore time).

## Wake word KWS install (D185, 18 Oct 2026)
- Streaming KWS install is now built: `py -3.12 -m ghostcursor.listen_kws install` downloads the sherpa-onnx gigaspeech KWS model and writes hey-bro.txt from the model's own BPE (keywords_text). Needs sherpa-onnx + sentencepiece + network on the user's machine; fail-open to Whisper throughout. Orchestration is tested with injected IO; the real download/tokenize is not CI-tested (no model/network in CI).

## Spatial: live region capture for Teach (HeyClicky parity) — 2026-10-18

Orbyn's spatial engine already resolves a REGION mark, not just a point:
`harness/spatial.py::SpatialReference.from_mark(mark: Rect, frame)` scores
candidates by area overlap/containment, and `mark_score` handles a non-zero
`mark_area`. The gap vs HeyClicky's "draw/circle to mark" is only live CAPTURE:
`teach_live.py` grabs `point(*cursor())` (a zero-size rect at the cursor), so a
user can point but not drag a box. Closing it means letting the overlay capture
a mouse drag and feeding the drawn rect to `from_mark` — an interactive UI
feature (needs the overlay to briefly own the mouse + an interactive test lane),
deliberately not rushed into an autonomous run. The ranking/resolution half is
done and tested; only the capture gesture is outstanding.

## Company Brain + readiness-doctor milestone review (D186) — 2026-10-18

Independent tier-2 review of 189b8f7^..7ab8343 (n-hop recall + linked_via
explainability, Markdown export, conflict/aging surfacing, readiness doctor, GUI
wiring). **Verdict: clean, no BLOCKING safety findings.** Four non-blocking items:

### 1. Sensitive facts rode the model-bound retrieval path — RESOLVED 2026-10-18
`recall()`/`context()` applied no sensitivity filter, so a fact marked
`sensitive` flowed into the model envelope (BYOK gateway) while `export_scope`
correctly excluded it. Sending a sensitive fact to a BYOK model is egress off
the device (rule 6). Fixed: `recall(..., include_sensitive=False)` excludes
sensitive facts by default; `context`/`connections` use the safe default and the
owner's own local `/know recall` opts in (`include_sensitive=True`), mirroring
export.

### 2. `doctor._rea()` read `.mcp.json` by a cwd-relative path — RESOLVED 2026-10-18
Readiness flipped with the directory doctor was run from. Now resolved against
the repo root (`Path(__file__).resolve().parents[1]`).

### 3. `retire` flips status but does not erase the row (secure_delete ON)
Retired/sensitive fact text still lives in the DB and the FTS shadow table.
Fine for governance history (states are auditable), but note it is not an erase
if that was ever the intent — `erase_all` is the erase path.

### 4. `connections()` runs a per-frontier-entity `recall()` (O(k·edges) FTS)
Bounded by `k` but repeats FTS queries per bridged entity. Cap/dedupe the
frontier if a scope's edge count grows large.

## Company Brain temporal-layer + relationships-GUI milestone review (D186) — 2026-10-18

Independent tier-2 review of 7ab8343..b9f5a3f (temporal edges, owner expire,
GUI Expire + Relationships panel, expired tags; plus the sensitive-facts and
doctor-path fixes from the prior review). **Verdict: clean, no BLOCKING.**
HTTP/auth boundary, scope isolation, migration idempotency, and expired-edge
exclusion across every model-reachable traversal reader all confirmed. Three
non-blocking items:

### 1. Edges carry no sensitivity classification
A sensitive *relationship* can still reach the model via related()/context(),
even though facts are now filtered (8738f5c). Pre-existing (edges never had a
sensitivity field), but the asymmetry is worth closing: add sensitivity to
edges and exclude sensitive ones from related()/connected()/connections() by
default, mirroring recall(include_sensitive=False).

### 2. expire() also sets last_verified=now
Expiring a fact marks it freshly verified, which is odd next to aging. Harmless
(an expired fact is stale, so aging_among never surfaces it), but expire() need
not touch last_verified.

### 3. expire_edge() has no store-level "no such eid" signal
Returns edge(eid) (None when absent) rather than raising. Console and app.py
both guard with `edge(eid) is None` first, so fine in practice; tighten only if
a caller ever skips that guard.

## Company Brain sensitivity-UI + add-relationship + time-scoped-recall milestone review (D186) — 2026-10-19

Independent tier-2 review of d7824cd..882bc40 (mark fact/edge sensitive post-hoc
+ GUI/console UI; GUI add-relationship form; time-scoped recall `since=`).
**Verdict: clean, no BLOCKING.** Rule 6 confirmed: `since` is ANDed into
recall's existing sensitive/stale/status guard (narrows only, never bypasses);
classify()/classify_edge() take effect immediately on every retrieval path
(plain UPDATE, next read re-reads the row); know_relate files CANDIDATE edges
(no reader walks a candidate, so a new edge can't reach the model before owner
review); know_list/know_edges expose sensitive rows only to the local GUI panel.
Prior review's FOLLOWUP #1 (edges had no sensitivity) is CLOSED by 0b8d8e1.
Three non-blocking items:

### 1. GUI add-link form has no sensitive toggle — RESOLVED 2026-10-19
Added a `private` checkbox to the add-link form; know_relate now carries
`sensitive` so an edge can be born sensitive without a follow-up Private click.

### 2. `/know recall ... since:<days>` silently ignores a malformed token — RESOLVED 2026-10-19
A `since:`-prefixed trailing token with non-digit days now returns
"since: wants a whole number of days, e.g. since:7" instead of folding into the
query text.

### 3. classify()/classify_edge() UPDATE any id with no store-level existence check — RESOLVED 2026-10-19
Both now short-circuit to None when the fid/eid is absent (no pointless UPDATE),
so a direct store caller gets an explicit None signal rather than a silent miss.

## Company Brain source-scoped auto-sensitivity milestone review (D186) — 2026-10-19

Independent tier-2 review of c215ede (private sources mark new facts/edges
sensitive at ingestion; console private-source verbs). **Verdict: clean, no
BLOCKING.** Rule 6 confirmed: `_resolve_sensitivity` only tightens (early-return
on explicit "sensitive"; SENSITIVITIES has no third value, so the only lift is
normal->sensitive, never a downgrade); the two INSERT choke points
(add_candidate, relate) both call the resolver, and ingest()/import_scope()
route through them, so no direct-INSERT path bypasses the gate; pattern and
source are both whitespace-normalized and lowercased, and import_scope's
"shared: " prefix still contains the matched substring; recall/related/
connected/neighbors/export_scope sensitive-exclusion guards untouched.
Driven by REA target #6 (Microsoft Recall / CoreAI, AIContextService.dll):
their ScreenUnderstanding pipeline gates capture at the source
(ExcludeBasedOnAppIdTargetPath, deny-on-unknown sensitivity). Four non-blocking
items:

### 1. GUI has no private-source control — RESOLVED 2026-10-19
Added a private-source input + "Make private" button and a removable list of
current patterns to the GUI Brain panel; `know_private_source` HTTP action
(add/list/remove) backs it. New knowledge from a matching source is now private
from the GUI, not console-only.

### 2. Marking a source does not retroactively tighten facts already ingested from it
`mark_source_sensitive` gates future adds only. A reclassify-existing sweep on
mark would close the window between an earlier ingest and the mark.

### 3. unmark_source_sensitive no-ops on blank; mark raises
Asymmetric: `mark_source_sensitive("  ")` raises ValueError, `unmark` returns
False silently. Make them symmetric for clearer console feedback.

### 4. _resolve_sensitivity re-queries sensitive_sources every add
One SELECT per add_candidate/relate. Cache in memory or JOIN at insert if
ingestion volume ever grows (local single-user, so not now).

## Company Brain deny-on-unknown posture + GUI private-source milestone review (D186) — 2026-10-19

Independent tier-2 review of 3b2f209 (GUI private-source control +
know_private_source action) and e177a7f (deny-on-unknown "private by default"
posture: brain_meta flag, set_private_by_default/private_by_default,
know_private_default action, console /know private-default, GUI checkbox). The
store core c215ede was reviewed clean earlier. **Verdict: clean, no BLOCKING.**
Rule 6 confirmed: `_resolve_sensitivity` still tightens-only (the new
private_by_default branch sits after the explicit-"sensitive" early return, so
it can only raise normal->sensitive, never downgrade); set_private_by_default
is an upsert only, so turning the posture off never retroactively loosens stored
sensitive rows; know_private_source/know_private_default run on the same
token+loopback-authenticated handler as every know_* action and return only a
pattern list and a boolean (no fact/edge text crosses to a model path); the
private_by_default() SELECT on the add_candidate/relate path is consistent with
the store's documented read-without-lock model. Each new guard has a failing-
without-it test. Driven by CoreAI deeper REA (block taxonomy:
CaptureBlockedUnknownSensitivity = deny-on-unknown). Two non-blocking items:

### 1. GUI private-by-default checkbox hydrates inside the source-list fetch
app.html -- if the know_private_source fetch fails, the checkbox stays unchecked
while the posture may be on (display-only, no egress effect). Hydrate it from
its own fetch or show a load error.

### 2. private_by_default() read is unguarded by _lock on the hot ingest path
knowledge.py -- consistent with the existing read pattern but now runs on every
add_candidate/relate. Apply the store's noted "guard reads if contention shows"
upgrade only if throughput ever matters (local single user, so not now).

## Company Brain pre-egress DLP redaction milestone review (D186) — 2026-10-19

Independent review of 8e748d7 (redact.py scrub/rehydrate/audit + redact-by-
default on export_scope/export_markdown). **Verdict: clean, no BLOCKING.** Rule 6
confirmed: audit() and the export `redacted` field carry category names + int
counts only (built purely from redact.audit().items()); the reversible mapping
holding raw originals is local to scrub and discarded by export_scope (not
stored, logged, or rendered); scrub is tighten-only (replaces a matched
substring or leaves a non-Luhn card unchanged, never injects originals into
clean text); sensitive facts/edges still excluded entirely, independent of
redaction; no ReDoS (each recognizer has at most one unbounded quantifier with a
following anchor/literal, no nesting); Luhn gate correct. Driven by REA target #7
(Microsoft Purview / Defender Endpoint DLP, endpointdlp.dll + MipDlp.dll:
regex classification behind Allow/Block blanket policy; MS ships PII classifiers
as policy, not in the client). Three non-blocking items:

### 1. KEY recognizer recall ceiling — RESOLVED 2026-10-19
Before wiring redaction into the live model path, added PEM private-key blocks,
JWTs, and bearer/authorization credentials to the recognizers (ghostcursor/
redact.py; moved to core from workspace so providers may import it without a
layering cycle). Free-text passwords remain the documented residual gap (no
reliable regex). Wired into the gateway egress path in the same milestone.

### 2. Edge predicate is not scrubbed — RESOLVED 2026-10-19
export_scope now scrubs the edge predicate too (same _s() as subject/object/
source), so a predicate carrying free text can't leak on export.

### 3. (rule 8) test pins no-raw-value in the export -- CONFIRMED PRESENT
test_export_redacts_embedded_secrets_before_egress asserts the raw email is
absent from both the exported fact text and that redacted["EMAIL"]==1 (count),
and test_workspace_redact asserts no raw value appears in str(audit). Removing
the scrub call fails these. No action; recorded for the reviewer's open question.

## Live-model egress DLP redaction TIER-1 review (D186) — 2026-10-19

Independent tier-1 review of 6e14a8a (Gateway._outbound scrubs outbound
System-Two text for remote providers; policy.redact_egress gate). **Verdict:
clean, no BLOCKING.** Rule 6 verified: complete() is the only System-Two send
site and plan() + all 6 real callers route through it, so no raw-messages path
survives; _outbound re-runs per provider so a local->remote fallthrough still
scrubs the remote leg; remote/local split fails safe (any provider not in
LOCAL_PROVIDERS is scrubbed); no outbound field bypasses the scrub (schema is
folded into the scrubbed system message; auth header carries only the key);
policy.redact_egress fails ON for unreadable/garbage on a managed machine, off
only when absent; attribution logs digest only. D018 mutation-valid guard test
present. Four non-blocking items:

### 1. System-One/Jev path is a second un-redacted remote egress — RESOLVED 2026-10-19
gateway._system_one now scrubs task/trusted/extra via redact.scrub_tree when
redact_egress is on (observed_data left as-is -- already sanitized by
Tainted.of). Added redact.scrub_tree (recursive string-leaf scrub for one-way
paths). Tests: Jev trusted-context scrubbed-on / raw-off; scrub_tree unit.

### 2. redact_egress captured once at construction, not re-read per request — RESOLVED 2026-10-19
gateway._redact_on() now reads policy.redact_egress() per request; the field no
longer snapshots policy at construction.

### 3. redact_egress field can be set below policy — RESOLVED 2026-10-19
_redact_on() = policy.redact_egress() or self.redact_egress, so policy forces it
on and a caller can only raise it, never lower it. Test pins this.

### 4. Free-text passwords not matched (documented residual gap)
redact.py -- regex recognizers miss "the password is swordfish". Over-redaction-
favouring, but a known false-negative class; needs NER to close.

## Deck planner milestone review (D186) — 2026-10-19

Independent tier-2 review of 402e8bd (SlideLayout/DeckSpec/parse_deck_spec +
plan_deck). **Verdict: clean, no BLOCKING.** Verified: plan_deck grounds via
knowledge.recall(goal, scope) with recall's default include_sensitive=False, so
sensitive facts are structurally excluded from grounding sent to a model (not
merely absent in the test); parse_deck_spec mirrors parse_teach_plan (strict_json
+ _exact + bounded types/lengths + closed SlideLayout enum), no path returns a
DeckSpec from malformed input; DeckSpec/Slide/SlideLayout are frozen data with no
Act/harness import -- inert, no execution authority; the goal in tainted is
scrubbed by Tainted.of and carries no authority. One non-blocking item:

### 1. Goal is placed in both trusted context and tainted — RESOLVED 2026-10-19
plan_deck now passes tainted={}; the user goal rides trusted context only (it is
user-supplied, not screen-observed).

## DeckSpec->Act brief + Jev egress gate review (D186) — 2026-10-19

Independent review of 5b8cf6c. **Verdict: clean, no BLOCKING.** #2 (tier-1, Jev
egress): _system_one scrubs task/trusted/extra via redact.scrub_tree when
redact_egress on, observed_data left (already Tainted.of-sanitized); scrub_tree
reaches nested string leaves, builds fresh structures (frozen envelope
untouched), preserves non-strings; injection_risk intact (screen text rides
observed_data, not scrubbed); System-Two _outbound unchanged. #1 build_brief
inert (no Act/harness import, returns a string). Three non-blocking items:

### 1. extra_state could shadow the observed_data key — RESOLVED 2026-10-19
gateway._system_one now asserts "observed_data_never_instructions" is not in
extra_state before building state, so the sanitized slot cannot be shadowed.

### 2. scrub_tree converts tuples to lists — RESOLVED 2026-10-19
redact.scrub_tree now returns a tuple for tuple input (and a list for list),
preserving the container type.

### 3. Free-text passwords still unmatched (known residual gap)
redact.py -- applies to this egress path too; needs NER to close. Documented.

## Deep research -> Company Brain review (D186) — 2026-10-19

Independent tier-2 review of 8c51a98 (deep_research: decompose -> cited research
per sub-question -> file cited claims to the Brain). **Verdict: clean, no
BLOCKING.** Verified: _file_cited_claims files only SUPPORTED/PARTIAL (cited)
claims (UNRESOLVED/CONTRADICTED skipped); research()'s citation discipline
(parse_claims offered-ids + graph.validate) untouched; filed facts are
CANDIDATES only (never auto-approved; recall excludes candidates, so web content
can't be model-recalled without owner review); provenance = cited page URL;
plan_research adds no new egress channel (reuses gateway.complete + the research
envelope under existing policy gates); planning failure falls back to one pass,
empty question raises, file_to_brain without knowledge/scope is a no-op. Items:

### 1. A cited Source with an empty url filed a blank source — RESOLVED 2026-10-19
_file_cited_claims now requires `source and source.url` before using it, else the
"research" fallback.

### 2. No test that UNRESOLVED/CONTRADICTED claims are not filed — RESOLVED 2026-10-19
Added test_only_cited_claims_are_filed_not_unresolved_or_contradicted: a mixed
supported+unresolved answer files only the supported claim (guards the status
gate per hard-rule 8).

### 3. Filed candidates default to sensitivity "normal"
research.py -- fine today (recall excludes candidates), but when a candidate is
promoted to reviewed/approved it should respect the deny-on-unknown posture /
source-sensitivity rules. Revisit if deep-research filing feeds an auto-promote
path.

## Voice: spoken-number cleanup + on-demand dictation review (D186) — 2026-10-19

Independent review of 771c74b (apply_numbers) + 7a7d9b0 (dictation). **Verdict:
clean, no BLOCKING.** Rule 1 holds: grep of dictation.py/voice.py for
SendInput/keybd_event/mouse/PostMessage/Invoke/paste/clipboard/pywinauto/
send_keys found only the prose comment forbidding synthesis -- no second
synthesis path; test_no_input_synthesis passes. apply_numbers is a pure string
transform on Orbyn's own goal (small bare number-words left as words). /dictate
only saves (file or Brain candidate, status candidate, not auto-usable), never
types into an app. save_transcript writes only under the dictations dir with a
timestamp filename (no path traversal from spoken text). Audio stays in memory;
nothing leaves the device. Two non-blocking items:

### 1. /dictate brain with no Brain fell through to a file silently — RESOLVED 2026-10-19
Now prints "no Company Brain here; saving to a file instead." before the file
save.

### 2. save_transcript no-clobber suffix is unbounded in theory
dictation.py -- bursts >1 capture/second grow -N suffixes; practically
irrelevant (a human triggers each capture). Leave as-is.

## Company Brain episodes review (D186, rec #3) — 2026-10-19

Independent tier-2 review of 34ca7cb (episodes: facts trace to the raw input).
**Verdict: clean, no BLOCKING.** Rule 6 verified: episode/episode_id/
record_episode appear only in knowledge.py + the owner console; recall/related/
neighbors/export_scope/export_markdown/import_scope never read the episodes
table or episode text, so raw input cannot reach a model-bound or export path.
Migration aligned (episode_id appended last in _SCHEMA, ALTER, and the Fact
dataclass, so Fact(*row) stays aligned; pre-episode rows NULL, no crash).
add_candidate INSERT column/value counts match. No auto-approve (episode linkage
keeps status candidate). export/import round-trip unaffected. Two non-blocking:

### 1. episode() reader takes no scope argument
knowledge.py -- returns any episode by eid regardless of scope. Safe today
(owner-only console; episode_of only follows a fact's own episode_id); add a
scope guard if ever exposed beyond the console.

### 2. Episodes have no retention/prune path
knowledge.py -- the episodes table is not reached by expire/retire; raw inputs
accumulate. Add a prune (e.g. drop episodes with no live fact, or an age cap) if
volume ever matters. Local single user, so not now.

## Auto-guide renderer review (D186, rec #1) — 2026-10-19

Independent tier-2 review of the guide.py commit. **Verdict: clean, no
BLOCKING.** Inert data (imports only redact; no Act/harness/synthesis; returns a
string, executes nothing). Rule 6 on the share path: title + instruction + text
all routed through redact.scrub when redact_pii=True; the action-phrasing line
uses the already-scrubbed text; no field bypasses. Default is redact_pii=True
(verbatim only on explicit False). Empty plan raises; text/action via getattr
defaults. One non-blocking item:

### 1. _step_line reads step.instruction directly (not getattr)
guide.py -- a duck-typed step lacking `instruction` would AttributeError instead
of a clean message. Real TeachPlan always has it; robustness only.

## Record->skill review (D186, rec #2) — 2026-10-19

Independent tier-2 review of task_skills.py. **Verdict: clean, no BLOCKING.** No
execution authority (serialize/deserialize only; no Act/harness import, runs
nothing). load_skill is the only TeachPlan construction path and routes through
the closed parse_teach_plan, so a hand-edited out-of-schema / unknown-action /
too-many-steps skill is refused (ProviderError) rather than replayed -- no
bypass. _slug maps to [a-z0-9-] only, so no name can traverse out of the skills
dir ("../../etc/x" -> "etc-x"); an all-punctuation name raises. Saved JSON holds
only the four TeachPlan fields. Two non-blocking:

### 1. step.text persisted in cleartext
task_skills.py -- a typed/pasted value (possibly a secret) is saved to the skill
JSON in cleartext. Fine on the owner's machine (local file, not egress); apply
DLP/Tainted if skills ever sync or are shared.

### 2. list_skills is lossy (slug collisions)
task_skills.py -- two distinct names can slug to the same file and silently
overwrite; list returns slugs, not original names. Fine for MVP; store the
original name if it must round-trip.

## One-step task router (/do) review (D186) — 2026-10-20

Independent tier-2 review of 1fcfd4b (Workspace.do + _plan_for + /do). **Verdict:
clean, no BLOCKING, no FOLLOWUPS.** Rule 2 verified: the "plan" intent only
builds a plan (_plan_for -> gateway.plan, a closed-schema completion) and
_propose()s it, returning text that points the user at /teach or /act -- no call
into harness/act, teach runtime, or input synthesis anywhere in do()/_plan_for;
/do never executes. parse_intent is strict/closed (enum + bounded arg,
INVALID_OUTPUT otherwise); a model failure falls back to discuss() (no crash, no
guessed action). Dispatched capabilities are the already-reviewed ones;
"remember" files a CANDIDATE, not auto-approved. _plan_for builds from the passed
need (not self.goal), returns None on failure. Rule 6: the classify call goes
through gateway.complete -> _outbound egress scrub; no new channel. Guards have
tests (plan-stays-approvable, chat fallback).

## Local file converter review (D186) — 2026-10-20

Independent review of 62d750c (convert.py, Open-Tangerine core). **Verdict:
clean, no BLOCKING.** No shell injection (subprocess list argv, no shell=True,
target allowlisted before run); no path traversal (output = src.stem +
allowlisted ext, never from content); local only (no network); FFmpeg-absent ->
clear RuntimeError; /convert surfaces errors as a message; no harness/act import
(rules 1-5 unaffected). Items (#1/#2 fixed now):

### 1. lstrip(".") stripped a char set, not a prefix — RESOLVED 2026-10-20
Replaced the three `to.lower().lstrip(".")` with `.removeprefix(".")`.

### 2. "gif" was in both _IMAGE and _MEDIA (video->gif unreachable via convert) — RESOLVED 2026-10-20
Dropped "gif" from _MEDIA; gif is an image target (router -> Pillow). A video->gif
still works by calling convert_media directly if ever needed.

### 3. /convert parsing is brittle (trailing space / embedded quotes) — RESOLVED 2026-10-21
`rest.strip().rsplit(None, 1)` now splits the format off the last whitespace
token (so a spaced path works) and strips surrounding `"`/`'` from the source.

## /deck build -- DeckSpec -> Act build (c561bed) -- tier-1 review clean, no BLOCKING
build_deck proposes a plan to build a reviewed DeckSpec in PowerPoint; the user
runs /act. Verified: no input synthesis, no new authority, never auto-acts, no
model-supplied geometry, no new egress; act.py/act_runtime not in the diff.
Both items below are pre-existing patterns, not introduced by this commit.

### 1. _plan_for puts build_brief (model/Brain-derived) text in trusted, not tainted — RESOLVED 2026-10-29
build_deck now sends a fixed trusted goal; the DeckSpec outline rides the
tainted channel, DLP-scrubbed (`tainted_chunks`, shared with Ask). Same
sweep moved research/Brain deck grounding and the critic's plan steps to
tainted (29 Oct). Open from its review (no BLOCKING): crew and router args
are model-written from the user's text and become trusted goals -- keep it
that way, or route them through tainted if research ever shapes them; a deck
outline over 8,000 chars is cut (the proposal now says so, and the plan may
miss later slides; chunking into several build plans is the upgrade), and
`sanitize` collapses its newlines so slides rest on the "Slide N" markers.
Review of 25755e4 (no BLOCKING): the OBSERVED_DATA label said "read from the
user's screen" although web claims, Brain facts and plan steps use it (RESOLVED
2026-10-29: it now says screen, files, the web or saved notes); the critic now judges
plan steps it is told are never instructions -- critique quality was not
re-checked against a live model; deck grounding is bounded (subquestions x 8
claims) but not capped, and overflow fails closed; `agents.dry_run` still puts
a model-drafted agent goal (drafted with Brain context, user-reviewed before
save) in trusted `goal`.
session.py:~841 -- shared with draft_skill + the one-step router. The DeckSpec
text becomes the plan goal via the trusted channel. Confirm grounding provenance
stays scrubbed; not a rule-6 egress change here.

### 2. /deck build topic parse couples to the ["build"] guard
__main__.py -- rest.split(maxsplit=1)[1] is safe only because the guard implies
>=1 token; a bare "/deck build" falls through to the goal-based deck (intended).

## Act guards from the Aside teardown -- 2026-10-29

`docs/evidence/aside-rea-2026-10-29.md`. Taken: `act.blocker` refuses a point
whose top-level window belongs to another process (covered or off screen),
and `chord_events` refuses the Windows key and Alt+Tab. Open:

- Aside yields when the user is using the mouse or keyboard ("the next action
  waits for their pause"). Orbyn has ESC but no yield. Tried 29 Oct with
  `GetLastInputInfo` and dropped: on the owner's machine the idle time never
  passed 0.25 s across 2.5 s of sampling (some device or service reports input
  every few tens of ms), so a 0.3 s pause gate would refuse almost every step.
  A yield needs a low-level hook that counts only real key presses and button
  clicks (skipping `LLMHF_INJECTED` and bare mouse moves), on its own thread.
  Partly done 29 Oct (`docs/evidence/aside-computer-use-rea-2026-10-29.md`):
  Orbyn's events carry an "ORBN" `dwExtraInfo` signature, and Act waits up to
  0.4 s while any key or mouse button is held, then retries next tick. Still
  open: Aside's 2 s recent-input window, which needs a native low-level hook
  (a Python hook callback risks system-wide pointer lag).
  Review of 436d779 (two BLOCKING, fixed: the scan read ESC and so cleared the
  "pressed since last call" bit the session's ESC poll needs to catch a tap,
  and the 0.4 s wait sat on top of the 0.15 s focus pause and the 0.2 s
  paste wait, about 0.75 s before Stop was seen; ESC is no longer read and
  the wait is 0.1 s, with a whole-step budget test). Open from it: the retry
  has no cap, so a key that reads as stuck down (remote session, ghost key,
  pedal) leaves the step "waiting" until `--seconds` -- block with a reason
  after N tries; the scan covers every VK including X-buttons and VK_PACKET,
  and does not ignore keys already down at approval; the drive path ends on
  `UserBusy` instead of retrying; no test that a retry tick re-resolves a
  control that moved; the "ORBN" signature only labels input -- any process
  can set `dwExtraInfo`, so it is never an authority check.
  Re-check of b75e127: no BLOCKING. Open: the 0.5 s budget test fakes the
  clipboard, so `_open_clipboard`'s real retries (up to 4 x 0.02 s, three
  opens per `paste_text`) can push a contended paste to about 0.69 s; this
  overrun predates the held-key wait (0.35 + 0.24 s) but the wait uses the
  margin. Count or cut those retries during a paste, and time a real
  `perform` on a desktop lane (only sleeps are counted today).
- Focus is re-checked once after the click, before a step's keys (29 Oct);
  Aside re-checks between keys of a long `typeText`. Orbyn sends a step's keys
  in one `SendInput` batch, so a focus steal mid-batch is still possible.
- Review of d0f3e5a (three BLOCKING, fixed in the next commit): the chord
  guard now judges key codes after the same strip/casefold `vk_of` uses
  (tabs and no-break spaces slipped past), single-character keys are ASCII
  only (`"ª"` was VK_BROWSER_SEARCH), and the covered check accepts
  only the bound window, windows it owns, or a `#32768` menu on its thread
  (a second presentation of the same app no longer passes). Open from that
  review: `perform(window=None)` skips the check silently (make it required);
  the `run_model_teach` closure and the drive lookup have no direct test; a
  missing label surfaces as a bare KeyError; alt+f4, f1 and ctrl+alt+arrows
  are allowed; a closed bound HWND reused by another process is not caught
  (pin the bound PID at bind time).
  Re-check of 0047647: no BLOCKING; an owned window from another process
  (some hosted or COM dialogs) is accepted -- add a same-process check if
  no real dialog needs it.

## Aside full teardown: what was added and what is open -- 2026-10-29

Added: fake role tags and envelope markers in tainted text are replaced
(`envelope.neutralize`); Chat folds turns that leave the history window into
an in-memory checkpoint summary; a weekdays routine cadence. Open:

- The checkpoint is in memory only, so after a restart the first long chat
  rebuilds it from the newest 3,000 tokens of the dropped turns; older ones
  are lost then. Persist it beside the brief if that bites.
- `neutralize` also replaces harmless tags that start with a role word
  (`<username>`, `<toolbar>`); fine for model input, visible in "Sent N
  characters".
- Not taken from Aside: Context Awareness (an always-on capture of the user's
  activity, summarised per window into a journal) needs an owner decision on
  an observation path (rule 6, sessions.sqlite); proactivity mode mines
  password vaults, cookies and history; final-confirm review drafts are for
  sending messages Orbyn cannot send; per-app tips are macOS bundle ids only.
- Review of 487675d..40bc409 (one BLOCKING, fixed: the fake-tag regex was
  quadratic on "<" + a long whitespace run and held the GIL past the 0.5 s
  Stop; every quantifier is now bounded and a 50k-character timing test pins
  it; soft hyphen / U+2060-2064 / U+180E are stripped; mixed-case
  `Trusted_Context` and `x_TRUSTED_CONTEXT` are caught). Open from it:
  Cyrillic look-alikes (`<ѕystem>`) still pass; `sanitize` now neutralises
  on-device text too (handoff `type` text such as `<user>`, and candidate
  names in `build_frame`), so only the sent copy should be neutralised;
  `tainted_chunks` runs on material with no size cap ahead of it; no property
  test pins `Tainted`'s scrub-idempotence over tag-heavy text; the chat
  checkpoint adds one model round-trip every tenth dropped turn and after a
  restart marks all dropped turns covered while summarising only the newest
  3,000 tokens; `weekdays` and `daily` drift an hour across DST; for
  `paste_text` the clipboard is set after the focus check, so a focus steal
  between check and Ctrl+V still pastes into the wrong window.
- Re-check of d7675b1 (no BLOCKING; the fake-tag scan timed linear on 50k
  hostile inputs in the reviewer's ad hoc probe). Fixed after it: `sanitize`
  collapsed whitespace after `neutralize`, so `"<" + 12 spaces + "system>"`
  came out as a live `< system>`; it now collapses first. Open: the older
  `scrub()` is quadratic on one long alphanumeric run (reviewer measured
  1.35 s at 20k characters; `_TOKEN`/`_MIXED`/`_SECRET` lookaheads). Today
  `Tainted.of` truncates to 300 first and `tainted_chunks` callers pass at
  most 8,000, but bound it before any caller passes more. "Ask Orbyn about
  this file": a second offer replaces one the page has not taken yet, with
  no notice; an offer accepted by an instance that is quitting is never
  opened.
- Review of 8f8e092 (empty chord parts refused): `_VK` has no `plus`/`minus` names, so zoom chords such as Ctrl+Plus cannot be written; add named keys if plans need them.
- Review of 8f8e092: `keys` text is not checked when a plan is parsed (`providers/schemas.py` PlanStep), so a bad chord stops the run after approval; check chords at plan time instead.

## Whole-tree review, 2026-10-29 -- status 2026-10-30

Fixed: d8bf30d, c590c9d, 2b6348e (first pass); 915277d (signed path), c8f7f6e
and 39e334c (harness Act), 3d8cc8b (Teach, perception, providers), c5d0d3c
(workspace), d17b543 (tools). Tier-1 review of 5fd3722..c8f7f6e: no BLOCKING.
D018: 19/19, then 4/4. Hermetic lane 3804 passed. Desktop lanes not run.

Still open (needs a live desktop session or an owner decision):
- `harness/act.py` `_on_bound_window`: unowned top-level popups of the same app (Office galleries, WPF Popup, Chromium select) are refused as "covered"; measure their window classes on the desktop, then accept same-thread popups if real.
- `harness/act.py` surrogate-pair typing is unit-tested only; try one emoji in Notepad and PowerPoint on the interactive lane.
- `tools/render_acceptance_evidence.py:79-80`: extra failed runs are accepted beside three passes. Owner to confirm the Task 8 rule; the pinned evidence includes earlier failed attempts, so changing it moves that document.
- `devtools/paint_budget.py:107`: budget_ms truncates microseconds before the ceiling. Left alone because the rendered evidence is pinned.

Closed without a change:
- `devtools/receipt_budget.py` cues_measured: counts the cues that travelled; the first cue is reported separately (settled_*), and the pinned runs (59/60) and the renderer's checks rely on that.
- `providers/envelope.py` tainted_chunks newline collapse: `last_sent` shows exactly the text that left, which is the intent.

From the tier-1 review of 5fd3722..c8f7f6e (not blocking):
- `harness/teach_live.py`: during one or two missed reads, Act can still act on a kept frame up to MAX_FRAME_AGE_S old; expose the miss count to the session and refuse Act while it is non-zero.
- `harness/act.py` restore: a copy the user makes in the 0.2 s before the restore is overwritten; skip the restore if GetClipboardSequenceNumber changed since our set.
- `harness/act.py` `_quietly`: a locked clipboard at restore time leaves Orbyn's text with no message; retry or report it.
- `harness/act.py` set_clipboard_text: no opt-out from Windows clipboard history / cloud sync (ExcludeClipboardContentFromMonitorProcessing, CanIncludeInClipboardHistory=0).
- `harness/act.py`: restore puts back CF_UNICODETEXT only; HTML/RTF of a rich copy is lost.
- `harness/act.py`: the join on a pending restore is unreachable within a step today (ACT_SETTLE_S=2.0); no test pins that.
- `harness/teach.py`: no test fails if `slot.cancel()` in `_advance` or the `chosen` capture in the verify lambda is removed.
- `harness/browser.py`: a parent Chrome that already exited leaves its children holding the profile.
- `harness/act.py` get_clipboard_text's non-text refusal (CountClipboardFormats) is only exercised live; no hermetic test reaches win32clipboard.

## Small-company deployment (D187), tier-1 review of b4783c0..ebde852 -- 2026-11-03

No BLOCKING. Fixed in the follow-up commit: skills/agents scrubbed on publish,
exact local-host check for CompanyEndpoint, DisableAct re-checked at execute
and before Teach asks to approve Act, an unverified team.json sequence can no
longer crash publish.

Resolved (owner chose a per-user opt-in): the company gateway is used only
after the person turns it on (`settings.company_gateway`); D187 addendum.

Also fixed (2026-11-03, second pass): browser Page actions check DisableAct and the
app lists; the signed path checks AllowedApps/BlockedApps at approval; audit
writes go through a writer thread with a cross-process file lock (record()
never waits on disk); ShareAudit's user names are documented in the admin
guide; re-syncing the same bundle is tested; sketch.start(latest=) places
marks on the newest frame; `team report` is the owner's view of shared logs.

Third pass: Page knows its browser (Browser.launch passes it), Act steps take the bound executable instead of identify() on the tick, the D183 Act-run line now goes to audit.py, and Teach can draw steps as sketches (--sketch).

Second tier-1 review (12c7116..adbbcb1): no BLOCKING. Fixed: a test that record() returns while the disk is stuck; bounded queue with full/exit losses counted in `dropped`; verify waits only for lines queued to its own file and rejects non-object lines; `team report` survives corrupt logs; one frame per tick for Teach and its sketch; AllowedApps/BlockedApps re-checked when a signed run starts. Left: a Page built without `executable` (only outside Browser.page) is refused only when both browsers are denied.

Open:
- `audit.py`: tail truncation is undetectable (no anchor); a periodic signed checkpoint would close it.
- `team.py`: a synced `team-<name>` skill overwrites a local skill a user named `team-...` (accepted: the prefix is reserved for the team).

## Dictation typing (D188), tier-1 review of 9b4f0aa..7648ce8 -- 2026-11-05

One BLOCKING, fixed in the follow-up commit: ESC pressed during the window
read after the countdown did not stop typing; `type_into` now checks ESC once
more right before `perform`. Also fixed: `type_focused` refuses any
non-printable character in act.py itself (not just line breaks); the console
names the app and field type before typing; a slow read says so.

Open:
- [ ] `type_focused` types over a selection in the field without asking
      (rule 2 asks before overwrite). Check TextPattern selection, or accept
      and say so in D188.
- [ ] The target is the window in front when the countdown ends, not the
      one clicked; tracking the last click would be stricter.
- [ ] `/dictate type` reads UIA on the console thread. Fine for the CLI; a
      workspace-app or hotkey version must move the read to a worker (rule 5).
- [ ] Teach's minimized hold applies to any minimized bound window, even one
      the step does not use (marked `ponytail:` in teach.py).

## D189-D191 tier-1 review of 915a0c7..bc20832 -- 2026-11-05

No BLOCKING (reviewer ran hermetic on bc20832: 3961 passed). Fixed in the
follow-up commit: freehand strokes clamp to 40 px outside the control (a big
pane is not a canvas); agent notes enter the conversation as the user's
words; a main-thread crash waits at most 2 s to send; install() tested.

Open:
- [ ] SAPI Speak runs on the Teach loop thread; a first call can block while
      the audio device starts. Give Speaker its own thread (D020 budget).
- [ ] Stop lands only between crew steps; pass `cancelled` through
      `_run_intent` so a crew's research/deck step stops mid-way too.
- [ ] A background crew's plan step replaces the current plan without saying
      so in the UI (Act still re-asks approval).
- [ ] No test pins the 4-redirect limit on the ICS fetch, or that an IMAP
      password never appears in an error message.

## HeyClicky UI pass and resilience sweep -- 2026-11-11/12

Three tier-1 reviews (9ecc270..eab0a49; af58006; 8b3885b..1053b54). One
blocking finding (empty-host redirect reached this machine's own services),
fixed in 8b3885b. Closed since: DNS rebinding (af58006, a6cfcd7), CI SHA
pins and no persisted token (1053b54), PyWin32 found in the system site for
the verified adapter boot (7abb41c, 9ece5b8). Hermetic CI green on Windows
from 1053b54. Still open:

- Closed 12 November: the cursor companion (`workspace/companion.py`)
  shows Listening / Thinking / the activity beside the OS pointer while
  Orbyn is busy or listening (D018 13/13); routine failure counts are saved
  with the routine (7/7); 6to4 is judged by its relayed IPv4 (2/2); a failed
  DLL directory closes the earlier handles (2/2).
- Resting dot with idle blink: opt-in, settings.json "companion_idle": true
  (13 November, D018 7/7). Not taken: Speaking (the workspace process never
  speaks; SAPI speech is in Teach live only). Switch: Brain › Setup.
- Tier-1 review 12 Nov (c4bd639..6051fe0): no blocking findings; fixed in
  0208c14. Left: the rule-3 companion test is a source-string check
  (documentation, not a guard); the badge stays while busy even after the
  user hides the island (intended: work stays visible).
- Tier-1 review 13 Nov (6051fe0..47f6f6b): no blocking findings. Fixed:
  settings writes under one lock (a concurrent switch could lose the D179
  vision value); no orphan badge if the bar fails to create; idle() timing
  tests; the timer repaints only when the dot changes and skips monitor
  lookups while the pointer is still. Resting-dot CPU, measured 13 Nov in a
  20 s session run (terminal only, not a captured file): about 0.9% of one
  core, against 0.16% for a bare 30 ms sleep loop and 1.2% before the
  repaint change. Left: a modal loop (MessageBox, menu) in a bar handler
  still holds the main loop, as before.
- EGM pass 13 Nov (Elephant-Goldfish Model plugin, egm@egm 0.1.1): drift
  report `docs/evidence/2026-11-13_DRIFT_REPORT.md` closed in 059a06c and
  5c995df; Goldfish design_critic and codebase_details reviews of the new
  FLOW sections found no blockers, and their code points were fixed (capture
  exclusion failure hides the badge; page fetch byte cap, one deadline,
  default ports, no https->http; 100 ms resting-dot pump). Left: a page fetch tries only
  the first checked address; EGM reviewers ran as general-purpose agents
  reading EGM personas, since its registered adapters (omitClaudeMd) load
  only in a new session.
- Tier-1 review 13 Nov (deef941..eb4f4f5): no blocking findings. Fixed:
  page fetches ask for identity encoding and refuse a compressed body (a
  stacked gzip could inflate past the cap); each hop's timeout is the time
  left; idle() steps are bounded by the time left; timing tests use a fake
  clock (two were flaky under load). Left: deep research files claims to the
  Brain (D190, owner decision) -- the rule-6 check of what reaches the
  Company Brain (knowledge.sqlite; the review called it kb.sqlite) was done 13 Nov (see the Modern Web Guidance entry below): no gap.
- `ghostcursor.__version__` is still 0.1.0; bump it when a release is cut.
- Native UI polish 13 Nov: the bar's text was the bitmap System font (WM_PAINT
  and the owner-drawn buttons never selected Segoe UI); its corners were a
  1-bit region and its buttons GDI RoundRect, both stair-stepped; the badge
  was colour-keyed (hard edges only); nothing scaled with DPI (125% here).
  Now: Segoe UI ClearType, Pillow 4x box-averaged shapes (GDI HALFTONE left a
  dark fringe), DWM rounded corners on Windows 11, a per-pixel-alpha badge via
  UpdateLayeredWindow inside WM_PAINT, all sizes scaled by the system DPI.
  Later 13 Nov: the bar handles WM_DPICHANGED (fonts, size, layout) and the
  badge takes the pointer monitor's scaling and the pointer-size setting.
  14 Nov: with no badge showing the bar handled input only at the 4 Hz tick
  (idle slept the whole 0.25 s); idle now waits on the message queue and
  answers at once, each wait bounded by the time left. Also: button hover
  states, one amber action, badge shadow, halo and glide, reply scrollbar
  only on overflow. Left: the scrollbar, when shown, is the stock dark one; a
  pointer-size change while Orbyn runs is picked up at the next start; the
  resting dot's CPU cost was not re-measured over a session.
- Brain audit 14 Nov (the Company Brain driven through the real page):
  the Add box and the link form accepted the same fact or link again (now
  an exact-match repeat returns the existing one; a near match is kept, as
  it may be a correction); one fact had no length limit (now 2,000
  characters, links 200 per part); a failed add cleared what was typed;
  Enter did nothing in the Brain inputs; an unbroken long fact pushed the
  page sideways; a non-text value or a null id gave a 500. Rows now show a
  status chip and dim retired facts. `tools/smoke_build.py` checks the
  packaged exe with throwaway data. Left: Export overwrites the previous
  export in Downloads; documents still enter the Company Brain only through
  /know in the console.
- Personal Brain audit 14 Nov: a card number written with spaces or dashes
  (and an SSN) was stored as a lasting memory, and memories are context for
  the model; eligibility now refuses anything redact.SECRETS recognises. An
  IBAN written in groups of four was not recognised anywhere; redact now
  has that form. RESOLVED same day: a superseded memory can no longer be
  corrected back to life, and a memory stored before the rule that today's
  rule would refuse is never handed to the model (it stays in the panel so
  it can be forgotten; it is not deleted).
- Enterprise privacy audit 14 Nov (cloud model, data stays in-house). Two
  gaps closed: (1) scrubbing private details before a remote model was
  reachable only through the RedactEgress registry policy; the person now
  has their own switch (settings "redact_egress"), which can add to policy
  and never lower it. (2) AllowedProviders did not cover research web
  search, so a machine pinned to the company model still sent the question
  to Tavily/DuckDuckGo; search now asks policy.allows(provider). Left, by
  design or not built: the scrub is pattern-based (no names of people,
  companies, projects, no free-text addresses); replies are not rehydrated,
  so placeholders show in answers; the company gateway counts as remote and
  is scrubbed too; redaction is off by default; research still fetches the
  result pages it found (URLs only, no user text); no count of redactions
  in the audit log.
- Tier-1 review 14 Nov (d4fe6bb..555df5b): one BLOCKING finding (rule 7),
  fixed: the receipt showed "nothing to hide" for a request sent with
  hiding switched off, because an empty map meant both "found nothing" and
  "did not run". The log now records `scrubbed`, and the page says "sent
  without hiding private details" or "stayed on this computer". Also fixed
  from it: a locked memory is never superseded or written back as text; a
  plain row starting "DP1:" is sealed (LIKE ignored case); an error or
  sign-in page is not returned as the page; NUL stripped; `at` typed. Left:
  a failed DPAPI call during the sealing migration stops the Brain opening;
  read_link runs outside the worker (not stoppable for up to 20 s, not
  refused while busy); an email or phone number in a typed address is sent
  to that site; the receipt reads the whole log file per click; no
  action-level test for a non-default port.
- Privacy-first pass 14 Nov (after dark.ai's stated aims and Agent-Reach's
  read-only reach). Built: Personal Brain text sealed with DPAPI (old plain
  rows sealed on open; a memory this account cannot open is listed as
  locked and never sent); a receipt in Setup of the last 20 model requests
  with a count of hidden details, no content; "Ask a link" -- one https
  page the person names, fetched directly through research.fetch_public,
  gated by policy.allows("web"), read-only. Left: Company Brain
  (knowledge.sqlite, FTS5) and kb.sqlite are not sealed at rest; the Jev
  channel records no hidden count; a DPAPI-sealed Brain does not roam to
  another computer or account (by design; no export-with-passphrase yet);
  Ask a link reads html and plain text only (no PDF, video subtitles or
  sign-in pages); the receipt does not list web page reads or searches.
- Tier-1 review 14 Nov (dfe1fd1): no blocking finding. Fixed from it: the
  default scrub rewrote about a quarter of picture reference ids sent to
  Jev (reviewer's probe, 20,000 uuid4), so the D179 picture choice failed
  soft; the ids are now kept. Placeholder avoidance is one regex pass.
  Left: a hidden key or card number the model echoes is put back like any
  other original and can reach text Act types (same reach as redaction
  off; Act still asks before risky controls) -- decide whether SECRETS
  categories should stay as placeholders in answers; the handoff export
  uses the lighter envelope scrub; `request_sha256` is over the unscrubbed
  envelope; a put-back value can push a field past its schema limit (the
  provider is then skipped); no direct test with a newline or non-BMP
  original, or for a fresh map per provider attempt.
- Owner decision 14 Nov 2026: hiding private details from cloud models is
  ON by default (settings "redact_egress" is on unless explicitly false; a
  damaged settings file reads as on), and originals are put back into a
  System-Two answer on this computer (JSON-escaped, one placeholder map per
  request, never reusing a placeholder already present in the text). Left:
  a detail scrubbed earlier (attached file, screen text) has no original in
  the map and still shows as a placeholder; Teach accuracy with scrubbed
  Jev context (dates read as phone numbers) is not measured.
- Tier-1 review 14 Nov (e78f494): no blocking finding. Fixed from it: with
  redaction on, observed data bound for Jev is now scrubbed too (Tainted.of
  alone let "10.0.0.5" and a short phone number through, probed by the
  reviewer); a research question is scrubbed before any web search, as a
  background job's already was. Left: Jev `questions` are not scrubbed (no
  caller puts user or screen text there today); the PHONE pattern turns ISO
  dates into placeholders when redaction is on; a Tavily key plus an
  allow-list naming only duckduckgo blocks search instead of falling back;
  an unreadable settings.json reads as switch off; a company gateway on
  127.0.0.1 is scrubbed like a remote one.
- Tier-1 review 14 Nov (45f1728..2f404af): no blocking finding. Done from
  it: one shared refusal rule for storing and for sending a memory, a test
  for each half, malformed Teach/Act steps pinned as refused, and `true` no
  longer accepted as memory #1 by forget/correct. Left: the Brain panel
  does not mark a memory that is withheld from the model; the console
  export writes withheld memories to the file the person names.
- Work page 14 Nov: "Ask a file" passed its click event as the offered
  file (sheet showed "File: undefined", no chooser, every ask failed);
  fixed. A sweep of malformed bodies over every local action now returns
  only 200/400 (ids went through bare int()). Not swept with real input:
  actions that reach a model, the microphone or Credential Manager.
- Tier-1 review 14 Nov (fb24b3e..9e2ad27): one BLOCKING finding, fixed: a
  link added again with Private ticked returned the existing normal link,
  dropping the mark. A repeat (link, typed fact, ingested passage) now
  tightens the one already there when this arrival is private, and never
  loosens. Also fixed: the smoke test drops ORBYN_* path overrides; an IBAN
  whose last groups run together; the page checks the 100,000-character
  limit before sending. Left: SQLite lower() is ASCII-only, so links that
  differ only in non-ASCII case are not merged; the spaced IBAN form does
  not cover lowercase or hyphen/tab separators.
- Tier-1 review 14 Nov (014ee08): no blocking findings. Fixed: the hover
  check in idle() no longer raises when the pointer cannot be read (UAC,
  lock screen) and is skipped once the bar closes; a refused message wait
  falls back to a short sleep. Left: dragging the bar enters Windows' modal
  move loop, so tick() stalls for the drag (Stop and ESC do not depend on
  tick); the badge render result is cached by (text, radius, scale) only up
  to 64 entries.
- Modern Web Guidance pass 13 Nov (GoogleChrome/modern-web-guidance 1.0.0,
  run from the npm package with DISABLE_TELEMETRY=1: its CLI otherwise sends
  search queries to Google). legacy-scan of ghostcursor/workspace found 11
  items in app.html; fixed: the sheet is a native modal <dialog closedby=any>
  (inert page, focus containment, Esc; no role/aria-modal by hand); Enter
  handlers skip an IME-composing Enter; the composer uses field-sizing instead
  of a scrollHeight script; standard scrollbar-color/width; the theme is set
  in <head> before first paint with <meta color-scheme> in sync. The 4 left
  are the scanner not seeing through the imeEnter() helper. New hermetic
  test parses the page's scripts with node --check (skips without Node).
  The browser's blocking confirm/prompt boxes (11 uses) are now one native
  modal (ask/askConfirm/askText): a confirmation starts on Cancel, the
  destructive button is red and named for the action, Enter submits a field
  through its form (IME-safe), Esc still stops a running session. The theme
  toggle follows the guide's two-state model: no saved value follows Windows
  (live), toggling to what Windows already uses clears the override, and a
  saved override survives Windows switching to match it.
- Brain rule-6 check 13 Nov: every Company Brain write (deep research,
  /research remember, clipboard, notes, know_add, folder ingest, team sync,
  snapshot import) lands as a candidate; recall to a model returns only
  usable, non-sensitive facts (edges too) wrapped in Tainted.of; the team
  bundle exports usable, non-sensitive, scrubbed facts. Personal memories
  refuse secret-looking text and reach the model only through Tainted.of.
  No perception or screen text writes to either store (knowledge.sqlite,
  brain.sqlite; screen observations live in kb.sqlite). Fixed the same day:
  every knowledge.sqlite write (candidate text and source, episode, edge,
  ingest dedup) scrubs credentials and card/ID numbers (redact.SECRETS) so a
  pasted key never rests on disk; contact details stay, as company facts,
  and are scrubbed on egress. Jobs, routines, agent notes and handoffs
  already scrubbed on write. Known ceiling: redact is regex, so a free-text
  password ("the password is swordfish") is not caught.
- Private words 14 Nov (tier 1, what leaves): a person's list (settings
  "private_terms") and an organisation's (policy PrivateTerms, which also
  forces hiding on) are swapped for [NAME_n] before a cloud model, Jev or a
  web search, whole word, any capitals, and put back into a System-Two
  answer. Setup shows "See what a model would get" (local preview, nothing
  sent). The receipt now lists web searches and page reads from the audit
  log. A failed DPAPI seal during migration no longer stops the Brain
  opening. Mutation sweep: 19 of 20 killed; the survivor (dropping the
  `event == "egress"` check in the receipt) is equivalent today because
  only egress events carry a provider. Left: the word list is plain text in
  settings.json; a web search for a private word searches the placeholder,
  so finds nothing useful; a word that is also a control name is hidden
  from Jev's view of that control; no stemming (plural or possessive forms
  with a letter attached are not matched); Teach accuracy with words hidden
  is unmeasured.
- Tier-1 review 14 Nov (c2ea2b6): three BLOCKING findings, all fixed: a
  two-word private word cut across two chunks of attached material left
  in full (the words are now taken out before the split); a word holding
  or spanning a line break, backslash or quote was missed in a System-Two
  message because that text is JSON (the pattern now reads both forms); a
  word touching a digit or underscore (Acme_Plan.pptx, Acme2026) was not
  hidden (the edge of a word is now any non-letter). Also fixed: each list
  keeps its own 200 limit; the preview says when hiding is off; a failed
  page read is recorded as failed. Mutation recheck 11 of 11 killed. Left
  from the review: a put-back word that spanned a line break shows the
  JSON form of the break; terms are not Unicode-normalised (a combining
  accent, a compatibility character); the 300-character cut of one screen
  value can leave the start of a listed word; Jev `questions` and pictures
  are not scrubbed; a pathological list (200 near-identical long terms) is
  slow (reviewer's probe, about 31 s on 93,000 characters, not recorded
  elsewhere); DuckDuckGo result-page fetches are not in the receipt; a
  search that failed before sending still shows as a failed search; an
  organisation list whose whole value is the text "unreadable" reads as
  none; a common word as a term ("Source") also replaces field names in
  the System-Two text; the local crash log, saved jobs and settings.json
  hold the words in plain text; a seal that keeps failing leaves old rows
  plain with no signal. The fix commit was not itself re-reviewed.
- YC RFS pass 14 Nov (Winter 2027 "AI for the Air-Gapped Economy"; also
  read: Summer 2026 "Company Brain", "Software for Agents"). Built: a
  person's own offline switch (settings "local_only" lowers
  policy.max_egress to local only; never raises the organisation's
  level); the private-words list is sealed with DPAPI in settings.json
  (an older plain list still reads); a term of more than 8 words is
  dropped (slow pattern); Ask a link reads a PDF with pypdf on this
  computer. Mutation sweep 10 of 10 killed. Left: with the offline switch
  on and no Ollama model installed Orbyn cannot answer and only the
  switch's note says so; a sealed word list another account cannot open
  reads as no words, silently; pypdf parses an untrusted file in-process;
  scanned PDFs have no text; whether the packaged app bundles pypdf was
  not checked.
- Agent access 15 Nov (tier 1, what leaves; YC S26 "Software for Agents",
  "Company Brain"): `py -3.12 -m ghostcursor.agent_server [scope]` is a
  read-only Model Context Protocol server over stdio with three tools
  (recall, list_workflows, get_workflow). It answers only when the person
  switched agent access on and policy.allows("agents"); replies are
  scrubbed (private details and words when hiding is on, keys and numbers
  always), never include sensitive or unreviewed facts, and each call
  leaves a content-free audit line shown in the receipt. Mutation sweep
  13 of 13 killed after one added test. Left: not tried with a real MCP
  client; the page shows the Python command, which is wrong for the
  packaged app (no console entry point there yet); a new Knowledge
  connection is opened per recall; relations (edges) and the Personal
  Brain are not exposed.
- Exports and audit 15 Nov (YC S26 "Company Brain", W27 "Own Your
  Intelligence", F26 "AI-Native Compliance"): Brain page writes a skills
  file (reviewed, non-sensitive facts plus saved workflows, in the agent
  skill format) and test cases (one JSONL case per saved workflow), both
  always scrubbed including private words; Setup shows an audit summary
  (chain intact or where it breaks, 30-day counts, where requests went,
  how far back the record goes) and exports a verified copy; the offline
  card warns when no local model is listening. Mutation sweep 9 of 10
  killed; the survivor (redact_pii=False on the fact export) is equivalent
  because every line is scrubbed again. Left: the test cases are steps
  only (no graded answers, no failures-as-training-data); the eval file is
  not run against any model here; the local-model check is a loopback
  connect to the default Ollama port only; exports overwrite the previous
  file of the same name.
- Tier-1 review 15 Nov (c2ea2b6..46dc0ef, read at 46dc0ef): no blocking
  finding. Fixed from it: the offline switch no longer fails open on a
  damaged settings.json (missing still means never set); replies to
  another agent are always fully scrubbed, whatever the person's own
  hiding switch; a private word starting with n, r or t no longer breaks
  JSON text; a term with a backslash at either end is dropped; workflow
  names are scrubbed in the two exports; a store that cannot be read no
  longer ends the agent server; a local model is reached without the
  environment's proxy; the page shows the organisation's own level
  separately from the person's switch; the offline, agent and audit cards
  say only what the code does; pypdf is a listed dependency and is named
  in the build spec; the packaged app serves agents with
  `Orbyn.exe --agent-server` (checked by tools/smoke_build.py). Mutation
  sweep of these fixes: 9 of 9 killed, output recorded in
  docs/evidence/mutation-sweep-2026-11-15.md. Earlier sweeps this week
  (11 of 11, 10 of 10, 13 of 13, 9 of 10) were shown in the session only
  and are not recorded in a file. Left from the review: ChatGPT sign-in,
  the first voice-model download and team publish are not gated by the
  offline switch (the card now says so); a term right after a \u00XX
  escape in trusted JSON text is missed; in plain text a lowercase word
  right after a single backslash keeps its first letter; the audit chain
  cannot show entries cut from its end; the agent server's scope comes
  from its command line; a sealed word list that cannot be opened reads
  as no words with no signal; _set stores any text for any key; pypdf
  parses an untrusted file in-process with no time bound.
- Keep keys and numbers hidden in answers, 15 Nov (the open decision from
  the dfe1fd1 review): a switch in Setup, off by default so the owner's
  choice to put originals back stands. When on, KEY, PEM, JWT, CARD, IBAN
  and SSN placeholders are left in a System-Two answer, so text Act types
  never holds them; emails, phones and private words still come back.
  Both guards broken on purpose and caught (session output only). Left:
  no organisation policy forces it on.
- Tier-1 re-review 15 Nov (46dc0ef..d0e39dd, read at d0e39dd): one
  BLOCKING finding, fixed: a multi-word private word inside a hyphenated
  workflow name (call-priya-nair) reached another agent through
  list_workflows. Words of a term now match across spaces, hyphens,
  underscores and JSON whitespace escapes, in every caller. Also fixed
  from it: \f and \b escapes; the Teach planner's local Ollama calls skip
  an environment proxy (they did not before; pre-existing tier-1 gap);
  loopback is parsed, not substring-matched; agent-server error text is
  scrubbed; the offline card names team sync. Also this round: the KEY
  pattern no longer takes any word starting with "gho" or "sk" for a key
  (measured: 9 of 239 recorded control names were hidden for that reason,
  0 after; docs/evidence/scrub-on-screen-names-2026-11-15.md). Mutation
  sweep 10 of 10 killed after one added test, recorded in
  docs/evidence/mutation-sweep-2026-11-15.md. This fix round was not
  re-reviewed. Left from the re-review: in plain non-JSON text a lowercase
  Windows path keeps a term's first letter (C:\tina -> C:\t[NAME_1]); a
  term starting with u after a backslash still breaks JSON (fails closed);
  agent_server error strings are fixed today.
- Tier-1 review 15 Nov (d0e39dd..2f89dc0, read at 2f89dc0): no blocking
  finding. Done from it: Groq gsk_, NVIDIA nvapi-, Tavily tvly-, Hugging
  Face hf_, Google AIza and AWS ASIA key shapes are hidden; a Windows path
  in plain text no longer keeps a private word's first letter (JSON
  escapes are lower-case only); a name that spanned a JSON escape came
  back escaped twice and now comes back once; handing a file to the
  running app skips an environment proxy; the measurement script is
  checked in (tools/measure_scrub_names.py). Mutation sweep 6 of 6,
  recorded in docs/evidence/mutation-sweep-2026-11-15.md. Left:
  keep_secrets_hidden covers Gateway.complete only (the page's promise is
  about Orbyn's planned steps, which go through it); a lower-case path
  such as C:\tina in plain text still keeps "t"; this round was not
  re-reviewed.
