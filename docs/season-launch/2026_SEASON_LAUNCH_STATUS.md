# 2026 season-launch readiness — pregame / Game Day / postgame

**Audit date:** 2026-09-03 (pre-Week-1). Owner priority order: pregame writeups →
Game Day dashboard → postgame writeups, all before kickoff. This document
records what already exists so no future session re-derives it, and names the
single highest-value next action per surface. It is a status/audit record,
not an authorization — none of this is V1-required (Game Day is explicitly
POST-V1 per `docs/VERSION_1_COMPLETION_CONTRACT.md` §4.1).

## 1. Pregame writeups — READY (public factual layer), NOT STARTED (private decision-intelligence layer)

**What exists and is live**, wired into the public league contract
(`src/public_league/public_contract.py:86-87`, consumed by
`frontend/lib/public-league-data.js`,
`frontend/app/league/week/[season]/[week]/page.jsx`,
`frontend/app/league/articles/[season]/[week]/page.jsx`):

- `src/public_league/matchup_preview.py` — per-matchup all-time H2H record,
  last-5-meetings, last-3-game recent form. Auto-detects `"preview"`
  (upcoming/unscored) vs `"recap"` (scored) mode from the snapshot itself —
  no separate pregame/postgame code path to keep in sync.
- `src/public_league/matchup_narrative.py` — full AI-generated ESPN-style
  preview/recap pipeline (Sleeper snapshot + NFL news/results + prior
  articles → structured brief → prompt → Claude-generated article → saved to
  `exports/narratives/`), with anti-repetition design (prior openers/angles
  fed back so consecutive weeks don't read templated).

**What is genuinely missing**: everything on the owner's fuller wishlist that
requires *private, proprietary decision intelligence* rather than public
factual/retrospective content — per CLAUDE.md's public/private boundary
("proprietary values, edges, targets, weaknesses, forecasts... are private"):
expected best-ball starters via the canonical lineup solver
(`src/ros/lineup.py`), projected scoring, roster strengths/weaknesses
(`src/roster_intel/strength.py` / `weakness.py`), playoff/power context
(`src/ros/championship.py`, `src/public_league/power_v2.py`), BDVM
projections. **No code searched found any private "my matchup this week"
surface** — this would be new, authenticated-surface work, not an extension
of the public narrative system.

**Highest-value next action**: audit whether the owner's fuller pregame ask
is meant to extend the PUBLIC narrative (in which case: wire
`matchup_narrative.py`'s brief-builder to also pull roster-strength/lineup
data as PUBLIC-safe *factual* content — e.g., "who started" is a fact even
though "who should start" is proprietary) or wants a genuinely new PRIVATE
per-team matchup page. That's a product-boundary question worth confirming
with the owner before building, since building the wrong one wastes real
effort against a hard kickoff deadline.

## 2. Game Day dashboard — NOT STARTED (live surface); evidence-capture substrate now WIRED (2026-09-03)

- `docs/GAME_DAY_PROBABILITY_SPEC.md` (13 sections) is a complete, approved
  design: win-matchup %, beat-league-median %, one canonical scoring
  simulation (never two unrelated formulas), live updating through the
  scoring period, explicit missing/unavailable semantics (no fake 0% for a
  league without a median game).
- `src/ros/game_day_archive.py` (`C5-GD-02`, delivered 2026-08-20) is a pure,
  append-only capture store for per-(league, season, week, team) prediction
  state — built specifically because the underlying observation is
  **perishable**: once a week scores, the pre-game state that would let a
  future backward-replaying simulator validate against it is gone forever
  unless captured before the outcome is known. Confirmed by a two-agent
  audit at build time: no backward-replaying simulation engine exists
  anywhere in the repo, and no archived per-week roster/projection data
  exists before whenever capture starts (the 2026-04-28 ROS-aggregate
  snapshots and the 2026-07-14 temporal-ledger floor are different, board-
  value-only quantities).
- **No shipped route or section file exists for a live Game Day view**
  (confirmed independently by this session and by the V1-123 scoping
  document: `frontend/app/league/sections/` has no `game-day.jsx`).
- **Real gap found this session, not previously recorded**: `grep -rn
  game_day_archive .github/workflows/ scripts/` returns **zero matches** —
  the capture substrate is a pure library module with **no caller**. It is
  not wired into any scheduled job, so it is capturing nothing right now,
  despite being built for exactly the perishable-evidence reason above and
  the season being about to start. Every day between now and whenever this
  is wired in is unrecoverable evidence loss, by the module's own stated
  rationale.

**Closed this session (2026-09-03)**: `scripts/capture_game_day_snapshots.py`
is `game_day_archive`'s first real caller, plus
`deploy/systemd/dynasty-game-day-snapshots.{service,timer}.template` (picked
up automatically on the next production deploy — `deploy/deploy.sh` globs
every `*.timer.template` in that directory and installs any that are
missing, no other deploy-script change needed). Validated end-to-end against
real production data in this sandbox (real Sleeper rosters for
`dynasty_main`, real scoring-fingerprint evidence, a real write, a real
idempotent re-run refusing the duplicate) before being committed — not just
unit-tested against fakes, though 8 unit tests (`tests/scripts/
test_capture_game_day_snapshots.py`) pin the behavior too, including the one
real bug that validation run caught:

- **A real defect, found and fixed before shipping**: the contract's
  `sleeper.positions` map is keyed by player NAME, not playerId —
  `sleeper.idToPlayer` (playerId → name) is the missing intermediate step.
  The first draft assumed a direct playerId → position map and silently
  captured every single player as `position: "UNKNOWN"` against a real
  real dynasty_main data (12 real teams, 45-58 players each). Caught
  by inspecting the actual written output rather than trusting a clean exit
  code — the script ran without erroring either way. Fixed and pinned by
  `test_position_map_chains_through_idtoplayer`.
- **What it honestly captures**: roster composition, a lineup-eligible flag
  (pure positional eligibility against the league's resolved starter slots —
  documented in the script's own module docstring as the simpler of two
  possible readings, since nothing else in the codebase defines this term
  for an unpriced, scripted capture), the league's PROVEN-CURRENT scoring
  fingerprint (fails closed — refuses the whole league rather than stamp an
  unverified identity — when that evidence is stale or missing), and a real
  wall-clock timestamp.
- **What it does NOT capture, and cannot yet**: every `pointEstimate` is
  `null`. A repo-wide check (this same design pass) found no per-week
  point-projection source anywhere in this codebase — BDVM produces a
  season-long/ROS rate and a dynasty asset value, neither of which is a
  specific upcoming week's expected score. This is not a shortcut; it is the
  only honest value `PlayerPointEstimate` supports today, and the module was
  explicitly designed to require exactly this state rather than coerce a
  guess. When a real per-week source lands, it plugs in as this script's
  `estimate_source` without changing the capture cadence or roster
  resolution.
- **Cadence is a documented, revisable operational choice**, not a spec
  requirement: `docs/GAME_DAY_PROBABILITY_SPEC.md` §5 requires archiving
  pregame snapshots but names no exact cutoff. Chosen: weekly, Thursday
  10:00 UTC — after `current_nfl_week()`'s own UTC-midnight Thursday
  week-turnover, before that week's first possible kickoff (Thursday Night
  Football). See the `.timer.template`'s own comment for the full
  reasoning; revise there if a tighter window is later decided.
- **Not yet installed on production** — that happens automatically on the
  next `deploy.sh` run once this lands on `main`; there is no separate
  manual step, but it has not been observed running on the real box yet.

**Highest-value next action, now**: (1) confirm the timer actually installs
and fires on the next production deploy (`journalctl -u
dynasty-game-day-snapshots.service` after the first Thursday post-deploy,
matching `SERVICE_NAME="${SERVICE_NAME:-dynasty}"` in `deploy/deploy.sh`);
(2) build the actual live dashboard (state machine: scheduled → live →
final, per the directive's own required order), since the dashboard is a
large, methodology-sensitive build (the spec explicitly says the
simulator's distribution family / sample count / correlation handling are
product-semantics-changing decisions, not to be invented unilaterally)
while the archive wiring above was small, mechanical, and time-critical —
now done.

## 3. Postgame writeups — READY (public factual layer), same private-layer gap as pregame

- `src/public_league/weekly_recap.py` — auto-generated ESPN-style postgame
  recap per scored week: headline, multi-sentence summary (standings
  context, MVP, blowout/nail-biter framing, top performers, bad beats,
  recent activity), superlatives, per-matchup one-liners, completed trades
  during the week. Wired into the same public contract as pregame.
  `matchup_narrative.py`'s `"recap"` mode covers the same ground with the
  AI-generated long-form article.
- Includes standings and playoff-week (`isPlayoff`) context. **Does not**
  include projection-based "expected vs. actual" analysis or power-ranking
  delta — those would need BDVM/projection data, which this module never
  references (confirmed: no BDVM import anywhere in `weekly_recap.py`).
- Same public/private boundary question as pregame applies to any richer
  "expected vs actual" or power-impact content the owner wants.

**Highest-value next action**: same boundary question as pregame #1 above —
confirm whether "expected vs actual" belongs in the public recap (arguably
factual: "the model expected X, Y happened" is retrospective once the week
is scored) before building it into `weekly_recap.py`'s existing pipeline
rather than a new one (avoiding a second recap-generation owner).

## Summary table

| surface | classification | blocking question |
|---|---|---|
| Pregame writeups | READY (public) / NOT STARTED (private) | public/private scope confirmation |
| Game Day dashboard | NOT STARTED (dashboard); substrate built but idle | none — wire the capture job now, time-critical |
| Postgame writeups | READY (public) / NOT STARTED (private "expected vs actual") | public/private scope confirmation |

None of this work is V1-required; it does not touch V1-123/V1-125/V1-126 or
any V1 row's denominator.
