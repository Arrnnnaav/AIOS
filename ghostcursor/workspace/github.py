"""Explicit read-only GitHub views for Work; no model or routine entry point."""

from __future__ import annotations

import re
import threading

import httpx

from ghostcursor.providers import keys

API = "https://api.github.com"
REPO_NAME = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


class GitHubConnector:
    def __init__(self, *, transport=None):
        self.transport = transport
        self._lock = threading.RLock()
        self._repos: set[str] = set()

    def connected(self) -> bool:
        return keys.get_key("github", allow_env=False) is not None

    def _get(self, path: str, token: str):
        if not path.startswith(("/user", "/repos/")):
            raise ValueError("unsupported GitHub read")
        try:
            with httpx.Client(transport=self.transport, timeout=8, follow_redirects=False) as client:
                response = client.get(
                    API + path,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                        "User-Agent": "Orbyn",
                    },
                )
            if response.status_code != 200:
                raise ValueError("GitHub refused this read; check the token and repository permissions")
            if len(response.content) > 1024 * 1024:
                raise ValueError("GitHub response exceeded the one-megabyte limit")
            return response.json()
        except (httpx.HTTPError, UnicodeError, ValueError) as exc:
            if isinstance(exc, ValueError):
                raise
            raise ValueError("GitHub could not be reached") from None

    def connect(self, token: str) -> str:
        if not isinstance(token, str) or not 20 <= len(token) <= 255 or any(c.isspace() for c in token):
            raise ValueError("enter a GitHub access token")
        with self._lock:
            user = self._get("/user", token)
            login = user.get("login") if isinstance(user, dict) else None
            if not isinstance(login, str) or not login:
                raise ValueError("GitHub did not return an account")
            keys.set_key("github", token)
            self._repos.clear()
            return login[:100]

    def disconnect(self) -> None:
        with self._lock:
            keys.delete_key("github")
            if self.connected():
                raise ValueError("the GitHub token could not be removed from Windows Credential Manager")
            self._repos.clear()

    def repos(self) -> list[dict]:
        with self._lock:
            token = keys.get_key("github", allow_env=False)
            if not token:
                raise ValueError("connect GitHub first")
            rows = self._get("/user/repos?per_page=30&sort=updated", token)
            if not isinstance(rows, list):
                raise ValueError("GitHub returned an invalid repository list")
            projected = []
            for row in rows[:30]:
                if not isinstance(row, dict) or not isinstance(row.get("full_name"), str):
                    continue
                name = row["full_name"]
                if not REPO_NAME.fullmatch(name) or any(part in (".", "..") for part in name.split("/")):
                    continue
                projected.append({
                    "name": name,
                    "description": str(row.get("description") or "")[:300],
                    "private": row.get("private") is True,
                })
            self._repos = {row["name"] for row in projected}
            return projected

    def issues(self, name: str) -> list[dict]:
        with self._lock:
            token = keys.get_key("github", allow_env=False)
            if not token:
                raise ValueError("connect GitHub first")
            if name not in self._repos:
                raise ValueError("choose a repository from the current list")
            rows = self._get(f"/repos/{name}/issues?state=open&per_page=30", token)
            if not isinstance(rows, list):
                raise ValueError("GitHub returned an invalid issue list")
            return [
                {"number": row["number"], "title": row["title"][:300]}
                for row in rows[:30]
                if isinstance(row, dict)
                and "pull_request" not in row
                and isinstance(row.get("number"), int)
                and isinstance(row.get("title"), str)
            ][:20]
