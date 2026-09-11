"""Production never imports a devtool.

`ghostcursor/devtools/` holds tools that reach real effects while deliberately
bypassing the reviewed product path. `act_acceptance.py` says so in its first
paragraph -- it calls `approve_action_graph` and `execute_approved_graph`
directly and never mints the one-use `ActExecutionRequest` that D121 requires of
the manager. `act_live_node.py` dispatches a real UIA effect under deadlines it
hardcodes rather than taking the measured ones.

That is legitimate for a diagnostic and fatal for production. The separation was
real at every commit so far, and it was held by nothing but habit: an activation
review checked by hand, found it clean, and pointed out that a single
`from ghostcursor.devtools import ...` would make the bypass reachable from the
product with no test objecting.

So the separation is now a property of the repository rather than of whoever
edits it next. This is the D031 distinction: "no production module happens to
import a devtool today" correlates with the boundary holding; "no production
module CAN import a devtool without failing a test" implies it.

The dependency runs one way only. A devtool importing production code is the
entire point of a devtool.
"""

import ast
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

_DEVTOOLS = "ghostcursor.devtools"


def _production_modules():
    """Every tracked `ghostcursor/` module except the devtools themselves."""

    listed = subprocess.run(
        ["git", "ls-files", "-z", "ghostcursor"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if listed.returncode != 0:
        pytest.skip("not a git work tree")
    names = [
        n
        for n in listed.stdout.decode("utf-8").split(chr(0))
        if n.endswith(".py") and not n.startswith("ghostcursor/devtools/")
    ]
    return sorted(names)


def _devtool_imports(source: str):
    """Every import naming `ghostcursor.devtools`, with its line."""

    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _DEVTOOLS or alias.name.startswith(_DEVTOOLS + "."):
                    found.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            # A relative import from inside the package resolves to the same
            # place: `from .devtools import x` in `ghostcursor/foo.py`.
            if node.level and any(a.name == "devtools" for a in node.names):
                found.append(f"line {node.lineno}: from . import devtools")
            if module == _DEVTOOLS or module.startswith(_DEVTOOLS + "."):
                found.append(f"line {node.lineno}: from {module} import ...")
            if node.level and module.split(".")[0] == "devtools":
                found.append(f"line {node.lineno}: from .{module} import ...")
    return found


def test_the_production_module_set_is_derived_and_not_empty():
    """Non-vacuity: a check over an empty set passes while checking nothing."""

    modules = _production_modules()

    assert len(modules) >= 30, len(modules)
    for required in (
        "ghostcursor/act_runtime.py",
        "ghostcursor/manager.py",
        "ghostcursor/act_cli.py",
        "ghostcursor/run.py",
    ):
        assert required in modules, required
    assert not any(m.startswith("ghostcursor/devtools/") for m in modules)


def test_no_production_module_imports_a_devtool():
    """The property: the bypass paths cannot be reached from the product."""

    offenders = []
    for name in _production_modules():
        source = (ROOT / name).read_text(encoding="utf-8")
        for hit in _devtool_imports(source):
            offenders.append(f"{name}: {hit}")

    assert not offenders, (
        "production imports a devtool, which makes the reviewed-path bypass "
        "reachable from the product:\n" + "\n".join(offenders)
    )


def test_the_scan_catches_every_import_form():
    """A check that cannot fire proves nothing about the files it passed."""

    assert _devtool_imports("import ghostcursor.devtools.act_acceptance")
    assert _devtool_imports("from ghostcursor.devtools import act_campaign")
    assert _devtool_imports("from ghostcursor.devtools.act_cli import x")
    assert _devtool_imports("from . import devtools")
    assert _devtool_imports("from .devtools.act_diagnosis import read")
    # The one-way direction stays legal, and ordinary imports are untouched.
    assert not _devtool_imports("from ghostcursor.act_runtime import approve")
    assert not _devtool_imports("import ghostcursor.act_protocol")
