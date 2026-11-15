# IDP accuracy, Lane F: the candidate set, and what a per-scope quantile match can and cannot correct (2026-10-26)

**Status: SHADOW RESEARCH.** Nothing here changes a served value, rank, flag, source weight, anchor or behaviour. Candidate D is not
imported by any production module (`tests/league_valuation/test_isolation.py` passes unchanged). Every artifact carries `promotes: false`.

**Authority:** `docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md` section 9 (cross-position value) and section 11 (independent
backtest), under its section 13 production-safety rules.
**Experiment:** `docs/valuation/idp_accuracy/G_PREREGISTRATION.md` (frozen at `4c53736fb`, blob `a60ae89c8`). Results: `G_ACCURACY.md`.
**Code:** `src/league_valuation/cross_position.py` (candidate D), `scripts/idp_accuracy/backtest.py`.
**Tests:** `tests/league_valuation/test_cross_position.py`, `tests/idp_accuracy/test_backtest.py`.
**Evidence (all blind-stage, no outcome in any of them):** `evidence/g_stage1_manifest.json`, `evidence/g_stage1_scores.json`,
`evidence/f_structural_level_invariance.json`. Blind-stage commit `127149899`, code pin `863691324`.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## 0. Summary

1. **Five candidates plus a reference were fixed before any outcome was read** (section 1). Three are evaluable on the cutoff board:
   A (BDVM league-scored fundamental utility, proxy tier), C (corrected replacement and lineup utility) and D (new, this lane). The
   served-market champion is the comparator. B (`league_fair_value_v1_shadow`) is **not evaluable** here: with a proxy-only A every one of
   its 1,067 rows is excluded and it returns the market value exactly.
2. **Candidate D** is the expected league-average marginal best-ball contribution, in expected league points per week, built from the
   league's own scoring card, lineup slots and the twelve cutoff rosters, and **from no market input at all** (section 2). It is an identity
   transform on the points scale and is uncalibrated by design (directive section 9). On the cutoff board it ranks Myles Garrett first of 651
   veterans (12.2 points per week; champion rank 126) and puts 9 defenders in its own top 36 against 1 for the champion.
3. **The F finding (section 3): the fair-value challenger's per-scope quantile matching structurally cannot correct an overall
   IDP-versus-offense level error.** It permutes (at full strength) or interpolates between values of the same scope, so each scope's
   multiset of values, and with a uniform strength its geometric mean, never moves. A constructed example and a measurement on two real boards agree
   exactly. What it *can* do under an adversarial order is flatten one scope's top end, which is a distortion, not a level correction.

## 1. The candidates, before any outcome

| id | what it is | scale | inputs | status in this run |
|---|---|---|---|---|
| champion | the canonical market value, `rankDerivedValue` | 1-9999 | the cutoff archive's own raw payload rebuilt by `build_api_data_contract` at HEAD (`champion_methodology_at_head`) | evaluable; **champion-rebuilt**, because the ledger read returned 0 of 834 (no `data/temporal_ledger.sqlite` exists here) |
| A | BDVM balanced-strategy discounted dynasty value, with the signed season-0 `fpg - R` as the tie-break | BDVM trade scale | A-proxy: BDVM's reconstructed baseline from nflverse 2023-2025 plus the play-by-play supplement and rookie draft-slot priors, at the cutoff date | evaluable; 805 players priced |
| B | `league_fair_value_v1_shadow` | 1-9999 | the champion as anchor, A as utility evidence | **not evaluable**: `degenerate_market_exact` (0 of 1,067 rows moved; evidence `partial` for 805 players, `unavailable` for 40) |
| C | `mu - R_p`, projected league ppg over the D1 starter threshold | league ppg | BDVM's consensus projection `mu`; Lane B's D1 (median over the 12 rosters of the weakest started player at the position, FLEX and SUPER_FLEX competing) | evaluable |
| D | expected league-average marginal best-ball contribution | league points per week | `mu`, 2025 host-scored games (availability, residuals), the 12 cutoff rosters, the exact lineup solver | evaluable |
| R0 | `mu` itself | league ppg | the shared projection prior | reference, outside every test family |

All of A, C, D and R0 descend from the same projection prior `mu`, and champion and B descend from the same market. Agreement among A, C and
D is **one body of evidence about `mu` and three mechanisms, not three confirmations** (preregistration section 4.7).

D1 for the weakest started player at each position (league ppg, from `mu`): QB 19.03, RB 12.12, WR 10.82, TE 8.44, DL 10.82, LB 11.42, DB 10.67.

### 1.1 What the candidates say about each other, before any outcome

Computed from the committed blind-stage score vectors (cohort of 651; no outcome involved). Equal-weight mean over the seven positions of the
within-position Spearman correlation between two candidates:

| | champion | A | C | D |
|---|---|---|---|---|
| champion | 1 | 0.69 | 0.72 | 0.68 |
| A | | 1 | 0.59 | 0.48 |
| C | | | 1 | 0.82 |
| D | | | | 1 |

C and R0 are the same ordering within a position (rank correlation 1.00) apart from hybrid eligibility, as the preregistration discloses: C's
within-position result is a test of `mu`, and its distinctive content is its cross-position level. The number of defenders each candidate
places in the top 36 and top 100 of the 651-player cohort (defenders are 47.9% of the cohort):

| | champion | A | C | D | R0 |
|---|---|---|---|---|---|
| IDP in own top 36 | 1 | 4 | 7 | 9 | 0 |
| IDP in own top 100 | 12 | 25 | 31 | 32 | 17 |

The ratio of the mean of the top 12 offensive players to the mean of the top 12 defenders is 2.03 for the champion (value units), 1.70 for C
(points over replacement) and 1.21 for D (points per week). The three are on different scales and are **not** comparable as measures of one
"level bias"; they only show that the candidates disagree about the cross-position exchange rate. Which of them orders offense-versus-IDP pairs
the way realized lineup contribution did is the question `G_ACCURACY.md` answers.

## 2. Candidate D

### 2.1 Definition

```
V_i = (1/S) sum_s (1/12) sum_t [ L(R_t U {i}, x_s) - L(R_t \ {i}, x_s) ]
```

* `L(R, x)` is the optimal best-ball lineup total of roster `R` under weekly scores `x`, from the exact solver `src.ros.lineup.solve_optimal_assignment`
  (injected through the existing `LineupPort`; there is no fallback solver and no greedy path).
* `R_t` is team `t`'s cutoff roster. For a player on `R_t` the union is `R_t`; for one not on it the difference is `R_t`. The twelve teams are
  weighted equally.
* Each simulated week draws every player independently: played ~ Bernoulli(`a_i`); if played, the score is `mu_i + eps`, with `eps` drawn
  uniformly from the player's own residual set `E_i = {y_ik - ybar_i}` when it has at least six residuals, otherwise from the pooled residual set of
  his cutoff position; if not played, 0.
* `a_i = (g_i + 4 * abar_p) / (G_i + 4)`: `g_i` games played and `G_i` games his NFL team played in 2025 regular-season weeks 1-18; `abar_p` the
  cohort mean of `g/G` at the position; 4 is a declared PRIOR pseudo-count (a quarter-season).
* `S = 200` simulated weeks, seed `20261027` on a stream separate from the bootstrap's.

### 2.2 What makes it different from C, and from what already exists

* **C is mean-based with one threshold per position and no variance.** D has no replacement constant at all: replacement emerges from who is on
  each of the twelve rosters, including which of a team's own players a newcomer would displace, so position scarcity and depth enter through the
  rosters. Its best-ball volatility premium is the contrast between D and the ablation D(sigma = 0), reported in `G_ACCURACY.md` as a stability variant.
* **`src/bestball/marginal.py` answers a different question** (value over the best free-agent replacement, for one roster, with an explicitly
  labelled replacement scenario) and `tests/bestball/test_import_graph.py` forbids importing it from `scripts/`. It was read, not used.
* **No market input, by construction.** D is never mapped onto the 1-9999 scale, never fitted to a price, never anchored to IDP Trade Calculator or
  Draft Sharks and never quantile-matched to a board. Directive section 9 says that where no independently justified transform into 1-9999 exists the
  estimate stays uncalibrated; D is uncalibrated by design and is compared with the other candidates **only through ranks**. A unit test pins that
  doubling every projected point doubles D (`test_value_is_an_identity_transform_on_the_points_scale`).

### 2.3 Rules that hold

* **Missing is never zero.** A rostered player with no `mu` (a 2026 rookie whose only projection is a draft-slot prior, or any player with no
  projection) is UNKNOWN in the environment: not assignable, his slot reported unfilled. 120 rostered players were unknown at the cutoff. 44
  players with a `mu` could not be simulated at all because no team schedule exists for them (`no_availability`) and are absent from D, never given a 0.
* **Reproducible in parallel.** Each simulated week owns an independent child stream `PCG64(SeedSequence([20261027, week]))`, so the result is a function
  of the seed alone: one process and many give the same numbers bit for bit (`test_parallel_d_equals_serial_d_exactly`).
* **Monte-Carlo error is reported, ties are not broken.** The median standard error over the cohort is 0.32 points per week (90th percentile 0.54).
* **Declared simplifications.** Draws are independent across players and weeks (no game-script correlation); the roster cap is ignored when a player is
  added; injury status at the cutoff is not used (it cannot be reconstructed point-in-time, which favours the market comparator).

### 2.4 Tests (`tests/league_valuation/test_cross_position.py`, `tests/idp_accuracy/test_backtest.py`)

The lineup port is checked against an independent brute-force best-ball optimum on tiny leagues; a hand-computed two-team league fixes D to
2.5 and 5.5 points; availability bounds and the pseudo-count's pull toward the position mean; the pooled residual rule; draw order independent of
who played; chunk invariance; the sigma-zero and own-team-only ablations; fingerprints. The cached-eligibility solver used for speed returns the
owner's own assignment byte for byte over 60 random full rosters.

## 3. The F finding: per-scope quantile matching cannot correct an overall IDP-versus-offense level error

### 3.1 The mechanism, from the code

`src/league_valuation/challenger.py` splits the board into two populations, OFFENSE (QB RB WR TE) and IDP (DL LB DB), and handles each separately:

```
m_i   = the canonical value at the same rank in the SAME population's descending list of canonical values   (quantile_match)
fair_i = exp( (1 - k_i) ln v_i + k_i ln m_i )                                                         (interpolate)
```

Both `v_i` and `m_i` are members of one scope's own value list. Consequently:

1. at `k = 1` for every row the scope's value list is **permuted**: its multiset is exactly preserved, so every statistic of the scope's values
   (mean, median, value at a fixed rank, top-12 mean) is unchanged;
2. at a uniform `k < 1` each row is replaced by a geometric blend of two members of the same scope, and the **sum of log values of the scope is
   exactly preserved** (the `logDrift` the diagnostics report is 0);
3. a utility tie block is replaced by the log-mean of the value block it spans, which preserves the log-sum but not the exact multiset (so the
   measurement below breaks ties first);
4. for IDP, a depth fan-out gate forces `k = 0` for the whole scope unless the utility-versus-market disagreement is stable across pool depth.

Nothing in this construction ever compares an offensive value with a defensive one. The cross-scope **exchange rate** is whatever the market
supplied; the utility evidence enters only as an **order inside a scope**.

### 3.2 A constructed example

Offense values 9,000 / 7,500 / 6,000 / 4,500 / 3,000 / 1,500 and defender values exactly half of them at every rank, 4,500 / 3,750 / 3,000 / 2,250 /
1,500 / 750: the whole IDP scope is priced at half the offense scope. Show the model evidence that is as favourable to defenders as evidence can be:
a utility signal that says **every defender is worth more than every offensive player**, and that also reverses the defenders among themselves.

* The cross-scope statement is never read: offense stays 9,000 ... 1,500 and the defender list stays 4,500 ... 750, so offense-over-IDP at every rank
  remains **2.0**.
* The reversal inside IDP is honoured (the bare quantile match maps defender 2001 from 4,500 to 750, 2002 from 3,750 to 1,500, ... 2006 from 750 to
  4,500), but the **set** of defender values is the same set. The level did not move.

(`tests/league_valuation/test_cross_position.py::test_fair_value_cannot_correct_an_idp_level_error_by_construction` pins the general form on random
boards: five different utility orders, the multiset and log-sum equal before and after, and the 1.5x level gap still there.)

### 3.3 The measurement on two real boards

`evidence/f_structural_level_invariance.json`. The challenger was run unchanged on the cutoff board and on Lane A's pinned board (2026-10-25
archive, sha256 `50fb251a...`), under three utility orders chosen to be as unlike a considered signal as possible (candidate D's order, a seeded random
permutation, and the market order reversed) and two configurations (the shipped one, `kMax = 0.25`, and `kMax = 1` at full quality). Evidence is admitted
by construction, so this measures the model, not BDVM's inputs. Offense is 411 rows and IDP 304 on the cutoff board.

Cutoff board, before: offense mean 3,053.7, IDP mean 1,922.3, top-12 means 9,084.1 and 4,687.9 (ratio **1.938**), 1 defender among the 36 highest values.

| order | config | multiset (OFF / IDP) | offense top-12 | IDP top-12 | ratio | IDP in top 36 | log drift (OFF / IDP) |
|---|---|---|---|---|---|---|---|
| D | `k = 1` | unchanged / unchanged | 9,084.1 | 4,687.9 | 1.938 | 1 | 0 / 0 |
| random | `k = 1` | unchanged / unchanged | 9,084.1 | 4,687.9 | 1.938 | 1 | 0 / 0 |
| market reversed | `k = 1` | unchanged / unchanged | 9,084.1 | 4,687.9 | 1.938 | 1 | 0 / 0 |
| any of the three | bare quantile match, gate bypassed | unchanged / unchanged | 9,084.1 | 4,687.9 | 1.938 | 1 | n/a |
| D | shipped | changed (OFF) / unchanged | 8,750.0 | 4,687.9 | 1.867 | 1 | 0 / 0 |
| random | shipped | changed (OFF) / unchanged | 6,965.8 | 4,687.9 | 1.486 | 2 | 0 / 0 |
| market reversed | shipped | changed (OFF) / unchanged | 5,242.4 | 4,687.9 | 1.118 | 10 | 0 / 0 |

Lane A's pinned board gives the same pattern (before: ratio 1.838, 1 defender in the top 36; every `k = 1` and bare row identical to the
before row; shipped, random order: ratio 1.417, 4 defenders; shipped, reversed order: ratio 1.080, 8 defenders).

Hypothetical level errors built into the cutoff board (the whole IDP scope priced 25% too high, or 20% too low) come out of the bare quantile match
**identical** to how they went in: ratio 1.550 and 2.422, 4 and 0 defenders in the top 36, IDP mean 2,402.9 and 1,537.9.

### 3.4 What this does and does not say

* **It cannot correct a level error.** A scope's location (its multiset at full strength, its geometric mean at any uniform strength) is invariant
  to whatever utility evidence it is shown. An IDP scope priced too low (or high) relative to offense stays that way exactly.
* **It does not say the model is inert.** It reorders players inside a scope, and a reordering changes *which* defender sits above *which* offensive
  player, so its offense-versus-IDP pair concordance can change. It does not change how many defenders clear a given value.
* **The shipped rows that move cross-scope statistics are a distortion, not a correction.** With the IDP gate forced to `k = 0` the only scope that
  moves is offense, and under a poor order it moves by flattening its own top end (top-12 mean 9,084 to 5,242 under the reversed order), which
  *raises* the defender count in the top 36 only because offense stars are deflated. The geometric mean of the scope is unchanged. That is a
  spread effect of a bad order, not evidence about level.
* **A level correction needs a cross-scope transform**, i.e. an exchange rate between a defensive point and an offensive point. The fair-value challenger
  has none by design (no centring constant exists, the directive's ±25% clamp is unused). Candidates C and D supply one on the league-points scale; whether
  either orders cross pairs better than the market is the experiment in `G_ACCURACY.md`, over six weeks only and not as a dynasty claim.
* **Nothing here edits the fair-value preregistration or sets any of its TO-FREEZE fields.**

## 4. Regenerate and test

```
python scripts/idp_accuracy/backtest.py stage1          # blind: needs the Lane A Sleeper cache and nflverse downloads
python scripts/idp_accuracy/backtest.py stage2          # unblind once; refuses unless the stage 1 commit is pushed and unchanged
python -m pytest tests/league_valuation tests/idp_accuracy -q
bash scripts/format_python_changes.sh
```

## 5. Limits and unresolved

* The champion is the **rebuilt** market method on point-in-time inputs, with source freshness weighting unavailable (every source votes at full base
  authority). It is not the board users saw, and no served board exists for the cutoff in this repository.
* A is the proxy tier. No box snapshot with a creation stamp at or before the cutoff exists here, so the real-projection stability variants cannot run.
* The structural finding is about the model's construction and is exact; its numeric illustration depends on the cutoff board and on the orders I chose.
* **UNRESOLVED:** whether any cross-scope transform should ever be adopted is an owner question and is not raised by this lane; nothing here sets a served value.
