"""A ProviderQueryFault must be diagnostic, never silently empty (D069).

Before this, a walker that hit a provider fault returned `[]`, which published
an empty *successful* observation — indistinguishable from "nothing is on
screen". That is how Open Folder's tier-1 perception went dark without any gate
noticing: the workflow still completed on OCR, and nothing reported a problem.

Raising the fault makes it observable. These tests pin the four properties the
raise depends on, plus the one property that must NOT change: a clean absence
still yields a normal empty UIA observation so OCR can escalate.

Every wait is a deadline poll, never a bare sleep (the module docstring in
tests/test_perception_service.py explains why).
"""

import threading
import time

from ghostcursor.perception.service import PerceptionService
from ghostcursor.perception.uia import Element, ProviderQueryFault

EXPORT = Element("Export", "Button", "1001", (10, 10, 110, 40))


def _service(walker, **kw):
    return PerceptionService(
        title_re=".*Whatever.*", walker=walker, interval_s=0.01, **kw
    )


def _wait_until(predicate, timeout=5.0, what="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.005)
    raise AssertionError(f"{what} never became true within {timeout}s")


def test_a_provider_fault_reaches_last_error():
    def walker(_title):
        raise ProviderQueryFault("provider property read failed: boom")

    service = _service(walker)
    service.start()
    try:
        error = _wait_until(
            lambda: service.progress().last_error,
            what="last_error populated by the fault",
        )
        assert "ProviderQueryFault" in error
        assert "boom" in error
    finally:
        service.stop()


def test_a_faulting_iteration_publishes_no_observation():
    def walker(_title):
        raise ProviderQueryFault("provider property read failed: boom")

    service = _service(walker)
    service.start()
    try:
        _wait_until(
            lambda: service.progress().last_error, what="the fault to be recorded"
        )
        # Give the loop several more iterations to be sure nothing lands.
        started = service.progress().heartbeat
        _wait_until(
            lambda: service.progress().heartbeat > started + 2,
            what="further iterations",
        )
        assert service.latest() is None, (
            "a faulting walk must publish nothing, not an empty success"
        )
    finally:
        service.stop()


def test_the_worker_survives_a_fault_and_a_later_iteration_recovers():
    """Transient faults must not be terminal: the tier can come back."""
    state = {"faulting": True}

    def walker(_title):
        if state["faulting"]:
            raise ProviderQueryFault("transient")
        return [EXPORT]

    service = _service(walker)
    service.start()
    try:
        _wait_until(
            lambda: service.progress().last_error, what="the fault to be recorded"
        )
        assert service.latest() is None

        state["faulting"] = False

        observation = _wait_until(service.latest, what="an observation after recovery")
        assert [element.name for element in observation.elements] == ["Export"]

        alive = [t for t in threading.enumerate() if t.is_alive()]
        assert any("perception" in t.name.lower() for t in alive), (
            "the perception worker must still be alive after a fault"
        )
    finally:
        service.stop()


def test_the_heartbeat_keeps_advancing_through_repeated_faults():
    """A looping failure must stay distinguishable from a blocked call."""

    def walker(_title):
        raise ProviderQueryFault("persistent")

    service = _service(walker)
    service.start()
    try:
        first = _wait_until(
            lambda: service.progress().heartbeat, what="a first heartbeat"
        )
        _wait_until(
            lambda: service.progress().heartbeat > first + 3,
            what="the heartbeat to keep advancing through failures",
        )
    finally:
        service.stop()


def test_a_clean_absence_still_publishes_an_empty_uia_observation():
    """The other half of the rule, and the one that must NOT change.

    A dead pointer is absence, not a fault. Absence still yields a successful
    empty observation, which is what lets executable-bounded OCR escalate for
    the same trusted target.
    """

    def walker(_title):
        return []

    service = _service(walker)
    service.start()
    try:
        observation = _wait_until(
            service.latest, what="an empty but successful observation"
        )
        assert observation.elements == ()
        assert service.progress().last_error is None, "a clean absence is not an error"
    finally:
        service.stop()
