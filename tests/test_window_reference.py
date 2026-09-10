"""A target reference must be a pseudonym, and equality must be real.

D128 replaced the raw HWND in an acceptance record with a label. An
independent review then found that nothing tested the replacement: making
`window_pseudonym` return `str(hwnd)` passed all 2461 tests, so the whole
privacy control could revert silently. Worse, the label came from a
process-local counter while a campaign runs each attempt in its own process,
so every run wrote `window-A` whatever it bound -- and the renderer's "all
three references are equal" check, which had been real evidence when the
record held the handle, could no longer fail.

Both properties are pinned here:

* the label is not the handle, in any form; and
* equality between labels tracks equality between handles, across process
  boundaries, because the salt is inherited rather than regenerated.

The second is what the evidence sentence rests on. A test that only checked
"the label is stable within one process" would pass for the broken version.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ghostcursor.devtools.candidate_acceptance import (
    campaign_scope,
    window_reference,
)

ROOT = Path(__file__).resolve().parents[1]


def test_a_reference_does_not_contain_the_handle_in_any_obvious_form():
    """The mutation that survived the whole suite: returning `str(hwnd)`."""

    hwnd = 1050680
    reference = window_reference(hwnd)

    assert str(hwnd) not in reference
    assert format(hwnd, "x") not in reference.lower()
    assert format(hwnd, "o") not in reference
    assert reference != str(hwnd)
    assert reference.startswith("window-")
    # A digest, not an ordinal: `window-A` carries no information about the
    # handle, but it also cannot distinguish two handles reliably once more
    # than one process is involved.
    assert len(reference) > len("window-A")


def test_equal_handles_give_equal_references_and_different_ones_do_not():
    scope, salt = "campaign-1", b"\x01" * 32

    assert window_reference(11, scope=scope, salt=salt) == window_reference(
        11, scope=scope, salt=salt
    )
    assert window_reference(11, scope=scope, salt=salt) != window_reference(
        12, scope=scope, salt=salt
    )


def test_a_different_salt_makes_the_same_handle_incomparable():
    """Two campaigns must not appear to share a window just because the same
    handle value was reused by the operating system."""

    assert window_reference(11, scope="c", salt=b"\x01" * 32) != window_reference(
        11, scope="c", salt=b"\x02" * 32
    )


def test_the_scope_is_inherited_from_the_environment_when_a_campaign_sets_it():
    previous = {
        k: os.environ.get(k)
        for k in ("GHOSTCURSOR_CAMPAIGN_SCOPE", "GHOSTCURSOR_CAMPAIGN_SALT")
    }
    try:
        os.environ["GHOSTCURSOR_CAMPAIGN_SCOPE"] = "abc123"
        os.environ["GHOSTCURSOR_CAMPAIGN_SALT"] = "aa" * 32
        scope, salt = campaign_scope()
        assert scope == "abc123"
        assert salt == bytes.fromhex("aa" * 32)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_without_a_campaign_scope_each_process_gets_its_own():
    """So that two unrelated runs are *incomparable* rather than falsely
    equal. This is the safe direction: a renderer refuses to compare them."""

    first, first_salt = campaign_scope()
    second, second_salt = campaign_scope()

    assert first != second
    assert first_salt != second_salt


def _reference_in_subprocess(hwnd, environment):
    code = (
        "from ghostcursor.devtools.candidate_acceptance import "
        "window_reference, window_scope;"
        f"print(window_reference({hwnd}), window_scope())"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=environment,
        check=True,
    )
    return result.stdout.split()


@pytest.mark.parametrize("same_window", [True, False])
def test_references_agree_across_processes_only_when_the_handle_agrees(same_window):
    """The property the evidence sentence rests on, checked the way a campaign
    actually runs: separate processes sharing one inherited scope.

    With the process-local counter this test's second case failed to fail --
    two different handles in two processes both produced `window-A`.
    """

    environment = dict(os.environ)
    environment["GHOSTCURSOR_CAMPAIGN_SCOPE"] = "campaign-xyz"
    environment["GHOSTCURSOR_CAMPAIGN_SALT"] = "bb" * 32
    environment["PYTHONPATH"] = str(ROOT)

    first, first_scope = _reference_in_subprocess(4242, environment)
    second, second_scope = _reference_in_subprocess(
        4242 if same_window else 9999, environment
    )

    assert first_scope == second_scope == "campaign-xyz"
    assert (first == second) is same_window


def test_every_committed_record_carries_a_reference_and_a_scope():
    """The migrated records, checked as data rather than as code."""

    records = sorted(
        path
        for path in (ROOT / "plugins" / "sources").rglob("*.json")
        if "acceptance-records" in path.parts
    )
    assert len(records) >= 15

    for path in records:
        target = json.loads(path.read_text(encoding="utf-8")).get("target")
        if target is None:
            continue
        assert "hwnd" not in target, path
        assert "pid" not in target, path
        assert isinstance(target.get("target_ref"), str) and target["target_ref"]
        assert isinstance(target.get("target_scope"), str) and target["target_scope"]


def test_records_that_bound_one_window_share_a_label_and_others_do_not():
    """Excel's worksheet campaign bound three different windows and its cell
    campaign bound one. If the labels did not reflect that, they would be
    decoration rather than evidence."""

    def labels(folder):
        return {
            json.loads(path.read_text(encoding="utf-8"))["target"]["target_ref"]
            for path in sorted(folder.glob("*.json"))
        }

    excel = ROOT / "plugins" / "sources" / "excel" / "acceptance-records"
    assert len(labels(excel / "add-worksheet")) == 3
    assert len(labels(excel / "select-cell-b2")) == 1
    assert (
        len(labels(ROOT / "plugins/sources/powerpoint/acceptance-records/add-slide"))
        == 1
    )
