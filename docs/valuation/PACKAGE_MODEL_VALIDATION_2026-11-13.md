# Package model q and fairness bands: out-of-sample validation (2026-11-13)

**Status: RESEARCH, for an owner decision.** Owner directive 2026-11-08, Priority 16 (Top 20 audit item 16).
Nothing here changes `geom_q078_v1` (q = 0.78), `fairness_bands_v2` (3.5 / 9 / 18 %, floor 250),
`config/trade/`, any flag or any served code.

- Plan, committed alone before any trade was priced:
  [`evidence/package_model_validation_2026-11-13/PREREGISTRATION.md`](evidence/package_model_validation_2026-11-13/PREREGISTRATION.md).
- Script: `scripts/research/package_model_validation.py`. Tests: `tests/scripts/test_package_model_validation.py`.
- Evidence: [`evidence/package_model_validation_2026-11-13/results.json`](evidence/package_model_validation_2026-11-13/results.json).

Agent-OS-Receipt: aa55ed12383caa257a25d28baa6612bc9577347d

## 0. Result in one screen

**Verdict on the data available here: insufficient data.** The only accepted-trade data on this machine is one
league's tracked snapshot: 28 eligible trades, 15 of them unequal-count. The preregistered sufficiency rule R0
needs at least 2,000 unequal-count trades from at least 200 leagues. The decisive population, the canonical
market-trade ledger, exists only on the production box. The script runs there unchanged (§7); it has not been
run there.

What this study does establish:

1. **Fitting q by least squares on accepted trades gives the wrong answer.** On synthetic trades that clear
   exactly at q = 0.78 plus noise sized to the production 1-for-1 dispersion, the preregistered least-squares fit
   returns q = 0.63–0.64, with an interval that excludes the truth. The preregistered out-of-sample rule R1 then
   "prefers" the fitted q although 0.78 is correct. The moment fit (mean residual = 0) recovers 0.78–0.80 and
   covers the truth. Any future fit of q must use calibration (the moment fit, or Phase 3's J), never squared
   error. This is recorded as deviation D1 (§3).
2. **On calibration, accepted trades want a much lower q in the geometric family, and the reason is probably not
   package shape.** Committed production evidence (Phase 3, 18,690 trades) has the calibration loss still falling
   at the grid edge q = 0.50. The local league agrees in direction: its moment fit is at the 0.30 boundary, with
   an interval of 0.30 to 0.54. Phase 3 showed that a fixed per-piece level of about 2,000 points explains this
   residual, with q near 0.85 above that level. That is a value-level effect, not a package-shape effect.
3. **The bands cannot be validated on accepted trades, only checked for shape neutrality and stability.**
   Accepted 1-for-1 trades, which no q can change, sit about 20 % apart on average on the canonical board
   (production mean |r| 0.200, n 4,850). The fair band is 3.5 %. So the bands state distance from the site's
   fair value; they do not describe where accepted trades land. In the local league, 79 % of accepted trades are
   labelled not fair at q = 0.78 (half of the 1-for-1s), and 77 % of those labels go against the side receiving
   fewer pieces. Whether that is the market's star premium or the site being right cannot be decided from
   completed trades (§5.1).

**Recommendation (an owner decision, §8):** keep q = 0.78 and `fairness_bands_v2` as declared priors. Authorize one
read-only box run of this preregistered script, read under D1. Restate OD-F4 as "shape-neutral and stable on
accepted trades, judged by outcomes", because 3.5 / 9 / 18 cannot be validated from accepted trades.

## 1. What data exists, and where (Q1)

| data | where | state | used here |
|---|---|---|---|
| canonical market-trade ledger `data/market_trades/underlying_trades.sqlite` (KTC trade database, Sharp Sleeper and own-league lanes) | **production box only** (gitignored) | 29,638 dated groups since 2026-07-01 and 18,690 graded at Phase 3 (2026-10-20). More now; not measured here | no: decisive, box-only |
| own-league acquisition store `data/retention/acquisition.sqlite` and own-league format captures | box only | not on this machine | no |
| local intel ledger `data/intel/ledger.sqlite3` | this machine | all 29 tables empty (0 transactions) | no |
| `data/market_trades/` | this machine | absent | no |
| **`data/sleeper_last_good.json`** | tracked | 96 `dynasty_main` trades from 2025-11 on | **yes: D-OWN, one league, not decisive** |
| `exports/archive/dynasty_export_*.zip` | tracked | 156 raw board payloads, 2026-07-14 to 2026-11-13 | yes: point-in-time boards |
| Phase 3 production aggregates (`evidence/package_model_phase3_2026-10-20/production_phase3_run_2026-10-20.json`) | tracked | aggregates only, no rows | cited as prior evidence, not re-analysed |
| synthetic trades with a known q | generated | labelled SYNTHETIC | estimator checks and power only |

The 1,121-trade sample behind the audit's "−0.14 to −0.15" figure was collected in a research container
(Phase 2) and only its aggregates were committed. It cannot be re-analysed.

### 1.1 The local population (D-OWN)

| step | trades |
|---|---:|
| trades in the snapshot | 96 |
| not two teams | −3 |
| in the 2025 season league (a different format) | −13 |
| ledger-shaped groups | 80 |
| no board strictly before the trade within 7 days (mostly before 2026-07-14) | −36 |
| an unresolved player name (missing is never zero) | −6 |
| an asset the point-in-time board does not price | −8 |
| one-sided | −2 |
| **graded** | **28** (15 unequal-count; one league; 19 dates, 2026-08-11 to 2026-11-12; 21 boards) |

- Shapes: 6 1v1, 3 1v2, 3 2v1, 4 2v2, 12 "3+".
- Classes: 11 offense players only, 9 with an IDP player, 8 with picks and no IDP.
- Format facts were read from the snapshot itself: `leagueSettings.type == 2` (dynasty) and a `SUPER_FLEX` slot.
- 77 pick labels the snapshot wrote as "Mid" were priced at the **generic** grade (year, round). The snapshot
  writes "Mid" for every future pick whose slot is unknown, and `market_resolution` answers an unknown slot with
  the generic grade.

## 2. Method

Exactly as preregistered, with the deviations listed in §3.

- **Values.** Point-in-time canonical values come from the board archived strictly before each trade (at most
  7 days before). Eligibility uses the ledger owner (`market_trade_eval.residual_eligible`). Utilities come from
  `package_model.geom_utility` and band labels from `fairness_bands.classify` + `fairness_base`. A parity check
  against the owners passed on every row (utility difference < 4e-12; adjusted gap within 0.5 of the served
  rounding).
- **Residual.** `r_q = (U_q(A) − U_q(B)) / mean(adjusted totals)`, where A is the side receiving fewer pieces.
  Negative means the market gave the consolidating side more credit than the model does. This is the Phase 2/3
  quantity.
- **Folds.** Trades are split into 5 contiguous date blocks; a date is never split. Folds 2–5 are fitted on all
  earlier blocks and scored on the next one.
- **Intervals.** Two-way pigeonhole bootstrap by league and date: 1,000 replicates, and 300 for refits of q.

## 3. Deviations from the plan

**D1. The preregistered least-squares fit and rule R1 are not valid tests of q.** The preregistered synthetic
check (`--power`, evidence `powerAnalysis` and `r1FalsePositiveCheck`) generated trades that clear exactly under a
known q, then added multiplicative clearing noise of σ = 0.25. That σ matches production 1-for-1 dispersion
(mean |r| 0.200 ≈ 0.8σ).

| true q | trades | least-squares fit [95 %] | moment fit [95 %] |
|---|---:|---|---|
| 0.70 | 5,000 | 0.56 [0.54, 0.58] | **0.70** [0.68, 0.72] |
| 0.78 | 1,000 | 0.63 [0.58, 0.67] | **0.79** [0.75, 0.85] |
| 0.78 | 5,000 | 0.64 [0.61, 0.65] | **0.79** [0.77, 0.81] |
| 0.85 | 5,000 | 0.70 [0.68, 0.72] | **0.86** [0.83, 0.88] |

These rows use symmetric noise. Noise on the larger side only gives the same picture.

- **Why.** Squared error is smallest when the noisy many-piece side is shrunk, so the least-squares fit drifts
  low. The bias is about 0.14 for every true q.
- **What it does to R1.** Run on 5,000 synthetic trades whose true q *is* 0.78, the full preregistered evaluation
  says R1 = `favours_alternative`: squared error at the fitted q is lower by 0.0033 [0.0019, 0.0045]. The
  calibration reading is right on the same data: J is 0.009 for 0.78 against 0.054 for the least-squares fit, and
  the moment fit is 0.80 [0.76, 0.83].
- **What changed.** R1 still reports as frozen. The script now also reports the moment fit's interval
  (`qMomentCi95`), a fifth model scored out of sample (`MMOM`, each fold's moment fit), and the R2 reading on
  moment fits (`D1_*` stamps). This document reads q only from those. The frozen R0 and R3 are unchanged.

**D2. A league-only interval is degenerate on D-OWN.** There is one league, so the league-only bootstrap
interval collapses to a point. The two-way interval is still a date-clustered interval. Both are reported.

## 4. q out of sample (Q2): local results, not decisive

R0 fails on all three counts: 15 unequal-count trades (2,000 needed), 1 league (200 needed), and test folds of 2 to
5 unequal-count trades (200 needed). The numbers below show that the pipeline runs end to end on real trades.
They are not evidence about q.

| | value |
|---|---|
| full-sample least-squares fit | 0.30, at the grid boundary (biased, D1) |
| full-sample moment fit | 0.30, at the boundary; interval 0.30–0.54, **below 0.78** |
| level diagnostic, c = 2,000 (least squares / moment) | 0.66 / 1.00 (grid edge; 15 trades say nothing about the level effect) |
| fold fits (least squares) | 1.00 (fold 2, one training trade), 0.30, 0.30, 0.30 |
| squared error out of sample, 14 test trades: q 0.78 / fitted / 1.00 | 0.097 [0.033, 0.176] / 0.054 [0.016, 0.122] / 0.201 [0.101, 0.318] |
| difference, 0.78 − fitted | +0.043 [−0.015, +0.104]: no difference detected |
| difference, 0.78 − 1.00 | −0.104 [−0.152, −0.054]: 0.78 better than raw sums |
| J out of sample: 0.78 / fitted = moment / 1.00 | 0.385 / 0.214 / 0.529 |

Out-of-sample mean signed residual at q = 0.78 (test trades; tiny cells):

| stratum | n | mean signed [95 %] |
|---|---:|---|
| 1-for-2/3 (Phase 3 bin) | 7 | −0.385 [−0.524, −0.263] |
| ordinary | 3 | −0.024 [−0.099, +0.039] |
| deep | 4 | −0.060 [−0.082, +0.001] |
| shape 1v2 / 2v1 / 3+ | 3 / 3 / 8 | −0.254 / −0.583 / −0.062 [−0.108, −0.009] |
| offense players only / with IDP / with picks | 2 / 6 / 6 | −0.188 / −0.080 [−0.174, +0.015] / −0.359 [−0.563, −0.109] |

The production evidence is in the same direction and very precise. Phase 3 measured q = 0.78 against 18,690
trades:

| shape | n | q = 0.78 | q = 1 (raw) | q = 0.50 |
|---|---:|---|---|---|
| 1v2 | 4,631 | −0.29 | −0.42 | −0.15 |
| 1v3 | 1,492 | −0.33 | −0.59 | −0.11 |
| 2v3 | 1,861 | −0.11 | −0.23 | −0.01 |
| 3+v4 (unequal) | 526 | −0.06 | −0.17 | +0.01 |
| 1v1 (no q dependence) | 4,850 | mean \|r\| 0.200 | same | same |

The shortfall shrinks as q falls and has not closed at q = 0.50 for 1-for-2/3. So the shape-only moment fit on
the ledger is below 0.50. That is an inference from the aggregates; the box run measures it.

Phase 3's decomposition separates two things. With a fixed per-piece level c = 2,000, the best q is 0.85
(J 0.008, against 0.300 at q = 0.78 and c = 0). That holds on held-out leagues, across league sizes and in both
sources. Under the frozen rule R2 a low shape-only q is then a level effect, and a change of q is not supported.
D1 does not weaken that reading: the decomposition was judged on calibration (J), not squared error.

**IDP and picks.** Only 138 of the 18,690 graded production trades contain an IDP player, and 80 % contain a pick.
An IDP-specific q cannot be estimated from the market ledger at any useful precision. Own-league trades are where
IDP lives.

## 5. Fairness bands (Q3)

### 5.1 The assumption

A band check on accepted trades assumes **A1: an accepted trade is, on average, a fair exchange at canonical
value**, so a band that labels it unfair is a false alarm. A1 fails in two ways the data cannot separate:

- **A2:** accepted trades include genuine mistakes, information gaps, team context and bargaining. A not-fair
  label can then be correct, so the not-fair share is an upper bound on false alarms.
- **A3:** the market prices some shapes by convention, for example a star premium. A shape-dependent gap may
  then be the site being right.

Completed trades cannot decide between A1 and A3. Only outcomes can. So nothing here fits a cut point.

### 5.2 What accepted trades show

Trade-level dispersion is far wider than the fair band:

- Accepted 1-for-1 trades, which no q can move, sit on average 20 % apart on the board (production mean |r| 0.200,
  n 4,850; about 18 % in band terms).
- The fair band is 3.5 %, and the lopsided cut is 18 %.

A1 can hold only on average, never trade by trade. The bands are a normative statement, "how far is this from the
site's fair value", not a description of accepted trades.

Local league (D-OWN, 28 trades; shares with 95 % intervals clustered by date):

| q | fair / slight / unfair / lopsided | not fair | lopsided | not-fair labels against the consolidating side |
|---|---|---|---|---|
| **0.78** | 6 / 3 / 7 / 12 | 79 % [62, 93] | 43 % | 77 % |
| fitted (0.30) | 7 / 3 / 9 / 9 | 75 % [58, 90] | 32 % | 42 % |
| 1.00 | 5 / 3 / 5 / 15 | 82 % [67, 94] | 54 % | 100 % |

- **By shape at q = 0.78:**
  - 1v1: 3 of 6 not fair;
  - 1v2: 3 of 3;
  - 2v1: 3 of 3 (all lopsided);
  - 2v2: 3 of 4;
  - 3+: 10 of 12.
- **By class:** offense players 64 %, with IDP 89 %, with picks 88 %.
- **R3 (shape bias, frozen rule):** not recorded. The 1v2 excess over 1v1 is +50 points, but the interval
  [0, 100] does not exclude 0 at n = 3.
- **Stability:** moving q from 0.78 to the fitted q changes the label on 46 % of trades; moving to 1.00 changes
  it on 32 %. No 1-for-1 changes.
- **Production inference (to be measured on the box).** A mean residual of −0.29 in 1-for-2 trades is about 28 %
  in band terms. So the typical market 1-for-2 trade would be labelled **lopsided against the consolidating
  side** at q = 0.78. Under A1 that is a false alarm concentrated in one shape; under A3 it is the site
  disagreeing with a market convention.

## 6. Market clearing, fair value and team utility (Q4)

| concept | in this study |
|---|---|
| **market clearing**: what two managers accepted | the observation (ledger, snapshot) |
| **fair value**: canonical value combined by the package model, judged by the bands | the model under test |
| **team utility**: one roster's lineup, roster spots, forced drops and posture | not measured; a cause of residuals, never a target |

- A residual is the gap between fair value and market clearing. It is a fair-value error only under A1.
- The level effect (about 2,000 points per piece) matches team utility, because roster spots cost something. The
  trade engine already charges that cost through roster capacity, forced drops and lineup value. Putting it into
  q would charge it twice.

## 7. What would settle it: the box run

**Not run. It needs a separate owner authorization**, the same posture as
`docs/ops/PACKAGE_MODEL_PROSPECTIVE_RERUN_COMMAND_2026-11.md`. It is a manual command: no merge-triggered job, no
deploy, nothing written on the box outside one temp dir. Run it as the service user between 09:30 and 13:30 UTC.

**Pin.** Use the commit on `main` that carries this script after merge. Until then, this PR's commit
`67c9794c16425237598c1bf763ef761142cb9641` carries the same bytes. The sha256 below is of the file bytes, so it
holds for any commit with the same file.

```bash
#!/usr/bin/env bash
# Package-model q + fairness-band validation (P16, preregistered).  READ-ONLY.
set -Eeuo pipefail
PIN=67c9794c16425237598c1bf763ef761142cb9641   # or the merge commit on main: same file bytes
APP_DIR=/home/dynasty/trade-calculator
RAW="https://raw.githubusercontent.com/jasonleetucker-code/riskittogetthebrisket/$PIN/scripts"
[[ "$(id -un)" != root ]] || { echo "run as the service user, not root" >&2; exit 64; }
umask 077
WORK="$(mktemp -d /tmp/pkg-validation.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
cd "$WORK"
curl -fsSL --proto '=https' --max-time 60 "$RAW/research/package_model_validation.py" -o "$WORK/package_model_validation.py"
curl -fsSL --proto '=https' --max-time 60 "$RAW/research_readonly_guard.py" -o "$WORK/research_readonly_guard.py"
sha256sum --check --strict --quiet - >&2 <<'PINS'
401f587c4d2ddb546e27e075b35158694108c847fca0fb53cfc78c3501f704ff  package_model_validation.py
5c208fe8ee187d78ef7173330efc795a621b970f1ba69ff416c9edf836bc6f18  research_readonly_guard.py
PINS
PY=/home/dynasty/.venvs/trade-calculator/bin/python
[[ -x "$PY" ]] || PY="$APP_DIR/.venv/bin/python"
[[ -x "$PY" ]] || { echo "no app python found" >&2; exit 2; }
TMPDIR="$WORK" RISKIT_APP_DIR="$APP_DIR" OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  timeout 2700 nice -n 19 ionice -c3 \
  "$PY" -B "$WORK/package_model_validation.py" --box
```

Run it from your machine as `ssh -p <port> dynasty@<host> 'bash -s' < pkg_validation_box.sh > pkg_validation_run.json`.

- **Pins.** The guard pin is that file at current `main`. Re-check the script pin at the chosen commit with
  `git show <PIN>:scripts/research/package_model_validation.py | sha256sum`. If the file changed, re-pin and
  re-review it.
- **Guard.** The read-only guard is installed before any application import. It refuses writes outside its
  scratch dir, read-write SQLite, subprocesses and network. Exit 3 if a write or process start was refused.
  Network refusals (about 270 at Phase 3, all `_resolve_league_context`) are expected and harmless (Phase 3 §1).
- **Footprint.** It rebuilds about 100 to 130 archived boards (about 5 s each) under the deployed `src/`. Phase 3 peaked
  at 1.2 GB.
- **Alternative with no box Python.** Copy `underlying_trades.sqlite` to a private location off the box, then run
  `--ledger <copy>` on a development checkout. The tracked `exports/archive` holds the same boards. Add
  `--write-rows <private path>` to keep the priced rows for re-evaluation (`--rows`). Both refuse paths inside
  the repository.

**Acceptance and reading:**

1. Exit 0, `readOnlyGuard.refusedWriteOrProcessAttempts == 0`, and the output passes the script's aggregate-only
   check.
2. `rules.R0_decisive == true`. Phase 3's ledger had 10,893 unequal-count trades in 11,565 leagues, so R0 should
   pass.
3. Read q from `rules.D1_momentQ_vs_078`, `qFit.qMomentCi95`, `outOfSample.J` (M078 against MMOM) and
   `rules.D1_R2_levelEffectExplainsLowQ_moment`. **Do not read R1 as a test of q (D1).**
4. Read the bands from `bands.byQ.0.78.excessOver1v1` (shape neutrality, with intervals),
   `againstConsolidatorShareOfNotFair`, the class rows and `bands.stabilityVs078`.
5. Commit the output byte for byte beside `results.json` as `production_run_<date>.json` and record its sha256.

**What would move q.** All three conditions are needed:

- the moment interval excludes 0.78;
- J out of sample favours MMOM over M078;
- R2 on moment fits is **false**, meaning the level diagnostic does not explain the low q.

If R2 is true, which Phase 3's decomposition predicts, the evidence points to the level layer of §8 option 4, not
to q.

## 8. Options for the owner

| # | option | evidence for | evidence against | change |
|---|---|---|---|---|
| 1 | **Keep q = 0.78 and `fairness_bands_v2` as declared priors, and authorize the one read-only box run (§7)** | q = 0.78 beats raw sums everywhere measured. The production shortfall is mostly the level effect (Phase 3 R1). The local data cannot decide anything. | It leaves a known 1-for-N shortfall (−0.29) in place until the run | none in production |
| 2 | **Restate OD-F4**: from "validate 3.5 / 9 / 18 on at-the-time market trades" to "shape-neutral and stable on accepted trades (measured here), plus an outcome-based check later" | Accepted trades sit about 20 % apart on the board even at 1-for-1, so cut points cannot be validated from them (A1 against A3) | none; it narrows what OD-F4 can promise | a config comment and status only, by a separate owner-approved change |
| 3 | Lower q toward the shape-only market fit (≤ 0.50) | It fits accepted unequal trades better on calibration | Level confound (Phase 3 R1 / R2). It double-counts roster-spot costs already charged by team context. It distorts elite and starter-for-starter trades. Least-squares fitting is biased (D1). | not recommended |
| 4 | Design a level-aware "trade currency" layer (about 2,000 points per piece), kept separate from q | Phase 3: c = 2,000 flattens the residual at every value level and in both sources | It is a valuation-owner question about sub-replacement assets, and it overlaps team context | separate design and owner decision; out of scope |
| 5 | Roll back to `ktc_2026_04` | none here | KTC is non-monotone (Phase 3 §7) | not recommended |

**Recommendation: options 1 and 2.** Nothing in production changes. One owner-authorized box run settles the q
question under D1. OD-F4 is restated to what accepted trades can actually show.

## 9. Verification and what is not verified

- **Tests.** `python -m pytest tests/scripts/test_package_model_validation.py -q` gives 33 passed. Hand-computed
  utilities and residuals (for example U_0.78([5000, 3000]) = 7,340 and r = −340 / 6,830 for 6,000 against
  4,000 + 3,000). Band labels through the owner (slight at q = 0.78, unfair at q = 1). Date folds never split a
  date. Recovery of a known q. Bootstrap weights. Point-in-time and all-or-nothing pricing. The own-league label
  adapter. The aggregate-only guard. The D1 estimator behaviour.
- **Gates.** `tests/scripts/test_research_band_basis_guard.py` passes. `bash scripts/format_python_changes.sh`
  is GREEN.
- **Not verified:**
  - the box run;
  - the ledger's current size;
  - the script's `--box` path under the real guard and deployed `src/` (the `--rows` and `--own-league` paths
    were run; `--ledger` was not run on a real ledger copy);
  - whether pick-heavy and IDP strata reach useful precision on the box.
- **Reproduction.** On D-OWN, run
  `ALLOW_DEFAULT_LOGIN_DEV=1 UPTIME_CHECK_ENABLED=0 python scripts/research/package_model_validation.py --own-league --power --out <file>`.
  It is seeded, so the numbers reproduce; `generatedAt` and `codeSha` differ.
