# chaseTradeMarket simulation and power study (P6a / G12s): synthetic

**What this is.** This study builds an invented dynasty trade market where the
true player and pick values are known. It then measures how many completed
trades, from how many independent leagues, the candidate trade-derived value
models need before their per-tier rankings are right. This is the "exact
shortfall" the owner directive (Chase Upside Trade Market, 2026-10-19; V2
wins) asks for, stated as a **requirement**. A shortfall needs a real
observed count, and only the production box has that.

**What this is not.**
- It used **no real data**: no league, manager, transaction or player identity.
  Every id is `syn-…`.
- It fits nothing that could vote, and it changes no served value, vote,
  weight or contract field.
- The bench estimators are prototypes for this study. P6 owns the production
  estimator (`src/trade/market_trade_price_model.py`, plan G12) and plugs it
  into the same metrics through `FitResult`.
- **Every number below describes the synthetic world**, whose shape (topology
  mix, activity, overlap, noise) is a declared assumption. The on-box
  real-topology rerun (§7) replaces those assumptions with measured
  aggregates. Until then, no real shortfall is claimed.

**Code**
- `src/trade/market_trade_sim.py`: the generator.
- `src/trade/market_trade_sim_bench.py`: the estimators, metrics, power study
  and influence analysis.
- `scripts/chase_trade_market_sim.py`: the CLI.
- `tests/trade/test_market_trade_sim.py`: 27 tests.
- Preregistration draft: `docs/market_trades/CHASE_TRADE_MARKET_PREREGISTRATION.md`.

---

## 1. The math in plain English (directive §10)

**A completed trade is a balance scale.** When two managers agree on a trade,
each side was worth roughly the same to them at that moment. One trade tells
us little. Thousands of overlapping trades, with the same players turning up
against different partners, let us solve for one value per player that keeps
as many scales as possible close to level.

**What a 1-for-1 can and cannot say.** A 1-for-1 says two players are *close*,
not which one is better. Order comes from **packages**. If one player was
traded for two, he is worth more than either of them, so the "2-for-1" trades
are what spread players out into a ranking.

**Second pieces are discounted.** Two quarters are not worth a dollar to a
manager who needs a dollar bill. The model counts a package as best piece +
78% of the second + 78%² of the third, and so on. This is the site's existing
geometric Value Adjustment (`q = 0.78`), used as a declared benchmark, not
assumed to be the true market rule. The simulation shows the *ranking* barely
depends on that choice (§4.4).

**Some trades are lopsided on purpose.** Rebuilds, contender pushes, fleeces
and collusion all happen. The model uses a "robust" error rule. A trade that
looks wildly unbalanced counts linearly, not quadratically, so one strange
trade cannot drag a player's value far. It is not thrown out because it
disagrees with our rankings.

**Recent trades count more.** A trade from 90 days ago counts half as much as
one from today, one from 180 days ago a quarter, and so on. "Today" means the
newest trade the build could actually see, never the calendar.

**No single league or pair of managers dominates.** A very active league's
total influence is capped. So is the total influence of two managers who
keep trading with each other.

**Format matters.** A quarterback is worth less in a one-QB league and a tight
end more with TE premium. The model learns those shifts and reports every
value in one declared reference format.

**How sure are we?** Every player gets:
- an uncertainty band;
- a count of how much trade evidence touched him;
- the number of independent league groups that evidence came from.

A player the trades say little about is labelled *prior-dominated* (shown
privately, never allowed to vote). A player the trades say nothing about is
*unpriced*, with a reason. Missing is never zero.

**The simulation.** We invent thousands of trades in a fake market where we
know every true value. We run each candidate method and check how often it
puts two players in the right order, tier by tier. We repeat that at
different data sizes. The smallest size where a tier reaches the target is
the requirement for that tier.

## 2. The synthetic world (declared assumptions, `SimConfig`)

| Piece | Default | Why it is there |
|---|---|---|
| Assets | 160 offense, 60 IDP, 36 picks (3 years × 4 rounds × 3 tiers) on a Hill-like 0–9,999 shape | the three domains |
| Value drift | random walk, 0.03 log/week | old trades describe an older market |
| Topology | 1-for-1 38%, 2-for-1 24%, 2-for-2 12%, 3-for-2 10%, 3-for-1 8%, 4-for-2 4%, 3-for-3 4% | unequal packages; counter-side built to clear under the TRUE aggregator `q_true = 0.78` |
| Clearing noise | Student-t (4 df), scale 0.12 log; 3% grossly lopsided trades (±0.8–1.6 log); manager overpay effect sd 0.05 | trades are not fair |
| Activity | lognormal trades per league (σ 0.8) | a few hyperactive leagues |
| Manager overlap | 2% of seats filled by a manager from another league | manager–lineage components (§4.5) |
| Format | 30% one-QB (QB −0.55 log), 40% TE premium (TE +0.25 log); IDP assets only in the 30% IDP leagues | format strata; reference = SF / no TEP |
| Maturity | completed seasons 1–6 (20/25/20/15/10/10%); both readings | cohorts A / B |
| Latency | exponential, mean 2 days; 5% backfilled late | folds filter on collection time |
| Prior covariate | correlated 0.5 with truth within domain | the consensus-free prior (age / draft-capital stand-in) |

**Splits**
- 20% of manager–lineage components are hashed into the locked reserve
  (`sha256(componentId|salt)`, the P1 rule).
- Chronological holdout: the last 56 days, with a 7-day purge.
- Training means **collected** by the cutoff. A trade dated before the cutoff
  but collected after it is excluded (pinned by test).
- About 60% of generated trades end up as training data. Requirements are
  given both as training trades and grossed up to total eligible trades.

**Metrics** (all compression-invariant)
- **Pairwise accuracy:** the share of same-tier pairs, whose true values
  differ by at least 20%, that the model orders correctly. Any monotone
  transform leaves it unchanged, and a constant board scores 0.5.
- **Decoy accuracy:** does the real counter-package fit better than random
  size-matched packages, or than a one-asset same-position swap? A constant
  board scores 0.5.
- **Interval coverage:** cluster-robust over components.

## 3. Candidates compared

| Name | What it is |
|---|---|
| `prior_only` | the consensus-free covariate alone: zero trades |
| `naive_sum_l2` | "both sides should add up": raw sums (`q = 1`), squared error, every trade weight 1, format ignored |
| `bt_consolidation` | graph / Bradley–Terry: a 1-for-k means the single beats each of the k; a 1-for-1 is a tie |
| `geom_huber` (E2 primary) | sorted geometric `q = 0.78`, Huber, recency H = 90 d, league cap 25, pair cap 4, format covariates, prior width τ = 2 |
| `geom_huber_unweighted` | the same with no recency weights or caps |
| ablations | `geom_huber_pooled` (no format), `geom_huber_mgr` (+ penalised manager effect) |

## 4. Findings

Reproduce the main grid with:

```
python scripts/chase_trade_market_sim.py power --leagues 20,40,80,160,320 \
  --trades-per-league 10,20,40 --replicates 5 \
  --only prior_only,naive_sum_l2,bt_consolidation,geom_huber,geom_huber_unweighted \
  --target pairwise_accuracy=0.90 --target supported_coverage=0.80 \
  --target appeared_pairwise_accuracy=0.85 --out power.json --markdown power.md
```

That is 15 grid points × 5 replicates, deterministic `hashlib` seeds, about
8 minutes on one core. Replicate noise is visible: some curves are not
monotone. `required_count` therefore demands the target be met at **every
larger grid point** and interpolates log-linearly. It never extrapolates: an
unmet target reads `beyond_grid`.

### 4.1 How many trades each tier needs (the requirement behind the shortfall)

**Joint target:** pairwise accuracy ≥ 0.90 on SUPPORTED assets **and** ≥ 80%
of the tier SUPPORTED. The requirement is whichever of the two needs more.
All figures are for the primary `geom_huber`, by trades per league (tr/lg).
"Domain" counts only trades touching that tier's domain, which is the unit to
compare with a real count such as "trades containing an IDP player".

| Tier | tr/lg 10 | tr/lg 20 | tr/lg 40 | Leagues needed (10 / 20 / 40 tr/lg) |
|---|---|---|---|---|
| Offense T1 (ranks 1–24) | 720 train (1,150 total) | 830 (1,360) | 790 (1,320) | 106 / 66 / 34 |
| Offense T2 (25–60) | 1,000 (1,600) | 1,230 (2,020) | 1,000 (1,670) | 148 / 96 / 42 |
| Offense T3 (61–120) | beyond grid | 1,750 (2,880) | 1,620 (2,700) | — / 142 / 73 |
| Offense T4 (121–160) | beyond grid | 3,240 (5,340) | 3,150 (5,250) | — / 270 / 127 |
| IDP T1 (1–12) | beyond grid | beyond grid | 4,700 (620 IDP-touching) | — / — / 180 |
| IDP T2 (13–36) | beyond grid | beyond grid | 8,030 (1,000 IDP-touching) | — / — / 316 |
| IDP T3 (37+) | beyond grid | beyond grid | beyond grid | — |
| Picks R1 | 930 (410 pick-touching) | 950 (400) | 850 (370) | 137 / 74 / 36 |
| Picks R2 | beyond grid | 1,580 (670) | 2,040 (900) | — / 127 / 90 |
| Picks R3+ | beyond grid | 3,460 (1,500) | 3,670 (1,600) | — / 289 / 143 |

**A looser target** (accuracy ≥ 0.85 on every asset that appeared, no
coverage condition):
- Offense T1: about 400–510 training trades.
- Offense T2: about 775–840.
- Offense T3: about 1,080–1,240.
- Offense T4: about 2,000.
- IDP T1: about 185–220 **IDP-touching** training trades.
- IDP T2: about 390–470 IDP-touching.

**Reading it**
- Leagues and volume trade off. At 10 trades per league the top tier needs
  about 106 leagues; at 40 it needs about 34. **The number of independent
  leagues matters, not only trades.**
- Deeper tiers need far more evidence. Low-value assets are traded less
  often, and their true gaps are smaller.

**IDP, provisionally**
- The on-box run of 2026-10-17 recorded **332 underlying trades with at least
  one IDP player across all lanes**: 313 BROAD_CONTEXT, 19 TARGET_UNSUPPORTED,
  0 NATIVE or VALIDATED (`docs/sources/SIGNALS_FANTASY_INTEGRATION.md`). That
  count is before the maturity filter, dedupe-state exclusions, the reserve
  and the holdout. At the bench's ≈ 0.6 training fraction it is about 200
  training trades.
- **If the real graph resembled this synthetic one,** about 200 IDP-touching
  training trades would sit near the looser IDP T1 requirement (about
  185–220). It would fall below the joint requirement: about 620 at 40 tr/lg,
  and beyond the grid at 10–20 tr/lg (more than the roughly 210–420
  IDP-touching trades the largest of those grid points reached). It would be
  far below anything for IDP T2 or T3.
- That is a planning signal, not a measured shortfall. The real requirement
  comes from the real-topology rerun (§7).

**Offense:** no repo-visible count of eligible mature-league offense trades
exists. That count is UNKNOWN, so the offense shortfall is **UNKNOWN**. The
CLI reports it as `unknown_observed_count`, never 0.

### 4.2 Recency weighting is a trade-off, not a free win

With the declared 90-day half-life:
- At small volumes the recency-weighted fit **loses** to the unweighted one,
  for example 0.72 vs 0.80 appeared accuracy in T1 at 40 leagues × 10 trades.
  Halving old evidence costs more precision than it buys in freshness.
- At large volumes it **wins**: 0.99 vs 0.96 at 80 × 40, and 0.97 vs 0.94 at
  320 × 20.

The crossover depends on how fast values truly drift, which no one knows in
advance. **H must be chosen by inner cross-validation on training data**
(`select_by_inner_cv`), not assumed. The preregistration draft (§4) makes
that binding.

### 4.3 Value *spread* is weakly identified, so only the ranking should vote

- With plenty of data and a perfectly clean world, the fitted log-value spread
  was 0.93× the truth at τ = 5 and 0.74× at τ = 1.
- With realistic noise it was 0.72× and 0.59×. The prior width, not the
  trades, controls how stretched the board is.
- That is expected. Only package trades carry spread information, and only
  through `q`.

Two consequences:
- **Rank-space voting is right.** The plan's rank → percentile → existing Hill
  curve path uses only order, and order is recovered well (T1 appeared
  accuracy 0.91–0.99 at 1,000+ training trades).
- **Cardinal intervals are wrong at the top.** Nominal 90% intervals on
  contrasts cover about 50–75% in T1 at a few hundred trades. Coverage falls
  **toward 0** as data grows (0.02 at 1,940 training trades), because the
  standard error shrinks while the shrinkage bias does not. Mid-tier coverage
  holds up longer, since contrasts near the core mean carry little
  compression bias: T3 was 0.83–1.00 up to about 4,000 training trades, then
  fell to 0.58 at 8,100.
  - **The support gate's interval criterion must move to rank space** before
    it means anything: a cluster bootstrap of ranks, calibrated on this bench.
  - Recorded in the preregistration draft §8 as a P6 requirement.

### 4.4 The aggregator `q` is not identified from accepted trades

Worlds were generated with true `q` ∈ {0.70, 0.78, 0.85, 1.0} and fitted with
`q` ∈ {0.70, 0.78, 0.85}. The setup was 160 leagues × 20 trades, 3 seeds each.

| True q | Fitted q | T1 accuracy | T2 accuracy | Hard-decoy accuracy | `naive_sum_l2` (T1 / T2) |
|---|---|---|---|---|---|
| 0.70 | 0.70 / 0.78 / 0.85 | 0.99 / 0.99 / 0.99 | 0.94 / 0.94 / 0.94 | 0.773 / 0.776 / 0.777 | 0.96 / 0.86 |
| 0.78 | 0.70 / 0.78 / 0.85 | 0.99 / 0.99 / 0.99 | 0.94 / 0.94 / 0.94 | 0.772 / 0.775 / 0.775 | 0.96 / 0.89 |
| 0.85 | 0.70 / 0.78 / 0.85 | 0.985 / 0.985 / 0.985 | 0.94 / 0.94 / 0.94 | 0.778 / 0.778 / 0.781 | 0.95 / 0.88 |
| 1.0 | 0.70 / 0.78 / 0.85 | 0.98 / 0.98 / 0.98 | 0.96 / 0.96 / 0.96 | 0.790 / 0.790 / 0.789 | 0.97 / 0.92 |

- Ranking is insensitive to `q`, and the held-out decoy metric cannot tell
  the `q` values apart (differences ≤ 0.004).
- This confirms the plan's statement that `q` is prior-only under D8. Any `q`
  profile computed from these trades is not D8 evidence.
- The geometric Huber model with format covariates beats raw summing even
  when raw summing is the true aggregator (`q_true = 1.0`). Its advantage
  comes from robustness and format handling, not from `q`.

### 4.5 Manager overlap can collapse "independent leagues" into a few clusters

Leagues that share a manager are one manager–lineage component, which is the
plan's unit for clustering, caps and held-out folds.

| Per-seat overlap | 40 leagues → components (largest) | 160 → | 640 → |
|---|---|---|---|
| 0% | 40 (1) | 160 (1) | 640 (1) |
| 1% | 36 (2) | 146 (5) | 565 (6) |
| 2% | 34 (2) | 130 (7) | 497 (9) |
| 5% | 25 (7) | 80 (25) | 308 (166) |
| 10% | 10 (29) | 25 (130) | 86 (533) |
| 15% | 2 (39) | 5 (156) | 25 (616) |

With 12 seats per league, a modest per-seat overlap makes a giant component.
The sharp graph is built by snowball discovery through shared managers, so
high overlap is plausible.

When that happens:
- cluster-robust intervals have few clusters;
- the 20% reserve can be one or two components;
- "≥ 3 components" support becomes unreachable, however many trades exist.

**The P1 census must measure real component sizes before the reserve share
and the support thresholds are fixed.** This may be the binding constraint,
ahead of trade volume.

### 4.6 "Does league age improve the signal?": power of the test

- **Test:** one-sided Mann–Whitney on per-league mean |held-out residual|,
  cohort A (≥ 3 completed seasons) vs younger leagues.
- **Declared effect:** clearing noise × `exp(−0.3 · (seasons − 3))`. A
  one-season league is 1.8× noisier than a three-season league, and a
  six-season league 0.4×.
- **Measured power at α = 0.05 (20 trades per league, 5 replicates):**
  - 0.0 at 40 leagues;
  - 0.0 at 80;
  - 0.8 at 160;
  - 0.6 at 320.
- **Under the null (no effect),** the 3-replicate exploratory grid showed
  rejections in only a few of its 60 cell × estimator combinations (1–2 of
  3), consistent with multiple comparisons. A 10-replicate recheck of the
  worst cell (320 leagues × 10 trades) gave 0 of 10.
- **Both readings:** the bench reports the test under the league-level and
  the point-in-time reading (`maturity_signal` / `maturity_signal_point_in_time`).
  On the synthetic chronological holdout they coincide, because every holdout
  trade falls after the last season boundary; on real multi-season data they
  can differ.
- **Conclusion:** the age question is answerable only with about 160+
  leagues. Below that, a null result means **underpowered**, never "age does
  not matter".

### 4.7 Prior influence: the full row is not a bounded share

- The plan's full-row prior influence `τ⁻² Σ_b |[C H⁻¹ Cᵀ]_ab|`, taken in
  contrast space, had a median of about 1.2 and a 90th percentile of about
  3.7 for traded assets in a default world. Neighbouring posteriors are
  positively correlated, so the row is not a 0–1 share, and a "≤ 0.5"
  threshold on it would reject most assets.
- The bench gates on the diagonal share `τ⁻²[C H⁻¹ Cᵀ]_aa` (median 0.20 for
  traded assets) and reports the row beside it. The diagonal is about 1 with
  no evidence, slightly above (1.1–1.25), because a contrast also carries the
  core-mean and group-mean uncertainty. It falls toward 0 as evidence grows.
- In raw (non-contrast) space the row is dominated by the common location,
  which no trade can inform. That is why contrast space is used.

## 5. Synthetic worked examples (shape of the five real anonymized examples)

`python scripts/chase_trade_market_sim.py examples --seed 5`.

**How influence is measured.** For each best-supported asset, the trades that
moved its estimate most are measured by a one-step leave-one-out influence
`−[C H⁻¹ g_t]_a`. A test checks the sign and rough size against an actual
refit without that trade.

| Asset | Estimate vs core | Evidence | Most influential trades |
|---|---|---|---|
| `syn-asset-o0001` (WR) | +136% | 31.4 info-weighted appearances, 42 components, SE 0.08 | a **3-for-1** where three good players went for him (**+1.4%**); a **2-for-1** against the #1 asset plus a pick (**+1.4%**); a **1-for-1** for the #3 asset (**−1.2%**) |
| `syn-asset-p0024` (pick) | +140% | 18.1, 33 components | 3-for-1 bought with three players (**+1.6%**); a 2-for-2 and a 3-for-2 that set it level with cheaper pieces (**−1.1%**, **−1.0%**) |
| `syn-asset-d0001` (LB) | +68% | 4.4, 8 components, SE 0.29 | a 2-for-1 against two offense players in an IDP league (**+5.0%**); a 1-for-1 with a top LB (**−2.4%**) |
| `syn-asset-o0000` (WR) | +150% | 28.7, 39 components | a 1-for-1 with the #4 asset (**−1.3%**); 2-for-1 and 3-for-1 consolidations (**+1.3%**, **+1.2%**) |
| `syn-asset-o0003` (RB) | +108% | 24.9, 37 components | 1-for-1s level with nearby assets (**−1.3%**, **+1.1%**); a 3-for-1 with a pick (**+0.7%**) |

**The pattern a non-statistician should take away**
- Being bought with *several* good pieces pushes a player up.
- Being swapped one-for-one with a slightly cheaper player pulls him toward
  that player.
- A thinly traded player (the LB: 8 components) moves several percent per
  trade, while a heavily traded one moves about 1%. That is exactly what the
  uncertainty band reports.

## 6. Running it

- **CI and local, synthetic only:** `python scripts/chase_trade_market_sim.py
  {scenario,power,examples,components}`. The script pins BLAS to one thread
  (`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`). Multi-threaded BLAS on these
  small matrices measured about 40× slower on a 4-core runner. The production
  unit pins one thread too (plan §7).
- **Inner-CV demo:** `scenario --inner-cv` adds a `geom_huber_innercv`
  estimator, with the half-life chosen on training data by hard-decoy
  accuracy.
- **Shortfall:** `power … --observed-train-trades N` turns each requirement
  into `max(0, required − N)`. Without N the state is
  `unknown_observed_count`.

## 7. On-box real-topology run (P6 owns it; not run here, so no on-box result is claimed)

**Prerequisites**
- P2 evidence fields: sender attribution, `collectedAt`, side keys.
- The P1 census.

**Steps**
1. **Read-only, as the service user:** produce **aggregates only** from the
   ledger and census:
   - topology mix;
   - trades-per-league distribution (lognormal σ fit);
   - per-seat manager overlap, or the component-size distribution;
   - maturity distribution (both readings);
   - format-stratum shares;
   - IDP-league share;
   - collection-latency quantiles.
2. **Write them as SimConfig overrides** into a 0600 box file, e.g.
   `real_topology.json` with keys `topology`, `activity_sigma`,
   `manager_multi_league_prob`, `maturity_probs`, `one_qb_share`, `tep_share`,
   `idp_league_share`, `latency_mean_days`, `backfill_share`. The loader
   refuses unknown keys and any 15+-digit number.
3. **Run the grid around the observed size:**

   ```
   OMP_NUM_THREADS=1 python scripts/chase_trade_market_sim.py power \
     --config-json real_topology.json --leagues <grid around observed> \
     --trades-per-league <observed median, ×0.5, ×2> --replicates 10 \
     --target pairwise_accuracy=<frozen> --target supported_coverage=<frozen> \
     --observed-train-trades <eligible A-cohort training trades> \
     --out <0600 box path>.json --markdown <0600 box path>.md 2>/dev/null
   ```

4. **Review before committing.** A human reviews the markdown, which holds
   aggregates only, and commits it if wanted. No workflow auto-commits, and
   stderr is never sent to a public log (plan §1.6).
5. **Freeze.** Only after this run are the preregistration placeholders fixed
   and the file frozen.

**Later step (P6):** feed the *real* trade graph's exact asset/trade
structure, rather than aggregates, into a semi-synthetic run: real topology,
synthetic true values. That needs P2's fields and a box-local loader, and is
out of scope here.

## 8. Limitations

- The generator's latent truth is a single market value per asset. Real
  managers' valuations are heterogeneous beyond the manager effect modelled
  here.
- Assets are traded by popularity ∝ value^0.6. The real selection into trades
  is unknown and affects deep-tier coverage most.
- The counter-side construction is greedy. Real negotiation produces
  different package shapes for the same clearing price.
- FAAB inside trades, KTC-lane overlap, dedupe states, pick origin and
  draft-slot information are not simulated. Those are covered by the real
  ledger's exclusions (plan §3), not by this bench.
- Replicates are 5 per grid point. Requirement estimates carry visible noise,
  so treat them as ±25%.
- "Accuracy" here is agreement with a known truth. On real data the truth is
  unknown, and the validation endpoints are held-out decoy, X3 and X4 (plan
  §5).

## Result

- **STATUS:** DONE for the P6a unit.
  - Synthetic generator, bench, power study, preregistration draft and this
    explanation.
  - No real data was used and no on-box result is claimed.
- **UNRESOLVED:**
  - The real-topology rerun (§7, P6).
  - The real observed counts, so every real shortfall stays UNKNOWN.
  - The rank-space interval criterion (§4.3).
  - Component sizes (§4.5).
  - Every preregistration placeholder.
