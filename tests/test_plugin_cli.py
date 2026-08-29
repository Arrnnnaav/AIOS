from __future__ import annotations

from ghostcursor.plugins import cli


def test_list_reports_effective_compatibility_state(monkeypatch, capsys):
    class Store:
        def list_installed(self):
            return ()

    monkeypatch.setattr(cli, "_store", lambda developer: Store())
    assert cli.main(["list"]) == 0
    assert "GhostCursor plugins" in capsys.readouterr().out


def test_developer_store_is_visibly_marked(monkeypatch, capsys):
    class Store:
        def list_installed(self):
            return ()

    monkeypatch.setattr(cli, "_store", lambda developer: Store())
    assert cli.main(["--developer", "list"]) == 0
    assert "DEVELOPER STORE" in capsys.readouterr().out
