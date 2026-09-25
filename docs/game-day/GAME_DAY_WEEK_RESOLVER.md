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
  before kickoff). Flag `sleeper_weekly_projections` (default ON since U5 —
  rollback `RISKIT_FEATURE_SLEEPER_WEEKLY_PROJECTIONS=0`; access is owner-attested — census `OWNER_ATTESTED_AUTHORIZED`, record
  `docs/game-day/SOURCE_ACCESS_EVIDENCE_2026-09-25.md`).
* `weekly:ensemble` — reserved for a player priced by two or more independent
  weekly provider FAMILIES. `WEEKLY_SOURCE_ADAPTERS` is the seam for further
  weekly sources (Fantasy Nerds, SportsDataIO, FantasyPros, DraftSharks — keyed
  APIs needing owner-configured credentials; none implemented). Independence
  is the census `providerFamily`: a same-family source gives no second vote
  (`sameFamilyDuplicates`), and cross-family combination is delegated to
  `projection_ensemble.combine_ensemble` (`equal_family_mean`).
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

## Shared live collector and generations (U5, `src/ros/game_day_live.py`)

Owner requirement (2026-09-24 escalation, §A.5): bounded shared background
collection and cached, versioned simulation generations — a live update never
needs a deployment, a scrape, or a simulation per viewer.

**Collector.** `scripts/run_game_day_live.py` under the
`dynasty-game-day-live` systemd timer (fires every minute; the tick decides
whether it is due, exit 2 otherwise). Cadence comes from OBSERVED game windows
(`decide_cadence`): 60 s while any game is live (a passed kickoff with no
observed final counts as live for 6 h), 180 s inside 90 min of a kickoff,
hourly otherwise, and the next tick is pulled forward to the near-kickoff
window and to each kickoff. A tick is bounded (`MAX_REQUESTS_PER_TICK` = 20;
one NFL-state, ESPN, live-stats, projections and players-DB request plus four
per league) and keeps a persisted per-source backoff, because the in-process
circuit breaker does not survive a oneshot run. A failed scoreboard read uses
the last good observation at its TRUE as-of, so the resolver marks it
`stale_live_state` rather than reading it as fresh.

**Weekly projections and the kickoff lock.** Fetched while any kickoff is
ahead (every 10 min inside 90 min of a kickoff, every 3 h otherwise, never
once every game has kicked off), with one fetch FORCED inside the final 10 min
before each kickoff. Every fetch is persisted, so a restart after kickoff keeps
each game's last pre-kickoff read (U4's gap). Each generation records
`preKickoffCoverage` — per game, the last pre-kickoff fetch and its lead time,
and the games that have none.

**Persistence** — `data/game_day/live/` (gitignored; never `data/ros/`, which
`scheduled-refresh.yml` force-adds to the public repo):

| path | what |
|---|---|
| `_nfl/<season>/week_<n>/observations/{espn_scoreboard,sleeper_live_stats,sleeper_weekly_projections}.jsonl` | NFL-wide observations, stored once |
| `<leagueKey>/<season>/week_<n>/observations/sleeper_league_week.jsonl` | league + users + rosters + matchups per tick |
| `<leagueKey>/<season>/week_<n>/generation.json` | the latest generation (atomic tempfile + replace) |
| `<leagueKey>/<season>/week_<n>/generations.jsonl` | one row per published generation, append-only: id, `supersedes`, `producer`, `inputFingerprint`, `leagueObservationSeq`, and per roster the AS-KNOWN win % / beat-median % / expected final / host score / `pointsBanked` / `scoreNow` (`load_generation_history`) |
| `<leagueKey>/<season>/week_<n>/state.json` | last tick, `lastVerifiedAt`, cadence, timings, refresh-in-progress, `statCorrections` |
| `_collector/state.json`, `_collector/ticks.jsonl`, `_collector/tick.lock` | next due time, source health/backoff, tick log (trimmed), lock |

Observation logs are append-only keyed-delta JSONL (`keyframe` / `delta` /
`unchanged` / `failure`; a keyframe every 100 records), with a `.head.json`
cache rebuilt from the log whenever it disagrees. A torn trailing write is cut
back rather than glued onto. Raw logs are pruned after 4 weeks; generations,
their index and state are kept for the season.

**Generations.** `generation.json` holds the input as-of stamps per source,
the resolved state (every team's `TeamWeek`, opponents, host scores), the
simulation output, `computedAt`, `modelVersion`, draws/seed, the generation id
and the rendered payload parts (`matchup_intel.render_league`: shared fields,
league lineage, one side per roster, the league half of the NFL slate). A new
generation is computed ONLY when `input_fingerprint` changes — a hash of the
pre-simulation render with fetch/compute timestamps stripped plus the
simulation's own input fingerprint — so an unchanged poll is a few requests and
a hash (0.6 s measured). A generation is published only if its `sequence` (the
tick's input fetch time) is newer than the one on disk.

**Serving.** `/api/matchup/intel` → `build_matchup_intel` →
`game_day_live.serve_league_render`: the latest generation, composed for the
requested owner (`compose_team_payload` adds only roster intelligence from the
loaded contract, the archive stamp and freshness) — 15 ms with a cold parse of
the ~1 MB generation, <1 ms warm. **The simulation never runs on a request
thread** (Game Day G, 2026-09-25):

* **Stale generation, collector absent** — served IMMEDIATELY at its true age
  (`state: "stale"`, never blanked) while ONE background compute refreshes it
  (`refreshInProgress`, reason `background_refresh_running`; a failure reads
  `background_refresh_failed:<error>`).
* **No usable generation** (none, or other draws/seed) — a PENDING payload
  from cheap factual inputs only (`matchup_intel.pending_league_render`): the
  TTL-cached Sleeper league fetch (players metadata from the collector's
  persisted daily DB when it covers every rostered player), the cached
  nflverse schedule, and the live-game-state observation ALREADY held
  (`peek_live_state`: in-process memo or the collector's persisted last good,
  at its true age) — no projection fetch, no preseason ensemble, no scoreboard
  request, no simulation. Rosters, host scores, game states, `scoreNow` and
  the banked best-ball lineup (`actual_lineup` → the exact solver in
  `src/ros/lineup.py`) are real; `probabilityState` is `PENDING` and every
  forecast field is WITHHELD as `null` — `outcome`, `expectedLineup`,
  `unpricedPlayerIds`, `uncoveredScoringKeys`, per-player
  `projectedRemaining` / `remainingBasis` / `projectionBasis` /
  `finalLineupPct` …, lineage `estimateCoverage` /
  `projectionFamiliesContributing` / `projectionBasisCounts` — never zero and
  never "unpriced". The request starts ONE background compute
  (`ensure_background_compute`: a daemon thread per league-week key, never
  one per request; concurrent cold requests share it; at most
  `MAX_BACKGROUND_COMPUTES` = 2 per process, past which a request answers
  pending with `background_compute_capacity_exhausted`). It runs the SAME
  fingerprint / simulation / render / generation layout as the collector
  (`compute_request_generation`, producer `game_day_request_compute`) and
  publishes through `write_generation`, so the next poll serves it as
  `servedFrom: "request_generation"`, `state: "degraded"`, reason
  `no_collector_generation`. The collector republishes it under its own name
  at its next tick (the simulation cache makes that cheap), and a request
  generation built from older inputs than the collector's is refused by the
  normal `sequence` order.
* **Background failure** — `state: "failed"`, reason
  `generation_failed:<error>`, forecast still withheld: never a fabricated
  number. It is retried by the first poll after
  `BACKGROUND_RETRY_AFTER_SECONDS` (30 s), which answers pending with
  `previous_attempt_failed:<error>`.

Measured on the real replay (`real_halftime`, `dynasty_main`, 12 teams, 2,000
draws, network seams replaced by the captures, this Windows dev box): cold
request **43.7–44.5 s** (the whole simulation on the request thread) →
**0.06–0.21 s** (median 0.13 s) pending; the background generation is ready
~44–46 s later and the next poll is served in 48–65 ms. Budget:
`docs/GLOBAL_PERFORMANCE_STANDARD.md` §2 (cold/uncached ≤ 3 s, useful state
≤ 5 s) — no route-specific budget exists for this endpoint; the tests pin
the 3 s cold budget.

**`freshness` block** (on every payload):

| field | meaning |
|---|---|
| `state` | served generation: `stale` (payload age > 3 cadence intervals for the current phase: 180 s live) › `degraded` (not the collector's current answer: request generation, last tick failed, generation behind evidence) › `partial` (a source unavailable: live state during games, weekly projections, league, schedule; or `stat_correction_pending_host`) › `current`. No forecast yet: `pending` (background compute running or about to) / `failed` (last background compute failed; retry window open) |
| `reasons` | why, machine-readable |
| `servedFrom` | `collector_generation` / `request_generation` / `pending_factual` |
| `generationId`, `generationComputedAt`, `simulationComputedAt` | which answer, when computed (`null` while pending) |
| `lastVerifiedAt`, `asOf`, `payloadAgeSeconds`, `staleAfterSeconds`, `phase` | the last moment the payload was known to reflect the freshest evidence (a tick that found inputs unchanged re-verifies it) and its age |
| `refreshInProgress`, `refreshStartedAt` | a collector tick or a background compute is working on this league-week now |
| `backgroundCompute` | pending / refreshing payloads only: `state` (`running` / `failed` / `capacity_exhausted`), `triggered` (this request started it), `reason`, `startedAt`, `finishedAt`, `outcome`, `error`, `generationId`, `previous` |
| `collector` | last tick time/outcome and cadence |
| `statCorrections` | generation payloads: `scoringSourceOfRecord`, `pendingHost` (entries below), `reflectedInHostCount`, `notScoredByLeagueCount`; `null` on pending payloads |
| `sources.<name>` | `status`, `fetchedAt` (when WE fetched), `observedAt` (when the source says its content was true, `observedAtBasis` naming the evidence — ESPN `http_last_modified`, projections `provider_updated_at`, else `fetch_time`), `ageSeconds`; sources `liveGameState` (the ONE provider whose state this tick used: `provider`, `selectionReason`), `espnScoreboard` and `sportsDataIoScores` (each provider's own attempt), `sleeperLeague`, `weeklyProjections`, `nflverseSchedule`, `preseasonProjection`, `sleeperLiveStats` (`postFinalChanges` / `unattributableChanges` when stats moved) |

**Stat corrections (Game Day D).** Banked points are the HOST's —
Sleeper league matchups' `players_points` under the league's own scoring —
and that is the scoring source of record; Sleeper live stats are never
rescored into points (`sources.sleeperLiveStats.consumedByScoring: false`).

* **A corrected host value propagates.** It changes the league observation,
  so `input_fingerprint` changes and the collector publishes a NEW generation
  whose current lineup, `scoreNow`, `expectedFinalBestBall` and win /
  beat-median probabilities are recomputed from it. The superseded generation
  is not lost: `generations.jsonl` keeps its row (with the as-known
  `scoreNow` / host score / forecast per roster), the new generation names it
  in `supersedes`, and each generation's `inputs.leagueObservationSeq` points
  at the exact raw, append-only `sleeper_league_week.jsonl` record — the
  host's player points as they were then. Proven on the REAL post-final change
  in the replay (`dynasty_main` roster 4 after GB@ATL went final: 6804
  22.07 → 18.30, 11559 19.01 → 18.83; banked best ball 118.88 → 114.93,
  expected final 358.65 → 355.30, beat median 75 % → 70 % at 200 draws) by
  `tests/game_day/test_game_day_correction_propagation.py`, one test per link.
* **A correction the host has not absorbed is reported, not applied.** Each
  tick diffs the new live-stats observation against the previous one. A
  change to a player whose game was ALREADY observed final when the previous
  stats were read (the collector records each game's first observed final,
  `finalFirstSeenAt`) is a post-final change; a game going final between two
  reads is not. Per league, a post-final change to a rostered player whose
  changed keys move points under that league's card (the exact scorer on the
  changed keys only — a diagnostic, never a score) is `pending_host` until
  the host's own points for him move from their value before the change; then
  `reflected_in_host`. A change the league does not score is
  `not_scored_by_league`. While any is pending the freshness state is
  `partial` with reason `stat_correction_pending_host` — in every mode,
  including `final` (Tuesday corrections) — and the payload still shows the
  host's points. Post-game, live stats are read hourly, so detection lags a
  correction by up to an hour.

**Live game state providers (2026-09-25).** `src/nfl_data/live_game_state.py`
stays the ONE owner of observed game state; SportsDataIO NFL v3
`ScoresByWeek` is a second provider behind it
(`src/nfl_data/sportsdataio_live_game_state.py`, same `ObservedGameState`
shape, `regulation_fraction_remaining` unchanged). The collector
(`game_day_live.collect_live_game_state`) reads ESPN first; only when ESPN
yields no fresh observation (HTTP 403, timeout, backoff) AND SportsDataIO is
eligible (flag `sportsdataio_live_game_state`, default OFF, plus
`SPORTSDATAIO_API_KEY`, checked before any request) does it read SportsDataIO.
One provider per tick, never a per-game merge; else the newest last-good
observation across both providers, else `unavailable` with each provider's
reason named in `freshness.reasons` (`live_game_state.espn:…`,
`live_game_state.sportsdataio:…`). The request-path seam
(`matchup_intel._observe_live_state`) is still ESPN-only.

**Flags.** `game_day_live_game_state` and `sleeper_weekly_projections` default
ON since U5 (rollback `RISKIT_FEATURE_GAME_DAY_LIVE_GAME_STATE=0` /
`RISKIT_FEATURE_SLEEPER_WEEKLY_PROJECTIONS=0` + restart; the collector reads
them at its next tick). The test suite runs with both OFF (`tests/conftest.py`)
so no unit test can reach ESPN or Sleeper.

**Tests.** `tests/game_day/test_game_day_live_collector.py` — cadence per
phase, the observation log (reconstruction, append-only, head rebuild, torn
write, damaged delta), ticks over the real replay fixtures (one generation per
league-week, served payload == direct build, unchanged poll recomputes nothing,
a scored point republishes, restart keeps the pre-kickoff baseline, last-good
scoreboard at its true age, persisted backoff, lock/not-due, one league
failing), out-of-order and failed publication, serving + every freshness state,
and the cold path (`TestColdRequest`: pending inside the 3 s budget with the
simulation gated off the request thread and the banked facts equal to the
generation's, exactly one background compute for six concurrent cold
requests, the next poll served, a failure named and retried after the
window, the per-process bound). `tests/game_day/serving_helpers.py` lets
assembly-focused tests (`test_game_day_replay.py`, `tests/api/test_matchup_intel.py`)
join the background compute and read the served generation.
`tests/game_day/test_game_day_correction_propagation.py` pins the
correction chain. #1346's single-flight / atomic-write tests are carried in
`tests/test_singleflight.py` and `tests/game_day/test_game_day_sim_cache.py`.

## Known limitations, named rather than papered over

* The observed-clock baseline scales a pregame projection by regulation time
  left; no possession, score, injury or usage modelling exists.
* ~~Live acquisition is an in-process memo; a restart after kickoff forgets
  pre-kickoff weekly observations~~ — closed by U5 (below): every observation is
  persisted append-only and the request seam merges the persisted history.
* The simulation still recomputes whenever its inputs change, which during a
  live game is every tick (the clock moves remaining production). U5 makes
  that ONE shared computation per input change instead of one per viewer:
  measured 24-29 s for `dynasty_main` (12 teams, 2,000 draws) on the real
  halftime/Q3/Q4 replays, inside the 60 s live cadence (44 s on the Windows
  dev box). With no generation the first viewer now waits for none of it
  (pending payload), but still sees no forecast until the background compute
  finishes.
* Background computes are in-process threads: each uvicorn worker process
  has its own (bounded) set, and a process restart abandons one mid-flight
  (the next poll starts another). Its result is shared across processes
  through the generation store.
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
