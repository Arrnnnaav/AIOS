"""VS Code workspace-title verification for the first real-app recipe."""
from __future__ import annotations

import re

from ghostcursor.reasoning.verification import Snapshot


_VS_CODE_SUFFIX = re.compile(r"(?:visual studio code|\s-\s*code)$", re.IGNORECASE)


def normalize_title_text(value: str) -> str:
    """Casefold and collapse whitespace without removing punctuation."""
    return " ".join(value.casefold().strip().split())


def folder_reference_from_goal(goal: str) -> str:
    """Extract a folder reference from an open-folder goal.

    A full path is reduced to its final segment before normalization, so a
    title containing only the workspace name can still be verified.
    """
    text = goal.strip()
    text = re.sub(r"^open\b", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(
        r"^(?:a\s+)?folder\s+in\s+(?:vs\s*code|visual\s+studio\s+code)\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    text = re.sub(
        r"\s+in\s+(?:vs\s*code|visual\s+studio\s+code)\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    if "\\" in text or "/" in text:
        segments = [segment for segment in re.split(r"[\\/]+", text) if segment]
        text = segments[-1] if segments else ""
    return normalize_title_text(text)


def is_valid_vscode_workspace_title(title: str) -> bool:
    return bool(_VS_CODE_SUFFIX.search(normalize_title_text(title)))


def verify_open_folder(before: Snapshot, after: Snapshot, goal: str) -> bool:
    """Verify a user-driven folder selection from VS Code's title state."""
    before_title = normalize_title_text(before.title)
    after_title = normalize_title_text(after.title)
    if before_title == after_title or not is_valid_vscode_workspace_title(after.title):
        return False

    folder = folder_reference_from_goal(goal)
    # Empty or one-character references are deliberately non-specific. A
    # value such as '.' appears in ordinary titles and must not self-satisfy.
    if len(folder) < 2:
        return True
    return folder in after_title
