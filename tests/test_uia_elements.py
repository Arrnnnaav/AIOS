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


def test_vscode_walk_returns_only_the_targeted_file_menu(monkeypatch):
    class Rect:
        left, top, right, bottom = 10, 20, 80, 50

    class Info:
        name = "Open Folder..."
        control_type = "Hyperlink"
        automation_id = ""
        rectangle = Rect()

    monkeypatch.setattr(
        uia, "windows_matching_executable", lambda title, exe: [4242]
    )
    monkeypatch.setattr(uia, "_vscode_open_folder_element_info", lambda hwnd: Info())
    monkeypatch.setattr(uia, "is_on_screen", lambda bbox: True)

    elements = uia.iter_vscode_elements(".*Visual Studio Code.*")

    assert len(elements) == 1
    assert elements[0].name == "Open Folder..."
    assert elements[0].control_type == "Hyperlink"
    assert elements[0].bbox == (10, 20, 80, 50)


def test_vscode_walk_degrades_to_empty_for_a_provider_failure(monkeypatch):
    monkeypatch.setattr(
        uia, "windows_matching_executable", lambda title, exe: [4242]
    )

    def blocked(_):
        raise OSError("provider unavailable")

    monkeypatch.setattr(uia, "_vscode_open_folder_element_info", blocked)
    assert uia.iter_vscode_elements(".*Visual Studio Code.*") == []


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
