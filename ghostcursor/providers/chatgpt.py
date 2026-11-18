"""Sign in with ChatGPT: the user powers Orbyn with their own ChatGPT plan.

OpenAI's open-source/local-client flow (developers.openai.com/siwc,
token-sharing-open-source/sign-in): browser OpenID Connect with PKCE (S256),
a loopback redirect ``http://127.0.0.1:<port>/auth/callback``, dynamic client
registration on first sign-in (``client_id=dynamic_agent_client``), and a
per-install ``ext_agent_host_id``. Inference then goes to the public Responses
API with the user's access token (``clients.responses_json_call``).

The credential record (tokens, issued client id, host id) is DPAPI-encrypted
for the current Windows user in ``%LOCALAPPDATA%\\GhostCursor\\chatgpt.cred``:
JWTs outgrow a Credential Manager blob. It is never logged or printed.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.parse
import uuid
import webbrowser
from pathlib import Path

import httpx

AUTH = "https://auth.openai.com"
AUTHORIZE_URL = AUTH + "/api/accounts/authorize"
TOKEN_URL = AUTH + "/api/accounts/oauth/token"
JWKS_URL = AUTH + "/.well-known/jwks.json"
RESOURCE = "https://api.openai.com/v1"
REQUIRED_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = "openid profile email offline_access resource.invoke " + REQUIRED_SCOPE
REGISTRATION_PORT = 1455  # the documented port for the first sign-in
CALLBACK_PATH = "/auth/callback"
APP_NAME = "Orbyn"


class SignInError(RuntimeError):
    pass


# --- the credential record ---------------------------------------------------------


def store_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "GhostCursor" / "chatgpt.cred"


def load(path: Path | None = None) -> dict | None:
    path = path or store_path()
    try:
        import win32crypt

        blob = path.read_bytes()
        _, plain = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
        record = json.loads(plain.decode("utf-8"))
    except Exception:  # missing, another user's, or corrupt: not signed in
        return None
    return record if isinstance(record, dict) else None


def save(record: dict, path: Path | None = None) -> None:
    import win32crypt

    path = path or store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = win32crypt.CryptProtectData(
        json.dumps(record).encode("utf-8"), "Orbyn ChatGPT", None, None, None, 0
    )
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(blob)
    os.replace(temporary, path)


def sign_out(path: Path | None = None) -> None:
    """Forget the tokens; keep the host id so a later sign-in is the same host."""

    record = load(path)
    with _REFRESH:
        _UNSAVED.pop(path, None)  # an unsaved refresh is still a token
    (path or store_path()).unlink(missing_ok=True)
    if record and record.get("ext_agent_host_id"):
        save({"ext_agent_host_id": record["ext_agent_host_id"]}, path)


def signed_in(record: dict | None) -> bool:
    return bool(record and record.get("access_token") and record.get("refresh_token"))


# --- PKCE and the authorization request ---------------------------------------------


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def authorize_url(
    *,
    client_id: str | None,
    redirect_uri: str,
    state: str,
    nonce: str,
    challenge: str,
    host_id: str,
) -> str:
    params = {
        "client_id": client_id or "dynamic_agent_client",
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "ext_agent_host_id": host_id,
    }
    if client_id is None:
        params["agent_name_hint"] = APP_NAME
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)


def listen(port: int) -> http.server.HTTPServer:
    """A one-shot loopback listener. Binds 127.0.0.1 only, never all interfaces."""

    server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.callback = None
    server.timeout = 0.5
    return server


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    # A client that connects and sends nothing (a browser preconnect) holds
    # the one-request loop this long; Stop must land within 0.5 s.
    timeout = 0.5

    def do_GET(self):  # noqa: N802 (http.server API)
        url = urllib.parse.urlsplit(self.path)
        if url.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return
        self.server.callback = dict(urllib.parse.parse_qsl(url.query))
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Orbyn: sign-in received. You can close this tab.")

    def log_message(self, *args):  # the query carries the code: never log it
        pass


def wait_for_code(
    server: http.server.HTTPServer, state: str, deadline_s: float, cancelled=lambda: False
) -> tuple[str, str | None]:
    """(code, issued client id) from the callback whose state matches ours.
    ``cancelled()`` (Stop) ends the wait within the server's 0.5 s timeout."""

    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        if cancelled():
            raise SignInError("sign-in cancelled")
        server.handle_request()
        callback = server.callback
        if callback is None:
            continue
        server.callback = None
        if not secrets.compare_digest(callback.get("state", ""), state):
            continue  # not ours (another local page): keep waiting for ours
        if callback.get("error"):
            raise SignInError(f"sign-in refused: {callback['error']}")
        if not callback.get("code"):
            raise SignInError("the sign-in reply had no code")
        return callback["code"], callback.get("client_id")
    raise SignInError("sign-in timed out")


# --- tokens ---------------------------------------------------------------------------


def _token_request(form: dict, transport=None, timeout_s: float = 20.0) -> dict:
    from ghostcursor import policy

    if not policy.allows("chatgpt"):  # D180: local only signs in nowhere
        raise SignInError("blocked by your organisation's policy")
    with httpx.Client(transport=transport, timeout=timeout_s) as client:
        try:
            response = client.post(TOKEN_URL, data=form)
        except httpx.HTTPError as exc:
            raise SignInError(
                f"token endpoint unreachable: {type(exc).__name__}"
            ) from exc
    if response.status_code != 200:
        raise SignInError(f"token endpoint refused: HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError as exc:
        raise SignInError("token reply is not JSON") from exc
    if not isinstance(body, dict) or not isinstance(body.get("access_token"), str):
        raise SignInError("token reply has no access token")
    return body


def granted_scopes(body: dict) -> list[str]:
    scope = body.get("scope")
    if isinstance(scope, str):
        return scope.split()
    if isinstance(body.get("scopes"), list):
        return [s for s in body["scopes"] if isinstance(s, str)]
    return []


def _jwt():
    try:
        import jwt
    except ImportError as exc:
        raise SignInError("PyJWT is not installed (pip install pyjwt[crypto])") from exc
    return jwt


def _jwks_key(token: str):
    jwt = _jwt()

    return jwt.PyJWKClient(JWKS_URL).get_signing_key_from_jwt(token).key


def validate_id_token(
    token: str, *, client_id: str, nonce: str, key_for=_jwks_key
) -> dict:
    """Signature against OpenAI's JWKS, issuer, audience, expiry and our nonce."""

    jwt = _jwt()

    try:
        claims = jwt.decode(
            token,
            key_for(token),
            algorithms=["RS256"],
            audience=client_id,
            issuer=AUTH,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except Exception as exc:
        raise SignInError(f"ID token rejected: {type(exc).__name__}") from exc
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise SignInError("ID token nonce does not match this sign-in")
    return claims


def complete_sign_in(
    body: dict,
    *,
    client_id: str,
    nonce: str,
    host_id: str,
    now: float,
    key_for=_jwks_key,
) -> dict:
    """The record to store, once the reply proves plan usage was granted."""

    scopes = granted_scopes(body)
    if REQUIRED_SCOPE not in scopes:
        raise SignInError(
            "ChatGPT did not grant plan usage to Orbyn (needs a Plus or Pro plan)"
        )
    if not isinstance(body.get("refresh_token"), str):
        raise SignInError("token reply has no refresh token")
    claims = validate_id_token(
        body.get("id_token") or "", client_id=client_id, nonce=nonce, key_for=key_for
    )
    return {
        "issuer": AUTH,
        "subject": claims["sub"],
        "client_id": client_id,
        "ext_agent_host_id": host_id,
        "access_token": body["access_token"],
        "refresh_token": body["refresh_token"],
        "expires_at": now + int(body.get("expires_in") or 3600),
        "scopes": scopes,
    }


def sign_in(
    *,
    open_browser=webbrowser.open,
    deadline_s: float = 300.0,
    path: Path | None = None,
    cancelled=lambda: False,
) -> dict:
    """Interactive browser sign-in; stores and returns the credential record."""

    from ghostcursor import policy

    if not policy.allows("chatgpt"):  # before the browser opens, not after
        raise SignInError("everything stays on this computer: sign-in is off")

    previous = load(path) or {}
    host_id = previous.get("ext_agent_host_id") or f"urn:uuid:{uuid.uuid4()}"
    client_id = previous.get("client_id")
    try:
        server = listen(0 if client_id else REGISTRATION_PORT)
    except OSError as exc:
        raise SignInError(
            f"port {REGISTRATION_PORT} is busy; close the app using it and retry"
        ) from exc
    with server:
        redirect_uri = f"http://127.0.0.1:{server.server_address[1]}{CALLBACK_PATH}"
        verifier, challenge = pkce()
        state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        open_browser(
            authorize_url(
                client_id=client_id,
                redirect_uri=redirect_uri,
                state=state,
                nonce=nonce,
                challenge=challenge,
                host_id=host_id,
            )
        )
        code, issued = wait_for_code(server, state, deadline_s, cancelled)
    client_id = client_id or issued
    if not client_id:
        raise SignInError("ChatGPT did not issue a client id")
    body = _token_request(
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "resource": RESOURCE,
        }
    )
    record = complete_sign_in(
        body, client_id=client_id, nonce=nonce, host_id=host_id, now=time.time()
    )
    with _REFRESH:
        _UNSAVED.pop(path, None)  # a new account: never the old cached token
    save(record, path)
    return record


_REFRESH = threading.Lock()


def access_token(
    *, path: Path | None = None, transport=None, now=time.time
) -> str | None:
    """A current access token, refreshed when within a minute of expiry; None
    when not signed in or the refresh was refused (sign in again).

    Refreshes are serialized: if OpenAI rotates refresh tokens, two at once
    would void each other and sign the user out."""

    from ghostcursor import policy

    if not policy.allows("chatgpt"):  # IT blocked it: no token leaves (D180)
        return None
    with _REFRESH:
        try:
            return _current_token(path, transport, now)
        except (KeyError, TypeError, ValueError):  # a malformed record or reply
            return None


#: A refreshed record that could not be saved, by path. OpenAI may rotate the
#: refresh token, so losing it would sign the user out; kept until a save works.
_UNSAVED: dict = {}


def _current_token(path, transport, now) -> str | None:
    record = _UNSAVED.get(path) or load(path)
    if not signed_in(record):
        return None
    if now() < float(record.get("expires_at") or 0) - 60:
        return record["access_token"]
    # ponytail: the refresh request shape is not documented by OpenAI yet; this
    # is the standard OAuth refresh_token grant (RFC 6749 s6) plus `resource`.
    try:
        body = _token_request(
            {
                "grant_type": "refresh_token",
                "client_id": record["client_id"],
                "refresh_token": record["refresh_token"],
                "resource": RESOURCE,
            },
            transport,
            timeout_s=10.0,
        )
    except SignInError:
        return None
    record["access_token"] = body["access_token"]
    if isinstance(body.get("refresh_token"), str):
        record["refresh_token"] = body["refresh_token"]
    record["expires_at"] = now() + int(body.get("expires_in") or 3600)
    try:
        save(record, path)
        _UNSAVED.pop(path, None)
    except OSError:
        _UNSAVED[path] = record
    return record["access_token"]


def list_models(token: str, transport=None) -> list[tuple[str, str]]:
    """(slug, display name) of the models this account may pick."""

    with httpx.Client(transport=transport, timeout=20.0) as client:
        response = client.get(
            RESOURCE + "/models", headers={"Authorization": f"Bearer {token}"}
        )
    response.raise_for_status()
    models = response.json().get("models") or []
    return [
        (m["slug"], m.get("display_name") or m["slug"])
        for m in models
        if isinstance(m, dict) and m.get("visibility") == "list" and m.get("slug")
    ]
