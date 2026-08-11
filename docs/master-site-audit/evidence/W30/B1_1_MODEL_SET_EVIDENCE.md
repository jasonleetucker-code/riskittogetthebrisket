# B1.1 — model-set evidence extension (W30-F008)

**Status: EVIDENCE ONLY. Nothing promoted, nothing applied, no production
constant changed.** The champion in `src/canonical/player_valuation.py` is
untouched and still matches registry v2 exactly.

Generated 2026-08-11 on the same pinned inputs as B1 (`data/dynasty_data_2026-08-10.json`,
the eight fit CSVs unchanged — see `B1_CHALLENGER_EVIDENCE.md` §1). Reproduce with
`b1_1_model_set_measure.py`; machine-readable output in `b1_1_model_set_report.json`.

B1 ended at **MORE EVIDENCE REQUIRED** for three reasons: GLOBAL and IDP have no holdout,
IDP extrapolates over a quarter of its served universe, and one IDP training source observes
only its top 29%. This file answers what that verdict left open.

---

## 1. Q4 — the fit-vs-serve coordinate trace

**Verdict: CONSISTENT.** After B1, the fitter, the holdout evaluator and the serving path all
call the same `rank_to_percentile`. There is no coordinate mismatch left to find. What the
trace does expose is a **coverage** gap — a different thing, and one B1 only characterised for
IDP:

| scope | deepest observation | extrapolated share of the universe | first extrapolated rank |
|---|---|---|---|
| GLOBAL | p = 0.7996 | 20.0% | 401 |
| OFFENSE | p = 0.7996 | 20.0% | 401 |
| IDP | p = 0.7395 | 26.1% | 371 |

And the reason differs by scope, which is the part worth knowing:

```
OFFENSE  KTC          500 rows -> trains 400   (TRUNCATED)
         YahooBoone   418 rows -> trains 400   (TRUNCATED)
         DraftSharks  411 rows -> trains 400   (TRUNCATED)
         DynastyDaddy 373 rows -> trains 373
         Fitzmaurice  299 rows -> trains 299
         DynastyNerds 294 rows -> trains 294
GLOBAL   IDPTradeCalc         900 rows -> trains 400   (TRUNCATED)
         DraftSharks-Combined 557 rows -> trains 400   (TRUNCATED)
IDP      IDPTradeCalc-IDP     370 rows -> trains 370
         DraftSharks-IDP      146 rows -> trains 146
```

**GLOBAL's and OFFENSE's blind tail is self-inflicted.** `FIT_TOP_N = 400`, not source depth,
is what stops them at p = 0.7996. KTC publishes exactly 500 rows and IDPTradeCalc 900, so
raising the truncation would let each scope's *deepest* source observe out to p = 1.0 —
the rows are already in CSVs the fit opens. IDP's tail is the real thing: 370 rows is all
IDPTradeCalc's IDP slice has, and nothing available extends it.

This matters because B1's §7.4 concluded "the tail is unobserved for every scope" and left it
there. For two of the three scopes it is unobserved **by policy**, and the policy is one line.

**And "deepest observation" understates it, because the master is not fit on observations.**
`_fit_scope_master` builds a percentile grid running to p ≈ 0.995, evaluates **every**
per-source fitted Hill at every grid point, averages, and fits one curve to that average. A
source therefore contributes to the whole grid whether or not it observed any of it — its own
curve is extrapolated there first, then averaged with equal weight. So the tail of a scope
master is shaped as much by the extrapolations of its shallow sources as by the observations
of its deep ones. This is the mechanism behind §30's IDP result: DraftSharks-IDP sees the top
29% and still votes across 100% of the grid.

## 2. Q5 — the tail clamp, measured on the live board

`rank_to_percentile` clamps at 1.0. Every rank past `PERCENTILE_REFERENCE_N` (500) therefore
receives an **identical percentile, and so an identical value**, from that source. Meanwhile
`OVERALL_RANK_LIMIT` is 800 — the board publishes 300 ranks deeper than the coordinate can
distinguish.

Counted on the real contract's `sourceRanks` (post-identity-join, so these are observations
that actually vote):

**877 of 7,130 served observations (12.3%) sit at the clamp, touching 487 of 1,095 board rows.**

| source | clamped / observations | % |
|---|---|---|
| `draftSharksIdp` | 203 / 318 | **63.8** |
| `idpShow` | 202 / 347 | **58.2** |
| `idpTradeCalc` | 399 / 899 | **44.4** |
| `dlfRookieIdp` | 8 / 29 | 27.6 |
| `flockFantasySfRookies` | 12 / 75 | 16.0 |
| `dlfIdp` | 24 / 170 | 14.1 |
| `draftSharks` | 26 / 411 | 6.3 |
| `fantasyProsIdp` | 3 / 143 | 2.1 |

Every other source clamps **zero** rows.

Two conclusions, and they are independent of any challenger:

* **This is an IDP pathology, not a board-wide one.** The majority of three IDP sources'
  votes are compressed onto one point. A defender at that source's rank 520 and one at its
  rank 899 contribute exactly the same number.
* **It is live today, under the champion.** No promotion decision touches it. It is a defect
  of the reference universe, and it should be recorded as one rather than folded into the
  promote/don't-promote question.

## 3. §18 — reference-universe candidates

B1 unified fit and serve onto N = 500 because 500 is what serving already used — not because
500 was shown to be right. Refitting every scope under the defensible alternatives, and
scoring OFFENSE (the only scope with a holdout) **in the serving coordinate** so the
candidates are comparable to each other:

| universe | GLOBAL | OFFENSE | IDP | OFFENSE holdout criterion |
|---|---|---|---|---|
| 400 (`FIT_TOP_N`) | 0.1120 / 0.720 | 0.0960 / 1.115 | 0.0480 / 0.875 | 927.77 |
| **500 (current)** | 0.0890 / 0.720 | **0.0770 / 1.110** | 0.0380 / 0.870 | **671.21** |
| 800 (`OVERALL_RANK_LIMIT`) | 0.0560 / 0.730 | 0.0480 / 1.110 | 0.0240 / 0.870 | 502.12 |

Champion, for reference: 1160.29.

### The adversarial check this needed

A criterion that improves monotonically as values fall is a criterion that would crown a curve
returning zero. It does not:

| c (s = 1.110) | criterion |
|---|---|
| 0.1100 (champion) | 1160.29 |
| 0.0770 (challenger) | 671.21 |
| 0.0520 | **488.77 (argmin)** |
| 0.0200 | 1230.49 |
| 0.0100 | 1707.88 |
| 0.0005 | 2446.11 |

There is a genuine interior optimum near c ≈ 0.052, and the N = 800 refit (0.0480) lands
within 2.7% of it. Fitting under a deeper universe independently recovers the curve the
holdout prefers.

### But the mean hides a split — and that is the decision

Sweeping c at s = 1.110 (`s18_unanimity_sweep`, full table in the JSON) and asking not "is the
mean lower" but "is **every** holdout board better than champion":

| region | c range | best criterion | unanimous? |
|---|---|---|---|
| unanimous improvement | **0.0680 – 0.1080** | 579.69 at c = 0.0680 | yes |
| mean-optimal | c ≈ 0.0520 | 488.77 | **no** — PFKDynasty +326 worse |
| N = 800 refit | c = 0.0480 | 502.12 | **no** — PFKDynasty +430 worse |

The three deep boards (FantasyCalc, FantasyNavigator, OTCFFB) keep improving as c falls well
past 0.068. PFKDynasty turns around and gets much worse. So:

* **The challenger (c = 0.0770) sits inside the unanimous region** — that is why B1's §4
  found all four boards agreeing.
* **It is not the best point in that region.** c ≈ 0.0680 is unanimous *and* scores 579.69
  against the challenger's 671.21.
* **"Just use N = 800" is not supported.** It buys its mean by giving up unanimity, which is
  precisely the trade ADR-008 declined to make.

## 4. §30 / §31 — leave-one-source-out

For OFFENSE, dropping a training source and re-scoring on the untouched holdout is a real
generalisation test. For GLOBAL and IDP there is no holdout, so the only honest measure is how
far the master **moves** — sensitivity, not quality.

### OFFENSE (full fit: c = 0.0770, criterion 671.21)

| dropped | depth | c / s | holdout | value shift @25 / @100 / @400 |
|---|---|---|---|---|
| KTC | 400 | 0.0720 / 1.185 | **576.37** | −1.7% / −10.7% / −21.3% |
| Fitzmaurice | 299 | 0.0700 / 1.100 | **605.71** | −4.1% / −6.9% / −7.3% |
| DraftSharks | 400 | 0.0820 / 1.200 | 671.22 | +4.3% / −0.7% / −11.9% |
| YahooBoone | 400 | 0.0770 / 1.090 | 687.54 | −0.4% / +1.4% / +4.4% |
| DynastyDaddy | 373 | 0.0800 / 1.085 | 727.53 | +1.1% / +4.9% / +9.7% |
| DynastyNerds | 294 | 0.0820 / 1.050 | 791.03 | +1.4% / +9.4% / +21.0% |

**Removing KTC improves out-of-sample fit by 95 points.** KTC is the deepest offense training
source and the market maker most of the board's other consumers already anchor on; it is
pulling the master away from what four independent retail boards say. DynastyNerds, the
shallowest at 294 rows, is the one source whose removal clearly hurts.

This is not an argument to drop KTC — it is one holdout on one day, and KTC's role in the
platform is much larger than this fit. It is an argument that **the OFFENSE master's source
mix has never been examined**, and the assumption that every source deserves equal voice is
untested.

### GLOBAL (full fit: c = 0.0890) — two sources, opposite pulls

| dropped | c / s | value shift @25 / @100 / @400 |
|---|---|---|
| IDPTradeCalc | 0.0520 / 0.710 | −15.6% / −22.5% / −26.4% |
| DraftSharks-Combined | 0.1490 / 0.780 | +16.1% / +23.6% / +24.4% |

### IDP (full fit: c = 0.0380) — the decisive result

| dropped | depth | p observed | c / s | value shift @25 / @100 / @400 |
|---|---|---|---|---|
| DraftSharks-IDP | 146 | ≤ 0.291 | 0.0650 / 0.785 | **+24.5% / +53.2% / +85.5%** |
| IDPTradeCalc-IDP | 370 | ≤ 0.740 | 0.0240 / 1.130 | **−30.2% / −56.1% / −71.7%** |

The IDP master is an average of two curves that disagree by a factor of roughly six at rank
400. Which of the two is in the room moves every IDP value by more than half. And one of them —
DraftSharks-IDP — casts an equal vote while observing only the top 29% of the curve it is
shaping, so its influence over the tail is entirely extrapolated.

**There is no configuration of this evidence in which promoting the IDP challenger is
justified.** It is not that the challenger is worse than the champion; it is that neither
number is supported by anything, and the scope's own inputs do not agree on the answer to
within a factor of six.

## 5. §39–§43 — coherent model sets

Two promotion sets are internally coherent. Board impact of each, rebuilt in-process against
the champion on the pinned snapshot:

| set | rows reordered | mean \|rank shift\| | max | rows moving > 10 |
|---|---|---|---|---|
| **OFFENSE-only** (every member validated) | 788 / 799 | **63.52** | 228 | 680 |
| **all three** (B1's full challenger) | 762 / 787 | 51.87 | 196 | 618 |

**The counter-intuitive result is the important one: promoting only the validated scope churns
the board MORE than promoting all three.** Moving OFFENSE alone changes the cross-scope
balance unilaterally — offense rows fall while IDP rows stay put, so the two populations
interleave differently. Moving all three preserves more of the relative ordering because both
populations move together.

So "promote only what is validated" is not the low-risk option it sounds like. It is the
option with *more* user-visible disruption and *less* justification for the balance it lands
on.

**Control, because the comparable-row counts differ (799 vs 787).** Each row above is measured
against its own intersection with the champion board, so the counts are not identical and the
result could in principle be an artifact of which rows each candidate happens to price.
Re-measured over the **single** intersection of all three boards — 786 rows scored identically
for every candidate:

| set | reordered | mean \|shift\| | max | > 10 |
|---|---|---|---|---|
| OFFENSE-only | 775 / 786 | **62.22** | 227 | 652 |
| all three | 761 / 786 | 51.76 | 196 | 616 |

Same conclusion, same margin. The result is not a row-set artifact.

Largest movers under OFFENSE-only — uniformly mid-board offense falling:

| player | rank | value |
|---|---|---|
| Mac Jones | 336 → 564 | 2028 → 1358 |
| Troy Franklin | 348 → 569 | 1987 → 1338 |
| Skyler Bell | 353 → 573 | 1970 → 1325 |

## 6. §33 — ADR-008 reassessment

B1 §7.5 said ADR-008 "should be revisited": it had narrowed its headline claim because the
holdout improvement was three boards outvoting PFKDynasty, and under the corrected coordinate
all four agreed.

**That reading is right about the 2026 instance and wrong about the principle.** §3 above
shows the 3-vs-1 split is not an artifact that the coordinate repair removed — it is a
structural property of this holdout set that reappears the moment c falls below ~0.068.
PFKDynasty is a genuinely different market from the other three, and any criterion that
averages it away will keep recommending curves it disagrees with.

Recommended amendment, for the owner to accept or decline:

1. **Keep** ADR-008's caution; it was correct, and §3 demonstrates the failure mode it guards
   against on live data.
2. **Correct** its stated reason. The narrowing was attributed to challenger v3 being weak.
   Under the repaired coordinate the champion itself is the outlier, and the pre-B1 scores in
   the registry were all measured in the defective coordinate.
3. **Add** unanimity as an explicit promotion condition alongside the 25-point margin. It is
   already the de facto rule — v2's promotion note cites "improving all four holdout sources
   with no sign flips" — but it is prose in a note, not a gate in `promotion.py`.

Not proposed here: re-scoring the registry's historical criteria. Those numbers were measured
on their own days' boards against a criterion that drifts ~68 points week to week; a
retroactive re-score would be a new measurement wearing an old date.

## 7. §54 — refit automation safety review

The workflow is materially safer than ADR-008 found it. Verified at HEAD:

* it commits `config/model_registry/` and nothing else (pinned by
  `tests/model_registry/test_refit_path_characterisation.py`);
* it cannot import the constant writer, let alone call it;
* the gate is a direct function call, not a pytest selection that a marker filter can
  deselect;
* an unevaluable gate exits 2 (red), not 0.

One gap remains, and B1 is what made it visible:

**The weekly refit does not pin its board snapshot.** `RISKIT_FIT_SNAPSHOT` — added in B1
precisely so a fit can be tied to an exact snapshot — appears nowhere under `.github/`. The
scheduled refit therefore falls through to `_latest_snapshot()`, which selects by **mtime**
across `data/` then `exports/latest/`. The IDP scope's IDPTradeCalc slice and the whole ROOKIE
scope are derived from that snapshot, so two of the four scopes are fit against an input the
run neither pins nor records. Setting the env var in the workflow is a one-line change; it is
not made here because §11 of the execution order keeps this step to evidence.

## 8. §55 — model registry provenance gap

Reading `config/model_registry/hill_scope_masters.json` at HEAD (champion v2; v1 retired,
v3 rejected):

**8.1 The registry pins 6 inputs for a model set with at least 10.** `training_input_paths()`
returns `source_roles()` filtered to `role == "train"`, which is `OFFENSE_TRAINING_SOURCES`
only. Every recorded version therefore fingerprints KTC, DynastyDaddy, DynastyNerds,
YahooBoone, Fitzmaurice and DraftSharks-SF — and stores params for **eight constants across
four scopes**. Not fingerprinted: `idpTradeCalc.csv` (GLOBAL), `draftSharksIdp.csv` (IDP), and
the board snapshot the IDP slice and every rookie slice are cut from. This is the same defect
class as B1's own finding F, fixed in the evidence instrument and still live in production.

**8.2 The holdout scores one scope; promotion moves all four.** `HoldoutResult.params` is a
single `{c, s}` pair and `VALIDATED_PARAMS` is literally `("HILL_PERCENTILE_C",
"HILL_PERCENTILE_S")`. The v1 → v2 promotion moved GLOBAL from 0.113/0.87 to 0.112/0.725 and
IDP from 0.093/0.97 to 0.083/1.11 — a slope change of 14% on GLOBAL — with **zero
out-of-sample evidence for either**. v2's note ("improving all four holdout sources") is true
of the OFFENSE curve and silent about the other six constants that rode along. This has
already happened in production; it is not a hypothetical risk of promoting B1's challenger.

**8.3 `measuredAt` is null on all three versions.** The field's own docstring explains it
exists because the criterion drifts ~19 points on identical parameters in 7 days against a
25-point promotion margin. It is unpopulated everywhere, and the dates survive only as prose
inside `notes`.

**8.4 `appliedAt` is null on the champion, which IS applied.** v2's params match
`player_valuation.py` exactly, all eight constants including ROOKIE 0.1530/0.885. ADR-008 split
promote from apply so a human performs the second step; the registry records the first and not
the second, so it cannot answer "are the live constants the champion?" — the question the
split was created to make askable.

## 9. What is now settled, and what is not

Settled by this file:

* the coordinate is consistent (Q4); the remaining gap is coverage, and two thirds of it is a
  one-line policy choice
* the tail clamp is real, live, quantified, and IDP-specific (Q5)
* the challenger is inside the unanimous-improvement region but not at its optimum (§18)
* the IDP master is not supportable at any setting — its two sources disagree by ~6× (§30)
* promoting the validated scope alone churns the board more, not less (§39)

Not settled, and not settleable without new inputs:

* **a holdout for GLOBAL and IDP.** Re-confirmed at HEAD by reading the fetchers and the CSV
  headers, not by trusting the source names:

  | candidate | header | why it cannot serve as holdout |
  |---|---|---|
  | `fantasyProsIdp` | `…,normalizedValue,…` | the value column is **manufactured by us**: `scripts/fetch_fantasypros_idp.py:381` writes `_hill_curve_value(eff)`, a hardcoded rank-form Hill (`1 + 9998/(1 + ((r−1)/45)^1.10)`). FantasyPros publishes ranks; the values are our curve applied to them. Scoring a fitted Hill against it measures one Hill against another Hill. |
  | `dlfIdp` | `name,rank` | rank-only |
  | `idpShow` | `name,position,rank` | rank-only |
  | `draftSharksRosIdp` | `…,rank,projection` | a rest-of-season points projection, not a dynasty trade value — a different quantity, not a cheaper version of the same one |

  There is no value-publishing IDP board in the corpus that the IDP fit does not already train
  on.

  One aside worth keeping, because it arrived from an unrelated direction. That hardcoded
  FantasyPros curve is `midpoint 45, slope 1.10` in **rank** form; at the serving reference of
  500 that is `c = 45/499 = 0.0902, s = 1.10` in percentile form — inside §3's unanimous
  region (0.068–0.108) and much nearer the challenger's 0.0770 than the champion's 0.1100. A
  constant someone hardcoded for a different purpose independently sits where the holdout says
  the curve belongs. Weak evidence — it is one hand-chosen number — but it points the same way
  as everything else in §3.
* **the tail past the last observed row**, for any scope. Raising `FIT_TOP_N` would fix
  OFFENSE and GLOBAL. Nothing available fixes IDP.

## 10. Verdict

**MORE EVIDENCE REQUIRED — and the required evidence is now named.**

Unchanged from B1 in conclusion, but no longer for the same reasons. B1 could not promote
because GLOBAL and IDP were unvalidated. B1.1 shows the IDP scope is not merely unvalidated
but *internally incoherent*, that the OFFENSE challenger is defensible yet demonstrably
sub-optimal within its own unanimity constraint, and that the intuitive fallback of promoting
OFFENSE alone is the higher-churn option.

The two blocking prerequisites are unchanged and now precisely stated:

1. **A holdout for GLOBAL and IDP** built from a value-publishing source that the fit does not
   read. No such source exists in the corpus today; acquiring one is a data problem, not a
   modelling one.
2. **A decided tail policy.** `FIT_TOP_N = 400` versus `PERCENTILE_REFERENCE_N = 500` versus
   `OVERALL_RANK_LIMIT = 800` are three different answers to "how deep is the board" living in
   three files, and §2 shows the disagreement reaching 487 live rows.

Two things worth doing that do **not** depend on either, and are not done here because the
execution order stops at evidence:

* pin `RISKIT_FIT_SNAPSHOT` in the refit workflow (§7)
* record GLOBAL/IDP inputs, `measuredAt` and `appliedAt` in the registry (§8)
