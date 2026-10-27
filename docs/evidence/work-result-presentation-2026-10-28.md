# Work result presentation

28 October 2026. Compared the retained HeyClicky desktop card screenshot
(`output/playwright/heyclicky-reference.png`, captured in an earlier live
session) with a fresh Orbyn 500 px Work screenshot
(`output/playwright/orbyn-before-500.png`). HeyClicky's installed window was
minimized during this turn, so no fresh HeyClicky state was inferred from it.
The older screenshot shows a compact completed-task card with the result and
one opening action over the desktop. Orbyn's Work stage showed a generic
Start here card even while a finished research result sat below it.

The Work stage now places the newest visible finished research result ahead
of older answer and plan cards. It shows a bounded text preview and Read
result, which opens the existing result sheet. Active work remains first.
Archiving a result removes it from the stage as well as the normal job list;
restoring it makes it eligible again. At desktop widths above 760 px, the
workspace contents and sheets stay centered within 760 px. This is local
presentation of already stored text, not a new authority or model request.

Fresh Playwright CLI screenshots after the change are
`output/playwright/orbyn-result-dark-500.png` and
`output/playwright/orbyn-result-dark-900.png`. At 900 px the CLI verified
`document.documentElement.scrollWidth <= innerWidth`, and clicking the new
Read result button opened the named Research result dialog. The screenshots
are local artifacts and are not committed because the HeyClicky reference
contains desktop filenames.

The focused Edge test passed (1 passed, 52 deselected) in
`.tmp/pytest-work-result-ui`. It checked the latest result in the stage,
opening its sheet, hiding the stage action after Archive, and the existing
Restore, follow-up and Markdown download flow. The staged full hermetic lane
passed 3,649 tests with 93 deselected in 239.56 seconds
(`.tmp/hermetic-work-result.log`). An independent D032 reviewer read
`545a3e8` in a detached worktree and returned READY with no blocking finding;
the reviewer did not rerun pytest under D025. The reviewer verified current
work precedence, latest visible result selection, text-only rendering,
archive behavior and bounded wide layout. The detached worktree was removed.

Opening Work now shows up to 360 characters of the newest saved answer.
Active-work precedence and 900 px overflow were checked in source and the
Playwright CLI session, respectively, but lack separate automated assertions.

The frozen app was rebuilt successfully with `tools/build_orbyn.ps1`
(`.tmp/build-work-result.log`). An isolated seeded-inbox trial launched
`dist/Orbyn/Orbyn.exe`, found the result spotlight, clicked Read result,
found the named result sheet, and quit with exit code 0
(`.tmp/packaged-work-result.log`; screenshot
`output/playwright/orbyn-packaged-work-result.png`). This confirms packaged
UI inclusion, not a live model response or HeyClicky action.
