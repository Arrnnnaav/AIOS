"""The service against a REAL hung window, not a fake slow walker.

Kept out of tests/test_perception_service.py because the fixture costs ~45s
per test — the same reason tests/test_hung_window.py is excluded from fast
runs. Everything else about the service is exercised with fakes; this file
exists to prove the fakes were telling the truth about the real failure.

Run:  python -B -m pytest tests/test_perception_service_hung.py -q
"""

import time

from ghostcursor.perception.service import PerceptionService
from tests.test_hung_window import HungWindow


def test_reads_stay_instant_while_the_worker_is_stuck_on_a_hung_window():
    """A UIA walk against a window that stopped pumping blocks for ~10-40s.

    That is 80x the 0.5s tick budget, and ESC is only polled between ticks.
    On the worker it costs the UI thread nothing: latest() returns whatever
    the slot holds (here None — no walk has ever completed) immediately.
    """
    with HungWindow() as hung:
        service = PerceptionService(title_re=hung.title_re, interval_s=0.01)
        service.start()
        try:
            # Give the worker time to actually enter the blocking walk.
            deadline = time.monotonic() + 5
            while service.heartbeat < 1 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert service.heartbeat >= 1, "the worker never started a walk"

            # Read the slot the way a tick would, for longer than a healthy
            # walk could ever take, and time the worst single read. The
            # fixture blocks for ~10-40s, so 3s of reads lands squarely
            # inside the block: no sleep here is being sized to "probably
            # long enough", it is a lower bound the fixture guarantees, and
            # a fixture that stopped hanging would show up as a climbing
            # heartbeat rather than as a silent pass.
            worst = 0.0
            reads = 0
            until = time.monotonic() + 3.0
            while time.monotonic() < until:
                t0 = time.perf_counter()
                service.latest()
                worst = max(worst, time.perf_counter() - t0)
                reads += 1

            # The worker is still inside the walk that would have frozen the
            # UI thread; the heartbeat is frozen with it, which is exactly
            # the diagnostic distinction it exists to make.
            stuck_heartbeat = service.heartbeat
            alive = service.is_alive()
        finally:
            # The worker cannot be interrupted mid-walk; it is a daemon and
            # exits with the process, so do not spend 2s joining it.
            service.stop(timeout=0.1)

    assert reads > 1000, f"only managed {reads} reads in 3s — reads are not free"
    assert worst < 0.05, (
        f"the slowest slot read took {worst:.3f}s against a hung target — "
        "the UI thread is still coupled to perception"
    )
    assert stuck_heartbeat == 1, (
        f"heartbeat reached {stuck_heartbeat} — the walk against the hung "
        "window returned within 3s, so this test is not reproducing the "
        "real failure"
    )
    assert alive, "the worker died rather than blocking"
