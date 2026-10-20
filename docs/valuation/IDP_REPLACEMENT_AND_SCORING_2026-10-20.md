# IDP replacement anchors and league-specific IDP scoring (2026-10-20)

**Status: RESEARCH — COMPLETE (investigation B).** Nothing in this workstream changes a value, a source weight,
a vote, a curve, a replacement anchor or any served behaviour. Every alternative below was computed in shadow
and fed to the canonical consumers' own pure functions; nothing was written back.

**Authority:** `docs/owner/LOW_VALUE_ASSET_OWNER_DECISIONS_2026-10-20.md` §3. Prior evidence it extends (not
redoes): `docs/valuation/LOW_VALUE_ASSET_RESEARCH_2026-10-20.md` §6 and
`evidence/low_value_assets_2026-10-20/idp_anomaly.json`.

**Evidence:** `evidence/idp_replacement_2026-10-20/idp_replacement.json`, produced by
`scripts/idp_replacement_research.py` (aggregate-only; NFL player names for illustrative rows; no league, user,
roster, transaction or player ids; no team or manager names; checked by `assert_aggregate_only`).

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## 0. Owner summary

**Verdict: both — but they are different sizes and need different owners.**

1. **Replacement methodology: the main, actionable cause of the anomaly.**
   - The waiver anchor is the single highest-valued unrostered player at each position.
   - It counts injured players and non-producing rookies. In this league that matters: it is best ball with no IR
     and no taxi, so an injured player fills one of 58 spots and scores nothing.
   - Value does not order the wire at IDP. Among unrostered players, the rank correlation between value and
     points per game is about zero (DL 0.09, LB −0.21, DB 0.21; every CI spans 0).
   - The worst case is DB. The anchor (2,156, an injured player) sits above **26 of the 35** DBs in the
     value-optimal lineups.
2. **League-specific valuation: real, but narrow. It is mostly DB, not "IDP".**
   - This card pays big plays: one pass defended is worth 3.98 solo tackles, one tackle for loss 3.19.
   - The pre-season board ranks DBs the way a tackle-heavy card would. Against 2025 production it agreed better
     with the tackle-heavy reference than with this card (paired difference −0.134, CI [−0.239, −0.041]).
   - Within DBs, the higher a player's tackle share, the more the board values him relative to his production
     under this card (ρ −0.56, CI [−0.70, −0.41]).
   - DL and LB show no such mismatch.
3. **The headline 0.45 vs 0.77 gap is mostly inherent IDP volatility, not a defect in the consensus.**
   - Take the same players (priced pre-season, with 2025 history). Their 2025 production, scored under this
     card, predicts 2026 production no better than pre-season value does: IDP 0.41 vs 0.40, against offense
     0.74 vs 0.68.
   - No single IDP source beats the consensus.
   - BDVM's league-scored projection does not beat it significantly either: IDP 0.44 vs 0.39, difference CI
     [−0.07, +0.16].

**Recommendation (§9):**
- **Methodology:** a gated anchor change for the displacement owner: healthy-only, banded over the top three.
  Sequence it after the forced-drop correction (investigation A).
- **Scarcity:** an owner decision on a latent wiring finding. The served positional scarcity multiplier is
  inert (1.0 everywhere).
- **DB:** evidence collection only. No value, weight or vote change.

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
| today's board | `exports/archive/dynasty_export_20261020_052241.zip`, built with today's code through `shadow_replay.build_context`, which reproduces the prior lane's anchors exactly (sha256 in the JSON) |
| pre-season board | the served 2026-08-25 golden board (`data/ops/v1-27/…`). Per-source pre-season ranks come from a today's-code replay of the 2026-08-25 archive. Ranks are source inputs, so methodology drift does not move them. |
| production | Sleeper weekly stat lines for 2026 weeks 1–6 and 2025 weeks 1–18. Both seasons are scored under the current card by the canonical scorer (`compute_weekly_points`). |
| scorer check | 3,299 / 3,299 player-weeks match Sleeper's own points (max difference 0.004) |
| rosters and rules | live Sleeper rosters, league settings and transactions (aggregate counts only) |
| BDVM | `fetch_and_build_baseline`: 2023–25 nflverse realized PPG under this card, plus rookie draft-slot priors. `run_valuation` was run in memory and no snapshot was written. It is a league-scored pre-season fundamental, so 2026 production is out of sample for it. |
| statistics | Spearman rank correlation; 95% CIs from 1,000 player-level bootstrap resamples. Differences use paired bootstrap on the same players, or independent bootstrap for offense vs IDP. |

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
- Among unrostered players, value and production are almost unrelated at IDP (Spearman: DL 0.09, LB −0.21,
  DB 0.21; every CI spans 0). WR is the only position where value orders the wire (0.45).
- The best-producing healthy unrostered DB ranks **34th by value** among unrostered DBs.

### 2.2 Alternative anchors, in shadow

"Canonical starters below" counts the DBs or DLs in the 12 value-optimal lineups that are valued below the
anchor (the prior lane's anomaly count). "Production starters below" counts the same for lineups re-solved on
season-to-date points.

**DB** (the anomaly):

| definition | anchor | canonical starters below | production starters below | rostered above |
|---|---:|---:|---:|---:|
| A0 served: best unrostered | 2,156 | 26/35 | 30/34 | 9/100 |
| A1 best healthy | 1,917 | 19/35 | 28/34 | 17/100 |
| A2 3rd-best healthy | 1,436 | 3/35 | 14/34 | 54/100 |
| A3 LI-5 banded top-3, all | 1,994 | 23/35 | 29/34 | 12/100 |
| **A3h LI-5 banded top-3, healthy** | **1,754** | **12/35** | 22/34 | 28/100 |
| A5 LI-5 best-ball starter (rosters) | 1,384 | 2/35 | 10/34 | 64/100 |
| D board price of wire-level production (diagnostic) | 1,588 | 9/35 | 18/34 | 36/100 |

**DL and LB:**

| definition | DL anchor | DL canonical starters below | LB anchor | LB canonical starters below |
|---|---:|---:|---:|---:|
| A0 served | 1,918 | 7/37 | 2,149 | 6/35 |
| A1 best healthy | 1,918 | 7/37 | 2,149 | 6/35 |
| A2 3rd-best healthy | 1,740 | 1/37 | 1,793 | 3/35 |
| **A3h banded healthy** | **1,812** | 3/37 | **1,946** | 3/35 |
| A5 best-ball starter | 1,668 | 1/37 | 1,628 | 1/35 |

**Offense** (A0 → A3h):

| pos | A0 | A3h | note |
|---|---:|---:|---|
| QB | 1,923 | 1,410 | only five healthy unrostered QBs |
| RB | 1,626 | 1,502 | |
| WR | 1,802 | 1,583 | |
| TE | 2,061 | 1,769 | |

**Reading:**
- **Healthy-only fixes the cause but not the noise.** A1 still leaves 19 of 35 DB starters below the anchor,
  and A1 equals A0 at DL and LB, where the anchors are healthy rookies who do not produce.
- **Healthy and banded (A3h)** is the smallest change that removes most of the anomaly at every IDP position
  while staying a waiver concept. The banding is LI-5's own rule: the mean of ranks 1–3.
- **Production-qualified (A4) is not viable as a served rule:**
  - it is hindsight;
  - it is undefined at four of seven positions (QB, RB, WR, LB), because the wire there has no startable
    producer;
  - it swings with the bar: at DB a P10 bar sets it at 1,917, a P25 bar at 229.
- **The diagnostic D anchor converges with A3h at IDP.** It is the board's own price of wire-level production:
  DB 1,588, DL 1,724, LB 1,401.

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
| LB | 33 | 27 | PUP 1, Out 1, IR 1, Questionable 1 (plus 3 listed "Active" with no team) |
| DB | 37 | 23 | Out 8, IR 6, Questionable 1 |

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

**Wire depth today** (2026 weeks 1–6, hindsight). All healthy unrostered players with at least 3 games,
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
   **IDP season-to-season predictability is inherently low, whatever the predictor.**
3. **Per source** (pre-season inputs vs 2026 ppg; consensus measured on the same players):

   | | idpTradeCalc | draftSharksIdp | idpShowCombined | fantasyProsIdp |
   |---|---|---|---|---|
   | IDP overall (source / consensus) | 0.39 / 0.43 | 0.38 / 0.45 | 0.42 / 0.44 | 0.38 / 0.39 |
   | DB (source / consensus) | 0.26 / 0.30 | 0.26 / 0.41 | 0.30 / 0.34 | 0.10 / 0.26 |

   **No single IDP source predicts this league's production better than the consensus.**

**Answer.** The 0.45 vs 0.77 gap is real and robust. Most of it is inherent IDP volatility: no available
predictor does materially better, whether a source, last season's league-scored production or BDVM (§7). It is
not a consensus-aggregation defect. The one position-specific exception is DB (§7).

## 7. Item 6: does the canonical IDP consensus reflect this league's scoring?

**Context.** The sources are scoring-agnostic dynasty boards. The league-aware overlay was rejected for
canonical use (`LEAGUE_AWARE_METHODOLOGY_REJECTION.md`). BDVM is the separately named, league-scored
fundamental concept.

### 7.1 Card-alignment test

Does value rank players more like this card's production or like the tackle-heavy reference's? The figure is
the paired difference ρ(value, ppg on this card) − ρ(value, ppg on the reference).

| board → production | IDP | DL | LB | DB |
|---|---|---|---|---|
| pre-season → 2025 | +0.065 [+0.015, +0.117] | +0.048 | +0.062 | **−0.134 [−0.239, −0.041]** |
| pre-season → 2026 | −0.004 | −0.010 | −0.029 | −0.078 [−0.178, +0.015] |
| today → 2026 | −0.017 | +0.001 | −0.019 | −0.064 [−0.149, +0.021] |

**Residual vs tackle share** (pre-season value, 2025 production): Spearman between (ppg rank − value rank) and
tackle share.

| position | ρ | 95% CI |
|---|---:|---|
| DB | **−0.56** | [−0.70, −0.41] |
| DL | −0.22 | [−0.43, 0.00] |
| LB | −0.16 | [−0.35, +0.05] |

- **DL and LB:** the consensus is neutral or slightly league-aligned.
- **DB:** the consensus ranks like a tackle-heavy card. It values tackle-heavy safeties above the
  coverage corners this card pays for.

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
- **Even a league-scored projection cannot predict DB well.** The DB-order mismatch in §7.1 is real, but
  correcting it would not by itself make DB values predictive.
- BDVM's dynasty trade value is a poor short-term predictor, as expected: it prices long horizons.

**Answer.**
- The consensus does not reflect this league's scoring at **DB**: a measurable mismatch in the startable range.
- It broadly does at DL and LB.
- It is weakly predictive everywhere at IDP, for reasons no league-scored alternative tested here removes.

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
| Perfect Waivers | `src/trade/perfect_waivers.py:1092` | calls `effective_cut_cost(asset, {}, None)`: **no anchor at all** |
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
| **A3h banded healthy** | 4/12 | −246 | 1,872 | 3.9 | 5/12 | −269 |
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
- **FAAB:** `V_repl` 1,687 → 1,655 with a healthy-only live pool, so a player at 2,200 moves from 50.9% to 54.2%
  of the budget ceiling. A production-qualified pool would collapse `V_repl` to 901, which is not viable.
  **FAAB is barely affected, because it is position-agnostic.**
- **LI-5 scarcity:** inert today. Wiring free agents into the gameplan bundle would activate a 0.85–1.15×
  multiplier on every cut cost: a served change, and an owner decision of its own.

## 9. Conclusion, recommendation, gates and what must not be done

**Conclusion: both.**

| issue | scope | evidence | owner |
|---|---|---|---|
| **Replacement methodology** (primary) | the waiver anchor at every position; worst at DB | §2: injured and non-producing players set 6 of 7 anchors; value does not order the IDP wire; DB anchor above 26/35 starters; §5: DB is the flattest position | displacement owner (`src/draft/displacement.py`), consumed by roster capacity and Perfect Draft |
| **League-specific valuation** (secondary, narrow) | DB order in the startable range | §4, §7.1: −0.134 alignment toward the tackle-heavy card; residual vs tackle share −0.56 | value pipeline / league-intel. **Not** a source-weight question |
| **Not a defect** | the headline IDP correlation gap | §6: the same-player predictor test, per-source results and BDVM are all no better | — (inherent volatility; disclose, don't fix) |

**Recommendations, each with what it requires:**

1. **Candidate anchor rule: A3h, healthy-only and banded.** The mean of the top three unrostered players at the
   position who are on an NFL team and not Out, IR, PUP, Doubtful, Suspended or NA, using Sleeper's injury
   status.
   - Owner: `waiver_values_by_position`. One rule, so every consumer moves together, with no consumer-local
     anchor.
   - Requires:
     - a gated PR with the shadow above re-run on the then-current board;
     - adversarial tests: an injury flip, a thin wire, a missing status counted as unknown, never healthy;
     - **sequencing after investigation A's forced-drop correction**, then before/after verdict comparisons on
       Trade Calculator Team Context, War Room, Finder and Perfect Draft.
   - It changes served recommendations, so the exact production impact goes to the owner before activation
     (owner decision §2 and §6).
   - Not production-qualified: hindsight-dependent and undefined at most positions.
2. **Latent scarcity wiring.** Either record "scarcity multiplier intentionally inert" in the displacement and
   gameplan owners, or wire LI-5 free agents into `get_league_bundle`.
   - The second is a served change and needs an owner decision.
   - Do not activate it silently, and not in the same PR as recommendation 1.
3. **DB league-scoring mismatch: evidence first.**
   - Re-run this script after week 17 and on the 2027 pre-season board. The DB alignment result must hold on
     out-of-sample 2026 production; today its CI spans 0.
   - Any remedy is a separately named, league-scored lens (BDVM is the existing concept) shown beside the
     canonical value. It is not a mutation of `rankDerivedValue`.
   - It would need the full methodology sequence (fit → backtest → validate → compare → human approval). The
     overlay rejection record (#822) is the bar.
4. **Disclosure.** The R-C disclosure design (separate workstream) may state, without numbers, that IDP
   production is less predictable and that IDP replacement is close to a starter in this league.

**What must NOT be done:**
- no automatic lowering of IDP values;
- no change to source weights, votes, families, curves or Hill constants to "fix" IDP correlation:
  - no source beats the consensus;
  - league-scored alternatives do not predict better;
- no page-local or consumer-local anchor: one owner;
- no production-qualified (hindsight) anchor;
- no stacking of the anchor change on top of investigation A's release-charge changes in one activation;
- no reading of an injured player's absence from the anchor as "zero value": he keeps his canonical value as an
  asset;
- no use of the league-aware overlay or BDVM numbers under a canonical field name.

## 10. Limits and UNRESOLVED

**Limits:**
- **2026 has only six weeks** (at least 3 games for ppg). Production lines and wire depth use hindsight.
- **2025 is "this card applied to 2025 stat lines",** not what the league scored then: it was a 10-team format
  with `bonus_rec_te` 0.35.
- **Today's board already knows the season.** The served pre-season board is the no-hindsight comparison.
- **Anchors, injury statuses and rosters are a 2026-10-20 snapshot.** Statuses change weekly; banding damps this
  but does not remove it.
- **The tackle-heavy reference card is illustrative.** The DB conclusion rests on the alignment *direction* and on
  the tackle-share residual, not on that card's exact weights.
- **BDVM was run without the play-by-play supplement.** That affects offense reception bands, not IDP.
- **The capacity shadow uses one neutral trade shape per roster;** other shapes stress other rungs.
- **Bootstrap CIs resample players** and ignore within-team clustering.
- **Investigation A is changing the forced-drop charge in parallel.** §8.2's deltas are measured against today's
  served charge.

**UNRESOLVED:**
- owner decision on recommendation 1, after investigation A lands;
- owner decision on recommendation 2;
- the DB alignment needs a confirmatory re-run at season end and on the 2027 pre-season board;
- this document has had no independent review yet.
