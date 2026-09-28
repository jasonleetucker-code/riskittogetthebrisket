# BALLDONTLIE as a Game Day live-state provider — evaluation record

**Owner decision (2026-09-27):** try BALLDONTLIE NFL as an alternative live NFL game-state source for
Game Day. Do not switch production over blindly: validate capabilities, build it behind the existing
provider abstraction, run it in shadow first, and promote only on real live-game evidence. Do not bypass
ESPN's block. Buy nothing without owner approval.

**Current status: ADAPTER CODED + SHADOW-CAPABLE. NOT shadow-validated, NOT a production provider.**
No BALLDONTLIE credential exists yet, so no live response has been captured.

## 1. Why

ESPN's public scoreboard refuses our User-Agent (HTTP 403 on every attempt on the production box, with no
success on record; reproduced off-box 2026-09-27). Some default library User-Agents are accepted, but
switching to one would work around a deliberate block, so it is not done. SportsDataIO is paid and not
activated. As a result, production Game Day's game status comes from the NFL schedule only: no observed
quarter, clock, halftime or final.

## 2. What BALLDONTLIE publishes (researched 2026-09-27, https://nfl.balldontlie.io/)

| Tier | $/month | Requests/min | NFL endpoints |
|---|---|---|---|
| Free | 0 | 5 | Teams, Players, **Games** |
| ALL-STAR | 9.99 | 60 | + injuries, stats, standings, rosters |
| GOAT | 39.99 | 600 | + advanced stats, **Plays**, props, DFS, fantasy |

Auth: `Authorization: <key>` (no prefix). Without a key the API answers `401 Unauthorized` (measured
2026-09-27). Documented errors: 401 (no key or tier), 400, 404, 406, 429 (rate limited), 500, 503.

**`GET /nfl/v1/games` (free).** Each row has:

- `id`, `home_team` / `visitor_team` (`abbreviation`), `date` (kickoff, ISO UTC), `season`, `week`, `postseason`;
- `status` — free text; only `"Final"` is documented;
- `status_state` — `scheduled | in_progress | final | postponed | canceled | delayed | suspended | abandoned | unknown`;
- `home_team_score` / `visitor_team_score` and per-quarter / `*_ot` line scores.

The docs state: "Game data is updated in real-time for games currently in progress." No refresh interval
or latency is documented.

What the Games endpoint does **not** publish:

- the current quarter/period;
- the game clock;
- a halftime value;
- any data-side "as of" timestamp.

Per-quarter line scores cannot stand in for the period: the docs' own final-game example has a `null`
quarter the team did play.

**`GET /nfl/v1/plays` (GOAT tier).** Takes a `game_id`. Each row has `period`, `clock_display`, `wallclock`
and the score at that play. That clock is the clock **at the last play**, not a running clock: it would
have to be modelled as "last observed game clock", timestamped by `wallclock`. It is also a per-game
request: 13+ concurrent Sunday games at 1/min each exceeds the free tier's 5/min. Not purchased.

## 3. Classification

**Provisional: B — PARTIAL LIVE-STATE PROVIDER** (free tier): lifecycle and score, no period or clock.
It stays provisional until the live evidence in §5 exists. **C — unsuitable** remains possible if live
latency or reliability is poor. **A — full** is reachable only with the GOAT-tier plays feed, which is
unverified and an owner purchase decision (§7).

## 4. What was built (canonical, no second owner)

- `src/nfl_data/balldontlie_live_game_state.py` — adapter.
  - Emits the SAME `ObservedGameState` / `ScoreboardSnapshot` as ESPN and SportsDataIO. `provider="balldontlie"`, lineage `balldontlie:games`.
  - Maps `status_state` to phase. `period`, `clock_seconds` and `display_clock` are always `None`, so `regulation_fraction_remaining` answers `period_missing`. No wall-clock inference.
  - Halftime is not mapped until evidence shows how BALLDONTLIE writes it. The raw `status` text is kept.
  - `overtime` is `True` only when an OT line score is published.
  - A missing score stays `None`, never 0. An unknown team code skips the row. An unexpected paginated answer is refused.
  - Credential env var `BALLDONTLIE_API_KEY`, read via `src/utils/secret_credentials`. It is never logged, put in a URL, or returned in an error string. Absent key: an explicit `credential_missing` result with no request made.
- `src/nfl_data/live_game_state.py` changes:
  - registry: `PROVIDERS`, `PROVIDER_SOURCE_LABELS`, `PROVIDER_FLAGS`;
  - `fetch_live_game_state(provider="balldontlie")` dispatch;
  - `compare_snapshots` — provider-neutral, matches games on canonical teams, reports every field from both sides, and counts a field only one side states as missing, never as agreement.
- Flag `balldontlie_live_game_state`, **default OFF**, under the Game Day master flag.
- Collector `src/ros/game_day_live.py::collect_shadow_live_state` — **shadow only**:
  - one request per due tick, under the tick budget, with its own persisted backoff;
  - raw observations go to the `balldontlie_games` log;
  - one comparison record per tick goes to `data/game_day/live/_nfl/<season>/week_<w>/shadow_balldontlie.jsonl`, against the provider the collector actually selected, or none;
  - it never enters selection, `live_sources`, lineage, the input fingerprint, a generation or a forecast. This is pinned by a test that requires byte-identical generations with and without the shadow.
- `scripts/balldontlie_shadow_report.py` summarizes the shadow log:
  - per game: first-seen lifecycle and phase, every raw status text, and score changes;
  - agreement vs the reference, and score lag;
  - fetch percentiles, errors, and request rate vs the 5/min limit.
- The read-only on-box diagnostic (`game-day-live-diagnostics.yml`) prints that report for the newest week.

**Selection order is unchanged:** ESPN → SportsDataIO (when eligible) → newest last-good → unavailable.
BALLDONTLIE is not in it. If promoted, the intended position is **after SportsDataIO and before the
stale last-good observation**. SportsDataIO is a full provider (quarter and clock) and ranks above a
partial one, while fresh lifecycle and score beat a stale full observation. That placement also needs a
consumer check: `src/ros/game_day_week.py` must treat an IN_PROGRESS game with no period as "remaining
time unknown", never as a wall-clock estimate.

## 5. Evidence required before promotion (none captured yet)

1. **Owner:** create a free BALLDONTLIE account and install `BALLDONTLIE_API_KEY` in the production
   `.env`. Agents cannot create accounts or handle the key.
2. **Deploy:** set `RISKIT_FEATURE_BALLDONTLIE_LIVE_GAME_STATE=1` on the box. The collector reads it the
   next tick; no restart is needed for the collector.
3. **Capture a full live slate:**
   - pregame: `scheduled`, correct kickoff;
   - Q1–Q4: `in_progress`, scores moving;
   - halftime: which `status` text appears, if any;
   - final: `final`, final scores, `completed` true;
   - overtime, if one occurs naturally.
4. **Measure freshness:**
   - fetch time;
   - score-change lag vs an independent reference;
   - the provider → collector → generation → screen path.

   ESPN is blocked, so the in-collector reference is usually "none". Final scores can be checked
   afterwards against the nflverse schedule results, and score timing against Sleeper live stats.
5. **Decide** A/B/C from that evidence; only then change the selector (a separate PR) and run the Stage 4
   production checks:
   - clock/status freshness;
   - fantasy score agreement;
   - remaining-production, matchup odds, Live Median Race and leverage updates;
   - no cross-provider identity mismatch.

## 6. Request budget (free tier)

The shared collector is the only poller; no viewer calls BALLDONTLIE.

- One request per due tick: 60 s while games are live, 180 s near kickoff, hourly otherwise.
- Estimated volume:
  - Sunday: about 660 requests over about 11 live hours;
  - Thursday and Monday: about 210 each;
  - idle: about 24 a day;
  - in total, about 1,300–1,500 a week.
- Peak rate: 1 request/min against the 5/min limit.
- A 30-second cadence would still fit (2/min), but a partial provider does not justify it.

## 7. Paid-tier question (owner decision; nothing bought)

GOAT ($39.99/month, 600 requests/min) unlocks `/plays`: `period`, `clock_display` and `wallclock` per play.

- That would let Game Day state "last observed game clock at <wallclock>", with the age shown.
- Budget: about one request per live game per tick, so 13+ requests/min at the Sunday peak (well inside 600/min).
- Whether it materially improves Game Day depends on play latency, which cannot be measured without the tier.
- The docs mention a 48-hour trial (GOAT tier limited to 5 requests/min), which could measure latency
  before any purchase. Starting it is also an owner action.

## 8. Source posture

Owner-approved candidate (2026-09-27). Role: **NFL game state only**. Sleeper keeps fantasy scoring,
player stat lines and league state. ESPN stays in place and degraded; its block is not bypassed.
SportsDataIO's adapter is kept, not activated.
