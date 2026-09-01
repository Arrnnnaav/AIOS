"""Phase A boundary probe: it must measure the run without being able to change it."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from ghostcursor.devtools import act_probe
from ghostcursor.devtools.act_probe import (
    ActBoundaryProbe,
    diff_parts,
    observe_package,
)


def _package(path: Path, parts: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in parts.items():
            archive.writestr(name, payload)


def _node(node_id: str = "n001", operation_id: str = "powerpoint.set_transition"):
    return SimpleNamespace(node_id=node_id, operation_id=operation_id)


def _started(node_id: str = "n001"):
    return SimpleNamespace(type="action_started", node_id=node_id)


def test_missing_package_is_reported_as_absent_not_as_an_error(tmp_path):
    state = observe_package(tmp_path / "nothing.pptx")

    assert state.exists is False
    assert state.sha256 is None
    assert state.fault is None


def test_a_readable_package_reports_its_digest_size_and_every_part(tmp_path):
    output = tmp_path / "deck.pptx"
    _package(
        output, {"ppt/slides/slide1.xml": b"<sld/>", "[Content_Types].xml": b"<T/>"}
    )

    state = observe_package(output)

    assert state.exists is True
    assert state.readable_zip is True
    assert state.reads_agreed is True
    assert state.size == output.stat().st_size
    assert state.sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
    assert set(state.parts) == {"ppt/slides/slide1.xml", "[Content_Types].xml"}
    assert (
        state.parts["ppt/slides/slide1.xml"].sha256
        == hashlib.sha256(b"<sld/>").hexdigest()
    )


def test_an_unreadable_package_still_reports_bytes_because_that_is_the_finding(
    tmp_path,
):
    """A half-written save is not an error to swallow -- it is what we came for."""

    output = tmp_path / "deck.pptx"
    output.write_bytes(b"PK\x03\x04 truncated")

    state = observe_package(output)

    assert state.exists is True
    assert state.readable_zip is False
    assert state.sha256 is not None
    assert state.parts == {}


def test_a_package_whose_bytes_move_between_reads_is_reported_as_disagreeing(
    tmp_path, monkeypatch
):
    """``reads_agreed`` must come from two independent reads.

    Comparing one read with itself is always True, which would report a file
    whose bytes were moving as settled -- the exact state this field exists
    to catch. Agreement is still not proof that a write completed.
    """

    output = tmp_path / "deck.pptx"
    _package(output, {"a.xml": b"<a/>"})
    answers = iter([("aa" * 32, 10), ("bb" * 32, 11)])
    monkeypatch.setattr(act_probe, "_digest", lambda _path: next(answers))

    assert observe_package(output).reads_agreed is False


def test_part_diff_names_what_changed_between_two_observations(tmp_path):
    before_path = tmp_path / "before.pptx"
    after_path = tmp_path / "after.pptx"
    _package(
        before_path,
        {"ppt/slides/slide1.xml": b"<sld/>", "ppt/gone.xml": b"<g/>"},
    )
    _package(
        after_path,
        {"ppt/slides/slide1.xml": b"<sld transition=/>", "ppt/new.xml": b"<n/>"},
    )

    diff = diff_parts(observe_package(before_path), observe_package(after_path))

    assert diff.modified == ("ppt/slides/slide1.xml",)
    assert diff.added == ("ppt/new.xml",)
    assert diff.removed == ("ppt/gone.xml",)
    assert diff.empty is False


def _observe(
    probe,
    node_id="n001",
    operation_id="powerpoint.set_transition",
    verified=True,
    error=None,
    seconds=1.0,
):
    """Drive the probe the way execute_approved_graph drives it."""

    observer = probe.verify_observer()
    observer("verify_started", {"node_id": node_id})
    observer(
        "verify_finished",
        {
            "error": error,
            "node_id": node_id,
            "operation_id": operation_id,
            "seconds": seconds,
            "verified": verified,
        },
    )


@pytest.mark.parametrize("answer", [True, False])
def test_the_probe_records_the_answer_core_reported(tmp_path, answer):
    output = tmp_path / "deck.pptx"
    _package(output, {"a.xml": b"<a/>"})
    records: list[dict] = []
    probe = ActBoundaryProbe(output, records.append)

    _observe(probe, verified=answer)

    assert records[0]["verified"] is answer


def test_the_probe_has_no_way_to_wrap_or_replace_the_verifier(tmp_path):
    """An earlier design handed the verifier callable to the probe and asked
    it to return the same answer. Nothing enforced that, so the seam could
    return True in place of a verification. The capability is gone, not merely
    discouraged."""

    probe = ActBoundaryProbe(tmp_path / "deck.pptx", lambda _r: None)

    assert not hasattr(probe, "wrap_verify")
    assert probe.verify_observer()("verify_started", {"node_id": "n001"}) is None


def test_a_failing_verification_is_recorded_with_its_error(tmp_path):
    output = tmp_path / "deck.pptx"
    _package(output, {"a.xml": b"<a/>"})
    records: list[dict] = []
    probe = ActBoundaryProbe(output, records.append)

    _observe(probe, verified=None, error="RuntimeError: could not open package")

    assert records[0]["verified"] is None
    assert "could not open" in records[0]["verifier_error"]


def test_the_record_names_the_part_the_adapter_wrote_for_this_node(tmp_path):
    """The whole point: which XML part moved between the node starting and
    the verifier reading it."""

    output = tmp_path / "deck.pptx"
    _package(output, {"ppt/slides/slide1.xml": b"<sld/>", "static.xml": b"<s/>"})
    records: list[dict] = []
    probe = ActBoundaryProbe(output, records.append)

    probe.event_sink()(_started("n025"))
    _package(
        output,
        {"ppt/slides/slide1.xml": b"<sld transition=/>", "static.xml": b"<s/>"},
    )
    _observe(probe, node_id="n025")

    record = records[0]
    assert record["node_id"] == "n025"
    assert record["adapter_wrote_parts"] == ["ppt/slides/slide1.xml"]
    assert record["before_node"]["sha256"] != record["after_adapter"]["sha256"]
    assert record["package_changed_during_verification"] is False


def test_a_package_written_during_verification_is_reported_without_naming_a_writer(
    tmp_path,
):
    """Non-vacuity guard: the field must be capable of being True.

    It says the package changed during the verification window. It does not
    say the verifier changed it -- an external writer is indistinguishable
    from here, and proving authorship needs the verifier to report the digest
    it actually opened.
    """

    output = tmp_path / "deck.pptx"
    _package(output, {"a.xml": b"<a/>"})
    records: list[dict] = []
    probe = ActBoundaryProbe(output, records.append)

    observer = probe.verify_observer()
    observer("verify_started", {"node_id": "n001"})
    _package(output, {"a.xml": b"<a modified=/>"})
    observer(
        "verify_finished",
        {
            "error": None,
            "node_id": "n001",
            "operation_id": "x",
            "seconds": 1.0,
            "verified": True,
        },
    )

    assert records[0]["package_changed_during_verification"] is True


def test_the_probe_cannot_swallow_a_runs_own_events(tmp_path):
    output = tmp_path / "deck.pptx"
    _package(output, {"a.xml": b"<a/>"})
    seen: list[str] = []
    probe = ActBoundaryProbe(output, lambda _record: None)

    sink = probe.event_sink(lambda event: seen.append(event.type))
    sink(_started())
    sink(SimpleNamespace(type="action_completed", node_id="n001"))

    assert seen == ["action_started", "action_completed"]


def test_a_probe_fault_is_reported_and_the_event_still_reaches_the_run(tmp_path):
    output = tmp_path / "deck.pptx"
    _package(output, {"a.xml": b"<a/>"})
    records: list[dict] = []
    seen: list[str] = []
    probe = ActBoundaryProbe(output, records.append)
    probe._observe = lambda: (_ for _ in ()).throw(OSError("volume disappeared"))

    probe.event_sink(lambda event: seen.append(event.type))(_started())

    assert seen == ["action_started"]
    assert probe.probe_faults == 1
    assert records[0]["type"] == "probe_fault"


def test_every_record_is_json_serialisable_because_it_is_written_as_jsonl(tmp_path):
    output = tmp_path / "deck.pptx"
    _package(output, {"a.xml": b"<a/>"})
    records: list[dict] = []
    probe = ActBoundaryProbe(output, records.append)

    probe.event_sink()(_started())
    _observe(probe)

    for record in records:
        json.loads(json.dumps(record, sort_keys=True))
