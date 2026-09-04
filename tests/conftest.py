"""Test-lane ownership.

Keep the categories in one reviewed table instead of scattering decorators
through old modules. New desktop-dependent modules must be added explicitly;
unlisted tests stay in the fast hermetic lane.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


INTERACTIVE_MODULES = {
    "test_appinfo.py",
    "test_bar.py",
    "test_focus.py",
    "test_overlay_freshness.py",
    "test_persistence_e2e.py",
    "test_tick_latency.py",
    "test_uia_app.py",
    "test_uia_elements.py",
    "test_warmup_real_window.py",
}

PIXEL_MODULES = {
    "test_guided_tour.py",
}

HUNG_MODULES = {
    "test_hung_window.py",
    "test_perception_service_hung.py",
    "test_run_threaded.py",
}


@pytest.fixture(scope="session", autouse=True)
def isolated_plugin_runtime(tmp_path_factory: pytest.TempPathFactory, request):
    """No test may bootstrap plugins into the user's real local store."""

    name = "GHOSTCURSOR_PLUGIN_ROOT"
    previous = os.environ.get(name)
    os.environ[name] = str(tmp_path_factory.mktemp("plugin-runtime"))

    def restore() -> None:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous

    request.addfinalizer(restore)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        name = Path(str(item.path)).name
        if name in INTERACTIVE_MODULES:
            item.add_marker(pytest.mark.interactive)
        if name in PIXEL_MODULES:
            item.add_marker(pytest.mark.pixel)
        if name in HUNG_MODULES:
            item.add_marker(pytest.mark.hung)


@pytest.fixture(autouse=True)
def no_real_control_bar_in_hermetic_tests(request: pytest.FixtureRequest, monkeypatch):
    """Keep the default lane genuinely desktop-independent.

    Several state-machine tests drive the real compiled tour while faking
    only its full-screen overlay. Without this guard they can still create the
    Win32 control rail. Desktop, pixel, and hung-window lanes retain their
    explicit environment and are not changed here.
    """

    if any(
        request.node.get_closest_marker(name) is not None
        for name in ("interactive", "pixel", "hung")
    ):
        return

    from ghostcursor.overlay import bar

    monkeypatch.setattr(bar, "create_bar_window", lambda: None)


@pytest.fixture(autouse=True)
def no_real_keyboard_in_hermetic_tests(request: pytest.FixtureRequest, monkeypatch):
    """A hermetic test must not read the machine's real ESC key.

    `escape_pressed()` calls `GetAsyncKeyState`, whose low bit means "pressed
    since the previous call" — so ANY ESC tap anywhere on the machine, at any
    point since the last poll, makes it true. `_run_compiled_tour` checks it
    before creating the overlay and returns 0 if it is set, which is correct
    for production and fatal for a test that asserts what happens after that
    point.

    That is what made
    `test_run_tour_creates_overlay_only_after_live_revalidation` fail twice on
    a full lane and pass in isolation and on the lanes either side: it does not
    pin `escape_pressed`, so it failed exactly when someone had pressed ESC —
    which, during an acceptance campaign where ESC is the documented abort key,
    happens often. It was recorded as an unexplained failure for a day.

    Pinned to False rather than to a fixture-controlled flag: a test that cares
    about ESC sets it itself, and `monkeypatch.setattr` inside the test body
    runs after this and wins. Lanes that drive a real desktop are left alone,
    exactly as the control-bar fixture above leaves them.
    """

    if any(
        request.node.get_closest_marker(name) is not None
        for name in ("interactive", "pixel", "hung")
    ):
        return

    import ghostcursor.run as run_module

    monkeypatch.setattr(run_module, "escape_pressed", lambda: False)
