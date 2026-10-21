"""Two small delights for the console (D186), both pure and local:

- ``suggest`` -- a typo'd ``/comand`` gets a "did you mean" instead of the
  whole help dump (the fuzzy-match trick every launcher people love is built
  on: Raycast, PowerToys Run, Trilium's jump-to).
- ``calc`` -- a plain arithmetic line (``3 * (4 + 1)``) is answered on the spot
  instead of going to a model, like Raycast's natural calculator. Evaluated by
  walking the AST, never ``eval`` -- only numbers and + - * / // % ** and unary
  minus are allowed, so a line can't run code or read a name.
"""

from __future__ import annotations

import ast
import difflib
import operator

#: Every slash command the console dispatches (keep in step with __main__).
COMMANDS = (
    "/point",
    "/voice",
    "/dictate",
    "/research",
    "/evidence",
    "/remember",
    "/clip",
    "/ideate",
    "/plan",
    "/agent",
    "/web",
    "/convert",
    "/do",
    "/deck",
    "/deepresearch",
    "/researchdeck",
    "/guide",
    "/skill",
    "/teach",
    "/providers",
    "/accounts",
    "/doctor",
    "/know",
    "/brain",
    "/stats",
    "/act",
    "/tip",
    "/quit",
    "/clips",
    "/snippet",
    "/capture",
    "/x",
    "/crew",
    "/notes",
    "/ask",
    "/related",
    "/find",
    "/todo",
    "/export",
    "/diff",
    "/pin",
)


def suggest(command: str) -> list[str]:
    """Known commands closest to an unknown one, nearest first (may be empty)."""

    return difflib.get_close_matches(command, COMMANDS, n=3, cutoff=0.6)


def highlight(typed: str, command: str) -> str:
    """``command`` with the characters it shares with ``typed`` upper-cased, so
    a "did you mean" shows *why* it matched (Notebag's missing-highlight gripe).
    Purely cosmetic -- the letters that line up stand out, the rest stay lower.
    """

    matcher = difflib.SequenceMatcher(None, typed.lower(), command.lower())
    out = list(command)
    for _i, j, n in matcher.get_matching_blocks():
        for k in range(j, j + n):
            out[k] = out[k].upper()
    return "".join(out)


_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}


def _eval(node):
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        right = _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ValueError("exponent too large")  # no 9**9**9 CPU bomb
        return _BINARY[type(node.op)](_eval(node.left), right)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _eval(node.operand)
        return v if isinstance(node.op, ast.UAdd) else -v
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    raise ValueError("not a plain arithmetic expression")


def calc(text: str) -> str | None:
    """The value of a plain arithmetic line, or None if it isn't one.

    None (not an error) for anything that isn't pure arithmetic, so the caller
    just falls through to the normal chat path -- "2 reasons to ..." is a
    sentence, not a sum.
    """

    stripped = text.strip()
    # Must look like a sum: digits and operators only. Keeps words out so the
    # model still handles real messages that merely contain a number.
    if not stripped or not all(c in "0123456789.+-*/%()^ \t" for c in stripped):
        return None
    if not any(c in "+-*/%^" for c in stripped):
        return None  # a bare number is not a question
    try:
        tree = ast.parse(stripped.replace("^", "**"), mode="eval")
        value = _eval(tree.body)
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"= {value}"


if __name__ == "__main__":  # ponytail: one runnable check for the parser path
    assert calc("2 + 2") == "= 4"
    assert calc("3 * (4 + 1)") == "= 15"
    assert calc("10 / 4") == "= 2.5"
    assert calc("2 ^ 10") == "= 1024"
    assert calc("7 // 2") == "= 3"
    assert calc("-5 + 2") == "= -3"
    assert calc("hello") is None  # a message, not a sum
    assert calc("42") is None  # a bare number asks nothing
    assert calc("2 reasons") is None  # words present -> chat
    assert calc("9 ** 9 ** 9") is None  # CPU bomb refused -> falls through
    assert calc("1/0") is None  # div by zero -> not a result
    assert calc("__import__('os')") is None  # no names, no calls
    assert suggest("/convrt")[0] == "/convert"
    assert suggest("/reserch")[0] == "/research"
    assert suggest("/zzzzz") == []
    assert highlight("/convrt", "/convert") == "/CONVeRT"  # shared chars upper
    assert highlight("", "/do") == "/do"  # nothing shared -> unchanged
    print("palette ok")
