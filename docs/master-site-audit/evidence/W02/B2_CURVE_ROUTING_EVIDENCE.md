# B2 — W02-F001 curve-routing root cause: reproduction, repair, measurement

**Phase**: B2 (authorized 2026-08-11, after PR #776 merged)
**Scope**: repair the curve-routing root cause; remeasure W02-F002 and
W02-F003 rather than pre-fixing them.
**Explicitly out of scope and NOT done**: no `promote`, no `apply`, no
Hill constant change, no `PERCENTILE_REFERENCE_N` change, no tail/clamp
policy change, no B3, no CE implementation. W30-F023 (tail clamp) stays
open and separate.

---

## 1. The pinned B2 baseline

| item | value |
|---|---|
| base commit | `a5ff76b09` (main after PR #776 merged) |
| board | `exports/latest/dynasty_data_2026-08-11.json` |
| board sha256₁₆ | `a495c049fa69f141` (834,844 B) |
| board rows | 1,092 |
| source CSVs | 24, all hashed (`b2_curve_routing_report.json`) |
| champion Hill model | registry v2 — GLOBAL 0.1120/0.725, OFFENSE 0.1100/1.110, IDP 0.0830/1.110, ROOKIE 0.1530/0.885 |

The registry now carries versions `[1, 2, 3, 4]`; **v4 is a recorded
challenger, not production**. Champion is unchanged at v2 throughout B2.

Reproduction harness: `b2_curve_routing_measure.py`.
Impact harness: `b2_board_impact.py` (`--dump` / `--compare`).
Full impact output: `b2_board_impact.txt`.

---

## 2. Reproduction — W02-F001 CONFIRMED

`_curve_for_source` chose the master from the source's registry entry:

```python
if src_def.get("is_cross_market"):        return GLOBAL
if src_def.get("scope") == "overall_idp": return IDP
return OFFENSE
```

It never consulted `needs_shared_market_translation` or
`needs_rookie_translation` — the two flags that say the pipeline is going
to move the rank into a *different* population before the curve sees it.

Routing table derived from the live registry (no source-name list):

| source | scope | sharedX | rookieX | cross | routed | verdict |
|---|---|---|---|---|---|---|
| `dlfIdp` | overall_idp | ✓ | | | IDP | **DEFECT** |
| `fantasyProsIdp` | overall_idp | ✓ | | | IDP | **DEFECT** |
| `idpShow` | overall_idp | ✓ | | | IDP | **DEFECT** |
| `dlfRookieIdp` | overall_idp | | ✓ | | IDP | **DEFECT** (via `idpTradeCalc`'s ladder) |
| `idpTradeCalc` | overall_idp | | | ✓ | GLOBAL | correct |
| `draftSharksIdp` | overall_idp | | | ✓ | GLOBAL | correct |
| `dlfRookieSf`, `flockFantasySfRookies` | overall_offense | | ✓ | | OFFENSE | correct (`ktcSfTep`'s ladder is an offense pool) |

Worked example on the baseline board — **Aidan Hutchinson**: raw IDP rank
1 from all three translated sources, crosswalked to effective rank **34**,
identical to `idpTradeCalc`'s own rank 34 and to the identical percentile
0.066132. The IDP master pays **5,627**; the shared-market master pays
**6,444**.

Measured contribution ratio (IDP master ÷ GLOBAL master at the same
percentile, over every contributing row):

| source | n | median ratio |
|---|---|---|
| `dlfIdp` | 145 | 0.386 |
| `fantasyProsIdp` | 119 | 0.473 |
| `idpShow` | 289 | 0.350 |

The historical registry entry recorded a single flat "~48%". The ratio is
strongly **rank-dependent**, which the flat number hides:

```
rank      1     5    10    25    50   100   200   300   500
IDP/GLB  1.00  1.07  1.07  1.00  0.87  0.69  0.52  0.44  0.35
```

At the top of the board the IDP master pays slightly MORE; the shortfall
opens up past rank ~50 and reaches ~1/3 in the tail.

### 2b. A second defect found while reproducing

`sourceRankMeta.sharedMarketTranslated` was stamped as

```python
bool(needs_shared_market and row_scope == SOURCE_SCOPE_OVERALL_IDP)
```

— the source's registered **intent**. When the backbone is unavailable
`translate_position_rank` returns the raw rank with
`method == "fallback"`, and the field still read `True`. A provenance
field that lies precisely when provenance matters; any routing built on
it would inherit the lie. Fixed in the same commit (it is the same root
cause: declaration substituted for outcome).

---

## 3. RED before GREEN

`tests/api/test_curve_routing_coordinate_pool.py` — 15 tests, all driving
`build_api_data_contract` (the production entry point). The synthetic raw
payload pins the ranks by construction so every assertion is an equality;
one test runs the invariant against the real exported board.

Before the repair: **6 failed, 9 passed**.

| test | kind | before |
|---|---|---|
| same effective rank in the same pool prices identically (120 pairs) | RED | fail |
| a shared-market-translated rank takes the GLOBAL master | RED | fail |
| the IDP rookie ladder lands in shared-market coordinates | RED | fail |
| the IDP rookie matches the cross-market source at the same rank | RED | fail |
| `sharedMarketTranslated` reads False when no translation occurred | RED | fail |
| live board: every translated rank on the shared-market master | RED | fail — **578 of 578** translated rank-Hill rows wrong |
| an untranslated (fallback) IDP rank keeps the IDP master | GUARD | pass |
| a skipped rookie ladder also stays IDP-local | GUARD | pass |
| offense rank-signal sources keep the OFFENSE master | GUARD | pass |
| the offense rookie ladder keeps the OFFENSE master | GUARD | pass |
| 3 fixture-validity guards (curves distinguishable, ranks aligned, both on the Hill path) | GUARD | pass |
| `sharedMarketTranslated` still True when translation did occur | GUARD | pass |

After the repair: **15 passed**. Verbatim RED output: `b2_curve_routing_RED.txt`.

The four guards are the reason the fix is not "route every defender
through GLOBAL". A rank that was *not* translated is still IDP-local and
must keep the IDP master; that case is live on any override board where
`idpTradeCalc` is switched off.

---

## 4. The repair

`src/canonical/rank_coordinates.py` is the single owner of "which
population does this rank count within, and which master prices that
population". Three pools — `shared_market`, `offense`, `idp` — one per
routed master.

The rule, in one line:

> **A translation moves a rank INTO the coordinate pool of the ladder it
> was translated through. The curve follows the pool.**

So the pool is a property of a specific `(row, source)` rank, not of a
source. Each Phase-1 pass stamps `rankCoordinatePool` on the meta as it
establishes the effective rank:

| pass | pool it establishes |
|---|---|
| Phase 1 direct | the source's native pool (`native_pool_for_source`) |
| Phase 1 shared-market crosswalk | `shared_market` — **only** when `method != fallback` |
| Phase 1 `position_idp` ladder | `idp` (`ladder_for` is numbered over IDP entries only) |
| Phase 1b DraftSharks combine | `shared_market` when both halves contributed; the single family's pool otherwise |
| Phase 1c CSV cross-market rank | `shared_market` (dormant — the key set is empty today) |
| Phase 1d rookie ladder | the reference source's pool: `ktcSfTep` → offense, `idpTradeCalc` → shared market |

`_curve_for_rank(src_def, meta)` reads the stamp and calls
`curve_for_pool`. `curve_for_pool` **raises** on an unknown pool rather
than defaulting — a silent default is how a rank with lost provenance
gets a plausible-looking value. The only fallback is "no pass claimed
this rank" → the source's declared native pool, which is the honest
reading of "nothing translated it".

**No source is named anywhere in the routing.** The one registry field
still consulted is `is_cross_market`, and it is read as a *description of
the source's own data* ("this source prices offense and IDP on one
scale") — which is exactly the definition of the shared-market pool.

Also removed: the scope-master constants were imported and mapped in two
places. They are now named once, in `rank_coordinates`. Two copies of the
mapping is what W02-F001 was.

### What the repair deliberately does NOT do

* **No Hill constant changes.** Champion stays registry v2.
* **The ROOKIE master stays unrouted.** A rookie rank whose ladder
  translation was skipped keeps its source's native pool — the
  pre-existing behaviour, tracked separately as `scale_integrity_lost`.
* **No reference-N and no tail-policy change.** W30-F023 remains open.

### Latent change worth knowing

The `position_idp` branch previously fell through to the OFFENSE master
(its scope is neither `overall_idp` nor cross-market) while its ladder is
numbered in IDP-overall space. It now takes the IDP master. **Zero live
rows**: no registered source declares that scope, confirmed by a census of
every `sourceRankMeta` stamp on the board.

---

## 5. Board impact — measured, only this change

Both sides built from the same pinned payload in the same working tree
(the production module swapped, everything else identical). The pipeline
was confirmed deterministic first: two runs of identical code produced
byte-identical dumps.

### Per-source contribution — the direct effect

| source | rows changed | median | mean | min | max |
|---|---|---|---|---|---|
| `idpShow` | 289 | +185.9% | +159.4% | +5.6% | +185.9% |
| `dlfIdp` | 145 | +159.1% | +132.1% | +5.6% | +185.9% |
| `fantasyProsIdp` | 119 | +111.2% | +121.6% | +5.6% | +185.9% |
| `dlfRookieIdp` | 25 | +163.4% | +139.2% | +27.0% | +185.9% |

No other source's contribution changed on any row.

### Served value (`rankDerivedValue`)

786 rows priced on both sides. **539 unchanged, 247 changed.**
|Δ%| mean 7.16, median 6.04, p90 15.60, max 150.27.

| |Δ| | rows | share of compared |
|---|---|---|
| > 5% | 139 | 17.7% |
| > 10% | 34 | 4.3% |
| > 25% | 1 | 0.1% |
| > 50% | 1 | 0.1% |

| bucket | changed / population | median | mean | min | max |
|---|---|---|---|---|---|
| offense | 1 / 530 | +8.1% | +8.1% | +8.1% | +8.1% |
| DL-EDGE | 83 / 145 | +6.7% | +7.4% | +0.5% | +21.3% |
| LB | 70 / 114 | +6.2% | +7.1% | −1.5% | +23.9% |
| DB | 54 / 139 | +5.0% | +9.3% | +1.7% | +150.3% |
| picks | 39 / 144 | +3.8% | +3.7% | +0.5% | +8.4% |
| other | 0 / 20 | — | — | — | — |

The single changed offense row is **Travis Hunter** (4,401 → 4,758): the
two-way-player boost takes `max(offense, alt-family)` and his DB side
moved. Picks move because current-year slot picks are tethered to the
merged rookie pool, which includes IDP rookies.

Largest moves: Malachi Moore 746 → 1,867 (+150.3%, a two-source row where
the mispriced `fantasyProsIdp` vote was half the blend), then Micah
Parsons +16.9%, Jared Verse +16.1%, Myles Garrett +15.6%.

### Rank

714 rows ranked on both sides: 79 unchanged, 635 moved. |Δrank| mean
19.8, median 10, p90 48, max 376 (Malachi Moore #740 → #364).

### Board membership — 26 IDP rows re-entered the served board

Priced-row *counts* are identical (812 → 812), which is exactly why the
totals alone would be misleading. The served board keeps a fixed
top-`OVERALL_RANK_LIMIT` (800) window, and the sets differ:

**26 IDP rows that were not priced at all before now are**, including
Devin Bush (#207), Xavier Watts (#296), Nick Cross (#309), Devon
Witherspoon (#316), Divine Deablo (#326), Anthony Hill (#329), Malaki
Starks (#336), Leo Chenal (#338), James Pearce (#351), Cole Bishop
(#353), Frankie Luvu (#358), Mike Green (#359), Talanoa Hufanga (#370),
Tre'von Moehrig (#386), Jalen Pitre (#391), Quentin Lake (#392), Jeremy
Chinn (#394), Leonard Williams (#400), Julian Love (#405), Mason Graham
(#407), Josh Sweat (#409), Kyle Louis (#412), Jordan Battle (#414), plus
three tail rows.

**26 deep-tail offense/pick rows left it** — all previously ranked #630
to #673 at values 1,143–1,203 (Jordan Whittington, Raheim Sanders,
Nick Chubb, Tyler Huntley, `2029 Early 3rd`, …).

So the defect did not only misprice defenders: it pushed 26 of them
below the served board's cut entirely, several of them real NFL starters.

### Offense / IDP balance

Top 100 is **unchanged**: 85 offense / 9 IDP / 6 picks on both sides. The
correction does not tilt the head of the board; it fixes the middle and
tail where the two masters diverge.

### IDP value at representative board ranks

| IDP rank | before | after |
|---|---|---|
| 1 | Aidan Hutchinson 6,362 | Aidan Hutchinson 6,393 |
| 5 | Jack Campbell 4,803 | Jared Verse 5,332 |
| 10 | Edgerrin Cooper 3,919 | Edgerrin Cooper 4,043 |
| 25 | David Bailey 3,059 | T.J. Watt 3,318 |
| 50 | George Karlaftis 2,587 | Byron Young 2,644 |
| 100 | Jessie Bates 1,707 | Quincy Williams 1,869 |
| 150 | Myles Murphy 1,404 | Austin Booker 1,562 |
| 200 | Christian Barmore 1,375 | Andrew Mukuba 1,416 |
| 300 | Kayden McDonald 872 | John Franklin-Myers 896 |

### A consequence that bears on model governance

On the default board, **no live rank is IDP-local any more** — the pools
observed are exactly `{offense, shared_market}`. With the backbone
present, every IDP source is either cross-market or crosswalked into the
shared market, so **the IDP scope master now prices nothing on the
default board**. It still routes on override boards where `idpTradeCalc`
is disabled (the `fallback` case), which is a real user-reachable path,
so the master is not dead — but its live role has changed materially.
Any future promotion decision about the IDP master must be made against
that fact, not against the pre-B2 assumption that it prices ~300 rows.

---

## 6. W02-F002 remeasured — the Hampel anchor ejection

Eligibility mirrors the finding's own reproduction: IDP rows carrying an
`idpTradeCalc` stamp and ≥ 4 stamped sources.

| | ejected / eligible | rate | HIGH | IDP rows with any drop |
|---|---|---|---|---|
| before | 50 / 164 | 30.5% | 50 / 50 | 73 |
| after | 4 / 190 | **2.1%** | 4 / 4 | 35 |

The registry recorded 29.4% and 52-of-52-HIGH; the baseline reproduces
that at 30.5% and 50-of-50. The finding's `expected` is "a low
single-digit percentage, with drops in both directions".

**Classification: RESOLVED AS A CONSEQUENCE OF W02-F001 — in magnitude.**
The mechanism was exactly the one F001 describes: three mispriced votes
dragged the per-player median down far enough that the correctly-priced
market anchor read as the outlier and was thrown out. Correct the
coordinate and the anchor stops being anomalous.

**PARTIALLY REMAINS — in direction.** The surviving ejections are still
4-of-4 HIGH. At n = 4 that is not evidence of a mechanism (a fair coin
gives 4 heads once in 8), so this does not by itself justify a
Hampel change. It is recorded so a later phase can test it on more
boards rather than assume it away.

---

## 7. W02-F003 remeasured — the market corridor clamp

| | clamped | share of ranked IDP rows | cappedByMaxBand | on the band edge | up / down | distinct bandPct |
|---|---|---|---|---|---|---|
| before | 131 | 43.2% of 303 | 131/131 (100%) | 131/131 (100%) | 57 / 74 | {0.15} |
| after | 183 | **55.6%** of 329 | 183/183 (100%) | 183/183 (100%) | **23 / 160** | {0.15} |

The registry recorded "the 0.15 cap binds on 100% of clamps" and "43.3%
of ranked IDP rows"; the baseline reproduces both (100%, 43.2%).

**Classification: STILL REPRODUCES — and the rate is higher, not lower.**
Both stated symptoms are unchanged after the repair:

* the per-bucket P90 machinery is still inert — every clamp is capped by
  `_MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS["idp"] = 0.15`, and the only
  `bandPct` observed is 0.15;
* every clamped row still lands exactly on `anchor × (1 ± 0.15)`.

Two things changed and both are informative:

1. The **rate rose** from 43.2% to 55.6% of ranked IDP rows. F001 was not
   the cause of the clamp binding; if anything it was masking part of it.
2. The **direction flipped**: 57 up / 74 down → 23 up / 160 down. Before
   the repair the mispriced blend sat below the anchor and was clamped
   up; after it, the corrected blend more often sits *above* the anchor
   and is clamped down. That is a substantive new fact about the
   corridor: it is now mostly acting as a ceiling on IDP value, which is
   the opposite of the "containing the IDP calibration runaway" rationale
   its own comments still give (a rationale CLAUDE.md already records as
   stale, since the calibration post-pass it names was removed).

W02-F003 therefore stays **OPEN** and is the strongest candidate for B3.
Nothing about it was pre-fixed here.

---

## 7b. The roadmap's refutation of the GLOBAL re-route, retested

`REPAIR_ROADMAP.md:1492` says, in bold, **"Do not ship the one-line version
of W02-F001"**, on two grounds established by an earlier verifier:

> the prescribed GLOBAL re-route returns per-source medians of
> **0.92 / 0.92 / 1.29 / 1.32** — a *wider* spread than the control band —
> and … the IDP master is fit in units **1.552×** the scale its output is
> consumed in, so correct-coordinate routing would be wrong by +55 % at
> the top. Fix both, or neither.

That statistic is the ratio of a source's contribution to the market
anchor's contribution **where the two share an effective rank**. Remeasured
on the B2 baseline (`b2_anchor_ratio_check.txt`; anchor = `idpTradeCalc`
on IDP rows, `ktcSfTep` on offense rows):

| source | n | before | after |
|---|---|---|---|
| `idpShow` | 67 | 0.484 | **0.949** |
| `dlfRookieIdp` | 5 | 0.584 | **0.893** |
| `dlfIdp` | 4 | 0.839 | **0.931** |
| `fantasyProsIdp` | 3 | 0.855 | **0.940** |

Offense control band, unchanged by the repair — 12 rank-signal sources,
medians 0.713 … 1.005 (span 0.292), min 0.675, max 1.116.

**The first ground is NOT reproduced on this baseline.** The four post-repair
medians span 0.056 (0.893 – 0.949) and sit *inside* the offense control
band; the spread is four times narrower than the control, not wider. The
`1.29 / 1.32` pair does not appear at all.

Stated with its limits, because two of these are thin: n is 3, 4 and 5 for
three of the four sources — only `idpShow` is well-powered at n = 67, and
its distribution does have a right tail (p75 1.373, max 2.223) that a
different summary statistic could plausibly report near 1.3. The earlier
verifier measured a different board (the 2026-08-04 payload) and its exact
statistic is not recorded, so this is **"not reproduced here"**, not "the
earlier measurement was wrong".

**The second ground is untested and is now mostly moot for the served
board.** The 1.552× fit-scale claim about the IDP master is not re-derived
in B2. It matters less than it did: after the repair the IDP master prices
**zero rows on the default board** (§5), because every live IDP rank is now
either cross-market or crosswalked into the shared market. It still routes
on override boards where `idpTradeCalc` is disabled, so the claim is live
on a real user-reachable path and stays **open**. Re-deriving it is a
model-scale question — B3 or a Hill-promotion cycle — not a routing one.

What this changes about the roadmap's instruction: the instruction was
"never ship the re-route alone", and the reason given was that the re-route
alone leaves the board mis-scaled. On this baseline the re-route alone
lands every affected source within the control band. The instruction is
recorded here as **not reproduced**, and the decision to keep W02-F003 open
(§7) is made on its own measured evidence rather than on this claim.

---

## 8. Gates

| gate | result |
|---|---|
| `tests/api/test_curve_routing_coordinate_pool.py` | 6 failed / 9 passed → **15 passed** |
| `tests/canonical` + `tests/api` | **1,983 passed, 3 skipped, 477 subtests, 0 failed** (1,002 s) |
| `ruff check src/ tests/` | clean |
| `ruff format --check` | clean |
| full `pytest tests/ -q -m "not livedata"` | see §9 of the B2 checkpoint report |

---

## 9. Files

| path | role |
|---|---|
| `src/canonical/rank_coordinates.py` | the canonical owner (new) |
| `src/api/data_contract.py` | pool stamping in Phases 1/1b/1c/1d; `_curve_for_rank` |
| `tests/api/test_curve_routing_coordinate_pool.py` | 15 regression tests (new) |
| `b2_curve_routing_measure.py` / `b2_curve_routing_report.json` | reproduction harness + pinned baseline |
| `b2_curve_routing_RED.txt` | verbatim RED output |
| `b2_board_impact.py` / `b2_board_impact.txt` | impact harness + full measurement |
