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
    constants = {
        "msoAnimEffectFly": 1,
        "msoAnimTriggerOnPageClick": 2,
        "msoTrue": -1,
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

    assert effect.Exit == -1


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
