# chaseTradeMarket preregistration — DRAFT, NOT FROZEN

**Status: DRAFT.** Nothing in this file binds a fit yet. Every value marked
`⟨PLACEHOLDER⟩` must be fixed, and the file frozen (commit SHA + content hash
recorded in §12), **before any real held-out trade is examined**. That includes
any run that computes residuals on a candidate reserved trade.

- **Owner directive:** Chase Upside Trade Market, 2026-10-19. The later V2 text
  wins on any conflict. It says to use leagues with at least three verified
  completed seasons, treat two-season leagues as a separate research cohort,
  and keep the source non-voting until validated and owner-approved.
- **Build plan:** the chaseTradeMarket synthesis plan, revision 2: G12s (the
  simulation behind this draft) and G13 (this file).
- **Product authority:** none. This file does not authorize a source, a vote, a
  weight or any change to a served value. `docs/EXECUTION_PLAN.md` remains the
  authorization record.
- **Synthetic evidence behind the placeholders:**
  `docs/market_trades/CHASE_TRADE_MARKET_POWER_STUDY.md`.

## 0. Freeze procedure

1. P6 runs `scripts/chase_trade_market_sim.py` on the box, on the **real
   trade-graph topology**. That run needs the real topology mix, activity
   distribution, manager–lineage component sizes and collection latency (P2
   evidence fields). The synthetic defaults in this draft stand in for those
   measured inputs. Only aggregate counts leave the box.
2. Every placeholder below is replaced with a value derived from that run plus
   inner CV on training components. Each value is written with its derivation.
3. The file is renamed out of DRAFT, its hash is recorded in §12, and it is
   committed by a human-reviewed PR.
4. The reserve sub-ledger access log (plan §5) records the first read of each
   sub-reserve only after step 3.
5. After the freeze, any change is a **new version**: a new file section and a
   new hash, and the reason is logged in §11. That applies in both directions,
   tightening or loosening. Nothing changes automatically.

## 1. Estimand

- **Voter estimand:** `transactionMarketValueGeneric`. This is the marginal
  clearing valuation of the sharp-graph verified-dynasty trade market.
  - It is post-stratified to the declared reference format: Superflex, TE
    demand level `⟨PLACEHOLDER⟩`, reception-scoring level `⟨PLACEHOLDER⟩`.
  - It is scoped to the scoring profile.
  - It is labelled a **sharp-graph sample, not all dynasty**.
- **What votes:** only the **rank** votes, through the existing rank →
  percentile → Hill scope curve. The spacing is declared as borrowed from the
  existing curve (`scale_borrowed_from`).
  - Synthetic finding: cardinal spread is weakly identified (power study §4.3),
    so no cardinal value votes.
- **`transactionMarketValueTargetLeague`:** a diagnostic only. It stays `null`
  as `no_validated_translator` until AL-2b.

## 2. Populations and maturity

- **Cohort A:** at least 3 completed **dynasty** seasons, verified through the
  real `previous_league_id` chain.
  - A hop counts only if `settings.type == 2` and `status == "complete"`, and
    the season is earlier than the trade's season-league.
  - A lower bound below 3 means "maturity unknown", never A.
- **Primary maturity reading:** `⟨PLACEHOLDER: point-in-time at the trade |
  league-level as of the build⟩`. This is owner question Q5. If Q5 is still
  unanswered at freeze, the point-in-time reading is primary, and the other
  reading is **always reported beside it**.
- **Cohort B (two completed seasons):** a separately reported research cohort.
  It is never silently merged into A.
- **Exclusion census:** for every exclusion reason, report the trades and
  leagues lost (plan §3 reason codes). This applies to KTC-linked lineages,
  Insider-pool and own-league-member strata (primary-population exclusions,
  each also run as a sensitivity arm) and the A/B/C cohort boundaries.
- **KTC separation:** Sleeper-observed and KTC-database observations stay
  separate lanes.
  - The KTC overlap is measured (X9) before any re-admission rule applies.
  - The first voting candidate uses Sleeper-observed trades only.

## 3. Splits

| Item | Value |
|---|---|
| Reserve assignment | `sha256(componentId ‖ committedSalt)` over manager–lineage components, assigned once, append-only |
| Reserve share | `⟨PLACEHOLDER: 20%⟩` (owner Q2) |
| Sub-reserves | R-act, R-hill, R-D8, R-AL1, R-AL2b, each with an access ledger |
| Chronological holdout window | `⟨PLACEHOLDER: 56 days⟩` |
| Purge gap | `⟨PLACEHOLDER: 7 days⟩` |
| Availability filter | training = **collected** on or before the cutoff. Trade date is never the filter |
| Inner CV | training components only; chronological inner validation of `⟨28 days⟩` |

**Synthetic warning (power study §4.5).** If Sharp managers sit in many
leagues, manager–lineage components merge into a few giant components. In the
simulation, a 10% per-seat overlap collapses 160 leagues into 25 components,
one of which holds 130 leagues. The P1 census must measure real component
sizes before the reserve share is fixed. Few components mean wide intervals
and few independent folds, however many trades there are.

## 4. Model

- **Primary candidate:** E2 (plan §4.2). It combines:
  - sorted geometric package utility with `q` pinned to `geom_q078_v1` as a
    declared benchmark;
  - Huber loss with `k = 1.345` on a stage-1 MAD scale;
  - recency weights `0.5 ** (age / H)`, where age runs from the **evidence
    cutoff**;
  - per-league and per-manager-pair caps;
  - format covariates;
  - a consensus-free prior (position mean plus age or draft-capital covariate);
  - a penalised manager effect, once G8 side keys exist.
- **Baselines** (all scored identically):
  - `prior_only`;
  - `naive_sum_l2` (raw summed totals);
  - `bt_consolidation` (graph / Bradley–Terry);
  - E0, E0γ, E0-iso, E1, canonical, KTC Crowd, KTC Trades (in-sample flagged),
    FantasyCalc.
- **Aggregator matrix:** train under {0.70, 0.78, 0.85, 1.0, KTC VA} and
  evaluate under each. Each comparator gets its best-case aggregator.

**Configuration grid** (chosen by inner CV on **hard-decoy accuracy**):

| Knob | Declared prior | Inner-CV grid |
|---|---|---|
| Half-life H | 90 days | `⟨{45, 90, 180, none}⟩` |
| League cap C | `⟨25⟩` | `⟨{10, 25, 50, none}⟩` |
| Manager-pair cap | `⟨4⟩` | `⟨{2, 4, 8, none}⟩` |
| Prior width τ (log units) | `⟨2⟩` | `⟨{1, 2, 4}⟩` |

**Why hard-decoy accuracy and not residual loss.** On a 1-for-1 trade, a
completely compressed board, where everyone has the same value, has residual 0.
So residual loss rewards shrinking all values together. Decoy accuracy gives a
compressed board exactly 0.5 (pinned by test).

**Synthetic finding on H.** At low volume the recency-weighted fit loses to an
unweighted one. At high volume it wins (power study §4.2). H is therefore
**chosen, not assumed**. A lone declared prior is not acceptable at freeze.

## 5. Support procedure (per asset, per segment)

An asset is **SUPPORTED** only if every condition below holds. Otherwise it is
PRIOR_DOMINATED (published privately, `eligibleToVote: false`). It is
INSUFFICIENT (published `null` with a reason) when it has no trade evidence or
lies outside its domain's two-edge-connected core.

| Criterion | Draft value |
|---|---|
| Information-weighted appearances (slot at sorted rank k counts `w · q^k`) | ≥ `⟨3.0⟩` |
| Distinct manager–lineage components | ≥ `⟨3⟩` |
| Largest single-component information share | ≤ `⟨0.6⟩` |
| Prior share `τ⁻²[C H⁻¹ Cᵀ]_aa` (contrast space) | ≤ `⟨0.5⟩` |
| Full-row prior influence `τ⁻² Σ_b \|[C H⁻¹ Cᵀ]_ab\|` | reported; gating rule `⟨PLACEHOLDER after X1⟩` |
| Contrast SE (cluster-robust, components) | ≤ `⟨0.35⟩` log units (precision only; the calibrated interval criterion moves to rank space, §8) |
| Effective resistance to the core | ≤ `⟨PLACEHOLDER⟩` (diagnostic until set) |
| `packageModelSensitive` (rank/Hill shift across the aggregator matrix) | false |
| Latest evidence within the recency horizon | `⟨PLACEHOLDER⟩` |

**Synthetic finding.** The full-row prior influence is **not bounded by 1**,
because neighbouring assets' posteriors are positively correlated. Its median
was about 1.2 and its 90th percentile about 3.7 for traded assets in a default
world. It therefore cannot use a "≤ 0.5"-style threshold. The diagonal share
(about 1 with no evidence) is the draft gate.

## 6. Primary endpoints (gatekeeping offense → IDP → picks)

These are as in plan §5:

1. **X3:** held-out loss of the canonical board rebuilt with versus without
   the source, on R-act.
2. **X4:** the 1-for-1 percentile-gap test.
3. **Decoy choice metric:** the actual counter-package ranks above size-matched
   decoys and same-position swap decoys from the same league and month.
4. **Ordering gain over E0-iso.**

All other analyses are exploratory, with Holm or simultaneous intervals. Every
"no rise" claim gets a TOST equivalence margin of `⟨PLACEHOLDER⟩`. The looks
budget per sub-reserve is `⟨2⟩`.

## 7. Sample-size gate (the "exact shortfall")

**Readiness requirement.** The source may not enter validation for a segment
(domain × tier) until its eligible **training** trades reach the requirement
from the on-box real-topology power run.

**Draft per-tier target, in simulation.**
- Pairwise ordering accuracy, on pairs whose true values differ by at least
  20%, must reach `⟨0.90⟩` on SUPPORTED assets.
- **And** supported coverage must reach `⟨0.80⟩` of the tier.

The requirement is the larger of the two. An accurate model that prices
almost no one has not met an accuracy target.

**Reported for each segment:**
- required training trades;
- required total eligible trades, including the reserve and holdouts;
- required leagues at the observed trades-per-league;
- the shortfall, calculated as
  `max(0, required − observed)`.

If the observed count is unknown, the shortfall is UNKNOWN, never 0. A
requirement beyond the simulated grid is reported as `beyond_grid` and is
never extrapolated.

## 8. Interval calibration

- Nominal 90% contrast intervals use cluster-robust SEs over manager–lineage
  components with `t(G−1)` quantiles.
- **Synthetic finding (power study §4.3):** top-tier coverage falls toward 0
  as data grows. That is 0.02 at about 1,900 training trades. The cause is
  that value spread is weakly identified, so shrinkage biases top contrasts
  toward the core. The SE shrinks; the bias does not. Inflating the SE cannot
  fix a bias that does not shrink.
- **Therefore, before freeze, P6 replaces the §5 interval criterion with a
  RANK-space interval:** a cluster bootstrap of the asset's rank over
  manager–lineage components (multinomial, not Dirichlet).
- That interval must reach `⟨0.85⟩` coverage of nominal 90% per tier in the
  real-topology simulation. Otherwise the support status for that tier is
  capped at PRIOR_DOMINATED.

## 9. Does league age improve the signal? (directive V2 §2)

- **Test:** per league, take the mean absolute held-out residual under the
  frozen fit. Compare cohort A with younger leagues using a one-sided
  Mann–Whitney test at α = `⟨0.05⟩`.
- **Readings:** report the test under both maturity readings.
- **Volume-matched arm:** subsample A+B down to A's information.
- **Size of test:** the null false-positive rate was measured in simulation
  (power study §4.6).
- **Synthetic power:** for a declared effect of `exp(−0.3·(seasons − 3))` on
  clearing noise, detection power reached about 0.6–0.8 only at 160+ leagues
  with 20 trades per league.
- **Underpowered case:** if the real data are below that, the result is
  reported as **underpowered, not as "no effect"**.

## 10. Picks and IDP

- **Picks** stay held from voting for the structural reason in plan §4.10.
  Their support statistics are reported.
- **IDP** waits for #1847 and the Signals IDP lane. In simulation, IDP tiers
  needed several times the offense volume, because only IDP leagues trade IDP
  assets (power study §4.1). Readiness is reported as a separate segment.

## 11. Deviations log

| Date | Version | Change | Reason | Reviewer |
|---|---|---|---|---|
| — | draft | — | — | — |

## 12. Freeze record

| Field | Value |
|---|---|
| Frozen at (UTC) | `⟨PLACEHOLDER⟩` |
| Commit SHA | `⟨PLACEHOLDER⟩` |
| sha256 of this file at freeze | `⟨PLACEHOLDER⟩` |
| Real-topology simulation receipt | `⟨PLACEHOLDER⟩` |
