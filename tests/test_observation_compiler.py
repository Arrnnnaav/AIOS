"""Compiling a verified recipe into one bounded observation tick.

A recipe declares every control its action, its verification, and its
wrong-action context need. The compiler turns that declaration into a plan --
which traversals to run, which selectors read from each -- so one worker tick
observes the whole union with no workflow-specific Python.

Three rules carry the weight here, and each is mutation-checked:

* grouping is strategy-specific -- a bounded walk is shared by control type
  because the traversal is what it costs; a provider call performs no traversal
  and collapses only on an identical full query;
* cardinality is evaluated per selector, over that selector's own results,
  after filtering rather than during it;
* a non-absence fault invalidates the entire tick, because a partial
  observation is indistinguishable from a screen where those controls are
  absent.
"""

from __future__ import annotations

import pytest

from ghostcursor.packs.compile import (
    AT_LEAST_ONE,
    EXACTLY_ONE,
    RecipeCompileError,
    compile_observation_plan,
    compile_recipe,
)
from ghostcursor.perception.service import run_observation_plan
from ghostcursor.perception.uia import (
    Element,
    ProviderQueryFault,
    SelectorAmbiguityFault,
)
from ghostcursor.reasoning.verification import MissingSelectorObservation

GLYPH = ""


# --------------------------------------------------------------------------
# Recipe fixtures
# --------------------------------------------------------------------------


def _selector(
    strategy="bounded_descendants",
    control_type="Button",
    names=("Open Folder...",),
    normalise="strip_leading_private_use",
    cardinality=EXACTLY_ONE,
    result_limit=4,
):
    return {
        "strategy": strategy,
        "control_type": control_type,
        "names": list(names),
        "normalise": normalise,
        "cardinality": cardinality,
        "result_limit": result_limit,
    }


def _step(
    target="open_folder", kind="element_appears", selector="folder_title", args=None
):
    return {
        "user_action": "click",
        "target_selector": target,
        "target_descriptor": {
            "claimed": {
                "name": "Open Folder...",
                "name_synonyms": [],
                "ocr_text": None,
                "visual_description": None,
            },
            "confirmed": [],
        },
        "instruction_text": "Click Open Folder",
        "verification_rule": {
            "kind": kind,
            "selector": selector,
            "args": {} if args is None else args,
            "timeout_s": 20.0,
        },
        "risk": "normal",
        "preconditions": [],
        "provenance": {
            "source_urls": [],
            "source_tier": "trusted",
            "model": "none",
            "prompt_version": "none",
            "created_at": "2026-08-27T00:00:00Z",
        },
    }


def _recipe(selectors=None, steps=None, context=("panel",)):
    return {
        "schema_version": 2,
        "intent_id": "OPEN_FOLDER",
        "step_key_namespace": "vscode.open_folder",
        "selectors": selectors
        if selectors is not None
        else {
            "open_folder": _selector(),
            "folder_title": _selector(cardinality=AT_LEAST_ONE),
            "panel": _selector(
                control_type="Pane",
                names=("Terminal Section",),
                cardinality=AT_LEAST_ONE,
            ),
        },
        "context_selectors": list(context),
        "steps": steps if steps is not None else [_step()],
    }


# --------------------------------------------------------------------------
# Grouping
# --------------------------------------------------------------------------


def test_one_traversal_per_control_type_shared_by_every_selector() -> None:
    plan = compile_observation_plan(_recipe())

    buttons = [t for t in plan.traversals if t.control_type == "Button"]
    assert len(buttons) == 1, "two Button selectors must share one walk"
    assert set(buttons[0].selector_ids) == {"open_folder", "folder_title"}
    assert {t.control_type for t in plan.traversals} == {"Button", "Pane"}
    assert plan.queries == ()


def test_provider_queries_group_only_on_an_identical_full_query() -> None:
    """Control type alone is not a grouping key for a provider call.

    A provider call performs no traversal, so there is nothing to share by
    control type. Two selectors of the same type asking for different names are
    two calls; grouping them would send one query and answer the other from it.
    """
    selectors = {
        "extensions": _selector(
            strategy="provider_exact", names=("Extensions",), normalise="none"
        ),
        "extensions_again": _selector(
            strategy="provider_exact",
            names=("Extensions",),
            normalise="none",
            cardinality=AT_LEAST_ONE,
        ),
        "settings": _selector(
            strategy="provider_exact", names=("Settings",), normalise="none"
        ),
    }
    plan = compile_observation_plan(
        _recipe(
            selectors=selectors,
            steps=[_step(target="extensions", selector="extensions_again")],
            context=("settings",),
        )
    )

    assert plan.traversals == ()
    by_name = {query.name: query for query in plan.queries}
    assert set(by_name) == {"Extensions", "Settings"}
    assert set(by_name["Extensions"].selector_ids) == {"extensions", "extensions_again"}
    assert by_name["Settings"].selector_ids == ("settings",)


def test_the_plan_covers_action_verification_and_context_selectors() -> None:
    plan = compile_observation_plan(_recipe())
    covered = {sid for t in plan.traversals for sid in t.selector_ids}
    covered |= {sid for q in plan.queries for sid in q.selector_ids}
    assert covered == set(plan.selectors) == {"open_folder", "folder_title", "panel"}


def test_compiling_preserves_declared_cardinality_and_limit() -> None:
    plan = compile_observation_plan(_recipe())
    assert plan.selectors["open_folder"].cardinality == EXACTLY_ONE
    assert plan.selectors["folder_title"].cardinality == AT_LEAST_ONE
    assert plan.selectors["open_folder"].result_limit == 4


def test_compile_recipe_carries_steps_and_verification() -> None:
    compiled = compile_recipe(_recipe())
    assert compiled.intent_id == "OPEN_FOLDER"
    assert compiled.context_selectors == ("panel",)
    assert len(compiled.steps) == 1
    step = compiled.steps[0]
    assert step.target_selector == "open_folder"
    assert step.verification.kind == "element_appears"
    assert step.verification.selector_id == "folder_title"
    assert step.verification.timeout_s == 20.0


def test_a_positional_automation_id_is_rejected_at_the_compiler() -> None:
    """The third independent boundary, not a restatement of the other two.

    `promote()` and `ObservationStore.record()` each reject these already. The
    compiler rejects them too, so a recipe carrying one never reaches either
    rather than relying on one of them having caught it.
    """
    step = _step(
        kind="focus_moves_to", selector=None, args={"automation_id": "list_id_3_7"}
    )
    with pytest.raises(RecipeCompileError) as caught:
        compile_recipe(_recipe(steps=[step]))
    assert "list_id_3_7" in str(caught.value)


def test_a_non_positional_automation_id_still_compiles() -> None:
    step = _step(
        kind="focus_moves_to",
        selector=None,
        args={"automation_id": "workbench.action.files.openFolder"},
    )
    compiled = compile_recipe(_recipe(steps=[step]))
    assert compiled.steps[0].verification.kind == "focus_moves_to"


# --------------------------------------------------------------------------
# Running a plan
# --------------------------------------------------------------------------


class _Ctl:
    def __init__(
        self,
        name,
        control_type="Button",
        bbox=(10, 10, 110, 40),
        raises=None,
        runtime_id=None,
    ):
        self._name = name
        self._control_type = control_type
        self._bbox = bbox
        self._raises = raises
        self._runtime_id = runtime_id

    def window_text(self):
        if self._raises is not None:
            raise self._raises
        return self._name

    def rectangle(self):
        rect = type("R", (), {})()
        rect.left, rect.top, rect.right, rect.bottom = self._bbox
        return rect

    @property
    def element_info(self):
        info = type("I", (), {})()
        info.control_type = self._control_type
        info.automation_id = ""
        if self._runtime_id is not None:
            info.runtime_id = self._runtime_id
        return info


def _runner(by_type, *, queries=None, calls=None):
    def walk_for(control_type):
        if calls is not None:
            calls.append(control_type)
        return lambda: list(by_type.get(control_type, []))

    def query_for(control_type, name):
        if calls is not None:
            calls.append((control_type, name))
        return lambda: list((queries or {}).get(name, []))

    class _Info:
        def __init__(self, raw):
            self.name = raw
            self.control_type = "Button"
            self.automation_id = ""
            self.rectangle = type(
                "R", (), {"left": 1, "top": 2, "right": 3, "bottom": 4}
            )()

    return walk_for, query_for, _Info


def test_a_shared_traversal_runs_once_and_each_selector_filters_it() -> None:
    calls: list = []
    walk_for, query_for, make_info = _runner(
        {
            "Button": [_Ctl(f"{GLYPH} Open Folder...")],
            "Pane": [_Ctl("Terminal Section", "Pane")],
        },
        calls=calls,
    )
    plan = compile_observation_plan(_recipe())

    observed = run_observation_plan(
        plan, walk_for=walk_for, query_for=query_for, make_info=make_info
    )
    assert calls.count("Button") == 1, (
        "the Button walk must run once for both selectors"
    )
    assert len(observed.selectors["open_folder"]) == 1
    assert len(observed.selectors["folder_title"]) == 1
    assert len(observed.selectors["panel"]) == 1


def test_the_published_name_is_the_raw_one_even_when_matching_normalised() -> None:
    """Matching strips a leading private-use glyph; publishing must not.

    A cleaned-up name would make the observation disagree with the screen, and
    every downstream trust decision keys off the observation.
    """
    walk_for, query_for, make_info = _runner(
        {"Button": [_Ctl(f"{GLYPH} Open Folder...")], "Pane": []}
    )
    observed = run_observation_plan(
        compile_observation_plan(_recipe()),
        walk_for=walk_for,
        query_for=query_for,
        make_info=make_info,
    )
    assert observed.selectors["open_folder"][0].name == f"{GLYPH} Open Folder..."


def test_a_clean_absence_publishes_an_empty_result() -> None:
    walk_for, query_for, make_info = _runner({"Button": [], "Pane": []})
    observed = run_observation_plan(
        compile_observation_plan(_recipe()),
        walk_for=walk_for,
        query_for=query_for,
        make_info=make_info,
    )
    assert dict(observed.selectors) == {"open_folder": (), "folder_title": (), "panel": ()}


def test_cardinality_is_judged_per_selector_over_the_shared_candidates() -> None:
    """Two matches: fine for the at_least_one selector, a fault for the action.

    Both read the same walk, so the difference can only come from each selector
    judging its own declared cardinality.
    """
    walk_for, query_for, make_info = _runner(
        {
            "Button": [
                _Ctl("Open Folder...", bbox=(0, 0, 10, 10)),
                _Ctl("Open Folder...", bbox=(20, 20, 30, 30)),
            ],
            "Pane": [],
        }
    )
    plan = compile_observation_plan(_recipe())
    with pytest.raises(SelectorAmbiguityFault):
        run_observation_plan(
            plan, walk_for=walk_for, query_for=query_for, make_info=make_info
        )

    verification_only = compile_observation_plan(
        _recipe(
            selectors={"folder_title": _selector(cardinality=AT_LEAST_ONE)},
            steps=[_step(target=None, selector="folder_title")],
            context=(),
        )
    )
    observed = run_observation_plan(
        verification_only, walk_for=walk_for, query_for=query_for, make_info=make_info
    )
    assert len(observed.selectors["folder_title"]) == 2


def test_a_fault_invalidates_the_whole_tick_rather_than_publishing_a_part() -> None:
    """No partial observation. The caller gets an exception, not a dict.

    A published partial would show the faulted selector as empty, and a
    verification reading it would conclude the control is absent -- turning a
    provider failure into a confident wrong answer.
    """
    walk_for, query_for, make_info = _runner(
        {
            "Button": [_Ctl("Open Folder...")],
            "Pane": [
                _Ctl("Terminal Section", "Pane", raises=OSError("provider went away"))
            ],
        }
    )
    with pytest.raises(ProviderQueryFault):
        run_observation_plan(
            compile_observation_plan(_recipe()),
            walk_for=walk_for,
            query_for=query_for,
            make_info=make_info,
        )


def test_a_walk_that_raises_faults_the_tick() -> None:
    def walk_for(control_type):
        def _boom():
            raise OSError("RPC server unavailable")

        return _boom

    _unused, query_for, make_info = _runner({})
    with pytest.raises(ProviderQueryFault):
        run_observation_plan(
            compile_observation_plan(_recipe()),
            walk_for=walk_for,
            query_for=query_for,
            make_info=make_info,
        )


def test_a_provider_selector_over_its_result_limit_faults() -> None:
    selectors = {
        "extensions": _selector(
            strategy="provider_exact",
            names=("Extensions",),
            normalise="none",
            cardinality=AT_LEAST_ONE,
            result_limit=1,
        ),
    }
    plan = compile_observation_plan(
        _recipe(
            selectors=selectors,
            steps=[_step(target=None, selector="extensions")],
            context=(),
        )
    )
    walk_for, query_for, make_info = _runner(
        {}, queries={"Extensions": ["Extensions", "Extensions"]}
    )
    with pytest.raises(ProviderQueryFault) as caught:
        run_observation_plan(
            plan, walk_for=walk_for, query_for=query_for, make_info=make_info
        )
    assert "over the result limit of 1" in str(caught.value)


# --------------------------------------------------------------------------
# Selector-backed verification
# --------------------------------------------------------------------------


def _snapshot(**selector_results):
    from ghostcursor.reasoning.verification import Snapshot

    return Snapshot(
        title="",
        elements=(),
        selector_results=tuple(selector_results.items()),
    )


def _element(name="Terminal Section", bbox=(0, 0, 1, 1)):
    return Element(
        name=name, control_type="Pane", automation_id="", bbox=bbox, path=("Pane",)
    )


@pytest.mark.parametrize(
    "kind,before,after,expected",
    [
        ("ELEMENT_APPEARS", (), (_element(),), True),
        ("ELEMENT_APPEARS", (_element(),), (_element(),), False),
        ("ELEMENT_APPEARS", (), (), False),
        ("ELEMENT_DISAPPEARS", (_element(),), (), True),
        ("ELEMENT_DISAPPEARS", (), (), False),
        ("ELEMENT_DISAPPEARS", (_element(),), (_element(),), False),
    ],
)
def test_selector_backed_presence_verification(kind, before, after, expected) -> None:
    from ghostcursor.reasoning.schema import VerificationKind, VerificationRule
    from ghostcursor.reasoning.verification import verify

    rule = VerificationRule(getattr(VerificationKind, kind), selector="panel")
    assert verify(rule, _snapshot(panel=before), _snapshot(panel=after)) is expected


def test_property_changes_needs_the_control_present_on_both_sides() -> None:
    from ghostcursor.reasoning.schema import VerificationKind, VerificationRule
    from ghostcursor.reasoning.verification import verify

    rule = VerificationRule(
        VerificationKind.PROPERTY_CHANGES, args={"property": "bbox"}, selector="panel"
    )
    moved = _element(bbox=(5, 5, 6, 6))
    assert (
        verify(rule, _snapshot(panel=(_element(),)), _snapshot(panel=(moved,))) is True
    )
    assert (
        verify(rule, _snapshot(panel=(_element(),)), _snapshot(panel=(_element(),)))
        is False
    )
    # An appearance is not a property change.
    assert verify(rule, _snapshot(panel=()), _snapshot(panel=(moved,))) is False


def test_a_rule_without_a_selector_keeps_the_v1_descriptor_behaviour() -> None:
    """Adding the field changes nothing until a compiled recipe supplies it."""
    from ghostcursor.reasoning.schema import VerificationKind, VerificationRule
    from ghostcursor.reasoning.verification import Snapshot, verify

    rule = VerificationRule(
        VerificationKind.ELEMENT_APPEARS,
        args={"target_descriptor": {"name": "Terminal Section"}},
    )
    assert rule.selector is None
    before = Snapshot(title="", elements=())
    after = Snapshot(title="", elements=(_element(),))
    assert verify(rule, before, after) is True


def test_an_unobserved_selector_faults_rather_than_reading_as_absence() -> None:
    """Only a published empty tuple is a clean absence.

    Answering `()` for a selector the snapshot never observed flattens "no
    observation" into "the control is not there". The two tests below show
    what that cost: both presence rules passed on a snapshot that simply
    omitted the selector.
    """
    snapshot = _snapshot(panel=(_element(),))
    assert snapshot.matched("panel") == (_element(),)
    with pytest.raises(MissingSelectorObservation):
        snapshot.matched("never_observed")

    observed_empty = _snapshot(panel=())
    assert observed_empty.matched("panel") == ()


def test_disappearance_is_not_concluded_from_a_missing_after_observation() -> None:
    from ghostcursor.reasoning.schema import VerificationKind, VerificationRule
    from ghostcursor.reasoning.verification import Snapshot, verify

    rule = VerificationRule(VerificationKind.ELEMENT_DISAPPEARS, selector="panel")
    unobserved = Snapshot(title="", elements=(), selector_results=())
    with pytest.raises(MissingSelectorObservation):
        verify(rule, _snapshot(panel=(_element(),)), unobserved)


def test_appearance_is_not_concluded_from_a_missing_before_observation() -> None:
    """The same hole in the other direction.

    `element_appears` needs the control absent BEFORE. A snapshot that never
    observed the selector satisfied that as readily as one that observed it
    empty.
    """
    from ghostcursor.reasoning.schema import VerificationKind, VerificationRule
    from ghostcursor.reasoning.verification import Snapshot, verify

    rule = VerificationRule(VerificationKind.ELEMENT_APPEARS, selector="panel")
    unobserved = Snapshot(title="", elements=(), selector_results=())
    with pytest.raises(MissingSelectorObservation):
        verify(rule, unobserved, _snapshot(panel=(_element(),)))


# --------------------------------------------------------------------------
# Declared normalisation
# --------------------------------------------------------------------------


def test_a_none_normalise_selector_does_not_accept_a_glyph_prefixed_name() -> None:
    """Migration must not broaden certified behaviour.

    Open Terminal's certified walker accepts exactly `Toggle Panel (Ctrl+J)`
    and `Terminal Section`. Its v2 selectors declare `normalise: "none"`, and
    that declaration has to reach the walk -- a runtime that always normalised
    would make the strict selector quietly accept names the certified walker
    rejects, with nothing in the recipe to show it.
    """
    plan = compile_observation_plan(
        _recipe(
            selectors={
                "toggle": _selector(names=("Toggle Panel (Ctrl+J)",), normalise="none")
            },
            steps=[_step(target="toggle", kind="focus_moves_to", selector=None,
                         args={"automation_id": "workbench.panel.toggle"})],
            context=(),
        )
    )
    assert plan.selectors["toggle"].normalise == "none"

    walk_for, query_for, make_info = _runner(
        {"Button": [_Ctl(f"{GLYPH} Toggle Panel (Ctrl+J)")]}
    )
    assert dict(
        run_observation_plan(
            plan, walk_for=walk_for, query_for=query_for, make_info=make_info
        ).selectors
    ) == {"toggle": ()}

    walk_for, query_for, make_info = _runner(
        {"Button": [_Ctl("Toggle Panel (Ctrl+J)")]}
    )
    exact = run_observation_plan(
        plan, walk_for=walk_for, query_for=query_for, make_info=make_info
    )
    assert len(exact.selectors["toggle"]) == 1


def test_two_selectors_over_one_walk_may_declare_different_normalisation() -> None:
    """The traversal is shared; the matching rule is not.

    Grouping by control type is a cost optimisation. If it also merged the
    selectors' matching rules, one strict selector sharing a walk with a
    lenient one would silently inherit the lenient rule.
    """
    plan = compile_observation_plan(
        _recipe(
            selectors={
                "strict": _selector(names=("Open Folder...",), normalise="none"),
                "lenient": _selector(names=("Open Folder...",),
                                     cardinality=AT_LEAST_ONE),
            },
            steps=[_step(target="strict", selector="lenient")],
            context=(),
        )
    )
    assert len([t for t in plan.traversals if t.control_type == "Button"]) == 1

    walk_for, query_for, make_info = _runner(
        {"Button": [_Ctl(f"{GLYPH} Open Folder...")]}
    )
    observed = run_observation_plan(
        plan, walk_for=walk_for, query_for=query_for, make_info=make_info
    )
    assert observed.selectors["strict"] == ()
    assert len(observed.selectors["lenient"]) == 1


# --------------------------------------------------------------------------
# One read per compiled group, one deduplicated published union
# --------------------------------------------------------------------------


def test_one_compiled_query_performs_exactly_one_find_all() -> None:
    """Compiling a query once is worthless if it executes once per selector.

    Cost is the smaller half. Two reads inside one tick observe two different
    screens, so two selectors on the SAME compiled query could disagree about
    how many controls exist -- and neither read looks wrong on its own, so
    nothing downstream can detect the disagreement.
    """
    selectors = {
        "extensions": _selector(strategy="provider_exact", names=("Extensions",),
                                normalise="none"),
        "extensions_again": _selector(strategy="provider_exact", names=("Extensions",),
                                      normalise="none", cardinality=AT_LEAST_ONE),
    }
    plan = compile_observation_plan(
        _recipe(selectors=selectors,
                steps=[_step(target="extensions", selector="extensions_again")],
                context=())
    )
    assert len(plan.queries) == 1
    assert len(plan.queries[0].selector_ids) == 2

    invocations = []

    def query_for(control_type, name):
        def _find_all():
            invocations.append(name)
            return ["Extensions"]

        return _find_all

    walk_for, _unused, make_info = _runner({})
    observed = run_observation_plan(
        plan, walk_for=walk_for, query_for=query_for, make_info=make_info
    )
    assert invocations == ["Extensions"], "one compiled query is one FindAll"
    assert len(observed.selectors["extensions"]) == 1
    assert len(observed.selectors["extensions_again"]) == 1


def test_a_shared_read_is_judged_separately_by_each_selector() -> None:
    """One read, two cardinalities, and the strict one still faults."""
    selectors = {
        "strict": _selector(strategy="provider_exact", names=("Extensions",),
                            normalise="none"),
        "lenient": _selector(strategy="provider_exact", names=("Extensions",),
                             normalise="none", cardinality=AT_LEAST_ONE),
    }
    plan = compile_observation_plan(
        _recipe(selectors=selectors,
                steps=[_step(target="strict", selector="lenient")], context=())
    )
    walk_for, query_for, make_info = _runner(
        {}, queries={"Extensions": ["Extensions", "Extensions"]}
    )
    with pytest.raises(SelectorAmbiguityFault):
        run_observation_plan(
            plan, walk_for=walk_for, query_for=query_for, make_info=make_info
        )


def test_the_published_union_collapses_one_control_reached_twice() -> None:
    """Two selectors, one control, one entry in the union.

    The union has to be built worker-side for this to be possible at all. By
    the time only `Element`s remain there is no backend identity left, and
    merging them would mean value equality -- which cannot tell one control
    reached by two selectors from two controls that agree on every field.
    """
    plan = compile_observation_plan(
        _recipe(
            selectors={
                "action": _selector(names=("Open Folder...",)),
                "check": _selector(names=("Open Folder...",), cardinality=AT_LEAST_ONE),
            },
            steps=[_step(target="action", selector="check")],
            context=(),
        )
    )
    walk_for, query_for, make_info = _runner(
        {"Button": [_Ctl("Open Folder...", runtime_id=(42, 7))]}
    )
    observed = run_observation_plan(
        plan, walk_for=walk_for, query_for=query_for, make_info=make_info
    )
    assert len(observed.selectors["action"]) == 1
    assert len(observed.selectors["check"]) == 1
    assert len(observed.union) == 1


def test_the_union_keeps_two_controls_the_backend_cannot_tell_apart() -> None:
    """No identity means retain both -- never a value merge.

    These two agree on name, control type, AutomationId and bbox. Collapsing
    them would report one control where the screen has two, which is the
    ambiguity the cardinality rule exists to surface.
    """
    plan = compile_observation_plan(
        _recipe(
            selectors={"check": _selector(names=("Open Folder...",),
                                          cardinality=AT_LEAST_ONE)},
            steps=[_step(target=None, selector="check")],
            context=(),
        )
    )
    walk_for, query_for, make_info = _runner(
        {"Button": [_Ctl("Open Folder..."), _Ctl("Open Folder...")]}
    )
    observed = run_observation_plan(
        plan, walk_for=walk_for, query_for=query_for, make_info=make_info
    )
    assert observed.selectors["check"][0] == observed.selectors["check"][1]
    assert len(observed.union) == 2


def test_the_union_spans_every_group_in_the_tick() -> None:
    plan = compile_observation_plan(_recipe())
    walk_for, query_for, make_info = _runner(
        {
            "Button": [_Ctl("Open Folder...", runtime_id=(1,))],
            "Pane": [_Ctl("Terminal Section", "Pane", runtime_id=(2,))],
        }
    )
    observed = run_observation_plan(
        plan, walk_for=walk_for, query_for=query_for, make_info=make_info
    )
    assert {e.name for e in observed.union} == {"Open Folder...", "Terminal Section"}


def test_a_fault_publishes_no_union_either() -> None:
    walk_for, query_for, make_info = _runner(
        {
            "Button": [_Ctl("Open Folder...")],
            "Pane": [_Ctl("Terminal Section", "Pane", raises=OSError("gone"))],
        }
    )
    with pytest.raises(ProviderQueryFault):
        run_observation_plan(
            compile_observation_plan(_recipe()),
            walk_for=walk_for, query_for=query_for, make_info=make_info,
        )
