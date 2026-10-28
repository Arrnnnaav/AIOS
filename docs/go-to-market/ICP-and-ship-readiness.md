# Orbyn — Ship-Readiness & ICP (2026-10-22)

Two things: what actually blocks selling Orbyn, and who to sell it to first.
ICP section is inferred from the product's structural advantages vs. the
competitor set (Orbyn is pre-market; no observed demand yet) — validate with
discovery calls before committing GTM spend.

---

## Part A — Production / ship readiness

### Done this session (committed)
- **Version string** — `ghostcursor.__version__ = "0.1.0"`, single source of
  truth for support / telemetry / update-check / signed-bundle compatibility.
- **Pinned dependencies** — `requirements.txt` (+ `requirements-voice.txt`), so
  a production PyInstaller build is reproducible (deps had lived only in prose).
- **User-facing README rewritten** — the shipped README was stale and wrong
  (named GhostCursor, VS Code/Excel focus, and claimed it "never sends input"
  which the signed Act path has made false). Now accurate to current Orbyn.
- **Safety surface hardened** — full D018 mutation audit of every tier-1 guard
  (input synthesis, ESC kill switch, signed-bundle verification, anti-rollback,
  egress/DLP, content containment) + the Brain's tenant isolation. All test
  lanes green (hermetic 3606, interactive 69, pixel 3, hung 13, overlay 16/16,
  e2e 8/8).

### Blocking — OWNER decisions (I cannot do these)
| Item | Why it blocks a sale | Owner action |
|---|---|---|
| **LICENSE / EULA** | No `LICENSE` file; can't legally distribute or sell. | Pick a commercial license + EULA; add `LICENSE`. |
| **Code-signing certificate** | `Orbyn.exe` is unsigned → SmartScreen warns, enterprises block it. Plugins are signed; the *app* is not. | Buy an EV/OV code-signing cert; sign the PyInstaller output + set up timestamping. |
| **Pricing & packaging tiers** | No pricing. (See ICP: ~$30–75/seat/mo beachhead.) | Decide tiers, seat minimums, expansion/org tier. |
| **Privacy policy / data-handling brief** | The #1 sales asset for the beachhead (local-first). Not written. | Draft a one-page "nothing leaves the device" security brief (I can draft from the code; owner approves claims). |
| **Act v1 acceptance evidence** | Counted PowerPoint manager runs (D162/D139). Needed to *claim* Act, not to ship Teach. | Run a counted campaign on a real desktop. |
| **Production trust-root signing** | Marketplace revocation/publisher identity is built + proven with a dev key; production needs the real root key. | Sign `root.b64` + key-manifest/revocation docs. |

### Build / infra gaps (buildable, not yet done)
- **Signed installer + auto-update** — PyInstaller onedir and a user-level
  shortcut installer exist. The installer now stages replacements and rolls
  back a failed switch; the executable and installer are unsigned, and there
  is no MSI or automatic update channel. See
  `docs/evidence/installer-update-2026-10-28.md`.
- **Crash reporting / support logging** — a local redacted crash log exists in
  `ghostcursor/workspace/crashlog.py`; an opt-in support export and reporting
  workflow are not built. Telemetry remains local and off by default.
- **Onboarding / first-run** — no guided first-run; `Orbyn.cmd` opens the
  workspace cold.

### Ship-readiness verdict
**Teach + Company Brain are demonstrable and safe to pilot** on a real desktop
today. **Not yet a boxed product to sell at scale** — the gating items are
LICENSE, app code-signing, pricing, and the local-first security brief. The
engineering/safety surface is in good shape; the gaps are commercial/legal and
packaging, which are owner calls.

---

## Part B — ICP (who to sell to)

### Beachhead (sell here first)
**Compliance / ops-enablement owners at regional & community banks, credit
unions, and insurance carriers / agencies / claims BPOs** (~200–5,000 employees,
BFSI + healthcare-admin), focused on back-office teams running complex **legacy
Windows desktop apps** (core banking, claims, EHR admin, case management).

**Why them, and why now (the wedge):** their screens hold SSNs / PHI / account
numbers, so any cloud DAP or screen-recorder triggers a data-egress security
review that stalls deals for months. Orbyn's *nothing-leaves-the-device* +
pre-egress DLP + org-policy-can-only-lower-egress means an ops leader can **pilot
it departmentally without that review** — local-first turns the compliance
blocker into a *faster* land where WalkMe-class incumbents can't go. That is the
core GTM insight.

**Painful job:** get a high-turnover back-office team through an error-prone
legacy app correctly every time, on-screen, without building/maintaining
training content or risking a compliance miss. Teach points at the next real
control; Act does narrow approved repetitive steps.

**Honest tension:** "regulated" and "short sales cycle" usually conflict. Orbyn
resolves it only for the *departmental, local-only pilot*; org-wide expansion
still hits full procurement. Sell the land as low-risk-because-local; expect
expansion slower.

### Also-ran ICPs
- **#2 Enterprise IT / L&D in privacy-constrained orgs** (gov, defense-adjacent,
  air-gapped) — strong revenue, but incumbent-displacement + long procurement.
  Not the beachhead.
- **#3 Prosumer privacy-conscious power users** (anti-Rewind/anti-Recall, BYOK +
  local) — good for funnel/awareness, weak as primary revenue (low ARPU, high
  churn, free local tools compete).

### Pricing shape
Land **bottom-up per-seat ~$30–75/seat/mo** (team plans, seat minimum) — a
department for a few thousand $/yr, deliberately **below the DAP
security-review/RFP threshold**. Expand **top-down** to an org agreement priced
against the DAP line (WalkMe-class $30k–$400k/yr), with org-policy egress locked.
Local-first architecture is what *enables* the bottom-up land in a regulated
buyer.

### Position against
- **WalkMe / Whatfix / Pendo Adopt** (DAPs, cloud, $30k–$400k/yr, long RFP) →
  Orbyn is on-device, pilotable without a cloud security review, and *acts*, not
  just guides.
- **Scribe / Guidde** (SOP docs, $12–50/seat/mo) → live in-app guidance + action
  vs. static docs that go stale.
- **UiPath / Power Automate Desktop** (RPA, $15–~$5k/user) → no brittle recorded
  scripts; approve-the-plan + observed-control safety; guidance-first, IT-light.
- **Microsoft Recall / Rewind→Limitless** (always-on recorders, $19–29/mo;
  Recall drew heavy privacy backlash) → Orbyn is explicitly **not** a recorder.
- **General computer-use agents** (Operator-class) → Orbyn is narrow, signed,
  auditable, on-device — deliberately not a general autonomous agent.

### Top objections → counter
1. *Why not WalkMe / free Scribe?* → cloud six-figure IT-owned vs. on-device
   pilotable-now, and Orbyn does guidance **and** approved action.
2. *Another Recall risk?* → opposite by design: no screenshots/HWND/PID leave
   the device; org policy can only lower egress.
3. *Trust an AI to act in our systems?* → whole-plan approval, observed controls
   only, asks before risky steps, ESC always stops, signed/auditable bundles —
   "narrower and more auditable than RPA," not an autonomous agent.

### Validate before GTM spend
5–10 discovery calls in credit unions / community banks / insurance claims BPOs.
Unproven: actual demand, that regulated ops teams adopt AI guidance at all, and
exact competitor list prices (all estimated from secondary sources — every
enterprise comparable is "contact sales").

### Channels
Vertical trade bodies/events (America's Credit Unions, ICBA, BAI, Big "I"/IIABA,
claims-BPO ops forums); compliance & back-office-ops communities; content themed
"DAP without the cloud / Recall-safe guidance." Package the local-first security
brief as the lead sales asset.

### Sources
DAP pricing trupeer.ai/nl/blog/dap-pricing · Scribe/Guidde guidde.com pricing
pages · RPA automationatlas.io, capterra UiPath, vendr UiPath · Recall backlash
techrepublic / corporatecomplianceinsights / cyberinsider · Rewind/Limitless
usagepricing.com, techcrunch (Meta acq.) · Whatfix vs WalkMe + FS positioning
whatfix.com.
