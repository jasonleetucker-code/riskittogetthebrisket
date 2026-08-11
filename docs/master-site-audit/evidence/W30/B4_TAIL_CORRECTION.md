# B4 — correction to the W30-F023 blast radius

The first reproduction counted **any** stamped `effectiveRank > 500` as
saturated. That is wrong. W30-F023 is a rank → percentile → Hill defect,
and a deep effective rank is not evidence that the source's live
contribution ever reached a clamp: **value-direct sources price from the
raw site value and never call `percentile_to_value` at all.**

The error is not cosmetic. It inflated the headline and attributed the
collapse to `idpTradeCalc` — which the harness's own record already
contradicted, reporting `rankHillObservations: 0` for it in the same row.
Caught in owner review of the committed report.

## What changed

| | first pass | corrected |
|---|---|---|
| population | any `effectiveRank > N` | `valueContributionPath == "rank_hill"` **and** `effectiveRank > N` |
| saturated observations | 703 of 6,322 (11.1%) | **421 of 5,146 (8.2%)** |
| board rows touched | 348 of 1,092 | **254 of 1,092** |
| `idpTradeCalc` | 282 saturated, "208 distinct ranks collapsed" | **0** — 779 stamped ranks, all value-direct, 0 rank-Hill |

The withdrawn claim, explicitly: *"Every GLOBAL-pool source pays the
identical 1,698 for every rank from 501 to its deepest — 208 distinct
`idpTradeCalc` opinions priced as one number."* The first clause is true
only of GLOBAL-pool observations **on the rank-Hill path**; the second is
false, because none of `idpTradeCalc`'s contributions take that path.

## Corrected reproduction

**421 of 5,146 rank-Hill observations sit past rank 500 (8.2%), touching
254 of 1,092 board rows.** Separately, 282 value-direct observations (of
1,176) also carry a rank past 500; those are *not* part of this defect.

| source | past N | distinct ranks collapsed | deepest Hill rank | clamped → continuous |
|---|---|---|---|---|
| `draftSharksIdp` | 193 | 193 | 730 | 1698 → 1345 (+26%) |
| `idpShow` | 170 | 170 | 877 | 1698 → 1197 (+42%) |
| `dlfIdp` | 23 | 19 | 620 | 1698 → 1489 (+14%) |
| `draftSharks` | 18 | 18 | 684 | 1698 → 1400 (+21%) |
| `dlfRookieIdp` | 8 | 6 | 661 | 1698 → 1431 (+19%) |
| `flockFantasySfRookies` | 6 | 6 | 621 | 794 → 635 (+25%) |
| `fantasyProsIdp` | 3 | 3 | 572 | 1698 → 1564 (+9%) |

Fourteen sources have zero saturated rank-Hill observations, now including
`idpTradeCalc` and `ktcSfTep` — the two value-direct sources.

`idpTradeCalc`'s deep ranks remain a real and separate fact: it is the
**shared-market translation backbone**, so its rank ladder sets the
coordinates every translated IDP source lands in. That is a translation
role, not a contribution the tail policy flattens.

## Path mix, per source

Recorded in full in `b4_tail_report.json` per source: stamped ranks,
value-direct observations, value-direct past N, rank-Hill observations,
rank-Hill past N, **fallback rank-Hill observations**, distinct ranks
collapsed, deepest rank, deepest rank-Hill rank, pool and curve.

**Fallback count is zero on this pin.** A value-based source whose raw
value is missing, out of range, or whose source was suppressed *does* fall
back to the Hill path and therefore *does* take the tail policy — the
production branch is at `data_contract.py` in the value-direct block. It is
simply not exercised by today's data. That is a live path with no live
traffic, so it needs a regression test rather than an observation, and it
is on the B4 RED list.

## The positional blast radius changed materially

| bucket | first pass | corrected |
|---|---|---|
| QB | 17.1% | **5.7%** |
| RB | 16.7% | **1.4%** |
| WR | 13.6% | **1.4%** |
| TE | 31.3% | **14.5%** |
| DL/EDGE | 66.9% | 66.9% |
| LB | 43.0% | 43.0% |
| DB | 64.7% | **62.6%** |
| picks | 14.6% | **0.0%** |

So it is a **more** concentrated IDP defect than the first pass claimed,
not a less serious one: the offense and pick numbers were almost entirely
`idpTradeCalc`'s value-direct ranks, and picks are untouched.

## Four rank domains — for candidate C

A bounded-tail candidate must not conflate these:

| domain | value |
|---|---|
| canonical final-board rank limit (`OVERALL_RANK_LIMIT`) | 800 |
| deepest canonical rank actually served | 740 (740 rows) |
| percentile saturation point (`PERCENTILE_REFERENCE_N`) | 500 |
| deepest translated effective rank, any path | 899 |
| deepest effective rank on the rank-Hill path | 877 |
| **deepest Hill rank consumed by a SERVED row** | **877** |

**Live rank-Hill evidence for served players extends past 800.** A policy
that saturates at the board limit would still collapse genuine evidence —
`idpShow` reaches effective rank 877 on rows the board publishes. The
board-rank domain and the source-coordinate domain are different things,
and 800 is not a defensible saturation point for the latter merely because
it bounds the former.

## Pin hygiene

`dirty` is no longer a bare bool. A run necessarily rewrites its own two
output files, so the flag was self-referential. The pin now enumerates the
dirty paths and classifies them: at measurement time the only modified
paths were the harness and its two outputs, all under
`docs/master-site-audit/evidence/`, so `dirtyIsEvidenceOnly` is **true** and
nothing that could change the measurement was uncommitted.
