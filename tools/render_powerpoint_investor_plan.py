"""Render the reviewed GhostCursor investor narrative as one signed action plan."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PAYLOAD = ROOT / "plugins" / "sources" / "powerpoint" / "payload" / "ghostcursor"
PLAN_DIR = PAYLOAD / "action-plans"
PLAN_PATH = PLAN_DIR / "build-investor-deck-v1.json"
INDEX_PATH = PAYLOAD / "action-plans.json"
PLAN_ID = "build-investor-deck-v1"
W, H = 13.333, 7.5
BG, SURFACE, TEXT, MUTED = "#080B12", "#111827", "#F5F7FB", "#A8B2C3"
CYAN, GREEN, AMBER, CORAL, BORDER = (
    "#26C6DA",
    "#48D597",
    "#FFB454",
    "#FF6B6B",
    "#334155",
)


class Deck:
    def __init__(self):
        self.nodes = []
        self.edges = []
        self.prior = None
        self.count = 0

    def add(self, operation, parameters, label):
        self.count += 1
        node_id = f"n{self.count:03d}-{label}"
        self.nodes.append(
            {"node_id": node_id, "operation_id": operation, "parameters": parameters}
        )
        if self.prior is not None:
            self.edges.append({"after": node_id, "before": self.prior})
        self.prior = node_id
        return node_id

    def slide(self, slide_id):
        self.add(
            "powerpoint.add_slide",
            {"background_color": BG, "slide_id": slide_id},
            slide_id,
        )

    def shape(
        self,
        slide,
        object_id,
        kind,
        left,
        top,
        width,
        height,
        fill=SURFACE,
        transparency=0.08,
        line=BORDER,
        weight=1,
    ):
        self.add(
            "powerpoint.add_shape",
            {
                "fill_color": fill,
                "fill_transparency": transparency,
                "height": height,
                "left": left,
                "line_color": line,
                "line_weight": weight,
                "object_id": object_id,
                "shape_kind": kind,
                "slide_id": slide,
                "top": top,
                "width": width,
            },
            object_id,
        )

    def text(
        self,
        slide,
        object_id,
        text,
        left,
        top,
        width,
        height,
        size=20,
        color=TEXT,
        bold=False,
        align="left",
        vertical="top",
        font=None,
    ):
        self.add(
            "powerpoint.add_text",
            {
                "align": align,
                "bold": bold,
                "color": color,
                "font_family": font or ("Aptos Display" if bold else "Aptos"),
                "font_size": size,
                "height": height,
                "left": left,
                "object_id": object_id,
                "slide_id": slide,
                "text": text,
                "top": top,
                "transparency": 0,
                "vertical_align": vertical,
                "width": width,
            },
            object_id,
        )

    def line(
        self,
        slide,
        object_id,
        x1,
        y1,
        x2,
        y2,
        color=BORDER,
        weight=1.5,
        dash="solid",
        end="none",
    ):
        self.add(
            "powerpoint.add_line",
            {
                "begin_arrow": "none",
                "color": color,
                "dash": dash,
                "end_arrow": end,
                "object_id": object_id,
                "slide_id": slide,
                "weight": weight,
                "x1": x1,
                "x2": x2,
                "y1": y1,
                "y2": y2,
            },
            object_id,
        )

    def title(self, slide, eyebrow, headline):
        self.text(
            slide,
            f"{slide}-eyebrow",
            eyebrow.upper(),
            0.68,
            0.42,
            5.8,
            0.32,
            14,
            CYAN,
            True,
        )
        self.text(
            slide, f"{slide}-title", headline, 0.68, 0.84, 11.9, 1.0, 38, TEXT, True
        )

    def notes(self, slide, text):
        self.add(
            "powerpoint.add_notes", {"slide_id": slide, "text": text}, f"{slide}-notes"
        )

    def animation(
        self,
        slide,
        object_id,
        effect="fade",
        order=1,
        category="entrance",
        trigger="after_previous",
        duration=0.45,
        delay=0.0,
        direction="none",
    ):
        self.add(
            "powerpoint.add_animation",
            {
                "category": category,
                "delay_s": delay,
                "direction": direction,
                "duration_s": duration,
                "effect": effect,
                "object_id": object_id,
                "order": order,
                "slide_id": slide,
                "trigger": trigger,
            },
            f"{slide}-anim-{order}",
        )

    def transition(self, slide, effect="fade"):
        self.add(
            "powerpoint.set_transition",
            {
                "advance_on_click": True,
                "duration_s": 0.55,
                "effect": effect,
                "slide_id": slide,
            },
            f"{slide}-transition",
        )


def _deck():
    d = Deck()
    output = {"$parameter": "output_path"}
    d.add(
        "powerpoint.create_presentation",
        {"height": H, "output_path": output, "width": W},
        "create",
    )
    d.add(
        "powerpoint.set_theme",
        {
            "accent_color": CYAN,
            "background_color": BG,
            "body_font": "Aptos",
            "error_color": CORAL,
            "heading_font": "Aptos Display",
            "primary_text_color": TEXT,
            "secondary_text_color": MUTED,
            "success_color": GREEN,
            "surface_color": SURFACE,
            "warning_color": AMBER,
        },
        "theme",
    )

    s = "slide-01"
    d.slide(s)
    d.shape(s, "focus-outer", "ellipse", 8.76, 1.02, 3.35, 3.35, BG, 1, CYAN, 2.5)
    d.shape(
        s, "focus-inner", "ellipse", 9.42, 1.68, 2.03, 2.03, SURFACE, 0.02, BORDER, 1
    )
    d.text(s, "focus-goal", "GOAL", 9.89, 2.18, 1.1, 0.35, 16, CYAN, True, "center")
    d.text(
        s,
        "hero-title",
        "Software should understand\nwhat the human is trying to accomplish.",
        0.72,
        0.86,
        7.45,
        2.35,
        50,
        TEXT,
        True,
    )
    d.text(
        s,
        "hero-subhead",
        "GhostCursor is a local, verified workflow layer for native Windows applications.",
        0.76,
        3.48,
        6.9,
        0.85,
        24,
        MUTED,
    )
    stages = [
        ("State a goal", CYAN),
        ("Review authority", TEXT),
        ("Teach or approve Act", TEXT),
        ("Verify the result", GREEN),
    ]
    for index, (label, color) in enumerate(stages):
        left = 0.76 + index * 2.93
        if index:
            d.line(
                s,
                f"stage-line-{index}",
                left - 0.48,
                5.38,
                left - 0.12,
                5.38,
                BORDER,
                1.2,
                "solid",
                "triangle",
            )
        d.shape(
            s,
            f"stage-dot-{index}",
            "ellipse",
            left,
            5.19,
            0.38,
            0.38,
            color,
            0,
            color,
            0,
        )
        d.text(
            s,
            f"stage-label-{index}",
            label,
            left + 0.51,
            5.06,
            2.15,
            0.65,
            17,
            color,
            index in {0, 3},
            vertical="middle",
        )
    d.text(
        s,
        "hero-footer",
        "GhostCursor · pre-seed product narrative · September 2026",
        0.76,
        6.92,
        8.0,
        0.28,
        12,
        MUTED,
    )
    d.notes(
        s,
        "[Sources]\n- Repository: docs/pitch/ghostcursor-investor-deck-content.md\n- Product state: local reviewed narrative; no external market claim on this slide.",
    )
    d.animation(s, "hero-title", "fade", 1)
    d.animation(s, "focus-outer", "zoom", 2, duration=0.55)
    d.animation(s, "stage-dot-0", "pulse", 3, "emphasis")
    d.transition(s)

    s = "slide-02"
    d.slide(s)
    d.title(
        s,
        "Problem",
        "The PDF knows the procedure. It cannot see where the employee is stuck.",
    )
    y = 3.0
    moments = [
        ("MANUAL", "Read away from work", CYAN),
        ("LIVE APP", "Lose context switching", AMBER),
        ("SENIOR", "Repeat screen-share support", CORAL),
        ("IT TICKET", "Receive ‘app not working’", MUTED),
    ]
    for index in range(3):
        d.line(
            s,
            f"broken-line-{index}",
            3.28 + index * 3.05,
            y + 0.5,
            3.72 + index * 3.05,
            y + 0.5,
            CORAL,
            2.0,
            "dash",
        )
    for index, (label, detail, color) in enumerate(moments):
        left = 0.72 + index * 3.05
        d.shape(
            s,
            f"moment-{index}",
            "rounded_rectangle",
            left,
            y,
            2.56,
            1.52,
            SURFACE,
            0.05,
            color,
            1.2,
        )
        d.text(
            s,
            f"moment-label-{index}",
            label,
            left + 0.22,
            y + 0.2,
            2.1,
            0.32,
            14,
            color,
            True,
        )
        d.text(
            s,
            f"moment-detail-{index}",
            detail,
            left + 0.22,
            y + 0.66,
            2.1,
            0.58,
            18,
            TEXT,
            True,
        )
    d.text(
        s,
        "problem-takeaway",
        "Training, execution, and support are separate systems—even though the failure happens in one live interface.",
        1.2,
        5.55,
        10.9,
        0.9,
        24,
        TEXT,
        True,
        "center",
        "middle",
    )
    d.notes(
        s,
        "[Sources]\n- Repository: docs/pitch/ghostcursor-investor-deck-content.md\n- Problem statements are hypotheses for customer discovery, not measured ROI claims.",
    )
    d.animation(s, "slide-02-title", "fade", 1)
    d.animation(s, "moment-0", "wipe", 2, direction="right")
    d.animation(s, "problem-takeaway", "fade", 3)
    d.transition(s)

    s = "slide-03"
    d.slide(s)
    d.title(s, "Surface", "Browser overlays stop where critical Windows work begins.")
    d.shape(
        s,
        "browser-boundary",
        "rounded_rectangle",
        0.72,
        2.25,
        4.15,
        3.78,
        SURFACE,
        0.05,
        BORDER,
        1,
    )
    d.text(
        s,
        "browser-label",
        "TRADITIONAL DIGITAL ADOPTION",
        1.02,
        2.58,
        3.55,
        0.34,
        14,
        MUTED,
        True,
    )
    d.text(
        s,
        "browser-copy",
        "Usually depends on application or webpage integration.\n\nReplays authored walkthroughs.\n\nMeasures clicks and completion events.",
        1.02,
        3.18,
        3.42,
        2.25,
        19,
        TEXT,
    )
    d.line(s, "surface-divider", 5.34, 2.15, 5.34, 6.12, CYAN, 2)
    d.text(
        s,
        "native-label",
        "GHOSTCURSOR · NATIVE WINDOWS",
        5.82,
        2.35,
        4.1,
        0.35,
        14,
        CYAN,
        True,
    )
    apps = [
        "SAP GUI",
        "Engineering tools",
        "Internal GCC apps",
        "Core banking",
        "Hospital admin",
    ]
    for index, app in enumerate(apps):
        left = 5.82 + (index % 2) * 3.1
        top = 3.0 + (index // 2) * 0.9
        d.shape(
            s,
            f"native-app-{index}",
            "rounded_rectangle",
            left,
            top,
            2.72,
            0.64,
            BG,
            0.1,
            BORDER,
            1,
        )
        d.text(
            s,
            f"native-name-{index}",
            app,
            left + 0.18,
            top + 0.1,
            2.35,
            0.42,
            17,
            TEXT,
            True,
            vertical="middle",
        )
    d.text(
        s,
        "native-proof",
        "Signed workflow → Teach guidance or approved Act → independent state verification",
        5.82,
        5.88,
        6.4,
        0.54,
        19,
        GREEN,
        True,
    )
    d.notes(
        s,
        "[Sources]\n- Repository: docs/pitch/ghostcursor-investor-deck-content.md\n- Named applications are customer-discovery examples, not claims of current supported coverage.",
    )
    d.animation(s, "browser-boundary", "fade", 1)
    d.animation(s, "surface-divider", "wipe", 2, direction="down")
    d.animation(s, "native-app-0", "fly_in", 3, direction="right")
    d.transition(s)

    s = "slide-04"
    d.slide(s)
    d.title(s, "Product", "Observe → authorize → guide or act → verify → learn.")
    d.shape(
        s,
        "live-frame",
        "rounded_rectangle",
        4.55,
        2.42,
        4.22,
        2.56,
        SURFACE,
        0.02,
        BORDER,
        1,
    )
    d.text(
        s,
        "live-frame-label",
        "LIVE APPLICATION STATE",
        5.17,
        3.25,
        3.0,
        0.35,
        16,
        CYAN,
        True,
        "center",
    )
    d.text(
        s,
        "live-frame-step",
        "One reviewed workflow state",
        5.0,
        3.76,
        3.3,
        0.5,
        22,
        TEXT,
        True,
        "center",
    )
    loop = [
        ("1", "Goal", 1.0, 2.28, CYAN),
        ("2", "Authorize", 2.06, 4.82, TEXT),
        ("3", "Guide", 4.04, 5.72, TEXT),
        ("4", "Human / Act", 7.48, 5.72, TEXT),
        ("5", "Verify", 10.18, 4.82, GREEN),
        ("6", "Learn", 10.72, 2.28, MUTED),
    ]
    for index in range(len(loop) - 1):
        _, _, x1, y1, _ = loop[index]
        _, _, x2, y2, _ = loop[index + 1]
        d.line(
            s,
            f"loop-line-{index}",
            x1 + 0.7,
            y1 + 0.38,
            x2 + 0.08,
            y2 + 0.38,
            BORDER,
            1.2,
            "solid",
            "triangle",
        )
    for number, label, left, top, color in loop:
        d.shape(
            s,
            f"loop-node-{number}",
            "ellipse",
            left,
            top,
            0.62,
            0.62,
            color,
            0.08,
            color,
            1.2,
        )
        d.text(
            s,
            f"loop-number-{number}",
            number,
            left,
            top + 0.09,
            0.62,
            0.3,
            15,
            color,
            True,
            "center",
        )
        d.text(
            s,
            f"loop-label-{number}",
            label,
            left - 0.36,
            top + 0.73,
            1.34,
            0.38,
            16,
            TEXT,
            True,
            "center",
        )
    d.shape(
        s, "trust-strip", "rounded_rectangle", 1.1, 6.65, 11.1, 0.48, BG, 0.1, BORDER, 1
    )
    d.text(
        s,
        "trust-copy",
        "Local by default   ·   Teach: no input synthesis   ·   Act: approved object model only   ·   stop / pause",
        1.3,
        6.73,
        10.7,
        0.25,
        14,
        MUTED,
        True,
        "center",
    )
    d.notes(
        s,
        "[Sources]\n- Repository: CLAUDE.md; FLOW.md; DECISIONS.md\n- Trust strip summarizes current reviewed product invariants.",
    )
    d.animation(s, "live-frame", "zoom", 1)
    d.animation(s, "loop-node-1", "wipe", 2, direction="right")
    d.animation(s, "trust-strip", "fade", 3)
    d.transition(s, "morph")

    s = "slide-05"
    d.slide(s)
    d.title(
        s,
        "Evidence",
        "The core is application-agnostic; workflows arrive as signed data.",
    )
    d.line(s, "waterline", 0.8, 3.22, 12.55, 3.22, BORDER, 1.2, "dash")
    plugins = [
        ("SYNTHETIC", GREEN),
        ("VS CODE", GREEN),
        ("EXCEL", GREEN),
        ("POWERPOINT", AMBER),
    ]
    for index, (name, color) in enumerate(plugins):
        left = 0.9 + index * 3.06
        d.shape(
            s,
            f"plugin-{index}",
            "rounded_rectangle",
            left,
            2.25,
            2.56,
            0.72,
            BG,
            0.1,
            color,
            1.2,
        )
        d.text(
            s,
            f"plugin-name-{index}",
            name,
            left,
            2.43,
            2.56,
            0.28,
            16,
            color,
            True,
            "center",
        )
    d.shape(
        s, "core-iceberg", "hexagon", 4.1, 3.58, 5.18, 2.65, SURFACE, 0.02, CYAN, 1.4
    )
    d.text(
        s,
        "core-label",
        "SMALL NATIVE CORE",
        5.22,
        4.18,
        2.95,
        0.35,
        18,
        CYAN,
        True,
        "center",
    )
    d.text(
        s,
        "core-proof",
        "One authorization gate\nFail-closed ambiguity\nSigned local bundles\nBounded verification",
        5.12,
        4.72,
        3.15,
        1.18,
        18,
        TEXT,
        True,
        "center",
    )
    d.text(
        s,
        "evidence-left",
        "3 signed active plugins\n6 active workflows\nExcel: 3/3 + 3/3 UIA-only",
        0.92,
        4.02,
        2.8,
        1.45,
        19,
        TEXT,
        True,
    )
    d.text(
        s,
        "evidence-right",
        "PowerPoint: 5 guided candidates\n+ signed Act candidate quarantined\nGate: 1,246 passed · 71 deselected",
        9.72,
        4.02,
        2.75,
        1.55,
        18,
        MUTED,
        True,
    )
    d.text(
        s,
        "evidence-legend",
        "● accepted / active     ◇ measured / quarantined",
        0.92,
        6.72,
        5.2,
        0.28,
        13,
        MUTED,
    )
    d.notes(
        s,
        "[Sources]\n- Repository: docs/pitch/ghostcursor-investor-deck-content.md\n- Closing candidate gate: 1,246 passed, 71 deselected. Live acceptance evidence records the committed baseline.",
    )
    d.animation(s, "core-iceberg", "zoom", 1)
    d.animation(s, "plugin-0", "fade", 2)
    d.animation(s, "evidence-right", "fade", 3)
    d.transition(s)

    s = "slide-06"
    d.slide(s)
    d.title(s, "Wedge", "Start where repeated guidance has measurable cost.")
    d.shape(
        s,
        "beachhead",
        "rounded_rectangle",
        0.78,
        2.25,
        5.12,
        3.92,
        SURFACE,
        0.03,
        CYAN,
        1.2,
    )
    d.text(
        s,
        "beachhead-label",
        "WINDOWS-HEAVY ENGINEERING + GCC ONBOARDING",
        1.1,
        2.62,
        4.5,
        0.5,
        16,
        CYAN,
        True,
    )
    d.text(
        s,
        "beachhead-user",
        "USER\nA new hire learning a company-specific workflow in unfamiliar tools.",
        1.1,
        3.35,
        4.42,
        0.9,
        19,
        TEXT,
        True,
    )
    d.text(
        s,
        "beachhead-buyer",
        "BUYER\nEngineering enablement, IT operations, or the team leader providing repeated screen-share support.",
        1.1,
        4.58,
        4.42,
        1.1,
        18,
        TEXT,
        True,
    )
    placeholders = [
        "[MONTHLY NEW-HIRE COHORT]",
        "[CURRENT TIME TO INDEPENDENCE]",
        "[TOP REPEATED SUPPORT WORKFLOW]",
        "[DESIGN-PARTNER QUOTE]",
    ]
    for index, value in enumerate(placeholders):
        top = 2.26 + index * 0.98
        d.shape(
            s,
            f"metric-{index}",
            "rounded_rectangle",
            6.52,
            top,
            5.78,
            0.74,
            BG,
            0.1,
            BORDER,
            1,
        )
        d.text(
            s,
            f"metric-copy-{index}",
            value,
            6.82,
            top + 0.18,
            5.18,
            0.3,
            16,
            AMBER,
            True,
        )
    d.text(
        s,
        "pilot-promise",
        "Pilot promise: encode one approved workflow → guide it in the real app → verify completion → measure support interruption and time-to-independence.",
        6.55,
        6.28,
        5.68,
        0.72,
        17,
        GREEN,
        True,
    )
    d.notes(
        s,
        "[Sources]\n- Repository: docs/pitch/ghostcursor-investor-deck-content.md\n- Bracketed discovery facts are intentionally unresolved and must remain placeholders.",
    )
    d.animation(s, "beachhead", "fade", 1)
    d.animation(s, "metric-0", "fly_in", 2, direction="right")
    d.animation(s, "pilot-promise", "fade", 3)
    d.transition(s)

    s = "slide-07"
    d.slide(s)
    d.title(
        s,
        "Expansion",
        "Capture once. Guide many. Resolve exceptions. Improve the procedure.",
    )
    d.shape(
        s, "flywheel-center", "ellipse", 5.2, 2.78, 2.92, 2.92, SURFACE, 0.02, CYAN, 1.4
    )
    d.text(
        s,
        "flywheel-outcome",
        "VERIFIED\nWORKFLOW",
        5.64,
        3.65,
        2.05,
        0.72,
        20,
        TEXT,
        True,
        "center",
        "middle",
    )
    wheel = [
        ("capture", "CAPTURE", 1.0, 2.65, CYAN),
        ("guide", "GUIDE", 2.52, 5.45, TEXT),
        ("verify", "VERIFY", 5.48, 6.12, GREEN),
        ("resolve", "RESOLVE", 8.52, 5.45, AMBER),
        ("insights", "INSIGHTS", 10.16, 2.65, MUTED),
    ]
    for index in range(len(wheel) - 1):
        _, _, x1, y1, _ = wheel[index]
        _, _, x2, y2, _ = wheel[index + 1]
        d.line(
            s,
            f"wheel-link-{index}",
            x1 + 1.3,
            y1 + 0.38,
            x2,
            y2 + 0.38,
            BORDER,
            1.2,
            "solid",
            "triangle",
        )
    for key, label, left, top, color in wheel:
        d.shape(
            s,
            f"wheel-{key}",
            "rounded_rectangle",
            left,
            top,
            2.05,
            0.76,
            BG,
            0.08,
            color,
            1.1,
        )
        d.text(
            s,
            f"wheel-label-{key}",
            label,
            left,
            top + 0.2,
            2.05,
            0.3,
            16,
            color,
            True,
            "center",
        )
    d.text(
        s,
        "privacy-boundary",
        "Privacy boundary: workflow-level friction—not employee ranking.",
        3.1,
        6.82,
        7.1,
        0.32,
        15,
        MUTED,
        True,
        "center",
    )
    d.notes(
        s,
        "[Sources]\n- Repository: docs/pitch/ghostcursor-investor-deck-content.md; Enterprise_Transformation research supplied by founder\n- Expansion modules are product direction, not shipped-feature claims.",
    )
    d.animation(s, "flywheel-center", "zoom", 1)
    d.animation(s, "wheel-capture", "wipe", 2, direction="right")
    d.animation(s, "privacy-boundary", "fade", 3)
    d.transition(s)

    s = "slide-08"
    d.slide(s)
    d.title(
        s,
        "Commercial path",
        "Land with one workflow. Expand by application and outcome.",
    )
    rungs = [
        (
            "01",
            "FIXED-SCOPE PILOT",
            "One team · one app · one approved workflow",
            1.0,
            5.25,
            CYAN,
        ),
        (
            "02",
            "TEAM DEPLOYMENT",
            "Additional workflows · local diagnostics",
            1.68,
            4.22,
            TEXT,
        ),
        (
            "03",
            "ENTERPRISE PLATFORM",
            "Governance · support routing · insights",
            2.36,
            3.19,
            GREEN,
        ),
        (
            "04",
            "DISTRIBUTION",
            "Partners publish reviewed workflow packs",
            3.04,
            2.16,
            AMBER,
        ),
    ]
    for number, label, detail, left, top, color in rungs:
        d.shape(
            s,
            f"rung-{number}",
            "rounded_rectangle",
            left,
            top,
            8.3,
            0.78,
            SURFACE,
            0.04,
            color,
            1.1,
        )
        d.text(
            s,
            f"rung-number-{number}",
            number,
            left + 0.22,
            top + 0.19,
            0.52,
            0.3,
            16,
            color,
            True,
        )
        d.text(
            s,
            f"rung-label-{number}",
            label,
            left + 0.92,
            top + 0.17,
            2.75,
            0.34,
            17,
            TEXT,
            True,
        )
        d.text(
            s,
            f"rung-detail-{number}",
            detail,
            left + 3.7,
            top + 0.17,
            4.25,
            0.34,
            16,
            MUTED,
        )
    d.shape(
        s,
        "pricing-hypothesis",
        "rounded_rectangle",
        10.08,
        2.16,
        2.35,
        3.87,
        BG,
        0.08,
        BORDER,
        1,
    )
    d.text(
        s,
        "pricing-label",
        "VALIDATE",
        10.35,
        2.48,
        1.8,
        0.32,
        15,
        AMBER,
        True,
        "center",
    )
    d.text(
        s,
        "pricing-copy",
        "[PILOT PRICE]\n\n[ANNUAL CONTRACT HYPOTHESIS]\n\n[FIRST DESIGN PARTNER]",
        10.34,
        3.05,
        1.84,
        2.3,
        15,
        TEXT,
        True,
        "center",
    )
    d.notes(
        s,
        "[Sources]\n- Repository: docs/pitch/ghostcursor-investor-deck-content.md\n- Pricing and partner fields are hypotheses/placeholders, not commercial claims.",
    )
    d.animation(s, "rung-01", "fly_in", 1, direction="left")
    d.animation(s, "rung-04", "fade", 2)
    d.animation(s, "pricing-hypothesis", "pulse", 3, "emphasis")
    d.transition(s)

    s = "slide-09"
    d.slide(s)
    d.title(
        s,
        "Defensibility",
        "The moat is not the overlay. It is trusted workflow intelligence.",
    )
    rings = [
        ("ring-5", 2.1, 0.98, 9.2, 5.65, MUTED),
        ("ring-4", 2.85, 1.48, 7.7, 4.65, AMBER),
        ("ring-3", 3.6, 1.98, 6.2, 3.65, GREEN),
        ("ring-2", 4.36, 2.48, 4.68, 2.65, CYAN),
        ("ring-1", 5.1, 2.98, 3.2, 1.65, TEXT),
    ]
    for key, left, top, width, height, color in rings:
        d.shape(s, key, "ellipse", left, top, width, height, BG, 1, color, 1.2)
    d.text(
        s,
        "moat-center",
        "VERIFIED\nOUTCOME",
        5.55,
        3.42,
        2.3,
        0.72,
        22,
        TEXT,
        True,
        "center",
        "middle",
    )
    labels = [
        ("Reviewed workflow graph", 0.72, 2.4, CYAN),
        ("Application understanding", 0.72, 3.22, GREEN),
        ("Organization procedure knowledge", 0.72, 4.04, AMBER),
        ("Outcome verification", 9.94, 3.0, TEXT),
        ("Resolution memory", 9.94, 3.82, MUTED),
    ]
    for index, (label, left, top, color) in enumerate(labels):
        d.text(s, f"moat-label-{index}", label, left, top, 2.7, 0.52, 17, color, True)
    d.text(
        s,
        "moat-discipline",
        "Signed bundles · exact app identity · fail-closed ambiguity · one authorization gate",
        2.4,
        6.64,
        8.55,
        0.36,
        15,
        MUTED,
        True,
        "center",
    )
    d.notes(
        s,
        "[Sources]\n- Repository: CLAUDE.md; DECISIONS.md; docs/pitch/ghostcursor-investor-deck-content.md\n- Moat framing is a strategy thesis, not a measured market claim.",
    )
    d.animation(s, "ring-5", "zoom", 1)
    d.animation(s, "ring-1", "fade", 2)
    d.animation(s, "moat-center", "pulse", 3, "emphasis")
    d.transition(s)

    s = "slide-10"
    d.slide(s)
    d.title(
        s,
        "Next proof",
        "The technical foundation is working. Now prove who urgently buys.",
    )
    d.line(s, "runway", 1.05, 4.15, 11.78, 4.15, BORDER, 2, "solid", "triangle")
    milestones = [
        ("01", "PowerPoint\nshowcase", 1.1, CYAN),
        ("02", "10–15 team\ninterviews", 3.35, TEXT),
        ("03", "3 pain-matched\npilots", 5.6, GREEN),
        ("04", "Paid design\npartner", 7.85, AMBER),
        ("05", "Measured\noutcomes", 10.1, CYAN),
    ]
    for number, label, left, color in milestones:
        d.shape(
            s,
            f"milestone-{number}",
            "ellipse",
            left,
            3.77,
            0.76,
            0.76,
            color,
            0.04,
            color,
            1.2,
        )
        d.text(
            s,
            f"milestone-number-{number}",
            number,
            left,
            3.98,
            0.76,
            0.26,
            14,
            color,
            True,
            "center",
        )
        d.text(
            s,
            f"milestone-label-{number}",
            label,
            left - 0.42,
            4.78,
            1.62,
            0.78,
            16,
            TEXT,
            True,
            "center",
        )
    d.text(
        s,
        "founder-placeholder",
        "[FOUNDER NAME, ROLE, RELEVANT CREDIBILITY]",
        0.82,
        2.28,
        5.7,
        0.38,
        16,
        AMBER,
        True,
    )
    d.text(
        s,
        "fundraise-placeholder",
        "[ROUND SIZE]  ·  [RUNWAY]  ·  [HIRING PLAN]  ·  [PILOT MILESTONES]",
        0.82,
        2.82,
        8.2,
        0.38,
        16,
        AMBER,
        True,
    )
    d.shape(
        s,
        "closing-box",
        "rounded_rectangle",
        2.1,
        6.05,
        9.15,
        0.82,
        SURFACE,
        0.02,
        CYAN,
        1.2,
    )
    d.text(
        s,
        "closing-copy",
        "If your team trains people on complex Windows software, let us encode one workflow and prove it in the live application.",
        2.48,
        6.23,
        8.4,
        0.4,
        18,
        TEXT,
        True,
        "center",
    )
    d.notes(
        s,
        "[Sources]\n- Repository: docs/pitch/ghostcursor-investor-deck-content.md\n- Founder and fundraise facts remain deliberately unresolved placeholders.",
    )
    d.animation(s, "runway", "wipe", 1, direction="right")
    d.animation(s, "milestone-01", "zoom", 2)
    d.animation(s, "closing-box", "fade", 3)
    d.transition(s, "morph")

    d.add("powerpoint.save_presentation", {"output_path": output}, "save")
    d.add("powerpoint.inspect_presentation", {}, "inspect")
    return {"edges": d.edges, "nodes": d.nodes, "plan_id": PLAN_ID, "schema_version": 1}


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def render():
    plan_bytes = _bytes(_deck())
    index = {
        "plans": {
            PLAN_ID: {
                "intent_id": "BUILD_INVESTOR_DECK",
                "parameters": {"output_path": {"kind": "string", "required": True}},
                "path": "ghostcursor/action-plans/build-investor-deck-v1.json",
                "sha256": hashlib.sha256(plan_bytes).hexdigest(),
            }
        },
        "plugin_id": "ghostcursor.powerpoint",
        "plugin_version": "1.0.0",
        "schema_version": 1,
    }
    return plan_bytes, _bytes(index)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    plan, index = render()
    if args.check:
        return (
            0
            if PLAN_PATH.is_file()
            and INDEX_PATH.is_file()
            and PLAN_PATH.read_bytes() == plan
            and INDEX_PATH.read_bytes() == index
            else 1
        )
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_bytes(plan)
    INDEX_PATH.write_bytes(index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
