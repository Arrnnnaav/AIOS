"""Browser via CDP (D184). Launches Orbyn's own Chrome/Edge, so interactive.
Observation is read-only; a page action refuses without approval and honours
the deny list, exactly like Act."""

from __future__ import annotations

import time

import pytest

from ghostcursor.harness import browser

pytestmark = pytest.mark.interactive

PAGE = (
    "data:text/html,<title>T</title>"
    "<button onclick=\"document.title='CLICKED'\">Save</button>"
    "<input id=i aria-label='Note'><button>Delete</button>"
)


@pytest.fixture(scope="module")
def _browser():
    if browser.find_browser() is None:
        pytest.skip("no Chrome or Edge")
    with browser.Browser.launch(PAGE) as b:
        yield b  # one browser for the module; a fresh launch per test raced


@pytest.fixture
def page(_browser):
    p = _browser.page()
    p.navigate(PAGE)  # reset the page for each test
    yield _browser, p
    p.close()


def test_observe_reads_named_interactive_controls_with_boxes(page):
    _, p = page
    controls = {c.name: c for c in p.controls()}
    assert {"Save", "Note", "Delete"} <= set(controls)
    assert controls["Save"].role == "button" and controls["Note"].role == "textbox"
    assert controls["Save"].rect is not None


def test_actions_are_gated_like_act(page):
    b, p = page
    controls = {c.name: c for c in p.controls()}
    with pytest.raises(PermissionError, match="approval"):
        p.click(controls["Save"])  # not approved
    with pytest.raises(PermissionError, match="deny"):
        p.click(controls["Delete"], approved=True, deny=["delete"])


def test_approved_click_and_type_land(page):
    b, p = page
    controls = {c.name: c for c in p.controls()}
    p.click(controls["Save"], approved=True)
    time.sleep(0.3)
    assert any(t.title == "CLICKED" for t in b.tabs())
    p.type_text(controls["Note"], "hello", approved=True)
    value = p.cmd(
        "Runtime.evaluate",
        {"expression": "document.getElementById('i').value", "returnByValue": True},
    )
    assert value["result"]["value"] == "hello"


def test_drive_clicks_toward_a_goal_then_stops_on_done(page):
    """Wiring check with a scripted gateway (no live model): drive clicks Save,
    then the gateway says DONE."""
    from ghostcursor.providers.schemas import Choice

    b, p = page
    save = next(c for c in p.controls() if c.name == "Save")
    calls = {"n": 0}

    class G:
        def choose(self, envelope, option_ids, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                sid = str(save.backend_node_id)
                assert sid in option_ids and "DONE" in option_ids
                return Choice(sid, {sid: 0.95})
            return Choice("DONE", {"DONE": 1.0})

    r = p.drive("click Save", G(), approved=True, deny=["delete"])
    assert r.status == "done" and r.steps == 1
    import time as _t; _t.sleep(0.3)
    assert any(t.title == "CLICKED" for t in b.tabs())


def test_drive_refuses_without_approval(page):
    _, p = page
    r = p.drive("do it", object(), approved=False)
    assert r.status == "not_approved"


def test_closing_the_browser_deletes_its_temporary_profile(tmp_path, monkeypatch):
    from ghostcursor.harness.browser import Browser

    profile = tmp_path / "orbyn-cdp-x"
    (profile / "Default").mkdir(parents=True)
    (profile / "Default" / "Cookies").write_bytes(b"c")

    class Proc:
        pid = 4242

        def poll(self):
            return None

        def wait(self, timeout):
            return 0

    ran = []
    monkeypatch.setattr(
        "ghostcursor.harness.browser.subprocess.run", lambda args, **k: ran.append(args)
    )
    Browser(Proc(), 0, str(profile)).close()
    assert not profile.exists()
    assert ran == [["taskkill", "/PID", "4242", "/T", "/F"]]  # the tree, by PID


def test_a_browser_that_already_exited_is_never_killed_by_pid(tmp_path, monkeypatch):
    from ghostcursor.harness.browser import Browser

    class Proc:
        pid = 4242

        def poll(self):
            return 0  # gone: the PID may belong to someone else now

        def wait(self, timeout):
            return 0

    ran = []
    monkeypatch.setattr(
        "ghostcursor.harness.browser.subprocess.run", lambda args, **k: ran.append(args)
    )
    Browser(Proc(), 0, str(tmp_path / "p")).close()
    assert ran == []
