"""The solo MVP workspace (docs/orbyn-plan/MVP.md, D173): one goal, with
Point, Research, Remember, Discuss, Plan and Teach around it. Every contract
here is data: none of it can select, authorize or execute anything."""


def write_atomic(path, text: str) -> None:
    """Write ``text`` whole or not at all: a crash mid-write must not leave a
    truncated file that the next load reads as empty and the next save wipes."""

    import os
    from pathlib import Path

    path = Path(path)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(text, encoding="utf-8", newline="\n")
    os.replace(partial, path)
