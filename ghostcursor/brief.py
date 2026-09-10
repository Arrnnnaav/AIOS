"""The conversation a plan is proposed from, stored so it outlives a session.

`idea.txt` was always a stand-in — its own first line says so. What actually
happens is that a person and the model talk about what they want, and later
something has to be built from that talk. This is where the talk lives.

**A brief is content, not authority.** D109-D111: planning context, never
execution authority. The model may read it to decide what is wanted, what is
unclear, and which REGISTERED capabilities to compose. It may not take a
selector, a coordinate, a keystroke, a verification rule, or a capability
from it. Nothing in this module returns anything executable, and a `Brief`
has no field that could carry one — that is the point of it being a closed
type rather than a dict.

**The digest is of the exact bytes.** A proposal binds the brief it was made
from, so "the brief" has to mean one specific byte sequence. Not the parsed
turns, not a normalised form: the bytes, as read.

**It is a separate store from everything else.** Not `sessions.sqlite`, which
must not hold goals or instructions by default; not `kb.sqlite`, which holds
screen-derived observations and is erasable; not the signed plan artifacts,
which are the only things that authorize anything. A conversation is a fourth
kind of thing and gets its own place, local only (D017).

Markdown, because a person has to be able to read it, edit it, and see it in
a diff. A brief someone cannot inspect is a brief they cannot correct.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

#: Who may speak in a brief. Closed on purpose: an open speaker field is a
#: way for a third party to appear in a conversation that only had two.
SPEAKERS = ("user", "assistant")

#: Largest brief that is still planning context. Beyond this it is a corpus,
#: and a corpus needs retrieval rather than a whole-file read.
MAX_BRIEF_BYTES = 1_000_000

#: Largest single turn. Bounded separately so one runaway paste cannot fill
#: the whole budget and evict the conversation around it.
MAX_TURN_BYTES = 100_000

_HEADING = re.compile(r"^## (user|assistant) · (\S+)$")


class BriefError(ValueError):
    """A brief that must not be written, or must not be read as one."""


@dataclass(frozen=True)
class Turn:
    """One thing one party said."""

    speaker: str
    at: str
    text: str


@dataclass(frozen=True)
class Brief:
    """One conversation, as bytes, with the digest a proposal binds.

    Deliberately carries no capability, selector, parameter or plan. A brief
    that could hold one would be a brief that could authorize something, and
    D109-D111 are explicit that it never can.
    """

    source: Path
    text: str
    sha256: str
    turns: tuple[Turn, ...]

    @property
    def is_empty(self) -> bool:
        return not self.turns


def _heading(speaker: str, at: str) -> str:
    return f"## {speaker} · {at}"


def append_turn(
    root: Path, topic: str, speaker: str, text: str, *, at: str | None = None
) -> Path:
    """Add one turn to a topic's brief, creating it if needed.

    Appending is what makes the memory: the file IS the conversation, so
    nothing has to be reconstructed from a session that has ended.
    """

    if speaker not in SPEAKERS:
        raise BriefError(f"speaker must be one of {SPEAKERS}, not {speaker!r}")
    if not isinstance(text, str) or not text.strip():
        raise BriefError("a turn needs text")
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_TURN_BYTES:
        raise BriefError(
            f"a turn of {len(encoded)} bytes exceeds the {MAX_TURN_BYTES} limit"
        )
    for line in text.splitlines():
        if _HEADING.match(line):
            # Otherwise a turn could forge a heading and put words in the
            # other party's mouth when the brief is read back.
            raise BriefError(
                "a turn may not contain a line that looks like a turn heading"
            )

    path = brief_path(root, topic)
    path.parent.mkdir(parents=True, exist_ok=True)
    moment = at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    block = f"{_heading(speaker, moment)}\n\n{text.rstrip()}\n\n"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if not existing:
        block = f"# {topic}\n\n" + block
    # A brief's exact bytes are hashed and bound to every proposal made from
    # it (D113), so newline translation would make the digest depend on the
    # platform that appended the turn.
    path.write_text(existing + block, encoding="utf-8", newline="\n")
    return path


def brief_path(root: Path, topic: str) -> Path:
    """Where a topic's brief lives.

    The topic becomes a filename, so it is bounded by a pattern with no
    character class admitting a separator — escaping the root is not
    something that has to be detected afterwards.
    """

    if not isinstance(topic, str) or not re.fullmatch(
        r"[a-z0-9]+(?:-[a-z0-9]+)*", topic
    ):
        raise BriefError(f"topic {topic!r} is not a valid topic name")
    return Path(root) / f"{topic}.md"


def load_brief(path: Path) -> Brief:
    """Read one brief and digest exactly what was read."""

    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise BriefError(f"no brief at {path}") from exc
    if len(raw) > MAX_BRIEF_BYTES:
        raise BriefError(
            f"a brief of {len(raw)} bytes exceeds the {MAX_BRIEF_BYTES} limit"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BriefError(f"brief at {path} is not valid UTF-8") from exc
    # The digest is of the BYTES, not the decoded or parsed form. A proposal
    # binds the brief it was made from, and that has to mean one specific
    # byte sequence.
    return Brief(
        source=path,
        text=text,
        sha256=hashlib.sha256(raw).hexdigest(),
        turns=parse_turns(text),
    )


def bind_brief(brief: Brief) -> str:
    """Confirm the brief on disk is still the one being bound, and return it.

    A `Brief` is an ordinary frozen value, so its `sha256` field is only as
    trustworthy as whoever built it. Re-reading the source at bind time is
    what makes the digest a fact rather than a claim.

    It also catches the case this is really for: a conversation that was
    APPENDED TO between being read and being proposed from. The brief is a
    living file — that is the whole point of it — so the window between load
    and proposal is real, and a proposal binding a digest that no longer
    describes the file would be bound to nothing.
    """

    if not isinstance(brief, Brief):
        raise BriefError("only a Brief can be bound to a proposal")
    current = load_brief(brief.source)
    if current.sha256 != brief.sha256:
        raise BriefError(
            f"the brief at {brief.source} changed after it was read "
            f"({brief.sha256} -> {current.sha256}); a proposal cannot bind a "
            "digest that no longer describes the file"
        )
    return current.sha256


def parse_turns(text: str) -> tuple[Turn, ...]:
    """The turns in a brief, in order.

    A hand-authored brief with no headings at all parses as zero turns and is
    still a perfectly good brief — `idea.txt` is exactly that. Reading it is
    a whole-text read; the turns are a convenience for a brief that has them.
    """

    turns: list[Turn] = []
    speaker = moment = None
    body: list[str] = []

    def flush() -> None:
        if speaker is not None:
            content = "\n".join(body).strip()
            if content:
                turns.append(Turn(speaker, moment, content))

    for line in text.splitlines():
        match = _HEADING.match(line)
        if match is None:
            body.append(line)
            continue
        flush()
        speaker, moment = match.group(1), match.group(2)
        body = []
    flush()
    return tuple(turns)


__all__ = [
    "MAX_BRIEF_BYTES",
    "MAX_TURN_BYTES",
    "SPEAKERS",
    "Brief",
    "BriefError",
    "Turn",
    "append_turn",
    "bind_brief",
    "brief_path",
    "load_brief",
    "parse_turns",
]
