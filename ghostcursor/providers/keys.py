"""Provider keys in Windows Credential Manager, never in tracked files.

Keys are stored as generic credentials under ``Orbyn/<name>`` (DPAPI-protected
per user). A process environment variable ``ORBYN_<NAME>_API_KEY`` is honoured
as an override for tests and one-off runs; files are never read here.
"""

from __future__ import annotations

import os

TARGET_PREFIX = "Orbyn/"

#: Provider key names this gateway knows.
KNOWN = ("typesafe", "nvidia", "openrouter", "tavily")


def _env_name(name: str) -> str:
    return f"ORBYN_{name.upper()}_API_KEY"


def get_key(name: str) -> str | None:
    """The key for ``name``, or None. Never logs or returns a partial key."""

    override = os.environ.get(_env_name(name))
    if override:
        return override.strip()
    if name == "chatgpt":  # an OAuth token from Sign in with ChatGPT, not a key
        from ghostcursor.providers import chatgpt

        return chatgpt.access_token()
    try:
        import win32cred
    except ImportError:  # non-Windows test hosts
        return None
    try:
        credential = win32cred.CredRead(
            TARGET_PREFIX + name, win32cred.CRED_TYPE_GENERIC
        )
    except Exception:  # not found, or Credential Manager unavailable
        return None
    blob = credential.get("CredentialBlob") or b""
    if isinstance(blob, str):
        return blob.strip() or None
    try:
        return blob.decode("utf-16-le").strip() or None
    except UnicodeDecodeError:
        return blob.decode("utf-8", errors="ignore").strip() or None


def set_key(name: str, value: str) -> None:
    import win32cred

    if not value or not value.strip():
        raise ValueError("refusing to store an empty key")
    win32cred.CredWrite(
        {
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": TARGET_PREFIX + name,
            "UserName": "orbyn",
            "CredentialBlob": value.strip(),
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        },
        0,
    )


def delete_key(name: str) -> None:
    import win32cred

    try:
        win32cred.CredDelete(TARGET_PREFIX + name, win32cred.CRED_TYPE_GENERIC)
    except Exception:
        pass


def status() -> dict[str, bool]:
    """Which keys are present -- presence only, never values."""

    from ghostcursor.providers import chatgpt

    present = {name: get_key(name) is not None for name in KNOWN}
    present["chatgpt"] = chatgpt.signed_in(chatgpt.load())
    return present
