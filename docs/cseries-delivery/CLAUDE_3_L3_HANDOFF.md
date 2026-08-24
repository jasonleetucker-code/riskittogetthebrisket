# Claude 3 → Claude 5 — L3 lane (Season / Scoring / Projections) handoff

2026-08-24. Dispatch main `131abf9f9`; work branched from `fa45be6bc`.
Standing tally at dispatch: **88 / 136 VERIFIED (64.7%)**.

Every L3 row below is in exactly one terminal state. Nothing is left "in
progress". **I promoted nothing and merged nothing** — §3 of the completion
contract is Integration's alone.

---

## 1. Lane census — all 8 rows

Lane membership derived from the completion contract's own `lane` column, which
is the only live row→lane mapping: `docs/claude-dispatch/ASSIGNMENTS.json` and
`LANE_STATUS.json` are both `RETIRED_DERIVED_SNAPSHOT` (2026-08-22) and forbid
being quoted as authority.

| row | title | ledger status | terminal state |
|---|---|---|---|
| V1-48 | Realized scoring correctness | VERIFIED | — |
| V1-49 | Individual special-teams scoring | IMPLEMENTED_UNVERIFIED | **READY_FOR_PROD_VERIFICATION** |
| V1-50 | ROS projections honest | VERIFIED | — |
| V1-51 | One playoff-probability engine | VERIFIED | — (not reopened) |
| V1-52 | One weekly power-rankings engine | IMPLEMENTED_UNVERIFIED | **READY_FOR_INTEGRATION** → then **STATE_BLOCKED** |
| V1-53 | Seasonal lane stays separate | VERIFIED | — |
| V1-54 | BDVM stays a separate concept | VERIFIED | — |
| V1-95 | Awards don't exist before games | VERIFIED | — |

Six of eight already VERIFIED. **The two open rows had no named code work
outstanding in the contract** — the dispatch's own expectation was that both
were state-blocked. I was asked to confirm that rather than assume it.

**One of the two confirmations failed.** V1-52 had a live implementation defect
behind the missing observation. That is the main finding of this session.

---

## 2. Rows ready for integration — three PRs, none self-merged

| PR | branch | head | row |
|---|---|---|---|
| **#1081** | `claude/v1-52-recent-season-binding` | `697f862eb` | V1-52 |
| **#1083** | `claude/v1-49-pbp-schema-integrity` | `99f7ec54b` | V1-49 (prerequisite) |
| **#1084** | `claude/v1-49-coverage-host-path` | `9ff5b057b` | V1-49 (prerequisite) |

All three branch from `fa45be6bc`. #1083 and #1084 both touch
`src/nfl_data/` but **different files** (`pbp_weekly.py` vs
`scoring_coverage.py`) and do not conflict with each other.

### PR #1081 — V1-52 `recent` / `all_play` season binding

**This is the refutation of V1-52's state-blocked premise.**

`build_section` gated the recent-form buffer on `season is seasons_sorted[-1]`,
but the accumulation loop `continue`s past a scoreless season *above* that
line. `seasons_sorted[-1]` is the newest season **in the snapshot**, not the
newest **with scores** — and those diverge in exactly one situation, the one
production is in: a scoreless current season after prior scored seasons, i.e.
every preseason.

So the guard never fired for any season, `last_season_recent` stayed empty for
every owner, `_score_state` read `recent = 0.0` for all, and a percentile over
an all-equal list is 0.5.

Same family as the already-merged #1032 (`ppg`/`wl_record`) and #1059
(`streak`/`luck_regression`), on the one accumulator neither touched.

**L2, measured on the live board** (`GET /api/public/league/rosPower?lens=results_only`,
real 12-owner league, 2026-08-24):

- **12 / 12** headline rows carried `recent = 0.5`, `recentAvg = 0.0`
- **108 / 108** trend rows (9 weeks × 12 owners) the same
- active weights sum `0.5500` → `recent` is **21.82%** of every published score
- **10.91 points of unmeasured constant in every `powerScore`**
- UI rendered `recentAvg` as a literal `"0.0"` as though observed

Rank *order* was undisturbed (a shared constant shifts all owners equally) —
which is why it survived three prior reviews of this file.

**Mutation:** restoring the retired binding at both sites → RED with the
predicted signature (`assert {0.5} != {0.5}`). Restored → 16/16.
**Regression:** `tests/ros/` + `tests/public_league/` **671 passed, 2 skipped**.

Also corrected two passages in `docs/power/V1_52_PPG_SEASON_SCOPING.md` that
cited the defective gate as *proof* `recentAvg` was "already correctly
season-scoped" and "remains correct" — append-only, originals left standing.

**Branch overlap, reported not resolved:** `check_work_claims.py` flags
`origin/claude/v1-52-power-lenses` as touching `src/ros/power_v2.py`, and a
trial merge conflicts. It has **no open PR** (checked against all 28 open), its
named work is already on `main` via #996/#1009, and **it does not fix this
defect** — the gate is unchanged on both sides of its diff. Treated as stale;
reconciliation is your call.

### PR #1083 — V1-49: PBP artifact schema version enforced

`PBP_WEEKLY_SCHEMA_VERSION` was **not** bumped when `kick_ret_td` joined
`PBP_SUPPLEMENT_KEYS` (#1031). Every artifact on disk predated the key;
`--skip-existing` compares exactly that constant and the weekly timer runs
`--skip-existing`, so it would **never** have rebuilt them; and
`load_pbp_weekly` had no version check at all, unlike `reception_depth` which
already refuses a mismatched schema.

**The failure was a fabricated zero, not an unknown** — `covers()` is
week-level, so a stale-but-complete week still reports covered, the supplement
is a Mapping merely lacking the key, `compute_weekly_points` takes its
`isinstance(supplement, Mapping)` branch, and `unscored` stays empty.
`kick_ret_td` scores 0 and nothing says so. I traced the full chain and
confirmed the repair inverts it: `None` routes the player-week through the
`else` branch where every PBP-only rule the card pays is reported `unscored`.

**Why it had to land before the production run:** a production measurement
cannot distinguish a correct zero from a silently-unreachable one. Measuring
against stale artifacts would have produced a clean-looking wrong result.

Adds a second guard refusing an artifact whose recorded `statKeys` lack an
expected key — that is the check that would have caught *this* defect, since
the key set moved *without* a version bump. `statKeys` was already written and
never read back.

**Mutations:** removing the version refusal → RED on 3 tests; removing the
`statKeys` refusal *with the version check intact* → RED on the key-set test.
Both restored → GREEN. **Regression:** `tests/nfl_data/` +
`tests/league_comparison/` **669 passed, 1 skipped**.

### PR #1084 — V1-49: coverage verdicts state which path they describe

`engine_reads_key` probes with nflverse **column** names and never passes
`source=`, so every verdict describes the champion path only — silently.

Measured over all three committed 2025 REG host dumps (6,181 player entries,
numeric-id filtered): `punt_ret_td` present on **0**, `pt_return_tds` (the
column it is scored from) on **0**, while the host **does** publish combined
`st_td` and `kr_yd`/`pr_yd`. A real per-key asymmetry — and
`classify("punt_ret_td")` returns `SCORED` unconditionally.

Adds `HOST_PATH_UNREACHABLE`, a record asserted against the committed dumps so
it cannot go stale, and states `classify`'s scoping explicitly.

**Mutations, both directions:** adding a key the host *does* publish → RED;
emptying the record → RED. The constant can be neither padded nor silently
emptied.

---

## 3. V1-49 — exact production checklist

Run on the prod box. The four gate items in
`docs/scoring/HOST_NATIVE_SCORING_VALIDATION.md` §4 are unchanged by my work;
what changed is that a **precondition** is now enforced instead of trusted.

### Step 0 — PRECONDITION (new; see §4b of that doc)

Merge **#1083 first**. On first deploy after it, every existing
`pbp_weekly_*.jsonl` is refused until rebuilt, because all of them predate
`kick_ret_td`.

```bash
# No --force needed: a refused artifact reads as "not on disk at current
# schema", so --skip-existing and the timer rebuild automatically.
python3 scripts/build_pbp_weekly.py --seasons 2021 2022 2023 2024 2025

# Confirm every season now stamps the current schema AND key set:
python3 - <<'PY'
import json, pathlib
from src.nfl_data.pbp_weekly import PBP_WEEKLY_SCHEMA_VERSION, load_pbp_weekly
from src.nfl_data.realized_points import PBP_SUPPLEMENT_KEYS
for season in (2021, 2022, 2023, 2024, 2025):
    p = load_pbp_weekly(season)
    print(season, "REFUSED/absent" if p is None else
          (p["schemaVersion"], sorted(p["statKeys"]) == sorted(PBP_SUPPLEMENT_KEYS)))
PY
```

Do not proceed while any season prints `REFUSED/absent`. **Until this
completes, affected rules report `unscored` rather than scoring zero — that is
the intended degraded state, not a failure.**

Note the doc's build command names 2021-2025; the sandbox box carried
2022-2025 only. A season with no artifact resolves to `None` and is reported by
`SeasonPbpIndex.seasons_missing`, which degrades honestly — unlike the stale
direction.

### Step 1 — enable the challenger

```bash
export RISKIT_FEATURE_HOST_NATIVE_SCORING=1
sudo systemctl restart dynasty        # REQUIRED — flag reads are process-cached
curl -s localhost:8000/api/status | python3 -m json.tool | grep -i host_native
```

`_host_native_enabled()` **raises** if the env var is set and the flag registry
cannot be imported (deliberate, `sleeper_stats.py:59-67`). Confirm whether that
surfaces as a startup refusal or a per-request 500 — that is a property of the
deployed process and has never been observed.

### Step 2 — the four open gate items

| gate item | command / requirement |
|---|---|
| play-by-play artifact built and joined in production | Step 0 above, then measure the resulting movement in BDVM baselines and league comparison — **measured, not assumed** |
| BDVM rerun against challenger output | needs prod snapshots under gitignored `data/bdvm/`; rerun the baseline build and diff against the pre-flag baseline |
| league-comparison rerun against **challenger** scoring | needs a live Sleeper fetch; the champion-side symmetry repair was already measured on 72,457 real weekly rows (§5b) |
| historical backtests rerun | downstream of the two above; `scripts/backtest_adjusted_board.py` |

### Step 3 — what a sandbox provably cannot answer

Record these as prod-only rather than re-attempting them offline:

1. Whether flipping the flag **moves numbers a user sees**, and by how much —
   the gate's actual subject.
2. Whether the host's live dump still matches the entry-kind and DST-key
   census. The player/team separation guards are **empirical**, measured on
   sampled weeks; confirming no third team-entry spelling has appeared needs a
   full-season live fetch.
3. Whether the `_host_native_enabled()` fail-loud path behaves as a startup
   refusal under real deployment conditions.

### Step 4 — one open semantic that gates promotion

`idp_blk_kick` is **IDP-position-scoped on the nflverse path**
(`realized_points.py:585-590`, deliberate) but **not scoped at all on the host
path**, because `host_stat_line` takes no `position` argument. A host row for an
RB carrying `idp_blk_kick` is paid under the host path and refused under the
champion path. Existing tests cover only the champion side. This is a semantic
that **will change when the flag flips** and nothing currently measures it.

---

## 4. V1-52 — STATE_BLOCKED, with one nuance worth checking first

After #1081 merges, V1-52 has **no known implementation defect** and its
remaining bar is Section 3 of `docs/power/V1_52_L2_VERIFICATION_RECIPE.md`:
rank agreement against the archived dual-engine capture
(`docs/master-site-audit/evidence/W30/power-two-engines.json`), plus a `record`
vs standings check.

Sections 1, 2, 4, 5, 6, 7, 8 already passed against real production 2026-08-21.

**Re-run trigger:** once the season produces real scored weeks. Production
currently reports `weeksPlayed 0`.

**But two things I measured complicate the stated premise, and you should look
before concluding the calendar is the only blocker:**

1. **The results-only lens is NOT refusing.** Measured live: `unrankable: null`,
   twelve real ranks, scores 82.41 → 20.00. The recorded rationale — "both
   lenses correctly refuse to rank and there are no numeric ranks to compare" —
   does not describe production. Section 3's own commands target the
   **forward-looking** lens and compare against an **archived file**, and 3(b)
   (`record` vs standings) looks executable *today* on the results-only lens.
   This may be narrower than "wait for Week 1".
2. **The forward-looking refusal is a data-plumbing condition, not a season
   property.** `rosPower` reports `rosTeamStrengthAvailable: false` — the
   serving process cannot read `data/ros/team_strength/latest.json`. The recipe
   itself names this as a *compound* condition (§195-196). If that artifact
   were present, preseason forward-looking would rank on `team_ros_strength`
   and Section 3(a) would run unchanged. Meanwhile `rosChampionship` and
   `rosPlayoffOdds` report `rosStrengthAvailable: true` from the same file —
   they are served from a 6h-TTL cache, so a cached `true` coexists with a live
   `false`. **Worth verifying on the box.**

**The fact I am not hiding:** if Section 3 genuinely requires scored weeks,
**136/136 is unreachable before Week 1**, and closing V1-52 sooner needs a
legitimate owner decision to change the canonical required verification. §10
forbids reclassifying an item out of V1 REQUIRED because it proved hard. I am
not proposing that — only stating that the deadline is a real constraint and
should not be discovered late.

---

## 5. Deliberately not done — named, not silently skipped

**The runtime symmetry fix for the host path** (from #1084). Making the sleeper
branch report `unscored` for structurally-absent rules, the way the nflverse
branch already does, needs an authoritative host key **vocabulary**. Three
sampled weeks is not that. The distinction the fix turns on — a key absent
because the player didn't accrue it, versus a key the host *never* publishes —
cannot be settled from this sample, and treating it as settled would be exactly
the overstatement `_MAXIMAL_ROW`'s own correction comment exists to prevent.

**Withdrawn after inspection:** an earlier census flagged
`bdvm/context.py::TRUE_POSITION_MAP` and
`league_comparison/scoring_engine.py::_canonical_position` as a second-owner
violation of position normalization. **They are not.** `_canonical_position`
already consumes canonical `POSITION_ALIASES` and then applies a
deliberately-local IDP collapse; BDVM's map targets a different vocabulary
(EDGE/DT kept distinct to flag designation risk). Three concepts, not one with
three owners. Merging them would destroy both distinctions. No work needed; the
one genuine defect there (`SAF` missing) was already fixed.

**Not built:** the projection ensemble (`C5-U1` / `C5-PROJ-A…F` are POST-V1 per
§4.1, and §7.1 A-3 rules "consolidate onto what exists; do not build the
ensemble"). Claude 11's isolated projection work was not wired in.

**Not rewritten:** BDVM architecture. `meta.auxiliaryInputs` missing/stale
truthfulness and zero-network interactive intent are untouched.

---

## 6. OWNER_DECISION_REQUIRED — surfaced, not decided

None of these is engineering. Each changes product methodology and is undecided
in the tree.

1. **`st_td` + split-key stacking.** A single punt-return TD emits both `st_td`
   and `punt_ret_td`, and the canonical scorer is a pure dot product with no
   de-duplication. Harmless today (both live cards zero-rate the split keys) but
   **unpinned**, and it breaks silently the day a commissioner enables one.
   Genuinely undecidable from host truth: Sleeper never publishes the split keys
   on player entries, so the convention this lane uses cannot arbitrate, and the
   repo's own reasoning cuts both ways (the scorer docstring says the host
   "emits every applicable key, so they all stack" — but the host demonstrably
   does not emit these two).
2. **Three playoff engines still exist** — `public_league/playoff_odds.py`,
   `ros/playoff_sim.py`, `ros/championship.py` — with **two different bracket
   models**: re-seeding vs advancement-order, re-draw vs coin-flip, excluded vs
   50/50 on a missing distribution. Two of them publish a per-owner
   `championshipOdds` from the same `_TeamDist` objects. V1-51 made them agree
   on refusal *vocabulary*; it did not merge them, and
   `docs/PLAYOFF_PREDICTOR_SPEC.md:55` states the target.
3. **Divergent methodology constants across those engines** — bootstrap
   resampling vs Gaussian draws for the same weekly-score quantity; `ROS_BLEND
   = 0.20` justified only by an in-code adjective; variance bumps; adaptive vs
   fixed Monte Carlo sample policy; `MIN_SAMPLED_WEEKS = 2` vs a bare `>= 4` for
   the same question; contender thresholds commented "per spec" that I could not
   locate in the spec.
4. **`league_average_match` median game is specified but unimplemented**
   (`docs/PLAYOFF_PREDICTOR_SPEC.md:86-109`, which states the owner's primary
   league enables it). Building it is spec-directed engineering; deferring it is
   an owner call.
5. **New owners with no games receive real numeric ranks.** Measured live:
   `jstuedle` and `Blaine` (`record 0-0`, `ppg 0.0`) receive `powerScore 20.00`
   and ranks 11-12, assembled entirely from component defaults —
   indistinguishable from a measured last place. The engine refuses when *every*
   component is missing but ranks an owner whose every component is a default.
   Whether that should be a per-row refusal is an owner call.

Also worth a decision, lower stakes: V1-51's own row records that
`rosPlayoffOdds` publishing `n_simulations: 0` without naming a reason "is an
owner call". That specific residual was closed by #1054 (merged) — the contract
row's note appears unreconciled.

---

## 7. Session provenance

Five PRs merged earlier this session before this dispatch (#1031 V1-49 return-TD
keys, #1032 V1-52 PPG, #1054 V1-51 residual, #1059 V1-52 streak/luck, #1064
V1-53 guard). Three opened under it (#1081, #1083, #1084), none merged, none
self-promoted, no ledger row edited.
