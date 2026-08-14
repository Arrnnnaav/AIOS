
from ghostcursor.memory.store import ObservationStore, default_db_path
from ghostcursor.reasoning.schema import ConfirmedObservation


def _obs(version="1.0.0", automation_id="1001", locales=("en-US",), ctype="Button"):
    return ConfirmedObservation(
        app_version=version,
        locales_observed=list(locales),
        automation_id=automation_id,
        control_type=ctype,
        last_seen_at="2026-08-14T00:00:00+00:00",
    )


def test_default_path_is_under_localappdata(monkeypatch):
    monkeypatch.delenv("GHOSTCURSOR_KB_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\someone\AppData\Local")
    path = default_db_path()
    assert path.name == "kb.sqlite"
    assert "GhostCursor" in str(path)
    assert "AppData" in str(path)


def test_env_var_overrides_the_default_path(monkeypatch, tmp_path):
    target = tmp_path / "custom.sqlite"
    monkeypatch.setenv("GHOSTCURSOR_KB_PATH", str(target))
    assert default_db_path() == target


def test_records_survive_closing_and_reopening(tmp_path):
    path = tmp_path / "kb.sqlite"
    with ObservationStore(path) as store:
        store.record("stepkey1", "notepad.exe", _obs())
    with ObservationStore(path) as store:
        loaded = store.observations_for("stepkey1", "notepad.exe")
    assert len(loaded) == 1
    assert loaded[0].automation_id == "1001"
    assert loaded[0].app_version == "1.0.0"
    assert loaded[0].control_type == "Button"
    assert loaded[0].locales_observed == ["en-US"]


def test_recording_the_same_observation_twice_does_not_duplicate(tmp_path):
    with ObservationStore(tmp_path / "kb.sqlite") as store:
        store.record("k", "app.exe", _obs())
        store.record("k", "app.exe", _obs())
        assert len(store.observations_for("k", "app.exe")) == 1


def test_reobserving_merges_locales(tmp_path):
    with ObservationStore(tmp_path / "kb.sqlite") as store:
        store.record("k", "app.exe", _obs(locales=("en-US",)))
        store.record("k", "app.exe", _obs(locales=("hi-IN",)))
        loaded = store.observations_for("k", "app.exe")
    assert len(loaded) == 1
    assert sorted(loaded[0].locales_observed) == ["en-US", "hi-IN"]


def test_different_versions_are_separate_observations(tmp_path):
    with ObservationStore(tmp_path / "kb.sqlite") as store:
        store.record("k", "app.exe", _obs(version="1.0.0"))
        store.record("k", "app.exe", _obs(version="2.0.0"))
        assert len({o.app_version for o in store.observations_for("k", "app.exe")}) == 2


def test_observations_are_scoped_by_step_and_app(tmp_path):
    with ObservationStore(tmp_path / "kb.sqlite") as store:
        store.record("k1", "app.exe", _obs(automation_id="1001"))
        store.record("k2", "app.exe", _obs(automation_id="2002"))
        store.record("k1", "other.exe", _obs(automation_id="3003"))
        assert [o.automation_id for o in store.observations_for("k1", "app.exe")] == [
            "1001"
        ]


def test_unknown_step_returns_nothing(tmp_path):
    with ObservationStore(tmp_path / "kb.sqlite") as store:
        assert store.observations_for("nope", "app.exe") == []


def test_forget_all_erases_everything(tmp_path):
    with ObservationStore(tmp_path / "kb.sqlite") as store:
        store.record("k", "app.exe", _obs())
        store.forget_all()
        assert store.observations_for("k", "app.exe") == []


def test_store_creates_its_parent_directory(tmp_path):
    nested = tmp_path / "a" / "b" / "kb.sqlite"
    with ObservationStore(nested) as store:
        store.record("k", "app.exe", _obs())
    assert nested.exists()
