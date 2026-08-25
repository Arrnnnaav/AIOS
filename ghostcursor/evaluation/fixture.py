"""Frozen Synthetic Export observation and live parity checks."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ghostcursor.demo.synthetic_export_app import EXPORT_ID, STATUS_ID, WRONG_ID
from ghostcursor.perception.uia import Element


FIXTURE_PATH = Path(__file__).resolve().parent / "data" / "synthetic_export_uia_v1.json"


@dataclass(frozen=True)
class Fixture:
    version: str
    provenance: dict[str, str]
    title: str
    elements: tuple[Element, ...]


def load_fixture(path: Path = FIXTURE_PATH) -> Fixture:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if set(raw) != {"fixture_version", "provenance", "window", "elements"}:
        raise ValueError("fixture top-level fields are invalid")
    if set(raw["window"]) != {"title", "captured_bbox"}:
        raise ValueError("fixture window fields are invalid")
    _validate_bbox(raw["window"]["captured_bbox"])
    expected_ids = {str(EXPORT_ID), str(WRONG_ID), str(STATUS_ID)}
    elements = []
    for item in raw["elements"]:
        if set(item) != {
            "name",
            "control_type",
            "automation_id",
            "source",
            "captured_bbox",
        }:
            raise ValueError("fixture element fields are invalid")
        bbox = _validate_bbox(item["captured_bbox"])
        elements.append(
            Element(
                name=item["name"],
                control_type=item["control_type"],
                automation_id=item["automation_id"],
                bbox=bbox,
                source=item["source"],
            )
        )
    if {element.automation_id for element in elements} != expected_ids:
        raise ValueError("fixture IDs drifted from Synthetic Export constants")
    return Fixture(
        version=raw["fixture_version"],
        provenance=raw["provenance"],
        title=raw["window"]["title"],
        elements=tuple(elements),
    )


def assert_live_parity(
    fixture: Fixture,
    live_elements: list[Element],
    window_bbox: tuple[int, int, int, int],
) -> dict[str, object]:
    """Compare identity exactly and geometry structurally, never pixel-for-pixel."""
    required_ids = {element.automation_id for element in fixture.elements}
    live_by_id = {
        element.automation_id: element
        for element in live_elements
        if element.automation_id in required_ids
    }
    if set(live_by_id) != required_ids:
        raise AssertionError(
            f"live fixture IDs differ: expected {sorted(required_ids)}, "
            f"got {sorted(live_by_id)}"
        )
    exact_fields = ("name", "control_type", "automation_id", "source")
    for expected in fixture.elements:
        actual = live_by_id[expected.automation_id]
        for field in exact_fields:
            if getattr(actual, field) != getattr(expected, field):
                raise AssertionError(
                    f"{expected.automation_id} {field} drifted: "
                    f"{getattr(actual, field)!r} != {getattr(expected, field)!r}"
                )
        _validate_bbox(actual.bbox)
        if not _intersects(actual.bbox, window_bbox):
            raise AssertionError(f"{expected.automation_id} is outside the target window")
    return {
        "identity_fields": list(exact_fields),
        "geometry_rule": "positive bbox intersecting target window",
        "ignored_volatile_fields": [
            "enumeration order",
            "focus",
            "HWND",
            "timestamp",
            "absolute position",
        ],
        "matched_ids": sorted(required_ids),
    }


def _validate_bbox(value: object) -> tuple[int, int, int, int]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 4
        or any(not isinstance(part, int) or isinstance(part, bool) for part in value)
    ):
        raise ValueError("bbox must contain four integers")
    left, top, right, bottom = value
    if right <= left or bottom <= top:
        raise ValueError("bbox must have positive dimensions")
    return left, top, right, bottom


def _intersects(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int]
) -> bool:
    left, top, right, bottom = first
    window_left, window_top, window_right, window_bottom = second
    return (
        right > window_left
        and left < window_right
        and bottom > window_top
        and top < window_bottom
    )
