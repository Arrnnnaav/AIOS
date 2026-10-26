# Packaged Work and GitHub live acceptance

26 October 2026. Run against the rebuilt `dist/Orbyn/Orbyn.exe` on this Windows PC. The packaged process served its bundled page through the token-protected loopback endpoint and opened one visible, correctly sized Edge app-mode window. A separate Playwright browser drove the same packaged server at 500 px width; the native Edge window was observed without moving the OS pointer. The run used a fresh local test topic. Raw console output is `.tmp/live_packaged_acceptance_final.log` (ignored); the non-sensitive result lines are preserved here:

```text
packaged_work_ui=rendered
packaged_edge_window=visible_and_sized
packaged_brain_ui=rendered_and_learning_toggled
packaged_chat_plan_ui=answered_and_drafted
packaged_routine_ui=create_pause_resume_delete
packaged_background_research=finished_and_viewed
live_github=connected repos=30 first_repo_open_issues=0
live_github=disconnected_local_credential_absent
packaged_ui_page_errors=0
```

The GitHub run used the account already authenticated in `gh`; its access token was passed in memory to the packaged Connect form for this test and removed from Orbyn's Windows Credential Manager at Disconnect. The token and repository names were not printed, saved in this evidence, or sent to a model. Only the connector's fixed GET endpoints were used. The first selected repository had no open issues in this view, so the issues endpoint and empty state were exercised; an issue-containing private repository was not demonstrated. After exit, the packaged server was down, the Orbyn GitHub credential was absent, and no running process loaded `dist/Orbyn/_internal/MSVCP140.dll`.

The first packaged attempt exposed a missing frozen `win32timezone` import: Credential Manager Write succeeded, but Read failed, making Connect appear disconnected. Adding the module to `tools/orbyn.spec` fixed the live packaged GUI flow above. A separate build lock showed that Ollama, launched by a frozen Orbyn process, inherited PyInstaller's DLL search path. Orbyn now clears that path only around the external Ollama launch and restores it afterward, following [PyInstaller's external-program guidance](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#launching-external-programs-from-the-frozen-application). The idle test-started Ollama process was stopped to rebuild the canonical `dist` directory; the final build succeeded (`.tmp/build-live-final-dist-unlocked.log`). The final GUI run restarted Ollama without loading Orbyn's DLL.

The user chose a **non-sleep replay** because they could not physically wake this PC if a wake timer failed. `test_missed_routine_after_downtime_replays_once` recreates `App` objects in one pytest process after advancing an injected clock past ten hourly due times; it observes one research job and no duplicate on the next reopen. Its focused run passed (`.tmp/pytest-wake-replay`, local test directory). A separate manual check then ran create, resume, and verify phases in **three OS processes** against one local schedule, with the same ten-interval clock jump. `.tmp/os-process-replay.log` (ignored) records these non-sensitive results:

```text
process_1=schedule_saved
process_2=one_missed_run_after_ten_intervals
process_3=no_duplicate_at_same_time
```

These checks verify durable reload and coalesced replay. They do not establish firmware wake behavior or execution while the PC is asleep. Actual sleep was not invoked.

This is functional acceptance of the packaged workspace interaction layer. It does not count as release acceptance for Teach or Act; those paths retain their separate campaigns and gates.

The final hermetic lane after the frozen-launch fix and replay test passed 3642 tests with 85 deselected in 346.37 s (`py -3.12 -m pytest tests -m "not interactive and not pixel and not hung" --basetemp=.tmp\pytest-hermetic-live-acceptance -p no:cacheprovider -q`; `.tmp\pytest-live-acceptance-full.log`, local ignored output). The long duration is a test-run observation, not a desktop performance measurement.
