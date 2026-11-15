"""ghostcursor.updates: one public read, only when asked, gated (rule 6)."""

import json

import httpx
import pytest

from ghostcursor import audit, policy, settings, updates


def _transport(status, body, seen):
    def handler(request):
        seen.append(request)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


def test_a_newer_release_is_reported_and_nothing_personal_is_sent():
    seen = []
    body = {"tag_name": "v0.3.0", "html_url": "https://github.com/Arrnnnaav/AIOS/releases/tag/v0.3.0"}
    got = updates.check(transport=_transport(200, body, seen), current="0.2.0")
    assert got == {"current": "0.2.0", "latest": "0.3.0", "newer": True, "url": body["html_url"]}
    (request,) = seen
    assert request.method == "GET" and str(request.url) == updates.API and request.content == b""
    assert request.headers["user-agent"] == "Orbyn" and "cookie" not in request.headers
    assert "authorization" not in request.headers
    audit.flush()
    line = json.loads(audit.default_path().read_text().splitlines()[-1])
    assert (line["provider"], line["failure"]) == ("updates", None)


def test_same_or_older_and_no_release_and_bad_answers():
    seen = []
    same = {"tag_name": "0.2.0", "html_url": "https://github.com/Arrnnnaav/AIOS/releases/tag/0.2.0"}
    assert updates.check(transport=_transport(200, same, seen), current="0.2.0")["newer"] is False
    assert updates.check(transport=_transport(200, {"tag_name": "v0.10.0"}, seen), current="0.9.9")["newer"] is True
    assert updates.check(transport=_transport(404, {}, seen))["latest"] is None
    for body in ({"tag_name": "nightly"}, ["x"], {}):
        with pytest.raises(ValueError):
            updates.check(transport=_transport(200, body, seen))
    with pytest.raises(ValueError):
        updates.check(transport=_transport(500, {}, seen))
    evil = {"tag_name": "v9.0.0", "html_url": "https://evil.example/x"}
    assert updates.check(transport=_transport(200, evil, seen))["url"] is None  # never a foreign link


def test_offline_and_policy_block_it_before_anything_is_sent(monkeypatch):
    seen = []
    settings.set_local_only(True)
    with pytest.raises(PermissionError):
        updates.check(transport=_transport(200, {}, seen))
    settings.set_local_only(False)
    monkeypatch.setattr(policy, "_value", lambda name: {"AllowedProviders": "openrouter"}.get(name))
    with pytest.raises(PermissionError):
        updates.check(transport=_transport(200, {}, seen))
    assert seen == []


def test_only_generic_headers_leave_and_an_older_release_is_not_newer():
    seen = []
    body = {"tag_name": "v0.1.0", "html_url": "https://github.com/Arrnnnaav/AIOS/releases/tag/v0.1.0"}
    got = updates.check(transport=_transport(200, body, seen), current="0.2.0")
    assert got["newer"] is False
    sent = {k.lower() for k in seen[0].headers.keys()}
    assert sent <= {"host", "accept", "accept-encoding", "connection", "user-agent"}, sent
