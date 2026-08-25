"""D006: production GhostCursor observes and guides; it never operates apps."""

import ast
from pathlib import Path


_BANNED_CALLS = {
    "SendInput",
    "SetCursorPos",
    "click_input",
    "keybd_event",
    "mouse_event",
    "send_keys",
}


def test_production_code_contains_no_input_synthesis_calls():
    root = Path(__file__).resolve().parents[1] / "ghostcursor"
    violations = []

    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
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
                violations.append(f"{path.relative_to(root)}:{node.lineno}:{name}")

    assert violations == [], "production input synthesis is forbidden: " + ", ".join(
        violations
    )
