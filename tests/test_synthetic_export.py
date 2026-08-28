from ghostcursor.reasoning.schema import Recipe, VerificationKind


def test_synthetic_export_recipe_verifies_application_status_change():
    recipe = Recipe.load("tests/fixtures/v1/reasoning/recipes/synthetic_export.json")
    rule = recipe.steps[0].verification_rule
    assert rule.kind is VerificationKind.ELEMENT_APPEARS
    assert rule.args["target_descriptor"]["name"] == "Export finished: table.csv"
    assert recipe.steps[1].verification_rule.kind is VerificationKind.USER_CONFIRMS
    assert recipe.steps[1].target_descriptor.claimed.name == "Export finished: table.csv"
