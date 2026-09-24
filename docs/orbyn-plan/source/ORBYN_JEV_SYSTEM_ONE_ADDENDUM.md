# ORBYN — Jev / System-One Intelligence Addendum

> **Planning status:** This owner-supplied addendum remains source material for System-One/System-Two architecture and Jev integration. The forward implementation sequence is now maintained in [`docs/orbyn-plan/README.md`](docs/orbyn-plan/README.md) and its linked Mega Phase documents. This notice does not amend the recorded decisions or authority rules below.

**Date:** 18 September 2026  
**Companion to:** `ORBYN_UNIFIED_PLAN.md`  
**Status:** Owner-directed architecture addendum

## 0. Merge / precedence rule

Use this file together with `ORBYN_UNIFIED_PLAN.md`.

- The unified plan remains canonical for product thesis, object model, trust model, authority, execution, verification, phases, and repo status.
- This addendum is canonical for System-One/System-Two separation, Jev, Semantic Target Resolution, Jev + Spatial Context, confidence routing, and the Jev network/API amendment.
- If the files conflict only on Jev/System-One behavior, this addendum wins.
- Nothing here weakens signed capabilities, exact process binding, deterministic authorization, Needs You, or independent verification.

---

# 1. Locked architecture decision

Orbyn will explicitly use a **System-One + System-Two** intelligence architecture.

## System Two
Use slower/open-ended reasoning models for:
- ideation;
- clarification;
- conversation;
- planning;
- decomposition;
- research;
- critique;
- complex recovery;
- long-context reasoning;
- multimodal interpretation.

Examples: local Qwen, workhorse/frontier LLMs, expert models, VLMs.

## System One
Use Jev for **fast bounded typed decisions inside workflows**.

Its first and highest-value Orbyn job is:

> Given a set of real candidate UI/application objects, choose or rank the object that best matches the user's intended target.

Other good uses:
- narrow intent classification;
- capability routing among registered options;
- event routing;
- recovery-branch ranking;
- context/graph relation scoring;
- semantic collision scoring;
- read-only semantic verification evidence.

## Deterministic code
Still controls:
- permissions;
- authority;
- signatures;
- policy;
- process/window binding;
- capability registration;
- approval;
- execution;
- audit;
- rollback;
- deterministic verification.

### Foundational rule

> **System Two decides what work should be done.  
> System One decides among bounded known options.  
> Deterministic code decides what is allowed.  
> Independent verification decides whether it succeeded.**

---

# 2. Jev is not the screen-perception model

Do not build:

```text
Raw screenshot → Jev → invented x/y click
```

Build:

```text
Screenshot / Plugin / UIA / DOM / OCR / VLM
                    ↓
          candidate extraction
                    ↓
       structured real candidates
                    ↓
         Jev semantic decision
                    ↓
        candidate + probability
                    ↓
          deterministic re-bind
                    ↓
       authority / policy / approval
                    ↓
               execution
                    ↓
       independent verification
```

Jev should choose only among **runtime-minted real candidates**.

Jev's type-safe output prevents an out-of-schema arbitrary option, but Jev can still select the wrong valid option. Therefore confidence, re-binding, fallback, and verification remain mandatory.

---

# 3. New internal component: `SemanticTargetResolver`

Add a non-user-facing internal component:

```python
resolve_target(
    intent,
    candidates,
    app_context,
    spatial_context=None,
    mission_context=None
) -> TargetResolution
```

Conceptual result:

```python
TargetResolution = {
    "candidate_id": "...",
    "distribution": {...},
    "confidence": 0.0,
    "abstain": False,
    "provider": "typesafe-jev"
}
```

Rules:
- candidate must already exist;
- candidate belongs to current observation epoch;
- resolver never executes;
- resolver never grants permission;
- resolver never invents selectors;
- resolver never mints authority.

---

# 4. Canonical target-resolution pipeline

```text
USER / AGENT INTENT
        ↓
SYSTEM-TWO REASONING
(what should happen?)
        ↓
APP / SCREEN OBSERVATION
        ├─ plugin object model
        ├─ connector/API
        ├─ DOM
        ├─ UIA/accessibility
        ├─ OCR
        └─ VLM candidate generation
        ↓
DETERMINISTIC PREFILTER
        ├─ correct app/window
        ├─ visible/enabled
        ├─ role/type filter
        ├─ capability compatibility
        ├─ geometry / region
        └─ stale objects removed
        ↓
SEMANTIC TARGET RESOLVER
        ├─ Jev Choice
        ├─ Jev Noul
        └─ Jev Score
        ↓
TARGET + DISTRIBUTION + CONFIDENCE
        ↓
DETERMINISTIC RE-BIND
        ├─ same observation epoch?
        ├─ same HWND/PID/process?
        ├─ object still exists?
        ├─ enabled/actionable?
        └─ capability still registered?
        ↓
AUTHORITY CHAIN
        ↓
TEACH / ASSIST / ACT
        ↓
INDEPENDENT VERIFICATION
```

---

# 5. New permanent anti-hallucination rule

Add this runtime rule:

> **Models may choose among registered objects; models may never invent executable object identities.**

This applies to Jev, LLMs, VLMs, experts, and future models.

Reject:
- invented XPath;
- invented CSS selector;
- invented automation id;
- invented HWND/PID;
- arbitrary coordinate;
- invented plugin/capability id;
- stale candidate;
- arbitrary object handle.

The runtime alone maps a semantic choice back to a real object.

---

# 6. Jev primitives mapped to Orbyn

## Choice
Use for closed candidate sets:
- correct UI target;
- correct DOM node;
- correct registered capability;
- correct workstream/owner;
- correct event destination;
- correct recovery branch;
- correct resource among discovered resources.

## Noul
Use for probability of propositions:
- "does this object match the user's intent?";
- "does this event belong to this Mission?";
- "is this context item likely stale?";
- "is this recovery branch applicable?";
- "is this observed state semantically consistent with the request?"

Never use Noul for permission or authorization.

## Score
Use for ordered/continuous judgments:
- semantic relevance;
- candidate fit;
- ambiguity;
- recovery suitability;
- context relevance;
- artifact quality dimension;
- advisory collision severity.

Policy thresholds remain Orbyn-controlled.

---

# 7. Primary use: finding the correct UI target

Example:

```text
User:
"Open slide layout"

PowerPoint candidates:
A17 = New Slide
A18 = Layout
A19 = Reset
A20 = Section
```

Jev may return a distribution such as:

```text
A18 Layout      0.96
A17 New Slide   0.02
A19 Reset       0.01
A20 Section     0.01
```

Orbyn then:
1. re-binds A18;
2. checks correct process/window;
3. checks current capability;
4. checks Mission/action authority;
5. highlights or acts;
6. independently verifies that the expected state occurred.

Target selection is not action authorization.

---

# 8. Confidence policy

Do not hard-code permanent thresholds before Orbyn-specific evaluation.

Use policy bands:

```text
HIGH
→ continue to deterministic validation

MEDIUM
→ highlight / ask user / gather more context

LOW
→ fallback perception / Spatial Context / abstain
```

Thresholds may vary by:
- app;
- mode;
- action risk;
- candidate source;
- enterprise policy.

Teach can tolerate lower confidence than Act.

Level 4/5 authority never loses human/policy requirements merely because Jev is confident.

---

# 9. Perfect fit with Spatial Context

Spatial Context answers:

> **Where is the user referring to?**

Jev answers:

> **Which real object in that region best matches what the user means?**

Pipeline:

```text
user circles region
        ↓
SpatialContextReference
        ↓
geometry filter
        ↓
plugin/UIA/DOM candidate extraction
        ↓
Jev choice/ranking
        ↓
best candidate + confidence
        ↓
fresh deterministic re-bind
        ↓
normal authority chain
```

Example:

```text
User circles a chart:
"Make this easier to understand."
```

Candidates:

```text
chart_12
legend_13
textbox_14
shape_15
```

Jev resolves `chart_12`; System Two decides how to simplify it; the signed PowerPoint capability performs approved work; the verifier checks the resulting deck.

Spatial Context remains **context, never authority**.

---

# 10. Two-mark Spatial Context

Support:

```text
Mark A = SOURCE
Mark B = TARGET
```

Examples:
- "Move this here."
- "Make this match this."
- "Use this style on these."
- "Connect this to this."

Flow:
1. extract source candidates;
2. Jev resolves source;
3. extract target candidates/region;
4. Jev resolves destination semantics;
5. planner proposes registered capability;
6. runtime validates resource types and permissions;
7. approve/act;
8. verify.

---

# 11. Candidate representation

Every candidate needs a stable local id plus semantic data.

Example:

```json
{
  "candidate_id": "uia:epoch481:node37",
  "source": "uia",
  "app_id": "powerpoint",
  "role": "button",
  "name": "Layout",
  "enabled": true,
  "visible": true,
  "parent_semantics": ["Home", "Slides"],
  "nearby_text": ["New Slide", "Reset"],
  "spatial_relation": "inside_user_mark",
  "capability_refs": ["ppt.open_layout"],
  "observation_epoch": "epoch481"
}
```

For a plugin object:

```json
{
  "candidate_id": "ppt:slide4:shape12",
  "source": "plugin",
  "app_id": "powerpoint",
  "object_type": "chart",
  "semantic_name": "Quarterly Revenue",
  "slide_index": 4,
  "spatial_relation": "inside_user_mark"
}
```

Only local runtime code can convert `candidate_id` to a live executable object.

---

# 12. High-cardinality screens

Do not pass the full desktop accessibility tree directly to one Choice.

Use hierarchical reduction:

```text
1800 UIA nodes
    ↓
bound window
    ↓
430
    ↓
visible/actionable
    ↓
122
    ↓
role + geometry + capability filters
    ↓
54
    ↓
Jev Choice
```

For larger sets:

```text
all candidates
    ↓
Noul/Score relevance
    ↓
top N
    ↓
Choice
```

Keep provider cardinality limits behind the adapter; never bake today's Jev limit into Orbyn's architecture.

---

# 13. Where Jev should be used

## P0
1. **Semantic Target Resolution**
2. **Spatial Context disambiguation**
3. **Capability routing among registered capabilities**
4. **Fast narrow intent classification**

## P1
5. **Event routing**
6. **Recovery-branch ranking**
7. **Company Brain relation classification**
8. **Context staleness triage**
9. **Coordination Engine semantic collision scoring**

## P2
10. **Artifact Critic structured judgments**
11. **Support/handoff destination routing**
12. **Agent-trace observability**
13. **Qualitative semantic verification evidence where deterministic checks are insufficient**

---

# 14. Where Jev must never decide

Jev must not decide:
- permissions;
- RBAC;
- authorization;
- credential exposure;
- signature validity;
- process identity;
- app identity;
- approval bypass;
- purchase/spending authority;
- destructive action authority;
- arbitrary selectors;
- arbitrary capability ids;
- whether Needs You may be skipped;
- deterministic completion when code can check it exactly.

Bad:

```text
Jev says this is safe → execute
```

Correct:

```text
Jev suggests target
↓
deterministic policy
↓
permission
↓
approval
↓
execution
↓
verification
```

---

# 15. Jev in verification

Deterministic verification stays first.

Example:

```text
✓ slide exists
✓ five competitors remain
✓ theme id unchanged
```

For qualitative criteria only:

```text
"Is the slide materially clearer?"
```

Jev or another critic may provide read-only semantic evidence.

Uncertain semantic verification triggers review.

The verifier remains read-only and independent from action execution.

---

# 16. Model Router changes

Change the router taxonomy to:

```text
SYSTEM TWO
├─ local reasoning
├─ workhorse reasoning
├─ frontier reasoning
├─ vision/multimodal
└─ embeddings

SYSTEM ONE
├─ Jev decision provider
└─ deterministic/local fallback
```

Add generic router operations:

```python
choose(...)
noul(...)
score(...)
resolve_target(...)
rank_candidates(...)
classify_state(...)
route_event(...)
route_capability(...)
```

Do not spread `jev_*` calls across core code.

---

# 17. Provider abstraction

```python
class SystemOneProvider:
    def choose(self, state, question, options): ...
    def noul(self, state, question): ...
    def score(self, state, question, scale): ...
```

Result:

```python
class DecisionResult:
    value
    distribution
    confidence
    provider
    model_version
    latency_ms
    request_digest
```

Initial provider:

```text
TypeSafeJevProvider
```

Fallbacks:

```text
DeterministicHeuristicProvider
LocalStructuredModelProvider
SystemTwoStructuredFallback
```

Orbyn safety must never depend on Jev availability.

---

# 18. D017 amendment

The owner has Jev API access and has explicitly approved adding Jev where it best fits.

Do not erase D017 history. Amend it.

## D141-R1 — Consented network intelligence and connector tier

**Amends D017.**

Local-only remains:
- default install behavior;
- hermetic test baseline;
- air-gapped option;
- safe fallback.

Add separately revocable network capabilities:

1. Connected App networking: API/OAuth/MCP/events.
2. System-Two cloud escalation under policy.
3. **System-One decision providers, initial provider TypeSafe Jev.**
4. Events-only telemetry, off by default.

### Jev network rules

Jev may receive:
- intent;
- candidate semantics;
- role/type/name;
- minimal local app context;
- spatial relationship.

Prefer not to send:
- full accessibility tree;
- raw screenshots;
- entire documents;
- secrets;
- credentials;
- unnecessary source code;
- customer content.

Jev never receives:
- Orbyn authority token;
- credential vault secrets;
- signing key;
- approval token.

A Jev outage must fail safely to fallback/confirmation, not to guessed execution.

---

# 19. New decision D145

## D145 — System-One models are bounded semantic decision providers

Orbyn may use System-One models such as Jev for fast semantic decisions over **closed runtime-provided option sets**.

### Allowed
- candidate target selection;
- ranking;
- classification;
- intent routing;
- capability proposal/routing among registered capabilities;
- event routing;
- recovery ranking;
- Context Graph candidate relation scoring;
- semantic collision scoring;
- semantic verification evidence.

### Forbidden
System-One providers may not:
- mint authority;
- grant permission;
- bypass approval;
- invent resource identities;
- invent selectors;
- invent capability ids;
- validate signatures;
- expose credentials;
- decide RBAC;
- override policy/risk;
- replace deterministic verification where exact checking exists.

### Runtime requirements
Every chosen object must:
1. already be known;
2. have a current candidate id;
3. be freshly re-bound before action;
4. pass the full authority chain;
5. be independently verified after execution.

---

# 20. Perception-source trust

Jev confidence is only one input.

The runtime should also consider:
- candidate source quality;
- object stability;
- spatial alignment;
- plugin evidence;
- current-state consistency.

Preference:

```text
plugin object model
    >
structured connector / DOM
    >
UIA/accessibility
    >
OCR-created candidate
    >
VLM-created candidate
```

Do not treat equal Jev probability over a VLM candidate and plugin object as equal overall trust.

---

# 21. Jev + VLM

When structured perception is weak:

```text
screenshot
    ↓
VLM / vision detector
    ↓
candidate regions + descriptions
    ↓
Jev semantic choice
    ↓
highlight / confirm / bounded action
```

The VLM discovers candidates.

Jev chooses among them.

VLM-generated candidates receive a lower trust class than plugin/UIA/DOM candidates.

---

# 22. Browser use

Preferred:

```text
DOM / browser connector
    ↓
real nodes
    ↓
filter
    ↓
Jev
    ↓
DOM action
    ↓
verification
```

No invented CSS selector.

---

# 23. Generic Windows applications

Preferred:

```text
UIA
↓
real accessible elements
↓
process/visibility/role filtering
↓
Jev
↓
fresh UIA re-bind
↓
pointer or allowed UIA invoke
↓
verification
```

This is especially valuable when user language and actual control names differ.

---

# 24. Legacy/inaccessible applications

If there is:
- no plugin;
- no connector/API;
- no DOM;
- weak UIA;
- weak OCR semantics;

then Jev alone cannot solve perception.

Use:

```text
vision/VLM candidate generation
↓
Jev candidate selection
↓
Teach/Assist unless a reviewed execution boundary exists
```

---

# 25. Jev in the Mission engine

System Two remains responsible for:
- Mission objective;
- clarification;
- decomposition;
- task graph;
- tradeoffs;
- complex recovery.

Jev handles narrow local decisions inside the graph:
- which candidate object?;
- which registered capability?;
- which known event destination?;
- which valid recovery branch?;
- which workstream is relevant?

---

# 26. Connected Apps enhancement

Keep the user-facing contract:

```text
Observe
Act
Verify
Events
Permissions
```

Internally allow Apps to additionally provide:
- candidate descriptions;
- aliases;
- object semantics;
- parent context;
- capability compatibility;
- stability metadata.

Do not create a new user-facing primitive.

---

# 27. Company Brain / Context Graph

Jev can score candidate graph relationships.

Example:

```text
Pricing changed.

Candidate affected objects:
- website pricing page
- sales deck
- proposal template
- CRM product
- onboarding FAQ
```

Jev may score likely impact.

Durable Company Brain knowledge still follows:
- provenance;
- owner;
- review;
- staleness;
- approval.

Jev never turns a candidate relation into unquestioned company truth.

---

# 28. Coordination Engine

Deterministic exact resource collisions need no AI.

Example:

```text
Agent A edits Slide 7
Agent B edits Slide 7
```

Semantic conflicts may.

Example:

```text
Marketing changes homepage headline
SEO changes search-intent positioning
```

Jev can score semantic conflict and raise a coordination warning.

Policy decides whether to wait, merge plans, or ask a human.

---

# 29. Recovery

Runtime creates the valid recovery set:

```text
reobserve
safe retry
alternate registered capability
ask user
handoff
```

Jev ranks/selects only within that set.

It cannot invent an unregistered execution path.

---

# 30. Agent observability

Use a read-only System-One review after significant runs:

```text
task_completed?
silent_failure_likely?
expectation_gap?
human_review_needed?
```

This can feed QA/recovery queues.

It does not rewrite the Mission record or grant authority.

---

# 31. Logging

For consequential Jev decisions record locally:
- provider;
- model/version;
- schema version;
- candidate-set digest;
- question digest;
- selected candidate id;
- distribution/confidence;
- latency;
- policy version;
- fallback used;
- resulting action;
- verification outcome.

Do not log sensitive full candidate content by default.

---

# 32. Outage behavior

Fallback ladder:

```text
deterministic exact/fuzzy match
↓
local structured model / embeddings
↓
System-Two structured fallback
↓
Spatial Context / user confirmation
↓
Teach/Assist / refusal
```

Never:

```text
Jev unavailable → guess coordinate
```

---

# 33. Jev security rules

1. API key in OS-secure storage / Credential Vault.
2. Only the Model Router/SystemOneProvider can call Jev.
3. Plugins, Skills, and Agents never receive the raw key.
4. Minimize state sent to provider.
5. Redact secrets and unnecessary personal data.
6. Use ephemeral external aliases for local candidate ids where practical.
7. Schema-validate every response.
8. Map the selection back locally.
9. Never send authority tokens.
10. Jev calls participating in active execution must respect Pause/Stop.

---

# 34. Suggested TypeScript-style data contracts

```typescript
type CandidateObject = {
  candidateId: string;
  source: "plugin" | "connector" | "dom" | "uia" | "ocr" | "vision";
  appId: string;
  resourceId?: string;
  objectType?: string;
  role?: string;
  label?: string;
  semanticDescription?: string;
  parentContext?: string[];
  nearbyText?: string[];
  visible?: boolean;
  enabled?: boolean;
  bounds?: { x: number; y: number; width: number; height: number };
  spatialRelation?: "inside" | "overlap" | "near" | "outside";
  capabilityRefs?: string[];
  observationEpoch: string;
};

type SemanticResolutionRequest = {
  intent: string;
  candidates: CandidateObject[];
  appContext: {
    appId: string;
    currentView?: string;
  };
  spatialContextRef?: string;
  missionContextDigest?: string;
};

type SemanticResolutionResult = {
  selectedCandidateId?: string;
  distribution: Record<string, number>;
  confidence: number;
  abstained: boolean;
  provider: string;
  modelVersion: string;
  requestDigest: string;
};
```

No executable selector leaves this contract.

---

# 35. Orbyn Target Resolution Eval

Build a dedicated benchmark.

Initial apps:
- PowerPoint;
- browser;
- VS Code;
- Excel;
- Windows Settings;
- legacy app later.

Each case:

```text
user_intent
candidate list
ground-truth target
perception source
spatial context if any
```

Compare:
1. deterministic match;
2. embeddings;
3. local Qwen structured choice;
4. Jev;
5. frontier System-Two model.

Measure:
- Top-1 accuracy;
- Top-3 accuracy;
- calibration;
- abstention quality;
- false-high-confidence rate;
- latency;
- cost;
- repeated-run stability;
- accuracy by candidate source;
- accuracy with/without Spatial Context.

### Most important metric

> **When Jev is wrong, does its confidence allow Orbyn to avoid acting?**

---

# 36. Activation criteria

Do not activate Jev-driven Act targeting just because the API works.

Require:
1. retained benchmark dataset;
2. independently reviewed harness;
3. measured latency;
4. calibration analysis;
5. false-high-confidence characterization;
6. exact candidate re-bind test;
7. stale-observation rejection;
8. wrong-process rejection;
9. Pause/Stop while Jev request is pending;
10. outage fallback;
11. authority-token leakage test;
12. privacy/redaction test;
13. independent verification preserved;
14. Teach-mode field trial first.

---

# 37. Updated roadmap

## Phase 1 — unchanged
Finish PowerPoint Limited Act activation and trust evidence.

Do not delay it for Jev.

## Phase 2 — add System-One foundation
Alongside Ideate/Plan + Spatial Context:
1. `CandidateObject`;
2. candidate registry;
3. observation epoch;
4. `SystemOneProvider`;
5. `SemanticTargetResolver`;
6. deterministic/local fallback;
7. `TypeSafeJevProvider`;
8. D141-R1 network policy;
9. PowerPoint target resolution;
10. Spatial Context + Jev;
11. target-resolution eval;
12. Teach-mode trial;
13. Act-mode use only after review.

## Phase 3 — capability platform
Use Jev for:
- capability routing;
- Connected App target resolution;
- event routing;
- narrow classification.

## Phase 4 — personal multi-agent
Use Jev for:
- workstream/event routing;
- recovery selection;
- agent-trace observability.

## Phase 5 — self-maintaining APIs
Use Jev for:
- provider-change classification;
- affected-resource candidate scoring;
- known-service/workstream routing;
- semantic verification evidence where deterministic code is insufficient.

Never use it for merge authority or credentials.

## Phase 6 — Multiplayer
Use Jev for:
- event routing;
- handoff destination suggestions;
- semantic collision scoring;
- context relevance.

## Phase 7 — Context Graph
Use Jev for:
- candidate relation scoring;
- staleness triage;
- candidate knowledge classification.

## Phase 8 — enterprise
Support provider policies:

```text
Jev cloud
local System-One provider
private provider
deterministic-only
```

---

# 38. Exact edits to `ORBYN_UNIFIED_PLAN.md`

## §0
Add under Intelligence:
`System-One Decision Layer (initial provider: Jev)`.

Add:
> Orbyn separates System-Two reasoning from System-One execution-time decisions; neither is an authority path.

## §3
Update Model Router:
`local / workhorse / frontier / vision / embeddings / System-One decision`.

Insert:
`Semantic Target Resolver (candidate extraction → typed semantic choice → deterministic re-bind)`.

## §3 execution rules
Add:
> Within plugin/UIA/DOM/vision paths, semantic target selection may use a System-One provider only over runtime-minted candidates.

## §5.1 Spatial Context
Add:
> Spatial Context narrows where; Semantic Target Resolver/Jev helps resolve what. Neither creates authority.

## §5.5 Perception
Add rows:
- Candidate Registry + Observation Epoch;
- Semantic Target Resolver;
- Jev target disambiguation.

## §5.6 Intelligence
Add rows:
- System-One Provider;
- TypeSafe Jev.

Update Model Router.

## §5.7 Capability Layer
Add internal candidate-description support to Connected Apps.

## §5.8 Collaboration Kernel
Add future:
- Jev event routing;
- handoff suggestions;
- semantic collision scoring.

## §6 Phase 2
Add System-One foundation and evaluation.

## §9 / §9b
Adopt D141-R1 and D145.

---

# 39. Suggested internal modules

```text
ghostcursor/
  intelligence/
    system_one/
      provider.py
      types.py
      policy.py
      resolver.py
      calibration.py
      providers/
        deterministic.py
        local.py
        typesafe_jev.py

  perception/
    candidates.py
    candidate_registry.py
    observation_epoch.py

  spatial/
    context.py
    resolver.py
```

Adapt to repository conventions rather than forcing this exact tree.

Application-specific candidate extraction stays inside the relevant plugin/adapter.

---

# 40. Minimal first implementation

## PowerPoint Teach target resolver

```text
user request
↓
PowerPoint UIA candidates
↓
deterministic filter
↓
Jev Choice
↓
fresh re-bind
↓
pointer highlight
↓
human action
↓
verification
```

Why Teach first:
- measures semantic accuracy;
- measures confidence;
- measures latency;
- tests target stability;
- tests Spatial Context;
- does not widen Act authority.

Then reuse the same resolver in Act after evidence/review.

---

# 41. Second implementation

## PowerPoint Spatial Context + Jev

```text
circle object
"make this simpler"
↓
plugin candidates
↓
Jev resolves object
↓
System Two plans change
↓
registered capability proposal
↓
Needs You if required
↓
Act
↓
verify
```

This is the cleanest demo of System One + System Two together.

---

# 42. Third implementation

## Browser DOM + Jev

```text
DOM candidates
↓
SemanticTargetResolver
↓
Jev
↓
real DOM node
↓
browser action
↓
verification
```

If PowerPoint object-model/UIA and browser DOM both use the same resolver, the abstraction has generalized correctly.

---

# 43. Foundational Orbyn statement

> **Perception discovers what exists.  
> System Two understands what the user wants.  
> System One chooses among real bounded options.  
> Deterministic policy decides what is allowed.  
> Apps perform the action.  
> Independent verification proves what happened.**

---

# 44. Strategic benefit

Avoid:

```text
screen
↓
one multimodal LLM
↓
reason
↓
invent click
↓
click
↓
same model claims success
```

Use:

```text
Observe
↓
Structure
↓
Reason
↓
Choose
↓
Authorize
↓
Execute
↓
Verify
```

Benefits:
- debuggability;
- lower latency;
- lower cost;
- explicit uncertainty;
- better privacy boundaries;
- clearer failure modes;
- provider replaceability;
- safer Spatial Context;
- stronger enterprise explainability.

---

# 45. Final locked Jev position

Jev is:

> **Orbyn's first System-One decision provider.**

Jev is not:
- the planner;
- permission engine;
- authority engine;
- screen-perception engine;
- executor;
- Company Brain;
- sole verifier;
- Agent runtime.

Its core job is:

> **Fast typed probabilistic decisions among options Orbyn already knows are real.**

Its first killer use is:

> **Semantic Target Resolution.**

Its ideal companion is:

> **Spatial Context — the human narrows where; Jev helps resolve what.**

---

# 46. External technical assumptions

This addendum is based on TypeSafe's public Jev material as of 18 September 2026:

- Jev is positioned as a System-One model for typed machine-facing decisions.
- TypeSafe publicly describes `Choice`, `Noul`, and `Score` workflow primitives.
- Outputs include probabilities/confidence.
- Jev is intended for bounded automation decisions rather than free-form text generation.
- Current public demos emphasize structured/text state rather than direct image perception.
- Type safety does **not** mean semantic infallibility; Jev can still choose the wrong valid option.

Any provider-specific API shape, limit, model version, latency, or price is an external dependency and must remain isolated behind `TypeSafeJevProvider`.

---

# 47. Immediate next actions

After current Act activation work:

1. Record D141-R1.
2. Record D145.
3. Add `SystemOneProvider`.
4. Add `CandidateObject`.
5. Add candidate registry and observation epoch.
6. Add `SemanticTargetResolver`.
7. Implement `TypeSafeJevProvider`.
8. Integrate PowerPoint UIA/object candidates.
9. Build target-resolution eval.
10. Calibrate confidence policy.
11. Add Spatial Context narrowing.
12. Run Teach field tests.
13. Add Act semantic targeting only after review.
14. Generalize to browser DOM.
15. Later extend to routing, recovery, Company Brain, Coordination Engine, and agent observability.

---

# 48. Non-negotiable constraint

The addition of Jev must make Orbyn **more reliable**, not more autonomous by shortcut.

> **Jev can help Orbyn know which real option is probably the right one.  
> Jev can never decide that Orbyn is allowed to act.**
