# Hill trainer / Autopilot substrate repair (Batch 3 Unit D), 2026-10-01

**Status:** implementation evidence. No Hill constant, champion, registry entry or
production value changed. Nothing was promoted, and `--override-scope` was not used.
The demonstration below is **LOCAL** (a Windows worktree), not CI.

Owner requirement (Section D): fix the training substrate **before** any KTC/DLF
scale change. Inputs: findings H1–H9 in
[`HILL_SOURCE_ALIGNMENT_AUDIT_2026-09-24.md`](../../HILL_SOURCE_ALIGNMENT_AUDIT_2026-09-24.md)
and errors E2/E3 in [`../hill-alignment-2026-10-01/README.md`](../hill-alignment-2026-10-01/README.md) §5.

## What changed

| item | owner requirement | where | pinned by |
|---|---|---|---|
| 1 | one manifest derived from source authority; trainers, holdouts and Autopilot read it | `src/model_registry/training_manifest.py`; `fit_hill_curve_percentile.OFFENSE/GLOBAL/IDP_CSV_SOURCES` and `holdout.OFFENSE_TRAINING/HOLDOUT_SOURCES` are now views of it | `tests/model_registry/test_training_manifest.py::TestOneManifest` |
| 2 | every run pins code, inputs, dataset state, as-of, freshness, health, coverage, families, population, game type, cutoff, holdout families, config, output hash | `src/model_registry/training_run.py`; stored as `trainingRun` on the registry challenger (`ModelVersion.training_run`) | `test_training_run.py::TestPins` |
| 3 | rank-only evidence never teaches spacing | manifest `spacing_evidence`; rank-only boards and snapshot synthetic encodings are excluded; a rank column declared as a value column is an error | `TestRankOnlyNeverTeachesSpacing` |
| 4 | no holdout family leakage; measured dependence ≠ ancestry; explicit, tested policy | manifest family rule (both directions); `evaluate_offense_master` refuses a family across the split; `HoldoutPolicy` | `TestHoldoutFamilies` |
| 5 | OFFENSE population players-only (E3) | one population rule, `training_manifest.load_board_values` (canonical `is_pick_name` + `PICK` position) | `TestPlayersOnlyPopulation` |
| 6 | reproducible, point-in-time refits | `training_run.replay` / `scripts/hill_training_run.py`; refusal of post-cutoff inputs; Autopilot tournaments only reproducible current-substrate challengers | `TestReproducibility`, `TestPointInTime`, `TestRegistryAndAutopilot`; demo below |

Commits: RED `4ea1f9d79` (tests fail on `main`), GREEN `698b281ef`, CRLF fix `1f7b24d7d`.

### 1. The manifest: derived vs declared

Derived from the live registry, never restated: CSV path (`_SOURCE_CSV_PATHS`),
signal type, live role (`_VALUE_BASED_SOURCES` / `_RANKING_SOURCES` /
`_NON_VOTING_SOURCE_CSV_KEYS` / `ktc_market.KTC_MARKET_KEY`), B10 family
(`correlation_group_for`), game type. Declared (no registry can express them): the
native value column, the requested scope/role, and measured dependences with their
evidence. Every registered source must be a declared board or sit in
`NOT_HILL_BOARDS` with a reason, so a new source cannot leave Hill behind (H8).
Two trainers from one family in one scope is a `ManifestError` (one vote per family).

**Trainer membership is unchanged** except where an owner item forced it. Today's
manifest (`1f31e6724c2b…`):

| scope | trains | holds out | excluded |
|---|---|---|---|
| OFFENSE | KTC (base), Dynasty Daddy, Dynasty Nerds, Yahoo/Boone, Fitzmaurice, DraftSharks | FantasyCalc (measured dep. on dynastyDaddySf), OTC, PFK (measured dep. on ktcCrowd) | Fantasy Navigator — `confirmed_common_ancestry:ktcCrowd` |
| GLOBAL | IDPTC, DraftSharks-Combined | — | — |
| IDP | IDPTC IDP slice, DraftSharks-IDP | — | — |
| ROOKIE | KTC-Rookie, IDPTC-Rookie, DraftSharks-Rookie | — | Boone-Rookie, Fitzmaurice-Rookie — `synthetic_rank_encoding` |

### 3. How rank sources are used (the "document precisely" branch)

- **Rank-only boards** (DLF Rank, FantasyPros, Flock, IDP Show, DLF rookie/IDP) never
  train or hold out. They contribute ORDER at serve time only.
- **Snapshot fields of rank-signal sources** hold the synthetic encoding
  `1,000,000 − 100·rank` (999,900 at rank 1), not a value. The ROOKIE trainer used to read them for
  Boone/Fitzmaurice; they were empty in every snapshot so this never fired, but it
  is now refused structurally.
- **Native values published by sources that VOTE by rank** (Dynasty Daddy, Dynasty
  Nerds, Boone, Fitzmaurice, DraftSharks) are real vendor spacing and still train,
  as before. That indirect channel is large (H3, §4b of the 09-24 audit) and is an
  **owner decision**; `TrainingPolicy(allow_rank_voter_native_values=False)` is the
  tested switch that restricts training to value-signal lineages (OFFENSE would then
  train on KTC base alone).

### 4. Holdout policy

- **Confirmed common ancestry** (same B10 family): hard exclusion, both directions.
  Fantasy Navigator is out while KTC trains; if KTC were ever held out, FN could not
  train.
- **Measured dependence** (PFK ~ KTC residual r +0.45 and 1.64× LOIFO flattering;
  FantasyCalc ~ Dynasty Daddy r +0.677): `retain_and_report` by default. The holdout
  record now publishes `holdoutFamilies`, `measuredDependence` and
  `independentCriterion` (mean over boards with no measured dependence — today OTC
  alone). `HoldoutPolicy(measured_dependence="exclude")` removes them; it is not the
  default because Autopilot's `minImprovedBoards = 3` could then never be met.
- Autopilot's breadth and leave-one-out gates now run on **3** holdout boards, not 4.

### 6. Autopilot / registry

- A raw refit records `trainingRun`. `--require-reproducible` (set in the workflow)
  refuses inputs that differ from HEAD; the cutoff is HEAD's commit time.
- New workflow step: `scripts/hill_training_run.py verify --latest-raw` replays the
  recorded run from git and requires the identical `challengerHash`.
- `scripts/hill_autopilot.py::tournament_versions` admits only challengers with a
  reproducible current-substrate run (`training_run.is_tournament_eligible`) and drops
  a challenger whose `challengerHash` repeats an earlier one (a refit on identical
  pins is not new stability evidence). **Consequence:** every pre-repair challenger,
  including the pending v171, leaves the tournament. No automatic promotion is
  possible until three new-substrate challengers spanning five days, plus forward
  persistence, accumulate. That is the intended effect of "fix the substrate first".
- The Autopilot composite inherits the raw winner's run (`register --derived-from`).

## LOCAL reproducibility demonstration

`python docs/valuation/evidence/hill-trainer-repair-2026-10-01/reproduce_demo.py --out …/demo.json`
at `1f7b24d7d` — full output in [`demo.json`](demo.json):

| check | result |
|---|---|
| two replays of one pin set (inputs from git at `1f7b24d7d`, cutoff 2026-10-01T13:38:34Z) | identical `58eccbffd384b5bc…` |
| CI path (worktree refit, `--require-reproducible`) vs replay of its own recorded pins | identical `58eccbffd384b5bc…` |
| two point-in-time replays, cutoff 2026-09-29T00:00Z → commit `8c73fcf5f`, snapshot `dynasty_data_2026-09-28.json` scraped 23:33:22Z, latest dataset clock 23:36:35Z | identical `131ae3c1f9bc25c1…`; nothing after the cutoff |

**Defect found by the demo, fixed in `1f7b24d7d`:** the first worktree run and its git
replay disagreed. `core.autocrlf` rewrote the board snapshot and every dataset-state
JSON to CRLF on disk, so a raw byte hash pinned the checkout, not the content. Pinned
files are now hashed with CRLF normalized to LF (`HASH_NORMALIZATION`), with a
regression test.

Diagnostics from the same run (context only, **not** a promotion input):

- KTC base, players only: 500 rows, 36 picks dropped, 464 players, top 400 fit →
  c 0.105 / s 0.925 (was 0.111 / 0.875 with picks), matching the 10-01 audit.
- The repaired OFFENSE master at HEAD is c 0.067 / s 1.110, close to the pending v171
  (0.066 / 1.085). On the repaired 3-board split: champion (0.110, 1.110) 1108.7,
  repaired refit 555.8, v171 555.6 (mean per-source RMSE).
- `ktc` has **no dataset-state file**, so the KTC trainer's freshness is recorded as
  `measured: false` — an honest unknown, not a fresh 1.0.

## E2 — Phase 1c signal-type coupling (patch for the `data_contract` owner)

Not edited here: `src/api/data_contract.py` belongs to another unit's one-writer slot.
Failing-first test: `tests/api/test_phase1c_signal_type_coupling.py`, `xfail(strict=True)`.
With `idpTradeCalc` taken off `_VALUE_BASED_SOURCES`, its `effectiveRank` is 9,992
today and must equal its Phase 1 ordinal.

Patch (verified locally against this test, then reverted):

1. Add after `_NON_VOTING_SOURCE_CSV_KEYS`:
   ```python
   def _csv_signal_for(key: str) -> str:
       cfg = _SOURCE_CSV_PATHS.get(key)
       if isinstance(cfg, dict):
           return str(cfg.get("signal") or "value").lower()
       return "value" if cfg else ""
   ```
2. In Phase 1c's `csv_rank_cross_market_keys`, replace
   `and str(s.get("key") or "") not in _VALUE_BASED_SOURCES` with
   `and _csv_signal_for(str(s.get("key") or "")) == "rank"`.
3. In the same PR: remove the `xfail` marker (strict mode turns the fix into an
   XPASS failure until it is removed), and invert
   `tests/api/test_hill_alignment_audit.py::test_emptying_the_value_set_decodes_idptc_values_as_ranks`,
   which characterizes the artifact and fails once it is gone.

Board impact today: none. The Phase 1c set is empty on the live registry both before
and after; the patch only changes what happens when a value-signal cross-market source
leaves the value path.

## What a clean D2 rerun (KTC native / KTC c3 / DLF Rank / DLF native spacing) now needs

1. **Score every arm against a substrate-v2 master.** Produce it with
   `scripts/hill_training_run.py replay --commit <pin> --out run.json` and stamp its
   `challengerHash`, `manifestHash` and `codeHash` into the audit's pins. The incumbent
   constants were fit on the pre-repair substrate. Every arm should be scored against
   both curves, so the substrate effect is not attributed to the arm.
2. **Decide H1/H2 first, because c3 makes Hill the sole spacing owner.** Under c3, KTC's
   spacing reaches the board only through training. Which KTC board trains is then
   load-bearing: base (today), Crowd TE++, Crowd + Trades as two families. Variant
   manifests are one `build_manifest(specs=…)` call each, and the family rule still
   applies.
3. **Decide the rank-voter-native-values policy (H3)** if the rerun should isolate
   value-signal spacing. Use `TrainingPolicy(allow_rank_voter_native_values=False)`.
4. **DLF Rank** is rank-only and can never be a Hill trainer. It is an order arm only.
5. **DLF native spacing is blocked as Hill training evidence.** `dlfValuesSfTep` is not in
   `_SOURCE_CSV_PATHS`, so the manifest refuses it. It first needs its own gate
   (`docs/sources/DLF_VALUES_GATE_2026-09-25.md`) and a registry entry with game-type
   evidence, even a non-voting one (repair-contract item 6). Until then it stays a
   scale comparison, as in the 10-01 audit §A2.
6. **Use point-in-time inputs throughout.** `materialize_inputs` + `commit_at_or_before`
   can materialize every registered CSV at a commit. That makes the audit's missing
   point-in-time board backtest (§3 E) feasible: build the board over the materialized
   tree with `build_api_data_contract(csv_root=…)`. The holdout scores against the same
   tree via `evaluate_offense_master(repo_root=…)`.
7. **Land E2 first** if any arm takes a cross-market value source off the value path. c3
   only moves KTC player rows, which are not cross-market, so c3 itself is unaffected.
