# PowerPoint UIA feasibility — measured candidate controls

Date: 2026-08-31

Application: Microsoft PowerPoint

Executable: `powerpnt.exe`

Executable version: `16.0.20326.20112`
Window measured: `Presentation2 - PowerPoint`, HWND `657022`

This is feasibility evidence, not adoption evidence. All interaction was
performed manually by the user. GhostCursor only enumerated the bound window's
UI Automation tree and issued exact provider-side queries.

## Add second slide

Pre-action, on a blank one-slide presentation:

| Control type | Exact name | Provider count | AutomationId |
|---|---|---:|---|
| Button | New Slide | 1 | empty |
| Text | View Indicator Slide 1 of 1 | 1 | empty |

After the user clicked **New Slide** once:

| Control type | Exact name | Provider count | AutomationId |
|---|---|---:|---|
| Text | View Indicator Slide 2 of 2 | 1 | empty |

A second visible PowerPoint HWND remained at `View Indicator Slide 1 of 1`.
The changed state was observed only on HWND `657022`, which proves the query
was scoped to the selected presentation rather than the process or desktop.

## Other exact pre-action controls observed

The same live tree exposed one `TabItem` each named `Home`, `Insert`, and
`Design`, one `Button` named `From Beginning`, and one `Button` named `Save`.
These are measurements only; they are not workflow claims until their own
post-action states are measured.

## Insert clustered bar chart

The user manually selected **Insert**, **Chart...**, **Bar**, and **OK**. The
bound presentation exposed each intermediate state as descendants of HWND
`657022`, including the modal `Insert Chart` surface.

| State | Control type | Exact name | Provider count | AutomationId |
|---|---|---|---:|---|
| Insert ribbon open | Button | Chart... | 1 | ChartInsert |
| Insert Chart open | ListItem | Bar | 1 | empty |
| Bar selected | ListItem | Bar | 1 | empty |
| Bar selected | Text | Clustered Bar | 1 | empty |
| Dialog awaiting confirmation | Button | OK | 1 | empty |
| Chart inserted | TabItem | Chart Design | 1 | empty |

`Pie` was measured and rejected: after selection, three `ListItem/Pie`
elements existed because the subtype gallery repeated the category name. That
would fault an exactly-one action selector on the verification tick. `Bar`
remained exactly one while `Text/Clustered Bar` appeared as a separate
postcondition.

After confirmation, PowerPoint opened `Chart in Microsoft PowerPoint - Excel`
as a separate visible window. The recipe does not bind, target, or authorize
that Excel window. Completion is the `Chart Design` tab exposed through the
original PowerPoint HWND.

## Limits

- The accepted precondition for this candidate is exactly one slide, expressed
  by the status text `View Indicator Slide 1 of 1`.
- No selector is inferred for a general N→N+1 slide transition.
- No input synthesis, COM automation, OCR, or model grounding was used.
- Adoption still requires isolated 3/3 UIA-only acceptance and independent
  review of the exact content-addressed candidate bytes.
