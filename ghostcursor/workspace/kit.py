"""A little utility belt (D186): the throwaway conversions people keep a
Raycast/DevToys window open for -- base64, URL-encode, a hex<->rgb colour, a
UUID, a strong password, a unix timestamp, a quick word count. All stdlib, all
local, all offline. One ``/x <op> <args>`` dispatcher in the console.

Each op is a plain function ``str -> str``; ``run`` looks one up and catches its
errors so the console never sees a traceback. Nothing here touches a model, the
network, or an app.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json as _json_mod
import re
import secrets
import string
import urllib.parse
import uuid
from datetime import datetime, timezone


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _unb64(text: str) -> str:
    try:
        return base64.b64decode(text.strip().encode("ascii"), validate=True).decode(
            "utf-8"
        )
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"not valid base64: {exc}")


def _urlenc(text: str) -> str:
    return urllib.parse.quote(text, safe="")


def _urldec(text: str) -> str:
    return urllib.parse.unquote(text)


def _hex2rgb(text: str) -> str:
    h = text.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6 or any(c not in string.hexdigits for c in h):
        raise ValueError("want a hex colour like #ff8800 or f80")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgb({r}, {g}, {b})"


def _rgb2hex(text: str) -> str:
    nums = [n for n in text.replace(",", " ").split() if n]
    if len(nums) != 3 or not all(n.isdigit() and 0 <= int(n) <= 255 for n in nums):
        raise ValueError("want three 0-255 values like 255 136 0")
    return "#" + "".join(f"{int(n):02x}" for n in nums)


def _uuid(text: str) -> str:
    return str(uuid.uuid4())


def _password(text: str) -> str:
    n = int(text) if text.strip().isdigit() else 20
    n = max(8, min(n, 128))  # bounded: no 1-char password, no 10k-char line
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _time(text: str) -> str:
    """No arg -> the current unix epoch. An integer -> that epoch as UTC ISO."""

    t = text.strip()
    if not t:
        return str(int(datetime.now(tz=timezone.utc).timestamp()))
    if not t.lstrip("-").isdigit():
        raise ValueError("want a whole unix timestamp, e.g. 1700000000")
    return datetime.fromtimestamp(int(t), tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def _count(text: str) -> str:
    return (
        f"{len(text.split())} words, {len(text)} chars, "
        f"{len(text.splitlines()) or (1 if text else 0)} lines"
    )


def _json(text: str) -> str:
    """Pretty-print and validate JSON; a clear error if it doesn't parse."""

    try:
        return _json_mod.dumps(
            _json_mod.loads(text), indent=2, ensure_ascii=False, sort_keys=False
        )
    except ValueError as exc:
        raise ValueError(f"not valid JSON: {exc}")


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().casefold()).strip("-")
    if not slug:
        raise ValueError("nothing to slugify")
    return slug


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


OPS = {
    "b64": _b64,
    "unb64": _unb64,
    "urlenc": _urlenc,
    "urldec": _urldec,
    "hex2rgb": _hex2rgb,
    "rgb2hex": _rgb2hex,
    "uuid": _uuid,
    "pass": _password,
    "time": _time,
    "count": _count,
    "json": _json,
    "slug": _slug,
    "sha256": _sha256,
}


def run(op: str, arg: str = "") -> str:
    """Apply ``op`` to ``arg``; return the result or a one-line error. The
    console passes raw user text straight through."""

    fn = OPS.get(op.lower())
    if fn is None:
        return f"unknown op '{op}'. try: {', '.join(OPS)}"
    try:
        return fn(arg)
    except ValueError as exc:
        return str(exc)


if __name__ == "__main__":  # ponytail: round-trips + the parsers that can fail
    assert run("b64", "hi") == "aGk="
    assert run("unb64", "aGk=") == "hi"
    assert run("unb64", "!!!").startswith("not valid base64")
    assert run("urlenc", "a b&c") == "a%20b%26c"
    assert run("urldec", "a%20b%26c") == "a b&c"
    assert run("hex2rgb", "#ff8800") == "rgb(255, 136, 0)"
    assert run("hex2rgb", "f80") == "rgb(255, 136, 0)"
    assert run("rgb2hex", "255, 136, 0") == "#ff8800"
    assert run("rgb2hex", "300 0 0").startswith("want three")
    assert len(run("uuid", "")) == 36
    assert len(run("pass", "16")) == 16 and len(run("pass", "")) == 20
    assert len(run("pass", "1")) == 8  # floored, not a 1-char password
    assert run("time", "0") == "1970-01-01 00:00:00 UTC"
    assert run("time", "x").startswith("want a whole")
    assert run("count", "a b c") == "3 words, 5 chars, 1 lines"
    assert run("json", '{"b":1,"a":2}').splitlines()[0] == "{"
    assert run("json", "{bad}").startswith("not valid JSON")
    assert run("slug", "Hello, World!") == "hello-world"
    assert run("slug", "!!!").startswith("nothing to")
    assert run("sha256", "") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert run("nope", "").startswith("unknown op")
    print("kit ok")
