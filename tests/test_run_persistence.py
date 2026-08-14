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
