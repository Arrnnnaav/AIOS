"""Recurring-use learning (D186): Orbyn notices when you keep doing the same
thing and offers to save it, the "learns your workflow and proactively
automates" idea that Attention Engineering is built around -- done locally and
without surveillance.

Only the NORMALISED task text is counted, in memory, for this session. Nothing
is written to disk, timed, or sent anywhere: a persistent log of everything a
person does is exactly the thing a privacy-first guide must not keep (rule 6).
When a task recurs, Orbyn says once how to save it (as a skill, or a crew for a
multi-step goal). The user still chooses to save; nothing is saved automatically.
"""

from __future__ import annotations

from collections import Counter

#: Offer to save on the Nth repeat -- timely, not naggy, and only once (the
#: offer fires exactly when the count reaches this, never again after).
SUGGEST_AT = 2


def _norm(text: str) -> str:
    return " ".join(str(text).split()).casefold()


class Usage:
    """A session tally of normalised task text, newest counts only."""

    def __init__(self, suggest_at: int = SUGGEST_AT) -> None:
        self._counts: Counter[str] = Counter()
        self._suggest_at = suggest_at

    def record(self, text: str) -> int:
        """Count a task; return how many times it's been seen this session."""

        key = _norm(text)
        if not key:
            return 0
        self._counts[key] += 1
        return self._counts[key]

    def nudge(self, text: str, *, kind: str = "skill") -> str | None:
        """Record the task and, exactly when it reaches the repeat threshold,
        return a one-line offer to save it; otherwise None. ``kind`` picks the
        wording: 'skill' (a single task) or 'crew' (a multi-step goal)."""

        count = self.record(text)
        if count != self._suggest_at:
            return None
        clean = " ".join(str(text).split())
        if kind == "crew":
            return (
                f"\N{ELECTRIC LIGHT BULB} You've run this {count}x this session -- save it: "
                f'/crew save <name> "{clean}"'
            )
        return (
            f"\N{ELECTRIC LIGHT BULB} You've done this {count}x this session -- save it as a "
            f'reusable skill: /skill from "{clean}"'
        )


if __name__ == "__main__":  # ponytail: threshold fires once, blanks ignored
    u = Usage(suggest_at=2)
    assert u.nudge("open the report") is None  # 1st time: quiet
    assert "skill from" in u.nudge("Open the  report")  # 2nd (normalised): offer
    assert u.nudge("open the report") is None  # 3rd: silent again, no nagging
    assert u.record("") == 0 and u.nudge("   ") is None  # blanks ignored
    assert "crew save" in Usage(suggest_at=1).nudge("build a pitch", kind="crew")
    print("usage ok")
