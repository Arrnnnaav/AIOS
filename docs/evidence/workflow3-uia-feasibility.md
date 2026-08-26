# Spike B — Workflow #3 UIA feasibility

Status: **complete; Open Extensions passes with existing kinds and strategies**

## Question

Can Open Extensions — or the predetermined Command Palette fallback — be
expressed with the 7 existing verification kinds and one of the 2 existing
selector strategies, with no new production Python?

Asked before the declarative workflow compiler is designed, because the
compiler's required expressiveness is defined by what workflow #3 actually
needs. Building the compiler first risks building the wrong abstraction.

## Environment

- VS Code **1.134.0**, commit `110a328ea54b42367b803ec53ee0bf52ef26b419`, x64
- Read-only throughout. The probe never imported `ghostcursor.run`, the
  reasoning loop, overlay creation, or any input-synthesis API. The operator
  drove every UI state by hand.
- Raw results: `.artifacts/model-evaluation/spike-b-{baseline,extensions-open,
  palette-open,transient,transient-final}.json` (ignored by design, per D065)

The two strategies under test, as they exist in `perception/uia.py`:

- **strategy-1** — provider-side `build_condition(title=…)` + `FindFirst`
  (`iter_vscode_elements`)
- **strategy-2** — `descendants(control_type=…)` walk then exact-name allowlist
  (`iter_vscode_terminal_elements`)

## Verdict — Open Extensions

| Dimension | Verdict |
|---|---|
| **Strategy class** | **`strategy-1`** — `'Extensions (Ctrl+Shift+X)'` reads as `TabItem` in 11.2 ms. `strategy-2` also serves it via a 9-element `TabItem` walk in 23 ms |
| **Window class** | **`persistent`** — a docked view; presence stable across resampling |
| **Verification kind** | **existing** — `element_appears` on `'Installed Section'` |
| **Special args** | none — no `vscode_workspace_title` equivalent required |
| **AutomationId** | empty → no promotion, no ID-based wrong-action feedback, exactly as OPEN_TERMINAL |

`'Installed Section'` is absent at baseline and present when the Extensions view
is open, giving the same absent-to-present transition OPEN_TERMINAL already
verifies with `Terminal Section`.

**No new verification kind and no new selector strategy are required.** The
compiler can be scoped to the 7 existing kinds and the 2 existing strategies.

## Verdict — Command Palette (fallback, rejected)

| Dimension | Verdict |
|---|---|
| **Strategy class** | `strategy-1` reads `'Type the name of a command to run.'` as `Edit` in 7.5 ms while open |
| **Window class** | **partially measured — see the declared gap below** |
| **Recommendation** | **rejected as a workflow target** |

Rejected on two measured grounds, neither of which depends on the unmeasured
property:

1. **It suppresses the rest of the tree while open.** With the palette up, the
   bounded `TabItem` walk returns **zero**, so the activity bar vanishes from
   that walk. A hint grounded on shell chrome becomes ungroundable the moment a
   palette opens.
2. **Its closed state is not distinguishable from its open state by
   `FindFirst` alone** (see the central finding below), so neither
   `element_appears` nor `element_disappears` can honestly verify it unless the
   selector requires a successful property read.

### Declared gap

Dismissal on focus loss was **attempted four times and never measured**. Two
runs caught the palette open but with VS Code holding focus for every sample
(60/60 really present); two runs caught focus correctly but with the palette
closed. A fifth attempt ended when the application was closed rather than
unfocused.

Recorded as unmeasured rather than inferred, per D034. Nothing downstream
depends on it: Open Extensions passed, so the palette was only ever the
fallback, and the two grounds above already disqualify it.

## Central finding — `FindFirst` non-`None` is not evidence of existence

When `build_condition(title=X)` matches nothing, `FindFirst` returns a
**non-`None` element whose every property access raises
`ValueError: NULL COM pointer access`** — rather than returning `None`.

Measured across all 30 observations (10 names x 3 UI states). The pattern is
exact and has no exceptions:

- `'Toggle Panel (Ctrl+J)'` — really present in all three states, reads cleanly
  (5.7–6.4 ms).
- `'Extensions (Ctrl+Shift+X)'` — dead pointer at baseline and with the palette
  open; reads cleanly as `TabItem` only when the Extensions view is open.
- `'Type the name of a command to run.'` — dead pointer at baseline and with
  Extensions open; reads cleanly as `Edit` only with the palette open.
- `'Command Palette'`, `'Quick Input'`, `'Terminal Section'`,
  `'Extensions Section'` — dead pointers in every state. None of these exist.

So: **dead pointer if and only if no match; presence if and only if a property
read succeeds.**

This holds for the **measured environment** — VS Code 1.134.0 with the installed
UIA provider and comtypes 1.4.16. It is an observation to defend against, not a
universal COM guarantee, and should not be restated as one.

Stated as the rule a shared helper must enforce, it has three branches:

| `FindFirst` | property read | meaning |
|---|---|---|
| object | succeeds | **present** |
| object | `NULL COM pointer access` | **absent** |
| object | any other COM/read failure | **perception fault** |

The third branch is the one current code gets wrong.
`iter_vscode_elements()` collapses it into the second with a blanket
`except Exception: return []`, so a real perception fault is published as an
empty successful observation and is indistinguishable from "nothing is there".

Three consequences:

1. Any strategy-1 selector must validate by reading a property. A non-`None`
   return carries no information in this build.
2. `iter_vscode_elements()` is safe today only because its `try/except` around
   `info.rectangle` incidentally catches this. That is a load-bearing accident,
   not a designed guard, and the compiler must make it explicit.
3. A shared provider-query helper must own this rule, and every provider-side
   query must route through it. Verification must never treat pointer existence
   as evidence — `element_appears` and `element_disappears` included.

### Correction to an earlier generalisation

An earlier reading of this data proposed the boundary "provider lookup works for
VS Code shell chrome but fails on Welcome-page webview content." **That is
wrong and must not be recorded.** `Extensions (Ctrl+Shift+X)` is shell chrome
and returned a dead pointer at baseline purely because the sidebar was not
rendered. The behaviour is about whether the condition matched, not about which
surface the element lives on.

## Finding — OPEN_FOLDER's UIA tier currently yields nothing

`iter_vscode_elements()` returns **0 elements** for the live Welcome page, 8/8
repeats. The workflow still completes, because an empty successful observation
lets executable-bounded OCR escalate — the documented design — but its cheapest
and most-trusted perception tier is contributing nothing.

The same target reads cleanly under strategy-2, 5/5, at a stable bbox
`(107, 450, 257, 488)`, under the accessible name `' Open Folder...'` — a
Codicon private-use glyph prefixed to the label. The recipe asks for
`'Open Folder...'`.

**Most likely cause: a name mismatch**, which under the central finding produces
exactly the observed dead pointer. **This is unverified.** Confirming it
requires querying the glyph-prefixed name and checking that a property read
succeeds; VS Code was closed before that test could run. An earlier test that
appeared to confirm all three name variants "HIT" used non-`None` as the
predicate and is therefore meaningless.

**Resolution taken:** move Open Folder to the bounded-descendants strategy,
which is measured working, instead of depending on the unverified hypothesis.
Match a normalised name — strip leading private-use Codicon characters, then
compare against `Open Folder...`. The observed glyph is deliberately *not*
written into the recipe: a specific private-use codepoint is version-sensitive
and would break the next time VS Code renumbers its icon font. Tracked in
`docs/superpowers/FOLLOWUPS.md`.

This does not retroactively invalidate the 3/3 acceptance runs, which were
measured on the then-current build. It does show that a degradation of this
shape **passes acceptance silently**, because the end-to-end outcome still
succeeds on the fallback tier.

## Finding — positional AutomationIds are a promotion hazard

The only non-empty AutomationIds observed anywhere in VS Code are positional:

```
list_id_1_0 … list_id_1_3     extension results
list_id_2_0, list_id_2_1      extension results
list_id_3_0                   extension results
list_id_5_0 … list_id_5_12    command palette entries
quickInput_list               the container itself
```

`list_id_<number>_<number>` encodes a list index. The palette's list is
recency-ordered, so `list_id_5_0` means "most recently used command" and changes
constantly.

`promote()` guards on provenance and non-emptiness, both of which these satisfy.
A recipe targeting such a control would persist a **position** and hydrate it on
the next run pointing at whatever now occupies that index.

**Ruling: the compiler and persistence layer must explicitly reject IDs matching
`list_id_<number>_<number>` from durable promotion.** They identify list
positions, not controls.

## State-by-state element counts

Bounded walks only; the generic full-tree walk was never used. Counts are
elements, times are milliseconds.

| control_type | baseline | extensions-open | palette-open |
|---|---:|---:|---:|
| Button | 44 / 47 | 35 / 46 | 17 / 27 |
| Edit | 0 / 11 | 1 / 24 | 1 / 14 |
| TabItem | 1 / 13 | 9 / 23 | **0 / 12** |
| Tree | 0 / 12 | 0 / 14 | 0 / 13 |
| List | 3 / 15 | 8 / 23 | 6 / 19 |
| ListItem | 11 / 21 | 12 / 25 | 18 / 26 |

Every bounded walk completed in under 50 ms. No walk approached the stall
behaviour that motivated narrowing perception in the first place.

## Consequences for the compiler

1. Recipes must **declare** selector strategy. Strategy 1 and strategy 2 were
   measured resolving the same target differently in the same instant; the
   choice cannot be inferred from the target name.
2. A dead COM pointer must be reported as a **clean absence**, never as a hit.
   Non-`None` is not an existence signal. Only *other* query or property-read
   exceptions are faults, and those must be raised rather than flattened into
   an empty result.
3. Trusted name matching must **strip private-use Codicon prefixes** before
   comparison.
4. Durable promotion must **reject positional IDs**.
5. `vscode_workspace_title` should move into declarative verification
   configuration rather than remaining app-specific logic in the schema layer.
6. Migration cost is roughly **9 real-desktop acceptance runs**: 3 each for the
   two migrated workflows plus 3 for Open Extensions.
7. The Open Folder migration gate must assert the hint was **UIA-grounded**, not
   merely that the workflow completed. Today it would pass on OCR alone and
   reveal nothing about the compiler's strategy-1 path.
