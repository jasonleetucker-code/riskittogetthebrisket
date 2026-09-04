> **CANONICAL WEEK 1 SCOREBOARD — OWNER DIRECTIVE 2026-09-04.** Before broad V2 work, finish the Week 1 pregame + Game Day launch tranche by **Wednesday 2026-09-09 (America/Chicago)**. Progress is governed by `docs/season-launch/WEEK_1_LAUNCH_CONTRACT.md`: fixed denominator **30**, and only literal `VERIFIED` counts. Claude/automation check-ins must mechanically report X/30 + percentage from that contract and preserve IMPLEMENTED/MERGED/DEPLOYED/VERIFIED boundaries.

# 2026 season-launch readiness — pregame / Game Day / postgame

**Audit date:** 2026-09-03 (pre-Week-1). **Updated 2026-09-04** — the owner's
season-launch directive answered this document's two open scope questions and
authorized the tranche; §0 records live state, the sections below keep the
original audit. Owner priority order: perishable evidence capture → pregame
writeups → Game Day dashboard → postgame. This document records what already
exists so no future session re-derives it, and names the single highest-value
next action per surface. Game Day remains POST-V1 per
`docs/VERSION_1_COMPLETION_CONTRACT.md` §4.1; nothing here reopens V1.

## 0. Live status — 2026-09-04

**The clock.** Sleeper's own `/state/nfl` reports `season=2026 week=1
season_type=regular` as of 2026-09-04. Week 1's first kickoff is Thursday
2026-09-10 (~00:15 UTC Fri). **The pregame capture window is OPEN and closes
at that kickoff**, permanently.

**Owner scope questions — ANSWERED by the directive**, so neither is blocking
any more. Both public and private are wanted: "polished public Week 1 pregame
coverage suitable for league members" AND "richer private owner-facing matchup
intelligence", from the same canonical data with correct public/private
filtering. §1 and §3 below are updated only by this note; their factual audit
stands.

| component | state | note |
|---|---|---|
| Game Day archive capture | IMPLEMENTED — awaiting merge/deploy | §2a |
| Week 1 pregame (public) | READY, unverified for Week 1 specifically | §1 |
| Week 1 pregame (private) | NOT STARTED | scope now authorized |
| Game Day dashboard | NOT STARTED | §2; methodology decision outstanding |

**Methodology finding that constrains Game Day, recorded here so it is not
re-derived.** `config/projections/source_capability_census.json` has exactly
two `implementationStatus: LIVE` `PROJECTION_MODEL` sources —
`clayProjections` and `idpShowProjections` — and **both are
`PRESEASON_FULL_SEASON` horizon. There are ZERO live WEEKLY-horizon projection
sources.** `src/ros/projection_ensemble.py` says so in its own docstring and is
why `C5-PROJ-D` (ROS/full-season) was built before `C5-PROJ-C` (weekly). So a
Week 1 per-player point estimate today is a full-season projection's per-game
figure, and any Game Day simulator's per-week variance term has no live weekly
source to fit against. That is an owner methodology decision, not something to
invent, and it is the one genuine owner decision this tranche surfaces.

### 2a. Game Day archive capture — IMPLEMENTED (2026-09-04)

The gap §2 recorded ("a pure library module with **no caller**") is closed:

- `src/ros/game_day_capture.py` — the resolution half: the pregame window
  gate, slot eligibility, IR/taxi subtraction, estimate joining. Pure
  functions of already-fetched payloads, so it is testable with no network.
- `scripts/capture_game_day_predictions.py` — the CLI. Exit codes
  0 captured/already-captured · 1 error · 2 nothing to do · **3 REFUSED**.
- `deploy/systemd/dynasty-game-day-capture.{service,timer}.template` — the
  schedule: **Thursday 13:00 UTC, retry 15:30 UTC**. Chosen against the
  season's EARLIEST first kickoff (Thanksgiving, 17:30 UTC), not the usual
  Thursday-night one, and after Wednesday waiver processing.
- `.github/workflows/game-day-capture.yml` — manual "capture now" + a
  dry-run verify mode, running the same script on the box over SSH.
- `tests/ros/test_game_day_capture.py` — 23 tests.

Three decisions worth not re-litigating:

1. **It runs on the box, not in CI.** Same reason `dynasty-faab-history`
   gives: `data/` is gitignored repo-wide, so an archive written on a runner
   is discarded with the runner. Sharper here — the projection snapshots the
   capture joins against (`data/bdvm/projections/`) exist only on the box, so
   a CI run would also record a uniformly estimate-less snapshot.
2. **A `pregame` capture is REFUSED once the week has begun**
   (`week_has_begun` — any nonzero team or player score from Sleeper). The
   archive itself cannot enforce this: `record_snapshot` takes `capture_kind`
   from its caller and its truthful `captured_at` proves *when* a capture ran,
   not that the week was unplayed when it did. A missed window stays missing.
3. **A preseason `season_type` is refused** (exit 2). The archive keys on
   `(league, season, week, team, capture_kind)` with no season-type axis, so a
   preseason run would consume the real Week 1 pregame slot with a preseason
   roster and then refuse the genuine capture as a duplicate.

Dry-run against live Sleeper, 2026-09-04, both leagues resolving end to end:

```
dynasty_main: teams=12 players=674 slots=21 (sleeper_roster_positions) scoring=sf1:9e51824690d091f9
dynasty_new:  teams=10 players=290 slots=10 (sleeper_roster_positions) scoring=sf1:82a5f8ef2bfdb098
```

Estimates were `0/674` and `0/290` **in this sandbox only** — `data/bdvm/`
is gitignored and exists on the box, where `dynasty-bdvm-refresh` writes it.
Whether prod resolves real estimates is exactly what the workflow's dry-run
mode is for, and it is **unverified until run there**.

**Status: IMPLEMENTED. Not yet MERGED, DEPLOYED or PRODUCTION VERIFIED.**

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

## 2. Game Day dashboard — NOT STARTED (live surface); evidence-capture substrate built but NOT RUNNING

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

**Highest-value next action, in order**: (1) wire `game_day_archive`'s
capture call into a scheduled job that runs before each week's games lock
(even a bare-minimum cron hitting it once a week beats zero capture — this
is a `RET`-flagged row, "collection should start as early as the phase
allows," per `docs/C_SERIES_SCOPE_MANIFEST.md`); (2) only then build the
actual live dashboard (state machine: scheduled → live → final, per the
directive's own required order), since the dashboard is a large,
methodology-sensitive build (the spec explicitly says the simulator's
distribution family / sample count / correlation handling are product-
semantics-changing decisions, not to be invented unilaterally) while the
archive wiring is small, mechanical, and time-critical.

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
