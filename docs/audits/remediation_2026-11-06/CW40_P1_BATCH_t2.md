# CW-40 Batch T2: re-adjudication of 17 P1 findings (settings, rankings display, FAAB, directional labels, public league, Terminal, gameplan, power)

Adjudicated against `main` at `d64fc276e7` (2026-11-07). The November recount labelled these `repro_rotted` /
`unsafe-to-rerun`, so it is a baseline, not a verdict. Every check here is offline and deterministic (synthetic leagues,
the repo's own public-league fixture snapshot, engine calls, vitest renders, source-shape guards on files the code
path depends on). No network, no production, no live board. **No player value, rank, threshold, weight or formula
changed in this PR; no production code changed at all** (tests + this record only). Reused starting evidence, not
verdicts: `docs/waivers/FAAB_INTEGRITY_VERIFICATION_2026-11-06.md` (CW-10), `tests/public_league/test_identity_retirement.py`
(C9-HIST-01), `frontend/__tests__/audit-w25-f003-regression.test.js` (W25-F003 display half).

Out-of-scope files (other workers' open PRs: #2109 gameplan/rosters, #2105 signal alerts, #2107 draft, T1 trade) were
read and adjudicated but not edited; the repair is recorded below.

| id | verdict | evidence | test | repair / decision |
|---|---|---|---|---|
| W07-F002 | CLOSED_VERIFIED | manual TE override withdrawn: `data_contract.py:4155` ingress gate; `settings/page.jsx:404` read-only; default `tepMultiplier: null` (`useSettings.js:51`) | closed.py (4) + existing `settings-tep-withdrawn.test.jsx`, `test_audit_tep_override_regression.py` | none |
| W07-F003 | OPEN (duplicate of W25-F003 display half) | `dynasty-data.js:1606` unpriced non-pick row takes `computedConsensusRank` | open.test.js (characterization + `it.fails`) | small frontend change; needs owner confirmation (below) |
| W07-F004 | PARTIAL | verdict + confidence fixed; tier + position rank still derived from the ordinal (`rankings-helpers.js:24`, `rankings/page.jsx:842`) | open.test.js (2 pass, 1 `it.fails`) | same repair as W07-F003 |
| W11-F003 | CLOSED_VERIFIED | formula replaced by `faab_engine.objective_ceiling` (`faab_engine.py:728`) | closed.py (2) + CW-10 `TestW11F003NoSaturationAtThePoolTop` | none |
| W11-F004 | CLOSED_VERIFIED (narrow by-design exception pinned by CW-10) | position blend / trending kicker deleted; worth and ladder monotone at real balances | closed.py (2) + CW-10 `TestW11F004Monotonicity` | none |
| W11-F005 | CLOSED_VERIFIED | `computeFaabHint` / `topAddValue` deleted; bids stamped by backend (`waiver.py:323`) | closed.py (2) + CW-10 | none |
| W11-F007 | CLOSED_VERIFIED | list and desk both call `faab_engine.recommend`; differences are labelled (posture) | closed.py (1) + CW-10 `TestW11F007OneEngineOneFigure` | none |
| W12-F001 | CLOSED_VERIFIED | both verdicts use `MARKET_GAP_MIN_VALUE_RATIO` (`thresholds.js:99`) over the backend `marketGapValueRatio` | closed.test.js (4) + closed.py (1) | none |
| W12-F004 | CLOSED_VERIFIED | `edge/page.jsx:152` and `edge-helpers.js` gate, sort and print the gap ratio, not `sourceRankSpread` | closed.test.js (3) + closed.py (1) + existing `edge-page-market-gap.test.jsx` | none |
| W12-F005 | OPEN | `signal_alerts.py:138` state keyed by tag-bearing signal key | open.py (characterization + 2 strict xfail) | repair belongs to PR #2105's file (below) |
| W12-F007 | REQUIRES_OWNER_DECISION | `display-helpers.js:275` / `trade-logic.js:1321` read no confidence field | open.test.js (characterization only) | exact question below |
| W19-F001 | CLOSED_VERIFIED | retirement is a current-state label; history kept (`identity.py:43`, C9-HIST-01) | closed.py (1, end to end through `records.build_section`) | none |
| W19-F003 | CLOSED_VERIFIED | unresolved asset gives `available: False` grade, never a partial grade (`activity.py:132-206`; `server.py:15201`) | closed.py (4) | none |
| W20-F003 | PARTIAL / REQUIRES_OWNER_DECISION | the raw sum is labelled "Team value" (not strength); picks excluded by documented design (`terminal.py:1070`) | open.py (characterization) | exact question below |
| W20-F004 | OPEN | `PortfolioSummary.jsx:101` mixes server total (no picks) with local legend (with picks) | open.test.jsx (characterization + `it.fails`) | decision + repair below |
| W20-F010 | PARTIAL | `pickValue` repaired to an explicit unavailable state; market / consensus / leagueAdjusted still 0.0 (`gameplan.py:525`, `engine.py:257`) | open.py (2 characterization + 1 strict xfail) | repair belongs to PR #2109's file (below) |
| W30-F003 | CLOSED_VERIFIED | legacy engine `src/public_league/power.py` deleted (V1-52); one engine, one tab | closed.py (2) | none |

Tally: **10 CLOSED_VERIFIED** (W07-F002, W11-F003/4/5/7, W12-F001/4, W19-F001/3, W30-F003), **3 OPEN** (W07-F003,
W12-F005, W20-F004), **2 PARTIAL** (W07-F004, W20-F010), **1 PARTIAL / REQUIRES_OWNER_DECISION** (W20-F003), **1
REQUIRES_OWNER_DECISION** (W12-F007).
Tests: `tests/api/test_audit_cw40_batch_t2_closed.py` (20 pass), `tests/api/test_audit_cw40_batch_t2_open.py` (5 pass,
3 strict xfail), `frontend/__tests__/audit-cw40-batch-t2-closed.test.js` (7 pass),
`frontend/__tests__/audit-cw40-batch-t2-open.test.js` (6 pass, 2 `it.fails`),
`frontend/__tests__/components/audit-cw40-batch-t2-portfolio.test.jsx` (1 pass, 1 `it.fails`).

## W07-F002 /settings TE override rendered as "Default 1.15x", Reset writes the override: CLOSED_VERIFIED

**Claim.** `tepIsDefault` hid a forced `tep_multiplier: 1.15`; "Reset to default" wrote it; no UI state reached the auto board.
**Requirement.** CLAUDE.md "Live Value Pipeline" 5a (the target TE basis is a constant, the override bypasses the curve); owner DEFECT-02: one canonical value per player per session.
**Live path.** `data_contract._TEP_OVERRIDES_DISABLED = True` (`data_contract.py:4155`) makes `normalize_tep_multiplier` / `normalize_tep_native_multiplier` return `None` and `withdrawn_tep_override_note` flag the key. `settings/page.jsx:404` renders a read-only `tep-premium-readonly` block; neither TEP input nor `update("tepMultiplier", ...)` exists. `useSettings.js:51` defaults to the auto `null`; the only migration restores auto. `useDynastyData.js` calls `fetchDynastyData({siteOverrides, valuationMode})` only.
**Evidence.** Ingress normalizers ignore the stock body and name it withdrawn; page and hook source guards; existing render test mounts the page with stale stored 1.45 / 1.3 and asserts no write. End-to-end board invariance is pinned by `test_audit_tep_override_regression.py` (W07-F001).

## W07-F003 `#` column shows a client-invented ordinal for rows the board declines to price: OPEN

**Claim.** 222 live rows with `rankDerivedValue: null` / `canonicalConsensusRank: null` render `#854-1092`; CLAUDE.md's stated bound is wrong.
**Requirement.** CLAUDE.md "No frontend ranking engine"; "MISSING IS NEVER ZERO" and "Unresolved identity != best fuzzy guess": a row the board cannot price has no board rank.
**Live path.** `buildRows` (`dynasty-data.js:1594-1608`): `r.rank = canonicalConsensusRank`, else null for picks / overlay, else `computedConsensusRank = i + 1`. Unpriced players sort to the bottom (value `|| 0`) and take the next ordinals. The doc half (the "past the 800 limit" statement) was corrected 2026-11-06 (W25-F003: 175 priced off-cap + 76 unpriced of 251 on the pinned archive); the display half is the same mechanism and is unchanged.
**Evidence.** vitest: a contract with two ranked rows and one `{canonicalConsensusRank: null, rankDerivedValue: null}` row; the unpriced row's `rank === computedConsensusRank`. `it.fails` states the intended `rank === null`.
**Decision needed (smallest).** CLAUDE.md "Single Source of Truth: Rankings Override Path" currently documents the ordinal as the intended display ordinal for BOTH off-cap-priced and unpriced rows. Confirm the owner wants the unpriced population (value `null`) to render no `#` (priced off-cap rows keep theirs). If yes the repair is two lines in `buildRows` plus checking the export Rank column, sort-by-rank and `rankings/page.jsx` row filters tolerate `rank: null` (they already do for picks); it moves no value or backend rank.

## W07-F004 fabricated tier, position rank, confidence, verdict for unpriced rows: PARTIAL

**Claim.** Ekeler renders `Tier 10`, `RB 115`, `Low`, value `0`; Mattison SELL, Dillon BUY.
**Live path.** Fixed halves: the verdict is `marketEdge` (`display-helpers.js`), which returns kind `unranked` when neither our model nor KTC Market prices the row and reads only the backend `marketGapDirection` / `marketGapValueRatio`; the confidence badge is the backend `confidenceBucket` (`none` renders "None"). Still open: `tierLabel` (`rankings-helpers.js:19-24`) falls through to `rankBasedTierLabel(row.rank)`, and `positionRankByName` (`rankings/page.jsx:842`) numbers every eligible row by `rank ?? Infinity`, so unpriced rows still receive a tier and a positional rank derived from the invented ordinal.
**Evidence.** vitest: unpriced row gives `marketAction().kind === "unranked"` and `confidenceDisplay().level === "none"` (pass); `tierLabel` returns `Tier N` (characterization) and `it.fails` asserts `"Unranked"`.
**Repair.** The same `rank: null` change as W07-F003 repairs the tier (`rankBasedTierId(null)` is `null`); `positionRankByName` additionally needs `if (row.rank == null) continue`. No backend stamp is touched.

## W11-F003 FAAB bid saturates at the top of the free-agent pool: CLOSED_VERIFIED

**Requirement.** CLAUDE.md "FAAB recommendations": objective ceiling is worth as a share of the ORIGINAL budget, anchored to league-format values, not to the wire.
**Live path.** The audited `value / max(value, best free agent)` is gone; `faab_engine.objective_ceiling` (`faab_engine.py:728`) is replace-level = 0, all-in line = whole budget, smootherstep between, with an uncapped raw ceiling above the line.
**Evidence.** Players at and above a 1908-valued best free agent (2300 / 3000 / 4500 / 7000) have strictly increasing raw ceilings and more than two distinct `maxRational` bids; 9999 is worth 100%, 0 is worth 0; a weaker wire never raises a player's worth. The finding's "367 rows price identically" is a property of the deleted formula. No curve change was made or proposed here (methodology).

## W11-F004 recommendation not monotone in value: CLOSED_VERIFIED

**Live path.** The 0.5 position blend and x1.20 trending kicker in `faab_recommender.py` no longer exist (the module is an adapter over the engine; demand enters once, in the market layer).
**Evidence.** Over a 125-step sweep of value 0-9999 at a $100 balance, objective dollars and every rung (conservative / recommended / aggressive / clearing / maxRational) are non-decreasing. CW-10 additionally pins 60 seeded random leagues at balance >= $8 and documents the one by-design exception (recommended can fall $1 to $0 at a $1-$2 balance because it is the cheapest bid within `minEdge` of the expected-surplus argmax); that is the model as documented, not a regression, and is not re-litigated here.

## W11-F005 FAAB hint changes with the position filter: CLOSED_VERIFIED

**Live path.** `computeFaabHint` is deleted (`waiver-logic.js:939` closing note); `waivers/page.jsx` has no `topAddValue`; the table figure is `waiverBidStateForRow(faabIndex, move.add)`, a verbatim join of the backend-stamped ladder. The position dropdown never reaches the backend.
**Evidence.** Source guards (no `computeFaabHint` export, no `topAddValue`); `find_waiver_targets` returns identical bids for `per_position_limit` 1000 vs 2.

## W11-F007 two FAAB figures for one player on /waivers: CLOSED_VERIFIED

**Live path.** Table and desk both call `faab_engine.recommend`; the list passes `risk_posture="balanced"` (`waiver.py:554`), the desk the user's posture. The `/waivers` tooltip states the table is not posture-shaped and points to the desk. Objective ceiling vs recommended bid are separate quantities by design (CLAUDE.md).
**Evidence.** `recommend_faab` legacy keys equal the engine's `bids` (`standard` = `recommended`, `max` = `maxRational`). Minor wording residual (not a defect against this finding): the tooltip says the ladder is "not team-specific" although the figure is capped at the team's balance.

## W12-F001 table verdict contradicts popup verdict: CLOSED_VERIFIED

**Live path.** `marketAction` (`display-helpers.js:275`, via `marketEdge`) and `getPlayerEdge` (`trade-logic.js:1321`) both compare the backend `marketGapValueRatio` with the single `MARKET_GAP_MIN_VALUE_RATIO = 0.05` (`thresholds.js:99`) and read the same `marketGapDirection`; the 10-rank and 3-rank floors no longer exist.
**Evidence.** A sweep of 11 ratios (0 to 0.6, straddling 0.05) x both directions: table kind and popup signal agree on every cell; a 3% gap is HOLD in the table and silent in the popup.
**Adjacent, not adjudicated.** `marketGapRatioOf` uses `Number(row.marketGapValueRatio)`, so an explicit `null` becomes 0 (finite) rather than "no gap". Reachable only for a row with both model and market present but a null ratio; the backend never stamps that combination, so no row is affected today. Worth a one-line `== null` guard.

## W12-F004 /edge ranks and headlines source dispersion as the gap: CLOSED_VERIFIED

**Live path.** `edge/page.jsx:152` `premiumBy` and `edge-helpers.js` `topRetailPremium` / `topConsensusPremium` filter with `marketGapAtLeast(r, PREMIUM_SUMMARY_VALUE_RATIO)`, sort by `marketGapRatioOf`, and print `formatMarketGap` (percent of value); `sourceRankSpread` is only used for the separate "disagreements" panel.
**Evidence.** A high-dispersion/low-gap row does not lead, a below-floor gap is dropped whatever its dispersion, and the printed detail is "45%", not a rank-spread number.

## W12-F005 signal-alert cooldown keyed on the rule tag: OPEN

**Claim.** A flip with a different firing rule is a new state row, so the 12 h cooldown never engages and the email shows `— -> SELL`.
**Live path.** `signal_alerts._next_alert_state` (`signal_alerts.py:112-170`): `state_key = alias_key or key` (`:138`), and both keys embed the tag (`terminal._signal_key` / `_signal_alias_key`). Unchanged since the audit.
**Evidence.** Against a scratch `user_kv`: BUY/`uptrend_controlled` then SELL/`sustained_downtrend` for one player, zero seconds apart, fires twice and the second carries `priorSignal: None`. Two strict xfails state the intended behaviour (previous signal reported; cooldown engages).
**Repair (not made: `src/api/signal_alerts.py` is in PR #2105).** Track state per player (Sleeper id, name fallback) in addition to the per-signal row: record `{signal, tag, notifiedAt}` per player, take `priorSignal` from it, and apply `_MIN_NOTIFY_INTERVAL_HOURS` to the player row. The module docstring says the cooldown is per "(user, signalKey)", so whether the intended unit is the tag-bearing key or the player is a one-line owner confirmation; the missing prior signal is a defect under either reading.

## W12-F007 direction is never gated on confidence: REQUIRES_OWNER_DECISION

**Live path.** `marketAction` / `getPlayerEdge` read only `marketGapDirection` and the gap ratio. Note the premise changed: the gap is now OUR model value vs canonical KTC Market (owner directive 2026-09-23), one market, so the audited "consensus of two sources or fewer" sub-claim (retail vs consensus means) no longer describes the comparison; the confidence-blind verdict does.
**Evidence.** A `low`-confidence, single-source, anomaly-flagged row still gets an actionable SELL, and raising confidence changes nothing.
**Decision needed.** Should a BUY/SELL verdict be (a) suppressed, (b) shown but visibly caveated, or (c) left as is when `confidenceBucket` is `low` / `none` (or `quarantined`)? And at which bucket? That sets a signal threshold, so it was not guessed. No xfail was written because no behaviour is settled.

## W19-F001 retired-owner list erased 2024 franchises from public aggregates: CLOSED_VERIFIED

**Live path.** `identity.py:27-46`: retirement is a current-state label (C9-HIST-01, owner-approved 2026-08-20); `roster_to_owner` and aliases are kept, only forward-facing directories (`ordered_managers` / `to_public_list`) filter. `metrics.resolve_owner` therefore resolves retired owners and the `if not owner_id: continue` branches no longer drop their roster-weeks.
**Evidence.** Building the fixture league with its record-holder flagged retired leaves `records.build_section` byte-identical to the unflagged build, and that owner still holds the record. This is the audit's own mutation (empty the retired list, compare) inverted. Unit pins: `test_identity_retirement.py`.

## W19-F003 public trade grades drop unpriced assets: CLOSED_VERIFIED

**Live path.** At-the-time grade: `_apply_trade_grades` (`activity.py:132`) resolves each asset from the temporal ledger (`None` on a miss) and any miss makes the side `available: False`, `reason: no_historical_evidence` with `missingAssets` named. Today band: `_apply_current_grades` (`activity.py:174`) is `unpriced_today`; `server.py:15201` maps the contract resolver's 0.0 miss to `None` so a zero is never summed. `activity.jsx` renders `available === false` as an explicit "unavailable" band. `sanitize_side_values` still drops non-positive values, but neither resolver returns 0.0 for a miss (ledger and current-board paths both return `None`), so a miss can no longer reach it as a zero.
**Evidence.** A trade whose pick the resolver cannot price: both sides `available: False`, `grade: None`, the pick named; the same for the current band; a fully-priced control trade still grades; source guard on the `None` mapping.

## W20-F003 Terminal roster strength is a raw value sum: PARTIAL / REQUIRES_OWNER_DECISION

**Claim.** `teamAggregates.totalValue == sum(rankDerivedValue)` with no lineup solve, and picks excluded.
**Live path.** `terminal.py:1070` and `:1494`. The raw sum is deliberate and labelled "Team value" in the UI (`TeamCommandHeader.jsx:212`), and `engine._rollup_values` states these are "portfolio totals, deliberately NOT a strength signal"; lineup-aware strength is a separate owner (`src/ros/team_strength`, `sleeper.teams[].optimalLineup`). So the audited label ("roster strength") is not what the product shows. The pick exclusion is a documented, deliberately left known difference (`terminal.py` comment at the PICK bucket: "a product decision about what `/api/terminal` means").
**Evidence.** Fixture team with two players and a priced pick: `totalValue` is the players' sum and `byPosition.PICK.count == 0`; the header carries no "strength" wording.
**Decision needed (shared with W20-F004).** Should `/api/terminal` portfolio totals include the team's owned picks? The client (`lib/portfolio-insights.js`, `lib/league-analysis.js`) already says yes; the server says no.

## W20-F004 PortfolioSummary total excludes picks beside a Picks legend that includes them: OPEN

**Live path.** `PortfolioSummary.jsx:94-106` takes `totalValue` / `byPosition` / `byAge` from the server (players only) and leaves `starterValue` / `benchValue` / `pickValue` / `pickCount` on the local object (picks included in `computePortfolio`'s own `totalValue`). Unchanged since the audit.
**Evidence.** Rendered with a server portfolio of 16,000 and a 5,000 pick: Total Value 16,000, legend Starters + Bench + Picks = 21,000. `it.fails` states "the legend adds up to the stated total"; the characterization test pins the 16,000 / 5,000 split.
**Decision, then repair.** Same question as W20-F003. If picks count: have `terminal.py` add owned-pick value and a PICK bucket to `_compute_portfolio_insights` (pick ownership is already in `sleeper.teams[].pickDetails`; respect `pickOwnershipState`). If not: drop `pickValue` from the legend or show it outside the total. Under either answer the client must not merge totals from two definitions; `byAge` / `volExposure` percentages are also computed over the server total. Not fixed here because it moves what `/api/terminal` means.

## W20-F010 /api/gameplan market / consensus / leagueAdjusted / pickValue are 0.0: PARTIAL

**Live path.** `gameplan.py:525` calls `analyze_roster(...)` without `player_values` and `pick_value`. `engine._rollup_values` (`engine.py:257`) sums an empty mapping.
**Fixed half.** `pick_value` is now `None` with `pickValueState: "unavailable"` (C1-U6 follow-up 6), not a measured 0.0.
**Still open.** `market`, `consensus`, `leagueAdjusted` still publish `0.0` beside `pricedPlayers > 0`.
**Evidence.** Engine call without `player_values`: three players priced, `market == consensus == leagueAdjusted == 0.0`, `pickValue is None`. AST characterization: the `analyze_roster` call carries no `player_values`. One strict xfail states that it must.
**Repair (not made: `src/api/gameplan.py` is in PR #2109).** Pass the site-value map `build_league_bundle` already builds (`_index_contract_players`'s `sites`) as `player_values`; and/or make `RosterValues` publish `market` / `consensus` / `leagueAdjusted` as `None` + a state when `player_values` is `None`, exactly as `pick_value` already does (MISSING IS NEVER ZERO). The frontend consumer (`frontend/app/rosters/*`, also in #2109) must render `null` as unavailable before the engine change lands.

## W30-F003 two power-ranking engines on one tab: CLOSED_VERIFIED

**Live path.** The v1 engine `src/public_league/power.py` was deleted by V1-52 (`f92a465edd`); `public_contract.py:156` and `:541` name `src/ros/power_v2.py` as the only engine and the overview card reads it; `LeagueClient.jsx:228` mounts one `RosPowerSection`. With one engine there is no 10-vs-12-team or rank-shift disagreement to produce.
**Evidence.** AST scan: nothing in `src/` or `server.py` imports the legacy module; overview references `power_v2`; the client lazy-loads exactly one power section. Retirement guard: `tests/public_league/test_legacy_power_engine_retired.py`.
**Residual, not part of this verdict.** The audit's second observation (preseason, seven of nine v2 components missing, so v2 is a renormalised ROS-strength ranking labelled "Power") is a methodology/labelling question. The Power tab prints per-component weights (`ros-power.jsx` `ComponentBar`) and an explicit "every weighted component is unavailable" state, so the effective weights are disclosed; whether the title should change in the preseason was not adjudicated.

## Repaired in this PR (W07-F003 / W07-F004 / W25-F003 display half)

`buildRows` no longer mints a `#` ordinal for a non-pick row the backend left both rank-less and
unpriced (`rankDerivedValue` null): `rank` is `null` and `computedConsensusRank` is `null`, so
`resolvedRank` reads it as unranked (Infinity) and `tierLabel` yields "Unranked". The rankings page's
`positionRankByName` skips such rows. Priced off-cap rows keep their display ordinal; backend-stamped
ranks are untouched. The `it.fails` pins in `audit-cw40-batch-t2-open.test.js` and
`audit-w25-f003-regression.test.js` are now passing tests.
