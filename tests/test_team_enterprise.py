"""D187: owner sets up once, staff use it; what happened is recorded.

Pinned: the new policies only lower what Orbyn may do (allow-lists fail
closed, DisableAct stops both Act paths, the company gateway is https-only
and answers first); the audit log is append-only, hash-chained, content-free
and never raises; a team bundle loads only when the pinned owner key signed
it, never older than the last one, and replaces the team scope exactly.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import httpx
import pytest

from ghostcursor import audit, policy, settings
from ghostcursor.harness import act as act_mod
from ghostcursor.harness import binding, teach_live
from ghostcursor.providers import TeachPlan
from ghostcursor.providers.gateway import Gateway
from ghostcursor.providers.schemas import ExpectedChange, PlanStep
from ghostcursor.workspace import task_skills, team
from ghostcursor.workspace.knowledge import Knowledge
from tests.test_providers import _envelope


def _policy(monkeypatch, **values):
    monkeypatch.setattr(policy, "_value", lambda name: values.get(name))


# --- policy -------------------------------------------------------------


def test_allow_lists_are_off_by_default_and_fail_closed(monkeypatch):
    _policy(monkeypatch)
    assert policy.allowed_apps() is None and policy.allowed_providers() is None
    assert not binding.denied("notepad.exe") and policy.allows("chatgpt")
    _policy(monkeypatch, AllowedApps=r"C:\Office\EXCEL.EXE; powerpnt.exe")
    assert not binding.denied("excel.exe") and binding.denied("notepad.exe")
    _policy(monkeypatch, AllowedApps=7)  # present but not text: nothing allowed
    assert binding.denied("excel.exe")
    _policy(monkeypatch, AllowedProviders="company;ollama")
    assert policy.allows("company") and policy.allows("ollama")
    assert not policy.allows("chatgpt") and not policy.allows("jev")


@pytest.mark.parametrize(
    "raw, off", [(None, False), (0, False), (1, True), ("x", True)]
)
def test_disable_act_fails_safe(monkeypatch, raw, off):
    _policy(monkeypatch, DisableAct=raw)
    assert policy.act_disabled() is off


def test_disable_act_stops_the_harness_before_any_input(monkeypatch):
    _policy(monkeypatch, DisableAct=1)
    sent = []
    step = SimpleNamespace(action="click", text="")
    target = SimpleNamespace(rect=(0, 0, 10, 10), name="Save", control_type="Button")
    with pytest.raises(PermissionError, match="guide, not act"):
        act_mod.perform(
            step, target, click=lambda x, y: sent.append((x, y)), send=sent.append
        )
    assert sent == []


@pytest.mark.parametrize(
    "url, kept",
    [
        ("https://ai.example.com/v1/", "https://ai.example.com/v1"),
        ("http://localhost:4000/v1", "http://localhost:4000/v1"),
        ("http://ai.example.com/v1", None),
        ("", None),
    ],
)
def test_company_endpoint_is_https_or_this_machine(monkeypatch, url, kept):
    _policy(monkeypatch, CompanyEndpoint=url)
    assert policy.company_endpoint() == kept


def _plan_reply(request):
    body = {
        "steps": [
            {"instruction": "Click Save", "expected_change": "chosen_state_changes"}
        ]
    }
    return httpx.Response(
        200, json={"choices": [{"message": {"content": json.dumps(body)}}]}
    )


def test_the_company_gateway_answers_first_without_a_personal_key(
    monkeypatch, tmp_path
):
    _policy(
        monkeypatch, CompanyEndpoint="https://ai.example.com/v1", CompanyModel="house"
    )
    settings.set_company_gateway(True)  # the person opted in
    seen = []

    def handler(request):
        seen.append((str(request.url), json.loads(request.content)["model"]))
        return _plan_reply(request)

    gateway = Gateway(
        transport=httpx.MockTransport(handler),
        key_lookup=lambda name: None,
        log_path=tmp_path / "log.jsonl",
    )
    assert gateway.available()["company"]
    gateway.plan(_envelope())
    assert seen == [("https://ai.example.com/v1/chat/completions", "house")]
    assert gateway.last_provider == "company"


def test_without_the_policy_there_is_no_company_provider(monkeypatch, tmp_path):
    _policy(monkeypatch)
    gateway = Gateway(key_lookup=lambda name: None, log_path=tmp_path / "l.jsonl")
    assert gateway.available()["company"] is False


# --- audit --------------------------------------------------------------


def test_the_audit_chain_detects_an_edited_or_removed_line(tmp_path):
    path = tmp_path / "audit.jsonl"
    assert audit.record(
        "plan_approved", path=path, steps=3, app=r"C:\Program Files\X\EXCEL.EXE"
    )
    assert audit.record("act_step", path=path, action="click", outcome="done")
    assert audit.record("act_step", path=path, action="type", outcome="refused")
    assert audit.verify(path) == (True, 3, None)
    audit.flush()
    first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert first["app"] == "EXCEL.EXE"  # a name, never a path
    lines = path.read_bytes().splitlines()
    path.write_bytes(
        lines[0].replace(b'"steps": 3', b'"steps": 1')
        + b"\n"
        + b"\n".join(lines[1:])
        + b"\n"
    )
    assert audit.verify(path) == (False, 3, 2)
    path.write_bytes(b"\n".join([lines[0], lines[2]]) + b"\n")
    assert audit.verify(path)[0] is False


def test_the_audit_refuses_content_and_never_raises(tmp_path):
    path = tmp_path / "audit.jsonl"
    assert not audit.record("act_step", path=path, goal="pay the invoice")
    assert not audit.record("screen_text", path=path)
    assert not audit.record("act_step", path=path, outcome=["a", "list"])
    assert not path.exists()
    blocked = tmp_path / "file"
    blocked.write_text("x")
    before = audit.dropped
    assert audit.record("act_step", path=blocked / "audit.jsonl", outcome="done")
    assert audit.flush() and audit.dropped == before + 1  # counted, never raised


def test_a_harness_step_is_audited_with_its_outcome(monkeypatch):
    monkeypatch.setattr(
        binding, "identify", lambda hwnd: binding.Identity(1, "excel.exe", "16")
    )
    step = SimpleNamespace(action="click", text="")
    target = SimpleNamespace(rect=(0, 0, 10, 10), name="Total", control_type="Edit")
    monkeypatch.setattr(act_mod, "perform", lambda *a, **k: "clicked Total")
    teach_live._live_perform(step, target, 5)

    def refuse(*a, **k):
        raise PermissionError("covered")

    monkeypatch.setattr(act_mod, "perform", refuse)
    with pytest.raises(PermissionError):
        teach_live._live_perform(step, target, 5)
    audit.flush()
    rows = [json.loads(line) for line in audit.default_path().read_text().splitlines()]
    assert [(r["event"], r["outcome"], r["app"], r["control_type"]) for r in rows] == [
        ("act_step", "done", "excel.exe", "Edit"),
        ("act_step", "refused", "excel.exe", "Edit"),
    ]
    assert "Total" not in audit.default_path().read_text()  # no control names


def test_egress_is_audited_without_content(monkeypatch, tmp_path):
    _policy(monkeypatch, CompanyEndpoint="https://ai.example.com/v1")
    settings.set_company_gateway(True)
    gateway = Gateway(
        transport=httpx.MockTransport(_plan_reply),
        key_lookup=lambda n: None,
        log_path=tmp_path / "l",
    )
    gateway.plan(_envelope())
    audit.flush()
    text = audit.default_path().read_text()
    assert '"event": "egress"' in text and '"provider": "company"' in text
    assert "Save" not in text


# --- team ---------------------------------------------------------------


@pytest.fixture
def owner(monkeypatch, tmp_path):
    store = {}
    monkeypatch.setattr(team.keys, "get_key", lambda name, **kw: store.get(name))
    monkeypatch.setattr(
        team.keys, "set_key", lambda name, value: store.__setitem__(name, value)
    )
    public = team.init_owner(key_lookup=store.get, key_store=store.__setitem__)
    folder = tmp_path / "share"
    _policy(monkeypatch, TeamFolder=str(folder), TeamOwnerKey=public)
    return SimpleNamespace(store=store, public=public, folder=folder)


def _brain(tmp_path, name, *facts):
    k = Knowledge(tmp_path / f"{name}.sqlite")
    for text in facts:
        k.approve(k.add_candidate(text, source="owner", scope="default").fid)
    return k


def _plan():
    return TeachPlan(
        (PlanStep("Click New invoice", ExpectedChange.CHOSEN_STATE_CHANGES),)
    )


def test_roles_come_from_the_pinned_key(owner, monkeypatch):
    assert team.role(key_lookup=owner.store.get) == "owner"
    assert team.role(key_lookup=lambda n: None) == "staff"
    _policy(monkeypatch)
    assert team.role(key_lookup=owner.store.get) == "solo"


def test_publish_then_sync_gives_staff_the_owners_facts_and_skills(owner, tmp_path):
    boss = _brain(
        tmp_path,
        "boss",
        "Invoices go to finance@example.com by Friday",
        "VAT is 20 percent",
    )
    secret = boss.add_candidate(
        "The safe code is 4471",
        source="owner",
        scope="default",
        sensitivity="sensitive",
    )
    boss.approve(secret.fid)
    owner_skills, staff_skills = tmp_path / "os", tmp_path / "ss"
    task_skills.save_skill("new invoice", _plan(), dest_dir=owner_skills)
    counts = team.publish(
        boss, scope="default", skills_dir=owner_skills, key_lookup=owner.store.get
    )
    assert counts == {"facts": 2, "skills": 1, "agents": 0}
    published = (owner.folder / "orbyn" / "team.json").read_text(encoding="utf-8")
    assert (
        "4471" not in published and "finance@example.com" not in published
    )  # scrubbed

    staff = Knowledge(tmp_path / "staff.sqlite")
    assert team.sync(staff, skills_dir=staff_skills)["facts"] == 2
    usable = {f.text for f in staff.list(scope="team") if f.status == "approved"}
    assert "VAT is 20 percent" in usable
    assert task_skills.load_skill("team-new-invoice", dest_dir=staff_skills) == _plan()


def test_staff_cannot_publish(owner, tmp_path):
    with pytest.raises(team.TeamError, match="only the owner"):
        team.publish(
            _brain(tmp_path, "s", "x y z"), scope="default", key_lookup=lambda n: None
        )


def test_a_tampered_or_foreign_bundle_is_refused(owner, tmp_path):
    team.publish(
        _brain(tmp_path, "boss", "VAT is 20 percent"),
        scope="default",
        skills_dir=tmp_path / "e",
        key_lookup=owner.store.get,
    )
    bundle = owner.folder / "orbyn" / "team.json"
    good = bundle.read_bytes()
    bundle.write_bytes(good.replace(b"20 percent", b"0 percent"))
    staff = Knowledge(tmp_path / "staff.sqlite")
    with pytest.raises(team.TeamError, match="not signed"):
        team.sync(staff, skills_dir=tmp_path / "ss")
    bundle.write_bytes(good)
    other = team.Ed25519PrivateKey.generate()
    raw, sig = team.sign(json.loads(good), other)
    (owner.folder / "orbyn" / "team.sig").write_bytes(sig)
    with pytest.raises(team.TeamError, match="not signed"):
        team.sync(staff, skills_dir=tmp_path / "ss")
    assert staff.list(scope="team") == []


def test_an_older_bundle_is_refused_and_removed_facts_retire(owner, tmp_path):
    boss = _brain(tmp_path, "boss", "VAT is 20 percent", "Office closes at six")
    team.publish(
        boss, scope="default", skills_dir=tmp_path / "e", key_lookup=owner.store.get
    )
    old = {
        n: (owner.folder / "orbyn" / n).read_bytes() for n in ("team.json", "team.sig")
    }
    staff = Knowledge(tmp_path / "staff.sqlite")
    team.sync(staff, skills_dir=tmp_path / "ss")
    six = next(f for f in boss.list(scope="default") if "six" in f.text)
    boss.retire(six.fid)
    team.publish(
        boss, scope="default", skills_dir=tmp_path / "e", key_lookup=owner.store.get
    )
    team.sync(staff, skills_dir=tmp_path / "ss")
    live = {f.text for f in staff.list(scope="team") if f.status == "approved"}
    assert live == {"VAT is 20 percent"}
    for name, data in old.items():  # an attacker puts the old signed bundle back
        (owner.folder / "orbyn" / name).write_bytes(data)
    with pytest.raises(team.TeamError, match="older bundle"):
        team.sync(staff, skills_dir=tmp_path / "ss")


def test_audit_is_shared_only_when_policy_says_so(owner, monkeypatch):
    audit.record("act_step", outcome="done")
    assert team.share_audit() is None
    _policy(
        monkeypatch,
        TeamFolder=str(owner.folder),
        TeamOwnerKey=owner.public,
        ShareAudit=1,
    )
    copy = team.share_audit()
    assert copy.parent == owner.folder / "orbyn" / "audit" and audit.verify(copy)[0]


def test_the_group_policy_template_names_every_policy_value():
    import re
    import xml.etree.ElementTree as ET
    from pathlib import Path

    source = Path(policy.__file__).read_text(encoding="utf-8")
    names = set(re.findall(r'_(?:value|names|text)\("([A-Za-z]+)"\)', source))
    admx = Path("tools/policy/Orbyn.admx").read_text(encoding="utf-8")
    adml = ET.parse("tools/policy/en-US/Orbyn.adml").getroot()
    strings = {e.get("id") for e in adml.iter() if e.tag.endswith("string")}
    assert names and names == set(re.findall(r'valueName="([A-Za-z]+)"', admx))
    assert set(re.findall(r"\$\(string\.([A-Za-z0-9_]+)\)", admx)) <= strings


@pytest.mark.parametrize(
    "url",
    ["http://localhost.evil.example/v1", "http://127.0.0.1.evil.example", "https://"],
)
def test_a_lookalike_local_endpoint_is_refused(monkeypatch, url):
    _policy(monkeypatch, CompanyEndpoint=url)
    assert policy.company_endpoint() is None


def test_teach_does_not_ask_to_approve_act_that_policy_disables(monkeypatch):
    from ghostcursor.harness.teach import ModelTeachSession, Phase
    from tests.test_harness_teach import SyncSlot, _frame

    _policy(monkeypatch, DisableAct=1)
    session = ModelTeachSession(
        "g", None, SyncSlot(), plan=_plan(), act=lambda s, t: "x"
    )
    shown = session.tick(_frame())
    assert session.phase is Phase.BLOCKED and "guide, not act" in shown.message
    assert not audit.default_path().exists()  # no plan_approved recorded


def test_published_skills_are_scrubbed(owner, tmp_path):
    plan = TeachPlan(
        (
            PlanStep(
                "Type the key",
                ExpectedChange.CHOSEN_STATE_CHANGES,
                action="type",
                text="mail ann@example.com",
            ),
        )
    )
    task_skills.save_skill("send", plan, dest_dir=tmp_path / "os")
    team.publish(
        _brain(tmp_path, "b", "x y z"),
        scope="default",
        skills_dir=tmp_path / "os",
        key_lookup=owner.store.get,
    )
    assert "ann@example.com" not in (owner.folder / "orbyn" / "team.json").read_text(
        encoding="utf-8"
    )


def test_a_garbage_sequence_in_the_folder_does_not_break_publish(owner, tmp_path):
    folder = owner.folder / "orbyn"
    folder.mkdir(parents=True)
    (folder / "team.json").write_text('{"sequence": [1]}', encoding="utf-8")
    team.publish(
        _brain(tmp_path, "b", "x y z"),
        scope="default",
        skills_dir=tmp_path / "e",
        key_lookup=owner.store.get,
    )
    assert (
        json.loads((folder / "team.json").read_text(encoding="utf-8"))["sequence"] == 1
    )


def test_it_policy_alone_never_sends_to_the_company_gateway(monkeypatch, tmp_path):
    _policy(monkeypatch, CompanyEndpoint="https://ai.example.com/v1")
    calls = []
    gateway = Gateway(
        transport=httpx.MockTransport(lambda r: calls.append(r) or _plan_reply(r)),
        key_lookup=lambda name: None,
        log_path=tmp_path / "l",
        system_two=("company",),
    )
    assert gateway.available()["company"] is False
    with pytest.raises(Exception):
        gateway.plan(_envelope())
    assert calls == []
    settings.set_company_gateway(True)
    assert gateway.available()["company"] is True
    _policy(monkeypatch)  # IT removed the endpoint: the opt-in alone adds nothing
    assert settings.company_gateway() is False


def test_audit_writes_never_wait_on_the_caller_and_two_writers_keep_the_chain(tmp_path):
    import threading

    path = tmp_path / "audit.jsonl"
    writers = [
        threading.Thread(
            target=lambda: [
                audit._write(path, {"event": "act_step", "outcome": "done"})
                for _ in range(25)
            ]
        )
        for _ in range(2)
    ]  # _write directly: the same path from two threads, as two processes would
    for w in writers:
        w.start()
    for w in writers:
        w.join()
    assert audit.verify(path) == (True, 50, None)


def test_the_owner_report_counts_each_pc_and_flags_a_broken_chain(tmp_path):
    folder = tmp_path / "audit"
    good, bad = folder / "pc1.jsonl", folder / "pc2.jsonl"
    for fields in ({"steps": 2}, {"outcome": "done"}, {"outcome": "refused"}):
        event = "plan_approved" if "steps" in fields else "act_step"
        audit._write(good, {"at": 5.0, "user": "ann", "event": event, **fields})
    audit._write(
        bad, {"at": 1.0, "user": "bob", "event": "egress", "provider": "company"}
    )
    audit._write(
        bad, {"at": 2.0, "user": "bob", "event": "egress", "provider": "company"}
    )
    lines = bad.read_bytes().splitlines()
    bad.write_bytes(lines[1] + b"\n")  # someone deleted the first line
    one, two = team.report(folder)
    assert (
        one["users"],
        one["approvals"],
        one["done"],
        one["refused"],
        one["intact"],
    ) == (["ann"], 1, 1, 1, True)
    assert (two["requests"], two["intact"], two["broken_at"]) == (1, False, 1)


def test_syncing_the_same_bundle_twice_is_harmless(owner, tmp_path):
    team.publish(
        _brain(tmp_path, "boss", "VAT is 20 percent"),
        scope="default",
        skills_dir=tmp_path / "e",
        key_lookup=owner.store.get,
    )
    staff = Knowledge(tmp_path / "staff.sqlite")
    first = team.sync(staff, skills_dir=tmp_path / "ss")
    assert team.sync(staff, skills_dir=tmp_path / "ss") == first
    assert [f.text for f in staff.list(scope="team") if f.status == "approved"] == [
        "VAT is 20 percent"
    ]


def test_browser_input_obeys_disable_act_and_the_app_lists(monkeypatch):
    from ghostcursor.harness.browser import Page, PageControl

    page = object.__new__(Page)  # no tab needed: the guard runs before CDP
    control = PageControl("button", "Submit", 7, None)
    _policy(monkeypatch, DisableAct=1)
    with pytest.raises(PermissionError, match="guide, not act"):
        page._guard(control, True, ())
    _policy(monkeypatch, AllowedApps="excel.exe")
    with pytest.raises(PermissionError, match="in the browser"):
        page._guard(control, True, ())
    _policy(monkeypatch, AllowedApps="msedge.exe")
    page._guard(control, True, ())  # allowed: no error
    page.executable = "chrome.exe"  # opened by Browser.launch: its own browser counts
    with pytest.raises(PermissionError, match="in the browser"):
        page._guard(control, True, ())


def test_a_harness_act_run_lands_in_the_one_audit_log():
    bindings = [SimpleNamespace(identity=SimpleNamespace(executable="excel.exe"))]
    teach_live._audit(bindings, [(1, "you confirmed"), (2, "observed change")], 0)
    audit.flush()
    row = json.loads(audit.default_path().read_text().splitlines()[-1])
    assert (row["event"], row["app"], row["completed"], row["code"]) == (
        "act_run",
        "excel.exe",
        2,
        "0",
    )
    assert "confirmed" not in audit.default_path().read_text()


def test_record_returns_while_the_disk_is_stuck(monkeypatch):
    import threading

    stuck = threading.Event()
    monkeypatch.setattr(audit, "_write", lambda path, entry: stuck.wait(5))
    started = time.monotonic()
    assert audit.record("act_step", outcome="done")
    assert time.monotonic() - started < 0.1  # the caller never waits on the disk
    stuck.set()
    assert audit.flush()


def test_a_full_queue_is_counted_not_raised(monkeypatch):
    import queue as queue_mod

    monkeypatch.setattr(audit, "_queue", queue_mod.Queue(maxsize=1))
    monkeypatch.setattr(audit, "_writer", SimpleNamespace(is_alive=lambda: True))
    before = audit.dropped
    assert audit.record("act_step", outcome="done")
    assert audit.record("act_step", outcome="done") is False
    assert audit.dropped == before + 1


def test_the_owner_report_survives_a_corrupt_log(tmp_path):
    folder = tmp_path / "audit"
    folder.mkdir()
    (folder / "pc9.jsonl").write_bytes(
        b'[1, 2]\n{"at": "noon", "event": "egress", "prev": "x"}\n'
    )
    (row,) = team.report(folder)
    assert row["intact"] is False and row["requests"] == 1 and row["last"] is None


def test_publish_is_refused_when_the_organisation_keeps_text_on_this_computer(
    owner, tmp_path, monkeypatch
):
    _policy(monkeypatch, MaxEgress="0")  # as handoff.export: policy only lowers
    with pytest.raises(team.TeamError, match="organisation"):
        team.publish(
            _brain(tmp_path, "boss", "VAT is 20 percent"),
            scope="default",
            skills_dir=tmp_path / "e",
            key_lookup=owner.store.get,
        )
    assert not (owner.folder / "orbyn" / "team.json").exists()
