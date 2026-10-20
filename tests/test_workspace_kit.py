"""The /x utility belt (D186): stdlib conversions, local and offline.

The parsers that can reject bad input (base64, colours, timestamps, password
length) are pinned, not just the happy path -- a utility that silently returns
garbage on bad input is worse than one that says no.
"""

from __future__ import annotations

from ghostcursor.workspace import kit


def test_round_trips():
    assert kit.run("unb64", kit.run("b64", "hello")) == "hello"
    assert kit.run("urldec", kit.run("urlenc", "a b&c=d")) == "a b&c=d"
    assert kit.run("rgb2hex", "255 136 0") == "#ff8800"
    assert kit.run("hex2rgb", "#ff8800") == "rgb(255, 136, 0)"


def test_colour_forms():
    assert kit.run("hex2rgb", "f80") == "rgb(255, 136, 0)"
    assert kit.run("hex2rgb", "nope").startswith("want a hex")
    assert kit.run("rgb2hex", "300 0 0").startswith("want three")


def test_generators_are_bounded():
    assert len(kit.run("uuid", "")) == 36
    assert len(kit.run("pass", "")) == 20
    assert len(kit.run("pass", "16")) == 16
    assert len(kit.run("pass", "1")) == 8  # floored
    assert len(kit.run("pass", "9999")) == 128  # capped


def test_time_and_count_and_unknown():
    assert kit.run("time", "0") == "1970-01-01 00:00:00 UTC"
    assert kit.run("time", "x").startswith("want a whole")
    assert kit.run("count", "a b c") == "3 words, 5 chars, 1 lines"
    assert kit.run("count", "") == "0 words, 0 chars, 0 lines"
    assert kit.run("bogus", "").startswith("unknown op")


def test_json_slug_sha256():
    assert kit.run("json", '{"a":1}').splitlines()[0] == "{"
    assert kit.run("json", "nope").startswith("not valid JSON")
    assert kit.run("slug", "Hello, World!") == "hello-world"
    assert kit.run("slug", "   ").startswith("nothing to")
    # known SHA-256 of the empty string
    assert kit.run("sha256", "") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
