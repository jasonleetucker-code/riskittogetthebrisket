# Owner TODO Recovery Audit — 2026-09-10

**Status:** zero-loss owner-intent recovery / repository reconciliation  
**Window:** 2026-07-10 through 2026-09-10 inclusive  
**Tracking:** #1336  
**Canonical intake destination:** `docs/OWNER_REQUESTED_TODO.md`  
**Implementation authorization:** unchanged; `docs/EXECUTION_PLAN.md` remains the sole implementation-authorization record.

## 1. Purpose

The owner asked for a semantic recovery of anything said during the two-month window that a reasonable product/engineering lead would interpret as durable future work: add/change/fix/improve/research/preserve/revisit/defer/reject/supersede, including informal wording and implementation-prompt requests. The goal is not to manufacture new scope. The goal is to stop owner intent from disappearing between ChatGPT conversations and repository-visible Astra work.

This audit starts from recovered owner intent, then reconciles it against current repository/GitHub truth. It does **not** treat an issue, PR, old assistant claim, or code existence as proof of product completion.

## 2. Coverage honesty

### Retrievable-context coverage

ChatGPT could retrieve substantial prior-conversation context, dated owner statements, prior assistant outputs, current-conversation text, user-supplied pasted material, and repository/GitHub evidence. The recovery reached at least **31 distinct dated project/topic clusters** across the window, including July product/model work, August owner-backlog decisions, late-August trade/roster additions, and September mobile/Game-Day/Agent-OS/Astra work.

The working census normalized **72 requirement/candidate clusters**: **70 resolved product/process requirements** plus **2 ambiguous candidates** retained for owner review. Because prior-context retrieval summarizes and collapses repeated messages, a literal source-message denominator is not available; the recovered source-fragment count must therefore be treated as a lower-bound rather than a raw-chat count.

### Literal raw-chat coverage

**NO — literal every-chat coverage is not available in this environment.** ChatGPT does not have an account-wide raw conversation-history browser. Raw text is available for the current conversation and any pasted/uploaded transcripts; older conversations may be exposed only as retrieved context/summaries. This audit therefore must not be described as “every raw message from every chat.”

To make a literal two-month audit possible later, provide/export the raw ChatGPT conversation corpus for 2026-07-10 through 2026-09-10 and rerun this document's reverse-audit against that corpus. The durable repository reconciliation below is still useful now because it captures every recoverable definite/high-confidence item found in the available context.

## 3. Repository authority observed

Current repository governance already says:

1. new owner instructions enter `docs/OWNER_REQUESTED_TODO.md` first;
2. detailed specs/issues may carry the long-form contract;
3. canonical product/inventory/manifest records reconcile the requirement;
4. only `docs/EXECUTION_PLAN.md` authorizes implementation.

Astra's current report-only Steward runtime already reads owner intake plus current GitHub/planning/execution evidence. The primary failure mode was therefore **capture fragmentation**, not an absence of an Astra reader: some requests were written only to issues, companion spec indexes, master-plan addenda, or chat responses.

## 4. Recovered requirement census

`Compact ledger?` means whether the requirement was directly discoverable from the live owner-intake file without requiring the reader to know which other planning artifact to inspect. `Mapped elsewhere` is not the same as “lost”; it explains why this pass uses compact bridge pointers rather than duplicating long specs.

| ID | Approx date | Recovered owner intent / normalized requirement | Canonical repo evidence before this pass | Current status / disposition | Compact ledger before pass? |
|---|---|---|---|---|---|
| R-01 | 2026-07-26 | Full-site premium, football/market-style UI/UX; dense-but-calm, fast, coherent, mobile/desktop optimized | Later refined into `PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md` / T-NEW-06 | **REFINED / MERGED INTO PSI** | No direct row |
| R-02 | 2026-07-27 | BDVM/fundamental dynasty value must remain independent from market value and feed roster/trade decisions without double-counting | BDVM/model docs + master product architecture | **PARTIAL / ONGOING PLATFORM FOUNDATION** | No direct row |
| R-03 | 2026-07-27 | Historical snapshots, leakage-safe backtests, uncertainty, versioning, champion/challenger and rollback for valuation/model work | C-series/history/model-governance docs | **REPRESENTED / ONGOING** | No direct row |
| R-04 | 2026-07-31 | Unified Sleeper + FFPC Sharp Tracker; shared normalization/dedupe/source breakdown; no false FFPC Sharp qualification | `docs/intel/FFPC_UNIFIED_SHARP.md`, `src/sharp/service.py` | **IMPLEMENTED**; production evidence governed elsewhere | No direct row |
| R-05 | 2026-08-09 | Reset Podcast Intelligence source inventory from screenshots; retire old active feeds; preserve canonical source identity | Analyst/intelligence specs and current `src/intel` lineage | **PARTIAL** | No direct row |
| R-06 | 2026-08-09 | Feed podcast intelligence into news/Buy-Sell/profiles/rankings/team intelligence while separating fact from opinion and deduping repeated stories | `OWNER_PRODUCT_BACKLOG_SPEC.md`, analyst claim/stance architecture | **PARTIAL / DEPENDENCY-GATED** | No direct row |
| R-07 | 2026-08-09 | Personalized roster-filtered team podcast/brief; roughly 10–20 minutes when warranted and end with five most important team takeaways | Analyst/weekly-report/intelligence plans | **PLANNED / PARTIAL FOUNDATION** | No direct row |
| R-08 | 2026-08-12 | Public `/league` as League Museum + Sports Network + Game Day; private app as Front Office + War Room | `MASTER_PRODUCT_PLAN.md` | **CANONICAL PRODUCT DIRECTION** | No direct row |
| R-09 | 2026-08-12/13 | Canonical owned-future-pick projection/valuation | T-NEW-01 | **PLANNED / FOUNDATION EXISTS** | Companion only |
| R-10 | 2026-08-13 | Multiple identical generic future-pick quantities in Trade Calculator | T-NEW-02 | **PLANNED / PARTIAL** | Companion only |
| R-11 | 2026-08-12 | Public League manual Sleeper Sync + freshness/status/cooldown; refresh current section without full reload | T-NEW-03 | **PLANNED / PARTIAL** | Companion only |
| R-12 | 2026-08-12 | Persistent authenticated top-level League navigation to canonical `/league` on desktop/mobile | T-NEW-04 | **REPRESENTED**; verify current shell behavior before closure | Companion only |
| R-13 | 2026-08-12 | `teamAssignment` missing data must not become zero/false certainty | T-NEW-05 / #815 | **SHIPPED_AND_VERIFIED** in 2026-09-10 replan | Companion only |
| R-14 | 2026-08-12 | Premium Sports Intelligence is the permanent visual north star and must migrate the full product without generic SaaS/AI-dashboard drift | T-NEW-06 + north-star doc | **PARTIAL** (~5/46 full route activations in 2026-09-10 replan) | Companion only |
| R-15 | 2026-08-12 | The Upside Report weekly showcase/storytelling product | T-NEW-07 + report specs | **PLANNED / PARTIAL PRIMITIVES** | Companion only |
| R-16 | 2026-08-12 | One canonical transparent/backtested Weekly Power Rankings engine with weekly movement | T-NEW-08 | **SHIPPED_AND_VERIFIED** | Companion only |
| R-17 | 2026-08-12 | Awards & Honors / MVP-race layer, with compact MVP Watch in weekly report rather than every award race | T-NEW-09 + award/report specs | **REPRESENTED** | Companion only |
| R-18 | 2026-08-12 | Analyst Intelligence: structured attributed stances/takes, provenance, freshness, dedupe/independence and downstream decision use | T-NEW-10 + `OWNER_PRODUCT_BACKLOG_SPEC.md` | **PARTIAL**; persistence/query work remains | Companion only |
| R-19 | 2026-08-14 | Hard B→C reconciliation/replan gate; do not blindly continue stale roadmap | T-NEW-11 / later execution-plan supersession | **SATISFIED / SUPERSEDED BY CURRENT EXECUTION MODEL** | Companion only |
| R-20 | 2026-08-14 | Watchdog infinity/false-negative repair | T-NEW-12 | **DONE** | Companion only |
| R-21 | 2026-08-12–14 | Player Impact / VORP/WAR/WAB/Game Changer | T-NEW-13 | **REAL REMAINING WORK** in 2026-09-10 replan | Companion only |
| R-22 | 2026-08-13/14 | Trade Calculator real-trade database and market-evidence expansion | T-NEW-14 + `TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md` | **PLANNED / PARTIAL** | Companion only |
| R-23 | 2026-08-13/14 | Canonical pick-value completeness through 2029 and cross-surface parity | T-NEW-15 | **REPRESENTED / PARTIAL** | Companion only |
| R-24 | 2026-08-14 | C-series zero-loss deployment/completion contract | T-NEW-16 | **REPRESENTED / PROCESS EVOLVED** | Companion only |
| R-25 | 2026-08-14 | Historical trade replay/as-of roster context for grading old trades | T-NEW-17 | **PLANNED / DEPENDENCY-GATED** | Companion only |
| R-26 | 2026-08-14 | Roster Age-Value Portfolio / Young Core | T-NEW-18 / #838 | **IMPLEMENTED; CLOSE AFTER REQUIRED PROD/acceptance proof** per replan | Companion only |
| R-27 | 2026-08-14 | Meaningful Roster Core based on league-config-derived starter demand, not stale fixed caps | T-NEW-19 / #839 / decision 67 | **IMPLEMENTED; CLOSE AFTER REQUIRED PROOF** | Decision/companion only |
| R-28 | 2026-08-18 | FLEX/SF/IDP-FLEX actual starter assignment happens before reserve/depth selection; every player counted once | #899 / decision 72 | **IMPLEMENTED; CLOSE AFTER REQUIRED PROOF** | Decision only |
| R-29 | 2026-08-11 | `/admin` runtime crash is a real defect | #779 | **IMPLEMENTED**; later verification disposition governed by current contracts | Yes |
| R-30 | 2026-08-11 | Configurable temporary-password/guest-access expiry must work end to end | #780 | **IMPLEMENTED**; later verification disposition governed by current contracts | Yes |
| R-31 | 2026-08-11 | Trade Calculator manual value edits visually silent; top-level Reset Values; removal clears edit state | #781 | **REAL REMAINING** in 2026-09-10 replan | Yes |
| R-32 | 2026-08-11 | YouTube dynasty intelligence extends shared Podcast/Analyst architecture with cross-media dedupe | #782 | **PLANNED / LONGER-TERM** | Yes |
| R-33 | 2026-08-11 | Universal Player Profile consumes one canonical podcast/YouTube/news intelligence feed | #783 | **PLANNED / LONGER-TERM** | Yes |
| R-34 | 2026-08-11 | Homepage SELL ticker only surfaces players on globally selected fantasy team's roster; BUY may be global | #784 | **REAL REMAINING** | Yes |
| R-35 | 2026-08-11 | Audit two-TE/TE-premium valuation against actual source basis and league demand; no double premium | #785 | **PARTIAL / REAL REMAINING** | Yes |
| R-36 | 2026-08-11 | Trade simulation shows canonical-value-weighted NFL-team exposure before/after, informational only | #786 | **PARTIAL — wire existing owner** | Yes |
| R-37 | 2026-08-11 | Future Dynasty X analyst feed is cost-gated and official-API-only | #788 | **LONG-TERM / COST-GATED** | Yes |
| R-38 | 2026-08-11 | Game Day Command Center with exact scoring, best-ball semantics, projections/win probability, leverage/rooting context and calibrated history | #789 / CE-20 | **PLANNED / DEPENDENCY-GATED** | Yes |
| R-39 | 2026-08-11 | Re-audit Trade Calculator Monte Carlo meaning, uncertainty/correlations, convergence and provenance | #790 | **REAL REMAINING** | Yes |
| R-40 | 2026-08-14 | Second Opinions one-glance independent-vendor tally; canonical fallback never becomes external corroboration | #791 | **PARTIAL** | Yes |
| R-41 | 2026-08-11 | One canonical Analyze Trade decision owner (MAKE…PASS) using unique-information dimensions and roster marginal impact | #792 | **REAL REMAINING / FOUNDATION DEPENDENCIES** | Yes |
| R-42 | 2026-08-11 | Equalizer suggestions ranked by post-active-Value-Adjustment gap; no double application | #800 | **REPAIRED / SPECIFIC REPRO VERIFY THEN CLOSE** per replan | Yes |
| R-43 | 2026-08-11 | Establish The Run source plan preserved but no purchase/work until owner resumes | #801 | **PAUSED** | Yes |
| R-44 | 2026-08-11 | Individual player KR/PR/special-teams scoring belongs to actual rostered players, not DST | #802 | **REAL REMAINING** | Yes |
| R-45 | 2026-08-11 | Player-specific exact-league scoring fit + cautious college/prospect translation; separate from market/scarcity value | #803 | **PLANNED / DEPENDENCY-GATED** | Yes |
| R-46 | 2026-08-14/20/09-07 | Weekly Report Studio defaults to Manual External AI, provider-neutral structured import, zero site-side LLM spend in that mode, deterministic graphics; later include current NFL/news/story context | #829 + weekly-report architecture | **PLANNED / LONGER-TERM** | Yes |
| R-47 | 2026-08-14 | FAAB Market Heat + normalized own/Sharp/broad-market winning-bid evidence on original-budget percentage basis | #830 | **PLANNED** | Yes |
| R-48 | 2026-08-14 | Best Trade to Send Each Team + persistent generated-package LOCK/EXCLUDE + generalized outgoing protection; latest topology permits picks when strategically valid and <=1 player-count difference | Master plan + trade-generation supersession specs | **PLANNED / REAL REMAINING** | **No direct row** |
| R-49 | 2026-08-14 | Owner overlay: Vikings effectively untouchable outgoing; implement as generalized user/league exclusion control, not global value mutation | `MASTER_PRODUCT_PLAN.md` owner overlay + trade specs | **PLANNED** | **No direct row** |
| R-50 | 2026-08-14 | Competitive Posture | #840 | **OWNER_DECISION_REQUIRED**: hard labels vs continuous current design | **No direct row** |
| R-51 | 2026-08-14 | Trade Finder / generated trades may use draft picks when both teams' strategic posture makes them mutually beneficial | #841 | **REAL REMAINING** | **No direct row** |
| R-52 | 2026-08-14 | Use Team Context toggle / team-aware trade evaluation behavior | #842 | **REAL REMAINING** | **No direct row** |
| R-53 | 2026-08-14 | Canonical Roster Capacity / forced-drop economics | #843 | **PARTIAL; CANONICAL-OWNER CONSOLIDATION REQUIRED** | **No direct row** |
| R-54 | 2026-08-15 | Mathematical/model-calibration policy: measured vs mechanical vs prior; challenger testing; no magic-number promotion by feel | compact owner row + calibration doc | **PLANNED / CROSS-CUTTING** | Yes |
| R-55 | 2026-08-15 | Multi-source weekly/ROS/season projection ensemble, offense + IDP, raw stats rescored under exact league rules, archived before outcomes | #854 | **PLANNED / LONGER-TERM** | Yes |
| R-56 | 2026-08-20 | Source-acquisition/cross-position bridge: Draft Sharks, Dynasty Dealer/Nerds discovery, IDP Show/Footballguys where authorized; preserve raw cross-position evidence and avoid artificial IDP=9999 ceilings | `docs/sources/*`, execution/source lanes | **PARTIAL; some vendors AUTH_REQUIRED** | **No direct row** |
| R-57 | 2026-08-20 | DynastyStats-derived League Hub/Pulse, League Asset Map, Transaction Intelligence, Manager Scout enrichment and related league-entry/presentation ideas | #985 | **LONG-TERM / POST-V1** | **No direct row** |
| R-58 | 2026-08-23 | Every actionable player name site-wide should open canonical Universal Player Profile / Player File through one shared identity-safe link primitive | recovered chat; 2026-09-10 replan says link centralization NOT_STARTED; now #1337 | **NOT STARTED** | **No direct row** |
| R-59 | 2026-08-29 | Roster-conditional dynasty best-ball utility for Analyze Trade without changing standalone canonical player values | #1173 + owner addendum | **REAL REMAINING / dependency-gated on #792** | **No direct row** |
| R-60 | 2026-09-02 | Fix iOS standalone-PWA top safe-area overlap that made team selector inaccessible; 44px controls and real-iPhone verification | PR #1219 | **IMPLEMENTED; real-device post-deploy proof was explicitly outstanding in PR** | No active row needed; audit provenance only |
| R-61 | 2026-09-03 | Hill v2 remains champion for 2026 launch; re-evaluate after real Week 3 evidence, outcome not pre-decided | decision 73 | **SCHEDULED FUTURE REVIEW / V2-SEASON FOLLOW-UP** | Yes (decision) |
| R-62 | 2026-09-03 | Genuine future-state-only verification may move to explicit V2/season debt; exact proof/trigger must remain; admin guest-access L4 proof moved accordingly | decisions 74–75 | **V2 VERIFICATION DEBT POLICY** | Yes (decisions) |
| R-63 | 2026-09-05/06 | Replace giant per-agent continuation prompts with one model-neutral Agent OS/startup/receipt/parity harness and durable repo context | `AI_INSTRUCTIONS.md`, `AGENT_OPERATING_SYSTEM.md`, shared startup/receipt machinery | **IMPLEMENTED** | Process docs, not product row |
| R-64 | 2026-09-08/10 | Site Steward/Astra coordination: durable campaign state, combined planning, routing and evidence; bounded report-only runtime first; unattended/merge/deploy authority remains separate | Steward vision/architecture/runtime | **BOUNDED RUNTIME IMPLEMENTED; FUTURE UNATTENDED ACTIVATION DEFERRED** | Process docs |
| R-65 | 2026-09-09/10 | When automated unrelated commits move `main`, prove/classify benign movement and do not restart unaffected CI from scratch | `ASSISTANT_COORDINATION.md`, Agent OS/AI instructions | **IMPLEMENTED PROCESS RULE** | Process docs |
| R-66 | 2026-09-09/10 | Reconcile TODO/backlog into combined phases that share foundations and minimize repeated subsystem touching | `BACKLOG_REPLAN_2026-09-10.md` | **IMPLEMENTED PLANNING OVERLAY** | Process/planning doc |
| R-67 | 2026-09-09 | Game Day NFL slate remains in real kickoff order with both fantasy sides' players grouped under each real NFL game | PR #1320 | **SHIPPED_AND_VERIFIED** in replan | Not needed as active row; audit provenance |
| R-68 | 2026-09-10 | Data-heavy performance architecture follow-through: trace real request paths, precompute/materialize expensive work, refresh asynchronously, measure before adding infrastructure | existing global performance standard + now #1338 | **NEW RESEARCH/FOLLOW-THROUGH** | **No direct row** |
| R-69 | 2026-09-10 | One canonical globally selected fantasy team across site; Game Day follows it; keep NFL slate chronological but emphasize games by selected-matchup projected fantasy-point impact | #1334 | **PLANNED / NEW OWNER SCOPE** | **No direct row** |
| R-70 | 2026-09-10 | Game Day UX overhaul: compact matchup hero, what-matters-now, NFL slate primary, progressive disclosure, collapse diagnostics/provenance, mobile-first scannability | #1335 | **PLANNED / NEW OWNER SCOPE** | **No direct row** |
| R-71 | 2026-09-10 | Every durable chat-derived owner request must flow into live owner intake before an agent claims “added”; issue alone is insufficient; Astra sees intake during reconciliation; capture != authorization | #1336 + this audit | **PROCESS REPAIR IN PROGRESS** | **No direct row** |
| R-72 | 2026-08-12 | Global performance is a product requirement: warm useful state ~1s, normal p95 ~2s where feasible, cold ~3s, 5s absolute failure ceiling, compute before click | `GLOBAL_PERFORMANCE_STANDARD.md` | **CANONICAL STANDARD; EXISTING SITE REPAIR CONTINUES** | No direct row |

## 5. Ambiguous candidates retained for owner review

These were intentionally **not** promoted into binding product scope by this recovery pass.

| Candidate | Why ambiguous | Current disposition |
|---|---|---|
| A-01 — individual offensive-lineman fantasy scoring / observability research | The owner explored how OL could be scored/ranked if every stat were available. Available context does not prove this was an instruction to add OL to Chase Upside's production product or current league scoring. | **AMBIGUOUS — do not add as active scope without owner confirmation.** If later approved, preserve the distinction between observed OL metrics and actual league scoring support; do not invent points. |
| A-02 — Fantrax migration contingency | The owner researched migration away from Sleeper and what a test migration would need to preserve. Available context reads as platform-contingency research rather than a directive to build a Fantrax integration now. | **DEFERRED/AMBIGUOUS — research provenance only.** Do not build unless owner explicitly activates migration work. |

## 6. Confirmed “claimed added, but not in the compact live intake” incidents

This is the failure mode that triggered the audit. The following are confirmed from retrievable context/repo comparison; the list is a **lower bound** because literal raw-chat history is unavailable.

1. **Analyst Intelligence** — owner explicitly said add to TODO; assistant said added. Durable detail exists as T-NEW-10/backlog spec, but no direct compact intake row.
2. **The Upside Report** — owner explicitly said add; assistant said added. Durable detail exists as T-NEW-07/specs, but no direct compact intake row.
3. **Canonical Weekly Power Rankings** — owner explicitly said add; assistant said added. Durable detail exists as T-NEW-08 and is now shipped, but no direct compact intake row.
4. **Premium Sports Intelligence north star** — owner explicitly required canonical roadmap/backlog preservation. Durable detail exists in T-NEW-06/north-star doc, but the compact intake required a reader to know the companion path.
5. **Authenticated Public League Navigation** — owner said add; assistant said added. Durable detail exists as T-NEW-04, not a direct compact row.
6. **Sleeper Manual Sync / League Freshness** — owner said add; assistant said added. Durable detail exists as T-NEW-03, not a direct compact row.
7. **Generic future-pick quantities** — owner said add; assistant said added. Durable detail exists as T-NEW-02, not a direct compact row.
8. **KTC-inspired Trade Calculator expansion** — owner instructed that every approved screenshot-derived feature be added to the master backlog. It was durably specified, but not directly indexed from the compact intake.
9. **Best Trade + LOCK/EXCLUDE generated-package controls** — owner explicitly requested persistence into all master TODOs; detailed trade specs/master plan exist, compact intake did not directly point to the requirement.
10. **#1334 selected-team/Game-Day-impact requirement** — ChatGPT said it was added to the repo backlog; it existed as an issue but was not yet in the live owner-intake ledger.
11. **#1335 Game Day UX overhaul** — ChatGPT said it was added; it existed as an issue but was not yet in the live owner-intake ledger.

None of items 1–9 were “lost from the repository” in the same way; most were safely preserved in companion specs. The defect is that the owner's mental model (“the master TODO”) and the repository's fragmented intake representation did not match. #1334/#1335 exposed the problem clearly because they were issue-only.

## 7. Backfill actions from this audit

The live owner intake should gain a compact **recovery bridge** rather than duplicate every long-form spec. The bridge must:

- explicitly incorporate T-NEW-01…T-NEW-19 by reference;
- point to the already-canonical trade/BDVM/podcast/Public-League families recovered from chats;
- add direct pointers for #840–#843, #985, #1173, #1337, #1338, #1334, #1335 and #1336;
- carry the latest Best Trade/LOCK/EXCLUDE topology rather than the superseded players-only/equal-count wording;
- carry the generalized user/league outgoing-protection requirement rather than hard-coding Vikings globally;
- preserve source-acquisition/cross-position work as one source-platform lane rather than creating duplicate source engines;
- state clearly that capture is durable scope intake, **not implementation authorization**.

## 8. Permanent process repair

Model-neutral agent instructions must enforce:

> If the owner expresses durable future work — including informal “add/fix/change/revisit/later/make this better” wording — the agent must classify whether the statement creates/changes/pauses/rejects durable scope. If yes, ensure it is represented in `docs/OWNER_REQUESTED_TODO.md` directly or through an explicit compact incorporation pointer to a detailed issue/spec. Do not claim “added,” “saved,” or “on the TODO” merely because it exists in chat or only in an issue. Capture does not authorize implementation; `docs/EXECUTION_PLAN.md` still controls execution.

Astra/Steward already reads owner intake and current GitHub/planning state. Therefore the required system behavior is:

`owner statement -> durable owner intake -> detailed issue/spec if needed -> canonical mapping -> execution plan when authorized -> Astra reconciliation`

not:

`owner statement -> assistant says “added” -> hope a later agent sees the chat`.

## 9. Combined-phase placement after reconciliation

This audit does not create a second roadmap. New/recovered active items should be folded into the existing 2026-09-10 combined backlog plan approximately as follows:

- **Shared UI/context lane:** #1334 global selected-team state + #1335 Game Day hierarchy + #1337 player-link centralization + remaining PSI migration, sharing shell/state/design-system work where safe.
- **Game Day/projection lane:** #1334 impact scoring + #1335 slate UX consume #789/CE-20 and #854 projection/scoring owners; preserve chronological NFL order from shipped #1320.
- **Trade/roster lane:** #840–#843 + #1173 + Best Trade/LOCK/EXCLUDE consume canonical Team Strength/Weakness/lineup/capacity systems; resolve duplicate owners before extension.
- **Source/intelligence lane:** source-acquisition/cross-position work + Analyst/Podcast/YouTube/UPP intelligence use one source/claim/provenance architecture.
- **Performance lane:** #1338 reconciles measured request-path work against the existing global performance standard and should be applied to each affected product phase instead of spawning a disconnected infrastructure rewrite.
- **Process lane:** #1336 owner-intake bridge is governance/coordination only; it must not become product-feature execution authority.

## 10. Reverse audit

### PASS A — recovered context -> requirement

**PASS for every definite/high-confidence item recovered in the available context.** Each resolves to an active, completed, superseded, paused, or process requirement above. The two uncertain items are explicitly retained in §5 rather than silently discarded.

### PASS B — requirement -> provenance

**PASS at the available-evidence level.** Every resolved row maps to either recovered dated chat context and/or a durable repository issue/spec/decision. Literal raw-chat provenance remains incomplete where only summarized prior context is available.

### PASS C — active requirement -> owner intake

**FAILED before this pass.** T-NEW companion rows, #840–#843, #985, #1173, #1334/#1335, site-wide player links and other durable items were not all directly discoverable from the compact live intake. The recovery-bridge update is the repair.

### PASS D — owner GitHub issue -> owner intake

**FAILED before this pass for multiple owner-driven issues.** #1334/#1335 were the clearest current examples. The bridge explicitly maps known owner issues while leaving generated maintenance issues outside product-intake semantics.

### PASS E — “added” claim audit

**11 confirmed incidents** are listed in §6. This is a lower bound, not a claim of literal raw-chat completeness.

### PASS F — duplicates

**PASS after normalization.** The recovery bridge uses pointers to existing specs rather than cloning long requirements. Later refinements win: e.g. Best Trade topology uses posture-aware picks and <=1 player-count difference; FLEX ordering uses #899; old UI vision is merged into PSI.

### PASS G — supersession

**PASS for recovered known supersessions.** Notable examples: old fixed meaningful-core caps -> #839; “FLEX after dedicated cores” -> #899; early generic UI direction -> PSI; old continuous-C numbering/freeze details -> current execution plan/backlog replan; Best Trade players-only/equal-count topology -> later posture-aware pick topology.

### PASS H — execution authority

**PASS.** This recovery does not authorize building recovered product items. `docs/EXECUTION_PLAN.md` remains controlling.

## 11. Measurable recovery report

- Date range: **2026-07-10 -> 2026-09-10**
- Distinct dated prior-conversation/topic clusters recovered: **at least 31** (summary-context count, not raw-chat count)
- Literal raw conversations fully enumerable: **NO / denominator unavailable**
- Normalized requirement/candidate clusters recorded: **72**
- Resolved definite/high-confidence requirements: **70**
- Ambiguous owner-review candidates: **2**
- Confirmed claimed-added-but-not-compactly-persisted incidents: **11 (lower bound)**
- Requirements already represented somewhere in durable repo evidence before this pass: **the large majority**; the primary defect was fragmentation rather than total loss
- Completely new durable tracking created by this pass: **#1336 owner-intake recovery/process, #1337 universal player-link requirement, #1338 performance follow-through**
- Current issue-only requirements that required live-intake backfill: **#1334 and #1335**
- Remaining unexplained recovered requirements after bridge reconciliation: **0 among definite/high-confidence items recovered from available context**
- Canonical live owner intake: **`docs/OWNER_REQUESTED_TODO.md`**
- Astra/Steward can read that intake during campaign reconciliation: **YES**
- Current execution authorization changed: **NO**
- Literal every-chat coverage: **NO** — raw export/transcripts are required for that stronger claim

## 12. What a future raw-chat export should do

When a full ChatGPT export becomes available, do **not** restart product planning from scratch. Use this audit as a baseline and run only the missing proof:

1. enumerate every raw conversation/message in the window;
2. semantically extract candidate owner intent;
3. diff it against R-01…R-72 and the then-current live intake;
4. add only genuinely missing/refined/superseding owner statements;
5. update the claimed-added incident count from a lower bound to an exact raw-chat count;
6. keep the current canonical issue/spec mappings wherever the raw transcript confirms them.

That converts this best-effort high-recall reconstruction into a literal every-message audit without duplicating already recovered work.
