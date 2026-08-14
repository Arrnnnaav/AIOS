# Perception Tier 2 — OCR Fallback — Design

Date: 2026-08-15
Status: reviewed, pending implementation plan
Builds on: `2026-08-14-perception-off-the-ui-thread-design.md` (the worker and
slot this runs inside)
Measurements: `2026-08-15-ocr-tier-spike-findings.md` — every number here comes
from that spike, not from estimation

---

## 1. Why

Ghost Cursor points at the UI element the current step names. When UIA cannot
see that element, it draws nothing and says nothing — which is indistinguishable
from working correctly.

Measured, on real screens:

| Application | UIA elements | Tool labels UIA exposes |
|---|---|---|
| Adobe Acrobat Reader (native) | 20 (17 anonymous Panes) | **0 of 16** |
| Canva photo editor (warm Chromium) | 66 (34 named) | **4 of 13** |

Acrobat is a mainstream Windows application, and Ghost Cursor is blind to
every one of its tools. OCR reads 24 of those 24 labels.

### What this is NOT for

An earlier probe suggested Chromium exposed no page content. That was an
artifact of the probe: **Chromium enables accessibility on demand**, and the
first UIA client to ask switches it on. The same tab later returned 145
elements including a `Document` node.

So Electron apps — VS Code, Slack, Discord, Teams, Canva-in-Chrome — are
*blind-until-asked*, not blind. They need a **warm-up retry**: a first walk
returning window furniture but no document content is not-yet-ready rather
than empty. That is cheaper than OCR, fixes a real bug (such a walk currently
reads as a successful observation), and is **explicitly out of scope here**.
It gets its own spec and its own milestone. Folding it in would make one
larger milestone out of two independent ones.

## 2. Scope, stated precisely

**In scope:** native applications whose text labels are invisible to UIA (the
Acrobat case), and the unexposed remainder of rich web editors (the Canva
editor case).

**Out of scope:** the Chromium warm-up retry (§1); icon-only controls, which
carry no text and are unreachable by any OCR — Acrobat's two vertical rails
and Photoshop's tool palette are tier 3, the VLM (D003).

**Not verified:** Photoshop itself was never measured. Acrobat was chosen as a
proxy for its *shape* — icon rails plus text menus — because Photoshop is not
installed on the development machine. Nothing in this document should be read
as "proven on Photoshop". Every Acrobat number carries that caveat, and the
claim being made is about **Acrobat-shaped native applications**, not about
Photoshop specifically.

## 3. Trigger: per-step grounding failure, never per-walk emptiness

The obvious trigger — "UIA returned nothing" — is wrong, and the spike shows
why. Chrome returned 43 elements in 0.31 s while containing zero page content.
UIA reported success while being useless.

**Tier 2 is triggered when grounding fails for the current step**, not when a
walk returns few elements.

This also avoids colliding with D023, which requires an empty walk to count as
a *successful observation* for staleness purposes. The two never conflict
because they answer different questions: staleness asks "did perception
complete recently", grounding asks "can this step be located".

### Stickiness resets at the step boundary

Once triggered, tier 2 stays on **for that step only**. When the tour advances,
the next step attempts UIA first, exactly as if tier 2 had never run.

This is load-bearing, not tidiness. Photoshop's text menus ground cheaply via
whatever UIA does expose while its tool palette does not; an app-wide sticky
flag would pay OCR cost on every subsequent step and silently become
"always-on OCR" wearing the label of a cheapest-first tier.

## 4. Cadence and cost control

Once tier 2 is on for a step, OCR re-runs **only when the captured region
visibly changes**, and never faster than a floor interval.

| Parameter | Value | Why |
|---|---|---|
| Capture region | the target window's rect | Cropping is the single largest speedup; detection cost scales with area |
| Frame-diff threshold | 2% of pixels changed | From the mss doc's `frames_differ` pattern |
| Minimum interval between OCR runs | 1.0 s | Cap; see below |
| Maximum OCR runs per step | 20 | Cap; see below |

**Both caps are required, not belt-and-braces.** "Re-run only when it changes"
degrades to "re-run every tick" against a genuinely animating region — a
loading spinner in frame, a window being resized, a video preview. Without an
explicit floor interval and a per-step ceiling, adversarial-but-entirely-
realistic screens turn the cheapest-first tier into unconditional OCR.

### Exhausting the run cap is terminal for the step

When the 20-run ceiling is reached and the step still cannot ground, **tier 2
is finished for that step**. It stops re-running, and the step is treated as
ungroundable — the same state a permanently unlocatable step already reaches,
feeding the existing grounding grace and its give-up path.

The rejected alternative is letting the last OCR result stand indefinitely and
simply age. That fails two ways at once: the ring keeps pointing at a
pixel-guess coordinate long after the system has stopped being able to confirm
it, which is the wrong point D006 exists to prevent; and the step becomes
incapable of ever failing, so the user waits on a hint that can never resolve
and is never told why.

Until the grace expires, the last observation continues to age normally through
the staleness ladder — it dims, then hides — so the display degrades honestly
in the meantime rather than freezing. The failure reason names the real cause
("could not read *label* on screen after N attempts") rather than the generic
"cannot find", for the same reason D024 requires a dead worker to be named as a
perception failure: telling the user their element is missing, when in fact we
gave up reading the screen, points them at their own application instead of at
ours.

Measured cost, `Windows.Media.Ocr` on this machine: **0.17–0.23 s** for a full
1938×1038 window, **0.03 s** cropped, **0.01 s** cold start.

### Threading

OCR runs on the **perception worker thread** established in the previous
milestone. Never the UI thread. A tick that runs OCR would blow the 0.5 s
ceiling (D020) and reintroduce the freeze D021 exists to prevent.

The worker being slow is now a solved problem: a slow observation simply
arrives later and the staleness ladder dims. No loading state, no special
case. In practice the cold start measured 0.01 s, so even that absorption is
barely exercised.

## 5. Engine: `Windows.Media.Ocr`

Settled by measurement, and not close:

| | cold start | full frame | cropped | VS Code recall @90 |
|---|---|---|---|---|
| `Windows.Media.Ocr` | **0.01 s** | **0.17–0.23 s** | **0.03 s** | **22/23** |
| RapidOCR (onnxruntime) | 0.68 s | **39–66 s** | 1.6–2.8 s | 16/23 |

RapidOCR is not slower, it is disqualified: ~200× over estimate on a full
window, and still over a tick when cropped.

**Stock PaddleOCR is ruled out without measurement.** A few-hundred-MB deep
learning runtime plus a first-run network fetch, inside an application that
otherwise touches no network, conflicts with D017 regardless of accuracy. No
accuracy result could have changed that, so spiking it would have cost the
heaviest install available to reject a candidate already excluded on
principle. This refines D003's engine choice; it does not reverse its tiering.

### Open risk with an owner, not a caveat

`Windows.Media.Ocr` needs an OCR language pack. On the development machine
`en-GB` and `en-US` were already present and required no elevation — but that
is evidence about **one machine**, and installing a missing pack requires
administrator rights. "End users need admin to use a fallback tier" is a
distribution blocker independent of how good the reads are.

**Checklist item, owner: the implementer of Task 1 of this milestone.**
Before any other task begins, verify on a clean non-development Windows
machine — a fresh VM is sufficient — that:

1. `OcrEngine.available_recognizer_languages` is non-empty out of the box;
2. `OcrEngine.try_create_from_user_profile_languages()` returns an engine;
3. neither required elevation.

If any of those fails, tier 2 stops and the engine decision reopens before
implementation continues. This is the one risk in the spike that data already
in hand does not resolve, so it is verified first rather than last.

## 6. What an OCR element is, and why it can never be promoted

`Element` gains one field:

```python
source: str = "uia"     # "uia" | "ocr"
```

OCR elements join the same list with an empty `automation_id` and empty
`control_type`. They cross the worker boundary as the same frozen dataclass of
primitives — no new contract, and no COM object ever crosses (D021).

**Tier-2 results are never promoted and never persisted.** This is not a
policy choice; it follows from an existing decision. OCR yields text, a box
and a confidence. The box cannot be stored — `schema.py` recursively rejects
`{"bbox", "x", "y", "coordinates", "rect", "point"}` because "a persisted pixel
is a lie the moment a window moves". The text is the claimed name the recipe
already had. There is nothing left worth writing.

So the knowledge base stays UIA-only and provably clean, and tier 2 is pure
runtime fallback. A user who deletes the database loses nothing OCR produced,
because OCR produced nothing durable.

## 7. Grounding: rung 4, OCR-only, one honest floor

The ladder gains a fourth rung that runs **only against `source == "ocr"`
elements**, after rungs 1–3 have failed:

| Rung | Match | Applies to |
|---|---|---|
| 1 | `automation_id`, exact | uia |
| 2 | `name`, exact | uia (ocr elements may incidentally hit this) |
| 3 | synonyms, exact | uia |
| **4** | **fuzzy text, score ≥ 95** | **ocr only** |

Rungs 1–3 stay exact. Loosening them to fuzzy-for-everyone would let an app
that grounds cleanly today start accepting a wrong confident match tomorrow,
paying a regression risk on working applications to solve an OCR-only problem.

An OCR element whose text happens to match exactly will be matched at rung 2,
since exact is strictly stronger than fuzzy and there is no reason to reject
it. **The display state keys off `source`, never off which rung matched** — an
OCR element matched at rung 2 is still shown as `INFERRED`, because it is
still a text match on pixels rather than a confirmed control. Rung number
describes how it was found; `source` describes how much it can be trusted.

**Duplicate labels are inherited, not newly solved.** When several elements
carry the same name — multiple `Export` buttons in different panels is
ordinary — rungs 2–4 fall back to whatever disambiguation the ladder already
performs today. That logic was written against UIA, whose elements come with
structural context OCR reads do not have, so it is weaker for tier 2 than for
tier 1. This is a pre-existing concern rather than one this milestone
introduces, and it is deliberately not addressed here — but it is recorded so
it is not silently assumed to be handled.

### The floor is 95, and one bar is doing two jobs

The design called for **two independent floors** — OCR read confidence and
fuzzy-match score, each clearing its own bar so a weak read and a loose match
could not borrow slack from one another and average into something that looks
acceptable.

**`Windows.Media.Ocr` exposes no per-word confidence.** That is stated plainly
rather than quietly dropped: the two-floor design cannot be implemented with
this engine, and **the fuzzy-match score alone now carries both jobs**. The
floor is set conservatively at 95 precisely because it is doing double duty,
not because 95 is where recall happens to look good.

95 is measured, not chosen. Sweeping the floor across four real screens:

| Screen | Worst false match | Score | Floor required |
|---|---|---|---|
| Canva Home | `Uploads` ← read `upload` | **92.3** | ≥ 95 |
| Acrobat | `Compare files` ← read `Combine files` | 76.9 | ≥ 85 |
| Canva editor | `Magic Expand` ← read `Magic Edit` | 72.7 | ≥ 85 |
| VS Code | none at any floor | — | — |

At 95, zero false matches on all four. The binding case is `Uploads` versus
`upload`: both are real Canva surfaces, one character apart. The PaddleOCR
doc's suggested 0.85 read-confidence threshold would have pointed at the wrong
one on the first real screen tested.

Recall at 95, with zero false matches throughout: Acrobat 21/24 (UIA found
**0**), Canva Home 21/22, VS Code 21/23, Canva editor 16/21.

## 8. Multi-line label reassembly — ships in this milestone

Single-line labels read perfectly: `BG Remover`, `Magic Edit`, `Upscale`,
`Blur`, `Select area` all scored **100.0**. Labels wrapping onto two lines fail
systematically, and fail in the worst available way:

```
Magic Eraser  ->  'Eraser'      66.7
BG Generator  ->  'Generator'   85.7
Magic Expand  ->  'Magic Edit'  72.7   <-- a DIFFERENT REAL TOOL, same grid
```

`Magic Expand` matching `Magic Edit` is the one genuinely dangerous result the
spike produced. Both are real buttons side by side; a user following that hint
applies the wrong operation to their image. That is precisely the failure D006
exists to prevent — we only ever point, so a wrong point is a wrong
instruction.

**This is not a later improvement.** Shipping the floor without the
reassembly would ship a system provably capable of confidently pointing at the
wrong tool; the floor of 95 excludes that particular match only incidentally,
and a different pair of adjacent labels could clear it. The fix removes the
mechanism rather than thresholding above its symptom.

Before matching, merge reads that are plausibly one wrapped label:

- horizontal centres within 40% of the wider box's width of each other, and
- vertical gap less than 0.75× the taller box's height, and
- at most three reads merged into one candidate.

Both the merged candidate and its parts are offered to rung 4, so a merge that
guesses wrong cannot lose a match the unmerged read would have made. All three
constants are tunable and expected to be revisited against a second
application.

**Reassembly introduces a second, opposite risk, and it must be measured
rather than argued.** Offering merged candidates means a merge of two
*unrelated but adjacent* labels could manufacture a string that matches
something at ≥ 95 which neither original read would have matched alone —
inventing a target out of two innocent ones. The geometry constants make that
unlikely, but "unlikely" is the claim this project has repeatedly found
diverging from "measured": the whole spike exists because a cold accessibility
tree, a tick ceiling and a fuzzy floor each behaved differently than reasoning
predicted. The false-positive direction therefore gets its own test (§11), built
from adjacent real labels on the spike's own captured screens, not only the
false-negative direction that motivated the feature.

## 9. Display: a third state, and no laundering

Tier 2 hints get their own visual state. The overlay knows two today.

| State | Meaning | Ring |
|---|---|---|
| `FRESH` | current, UIA-confirmed | bright |
| `INFERRED` | current, read from pixels | third treatment |
| `DIMMED` | last known, unconfirmed (any source) | dimmed |
| `HIDDEN` | too old to show | nothing |

`DIMMED` and `INFERRED` answer structurally different questions — one about
time ("was this true a moment ago"), one about source confidence ("I matched
text on pixels rather than confirming the control"). Collapsing them would tell
the user to be careful without telling them *what kind* of caution applies,
which is the calibration D006 depends on. The hedge does not go in the
instruction text either: that text describes the task, and perception
provenance is not task content.

**Precedence is strict:** `HIDDEN` > `DIMMED` > `INFERRED` > `FRESH`.
Staleness dominates — "possibly outdated" subsumes "possibly misread".

**The source axis persists underneath the display.** A tier-2 hint that goes
stale shows `DIMMED`; when perception recovers it must return to `INFERRED`,
never to `FRESH`. Otherwise a round trip through staleness silently launders a
pixel guess into a confirmed control — the same shape as the verification-
baseline laundering bug found in the previous milestone.

`HIDDEN` still clears the hint rather than being passed to `set_hint`, since
the painter distinguishes only `FRESH` from everything else.

## 10. Error handling

| Failure | Response |
|---|---|
| No OCR language pack | Tier 2 disabled for the session; logged once with an explicit reason. The tour continues on UIA alone rather than failing |
| Capture fails (window vanished mid-grab) | No observation this cycle; existing staleness handling applies |
| OCR raises | Treated as a failed walk, not an empty one; worker keeps running |
| OCR returns nothing | A successful observation with no elements — grounding fails, the existing grace applies |
| Region has animated continuously | Re-run caps in §4 hold; the last OCR result stays in use and ages normally |
| Run cap exhausted, step still ungroundable | Tier 2 stops for that step; the step is treated as ungroundable and enters the existing grounding grace, ending with a reason that names the read failure (§4) |

## 11. Testing

- Rung 4 matches at 95 and rejects at 94, against fixtures built from the
  spike's real reads — including `Uploads`/`upload` at 92.3, which must NOT
  match.
- Multi-line reassembly recovers `Magic Eraser`, `BG Generator` and
  `Magic Expand` from their real component reads, and `Magic Expand` must not
  match `Magic Edit`.
- Reassembly does not MANUFACTURE a match: given an adversarial pair of
  adjacent-but-unrelated real labels taken from the spike's captured screens
  (for example Acrobat's vertically stacked `Redact a PDF` / `Compress a PDF`,
  or the Canva editor's `Crop` / `Pixel Eraser`), no merged candidate may reach
  95 against any target that neither component read matches alone. This is the
  false-positive direction of §8 and is as load-bearing as the recall case.
- `source` survives the worker boundary intact.
- Tier 2 does not trigger while grounding succeeds; triggers on grounding
  failure; and resets at the step boundary.
- Re-run caps hold against a synthetic continuously-changing region.
- `INFERRED` renders in its own colour on real pixels — a 16th check in
  `tests/test_overlay.py`, matching how `FRESH` and `DIMMED` were each
  verified.
- Precedence, including that a recovered tier-2 hint returns to `INFERRED`
  and not `FRESH`.
- Per D018, mutation-verified: the rung-4 floor, the reassembly, the
  no-laundering rule, and the re-run caps must each fail a test when broken.
- Per D026, the display transitions are asserted as an ordered sequence on the
  injected clock, not as end states.

## 12. Open questions

- The cadence constants (1.0 s floor, 20 runs per step, 2% diff) and the three
  reassembly geometry constants are judgement informed by one machine and four
  screens. They are constructor parameters and should be revisited against a
  second native application.
- Whether `INFERRED` should also carry a distinct ring thickness rather than
  colour alone, for accessibility under colour-vision deficiency.
