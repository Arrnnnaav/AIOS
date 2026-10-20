"""A small clipboard history (D186), the Raycast/Alfred staple people miss most.

No background watcher: the console calls ``offer`` with the current clipboard
once per prompt, so history fills as you work without a thread. Text only, and
it never leaves the machine on its own -- ``/clips <n>`` puts an entry back on
the clipboard, ``/clips <n> brain`` files it as a Brain candidate the owner
reviews. In-memory for the session only (a persisted clipboard log is a privacy
liability nobody asked for).
"""

from __future__ import annotations

from collections import deque

MAX_ENTRIES = 25
MAX_CHARS = 2000


class Clips:
    """A bounded, newest-first ring of distinct recent clipboard texts."""

    def __init__(self, maxlen: int = MAX_ENTRIES) -> None:
        self._ring: deque[str] = deque(maxlen=maxlen)

    def offer(self, text: str | None) -> bool:
        """Record ``text`` if it's new, non-blank and not the latest already.
        Returns True when it was added."""

        if not text:
            return False
        text = text.strip()[:MAX_CHARS]
        if not text or (self._ring and self._ring[0] == text):
            return False
        # Move an older duplicate to the front rather than keep two copies.
        if text in self._ring:
            self._ring.remove(text)
        self._ring.appendleft(text)
        return True

    def list(self) -> list[str]:
        return list(self._ring)

    def get(self, n: int) -> str | None:
        """Entry ``n`` (1-based, newest = 1), or None if out of range."""

        return self._ring[n - 1] if 1 <= n <= len(self._ring) else None


def _preview(text: str, width: int = 70) -> str:
    """One-line preview for the console list."""

    one = " ".join(text.split())
    return one if len(one) <= width else one[: width - 1] + "\N{HORIZONTAL ELLIPSIS}"


if __name__ == "__main__":  # ponytail: ring semantics (dedup, order, bounds)
    c = Clips(maxlen=3)
    assert c.offer("one") and c.offer("two")
    assert not c.offer("two")  # same as latest -> ignored
    assert not c.offer("  ")  # blank -> ignored
    assert c.offer("one")  # older dup -> moves to front
    assert c.list() == ["one", "two"]
    c.offer("a"), c.offer("b"), c.offer("c")  # evict past maxlen=3
    assert c.list() == ["c", "b", "a"]
    assert c.get(1) == "c" and c.get(9) is None
    assert _preview("x" * 100).endswith("\N{HORIZONTAL ELLIPSIS}")
    print("clips ok")
