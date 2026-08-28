"""Regression coverage formerly driven through the deleted v1 tour driver.

These aliases deliberately execute the implementations in the compiled
perception suite, so the old lanes cannot silently reintroduce a second
execution authority.
"""
from tests.test_compiled_perception import (
    test_a_worker_that_never_answers_is_still_caught_after_the_grace,
    test_the_executor_asks_for_tier_two_when_grounding_fails,
    test_compiled_focus_history_rehints_after_a_wrong_control,
    test_each_new_observation_ages_the_staleness_ladder,
    test_a_real_worker_drives_a_real_tour_to_completion,
)
