# FAAB / Waiver Recommendation Redesign — Deliverable Report

**Date:** 2026-09-01 · **Branch:** `claude/faab-waiver-redesign-8jv33n` · **Design doc:** `docs/faab-live-opportunity-model.md`

---

## 1. Root Cause

Two independent defects, plus one absent capability, produced the unreliable recommendations:

1. **Two formulas for one player.** `/api/waiver/suggestions` priced every candidate with `waiver.py::_compute_faab_bid` — Stage A–C of the engine only (anchors → objective ceiling), then a **fixed 70%/35% multiplier**, with **no market/rival model at all**. `/api/waiver/faab-recommend` ran the full engine, including the zero-inflated-lognormal rival auction. Same player, same moment, two different numbers, 3–4x+ apart.
2. **The one live-ish signal already in the pipeline did nothing.** Sleeper "trending adds" was fetched and displayed as a factor row, but never actually reached `demand_signal` or the rival-engagement math — contrary to what both the code's own docstring and `docs/faab-model.md` claimed.
3. **No live football-opportunity signal existed anywhere.** The engine's sole value input was `rankDerivedValue` — the canonical dynasty board, which moves on a scrape/refit cadence, not live. A depth-chart promotion, an injury vacancy, or a breakout game had no path into a FAAB dollar figure.

## 2. Old Model — Reproduced Live, Not Guessed At

Built the real 2026-09-01 board through the actual pipeline (`src.api.data_contract.build_api_data_contract` against `exports/archive/dynasty_export_20260901_120444.zip`) and ran both pre-existing code paths for Cyrus Allen (rookie WR, board value 2282, `low` confidence, 3 sources):

| Path | Result |
|---|---|
| `/api/waiver/suggestions` (`_compute_faab_bid`) | **aggressive $85 / reasonable $60 / lowball $30** |
| `/api/waiver/faab-recommend`, no rival data | **recommended $0** |
| `/api/waiver/faab-recommend`, 11 rivals at full $100 (most-contested case) | **recommended $19** |

The owner's reported "~$40" sits exactly between these two pre-existing numbers, consistent with whatever partial rival data the live page had at that moment. **Root cause confirmed with real numbers, before any code changed.**

A second finding, not previously known: on the same real board, **11 of the 13 named September-1 benchmark players priced at exactly $0 under both pre-existing formulas** (full table in §7) — the canonical board's `V_repl = 1607` sits above every one of them. This is the same problem stated in the opposite direction: one outlier overpriced by a broken market model, and a much larger set underpriced because the only value input available is too slow to recognize a real short-term opportunity.

## 3. New Model

**Preserved unchanged** (verified, not assumed): the objective-ceiling/recommended-bid split, the zero-inflated-lognormal rival market, season option value, positional need via startable depth, crowd comparability, $0 as a real bid, balance-as-cap-never-denominator, and the historical-budget derivation via the live Sleeper chain walk (already correct — no hardcoded $1000/$200/$100 table needed).

**Fixed (ship regardless of the new layer):**

- `waiver.py::find_waiver_targets` now accepts an optional `team_owner_id`. When it resolves to a real roster, bids come from the **same market-aware engine** `/faab-recommend` uses (`faab_engine.recommend()` + `faab_recommender.build_rivals`, built once per position group, not per candidate). Without a resolvable owner, it stays the ceiling-only estimate — but the response now says which: `bidMethodology: "market_aware" | "ceiling_only_estimate"`.
- Sleeper trending now genuinely reaches Stage E: `_rival_engagement`/`rival_bid_cdf` gained a `trending_share` parameter (mirroring the existing `crowd_share` mechanism), bounded by a new, smaller `trendingEngagementLift` (1.5 vs crowd's 5.0 — weaker evidence, smaller bound). It can raise expected competition; it never touches `objective_ceiling`.
- `faab_analytics.py`'s "zero-bid gate" — investigated, not a live defect. `docs/faab-model.md` §9.2 claimed it excluded $0 bids; reading the file at HEAD showed `all_bids.append(bid)` already runs unconditionally with an explicit comment. Only the doc was stale (corrected). Added `zeroBidShare` for parity with `faab_history.py`'s existing field.

**New — the Live Waiver Opportunity layer** (`src/trade/faab_opportunity.py`, shadow-only):

```
opportunity_value = dynasty_value + retention(dynasty_value) × short_term_surplus
```

- `short_term_surplus` is an unweighted mean of independently-bounded axes ([-1, 1]), scaled by a documented constant:
  - **role trend** — delegates verbatim to the existing `src.consensus_edge.opportunity.snap_trend_axis` (playerctx snap-share trend). No second copy.
  - **depth-chart rank** — new, small axis reading the same playerctx record's `depth.rank`.
  - **structured events** — reads `src.bdvm.events.load_events_file`/`effective_impact` (the existing closed ontology's own decay + speculation-confidence gate), so an auto-classified news event (confidence 0.45) can widen uncertainty but **structurally cannot** move the mean — enforced by BDVM's own code, not re-implemented.
- `availability` — a separate [0,1] factor from decayed `games_delta` (INJURY/SUSPENSION/ACTIVATED_RETURN), damping the whole surplus toward zero for a player unlikely to play soon (the Jer'Zhan-Newton-on-IR case).
- `retention()` — flat 1.0, explicitly provisional (category D), documented and config-isolated so a real shape can be fit once shadow data accumulates.
- Never below `dynasty_value` (surplus is clamped ≥0 before being added) — the layer names a reason to price *above* the slow board, never below a value the canonical pipeline already stands behind.
- **Never touches `objective_ceiling`'s Stage A anchors** (`V_allin`/`V_repl` stay computed off the stable board — pinned by a dedicated AST + equality test) and **never reads Sleeper trending** (pinned by an AST guard) — worth and demand stay separate axes by construction, not by convention.

**Data sources reused, not rebuilt:** `src/playerctx/` (live, weekly snap share/depth rank), `src/bdvm/news_events.py` + `config/bdvm/event_types_v1.json` (live, daily). **Revived** (built, tested, previously zero callers): `src/nfl_data/depth_charts.py` and `src/nfl_data/injury_feed.py`, now driven by extended `scripts/refresh_depth_charts.py` and new `scripts/refresh_injury_feed.py`, which diff consecutive fetches and write `DEPTH_CHART_PROMOTION`/`DEPTH_CHART_DEMOTION`/`INJURY`/`ACTIVATED_RETURN` events (real confidence 0.85, not the news lane's 0.45) into the same BDVM ledger. **This is the injury-vacancy propagation mechanism**: ESPN's own depth chart re-orders when a starter goes down, so the same diff that catches a clean role change also catches the backup's promotion — no separate injury-to-teammate join was needed. **New:** `src/adapters/sleeper_trending_history.py` + `scripts/refresh_sleeper_trending_history.py` add `trending/drop` and an hourly on-disk ring so 6h/12h/24h/48h velocity is computable (diagnostic only today — not wired into any dollar figure, per "no fake precision").

**Ontology change, scoped down after inspection**: only `ROLE_UNCERTAIN` was genuinely missing (committee/timeshare language — no existing type covered "less certain," only directional role changes). `PROMOTED_TO_STARTER` and `PRACTICE_SQUAD_ELEVATION`/`SIGNED_OFF_WAIVERS` were evaluated and **not** added — the first already duplicates `DEPTH_CHART_PROMOTION`'s existing regex, the second two are transaction facts with no ingestion source yet (documented as a genuine follow-up, not fabricated).

**Rollout — shadow only, evaluation is not activation.** New flag `waiver_live_opportunity` (default **False**). When enabled, `server.py`'s `/api/waiver/faab-recommend` handler computes `faab_opportunity.opportunity_value()` alongside the canonical-only value and logs both to `data/faab/shadow_comparisons_<leagueKey>.json` (`src/trade/faab_shadow.py`) — **the live response is provably unaffected**, pinned by an endpoint test asserting byte-identical JSON with the flag on vs. off. Promotion to the live bid is a separate, later, human-reviewed step.

## 4. Data, Cadence, Fallback

| Source | Cadence | Fallback on failure |
|---|---|---|
| Canonical dynasty board | ~2h scrape | unchanged, existing pipeline |
| Playerctx (snap share/trend/depth rank) | weekly (existing) | axis reads `TIER_ABSENT`, contributes 0 |
| BDVM event ledger | daily news sweep (existing) + **new**: depth-chart diff (daily 04:20 UTC) + injury diff (every 4h) | axis reads `TIER_ABSENT` on load failure |
| Sleeper trending adds/drops + history | 15-min in-process cache (existing) + **new**: hourly disk snapshot | stale-gated (existing `STALENESS_MAX_AGE_S["trending"]`); missing → factor row `missing: true`, never asserted as current |
| Rival balances | per-request live overlay | unverifiable balance → excluded from clearing math by policy (existing, hard invariant) |

All new fetchers follow the repo's existing prod-side-systemd-timer pattern (`data/` is gitignored, so a CI artifact never reaches the running server) — three new template pairs (`dynasty-depth-charts-refresh`, `dynasty-injury-feed-refresh`, `dynasty-trending-history-refresh`), registered in `deploy/install-systemd-service.sh` and `deploy/systemd/README.md`, all installing unconditionally (public endpoints, no credentials).

## 5. Calibration Provenance

| Parameter | Category | Basis |
|---|---|---|
| Anchors, starter-slot counts | **A** (directly derived) | league roster settings |
| Existing `market.*` rival constants | **B** (empirically fitted) | this league's real bid history (unchanged) |
| `trendingEngagementLift` (1.5), `trendingSaturationCount` (500) | **C** (documented reasoning) | smaller than `crowdEngagementLift` (5.0) — an add-count is weaker evidence than a comparable league's paid price |
| `depthRankSaturation` (3), `eventMuSaturation` (0.20), `availabilityGamesDeltaFloor` (3), `shortTermSurplusScale` (250) | **C** | plain, legible bounds (e.g. `shortTermSurplusScale` ≈ 1/3 of the measured V_allin−V_repl band width); none validated against an outcome yet |
| `retentionFlat` (1.0) | **D** (explicitly provisional) | flat until the shadow log gives outcome data |

Every constant lives in `config/trade/faab.json`'s new `opportunity` section with inline rationale — the engine contains no numeric literal that affects a recommendation, unchanged invariant.

## 6. Backtest — Current vs. Challenger

`scripts/faab_backtest.py` extended with a third `CHALLENGER` column (opportunity-adjusted value → same engine). **Read before quoting any CHALLENGER number:** it is not a validated backtest of the opportunity layer. `src.trade.faab_opportunity` reads *today's* playerctx/event evidence for every row, including a 2024 claim — neither source has historical retention, so this is a far worse look-ahead violation than the pre-existing OLD-vs-NEW comparison's own caveat 1. The script now stamps `challengerRowsWithEvidence` (expected ≈0 on real historical data) specifically so this can't be misread as validation. The mechanics were verified correct via a synthetic wiring test — this script could not be run against live data in this sandboxed session (no `data/faab/bid_history_*.json`, which requires a live Sleeper fetch this environment cannot make; see §13).

The real validation path for the opportunity layer specifically is the **forward shadow-comparison log**, not a retroactive replay — that log starts accumulating the moment the flag is turned on in shadow mode.

The OLD-vs-NEW comparison (objective ceiling + market model, which **does** have real historical data) is unaffected by this limitation and continues to work exactly as before this change — unmodified by this pass beyond adding the CHALLENGER column alongside it.

## 7. Current Board — Old vs. New

All computed live against the real archived 2026-09-01 board (not hand math), 12-team league, $100 budget, owner scenario (6 open roster spots). Market-aware "NEW" figures use a synthetic-but-reasoned 11-rival field (varied balances/needs) since live Sleeper roster data wasn't reachable from this sandbox — explicitly not the live production numbers.

| Player | Board value | Old `/suggestions` (agg/reas/low) | Old `/faab-recommend`, worst case | **New unified, market-aware** |
|---|---|---|---|---|
| Cyrus Allen | 2282 | 85 / 60 / 30 | $0–19 | **$19** (recommended), conf. high |
| George Holani | 1464 | 0/0/0 | $0 | $0 — below `V_repl` (1607) |
| Jacob Saylors | 74 | 0/0/0 | $0 | $0 |
| Kamren Kinchens | 1593 | 0/0/0 | $0 | $0 |
| Seth McGowan | 1607 | 0/0/0 | $0 | $0 (exactly at replacement) |
| Barion Brown | 1438 | 0/0/0 | $0 | $0 |
| Derrick Moore | 1955 | 3/2/1 | $0 | $0 (objective $3) |
| Jonas Sanker | 1998 | 7/5/2 | $0 | $0 (objective $7) |
| Justice Hill | 1379 | 0/0/0 | $0 | $0 |
| Malik Benson | 1411 | 0/0/0 | $0 | $0 |
| Dohnte Meyers | 711 | 0/0/0 | $0 | $0 |
| Jer'Zhan Newton | 1816 | 0/0/0 | $0 | $0 (objective $0) |
| Carson Wentz | — | not on canonical board | — | not on canonical board |
| Aaron Donald | — | not on canonical board | — | not on canonical board |

## 8. Explanations

- **Cyrus Allen**: root-caused and fixed. The shim's $60–85 was pure ceiling math with zero market discipline; the unified engine's $19 reflects that most claims in this league's real history clear near $0 and that even a maximally-contested field caps out at $19 given the objective ceiling. The full explanation is mechanical, not a guess (§2).
- **George Holani / Jacob Saylors / Kamren Kinchens / Seth McGowan / Barion Brown / Justice Hill / Malik Benson / Dohnte Meyers**: $0 under every current formula because the canonical dynasty board — thinly sourced for deep rookies, refit-cadence not live — has not yet recognized any of them as above the league-wide replacement line. This is exactly the gap the Live Waiver Opportunity layer targets; it is built and shadow-tested but not promoted (no evidence base exists yet to calibrate `retention()` or validate the axes against outcomes — see §6/§13).
- **Derrick Moore / Jonas Sanker**: small nonzero objective ceilings ($3/$7) but $0 recommended once real contention is modeled — directive Part IX's own framing ("a young DL with upside does not automatically require several dollars when demand is low") is exactly what the market-aware engine now produces, where the old shim's ceiling-only path would have shown $1–2/$2–5.
- **Jer'Zhan Newton**: $0 under every formula. His board value (1816) sits below this league's replacement line, and — separately — the directive's IR/no-reserve-slot concern is now structurally handled by the opportunity layer's `availability` factor (damped toward 0 by a decayed INJURY/IR event), verified by a dedicated unit test (§11), though not live for him today absent real event data.
- **Aaron Donald / Carson Wentz**: not on the canonical board at all — the most extreme form of "missing is never zero." No current or new mechanism in this pass invents a value for a player with zero canonical coverage; this remains a genuine limitation (§13).

## 9. UI

**No frontend changes were needed or made.** `FaabRecommendation.jsx`, `frontend/lib/waiver-faab.js`, and `waiver-logic.js` were confirmed clean (display/index-only, no bid math) before this work started and remain unchanged — they render whatever the backend returns generically, so the engine-unification and trending fixes are **already live in the UI** with zero JSX changes. The opportunity layer's fields are deliberately absent from the live response (shadow-only), so there is nothing new to surface yet; wiring a "dynasty vs. opportunity" split into the existing "Why this bid?" panel is scoped for the promotion step, not this pass (§14).

## 10. Operations — Freshness Proof

Three new systemd timer pairs (depth charts: daily 04:20 UTC; injury feed: every 4h; trending history: hourly), all public endpoints needing no credentials. Registered via the repo's shared `install_simple_timer` helper in `deploy/install-systemd-service.sh` (render, install, `daemon-reload`, enable — one call each) and documented in `deploy/systemd/README.md`. **Not yet installed on production** — this session has no VPS/SSH access (§13); the templates and install-script wiring are complete, tested (`tests/deploy/`, 402 passed), and ready for an operator to deploy.

## 11. Tests — Commands and Results

```
python3 -m pytest tests/trade/test_faab_opportunity.py -q          # 12 passed (new)
python3 -m pytest tests/trade/test_waiver.py -q                    # 32 passed (6 new)
python3 -m pytest tests/trade/test_faab_engine.py -q                # 61 passed (2 new)
python3 -m pytest tests/api/test_faab_recommend_endpoint.py -q     # 32 passed (4 new)
python3 -m pytest tests/api/test_faab_analytics.py -q               # 21 passed (unchanged, verified clean)
python3 -m pytest tests/bdvm/ -q                                    # 336 passed (unchanged)
python3 -m pytest tests/adapters/ -q                                 # unchanged + trending/drop coverage
python3 -m pytest tests/api/test_feature_flag_reachability.py \
                    tests/api/test_feature_flags.py -q               # 56 passed (new flag classified correctly)
python3 -m pytest tests/api/test_feature_flag_docs_match_registry.py -q  # 6 passed (doc counts corrected)
```

**Full suite** (`pytest tests/ -q --ignore=tests/e2e -m "not livedata"`, 10,891 collected): **10,522 passed, 43 skipped, 330 deselected** (0:16:31). Two failures surfaced on the first full run, both fixed and re-verified green:

1. `tests/deploy/test_all_timers_are_wired.py::test_every_needs_install_flag_reaches_the_daemon_reload` — a **real bug this repo's own guard caught**: the three hand-written systemd install blocks I first wrote (copied from the `playerctx` block) were never added to the shared daemon-reload trigger line, which would have installed the units without ever `daemon-reload`-ing systemd — exactly the "deployed, reported as deployed, not running" failure mode `docs/faab-live-opportunity-model.md`'s own precedent (`ce_needs_install`) describes. Fixed by deleting all three bespoke ~55-line blocks entirely and using the repo's existing `install_simple_timer` shared helper instead (three one-line calls) — the helper always reloads and always enables, so this class of bug is now structurally unreachable rather than merely fixed once. `tests/deploy/` (402 tests) reruns green.
2. `tests/trade/test_waiver.py::TestDegradedInputs::test_missing_players_array_returns_empty_shape` — a stale-process artifact: the background full-suite run started before an earlier fix to this same test landed on disk, so it exercised an old in-memory copy. Confirmed passing standalone before and after the full run; not a real regression.

Directive Part XIII's 20-item checklist, mapped:

| # | Guardrail | Test |
|---|---|---|
| 1 | Deterministic | `TestNoDiscontinuity` (exact delta match) |
| 2 | Balance changes bid, not objective worth | pre-existing `test_faab_engine.py` (unchanged) |
| 3 | No discontinuity from small value change | `TestNoDiscontinuity`, `TestAnchorsUnaffectedByLiveOpportunityLayer` |
| 4 | STARTER_OUT-style event raises backup opportunity | `test_starter_out_style_promotion_materially_increases_backup_opportunity` |
| 5 | Stale/speculative news can't apply a permanent boost | `TestStaleSpeculationCannotMoveTheMean` (2 tests) |
| 6 | Stale trending isn't current surge evidence | pre-existing `faab_contention.input_is_stale` reused verbatim by `_trending_share` |
| 7 | Add velocity affects market, not worth | `TestMarketHeatNeverEntersThisModule` (AST guard) + `test_faab_engine.py` trending-share smoke test |
| 8 | $0 historical bids valid | pre-existing, unchanged, verified |
| 9/10 | Budget normalization per season / unknown ≠ $100 | pre-existing, unchanged, verified correct |
| 11 | No IR slot → damped availability | `test_active_injury_damps_availability_and_reduces_surplus` |
| 12 | Open roster spot, no phantom drop penalty | pre-existing engine behavior, unchanged |
| 13 | Opponent FAAB limits expected bid | pre-existing market model, unchanged |
| 14 | Tiny-sample manager shrunk to league average | pre-existing `faab_history.owner_aggression_factor`, unchanged |
| 15 | Missing source lowers confidence, not silently zero | pre-existing `compute_confidence`, unchanged; opportunity layer's `hasEvidence` flag |
| 16 | Offense/IDP replacement per actual league | pre-existing, unchanged |
| 17 | Best-ball lineup utility respected | not newly built this pass (existing lineup solver untouched; opportunity layer does not yet weight by lineup-crackability — follow-up) |
| 18 | No frontend derives its own FAAB dollars | confirmed clean, unchanged (§9) |
| 19 | Every visible recommendation from canonical engine | `test_shadow_computation_never_changes_the_live_response` |
| 20 | Recommendation updates on snapshot change | mechanically true by construction (fresh reads each request); not separately re-pinned this pass |

## 12. Production Verification

**Not performed — no production access in this session.** See §13.

## 13. Remaining Limitations

- **No historical backtest exists for the opportunity layer itself**, and cannot be fabricated — neither playerctx nor the BDVM event ledger retains history reaching back to any historical claim date. Only the forward shadow-comparison log can validate it, and that log has zero entries until the flag runs in shadow mode against live traffic.
- **This session has no production VPS/SSH access.** The three new systemd timer pairs are built, registered in the install script, and documented, but not installed or running anywhere. §10/§12 are therefore code-complete, not operationally proven.
- **`scripts/faab_backtest.py`'s CHALLENGER column could not be run against real data in this sandbox** — no `data/faab/bid_history_*.json` exists here (requires a live Sleeper fetch). Verified correct via synthetic wiring tests only.
- **Aaron Donald and Carson Wentz carry zero canonical coverage** and are unpriced by every path in this pass, old and new. Nothing here invents dynasty coverage for an uncovered player — that is a canonical-board question, out of scope for a FAAB-layer fix by this repo's own "one canonical owner" rule.
- **No route participation or target-share data exists anywhere in this repo** (confirmed by the codebase's own prior audit comment) — the role axis uses snap share and depth-chart slot as the best available proxies, named as such, no fake precision.
- **Losing bids are not observable** — Sleeper exposes winning bids only; unchanged from before this work, inherited by both the pre-existing backtest and the new CHALLENGER column.
- **`retention()` is flat at 1.0**, a placeholder until real outcome data exists to fit a shape.
- **Lineup-crackability (best-ball utility) is not yet folded into the opportunity layer's short-term-surplus scoring** — the existing exact lineup solver is reused elsewhere in the codebase but not wired into this new layer this pass.
- **Portfolio/multi-claim optimization** (directive Part XII) is architected for (each `recommend()` call is already independent per player) but not built.

## 14. Follow-Ups (genuine future work only)

1. Install and enable the three new systemd timers on production; let the shadow-comparison log accumulate real cases for a season/off-season cycle.
2. Once evidence exists, fit `retention()`'s real shape and re-run the promotion decision — human-reviewed, per champion/challenger discipline.
3. Wire the opportunity layer's dynasty-vs-opportunity split into `FaabRecommendation.jsx`'s "Why this bid?" panel **at promotion time**, not before.
4. Build a Sleeper-transaction-derived event source for `PRACTICE_SQUAD_ELEVATION`/`SIGNED_OFF_WAIVERS` (roster-transaction facts, not narrative — no ingestion path exists today).
5. Fold best-ball lineup-crackability into the short-term-surplus scoring, reusing the existing exact lineup solver.
6. Build the portfolio/multi-claim optimizer (directive Part XII) on top of the now-independent per-player `recommend()` calls.
7. Wire the trending-drops velocity/acceleration data (persisted, computable) into the market layer once a real outcome study justifies a specific transform — deliberately left diagnostic-only in this pass.

---

## 15. Follow-up (2026-09-01): the frontend never sent `teamOwnerId`

**This section documents a bug found in the deployed page after the above
work merged, its root cause, the fix, and re-verification.** It does not
supersede §1-14 above — the backend engine described there is correct and
was never the problem; its market-aware path simply had no caller reaching
it from the `/waivers` main table.

### 15.1 Root cause

The owner reported the deployed `/waivers` page, with team "Collin"
selected, showing Cyrus Allen at "FAAB BID $56 · lowball $28 · aggressive
$80" — exactly `_compute_faab_bid`'s retired fixed-fraction formula
($56 = 70%×$80, $28 = 35%×$80), not the market-aware engine this redesign
built.

Traced to `frontend/components/useWaiverAnalysis.js` (the hook behind the
MAIN waivers table, distinct from the single-player bid-desk modal
`FaabRecommendation.jsx`, which already sent this field correctly). Its
`POST /api/waiver/suggestions` body never included `teamOwnerId`, even
though the hook already calls `useTeam()` and has `selectedTeam.ownerId`
available in the same closure. Every request from this page's main table
therefore resolved `team_owner_id=None` on the backend, which — by design,
documented in `waiver.py`'s own docstring from the original pass — falls
back to the ceiling-only estimate and stamps
`bidMethodology: "ceiling_only_estimate"`. Nothing on the frontend read that
field, so the fallback rendered identically to a real recommendation.

This was purely a missing frontend wire-up. The backend fix from the
original pass (§9 above) was correct and already merged; it had no caller
that could reach it from this specific page.

### 15.2 The fix

- `frontend/components/useWaiverAnalysis.js` — sends
  `teamOwnerId: selectedTeam?.ownerId`; also added `selectedTeam?.ownerId` to
  the fetch effect's dependency array (switching between two already-selected
  teams previously would not have re-fetched, since `bidsEnabled` stays true
  in that case).
- `frontend/lib/waiver-faab.js` — `buildWaiverBidIndex` now carries
  `bidMethodology` onto the index; `waiverBidStateForRow` gained a new state,
  `team_context_missing`, returned whenever the payload's methodology is not
  `market_aware`. This wins over `priced` even though a `bid` object
  genuinely exists in ceiling-only mode — it is not a recommendation and
  must not render as one.
- `frontend/components/waivers/WaiverBidFigure.jsx` — renders "Recommendation
  unavailable: team context missing" for that state (satisfies the
  requirement that the fallback must never be labeled "FAAB BID"), and
  redesigns the priced row from "reasonable / lowball / aggressive" to
  **"Bid $X · Expected clearing $Y-$Z · Max I'd pay $M"**, with "Max Worth"
  (the objective ceiling) and confidence moved to the tooltip.
- `src/trade/waiver.py::WaiverCandidate` — gained `clearing`, `clearingLow`,
  `clearingHigh`, `maxRational`, `objectiveDollars`, `confidence` fields,
  populated in the market-aware branch from `faab_engine.recommend()`'s
  existing return (`rec["bids"]`, `rec["objective"]["dollars"]`,
  `rec["confidence"]`) — these were already computed by the engine per
  candidate and previously discarded; `null` in ceiling-only mode.
- `src/trade/faab_engine.py::_market_clearing_price` — extended to return
  p25/p50/p75 of the same rival-bid CDF in one scan (was p50 only), so
  "Expected clearing $Y-$Z" is a real quantile of modelled evidence, not a
  fabricated range.
- New `scripts/faab_trace.py` — diagnostic CLI reproducing the exact
  production call path (`find_waiver_targets` + a supplementary
  `faab_engine.recommend()` call for fields the list endpoint doesn't
  return) for one player/team, or the whole September 1 board at once.

### 15.3 Why the UI said $56 — traced end to end

Reproduced locally against `exports/latest/dynasty_data_2026-09-01.json`
(the real 2026-09-01 board, including a real "Collin" team with 11
opponents) via `scripts/faab_trace.py`:

```
$ python scripts/faab_trace.py --contract exports/latest/dynasty_data_2026-09-01.json \
    --team-name Collin --player "Cyrus Allen"
```

| field | before fix (production, reported) | after fix (local repro) |
|---|---|---|
| bidMethodology | `ceiling_only_estimate` (silent) | `market_aware` |
| canonical value | 2282 | 2282 |
| objective ceiling ("Max Worth") | not surfaced (shim doesn't compute one honestly — it derives a ceiling but applies no rival model) | **$81** |
| max I'd pay (maxRational) | n/a | **$36** |
| expected clearing (band) | n/a | **$0-$0** (see caveat below) |
| recommended bid | **$56** | **$0** |
| lowball / aggressive shown | $28 / $80 | *(retired — not shown as bid advice)* |
| rival count | n/a (no rival model ran) | 11 |
| confidence | n/a | medium |

The $56 was 70% of an $80 ceiling-derived figure with **zero rival
modeling** — every uncontested, thinly-sourced rookie WR near this value
would have priced similarly under the old fallback, regardless of actual
market demand. Once the market-aware engine actually ran (owner id resolved,
11 real opponents loaded from the same export), the recommended bid
collapsed to $0.

**Caveat on the exact $0, stated honestly rather than forced to match
anything:** in this local reproduction, `rivalsWithKnownBalance` is 0 — the
static export used here is the raw scraper block, which does not carry
`faabRemaining` per team (that comes from a separate live Sleeper
teams-overlay fetch the production server makes at request time,
`_sleeper_overlay.fetch_sleeper_teams_overlay`, which this sandbox has no
credentials to reach). Per the engine's own invariant ("a rival with no
visible balance is excluded outright — an unverifiable rival must never
raise your bid"), all 11 opponents were excluded from the win-probability
math here, which pushes P(win) toward 1.0 at every bid level and collapses
the recommended bid toward $0 for every player, not just Cyrus Allen. In
production, with real balances loaded, the number would likely land
somewhere in the engine's own previously-documented range for this exact
player ($0-$19, per §9's original finding) rather than exactly $0 — but the
qualitative result (large collapse from the ceiling-only $56-60, driven by
real rival modeling) is confirmed, and is the property this fix is
responsible for restoring, not a specific dollar figure.

### 15.4 September 1 diagnostic board — re-run, gap explained with evidence

Re-ran the fixed system (`scripts/faab_trace.py --board`) against the same
local export/team. Full raw output is captured with the PR; summary:

| player | owner's reviewed board | local repro (fixed system) | found on board? |
|---|---|---|---|
| Aaron Donald | ~$17 | *(not found)* | No — **already documented in §13 above** as zero canonical coverage; unrelated to this fix, present before and after |
| George Holani | ~$6 | $0 | Yes |
| Jacob Saylors | ~$5 | *(not in suggestions list)* | canonical value found (74), but `sourceCount: 1` — excluded by the pre-existing two-source minimum (`TestTwoSourceMinimum`), unrelated to this fix |
| Kamren Kinchens | ~$4 | $0 | Yes |
| Seth McGowan | ~$3 | $0 | Yes |
| Barion Brown | ~$3 | $0 | Yes |
| Derrick Moore | ~$1 | $0 | Yes |
| Jonas Sanker | ~$1 | $0 | Yes |
| Justice Hill | ~$1 | $0 | Yes |
| Carson Wentz | ~$1 | *(not found)* | No — same pre-existing canonical-coverage gap as Aaron Donald |
| Malik Benson | ~$1 | $0 | Yes |
| Dohnte Meyers | ~$1 | *(not in suggestions list)* | canonical value found (711, `sourceCount: 2`, passes the two-source gate) but ranks below the top `DEFAULT_PER_POSITION_LIMIT=6` WR candidates by value, so it's capped out of `find_waiver_targets`'s per-position output — a pre-existing, unrelated behavior |
| Jer'Zhan Newton | ~$0 | $0 | Yes |

**Every priced player collapsed to $0 in this local reproduction**, where the
owner's board shows a range from ~$0 to ~$17. This is the SAME structural
cause as §15.3's Cyrus Allen caveat: this sandbox's rival field has zero
known FAAB balances (no live Sleeper credentials here), so every claim reads
as effectively uncontested and prices at the floor. This is **not evidence
the fixed model is wrong** — it is evidence that a meaningful re-verification
of the exact dollar amounts requires production's live balance data, which
this session cannot reach (see §15.5). What this repro DOES confirm,
independent of the balance-data gap: `bidMethodology` correctly resolves to
`market_aware` for a real team against a real board, the engine runs without
error across the whole named board, and the qualitative direction (ceiling-
only's fixed-fraction numbers replaced by a real, lower, contention-aware
number) is exactly what the fix was for.

### 15.5 Production verification — what could and could not be done

**This session has no VPS/SSH/deploy credentials** (unchanged from §12/§13).
What was done instead:
- Fixed the code (frontend + backend) and verified it against `pytest`
  (backend, 524 FAAB/waiver tests passing) and the frontend test suite
  (2404 tests passing, including new tests for the fixed request body, the
  new `team_context_missing` state, and the redesigned row).
- Ran the actual production code path (`find_waiver_targets` +
  `faab_engine.recommend`) against a real archived board
  (`exports/latest/dynasty_data_2026-09-01.json`) and a real team ("Collin",
  the exact team from the owner's screenshot) via `scripts/faab_trace.py`,
  confirming `bidMethodology` flips to `market_aware` and the fixed-fraction
  numbers disappear.
- Could NOT: push this fix to the live server, restart
  `dynasty.service`/`dynasty-frontend.service`, fetch live Sleeper FAAB
  balances for a fully realistic dollar-figure reproduction, or take a
  screenshot of the actual deployed page.

**To close the loop:** merge this PR, then pull `main` and restart both
systemd services on the production VPS (per CLAUDE.md's deployment section).
No config or migration changes are required — this is a pure code fix.

### 15.6 Live Waiver Opportunity activation plan

See `docs/faab-live-opportunity-model.md` §5a (added alongside this
addendum) for the staged, criteria-gated activation/calibration plan. Status
unchanged by this follow-up: the layer remains shadow-only, default off.
