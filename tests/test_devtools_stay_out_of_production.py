"""Production never imports a devtool.

`ghostcursor/devtools/` holds tools that reach real effects while deliberately
bypassing the reviewed product path. `act_acceptance.py` says so in its first
paragraph -- it calls `approve_action_graph` and `execute_approved_graph`
directly and never mints the one-use `ActExecutionRequest` that D121 requires of
the manager. `act_live_node.py` dispatches a real UIA effect while using the
measured deadlines, but still stubs the production approval authority.

That is legitimate for a diagnostic and fatal for production. The separation was
real at every commit so far, and it was held by nothing but habit: an activation
review checked by hand, found it clean, and pointed out that a single
`from ghostcursor.devtools import ...` would make the bypass reachable from the
product with no test objecting.

So the separation is now a property of the repository rather than of whoever
edits it next. D031: "no production module happens to import a devtool today"
correlates with the boundary holding. What the checks below actually enforce is
"no production module NAMES the devtools package", which implies it for every
import mechanism, because every mechanism needs the name. The first version
enforced only the AST import forms and claimed the implication anyway -- a
deferred `importlib.import_module` call inside a function defeated it, and a
re-review said so (D138). A name assembled from fragments at runtime is the
stated residual gap; it cannot happen by accident, which is the failure this
guards.

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


def _dynamic_devtool_references(source: str):
    """Any string naming the devtools package, anywhere in the module.

    The AST forms above are defeated by
    `importlib.import_module("ghostcursor.devtools.act_acceptance")` inside a
    function, and by `__import__` with the same string.

    Rather than enumerate the dynamic-import APIs -- the treadmill this
    repository has ridden for eight rounds on a different scan -- this matches
    the NAME. A module that never names the package cannot import it by any
    mechanism, because every mechanism needs the name.
    """

    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _DEVTOOLS in node.value:
                found.append(f"line {node.lineno}: string naming {_DEVTOOLS!r}")
    return found


#: The production package as MEASURED at this commit, per directory. Not a
#: floor: a reviewer narrowed `_production_modules()` to top-level modules only
#: -- 32 of 85 -- and the `>= 30` floor passed while a planted devtool import in
#: `reasoning/loop.py` went unseen, whole lane green (D139).
#:
#: A floor comfortably below reality guards nothing; it only records that
#: somebody once counted. These numbers are the count, so shrinking the scanned
#: set fails here and names the directory that vanished. They change when the
#: package changes, deliberately and visibly in a diff.
_MEASURED_INVENTORY = {
    # D193 retired the per-app plugin system: 92 modules unreachable from the
    # product were removed, so these are the counts that remain.
    "ghostcursor": 16,
    "ghostcursor/evaluation": 3,  # safety, teach_replay
    "ghostcursor/harness": 12,
    "ghostcursor/overlay": 4,
    "ghostcursor/perception": 3,  # uia, appinfo
    "ghostcursor/providers": 10,
    "ghostcursor/reasoning": 2,  # staleness
    "ghostcursor/workspace": 36,
}


def test_the_production_module_set_matches_the_measured_inventory():
    """Non-vacuity, by measurement rather than by floor.

    Every subpackage is named with its count, so a scan narrowed to any subset
    of the tree fails and says which part it stopped looking at.
    """

    modules = _production_modules()

    counted = {}
    for name in modules:
        parent = str(Path(name).parent).replace(chr(92), "/")
        counted[parent] = counted.get(parent, 0) + 1

    assert counted == _MEASURED_INVENTORY, (
        "the scanned production set no longer matches the measured inventory. "
        f"missing/changed: {set(_MEASURED_INVENTORY.items()) ^ set(counted.items())}"
    )
    assert sum(_MEASURED_INVENTORY.values()) == len(modules) == 86

    for required in (
        "ghostcursor/agent_server.py",
        "ghostcursor/policy.py",
        # From subpackages, because the narrowing that survived kept every
        # top-level module and dropped every nested one.
        "ghostcursor/harness/act.py",
        "ghostcursor/harness/teach_live.py",
        "ghostcursor/workspace/app.py",
        "ghostcursor/reasoning/staleness.py",
    ):
        assert required in modules, required
    assert not any(m.startswith("ghostcursor/devtools/") for m in modules)


def test_no_production_module_imports_a_devtool():
    """The property: the bypass paths cannot be reached from the product."""

    offenders = []
    for name in _production_modules():
        source = (ROOT / name).read_text(encoding="utf-8")
        for hit in _devtool_imports(source) + _dynamic_devtool_references(source):
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


def test_the_scan_catches_a_dynamic_import():
    """The AST forms alone enforce a correlation, not the boundary: a deferred
    `importlib` call inside a function reaches the same module and creates no
    import node at all (D138)."""

    deferred = "def go():\n    importlib.import_module('ghostcursor.devtools.act_cli')"

    assert _dynamic_devtool_references(deferred)
    assert _dynamic_devtool_references('__import__("ghostcursor.devtools")')
    assert _dynamic_devtool_references('MODULE = "ghostcursor.devtools.act_campaign"')
    # And it says nothing about modules that never name the package.
    assert not _dynamic_devtool_references("import ghostcursor.act_runtime")
    assert not _dynamic_devtool_references('X = "ghostcursor.manager"')
