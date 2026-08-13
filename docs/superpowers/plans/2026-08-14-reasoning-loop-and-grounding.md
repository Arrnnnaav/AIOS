# Ghost Cursor Reasoning Loop and Grounding Ladder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a guided tour that walks a user through a multi-step task in a real Windows application — grounding each step to a live UI element, drawing a hint, waiting for the user to act, and verifying they did — driven by hand-authored recipes.

**Architecture:** A frozen step contract (`schema.py`) is the interface between recipe producers and the reasoning loop. A grounding ladder resolves a step's text description to a live screen rectangle, cheapest and most stable matcher first, and *promotes* what it learns — writing the discovered AutomationId back into the step so later runs are immune to renames and translation. A state machine drives observe → ground → render → wait → verify, re-planning from real state whenever verification fails. Collaborators are injected so state transitions can be tested without any UI.

**Tech Stack:** Python 3.12, pywin32 (win32gui/win32con/win32api), pywinauto (UIA), mss, numpy, pytest 9.0.3.

**Spec:** `docs/superpowers/specs/2026-08-14-reasoning-and-knowledge-design.md` (sections 4–7; sections 8–10 are out of scope)

## Global Constraints

- **D006 — the system never acts.** No `SendInput`, `mouse_event`, PyAutoGUI, synthesised keystrokes, or moving the real cursor. Ever. The schema field is `user_action` — what to ask the *human* to do.
- **Recipes store intent, never pixels.** No coordinate is ever persisted. Coordinates are resolved live on every render.
- **Locale gates text matchers only.** Rungs 2–4 (name/OCR) are locale-scoped. Rung 1 (AutomationId) is language-independent — never filter it by locale.
- **`accessibility_path_hint` is never identity.** Use only to disambiguate between several otherwise-equal matches.
- **A step with `risk: elevated` may never be completed by `any_meaningful_change`.**
- **Verification checks world state, not the route taken.** Ctrl+S must satisfy a step that said "click File → Save".
- **Import `ghostcursor.overlay.dpi` before creating any window.** It declares DPI awareness at import; skipping it silently changes `GetSystemMetrics` mid-run.
- **The overlay must stay escapable** — ESC from any app, plus timeout, plus teardown in `finally`.
- Existing tests must keep passing: `python -m tests.test_overlay` (14) and `python -m tests.test_end_to_end` (8).

## File Structure

| File | Responsibility |
|---|---|
| `ghostcursor/reasoning/schema.py` | Step/Recipe dataclasses, enums, JSON round-trip, validation |
| `ghostcursor/reasoning/grounding.py` | Grounding ladder rungs 1–3, promotion write-back |
| `ghostcursor/reasoning/verification.py` | UIA snapshots, verification rule evaluation |
| `ghostcursor/reasoning/loop.py` | `GuidedTour` state machine with injected collaborators |
| `ghostcursor/reasoning/recipes/notepad_find.json` | Hand-authored recipe |
| `ghostcursor/perception/uia.py` | *(modify)* add `iter_elements()` exposing automation_id |
| `tests/uia_app.py` | Synthetic Win32 app with known AutomationIds, for grounding tests |
| `tests/test_schema.py` | Schema validation and round-trip |
| `tests/test_grounding.py` | Each rung, promotion, locale scoping |
| `tests/test_verification.py` | Each verification rule kind |
| `tests/test_loop.py` | State transitions, pure, no UI |
| `tests/test_guided_tour.py` | End-to-end tour against the synthetic app |

**Test runner:** new tests use pytest (`python -m pytest tests/test_x.py -v`). The two existing pixel harnesses keep their bespoke runner — they assert against the whole desktop and use exit code 2 for "environment unavailable".

---

### Task 1: Synthetic UIA test app

Everything downstream grounds against this. Build it first so no later task is blocked on a real application being open.

**Files:**
- Create: `tests/uia_app.py`
- Test: `tests/test_uia_app.py`

**Interfaces:**
- Consumes: `ghostcursor.overlay.dpi` (DPI awareness at import)
- Produces:
  - `SyntheticApp(title: str = "GhostCursorTestApp", locale: str = "en-US")` context manager
  - `SyntheticApp.hwnd -> int`
  - `SyntheticApp.pump() -> None`
  - `SyntheticApp.click_button(control_id: int) -> None` — simulates the *app's own* state change, used by tests to stand in for the user having acted. This is the test harness moving its own window's state, never input synthesis against another app.
  - Control IDs: `BTN_EXPORT = 1001`, `BTN_DELETE = 1002`, `BTN_CANCEL = 1003`, `EDIT_FILENAME = 1004`, `LBL_STATUS = 1005`
  - `LOCALIZED_NAMES: dict[str, dict[int, str]]` — `{"en-US": {1001: "Export", ...}, "hi-IN": {1001: "निर्यात", ...}}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_uia_app.py
from pywinauto import Desktop

from tests.uia_app import BTN_DELETE, BTN_EXPORT, SyntheticApp


def _elements(title):
    win = Desktop(backend="uia").window(title_re=f".*{title}.*")
    win.wait("exists", timeout=5)
    return {
        c.element_info.automation_id: (c.window_text(), c.element_info.control_type)
        for c in win.descendants()
        if c.element_info.automation_id
    }


def test_buttons_expose_automation_ids_and_names():
    with SyntheticApp() as app:
        app.pump()
        found = _elements(app.title)
    assert found[str(BTN_EXPORT)] == ("Export", "Button")
    assert found[str(BTN_DELETE)] == ("Delete", "Button")


def test_locale_changes_names_but_not_automation_ids():
    with SyntheticApp(title="GhostCursorTestAppHi", locale="hi-IN") as app:
        app.pump()
        found = _elements(app.title)
    assert found[str(BTN_EXPORT)][0] == "निर्यात"
    assert found[str(BTN_EXPORT)][1] == "Button"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_uia_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tests.uia_app'`

- [ ] **Step 3: Write minimal implementation**

```python
# tests/uia_app.py
"""A real Win32 window with known AutomationIds, used as a grounding target.

Grounding tests need an application whose element identities we control
exactly. Using a real app (Notepad, Chrome) makes tests depend on that app's
version and UI language. This gives us both, deterministically: the same
control IDs under any locale, with different display names.

Win32 controls expose their integer control ID as the UIA AutomationId, which
is what makes rung 1 of the grounding ladder testable here.
"""

import win32api
import win32con
import win32gui

from ghostcursor.overlay import dpi  # noqa: F401  declares DPI awareness first

BTN_EXPORT = 1001
BTN_DELETE = 1002
BTN_CANCEL = 1003
EDIT_FILENAME = 1004
LBL_STATUS = 1005

LOCALIZED_NAMES = {
    "en-US": {
        BTN_EXPORT: "Export",
        BTN_DELETE: "Delete",
        BTN_CANCEL: "Cancel",
        LBL_STATUS: "Ready",
    },
    "hi-IN": {
        BTN_EXPORT: "निर्यात",
        BTN_DELETE: "हटाएं",
        BTN_CANCEL: "रद्द करें",
        LBL_STATUS: "तैयार",
    },
}

_LAYOUT = {
    BTN_EXPORT: (30, 40, 140, 34),
    BTN_DELETE: (30, 90, 140, 34),
    BTN_CANCEL: (30, 140, 140, 34),
    EDIT_FILENAME: (200, 40, 180, 28),
    LBL_STATUS: (200, 90, 180, 28),
}

_registered: set[str] = set()


class SyntheticApp:
    """Context manager owning a real top-level window and its child controls."""

    def __init__(self, title: str = "GhostCursorTestApp", locale: str = "en-US"):
        self.title = title
        self.locale = locale
        self.hwnd: int | None = None
        self._children: dict[int, int] = {}

    def __enter__(self) -> "SyntheticApp":
        h_instance = win32api.GetModuleHandle(None)
        class_name = f"GhostCursorSynthetic_{self.title}"

        if class_name not in _registered:
            wnd_class = win32gui.WNDCLASS()
            wnd_class.lpfnWndProc = win32gui.DefWindowProc
            wnd_class.hInstance = h_instance
            wnd_class.lpszClassName = class_name
            wnd_class.hbrBackground = win32gui.GetStockObject(win32con.WHITE_BRUSH)
            win32gui.RegisterClass(wnd_class)
            _registered.add(class_name)

        self.hwnd = win32gui.CreateWindowEx(
            win32con.WS_EX_TOOLWINDOW,
            class_name,
            self.title,
            win32con.WS_OVERLAPPEDWINDOW,
            200, 200, 420, 260,
            None, None, h_instance, None,
        )

        names = LOCALIZED_NAMES[self.locale]
        for control_id, (x, y, w, h) in _LAYOUT.items():
            if control_id == EDIT_FILENAME:
                cls, style, text = "EDIT", win32con.WS_BORDER, ""
            elif control_id == LBL_STATUS:
                cls, style, text = "STATIC", 0, names[control_id]
            else:
                cls, style, text = "BUTTON", win32con.BS_PUSHBUTTON, names[control_id]

            self._children[control_id] = win32gui.CreateWindowEx(
                0, cls, text,
                win32con.WS_CHILD | win32con.WS_VISIBLE | style,
                x, y, w, h, self.hwnd, control_id, h_instance, None,
            )

        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNOACTIVATE)
        win32gui.UpdateWindow(self.hwnd)
        self.pump()
        return self

    def __exit__(self, *exc) -> None:
        if self.hwnd:
            win32gui.DestroyWindow(self.hwnd)
            self.pump()
        self.hwnd = None

    def pump(self) -> None:
        win32gui.PumpWaitingMessages()

    def set_status(self, text: str) -> None:
        """Change the status label — how tests simulate the app reacting."""
        win32gui.SetWindowText(self._children[LBL_STATUS], text)
        self.pump()

    def hide_control(self, control_id: int) -> None:
        win32gui.ShowWindow(self._children[control_id], win32con.SW_HIDE)
        self.pump()

    def show_control(self, control_id: int) -> None:
        win32gui.ShowWindow(self._children[control_id], win32con.SW_SHOW)
        self.pump()

    def click_button(self, control_id: int) -> None:
        """Stand-in for 'the user clicked this'. Mutates only this test
        window's own state — never synthesises input to another application."""
        self.set_status(f"clicked:{control_id}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_uia_app.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add tests/uia_app.py tests/test_uia_app.py
git commit -m "test: add synthetic UIA app with known AutomationIds"
```

---

### Task 2: Freeze the step contract

**Files:**
- Create: `ghostcursor/reasoning/schema.py`
- Test: `tests/test_schema.py`

**Interfaces:**
- Produces:
  - `UserAction`, `Risk`, `VerificationKind` — str enums
  - `ClaimedDescriptor(name, name_synonyms, ocr_text, visual_description)`
  - `ConfirmedObservation(app_version, locales_observed, automation_id, control_type, accessibility_path_hint, last_seen_at)`
  - `TargetDescriptor(claimed, confirmed)`
  - `VerificationRule(kind, args, timeout_s)`
  - `Step(user_action, target_descriptor, instruction_text, verification_rule, risk, preconditions, provenance)`
  - `Recipe(app_id, intent, steps)`
  - `validate_step(step: Step) -> list[str]` — human-readable errors, empty when valid
  - `Recipe.to_dict()` / `Recipe.from_dict(d)` / `Recipe.load(path)` / `Recipe.save(path)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schema.py
import pytest

from ghostcursor.reasoning.schema import (
    ClaimedDescriptor,
    Recipe,
    Risk,
    Step,
    TargetDescriptor,
    UserAction,
    VerificationKind,
    VerificationRule,
    validate_step,
)


def _step(**overrides):
    base = dict(
        user_action=UserAction.CLICK,
        target_descriptor=TargetDescriptor(
            claimed=ClaimedDescriptor(name="Export", name_synonyms=["Export As"]),
        ),
        instruction_text="Click Export.",
        verification_rule=VerificationRule(
            kind=VerificationKind.ELEMENT_APPEARS,
            args={"target_descriptor": {"name": "Save"}},
        ),
        risk=Risk.NORMAL,
    )
    base.update(overrides)
    return Step(**base)


def test_valid_step_has_no_errors():
    assert validate_step(_step()) == []


def test_elevated_risk_cannot_use_any_meaningful_change():
    step = _step(
        risk=Risk.ELEVATED,
        verification_rule=VerificationRule(
            kind=VerificationKind.ANY_MEANINGFUL_CHANGE, args={"scope": {}}
        ),
    )
    errors = validate_step(step)
    assert any("elevated" in e for e in errors)


def test_normal_risk_may_use_any_meaningful_change():
    step = _step(
        verification_rule=VerificationRule(
            kind=VerificationKind.ANY_MEANINGFUL_CHANGE, args={"scope": {}}
        )
    )
    assert validate_step(step) == []


def test_element_appears_requires_target_descriptor_arg():
    step = _step(
        verification_rule=VerificationRule(
            kind=VerificationKind.ELEMENT_APPEARS, args={}
        )
    )
    assert any("target_descriptor" in e for e in validate_step(step))


def test_window_title_matches_requires_pattern_arg():
    step = _step(
        verification_rule=VerificationRule(
            kind=VerificationKind.WINDOW_TITLE_MATCHES, args={}
        )
    )
    assert any("pattern" in e for e in validate_step(step))


def test_step_with_no_claimed_identity_is_rejected():
    step = _step(target_descriptor=TargetDescriptor(claimed=ClaimedDescriptor()))
    assert any("identify" in e for e in validate_step(step))


def test_observe_step_needs_no_target():
    step = _step(
        user_action=UserAction.OBSERVE,
        target_descriptor=TargetDescriptor(claimed=ClaimedDescriptor()),
        verification_rule=VerificationRule(kind=VerificationKind.USER_CONFIRMS, args={}),
    )
    assert validate_step(step) == []


def test_recipe_round_trips_through_json(tmp_path):
    recipe = Recipe(app_id="notepad", intent="export a file", steps=[_step()])
    path = tmp_path / "r.json"
    recipe.save(path)
    loaded = Recipe.load(path)
    assert loaded == recipe
    assert loaded.steps[0].target_descriptor.claimed.name == "Export"


def test_recipe_rejects_a_step_that_stores_coordinates():
    with pytest.raises(ValueError, match="coordinates"):
        Recipe.from_dict(
            {
                "app_id": "notepad",
                "intent": "x",
                "steps": [{**_step().to_dict(), "bbox": [1, 2, 3, 4]}],
            }
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostcursor.reasoning.schema'`

- [ ] **Step 3: Write minimal implementation**

```python
# ghostcursor/reasoning/schema.py
"""The step contract — the interface between recipe producers and the loop.

Frozen deliberately: the knowledge base (later) and the reasoning loop (now)
are built against this and nothing else, so they can evolve independently.

See docs/superpowers/specs/2026-08-14-reasoning-and-knowledge-design.md §4.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

# Keys that must never appear in a serialised step. Recipes describe intent;
# coordinates are resolved live on every render, because a persisted pixel is
# wrong the moment the window moves.
_FORBIDDEN_KEYS = {"bbox", "x", "y", "coordinates", "rect", "point"}


class UserAction(str, Enum):
    """What to ask the *human* to do. Never what this program does — the
    system draws hints and never acts (D006)."""

    CLICK = "click"
    PRESS_KEYS = "press_keys"
    TYPE = "type"
    DRAG = "drag"
    SELECT = "select"
    SCROLL = "scroll"
    OBSERVE = "observe"
    WAIT = "wait"


class Risk(str, Enum):
    NORMAL = "normal"
    ELEVATED = "elevated"  # destructive or hard to undo


class VerificationKind(str, Enum):
    ELEMENT_APPEARS = "element_appears"
    ELEMENT_DISAPPEARS = "element_disappears"
    WINDOW_TITLE_MATCHES = "window_title_matches"
    FOCUS_MOVES_TO = "focus_moves_to"
    PROPERTY_CHANGES = "property_changes"
    ANY_MEANINGFUL_CHANGE = "any_meaningful_change"
    USER_CONFIRMS = "user_confirms"


#: Actions that point at a UI element and therefore need something to ground.
_TARGETED_ACTIONS = {
    UserAction.CLICK,
    UserAction.TYPE,
    UserAction.DRAG,
    UserAction.SELECT,
    UserAction.SCROLL,
}

_REQUIRED_ARGS = {
    VerificationKind.ELEMENT_APPEARS: ("target_descriptor",),
    VerificationKind.ELEMENT_DISAPPEARS: ("target_descriptor",),
    VerificationKind.WINDOW_TITLE_MATCHES: ("pattern",),
    VerificationKind.FOCUS_MOVES_TO: ("target_descriptor",),
    VerificationKind.PROPERTY_CHANGES: ("target_descriptor", "property"),
    VerificationKind.ANY_MEANINGFUL_CHANGE: ("scope",),
    VerificationKind.USER_CONFIRMS: (),
}


@dataclass
class ClaimedDescriptor:
    """What documentation can tell us. A guess: may be wrong, may be for a
    different UI language."""

    name: str | None = None
    name_synonyms: list[str] = field(default_factory=list)
    ocr_text: str | None = None
    visual_description: str | None = None

    def is_empty(self) -> bool:
        return not (self.name or self.name_synonyms or self.ocr_text)


@dataclass
class ConfirmedObservation:
    """What we learned by grounding successfully. Written at runtime, never by
    distillation — no tutorial ever names an AutomationId."""

    app_version: str
    locales_observed: list[str] = field(default_factory=list)
    automation_id: str | None = None
    control_type: str | None = None
    #: Tie-breaker between otherwise-equal matches only. Never identity —
    #: a tree path breaks whenever layout changes.
    accessibility_path_hint: list[str] = field(default_factory=list)
    last_seen_at: str | None = None


@dataclass
class TargetDescriptor:
    claimed: ClaimedDescriptor = field(default_factory=ClaimedDescriptor)
    confirmed: list[ConfirmedObservation] = field(default_factory=list)


@dataclass
class VerificationRule:
    kind: VerificationKind
    args: dict = field(default_factory=dict)
    timeout_s: float = 30.0


@dataclass
class Step:
    user_action: UserAction
    target_descriptor: TargetDescriptor
    instruction_text: str
    verification_rule: VerificationRule
    risk: Risk = Risk.NORMAL
    preconditions: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Recipe:
    app_id: str
    intent: str
    steps: list[Step]

    def to_dict(self) -> dict:
        return {
            "app_id": self.app_id,
            "intent": self.intent,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Recipe":
        steps = []
        for raw in data["steps"]:
            leaked = _FORBIDDEN_KEYS & set(raw)
            if leaked:
                raise ValueError(
                    f"step stores coordinates {sorted(leaked)}; recipes store "
                    "intent only, coordinates are resolved live"
                )
            steps.append(_step_from_dict(raw))
        return cls(app_id=data["app_id"], intent=data["intent"], steps=steps)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: str | Path) -> "Recipe":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _step_from_dict(raw: dict) -> Step:
    td = raw["target_descriptor"]
    return Step(
        user_action=UserAction(raw["user_action"]),
        target_descriptor=TargetDescriptor(
            claimed=ClaimedDescriptor(**td.get("claimed", {})),
            confirmed=[ConfirmedObservation(**c) for c in td.get("confirmed", [])],
        ),
        instruction_text=raw["instruction_text"],
        verification_rule=VerificationRule(
            kind=VerificationKind(raw["verification_rule"]["kind"]),
            args=raw["verification_rule"].get("args", {}),
            timeout_s=raw["verification_rule"].get("timeout_s", 30.0),
        ),
        risk=Risk(raw.get("risk", "normal")),
        preconditions=raw.get("preconditions", []),
        provenance=raw.get("provenance", {}),
    )


def validate_step(step: Step) -> list[str]:
    """Return human-readable problems with a step. Empty means valid."""
    errors: list[str] = []
    rule = step.verification_rule

    # Spec §7: any_meaningful_change fires on unrelated activity, so it must
    # never be what declares a destructive step complete.
    if step.risk is Risk.ELEVATED and rule.kind is VerificationKind.ANY_MEANINGFUL_CHANGE:
        errors.append(
            "elevated-risk step cannot be verified by any_meaningful_change; "
            "use an element-level rule or user_confirms"
        )

    for required in _REQUIRED_ARGS[rule.kind]:
        if required not in rule.args:
            errors.append(f"verification rule {rule.kind.value} requires arg {required!r}")

    if step.user_action in _TARGETED_ACTIONS and step.target_descriptor.claimed.is_empty():
        if not step.target_descriptor.confirmed:
            errors.append(
                f"{step.user_action.value} step has nothing to identify its target with"
            )

    if not step.instruction_text.strip():
        errors.append("step has no instruction_text to show the user")

    return errors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_schema.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add ghostcursor/reasoning/schema.py tests/test_schema.py
git commit -m "feat: freeze the step contract"
```

---

### Task 3: Expose element details from the perception layer

The grounding ladder needs `automation_id`, which `uia.py` does not currently return.

**Files:**
- Modify: `ghostcursor/perception/uia.py`
- Test: `tests/test_uia_elements.py`

**Interfaces:**
- Consumes: `uia.is_on_screen` (exists)
- Produces:
  - `Element(name: str, control_type: str, automation_id: str, bbox: tuple[int,int,int,int], path: list[str])`
  - `iter_elements(title_re: str) -> list[Element]` — on-screen elements only

- [ ] **Step 1: Write the failing test**

```python
# tests/test_uia_elements.py
from ghostcursor.perception.uia import iter_elements
from tests.uia_app import BTN_EXPORT, SyntheticApp


def test_iter_elements_exposes_automation_id_and_bbox():
    with SyntheticApp() as app:
        elements = iter_elements(f".*{app.title}.*")

    export = next(e for e in elements if e.automation_id == str(BTN_EXPORT))
    assert export.name == "Export"
    assert export.control_type == "Button"
    left, top, right, bottom = export.bbox
    assert right > left and bottom > top


def test_iter_elements_skips_offscreen_elements():
    with SyntheticApp() as app:
        elements = iter_elements(f".*{app.title}.*")
    # Window chrome buttons report (0,0,0,0); is_on_screen must filter them.
    assert all(e.bbox != (0, 0, 0, 0) for e in elements)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_uia_elements.py -v`
Expected: FAIL with `ImportError: cannot import name 'iter_elements'`

- [ ] **Step 3: Write minimal implementation**

Append to `ghostcursor/perception/uia.py`:

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Element:
    """One on-screen UI element, normalised across perception tiers."""

    name: str
    control_type: str
    automation_id: str
    bbox: tuple[int, int, int, int]
    path: tuple[str, ...] = field(default=())


def iter_elements(title_re: str) -> list[Element]:
    """Every on-screen element inside the window matching title_re.

    Off-screen and degenerate elements are filtered out — window chrome
    frequently reports (0, 0, 0, 0), which would otherwise ground a hint into
    the corner of the desktop.
    """
    try:
        window = Desktop(backend="uia").window(title_re=title_re)
        window.wait("exists", timeout=3)
        descendants = window.descendants()
    except Exception:
        return []

    elements: list[Element] = []
    for ctrl in descendants:
        try:
            rect = ctrl.rectangle()
            bbox = (rect.left, rect.top, rect.right, rect.bottom)
            if not is_on_screen(bbox):
                continue
            info = ctrl.element_info
            elements.append(
                Element(
                    name=ctrl.window_text() or "",
                    control_type=info.control_type or "",
                    automation_id=info.automation_id or "",
                    bbox=bbox,
                    path=(info.control_type or "",),
                )
            )
        except Exception:
            continue  # elements can vanish mid-enumeration
    return elements
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_uia_elements.py -v`
Expected: 2 passed

- [ ] **Step 5: Verify nothing regressed, then commit**

```bash
python -m tests.test_overlay && python -m tests.test_end_to_end
git add ghostcursor/perception/uia.py tests/test_uia_elements.py
git commit -m "feat: expose element automation ids from perception layer"
```

---

### Task 4: Grounding ladder, rungs 1–3

**Files:**
- Create: `ghostcursor/reasoning/grounding.py`
- Test: `tests/test_grounding.py`

**Interfaces:**
- Consumes: `uia.iter_elements`, `schema.Step`, `schema.TargetDescriptor`
- Produces:
  - `GroundedTarget(bbox, rung, automation_id, control_type, name)`
  - `ground(step: Step, title_re: str, locale: str = "en-US", elements: list[Element] | None = None) -> GroundedTarget | None`
  - `RUNG_AUTOMATION_ID = 1`, `RUNG_TYPE_AND_NAME = 2`, `RUNG_FUZZY_NAME = 3`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_grounding.py
from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.grounding import (
    RUNG_AUTOMATION_ID,
    RUNG_FUZZY_NAME,
    RUNG_TYPE_AND_NAME,
    ground,
)
from ghostcursor.reasoning.schema import (
    ClaimedDescriptor,
    ConfirmedObservation,
    Risk,
    Step,
    TargetDescriptor,
    UserAction,
    VerificationKind,
    VerificationRule,
)

ELEMENTS = [
    Element("Export", "Button", "1001", (10, 10, 110, 40)),
    Element("Delete", "Button", "1002", (10, 50, 110, 80)),
    Element("", "Edit", "1004", (200, 10, 300, 40)),
]


def _step(claimed=None, confirmed=None):
    return Step(
        user_action=UserAction.CLICK,
        target_descriptor=TargetDescriptor(
            claimed=claimed or ClaimedDescriptor(name="Export"),
            confirmed=confirmed or [],
        ),
        instruction_text="Click Export.",
        verification_rule=VerificationRule(kind=VerificationKind.USER_CONFIRMS),
        risk=Risk.NORMAL,
    )


def test_rung1_prefers_confirmed_automation_id():
    step = _step(
        claimed=ClaimedDescriptor(name="WrongName"),
        confirmed=[ConfirmedObservation(app_version="1.0", automation_id="1001")],
    )
    result = ground(step, ".*", elements=ELEMENTS)
    assert result.rung == RUNG_AUTOMATION_ID
    assert result.bbox == (10, 10, 110, 40)


def test_rung1_ignores_locale_mismatch():
    # AutomationId is language-independent: an observation recorded in en-US
    # must still ground for a hi-IN user, or promotion is pointless.
    step = _step(
        claimed=ClaimedDescriptor(name="Export"),
        confirmed=[
            ConfirmedObservation(
                app_version="1.0", automation_id="1001", locales_observed=["en-US"]
            )
        ],
    )
    result = ground(step, ".*", locale="hi-IN", elements=ELEMENTS)
    assert result.rung == RUNG_AUTOMATION_ID


def test_rung2_matches_control_type_and_exact_name():
    step = _step(claimed=ClaimedDescriptor(name="Delete"))
    result = ground(step, ".*", elements=ELEMENTS)
    assert result.rung == RUNG_TYPE_AND_NAME
    assert result.automation_id == "1002"


def test_rung3_matches_a_synonym():
    step = _step(claimed=ClaimedDescriptor(name="Save As", name_synonyms=["Export"]))
    result = ground(step, ".*", elements=ELEMENTS)
    assert result.rung == RUNG_FUZZY_NAME
    assert result.automation_id == "1001"


def test_returns_none_when_nothing_matches():
    step = _step(claimed=ClaimedDescriptor(name="Nonexistent"))
    assert ground(step, ".*", elements=ELEMENTS) is None


def test_path_hint_disambiguates_equal_matches():
    duplicates = [
        Element("Delete", "Button", "2001", (0, 0, 10, 10), path=("ToolBar",)),
        Element("Delete", "Button", "2002", (50, 0, 60, 10), path=("Dialog",)),
    ]
    step = _step(
        claimed=ClaimedDescriptor(name="Delete"),
        confirmed=[
            ConfirmedObservation(
                app_version="1.0", accessibility_path_hint=["Dialog"]
            )
        ],
    )
    result = ground(step, ".*", elements=duplicates)
    assert result.automation_id == "2002"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_grounding.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostcursor.reasoning.grounding'`

- [ ] **Step 3: Write minimal implementation**

```python
# ghostcursor/reasoning/grounding.py
"""Turn a step's description of a target into a live screen rectangle.

Cheapest and most stable matcher first, mirroring the perception ladder
(DECISIONS.md D005). See spec §5.

    rung 1  confirmed automation_id   survives renames AND translation
    rung 2  control_type + exact name
    rung 3  fuzzy name / synonyms

Rungs 2-3 match on displayed text and are therefore locale-scoped. Rung 1 is
language-independent by construction and must never be filtered by locale —
doing so would defeat the promotion mechanism it exists to enable.

Scope note for this milestone: `locale` is threaded through but does not
filter live matching, and that is correct rather than incomplete. The live UI
renders in whatever language the app is running in, so rungs 2-3 match the
text actually on screen — there is nothing to filter against. Locale becomes
load-bearing when *selecting between stored observations and recipe variants*,
which is knowledge-base territory (spec sections 8-10) and deliberately out of
scope here. The parameter exists now so that `promote()` records which locale
an observation came from, which is the data that later selection will need.
"""

from __future__ import annotations

from dataclasses import dataclass

from ghostcursor.perception.uia import Element, iter_elements
from ghostcursor.reasoning.schema import Step

RUNG_AUTOMATION_ID = 1
RUNG_TYPE_AND_NAME = 2
RUNG_FUZZY_NAME = 3


@dataclass(frozen=True)
class GroundedTarget:
    bbox: tuple[int, int, int, int]
    rung: int
    automation_id: str
    control_type: str
    name: str


def _as_target(element: Element, rung: int) -> GroundedTarget:
    return GroundedTarget(
        bbox=element.bbox,
        rung=rung,
        automation_id=element.automation_id,
        control_type=element.control_type,
        name=element.name,
    )


def _disambiguate(
    matches: list[Element], step: Step
) -> Element:
    """Pick between equally-good matches using the path hint.

    The hint is a tie-breaker only — never identity — because a tree path
    breaks whenever layout changes.
    """
    if len(matches) == 1:
        return matches[0]
    hints = {
        segment
        for obs in step.target_descriptor.confirmed
        for segment in obs.accessibility_path_hint
    }
    if hints:
        for element in matches:
            if hints & set(element.path):
                return element
    return matches[0]


def ground(
    step: Step,
    title_re: str,
    locale: str = "en-US",
    elements: list[Element] | None = None,
) -> GroundedTarget | None:
    """Resolve step's target to a live rectangle, or None if not found."""
    if elements is None:
        elements = iter_elements(title_re)
    if not elements:
        return None

    claimed = step.target_descriptor.claimed

    # Rung 1 — confirmed AutomationId. Locale-independent on purpose.
    known_ids = {
        obs.automation_id
        for obs in step.target_descriptor.confirmed
        if obs.automation_id
    }
    if known_ids:
        matches = [e for e in elements if e.automation_id in known_ids]
        if matches:
            return _as_target(_disambiguate(matches, step), RUNG_AUTOMATION_ID)

    # Rung 2 — control type plus exact displayed name.
    wanted_type = next(
        (obs.control_type for obs in step.target_descriptor.confirmed if obs.control_type),
        None,
    )
    if claimed.name:
        matches = [
            e
            for e in elements
            if e.name == claimed.name
            and (wanted_type is None or e.control_type == wanted_type)
        ]
        if matches:
            return _as_target(_disambiguate(matches, step), RUNG_TYPE_AND_NAME)

    # Rung 3 — synonyms and case-insensitive substring.
    candidates = [claimed.name, *claimed.name_synonyms]
    for candidate in filter(None, candidates):
        needle = candidate.casefold()
        matches = [
            e for e in elements if e.name and needle in e.name.casefold()
        ]
        if matches:
            return _as_target(_disambiguate(matches, step), RUNG_FUZZY_NAME)

    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_grounding.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add ghostcursor/reasoning/grounding.py tests/test_grounding.py
git commit -m "feat: add grounding ladder rungs 1-3"
```

---

### Task 5: Promotion — learn the AutomationId and write it back

This is what makes recipes get stronger with use, and what makes them survive translation.

**Files:**
- Modify: `ghostcursor/reasoning/grounding.py`
- Test: `tests/test_promotion.py`

**Interfaces:**
- Produces: `promote(step: Step, grounded: GroundedTarget, app_version: str, locale: str) -> bool` — True when the step was modified

- [ ] **Step 1: Write the failing test**

```python
# tests/test_promotion.py
from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.grounding import (
    RUNG_AUTOMATION_ID,
    ground,
    promote,
)
from ghostcursor.reasoning.schema import (
    ClaimedDescriptor,
    Risk,
    Step,
    TargetDescriptor,
    UserAction,
    VerificationKind,
    VerificationRule,
)

EN = [Element("Export", "Button", "1001", (10, 10, 110, 40))]
HI = [Element("निर्यात", "Button", "1001", (10, 10, 110, 40))]


def _step():
    return Step(
        user_action=UserAction.CLICK,
        target_descriptor=TargetDescriptor(claimed=ClaimedDescriptor(name="Export")),
        instruction_text="Click Export.",
        verification_rule=VerificationRule(kind=VerificationKind.USER_CONFIRMS),
        risk=Risk.NORMAL,
    )


def test_promotion_records_the_discovered_automation_id():
    step = _step()
    grounded = ground(step, ".*", elements=EN)
    assert promote(step, grounded, app_version="1.2.7", locale="en-US") is True

    observation = step.target_descriptor.confirmed[0]
    assert observation.automation_id == "1001"
    assert observation.control_type == "Button"
    assert observation.app_version == "1.2.7"
    assert observation.locales_observed == ["en-US"]
    assert observation.last_seen_at is not None


def test_promoted_step_grounds_on_rung_1_next_time():
    step = _step()
    promote(step, ground(step, ".*", elements=EN), "1.2.7", "en-US")
    assert ground(step, ".*", elements=EN).rung == RUNG_AUTOMATION_ID


def test_english_promotion_grounds_for_a_hindi_user():
    # The whole point: the Hindi UI shows a different name, same AutomationId.
    step = _step()
    promote(step, ground(step, ".*", elements=EN), "1.2.7", "en-US")

    result = ground(step, ".*", locale="hi-IN", elements=HI)
    assert result is not None
    assert result.rung == RUNG_AUTOMATION_ID


def test_second_locale_is_appended_not_duplicated():
    step = _step()
    promote(step, ground(step, ".*", elements=EN), "1.2.7", "en-US")
    promote(step, ground(step, ".*", elements=HI), "1.2.7", "hi-IN")

    assert len(step.target_descriptor.confirmed) == 1
    assert step.target_descriptor.confirmed[0].locales_observed == ["en-US", "hi-IN"]


def test_a_new_app_version_creates_a_separate_observation():
    step = _step()
    promote(step, ground(step, ".*", elements=EN), "1.2.7", "en-US")
    promote(step, ground(step, ".*", elements=EN), "2.0.0", "en-US")

    versions = {o.app_version for o in step.target_descriptor.confirmed}
    assert versions == {"1.2.7", "2.0.0"}


def test_promotion_is_a_noop_without_an_automation_id():
    step = _step()
    anonymous = [Element("Export", "Button", "", (10, 10, 110, 40))]
    assert promote(step, ground(step, ".*", elements=anonymous), "1.0", "en-US") is False
    assert step.target_descriptor.confirmed == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_promotion.py -v`
Expected: FAIL with `ImportError: cannot import name 'promote'`

- [ ] **Step 3: Write minimal implementation**

Append to `ghostcursor/reasoning/grounding.py`:

```python
from datetime import datetime, timezone

from ghostcursor.reasoning.schema import ConfirmedObservation


def promote(
    step: Step,
    grounded: GroundedTarget | None,
    app_version: str,
    locale: str,
) -> bool:
    """Record what grounding just learned, so later runs use rung 1.

    Documentation cannot supply an AutomationId — no tutorial has ever named
    one — so the only way to get it is to observe the real application. This
    is what makes a recipe more robust every time it is used, and what lets a
    recipe confirmed by an English user ground for a Hindi one.

    Returns True when the step was modified.
    """
    if grounded is None or not grounded.automation_id:
        return False

    for observation in step.target_descriptor.confirmed:
        if (
            observation.app_version == app_version
            and observation.automation_id == grounded.automation_id
        ):
            if locale not in observation.locales_observed:
                observation.locales_observed.append(locale)
            observation.last_seen_at = _now()
            return True

    step.target_descriptor.confirmed.append(
        ConfirmedObservation(
            app_version=app_version,
            locales_observed=[locale],
            automation_id=grounded.automation_id,
            control_type=grounded.control_type,
            accessibility_path_hint=[],
            last_seen_at=_now(),
        )
    )
    return True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_promotion.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add ghostcursor/reasoning/grounding.py tests/test_promotion.py
git commit -m "feat: promote learned automation ids into step descriptors"
```

---

### Task 6: Verification rules

**Files:**
- Create: `ghostcursor/reasoning/verification.py`
- Test: `tests/test_verification.py`

**Interfaces:**
- Consumes: `uia.iter_elements`, `schema.VerificationRule`, `schema.VerificationKind`
- Produces:
  - `Snapshot(title: str, elements: tuple[Element, ...], focused_automation_id: str)`
  - `take_snapshot(title_re: str) -> Snapshot`
  - `verify(rule: VerificationRule, before: Snapshot, after: Snapshot) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_verification.py
from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.schema import VerificationKind, VerificationRule
from ghostcursor.reasoning.verification import Snapshot, verify

A = Element("Export", "Button", "1001", (10, 10, 110, 40))
B = Element("Save", "Button", "1002", (10, 50, 110, 80))


def snap(title="App", elements=(A,), focus=""):
    return Snapshot(title=title, elements=tuple(elements), focused_automation_id=focus)


def test_element_appears_detects_a_new_element():
    rule = VerificationRule(
        kind=VerificationKind.ELEMENT_APPEARS,
        args={"target_descriptor": {"name": "Save"}},
    )
    assert verify(rule, snap(elements=(A,)), snap(elements=(A, B))) is True


def test_element_appears_is_false_when_nothing_changed():
    rule = VerificationRule(
        kind=VerificationKind.ELEMENT_APPEARS,
        args={"target_descriptor": {"name": "Save"}},
    )
    assert verify(rule, snap(), snap()) is False


def test_element_disappears():
    rule = VerificationRule(
        kind=VerificationKind.ELEMENT_DISAPPEARS,
        args={"target_descriptor": {"automation_id": "1001"}},
    )
    assert verify(rule, snap(elements=(A, B)), snap(elements=(B,))) is True


def test_window_title_matches():
    rule = VerificationRule(
        kind=VerificationKind.WINDOW_TITLE_MATCHES, args={"pattern": r".*Saved.*"}
    )
    assert verify(rule, snap(title="App"), snap(title="App - Saved")) is True
    assert verify(rule, snap(title="App"), snap(title="App")) is False


def test_focus_moves_to():
    rule = VerificationRule(
        kind=VerificationKind.FOCUS_MOVES_TO,
        args={"target_descriptor": {"automation_id": "1002"}},
    )
    assert verify(rule, snap(focus="1001"), snap(focus="1002")) is True
    assert verify(rule, snap(focus="1001"), snap(focus="1001")) is False


def test_property_changes():
    changed = Element("Exported", "Button", "1001", (10, 10, 110, 40))
    rule = VerificationRule(
        kind=VerificationKind.PROPERTY_CHANGES,
        args={"target_descriptor": {"automation_id": "1001"}, "property": "name"},
    )
    assert verify(rule, snap(elements=(A,)), snap(elements=(changed,))) is True
    assert verify(rule, snap(elements=(A,)), snap(elements=(A,))) is False


def test_any_meaningful_change():
    rule = VerificationRule(
        kind=VerificationKind.ANY_MEANINGFUL_CHANGE, args={"scope": {}}
    )
    assert verify(rule, snap(elements=(A,)), snap(elements=(A, B))) is True
    assert verify(rule, snap(elements=(A,)), snap(elements=(A,))) is False


def test_any_meaningful_change_ignores_pure_movement():
    # A window being dragged is not the user completing a step.
    moved = Element("Export", "Button", "1001", (999, 999, 1099, 1029))
    rule = VerificationRule(
        kind=VerificationKind.ANY_MEANINGFUL_CHANGE, args={"scope": {}}
    )
    assert verify(rule, snap(elements=(A,)), snap(elements=(moved,))) is False


def test_user_confirms_is_never_satisfied_by_observation():
    # It is resolved by the user pressing a key, not by inspecting the screen.
    rule = VerificationRule(kind=VerificationKind.USER_CONFIRMS)
    assert verify(rule, snap(), snap(elements=(A, B))) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_verification.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostcursor.reasoning.verification'`

- [ ] **Step 3: Write minimal implementation**

```python
# ghostcursor/reasoning/verification.py
"""Decide whether the user actually completed a step.

Verification checks *world state, never the route taken* (spec §7). If the
recipe said "click File > Save" and the user pressed Ctrl+S, they achieved the
goal and verification must pass. Grading the method instead of the outcome
makes the teacher wrong exactly when the student is efficient.

This mirrors OSWorld's execution-based grading: inspect real state, don't
grade a transcript.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ghostcursor.perception.uia import Element, iter_elements
from ghostcursor.reasoning.schema import VerificationKind, VerificationRule


@dataclass(frozen=True)
class Snapshot:
    title: str
    elements: tuple[Element, ...]
    focused_automation_id: str = ""


def take_snapshot(title_re: str) -> Snapshot:
    import win32gui

    elements = tuple(iter_elements(title_re))
    try:
        title = win32gui.GetWindowText(win32gui.GetForegroundWindow())
    except Exception:
        title = ""
    return Snapshot(title=title, elements=elements, focused_automation_id="")


def _matches(element: Element, descriptor: dict) -> bool:
    if "automation_id" in descriptor:
        return element.automation_id == descriptor["automation_id"]
    if "name" in descriptor:
        return element.name == descriptor["name"]
    return False


def _find(snapshot: Snapshot, descriptor: dict) -> Element | None:
    return next((e for e in snapshot.elements if _matches(e, descriptor)), None)


def _identity(snapshot: Snapshot) -> set[tuple[str, str, str]]:
    """Which elements exist, ignoring position — moving a window is not
    progress."""
    return {(e.automation_id, e.name, e.control_type) for e in snapshot.elements}


def verify(rule: VerificationRule, before: Snapshot, after: Snapshot) -> bool:
    kind = rule.kind
    args = rule.args

    if kind is VerificationKind.USER_CONFIRMS:
        # Resolved by a keypress in the loop, never by looking at the screen.
        return False

    if kind is VerificationKind.ELEMENT_APPEARS:
        descriptor = args["target_descriptor"]
        return _find(before, descriptor) is None and _find(after, descriptor) is not None

    if kind is VerificationKind.ELEMENT_DISAPPEARS:
        descriptor = args["target_descriptor"]
        return _find(before, descriptor) is not None and _find(after, descriptor) is None

    if kind is VerificationKind.WINDOW_TITLE_MATCHES:
        return re.search(args["pattern"], after.title) is not None

    if kind is VerificationKind.FOCUS_MOVES_TO:
        wanted = args["target_descriptor"].get("automation_id")
        return (
            after.focused_automation_id == wanted
            and before.focused_automation_id != wanted
        )

    if kind is VerificationKind.PROPERTY_CHANGES:
        descriptor = args["target_descriptor"]
        prop = args["property"]
        old, new = _find(before, descriptor), _find(after, descriptor)
        if old is None or new is None:
            return False
        return getattr(old, prop) != getattr(new, prop)

    if kind is VerificationKind.ANY_MEANINGFUL_CHANGE:
        return _identity(before) != _identity(after)

    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_verification.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add ghostcursor/reasoning/verification.py tests/test_verification.py
git commit -m "feat: add state-based verification rules"
```

---

### Task 7: The state machine

Collaborators are injected, so every transition is testable with no UI at all.

**Files:**
- Create: `ghostcursor/reasoning/loop.py`
- Test: `tests/test_loop.py`

**Interfaces:**
- Consumes: `schema.Recipe`, `schema.Step`, `grounding.GroundedTarget`, `verification.Snapshot`
- Produces:
  - `State` enum: `IDLE, OBSERVING, DECIDING, RENDERING_HINT, AWAITING_USER_ACTION, VERIFYING, DONE, FAILED`
  - `GuidedTour(recipe, grounder, snapshotter, verifier, renderer, clock=time.monotonic, idle_timeout_s=30.0)`
  - `GuidedTour.tick() -> State`
  - `GuidedTour.state`, `.step_index`, `.confirm()` (satisfies a `user_confirms` step)
  - Collaborator signatures:
    - `grounder(step, step_index) -> GroundedTarget | None`
    - `snapshotter() -> Snapshot`
    - `verifier(rule, before, after) -> bool`
    - `renderer.show(grounded, instruction_text) -> None`, `renderer.clear() -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_loop.py
from ghostcursor.perception.uia import Element  # noqa: F401  used in CHANGED
from ghostcursor.reasoning.grounding import GroundedTarget
from ghostcursor.reasoning.loop import GuidedTour, State
from ghostcursor.reasoning.schema import (
    ClaimedDescriptor,
    Recipe,
    Risk,
    Step,
    TargetDescriptor,
    UserAction,
    VerificationKind,
    VerificationRule,
)
from ghostcursor.reasoning.verification import Snapshot

TARGET = GroundedTarget((10, 10, 110, 40), 1, "1001", "Button", "Export")


class FakeRenderer:
    def __init__(self):
        self.shown = []
        self.cleared = 0

    def show(self, grounded, instruction_text):
        self.shown.append((grounded, instruction_text))

    def clear(self):
        self.cleared += 1


def _step(kind=VerificationKind.ELEMENT_APPEARS, text="Click Export."):
    return Step(
        user_action=UserAction.CLICK,
        target_descriptor=TargetDescriptor(claimed=ClaimedDescriptor(name="Export")),
        instruction_text=text,
        verification_rule=VerificationRule(
            kind=kind, args={"target_descriptor": {"name": "Save"}}
        ),
        risk=Risk.NORMAL,
    )


STILL = Snapshot("App", ())
CHANGED = Snapshot("App", (Element("Dialog", "Window", "9001", (0, 0, 50, 50)),))


def _tour(steps=None, grounder=None, verifier=None, clock=None, snapshotter=None):
    recipe = Recipe(app_id="test", intent="t", steps=steps or [_step(), _step()])
    return GuidedTour(
        recipe=recipe,
        grounder=grounder or (lambda step, i: TARGET),
        snapshotter=snapshotter or (lambda: STILL),
        verifier=verifier or (lambda rule, before, after: True),
        renderer=FakeRenderer(),
        clock=clock or (lambda: 0.0),
    )


def test_reaches_awaiting_user_action_and_renders_the_hint():
    tour = _tour()
    for _ in range(4):
        tour.tick()
    assert tour.state is State.AWAITING_USER_ACTION
    assert tour.renderer.shown[0][1] == "Click Export."


def test_awaiting_is_a_dwelling_state_not_a_pass_through():
    # The user has not acted and nothing changed, so the tour must sit still.
    # Falling through to VERIFYING every tick is what previously made the
    # idle timer reset forever and the re-hint unreachable.
    tour = _tour(verifier=lambda rule, before, after: False)
    for _ in range(10):
        tour.tick()
    assert tour.state is State.AWAITING_USER_ACTION
    assert tour.step_index == 0
    assert len(tour.renderer.shown) == 1  # hint drawn once, not redrawn per tick


def test_successful_verification_advances_to_the_next_step():
    tour = _tour()
    for _ in range(6):
        tour.tick()
    assert tour.step_index == 1


def test_unexpected_change_reobserves_instead_of_advancing():
    # The user did something other than what was suggested. Re-plan from real
    # state rather than retrying a hint whose target may have moved.
    snaps = iter([STILL, CHANGED, CHANGED, CHANGED, CHANGED, CHANGED, CHANGED])
    tour = _tour(
        verifier=lambda rule, before, after: False,
        snapshotter=lambda: next(snaps, CHANGED),
    )
    for _ in range(5):
        tour.tick()
    assert tour.step_index == 0
    assert tour.state is State.OBSERVING


def test_completing_every_step_finishes_the_tour():
    tour = _tour(steps=[_step()])
    for _ in range(8):
        tour.tick()
    assert tour.state is State.DONE
    assert tour.renderer.cleared >= 1


def test_ungroundable_step_fails_rather_than_guessing():
    tour = _tour(grounder=lambda step, i: None)
    for _ in range(4):
        tour.tick()
    assert tour.state is State.FAILED


def test_user_confirms_step_waits_for_confirm():
    tour = _tour(steps=[_step(kind=VerificationKind.USER_CONFIRMS)],
                 verifier=lambda rule, before, after: False)
    for _ in range(5):
        tour.tick()
    assert tour.state is State.AWAITING_USER_ACTION

    tour.confirm()
    for _ in range(3):
        tour.tick()
    assert tour.state is State.DONE


def test_idle_timeout_rehints_once_then_goes_quiet():
    now = {"t": 0.0}
    tour = _tour(verifier=lambda rule, before, after: False, clock=lambda: now["t"])
    for _ in range(4):
        tour.tick()
    assert tour.state is State.AWAITING_USER_ACTION
    assert tour.rehint_count == 0

    now["t"] = 31.0
    tour.tick()
    assert tour.rehint_count == 1

    now["t"] = 62.0
    tour.tick()
    assert tour.rehint_count == 1  # never nags twice


def test_idle_timer_survives_a_reobserve_cycle():
    # Regression: re-entering RENDERING_HINT for the SAME step must not reset
    # the idle clock, or the timeout can never elapse in a real run.
    now = {"t": 0.0}
    snaps = iter([STILL, CHANGED])
    tour = _tour(
        verifier=lambda rule, before, after: False,
        clock=lambda: now["t"],
        snapshotter=lambda: next(snaps, CHANGED),
    )
    for _ in range(5):
        tour.tick()
    assert tour.state is State.OBSERVING  # unexpected change sent us back

    now["t"] = 31.0
    for _ in range(4):  # OBSERVING -> DECIDING -> RENDERING_HINT -> AWAITING
        tour.tick()
    assert tour.rehint_count == 1, "idle clock was reset by the re-observe cycle"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_loop.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostcursor.reasoning.loop'`

- [ ] **Step 3: Write minimal implementation**

```python
# ghostcursor/reasoning/loop.py
"""The observe-act-verify state machine (spec §6).

Not plain ReAct. ReAct's observe step is passive — read a tool result — and
assumes the agent's own action changed the world. Here the *user* acts, and
they can do something entirely different from what was suggested, so
VERIFYING is an active re-perception against a predicted post-condition, and a
failed verification re-plans from real state rather than retrying blindly.

Collaborators are injected so every transition is testable without a UI.
"""

from __future__ import annotations

import time
from enum import Enum, auto
from typing import Callable, Protocol

from ghostcursor.reasoning.grounding import GroundedTarget
from ghostcursor.reasoning.schema import Recipe, Step, VerificationKind
from ghostcursor.reasoning.verification import Snapshot


class State(Enum):
    IDLE = auto()
    OBSERVING = auto()
    DECIDING = auto()
    RENDERING_HINT = auto()
    AWAITING_USER_ACTION = auto()
    VERIFYING = auto()
    DONE = auto()
    FAILED = auto()


class Renderer(Protocol):
    def show(self, grounded: GroundedTarget, instruction_text: str) -> None: ...
    def clear(self) -> None: ...


class GuidedTour:
    def __init__(
        self,
        recipe: Recipe,
        grounder: Callable[[Step, int], GroundedTarget | None],
        snapshotter: Callable[[], Snapshot],
        verifier: Callable[..., bool],
        renderer: Renderer,
        clock: Callable[[], float] = time.monotonic,
        idle_timeout_s: float = 30.0,
    ) -> None:
        self.recipe = recipe
        self.grounder = grounder
        self.snapshotter = snapshotter
        self.verifier = verifier
        self.renderer = renderer
        self.clock = clock
        self.idle_timeout_s = idle_timeout_s

        self.state = State.IDLE
        self.step_index = 0
        self.rehint_count = 0
        self.failure_reason: str | None = None

        self._before: Snapshot | None = None
        self._grounded: GroundedTarget | None = None
        self._waiting_since = 0.0
        self._confirmed = False
        #: Which step the idle clock belongs to. Re-rendering the same step
        #: after a re-observe must NOT restart it, or the timeout can never
        #: elapse during a normal poll cycle.
        self._hint_step_index: int | None = None

    @property
    def current_step(self) -> Step | None:
        if self.step_index >= len(self.recipe.steps):
            return None
        return self.recipe.steps[self.step_index]

    def confirm(self) -> None:
        """The user pressed the confirm key for a user_confirms step."""
        self._confirmed = True

    def tick(self) -> State:
        if self.state in (State.DONE, State.FAILED):
            return self.state

        if self.state is State.IDLE:
            self.state = State.OBSERVING

        elif self.state is State.OBSERVING:
            if self.current_step is None:
                self.renderer.clear()
                self.state = State.DONE
            else:
                self._before = self.snapshotter()
                self.state = State.DECIDING

        elif self.state is State.DECIDING:
            step = self.current_step
            self._grounded = self.grounder(step, self.step_index)
            if self._grounded is None:
                # Never guess a coordinate. Say so instead.
                self.renderer.clear()
                self.failure_reason = (
                    f"cannot find {step.target_descriptor.claimed.name!r} on screen"
                )
                self.state = State.FAILED
            else:
                self.state = State.RENDERING_HINT

        elif self.state is State.RENDERING_HINT:
            step = self.current_step
            self.renderer.show(self._grounded, step.instruction_text)
            if self._hint_step_index != self.step_index:
                # Genuinely a new step: start its idle clock.
                self._waiting_since = self.clock()
                self.rehint_count = 0
                self._confirmed = False
                self._hint_step_index = self.step_index
            self.state = State.AWAITING_USER_ACTION

        elif self.state is State.AWAITING_USER_ACTION:
            # A dwelling state, not a pass-through. The user acts on their own
            # schedule, so this polls and stays put until something happens.
            step = self.current_step
            after = self.snapshotter()

            if step.verification_rule.kind is VerificationKind.USER_CONFIRMS:
                satisfied = self._confirmed
            else:
                satisfied = self.verifier(step.verification_rule, self._before, after)

            if satisfied:
                self.state = State.VERIFYING
            elif after != self._before:
                # The world changed, but not into what we predicted — the user
                # did something else. Re-observe and re-ground: the target may
                # have moved or be gone. AndroidWorld-style interrupt handling.
                self.state = State.OBSERVING
            elif self.clock() - self._waiting_since >= self.idle_timeout_s:
                # Clippy lesson: re-hint once, then go quiet. Never nag.
                if self.rehint_count == 0:
                    self.renderer.show(self._grounded, step.instruction_text)
                    self.rehint_count += 1
                self._waiting_since = self.clock()
            # else: keep waiting, and let the idle clock keep accumulating.

        elif self.state is State.VERIFYING:
            # Commit: the predicted post-condition held.
            self.step_index += 1
            self.renderer.clear()
            self._confirmed = False
            self.state = State.OBSERVING

        return self.state
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_loop.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add ghostcursor/reasoning/loop.py tests/test_loop.py
git commit -m "feat: add observe-act-verify state machine"
```

---

### Task 8: Overlay renderer adapter

Bridges the loop's `Renderer` protocol to the existing overlay.

**Files:**
- Create: `ghostcursor/reasoning/renderer.py`
- Test: `tests/test_renderer.py`

**Interfaces:**
- Consumes: `overlay.window.set_hint`, `overlay.window.clear_hint`, `grounding.GroundedTarget`
- Produces: `OverlayRenderer(hwnd: int)` with `.show(grounded, instruction_text)`, `.clear()`, `.last_instruction: str | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_renderer.py
from ghostcursor.reasoning.grounding import GroundedTarget
from ghostcursor.reasoning.renderer import OverlayRenderer

TARGET = GroundedTarget((100, 200, 200, 240), 1, "1001", "Button", "Export")


class SpyOverlay:
    def __init__(self):
        self.hints = []
        self.clears = 0

    def set_hint(self, hwnd, x, y, radius=24):
        self.hints.append((hwnd, x, y, radius))

    def clear_hint(self, hwnd):
        self.clears += 1


def test_show_points_at_the_centre_of_the_grounded_element():
    spy = SpyOverlay()
    OverlayRenderer(hwnd=42, overlay=spy).show(TARGET, "Click Export.")
    assert spy.hints == [(42, 150, 220, 24)]


def test_show_records_the_instruction_for_display():
    renderer = OverlayRenderer(hwnd=42, overlay=SpyOverlay())
    renderer.show(TARGET, "Click Export.")
    assert renderer.last_instruction == "Click Export."


def test_clear_clears_the_overlay_and_the_instruction():
    spy = SpyOverlay()
    renderer = OverlayRenderer(hwnd=42, overlay=spy)
    renderer.show(TARGET, "Click Export.")
    renderer.clear()
    assert spy.clears == 1
    assert renderer.last_instruction is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_renderer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostcursor.reasoning.renderer'`

- [ ] **Step 3: Write minimal implementation**

```python
# ghostcursor/reasoning/renderer.py
"""Adapts the loop's Renderer protocol onto the Win32 overlay.

Kept separate from the loop so state transitions can be tested with no UI,
and so the overlay stays a pure rendering surface with no knowledge of
recipes or verification.
"""

from __future__ import annotations

from ghostcursor.overlay import window as overlay_window
from ghostcursor.reasoning.grounding import GroundedTarget


class OverlayRenderer:
    def __init__(self, hwnd: int, overlay=overlay_window) -> None:
        self.hwnd = hwnd
        self.overlay = overlay
        self.last_instruction: str | None = None

    def show(self, grounded: GroundedTarget, instruction_text: str) -> None:
        left, top, right, bottom = grounded.bbox
        # Coordinates are computed here, at render time, from the live
        # rectangle — never read from the recipe.
        self.overlay.set_hint(
            self.hwnd, (left + right) // 2, (top + bottom) // 2
        )
        self.last_instruction = instruction_text

    def clear(self) -> None:
        self.overlay.clear_hint(self.hwnd)
        self.last_instruction = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_renderer.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add ghostcursor/reasoning/renderer.py tests/test_renderer.py
git commit -m "feat: adapt overlay to the loop renderer protocol"
```

---

### Task 9: Hand-authored recipe and end-to-end guided tour

Proves the whole chain against a real window, with real pixels.

**Files:**
- Create: `ghostcursor/reasoning/recipes/synthetic_export.json`
- Create: `tests/test_guided_tour.py`

**Interfaces:**
- Consumes: everything above

- [ ] **Step 1: Write the failing test**

```python
# tests/test_guided_tour.py
"""End-to-end: recipe -> ground -> hint on screen -> user acts -> verify."""

from pathlib import Path

import mss
import numpy as np

from ghostcursor.overlay import dpi
from ghostcursor.overlay import window as ov
from ghostcursor.reasoning import grounding
from ghostcursor.reasoning.loop import GuidedTour, State
from ghostcursor.reasoning.renderer import OverlayRenderer
from ghostcursor.reasoning.schema import Recipe
from ghostcursor.reasoning.verification import Snapshot, take_snapshot, verify
from tests.uia_app import BTN_EXPORT, LBL_STATUS, SyntheticApp

RECIPE_PATH = (
    Path(__file__).resolve().parents[1]
    / "ghostcursor" / "reasoning" / "recipes" / "synthetic_export.json"
)


def _ring_pixels():
    with mss.MSS() as sct:
        frame = np.array(sct.grab(dpi.capture_region()))[:, :, :3]
    b, g, r = frame[:, :, 0], frame[:, :, 1], frame[:, :, 2]
    return np.argwhere((r < 80) & (g > 150) & (b > 190))


def test_recipe_file_is_valid():
    recipe = Recipe.load(RECIPE_PATH)
    from ghostcursor.reasoning.schema import validate_step

    assert recipe.steps, "recipe has no steps"
    for i, step in enumerate(recipe.steps):
        assert validate_step(step) == [], f"step {i} invalid"


def test_tour_grounds_renders_and_verifies_against_a_real_window():
    recipe = Recipe.load(RECIPE_PATH)

    with SyntheticApp() as app:
        title_re = f".*{app.title}.*"
        hwnd = ov.create_overlay_window()
        try:
            renderer = OverlayRenderer(hwnd)
            tour = GuidedTour(
                recipe=recipe,
                grounder=lambda step, i: grounding.ground(step, title_re),
                snapshotter=lambda: take_snapshot(title_re),
                verifier=verify,
                renderer=renderer,
            )

            for _ in range(4):
                tour.tick()
                app.pump()
            assert tour.state is State.AWAITING_USER_ACTION

            # the hint must be on screen, over the Export button
            ring = _ring_pixels()
            assert len(ring) > 50, "no hint ring rendered"

            elements = {
                e.automation_id: e
                for e in __import__(
                    "ghostcursor.perception.uia", fromlist=["iter_elements"]
                ).iter_elements(title_re)
            }
            btn = elements[str(BTN_EXPORT)]
            cy, cx = ring[:, 0].mean(), ring[:, 1].mean()
            assert btn.bbox[0] <= cx <= btn.bbox[2]
            assert btn.bbox[1] <= cy <= btn.bbox[3]

            # the user acts: the app's status label changes
            app.click_button(BTN_EXPORT)
            app.pump()

            for _ in range(3):
                tour.tick()
                app.pump()
            assert tour.step_index == 1
        finally:
            ov.destroy_overlay_window(hwnd)


def test_promotion_persists_after_a_successful_grounding():
    recipe = Recipe.load(RECIPE_PATH)
    step = recipe.steps[0]
    assert step.target_descriptor.confirmed == []

    with SyntheticApp() as app:
        title_re = f".*{app.title}.*"
        grounded = grounding.ground(step, title_re)
        assert grounded is not None
        grounding.promote(step, grounded, app_version="1.0.0", locale="en-US")

    assert step.target_descriptor.confirmed[0].automation_id == str(BTN_EXPORT)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_guided_tour.py -v`
Expected: FAIL — the recipe file does not exist yet

- [ ] **Step 3: Write the recipe**

```json
{
  "app_id": "synthetic",
  "intent": "export the current file",
  "steps": [
    {
      "user_action": "click",
      "target_descriptor": {
        "claimed": {
          "name": "Export",
          "name_synonyms": ["Export As", "Save As"],
          "ocr_text": "Export",
          "visual_description": "button in the left column, top"
        },
        "confirmed": []
      },
      "instruction_text": "Click Export to start exporting your file.",
      "verification_rule": {
        "kind": "property_changes",
        "args": {
          "target_descriptor": { "automation_id": "1005" },
          "property": "name"
        },
        "timeout_s": 30.0
      },
      "risk": "normal",
      "preconditions": [],
      "provenance": {
        "source_urls": [],
        "source_tier": "hand-authored",
        "model": "none",
        "prompt_version": "none",
        "created_at": "2026-08-14"
      }
    },
    {
      "user_action": "observe",
      "target_descriptor": { "claimed": {}, "confirmed": [] },
      "instruction_text": "Check the status line — it should show the export finished.",
      "verification_rule": { "kind": "user_confirms", "args": {}, "timeout_s": 30.0 },
      "risk": "normal",
      "preconditions": [],
      "provenance": {
        "source_urls": [],
        "source_tier": "hand-authored",
        "model": "none",
        "prompt_version": "none",
        "created_at": "2026-08-14"
      }
    }
  ]
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_guided_tour.py -v`
Expected: 3 passed

- [ ] **Step 5: Run the whole suite, then commit**

```bash
python -m pytest tests/ -v
python -m tests.test_overlay
python -m tests.test_end_to_end
git add ghostcursor/reasoning/recipes/ tests/test_guided_tour.py
git commit -m "feat: add hand-authored recipe and end-to-end guided tour"
```

---

### Task 10: Wire the tour into the entry point

**Files:**
- Modify: `ghostcursor/run.py`
- Modify: `FLOW.md`, `DECISIONS.md`

**Interfaces:**
- Produces: `python -m ghostcursor.run --recipe <path> --target <title regex>`

- [ ] **Step 1: Add the recipe mode to run.py**

Add to the argument parser and dispatch:

```python
    parser.add_argument("--recipe", help="path to a recipe JSON to run as a guided tour")
```

```python
def run_tour(recipe_path: str, title_re: str, seconds: float) -> int:
    """Drive a hand-authored recipe against a live window."""
    from ghostcursor.reasoning import grounding
    from ghostcursor.reasoning.loop import GuidedTour, State
    from ghostcursor.reasoning.renderer import OverlayRenderer
    from ghostcursor.reasoning.schema import Recipe
    from ghostcursor.reasoning.verification import take_snapshot, verify

    recipe = Recipe.load(recipe_path)
    hwnd = window.create_overlay_window()
    print(f"Guided tour: {recipe.intent!r}. ESC to quit.")

    deadline = time.monotonic() + seconds
    try:
        tour = GuidedTour(
            recipe=recipe,
            grounder=lambda step, i: grounding.ground(step, title_re),
            snapshotter=lambda: take_snapshot(title_re),
            verifier=verify,
            renderer=OverlayRenderer(hwnd),
        )
        while time.monotonic() < deadline:
            if escape_pressed():
                print("ESC pressed — exiting.")
                break
            if win32api.GetAsyncKeyState(win32con.VK_SPACE) & 0x8000:
                tour.confirm()

            state = tour.tick()
            if state is State.DONE:
                print("Tour complete.")
                break
            if state is State.FAILED:
                print(f"Stopped: {tour.failure_reason}")
                break
            if tour.renderer.last_instruction:
                print(f"  step {tour.step_index + 1}: {tour.renderer.last_instruction}")

            window.pump_messages_nonblocking()
            time.sleep(REFRESH_SECONDS)
    finally:
        window.destroy_overlay_window(hwnd)
    return 0
```

And in `main()`, before the existing loop:

```python
    if args.recipe:
        return run_tour(args.recipe, args.target, args.seconds)
```

- [ ] **Step 2: Run it against the synthetic app**

```bash
python -m pytest tests/test_guided_tour.py -v
python -m ghostcursor.run --recipe ghostcursor/reasoning/recipes/synthetic_export.json --target ".*GhostCursorTestApp.*" --seconds 20
```

Expected: prints the first instruction; exits cleanly on ESC or timeout. (Requires a `SyntheticApp` window open — or point `--target` at any window and expect "cannot find ... on screen", which is the correct refusal.)

- [ ] **Step 3: Update FLOW.md**

Replace the "You are here" section with the new call graph: `run.run_tour → GuidedTour.tick → grounding.ground → OverlayRenderer.show → verification.verify`, and mark the Intermediate milestone as in progress with the KB still unbuilt.

- [ ] **Step 4: Add DECISIONS.md entries**

Add D013 (grounding ladder as a promotion mechanism — AutomationId cannot come from docs, so it is learned on first grounding and written back; locale gates text matchers only) and D014 (verification checks world state not method, so a keyboard shortcut satisfies a step that named a menu path).

- [ ] **Step 5: Commit**

```bash
python -m pytest tests/ -v && python -m tests.test_overlay && python -m tests.test_end_to_end
git add ghostcursor/run.py FLOW.md DECISIONS.md
git commit -m "feat: run hand-authored recipes as guided tours"
```

---

## Self-Review

**Spec coverage.** §4 step contract → Task 2. §5 grounding ladder → Task 4; promotion → Task 5; locale rule → Tasks 4–5; path-hint-as-tie-breaker → Task 4. §6 state machine, including re-plan on failed verification and re-hint-once idle handling → Task 7. §7 verification rules and `user_confirms` fallback → Task 6; the elevated-risk prohibition is enforced in Task 2's `validate_step`. §11 error handling: ungroundable step → Task 7 (`FAILED` with a reason, never a guessed coordinate); off-screen targets → Task 3. §12 synthetic UIA app → Task 1. Sections 8–10 (KB, versions, storage) are deliberately absent — out of scope, and `app_version` is threaded through `promote()` so the KB can key on it later without a schema change.

**Not covered, by design:** rungs 4–5 (OCR, VLM) have no perception tier behind them yet; `preconditions` is carried in the schema but not enforced by the loop, since a two-step recipe has none. Both are noted here rather than silently skipped.

**Placeholder scan.** No TBD/TODO markers; every code step contains complete, runnable content.

**Type consistency.** `GroundedTarget` fields (`bbox, rung, automation_id, control_type, name`) are used identically in Tasks 4, 5, 8, 9. `Element` (`name, control_type, automation_id, bbox, path`) is consistent across Tasks 3, 4, 6. `ConfirmedObservation` field names match between Task 2's definition and Task 5's writes. `verify(rule, before, after)` matches the `verifier` collaborator signature in Task 7 and the real function in Task 6. `renderer.show(grounded, instruction_text)` / `.clear()` match between Tasks 7 and 8.

---

Plan complete and saved to `docs/superpowers/plans/2026-08-14-reasoning-loop-and-grounding.md`.
