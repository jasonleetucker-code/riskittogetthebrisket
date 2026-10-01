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
| V1 | Reproducible current-value evidence (Coker + contrasts) | `src/api/value_replay.py` + `scripts/value_replay.py` | **MERGED + DEPLOYED** (#1562, `5385a6907`, in `7db3f3144`); stamps explain published offense values (within 1 point, stamp-consistency) | Live served response capture needs owner auth | DONE (extended by Batch 2 Unit B) | lane C | #1562 | tests + pinned evidence | tooling only |
| V2-1 | Cross-subset freshness (IDPTC IDP edits refresh offense) | `src/sources/freshness.py` (`universe_clock`) | **MERGED + DEPLOYED + flag LIVE** (#1565, `0c7830a55`) | — | DONE | lane C | #1565 | RED→GREEN, whole-board evidence, review APPROVE | `RISKIT_FEATURE_SOURCE_UNIVERSE_FRESHNESS=0` |
| V2-2 | Cadence vs information age | `freshness.py` | **Verified** (Coker: three voters carry pre-season data, applied weights 1.0 / 0.5 / 0.057; removing them +196) | Season-event-aware information age; must not teach outages as normal | LATER (methodology) | lane C + owner review | — | challenger report, not auto-promotion | — |
| V2-3 | Weight-blind outlier filter | `data_contract._hampel_filter_per_player` | Mechanism verified; latent on the measured board | **Owner decision B (2026-10-01):** treat it jointly with V2-6, no isolated filter patch | **NOW — Batch 2 Unit C** (disabled/shadow challenger) | Batch 2 decision B + lane C | `claude/joint-outlier-sparse-challenger` | full-pipeline tests, full-board diagnostics, independent review; promotion needs separate candidate approval | flag off = legacy |
| V2-4 | Lineage / independence | `cap_family_weights`, B10 families, B11 confidence | KTC Crowd and Trades are separate families; KTC Market is benchmark-only (refused at import) | Asset-specific dependencies; IDPTC↔IDP Show; Signals ancestry | LATER | lane C | — | — | — |
| V2-5 | Native value vs rank→Hill | Hill masters + `_VALUE_BASED_SOURCES` | Measured 2026-09-30 (KTC Crowd 14–45%, Trades 22–60% above Hill(own rank); IDPTC confounded by population) | Separate scale / population / disagreement | **NOW — Batch 2 Unit B** (read-only audit) | lane C; calibration only as a Hill Autopilot challenger | `claude/hill-alignment-audit` | pinned audit artifact + one recommendation | none (read-only) |
| V2-6 | Confidence vs value (single-source haircut) | `_SINGLE_SOURCE_VALUE_RETENTION`, `confidence.py` | Haircut multiplies value by 0.30 | **Owner decision B:** the design principle "one family ⇒ 30% of the estimate" is rejected; express thin coverage as uncertainty | **NOW — Batch 2 Unit C** | Batch 2 decision B | `claude/joint-outlier-sparse-challenger` | as V2-3 | flag off = legacy |
| V2-7 | Ingestion integrity | `dataset_integrity.py`, source health | existing health/coverage gates | not re-audited this batch | LATER | lane C | — | — | — |
| V3 | BDVM formulas / semantics | `src/bdvm/` | leads a–d verified; (b) **MERGED + DEPLOYED** (#1563); (a) labels **MERGED + DEPLOYED** (#1564); (c)/(d) documented | (c)/(d) remain priors | DONE (b, a) / LATER (c, d) | lane D, lane 6 | #1563, #1564 | RED→GREEN; UI tests | revert |
| V3-S | Exact scoring coverage | `src/bdvm/scoring.py`, `projections.py`, `service.py` | **Unsupported rules are now REPORTED** per player and in `meta.scoringCoverage` (#1566, deployed). Their projected contribution is still unavailable, and the omitted contribution may be positive or negative | Census, exact mappings where fields exist, capable feed for the rest | **NOW — Batch 2 Unit D** | lane D | `claude/bdvm-scoring-census` | pinned census; reporting-only tests | revert |
| V4 | Signals data integration (W1) | canonical source registry + `src/sources/*` + #791 second opinions | **Permission resolved (owner-attested 2026-10-01).** Public boards accessible; paid surfaces need an owner session (access dependency) | Real capture, second opinion, then shadow eligibility | **NOW — Batch 2 Unit A** | Batch 2 decision A | `claude/signals-adapter` | real capture + replay + labelled second opinion; stage 4/5 need comparable native values | disabled by default |
| V4-P | Signals product capabilities (W2) | #792, #838/#839/#840, draft/waiver/profile owners | capability matrix written | per-capability units | NEXT/LATER | per owning lane | same doc | per unit | — |
| V5 | Point-in-time raw data + independent BDVM challenger | `src/history/`, `src/bdvm/` | BDVM universe = market board rows; priors uncalibrated | Baseline milestone (below) | LATER | owner-gated promotion | — | held-out evidence | — |
| V6 | Own completed-trade market model | CE-01 ledger, `C4-MTL-*` | KTC trade DB lane unblocked by B | Ingestion then latent-price challenger | LATER | lane B/C when scheduled | — | time/league holdouts | — |
| V7 | Three-part decision UX | #792 | Analyze Trade exists | separate fundamental/market/roster panels; no cross-scale subtraction | LATER | lane B + 6 | — | #792 acceptance | — |
| V8 | Evaluation / release | this map + CI | — | targets defined before tuning | continuous | — | — | — | — |
| UI | Value-type labels, information age, scoring coverage, Signals second opinion | Lane 6 | BDVM truthful labels **MERGED + DEPLOYED** (#1564); real-browser check of private pages open | information-age explainer, BDVM partial-scoring notice, Signals second opinion | **NOW — Batch 2 Lane 6** | Batch 2 decision D | `claude/lane6-information-age` | component/contract tests, a11y, browser checks where access exists | revert |

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

- **Permission: resolved.** Owner-attested on 2026-10-01: *"I have explicit permission to use
  signals how I see fit."* The 2026-09-30 permission request is superseded and was never sent.
- **Access:** public boards are reachable without login. Paid, native-value and projection
  surfaces need an owner-controlled session — an access dependency.
- **Values:** Signals does not affect canonical values. The public boards are positional
  rank + tier only, with no native scale, so they are ineligible to vote. Stage evidence is
  in the Signals record §8 (Batch 2 Unit A).

## F2. Batch 1 outcomes (closed out 2026-10-01)

| Unit | PR | Merged | Deployed / production evidence | Independent evidence |
|---|---|---|---|---|
| V1 replay + records | #1562 | `5385a6907` | in `7db3f3144`, run 36795430875, smoke `PASS build.commit` | review APPROVE (after REQUEST_CHANGES: unpinned inputs, doc numbers); claims verified vs pinned diff + PR Validation (#1542 grader, strict) |
| V2-1 universe-aware freshness | #1565 | `0c7830a55` | in `7db3f3144`; live `/api/status` `source_universe_freshness` enabled/LIVE | review APPROVE (after perf fix +65% → +4%); grader strict PASS |
| V3 lead b — BDVM timestamps fail closed | #1563 | `017a8a7d9` | in `1e59e06a5`, run 36790190316, `PASS build.commit` | review APPROVE |
| V3 lead a / Lane 6 — BDVM truthful labels | #1564 | `1e59e06a5` | same run | vitest 3075/3075; real-browser check of private pages NOT done |
| V3-S — unscored card rules reported | #1566 | `71d5d9dcd` | run 36805504364, `PASS build.commit == 71d5d9dcd…` | grader strict PASS |

Production served values for these changes cannot be read without an owner login, so served-value effects are verified only on the pinned rebuild. The facts verified in production are the shipped commit identity and flag state. The census `meta.scoringCoverage` (#1566) on `/api/bdvm/values` will show which card rules the production projections leave unscored, once read with owner auth.

## G. Batch 2 (owner directive 2026-10-01) — units and claims

| Unit | Scope | Branch | Gate |
|---|---|---|---|
| Records | permission recorded, stale status corrected, decisions A–E captured | `claude/batch2-records` | governance gates |
| A | Signals real collection (public dynasty + IDP dynasty boards), identity, private archive, #791 second opinion | `claude/signals-adapter` | real capture; ingestion/privacy review |
| B | Hill / native-source alignment audit (read-only), one recommendation | `claude/hill-alignment-audit` | pinned artifact; calibration only as a registry challenger |
| C | Joint outlier / sparse-source challenger, disabled/shadow, legacy reproducible | `claude/joint-outlier-sparse-challenger` | full-board diagnostics; independent review; promotion needs candidate approval |
| D | BDVM scoring census, sign-aware wording, exact mappings only where fields exist | `claude/bdvm-scoring-census` | pinned local census (no owner session) |
| Lane 6 | information age + provenance in the value explainer; BDVM partial-scoring notice; Signals second opinion | `claude/lane6-information-age` | a11y, mobile parity, browser checks where access exists |
| Integration | manual-deploy SHA pinning (owner decision C) | `claude/deploy-sha-pinning` | independent review; workflow tests |

**Owner decisions recorded 2026-10-01:**
- **(A)** Signals is built toward an active validated source; numeric participation goes
  through promotion stages.
- **(B)** Outlier handling and sparse confidence form one pipeline problem; one family does not
  mean 30% of the estimate.
- **(C)** Manual-deploy SHA pinning is approved.
- **(D)** Lane 6 stays active in parallel.
- **(E)** Bounded non-promotional units may be implemented, reviewed, merged and deployed
  when gates pass. Candidate-specific approval for new canonical models/weights stays in
  force.

Kept in their existing backlog positions: V5 independent fundamentals, V6 completed-trade
estimator, #792 three-part UX.

