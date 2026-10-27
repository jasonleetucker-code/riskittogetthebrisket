# IDP market hypotheses H1–H7: preregistration — DRAFT, NOT FROZEN (IDPM-4, 2026-10-27)

**Status: DRAFT.** Nothing in this file binds an analysis yet. Every value marked `⟨DRAFT⟩` is a proposed value the
owner must confirm or change, and every `⟨OWNER⟩` item is an open owner decision (§13). The file is frozen only by
the procedure in §12. **Until it is frozen, every hypothesis status is `unavailable: preregistration_not_frozen`**,
whatever any data would say. That is the anti-adaptive rule of `src/league_valuation/preregistration.py`: a threshold
chosen after seeing the data is not a threshold.

- **Owner directive:** `docs/owner/IDP_MARKET_ACQUISITION_DIRECTIVE_2026-10-26.md`, §4 (hypotheses H1–H7 and their
  statistical requirements), §11 (backtest safeguards) and §16 (validation and release conditions).
- **Authorization:** `docs/EXECUTION_PLAN.md`, 2026-10-26 entry, Phase 2: "preregistered market-hypothesis research
  (H1–H7)". Research only.
- **Product authority:** none. This file fits nothing, votes nothing and changes no served value, vote, weight,
  anchor, package model, fairness band, verdict or flag. Every §15 item of the directive stays owner-reserved. Every
  artifact this plan could ever produce carries `promotes: false`.
- **Relation to `chaseTradeMarket`:** a separate, complementary preregistration (§11). It does not edit, contradict
  or consume `docs/market_trades/CHASE_TRADE_MARKET_PREREGISTRATION.md`.

Agent-OS-Receipt: 47a8b19fff9d06da9b1a651aab5fb92f1e16d5f6

---

## 0. Pins and disclosure

### 0.1 Records this draft is written against (main at `44695ab61270fc6124c62190f895ec8171b0e239`)

| item | blob |
|---|---|
| owner directive | `7d7066b6c8074bea1eb82a903640389f7b97df80` |
| own-league census (markdown) | `d5df30d8c7623ee0421bb1ab3ffa19a34b99f461` |
| own-league census (JSON evidence) | `31bdb7551389ad11ae0a7d9ab3953800ee9efc8f` |
| census script `scripts/own_league_history_census.py` | `ef57ad4e67829e6c4308d12dd6b516c1daaae724` |
| historical price archive survey | `b4c856c6947b998cc89bcceea0a10b1305d7d5ac` |
| `chaseTradeMarket` preregistration (DRAFT) | `104b9d8388aee50a7e5da877bb747c1ab05a7d90` |
| `chaseTradeMarket` power study | `6aeac523b5e6552813e210196af4a9fb2a2630af` |
| `config/trade/package_model.json` (`geom_q078_v1`) | `897982b0575c0bd0404b96f32488ad937a5c4628` |
| `config/trade/fairness_bands.json` (`fairness_bands_v2`) | `86d0ab4aef532c6e0bc82f76b7ccdac01d69dc33` |
| `src/history/asof.py` | `5cc8cabc112e7545c6f7a629e638b17a832a5f8b` |
| `src/trade/market_trade_eval.py` (`fit_suitability`) | `0beeb14038f7dd38da1c05726ccd3e6b45cd7a39` |
| `src/trade/market_trade_format.py` (`compare_formats`) | `ea24c202ac3da5d3d67507880745a28d3e9282d3` |

The freeze (§12) re-pins every row against the main SHA it is written on.

### 0.2 What the author saw (disclosure, not a claim of blindness)

Read: the directive; the census markdown and its JSON (aggregate counts only); the archive survey; the
`chaseTradeMarket` preregistration and power study; `docs/valuation/idp_accuracy/G_PREREGISTRATION.md`;
`src/league_valuation/preregistration.py`; the freeze check in `scripts/idp_accuracy/backtest.py`.

**Not opened:** the private transaction-level evidence under `data/research/own_league_census/`, any temporal ledger,
any price of any traded asset, and any residual, gap or premium. The author knows how many trades exist and how many
are priced. The author does not know what any of them says about H1–H6.

Every number in §3–§9 is one of: a census count; arithmetic on census counts, shown; a decision-relevance argument; or
a planning calculation with its formula and assumptions shown (§4, Appendix A). No constant is fitted.

---

## 1. Questions

| id | directive wording (§4) | operational question in this file |
|---|---|---|
| H1 | IDPTC approximates the league's actual market prices | Does IDPTC order this league's accepted trades better than chance, **and** show no material systematic IDP bias? |
| H2 | Canonical values approximate actual transaction behavior more closely | On the same accepted trades, do canonical values make them look more balanced than IDPTC does? |
| H3 | The league has position-specific premiums | In IDPTC value, do buyers of IDP players systematically pay more (or less) than the IDP side is worth? |
| H4 | The league has tier-specific premiums, especially for elite IDPs | Is that premium materially larger for elite IDP than for non-elite IDP? |
| H5 | Some managers have different pricing preferences | Is there a material between-manager component in trade residuals? |
| H6 | The apparent discrepancy is explained by package effects, picks, source staleness or player selection | When a discrepancy is established, does any of four named explanations remove it? |
| H7 | The sample is insufficient to distinguish these explanations | The **default** outcome whenever a minimum sample (§4) is not met |

Completed trades are constraints and revealed preferences, not reservation prices (directive §4). No test here
assumes a completed trade was fair, and no trade is dropped because it disagrees with any source.

---

## 2. Population, sample definition and exclusions

### 2.1 Population

Every completed own-league trade of `dynasty_main`'s verified `previous_league_id` chain, exactly as the census
defines it: `type == trade`, `status == complete`, unique by `transaction_id` across weeks and seasons (all 233 are
`CONFIRMED_UNIQUE`). The trade instant is Sleeper's completion time (`status_updated`; `created` when absent), as in
the census. Nothing from outside the league enters any test (§11).

### 2.2 Format rule: format-matched seasons only

The **reference format** is `dynasty_main`'s 2026 format, as captured at the freeze. A season is format-matched only if
`market_trade_format.compare_formats` finds no differing and no unknown axis.

| season | census verdict | rule |
|---|---|---|
| 2024 | 9 axes differ (teams 10 vs 12, IDP starters DL 1 / LB 1 / DB 1 / IDP_FLEX 1 vs 3/3/3, roster 36 vs 58, scoring, TE demand, …) | **excluded** from every confirmatory test |
| 2025 | 9 axes differ (teams 10 vs 12, IDP starters 2/2/2 vs 3/3/3, roster 55 vs 58, scoring, …) | **excluded** from every confirmatory test |
| 2026 | no axis differs | included |

Why exclusion, not pooling with a format covariate: the hypotheses are about prices in *this* league's market. A
change from 6 to 9 IDP starters and from 10 to 12 teams changes IDP scarcity, which is the very quantity H3 and H4
measure. A covariate fitted on two other formats would decide the answer.

The rule is binding even though it currently costs nothing: no 2024 or 2025 trade has a point-in-time price in any
lane, under either regime (§3). It decides what happens if a future approved source prices them. Pooling is
`⟨OWNER⟩` decision O3; if the owner chooses it, 2024/2025 enter only a separately reported, format-stratified
exploratory arm, never a confirmatory family.

**Within 2026.** The census compares current settings, so a mid-season change is not ruled out. At the freeze run, each
2026 trade's format must be bracket-confirmed by `src/trade/own_league_format_capture.py` (a season capture at or
before the trade and a later observation with the same payload hash). An unconfirmed trade goes to a sensitivity arm,
not the primary sample.

### 2.3 Structural exclusions (counts from the census, all seasons)

| exclusion | census count | rule |
|---|---:|---|
| three or more teams | 11 | excluded from every confirmatory test (no two-sided reading; a per-team N-team reading is a later amendment) |
| includes FAAB | 8 | excluded |
| includes an unresolved player id | 2 | excluded |
| includes a pick beyond round 6 | 7 | excluded |
| includes a startup-draft pick | 2 trades | excluded |
| one side empty | 1 | excluded |
| includes any league pick | 145 | **excluded by default** until the pick-pricing rule (O4) is decided |
| any asset not priced in the test's lane at the trade instant | per lane (§3) | excluded from that lane's test |

Not an exclusion: a lopsided, collusive-looking, rebuild or contender trade. Robust estimators (§5) bound one
trade's influence instead.

### 2.4 Pricing rule (point in time)

- Every price comes from `src.history.asof.batch_known_before`, knowledge cutoff = the trade instant, strict. A later
  observation is never selectable. Today's value is never used. Missing is never 0.
- **Fidelity.** `exact` or `nearest-prior` with ledger observation age ≤ `⟨DRAFT: 7⟩` days. Older → missing for that
  test.
- **One lane per statistic.** Every asset in one trade's statistic is priced by the same source, from the same
  snapshot date (§2.5).
- **As-of position.** The census basis: chain draft metadata, else the current Sleeper directory (97 player legs). A
  sensitivity arm drops trades with any `current_sleeper_directory` leg.
- **Regime B observations** (§3.2) carry a separate fidelity label, `nearest_prior_content_unverified`. Git history
  records only the days a vendor file changed, so "unchanged on day *d*" is inferred, not observed.

### 2.5 Evidence-lineage rule (no double counting)

| lane | what it may be used for | lineage facts that bind |
|---|---|---|
| **IDPTC** (`idpTradeCalc`) | the primary lane for every IDP test (H1, H3, H4, H5, H6) | A full-roster calculator: offense, IDP and picks on one 0–9,999 scale, so a whole offense-for-IDP trade is priced in one lane. It republishes rarely (6 content changes in 165 post-floor archives, per `CLAUDE.md`) |
| **canonical** (`rankDerivedValue`) | H2 and H6d only | **IDPTC is one of canonical's voters** (and one of the two pick markets). KTC Crowd and KTC Trades are two more. So canonical vs IDPTC is a blend against one of its own inputs: their agreement is never independent confirmation, and H2 measures what the rest of the blend adds |
| **KTC** | no IDP test (KTC prices no IDP player). Offense-only diagnostics, if any, use KTC Market where it was captured (from 2026-09-08) and otherwise the Crowd-only stand-in named by `KTC_HISTORICAL_MARKET_KEYS`, labelled as such | KTC Crowd, KTC Trades and KTC Market are one provider: never three confirmations. **KTC Trades is built from KTC's trade database, which may contain this league's own trades if a manager synced the league (UNKNOWN; the `chaseTradeMarket` plan's X9 overlap check is the analogue).** Any lane containing KTC Trades (KTC Trades, KTC Market, canonical) is therefore labelled `possibly_circular` and is never the sole basis of a supported verdict |
| `chaseTradeMarket` | nothing | Non-voting and out of scope (§11) |

Further rules:
- A trade contributes **one** residual per test, however many assets it carries.
- A conclusion reached in two lanes is one conclusion seen twice, not two confirmations.
- No lane's values are mixed with another's inside one trade. KTC offense plus IDPTC defense is forbidden even though
  the two scales are close (median ratio 1.000 on shared rows, per `CLAUDE.md`).
- Agreement between different providers is consensus, not duplication (owner directive 2026-10-19). Nothing here
  haircuts, merges or caps a provider. This file does not vote, so the rule only limits how agreement is described.

---

## 3. The two sample regimes

### 3.1 Regime A: post-floor only (main today)

Point-in-time prices begin at `HISTORY_FLOOR` = 2026-07-14. Every number is a census count. "Fully priced" means every
non-FAAB asset priced in the lane at the trade instant.

| quantity | Regime A |
|---|---:|
| trades on or after the floor (all in the 2026 league) | 43 |
| fully priced, IDPTC / KTC / canonical | 17 / 13 / **0** |
| clean 1-for-1 (any position), eligible / fully IDPTC-priced | 9 / **7** |
| IDP 1-for-1 player swaps with IDPTC on both assets | **0** |
| two-team offense-for-IDP, eligible / fully IDPTC-priced | 5 / **1** |
| two-team trades containing an IDP, eligible / fully IDPTC-priced (before any tier split) | 14 / **4** |
| package trades (`package_va_required`), eligible / fully IDPTC-priced | 30 / **10** |
| managers in fully IDPTC-priced trades | 8 (median 2 trades each; the most active manager is in **>50%** of them) |
| canonical at-trade-time prices | **none locally**. The canonical-board history lives only on the box (`board_history.sqlite` and the box ledger's `canonical_board` lane); the census did not read it (owner: no box run) |

Regime A grows over time. The tracked archive adds one bundle a day, so the post-floor window lengthens. §8 states the
accrual arithmetic.

### 3.2 Regime B: post-floor plus the pre-floor vendor backfill (only if the owner approves D1 and D2)

The archive survey's candidate R1: the repo's own git history of vendor CSVs (from 2026-03-09) and dated
`dynasty_data_*.json` exports (from 2026-03-25), up to 2026-07-13.

**What can be said without ingesting anything.** All of it is arithmetic on census counts. Every 2024 and 2025 asset
is `before_history_boundary`, so all 43 post-floor trades are 2026 trades.

| quantity | derivation from census counts | Regime B adds at most |
|---|---|---:|
| 2026 trades before the floor | 80 − 43 | 37 (from January 2026; how many fall on or after 2026-03-09 is **not reported**) |
| clean 1-for-1 | 2026 one-for-one swaps (14) − post-floor clean 1-for-1 (9) | 5 |
| IDP 1-for-1 player swaps | all-season total (2) − post-floor (0); season not reported, so possibly 0 in 2026 | 2 |
| two-team offense-for-IDP | 2026 offense-for-IDP trades, any team count (7) − post-floor eligible (5) | 2 |
| two-team IDP trades | 2026 IDP trades (19) − post-floor eligible (14) | 5 |
| package trades | 2026 two-team packages (64) − post-floor eligible (30) | 34 |
| managers | the 2026 league has 12 teams; 14 distinct managers across the whole chain | no new managers beyond those bounds |

**What cannot be known without ingestion.**
- How many of those trades fall inside 2026-03-09..07-13 rather than January to early March.
- How many become fully priced. IDPTC has only 19 content-change days in R1, has no pick rows before 2026-04-09, and
  2026's pre-floor window is rookie-draft season, when pick-bearing trades are common (145 of 233 trades carry picks).
- Whether IDPTC's "last change" was still its live board on a given trade day (§2.4 fidelity label).

**What D2 decides.**
- Under D2(a) or D2(c), Regime B adds `source_value` prices only. **H2 and H6d stay unavailable**: the pipeline never
  ran on those dates.
- Under D2(b), canonical prices exist only as a labelled `reconstructed` lane, under the champion-versus-challenger
  gates. Even then H2's verdict must name that comparator as today's methodology on old inputs, not the board managers
  saw.

**Ceiling.** Regime B can at most add the counts above. Under every row of §4, the Regime B ceiling is still below the
minimum sample.

### 3.3 Accrual and the retrospective / prospective split

- Every trade completed **before** the freeze commit is `retrospective_point_in_time`. Its prices were point in time,
  but the author has seen the census counts (§0.2).
- Every trade completed **after** the freeze commit is `prospective`.
- Both enter the primary sample. Each verdict reports its prospective share, and a `prospective_only` sensitivity arm is
  always reported beside it.

---

## 4. Minimum effective sample: method and derivation

**Rule.** For each primary statistic, the minimum effective sample `n_min` is the smallest `n_eff` at which **both** a
`supported` and a `rejected` verdict are attainable with power 0.80 at the strictest Holm step of its family. A test
whose sample is below `n_min` is **not run**. It is reported `unavailable: insufficient_sample`, which is H7 for that
hypothesis.

Why both: a sample that can only ever reach "significant" can never reach "no material premium". Its silence would
look like a negative result.

### 4.1 Common planning inputs (declared, not fitted)

| input | value | source |
|---|---|---|
| confirmatory family size | m = 5 (H1a, H2, H3, H4, H5; §7) | this plan |
| strictest Holm step | α = 0.05 / 5 = 0.01 | Holm |
| detection, two-sided | z₀.₉₉₅ = 2.576; power 0.80, z₀.₈₀ = 0.842 | — |
| equivalence (TOST), one-sided each | z₀.₉₉ = 2.326; power 0.80 for both one-sided tests jointly, z₀.₉₀ = 1.282 | — |
| **materiality of a price premium**, δ_prem | **0.0943 log units** (a 9.9% premium) | `fairness_bands_v2` puts a gap of 9% of the larger package utility at the "unfair" cut. For a buyer who gives U_G for U_R, relativePct = 1 − U_R/U_G, so 9% ⇔ log(U_G/U_R) = −log(0.91) = 0.0943. A smaller unrecognized premium leaves a market-clearing trade at "fair" or "slight". From 9% upward the calculator calls it unfair, which is exactly the directive's §2 practical problem |
| planning SD of a per-trade log residual, σ | **0.27** (sensitivity 0.15 and 0.40) | The `chaseTradeMarket` power study's *declared* synthetic clearing noise, combined (Appendix A): Student-t(4) scale 0.12 → SD 0.170; manager effect SD 0.05; 3% gross trades of ±0.8–1.6 log. Total √0.0752 = 0.274. It is a planning assumption about the market, not a measurement of this league |
| estimator efficiency | Hodges–Lehmann pseudo-median: n × π/3 (ARE 3/π = 0.955 vs the mean under normality) | standard |

The formulas, with every result reproducible from Appendix A:

```
n_detect = ((z_{1-α/2} + z_{0.80}) · σ / δ)²
n_equiv  = ((z_{1-α}   + z_{0.90}) · σ / δ)²
n_min    = ⌈ max(n_detect, n_equiv) × efficiency factor ⌉
```

### 4.2 Results

| statistic | effect / margin | planning dispersion | n_detect | n_equiv | **n_min** |
|---|---|---|---:|---:|---:|
| H1a decoy concordance (§6.1) | mean u ≥ c_min = `⟨DRAFT: 0.70⟩` (vs 0.5) | SD of u under the null, √((K+2)/(12K)) = 0.316 at K = 10 decoys | 29.2 | — | **30 trades** (33 at K = 6; 117 if c_min = 0.60) |
| H2 paired gap difference (§6.2) | standardized d_z = 0.5 (the floor assumes the paired SD is at most twice the margin δ₂) | — | 46.7 | 52.1 | **55 trades** (112 at d_z = 0.35; 22 at 0.8) |
| H3 IDP premium (§6.3) | δ_prem = 0.0943 | σ = 0.27 | 95.7 | 106.7 | **112 trades** (35 at σ = 0.15; 246 at σ = 0.40) |
| H3 per family DL / LB / DB (F3) | δ_prem | σ = 0.27 | — | — | **112 per family** |
| H4 elite minus non-elite (§6.4) | δ_prem, two-sample | σ = 0.27 | 191.4 | 213.4 | **224 per group, 448 total** |
| H5 manager component (§6.5) | ICC ρ = `⟨DRAFT: 0.20⟩` | one-way random-effects F test, G managers × k appearances | — | — | **G = 12 managers × k = 12 appearances each ≈ 72 trades**, optimistic (below) |
| H6 components (§6.6) | inherit H3 | — | — | — | H3's n_min **within each arm** |

**H5 derivation.** Balanced one-way random effects, G groups of k. Under ICC ρ, F ~ (1 + kρ/(1−ρ)) · F(G−1, G(k−1)).
Power is P(F(G−1, G(k−1)) > F_crit / (1 + kρ/(1−ρ))) at α = 0.01. The league has at most 12 current managers (14 across
the chain), so G is fixed and k is the free variable:

| G | ρ = 0.1 | ρ = 0.2 | ρ = 0.3 |
|---:|---|---|---|
| 8 | k = 36 (≈ 144 trades) | k = 17 (≈ 68) | k = 11 (≈ 44) |
| 12 | k = 24 (≈ 144) | k = 12 (≈ 72) | k = 7 (≈ 42) |
| 14 | k = 21 (≈ 147) | k = 10 (≈ 70) | k = 7 (≈ 49) |

"Trades" is G·k/2, since each two-team trade gives two manager appearances. That is **optimistic**: a trade residual
carries the buyer's and the seller's effect with opposite signs, which costs information, and real activity is far from
balanced (one manager is in more than half of the priced trades). At the freeze, the H5 floor is replaced by a
simulation on the measured activity distribution. It reuses `src/trade/market_trade_sim_bench.py` (`geom_huber_mgr`
ablation) and the on-box procedure of the power study's §7, run on aggregates only. Until then the table is a lower
bound, never a sufficiency claim.

### 4.3 Two further floors on every test

- **Managers.** At least G_min = `⟨DRAFT: 10⟩` distinct managers in the test's eligible set. Cluster-robust and
  cluster-bootstrap inference with fewer clusters is known to over-reject (Cameron, Gelbach and Miller, 2008).
  Regime A has 8 managers in its fully IDPTC-priced trades, so **every IDPTC test fails this floor today**, whatever
  its trade count.
- **Leave one manager out (LOMO).** A `supported` or `rejected` verdict must survive recomputation without each manager
  in turn: the point estimate stays on the same side of every bound that decided it. Otherwise the verdict is
  `inconclusive: manager_unstable`.
  - In Regime A the most active manager is in more than half of the 17 fully IDPTC-priced trades. So fewer than 8.5 of
    them involve no single dominant manager: arithmetic on the census bucket.

### 4.4 Effective sample size

`n_eff` is computed over the eligible trades of one test:
- trade weights `w_t = 1`, then capped per unordered manager pair at `⟨DRAFT: 4⟩` trades of total weight per season
  (excess scaled down proportionally, the `chaseTradeMarket` pair-cap idea);
- `n_eff = (Σw)² / Σw²` (Kish).

Counting eligible trades and their managers needs no price residual. It is the only thing done before a test is run
(§12, Stage 1).

---

## 5. Uncertainty method (all tests)

**Unit of analysis: the trade.** Assets inside one trade are dependent by construction. Each trade yields exactly one
residual per test, so trade-level clustering is structural.

**Primary: dyadic (vertex) bootstrap over managers.** Two managers sit on every two-team trade, so trades share
managers in both directions:
- draw B = `⟨DRAFT: 4000⟩` replicate weights, one multinomial draw over managers per replicate;
- each trade is weighted by the product of its two managers' multiplicities (the node-resampling bootstrap for dyadic
  data; Snijders and Borgatti, 1999);
- generator `numpy.random.Generator(PCG64(⟨DRAFT: 20261027⟩))`, one stream, managers in sorted private-id order;
- percentile intervals at the level each gate needs;
- p-values from the bootstrap tails, `(1 + #{Δ*_b on the null side}) / (B + 1)`;
- the smallest attainable two-sided p is 2/4001 ≈ 0.0005, below the strictest Holm step of every family.

**Cross-check: dyadic-robust analytic SE** (Aronow, Samii and Assenova, 2015). Reported beside the bootstrap. If the
two disagree on a verdict, the verdict is `inconclusive: inference_unstable`.

**Exploratory Bayesian arm.** A hierarchical model with buyer and seller manager effects:
- prior half-normal(0, 0.25) on the manager SD and Student-t(4, 0, 0.27) on the residual;
- posterior intervals reported;
- never gating, never published per manager (§6.5).

**Point estimators.**
- Location: Hodges–Lehmann pseudo-median.
- Package residuals: Huber, k = 1.345 on a MAD scale, matching the `chaseTradeMarket` E2 loss.

---

## 6. Hypotheses

**Status vocabulary** (directive §4): `supported`, `rejected`, `inconclusive`, `unavailable:<reason>`.
`unavailable: insufficient_sample` is H7 for that hypothesis. "Significant" always means the Holm-adjusted test of its
family (§7). "Equivalent" means TOST at the same Holm-adjusted α: the (1 − 2α_j) interval lies inside (−margin, +margin).

**Package benchmark.** Package values use `geom_q078_v1` (sorted utility U = Σ q^(i−1) v_i, q = 0.78) as a declared
**benchmark**, never as the true clearing rule (directive §4). The power study showed q is not identified from accepted
trades (its §4.4), so nothing here estimates q. Sensitivity to it is H6a.

### 6.1 H1: IDPTC approximates the league's market

**Estimand and measurement.** H1 has two components and is decided by both.

*H1a, information.* For each eligible clean 1-for-1 trade t (assets a ↔ b, any positions, IDPTC prices both at t):
- `g_t = |p(a) − p(b)|`, where p is the percentile on IDPTC's board at t. The board is restricted to the common
  population of assets IDPTC prices at t.
- **Decoys:** the counter-assets b′ of the other eligible 1-for-1 trades completed within ±`⟨DRAFT: 90⟩` days, each
  priced by IDPTC at t. If fewer than K = `⟨DRAFT: 10⟩` exist, the trade is ineligible.
- `u_t` = share of decoys with `|p(a) − p(b′)| > g_t`, ties counted ½.
- Statistic: mean u. Under an uninformative board the real pairing is exchangeable with the decoy pairings, so
  E[u] = 0.5.
- Percentile rank is invariant to monotone transforms, so a compressed board gains nothing. A constant board scores
  exactly 0.5. This is the `chaseTradeMarket` decoy argument.

*H1b, no material bias.* This is H3's equivalence result (§6.3): no material IDP premium relative to IDPTC.

**Sample.** Format-matched, structurally clean two-team 1-for-1 trades fully priced by IDPTC (§2). The IDP-involving
subset is reported as a descriptive stratum only. There are 0 such trades in Regime A and at most 2 in Regime B.

**Gate.**

| status | condition |
|---|---|
| supported | H1a: mean u significantly > 0.5 **and** point ≥ c_min = `⟨DRAFT: 0.70⟩`; **and** H1b: H3 `rejected` (equivalent within ±δ_prem) |
| rejected | H3 `supported` (a material premium relative to IDPTC exists), **or** H1a equivalent to 0.5 within ±`⟨DRAFT: 0.10⟩` (IDPTC carries no detectable ordering information) |
| inconclusive | both components evaluable, neither row above |
| unavailable | H1a below n_min (30) or H3 below n_min (112), or a floor of §4.3 fails |

Why c_min = 0.70: about 70% of the way from an uninformative board (0.5) to the hard-decoy accuracy of about
0.77–0.79 that a correctly specified fitted model reached in the synthetic world (power study §4.4). A source that clears it carries a
meaningful share of the achievable ordering information. The value is a convention, to be confirmed (O5).

**Can conclude.** Whether IDPTC's ordering and level are consistent with this league's accepted trades in 2026, at the
stated margins.

**Cannot conclude.**
- Whether managers *use* IDPTC: correlation with a calculator is not use of it.
- Anything about other leagues (§10).
- Anything about IDP 1-for-1 swaps specifically: there are none.
- That IDPTC is *correct* dynasty value: a market can be consistently wrong.

### 6.2 H2: canonical tracks accepted trades more closely than IDPTC

**Estimand and measurement.**
- Same trades as H1a, restricted to those canonical **and** IDPTC both price at t.
- Percentiles are recomputed within the assets **both** price at t, so the two sources rank the same population.
- `D_t = g_t^canon − g_t^IDPTC`. Statistic: HL pseudo-median of D.
- Negative means canonical makes the accepted trades look closer to balanced.
- Secondary, exploratory: the same paired comparison on package trades, using each source's benchmark residual in its
  own log-value space, standardized by that source's cross-sectional SD over the common population.

**Lineage.** Canonical contains IDPTC (and possibly-circular KTC Trades, §2.5). H2 therefore asks what canonical's
other inputs and methodology add or subtract relative to one of its own inputs. It is not a contest between
independent opinions.

**Gate.** Margin δ₂ = `⟨DRAFT: 0.02⟩` percentile units. That is a convention: two percentile points of the common board,
the same "2 per 100" unit the IDP accuracy Lane G preregistration uses for its cross-position concordance.

| status | condition |
|---|---|
| supported | median D significantly < 0 and point ≤ −δ₂ |
| rejected | median D significantly > 0 and point ≥ +δ₂ (IDPTC closer), **or** equivalent within ±δ₂ (neither closer) |
| inconclusive | evaluable, neither row above |
| unavailable | no canonical at-trade-time lane (**Regime A as on main; Regime B under D2(a) or D2(c)**), or below n_min (55), or a §4.3 floor fails |

**Can conclude.** Which of the two boards, as served at the time, made this league's accepted trades look more
balanced.

**Cannot conclude.**
- That canonical is the better *dynasty value*. Accepted trades are not ground truth, and directive §16 forbids treating
  in-sample alignment with market sources as accuracy.
- Anything if canonical came from a `reconstructed` lane, beyond that lane's own label.

### 6.3 H3: position-specific premium

**Estimand and measurement.**
- Eligible two-team trades in which one side receives **only IDP players** and the other **only offense players**
  ("pure cross-family"), fully priced by IDPTC.
- Orient each trade from the IDP buyer: `r_t = log( U(offense given) / U(IDP received) )`, with U the `geom_q078_v1`
  package utility in IDPTC value.
- θ₃ = HL pseudo-median of r.
- θ₃ > 0: the league pays more for IDP than IDPTC says they are worth. θ₃ < 0: less.
- Mixed trades, with IDP and offense on the same side, are reported descriptively only.

**Gate.**

| status | condition |
|---|---|
| supported | θ₃ significant and \|θ₃\| ≥ δ_prem = 0.0943 (direction reported) |
| rejected | equivalent within ±δ_prem |
| inconclusive | evaluable, neither row above, including significant but below δ_prem |
| unavailable | below n_min (112), or a §4.3 floor fails |

**Per family (F3, descriptive with Holm).** DL, LB and DB separately, each with an n_min of 112. A family-level
statement is allowed only where F3 rejects.

**Can conclude.** Whether this league systematically prices IDP above or below IDPTC on pure cross-family trades in
2026, at the 9.9% margin.

**Cannot conclude.**
- Whether the premium is "justified": that is roster utility, Phase 3.
- That canonical should move: §15 is owner-reserved.
- Anything about premiums smaller than δ_prem.

### 6.4 H4: tier-specific premium, especially elite IDP

**Tier definition, fixed before data.**
- Elite = within-family rank ≤ 12 at the trade instant. Twelve is the team count: one per team, the same convention as
  Lane G §7.3.
- **The rank is NOT taken from IDPTC.** Ranking by the source being tested selects on that source's own error.
  Players IDPTC ranks elite are disproportionately ones it overrates, which manufactures an "elite discount" by
  regression to the mean.
- Primary basis: the previous completed season's league-scored points per game within family, scored with the 2026
  card from point-in-time stats. Rookies have no prior season and are excluded from H4.
- The basis is `⟨OWNER⟩` decision O6; IDPTC rank is a labelled sensitivity arm.

**Estimand.** θ₄ = θ₃(trades whose IDP side contains an elite player) − θ₃(trades whose IDP side contains none). Two
independent groups.

**Gate.**

| status | condition |
|---|---|
| supported | θ₄ significant and \|θ₄\| ≥ δ_prem |
| rejected | equivalent within ±δ_prem |
| inconclusive | evaluable, neither row above |
| unavailable | either group below 224, or a §4.3 floor fails |

**Can conclude.** Whether the IDP premium differs materially between elite and non-elite defenders in this league.

**Cannot conclude.** Anything about an elite *level* by itself: that is H3 restricted to elite, which is descriptive.
Nothing about rookies.

### 6.5 H5: manager heterogeneity

**Estimand and measurement.**
- On H3's residuals: r_t = θ₃ + γ_buyer − γ_seller + ε_t.
- τ = SD of γ over managers.
- **Materiality.** τ_min = δ_prem · √π / 2 = **0.0836**, so that two random managers' premiums differ in expectation by
  E|γ_i − γ_j| = 2τ/√π ≥ δ_prem.
- **Test.** A permutation test of τ = 0 that permutes manager labels across trades within season, preserving each
  trade's two-manager structure; B = `⟨DRAFT: 4000⟩`.
- **Interval.** The dyadic bootstrap of τ̂ (§5).

**Gate.**

| status | condition |
|---|---|
| supported | permutation test significant and τ̂ ≥ τ_min |
| rejected | upper (1 − 2α_j) bound of τ < τ_min |
| inconclusive | evaluable, neither row above |
| unavailable | below the H5 floor (G ≥ 8 managers with ≥ k appearances each, §4.2; replaced by a simulation at the freeze), or a §4.3 floor fails |

**Privacy (binding regardless of n).**
- Only τ̂, its interval and the status are ever committed.
- No per-manager coefficient, rank, label or ordering is published, as the directive says ("do not publish precise
  owner-specific pricing coefficients if the effective sample size is inadequate").
- The census's anonymization rules apply: no team label, no per-team count except quartiles over 8+ teams.

**Can conclude.** Whether this league's managers differ materially in how they price IDP relative to IDPTC.

**Cannot conclude.** Which manager does what, ever, under this preregistration. Whether a difference is a stable
preference or one season's roster needs.

### 6.6 H6: explanations of an apparent discrepancy

**Applicability.** H6 applies only once a discrepancy is established: H3 `supported`, or H2 `rejected` in IDPTC's
favour with a material gap. Otherwise H6 is `unavailable: no_established_discrepancy`. An unestablished discrepancy
cannot be "explained".

**Components (family F2, Holm over the evaluable ones).** Each recomputes the discrepancy's primary statistic.

| id | explanation | arm | "explains" if |
|---|---|---|---|
| H6a | package effects | recompute H3 under the aggregator matrix {geom q = 0.70, 0.78, 0.85, raw sum q = 1.0, KTC rollback `ktc_2026_04`}, as in the `chaseTradeMarket` plan §4 | material under 0.78 but equivalent within ±δ_prem under at least one other aggregator → `packageModelSensitive`. This is a sensitivity, not an estimate of q |
| H6b | draft picks | pick-free vs pick-bearing trades, two-sample | the premium is material only in the pick-bearing group. **Needs the pick-pricing rule (O4)**; under the default exclusion H6b is `unavailable: picks_unpriced` |
| H6c | source staleness | restricted to trades where IDPTC's last content change is ≤ `⟨DRAFT: 30⟩` days before the trade, vs older | material only in the stale group |
| H6d | player selection | canonical/IDPTC log ratio on the IDP players actually traded vs every untraded IDP player of the same family and tier on the same dates | the traded set's ratio differs from the untraded set's by ≥ δ_prem in the direction of the discrepancy. **Needs the canonical lane**, so unavailable in Regime A as on main |

**Gate.**

| status | condition |
|---|---|
| supported | at least one component explains (each named) |
| rejected | every component evaluable, none explains, and the discrepancy is still material |
| inconclusive | otherwise |
| unavailable | no established discrepancy, or every component unavailable |

Each arm must itself meet H3's n_min **within each group it compares**.

**Can conclude.** Whether a named mechanism is sufficient to remove an established discrepancy in this sample.

**Cannot conclude.** That an unexplained discrepancy is a "real" premium. Unlisted mechanisms such as roster needs,
contention timing and collusion are not tested.

### 6.7 H7: insufficient sample (the default)

- **Per hypothesis.** H7(Hk) holds whenever Hk is `unavailable: insufficient_sample` or fails a §4.3 floor.
- **Global.**
  - `supported` when every one of H1–H6 is unavailable or inconclusive. Then nothing distinguishes them, which is
    exactly the directive's wording.
  - `rejected` only when every one of H1–H6 reaches `supported` or `rejected`.
  - Otherwise H7 is reported as the list of hypotheses it holds for.
- **Underpowered is not a negative.** An H7 outcome is never reported as "no premium", "IDPTC is right" or "canonical
  is right". It says the league has not traded enough priced IDP for the question to be answered.

---

## 7. Multiple testing

| family | hypotheses | max m | role |
|---|---|---:|---|
| **F1** (confirmatory) | H1a, H2, H3, H4, H5 primary tests | 5 | decides statuses. H1 is composed from H1a and H3; it adds no test |
| **F2** | H6a–H6d | 4 | decides H6 |
| **F3** | H3 per family DL / LB / DB | 3 | descriptive; per-family statements only where it rejects |

- **Holm**, familywise α = 0.05, separately per family, on the bootstrap p-values (§5).
- **TOST** equivalence uses the same Holm-adjusted α_j.
- Each family's evaluable set and size **m are fixed by counts alone** in Stage 1 (§12), before any residual exists.
  §4 sizes every floor at the strictest step, m = 5 for F1, so a smaller evaluable family only makes the floor
  conservative.
- Sensitivity arms (§2, §3.3, §9) and the Bayesian arm are outside every family. They are reported, never gating.
- **One look per hypothesis.** Each hypothesis is evaluated once: at the first scheduled look (§12.3) at which its
  count-only floor is met. Because only counts decide when a test runs, the sequential schedule spends no α.

---

## 8. Regime A status, and accrual arithmetic

| hypothesis | n_min | Regime A available | Regime A + a pick rule (upper bound: eligible post-floor) | Regime B ceiling (adds §3.2) | likely status under Regime A |
|---|---|---:|---:|---:|---|
| H1a | 30 trades (K ≥ 10 decoys) | 7 (and K ≤ 6) | 9 | ≤ 12 priced / ≤ 14 eligible | **H7** (`insufficient_sample`) |
| H1 | H1a and H3 | — | — | — | **H7** |
| H2 | 55 trades + canonical lane | 0 (no canonical lane) | 0 | 0 under D2(a)/(c) | **unavailable: no_canonical_lane**, and H7 even with it (≤ 9) |
| H3 | 112 trades | 1 | 5 | ≤ 3 priced / ≤ 7 eligible | **H7** |
| H4 | 224 per group | ≤ 4 before the tier split | ≤ 14 | ≤ 9 priced / ≤ 19 eligible | **H7** |
| H5 | G ≥ 8 with k ≈ 12+; G_min 10 | 8 managers, median 2 trades | — | ≤ 12 current managers | **H7** |
| H6 | needs an established discrepancy | — | — | — | **unavailable: no_established_discrepancy** |
| H7 (global) | — | — | — | — | **supported** |

Every IDPTC test also fails the G_min = 10 manager floor today (8 managers).

**Accrual arithmetic, not a forecast.**
- **H3 (n_min 112).** The league produced 18 offense-for-IDP trades in the 2025 season (10 teams) and 7 in 2026 so far.
  Even if every future one were two-team, pure cross-family and fully priced (in Regime A only 1 of 5 eligible
  post-floor trades is), that is **about 6 to 16 seasons** of trading.
- **H1a (30).** 25 (2025) and 14 (2026 so far) one-for-one swaps per season: about 1.2 to 2.1 seasons if every one
  were clean and IDPTC-priced (in Regime A, 7 of 9 clean post-floor ones are). The decoy rule binds first: K ≥ 10
  decoys inside ±90 days needs at least 11 clean 1-for-1 trades in one 181-day window, against 9 in the 3.4 post-floor
  months so far.
- **H2 (55).** About 2.2 to 3.9 seasons on the same arithmetic, and only if the canonical lane is readable.
- **IDP 1-for-1 swaps.** 2 in three seasons: this league essentially does not trade defenders one for one.

The honest expectation is that, for this one league, most of H1–H6 remain H7 for years. External validity needs other
leagues (§10).

---

## 9. Sensitivity arms (reported, never gating)

S1 `prospective_only`; S2 exclude trades with any `current_sleeper_directory` position leg; S3 exclude trades whose
2026 format is not bracket-confirmed (§2.2); S4 exact-fidelity prices only; S5 no manager-pair cap; S6 Bayesian arm
(§5); S7 IDPTC-rank tiers for H4 (with the regression-to-the-mean warning); S8 pooled 2024/2025 format-stratified
arm, only if O3 allows it and a future approved source prices them; S9 Regime B observations excluded (if Regime B is
approved).

A primary verdict whose direction reverses under S1, S2, S3 or S4 is reported as `supported_unstable` /
`rejected_unstable`. That is not a supported or rejected outcome.

---

## 10. Holdouts and external validity

**Chronological.**
- The confirmatory reading is the single count-triggered look per hypothesis (§7) over all eligible trades.
- Every verdict also reports the first-half and second-half estimates, split at the median completion time of its
  sample, plus S1.
- A sign disagreement between halves makes the verdict `*_unstable`.
- No model is fitted here, so there is no training window to hold out. The holdout protects the *definitions* from
  being tuned to the data, which is what the freeze and the count-only Stage 1 already do.

**Independent league.**
- **None is available inside this preregistration.** It is own-league only by design (directive §3: the own-league
  census is the evidence base).
- The only independent-league trade evidence in the repo is the Sharp ledger, and its reserve belongs to the
  `chaseTradeMarket` preregistration (§11).
- An independent-league holdout for H1–H6 needs a **separate amendment** that draws IDP leagues matching the reference
  format from the Sharp ledger, through that plan's reserve access ledger and with its consent, never by reading the
  reserve directly.

**Why own-league-only limits external validity.**
- One league: 12 seats (14 managers across the chain), one trade culture, and one claimed calculator habit.
- Even a clean H3 `supported` would describe how *these* managers price IDP against IDPTC in 2026. It would say
  nothing about the dynasty market, or about this league after its membership or format changes.
- Manager effects (H5) and the league effect are not separable with one league.
- These limits are inherent to the question the directive asks ("does IDPTC represent *our* league market"). They are
  stated, not solved.

---

## 11. Relation to the `chaseTradeMarket` preregistration

| | `chaseTradeMarket` (DRAFT) | this file (DRAFT) |
|---|---|---|
| population | the Sharp-graph verified-dynasty trade market across external leagues, all lanes (Sleeper-observed; KTC database kept separate) | `dynasty_main`'s own chain only |
| estimand | `transactionMarketValueGeneric`: a fitted latent clearing value per asset, post-stratified to a reference format | hypothesis statuses: do fixed, already-served external sources (IDPTC, canonical) agree with this league's accepted trades? |
| fits a model | yes (E2) | **no** |
| output | a non-voting rank candidate, still subject to validation and owner approval | Deliverable B verdicts, which inform the IDPM-5 design only |
| reserve | hashed manager–lineage reserve with sub-reserve access ledgers | none; nothing is held out because nothing is fitted |

**Consistent by construction.** This file reuses that plan's choices rather than inventing rival ones:
- `q` pinned to `geom_q078_v1` as a declared benchmark, with the same aggregator matrix;
- compression-invariant decoy concordance instead of residual loss;
- Holm with TOST equivalence margins;
- "underpowered, not no effect";
- UNKNOWN is never 0.

**Disjoint by construction.**
- That plan excludes own-league-member strata from its primary population; it runs them only as a sensitivity arm.
- This file reads only own-league trades from the census owners. It never reads the Sharp ledger, its reserve or its
  access log.
- If that plan's sensitivity arm uses `dynasty_main` trades after this file has produced results, the commit freezing
  that plan must disclose them. The reverse holds too.

**Neither authorizes voting.** Nothing here changes that plan's §10 hold on picks and IDP.

---

## 12. Freeze procedure

### 12.1 Before the freeze

1. The owner records decisions O1–O8 (§13).
2. Every `⟨DRAFT⟩` and `⟨OWNER⟩` value is replaced with its decided value and that value's justification.
3. The H5 floor is replaced by the measured-activity simulation (§4.2), committed as aggregates only.
4. Section 0.1 is re-pinned against the current main SHA.

### 12.2 The freeze commit

- A new file, `docs/market_trades/IDP_MARKET_HYPOTHESES_PREREGISTRATION.md`, is added by a commit **whose only file it
  is**. This DRAFT stays at its path as history.
- A pointer line to the frozen file is added to this DRAFT in a *separate, later* commit, never the freeze commit.
- The frozen file carries the §14 JSON twin with no placeholder left.

### 12.3 Pinning, squash-safe (the #1964 pattern)

The future evaluator (not written here; IDPM-4 Stage 1/2 code, under the research isolation rules) pins three
constants, as `scripts/idp_accuracy/backtest.py` does:

```
PREREG_PATH   = "docs/market_trades/IDP_MARKET_HYPOTHESES_PREREGISTRATION.md"
PREREG_COMMIT = "<the PR-branch commit that added it>"
PREREG_BLOB   = "<git hash-object of the frozen file>"
```

Its check refuses to run unless all three hold:
- (a) `git hash-object PREREG_PATH == PREREG_BLOB`;
- (b) the first commit adding the path (`git log --diff-filter=A`) is `PREREG_COMMIT` **or** the recorded
  `PREREG_SQUASH_COMMIT`;
- (c) no commit after that first commit touches the path.

**Why the blob is the real pin.**
- The blob is content-addressed, so it is identical before and after a squash merge. Only the commit identity changes.
- After the freeze PR merges, `PREREG_SQUASH_COMMIT` is recorded in the evaluator **below its Stage 2 marker**, so the
  Stage 1 code hash is not disturbed. That is exactly the repair #1964 made after #1942 was squash-merged.

**Scheduled looks.** At the freeze, and then on the first day of each calendar quarter, `⟨DRAFT⟩`.

### 12.4 Stage 1 at each look: blind, counts only

1. Compute eligibility, `n_eff`, G, LOMO counts and the evaluable set per family **from counts and pricing coverage
   alone**, the same quantities the census already reports. No residual, gap, percentile difference or premium is
   computed.
2. Write a manifest with:
   - the preregistration and code SHAs;
   - the census script blob;
   - the ledger file hash;
   - the sha256 of each test's sorted eligible-trade-id list (a digest, never the ids);
   - the family sizes;
   - the seeds.
3. The manifest is committed before Stage 2.

### 12.5 Stage 2: once per hypothesis

1. Only hypotheses whose floors were met in that look's manifest are computed, once.
2. Evaluated hypotheses are never recomputed at later looks; later looks report their verdict unchanged.
3. Results commit aggregates only, under the privacy rules of §6.5 and the census.

### 12.6 Amendments, deviations and the unfrozen state

- **Amendment:** any change before a hypothesis's Stage 2. It goes in a dated
  `IDP_MARKET_HYPOTHESES_PREREGISTRATION_AMENDMENT_<n>.md`.
- **Deviation:** any change after that hypothesis's Stage 2. It is reported as a deviation and never presented as the
  plan.
- **Unfrozen state.** Until the freeze, every status is `unavailable: preregistration_not_frozen`. This includes any
  exploratory computation anyone runs, which may not be reported as a verdict.

---

## 13. What the owner must decide before freezing

| id | decision | default if undecided |
|---|---|---|
| **O1 = survey D1** | approve R1 (repo git history of vendor CSVs and dated exports, 2026-03-09..07-13) as a `source_value` backfill, with its observation-time and intraday-version rule | not approved: Regime A only |
| **O2 = survey D2** | how pre-floor trades are graded: (a) unavailable, R1 diagnostics only; (b) a labelled `reconstructed` canonical lane under the challenger gates; (c) per-source comparison, KTC-only figures before 2026-09-08 labelled as the Crowd-only stand-in | (a). H2 and H6d stay unavailable for pre-floor trades |
| **O3** | 2024/2025: excluded (this draft's rule) or pooled in a format-stratified exploratory arm | excluded |
| **O4** | the pick-pricing rule: (i) exclude pick-bearing trades; (ii) the generic grade = unweighted mean of the early/mid/late tier observations known before the trade, the same uniform-tier PRIOR as canonical's `genericGradeModel` (the census counts 29 such 2026 picks); (iii) slot-resolved where the draft order was known at the trade instant | (i) exclude. H6b is unavailable under it |
| **O5** | gate thresholds: δ_prem (9% "unfair" cut = 0.0943, or the 3.5% "slight" cut = 0.0356, which needs (0.0943/0.0356)² ≈ 7× the sample); c_min 0.70; δ₂ 0.02; τ_min 0.0836; power 0.80; α 0.05 per family; G_min 10; observation age 7 days; staleness split 30 days; pair cap 4 | this draft's values are proposals only, not defaults |
| **O6** | H4's tier basis: prior-season league-scored production (this draft) or another non-IDPTC ranking | production basis |
| **O7** | a read-only box run to obtain canonical at-trade-time prices for post-floor trades (`board_history.sqlite` or the box ledger's `canonical_board` lane), aggregates only. The owner said "no box run" for the census, so this is a new decision. Without it H2 and H6d stay unavailable | no box run |
| **O8** | whether retrospective trades (completed before the freeze) may enter the confirmatory reading, or only the S1 prospective arm | both enter, with the prospective share and S1 reported |

Also needed, not owner decisions: the H5 measured-activity simulation (§4.2), and the coordinator's work claim for the
evaluator code.

---

## 14. Machine-readable twin (DRAFT; every `null` is a placeholder)

```json
{
  "preregistration": "idp_market_hypotheses_v1",
  "status": "DRAFT_NOT_FROZEN",
  "league": "dynasty_main",
  "referenceFormat": "dynasty_main 2026 as captured at freeze",
  "seasons": {"confirmatory": [2026], "excluded": [2024, 2025], "poolingDecision": null},
  "tradeInstant": "status_updated (completion); created when absent",
  "pricing": {
    "reader": "src.history.asof.batch_known_before",
    "knowledgeCutoff": "trade instant, strict",
    "maxObservationAgeDays": null,
    "regimeBFidelityLabel": "nearest_prior_content_unverified",
    "missingIsZero": false
  },
  "exclusions": [
    "three_or_more_teams", "includes_faab", "includes_unresolved", "includes_pick_beyond_round_6",
    "includes_startup_pick", "one_side_empty", "includes_league_pick_until_O4", "not_fully_priced_in_lane"
  ],
  "lanes": {
    "primaryIdp": "idpTradeCalc",
    "comparator": "canonical rankDerivedValue (contains idpTradeCalc and KTC Crowd/Trades)",
    "possiblyCircular": ["ktcTrades", "ktcMarket", "canonical"],
    "mixLanesWithinTrade": false
  },
  "packageBenchmark": {"model": "geom_q078_v1", "q": 0.78, "role": "declared benchmark, not identified",
                       "sensitivityMatrix": ["geom_0.70", "geom_0.78", "geom_0.85", "raw_sum_1.0", "ktc_2026_04"]},
  "materiality": {"deltaPremLog": null, "deltaPremProposal": 0.0943, "cMin": null, "cMinProposal": 0.70,
                  "delta2Pct": null, "delta2Proposal": 0.02, "tauMin": null, "tauMinProposal": 0.0836},
  "minimumEffectiveSample": {
    "H1a": 30, "H2": 55, "H3": 112, "H3perFamily": 112, "H4perGroup": 224,
    "H5": "G>=8 x k>=12 appearances (optimistic; replace by simulation at freeze)",
    "H6": "H3 n_min within each compared group",
    "planning": {"sigmaLog": 0.27, "power": 0.80, "alphaStrictestHolmF1": 0.01, "hlEfficiency": "pi/3",
                 "decoysK": 10, "h2StandardizedEffect": 0.5, "h5Icc": 0.20}
  },
  "floors": {"managersMin": null, "managersMinProposal": 10, "lomoVerdictStability": true, "pairCap": null},
  "uncertainty": {
    "primary": "dyadic node bootstrap over managers, trade weight = product of multiplicities",
    "B": null, "seed": null, "generator": "numpy.random.Generator(PCG64)",
    "crossCheck": "dyadic-robust analytic SE",
    "bayesian": "exploratory, never gating"
  },
  "families": {"F1": ["H1a", "H2", "H3", "H4", "H5"], "F2": ["H6a", "H6b", "H6c", "H6d"], "F3": ["H3_DL", "H3_LB", "H3_DB"],
               "method": "holm", "alpha": 0.05, "equivalence": "TOST at Holm-adjusted alpha"},
  "looks": "count-triggered single look per hypothesis; schedule null",
  "h4Tier": {"elite": "within-family rank <= 12", "basis": null, "basisProposal": "prior-season league-scored ppg"},
  "h7Default": true,
  "promotes": false
}
```

---

## Appendix A. Planning calculations (no data; reproducible)

```python
import math
from scipy.stats import norm, f

m = 5; a = 0.05 / m                      # strictest Holm step of F1
z2, z1 = norm.ppf(1 - a / 2), norm.ppf(1 - a)          # 2.5758, 2.3263
zp, zp2 = norm.ppf(0.80), norm.ppf(0.90)               # 0.8416, 1.2816
det = lambda sd, d: ((z2 + zp) * sd / d) ** 2
eqv = lambda sd, d: ((z1 + zp2) * sd / d) ** 2

# planning sigma from the chaseTradeMarket power study's declared world
t_sd = 0.12 * math.sqrt(4 / 2)                         # Student-t(4) scale 0.12 -> 0.1697
ex2 = (1.6**3 - 0.8**3) / (3 * 0.8)                    # E[x^2], x ~ U(0.8, 1.6) -> 1.4933
sigma = math.sqrt(0.97 * (t_sd**2 + 0.05**2) + 0.03 * (ex2 + 0.05**2))   # 0.2743

delta = -math.log(1 - 0.09)                            # fairness_bands_v2 'unfair' cut -> 0.0943
hl = math.pi / 3
n_h3 = math.ceil(max(det(0.27, delta), eqv(0.27, delta)) * hl)           # 112
n_h4_group = math.ceil(2 * max(det(0.27, delta), eqv(0.27, delta)) * hl) # 224
K = 10; sd_u = math.sqrt((K + 2) / (12 * K))           # 0.3162
n_h1a = math.ceil(((z2 + zp) * sd_u / (0.70 - 0.5)) ** 2)                # 30
n_h2 = math.ceil(max(((z2 + zp) / 0.5) ** 2, ((z1 + zp2) / 0.5) ** 2) * hl)  # 55

def power_h5(G, k, rho, alpha=a):                      # one-way random effects F test
    fc = f.ppf(1 - alpha, G - 1, G * (k - 1))
    return 1 - f.cdf(fc / (1 + k * rho / (1 - rho)), G - 1, G * (k - 1))
k_h5 = next(k for k in range(2, 2000) if power_h5(12, k, 0.20) >= 0.80)  # 12
```

## Appendix B. Method references

- Holm, S. (1979). A simple sequentially rejective multiple test procedure. *Scandinavian Journal of Statistics* 6(2).
- Schuirmann, D. J. (1987). A comparison of the two one-sided tests procedure and the power approach for assessing the
  equivalence of average bioavailability. *Journal of Pharmacokinetics and Biopharmaceutics* 15(6).
- Snijders, T. A. B. and Borgatti, S. P. (1999). Non-parametric standard errors and tests for network statistics.
  *Connections* 22(2).
- Aronow, P. M., Samii, C. and Assenova, V. A. (2015). Cluster-robust variance estimation for dyadic data. *Political
  Analysis* 23(4).
- Cameron, A. C., Gelbach, J. B. and Miller, D. L. (2008). Bootstrap-based improvements for inference with clustered
  errors. *Review of Economics and Statistics* 90(3).
- Hodges, J. L. and Lehmann, E. L. (1963). Estimates of location based on rank tests. *Annals of Mathematical
  Statistics* 34(2).

## Result

- **STATUS:** PARTIAL. The draft is complete. Freezing needs O1–O8 and the H5 simulation.
- **UNRESOLVED:** owner decisions O1–O8; the H5 measured-activity simulation; re-pinning at the freeze; the evaluator
  code (not written, not claimed); whether 2026's pre-floor trades fall inside the R1 window (unknowable without
  ingestion); whether this league's trades appear in KTC's trade database (UNKNOWN).
