# League-specific scoring, roster and valuation audit — 2026-10-19

**Status: PARTIAL EVIDENCE AUDIT / research baseline — NOT a complete site-wide certification.**  
**League:** `dynasty_main` / Sleeper `1312006700437352448`.  
**Scope:** Calculator repository only. Main-branch source reviewed 2026-10-19.  
**Important verification boundary:** a live call to `https://api.sleeper.app/v1/league/1312006700437352448` was not available in the audit environment. The host snapshot below is **archived 2026-07-26 evidence**, not proof of October 2026 settings. Running the companion `scripts/audit_league_settings.py --live --strict` in a networked environment is a **P0 verification prerequisite** before claiming live parity.

## 1. Actual recorded league shape

`config/leagues/registry.json` and `config/league_intel/sleeper_league_snapshot_2026-07-26.json` record a 12-team best-ball league, 58 rostered slots, zero taxi, 21 starters: QB 1, RB 2, WR 3, TE 2, FLEX 2, SUPER_FLEX 1, K 1, DL 3, LB 3, DB 3. The snapshot records 7 playoff teams beginning week 15; 6 rookie draft rounds and $100 FAAB. **Do not substitute previously discussed League Tycoon / 10-IDP proposals.**

Scoring is not ordinary PPR. Examples from the snapshot: `pass_yd=.0333333`, `pass_td=6`, `pass_int=-4`, `pass_cmp=.15`, `pass_inc=-.22`, `rush_att=.08`, `bonus_fd_qb=.67`, `bonus_fd_rb/wr/te=1`, `rec=.08` plus reception-distance bands, `idp_tkl_solo=1.33`, `idp_tkl_ast=.8`, `idp_tkl_loss=4.25`, `idp_sack=2.92`, `idp_qb_hit=2.13`, `idp_pass_def=5.32`, `kr_yd/pr_yd=1/30`. Kicking pays `fgm_yds=.07` rather than a flat successful-FG base. Every nonzero or zero key must be reconciled, not just these examples.

### Tight end is two separate questions
The snapshot has `bonus_rec_te=0` and `bonus_fd_te=1` (same bonus as WR/RB) while requiring **two TE starters**. It is inaccurate to infer a scoring premium solely from the two mandatory TE slots. `src/league_intel/te_premium.py` separates source-format normalization from structural demand and reports a TE++ target basis for two required TEs. Validate whether that basis aligns with actual outcomes and avoid applying another lift to a TE++ normalized source. The registry's `superflex_tep15_ppr1` label may describe historical assumptions, not the complete current rate card.

## 2. Source-to-consumer trace, observed from code

| Layer | Verified path | What is demonstrably implemented | Evidence gap / risk |
|---|---|---|---|
| League registry | `src/api/league_registry.py`, `config/leagues/registry.json` | Default/secondary league mapping; roster settings and league key. | Its `scoringProfile` label is explicitly a marker, not proof of a per-league scoring computation; live drift unverified. |
| Full-fidelity config | `src/league_intel/config.py` and dated snapshot | Validates Sleeper scoring/slots and has drift detection/refresh machinery. | Reconcile active deployed snapshots and use one live confirmed rule version. |
| Scoring engine | `src/league_intel/scorer.py`; `src/scoring/sleeper_ingest.py` | Exact-score dot product and aliases; prior goldens 1,415/1,415 archived 2025 player-weeks within .011 under 2025 rules. | This is not a 2026 host-week reconciliation; confirm 2026 unusual stacking and any missing keys. |
| League scoring-fit | `src/league_intel/scoring_fit.py` | Historical re-score-based **positional** IDP fit; corrections documented for `idp_qb_hit` alias. | Per-player adjustment from sparse historical IDP event rates was rejected as noisy; update with robust projections only if validated. |
| Structural scarcity | `src/league_intel/replacement.py`, `src/ros/lineup.py` | Exact lineup assignment and replacement tiers with FLEX/SFLEX; recorded 2025 TE FLEX share 10.4% vs 0% from mean-index route. | Mean `rosValue` masks weekly spike participation in best ball. Current bench/roster availability varies with identity freshness. |
| Canonical value | `src/api/data_contract.py::_compute_unified_rankings` | Weighted source rankings → canonical `rankDerivedValue`; Superflex and TE++ source-basis alignment are documented. | Not equivalent to exact-league intrinsic projected production. Audit all source basis and second-opinion fallbacks. |
| Optional adjusted bundle | `src/league_intel/values.py`, `publish.py` | Stores `marketValue`, `consensusValue`, `leagueAdjustedDynastyValue` independently. | Presence of a bundle value **does not** establish canonical adoption. |
| Canonical promotion boundary | `frontend/lib/valuation-mode.js`, `server.py::_valuation_scoped_contract` | The 2026-08-14 league lens was withdrawn: frontend returns market, backend ignores requested `leagueAdjusted` and returns canonical contract. | Preserve this until a separately validated replacement is authorized. |
| Seasonal projected points | `src/ros/projection_observations.py`, `projection_ensemble.py` | Raw stat lines can be re-scored through caller league rules. Full-season ensemble built from registered provider families. | Provider coverage uneven; multi-family seasonal projection does NOT automatically modify dynasty canonical value. |
| Best-ball trade utility | `src/roster_intel/best_ball_utility.py` | Samples weekly outcomes and re-optimizes lineup per simulated week; can use league-scored ensemble. | Its own assumptions state independent player draws; missing/uncertain availability and full-season-rate-as-weekly-proxy may bias value. |
| Trade engine contract | `server.py::_valuation_scoped_contract` | Multiple trade / waiver endpoints share a declared canonical-value boundary. | Need per-endpoint sensitivity tests of rules, pick valuations, timing, league-key scope. |

## 3. League configuration propagation matrix — inspection and test queue

**Legend:** CODE = execution path inspected; DOC = historical design document only; TEST NEEDED = not yet empirically proven on current production; NO CREDIT until counterfactual output check. This matrix is a **work queue**, not a blanket PASS.

| Consumer family | Rule dimensions to vary in metamorphic tests | Current evidence / next action |
|---|---|---|
| Rankings, player profiles, Source Opinions, VA | SFLEX, TE demand, dynasty basis; scoring categories | CODE canonical source blend. Test input-to-output provenance; do not mislabel canonical as exact-league PPG. |
| Trade Calculator, War Room, trade history, public advisor | Scoring, starters, roster supply, best ball, active value mode, historical as-of | CODE shared canonical contract. TRACE EACH route, including historical scoring version and price basis. |
| Finder / Golden Trades / packages | Player values, league-key, roster needs, bench space, package sizes | TEST NEEDED: inspect `src/trade/` consumers and compare decisions when slots differ. |
| Rosters / power rankings / matchup / playoffs | All 21 starting slots, hybrid eligibility, weekly variance, best ball, opponent schedule | CODE exact optimizer & sim components exist; require randomized optimizer parity and 2026 host reconciliation. |
| Waivers / FAAB / roster constraints | 58 slots, bench depth, replacement supply, 9 IDP, lineup capacity | TEST NEEDED: ensure league registry reaches every public/private route. |
| Rookie picks / draft / auction | Team count, rookie class, picks, roster scarcity, age, future seasons | TEST NEEDED: distinguish market pick price, future production and pick ownership. |
| IDP stats / projections | Hits, TFL, tackles, PD, position hybridity, cumulative-event stacking | CODE alias fixes documented; verify per-player 2026 scoring, no zero-filling missing stat columns. |
| K, returns and special teams | Distance-dependent kicking, player return yards, eligibility | DOC notes historical repair and an unmerged host-native challenger; verify live branch state before changing production. |
| Multi-league selection | `dynasty_main` vs `dynasty_new` (non-IDP) | CODE registry includes a second distinct league; test request league-key isolation and cache keys. |

## 4. Confirmed pitfalls to address, without premature behavior changes

1. **Live source of truth unavailable in this audit run.** The archived snapshot is a reference, not a current verification. A code-backed, read-only drift/fingerprint tool is included.
2. **Canonical dynasty value ≠ projection or exact league utility.** Production withdrawal of the league-adjusted lens is documented in `docs/valuation/LEAGUE_AWARE_METHODOLOGY_REJECTION.md`. Do not silently revive it.
3. **Best-ball demand requires full weekly distributions.** Mean-based flex allocation misses spikes; historical weekly replay already documents this.
4. **Source census ≠ functioning production fetch.** `config/projections/source_capability_census.json` distinguishes LIVE, IMPLEMENTED_FLAG_OFF, GREENFIELD and RANKINGS_ONLY. Check runtime snapshot freshness and access rights.
5. **No unmeasured 0–9999 multiplication.** Prior method used `rosValue` (rank index) as if it were physical points, omitted roster size/team count mathematically, and risked SF/TE double counting. It was rejected on 2026-08-14.
6. **Past documents are not deploy proof.** Several docs describe work awaiting merge, flags or host verification. Inspect main, active PRs, deployment/version before declaring complete.
7. **Separate player market price, exact league intrinsic forecast, and roster-specific marginal value.** They have different calibration and validation targets.

## 5. Implementation evidence / next gates

The accompanying read-only `scripts/audit_league_settings.py` produces a stable SHA-256 fingerprint of the exact archived or currently fetched host scoring + rules (excluding transient progress fields) and explicitly labels `LIVE_SLEEPER_API` vs `EXPLICIT_ARCHIVED_SNAPSHOT`; `--strict` fails on registry drift. It **does not** modify canonical configuration. Tests cover matching roster structures, Superflex aliases, scoring changes, key-order stability, drift and fail-closed malformed input.

**Remaining audit work, not represented as completed here:** current Sleeper GET, 2026 host-awarded score sample, route-by-route end-to-end trace across frontend/backend, shadow challengers, longitudinal outcome holdouts, and production deploy verification. Log these against the issue/plan before upgrading this report's status.

## 6. Owner-approved precedence

Preserve already approved source voting, value adjustment, league-specific strategy and parallel-development policy. Do not overwrite active PRs. League Tycoon contract conversion remains postponed. Source ingestion is separate from voting activation; seasonal projection models do not become dynasty voter sources. Model promotion needs outcome evidence, appropriate review and owner authorization.
