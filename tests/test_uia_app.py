from pywinauto import Desktop

from tests.uia_app import (
    BTN_DELETE,
    BTN_EXPORT,
    EDIT_FILENAME,
    LBL_STATUS,
    SyntheticApp,
)


def _elements(title):
    win = Desktop(backend="uia").window(title_re=f".*{title}.*")
    win.wait("exists", timeout=5)
    return {
        c.element_info.automation_id: (c.window_text(), c.element_info.control_type)
        for c in win.descendants()
        if c.element_info.automation_id
    }


def test_buttons_expose_automation_ids_and_names():
    with SyntheticApp() as app:
        app.pump()
        found = _elements(app.title)
    assert found[str(BTN_EXPORT)] == ("Export", "Button")
    assert found[str(BTN_DELETE)] == ("Delete", "Button")


def test_locale_changes_names_but_not_automation_ids():
    with SyntheticApp(title="GhostCursorTestAppHi", locale="hi-IN") as app:
        app.pump()
        found = _elements(app.title)
    assert found[str(BTN_EXPORT)][0] == "निर्यात"
    assert found[str(BTN_EXPORT)][1] == "Button"


def test_edit_and_static_expose_automation_ids_and_status_updates():
    with SyntheticApp() as app:
        app.pump()
        found = _elements(app.title)
        assert str(EDIT_FILENAME) in found
        assert found[str(EDIT_FILENAME)][1] == "Edit"

        assert str(LBL_STATUS) in found
        assert found[str(LBL_STATUS)][0] == "Ready"

        app.click_button(BTN_EXPORT)
        found_after = _elements(app.title)
        assert found_after[str(LBL_STATUS)][0] == f"clicked:{BTN_EXPORT}"
        assert found_after[str(LBL_STATUS)][0] != found[str(LBL_STATUS)][0]
