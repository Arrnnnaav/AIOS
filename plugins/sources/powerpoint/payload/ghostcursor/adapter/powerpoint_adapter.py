"""Signed GhostCursor PowerPoint adapter (JSONL protocol v1).

This process receives only operations from the signed closed registry.  It has
no planner, model, workflow matcher, or generic input-synthesis facility.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from pathlib import Path


#: Thinnest region worth ringing, in screen pixels.
_MIN_REGION_PX = 4

PLUGIN_ID = "ghostcursor.powerpoint"
PLUGIN_VERSION = "1.0.0"
_ID_RE = re.compile(r"[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*")
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}")
_ANIMATION_EFFECTS = {
    "entrance": {"appear", "fade", "fly_in", "wipe", "zoom"},
    "emphasis": {"pulse", "grow_shrink", "spin", "color_change"},
    "exit": {"disappear", "fade", "fly_out", "wipe_exit"},
    "motion": {"line", "arc"},
}


class Refusal(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _exact(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise Refusal(f"{label} fields are invalid")


def _identifier(value, label):
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise Refusal(f"{label} is invalid")
    return value


def _text(value, label, limit=4000):
    if not isinstance(value, str) or not value or len(value) > limit:
        raise Refusal(f"{label} is invalid")
    return value


def _number(value, label, low=0.0, high=1000.0, *, positive=False):
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        raise Refusal(f"{label} is invalid")
    value = float(value)
    if value < low or value > high or (positive and value <= 0):
        raise Refusal(f"{label} is outside its bounded range")
    return value


def _integer(value, label, low=0, high=1000):
    if type(value) is not int or value < low or value > high:
        raise Refusal(f"{label} is invalid")
    return value


def _color(value, label):
    if not isinstance(value, str) or _COLOR_RE.fullmatch(value) is None:
        raise Refusal(f"{label} is invalid")
    return value.upper()


def _enum(value, allowed, label):
    if value not in allowed:
        raise Refusal(f"{label} is invalid")
    return value


def _path(value, expected):
    if not isinstance(value, str) or Path(value).resolve() != Path(expected).resolve():
        raise Refusal("operation output path disagrees with approved output")
    if Path(value).suffix.casefold() != ".pptx":
        raise Refusal("PowerPoint output must be .pptx")
    return str(Path(value).resolve())


def _chart_data(categories_raw, series_raw):
    try:
        categories = json.loads(categories_raw)
        series = json.loads(series_raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise Refusal("chart data must be canonical JSON") from exc
    if _canonical(categories) != categories_raw or _canonical(series) != series_raw:
        raise Refusal("chart data must be canonical JSON")
    if (
        not isinstance(categories, list)
        or not 1 <= len(categories) <= 12
        or not all(isinstance(item, str) and 0 < len(item) <= 40 for item in categories)
        or not isinstance(series, list)
        or not 1 <= len(series) <= 4
    ):
        raise Refusal("chart data dimensions are invalid")
    for item in series:
        if not isinstance(item, dict) or set(item) != {"name", "values"}:
            raise Refusal("chart series fields are invalid")
        if not isinstance(item["name"], str) or not 0 < len(item["name"]) <= 40:
            raise Refusal("chart series name is invalid")
        values = item["values"]
        if (
            not isinstance(values, list)
            or len(values) != len(categories)
            or any(type(value) not in {int, float} or not math.isfinite(float(value)) for value in values)
        ):
            raise Refusal("chart series values are invalid")
    return categories, series


class PlanValidator:
    def __init__(self, context):
        _exact(context, {"output_path", "target"}, "session context")
        _exact(
            context["target"],
            {"executable", "executable_version", "hwnd", "pid"},
            "session target",
        )
        if context["target"]["executable"] != "powerpnt.exe":
            raise Refusal("PowerPoint adapter requires powerpnt.exe authority")
        if type(context["target"]["hwnd"]) is not int or context["target"]["hwnd"] <= 0:
            raise Refusal("PowerPoint HWND is invalid")
        self.context = context
        self.width = 0.0
        self.height = 0.0
        self.created = False
        self.themed = False
        self.saved = False
        self.slides = {}
        self.animation_orders = {}

    def validate(self, nodes):
        if not isinstance(nodes, list) or not 3 <= len(nodes) <= 512:
            raise Refusal("PowerPoint plan size is invalid")
        for ordinal, node in enumerate(nodes, 1):
            _exact(node, {"node_id", "operation_id", "parameters"}, "plan node")
            _identifier(node["node_id"], "node id")
            method = getattr(self, "validate_" + node["operation_id"].replace(".", "_"), None)
            if method is None:
                raise Refusal(f"unsupported PowerPoint operation {node['operation_id']!r}")
            if not isinstance(node["parameters"], dict):
                raise Refusal("operation parameters are invalid")
            method(node["parameters"])
        if not self.saved or not any(node["operation_id"] == "powerpoint.inspect_presentation" for node in nodes):
            raise Refusal("PowerPoint plan must save and inspect its complete output")

    def _box(self, p):
        left = _number(p["left"], "left", 0, self.width)
        top = _number(p["top"], "top", 0, self.height)
        width = _number(p["width"], "width", 0, self.width, positive=True)
        height = _number(p["height"], "height", 0, self.height, positive=True)
        if left + width > self.width + 0.01 or top + height > self.height + 0.01:
            raise Refusal("object escapes the slide canvas")

    def _new_object(self, p):
        slide_id = _identifier(p["slide_id"], "slide id")
        object_id = _identifier(p["object_id"], "object id")
        if slide_id not in self.slides:
            raise Refusal(f"unknown slide {slide_id!r}")
        if object_id in self.slides[slide_id]:
            raise Refusal(f"duplicate object {object_id!r} on slide {slide_id!r}")
        if len(self.slides[slide_id]) >= 80:
            raise Refusal("slide object limit exceeded")
        self.slides[slide_id].add(object_id)
        return slide_id, object_id

    def validate_powerpoint_create_presentation(self, p):
        _exact(p, {"height", "output_path", "width"}, "create presentation")
        if self.created:
            raise Refusal("presentation may be created only once")
        self.width = _number(p["width"], "slide width", 10, 20, positive=True)
        self.height = _number(p["height"], "slide height", 5, 12, positive=True)
        output = _path(p["output_path"], self.context["output_path"])
        if Path(output).exists():
            raise Refusal("approved output already exists")
        self.created = True

    def validate_powerpoint_set_theme(self, p):
        _exact(p, {"accent_color", "background_color", "body_font", "error_color", "heading_font", "primary_text_color", "secondary_text_color", "success_color", "surface_color", "warning_color"}, "theme")
        if not self.created or self.themed:
            raise Refusal("theme must follow presentation creation exactly once")
        for name, value in p.items():
            _text(value, name, 80) if name.endswith("font") else _color(value, name)
        self.themed = True

    def validate_powerpoint_add_slide(self, p):
        _exact(p, {"background_color", "slide_id"}, "slide")
        if not self.themed or self.saved:
            raise Refusal("slides must be added after theme and before save")
        slide_id = _identifier(p["slide_id"], "slide id")
        _color(p["background_color"], "slide background")
        if slide_id in self.slides or len(self.slides) >= 40:
            raise Refusal("slide id is duplicate or slide limit is exceeded")
        self.slides[slide_id] = set()

    def validate_powerpoint_add_text(self, p):
        _exact(p, {"align", "bold", "color", "font_family", "font_size", "height", "left", "object_id", "slide_id", "text", "top", "transparency", "vertical_align", "width"}, "text")
        self._new_object(p); self._box(p)
        _text(p["text"], "text"); _text(p["font_family"], "font family", 80)
        _number(p["font_size"], "font size", 8, 120, positive=True)
        _color(p["color"], "text color")
        if type(p["bold"]) is not bool: raise Refusal("bold is invalid")
        _enum(p["align"], {"left", "center", "right"}, "alignment")
        _enum(p["vertical_align"], {"top", "middle", "bottom"}, "vertical alignment")
        _number(p["transparency"], "text transparency", 0, 1)

    def validate_powerpoint_add_shape(self, p):
        _exact(p, {"fill_color", "fill_transparency", "height", "left", "line_color", "line_weight", "object_id", "shape_kind", "slide_id", "top", "width"}, "shape")
        self._new_object(p); self._box(p)
        _enum(p["shape_kind"], {"rectangle", "rounded_rectangle", "ellipse", "chevron", "hexagon", "arc"}, "shape kind")
        _color(p["fill_color"], "shape fill"); _color(p["line_color"], "shape line")
        _number(p["fill_transparency"], "fill transparency", 0, 1)
        _number(p["line_weight"], "line weight", 0, 10)

    def validate_powerpoint_add_line(self, p):
        _exact(p, {"begin_arrow", "color", "dash", "end_arrow", "object_id", "slide_id", "weight", "x1", "x2", "y1", "y2"}, "line")
        self._new_object(p)
        for name, high in (("x1", self.width), ("x2", self.width), ("y1", self.height), ("y2", self.height)):
            _number(p[name], name, 0, high)
        _color(p["color"], "line color"); _number(p["weight"], "line weight", 0.1, 10, positive=True)
        _enum(p["dash"], {"solid", "dash", "dot"}, "line dash")
        _enum(p["begin_arrow"], {"none", "triangle"}, "begin arrow")
        _enum(p["end_arrow"], {"none", "triangle"}, "end arrow")

    def validate_powerpoint_add_chart(self, p):
        _exact(p, {"categories_json", "chart_kind", "height", "left", "object_id", "series_json", "slide_id", "title", "top", "width"}, "chart")
        self._new_object(p); self._box(p); _text(p["title"], "chart title", 120)
        _enum(p["chart_kind"], {"bar", "column", "line"}, "chart kind")
        _chart_data(p["categories_json"], p["series_json"])

    def validate_powerpoint_add_notes(self, p):
        _exact(p, {"slide_id", "text"}, "notes")
        slide_id = _identifier(p["slide_id"], "slide id")
        if slide_id not in self.slides: raise Refusal("notes name an unknown slide")
        _text(p["text"], "notes", 8000)

    def validate_powerpoint_add_animation(self, p):
        _exact(p, {"category", "delay_s", "direction", "duration_s", "effect", "object_id", "order", "slide_id", "trigger"}, "animation")
        slide_id = _identifier(p["slide_id"], "slide id"); object_id = _identifier(p["object_id"], "object id")
        if slide_id not in self.slides or object_id not in self.slides[slide_id]: raise Refusal("animation target does not exist")
        category = _enum(p["category"], set(_ANIMATION_EFFECTS), "animation category")
        if p["effect"] not in _ANIMATION_EFFECTS[category]: raise Refusal("animation effect disagrees with its category")
        _enum(p["trigger"], {"on_click", "with_previous", "after_previous"}, "animation trigger")
        _enum(p["direction"], {"none", "left", "right", "up", "down"}, "animation direction")
        order = _integer(p["order"], "animation order", 1, 24)
        orders = self.animation_orders.setdefault(slide_id, set())
        if order in orders: raise Refusal("animation order is duplicate on one slide")
        orders.add(order)
        _number(p["duration_s"], "animation duration", 0.05, 10, positive=True)
        _number(p["delay_s"], "animation delay", 0, 10)

    def validate_powerpoint_set_transition(self, p):
        _exact(p, {"advance_on_click", "duration_s", "effect", "slide_id"}, "transition")
        if _identifier(p["slide_id"], "slide id") not in self.slides: raise Refusal("transition names an unknown slide")
        _enum(p["effect"], {"none", "fade", "morph"}, "transition effect")
        _number(p["duration_s"], "transition duration", 0, 5)
        if type(p["advance_on_click"]) is not bool: raise Refusal("advance_on_click is invalid")

    def validate_powerpoint_save_presentation(self, p):
        _exact(p, {"output_path"}, "save")
        if not self.slides or self.saved: raise Refusal("presentation must contain slides and may be saved once")
        _path(p["output_path"], self.context["output_path"]); self.saved = True

    def validate_powerpoint_inspect_presentation(self, p):
        _exact(p, set(), "inspect")
        if not self.saved: raise Refusal("inspection must follow save")


def _rgb(value):
    value = value.lstrip("#")
    red, green, blue = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return red | (green << 8) | (blue << 16)


class PowerPointSession:
    def __init__(self, context):
        self.context = context
        self.application = None
        self.presentation = None
        self.constants = None
        self.slides = {}
        self.shapes = {}
        self.theme = {}

    def _connect(self):
        if self.application is not None: return
        import win32com.client
        self._verify_com_authority()
        self.application = win32com.client.gencache.EnsureDispatch("PowerPoint.Application")
        self.constants = win32com.client.constants

    def _verify_com_authority(self):
        """Prove COM will bind the APPROVED PowerPoint, without Application.HWND.

        `Application.HWND` and every sibling handle -- `Windows(1).HWND`,
        `ActiveWindow.HWND`, `Presentation.Windows(1).HWND` -- raise
        DISP_E_MEMBERNOTFOUND on Office build 16.0.20326 under both late and
        early binding. The type library declares HWND at dispid 2031; the
        running application refuses it. A regenerated gencache does not change
        that, and every non-HWND member works, so this is the build removing
        window-handle exposure rather than a broken cache or a missing API.

        The property that check defended still has to hold (D102): the COM
        instance must be the target the approval authorized. It is established
        here from signals this build does expose. COM attaches to the running
        PowerPoint, so if exactly one exists and the approved window still
        belongs to that same process, the instance COM returns is the approved
        one.

        This is PROCESS identity, not window identity. It is narrower than the
        check it replaces: it cannot distinguish two windows of one PowerPoint.
        It still refuses the threat that mattered -- COM binding a different
        PowerPoint than the one approved -- and the singleton requirement is
        what keeps that true. Caption matching would restore window identity
        and is not used: titles are free text, which D075 already rejected as
        an identity signal.

        Ordered before EnsureDispatch deliberately. Dispatching first would
        LAUNCH PowerPoint when none is running, manufacturing the very process
        this is supposed to verify.
        """
        import psutil
        import win32gui
        import win32process

        approved_hwnd = int(self.context["target"]["hwnd"])
        approved_pid = int(self.context["target"]["pid"])

        if not win32gui.IsWindow(approved_hwnd):
            raise Refusal("approved PowerPoint window no longer exists")
        _thread, owner = win32process.GetWindowThreadProcessId(approved_hwnd)
        if int(owner) != approved_pid:
            raise Refusal("approved window no longer belongs to the approved process")

        live = sorted(
            p.pid
            for p in psutil.process_iter(["name"])
            if (p.info["name"] or "").upper().startswith("POWERPNT")
        )
        if live != [approved_pid]:
            raise Refusal(
                "PowerPoint must be the single approved process; found " + repr(live)
            )

    #: HRESULTs that mean the application REJECTED the call rather than
    #: running it. Retrying is safe for exactly these two and for nothing
    #: else: a call that was rejected did not happen, so repeating it cannot
    #: double an effect. A generic "retry on com_error" would be dangerous,
    #: because most COM failures leave the call's effect undefined.
    _REJECTED = (-2147418111, -2147417846)  # RPC_E_CALL_REJECTED, RETRYLATER

    def _retrying(self, call):
        """Run ONE idempotent COM call, waiting out a busy application.

        Callers must pass a single call whose repetition changes nothing --
        `Save()`, a read, a view change. Never a method that creates
        something: see the comment in `execute`.

        PowerPoint rejects calls while it is mid-operation -- closing a
        presentation, showing a transient dialog, finishing a save. Measured
        4 September 2026: a 255-node build failed at a different node on
        roughly half its attempts with RPC_E_CALL_REJECTED, and the same
        bundle passed on the others. Nothing about the plan was wrong; the
        application was briefly unavailable.
        """
        import time as _time

        delay = 0.15
        for attempt in range(6):
            try:
                return call()
            except Exception as exc:  # noqa: BLE001 - re-raised below
                code = getattr(exc, "args", (None,))[0]
                if code not in self._REJECTED or attempt == 5:
                    raise
                _time.sleep(delay)
                delay = min(delay * 2, 2.0)

    def execute(self, operation_id, p):
        method = getattr(self, "do_" + operation_id.replace(".", "_"), None)
        if method is None: raise Refusal("operation is not implemented")
        slide_id = p.get("slide_id") if isinstance(p, dict) else None
        # BEFORE the effect, so the change is watched landing on a slide that
        # is already in view rather than appearing on one the view then jumps
        # to. A slide this node is about to CREATE is not known yet, which is
        # why the same call is made again afterwards.
        shown = self._follow(slide_id)
        # NOT retried. A handler makes MANY COM calls -- `do_powerpoint_add_slide`
        # calls `Slides.Add` and then five more -- so a rejection landing after
        # the creating call would re-run the whole method and add a SECOND
        # slide. "A rejected call did not happen" is true of ONE call; it is
        # false of a method that already completed part of its work. Wrapping
        # the handler was a real duplication bug in a signed adapter, found by
        # the D032 review of 4 September 2026.
        #
        # A rejection mid-handler now fails the node, which is correct: a
        # failed run is recoverable and a duplicated slide in a signed
        # artifact is not.
        data = method(p) or {}
        if shown is None:
            shown = self._follow(slide_id)
        if self.presentation is not None and operation_id != "powerpoint.inspect_presentation":
            self._retrying(self.presentation.Save)
        if shown is not None:
            data["shown_slide_index"] = shown
        region = self._region(p if isinstance(p, dict) else {})
        if region is not None:
            data["region"] = region
        return data

    def _region(self, p):
        """Screen rect of the shape this node just touched, or None.

        PRESENTATION ONLY (D106). No verification reads it, no authorization
        depends on it, and it is reported after the effect rather than
        consulted before one. A failure to compute it is silently None: a
        highlight that cannot be drawn must never fail an authorized effect.

        `PointsToScreenPixelsX/Y` is used rather than assumed to exist --
        `Application.HWND` and every sibling window handle raise
        DISP_E_MEMBERNOTFOUND on Office 16.0.20326, so this one was probed on
        the same build before being relied on.
        """
        slide_id, object_id = p.get("slide_id"), p.get("object_id")
        shape = self.shapes.get((slide_id, object_id)) if object_id else None
        if shape is None:
            return None
        try:
            window = self.presentation.Windows(1)
            left = int(window.PointsToScreenPixelsX(shape.Left))
            top = int(window.PointsToScreenPixelsY(shape.Top))
            right = int(window.PointsToScreenPixelsX(shape.Left + shape.Width))
            bottom = int(window.PointsToScreenPixelsY(shape.Top + shape.Height))
        except Exception:
            return None
        # A perfectly horizontal or vertical line has a zero-area bounding
        # box. Dropping those cost 10 of the 18 dividers in the investor deck
        # their highlight -- a thin region is still a region that changed, so
        # the flat axis is opened to a visible minimum rather than refused.
        # Presentation only, so widening by two pixels misrepresents nothing.
        if right - left < _MIN_REGION_PX:
            middle = (left + right) // 2
            left, right = middle - _MIN_REGION_PX // 2, middle + _MIN_REGION_PX // 2
        if bottom - top < _MIN_REGION_PX:
            middle = (top + bottom) // 2
            top, bottom = middle - _MIN_REGION_PX // 2, middle + _MIN_REGION_PX // 2
        if right <= left or bottom <= top:
            return None
        return [left, top, right, bottom]

    def _follow(self, slide_id):
        """Bring the slide this node works on into view. Presentation only.

        Returns the 1-based index shown, or None if there was nothing to show.

        A failure here is swallowed deliberately and is never fatal. The view
        is not authority (D106) -- no verification reads it and no
        authorization depends on it -- so refusing a real, authorized effect
        because a window would not scroll would be the wrong trade. The index
        that WAS shown is reported in the result, so a run where the view
        never moved is visible in the record rather than merely unnoticed.
        """
        if not slide_id or slide_id not in self.slides:
            return None
        try:
            index = int(self.slides[slide_id].SlideIndex)
            # `GotoSlide` takes a plain integer. No application constant is
            # named here on purpose: a stubbed constant the application does
            # not expose is what let every exit animation refuse in
            # production while the contract test passed.
            self.presentation.Windows(1).View.GotoSlide(index)
            return index
        except Exception:
            return None

    def _slide(self, slide_id): return self.slides[slide_id]
    def _shape(self, slide_id, object_id): return self.shapes[(slide_id, object_id)]
    def _pt(self, inches): return float(inches) * 72.0
    def _const(self, *names):
        for name in names:
            try: return getattr(self.constants, name)
            except AttributeError: pass
        raise Refusal(f"PowerPoint does not expose required constant {names[0]}")

    def do_powerpoint_create_presentation(self, p):
        self._connect(); self.presentation = self.application.Presentations.Add()
        self.presentation.PageSetup.SlideWidth = self._pt(p["width"])
        self.presentation.PageSetup.SlideHeight = self._pt(p["height"])
        output = str(Path(p["output_path"]).resolve()); Path(output).parent.mkdir(parents=True, exist_ok=True)
        self.presentation.SaveAs(output)
        return {"output_path": output}

    def do_powerpoint_set_theme(self, p):
        self.theme = dict(p)
        theme_sha = hashlib.sha256(_canonical(p).encode()).hexdigest()
        # `Tags.Add` is the load-bearing write. It persists to
        # `ppt/tags/tagN.xml`, which is exactly what the independent verifier
        # reads, and it was measured persisting after `SaveAs`.
        #
        # This used to set `BuiltInDocumentProperties("Subject")` and fall back
        # to a tag on exception. Measured after `SaveAs`, that assignment
        # SUCCEEDS without raising and still does not persist -- so the except
        # branch could never run and the digest reached the file by no route at
        # all. An invariant that does not imply the property it guards is worse
        # than no guard: it reads as covered.
        self.presentation.Tags.Add("ghostcursor_theme", theme_sha)
        try:
            self.presentation.BuiltInDocumentProperties("Subject").Value = (
                "GhostCursor theme " + theme_sha
            )
        except Exception:
            pass  # Human-readable only; the tag above is what verification reads.
        return {"theme_sha256": theme_sha}

    def do_powerpoint_add_slide(self, p):
        slide = self.presentation.Slides.Add(self.presentation.Slides.Count + 1, 12)
        slide.Name = p["slide_id"]; slide.Tags.Add("ghostcursor_id", p["slide_id"])
        background = slide.Background.Fill
        background.Solid(); background.ForeColor.RGB = _rgb(p["background_color"])
        self.slides[p["slide_id"]] = slide
        return {"slide_count": int(self.presentation.Slides.Count)}

    def do_powerpoint_add_text(self, p):
        shape = self._slide(p["slide_id"]).Shapes.AddTextbox(1, self._pt(p["left"]), self._pt(p["top"]), self._pt(p["width"]), self._pt(p["height"]))
        shape.Name = p["object_id"]; frame = shape.TextFrame2; frame.TextRange.Text = p["text"]
        font = frame.TextRange.Font; font.Name = p["font_family"]; font.Size = p["font_size"]; font.Bold = -1 if p["bold"] else 0
        font.Fill.ForeColor.RGB = _rgb(p["color"]); font.Fill.Transparency = p["transparency"]
        frame.TextRange.ParagraphFormat.Alignment = {"left": 1, "center": 2, "right": 3}[p["align"]]
        frame.VerticalAnchor = {"top": 1, "middle": 3, "bottom": 4}[p["vertical_align"]]
        frame.MarginLeft = frame.MarginRight = frame.MarginTop = frame.MarginBottom = 0
        self.shapes[(p["slide_id"], p["object_id"])] = shape

    def do_powerpoint_add_shape(self, p):
        kind = {"rectangle": 1, "rounded_rectangle": 5, "ellipse": 9, "chevron": 52, "hexagon": 10, "arc": 25}[p["shape_kind"]]
        shape = self._slide(p["slide_id"]).Shapes.AddShape(kind, self._pt(p["left"]), self._pt(p["top"]), self._pt(p["width"]), self._pt(p["height"]))
        shape.Name = p["object_id"]; shape.Fill.Solid(); shape.Fill.ForeColor.RGB = _rgb(p["fill_color"]); shape.Fill.Transparency = p["fill_transparency"]
        shape.Line.ForeColor.RGB = _rgb(p["line_color"]); shape.Line.Weight = p["line_weight"]; shape.Line.Visible = -1 if p["line_weight"] > 0 else 0
        self.shapes[(p["slide_id"], p["object_id"])] = shape

    def do_powerpoint_add_line(self, p):
        shape = self._slide(p["slide_id"]).Shapes.AddLine(self._pt(p["x1"]), self._pt(p["y1"]), self._pt(p["x2"]), self._pt(p["y2"]))
        shape.Name = p["object_id"]; shape.Line.ForeColor.RGB = _rgb(p["color"]); shape.Line.Weight = p["weight"]
        shape.Line.DashStyle = {"solid": 1, "dash": 4, "dot": 3}[p["dash"]]
        shape.Line.BeginArrowheadStyle = {"none": 1, "triangle": 3}[p["begin_arrow"]]
        shape.Line.EndArrowheadStyle = {"none": 1, "triangle": 3}[p["end_arrow"]]
        self.shapes[(p["slide_id"], p["object_id"])] = shape

    def do_powerpoint_add_chart(self, p):
        categories, series = _chart_data(p["categories_json"], p["series_json"])
        slide = self._slide(p["slide_id"]); names = []
        max_value = max(abs(float(value)) for item in series for value in item["values"]) or 1.0
        left, top, width, height = map(self._pt, (p["left"], p["top"], p["width"], p["height"]))
        title = slide.Shapes.AddTextbox(1, left, top, width, 28); title.Name = p["object_id"] + "-title"; title.TextFrame2.TextRange.Text = p["title"]; names.append(title.Name)
        plot_top, plot_height = top + 36, height - 36
        colors = [self.theme.get("accent_color", "#26C6DA"), self.theme.get("success_color", "#48D597"), self.theme.get("warning_color", "#FFB454"), self.theme.get("error_color", "#FF6B6B")]
        if p["chart_kind"] in {"bar", "column"}:
            slots = len(categories) * len(series); gap = 4.0
            for category_index, category in enumerate(categories):
                for series_index, item in enumerate(series):
                    value = max(0.0, float(item["values"][category_index])); fraction = value / max_value
                    if p["chart_kind"] == "column":
                        bar_w = (width - gap * (slots - 1)) / slots; x = left + (category_index * len(series) + series_index) * (bar_w + gap); h = plot_height * fraction; y = plot_top + plot_height - h; w = bar_w
                    else:
                        bar_h = (plot_height - gap * (slots - 1)) / slots; y = plot_top + (category_index * len(series) + series_index) * (bar_h + gap); w = width * fraction; h = bar_h; x = left
                    bar = slide.Shapes.AddShape(1, x, y, max(w, 1), max(h, 1)); bar.Name = f"{p['object_id']}-bar-{category_index}-{series_index}"; bar.Fill.Solid(); bar.Fill.ForeColor.RGB = _rgb(colors[series_index]); bar.Line.Visible = 0; names.append(bar.Name)
        else:
            for series_index, item in enumerate(series):
                prior = None
                for index, value in enumerate(item["values"]):
                    x = left + (width * index / max(1, len(categories) - 1)); y = plot_top + plot_height * (1 - max(0.0, float(value)) / max_value)
                    dot = slide.Shapes.AddShape(9, x - 3, y - 3, 6, 6); dot.Name = f"{p['object_id']}-dot-{series_index}-{index}"; dot.Fill.Solid(); dot.Fill.ForeColor.RGB = _rgb(colors[series_index]); dot.Line.Visible = 0; names.append(dot.Name)
                    if prior is not None:
                        line = slide.Shapes.AddLine(prior[0], prior[1], x, y); line.Name = f"{p['object_id']}-line-{series_index}-{index}"; line.Line.ForeColor.RGB = _rgb(colors[series_index]); line.Line.Weight = 2; names.append(line.Name)
                    prior = (x, y)
        group = slide.Shapes.Range(tuple(names)).Group(); group.Name = p["object_id"]
        self.shapes[(p["slide_id"], p["object_id"])] = group

    def do_powerpoint_add_notes(self, p):
        notes = self._slide(p["slide_id"]).NotesPage
        for index in range(1, notes.Shapes.Placeholders.Count + 1):
            shape = notes.Shapes.Placeholders(index)
            try:
                if shape.PlaceholderFormat.Type == 2:
                    shape.TextFrame.TextRange.Text = p["text"]; return
            except Exception: pass
        raise Refusal("PowerPoint notes body placeholder is unavailable")

    def do_powerpoint_add_animation(self, p):
        effects = {
            "appear": ("msoAnimEffectAppear",), "fade": ("msoAnimEffectFade",), "fly_in": ("msoAnimEffectFly",), "wipe": ("msoAnimEffectWipe",), "zoom": ("msoAnimEffectZoom",),
            "pulse": ("msoAnimEffectPulse", "msoAnimEffectGrowShrink"), "grow_shrink": ("msoAnimEffectGrowShrink",), "spin": ("msoAnimEffectSpin",), "color_change": ("msoAnimEffectChangeFontColor", "msoAnimEffectChangeFillColor"),
            "disappear": ("msoAnimEffectDisappear", "msoAnimEffectAppear"), "fly_out": ("msoAnimEffectFly",), "wipe_exit": ("msoAnimEffectWipe",), "line": ("msoAnimEffectPathLine", "msoAnimEffectPathLines", "msoAnimEffectPathDown", "msoAnimEffectPathRight"), "arc": ("msoAnimEffectPathArcUp", "msoAnimEffectArcUp"),
        }
        triggers = {"on_click": ("msoAnimTriggerOnPageClick",), "with_previous": ("msoAnimTriggerWithPrevious",), "after_previous": ("msoAnimTriggerAfterPrevious",)}
        effect = self._slide(p["slide_id"]).TimeLine.MainSequence.AddEffect(self._shape(p["slide_id"], p["object_id"]), self._const(*effects[p["effect"]]), 0, self._const(*triggers[p["trigger"]]))
        if p["category"] == "exit":
            effect.Exit = True
        effect.Timing.Duration = p["duration_s"]; effect.Timing.TriggerDelayTime = p["delay_s"]
        if p["direction"] != "none":
            names = {"left": "msoAnimDirectionLeft", "right": "msoAnimDirectionRight", "up": "msoAnimDirectionUp", "down": "msoAnimDirectionDown"}
            try: effect.EffectParameters.Direction = self._const(names[p["direction"]])
            except Exception: pass
        try: effect.MoveTo(p["order"])
        except Exception: pass

    def do_powerpoint_set_transition(self, p):
        transition = self._slide(p["slide_id"]).SlideShowTransition
        if p["effect"] == "none": transition.EntryEffect = 0
        elif p["effect"] == "fade": transition.EntryEffect = self._const("ppEffectFadeSmoothly", "ppEffectFade")
        else: transition.EntryEffect = self._const("ppEffectMorphByObject", "ppEffectMorph")
        transition.Duration = p["duration_s"]; transition.AdvanceOnClick = -1 if p["advance_on_click"] else 0

    def do_powerpoint_save_presentation(self, p): self.presentation.SaveAs(str(Path(p["output_path"]).resolve()))

    def do_powerpoint_inspect_presentation(self, _p):
        return {"slides": int(self.presentation.Slides.Count), "shapes": {slide_id: int(slide.Shapes.Count) for slide_id, slide in self.slides.items()}}

    def close(self):
        if self.presentation is not None:
            try: self.presentation.Save()
            except Exception: pass
            try: self.presentation.Close()
            except Exception: pass


def _write(value):
    sys.stdout.write(_canonical(value) + "\n"); sys.stdout.flush()


def main():
    if sys.argv[1:] != ["--jsonl"]: return 2
    hello = json.loads(sys.stdin.readline())
    _exact(hello, {"adapter_sha256", "plugin_id", "plugin_version", "protocol_version", "session_context", "session_nonce", "type"}, "hello")
    own_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if hello["type"] != "hello" or hello["protocol_version"] != 1 or hello["plugin_id"] != PLUGIN_ID or hello["plugin_version"] != PLUGIN_VERSION or hello["adapter_sha256"] != own_sha:
        raise Refusal("adapter handshake authority disagrees")
    validator = PlanValidator(hello["session_context"]); session = PowerPointSession(hello["session_context"]); plan = None; cursor = 0; authorizations = set()
    _write({**hello, "type": "ready"})
    try:
        for line in sys.stdin:
            request = json.loads(line)
            if request.get("type") == "stop": break
            if request.get("session_nonce") != hello["session_nonce"]: raise Refusal("session nonce disagrees")
            if request.get("type") == "preflight":
                _exact(request, {"nodes", "request_id", "session_nonce", "type", "validation_sha256"}, "preflight")
                try:
                    if _SHA_RE.fullmatch(request["validation_sha256"]) is None: raise Refusal("validation digest is invalid")
                    validator.validate(request["nodes"]); plan = request["nodes"]
                    outcome, detail = "accepted", "complete PowerPoint plan is valid"
                except Refusal as exc: outcome, detail = "rejected", str(exc)
                _write({"detail": detail, "outcome": outcome, "request_id": request["request_id"], "session_nonce": hello["session_nonce"], "type": "preflight_result", "validation_sha256": request["validation_sha256"]})
                if outcome == "rejected": break
                continue
            _exact(request, {"authorization_sha256", "node_id", "operation_id", "ordinal", "parameters", "request_id", "session_nonce", "type", "validation_sha256"}, "execute")
            if plan is None or cursor >= len(plan): raise Refusal("execute arrived without accepted preflight")
            expected = plan[cursor]
            if request["type"] != "execute" or request["ordinal"] != cursor + 1 or request["node_id"] != expected["node_id"] or request["operation_id"] != expected["operation_id"] or request["parameters"] != expected["parameters"]:
                raise Refusal("execute request disagrees with accepted plan")
            if _SHA_RE.fullmatch(request["authorization_sha256"]) is None or request["authorization_sha256"] in authorizations:
                raise Refusal("authorization is invalid or replayed")
            authorizations.add(request["authorization_sha256"])
            try:
                data = session.execute(request["operation_id"], request["parameters"]); outcome, detail = "completed", "PowerPoint effect completed"
            except Exception as exc:
                data, outcome, detail = {}, "failed", f"{type(exc).__name__}: {exc}"
            _write({"data": data, "detail": detail, "facts": [], "outcome": outcome, "request_id": request["request_id"], "session_nonce": hello["session_nonce"], "type": "result"})
            if outcome != "completed": break
            cursor += 1
    finally: session.close()
    return 0


if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception as exc:
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n"); raise SystemExit(3)
