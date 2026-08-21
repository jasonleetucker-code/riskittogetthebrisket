# Claude 11 — C5 Seasonal Intelligence — Delivery Log

**Lane:** 3 — Season / Scoring / Projections (per `docs/EXECUTION_PLAN.md` §0)
**Branch:** `claude/cseries-seasonal-intelligence-efz837`
**Started:** 2026-08-20

## 0. Scope correction — read this first

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
3. Do not begin the POST-V1 items in §0's table without a fresh owner
   decision recorded in `docs/EXECUTION_PLAN.md` §0, per that file's own
   authorization rule.

## 6. Correction, 2026-08-21 — §1's V1-49 and V1-52 rows are stale

Appended rather than rewritten, so the reasoning trail stays legible — this
section supersedes §1's V1-49 and V1-52 rows for anyone reading them today.

**V1-49.** §1's row described V1-49 as "already delivered" with SAF
"already in `POSITION_ALIASES`/`_IDP_POSITIONS`" — that was true of `#802`'s
tests, but **not** true of the engine underneath them at the time this log
was written: `#915` (merged `7446b8b31`, 2026-08-20, after this log's
"Started" date) found that `SAF` was in **neither** table, so every safety's
IDP scoring was silently skipped — a well-formed `0.000`, 1,429 player-weeks,
10,842.88 points never awarded on the live `dynasty_main` card. `#915` fixed
the engine (added `SAF` to `POSITION_ALIASES`, derived `_IDP_POSITIONS` from
it rather than hand-maintaining it), fixed blocked-kick scoring (was wrongly
marked `UNSCORABLE`), and fixed a separate asymmetric season-card resolver.
All three are confirmed correct on `main` today, with passing coverage
(`tests/nfl_data/test_individual_special_teams.py`,
`tests/nfl_data/test_idp_position_coverage.py`,
`tests/league_comparison/test_season_card_symmetry.py`). Individual-ST-vs-DST
separation (`is_host_player_entry`) is also confirmed correct and well-tested.

**What is NOT yet closed, and is the actual remaining gate**:
`docs/VERSION_1_COMPLETION_CONTRACT.md` §3.4 still records V1-49 as
`IN PROGRESS` at L2, and that is accurate — the gate is the
`host_native_scoring` challenger-path promotion (`#915`'s own "Promotion
gate" table), with 4 of 10 items explicitly `OPEN — needs prod`: the PBP
artifact isn't yet built+scheduled in production, BDVM hasn't been rerun
against the challenger, `league_comparison` hasn't been rerun against
challenger scoring, and historical backtests haven't been rerun. The flag
itself (`host_native_scoring`, `src/api/feature_flags.py`) stays default
`OFF`. This is **PRODUCTION_ONLY** — none of the four gate items are
reachable from a sandbox session, so no further Lane-3 sandbox work can
close V1-49; it needs Integration/Claude 5 to run the four items against a
real deploy.

**A separate, real-but-latent architectural finding, investigated and
deliberately NOT repaired this session**: `POSITION_ALIASES`
(`src/utils/name_clean.py`) is documented as the sole canonical
position-normalization owner, and `#915` correctly derived
`realized_points._IDP_POSITIONS` from it — but three consumer modules still
hand-maintain their own position tables rather than deriving from it
(`league_comparison/scoring_engine.py::_canonical_position`,
`league_intel/replacement.py::_BASE_POSITION_ALIASES`, and
`ros/lineup.py::_LINEUP_FAMILY` — the last is the canonical lineup/slot
owner per `CLAUDE.md`'s C2-U1 section, and its own code comment records the
exact same defect class already firing once before with `MLB`, fixed
2026-08-19). Checked empirically before deciding whether to fix: the live
exported board (`exports/latest/dynasty_data_2026-08-21.json`,
`sleeper.positions`, 940 entries) contains **zero** `"SAF"`-spelled
positions — Sleeper's own player database already reports safeties as
`"S"`/`"DB"`, never nflverse's 2025-unified `"SAF"` spelling, and every
consumer of these three tables (`roster_intel/marginal.py`,
`api/gameplan.py`, `roster_intel/profiles.py`, `roster_intel/targets.py`,
and the lineup optimizer itself) reads `RosterPlayer.position`, which is
sourced from that same Sleeper-derived board field, not from raw nflverse
stat rows. So unlike the scoring-engine SAF gap `#915` fixed, this one does
not currently fire on real data — the same "latent, not firing" status the
`MLB` fix's own regression test documents for that earlier defect. Per this
session's explicit instruction not to repair unreachable theoretical
defects, this was investigated to a firm conclusion and **not** coded —
recorded here as a real, precisely-scoped risk for whoever next touches
position normalization (it would fire the instant any of these three
tables' input ever carries a raw nflverse-spelled position instead of a
Sleeper-derived one), not as an open TODO for this lane to chase further.

**V1-52.** §1's row described V1-52 as blocked on `C2-U4` (Team Strength)
being open. That dependency has since closed and the unit proceeded without
waiting further: `#979` (merged) shipped the canonical `power_v2` engine
with both lenses reachable; `#996` and `#1009` (both open, unmerged, frozen
for Integration as of this correction) complete the retirement of the legacy
`power.py` engine. `docs/VERSION_1_COMPLETION_CONTRACT.md` §3.4 correctly
shows `IN PROGRESS`, matching the live PR queue. See
`docs/power/V1_52_L2_VERIFICATION_RECIPE.md` for the checklist Integration
needs to run after merging `#996` → `#1009`; no further V1-52 implementation
is authorized in this lane unless that verification surfaces a causal gap.

