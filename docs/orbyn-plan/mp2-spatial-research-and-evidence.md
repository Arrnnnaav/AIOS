# MP2 — Spatial, Research, and Evidence

## Purpose and phase grouping

Deliver trustworthy pointing and evidence-grounded answers. The Untrusted Observation Boundary is a prerequisite of the earliest work here, before DOM, PDF, OCR, or search content enters any model request. Detailed phases:

- **Phase 5 — Untrusted Observation Boundary**
- **Phase 6 — Spatial contract and candidate pipeline**
- **Phase 7 — EvidenceGraph and ResearchTrace**
- **Phase 8 — Research workflow and answer presentation**

## Project and activation boundary

The standalone Spatial application is a separate project at `D:\PROJECTS\Spatial`; it is built, evaluated, and reviewed in its own repository. Do not move its implementation into AIOS or couple it to the manager during the standalone phase. The Spatial repository currently has independent local work; this plan does not authorize cleaning, resetting, or editing that working tree.

Before GhostCursor/Orbyn Act activation, only the standalone Spatial project and read-only evaluation/design may advance. Phase 6's Orbyn integration is explicitly later: after the independent Act activation review returns READY, implement D143 Spatial Context as the first item of ROADMAP Stage 1. That integration passes a `SpatialContextReference` into a Brief as context only; it is not a selector, coordinate, target identity, or authority. Research features that require Orbyn manager wiring wait for that gate. Cloud reasoning is available under D147; side-effecting connectors remain separately gated under D141/D144.

## Phase 5 first: untrusted content boundary

Define typed request envelopes that separate trusted control fields (user’s current question/goal, policy, provider instructions, and allowed task) from tainted content (DOM, ARIA labels, PDF text, OCR, document text, search results, retrieved passages, and application-authored messages). Tainted content is quoted/structured evidence only and cannot modify the goal, permissions, tools, provider routing policy, or system instructions.

Tag each content item with source kind, origin reference, observation/context digest, extraction time, and trust class. Sanitize markup/control characters and bound size. Do not rely on prompt wording alone: prevent tainted values from populating trusted schema fields; validate output against a closed schema; never parse model text as code, selector, shell command, policy, or capability.

Test direct and indirect injection across all supported sources, including OCR and search pages. Test hidden DOM text, ARIA instruction strings, source conflicts, Unicode/control characters, long payloads, and attempts to request secrets or unrelated actions. A detected malicious instruction remains quoted content; it may be reported to the user but cannot expand authority.

## Phase 6: SpatialContext and candidate pipeline

Within the standalone Spatial project, use the existing Spatial v3 schema as the initial compatibility baseline. Preserve mark geometry in CSS/logical surface pixels with explicit crop and device-pixel metadata. Candidate sources normalize to one `CandidateObject` shape (DOM, PDF text, OCR, later UIA/vision). Stable candidate identity is scoped to an observation/context epoch and never promoted to a selector or authority. The Orbyn-facing SpatialContextReference adapter/schema and Brief append are not part of this independent build; they wait for Act activation READY and ROADMAP Stage 1.

Pipeline:

1. Capture mark and question from extension or supported desktop surface.
2. Collect only nearby/relevant structured candidates; exclude hidden/sensitive fields by policy.
3. Run deterministic geometry filtering/ranking and candidate deduplication locally.
4. Run local OCR when structured text is missing; map OCR boxes through the captured crop geometry.
5. Use Jev for bounded target disambiguation only when it improves a measured case; otherwise use deterministic selection or ask for clarification.
6. Show resolved-object chip, confidence/ambiguity, and correction alternatives before relying on the resolution.

Start with browser DOM and PDF text, using the existing prototype. Add shadow DOM, iframes, SVG, canvas, scanned PDFs, desktop UIA, and vision candidates as independently evaluated expansions. Do not let an absent candidate become a fabricated one.

## Phase 7: shared evidence and trace contracts

`EvidenceGraph` is the shared research/answer artifact, not merely a list of URLs. It models nodes for question, selected context, claim, source, passage, generated answer, and optionally memory/plan references; edges encode `derived_from`, `supports`, `partially_supports`, `contradicts`, and `cites`. Claim support state is explicit. Graph IDs are scoped/versioned; graph validation rejects dangling IDs, unsupported claim edges, citations to unused passages, and cycles in provenance/derivation paths. Support and contradiction relations remain typed links between claims and evidence.

`ResearchTrace` is an append-only sequence for one research operation. It records request/trace identity; input/context digest; trust labels; System-One routing decision and candidate set digest; query strings (redacted if sensitive); search/fetch provider; source and passage identities; graph changes; answer claims/citations; System-Two provider/model; privacy decision and data classes sent; timestamps/latencies; errors/fallback; and the final user-visible result digest. It must not retain API keys, raw window/process handles, or screenshot bytes. Retention is local and bounded in MVP, with export/delete controls.

The future Orbyn planning layer references the `ResearchTrace` and graph digest rather than flattening evidence into unattributed chat text. This consumer integration waits for Act activation READY and the relevant ROADMAP stage. Store fetched passages locally under a bounded retention policy; exports carry source and claim relationships, not copied page corpora by default. Exported context avoids hidden dependencies on a chat session.

## Phase 8: Research workflow and answer presentation

The standalone Spatial project already contains search/research work; continue it only behind the Phase 5 trust boundary and Phase 7 evidence validation. In Orbyn, manager-integrated research still waits for its roadmap stage. Network-backed search/fetch and cloud reasoning are available under D147 within the standalone project and behind the provider gateway; they do not bypass the Phase 5 trust boundary or Phase 7 evidence validation. No page/document payload may be sent to a model before Phase 5 passes its adversarial gate, and no research answer is called evidence-grounded before Phase 7 validation exists.

Search/fetch uses bounded queries, strict URL/redirect policy, private-address/SSRF rejection, size/time/content-type bounds, deduplication, and passage extraction. Search snippets are provisional evidence; prefer the source page when it can be fetched safely. Retrieved pages remain untrusted and cannot alter the user goal or trusted model instructions.

Answer pipeline:

```text
question + selected context
→ bounded queries
→ fetched sources and passages
→ EvidenceGraph construction
→ claim/evidence synthesis
→ deterministic citation validation
→ concise answer + source panel + ResearchTrace
```

Use source categories and provenance (primary documentation, official source, academic, government, established publication, community, unknown), publication/update metadata when available, and retrieval time. Do not expose an unexplained numerical credibility score. Each factual claim links to passage/source nodes and is marked `SUPPORTED`, `PARTIALLY_SUPPORTED`, `CONTRADICTED`, or `UNRESOLVED`. A validator checks cited IDs and graph links; missing or unsupported evidence is labeled or omitted.

## Interfaces and compatibility

- `SpatialContext` v3 remains the source shape until compatibility is reviewed; a future version adds explicit observation frame, trust labels, and candidate provenance without silently changing v3 meaning.
- `SpatialContextReference` is a brief-safe, digest-bound projection. It cannot carry actionable coordinates or selectors for later execution.
- `EvidenceGraph` and `ResearchTrace` are shared across Spatial, Orbyn briefs, plan review, and future Brain provenance; no service owns their semantics privately. Provenance/derivation paths are acyclic; support and contradiction links are typed relations.
- The browser extension does not hold model/provider secrets. All network calls pass through the server gateway.

## Continuous evaluation and exit gates

- Geometry JS/server parity fixtures run on each geometry change.
- Maintain golden browser/PDF cases for correct target, ambiguity/abstention, OCR, multi-mark, and user correction from the first integration change.
- Replay EvidenceGraph and ResearchTrace construction after every retrieval/resolver/provider change.
- Keep adversarial document/web injection corpus in the earliest merge gate, not a later security cleanup.
- Phase 7 exit: EvidenceGraph and ResearchTrace are stable, versioned, privacy-bounded, and replayable; dangling or fabricated provenance fails closed.
- Phase 8 exit: supported surfaces produce replayable contexts; candidate corrections are represented; claim/source/passage lineage is queryable; citations are validated; source fetch restrictions and degraded behavior are tested.
