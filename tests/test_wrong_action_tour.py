"""D037 wrong-action recovery through the compiled executor."""
from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.compiled_tour import RunOutcome, TickInput, execute_compiled_workflow
from tests.test_compiled_workflow import _workflow


class _Clock:
    def __init__(self): self.t=0.0
    def __call__(self): return self.t
    def sleep(self, s): self.t += s


class _Renderer:
    def __init__(self): self.shown=[]
    def show(self, grounded, text): self.shown.append((grounded.automation_id, text))
    def clear(self): pass
    def settle(self): pass


def _run(visited):
    workflow, _ = _workflow(); clock=_Clock(); renderer=_Renderer(); reads=[]
    target=Element("Open Folder...", "Button", "target", (1,2,30,20))
    def observe():
        reads.append(1)
        focus=visited if len(reads) >= 3 else ()
        return TickInput("Welcome - Visual Studio Code", {"open_folder":(target,)}, (target,), focus_visited=focus)
    result=execute_compiled_workflow(
        workflow, observe=observe, renderer=renderer,
        clock=clock, sleeper=clock.sleep, seconds=2.0,
    )
    return result, renderer


def test_a_wrong_action_prints_once_and_re_asserts_the_hint():
    result, renderer=_run(("wrong",))
    assert result.outcome is RunOutcome.TIMED_OUT
    assert len(renderer.shown) >= 2


def test_no_line_when_focus_stayed_on_the_target():
    _result, renderer=_run(("target",))
    assert len(renderer.shown) == 1


def test_worker_published_hwnd_enables_space_confirmation(monkeypatch):
    import ghostcursor.run as run_module
    monkeypatch.setattr(run_module.win32gui, "GetForegroundWindow", lambda: 101)
    monkeypatch.setattr(run_module, "key_was_pressed", lambda _vk, **_kwargs: True)
    assert run_module.space_confirmation_requested(101, None)
    assert not run_module.space_confirmation_requested(202, None)
