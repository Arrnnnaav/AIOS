"""Developer-only instruments. Never imported by production code paths.

Nothing here may be reachable from the production argument parser, from
planning, or from Ask. These modules exist so a human can exercise candidate
bytes BEFORE those bytes gain any authority; they are acceptance instruments,
never a second authority path.

`tests/test_no_input_synthesis.py` scans this package under the same D006 rule
as the rest of `ghostcursor/`, and `tests/test_candidate_acceptance.py` asserts
the unreachability directly rather than trusting convention.
"""
