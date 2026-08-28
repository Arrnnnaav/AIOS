"""Current production-run seams.

The former v1 tour and per-application walker tests were migrated to the
compiled perception and workflow suites; this file retains the small public
input-policy checks that remain applicable after cutover.
"""
from ghostcursor.run import should_poll_space


def test_should_poll_space_false_when_there_is_no_current_step():
    assert should_poll_space(None) is False
