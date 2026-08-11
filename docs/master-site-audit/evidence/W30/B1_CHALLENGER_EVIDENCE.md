# B1 challenger evidence — W30-F008 percentile-coordinate repair

**Status: CHALLENGER ONLY. Nothing promoted, nothing applied, no production
constant changed.** The champion below is still live.

Generated 2026-08-11 on pinned inputs. Reproduce with
`docs/master-site-audit/evidence/W30/b1_denominator_measure.py` and the refit
command in §2.

---

## 1. Pinned input state

Re-verified immediately before the refit: **all 8 fit sources unchanged**, so
challenger-vs-champion differences are attributable to model methodology rather
than scraper movement.

| file | sha256₁₆ |
|---|---|
| `CSVs/site_raw/ktc.csv` | `0cbf7f20f32c5927` |
| `CSVs/site_raw/dynastyDaddySf.csv` | `fafd71c15e2e18f2` |
| `CSVs/site_raw/dynastyNerdsSfTep.csv` | `fe232d5ef61c7379` |
| `CSVs/site_raw/yahooBoone.csv` | `27cdfd58e4f4e7db` |
| `CSVs/site_raw/fantasyProsFitzmaurice.csv` | `a834e5f371c49970` |
| `CSVs/site_raw/draftSharksSf.csv` | `2a656d65e0514479` |
| `CSVs/site_raw/idpTradeCalc.csv` | `00a43e7aaa6ce0d9` |
| `CSVs/site_raw/draftSharksIdp.csv` | `f5fe62320c7e1837` |

**Board snapshot** (position filter + IDPTC values behind the IDP scope):
`data/dynasty_data_2026-08-10.json`, sha256 `9199883f9e0aea59955ade05febc00eb…`,
835,413 B — byte-identical to the committed `exports/latest/` copy. Forced via
`RISKIT_FIT_SNAPSHOT` rather than left to mtime.

**Holdout contamination: CLEAN.** Holdout labels
(`FantasyCalc`, `FantasyNavigator`, `OTCFFB`, `PFKDynasty`) share no file with
the six training labels.

## 2. Refit command

```bash
RISKIT_FIT_SNAPSHOT="$PWD/data/dynasty_data_2026-08-10.json" \
  .venv/bin/python scripts/fit_hill_curve_percentile.py
```

The script prints suggested constants and writes nothing.

## 3. Champion vs challenger constants

| scope | champion c | champion s | challenger c | challenger s | master-fit RMSE (challenger) |
|---|---|---|---|---|---|
| GLOBAL | 0.1120 | 0.725 | **0.0890** | **0.720** | 14.0 |
| OFFENSE | 0.1100 | 1.110 | **0.0770** | **1.110** | 39.2 |
| IDP | 0.0830 | 1.110 | **0.0380** | **0.870** | 60.0 |
| ROOKIE (not routed) | 0.0250 | 0.890 | 0.0220 | 0.870 | 19.9 |

`c` falls in every scope, which is the expected direction: the correction places
each training row at a **smaller** percentile than before, so the curve must
decay faster to fit the same values. OFFENSE and GLOBAL keep their slope; **IDP
changes shape** (1.110 → 0.870), and that is the parameter governing the tail.

## 4. Holdout — OFFENSE only

```
champion   c=0.1100 s=1.110   criterion 1160.29
challenger c=0.0770 s=1.110   criterion  671.21      improvement +42.2%
```

| board | rows | champion | challenger | delta | verdict |
|---|---|---|---|---|---|
| FantasyCalc | 398 | 1185.42 | 608.13 | −577.29 | BETTER |
| FantasyNavigator | 400 | 1530.16 | 946.52 | −583.63 | BETTER |
| OTCFFB | 380 | 1436.51 | 821.98 | −614.53 | BETTER |
| PFKDynasty | 400 | 489.07 | 308.23 | −180.85 | BETTER |

Unanimous, and large. **This is evidence for OFFENSE and nothing else** — see §7.

## 5. Representative rank effects

Rank 1 is unchanged in every scope by construction (p = 0 → 9999).

| rank | OFFENSE | GLOBAL | IDP |
|---|---|---|---|
| 25 | −12.2% | −6.1% | −30.6% |
| 50 | −18.5% | −7.9% | −32.9% |
| 100 | −24.2% | −9.6% | −30.3% |
| 200 | −28.2% | −11.0% | −23.1% |
| 400 | −30.4% | −12.0% | −11.9% |

Every value falls. That is the defect being undone: the champion was serving
above what it was ever scored against.

## 6. Cross-scope balance — the part that reorders the board

IDP value as a share of OFFENSE value at the same rank:

| rank | champion | challenger | shift |
|---|---|---|---|
| 25 | 0.905 | 0.715 | **−21.0%** |
| 50 | 0.853 | 0.703 | −17.6% |
| 100 | 0.805 | 0.741 | −8.1% |
| 200 | 0.772 | 0.825 | +7.0% |
| 400 | 0.752 | 0.952 | **+26.7%** |

IDP gets materially **cheaper at the top and dearer at the tail**. GLOBAL/OFFENSE
moves +6.9% (rank 25) to +26.6% (rank 400) the same way.

### Board impact — measured, not modelled

Both boards rebuilt in-process from the pinned snapshot (no file writes),
787 comparable priced rows:

* **762 of 787 rows change overall ordinal.** This is a REORDERING, not a
  rescaling.
* mean |rank shift| **51.87**, max **196**, and **618 rows move more than 10
  places**.

Largest absolute value movers (all fall; TEs and mid-board offense dominate):

| player | pos | champion | challenger | delta | rank |
|---|---|---|---|---|---|
| Harold Fannin | TE | 5736 | 4638 | −19.1% | 48→59 |
| Cam Ward | QB | 5006 | 3914 | −21.8% | 71→87 |
| Tucker Kraft | TE | 5713 | 4637 | −18.8% | 49→60 |
| Rome Odunze | WR | 4991 | 3924 | −21.4% | 72→86 |
| DeVonta Smith | WR | 5188 | 4133 | −20.3% | 64→78 |

Largest ordinal movers, and the pattern is systematic — **offense down, IDP up**:

| player | pos | rank shift | value |
|---|---|---|---|
| Ollie Gordon | RB | 405 → 601 (−196) | 1792 → 1219 |
| Chimere Dike | WR | 400 → 594 (−194) | 1802 → 1236 |
| Jonathon Cooper | DL | 678 → **495** (+183) | 1251 → 1323 |
| Chris Jones | DL | 695 → **513** (+182) | 1204 → 1299 |
| Trevin Wallace | LB | 651 → **490** (+161) | 1343 → 1338 |

## 7. Methodological concerns — why this is not a promote recommendation

**7.1 There is no holdout for GLOBAL or IDP.** `evaluate_offense_master` is the
only evaluator in `src/model_registry/holdout.py`. The +42.2% validates the
OFFENSE challenger. The GLOBAL and IDP challengers have **zero out-of-sample
validation**, and IDP is the scope that changed shape and drives the reordering.

**7.2 IDP extrapolates over a quarter of the served universe.** Its fit sees
370 rows → percentiles `[0, 0.7395]`. Serving runs to `p = 1.0`. Ranks
**371–500 (26% of the universe) are extrapolation**, and that is exactly where
the IDP slope change lands the biggest relative gains (+26.7% at rank 400,
DL/LB rows climbing ~180 ordinal places).

**7.3 One of the two IDP training sources barely constrains the curve.**
`DraftSharks-IDP` has 146 rows → trained only to `p = 0.2906`. It is averaged
into the IDP master with equal voice while observing the top 29%.

**7.4 The tail is unobserved for every scope, and the old system hid it.**
Holdout boards are 380–400 rows, so even the OFFENSE validation only tests to
`p ≈ 0.8`. Stretching short sources to 1.0 used to manufacture the appearance of
coverage; the correction is right precisely because it stops doing that — but
it makes visible that the deep board was never observed by anything.

**7.5 ADR-008's narrowing rests on a coordinate artifact.** It narrowed its
headline claim because the holdout improvement was three boards outvoting
PFKDynasty. Under the corrected coordinate all four agree and PFKDynasty is the
biggest gainer (552.03 → 283.81). The ADR should be revisited — an owner
decision, not one this evidence makes unilaterally.

## 8. What would settle it

1. A holdout for IDP and GLOBAL, with sources genuinely held out of their fits.
2. A decision on tail behavior: either declare the reference universe to be what
   is actually observed, constrain the curve past the last observed row, or
   accept extrapolation explicitly and say so on the board.
3. Re-run §4–§6 against that, on this same pinned input state.

## 9. Verdict

**MORE EVIDENCE REQUIRED.** The coordinate repair itself is sound and is
already merged; the OFFENSE challenger is well-evidenced. Promoting GLOBAL and
IDP on this evidence would be promoting two unvalidated curves — one of which
reshapes the board's cross-scope balance and moves 618 rows more than ten
places — on the strength of a holdout that never scored them.
