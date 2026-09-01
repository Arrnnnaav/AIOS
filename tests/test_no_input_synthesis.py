"""D006: production GhostCursor observes and guides; it never operates apps.

The hard safety boundary. The overlay shows the user where to act and must
never act for them, so the scan below is not a style check -- it is the thing
standing between a guide and an autonomous agent.

Two scans, because a call check alone is not enough. `pyautogui.click` never
appears as the name `click` if the module is aliased or the function rebound,
and a module imported for its side effects can synthesize input without any
call this file would recognise. Refusing the IMPORT closes what refusing the
call cannot: code that cannot reach the library cannot drive the mouse whatever
it names the variable.

Scope is every package under `ghostcursor/`, `devtools` included. A developer
instrument runs on a real desktop against a real application, which is exactly
where synthesizing one click would be least visible and most harmful.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "ghostcursor"

_BANNED_CALLS = {
    "SendInput",
    "SetCursorPos",
    "click_input",
    "keybd_event",
    "mouse_event",
    "send_keys",
    "type_keys",
}

#: Libraries whose entire purpose is synthesizing input. Importing one is the
#: violation; no call has to be found. `pywinauto` is deliberately NOT here --
#: tier 1 perception depends on it, and it is input-capable, which is why the
#: call list bans its input methods by name instead.
_BANNED_IMPORTS = {
    "pyautogui",
    "pydirectinput",
    "pynput",
    "keyboard",
    "mouse",
    "autoit",
    "win32com.client.Dispatch",
}


def _python_files() -> list[Path]:
    return sorted(ROOT.rglob("*.py"))


def _trees():
    for path in _python_files():
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def banned_calls_in(tree: ast.AST) -> list[str]:
    """Every banned call name in one parsed module, with line numbers.

    Extracted so the self-check below runs THIS function over known-violating
    source rather than a copy of its logic. A self-check that reimplements the
    scan proves the copy works and says nothing about the scanner -- and since
    no file in the tree currently imports a banned library, a broken scanner
    and a clean codebase produce identical output.
    """
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        name = (
            function.attr
            if isinstance(function, ast.Attribute)
            else function.id
            if isinstance(function, ast.Name)
            else ""
        )
        if name in _BANNED_CALLS:
            found.append(f"{node.lineno}:{name}")
    return found


def banned_imports_in(tree: ast.AST, banned: set[str] | None = None) -> list[str]:
    """Every banned import in one parsed module, with line numbers.

    `banned` defaults to the core list. A signed adapter needs a different
    one -- `win32com` is its sanctioned object-model path, not a violation --
    so the scan takes the set rather than each root growing its own copy of
    this walker.
    """
    banned = _BANNED_IMPORTS if banned is None else banned
    found = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module] + [
                f"{node.module}.{alias.name}" for alias in node.names
            ]
        for name in names:
            if name in banned or name.split(".")[0] in banned:
                found.append(f"{node.lineno}:{name}")
    return found


def test_production_code_contains_no_input_synthesis_calls():
    violations = [
        f"{path.relative_to(ROOT)}:{hit}"
        for path, tree in _trees()
        for hit in banned_calls_in(tree)
    ]
    assert violations == [], "production input synthesis is forbidden: " + ", ".join(
        violations
    )


def test_production_code_imports_no_input_synthesis_library():
    """Refusing the import closes what refusing the call cannot.

    An aliased module or a rebound function defeats a name-based call scan
    entirely: `import pyautogui as p; p.click()` matches no banned call name.
    Code that never imports the library cannot do that under any name.
    """
    violations = [
        f"{path.relative_to(ROOT)}:{hit}"
        for path, tree in _trees()
        for hit in banned_imports_in(tree)
    ]
    assert violations == [], "importing an input-synthesis library is forbidden: " + (
        ", ".join(violations)
    )


def test_the_scan_actually_covers_the_devtools_package():
    """The scope claim, asserted rather than assumed.

    `rglob` covers `devtools` today because the package sits under
    `ghostcursor/`. That is a fact about the current layout, not a guarantee --
    moving developer instruments out of the package would drop them from this
    scan silently, and nothing else would notice. This fails if that happens.
    """
    scanned = {path.relative_to(ROOT).as_posix() for path in _python_files()}
    assert "devtools/candidate_acceptance.py" in scanned
    assert any(name.startswith("devtools/") for name in scanned)
    assert any(name.startswith("packs/") for name in scanned)
    assert any(name.startswith("perception/") for name in scanned)


@pytest.mark.parametrize(
    "source,scan",
    [
        ('import pyautogui\npyautogui.click()\n', 'import'),
        ('import pyautogui as p\np.click()\n', 'import'),
        ('from pynput import mouse\n', 'import'),
        ('from pynput.mouse import Controller\n', 'import'),
        ('import mouse.wheel\n', 'import'),
        ('from ghostcursor.x import y\ny.send_keys(1)\n', 'call'),
        ('ctrl.click_input()\n', 'call'),
        ('SetCursorPos(10, 10)\n', 'call'),
    ],
)
def test_the_scans_detect_what_they_claim_to(source, scan):
    """Mutation-verify the scanners themselves (D018).

    Nothing under `ghostcursor/` imports a banned library, so both scans find
    nothing on a healthy tree -- which is exactly what a disabled scan finds.
    These synthetic violations are the only thing separating the two states,
    and they run the real functions, not a copy.
    """
    tree = ast.parse(source, filename="sample.py")
    detector = banned_imports_in if scan == "import" else banned_calls_in
    assert detector(tree), f"the {scan} scan missed a known violation"


def test_a_clean_module_trips_neither_scan():
    """The other half: the scans must not flag ordinary code.

    Without this, "always report a violation" would pass every test above.
    """
    tree = ast.parse('import json\nfrom pathlib import Path\nPath(x).read_text()\n', filename="clean.py")
    assert banned_calls_in(tree) == []
    assert banned_imports_in(tree) == []


# ---------------------------------------------------------------------------
# Signed plugin adapters (D100)
# ---------------------------------------------------------------------------
#
# The scans above are scoped to `ghostcursor/`. A signed adapter deliberately
# lives OUTSIDE it -- out of process is the point -- so those scans have never
# looked at the one component that can actually change a user's document.
#
# CLAUDE.md states the rule: an adapter "may call only the application object
# model declared by its signed operation registry; it may not call SendInput,
# cursor APIs, or generic mouse/keyboard automation." Until this file existed
# that rule held because the first adapter was written carefully, not because
# anything would notice if the next one was not. The first adapter is the
# template every later one gets copied from.

ADAPTER_ROOTS = sorted(
    (Path(__file__).resolve().parents[1] / "plugins" / "sources").glob("*/payload")
)

#: The core list minus `win32com.client.Dispatch`. Core may not drive an Office
#: object model; an adapter exists to do exactly that. Everything whose sole
#: purpose is synthesizing input stays banned.
_ADAPTER_BANNED_IMPORTS = _BANNED_IMPORTS - {"win32com.client.Dispatch"}


def _adapter_trees():
    for root in ADAPTER_ROOTS:
        for path in sorted(root.rglob("*.py")):
            yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_signed_adapters_synthesize_no_input():
    """An adapter drives the object model, never the mouse or keyboard."""
    violations = [
        f"{path}:{hit}"
        for path, tree in _adapter_trees()
        for hit in banned_calls_in(tree)
    ]
    assert violations == [], "adapter input synthesis is forbidden: " + ", ".join(
        violations
    )


def test_signed_adapters_import_no_input_synthesis_library():
    """Refusing the import closes what refusing the call cannot, here too."""
    violations = [
        f"{path}:{hit}"
        for path, tree in _adapter_trees()
        for hit in banned_imports_in(tree, _ADAPTER_BANNED_IMPORTS)
    ]
    assert violations == [], "adapter imported an input library: " + ", ".join(
        violations
    )


def test_the_adapter_scan_actually_reaches_a_shipped_adapter():
    """Non-vacuity. A glob that matches nothing passes both scans forever.

    This is the failure this repo has caught repeatedly: a guard that cannot
    fire reads exactly like a guard that never had to.
    """
    scanned = [path for path, _tree in _adapter_trees()]
    assert scanned, f"the adapter scan found no files under {ADAPTER_ROOTS}"
    assert any(
        "adapter" in path.name for path in scanned
    ), f"no adapter module among {[p.name for p in scanned]}"


def test_the_adapter_scan_still_permits_the_sanctioned_object_model():
    """`win32com` is the adapter's whole purpose, so it must NOT be a hit.

    Without this, tightening the adapter list to the core one would look like
    a safety improvement while actually banning the only sanctioned mechanism.
    """
    # `Dispatch` is the symbol the core list names, so that import form is what
    # separates the two roots. Worth knowing: plain `import win32com.client` is
    # banned in neither, so the core rule is narrower than "core cannot reach
    # an Office object model".
    dispatch = ast.parse("from win32com.client import Dispatch\n")
    assert banned_imports_in(dispatch, _ADAPTER_BANNED_IMPORTS) == []
    assert banned_imports_in(dispatch) != [], "core must still refuse Dispatch"

    # The form the shipped adapter actually uses stays clean under its own list.
    used = ast.parse(
        "import win32com.client\n"
        "app = win32com.client.gencache.EnsureDispatch('PowerPoint.Application')\n"
    )
    assert banned_imports_in(used, _ADAPTER_BANNED_IMPORTS) == []
