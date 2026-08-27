"""Tier 1 perception: Windows UI Automation via pywinauto.

Reference: D:\\tracker\\docs\\ghostcursor\\python-uiautomation-for-windows-uiautomation.docx,
D:\\tracker\\docs\\ghostcursor\\pywinauto-windows-gui-automation-with-python.docx
"""

import os
import re
from dataclasses import dataclass, field

import win32gui
import win32process
from pywinauto import Desktop

from ghostcursor.overlay import dpi

# Windows parks minimized windows at (-32000, -32000). Anything at or beyond
# this is not on screen, and pointing at it draws the hint into the void.
_MINIMIZED_SENTINEL = -30000


def is_on_screen(bbox: tuple[int, int, int, int] | None) -> bool:
    """True if bbox is a real, non-degenerate rect that overlaps the desktop.

    Guards three separate failure modes seen in practice:
      * minimized windows, parked at (-32000, -32000);
      * degenerate zero-area rects;
      * windows dragged fully off the edge of the virtual desktop.
    """
    if bbox is None:
        return False

    left, top, right, bottom = bbox
    if left <= _MINIMIZED_SENTINEL or top <= _MINIMIZED_SENTINEL:
        return False
    if right - left <= 0 or bottom - top <= 0:
        return False

    vl, vt, vw, vh = dpi.virtual_screen_rect()
    overlaps_x = right > vl and left < vl + vw
    overlaps_y = bottom > vt and top < vt + vh
    return overlaps_x and overlaps_y


def windows_matching(title_re: str) -> list[int]:
    """HWNDs of visible, non-minimized, on-screen top-level windows whose
    title matches title_re, in z-order.

    The single place this enumeration lives. It was duplicated in
    perception/appinfo.py, and the two copies drifted: this one excluded
    minimized and off-screen windows (a hint cannot be drawn on one) while
    the copy did not — so a minimized window could supply the app identity
    that observations are persisted under, while grounding refused that same
    window. Identity and grounding must agree on which window they mean.
    """
    pattern = re.compile(title_re)
    matches: list[int] = []

    def _collect(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            return
        if pattern.search(win32gui.GetWindowText(hwnd)) and is_on_screen(
            win32gui.GetWindowRect(hwnd)
        ):
            matches.append(hwnd)

    try:
        win32gui.EnumWindows(_collect, None)
    except Exception:
        # A transient desktop/session access failure means "no visible
        # target" for this observation, not a worker-killing exception.
        return []
    return matches


def first_matching_hwnd(title_re: str) -> int:
    """The topmost visible, non-minimized, on-screen window matching title_re,
    or 0 when there is none.

    Warm-up is keyed on this, so it must agree with the window grounding walks
    on which window is meant. Both are GATED by the same windows_matching
    enumeration, but the walk (iter_elements) hands the final selection to
    pywinauto's Desktop().window(title_re=...), not to this function -- so
    with several matching windows the two can name different ones. The
    consequence is bounded: a sibling handle among the matches still gets its
    own warm-up patience, it is just not guaranteed to be the same handle
    grounding actually walked.
    """
    matches = windows_matching(title_re)
    return matches[0] if matches else 0


def _executable_name_for_hwnd(hwnd: int) -> str:
    """Owning executable basename, or an empty string when unavailable."""
    try:
        from ghostcursor.perception.appinfo import _exe_path_for_pid

        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        return os.path.basename(_exe_path_for_pid(pid) or "").casefold()
    except Exception:
        return ""


def windows_matching_executable(title_re: str, executable_name: str) -> list[int]:
    """Title matches whose owning executable also matches exactly."""
    expected = os.path.basename(executable_name).casefold()
    return [
        hwnd
        for hwnd in windows_matching(title_re)
        if _executable_name_for_hwnd(hwnd) == expected
    ]


def first_matching_hwnd_for_executable(title_re: str, executable_name: str) -> int:
    matches = windows_matching_executable(title_re, executable_name)
    return matches[0] if matches else 0


def _raw_window_rect(title_re: str) -> tuple[int, int, int, int] | None:
    """Fallback: raw win32gui geometry for a visible, non-minimized top-level
    window matching title_re, for the cases where UIA exposes no usable
    geometry at all."""
    for hwnd in windows_matching(title_re):
        return win32gui.GetWindowRect(hwnd)
    return None


def find_element(
    title_re: str, control_type: str | None = None, name_re: str | None = None
) -> tuple[int, int, int, int] | None:
    """Find one element in a top-level window matching title_re, optionally
    filtered by control_type ("Button", "Edit", ...) and name_re.

    Returns (left, top, right, bottom) in screen coordinates, or None if no
    window or no matching descendant was found.
    """
    try:
        window = Desktop(backend="uia").window(title_re=title_re)
        window.wait("exists", timeout=3)
    except Exception:
        return None

    candidates = (
        window.descendants(control_type=control_type)
        if control_type
        else window.descendants()
    )
    for ctrl in candidates:
        if name_re and name_re.lower() not in ctrl.window_text().lower():
            continue
        rect = ctrl.rectangle()
        bbox = (rect.left, rect.top, rect.right, rect.bottom)
        if is_on_screen(bbox):
            return bbox

    return None


def window_bbox(title_re: str) -> tuple[int, int, int, int] | None:
    """Fallback: bbox of the whole top-level window, when no specific
    descendant match is needed/found."""
    try:
        window = Desktop(backend="uia").window(title_re=title_re)
        window.wait("exists", timeout=3)
        rect = window.rectangle()
        bbox = (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        bbox = None

    if not is_on_screen(bbox):
        # Covers minimized, degenerate and off-desktop rects alike.
        return _raw_window_rect(title_re)
    return bbox


@dataclass(frozen=True)
class Element:
    """One on-screen UI element, normalised across perception tiers."""

    name: str
    control_type: str
    automation_id: str
    bbox: tuple[int, int, int, int]
    path: tuple[str, ...] = field(default=())
    #: Which perception tier produced this element. "uia" is a confirmed
    #: control; "ocr" is text read off pixels, which carries no AutomationId,
    #: no control_type, and no structural context. Everything downstream that
    #: decides how much to trust an element keys off THIS, not off which
    #: grounding rung matched it.
    #:
    #: Last field on purpose: existing call sites construct Element
    #: positionally, so an earlier insertion would silently shift them.
    source: str = field(default="uia")


# Codicons live in the Unicode Private Use Area. VS Code 1.134.0 prefixes one to
# the Welcome-page action name, so the accessible name is " Open Folder..."
# while the trusted recipe asks for "Open Folder..." -- an exact match misses,
# which is how that workflow's tier-1 perception went dark (D069).
_PRIVATE_USE_FIRST = 0xE000
_PRIVATE_USE_LAST = 0xF8FF


def normalise_accessible_name(name: str | None) -> str:
    """Strip a leading decorative icon codepoint and the space it leaves.

    Deliberately narrow. Only a LEADING private-use character is decoration;
    one anywhere else is part of the label. This is not a fuzzy matcher and
    must never lower the grounding floor -- it removes a glyph, nothing more.

    The observed glyph is normalised away rather than written into the recipe
    on purpose: a specific private-use codepoint is version-sensitive and would
    break the next time VS Code renumbers its icon font.
    """
    if not name:
        return ""
    index = 0
    while (
        index < len(name)
        and _PRIVATE_USE_FIRST <= ord(name[index]) <= _PRIVATE_USE_LAST
    ):
        index += 1
    if index == 0:
        return name
    return name[index:].lstrip()


#: The two declared normalisation strategies. `NONE` compares the observed name
#: byte for byte; `STRIP_LEADING_PRIVATE_USE` removes a leading Codicon glyph
#: first. A recipe declares which; neither is inferred from the name it sees.
NORMALISE_NONE = "none"
NORMALISE_STRIP_LEADING_PRIVATE_USE = "strip_leading_private_use"


def matches_trusted_name(
    observed: str | None,
    allowed_names,
    *,
    normalise: str = NORMALISE_STRIP_LEADING_PRIVATE_USE,
) -> bool:
    """True when an observed name equals a trusted name under `normalise`.

    Equality, never substring: rung 3 is the substring rung and OCR is barred
    from it so the floor is not decorative (D030). Normalisation must not
    reintroduce that looseness by the back door.

    `normalise` is the selector's declared strategy, not a property of the name
    observed. Open Terminal's certified walker accepts exactly `Toggle Panel
    (Ctrl+J)` and `Terminal Section` with no normalisation at all, so applying
    the glyph strip to it would broaden certified behaviour during migration --
    the one thing the migration is not allowed to do.
    """
    if normalise == NORMALISE_NONE:
        candidate = observed or ""
    else:
        candidate = normalise_accessible_name(observed)
    if not candidate:
        return False
    return any(candidate == name for name in allowed_names if name)


class ProviderQueryFault(RuntimeError):
    """A provider-side query failed in a way that is not a clean absence.

    Raised rather than returned so a caller cannot accidentally treat it like a
    false or empty result. That flattening is exactly what hid Open Folder's
    tier-1 perception going dark: the walk published an empty *successful*
    observation, indistinguishable from "nothing is on screen" (D069).
    """


class SelectorAmbiguityFault(ProviderQueryFault):
    """An action selector matched more than one control.

    A subclass so existing fault handling catches it without knowing the
    subtype, while an operator can still tell the two apart. Measured on live
    VS Code 1.134.0: the Explorer sidebar button and the Welcome-page action
    both matched the trusted Open Folder names, and silently taking the first
    would have pointed the user at the wrong control (D069).
    """


#: An ACTION selector must resolve to one control, because the hint points the
#: user at exactly one thing. Zero is a clean absence; more than one is a fault.
EXACTLY_ONE = "exactly_one"

#: A VERIFICATION selector may match several. "An Installed Section exists"
#: does not require choosing one control on the user's behalf.
AT_LEAST_ONE = "at_least_one"


def _is_dead_pointer(exc: BaseException) -> bool:
    """True when a property read failed because the element no longer exists.

    Measured on VS Code 1.134.0 with the installed UIA provider and comtypes
    1.4.16: `FindFirst` answers a condition that matched nothing with a
    non-`None` object whose every property access raises this, instead of
    returning `None`. That is an observation to defend against, not a contract
    the platform owes, so the predicate is deliberately narrow -- any OTHER
    ValueError is a fault, not an absence.

    The exception was also reproduced independently of VS Code, by accessing a
    plain null ``POINTER(IUnknown)``: comtypes raises ``builtins.ValueError``
    with args ``('NULL COM pointer access',)``. So the match is on comtypes'
    own null-pointer message, not on a VS Code quirk.
    """
    return isinstance(exc, ValueError) and "NULL COM pointer" in str(exc)


def _runtime_identity(info) -> object | None:
    """A live backend identity for one candidate, or `None` when unavailable.

    Deduplication must never use a serialized value. `Element` equality
    compares name, control type, AutomationId and bbox, and two genuinely
    different controls can agree on all four -- VS Code exposes empty
    AutomationIds and repeats accessible names across views. Only the backend
    can say "these are the same control", and only while the handle is live.

    Returning `None` is a real answer: it means identity could not be
    established, and the caller must then retain both candidates rather than
    guess.
    """
    for attribute in ("runtime_id", "handle"):
        try:
            value = getattr(info, attribute, None)
        except Exception:  # noqa: BLE001 - an unreadable identity is no identity
            return None
        if value:
            return (
                attribute,
                tuple(value) if isinstance(value, (list, tuple)) else value,
            )
    return None


@dataclass(frozen=True)
class Candidate:
    """One observed control, still paired with its live backend identity.

    `Element` is the frozen value that crosses the worker boundary (D021) and
    deliberately carries no backend identity. That makes it the wrong thing to
    deduplicate: two genuinely different controls can agree on name, control
    type, AutomationId and bbox. So identity is kept beside the element for as
    long as the observation stays worker-side -- through cardinality, through
    the published union -- and is dropped only when the elements cross to the
    UI thread.

    `identity` is `None` when the backend could not supply one. That is a real
    answer, not a missing value, and every consumer must then retain the
    candidate rather than guess it is a duplicate.
    """

    identity: object | None
    element: Element


def deduplicated(candidates) -> list[Candidate]:
    """Collapse candidates the backend proves are the same control.

    Identity-bearing duplicates collapse; identity-less candidates are all
    retained. Never a value comparison: collapsing on value would hide a real
    second match from the cardinality check, which is the one thing that check
    exists to catch.
    """
    seen: list[object] = []
    kept: list[Candidate] = []
    for candidate in candidates:
        if candidate.identity is not None and candidate.identity in seen:
            continue
        seen.append(candidate.identity)
        kept.append(candidate)
    return kept


def apply_cardinality(
    candidates,
    *,
    cardinality: str,
    limit: int | None = None,
    label: str = "action selector",
) -> list[Candidate]:
    """Judge one selector's declared cardinality over its own candidates.

    Separated from the read so several selectors can judge one shared read
    independently. Grouping selectors by query is a cost decision; it must
    never merge their answers, and it must never re-read the screen per
    selector -- two reads within one tick can observe two different screens,
    so two selectors on one compiled query could then disagree about how many
    controls exist.

    Cardinality BEFORE the limit. Both faults would fire on a one-limit
    selector that matched twice, and ambiguity is the more specific answer: it
    says the filter names two controls, where the limit only says there were
    more results than allowed.
    """
    chosen = list(candidates)

    if cardinality == EXACTLY_ONE and len(chosen) > 1:
        described = ", ".join(f"{c.element.name!r}@{c.element.bbox}" for c in chosen)
        raise SelectorAmbiguityFault(
            f"{label} matched {len(chosen)} controls, expected one: {described}"
        )

    # Raise, never truncate. Truncating discarded matches before the ambiguity
    # check could see them, so a one-limit selector matching two controls
    # returned the first one silently -- the exact "silently taking the first"
    # failure the cardinality rule exists to prevent. The limit bounds how many
    # trusted results a recipe may claim, not how long the read may take.
    if limit is not None and len(chosen) > limit:
        raise ProviderQueryFault(
            f"{label} matched {len(chosen)} controls, over the result limit of {limit}"
        )
    return chosen


def element_array_items(array) -> list:
    """Adapt an `IUIAutomationElementArray` to a plain list of raw elements.

    `FindAll` returns a COM array, not a Python sequence. Converting here keeps
    :func:`provider_exact` injectable with an ordinary list in tests while the
    live path still reads `Length` and `GetElement` exactly once each.
    """
    return [array.GetElement(index) for index in range(array.Length)]


def provider_candidates(find_all, make_info) -> list[Candidate]:
    """Perform ONE provider `FindAll` and classify every result.

    The read half of :func:`provider_exact`, separated so that several
    selectors sharing one compiled query judge a single read rather than each
    triggering their own. Two reads inside one tick can observe two different
    screens, so per-selector reads let two selectors on the same query
    disagree about how many controls exist -- a divergence no caller could
    detect, because each read is individually consistent.

    Returns candidates with identity attached and backend-proven duplicates
    already collapsed. It applies no cardinality: that belongs to the
    selector, not the query.
    """
    try:
        raw_items = list(find_all())
    except Exception as exc:  # noqa: BLE001 - re-raised as a typed fault
        raise ProviderQueryFault(f"provider query failed: {exc}") from exc

    candidates: list[Candidate] = []
    for raw in raw_items:
        if raw is None:
            continue
        try:
            info = make_info(raw)
            name = info.name or ""
            control_type = info.control_type or ""
            automation_id = info.automation_id or ""
            rect = info.rectangle
            bbox = (rect.left, rect.top, rect.right, rect.bottom)
            identity = _runtime_identity(info)
        except Exception as exc:  # noqa: BLE001 - classified below
            if _is_dead_pointer(exc):
                continue
            raise ProviderQueryFault(f"provider property read failed: {exc}") from exc

        candidates.append(
            Candidate(
                identity=identity,
                element=Element(
                    name=name,
                    control_type=control_type,
                    automation_id=automation_id,
                    bbox=bbox,
                    path=(control_type,),
                ),
            )
        )
    return deduplicated(candidates)


def provider_exact(
    find_all, make_info, *, cardinality: str = EXACTLY_ONE
) -> list[Element]:
    """Resolve one provider-side query into presence, absence, or a fault.

    `find_all()` performs the **FindAll** and returns a sequence of raw
    results; `make_info(raw)` wraps one so its properties can be read. Both are
    injected so the presence rule can be tested without a live UIA provider.

        empty result set             -> []        (clean absence)
        properties read              -> [Element] (present)
        NULL COM pointer on read     -> skipped   (died between call and read)
        any other failure            -> ProviderQueryFault
        several matches, exactly_one -> SelectorAmbiguityFault

    **Never `FindFirst`.** It returns one element and cannot report that a
    second exists, so `exactly_one` is unprovable with it -- and on a match of
    nothing it answers with a non-`None` object whose every property access
    raises, which is a dead pointer rather than an honest absence. `FindAll`
    reports `Length = 0` for a genuine absence and counts, so it can prove
    cardinality. Length alone still carries no information about any one
    element: only a successful property read establishes presence, which is why
    a result whose read dies is dropped rather than counted.
    """
    chosen = apply_cardinality(
        provider_candidates(find_all, make_info),
        cardinality=cardinality,
        label="provider selector",
    )
    return [candidate.element for candidate in chosen]


#: Ceiling on how many elements one bounded walk may publish. Measured Button
#: counts on VS Code 1.134.0 were 17-44 across three UI states, so a trusted
#: recipe selecting more than a handful means the filter is wrong, not that the
#: screen is busy.
DEFAULT_DESCENDANT_LIMIT = 16


def bounded_candidates(
    walk,
    allowed_names,
    *,
    limit: int = DEFAULT_DESCENDANT_LIMIT,
    cardinality: str = AT_LEAST_ONE,
    normalise: str = NORMALISE_STRIP_LEADING_PRIVATE_USE,
) -> list[Candidate]:
    """Select trusted controls from a bounded, control-type-scoped walk.

    The second declared selector strategy. Measured on VS Code 1.134.0: the
    Welcome-page Open Folder action reads cleanly here (5/5, stable bbox) while
    provider-side exact lookup returns a dead pointer for it, so the two
    strategies are not interchangeable and a recipe must declare which it uses.

    Matching follows the selector's declared `normalise` strategy, so a Codicon
    prefix cannot defeat a selector that declares the strip -- and cannot be
    silently tolerated by one that declares `none`. Either way the element
    publishes the RAW observed name: a cleaned-up name would make the
    observation disagree with the screen, and every downstream trust decision
    keys off the observation.

    Per-control failures follow the same three-branch rule as
    :func:`provider_exact`. A control that died mid-walk is a clean absence and
    is skipped; anything else is a fault for the whole walk, because silently
    dropping it is how a dark tier stays invisible.
    """
    try:
        controls = list(walk())
    except Exception as exc:  # noqa: BLE001 - re-raised as a typed fault
        raise ProviderQueryFault(f"bounded walk failed: {exc}") from exc

    selected: list[Candidate] = []
    for control in controls:
        try:
            name = control.window_text() or ""
            if not matches_trusted_name(name, allowed_names, normalise=normalise):
                continue
            rect = control.rectangle()
            bbox = (rect.left, rect.top, rect.right, rect.bottom)
            info = control.element_info
            control_type = info.control_type or ""
            automation_id = info.automation_id or ""
            identity = _runtime_identity(info)
        except Exception as exc:  # noqa: BLE001 - classified below
            if _is_dead_pointer(exc):
                continue
            raise ProviderQueryFault(f"bounded walk read failed: {exc}") from exc

        if not is_on_screen(bbox):
            continue
        selected.append(
            Candidate(
                identity=identity,
                element=Element(
                    name=name,
                    control_type=control_type,
                    automation_id=automation_id,
                    bbox=bbox,
                    path=(control_type,),
                ),
            )
        )

    # Shared-traversal candidates deduplicate on live backend identity only.
    # Two selectors over one walk can reach the same control, and value
    # equality cannot tell that from two distinct controls that happen to
    # agree on every published field.
    return apply_cardinality(
        deduplicated(selected),
        cardinality=cardinality,
        limit=limit,
        label="bounded selector",
    )


def bounded_descendants(walk, allowed_names, **kwargs) -> list[Element]:
    """:func:`bounded_candidates` for callers that need only the elements.

    Backend identity is dropped here on purpose: a caller taking plain
    elements has left the worker-side window in which identity is meaningful,
    and a stale identity is worse than none.
    """
    return [candidate.element for candidate in bounded_candidates(walk, allowed_names, **kwargs)]


def iter_elements(title_re: str) -> list[Element]:
    """Every on-screen element inside the window matching title_re.

    Off-screen and degenerate elements are filtered out — window chrome
    frequently reports (0, 0, 0, 0), which would otherwise ground a hint into
    the corner of the desktop.
    """
    # Ask the cheap question first. windows_matching is an EnumWindows scan
    # costing ~0.1ms; pywinauto's wait("exists", timeout=3) costs ~50ms when
    # the window IS there and a full 3 seconds when it is not. With three
    # perception calls per tick, an absent target — the user simply alt-tabbed
    # — blocked a tick for ~9.1 seconds, and ESC is only polled between ticks,
    # so the overlay sat on screen un-dismissable for that whole time.
    #
    # No wait() below either: existence is already established here, and the
    # window can still vanish between this check and the walk, which the
    # except clause handles. Waiting cannot close that race, only pay for it.
    if not windows_matching(title_re):
        return []

    try:
        window = Desktop(backend="uia").window(title_re=title_re)
        descendants = window.descendants()
    except Exception:
        # The window went away mid-walk, or exposes no usable UIA tree.
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


#: The Welcome-page action, in the spellings VS Code has used. The observed
#: Codicon prefix is deliberately NOT listed: a private-use codepoint is
#: version-sensitive, so it is normalised away at match time instead (D069).
#:
#: NARROWER than the recipe's synonyms, on purpose. The recipe also accepts a
#: bare "Open Folder", but live VS Code 1.134.0 shows two Open Folder
#: affordances: the Explorer sidebar button at (39, 263, 359, 297), named plain
#: "Open Folder", and the Welcome-page action at (527, 238, 677, 277), which
#: carries the ellipsis. Both matched, and grounding took the first -- the
#: sidebar one -- which is not the validated target. Only the ellipsis
#: spellings identify the action this recipe was certified against.
_VSCODE_OPEN_FOLDER_NAMES = ("Open Folder...", "Open Folder…")


def _vscode_button_walk(hwnd: int):
    """Bounded Button descendants of one Code.exe window.

    Module level so the COM call is one seam. Never the generic full-tree walk:
    that is the stall this project measured and narrowed away from.
    """
    window = Desktop(backend="uia").window(handle=hwnd)
    return window.descendants(control_type="Button")


def iter_vscode_elements(title_re: str) -> list[Element]:
    """Minimal UIA perception for the trusted VS Code open-folder workflow.

    Uses the bounded-descendants strategy. It previously used a provider-side
    exact query, which on VS Code 1.134.0 returns a dead COM pointer for this
    target while the Button walk reads it cleanly (5/5, stable bbox) -- so the
    workflow had silently fallen back to OCR for its grounding (D069).

    A clean absence still returns an empty successful observation, which is what
    lets executable-bounded OCR escalate for the same trusted target. A genuine
    provider fault now raises rather than masquerading as an empty screen.
    """
    matches = windows_matching_executable(title_re, "code.exe")
    if not matches:
        return []
    hwnd = matches[0]
    return bounded_descendants(
        lambda: _vscode_button_walk(hwnd),
        _VSCODE_OPEN_FOLDER_NAMES,
        cardinality=EXACTLY_ONE,
    )


_VSCODE_TERMINAL_BUTTONS = {
    "Toggle Panel (Ctrl+J)",
    "Terminal Section",
}


def iter_vscode_terminal_elements(title_re: str) -> list[Element]:
    """Trusted UIA surface for the VS Code integrated-terminal workflow.

    Electron exposes the title-bar Toggle Panel control and the visible
    terminal section as Buttons, but neither has a stable AutomationId. Walk
    only Buttons and publish only these two hand-approved exact names. The
    walk remains on the bounded perception worker; a slow Electron provider
    therefore cannot freeze ESC or the control rail.
    """

    matches = windows_matching_executable(title_re, "code.exe")
    if not matches:
        return []
    try:
        window = Desktop(backend="uia").window(handle=matches[0])
        controls = window.descendants(control_type="Button")
    except Exception:
        return []

    elements: list[Element] = []
    for control in controls:
        try:
            name = control.window_text() or ""
            if name not in _VSCODE_TERMINAL_BUTTONS:
                continue
            rect = control.rectangle()
            bbox = (rect.left, rect.top, rect.right, rect.bottom)
            if not is_on_screen(bbox):
                continue
            info = control.element_info
            elements.append(
                Element(
                    name=name,
                    control_type=info.control_type or "",
                    automation_id=info.automation_id or "",
                    bbox=bbox,
                    path=(info.control_type or "",),
                )
            )
        except Exception:
            continue
    return elements
