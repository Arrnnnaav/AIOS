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
would remove the focus sampling gap entirely. Not built: at 50 ms slices the
missed window is a wrong-then-right round trip completing inside 50 ms, faster
than a human performs two deliberate clicks, and the cost is COM callbacks on
RPC-managed threads marshalled into the worker's apartment — the area D021 warns
gives confusing intermittent failures rather than clean errors.

**Trigger:** evidence that real use is missing wrong actions. NOT the
theoretical existence of the gap, which is already known and accepted.

### `test_appinfo.py::test_app_info_for_a_store_app_prefers_appx_version` fails on a real desktop
Discovered during the wrong-action feedback milestone, 2026-08-20, and verified
as PRE-EXISTING rather than assumed: it fails identically on `main`
(`1 failed, 7 passed`) and on the feature branch, and `appinfo.py` is byte-identical
between them. The test enumerates live Store-app windows, so it depends on what
happens to be running on the machine.

Verified by checking out `main` and running it there, not by inspection. This
project's CLAUDE.md records that timing-marginal failures have twice been
misreported here as pre-existing flakes when they were not, so "unrelated" is a
claim that has to be measured.

**Trigger:** any work that touches `ghostcursor/perception/appinfo.py`, or the
next time the fast suite's pass count is quoted as authoritative — the suite is
not currently green on a real desktop, and a documented count that silently
excludes a failure is the kind of number D034 exists to stop.
