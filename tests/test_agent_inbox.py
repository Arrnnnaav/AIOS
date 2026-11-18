"""Goals other agents suggest: capped, sealed, taken once, never acted on."""

import pytest

from ghostcursor.workspace import agent_inbox


def test_suggestions_are_capped_deduplicated_and_taken_once(tmp_path):
    path = tmp_path / "goals.sealed"
    ids = [agent_inbox.suggest(f"goal number {i}", "", "agent", path=path) for i in range(agent_inbox.MAX_WAITING)]
    with pytest.raises(ValueError):
        agent_inbox.suggest("one more goal", "", "agent", path=path)
    assert len(agent_inbox.waiting(path=path)) == agent_inbox.MAX_WAITING
    taken = agent_inbox.take(ids[0], path=path)
    assert taken["goal"] == "goal number 0" and agent_inbox.take(ids[0], path=path) is None
    assert len(agent_inbox.waiting(path=path)) == agent_inbox.MAX_WAITING - 1


def test_a_damaged_or_foreign_file_reads_as_nothing_waiting(tmp_path):
    path = tmp_path / "goals.sealed"
    for content in ("not sealed json", "dp1:AAAA", ""):
        path.write_text(content, encoding="ascii")
        assert agent_inbox.waiting(path=path) == []
    assert agent_inbox.waiting(path=tmp_path / "missing") == []
