"""The manager/worker presentation bridge, without a desktop dependency."""

from __future__ import annotations

import threading
import time

import pytest

from ghostcursor.act_protocol import LifecycleState, PresentationRequest
from ghostcursor.act_ui_bridge import (
    PresentationBridgeClosed,
    UiThreadPresentationBridge,
)


def _request() -> PresentationRequest:
    return PresentationRequest("session", "node:1", "a" * 32, 1, 1, True)


class FakeOverlay:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def present(self, request, observation, sink=None):
        self.events.append(("present", request, observation, sink))
        return ()

    def on_node_state(self, node, state):
        self.events.append(("state", node, state))

    def release(self):
        self.events.append(("release",))


def test_worker_presentation_runs_only_when_the_owner_thread_pumps():
    overlay = FakeOverlay()
    bridge = UiThreadPresentationBridge(overlay)
    finished = threading.Event()
    result = []

    def worker():
        result.append(bridge.present(_request(), "observation"))
        finished.set()

    thread = threading.Thread(target=worker)
    thread.start()
    time.sleep(0.05)
    assert not finished.is_set()

    assert bridge.pump() == 1
    thread.join(timeout=1.0)

    assert finished.is_set()
    assert result == [()]
    assert overlay.events[0][:3] == ("present", _request(), "observation")


def test_state_repaint_is_ordered_before_the_next_presentation():
    overlay = FakeOverlay()
    bridge = UiThreadPresentationBridge(overlay)
    node = object()
    worker_done = threading.Event()

    def worker():
        bridge.on_node_state(node, LifecycleState.VERIFIED)
        bridge.present(_request(), "next")
        worker_done.set()

    thread = threading.Thread(target=worker)
    thread.start()
    deadline = time.monotonic() + 1.0
    while not worker_done.is_set() and time.monotonic() < deadline:
        bridge.pump()
        time.sleep(0.01)
    thread.join(timeout=1.0)

    assert worker_done.is_set()
    assert [event[0] for event in overlay.events] == ["state", "present"]


def test_overlay_error_is_returned_to_the_worker_not_lost_on_the_ui_thread():
    class Broken(FakeOverlay):
        def present(self, *_args):
            raise ValueError("paint failed")

    bridge = UiThreadPresentationBridge(Broken())
    caught = []

    def worker():
        try:
            bridge.present(_request(), object())
        except BaseException as exc:  # test records the exact transported error
            caught.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    while bridge.pump() == 0:
        time.sleep(0.01)
    thread.join(timeout=1.0)

    assert len(caught) == 1
    assert isinstance(caught[0], ValueError)
    assert str(caught[0]) == "paint failed"


def test_close_releases_a_worker_whose_cue_was_never_pumped():
    overlay = FakeOverlay()
    bridge = UiThreadPresentationBridge(overlay)
    caught = []

    def worker():
        try:
            bridge.present(_request(), object())
        except BaseException as exc:
            caught.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    time.sleep(0.05)
    bridge.close()
    thread.join(timeout=1.0)

    assert len(caught) == 1
    assert isinstance(caught[0], PresentationBridgeClosed)
    assert overlay.events == [("release",)]


def test_only_the_creator_thread_may_pump_or_close_the_surface():
    bridge = UiThreadPresentationBridge(FakeOverlay())
    errors = []

    def wrong_thread():
        for call in (bridge.pump, bridge.close):
            try:
                call()
            except BaseException as exc:
                errors.append(exc)

    thread = threading.Thread(target=wrong_thread)
    thread.start()
    thread.join(timeout=1.0)

    assert [str(error) for error in errors] == [
        "presentation UI must be serviced on its owner thread",
        "presentation UI must be serviced on its owner thread",
    ]
    bridge.close()


def test_the_owner_thread_cannot_wait_on_itself():
    bridge = UiThreadPresentationBridge(FakeOverlay())

    with pytest.raises(RuntimeError, match="cannot wait on its own"):
        bridge.present(_request(), object())

    bridge.close()
