import pytest
from pywinauto import Desktop

from ghostcursor.perception import uia
from ghostcursor.perception.uia import iter_elements
from tests.uia_app import BTN_EXPORT, SyntheticApp


def test_iter_elements_exposes_automation_id_and_bbox():
    with SyntheticApp() as app:
        elements = iter_elements(f".*{app.title}.*")

    export = next(e for e in elements if e.automation_id == str(BTN_EXPORT))
    assert export.name == "Export"
    assert export.control_type == "Button"
    left, top, right, bottom = export.bbox
    assert right > left and bottom > top


def test_iter_elements_filters_out_degenerate_chrome_elements():
    with SyntheticApp() as app:
        # Enumerate raw descendants to check if any have degenerate rects
        try:
            window = Desktop(backend="uia").window(title_re=f".*{app.title}.*")
            window.wait("exists", timeout=3)
            raw_descendants = window.descendants()
        except Exception:
            pytest.skip("Could not enumerate raw descendants")

        raw_rects = []
        for ctrl in raw_descendants:
            try:
                rect = ctrl.rectangle()
                bbox = (rect.left, rect.top, rect.right, rect.bottom)
                raw_rects.append(bbox)
            except Exception:
                continue

        # Check if any raw descendant has degenerate dimensions
        has_degenerate = any(
            (bbox[2] - bbox[0] <= 0 or bbox[3] - bbox[1] <= 0) for bbox in raw_rects
        )
        if not has_degenerate:
            pytest.skip(
                "No degenerate elements found in raw descendants on this machine"
            )

        # Now check filtered elements
        elements = iter_elements(f".*{app.title}.*")

        # iter_elements should have fewer elements than raw descendants
        # (because it filters out degenerate ones)
        assert len(elements) < len(raw_descendants)

        # None of the returned elements should be degenerate
        assert all(
            (e.bbox[2] - e.bbox[0] > 0 and e.bbox[3] - e.bbox[1] > 0) for e in elements
        )


def test_vscode_terminal_walk_returns_only_trusted_exact_buttons(monkeypatch):
    class Rect:
        left, top, right, bottom = 10, 20, 180, 50

    class ElementInfo:
        control_type = "Button"
        automation_id = ""

    class Control:
        element_info = ElementInfo()

        def __init__(self, name):
            self.name = name

        def window_text(self):
            return self.name

        def rectangle(self):
            return Rect()

    controls = [
        Control("Toggle Panel (Ctrl+J)"),
        Control("Terminal Section"),
        Control("Toggle Chat"),
    ]

    class Window:
        def descendants(self, *, control_type):
            assert control_type == "Button"
            return controls

    class FakeDesktop:
        def __init__(self, *, backend):
            assert backend == "uia"

        def window(self, *, handle):
            assert handle == 4242
            return Window()

    def matching_executable(title_re, executable_name):
        assert title_re == ".*Visual Studio Code.*"
        assert executable_name == "code.exe"
        return [4242]

    monkeypatch.setattr(uia, "windows_matching_executable", matching_executable)
    monkeypatch.setattr(uia, "Desktop", FakeDesktop)
    monkeypatch.setattr(uia, "is_on_screen", lambda bbox: True)

    elements = uia.iter_vscode_terminal_elements(".*Visual Studio Code.*")

    assert [element.name for element in elements] == [
        "Toggle Panel (Ctrl+J)",
        "Terminal Section",
    ]


def test_vscode_terminal_walk_degrades_to_empty_for_provider_failure(monkeypatch):
    monkeypatch.setattr(uia, "windows_matching_executable", lambda *args: [4242])

    class BrokenDesktop:
        def __init__(self, *, backend):
            raise OSError("provider unavailable")

    monkeypatch.setattr(uia, "Desktop", BrokenDesktop)

    assert uia.iter_vscode_terminal_elements(".*Visual Studio Code.*") == []


def test_executable_matching_rejects_a_title_collision(monkeypatch):
    monkeypatch.setattr(uia, "windows_matching", lambda _: [1, 2])
    monkeypatch.setattr(
        uia,
        "_executable_name_for_hwnd",
        lambda hwnd: "chrome.exe" if hwnd == 1 else "code.exe",
    )

    assert uia.windows_matching_executable(
        ".*Visual Studio Code.*", "Code.exe"
    ) == [2]
