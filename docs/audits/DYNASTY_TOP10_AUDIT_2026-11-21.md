# Dynasty Top 10 audit and Chase Trade Market status — 2026-11-21

**Directive:** `docs/owner/DYNASTY_TOP10_TRADE_MARKET_DIRECTIVE_2026-11-21.md`. **Intake:** DYN10-1 … DYN10-14.
**Authorization:** `docs/EXECUTION_PLAN.md` (2026-11-21).

This is an audit record, not a second roadmap. The ranked items route into the existing planning documents, and the
implementation state of each lives in its PR.

**Method.** Five read-only audits ran against `origin/main` `110d1f54`; each finding was checked against live code before
use here:
1. CTM pipeline and PR history;
2. CTM data and collection;
3. the canonical valuation engine;
4. trade tools, advisor, posture and Manager Scout;
5. Sleeper, waivers, draft and command center.

Every number below carries its date and source. Production stores (`data/market_trades/*`, `data/intel/ledger.sqlite3`,
BDVM snapshots, the temporal ledger) are box-local and were **not** read; no production data was changed.

## Deliverable A — Chase Trade Market status report

**Headline:**
- Everything before pricing runs in production: acquisition, identity, deduplication, format dispositions and the daily
  ledger report.
- **No trade-derived price exists anywhere.** No estimator has been fitted to real trades. There is no shadow board, and
  `chaseTradeMarket` is registered nowhere.
- The project is a well-built evidence pipeline waiting on three things: an estimator, an independent-data answer, and
  four owner decisions.

| Category | Answer (dated) |
|---|---|
| Collection | **37,089 raw observations** on 2026-10-26: KTC 26,481, Sharp/Sleeper 10,309, own leagues 299. That is **37,022 underlying trades**, 36,907 confirmed unique (readiness audit RPA-COL-015). **No newer measurement exists.** The box writes counts daily to `data/market_trades/reports/latest.json`, but no workflow or route publishes them (see "Current counts" below). |
| Coverage | 11,565 distinct leagues among trades priced at trade time (2026-10-20). 6,092 Sharp-eligible leagues (2026-10-26). **Managers and lineages: not measurable on the box today.** Manager keys need a side-key secret that was never provisioned (`scripts/market_trade_ledger.py:24-31`), and the pinned lineage census (`LINEAGE_COMPONENT_CENSUS_2026-10-21.md` §7) has never run. |
| Eligibility | 18,690 trades are "graded" (priced at trade time), 2026-10-20: KTC 13,782 / Sharp 4,880 / own 27. **Graded ≠ eligible.** Native-comparable to `dynasty_main`: **1** trade. Broad context: 34,868; unsupported: 2,153 (2026-10-26). League maturity (≥3 completed seasons) is **unknown for every cohort**: the resolver lives only on unmerged #1852, so the cohort-A training set is empty by construction. **Legitimately price-informing trades today: 0 under the preregistered rules.** |
| Offense | Offense dominates every lane (positions are in the full census tables). Under the preregistration, the only defensible first estimand is the **generic offense market** from Sleeper-observed trades. The KTC lane is in-sample (next row). |
| IDP | 138 graded trades with an IDP player (DB 98, LB 41, DL 20), 2026-10-20; 332 across all lanes, 0 native-comparable. Our own league: 233 trades, 54 with IDP (DL 23, LB 34, DB 24), 2026-10-27 census. **Insufficient for any position-specific IDP price or a 3/3/3 premium**; reported as insufficient, no premium inferred (CTM-6). |
| Draft picks | 80.3% of graded trades include a pick (2026-10-20), but picks are generic-grade only (season + round), with no slot certainty. Pick pricing stays held by the preregistration. |
| Model | Implemented **only on synthetic markets** (`src/trade/market_trade_sim_bench.py`): prior-only, raw-sum L2, Bradley–Terry, and E2 (geometric q = 0.78, Huber loss, recency, caps, format covariates), with ablations and inner CV. The preregistration picks E2 and lets only its *rank* vote. The production estimator (`market_trade_price_model.py`) **was never written**. The real-trade fits in the repo estimate the package parameter q, not player prices. |
| Validation | 979 CTM tests: 973 pass. The 5 failures and 1 skip come from the source-only extract (no git commit, no export), not from `main`. Synthetic power study done (#1865). **No real-data holdout has run**, correctly: the preregistration is a draft with placeholder thresholds and the reserve (Q2) is owner-pending. |
| Production | **Absent as a price.** The routes `/api/market/trades` (plus `/reference`, `/comparable`, `/database`), the /trade "market" tab, `/market/trade-database` and the War Room "Comparable real trades" lens (`votes: False`) show trade **facts**, never prices. Nothing reads `chaseTradeMarket`; there is no flag to flip (`VOTE_RELEASE_FLAG = None`). |
| Blockers | (1) **No independent data at scale.** KTC trade rows feed KTC's own "value from trades" (`ktcTradesSfTep`, which already votes; `isUsedInVft` flips within minutes), so they are in-sample. The Sharp crawl rejects best-ball leagues, so no Sharp trade can be native-comparable to our best-ball league. The Sleeper lane is thin: first-pass backfill of 30 days, then current week only, kept 400 days. (2) Maturity resolver unmerged (#1852 is 2,110 commits behind and conflicting); the league-age rule counts Sleeper's `"0"` terminator as a previous season (`src/intel/league_filter.py:85`). (3) Owner decisions Q2, Q5, side-key custody, census approval. (4) No estimator, board, registry version or owner view. (5) **Perishable ops risk**, next row. |
| Ops risk | The daily ledger build holds every observation in memory (~20 KiB each). Peak was 870 MiB at 37k observations on 2026-10-26, growing ~27 MiB/day, under `MemoryMax=2G`. Projection: **~1.57 GiB now; the ceiling around 2026-12-09.** There is no streamed persist (none landed since #1926) and no missed-report alert. |
| Next steps | Shortest responsible path, non-voting throughout: (1) ops guard (streamed persist plus stale-report alert); (2) minimal maturity slice from #1852 on current main, including the age fix; (3) read-only aggregate box report so current counts are published; (4) owner packet Q2/Q5/side-key/census; (5) one aggregate box run feeding the power study; (6) freeze the preregistration; (7) offense-only real-data estimator on Sleeper-observed, cohort-A trades; (8) private shadow board, challenger registration and owner view. |

### CTM pipeline stages (CTM-1)

| Stage | Owner | Status |
|---|---|---|
| Acquisition: KTC (30 min), Sharp/Sleeper (4×/day), own leagues | `src/sources/ktc_trades.py`, `src/sharp/transactions.py`, `scripts/market_trade_ledger.py` | working+deployed (Sleeper lane thin) |
| Identity resolution | `src/trade/market_trade_normalize.py` | working+deployed (resolution 0.9995 / 0.9998 / 1.0) |
| Deduplication | `market_trade_groups.py` | working+deployed (KTC has no transaction id: KTC↔Sleeper matches are "probable") |
| Format dispositions | `market_trade_format.py` | working+deployed (1 NATIVE_COMPARABLE) |
| Format translators | `market_trade_format.py` registry | not implemented (empty registry) |
| Point-in-time timing | collected-at stamps, format bracket, 7-day board-lag guard | partial: no canonical prices before 2026-07-14 (permanent gap) |
| League maturity | hook in `market_trade_report.py`; resolver on #1852 | partial: every cohort `unknown`; age bug live |
| Lineage reserve / holdout | census script; reserve code on #1852 | blocked by owner decision (Q2) |
| Training set | `market_trade_eval.estimator_evidence` | partial: flags exist, no builder |
| Price estimation | `market_trade_sim_bench.py` | research-only (synthetic) |
| Evaluation | bench metrics, residual report | research-only; preregistration draft |
| Registry / promotion gate | `src/model_registry/promotion_gates.py` | implemented-but-inactive (no version) |
| Shadow board / owner view | `BOARD_DIR` | not implemented |
| Canonical voting | `chase_trade_market.py` | blocked by owner decision (owner-reserved) |

PR states:
- #1586, #1610, #1721, #1742 and #1752 are merged and live. #1610 superseded the three-disposition rule.
- #1851, #1858 and #1865 merged via train #1876.
- #1907, #1985, #1987, #1989 and #2202 are merged.
- **#1852 is open and conflicting.** It carries the age fix, `resolve_league_maturity`, the chain store, an off-by-default
  chain crawl, the maturity census, and reserve code that refuses to persist until approved.

### Current counts

The most recent committed production measurement is 2026-10-26. The box already writes
`data/market_trades/reports/latest.json` daily (counts only), and `scripts/fetch_ktc_trades.py --stats` reports archive
coverage read-only. Workstream A adds a read-only, aggregate-only workflow so these are published without anyone opening
a shell. The heavy census (`market_trade_ledger.py --census`) rebuilds the ledger in memory (870 MiB+), and its own
document says agents do not run it against production. It stays an owner/operator action.

### Owner decision packet (prepared, not decided)

| # | Decision | Recommendation | Why |
|---|---|---|---|
| Q2 | Holdout reserve policy | **Policy A**: whole-league/lineage-component reserve plus a chronological split (`docs/owner/LVA_OWNER_DECISIONS_2026-10-21.md` §5A) | Matches the owner's stated intent; it is the only split that tests generalization to unseen leagues and future trades |
| Q5 | Primary maturity reading | Point-in-time (the preregistration default) | Avoids crediting a league with seasons completed after the trade |
| SK | Manager side-key secret custody | Provision a box-local secret (never in the repo), or accept the census's in-memory join for research only | Without manager keys, lineage leakage cannot be measured |
| C | Authorize the pinned read-only lineage census box command | Approve | It yields the real sample-size shortfall the power study needs |
| KTC | Treat KTC trade rows as in-sample for every validation, and as training data only with a declared correlation with `ktcTradesSfTep` | Approve (already the code's posture) | Prevents double counting the evidence the board already votes |
| PG | Turn on `pick_class_tether_guard` (top-10 #3, PR #2296; evidence `docs/picks/PICK_CLASS_GUARD_EVIDENCE_2026-11-21.md`) | **Keep OFF for now.** Decide together with PB | ON fixes the class error: no 2026 rookie prices a 2027 slot. It moves all 72 2027 slots: −8.7% in sum, max +43.5%, no non-pick row moves. Rounds 1–4 would then rest on one provider, IDP Trade Calculator's 2027 slot board: its pick rows have been byte-identical for 41 days, its board is steeper than both markets' tiers, and the result is a 2027/2028 fourth-round inversion against the vendors' own tiers |
| PB | Pricing basis for a slotted class whose rookies are not yet known | Price those slots at **TIER grade from both markets** (the C1-U6-D2 unslotted-class treatment), then turn PG on | Gives a two-market price instead of one stale vendor. It is a methodology change, because it would suppress IDPTC's published slots as that year's evidence, so it needs its own owner decision and a separate implementation |

## Deliverable B — Top 10 ranked improvements

Scores are decision quality /30, accuracy /20, usefulness /15, improvement over existing /15, feasibility /10 and
differentiation /10. Complexity and risk are listed separately.

| Rank | Improvement | Existing state | Score | Complexity | Expected benefit |
|---|---|---|---|---|---|
| 1 | **Forward validation scoreboard**: the served board vs later market prices (30/90/365 days) and realized points, by source, position and pick | No test of the served board against later prices or dynasty outcomes. The 2025 adjusted-board backtest is ρ .56 vs market. The Hill independent-validation registry is empty | **26+17+11+13+6+9 = 82** | Medium-high / low risk (evaluation only) | The first measure of whether our values beat the market. Unblocks CTM-5, Hill gate 7 and BDVM claims. Proves or disproves our edge |
| 2 | **Composed Team Advisor plan** built from existing owners: posture → ranked buy / sell-high / pick / aging actions, each with evidence and uncertainty | Pieces exist (roster intelligence, gameplan, Team Strength/Weakness, terminal signals); no composed plan. Terminal Buy/Sell is a roster-blind momentum rule table (`frontend/lib/signal-engine.js`) | **26+14+15+13+5+9 = 82** | Large / medium | Directly answers "what should I do next". Ships behind a default-OFF flag; rule thresholds are owner-reviewed |
| 3 | **2027 slot-pick class guard**: tether picks only to rookies of the same draft class | **Defect:** `_anchor_current_year_picks_to_rookies` (`src/api/data_contract.py:10572`) maps 2027 slots onto the drafted 2026 class (1.01 = 7121 from Jeremiyah Love vs KTC 2027 Early 1st 6584; 72 picks). Breaks the "never map one rookie class onto another" rule | **24+18+12+13+9+4 = 80** | Small / medium (moves 72 canonical pick values) | Correct pick prices in every trade, finder and draft-capital consumer. Flag default OFF plus measured board diff, with **activation owner-gated** |
| 4 | **Trade → title-odds delta** with an interval and a significance flag | `playoff_sim.simulate_trade_impact` (`src/ros/playoff_sim.py:2303`) and `league_intel/twin.py` are built with no production caller | **24+14+14+13+6+9 = 80** | Medium-large / medium | Ties trades to the contender question. Behind a flag, with uncalibrated-odds disclosure |
| 5 | **Server-composed "This week" panel** on the signed-in home: weak spots, top trade targets, best Perfect Waivers move, roster freshness, draft capital, league-mate moves | Home is the terminal; strengths, targets, waivers and freshness are disconnected; no command endpoint | **25+15+13+12+6+7 = 78** | Medium-large / low (one panel on existing components; no redesign) | One place to act each week |
| 6 | **Waiver correctness**: protections on the greedy add/drop lists and roster freshness on waiver payloads | **Defect B1:** `/api/roster/intelligence?droppability=1` (`server.py:10565`) never resolves trade protections, so `/waivers` can propose dropping a protected player while Perfect Waivers refuses. **B3:** `rosterSource` carries no stale flag | **24+19+11+10+9+4 = 77** | Small / low | Realistic moves; no contradictions on one page |
| 7 | **Chase Trade Market completion to a trustworthy shadow** (Deliverable A next steps) | Pipeline deployed; no estimator, maturity, board or owner decisions; perishable memory risk | **23+15+9+13+6+10 = 76** | Large / medium (ops) | Independent market evidence once the data supports it. Ops guard protects the deployed pipeline now |
| 8 | **Rookie source coverage and freshness** on `/draft` and `/api/draft-capital` | **Defect C1:** `_our_rookie_pool` (`server.py:13600`) reports stale vendors only for KTC/IDPTC; a KTC-only rookie looks fully supported | **22+18+11+11+8+6 = 76** | Small-medium / low | Honest uncertainty for rookie bids and auctions |
| 9 | **IDP evidence independence** (shadow): measure idpTradeCalc / IDP Show ancestry and the single IDP level anchor; prepare a lineage-aware cap proposal | 4 IDP voters, all on the idpTradeCalc ladder. idpTradeCalc + IDP Show carry 56% of IDP weight with Spearman .998. 0 of 429 IDP rows reach "high" confidence | **20+14+10+11+6+7 = 68** | Medium / medium (any cap is owner-reserved) | IDP is a competitive edge; this shows whether its consensus is real |
| 10 | **Trade-context correctness**: fix the inverted sell-high edge, retire the undeclared median-split `team-phase.js` for the canonical posture, and replace the years-of-experience strategy proxy | **Defects:** `suggestions.py:462` fires "sell before the market corrects down" when the user *overpays* (and the edge feeds ranking). Three conflicting contender/rebuilder classifiers. `_strategy_for_player` labels by experience | **18+15+9+10+8+3 = 63** | Small / low-medium (public posture labels are owner-reviewed) | Consistent, correct trade context everywhere |

**Where Chase Trade Market ranks, and why not higher:** seventh, at 76. The investment is real and the pipeline is
sound, but today it cannot improve a single decision:
- **No independent evidence at the needed scale.** KTC rows are in-sample with a source that already votes. The Sleeper
  lane is thin and best-ball-blind. Exact-format evidence is a single trade.
- **No real-data estimator.**
- **The governance prerequisites are owner decisions:** Q2, Q5, the side key and the frozen preregistration.

It ranks above items 8–10 because of its long-term differentiation and the perishable memory risk, which is scheduled
first regardless of rank. It would rise sharply once a Sleeper-observed, cohort-A training set of adequate size exists
and the forward scoreboard (#1) can validate it.

**Departures from the original candidate list:**
- Three repairs were promoted (the pick-class guard, waiver protections, trade-context correctness).
- The forward scoreboard became #1, because no other improvement can be shown to help without it.
- Sleeper/multi-league, Manager Scout and championship probability did not make the ten:
  - **Sleeper/multi-league:** sound for `dynasty_main`. The second league's missing private tools are out of owner scope
    (2026-10-18 scope correction).
  - **Manager Scout:** counts-only by owner rule; low headroom without a pooling method.
  - **Championship probability:** the odds display is disciplined; the double-count fix is owner-held after failing gate G4.
- The canonical valuation engine is covered by items 1, 3 and 9.

**Out of scope or owner-reserved, recorded not acted on:**
- Activating `forced_drop_cheapest_legal`.
- Activating `playoff_ros_counted_once`.
- The `brisket_trade_advisor` launch.
- DLF IDP voting.
- `source_freshness_schedule_v2`.
- The package model.
- `fairness_bands_v2`.
- Recommendation rule tables.
- Any source weight or voting change.

## Other confirmed findings (not in the ten)

**Valuation (stale and correlated sources):**
- A stale sole voter still publishes a full value. Weights renormalize, so 48 slot picks rest on idpTradeCalc alone at
  applied weight .0388.
- `yahooBoone` votes at .997 with a 37-day-old board; the schedule that would zero it is owner-held.
- `sourceVotingStatus` shows source-level weights, so influence is overstated: fantasyProsFitzmaurice is shown at 1.0
  against an applied .51.
- idpShowCombined is a vendor-declared aggregate and still votes.
- Draft Sharks ranks RBs a median 79 places below the other voters (an uncorrected positional bias).
- The Hill masters were last fit 2026-07-29.
- The BDVM proxy tier measured a negative within-position correlation with the market (−0.27, weeks 1–6, n = 651), so
  the Fund-gap column carries that caveat.

**Trade / posture:**
- Contender/rebuilder context often changes nothing in the offseason: no horizon input reaches trade analysis. Changing
  the rule table is owner-reserved.
- The served `leaning` field contradicts the headline (served, not rendered).
- Insider leads use an even-split flex need.
- The posture "NN% leaning" is shown without the uncalibrated-odds note.

**League / draft / hub:**
- Only the default league's contract is loaded, so the second league's private tools 503 (out of owner scope).
- Roster freshness is not shown on any page.
- There is no Next bridge route for `/api/waiver/faab-recommend` in dev.
- Four docstrings are stale.
- The rookie-pick anchor uses the default league's team count.

**CTM data:**
- Sharp's "≥2 seasons" gate counts `"0"` (`league_filter.py:85`).
- In season, the Sleeper lane reads only the current week.
- No scheduled builder for the own-league acquisition store.

## Implementation sequence (first batch)

Small, reviewable PRs on the existing owners; non-voting; nothing activates:

- **A1:** CTM ops guard. Streamed ledger persist and a stale-report alert (#7, perishable).
- **A2:** CTM minimal maturity slice from #1852 on current main, with the league-age fix and the maturity resolver wired
  into the ledger report (#7).
- **A3:** read-only aggregate workflow publishing the daily ledger report and KTC archive stats (#7, Deliverable A
  current counts).
- **B1:** 2027 slot-pick class guard behind a default-OFF flag, with the measured board diff and an owner decision (#3).
- **D1:** waiver protections on the greedy lists, plus a roster-freshness stamp (#6).
- **C1:** sell-high sign fix (#10).
- **D2:** rookie source coverage line (#8).
- **V1:** forward validation scoreboard over the committed export archive (#1). This is research tooling and changes
  nothing served.

Progress, PRs and production state for each are recorded in `docs/EXECUTION_PLAN.md` (2026-11-21 section) and in each PR.
