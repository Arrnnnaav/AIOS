"""Console palette (D186): fuzzy command hints + safe inline calculator.

The calculator is a parser on an untrusted line, so the security boundary --
only arithmetic, never names or calls, never a CPU bomb -- is pinned here, not
just the happy path.
"""

from __future__ import annotations

from ghostcursor.workspace import palette


def test_suggest_finds_the_nearest_command():
    assert palette.suggest("/convrt")[0] == "/convert"
    assert palette.suggest("/reserch")[0] == "/research"
    assert palette.suggest("/zzzzz") == []


def test_highlight_uppercases_shared_characters():
    assert palette.highlight("/convrt", "/convert") == "/CONVeRT"
    assert palette.highlight("", "/do") == "/do"  # nothing shared, unchanged


def test_every_listed_command_is_dispatched():
    """A command in the palette the console never handles would hint at a verb
    that does nothing; keep the list honest against __main__."""

    import pathlib

    source = (pathlib.Path(palette.__file__).with_name("__main__.py")).read_text(
        encoding="utf-8"
    )
    for cmd in palette.COMMANDS:
        assert f'"{cmd}"' in source, cmd


def test_calc_answers_plain_arithmetic():
    assert palette.calc("2 + 2") == "= 4"
    assert palette.calc("3 * (4 + 1)") == "= 15"
    assert palette.calc("10 / 4") == "= 2.5"
    assert palette.calc("2 ^ 10") == "= 1024"
    assert palette.calc("-5 + 2") == "= -3"


def test_calc_leaves_real_messages_alone():
    for line in ("hello", "42", "2 reasons to refactor", "", "   "):
        assert palette.calc(line) is None


def test_calc_refuses_code_and_bombs():
    assert palette.calc("__import__('os').system('x')") is None
    assert palette.calc("9 ** 9 ** 9") is None
    assert palette.calc("1 / 0") is None
    assert palette.calc("open('x')") is None
