"""Names the devtools use must exist before a live desktop run finds out.

A dropped import in `act_acceptance` is invisible until the moment the
diagnostics branch executes -- which is after PowerPoint has been opened, a
plugin installed, an approval minted, and the desktop handed over. That is an
expensive place to learn about a NameError, and it happened.

Scope analysis is CPython's own (`symtable`), not a hand-rolled AST walk. The
first version of this file walked each function with `ast.walk`, which
descends into nested functions, so a name bound only inside an inner function
counted as bound in the outer one -- a false negative for exactly the bug
class the file exists to catch.
"""

from __future__ import annotations

import builtins
import importlib
import symtable
from pathlib import Path

import pytest


MODULES = [
    "ghostcursor.devtools.teach_capture",
    "ghostcursor.devtools.jev_replay",
    "ghostcursor.devtools.sketch_demo",
]

#: Bound by the import machinery, never by the source itself.
_MODULE_DUNDERS = {"__file__", "__name__", "__doc__", "__spec__", "__package__"}


def _module_bindings(table: symtable.SymbolTable) -> set[str]:
    """Only names the module actually BINDS.

    `get_symbols()` also lists names the module merely references, so taking
    every symbol would make any module-level typo bind itself and the scan
    would pass on the very file it was reading.
    """

    return {
        symbol.get_name()
        for symbol in table.get_symbols()
        if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace()
    }


def _unbound_names(source: str, filename: str) -> set[str]:
    """Every name loaded as a global that nothing at module scope binds.

    `symtable` resolves closures properly: a name bound in an enclosing
    function is `free`, not `global`, so only genuine module-level lookups are
    checked here.
    """

    top = symtable.symtable(source, filename, "exec")
    available = _module_bindings(top) | set(dir(builtins)) | _MODULE_DUNDERS
    unbound: set[str] = set()

    def visit(table: symtable.SymbolTable) -> None:
        for symbol in table.get_symbols():
            if symbol.is_global() and symbol.get_name() not in available:
                unbound.add(symbol.get_name())
        for child in table.get_children():
            visit(child)

    visit(top)
    return unbound


@pytest.mark.parametrize("module_name", MODULES)
def test_every_name_a_devtool_loads_is_actually_bound(module_name):
    module = importlib.import_module(module_name)
    source = Path(module.__file__).read_text(encoding="utf-8")

    unbound = _unbound_names(source, module.__file__)

    assert not unbound, f"{module_name} loads unbound name(s): {sorted(unbound)}"


def test_the_scan_catches_a_dropped_import():
    """Non-vacuity: the exact shape of the bug this file exists to prevent."""

    source = "def run():\n    return ActBoundaryProbe(1, 2)\n"

    assert "ActBoundaryProbe" in _unbound_names(source, "<planted>")


def test_the_scan_catches_a_name_bound_only_in_a_nested_function():
    """The false negative the hand-rolled walk had.

    `helper` binds `probe`; `run` loads a `probe` that nothing bound. A walk
    that collects names from nested scopes sees the inner binding and passes.
    """

    source = (
        "def run():\n"
        "    def helper():\n"
        "        probe = 1\n"
        "        return probe\n"
        "    helper()\n"
        "    return probe\n"
    )

    assert "probe" in _unbound_names(source, "<planted>")


def test_a_genuine_closure_is_not_reported_as_unbound():
    """Non-over-firing: a name bound in an enclosing function is free, not
    global, and must not be flagged."""

    source = (
        "def outer():\n"
        "    probe = 1\n"
        "    def inner():\n"
        "        return probe\n"
        "    return inner()\n"
    )

    assert _unbound_names(source, "<planted>") == set()


def test_a_module_level_statement_is_scanned_too():
    """The hand-rolled version only looked inside module-level def/class
    bodies, so a bad name in a module-level statement was never checked."""

    source = "VALUE = MissingThing()\n"

    assert "MissingThing" in _unbound_names(source, "<planted>")


def test_a_lazily_imported_name_inside_a_function_is_accepted():
    """Several devtools import comtypes inside the function that needs it."""

    source = "def run():\n    import comtypes\n    return comtypes\n"

    assert _unbound_names(source, "<planted>") == set()


