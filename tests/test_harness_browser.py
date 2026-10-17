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
