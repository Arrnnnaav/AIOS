"""A dead-but-undetected worker would be a regression dressed as a fix.

The UI thread stays responsive and ESC still works, so nothing looks wrong
while the system silently stops guiding — harder to notice than a freeze, not
easier.
"""

from ghostcursor.perception.health import WorkerHealth
from ghostcursor.reasoning.staleness import StalenessLadder


class FakeService:
    def __init__(self, alive=True):
        self._alive = alive
        self.heartbeat = 7
        self.restarts = 0
        self.started = 0

    def is_alive(self):
        return self._alive

    def restart(self):
        self.restarts += 1
        self.started += 1
        self._alive = True


def _health(service, now, **kw):
    ladder = StalenessLadder(clock=lambda: now["t"])
    return WorkerHealth(
        service=service, ladder=ladder, log=lambda m: logs.append(m), **kw
    ), ladder


logs: list[str] = []


def setup_function():
    logs.clear()


def test_a_healthy_worker_reports_nothing():
    now = {"t": 0.0}
    service = FakeService()
    health, ladder = _health(service, now)
    ladder.observed()
    assert health.check() is None
    assert service.restarts == 0


def test_a_dead_worker_is_restarted_once():
    now = {"t": 0.0}
    service = FakeService(alive=False)
    health, ladder = _health(service, now)
    ladder.observed()

    assert health.check() is None, "the first death should restart, not give up"
    assert service.restarts == 1


def test_a_second_death_ends_the_tour_with_a_reason():
    now = {"t": 0.0}
    service = FakeService(alive=False)
    health, ladder = _health(service, now)
    ladder.observed()

    health.check()  # first death: restart
    service._alive = False  # it died again
    reason = health.check()

    assert reason is not None
    assert "perception" in reason.lower()
    assert service.restarts == 1, "it must not keep restarting forever"


def test_a_stalled_but_living_worker_is_also_treated_as_dead():
    """Alive but never progressing is the other death mode."""
    now = {"t": 0.0}
    service = FakeService(alive=True)
    health, ladder = _health(service, now, dead_after_s=15.0)
    ladder.observed()

    now["t"] = 20.0
    assert health.check() is None
    assert service.restarts == 1, "a stalled worker was not restarted"


def test_the_heartbeat_is_logged_when_the_policy_fires():
    """Diagnostic only — it must never decide anything."""
    now = {"t": 0.0}
    service = FakeService(alive=False)
    health, ladder = _health(service, now)
    ladder.observed()
    health.check()

    assert any("heartbeat" in message.lower() for message in logs), (
        "the heartbeat was not recorded when the restart policy fired"
    )
