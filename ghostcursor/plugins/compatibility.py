"""The single core/plugin compatibility policy.

Installation, activation, catalog loading, upgrade preflight, status display,
authorization, and live revalidation must all call ``check_core_compatibility``.
Keeping the policy here prevents those consumers from growing subtly different
interpretations of the same manifest range.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping


_SEMVER_RE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")


@dataclass(frozen=True)
class CompatibilityResult:
    compatible: bool
    core_version: str
    minimum: str
    maximum_exclusive: str
    reason: str


def _version(value: object, label: str) -> tuple[int, int, int]:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a semantic version string")
    match = _SEMVER_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"{label} must use canonical MAJOR.MINOR.PATCH")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def check_core_compatibility(
    manifest: Mapping[str, Any], core_version: str
) -> CompatibilityResult:
    """Return whether ``core_version`` lies in the manifest's half-open range."""

    current = _version(core_version, "core version")
    value = manifest.get("core_compatibility")
    if not isinstance(value, Mapping):
        raise ValueError("plugin.core_compatibility must be an object")
    if set(value) != {"minimum", "maximum_exclusive"}:
        raise ValueError(
            "plugin.core_compatibility requires exactly minimum and maximum_exclusive"
        )
    minimum_text = value["minimum"]
    maximum_text = value["maximum_exclusive"]
    minimum = _version(minimum_text, "minimum core version")
    maximum = _version(maximum_text, "maximum core version")
    if minimum >= maximum:
        raise ValueError("minimum core version must be lower than maximum_exclusive")
    compatible = minimum <= current < maximum
    if compatible:
        reason = f"core {core_version} is in [{minimum_text}, {maximum_text})"
    else:
        reason = f"core {core_version} is outside [{minimum_text}, {maximum_text})"
    return CompatibilityResult(
        compatible=compatible,
        core_version=core_version,
        minimum=minimum_text,
        maximum_exclusive=maximum_text,
        reason=reason,
    )
