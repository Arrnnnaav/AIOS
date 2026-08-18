"""A standing property, not a regression check (D027).

The bug that prompted this was narrow — an OCR-grounded hint drawn once in
the confirmed-control colour before being corrected in the same tick. The
PROPERTY is not narrow, and these tests are written so a future third
perception source or a new staleness rung is covered without anyone
remembering to come back here:

    a hint's very first paint already reflects its final display state,
    because at most one write per tick is even representable.

The cross-product below is generated from `Freshness` itself and from a
source list that deliberately includes an unrecognised one, so adding a rung
to the enum or a tier to perception extends the coverage automatically.
"""

import itertools

import pytest

from ghostcursor.reasoning.grounding import GroundedTarget
from ghostcursor.reasoning.renderer import OverlayRenderer
from ghostcursor.reasoning.staleness import Freshness, display_freshness

TARGET = GroundedTarget((100, 200, 200, 240), 1, "1001", "Button", "Export", "uia")

#: Every source the system can attribute a grounding to, plus one that does
#: not exist yet. `display_freshness` is fail-safe by design — an unrecognised
#: source must render INFERRED, never FRESH — and "vlm" stands in for the next
#: tier so that guarantee is exercised before the tier is written.
SOURCES = ("uia", "ocr", "vlm", "")


class RecordingOverlay:
    """Records every write, in order, with whatever freshness it was given."""

    def __init__(self):
        self.writes = []

    def set_hint(self, hwnd, x, y, radius=24, freshness=None):
        self.writes.append(("set_hint", freshness))

    def clear_hint(self, hwnd):
        self.writes.append(("clear_hint", None))


@pytest.mark.parametrize(
    "ladder_state,source", list(itertools.product(list(Freshness), SOURCES))
)
def test_the_first_paint_is_already_the_final_display_state(ladder_state, source):
    """For EVERY combination of staleness rung and grounding source.

    Not "INFERRED appears somewhere in the sequence" and not "OCR is not drawn
    cyan": the general property is that the opening write is the settled one,
    whatever the two axes happen to say.
    """
    expected = display_freshness(ladder_state, source)
    overlay = RecordingOverlay()
    renderer = OverlayRenderer(
        hwnd=42, overlay=overlay, freshness_source=lambda: expected
    )

    renderer.show(TARGET, "Click Export.")

    assert len(overlay.writes) == 1, (
        f"{source}/{ladder_state.name} produced {len(overlay.writes)} writes "
        f"for one show(): {overlay.writes}"
    )
    kind, drawn = overlay.writes[0]
    if expected is Freshness.HIDDEN:
        # HIDDEN is the one state that must not reach set_hint at all: the
        # painter distinguishes only FRESH from everything-else, so a HIDDEN
        # passed down would draw a DIMMED ring where the design says draw
        # nothing, and the 5s rung would be dead code.
        assert kind == "clear_hint", (
            f"{source}/{ladder_state.name} resolves to HIDDEN but the first "
            f"paint was {overlay.writes[0]} — a ring was drawn instead of none"
        )
    else:
        assert (kind, drawn) == ("set_hint", expected), (
            f"{source}/{ladder_state.name} should paint {expected.name} on the "
            f"FIRST write, but wrote {overlay.writes[0]}"
        )


@pytest.mark.parametrize(
    "ladder_state,source", list(itertools.product(list(Freshness), SOURCES))
)
def test_a_settled_tick_adds_no_second_write(ladder_state, source):
    """The tick's redraw must never become a correction.

    `settle()` exists so a staleness-only transition still reaches the screen.
    If it also fired after the loop had already drawn, it would recreate the
    exact two-step shape D027 forbids — just one layer further down.
    """
    expected = display_freshness(ladder_state, source)
    overlay = RecordingOverlay()
    renderer = OverlayRenderer(
        hwnd=42, overlay=overlay, freshness_source=lambda: expected
    )

    renderer.show(TARGET, "Click Export.")
    renderer.settle()

    assert len(overlay.writes) == 1, (
        f"{source}/{ladder_state.name}: settle() wrote again after the loop "
        f"had already painted this tick: {overlay.writes}"
    )


def test_settle_is_what_carries_a_staleness_only_transition_to_the_screen():
    """The other side of the guard, and the one nothing else covers.

    A `settle()` that was too eager to stay silent would pass every assertion
    above while quietly making the whole staleness ladder dead code: the loop
    calls show() only when it changes WHAT is displayed, never when it changes
    how confident it is.
    """
    state = {"f": Freshness.FRESH}
    overlay = RecordingOverlay()
    renderer = OverlayRenderer(
        hwnd=42, overlay=overlay, freshness_source=lambda: state["f"]
    )

    renderer.show(TARGET, "Click Export.")  # tick 1: the loop draws
    renderer.settle()
    state["f"] = Freshness.DIMMED  # the observation ages
    renderer.settle()  # tick 2: nobody called show()

    assert overlay.writes == [
        ("set_hint", Freshness.FRESH),
        ("set_hint", Freshness.DIMMED),
    ], f"a staleness-only transition never reached the screen: {overlay.writes}"


def test_a_cleared_hint_is_not_resurrected_by_settle():
    """The loop clears the hint when grounding fails. A redraw that ignored
    that would put a ring back over a target the loop deliberately took down —
    pointing the user at a coordinate nothing confirmed.
    """
    overlay = RecordingOverlay()
    renderer = OverlayRenderer(
        hwnd=42, overlay=overlay, freshness_source=lambda: Freshness.FRESH
    )

    renderer.show(TARGET, "Click Export.")
    renderer.settle()
    renderer.clear()
    renderer.settle()
    renderer.settle()

    assert overlay.writes == [
        ("set_hint", Freshness.FRESH),
        ("clear_hint", None),
    ], f"a cleared hint came back: {overlay.writes}"


def test_a_renderer_cannot_be_built_without_declaring_provenance():
    """Structural, not a tripwire.

    This used to be a permissive default policed by a scan over the package.
    A scan passes the day someone adds a construction it does not match, and
    what it was guarding is "unknown provenance draws as a confirmed control"
    — the exact shape D027 exists to remove. The constructor now refuses.
    """
    with pytest.raises(TypeError):
        OverlayRenderer(hwnd=42, overlay=RecordingOverlay())


def test_a_source_that_cannot_answer_resolves_to_inferred_never_fresh():
    """The other half of the closure.

    Requiring the parameter stops omission; this stops a source that exists
    but returns nothing from falling through to `set_hint`'s own default,
    which is FRESH. There is deliberately no code path left that calls
    set_hint without an explicit freshness.
    """
    overlay = RecordingOverlay()
    renderer = OverlayRenderer(hwnd=42, overlay=overlay, freshness_source=lambda: None)

    renderer.show(TARGET, "Click Export.")

    assert overlay.writes == [("set_hint", Freshness.INFERRED)], (
        f"a hint with no answerable provenance was not drawn INFERRED: {overlay.writes}"
    )


def test_exactly_one_hint_write_per_tick_through_a_whole_tour(tmp_path, monkeypatch):
    """The same property, end to end, against the real `run_tour`.

    The renderer-level tests above cannot see a second write issued by the
    TICK LOOP rather than by the renderer — which is exactly where the
    original defect lived. This drives a real tour and buckets every overlay
    write by tick, so any provisional-then-corrected pair is a bucket of two.

    Deliberately grounded through UIA, not OCR: the property is about the
    shape of the render, not about which tier produced the target, and this
    way it also runs on a machine with no OCR language pack.
    """
    import ghostcursor.run as run_module
    from ghostcursor.perception import appinfo, service as service_module
    from ghostcursor.perception.service import Observation
    from ghostcursor.perception.uia import Element
    from ghostcursor.reasoning.verification import Snapshot
    from tests.test_run_threaded import _fake_overlay, _recipe_file

    class Clock:
        def __init__(self):
            self.t = 1000.0

        def __call__(self):
            return self.t

    clock = Clock()

    class SightedService:
        heartbeat = 0

        def start(self):
            pass

        def stop(self):
            pass

        def restart(self):
            pass

        def is_alive(self):
            return True

        # Tier 2 is asked for and called off through the service now, and a
        # step that grounds through UIA calls it off. Accepted and ignored:
        # this test is about the first paint, not about OCR.
        def request_tier2(self, step_index):
            pass

        def cancel_tier2(self, step_index=None):
            pass

        def report_tier2_grounded(self, step_index):
            pass

        def latest(self):
            now = clock()
            elements = (Element("Export", "Button", "btn_export", (10, 20, 110, 44)),)
            return Observation(
                snapshot=Snapshot(title="app", elements=elements, observed_at=now),
                elements=elements,
                observed_at=now,
                ok=True,
            )

    calls = _fake_overlay(monkeypatch)
    monkeypatch.setattr(
        service_module, "PerceptionService", lambda *a, **k: SightedService()
    )
    monkeypatch.setattr(appinfo, "app_info_for_window", lambda _t: None)
    monkeypatch.setattr(run_module, "escape_pressed", lambda: False)
    monkeypatch.setattr(run_module, "key_was_pressed", lambda vk: False)
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)

    # `sleeper` is called exactly once per tick, so it is the tick boundary.
    ticks = []

    def sleeper(seconds):
        ticks.append(len(calls))
        clock.t += seconds

    run_module.run_tour(
        _recipe_file(tmp_path), ".*app.*", seconds=5.0, clock=clock, sleeper=sleeper
    )

    hint_writes = [i for i, c in enumerate(calls) if c[0] in ("set_hint", "clear_hint")]
    per_tick = []
    start = 0
    for boundary in ticks:
        per_tick.append(len([i for i in hint_writes if start <= i < boundary]))
        start = boundary

    assert any(per_tick), f"no hint was ever drawn, so nothing was proved: {calls}"
    assert max(per_tick) <= 1, (
        "a tick wrote to the overlay more than once, which is the "
        "provisional-then-corrected shape D027 forbids — set_hint paints "
        f"synchronously, so the first frame really was displayed: {per_tick}"
    )
