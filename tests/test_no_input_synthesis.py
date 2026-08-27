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


def banned_imports_in(tree: ast.AST) -> list[str]:
    """Every banned import in one parsed module, with line numbers."""
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
            if name in _BANNED_IMPORTS or name.split(".")[0] in _BANNED_IMPORTS:
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
