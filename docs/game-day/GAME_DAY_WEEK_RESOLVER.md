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
and typed `GameEvidence`. The existing nflverse schedule cache can establish
scheduled and completed games. A passed kickoff without a result remains
`unknown`; wall time does not prove that a game started.

**Owner methodology decision, 2026-09-09: in-progress remaining production is
TIME-PRORATED.** An explicitly evidenced `in_progress` player keeps observed
points, and his remaining production is his pregame per-game estimate scaled
by the fraction of a single fixed assumed game duration
(`_ASSUMED_GAME_DURATION_SECONDS`, ~3h15m) not yet elapsed since the evidenced
`kickoff_at`. This is deliberately the simplest correct estimator — a future
revision may use snaps, drives, possession or game script, but not without the
same owner authority. The rejected alternative was "remaining = 0 for every
in-progress player," which is not a default, it is a different forecast.

When a player is evidenced `in_progress` but has no usable `kickoff_at` (or
`now` precedes it), remaining stays `None` and the resolver reports him in
`progress_unavailable_player_ids` — a **missing-evidence** state, never a
**methodology-undecided** one (that seam is closed). Completed players and a
host-declared `Out` (definitively finished) both get `remaining=0.0`, not
`None`: the game being over is real evidence nothing further is coming, and
`0.0` is the honest number for that, distinct from `None` ("we cannot say").
Final state requires completed game evidence and actual player scoring, and
its optimal lineup comes from `src/ros/lineup.py`.

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

## Known limitation, named rather than papered over

No live per-game clock/quarter feed is wired, so proration uses a single fixed
assumed game duration rather than a real per-game measurement — a simple
estimator by design (see the owner decision above), not a precise one. The API
shows actual/banked scoring and player state where it has evidence, and
withholds probability only when game-progress evidence for an in-progress
player is genuinely missing. Sleeper `Out` is treated as definitively finished
(`remaining=0.0`); less certain injury labels remain projections.

## Tests

`tests/ros/test_game_day_week.py` covers pregame plus deterministic live/final
fixtures. The tests pin that banked points survive, in-progress remainder is
time-prorated when kickoff evidence is usable and reports
`progress_unavailable_player_ids` when it is not, completed and ruled-out
players get `remaining=0.0` (not `None`), completed scoring produces the
canonical final lineup, and a passed kickoff without a result remains unknown.
The pregame tests still cover what is not there: an unpriced player is `unknown` and reaches
`unsimulable_player_ids` (asserted through a real `simulate_league_week` call,
not just on the resolver's own output); an IR player leaves the week and is
**not** miscounted as merely unpriced; a begun week is refused on both the
team-score and player-score signals; no rosters and no starter slots are
refused; every team gets an opponents entry.
