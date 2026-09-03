"""The approved path holds a complete deck or nothing.

Every case here is a way a partial artifact could reach the final path, or a
way an incomplete staging file could stop being labelled as one. The defect
this exists to fix was measured, not imagined: stopped deck builds left
36-53KB `.pptx` files at their approved paths.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghostcursor.act_staging import (
    STAGING_DIRNAME,
    Staging,
    StagingError,
    abandon,
    incomplete_files,
    open_staging,
    publish,
)


@pytest.fixture
def owned(tmp_path):
    root = tmp_path / "owned"
    root.mkdir()
    return root


def _area(owned, name="deck.pptx", run_id="run01"):
    return open_staging(owned / name, owned_root=owned, run_id=run_id)


def _write(area, data=b"a complete deck" * 100):
    area.staging.write_bytes(data)
    return data


# --- the final path does not exist until it is complete -------------------


def test_claiming_a_staging_area_creates_no_final_file(owned):
    area = _area(owned)

    assert area.final.exists() is False
    assert area.staging.parent.name == STAGING_DIRNAME


def test_the_final_path_appears_only_at_publish(owned):
    area = _area(owned)
    _write(area)

    assert area.final.exists() is False
    publish(area)
    assert area.final.is_file()


def test_the_published_bytes_are_the_staged_bytes(owned):
    area = _area(owned)
    data = _write(area)

    digest = publish(area)

    assert area.final.read_bytes() == data
    assert len(digest) == 64


def test_a_run_that_never_publishes_leaves_no_final_file(owned):
    """The measured defect, inverted. A stopped build must not leave a
    partial deck where a finished one belongs."""

    area = _area(owned)
    _write(area, b"only the first forty nodes")

    abandon(area)

    assert area.final.exists() is False
    assert area.staging.is_file()  # the work is kept, just not published


def test_publishing_over_an_existing_final_path_is_refused(owned):
    area = _area(owned)
    _write(area)
    area.final.write_bytes(b"something already here")

    with pytest.raises(StagingError, match="already exists"):
        publish(area)

    assert area.final.read_bytes() == b"something already here"


def test_claiming_a_staging_area_for_an_existing_final_is_refused(owned):
    (owned / "deck.pptx").write_bytes(b"already here")

    with pytest.raises(StagingError, match="already exists"):
        _area(owned)


def test_publishing_with_nothing_staged_is_refused(owned):
    area = _area(owned)

    with pytest.raises(StagingError, match="nothing was staged"):
        publish(area)

    assert area.final.exists() is False


# --- the published bytes are the verified bytes ---------------------------


def test_a_file_that_changes_during_publish_is_not_published(owned, monkeypatch):
    """PowerPoint autosaves. If something writes between the last
    verification and the publish, what lands would not be what verified."""

    area = _area(owned)
    _write(area, b"verified content")

    from ghostcursor import act_staging

    real = act_staging._digest
    calls = {"n": 0}

    def shifting(path):
        calls["n"] += 1
        # The second digest is the re-read after the copy.
        if calls["n"] == 2:
            return "b" * 64
        return real(path)

    monkeypatch.setattr(act_staging, "_digest", shifting)

    with pytest.raises(StagingError, match="changed while it was being published"):
        publish(area)

    assert area.final.exists() is False


def test_a_copy_that_does_not_match_is_not_published(owned, monkeypatch):
    """Distinct from the case above: here the source held still and the COPY
    is wrong. Both must refuse, and for different reasons."""

    area = _area(owned)
    _write(area, b"verified content")

    from ghostcursor import act_staging

    real = act_staging._digest
    calls = {"n": 0}

    def bad_copy(path):
        calls["n"] += 1
        if calls["n"] == 3:  # the digest of the partial
            return "c" * 64
        return real(path)

    monkeypatch.setattr(act_staging, "_digest", bad_copy)

    with pytest.raises(StagingError, match="does not match what was staged"):
        publish(area)

    assert area.final.exists() is False


def test_no_partial_file_survives_a_refused_publish(owned, monkeypatch):
    """The failure has to happen AFTER the partial is written, or the test
    proves nothing: an earlier version blocked on the final path already
    existing, which refuses before any partial is created, so removing the
    cleanup changed nothing it could see."""

    from ghostcursor import act_staging

    area = _area(owned)
    _write(area, b"verified content")

    real = act_staging._digest
    calls = {"n": 0}

    def shifting(path):
        calls["n"] += 1
        return "b" * 64 if calls["n"] == 2 else real(path)

    monkeypatch.setattr(act_staging, "_digest", shifting)

    with pytest.raises(StagingError, match="changed while it was being published"):
        publish(area)

    leftovers = [p.name for p in owned.iterdir() if p.name.endswith(".partial")]
    assert leftovers == []
    assert area.final.exists() is False


# --- the marker labels what is unfinished ---------------------------------


def test_the_marker_is_written_when_the_area_is_claimed(owned):
    """At the START, not on failure. A crash runs no failure handler, so a
    marker written on failure is exactly absent in the case it exists for."""

    area = _area(owned)

    assert area.marker.is_file()
    assert area.complete is False


def test_the_marker_is_cleared_only_by_a_successful_publish(owned):
    area = _area(owned)
    _write(area)

    assert area.complete is False
    publish(area)
    assert area.complete is True


def test_a_refused_publish_leaves_the_marker_in_place(owned):
    area = _area(owned)
    _write(area)
    area.final.write_bytes(b"blocking")

    with pytest.raises(StagingError):
        publish(area)

    assert area.complete is False


def test_the_marker_says_what_the_file_is_and_is_not(owned):
    area = _area(owned)

    record = json.loads(area.marker.read_text(encoding="utf-8"))

    assert record["final_path"] == str(area.final)
    assert record["run_id"] == "run01"
    assert "INCOMPLETE" in record["note"]


def test_abandoning_keeps_the_label_by_default(owned):
    """A staging file whose marker was removed is an anonymous partial .pptx
    someone can mistake for a deck. That is the thing being prevented."""

    area = _area(owned)
    _write(area)

    abandon(area)

    assert area.staging.is_file()
    assert area.marker.is_file()


def test_abandoning_can_remove_both_when_asked(owned):
    area = _area(owned)
    _write(area)

    abandon(area, remove=True)

    assert area.staging.exists() is False
    assert area.marker.exists() is False


# --- finding what was left behind -----------------------------------------


def test_incomplete_files_reports_every_unfinished_staging_file(owned):
    first = _area(owned, "one.pptx", "runa")
    second = _area(owned, "two.pptx", "runb")
    _write(first)
    _write(second)
    publish(first)

    found = incomplete_files(owned)

    assert [area.final.name for area in found] == ["two.pptx"]
    assert found[0].staging == second.staging


def test_incomplete_files_is_empty_when_nothing_was_staged(owned):
    assert incomplete_files(owned) == ()


def test_an_unreadable_marker_is_still_reported(owned):
    """A marker nobody can parse still means something here is incomplete.
    Skipping it would make a corrupt record indistinguishable from a clean
    root."""

    area = _area(owned)
    area.marker.write_text("{ not json", encoding="utf-8")

    found = incomplete_files(owned)

    assert len(found) == 1
    assert found[0].marker == area.marker


def test_incomplete_files_reports_rather_than_deletes(owned):
    area = _area(owned)
    _write(area)

    incomplete_files(owned)

    assert area.staging.is_file()


# --- the staging area has to be somewhere a rename can be atomic ----------


def test_a_final_path_outside_the_owned_root_is_refused(owned, tmp_path):
    with pytest.raises(StagingError, match="not under the owned root"):
        open_staging(tmp_path / "elsewhere.pptx", owned_root=owned, run_id="run01")


def test_a_missing_owned_root_is_refused(tmp_path):
    with pytest.raises(StagingError, match="not a directory"):
        open_staging(
            tmp_path / "nope" / "deck.pptx",
            owned_root=tmp_path / "nope",
            run_id="run01",
        )


def test_a_cross_volume_staging_area_is_refused(owned, monkeypatch):
    """A staging area on another volume makes the final step a non-atomic
    copy, and the whole guarantee quietly becomes a wish."""

    from ghostcursor import act_staging

    monkeypatch.setattr(act_staging, "_same_volume", lambda left, right: False)

    with pytest.raises(StagingError, match="different volumes"):
        _area(owned)


@pytest.mark.parametrize("run_id", ["", "has space", "has-dash", "../..", "a/b"])
def test_a_malformed_run_id_is_refused(owned, run_id):
    """The run id becomes part of a filename."""

    with pytest.raises(StagingError, match="run id"):
        open_staging(owned / "deck.pptx", owned_root=owned, run_id=run_id)


def test_two_runs_cannot_claim_the_same_staging_file(owned):
    _area(owned, "deck.pptx", "runa")

    with pytest.raises(StagingError, match="already in use"):
        _area(owned, "deck.pptx", "runa")


def test_two_runs_for_the_same_deck_get_different_staging_files(owned):
    first = _area(owned, "deck.pptx", "runa")
    second = _area(owned, "deck.pptx", "runb")

    assert first.staging != second.staging


@pytest.mark.parametrize("call", [publish, abandon])
def test_something_that_is_not_a_staging_area_is_refused(call):
    with pytest.raises(StagingError):
        call(Path("nope"))


def test_a_staging_area_is_frozen(owned):
    area = _area(owned)

    with pytest.raises(Exception):
        area.final = Path("elsewhere")
    assert isinstance(area, Staging)
