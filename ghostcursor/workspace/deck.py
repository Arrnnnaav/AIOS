"""Plan a presentation from a goal (D186): "build me a deck about X" -> a
reviewable DeckSpec (an outline of slides, each with a content-typed layout).

This is Orbyn's planner form of what Gamma / Beautiful.ai do (outline first,
then a layout per slide); it is grounded, when a Company Brain is present, in
the owner's own reviewed facts rather than invented content. The spec is DATA:
the owner reviews it, and the existing Act-on-PowerPoint path builds it with
approval. The plan never executes anything by itself.

ponytail: one closed-schema completion produces the whole outline. A per-slide
"swarm" of agents is deliberately NOT built -- it is unproven cost for a one-
page deck; add it only if a measured deck needs per-slide expansion a single
pass cannot give.
"""

from __future__ import annotations

from ghostcursor.providers import DECK_SPEC_SCHEMA, DeckSpec, Envelope, parse_deck_spec
from ghostcursor.providers.envelope import tainted_chunks


def build_brief(spec: DeckSpec) -> str:
    """Render a DeckSpec as an ordered, unambiguous build brief -- the goal the
    EXISTING approved Teach/Act loop runs against real PowerPoint (the powerpoint
    skill + observed controls decide the clicks; this says only WHAT to build).

    This is the DeckSpec -> Act bridge and it is DATA: a string goal. It mints no
    input, selects no control, and carries no execution authority. Act still asks
    the user to approve the whole plan and acts only on observed controls."""

    lines = [
        f"Build this {len(spec.slides)}-slide PowerPoint deck titled "
        f'"{spec.title}", one slide per item below, in order. For each slide set '
        "its title and add its bullet points; use the slide layout named.",
        "",
    ]
    for index, slide in enumerate(spec.slides, start=1):
        lines.append(f"Slide {index} [{slide.layout.value}]: {slide.title}")
        lines += [f"  - {bullet}" for bullet in slide.bullets]
    return "\n".join(lines) + "\n"


DECK_SYSTEM_PROMPT = (
    "You plan a presentation as a slide-by-slide outline. Return only a JSON "
    "object matching the schema you are given: a deck title and an ordered list "
    "of slides. Each slide has a short title, 0-8 terse bullets, and a layout "
    "chosen by its content type (title/section/bullets/two_column/comparison/"
    "timeline/table/quote/image). Open with a title slide and group the deck "
    "into a clear narrative. Use ONLY the facts in the OBSERVED_DATA grounding "
    "entries when they are present; "
    "do not invent figures, names or quotes."
)


def plan_deck(
    gateway,
    goal: str,
    *,
    scope: str | None = None,
    knowledge=None,
    grounding: list[str] | None = None,
    k: int = 8,
    deadline_s: float = 45.0,
    cancelled=lambda: False,
) -> DeckSpec:
    """A ``DeckSpec`` for ``goal`` from the first System-Two provider that
    answers validly. Grounding (so the deck is built from known facts, not
    invented) comes from, in order: explicit ``grounding`` lines if given (e.g.
    this session's cited research claims), else the owner's reviewed non-
    sensitive Brain facts for the goal when ``knowledge`` + ``scope`` are set.
    Grounding is web- or Brain-derived, so it rides the tainted channel,
    DLP-scrubbed, as data the model may use but never as instruction."""

    goal = " ".join(str(goal).split())
    if not goal:
        raise ValueError("a deck needs a goal")
    lines = list(grounding or ())
    if not lines and knowledge is not None and scope is not None:
        facts = knowledge.recall(goal, scope, k=k)  # non-sensitive, usable only
        lines = [f"{f.text} (source: {f.source})" for f in facts]
    tainted = {"grounding": [c for line in lines for c in tainted_chunks("grounding", line)[1]]} if lines else {}
    # The goal is user-supplied, not screen-observed, so it is authoritative
    # trusted context; no tainted copy (deck review FOLLOWUP #1).
    envelope = Envelope(
        task="plan a presentation for the goal", trusted={"goal": goal}, tainted=tainted
    )
    return gateway.complete(
        envelope,
        DECK_SYSTEM_PROMPT,
        DECK_SPEC_SCHEMA,
        parse_deck_spec,
        deadline_s=deadline_s,
        cancelled=cancelled,
        purpose="deck planning",
    )


def research_deck(
    gateway,
    topic: str,
    *,
    knowledge=None,
    scope: str | None = None,
    file_to_brain: bool = True,
    **research_kw,
):
    """ "Research X and make a deck": deep-research the topic, then plan a deck
    grounded on this session's cited research claims. The rocket.new research ->
    build "one shared context" chain on Orbyn's rails -- each deck bullet traces
    to a cited, Jev-checked claim, nothing invented. With a Brain + scope the
    cited claims are also filed as reviewable candidates (durable context).

    Returns (DeckSpec, DeepResearchReport). Grounding uses the research claims
    directly (not recall), so a fresh run needs no prior owner review."""

    from ghostcursor.workspace.contracts import ClaimStatus
    from ghostcursor.workspace.research import deep_research

    report = deep_research(
        topic,
        gateway,
        knowledge=knowledge,
        scope=scope,
        file_to_brain=file_to_brain,
        **research_kw,
    )
    grounding = []
    for graph in report.graphs:
        for claim in graph.claims:
            if claim.status in (ClaimStatus.SUPPORTED, ClaimStatus.PARTIAL):
                source = next(
                    (
                        graph.source_of(pid)
                        for pid in claim.evidence
                        if graph.source_of(pid)
                    ),
                    None,
                )
                src = source.url if source and source.url else "research"
                grounding.append(f"{claim.text} (source: {src})")
    deck = plan_deck(gateway, topic, grounding=grounding or None)
    return deck, report
