# Preregistration — IDP accuracy, Lane G: near-term retrospective backtest of cross-position valuation candidates

**Status: FROZEN on commit.** This file is frozen by the commit that first adds it. It is that commit's only file.
No result of this experiment existed when it was written. The author did not compute, load or look at any
evaluation output: no candidate value was joined to any 2026 outcome. Section 0.3 lists exactly what the author
had read.

**Amendments.** Any change before Stage 2 (§12) goes in a separate, dated `G_PREREGISTRATION_AMENDMENT_<n>.md`,
committed before the Stage 1 manifest. A change made after Stage 1 began is a **deviation**. It is reported as a
deviation and never presented as part of the plan. The evaluator verifies that this file's blob is unchanged since
its first commit, the same check as `model_registry.independent_validation.git_preregistration_committed`.

**Authority:** `docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md` §9 (cross-position value) and §11
(independent backtest), under its §13 production-safety rules. These authorize research and shadow work only.
Nothing here authorizes a served value, rank, source weight, vote, anchor, Hill curve, package-model or
fairness change, or a production recommendation.

**Does not edit:** `docs/valuation/evidence/league_fair_value_v1/PREREGISTRATION.md`. That record is untouched, and
its forward requirement stays unmet (§14).

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

---

## 0. Pins and disclosure

### 0.1 Code and records this plan is written against

| item | pin |
|---|---|
| branch base (Lane B, PR #1940) | `f64b16fbfc48f538b596f0403de3920cd5e87a6b` |
| Lane C summary branch | `origin/claude/idp-c-market-baseline` at `4484f5f7a496852d3639c66810b0c7019b760db4` |
| `src/league_valuation/replacement_shadow.py` (candidate C) | blob `db83469afc2282c39dea4a1a868e408c879fc1ae` |
| `config/league_valuation/replacement_shadow_v1.json` | blob `c6e0c9f41a7df3d825af114ded493e7a2bcd2a11` |
| `config/league_valuation/fair_value_v1.json` (candidate B) | blob `3ef9f2f04967acb82859b5cf0bcddd493a445f88` |
| `config/bdvm/params_v1.json` (candidate A) | blob `00a4bb083f546090bb882fed4a2a7aad408ec026` |
| `scripts/bdvm_build_baseline.py` (A's substitute input) | blob `1fc156d5bdf9470a5220582c5178986ef15f20d5` |
| `src/ros/lineup.py` (the one lineup owner) | blob `a0fffdf04caff49ea81990511fc9c5f80a3bf8ad` |
| `config/trade/package_model.json` (descriptive trade examples) | blob `897982b0575c0bd0404b96f32488ad937a5c4628` |
| `src/history/asof.py` (`knowledge_cutoff`) | blob `5cc8cabc112e7545c6f7a629e638b17a832a5f8b` |
| fair-value preregistration (read, not edited) | blob `b3c4db4535a646c12a36c4499f47bee9980f0218` |
| fair-value model card | blob `10e498c71becc7778a4075f9666ba5db83d272c8` |
| owner directive | blob `5db1d66c7e1c47bb7b6a2610a529b611a5d4058b` |

If a pinned file differs from the code that actually runs, the receipt names the difference. The run uses the code
at the Stage 1 commit (§12), and that commit's SHA is the code pin.

### 0.2 Facts taken as given (established by other lanes, re-verified as Stage 2 preconditions in §6.3)

* The point-in-time archives `exports/archive/dynasty_export_*.zip` start at 2026-07-14. Nothing earlier exists,
  and nothing earlier will be reconstructed.
* Outcomes are the 2026 regular season, weeks 1–6, scored by the host-native Sleeper scorer
  (`compute_weekly_points(source="sleeper")`). Lane A verified it 3,710 / 3,710 against Sleeper's awarded points.
* `src/ros/lineup.py` (`solve_optimal_assignment`) reproduces Sleeper's awarded best-ball team-week totals. Lane B
  reports 72 / 72 within Sleeper's 2-decimal rounding, with the host rule (§3.4).
* Lane C: the cardinal cross-position level on the served board comes from two external markets, IDP Trade
  Calculator and Draft Sharks. Their shared-market anchor is `NOT_JUSTIFIED` as a representation of this league.
* Lane B: free-agent production levels suffer a strong winner's curse. Free agents chosen on prior weeks scored
  about half their history ppg in the following week.

### 0.3 What the author saw before writing this plan (disclosure, not a claim of blindness)

Read: directive §9 and §11; the fair-value preregistration and model card; the header and §0–§2 of Lane B's
`B_REPLACEMENT.md`; the header and §6.5 of Lane C's `C_MARKET_CROSS_POSITION.md`; `src/history/asof.py`.

Lane B's and Lane C's headline findings were computed on the same 2026 weeks 1–6 this experiment uses as outcomes,
so the author is **not blind** to those weeks' broad character. No constant in this plan is fitted. Every number in
§7–§10 is a convention, a structural quantity or a decision-relevance argument, and each is justified where it is
introduced.

---

## 1. Question and scope

**Question.** On identical cohorts, inputs and cutoffs, which valuation candidate best anticipates the next weeks'
realized **marginal best-ball lineup contribution** in `dynasty_main`? The comparison is made within each of QB, RB,
WR, TE, DL, LB and DB, and across offense versus IDP.

**This experiment is a NEAR-TERM RETROSPECTIVE.** It is NOT the long forward dynasty horizon the fair-value
preregistration requires. That preregistration's primary target is realized league-scored points over replacement
summed over two or more forward seasons. That requirement **stays unmet** whatever this experiment finds. A
six-week production target can neither show nor refute a candidate's accuracy as a *dynasty trade value* (§13).

**It is also not fully out-of-sample.** Every candidate input is read point-in-time (§2), so no input was generated
after the evaluated games. But the outcomes were public, and other lanes had examined them before several
candidates were defined (§4.7). Directive §11 forbids calling such a test fully out-of-sample. Its label is
**`retrospective_point_in_time`**.

---

## 2. Point-in-time design

### 2.1 Windows

| id | role | origin | outcome weeks |
|---|---|---|---|
| **W0** | **primary** | latest archive strictly before the week-1 kickoff | 2026 REG weeks 1–6 |
| Wa | stability (§10) | same origin as W0 | weeks 1–3 |
| Wb | stability (§10) | latest archive strictly before the week-4 kickoff | weeks 4–6 |

No other window is examined under this preregistration. Weeks 7 and later are out of scope. A confirmatory test on
outcomes unobserved at preregistration time needs a **new** preregistration (§13.3).

### 2.2 Cutoff instants

For window *w*:

* `K_w` is the kickoff instant (UTC) of the first game of the window's first week, from the NFL schedule pinned in
  the Stage 1 manifest. It is resolved there and not hardcoded here.
* `A*_w` is the archive in `exports/archive/` whose generation instant `g(A)` is the latest with `g(A) < K_w`
  (strictly before). `g(A)` is the archive's internal generation timestamp if it carries one. Otherwise it is the
  filename stamp `dynasty_export_YYYYMMDD_HHMMSS`, read as UTC, and the manifest records which source was used. The
  archive's sha256 is pinned.
* `C_w = g(A*_w)` is the **cutoff instant**. `knowledge_cutoff_w = K_w − 1 second`.

Every ledger read for window *w* is
`src.history.asof.batch_known_before([(asset_key, C_w), …], knowledge_cutoff=knowledge_cutoff_w)`. Valid time is
therefore bounded by the cutoff archive. Transaction time is bounded strictly before the window began, so a
backfill or correction recorded later is invisible (the asof module docstring). `max_age_days` is `None`, the
module's own historical-replay posture. An `unavailable` result is **missing**: never 0, and never a later value.

### 2.3 Admissibility of every input

An input is admissible for window *w* only if its own provenance proves it existed at or before `C_w`.

| input | admissible form for window *w* |
|---|---|
| champion value | ledger `canonical_board` lane via the read in §2.2 |
| rosters (12 teams) | `sleeper.teams` inside `A*_w` (players only; picks never occupy roster spots) |
| starter slots | `rosterPositions` inside `A*_w`, resolved by `lineup.resolve_starter_slots` (live list, then refuse; never a literal) |
| scoring card | the 2026 card in force during the window, proven by the §6.3 reconciliation. A league's rules are ex-ante knowledge. The card is not a forecast |
| player position and eligibility | the cutoff archive's position (stratum, §5) and Sleeper `fantasy_positions` as of the cutoff archive. If not recoverable point-in-time, today's `fantasy_positions` are used and labelled `eligibility_today` |
| historical production | host-scored games completed before `C_w`: 2025 REG for W0/Wa, plus 2026 REG weeks 1–3 for Wb |
| BDVM projection snapshot | see §4.2. A box-local snapshot counts only with an immutable creation stamp ≤ `C_w` and a content hash, and with every source record retrieved ≤ `C_w` |
| BDVM events | only events whose own dated provenance is ≤ `C_w`. Otherwise none |
| injury status at cutoff | **not used.** It cannot be reconstructed point-in-time from the repo. The asymmetry this creates is declared in §13.2 |

---

## 3. Shared inputs, identical for every candidate

### 3.1 Production prior `P`

One owner: BDVM. The directive's §9 rule is "where the existing BDVM already owns a correct calculation, reuse it",
so this experiment introduces no second projection engine. `P` supplies each player's season-0 projected league
points per game `μ_i`. Candidates A, C and D all consume the **same** `P` at the same tier (§4.2). R0 (§4.6)
reports `P` itself.

### 3.2 Weekly residuals and availability (consumed by D only)

* Residual set `E_i = {y_ik − ȳ_i}` over i's admissible host-scored games played (§2.3).
* Availability `a_i = (g_i + 4·ā_p) / (G_i + 4)`. Here `g_i` is games played in the admissible history, `G_i` is
  team games while the player was on an NFL roster, `ā_p` is the cohort mean of `g/G` at i's position, and 4 is a
  declared PRIOR pseudo-count (a quarter-season).

### 3.3 Lineup engine

`src.ros.lineup.solve_optimal_assignment` is the one exact solver. There is no greedy fallback. Lineup computations
**always use the full cutoff rosters**, including kickers, rookies and players outside the cohort. The cohort (§5)
only decides which players are *evaluated*.

### 3.4 Host lineup rule

In realized weeks, a rostered player with no stat line scores 0.0 and is startable (Lane B §1). It is applied to
realized outcomes only, never to an ex-ante projection.

### 3.5 Unprojected rostered players in ex-ante environments

A rostered player with no `P` projection, such as a 2026 rookie, is UNKNOWN in candidate C's and D's ex-ante lineup
environments. That is `lineup.py`'s `None` semantics: not assignable, and the slot is reported unfilled. No value is
imputed. A placeholder variant is a stability check only (§10, S7).

---

## 4. Candidates

Every candidate maps each cohort player to a score `V_i^c` computed from window-*w* admissible inputs only. All
confirmatory tests are **rank-based**, so no candidate is converted to another's scale.

### 4.1 Champion — canonical market value, as served

`V^0_i` = the served `rankDerivedValue` of player i at `C_w`, read from the ledger (§2.2).

* **Concordance check.** If `A*_w` carries a served contract, its `rankDerivedValue` must equal the ledger value as
  an exact integer for at least 99% of cohort rows. Agreement below that is reported, and the ledger value still
  governs because it is the bitemporal record.
* **Ledger unavailable**, or coverage of the archive's priced player rows below 95% under `knowledge_cutoff`:
  the champion becomes **champion-rebuilt**. That is `A*_w`'s raw payload rebuilt by `build_api_data_contract` at
  the Stage 1 commit, labelled `champion_methodology_at_head`, and every claim must then say the comparator is
  today's market method on point-in-time inputs, not the board users saw.
* **Champion-rebuilt** is also computed whenever possible. It is B's anchor where no served contract exists (§4.3),
  and the drift between served and rebuilt is reported as within-position Spearman between the two.

### 4.2 Candidate A — BDVM league-scored fundamental utility

**Point-in-time reconstruction problem, stated plainly.** BDVM projection snapshots live under the gitignored, box-local
`data/bdvm/projections/`, and a rebuild "carries real records forward". From the repository alone, nothing proves a
pre-kickoff snapshot existed in the form the box now holds. So A is defined in two tiers. The tier is chosen in Stage 1
**by provenance alone, before any outcome is loaded**:

* **A-real.** A box snapshot whose immutable creation stamp is ≤ `C_w`, with a content hash, and every source record
  (Mike Clay's guide, IDP Show) retrieved ≤ `C_w`. It is used as-is.
* **A-proxy (honest substitute).** A §8.3 reconstructed baseline built by `scripts/bdvm_build_baseline.py` into a
  **clean, empty output directory**, so there is no prior snapshot to carry forward. Its nflverse inputs are restricted
  to seasons ≤ 2025 (plus 2026 REG weeks 1–3 for Wb), with rookie draft-slot priors where BDVM has them. Every record is
  `is_proxy`. This is **not "BDVM as served then"**. It is the current BDVM method applied to inputs that existed
  before the cutoff. Stat corrections to 2025 games published after `C_w` cannot be excluded. They are declared and
  presumed negligible.

If neither tier can be built, A is `not_evaluable: no_point_in_time_projection` and is excluded. B then cannot be
built either (§4.3).

Run settings:

* `config/bdvm/params_v1.json` at the pin. Its `paramSetId` is recorded.
* League configuration from §2.3.
* Events per §2.3.
* `actuals`: `None` for W0 and Wa. For Wb, weeks 1–3 only, if `run_valuation(actuals=…)` accepts an explicitly
  truncated input. Otherwise `None`, labelled `no_inseason_update`, which declares a handicap against the
  champion, whose market had moved.

**Score.** `V^A_i` is the lexicographic order of (balanced-strategy discounted DV, signed season-0 `fpg − R`). These
are the same utility pair `league_fair_value_v1` consumes (model card, Method step 2). Unpriced players are missing.
The 2026 rookie class has `no_projection` and is missing.

### 4.3 Candidate B — `league_fair_value_v1_shadow`

`V^B` is the fair value computed by `src/league_valuation/` with `fair_value_v1.json` at the pin. Its anchor is the
served contract inside `A*_w` if one exists, otherwise champion-rebuilt. Its utility evidence is candidate A's
output at the chosen tier. **B's configuration is not changed for this experiment.**

Pre-declared consequences of B's own model card:

* Under **A-proxy**, every row's utility evidence is proxy-only, so `k = 0` and `fairValue == marketValue` exactly.
  B is then **degenerate**: identical to its anchor on every cohort row. In that case B is reported
  `not_evaluable: degenerate_market_exact` and removed from every test family **in Stage 1**. B is not made
  non-degenerate by any change.
* If B's IDP depth fan-out gate fails, `k = 0` for the whole IDP scope. That is part of B and is evaluated as is.
* B quantile-matches offense and IDP **separately**, so it cannot move the cross-position level by construction.
  Its cross-position concordance can change only through reordering within a population.
* **Mechanism comparison.** B against its own anchor is reported descriptively beside B against the champion, so
  B's effect is not confused with drift between the served and rebuilt boards.

### 4.4 Candidate C — corrected replacement and lineup utility (`replacement_shadow`)

`V^C_i = μ_i − R_{π(i)}`, in league points per game.

* `μ_i` comes from `P` (§3.1).
* `R_p` is **Lane B's D1** at the cutoff. D1 is the league-wide starter threshold at position p, from the exact
  solver over the 12 cutoff rosters scored by `μ`, with FLEX and SUPER_FLEX competing. It is computed by
  `replacement_shadow` at the pin.
* `π(i)` is the position among i's eligible positions (`fantasy_positions`) that maximizes `μ_i − R_p`.

**Why D1 is primary, decided here before any outcome:** it is the only Lane B definition that exists at every
position. The free-agent definitions D2–D4 are undefined at QB (0 viable unrostered QBs) and rest on thin pools. A
candidate that is undefined at a position would shrink the common cohort for every other candidate. D2, D4 and D5 are
stability variants (§10, S3). Wherever `replacement_shadow` exposes its empirical-Bayes winner's-curse correction,
those variants use it, with any hyperparameter estimated **only from admissible pre-cutoff player-weeks**. Where a
free-agent level is undefined, the variant falls back to D1 at that position and is labelled.

**Disclosure.** Within a position, C's order equals `μ`'s order apart from hybrid eligibility. C's within-position
result is therefore a test of `P`. C's distinctive content is its **cross-position level**.

### 4.5 Candidate D — common league-utility scale, independently calibrated (no market input)

**What D is.** D is the ex-ante **expected league-average marginal best-ball contribution**, in expected league
points per week. It is the expectation of the primary outcome (§6.1) under a simulation model built only from
admissible inputs:

```
V^D_i = (1/S) Σ_s (1/12) Σ_t [ L(R_t ∪ {i}, x_s) − L(R_t \ {i}, x_s) ]
```

* `L(R, x)` is the optimal best-ball lineup total of roster R under weekly scores x, from the exact solver (§3.3).
* `R_t` is the cutoff roster of team t. For i on `R_t`, `R_t ∪ {i} = R_t`.
* Each simulated week `x_s` draws every player independently. Played ~ Bernoulli(`a_i`). If played, the score is
  `μ_i + ε`, with ε drawn uniformly from `E_i` when `|E_i| ≥ 6`, otherwise from the pooled residual set (the union
  of `E_j` over cohort players j with i's cutoff position and `|E_j| ≥ 6`). If not played, the score is 0.
* `S = 200` simulated weeks, with seed `20261027` from a stream separate from the bootstrap.
* Monte Carlo standard errors are reported per player. Ties inside MC error are not broken artificially.

**Transform family: the identity on the league-points scale.** D is never mapped onto the canonical 1–9999 scale,
never fitted to any market price, never anchored to IDPTC, Draft Sharks or any other value source, and never
quantile-matched to any board. Its only calibration is the league's own scoring card, lineup slots and roster
contexts. Directive §9 says that if an independently justified transform into 1–9999 cannot be established, the
estimate stays uncalibrated, so D is uncalibrated by design. It is compared with the other candidates **only through
ranks** (§7). Cardinal statements are made only against outcomes on the same points scale (§9.4).

**How D differs from C.** C is mean-based, with a single position threshold, and has no variance. D uses each
player's score distribution and the real roster contexts, and has no replacement constant at all, because
replacement emerges from who is on each roster. The ablation **D(σ=0)**, with residuals set to 0, is a declared
stability variant (§10, S4). The contrast D minus D(σ=0) is the descriptive estimate of a best-ball volatility
premium (directive §3, question 6).

Simplifications declared: independent draws across players and weeks (no game-script correlation); the roster
cap is ignored when adding a player (its cost belongs to §9.1); no injury status at cutoff (§2.3).

### 4.6 Reference R0 — the shared prior alone (not a candidate)

`V^R0_i = μ_i`. It sits outside every test family and is reported descriptively, so a reader can see whether A, C or D
add anything to `P` itself.

### 4.7 Design timing and signal dependence (both bind the claims in §13)

| candidate | when its definition was fixed, relative to public 2026 week 1–6 outcomes |
|---|---|
| champion | served live; no design choice made for this test |
| A | `params_v1` predates the season; the code is HEAD |
| B | `fair_value_v1` was authored in-season, from the owner directive of 2026-10-19 |
| C | Lane B developed its definitions **by computing on weeks 1–6**. Highest overlap |
| D | defined in this document, after the author read Lane B and C headline findings (§0.3). No fitted constant |

**Correlated descendants.** A, C, D and R0 all descend from `P`. Champion and B both descend from the market. Agreement
among A, C and D is one body of evidence about `P` plus their mechanisms, not three independent confirmations. Holm
correction (§7.5) controls multiplicity but does not turn correlated agreement into corroboration.

---

## 5. Cohort, identical for all candidates

For each window, the cohort is the set of players satisfying **all** of:

1. a champion value at the cutoff (§4.1);
2. a Sleeper player id on the cutoff row;
3. a cutoff position that maps, via `POSITION_ALIASES`, to one of QB, RB, WR, TE, DL, LB or DB (kickers and picks
   are out);
4. a defined value from **every evaluable candidate**: the common support;
5. a defined primary outcome. LAMBC is defined for every valid Sleeper id, because a missing stat line in a realized
   week is a 0.0 contribution under the host rule. Note that "no contribution" here is the host's real scoring, not
   imputation.

The stratum is the cutoff position. Lineup legality uses eligibility.

* **Counting.** The Stage 1 manifest counts exclusions by reason and by candidate.
* **Missing is never zero.** No candidate's missing value is filled with 0, a floor, a default or a later value.
* **Expected exclusion.** The 2026 rookie class (no `P`, no A). **This experiment says nothing about rookies.**
* **Minimum size.** `min_n_per_position = 20`. Below 20, a Spearman's sampling SD exceeds about 0.2 at ρ ≈ 0.4,
  roughly `1/√(n−1)`, which is four times the effect size that matters (§8). Such a position is reported
  descriptively and dropped from the pooled primary metric. The family is then labelled `reduced_family`.
* **When F1 is INSUFFICIENT.** F1 (§7.5) needs at least 5 qualifying positions, including at least 3 offense and at
  least 2 IDP. The cross-position metric needs at least 50 players in each population. Otherwise F1 is
  `insufficient_sample: cohort_size` and nothing in F1 is tested.
* **When the cohort is frozen.** Cohort size is known in Stage 1, before outcomes are joined, so these rules cannot
  respond to results.

---

## 6. Outcomes

### 6.1 Primary — realized league-average marginal best-ball contribution (LAMBC)

```
Y_i = (1/|W|) Σ_{w∈W} (1/12) Σ_t [ L(R_t ∪ {i}, y_w) − L(R_t \ {i}, y_w) ]
```

* `y_w` is the realized host-scored points of week w.
* `R_t` is team t's **cutoff** roster. The rosters are fixed at the cutoff deliberately: this is the counterfactual
  "what this player was worth to this league's rosters as they stood", not a replay of later transactions.
* The unit is league points per week.

Why this target:

* it is directive §9's marginal lineup utility, measured, under exact best-ball rules;
* it averages over the league's real roster contexts, so positional scarcity and depth enter through rosters rather
  than a constant;
* its cross-position comparison is in one unit, league points, with no market involved.

### 6.2 Secondary — realized points per game

Realized points per game is window host-scored points divided by games played. It is undefined for a player with
zero games, who is excluded from secondary metrics only. Secondary metrics are descriptive and never gate a verdict.

### 6.3 Preconditions, checked at the start of Stage 2 and before any metric

1. **Scorer reconciliation.** The host-native scorer equals Sleeper's awarded points within Sleeper's 2-decimal
   rounding for every player-week of the exact stat pull used.
2. **Lineup reconciliation.** The exact solver with the host rule reproduces Sleeper's awarded best-ball team-week
   totals for weeks 1–6 on the actual weekly rosters.

Either failure stops the run with `insufficient_sample: scorer_unreconciled` and no metric is computed. Directive §6B:
no performance claim while scorer discrepancies are unexplained.

---

## 7. Metrics and tests

### 7.1 Within-position ordering (directive §11C)

`ρ_p(V, Y)` is the Spearman correlation within position p, with midranks for ties. The per-position delta is
`Δρ_{p,c} = ρ_p(V^c, Y) − ρ_p(V^0, Y)`.

**Primary metric**, `within_position_spearman_delta_vs_champion_lambc_2026w1_6`:

```
Δ1_c = (1/|P*|) Σ_{p∈P*} Δρ_{p,c}
```

`P*` is the set of qualifying positions (§5). Each position gets equal weight. Each position is its own decision
domain, so neither the deepest position nor the thinnest dominates. The `n`-weighted pooling is a stability variant
(§10, S9).

### 7.2 Cross-position ordering, offense vs IDP (directive §11E)

For offense O = {QB, RB, WR, TE} and IDP I = {DL, LB, DB}:

```
CC(V) = Σ_{o∈O, d∈I, Y_o≠Y_d} [ 1{(V_o−V_d)(Y_o−Y_d) > 0} + ½·1{V_o = V_d} ] / #{(o,d) : Y_o ≠ Y_d}
Δ2_c  = CC(V^c) − CC(V^0)
```

This is the probability that the candidate orders a random offense-versus-defender pair the way realized lineup
contribution did. It is scale-free, so the champion's 1–9999 scale, BDVM's 0–10000 scale and D's points compare
without calibration.

### 7.3 Elite identification (directive §11D)

Elite is defined **ex ante**, by a rule fixed here:

* **Positional.** The realized elite set is the top 12 by `Y` within position p. Twelve is the team count: a league's
  "number one" at the position, one per team. All players tied at the boundary are included. The candidate's
  ex-ante set is its top 12 by `V^c` within p. Boundary ties are broken by champion value, then by Sleeper id.
  Metric: precision@12, averaged over `P*`. The delta is `Δ3pos_c`.
* **Pooled.** The realized set is the top 36 by `Y` over the whole cohort. Thirty-six is a convention: three per
  team, the first three rounds of a 12-team startup, which is where star-for-depth pricing happens. The candidate's
  set is its top 36 by its own score. Metric: precision@36. The delta is `Δ3pool_c`.

  Pooled top-36 is defined on each candidate's own ordering, so it needs no common scale. The number of IDP players
  in each candidate's top 36 against the realized top 36 is reported descriptively (§9.3).

### 7.4 Bootstrap

* **Draws.** Paired bootstrap, `B = 2000` resamples, generator `numpy.random.Generator(PCG64(20261026))`, a single
  stream.
* **Draw order.** `for b in 1..B: for p in [QB, RB, WR, TE, DL, LB, DB]: idx[b][p] = rng.integers(0, n_p, n_p)`.
  This stratifies by position, and therefore by population.
* **Resampling unit.** Players. The **same** index arrays are used for every candidate and for every metric in
  F1–F3. Pairing is across candidates as well as against the champion.
* **Intervals.** Percentile 95%, two-sided (2.5% and 97.5%).
* **p-values.** `p_up = (1 + #{Δ*_b ≤ 0}) / (B + 1)`, `p_down = (1 + #{Δ*_b ≥ 0}) / (B + 1)`, two-sided
  `p = min(1, 2·min(p_up, p_down))`. The smallest attainable two-sided p is 2/2001 ≈ 0.001.
* **Limitation.** Player resampling treats 2026 weeks 1–6 as a fixed environment. It does not sample season-level
  variation, and players who share NFL games are correlated. An NFL-team cluster bootstrap is stability variant S8.

### 7.5 Test families and Holm correction

`E` is the set of **evaluable candidates**, fixed in the Stage 1 manifest before unblinding. Removal is for
degeneracy (§4.3), no point-in-time input (§4.2), or cohort failure. Family sizes `m` are therefore fixed before any
outcome is seen. Each family is Holm-corrected separately at familywise α = 0.05 on the two-sided p of §7.4. Holm
step-down: sort p ascending, then reject the k smallest while `p_(j) ≤ α / (m − j + 1)` holds for every j ≤ k.

| family | hypotheses | max m | role |
|---|---|---|---|
| **F1** (confirmatory) | `Δ1_c = 0` and `Δ2_c = 0` for each c ∈ E | 8 | decides `advance_retrospective` / `champion_better` (§8) |
| **F2** (position level) | `Δρ_{p,c} = 0` for the 7 positions × each c ∈ E | 28 | the no-regression guard (§8.2); per-position reporting |
| **F3** (elite) | `Δ3pos_c = 0` and `Δ3pool_c = 0` for each c ∈ E | 8 | secondary; reported, never gates |

R0, the secondary outcome (§6.2), §9 and §10 sit outside every family. They are descriptive only, with intervals and
without p-values.

**Resolution limit, stated in advance.** With B = 2000, F2's first Holm threshold at m = 28 is 0.05/28 ≈ 0.0018.
Only the minimum attainable p (2/2001) clears it, so an F2 rejection requires that **no** resample crosses zero. The
practical regression guard is therefore the point floor in §8.2 rule 3, not F2 significance. B is not raised after
the fact.

---

## 8. Minimum practically meaningful effects and the advance rule

### 8.1 Thresholds (decision relevance, fixed before data)

| quantity | minimum meaningful effect | justification |
|---|---|---|
| `Δ1_c` (pooled within-position Spearman) | **+0.05** | For a bivariate-normal pair, Spearman ρ_s maps to Kendall τ by `r = 2 sin(πρ_s/6)`, `τ = (2/π) arcsin r`, and the pairwise-ordering probability is `(1+τ)/2`. Across ρ_s from 0.30 to 0.75, Δρ_s = 0.05 is about 0.017–0.023 in ordering probability, roughly **2 more correct same-position calls per 100 comparisons**. A trade calculator's advice is a sequence of such comparisons. A smaller gain would change the answer in fewer than 1 comparison in 50, which does not justify a second valuation path, its governance and its explanation cost |
| `Δ2_c` (cross-position concordance) | **+0.02** | The same unit, made directly: **2 more correct offense-versus-IDP orderings per 100 cross pairs**. Cross pairs are exactly the decisions an offense-for-defender trade turns on |
| `Δ3pos_c`, `Δ3pool_c` (elite precision) | **+1/12 ≈ 0.083** | One more correctly identified elite player per position (positional), or three more in the pooled top 36. F3 is secondary, and these effects describe it |

The thresholds are argued from what changes a decision. They were not chosen from data, power or any observed
result. The Stage 1 manifest **may** record a design-power note computed from cohort sizes alone, assuming
ρ_s = 0.40 and an inter-candidate score correlation of 0.8 (stated assumptions, no outcome data). It is informational
and changes no threshold.

### 8.2 Advance rule (per candidate, per axis)

**`advance_retrospective` on the within axis** requires all of:

1. F1 rejects `Δ1_c = 0` (Holm) with `Δ1_c > 0`, and the point estimate `Δ1_c ≥ 0.05`;
2. no position with an F2-significant (Holm) negative `Δρ_{p,c}`;
3. no position with a point estimate `Δρ_{p,c} < −0.10`. A loss that large at one position, about 4 calls per 100,
   is twice the minimum gain. A candidate buying a pooled gain with it moves error rather than removing it;
4. a cross-axis guard: `Δ2_c ≥ −0.01`;
5. stability (§10): the sign of `Δ1_c` is unchanged under every evaluable core variant (S1–S6). Otherwise the
   result is `advance_unstable`, which is **not** an advance.

**`advance_retrospective` on the cross axis** requires the same five conditions with these substitutions:

1. F1 rejects `Δ2_c = 0` with `Δ2_c > 0`, and `Δ2_c ≥ 0.02`;
2. no F2-significant regression (as above);
3. no `Δρ_{p,c} < −0.10` (as above);
4. a within-axis guard: `Δ1_c ≥ −0.02`;
5. sign stability of `Δ2_c` under S1–S6.

**Other verdicts**

| verdict | condition |
|---|---|
| `champion_better` (axis) | F1 rejects the axis hypothesis with the delta below 0 |
| `advance_blocked_regression` | rule 1 holds but rule 2, 3 or 4 fails |
| `below_meaningful_effect` | significant, but the point estimate is under the threshold |
| `no_detectable_difference` | F1 does not reject |
| `not_evaluable:<reason>` / `insufficient_sample:<reason>` | per §4–§6 |

**What "advance" means.** `advance_retrospective` means "worth carrying to a confirmatory test on outcomes not yet
observed when that test is preregistered". It **never** means validated, promoted, served or eligible under the
fair-value gate. No verdict here writes an `EvaluationReceipt` in the `league_fair_value_v1` family, emits
`challenger_better_pending_policy`, or touches `model_registry.family_gates`. Every artifact carries
`promotes: false`.

---

## 9. Descriptive analyses (no test family, no gate)

### 9.1 Roster counterfactuals (directive §11F), W0 only

For each team t:

* **Universe.** Every legal swap at the cutoff: drop r ∈ `R_t` ∩ cohort, add f ∈ cohort unrostered at the cutoff.
* **Realized benefit.** `ΔL = Σ_w [L(R_t − r + f, y_w) − L(R_t, y_w)]`.
* **Predicted gain.**
  * champion, A, B: `V_f − V_r`;
  * C: the deterministic μ-lineup change for t;
  * D: the simulated expected lineup change for t, with the same S and seed.

Reported:

* pairwise sign accuracy over swaps with `ΔL ≠ 0`;
* each candidate's top predicted swap per team (deterministic tie-break). Its realized `ΔL` is averaged over the 12
  teams, alongside the count of teams where it beat the champion's top swap. The same is reported for the top three;
* the predicted-versus-realized gap of the chosen swaps. Selection on predicted gain inflates every candidate's
  prediction (Lane B's winner's curse), so this gap is reported and **never** used to score a candidate.

With n = 12 teams, no inferential claim is made.

### 9.2 Trade examples (directive §11G), W0 only

**Universe.** Trades between two different teams at the cutoff whose assets are cohort players, and which the
champion's own rule calls fair: the adjusted gap from `geom_q078_v1` (`package_model.adjusted_pair_totals`) falls
inside the `fairness_bands_v2` "fair" band. These are the trades a user is told are even, which is where a different
valuation would change the advice.

Categories:

* (a) offense-for-IDP, 1-for-1;
* (b) 2-for-1, with the starter-upgrade side and the depth side each evaluated;
* (c) any (b) trade that pushes the receiving-more team past its roster limit. That team must cut, and each candidate
  chooses the cut by its own score. For C and D, the cut is the player whose removal costs the least expected lineup
  points.

**Sample.** Up to 150 trades per category, the first by `sha256("idp-g-v1" + trade id)`.

**Realized.** Each team's `ΔL` over W0, after the cut is applied. The realized winner is the team with the larger
`ΔL`.

**Calls.**

* champion and B: the package model on their values;
* A: BDVM `package_value` (balanced strategy);
* C and D: whole-roster expected lineup change for each team.

**Reported.** Share of correct winner calls, with Wilson 95% intervals. A dynasty trade is a multi-year bet, and
**six weeks of lineup points cannot grade it** (§13). These examples expose failure modes only.

### 9.3 IDP level diagnostic (the central question, made directly observable)

Among cross pairs the candidate orders **wrongly**, the share where it overrated the IDP side. 0.5 means no level
bias. Above 0.5 means it overvalues defenders relative to offense in near-term utility. Below 0.5 means it
undervalues them. A bootstrap interval comes from the same resamples. Reported with it: IDP counts in each
candidate's top 36 against the realized top 36.

### 9.4 Elite separation (cardinal)

Elite separation is reported only where the candidate's scale is league points, that is C and D against `Y`:

```
ratio = mean of the top 12 at the position / mean of ranks 13–36
```

The ratio is computed for the prediction and for the outcome. Champion, A and B are on value scales with no
validated mapping to points, so their separation is `unavailable: no_validated_points_mapping`. That is the answer
directive §9 requires when no independent transform exists.

### 9.5 Secondary outcome and R0

Every F1–F3 metric is re-computed on realized ppg, and every metric is computed for R0, all with intervals.

---

## 10. Stability checks (directive §11I)

Each variant re-computes `Δ1`, `Δ2` and the §9.3 diagnostic for every evaluable candidate. S1–S6 are the **core**
variants that §8.2 rule 5 requires to preserve sign. A variant that cannot be built is `not_evaluable` and does not
block.

| id | variant | applies to |
|---|---|---|
| S1 | **windows:** Wa (weeks 1–3) and Wb (origin before week 4, weeks 4–6) | all |
| S2 | **age assumptions:** every age +1 year and −1 year in BDVM's aging | A, B (C, D are season-0: `not_applicable`) |
| S3 | **replacement definition:** D2, D4, D5 in place of D1 (EB-corrected where available; D1 fallback labelled) | C |
| S4 | **best-ball volatility ablation:** D(σ=0); and roster context = own team only for rostered players | D |
| S5 | **projection mix:** A-real against A-proxy when both exist; offense-real plus IDP-proxy; IDP Show dropped | A, B, C, D |
| S6 | **missing data:** pairwise common support (each candidate against the champion on its own support) in place of the all-candidate intersection | all |
| S7 | unprojected rostered players given their position's D1 level as a **labelled placeholder** in ex-ante environments | C, D |
| S8 | NFL-team cluster bootstrap (players clustered by cutoff NFL team) | all |
| S9 | `n`-weighted position pooling; and cross-position concordance restricted to players rostered at the cutoff | all |
| S10 | availability pseudo-count 0 and 16 in place of 4 | D |

---

## 11. Failure-case analysis (directive §11J)

These slices are fixed now. Each reports Δρ and cross-pair concordance per candidate where the slice has `n ≥ 15`.

* each position;
* champion market band at the cutoff: board rank 1–50, 51–150, 151–300, 301–800, and off-cap value-only;
* age at the cutoff: ≤ 24, 25–28, ≥ 29;
* rostered against unrostered at the cutoff;
* DL/LB hybrid-eligible players;
* players with ≤ 3 games played in the window. They are an injury-dominated slice, reported, never removed from the
  primary.

Per candidate, the 20 players with the largest increase in absolute rank error against the champion
(`|rank_c − rank_Y| − |rank_0 − rank_Y|`) are listed, using public NFL names only.

**Unavailable, named rather than invented:** interior DL against edge, and CB against S. Sleeper positions do not
distinguish them, and no point-in-time depth-chart source is pinned. A slice needs such a source pinned in an
amendment before Stage 1.

---

## 12. Execution protocol

### 12.1 Stage 1 — blind

No 2026 week 1–6 outcome is loaded into the process. Stage 1:

1. resolves `K_w`, `A*_w` and `C_w` (§2.2);
2. builds every admissible input;
3. decides A's tier and B's degeneracy;
4. computes every candidate score, R0 and the cohort;
5. records `n_p`, `E` and the family sizes `m`;
6. may compute an optional power note (§8.1) and a **noise ceiling**. The noise ceiling is the Spearman between two
   disjoint 6-week windows of **2025** host-scored ppg per position, pre-cutoff data only, which shows how much any
   candidate could achieve.

It writes `docs/valuation/idp_accuracy/evidence/g_stage1_manifest.json` with every pin:

* this preregistration's commit SHA;
* the code SHA;
* archive sha256 per window;
* the ledger file hash;
* `C_w` and `knowledge_cutoff_w`;
* the scoring fingerprint (sf1);
* BDVM `paramSetId`, A's tier and the snapshot hash;
* the fair-value `paramSetId`;
* the `replacement_shadow_v1` content id;
* the package-model id;
* the seeds and `B`;
* the sha256 of every candidate's score vector and of the cohort id list.

The manifest is committed and pushed **before Stage 2**. Its commit SHA is recorded.

### 12.2 Stage 2 — unblind, once

Stage 2:

1. checks the §6.3 preconditions;
2. joins outcomes;
3. verifies that the score-vector hashes equal the manifest's;
4. computes §7–§11 exactly once;
5. writes `docs/valuation/idp_accuracy/evidence/g_backtest_2026w1_6.json` (aggregates and public NFL names only)
   and `G_RESULTS.md`, both citing the preregistration and Stage 1 SHAs.

### 12.3 After unblinding

* **A bug found after unblinding** is fixed and re-run. Both runs are published, the original is the result of
  record, and the fix is a named deviation.
* **No re-run** with a changed threshold, cohort, window, variant set or candidate definition is ever reported as
  this experiment.
* **Privacy.** Committed evidence carries no manager, team, owner or roster identifiers, no raw Sleeper league id
  and no per-team roster listing. Hypothetical trades and roster moves are reported in aggregate. Example trades
  name public NFL players only, never a team. Per-team detail stays in the gitignored research cache.

---

## 13. Claims rules

### 13.1 What may be concluded

* **Within-position result.** One sentence of this form, and only this form: *"On 2026 regular-season weeks 1–6,
  for veteran players with prior-season production (no rookies), at a point-in-time cutoff before week 1, candidate X
  ordered realized marginal best-ball lineup contribution within positions better / worse / indistinguishably from
  the served market board, by Δ1 = … (95% CI …, Holm-adjusted p …)."* The cross-position axis is stated the same way.
* **Level direction.** The IDP level diagnostic (§9.3) may be stated as near-term evidence. Example: *"the served
  board overrated defenders in X% of the cross pairs it got wrong"*. It is evidence about **near-term league
  utility**, not about dynasty trade value.
* **Positional detail.** Per-position statements are allowed only where F2 rejects after Holm. Elsewhere,
  per-position numbers are descriptive.
* **Carry forward.** An `advance_retrospective` candidate may be carried to a confirmatory preregistration (§13.3).

### 13.2 What may not be concluded

* **No dynasty claim.** Nothing about multi-season dynasty value: aging, development, durability, role security,
  rookie outcomes or future discounting. The target is six weeks. A projection-built candidate is favoured by
  construction on a near-term production target, exactly as the fair-value preregistration says of its own
  secondary ROS metric. The market champion prices years, not six weeks. "Beats the market on six weeks" does
  **not** mean "is a better dynasty value".
* **Not out-of-sample.** No "out-of-sample" or "validated" language. The label is `retrospective_point_in_time`
  (§1, §4.7).
* **Correlated wins are not three confirmations.** A, C and D winning together is not three independent
  confirmations (§4.7).
* **No scale or production change.** Nothing about calibration to the 1–9999 scale. No served value, anchor, IDP
  ceiling, source weight, Hill curve, package model, fairness band or trade recommendation changes on this result.
* **Nothing about rookies**, kickers or picks. They are not in the cohort.
* **No archetype claim.** Interior DL and CB are unavailable (§11).
* **No individual-player claim.** A player's six-week outcome is dominated by noise and injury. Failure-case lists
  illustrate patterns. They do not grade players.
* **Not "the market is right" either.** A null result is not evidence that the market level is correct. It may be
  low power over six weeks.
* **The injury asymmetry.** Injury status at the cutoff is not used (§2.3). The champion's market knew about
  preseason injuries and the projection-built candidates did not. Any result favouring the champion may partly
  reflect that.
* **No setting of fair-value fields.** Nothing here sets or informs any TO-FREEZE field of the fair-value
  preregistration (§14).

### 13.3 What six weeks can and cannot support

* **Can.** Detect large near-term ordering differences among established players. Detect a gross offense-versus-IDP
  level bias in near-term utility. Expose failure modes.
* **Cannot.**
  * **Small differences.** Effects at or below the §8.1 thresholds may be undetectable. The power note and the
    noise ceiling say how far.
  * **Generalization.** No generalization to other seasons. One season is one draw of league environment, and the
    player bootstrap does not sample it.
  * **Thin positions.** Stable conclusions at a position with small `n_p`.
  * **Confirmation.** Anything the long dynasty horizon requires. Confirmation needs a new preregistration whose
    window starts after that preregistration's commit, and the forward multi-season validation stays required on
    top of that.

---

## 14. Interaction with the fair-value preregistration (not edited)

* That record's holdout is TO-FREEZE, expected to be the 2026 and 2027 seasons, examined once, with thresholds not
  yet frozen. Running this experiment reveals how `league_fair_value_v1_shadow` performs on part of the 2026
  season **before** those thresholds are frozen.
* So, binding here: (1) no result of this experiment may be used to choose any of its TO-FREEZE values; (2) the
  commit that freezes it must disclose that this experiment ran and what it found for B.
* Whether 2026 can still serve as a clean holdout season for `league_fair_value_v1` once this runs is an **owner
  question**. It is raised here, not decided.
* Its owner preconditions (`projectionUtilityInDynastyRuling`, `canonicalIdentityArchitecture`) remain unrecorded.
  Nothing here records them.

---

## 15. Frozen parameters (machine-readable twin of §2–§10)

```json
{
  "preregistration": "idp_accuracy_G_v1",
  "label": "retrospective_point_in_time",
  "branchBase": "f64b16fbfc48f538b596f0403de3920cd5e87a6b",
  "league": "dynasty_main",
  "season": 2026,
  "windows": {
    "W0": {"role": "primary", "originBeforeWeek": 1, "outcomeWeeks": [1, 2, 3, 4, 5, 6]},
    "Wa": {"role": "stability", "originBeforeWeek": 1, "outcomeWeeks": [1, 2, 3]},
    "Wb": {"role": "stability", "originBeforeWeek": 4, "outcomeWeeks": [4, 5, 6]}
  },
  "cutoff": {
    "archive": "latest exports/archive generation strictly before K_w",
    "instant": "g(A*_w)",
    "knowledgeCutoff": "K_w minus 1 second",
    "reader": "src.history.asof.batch_known_before",
    "maxAgeDays": null
  },
  "candidates": {
    "champion": "served rankDerivedValue via ledger canonical_board at C_w",
    "A": "BDVM balanced DV, tie-break signed fpg-R; tier A-real else A-proxy (clean rebuild)",
    "B": "league_fair_value_v1_shadow, config unchanged; degenerate => not_evaluable",
    "C": "mu - D1_threshold(pi(i)) via replacement_shadow",
    "D": "E[league-average marginal best-ball contribution], identity transform, league points/week",
    "R0": "mu (reference, outside all families)"
  },
  "positions": ["QB", "RB", "WR", "TE", "DL", "LB", "DB"],
  "offense": ["QB", "RB", "WR", "TE"],
  "idp": ["DL", "LB", "DB"],
  "minNPerPosition": 20,
  "minQualifyingPositionsF1": {"total": 5, "offense": 3, "idp": 2},
  "minNPerPopulationCross": 50,
  "primaryOutcome": "LAMBC_points_per_week_cutoff_rosters",
  "secondaryOutcome": "realized_ppg",
  "primaryMetric": "within_position_spearman_delta_vs_champion_lambc_2026w1_6",
  "positionPooling": "equal_weight",
  "crossMetric": "offense_vs_idp_pair_concordance_delta",
  "elite": {"perPositionTop": 12, "pooledTop": 36},
  "bootstrap": {
    "B": 2000,
    "seed": 20261026,
    "generator": "numpy.random.Generator(PCG64)",
    "unit": "player",
    "stratifiedBy": "position",
    "paired": "across all candidates and metrics",
    "interval": "percentile_95_two_sided",
    "pValue": "two_sided_from_bootstrap_tails_plus_one"
  },
  "simulationD": {
    "weeks": 200,
    "seed": 20261027,
    "availabilityPseudoGames": 4,
    "minOwnResiduals": 6
  },
  "holm": {
    "alpha": 0.05,
    "F1": "Delta1_c and Delta2_c for c in E (max 8)",
    "F2": "Delta_rho_{p,c} for 7 positions x E (max 28)",
    "F3": "Delta3pos_c and Delta3pool_c for c in E (max 8)"
  },
  "minimumMeaningfulEffect": {
    "Delta1_withinSpearman": 0.05,
    "Delta2_crossConcordance": 0.02,
    "Delta3_elitePrecision": 0.0833
  },
  "regressionGuards": {
    "perPositionSpearmanPointFloor": -0.10,
    "crossFloorForWithinAdvance": -0.01,
    "withinFloorForCrossAdvance": -0.02
  },
  "coreStabilityVariants": ["S1", "S2", "S3", "S4", "S5", "S6"],
  "tradeExamples": {"perCategoryMax": 150, "sampleSalt": "idp-g-v1", "fairnessRule": "geom_q078_v1 + fairness_bands_v2 fair band"},
  "promotes": false
}
```
