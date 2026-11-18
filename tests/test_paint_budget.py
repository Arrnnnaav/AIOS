from __future__ import annotations

import pytest

from ghostcursor.act_protocol import TrustClass
from ghostcursor.devtools.paint_budget import (
    PaintMeasurementRefused,
    _paint_checked_frame,
)
from ghostcursor.overlay.cue import CueScene


SCENE = CueScene(
    pointer=(20, 20),
    target=(10, 10, 30, 30),
    label="target",
    trust=TrustClass.NEUTRAL,
    final=False,
    label_rect=(40, 10, 100, 35),
)


def test_measured_frame_pays_precheck_paint_and_postcheck_in_order() -> None:
    calls: list[str] = []

    def check(_hwnd, _geometry, _rectangle):
        calls.append("check")
        return ()

    def paint(_hwnd, _scene):
        calls.append("paint")

    _paint_checked_frame(7, SCENE, object(), SCENE.target, check=check, paint=paint)

    assert calls == ["check", "paint", "check"]


def test_prepaint_disagreement_refuses_without_drawing() -> None:
    painted = False

    def paint(_hwnd, _scene):
        nonlocal painted
        painted = True

    with pytest.raises(PaintMeasurementRefused, match="before measured paint"):
        _paint_checked_frame(
            7,
            SCENE,
            object(),
            SCENE.target,
            check=lambda *_args: ("wrong space",),
            paint=paint,
        )

    assert painted is False


def test_postpaint_disagreement_is_not_recorded_as_a_valid_sample() -> None:
    answers = iter(((), ("space moved",)))

    with pytest.raises(PaintMeasurementRefused, match="during measured paint"):
        _paint_checked_frame(
            7,
            SCENE,
            object(),
            SCENE.target,
            check=lambda *_args: next(answers),
            paint=lambda *_args: None,
        )


def test_the_budget_is_p99_rounded_up_never_below_it():
    from ghostcursor.devtools.paint_budget import PaintMeasurement

    m = PaintMeasurement(frames=1, samples=(2.0004,), bounds=(0, 0, 1, 1), monitors=1)
    assert m.budget_ms == 3
