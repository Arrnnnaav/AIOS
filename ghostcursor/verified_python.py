"""Execute one Python payload from the exact bytes whose digest was approved.

Launching a verified path directly is a TOCTOU gap: Python executes module
top-level code before that module can hash ``__file__``.  This trusted runtime
bootstrap reads the payload once, checks those in-memory bytes, then compiles
and executes those same bytes.  A replacement before the read fails the hash;
a replacement after the read is irrelevant to the code being executed.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path


_SHA256 = re.compile(r"[0-9a-f]{64}")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) < 3 or arguments[0] != "--sha256":
        raise SystemExit("usage: verified_python --sha256 HEX PATH [ARG ...]")
    expected = arguments[1]
    if _SHA256.fullmatch(expected) is None:
        raise SystemExit("verified payload digest is invalid")
    path = Path(arguments[2]).resolve(strict=True)
    source = path.read_bytes()
    actual = hashlib.sha256(source).hexdigest()
    if actual != expected:
        raise SystemExit("verified payload bytes changed before execution")

    child_argv = [str(path), *arguments[3:]]
    namespace = {
        "__builtins__": __builtins__,
        "__file__": str(path),
        "__ghostcursor_verified_sha256__": actual,
        "__name__": "__main__",
        "__package__": None,
    }
    previous = sys.argv
    try:
        sys.argv = child_argv
        exec(compile(source, str(path), "exec"), namespace, namespace)
    finally:
        sys.argv = previous
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
