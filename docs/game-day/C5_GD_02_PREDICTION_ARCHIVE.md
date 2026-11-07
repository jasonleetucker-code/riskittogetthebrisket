# C5-GD-02 — Prediction Archive Without Temporal Leakage

**Status:** DELIVERED 2026-08-20 — capture substrate only; the simulator that
will consume it is NOT built here
**Unit:** `C5-GD-02` (manifest row, `RET`-flagged — irreversible evidence)
**Governing specs:** `docs/GAME_DAY_PROBABILITY_SPEC.md` §5,
`docs/PLAYER_IMPACT_WAR_MVP_SPEC.md` §10, `docs/PROJECTION_ENSEMBLE_PLAN_2026-08-15.md`
§7 ("archive before learning" — the same perishable-evidence principle applied
one level up, to Game Day/xWAR's own consumer)
**Owner:** `src/ros/game_day_archive.py`
**Lane:** Claude 11 — C5, under the POST-V1 C-Series mass-build campaign
(`docs/EXECUTION_PLAN.md` §0, owner directive 2026-08-20)
**Depends on:** nothing from the other three open C5 PRs — branched from
`main`, deliberately (see "Why this doesn't stack" below)

## Why this unit, and why now

`docs/PLAYER_IMPACT_WAR_MVP_SPEC.md` §4 (xWAR) and
`docs/GAME_DAY_PROBABILITY_SPEC.md` §10-12 both require "the same archived
no-lookahead league-week scoring distribution/simulation." Before building
either, this session ran a two-agent audit to answer one question: does a
canonical implementation already exist? The answer, confirmed independently
by both agents:

- **No backward-replaying simulation engine exists.** Every engine in the
  repo (`src/public_league/playoff_odds.py`, `src/ros/playoff_sim.py` +
  `src/ros/championship.py`) is forward-looking — projects from *today's*
  live roster state through the remaining season. None replays an
  already-played week using only evidence available at that time. The
  repo's own governance already flags the two playoff engines as an
  unresolved duplication (`docs/C_SERIES_SCOPE_MANIFEST.md:303`,
  `C5-PLAY-01`, disposition CONSOLIDATE) — a third forward engine must never
  be added, and neither of the existing two is the missing backward kind
  anyway.
- **No archived per-week roster/projection data exists to replay against,
  even if a backward engine were built.** `src/history/`'s temporal ledger
  (C1-U4) is asset-value-identity-keyed only — no team/roster/week axis
  anywhere in its schema — and its own `HISTORY_FLOOR` (2026-07-14) is a
  hard floor with nothing earlier recoverable. `exports/archive/` is
  board-value snapshots only. `data/ros/aggregate/history/` is ROS-aggregate
  value snapshots only, back to 2026-04-28. None captures "who was
  rostered/started, what were the pre-game point estimates" for any past
  week.

The second finding is the more consequential one: **retroactive backfill is
structurally impossible.** The observation was never made, for the same
reason `scripts/backtest_perfect_draft.py` already hard-blocks (exit 2) on
the analogous draft-price problem — "This one cannot be fixed by code — the
observation was never made." A substrate can only run prospectively from
whenever capture starts. Every week that passes without capture is
unrecoverable evidence, permanently — this is exactly the shape of loss
`C1-RET-*` exists to prevent for other data, and `C5-GD-02` is the named,
owner-approved, `RET`-flagged row for this one.

## What this unit deliberately does NOT do

Build the simulator. A joint weekly Monte Carlo engine needs methodology
decisions — per-player score distribution family/shape, sample count,
cross-player correlation handling — that materially change product
semantics. Inventing them unilaterally in this pass would violate the
calibration policy's requirement that every consequential tunable be
classified MEASURED/VALIDATED, MECHANICALLY REQUIRED, or PRIOR/HEURISTIC
with a named challenger obligation — not silently decided. This matches
last session's own Game Day assessment
(`docs/cseries-delivery/CLAUDE_11.md` §7): the joint simulation + lineup
integration + live-state updating + calibration is genuinely multi-session
scope, and this unit does not shortcut that by building an unvalidated
model just to have something running.

So: **capture now, model later.** Once this substrate has been running for
enough weeks to be useful, the simulator becomes buildable as a genuinely
validatable PRIOR rather than a guess with nothing to check it against.

## Design decisions worth recording

### Why this doesn't stack on #966/#973/#969

Per this session's own mission brief: "avoid touching projection PR
branches" and "do not stack on #969 unless unavoidable." This unit needs
neither. It computes no standings credit (so it needs nothing from
`src/war/standings.py` on #969), and it does not resolve point estimates
itself (so it needs nothing from `src/ros/projection_observations.py` on
#973) — see below.

### Point-estimate resolution is deliberately NOT this module's job

The module accepts already-resolved `PlayerPointEstimate` rows; it does not
call BDVM, a projection ensemble, or anything else to produce them. This
mirrors `src/history/store.py`'s own separation (a pure store; callers pass
already-resolved values) and keeps this module dependency-light and fully
testable without any live service. A future capture SCRIPT (not this unit)
is responsible for gathering roster data from Sleeper and point estimates
from wherever is appropriate at that time, and calling `record_snapshot`.
This also means the module doesn't need to pick — right now, in this
pass — whether "wherever is appropriate" means BDVM's live service, the new
`C5-PROJ-B` `ProjectionObservation` wrapper, or something else; that choice
is deferred to whoever writes the capture script, after `C5-PROJ-B` merges.

### Missing point estimates cannot be silently coerced to a fabricated pair

`PlayerPointEstimate` enforces `point_estimate` and `estimate_source` are
either both present or both absent — a source name with no number, or a
number with no attributable source, are both refused at construction.
Mutation-proved: disabling the check sends both
`test_source_without_estimate_is_refused` and
`test_estimate_without_source_is_refused` RED.

### Append-only, identity-keyed filenames — not a timestamped log

A snapshot's file path is derived purely from `(season, league_key, week,
team_id, capture_kind)` — no timestamp in the name. This is what makes a
second write for the same tuple collide on the same file and be refusable,
rather than silently accumulating unbounded duplicate captures the way a
timestamped filename would. Mutation-proved: disabling the
`path.exists()` refusal sends `test_second_capture_of_the_same_tuple_is_refused`
RED, and the surviving `test_first_capture_succeeds` alone would NOT have
caught that regression — recorded in the test file's own docstring so a
future reader understands why both tests exist.

### `captured_at` cannot be backdated because it isn't a parameter

`record_snapshot`'s signature has no `captured_at` argument at all — the
value is always `datetime.now(timezone.utc)` at call time. A caller cannot
inject an earlier timestamp to make a late capture look like it happened
on time. This is stronger than validating a caller-supplied value (which a
sufficiently motivated caller could still spoof within tolerance) —
structurally impossible instead of merely checked.

### No `HISTORY_FLOOR`-equivalent constant, and that's deliberate

`src/history/store.py`'s `HISTORY_FLOOR` names a specific date because
`exports/archive/` genuinely starts there and the boundary is a fact about
recoverable evidence. This module has no equivalent constant because there
is no earlier data to bound — the floor is simply "whenever this unit first
deploys," and inventing a constant for that would misrepresent an
operational fact as a designed boundary. The `reconstructed` fidelity label
`src/history/asof.py` defines-but-never-produces has the same shape here:
this module has no reconstruction path at all, and none should be added
without an explicitly approved methodology, exactly as that precedent
establishes.

## Validation

`tests/ros/test_game_day_archive.py` — 15 tests: the two `PlayerPointEstimate`
consistency invariants (mutation-proved), three `WeeklyPredictionSnapshot`
construction refusals (bad capture kind, empty roster, duplicate player in
one roster), round-trip write/read preserving both present and missing
estimates, load-of-never-captured returns `None` not an error,
`captured_at` bounded between two real clock reads taken around the call
(proving it's the real clock, not a caller value), per-week multi-team
loading, capture-kind filtering, empty-week returns `[]` not an error, and
the duplicate-capture refusal pair (mutation-proved, with the explicit note
on why both tests in that pair are needed).

`tests/api/test_canonical_ownership_protections.py` (35/35 combined with
the new tests) — confirms this new `src/ros/` module writes no canonical
dynasty value or alias (the existing seasonal-lane guard already scans
everything under `src/ros/`).

Combined `tests/ros/`: 217 passed / 1 skipped (livedata-marked), zero
regressions. `ruff check .` + `ruff format --check .` clean across the
whole repo (checked BEFORE pushing this time, unlike the prior three units
which each needed a post-push fix cycle). `scripts/check_planning_integrity.py`
— OK.

## Pre-kickoff hardening (owner directive 2026-11-07, Part 7)

Owner: "Prioritize reliable point-in-time collection ... Do not overwrite
historical snapshots with newer information. Use immutable timestamps, model
versions, source provenance, configuration versions, and input hashes."
Data capture only — no forecast, valuation, constant or flag changed.

- **Second pre-event kind, `pregame_late`.** `pregame` is captured inside 30h
  of the week's FIRST kickoff (in practice Wednesday evening), so Sunday and
  Monday games were archived against four-day-old inputs. `pregame_late` is
  captured inside 12h of the week's first SUNDAY kickoff, resolved from the
  same nflverse slate (`game_day_capture.first_sunday_kickoff_utc`: the ET
  calendar date nflverse publishes, so a London 9:30am game is the Sunday
  kickoff and Thursday/Saturday games are not). Own file
  `<team>_pregame_late.json`, append-only — it can never overwrite the early
  snapshot. The score gate cannot protect it (Thursday has scored by Sunday),
  so an unknown Sunday kickoff is refused (exit 1), never guessed — including
  a slate with a Sunday-dated game whose time is blank/"TBD" (it may be the
  earliest Sunday game) or a week row with no readable date. Collected from 2026 week 10 (`PREGAME_LATE_FIRST_WEEK`);
  earlier weeks are "never collected", not lost. The existing 4-hourly timer
  already lands in the window — a half-open 12h window always holds exactly
  three `00/04/08/12/16/20 UTC` firings, pinned against the timer's own
  `OnCalendar` in `tests/ros/test_game_day_pregame_late_capture.py` — so only
  the service's `ExecStart` changed (`--capture-kind pregame --capture-kind
  pregame_late`, one process, exit code 3 > 1 > 0 > 2).
- **Injury state at capture time.** Each run that writes a snapshot records
  `data/game_day/capture_context/<season>/week_<n>/<kind>__<UTC instant>.json`
  (create-once): the injury report as known at the capture instant through
  its canonical owner `src/nfl_data/injury_history.as_known_at` (latest proven
  ESPN fetch at or before it — never a later one), full entries, the ledger's
  `contentSha256` re-verified against them, `snapshotFetchedAt`,
  `observedAgeSeconds`. No ledger / no record → `state: "unavailable"` with a
  reason, never an empty "no injuries" list. Note the injury refresh timer
  runs at :10 past every fourth hour and the capture at :00, so the as-known
  report is typically ~3h50m old; the age is recorded, not hidden.
- **Board identity.** The same file records the canonical board current on the
  host, using the identity the sparse-evidence shadow ledger already uses
  (`newest_live_payload`: payload file sha256, `scrapeTimestamp`, age vs
  `SCORING_SNAPSHOT_MAX_AGE_HOURS`). `usedByEstimates: false` — Game Day point
  estimates come from the projection ensemble, which never reads
  `rankDerivedValue`; this is point-in-time source-ranking context, not an
  input of the forecast.
- **Per-snapshot `provenance`** (new snapshots only; older files keep their
  exact shape): `precedesKickoffUtc` + basis, deployed `codeRevision`,
  `projectionInputs` (label, sources loaded/unavailable, slot source), the
  injury/board summaries, and `captureContext` `{path, sha256}`.
- **A permanent name only ever holds complete JSON.** Snapshot and context
  files are written to a same-directory `.tmp` file, fsynced, then published
  with `os.link` (fails if the name exists → "already captured"); a kill,
  timeout or full disk mid-write leaves at most a stray `.tmp`, never a
  truncated file at the append-only name. Without hard links the fallback is
  exclusive create (still never an overwrite). The readers report a file they
  cannot parse (`scan_snapshots_for_week` / `scan_capture_contexts`) instead
  of raising, so one damaged file blocks neither kind; and each kind runs in
  its own guard, so a crash in one is exit 1 for that kind while the other
  still captures.
- **The context builders are script-only**
  (`src/ros/game_day_capture_context.py`, imported by the capture script
  alone). `game_day_capture.py` is on the request path (Matchup Intel imports
  it), and the injury ledger's fetch helpers reference
  `src/nfl_data/injury_feed.py`; the capture only reads the stored ledger, so
  keeping the import off the served module keeps `espn_injury_feed` honestly
  `SCRIPT_ONLY`.

### Operator verification on the box

Weeks before this deploy (including the unverified weeks 8 and 9) can be
checked for the early kind the same way; `pregame_late` exists from week 10.

```bash
APP_DIR=/home/dynasty/trade-calculator; cd "$APP_DIR"
PY=/home/dynasty/.venvs/trade-calculator/bin/python

# Read-only verdict per pregame kind: exit 0 complete, 3 gap (only once that
# kind's window has CLOSED), 2 not yet due (window early/open), 1 window
# unresolvable. UNREADABLE lines name a file that cannot be parsed back.
"$PY" scripts/capture_game_day_predictions.py --verify --season 2026 --week 10
"$PY" scripts/capture_game_day_predictions.py --verify --season 2026 --week 9 --capture-kind pregame
"$PY" scripts/capture_game_day_predictions.py --verify --season 2026 --week 8 --capture-kind pregame

# The files: one <team>_pregame.json AND one <team>_pregame_late.json per team.
for L in data/game_day/predictions/2026/*/; do
  echo "$L early=$(ls "$L"week_10/*_pregame.json 2>/dev/null | wc -l)"        "late=$(ls "$L"week_10/*_pregame_late.json 2>/dev/null | wc -l)"
done
ls -l data/game_day/capture_context/2026/week_10/

# What the timer did (installed unit name = SERVICE_NAME, default "dynasty").
systemctl list-timers 'dynasty-game-day-capture*'
journalctl -u dynasty-game-day-capture.service --since "-7 days"   | grep -E "window:|wrote|REFUSED|Per-kind"
```

## What's next (not this unit's scope)

1. **A capture script** that gathers real roster data (via
   `src.public_league.snapshot`, the same source `C5-WAR-01`'s future
   consumer wiring will use) and point estimates (from wherever is
   appropriate once `C5-PROJ-B` merges) and calls `record_snapshot` on a
   schedule, before each week locks.
2. **The joint weekly simulator itself** — genuinely the next unit after
   enough weeks of capture exist to validate against, and genuinely needs
   an owner/Integration-level methodology decision first (distribution
   family, sample count, correlation handling) per METHODOLOGY STOP.
3. **xWAR**, once the simulator exists — `src/war/player_impact.py` (#969)
   is already structured to accept it as a sibling function once the
   dependency is real.
4. **Game Day's live probability output**, once the simulator exists.

## Deliberately NOT claimed

The simulator; xWAR; Game Day's probability output; any capture script
(this unit is the store, not the collector); any change to
`src/history/*`, `src/war/*`, or `src/ros/projection_observations.py`
(none imported); any resolution of where point estimates come from.
