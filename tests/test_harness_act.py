"""Act on any application (D182): the user approves the whole plan first;
each step is performed once, at the centre of the freshly observed control;
risky controls still wait for the user; nothing acts before approval."""

from __future__ import annotations

import pytest

from ghostcursor.harness import act
from ghostcursor.harness.teach import ACT_SETTLE_S, ModelTeachSession, Phase
from ghostcursor.providers import ExpectedChange, PlanStep, TeachPlan
from ghostcursor.providers.schemas import parse_teach_plan
from tests.test_harness_teach import FakeGateway, SyncSlot, _c, _choice, _frame

E = ExpectedChange
#: The real scan, kept before the autouse fixture below replaces it.
REAL_HELD_INPUT = act.held_input


@pytest.fixture(autouse=True)
def _nothing_held(monkeypatch):
    """perform() waits while the real user holds a key; tests must not depend
    on this machine's keyboard."""

    monkeypatch.setattr(act, "held_input", lambda: False)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _session(steps, choices, plan_given=False):
    plan = TeachPlan(tuple(steps))
    done = []
    clock = Clock()
    session = ModelTeachSession(
        "fill the form",
        FakeGateway(plan, choices),
        SyncSlot(),
        clock=clock,
        plan=plan if plan_given else None,
        act=lambda step, target: done.append((step.action, target.name)) or "ok",
    )
    return session, done, clock


def test_nothing_acts_until_the_whole_plan_is_approved():
    session, done, _ = _session(
        [PlanStep("Click Insert", E.CHOSEN_STATE_CHANGES)], [_choice("c1")]
    )
    frame = _frame([_c(1)])
    shown = session.tick(frame)
    assert shown.phase is Phase.APPROVE and "Click Insert" in shown.message
    assert session.tick(frame).phase is Phase.APPROVE and done == []
    acted = session.tick(frame, confirm=True)
    assert acted.phase is Phase.SHOWING and done == [("click", "Insert")]


def test_a_reviewed_plan_still_needs_approval_to_act():
    session, done, _ = _session(
        [PlanStep("Click Insert", E.CHOSEN_STATE_CHANGES)],
        [_choice("c1")],
        plan_given=True,
    )
    assert session.tick(_frame([_c(1)])).phase is Phase.APPROVE and done == []


def test_each_step_acts_once_then_completes_on_change_or_settle():
    session, done, clock = _session(
        [
            PlanStep("Click Insert", E.CHOSEN_STATE_CHANGES),
            PlanStep("Type the title", E.CHOSEN_STATE_CHANGES, "type", "Q3"),
        ],
        [_choice("c1"), _choice("c2")],
    )
    title = _c(2, "Title", "Edit", rect=(10, 100, 200, 130))
    session.tick(_frame([_c(1, state="selected=0"), title]))
    session.tick(_frame([_c(1, state="selected=0"), title]), confirm=True)
    session.tick(_frame([_c(1, state="selected=0"), title]))  # no second click
    assert done == [("click", "Insert")]
    session.tick(_frame([_c(1, state="selected=1"), title], frame_id=2))
    assert session.completed[0] == (1, "observed chosen_state_changes")
    assert done[-1] == ("type", "Title")
    clock.now = ACT_SETTLE_S
    result = session.tick(_frame([_c(2, "Title", "Edit")], frame_id=4))
    assert result.phase is Phase.DONE
    assert session.completed[1] == (2, "acted (no change seen)")


def test_a_risky_control_waits_for_the_user_before_acting():
    session, done, _ = _session(
        [PlanStep("Delete the slide", E.CHOSEN_DISAPPEARS)], [_choice("c1")]
    )
    frame = _frame([_c(1, "Delete Slide", "Button")])
    session.tick(frame)
    session.tick(frame, confirm=True)  # approves the plan
    assert session.tick(frame).phase is Phase.CONFIRM_RISK and done == []
    session.tick(frame, confirm=True)
    assert done == [("click", "Delete Slide")]


def test_a_failed_action_blocks_instead_of_retrying_blind():
    plan = TeachPlan((PlanStep("Press", E.TITLE_CHANGES, "keys", "esc"),))
    session = ModelTeachSession(
        "x",
        FakeGateway(plan, [_choice("c1")]),
        SyncSlot(),
        clock=lambda: 0.0,
        plan=plan,
        act=lambda step, target: act.perform(
            step,
            target,
            send=lambda e: None,
            click=lambda x, y: None,
            check=lambda x, y, window: None,
        ),
    )
    frame = _frame([_c(1)])
    session.tick(frame, confirm=True)
    assert session.tick(frame).phase is Phase.BLOCKED


def test_perform_clicks_the_observed_centre_then_sends_the_action():
    clicks, sent = [], []
    target = _frame([_c(1, "Title", "Edit", rect=(100, 200, 300, 240))]).candidates[0]

    def run(action, text=""):
        clicks.clear(), sent.clear()
        return act.perform(
            PlanStep("s", E.TITLE_CHANGES, action, text),
            target,
            send=sent.append,
            click=lambda x, y: clicks.append((x, y)),
            pause=lambda s: None,
            check=lambda x, y, window: None,
        )

    assert run("click") == "clicked Title" and clicks == [(200, 220)] and not sent
    run("type", "hi\n")
    assert len(sent[0]) == 6  # h, i, enter: down+up each
    run("paste")
    assert [e.u.ki.wVk for e in sent[0]] == [0x11, 0x56, 0x56, 0x11]
    run("keys", "ctrl+shift+s")
    assert [e.u.ki.wVk for e in sent[0]][:3] == [0x11, 0x10, 0x53]
    assert run("none") == "nothing to do" and not clicks


@pytest.mark.parametrize("chord", ["", "ctrl+banana", "ctrl++", "ctrl+ ", "+s"])
def test_bad_key_chords_are_refused(chord):
    with pytest.raises(ValueError):
        act.chord_events(chord)


# The stop key is refused by chord_events' OWN guard, not incidentally by an
# unknown-key lookup -- so assert the guard's message fires, and in any case
# (an uppercase ESC must not slip past casefold). This is the model being
# unable to synthesize the user's stop key (D020).
@pytest.mark.parametrize(
    "chord",
    ["esc", "ESC", "escape", "ESCAPE", "ctrl+escape", "Ctrl+Escape", "shift+ESC"],
)
def test_the_stop_key_is_refused_by_the_guard_in_any_case(chord):
    with pytest.raises(ValueError, match="refused key chord"):
        act.chord_events(chord)


# The Windows key and Alt+Tab leave the approved window (shell, Run dialog,
# lock screen, another app); a model-written plan must not reach them.
@pytest.mark.parametrize(
    "chord",
    [
        "win", "WIN+r", "win+d", "alt+tab", "Alt+Shift+Tab",
        # other whitespace must not slip a name past the guard (review of d0f3e5a)
        "win\t", "\twin+r", "win\u00a0", "alt\t+tab", "alt+tab\n", "esc\t",
    ],
)  # fmt: skip
def test_keys_that_leave_the_approved_window_are_refused(chord):
    with pytest.raises(ValueError, match="refused key chord"):
        act.chord_events(chord)


@pytest.mark.parametrize("key", ["\u00aa", "\u00b3", "\u00e9"])
def test_a_non_ascii_letter_is_not_a_key(key):
    # isalnum() is true for these, and ord() would be a browser/media key.
    with pytest.raises(ValueError):
        act.vk_of(key)


def test_ordinary_shortcuts_still_pass():
    assert len(act.chord_events("ctrl+shift+s")) == 6
    assert len(act.chord_events("alt+f")) == 4
    assert len(act.chord_events("tab")) == 2


def test_plans_carry_an_action_and_old_plans_default_to_click():
    old = parse_teach_plan(
        '{"steps":[{"instruction":"Click Insert","expected_change":"title_changes"}]}'
    )
    assert old.steps[0].action == "click" and old.steps[0].text == ""
    new = parse_teach_plan(
        '{"steps":[{"instruction":"Type","expected_change":"title_changes",'
        '"action":"type","text":"Q3 deck"}]}'
    )
    assert (new.steps[0].action, new.steps[0].text) == ("type", "Q3 deck")
    with pytest.raises(Exception):
        parse_teach_plan(
            '{"steps":[{"instruction":"x","expected_change":"title_changes",'
            '"action":"format_disk","text":""}]}'
        )


def test_a_blocked_desktop_or_elevated_window_gets_no_input():
    target = _frame([_c(1)]).candidates[0]
    clicks = []
    with pytest.raises(PermissionError, match="administrator"):
        act.perform(
            PlanStep("s", E.TITLE_CHANGES),
            target,
            click=lambda x, y: clicks.append((x, y)),
            check=lambda x, y, window: "that window runs as administrator",
        )
    assert clicks == []


def test_this_process_can_ask_its_own_elevation():
    assert act._elevated() in (True, False)


def test_a_denied_control_is_never_acted_on_even_if_jev_picks_it():
    session, done, _ = _session(
        [PlanStep("Remove the row", E.CHOSEN_DISAPPEARS)], [_choice("c1")]
    )
    session.deny = ("delete",)
    frame = _frame([_c(1, "Delete row", "Button")])
    session.tick(frame)
    session.tick(frame, confirm=True)  # approve plan
    out = session.tick(frame, confirm=True)  # past risk gate
    assert out.phase is Phase.BLOCKED and "not to touch" in out.message
    assert done == []


def test_an_empty_deny_entry_blocks_nothing():
    session, done, _ = _session(
        [PlanStep("Click it", E.CHOSEN_STATE_CHANGES)], [_choice("c1")]
    )
    session.deny = ("",)  # must not match every control
    frame = _frame([_c(1, "Save", "Button")])
    session.tick(frame)
    session.tick(frame, confirm=True)
    assert done == [("click", "Save")]


def test_act_audit_writes_a_screen_text_free_line(tmp_path, monkeypatch):
    import json

    from ghostcursor.harness import teach_live

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    class B:
        class identity:
            executable = "powerpnt.exe"

    teach_live._audit(
        [B()], [(1, "observed chosen_state_changes"), (2, "you confirmed")], 0
    )
    path = tmp_path / "GhostCursor" / "act-audit.jsonl"
    line = json.loads(path.read_text(encoding="utf-8").strip())
    assert line["apps"] == ["powerpnt.exe"] and line["code"] == 0
    assert [s["step"] for s in line["steps"]] == [1, 2]
    assert "goal" not in line and "name" not in json.dumps(line)


def test_step_verification_relooks_on_a_confident_no(monkeypatch):
    """In Act, a settle with no observed change asks Jev; a confident 'no'
    re-looks instead of counting the step done."""
    from ghostcursor.providers.schemas import Choice

    session, done, clock = _session(
        [PlanStep("Click Insert", E.CHOSEN_STATE_CHANGES)], [_choice("c1")]
    )
    session.gateway.judge = lambda env, qs, **k: {
        "happened": Choice("no", {"no": 0.95, "yes": 0.05})
    }
    frame = lambda fid=1: _frame([_c(1, state="selected=0")], frame_id=fid)
    session.tick(frame())  # APPROVE
    session.tick(frame(), confirm=True)  # approve -> act
    assert done == [("click", "Insert")]
    clock.now = ACT_SETTLE_S
    out = session.tick(frame(fid=2))  # settle, no change: Jev says no
    assert (
        out.phase is Phase.CHOOSING and session.completed == []
    )  # re-looked, not done


def test_step_verification_lets_the_step_stand_when_jev_is_unsure(monkeypatch):
    from ghostcursor.providers.schemas import Choice

    session, done, clock = _session(
        [PlanStep("Click Insert", E.CHOSEN_STATE_CHANGES)], [_choice("c1")]
    )
    session.gateway.judge = lambda env, qs, **k: {
        "happened": Choice("unsure", {"unsure": 0.9})
    }
    frame = lambda fid=1: _frame([_c(1, state="selected=0")], frame_id=fid)
    session.tick(frame())
    session.tick(frame(), confirm=True)
    clock.now = ACT_SETTLE_S
    out = session.tick(frame(fid=2))
    assert session.completed == [(1, "acted (Jev: likely done)")]  # fail-open


def test_paste_text_carries_known_text_then_restores_the_clipboard():
    """Cross-app context carry (D182 activation): paste_text puts Orbyn's text
    on the clipboard, focuses the observed control, pastes with ctrl+v, then
    restores the user's prior clipboard so Orbyn's text is never left behind."""

    target = _frame([_c(1, "Body", "Edit", rect=(100, 200, 300, 240))]).candidates[0]
    clicks, sent, clip_writes = [], [], []

    out = act.perform(
        PlanStep(
            "Paste the address", E.CHOSEN_STATE_CHANGES, "paste_text", "221B Baker St"
        ),
        target,
        send=sent.append,
        click=lambda x, y: clicks.append((x, y)),
        pause=lambda s: None,
        check=lambda x, y, window: None,
        get_clip=lambda: "USER PRIOR",
        set_clip=clip_writes.append,
        later=lambda job: job(),
    )
    assert out == "pasted 13 characters"
    assert clicks == [(200, 220)]  # focused the observed control first
    assert [e.u.ki.wVk for e in sent[0]] == [0x11, 0x56, 0x56, 0x11]  # ctrl+v
    # set to our text, then restored to the user's prior clipboard (never left ours)
    assert clip_writes == ["221B Baker St", "USER PRIOR"]


def test_paste_text_restores_the_clipboard_even_if_the_paste_fails():
    """The guard (D018 mutation target): the restore is in a finally, so a
    failed paste still puts the user's clipboard back -- Orbyn's text is never
    stranded on the clipboard."""

    target = _frame([_c(1, "Body", "Edit", rect=(10, 10, 50, 50))]).candidates[0]
    clip_writes = []

    def boom(_events):
        raise OSError("SendInput failed")

    with pytest.raises(OSError, match="SendInput failed"):
        act.perform(
            PlanStep("Paste", E.CHOSEN_STATE_CHANGES, "paste_text", "secret-carry"),
            target,
            send=boom,
            click=lambda x, y: None,
            pause=lambda s: None,
            check=lambda x, y, window: None,
            get_clip=lambda: "USER PRIOR",
            set_clip=clip_writes.append,
            later=lambda job: job(),
        )
    assert clip_writes[-1] == "USER PRIOR"  # restored despite the failure
    assert "secret-carry" not in clip_writes[-1:]  # ours is not what's left


def test_paste_text_with_no_text_touches_nothing():
    target = _frame([_c(1, "Body", "Edit")]).candidates[0]
    clip_writes, clicks = [], []
    out = act.perform(
        PlanStep("Paste", E.CHOSEN_STATE_CHANGES, "paste_text", ""),
        target,
        send=lambda e: None,
        click=lambda x, y: clicks.append(1),
        pause=lambda s: None,
        check=lambda x, y, window: None,
        get_clip=lambda: "USER PRIOR",
        set_clip=clip_writes.append,
        later=lambda job: job(),
    )
    assert out == "nothing to paste" and clip_writes == []


def test_paste_text_is_refused_on_a_blocked_or_elevated_window():
    """The lock/admin blocker runs before any clipboard write or paste."""

    target = _frame([_c(1, "Body", "Edit")]).candidates[0]
    clip_writes = []
    with pytest.raises(PermissionError, match="administrator"):
        act.perform(
            PlanStep("Paste", E.CHOSEN_STATE_CHANGES, "paste_text", "x"),
            target,
            send=lambda e: None,
            click=lambda x, y: None,
            pause=lambda s: None,
            check=lambda x, y, window: "that window runs as administrator",
            get_clip=lambda: "PRIOR",
            set_clip=clip_writes.append,
            later=lambda job: job(),
        )
    assert clip_writes == []  # nothing written to the clipboard


def test_paste_text_restore_failure_does_not_mask_the_real_error():
    """Tier-1 review followup: if restoring the clipboard itself fails, that
    must not propagate or hide the paste's own error."""

    target = _frame([_c(1, "Body", "Edit")]).candidates[0]
    calls = {"n": 0}

    def flaky_set(_text):
        calls["n"] += 1
        if calls["n"] == 2:  # the restore call
            raise OSError("clipboard locked at restore")

    # paste fails; restore also fails -> the ORIGINAL paste error surfaces
    with pytest.raises(OSError, match="SendInput failed"):
        act.perform(
            PlanStep("Paste", E.CHOSEN_STATE_CHANGES, "paste_text", "x"),
            target,
            send=lambda e: (_ for _ in ()).throw(OSError("SendInput failed")),
            click=lambda x, y: None,
            pause=lambda s: None,
            check=lambda x, y, window: None,
            get_clip=lambda: "PRIOR",
            set_clip=flaky_set,
            later=lambda job: job(),
        )
    # happy paste, restore fails -> still returns cleanly (error swallowed)
    calls["n"] = 0
    out = act.perform(
        PlanStep("Paste", E.CHOSEN_STATE_CHANGES, "paste_text", "hi"),
        target,
        send=lambda e: None,
        click=lambda x, y: None,
        pause=lambda s: None,
        check=lambda x, y, window: None,
        get_clip=lambda: "PRIOR",
        set_clip=flaky_set,
        later=lambda job: job(),
    )
    assert out == "pasted 2 characters"


class _Desk:
    """user32 for blocker(): default desktop, window ``hit`` at every point,
    every window top-level and in one process; ``owners``, ``classes`` and
    ``threads`` describe the windows."""

    def __init__(self, hit, owners=(), classes=(), threads=()):
        self.hit, self.owners = hit, dict(owners)
        self.classes, self.threads = dict(classes), dict(threads)

    def OpenInputDesktop(self, *_):
        return 1

    def GetUserObjectInformationW(self, _desktop, _index, name, *_):
        name.value = "Default"

    def CloseDesktop(self, _):
        pass

    def WindowFromPoint(self, _point):
        return self.hit

    def GetAncestor(self, hwnd, _flag):
        return hwnd

    def GetWindow(self, hwnd, _flag):
        return self.owners.get(hwnd, 0)

    def GetClassNameW(self, hwnd, name, _size):
        name.value = self.classes.get(hwnd, "")

    def GetWindowThreadProcessId(self, hwnd, pid):
        if pid is not None:
            pid._obj.value = 100
        return self.threads.get(hwnd, 1)


@pytest.mark.parametrize(
    "desk, refused",
    [
        (_Desk(hit=9), False),  # the bound window itself
        (_Desk(hit=7, owners={7: 9}), False),  # its own dialog
        (_Desk(hit=7, owners={7: 8, 8: 9}), False),  # a dialog of its dialog
        (_Desk(hit=7, classes={7: "#32768"}), False),  # its menu, same thread
        (_Desk(hit=7, classes={7: "#32768"}, threads={7: 2}), True),  # other thread
        (_Desk(hit=7), True),  # another window of the same app on top
        (_Desk(hit=7, owners={7: 7}), True),  # an owner cycle ends, refused
        (_Desk(hit=0), True),  # off screen
    ],
)
def test_only_the_bound_window_its_dialogs_and_menus_take_input(monkeypatch, desk, refused):
    monkeypatch.setattr(act, "_elevated", lambda pid=None: False)
    monkeypatch.setattr(act, "_user32", desk)
    reason = act.blocker(5, 5, window=9)
    assert (reason is not None and "covered" in reason) if refused else reason is None


def test_without_a_bound_window_only_the_lock_and_admin_checks_run(monkeypatch):
    monkeypatch.setattr(act, "_elevated", lambda pid=None: False)
    monkeypatch.setattr(act, "_user32", _Desk(hit=7))
    assert act.blocker(5, 5) is None


def test_perform_hands_the_bound_window_to_the_blocker():
    seen = []
    target = _c("c1", "Bold", "Button")
    act.perform(
        PlanStep("s", E.TITLE_CHANGES, action="click"),
        target,
        window=9,
        click=lambda x, y: None,
        check=lambda x, y, window: seen.append(window),
    )
    assert seen == [9]


def test_the_live_act_path_passes_the_bound_window(monkeypatch):
    from ghostcursor.harness import teach_live

    seen = []
    monkeypatch.setattr(act, "perform", lambda step, target, window: seen.append(window))
    teach_live._live_perform(None, None, 9)
    assert seen == [9]


def test_keys_are_not_sent_when_focus_moved_to_another_window(monkeypatch):
    monkeypatch.setattr(act, "_user32", _Desk(hit=9))
    sent = []
    with pytest.raises(PermissionError, match="focus moved"):
        act.perform(
            PlanStep("s", E.TITLE_CHANGES, action="type", text="secret"),
            _c("c1", "Title", "Edit"),
            window=9,
            focus=lambda: 7,  # a toast took focus after the click
            pause=lambda s: None,
            click=lambda x, y: None,
            send=sent.append,
            check=lambda x, y, window: None,
        )
    assert sent == []
    act.perform(
        PlanStep("s", E.TITLE_CHANGES, action="type", text="ok"),
        _c("c1", "Title", "Edit"),
        window=9,
        focus=lambda: 9,
        pause=lambda s: None,
        click=lambda x, y: None,
        send=sent.append,
        check=lambda x, y, window: None,
    )
    assert len(sent) == 1


def test_act_waits_for_a_held_key_to_be_released():
    held = iter([True, True, False])
    pauses = []
    act.wait_for_release(lambda: next(held), pauses.append)
    assert pauses == [0.05, 0.05]


def test_act_gives_up_inside_the_stop_budget_while_a_key_stays_held():
    pauses = []
    with pytest.raises(act.UserBusy, match="holding a key"):
        act.wait_for_release(lambda: True, pauses.append)
    assert sum(pauses) <= act.MAX_HELD_WAIT_S < 0.5  # D020: Stop within 0.5 s


def test_a_held_key_means_nothing_is_clicked_or_sent():
    clicks, sent = [], []
    with pytest.raises(act.UserBusy):
        act.perform(
            PlanStep("s", E.TITLE_CHANGES, action="type", text="hi"),
            _c("c1", "Title", "Edit"),
            held=lambda: True,
            pause=lambda s: None,
            click=lambda x, y: clicks.append((x, y)),
            send=sent.append,
            check=lambda x, y, window: None,
        )
    assert clicks == [] and sent == []


def test_a_busy_user_makes_teach_wait_a_tick_instead_of_blocking():
    plan = TeachPlan((PlanStep("Click Insert", E.CHOSEN_STATE_CHANGES),))
    busy = [True]
    done = []

    def perform(step, target):
        if busy[0]:
            raise act.UserBusy("you are holding a key or mouse button, so Orbyn is waiting")
        done.append(target.name)
        return "clicked"

    session = ModelTeachSession(
        "x", FakeGateway(plan, [_choice("c1")]), SyncSlot(), clock=lambda: 0.0, plan=plan, act=perform
    )
    frame = _frame([_c(1)])
    shown = session.tick(frame, confirm=True)
    assert shown.phase is Phase.SHOWING and "waiting" in shown.message and done == []
    busy[0] = False
    session.tick(frame)
    assert done == ["Insert"]


def test_every_event_orbyn_sends_carries_its_signature():
    events = act.text_events("a") + act.chord_events("ctrl+s")
    assert {e.u.ki.dwExtraInfo for e in events} == {act.INPUT_SIGNATURE}
    sent = []
    original = act._send
    try:
        act._send = sent.extend
        act.click_at(10, 10)
    finally:
        act._send = original
    assert {e.u.mi.dwExtraInfo for e in sent} == {act.INPUT_SIGNATURE}


def test_the_held_key_scan_never_reads_escape(monkeypatch):
    read = []

    class Keys:
        def GetAsyncKeyState(self, vk):
            read.append(vk)
            return 0

    monkeypatch.setattr(act, "_user32", Keys())
    assert REAL_HELD_INPUT() is False
    assert 0x1B not in read and {0x01, 0x10, 0x41} <= set(read)


def test_a_whole_step_with_a_held_key_stays_inside_the_stop_budget():
    pauses, calls = [], [0]

    def held():  # held through every poll, let go at the final check: the worst case
        calls[0] += 1
        return calls[0] <= round(act.MAX_HELD_WAIT_S / 0.05)

    act.perform(
        PlanStep("s", E.TITLE_CHANGES, action="paste_text", text="hello"),
        _c("c1", "Title", "Edit"),
        held=held,
        pause=pauses.append,
        click=lambda x, y: None,
        send=lambda e: None,
        check=lambda x, y, window: None,
        set_clip=lambda t: None,
        get_clip=lambda: None,
    )
    assert sum(pauses) < 0.5  # D020: Stop reaches a running Act within 0.5 s


def test_a_key_name_with_a_space_inside_still_works():
    assert [e.u.ki.wVk for e in act.chord_events("ctrl+page down")] == [0x11, 0x22, 0x22, 0x11]


def test_an_emoji_is_typed_as_its_surrogate_pair():
    events = act.text_events("a\U0001F600")
    assert [e.u.ki.wScan for e in events] == [0x61, 0x61, 0xD83D, 0xD83D, 0xDE00, 0xDE00]


def test_a_confident_no_after_typing_blocks_instead_of_typing_again():
    from ghostcursor.providers.schemas import Choice

    session, done, clock = _session(
        [PlanStep("Type the title", E.TITLE_CHANGES, action="type", text="Q3")],
        [_choice("c1"), _choice("c1")],
    )
    session.gateway.judge = lambda env, qs, **k: {
        "happened": Choice("no", {"no": 0.95, "yes": 0.05})
    }
    frame = lambda fid=1: _frame([_c(1, state="selected=0")], frame_id=fid)
    session.tick(frame())
    session.tick(frame(), confirm=True)
    clock.now = ACT_SETTLE_S
    out = session.tick(frame(fid=2))
    assert out.phase is Phase.BLOCKED and len(done) == 1


def test_step_verification_never_runs_on_the_ui_tick():
    """The verify call goes to the worker slot; a slot that has not answered
    yet leaves the tick free to return (and the loop free to read ESC)."""
    from ghostcursor.providers.schemas import Choice

    session, done, clock = _session(
        [PlanStep("Click Insert", E.CHOSEN_STATE_CHANGES)], [_choice("c1")]
    )
    session.gateway.judge = lambda env, qs, **k: {"happened": Choice("no", {"no": 0.95})}
    frame = lambda fid=1: _frame([_c(1, state="selected=0")], frame_id=fid)
    session.tick(frame())
    session.tick(frame(), confirm=True)
    submitted = []
    session.slot.submit = lambda work: submitted.append(work) or 99
    session.slot.poll = lambda rid: None
    clock.now = ACT_SETTLE_S
    out = session.tick(frame(fid=2))
    assert len(submitted) == 1 and out.phase is Phase.SHOWING and session.completed == []



def _paste(target, **kw):
    values = dict(
        send=lambda e: None,
        click=lambda x, y: None,
        pause=lambda s: None,
        check=lambda x, y, window: None,
    )
    values.update(kw)
    return act.perform(
        PlanStep("Paste", E.CHOSEN_STATE_CHANGES, "paste_text", "ours"), target, **values
    )


def test_paste_text_restores_after_the_step_returns():
    """The 0.2 s wait and the restore run off the step, so Stop is read again
    within D020's 0.5 s; the restore still happens."""

    target = _frame([_c(1, "Body", "Edit")]).candidates[0]
    clip_writes, jobs = [], []
    out = _paste(
        target, get_clip=lambda: "PRIOR", set_clip=clip_writes.append, later=jobs.append
    )
    assert out == "pasted 4 characters" and clip_writes == ["ours"] and len(jobs) == 1
    jobs[0]()
    assert clip_writes == ["ours", "PRIOR"]


def test_paste_text_over_a_picture_is_refused_before_any_input():
    target = _frame([_c(1, "Body", "Edit")]).candidates[0]
    clicks, clip_writes = [], []

    def picture():
        raise PermissionError("the clipboard holds a picture or files")

    with pytest.raises(PermissionError, match="picture"):
        _paste(
            target,
            click=lambda x, y: clicks.append(1),
            get_clip=picture,
            set_clip=clip_writes.append,
        )
    assert clicks == [] and clip_writes == []


def test_a_new_step_waits_for_the_last_paste_to_restore():
    import threading

    target = _frame([_c(1, "Body", "Edit")]).candidates[0]
    clip_writes, release = [], threading.Event()
    _paste(
        target,
        get_clip=lambda: "PRIOR",
        set_clip=clip_writes.append,
        pause=lambda s: release.wait(5) if s == 0.2 else None,
    )
    seen = []
    threading.Timer(0.1, release.set).start()
    act.perform(
        PlanStep("Click", E.CHOSEN_STATE_CHANGES),
        target,
        click=lambda x, y: seen.append(list(clip_writes)),
        pause=lambda s: None,
        check=lambda x, y, window: None,
    )
    assert seen == [["ours", "PRIOR"]]  # restored before the click went out
