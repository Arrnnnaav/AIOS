"""Signed GhostCursor generic UIA adapter (JSONL protocol v1).

One canonical source. A plugin that declares UIA operations copies these exact
bytes into its own payload and signs them as its own adapter (D108). The
copies are byte-identical, so they share one digest and one review, while
separate signing keeps one plugin's adapter unable to act for another.

**It knows nothing about any application.** It is handed a control type, an
exact accessible name and a pattern to dispatch, all from the signed operation
registry, and it resolves and invokes exactly that. There is no application
name in this file and there must never be one: an adapter that learns an
application's object model is an application adapter, and belongs in that
plugin rather than here.

**It never synthesizes input.** No SendInput, no cursor movement, no
keystrokes. It calls UIA patterns, which ask the control to act on itself. The
pointer the user sees is drawn by the overlay at the rectangle this adapter
reports; the click is this pattern call, at that control (D109).

**Resolution happens once, immediately before the call.** The element that was
compared is the element that is invoked -- never re-resolved between the
comparison and the dispatch, because a selector can start matching something
else in that gap.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

# No plugin identity constant, deliberately. The bytes must be IDENTICAL in
# every payload that carries them, or the canonical-digest check refuses them
# (D108) -- so stamping an id in at build time would break the very property
# that lets one review cover every copy. Identity arrives in the `hello`
# handshake instead, from the signed manifest core already verified.
_SHA_RE = re.compile(r"[0-9a-f]{64}")

#: TreeScope_Descendants. Scoped to the approved window's subtree, never the
#: desktop root -- a query rooted at the desktop is an unbounded traversal in
#: another costume.
_TREE_SCOPE_DESCENDANTS = 4
_UIA_NAME_PROPERTY = 30005
_UIA_CONTROL_TYPE_PROPERTY = 30003

#: Control types this adapter may be pointed at. Explicit rather than derived:
#: a mapping built by scanning the UIA module would silently start accepting
#: types no operation has been reviewed against.
_CONTROL_TYPE_IDS = {
    "Button": 50000,
    "CheckBox": 50002,
    "DataItem": 50029,
    "Edit": 50004,
    "List": 50008,
    "ListItem": 50007,
    "MenuItem": 50011,
    "RadioButton": 50013,
    "SplitButton": 50031,
    "Tab": 50018,
    "TabItem": 50019,
    "Text": 50020,
    "TreeItem": 50024,
}

#: Pattern id, and the interface that dispatches it. `DoDefaultAction` is not
#: a UIA pattern and is dispatched through LegacyIAccessible; it is listed
#: separately everywhere so it can never be presented as a true pattern.
_PATTERNS = {
    "Invoke": (10000, "IUIAutomationInvokePattern", "Invoke"),
    "SelectionItem": (10010, "IUIAutomationSelectionItemPattern", "Select"),
    "Toggle": (10015, "IUIAutomationTogglePattern", "Toggle"),
    "Value": (10002, "IUIAutomationValuePattern", "SetValue"),
}
_LEGACY_PATTERN_ID = 10018


class Refusal(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _exact(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise Refusal(f"{label} fields are invalid")


def _write(value):
    sys.stdout.write(_canonical(value) + "\n")
    sys.stdout.flush()


class UiaSession:
    """Holds the approved window and resolves controls inside it."""

    def __init__(self, context):
        _exact(context, {"target"}, "session context")
        target = context["target"]
        _exact(
            target,
            {"executable", "executable_version", "hwnd", "pid"},
            "session target",
        )
        self.hwnd = int(target["hwnd"])
        self.pid = int(target["pid"])
        self.executable = str(target["executable"]).casefold()
        self.executable_version = str(target["executable_version"])
        self._automation = None
        self._module = None
        self._consumed = set()

    def _connect(self):
        if self._automation is None:
            import comtypes.client

            self._module = comtypes.client.GetModule("UIAutomationCore.dll")
            self._automation = comtypes.client.CreateObject(
                "{ff48dba4-60ef-4201-aa87-54103eef594e}",
                interface=self._module.IUIAutomation,
            )
        return self._automation, self._module

    def _verify_window_authority(self):
        """Prove the approved window still exists and still belongs to the
        approved process, before anything is resolved inside it.

        Checked every time rather than once at startup: the handle can be
        recycled, and a recycled handle is a different window with the same
        number.
        """

        import win32gui
        import win32process

        if not win32gui.IsWindow(self.hwnd):
            raise Refusal("approved window no longer exists")
        _thread, owner = win32process.GetWindowThreadProcessId(self.hwnd)
        if int(owner) != self.pid:
            raise Refusal("approved window no longer belongs to the approved process")

    def resolve_exactly_one(self, control_type, name):
        """Resolve one control, or refuse. Never take the first of several."""

        self._verify_window_authority()
        automation, _module = self._connect()
        type_id = _CONTROL_TYPE_IDS.get(control_type)
        if type_id is None:
            raise Refusal(f"control type {control_type!r} has no reviewed UIA id")
        root = automation.ElementFromHandle(self.hwnd)
        condition = automation.CreateAndCondition(
            automation.CreatePropertyCondition(_UIA_CONTROL_TYPE_PROPERTY, type_id),
            automation.CreatePropertyCondition(_UIA_NAME_PROPERTY, name),
        )
        found = root.FindAll(_TREE_SCOPE_DESCENDANTS, condition)
        count = int(found.Length)
        if count == 0:
            raise Refusal(f"no {control_type} named {name!r} in the approved window")
        if count != 1:
            raise Refusal(
                f"{control_type} named {name!r} matched {count} controls, not one"
            )
        return found.GetElement(0)

    def describe(self, element, control_type):
        """Read the identity core compares, and the rectangle it may draw.

        Each read is separate: an unreadable RuntimeId must not cost the
        bounding rectangle, and a property that cannot be read is reported
        absent rather than defaulted.
        """

        identity = {"control_type": control_type}
        for key, reader in (
            ("name", lambda: str(element.CurrentName)),
            ("automation_id", lambda: str(element.CurrentAutomationId)),
            ("runtime_id", lambda: [int(part) for part in element.GetRuntimeId()]),
            (
                "native_window_handle",
                lambda: int(element.CurrentNativeWindowHandle) or None,
            ),
        ):
            try:
                identity[key] = reader()
            except Exception:  # noqa: BLE001 - absence is the honest answer
                identity[key] = None
        try:
            rect = element.CurrentBoundingRectangle
            rectangle = [
                int(rect.left),
                int(rect.top),
                int(rect.right),
                int(rect.bottom),
            ]
        except Exception:  # noqa: BLE001
            rectangle = None
        return identity, rectangle

    def dispatch(self, element, pattern, value=None):
        """Invoke the declared pattern on THIS element.

        The element is passed in rather than re-resolved. Re-resolving here
        would mean the control core compared and the control that acts could
        differ, which is the whole gap the identity check exists to close.
        """

        _automation, module = self._connect()
        if pattern == "DoDefaultAction":
            legacy = element.GetCurrentPattern(_LEGACY_PATTERN_ID)
            if legacy is None:
                raise Refusal("control does not expose LegacyIAccessible")
            legacy.QueryInterface(
                module.IUIAutomationLegacyIAccessiblePattern
            ).DoDefaultAction()
            return
        entry = _PATTERNS.get(pattern)
        if entry is None:
            raise Refusal(f"pattern {pattern!r} is not dispatchable")
        pattern_id, interface_name, method = entry
        handle = element.GetCurrentPattern(pattern_id)
        if handle is None:
            raise Refusal(f"control does not expose {pattern}")
        interface = handle.QueryInterface(getattr(module, interface_name))
        if pattern == "Value":
            if not isinstance(value, str):
                raise Refusal("Value requires a string")
            getattr(interface, method)(value)
        else:
            getattr(interface, method)()

    def execute_confirmed(self, request):
        """Consume one request and compare immediately before the effect.

        Core selects required fields from signed policy. This boundary does
        not select a policy: every supplied expectation must hold. Failed
        attempts consume the token too, so callers cannot replay uncertain
        effects or retry a refused target silently.
        """
        digest = request["authorization_sha256"]
        if not isinstance(digest, str) or _SHA_RE.fullmatch(digest) is None:
            raise Refusal("authorization digest is invalid")
        if digest in self._consumed:
            raise Refusal("authorization was already consumed")
        self._consumed.add(digest)
        expected = request["expected_identity"]
        allowed = {"control_type", "name", "runtime_id", "automation_id", "native_window_handle"}
        if (not isinstance(expected, dict) or not expected
                or not set(expected) <= allowed or "control_type" not in expected
                or not ({"name", "runtime_id"} & set(expected))):
            raise Refusal("confirmed identity fields are invalid")
        if expected["control_type"] != request["control_type"]:
            raise Refusal("confirmed control type disagrees with selector")
        for key, value in expected.items():
            if key == "runtime_id":
                valid = isinstance(value, list) and bool(value) and all(type(v) is int for v in value)
            elif key == "native_window_handle":
                valid = type(value) is int and value > 0
            else:
                valid = isinstance(value, str) and bool(value)
            if not valid:
                raise Refusal(f"required {key} was not successfully read")
        wanted_rect = request["expected_rectangle"]
        if (not isinstance(wanted_rect, list) or len(wanted_rect) != 4
                or not all(type(v) is int for v in wanted_rect)
                or wanted_rect[2] <= wanted_rect[0] or wanted_rect[3] <= wanted_rect[1]):
            raise Refusal("confirmed rectangle is invalid")
        element = self.resolve_exactly_one(request["control_type"], request["name"])
        identity, rectangle = self.describe(element, request["control_type"])
        for field, wanted in expected.items():
            if field not in identity or _canonical(identity[field]) != _canonical(wanted):
                raise Refusal(f"confirmed target identity changed: {field}")
        if rectangle != wanted_rect:
            raise Refusal("confirmed target rectangle changed")
        self._verify_window_authority()
        self.dispatch(element, request["pattern"], request.get("value"))
        return identity, rectangle


def main():
    if sys.argv[1:] != ["--jsonl"]:
        return 2
    own_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    hello = json.loads(sys.stdin.readline())
    _exact(
        hello,
        {
            "adapter_sha256",
            "plugin_id",
            "plugin_version",
            "protocol_version",
            "session_context",
            "session_nonce",
            "type",
        },
        "hello",
    )
    if (
        hello["type"] != "hello"
        or hello["protocol_version"] != 1
        or hello["adapter_sha256"] != own_sha
        or _SHA_RE.fullmatch(hello["adapter_sha256"]) is None
    ):
        raise Refusal("adapter authority disagrees")
    session = UiaSession(hello["session_context"])
    _write({**hello, "type": "ready"})

    for line in sys.stdin:
        request = json.loads(line)
        if request.get("type") == "stop":
            break
        try:
            if request.get("session_nonce") != hello["session_nonce"]:
                raise Refusal("session nonce disagrees")
            kind = request.get("type")
            if kind == "observe":
                _exact(
                    request,
                    {"control_type", "name", "request_id", "session_nonce", "type"},
                    "observe",
                )
                element = session.resolve_exactly_one(
                    request["control_type"], request["name"]
                )
                identity, rectangle = session.describe(element, request["control_type"])
                _write(
                    {
                        "identity": identity,
                        "outcome": "observed",
                        "rectangle": rectangle,
                        "request_id": request["request_id"],
                        "session_nonce": hello["session_nonce"],
                        "type": "observation",
                    }
                )
                continue
            if kind != "execute":
                raise Refusal("unknown request type")
            _exact(
                request,
                {
                    "authorization_sha256",
                    "expected_identity",
                    "expected_rectangle",
                    "control_type",
                    "name",
                    "pattern",
                    "request_id",
                    "session_nonce",
                    "type",
                    "value",
                },
                "execute",
            )
            identity, rectangle = session.execute_confirmed(request)
            _write(
                {
                    "data": {"identity": identity, "rectangle": rectangle},
                    "detail": "pattern dispatched on the resolved control",
                    "facts": [],
                    "outcome": "completed",
                    "request_id": request["request_id"],
                    "session_nonce": hello["session_nonce"],
                    "type": "result",
                }
            )
        except Exception as exc:  # noqa: BLE001 - every refusal is reported
            _write(
                {
                    "data": {},
                    "detail": f"{type(exc).__name__}: {exc}",
                    "facts": [],
                    "outcome": "refused",
                    "request_id": request.get("request_id", ""),
                    "session_nonce": hello["session_nonce"],
                    "type": "result",
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
