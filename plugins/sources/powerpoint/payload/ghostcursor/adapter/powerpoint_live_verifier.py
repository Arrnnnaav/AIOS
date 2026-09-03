"""Read-only live-state verifier for PowerPoint UIA effects.

The other verifier in this payload opens a saved `.pptx` and counts slides in
the package. That is the right evidence for an `object_model` operation, whose
effect IS a file. It is the wrong evidence for a `uia_pattern` operation:
clicking `New Slide` changes the running application, and nothing reaches disk
until somebody saves. Asked to verify a UIA effect, the artifact verifier can
only decline -- which is what it did, correctly, on the first live run.

This reads the live application instead, and it is deliberately a SEPARATE
signed file rather than a mode of the other one. They carry different trust:
`trust_for(UIA_PATTERN, VERIFIED)` is LIVE_STATE and
`trust_for(OBJECT_MODEL, VERIFIED)` is ARTIFACT. One file answering for both
would let a reading of the wrong kind satisfy either claim.

**It cannot act.** It resolves nothing to click, dispatches no pattern, and
imports no input API. The only UIA calls it makes are property reads through
`FindAll` and `CurrentName`. That prohibition is scanned from this module's
AST by the core test suite, the same way `uia_feasibility` is.

**What it verifies is a CHANGE, not a state.** `slide.exists` is satisfied by
any non-empty deck, so a node that did nothing would pass it. The request
carries the baseline reading taken before the cue, and the postcondition names
a relation between then and now. The comparison lives here, in signed plugin
code, because "a slide was added" is knowledge about PowerPoint and core must
never learn it.

Identity discipline matches the adapter's: the approved window must still
exist and still belong to the approved process, checked at read time, because
a handle can be recycled and a recycled handle is a different window with the
same number.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

PLUGIN_ID = "ghostcursor.powerpoint"
PLUGIN_VERSION = "1.0.0"
_SHA_RE = re.compile(r"[0-9a-f]{64}")

#: UIA property and control-type ids this file is allowed to name. Written out
#: rather than imported so the reviewed bytes contain every constant they rely
#: on and no lookup can be redirected.
_UIA_CONTROL_TYPE_PROPERTY = 30003
_STATUS_BAR_CONTROL_TYPE = 50021
_TREE_SCOPE_DESCENDANTS = 4

#: `View Indicator Slide 3 of 7`. The trailing number is the deck's slide
#: count; the leading one is which slide is selected. Anchored so a caption
#: containing the phrase cannot match loosely.
_SLIDE_INDICATOR = re.compile(r"^View Indicator Slide (\d+) of (\d+)$")

#: The postconditions this verifier knows how to answer, and what each means
#: as a relation between the baseline reading and the current one. A
#: postcondition absent from here is refused rather than assumed true.
_RELATIONS = {
    "slide.count.increased": lambda before, now: now > before,
    "slide.count.increased_by_one": lambda before, now: now == before + 1,
    "slide.count.unchanged": lambda before, now: now == before,
}


class Refusal(ValueError):
    pass


def _exact(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise Refusal(f"{label} fields are invalid")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class LiveWindow:
    """The approved window, re-proved every time it is read."""

    def __init__(self, target):
        _exact(
            target,
            {"executable", "executable_version", "hwnd", "pid"},
            "verification target",
        )
        self.hwnd = int(target["hwnd"])
        self.pid = int(target["pid"])

    def _authority(self):
        import win32gui
        import win32process

        if not win32gui.IsWindow(self.hwnd):
            raise Refusal("approved window no longer exists")
        _thread, owner = win32process.GetWindowThreadProcessId(self.hwnd)
        if int(owner) != self.pid:
            raise Refusal("approved window no longer belongs to the approved process")

    def slide_count(self):
        """Slides in the running deck, from the status bar's view indicator.

        Every status bar descendant is read and the matches collected, then
        the count is required to be exactly one. Taking the first match would
        mean a second indicator -- a second view, a second window pane --
        silently decided the answer.
        """

        self._authority()
        import comtypes.client

        module = comtypes.client.GetModule("UIAutomationCore.dll")
        automation = comtypes.client.CreateObject(
            "{ff48dba4-60ef-4201-aa87-54103eef594e}", interface=module.IUIAutomation
        )
        root = automation.ElementFromHandle(self.hwnd)
        bars = root.FindAll(
            _TREE_SCOPE_DESCENDANTS,
            automation.CreatePropertyCondition(
                _UIA_CONTROL_TYPE_PROPERTY, _STATUS_BAR_CONTROL_TYPE
            ),
        )
        readings = []
        for index in range(int(bars.Length)):
            children = bars.GetElement(index).FindAll(
                _TREE_SCOPE_DESCENDANTS, automation.CreateTrueCondition()
            )
            for child in range(int(children.Length)):
                try:
                    name = children.GetElement(child).CurrentName
                except Exception:  # noqa: BLE001
                    # An unreadable sibling is not an absent indicator. It is
                    # skipped, and if the indicator itself is the unreadable
                    # one the count below refuses -- a failed read never
                    # becomes a clean zero (D069).
                    continue
                match = _SLIDE_INDICATOR.match(name or "")
                if match is not None:
                    readings.append((int(match.group(1)), int(match.group(2))))
        if len(readings) != 1:
            raise Refusal(f"expected exactly one slide indicator, read {len(readings)}")
        current, total = readings[0]
        return {"slide_current": current, "slide_count": total}


def _decide(postconditions, baseline, observed):
    """Answer every declared postcondition, or refuse.

    Refuses an unknown one rather than ignoring it. A postcondition nothing
    can answer must not pass by being skipped -- that is the shape of a check
    that looks present in the record and enforces nothing.
    """

    if not postconditions:
        raise Refusal("the operation declares no postcondition to verify")
    for name in postconditions:
        relation = _RELATIONS.get(name)
        if relation is None:
            raise Refusal(f"postcondition {name!r} is not one this verifier answers")
        if "slide_count" not in baseline:
            raise Refusal(f"postcondition {name!r} needs a baseline slide count")
        if not relation(int(baseline["slide_count"]), int(observed["slide_count"])):
            raise Refusal(
                f"postcondition {name!r} does not hold: "
                f"{baseline['slide_count']} -> {observed['slide_count']}"
            )
    return True


def main():
    if sys.argv[1:] != ["--json"]:
        return 2
    request = json.loads(sys.stdin.readline())
    _exact(
        request,
        {
            "baseline",
            "node",
            "output_path",
            "plugin_id",
            "plugin_version",
            "postconditions",
            "session_nonce",
            "target",
            "type",
            "validation_sha256",
            "verifier_sha256",
        },
        "verification request",
    )
    _exact(
        request["node"], {"node_id", "operation_id", "parameters"}, "verification node"
    )
    own_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if (
        request["type"] != "verify"
        or request["plugin_id"] != PLUGIN_ID
        or request["plugin_version"] != PLUGIN_VERSION
        or request["verifier_sha256"] != own_sha
        or _SHA_RE.fullmatch(request["validation_sha256"]) is None
    ):
        raise Refusal("verifier authority disagrees")

    try:
        observed = LiveWindow(request["target"]).slide_count()
        baseline = request["baseline"]
        if baseline is None:
            # A READING, not a verdict. `observe_before` and `confirm_before`
            # both call this with no baseline: there is nothing yet to compare
            # against, and reporting `verified` for a comparison that was
            # never made is exactly the false green this whole flow exists to
            # prevent.
            outcome, detail = "refused", "reading only; no baseline to compare against"
        elif not isinstance(baseline, dict):
            raise Refusal("baseline must be an object")
        else:
            _decide(request["postconditions"], baseline, observed)
            outcome = "verified"
            detail = "live application state independently confirms the change"
    except Exception as exc:  # noqa: BLE001 - every refusal is reported
        observed, outcome, detail = {}, "refused", f"{type(exc).__name__}: {exc}"

    sys.stdout.write(
        _canonical(
            {
                "detail": detail,
                "node_id": request["node"]["node_id"],
                "observed": observed,
                "outcome": outcome,
                "session_nonce": request["session_nonce"],
                "type": "verification_result",
                "validation_sha256": request["validation_sha256"],
            }
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
