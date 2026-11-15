"""Smoke-test the packaged Orbyn build (dist/Orbyn/Orbyn.exe).

Starts the exe with a throwaway data folder (so the person's own Brain,
settings and running Orbyn are untouched), then checks what only the frozen
build can get wrong: that it starts, shows its bar, serves the page, and that
the bundled modules behind a few actions import and run. Quits it at the end.

    py -3.12 tools\\smoke_build.py [path\\to\\Orbyn.exe]

Exit code 0 when every check passes. Not a test lane: it opens a real window,
so run it alone (CLAUDE.md rule 8).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def call(url: str, action: str, body: dict | None = None):
    parts = urllib.parse.urlparse(url)
    token = urllib.parse.parse_qs(parts.query)["t"][0]
    request = urllib.request.Request(
        f"http://{parts.netloc}/api/{action}",
        data=json.dumps(body or {}).encode("utf-8"),
        headers={"X-Orbyn-Token": token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def main(argv: list[str]) -> int:
    exe = Path(argv[0]) if argv else ROOT / "dist" / "Orbyn" / "Orbyn.exe"
    if not exe.is_file():
        print(f"no build at {exe}; run tools\\build_orbyn.ps1 first")
        return 2
    failed = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail}")
        if not ok:
            failed.append(name)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as data:
        # Only throwaway data: ORBYN_* can point a store at the person's own.
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("ORBYN_")}
        env.update(LOCALAPPDATA=data, USERPROFILE=data)
        process = subprocess.Popen([str(exe), "smoke"], env=env, cwd=data)
        lock = Path(data) / "GhostCursor" / "app.lock"
        url = ""
        try:
            until = time.monotonic() + 60
            while time.monotonic() < until and process.poll() is None:
                if lock.is_file() and (url := lock.read_text(encoding="utf-8").strip()):
                    break
                time.sleep(0.25)
            check("starts and writes its lock", bool(url), f"exit={process.poll()}")
            if not url:
                return 1

            import win32gui
            import win32process

            bars = []

            def see(hwnd, _):
                if win32gui.GetClassName(hwnd) == "OrbynWorkspaceIsland":
                    if win32process.GetWindowThreadProcessId(hwnd)[1] == process.pid:
                        bars.append(hwnd)

            until = time.monotonic() + 15
            while not bars and time.monotonic() < until:
                win32gui.EnumWindows(see, None)
                time.sleep(0.25)
            check("the bar window exists", bool(bars))
            if bars:
                left, top, right, bottom = win32gui.GetWindowRect(bars[0])
                check("the bar has a size", right - left > 200 and bottom - top > 30)

            with urllib.request.urlopen(url, timeout=20) as response:
                page = response.read().decode("utf-8")
            check(
                "serves the page", "<title>Orbyn</title>" in page, f"{len(page)} bytes"
            )
            bare = url.split("?")[0] + "api/state"
            try:
                urllib.request.urlopen(
                    urllib.request.Request(bare, data=b"{}"), timeout=20
                )
                refused = False
            except urllib.error.HTTPError as error:
                refused = error.code == 403
            check("refuses a call without the token", refused)

            status, state = call(url, "state")
            check("state", status == 200 and "busy" in state, f"{status}")
            status, doctor = call(url, "doctor")
            check("readiness checks run", status == 200 and bool(doctor.get("checks")))
            status, _ = call(url, "stats")
            check("stats", status == 200, f"{status}")
            # The Company Brain store: sqlite + FTS5 and the secret scrub, frozen.
            status, added = call(
                url, "know_add", {"text": "smoke fact; key sk-proj-" + "a" * 40}
            )
            check("Company Brain accepts a fact", status == 200, f"{status} {added}")
            status, facts = call(url, "know_list")
            texts = [f["text"] for f in facts.get("facts", [])]
            check(
                "and scrubs a pasted key",
                texts == ["smoke fact; key [KEY_1]"],
                str(texts),
            )
            status, told = call(url, "brain", {"verb": "pause"})
            check("Personal Brain answers", status == 200, f"{status} {told}")
            status, _ = call(url, "nonsense")
            check("an unknown action is a plain 400", status == 400, f"{status}")
        finally:
            if url and process.poll() is None:
                try:
                    call(url, "quit")
                except Exception:
                    pass
            try:
                process.wait(timeout=15)
                check("quits when asked", True, f"exit={process.returncode}")
            except subprocess.TimeoutExpired:
                process.kill()
                check("quits when asked", False, "had to be killed")
        # The same exe as a read-only MCP server for another agent (stdio).
        try:
            agent = subprocess.run(
                [str(exe), "--agent-server"],
                input='{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n'
                '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"recall","arguments":{"query":"smoke"}}}\n',
                capture_output=True, text=True, encoding="utf-8", timeout=60, env=env, cwd=data,
            )
            replies = [json.loads(x) for x in agent.stdout.splitlines()]
            check(
                "answers another agent over stdio",
                len(replies) == 2 and len(replies[0]["result"]["tools"]) == 4,
                agent.stdout[:200] + agent.stderr[-200:],
            )
            check(
                "and shares nothing while agent access is off",
                replies[1]["result"]["isError"] is True
                and "smoke fact" not in agent.stdout,
            )
        except Exception as exc:
            check("answers another agent over stdio", False, repr(exc))
        crashes = list(Path(data).rglob("crash*"))
        check("left no crash report", not crashes, str([c.name for c in crashes]))
    print("FAILED: " + ", ".join(failed) if failed else "all checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
