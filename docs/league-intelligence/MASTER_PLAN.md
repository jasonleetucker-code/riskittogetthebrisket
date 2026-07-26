# League Intelligence Engine — Master Plan

Status: Phase 0–2 in progress · Owner: main orchestrator session
Spec: user directive 2026-07-26 ("League Intelligence Engine"). This plan
maps that spec onto the EXISTING repository — a large fraction is already
built and must be audited/extended, not duplicated.

## What the repo already provides (do NOT rebuild)

| Spec concept | Existing implementation | Status |
|---|---|---|
| Market value (KTC offense / IDPTC IDP) | `ktcSfTep` + `idpTradeCalc` value-direct sources in `_RANKING_SOURCES` | live |
| Consensus value | `src/api/data_contract.py::_compute_unified_rankings` (21+ sources, Hill curves, Hampel, count-aware blend) | live |
| TEP handling | per-source `is_tep_premium` flags, KTC TEP++ input, non-native 1.15 multiplier | live — §22 audit pending |
| Market/consensus guardrail | corridor clamp + single-source haircut in the blend | live — audit in §21.4 |
| Sleeper integration | scraper + `sleeper_overlay.py` (rosters, users, matchups, tx, traded picks, drafts) | live |
| ROS values | `src/ros/` (source ingestion, aggregate, team strength) | live |
| Lineup optimizer | `src/ros/lineup.py` | live — **must audit slots vs live config (see SETTINGS_AUDIT: registry is stale)** |
| League Twin (partial) | `src/ros/playoff_sim.py` + `championship.py` (empirical distributions, playoff/championship odds) | live |
| Trade engines | `src/trade/suggestions.py`, `finder.py`, trade simulate | live |
| Waiver/FAAB | FAAB v2 contention engine (`faab_contention.py`) | live |
| Player context | `src/playerctx/` (contracts, snaps, depth) | live |
| Pick values | pick tethering + year discount + Pick Projector (`src/ros/pick_projection.py`) | live |
| League behavior intel | `src/intel/` Sharp Tracker | live |
| News signals | `src/news/` (structured, 7-day cutoff, digests) | live |

## What is genuinely NEW (build order)

1. **LI-1 Canonical league config + settings audit** — versioned canonical
   config from live Sleeper API, screenshot evidence, repo values; fix the
   stale registry rosterSettings (with consumer verification). → `config/league_intel/`, `src/league_intel/config.py`
2. **LI-2 Deterministic exact scorer + golden validation** — pure
   `score_stat_line(stat_line, config)` covering all 141 scoring keys,
   validated against host-awarded historical player scores and team totals.
   → `src/league_intel/scorer.py`, `tests/league_intel/`
3. **LI-3 True best-ball optimizer** — exact 21-slot legal-lineup solver
   (assignment problem, multi-eligibility), historical starter
   reconstruction validation. Audit/extend `src/ros/lineup.py` first —
   prefer fixing it over a parallel optimizer (CLAUDE.md rule 2).
4. **LI-4 Value schema + centralized selector foundation** — parallel value
   fields (`leagueAdjustedDynastyValue` = consensus no-op until validated),
   versioned snapshots, `getActiveValue()` service, global mode toggle
   (default consensus). Frontend integration WAITS for redesign R2 merge
   (rankings page + PlayerPopup are owned by the R2 agent right now).
5. **LI-5 Replacement/scarcity engine** — starter/best-ball/roster/waiver
   replacement from the real 12×58 pool with endogenous flex allocation.
6. **LI-6 Projection re-scoring** — run existing ROS source projections
   through the exact scorer; source audit per §7; derived first-down/
   distance-band estimation with provenance tiers.
7. **LI-7 League-adjusted correction** — confidence-weighted delta vs
   consensus with the three-guardrail system (§21), TE residual (§22),
   explanations (§35).
8. **LI-8 Best-ball weekly simulation + League Twin extension** — extend
   playoff_sim with exact scoring + exact lineups; trade deltas on shared
   seeds.
9. **LI-9+** Archetypes/role states, rookie priors, champion–challenger
   MLOps, contextual values (contender/rebuilder/roster-specific), waiver
   score v2, movement views. Phased per spec §42; each earns its place.

## Sequencing constraints (live agent coordination)

- Redesign R2 agent owns `frontend/app/rankings/` + `PlayerPopup.jsx` (in
  flight). E2E agent owns `tests/e2e/`. LI work is backend-first in NEW
  territory (`src/league_intel/`, `config/league_intel/`, `tests/league_intel/`,
  these docs). UI toggle lands after R2 merges, via the R1 nav-model/TopBar
  (stable) + `getActiveValue()` adoption per page.
- Registry rosterSettings fix touches shared config — coordinate: verify
  every consumer (FAAB `analyze_roster`, ros lineup slots, draft capital)
  with tests in the same PR. See DECISIONS ADR-002.

## Non-negotiables carried from the spec

- League value starts as consensus no-op; never fabricate adjustments.
- Terminology fields exactly as §2 (market/consensus/leagueAdjusted...).
- Every material departure → ADR in DECISIONS.md.
- Champion–challenger before any model replaces production behavior.
- Time-aware validation only; no leakage; no invented data access.
