"""The selector file decides which control gets invoked, so it has to be the
reviewed one.

Until this module existed the operation carried a `selector_sha256` that
nothing ever compared to anything. These are the ways a control name could
reach the adapter without being the signed plugin's.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ghostcursor.selectors import (
    SelectorError,
    load_action_selector,
    load_selector,
    selector_path,
)

REPO = Path(__file__).resolve().parents[1]
PAYLOAD = REPO / "plugins/sources/powerpoint/payload"


def _write(tmp_path: Path, body, *, pack="powerpoint", stem="new-slide") -> str:
    """Put a selector where the loader will look, and return its digest."""

    folder = tmp_path / "ghostcursor" / "packs" / pack / "selectors"
    folder.mkdir(parents=True, exist_ok=True)
    raw = (
        body
        if isinstance(body, bytes)
        else json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    )
    (folder / f"{stem}.json").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _body(**overrides):
    body = {
        "cardinality": "exactly_one",
        "control_type": "Button",
        "name": "New Slide",
        "selector_id": "powerpoint.new-slide",
    }
    body.update(overrides)
    return body


# --- the shipped selector is the one the shipped operation names -----------


def test_the_real_powerpoint_selector_matches_its_signed_digest():
    """The end-to-end claim. If this fails, the plugin's own operation and its
    own selector file disagree about which control `New Slide` is."""

    operations = json.loads(
        (PAYLOAD / "ghostcursor/operations.json").read_bytes().decode()
    )
    uia = operations["operations"]["powerpoint.new_slide_uia"]["uia"]

    selector = load_action_selector(
        PAYLOAD,
        uia["selector_id"],
        uia["selector_sha256"],
        control_type=uia["control_type"],
    )

    assert selector.name == "New Slide"
    assert selector.control_type == "Button"
    assert selector.cardinality == "exactly_one"


def test_a_selector_id_resolves_under_the_payloads_own_pack_root():
    path = selector_path(PAYLOAD, "powerpoint.new-slide")

    assert path == PAYLOAD / "ghostcursor/packs/powerpoint/selectors/new-slide.json"
    assert path.exists()


# --- a substituted selector has no authority ------------------------------


def test_a_selector_whose_bytes_changed_is_refused(tmp_path):
    """The whole point. A file that says `Delete Slide` where the reviewed one
    said `New Slide` must not be usable just because it is in the right
    place."""

    digest = _write(tmp_path, _body())
    _write(tmp_path, _body(name="Delete Slide"))

    with pytest.raises(SelectorError, match="but the signed operation declares"):
        load_selector(tmp_path, "powerpoint.new-slide", digest)


def test_the_refusal_does_not_quote_the_unapproved_name(tmp_path):
    """The digest is checked BEFORE the file is parsed. Reading it first would
    put a control name nobody approved into the run record as if it were
    part of the operation."""

    digest = _write(tmp_path, _body())
    _write(tmp_path, _body(name="Delete Slide"))

    with pytest.raises(SelectorError) as raised:
        load_selector(tmp_path, "powerpoint.new-slide", digest)

    assert "Delete Slide" not in str(raised.value)


def test_a_selector_that_names_a_different_id_than_it_was_reached_by(tmp_path):
    """Misfiled or substituted. Neither is usable, and the digest alone would
    not catch it -- the file is exactly its own bytes."""

    digest = _write(tmp_path, _body(selector_id="powerpoint.delete-slide"))

    with pytest.raises(SelectorError, match="names 'powerpoint.delete-slide'"):
        load_selector(tmp_path, "powerpoint.new-slide", digest)


def test_a_missing_selector_is_refused(tmp_path):
    with pytest.raises(SelectorError, match="not in the payload"):
        load_selector(tmp_path, "powerpoint.new-slide", "a" * 64)


@pytest.mark.parametrize(
    "selector_id",
    [
        "../../../etc/passwd",
        "powerpoint../new-slide",
        "powerpoint.new-slide/../../x",
        "powerpoint..new-slide",
        "PowerPoint.new-slide",
        "powerpoint",
        "powerpoint.new-slide.extra",
        "",
    ],
)
def test_a_selector_id_cannot_walk_out_of_the_pack_root(selector_id):
    """Bounded by the pattern rather than by a path check afterwards: there is
    no character class in it that admits a separator, so escaping is not
    something that has to be detected."""

    with pytest.raises(SelectorError, match="not a valid id"):
        selector_path(Path("/payload"), selector_id)


@pytest.mark.parametrize("digest", ["", "abc", "A" * 64, "g" * 64, 64, None])
def test_a_malformed_digest_is_refused_before_anything_is_read(tmp_path, digest):
    with pytest.raises(SelectorError, match="64 lowercase hex"):
        load_selector(tmp_path, "powerpoint.new-slide", digest)


# --- the file has to be a selector ----------------------------------------


def test_a_selector_that_is_not_json_is_refused(tmp_path):
    digest = _write(tmp_path, b"not json at all")

    with pytest.raises(SelectorError, match="not valid JSON"):
        load_selector(tmp_path, "powerpoint.new-slide", digest)


@pytest.mark.parametrize(
    "field", ["cardinality", "control_type", "name", "selector_id"]
)
def test_a_selector_missing_a_field_is_refused(tmp_path, field):
    body = _body()
    del body[field]
    digest = _write(tmp_path, body)

    with pytest.raises(SelectorError, match="fields are invalid"):
        load_selector(tmp_path, "powerpoint.new-slide", digest)


def test_an_extra_field_is_refused(tmp_path):
    """A selector carrying something the loader ignores is a selector saying
    more than was reviewed."""

    digest = _write(tmp_path, _body(offset=[3, 4]))

    with pytest.raises(SelectorError, match="fields are invalid"):
        load_selector(tmp_path, "powerpoint.new-slide", digest)


@pytest.mark.parametrize("value", ["", 7, None, []])
def test_an_empty_or_non_string_name_is_refused(tmp_path, value):
    digest = _write(tmp_path, _body(name=value))

    with pytest.raises(SelectorError, match="name is invalid"):
        load_selector(tmp_path, "powerpoint.new-slide", digest)


def test_an_unknown_cardinality_is_refused(tmp_path):
    digest = _write(tmp_path, _body(cardinality="first_match"))

    with pytest.raises(SelectorError, match="unknown cardinality"):
        load_selector(tmp_path, "powerpoint.new-slide", digest)


# --- an ACTION selector is stricter ---------------------------------------


def test_an_action_selector_may_not_match_several_controls(tmp_path):
    """D069: choosing one of several on the operator's behalf is never the
    software's call. A verification selector may be at_least_one; this is not
    a verification selector."""

    digest = _write(tmp_path, _body(cardinality="at_least_one"))

    with pytest.raises(SelectorError, match="cannot choose a control to act on"):
        load_action_selector(
            tmp_path, "powerpoint.new-slide", digest, control_type="Button"
        )


def test_an_at_least_one_selector_still_loads_for_verification(tmp_path):
    digest = _write(tmp_path, _body(cardinality="at_least_one"))

    selector = load_selector(tmp_path, "powerpoint.new-slide", digest)

    assert selector.cardinality == "at_least_one"


def test_an_action_selector_must_agree_with_the_operations_control_type(tmp_path):
    """Two independent statements about the same control. If they disagree,
    the operation is not describing this selector."""

    digest = _write(tmp_path, _body(control_type="MenuItem"))

    with pytest.raises(SelectorError, match="names a MenuItem"):
        load_action_selector(
            tmp_path, "powerpoint.new-slide", digest, control_type="Button"
        )


def test_an_agreeing_action_selector_loads(tmp_path):
    digest = _write(tmp_path, _body())

    selector = load_action_selector(
        tmp_path, "powerpoint.new-slide", digest, control_type="Button"
    )

    assert selector.name == "New Slide"
    assert selector.sha256 == digest
