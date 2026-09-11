# Combined-Phase Backlog Replan — 2026-09-10

**Status:** Canonical combined-phase sequencing overlay. This document does **not**
replace `docs/EXECUTION_PLAN.md` (sole authorization record), `docs/MASTER_PRODUCT_PLAN.md`
(product hierarchy), `docs/C_SERIES_SCOPE_MANIFEST.md` (full 163-row requirement census),
or `docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md` (zero-loss mapping proof). It sits **above**
them as the "which shared foundation unlocks which features, in what combined order"
layer that those documents do not themselves provide. Where this document's reconciled
disposition for an item differs from an older doc's last-recorded status, this document
wins for **sequencing purposes only** — it is evidence-based (current code + current
issues), not a new product/methodology decision. No item is deleted from the manifest;
this is a pointer-and-correction layer, not a duplicate roadmap.

Produced per owner directive "COMBINED TODO / BACKLOG EXECUTION REPLAN." Method: fetched
current `main`, read all cited planning docs in full, read all 52 open GitHub issues,
read the last 60 merged/closed PRs, and verified actual code state for every platform
grouping the directive named as a likely combination opportunity, via four parallel
research passes. No code was changed to produce this document.

**Starting SHA:** `b69455136b80cd1c3cd29ef44a24799c48cc3793` (origin/main, 2026-09-10).

**Bounded infrastructure update, 2026-09-10:** the later owner-authorized Astra
consolidation implements the local report-only runtime at `src/steward/`.
This supersedes this document's architecture-only/missing-runtime statements
for that bounded capability. See `docs/agent-operating-system/STEWARD_RUNTIME.md`
and current tests/integration evidence. Phase 9's remaining dispatcher/census
work and future unattended activation are separate; no product phase or launch
acceptance is promoted by this update.

---

## 0.5. Execution-coordination reconciliation — 2026-09-10 (post-#1328)

A second, broader directive ("take over execution coordination, get the
project back on track") reconciled main again a few hours after this
document's PR (#1328) merged. New SHA verified: `3c49946940748e476d17ffff57
dbd742ecbff730`. Zero open PRs at that point. This section is the compact
master status matrix the directive requires — one table an owner can scan to
answer "what shipped, what looks shipped but isn't, what's in flight, what's
blocked by real-world timing, what's next." It supersedes stale specifics in
§1-§3 above where they conflict (e.g. #839/#899/#838/#843 status, the
freeze-supersession framing) without re-litigating them — see the classes
below for the reasoning.

**Reconciliation classes used**: `SHIPPED_AND_VERIFIED`,
`SHIPPED_NEEDS_PRODUCTION_CHECK`, `PARTIAL`, `CLOSED_UNMERGED_REAL_WORK`,
`SUPERSEDED_DO_NOT_RESURRECT`, `NOT_STARTED`, `TEMPORALLY_BLOCKED`,
`OWNER_DECISION_REQUIRED`.

| Initiative | Status | Canonical owner | Source | Next action |
|---|---|---|---|---|
| Power Rankings (canonical blend + weekly share card) | SHIPPED_AND_VERIFIED | `src/ros/power_v2.py`, `power_snapshots.py` | #1295, #1286, #1321 (incident, repaired) | None — frozen, do not touch methodology absent a real regression |
| Game Day NFL slate (kickoff-ordered, players grouped by game) | SHIPPED_AND_VERIFIED | `frontend/components/GameDayPanel.jsx` (`NflSlateSection`), `src/ros/game_day_week.py` | #1320 | None — frozen |
| KTC/DLF three-signal valuation architecture | SHIPPED_AND_VERIFIED | `src/sources/ktc_value_sources.py` | #1297 | None — frozen; genuine remaining drift tracked separately (#1322/#898/#1065/#785) |
| Hill Autopilot v2 (auto-refit/tournament/board-impact-gate) | SHIPPED_AND_VERIFIED | `src/model_registry/autopilot.py`, `hill_masters.py`, `versioning.py` | #1315 | None — frozen. **#1290 SUPERSEDED_DO_NOT_RESURRECT** (zero code trace, never merged) |
| FAAB Stage 1 shadow logging | SHIPPED_AND_VERIFIED | `src/api/feature_flags.py` (`waiver_live_opportunity`), `src/trade/faab_shadow.py` | #1313 | None — frozen. **#1217 SUPERSEDED_DO_NOT_RESURRECT** (zero code trace, never merged) |
| Admin `fmtPassExpiry` crash | SHIPPED_AND_VERIFIED | `frontend/lib/guest-pass-format.js` | #779 | **Closed 2026-09-10** with evidence (`tests/e2e/specs/admin-guest-pass.spec.js`) |
| Temp-password expiry | SHIPPED_AND_VERIFIED | `src/api/guest_passes.py` | #780 | **Closed 2026-09-10** with evidence |
| `/league` `teamAssignment` degraded-as-200 | SHIPPED_AND_VERIFIED | `src/api/team_assignment.py` | #815 | **Closed 2026-09-10** with evidence (`tests/api/test_team_assignment_availability.py`) |
| Mobile drawer (#1153) | SHIPPED_NEEDS_PRODUCTION_CHECK → verifying | `frontend/components/shell/MobileChrome.jsx`, `ds/Dialog.jsx` | #1153, V1-131 | Added local (non-prod-auth) regression coverage 2026-09-10 (`tests/e2e/specs/mobile-smoke.spec.js`); see its actual pass/fail result before closing #1153 |
| Week 1 launch contract deadline/evidence-window text | PARTIAL → corrected | `docs/season-launch/WEEK_1_LAUNCH_CONTRACT.md` | directive 2026-09-10 | Corrected 2026-09-10 (docs only, acceptance criteria unchanged) |
| W1-27 (Game Day LIVE) | SHIPPED_AND_VERIFIED (2026-09-11) | `src/ros/game_day_week.py`, `tests/e2e/specs/prod-auth/w1-16-game-day.spec.js` | W1-27 | Done — real production evidence captured during Thu 2026-09-10 20:35 ET SF@LA window, run [34548330201](https://github.com/jasonleetucker-code/riskittogetthebrisket/actions/runs/34548330201). Incidentally surfaced 2 unrelated production defects, tracked separately: #1157 (roster-percentage timeout) and #1340 (Team Strength page timeout, new) |
| W1-28 (Game Day FINAL) | TEMPORALLY_BLOCKED | same instrument, §6 of the runbook | W1-28 | Cannot be evidenced before Week 1's real conclusion, Mon 2026-09-14 20:15 ET |
| W1-30 (final launch-tree verification) | NOT_STARTED, depends on W1-27/28 | §7 of the runbook | W1-30 | Execute once W1-27 and W1-28 are both real |
| Site Steward Phase 1 runtime | CLOSED_UNMERGED_REAL_WORK | none yet — architecture only (`docs/AUTONOMOUS_SITE_STEWARD_VISION.md`, `docs/autonomy/SITE_STEWARD_ARCHITECTURE_2026-09-08.md`, `config/steward/contracts.schema.json`) | #1318 (closed unmerged), #1291 (architecture, merged) | Rebuild cleanly from current main once Week 1 = 30/30 — do not resurrect #1318's branch |
| Analyst claim/evidence ledger persistence | CLOSED_UNMERGED_REAL_WORK | `src/analyst/claim.py`, `stance.py` (schema only) | #980 (closed unmerged) | Real remaining work: build `store.py`/`query.py` on the existing schema, as the foundation Analyst/Intelligence Platform phase needs first |
| Realized VORP/WAR/WAB/Game Changer | CLOSED_UNMERGED_REAL_WORK | `src/scoring/replacement_level.py` (reusable primitive), `public_league/awards.py` (differently-scoped VORP) | #969 (closed unmerged) | Real remaining work: build the full core on `replacement_level.py`, do not extend `awards.py`'s award-scoped VORP in place |
| Central Buy/Sell Reconciler + market-ticker contract | CLOSED_UNMERGED_REAL_WORK | not yet verified this pass | #970 (closed unmerged) | Re-derive from current main when the Analyst/Intelligence Platform phase reaches it — do not resurrect the closed branch |
| Roster capacity duplicate ownership | OWNER_DECISION_REQUIRED (methodology, not a build gap) | `src/trade/roster_capacity.py` vs `src/roster_intel/droppability.py`/`marginal.py` | #843 | Consolidate onto one owner before further extension |
| Team Strength duplicate ownership | OWNER_DECISION_REQUIRED | `src/roster_intel/strength.py` vs `src/ros/team_strength.py` | (no issue filed) | Consolidate onto one owner before further extension |
| Competitive Posture hard labels vs. continuous design | OWNER_DECISION_REQUIRED | `src/roster_intel/window.py` (deliberately non-labeled) | #840 | Genuine methodology conflict — needs an explicit owner ruling, not a silent pick either way |
| PSI full-site migration | PARTIAL (~5/46 routes fully activated) | `frontend/components/ds/` (primitives exist) | T-NEW-06 | Migrate remaining ~37 routes by route family using existing `ds/` primitives; do not redesign primitives |
| Universal Player File link centralization | NOT_STARTED | `/players/[playerId]` (canonical destination exists) | owner standing UX requirement | Audit every player-name render surface, centralize through one shared player-link component |

Everything not listed above keeps its disposition from §4 (the reconciled
backlog table) and §3 (stale-manifest corrections) unchanged.

---

## 0. Authority reconciliation (read this before anything else)

Two of the canonical C-Series documents contain text that is **stale relative to
`docs/EXECUTION_PLAN.md`**, which every other document (including those two) names as
the sole current authorization record. This matters because a mechanical reading of the
freeze language would tell a future agent to stop work that the owner has since
explicitly re-authorized.

- `docs/C_SERIES_EXECUTION_MAP.md` §18 declares a **2026-08-17 feature freeze**: only the
  post-merge C-Series audit/stability-gate repairs are authorized; `C2-U2`, `C2-U3`,
  `C2-U4`, `C2-U6`, `C1-U7`, and every `C3+` unit are named not-to-be-begun; the
  continuous C-Series campaign is "paused, not cancelled," resuming only on a fresh
  owner decision recorded in `EXECUTION_PLAN.md`.
- `docs/EXECUTION_PLAN.md` (reconciled **2026-08-20**, three days later) is that fresh
  owner decision. It authorizes, concurrently: (a) the V1 Completion Sprint; (b) seven
  parallel product lanes (Lane 1 Roster, Lane 2 Trade — which is C3-scope work under a
  different name, Lane 3 Season/Scoring, Lane 4 Market/FAAB/Analyst, Lane 5 Integration,
  Lane 6 Premium UI, Lane 8 Source Acquisition); (c) a **POST-V1 C-Series mass-build
  campaign** letting Claude 9–13 implement real C3–C10 work on isolated branches ahead of
  V1 closing (merge to `main` withheld until V1 closes, not implementation itself); (d) a
  bounded first PSI production migration.
- `docs/OWNER_REQUESTED_TODO.md` decisions 73–76 (**2026-09-03**) and the merged Hill
  Autopilot v2 work (**2026-09-09**, PR #1315, an explicit owner-confirmed exception to
  the human-approval invariant) show continued live owner engagement well past both the
  08-17 freeze and the 08-20 re-authorization.

**Reconciled conclusion:** the 08-17 raw C-numbering freeze is **superseded** by the
08-20 lane-based authorization and subsequent owner decisions. `EXECUTION_PLAN.md`
remains controlling. This replan is written against the **lane + POST-V1-campaign**
authorization state as it stands today, not the frozen C-numbering. `C_SERIES_EXECUTION_MAP.md`
§18 is marked HISTORICAL/SUPERSEDED-BY-EXECUTION_PLAN below (§7) — its content is kept
for traceability, not deleted.

A second, narrower authority note: `docs/VERSION_1_COMPLETION_CONTRACT.md` reports
**132/132 (100%) V1 REQUIRED complete**, with four items (V1-49, V1-83, V1-101, V1-102)
moved to explicit V2 verification debt by owner decision. The still-active document is
`docs/season-launch/WEEK_1_LAUNCH_CONTRACT.md` (a **different**, later-created 30-row
gate, not the same denominator as V1): **27/30 VERIFIED**, with W1-27 and W1-28
`IMPLEMENTED_UNVERIFIED` and W1-30 `NOT STARTED` (§1 below). Do not conflate "V1 complete"
with "Week 1 launch gate complete" — they are two different fixed-denominator contracts
and both remain governing while open.

---

## 1. Verified current state vs. the mission's "verify, don't assume" checklist

| Claim | Verified reality |
|---|---|
| Formal V1 appears complete | **Confirmed.** 132/132, 100%. Do not reopen (contract §10 boundary). |
| Week 1 launch contract near completion | **Confirmed, 27/30 (90%).** Three open rows: W1-27, W1-28 (`IMPLEMENTED_UNVERIFIED`, real-game-window evidence outstanding — W1-28's FINAL-state evidence is temporally unreachable before the contract's own deadline and needs an owner deadline decision, not more engineering), W1-30 (`NOT STARTED`, final tree verification, blocked on W1-27/28). |
| Significant Game Day functionality already implemented | **Confirmed.** `src/ros/game_day_sim.py`, `game_day_week.py`, `game_day_capture.py`, `playoff_sim.py` are mature and actively edited (matchup-slate PR #1320 merged 2026-09-09). |
| Power Rankings substantially rebuilt | **Confirmed.** PR #1295 (merged) built canonical blended Power Rankings + weekly share card on `src/ros/power_v2.py`; PR #1286 added live team-strength fallback/progressive eligibility. |
| PSI/Chase Upside migration advanced across multiple routes | **Confirmed but smaller than it reads.** Only 5 of 46 `page.jsx` routes (~11%) carry the `psi-editorial` activation class (`/`, `/login`, `/trade`, `/rankings`, `/players/[playerId]`). A further ~4 routes (`/phases`, `/market/sharp-tracker`, `/market/sharp-people`, `/league` primitives) adopted `ds/` components without full visual activation — the PR authors themselves distinguish these two states. ~37 routes are unmigrated. CLAUDE.md's "~38 pages" count is stale; actual count is 46. |
| Universal Player Profile / Player File advanced | Player-file route exists and carries PSI activation; a dedicated **unified intelligence feed** (podcasts+YouTube+news) onto it (#783) is **not built** — `src/intel/` (podcast ingestion+ledger) is mature and could feed it, but no consumer wires that in yet. |
| Trade UI work advanced | **Confirmed** — `/trade` migrated to PSI (#1294), `BdvmTradePanel.jsx`/`RosTradeFitPanel.jsx` live. |
| Hill Autopilot/curve work advanced | **Confirmed, v2 is live.** `src/model_registry/autopilot.py`, `hill_masters.py`, `versioning.py`, `docs/valuation/HILL_AUTOPILOT_V2.md` all exist and match CLAUDE.md's stated rule. Auto-refit-on-refresh, tournament gate, board-impact gate, auto-promotion for OFFENSE only. Issue #1322 is a **live, legitimate** auto-filed blocker from this pipeline (not stale); #895 and #777 (older manual-promotion "challenger cleared" reports) **are stale**, superseded by v2's automatic path — safe to close. |
| KTC/DLF valuation-source work advanced | **Confirmed** — PR #1297 (merged, "repair DLF source semantics and prepare KTC three-signal cutover") is recent and large. Issue #1005 (DLF/bridge integrity drift) plausibly closed by it but not code-confirmed — flagged NEEDS-CONFIRMATION, not auto-closed. |
| Site Steward/Agent OS architecture advanced | **Partially confirmed — architecture only, no runtime.** `docs/AUTONOMOUS_SITE_STEWARD_VISION.md` and `docs/autonomy/SITE_STEWARD_ARCHITECTURE_2026-09-08.md` merged via #1291; `config/steward/contracts.schema.json` exists. **`src/steward/` does not exist** — PR #1318 ("report-only evaluation and telemetry foundation") is **closed but never merged**. Do not credit any Steward runtime as shipped. |
| Some open issues stale despite v1-required label | **Confirmed, multiple concrete cases** (see §3 and §4): #839/#899 (meaningful roster core) is already implemented verbatim in `src/roster_intel/core.py`; #838 (Young Core Index) is already implemented in `src/roster_intel/age_portfolio.py`; #843 (roster capacity) is built at the trade layer but has a duplicate-owner problem, not a missing-feature problem; #800 (VA-aware equalizer) reads as already fixed per CLAUDE.md's documented 0/4000-miss repair. |
| Old C-Series manifest statuses may be pre-implementation | **Confirmed** — see §3 correction table. Several `ABSENT` manifest rows are now built. |

**Important negative finding not in the mission's checklist:** several PRs that *read* as
completed features are **closed without merging** — their code does not exist on `main`
despite detailed PR bodies describing finished work. Confirmed unmerged-but-closed:
**#980** (Analyst claim/evidence ledger persistence), **#969** (C5-WAR-01 Realized
VORP/WAR core), **#1318** (Steward telemetry runtime), **#1290** (an earlier Hill
Autopilot v2 draft, superseded by the version in #1315 which *did* merge), **#1217**
(FAAB Live Opportunity Stage 1 draft, superseded by #1313 which *did* merge). Any future
session must check `merged:true`, not `state:closed`, before crediting a PR's claims.

---

## 2. Platform-by-platform shared-foundation survey

Per-platform "does it exist, where, how mature" findings, condensed. This is what powers
the combined-phase groupings in §5 — the point is not to relist every file, it's to show
which features already share a canonical owner (combine trivially) vs. which have a
duplicate-owner risk (must be consolidated, not extended in place) vs. which are
genuinely greenfield (real new-build work).

### 2.1 Trade Decision Platform
Mature core: `src/trade/suggestions.py`, `finder.py`, `ktc_va.py`, `roster_capacity.py`,
`faab_engine.py`, `monte_carlo.py`, `correlation_matrix.py`, `analyze_trade.py`,
`comparable_trades.py`, `market_trade_ledger.py`. Frontend: `BdvmTradePanel.jsx`,
`RosTradeFitPanel.jsx`, `TradeSourceBreakdown.jsx`, migrated `/trade` route.
**Duplicate-owner risk, confirmed live:** roster-capacity/forced-drop logic exists in
*both* `src/trade/roster_capacity.py` (the CLAUDE.md-documented canonical owner) *and*
`src/roster_intel/droppability.py` + `marginal.py`. NFL-team exposure exists in
`src/roster_intel/exposure.py`; issue #786 asks for a *new* one in the trade simulator —
it must consume the existing owner, not mint a second. **Genuinely missing:** "Best Trade
to Send Each Team," "Package Builder," "Negotiation Coach," "Trade Desk" — zero code hits
anywhere; these are pure planning-doc concepts today (CE-05 Trade Desk, C7-BEST-TRADE,
C7-PKGB-01 in the manifest). Competitive Posture exists as `src/roster_intel/window.py`
(`CompetitiveWindow`, `trajectory_score`) but *deliberately avoids* hard PUSH/HOLD/RETOOL/
REBUILD labels ("a label picks a side without saying it was close") — issue #840 wants
exactly those hard labels. **This is a live methodology disagreement between existing
code and an open owner-authored issue, not an implementation gap** — flagged as
NEEDS-OWNER-DECISION in §4, not silently resolved either direction.

### 2.2 Analyst/Intelligence Platform
Mature: `src/intel/` (crawler.py, ledger.py, platform_ledger.py, service.py, signals.py,
leads.py — Podcast Intelligence ingestion architecture, ~38–79KB files). Schema-only:
`src/analyst/claim.py`, `stance.py`. **Missing despite PR effort:** persistence/as-of
query layer for the analyst ledger (#980 closed unmerged — the schema exists, the store
does not). **Genuinely missing:** YouTube ingestion (#782), unified player-profile feed
consumer (#783), homepage ticker (#784), Manager Scout (no module at all), Weekly Report
Studio (#829). `src/consensus_edge/` exists as a separate, more mature concept.

### 2.3 Projection/Scoring/Game Day Platform
Mature: `src/bdvm/` (28 files — fundamentals engine), `src/ros/lineup.py` (the single
exact-assignment lineup owner per CLAUDE.md's C2-U1 record), `game_day_sim.py`,
`game_day_week.py`, `playoff_sim.py`, `power_v2.py`, `team_strength.py`,
`src/scoring/replacement_level.py`. **Confirmed gap matching the open issue exactly:**
`src/ros/projection_ensemble.py` exists but per #854 it carries `projection_value`
without consuming it — the issue's description of the gap is accurate, not stale.
**Missing despite PR effort:** Realized VORP/WAR core (#969/C5-WAR-01 closed unmerged;
`src/public_league/awards.py` has an existing, differently-scoped VORP calc that floors
at 0 — not the same thing). **Duplicate risk:** Team Strength in both
`src/roster_intel/strength.py` and `src/ros/team_strength.py` — needs reconciliation
before either is extended.

### 2.4 Trade/Market Evidence Platform
`comparable_trades.py` (150 lines) and `market_trade_ledger.py` (167 lines) both exist
but are thin relative to the CE-01/CE-18 vision (Trade Trees/Asset Lineage, full Market
Trade Ledger). Second Opinions has a per-vendor breakdown component
(`TradeSourceBreakdown.jsx`) but not the "quick winner tally" #791 asks for.

### 2.5 Roster Intelligence Platform
**Largest single finding of this replan.** A full `src/roster_intel/` package (16 files,
~300KB) exists, is wired into `server.py` via `/api/roster/intelligence`
(`src/api/roster_intelligence.py`), and **already implements #839 and #899 verbatim** —
`src/roster_intel/core.py` contains `ceil(1.5×starters)`, FLEX-solved-before-reserve, and
Superflex-as-QB-demand handling matching the owner spec almost exactly. `#838` (Age-Value
Portfolio/Young Core Index) is likewise already built in `src/roster_intel/age_portfolio.py`
(22.7KB). Both issues describe unbuilt work; the code says otherwise. Also present and
**not mentioned in any open issue** — worth surfacing rather than re-inventing:
`src/roster_intel/targets.py` (41KB) and `partner.py` (46KB), a mature trade-target/
partner-discovery layer. Dynasty Command Center (CE-04): no code exists.

### 2.6 FAAB/Waiver Platform
Large, mature: `faab_engine.py` (56KB), `faab_comparability.py`, `faab_history.py`,
`faab_contention.py`, `faab_opportunity.py`, `faab_recommender.py`, `faab_shadow.py`,
`waiver.py`, `waiver_idp_best_available.py`, `waiver_ledger.py`. **Current live state:**
Stage 1 shadow-logging (`waiver_live_opportunity` flag, default ON, shadow-only) shipped
via **#1313 (merged)** — the earlier draft #1217 that some issue text still references is
closed unmerged and superseded. #738's five handoff items (seed bid history, timer
`Requires=` misuse, nonzero-only-median artifact, missing dev bridge route, one valuation
disagreement) remain open follow-ups from the earlier FAAB redesign, independent of
Stage 1.

### 2.7 Reporting/Storytelling Platform
PR #1295 (merged) built the canonical blended Power Rankings + a weekly share card, but
the share-card rendering lives *inside* `frontend/app/league/sections/ros-power.jsx` —
**there is no standalone, reusable `ShareCard`/`share_renderer` primitive today.** Any
future consumer (Weekly Report Studio #829, Awards v2/Wrapped, Game Day recap) that wants
a shareable graphic will either duplicate this rendering or the Power Rankings work needs
a follow-up PR to extract its renderer into a reusable primitive first. `src/public_league/
awards.py`, `overview.py`, `franchise.py` are mature pre-existing public-league recap
infrastructure, separate from the new share-card work.

### 2.8 PSI Full-Site Migration
See §1 table. ~5/46 routes fully activated, ~4 partially (`ds/` components without visual
activation), ~37 unmigrated. `frontend/components/ds/` is the established shared
primitive library — the mission's instruction to "identify shared UI primitives first"
is **already satisfied**; what remains is route-family migration work, not primitive
design.

### 2.9 Valuation/Source Platform (Hill Autopilot, KTC/DLF)
Hill Autopilot v2 is live (§1). KTC/DLF repair (#1297) is recent and large. Open,
real work: #1322 (board-impact gate rejected challenger v10, needs human review of *why*
— methodology question, not a bug), #898 (rank-form curve drift — committed constants no
longer reproduce the live board, needs manual multi-file edit), #1065 (IDPTradeCalc
content staleness despite healthy fetch — needs fetch-fresh/content-fresh separation
preserved end-to-end), #785 (TE premium deep audit — CLAUDE.md documents the basis
conversion as implemented, but the full audit scope in the issue is broader than that one
fix).

### 2.10 Agent OS / Site Steward
Architecture and schema merged (#1291); **runtime does not exist** (#1318 unmerged). Any
Phase-1 report-only runtime work is real greenfield work, not a resume-from-draft task —
the draft in #1318 can be read for design intent but its code isn't on `main`.
`EXECUTION_PLAN.md`'s own record already gates Steward Phase 1 runtime as
`DEFERRED_BY_AUTHORITY` until Week 1 reaches 30/30 — this replan does not change that
gate, only records that "advanced" in the mission's checklist means "architecture only."

---

## 3. Stale-manifest corrections (targeted, not a full rewrite)

`docs/C_SERIES_SCOPE_MANIFEST.md` is the zero-loss-verified 163-row census and is **not**
rewritten here in full (that would be exactly the duplicate roadmap the mission
prohibits). These are the specific rows this replan's code verification proves are
out of date; a future session updating the manifest directly should apply these:

| Manifest row | Manifest's recorded status | Verified 2026-09-10 reality |
|---|---|---|
| C2-CORE-01 (Meaningful Roster Core) | ABSENT (hard-coded caps still live) | **Built.** `src/roster_intel/core.py` implements the `ceil(1.5×starters)` + FLEX rule per #839/#899. |
| C2-AGE-01/02/03 (Age-value portfolio) | ABSENT | **Built.** `src/roster_intel/age_portfolio.py`. |
| C3-VA-01/02 | COMPLETE (2026-08-20) | Confirmed still accurate. |
| C5-WAR-01 (Realized VORP/WAR) | ABSENT | Still accurate — #969's PR closed unmerged; do not credit as in-progress. |
| C6-ANA-01 (Analyst ledger) | ABSENT (zero ingestion/credentials) | **Partially stale** — ingestion architecture (`src/intel/`) is mature; the *persistence/as-of query* half is what's actually absent (#980 closed unmerged). Podcast content-flow liveness not verified this pass — flag NEEDS-VERIFICATION before crediting further. |
| C4-FAAB-02 (timer) | PARTIAL (no timer) | Still accurate; #1313 added shadow logging, not the timer. |
| C2-REPL-01 / C2-STR-01 / C2-WEAK-01 / C2-GP-01 (duplicate-owner rows) | DUPLICATED / PARTIAL / DISCONNECTED | Confirmed still accurate and, per §2.1/§2.5, the duplication is *worse* than the manifest states in one place: roster-capacity now has confirmed duplicate owners not previously flagged as such at the trade-layer/roster-intel-layer boundary. |

---

## 4. Deliverable 1 — Reconciled backlog table

Scope: every currently open GitHub issue (52), plus the owner-TODO T-NEW items not
already closed, plus CE-series items with no code owner, plus the duplicate-owner
consolidations surfaced in §2/§3. Full long-tail manifest detail (the ~140 other rows
not independently re-verified this pass) remains authoritative in
`C_SERIES_SCOPE_MANIFEST.md` — nothing there is superseded except the rows named in §3.

Legend for **Disposition**: DONE→CLOSE, DONE-NEEDS-PROD-PROOF, PARTIAL, REAL-REMAINING,
DUPLICATE/SUPERSEDED, BLOCKED-EXTERNAL, OWNER-PAUSED, COST-GATED, LONG-TERM,
NEEDS-OWNER-DECISION.

### 4.1 Phase 0 — Active launch gate & production health (critical path)

| ID | Requirement | Current reality | Disposition | Canonical owner | Dep |
|---|---|---|---|---|---|
| W1-27 | Game Day LIVE state production-usable | Methodology fixed (#1319 merged); only real in-game production observation window missing | REAL-REMAINING (evidence-only, no code) | `src/ros/game_day_sim.py` | none |
| W1-28 | Game Day FINAL state production-usable | Evidence window (Mon 2026-09-14 20:15 ET) is *after* the contract's own 2026-09-09 23:59 CT deadline | **NEEDS-OWNER-DECISION** (deadline vs. evidence conflict — not an engineering gap) | same | W1-27 |
| W1-30 | Final Week 1 tree verified end-to-end | NOT STARTED | REAL-REMAINING | Lane 5 | W1-27, W1-28 |
| #1326/#1190/#1061/#1046 | Production health check failing (rolling) | Bot-filed, self-closing on next green run | DUPLICATE/OPERATIONAL-NOISE — close as a class, do not schedule engineering time | ops | none |
| #951 | `/api/sharp/*` production gate unauthenticated (472 comments, 3 weeks) | No credential ever provisioned | BLOCKED-EXTERNAL (needs a credential decision from Lane 5/owner) | ops | none |
| #737 | Daily intel refresh failing (Sharp Tracker crawl) | Rolling, auto-retries | REAL-REMAINING if it doesn't self-clear; else operational noise | `src/intel/` | none |
| #779 | Admin `fmtPassExpiry` crash | Live client-side crash | REAL-REMAINING | admin UI | none |
| #780 | Temp-password generator repair | Owner-reported broken | REAL-REMAINING | admin UI | #779 |
| #815 | Public `/league` `teamAssignment` serves degraded-as-200 | Confirmed live semantics bug | REAL-REMAINING | public league | none |
| #1153 | Mobile drawer still fails after #1150 (attempt 6) | Confirmed unresolved, needs trace-level diagnosis | REAL-REMAINING | PSI/MobileChrome | none |

### 4.2 Phase 1 — Roster Decision Foundation

| ID | Requirement | Current reality | Disposition | Canonical owner |
|---|---|---|---|---|
| #839 | Meaningful roster core = ceil(1.5×starters) | **Already implemented** in `src/roster_intel/core.py` | DONE→CLOSE (verify prod-deployed, then close issue) | `src/roster_intel/core.py` |
| #899 | FLEX before reserve depth | **Already implemented**, same module | DONE→CLOSE | same |
| #838 | Age-Value Portfolio / Young Core Index | **Already implemented** in `age_portfolio.py` | DONE→CLOSE | `src/roster_intel/age_portfolio.py` |
| — | Roster-capacity duplicate owner (`src/trade/roster_capacity.py` vs `src/roster_intel/droppability.py`+`marginal.py`) | Two live implementations | **NEEDS CONSOLIDATION** — not a GitHub issue today, should be filed | one of the two, TBD by Lane 1/2 |
| — | Team Strength duplicate owner (`src/roster_intel/strength.py` vs `src/ros/team_strength.py`) | Two live implementations | **NEEDS CONSOLIDATION** — should be filed | TBD |
| #843 | Roster capacity + forced-drop for trade analysis | Built at trade layer per CLAUDE.md; duplicate-owner risk above | PARTIAL (consolidation, not net-new build) | `src/trade/roster_capacity.py` (candidate canonical) |
| #840 | Competitive Posture Engine PUSH/HOLD/RETOOL/REBUILD | `src/roster_intel/window.py` deliberately avoids hard labels | **NEEDS-OWNER-DECISION**: does the issue's hard-label ask override the existing deliberate design, or does window.py's continuous framing stand and the issue gets closed as superseded? | `src/roster_intel/window.py` |
| #1152 | V1-45 remaining truthful L4 states (`capacity_uncertain`, generic error) | Populated state proven; two states still need real prod observation | PARTIAL | roster simulation |

### 4.3 Phase 2 — Trade Decision Platform

| ID | Requirement | Current reality | Disposition | Canonical owner |
|---|---|---|---|---|
| #792 | Analyze Trade — canonical MAKE/LEAN/PASS synthesis | `analyze_trade.py` exists but narrower than the full spec | REAL-REMAINING | `src/trade/analyze_trade.py` |
| #842 | Use Team Context toggle, default ON | Not found | REAL-REMAINING | trade UI + engines |
| #841 | Posture-aware draft-pick generation in Trade Finder | Not found | REAL-REMAINING | `src/trade/finder.py` |
| #800 | Equalizer must use VA-adjusted totals | CLAUDE.md documents this exact defect as repaired (0/4000 misses) | DONE→CLOSE (verify against issue's specific repro before closing) | `findBalancers`/`_find_balancers` |
| #790 | Monte Carlo re-audit | `monte_carlo.py`/`correlation_matrix.py` exist; audit itself not performed | REAL-REMAINING (audit task) | `src/trade/monte_carlo.py` |
| #791 | Second Opinions winner tally | Per-vendor breakdown exists; tally summary not confirmed | PARTIAL | `TradeSourceBreakdown.jsx` |
| #786 | NFL team exposure before/after in simulator | Owner already exists (`src/roster_intel/exposure.py`) | PARTIAL — wire existing owner into simulator, don't build new | `src/roster_intel/exposure.py` |
| #781 | Silent value-override UX + global reset | Not confirmed built | REAL-REMAINING | trade UI |
| #1173 | Best-ball roster-conditional utility in Analyze Trade | New owner spec, depends on #792 existing | REAL-REMAINING, dependency-gated on #792 | `analyze_trade.py` + `src/ros/lineup.py` |
| #1005 | DLF/bridge integrity drift advisory | Plausibly closed by merged #1297 | NEEDS-CONFIRMATION (not code-verified this pass) | source bridge |

### 4.4 Phase 3 — Valuation/Source Platform

| ID | Requirement | Current reality | Disposition | Canonical owner |
|---|---|---|---|---|
| #1322 | Hill Autopilot board-impact gate blocking v10 promotion | Live, legitimate v2-pipeline output | BLOCKED-EXTERNAL (human methodology review, per contract) | `src/model_registry/autopilot.py` |
| #898 | Rank-form curve drift, committed constants stale | Confirmed via weekly drift-check bot | REAL-REMAINING | `src/canonical/player_valuation.py` + rank-form config |
| #1065 | IDPTradeCalc content stale despite healthy fetch | Confirmed | REAL-REMAINING | source-health staleness config |
| #785 | 2-TE premium deep audit | Basis conversion implemented (ADR-015); full audit scope broader | PARTIAL | `src/league_intel/te_premium.py` |
| #895, #777 | Hill refit "challenger cleared held-out gate" (manual-era reports) | Superseded by Autopilot v2's automatic path | DUPLICATE/SUPERSEDED → close both | — |
| #801 | Establish The Run source | Owner-paused explicitly | OWNER-PAUSED | — |

### 4.5 Phase 4 — Analyst/Intelligence Platform

| ID | Requirement | Current reality | Disposition | Canonical owner |
|---|---|---|---|---|
| #782 | YouTube ingestion parallel to Podcast Intelligence | Podcast infra (`src/intel/`) mature; YouTube not built | LONG-TERM (real work, no urgency signal) | `src/intel/` (extend) |
| #783 | Unified player-profile intelligence feed | No consumer wiring `src/intel/` output onto Universal Player Profile | LONG-TERM | `src/intel/` + player profile route |
| #784 | Homepage Consensus Edge ticker | Not found | REAL-REMAINING (smaller, UI-shaped) | `src/consensus_edge/` |
| #829 | Weekly Report Studio (manual-AI default) | Not built; narrative infra (`matchup_narrative.py`) exists as a building block | LONG-TERM | new, built on existing narrative + reporting primitive (§2.7) |
| #985 | DynastyStats owner addendum (League Hub, Asset Map, Transaction Intelligence, Manager Scout enrichment) | Explicit owner note: POST-V1 unless foldable | LONG-TERM | multiple, TBD |
| #788 | ~500-analyst X feed | Explicit cost-gate | COST-GATED | — |
| #980 | Analyst claim/evidence ledger persistence | Schema exists, store does not (PR closed unmerged) | REAL-REMAINING (real work, not resumable from the closed PR as-is) | `src/analyst/` |

### 4.6 Phase 5 — Projection/Scoring/Game Day Platform

| ID | Requirement | Current reality | Disposition | Canonical owner |
|---|---|---|---|---|
| #802 | Individual special-teams scoring bug (KR/PR/ST misclassified NOT_APPLICABLE) | Confirmed live scoring-correctness bug | REAL-REMAINING, small and urgent (v1-required label, correctness bug) | scoring config |
| #854 | Multi-source projection ensemble | Confirmed gap: aggregator carries but doesn't consume `projection_value` | LONG-TERM (large) | `src/ros/projection_ensemble.py` |
| #789 | Game Day best-ball-aware win probability expansion | Foundation (`game_day_sim.py`) mature; full spec not complete | LONG-TERM | `src/ros/game_day_sim.py` |
| #969 (C5-WAR-01) | Realized VORP/WAR/WAB/Game Changer | PR closed unmerged — real work remains | REAL-REMAINING | new module, consumes `src/scoring/replacement_level.py` |
| #803 | Player-specific league-fit + college translation | Not built | LONG-TERM | new |

### 4.7 Phase 6 — FAAB/Waiver Platform

| ID | Requirement | Current reality | Disposition | Canonical owner |
|---|---|---|---|---|
| #1151 | Render league FAAB context with no team selected | Confirmed UI gating bug | REAL-REMAINING, small | `/waivers` |
| #1157 | Roster-percentage production timeout | Confirmed `build_board()` >60s in prod | REAL-REMAINING, correctness-adjacent perf bug | `src/sharp/roster_percentage.py` |
| #830 | Extend FAAB market layer (Sleeper heat + Sharp bids) | Not built; large mature FAAB layer exists to extend | REAL-REMAINING | `src/trade/faab_engine.py` family |
| #738 | FAAB redesign handoff (5 items) | Independent of Stage-1 shadow logging (#1313, merged) | REAL-REMAINING (small items) | FAAB layer |

### 4.8 Phase 7 — Reporting/Storytelling Platform

| ID | Requirement | Current reality | Disposition | Canonical owner |
|---|---|---|---|---|
| #1166 | `/league` SSR missing OpenGraph metadata | Confirmed via prod E2E | REAL-REMAINING, small | public league SSR |
| — | Extract Power Rankings share-card renderer into a reusable primitive | Confirmed: rendering is inline in `ros-power.jsx`, not reusable | **NEEDS FILING** — no issue exists; recommended before #829/Awards v2/Wrapped build their own | new `ShareCard`/`share_renderer` primitive |
| #829 | Weekly Report Studio | See Phase 4 (cross-listed — also a reporting-platform consumer) | LONG-TERM | — |

### 4.9 Phase 8 — PSI Full-Site Migration

| ID | Requirement | Current reality | Disposition | Canonical owner |
|---|---|---|---|---|
| #1153 | Mobile drawer failure (also Phase 0, urgent) | See 4.1 | REAL-REMAINING | PSI shell |
| #730 | Streaming SSR duplicate-DOM race | Diagnosed, not fixed; explicit instruction not to paper over with `.first()` | REAL-REMAINING | Next streaming SSR |
| — | Remaining ~37 unmigrated routes | See §2.8 | LONG-TERM, route-family batched | `ds/` primitives (exist) |

### 4.10 Phase 9 — Agent OS / Site Steward

| ID | Requirement | Current reality | Disposition | Canonical owner |
|---|---|---|---|---|
| #1214 | V1-125 rebase W30 census before duplicate-owner retirement | Confirmed real, corrects 2 misidentified rows | REAL-REMAINING | census/dedup tooling |
| #967 | Dispatch registry missing lanes 8/9-13 | Bookkeeping drift | LIKELY-DUPLICATE/STALE (verify against current dispatcher state before acting) | dispatcher config |
| — | Steward Phase 1 report-only runtime | Architecture merged, runtime doesn't exist (#1318 unmerged) | DEFERRED_BY_AUTHORITY (per EXECUTION_PLAN — gated until Week 1 = 30/30) | new `src/steward/` |

### 4.11 Future / paused / cost-gated / owner-rejected (Category D — excluded from completion math)

| Item | Disposition |
|---|---|
| #801 / X-03 Establish The Run | OWNER-PAUSED |
| #788 / C6-X-01 ~500-analyst X feed | COST-GATED |
| X-01 Fantasy Schedule Generator | OWNER-REJECTED |
| X-02 Money/Constitution/League Media | OWNER-REJECTED |
| X-05 League-aware valuation overlay as canonical | OWNER-REJECTED |
| X-07 "Link any Sleeper account" onboarding | NOT-PRODUCT-SCOPE |
| CE-28 User feedback/polling | NOT OWNER-APPROVED (needs OD-06) |
| V1-49, V1-83, V1-101, V1-102 | V2 VERIFICATION DEBT (owner-deferred, event-gated recheck triggers, not open engineering work) |

---

## 5. Deliverable 2 — Combined phase plan

Derived from §2's shared-foundation survey, not from issue numbers in order.

- **Phase 0 — Finish Active Launch Gate.** W1-27/28/30, rolling production-health/ops
  noise, admin crash pair, mobile drawer, `teamAssignment` degraded-as-200. Nothing else
  should compete with this for Lane 5 attention until it closes or the owner explicitly
  reprioritizes (per the launch contract's own "keep V1 closed, don't begin broad V2"
  rule — this replan is V2 *planning*, not V2 *implementation*, which stays gated).
- **Phase 1 — Canonical Roster Decision Foundation.** Consolidate the two confirmed
  duplicate owners (roster-capacity, Team Strength) *before* anything downstream extends
  either. Close #839/#899/#838 as already-implemented once prod-verified. Resolve the
  Competitive Posture label question (#840 vs. `window.py`'s design) as an explicit
  owner decision. This phase is the dependency root for nearly everything in Phase 2 and
  Phase 5 (Team Strength/posture feed Analyze Trade, Game Day, FAAB need classification).
- **Phase 2 — Trade Intelligence Decision Platform.** Analyze Trade (#792) as the
  synthesis consumer of Phase 1's roster foundation + existing VA/capacity/exposure
  owners; Use Team Context toggle (#842) and posture-aware pick generation (#841) as
  siblings that share Analyze Trade's data path; Second Opinions tally (#791), Monte
  Carlo re-audit (#790), silent-override UX (#781), best-ball utility (#1173) as
  consumers layered on once the synthesis contract exists. This is the mission's
  worked example almost exactly as given.
- **Phase 3 — Valuation/Source Platform Hardening.** Board-impact gate review (#1322),
  rank-form drift repair (#898), content-staleness fix (#1065), TE premium audit (#785),
  close stale Hill-refit issues (#895/#777). Independent of Phases 1–2; can run fully
  parallel.
- **Phase 4 — Analyst/Intelligence Platform.** Build the analyst-ledger persistence
  (#980, real work despite the closed PR) first — it's the shared substrate YouTube
  ingestion (#782), the unified profile feed (#783), the homepage ticker (#784), and
  Weekly Report Studio (#829) all need for provenance/freshness/dedup. Matches the
  mission's "Analyst / intelligence platform" combination hypothesis closely.
- **Phase 5 — Projection/Scoring/Game Day Platform.** Fix the special-teams scoring bug
  (#802) immediately — it's small, correctness-critical, and independent. Then the
  projection ensemble (#854) becomes the shared substrate for Realized WAR (#969),
  Game Day win-probability expansion (#789), and league-fit/college translation (#803).
- **Phase 6 — FAAB/Waiver Intelligence.** Small urgent items first (#1151 UI gating,
  #1157 perf), then the Sleeper-heat/Sharp-bid market extension (#830) and the #738
  handoff items on the existing mature FAAB layer.
- **Phase 7 — Reporting/Storytelling Platform.** Extract the Power Rankings share
  renderer into a reusable primitive *before* Weekly Report Studio, Awards v2, or Wrapped
  each build their own — this is the mission's "one deterministic rendering/report
  package" instruction operationalized. Fix the OpenGraph SSR gap (#1166) independently
  (small, unrelated file).
- **Phase 8 — PSI Full-Site Migration.** Fix the two urgent PSI-adjacent bugs (mobile
  drawer #1153 — also Phase 0, streaming SSR dup-DOM #730) first since they affect
  already-migrated routes; then batch-migrate the remaining ~37 routes by route family
  (waivers, game-day, bdvm/consensus-edge, draft, league sub-pages, admin) using the
  already-built `ds/` primitives — no new primitive design needed, per §2.8.
- **Phase 9 — Agent OS / Site Steward.** Rebuild the Steward Phase 1 runtime as real
  new work (not resumable from #1318's closed PR), gated `DEFERRED_BY_AUTHORITY` until
  Week 1 = 30/30 per the existing EXECUTION_PLAN record. Fix dispatcher bookkeeping
  drift (#967, #1214) opportunistically — small, independent.
- **Phase 10 — Final C10 Hardening/Closure.** Unchanged from `C_SERIES_EXECUTION_MAP.md`'s
  M8 milestone — runs once Phases 1–9 have landed enough real capability that the
  C-Series Completion Audit (contract §13) is worth attempting.

---

## 6. Deliverable 3 — Dependency graph

```
Phase 0 (launch gate)         Phase 3 (valuation/source)     Phase 9 (Agent OS)
   |  (soft gate: don't          |  (fully independent,          |  (hard-gated by
   |   compete for Lane 5         |   parallel-safe)              |   Week1=30/30 per
   |   attention until closed              |                      |   existing EXEC_PLAN)
   v                             v                                v
Phase 1 (roster foundation) ----+--------------------------------+
   |   |                                                           
   |   +--> consolidate roster-capacity duplicate owner            
   |   +--> consolidate Team Strength duplicate owner               
   |   +--> resolve #840 posture-label decision (NEEDS-OWNER-DECISION)
   v
Phase 2 (trade decision platform)   Phase 5 (projection/scoring/GameDay)
   |  needs: Phase 1's Team           |  needs: nothing from Phase 1/2
   |  Strength/posture/capacity       |  (independent substrate); #802
   |  owners settled                  |  scoring-bug fix is fully parallel
   v                                  v
Phase 6 (FAAB/waiver)              Phase 4 (analyst/intelligence)
   |  independent of 1/2/5,           |  independent of everything else;
   |  parallel-safe                   |  #980 ledger persistence is its
   v                                  |  own internal foundation-first step
Phase 7 (reporting/storytelling)      v
   |  needs: Power Rankings        (Phase 4 output feeds Phase 7's
   |  share-renderer extraction     Weekly Report Studio eventually,
   |  (small, do first)             but not blocking)
   v
Phase 8 (PSI migration)
   |  independent of 1-7 except the two urgent shared-route bugs
   |  (#1153, #730), which should land before route-family batching
   v
Phase 10 (C10 closure)
   requires meaningful completion signal from 1, 2, 5 at minimum
```

**Critical path today:** Phase 0 (launch gate) is soft-blocking in the sense that Lane 5
integration authority and owner attention are the scarce resource, not that Phases 1-9
are code-blocked by it — the POST-V1 mass-build campaign already authorizes parallel
branch work. The *real* critical path once Phase 0 closes is **Phase 1 → Phase 2**,
because Phase 2's flagship deliverable (#792 Analyze Trade) is explicitly named in
multiple owner docs as dependency-gated on exactly the roster foundation Phase 1
consolidates, and Phase 2 is the mission's own worked example of what "combined phase"
means.

**Fully parallel-safe today, no shared files with Phase 0/1/2:** Phase 3 (valuation),
Phase 4 (analyst), Phase 5 (projection/scoring — except its Team-Strength/posture
consumers, which wait on Phase 1), Phase 6 (FAAB), Phase 8 (PSI route migration, except
the two urgent shared bugs).

**Contention points (one writer at a time):**
- `src/roster_intel/` (Phase 1 consolidation touches strength.py, droppability.py,
  marginal.py, window.py — do not let Phase 2 work edit these concurrently)
- `data_contract.py` pipeline core (any valuation/source work in Phase 3)
- `CE_REGISTRY.md` (any new CE-xx minting across Phases 2/4/6/7)
- `docs/EXECUTION_PLAN.md`, `docs/WORK_CLAIMS.md` (Lane 5 only, per existing rule)

---

## 7. Deliverable 4 — Optimized PR map (Phases 0–2 at full depth; Phases 3–9 sketched)

### Phase 0
- **PR 0.1** — Close/triage rolling production-health issues as a class (#1326, #1190,
  #1061, #1046); confirm the health check itself isn't flapping on a real intermittent
  bug before mass-closing. *Verification: 3 consecutive green scheduled runs.* Parallel-safe.
- **PR 0.2** — Provision the `/api/sharp/*` production-gate credential (#951). *Verification:
  the workflow reports a real pass/fail instead of `unverifiable_unauthenticated`.* Needs
  an owner/ops credential decision — not pure engineering.
- **PR 0.3** — Fix admin `fmtPassExpiry` crash + temp-password generator (#779, #780
  together — same file, same root cause likely). *Verification: `/admin` loads without
  crash; generated temp password respects configured expiry, end to end.* Parallel-safe.
- **PR 0.4** — Fix `/league` `teamAssignment` degraded-as-200 semantics (#815).
  *Verification: a degraded snapshot returns a distinguishable state, not `assignments: []`
  with HTTP 200.* Parallel-safe.
- **PR 0.5** — Trace and fix mobile drawer (#1153), attempt 7. *Verification: Playwright
  mobile-viewport E2E passes at 390×844, not just desktop.* Parallel-safe.
- **PR 0.6** — Owner decision + doc update on W1-28's deadline/evidence-window conflict;
  then W1-30 final verification once W1-27/28 resolve. Serial, depends on all of the above
  plus a real in-game observation window.

### Phase 1
- **PR 1.1** — Consolidate roster-capacity: pick canonical owner (recommend keeping
  `src/trade/roster_capacity.py` per its CLAUDE.md documentation and existing consumer
  wiring into suggestions/finder/simulate/angle), migrate `droppability.py`/`marginal.py`
  callers onto it or retire them, add an AST/import guard preventing a third owner.
  *Verification: existing roster_capacity test suite green + no remaining import of the
  retired module.* Must land before PR 1.4/1.5.
- **PR 1.2** — Consolidate Team Strength: same pattern between `roster_intel/strength.py`
  and `ros/team_strength.py`. *Verification: single owner, existing consumers repointed,
  parity test between old/new outputs on real rosters.* Can run parallel to PR 1.1
  (different files) but both should land before Phase 2 starts.
- **PR 1.3** — Verify and close #839/#899/#838 as already-implemented: add/confirm test
  coverage proving `roster_intel/core.py` and `age_portfolio.py` match the issue specs
  exactly, get production-deployed confirmation, close the three issues with evidence
  links. *Verification: issue-specific acceptance criteria checked off against passing
  tests, not just "code exists."* Parallel-safe once PR 1.1/1.2 aren't touching the same
  files.
- **PR 1.4** — Owner decision on #840 (Competitive Posture labels vs. `window.py`'s
  continuous design) — this is an `AskUserQuestion`/owner-escalation step, not a code PR.
  Blocks any PR that would implement hard PUSH/HOLD/RETOOL/REBUILD labels.
- **PR 1.5** — Resolve remaining V1-45 truthful states (#1152: `capacity_uncertain` +
  generic error, real prod observation). Depends on PR 1.1 landing (capacity owner
  settled first).

### Phase 2
- **PR 2.1** — Analyze Trade canonical contract (#792): define the MAKE/LEAN/PASS
  synthesis API consuming Phase 1's settled Team Strength/posture/capacity/exposure
  owners plus existing VA — this is the "canonical contract/owner" PR the mission's
  worked example calls for. *Verification: no double-counting of correlated signals
  (explicit test), contract schema test.*
- **PR 2.2** — Use Team Context toggle (#842) as a consumer of 2.1's contract, shared
  between Analyze Trade and Trade Finder.
- **PR 2.3** — Posture-aware pick generation in Trade Finder (#841), consumes 1.4's
  resolved posture decision.
- **PR 2.4** — Best-ball roster-conditional utility (#1173) as a consumer of 2.1,
  depends on `src/ros/lineup.py` (already canonical, no new owner needed).
- **PR 2.5** — Second Opinions tally (#791) — small, UI-shaped, parallel-safe against 2.1-2.4.
- **PR 2.6** — Monte Carlo re-audit (#790) — audit-only PR (docs + any bug fixes found),
  parallel-safe.
- **PR 2.7** — Wire existing NFL-exposure owner into Trade Simulator (#786) — small,
  parallel-safe, explicitly must NOT create a second exposure engine.
- **PR 2.8** — Silent-override UX + global reset (#781) — frontend-only, parallel-safe.
- **PR 2.9** — Verify #800's VA-equalizer fix against the issue's specific repro, close
  or fix residual gap. Parallel-safe, small.

### Phases 3–9 (sketched — full PR breakdown deferred to when each phase becomes active)
- **Phase 3**: one PR per issue (#1322 methodology review + doc, #898 curve-constant
  fix, #1065 fetch/content-freshness split, #785 audit, #895/#777 close-as-duplicate) —
  all small, independent, parallel-safe.
- **Phase 4**: PR 4.1 analyst-ledger persistence (foundation, serial-first) → PR 4.2
  YouTube ingestion, PR 4.3 unified profile-feed consumer, PR 4.4 homepage ticker, PR 4.5
  Weekly Report Studio v1 — 4.2/4.3/4.4 can parallelize once 4.1 lands; 4.5 also needs
  Phase 7's share-renderer extraction.
- **Phase 5**: PR 5.1 special-teams scoring bug (urgent, standalone) → PR 5.2 projection
  ensemble foundation (serial-first) → PR 5.3 Realized WAR, PR 5.4 Game Day win-prob
  expansion, PR 5.5 league-fit/college translation (5.3/5.4/5.5 parallel once 5.2 lands).
- **Phase 6**: PR 6.1/6.2 small urgent fixes (#1151, #1157) parallel-safe → PR 6.3 market
  extension (#830) → PR 6.4 handoff cleanup (#738, five small sub-items, can parallelize
  internally).
- **Phase 7**: PR 7.1 extract share-renderer primitive (foundation, serial-first) → PR
  7.2 OpenGraph fix (#1166, fully independent, can land anytime) → downstream Weekly
  Report Studio/Awards work waits on 7.1.
- **Phase 8**: PR 8.1/8.2 urgent bug fixes (#1153 — shared with Phase 0, #730) → PR 8.3+
  one PR per route family (waivers, game-day, bdvm/consensus-edge, draft, league
  sub-pages, admin) — each independently reviewable and parallel-safe against each other.
- **Phase 9**: PR 9.1 dispatcher bookkeeping fix (#967, #1214, small) → PR 9.2 Steward
  Phase 1 runtime (real new build, gated `DEFERRED_BY_AUTHORITY` until Week 1 closes).

---

## 8. Deliverable 5 — Completion forecast

**Method note:** ranges, not false precision, per the mission's instruction. Sizing
combines the four research passes' file-size/maturity signals with issue count and
dependency depth — it is a planning estimate, not a measured velocity model.

| Metric | Estimate |
|---|---|
| V1 REQUIRED complete | 100% (132/132) — closed, do not reopen |
| Week 1 launch gate complete | 90% (27/30) — 2 rows are evidence-timing, not code work; 1 depends on those two |
| Core product complete (mission's Category B — roster/trade/FAAB/valuation feel like a complete dynasty operating system) | **~55-65%.** Roster intelligence, trade calculator core, FAAB engine, Hill Autopilot, Game Day, Power Rankings, PSI foundation are mature. Analyze Trade synthesis, Competitive Posture productization, analyst/intelligence ingestion-to-UI, projection ensemble, PSI full-site coverage, and a reusable reporting primitive are the largest remaining core gaps. |
| Full currently-authorized product (Category C — all C-series through C10 closure) | **~35-45%.** Per the Scope Manifest's own tallies (C1 closed, C2 partial/duplicated, C3 mostly absent beyond VA, C4-C6 mostly absent, C7 almost entirely absent except draft snapshot, C8 partial, C9 mostly wrong/absent, C10 not begun). |
| Category D (paused/cost-gated/rejected) | Excluded from the above — ETR, X-feed, schedule generator, Money/Constitution, league-account-linking, CE-28 pending decision. |

**Remaining meaningful work packages (Phases 1-9 above):** roughly **9 combined phases**
containing an estimated **55-75 bounded PRs** total (Phase 0: ~6, Phase 1: ~5, Phase 2:
~9, Phase 3: ~5, Phase 4: ~5-6, Phase 5: ~5, Phase 6: ~4, Phase 7: ~2 plus downstream
consumers counted in Phase 4/9, Phase 8: ~8-10 route-family PRs, Phase 9: ~2). This is
materially fewer than treating each of the 52 open issues plus ~140 remaining manifest
rows independently would produce (which would run well past 150 independent units) —
the reduction comes almost entirely from Phase 1 (roster foundation touched once instead
of by #839/#899/#838/#843/#840/#792/#1173/#786/#969 each separately), Phase 2 (one
Analyze Trade contract instead of nine separate trade-feature implementations each
re-deriving posture/capacity/VA composition), and Phase 8 (route-family batching instead
of per-page migration).

**T-shirt sizing by phase:**

| Phase | Size | Gross LOC touched (rough) | Risk |
|---|---|---|---|
| 0 — Launch gate | S-M | 500-1500 | Low (small bugs) except W1-28 (owner-decision risk) |
| 1 — Roster foundation | M | 1500-3000 (mostly consolidation/deletion, not net-new) | Medium (duplicate-owner retirement touches live consumers) |
| 2 — Trade decision platform | L | 3000-6000 | Medium (many consumers, correctness-sensitive, double-counting risk) |
| 3 — Valuation/source hardening | S-M | 800-2000 | Low-Medium (methodology review risk on #1322) |
| 4 — Analyst/intelligence | L-XL | 4000-9000 | Medium (new persistence layer, external ingestion) |
| 5 — Projection/scoring/GameDay | L-XL | 4000-8000 | Medium-High (projection ensemble is genuinely hard, multi-vendor) |
| 6 — FAAB/waiver | M | 1500-3000 | Low-Medium |
| 7 — Reporting/storytelling | M | 1500-3000 (renderer extraction) + more for consumers | Low |
| 8 — PSI migration | L | 3000-6000 (mostly repetitive route work) | Low (primitives exist) but High volume |
| 9 — Agent OS/Steward | M | 1500-3000 (real runtime build) | Low risk, explicitly gated by authority |

**Optimistic / expected / conservative completion range** (Phases 0-9 above, excluding
Category D and excluding any further owner-added scope): **optimistic 10-12 weeks,
expected 16-22 weeks, conservative 28-36 weeks** of sustained multi-lane agent+owner
throughput at something close to the velocity evidenced by the last 30 days of merged
PRs (which was very high — dozens of substantial merges). The dominant swing factor is
Phase 4 (analyst ingestion) and Phase 5 (projection ensemble), both of which are
genuinely large and have external-dependency/data-availability risk the repo doesn't
fully control.

**Critical-path phases:** Phase 0 (soft, owner-attention-bound) → Phase 1 (hard
dependency root for Phase 2 and part of Phase 5) → Phase 2 (the mission's flagship
combination example, largest correctness risk). Phases 3, 4, 6, 8 can absorb most
available parallel capacity without waiting on the critical path.

**Highest-risk unknowns:**
1. #840's posture-label question is a live methodology disagreement, not an engineering
   gap — needs an explicit owner ruling before Phase 2 can implement it cleanly.
2. W1-28's evidence-window-vs-deadline conflict needs an owner decision (extend the
   deadline, or accept the current LIVE-state evidence as suf­ficient and reclassify
   FINAL-state as V2 debt the way V1-49/83/101/102 were handled).
3. Podcast-intelligence content liveness (are `src/intel/` crawlers actually producing
   usable signal today, or is the architecture built but dormant?) was not verified this
   pass — Phase 4 sizing depends on the answer.
4. The roster-capacity and Team-Strength duplicate-owner consolidations (Phase 1) carry
   real regression risk to already-shipped trade/roster features if done carelessly —
   size them as M, not S, for that reason.

---

## 9. Durable planning rule (added to `docs/EXECUTION_PLAN.md`, restated here for context)

> Before implementing a backlog item, identify other active requirements that touch the
> same canonical owner, dependency, data model, API, route family, UI primitive, test
> infrastructure, or workflow. Where a shared foundation can satisfy several requirements
> without unsafe scope coupling, plan them under one combined phase and implement that
> foundation once. Preserve small reviewable PR boundaries within the combined phase.
> Check `docs/BACKLOG_REPLAN_2026-09-10.md` (or its successor reconciliation) for the
> current combined-phase assignment before starting isolated work on an open issue.

---

## 10. What this replan deliberately does not do

- It does not reopen V1 (100% complete, do-not-reopen boundary respected).
- It does not begin broad V2 implementation while the Week 1 launch contract is
  incomplete — this is planning only, matching the mission's explicit "this is a
  PLANNING + RECONCILIATION task first."
- It does not delete or override any owner-rejected item (X-01/02/05/07), paused item
  (#801/ETR), or cost-gated item (#788/X-feed).
- It does not silently resolve the #840 posture-label methodology question either
  direction — that's named as an explicit owner decision point.
- It does not rewrite `C_SERIES_SCOPE_MANIFEST.md`'s 163 rows in full; §3 names the
  specific corrections a future manifest-editing session should apply.
- It does not open implementation PRs. Per the mission: "This directive's first
  objective is the replan."
