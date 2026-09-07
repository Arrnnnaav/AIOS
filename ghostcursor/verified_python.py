"""Execute one Python payload from the exact bytes whose digest was approved.

Launching a verified path directly is a TOCTOU gap: Python executes module
top-level code before that module can hash ``__file__``.  This trusted runtime
bootstrap reads the payload once, checks those in-memory bytes, then compiles
and executes those same bytes.  A replacement before the read fails the hash;
a replacement after the read is irrelevant to the code being executed.
"""

from __future__ import annotations

import hashlib
import os
import re
import site
import sys
import sysconfig
from pathlib import Path


_SHA256 = re.compile(r"[0-9a-f]{64}")


def main(argv: list[str] | None = None) -> int:
    if not sys.flags.isolated or not sys.flags.no_site or not sys.flags.safe_path:
        raise SystemExit("verified Python requires -I -S startup isolation")
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

    # Isolated mode kept the payload working directory and PYTHONPATH out
    # while THIS trusted bootstrap loaded. Add only the trusted GhostCursor
    # root before running the approved payload; never add the payload
    # directory, so a mutable sibling cannot become executable by import.
    trusted_root = Path(__file__).resolve().parent.parent
    payload_root = Path.cwd().resolve()
    safe_paths: list[str] = []
    for item in sys.path:
        if not item:
            continue
        try:
            resolved = Path(item).resolve()
        except OSError:
            continue
        if resolved == payload_root or resolved == path.parent:
            continue
        safe_paths.append(str(resolved))
    # ``-I`` intentionally disables the user site. GhostCursor's Windows
    # dependencies may legitimately be installed there, so add the directory
    # itself without running its ``.pth`` startup code. PyWin32 also needs its
    # three import directories and DLL directory explicitly. These are
    # interpreter-owned dependency locations, never the plugin payload root.
    user_site = Path(site.getusersitepackages()).resolve()
    install_paths = sysconfig.get_paths()
    dependency_paths = [
        Path(install_paths["purelib"]).resolve(),
        Path(install_paths["platlib"]).resolve(),
        user_site,
        user_site / "win32",
        user_site / "win32" / "lib",
        user_site / "Pythonwin",
    ]
    for dependency in dependency_paths:
        if dependency.is_dir() and str(dependency) not in safe_paths:
            safe_paths.append(str(dependency))
    dll_directory = user_site / "pywin32_system32"
    dll_handle = None
    if dll_directory.is_dir() and hasattr(os, "add_dll_directory"):
        dll_handle = os.add_dll_directory(str(dll_directory))
    sys.path[:] = [str(trusted_root), *safe_paths]

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
        if dll_handle is not None:
            dll_handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
