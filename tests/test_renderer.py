from ghostcursor.reasoning.grounding import GroundedTarget
from ghostcursor.reasoning.renderer import OverlayRenderer

TARGET = GroundedTarget((100, 200, 200, 240), 1, "1001", "Button", "Export")


class SpyOverlay:
    def __init__(self):
        self.hints = []
        self.clears = 0

    def set_hint(self, hwnd, x, y, radius=24):
        self.hints.append((hwnd, x, y, radius))

    def clear_hint(self, hwnd):
        self.clears += 1


def test_show_points_at_the_centre_of_the_grounded_element():
    spy = SpyOverlay()
    OverlayRenderer(hwnd=42, overlay=spy).show(TARGET, "Click Export.")
    assert spy.hints == [(42, 150, 220, 24)]


def test_show_records_the_instruction_for_display():
    renderer = OverlayRenderer(hwnd=42, overlay=SpyOverlay())
    renderer.show(TARGET, "Click Export.")
    assert renderer.last_instruction == "Click Export."


def test_clear_clears_the_overlay_and_the_instruction():
    spy = SpyOverlay()
    renderer = OverlayRenderer(hwnd=42, overlay=spy)
    renderer.show(TARGET, "Click Export.")
    renderer.clear()
    assert spy.clears == 1
    assert renderer.last_instruction is None
