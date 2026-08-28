"""Test-lane ownership.

Keep the categories in one reviewed table instead of scattering decorators
through old modules. New desktop-dependent modules must be added explicitly;
unlisted tests stay in the fast hermetic lane.
"""

from __future__ import annotations

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

    Several state-machine tests drive the real ``run_tour`` loop while faking
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
