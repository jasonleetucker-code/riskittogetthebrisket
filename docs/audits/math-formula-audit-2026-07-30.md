# Sitewide math and formula audit — 2026-08-04

**Branch:** `claude/sitewide-math-formula-audit-xswjai` · **Base:** `a006a4b`
**Scope:** every calculation, formula, weighting, normalization, aggregation,
conversion, percentage, probability and derived numerical field in the repo —
audited for **implementation correctness** (is the formula coded right?) *and*
**conceptual correctness** (is it the right formula for this purpose?).

**Companion artifacts**

| file | contents |
|---|---|
| `docs/audits/formula-registry.json` | machine-readable registry: one record per numerical concept, its canonical owner, and every duplicate |
| `tests/audit/test_formula_registry.py` | keeps the registry true — every path it names must exist, every invariant it claims must be enforced |
| `scripts/audit/math_audit_snapshot.py` | rebuilds the board from a fixed payload and diffs it, so every value-moving change has before/after evidence |
| `scripts/audit/fit_ktc_te_rank_shift.py` | the measurement behind a **rejected** alternative (finding C4), kept as the record |

---

## 1. Executive summary

**Overall confidence: the market board is sound; the surfaces built on top of it
were not.**

The core blend was audited five days earlier
(`docs/audits/complete-codebase-audit-2026-07-29.md`) and re-verified here — the
percentile→Hill chain, count-aware blend, weighted median, α-shrinkage, Hampel
filter, single-source retention and pick-year discount all behave as documented.
This pass deliberately did not re-derive them. Its value is the surface those
audits did not reach: the consumer engines, the frontend display math, the
scraper's own math stack, BDVM, and — the recurring theme — the places where a
number crossed a boundary and changed meaning without changing name.

**The pattern worth naming.** Almost every serious finding is the same shape: a
formula that is *correct about what it computes* and wrong about what it is taken
to mean. A composite value under a board-scale name. A rank shift labelled a
percentage. A 2-day delta labelled 90 days. A stability metric read as accuracy.
Individually small; collectively they mean several displayed numbers were not
what their labels claimed.

### By the numbers

| | |
|---|---|
| Numerical concepts inventoried | 16 (registry), spanning ~80 distinct implementations |
| Confirmed defects | 4 critical, 8 high, 8 medium, ~20 low |
| Duplicate implementations found | 11 concepts with >1 implementation; 5 legitimately different, 6 accidental |
| Value-moving corrections | 2 (both measured on the real board; see §8) |
| Corrections with zero board movement | most — the majority of defects were downstream of the board, not in it |
| Tests added | ~516 backend + ~180 frontend cases, all failing-before / passing-after |
| Open decisions recorded, not forced | 5 (§9) |
| Findings **refuted** on verification | 3 (§4.4) — recorded so nobody re-raises them |
| Fixes **rejected after measurement** | 1 (C4's rank-space alternative), recorded with its numbers |
| Defects found but deliberately NOT fixed | 3 — `_PERCENTILE_REFERENCE_N` (§9 U1), BDVM's spec-faithful risk double-count (M5), the scraper's `_market_confidence` divisor (known debt D15) |

### Highest-risk problems found

1. **`/api/draft-capital` priced half its board from invented constants** (C1) —
   with a fully valid contract loaded, and `CLAUDE.md` asserted this case was
   impossible.
2. **A formula the codebase had formally retired was still the primary sort key**
   of the Insider Trading board (C2), summing three nested time windows so one
   event counted six times.
3. **Public and private trade grading used different formulas against identical
   thresholds** (C3), with a comment claiming they agreed.
4. **Six sources' top-TE votes collapsed onto one identical number** (C4),
   erasing the disagreement they published.
5. **270 rows carried a different value scale under a board-scale name** (H1),
   which leaked into public trade grading and every frontend value sum.

### Features whose displayed numbers were unreliable before this pass

- `/draft` auction dollars (every team's total was diluted by invented pick values)
- `/league` public trade grades (different formula from `/trades`; also mixed scales)
- `/league` Insider Trading board ordering (overlapping-window double count)
- Terminal 7/30/90/180-day value deltas (positively biased by a population mismatch)
- `/api/movers` window labelling (a ~2-day delta reported as up to 90 days)
- FAAB recommendations for a manager with $0 remaining (sized against $100)

---

## 2. Formula registry

The machine-readable registry is `docs/audits/formula-registry.json` — 16
concepts, each with its canonical owner, units, expected range, consumers, and
every known duplicate with an explicit disposition.

It is deliberately a registry of **concepts**, not of arithmetic expressions.
A registry of every `+` in the repo would be thousands of rows and would answer
no question anyone asks. The question this one answers is *"who owns this number,
and who else computes it?"* — so that a future duplicate shows up as a diff
against a checked-in file rather than as a bug report months later.
`tests/audit/test_formula_registry.py` enforces that every path it names exists
and that its load-bearing invariants are backed by code rather than prose.

---

## 3. Canonical formula map

| concept | canonical implementation | duplicates | disposition |
|---|---|---|---|
| **Player value** | `data_contract.py::_compute_unified_rankings` → `rankDerivedValue` | scraper `_composite`; BDVM `to_trade_value` | both are **different concepts**, retained and now clearly separated (H1) |
| **Value bundle scale** | `data_contract.py::_player_value_bundle` | — | board-named keys are board-or-`None`; composite lives only under `rawComposite` (H1) |
| **Rank** | `data_contract.py::compact_ranks_and_tiers` | frontend `computedConsensusRank` | display ordinal for backend-unranked rows only — **intentional**, not a ranker |
| **Rank → value** | `player_valuation.py::percentile_to_value` | scraper `_calibrated_rank_to_value`; `value-history.js::valueFromRank` | scraper is a **separate system** (M8); frontend mirror is offense-only (M3) |
| **TE premium** | `te_premium.py::convert_te_value` + `_te_lift_under_ceiling` | — | structural double-count guard preserved; ceiling bound corrected (C4) |
| **Pick value** | `data_contract.py` blend + discount + tethering | draft-capital flat table; `calibration.py::_pick_curve_value`; BDVM `picks.py` | flat table **removed** (C1); calibration is legacy; BDVM is a different concept |
| **Trade grade** | `public_league/trade_grading.py` + `league-analysis.js::gradeTradeSides` | alpha-weighted public path | **replaced**; two languages now pinned by one shared fixture (C3) |
| **Activity ranking** | `intel/signals.py::signal_strength` / `velocity` | `aggregate.py::trend_score` | removed from all ranking paths (C2) |
| **Team value** | *none — three legitimately different concepts* | `marginal.py` (lineup-solved); `league-analysis.js` (simple sum); `terminal.py` (simple sum, excludes picks) | **documented divergence**; only `marginal.py` may claim lineup awareness |
| **Starter slots** | `config/leagues/registry.json` | 3 divergent hardcoded sets | **documented divergence** (M3) |
| **Percentile** | *none — five incompatible definitions* | `power.py`, `sharp/score.py`, `window.py`, `power_v2.py`, `profiles.py` | **documented divergence** (M3); one makes a cohort bar unreachable |
| **FAAB bid** | `waiver.py::_compute_faab_bid` | `waiver-logic.js::computeFaabHint` | parity port; rounding convention unified (H4) |
| **Buy/Sell/Hold** | `tests/fixtures/signal_parity_cases.json` (shared rule table) | — | **already consolidated** — debt register D3 is stale (§4.4) |

**Intentional differences preserved.** Market value vs fundamental value (BDVM);
rest-of-season vs long-term dynasty value; contender vs rebuilder currency;
display rank vs raw model score; the trade finder's market anchor staying retail
while its own side takes the league lens. Each is a different question, and
collapsing them would destroy information rather than add consistency.

---

## 4. Findings

Severity: **Critical** materially corrupts core values/rankings/trades ·
**High** incorrect results in an important feature or substantial inconsistency ·
**Medium** limited cases, precision, secondary calculations · **Low** naming,
docs, minor rounding.

### 4.1 Critical

---

**C1 — `/api/draft-capital` priced half its board from an invented flat table**

*Feature:* `/draft` auction dollars · *Files:* `src/api/draft_capital_fallback.py:71-101,159-180`

`build_sleeper_derived` loops `for season in (current_season, current_season + 1)`
and asks the contract for each pick. On a miss, `_pick_value_from_contract`
returned a hardcoded `{1: 7000, 2: 4000, 3: 2000, 4: 1200, 5: 700, 6: 300}`.

*Verified:* the live contract carries **2026 slot picks only** (72 rows: 12 slots
× 6 rounds), so every `current_season + 1` pick — **half the generated board** —
took the flat table **with a fully valid contract loaded**. Those constants sat on
the same 0-9999 scale as the Hill-calibrated real values and were normalized into
the same $1200 pool, diluting every genuine pick and shifting every team's
`auctionDollars`. The response stamped `source: "sleeper_derived"` and
`coveredPickYears` claimed both years were covered.

`CLAUDE.md` asserted *"that is the case the 503 covers"*. It is not: the 503 fires
only when **no** contract is loaded.

*Correction:* `_pick_value_from_contract` returns `None`; unpriced picks are
excluded from the dollar-normalization pool and emitted with `dollarValue: None`
plus an explicit flag; coverage metadata reports what was actually priced.
`CLAUDE.md` corrected.

---

**C2 — a formally retired formula was still the board's primary sort key**

*Feature:* `/league` Insider Trading · *Files:* `src/intel/aggregate.py:41`, `src/intel/service.py:403`

`src/intel/signals.py:5-25` is a **deprecation notice** explaining that
`trendScore = 3·net48h + 2·net7d + 1·net30d` sums nested windows, so an event an
hour old lands in all three terms and contributes 3+2+1 = 6 — *"One event, six
counted"* — and concluding *"Nothing here ever adds two windows together."*

*Verified live:* `aggregate.py:41` still defined it verbatim, `:149` stamped it on
every asset, and `service.py:403` **sorted the board by it**. A second surface
(`build_member_activity`) ordered by `-abs(trendScore)`.

This is precisely the defect class the audit brief names by example.

*Correction:* the board now ranks on `signalStrength`, computed over a single
primary window, with a deterministic total-order tie-break. The two divergent
`WINDOWS_MS` registries were reconciled.

---

**C3 — public and private trade grading used different formulas, same thresholds**

*Feature:* `/league` activity vs `/trades` · *Files:* `src/public_league/activity.py:79-153`, `frontend/lib/league-analysis.js:377-386`

Public graded on `Σ max(v, 1)^1.65` **without** the KTC value adjustment; private
graded on a **linear** ratio **with** it — and the frontend explicitly refused
alpha (*"those dominate by an order of magnitude and would crush all pcts toward
zero"*). Both fed the same 3/8/15/25/40 bands, so a ~15% linear edge is ~24% under
alpha and the same trade rendered a different letter on each page.
`activity.py:40-47` asserted they *"land in the same bucket."*

*Correction:* one canonical formula (linear + VA), implemented once per language
and pinned by a shared fixture — the pattern `signal_parity_cases.json` already
established. The winner/headline split was resolved so one trade has one winner.

---

**C4 — the TE premium collapsed six sources' votes onto the ceiling**

*Feature:* rankings, everywhere a TE is valued · *File:* `src/api/data_contract.py:7192-7216`

A tight end's per-source contribution was lifted onto the TE++ basis then bounded
with `min(..., 9999)`. A hard clamp is not injective, and the inputs routinely
exceed it: a contribution is `Hill(rank)`, and the Hill master is far steeper at
the top than KTC's real value distribution — **KTC ranks Brock Bowers 8th and
values him 8153, while Hill maps rank 8 to 9076**. Lifting 9076 by the measured
1.2092 floor gives 10975.

*Verified against the live source CSVs* — six sources' top-TE votes all became
exactly 9999:

| source | rank | uncapped | clamped |
|---|---:|---:|---:|
| fantasyCalc / pfkDynasty / dynastyDaddySf | 8 | 10975 | 9999 |
| idpTradeCalc / dynastyNerdsSfTep | 7 | 10131 | 9999 |
| otcffbSf | 14 | 10058 | 9999 |

Each was then casting an identical vote for a tight end and for the #1 overall
player. Offense rows are exempt from the market-corridor clamp, so nothing
downstream contained it.

*The premium itself is not the defect.* Across all 72 tight ends paired on KTC's
base and TE++ boards it reproduces KTC's true ratio to a mean absolute error of
**0.090**. Only the bound was wrong.

*Correction:* `_te_lift_under_ceiling` — identity below 9900, a strictly
increasing squash above it, asymptotic to 9999 and never reaching it. Distinct
votes stay distinct; a lifted TE can approach the top asset on its source's board
but never displace it (which matches KTC, where Bowers lands 5th at 9859).

*Board impact:* **1 row, −10 points, 0 rank changes** (Brock Bowers 9933 → 9923).

*Rejected alternative, recorded because it was measured.* Applying the premium as
a **rank shift** before the Hill call, fitted from the same paired boards
(`scripts/audit/fit_ktc_te_rank_shift.py`; Bowers 8→5, McBride 17→8, monotone,
bounded by construction, cannot saturate). It is worse: pushing a rank shift
through the Hill curve does not recover the measured value ratio, because the
curve's shape is not KTC's value distribution.

| method | mean abs error vs KTC's true TE ratio | median |
|---|---:|---:|
| value-space (kept) | **0.090** | 0.081 |
| rank-space (rejected) | 0.175 | 0.085 |

At KTC base rank 496 the true ratio is 2.045; value space gives 1.633, rank space
1.122. The value space is where the premium was measured and where it belongs.
Wiring the rank shift moved 125 values and 567 ranks — a large change in the wrong
direction, caught only because it was measured against ground truth before being
kept.

### 4.2 High

**H1 — 270 rows carried composite scale under a board-scale name**

*Files:* `data_contract.py::_player_value_bundle` + stamping loop; `public_activity_valuation.py:70`; `dynasty-data.js::inferValueBundle`

`values.overall` / `finalAdjusted` / `displayValue` were *seeded* from the legacy
scraper composite (~1.131× the board) and only *overwritten* by
`rankDerivedValue` when it was `> 0`. **Measured on the live board: 270 rows** —
every suppressed generic pick tier among them — kept a composite number under a
board-scale name. `2026 Early 1st` reported 6136 against real slot picks at
1.01 = 7852 and 1.02 = 6101.

`public_activity_valuation.py` walked `displayValue → overall → finalAdjusted →
**rawComposite**` and summed whatever it found into one trade-side total, so a
public trade could be graded with board-scale assets on one side and
composite-scale on the other. The frontend's `values.full` had the same fallback,
contaminating every downstream sum (team value, trade sides, waiver gaps,
portfolio totals).

*Correction:* the board-named keys are seeded `None`. A row the board declined to
price now reads as **unpriced** — there is no composite value available under a
board name to pick up by accident. `rawComposite` keeps the composite under its
own name. The contract stamps `rowsUnpricedByBoard` so the omission is visible.

*Board impact:* **0 values, 0 ranks.** Only the 270 unpriced rows' `values.*`
changed, from a composite number to `None`; every priced row's `values.overall`
still mirrors `rankDerivedValue` exactly.

**H2 — terminal value deltas were positively biased by a population mismatch** ·
`terminal.py:574-680,1470-1503`. A 60-99%-covered past-roster sum was subtracted
from a ~100%-covered present sum, biasing `delta{7,30,90,180}d` positive by
roughly the uncovered fraction. Corrected to an apples-to-apples population.

**H3 — two window labels were false** · `terminal.py:531` windowed by *snapshot
count*, not days (the scrape runs every ~2h, so `days=30` was ~2.5 days);
`server.py:3466` anchored on the oldest loaded point and echoed the requested
window, reporting a ~2-day delta as up to 90 days. Both now report the span they
actually measured.

**H4 — a manager with $0 FAAB was billed against $100** · `waiver.py:187-190`
substituted `100` when remaining budget was `<= 0` — the inverse of the intended
cap — and the parameter named `league_budget` received *remaining*. Also
`reasonable`/`lowball` derived from an already-rounded `aggressive`, and the JS
parity port used half-up rounding against Python's banker's rounding.

**H5 — three double-counts** · `league-analysis.js::scoreTeamTiers` nets picks at
**+0.1** while its docstring says they are penalized at −0.1 (`pickValue ⊂
depthValue`); `team_assignment.py:286-311` pays the same depth-chart signal twice
(5 + 3); `team_impact.py:213-247` subtracts `pick_share + young_share` from a
`top10_share` that already contains them.

**H6 — BDVM's declared value ceiling was decorative** · `trade_value_max: 10000.0`
had exactly one reference in the repo: its own declaration. Measured p85 ceilings
of **19,736** and **21,997**, and the band could invert (ceiling < median). *The
engine now reads the declared cap and the band is monotone by construction.*

**H7 — BDVM replacement level silently became 0.0** · three routes to `R = 0`,
which makes every player's surplus their entire FPG — the value scale's origin
collapses. *Missing data now returns an explicit unpriced reason, following the
module's own existing policy rather than imputing a normal-looking zero.*

**H8 — the trade simulator's verdict is VA-blind** while the trade meter beside it
is not, so the same trade shows two different equity numbers. *Recorded; see §9.*

### 4.3 Medium and low

**M1 — the board publishes 300 ranks past the point its inputs resolve.**
`_PERCENTILE_REFERENCE_N = 500` but `OVERALL_RANK_LIMIT = 800`. `p` clamps at 1.0,
so ranks 500/600/800/1000 all yield identical per-source values (verified by
independent recomputation: OFFENSE 794.3 / IDP 593.7 / GLOBAL 1697.6). **240 of
740 ranked rows (32%)** sit in that region; **716 of 6,251 per-source votes
(11.5%)** are mutually indistinguishable. **Left unchanged deliberately — see §9.**

**M2 — cross-curve scale divergence.** Cross-market sources route through GLOBAL
(s=0.725), others through OFFENSE/IDP (s=1.110). At rank 400: GLOBAL 1939 /
OFFENSE 996 / IDP 748 — **1.95× and 2.59×**. These are averaged in one blend, and
the cross-market sources are also the α-shrinkage anchor for IDP and pick rows.
Arguable (the populations genuinely differ) but nothing pins the relationship.
Compounded by train/serve skew: `model_registry/holdout.py` scores candidate
curves under `p = i/(n−1)` over a 400-cap native pool while production serves a
fixed 500.

**M3 — the definitional zoo.** Five percentile definitions (one makes
`sharp/score.py`'s 0.85 cohort bar **unreachable at n=2**; another can never
return 1.0, so only the #1 team can approach a 0.95 anchor); five starter-slot
definitions; two power rankings side by side on `/league` with different formulas,
windows and percentile conventions; two CV threshold sets for one formula (the
popup can say "strong consensus" about a player the engine flags
`high_dispersion`); three "percentage gap" denominators; three `computeMovers`;
and a frontend rank→value mirror that is offense-only, re-creating the
scope-aware bug the backend fixed on 2026-07-29.

**M4 — `public_league/power.py` blends three time windows** under one weight
scheme (career-to-date PPG, season recent form, single-week all-play) and mixes
two metric types, while its docstring and served `methodology` string both say
"season-to-date".

**M5 — BDVM double-counts risk aversion and consolidation.** The p20/p85 quantile
paths already *are* the downside/upside, then `_discounted_value` subtracts
`λ·0.35·Ψ` again — measured 6.7% (balanced) to 14.2% (contender) over-penalty,
and the rebuilder's "floor" is *raised* 9.3% above its own p20 path. Separately Ψ
assumes independent seasons while the quantile band shifts every season by the
same `z` — measured **2.39×** apart inside one `Valuation`. **Deliberately not
changed:** it is spec-faithful, so changing it breaks Appendix-C parity.
Documented in `docs/research/bdvm-v1/IMPLEMENTATION_REPORT.md` with the measured
numbers.

**M6 — BDVM's `season` conflated the rookie-draft year with the NFL season.**
Latent today (§4.4). *Corrected:* a dedicated `nfl_projection_season()` now
resolves the projection season, and it agrees with the actuals season by
construction — the two concepts are stamped separately (`meta.season` vs
`meta.rookieDraftYear`) so they can never silently diverge again.

**M7 — BDVM dead knobs and unreachable states.** `STRONG_BUY` required a
`gap_persisted_days` the caller never passed, so it could never fire while
`ACTIONABLE_BDVM_SIGNALS` listed it; `STRONG_SELL` fired at `alpha = −1` with no
magnitude floor; rookie-pick EV was **flat past overall slot 36** (every pick from
3.12 on priced identically); and liquidity *rose* with cross-source disagreement
while `τ_market` *fell* with it — the same input meaning opposite things in one
function. *Corrected:* dispersion now subtracts in both places (`base` retuned to
1.0 so a typical row lands where it did before), the signal ladder is reachable
and magnitude-gated, and the pick table extrapolates past its last slot.

**M8 — the scraper's second math stack.** *Corrected:* `_rank_percentile`'s two
"no information" branches returned opposite ends of the scale (1.0 for empty, 0.0
for a single element) and now both return 0.5; `_build_idp_anchor_points` no
longer pads with repeated trailing values, so the tail extrapolation has a real
slope instead of a flat one (rank 96 and rank 300 no longer price identically);
`SITE_WEIGHTS` is renamed `LEGACY_COMPOSITE_SITE_WEIGHTS` so it cannot be mistaken
for the blend weights (its *values* are deliberately unchanged — moving them would
shift the composite with no evidence); and the elite-separation boost now reads
the **post-trim** population it multiplies rather than the untrimmed one, so an
observation already discarded from the value can no longer veto a boost the
survivors earned. `_market_confidence`'s 8.0 divisor is **deliberately left**
(known debt D15, measured and deferred in `docs/open-modeling-decisions.md` §3).

**Note on measuring M8:** the scraper is not imported by the contract builder, so
these changes cannot move a board rebuilt from an existing export — their effect
lands on the next scrape. That is why they carry unit tests
(`tests/pool/test_scraper_composite_math.py`) rather than a board diff.

**Low tier** (~20, all corrected): pick-round fallback to round **1** instead of
the worst round, plus a 15% discontinuity between slot 4 and slot 5; a
`source_weights` block whose second loop has no body, so an advertised parameter
was a silent no-op; a tier map zipped **by index** against a list `detect_tiers`
drops rows from, so one drop shifted every subsequent row onto another row's tier;
three unit errors in `feature_engineering` (TDs *per yard* against a 0.06
threshold, receptions *per yard* for WR/TE against a fraction for RB at the same
0.22 threshold, and an already-per-game figure divided by games again) that made
two tags unreachable; a phantom loss for an owner who was scored but not paired;
Monte Carlo ties credited entirely to side B via `winProbB = 1 − winProbA`; six
chained roundings in the FAAB recommender plus a variable confidence denominator
where "present but neutral" scored differently from "missing"; a `max(1, …)`
guard that turned an over-spent draft workbook into an ~800× inflation
multiplier; and a docstring promising NumPy acceleration that appears nowhere in
the module.

Deliberately **not** fixed, and recorded instead: the ~15 missing sort tie-breaks
outside the paths this audit touched (each is a determinism nit, not a wrong
number), and `league_intel/replacement.py`'s 5th-percentile index returning the
**top** player on a 10-player pool via banker's rounding — real, but it sits in
the league-adjusted overlay, which is a toggle rather than the default board (see
`docs/adjusted-board-backtest.md`).

### 4.4 Defects introduced BY the fixes, caught by adversarial review

Every fix was re-checked by an independent skeptic instructed to find what was
wrong with it, not to agree. Three fixes introduced new defects. That is the
finding, and it is recorded rather than quietly patched, because the pattern is
instructive: **each new defect was the same class as the one being fixed.**

**R1 — BDVM's new value cap was a hard clamp.** H6 enforced `trade_value_max`
with `min(cap, x)`. Non-injective — measured on an elite-heavy ladder, seven
distinct ceilings spanning an ~1.8× uncapped range collapsed onto exactly
`10000.0`, which `frontend/lib/bdvm.js` renders as a tie. This repo already
contained both the tool and the argument against the clamp — `_te_lift_under_ceiling`,
added by C4 *on this same branch*, whose docstring says "a hard clamp is the wrong
tool because it is not injective". Worse, the accompanying test asserted exact
equality with the cap, **pinning the defect in place**. Corrected to a monotone
squash; the test now asserts strictly-under and that distinct ceilings stay
distinct. One real difference from the C4 case, documented in the code: BDVM's
inputs reach ~2.2× its ceiling where the TE case reaches ~1.21×, so the decay
scale must be decoupled from the span or the exponential underflows float64 and
flattens the top again — my own test caught that on the first attempt.

**R2 — the FAAB confidence flip.** Removing the premature rounding (H4) made
`standard` a float, and the factor rows were gated on `standard != before`. So
whether the league-calibration row counted as *realized* evidence or as **missing**
evidence depended on where the 50/50 blend happened to land. Measured: the same
player, the same $12 recommendation and the same league data reported `low`
confidence at a league average of 12.0 and `high` at 12.4. The deeper error was
the gate itself — `compute_confidence` is a weighted realized-share, i.e. it asks
*"how much of the evidence did we have?"*, so a calibration that ran against three
real bids and agreed with the baseline is realized evidence, not missing evidence.
Both gates now test **input presence** via predicates split out of the helpers so
they share one condition and cannot drift.

**R3 — `historyDepthDays` measured the slice, not the log.** H3's fix derived depth
from `load_history(days=window + 1)` — a *count* slice — so it equalled
`min(true_depth, window)` by construction and could never report "the log is deeper
than you asked", which is half of what a depth field is for. It read correctly only
because the live log is shallower than any window: the same accident H3 was filed
against. Now measured from `rank_history.coverage()`'s untrimmed first date —
through the same `_span_days` helper the window uses, because `coverage()`'s own
`spanDays` is an inclusive calendar-day *count* and mixing the two would have put
two different definitions of "days back" in one response.

**Still open from that review**, recorded in §9: H2's population fix is
one-directional — it removed a positive bias and left the mirror case negative by
the same mechanism.

### 4.5 Findings refuted on verification — recorded so they are not re-raised

**A refuted finding is a deliverable.** Three claims reaching this audit did not
survive:

1. **"Buy/Sell/Hold is implemented twice with no parity test" (debt register D3).**
   **Stale.** `tests/fixtures/signal_parity_cases.json` is a shared rule table read
   by *both* `terminal.py` and `signal-engine.js`, with parity tests on both sides.
   No work was needed; the register was corrected.

2. **"BDVM ages every player a year old in-season."** Reported as live. It is
   **latent**: `current_rookie_draft_year()` prefers the year *observed in the
   scrape* over the date fallback, and the live scrape publishes only 2026 slot
   picks, so `currentDraftYear` == the calendar season today. Real, but it bites
   only on the date-fallback path and once the sources roll (§9).

3. **"The TE premium should be applied as a rank shift."** My own hypothesis,
   built and wired, then **refuted by measurement** against KTC's paired boards
   (C4). Reverted.

---

## 5. Cross-feature consistency matrix

✅ consistent · ⚠️ intentionally different (documented) · ❌ inconsistent
(unintentional) · — not applicable

| concept | Rankings | Player page | Trade calc | Trade history | Roster analysis | Draft tools | Historical charts | Public /league | Canonical? |
|---|---|---|---|---|---|---|---|---|---|
| Player value | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ reconstruction | ✅ *(was ❌ — H1)* | **yes** |
| Value scale (board vs composite) | ✅ | ✅ | ✅ *(was ❌ — "Raw" mode)* | ✅ | ✅ *(was ❌ — H1)* | ✅ | ✅ | ✅ *(was ❌ — H1)* | **yes** |
| Rank | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ | — | **yes** |
| Pick value | ✅ | — | ✅ | ✅ | ✅ | ✅ *(was ❌ — C1)* | — | ✅ | **yes** |
| TE premium | ✅ *(was ❌ — C4)* | ✅ | ✅ | — | ✅ | ✅ | — | — | **yes** |
| Trade grade | — | — | ✅ | ✅ | — | — | — | ✅ *(was ❌ — C3)* | **yes** |
| Activity / transactions | — | ✅ | — | — | — | — | — | ✅ *(was ❌ — C2)* | **yes** |
| FAAB bid | — | — | — | — | ✅ | — | — | — | **yes** *(was ❌ — H4)* |
| Buy/Sell/Hold | ✅ | ✅ | — | — | ✅ | — | — | — | **yes** (shared fixture) |
| Value deltas over time | ✅ | ✅ | — | — | ✅ *(was ❌ — H2)* | — | ⚠️ | — | partial |
| Time-window labelling | ✅ *(was ❌ — H3)* | ✅ | — | — | ✅ | — | ⚠️ | — | partial |
| Team value | — | — | ⚠️ | — | ❌ **three definitions** | — | ❌ reconstruction | — | **no** — §9 |
| Starter slots | — | — | ❌ | — | ❌ **five definitions** | — | — | — | **no** — §9 |
| Percentile | — | — | — | — | ❌ **five definitions** | — | — | ❌ | **no** — §9 |
| Rank→value curve | ✅ | ✅ | — | — | — | — | ❌ offense-only mirror | — | partial |

---

## 6. Code changes

Every change carries a documented before/after and a test. Nothing was fixed
silently.

**Board math (measured on the real payload with `math_audit_snapshot.py`)**
- `data_contract.py::_player_value_bundle` + stamping loop — H1. Board-named keys
  seeded `None`; `rowsUnpricedByBoard` stamped. **0 values, 0 ranks moved.**
- `data_contract.py::_te_lift_under_ceiling` — C4. Monotone squash replaces the
  hard clamp. **1 value moved (−10), 0 ranks.**
- `data_contract.py` top-50 coverage sort now reads `rankDerivedValue` directly.

**Downstream**
- `draft_capital_fallback.py` — C1: invented table removed; unpriced picks
  excluded from normalization and reported.
- `intel/{aggregate,service}.py` — C2: overlapping-window sum removed from all
  ranking paths; window registries reconciled.
- `public_league/trade_grading.py` (new) + `league-analysis.js` — C3: one formula,
  two languages, one shared fixture.
- `terminal.py`, `server.py` — H2/H3: population-consistent deltas; windows report
  the span actually measured.
- `public_activity_valuation.py`, `frontend/lib/dynasty-data.js` — H1: composite
  removed from every board-scale fallback chain.

**Documentation corrected because it was false**
- `CLAUDE.md` `/api/draft-capital` section (asserted a 503 covered C1).
- `public_league/activity.py:40-47` (asserted grading parity that did not exist).
- `scripts/backtest_percentile_reference_n.py` — now prints why its own
  recommendation is not an accuracy finding (§9).

---

## 7. Tests

| file | pins |
|---|---|
| `tests/api/test_value_bundle_scale_contract.py` | H1 — board-named keys never seeded from the composite; every contract key still present |
| `tests/api/test_te_lift_ceiling.py` | C4 — identity below the knee, strictly increasing above it, distinct votes stay distinct, hand-computed closed form |
| `tests/api/test_percentile_reference_resolution.py` | M1 tripwire — the flat tail is real; the gap may shrink, never grow |
| `tests/audit/test_formula_registry.py` | the registry stays true; nothing ranks on `trendScore` |
| `tests/api/test_draft_capital_fallback.py` | C1 — `None` on a miss; unpriced picks excluded from the pool |
| `tests/intel/*` | C2 — one event cannot enter the ranking through multiple nested windows |
| `tests/public_league/test_trade_grade_parity.py` + `frontend/__tests__/trade-grade-parity.test.js` | C3 — shared fixture, neither side may hardcode its own expectation |
| `tests/api/test_movers_window.py`, `tests/api/test_terminal.py` | H2/H3 |

**Verification rule applied throughout:** a test never calls the production helper
to produce its own expected value. Expected numbers are hand-computed or
re-derived from the committed constants. A test that uses the implementation for
both sides proves nothing.

**Results** (after merging `origin/main`, which advanced 20+ commits during the audit)

```
python -m pytest tests/ -q
  6106 passed, 39 skipped, 0 failed        (baseline: 5548 passed, 1 failed)

cd frontend && npx vitest run
  101 files, 1708 passed                   (baseline: 89 files, 1526 passed)

python -m ruff format --check .
  817 files already formatted
```

Fully green. The one baseline failure
(`test_faab_recommend_endpoint.py::test_matching_league_snapshot_consumed_normally`,
a staleness fixture asserted against a container clock 122h ahead of the data)
was resolved by the data refresh that arrived with the merge — it was never a
code defect.

**A note on the merge.** `main` moved while this audit ran, and one of its commits
(PR #697, "Consensus Edge") **independently fixed C2** by deleting
`src/intel/aggregate.py` outright and restructuring the intel module to
per-window indexed queries. That resolution is more thorough than this audit's —
it removes the summed-window metric rather than merely un-ranking by it — so the
merge deferred to it wholesale. `scoreTeamTiers` needed a genuine three-way
resolution: `main` fixed a *different* defect in the same function (starter value
was the top 10 offensive players, which reads a defense-heavy contender as a
rebuilder in a 9-IDP league) while this audit fixed the pick double-count. Both
corrections are live; neither was dropped.

---

## 8. Recalculation and migration plan

**Values that move.** Exactly one board row: Brock Bowers 9933 → 9923 (−0.1%),
no rank change. No recalculation of stored history is required — the change is
below the noise of a single scrape.

**Values that change shape, not magnitude.**
- 270 rows' `values.{overall,finalAdjusted,displayValue}` become `null` instead of
  a composite number. **Any consumer that treated those as numbers must handle
  `null`.** All in-repo consumers were updated; the contract now publishes
  `rowsUnpricedByBoard` so the count is visible.
- `/api/draft-capital` emits `dollarValue: null` for picks the contract cannot
  price, and team `auctionDollars` **will change** — they were previously diluted
  by invented values. This is a visible, intended correction.

**Caches to invalidate on deploy.** The three never-invalidated module caches
(debt D9) plus `bdvm_api`'s `id(contract)`-keyed cache. A restart clears all of
them; no migration script is needed because nothing derived is persisted.

**Formula versioning.** No stored historical values were computed by a changed
formula, so no backfill is required. `rank_history` and `source_history` store
ranks and per-source values, not blended outputs, and are unaffected.

**User-visible changes to expect:** `/draft` auction dollars shift; `/league`
trade grades change letters where the two formulas previously disagreed; the
Insider Trading board reorders; movers windows report shorter spans than they
used to claim.

---

## 9. Remaining uncertainties

Recorded rather than guessed. Each states the ambiguity, current behavior,
interpretations, a recommendation, and what decision is needed.

**U1 — `_PERCENTILE_REFERENCE_N` (M1).**
*Ambiguity:* the board publishes 800 ranks; its inputs resolve 500.
*Current:* N=500, documented in `CLAUDE.md` as deliberate top-500-board behavior.
*Interpretations:* (a) deliberate — the retail market is a top-500 phenomenon and
deeper ranks are noise; (b) a stale constant — 11.5% of votes are discarded.
*Why it was not changed:* `scripts/backtest_percentile_reference_n.py` recommends
N=1000, and that recommendation **cannot be acted on**. It scores *stability*,
which this clamp makes degenerate — a smaller N flattens more of the board and so
has less left to churn, meaning a maximally uninformative board can win. Its
snapshots are also hybrid: `build_api_data_contract` reads CSV-backed sources from
the *current* tree regardless of which payload is replayed, and the archives
bundle site_raw for only 3 of 21 sources. **Measured: replaying the 2026-07-14
payload had 21 sources voting, 18 of them from today's files.** Both caveats are
now printed in the report the script generates.
*Recommendation:* raise N to 800 to match `OVERALL_RANK_LIMIT` — but only after
an accuracy measurement against realized scoring, in the style of
`docs/adjusted-board-backtest.md`. It reprices every row past rank 500.
*Decision needed:* product call on whether the board should publish 800 ranks at
all, and budget for an accuracy backtest.

**U2 — cross-curve commensurability (M2).**
*Ambiguity:* should GLOBAL and OFFENSE agree at the same rank?
*Current:* they diverge to 1.95× by rank 400 and are averaged together.
*Interpretations:* (a) correct — a cross-market rank-400 asset is genuinely
different from an offense-only rank-400 asset; (b) a scale error.
*Recommendation:* (a) is probably right, but the relationship is unpinned and the
promotion gate measures a different percentile convention than production serves.
*Decision needed:* state the intended relationship, then pin it with a test.

**U3 — team value / starter slots / percentile (M3).**
*Ambiguity:* three concepts with 3, 5 and 5 implementations respectively.
*Current:* divergent; consequences include a sharp-manager cohort bar that is
unreachable at n=2.
*Recommendation:* one percentile helper and one starter-slot source (the league
registry) are mechanical and safe. "Team value" is **not** — a lineup-solved total
and a simple sum answer different questions, and `roster_intel` runs on a 0-100
ROS index while the board is 0-9999. They should be renamed to say which they are
rather than merged.
*Decision needed:* whether `/rosters` should show lineup-constrained or raw-sum
team value. That is a product question, not a math one.

**U4 — BDVM `season` semantics (M6).** Latent today. The projection season must be
the NFL season; `currentDraftYear` is the rookie-draft year and rolls a year ahead
after May 15 on the date-fallback path. *Decision needed:* none — the fix is
unambiguous; flagged here because it changes no number today and so is easy to
mistake for a no-op.

**U6 — the terminal delta fix is one-directional (from §4.4, R-review).**
*Ambiguity:* H2 made the past sum use only players priceable *then*, removing the
positive bias. The mirror case is untouched: a player priceable then but **not
now** still enters `pastValue` with no counterpart in `presentValue`, biasing the
delta **negative** by the same mechanism. Reproduced by the reviewer at −5880
where the honest two-player answer is +90; `comparedCount: 2` vs `resolved: 3` is
the only tell, and the code comment claims "nothing enters one sum without a
counterpart in the other", which is false in that direction. Reachable — H1's own
`rowsUnpricedByBoard` is exactly the population that can lose a price.
*Recommendation:* build the compared population once, symmetrically, over
`held_then ∪ held_now`, skipping anyone priceable on only one side. That needs
`_sum_roster_value_at_date` to return per-name amounts rather than just names, so
it is a real change rather than a one-liner.
*Decision needed:* none on the math — it is unambiguous. Flagged here rather than
rushed because it is the last item found and deserves its own change with its own
before/after, not a tail-end edit to a large branch.

**U5 — BDVM priors vs the live league.** Every prior in `params_v1.json` was tuned
for a SF/TEP/PPR card; the live league has `bonus_rec_te = 0.0` and `rec = 0.08`.
Out of scope to refit. *Decision needed:* whether BDVM's priors should be refit
before its numbers are trusted for decisions.

---

## Standing limitations

- **No ground truth exists for dynasty asset value.** Nothing here makes any value
  "correct"; it makes the paths coherent and the labels honest.
- KTC's TE curve is measured *within* KTC's board. Applying it to another
  publisher assumes their TEs sit on a comparable base — better founded than a
  flat 1.15, still an assumption.
- Historical replay is contaminated (U1), so anything requiring a time series of
  boards cannot currently be measured properly. Fixing that means archiving all
  21 sources' CSVs, not 3.
- The Appendix-C BDVM fixture reproduces a documented input bug (`RiskProfile`
  positional args land `0.05`/`0.35` in `small_sample` instead of
  `designation_risk`), so BDVM parity is achieved by feeding production the same
  wrong inputs. Fixing it changes the goldens and needs its own decision.
