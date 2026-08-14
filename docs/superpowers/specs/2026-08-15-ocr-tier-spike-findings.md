# Perception Tier 2 — Spike Findings

Date: 2026-08-15
Status: spike complete; input to the tier-2 design
Probe code: throwaway, not kept (scratchpad `ocr_spike/`)

Measured on this machine against four real, deliberately-composed screens.
Every number below is measured, not estimated.

---

## 1. The correction that reframes the milestone

An earlier probe found Chrome exposing **43 UIA elements and zero page
content**, and the trigger design was built on it. That was wrong, and it was
an artifact of the probe itself.

**Chromium enables its accessibility tree on demand.** The first UIA client to
ask switches it on. Re-probing the *same* claude.ai tab later returned **145
elements including a `Document` node**. So Chromium — and therefore every
Electron app — is **blind-until-asked, not blind**.

Consequence: VS Code, Slack, Discord, Teams and Canva-in-Chrome do not need
OCR to become visible. They need a **warm-up retry**: a first walk that returns
window furniture but no document content is *not yet ready*, and re-probing
costs nothing. That is a far cheaper fix than an OCR tier, and it is a separate
piece of work from this one.

## 2. Where UIA genuinely fails

| Application | UIA elements | Tool labels UIA exposes |
|---|---|---|
| Canva photo editor (warm Chromium) | 66 (34 named) | **4 of 13** |
| Adobe Acrobat Reader (native) | 20 (17 Panes) | **0 of 16** |

Acrobat is the real case. A mainstream native Windows app exposes a MenuBar, a
ScrollBar and seventeen anonymous Panes — and not one of `All tools`,
`Export a PDF`, `Combine files`, `Scan & OCR`, `Share`, `Convert`.

The Canva editor is the second case: even with a fully warm accessibility
tree, roughly **70% of a photo editor's tool labels are missing**.

So tier 2's justification is not "web content is invisible". It is:
**native apps with text labels but no usable UIA, plus the unexposed remainder
of rich web editors.**

## 3. Engine selection

Measured steady-state, after warm-up, same captures:

| | cold start | full frame 1938x1038 | cropped 646x346 | VS Code recall @90 |
|---|---|---|---|---|
| `Windows.Media.Ocr` | **0.01 s** | **0.17-0.23 s** | **0.03 s** | **22/23** |
| RapidOCR (onnxruntime) | 0.68 s | **39-66 s** | 1.6-2.8 s | 16/23 |

RapidOCR is not "slower" — it is unusable, ~200x over estimate on a full
window, and still over a tick when cropped. `Windows.Media.Ocr` wins on
latency, accuracy, cold start, and D017 (ships with the OS, no model download,
no network).

**Stock PaddleOCR was ruled out without spiking it**: a few-hundred-MB deep
learning runtime plus a first-run network fetch, inside an application that
otherwise touches no network. That conflicts with D017 regardless of accuracy,
so measuring it could not have changed the decision.

Two caveats carried forward, not resolved:

- The `en-GB`/`en-US` OCR recognizers were already present here and needed no
  elevation. That is evidence about **this machine**, not about an arbitrary
  user's. If a user lacks the pack and installing it needs admin, that is a
  distribution blocker independent of accuracy.
- `Windows.Media.Ocr` exposes **no per-word confidence**. The design called for
  two independent floors — read confidence AND fuzzy-match score, neither
  borrowing slack from the other. This engine can only supply one. See §5.

## 4. The floor is 95

Swept the fuzzy-match floor across all four screens. A "decoy" is a label
plausible for that application but definitely not on that screen; any decoy
clearing the floor is a point the system would have drawn somewhere real and
wrong, which under D006 is worse than drawing nothing.

| Screen | Worst false match | Score | Floor required |
|---|---|---|---|
| Canva Home | `Uploads` <- read `upload` | **92.3** | >= 95 |
| Canva editor | `Magic Expand` <- read `Magic Edit` | 72.7 | >= 85 |
| Acrobat | `Compare files` <- read `Combine files` | 76.9 | >= 85 |
| VS Code | none at any floor | - | - |

**Rung 4's floor is 95.** At 95, zero false matches across all four screens.

The `Uploads`/`upload` case is the binding one and could not have been guessed:
both are real Canva surfaces, they differ by one character, and the doc's
suggested 0.85 read-confidence threshold would have shipped a wrong point on
the first real screen tested.

Recall at floor 95, with zero false matches throughout:

| Screen | Labels found | Note |
|---|---|---|
| Acrobat | 21/24 | UIA found **0** — entirely tier-2 gain |
| Canva Home | 21/22 | |
| VS Code | 21/23 | UIA already covers this app |
| Canva editor | 16/21 | recovers **5 of the 9** labels UIA cannot see |

## 5. The dominant failure: multi-line labels

Single-line labels are read perfectly — `BG Remover`, `Magic Edit`, `Upscale`,
`Blur`, `Select area` all scored **100.0**. Labels wrapping onto two lines fail
systematically, and fail in the worst available way:

```
Magic Eraser  -> read as 'Eraser'      66.7
BG Generator  -> read as 'Generator'   85.7
Magic Expand  -> read as 'Magic Edit'  72.7   <-- a DIFFERENT REAL TOOL
```

`Magic Expand` matching `Magic Edit` is the exact confident-wrong failure this
spike existed to find. Both are real buttons in the same grid; a user following
that hint applies the wrong operation to their image. The floor of 95 excludes
it, but only incidentally.

**Design lead for the spec:** reassemble vertically-adjacent reads before
matching. That likely recovers the four multi-line labels currently lost at
floor 95, and removes the mechanism that produced the dangerous match rather
than merely thresholding above it.

## 6. What the spike did not establish

- **Photoshop itself was never measured.** Acrobat is a proxy for its shape
  (icon rails plus text menus), chosen because Photoshop is not installed on
  this machine. Every Acrobat number above carries that caveat; none of it
  should be generalised to Photoshop specifically.
- Icon-only controls remain out of reach. Acrobat's two vertical rails and
  Photoshop's tool palette carry no text at all. OCR cannot help there; that is
  the VLM tier (D003 tier 3).
- Discord and VS Code UIA exposure was not re-measured warm; they were closed
  before that probe.
- Latency was measured on this machine's CPU only.

## 7. Recommendation

Proceed with tier 2, scoped by what was measured:

1. Engine: `Windows.Media.Ocr`. Record the language-pack caveat as a known
   distribution risk.
2. Rung-4 floor: **95**, with the multi-line reassembly in §5 as part of the
   work rather than a later improvement.
3. Primary target: **native apps opaque to UIA** (the Acrobat case), and the
   unexposed remainder of rich web editors (the Canva editor case).
4. Handle Electron/Chromium with a **warm-up retry**, not OCR. Cheaper, and it
   fixes a real bug: a first walk currently returns window furniture and reads
   as a successful observation.
