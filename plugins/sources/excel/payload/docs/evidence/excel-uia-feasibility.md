# Excel plugin UIA feasibility

Measured locally on 2026-08-30 against Microsoft Excel
`16.0.20326.20112`, workbook window HWND `198302`, using the committed core
observation adapters.

## Traversal decision

Excel exposed stable worksheet controls only while its workbook was the active
foreground window. In that state, one full descendant enumeration of the
already-bound workbook HWND returned 295 controls in 0.547 seconds.

Provider-side exact `FindAll` and pywinauto's type-filtered descendant call
both returned zero for controls that the complete target-window tree exposed.
That measurement caused the separately reviewed D080
`window_descendants` grammar addition. No Excel-specific Python was added.

## SELECT_CELL_B2

| State | Name | Control type | AutomationId | Count |
|---|---|---|---|---:|
| pre-action | `B2` | `DataItem` | `B2` | 1 |
| focus before | — | — | `A1` | 1 |
| focus after click | — | — | `B2` | 1 |

## ADD_WORKSHEET

| State | Name | Control type | Count |
|---|---|---|---:|
| pre-action | `Add Sheet` | `Button` | 1 |
| pre-action | `Sheet2` | `TabItem` | 0 |
| post-action | `Add Sheet` | `Button` | 1 |
| post-action | `Sheet2` | `TabItem` | 1 |

## Sources

- [Microsoft UI Automation control type identifiers](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-controltype-ids)
- [Microsoft UI Automation DataItem control type](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-supportdataitemcontroltype)
- [Microsoft Support: insert or delete a worksheet](https://support.microsoft.com/en-us/office/insert-or-delete-a-worksheet-19d3d21e-a3b3-4e13-a422-d1f43f1faaf2)

These are feasibility measurements, not acceptance evidence. The plugin stays
inactive until the required campaign and independent review are recorded.
