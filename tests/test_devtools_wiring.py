"""Names the devtools use must exist before a live desktop run finds out.

A dropped import in `act_acceptance` is invisible until the moment the
diagnostics branch executes -- which is after PowerPoint has been opened, a
plugin installed, an approval minted, and the desktop handed over. That is an
expensive place to learn about a NameError, and it happened.
"""

from __future__ import annotations

import ast
import builtins
import importlib
from pathlib import Path

import pytest


#: Bound by the import machinery, never by the source itself.
_MODULE_DUNDERS = {"__file__", "__name__", "__doc__", "__spec__", "__package__"}

MODULES = [
    "ghostcursor.devtools.act_acceptance",
    "ghostcursor.devtools.act_probe",
    "ghostcursor.devtools.act_diagnosis",
    "ghostcursor.devtools.uia_feasibility",
]


def _bound_names(tree: ast.AST) -> set[str]:
    """Everything a module binds at its own top level."""

    bound: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            bound.add(node.target.id)
        elif isinstance(node, ast.If):
            for inner in node.body:
                if isinstance(inner, (ast.Import, ast.ImportFrom)):
                    for alias in inner.names:
                        bound.add(alias.asname or alias.name.split(".")[0])
    return bound


def _local_names(function: ast.AST) -> set[str]:
    """Names bound anywhere inside a function, including nested scopes."""

    local: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            local.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                local.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local.add(node.name)
        elif isinstance(node, ast.arg):
            local.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            local.add(node.name)
        elif isinstance(node, (ast.comprehension,)):
            for name in ast.walk(node.target):
                if isinstance(name, ast.Name):
                    local.add(name.id)
    return local


@pytest.mark.parametrize("module_name", MODULES)
def test_every_name_a_devtool_loads_is_actually_bound(module_name):
    module = importlib.import_module(module_name)
    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    available = _bound_names(tree) | set(dir(builtins)) | _MODULE_DUNDERS

    unbound: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        scope = available | _local_names(node)
        for inner in ast.walk(node):
            if isinstance(inner, ast.Name) and isinstance(inner.ctx, ast.Load):
                if inner.id not in scope:
                    unbound.add(inner.id)

    assert not unbound, f"{module_name} loads unbound name(s): {sorted(unbound)}"


def test_the_scan_catches_a_dropped_import():
    """Non-vacuity: this is the exact shape of the bug it exists to prevent."""

    tree = ast.parse("def run():\n    return ActBoundaryProbe(1, 2)\n")
    available = _bound_names(tree) | set(dir(builtins))
    scope = available | _local_names(tree.body[0])

    assert "ActBoundaryProbe" not in scope


def test_the_acceptance_harness_still_imports_the_probe_it_wires():
    module = importlib.import_module("ghostcursor.devtools.act_acceptance")
    from ghostcursor.devtools.act_probe import ActBoundaryProbe

    assert module.ActBoundaryProbe is ActBoundaryProbe


def test_the_harness_passes_the_observer_under_the_name_core_expects():
    """A renamed keyword would be a TypeError only once the run started."""

    import inspect

    from ghostcursor.act_runtime import execute_approved_graph

    module = importlib.import_module("ghostcursor.devtools.act_acceptance")
    source = Path(module.__file__).read_text(encoding="utf-8")

    assert "verify_observer=verify_observer," in source
    assert "verify_observer" in inspect.signature(execute_approved_graph).parameters
