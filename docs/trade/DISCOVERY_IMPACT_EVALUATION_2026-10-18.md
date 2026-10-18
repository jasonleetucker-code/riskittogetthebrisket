# Trade discovery — Most Impactful evaluation (2026-10-18)

**Owner directive:** 2026-10-18, "Trade Finder meaningful discovery" (`docs/OWNER_REQUESTED_TODO.md`,
"Added 2026-10-18"). **Status of the ordering:** `PRIOR_UNVALIDATED`
(`config/trade/discovery_impact_prior.json`). This document is the representative-trade evaluation the
directive requires before the declared prior ships; it is not a validation. No validation target exists yet.

**Board:** `dynasty_main`, newest complete archived scrape `dynasty_export_20261018_002736.zip`
(`tests/archive_fixtures.newest_complete_raw_payload()`), built read-only by
`src.api.data_contract.build_api_data_contract`. **Owner evidence:** `owner_arbitrage_capture_2026-10-18.pdf`,
a 27-page capture of the live `/arbitrage` page on the same day. It is referenced by name and not committed.

## 1. What changed, in one paragraph

Every discovery view (Golden Upgrades, Package Scan, Best Offer by Opponent, and in Batch 2 the Package
Builder) now takes one shared `discovery` request (`src/trade/discovery.py`).

* **Target Quality** (Top 100 / 250 / 500 / All, default Top 250) uses the canonical overall rank.
* **Players to target** is Offense, Defense (IDP) or Both, mapped through `POSITION_ALIASES` and the
  lineup owner's slot eligibility.
* **Sort** is Most Impactful by default, with Largest Value Gain, Highest % Edge and Highest-Ranked
  Incoming as alternatives.

Quality is enforced per asset during enumeration through the substrate's new `receive_anchor`: at least one
incoming player must qualify. Players to target narrows the incoming pool before enumeration. No engine's
qualification rule, no canonical value and no Value Adjustment changed. Gains are the calculator's own
`analyze_trade.equity_verdict`, which is `rankDerivedValue` plus the active package model.

## 2. The declared prior

`impact = evidenceMultiplier × (0.35·incomingImportance + 0.30·edge + 0.20·rosterFit +
0.15·counterpartyPlausibility) − 0.15·forcedDropCost`

| factor | source (existing canonical owner) | why it is counted once |
|---|---|---|
| incomingImportance | best incoming PLAYER's `rankDerivedValue` / 9999 | Rank is the same evidence, since value is the Hill curve of the rank, so it is not a second term. Using the max single player means filler cannot raise it. |
| edge | √(abs-gain saturation × %-gain saturation) of the VA-adjusted canonical gap (`equity_verdict`) | Absolute and percentage gain are correlated readings of one gain, so they form ONE factor. |
| rosterFit | canonical lineup solver delta (`best_offers.lineup_delta_from_bundle`, `src/ros/lineup.py`), else the Team Weakness need share | Lineup improvement and filling a rated need are the same evidence, so only one is ever used. |
| counterpartyPlausibility | each engine's own acceptance reading: Golden's market inversion × its exploit decay; the finder's opponent market appeal through the Best Offers comfort plateau; Best Offers' `externalComfort` | Each engine already owns its plausibility rule, so this term only normalizes it. |
| evidenceMultiplier | B11 `confidenceBucket` of the best incoming player (`src/api/confidence.py`) | There is no second confidence model. |
| forcedDropCost | `roster_capacity.forced_drop_cost` (cost) | It is the same cost the legacy order charges. |

An unknown benefit is imputed as `min(worst known, 0)` and an unknown cost as the worst known cost within
the same ranked set. An unknown factor is never free.

## 3. Before / after — the owner capture (Player-level table)

**Before.** The capture shows the default `/arbitrage` page:

* The Player-level table renders FIRST: 301 buy rows across ~26 printed pages before any trade tool.
* The defaults are Buy arbitrage, all players, 5%+ edge, sorted by percentage edge.
* The top rows are deep IDP players: Trevin Wallace LB #385 +128%, Will Johnson DB #574 +90%, Bryan Bresee
  DL #568, Derek Stingley DB #639 and Nate Wiggins DB #536.
* Cedric Gray LB #90 (+2,320 absolute), CJ Allen LB #114 (+1,691) and Jamien Sherwood LB #130 (+1,451)
  appear only incidentally.

Two more failure modes are visible in the capture:

* The "Our rank" column printed display ordinals (850–970) for rows past the canonical ranked cap. Those
  numbers are not canonical ranks.
* The Signal column clipped at the panel edge.

**After** (`frontend/__tests__/arbitrage-board-regression.test.js`, on the same day's real rows):

* The table lives below the tools in a collapsed **Player-level market research** section, shows 50 rows
  before "Show all", and scrolls horizontally only inside its own region.
* Its defaults are Top 250 and Largest absolute opportunity. Its rank column is the backend
  `canonicalConsensusRank`, and "unranked" is never an ordinal.
* None of the five deep IDP players above appears. Gray, Allen and Sherwood are in the top 10.
* The legacy order, Trevin Wallace first, is still reachable as an explicit opt-in: All Players plus Highest
  % edge.

## 4. Before / after — Golden Upgrades (all 12 `dynasty_main` teams, lineup on)

Legacy = no `discovery` object (the previous order: weaker edge, exploit-decayed). Default = Top 250 / Both /
Most Impactful. `#` is the canonical overall rank.

| team | legacy #1 | default #1 |
|---|---|---|
| Blaine | Payton Wilson #306 → Zaire Franklin #257 | Terrel Bernard #252 → **Cedric Gray #89** (+1,828) |
| Brent | T.J. Watt #242 → Jalen Carter #203 | Nate Landman #284 → Daiyan Henley #170 (+885) |
| Collin | Foyesade Oluokun #180 → CJ Allen #114 | Anthony Hill #214 → Zack Baun #144 (+708) |
| Ed | Bryce Young #55 → Jalen Hurts #35 | same (+785) |
| Eric | Devin Bush #154 → CJ Allen #114 | **Kenneth Walker #21 → Ashton Jeanty #14** (+674) |
| Jason | Blake Cashman #152 → CJ Allen #114 | Barrett Carter #194 → **Cedric Gray #89** (+1,452) |
| Joey | Josiah Trotter #250 → Foyesade Oluokun #180 | Josiah Trotter #250 → Zack Baun #144 (+963) |
| John | CJ Allen #114 → Cedric Gray #89 | Denzel Boston #94 → Rashee Rice #81 (+370) |
| Kich | Roquan Smith #148 → Quay Walker #113 | **Derrick Henry #71 → Omarion Hampton #54** (+573) |
| MaKayla | Quay Walker #113 → Cedric Gray #89 | Jacob Rodriguez #77 → **Jack Campbell #53** (+740) |
| Roy | Alex Highsmith #239 → Jared Verse #215 | same (+172) |
| Ty | **Budda Baker #420 → Chamarri Conner #340** | Bucky Irving #65 → **Omarion Hampton #54** (+422) |

What the table shows:

* Every default result brings back a Top 250 player. This is pinned on the real board by
  `tests/trade/test_trade_discovery_live_board.py`.
* Ty's legacy list was led by a rank-340 bench swap; its default leads with a top-60 RB.
* Deep pairs such as Jake Golday #362 → T.J. Edwards #297 or Quincy Williams #299 (Jason's legacy rows 6–10)
  no longer appear by default.
* The Golden Upgrade definition itself is unchanged. With All Players + Both the candidate set equals the
  legacy set exactly (`test_golden_eligibility_definition_is_unchanged_by_the_filters`).

## 5. Before / after — Package Scan (Jason, equal-count, asset-only)

| | #1 | #2–5 |
|---|---|---|
| legacy (arbitrage score) | Jake Golday #362 → Cedric Gray #89 | four more single swaps into Cedric Gray (Abdul Carter, Dallas Turner, Andrew Van Ginkel, Devon Witherspoon) |
| default (Most Impactful) | George Pickens #36 + Dallas Turner #112 → **Caleb Williams #9** + Jamien Sherwood #132 (adjusted +2,538) | Amon-Ra St. Brown #10 + Cedric Gray, CeeDee Lamb #13 + Sherwood, … |

The legacy list was not filler, but it was five variants of one 1-for-1 target. The default leads with
packages that bring back a top-15 player at a large VA-adjusted gain.

Two caveats apply:

1. Many top results are variants of the same incoming pair with a different second outgoing piece.
2. Every result still passes the finder's own gates: plausibility, opponent appeal, `boardDelta > 0`.

## 6. Best Offer by Opponent (Jason, asset-only)

| | first cards |
|---|---|
| legacy | Oronde Gadsden → Quay Walker #113; George Pickens → Sam LaPorta #43 + Talanoa Hufanga #376; Laiatu Latu → RJ Harvey #165; Eli Stowers → Kaden Elliss #277 + T.J. Edwards #297 |
| default | Brock Bowers → Caleb Williams #9 + Luther Burden #64 (+2,790); Brock Bowers → Amon-Ra St. Brown #10 + Omarion Hampton #54; Brock Bowers → Ja'Marr Chase #7 + DJ Moore #126; Justin Jefferson → Jayden Daniels #19 + Devin Lloyd #116 |

**Known effect, reported rather than hidden.** Under Most Impactful the same outgoing star (Brock Bowers)
headlines several cards, because each card is an independent best offer. The existing
`outgoingAlsoOfferedTo` / `outgoingConcentration` fields already say so on every affected card. Choosing
diverse offers across cards would be a new methodology and is not part of this prior.

## 7. Performance (dynasty_main-shaped data, same machine, contended)

| surface | legacy | default |
|---|---|---|
| Golden Upgrades (1 team) | 0.24 s | 0.08–0.13 s (target pool narrowed before enumeration) |
| Package Scan (Jason, all opponents) | 10.9–11.9 s | 11.3–12.3 s (lineup head included) |
| Best Offers (Jason, asset-only) | 11.6 s | 12.4 s |

Uncontended single runs measured 7.3–7.7 s (legacy) against 8.4 s (default) for the scan. The anchor rejects
~18.7k receive sides before scoring, but the 2-for-2 pool limit already keeps most qualifying players.
Timings stay inside the existing route budget, with no new timeout.

## 8. What would validate or replace this prior

The prior is evaluated, not validated. A replacement needs an outcome target:

* trades actually accepted in `dynasty_main` versus offered, from the AL-P5 decision receipts; or
* the realized value change of executed trades over a fixed horizon.

The prior must then be compared against the legacy orders on held-out trades. Until that exists, every
weight above is a declared prior, editable only in the config.
