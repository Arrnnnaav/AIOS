"""The generic UIA adapter resolves one control and invokes it — nothing else.

Every case here is a way the adapter could act on something other than the
single control the signed operation named, or could act at all when it should
have refused. The live COM path is exercised only through injected fakes; the
real dispatch is proven on a desktop, not here.
"""

from __future__ import annotations

import importlib.util
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "plugins" / "shared" / "uia_adapter.py"


def _module():
    spec = importlib.util.spec_from_file_location("shared_uia_adapter", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = _module()


class _Element:
    def __init__(
        self,
        *,
        name="New Slide",
        automation_id="NewSlide",
        runtime_id=(7, 1, 2),
        rect=(10, 20, 110, 60),
        patterns=None,
    ):
        self.CurrentName = name
        self.CurrentAutomationId = automation_id
        self.CurrentNativeWindowHandle = 0
        self.CurrentBoundingRectangle = SimpleNamespace(
            left=rect[0], top=rect[1], right=rect[2], bottom=rect[3]
        )
        self._runtime_id = runtime_id
        self._patterns = patterns if patterns is not None else {10000: "Invoke"}
        self.invoked = []

    def GetRuntimeId(self):
        return list(self._runtime_id)

    def GetCurrentPattern(self, pattern_id):
        if pattern_id not in self._patterns:
            return None
        element = self

        class _Handle:
            def QueryInterface(self, _interface):
                class _Pattern:
                    def Invoke(self):
                        element.invoked.append(("Invoke", None))

                    def Select(self):
                        element.invoked.append(("Select", None))

                    def Toggle(self):
                        element.invoked.append(("Toggle", None))

                    def SetValue(self, value):
                        element.invoked.append(("SetValue", value))

                    def DoDefaultAction(self):
                        element.invoked.append(("DoDefaultAction", None))

                return _Pattern()

        return _Handle()


class _FoundAll:
    def __init__(self, elements):
        self._elements = list(elements)
        self.Length = len(self._elements)

    def GetElement(self, index):
        return self._elements[index]


class _Automation:
    """Enough of IUIAutomation for the adapter's real resolution path.

    The previous helper replaced `resolve_exactly_one` outright, so the tests
    exercised the stub and four mutations to the real method survived. Faking
    at THIS level means the cardinality check, the control-type table and the
    scope constant are all the adapter's own.
    """

    def __init__(self, elements):
        self._elements = list(elements)
        self.requested = []

    def ElementFromHandle(self, hwnd):
        automation = self

        class _Root:
            def FindAll(self, scope, condition):
                automation.requested.append((scope, condition))
                name = condition["name"]
                return _FoundAll(
                    [e for e in automation._elements if e.CurrentName == name]
                )

        return _Root()

    def CreateAndCondition(self, first, second):
        return {**first, **second}

    def CreatePropertyCondition(self, property_id, value):
        key = "control_type" if property_id == adapter._UIA_CONTROL_TYPE_PROPERTY else "name"
        return {key: value}


def _session(elements=None, *, hwnd=101, pid=202, owner=None, window_exists=True):
    """A session whose COM and Win32 edges are faked, and whose LOGIC is real."""

    import sys
    from unittest import mock

    context = {
        "target": {
            "executable": "powerpnt.exe",
            "executable_version": "16.0",
            "hwnd": hwnd,
            "pid": pid,
        }
    }
    session = adapter.UiaSession(context)
    automation = _Automation(elements if elements is not None else [_Element()])
    module = SimpleNamespace(
        IUIAutomationLegacyIAccessiblePattern=object,
        **{entry[1]: object for entry in adapter._PATTERNS.values()},
    )
    session._connect = lambda: (automation, module)
    session._automation = automation
    session._module = module

    win32gui = SimpleNamespace(IsWindow=lambda handle: window_exists)
    win32process = SimpleNamespace(
        GetWindowThreadProcessId=lambda handle: (0, pid if owner is None else owner)
    )
    session._patch = mock.patch.dict(
        sys.modules, {"win32gui": win32gui, "win32process": win32process}
    )
    return session


def _resolve(session, control_type="Button", name="New Slide"):
    """Run the adapter's real resolution with the Win32 edge faked."""

    with session._patch:
        return session.resolve_exactly_one(control_type, name)


# --- it knows nothing about any application -------------------------------


def test_the_canonical_source_names_no_application():
    """An adapter that learns an application's object model is an application
    adapter and belongs in that plugin, not in the shared source (D108)."""

    text = SOURCE.read_text(encoding="utf-8").lower()

    for application in (
        "powerpoint",
        "powerpnt",
        "excel",
        "word",
        "outlook",
        "vscode",
        "chrome",
        "notepad",
    ):
        assert application not in text, application


def test_the_canonical_source_declares_no_plugin_identity():
    """It cannot carry one. The bytes must be identical in every payload or
    the canonical-digest check refuses them, so a build-time stamp would break
    the property that lets one review cover every copy. Identity arrives in
    the hello handshake, from the manifest core already verified."""

    assert not hasattr(adapter, "PLUGIN_ID")
    assert not hasattr(adapter, "PLUGIN_VERSION")
    assert "PLUGIN_ID" not in SOURCE.read_text(encoding="utf-8").replace(
        "plugin identity constant", ""
    ).replace("stamping an id", "")


# --- exactly one control, or nothing --------------------------------------


def test_a_selector_matching_nothing_refuses():
    session = _session([])

    with pytest.raises(adapter.Refusal, match="no Button named"):
        _resolve(session)


def test_a_selector_matching_several_refuses_rather_than_taking_the_first():
    session = _session([_Element(), _Element()])

    with pytest.raises(adapter.Refusal, match="matched 2 controls, not one"):
        _resolve(session)


def test_an_unreviewed_control_type_refuses():
    """A mapping built by scanning the UIA module would silently start
    accepting types no operation has been reviewed against."""

    session = _session()

    with pytest.raises(adapter.Refusal, match="no reviewed UIA id"):
        _resolve(session, control_type="Hyperlink")


def test_window_authority_is_rechecked_on_every_resolution():
    """A handle can be recycled, and a recycled handle is a different window
    with the same number."""

    session = _session(owner=999)

    with pytest.raises(adapter.Refusal, match="no longer belongs"):
        _resolve(session)


# --- dispatch happens on the element that was compared --------------------


@pytest.mark.parametrize(
    "pattern,method",
    [("Invoke", "Invoke"), ("SelectionItem", "Select"), ("Toggle", "Toggle")],
)
def test_each_pattern_dispatches_its_own_method(pattern, method):
    element = _Element(patterns={adapter._PATTERNS[pattern][0]: pattern})
    session = _session([element])

    session.dispatch(element, pattern)

    assert element.invoked == [(method, None)]


def test_value_requires_a_string():
    element = _Element(patterns={adapter._PATTERNS["Value"][0]: "Value"})
    session = _session([element])

    with pytest.raises(adapter.Refusal, match="requires a string"):
        session.dispatch(element, "Value", 42)

    session.dispatch(element, "Value", "hello")
    assert element.invoked == [("SetValue", "hello")]


def test_a_control_that_does_not_expose_the_pattern_refuses():
    element = _Element(patterns={})
    session = _session([element])

    with pytest.raises(adapter.Refusal, match="does not expose Invoke"):
        session.dispatch(element, "Invoke")


def test_an_undispatchable_pattern_refuses():
    element = _Element()
    session = _session([element])

    with pytest.raises(adapter.Refusal, match="not dispatchable"):
        session.dispatch(element, "ExpandCollapse")


def test_the_legacy_default_action_is_dispatched_separately_from_patterns():
    """It is not a UIA pattern and is never presented as one."""

    element = _Element(patterns={adapter._LEGACY_PATTERN_ID: "legacy"})
    session = _session([element])

    session.dispatch(element, "DoDefaultAction")

    assert element.invoked == [("DoDefaultAction", None)]
    assert "DoDefaultAction" not in adapter._PATTERNS


def _confirmed_request(**overrides):
    geometry = adapter.observe_bracketed(lambda: [[10, 20, 110, 60]])
    value = {
        "authorization_sha256": "a" * 64,
        "control_type": "Button",
        "expected_identity": {
            "control_type": "Button",
            "name": "New Slide",
            "runtime_id": [7, 1, 2],
        },
        "expected_coordinate_space": geometry.as_record(),
        "expected_rectangle": [10, 20, 110, 60],
        "name": "New Slide",
        "pattern": "Invoke",
        "value": None,
    }
    value.update(overrides)
    return value


def test_confirmed_dispatch_compares_and_invokes_the_same_element():
    element = _Element()
    session = _session([element])

    with session._patch:
        identity, rectangle, geometry = session.execute_confirmed(_confirmed_request())

    assert identity["runtime_id"] == [7, 1, 2]
    assert rectangle == [10, 20, 110, 60]
    assert geometry.rectangles == ((10, 20, 110, 60),)
    assert element.invoked == [("Invoke", None)]


@pytest.mark.parametrize(
    "change,detail",
    [
        ({"expected_identity": {"control_type": "Button", "name": "New Slide", "runtime_id": [9]}}, "runtime_id"),
        ({"expected_rectangle": [11, 20, 110, 60]}, "rectangle"),
        ({"expected_identity": {"control_type": "TabItem", "name": "New Slide"}}, "control type"),
    ],
)
def test_a_changed_confirmed_target_refuses_before_the_effect(change, detail):
    element = _Element()
    session = _session([element])

    with session._patch, pytest.raises(adapter.Refusal, match=detail):
        session.execute_confirmed(_confirmed_request(**change))

    assert element.invoked == []


def test_a_coordinate_space_change_refuses_before_the_effect():
    element = _Element()
    session = _session([element])
    request = _confirmed_request()
    record = request["expected_coordinate_space"]
    changed = list(record["before"]["virtual_bounds"])
    changed[2] += 1
    record["before"]["virtual_bounds"] = changed
    record["after"]["virtual_bounds"] = list(changed)

    with session._patch, pytest.raises(adapter.Refusal, match="coordinate space changed"):
        session.execute_confirmed(request)

    assert element.invoked == []


def test_a_coordinate_context_that_changes_during_final_read_refuses_before_effect(
    monkeypatch,
):
    from ghostcursor.coordinate_space import BracketedGeometry, capture

    element = _Element()
    session = _session([element])
    request = _confirmed_request()
    before = capture()
    after = replace(before, virtual_bounds=(0, 0, before.virtual_bounds[2] + 1, 1))
    monkeypatch.setattr(
        adapter,
        "observe_bracketed",
        lambda _read: BracketedGeometry(before, after, ((10, 20, 110, 60),)),
    )

    with session._patch, pytest.raises(adapter.Refusal, match="coordinate space changed"):
        session.execute_confirmed(request)

    assert element.invoked == []


def test_a_confirmation_authorization_is_one_use_even_after_refusal():
    element = _Element()
    session = _session([element])
    wrong = _confirmed_request(expected_rectangle=[11, 20, 110, 60])

    with session._patch, pytest.raises(adapter.Refusal, match="rectangle"):
        session.execute_confirmed(wrong)
    with session._patch, pytest.raises(adapter.Refusal, match="already consumed"):
        session.execute_confirmed(_confirmed_request())

    assert element.invoked == []


def test_a_control_without_legacy_support_refuses():
    element = _Element(patterns={})
    session = _session([element])

    with pytest.raises(adapter.Refusal, match="does not expose LegacyIAccessible"):
        session.dispatch(element, "DoDefaultAction")


# --- what it reports back --------------------------------------------------


def test_describe_reports_identity_rectangle_and_coordinate_space():
    element = _Element()
    session = _session([element])

    identity, rectangle, geometry = session.describe(element, "Button")

    assert identity["control_type"] == "Button"
    assert identity["name"] == "New Slide"
    assert identity["runtime_id"] == [7, 1, 2]
    assert rectangle == [10, 20, 110, 60]
    assert geometry.rectangles == ((10, 20, 110, 60),)


def test_an_unreadable_property_is_reported_absent_not_defaulted():
    """A property that cannot be read must not cost the others, and must not
    be filled in with something plausible."""

    element = _Element()

    def explode():
        raise OSError("gone")

    type(element).GetRuntimeId = lambda self: explode()
    session = _session([element])

    identity, rectangle, geometry = session.describe(element, "Button")

    assert identity["runtime_id"] is None
    assert identity["name"] == "New Slide"
    assert rectangle == [10, 20, 110, 60]
    assert geometry.rectangles == ((10, 20, 110, 60),)


# --- the closed vocabularies ----------------------------------------------


def test_the_pattern_table_matches_the_registry_vocabulary():
    from ghostcursor.action import UIA_PATTERNS

    assert set(adapter._PATTERNS) == set(UIA_PATTERNS)


def test_every_pattern_names_a_distinct_id_and_method():
    ids = [entry[0] for entry in adapter._PATTERNS.values()]

    assert len(ids) == len(set(ids))
    assert adapter._LEGACY_PATTERN_ID not in ids



def test_a_window_that_no_longer_exists_refuses():
    session = _session(window_exists=False)

    with pytest.raises(adapter.Refusal, match="no longer exists"):
        _resolve(session)


def test_a_single_match_resolves_and_is_the_element_returned():
    element = _Element()
    session = _session([element])

    assert _resolve(session) is element


def test_resolution_is_scoped_to_the_window_subtree_not_the_desktop():
    """A query rooted at the desktop is an unbounded traversal in another
    costume."""

    session = _session()
    _resolve(session)

    scope, condition = session._automation.requested[0]
    assert scope == adapter._TREE_SCOPE_DESCENDANTS
    assert condition["control_type"] == adapter._CONTROL_TYPE_IDS["Button"]
    assert condition["name"] == "New Slide"
