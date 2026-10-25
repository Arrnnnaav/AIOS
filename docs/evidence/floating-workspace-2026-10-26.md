# Floating workspace launch

26 October 2026. A seeded local workspace page was opened through the installed Edge app-mode launcher on this Windows desktop. Edge initially reused saved dock bounds despite `--window-size` and `--window-position`; launching a fresh app window and moving only the newly observed Edge window titled Orbyn produced the requested floating bounds `(640, 90, 1280, 810)` in DPI-aware screen coordinates. The window retained its native title bar, so it can be dragged and resized by Windows. The test windows were closed afterward. This is a window-layout check, not a Teach or Act acceptance run.

`open_window()` compares matching Edge app windows before and after launch and moves only a new one. `--dock` selects the old right-side layout. A focused unit test checks both argument sets and that an existing window is not moved; the observed Edge launch above checks that positioning takes effect when Edge ignores launch bounds. No backend API, screen targeting or input synthesis was added.

The full hermetic lane (`py -3.12 -m pytest tests -m "not interactive and not pixel and not hung" --basetemp=.tmp\pytest-hermetic-floating -p no:cacheprovider -q`) passed 3,623 tests with 85 deselected in 206.29 s. Interactive, pixel and hung-window lanes were not run for this window-layout slice.
