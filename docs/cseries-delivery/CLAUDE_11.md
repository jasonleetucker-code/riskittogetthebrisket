# Claude 11 — C5 Seasonal Intelligence — Delivery Log

**Lane:** 3 — Season / Scoring / Projections; also named directly as **Claude 11 — C5**
under the POST-V1 C-Series mass-build campaign (`docs/EXECUTION_PLAN.md` §0, owner
directive 2026-08-20)
**Branches:** `claude/cseries-seasonal-intelligence-efz837` (V1-53, PR #964),
`claude/c5-proj-a-source-census` (C5-PROJ-A)
**Started:** 2026-08-20

## 0.1 UPDATE 2026-08-20 (same day) — the freeze that motivated §0 below has partially lifted

§0 was written against `docs/EXECUTION_PLAN.md` as it read at session start: V1-required
work only, full C5 (projection ensemble, Game Day, WAR/VORP, player fit/college
translation) explicitly POST-V1 DEFERRED with no implementation authorized. **That has
changed.** A fresh owner directive recorded the same day (`docs/EXECUTION_PLAN.md` "POST-V1
C-SERIES MASS-BUILD CAMPAIGN — AUTHORIZED BY THE OWNER, 2026-08-20") now names **"Claude 11
— C5: C5 Seasonal Intelligence"** directly as an authorized isolated-branch implementation
lane. §0's scope table stays correct on the **V1 REQUIRED denominator** — nothing there
changed, and the four V1-required rows (V1-49/51/52/53) are exactly as described. What
changed is that the REST of the C5 family (§0's "POST-V1 DEFERRED" column) is now
authorized for real implementation on isolated branches, **not to be merged to `main` by
this session** — Claude 5 (Integration Authority) is the sole merge authority. So: build the
full C5 family for real, hand off bounded PRs, never merge them myself, and never claim a
V1 row `VERIFIED` (only Claude 5 edits that document).

## 0. Scope correction — read this first (superseded in part by §0.1 above; kept for the
record of what was true at session start)

The assignment brief for this session names the full C5 family as ownable
work: the multi-source projection ensemble, Game Day, prediction archive,
playoff-probability consolidation, power-ranking consolidation, WAR/VORP,
special-teams integration, BDVM completion, league-specific player fit and
college translation.

`CLAUDE.md` states that repository governance overrides default behavior,
and names `docs/EXECUTION_PLAN.md` as the only record that authorizes
implementation work. That file (§0, reconciled 2026-08-18) authorizes
**only the V1 REQUIRED denominator** in
`docs/VERSION_1_COMPLETION_CONTRACT.md` §3, not the C-Series census as a
whole. Cross-checking the brief's C5 scope against that denominator (§3.4)
and the explicit deferral list (§4.1, §4.2, owner decision 2026-08-18):

| brief item | actual authorization today |
|---|---|
| Multi-source projection ensemble (`C5-U1`, `C5-PROJ-A…F`) | **POST-V1 DEFERRED** — named explicitly in §4.1 |
| Game Day Command Center + prediction archive (`C5-GD-01/02`) | **POST-V1 DEFERRED** — §4.1 |
| Advanced WAR/VORP (`C5-WAR-01`) | **POST-V1 DEFERRED** — §4.1 |
| League-specific player fit / college translation (`C5-FIT-01`) | **POST-V1 DEFERRED, lane continuation** — §4.2 (L3 row) |
| BDVM completion work | `C5-BDVM-01` is **VERIFIED, complete for declared scope** (V1-54) — nothing further is V1-required |
| Individual special-teams scoring (`C5-ST-01`) | **V1-49, V1-required** |
| One playoff-probability engine (`C5-PLAY-01`) | **V1-51, V1-required** |
| One weekly power-rankings engine (`C5-POW-01`) | **V1-52, V1-required** |
| Redraft/ROS lane stays separate from dynasty valuation (`C5-ROS-01`) | **V1-53, V1-required** |

So the actually-authorized C5 denominator today is four rows — V1-49,
V1-51, V1-52, V1-53 — not the nine-unit family the brief describes. This
is not a refusal to do the broader work; it is real, owner-approved scope
recorded in `docs/VERSION_1_COMPLETION_CONTRACT.md` §4.1/§4.2, deliberately
scheduled after V1. Building it now would be exactly the "opportunistic
feature lane" the feature-freeze conditions (retained in EXECUTION_PLAN §0
even under the V1-sprint supersession) forbid, and would risk building a
seasonal ensemble against a Team Strength/scoring foundation that is still
moving.

**Absolute invariant restated and held:** seasonal evidence never directly
modifies canonical dynasty `rankDerivedValue`. See §3 below — this session's
one shipped change is a repair to the guard that proves exactly that.

## 1. Status of the four authorized rows, as found

| row | status found | disposition this session |
|---|---|---|
| V1-49 (special-teams scoring) | Already delivered — `#802` (commits `fb3078e7`/`013ee6fb`/`53dd1a5f`) merged to `main` and present on this branch. `tests/nfl_data/test_individual_special_teams.py` 28/28 green. SAF already in `POSITION_ALIASES`/`_IDP_POSITIONS`; blocked-kick scoring (`idp_blk_kick`, IDP-scoped) implemented in `src/nfl_data/realized_points.py`. | No action — verified only |
| V1-51 (one playoff-probability engine) | Already delivered — PR `#956` (`claude/v1-51-championship-truthful-sims`) merged to `main` (`4157adfe`) and present on this branch. `src/ros/championship.py`'s `if not distributions:` branch now returns `n_simulations: 0` + `unsimulable`, matching its sibling. `tests/ros/test_probability_surface_agreement.py` 12/12 green. `docs/WORK_CLAIMS.md`'s row for this still reads `open` — stale bookkeeping, not a live conflict; not touched here since it is another session's claim to close. | No action — verified only |
| V1-52 (one weekly power-rankings engine) | **Genuinely open, but blocked.** Two live engines (`src/public_league/power.py` "v1", `src/ros/power_v2.py` "v2") measurably disagree (10 teams vs 12, mean |Δrank| 2.8, max 7 — `W30-F003`, documented in `docs/master-site-audit/FORMULA_INVENTORY.md`). An owner-approved methodology spec exists (`docs/CANONICAL_WEEKLY_POWER_RANKINGS_SPEC.md`), but it explicitly states neither existing engine is final, and the unit's declared **hard** dependency `C2-U4` (Canonical Team Strength, `src/ros/team_strength.py`) is `IN PROGRESS` (V1-31), not closed. Per `C_SERIES_EXECUTION_MAP.md` §0.2, deps are hard — consolidating onto a moving Team Strength formula would be "tuning a product around a temporary formula," which the calibration policy's dependency principle (§8) forbids. | **Stopped, documented, not implemented.** See §2 |
| V1-53 (redraft/ROS lane separation) | Structurally already held (zero live writes into any `src/ros/*.py` module of `rankDerivedValue` or its aliases; `tests/ros/test_isolation.py` already proves ROS imports cannot mutate `_RANKING_SOURCES`/etc.), but had **no dedicated enforcement of the three canonical-value aliases** (`overall`, `finalAdjusted`, `displayValue`) — the existing repo-wide write scan in `tests/api/test_canonical_ownership_protections.py` matched only `rankDerivedValue` by name. | **Repaired this session.** See §3 |

## 2. V1-52 — stopped, per the "owner decision not already ratified" rule

The brief's own instruction is to stop a sub-unit when weights/calibration
require an owner decision not already ratified, document measured
alternatives, and continue other C5 work. That is the situation here,
plus a harder blocker: the unit's *dependency* (not merely a weight) is
open.

**Measured today:**
- v1 (`src/public_league/power.py:44-49,81-84,141`): `0.50·PPG%ile (career-cumulative, cross-season) + 0.25·recent3%ile + 0.25·all-play(this week only)`. Served eagerly at `/api/public/league` under `"power"`; both `frontend/app/league/sections/power.jsx` and the `overview.jsx` "Power rank #1" widget read it, the latter unconditionally regardless of which engine the Power tab shows.
- v2 (`src/ros/power_v2.py:92-101`): `0.41·ROS-strength%ile + 0.18·ppg%ile + 0.12·recent%ile + 0.10·wl_record%ile + 0.08·all_play%ile + 0.05·streak + 0.04·schedule_adjusted + 0.02·luck_regression`, reading `data/ros/team_strength/latest.json`. Served lazily at `/api/public/league/rosPower`, toggled via `settings.useRosPowerRankings`.
- `docs/CANONICAL_WEEKLY_POWER_RANKINGS_SPEC.md` (owner-approved, 2026-08-12) names concrete repair directives for whichever engine is retired into: exclude cross-season PPG accumulation (v1's defect), all-play must be season/rolling not last-week-only (v1's defect), exclude future schedule from Power (contradicts v2's `schedule_adjusted` term), no double-counting streak/luck against all-play/recent, missing inputs renormalize rather than zero. It explicitly does not select a winner between v1 and v2.
- `C2-U4` / `C2-STR-01` (`src/ros/team_strength.py`) — the ROS-strength term v2 already depends on, and the term the spec's repaired all-play/recent components would also plausibly route through — is `IN PROGRESS` per `V1-31` (owned by Lane 1, "#914 builds the owner"). It is a declared **hard** dependency of `C5-U4` in `docs/C_SERIES_EXECUTION_MAP.md` §7.

**Why this stays undone rather than picked between the two existing engines:**
Retiring one engine into a "canonical" owner today would freeze a formula
built on a Team Strength module Lane 1 is still changing — precisely the
anti-pattern the calibration policy names ("C7 may not begin against a
provisional C2/C3 formula, because tuning a product around a temporary
formula is how the formula becomes permanent," applied here one phase
down). It would also require resolving the spec's repair directives
against v1/v2's existing double-counting risk, which is itself a
calibration decision, not a mechanical pick.

**Left for the next session that owns `C2-U4`, or for this session once
`C2-U4` closes:** consolidate `C5-POW-01` onto `src/ros/team_strength.py`'s
output per `docs/CANONICAL_WEEKLY_POWER_RANKINGS_SPEC.md`, retiring
whichever of `power.py`/`power_v2.py` is not kept, and repointing both
`overview.jsx`'s badge and the Power tab at the single result.

## 3. V1-53 — repaired: canonical-alias write guard widened to cover the seasonal lane

**Defect found:** `tests/api/test_canonical_ownership_protections.py`'s
`_CANONICAL_WRITE` regex — the sole repo-wide guard against a non-canonical
module writing dynasty value — matched only `rankDerivedValue` itself.
`test_the_aliases_are_intentional_and_pinned` (same file) already proves
`values.overall` / `values.finalAdjusted` / `values.displayValue` equal
`rankDerivedValue` on every row of a real capture — they are the same
canonical quantity under three names — but a module writing one of those
three aliases directly, instead of `rankDerivedValue` by name, passed the
write-ownership gate silently. That is precisely the shape a seasonal-lane
leak would take under the source-domain-boundary invariant this row exists
to guard.

**Repair:** widened `_CANONICAL_WRITE` to also match assignment to the
three aliases (dict-key and attribute forms, in Python or JS), updated the
vacuousness test to assert both the aliases are caught and an equality
check on an alias is not mistaken for a write, and added
`test_no_seasonal_lane_module_assigns_a_canonical_alias` — a dedicated,
narrowly-scoped scan of `src/ros/**/*.py` naming `V1-53`/`C5-ROS-01` and
`docs/REDRAFT_ROS_INTELLIGENCE_SPEC.md` §3 directly, so a future failure
here points at the seasonal lane specifically rather than only at the
repo-wide generic assertion.

**False-positive check:** a repo-wide scan for `overall`/`finalAdjusted`/
`displayValue` assignment across every tracked production `.py`/`.js`/
`.jsx` file (outside `tests/`/`docs/`/`scripts/`/`frontend/__tests__/`)
found exactly one writer for each — `src/api/data_contract.py`, the
already-approved canonical producer. Widening the pattern introduces zero
false positives anywhere in the tree.

**Mutation-proved:** appended a synthetic `row["displayValue"] = ...`
write to a scratch copy of `src/ros/team_strength.py` and confirmed both
`test_only_approved_modules_assign_the_canonical_value_field` and the new
`test_no_seasonal_lane_module_assigns_a_canonical_alias` go RED, each
naming `src/ros/team_strength.py` in the failure message; restoring the
file returns both to green. The mutation was not committed.

**Verification run:** `tests/api/test_canonical_ownership_protections.py`
20/20 green; `tests/ros/` 202 passed / 1 skipped (livedata-marked, not
excluded for a methodology reason); `tests/api/` (excluding `livedata`)
2088 passed / 18 skipped / 196 deselected, 0 failed.

**Deliberately NOT claiming:** any change to `rankDerivedValue`,
`_RANKING_SOURCES`, `src/ros/team_strength.py`'s formula, `C5-POW-01`,
`C5-PLAY-01`, `C5-ST-01` (all verified-only, see §1), the full projection
ensemble, Game Day, WAR/VORP, BDVM, player fit or college translation
(all POST-V1 DEFERRED, see §0), or any C2+ roster-math unit.

**File touched:** `tests/api/test_canonical_ownership_protections.py` only.

## 4. Claim

Registered in `docs/WORK_CLAIMS.md` as V1-53 / C5-ROS-01.

## 5. Next steps for a continuing session in this lane

1. Watch `C2-U4` (`src/ros/team_strength.py`, owned by Lane 1 / V1-31). Once
   it closes, `V1-52` becomes unblocked — pick up `docs/CANONICAL_WEEKLY_POWER_RANKINGS_SPEC.md`
   and consolidate `power.py`/`power_v2.py` per §2 above.
2. `V1-49` and `V1-51` need no further Lane 3 work; if `docs/WORK_CLAIMS.md`'s
   V1-51 row is still marked `open` when picked up again, that is a
   bookkeeping close-out for whoever owns that claim, not new implementation.
3. ~~Do not begin the POST-V1 items in §0's table without a fresh owner
   decision recorded in `docs/EXECUTION_PLAN.md` §0, per that file's own
   authorization rule.~~ **Superseded by §0.1 — that fresh owner decision
   landed the same day.** See §6 onward below.

## 6. C5-PROJ-A — projection-source capability / access / lineage census

**Branch:** `claude/c5-proj-a-source-census` (separate branch/PR from V1-53's, since
this is a genuinely distinct cluster — the first sub-unit of the multi-source
projection ensemble `C5-U1`, now authorized under §0.1).

Full record: `docs/projections/C5_PROJ_A_SOURCE_CAPABILITY_CENSUS.md`. Summary:

- **Delivered:** `config/projections/source_capability_census.json` (data) +
  `src/ros/projection_source_census.py` (validating loader, closed-vocabulary
  enforcement, query helpers) + `tests/ros/test_projection_source_census.py` (17
  tests: structural validation with non-vacuousness proofs, plus a `TestMeasuredFacts`
  class pinning the actual findings).
- **Key finding:** two of the plan's target sources (Mike Clay/ESPN, The IDP Show)
  already have real, live `PROJECTION_MODEL` implementations — inside `src/bdvm/`,
  not the ROS/seasonal tree. C5-PROJ-B should reconcile with BDVM's existing
  `ProjectionRecord` schema rather than building a second one.
- **Key finding:** five currently-wired ROS sources (three FantasyPros, two
  DraftSharks) are rankings, not projections, despite one of them
  (`draftSharksRosSf`) being flagged `is_projection_source: True` in the live
  `ROS_SOURCES` registry — a discrepancy recorded, not repaired (out of this
  foundational unit's scope; `ROS_SOURCES` is live and consumed elsewhere).
- **Key finding:** CBS Sports Fantasy, NFL Fantasy, and FantasyPros' actual
  projections page are genuinely greenfield — zero existing code. No source URL was
  invented for any of them; recording "no access path yet" is the correct state per
  the plan's own "record before automation" instruction.
- **Key finding:** DFS and sportsbook/player-prop discovery lanes were actively
  searched (not merely left unexamined) and confirmed to have zero existing
  infrastructure in this repo.
- **One-writer boundary respected:** both DraftSharks census entries are stamped
  `acquisitionOwnerLane: "Claude 8"` per `docs/EXECUTION_PLAN.md` §0's explicit
  assignment of Draft Sharks cross-position/IDP Show/Footballguys acquisition to
  Claude 8 — no acquisition code was written for either.
- **Verification:** `tests/ros/test_projection_source_census.py` 17/17;
  `tests/ros/` full suite 219 passed / 1 skipped, zero regressions;
  `scripts/check_planning_integrity.py` OK.
- **Deliberately NOT claimed:** any fetcher/parser/automation for any censused
  source; any change to `ROS_SOURCES`; C5-PROJ-B through F.

## 7. Assessed and deferred: Game Day (C5-GD-01) and the xWAR half of C5-WAR-01

Both read in full against their governing specs (`docs/GAME_DAY_PROBABILITY_SPEC.md`,
`docs/PLAYER_IMPACT_WAR_MVP_SPEC.md`) before deciding not to attempt a rushed partial
build this session:

- **Game Day** needs ONE joint league-wide weekly-score Monte Carlo simulation
  feeding both Win-Matchup% and Beat-Median%, explicitly forbids a second
  matchup/projection model, and carries a 14-item acceptance list including a
  calibration archive that does not exist yet. A legitimate low-cost path exists
  (reuse BDVM's per-player mu/sigma projection primitives — not its dynasty value
  output — as the weekly score-distribution input, since BDVM already has real
  Clay/IDP Show projections with in-season blending), but the joint simulation +
  lineup integration + live-state updating + calibration archive is genuinely
  multi-session scope. Shipping a partial version would violate "implement working
  capability, not scaffolding or stubs."
- **xWAR** (the fourth of `C5-WAR-01`'s four metrics) needs "the same archived
  no-lookahead league-week scoring distribution/simulation" — i.e. the same
  dependency as Game Day. The other three (Realized Lineup VORP, Actual WAR, Wins
  Above Bench + Game Changer Points) are fully deterministic — no simulation
  needed, only realized scores, the replacement-level owner, and the canonical
  best-ball solver, all of which already exist. See §8.

## 8. Found: an existing but spec-noncompliant VORP calculation in `src/public_league/awards.py`

`src/public_league/awards.py:1441-1444` already computes a per-position playoff VORP
(`vorp = max(0.0, r["starterPoints"] - replacement_per_game * games)`), consuming the
canonical `src/scoring/replacement_level.py::replacement_per_game` (the correct owner
per `scripts/replacement_census.py`'s declared OWNER row `B`). Two measured
discrepancies against the binding spec (`docs/PLAYER_IMPACT_WAR_MVP_SPEC.md` §2, §11):

1. **Floors at 0.0.** The spec is explicit: "Negative VORP is valid." This
   implementation cannot express a below-replacement player.
2. **Season-aggregate, not per-week.** The spec defines `weeklyVORP` per
   best-ball-counted player-week, summed to `seasonVORP`. This implementation uses
   season totals divided by games started against a single season-level
   replacement figure — a different (simpler, less correct under bye weeks /
   variable per-week replacement) computation.

This is C9-AWARD scope (not mine — C5-WAR-01 is the underlying metric, C9-AWARD-02
is POST-V1 DEFERRED per contract §4.1 and belongs to Claude 13's C9 lane), so not
repaired here. Recorded because whoever builds the real `C5-WAR-01` canonical
Player Impact module (§7) will retire this inline calculation into a call to it, per
ONE CONCEPT ONE CANONICAL OWNER — and because Claude 13 should not independently
"fix" the floor/aggregation without knowing the real owner is coming.

## 9. Next steps for a continuing session in this lane

1. `C5-PROJ-B` (canonical projection-stat schema + exact-league rescoring) — build
   against BDVM's `ProjectionRecord`, do not re-derive it. Start from the two LIVE
   sources this census found.
2. `C5-WAR-01` deterministic core (Realized VORP, Actual WAR, WAB, Game Changer) —
   spec'd, dependencies exist (`src/scoring/replacement_level.py`,
   `src/ros/lineup.py::solve_optimal_assignment`, closed C1-U4 ledger for
   provenance). xWAR itself waits on Game Day's joint simulation.
3. `C5-FIT-01` — the scoring-fit half (decisions 44/46) is **already substantially
   implemented** at `src/consensus_edge/scoring_fit.py` +
   `src/league_intel/scoring_fit.py` + `src/league_intel/reception_fit.py`, consumed
   by `fair_value.py` — the manifest's "ABSENT" status at this row is stale. Do not
   build a third parallel fit engine (decision 46 explicitly forbids double-counting
   these as independent votes). The genuinely absent half is **college translation**
   (decision 45): `src/bdvm/service.py:519` hardcodes `college_score=0.0` with a
   "no college feed yet" comment; no college-stat ingestion exists anywhere. Building
   it needs a college stats source (distinct from Claude 8's named vendor list — likely
   an nflverse-adjacent or CFBD-style feed, not yet identified) and, per decision 45,
   must not "promote" the signal until historical drafted-cohort transfer is validated
   without temporal leakage. Recommend flagging this finding to Integration so the
   manifest's `C5-FIT-01` status can be corrected from ABSENT to PARTIAL.
4. Watch `C2-U4` for `V1-52` (unchanged from §5 above).
5. Continue picking dependency-ready C5 units per §0.1's authorization; do not merge
   any PR — hand green batches to Claude 5.

## 10. C5-WAR-01 — deterministic core (Realized VORP, Actual WAR, WAB, Game Changer)

**Branch:** `claude/c5-war-01-deterministic-core` (separate branch/PR — distinct cluster
from both V1-53 and C5-PROJ-A).

Full record: `docs/player-impact/C5_WAR_01_DETERMINISTIC_CORE.md`. Summary:

- **Delivered:** `src/war/standings.py` (pure H2H/median credit primitives) +
  `src/war/player_impact.py` (Realized Lineup VORP, Actual WAR, Wins Above Bench,
  Game Changer Points — four of the spec's five metrics) + `tests/war/` (40 tests
  directly pinning `docs/PLAYER_IMPACT_WAR_MVP_SPEC.md` §12's own validation list).
- **xWAR deliberately excluded** — needs the same joint weekly league-score
  simulation Game Day needs (assessed and deferred in §7 above); building a
  standalone one for xWAR alone would be the "second matchup model" the Game Day
  spec forbids.
- **No duplicate math:** consumes `src/scoring/replacement_level.py::replacement_per_game`
  (the declared owner) and `src/ros/lineup.py::assign_lineup` (the C2-U1 canonical
  solver) as-is. `tests/lineup/test_single_owner.py` 16/16 confirms no second
  assignment engine was introduced.
- **Key correctness decision:** team scores are summed from real per-player points,
  never `LineupAssignment.score` (which floors a negative objective via the
  solver's live health-penalty path — wrong for an already-played historical
  week).
- **Key correctness decision:** the counterfactual median is genuinely
  recalculated from the counterfactual score set on every call (spec §3's
  "Mandatory" instruction), with a test specifically constructed to diverge from
  a stale-median answer so it cannot pass by accident.
- **Found, not repaired (C9-AWARD scope, Claude 13's lane):**
  `src/public_league/awards.py:1441-1444` has an existing VORP calculation that
  floors at 0.0 and is season- rather than week-aggregate, both diverging from
  the binding spec. Recorded so Claude 13 retires it into a call to this owner
  rather than independently "fixing" it in place.
- **Labelled PRIOR, not verified:** median-game tie/odd-even handling (no network
  egress in this environment to check against live Sleeper behavior).
- **Verification:** `tests/war/` 40/40; combined with `tests/lineup/` +
  `tests/scoring/` 180/180, zero regressions; `ruff check .` + `ruff format --check .`
  clean across the whole repo.
- **Deliberately NOT claimed:** xWAR; consumer wiring to real Sleeper snapshot
  data; the spec's §10 immutable historical evidence store; the `awards.py` VORP
  repair; MVP/OPOY/DPOY methodology (spec §7/§8); any change to
  `replacement_level.py` or `lineup.py`.

## 11. C5-PROJ-B — canonical projection-stat schema + exact-league rescoring

**Branch:** `claude/c5-proj-b-canonical-schema`, branched from `claude/c5-proj-a-source-census`
(a real dependency, not a convenience — this unit imports the census module `C5-PROJ-A`
introduced, so it cannot exist on a branch that doesn't have it).

Full record: `docs/projections/C5_PROJ_B_CANONICAL_SCHEMA.md`. Summary:

- **Delivered:** `src/ros/projection_observations.py` — wraps BDVM's existing
  `ProjectionRecord`/`resolve_fpg` (the two LIVE sources `C5-PROJ-A` found: Mike
  Clay/ESPN, The IDP Show) into the seasonal ensemble's plan-§4 observation contract.
  No BDVM file touched; `resolve_fpg` does the actual exact-league rescoring, reusing
  the same production scoring engine (`compute_weekly_points`) that scores realized
  history.
- **Structural enforcement, not just documentation:** a `ProjectionObservation`
  cannot be built for a source missing from the `C5-PROJ-A` census (raises) or for a
  `RANKINGS_ONLY`-censused source (refuses — would otherwise manufacture a projection
  a source never published). Proxy rows (BDVM's own reconstructed-baseline estimates)
  are excluded by default and stay labelled when explicitly included.
- **Key finding for future adapters:** a projection's raw `stat_line` uses nflverse
  COLUMN names (`receptions`/`receiving_yards`), not Sleeper SCORING-KEY names
  (`rec`/`rec_yd`) — similar enough to confuse, and a stat line built with the wrong
  vocabulary silently scores 0.0 rather than raising. Caught by this unit's own tests
  before it could reach `C5-PROJ-C`.
- **Verification:** `tests/ros/test_projection_observations.py` 12/12 (including a
  real snapshot round-trip via `write_snapshot`→`load_and_rescore_source`);
  `tests/api/test_canonical_ownership_protections.py` 20/20 (seasonal-lane write
  guard); `tests/bdvm/test_engine_parity.py` 7/7 (BDVM's frozen reference fixture
  untouched); combined `tests/ros/`+`tests/bdvm/` 550/1-skipped, zero regressions;
  `ruff check .` + `ruff format --check .` clean.
- **Deliberately NOT claimed:** any change to `src/bdvm/*`; `C5-PROJ-C`/`C5-PROJ-D`
  ensemble aggregation; any new fetcher/acquisition code; DFS/betting-market
  discovery lanes (still `GREENFIELD`).

## 12. Session status and open PRs (as of this entry)

| PR | branch | unit | status |
|---|---|---|---|
| #964 | `claude/cseries-seasonal-intelligence-efz837` | V1-53 | **merged to `main`** |
| #966 | `claude/c5-proj-a-source-census` | C5-PROJ-A | open, CI green |
| #969 | `claude/c5-war-01-deterministic-core` | C5-WAR-01 deterministic core | open, CI green |
| #973 | `claude/c5-proj-b-canonical-schema` | C5-PROJ-B | open, based on #966 (base branch, not `main`) |

None merged by this session except via Integration (#964) — Claude 5 (Integration
Authority) is the sole merge authority per `docs/EXECUTION_PLAN.md` §0. `#966` should
merge before or together with `claude/c5-proj-b-canonical-schema`'s PR, since the
latter is branched from and depends on it.
