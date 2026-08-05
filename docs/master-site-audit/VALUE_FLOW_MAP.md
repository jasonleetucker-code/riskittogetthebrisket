# Value Flow Map — §7, value architecture and the single source of truth

Deliverable for prompt section 7. Built from the **W29** and **W02** shards
(`evidence/registry/W29.jsonl`, `evidence/registry/W02.jsonl`), the W29 evidence set
(`evidence/W29/`), and the cross-workstream §7 findings in `findings.json`
(35 findings carry `promptSections: [7]`). Every number below was either re-run against the
running stack while writing this file, or is cited to the finding and artifact that produced it.

| | |
|---|---|
| Repo / HEAD | `/home/user/riskittogetthebrisket`, `fb4a15a0` (findings merged at `ba9f348b`; W29/W02 authored at `e96c06ef`) |
| Contract | `2026-03-10.v2`, scrape `2026-08-04T18:20:36`, built `2026-08-05T00:25:32Z` |
| Board size | 1,092 `playersArray` rows / 1,092 legacy `players` entries / 1,074 raw scraper players |
| Stack | API `:8000`, pages `:3000` |

**Headline.** There is exactly one function that computes a dynasty value, and it is
deterministic and reproducible (W02-F012, verified). There is **not** one number per player per
session. Three separate mechanisms put a second value on screen under the first one's name: the
frontend's default `tep_multiplier=1.15` (a whole second board — W03-F001 / W07-F001 / W08-F001,
all P0, all verified), the offense-only board serialized into the trade engines' `displayValue`
(W29-F001 / W29-F002 / W09-F006), and the pre-canonical scraper composite that still ships in
`exports/latest/dynasty_full.csv` (W29-F003). The single-source-of-truth rule holds for
*computation* and fails for *presentation*.

---

## 1. The complete map: source CSV → rendered DOM

### 1.1 Where a value is CALCULATED

One place. `src/api/data_contract.py::_compute_unified_rankings` (defined at line 6770) is the
only code path that produces a live dynasty value. Everything else transforms, selects or
displays what it emits.

| # | Stage | Where | Emits |
|---|---|---|---|
| 0 | Source ingestion → per-source raw values / ranks | `Dynasty Scraper.py` + `scripts/` fetchers | `canonicalSiteValues`, `sourceNativeValues`, `rawSourceValues`, `_composite` |
| 1 | 0–9999 internal scale + percentile normalization vs a fixed 500-row reference | `_compute_unified_rankings` | `sourceRankMeta[*].percentile` |
| 2 | Hill percentile→value per scope master | `src/canonical/player_valuation.py` | `sourceRankMeta[*].valueContribution` |
| 3 | Value-direct voting (`ktcSfTep`, `idpTradeCalc`) | `_compute_unified_rankings` | same |
| 3a | TE base→TE++ basis conversion (ADR-015) | `src/league_intel/te_premium.convert_te_value` | converted contributions on 536 TE votes |
| 4 | Hampel outlier rejection | `_compute_unified_rankings` | `droppedSources` |
| 5 | Hierarchical anchor + α-shrinkage (IDP + picks only, α=0.10) | `_compute_unified_rankings` | `anchorValue`, `subgroupBlendValue`, `alphaShrinkage` |
| 6 | Count-aware aggregation | `_compute_unified_rankings` | `_blendedValueUncapped` |
| 7 | Single-source haircut (0.30 retention) | `_compute_unified_rankings` | `singleSourceValuePenaltyApplied` (35 rows) |
| 8 | Market corridor clamp (IDP rows only) | `_apply_market_corridor_clamp` | `marketCorridorClamp` |
| 9 | Two-way player boost (`{"Travis Hunter": "DB"}`) | `_apply_two_way_player_boost` | overwrites `rankDerivedValue` |
| 10 | Future-year pick discount | `config/weights/pick_year_discount.json` | `pickYearDiscount` — **12 rows, all 2029, all 0.53** |
| 11 | Pick tethering to the merged rookie pool (post-sort) | `_compute_unified_rankings` phase 5.2b | `rankDerivedValue`, `pickRookieAnchor` on 72 slot picks |
| 12 | Stamping | `data_contract.py:9225-9236` | `rankDerivedValue` + `values.{overall,finalAdjusted,displayValue}` written in **one branch** |
| 13 | IDP-disabled re-run of the whole pipeline | `data_contract.py:9158-9192` | `offenseOnlyRankDerivedValue` (606 rows) |

Stage 10 does not do what CLAUDE.md says. The doc claims the discount lowers 2027/2028 picks;
live it is stamped on 12 rows and every one is a 2029 row (W02-F007, `Deprecated but still
active`). Verified here: `Counter({('2029', 0.53): 12})`, with 12 priced 2027 picks and 12
priced 2028 picks carrying no discount at all.

Two post-contract *modifiers* also compute values, both outside `_compute_unified_rankings`:

| Modifier | Where | Effect |
|---|---|---|
| League-adjusted overlay | `src/league_intel/overlay.py:86-93` | `rankDerivedValue × factor`, **one key only** |
| Injury decay | `src/api/injury_impact.py:37` | `injuryAdjustedValue = value × decay`, terminal only |

### 1.2 Where a value is MODIFIED, DISPLAYED, SORTED, SUMMED, COMPARED, EXPORTED, CACHED

| Verb | Where it happens | Field read | Notes |
|---|---|---|---|
| **Modified** | `overlay.adjusted_rows` (server), `dynasty-data.js:1941-1952` (client) | `rankDerivedValue` | The two appliers are not equivalent — see V3 |
| **Modified** | `POST /api/rankings/overrides` (`tep_multiplier`, source weights) | whole board | Recomputes through the same pipeline; see V1 |
| **Displayed** | `/rankings` cell `page.jsx:1050`; mobile card `:1977` | `row.rankDerivedValue \|\| row.values?.full \|\| 0` | Identical expression at all four call sites |
| **Sorted** | `/rankings` comparator `page.jsx:596-597` (`case "value"`) | same expression | Default sort is by backend rank, not value |
| **Summed** | `/trade` sides (`trade-logic.js::sideTotal` → `effectiveValue`) | `row.values[valueMode]` or `customValue` | |
| **Summed** | `/rosters` team totals (`page.jsx:320,331`, `league-analysis.js:676`) | `r.values?.full` | Leaderboard sorts on the total it prints |
| **Summed** | `/terminal` roster strength (`src/api/terminal.py:157`) | `rankDerivedValue` | Raw sum, no lineup solve (W20-F003) |
| **Summed** | `frontend/lib/portfolio-insights.js` | `rankDerivedValue` | Prices current-year picks at 0 (W20-F005) |
| **Summed** | `/api/gameplan` roster rollup | — | Emits **0.0** for market/consensus/leagueAdjusted/pickValue on all 12 teams (W20-F010) |
| **Compared** | consensus vs retail → `marketGapDirection/Magnitude` | `effectiveSourceRanks` | Rank space, not value space (W03-F006, rescoped) |
| **Compared** | board vs retail market → arbitrage | `board_values_from_contract` vs `ktcSfTep`/`idpTradeCalc` | `src/trade/finder.py:346` |
| **Compared** | fundamental vs market → "Fund gap" | `/api/bdvm/values` joined at render time | Blocked by data (§2 row 1) |
| **Compared** | board vs ROS strength → context tags | `values.full` vs `rosValue × 0.7` | Cross-scale; unreachable (W29-F005) |
| **Exported** | `/rankings` CSV + clipboard (`page.jsx:764`) | same expression as render | Carries a `Value Basis` column |
| **Exported** | `/trade` CSV | `effectiveValue` | |
| **Exported** | `exports/latest/dynasty_full.csv` (`Dynasty Scraper.py:7433`) | `_finalAdjusted` | **Not the board** — V6 |
| **Cached** | `_OVERRIDES_RESPONSE_CACHE` (`server.py:378`) | key includes hashed body + league + contract version; `cacheable = not want_league_adjusted` (`server.py:3988`) | Safe |
| **Cached** | `_OVERLAY_RESPONSE_CACHE` (`server.py:358`), `_XLEAGUE` slot | league + loaded league + view + etag | Safe |
| **Cached** | frontend base contract (`dynasty-data.js:1499`) | `` `${leagueKey}|${view}` `` | Safe — base is always the market board |
| **Cached** | `useTerminal` (`useTerminal.js` `cacheKey`) | includes `valuationMode` | Safe, and commented as to why |

**No cache key omits a discriminator that changes the value.** That is a positive result, checked
against every cache in the value path. Two adjacent caching defects exist but are not value
correctness: `/api/valuation/league-adjusted` and `/api/bdvm/*` send no `Cache-Control`/`ETag`
(W26-F009), and `_LEAGUE_CONTEXT_CACHE` is a single unkeyed global slot across leagues
(W26-F018).

### 1.3 Where the DOM gets its number

`buildRows` (`frontend/lib/dynasty-data.js`) is a pure materializer with a hard fail-fast: a
non-empty payload with zero backend rank stamps logs an error and returns `[]`
(`dynasty-data.js:1344-1349`). The ~280-line `computeUnifiedRanks` client blend is genuinely
gone. **No page contains its own value formula.** The only client arithmetic on a value is
`× factor` in the league-adjusted overlay (server-supplied factors, server-supplied ranks) and
the KTC value-adjustment port, which is package-scope and never written back to a row.

One nuance, measured: `buildRows` assigns a display ordinal `computedConsensusRank = i + 1`
(`:1391`) and uses it for `r.rank` only when the backend stamped nothing (`:1403`). Running
`buildRows` over the live `view=app` payload: **1,072 rows, 740 backend-stamped ranks, max
backend rank 740, 219 rows client-numbered.** CLAUDE.md attributes those rows to an
`OVERALL_RANK_LIMIT` of 800 — the board never reaches 800, so that explanation is wrong
(W25-F003), and the client-numbered rows still receive tiers, positional ranks and BUY/SELL
verdicts they have no basis for (W07-F003, W07-F004).

Re-run: §9 step 5 executes the real `buildRows` over the real `view=app` payload.

---

## 2. The thirteen value concepts

"Substituted?" means: is this concept ever written into, or read out of, a field belonging to
another concept without the reader being told.

| # | Concept | Exists? | Computed in | Field | Read by | Silently substituted? |
|---|---|---|---|---|---|---|
| 1 | **Independent fundamental** | Yes — **Blocked by data** | `src/bdvm/engine.py::run_valuation` | `fundamental.balanced/.contender/.rebuilder` | `/bdvm`, `/rankings` Fund-gap col, `/draft` Fund-gap, `BdvmTradePanel` | **No.** Live probe returns `status: "no_projection_snapshot"` (`data/bdvm/projections/` absent); every surface silent-vanishes. Never writes `rankDerivedValue` — structurally verified (W13-F008). |
| 2 | **External market** | Yes | `Dynasty Scraper.py` → per-source maps | `canonicalSiteValues.*`, `rawSourceValues.ktcSfTep`, `sourceNativeValues.*` | `PlayerPopup` chips, `/trade` per-source row, `finder.py` market anchor | **Partly.** `canonicalSiteValues` holds *synthetic rank encodings* for rank-signal sources — Josh Allen reads `dlfSf: 999900`, `draftSharks: 100` — beside genuine values (`ktc: 9983`). One field, two meanings; the popup renders both. |
| 3 | **Consensus (the board)** | Yes | `_compute_unified_rankings` | **`rankDerivedValue`**, mirrored to `values.overall/.finalAdjusted/.displayValue` | Everything: 64 frontend read sites, 165 backend lines | **Yes — V1, V2.** The trade engines emit concept 14 under `displayValue`; the rendered `/rankings` board is a *different* board from the one the engines price from. |
| 4 | **League-adjusted consensus** | Yes, live | `src/league_intel/adjustment.py` + `replacement.py` → `overlay.py` | `factors{}` (client) / `rankDerivedValue` on a scoped copy (server) | `/rankings` toggle + 6 engine endpoints via `valuation_mode` | **Yes — V3.** Overlay multiplies one key; `offenseOnlyRankDerivedValue` rides through unscaled, so 41% of suggestion legs are unadjusted under an `leagueAdjusted` stamp. |
| 5 | **Market-adjusted** | **Partially implemented** | `_apply_market_corridor_clamp` (IDP only), `_compute_market_gap`, `src/consensus_edge/fair_value.py` | `marketCorridorClamp`, `marketGapDirection/Magnitude` | `/edge` (flag off → 503), `PlayerPopup`, `/rankings` Edge column | **No** substitution. The clamp folds into `rankDerivedValue` by design; the gap is a separate stamp. Its inputs are defective (W02-F003, W03-F006). |
| 6 | **Rest-of-season** | Yes | `src/ros/aggregate.py::rank_to_score` | **`rosValue`** (0–100 log-rank index, live 9.4–86.79 over 500 players) | `/league` ROS strength, `/tools/ros-data-health`, `PlayerPopup`, `RosTradeFitPanel` | **No, as a value.** But it is the sole input to concept 4's multiplier (§5), and three copies of one predicate compare it directly against a 0-9999 board value (W29-F005). |
| 7 | **Contender** | Yes — **Blocked by data** | `config/bdvm/params_v1.json::strategies.contender` (discount .72 / horizon 4 / pick premium .92) | `strategyCapitals.contender` | `/bdvm` | No. |
| 8 | **Balanced** | Yes — **Blocked by data** | `strategies.balanced` (.85 / 6 / 1.00) | `fundamental.balanced` | `/bdvm`, both gap columns | No. |
| 9 | **Rebuilder** | Yes — **Blocked by data** | `strategies.rebuilder` (.93 / 8 / 1.08) | `strategyCapitals.rebuilder` | `/bdvm` | No. |
| 10 | **Roster-specific marginal** | Yes | `src/roster_intel/marginal.py::position_marginals` | `marginalStrengthIndex` (+ deprecated alias `marginalPoints`, `marginal.py:172-173`) | `/gameplan` — which **has no frontend consumer at all** (W20-F001) | No. Correctly renamed off "points"; units are ROS strength index, not trade units. |
| 11 | **Waiver** | Yes | `src/trade/waiver.py::find_waiver_candidates` | `consensusValue`, plus alias `adjustedValue` | `/waivers`, `POST /api/waiver/*` | **Name-level only.** `waiver.py:68` sets `"adjustedValue": self.consensus_value` verbatim — no adjustment is applied, and it is labelled `# alias for backwards compat`. Nothing downstream treats it as adjusted. |
| 12 | **Rookie-pick** | Yes | stage 10 (year discount) + stage 11 (rookie-pool tethering) | `rankDerivedValue` on pick rows, `pickYearDiscount`, `pickRookieAnchor`, `pickProjectedDraftValue` | `/draft`, `/trade`, `PlayerPopup` | **No.** Verified live: `2026 Pick 1.01` → 7,799 anchored to Jeremiyah Love; `2029 Early 1st` → 2,668 with `pickYearDiscount 0.53` and `pickProjectedDraftValue 5034` (= 2668/0.53). `src/ros/pick_projection.py` supplies slot *order* only, never a value. |
| 13 | **Trade-clearing / normalized** | Yes | `src/trade/ktc_va.py::adjusted_pair_totals` ≡ `frontend/lib/trade-logic.js::ktcAdjustPackage` | package-level `vaNet`, `giveTotal`/`receiveTotal`/`gap` | `/trade` TradeMeter, `/trades` grades, `suggestions.py::_va_gap` | **No** — package scope only, never written onto a player row. But there are **four** implementations (V8). |

**Two concepts the brief did not name, both of which matter:**

| # | Concept | Field | Why it matters |
|---|---|---|---|
| 14 | **Offense-only board** — an IDP-disabled re-run of the whole pipeline | `offenseOnlyRankDerivedValue` (606 rows, 262–9,987) / `_offenseOnlyFinalAdjusted` | This is the substitution vector for V2 and V3. It is a legitimate second concept with no name of its own on the wire. |
| 15 | **Injury-decayed value** | `injuryAdjustedValue` = live value × decay (`src/api/injury_impact.py:37`) | Terminal `BuySellHold` only, always rendered beside the undecayed number. Clean — though the decay *trigger* misfires on contract news (W21-F001). |

And one that is not a player value at all but is named like one: `/api/draft-capital`'s
`rookieKtcValue` carries **auction dollars** (live range 91.5–135.5), documented at
`server.py:8208-8218`. `/draft` renders a `ValueBasisNote`, so no user-visible defect today.

---

## 3. Every distinct value field in the live contract

Measured on `GET /api/data`, 1,092 rows. Command in §9.

| Field | Rows non-null | Range | Scale | Written at | Read by |
|---|---|---|---|---|---|
| `rankDerivedValue` (playersArray + legacy dict) | 812 | 757 – 9,988 | **board 0-9999** | `data_contract.py:9229-9236` | 64 frontend sites, 165 backend lines. `board_values_from_contract` (`finder.py:346`) and `get_active_value` (`league_intel/values.py:241`) are the only two named selectors; 24 other backend call sites inline the read |
| `values.overall` / `.finalAdjusted` / `.displayValue` | 812 each | 757 – 9,988 (identical) | board | same single branch | `/rosters`, `/trades`, `trade-logic`, `RosTradeFitPanel` (45 `values?.full` sites) |
| `values.rawComposite` | 1,074 | 138 – 9,999 | **composite** (median 1.0855× board) | mirrored from scraper | `inferValueBundle` "Raw" mode, `/trade` Raw value mode |
| `_finalAdjusted` = `_composite` = `_rawComposite` (legacy dict) | 1,074 each | 138 – 9,999 | **composite** | `Dynasty Scraper.py:7120-7128` | `finder.py:498` (legacy branch), `finder.py:1006` (diagnostic on the composite threshold), `dynasty-data.js` overlay scaling |
| `offenseOnlyRankDerivedValue` / `_offenseOnlyFinalAdjusted` | 606 | 262 – 9,987 | board, **different board** | `data_contract.py:9192,9263` | `suggestions.py:626,767,1739`, `trade_simulator.py:64`, `finder.py:495` |
| `_blendedValueUncapped` | 990 | 195 – 9,988 | board, pre-clamp | pipeline stage 6 | audit/diagnostic |
| `anchorValue` | 918 | 757 – 9,999 | board | pipeline stage 5 | `PlayerPopup` methodology panel |
| `subgroupBlendValue` | 852 | 594 – 9,987 | board | pipeline stage 5 | `PlayerPopup` methodology panel |
| `pickProjectedDraftValue` (+`Gain`, `GainPct`) | 103 | 1,297 – 7,799 | board | `_stamp_pick_value_projections` | `/draft` |
| `fantasyProsIdpNormalizedValue` | 211 | — | source-normalized | `data_contract.py:3762` | **nobody** — zero readers in `src/` or `frontend/` |
| `canonicalSiteValues{}` | 1,092 | mixed | **two meanings** — real values for value-signal sources, synthetic ~999900 encodings for rank-signal sources | scraper + contract | `PlayerPopup`, `/trade` source breakdown (21 sites) |
| `rawSourceValues{}` | 1,092 (sparse: `ktcSfTep`) | vendor | vendor native | contract | popup chips (24 sites) |
| `sourceNativeValues{}` | 1,092 | vendor (e.g. `otcffbSf: 92.7`, `fantasyCalc: 10338`) | vendor native | contract | source charts (16 sites) |
| `hillValueSpread` | 1,092 | — | diagnostic | `data_contract.py:7965` | popup |
| `injuryAdjustedValue` | terminal rows | board × decay | board | `injury_impact.py:37` | `BuySellHold` |
| `_fallbackValue` | 108 (legacy dict) | boolean | **flag, not a value** | `Dynasty Scraper.py:6882,6962` | scraper-internal |
| `_canonicalDisplayValue` | **0** | — | — | never written | never read (only `dynasty-data.js:156` records this) |
| `factors{}` (`/api/valuation/league-adjusted`) | 709 | 0.979705 – 1.09776 | dimensionless | `league_intel/adjustment.py` | client overlay + `_valuation_scoped_contract` |
| `rosValue` (`/api/ros/player-values`) | 500 | 9.4 – 86.79 | **0-100 ordinal log-rank index** | `src/ros/aggregate.py:171` | ROS surfaces, `compute_scarcity` |
| `dollarValue` / `rookieKtcValue` (`/api/draft-capital`) | per pick | 91.5 – 135.5 sampled | **auction dollars** | `server.py:8208-8218` | `/draft` |

**The `finalAdjusted` trap, verified in one payload:** `playersArray[Bijan Robinson].values.finalAdjusted = 9706`
(board) while `players["Bijan Robinson"]._finalAdjusted = 9999` (composite). Same name, two
scales, one response. Josh Allen: 9,988 vs 9,983. Travis Hunter: 4,401 vs 4,654. This is the
mechanism behind W00-F006.

---

## 4. The single-source-of-truth rule: does it hold?

**The rule, as CLAUDE.md states it:** "The live `/api/data` contract is the single source of
truth"; "every engine reads exactly one value — `rankDerivedValue`"; "there is no frontend
ranking engine, period."

**Verdict, split three ways:**

| Claim | Verdict |
|---|---|
| One function computes the board | **Holds.** `_compute_unified_rankings` is the only producer, and it is bit-reproducible (W02-F012). |
| No frontend ranking engine | **Holds.** Fail-fast is real; the only client arithmetic is `× factor` with server-supplied factors and server-supplied ranks. |
| Every engine *reads* `rankDerivedValue` | **Holds for the read.** |
| Every engine *serves* `rankDerivedValue` | **Fails.** |
| One number per player per session | **Fails.** |

### Violations, with evidence

**V1 — `/rankings` renders a board no engine prices from.** P0. `frontend/components/useSettings.js:35`
sets `SETTINGS_DEFAULTS.tepMultiplier = 1.15`, and `tepMultiplierIsCustomized()` returns true for
any finite number, so **every** page load — including a browser with empty localStorage — POSTs
`{"tep_multiplier":1.15}`. `data_contract.py:6939`'s `if not tep_multiplier_is_override:` then
skips the ADR-015 TE-basis curve entirely and falls through to a flat 1.15 — the exact constant
ADR-015 retired for sitting below the measured 1.209–2.05 range. Result: 627 of 740 ranks, 654
tiers and 135 values differ from `GET /api/data`, while the response stamps `isCustomized:false`.
Tyler Conklin renders #666 / 1,142 against #469 / 1,450 canonical (−21.2%). Brevin Jordan renders
1,243 while `/api/waiver/faab-recommend` answers 1,519.0 in the same session.
*Verifier position:* W03-F001 **rescoped** — reproduction re-ran to the digit; `pagesAffected`
raised 1 → 10; the empty-body control (`{}`) returns a byte-identical board, proving the
*presence* of the key, not its value, causes the divergence. W07-F001 **rescoped** —
`pagesAffected` 5 → ~30 (AppShell hydrates `useDynastyData` on every private page), and `/draft`
reclassified as a two-boards-on-one-page case because it fetches `/api/data` directly. W08-F001
**upheld**, `pagesAffected` 6 → 11 understated. All three keep P0.

**V2 — the trade engines emit the offense-only board under the consensus board's field name.**
`suggestions.py::_serialize_player` (`:1737-1741`) writes `p.offense_only_value` into
`displayValue` whenever `_trade_is_idp_free(give, receive)`. Re-run today:
**19 of 51 asset legs across all 12 rosters disagree with the board in default market mode**;
worst case Travis Hunter, shown **5,637** on `/trade` against **4,401** on `/rankings` (+28.08%)
— the offense-only board never saw stage 9's two-way boost, so a documented post-blend override
is silently reverted on a user-facing surface. The same player can carry two different
`displayValue`s inside one response (Brian Thomas 4,436 in a suggestion leg, 4,466 in
`rosterAnalysis.byPosition`).
*Position:* W29-F001, P1, unverified by an adversarial pass but its reproduction re-runs exactly.

**V3 — `valuationMode: leagueAdjusted` is stamped on responses that are partly unadjusted.**
`overlay.adjusted_rows` scales exactly one key (`overlay.py:90-93`); `offenseOnlyRankDerivedValue`
rides through untouched. Re-run today: **21 of 51 legs still at the unadjusted offense-only
value** under `leagueAdjusted`, and 12 of 12 for one roster. Kenneth Walker: `rankDerivedValue`
5,813 × factor 1.041554 = **6,055 expected, 5,831 served** (= the offense-only value), with
`valuationNote: null`.
*Verifier position:* W29-F002 **rescoped** — upheld on substance, P1 unchanged, but the defect
is **arithmetic, not serialization**: `_eff_val` (`suggestions.py:760-768`) is called at 11 sites
that pick targets and compute gap/fairness, so an IDP-free suggestion is *constructed* on the
unadjusted board. Routes corrected 6 → **3 measured** (`/api/trade/suggestions`,
`/api/trade/simulate`, `/api/trade/finder`); players corrected 606 → **416** (rows carrying an
offense-only value *and* a non-unit factor). W09-F006 independently measured
`/api/trade/simulate` returning byte-identical equity 4004 under both modes, with an IDP-bearing
control proving the plumbing works (Bowers 9,947 → 10,062).

**V4 — the two overlay appliers are not the same function.** Server side scales
`rankDerivedValue` only. Client side (`dynasty-data.js:1943-1952`) additionally scales
`values.overall`, `values.finalAdjusted`, `values.displayValue`, and at `:1978` `_finalAdjusted`
— a *composite*-scale number multiplied by a *board*-derived factor. Neither side touches the
offense-only key. Cited in W29-F002 and confirmed by its verifier. Practically the client applier
is dead: W07-F006 captured a real toggle click and found **zero** `GET /api/valuation/league-adjusted`
requests — V1 makes every session "customized", so the lens always rides the override POST and is
composed server-side. ~150 lines of merge logic and their regression suite guard an unreachable
path.

**V5 — the legacy composite branch in the arbitrage finder is still in the tree.**
`finder.py:498` reads `_finalAdjusted` when no contract is supplied. Traced: the sole HTTP caller
(`server.py:6190`) always passes `contract=contract` and the route is gated by
`require_loaded_contract=True`, and the live probe stamps `metadata.valueSource:
"rankDerivedValue"`. So the branch is **unreachable from HTTP** — which answers the question
W00-F006 left open — but it remains two scales in one function.

**V6 — `exports/latest/dynasty_full.csv` publishes the pre-canonical composite under the column
name `Composite`.** Re-run today: **805 players matched, exactly 1 exact-equal, median ratio
1.0855** (p10 0.9555, p90 1.2601 measured over the same pairs on the contract). It is not a
constant rescale, so no factor corrects it: Lamar Jackson 7,631 vs 8,784 (0.869×), Carson
Schwesinger 4,357 vs 5,908. No HTTP route serves the file, so reach is limited to whoever opens
the repo or the release bundle. W29-F003, P2, `Duplicate or conflicting implementation`.

**V7 — there is no historical record of the served board at all.** Archived exports carry
`_composite`/`_finalAdjusted` and **no** `rankDerivedValue`, `canonicalConsensusRank`,
`confidenceBucket` or `sourceRanks`. Every "historical" backtest therefore rebuilds a board by
calling `build_api_data_contract` on an old payload, which reads today's CSVs from disk — 18 of
21 sources leak in, including two whose CSVs first entered the tree three weeks after the
snapshot date. W04-F009, **rescoped** by its verifier, P1 → P2. Downstream: `/trades` grades 110
trades spanning 2025-08-05 → 2026-07-31 against the 2026-08-04 board (W29-F004), and
`data/rank_history.jsonl` does not exist in this container, so the as-of badge path is inert
(`GET /api/data/rank-history?days=365` → `{"days":365,"history":{}}`) — **Blocked by data**, not
broken code.

**V8 — four implementations of the KTC value adjustment ship simultaneously.** `src/trade/ktc_va.py`,
`src/trade/market_value_adjustment.py`, `src/trade/finder_value_adjustment.py`, plus the JS port
in `frontend/lib/trade-logic.js`. Re-run today: over 20,000 random packages the first two
disagree on **38** (0.19%), always by exactly 1 — `ktc_va` uses `round()`, the others
`floor(x+0.5)`. Worked example `A=[4581,6362,4354] B=[7181,3245]` → **1281 vs 1280**. `ktc_va`'s
own parity test asserts agreement "to ±1", exactly the size of the divergence. W30-F005, P2.

**V9 — one field name, two meanings, inside `canonicalSiteValues`.** Real vendor values
(`ktc: 9983`) sit beside synthetic rank encodings (`dlfSf: 999900`, `draftSharks: 100`) in the
same dict, and the popup renders both. This is the encoding CLAUDE.md warns BDVM's market layer
never to read; nothing warns the UI.

### Two claims that do NOT hold up, recorded so they are not carried forward

- **PRIOR-A01-F00 (severity "critical") is refuted.** The claim was that the `/rankings` Value
  column silently falls back to the raw scraper composite for 260 rows. Re-run today:
  **0** rows have `values.displayValue` null while `overall`/`finalAdjusted` is set;
  `data_contract.py:9229-9236` writes all three in one branch gated on `rdv is not None and rdv > 0`.
  Devin Bush reads `{overall: null, finalAdjusted: null, displayValue: null, rawComposite: 2544}`.
  The prior evidence cited the *scraper export*, not the contract. PRIOR-A09-F07
  ("`values.displayValue` is produced by none") falls on the same evidence — it is produced at
  `:9233` and non-null on 812 rows. W29-F006.
- **W11-F022's mechanism does not reproduce; its row census does.** The finding states that on
  the default `view=app` payload `buildRows` takes a branch where `values.full` falls back to
  `_finalAdjusted`, pricing 4 waiver-drop rows off the composite. Executed here: `inferValueBundle`
  (`dynasty-data.js:157-168`) returns `full = rankDerivedValue ?? 0` — board only — so running
  `buildRows` over the live payload gives Devon Witherspoon `{raw: 1935, full: 0}`, and **0 of
  1,072 rows** have `values.full > 0` without a backend `rankDerivedValue`. `waiver-logic.js`
  contains no reference to `_finalAdjusted`, `_composite` or `rawComposite`. The four unpriced
  rows are real and they do enter waiver math **at 0**, which is a defect of the class W08-F006
  describes — but not the composite-contamination this finding names.

---

## 5. ROS contamination — the verified position

**Can a ROS value reach dynasty rankings?** **No.** W17-F003 (`Implemented and verified`) ran
three independent checks: zero keys matching `^(ros[A-Z]|ros_|restOfSeason|teamRos)` at any depth
of the live contract; zero imports of `src.ros` in `src/api/data_contract.py`, `src/trade/*` or
`src/canonical/*`; every write under `src/ros/` resolving inside `data/ros/`. W29 independently
confirmed the pick path: `pickProjectedDraftValue = rankDerivedValue / pickYearDiscount`
(verified live: 2668/0.53 = 5034), and `src/ros/pick_projection.py` supplies projected *slot
order* only, per its own docstring.

**Can a ROS value reach the trade calculator?** **Not as a value. Yes as a multiplier, under one
toggle.** This is the distinction that matters and it is easy to get wrong in both directions.

1. **The load-bearing door — the league-adjusted lens.** `src/league_intel/replacement.py` runs
   `src.ros.lineup.optimize_lineup` over `rosValue` (`:212, 312, 388, 399, 580, 631`) to measure
   endogenous starter demand, reading rosters from `data/ros/team_strength/<league>.json`.
   `compute_scarcity` builds every component from `rosValue` — verified live, the
   `/api/valuation/league-adjusted` `scarcity` block reports `lineupScarcity`, `rosterScarcity`,
   `eliteSeparation` and `starterSeparation` per position, all in ROS units. `lineupScarcity`
   feeds `structural_scarcity_axis` (`adjustment.py:247`, `delta = (value − 0.5) × sensitivity`)
   → `factors` → `overlay.adjusted_rows` → every engine under `valuation_mode=leagueAdjusted`.
   Measured live: 709 factors, **exactly one distinct factor per position** (DL 1.097760,
   RB 1.041554, WR 1.026798, QB 1.018366, DB 1.011826, TE 1.011595, LB 0.979705), against
   `lineupScarcity` DL 0.7672 / RB 0.7078 / WR 0.6340 / LB 0.5985. That proves the documented
   design property — the factor is a function of position alone and never reads the consensus
   value, so it composes against any board.
   *The honest statement of the problem:* the influence is **dimensionally safe** — a ratio of
   two `rosValue`s cancels units, so this is not the 0-9999-vs-0-100 error of the tags. But
   `rosValue` is `100*(ln(N+1)−ln(r))/ln(N+1)`, an **ordinal** log-rank index, so a ratio of two
   of them is not the cardinal "drop from the top RB to the last starting RB" the name implies.
   `replacement.py:20-52` documents the resulting bias honestly (projection path measures FLEX-TE
   share at 0.0% vs 10.4% on weekly actuals) — but that docstring sits on the measurement
   function, not on the published board, and the `/rankings` toggle says nothing about ROS being
   its input. W29-F007, `Partially implemented`, P2, confidence **medium**. Guardrails are real:
   evidence tier `STRUCTURAL_ONLY`, absent axes contribute exactly 0 (live `inactiveAxes:
   ["tePremium","projectionCorroboration","receptionFit"]`), `monotonicityViolations: []`,
   observed factor span −2.0% to +9.8%, and `docs/adjusted-board-backtest.md` records the board as
   a deliberate toggle because four backtest framings found no improvement.

2. **The leaky door — and it is closed by arithmetic, not by design.** Three copies of one
   predicate compare a 0-9999 board value against `rosValue × 0.7`:
   `frontend/components/PlayerPopup.jsx:108` (fed `row.values?.full ?? row.rankDerivedValue` at
   `:142`), `frontend/components/RosTradeFitPanel.jsx:75` (renders on `/trade`), and
   `src/ros/tags.py:71`. Re-run today: `max(rosValue) × 0.7 = 60.8`, `min(rankDerivedValue) = 757`
   — **0 of 1,092 rows can satisfy it.** The "Seller cash-out" tag has never rendered. This is a
   silent absence, not a wrong number. Addition to the finding: `src/ros/tags.py::tags_for_player`
   has **zero callers** anywhere in `src/`, `scripts/` or `server.py` — the Python copy is
   `Scaffolded only`; only the two JS copies are live. W29-F005, P3, confirming
   PRIOR-A01-F14 / A02-F06 / A19-F13.

The firewall itself is the best scale discipline in the repo. `src/api/gameplan.py:34-60`
deliberately withholds `site_values` from the ROS target engines and states why: feeding 0-9999
numbers into a `(ros_value − price)/price` edge would return ≈ −0.99 for every player alive.
`src/api/gameplan.py:244` says "NEVER mixed with rosValue" at the one place `src/ros/lineup.py`
is shared. The optimizer is a pure function of slots and weights, not a value — the reverse
import is real and benign.

---

## 6. The 1..9999 scale

### Where it holds

| Quantity | Rows | Live range | Scale |
|---|---|---|---|
| `rankDerivedValue` | 812 | 757 – 9,988 | board 0-9999 ✅ |
| `values.overall` / `.finalAdjusted` / `.displayValue` | 812 | 757 – 9,988, identical | board ✅ |
| `offenseOnlyRankDerivedValue` | 606 | 262 – 9,987 | board scale, different board ⚠ |
| `_blendedValueUncapped` | 990 | 195 – 9,988 | board, pre-clamp ✅ |
| `anchorValue` | 918 | 757 – 9,999 | board ✅ |
| `pickProjectedDraftValue` | 103 | 1,297 – 7,799 | board ✅ |

Inside the contract the board scale holds. It does not hold at four boundaries.

### Where it breaks

| Break | Evidence |
|---|---|
| **The adjusted lens exits the ceiling.** `overlay` is a plain multiply with no renormalization, so Josh Allen renders **10,171** (9,988 × 1.018366) and Bijan 10,109 under "My league". Value bands and any consumer assuming a 9,999 ceiling see out-of-range input. W07-F008, P3 |
| **The composite is a different scale wearing the same names.** `_finalAdjusted`/`_composite`/`_rawComposite` span 138 – 9,999 at a median 1.0855× the board, and the ratio is class-dependent, not constant: median 1.1034 offense, 1.0467 IDP, 1.0629 picks. W08-F007 measured the consequence end-to-end: Sam LaPorta and Sonny Styles both carry `rankDerivedValue` 5,222; one dropdown click from "Our Value" to "Raw" turns `5,021 vs 5,222 FAIR, B wins 4%` into `5,564 vs 4,180 UNFAIR, A wins 25%`. The verdict flips severity *and* direction, with nothing on screen saying the modes are incomparable. P1 |
| **The Monte Carlo clamp is one-sided.** `_shifted()` clamps to 9999 while the +15% leg is not, so a top asset's sampled mean falls *below* its board value: Brock Bowers 9,947 simulates at 9,441.9 (−5.07%). Its verifier ran the unclamped control and got equality to 0.008%, proving the clamp is the sole cause. W09-F005, **rescoped**, P1 |
| **Rounding disagrees with itself.** `rankDerivedValue` is `int(norm_val)` (truncation) while `_blendedValueUncapped` is `int(round(...))`, so **280 rows** publish a value exactly 1 below their own blend. Sub-point magnitude; it makes ~35% of rows disagree with their own audit stamp. W02-F010, P3 |

### Are 0-100 scores and probabilities kept visibly distinct from trade units?

**On the contract, yes — by naming discipline that actually holds.** Enumerating every numeric
row field with a maximum ≤ 100 returns only: `alphaShrinkage` [0, 0.1], `identityConfidence`
[0.7, 1.0], `marketConfidence` [0.3457, 0.5938], `marketDispersionCV` [0, 0.248],
`sourceRankPercentileSpread` [0.0038, 0.8506], `softFallbackCount`, `sourceCount`, `age`,
`yearsExp`, `pickProjectedDraftValueGainPct`. Every one of them is named for what it is; none is
named `*Value`. `rosValue` — the one 0-100 quantity that *is* named like a value — **does not
appear on the contract at all**; it lives only on `/api/ros/player-values`.

**Three exceptions, in descending severity:**

1. `rosValue` is compared against a board value in three code paths (§5.2). Unreachable today,
   but the naming is what let it survive review three times.
2. `rookieKtcValue` / `dollarValue` on `/api/draft-capital` carry auction dollars while wearing a
   value-shaped name. `/draft` labels the basis, so no live defect.
3. The scale itself is **never stated in visible text**. `/rankings` prints "9,988" with no unit;
   the only disclosure is `title="Hill-curve value … (scale 1–9,999)"` — one of 1,933 `title`
   attributes on the page, and `title` never fires on touch. W26-F013, P2.

Two quality caveats on the confidence scores themselves, which belong here because they are
rendered beside the value: `marketConfidence` is structurally confined to roughly [0.20, 0.594]
because its site-count term divides by 8 while the scraper never supplies more than ~5
(W03-F008 — live range 0.3457–0.5938 corroborates), and `identityConfidence` is a four-valued
proxy for "does this row have a Sleeper ID" presented as a 0-1 score (W03-F009 — live range
0.7–1.0 over all 1,092 rows).

---

## 7. What works — do not "fix" these

Stated plainly, because a list of only defects is not an audit.

- **The blend is exactly reproducible.** A clean-room reimplementation matches
  `_blendedValueUncapped` on 800/800 rows, `droppedSources` on 800/800, `anchorValue` on 800/800,
  `subgroupBlendValue` on 800/800; two in-process rebuilds hash identically; the in-process
  rebuild matches the *served* `rankDerivedValue` on 1,092/1,092. Three CLAUDE.md claims fall out
  as proven: the retired λ·MAD penalty touches nothing, `softFallbackCount` touches nothing, and
  α-shrinkage applies to IDP + pick rows only. W02-F012.
- **Post-blend stages are exact.** All 35 single-source rows satisfy
  `_blendedValueUncapped == round(0.30 × anchorValue)`; no pick row is haircut; 536/536 TE basis
  conversions reproduce from the stamped percentile; zero rows carry both `tepBoostApplied` and
  `tepNativeCorrectionApplied`; all 72 current-year slot picks equal their rookie-pool anchors.
  W02-F013.
- **Missing data abstains rather than defaulting.** 280 rows publish `rankDerivedValue: null`
  rather than a floor. The only fabricated values on the board are 12 synthetic 2029 pick rows,
  and they are labelled `confidenceLabel: 'Low — single pick source'`, `isSingleSource: true`,
  with `sourceAudit.allowlistReason` explaining the clone. W02-F014.
- **The arbitrage finder's migration is real and proves it at runtime.** Live probe:
  `metadata.valueSource: "rankDerivedValue"`, `assetsUnpricedByBoard: 186`, per-market
  `marketCoverage: {ktcSfTep: 132, ktc: 18, idpTradeCalc: 150}`, `marketTopNFilter: 150`. Unpriced
  assets are counted, not silently dropped, and the payload warns that unpriced ≠ worthless. The
  engine is no longer offense-only (W09-F014).
- **`/rankings` sort, render and export agree exactly.** All four consumers use the identical
  expression `row.rankDerivedValue || row.values?.full || 0` (`page.jsx:596-597`, `:764`,
  `:1050`, `:1977`), and the CSV carries a `Value Basis` column so an exported adjusted board
  cannot be mistaken for a market one. Every in-app export agrees with its screen.
- **No cache can serve a stale board across a mode switch.** `cacheable = not want_league_adjusted`
  (`server.py:3988`) means adjusted responses are never cached at all; `useTerminal`'s key
  includes `valuationMode` with a comment saying exactly why.
- **The no-frontend-ranker rule holds**, including its fail-fast.
- **The lens is genuinely composed server-side** and `overlay.adjusted_rows` returns **all** rows
  rather than `compact_ranks_and_tiers`' ranked subset — the 2026-picks-vanish bug its comment
  describes is really prevented. `isNoop: false`, 709/1,092 adjusted, `monotonicityViolations: []`,
  `warnings: []`.
- **BDVM degrades honestly.** With `data/bdvm/projections/` absent the endpoint answers
  `status: "no_projection_snapshot"` with full version metadata, and every consuming surface
  vanishes rather than rendering a hole. Market isolation is structurally verified (W13-F008), and
  its value scale respects the ceiling (W13-F011).
- **`src/api/gameplan.py:34-60` and `frontend/app/rosters/page.jsx:24-41`** are the two best
  pieces of scale/naming discipline in the codebase. Keep them.

---

## 8. Corrections to authored claims

Where a verifier moved a position, this document reports the verified one.

| Finding | Authored | Verified | What changed |
|---|---|---|---|
| W03-F001 | P0 | **P0, rescoped** | Reproduction re-ran to the digit. `pagesAffected` 1 → 10. Empty-body control proves the *presence* of `tep_multiplier`, not its value, causes the divergence. |
| W07-F001 | P0 | **P0, rescoped** | `pagesAffected` 5 → ~30; `/draft` reclassified from "1.15 board" to "renders both boards at once". |
| W08-F001 | P0 | **P0, upheld** | Only correction: `pagesAffected` 6 → 11 understated. Verifier additionally established there is **no** user-facing path to the un-overridden board (the settings "Reset to default" button writes 1.15, still an override). |
| W29-F002 | P1 | **P1, rescoped** | Upheld on substance. Mechanism corrected from *serialization* to *arithmetic* (`_eff_val` drives target selection and gap). Routes 6 → 3 measured. Players 606 → 416. |
| W02-F001 | P1 | **P1, rescoped** | Mechanism confirmed to the digit, but the published reproduction command **does not produce the cited numbers** — the verifier rebuilt the measurement independently. `playersAffected` 398 → **281** (398 counts all DL/LB/DB rows; 117 carry only anchor sources). The finding's `requiredRepair` (route to GLOBAL) is **not endorsed**: a second scale defect compounds — the IDP master is fit on a slice renormalized so the best IDP = 9,999 while that player's anchor value is 6,444, i.e. the curve is fit in units 1.552× the scale its output is consumed in. The naive re-route moves affected rows a median +8.94% (p90 +42.1%) with no validation. |
| W03-F006 | **P0** | **P2, rescoped** | The largest correction in §7. The verifier rejected the inferential step: `rawRank / poolSize` is not a valid ground truth, because nested-subset boards that agree perfectly get the same ordinal and dividing by different pool sizes manufactures disagreement. The real incommensurability is asset-class *composition* (KTC = 463 OFF + 36 PICK; idpTradeCalc = 437 OFF + 370 IDP + 96 PICK, biases pushing opposite ways). Re-densifying within asset class: the pick flip rate collapses from **23/24 to 1/24**; only **8** rendered `/rankings` badges are opposite and **1** is materially wrong. The P0 anchor was wrong on its own facts — Calvin Ridley's BUY label is **correct**. Blast radius overstated ~30×. The sub-claim that the Edge column has "no coverage note" is false; a per-row hover explanation is rendered. |
| W04-F009 | P1 | **P2, rescoped** | Retained as the reason no historical board exists. |
| W09-F005 | P1 | **P1, rescoped** | Arithmetic confirmed three times; verifier added the unclamped control that isolates the clamp as sole cause. |
| PRIOR-A01-F00 | "critical" | **Refuted** | 0 rows reproduce; prior read the scraper export, not the contract. W29-F006. |
| PRIOR-A09-F07 | — | **Refuted** | `values.displayValue` is produced at `data_contract.py:9233`, non-null on 812 rows. |
| W11-F022 | P3 | **Mechanism not reproduced** (this document) | Row census holds (4 rows unpriced with a non-null composite); the stated composite fallback does not exist on this build — `buildRows` yields `values.full = 0` for all of them, and `waiver-logic.js` never reads a composite field. The residual defect is unpriced-drop-at-zero, which W08-F006 owns. |

### Not proven — recorded as such

- **Whether the un-overridden ADR-015 board is better than the 1.15 board.** V1 proves the two
  boards differ and that no user can reach the canonical one. It does not prove which is right.
  The rollback switch is `RISKIT_FEATURE_TE_BASIS_CONVERSION=0`.
- **Whether the league-adjusted lens improves anything.** `docs/adjusted-board-backtest.md`
  records four framings returning "no difference detected", three leaning negative. W29-F007's
  confidence is **medium** for this reason.
- **Whether the offense-only board is the right value for an IDP-free trade.** The audit proves
  it is served under the wrong field name and unadjusted by the lens. Whether IDP source
  calibration *should* be excluded from an all-offense trade is a design question this audit did
  not settle.
- **The retro trade-grading path could not be exercised.** `data/rank_history.jsonl` is absent in
  this container — **Blocked by data**, not Missing. The pick-history gap (24% of traded assets,
  60% of trades) is structural and survives populating it.
- **BDVM's four fundamental concepts (1, 7, 8, 9) could not be executed.** `data/bdvm/projections/`
  is absent — **Blocked by data**. Their separation is verified by code structure and by the
  endpoint's honest degradation, not by comparing live numbers.

---

## 9. How to re-run everything in this document

```bash
# 0) session + contract  (protocol §"The stack is RUNNING")
SECRET=$(cat /tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/e2e_secret.txt)
curl -s -c /tmp/vfm-cookies.txt -X POST http://127.0.0.1:8000/api/test/create-session \
  -H "Authorization: Bearer $SECRET"
curl -s -b /tmp/vfm-cookies.txt "http://127.0.0.1:8000/api/data"          -o /tmp/vfm-full.json
curl -s -b /tmp/vfm-cookies.txt "http://127.0.0.1:8000/api/data?view=app" -o /tmp/vfm-app.json

# 1) §4 violations V2 / V3 / V6 + the §5 ROS scale mix + the PRIOR-A01-F00 retest
OUT=/tmp/vfm-w29 bash docs/master-site-audit/evidence/W29/repro.sh
#   -> market mode : 19/51 legs disagree with rankDerivedValue
#   -> worst       : Travis Hunter shown=5637 board=4401 (+28.08%)
#   -> adjusted    : 21/51 legs still at the UNADJUSTED offense-only market value
#   -> matched 805 | exact-equal 1 | median ratio 1.0855
#   -> max(rosValue*0.7)=60.8  min(rankDerivedValue)=757  rows able to fire: 0
#   -> rows with values.displayValue null but overall/finalAdjusted set: 0

# 2) §3 field census (rows, ranges, scales)
.venv/bin/python - <<'PY'
import json, statistics
d = json.load(open("/tmp/vfm-full.json"))
pa, pl = d["playersArray"], d["players"]
def rng(vals, label):
    nn = [v for v in vals if isinstance(v, (int, float))]
    print(f"{label:34s} n={len(nn):5d} [{min(nn)}, {max(nn)}]")
rng([r.get("rankDerivedValue") for r in pa], "rankDerivedValue")
rng([(r.get("values") or {}).get("displayValue") for r in pa], "values.displayValue")
rng([(r.get("values") or {}).get("rawComposite") for r in pa], "values.rawComposite")
rng([r.get("offenseOnlyRankDerivedValue") for r in pa], "offenseOnlyRankDerivedValue")
rng([r.get("_finalAdjusted") for r in pl.values()], "legacy _finalAdjusted")
ratio = sorted(r["_finalAdjusted"] / r["rankDerivedValue"] for r in pl.values()
               if r.get("_finalAdjusted") and r.get("rankDerivedValue"))
print("composite/board  n=%d median=%.4f p10=%.4f p90=%.4f"
      % (len(ratio), statistics.median(ratio),
         ratio[len(ratio) // 10], ratio[9 * len(ratio) // 10]))
print("Bijan array values:", pa[[r["displayName"] for r in pa].index("Bijan Robinson")]["values"],
      "| legacy _finalAdjusted:", pl["Bijan Robinson"]["_finalAdjusted"])
PY

# 3) §5 the lens is a function of position alone, and its inputs are ROS units
curl -s -b /tmp/vfm-cookies.txt http://127.0.0.1:8000/api/valuation/league-adjusted \
| .venv/bin/python -c "import json,sys; d=json.load(sys.stdin); \
print({k: round(v['lineupScarcity'],4) for k,v in d['scarcity'].items()}); \
print('factors', len(d['factors']), min(d['factors'].values()), max(d['factors'].values())); \
print('inactiveAxes', d['inactiveAxes'], 'monotonicityViolations', d['monotonicityViolations'])"

# 4) §4 V8 — the KTC value-adjustment ports disagree
.venv/bin/python -c "
import random
from src.trade.ktc_va import ktc_adjust_package as a
from src.trade.market_value_adjustment import ktc_adjust_package as b
random.seed(11); n=0
for _ in range(20000):
    A=[random.randint(200,9999) for _ in range(random.randint(1,5))]
    B=[random.randint(200,9999) for _ in range(random.randint(1,5))]
    n += int(int(a(A,B).value) != int(b(A,B).value))
print('divergences of 20000:', n, '| example', a([4581,6362,4354],[7181,3245]).value,
      'vs', b([4581,6362,4354],[7181,3245]).value)"

# 5) §1.3 + §8 W11-F022 — run the real materializer over the real payload
cat > /tmp/vfm_buildrows.mjs <<'JS'
import fs from "fs";
const m = await import("/home/user/riskittogetthebrisket/frontend/lib/dynasty-data.js");
const rows = m.buildRows(JSON.parse(fs.readFileSync("/tmp/vfm-app.json", "utf8")));
let clientNumbered = 0, stamped = 0, maxRank = 0, leak = 0;
for (const r of rows) {
  const b = r.canonicalConsensusRank ?? r._canonicalConsensusRank ?? null;
  if (b) { stamped++; maxRank = Math.max(maxRank, b); }
  else if (r.rank && r.rank === r.computedConsensusRank) clientNumbered++;
  if (!(Number(r.rankDerivedValue) > 0) && Number(r.values?.full) > 0) leak++;
}
console.log({ rows: rows.length, stamped, maxRank, clientNumbered, compositeLeak: leak });
console.log(rows.find((r) => r.name === "Devon Witherspoon").values);
JS
(cd frontend && node /tmp/vfm_buildrows.mjs)
#   -> { rows: 1072, stamped: 740, maxRank: 740, clientNumbered: 219, compositeLeak: 0 }
#   -> { raw: 1935, full: 0 }

# 6) §1.1 stage 10 — the pick-year discount reaches only 2029
.venv/bin/python -c "
import json; from collections import Counter
d=json.load(open('/tmp/vfm-full.json'))
picks=[r for r in d['playersArray'] if (r.get('position') or '')=='PICK']
print(Counter((r['displayName'][:4], r['pickYearDiscount']) for r in picks if r.get('pickYearDiscount')))
print('priced by year', Counter(r['displayName'][:4] for r in picks if r.get('rankDerivedValue')))"

# 7) §3 frontend read-site census
cd frontend && for f in ".rankDerivedValue" "values?.full" "rawSourceValues" "canonicalSiteValues" \
                        "sourceNativeValues" "_finalAdjusted" ".rosValue"; do
  printf '%-22s %s\n' "$f" \
    "$(grep -ro --include=*.js --include=*.jsx -F "$f" app components lib | grep -vc __tests__)"
done
```

Related evidence already on disk: `evidence/W29/value-flow-map.md` (the source analysis),
`evidence/W29/{market-mode-mismatch,lens-blast,export-vs-board,league-adjusted-overlay,prior-a01-f00-test}.json`,
`evidence/W02/{w02-measurements.json,repro_blend.py,rebuild_determinism.py}`,
`evidence/verify/verdicts-B1.jsonl` (W03-F001), `verdicts-B5.jsonl` (W02-F001),
`verdicts-B8.jsonl` (W29-F002).
