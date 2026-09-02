"""Loads the one signed selector an operation names, and proves it is that one.

An operation's UIA block carries a `selector_id` and a `selector_sha256` but
not the control's name. The name lives in a separate file inside the plugin's
signed payload, and until now nothing read it — the digest was carried through
validation and never compared against anything.

That gap matters more than a missing feature. The selector file is what says
WHICH control gets invoked. If the name reached the adapter from anywhere but
a digest-checked file, then the thing deciding what gets clicked would not be
the signed plugin.

So this does two things and refuses if either fails: it resolves the file from
the selector id under the payload's own selector root, and it compares the
file's digest to the one the signed operation declared. A mismatch is not a
warning — a selector whose bytes are not the reviewed bytes has no authority,
whatever it says inside.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

#: `plugin.thing` — the two halves become a directory and a file stem. Bounded
#: so a selector id can never walk out of the pack root: no dots, no slashes,
#: no separators of any kind survive the pattern.
_SELECTOR_ID = re.compile(r"^([a-z0-9]+(?:_[a-z0-9]+)*)\.([a-z0-9]+(?:-[a-z0-9]+)*)$")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")

#: The cardinalities a selector may declare. `exactly_one` is the only one an
#: ACTION selector may use — zero matches is a clean absence and more than one
#: is an ambiguity nobody may resolve on the operator's behalf (D069, D070).
CARDINALITIES = frozenset({"exactly_one", "at_least_one"})

_REQUIRED_FIELDS = frozenset({"cardinality", "control_type", "name", "selector_id"})


class SelectorError(ValueError):
    """A selector that must not be used to choose a control."""


@dataclass(frozen=True)
class Selector:
    """One reviewed way to name one control."""

    selector_id: str
    control_type: str
    name: str
    cardinality: str
    sha256: str


def selector_path(payload_root: Path, selector_id: str) -> Path:
    """Where a selector id resolves to inside a payload.

    The id is matched against a bounded pattern first, so a crafted id cannot
    escape the pack root through `..` or a separator — there is no character
    class in the pattern that admits one.
    """

    match = _SELECTOR_ID.match(selector_id)
    if match is None:
        raise SelectorError(f"selector id {selector_id!r} is not a valid id")
    pack, stem = match.groups()
    return (
        Path(payload_root)
        / "ghostcursor"
        / "packs"
        / pack
        / "selectors"
        / f"{stem}.json"
    )


def load_selector(
    payload_root: Path, selector_id: str, selector_sha256: str
) -> Selector:
    """Read the selector the operation names, or refuse.

    `selector_sha256` comes from the signed operation registry. Comparing it
    to the file on disk is what makes the control name signed data rather
    than a string that happened to be sitting in the right place.
    """

    if not isinstance(selector_sha256, str) or _SHA256.match(selector_sha256) is None:
        raise SelectorError("a selector digest is 64 lowercase hex characters")
    path = selector_path(payload_root, selector_id)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SelectorError(f"selector {selector_id!r} is not in the payload") from exc

    digest = hashlib.sha256(raw).hexdigest()
    if digest != selector_sha256:
        # Before parsing, deliberately. Bytes that are not the reviewed bytes
        # have no authority, and reading their contents first would mean the
        # refusal message quoted a control name nobody approved.
        raise SelectorError(
            f"selector {selector_id!r} has digest {digest} but the signed "
            f"operation declares {selector_sha256}"
        )

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SelectorError(f"selector {selector_id!r} is not valid JSON") from exc
    if not isinstance(parsed, dict) or set(parsed) != _REQUIRED_FIELDS:
        raise SelectorError(f"selector {selector_id!r} fields are invalid")
    if parsed["selector_id"] != selector_id:
        # The file names itself. A selector reached through one id that claims
        # another is either misfiled or substituted, and neither is usable.
        raise SelectorError(
            f"selector file names {parsed['selector_id']!r}, not {selector_id!r}"
        )
    for field in ("control_type", "name"):
        value = parsed[field]
        if not isinstance(value, str) or not value:
            raise SelectorError(f"selector {selector_id!r} {field} is invalid")
    if parsed["cardinality"] not in CARDINALITIES:
        raise SelectorError(
            f"selector {selector_id!r} declares unknown cardinality "
            f"{parsed['cardinality']!r}"
        )

    return Selector(
        selector_id=selector_id,
        control_type=parsed["control_type"],
        name=parsed["name"],
        cardinality=parsed["cardinality"],
        sha256=digest,
    )


def load_action_selector(
    payload_root: Path, selector_id: str, selector_sha256: str, *, control_type: str
) -> Selector:
    """A selector used to CHOOSE a control to act on.

    Two extra requirements over a plain load, both from D069/D070:

    - it must be `exactly_one`. An action selector that matched several
      controls would have to pick one on the operator's behalf, and that
      choice is never the software's to make.
    - its control type must equal the one the signed operation declared.
      They are two independent statements about the same control, and if they
      disagree the operation is not describing this selector.
    """

    selector = load_selector(payload_root, selector_id, selector_sha256)
    if selector.cardinality != "exactly_one":
        raise SelectorError(
            f"selector {selector_id!r} is {selector.cardinality} and cannot "
            "choose a control to act on"
        )
    if selector.control_type != control_type:
        raise SelectorError(
            f"selector {selector_id!r} names a {selector.control_type} but the "
            f"operation declares a {control_type}"
        )
    return selector


__all__ = [
    "CARDINALITIES",
    "Selector",
    "SelectorError",
    "load_action_selector",
    "load_selector",
    "selector_path",
]
