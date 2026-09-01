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
    assert state.stable is True
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


def test_a_package_whose_bytes_move_between_reads_is_reported_unstable(
    tmp_path, monkeypatch
):
    """``stable`` must come from two independent reads.

    Comparing one read with itself is always True, which would report a file
    still being flushed as settled -- the exact state this field exists to
    catch.
    """

    output = tmp_path / "deck.pptx"
    _package(output, {"a.xml": b"<a/>"})
    answers = iter([("aa" * 32, 10), ("bb" * 32, 11)])
    monkeypatch.setattr(act_probe, "_digest", lambda _path: next(answers))

    assert observe_package(output).stable is False


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


@pytest.mark.parametrize("answer", [True, False])
def test_the_probe_returns_the_verifiers_own_answer_unchanged(tmp_path, answer):
    output = tmp_path / "deck.pptx"
    _package(output, {"a.xml": b"<a/>"})
    records: list[dict] = []
    probe = ActBoundaryProbe(output, records.append)

    wrapped = probe.wrap_verify(lambda *_args: answer)

    assert wrapped(_node(), None, None, None) is answer
    assert records[0]["verified"] is answer


def test_a_failing_verifier_still_raises_and_is_still_recorded(tmp_path):
    output = tmp_path / "deck.pptx"
    _package(output, {"a.xml": b"<a/>"})
    records: list[dict] = []
    probe = ActBoundaryProbe(output, records.append)

    def boom(*_args):
        raise RuntimeError("verifier could not open the package")

    with pytest.raises(RuntimeError, match="could not open"):
        probe.wrap_verify(boom)(_node(), None, None, None)

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
    probe.wrap_verify(lambda *_args: True)(_node("n025"), None, None, None)

    record = records[0]
    assert record["node_id"] == "n025"
    assert record["adapter_wrote_parts"] == ["ppt/slides/slide1.xml"]
    assert record["before_node"]["sha256"] != record["after_adapter"]["sha256"]
    assert record["verifier_mutated_package"] is False


def test_a_verifier_that_writes_to_the_package_is_reported_as_not_read_only(tmp_path):
    """Non-vacuity guard for ``verifier_mutated_package``: it must be capable
    of being True, or the read-only claim it checks is decorative."""

    output = tmp_path / "deck.pptx"
    _package(output, {"a.xml": b"<a/>"})
    records: list[dict] = []
    probe = ActBoundaryProbe(output, records.append)

    def writes_while_verifying(*_args):
        _package(output, {"a.xml": b"<a modified=/>"})
        return True

    probe.wrap_verify(writes_while_verifying)(_node(), None, None, None)

    assert records[0]["verifier_mutated_package"] is True


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
    probe.wrap_verify(lambda *_args: True)(_node(), None, None, None)

    for record in records:
        json.loads(json.dumps(record, sort_keys=True))
