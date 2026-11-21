"""Static no-action checks for project-controlled evaluation code."""

from __future__ import annotations

import ast
from pathlib import Path


ALLOWED_GHOSTCURSOR_IMPORTS = (
    "ghostcursor.demo.synthetic_export_app",
    "ghostcursor.evaluation",
    "ghostcursor.harness.binding",
    "ghostcursor.harness.frame",
    "ghostcursor.harness.teach",
    "ghostcursor.inference.ollama",
    "ghostcursor.inference.screen_hint",
    "ghostcursor.perception.uia",
    "ghostcursor.providers",
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
                if node.level:  # `from ..run import x` would slip the prefix check
                    violations.append(f"{path.name}:{node.lineno}:relative-import")
                _check_import(node.module or "", path, node.lineno, violations)
                for alias in node.names:  # `from x import SendInput as s`
                    if alias.name in FORBIDDEN_CALLS:
                        violations.append(f"{path.name}:{node.lineno}:call:{alias.name}")
            # Any reference, not only a direct call: `s = user32.SendInput`
            # then `s(...)` passed before; so did getattr(user32, "SendInput").
            elif isinstance(node, (ast.Name, ast.Attribute)):
                name = node.attr if isinstance(node, ast.Attribute) else node.id
                if name in FORBIDDEN_CALLS:
                    violations.append(f"{path.name}:{node.lineno}:call:{name}")
                elif name in ("import_module", "__import__"):  # imports the scan cannot see
                    violations.append(f"{path.name}:{node.lineno}:dynamic-import:{name}")
            elif isinstance(node, ast.Call):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and arg.value in FORBIDDEN_CALLS:
                        violations.append(f"{path.name}:{node.lineno}:call:{arg.value}")
    return sorted(violations)


def assert_evaluation_is_read_only(root: Path | None = None) -> dict[str, object]:
    violations = evaluation_safety_violations(root)
    if violations:
        raise AssertionError(
            "evaluation no-action boundary failed: " + ", ".join(violations)
        )
    return {
        "project_import_allowlist": list(ALLOWED_GHOSTCURSOR_IMPORTS),
        "forbidden_calls": sorted(FORBIDDEN_CALLS),
        "third_party_recursive_scan": False,
        "violations": [],
    }


def _check_import(module: str, path: Path, line: int, violations: list[str]) -> None:
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
