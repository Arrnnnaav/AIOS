"""Read-only calendar and mail views for Work (HeyClicky ships hosted
connectors; Orbyn talks to the provider directly from this PC).

Calendar: the private iCalendar (ICS) address Outlook.com, Microsoft 365 and
Google publish for a calendar. Mail: IMAP over TLS, opened read-only, headers
peeked so nothing is marked read. Secrets (the ICS address, the IMAP app
password) live in Windows Credential Manager. Like the GitHub view, nothing
here feeds a model or a routine: what is fetched is shown to the user and
kept nowhere. The organisation's egress policy applies ("calendar", "mail").
"""

from __future__ import annotations

import datetime as dt
import email.header
import email.utils
import imaplib
import json
import re

import httpx

from ghostcursor import policy
from ghostcursor.providers import keys

MAX_ICS_BYTES = 5 * 1024 * 1024
MAX_EVENTS = 50
MAX_MAIL = 20
HOST = re.compile(r"[A-Za-z0-9.-]{1,253}\Z")


def _short(text: str, limit: int = 200) -> str:
    return " ".join(str(text).split())[:limit]


# --- calendar -----------------------------------------------------------------


def calendar_connected() -> bool:
    return keys.get_key("calendar", allow_env=False) is not None


def _fetch_ics(url: str, transport=None) -> str:
    if not policy.allows("calendar"):
        raise ValueError("the calendar is blocked by the organisation's egress policy")
    if not url.startswith("https://"):
        raise ValueError("use the calendar's https:// iCalendar (ICS) address")
    try:
        with httpx.Client(
            transport=transport, timeout=10, follow_redirects=False
        ) as client:
            for _ in range(4):  # follow redirects by hand: never to plain http
                response = client.get(url, headers={"User-Agent": "Orbyn"})
                if not response.is_redirect:
                    break
                url = str(response.next_request.url)
                if not url.startswith("https://"):
                    raise ValueError("the calendar redirected to an insecure address")
    except httpx.HTTPError:
        raise ValueError("the calendar could not be reached") from None
    if response.status_code != 200 or len(response.content) > MAX_ICS_BYTES:
        raise ValueError("the calendar address did not return a calendar")
    text = response.content.decode("utf-8", errors="replace")
    if "BEGIN:VCALENDAR" not in text:
        raise ValueError("the calendar address did not return a calendar")
    return text


def connect_calendar(url: str, *, transport=None) -> int:
    """Check the ICS address works, then keep it in Credential Manager (it is
    a secret: anyone with it can read the calendar). Returns the event count."""

    url = str(url).strip()
    events = parse_ics(_fetch_ics(url, transport))
    keys.set_key("calendar", url)
    return len(events)


def disconnect_calendar() -> None:
    keys.delete_key("calendar")


def _when(value: str, params: str) -> dt.datetime | None:
    """An ICS DATE or DATE-TIME as a local, naive datetime."""

    try:
        if "VALUE=DATE" in params or len(value) == 8:
            return dt.datetime.strptime(value[:8], "%Y%m%d")
        moment = dt.datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    if value.endswith("Z"):  # UTC -> this PC's local time
        return moment.replace(tzinfo=dt.timezone.utc).astimezone().replace(tzinfo=None)
    return moment  # ponytail: TZID treated as local; map VTIMEZONE if users travel


def _unescape(text: str) -> str:
    return re.sub(
        r"\\([,;\\nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), text
    )


def parse_ics(text: str) -> list[dict]:
    """VEVENTs as {start, end, title, location, all_day}. ponytail: RRULE
    repeats are not expanded (only each series' first date shows); add
    rrule expansion when recurring meetings matter."""

    lines = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:  # RFC 5545 line folding
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    events, current = [], None
    for line in lines:
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT" and current is not None:
            if current.get("start"):
                events.append(current)
            current = None
        elif current is not None and ":" in line:
            head, value = line.split(":", 1)
            name, _, params = head.partition(";")
            if name in ("DTSTART", "DTEND"):
                key = "start" if name == "DTSTART" else "end"
                current[key] = _when(value.strip(), params)
                if key == "start":
                    current["all_day"] = (
                        "VALUE=DATE" in params or len(value.strip()) == 8
                    )
            elif name == "SUMMARY":
                current["title"] = _short(_unescape(value))
            elif name == "LOCATION":
                current["location"] = _short(_unescape(value), 120)
    return events


def agenda(
    *, days: int = 1, now: dt.datetime | None = None, transport=None
) -> list[dict]:
    """Events from the start of today for DAYS days, earliest first."""

    url = keys.get_key("calendar", allow_env=False)
    if not url:
        raise ValueError("connect a calendar first")
    now = now or dt.datetime.now()
    begin = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = begin + dt.timedelta(days=max(1, min(int(days), 14)))
    rows = [
        e
        for e in parse_ics(_fetch_ics(url, transport))
        if e["start"] < end and (e.get("end") or e["start"]) >= begin
    ]
    rows.sort(key=lambda e: e["start"])
    return [
        {
            "start": e["start"].isoformat(timespec="minutes"),
            "all_day": bool(e.get("all_day")),
            "title": e.get("title", "(no title)"),
            "location": e.get("location", ""),
        }
        for e in rows[:MAX_EVENTS]
    ]


# --- mail -----------------------------------------------------------------------


def mail_connected() -> bool:
    return keys.get_key("mail", allow_env=False) is not None


def _open(host: str, user: str, password: str, imap=imaplib.IMAP4_SSL):
    if not policy.allows("mail"):
        raise ValueError("mail is blocked by the organisation's egress policy")
    if not HOST.fullmatch(host or "") or not user or not password:
        raise ValueError("enter the IMAP server, your address and an app password")
    try:
        client = imap(host, 993, timeout=10)
        client.login(user, password)
        status, _ = client.select("INBOX", readonly=True)  # EXAMINE: changes nothing
    except (OSError, imaplib.IMAP4.error):
        raise ValueError("the mail server refused the sign-in") from None
    if status != "OK":
        raise ValueError("the inbox could not be opened")
    return client


def connect_mail(
    host: str, user: str, password: str, *, imap=imaplib.IMAP4_SSL
) -> None:
    host, user = str(host).strip(), str(user).strip()
    client = _open(host, user, password, imap)
    client.logout()
    keys.set_key("mail", json.dumps({"host": host, "user": user, "password": password}))


def disconnect_mail() -> None:
    keys.delete_key("mail")


def _header(value) -> str:
    try:
        return _short(
            str(email.header.make_header(email.header.decode_header(value or "")))
        )
    except Exception:
        return _short(value or "")


def unread(*, limit: int = 10, imap=imaplib.IMAP4_SSL) -> list[dict]:
    """The newest unread messages' sender, subject and date. Headers only,
    peeked (nothing is marked read); bodies are never fetched."""

    saved = keys.get_key("mail", allow_env=False)
    if not saved:
        raise ValueError("connect mail first")
    account = json.loads(saved)
    client = _open(account["host"], account["user"], account["password"], imap)
    try:
        # UIDs, not sequence numbers: a UID names one message for good.
        status, found = client.uid("SEARCH", None, "UNSEEN")
        ids = found[0].split() if status == "OK" and found and found[0] else []
        rows = []
        for mid in reversed(ids[-max(1, min(int(limit), MAX_MAIL)) :]):
            status, data = client.uid(
                "FETCH",
                mid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
            )
            if status != "OK" or not data or not isinstance(data[0], tuple):
                continue
            message = email.message_from_bytes(data[0][1])
            name, address = email.utils.parseaddr(_header(message.get("From")))
            rows.append(
                {
                    "id": mid.decode("ascii", "replace"),
                    "from": name or address,
                    "subject": _header(message.get("Subject")) or "(no subject)",
                    "date": _short(message.get("Date", ""), 40),
                }
            )
        return rows
    finally:
        try:
            client.logout()
        except Exception:
            pass


MAX_MAIL_CHARS = 100_000
MAX_MAIL_BYTES = 2_000_000


def message_text(mid: str, subject: str, *, imap=imaplib.IMAP4_SSL) -> tuple[str, str]:
    """(subject, plain text) of ONE message the person picked from the
    unread list, for them to add to the Company Brain. Peeked (nothing is
    marked read), plain-text part only, capped. ``subject`` is the one the
    list showed: a different message at that number (the inbox changed)
    is refused rather than added."""

    if not isinstance(mid, str) or not mid.isdigit() or len(mid) > 12:
        raise ValueError("choose a message from the unread list")
    saved = keys.get_key("mail", allow_env=False)
    if not saved:
        raise ValueError("connect mail first")
    account = json.loads(saved)
    client = _open(account["host"], account["user"], account["password"], imap)
    try:
        # Size first: a huge message (attachments) is refused, not downloaded.
        status, sized = client.uid("FETCH", mid.encode("ascii"), "(RFC822.SIZE)")
        size = re.search(rb"RFC822\.SIZE (\d+)", sized[0] if sized and isinstance(sized[0], bytes) else b"")
        if status != "OK" or size is None or int(size.group(1)) > MAX_MAIL_BYTES:
            raise ValueError("that message is too large to add (over 2 MB)")
        status, data = client.uid("FETCH", mid.encode("ascii"), "(BODY.PEEK[])")
        if status != "OK" or not data or not isinstance(data[0], tuple):
            raise ValueError("that message could not be read")
        message = email.message_from_bytes(data[0][1])
    finally:
        try:
            client.logout()
        except Exception:
            pass
    found = _header(message.get("Subject")) or "(no subject)"
    if found != subject:
        raise ValueError("the inbox changed; show unread mail again")
    parts = message.walk() if message.is_multipart() else [message]
    text = ""
    for part in parts:
        if part.get_content_type() == "text/plain" and not part.get_filename():
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", "replace")
            break
    text = text.replace("\0", " ")[:MAX_MAIL_CHARS]
    if not text.strip():
        raise ValueError("that message has no plain text to add")
    return found, text
