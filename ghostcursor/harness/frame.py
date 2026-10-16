"""The observation frame: real controls from every bound window, for a model.

A frame is an immutable snapshot of the candidates the harness OBSERVED, across
all bound windows. A model may only refer to a candidate by its frame-local id
(``c1``, ``c2``...). The harness keeps each candidate's UIA runtime id and
rectangle; the model never sees them.

Freshness is by identity, not by frame id (spec review B1): before anything is
drawn, the chosen candidate is re-resolved to exactly one control with the same
runtime id in the same window of the LATEST frame, still enabled and on screen,
its rectangle within a tolerance of where it was chosen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from ghostcursor.harness.binding import WindowBinding
from ghostcursor.providers.envelope import Tainted, sanitize

#: Control types a guidance step may point at (spec section 3).
ALLOWED_TYPES = frozenset(
    {
        "Button",
        "SplitButton",
        "MenuItem",
        "TabItem",
        "ListItem",
        "TreeItem",
        "CheckBox",
        "RadioButton",
        "ComboBox",
        "Hyperlink",
        "Edit",
    }
)

#: Initial cap on candidates per frame, to be fitted on the corpus (spec 3).
MAX_CANDIDATES = 150

Rect = tuple[int, int, int, int]

#: What a model sees instead of a name that reveals a document (D167): a
#: window title never leaves the machine (spec section 7), and a tab or item
#: naming a file is the same information.
HIDDEN_NAME = "(document name hidden)"
#: A control with no accessible name, kept only when pictures may be sent (D179).
UNNAMED = "(no name; see its outline in the picture)"
_FILE_NAME = re.compile(r"\.[A-Za-z0-9]{1,5}\b")
_UNSAVED = re.compile(r"\b(modified|unsaved|edited)\.?$", re.IGNORECASE)


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def reveals_document(name: str, control_type: str, title: str) -> bool:
    """True for a name that looks like a file or document: a file extension,
    an unsaved-changes marker, or a tab whose name appears in its window's
    title. Errs toward hiding; the model can still choose the candidate."""

    if _FILE_NAME.search(name) or _UNSAVED.search(name):
        return True
    norm = _norm(name)
    return control_type == "TabItem" and len(norm) >= 4 and norm in _norm(title)


@dataclass(frozen=True)
class RawControl:
    """One control as read on the perception worker (primitives only)."""

    runtime_id: tuple[int, ...]
    name: str
    control_type: str
    rect: Rect
    enabled: bool
    offscreen: bool
    is_password: bool = False
    #: Selection/toggle/expand state, e.g. ``"selected=1"``; local only, used
    #: to verify CHOSEN_STATE_CHANGES (spec section 5).
    state: str = ""
    focused: bool = False


@dataclass(frozen=True)
class WindowObservation:
    binding: WindowBinding
    window_rect: Rect
    controls: tuple[RawControl, ...]
    timed_out: bool = False
    minimized: bool = False
    #: Local-only facts for verification; never sent to a model.
    title: str = ""
    owned_windows: int = 0  # visible top-level windows of the bound PID


@dataclass(frozen=True)
class Candidate:
    cid: str
    window: str  # binding label, "w1"
    runtime_id: tuple[int, ...]
    name: str
    control_type: str
    rect: Rect
    region: str  # coarse position within its window, for the model
    state: str = ""
    focused: bool = False


@dataclass(frozen=True)
class ObservationFrame:
    frame_id: int
    at: float
    windows: tuple[WindowBinding, ...]
    candidates: tuple[Candidate, ...]
    truncated: bool
    incomplete: tuple[str, ...]  # window labels whose read hit its budget
    minimized: tuple[str, ...] = ()  # window labels that were minimized
    #: (label, title, owned_windows) per window; local only, for verification.
    facts: tuple[tuple[str, str, int], ...] = ()
    #: (label, window rectangle); local only, for redacted pictures (D179).
    window_rects: tuple[tuple[str, Rect], ...] = ()

    def get(self, cid: str) -> Candidate | None:
        return next((c for c in self.candidates if c.cid == cid), None)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(c.cid for c in self.candidates)

    def model_view(self) -> dict:
        """The tainted data a model may see: window labels and app names, and
        per candidate its window, type, name and coarse region. Every string
        is Tainted; no runtime id, rectangle, handle or title is included."""

        titles = {label: title for label, title, _ in self.facts}

        def shown(c: Candidate) -> str:
            hidden = reveals_document(c.name, c.control_type, titles.get(c.window, ""))
            return HIDDEN_NAME if hidden else c.name or UNNAMED

        return {
            "windows": {
                b.label: {
                    "application": Tainted.of("executable", b.identity.executable),
                    "state": Tainted.of(
                        "window_state",
                        "minimized" if b.label in self.minimized else "open",
                    ),
                }
                for b in self.windows
            },
            "candidates": {
                c.cid: {
                    "window": Tainted.of("window_label", c.window),
                    "type": Tainted.of("control_type", c.control_type),
                    "name": Tainted.of("uia_name", shown(c)),
                    "region": Tainted.of("region", c.region),
                }
                for c in self.candidates
            },
        }


def _valid(rect: Rect) -> bool:
    left, top, right, bottom = rect
    return right - left >= 4 and bottom - top >= 4


def _inside(rect: Rect, outer: Rect) -> bool:
    cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def region_of(rect: Rect, outer: Rect) -> str:
    """A 3x3 coarse position such as ``top-left`` or ``middle-center``."""

    width = max(1, outer[2] - outer[0])
    height = max(1, outer[3] - outer[1])
    cx = ((rect[0] + rect[2]) / 2 - outer[0]) / width
    cy = ((rect[1] + rect[3]) / 2 - outer[1]) / height
    column = "left" if cx < 1 / 3 else "center" if cx < 2 / 3 else "right"
    row = "top" if cy < 1 / 3 else "middle" if cy < 2 / 3 else "bottom"
    return f"{row}-{column}"


def build_frame(
    frame_id: int,
    at: float,
    observations: Sequence[WindowObservation],
    *,
    unnamed: bool = False,
) -> ObservationFrame:
    """Filter, deduplicate, order and cap the candidates of every bound window.
    ``unnamed`` keeps controls with no accessible name (icon-only buttons):
    only useful when Jev may see a picture of them (D179)."""

    kept: list[tuple[WindowBinding, RawControl, Rect]] = []
    for observation in sorted(observations, key=lambda o: o.binding.index):
        seen: set[tuple[int, ...]] = set()
        for control in observation.controls:
            name = sanitize(control.name, 120)
            if (
                control.control_type not in ALLOWED_TYPES
                or control.is_password
                or not control.enabled
                or control.offscreen
                or not (name or unnamed)
                or not control.runtime_id
                or not _valid(control.rect)
                or not _inside(control.rect, observation.window_rect)
                or control.runtime_id in seen
            ):
                continue
            seen.add(control.runtime_id)
            kept.append((observation.binding, control, observation.window_rect))
    kept.sort(key=lambda item: (item[0].index, item[1].rect[1], item[1].rect[0]))
    truncated = len(kept) > MAX_CANDIDATES
    candidates = tuple(
        Candidate(
            f"c{number}",
            binding.label,
            control.runtime_id,
            sanitize(control.name, 120),
            control.control_type,
            control.rect,
            region_of(control.rect, window_rect),
            control.state,
            control.focused,
        )
        for number, (binding, control, window_rect) in enumerate(
            kept[:MAX_CANDIDATES], start=1
        )
    )
    return ObservationFrame(
        frame_id,
        at,
        tuple(o.binding for o in sorted(observations, key=lambda o: o.binding.index)),
        candidates,
        truncated,
        tuple(o.binding.label for o in observations if o.timed_out),
        tuple(o.binding.label for o in observations if o.minimized),
        tuple((o.binding.label, o.title, o.owned_windows) for o in observations),
        tuple((o.binding.label, o.window_rect) for o in observations),
    )


def resolve(
    chosen: Candidate, latest: ObservationFrame, *, tolerance_px: int = 24
) -> Candidate | None:
    """The chosen control in the latest frame, or None.

    Exactly one candidate in the same window with the same runtime id, whose
    centre moved at most ``tolerance_px`` and whose size changed by less than
    half. Anything else means re-observe and re-ask -- never draw at an old
    rectangle (D069 exactly-one at render; spec review B1).
    """

    matches = [
        c
        for c in latest.candidates
        if c.window == chosen.window and c.runtime_id == chosen.runtime_id
    ]
    if len(matches) != 1:
        return None
    current = matches[0]
    old_cx, old_cy = (
        (chosen.rect[0] + chosen.rect[2]) / 2,
        (chosen.rect[1] + chosen.rect[3]) / 2,
    )
    new_cx, new_cy = (
        (current.rect[0] + current.rect[2]) / 2,
        (current.rect[1] + current.rect[3]) / 2,
    )
    if abs(new_cx - old_cx) > tolerance_px or abs(new_cy - old_cy) > tolerance_px:
        return None
    old_w, old_h = chosen.rect[2] - chosen.rect[0], chosen.rect[3] - chosen.rect[1]
    new_w, new_h = current.rect[2] - current.rect[0], current.rect[3] - current.rect[1]
    if not (0.5 < new_w / max(1, old_w) < 2 and 0.5 < new_h / max(1, old_h) < 2):
        return None
    return current
