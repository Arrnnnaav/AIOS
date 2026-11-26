"""MVP contracts (MVP.md "MVP contracts"): versioned, data-only values.

None of these carries a selector, coordinate, handle, capability or plan
step that could execute: they are context and provenance, never authority.
"""

from __future__ import annotations

import hashlib
import re
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from urllib.parse import urlparse

VERSION = 1


def digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


#: Brief turns that hold a spatial reference start with this; they are screen
#: text, so they are never the (trusted) goal.
POINT_PREFIX = "[pointed at]"


# --- Spatial --------------------------------------------------------------------


@dataclass(frozen=True)
class SpatialContextReference:
    """What the user pointed at, as brief content (D143, D171): the resolved
    control's name, type and application, and how sure the resolver was. No
    rectangle, point, runtime id or handle."""

    mark_kind: str  # "point"
    name: str
    control_type: str
    application: str
    confidence: float
    alternatives: tuple[str, ...] = ()
    version: int = VERSION

    def digest(self) -> str:
        return digest(asdict(self))

    def as_text(self) -> str:
        """Brief text; starts with POINT_PREFIX so it is never read as the goal."""

        alt = (
            f" (also under it: {', '.join(self.alternatives)})"
            if self.alternatives
            else ""
        )
        return (
            f"{POINT_PREFIX} {self.control_type} '{self.name}' in {self.application}, "
            f"confidence {self.confidence:.2f}{alt}"
            + ("" if self.mark_kind == "point" else f" ({self.mark_kind})")
        )


# --- Research -------------------------------------------------------------------


class SourceCategory(str, Enum):
    """A source's kind -- shown as a category, never as a credibility score."""

    PRIMARY_DOCS = "primary documentation"
    GOVERNMENT = "government"
    ACADEMIC = "academic"
    PUBLICATION = "established publication"
    COMMUNITY = "community"
    UNKNOWN = "unknown"


_DOCS = (
    "docs.python.org",
    "developer.mozilla.org",
    "learn.microsoft.com",
    "docs.github.com",
)
_PUBLICATION = (
    "reuters.com",
    "bbc.com",
    "nature.com",
    "britannica.com",
    "wikipedia.org",
    "apnews.com",
    "nytimes.com",
    "theguardian.com",
    "ft.com",
    "wsj.com",
    "bloomberg.com",
    "economist.com",
    "arstechnica.com",
    "theverge.com",
    "techcrunch.com",
    "wired.com",
)
_ACADEMIC = ("arxiv.org", "nih.gov", "acm.org", "ieee.org", "springer.com", "sciencedirect.com", "doi.org")
_GOVERNMENT = ("europa.eu", "who.int", "un.org", "gc.ca")
_COMMUNITY = (
    "stackoverflow.com",
    "stackexchange.com",
    "reddit.com",
    "github.com",
    "medium.com",
    "dev.to",
    "quora.com",
    "substack.com",
    "news.ycombinator.com",
    "hashnode.dev",
)
#: A project's own documentation or release pages on its own site
#: (sqlite.org/docs.html, nodejs.org/en/about/previous-releases).
_DOCS_PATH = re.compile(r"/(docs?|documentation|manual|reference|api|releases?|previous-releases|changelog|release-notes)(?:[/._-]|\.html?$|$)")


def categorize(url: str) -> SourceCategory:
    parts = urlparse(url)
    host = parts.netloc.lower().split(":")[0].removeprefix("www.")

    def under(hosts):
        return any(host == h or host.endswith("." + h) for h in hosts)

    if under(_DOCS) or host.startswith(("docs.", "developer.", "developers.")):
        return SourceCategory.PRIMARY_DOCS
    if under(_ACADEMIC) or host.endswith(".edu") or ".edu." in host or ".ac." in host:
        return SourceCategory.ACADEMIC
    if under(_GOVERNMENT) or host.endswith((".gov", ".mil")) or ".gov." in host:
        return SourceCategory.GOVERNMENT
    if under(_PUBLICATION):
        return SourceCategory.PUBLICATION
    if under(_COMMUNITY):
        return SourceCategory.COMMUNITY
    if _DOCS_PATH.search(parts.path.lower()):
        return SourceCategory.PRIMARY_DOCS
    return SourceCategory.UNKNOWN


class ClaimStatus(str, Enum):
    SUPPORTED = "supported"
    PARTIAL = "partially_supported"
    CONTRADICTED = "contradicted"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class Source:
    sid: str  # "s1"
    url: str
    title: str
    category: SourceCategory


@dataclass(frozen=True)
class Passage:
    pid: str  # "p1"
    sid: str
    text: str


@dataclass(frozen=True)
class Claim:
    text: str
    status: ClaimStatus
    evidence: tuple[str, ...]  # passage ids


class CitationError(ValueError):
    """An answer cited something that was not in its context."""


@dataclass(frozen=True)
class EvidenceGraph:
    question: str
    sources: tuple[Source, ...]
    passages: tuple[Passage, ...]
    claims: tuple[Claim, ...] = ()
    version: int = VERSION

    def validate(self) -> None:
        """Every cited id exists and entered the answer context; a supported
        or partial claim cites at least one passage. The model cannot invent a
        source id (MVP.md "Research and source rules")."""

        sids = {s.sid for s in self.sources}
        pids = {p.pid for p in self.passages}
        if any(p.sid not in sids for p in self.passages):
            raise CitationError("a passage belongs to no source")
        for claim in self.claims:
            unknown = set(claim.evidence) - pids
            if unknown:
                raise CitationError(f"claim cites unknown passages {sorted(unknown)}")
            if (
                claim.status in (ClaimStatus.SUPPORTED, ClaimStatus.PARTIAL)
                and not claim.evidence
            ):
                raise CitationError("a supported claim cites no passage")

    def source_of(self, pid: str) -> Source | None:
        sid = next((p.sid for p in self.passages if p.pid == pid), None)
        return next((s for s in self.sources if s.sid == sid), None)

    def digest(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class ResearchTrace:
    """Question -> answer path. Local only; no secrets, keys or image bytes.
    Holds digests of question and context, not their text."""

    question_sha256: str
    context_sha256: str
    queries: int
    search_provider: str
    source_urls: tuple[str, ...]
    passage_ids: tuple[str, ...]
    claims: int
    unresolved: int
    model_provider: str
    privacy: str  # e.g. "question sent to tavily; passages sent to nvidia"
    timings_ms: dict = field(default_factory=dict)
    failures: tuple[str, ...] = ()
    version: int = VERSION

    def as_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


# --- Plan -----------------------------------------------------------------------


@dataclass(frozen=True)
class PlanProposal:
    """A plan the user reads and may edit (MVP.md "MVP contracts"). Records
    the digest of the brief bytes it was made from; any edit is a new revision with a
    new digest. Advice for Teach, never authority: nothing here can execute."""

    plan: object  # providers.TeachPlan
    brief_sha256: str
    revision: int
    version: int = VERSION

    def digest(self) -> str:
        return digest(asdict(self))

    def as_text(self) -> str:
        lines = [
            f"{n}. {s.describe()}" for n, s in enumerate(self.plan.steps, start=1)
        ]
        return (
            f"[plan r{self.revision}, a proposal {self.digest()[:12]}]\n"
            + "\n".join(lines)
        )
