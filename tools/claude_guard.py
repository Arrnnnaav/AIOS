"""PreToolUse guards for Claude Code in this repository (tier 3 tooling).

    py -3.12 tools/claude_guard.py secrets   # Write/Edit: no provider key in content
    py -3.12 tools/claude_guard.py shell     # Bash/PowerShell: campaign freeze, D025

Reads the hook payload as JSON on stdin. Exit 2 blocks the tool call and the
message on stderr goes back to Claude; exit 0 allows it. A guard that cannot
parse its input allows the call: it is a seatbelt, not the enforcement (the
hermetic tests and evidence scans remain that).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Shapes of the provider keys this project uses (CLAUDE.md rule 6).
KEY_SHAPES = re.compile(
    r"apikey_[A-Za-z0-9]{12,}|nvapi-[A-Za-z0-9_-]{12,}|sk-or-v1-[a-f0-9]{12,}"
)

#: Desktop lanes that must run alone (D025).
DESKTOP_LANE = re.compile(
    r"-m\s+[\"']?(interactive|pixel)\b|test_hung_window|test_perception_service_hung"
    r"|test_run_threaded|tests\.test_overlay|tests\.test_end_to_end"
)
COMMIT = re.compile(r"\bgit\b[^|;&]*\bcommit\b")


def _stored_keys() -> list[str]:
    try:
        sys.path.insert(0, str(ROOT))
        from ghostcursor.providers import keys

        return [k for k in (keys.get_key(n) for n in keys.KNOWN) if k and len(k) >= 12]
    except Exception:
        return []


def check_secrets(payload: dict, stored=_stored_keys) -> str | None:
    tool_input = payload.get("tool_input") or {}
    text = "\n".join(
        str(tool_input.get(field) or "") for field in ("content", "new_string")
    )
    if KEY_SHAPES.search(text) or any(key in text for key in stored()):
        return (
            "Blocked: the content contains a provider API key. Keys live only in "
            "Windows Credential Manager (Orbyn/<provider>), never in files."
        )
    return None


def _other_pytest_running() -> bool:
    import os

    import psutil

    me = os.getpid()
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if (
                process.info["pid"] == me
                or "python" not in (process.info["name"] or "").lower()
            ):
                continue
            line = " ".join(process.info["cmdline"] or [])
            if "pytest" in line or "tests.test_" in line:
                return True
        except (psutil.Error, TypeError):
            continue
    return False


def check_shell(
    payload: dict, root: Path = ROOT, busy=_other_pytest_running
) -> str | None:
    command = str((payload.get("tool_input") or {}).get("command") or "")
    lock = root / ".artifacts" / "campaign.lock"
    if COMMIT.search(command) and lock.exists():
        campaign = lock.read_text(encoding="utf-8").strip()
        return (
            f"Blocked: campaign {campaign} is open (D163). Nothing is committed "
            "until its last attempt and its document is rendered; rendering "
            "removes .artifacts/campaign.lock."
        )
    if DESKTOP_LANE.search(command) and busy():
        return (
            "Blocked: another test session is running. Desktop lanes run one at "
            "a time (D025); wait for it to finish."
        )
    return None


def main(argv: list[str]) -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    check = {"secrets": check_secrets, "shell": check_shell}.get(
        argv[1] if len(argv) > 1 else ""
    )
    message = check(payload) if check else None
    if message:
        print(message, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
