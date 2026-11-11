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
    # ``-I`` intentionally disables the user site and ``-S`` skips every
    # ``.pth``. GhostCursor's Windows dependencies may be installed in either
    # the system or the user site, so add each site directory itself without
    # running its startup code, plus PyWin32's three import directories and
    # DLL directory, which its ``.pth`` would normally add. These are
    # interpreter-owned dependency locations, never the plugin payload root.
    install_paths = sysconfig.get_paths()
    dependency_paths, dll_directories = _dependency_paths(
        [
            Path(install_paths["purelib"]).resolve(),
            Path(install_paths["platlib"]).resolve(),
            Path(site.getusersitepackages()).resolve(),
        ],
        exclude=(payload_root, path.parent),
    )
    for dependency in dependency_paths:
        if str(dependency) not in safe_paths:
            safe_paths.append(str(dependency))
    dll_handles = [
        os.add_dll_directory(str(d))
        for d in dll_directories
        if hasattr(os, "add_dll_directory")
    ]
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
        for handle in dll_handles:
            handle.close()
    return 0


def _dependency_paths(
    site_dirs: list[Path], *, exclude: tuple[Path, ...] = ()
) -> tuple[list[Path], list[Path]]:
    """Existing site directories with PyWin32's import directories, in order,
    and its DLL directories -- for the system and the user site alike."""

    paths: list[Path] = []
    dlls: list[Path] = []
    for root in site_dirs:
        for directory in (root, root / "win32", root / "win32" / "lib", root / "Pythonwin"):
            if directory.is_dir() and directory not in paths and directory not in exclude:
                paths.append(directory)
        dll = root / "pywin32_system32"
        if dll.is_dir() and dll not in dlls and dll not in exclude:
            dlls.append(dll)
    return paths, dlls


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
