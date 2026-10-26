# Desktop companion interaction study and Orbyn island trial

26 October 2026. This review asks what a desktop companion should show while
idle, working and returning a result. Product claims below come from the
vendors' own documentation. The user-feedback examples came from Agent Reach
1.6's anonymous Reddit public-web search; it marked them as search results,
not verified full threads or a representative survey. Reading one Reddit page
returned a network-security block, so no claim here relies on unseen comments.
Tavily's research CLI was installed but its stored OAuth refresh failed twice;
it was not used as evidence.

| Pattern | Observed product evidence | Orbyn decision |
|---|---|---|
| Summonable companion | [ChatGPT for Windows](https://help.openai.com/en/articles/9982051-using-the-chatgpt-windows-app) uses Alt+Space, remembers its window position, and reopens by shortcut. [Claude quick entry](https://academy.claude.com/tutorials/navigating-the-claude-desktop-app) puts a small prompt over the current app by shortcut. [Copilot on Windows](https://learn.microsoft.com/en-us/copilot/windows) lets its key launch either quick view or the full app. | Add a Hide control and Ctrl+Alt+O recall, leaving the default voice Ctrl+Alt+Space intact. Keep the existing full workspace available through Open. If Windows refuses that shortcut, leave Hide unavailable so the user cannot lose the island. |
| Brief status and direct result | [Apple Live Activities guidance](https://developer.apple.com/design/human-interface-guidelines/live-activities) favors compact state, essential actions, innocuous summaries in prominent locations, and a link to related details. The installed HeyClicky result card opened its detail view in the [local UI comparison](heyclicky-live-ui-2026-10-26.md). | Keep generic status only; automatically show a hidden island for active work or a new research result, then hide it again after the result interval. Open a fresh research result in Orbyn's existing Work tab. |
| Quick entry plus durable workspace | [Raycast AI Chat](https://manual.raycast.com/ai/ai-chat) separates Quick AI from a durable chat workspace and can continue a quick query in that workspace. [Raycast Windows](https://www.raycast.com/changelog/windows/2) added focused-window context through an explicit command. | Use the island for status and essential controls and the full workspace for history, results and planning. Do not add automatic screen capture or another agent authority path. |
| Explicit context sharing | [Copilot Vision](https://support.microsoft.com/en-au/microsoft-365-copilot/get-started-vision-microsoft-365-copilot) requires starting voice and choosing screen sharing; it shows the shared scope and a Stop-sharing control. | Keep Orbyn's existing observed-control Teach flow and approval boundaries. The island does not silently start perception or share the screen. |
| Context-specific surface | [Comet](https://www.perplexity.ai/comet/resources/articles/comet-quick-start-guide) puts a collapsible assistant next to browser pages. [Wispr Flow](https://docs.wisprflow.ai/articles/2772472373-what-is-flow) uses a desktop dictation shortcut for text insertion in the active field. | Keep Orbyn's general desktop status island separate from its full workspace and local dictation flow. Do not copy Comet's browser control or Flow's cross-app text insertion into this surface. |

The Agent Reach sample included a [ChatGPT companion complaint](https://www.reddit.com/r/ChatGPT/comments/1ij0zz1/how_to_stop_the_windows_companion_app_for_staying/) about a persistent topmost window without a minimize path, a [request for a quick-ask hotkey](https://www.reddit.com/r/macapps/comments/1vp7xuz/app_suggestions_for_a_global_hotkey_to_launch_a/), and a [Raycast user describing tension between quick entry and a durable result](https://www.reddit.com/r/raycastapp/comments/1qcgn87/tabs_in_raycast_for_quick_ai/). These are individual reports, not evidence of what most users prefer. The common product design and those examples support testing an explicit Hide/recall path rather than forcing an always-visible capsule.

## Implemented trial

The island now offers Hide while idle and registers Ctrl+Alt+O for show/hide.
It refuses Hide during work so Stop remains available. If the user hides the
island, a running task or new research result reveals it automatically; a new
result opens directly in Work and the auto-revealed island hides after its
short result interval. A second default launcher invocation recalls an
existing hidden island. A shortcut conflict leaves the island visible and
disables Hide; it does not seize another application's key. A configured voice
key using Ctrl+Alt+O has priority and also disables Hide. The full workspace
and existing Stop/Quit signals remain unchanged.

Windows exposed one active monitor during this trial: one 1920×1080 physical
work area at 120 DPI. The retired Epson projector entry was not active.
An interactive native-window test moved the compact island near the real
monitor's top-left and bottom-right edges, expanded it, and checked the entire
expanded rectangle stayed in the work area. The same test replayed a
1920-pixel secondary on the left at negative X/Y and one on the right, testing
both edges of each; it then replayed a disconnected secondary and verified
the island clamped back into the active monitor's work area. This exercises
Orbyn's monitor selection and geometry math with real HWND moves, but it is
not a visual or DPI trial on a physically connected second display.

Focused interactive/workspace/no-input-synthesis/signed-byte tests passed 76
tests. The full hermetic lane passed 3,644 tests with 90 deselected in 332.28
seconds; its local output is `.tmp/hermetic-island-study.log` (ignored). D018
mutation and frozen-build results are appended after those checks run.
