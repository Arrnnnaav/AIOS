# PowerPoint UIA feasibility — the first pointer-visible target

**PRIMARY RECORD.** Measured 3 September 2026 on a live desktop, read-only.
The probe reads pattern-availability and identity properties and never calls
`Invoke`, `DoDefaultAction`, `Toggle` or `SetValue`; that prohibition is
scanned from the module's AST.

PowerPoint `16.0.20326.20112`, window class `PPTFrameClass`, one matching
window, fixture deck open.

## Why PowerPoint rather than Excel

Excel was the original second-application proof because PowerPoint's Act path
is COM object-model and never exercises UIA. Under D109 a COM operation draws
no pointer, so a PowerPoint-only COM build never shows the cursor — the
central thing this phase delivers. PowerPoint has its own UIA surface, so
proving the backend here keeps one application and puts the visible pointer
inside the real deck build.

Excel's measurement stands and is not wasted: it validated the probe and the
identity-policy shape, and remains a fallback.

## The ribbon exposes a usable surface

63 `Button` controls resolved through provider-side `FindAll`. A large
majority expose a true UIA pattern. Full record:
`.artifacts/powerpoint-act/ribbon-candidates.json` (ignored path).

Representative, with their AutomationIds:

| Control | AutomationId | Backend |
|---|---|---|
| `New Slide` | *(empty)* | Invoke |
| `Save` | `FileSave` | Invoke |
| `Copy` / `Paste` / `Cut` | `Copy` / `Paste` / `Cut` | Invoke |
| `Increase Font Size` | `FontSizeIncrease` | Invoke |
| `Bold` / `Italic` | `Bold` / `Italic` | Toggle |
| `From Beginning` | `SlideShowFromBeginning` | Invoke |

## `New Slide` is the first target

Chosen because it is product-relevant — adding a slide is what a deck build
does — visible on the ribbon, and its postcondition is countable.

```json
{
  "name": "New Slide", "control_type": "Button", "automation_id": "",
  "backend": "Invoke", "identity_mode": "runtime_id_required",
  "usable": true, "reasons": [],
  "patterns": {"Invoke": true, "LegacyIAccessible": true,
               "SelectionItem": false, "Toggle": false, "Value": false},
  "legacy_default_action": "Press", "match_count": 1,
  "cycles": 100, "resolved_cycles": 100,
  "observations": 200, "dwell_intervals": 100,
  "cycles_with_identity_change": 0, "faults": [],
  "distinct_runtime_ids": 1, "distinct_names": 1,
  "distinct_match_counts": [1],
  "runtime_id_stable": true, "semantic_identity_stable": true
}
```

Full record: `.artifacts/powerpoint-act/new-slide-feasibility.json`.

**Identity mode is `runtime_id_required`**, the strongest: 100 of 100
complete observe → 650 ms dwell → re-resolve pairs resolved, 200 observations,
zero cycles in which the RuntimeId moved across the dwell, zero faults.

**Its AutomationId is empty.** That is not a problem here because RuntimeId
carries the identity, and an empty string is not positional so D069's refusal
does not apply. It does mean this control could not have used
`semantic_exactly_one` with an AutomationId — the name and control type are
what a semantic fallback would rest on, and both were also stable.

`LegacyIAccessible` is present with default action `Press` and is recorded as
evidence only. Invoke is available, so the weaker backend is not used.

## Not measured here

Whether invoking it adds exactly one slide, and what that slide is named.
Measuring that requires acting, which this probe must not do. It is a Phase D
acceptance measurement.
