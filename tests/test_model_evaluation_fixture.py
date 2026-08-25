from dataclasses import replace

import pytest

from ghostcursor.demo.synthetic_export_app import EXPORT_ID, STATUS_ID, WRONG_ID
from ghostcursor.evaluation.fixture import assert_live_parity, load_fixture


def test_fixture_ids_are_imported_demo_constants():
    fixture = load_fixture()

    assert {element.automation_id for element in fixture.elements} == {
        str(EXPORT_ID),
        str(WRONG_ID),
        str(STATUS_ID),
    }
    assert fixture.provenance["source_commit"]
    assert fixture.provenance["captured_at"] == "2026-08-25"


def test_parity_matches_identity_exactly_but_allows_shifted_geometry():
    fixture = load_fixture()
    shifted = [
        replace(
            element,
            bbox=tuple(coordinate + 100 for coordinate in element.bbox),
        )
        for element in fixture.elements
    ]

    result = assert_live_parity(fixture, shifted, (400, 300, 1200, 900))

    assert result["matched_ids"] == [str(EXPORT_ID), str(WRONG_ID), str(STATUS_ID)]
    assert "absolute position" in result["ignored_volatile_fields"]


def test_parity_rejects_identity_drift():
    fixture = load_fixture()
    live = list(fixture.elements)
    live[0] = replace(live[0], name="Export now")

    with pytest.raises(AssertionError, match="name drifted"):
        assert_live_parity(fixture, live, (0, 0, 2000, 2000))
