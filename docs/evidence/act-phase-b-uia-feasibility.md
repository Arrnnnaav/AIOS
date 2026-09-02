# Act v1 Phase B — read-only UIA feasibility probe

**PRIMARY RECORD.** Measured 2 September 2026 on a live desktop. Nothing here
is restated from another document, and nothing was acted on: the probe reads
pattern-availability properties and identity properties only. It never calls
`Invoke`, `DoDefaultAction`, `Toggle`, or `SetValue`, and that prohibition is
scanned from the module's AST by `tests/test_uia_feasibility.py`.

Target application: Excel `16.0.20326.20112` (`EXCEL.EXE`, Office 16 root) —
the same Office build the PowerPoint adapter is accepted against. Window class
`XLMAIN`, one matching window. Disposable workbook
`.artifacts/excel-probe/probe-workbook.xlsx`, created with `xlsxwriter`, never
modified.

The build, the exe path and the window class are recorded in
`.artifacts/excel-probe/tabitem-topology.json`. They were originally asserted
here from an unrecorded session, which D034 does not allow; the artifact was
written afterwards from the same live window.

## Excel satisfies the generic-UIA gate

```json
{
  "name": "Add Sheet",
  "control_type": "Button",
  "automation_id": "SheetTab",
  "backend": "Invoke",
  "identity_mode": "runtime_id_required",
  "usable": true,
  "reasons": [],
  "patterns": {"Invoke": true, "SelectionItem": false, "Toggle": false,
               "Value": false, "LegacyIAccessible": true},
  "legacy_default_action": "Press",
  "match_count": 1,
  "cycles": 100, "resolved_cycles": 100,
  "observations": 200, "dwell_intervals": 100,
  "cycles_with_identity_change": 0,
  "distinct_runtime_ids": 1, "distinct_names": 1,
  "distinct_match_counts": [1], "faults": [],
  "runtime_id_stable": true, "semantic_identity_stable": true
}
```

Full record: `.artifacts/excel-probe/add-sheet-feasibility.json` (ignored path).

**`InvokePattern` is available**, so the strongest backend applies and the
`LegacyIAccessible` fallback is not needed — it is present (`Press`) and is
recorded as evidence only. **The VS Code fallback is not required.**

**Identity is `runtime_id_required`,** the strongest mode: 100 of 100 complete
observe → 650 ms dwell → re-resolve pairs resolved, 200 observations, zero
cycles in which the RuntimeId moved across the dwell, zero faults. The
AutomationId `SheetTab` is non-positional, so D069's refusal does not apply.

This is the direct answer to the concern that motivated the gate. D037
measured VS Code's element set churning ~10% in steady state; Excel's
sheet-insert control did not move at all across the exact dwell a cue will
impose.

## The name would have been guessed wrong

The control is named **`Add Sheet`**.

Earlier drafts of the completion plan referred to it as "New Sheet", and
"Insert Worksheet" is the other plausible guess. Both are wrong. A signed
selector carrying either would have pointed the recipe at nothing, and the
failure would have surfaced as an unexplained refusal during acceptance rather
than as a naming mistake.

This is why the probe's discovery mode exists and why `--name` is optional.

## Worksheet tabs and ribbon tabs share a control type

Both are `TabItem`. The postcondition "the worksheet-tab set increased by
exactly one" therefore cannot be computed over all `TabItem`s in the window —
switching a ribbon tab would perturb the same set. Measured separation:

| TabItem | parent | parent type | AutomationId |
|---|---|---|---|
| `Home`, `Insert`, `Draw`, … (10) | `Ribbon Tabs` | Tab | `TabHome`, `TabInsert`, … |
| `Sheet1` | `probe-workbook` | Tab | `SheetTab` |

Recorded in `.artifacts/excel-probe/tabitem-topology.json`, a read-only
enumeration of all 11 `TabItem`s with each one's parent and AutomationId.

Two separable signals: the parent `Tab`, and the AutomationId.

The parent Tab's name is the **workbook file name**, so scoping by it would
bind a selector to a filename and carry content into the selector. Scoping by
`TabItem` + AutomationId `SheetTab` is therefore the **proposed** baseline for
the Phase C contract.

**Its stability is not measured.** The 100-cycle probe ran against the
`Add Sheet` *Button*; nothing here establishes that a worksheet `TabItem`
keeps its identity across a cue's dwell, and an earlier draft of this document
called the scoping "stable" as though it had. `SheetTab` is non-positional,
which is a property of the string; stability is a separate measurement and
belongs to whichever phase first needs to bind a tab.

One caution for that contract: the `Add Sheet` **Button** also carries
AutomationId `SheetTab`. AutomationId alone does not separate the action
target from the postcondition target; control type does.

**Unverified here, by design.** The post-action state cannot be measured
without acting, which Phase B forbids. That the set grows by exactly one, and
what the new tab is named, are Phase D acceptance measurements. Nothing in
this document asserts them.

## A defect this run found in the probe itself

The discovery mode used a pywinauto `descendants(control_type=...)` walk while
the action path used a provider-side `FindAll`. On this window they disagree:

| | Buttons reported |
|---|---|
| pywinauto `descendants(control_type="Button")` | **3** |
| provider `FindAll`, TreeScope_Descendants | **28** |

The three were `Minimize`, `Maximize`, `Close`. `Add Sheet` was among the 25
the walk could not see, so the discovery tool would have reported the control
absent while the action path could have acted on it.

Fixed by adding `provider_type_query_for()` beside `provider_query_for()` in
`ghostcursor/perception/uia.py`, sharing its scope, its reviewed control-type
ids and its FindAll strategy. Two implementations of "what is in this window"
is how they came to disagree in the first place. Re-measured after the fix: 28
candidates, `Add Sheet` present.

## Status against the plan

- Excel passes; the second-application proof does not fall back to VS Code.
- `Invoke` is the backend; `LegacyIAccessible` is recorded, not used.
- Identity mode is `runtime_id_required`, the strongest available.
- No VS Code probe was run, because the gate's own order makes it unnecessary
  when Excel passes. If Excel is later disqualified for another reason, that
  probe still has to happen before VS Code can be named as the proof.
