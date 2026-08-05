# W29 — Value architecture and the single source of truth

Workstream W29, prompt section 7. Repo `/home/user/riskittogetthebrisket`, branch
`claude/fantasy-football-master-audit-umvex5`, HEAD `e96c06ef`. All numbers below come from the
running stack (`:8000` API, `:3000` pages), contract `2026-03-10.v2`, scrape
`2026-08-04T18:20:36`, 1,092 rows. Reproduce with `./repro.sh` in this directory.

---

## 1. The thirteen value concepts

Legend for **Substituted?** — whether the concept is ever written into, or read out of, a field
belonging to another concept without the reader being told.

| # | Concept | Exists? | Computed in | Field that carries it | Surfaces that read it | Substituted? |
|---|---|---|---|---|---|---|
| 1 | Independent fundamental dynasty value | Yes, **Blocked by data** | `src/bdvm/engine.py` (`run_valuation`) | `fundamental.balanced` / `.contender` / `.rebuilder` in `/api/bdvm/values` | `/bdvm`, `/rankings` "Fund gap" col, `/draft` "Fund gap", `BdvmTradePanel` on `/trade` | **No.** Never writes `rankDerivedValue`. Live probe returns `status:"no_projection_snapshot"` — `data/bdvm/projections/` absent — and every surface silent-vanishes. Honest degradation. |
| 2 | External market value | Yes | `Dynasty Scraper.py` → `canonicalSiteValues` | `canonicalSiteValues.{ktc,ktcSfTep,idpTradeCalc,…}`, `rawSourceValues.ktcSfTep`, `sourceNativeValues` | `PlayerPopup` source chips, `/trade` per-source winner row, `finder.py` market anchor | No. Kept distinct; `finder.py` stamps `marketCoverage` per market. |
| 3 | Consensus value (the board) | Yes | `src/api/data_contract.py::_compute_unified_rankings` | **`rankDerivedValue`**, mirrored to `values.overall` / `.finalAdjusted` / `.displayValue` | Everything. 64 read sites in `frontend/`, ~30 in `src/` | **Yes — see F001.** `/api/trade/suggestions` sometimes puts concept 14 in the same field. |
| 4 | League-adjusted consensus | Yes, live | `src/league_intel/adjustment.py` + `replacement.py` → `src/league_intel/overlay.py` | `factors{}` (client) / `rankDerivedValue` on a scoped contract copy (server) | `/rankings` overlay, 6 engine endpoints via `valuation_mode` | **Yes — see F002.** The overlay multiplies only `rankDerivedValue`; `offenseOnlyRankDerivedValue` stays at market and 41% of suggestion legs read *that*. |
| 5 | Market-adjusted | **Partially implemented** | `_apply_market_corridor_clamp` (IDP only), `marketGapDirection/Magnitude`, `src/consensus_edge/fair_value.py` | `marketCorridorClamp` (127 rows), `marketGapMagnitude` | `/edge` (flag off → 503), `PlayerPopup` | No. Diagnostic-only; the clamp folds into `rankDerivedValue` by design (pipeline stage 10). |
| 6 | Rest-of-season | Yes | `src/ros/aggregate.py::rank_to_score` | **`rosValue` (0–100 log-rank index)** | `/league` ROS strength, `/tools/ros-data-health`, `PlayerPopup` ROS section, `RosTradeFitPanel` | **Structurally, yes — see F004/F008.** `rosValue` is the sole input to `compute_scarcity`, which produces concept 4's factors. And it is compared directly against a 0-9999 board value in two UI tag functions. |
| 7 | Contender | Yes, **Blocked by data** | `config/bdvm/params_v1.json::strategies.contender` (discount .72, horizon 4, pick_premium .92) | `strategyCapitals.contender` | `/bdvm` | No. |
| 8 | Balanced | Yes, **Blocked by data** | `strategies.balanced` (.85 / 6 / 1.00) | `fundamental.balanced` | `/bdvm`, gap columns | No. |
| 9 | Rebuilder | Yes, **Blocked by data** | `strategies.rebuilder` (.93 / 8 / 1.08) | `strategyCapitals.rebuilder` | `/bdvm` | No. |
| 10 | Roster-specific marginal | Yes | `src/roster_intel/marginal.py::position_marginals` | `marginalStrengthIndex` (+ deprecated alias `marginalPoints`) | `/gameplan` | No — correctly renamed off "points". Units are ROS strength index, not trade units. |
| 11 | Waiver | Yes | `src/trade/waiver.py::find_waiver_candidates` | `consensusValue`, plus alias **`adjustedValue`** | `/waivers`, `POST /api/waiver/*` | Name-level only. `adjustedValue` is a verbatim copy of `consensusValue` (`waiver.py:68`) — no adjustment is applied. Documented as back-compat; nothing downstream treats it as adjusted. |
| 12 | Rookie-pick | Yes | pipeline stage 12 (year discount) + stage 13 (rookie-pool tethering); `_stamp_pick_value_projections` | `rankDerivedValue` on pick rows, `pickYearDiscount`, `pickRookieAnchor`, `pickProjectedDraftValue` | `/draft`, `/trade`, `PlayerPopup` | No. `pickProjectedDraftValue` = `rankDerivedValue / pickYearDiscount` — board-derived, not ROS-derived (checked: `src/ros/pick_projection.py` supplies *slot order* only, never a value). |
| 13 | Trade-clearing / normalized market | Yes | `src/trade/ktc_va.py::adjusted_pair_totals` ≡ `frontend/lib/trade-logic.js::ktcAdjustPackage` (verbatim port of keeptradecut.com `site.min.js`) | package-level `vaNet`, `giveTotal`/`receiveTotal`/`gap` | `/trade` TradeMeter, `/trades` grades, `suggestions.py::_va_gap` | No. Package-scope only; never written back onto a player row. |

**Two concepts the brief did not name but that exist and matter:**

| # | Concept | Field | Note |
|---|---|---|---|
| 14 | Offense-only board (IDP-disabled re-run of the whole pipeline) | `offenseOnlyRankDerivedValue` (606 rows) / `_offenseOnlyFinalAdjusted` | **This is the substitution vector for F001 and F002.** |
| 15 | Injury-decayed value | `injuryAdjustedValue` = live value × decay | `src/api/injury_impact.py`; terminal `BuySellHold` only, always shown beside the undecayed number. Clean. |

---

## 2. Is there a single canonical value selector?

**No. There is one canonical *field* and at least four different selectors reading it.**

Backend — only two named helpers exist; every other consumer inlines the read:

| Selector | Location | Chain |
|---|---|---|
| `board_values_from_contract` | `src/trade/finder.py:346` | `rankDerivedValue` only |
| `get_active_value` | `src/league_intel/values.py:241` | `rankDerivedValue` → `displayValue`/`finalAdjusted`/`overall` |
| inline `row.get("rankDerivedValue")` | 24 call sites: `terminal.py:157`, `suggestions.py:561`, `angle.py:324`, `waiver.py:196,315`, `monte_carlo.py:379`, `injury_impact.py:325`, `tiering.py:348`, `chat.py:177`, `custom_alerts.py:224`, `roster_percentage.py:284`, `rank_history.py:151`, `draft_capital_fallback.py:105,112`, `server.py:1344,3624,5072,5073,5135,7168,12350` … | varies |
| `src/api/public_activity_valuation.py:79` | public league grading | `displayValue` → `overall` → `finalAdjusted` |

Frontend — measured by grep across `frontend/app`, `frontend/components`, `frontend/lib`:

| Field read | Count | Who |
|---|---|---|
| `.rankDerivedValue` | 64 | `/rankings` (sort + display + export), graph components, `PlayerPopup`, `waiver-logic`, `portfolio-insights` |
| `values?.full` | 45 | `/rosters`, `/trades`, `league-analysis`, `trade-logic::displayValue`, `RosTradeFitPanel` |
| `rawSourceValues` | 24 | `PlayerPopup` chips |
| `canonicalSiteValues` | 21 | `PlayerPopup`, `/trade` source breakdown |
| `sourceNativeValues` | 16 | source charts |
| `displayValue` | 10 | `/draft` sync chain, `/trade` suggestion render |
| `_finalAdjusted` | 6 | 4 are comments; **2 are live** (`dynasty-data.js:1980-81`, the client overlay scaling the composite by a board-scale factor) |
| `subgroupBlendValue` / `anchorValue` | 3 / 3 | `PlayerPopup` methodology panel only — correctly labelled as pipeline internals |
| `_composite` / `_rawComposite` | 2 / 1 | `inferValueBundle` "Raw" mode only |

**CLAUDE.md's claim — "every engine reads exactly one value — `rankDerivedValue`" — is true of the
*read*, and false of the *emit*.** `suggestions.py` reads `rankDerivedValue` at intake
(`:561`) but re-serializes some legs from `offense_only_value` (`_serialize_player`, `:1737-1741`)
under the field name `displayValue`. That is the single most consequential gap in this workstream
(F001, F002).

### Does any page contain its own unofficial value formula?

**No.** The ~280-line `computeUnifiedRanks` fallback is genuinely gone; `buildRows` fails fast with
an empty array + error banner when no backend stamps are present (`dynasty-data.js:1350-1358`). The
only client-side arithmetic on a value is (a) `× factor` in the league-adjusted overlay, using
server-supplied factors and server-supplied ranks, and (b) the KTC VA port, which is package-scope.
`buildRows`' `computedConsensusRank = i + 1` is a display ordinal for rows the backend deliberately
left unranked, and it is suppressed for picks and correctly sorted by the *served* rank when the
overlay is active (`dynasty-data.js:1374-1389`).

### Is any obsolete value field still silently consumed?

| Field | Verdict |
|---|---|
| `_finalAdjusted` | **Deprecated but still active.** It is a verbatim copy of `_rawComposite` (verified: Josh Allen 9983/9983, Bijan 9999/9999) — the composite scale, median 1.0855× the board. Read live at `finder.py:498` (legacy no-contract path, unreachable when a contract is loaded — live probe returns `valueSource: "rankDerivedValue"`), `finder.py:1006` (diagnostic count, gated on the *composite*-scale threshold, correct), and `dynasty-data.js:1980-81` (client overlay). **Trap:** `values.finalAdjusted` on `playersArray` is the *board* value while `players[].._finalAdjusted` on the legacy dict is the *composite*. Bijan Robinson: 9706 vs 9999 under the same name in one payload. |
| `_canonicalDisplayValue` | **Missing** and no longer read. Only a comment survives (`dynasty-data.js:156`). Prior claim that it heads a live fallback chain does not hold on this build. |
| `values.full` | Frontend-synthesized by `buildRows`; does **not** exist on backend rows. `monte_carlo.py:379`'s `row.get("values",{}).get("full")` fallback is dead but harmless. |
| `ktcRank` / `ktcTopNFilter` | Deprecated aliases for `boardRank` / `boardTopNFilter`; both stamped, honest. |
| `adjustedValue` (waiver) | Alias for `consensusValue`. No adjustment applied. |

---

## 3. Is the 1..9999 scale held everywhere?

Live ranges:

| Quantity | Range | Scale |
|---|---|---|
| `rankDerivedValue` | 757 – 9,988 (812 rows) | board 0-9999 |
| `values.displayValue` / `.overall` / `.finalAdjusted` | 757 – 9,988 (812 rows, identical) | board |
| `_finalAdjusted` / `_rawComposite` | 138 – 9,999 (1,074 rows) | **composite, 1.0855× board** |
| `offenseOnlyRankDerivedValue` | 606 rows | board-scale, different board |
| `rosValue` | 9.4 – 86.79 | **0-100 log-rank index** |
| `lineupScarcity` | 0.436 – 0.767 | dimensionless ratio of ROS values |
| `factors` | 0.953 – 1.043 (709 rows) | dimensionless |
| `dollarValue` (`/api/draft-capital`) | 0 – 134.5 | **auction dollars** |
| `marginalStrengthIndex` | ROS-derived | strength index |

The board scale holds inside the contract. It does **not** hold across the artifact boundary
(`dynasty_full.csv`, F003) and it is **violated in two UI predicates** where a 0-9999 value is
compared against a 0-100 index (F005).

One naming landmine worth recording even though it is currently benign: `rookieKtcValue` in
`/api/draft-capital` carries an **auction dollar** (135.5 for 1.01), not a KTC 0-9999 value.
`server.py:8208-8218` documents this ("retains its legacy field name for back-compat but now
carries our derived dollar value"). CLAUDE.md's line "its `rookieKtcValue` IS a player value and
does move under the lens" describes a dollar figure as a player value; `/draft` renders a
`ValueBasisNote`, so no user-visible defect today.

`frontend/app/rosters/page.jsx:24-41` carries an excellent in-code warning about `VALUE_MODES`
colliding between "which assets to count" and "which value number to read" — both use the key
`"full"`. That collision is currently defused by the rename. Keep it.

---

## 4. Do sorting and the displayed value ever disagree?

**No, on both pages tested.**

`/rankings` — all four consumers use the identical expression `row.rankDerivedValue || row.values?.full || 0`:

| Consumer | Line |
|---|---|
| sort comparator, `case "value"` | `frontend/app/rankings/page.jsx:596-597` |
| CSV / clipboard export | `:764` |
| table cell render | `:1050` |
| mobile card render | `:1977` |

Default sort is `case "rank"` → `resolvedRank` → `canonicalConsensusRank ?? computedConsensusRank`,
which under the overlay uses the **server-sent** rank (`dynasty-data.js:1375-1379`) — deliberately,
to avoid a `#100, #101, #100` stutter from Python round-half-even vs JS round-half-up.

`/rosters` — reads `r.values?.full` at both aggregation sites (`page.jsx:320,331`) and
`league-analysis.js:676`; the team leaderboard sorts on the same total it prints. The
`ASSET_SCOPES` selector is a *filter*, not a valuation, and is documented as such.

---

## 5. Do exports agree with the screen?

| Export | Agrees? |
|---|---|
| `/rankings` "Export CSV" + "Copy values" | **Yes** — `buildExportLines` uses the render expression verbatim (`page.jsx:764`). |
| `/draft` "Export CSV" | Yes — `draftReviewToCsv` over workspace state already materialized from the board. |
| `/trade` "Export CSV" | Yes — serializes side assets by `effectiveValue`. |
| `/idptc-rookies` CSV | Yes — its own vendor board, labelled. |
| **`exports/latest/dynasty_full.csv`** | **No — F003.** Its `Composite` column is the scraper composite. 804 of 805 matched players disagree with the board; median ratio 1.0855, p10 0.956, p90 1.260. Lamar Jackson 7,631 vs 8,784 on screen. |
| `exports/latest/dynasty_values.csv` | N/A — per-source raw vendor values (`Player,KTC,IDPTradeCalc`), never presented as consensus. Correct. |

No HTTP route serves `dynasty_full.csv` (`openapi.json` has only `/api/public/league/{section}.csv`
and `/api/trade/export-ktc`), so this is a release-artifact divergence, not a click-through one.

---

## 6. Can a cached value disagree with an uncached one?

**No cache key omits a discriminator that changes the value.** Checked:

| Cache | Key | Verdict |
|---|---|---|
| `_OVERRIDES_RESPONSE_CACHE` | `("overrides", sha1(canonical body), delta_view, league_cfg.key, sleeper_matches)` + `contract_version` checked on hit | Safe. `valuation_mode` is inside the hashed body, and `cacheable = not want_league_adjusted` (`server.py:3988`) means adjusted responses are never cached at all. |
| `_OVERLAY_RESPONSE_CACHE` | `("overlay", league_key, loaded_league, view, sleeper_matches)` + version `(overlayFetchedAt, payload_etag)` | Safe — one generation per slot. |
| `_XLEAGUE` slot | `("xleague", league_key, loaded_league, view)` + `payload_etag` | Safe. |
| Frontend base contract | `` `${leagueKey}|${view}` `` (`dynasty-data.js:1499`) | Safe — the base contract is *always* the market board; the overlay composes on top. |
| `useTerminal` | includes `valuationMode` (`useTerminal.js:52-58`) | Safe, and explicitly commented as such. |
| `get_league_bundle` | league key + scoring profile + roster-snapshot mtime stamp | Safe. |
| `bdvm_api` | model/param/config hash + events-file fingerprint + UTC day | Safe. |

Scoring profile is not a literal key component anywhere, but `league_cfg.key` determines it 1:1 via
the registry, so no collision is reachable.

---

## 7. ROS contamination — the direct answer

**Can ROS values reach dynasty rankings?** No, not as values.
`src/api/data_contract.py` imports nothing from `src.ros`; `pickProjectedDraftValue` is
`rankDerivedValue / pickYearDiscount`, and `src/ros/pick_projection.py` supplies projected *slot
order* only and says so in its own docstring.

**Can ROS values reach the trade calculator?** **Yes — structurally, through one documented door and
one undocumented one.**

1. *The documented door.* `src/league_intel/replacement.py` imports `src.ros.lineup.optimize_lineup`
   and runs it over `rosValue` (`replacement.py:212,312,388,399,580,631`) to measure endogenous
   starter demand. `compute_scarcity` then builds every scarcity component from `rosValue`
   (`:631` — `value = float(p.get("rosValue") or 0.0)`), reading rosters out of
   `data/ros/team_strength/<league>.json` (`gameplan.py:357`). `lineupScarcity` feeds
   `structural_scarcity_axis` (`adjustment.py:247`: `delta = (value − 0.5) × 0.20`) → `factors` →
   `overlay.adjusted_rows` → **every engine** under `valuation_mode=leagueAdjusted`. Live: WR
   `lineupScarcity` 0.634 → factor 1.0268; Jayden Daniels 8,898 → 9,061 on `/api/trade/suggestions`.
   The influence is dimensionless (a ratio of ROS values), so no scale is mixed — but the quantity
   being ratio'd is an *ordinal* log-rank index, so "the drop from the top RB to the last starting
   RB" is not a cardinal drop. `replacement.py:22-52` documents this honestly (measured FLEX-TE
   share 0.0% on projections vs 10.4% on weekly actuals). This is a stated-assumption issue, not a
   contamination bug.

2. *The undocumented door.* `PlayerPopup.jsx:108` and `RosTradeFitPanel.jsx:75` (the latter renders
   on `/trade`) compare a 0-9999 board value against `rosValue × 0.7` directly — **F005**.

`/api/ros/*` is otherwise correctly firewalled: `src/ros/api.py:13-16` states the write isolation
invariant, and `gameplan.py:34-60` is the clearest scale-separation doc in the repo — it
deliberately withholds `site_values` from the target engines because feeding 0-9999 numbers to a
`(ros_value − price)/price` edge would return ≈ −0.99 for every player alive.

---

## 8. Trade history — leakage

**The primary grade is retrodiction; a secondary badge is the correct-as-of one.**

- `analyzeSleeperTradeHistory(rawData, rows, windowDays=365, alpha)` (`league-analysis.js:533`)
  builds its lookup from **today's** `rows`. `resolveTradeItemValue` reads `row.values?.full`
  for players (`:146`) and for picks (`:132`). Everything visible follows: `pctGap`, the letter
  grade, "won by X%" (`trades/page.jsx:264`), and the `teamScores` won/lost/`totalGain`
  leaderboard (`:552-573`).
- Live payload: **110 trades spanning 2025-08-05 → 2026-07-31**, all graded on the 2026-08-04 board.
- A correct as-of path *does* exist — `frontend/lib/trade-retro-value.js::gradeRetro`, wired at
  `trades/page.jsx:397-416` with `asOfMs` — but it produces only an `aged_well` / `aged_poorly` /
  `stable` badge, never the headline. And it has two holes of its own:
  - **Picks always use the current value** (`trade-retro-value.js:76-83`, `source: "current"`).
    Picks are **24% of all traded assets and appear in 60% of the 110 trades**.
  - Trades predating coverage fall back to the *earliest* sample (`pointAt`, `:52-56`).
- In this container the badge is **Blocked by data**: `data/rank_history.jsonl` does not exist, and
  `GET /api/data/rank-history?days=365` returns `{"days":365,"history":{}}`, so every asset takes
  `current_fallback` and `verdictDelta` is identically 0. (`data/source_value_history.jsonl` exists
  with 1 snapshot; the module is designed for 180.)

**Answer: today's values, applied retroactively, for every number a user actually reads on `/trades`.**

---

## 9. What works — do not "fix" these

- `finder.py` migrated correctly and proves it at runtime: `metadata.valueSource: "rankDerivedValue"`,
  `assetsUnpricedByBoard: 186`, per-market `marketCoverage: {ktcSfTep:132, ktc:18, idpTradeCalc:150}`,
  and an explicit warning that unpriced ≠ worthless.
- The no-frontend-ranker rule holds. The fail-fast in `buildRows` is real.
- The league-adjusted lens is genuinely composed server-side (`_valuation_scoped_contract`), every
  response stamps `valuationMode` including `"market"`, and `overlay.adjusted_rows` returns **all**
  rows rather than `compact_ranks_and_tiers`' ranked subset — the 2026-picks-vanish bug its comment
  describes is genuinely prevented.
- `LEAGUE_ADJUSTED_IS_NOOP = False` is accurate: 709 of 1,092 rows carry a factor,
  `monotonicityViolations: []`, factors inside `MAX_TOTAL_ADJUSTMENT`.
- BDVM degrades honestly with no snapshot and never touches `rankDerivedValue`.
- `gameplan.py:34-60` and `rosters/page.jsx:24-41` are the two best pieces of scale/naming
  discipline in the codebase.
