"""Sign in with ChatGPT, hermetically: no browser, no network, no real account.

Properties: the sign-in is bound to our state, nonce, client id and OpenAI's
issuer; plan usage needs the granted scope; the listener is loopback only;
inference never asks OpenAI to store anything, never retries (each retry is
charged to the user's plan), and counts only a completed stream; a spent
plan allowance is RATE_LIMITED, never a guess.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from ghostcursor.providers import (
    Envelope,
    FailureKind,
    Gateway,
    ProviderError,
    Tainted,
    chatgpt,
    clients,
)

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PLAN = json.dumps(
    {"steps": [{"instruction": "Click Save", "expected_change": "chosen_disappears"}]}
)


def _id_token(**claims):
    body = {
        "iss": chatgpt.AUTH,
        "aud": "oaiapp_1",
        "sub": "user-1",
        "nonce": "n1",
        "exp": int(time.time()) + 600,
    }
    body.update(claims)
    return jwt.encode(body, KEY, algorithm="RS256")


def _reply(**overrides):
    body = {
        "access_token": "at",
        "refresh_token": "rt",
        "expires_in": 3600,
        "scope": "openid profile email offline_access resource.invoke "
        "chatgpt.tokens.use.direct",
        "id_token": _id_token(),
    }
    body.update(overrides)
    return body


def _complete(body, nonce="n1"):
    return chatgpt.complete_sign_in(
        body,
        client_id="oaiapp_1",
        nonce=nonce,
        host_id="urn:uuid:h",
        now=1000.0,
        key_for=lambda token: KEY.public_key(),
    )


# --- the authorization request ---------------------------------------------------


def test_first_sign_in_registers_and_later_ones_reuse_the_issued_client():
    common = dict(
        redirect_uri="http://127.0.0.1:1455/auth/callback",
        state="s",
        nonce="n",
        challenge="c",
        host_id="urn:uuid:h",
    )
    first = httpx.URL(chatgpt.authorize_url(client_id=None, **common)).params
    assert first["client_id"] == "dynamic_agent_client"
    assert first["agent_name_hint"] == "Orbyn"
    assert first["code_challenge_method"] == "S256"
    assert "chatgpt.tokens.use.direct" in first["scope"].split()
    assert first["resource"] == "https://api.openai.com/v1"
    assert first["ext_agent_host_id"] == "urn:uuid:h"
    later = httpx.URL(chatgpt.authorize_url(client_id="oaiapp_1", **common)).params
    assert later["client_id"] == "oaiapp_1" and "agent_name_hint" not in later


def test_the_pkce_challenge_is_the_s256_of_the_verifier():
    import base64
    import hashlib

    verifier, challenge = chatgpt.pkce()
    digest = hashlib.sha256(verifier.encode()).digest()
    assert challenge == base64.urlsafe_b64encode(digest).decode().rstrip("=")
    assert chatgpt.pkce()[0] != verifier


def _hit(port, query, path="/auth/callback"):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}{path}?{query}", timeout=5)
    except urllib.error.HTTPError:
        pass


def _callback(query, *, state="s1", before=(), before_query="code=stray&state=s1"):
    with chatgpt.listen(0) as server:
        host, port = server.server_address
        assert host == "127.0.0.1"

        def send():
            for path in before:
                _hit(port, before_query, path)
            _hit(port, query)

        threading.Thread(target=send, daemon=True).start()
        return chatgpt.wait_for_code(server, state, 10.0)


def test_the_callback_must_carry_our_state():
    assert _callback("code=c1&state=s1&client_id=oaiapp_1") == ("c1", "oaiapp_1")
    # a reply with another state (any local page can send one) is ignored
    got = _callback(
        "code=c1&state=s1",
        before=("/auth/callback",),
        before_query="code=forged&state=forged",
    )
    assert got == ("c1", None)
    with pytest.raises(chatgpt.SignInError, match="refused"):
        _callback("error=access_denied&state=s1")
    with pytest.raises(chatgpt.SignInError, match="no code"):
        _callback("state=s1")


def test_requests_off_the_callback_path_are_ignored():
    got = _callback("code=c2&state=s1", before=("/favicon.ico",))
    assert got == ("c2", None)


def test_the_listener_gives_up_at_its_deadline():
    with chatgpt.listen(0) as server, pytest.raises(chatgpt.SignInError, match="timed"):
        chatgpt.wait_for_code(server, "s", 0.6)


def test_stop_ends_the_sign_in_wait():
    import time

    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()
    started = time.monotonic()
    with chatgpt.listen(0) as server, pytest.raises(chatgpt.SignInError, match="cancelled"):
        chatgpt.wait_for_code(server, "s", 300.0, stop.is_set)
    assert time.monotonic() - started < 2  # not the 300 s deadline


# --- the token reply --------------------------------------------------------------


def test_a_valid_reply_becomes_a_record():
    record = _complete(_reply())
    assert record["access_token"] == "at" and record["refresh_token"] == "rt"
    assert record["client_id"] == "oaiapp_1" and record["subject"] == "user-1"
    assert record["expires_at"] == 4600.0
    assert record["ext_agent_host_id"] == "urn:uuid:h"


def test_plan_usage_needs_the_granted_scope():
    with pytest.raises(chatgpt.SignInError, match="plan usage"):
        _complete(_reply(scope="openid profile email offline_access"))


@pytest.mark.parametrize(
    "claims",
    [
        {"nonce": "replayed"},
        {"aud": "another-app"},
        {"iss": "https://evil.example"},
        {"exp": int(time.time()) - 10},
    ],
)
def test_an_id_token_not_minted_for_this_sign_in_is_refused(claims):
    with pytest.raises(chatgpt.SignInError):
        _complete(_reply(id_token=_id_token(**claims)))


def test_an_id_token_signed_by_another_key_is_refused():
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(
        jwt.decode(_id_token(), options={"verify_signature": False}),
        other,
        algorithm="RS256",
    )
    with pytest.raises(chatgpt.SignInError):
        _complete(_reply(id_token=forged))


# --- the stored record and refresh -------------------------------------------------


def test_access_token_refreshes_near_expiry_and_stores_the_new_tokens(tmp_path):
    path = tmp_path / "c.cred"
    assert chatgpt.access_token(path=path) is None
    chatgpt.save(_complete(_reply()), path)
    assert chatgpt.access_token(path=path, now=lambda: 2000.0) == "at"

    forms = []

    def token(request):
        forms.append(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(200, json={"access_token": "at2", "refresh_token": "rt2"})

    fresh = chatgpt.access_token(
        path=path, transport=httpx.MockTransport(token), now=lambda: 4560.0
    )
    assert fresh == "at2"
    assert forms[0]["grant_type"] == "refresh_token"
    assert forms[0]["refresh_token"] == "rt" and forms[0]["client_id"] == "oaiapp_1"
    assert chatgpt.load(path)["refresh_token"] == "rt2"


def test_a_refused_refresh_means_sign_in_again(tmp_path):
    path = tmp_path / "c.cred"
    chatgpt.save(_complete(_reply()), path)
    refused = httpx.MockTransport(lambda r: httpx.Response(400, json={}))
    assert chatgpt.access_token(path=path, transport=refused, now=lambda: 9e9) is None


def test_sign_out_forgets_tokens_but_keeps_the_host_id(tmp_path):
    path = tmp_path / "c.cred"
    chatgpt.save(_complete(_reply()), path)
    chatgpt.sign_out(path)
    assert chatgpt.load(path) == {"ext_agent_host_id": "urn:uuid:h"}
    assert not chatgpt.signed_in(chatgpt.load(path))


def test_the_record_is_encrypted_at_rest(tmp_path):
    path = tmp_path / "c.cred"
    chatgpt.save(_complete(_reply()), path)
    blob = path.read_bytes()
    assert b"access_token" not in blob and b"oaiapp_1" not in blob


def test_models_keeps_only_listed_entries():
    body = {
        "models": [
            {"slug": "a", "display_name": "A", "visibility": "list"},
            {"slug": "b", "visibility": "hide"},
        ]
    }
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=body))
    assert chatgpt.list_models("t", transport) == [("a", "A")]


# --- inference through the gateway -----------------------------------------------


def _sse(*events):
    text = "".join(f"event: x\ndata: {json.dumps(e)}\n\n" for e in events)
    return text.encode()


def _delta(text):
    return {"type": "response.output_text.delta", "delta": text}


COMPLETED = {
    "type": "response.completed",
    "response": {"model": "gpt-x", "usage": {"input_tokens": 9, "output_tokens": 4}},
}


def _gateway(tmp_path, *events, status=200):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, content=_sse(*events))

    gateway = Gateway(
        system_two=("chatgpt",),
        transport=httpx.MockTransport(handler),
        key_lookup=lambda name: "at" if name == "chatgpt" else None,
        log_path=tmp_path / "log",
    )
    return gateway, calls


def _envelope():
    return Envelope(
        task="plan",
        trusted={"goal": "save"},
        tainted={"c": {"c1": Tainted.of("uia_name", "Save")}},
    )


def test_a_completed_stream_is_the_answer_and_nothing_is_stored(tmp_path):
    gateway, calls = _gateway(tmp_path, _delta(PLAN[:20]), _delta(PLAN[20:]), COMPLETED)
    plan = gateway.plan(_envelope())
    assert plan.steps[0].instruction == "Click Save"
    sent = json.loads(calls[0].content)
    assert calls[0].url == "https://api.openai.com/v1/responses"
    assert calls[0].headers["authorization"] == "Bearer at"
    assert sent["store"] is False and sent["stream"] is True
    assert "temperature" not in sent
    assert all(item["role"] != "system" for item in sent["input"])
    assert "Schema:" in sent["instructions"]
    # screen text travels only as labelled data in the user turn
    assert "uia_name" not in sent["instructions"]
    assert "uia_name" in sent["input"][0]["content"]
    line = json.loads((tmp_path / "log").read_text())
    assert line["provider"] == "chatgpt" and line["output_tokens"] == 4


def test_config_extras_cannot_turn_storage_or_streaming_back_on(tmp_path, monkeypatch):
    config = clients.SYSTEM_TWO["chatgpt"]
    monkeypatch.setitem(
        clients.SYSTEM_TWO,
        "chatgpt",
        clients.ProviderConfig(
            config.name,
            config.base_url,
            config.model,
            config.key_name,
            config.timeout_s,
            (("store", True), ("stream", False)),
            api="responses",
        ),
    )
    gateway, calls = _gateway(tmp_path, _delta(PLAN), COMPLETED)
    gateway.plan(_envelope())
    sent = json.loads(calls[0].content)
    assert sent["store"] is False and sent["stream"] is True


@pytest.mark.parametrize(
    "code",
    [
        "subscription_sharing_usage_limit_exceeded",
        "subscription_sharing_usage_unavailable",
    ],
)
def test_a_spent_plan_is_rate_limited_not_guessed(tmp_path, code):
    failed = {"type": "response.failed", "response": {"error": {"code": code}}}
    gateway, calls = _gateway(tmp_path, _delta(PLAN), failed)
    with pytest.raises(ProviderError) as raised:
        gateway.plan(_envelope())
    assert raised.value.kind is FailureKind.RATE_LIMITED and len(calls) == 1


@pytest.mark.parametrize(
    "events",
    [
        (_delta(PLAN),),  # stream ended with no completion
        # incomplete is final, whatever arrives after it
        (_delta(PLAN), {"type": "response.incomplete"}, COMPLETED),
        (_delta(PLAN), {"type": "response.failed", "response": {"error": {}}}),
        (COMPLETED,),  # completed but empty
    ],
)
def test_only_a_completed_stream_with_content_counts(tmp_path, events):
    gateway, _ = _gateway(tmp_path, *events)
    with pytest.raises(ProviderError) as raised:
        gateway.plan(_envelope())
    assert raised.value.kind is FailureKind.UNAVAILABLE  # every provider failed


@pytest.mark.parametrize("status", [429, 500, 503])
def test_a_refused_request_is_never_retried_on_the_users_plan(tmp_path, status):
    gateway, calls = _gateway(tmp_path, status=status)
    with pytest.raises(ProviderError):
        gateway.plan(_envelope())
    assert len(calls) == 1


def test_an_expired_token_is_auth_failed(tmp_path):
    gateway, _ = _gateway(tmp_path, status=401)
    with pytest.raises(ProviderError) as raised:
        gateway.plan(_envelope())
    assert "auth_failed" in str(raised.value)


def test_not_signed_in_sends_nothing_and_falls_through(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": PLAN}}], "model": "m"}
        )

    gateway = Gateway(
        transport=httpx.MockTransport(handler),
        key_lookup=lambda name: "k" if name == "nvidia" else None,
        log_path=tmp_path / "log",
    )
    assert gateway.system_two[0] == "chatgpt"
    gateway.plan(_envelope())
    assert [c.url.host for c in calls] == ["integrate.api.nvidia.com"]


def test_a_malformed_refresh_reply_means_sign_in_again(tmp_path):
    path = tmp_path / "c.cred"
    chatgpt.save(_complete(_reply()), path)
    odd = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"access_token": "x", "expires_in": "soon"})
    )
    assert chatgpt.access_token(path=path, transport=odd, now=lambda: 9e9) is None


def test_a_spent_plan_sent_as_an_http_error_is_rate_limited(tmp_path):
    body = {"error": {"code": "subscription_sharing_usage_limit_exceeded"}}
    gateway = Gateway(
        system_two=("chatgpt",),
        transport=httpx.MockTransport(lambda r: httpx.Response(400, json=body)),
        key_lookup=lambda name: "at",
        log_path=tmp_path / "log",
    )
    with pytest.raises(ProviderError) as raised:
        gateway.plan(_envelope())
    assert raised.value.kind is FailureKind.RATE_LIMITED


def test_hermetic_tests_never_see_a_real_token():
    import os

    from ghostcursor.providers import keys

    assert "ORBYN_CHATGPT_API_KEY" not in os.environ
    assert keys.get_key("chatgpt") is None


def test_a_refreshed_token_that_cannot_be_saved_is_kept_in_memory(tmp_path, monkeypatch):
    path = tmp_path / "c.cred"
    chatgpt.save(_complete(_reply()), path)
    forms = []

    def token(request):
        forms.append(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(200, json={"access_token": f"at{len(forms) + 1}", "refresh_token": f"rt{len(forms) + 1}"})

    def no_disk(record, path=None):
        raise PermissionError("locked")

    monkeypatch.setattr(chatgpt, "save", no_disk)
    monkeypatch.setattr(chatgpt, "_UNSAVED", {})
    transport = httpx.MockTransport(token)
    assert chatgpt.access_token(path=path, transport=transport, now=lambda: 4560.0) == "at2"
    assert chatgpt.access_token(path=path, transport=transport, now=lambda: 9000.0) == "at3"
    assert forms[1]["refresh_token"] == "rt2"  # the rotated token, not the dead one on disk


class _Stalls(httpx.SyncByteStream):
    """A stream that sends one line, then hangs until it is closed (as a
    socket read does), like a provider that stops mid-answer."""

    def __init__(self):
        self.closed = threading.Event()

    def __iter__(self):
        yield b'data: {"type":"response.output_text.delta","delta":"x"}\n\n'
        self.closed.wait(10)
        raise httpx.ReadError("closed")

    def close(self):
        self.closed.set()


@pytest.mark.parametrize("stop_after", ["cancel", "deadline"])
def test_a_stalled_stream_ends_at_stop_or_the_deadline(stop_after):
    from ghostcursor.providers.clients import ProviderConfig, responses_json_call
    from ghostcursor.providers.errors import FailureKind, ProviderError

    stream = _Stalls()
    transport = httpx.MockTransport(lambda r: httpx.Response(200, stream=stream))
    config = ProviderConfig("chatgpt", "https://x.test", "m", None, 30.0, api="responses")
    started = time.monotonic()
    pressed = lambda: stop_after == "cancel" and time.monotonic() - started > 0.3
    with pytest.raises(ProviderError) as caught:
        responses_json_call(
            config, "k", [{"role": "user", "content": "q"}], {},
            transport=transport, deadline_s=0.5 if stop_after == "deadline" else 30.0,
            cancelled=pressed,
        )  # fmt: skip
    assert time.monotonic() - started < 2.0  # not the 10 s the read would hang
    want = FailureKind.CANCELLED if stop_after == "cancel" else FailureKind.TIMEOUT
    assert caught.value.kind is want


def test_stop_lands_quickly_even_with_an_idle_preconnect():
    import socket

    stop = threading.Event()
    with chatgpt.listen(0) as server:
        idle = socket.create_connection(server.server_address)  # sends nothing
        threading.Timer(0.2, stop.set).start()
        started = time.monotonic()
        with pytest.raises(chatgpt.SignInError, match="cancelled"):
            chatgpt.wait_for_code(server, "s", 300.0, stop.is_set)
        idle.close()
    assert time.monotonic() - started < 1.5  # not the old 5 s handler timeout
