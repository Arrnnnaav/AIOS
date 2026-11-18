"""The Teach ring flies from the user's cursor to the control (HeyClicky's
spring flight) and always lands exactly on the observed control (rule 3)."""

from ghostcursor.overlay.cue import FLY_S, fly_position


def test_flight_starts_at_the_cursor_and_lands_exactly_on_the_control():
    start, end = (0, 0), (1000, 400)
    assert fly_position(start, end, 0.0) == start
    assert fly_position(start, end, FLY_S) == end
    assert fly_position(start, end, FLY_S * 5) == end
    assert fly_position(start, end, -1.0) == start


def test_flight_moves_forward_and_overshoots_only_a_little():
    start, end = (0, 0), (1000, 0)
    xs = [fly_position(start, end, FLY_S * i / 20)[0] for i in range(21)]
    assert xs[5] > 300  # ease-out: most of the way early
    assert max(xs) <= 1000  # never past the observed control (rule 3)
    assert xs[-1] == 1000


def test_zero_duration_lands_at_once():
    assert fly_position((0, 0), (50, 50), 0.0, duration=0) == (50, 50)
    assert fly_position((0, 0), (50, 50), -1.0, duration=0) == (50, 50)


class _Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def _overlay(monkeypatch):
    import time
    import types

    from ghostcursor.overlay import window as ov

    clock = _Clock()
    timers = []
    monkeypatch.setattr(time, "monotonic", clock)
    monkeypatch.setattr(ov.win32gui, "InvalidateRect", lambda *a: None)
    monkeypatch.setattr(ov.win32gui, "UpdateWindow", lambda *a: None)
    monkeypatch.setattr(ov.win32api, "GetCursorPos", lambda: (0, 0))
    user32 = types.SimpleNamespace(SetTimer=lambda *a: timers.append(a), KillTimer=lambda *a: None)
    monkeypatch.setattr(ov, "_user32", user32)
    monkeypatch.setattr(ov, "_origin", (0, 0))
    monkeypatch.setattr(ov, "_hint", None)
    monkeypatch.setattr(ov, "_flight", None)
    return ov, clock, timers


def test_ring_flies_from_the_cursor_and_rests_exactly_on_the_control(monkeypatch):
    ov, clock, timers = _overlay(monkeypatch)
    ov.set_hint(1, 800, 600)
    assert ov._ring_position() == (0, 0) and len(timers) == 1  # leaves the cursor
    clock.t += FLY_S / 5
    ov.set_hint(1, 803, 602)  # jitter mid-flight keeps the same flight
    assert len(timers) == 1 and ov._flight[0] == (0, 0)
    clock.t += FLY_S
    assert ov._ring_position() == (803, 602)  # rule 3: rests on the control
    ov.set_hint(1, 808, 605)  # perception jitter snaps, no new flight
    assert ov._ring_position() == (808, 605) and len(timers) == 1
    ov.clear_hint(1)
    assert ov._hint is None and ov._flight is None


def test_a_hint_already_under_the_cursor_does_not_fly(monkeypatch):
    ov, _, timers = _overlay(monkeypatch)
    ov.set_hint(1, 10, 10)
    assert ov._ring_position() == (10, 10) and timers == []


def test_destroying_the_overlay_forgets_its_ring(monkeypatch):
    ov, _, _ = _overlay(monkeypatch)
    monkeypatch.setattr(ov.win32gui, "DestroyWindow", lambda h: None)
    monkeypatch.setattr(ov.win32gui, "PumpWaitingMessages", lambda: None)
    ov.set_hint(1, 800, 600)
    ov.destroy_overlay_window(1)
    assert ov._hint is None and ov._flight is None


def test_destroying_the_overlay_forgets_its_cue_and_sketch(monkeypatch):
    ov, _, _ = _overlay(monkeypatch)
    monkeypatch.setattr(ov.win32gui, "DestroyWindow", lambda h: None)
    monkeypatch.setattr(ov.win32gui, "PumpWaitingMessages", lambda: None)
    ov._cue, ov._sketch = object(), object()
    ov.destroy_overlay_window(1)
    assert ov._cue is None and ov._sketch is None
