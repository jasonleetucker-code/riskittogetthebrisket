# The Game Day week resolver — `src/ros/game_day_week.py`

**Why it exists.** `src/ros/game_day_sim.py` (W1-18..W1-24, merged #1244) is
the canonical league-aware current-week simulation, and it is deliberately
pure: `LeagueWeekRules` + `TeamWeek`s + an opponent map in, two probabilities
out. It knows nothing about Sleeper. Measured on `main` 2026-09-05, a grep for
`game_day_sim` across `src/`, `scripts/` and `server.py` returned **zero
matches** — a canonical owner with no caller, the same shape
`game_day_archive` was in before `game_day_capture` became its resolver.

This module is that missing half: already-fetched Sleeper payloads plus an
estimate index in, simulation inputs out.

## It is not a third owner of the roster

| concern | owner |
|---|---|
| player enumeration, position resolution, IR/taxi subtraction | `src/ros/game_day_capture.py` |
| starter slots, slot eligibility, optimal assignment | `src/ros/lineup.py` |
| per-player weekly distribution, both probabilities | `src/ros/game_day_sim.py` |
| projection estimates | `src/ros/projection_ensemble.py` |
| **per-player STATE for one week** | this module |

The non-active (IR / taxi) subtraction was `game_day_capture`'s private
`_NON_ACTIVE_ROSTER_BUCKETS` loop; it is now
`game_day_capture.non_active_player_ids()` and **both** callers use it. Two
answers to "is this player available" would be two definitions of the roster.

The one genuinely new thing is the **state axis**, and it is new because the
archive has no use for it: the archive is pregame-only by construction, while
the simulation distinguishes `completed` / `in_progress` / `not_started` /
`inactive` / `unknown` and scores each differently.

## Scheduled, live, and final resolution

`resolve_pregame_week` remains the pregame adapter and still refuses a begun
week. `resolve_scoring_week` reuses it for roster enumeration, projections,
IR/taxi subtraction, positions, and rules, then overlays Sleeper actual scores
and typed `GameEvidence`. Evidence comes from two places, merged per NFL team
by `merge_game_evidence` (observed wins):

* **observed** — `observed_game_evidence` turns one ESPN scoreboard
  observation (`src/nfl_data/live_game_state.py`, flag
  `game_day_live_game_state`) into per-team evidence carrying the observed
  `phase`, `period`, `clock_seconds` and `remaining_fraction`, joined to our
  schedule by normalized team codes (`WSH`→`WAS`, `LA`→`LAR`) plus a kickoff
  within 36 h. A scoreboard for another season/week/season type is refused
  whole. `in_progress` is a real state here.
* **schedule** — the nflverse cache establishes scheduled and completed
  games only. A passed kickoff without a result or an observation remains
  `unknown`; wall time does not prove that a game started.

### In-progress remaining production: observed clock first (reconciliation)

**Owner decision 2026-09-09** chose a PRORATED remaining — "remaining = 0 for
every in-progress player" was rejected — and, with no live clock wired,
measured progress as wall time since kickoff over one fixed assumed duration
(`_ASSUMED_GAME_DURATION_SECONDS`, ~3h15m).

**Owner contract 2026-09-24** ("observe actual quarter/clock/status; elapsed
wall time since kickoff is not sufficient") keeps the proration and changes
what it is prorated BY. It does not silently change the 09-09 meaning; it
demotes the wall-time measure to a labelled, degraded fallback:

| `remainingBasis` | when | remaining |
|---|---|---|
| `pregame_full_baseline` | game not started (observed `SCHEDULED`, or schedule says future) | pregame provider baseline |
| `observed_clock` | observed in progress / end of period / halftime | baseline × `regulation_fraction_remaining` (observed quarter + clock) |
| `wall_time_fallback` | `in_progress` evidence with NO observed phase (the legacy seam) | baseline × (1 − elapsed / assumed duration) |
| `game_over` | completed, or host-declared `Out` | 0.0 |
| — (withheld) | see below | `None`, reason in `progress_unavailable_reasons` |

Withheld with a named reason, never invented: `overtime` (period > 4),
`overtime_possible` (end of regulation with the score tied or unstated),
`delayed`, `postponed`, `canceled`, `unknown_status:*`, `stale_live_state`
(observation older than `LIVE_STATE_MAX_AGE_SECONDS` = 180 s, i.e. three missed
60 s polls), `no_kickoff_evidence`, and `wall_time_exhausted_without_observed_final`
— the fallback can never finish a game by itself. The nflverse cache never
asserts `in_progress`, so with the live feed off (or failing) the fallback is
unreachable from the matchup endpoint: a begun game stays `unknown` and the
probability is withheld as `GAME_STATE_OR_SCORING_UNAVAILABLE`.

**The baseline is never reduced by actual points** — banked points and
remaining production are separate terms, so nothing is counted twice. This is
a simple observed-clock baseline, labelled as one: it knows nothing about
possession, score, injuries or usage, and nothing here claims otherwise.

Completed players and a host-declared `Out` get `remaining=0.0`, not `None`:
the game being over is real evidence nothing further is coming. Final state
requires completed game evidence for every team with a game and actual player
scoring.

### Weekly baselines (`src/ros/game_day_estimates.py`)

Each player's pregame baseline has ONE basis, published per player as
`projectionBasis`:

* `weekly:rotowire_via_sleeper` — the Sleeper weekly projection (RotoWire),
  rescored under this league's card by the exact scorer and locked at the
  player's kickoff (`lock_baseline_at_kickoff`: last observation fetched at or
  before kickoff). Flag `sleeper_weekly_projections`, DEFAULT OFF: the
  endpoint is a source candidate whose terms are UNVERIFIED (census
  `licensingStatus: UNVERIFIED`); activation is pending terms verification.
* `preseason_full_season_fallback` — the full-season ensemble's per-game
  average, used only when no locked weekly baseline exists. It is a FALLBACK
  and NOT a current-week forecast; the payload says so per player and in
  lineage, and never presents it as the weekly projection.

Joins are by Sleeper `player_id`; the name-keyed preseason ensemble resolves
name → id through the Sleeper player map and refuses a name two current NFL
players share. League-paid keys the provider does not project are published as
`uncoveredScoringKeys` (unknown, never zero). The first-down bonus
(`bonus_fd_<pos>`) is imputed from the canonical measured fit
(`first_down_rate.imputed_sleeper_first_down_bonus`) and carried separately as
OUR component (`imputedPoints` / `imputedScoringKeys`). The provider's
`pass_fd` / `rush_fd` / `rec_fd` are yards/10 on every measured row (677/677),
not first downs: they are never read as such, and a card that pays them refuses
the weekly line.

### The simulation's own outputs (`src/ros/game_day_sim.py`, model v4)

Per draw: banked points are kept, only remaining production is drawn, and the
exact lineup is re-solved on the final points — choice and sum both on the raw
points (`lineup.OBJECTIVE_REALIZED_POINTS`), so a negative score is never
seated over a 0.0. From the SAME draws: win %, beat-median %, per-player
`player_lineup_pct` (a completed player below 100 % is being displaced), and
per-NFL-game `game_leverage`:

> net_g = (team's final-lineup points from game g) − (opponent's, same game);
> leverage_g = P(win | net_g above its median) − P(win | net_g below its median),
> in percentage points. Games with nothing left to play carry no leverage.

`projected_mean` (published as `expectedFinalBestBall`) is the mean of the
optimized totals — deliberately distinct from `expectedLineup.projectedTotal`,
the lineup optimizing individual means implies. Remaining draws are floored at
0 (`PointsModel.draw_from_mean`): the per-position CV model has no basis for a
negative remainder; the floor adds a small upward bias on tiny remaining means.

## The NFL slate — a per-game object, not a fan-out of `GameEvidence`

`GameEvidence` is per-TEAM: `schedule_game_evidence` writes the same evidence
object under both a game's `home_team` and `away_team` keys, with no pairing
between them and no `game_id`. That is sufficient for "is this one team's game
live yet" but cannot answer "what is the week's real NFL schedule, in
chronological order" — nothing needed that question until the matchup NFL
slate (2026-09-09).

`NflGame` is the missing per-game shape, and `schedule_games(rows, *, season,
week, now)` builds the list: `game_id`, `home_team`, `away_team`, `kickoff_at`,
`state` (the same `not_started` / `in_progress` / `completed` / `unknown`
vocabulary as `GameEvidence`), `home_score`, `away_score`. Ordered by
`kickoff_at` ascending, with an unknown kickoff sorted **last** — never first,
since an unresolvable kickoff is not evidence of "earliest." Both functions
derive state and kickoff from the same private per-row helper
(`_row_game_state`) so they can never disagree about what one schedule row
means; `schedule_games` is a pure additive sibling and does not change
`schedule_game_evidence`'s existing per-team behavior.

`src/api/matchup_intel.py::build_matchup_intel` consumes it to stamp a new
`nflSlate` field: the complete real schedule for the week, with the
requesting matchup's two rosters' players (from `TeamWeek.players` — the full
active roster, bench included, already correctly resolved for pregame/live/
final by `resolve_scoring_week`) attached to the game matching their NFL team
(`side: "team" | "opponent"`). A player whose team has no game this week is a
real fact (`byeWeek`), not a silent drop; a player with no resolvable NFL team
on file is a data gap (`unattributed`, with a reason), never guessed into a
game. `scheduleState: "unavailable"` (with a reason) is stamped distinctly
from an empty `games` list when the schedule cache itself has nothing —
"missing" and "empty" must not read the same. `frontend/components/
GameDayPanel.jsx` renders this verbatim (materializer only): the complete
schedule in the order given, never re-sorted or filtered by relevance, with a
game carrying no relevant players collapsed to a compact row rather than
hidden.

## The three ways a player can be absent stay distinct

- **ineligible** — in the roster's `reserve` / `taxi` buckets. He cannot
  legally start, so he leaves the week entirely and is reported in
  `ineligible_player_ids`. Leaving him in the pool at a 0.0 draw would let him
  occupy a slot on a thin roster — a lineup the host would not award.
- **unpriced** — active and startable, but no projection source covers him.
  He enters as `state="unknown"`, which `game_day_sim._drawable` excludes and
  `unsimulable_player_ids` reports. **Never drawn as zero.**
- **priced** — `state="not_started"` with `projected_remaining` set to the
  per-game estimate. `points_scored` is `0.0`, which pregame is an observation
  (the games have not kicked off), not a gap.

`estimate_coverage` is published as **two numbers**, `(priced, active)`, rather
than a ratio, so "no projections at all" and "thin coverage" cannot read the
same. A league with no projection snapshot still resolves — every player comes
back `unknown` and a note says so — because "we cannot price this week" is a
better answer than a number built on nothing.

An unscheduled team gets `opponents[team] = None`, never an arbitrary
pairing, which `game_day_sim` turns into `UNSIMULABLE` rather than 50%. A
`matchup_id` holding one or three rosters is treated the same way. Every
resolved team gets an entry even when the matchup payload omits it, so an
absent key and a `None` value are not left for the simulator to tell apart.

## Proven against the live league

2026-09-05, `dynasty_main` (`1312006700437352448`), Week 1, unplayed:

```
slots: 21 (sleeper_roster_positions)
teams: 12   active players: 674   ineligible: 0 (taxiSize 0, nobody on IR)
opponents: 1↔4  2↔10  3↔12  5↔7  6↔9  8↔11
```

Those six pairings match Sleeper's `/matchups/1` exactly (independently
verified in `docs/season-launch/W1_10_WEEK1_MATCHUP_AUDIT_2026-09-05.md`).
Feeding the result to `simulate_league_week` with a synthetic estimate index —
`data/bdvm/projections/` is gitignored and lives only on the box, so the real
one is not present in a sandbox — produced coherent per-team probabilities
whose win% + tie% summed to **exactly 600.0** across 12 teams / 6 matchups.
The estimate index was labelled `SYNTHETIC:wiring-proof-only`; it proves the
wiring, not a forecast.

## Known limitations, named rather than papered over

* The observed-clock baseline scales a pregame projection by regulation time
  left; no possession, score, injury or usage modelling exists.
* Live acquisition in `matchup_intel` is an in-process interim memo until the
  shared background collector (U5): a restart after kickoff forgets pre-kickoff
  weekly observations, and those players fall back to the preseason basis
  (counted as `noPreKickoffObservation`).
* The simulation cache fingerprint includes live inputs, so it misses on every
  live poll; making live simulation cheap is the collector's job (U5).
* Sleeper `Out` is treated as definitively finished; less certain injury labels
  remain projections.

## Tests

`tests/ros/test_game_day_week.py` covers pregame plus deterministic live/final
fixtures. The tests pin that banked points survive, the legacy (no observed
clock) in-progress remainder takes the labelled wall-time fallback when kickoff
evidence is usable and reports
`progress_unavailable_player_ids` when it is not, completed and ruled-out
players get `remaining=0.0` (not `None`), completed scoring produces the
canonical final lineup, and a passed kickoff without a result remains unknown.
The pregame tests still cover what is not there: an unpriced player is `unknown` and reaches
`unsimulable_player_ids` (asserted through a real `simulate_league_week` call,
not just on the resolver's own output); an IR player leaves the week and is
**not** miscounted as merely unpriced; a begun week is refused on both the
team-score and player-score signals; no rosters and no starter slots are
refused; every team gets an opponents entry.

`schedule_games` is covered separately in the same test file: chronological
ordering including an unknown-kickoff row sorting last, state derivation
agreeing with `schedule_game_evidence` on the same rows, `LA`→`LAR`
normalization, and a row with no team code being dropped rather than
fabricated into a game. `tests/api/test_matchup_intel.py::NflSlateTests`
covers the `nflSlate` field end to end: games grouped by side, a bye-week
player reported rather than dropped, an unattributed player reported with a
reason, an unavailable schedule cache stamped distinctly from an empty one,
and games rendered in kickoff order regardless of fantasy relevance.
`frontend/__tests__/components/game-day-panel.test.jsx` pins the same
properties on the render side.

`tests/game_day/test_game_day_u4_correctness.py` pins the U4 mechanics on
synthetic inputs (negative vs zero lineup choice, FLEX / SUPER_FLEX displacement
of completed players, every observed status, the capped wall-time fallback, the
kickoff lock, first-down imputation, leverage). `tests/game_day/test_game_day_replay.py`
replays real 2026-09-25 captures (`tests/fixtures/game_day/replay/`) through the
whole matchup assembly and asserts banked points retained, remaining only for
unfinished players, one coherent simulation (every league draw puts exactly half
the teams above the median), and every withheld state named.
