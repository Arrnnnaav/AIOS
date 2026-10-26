"""The GitHub connector has one fixed, read-only network authority."""

from __future__ import annotations

import json

import httpx
import pytest

from ghostcursor.brief import brief_path
from ghostcursor.providers import keys
from ghostcursor.workspace.app import App
from ghostcursor.workspace.brain import Brain
from ghostcursor.workspace.github import GitHubConnector
from ghostcursor.workspace.session import Workspace


def test_github_views_are_fixed_gets_and_keep_token_out_of_state(tmp_path, monkeypatch):
    stored = {"value": None}
    monkeypatch.setattr(keys, "get_key", lambda name, *, allow_env=True: stored["value"] if not allow_env else None)
    monkeypatch.setattr(keys, "set_key", lambda name, value: stored.update(value=value))
    monkeypatch.setattr(keys, "delete_key", lambda name: stored.update(value=None))
    seen = []

    def respond(request):
        seen.append((request.method, request.url.host, request.headers.get("Authorization")))
        assert request.method == "GET"
        assert request.url.host == "api.github.com"
        if request.url.path == "/user":
            body = {"login": "octocat"}
        elif request.url.path == "/user/repos":
            body = [
                {"full_name": "octocat/Hello-World", "description": "<script>unsafe</script>", "private": True},
                {"full_name": "../bad", "description": "skip"},
            ]
        elif request.url.path == "/repos/octocat/Hello-World/issues":
            body = [
                {"number": 7, "title": "Fix <script>text</script>"},
                {"number": 8, "title": "Pull request", "pull_request": {}},
            ]
        else:
            return httpx.Response(404)
        return httpx.Response(200, json=body)

    app = App(
        "trip", make_workspace=lambda: Workspace(
            "trip", object(), Brain(tmp_path / "kb.sqlite"), root=tmp_path / "briefs"
        ),
    )
    app.github = GitHubConnector(transport=httpx.MockTransport(respond))
    token = "github_pat_abcdefghijklmnopqrstuvwxyz"
    try:
        assert app.handle("github_connect", {"token": token}) == {"login": "octocat"}
        assert app.state()["github_connected"] is True
        assert token not in json.dumps(app.state())
        assert app.handle("github_repos", {}) == {"repos": [{
            "name": "octocat/Hello-World", "description": "<script>unsafe</script>", "private": True,
        }]}
        assert app.handle("github_issues", {"name": "octocat/Hello-World"}) == {
            "issues": [{"number": 7, "title": "Fix <script>text</script>"}],
        }
        with pytest.raises(ValueError):
            app.handle("github_issues", {"name": "other/repo"})
        assert not brief_path(app.ws.root, app.ws.topic).exists()
        assert [method for method, _, _ in seen] == ["GET", "GET", "GET"]
        assert all(host == "api.github.com" and auth == f"Bearer {token}" for _, host, auth in seen)
        app.handle("github_disconnect", {})
        assert app.state()["github_connected"] is False
        with pytest.raises(ValueError):
            app.handle("github_repos", {})
    finally:
        app.close()


def test_github_rejects_bad_token_and_failed_disconnect(tmp_path, monkeypatch):
    stored = {"value": None}
    monkeypatch.setattr(keys, "get_key", lambda name, *, allow_env=True: stored["value"])
    monkeypatch.setattr(keys, "set_key", lambda name, value: stored.update(value=value))
    monkeypatch.setattr(keys, "delete_key", lambda name: None)
    connector = GitHubConnector(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"login": "octocat"})))
    with pytest.raises(ValueError):
        connector.connect("short")
    connector.connect("github_pat_abcdefghijklmnopqrstuvwxyz")
    with pytest.raises(ValueError, match="could not be removed"):
        connector.disconnect()
