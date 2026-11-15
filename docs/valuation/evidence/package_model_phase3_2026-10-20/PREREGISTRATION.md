# Package Value Adjustment — Phase 3 preregistration (frozen 2026-10-20)

**Status: FROZEN before the Phase 3 production run.**

- **Research only.** `geom_q078_v1` (q = 0.78) stays the production model.
- **Authority:** owner directive 2026-10-20, "Production market-ledger analysis & Value Adjustment Phase 3" (see `docs/OWNER_REQUESTED_TODO.md`).
- **Not authorized:** nothing here activates, ranks or promotes a model. A candidate that passes every criterion becomes evidence for an owner decision, nothing more.
- **Freeze:** the protocol is fixed by the code at the pinned commit that runs it, `scripts/package_model_phase3_research.py --box`. This document describes that code. Any later change is an amendment, dated and explained below.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## 1. What has already been seen (disclosure)

1. **The Phase 2 production report**, all 18,031 graded trades, covering 2026-07-15 → 2026-10-19:
   - per-bin mean signed residuals for the 13 Phase 2 models, LP_150 included;
   - splits by source, TEP, IDP format, picks and the KTC vendor flag;
   - the league-capped view;
   - the KTC-market-basis control.

   No trade-level data was seen.
2. **A local rehearsal of this exact script** on the research container's own public-endpoint ledger. That ledger has 1,078 graded trades, mostly from the Sharp Sleeper lane, and it overlaps the box ledger.
   - **Selections it produced:**
     - pooled selection S1 = `GP_090_250`;
     - elite-level selection S2 = `LP_175`;
     - joint decomposition best = `VG_078_2000` on discovery and `VG_085_2000` on the full sample.
   - **Key pattern:** the residual shrinks as the trade's value level rises.

   These rehearsal numbers are not evidence. They show what the protocol does, and they are why the decomposition (§4.3) and the elite-overcredit flag (§5 C6) were added before freezing.

The model families below were designed after seeing (1). That is why a league-disjoint confirmation alone is called *secondary*, and the prospective population (§2.3) is the only fully independent test.

## 2. Populations

All graded trades come from the box's canonical ledger through the Phase 2 pricing owner (`price_market_groups`). That pricing is unchanged:
- the board is strictly before the trade, and at most 7 days older;
- format is dynasty superflex;
- the group is proven unique;
- every asset must be priced (all-or-nothing);
- the comparison is between two teams.

Trades are split into three populations:

1. **Discovery.** Leagues whose salted hash `sha256("phase3-pkg-2026-10-20|" + league)` has an even first byte, plus trades with no league id.
2. **Confirmation (league-disjoint).** Leagues with an odd first byte. No league appears in both discovery and confirmation.
3. **Prospective.** Trades dated after 2026-10-20, in any league. They never enter discovery. They are reported once they include at least 2,000 unequal-count trades. A re-run of the same pinned commit after that point is the confirmatory test.

## 3. Statistics

**Residual and bins.** These are exactly Phase 2's (`PREREGISTRATION.md` of Phase 2, Amendment 1):
- trades are oriented by piece count, with the fewer-pieces side first;
- the signed residual is the adjusted gap divided by the mean adjusted total;
- bins: `1vN_small`, `ordinary`, `deep` and `equal`.

**Calibration loss.** J is the worst |mean signed residual| over the three unequal bins.

**Uncertainty.** League-clustered bootstrap: leagues are resampled with replacement, 400 reps, seed 20261020. Paired statistics use the same resamples.

## 4. Families and selection rules

### 4.1 Eligible, homogeneous family

Every member is monotone, positively homogeneous, order-invariant and anti-symmetric. Each gives a 1-for-1 trade its raw value, and an added piece adds at most its own value.
- `GEOM_q = Σ q^i v_(i)`, with q ∈ {0.50, 0.55, …, 0.78, 0.80, 0.85, 0.90};
- `LP_p = (Σ v^p)^(1/p)`, with p ∈ {1.10, 1.20, 1.30, 1.40, 1.50, 1.60, 1.75, 2.00, 2.50, 3.00, 4.00};
- `GP_q_g = (Σ q^i v_(i)^g)^(1/g)`, with q ∈ {0.60, 0.70, 0.78, 0.85, 0.90} and g ∈ {1.10, 1.20, 1.30, 1.50, 1.75, 2.00, 2.50}.

### 4.2 Selections

On **discovery** only:
- **S1 (pooled):** the argmin of J over the eligible family on all discovery trades.
- **S2 (elite level):** the argmin of J on discovery trades whose noise-balanced level is at least 6000. The level is the mean of both sides' best asset. Above this level a fixed replacement threshold removes little value, so S2 is the cleaner estimate of a pure package effect.
- **Ties** (|ΔJ| < 1e-4) go to the simpler model (GEOM, then LP, then GP), then to grid order.

### 4.3 Decomposition (diagnostic; never a candidate)

`VG_q_c = Σ q^i max(0, v_(i) − c)`, with q ∈ {0.50 … 1.00} and c ∈ {0 … 4000}:
- q is the package-shape effect;
- c is an absolute value level, the market's replacement threshold.

Because c > 0 breaks homogeneity, a VG model can never be a package formula. Its job is to apportion the residual between the package shape and the value level.

The decomposition is reported on discovery, confirmation, the full population and prospective, and per league size, source and composition.

## 5. Confirmation criteria

S1 and S2 are each tested against `GEOM_78`, on confirmation and later on prospective:

| id | criterion | pass when |
|---|---|---|
| C1 | calibration gain | the clustered 95% CI of J(GEOM_78) − J(S) is above 0 |
| C2 | no bin materially worse | in every unequal bin, abs(mean_S) − abs(mean_GEOM78) ≤ 0.02 |
| C3 | dispersion not worse | the clustered CI of mean(abs(r_S) − abs(r_GEOM78)) over all trades is below 0 |
| C4 | both source families | J_S < J_GEOM78 in KTC trade-database trades and in Sharp-Sleeper trades |
| C5 | players and picks | J_S < J_GEOM78 in player-only trades and in trades with picks |
| C6 | no elite over-credit | in the 6000–7999 and 8000+ level tiers, no unequal bin with n ≥ 50 has signed mean > +0.05 |

- The verdict `CALIBRATION_ADVANTAGE_REPLICATED` requires C1–C5. A C6 flag is reported beside it.
- A flagged candidate cannot be recommended for production. Over-crediting consolidation at the elite level is exactly the superstar-preference failure the owner named.

## 6. Interpretation rules (fixed in advance)

**R1 — the package shape is not the problem.** R1 applies when, on confirmation:
- the decomposition's best has c > 0;
- its q lies in [0.70, 0.85];
- its J is below J of the better of S1 and S2.

Then the market residual is best explained by the incumbent's package shape plus an absolute value-level term. A change to the package formula is **not supported**. The level effect is routed to a value-curve, replacement-level or roster-context follow-up, and **never** absorbed into the package formula.

**R2 — evidence for stronger consolidation.** R2 requires all of the following:
- the decomposition's best has c = 0, or its q < 0.70;
- S2 passes C1–C5 without a C6 flag.

Then there is evidence for a stronger-consolidation package model. The next step is the decision replay and an owner decision. Activation still needs the prospective test (§2.3) to pass.

**R3 — replacement-level corroboration.** If the best c falls as league size grows, across the reported league-size tiers, that corroborates R1. A replacement level falls as more teams roster more players.

**R4 — the pure package premium.** S2's two-piece factor (its utility of two equal pieces, divided by one piece) is the elite-level estimate of that premium. The incumbent's factor is 1.78.

**Neither R1 nor R2 changes production.**

## 7. Privacy

- The output is aggregates only: counts, means, intervals and model names.
- `assert_aggregate_only` refuses identifier-like content.
- The league hash is computed in-process and never printed.

## Amendments

None.
