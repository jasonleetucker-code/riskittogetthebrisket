# OTC re-measured against the Hill trainers, across snapshots (D2 follow-up, 2026-10-01)

**Status: evidence only.** No served value, weight, B10 family, Hill constant, registry
entry or manifest changed. Correlation is dependence, never ancestry.

| file | what it is |
|---|---|
| [`scripts/audit/lineage_pair_snapshots.py`](../../../scripts/audit/lineage_pair_snapshots.py) | the instrument (imports the 2026-10-01 sweep's primitives; tests in `tests/sources/test_lineage_pair_snapshots.py`) |
| [`OTC_PAIR_SNAPSHOTS_2026-10-01.json`](OTC_PAIR_SNAPSHOTS_2026-10-01.json) | every snapshot, every pair, every variant, with the CSV commit each board was read at |
| `config/sources/source_lineage.json` | the recorded relations and pairs (`otc-*`, `pair-otc-*`) |

Pins: instrument commit `ea23fab74`; inputs are the git history of `CSVs/site_raw` reachable
from `origin/main` `74342d588`. Each snapshot reads every board at its last committed version
at or before the instant, so nothing later than the instant is read.

## Why

Batch 3 D2 (PR #1598) used OTC (`otcffbSf`) as its only lineage-safe Hill holdout. Its review
found that clearance rested on ONE snapshot measured only against KTC Crowd and KTC Trades
(-0.204 / -0.146). Base `ktc`, which trains the Hill masters and carried the recorded +0.891,
was never re-measured as a named pair. OTC was never measured against Dynasty Daddy, Dynasty
Nerds, Yahoo/Boone, Fitzmaurice or Draft Sharks. The lineage owner was also half-updated:
`statistics` still held 0.891 and 0.329 beside refreshed summaries.

## Method

- **Snapshots:** 21 weekly instants, 2026-05-16 to 2026-10-01 at 23:59:59Z. OTC's history
  starts 2026-05-15. Dependence comes only from the CSV git history, as in the sweep. The export
  archive is not a dependence input to the sweep, so it is not one here.
- **Consensus pool:** today's voting registry. Before 2026-09-09 the KTC Crowd voter had no CSV,
  so its committed carrier `ktcSfTep` fills the pool (D2 precondition P1 found them identical).
  A carrier is never a measured member.
- **Statistic:** the sweep's leave-pair-out residual correlation of percentile ranks
  (`leave_pair_out_residuals`), offense only, picks excluded. It is computed under these variants:
  - `lpo` is the sweep's rule exactly: per-board percentiles, with both members removed from the consensus.
  - `lfo` also removes both members' B10 families and providers from the consensus.
  - `cp_*` re-ranks every board inside ONE common population: the two members, plus every
    consensus board covering at least 60% of their shared players.
  - `cpx_*` is `cp_*` with TE rows removed.
- **Value space:** the D2 metric compares spacing, so the same construction runs on
  ln(value / board max). `valueResidualRaw` includes any curve shape the two boards share.
  `valueResidualDetrended` removes each residual's cubic in the consensus first. That leaves
  player-specific value agreement beyond shape.
- **Indirect path:** the OTC to FantasyCalc to Dynasty Daddy path is tested with a partial
  correlation r(OTC, DD | FC) on residuals. All three boards are excluded from the consensus.
- **Controls:** four pairs with a recorded sweep verdict, measured in the same run.

## Two instrument findings (they change the answer)

1. **Per-board percentiles confound board depth.** A 370-row board and a 460-row board sit on
   different percentile scales. So two boards of similar depth share a residual whatever their
   opinions are. On synthetic boards with independent noise (pinned by test), the sweep statistic
   for two deep boards is about +0.5 and the common-population statistic is about +0.1. On real
   boards, OTC's offense population dropped from about 435-455 rows to about 360-367 rows on
   2026-09-12. It also dropped briefly on 07-11 and 08-08. The sweep statistic against base KTC
   swings with it, from -0.20 to +0.91. The common-population statistic stays at +0.09 to +0.65.
   The controls move the same way: PFK vs base KTC falls from +0.57 to +0.06. Fitzmaurice vs
   Dynasty Nerds, two shallow boards, falls from +0.50 to +0.10. DLF vs KTC stays negative.
   FantasyCalc vs Dynasty Daddy rises from +0.60 to +0.84.
2. **The TE basis manufactures disagreement.** OTC is non-TEP, while KTC Crowd, Trades and
   `ktcSfTep` are TE++. With TE rows kept, OTC vs `ktcSfTep` measures -0.13. With TE rows removed
   it is identical to base KTC, at +0.45. That is expected, because the two boards differ only in
   TE values. Last sweep's "not reproduced" (-0.204 / -0.146) was this artifact plus depth.

**Leave-pair-out baseline.** Two residuals against one consensus share its error. That puts a
positive floor of about 1/(k+1) under the statistic, which is about +0.08 to +0.10 for the 9 to
12 consensus boards used here. Small positive values must be read against that floor.

## Results — OTC vs each Hill trainer (21 snapshots)

`lpo` is the sweep's method. `cpx_lfo` is basis-neutral: common population, no TE rows, and the
members' families removed from the consensus. Ranges are [min, max] across snapshots. "pos" is
the number of snapshots with a positive statistic. n is the median players per snapshot. "dist.
versions" counts the comparator's distinct CSV versions inside the window.

| comparator | rank `lpo` | **rank `cpx_lfo`** | pos | n | value raw `cpx_lfo` | **value detrended `cpx_lfo`** | pos | value detrended `lpo` | snapshots / dist. versions | category |
|---|---|---|---|---|---|---|---|---|---|---|
| `ktc` (base) | +0.25 [-0.20, +0.91] | **+0.45 [+0.09, +0.65]** | 21/21 | 209 | +0.56 [+0.01, +0.84] | **+0.44 [+0.22, +0.77]** | 21/21 | +0.57 [+0.05, +0.93] | 21 / 21 | MEASURED_DEPENDENCE |
| `ktcSfTep` | -0.18 [-0.35, +0.54] | **+0.45 [+0.09, +0.65]** | 21/21 | 209 | +0.56 | **+0.44** | 21/21 | +0.27 [-0.08, +0.75] | 21 / 21 | MEASURED_DEPENDENCE |
| `dynastyDaddySf` | +0.40 [-0.11, +0.59] | **+0.69 [+0.40, +0.84]** | 21/21 | 201 | +0.06 [-0.43, +0.49] | **+0.43 [-0.06, +0.68]** | 20/21 | +0.28 [+0.04, +0.55] | 21 / 21 | MEASURED_DEPENDENCE |
| `dynastyNerdsSfTep` | -0.10 [-0.37, +0.58] | **-0.05 [-0.17, +0.14]** | 8/21 | 201 | +0.58 [-0.07, +0.69] | **+0.15 [-0.06, +0.28]** | 20/21 | +0.16 [-0.10, +0.27] | 21 / 5 | SUSPECTED_DEPENDENCE (spacing only) |
| `yahooBoone` | +0.20 [+0.04, +0.32] | **+0.42 [+0.25, +0.50]** | 21/21 | 201 | +0.23 [-0.03, +0.47] | **+0.33 [-0.04, +0.55]** | 15/16 | +0.24 [+0.06, +0.46] | 21 / 6 | MEASURED_DEPENDENCE |
| `fantasyProsFitzmaurice` | -0.01 [-0.16, +0.62] | **+0.15 [-0.09, +0.31]** | 19/21 | 201 | +0.11 [-0.09, +0.28] | **+0.13 [-0.07, +0.24]** | 20/21 | +0.23 [-0.04, +0.49] | 21 / 6 | SUSPECTED_DEPENDENCE |
| `draftSharks` (`draftSharksSf.csv`) | +0.15 [-0.50, +0.38] | **-0.03 [-0.25, +0.06]** | 7/21 | 201 | — | — (values do not cover the common population) | — | +0.03 [-0.17, +0.27] | 21 / 16 | INDEPENDENT_NO_EVIDENCE |
| `fantasyCalc` (holdout, intermediary) | +0.47 [+0.21, +0.67] | **+0.65 [+0.40, +0.80]** | 21/21 | 201 | +0.36 [+0.04, +0.61] | **+0.46 [+0.12, +0.71]** | 21/21 | +0.52 [+0.23, +0.75] | 21 / 21 | MEASURED_DEPENDENCE |
| `ktcCrowdSfTep` (since 09-09) | -0.21 [-0.22, -0.20] | **+0.45 [+0.41, +0.52]** | 4/4 | 219 | +0.79 | **+0.35** | 4/4 | +0.04 | 4 / 4 | MEASURED_DEPENDENCE (in `pair-otc-ktc`) |
| `ktcTradesSfTep` (since 09-09) | -0.21 [-0.26, -0.15] | **+0.73 [+0.71, +0.75]** | 4/4 | 206 | +0.88 | **+0.70** | 4/4 | +0.01 | 4 / 4 | MEASURED_DEPENDENCE (in `pair-otc-ktc`) |

Controls, rank `lpo` and then `cpx_lfo`:

- DLF vs base KTC: -0.28, then -0.33 (0/21 positive).
- FantasyCalc vs Dynasty Daddy: +0.60, then +0.84 (21/21).
- Fitzmaurice vs Dynasty Nerds: +0.50, then +0.10 (20/21).
- PFK vs base KTC: +0.57, then +0.06 (8/10; PFK exists from 2026-08-01).

**Indirect path.** On the basis-neutral instrument, OTC vs Dynasty Daddy is +0.73 in rank.
Partialling out FantasyCalc leaves **+0.33** (20/21 positive, n about 201). The order dependence
is therefore not only the FantasyCalc path. In value space the partial is -0.15 (7/21 positive),
so there the path explains it. On the sweep's per-board percentiles the rank partial was +0.06,
which is depth-confounded.

**Category rule used here.** This rule was declared after looking at the data, and the owner may
revise it. The raw distributions are in the JSON. A pair is:

- `MEASURED_DEPENDENCE` when a basis-neutral rank or detrended-value median is at least +0.30,
  with at least 90% of snapshots positive.
- `SUSPECTED_DEPENDENCE` when a median is between +0.10 and +0.30, with at least 75% of
  snapshots positive. That is above the about +0.09 leave-pair-out floor, but weak.
- `INDEPENDENT_NO_EVIDENCE` otherwise.

Every OTC pair is dependence, not ancestry. Values are not copies (OTC publishes 0-100, and
there is 0 lagged value identity), and no vendor statement links OTC to any of them. Some of the
dependence may be shared evidence rather than lineage, for example trade-informed markets
reacting to the same trades.

## Is OTC an ancestry-safe holdout?

**No, not for any current OFFENSE trainer set, and therefore not for D2.** No ancestry is proven.
But the preregistered D2 rule excludes any holdout with a proven, suspected or currently positive
measured relation to a board an arm trains on. OTC is now excluded:

- **KTC-trained arms** (base `ktc`: C0, M1, M2; Crowd TE++: M3; Trades: M5-M8). OTC has measured
  dependence on base KTC in 21 of 21 snapshots, in both order and shape-removed spacing.
- **Dynasty Daddy** (C0, M1, M3). Measured dependence in 21 of 21 snapshots, and still positive
  after partialling out FantasyCalc.
- **Yahoo/Boone** (M1 "five"). Measured dependence in 21 of 21.
- **Fitzmaurice** and **Dynasty Nerds** (M1 "five"). Weak suspected dependence, which is
  excluding under the D2 rule.
- **Draft Sharks.** No evidence of dependence. This does not rescue anything, because every arm
  also trains on KTC.

Under a strict reading there is **no ancestry-safe board holdout at all**. PFK, FantasyCalc and
Fantasy Navigator were already excluded, and OTC now joins them. D2's verdicts compare arms by
closeness to a board that depends on their trainers. They are not evidence against an independent
market. **Hill evaluation needs a non-board target**, such as the completed-trade ledger. KTC
Trade Database trades are KTC-platform trades and are in-sample for KTC Trades, so they must be
reported per family, or a non-KTC trade population is needed.

## Lineage owner changes (`config/sources/source_lineage.json`)

- **Stale statistics completed.** Every relation's `statistics` is now a dated history
  `{"measurements": [...]}`: method, window, n and values. Exactly one entry is `current`, and it
  carries the relation's `asOf`. Superseded values are kept, not overwritten: 0.891 (2026-07-27)
  and -0.204 / -0.146 (2026-10-01, single snapshot) on `otc-ktc-dependence`, and 0.329
  (2026-08-04) and +0.511 (2026-10-01 sweep) on `otc-fc-dependence`. The same applies to the ten
  other relations whose `statistics` lagged their summaries.
- **Validator.** `source_census._validate_statistics` enforces that shape. A refresh can no longer
  move `asOf` without adding a measurement, and it cannot overwrite an old value.
- **Relation changes.** `otc-ktc-dependence` is re-measured and now names `ktcSfTep`.
  `otc-fc-dependence` is refreshed. `otc-dd-dependence` and `otc-boone-dependence` are new.
- **Pairs.** `pair-otc-ktc`, `pair-otc-ktcsftep`, `pair-otc-dynastydaddy`, `pair-otc-boone`,
  `pair-otc-fitzmaurice`, `pair-otc-dynastynerds` and `pair-otc-draftsharks` are added, each with
  the five implication axes.
- **Pointers.** The OTC source entry gets a note, and the evidence pointers are updated.

## Not changed, and why

- **Recorded verdicts on other pairs** (PFK-KTC +0.687, Fitzmaurice-Nerds +0.643, and others) are
  not re-classified. Their controls suggest they are partly the depth artifact. That review is a
  separate unit, and notes are attached to their current measurements.
- **`training_manifest._MEASURED_DEPENDENCES`** still carries 0.33 / 0.677 / 0.45. It is a
  second copy of dependence numbers inside the Hill manifest, and editing it could change
  manifest hashes. It is out of scope for an evidence-only change.
