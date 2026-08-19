# Can we consume a real projection feed today?

Status: **assessed, answer is no — for two independent reasons**, both
measured. The consensus blend is hardened so that if a usable feed
arrives it cannot be mixed wrongly.

This document exists to stop the next session doing the obvious thing.
There are projection numbers sitting in the repo, fetched and committed,
consumed by nothing. Wiring them up looks like a five-line change and is
not one.

## The feed

`CSVs/site_raw/draftSharksSf.csv` and `draftSharksIdp.csv` publish
`1yr. Proj`, `3yr. Proj`, `5yr. Proj`, `10yr. Proj` and `3D Value +`.

`1yr. Proj` is populated on **412 of 439** offensive rows and **375 of
410** IDP rows, with exactly the season-total shape you would expect:

| pos | n | max | median |
|---|---|---|---|
| QB | 51 | 403 (Josh Allen) | 248 |
| RB | 115 | 309 (Jahmyr Gibbs) | 76 |
| WR | 185 | 257 (Puka Nacua) | 70 |
| TE | 88 | 214 (Brock Bowers) | 47 |

This is a real forward-looking projection. It is not a stub, not a
placeholder, and not empty.

## Two claims in the tree that contradicted each other

Both were wrong, in opposite directions, and measuring settled it.

* **`ros/aggregate.py`** said `projection_value` was *"a live signal
  being dropped rather than an unused hook"*. Measured across every
  cached ROS board — `draftSharksRosSf`, `fantasyProsRosSf`,
  `fantasyProsRosIdp`, `fantasyProsRosOverall`, `footballGuysRosIdp` —
  **0 of 2,168 rows** carry a projection. It is an unused hook.
* **`bdvm/projections.py`** said the platform has **zero**
  forward-looking projection sources. Also untrue, per the table above.

The first claim was **mislocated rather than baseless**: DraftSharks does
publish projections, in its *dynasty* feed, not in the ROS-format board
that pipeline reads. Both comments are corrected in place.

## Reason 1 — the numbers cannot be scored under this league's card

The feed publishes **totals, not stat lines**, and **no scoring
metadata**. So:

* there is nothing to re-score under `dynasty_main`'s card; and
* the basis those totals are denominated in cannot be verified.

An unverified basis **fails closed** here for the same reason an
unverified game type does in the dynasty lane: `UNKNOWN` is not a match.

**An attempt to identify the basis, and why it failed.** Comparing
`1yr. Proj` against our own league-scored 2025 realized totals for 232
matched players gives a position-dependent ratio — RB 0.759, QB 0.886,
WR 0.924, TE 1.066, overall median 0.876. That *looks* like a different
scoring card. But it compares a **forward projection** against a
**realized season**, and a projection is systematically less extreme
than a realized outcome, so regression to the mean is confounded with
any scoring difference and the two cannot be separated from this
evidence.

Recorded as **unverified rather than resolved**. The conclusion does not
depend on it: totals without stat lines cannot be rescored under this
league's card whatever their basis.

## Reason 2 — it is not an independent signal

Signal independence (CLAUDE.md §3.3): a body of evidence affects a
conclusion once. DraftSharks **already votes twice** — a dynasty rank on
the valuation board (`draftSharksSf`) and a rest-of-season rank in the
season pipeline (`draftSharksRosSf`).

Spearman ρ, measured:

| pair | n | ρ |
|---|---|---|
| DS dynasty rank vs DS `1yr. Proj` | 412 | **+0.873** |
| … within QB / RB / WR / TE | 42–173 | +0.887 / +0.926 / +0.895 / +0.911 |
| DS ROS rank vs DS `1yr. Proj` | 168 | +0.781 |
| DS ROS rank vs DS dynasty rank | 168 | +0.852 |

`1yr. Proj` is largely the same opinion re-expressed. It is not
identical — a one-year projection legitimately diverges from a dynasty
rank on age — but the correlation group is not in question, because it is
the **same provider**. This is the KTC precedent exactly: Off / TE+ /
TE++ / TE+++ are *"same-source calibration states of one provider, not
four independent votes"*. Counting DraftSharks' projection beside
DraftSharks' rank would manufacture agreement out of one opinion.

## What was hardened instead

`blend_consensus` could not refuse a foreign-basis record.
`ProjectionRecord.resolve_fpg` returns `(value, scoring_native)`, the
blend averaged everything regardless, and stamped `all_scoring_native`
on the result — **written in one place, consumed in none**. A projection
denominated in another provider's scoring landed in the same `mu_fpg` as
a league-scored one, with no consumer able to tell.

Averaging points from two scoring systems is a **category error**, not an
imprecision: they are not the same quantity, so their mean is not a
quantity. Non-native records are now **excluded** and named in
`excluded_foreign_basis` — excluded rather than down-weighted, because a
weight expresses lower confidence in the *same* quantity and this is a
different unit. When every record is non-native they blend and carry
`all_scoring_native: false`, since excluding them all would report the
player **unpriced**, which is a different and false claim.

The reachable path is the documented one: the manual-CSV adapter, which
`projections.py`'s own docstring names as the drop-in for a real feed,
sets `scoring_native=False` unconditionally.

## What a usable feed would look like

Both objections are properties of *this* source, and a different source
clears them:

1. **stat lines, not totals** — so the league's own card scores them,
   which is what `resolve_fpg` already does when `stat_line` is present;
2. **not already voting** in the dynasty or ROS pipelines, or explicitly
   declared as part of that provider's correlation group rather than as
   an independent one.

The BDVM adapters that already exist meet the first test — Mike Clay's
guide and The IDP Show both publish raw stat lines
(`scripts/fetch_clay_projections.py`,
`scripts/fetch_idpshow_projections.py`), which is why those are the real
sources and this one is not.

## Not claimed

Collecting `1yr. Proj` is fine and should continue — archiving a source
is not consuming it, the same posture CLAUDE.md takes for alternate
dynasty boards. Nothing here authorises using it to alter a production
value, and nothing here says the number is wrong. It says we cannot
verify what unit it is in, and that we already count its author's
opinion.
