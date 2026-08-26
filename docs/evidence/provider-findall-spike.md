# Step 0 spike — can a provider query prove `EXACTLY_ONE`?

Status: **complete; `FindAll` is viable, and it found an ambiguity `FindFirst`
was hiding**

## Question

`EXACTLY_ONE` requires knowing whether a selector matched one control or
several. `FindFirst` returns at most one element and cannot detect a second, so
cardinality is **unprovable** with it. Does `FindAll` work on the Chromium
provider, count correctly, and report absence honestly?

The answer gates the declarative compiler's `provider_exact` strategy: if
`FindAll` fails or misreports, `provider_exact` is forbidden for action
selectors and those targets must use `bounded_descendants`.

## Environment

- VS Code **1.134.0**, window `Welcome - AIOS - Visual Studio Code`,
  hwnd rect `(952, 0, 1928, 1028)`, restored (not minimized), Extensions view
  open
- comtypes 1.4.16, pywinauto UIA backend
- Read-only throughout: no input synthesis, no overlay, no tour dispatch

## Result — warm tree, stable across repeats

| Query | `FindAll` Length | property reads OK | `FindFirst` |
|---|---:|---:|---|
| `Toggle Panel (Ctrl+J)` | 1 | 1 | reads OK |
| `Installed Section` + `Button` | 1 | 1 | reads OK |
| `' Open Folder...'` | 1 | 1 | reads OK |
| `' Open Folder...'` + `Button` | 1 | 1 | — |
| `Extensions (Ctrl+Shift+X)` — no control type | **2** | 2 | reads OK (returns only the first) |
| `Extensions (Ctrl+Shift+X)` + `TabItem` | **1** | 1 | — |
| `ThisDoesNotExist12345` | **0** | 0 | **`ValueError: NULL COM pointer access`** |

Repeats: 5/5 identical for the first stability pass, 3/3 identical for the
control-type pass.

## Conclusions

**1. `FindAll` is viable on the Chromium provider.** It counts, it reads, and it
reports a genuine absence as `Length = 0` rather than a dead pointer. The
outcome rule's failure branch does not trigger; `provider_exact` may serve
action selectors.

**2. `FindAll` is strictly better than `FindFirst` for this purpose.** On a
genuine absence `FindFirst` returns a non-`None` object whose property access
raises `NULL COM pointer access`, reconfirming D069's rule on this provider,
while `FindAll` simply reports zero. D069's dead-pointer classification is
largely a `FindFirst` artifact.

**3. It found a real ambiguity that `FindFirst` was hiding.**
`Extensions (Ctrl+Shift+X)` matches **two** elements:

| # | control type | bbox | runtime id |
|---|---|---|---|
| 0 | `TabItem` | `(1093, 923, 1133, 969)` | `(42, 460470, 4, 4, 1, 890)` |
| 1 | `Group` | `(1101, 934, 1124, 957)` | `(42, 460470, 4, 4, 1, 891)` |

The `Group` is **spatially contained** within the `TabItem` and carries an
adjacent runtime id, which is consistent with a nested icon container sharing
the tab's accessible name. The UIA parent relationship was **not queried
directly**, so nesting is inferred from position and id adjacency rather than
established.

**This amends D069**, which now carries a "later measurement" note recording
it. Spike B recorded Open Extensions as `strategy-1` on that
name with `EXACTLY_ONE`, measured through `FindFirst`, which silently returned
the first of two. Under the cardinality rule that selector would raise
`SelectorAmbiguityFault`. The verdict is amended, not overturned: adding
`control_type: "TabItem"` resolves it to `Length = 1`, measured 3/3. Schema v2
does not exist yet; the **agreed v2 design** already includes a `control_type`
field on selectors, so this needs no expressiveness beyond what is planned — but
for this selector the field is **required**, not optional.

**4. Runtime identity is usable for deduplication.** `GetRuntimeId()` returned
identical values across **three consecutive calls within one live observation
session**, against one window whose tree was not rebuilt in between, and
distinguished the two matches. Stability across ticks, across worker
generations, or across a tree rebuild was **not** measured and is not claimed.

That is the stable backend identity the **proposed compiler design** calls for
in its worker-side deduplication rule. D070 records the storage and authority
boundary and contains no runtime-element deduplication rule; the dedupe rule is
design not yet recorded as a decision.

These two particular controls would *also* have been distinguished by serialized
value, since their `control_type` and bounding boxes both differ — so this case
is not itself an example of value equality failing. The rule stands on the
general point: serialized `Element` values are not a reliable backend-identity
mechanism, because nothing guarantees two distinct controls differ in the fields
`Element` carries.

**5. `provider_exact` cannot serve Open Folder.** `build_condition(title=…)` is
an exact match with no normalisation hook, so reaching that element through a
provider query requires writing the observed Codicon glyph into the recipe —
forbidden, because a private-use codepoint is version-sensitive. This
independently confirms the decision to migrate Open Folder to
`bounded_descendants`, which filters on a normalised name after the walk.

## Cold-tree caveat, and a corrected first reading

The **first** measurement pass returned `Length = 0` for every query, including
targets that were plainly on screen; a later pass against the same window
returned non-zero. This spike did **not** isolate the cause, but the pattern is
consistent with the on-demand Chromium accessibility-tree population previously
measured in D035. Every result above is from the later, warm pass.

This matters for the design beyond the spike: a genuinely cold window reports
zero for everything, so an observation plan that runs once against a cold tree
sees an empty screen rather than an absent control. That is indistinguishable
from a clean absence by the rule alone.

**Retracted first reading.** An intermediate run appeared to show that the
provider's `control_type` filter disagreed with what the descendants walk
reports for the same element — `Length = 0` with `control_type="Button"` while
the walk called it a Button. That was wrong: the Codicon glyph in the query
string had been mangled by shell escaping, so the query was for a different
name. Re-run with the name taken directly from the walk, `control_type="Button"`
returns `Length = 1` and `CurrentControlType` is `50000`. There is no
discrepancy between the strategies' control-type semantics.

## Not measured

**Multi-name union cardinality across two *different* names resolving to the
same control** was not measured — no natural case exists among the current
selectors, since Open Folder's ellipsis variants do not both match a live
element. What was measured is the property the union rule actually depends on:
that two distinct matches carry distinct, stable runtime ids and can therefore
be told apart.

A synthetic two-name case should be measured before a **multi-name
`provider_exact`** selector is declared, since that is where per-name `FindAll`
results must be unioned. It does not gate multi-name selectors generally:
`bounded_descendants` filters names after a single walk, so its multi-name
behaviour does not depend on unioning separate provider queries.
