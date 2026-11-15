# IDP replacement anchors and league-specific IDP scoring (2026-10-20)

**Status: RESEARCH — COMPLETE (investigation B); independent-review fixes applied.** Nothing in this
workstream changes a value, a source weight, a vote, a curve, a replacement anchor or any served behaviour. Every alternative below was computed in shadow
and fed to the canonical consumers' own pure functions; nothing was written back.

**Authority:** `docs/owner/LOW_VALUE_ASSET_OWNER_DECISIONS_2026-10-20.md` §3. Prior evidence it extends (not
redoes): `docs/valuation/LOW_VALUE_ASSET_RESEARCH_2026-10-20.md` §6 and
`evidence/low_value_assets_2026-10-20/idp_anomaly.json`.

**Evidence:** `evidence/idp_replacement_2026-10-20/idp_replacement.json`, produced by
`scripts/idp_replacement_research.py` (aggregate-only; NFL player names for illustrative rows; no league, user,
roster, transaction or player ids; no team or manager names; checked by `assert_aggregate_only`).

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## 0. Owner summary

**Verdict: replacement methodology.** The waiver anchor is a measured, actionable methodology defect. A
league-specific *valuation* defect is **not established**: the DB scoring mismatch is an unconfirmed hypothesis,
and the headline IDP correlation gap is explained by range restriction and IDP noise.

1. **Replacement methodology: the main, actionable cause of the anomaly.**
   - The waiver anchor is the single highest-valued unrostered player at each position.
   - It counts injured players and non-producing rookies. In this league that matters: it is best ball with no IR
     and no taxi, so an injured player fills one of 58 spots and scores nothing.
   - Value is not shown to order the IDP wire. Among unrostered players, the rank correlation between value and
     points per game is not distinguishable from zero (DL 0.09, LB −0.21, DB 0.21; n 36 / 21 / 27, CIs about
     ±0.34 to ±0.41).
   - The worst case is DB. The anchor (2,156, a player listed Out) sits above **26 of the 35** DBs in the
     value-optimal lineups.
2. **League-specific valuation at DB: an unconfirmed hypothesis, not a finding.**
   - This card pays big plays: one pass defended is worth 3.98 solo tackles, one tackle for loss 3.19.
   - Only one card-alignment test points to a DB mismatch, and it is **in-sample**: the pre-season board (built after the 2025
     season) against 2025 production, paired difference −0.134 [−0.239, −0.041]. Both out-of-sample 2026 tests
     have CIs spanning 0 (−0.078 [−0.178, +0.015]; −0.064 [−0.149, +0.021]).
   - Multiplicity: that is 1 of 12 alignment cells in the hypothesised direction, uncorrected. The in-sample IDP
     and DL cells are nominally significant the *opposite* way (+0.065, +0.048). After a Holm correction across
     the 12 cells nothing is significant (DB adjusted p 0.084).
   - Confound: big-play points are much less stable year to year than tackle points (IDP 0.35 vs 0.67; DB 0.24
     vs 0.38). At DB, the tackle-heavy reference card's 2025 production predicts *this card's* 2026 production at
     least as well as this card's own 2025 production does (0.374 vs 0.309; difference +0.066 [−0.059, +0.195]).
     A board that rationally discounts noisy big plays would therefore show the same signature in the alignment
     test and in the tackle-share residual (ρ −0.56) without any mis-valuation.
   - For the same DBs, 2025 production under this card does not predict 2026 better than pre-season value
     (0.323 vs 0.342).
3. **The headline 0.45 vs 0.77 gap reflects range restriction and IDP noise; it does not establish a valuation
   defect.**
   - Range restriction: across all IDPs with both seasons, 2025 → 2026 ppg correlates at 0.682 (n 568). Among
     the 229 priced pre-season it is 0.413 (offense: 0.824 → 0.738). Priced IDPs are a narrow slice of
     production, so every predictor's correlation is compressed.
   - Noise: in that priced set, pre-season value (0.402) and 2025 league-scored production (0.413) predict 2026
     equally; big-play scoring, which this card weights heavily, is the least repeatable component.
   - Pre-season, no single IDP source beats the consensus. On today's in-season board idpTradeCalc's point
     estimate is above it (IDP 0.501 vs 0.474, difference +0.027 [−0.016, +0.071]; DB 0.439 vs 0.384,
     +0.055 [−0.031, +0.135]), not significantly except at LB (+0.071 [+0.001, +0.140], uncorrected).
   - BDVM's league-scored projection does not beat the consensus significantly (IDP 0.44 vs 0.39, difference
     CI [−0.07, +0.16]), and it is built from 2023–25 realized PPG under this card, so it largely overlaps the
     last-season-production predictor rather than adding an independent one.
   - None of this rules a valuation defect out either; it means none is demonstrated.

**Recommendation (§9):**
- **Methodology:** consolidate, do not add. Route the displacement anchor through the canonical replacement owner
  (LI-5's waiver tier, which is exactly the "banded top three" rule tested here) with a health filter, as part of
  the C2-REPL-01 consolidation. Gated, requires owner approval, and sequenced after the forced-drop correction
  (investigation A).
- **Scarcity:** coupled to the above. Feeding free agents to LI-5 is what activates the currently inert
  scarcity multiplier (1.0 everywhere), so it is either a separately flagged effect of the same PR or an
  explicitly later step, and an owner decision either way.
- **DB:** evidence collection only, with pre-registered out-of-sample, multiplicity-corrected tests that must
  beat the rational-discounting explanation. No value, weight or vote change.

## Contents

1. Inputs and validation
2. Item 1: injured and non-producing free agents in the anchors; alternative anchors in shadow
3. Item 2: availability and eligibility of waiver replacements
4. Item 3: this league's IDP scoring card
5. Item 4: positional scarcity and roster requirements
6. Item 5: the 0.45 vs 0.77 correlation, tested for robustness
7. Item 6: does the canonical IDP consensus reflect this league's scoring?
8. Item 7: how the anchor moves each consumer (code trace and shadow)
9. Conclusion, recommendation, gates and what must not be done
10. Limits and UNRESOLVED

## 1. Inputs and validation

| input | detail |
|---|---|
| today's board | `exports/archive/dynasty_export_20261020_052241.zip`, built with today's code through `shadow_replay.build_context`, which reproduced the prior lane's anchors exactly at the evidence commit `b8008c2a4` (the sha256 in the JSON pins the input archive only). `build_api_data_contract` also reads the working tree's tracked `data/` and `CSVs/`, which refresh every two hours: re-running on a later HEAD with the same archive drifts the anchors by up to about 3% (DB A0 2156 to 2146, LB 2149 to 2208, RB 1626 to 1660) with conclusions unchanged (independent review, 2026-10-21). Treat every figure as of that commit |
| pre-season board | the served 2026-08-25 golden board (`data/ops/v1-27/…`). Per-source pre-season ranks come from a today's-code replay of the 2026-08-25 archive. Ranks are source inputs, so methodology drift does not move them. |
| production | Sleeper weekly stat lines for 2026 weeks 1–6 and 2025 weeks 1–18. Both seasons are scored under the current card by the canonical scorer (`compute_weekly_points`). |
| scorer check | 3,299 / 3,299 player-weeks match Sleeper's own points (max difference 0.004) |
| rosters and rules | live Sleeper rosters (2026-10-20 snapshot; the review re-run reused it via `--roster-max-age-s`), league settings and transactions (aggregate counts only) |
| BDVM | `fetch_and_build_baseline`: 2023–25 nflverse realized PPG under this card, plus rookie draft-slot priors. `run_valuation` was run in memory and no snapshot was written. It is a league-scored pre-season fundamental, so 2026 production is out of sample for it. |
| statistics | Spearman rank correlation; 95% CIs from 1,000 player-level bootstrap resamples. Differences use paired bootstrap on the same players, or independent bootstrap for offense vs IDP. Paired differences also carry a two-sided bootstrap p-value; the 12-cell card-alignment family is Holm- and Bonferroni-corrected (§7.1). |

## 2. Item 1: injured and non-producing free agents in the anchors

### 2.1 Who sets the anchor today

The rule lives in `src/draft/displacement.py:276` (`waiver_values_by_position`): the best unrostered
`rankDerivedValue` at the position. Today's anchors (live rosters):

| pos | anchor | set by | status | 2026 ppg |
|---|---:|---|---|---:|
| QB | 1,923 | Drew Allar | Out, rookie | — |
| RB | 1,626 | Isiah Pacheco | IR | — |
| WR | 1,802 | Jerry Jeudy | healthy | 5.6 |
| TE | 2,061 | Ja'Tavion Sanders | Out | — |
| DL | 1,918 | Derrick Moore | rookie | 1.7 |
| LB | 2,149 | Kaleb Elarms-Orr | rookie | 2.8 |
| DB | 2,156 | Antoine Winfield | Out | 8.4 |

**What the top 10 unrostered by value look like:**

| pos | injured or inactive now | fewer than 3 games | dropped by a manager this season | healthy and startable (ppg ≥ P10 of production starters) |
|---|---:|---:|---:|---:|
| QB | 7 | 9 | 9 | 0 |
| RB | 4 | 7 | 9 | 0 |
| WR | 2 | 4 | 7 | 0 |
| TE | 4 | 5 | 7 | 0 |
| DL | 5 | 2 | 6 | 0 |
| LB | 2 | 3 | 8 | 0 |
| DB | 6 | 3 | 7 | 1 |

- Six of the seven anchors are set by an injured player or a non-producing rookie. WR is the exception.
- Most of the top-valued free agents were dropped by a manager this season.
- Among unrostered players, the relationship between value and production at IDP is not distinguishable from
  zero (Spearman: DL 0.09 [−0.25, 0.43], n 36; LB −0.21 [−0.58, 0.24], n 21; DB 0.21 [−0.21, 0.60], n 27). The
  samples are small, so this is an absence of evidence that value orders the wire, not proof that it cannot. WR
  is the only position where value orders the wire (0.45 [0.07, 0.72], n 27).
- At DB, the highest-scoring healthy unrostered player (13.7 ppg) ranks **34th of 37** by value among
  board-priced unrostered DBs (`valueRankOfTopPpgHealthyFA`). The best-valued healthy DB who clears the P10
  startable bar ranks 2nd (`valueRankOfBestProducingHealthyFA`; Keionte Scott, 1,917, who sets both A1 and A4).

### 2.2 Alternative anchors, in shadow

"Canonical starters below" counts the DBs or DLs in the 12 value-optimal lineups that are valued below the
anchor (the prior lane's anomaly count). "Production starters below" counts the same for lineups re-solved on
season-to-date points.

**DB** (the anomaly):

| definition | anchor | canonical starters below | production starters below | rostered above |
|---|---:|---:|---:|---:|
| A0 served: best unrostered | 2,156 | 26/35 | 30/34 | 9/100 |
| A1 best healthy | 1,917 | 19/35 | 28/34 | 17/100 |
| A1s best healthy, strict rule | 1,917 | 19/35 | 28/34 | 17/100 |
| A2 3rd-best healthy | 1,436 | 3/35 | 14/34 | 54/100 |
| A3 LI-5 banded top-3, all | 1,994 | 23/35 | 29/34 | 12/100 |
| **A3h LI-5 banded top-3, healthy** | **1,754** | **12/35** | 22/34 | 28/100 |
| **A3hs LI-5 banded top-3, healthy, strict rule** | **1,754** | **12/35** | 22/34 | 28/100 |
| A4 best production-qualified (P10 bar) | 1,917 | 19/35 | 28/34 | 17/100 |
| A4b best production-qualified (P25 bar) | 229 | 0/35 | 0/34 | 100/100 |
| A5 LI-5 best-ball starter (rosters) | 1,384 | 2/35 | 10/34 | 64/100 |
| D board price of wire-level production (diagnostic) | 1,588 | 9/35 | 18/34 | 36/100 |

**DL and LB:**

| definition | DL anchor | DL canonical starters below | LB anchor | LB canonical starters below |
|---|---:|---:|---:|---:|
| A0 served | 1,918 | 7/37 | 2,149 | 6/35 |
| A1 best healthy | 1,918 | 7/37 | 2,149 | 6/35 |
| A2 3rd-best healthy | 1,740 | 1/37 | 1,793 | 3/35 |
| **A3h banded healthy** | **1,812** | 3/37 | **1,946** | 3/35 |
| **A3hs banded healthy, strict rule** | **1,812** | 3/37 | **1,946** | 3/35 |
| A5 best-ball starter | 1,668 | 1/37 | 1,628 | 1/35 |
| D board price of wire-level production (diagnostic) | 1,724 | 1/37 | 1,401 | 0/35 |

**Offense** (A0 → A3h; A3hs is identical):

| pos | A0 | A3h | note |
|---|---:|---:|---|
| QB | 1,923 | 1,410 | only five healthy unrostered QBs |
| RB | 1,626 | 1,502 | |
| WR | 1,802 | 1,583 | |
| TE | 2,061 | 1,769 | |

**Two health rules.** A1 and A3h use the prior lane's shadow rule (`low_value_asset_idp_anomaly.is_healthy`),
which treats a missing `status` as healthy when the player has an NFL team. A1s and A3hs use the rule
recommended in §9 (`is_healthy_strict`): an NFL team, an explicit `status` of `Active`, and no unavailable
injury designation, so a missing or unrecognised status is unknown and excluded. In this snapshot the two rules
give **identical anchors at every position**: no board-priced free agent passes one and fails the other
(`healthyLooseButNotStrict` is 0 everywhere), because Sleeper's directory gave every board-priced free agent
an explicit status. The strict rule is still the one to adopt, because the difference only appears when
the feed degrades.

**Reading:**
- **Healthy-only fixes the cause but not the noise.** A1 still leaves 19 of 35 DB starters below the anchor,
  and A1 equals A0 at DL and LB, where the anchors are healthy rookies who do not produce.
- **Healthy and banded (A3h)** is the smallest change that removes most of the anomaly at every IDP position
  while staying a waiver concept. The banding is LI-5's own rule: the mean of ranks 1–3.
- **Production-qualified (A4) is not viable as a served rule.** It is computable in season (season-to-date
  stats exist), so hindsight is not the objection. The objections are:
  - instability: it swings with the bar. At DB a P10 bar sets it at 1,917 and a P25 bar at 229 (one qualifying
    priced free agent, Christian Izien);
  - it is undefined at four of seven positions (QB, RB, WR, LB), because the wire there has no startable
    producer;
  - circular evaluation: its qualifier uses the same weeks 1–6 production as the "production starters below"
    column, so that column flatters A4 by construction.
- **The diagnostic D anchor does not converge with A3h.** It is the board's own price of wire-level production:
  DB 1,588 vs A3h 1,754; DL 1,724 vs 1,812; LB 1,401 vs 1,946. It sits below A3h at all three IDP positions,
  by 166 at DB, 88 at DL and 545 at LB, so it is a direction check, not a corroborating estimate.

## 3. Item 2: availability and eligibility of waiver replacements

**League rules (live):**
- best ball;
- FAAB with a $100 budget and daily waivers, a 1-day clear window;
- **0 IR slots and 0 taxi slots**, with every `reserve_allow_*` off;
- 58 roster spots: 21 starters, 37 bench;
- 11 of 12 rosters at or over the cap (one at 59).

**What that means for availability:**
- **A free agent is effectively always available.** Only one unrostered DB, and nobody at the other positions,
  was dropped within the current waiver window.
- **An injured free agent is not a replacement for a lineup spot.** He costs a roster spot and scores 0 until he
  returns, so "available" and "replacement" are different questions in this league.

**Status of the board-priced unrostered pool:**

| pos | priced unrostered | healthy now | status mix (not healthy) |
|---|---:|---:|---|
| DL | 45 | 34 | IR 7, Out 2, PUP 1, NA 1 |
| LB | 33 | 27 | PUP 1, Out 1, IR 1, plus 3 listed "Active" with no team (1 Questionable counts as healthy) |
| DB | 37 | 23 | Out 8, IR 6 (1 Questionable counts as healthy) |

**Eligibility:**
- The slot rules come from the canonical owner (`slot_eligible_positions`):
  - DL accepts DE / DL / DT / EDGE;
  - LB accepts LB only;
  - DB accepts CB / DB / S.
- There is no IDP flex slot.
- Hybrids on the wire: 3 DL/LB at DL, 4 DL/LB at LB, 1 DB/LB at DB.
- The anchor pool is keyed by board position only, so a hybrid counts toward one position's anchor. The lineup
  solver can still use him in either slot.
- No board-vs-Sleeper position mismatches among free agents.
- Every priced DL and DB free agent has an NFL team; 30 of 33 LB do.

## 4. Item 3: this league's IDP scoring card

**The card (Sleeper keys):**

| stat | points |
|---|---:|
| solo tackle | 1.33 |
| assisted tackle | 0.80 |
| sack | 2.92 (+0.11 per yard) |
| tackle for loss | 4.24 |
| QB hit | 2.12 |
| pass defended | 5.30 |
| interception | 5.30 |
| forced fumble | 4.24 |
| fumble recovery | 3.19 |
| defensive TD | 6.36 |
| safety | 5.30 |
| blocked kick | 5.30 |

- **Price ratios:** one pass defended = 3.98 solo tackles; one TFL = 3.19; one sack = 2.20.
- **The reference card** is a tackle-heavy card authored for this research only. It is no provider's card and no
  recommendation: solo 1.5, assist 0.75, sack 3, TFL 1, QB hit 0.5, INT 3, PD 1, FF 3, FR 2, TD 6. One PD = 0.67
  solos.

**What the card rewards.** Starting pool = 36 per IDP position, 2025 season:

| | DL | LB | DB |
|---|---:|---:|---:|
| mean ppg of the starting pool, this card | 13.5 | 15.2 | 13.0 |
| mean ppg of the starting pool, reference | 7.6 | 11.1 | 9.1 |
| median tackle share of points, this card | 0.26 | 0.56 | 0.46 |
| rank agreement, this card vs reference, top-2× starters (ρ) | 0.91 | 0.83 | **0.62** |

- **IDP is scored like offense here.** The DB starting pool averages 13.0 ppg, about the same as WR (15.0) and
  more than TE (10.5).
- **The card reorders the startable range most at DB.**
  - Gainers are coverage corners: DJ Turner is 64th under this card and 142nd under the reference; Jourdan
    Lewis and Emmanuel Forbes gain similarly. All average about 1 PD per game.
  - Losers are tackle-heavy safeties: Nick Scott is 113th vs 39th, with a tackle share of 0.83.
- **At LB, edge rushers listed as LB gain** (T.J. Watt 4th vs 42nd, Micah Parsons 21st vs 52nd) and
  off-ball tackle LBs lose.
- **Within each IDP position's top-2× pool,** the low-tackle-share tertile outscores the high one under this card
  (DL 13.0 vs 8.8 ppg). Under the reference the order reverses at LB (8.1 vs 10.4) and at DB (7.1 vs 8.9).

## 5. Item 4: positional scarcity and roster requirements

**Demand:**
- Slots are resolved by the canonical owner (`resolve_starter_slots`, source `sleeper_roster_positions`):
  `QB, RB×2, WR×3, TE×2, FLEX×2, SUPER_FLEX, K, DL×3, LB×3, DB×3`.
- That is 36 starters per IDP position league-wide.
- There is no IDP flex, so IDP demand is fixed at 3/3/3. Offense demand flexes with FLEX and SUPER_FLEX.

**Format scarcity:** ppg at twice the starter line divided by ppg at the starter line. Higher means flatter,
so replacement is closer to a starter.

| season | QB | RB | WR | TE | DL | LB | DB |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2025 | 0.60 | 0.41 | 0.46 | 0.30 | 0.71 | 0.71 | **0.89** |
| 2026 (weeks 1–6) | 0.47 | 0.37 | 0.54 | 0.27 | 0.73 | 0.67 | **0.80** |

**Wire depth today** (2026 weeks 1–6, season to date). All healthy unrostered players with at least 3 games,
including players the board does not price:

| pos | healthy unrostered | at least P10 of production starters | at least median starter | 3rd-best free agent / median starter |
|---|---:|---:|---:|---:|
| RB | 29 | 0 | 0 | 0.23 |
| WR | 46 | 0 | 0 | 0.47 |
| TE | 53 | 3 | 0 | 0.35 |
| DL | 159 | 5 | 0 | 0.79 |
| LB | 80 | 0 | 0 | 0.63 |
| DB | 164 | **13** (10 not priced by the board) | 2 | **0.95** |

- **IDP replacement is genuinely close to a starter**, most of all at DB. The wire's third-best healthy DB
  produces 95% of the median production-starting DB.
- The DB anchor (2,156) is therefore at odds with the scarcity in this league's format.
- **Scarcity is low precisely because the wire is productive,** and the wire's productive players are priced near
  the board's floor or not priced at all.

## 6. Item 5: the 0.45 vs 0.77 correlation, tested for robustness

**Value vs league-scored ppg** (players with at least 3 games, all valued):

| comparison | offense | IDP | offense − IDP |
|---|---|---|---|
| today's value vs 2026 ppg (in-season board, hindsight) | 0.774 [0.727, 0.814] | 0.450 [0.360, 0.541] | 0.32 [0.22, 0.43] |
| pre-season served value vs 2026 ppg (no hindsight) | 0.670 [0.602, 0.728] | 0.403 [0.299, 0.495] | 0.27 [0.15, 0.38] |
| pre-season value vs 2025 ppg (does the board reflect last season?) | 0.795 [0.743, 0.836] | 0.605 [0.510, 0.682] | 0.19 [0.09, 0.30] |
| pre-season value vs 2026 ppg, comparable depth (top 2× starters per position) | 0.679 | 0.412 | 0.27 [0.13, 0.40] |

**By position** (pre-season value vs 2026 ppg):

| position | ρ |
|---|---:|
| DL | 0.32 |
| LB | 0.53 |
| DB | 0.33 |
| QB | 0.51 |
| RB | 0.71 |
| WR | 0.70 |
| TE | 0.64 |

**The gap is robust:** it holds with and without hindsight, on rostered players only, at comparable depth,
and against last season.

**Is it the consensus, or IDP itself?**

1. **Reliability of production itself** (odd vs even weeks, Spearman–Brown):
   - 2026 six-week ppg: offense 0.87, IDP 0.78 (DL 0.64, DB 0.77, LB 0.83);
   - 2025 full season: offense 0.94, IDP 0.90.
   - Noise in six-week production explains only part of the gap. Disattenuated, pre-season value vs 2026 ppg is
     offense 0.72 vs IDP 0.46.
2. **Same-player predictors of 2026 ppg** (priced pre-season, at least 8 games in 2025 and at least 3 in 2026):

   | group | pre-season value | 2025 league-scored ppg | ppg − value (paired) |
   |---|---:|---:|---|
   | offense (n 237) | 0.676 | 0.738 | +0.06 [−0.01, +0.13] |
   | IDP (n 229) | 0.402 | 0.413 | +0.01 [−0.09, +0.11] |
   | DL / LB / DB | 0.39 / 0.47 / 0.34 | 0.36 / 0.42 / 0.32 | all CIs span 0 |

   Last season's production *under this exact card* predicts this season no better than canonical value does.
   Two things compress this, and they must be read together:
   - **Range restriction.** Across *all* IDPs with both seasons, 2025 → 2026 ppg correlates at 0.682 (n 568;
     DL 0.62, LB 0.72, DB 0.64). Restricted to the 229 priced pre-season it is 0.413. Offense loses much less
     (0.824, n 331 → 0.738, n 237). Priced IDPs cover a narrow band of production, so every predictor is
     compressed there; the low figure is not "volatility whatever the predictor".
   - **Noise in what this card pays for.** For nearly the same players (n 228), tackle points per game repeat at 0.67
     year to year and big-play points at 0.35 (DB 0.38 vs 0.24) (§7.1, stability control).
3. **Per source** (vs 2026 ppg; consensus measured on the same players; paired difference source − consensus).

   Pre-season inputs (no hindsight):

   | | idpTradeCalc | draftSharksIdp | idpShowCombined | fantasyProsIdp |
   |---|---|---|---|---|
   | IDP overall (source / consensus) | 0.39 / 0.43 | 0.38 / 0.45 | 0.42 / 0.44 | 0.38 / 0.39 |
   | IDP difference | −0.050 [−0.079, −0.021] | −0.070 [−0.141, +0.014] | −0.019 [−0.052, +0.012] | −0.009 [−0.096, +0.075] |
   | DB (source / consensus) | 0.26 / 0.30 | 0.26 / 0.41 | 0.30 / 0.34 | 0.10 / 0.26 |

   Today's sources (in-season board, hindsight):

   | | idpTradeCalc | draftSharksIdp | idpShowCombined | fantasyProsIdp |
   |---|---|---|---|---|
   | IDP overall (source / consensus) | 0.50 / 0.47 | 0.36 / 0.44 | 0.41 / 0.47 | 0.38 / 0.42 |
   | IDP difference | +0.027 [−0.016, +0.071] | −0.084 [−0.149, −0.022] | −0.059 [−0.117, −0.001] | −0.035 [−0.139, +0.066] |
   | LB difference | +0.071 [+0.001, +0.140] | −0.134 [−0.234, −0.048] | −0.036 [−0.117, +0.028] | −0.090 [−0.241, +0.057] |
   | DB (source / consensus) | 0.44 / 0.38 | 0.23 / 0.36 | 0.29 / 0.36 | 0.10 / 0.29 |
   | DB difference | +0.055 [−0.031, +0.135] | −0.133 [−0.279, +0.004] | −0.069 [−0.198, +0.065] | −0.186 [−0.389, +0.016] |

   - **Pre-season, no single IDP source predicts this league's production better than the consensus.**
   - **In season, idpTradeCalc's point estimate is above the consensus** at IDP overall, LB and DB. Only LB is
     nominally significant (uncorrected, one of many cells). It is an in-season, hindsight-era comparison, not
     a basis for a weight change.

**Answer.** The 0.45 vs 0.77 gap is real and robust to depth, rostered-only and hindsight checks. It reflects
range restriction among priced IDPs plus genuine noise in IDP production, especially in the big-play scoring
this card emphasises. No available pre-season predictor does materially better, whether a source, last season's
league-scored production or BDVM (§7.2, which overlaps the last-season predictor). Neither the gap nor these
comparisons establishes a valuation defect, and they do not rule one out.

## 7. Item 6: does the canonical IDP consensus reflect this league's scoring?

**Context.** The sources are scoring-agnostic dynasty boards. The league-aware overlay was rejected for
canonical use (`LEAGUE_AWARE_METHODOLOGY_REJECTION.md`). BDVM is the separately named, league-scored
fundamental concept.

### 7.1 Card-alignment test

Does value rank players more like this card's production or like the tackle-heavy reference's? The figure is
the paired difference ρ(value, ppg on this card) − ρ(value, ppg on the reference).

| board → production | sample | IDP | DL | LB | DB |
|---|---|---|---|---|---|
| pre-season → 2025 | **in-sample** (board built after 2025) | +0.065 [+0.015, +0.117] | +0.048 [+0.001, +0.109] | +0.062 [−0.008, +0.138] | −0.134 [−0.239, −0.041] |
| pre-season → 2026 | out-of-sample (no hindsight) | −0.004 [−0.047, +0.040] | −0.010 [−0.082, +0.060] | −0.029 [−0.089, +0.030] | −0.078 [−0.178, +0.015] |
| today → 2026 | 2026 production; board updated in season | −0.017 [−0.055, +0.019] | +0.001 [−0.048, +0.046] | −0.019 [−0.058, +0.021] | −0.064 [−0.149, +0.021] |

**Multiplicity** (`valueVsCard_multiplicity`): 12 cells. Three have a 95% CI excluding 0, all in-sample: DB
−0.134 in the hypothesised direction, and IDP +0.065 and DL +0.048 the opposite way. Holm-adjusted p across the
family: DB 0.084, IDP 0.099, DL 0.49, the rest ≥ 0.74; **none survives**. No Bonferroni interval
(level 1 − 0.05/12) excludes 0 (DB in-sample [−0.301, +0.002]).

**Residual vs tackle share** (pre-season value, 2025 production): Spearman between (ppg rank − value rank) and
tackle share.

| position | ρ | 95% CI |
|---|---:|---|
| DB | **−0.56** | [−0.70, −0.41] |
| DL | −0.22 | [−0.43, 0.00] |
| LB | −0.16 | [−0.35, +0.05] |

**Stability control** (`perCardYearToYearStability_control`; same players: priced pre-season, ≥ 8 games in
2025 and ≥ 3 in 2026). How stable is each card's ordering of the same players from 2025 to 2026, and which
card's 2025 production best predicts *this* card's 2026 production?

| | IDP (n 228) | DL (n 63) | LB (n 84) | DB (n 81) |
|---|---:|---:|---:|---:|
| this card, 2025 → 2026 | 0.411 | 0.364 | 0.415 | 0.309 |
| reference card, 2025 → 2026 | 0.501 | 0.335 | 0.478 | 0.345 |
| this − reference stability | −0.091 [−0.166, −0.021] | +0.030 [−0.090, +0.146] | −0.063 [−0.169, +0.043] | −0.036 [−0.198, +0.125] |
| this card's 2026, predicted by the reference card's 2025 | 0.435 | 0.348 | 0.410 | 0.374 |
| reference − this card's 2025, as predictor (paired) | +0.024 [−0.043, +0.085] | −0.016 [−0.100, +0.056] | −0.005 [−0.100, +0.087] | +0.066 [−0.059, +0.195] |
| tackle points per game, 2025 → 2026 | 0.665 | 0.439 | 0.545 | 0.377 |
| big-play points per game, 2025 → 2026 | 0.346 | 0.303 | 0.429 | 0.242 |

- Big-play scoring, which this card emphasises, repeats less than tackle scoring at every position, and by the
  widest margin at IDP overall (0.35 vs 0.67) and DB (0.24 vs 0.38).
- At DB, the reference card's 2025 production predicts this card's 2026 production at least as well as this
  card's own 2025 production does (point estimate higher; CI spans 0).
- So the alignment signature and the tackle-share residual are **what a board that rationally discounts noisy
  big plays would produce**. A board that tracks a tackle-heavier ordering can be the better *forecast* of this
  card's future production. The residual (ρ −0.56) is measured against in-sample 2025 production, where
  big-play-driven seasons are exactly the ones expected to regress.

**Reading:**
- **DL and LB:** no mismatch; the in-sample cells lean slightly toward this card.
- **DB:** the only supporting cell is in-sample, does not survive a multiplicity correction, is not replicated
  out of sample, and is confounded with rational discounting of unstable big-play scoring. **The DB mismatch is
  an unconfirmed hypothesis.**

### 7.2 BDVM

BDVM was run in memory: 864 priced. It is pre-season and league-scored, with 2026 production out of sample.

| group | BDVM projected fpg | canonical pre-season (same players) | difference (paired) | BDVM balanced trade value |
|---|---:|---:|---|---:|
| offense | 0.74 | 0.67 | +0.07 [0.00, +0.14] | 0.56 |
| IDP | 0.44 | 0.39 | +0.04 [−0.07, +0.16] | 0.15 |
| DL | 0.46 | 0.31 | +0.15 [−0.03, +0.34] | 0.17 |
| LB | 0.42 | 0.52 | −0.10 [−0.28, +0.07] | 0.37 |
| DB | 0.32 | 0.32 | +0.01 [−0.23, +0.25] | 0.10 |

- Rank agreement between BDVM and canonical: IDP 0.37, against offense 0.84.
- **The two concepts disagree far more at IDP, yet neither predicts this season's IDP production better.**
- **Even a league-scored projection cannot predict DB well** (0.32, identical to canonical).
- **BDVM is not an independent predictor here.** Its projection is built from 2023–25 realized PPG under this
  card plus rookie priors, so it largely re-uses the information in the last-season-production predictor of
  §6. Its failure to beat canonical value and that predictor's failure are not two separate pieces of evidence.
- BDVM's dynasty trade value is a poor short-term predictor, as expected: it prices long horizons.

**Answer.**
- Whether the consensus reflects this league's scoring at **DB** is **unresolved**: one in-sample signal that
  does not survive multiplicity correction or replicate out of sample, and that rational discounting of noisy
  big plays would also produce.
- There is no mismatch at DL or LB.
- IDP value is weakly predictive of next-season production, as is every alternative tested here, for reasons
  covered in §6 (range restriction and noise).

## 8. Item 7: how the anchor moves each consumer

### 8.1 Code trace

Line numbers are traced at run time; see `consumers` in the JSON.

| consumer | where | how the anchor enters |
|---|---|---|
| anchor owner | `src/draft/displacement.py:276` | best unrostered `rankDerivedValue` per position |
| ECC / unpriced base | `src/draft/displacement.py:359` | `ECC = max(0, base − waiver) × mult`; an unpriced player's base is the waiver value (`assumedWaiver`) |
| cut-ladder order | `src/draft/displacement.py:455` | cheapest ECC first, ties broken by name |
| capacity context (Trade Calculator Team Context, War Room, Trade Finder, Angle, suggestions) | `src/trade/roster_capacity.py:498` | builds the anchor league-wide |
| release cost | `src/trade/roster_capacity.py:1282` | `base × mult`, so it depends on the anchor only for unpriced drops |
| Team Context charge | `src/trade/roster_capacity.py:629` (`forced_drop_cost`) | the sum of the added drops' release cost |
| Trade Finder | `src/trade/finder.py:1159` | `−(cost / give) × 50` added to the score (reorders, filters nothing) |
| Analyze Trade | `src/trade/analyze_trade.py:472` | nets `forcedDropReleaseCost` from the objective component |
| Trade simulator | `src/api/trade_simulator.py:961` | attaches capacity |
| War Room | `server.py:10132` | `forced_drop_cost` per offer |
| Perfect Draft (server) | `src/draft/context.py:324` | positional anchor, plus a position-agnostic free-agent ladder `W(k)` |
| Perfect Draft (client) | `frontend/lib/perfect-draft.js:170`, `:250` | rookie surplus = `max(0, v·tilt − waiver(pos))`; release cost = base × mult |
| Droppability | `src/roster_intel/droppability.py:235` | same cut ladder |
| Perfect Waivers | `src/trade/perfect_waivers.py:1092` | calls `effective_cut_cost(asset, {}, None)`: **no anchor in its cost basis**. It also calls `team_droppability` and the capacity assessment, and its `requiredStartersToday` comes from the cut ladder's `undroppable` list, which is built in ECC order, so that list's contents can shift (capacity counts do not) |
| Others downstream of the same anchor | `frontend/lib/auction-advice.js:97,111` (reads `waiverValues`), the decision engine's forced-drop term (via `forced_drop_cost`), and the N-team path (via the simulator) | all move with the anchor; omitted from the first consumer list |
| FAAB | `src/trade/faab_engine.py:326`, `server.py:8054` | `V_repl` is **position-agnostic**: the format line blended 50/50 with the 12th-best unrostered player |
| LI-5 / scarcity | `src/league_intel/replacement.py:341`, `src/api/gameplan.py:517`, `src/draft/displacement.py:209` | gameplan calls LI-5 **without free agents**, so there is no waiver tier, `waiver_scarcity` is `None`, and the multiplier is **inert at 1.0 for every position** (confirmed: `servedMultiplierByPosition` is all 1.0) |

### 8.2 Shadow quantification

The anchor dicts were swapped into the real `CapacityContext` and passed to `assess_roster_capacity` and
`forced_drop_cost`.

**Scenario:** each of the 12 rosters trades its offense player nearest 3,500 for the next roster's two (net +1)
or three (net +2) offense players nearest 3,500. The incoming players are far above any anchor, so the forced
drop is the roster's own cheapest legal cut.

| anchor | net +1: teams whose forced drop changes | mean Δ cost | max \|Δ\| | mean \|Δ Finder factor\| | net +2: teams changed | mean Δ cost |
|---|---:|---:|---:|---:|---:|---:|
| A1 best healthy | 1/12 | −51 | 614 | 1.1 | 2/12 | −226 |
| A2 3rd-best healthy | 6/12 | −440 | 1,897 | 7.0 | 9/12 | −635 |
| **A3h banded healthy** (A3hs strict: identical) | 4/12 | −246 | 1,872 | 3.9 | 5/12 | −269 |
| A5 best-ball starter | 5/12 | −343 | 1,872 | 5.9 | 8/12 | −290 |

- Baseline mean forced-drop cost is 1,023 (net +1) and 2,128 (net +2).
- **Every forced drop has an effective cut cost of 0 under every anchor:** the cut is always a sub-anchor player.
- So the anchor moves the charge only through:
  1. which tied sub-anchor player is chosen;
  2. the release cost of **unpriced** cuts, which is charged as the waiver value: 3 of 12 net +1 drops today.
- Both mechanisms are exactly what investigation A is correcting (alphabetical ties; unpriced players charged
  a whole waiver value). **The anchor change and the forced-drop fix must be sequenced, not stacked.**
- **Perfect Draft:** board rookies with positive surplus over the anchor.

  | position | A0 | A3h | A2 |
  |---|---:|---:|---:|
  | DB | 2 of 21 | 6 | 8 |
  | DL | 3 of 24 | 5 | 5 |
  | LB | 5 of 18 | 6 | 8 |

  The position-agnostic ladder `W(k)` top five falls from 2,156 to 2,149 at the top, and from 1,923 to 1,895 at
  the fifth.
- **FAAB:** served `V_repl` is 1,687, and that figure is **guardrail-capped**: the raw 50/50 blend of the
  12th-best unrostered player (1,839) and the format line (1,573) is 1,706, and the engine widens it down to
  `V_allin` 2,387 − the 700 minimum band. With a healthy-only live pool (shadow or strict rule, identical) the
  12th best is 1,737, the blend is 1,655 and no cap applies, so a player at 2,200 moves from 50.9% to 54.2% of
  the budget ceiling. A production-qualified pool would collapse `V_repl` to 901 (its live-pool figure is 229),
  which is not viable. **FAAB is barely affected, because it is position-agnostic and has its own anchor.**
- **LI-5 scarcity:** inert today. Wiring free agents into the gameplan bundle would activate a 0.85–1.15×
  multiplier on every cut cost: a served change, and an owner decision of its own. Routing the anchor through
  LI-5 (§9 recommendation 1) supplies exactly those free agents, so the two can be coupled; see the currency note in §9 recommendation 1.

## 9. Conclusion, recommendation, gates and what must not be done

**Statistical caveats (independent review).** The out-of-sample DB intervals still admit effects as large as the in-sample
-0.134; "predicts at least as well" is a point estimate with a CI of [-0.059, +0.195]; the Bonferroni DB upper bound
(+0.002) is borderline; there is a single author-chosen reference card with no sensitivity check; and the games-played
selection conditions on survival. Sample sizes differ between cells (DB 0.309 at n=81 versus 0.323 at n=82) and the
wire-order DB rho differs from the prior lane's (0.206 at n=27 versus 0.124 at n=26) because the pools differ. 10 of 13
production-qualified wire DBs are unpriced by the board, so the deep DB wire is simply not covered. Perfect Draft's
shadow skips the auction-rookie exclusion the served path applies (`src/draft/context.py:324,332`); whether that
matters in October is unverified.

**Conclusion: replacement methodology. A league-specific valuation defect is not established.**

| issue | status | evidence | owner |
|---|---|---|---|
| **Replacement methodology** | measured defect; actionable | §2: injured and non-producing players set 6 of 7 anchors; value is not shown to order the IDP wire; DB anchor above 26/35 starters; §5: DB is the flattest position | the canonical replacement owner (LI-5, `src/league_intel/replacement.py`), consolidated under C2-REPL-01; consumed by the displacement anchor and through it roster capacity, Perfect Draft and Droppability |
| **League-specific valuation at DB** | unconfirmed hypothesis | §7.1: one in-sample cell (−0.134); out-of-sample CIs span 0; nothing survives Holm across 12 cells; confounded with rational discounting of unstable big plays (stability control); residual vs tackle share −0.56 is in-sample | none until confirmed. **Not** a source-weight question |
| **Headline IDP correlation gap** | not a demonstrated defect | §6: range restriction (0.682 all IDPs vs 0.413 priced) plus big-play noise; no pre-season predictor does better; BDVM overlaps the last-season predictor | — (disclose, don't fix) |

**Recommendations, each with what it requires:**

1. **Consolidate the waiver anchor into the canonical replacement owner; do not add a sixth implementation.**
   - The candidate rule A3h is exactly LI-5's waiver tier: `compute_replacement_levels` takes
     `_banded_value(fa_pool, 1, band)` with `DEFAULT_BAND = 2` (`src/league_intel/replacement.py:440–452`), the
     mean of free-agent ranks 1–3. The only change is a health filter on the free agents LI-5 is given.
   - Replacement level is already recorded as **DUPLICATED — 5 implementations in 3 units** (manifest row
     `C2-REPL-01`, CE-09; target "one service; domain views are consumers"; `C2-DROP-01` says displacement
     "consumes the shared replacement owner"). So the recommendation is: route
     `src/draft/displacement.py::waiver_values_by_position` through LI-5's waiver tier, with the strict health
     rule (§2.2: NFL team, explicit `Active` status, no unavailable injury designation; a missing status is
     unknown, never healthy), **as part of the C2-REPL-01 consolidation**. A health-filtered banded rule written
     inside `displacement.py` would be a sixth implementation and is out. The strict health rule in this study
     (`is_healthy_strict`) is a research definition: a production version must consume the existing owners
     (`src/ros/availability.py` states and `src/trade/waiver.py::waiver_candidate_exclusion`, the add-pool filter)
     rather than add another health definition. Whether the DL/LB rookie anchor setters pass that filter's
     `rookie_gate` and `single_source` checks is not yet checked.
   - **Currency and the scarcity coupling.** LI-5 in the gameplan bundle runs on `rosValue`, a 0-100 ROS index, while
     the displacement anchor is in `rankDerivedValue` (0-9999). Scarcity today comes from the bundle's rosValue LI-5
     call (`src/draft/context.py:152-174`), so a separate market-value LI-5 call fed free agents would not activate
     scarcity unless the bundle call is also changed. Whether the two are "coupled" is therefore a design choice for
     the consolidation, not a given. The study's A3 is an inline top-three mean, not an LI-5 call; a parity assertion
     against `compute_replacement_levels(free_agents=...)` is part of the build.
   - **Which question the ladder answers.** The anchor prices the opportunity cost of a roster spot in dynasty-asset
     terms, where a free injured star or rookie is a claimable asset with real value. The health filter is right only
     if the question is this-season lineup replacement. That is an owner call, and it is not settled here. Residuals
     remain even after A3h: 12-13 of 35 DB starters sit below the anchor, and the DB anchor (1,754) is above the
     lowest starter (1,335).
   - **Who moves.** Everything that reads the displacement anchor moves together: roster capacity and its
     consumers (Trade Calculator Team Context, War Room, Trade Finder, Angle, suggestions, Analyze Trade, trade
     simulator), Perfect Draft (server and client) and Droppability. **FAAB does not**: it has its own
     position-agnostic `V_repl` (`src/trade/faab_engine.py:326`, `resolve_anchors`: the format line blended
     50/50 with the live pool's 12th best). **Perfect Waivers does not**: it prices cuts with no anchor
     (`effective_cut_cost(asset, {}, None)`). Whether FAAB's live pool should also exclude injured players is a
     separate, small question (§8.2: 1,706 raw → 1,655).
   - **Coupled with recommendation 2.** Giving LI-5 free agents is what creates the waiver tier, hence
     `waiver_scarcity`, hence a live 0.85–1.15× scarcity multiplier on every cut cost. Sequencing must handle
     both, either:
     - one gated PR with **two separately flagged effects** (anchor on its flag; scarcity on its own flag, held
       off until its own owner decision), or
     - explicit ordering: the anchor first with the scarcity multiplier explicitly pinned inert, scarcity later.
   - Requires: a gated PR with the shadow above re-run on the then-current board; adversarial tests (an injury
     flip, a thin wire, a missing status counted as unknown, the scarcity flag off leaving multipliers at 1.0);
     **sequencing after investigation A's forced-drop correction**; then before/after verdict comparisons on
     Trade Calculator Team Context, War Room, Finder and Perfect Draft.
   - It changes served recommendations, so the exact production impact goes to the owner before activation
     (owner decision §2 and §6). Both effects require owner approval and remain gated.
   - Not production-qualified (A4): unstable in the bar, undefined at four positions, and its evaluation here is
     circular.
2. **Latent scarcity wiring.** Either record "scarcity multiplier intentionally inert" in the displacement and
   gameplan owners, or let LI-5's free-agent tier feed it.
   - The second is a served change and needs an owner decision.
   - It is coupled to recommendation 1 (above): it must not switch on silently as a side effect of the anchor
     consolidation.
3. **DB league-scoring hypothesis: evidence first.**
   - Re-run this script after week 17 and on the 2027 pre-season board. A confirmatory test must be
     out-of-sample, pre-registered (cells named in advance), multiplicity-corrected, and must beat the
     rational-discounting explanation: for example, a DB ordering re-weighted toward this card must predict this
     card's *future* production better than the canonical ordering and better than the tackle-heavier ordering.
     Today the reverse point estimate holds (§7.1 stability control).
   - Any remedy is a separately named, league-scored lens (BDVM is the existing concept) shown beside the
     canonical value. It is not a mutation of `rankDerivedValue`.
   - It would need the full methodology sequence (fit → backtest → validate → compare → human approval). The
     overlay rejection record (#822) is the bar.
4. **Disclosure.** The R-C disclosure design (separate workstream) may state, without numbers, that IDP
   production is less predictable and that IDP replacement is close to a starter in this league.

**What must NOT be done:**
- no automatic lowering of IDP values;
- no change to source weights, votes, families, curves or Hill constants to "fix" IDP correlation:
  - pre-season, no source beats the consensus, and the in-season idpTradeCalc edge is a hindsight-era point
    estimate;
  - league-scored alternatives do not predict better;
- no new replacement-level implementation: one owner (LI-5), consumed, never re-derived per consumer or page;
- no production-qualified (A4) anchor;
- no stacking of the anchor change on top of investigation A's release-charge changes in one activation, and no
  silent activation of the scarcity multiplier through it;
- no reading of an injured player's absence from the anchor as "zero value": he keeps his canonical value as an
  asset;
- no use of the league-aware overlay or BDVM numbers under a canonical field name.

## 10. Limits and UNRESOLVED

**Limits:**
- **2026 has only six weeks** (at least 3 games for ppg). Production lines and wire depth use season-to-date
  data.
- **2025 is "this card applied to 2025 stat lines",** not what the league scored then: it was a 10-team format
  with `bonus_rec_te` 0.35.
- **The pre-season board was built after the 2025 season,** so any pre-season → 2025 comparison is in-sample.
- **Today's board already knows the season.** The served pre-season board is the no-hindsight comparison.
- **Anchors, injury statuses and rosters are a 2026-10-20 snapshot.** Statuses change weekly; banding damps this
  but does not remove it. The JSON was regenerated against the same roster snapshot
  (`--roster-max-age-s`); every pre-existing number reproduced exactly.
- **The two health rules agree today only because the feed is complete;** the strict rule matters when it is not.
- **The tackle-heavy reference card is illustrative.** The DB hypothesis rests on the alignment *direction* and
  on the tackle-share residual, not on that card's exact weights.
- **Bootstrap p-values use 1,000 resamples** (resolution about 0.001), and only the 12-cell alignment family is
  multiplicity-corrected; the per-source cells are reported uncorrected.
- **BDVM was run without the play-by-play supplement.** That affects offense reception bands, not IDP.
- **The capacity shadow uses one neutral trade shape per roster;** other shapes stress other rungs.
- **Bootstrap CIs resample players** and ignore within-team clustering.
- **Investigation A is changing the forced-drop charge in parallel.** §8.2's deltas are measured against today's
  served charge.

**UNRESOLVED:**
- owner decision on recommendation 1 (consolidation into LI-5 with a health filter), after investigation A
  lands, and on how its coupling with recommendation 2 is sequenced;
- owner decision on recommendation 2;
- the DB hypothesis needs the confirmatory, pre-registered re-run at season end and on the 2027 pre-season board;
- the independent review (ACCEPT WITH FIXES) findings are applied here; the fixes themselves have not been
  re-reviewed.
