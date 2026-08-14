# Persistent Confirmed Observations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an AutomationId learned during one run survive process exit, so the next run grounds by AutomationId immediately instead of re-learning by name.

**Architecture:** Promotion already discovers AutomationIds and writes them onto the in-memory `Step`; it just forgets at exit. This adds the write-to-disk half: a `step_key` that durably identifies a step, a SQLite store under `%LOCALAPPDATA%`, persistence on promote, hydration before a tour starts, and — because persistence is what makes it dangerous — version-scoped selection in `ground()` with a `control_type` cross-check so a stale id from an older UI generation can never mis-ground.

**Tech Stack:** Python 3.12, sqlite3 (stdlib), pywin32, pywinauto, pytest 9.0.3.

**Spec:** `docs/superpowers/specs/2026-08-14-reasoning-and-knowledge-design.md` (§9 selection/step_key/privacy, §10 data model, §13 build order step 6)

## Global Constraints

- **D006 — the system never acts.** No `SendInput`, `mouse_event`, PyAutoGUI, synthesized keystrokes, or moving the real cursor, anywhere, including tests.
- **Recipes store intent, never pixels.** Nothing persisted may contain a coordinate. `Recipe.from_dict` rejects them recursively; the store must not become a loophole.
- **Local only.** No telemetry, no network, no cloud sync. The store lives at `%LOCALAPPDATA%\GhostCursor\kb.sqlite` and nowhere else. Deleting that file fully erases it.
- **Failing to ground is acceptable; mis-grounding is not.** A failure is visible and recoverable. A confident hint on the wrong control teaches the user something false with no signal.
- **Import `ghostcursor.overlay.dpi` before creating any window.**
- **NOT in this milestone:** web search, doc ingestion, embeddings, intent matching, recipe distillation, OCR, VLM.
- Existing suites must keep passing: `python -m pytest tests/` (70) and the two pixel harnesses (`python -m tests.test_overlay` 14/14, `python -m tests.test_end_to_end` 8/8, controller-run only).

## File Structure

| File | Responsibility |
|---|---|
| `ghostcursor/perception/appinfo.py` | App identity + version from a live window (Win32 VERSIONINFO, Appx package) |
| `ghostcursor/reasoning/identity.py` | `step_key()` — durable identity for a step |
| `ghostcursor/memory/store.py` | SQLite observation store: schema, upsert, query, path resolution |
| `ghostcursor/reasoning/grounding.py` | *(modify)* version-scoped rung-1 selection + cross-check |
| `ghostcursor/run.py` | *(modify)* hydrate before the tour, persist on promote |
| `tests/test_appinfo.py`, `test_identity.py`, `test_store.py`, `test_scoped_grounding.py`, `test_persistence_e2e.py` | one per unit above, plus the subprocess proof |

**Test runner:** pytest. Never run the two pixel harnesses — they assert against the whole screen and fail spuriously alongside other work.

---

### Task 1: App identity and version detection

**Files:**
- Create: `ghostcursor/perception/appinfo.py`
- Test: `tests/test_appinfo.py`

**Interfaces:**
- Produces:
  - `AppInfo(app_id: str, exe_path: str, version: str, kind: str)` — frozen dataclass; `kind` is `"win32"` or `"appx"`; `version` is `"unknown"` when undeterminable
  - `app_info_for_window(title_re: str) -> AppInfo | None`
  - `parse_version(text: str) -> tuple[int, ...] | None` — `"151.0.7922.110"` → `(151,0,7922,110)`; `None` for unparseable/unknown

- [ ] **Step 1: Write the failing test**

```python
# tests/test_appinfo.py
from ghostcursor.perception.appinfo import AppInfo, app_info_for_window, parse_version
from tests.uia_app import SyntheticApp


def test_parse_version_reads_dotted_numbers():
    assert parse_version("151.0.7922.110") == (151, 0, 7922, 110)
    assert parse_version("1.2") == (1, 2)


def test_parse_version_rejects_unparseable():
    assert parse_version("unknown") is None
    assert parse_version("") is None
    assert parse_version("1.2.beta") is None


def test_app_info_for_a_live_window():
    with SyntheticApp() as app:
        info = app_info_for_window(f".*{app.title}.*")
    assert info is not None
    # the synthetic app is hosted by python.exe, a plain Win32 binary
    assert info.kind == "win32"
    assert info.exe_path.lower().endswith(".exe")
    assert info.app_id == "python.exe"
    assert parse_version(info.version) is not None, f"got {info.version!r}"


def test_app_info_is_none_when_no_window_matches():
    assert app_info_for_window(".*NoSuchWindowAnywhere12345.*") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m pytest tests/test_appinfo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostcursor.perception.appinfo'`

- [ ] **Step 3: Write minimal implementation**

```python
# ghostcursor/perception/appinfo.py
"""Which application is this, and which version of it is running.

Needed because a learned AutomationId is only meaningful alongside the
version it was observed on (spec §9). Verified on this machine:

    HWND -> PID -> QueryFullProcessImageNameW -> exe path -> GetFileVersionInfo
        Chrome (Win32)    -> 151.0.7922.110
        Terminal (Store)  -> VERSIONINFO 1.24.2607.10001
                          -> Appx pkg   1.24.11911.0   <- authoritative, differs

For Store apps the package version is authoritative and the exe's VERSIONINFO
disagrees, so the WindowsApps branch is not optional.

Results are cached per (exe_path, mtime): the version of an installed binary
cannot change without the file changing, and the Appx lookup shells out.
"""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
from dataclasses import dataclass

import win32api
import win32gui
import win32process

from ghostcursor.overlay import dpi  # noqa: F401  declares DPI awareness first

UNKNOWN = "unknown"
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_cache: dict[tuple[str, float], str] = {}


@dataclass(frozen=True)
class AppInfo:
    app_id: str
    exe_path: str
    version: str
    kind: str  # "win32" | "appx"


def parse_version(text: str) -> tuple[int, ...] | None:
    """Dotted numeric version to a comparable tuple, or None if unparseable."""
    if not text or text == UNKNOWN:
        return None
    parts = text.split(".")
    if not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def _exe_path_for_pid(pid: int) -> str | None:
    handle = ctypes.windll.kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = ctypes.c_ulong(32768)
        ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(
            handle, 0, buf, ctypes.byref(size)
        )
        return buf.value if ok else None
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _file_version(exe_path: str) -> str:
    try:
        info = win32api.GetFileVersionInfo(exe_path, "\\")
        ms, ls = info["FileVersionMS"], info["FileVersionLS"]
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:
        return UNKNOWN


def _appx_version(exe_path: str) -> str:
    """Store apps carry the authoritative version in the package, not the exe."""
    match = re.search(r"WindowsApps\\([^\\]+)", exe_path)
    if not match:
        return UNKNOWN
    package_name = match.group(1).split("_")[0]
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-AppxPackage -Name {package_name}).Version"],
            capture_output=True, text=True, timeout=25,
        )
        return result.stdout.strip() or UNKNOWN
    except Exception:
        return UNKNOWN


def _version_for(exe_path: str, kind: str) -> str:
    try:
        key = (exe_path, os.path.getmtime(exe_path))
    except OSError:
        key = (exe_path, 0.0)
    if key not in _cache:
        _cache[key] = _appx_version(exe_path) if kind == "appx" else _file_version(exe_path)
    return _cache[key]


def app_info_for_window(title_re: str) -> AppInfo | None:
    """Identify the application owning the first visible window matching
    title_re, or None if no such window exists."""
    pattern = re.compile(title_re)
    found: list[int] = []

    def _collect(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and pattern.search(win32gui.GetWindowText(hwnd)):
            found.append(hwnd)

    win32gui.EnumWindows(_collect, None)
    if not found:
        return None

    pid = win32process.GetWindowThreadProcessId(found[0])[1]
    exe_path = _exe_path_for_pid(pid)
    if not exe_path:
        return None

    kind = "appx" if "WindowsApps" in exe_path else "win32"
    return AppInfo(
        app_id=os.path.basename(exe_path).lower(),
        exe_path=exe_path,
        version=_version_for(exe_path, kind),
        kind=kind,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -B -m pytest tests/test_appinfo.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add ghostcursor/perception/appinfo.py tests/test_appinfo.py
git commit -m "feat: detect app identity and version from a live window"
```

---

### Task 2: Durable step identity

Kept separate from the store on purpose: this is product semantics — it decides which authoring edits forfeit learned data — while the store is plumbing.

**Files:**
- Create: `ghostcursor/reasoning/identity.py`
- Test: `tests/test_identity.py`

**Interfaces:**
- Consumes: `schema.Step`
- Produces: `step_key(intent: str, step: Step) -> str` — stable hex digest

- [ ] **Step 1: Write the failing test**

```python
# tests/test_identity.py
from ghostcursor.reasoning.identity import step_key
from ghostcursor.reasoning.schema import (
    ClaimedDescriptor,
    Risk,
    Step,
    TargetDescriptor,
    UserAction,
    VerificationKind,
    VerificationRule,
)


def _step(**claimed):
    base = dict(name="Export", ocr_text="Export", visual_description="top left button")
    base.update(claimed)
    return Step(
        user_action=UserAction.CLICK,
        target_descriptor=TargetDescriptor(claimed=ClaimedDescriptor(**base)),
        instruction_text="Click Export.",
        verification_rule=VerificationRule(kind=VerificationKind.USER_CONFIRMS),
        risk=Risk.NORMAL,
    )


def test_key_is_stable_across_calls():
    assert step_key("export a file", _step()) == step_key("export a file", _step())


def test_key_ignores_step_position_and_instruction_text():
    a = _step()
    b = _step()
    b.instruction_text = "Totally different wording."
    assert step_key("export a file", a) == step_key("export a file", b)


def test_key_is_namespaced_by_intent():
    assert step_key("export a file", _step()) != step_key("crop an image", _step())


def test_adding_a_synonym_does_not_orphan_learning():
    # Synonyms are alternate spellings of the SAME target.
    plain = _step()
    with_synonym = _step()
    with_synonym.target_descriptor.claimed.name_synonyms = ["Save As"]
    assert step_key("export a file", plain) == step_key("export a file", with_synonym)


def test_visual_description_distinguishes_same_named_targets():
    # "Delete in the toolbar" vs "Delete in the dialog" must not collide.
    toolbar = _step(name="Delete", visual_description="in the toolbar")
    dialog = _step(name="Delete", visual_description="in the confirmation dialog")
    assert step_key("delete a file", toolbar) != step_key("delete a file", dialog)


def test_renaming_the_target_orphans_learning():
    # Correct: the step now describes a different target.
    assert step_key("export a file", _step()) != step_key(
        "export a file", _step(name="Publish")
    )


def test_key_normalizes_whitespace_and_case():
    assert step_key("export a file", _step(name="Export")) == step_key(
        "export a file", _step(name="  export  ")
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m pytest tests/test_identity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostcursor.reasoning.identity'`

- [ ] **Step 3: Write minimal implementation**

```python
# ghostcursor/reasoning/identity.py
"""A durable identity for "this step of this recipe" (spec §9).

Persisting what a step learned needs a key that survives editing the recipe.
`(intent, step_index)` is unusable: inserting a step silently re-attaches
every learned observation to a different instruction.

The key hashes the intent (as namespace) plus the step's CLAIMED descriptor:
`name`, `ocr_text` and `visual_description`.

  - `name_synonyms` is excluded. Synonyms are alternate spellings of the same
    target, so adding one must not discard what the step has learned.
  - `visual_description` is included. It is what separates two steps sharing a
    name but differing in location ("Delete in the toolbar" versus "Delete in
    the dialog") — exactly the collision that would otherwise let one step's
    observations mis-ground the other.

Editing any of the three orphans that step's observations. That is correct,
not unfortunate: the step now describes a different target, and inherited
evidence about the old one would be wrong.
"""

from __future__ import annotations

import hashlib

from ghostcursor.reasoning.schema import Step


def _normalize(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def step_key(intent: str, step: Step) -> str:
    claimed = step.target_descriptor.claimed
    parts = [
        _normalize(intent),
        _normalize(claimed.name),
        _normalize(claimed.ocr_text),
        _normalize(claimed.visual_description),
    ]
    # \x1f (unit separator) cannot appear in normalized text, so distinct
    # field values can never combine into the same digest input.
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -B -m pytest tests/test_identity.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add ghostcursor/reasoning/identity.py tests/test_identity.py
git commit -m "feat: add durable step identity for persisted observations"
```

---

### Task 3: The SQLite observation store

**Files:**
- Create: `ghostcursor/memory/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `schema.ConfirmedObservation`
- Produces:
  - `default_db_path() -> Path` — `%LOCALAPPDATA%\GhostCursor\kb.sqlite`, overridable by env var `GHOSTCURSOR_KB_PATH`
  - `ObservationStore(path)` — context manager
  - `.record(step_key, app_id, observation) -> None` — idempotent upsert
  - `.observations_for(step_key, app_id) -> list[ConfirmedObservation]`
  - `.forget_all() -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_store.py
import os

from ghostcursor.memory.store import ObservationStore, default_db_path
from ghostcursor.reasoning.schema import ConfirmedObservation


def _obs(version="1.0.0", automation_id="1001", locales=("en-US",), ctype="Button"):
    return ConfirmedObservation(
        app_version=version,
        locales_observed=list(locales),
        automation_id=automation_id,
        control_type=ctype,
        last_seen_at="2026-08-14T00:00:00+00:00",
    )


def test_default_path_is_under_localappdata(monkeypatch):
    monkeypatch.delenv("GHOSTCURSOR_KB_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\someone\AppData\Local")
    path = default_db_path()
    assert path.name == "kb.sqlite"
    assert "GhostCursor" in str(path)
    assert "AppData" in str(path)


def test_env_var_overrides_the_default_path(monkeypatch, tmp_path):
    target = tmp_path / "custom.sqlite"
    monkeypatch.setenv("GHOSTCURSOR_KB_PATH", str(target))
    assert default_db_path() == target


def test_records_survive_closing_and_reopening(tmp_path):
    path = tmp_path / "kb.sqlite"
    with ObservationStore(path) as store:
        store.record("stepkey1", "notepad.exe", _obs())
    with ObservationStore(path) as store:
        loaded = store.observations_for("stepkey1", "notepad.exe")
    assert len(loaded) == 1
    assert loaded[0].automation_id == "1001"
    assert loaded[0].app_version == "1.0.0"
    assert loaded[0].control_type == "Button"
    assert loaded[0].locales_observed == ["en-US"]


def test_recording_the_same_observation_twice_does_not_duplicate(tmp_path):
    with ObservationStore(tmp_path / "kb.sqlite") as store:
        store.record("k", "app.exe", _obs())
        store.record("k", "app.exe", _obs())
        assert len(store.observations_for("k", "app.exe")) == 1


def test_reobserving_merges_locales(tmp_path):
    with ObservationStore(tmp_path / "kb.sqlite") as store:
        store.record("k", "app.exe", _obs(locales=("en-US",)))
        store.record("k", "app.exe", _obs(locales=("hi-IN",)))
        loaded = store.observations_for("k", "app.exe")
    assert len(loaded) == 1
    assert sorted(loaded[0].locales_observed) == ["en-US", "hi-IN"]


def test_different_versions_are_separate_observations(tmp_path):
    with ObservationStore(tmp_path / "kb.sqlite") as store:
        store.record("k", "app.exe", _obs(version="1.0.0"))
        store.record("k", "app.exe", _obs(version="2.0.0"))
        assert len({o.app_version for o in store.observations_for("k", "app.exe")} ) == 2


def test_observations_are_scoped_by_step_and_app(tmp_path):
    with ObservationStore(tmp_path / "kb.sqlite") as store:
        store.record("k1", "app.exe", _obs(automation_id="1001"))
        store.record("k2", "app.exe", _obs(automation_id="2002"))
        store.record("k1", "other.exe", _obs(automation_id="3003"))
        assert [o.automation_id for o in store.observations_for("k1", "app.exe")] == ["1001"]


def test_unknown_step_returns_nothing(tmp_path):
    with ObservationStore(tmp_path / "kb.sqlite") as store:
        assert store.observations_for("nope", "app.exe") == []


def test_forget_all_erases_everything(tmp_path):
    with ObservationStore(tmp_path / "kb.sqlite") as store:
        store.record("k", "app.exe", _obs())
        store.forget_all()
        assert store.observations_for("k", "app.exe") == []


def test_store_creates_its_parent_directory(tmp_path):
    nested = tmp_path / "a" / "b" / "kb.sqlite"
    with ObservationStore(nested) as store:
        store.record("k", "app.exe", _obs())
    assert nested.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostcursor.memory.store'`

- [ ] **Step 3: Write minimal implementation**

```python
# ghostcursor/memory/store.py
"""Local, on-disk memory of what grounding has learned (spec §10).

This is the first thing in the system to write screen-derived data to disk:
application identity and the names of UI elements read from the user's screen.
The §2 invariant governs data LEAVING the machine and is not weakened by this,
but the locality is deliberate and stated:

  - local only; no telemetry, no network, no cloud sync
  - stored at %LOCALAPPDATA%\\GhostCursor\\kb.sqlite and nowhere else
  - deleting that file fully erases it; the system re-learns from scratch

The primary key (step_key, app_id, app_version, automation_id) is what makes
promotion idempotent: re-observing the same id for the same step, app and
version updates one row instead of appending a duplicate forever.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from ghostcursor.reasoning.schema import ConfirmedObservation

#: Overriding the path is what lets tests — and a second process in the
#: end-to-end proof — share a database without touching the real one.
ENV_PATH = "GHOSTCURSOR_KB_PATH"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    step_key         TEXT NOT NULL,
    app_id           TEXT NOT NULL,
    app_version      TEXT NOT NULL,
    automation_id    TEXT NOT NULL,
    control_type     TEXT,
    locales_observed TEXT NOT NULL DEFAULT '[]',
    last_seen_at     TEXT,
    ok_count         INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (step_key, app_id, app_version, automation_id)
);
"""


def default_db_path() -> Path:
    override = os.environ.get(ENV_PATH)
    if override:
        return Path(override)
    local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local_app_data) / "GhostCursor" / "kb.sqlite"


class ObservationStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def __enter__(self) -> "ObservationStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def record(self, step_key: str, app_id: str, observation: ConfirmedObservation) -> None:
        """Upsert one observation, merging locales with anything already known."""
        if not observation.automation_id:
            return  # nothing learned; never invent an id

        existing = self._conn.execute(
            "SELECT locales_observed, ok_count FROM observations "
            "WHERE step_key=? AND app_id=? AND app_version=? AND automation_id=?",
            (step_key, app_id, observation.app_version, observation.automation_id),
        ).fetchone()

        locales = set(observation.locales_observed)
        ok_count = 1
        if existing:
            locales |= set(json.loads(existing["locales_observed"]))
            ok_count = existing["ok_count"] + 1

        self._conn.execute(
            "INSERT INTO observations (step_key, app_id, app_version, automation_id,"
            " control_type, locales_observed, last_seen_at, ok_count)"
            " VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(step_key, app_id, app_version, automation_id) DO UPDATE SET"
            "   control_type=excluded.control_type,"
            "   locales_observed=excluded.locales_observed,"
            "   last_seen_at=excluded.last_seen_at,"
            "   ok_count=excluded.ok_count",
            (
                step_key, app_id, observation.app_version, observation.automation_id,
                observation.control_type, json.dumps(sorted(locales)),
                observation.last_seen_at, ok_count,
            ),
        )
        self._conn.commit()

    def observations_for(self, step_key: str, app_id: str) -> list[ConfirmedObservation]:
        rows = self._conn.execute(
            "SELECT * FROM observations WHERE step_key=? AND app_id=?"
            " ORDER BY app_version, automation_id",
            (step_key, app_id),
        ).fetchall()
        return [
            ConfirmedObservation(
                app_version=row["app_version"],
                locales_observed=json.loads(row["locales_observed"]),
                automation_id=row["automation_id"],
                control_type=row["control_type"],
                accessibility_path_hint=[],
                last_seen_at=row["last_seen_at"],
            )
            for row in rows
        ]

    def forget_all(self) -> None:
        """Erase everything. The user-facing equivalent is deleting the file."""
        self._conn.execute("DELETE FROM observations")
        self._conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -B -m pytest tests/test_store.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add ghostcursor/memory/store.py tests/test_store.py
git commit -m "feat: add local sqlite store for confirmed observations"
```

---

### Task 4: Version-scoped selection with the cross-check

The parked cross-version union problem. It ships here, with the store, because persistence is what makes it dangerous.

**Files:**
- Modify: `ghostcursor/reasoning/grounding.py`
- Test: `tests/test_scoped_grounding.py`

**Interfaces:**
- Consumes: `appinfo.parse_version`
- Produces:
  - `select_observations(confirmed, app_version) -> list[tuple[ConfirmedObservation, bool]]` — the bool is `is_exact`
  - `ground(step, title_re, locale="en-US", elements=None, app_version=None)` — new keyword-only-in-effect final parameter

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scoped_grounding.py
from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.grounding import (
    RUNG_AUTOMATION_ID,
    RUNG_TYPE_AND_NAME,
    ground,
    select_observations,
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


def _obs(version, automation_id="1001", ctype="Button"):
    return ConfirmedObservation(
        app_version=version, locales_observed=["en-US"],
        automation_id=automation_id, control_type=ctype,
    )


def _step(confirmed, name="Export"):
    return Step(
        user_action=UserAction.CLICK,
        target_descriptor=TargetDescriptor(
            claimed=ClaimedDescriptor(name=name), confirmed=list(confirmed)
        ),
        instruction_text="Click Export.",
        verification_rule=VerificationRule(kind=VerificationKind.USER_CONFIRMS),
        risk=Risk.NORMAL,
    )


BUTTON = [Element("Export", "Button", "1001", (10, 10, 110, 40))]


def test_exact_version_wins_and_is_marked_exact():
    chosen = select_observations([_obs("1.0.0"), _obs("2.0.0")], "2.0.0")
    assert [(o.app_version, exact) for o, exact in chosen] == [("2.0.0", True)]


def test_nearest_lower_version_is_used_when_no_exact_match():
    chosen = select_observations([_obs("1.0.0"), _obs("1.5.0"), _obs("3.0.0")], "2.0.0")
    assert [o.app_version for o, _ in chosen] == ["1.5.0"]
    assert all(exact is False for _, exact in chosen)


def test_newer_observations_are_never_used_for_an_older_app():
    # An id learned on 3.0.0 says nothing about what 2.0.0 shows.
    chosen = select_observations([_obs("3.0.0")], "2.0.0")
    assert [o.app_version for o, _ in chosen] == ["unknown"] or chosen == []


def test_unknown_app_version_uses_every_observation_inexactly():
    chosen = select_observations([_obs("1.0.0"), _obs("2.0.0")], None)
    assert len(chosen) == 2
    assert all(exact is False for _, exact in chosen)


def test_a_patch_bump_still_reuses_what_was_learned():
    step = _step([_obs("151.0.7922.110")])
    result = ground(step, ".*", elements=BUTTON, app_version="151.0.7923.5")
    assert result is not None and result.rung == RUNG_AUTOMATION_ID


def test_exact_version_match_skips_the_cross_check():
    # control_type disagrees, but the version matches exactly, so the
    # observation is trusted.
    step = _step([_obs("1.0.0", ctype="Hyperlink")])
    result = ground(step, ".*", elements=BUTTON, app_version="1.0.0")
    assert result is not None and result.rung == RUNG_AUTOMATION_ID


def test_stale_id_from_an_older_version_does_not_misground():
    # The id was learned on 1.0.0 as a Hyperlink; on 2.0.0 that same id is a
    # Button, i.e. it now belongs to something else. Rung 1 must be rejected
    # and grounding must fall through to the name.
    step = _step([_obs("1.0.0", ctype="Hyperlink")])
    result = ground(step, ".*", elements=BUTTON, app_version="2.0.0")
    assert result is not None
    assert result.rung == RUNG_TYPE_AND_NAME, "stale observation was trusted"


def test_cross_check_allows_a_match_when_control_type_agrees():
    step = _step([_obs("1.0.0", ctype="Button")])
    result = ground(step, ".*", elements=BUTTON, app_version="2.0.0")
    assert result is not None and result.rung == RUNG_AUTOMATION_ID


def test_observation_without_control_type_cannot_be_cross_checked():
    # Nothing to compare against; allowed, and noted in the module docs.
    step = _step([_obs("1.0.0", ctype=None)])
    result = ground(step, ".*", elements=BUTTON, app_version="2.0.0")
    assert result is not None and result.rung == RUNG_AUTOMATION_ID


def test_grounding_without_an_app_version_still_works():
    # Existing callers that pass no version keep working.
    step = _step([_obs("1.0.0")])
    result = ground(step, ".*", elements=BUTTON)
    assert result is not None and result.rung == RUNG_AUTOMATION_ID
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m pytest tests/test_scoped_grounding.py -v`
Expected: FAIL with `ImportError: cannot import name 'select_observations'`

- [ ] **Step 3: Write minimal implementation**

Add to `ghostcursor/reasoning/grounding.py`, and rewrite the rung-1 block to use it:

```python
from ghostcursor.perception.appinfo import parse_version
from ghostcursor.reasoning.schema import ConfirmedObservation


def select_observations(
    confirmed: list[ConfirmedObservation], app_version: str | None
) -> list[tuple[ConfirmedObservation, bool]]:
    """Which stored observations apply to the running app, and which are exact.

    Spec §9's ladder: exact version, else nearest LOWER verified version, else
    unknown/global. Never a newer version — an id learned on 3.0 says nothing
    about what 2.0 displays.

    Strict equality was considered and rejected: AutomationIds survive version
    changes far more often than they break, so requiring an exact match would
    discard every learned id on each patch bump and re-learn from scratch.
    Non-exact reuse is made safe by the cross-check in ground() instead.
    """
    running = parse_version(app_version or "")

    if running is not None:
        exact = [o for o in confirmed if o.app_version == app_version]
        if exact:
            return [(o, True) for o in exact]

        lower = [
            (parse_version(o.app_version), o)
            for o in confirmed
            if parse_version(o.app_version) is not None
            and parse_version(o.app_version) < running
        ]
        if lower:
            nearest = max(v for v, _ in lower)
            return [(o, False) for v, o in lower if v == nearest]

        return [(o, False) for o in confirmed if parse_version(o.app_version) is None]

    # We do not know what is running, so nothing can be an exact match and
    # every observation is subject to the cross-check.
    return [(o, False) for o in confirmed]
```

Replace the existing rung-1 block (`known_ids = {...}` through its `return`) with:

```python
    # Rung 1 — confirmed AutomationId. Locale-independent on purpose.
    #
    # Version-scoped (spec §9): observations from a DIFFERENT app version are
    # usable, but only if the live element's control_type still agrees with
    # what was recorded. A stale id whose control has been reassigned would
    # otherwise produce a confident hint on the wrong element — and failing to
    # ground is recoverable, whereas mis-grounding teaches the user something
    # false with no signal that anything went wrong.
    #
    # An observation with no recorded control_type cannot be cross-checked and
    # is allowed through; promote() always records one, so this only affects
    # incomplete legacy rows.
    for observation, is_exact in select_observations(
        step.target_descriptor.confirmed, app_version
    ):
        if not observation.automation_id:
            continue
        matches = [e for e in elements if e.automation_id == observation.automation_id]
        if not is_exact and observation.control_type:
            matches = [e for e in matches if e.control_type == observation.control_type]
        if matches:
            return _as_target(_disambiguate(matches, step), RUNG_AUTOMATION_ID)
```

And add the parameter to `ground`'s signature:

```python
def ground(
    step: Step,
    title_re: str,
    locale: str = "en-US",
    elements: list[Element] | None = None,
    app_version: str | None = None,
) -> GroundedTarget | None:
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -B -m pytest tests/test_scoped_grounding.py tests/test_grounding.py tests/test_promotion.py -v`
Expected: all pass. If a pre-existing grounding/promotion test now fails, do NOT weaken it — read it, decide whether the behaviour change is legitimate, and report your reasoning.

- [ ] **Step 5: Commit**

```bash
git add ghostcursor/reasoning/grounding.py tests/test_scoped_grounding.py
git commit -m "feat: scope rung-1 observations by version with a control_type cross-check"
```

---

### Task 5: Persist on promote, hydrate before the tour

**Files:**
- Modify: `ghostcursor/run.py`
- Test: `tests/test_run_persistence.py`

**Interfaces:**
- Consumes: `appinfo.app_info_for_window`, `identity.step_key`, `store.ObservationStore`
- Produces:
  - `hydrate_recipe(recipe, app_id, store) -> int` — fills each step's `confirmed` from the store; returns how many observations were loaded
  - `persist_step(recipe_intent, step, app_id, store) -> None`
  - `make_grounder(title_re, app_info=None, store=None)` — extended; still grounds then promotes, and now also persists and passes `app_version`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run_persistence.py
from ghostcursor.memory.store import ObservationStore
from ghostcursor.perception.appinfo import AppInfo
from ghostcursor.reasoning.identity import step_key
from ghostcursor.reasoning.schema import (
    ClaimedDescriptor, ConfirmedObservation, Recipe, Risk, Step,
    TargetDescriptor, UserAction, VerificationKind, VerificationRule,
)
from ghostcursor.run import hydrate_recipe, persist_step

APP = AppInfo(app_id="app.exe", exe_path=r"C:\app.exe", version="1.0.0", kind="win32")


def _recipe():
    return Recipe(
        app_id="app", intent="export a file",
        steps=[Step(
            user_action=UserAction.CLICK,
            target_descriptor=TargetDescriptor(claimed=ClaimedDescriptor(name="Export")),
            instruction_text="Click Export.",
            verification_rule=VerificationRule(kind=VerificationKind.USER_CONFIRMS),
            risk=Risk.NORMAL,
        )],
    )


def test_persist_then_hydrate_round_trips(tmp_path):
    recipe = _recipe()
    recipe.steps[0].target_descriptor.confirmed.append(
        ConfirmedObservation(app_version="1.0.0", locales_observed=["en-US"],
                             automation_id="1001", control_type="Button")
    )
    with ObservationStore(tmp_path / "kb.sqlite") as store:
        persist_step(recipe.intent, recipe.steps[0], APP.app_id, store)

    fresh = _recipe()
    assert fresh.steps[0].target_descriptor.confirmed == []
    with ObservationStore(tmp_path / "kb.sqlite") as store:
        loaded = hydrate_recipe(fresh, APP.app_id, store)

    assert loaded == 1
    assert fresh.steps[0].target_descriptor.confirmed[0].automation_id == "1001"


def test_hydration_is_scoped_by_step_key(tmp_path):
    recipe = _recipe()
    with ObservationStore(tmp_path / "kb.sqlite") as store:
        store.record(
            step_key("a totally different intent", recipe.steps[0]), APP.app_id,
            ConfirmedObservation(app_version="1.0.0", automation_id="9999"),
        )
        loaded = hydrate_recipe(recipe, APP.app_id, store)
    assert loaded == 0
    assert recipe.steps[0].target_descriptor.confirmed == []


def test_hydrating_an_unknown_recipe_loads_nothing(tmp_path):
    recipe = _recipe()
    with ObservationStore(tmp_path / "kb.sqlite") as store:
        assert hydrate_recipe(recipe, APP.app_id, store) == 0


def test_persist_is_a_noop_for_a_step_that_learned_nothing(tmp_path):
    recipe = _recipe()
    with ObservationStore(tmp_path / "kb.sqlite") as store:
        persist_step(recipe.intent, recipe.steps[0], APP.app_id, store)
        assert store.observations_for(step_key(recipe.intent, recipe.steps[0]), APP.app_id) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m pytest tests/test_run_persistence.py -v`
Expected: FAIL with `ImportError: cannot import name 'hydrate_recipe'`

- [ ] **Step 3: Write minimal implementation**

Add to `ghostcursor/run.py`:

```python
def hydrate_recipe(recipe, app_id: str, store) -> int:
    """Load each step's previously learned observations from disk.

    This is the half that was missing: promotion already discovered
    AutomationIds and wrote them onto the in-memory Step, but nothing read
    them back, so every run re-learned from scratch.
    """
    from ghostcursor.reasoning.identity import step_key

    loaded = 0
    for step in recipe.steps:
        observations = store.observations_for(step_key(recipe.intent, step), app_id)
        if observations:
            step.target_descriptor.confirmed = observations
            loaded += len(observations)
    return loaded


def persist_step(recipe_intent: str, step, app_id: str, store) -> None:
    """Write a step's confirmed observations to disk, idempotently."""
    from ghostcursor.reasoning.identity import step_key

    key = step_key(recipe_intent, step)
    for observation in step.target_descriptor.confirmed:
        store.record(key, app_id, observation)
```

Then extend `make_grounder` so a live run persists what it learns and grounds with the real version. Keep the existing behaviour when no store or app info is supplied, so current callers and tests are unaffected:

```python
def make_grounder(title_re: str, app_info=None, store=None, recipe_intent: str = ""):
    """Build the grounder used by a live run_tour: ground, promote, persist."""
    from ghostcursor.reasoning import grounding

    ui_locale = get_ui_locale()
    app_version = app_info.version if app_info else "unknown"
    app_id = app_info.app_id if app_info else None

    def grounder(step, i):
        grounded = grounding.ground(
            step, title_re, locale=ui_locale, app_version=app_version
        )
        if grounded is not None:
            grounding.promote(step, grounded, app_version=app_version, locale=ui_locale)
            if store is not None and app_id is not None:
                persist_step(recipe_intent, step, app_id, store)
        return grounded

    return grounder
```

Finally, wire it in `run_tour`: resolve `app_info_for_window(title_re)` once, open an `ObservationStore()`, `hydrate_recipe(...)` before constructing the tour, print how many observations were loaded, and close the store in the same `finally` that destroys the overlay.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -B -m pytest tests/test_run_persistence.py tests/test_run.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add ghostcursor/run.py tests/test_run_persistence.py
git commit -m "feat: persist learned observations and hydrate them before a tour"
```

---

### Task 6: The end-to-end proof — two real processes

The milestone's headline claim, proved the only way that actually counts: a second OS process, started fresh, grounding by an id the first one learned.

**Files:**
- Create: `tests/persistence_child.py` (the script each subprocess runs)
- Create: `tests/test_persistence_e2e.py`

**Interfaces:**
- Consumes: everything above

- [ ] **Step 1: Write the failing test**

```python
# tests/test_persistence_e2e.py
"""Two real processes, one shared database.

Reopening a connection in-process proves the storage layer. It does not prove
a second LAUNCH works, because module state and DPI awareness are already
warm. This spawns actual subprocesses so the claim being made — a recipe grows
stronger across restarts — is the claim being tested.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHILD = REPO / "tests" / "persistence_child.py"


def _run_child(db_path: Path) -> dict:
    env = dict(os.environ, GHOSTCURSOR_KB_PATH=str(db_path), PYTHONPATH=str(REPO))
    result = subprocess.run(
        [sys.executable, "-B", str(CHILD)],
        capture_output=True, text=True, timeout=120, env=env, cwd=str(REPO),
    )
    assert result.returncode == 0, f"child failed:\n{result.stdout}\n{result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_second_process_grounds_by_the_id_the_first_one_learned(tmp_path):
    db = tmp_path / "kb.sqlite"

    first = _run_child(db)
    assert first["grounded"] is True
    assert first["hydrated"] == 0, "nothing should exist before the first run"
    assert first["rung"] in (2, 3), f"first run must learn by name, got rung {first['rung']}"
    assert first["automation_id"] == "1001"

    assert db.exists(), "the first run did not create the database"

    second = _run_child(db)
    assert second["grounded"] is True
    assert second["hydrated"] >= 1, "the second run loaded nothing from disk"
    assert second["rung"] == 1, (
        f"second run should ground by AutomationId, got rung {second['rung']}"
    )
    assert second["automation_id"] == "1001"


def test_deleting_the_database_makes_the_system_relearn(tmp_path):
    db = tmp_path / "kb.sqlite"
    _run_child(db)
    assert _run_child(db)["rung"] == 1

    db.unlink()  # the documented user-facing erase path

    relearned = _run_child(db)
    assert relearned["hydrated"] == 0
    assert relearned["rung"] in (2, 3), "learning survived deletion of the store"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m pytest tests/test_persistence_e2e.py -v`
Expected: FAIL — `tests/persistence_child.py` does not exist

- [ ] **Step 3: Write the child script**

```python
# tests/persistence_child.py
"""One "run" of the system, for the cross-process persistence proof.

Opens the synthetic app, hydrates from the shared store, grounds one step,
persists what it learned, and prints a JSON line describing what happened.
Draws no overlay: this proves persistence, and the overlay is covered by the
pixel harnesses.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ghostcursor.memory.store import ObservationStore
from ghostcursor.perception.appinfo import app_info_for_window
from ghostcursor.reasoning import grounding
from ghostcursor.reasoning.schema import (
    ClaimedDescriptor, Recipe, Risk, Step, TargetDescriptor,
    UserAction, VerificationKind, VerificationRule,
)
from ghostcursor.run import hydrate_recipe, persist_step
from tests.uia_app import SyntheticApp


def build_recipe() -> Recipe:
    return Recipe(
        app_id="synthetic", intent="export a file",
        steps=[Step(
            user_action=UserAction.CLICK,
            target_descriptor=TargetDescriptor(
                claimed=ClaimedDescriptor(name="Export", visual_description="left column")
            ),
            instruction_text="Click Export.",
            verification_rule=VerificationRule(kind=VerificationKind.USER_CONFIRMS),
            risk=Risk.NORMAL,
        )],
    )


def main() -> int:
    recipe = build_recipe()
    step = recipe.steps[0]

    with SyntheticApp() as app:
        title_re = f".*{app.title}.*"
        info = app_info_for_window(title_re)
        app_id = info.app_id if info else "unknown.exe"
        app_version = info.version if info else "unknown"

        with ObservationStore() as store:  # path comes from GHOSTCURSOR_KB_PATH
            hydrated = hydrate_recipe(recipe, app_id, store)
            grounded = grounding.ground(step, title_re, app_version=app_version)
            if grounded is not None:
                grounding.promote(step, grounded, app_version=app_version, locale="en-US")
                persist_step(recipe.intent, step, app_id, store)

    print(json.dumps({
        "hydrated": hydrated,
        "grounded": grounded is not None,
        "rung": grounded.rung if grounded else None,
        "automation_id": grounded.automation_id if grounded else None,
        "app_version": app_version,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -B -m pytest tests/test_persistence_e2e.py -v`
Expected: 2 passed

If the child fails, read its captured stdout/stderr from the assertion message — do not weaken the rung assertions to make the test green. Rung 1 on the second run IS the milestone.

- [ ] **Step 5: Run the whole suite and commit**

```bash
python -B -m pytest tests/ -v
git add tests/persistence_child.py tests/test_persistence_e2e.py
git commit -m "test: prove learned ids survive across real process restarts"
```

---

### Task 7: Documentation and the user-facing erase path

**Files:**
- Modify: `FLOW.md`, `DECISIONS.md`, `CLAUDE.md`

- [ ] **Step 1: Update FLOW.md**

Add the persistence path to the guided-tour call graph: `app_info_for_window` → `ObservationStore` → `hydrate_recipe` before the tour, `persist_step` inside the grounder, store closed in the same `finally` as the overlay. Update the "you are here" marker: promotion now survives process exit; the doc-ingestion knowledge base (spec §8) remains unbuilt.

- [ ] **Step 2: Add DECISIONS.md entries**

Append D015–D017, matching the existing entries' format and depth:
- **D015** — observation selection: exact → nearest lower → unknown, and why strict version equality was rejected (it would discard every learned id on each patch bump); the `control_type` cross-check on non-exact matches, and the asymmetry that justifies it (failing to ground is visible and recoverable; mis-grounding teaches something false silently).
- **D016** — `step_key` derivation: why `(intent, step_index)` is unusable, why `name_synonyms` is excluded and `visual_description` included, and that editing the claimed descriptor orphans observations by design.
- **D017** — the store is the first screen-derived data written to disk: local only, no telemetry, no sync, `%LOCALAPPDATA%\GhostCursor\kb.sqlite`, deletable by removing the file.

- [ ] **Step 3: Document the erase path in CLAUDE.md**

Under the Tests/Running sections, add a short "Stored data" note: what the KB records, where it lives, that `GHOSTCURSOR_KB_PATH` overrides it for tests, and that deleting the file erases everything and makes the system re-learn.

- [ ] **Step 4: Verify and commit**

```bash
python -B -m pytest tests/ -v
git add FLOW.md DECISIONS.md CLAUDE.md
git commit -m "docs: record persistence decisions and the erase path"
```

---

## Self-Review

**Spec coverage.** §9 selection ladder → Task 4 (`select_observations`); §9 cross-check → Task 4 (rung-1 rewrite); §9 `step_key` → Task 2; §9 version detection → Task 1; §9 privacy → Tasks 3 and 7; §10 `observations` table incl. the idempotent primary key → Task 3; §13 task 4 persist → Task 5; §13 task 5 hydrate → Task 5; §13 task 7 tests → Tasks 4 and 6. The parked cross-version union problem is closed by Task 4 and the R13 unbounded-growth problem by Task 3's primary key.

**Explicitly out of scope, by design:** web search, doc ingestion, embeddings, intent matching, distillation, OCR, VLM. No task touches them.

**Placeholder scan.** No TBD/TODO markers; every code step contains complete, runnable content. Task 7 is prose because it is documentation, and each bullet names the specific content required.

**Type consistency.** `ConfirmedObservation` field names match between `schema.py`, Task 3's SQL columns and Task 4's selection. `AppInfo.app_id`/`.version` are used identically in Tasks 1, 5, 6. `store.record(step_key, app_id, observation)` and `store.observations_for(step_key, app_id)` match every call site. `ground(..., app_version=)` matches Task 5's grounder and Task 6's child script. `hydrate_recipe(recipe, app_id, store)` and `persist_step(intent, step, app_id, store)` are used consistently in Tasks 5 and 6.

**One risk worth naming.** Task 4 changes `ground()`'s rung-1 behaviour, and existing `test_grounding.py` / `test_promotion.py` construct observations with assorted `app_version` values. Those calls pass no `app_version`, which routes to the "unknown running version" branch where every observation is usable and only the cross-check applies — so they should keep passing. Task 4's step 4 checks exactly that, and instructs the implementer to reason rather than weaken if any fail.
