"""A local unified diff of two files (D186): see what changed between two
versions without leaving the workspace. stdlib difflib; nothing is sent anywhere.
"""

from __future__ import annotations

import difflib


def unified(a_text: str, b_text: str, a_name: str = "a", b_name: str = "b") -> str:
    """A unified diff of two texts; "(identical)" when they match."""

    lines = list(
        difflib.unified_diff(
            a_text.splitlines(),
            b_text.splitlines(),
            fromfile=a_name,
            tofile=b_name,
            lineterm="",
        )
    )
    return "\n".join(lines) or "(identical)"


if __name__ == "__main__":  # ponytail: shows adds/removes, flags identical
    out = unified("one\ntwo\nthree", "one\n2\nthree", "old", "new")
    assert "-two" in out and "+2" in out and "--- old" in out
    assert unified("same", "same") == "(identical)"
    print("diffs ok")
