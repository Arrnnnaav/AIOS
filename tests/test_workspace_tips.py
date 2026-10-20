"""Discoverability tips (D186): pure, local, every tip points at a real command."""

from __future__ import annotations

import random

from ghostcursor.workspace import tips


def test_tip_returns_a_nonempty_tip():
    assert tips.tip().strip()
    # deterministic with a seeded Random
    assert tips.tip(random.Random(1)) in tips.TIPS


def test_every_tip_mentions_a_command_or_action():
    for t in tips.TIPS:
        assert t.strip() and ("/" in t or "ESC" in t), t
