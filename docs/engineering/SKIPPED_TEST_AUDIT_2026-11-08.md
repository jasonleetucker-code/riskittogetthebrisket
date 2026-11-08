# Skipped-test audit — 2026-11-08

Scope: the backend hard gate (`pytest tests/ -x -q -m "not livedata"`, 8 shards,
`config/ci/test_shards.json` `max_skipped: 290`).  Source run: PR Validation run
`42440671260` (all 8 `backend-shard-N` manifests): **261 skipped, 30 xfailed,
34,608 passed, 0 module-level (collect) skips.**

The shard manifests carried only counts, not reasons.  This audit reproduced the
reasons by running the skip-bearing files locally (Windows, so OS-conditional
skips differ from Linux CI and were set aside) and reading each skip condition.
`scripts/ci_test_shards.py` now also writes `skip_reasons` (node id -> reason)
into every shard manifest, so the next audit reads them from the artifact
(observability only: not hashed, not counted, no verdict can change).

## Initial count and classification (261)

| Reason class | Count | Hides a risk? |
|---|---:|---|
| Seeded random draw does not exercise the property (`tests/trade/test_forced_drop_selection.py`: 164 no taxi bracket, 60 trade fits / no legal cleanup, 16 roster cannot fill every slot) | 240 | Low per draw, but each skip silently narrowed a property sweep (the taxi sweep exercised only 76 of 240 cases) |
| Data-dependent: pinned archives pruned by `exports/archive` retention (`tests/api/test_unslotted_draft_class.py`) | 7 | **High**: the C1-U6-D2 rollover regression (2027 class priced as tiers, never tethered) was never tested |
| Obsolete: module no longer exists (`src.api.export_builder`) | 1 | None (nothing to protect) |
| Vacuous: live-board filter that matches no row (`pickYearDiscount` is stamped on no pick since the derived year-step model) | 1 | Medium: the discount-inversion math had no test |
| Environment: suite registry is hermetic-empty, so `dynasty_main` is never "active" | 1 | Medium: league-scoped signal restore never tested |
| Data-dependent: gitignored nflverse schedule cache | 1 | Low (math is pure; only the file was missing) |
| Not individually identified from CI (reasons not in manifests) | ~10 | Unknown until the PR's shard manifests are read; see below |

The ~10 residual is `261 - 251`.  Locally identified members: 3 gitignored
Sleeper cache (`data/idp_accuracy/cache`), 1 unreachable-by-construction flag
branch, 1 declared-exempt call site.  About 5 are unattributed because their
files error or time out on Windows (Linux-only deploy/shell tests presumably run
on CI where `bash`, `jq` and `tesseract` are installed).

## Outcome: 11 skips resolved by real coverage, 240 reclassified (expected CI count 261 -> about 10)

### Restored coverage (10 tests now run) and 1 obsolete test removed

| Change | Skips resolved |
|---|---:|
| `test_unslotted_draft_class.py`: the two pinned bundles recovered from git history (`c02426fa6`, `52d78cbc1`) and committed under `tests/fixtures/pick_rollover/` (~670 KB); a missing fixture now fails | 7 |
| `test_picks_end_to_end.py::test_future_year_picks_project_above_today`: deterministic synthetic rows against `_stamp_pick_value_projections` (incl. out-of-range discount); the live-board form never ran | 1 |
| `test_private_route_auth_regressions.py::test_signals_restore_league_scoped_bucket_only`: loads the committed registry for the test only, restores the hermetic state | 1 |
| `idp_accuracy/test_backtest.py::test_availability_inputs_...`: hermetic synthetic schedule CSV | 1 |
| `test_pick_completeness.py::TestExportParity` REMOVED (obsolete, not restored): `src.api.export_builder` does not exist and nothing builds a values CSV from the contract; value integrity is covered by `TestPickCompletenessCensus` in the same module | 1 |

### Reclassified, not restored: 240 forced-drop draws

`tests/trade/test_forced_drop_selection.py`: coverage is UNCHANGED.  These draws
never exercised the property; they used to be skipped and are now excluded from
the parametrization by id (frozensets `_*_NOT_APPLICABLE`), and each test ASSERTS
its precondition.  The gain is a loud guard against generator / capacity-owner
drift (a changed draw fails instead of silently narrowing the sweep) and a skip
count small enough to tighten the budget.  It is not new coverage: the taxi
sweep's real coverage remains 76 of 240 seeded cases (brute-force 4 dimensions:
352 of 400 applicable; v5/v5r 88 of 100; monotonicity 24 of 40).  Result: 666
passed, 0 skipped (was 666 + 240).

Nothing was weakened, no `xfail` or new skip was added, `max_skipped` is
unchanged (the coordinator tightens it after CI reports the count).

## Remaining justified or deferred skips

* `test_pbp_supplement_call_sites.py`: one call site is declared exempt on
  purpose (it is a before/after measurement against a second tree). Justified.
* `test_verify_signals_onbox_v2.py::test_gate_refuses_every_f_build_until_its_flags_are_registered`
  (1): unreachable while the per-family flags are registered, and the check runs
  the gate in a subprocess so an in-process registry patch cannot reach it.
  Follow-up (low risk): drive it through a subprocess environment that hides the
  flags, or delete it when the flags' registration is permanent.
* `tests/idp_accuracy`, `tests/league_valuation` real-data tests (3): need the
  gitignored `data/idp_accuracy/cache` Sleeper bodies. **Follow-up (medium)**:
  commit a trimmed pinned cache (or a derived fixture) so
  `test_real_data_parity_and_pool_sizes_match_the_evidence`,
  `test_real_rosters_engine_reproduces_sleepers_best_ball_and_scorer` and
  `test_real_rosters_aggregate_invariants` run in CI. Acceptance: they execute
  (0 skipped) from a clean checkout and still assert the pinned scoring
  fingerprint and 72/72 best-ball team-weeks.
* Linux CI environment skips (symlink, `/proc`, POSIX modes, `jq`, `tesseract`,
  `bash`): run on CI's Ubuntu image (the workflow installs `tesseract`); they
  skip only on Windows and are not in the 261.

## High-risk skips needing follow-up

0. **Forced-drop sweep depth.** Only 76 of 240 taxi seeds exercise the property.
   Acceptance test: every forced-drop property test runs at least N applicable
   draws per scenario (N chosen by the owner of `roster_capacity`, e.g. 100 for
   the taxi bracket), generated deterministically by construction (a generator
   that targets the precondition), NOT filtered after the fact; a meta-test
   asserts the applicable-draw count per scenario >= N.

1. The ~5 unattributed skips. Acceptance: after this PR's shards run, read
   `skip_reasons` from the `backend-shard-*` artifacts, classify, and either fix
   or list each here with a reason.
2. Any future retention pass over `exports/archive` can again silently skip
   archive-pinned tests (other modules use `tests/archive_fixtures.py`, which
   skips when no complete board exists). Acceptance: a guard test that fails when
   `newest_complete_raw_payload()` would return `None` in CI, so "no board" is a
   failure, not a skip.

## Budget tightened (coordinator, after CI)

PR Validation run 42471438554 on this branch: 34,686 collected, **10 skipped** (was 261), 30 xfailed, 0 failed. Every remaining skip names a deterministic environment or data condition, and the shard manifests now carry the `skip_reasons`:
- 4 privacy tests that need the box-only ROS artifacts;
- 1 POSIX-only file-replace path, covered by a stub;
- 3 tests that need the gitignored real-Sleeper cache;
- 1 declared-exempt pbp call site;
- 1 refusal path that is unreachable while the flags are registered.

`config/ci/test_shards.json` `max_skipped` goes from 290 to **10**. Any new skip now fails `Validate PR` until it is justified and the budget is raised in a reviewed change.

