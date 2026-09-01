from __future__ import annotations

import hashlib
import importlib.util
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from ghostcursor.action import (
    ActionEdge,
    ActionGraph,
    ActionNode,
    load_operation_registry,
    validate_action_graph,
)
from ghostcursor.adapter_host import AdapterHost, AdapterProtocolError, VerifierHost


ROOT = (
    Path(__file__).resolve().parent.parent
    / "plugins"
    / "sources"
    / "powerpoint"
    / "payload"
    / "ghostcursor"
)
ADAPTER = ROOT / "adapter" / "powerpoint_adapter.py"
VERIFIER = ROOT / "adapter" / "powerpoint_verifier.py"
OPERATIONS = ROOT / "operations.json"
PLUGIN = "ghostcursor.powerpoint"
VERSION = "1.0.0"


def _descriptor():
    return SimpleNamespace(
        plugin_id=PLUGIN,
        plugin_version=VERSION,
        manifest_sha256="c" * 64,
        payload_root=ROOT,
        entrypoint=ADAPTER,
        adapter_sha256=hashlib.sha256(ADAPTER.read_bytes()).hexdigest(),
        verifier=VERIFIER,
        verifier_sha256=hashlib.sha256(VERIFIER.read_bytes()).hexdigest(),
    )


def _registry():
    descriptor = _descriptor()
    return load_operation_registry(
        OPERATIONS.read_bytes(),
        plugin_id=PLUGIN,
        plugin_version=VERSION,
        adapter_sha256=descriptor.adapter_sha256,
    )


def _theme():
    return {
        "accent_color": "#26C6DA",
        "background_color": "#080B12",
        "body_font": "Aptos",
        "error_color": "#FF6B6B",
        "heading_font": "Aptos Display",
        "primary_text_color": "#F5F7FB",
        "secondary_text_color": "#A8B2C3",
        "success_color": "#48D597",
        "surface_color": "#111827",
        "warning_color": "#FFB454",
    }


def _minimal_graph(output: Path, *, extra=()):
    nodes = [
        ActionNode(
            "create",
            "powerpoint.create_presentation",
            {"height": 7.5, "output_path": str(output.resolve()), "width": 13.333},
        ),
        ActionNode("theme", "powerpoint.set_theme", _theme()),
        ActionNode(
            "slide-one",
            "powerpoint.add_slide",
            {"background_color": "#080B12", "slide_id": "slide-one"},
        ),
        *extra,
        ActionNode(
            "save",
            "powerpoint.save_presentation",
            {"output_path": str(output.resolve())},
        ),
        ActionNode("inspect", "powerpoint.inspect_presentation", {}),
    ]
    edges = tuple(
        ActionEdge(nodes[index].node_id, nodes[index + 1].node_id)
        for index in range(len(nodes) - 1)
    )
    return ActionGraph(
        PLUGIN,
        VERSION,
        _descriptor().adapter_sha256,
        tuple(nodes),
        edges,
    )


def _context(output):
    return {
        "output_path": str(output.resolve()),
        "target": {
            "executable": "powerpnt.exe",
            "executable_version": "16.0.20326.20112",
            "hwnd": 101,
            "pid": 202,
        },
    }


def test_signed_powerpoint_adapter_preflights_a_complete_plan_without_touching_com(
    tmp_path,
):
    output = tmp_path / "deck.pptx"
    registry = _registry()
    validated = validate_action_graph(_minimal_graph(output), registry)

    with AdapterHost(
        _descriptor(), session_nonce="nonce", session_context=_context(output)
    ) as host:
        host.preflight(
            validated.ordered_nodes,
            validation_sha256=validated.validation_sha256,
        )

    assert not output.exists()


def test_animation_category_mismatch_rejects_the_whole_plan_before_effects(tmp_path):
    output = tmp_path / "deck.pptx"
    text = ActionNode(
        "headline",
        "powerpoint.add_text",
        {
            "align": "left",
            "bold": True,
            "color": "#F5F7FB",
            "font_family": "Aptos Display",
            "font_size": 44,
            "height": 1.0,
            "left": 1.0,
            "object_id": "headline",
            "slide_id": "slide-one",
            "text": "Outcome",
            "top": 1.0,
            "transparency": 0,
            "vertical_align": "top",
            "width": 10.0,
        },
    )
    bad = ActionNode(
        "bad-animation",
        "powerpoint.add_animation",
        {
            "category": "entrance",
            "delay_s": 0,
            "direction": "none",
            "duration_s": 0.4,
            "effect": "spin",
            "object_id": "headline",
            "order": 1,
            "slide_id": "slide-one",
            "trigger": "after_previous",
        },
    )
    registry = _registry()
    validated = validate_action_graph(
        _minimal_graph(output, extra=(text, bad)), registry
    )

    with AdapterHost(
        _descriptor(), session_nonce="nonce", session_context=_context(output)
    ) as host:
        with pytest.raises(AdapterProtocolError, match="disagrees with its category"):
            host.preflight(
                validated.ordered_nodes,
                validation_sha256=validated.validation_sha256,
            )

    assert not output.exists()


def test_full_bounded_animation_catalog_and_both_transitions_preflight(tmp_path):
    output = tmp_path / "animation-catalog.pptx"
    text = ActionNode(
        "target",
        "powerpoint.add_text",
        {
            "align": "center",
            "bold": True,
            "color": "#F5F7FB",
            "font_family": "Aptos Display",
            "font_size": 36,
            "height": 1.0,
            "left": 2.0,
            "object_id": "target",
            "slide_id": "slide-one",
            "text": "Animated",
            "top": 2.0,
            "transparency": 0,
            "vertical_align": "middle",
            "width": 5.0,
        },
    )
    catalog = {
        "entrance": ("appear", "fade", "fly_in", "wipe", "zoom"),
        "emphasis": ("pulse", "grow_shrink", "spin", "color_change"),
        "exit": ("disappear", "fade", "fly_out", "wipe_exit"),
        "motion": ("line", "arc"),
    }
    animations = []
    order = 0
    for category, effects in catalog.items():
        for effect in effects:
            order += 1
            animations.append(
                ActionNode(
                    f"animation-{order}",
                    "powerpoint.add_animation",
                    {
                        "category": category,
                        "delay_s": 0,
                        "direction": "none" if category != "entrance" else "right",
                        "duration_s": 0.3,
                        "effect": effect,
                        "object_id": "target",
                        "order": order,
                        "slide_id": "slide-one",
                        "trigger": "after_previous",
                    },
                )
            )
    transition_one = ActionNode(
        "fade-transition",
        "powerpoint.set_transition",
        {
            "advance_on_click": True,
            "duration_s": 0.5,
            "effect": "fade",
            "slide_id": "slide-one",
        },
    )
    second_slide = ActionNode(
        "slide-two",
        "powerpoint.add_slide",
        {"background_color": "#080B12", "slide_id": "slide-two"},
    )
    transition_two = ActionNode(
        "morph-transition",
        "powerpoint.set_transition",
        {
            "advance_on_click": True,
            "duration_s": 0.5,
            "effect": "morph",
            "slide_id": "slide-two",
        },
    )
    registry = _registry()
    validated = validate_action_graph(
        _minimal_graph(
            output,
            extra=(text, *animations, transition_one, second_slide, transition_two),
        ),
        registry,
    )

    with AdapterHost(
        _descriptor(), session_nonce="nonce", session_context=_context(output)
    ) as host:
        host.preflight(
            validated.ordered_nodes,
            validation_sha256=validated.validation_sha256,
        )

    assert order == 15
    assert not output.exists()


def test_exit_category_sets_the_powerpoint_effect_exit_flag():
    spec = importlib.util.spec_from_file_location("candidate_powerpoint_adapter", ADAPTER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    timing = SimpleNamespace(Duration=None, TriggerDelayTime=None)
    effect = SimpleNamespace(
        Timing=timing,
        EffectParameters=SimpleNamespace(Direction=None),
        MoveTo=lambda _order: None,
    )
    sequence = SimpleNamespace(AddEffect=lambda *_args: effect)
    session = module.PowerPointSession(
        {
            "output_path": str(Path("deck.pptx").resolve()),
            "target": {
                "executable": "powerpnt.exe",
                "executable_version": "16.0",
                "hwnd": 101,
                "pid": 202,
            },
        }
    )
    session.slides["slide"] = SimpleNamespace(
        TimeLine=SimpleNamespace(MainSequence=sequence)
    )
    session.shapes[("slide", "object")] = object()
    # No "msoTrue" here, deliberately. It lives in the Office type library,
    # not PowerPoint's, so `win32com.client.constants` never exposes it on a
    # real desktop -- measured on build 16.0.20326. Stubbing it is what let
    # this test pass while every exit animation refused in production. A
    # constants stub must not contain a name the application does not.
    constants = {
        "msoAnimEffectFly": 1,
        "msoAnimTriggerOnPageClick": 2,
    }
    session._const = lambda *names: next(
        constants[name] for name in names if name in constants
    )

    session.do_powerpoint_add_animation(
        {
            "category": "exit",
            "delay_s": 0,
            "direction": "none",
            "duration_s": 0.4,
            "effect": "fly_out",
            "object_id": "object",
            "order": 1,
            "slide_id": "slide",
            "trigger": "on_click",
        }
    )

    # A plain bool: COM marshals it to VARIANT_BOOL, and it needs no constant
    # the application might not expose.
    assert effect.Exit is True


def _minimal_pptx(path: Path):
    content_types = b'<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>'
    presentation = b'<?xml version="1.0" encoding="UTF-8"?><p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>'
    slide = b'<?xml version="1.0" encoding="UTF-8"?><p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld name="slide-one"><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="2" name="headline"/></p:nvSpPr><p:txBody><a:p xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:r><a:t>Outcome</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("ppt/presentation.xml", presentation)
        archive.writestr("ppt/slides/slide1.xml", slide)
        archive.writestr(
            "padding.bin",
            b"".join(
                hashlib.sha256(str(index).encode()).digest() for index in range(64)
            ),
        )


def test_separate_signed_verifier_reads_the_saved_package_not_adapter_claims(tmp_path):
    output = tmp_path / "deck.pptx"
    _minimal_pptx(output)
    node = ActionNode(
        "headline",
        "powerpoint.add_text",
        {
            "slide_id": "slide-one",
            "object_id": "headline",
            "text": "Outcome",
        },
    )

    result = VerifierHost(_descriptor()).verify(
        node=node,
        validation_sha256="e" * 64,
        output_path=str(output),
        target=_context(output)["target"],
    )

    assert result.verified
    assert result.observed["object_id"] == "headline"


# --- the transition the verifier could not see (Phase A finding) -----------

_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def _slide_with_wrapped_transition(effect: str = "fade") -> bytes:
    """The shape PowerPoint 16.0.20326 actually saved, not an invented one.

    Copied from the transition written by the first instrumented Phase A run:
    a duration makes PowerPoint emit p14:dur, which forces the whole element
    into mc:AlternateContent with an mc:Fallback carrying the plain form. The
    transition is then a GRANDCHILD of p:sld.
    """

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        ' xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
        ' xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main">'
        '<p:cSld name="slide-one"><p:spTree/></p:cSld>'
        '<mc:AlternateContent><mc:Choice Requires="p14">'
        f'<p:transition spd="med" p14:dur="550"><p:{effect}/></p:transition>'
        '</mc:Choice><mc:Fallback>'
        f'<p:transition spd="med"><p:{effect}/></p:transition>'
        "</mc:Fallback></mc:AlternateContent></p:sld>"
    ).encode("utf-8")


def _slide_without_transition() -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        '<p:cSld name="slide-one"><p:spTree/></p:cSld></p:sld>'
    ).encode("utf-8")


def _package_with_slide(path: Path, slide_xml: bytes) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            b'<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
        )
        archive.writestr(
            "ppt/presentation.xml",
            b'<?xml version="1.0" encoding="UTF-8"?><p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>',
        )
        archive.writestr("ppt/slides/slide1.xml", slide_xml)
        # The verifier refuses an implausibly small package before it parses
        # anything; the same padding the other fixture uses gets past that
        # floor without changing what is being tested.
        archive.writestr(
            "padding.bin",
            b"".join(
                hashlib.sha256(str(index).encode()).digest() for index in range(64)
            ),
        )


def _transition_node():
    return ActionNode(
        "transition",
        "powerpoint.set_transition",
        {
            "advance_on_click": True,
            "duration_s": 0.55,
            "effect": "fade",
            "slide_id": "slide-one",
        },
    )


def test_the_verifier_sees_a_transition_wrapped_in_alternate_content(tmp_path):
    """Phase A's measured defect.

    `root.find()` matches direct children only, so a transition PowerPoint
    wrapped in mc:AlternateContent was invisible to it. The adapter had
    written the transition correctly; every run refused at node 25 anyway.
    """

    output = tmp_path / "deck.pptx"
    _package_with_slide(output, _slide_with_wrapped_transition())

    result = VerifierHost(_descriptor()).verify(
        node=_transition_node(),
        validation_sha256="e" * 64,
        output_path=str(output),
        target=_context(output)["target"],
    )

    assert result.verified
    assert result.observed["transition_elements"] == 2


def test_a_slide_with_a_transition_as_a_direct_child_still_verifies(tmp_path):
    """The unwrapped form must keep working: a transition with no duration is
    emitted directly under p:sld."""

    output = tmp_path / "deck.pptx"
    _package_with_slide(
        output,
        (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            '<p:cSld name="slide-one"><p:spTree/></p:cSld>'
            '<p:transition spd="med"><p:fade/></p:transition></p:sld>'
        ).encode("utf-8"),
    )

    result = VerifierHost(_descriptor()).verify(
        node=_transition_node(),
        validation_sha256="e" * 64,
        output_path=str(output),
        target=_context(output)["target"],
    )

    assert result.verified
    assert result.observed["transition_elements"] == 1


def test_a_slide_with_no_transition_at_all_is_still_refused(tmp_path):
    """Non-vacuity. Widening the search must not make the check unfailable --
    the point of the fix is to see a real transition, not to stop looking."""

    output = tmp_path / "deck.pptx"
    _package_with_slide(output, _slide_without_transition())

    result = VerifierHost(_descriptor()).verify(
        node=_transition_node(),
        validation_sha256="e" * 64,
        output_path=str(output),
        target=_context(output)["target"],
    )

    assert not result.verified
    assert "no approved transition" in result.detail


def test_a_transition_buried_deeper_than_slide_level_is_not_accepted(tmp_path):
    """The fix is scoped to slide level and one AlternateContent below it, not
    a whole-subtree search. This project has already paid for matching looser
    than the thing it identifies (rung 3)."""

    output = tmp_path / "deck.pptx"
    _package_with_slide(
        output,
        (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            '<p:cSld name="slide-one"><p:spTree>'
            '<p:transition spd="med"><p:fade/></p:transition>'
            "</p:spTree></p:cSld></p:sld>"
        ).encode("utf-8"),
    )

    result = VerifierHost(_descriptor()).verify(
        node=_transition_node(),
        validation_sha256="e" * 64,
        output_path=str(output),
        target=_context(output)["target"],
    )

    assert not result.verified
