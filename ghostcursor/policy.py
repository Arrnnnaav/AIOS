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
- ``AllowedApps`` (REG_SZ): if set, ONLY these executables may be bound.
- ``DisableAct`` (DWORD): 1 -- Orbyn guides only; no step is performed.
- ``AllowedProviders`` (REG_SZ): if set, only these model providers answer.
- ``CompanyEndpoint`` / ``CompanyModel`` (REG_SZ): the company's own
  OpenAI-compatible model gateway (https), tried before any personal account;
  its key, if it needs one, is ``Orbyn/company`` in Credential Manager.
- ``TeamFolder`` / ``TeamOwnerKey`` (REG_SZ): the shared folder the owner
  publishes to, and the owner's public key; only bundles it signed are loaded.
- ``ShareAudit`` (DWORD): 1 -- copy this PC's audit log to the team folder.

Allow-lists fail closed: present but unreadable allows nothing.
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


def telemetry_enabled() -> bool:
    """Local, events-not-content telemetry (D141). OFF by default AND off when
    absent or unreadable -- it is opt-in local diagnostics, not a safety guard,
    so anything but an explicit ``1`` means off. Even when on, NOTHING leaves
    the device (rule 6): it only permits counting allowlisted event NAMES in a
    local file for the owner's own view."""

    value = _value("Telemetry")
    if value is None or value == "unreadable":
        return False
    try:
        return int(value) >= 1
    except (TypeError, ValueError):
        return False


def blocked_apps() -> frozenset[str]:
    value = _value("BlockedApps")
    if not isinstance(value, str):
        return frozenset()
    return frozenset(
        ntpath.basename(p.strip()).casefold() for p in value.split(";") if p.strip()
    )


def _names(name: str) -> frozenset[str] | None:
    """A ``;``-separated allow-list, casefolded; None when not set. A value
    that is present but not text allows nothing (fails closed)."""

    value = _value(name)
    if value is None:
        return None
    if not isinstance(value, str) or value == "unreadable":
        return frozenset()
    return frozenset(
        ntpath.basename(p.strip()).casefold() for p in value.split(";") if p.strip()
    )


def allowed_apps() -> frozenset[str] | None:
    return _names("AllowedApps")


def allowed_providers() -> frozenset[str] | None:
    return _names("AllowedProviders")


def act_disabled() -> bool:
    """DisableAct: anything present but ``0`` disables Act (fails safe)."""

    value = _value("DisableAct")
    if value is None:
        return False
    try:
        return int(value) != 0
    except (TypeError, ValueError):
        return True


def _text(name: str) -> str | None:
    value = _value(name)
    return value.strip() or None if isinstance(value, str) and value != "unreadable" else None


def company_endpoint() -> str | None:
    """The company model gateway, https only (or this machine)."""

    url = _text("CompanyEndpoint")
    if url is None:
        return None
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return None
    local = parts.scheme == "http" and host in ("127.0.0.1", "localhost", "::1")
    return url.rstrip("/") if (parts.scheme == "https" and host) or local else None


def company_model() -> str:
    return _text("CompanyModel") or "default"


def team_folder() -> str | None:
    return _text("TeamFolder")


def team_owner_key() -> str | None:
    return _text("TeamOwnerKey")


def share_audit() -> bool:
    """Opt-in: only an explicit 1 copies the audit log to the team folder."""

    value = _value("ShareAudit")
    try:
        return value is not None and int(value) == 1
    except (TypeError, ValueError):
        return False


def allows(provider: str, *, images: int = 0) -> bool:
    """May a request go to ``provider`` now?"""

    listed = allowed_providers()
    if listed is not None and provider.casefold() not in listed:
        return False
    level = max_egress()
    if provider in LOCAL_PROVIDERS:
        return not images or level >= PICTURES
    return level >= (PICTURES if images else TEXT)


def managed() -> bool:
    return _value("MaxEgress") is not None
