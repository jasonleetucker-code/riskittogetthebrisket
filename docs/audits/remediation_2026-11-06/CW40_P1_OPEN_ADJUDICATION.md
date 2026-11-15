# CW-40: adjudication of 5 "still open" master-site-audit P1 findings

Adjudicated against `main` at `9386025865` (2026-11-06), the same way `CW40_P0_ADJUDICATION.md` did for the P0s.
The November recount called these five "still open" with a tool (`verify_closure.py`) that never compared repro output
to expected (NEW-02 in `build_inventory.py`), so that label carries no evidence either way. Every repro below was
rebuilt offline: pure functions, synthetic inputs, the tracked export archive, or a tracked evidence artifact. No
network, no live board, nothing written outside tmp. Nothing in this PR changes served behaviour, values, thresholds,
identity policy or edge methodology; it adds tests and this record only.

| id | classification | one-line evidence |
|---|---|---|
| W06-F001 | PARTIAL | scraper has a first-name-drift rung, but the must-have rookie guarantee re-creates the Hibner and Miller ghosts after it; both still on the 2026-11-06 archive board |
| W10-F003 | PARTIAL | Perfect Draft optimizer exists and is mounted; the old Next Best Targets panel is unchanged and still returns 0 rows at budget advantage 1.0 to 3.0 |
| W13-F003 | OPEN | current `market_comparison` + `buy_hold_sell` over the audit's recorded inputs reproduce 570 STRONG_SELL of 676 market-anchored rows exactly |
| W27-F001 | OPEN | 430/430 IDP rows render "—" on /rankings and match no `edge=` filter; `idpMarketAction` gives 323 of them BUY/SELL on /edge |
| W30-F002 | PARTIAL | zero-games state now refuses by name, with or without ROS strength; the convergence gate still certifies a zero-variance 0/1 result (latent, unreachable from production builders) |

## W06-F001 (split-identity ghost rows)

**Claim.** Name-variant drift left one human on two rows: a resolved row and an id-less ghost holding the vendor votes
(Matt/Matthew Hibner, Jam/Jamarion Miller). `duplicateCanonicalIdentityCount` was 0 because it keys on exact equality.

**What was fixed.** `Dynasty Scraper.py:4468-4530` ("Second rung: first-name drift") folds an id-less ghost into the
single identified row it is a first-name variant of (`name_clean.is_first_name_variant`, `src/utils/name_clean.py:787`;
prefix >= 3 chars, identical surname and middle parts), refuses ambiguous ghosts, never fuses two identified rows. Rule
pinned by `tests/api/test_first_name_variant_ghosts.py` (the gate there is a replica of the scraper loop; the new test
below pins the real wiring by source shape).

**What is still broken.** On the newest tracked archive board (`exports/archive/dynasty_export_20261106_194518.zip`,
raw payload `players` dict):

| ghost | resolved row | ghost carries |
|---|---|---|
| `Matthew Hibner` (no `_sleeperId`, no position) | `Matt Hibner` (13324, TE, BAL) | `_fallbackReason: must_have_rookie_guarantee`, `_composite 1160` |
| `Jamarion Miller` (no `_sleeperId`) | `Jam Miller` (13403, RB, ATL) | `_fallbackReason: must_have_rookie_guarantee`, `_composite 2207` |

The contract built from that payload keeps both rows (`Matt Hibner` rank 296, `Matthew Hibner` unranked, with
`dlfRookieSf` / `draftSharks` / `flockFantasySf` stranded on the ghost); `validationSummary.duplicateCanonicalIdentityCount`
is still 0. Of the 136 id-less rows in the raw payload, exactly these two are first-name variants of a resolved row.

**Cause (changed since the audit).** The vendor-CSV ghost path was repaired, but the ghosts are now created by a
different path that runs after the rung. `rookie_must_have.txt` lists `Matthew Hibner` (line 109) and `Jamarion Miller`
(line 47). The must-have rookie guarantee (`Dynasty Scraper.py:6555-6640`) resolves each listed name to an existing row
only by exact key or `normalize_lookup_name` (`_norm_to_player_key`), then identity-resolves it with a guard that
rejects any match whose normalized name differs from the listed one. Neither check understands a first-name variant, so
it mints a fresh fallback row. Both ghosts come from this file.

**Classification.** PARTIAL. Closed: vendor-CSV ghosts (the audit's mechanism). Open: must-have rookie ghosts, the same
two players the finding named.

**Smallest candidate repair.** In the must-have loop, before creating a row, look for a unique identified row that
`is_first_name_variant` of `_clean_nm` (the same single-match, identified-only gate the rung uses) and reuse its key.
Alternative with the same effect: run the dedup rung again after the guarantee. Gate: identity policy. This is the
C1-ID-01 scope (the `CANONICAL_V2` first-name-variant rung, `docs/identity/C1_ID_01_IDENTITY_CONSOLIDATION.md` §9) and
needs the owner-authorized identity unit; not changed here. The data-only alternative (rename the two lines in
`rookie_must_have.txt` to the Sleeper spellings) would hide the mechanism and is not recommended without that unit.

**Test added.** `tests/identity/test_audit_w06_f001_regression.py`: wiring of the rung and its identity gate (passes);
every surviving ghost is a `must_have_rookie_guarantee` row listed in `rookie_must_have.txt` (passes, documents the
cause); `xfail(strict)` "no unresolved row is a first-name variant of a resolved row", pinned to the one tracked archive
bundle by name (skips if retention removes it).

## W10-F003 (no perfect-draft optimizer; Next Best Targets empty)

**Claim.** The only recommender was `nextBestTargets`, whose EV is `max(0, inflatedFair - myWinningBid) * tagWeight`; for
a contested player `myWinningBid = topCompetitorMax + 1` clears `inflatedFair`, so the surplus is 0 and the `ev <= 0`
filter empties the panel at budget advantage (BA) >= 1.

**Live path now.**
- Optimizer: exists. `frontend/lib/perfect-draft.js` exports `optimizeDraft` (`:1146`), `computeMaxBid`, `evaluateBid`,
  `solveFrontier`; server side `src/draft/` + `GET /api/draft/roster-context`; flag `perfect_draft` default on
  (`src/api/feature_flags.py:591`). `PerfectDraftPanel` is mounted at `frontend/app/draft/page.jsx:5121`. "No optimizer"
  is closed.
- The audited panel was not removed. `NextBestTargets` is still mounted (`page.jsx:2788`, `:5102`) and
  `draft-logic.js:1983` `nextBestTargets` is unchanged in model: `surplus = max(0, p.inflatedFair - p.myWinningBid)`
  (`:1991`), `if (ev <= 0 && p.userTag !== TAG_TARGET) continue` (`:2000`). The only change is the empty-state copy
  ("tag a few players as target to seed EV ranking", `page.jsx:2793-2800`) and that a tagged target bypasses the filter.

**Rebuilt repro.** Node ESM import of the real `draft-logic.js` (same scenario as the audit's
`probe-nbt-emptiness.mjs`, minus the removed `initialSlots`), 3 players (60/35/30) vs one rival:

| my budget | rival budget | BA | `nextBestTargets` rows |
|---|---|---|---|
| 100 | 100 | 1.0 | 0 |
| 110 | 100 | 1.1 | 0 |
| 150 | 100 | 1.5 | 0 (every player: `myWinningBid = inflatedFair + 1`) |
| 300 | 100 | 3.0 | 0 |
| 100 | 60 | 1.66 | 0 |
| 100 | 300 | 0.33 | 3 |
| 100 | 20 | 5.0 | 3 |

BA 1.0/1.1/1.5/3.0 -> 0 rows, as audited. A user-tagged target at BA 1.5 does surface.

**Classification.** PARTIAL. Closed: no optimizer. Open: the untagged Next Best Targets panel is empty across the
ordinary budget-advantage range; it now explains itself but the EV model that causes it is untouched.

**Smallest candidate repair.** Retire the EV panel in favour of the Perfect Draft plan (the panel's own purpose is now
served by `planMaxBid` / the frontier), or seed `nextBestTargets` from `lib/perfect-draft.js` pivots instead of the
per-player surplus. Gate: product decision on /draft (UI, not a methodology constant); not done here.

**Test added.** `frontend/__tests__/audit-w10-f003-regression.test.js`: `optimizeDraft` exported and
`<PerfectDraftPanel` mounted (pass); populated regime at BA 0.33 and the tagged-target mitigation (pass);
`it.fails` "untagged panel is non-empty at BA 1.5" so it goes red when the EV model is fixed. **Verification
limit:** vitest cannot start in this worktree (no `node_modules`; `vitest.config.js` needs its plugins), so every
assertion was replicated and run under plain `node` against the real modules (outputs above); CI is the first
vitest run.

## W13-F003 (BDVM signal saturation)

**Claim.** `DynastyEngine.calibrate` anchors only the top asset to `target_top_value` (9800); `signal_thresholds` are
absolute (+/-400, +/-900). With the fundamental median (511.6) far below the market median (1914.5), 570 of 699 priced
players read STRONG_SELL.

**Live path now.** Unchanged in kind. `src/bdvm/engine.py:290-299` (`calibrate`: per-strategy max only);
`src/bdvm/market.py:256-257` (`gap = fund_balanced - market_tv`, `alpha = gap * effective_liquidity`);
`config/bdvm/params_v1.json:544-550` (`strong_sell_alpha -900.0`, `sell_alpha -400.0`, `buy_alpha 400.0`,
`strong_buy_alpha 900.0`); `buy_hold_sell` ladder at `market.py:291-367`. The audit's M7 liquidity sign fix is in
(`market.py:105-117`, dispersion subtracts) and the market anchor is now KTC Market first
(`VALUE_MARKET_SOURCES`), neither of which touches the shape mismatch.

**Rebuilt repro (offline).** A full live re-run needs the nflverse weekly feed (`repro_engine_run.py` calls
`ingest.fetch_weekly_stats`), so the repro freezes the INPUTS: the audit's recorded per-player `tradeValue` and `market`
blocks (`docs/master-site-audit/evidence/W13/engine-live-run.json`, tracked) are fed through today's
`market_comparison` + `buy_hold_sell` with the recorded `p_value_collapse_1y`. Result on current main, identical to the
audit's recorded counts:

`STRONG_SELL 570, HOLD 69, NO_MARKET 23, BUY 14, SELL 13, STRONG_BUY 10`; 676 market-anchored rows, STRONG_SELL share
0.843 (0.815 of the 699 priced). Medians over those rows: fundamental balanced 511.6, market 1914.5, gap -1228.8.

**Limit, stated plainly.** This proves no code since the audit changes the signal distribution for those inputs. It does
not prove today's live board still saturates (the fundamentals depend on a projection snapshot not available offline).

**Classification.** OPEN.

**Smallest candidate repair.** Make the comparison shape-aware: re-anchor the fundamental board to the market's own
scale before taking the gap (for example match the median or a rank-order quantile map per asset group), or express
the thresholds as quantiles of the day's `alpha` distribution rather than absolute points. Either changes what STRONG_SELL
means. Gate: BDVM methodology (owner / evidence gated; `params_v1.json` values are labelled priors, and `CLAUDE.md`
keeps BDVM thresholds out of automatic change); not changed here.

**Test added.** `tests/bdvm/test_audit_w13_f003_regression.py`: ladder control (passes);
`xfail(strict)` "STRONG_SELL share <= 0.5" over the frozen artifact through the current logic. A repair confined to
calibration will not flip it (inputs are frozen); the evidence artifact must then be regenerated from a pinned input.

## W27-F001 (IDP rows carry no Edge signal on /rankings; second detector on /edge)

**Claim.** The retail anchor is KTC, KTC publishes no IDP, so every IDP row has no gap on /rankings, while /edge runs a
second detector (`idpMarketAction`, IDPTC as the anchor) that labels the same players BUY/SELL.

**Live path now.** The backend half moved but the outcome did not. The gap is now our `rankDerivedValue` vs KTC Market
(`data_contract.py:4764` `_compute_market_gap` -> `src/sources/ktc_market.py::compute_market_gap`); IDP rows stamp
`ktcMarket: {available: false, reason: "no_ktc_coverage"}` (`ktc_market.py:67`) and `marketGapDirection: "none"`.
Frontend: `marketAction` (`display-helpers.js:275`) returns "—" for a row without `ktcMarket`; `rowMatches` edge filter
(`player-filters.js:176-185`) compares `marketGapDirection` to `retail_premium` / `consensus_premium`; /edge still calls
`idpMarketAction` (`display-helpers.js:477`, `edge/page.jsx:181,192`), which compares IDPTC's value contribution to the
mean of the IDP expert sources.

**Rebuilt repro.** Newest complete archive board (`newest_complete_contract()`, `dynasty_export_20261106_194518`), 430 IDP
rows (DB 150, DL 165, LB 115; all 430 carry an `idpTradeCalc` value):
- `marketGapDirection` is `none` on 430/430; offense rows carry `retail_premium` / `consensus_premium`.
- The real frontend helpers imported under node over those rows: `marketAction` label `—` on 430/430;
  `idpMarketAction` BUY 238 / SELL 85 / HOLD 15 / `—` 92; `edge=buy` and `edge=sell` filters match 0 IDP rows;
  323 rows are `—` on /rankings and BUY or SELL on /edge (for example Abdul Carter, Aidan Hutchinson).

**Classification.** OPEN (unchanged outcome; the detector pair is now different: KTC Market value-space vs IDPTC
value-space).

**Smallest candidate repair.** One owner for the gap: stamp the IDP gap in the contract (IDPTC value vs the IDP
consensus, the same quantity `idpMarketAction` derives client-side) so `marketAction` and the filter read it, and delete
the client-side second computation; or explicitly label the /rankings Edge column "offense only" for IDP rows instead of
a bare "—". Gate: edge-detector methodology. Which IDP benchmark counts is an evidence and signal-independence
question (IDPTC both anchors and votes in the blend), so it is owner-gated; not changed here. The label-only variant is
presentation-only and could ship without the methodology gate if the owner wants it.

**Test added.** `frontend/__tests__/audit-w27-f001-regression.test.js` on a trimmed copy of the real Abdul Carter row:
offense control (SELL, filter matches), `idpMarketAction` verdict `sell`, `marketAction` is `—` (all pass);
two `it.fails`: /rankings verdict equals /edge's, and `edge=sell` matches the IDP row. Same node-replication note as
W10-F003 (vitest not runnable here; assertions run under node).

## W30-F002 (playoff odds certainty with zero games played)

**Claim.** Both engines published exactly 1.0/0.0 with zero games played and 14 weeks left, and `converged: true` with
`worstPlayoffOddsSe 0.0`.

**Live path now.**
- `src/public_league/playoff_odds.py` no longer simulates: it is an adapter over `src/ros/playoff_sim.canonical_forecast`
  (module docstring, C5-PLAY-01). The retired resampling loop and its `[100.0]` placeholder that caused the audited
  alphabetical 1.0/0.0 are deleted.
- `simulate_playoff_odds` (`playoff_sim.py:1334`): with no scored week in the league `_season_weekly_scores` yields no
  distributions and the engine returns `unsimulable.reason = "no_scored_weeks_in_league"` (`:1464`) with empty odds; with
  no remaining schedule and no games played it returns `no_games_played_and_none_scheduled` (`:1553`). The public section
  then publishes `simulated: False` and `playoffProbability: None` for every owner. A refusal is not `converged`.
- The convergence gate is unchanged: `"converged": worst_se <= odds_se_tolerance` (`:1841`), `worst_se` a binomial SE
  that is 0 at p in {0, 1}.

**Rebuilt repro.**
- Public section on a 6-owner snapshot with 3 posted unplayed weeks and ROS strength present for every owner (the case the
  existing tests did not cover; they run with an empty ROS map): `weeksPlayed 0`, `weeksRemaining 3`, `simulated False`,
  all probabilities `None`, `unsimulable.reason == no_scored_weeks_in_league`.
- Engine with injected distributions, 12 teams, 14 posted weeks, 0 played, sd 20: probabilities strictly inside (0, 1)
  (range 0.06 to 0.92 with distinct means, 0.445 to 0.545 with equal means).
- Same with sd = 0 and distinct means: every owner exactly 0.0 or 1.0, `converged: True`, `worstPlayoffOddsSe: 0.0`. The
  audited signature, still produced by the gate when handed a zero-variance input.

**Why PARTIAL and not OPEN.** Production distributions cannot be zero-variance: `_compose_team_distribution` floors `sd`
at 1.0 (`playoff_sim.py:353`) and a league with no scored week is refused before any draw. So the audited state is not
reachable from the shipped builders. The gate gap is latent: a future caller injecting its own distributions
(`simulate_playoff_odds(..., distributions=...)` is public) would be certified.

**Classification.** PARTIAL. Closed: the audited zero-games publication, both engines (one engine now). Residual: the
convergence gate cannot detect a degenerate result.

**Smallest candidate repair.** When any regular-season week remains, stamp `converged: false` (or a `degenerate: true`
diagnostic) if every owner's `playoffOdds` is exactly 0 or 1. It adds a field state, changes no probability. Gate: low;
it alters a published diagnostic consumed by the trade-deadline direction code, so the coordinator should confirm the
consumers (`src/ros/trade_deadline.py`) before it ships. Not changed here.

**Test added.** `tests/public_league/test_audit_w30_f002_regression.py`: ROS-available zero-games refusal (pass);
12-team 14-week control with variance spreads odds (pass); `xfail(strict)` "degenerate result is not certified converged".

## Routing

Tally: W06-F001, W10-F003, W30-F002 PARTIAL; W13-F003, W27-F001 OPEN; none CLOSED_VERIFIED, none UNVERIFIABLE.

| id | residual | gate |
|---|---|---|
| W06-F001 | must-have rookie guarantee mints first-name-variant ghosts (Hibner, Miller) | identity policy, C1-ID-01 `CANONICAL_V2` first-name rung |
| W10-F003 | untagged Next Best Targets empty at BA >= 1 | /draft product decision (retire or reseed from Perfect Draft) |
| W13-F003 | absolute alpha thresholds vs top-only calibration | BDVM methodology, owner/evidence |
| W27-F001 | IDP rows have no /rankings Edge; two detectors | edge-detector methodology, owner (IDPTC double role) |
| W30-F002 | convergence gate certifies zero-variance 0/1 (unreachable from builders) | coordinator confirms trade-deadline consumers |

No fix is included. Nothing in this PR is a bug fix. Coordinator to record outcomes in the audit status tooling.
