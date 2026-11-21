"""Read-only calendar (ICS) and mail (IMAP) views: secrets in Credential
Manager, egress policy obeyed, https only, nothing marked read. Hermetic:
fake transports, no network."""

from __future__ import annotations

import datetime as dt
import json

import httpx
import pytest

from ghostcursor import policy
from ghostcursor.workspace import connectors

ICS = "\r\n".join(
    [
        "BEGIN:VCALENDAR",
        "BEGIN:VEVENT",
        "DTSTART:20261105T090000",
        "DTEND:20261105T093000",
        "SUMMARY:Stand-up\\, team",
        "LOCATION:Room 2",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "DTSTART;VALUE=DATE:20261105",
        "SUMMARY:Holiday for some of the",
        "  team",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "DTSTART:20261109T090000",
        "SUMMARY:Next week",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
)
URL = "https://calendar.example.com/private-abc/basic.ics"
NOW = dt.datetime(2026, 11, 5, 12, 0)


@pytest.fixture(autouse=True)
def vault(monkeypatch):
    store = {}
    monkeypatch.setattr(
        connectors.keys, "get_key", lambda name, allow_env=True: store.get(name)
    )
    monkeypatch.setattr(
        connectors.keys, "set_key", lambda name, value: store.__setitem__(name, value)
    )
    monkeypatch.setattr(
        connectors.keys, "delete_key", lambda name: store.pop(name, None)
    )
    monkeypatch.setattr(policy, "allows", lambda provider, images=0: True)
    return store


def _transport(routes):
    def handle(request):
        status, body, headers = routes[str(request.url)]
        return httpx.Response(status, content=body.encode(), headers=headers)

    return httpx.MockTransport(handle)


def test_a_calendar_is_checked_kept_secret_and_shows_today(vault):
    transport = _transport({URL: (200, ICS, {})})
    assert connectors.connect_calendar(URL, transport=transport) == 3
    assert vault["calendar"] == URL and connectors.calendar_connected()
    rows = connectors.agenda(now=NOW, transport=transport)
    assert [r["title"] for r in rows] == [
        "Holiday for some of the team",
        "Stand-up, team",
    ]
    assert rows[0]["all_day"] and rows[1]["location"] == "Room 2"
    assert len(connectors.agenda(days=7, now=NOW, transport=transport)) == 3
    connectors.disconnect_calendar()
    assert not connectors.calendar_connected()


@pytest.mark.parametrize(
    "url, routes, message",
    [
        ("http://calendar.example.com/x.ics", {}, "https://"),
        (URL, {URL: (200, "<html>sign in</html>", {})}, "did not return a calendar"),
        (URL, {URL: (404, "", {})}, "did not return a calendar"),
        (
            URL,
            {URL: (302, "", {"Location": "http://calendar.example.com/x.ics"})},
            "insecure",
        ),
    ],
)
def test_a_bad_calendar_address_is_refused_and_not_kept(vault, url, routes, message):
    with pytest.raises(ValueError, match=message):
        connectors.connect_calendar(url, transport=_transport(routes))
    assert "calendar" not in vault


def test_an_https_redirect_is_followed():
    other = "https://cdn.example.com/cal.ics"
    transport = _transport({URL: (301, "", {"Location": other}), other: (200, ICS, {})})
    assert connectors.connect_calendar(URL, transport=transport) == 3


def test_egress_policy_blocks_the_calendar_and_mail(monkeypatch, vault):
    monkeypatch.setattr(policy, "allows", lambda provider, images=0: False)
    with pytest.raises(ValueError, match="policy"):
        connectors.connect_calendar(URL, transport=_transport({URL: (200, ICS, {})}))
    with pytest.raises(ValueError, match="policy"):
        connectors.connect_mail(
            "imap.example.com", "me@example.com", "pw", imap=FakeImap
        )
    assert vault == {}


class FakeImap:
    instances = []

    def __init__(self, host, port, timeout):
        self.host, self.port, self.calls = host, port, []
        FakeImap.instances.append(self)

    def login(self, user, password):
        if password != "app-password":
            import imaplib

            raise imaplib.IMAP4.error("bad")

    def select(self, box, readonly=False):
        self.calls.append(("select", box, readonly))
        return "OK", [b"2"]

    def search(self, charset, criterion):
        self.calls.append(("search", criterion))
        return "OK", [b"1 2"]

    def fetch(self, mid, spec):
        self.calls.append(("fetch", mid, spec))
        header = (
            b"From: =?utf-8?q?Ana_P=C3=A9rez?= <ana@example.com>\r\nSubject: Invoice "
            + mid
            + b"\r\n\r\n"
        )
        return "OK", [(b"1", header)]

    def logout(self):
        self.calls.append(("logout",))

    def uid(self, command, *args):
        # Message UIDs, as imaplib's IMAP4.uid passes them on.
        self.calls.append(("uid", command))
        if command == "SEARCH":
            return self.search(*args)
        if command == "FETCH":
            return self.fetch(*args)
        raise AssertionError(command)


class FakeImapBodies(FakeImap):
    size = 900

    def fetch(self, mid, spec):
        self.calls.append(("fetch", mid, spec))
        if "HEADER" in spec:
            return super().fetch(mid, spec)
        if "RFC822.SIZE" in spec:
            return "OK", [mid + b" (RFC822.SIZE " + str(self.size).encode() + b")"]
        raw = (
            b"From: ana@example.com\r\nSubject: Invoice " + mid + b"\r\n"
            b"Content-Type: multipart/mixed; boundary=x\r\n\r\n"
            b"--x\r\nContent-Type: text/plain\r\nContent-Disposition: attachment; filename=a.txt\r\n\r\nattached\r\n"
            b"--x\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
            b"Refunds over 500 need a manager.\r\n\r\nPricing exceptions go to Sam.\r\n--x--\r\n"
        )
        return "OK", [(b"1", raw)]


def test_one_picked_message_is_read_as_plain_text_and_never_marked_read(vault):
    FakeImapBodies.instances.clear()
    connectors.connect_mail("imap.example.com", "me@example.com", "app-password", imap=FakeImapBodies)
    subject, text = connectors.message_text("2", "Invoice 2", imap=FakeImapBodies)
    assert subject == "Invoice 2" and "Refunds over 500" in text and "attached" not in text
    calls = FakeImapBodies.instances[-1].calls
    # Only fetches that never set \Seen: a peek, or the size.
    assert ("select", "INBOX", True) in calls
    assert all("PEEK" in c[2] or c[2] == "(RFC822.SIZE)" for c in calls if c[0] == "fetch")
    before = len(FakeImapBodies.instances)
    for bad in ("", "1;2", "x", "1" * 13, None, "1 2"):
        with pytest.raises(ValueError):
            connectors.message_text(bad, "Invoice 2", imap=FakeImapBodies)
    assert len(FakeImapBodies.instances) == before  # refused before any connection
    FakeImapBodies.size = 3_000_000
    try:
        with pytest.raises(ValueError):
            connectors.message_text("2", "Invoice 2", imap=FakeImapBodies)
        assert not any(c[2] == "(BODY.PEEK[])" for c in FakeImapBodies.instances[-1].calls if c[0] == "fetch")
    finally:
        FakeImapBodies.size = 900
    with pytest.raises(ValueError):  # the inbox changed under the list
        connectors.message_text("2", "Invoice 9", imap=FakeImapBodies)


def test_mail_reads_unread_headers_without_marking_anything_read(vault):
    FakeImap.instances.clear()
    connectors.connect_mail(
        " imap.example.com ", "me@example.com", "app-password", imap=FakeImap
    )
    assert json.loads(vault["mail"])["host"] == "imap.example.com"
    rows = connectors.unread(imap=FakeImap)
    assert rows[0] == {"id": "2", "from": "Ana Pérez", "subject": "Invoice 2", "date": ""}
    calls = FakeImap.instances[-1].calls
    assert ("select", "INBOX", True) in calls  # EXAMINE: read-only
    assert all("PEEK" in c[2] for c in calls if c[0] == "fetch")  # never sets \Seen
    # Every search and fetch went by UID: a sequence number can name another message.
    assert ("uid", "SEARCH") in calls and calls.count(("uid", "FETCH")) == len([c for c in calls if c[0] == "fetch"])
    assert calls[-1] == ("logout",)


@pytest.mark.parametrize(
    "host, user, password",
    [
        ("imap.example.com", "me@example.com", "wrong"),
        ("imap.example.com/../x", "me@example.com", "app-password"),
        ("", "me@example.com", "app-password"),
        ("imap.example.com", "", "app-password"),
    ],
)
def test_a_failed_mail_sign_in_keeps_nothing(vault, host, user, password):
    with pytest.raises(ValueError):
        connectors.connect_mail(host, user, password, imap=FakeImap)
    assert "mail" not in vault


def test_nothing_is_read_before_connecting():
    with pytest.raises(ValueError, match="connect"):
        connectors.agenda()
    with pytest.raises(ValueError, match="connect"):
        connectors.unread(imap=FakeImap)


def test_an_inbox_that_will_not_open_read_only_keeps_nothing(vault):
    class NoExamine(FakeImap):
        def select(self, box, readonly=False):
            return "NO", [b"EXAMINE not allowed"]

    with pytest.raises(ValueError, match="inbox"):
        connectors.connect_mail("imap.example.com", "me@example.com", "app-password", imap=NoExamine)
    assert "mail" not in vault


def test_yesterdays_all_day_event_is_not_on_todays_agenda(vault):
    # DTEND is exclusive: an all-day event on the 4th ends at the 5th 00:00.
    ics = ICS.replace(
        "DTSTART;VALUE=DATE:20261105",
        "DTSTART;VALUE=DATE:20261104" + chr(13) + chr(10) + "DTEND;VALUE=DATE:20261105",
    )
    transport = _transport({URL: (200, ics, {})})
    connectors.connect_calendar(URL, transport=transport)
    titles = [r["title"] for r in connectors.agenda(now=NOW, transport=transport)]
    assert titles == ["Stand-up, team"]


def test_a_refused_mailbox_does_not_leave_the_socket_open(vault):
    class Refusing(FakeImap):
        def select(self, box, readonly=False):
            return "NO", [b""]

    with pytest.raises(ValueError):
        connectors.connect_mail(
            "imap.example.com", "me@example.com", "app-password", imap=Refusing
        )
    assert ("logout",) in FakeImap.instances[-1].calls
