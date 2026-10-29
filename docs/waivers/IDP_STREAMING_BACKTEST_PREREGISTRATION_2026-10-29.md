# IDP weekly streaming backtest — PREREGISTRATION (2026-10-29)

**Status:** preregistered BEFORE any result was computed.  Committed alone, ahead of
the harness and the results document, so every choice below can be checked against
what was decided before the numbers existed.  Any later deviation is listed in the
results document under "Deviations from preregistration", never edited in here.

**Authority:** research / shadow only.  Nothing here changes a value, a ranking, a
FAAB recommendation or any live route.  The harness (`src/waivers/streaming_backtest.py`)
is isolated: no production module may import it (pinned by
`tests/waivers/test_streaming_backtest.py`).

**Question.**  In `dynasty_main` (best ball; custom IDP scoring card), one manager —
called **manager B** here and in every committed artifact — keeps several roster spots
churning individual defenders week to week.  *Does that streaming gain realized
starting-lineup points over simply holding, and how does it compare with simple,
explicit streaming rules?*  Measured, not assumed.

## 1. Data and seasons

| item | decision |
|---|---|
| league | the `dynasty_main` Sleeper league chain, walked through `previous_league_id` by `src/public_league/sleeper_client.walk_league_chain` |
| seasons | **2026** regular-season weeks that are COMPLETE when the run starts (the run reads `last_scored_leg`; at preregistration time that is weeks 1–7; week 8 is in progress and excluded) and **2025** regular season (weeks 1 to `playoff_week_start − 1`) |
| excluded seasons | 2024 and earlier: a different IDP slot structure (1 DL / 1 LB / 1 DB + IDP_FLEX), so a streaming effect there is not the same quantity. Out of scope, not "no effect" |
| per-season rules | each season is scored with ITS OWN league object: its own scoring card, its own `roster_positions`, its own team count. Today's card is never applied to 2025 |
| decision weeks | weeks 2 … last; week 1's roster is the starting state (pre-season/draft moves are not "streaming") |
| rostered sets, ground truth | `/league/{id}/matchups/{week}` `players` per roster per week |
| transactions | `/league/{id}/transactions/{week}` for weeks 1 … 18 (all types: waiver, free_agent, trade, commissioner), `complete` only |
| realized points | Sleeper weekly stat lines (`src/league_comparison/sleeper_stats.fetch_week_stats_response`) rescored under the season's card by `src/league_intel/scorer.score_stat_line`. Cross-checked against the host's own `players_points` on every rostered player-week |
| player who recorded no stat line in a complete weekly payload | realized **0.0** — the host's own award (verified against `players_points`, not assumed). A whole-week payload that is missing is an ERROR, never a week of zeros |
| positions | Sleeper player dump (`fetch_nfl_players`): `position` (DL / LB / DB) decides the swap group; `fantasy_positions` decides lineup-slot eligibility. The dump is today's, so a mid-season position change is a known, declared approximation |
| lineup | best ball: the starting lineup is the OPTIMAL lineup on realized points, computed by the canonical exact solver `src/ros/lineup.py::solve_optimal_assignment(objective="realized_points")` over the season's own slots. The harness reproduces the host's awarded team totals before trusting itself (reported) |
| pregame projections | Sleeper weekly projections (`src/ros/sleeper_weekly_projections`, provider company `rotowire`), fetched TODAY for past weeks and rescored under the season card. **NOT point-in-time verified**: the provider stamps `updated_at` after games (measured on a week-3 2026 sample: every row updated 2026-09-29, after week 3 kicked off). The run reports, per week, the share of rows whose `updated_at` is after kickoff. Game Day's pregame archive (`data/game_day/live/…/pregame_projections.json.gz`) is the point-in-time source but exists on the production box only; it is read when present and its absence is reported |
| dynasty value at decision time | `src/history` (`value_known_before`, instant = decision cutoff, `knowledge_cutoff` = decision cutoff). History floor **2026-07-14**: every 2025 decision is `before_history_boundary` → UNAVAILABLE, never today's value. The canonical-board lane is a production-only store; where it is absent the harness reports it as unavailable and reports, under its own name, the vendor-published IDP Trade Calculator value (`source_value` lane, `idpTradeCalc`) — a different, explicitly named quantity, never relabelled as canonical value |
| kickoff / decision cutoff | the earliest kickoff of week *w* (nflverse schedule through `src/nfl_data/ingest.fetch_schedules`, ET → UTC). Fallback when unavailable: the Sleeper schedule's earliest game DATE at 00:00 UTC (earlier than any kickoff, so conservative) |

## 2. Leakage policy (no hindsight)

A week-*w* decision may read only:

* realized stat lines of weeks **< w** (all final before week *w* kicks off);
* projections for week *w* (labelled not point-in-time verified, above);
* dynasty values whose observation instant AND record instant are at or before the
  week-*w* cutoff;
* rosters as of the end of week *w − 1*.

Realized points of week *w* or later are read ONLY to SCORE a decision, never to make
one.  The harness enforces this structurally (a decision context is built by one
function that filters every timed input by the cutoff) and a test injects post-cutoff
data and asserts no decision changes.

**One declared exception — availability.**  The primary pool excludes any defender
another team actually rostered in week *w* (see §4).  That reads other managers'
week-*w* roster state, which is a RESTRICTION on what the rule may take (it can only
remove candidates and never reveals a realized score); it is disclosed and run both
ways.

## 3. Unit of analysis and scenarios

For every team (anonymized as an index; manager B by label) and every decision week,
each scenario defines the team's set of rostered defenders.  Offense is identical in
every scenario, and no lineup slot in 2025 or 2026 accepts both an offensive player and
a defender (asserted by the harness), so **the scenario difference in realized
starting-lineup points equals the difference in the optimal IDP sub-lineup**.

Trades and commissioner moves that change a team's defenders are applied in EVERY
scenario (they are not streaming).  Waiver and free-agent adds/drops of defenders are
the manager's streaming and are applied only in baseline 8.

| # | baseline | definition |
|---|---|---|
| 1 | **no streaming (hold)** | week-1 defenders, plus/minus defenders moved by trades/commissioner actions; no waiver or free-agent defender move |
| 2 | **previous-week points** | each week, swap rostered defenders for available ones by realized league points in week *w − 1* |
| 3 | **rolling recent production** | same, by mean realized league points over the last 3 regular-season weeks before *w* in which the player recorded a stat line; needs ≥ 2 such weeks, else unknown |
| 4 | **single projection provider** | same, by the week-*w* Sleeper/RotoWire projection rescored under the season card |
| 5 | **independent-source consensus** | runs only if ≥ 2 independent weekly IDP projection families are available for the backtest weeks. At preregistration only one is available historically → declared **N/A**, never a single source relabelled as consensus |
| 6 | **release lowest-valued dynasty player** | add by the week-*w* projection (as 4); the released defender is the LOWEST point-in-time dynasty value at that position among rostered defenders projected below the add.  Unpriced defenders (no observed value) are released first, a declared tier, never "value 0".  Runs only where a point-in-time value exists (2026); 2025 is **N/A** (before the history boundary) |
| 7 | **full dynasty-safe optimizer** | placeholder — W4's solver, called through the interface in §6. Reported as NOT RUN until it lands |
| 8 | **manager's actual behavior** | the actual week-by-week defenders from the matchup rosters |

**Swap rule (2, 3, 4, 6).**  Swaps are 1-for-1 within a swap group (DL / LB / DB by
`position`), so roster size and lineup shape are preserved.  Up to **S = 3** swaps per
week (primary; sensitivity S = 1 and S = 5).  Greedy: repeatedly take the
(drop, add) pair with the largest metric improvement; a swap happens only on a STRICT
improvement (> 0).  A player whose metric is unknown is neither added nor dropped
(unknown is not zero).  A released defender returns to the pool.

## 4. Pool

The waiver pool for week *w* is every NFL defender (dump position DL / LB / DB) who is
not on another team's roster at the end of week *w − 1* and is not already in the
scenario's own set.

* **Primary (contention-masked):** additionally excludes defenders another team rostered
  in week *w*.  What remains cleared waivers unclaimed, so taking it is a $0 free-agent
  add — the rule's FAAB cost is genuinely $0.
* **Sensitivity (unmasked):** no week-*w* exclusion — an UPPER BOUND, because the rule
  would have had to win contested FAAB claims it never bid on.  FAAB cost is reported as
  UNKNOWN for contested adds.

## 5. Metrics

* **Primary endpoint:** manager B, baseline 8 − baseline 1, realized optimal IDP lineup
  points per decision week, pooled over 2025 and 2026 decision weeks.
* For every baseline and team: Δ realized IDP lineup points vs baseline 1 per team-week.
* FAAB spent (manager B and every team: sum of winning `waiver_bid` on defender adds).
* Transaction count / churn: defender adds per team-week; distinct defender spots
  churned; league average vs manager B.
* Dynasty value released / acquired at decision time (2026 only; named quantity per §1).
* Subsequent performance of dropped players: their realized points over the following
  1 and 3 weeks against the player added in their place.
* **False-positive move:** a defender add whose realized points over the following
  3 weeks (or fewer, if the season ends) are below those of the defender released for
  it in the same period.
* Whether added defenders made the optimal lineup in weeks they were rostered.
* Projection accuracy (provider of baseline 4): MAE, RMSE and mean bias (projected −
  realized) by DL / LB / DB over player-weeks with a recorded stat line.

## 6. Interface for baseline 7 (W4's solver)

The harness calls any policy through one protocol and enforces the rules itself:

```python
class StreamingPolicy(Protocol):
    name: str
    def decide(self, ctx: DecisionContext) -> Sequence[Swap]: ...
```

`DecisionContext` (frozen) carries: `season`, `week`, `cutoff_utc`, `team_index`,
`idp_roster` (the scenario's defender ids), `pool` (available defender ids),
`positions` / `eligibility` (player id → swap group / fantasy positions),
`idp_slots` (the season's IDP starter slots), `realized_before` (player id → {week:
points} for weeks < w only), `projection` (player id → week-w projected points,
labelled `projection_point_in_time_verified=False`), `dynasty_value` (player id → value
known before the cutoff, or absent), `max_swaps`.  `Swap = (drop_id, add_id,
faab_bid | None)`.  The harness rejects (and counts) any swap whose drop is not
rostered, whose add is not in the pool, that is not 1-for-1, or that exceeds
`max_swaps`.  The policy never sees week-*w* realized points.

## 7. Statistics and sample-size rules

* Bootstrap 95% percentile CIs, 10,000 resamples, seed `20261029`.  Manager B:
  resample decision weeks.  League-wide: cluster bootstrap over teams (team-season is
  the cluster).
* **Verdicts:** "gains" only if the CI lower bound > 0; "loses" only if the upper bound
  < 0; otherwise "no detectable effect".  Never a point estimate alone.
* **Minimum samples:** manager B needs ≥ 6 decision weeks (pooled) for a CI; league
  aggregates need ≥ 6 team-seasons; projection accuracy needs ≥ 100 player-weeks per
  position.  Below the minimum the cell is reported **INSUFFICIENT** with its n, never
  as a number with a CI.
* Every reported number carries its n.

## 8. Privacy

Committed artifacts carry no Sleeper league / user / roster ids and no manager or team
names; teams are anonymous indexes and the studied manager is "manager B".  Named
detail and per-transaction lists go to the gitignored `data/research/idp_streaming/`.
Raw Sleeper responses are cached there too (read-only public API).
