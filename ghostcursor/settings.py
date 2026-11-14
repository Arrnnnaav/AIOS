"""The user's own switches, on this machine only (LOCALAPPDATA)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

# The page server is threaded: two switches flipped at once must not lose one.
_write_lock = threading.Lock()


def _path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "GhostCursor" / "settings.json"


def load(path: Path | None = None) -> dict:
    try:
        value = json.loads((path or _path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def jev_vision(path: Path | None = None) -> bool:
    """D179: may Jev see redacted pictures of the windows being guided?
    Off unless the user turned it on; anything but a literal true is off,
    and an organisation policy below pictures turns it off (D180)."""

    from ghostcursor import policy

    return (
        load(path).get("jev_vision") is True and policy.max_egress() >= policy.PICTURES
    )


def _set(key: str, on, path: Path | None) -> None:
    path = path or _path()
    with _write_lock:  # read-change-write as one step
        value = load(path) | {
            key: on if isinstance(on, (list, str)) else bool(on)
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(value), encoding="utf-8")
        temp.replace(path)  # never a half-written file


def set_jev_vision(on: bool, path: Path | None = None) -> None:
    _set("jev_vision", on, path)


def company_gateway(path: Path | None = None) -> bool:
    """D187: may this person's requests go to the company model gateway IT
    named (CompanyEndpoint)? Off unless the user turned it on: an IT policy
    alone never adds a place text is sent (rule 6, policy only lowers)."""

    from ghostcursor import policy

    return (
        load(path).get("company_gateway") is True
        and policy.company_endpoint() is not None
    )


def set_company_gateway(on: bool, path: Path | None = None) -> None:
    _set("company_gateway", on, path)


def crash_reports(path: Path | None = None) -> bool:
    """D191: may a content-free crash event go to the organisation's
    CrashEndpoint? Off unless this person turned it on (rule 6)."""

    from ghostcursor import policy

    return (
        load(path).get("crash_reports") is True and policy.crash_endpoint() is not None
    )


def set_crash_reports(on: bool, path: Path | None = None) -> None:
    _set("crash_reports", on, path)


def redact_egress(path: Path | None = None) -> bool:
    """The person's own switch: scrub private details (email, phone, card,
    ID, key, address of a machine) out of text bound for a cloud model.
    It can only add to the organisation's RedactEgress policy, never
    lower it (rule 6). On unless this person turned it off (owner decision,
    14 Nov 2026); an unreadable settings file therefore reads as on."""

    return load(path).get("redact_egress") is not False


def set_redact_egress(on: bool, path: Path | None = None) -> None:
    _set("redact_egress", on, path)


def own_private_terms(path: Path | None = None) -> tuple[str, ...]:
    """The private words this person listed (names of people, clients,
    projects). Kept on this computer only."""

    from ghostcursor import redact
    from ghostcursor.workspace import brain

    value = load(path).get("private_terms")
    if isinstance(value, str):  # sealed to this Windows account
        try:
            value = json.loads(brain._unseal(value))
        except ValueError:  # another account's, or damaged: no words
            return ()
    return redact.clean_terms(value)


def private_terms(path: Path | None = None) -> tuple[str, ...]:
    """Every private word to hide from a remote service: this person's
    and the organisation's (PrivateTerms). Either can only add (rule 6)."""

    from ghostcursor import policy, redact

    # Each list keeps its own limit: a long organisation list never
    # pushes out a person's words.
    org = redact.clean_terms(list(policy.private_terms()))
    return redact.clean_terms(
        [*org, *own_private_terms(path)], 2 * redact.MAX_TERMS
    )


def set_private_terms(terms, path: Path | None = None) -> None:
    from ghostcursor import redact

    from ghostcursor.workspace import brain

    words = list(redact.clean_terms(terms))
    try:  # the names themselves are private: sealed like a memory
        stored = brain._seal(json.dumps(words))
    except Exception:  # Windows cannot seal now: keep them, plain
        stored = words
    _set("private_terms", stored, path)


def local_only(path: Path | None = None) -> bool:
    """The person's own air gap: nothing leaves this computer, only a
    model running here answers. Off unless switched on; it only ever
    lowers what the organisation allows (rule 6)."""

    try:
        value = json.loads((path or _path()).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False  # never set
    except (OSError, ValueError):
        return True  # there but unreadable: an air gap does not fail open
    return isinstance(value, dict) and value.get("local_only") is True


def set_local_only(on: bool, path: Path | None = None) -> None:
    _set("local_only", on, path)


def agent_access(path: Path | None = None) -> bool:
    """May another agent on this computer read the Company Brain and
    saved workflows through ghostcursor.agent_server? Off unless this
    person turned it on: that agent may pass what it reads to a cloud."""

    return load(path).get("agent_access") is True


def set_agent_access(on: bool, path: Path | None = None) -> None:
    _set("agent_access", on, path)


def companion_idle(path: Path | None = None) -> bool:
    """settings.json "companion_idle": true keeps a small resting dot beside
    the pointer when Orbyn is idle (HeyClicky's docked companion). Off by
    default: the badge shows only while Orbyn is busy or listening."""

    return load(path).get("companion_idle") is True


def set_companion_idle(on: bool, path: Path | None = None) -> None:
    _set("companion_idle", on, path)


def listening(path: Path | None = None) -> tuple[bool, str | None]:
    """(wake word on, hotkey or None) -- "Hey Bro" and Ctrl+Alt+Space by
    default (D182); settings.json "wake_word": false / "hotkey": "" turn
    them off, "hotkey": "ctrl+shift+o" changes it."""

    value = load(path)
    hotkey = value.get("hotkey", "ctrl+alt+space")
    return value.get("wake_word", True) is not False, (
        hotkey if isinstance(hotkey, str) and hotkey else None
    )
