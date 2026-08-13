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


def test_iter_elements_skips_offscreen_elements():
    with SyntheticApp() as app:
        elements = iter_elements(f".*{app.title}.*")
    # Window chrome buttons report (0,0,0,0); is_on_screen must filter them.
    assert all(e.bbox != (0, 0, 0, 0) for e in elements)
