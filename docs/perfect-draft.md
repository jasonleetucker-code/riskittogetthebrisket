# Perfect Draft — technical reference

The budget-constrained rookie-auction optimizer on `/draft`.

**User-facing summary** (rendered in the panel):

> Perfect Draft compares each available rookie's value with the value of the
> roster player you would likely have to release, then searches for the
> combination of rookies that produces the greatest total roster improvement
> without exceeding your remaining draft budget.

Decisions and their rationale live in
`docs/roster-trade-intelligence/DECISIONS.md`, ADR-009 / ADR-010 / ADR-011.
This file is the mechanical reference.

---

## 1. Where the code is

| Piece | Path |
|---|---|
| Cut ladder + Effective Cut Cost | `src/draft/displacement.py` |
| Roster-context assembly | `src/draft/context.py` |
| Cached adapter | `src/api/draft_optimizer_api.py` |
| Route | `server.py::get_draft_roster_context` (`GET /api/draft/roster-context`) |
| The solve | `frontend/lib/perfect-draft.js` |
| UI | `frontend/components/draft/PerfectDraftPanel.jsx` |
| Fetch hook | `frontend/components/useRosterContext.js` |
| Dev bridge | `frontend/app/api/draft/roster-context/route.js` |

Feature flag `perfect_draft` (LIVE, default on). Rollback:
`RISKIT_FEATURE_PERFECT_DRAFT=0` **and restart** — flag reads are cached per
process.

---

## 2. Rookie value source

`rankDerivedValue`, the canonical 0-9999 board every other engine reads. The
optimizer creates no second valuation.

It reaches the client as `rookieBoardValue` on `/api/draft-capital` pick rows
(`server.py`, from `_our_rookie_pool`, which already computed it and used to
discard it). The existing `rookieKtcValue` field carries the **dollar** value
on the $1200 ladder; that curve is not invertible, so dollars cannot stand in
for board value. `rookieBoardValue` is in
`_DRAFT_CAPITAL_PRIVATE_PICK_FIELDS` and is stripped for unauthenticated
callers.

BDVM is deliberately **not** a source here: it returns `no_projection` for the
2026 rookie class because nflverse has not published 2026 draft data. It
remains a display-only cross-check via the existing Fund-gap column.

### Strategy modes

`balanced` (default) applies **no** tilt — it is exactly the canonical board.
`winNow` and `longTerm` apply a small multiplier keyed on `yearsExp`, applied
identically to rookies and roster players so both sides stay comparable.
Unknown experience returns 1.0; `_yearsExp` is present for 84% of rows while
`_age` is present for 0%, which is why experience is the axis. The tilt is a
heuristic and is labelled as one in the UI — `rankDerivedValue` already prices
age and career length, so a large tilt would double-count.

---

## 3. Expected price

Reused from the board's existing live model, not reinvented:

```
inflation       = RemainingLeague$ / (TotalAuction$ − Σ soldPreDraft)
tierInflation(T)= inflation × (conf × tierHeat(T) + (1 − conf) × 1)
expectedPrice(i)= floor(preDraft(i) × tierInflation(tier(i)))     [ = inflatedFair ]
```

This is also the mechanism by which price responds to rivals' declining
budgets — as dollars leave the pool, inflation moves. There is no second price
model.

**Range.** Dispersion is measured in log space, because prices are
multiplicative ("went for 1.4x sheet") and a symmetric linear band would go
negative at the cheap end:

```
s_T      = sd( ln(paid / preDraftAtPick) ) over recorded picks in tier T
conf(n)  = min(1, n / TIER_CONFIDENCE_MIN_SAMPLES)
s_global = conf(n_all)·s_all + (1 − conf(n_all))·PRICE_DISPERSION_PRIOR
s_eff(T) = conf(n_T)·s_T     + (1 − conf(n_T))·s_global
band     = expectedPrice × exp(∓ z·s_eff),   floored at $1
```

Two levels of shrinkage: a tier's own dispersion toward the board-wide sample,
and the board-wide sample toward `PRICE_DISPERSION_PRIOR`. The weight is the
same one the tier-heat centre already uses, so the page carries one confidence
concept rather than three.

`computeDraftStats` publishes the raw ratios (`tierPriceRatios`,
`allPriceRatios`) and `perfect-draft.js` estimates from them — deliberately
split, because importing the estimator into `draft-logic.js` would drag the
knapsack solver out of its lazy chunk and back into the main `/draft` bundle.

**`PRICE_DISPERSION_PRIOR` is a declared prior, not a measurement.** Nothing in
this repo has a completed rookie auction to fit against, so before the first
sale the band is entirely an assumption; `priceSigmaByTier(...).measured` says
which regime you are in. It is worth knowing how much this matters — the same
$53 rookie, top of a real board:

| state | sigma | band |
|---|---|---|
| before any sale (prior) | 0.350 | $42–$67 |
| a calm room, 6 sales | 0.023 | $52–$54 |
| a hot room, 6 sales | 0.137 | $48–$58 |
| a chaotic room, 6 sales | 0.752 | $32–$88 |

Until 2026-08-04 this whole section was aspirational: the panel called
`priceBand(price, 0.35)` with the sigma hardcoded, and `logPriceDispersion`
was never called in production.

The range is used for display, as a bootstrap input, and for the p75 headroom
figure (§7). It is **not** used to optimize: minimax-regret over auction prices
says "buy nothing expensive", which is exactly the wrong bias for a rookie
draft where the stud is the point.

---

## 4. Effective Cut Cost

```
waiverValue(pos) = best UNROSTERED player at that position (league-wide)
base(p)          = rankDerivedValue(p), or waiverValue(pos) if unranked
ECC(p)           = max(0, base(p) − waiverValue(pos(p))) × scarcityMult(pos(p))
scarcityMult     = 0.85 + 0.30 × clamp(waiverScarcity, 0, 1)
```

- `waiverScarcity` only, verbatim from
  `src/roster_intel/targets.py::_scarcity_multiplier`. Missing signal → 1.0
  (inert), so a league without a ROS snapshot degrades rather than fails.
- An unranked player scores 0 and is stamped `valueBasis: "assumedWaiver"`,
  which the UI surfaces as "unpriced". Substituting the board's 375/497 floor
  would let an identity-join miss on a real asset read as a cheap cut.
- A positionless player falls back to the *cheapest* positional waiver level —
  the most conservative real number available. Using 0.0 would make him look
  maximally expensive to cut, the opposite of the truth.

**Currency discipline** (`src/api/gameplan.py` states this as a repo-wide
tripwire): `rosValue` (0-100 log-rank) answers *who starts*; `rankDerivedValue`
(0-9999) answers *what is it worth*. Only the former reaches the lineup solver,
only the latter reaches cost arithmetic. Of the six `ScarcityComponents`
fields, only the three `*Scarcity` ones are dimensionless — the separation/gap
fields are `rosValue` units and must never be added to a board value.

### The ladder

Greedy cheapest-first, with `solve_optimal_assignment` re-run after each
candidate: a player is admitted only if releasing him does not reduce how many
starting slots the surviving roster can fill. Compared against the **baseline**
fill count, not `len(slots)` — a roster that already cannot fill every slot
would otherwise report nobody as droppable.

Greedy is exactly optimal: legal cut-sets are the independent sets of the dual
of a transversal matroid, greedy is optimal on a matroid, and successive
minimum-weight independent sets nest. `tests/draft/test_displacement.py` checks
this against brute force at every cardinality rather than asserting it.

---

## 5. Net roster value and the optimization

```
openRosterSpots = rosterSize − currentRosterCount
L               = free-agent values, descending, EXCLUDING this auction's rookies
W(n)            = Σ of L's first n rungs
R(k)            = W(open) − W(open − min(k, open))       ← the TAIL, see below
releaseCost(p)  = baseValue(p) · scarcityMult(p)
D(k)            = Σ of the (k − open) cheapest releaseCosts   ( 0 when k ≤ open )

maximize  Σ_{i∈S} boardValue(i)·tilt − R(|S|) − D(|S|)   s.t.  Σ price(i) ≤ budget
```

Both `R` and `D` depend only on `k`, so this decomposes into a
cardinality-constrained 0/1 knapsack `F[k][b]`, then
`argmax_k (F[k][B] − R(k) − D(k))`. Exact, pure JS, integer dollars.

**Why `R(k)` is the tail and not the top-k.** The baseline is "buy nothing",
and an idle team does not leave roster spots empty — it fills them off the
wire. A plan that uses `k` of those spots therefore forgoes the *last* `k` free
agents it would have signed, not the best: with five open spots, buying one
rookie costs the fifth-best free agent, because you still sign the top four.
Once `k` reaches `open` the charge saturates at `W(open)` — every spot is
spoken for, and further rookies displace rostered players instead.

**Why the cut side is `releaseCost` and not `ECC`.** ECC is measured *over*
waiver level, which was consistent while a rookie's gain was measured over
waiver level too — the two terms cancelled and the model was coherent by
construction. Under a ladder they do not cancel, and keeping ECC would take the
waiver credit twice. This is not a rounding difference: **23 of 30 rungs on the
2026-08-04 board have an ECC of exactly zero**, twelve of them unranked players
whose `max(0, waiver − waiver)` is structurally 0 — the free-cut-on-an-
identity-join-miss failure §4 says the design prevents, and did not.
`releaseCost` charges `baseValue × scarcityMultiplier`, and `baseValue` already
carries the unranked fallback, so a join miss costs a full waiver level to
release rather than nothing.

Taking the **cheapest releases rather than ladder order** is exact, not a
heuristic: the backend's greedy built its rungs as a nested sequence of legal
cut-sets, so all of them are jointly droppable, and every subset of an
independent set in a matroid is independent.

`consumptionOrder` is the single answer to "which cut is next", and **every**
consumer must use it: the charge table, `applyDraftProgress` (mid-draft),
`realizedResults` (what you bought) and the panel's cut column. The backend
orders by ECC and the plan charges by release value; those orders are
unrelated, so a consumer walking the wrong one charges a player twice and
another never. Three separate places got this wrong before it was unified —
worth remembering before adding a fourth.

`k` is a **free variable** — the league caps nobody's rookie count. The
optimizer may return zero rookies, one, or many, and is never required to spend
the full budget.

`kMax` is bounded soundly rather than heuristically, but the *form* of the
bound had to change with `R(k)`. The old early-exit relied on marginal cost
being non-decreasing, which held when the only cost was the cheapest-first cut
ladder. `R`'s marginal term is not monotone across the `k = open` boundary
(it jumps from the ladder's best rung to zero as cuts take over), so a first
failure no longer implies every later one. The ladder path instead scans
`UB(k) = Σ(top-k values) − R(k) − D(k)` — an upper bound on net at that
cardinality — and keeps the largest `k` with `UB(k) > 0`. The flat path keeps
the tighter monotone stop, which is still valid there.

**Performance note.** The charge table is built once per solve, not per query.
`computeMaxBid` evaluates its indifference price over every dollar from the
budget down, times every cardinality, times every recommended rookie; sorting
the release ladder inside that loop measured **1129 ms** against 327 ms before
— roughly 460,000 sorts of the same thirty numbers. Precomputed prefix sums
bring it back to 312 ms.

Rookies the board cannot price, or with no expected price, are **excluded and
reported** in `excluded[]` (per the `assetsUnpricedByBoard` precedent), never
silently priced at zero.

---

## 6. Max bid

```
Φ_i(q)         = max net over plans containing i priced at q   (DP over items \ {i})
planMaxBid(i)  = max{ q ∈ [price_i, B] : Φ_i(q) ≥ bestNetWithout(i) }
```

An indifference price. No value→dollar exchange rate is needed or invented.
Negative means "do not bid" (clamped for display); `B < price_i` yields an
empty feasible range and 0, with no special case.

`bestNetWithout(i)` doubles as the **pivot**: the plan to fall back to if that
rookie is lost, which is what the sequence lines render ("pursue to $X; if he
goes higher, the money is better spent on …").

Named `planMaxBid` because the board already shows `myMaxBid`,
`theoreticalMaxBid`, `myWinningBid`, `bayesianWinningBid` and `enforceUpTo`.

---

## 7. Confidence

Parametric bootstrap over the top ~8 candidate plans — the cardinality frontier
**plus** the per-rookie pivots. The pivots matter: the frontier keeps one
winner per cardinality, so two tied plans of the same size are invisible
without them.

- Value shock per player: `exp(N(0, cv))` where `cv` is the board's
  `marketDispersionCV`, floored at 0.35 for single-source rows (they already
  carry the pipeline's 30% haircut, so their remaining uncertainty is real).
- One shock per distinct player, **shared across every plan containing him** —
  that is what gets the correlation right, so a one-swap difference reads as
  tight even when both totals are noisy.
- Plans are **re-scored, not re-solved**.
- `confidence = P(plan 1 wins)`. **Near-tie = any rival plan with P ≥ 0.25.**
- Seeded PRNG (mulberry32): an unseeded RNG would make the displayed
  confidence flicker on every re-render, reading as instability rather than
  uncertainty.

A flat "within 2%" band was rejected: 2% of a large total is an arbitrary
absolute number on an arbitrary scale, and it ignores correlation entirely.

### Reading the CV's zero

The scraper's `_coeff_var` returns `0.0` whenever it has fewer than two
comparable site values, so **a zero CV means dispersion was unobserved, not
that the sources agreed** — and it is the thinnest-covered rows that get it.
Measured on the 2026-08-04 board, 31 of the top 72 rookies have no observable
dispersion. Passing that `0.0` through as a sigma would have presented the
least trustworthy values on the board as the most certain ones.

So `_our_rookie_pool` nulls non-positive at the source, and `valueSigmas`
places an unobserved row at the **p90 of the dispersion observed across this
pool** — the pessimistic end of the real distribution rather than a declared
constant, falling back to `defaultCv` only when there are too few observations
to form a p90.

Until 2026-08-04 neither `marketDispersionCV` nor `singleSource` was set
anywhere in the draft data path, so every rookie took one flat `defaultCv` and
the single-source floor could never fire. Two honest notes on what fixing it
bought:

- **On today's board it changes nothing visible.** The recommended plan is
  identical and confidence matches to 3 s.f. (39.5% either way), because the
  measured stand-in (0.075) lands almost exactly where the old constant (0.08)
  sat and the observed CVs are small relative to the surplus gaps. The wiring
  is live, not inert — scaling the real CVs 5x moves confidence to 22.0% and
  surfaces a near-tie — but this was a correctness fix, not an improvement to
  today's numbers.
- **`singleSource` is a narrow term, not a broad one.** Only 2 of the top 72
  rookies carry the pipeline's semantic single-source flag (Rahsul Faison,
  Caullin Lacy) — it requires that matching *could* have produced more than one
  source, a much stricter condition than "we only observed one value". Both sit
  inside the 31 unobserved rows, so the 0.35 floor raises those two above the
  p90 stand-in and the unobserved-CV path covers the other 29 on its own.

### Price risk

Price enters as **feasibility** risk, which is the only honest route: surplus
is value over replacement and does not depend on what a rookie cost, so a price
draw cannot move a plan's net value. What it can do is push a plan's spend past
the budget, and an unaffordable plan is not the best plan. Plans resting well
under budget are untouched; a plan spending to the ceiling loses confidence.

The frontier carries an empty `k = 0` plan, so scenarios in which nothing is
affordable are absorbed by "buy nothing" competing as a plan rather than
vanishing. (`assessPlans` also counts `infeasibleDraws` for callers that assess
a hand-built list with no empty plan in it.)

`meta.budgetHeadroomAtP75` re-prices the recommended plan with every rookie at
the top of his band. It is `null` — never `0` — when no price sigma was
supplied, because "not measured" and "no risk" must not render identically.
On the live board a plan spending the full $400 shows −$28 of headroom at a
modest sigma of 0.1, which is precisely the thing the panel previously could
not say.

---

## 8. Live updating during the auction

The solve is a `useMemo` over live workspace state, so it re-runs whenever:

- a rookie is drafted or a final price is recorded — by hand, by the `Q`
  quick-record, or from the live Sleeper feed (`useSleeperDraftSync` →
  `handleLivePick` → `recordPick`),
- a team's budget is edited or `/api/draft-capital` re-syncs,
- inflation or tier heat moves (which any recorded pick does),
- a PreDraft value is edited,
- the strategy mode or the selected team changes.

`stats` is memoized on `workspace` (`page.jsx`), so the chain fires on real state
changes rather than on every render.

### Consuming what has already been bought

The roster context is a **pre-draft snapshot**: its `openRosterSpots` and cut
ladder describe the roster before the auction and do not move when a rookie
sells. `applyDraftProgress` advances both past this team's purchases — each
rookie bought fills an open spot first, then consumes the cheapest remaining
rung, matching the order the plan itself assumes.

Without it, two things break the moment you buy anything: roster room is
double-counted (three rookies into one open spot, and the model still thinks the
spot is free), and the ladder re-offers rungs those purchases already consumed —
i.e. it recommends releasing the same player twice, which is exactly what the
spec forbids. Budget already flowed through correctly via `stats.myRemaining`;
this is the other half.

`ladderExhausted` is surfaced explicitly, because "no roster room left to model"
and "nothing is worth buying" render identically and mean opposite things.

### Phase, and completed results

`draftPhase(stats)` → `pre` | `live` | `complete`, from picks recorded against
the pool size, shown as a badge. `realizedResults` values what has already been
bought using the *same* surplus and ECC primitives as the plan, so the
"bought so far" line and the remaining plan are directly comparable — a separate
results formula would drift.

### Cost and responsiveness

A full solve measured ~140 ms at a $417 budget on the live board (most of it the
per-rookie max-bid DPs). The solve inputs go through `useDeferredValue` so a
burst of live picks cannot jank the board; the previous plan stays painted and
the header shows "Recalculating…" until the new one lands.

### Refetching the roster context

Fetched once per (league, team), and on `league:changed` / `auth:changed`. It is
static for a draft and the server build is ~1.35 s cold, so it is deliberately
not polled — purchases are applied client-side instead. A mid-draft **trade** is
the exception, so the panel carries an explicit "Refresh roster" control.

### Bundle

The panel is code-split with `React.lazy` + `Suspense`, keeping it and the
optimizer out of the initial `/draft` chunk: 124.7 KB against the 128 KB budget,
versus 141.9 KB statically imported. (`main` sits at 125.8 KB *without* this
feature, so the page was already at the edge.)

`React.lazy` rather than `next/dynamic`, and the choice is measured. `next/dynamic`
pulled Next's loadable runtime into the shared chunk graph and moved ~8 KB out of
the common chunk into **every** page's own chunk — `/page` 71.5 → 79.8,
`/settings` 43.5 → 51.7, and `/waivers` 30.8 → 38.7, which broke its 36 KB
budget as collateral. `React.lazy` uses webpack's plain dynamic import and leaves
every other route byte-identical to `main`. Verified by building both.

The fallback is `null` deliberately: the panel renders nothing until its own
fetch settles, so a placeholder would only add a flash of layout.

Server-side cache key: contract identity (`id` + `generatedAt` +
`scrapeTimestamp`), league key, and **team identity**. The last is what
structurally prevents one team's results reaching another.

---

## 9. Known limitations

- **BDVM cannot price the 2026 rookie class** (upstream nflverse gap). When it
  can, `strategyMultiplier` is the single seam to replace with a measured
  contender/rebuilder currency.
- **Taxi squads are not modelled.** `dynasty_main` has none
  (`rosterPositions` = 21 starters + 37 BN, no `TAXI`, no `IR`), but
  `dynasty_new` has 5. Nothing in this codebase ingests Sleeper's per-player
  taxi assignment; the payload carries `taxiSlotsAvailable` (default 0) and
  says so in `notes` rather than guessing.
- **Second league gets the board but not the panel**, and the reason changed.
  This entry used to say the Sleeper-derived draft-capital fallback "emits no
  rookie fields, so `/draft` there falls back to a hardcoded rookie list". That
  is no longer true: `_serialize_pick` staples the real rookie board onto the
  current season's slots (`src/api/draft_capital_fallback.py`), so `dynasty_new`
  sees genuine rookie names and values on `/draft`.

  The panel still vanishes there, for a different and unchanged reason: the
  optimizer needs that league's **rosters**, not its rookie fields.
  `GET /api/draft/roster-context` gates on whether the loaded contract's
  `leagueKey` matches the request, and the server holds one league's rosters at
  a time. So this unblocks when the second league's rosters are loaded — not
  when the fallback improves.
- **RESOLVED (2026-08-04), and the fix did not do what this entry predicted.**
  The flat per-addition waiver charge is gone, replaced by the `R(k)` ladder in
  §5, and the auction's own rookies no longer count as free agents. But this
  entry claimed the flat charge was the cause of the model's preference for
  large `k`, and that `W(k)` would correct it. Measured on the live board, it
  does not: the recommendation moved from 35 rookies to 34.

  The actual cause was on the **cut** side. `ECC = max(0, base − waiver)` is
  zero for any player at or below his position's waiver level, and that was 23
  of 30 rungs — so the model believed it could release 23 rostered players for
  nothing and would fill the roster to capacity with $1 rookies every time.
  Charging `releaseCost` instead is what makes the cut side bite. See §5.

  What remains, and is now the honest statement of the limitation: **roster
  value is an unweighted sum of market values.** A 58-man roster starts 21, so
  bench player #40 does not contribute his full market value — but the model
  says he does, which is why swapping deep bench bodies (~1300) for marginal
  rookies (~2400) still scores positive 34 times over. The frontier and the
  star-focused alternative remain the mitigation, and the confidence figure on
  such plans is low (0.11 on the live board) precisely because the top
  cardinalities are not separated. The real fix is lineup-aware roster value —
  `src/ros/lineup.py::solve_optimal_assignment` already computes it, and is
  already used on the cut side for *droppability* but not for *value*. That
  breaks the `k`-decomposition, so it is genuinely harder than this entry
  previously implied.

  **MEASURED (2026-08-05).** `scripts/measure_lineup_value_gap.py` walks
  `k = 0..40` rookies onto a real roster and compares what the naive objective
  credits against what the league's own 21 starting slots can actually field,
  scored by the real solver. The distortion is not marginal — on the
  2026-08-05 board, over `k = 1..40`:

  | team | roster | naive credits | startable credits | share | first rookie adding 0 |
  |---|---|---|---|---|---|
  | Blaine | 53 | 132,172 | 33,411 | **25.3%** | k=3 (26 of 40 add nothing) |
  | Eric | 58 | 132,172 | 15,995 | **12.1%** | k=6 (29 of 40) |
  | MaKayla | 58 | 132,172 | 14,355 | **10.9%** | k=6 (30 of 40) |
  | Jason | 57 | 132,172 | 11,478 | **8.7%** | k=3 (32 of 40) |

  Past roughly `k = 20` every additional rookie adds **exactly zero** startable
  value on every roster tested. So the objective is crediting four to eleven
  times the value the lineup can realize, and the high-`k` preference follows
  directly.

  **But pure lineup value is not the answer either, and that is the real
  finding.** This measurement scores *today's* lineup, and these are dynasty
  rookies — a player who cannot crack the lineup now is exactly the asset
  class this league is built to accumulate. Bench depth is also injury
  insurance and trade currency. Zero is as wrong as full market value; the
  truth is bounded between them.

  That reframes Phase B. It is **not** "swap Σ market value for lineup value" —
  that would trade one wrong number for another and would tell a dynasty
  manager to stop buying at 20. It is "value a bench player below a starter at
  a rate that is derived rather than invented", which is the same objection
  §9's positional-balance entry raises. Until that rate has a defensible
  source, shipping either extreme would be a regression dressed as a fix.

- **Opponent modelling is a price cap, not a bidding model.** `bayesianTopCompetitor`
  (nomination-decayed tier interest) now reaches the optimizer through the
  **Prices** control: `"fair"` is the board's inflation-adjusted price and the
  default; `"contested"` caps it at one dollar past the richest rival who still
  wants that tier, which is what an auction actually settles at. The cap only
  ever LOWERS a price, so it is never more optimistic about affordability — it
  just stops requiring you to outbid budgets that no longer exist, which is the
  late-draft failure mode. It still knows nothing about bid ORDER, or about a
  rival who wants one specific player badly.
- **The price prior is declared, not fitted.** `PRICE_DISPERSION_PRIOR = 0.35`
  is a plausible starting width, not a measurement, and before the first sale
  of a draft it is doing all the work. Fitting it needs one auction recorded
  end to end; `priceSigmaByTier(...).measured` distinguishes the two regimes in
  the meantime.
- **Positional balance is reported, not optimized.** The plan is chosen on
  value alone; `planPositionBalance` states the consequence beside it — which
  starting slots this roster cannot fill (measured against the league's own
  `starters` block, not a constant), which of them the plan fills, and which it
  leaves open. Folding a positional minimum into the objective would need
  per-position counts in the dynamic program's state, which is exactly the
  explosion the `k`-only decomposition avoids, and it would mean inventing a
  rate at which a filled starting slot is worth giving up board value. That
  rate is a judgement, so it is surfaced rather than assumed.
- **Nomination order is not modelled.** A plan requiring three specific wins is
  more fragile than the confidence number alone conveys; the pivots partially
  cover this.
- **Roster-tail values are noisy.** Cut costs at the bottom of a roster rest on
  thin-coverage rows; the `assumedWaiver` stamp marks them but cannot fix them.


### Live bidding

`evaluateBid(input, rookieId, bid)` answers the question a live auction
actually asks — *"the bidding is at $X, do I go?"* — which is **not** the one
`planMaxBid` alone answers. `planMaxBid` is an indifference price computed
against the board's expected prices for everyone else; a bidder in the moment
needs the comparison between two concrete futures: win him at this number, or
lose him and run the pivot.

Both branches come free from the solve `computeMaxBid` already performs —
`Φ(bid)` is the best plan containing him at that price, `bestNetWithout` is the
pivot. No new model and no second price concept.

`verdict` is deliberately coarse (`go` / `limit` / `stop`). The numbers behind
it carry uncertainty the panel reports separately, and a finer scale here would
read as more confidence than exists.

---

## 10. Backtesting: what is missing, and what was done about it

`scripts/backtest_perfect_draft.py` exists and **cannot produce a verdict on
any data in this repository**. It exits 2 (skipped) and says why, rather than
scoring something else and calling it a backtest.

Four inputs are needed. Three were absent and one cannot be backfilled:

| # | Input | Status |
|---|---|---|
| 1 | realized `(player, price)` pairs from a completed auction | **partly unblocked** — see below |
| 2 | a season-agnostic draft resolver | partly unblocked with (1) |
| 3 | a pre-draft board snapshot from before that auction | **cannot be backfilled** |
| 4 | a pre-draft roster snapshot (open spots, cut ladder) | now capturable |

`CSVs/Draft Data.xlsx`'s `Final Price` column is three literal zeroes over a
class that has not drafted. Realized prices otherwise live only in the browser's
`localStorage` draft workspace and were never persisted anywhere.

**What was fixed:** `src/public_league/draft.py::_normalize_pick` was reading
Sleeper's pick metadata for names, position and team and **discarding
`metadata.amount`** — the sale price. The multi-season raw picks were already
being fetched. Carrying one field through turns an existing fetch into a
realized-price corpus. `amount` is `None` for a snake draft, which is a
different statement from `0`, and the two must not be allowed to read alike.

**What cannot be fixed:** `rank_history` appends one entry per scrape date and
does not reach back past `exports/archive/`'s 2026-07-14 start. The pre-draft
board for any earlier auction was never observed, and no code recovers an
observation nobody made. So the first honestly backtestable event is the 2026
rookie auction itself.

`--record-snapshot` captures the pre-draft board and every team's roster
context together, because a recommendation can only be scored against the state
it was made from — and the roster context stops being recoverable the moment
the first pick lands. Run it **before** the auction. That is the missing step,
and it is the only one code can fix.
