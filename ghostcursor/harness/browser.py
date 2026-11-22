"""Work in the browser through the Chrome DevTools Protocol (D184; the rung
Antigravity uses via chrome-devtools-mcp, cleaner than screen pixels).

Orbyn launches its OWN Chrome/Edge window with a debugging port and a
dedicated profile -- never the person's everyday profile, never attaching to
a browser they did not hand over. Observation (tabs, the page's accessible
controls) is read-only and free. A page ACTION (click, type, key) refuses
unless the caller passes ``approved=True`` and the control is not on the deny
list -- the same gate as Act (D182): the person approves, risky controls are
never touched, and nothing is a model-supplied coordinate (every action names
a real observed node).
"""

from __future__ import annotations

import json
import os
import socket
import shutil
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
_EDGE = (
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    / r"Microsoft\Edge\Application\msedge.exe"
)
#: roles worth offering as controls (the interactive page surface).
_USEFUL = {
    "button", "link", "textbox", "searchbox", "combobox", "checkbox",
    "radio", "tab", "menuitem", "option", "switch", "slider", "listbox",
}  # fmt: skip


def find_browser() -> Path | None:
    return _CHROME if _CHROME.exists() else _EDGE if _EDGE.exists() else None


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@dataclass(frozen=True)
class PageTab:
    title: str
    url: str
    target_id: str
    ws_url: str


@dataclass(frozen=True)
class PageControl:
    """One observed, actionable node on the page. ``backend_node_id`` is CDP's
    stable handle; Orbyn acts by it, never by a model-supplied position."""

    role: str
    name: str
    backend_node_id: int
    rect: tuple[int, int, int, int] | None


class Browser:
    """Orbyn's own browser window. Use as a context manager so the process and
    its temporary profile are always cleaned up."""

    def __init__(
        self, proc: subprocess.Popen, port: int, profile: str, executable: str = ""
    ):
        self.proc, self.port, self.profile = proc, port, profile
        self.executable = executable  # "chrome.exe" / "msedge.exe", for policy

    @classmethod
    def launch(cls, url: str = "about:blank", *, timeout_s: float = 12.0) -> "Browser":
        exe = find_browser()
        if exe is None:
            raise RuntimeError("no Chrome or Edge found")
        port = _free_port()
        profile = tempfile.mkdtemp(prefix="orbyn-cdp-")
        proc = subprocess.Popen(
            [
                str(exe),
                f"--remote-debugging-port={port}",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--no-service-autorun",
                str(url),
            ]
        )
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/json/version", timeout=1
                )
                return cls(proc, port, profile, Path(exe).name.casefold())
            except Exception:
                time.sleep(0.2)
        cls(proc, port, profile).close()
        raise RuntimeError("browser did not open a debugging port in time")

    def tabs(self) -> list[PageTab]:
        raw = json.load(
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=3)
        )
        return [
            PageTab(
                t.get("title", ""), t.get("url", ""), t["id"], t["webSocketDebuggerUrl"]
            )
            for t in raw
            if t.get("type") == "page" and t.get("webSocketDebuggerUrl")
        ]

    def page(self, tab: PageTab | None = None) -> "Page":
        tab = tab or next(iter(self.tabs()))
        return Page(tab.ws_url, executable=self.executable)

    def close(self) -> None:
        try:
            if self.proc.poll() is None:  # still running, so the PID is still ours
                # Chrome's renderer and GPU children outlive a terminated parent
                # and keep the profile's files open: end the tree, by PID only.
                subprocess.run(
                    ["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            self.proc.wait(timeout=5)
        except Exception:
            pass
        # The profile holds cookies and history of the pages Orbyn visited.
        shutil.rmtree(self.profile, ignore_errors=True)

    def __enter__(self) -> "Browser":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class Page:
    """One tab, driven over CDP. Observation is read-only; actions are gated."""

    def __init__(self, ws_url: str, *, timeout_s: float = 10.0, executable: str = ""):
        import websocket  # websocket-client

        self.executable = executable
        self.ws = websocket.create_connection(ws_url, timeout=timeout_s)
        self._id = 0
        self.cmd("Page.enable")
        self.cmd("DOM.enable")
        self.cmd("Accessibility.enable")

    def cmd(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == mid:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error'].get('message')}")
                return message.get("result", {})

    def navigate(self, url: str, *, settle_s: float = 0.8) -> None:
        self.cmd("Page.navigate", {"url": url})
        time.sleep(settle_s)

    def controls(self) -> list[PageControl]:
        """The page's interactive, named, on-screen nodes -- read only."""

        nodes = self.cmd("Accessibility.getFullAXTree").get("nodes", [])
        out = []
        for node in nodes:
            role = (node.get("role") or {}).get("value", "")
            name = (node.get("name") or {}).get("value", "")
            backend = node.get("backendDOMNodeId")
            if role not in _USEFUL or not name or backend is None:
                continue
            if node.get("ignored"):
                continue
            out.append(
                PageControl(role, " ".join(name.split()), backend, self._rect(backend))
            )
        return out

    def _rect(self, backend_node_id: int) -> tuple[int, int, int, int] | None:
        try:
            box = (
                self.cmd("DOM.getBoxModel", {"backendNodeId": backend_node_id})
                .get("model", {})
                .get("border")
            )
        except RuntimeError:
            return None
        if not box or len(box) < 6:
            return None
        xs, ys = box[0::2], box[1::2]
        return (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))

    def label_now(self, backend_node_id: int) -> str:
        """The node's accessible name AND visible text, read now. Both, since
        an aria-label ("Continue") can hide what the person sees ("Delete
        account"), and a single-page app can rename a node after observe."""

        parts = []
        try:
            nodes = self.cmd(
                "Accessibility.getPartialAXTree",
                {"backendNodeId": backend_node_id, "fetchRelatives": False},
            ).get("nodes", [])
            parts += [(n.get("name") or {}).get("value", "") for n in nodes]
        except RuntimeError:
            pass
        try:
            obj = self._isolated_object(backend_node_id)
            if obj:
                got = self.cmd(
                    "Runtime.callFunctionOn",
                    {
                        "objectId": obj,
                        "functionDeclaration": "function(){return String("
                        "this.innerText||this.value||this.title||'').slice(0,300)}",
                        "returnByValue": True,
                    },
                )
                parts.append(str(got.get("result", {}).get("value", "")))
        except RuntimeError:
            pass
        return " | ".join(" ".join(str(p).split()) for p in parts if p)

    def _isolated_world(self) -> int | None:
        """An execution context the page's own scripts cannot reach: there a
        hostile page cannot override innerText/value to report something
        harmless. None when the browser offers none."""

        cached = getattr(self, "_iso_context", None)
        if cached is not None:
            return cached
        try:
            frame = self.cmd("Page.getFrameTree")["frameTree"]["frame"]["id"]
            self._iso_context = self.cmd(
                "Page.createIsolatedWorld", {"frameId": frame, "worldName": "orbyn-read"}
            ).get("executionContextId")
        except (RuntimeError, KeyError, TypeError):
            self._iso_context = None
        return self._iso_context

    def _isolated_object(self, backend_node_id: int) -> str | None:
        """The node's handle in the isolated world, or None. Never the page's
        main world: there the page could override what is read."""

        for _attempt in range(2):  # one world per page, made again after a reload
            context = self._isolated_world()
            if context is None:
                return None
            try:
                return (
                    self.cmd(
                        "DOM.resolveNode",
                        {"backendNodeId": backend_node_id, "executionContextId": context},
                    )
                    .get("object", {})
                    .get("objectId")
                )
            except RuntimeError:
                self._iso_context = None  # the page navigated: its world is gone
        return None

    def visible_text_now(self, backend_node_id: int) -> str | None:
        """What the person sees on the node, read in the isolated world; None
        when it cannot be read (no isolated world, a cross-origin frame)."""

        try:
            obj = self._isolated_object(backend_node_id)
            if not obj:
                return None
            got = self.cmd(
                "Runtime.callFunctionOn",
                {
                    "objectId": obj,
                    "functionDeclaration": "function(){return String("
                    "this.innerText||this.value||this.title||'').slice(0,300)}",
                    "returnByValue": True,
                },
            )
            return str(got.get("result", {}).get("value", ""))
        except RuntimeError:
            return None

    def _hit_is(self, backend_node_id: int, x: int, y: int) -> bool:
        """Is the node at (x, y) the control or inside it? A cookie banner or a
        transparent overlay placed over it would take the click otherwise."""

        try:
            hit = self.cmd(
                "DOM.getNodeForLocation",
                # False: an <input>'s own inner shadow node is not "else".
                {"x": x, "y": y, "includeUserAgentShadowDOM": False},
            ).get("backendNodeId")
            if hit is None:
                return False
            if hit == backend_node_id:
                return True
            target, at = self._isolated_object(backend_node_id), self._isolated_object(hit)
            if not target or not at:
                return False
            got = self.cmd(
                "Runtime.callFunctionOn",
                {
                    "objectId": target,
                    "functionDeclaration": "function(n){return this.contains(n)}",
                    "arguments": [{"objectId": at}],
                    "returnByValue": True,
                },
            )
            return got.get("result", {}).get("value") is True
        except RuntimeError:
            return False

    # --- actions (gated exactly like Act, D182) --------------------------

    def _guard(self, control: PageControl, approved: bool, deny) -> None:
        from ghostcursor import policy
        from ghostcursor.harness.binding import denied

        if policy.act_disabled():  # D187: the organisation allows guidance only
            raise PermissionError("your organisation allows Orbyn to guide, not act")
        # A page opened outside Browser.launch does not know its browser; it
        # is then refused only when policy denies both.
        known = getattr(self, "executable", "")
        if denied(known) if known else denied("chrome.exe") and denied("msedge.exe"):
            raise PermissionError("your organisation does not allow Orbyn in the browser")
        if not approved:
            raise PermissionError("browser actions need the user's approval first")
        name = control.name.casefold()
        if any(d and d.casefold() in name for d in deny or ()):
            raise PermissionError(f"{control.name!r} is on the deny list")

    def click(self, control: PageControl, *, approved: bool = False, deny=()) -> None:
        self._guard(control, approved, deny)
        self.cmd(
            "DOM.scrollIntoViewIfNeeded", {"backendNodeId": control.backend_node_id}
        )
        rect = self._rect(control.backend_node_id)
        if rect is None:
            raise RuntimeError("the control has no on-screen box")
        x, y = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        if not self._hit_is(control.backend_node_id, x, y):
            raise PermissionError(
                f"something else is over {control.name!r}; Orbyn did not click"
            )
        for kind in ("mousePressed", "mouseReleased"):
            self.cmd(
                "Input.dispatchMouseEvent",
                {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1},
            )

    def type_text(
        self, control: PageControl, text: str, *, approved: bool = False, deny=()
    ) -> None:
        self._guard(control, approved, deny)
        self.cmd("DOM.focus", {"backendNodeId": control.backend_node_id})
        self.cmd("Input.insertText", {"text": text})

    def drive(
        self,
        goal: str,
        gateway,
        *,
        approved: bool = False,
        deny=(),
        max_steps: int = 8,
        stop=lambda: False,
    ):
        """Act toward ``goal`` on this page a click at a time (D185), Jev
        choosing each control. Refuses unless ``approved``; never touches a
        deny-listed control; ``stop()`` (ESC) ends it. Returns a drive Result.
        Clicks only -- text entry stays on the gated type_text path."""

        from ghostcursor.harness.drive import drive_until
        from ghostcursor.providers.envelope import Envelope, Tainted

        DONE = "DONE"

        def observe():
            handles = {}
            out = []
            for c in self.controls():
                cid = str(c.backend_node_id)
                handles[cid] = c
                out.append(_Pick(cid, c.name, c.role))
            observe.handles = handles
            return out

        def choose(goal_text, controls):
            tainted = {
                c.id: Tainted.of("page_control", f"{c.role}: {c.name}")
                for c in controls
            }
            envelope = Envelope(
                task="browser",
                trusted={"goal": goal_text, "done_means": "the goal is already met"},
                tainted=tainted,
            )
            return gateway.choose(
                envelope,
                tuple(c.id for c in controls) + (DONE,),
                question="Which control should be clicked next to reach the goal, "
                "or DONE if the goal is already met?",
            )

        def act(pick):
            from ghostcursor.harness.teach import HIGH_RISK

            control = observe.handles[pick.id]
            # Re-read at click time (rule 2): the node may have been renamed
            # since observe, or its label may hide a risky visible text.
            if self.visible_text_now(control.backend_node_id) is None:
                # Unread is not harmless: without the visible text a label
                # ("Continue") could hide "Delete account". Fail closed.
                raise PermissionError(
                    f"Orbyn could not read what {control.name!r} shows; did not click"
                )
            now = self.label_now(control.backend_node_id) or control.name
            if any(d and d.casefold() in now.casefold() for d in deny or ()):
                raise PermissionError(f"{now!r} is on the deny list")
            if HIGH_RISK.search(now):
                raise PermissionError(f"Orbyn will not click {now!r} without asking")
            self.click(control, approved=True, deny=())

        return drive_until(
            goal,
            observe=observe,
            choose=choose,
            act=act,
            approved=approved,
            deny=deny,
            max_steps=max_steps,
            stop=stop,
        )

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


@dataclass(frozen=True)
class _Pick:
    id: str
    name: str
    role: str
