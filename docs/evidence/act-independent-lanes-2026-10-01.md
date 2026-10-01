# Independent desktop lanes — 1 October 2026

Each lane ran on its own on the owner's unlocked Windows 11 desktop, at commit
`d663420`, before the counted investor-deck campaign and with nothing else
running (D025). Counts are copied from the pytest and harness summaries of
those runs; this document is prose, not captured output.

| Lane | Command | Result |
|---|---|---|
| Interactive | `py -3.12 -m pytest tests -m interactive` | 61 passed |
| Pixel (pytest) | `py -3.12 -m pytest tests -m pixel` | 3 passed |
| Pixel (overlay harness) | `py -3.12 -m tests.test_overlay` | 16/16 checks passed |
| Pixel (end-to-end harness) | `py -3.12 -m tests.test_end_to_end` | 8/8 checks passed |
| Hung window | `py -3.12 -m pytest tests\test_hung_window.py` | 4 passed |
| Hung perception service | `py -3.12 -m pytest tests\test_perception_service_hung.py` | 2 passed |
| Hung runtime | `py -3.12 -m pytest tests\test_run_threaded.py` | 7 passed |

**Disclosure.** The three hung-window files were first submitted together in
one batch of tool calls, which may have run them concurrently -- a D025
violation. They passed, but those results are not the ones cited. Each file
was then re-run strictly on its own, in sequence; the counts above are those
re-runs, and their timings matched the first runs to within 0.1 s.
