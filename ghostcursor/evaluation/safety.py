"""Static no-action checks for project-controlled evaluation code."""
from __future__ import annotations

import ast
from pathlib import Path


ALLOWED_GHOSTCURSOR_IMPORTS = (
    "ghostcursor.demo.synthetic_export_app",
    "ghostcursor.evaluation",
    "ghostcursor.inference.ollama",
    "ghostcursor.inference.screen_hint",
    "ghostcursor.perception.uia",
    "ghostcursor.reasoning.planner",
)
FORBIDDEN_IMPORT_PREFIXES = (
    "ghostcursor.run",
    "ghostcursor.reasoning.loop",
)
FORBIDDEN_CALLS = {
    "SendInput",
    "SetCursorPos",
    "click_input",
    "keybd_event",
    "mouse_event",
    "send_keys",
    "run_tour",
}


def evaluation_safety_violations(root: Path | None = None) -> list[str]:
    """Scan only project-controlled evaluation modules, never dependencies."""
    package = root or Path(__file__).resolve().parent
    violations: list[str] = []
    for path in package.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    _check_import(alias.name, path, node.lineno, violations)
            elif isinstance(node, ast.ImportFrom):
                _check_import(node.module or "", path, node.lineno, violations)
            elif isinstance(node, ast.Call):
                function = node.func
                name = (
                    function.attr
                    if isinstance(function, ast.Attribute)
                    else function.id
                    if isinstance(function, ast.Name)
                    else ""
                )
                if name in FORBIDDEN_CALLS:
                    violations.append(f"{path.name}:{node.lineno}:call:{name}")
    return sorted(violations)


def assert_evaluation_is_read_only(root: Path | None = None) -> dict[str, object]:
    violations = evaluation_safety_violations(root)
    if violations:
        raise AssertionError("evaluation no-action boundary failed: " + ", ".join(violations))
    return {
        "project_import_allowlist": list(ALLOWED_GHOSTCURSOR_IMPORTS),
        "forbidden_calls": sorted(FORBIDDEN_CALLS),
        "third_party_recursive_scan": False,
        "violations": [],
    }


def _check_import(
    module: str, path: Path, line: int, violations: list[str]
) -> None:
    if not module.startswith("ghostcursor"):
        return
    if module.startswith(FORBIDDEN_IMPORT_PREFIXES):
        violations.append(f"{path.name}:{line}:forbidden-import:{module}")
        return
    if not any(
        module == allowed or module.startswith(allowed + ".")
        for allowed in ALLOWED_GHOSTCURSOR_IMPORTS
    ):
        violations.append(f"{path.name}:{line}:unapproved-import:{module}")
