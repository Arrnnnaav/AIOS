"""Organisation policy (D180): what IT allows to leave this machine.

Set through Group Policy or Intune as registry values under
``Software\\Policies\\Orbyn`` (HKLM first, then HKCU). A policy only ever
lowers what the user may switch on; with no policy, behaviour is unchanged.

- ``MaxEgress`` (DWORD): 0 local only -- nothing leaves, only the local model
  answers; 1 text -- the redacted model view; 2 text and pictures (D179).
- ``RedactEgress`` (DWORD): 0 off (default); 1 on -- scrub embedded secrets
  (email/card/SSN/key/...) out of text bound for a remote model (D186). Absent
  leaves it off (unchanged behaviour); present but unreadable fails safe to on.
- ``BlockedApps`` (REG_SZ): executables never bound, ``;``-separated.
"""

from __future__ import annotations

import ntpath

LOCAL, TEXT, PICTURES = 0, 1, 2
_KEY = r"Software\Policies\Orbyn"
#: Providers that run on this machine (the local Ollama server).
LOCAL_PROVIDERS = frozenset({"ollama"})


def _value(name: str):
    """The policy value, HKLM before HKCU, or None. Read on every call so a
    policy pushed mid-session applies at the next request."""

    import winreg

    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, _KEY) as key:
                return winreg.QueryValueEx(key, name)[0]
        except FileNotFoundError:
            continue
        except OSError:
            return "unreadable"  # present but not readable: fails closed
    return None


def max_egress() -> int:
    value = _value("MaxEgress")
    if value is None:
        return PICTURES
    try:
        return min(PICTURES, max(LOCAL, int(value)))
    except (TypeError, ValueError):
        return LOCAL  # an unreadable policy fails closed


def redact_egress() -> bool:
    """Should embedded secrets be scrubbed from text bound for a REMOTE model?
    Default off (no policy -> unchanged behaviour); present but unreadable fails
    safe to on, since a managed machine asked for the guard."""

    value = _value("RedactEgress")
    if value is None:
        return False
    if value == "unreadable":
        return True  # policy present but unreadable: fail safe to redacting
    try:
        return int(value) >= 1
    except (TypeError, ValueError):
        return True  # garbage value on a managed machine: fail safe
    return False


def blocked_apps() -> frozenset[str]:
    value = _value("BlockedApps")
    if not isinstance(value, str):
        return frozenset()
    return frozenset(
        ntpath.basename(p.strip()).casefold() for p in value.split(";") if p.strip()
    )


def allows(provider: str, *, images: int = 0) -> bool:
    """May a request go to ``provider`` now?"""

    level = max_egress()
    if provider in LOCAL_PROVIDERS:
        return not images or level >= PICTURES
    return level >= (PICTURES if images else TEXT)


def managed() -> bool:
    return _value("MaxEgress") is not None
