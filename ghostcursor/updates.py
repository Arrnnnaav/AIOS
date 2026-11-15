"""Is there a newer Orbyn? Read the public releases of the project repository.

Only when the person presses "Check for updates": one GET to GitHub's public
releases API, with a generic User-Agent and nothing about the person, the
computer or what they do. Blocked by the offline switch and by an
organisation allow-list that does not name ``updates`` (rule 6). Nothing is
downloaded or installed here; the page links to the release.
"""

from __future__ import annotations

import re

from ghostcursor import __version__

REPOSITORY = "Arrnnnaav/AIOS"
API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def _parts(tag: str) -> tuple[int, int, int] | None:
    m = _VERSION.fullmatch(tag.strip())
    return tuple(int(x) for x in m.groups()) if m else None


def check(*, transport=None, current: str = __version__) -> dict:
    """{"current", "latest", "newer", "url"}; raises PermissionError when the
    person or the organisation keeps everything on this computer, and
    ValueError for an answer that is not a release."""

    import httpx

    from ghostcursor import audit, policy

    if not policy.allows("updates"):
        raise PermissionError("updates are not checked: everything stays on this computer")
    failure = "fetch"
    try:
        with httpx.Client(transport=transport, timeout=10, follow_redirects=False) as client:
            reply = client.get(
                API,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "Orbyn"},
            )
        failure = None if reply.status_code == 200 else "fetch"
    finally:
        audit.record("egress", provider="updates", model=None, failure=failure, images=0)
    if reply.status_code == 404:
        return {"current": current, "latest": None, "newer": False, "url": None}
    if reply.status_code != 200:
        raise ValueError("the release list could not be read")
    body = reply.json()
    tag = body.get("tag_name") if isinstance(body, dict) else None
    url = body.get("html_url") if isinstance(body, dict) else None
    latest, mine = _parts(tag or ""), _parts(current)
    if latest is None or mine is None:
        raise ValueError("the latest release has no version number")
    if not (isinstance(url, str) and url.startswith(f"https://github.com/{REPOSITORY}/releases/")):
        url = None
    return {"current": current, "latest": ".".join(map(str, latest)), "newer": latest > mine, "url": url}
