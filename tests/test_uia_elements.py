import pytest
from pywinauto import Desktop

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
