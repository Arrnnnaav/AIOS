"""One "run" of the system, for the cross-process persistence proof.

Opens the synthetic app, hydrates from the shared store, grounds one step,
persists what it learned, and prints a JSON line describing what happened.
Draws no overlay: this proves persistence, and the overlay is covered by the
pixel harnesses.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ghostcursor.memory.store import ObservationStore
from ghostcursor.perception.appinfo import app_info_for_window
from ghostcursor.reasoning import grounding
from ghostcursor.reasoning.schema import (
    ClaimedDescriptor,
    Recipe,
    Risk,
    Step,
    TargetDescriptor,
    UserAction,
    VerificationKind,
    VerificationRule,
)
from ghostcursor.run import hydrate_recipe, persist_step
from tests.uia_app import SyntheticApp


def build_recipe() -> Recipe:
    return Recipe(
        app_id="synthetic",
        intent="export a file",
        steps=[
            Step(
                user_action=UserAction.CLICK,
                target_descriptor=TargetDescriptor(
                    claimed=ClaimedDescriptor(
                        name="Export", visual_description="left column"
                    )
                ),
                instruction_text="Click Export.",
                verification_rule=VerificationRule(kind=VerificationKind.USER_CONFIRMS),
                risk=Risk.NORMAL,
            )
        ],
    )


def main() -> int:
    recipe = build_recipe()
    step = recipe.steps[0]

    with SyntheticApp() as app:
        title_re = f".*{app.title}.*"
        info = app_info_for_window(title_re)
        app_id = info.app_id if info else "unknown.exe"
        app_version = info.version if info else "unknown"

        with ObservationStore() as store:  # path comes from GHOSTCURSOR_KB_PATH
            hydrated = hydrate_recipe(recipe, app_id, store)
            grounded = grounding.ground(step, title_re, app_version=app_version)
            if grounded is not None:
                grounding.promote(
                    step, grounded, app_version=app_version, locale="en-US"
                )
                persist_step(recipe.intent, step, app_id, store)

    print(
        json.dumps(
            {
                "hydrated": hydrated,
                "grounded": grounded is not None,
                "rung": grounded.rung if grounded else None,
                "automation_id": grounded.automation_id if grounded else None,
                "app_version": app_version,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
