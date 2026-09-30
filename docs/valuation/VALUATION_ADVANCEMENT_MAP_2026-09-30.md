# Valuation advancement + comprehensive Signals integration — requirement map (2026-09-30)

**Role:** the requirement-to-implementation map for owner direction #1555. It is
incorporated into #792 and extended on 2026-09-30 with the comprehensive Signals scope.
It maps requirements onto existing canonical owners and authority. It is **not** a second
roadmap, and it grants no authority of its own. Implementation authority stays in
`docs/EXECUTION_PLAN.md` (the 2026-09-24 Calculator completion campaign, lanes C/D/6,
plus the 2026-09-30 section that points here). Intake pointer:
`docs/OWNER_REQUESTED_TODO.md` ("Valuation advancement + comprehensive Signals").

**Three capabilities kept distinct throughout:**

1. **Fundamental dynasty value** — our forecast of football outcomes turned into value for
   the actual league. BDVM today, a provisional challenger.
2. **Market price** — what comparable managers exchange. The canonical board today, plus
   our own completed-trade estimator later.
3. **Roster-specific trade impact** — the legal post-trade roster, lineup, assets, risk and
   window. #792 is the single owner.

Agreement with KTC or Signals is not correctness; disagreement is not an edge.

## A. Reused, not rebuilt (harness closeout, verified 2026-09-30)

| Capability | Evidence | Use in this batch |
|---|---|---|
| Steward raw-evidence validation | #1536 merged `0ee4f0200` | unchanged |
| Changed-file claims vs pinned diff | #1537 merged `6e9f4110b` | used for this batch's PR evidence while PRs are open |
| Test claims vs GitHub CI records | #1542 merged `49c65941a` | same; captured before merge, because verification needs the open PR |
| Served build identity + deploy smoke | #1543 merged `67f300cdb`; first verified deploy `850a83a67` (run 36744356641) | **current production `b512619f1`** (`/api/status` `build.commit`, read 2026-09-30) is the reference for any release from this batch |
| Documentation closeout | #1545 merged `5e298f63b` | — |

**Not revived:** the Steward-receipts→eval bridge (withdrawn — circular).
**Still approval-gated, separate:** pinning manual deploys to the guarded SHA.
**Preserved follow-ups, not prioritized here:** typed endpoint, parser replay fixtures,
CLAUDE.md slimming.

## B. KeepTradeCut authorization (owner decision, 2026-09-30)

The owner states he holds explicit permission from KeepTradeCut to scrape **all KTC
data**. It is recorded as **owner-reported authorization** in the canonical provenance record
(`docs/MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md` §19.2) and in manifest row `F-EXT-01`.
KTC scraping is no longer classified as absent or blocked.

No permission document is invented. The authorization does **not** disclose KTC's
proprietary Tradesourced formula. It does not transfer to Signals, IDP Trade Calculator or
any other provider, and it grants no redistribution or commercial rights beyond what was
granted. Request hygiene and technical limits (rate, robots, no access bypass) still apply.
Dependent lane: `C4-MTL-02` (KTC trade database) is no longer blocked on an artifact.

## C. Requirement-to-implementation map

Legend: **NOW** = in this batch; NEXT = dependency-ready next; LATER = needs a predecessor;
BLOCKED = external. Readiness is not permission — the authority column says which record
permits execution.

| # | Requirement | Canonical owner | Current state (verified) | Gap | Stage | Authority | Claim / PR | Acceptance / release gate | Rollback |
|---|---|---|---|---|---|---|---|---|---|
| V1 | Reproducible current-value evidence (Coker + contrasts) | `src/api/value_replay.py` + `scripts/value_replay.py`, extending `source_weighting_explain` | **Implemented** 2026-09-30; offense blend reproduced from stamps on 406/406 ranked rows | Live served response/UI capture needs owner-authenticated read | **NOW** | campaign lane C | `claude/value-replay-evidence` | tests + pinned evidence `docs/valuation/evidence/value-replay-2026-09-30/` | tooling only |
| V2-1 | Cross-subset freshness (IDPTC IDP edits refresh offense) | `src/sources/dataset_state.py`, `freshness.py` | **Reproduced** in tracked state (below) | Offense-universe clock from existing per-row times | NEXT (own PR) | lane C | next unit | RED regression; whole-board before/after; flag | flag / `RISKIT_FEATURE_SOURCE_FRESHNESS_WEIGHTING=0` |
| V2-2 | Cadence vs information age | `freshness.py` | **Verified** (Coker: three voters carry pre-season data at weight ~1.0) | Season-event-aware information age; must not teach outages as normal | LATER (methodology) | lane C + owner review | — | challenger report, not auto-promotion | — |
| V2-3 | Weight-blind outlier filter | `data_contract._hampel_filter_per_player` | **Mechanism verified; latent** (0 of 116 dropping rows removed dominant weight) | Correction must also address the post-filter single-source haircut | LATER | lane C | — | characterization test pinned | — |
| V2-4 | Lineage / independence | `cap_family_weights`, B10 families, B11 confidence | KTC Crowd and Trades are separate families; KTC Market is benchmark-only (refused at import) | Asset-specific dependencies; IDPTC↔IDP Show; Signals ancestry | LATER | lane C | — | — | — |
| V2-5 | Native value vs rank→Hill | Hill masters + `_VALUE_BASED_SOURCES` | **Measured:** KTC native sits 14–45% above Hill(own rank) mid-board | Cause unknown; belongs to the owner-requested Hill / source-authority alignment audit | NEXT | lane C ("Hill / native-source alignment") | — | Hill Autopilot / model registry only | registry rollback |
| V2-6 | Confidence vs value (single-source haircut) | `_SINGLE_SOURCE_VALUE_RETENTION`, `confidence.py` | Haircut multiplies value by 0.30 | Priors/intervals instead of haircut | LATER (methodology) | owner review | — | — | — |
| V2-7 | Ingestion integrity | `dataset_integrity.py`, source health | existing health/coverage gates | not re-audited this batch | LATER | lane C | — | — | — |
| V3 | BDVM formulas / semantics | `src/bdvm/` | documented below; leads a–d **verified** | (b) fixed now; (a) labels fixed now; (c)/(d) documented | **NOW** (b, a) / LATER | lane D (b), lane 6 (a) | `claude/bdvm-stale-timestamp-failclosed`, `claude/bdvm-truthful-labels` | RED→GREEN; UI tests | revert |
| V3-S | Exact scoring coverage | `src/nfl_data/realized_points.py`, `league_intel/scorer.py` | unsupported keys (reception-distance, ST tackles, play-type first downs) score **0 silently** in BDVM projections | Explicit unsupported-key reporting | NEXT | lane D (#802/#854) | — | per-key test vs card | — |
| V4 | Signals data integration (W1) | canonical source registry + `src/sources/*` | **Discovery done** (public); automated collection **permission-blocked** by Signals terms | Written consent; then adapter, real capture, stages 2–5 | BLOCKED (live) / NOW (design, fixtures) | new source onboarding → campaign lane C once consent exists | `docs/sources/SIGNALS_FANTASY_INTEGRATION.md` | stage gates in that doc | disabled by default |
| V4-P | Signals product capabilities (W2) | #792, #838/#839/#840, draft/waiver/profile owners | capability matrix written | per-capability units | NEXT/LATER | per owning lane | same doc | per unit | — |
| V5 | Point-in-time raw data + independent BDVM challenger | `src/history/`, `src/bdvm/` | BDVM universe = market board rows; priors uncalibrated | Baseline milestone (below) | LATER | owner-gated promotion | — | held-out evidence | — |
| V6 | Own completed-trade market model | CE-01 ledger, `C4-MTL-*` | KTC trade DB lane unblocked by B | Ingestion then latent-price challenger | LATER | lane B/C when scheduled | — | time/league holdouts | — |
| V7 | Three-part decision UX | #792 | Analyze Trade exists | separate fundamental/market/roster panels; no cross-scale subtraction | LATER | lane B + 6 | — | #792 acceptance | — |
| V8 | Evaluation / release | this map + CI | — | targets defined before tuning | continuous | — | — | — | — |
| UI | Value-type labels, honest states | Lane 6 | **NOW:** BDVM truthful labels | explanation/provenance UI once V2 contracts settle | NOW | lane 6 | `claude/bdvm-truthful-labels` | vitest + a11y; real-browser check pending | revert |

Dedupe (all verified **open** 2026-09-30, none reopened or duplicated): #785 TE premium
(`F-VAL-01`/`C1-SRC-01`), #790 trade MC (`C3-MC-01`), #791 second opinions
(`C3-CALC-03`), #792 Analyze Trade (`C7-DESK-01`), #800 equalizer (`C3-EQ-01`), #802 special
teams (`C5-ST-01`), #803 league fit (`C5-FIT-01`), #838 young core (T-NEW-18,
IMPLEMENTED), #839 meaningful core (`C2-CORE-01`), #840 competitive posture
(`C7-POST-01`), #854 projection ensemble (`C5-ROS-01`). BDVM is `C5-BDVM-01`.

## D. Audit leads — status

| Lead | Status | Evidence |
|---|---|---|
| Coker exact live value/rank | **STILL UNKNOWN for the served response**; rebuild = 3286 / rank 156 / WR45 | replay pins; production `/api/data` needs owner auth |
| Coker gap explanation | **VERIFIED** (mostly current disagreement; + information age; + scale mixing; KTC outlier-excluded) | evidence README |
| V2-1 cross-subset freshness | **VERIFIED** | `data/scrape_state/idpTradeCalc_dataset.json`: 428 offense rows (incl. Coker) last changed 2026-08-28; broad changes on 09-15 (184 rows) and 09-23 (28 rows) were IDP-only; row age = `max(row, broad)` credits offense from 09-23 |
| V2-2 cadence vs information age | **VERIFIED** | three Coker voters dated 08-19..09-03 weighted as on-schedule |
| V2-3 weight-blind outlier filter | **VERIFIED (mechanism), latent** | characterization test; board census |
| V2-4 KTC Market as a third vote | **DISPROVED** | benchmark-only; registration refused at import |
| V2-5 native vs rank scale | **VERIFIED as measurement; cause UNKNOWN** | `board.nativeVsHill` |
| V2-6 haircut confuses certainty with value | **VERIFIED (design)** | ×0.30 value multiplier |
| Explain view contribution = actual blend | **DISPROVED** (it is a weighted-mean approximation) | `source_weighting_explain.py:190`; the replay's blend check replaces it for evidence |
| BDVM pick "median" | **VERIFIED** misnomer → fixed labels (Lane 6) | `picks.py:111` |
| BDVM malformed timestamps fresh | **VERIFIED → FIXED on branch** | RED 7 failing → GREEN |
| BDVM neutral placeholders | **VERIFIED**, documented | `service.py:103-132` |
| BDVM overlapping age/risk | **VERIFIED as design overlap**, magnitude UNKNOWN | engine/survival/uncertainty |
| BDVM "zero market inputs" | **PARTIALLY DISPROVED**: universe = market board; quarantined rows vanish silently; scale anchored to board-derived universe | `service.py:408,428` |
| BDVM pick values "market-anchored" | **DISPROVED** (comment false; display only) | `service.py:631` |

## E. BDVM — what the code actually computes (origin/main `4ae23193e`)

Every constant is a prior (`config/bdvm/params_v1.json` says so), and payloads carry
`provisional: true`.

- **Consensus projections:** `projections.blend_consensus`, with source weights, stale
  ×0.5, vocabulary-dominated ×0.25, trim at 5+ sources, cap 35%.
- **Replacement:** from projections only (`pool.py`, `replacement.py`).
- **Season path:** μ_t follows age curves and ascension; σ_t combines CV, source σ and
  drift.
- **Surplus:** option E[max(0, X−R)]·G.
- **Survival:** hazard S_t.
- **Strategy DV:** Σ u·d^t·S·SSV − λ·0.35·Ψ.
- **Display:** TV = 10000·(DV/anchor)^1.2, where the anchor sets the top priced player =
  9800.
- **Market layer strictly afterwards.**

Independence limits: see §D. Unsupported scoring keys score zero silently. K/DEF are
unpriced.

**Next measurable proprietary-model milestone (V5 baseline):** a versioned transparent
baseline computed and archived weekly with its inputs:

- opportunity-share forecasts from raw usage;
- regressed efficiency;
- empirical position age/persistence curves;
- observed replacement from actual rosters.

It is scored on held-out realized weekly usable points (best-ball lineup-legal) against
(a) current BDVM, (b) the market board, (c) a naive last-season baseline, with offense, IDP,
rookies and sparse players reported separately. No third-party rank or value may enter it.

## F. Signals — summary (full record: `docs/sources/SIGNALS_FANTASY_INTEGRATION.md`)

- **Does Signals affect canonical values now? No.** It is at activation stage 1
  (discovered and characterized from public pages).
- **Exact remaining gate:** Signals' **prior written consent for automated access and
  extraction** (Terms, effective 2026-08-31), plus the owner's active subscription and an
  owner-controlled session path.
- After that: stage 2 (real authorized observations ingested and replayable), then the
  existing source-promotion gates.
- The public board is order-and-tier only. It is never presented as values or as the
  league-adjusted product.

## G. Next dependency-ready batch

1. V2-1 cross-subset freshness correction (RED→GREEN, flag, whole-board evidence) — lane C.
2. Hill / native-source alignment audit using `board.nativeVsHill` (lane C; Hill Autopilot gates).
3. Unsupported-scoring-key reporting (lane D).
4. Signals: send the prepared permission request (owner action); on consent, build the
   adapter and fixtures, then do the first real capture.
5. Lane 6: provenance/information-age display in the existing value explainer, once
   V2-1/V2-2 settle the contract.
