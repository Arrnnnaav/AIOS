"""Interactive D035 check through the real compiled worker wiring."""
import threading
import time

from ghostcursor.perception.service import PerceptionService
from tests.test_compiled_workflow import _target, _window, _workflow
from tests.uia_app import SyntheticApp


class _Renderer:
    def show(self, *args): pass
    def clear(self): pass
    def settle(self): pass


def test_real_compiled_perception_publishes_the_bound_window_handle():
    from ghostcursor.perception.compiled import build_compiled_perception
    from ghostcursor.perception.uia import windows_matching

    with SyntheticApp(title="GhostCursorCompiledWarmupHandle") as app:
        hwnd = windows_matching(f".*{app.title}.*")[0]
        workflow, _ = _workflow(target=_target(_window(hwnd=hwnd, title=app.title)))
        perception = build_compiled_perception(workflow, time.monotonic)
        _source, _grounding, stop = perception.start()
        try:
            deadline = time.monotonic() + 5.0
            observation = None
            while observation is None and time.monotonic() < deadline:
                app.pump()
                observation = perception.service.latest()
                time.sleep(0.001)
        finally:
            stop()
    assert observation is not None
    assert observation.target_hwnd == hwnd


def test_the_tick_loop_suppresses_tier2_through_the_real_wiring(monkeypatch):
    import ghostcursor.run as run_module
    from ghostcursor.perception.uia import windows_matching

    budget = 1.5
    requests = []
    real_request = PerceptionService.request_tier2
    def request(self, step):
        requests.append(time.monotonic())
        return real_request(self, step)
    monkeypatch.setattr(PerceptionService, "request_tier2", request)
    monkeypatch.setattr(run_module, "escape_pressed", lambda: False)

    with SyntheticApp(title="GhostCursorCompiledWarmup") as app:
        hwnd = windows_matching(f".*{app.title}.*")[0]
        workflow, _ = _workflow(target=_target(_window(hwnd=hwnd, title=app.title)))
        started = time.monotonic()
        result = {}
        def run():
            result["rc"] = run_module._run_compiled_tour(
                workflow, seconds=3.5, clock=time.monotonic, sleeper=time.sleep,
                warmup_budget_s=budget, create_overlay=lambda: 0,
                renderer=_Renderer(),
            )
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        deadline = started + 8.0
        while thread.is_alive() and time.monotonic() < deadline:
            app.pump(); time.sleep(0.001)
        thread.join(timeout=2.0)

    assert not thread.is_alive()
    assert "rc" in result
    assert requests, "tier 2 never became eligible"
    assert all(moment - started >= budget for moment in requests)
