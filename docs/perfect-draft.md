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
s_T   = sd( ln(paid / preDraftAtPick) ) over recorded picks in tier T
s_eff = conf·s_T + (1 − conf)·s_global,   conf = min(1, n / TIER_CONFIDENCE_MIN_SAMPLES)
band  = expectedPrice × exp(∓ z·s_eff),   floored at $1
```

The shrinkage weight is the same one the tier-heat centre already uses, so the
page carries one confidence concept rather than two.

The range is used for display and as a bootstrap input. It is **not** used to
optimize: minimax-regret over auction prices says "buy nothing expensive",
which is exactly the wrong bias for a rookie draft where the stud is the point.

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
surplus(i)      = max(0, boardValue(i)·tilt − waiverValue(pos(i)))
D(k)            = Σ of the (k − openRosterSpots) cheapest ECCs   ( 0 when k ≤ open )

maximize  Σ_{i∈S} surplus(i) − D(|S|)     s.t.  Σ_{i∈S} price(i) ≤ budget
```

`D` depends only on `k`, so this decomposes into a cardinality-constrained 0/1
knapsack `F[k][b]`, then `argmax_k (F[k][B] − D(k))`. Exact, pure JS, integer
dollars.

`k` is a **free variable** — the league caps nobody's rookie count. The
optimizer may return zero rookies, one, or many, and is never required to spend
the full budget.

`kMax` is bounded exactly, not capped heuristically: an exchange argument bounds
the gain of the k-th rookie by the k-th largest surplus, its cost is at least
the k-th marginal cut, and marginal cuts are non-decreasing — so once
`surplusDesc[k−1] − m(k) ≤ 0` no larger `k` can win.

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

The panel is mounted via `next/dynamic` with `ssr: false`, keeping it and the
optimizer out of the initial `/draft` chunk (measured: 124.7 KB against the
128 KB budget, versus 141.9 KB when statically imported). `ssr: false` is
required, not cosmetic — the panel reads `localStorage` via `useRosterContext`.

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
- **Second league unsupported.** The Sleeper-derived draft-capital fallback
  emits no rookie fields, so `/draft` there falls back to a hardcoded rookie
  list. The panel vanishes rather than optimizing against placeholders.
- **Multiple additions are each measured against the SAME waiver level.**
  `surplus(i) = boardValue − waiverValue(pos)` is exact for one addition. For
  a `k`-rookie plan the honest comparison is against the 1st, 2nd, … k-th best
  free agent, which declines — so total surplus is optimistic, and increasingly
  so as `k` grows. Measured effect on the live board: waiver levels sit at
  1711-2302 by position with ~500 unrostered ranked players, so the top of each
  positional pool is fairly flat and the per-addition error is small, but it
  accumulates. It is the mirror of the `D(k)` treatment on the cut side and has
  the same fix: subtract a `W(k)` term (the sum of the top-`k` free-agent
  values) instead of a flat per-item waiver level. That preserves the
  cardinality decomposition, so it is a contained change — deferred rather than
  hard.

  Practical consequence today: high-`k` plans look better than they are. The
  frontier and the star-focused alternative are the mitigation — a plan
  recommending 18 rookies and 17 releases is arithmetically defensible under
  the model but should be read alongside its lower-`k` neighbours, and the
  confidence figure on such plans is typically low (0.4 or so) precisely
  because they are not clearly separated.

- **Opponent modelling is coarse.** The plan is priced at expected cost; the
  board's `bayesianTopCompetitor` (nomination-decayed tier interest) is not yet
  fed into plan feasibility.
- **Nomination order is not modelled.** A plan requiring three specific wins is
  more fragile than the confidence number alone conveys; the pivots partially
  cover this.
- **Roster-tail values are noisy.** Cut costs at the bottom of a roster rest on
  thin-coverage rows; the `assumedWaiver` stamp marks them but cannot fix them.
