# PowerPoint UIA feasibility — measured candidate controls

Date: 2026-08-31

Application: Microsoft PowerPoint

Executable: `powerpnt.exe`

Executable version: `16.0.20326.20112`
Window measured: `Presentation2 - PowerPoint`, HWND [redacted, D128]

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
The changed state was observed only on HWND [redacted, D128], which proves the query
was scoped to the selected presentation rather than the process or desktop.

## Other exact pre-action controls observed

The same live tree exposed one `TabItem` each named `Home`, `Insert`, and
`Design`, one `Button` named `From Beginning`, and one `Button` named `Save`.
These are measurements only; they are not workflow claims until their own
post-action states are measured.

## Insert clustered bar chart

The user manually selected **Insert**, **Chart...**, **Bar**, and **OK**. The
bound presentation exposed each intermediate state as descendants of HWND
[redacted, D128], including the modal `Insert Chart` surface.

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

## Open a comment editor

After the user closed the chart-data window, selected **Insert**, and clicked
**Comment**, HWND [redacted, D128] exposed:

| Control type | Exact name | Count | AutomationId |
|---|---|---:|---|
| Button | Comment | 1 | InsertNewComment |
| Edit | Start a conversation | 1 | dynamic `cardEditor_...` value |
| Button | Post comment (Ctrl + Enter) | 1 | dynamic `sendReplyButton_...` value |
| Button | Cancel | 1 | dynamic `draftCancelButton_...` value |

The recipe binds names and types, not the dynamic GUID-bearing IDs. Completion
is the exact editor name. It uses `accept_if_already_present`, so an already-
open editor completes without creating a second draft.

## Open Slide Sorter

After discarding the empty comment draft, the user manually clicked **Slide
Sorter**. The first attempt was excluded because a comment-discard confirmation
modal still covered the presentation. In the clean state, HWND [redacted, D128]
exposed:

| Control type | Exact name | Count | AutomationId |
|---|---|---:|---|
| Button | Slide Sorter | 1 | empty |
| Pane | Slide Sorter | 1 | SlideSorterPane |
| ListItem | Slide | 2 | Slide256Image / Slide257Image |

The two same-name slide thumbnails are not selectors. Completion is the unique
semantic pane; the status-bar button is the unique action.

## Open Normal View

From the clean Slide Sorter state, the user manually clicked **Normal**. Exact
provider-side queries on the same HWND returned:

| Phase | Control type | Exact name | Count | AutomationId |
|---|---|---|---:|---|
| before/action | Button | Normal | 1 | empty |
| before | Pane | Slide Sorter | 1 | SlideSorterPane |
| after | Pane | Slide | 1 | SlidePane |
| after | Pane | Slide Sorter | 0 | n/a |
| both | Text | View Indicator Slide 2 of 2 | 1 | empty |

Completion is the semantic slide-editing pane, not button state, geometry, or
the disappearance of the old pane. The candidate requires Slide Sorter as a
precondition and uses `accept_if_already_present` for an already-open Normal
view.

## Limits

- The accepted precondition for this candidate is exactly one slide, expressed
  by the status text `View Indicator Slide 1 of 1`.
- No selector is inferred for a general N→N+1 slide transition.
- No input synthesis, COM automation, OCR, or model grounding was used.
- Adoption still requires isolated 3/3 UIA-only acceptance and independent
  review of the exact content-addressed candidate bytes.
