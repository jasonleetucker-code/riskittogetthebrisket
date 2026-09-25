# Game Day replay fixtures (U4)

Consumed by `tests/game_day/test_game_day_replay.py`. Rebuilt from the raw
captures by `build_replay_fixtures.py` (the raw capture directory, ~30 MB, is
not committed).

## Real (`real_*`)

Trimmed REAL captures taken 2026-09-25 during the Thursday GB@ATL game
(kickoff 00:15Z), week 3 of 2026:

| scenario | captured | GB@ATL observed |
|---|---|---|
| `real_end_q1` | 00:58:24Z | `STATUS_END_PERIOD` Q1 |
| `real_q2_in_progress` | 01:13:34Z | Q2 9:38 |
| `real_halftime` | 01:50:08Z | `STATUS_HALFTIME` (both leagues) |
| `real_q3_in_progress` | 02:05:24Z | Q3 12:26 |

Each `scenario.json` carries the ESPN public scoreboard (trimmed to id, dates,
competitors' abbreviations + scores, and status) and the Sleeper week-3
matchups for `dynasty_main` (`1312006700437352448`, best ball) and, for
halftime, `dynasty_new` (`1320092771247222784`, managed). Matchup rows keep
`roster_id`, `matchup_id`, `points`, `players`, `starters`, `players_points`.

`shared/`:

- `dynasty_main_league.json` / `dynasty_new_league.json` — `settings`
  (`best_ball`, `league_average_match`, `num_teams`), `roster_positions` and
  `scoring_settings`, from the committed Sleeper league evidence in
  `docs/master-site-audit/evidence/W18/`.
- `players.json` — Sleeper player metadata (name, position,
  fantasy_positions, team, injury_status) for every rostered player, taken from
  the `player` block Sleeper embeds in its projection rows.
- `projections_real.json` — the REAL Sleeper weekly projections fetch at
  00:58:24Z (RotoWire model), trimmed to rostered players with a `game_id`
  (placeholders dropped), stat keys trimmed to those either league card pays
  plus `pass_yd`/`rush_yd`/`rec_yd`, zero values dropped. The 01:13:34Z fetch
  was byte-identical to it.
- `projections_real_later_changed_only.json` — the REAL 01:28:54Z fetch,
  same trims, further trimmed to the rostered rows whose stat line CHANGED
  versus 00:58:24Z (205 rows, 10 of them GB/ATL). The provider changes lines
  mid-game; the kickoff lock must ignore those for TNF players while Sunday
  players (still pre-kickoff) take the newer line.
- `players.json` and the projection files are written as compact JSON.

## Synthetic — labelled, never presented as captures

- `shared/projections_synthetic_pre_kickoff.json` — the real TNF (GB/ATL)
  rows re-stamped as fetched at 00:10Z, provider stamp removed. No capture
  predates kickoff; the provider's per-row `updated_at` is one 00:50:12Z batch
  stamp that cannot date a line. UNVERIFIABLE ASSUMPTION: the lines did not
  change between 00:10Z and 00:58Z — and the 01:28:54Z fetch proves the
  provider does change lines mid-game, so this file exercises the in-progress
  path and is NOT evidence of a real baseline. Without it the real replay
  correctly leaves TNF players
  with NO weekly baseline (asserted by
  `test_real_capture_without_pre_kickoff_fetch_leaves_tnf_players_unpriced`).
- `synthetic_overtime`, `synthetic_end_regulation_tied`, `synthetic_delayed`,
  `synthetic_postponed`, `synthetic_final` — the real halftime capture with one
  ESPN status rewritten; each file's `meta.mutation` says exactly what changed.
- Missing feed, stale feed, a post-final stat correction, and both flags off are
  produced inside the test from these files (snapshot error / older
  `observed_at` / one `players_points` edit / disabled seams).
- Nflverse schedule rows are derived in the test from each scenario's ESPN
  kickoffs (the 2026 nflverse cache is not available offline).
