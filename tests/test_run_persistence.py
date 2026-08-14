from ghostcursor.memory.store import ObservationStore
from ghostcursor.perception.appinfo import AppInfo
from ghostcursor.reasoning.identity import step_key
from ghostcursor.reasoning.schema import (
    ClaimedDescriptor,
    ConfirmedObservation,
    Recipe,
    Risk,
    Step,
    TargetDescriptor,
    UserAction,
    VerificationKind,
    VerificationRule,
)
from ghostcursor.run import hydrate_recipe, persist_step

APP = AppInfo(app_id="app.exe", exe_path=r"C:\app.exe", version="1.0.0", kind="win32")


def _recipe():
    return Recipe(
        app_id="app",
        intent="export a file",
        steps=[
            Step(
                user_action=UserAction.CLICK,
                target_descriptor=TargetDescriptor(
                    claimed=ClaimedDescriptor(name="Export")
                ),
                instruction_text="Click Export.",
                verification_rule=VerificationRule(kind=VerificationKind.USER_CONFIRMS),
                risk=Risk.NORMAL,
            )
        ],
    )


def test_persist_then_hydrate_round_trips(tmp_path):
    recipe = _recipe()
    recipe.steps[0].target_descriptor.confirmed.append(
        ConfirmedObservation(
            app_version="1.0.0",
            locales_observed=["en-US"],
            automation_id="1001",
            control_type="Button",
        )
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
            step_key("a totally different intent", recipe.steps[0]),
            APP.app_id,
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
        assert (
            store.observations_for(step_key(recipe.intent, recipe.steps[0]), APP.app_id)
            == []
        )


def test_persist_writes_only_the_observation_just_learned(tmp_path):
    """A tour must not rewrite observations it did not touch.

    persist_step used to loop over every confirmed observation on the step and
    write each one. It is called from the grounder on every DECIDING tick, so
    an observation hydrated from a previous run — for a different app version,
    never grounded this run — had its ok_count incremented on every tick. That
    made ok_count count persist calls rather than times-observed, and issued
    N x M writes per tour for no reason.
    """
    from ghostcursor.memory.store import ObservationStore

    recipe = _recipe()
    step = recipe.steps[0]
    stale = ConfirmedObservation(
        app_version="0.9.0", locales_observed=["en-US"],
        automation_id="9999", control_type="Button",
    )
    fresh = ConfirmedObservation(
        app_version="1.0.0", locales_observed=["en-US"],
        automation_id="1001", control_type="Button",
    )
    step.target_descriptor.confirmed.extend([stale, fresh])

    key = step_key(recipe.intent, step)
    with ObservationStore(tmp_path / "kb.sqlite") as store:
        # three ticks, all grounding the SAME live element (1001 on 1.0.0)
        for _ in range(3):
            persist_step(recipe.intent, step, APP.app_id, store, observation=fresh)
        rows = {o.automation_id: o for o in store.observations_for(key, APP.app_id)}

    assert "1001" in rows, "the observation that was actually learned must be written"
    assert "9999" not in rows, (
        "an untouched observation from a previous run was rewritten; "
        "persist_step must write only what this tick learned"
    )


def test_persist_without_an_explicit_observation_writes_them_all(tmp_path):
    """The whole-step form stays available for callers that mean it."""
    from ghostcursor.memory.store import ObservationStore

    recipe = _recipe()
    step = recipe.steps[0]
    step.target_descriptor.confirmed.extend([
        ConfirmedObservation(app_version="0.9.0", automation_id="9999"),
        ConfirmedObservation(app_version="1.0.0", automation_id="1001"),
    ])
    key = step_key(recipe.intent, step)
    with ObservationStore(tmp_path / "kb.sqlite") as store:
        persist_step(recipe.intent, step, APP.app_id, store)
        ids = {o.automation_id for o in store.observations_for(key, APP.app_id)}
    assert ids == {"9999", "1001"}
