# Unified Manager of the Year — methodology record (v1 candidate)

**Status:** CANDIDATE METHODOLOGY — implemented, replayed, **not promoted**; one pathology open (§11.4, OD-MOTY-7). Official historical winners are
unchanged (§9).
**Method version:** `moty-unified-v1-2026-09-28`
**Owner decision:** 2026-09-28, recorded in `docs/OWNER_REQUESTED_TODO.md` ("ONE unified Manager of the Year").
**Implementation:** `src/public_league/manager_of_the_year.py` (engine), wired through
`src/public_league/awards.py` (the canonical awards owner), rendered by
`frontend/app/league/sections/awards.jsx` (`ManagerOfTheYearCard`).
**Freeze:** every definition and parameter in §1–§8 was written and committed **before** any season's
Manager of the Year result was computed. The replay (§11) was run afterwards against the frozen code. A change
to anything in §1–§8 is a methodology change and bumps the method version.

The weights are the owner's proposed award-policy weights. They are **not** statistically validated, and a
plausible-looking winner list is not validation (§11.4).

---

## 1. What the award answers

One award for the whole franchise year: how well the manager **competed** (A, P) and how much **net value** the
manager's roster decisions created (T, W, D). It replaces the separate Manager-of-the-Year / GM-of-the-Year
proposal. There is **no** playoff-field, winning-record, standings, all-play-threshold or contender/rebuilder
gate. Every manager is ranked on the same formula.

This is an award index. It does not isolate managerial skill from luck, and nothing here claims it does.

## 2. Outer formula and states

```
MOTY_final       = 0.40·A + 0.25·T + 0.15·W + 0.10·D + 0.10·P          (each component 0–100)
MOTY_provisional = (0.40·A + 0.25·T + 0.15·W + 0.10·D) / 0.90           (before P is final)
earnedOf90       =  0.40·A + 0.25·T + 0.15·W + 0.10·D                   (published with the provisional score)
```

* **Provisional** — P pending (the championship final has no winner yet). Label: *"Provisional score — postseason
  component pending."* The same division applies to every manager; there is no per-manager reweighting.
* **Final** — the final has a winner; the full formula applies.
* **Unscored** — any of A/T/W/D is unmeasurable for that manager (e.g. no finished week yet): the row publishes
  its components and no score. Never 0, never 50.
* **Coverage** — `complete` only when every channel below is fully measurable for the season; otherwise
  `partial`, with machine-readable reasons (§8).
* **Official** — see §9. In v1 every season's unified result is a **candidate**.

Contributions are published per component (out of 40 / 25 / 15 / 10 / 10). Ranking uses full precision; only
display rounds.

## 3. A — regular-season all-play (weight 0.40)

`A = 100 · mean_w( (opponents outscored + 0.5 · opponents tied) / (teams − 1) )` over the season's **finished
regular-season weeks** (`metrics.final_regular_season_weeks`, the one "finished" definition).

Reuses the canonical all-play owner (`luck._season_weekly_scores` + `luck._all_play_week`): official host team
totals, the full league pool, one observation per finished week, genuine zero and negative scores kept, an absent
score missing (never zero). The league-median game is a **record** rule; all-play already compares against every
team, so the median game is not counted again. No bonus for H2H record, points for, standings, consistency or
close games. A manager missing a week that others have is published with `coverage: partial` for A.

## 4. P — championship-playoff achievement (weight 0.10)

From the **actual** winners bracket only. Let K = the number of bracket entrants.

* Champion: finish rank 1. Runner-up: 2.
* Teams eliminated in the same championship round share the **average** of the finish ranks that round occupies
  (e.g. two semifinal losers in a 5-team bracket occupy ranks 3–4 → 3.5 each).
* `P = 100 · (K + 1 − finish_rank) / K`. A non-playoff manager has `P = 0` and remains fully eligible.
* Placement games (`p = 3, 5, …`) and the losers bracket are ignored: no consolation or third-place tie-break.
* A first-round bye is not a win; a bye team eliminated in round 2 ties with the other round-2 losers.
* Multi-week rounds are decided by the host's bracket result (`w`/`l`), so they need no special handling.
* **Pending** (not zero) until the final (`p = 1`) has a winner. No previous-champion metadata, no predictions.

Replayed values: 5-team brackets (2024, 2025) → 100 / 80 / 50 / 50 / 20 / 0…; the 7-team 2026 bracket will give
100 / 85.7 / 64.3 ×2 / 28.6 ×3 / 0….

## 5. Management channels T, W, D — shared foundation

### 5.1 The unit: replacement-level surplus (RLS)

For a player `p` and finished regular-season week `w`:

```
u(p, w) = max(0, points(p, w) − L[position(p)])
```

* `points(p, w)` — the player's **official** Sleeper score for that week (`players_points`), read from whichever
  league roster lists him that week. If no roster lists him, the week is **unobservable**: `u` is UNKNOWN.
* `L[pos]` — the season's regular-season replacement points-per-game the canonical VORP board already measures
  (`awards._vorp_board_with_levels`; `src/scoring/replacement_level.py`). A position the board excludes as
  unmeasurable (thin band) has no `L`, so its players' `u` is UNKNOWN.
* Position: `snapshot.player_position` (IDP families collapse to DL/LB/DB), the same resolver VORP uses.

Why this unit, and what it deliberately does not do:

* **Lineup-independent.** It never reads who started. Best-ball lineups earn no start/sit credit, and no
  manager's lineup choices (ours or a trade partner's) stand in for value. (Measured: the 2024 regular season
  was played with **manager-set** lineups — official lineups averaged 62.7 points/week below the week-end
  roster's optimal lineup — while 2025/2026 were best ball; one lineup-independent unit keeps the three seasons
  comparable.)
* **Replacement baseline = the explicit feasible baseline.** Any team can field replacement-level production;
  a player is worth only what he produces above that line, and a below-replacement week is worth 0, not negative.
* **Symmetric.** Incoming and outgoing assets are measured the same way, so a neutral swap nets zero in
  expectation.
* **Known limitation — depth.** A held player's above-replacement week counts even when he did not enter the
  counted lineup (best-ball depth). Scoring only counted starts would need a counterfactual lineup for every
  surrendered player, which requires the historical slot structure (2025's is not recorded: its league object
  now shows 17 slots while weeks 1–16 used 22) and game-time holdings (week-end rosters include players added
  after their game). Owner decision OD-MOTY-3 (§10).

### 5.2 The window

Franchise-management year of season Y = end of Y−1's championship → end of Y's regular season. Sleeper files
every offseason move of that year in league Y (leg 1), so the window is **league Y's completed trades, waiver
claims, free-agent moves and commissioner moves with `leg < playoff_week_start`**, plus league Y's completed
drafts. Postseason moves belong to no management year ("no extra postseason management weeks"). Production is
counted over the finished regular-season weeks only, and the regular-season cutoff freezes T/W/D; the postseason
contributes only P.

### 5.3 The ledger (one acquisition/ownership ledger, every increment credited once)

For roster `r` and finished regular-season week `w`:

* `R(r, w)` — the players Sleeper lists on `r` for week `w` (host truth for holdings).
* `B0(r)` — holdings at the start of the window: the same roster id's **final roster in league Y−1** (Sleeper
  carries roster ids through a renewal). Inaugural season: empty (the startup draft is the construction). A roster
  id the previous league did not have (2026 expansion rosters 11, 12): empty. A previous league missing from the
  snapshot: `unavailable` — T/W/D are not computed for that season.
* `M(r, w)` — the **no-market world**: `B0(r)` with every commissioner move up to `w` applied (commissioner moves —
  e.g. the 2026 expansion allocation — are administrative, not management), plus every player `r` drafted in the
  window.

Attribution:

| case | effect | channel |
|---|---|---|
| `p ∈ R − M` | credit `u(p, w)` | the channel of `r`'s latest acquisition of `p` with `leg ≤ w`: trade → **T**; waiver / free agent → **W** |
| `p ∈ M − R` | charge `u(p, w)` (observed wherever `p` is rostered that week) | the channel of `r`'s latest exit of `p` with `leg ≤ w`: trade → **T**; drop (waiver / FA / standalone) → **W** |
| `p ∈ R ∩ M` or neither | nothing | — |
| no acquisition / exit event explains the difference | nothing; counted | `reconciliation.unexplained*` |

**D** (§5.6) credits each drafted player holder-independently, so a drafted player traded away is charged to T
for the weeks after he left (he is in `M`), and D keeps his selection value.

Summed over T, W and D this telescopes exactly to `u(R) − u(B0) − E(own current picks)`: every surplus increment
is attributed once. Consequences, each pinned by a test (§12):

* **Round trips cannot manufacture value.** Trading X away and trading him back: X is in `M`, so only the weeks
  he was actually away are charged, and the player received in between is credited only while held.
* **Re-acquisition duplicates nothing.** A baseline player dropped and re-added is in `R ∩ M`.
* **Churn is not credit.** A move earns only the surplus its player actually produces while held; a transaction
  with no surplus earns nothing.
* **Gross incoming never ignores outgoing**, and **inherited roster appreciation is not new acquisition** (a
  player in `B0` is never credited).
* **No summed counterfactuals.** There is one set difference per week, not one counterfactual per move.

**UNKNOWN is never zero.** A `u` that cannot be observed is excluded and counted (`unobservedWeeks`). It is not
imputed. The largest such gap is the W charge side (players dropped to free agency are unrostered everywhere);
§8 and §11.3 report it and its sensitivity.

### 5.4 Normalization (T, W, D production channels)

```
channel_score = 50 + 50 · tanh( (net / weeks) / (KAPPA · σ_week) )
```

| parameter | value | provenance |
|---|---|---|
| `net` | channel net RLS over the window | §5.3 |
| `weeks` | the season's finished regular-season weeks | same for every manager |
| `σ_week` | population SD of the season's official regular-season team-week scores (finished weeks) | a property of the league-season's scoring scale, independent of any manager's T/W/D |
| `KAPPA` | **0.5** | predeclared: a net of +½ weekly-score SD per week (a very large management season) maps to 88.1; +1 SD → 98.2 |

Zero net value → exactly 50. Positive above, negative below. Bounded (0, 100), strictly monotonic, no min-max, no
dependence on the other managers' results. **Demonstrated no activity** (no trades / no moves / no selections) →
net 0 → 50: neutral, never "perfect", never "missing". Activity alone cannot move the score — only surplus can.

Reported with every score: the raw net, its credit and charge halves, net per week and unobserved weeks.

### 5.5 T — trade value added (weight 0.25)

**Production channel (P-channel):** the T credits and charges of §5.3 plus traded current-draft picks:

* a pick of the season's own annual draft that changes hands in a window trade carries its slot expectation
  `e(k) · weeks` (§5.6) from the sender to the receiver. `k` = the pick's nominal overall number from the draft's
  order (snake rounds reversed); an unknown slot uses the round's middle slot. Sleeper cannot trade a used pick,
  so every such pick was live when it moved (including picks traded during a slow draft).
* This is the anti-double-count rule for draft capital: **the trade accounts for obtaining the pick, the draft
  (D) accounts for how well it was used.**

**Future-value channel (FV-channel):** acquisition-time package value, reusing the public activity feed's
canonical machinery verbatim — the trade normalizer (`activity._normalize_trade`), the as-of resolver
(`src/api/public_activity_valuation.build_asof_valuation`: the temporal ledger **at the trade's own instant**,
never today's board) and `trade_grading`'s VA-inclusive per-side net (non-additive package valuation, future
picks included). Per manager: `pct = 100 · Σ netAdjusted / Σ max(effective side totals)` over their window
trades; `FV = 50 + 50 · tanh(pct / 25)`, where 25 is the canonical trade-grade band table's "Clear win" edge
(`trade_grading._GRADE_PCT_CLEAR`). A trade with any unresolved asset has no value; the channel is **scored only
when every window trade resolved** — otherwise it is `partial`/`unavailable` and T is the P-channel alone. Raw
values never leave the backend (public/private boundary): only the normalized channel score and coverage counts
are published. Acquisition-time advantage only; later value drift is not credited (it would mix model-wide
inflation into managerial value and double-count surplus the P-channel already measures).

`T = 0.5 · P-channel + 0.5 · FV-channel` when the FV-channel is complete for the season (the 50/50 candidate);
otherwise `T = P-channel`, labelled `partial`. FAAB moved in trades is reported (`faabTradedNet`), not converted.
Forced roster-space drops caused by a trade land in W (the drop's channel); the canonical roster-capacity owner
lives in `src/trade`, which the public package may not import. No trade-count bonus.

### 5.6 D — draft value added relative to opportunity (weight 0.10)

For each selection `s` of player `p` by roster `r` at band `b`:

```
D_r = Σ_s Σ_{observed w} ( u(p, w) − e_kind(b) )
```

* Holder-independent: the drafted player's weeks count wherever he is rostered (§5.3).
* `b = ceil(k / 10)`; `k` = overall pick number (snake/linear). An **auction** has no slots: the k-th most
  expensive purchase is treated as overall pick k (price rank), and the price is kept.
* `kind`: the league's **startup** draft (structural: the earliest completed draft of the chain's inaugural
  season) or an **annual** draft (every other draft). Not inferred from who was picked: 2024's second draft and
  the 2025 draft both mixed rookies and veterans.
* `e_kind(b)` — frozen per-week RLS expectation (table below): calibrated once on 2026-09-28, before any Manager
  of the Year result was computed, from observed holder-independent surplus of every selection, weighted by
  observed weeks, with weighted isotonic (non-increasing) regression. Bands past a table's end use its last
  entry.

| band (overall picks) | annual raw | **annual frozen** | startup raw | **startup frozen** |
|---|---|---|---|---|
| 1 (1–10) | 5.790 | **5.790** | 12.578 | **12.578** |
| 2 (11–20) | 3.003 | **3.003** | 9.122 | **9.122** |
| 3 | 0.737 | **1.802** | 7.6815 | **7.681** |
| 4 | 1.050 | **1.802** | 5.950 | **7.351** |
| 5 | 2.724 | **1.802** | 6.636 | **7.351** |
| 6 | 1.604 | **1.802** | 9.467 | **7.351** |
| 7 | 1.671 | **1.802** | 5.585 | **6.408** |
| 8 | 3.878 | **1.802** | 7.230 | **6.408** |
| 9 | 2.531 | **1.802** | 5.656 | **5.656** |
| 10 | 1.189 | **1.189** | 3.895 | **5.034** |
| 11–24 | — | (1.189) | 6.173, 4.899, 3.015, 3.536, 4.289, 3.980, 3.661, 3.561, 4.741, 3.312, 4.546, 1.505, 2.195, 3.740 | 5.034, 4.899, 3.845 ×9, 2.424 ×3 |

Annual population: 2024 annual draft (100 selections) + 2025 annual draft (70) — 170 selections, 1,887 observed
weeks. Startup population: the 2024 startup draft (240 selections, 24 bands of 10). **Both are in-sample for the
seasons they were calibrated on**, and there is no comparable startup history at all; 2026+ annual drafts are
out-of-sample. Stated, not hidden (§10 OD-MOTY-4).

Properties: 1.01 is not automatically the best draft (it is measured against band 1's expectation); a manager with
no selections has D = 0 net → 50 (the trade ledger holds whatever they did with the picks); a missing draft is
reported as missing, never "no activity". **D's future-value channel is not implemented in v1**: no decision-time
pick or rookie valuation exists for any replayed draft (all precede the 2026-07-14 history floor). D is labelled
`partial`.

### 5.7 W — waiver / free-agent and roster management (weight 0.15)

The W credits and charges of §5.3: surplus produced by waiver / FA acquisitions while held, minus the surplus of
baseline or drafted players the manager dropped (observed where re-rostered). Bench-only above-replacement weeks
count as depth (§5.1 limitation). No-surplus pickups earn nothing. Drop/re-add is neutral by construction.

**FAAB.** FAAB spent on completed window claims is reported (`faabSpent`, `faabSpentPct` of the season's
original budget) and is **not converted to points**. Within a season the budget expires and has no other use, so
its opportunity cost is already inside W: overspending on one player forgoes other acquisitions whose surplus
then never appears. A separate FAAB charge would count that cost twice. Expensive and cheap equivalent pickups
are therefore distinguished in the published raw metrics (and the plain-English summary says "low-cost" when the
manager spent at or below the league median), not in the score. A scored FAAB charge would need an owner-approved
conversion basis (§10 OD-MOTY-2).

**W's future-value channel is not implemented in v1** (no existing validated method; pre-2026-07-14 moves have
no decision-time values). W is labelled `partial`.

## 6. Frozen parameters (v1)

| name | value | where |
|---|---|---|
| weights | A .40, T .25, W .15, D .10, P .10 | `WEIGHTS` |
| provisional denominator | 0.90 | `NON_POSTSEASON_WEIGHT` |
| KAPPA | 0.5 (weekly team-score SDs) | `KAPPA` |
| FV % scale | 25 (canonical "Clear win" band edge) | `FV_PCT_SCALE` |
| production share inside a two-channel subscore | 0.5 | `PRODUCTION_SHARE` |
| draft band size | 10 picks | `DRAFT_BAND_SIZE` |
| annual / startup expectation tables | §5.6 | `ANNUAL_BAND_EXPECTATION`, `STARTUP_BAND_EXPECTATION` |
| first official season | none (candidate only) | `OFFICIAL_FROM_SEASON = None` |

## 7. Ties

Full precision. Exact ties are broken by (1) higher combined T/W/D weighted contribution, then (2) higher A; a
tie on all three is an honest shared rank (`tied: true`). Never owner id, name or array order.

## 8. Coverage and uncertainty (published per season and per channel)

* `coverage.status` — `complete` or `partial`; `coverage.reasons` names each gap:
  `trade_future_value_{unavailable|partial}`, `waiver_future_value_not_implemented`,
  `draft_future_value_not_implemented`, `window_baseline_unavailable`, `ledger_reconciliation_gaps`.
* `coverage.tradeFutureValue` — status, trades, valuedTrades.
* `coverage.reconciliation` — player-weeks the ledger could not explain (held without an acquisition event;
  missing without an exit event), and roster-weeks absent.
* per manager, per channel — `coverage`, `productionScore`, `futureValueScore`, and `unobservedWeeks`.
* model-valued future assets: v1 scores none; when the FV-channel becomes scoreable its inputs are the canonical
  board's as-of values, which carry their own confidence (`src/api/confidence.py`) — v1 does not propagate it
  into the award, and says so here.

## 9. Official vs candidate; historical records

`OFFICIAL_FROM_SEASON = None`. Therefore:

* **Completed seasons (2024, 2025)** keep their existing official Manager of the Year winner (the legacy
  composite, `awards._manager_of_the_year_scores`) exactly as published before this unit. The unified result is
  attached to that award as `unifiedCandidate` and published in the season's `managerOfTheYear` block, labelled
  candidate. No trophy record is rewritten.
* **The live season (2026)** — its race and award card show the unified **provisional** score (a live leader is
  not an official record), with the method version and the candidate label.
* Promotion is a deliberate edit of `OFFICIAL_FROM_SEASON` (and a method-version bump if anything else changes),
  after owner review of this record — never automatic. A season is official only when its coverage is `complete`
  and P is final.

## 10. Remaining owner decisions

* **OD-MOTY-1 — promotion.** Whether (and from which season) the unified award becomes official, and whether
  2024/2025 may ever be re-awarded under it given their permanent `partial` coverage (§11.1).
* **OD-MOTY-2 — FAAB.** Keep FAAB as context only (v1), or approve a conversion basis for a scored cost.
* **OD-MOTY-3 — counted vs depth surplus.** v1 credits above-replacement depth weeks; scoring only counted starts
  needs a per-week slot-structure and game-time-holding record the evidence does not have for 2025.
* **OD-MOTY-4 — draft expectation.** The expectation tables are in-sample for 2024/2025; the startup table has no
  comparable history. Accept, or require an external slot-expectation benchmark.
* **OD-MOTY-5 — unobserved surrendered weeks.** Materialize weekly scores for unrostered players (host stat lines
  scored under the league card) so W's charge side is complete, or accept the documented bias (§11.3).
* **OD-MOTY-6 — future-value channels.** Public/private boundary: the FV-channel publishes only derived scores.
  Approve the T FV-channel for scoring once a season has complete decision-time coverage (first possible: 2027),
  and decide whether W/D future value should be built.
* **OD-MOTY-7 — T without its future-value half (found in the replay, §11.4).** Production-only T penalizes
  rebuilding trades and rewards win-now trades whose surrendered picks cannot be valued. Choose a repair (§11.4)
  before the unified race is released publicly or promoted.

## 11. Data / coverage audit and historical replay

§11.1 is the Phase 1 audit (evidence inventory; no scores). §11.2–§11.4 are appended after the freeze.

### 11.1 Coverage audit (Phase 1)

Evidence as held by the public-league snapshot (`data/public_league/snapshot.json`, generated
2026-09-26T07:15Z — the latest snapshot whose 2026 finished weeks are exactly the host's `last_scored_leg = 2`),
cross-checked against a fresh 2026-09-29 pull for 2024/2025 (identical).

| evidence | 2024 (`1090320428817592320`) | 2025 (`1180092661344120832`) | 2026 (`1312006700437352448`), through week 2 |
|---|---|---|---|
| teams | 10 | 10 | 12 (expansion rosters 11, 12 stocked by 23 commissioner moves, 2026-01-05) |
| lineup mode (measured, not the setting) | **manager-set** (0/130 regular-season team-weeks optimal; mean 62.7 pts below the week-end optimal lineup) | best ball (mean 2.5-pt gap from mid-week roster timing / IR) | best ball (exact on finished weeks) |
| finished regular-season weeks | 1–13 | 1–13 | 1–2 |
| official team-week scores | 130/130 | 130/130 | 24/24 |
| player scores (starters + bench, `players_points`) | every rostered player, every week | same | same |
| replacement levels (VORP board) | all positions except FB (thin band) | all | all |
| window transactions (trade / waiver+FA / commissioner) | 28 / 218 / 2 | 124 / 581 / 1 | 67 / 279 / 23 |
| window baseline | inaugural (empty) | 2024 final rosters | 2025 final rosters; rosters 11–12 empty |
| ledger reconciliation gaps | 0 | 13 player-weeks (1 player, no exit event) | 0 |
| drafts | startup snake 240 + annual snake 100 | annual linear 70 | annual **auction** 84 (prices); a second auction with 0 selections |
| current-draft picks traded (priced via §5.5) | 26 | 22 | 22 |
| future picks traded (FV-channel only) | 17 | 122 | 54 |
| FAAB | budget 1000; 2,859 spent; 125 traded | budget 200; 1,732 spent; 4 FAAB trades | budget 100; 683 spent; 5 traded |
| surrendered-player weeks unobservable (charge side) | W 364 · T 4 | W 833 · T 102 | W 118 · T 4 |
| drafted-player weeks unobservable | 368 of 4,420 | 59 of 910 | 18 of 168 |
| decision-time dynasty valuations (temporal ledger, floor 2026-07-14) | **none** | **none** | 30 of 67 window trades after the floor; the 37 offseason trades and the May auction precede it |
| decision-time pick valuations | none | none | none for the May 2026 draft; post-floor future picks only |
| scoring settings | current card only; `players_points` are the host's scores at the time | same | same |
| winners bracket | resolved, 5 entrants | resolved, 5 entrants | pending (7 entrants) |
| `exports/archive` | starts 2026-07-14 | — | from 2026-07-14 |

**Consequences.** A, P and every production channel are fully computable for all three seasons (with the counted
unobservable weeks). No future-value channel can be scored for 2024 or 2025 — **ever**, with current evidence:
decision-time valuations do not exist and today's rankings may not stand in for them. For 2026 the T FV-channel is
partial (the offseason trades precede the history floor). Every season is therefore `partial`, and no season can
produce a fully comparable official winner under v1.

### 11.2 Historical replay (run after the freeze, against the frozen v1 code)

Command: `python scripts/replay_manager_of_the_year.py --snapshot data/public_league/snapshot.json` (the
2026-09-26 snapshot, so 2026 is exactly the host-finalized weeks 1–2). No valuation source is supplied offline,
so the trade future-value channel reports `unavailable` in every season — which is also its production answer
for 2024/2025, and a `partial` answer for 2026 (30 of 67 window trades post-date the history floor). Columns:
record, legacy composite (legacy rank), component scores 0–100, contributions out of 40/25/15/10/10, unified
score, raw nets in replacement-level-surplus points, unobservable player-weeks. "pend" = P pending.

#### 2026 — provisional (as of week 2), coverage partial

| # | manager | rec | legacy (rank) | A | T | W | D | P | contrib A/T/W/D/P | score | T net | W net | D net | unobs |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Brent | 3-1 | 0.779 (1) | 95.5 | 67.6 | 93.5 | 50.0 | — | 38.2/16.9/14.0/5.0/pend | 82.33 | 22.1 | 80.1 | 0.0 | 17 |
| 2 | Eric | 2-2 | 0.583 (4) | 59.1 | 99.1 | 81.0 | 50.0 | — | 23.6/24.8/12.1/5.0/pend | 72.84 | 141.6 | 43.5 | 0.0 | 13 |
| 3 | Joey | 4-0 | 0.763 (2) | 81.8 | 53.0 | 43.7 | 62.6 | — | 32.7/13.2/6.6/6.3/pend | 65.33 | 3.6 | -7.6 | 15.5 | 4 |
| 4 | Kich | 2-2 | 0.546 (5) | 63.6 | 51.0 | 74.1 | 27.2 | — | 25.5/12.7/11.1/2.7/pend | 57.82 | 1.2 | 31.6 | -29.6 | 17 |
| 5 | jstuedle | 1-3 | 0.369 (10) | 50.0 | 50.0 | 92.4 | 41.2 | — | 20.0/12.5/13.9/4.1/pend | 56.09 | 0.0 | 75.2 | -10.7 | 2 |
| 6 | Jason | 3-1 | 0.511 (6) | 59.1 | 47.4 | 71.2 | 14.4 | — | 23.6/11.9/10.7/1.4/pend | 52.90 | -3.1 | 27.2 | -53.5 | 6 |
| 7 | Ty | 2-2 | 0.380 (8) | 40.9 | 81.0 | 50.0 | 31.0 | — | 16.4/20.2/7.5/3.1/pend | 52.45 | 43.5 | 0.0 | -24.0 | 4 |
| 8 | Blaine | 1-3 | 0.378 (9) | 13.6 | 80.3 | 91.3 | 35.4 | — | 5.5/20.1/13.7/3.5/pend | 47.53 | 42.3 | 70.8 | -18.0 | 7 |
| 9 | Ed | 2-2 | 0.460 (7) | 45.5 | 34.6 | 54.2 | 46.6 | — | 18.2/8.7/8.1/4.7/pend | 44.03 | -19.1 | 5.0 | -4.1 | 30 |
| 10 | MaKayla | 3-1 | 0.610 (3) | 50.0 | 8.8 | 68.9 | 35.9 | — | 20.0/2.2/10.3/3.6/pend | 40.16 | -70.1 | 23.9 | -17.4 | 25 |
| 11 | Collin | 1-3 | 0.258 (11) | 27.3 | 24.9 | 27.9 | 44.3 | — | 10.9/6.2/4.2/4.4/pend | 28.62 | -33.2 | -28.5 | -6.9 | 15 |
| 12 | Roy | 0-4 | 0.145 (12) | 13.6 | 1.5 | 64.3 | 38.0 | — | 5.5/0.4/9.6/3.8/pend | 21.41 | -125.7 | 17.6 | -14.7 | 2 |

Legacy winner: Brent · unified winner: Brent · changed: False
#### 2025 — final (as of week 13), coverage partial

| # | manager | rec | legacy (rank) | A | T | W | D | P | contrib A/T/W/D/P | score | T net | W net | D net | unobs |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Brent | 21-5 | 0.963 (1) | 83.8 | 95.9 | 98.5 | 45.4 | 80.0 | 33.5/24.0/14.8/4.5/8.0 | 84.80 | 515.0 | 675.7 | -29.9 | 196 |
| 2 | Ed | 15-11 | 0.764 (2) | 53.0 | 82.7 | 86.7 | 52.3 | 100.0 | 21.2/20.7/13.0/5.2/10.0 | 70.10 | 254.7 | 304.4 | 15.0 | 137 |
| 3 | Joey | 15-11 | 0.630 (4) | 54.7 | 72.6 | 77.6 | 49.2 | 50.0 | 21.9/18.1/11.6/4.9/5.0 | 61.58 | 158.2 | 202.1 | -5.0 | 81 |
| 4 | MaKayla | 15-11 | 0.654 (3) | 55.6 | 42.1 | 87.4 | 42.4 | 50.0 | 22.2/10.5/13.1/4.2/5.0 | 55.10 | -51.9 | 315.8 | -49.9 | 84 |
| 5 | Kich | 11-15 | 0.420 (7) | 47.9 | 79.9 | 81.3 | 30.8 | 0.0 | 19.1/20.0/12.2/3.1/0.0 | 54.40 | 224.7 | 239.1 | -131.7 | 83 |
| 6 | Eric | 8-18 | 0.341 (8) | 41.0 | 79.7 | 91.5 | 40.5 | 0.0 | 16.4/19.9/13.7/4.0/0.0 | 54.11 | 222.5 | 386.8 | -62.6 | 130 |
| 7 | Ty | 15-11 | 0.507 (6) | 47.9 | 34.5 | 72.5 | 53.0 | 20.0 | 19.1/8.6/10.9/5.3/2.0 | 45.94 | -104.4 | 157.8 | 19.2 | 40 |
| 8 | Roy | 10-16 | 0.295 (9) | 43.6 | 29.7 | 85.9 | 45.9 | 0.0 | 17.4/7.4/12.9/4.6/0.0 | 42.34 | -140.0 | 294.2 | -26.7 | 35 |
| 9 | Collin | 13-13 | 0.513 (5) | 41.0 | 17.8 | 92.4 | 47.4 | 0.0 | 16.4/4.5/13.9/4.7/0.0 | 39.45 | -249.0 | 405.5 | -17.0 | 68 |
| 10 | Jason | 7-19 | 0.144 (10) | 31.6 | 1.6 | 84.3 | 35.0 | 0.0 | 12.6/0.4/12.6/3.5/0.0 | 29.19 | -675.1 | 273.9 | -100.5 | 140 |

Legacy winner: Brent · unified winner: Brent · changed: False
#### 2024 — final (as of week 13), coverage partial

| # | manager | rec | legacy (rank) | A | T | W | D | P | contrib A/T/W/D/P | score | T net | W net | D net | unobs |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Ty | 21-5 | 0.841 (1) | 81.2 | 66.1 | 93.9 | 98.3 | 50.0 | 32.5/16.5/14.1/9.8/5.0 | 77.92 | 95.0 | 389.3 | 572.9 | 68 |
| 2 | Roy | 17-9 | 0.785 (2) | 66.7 | 49.1 | 94.4 | 63.6 | 80.0 | 26.7/12.3/14.2/6.4/8.0 | 67.47 | -4.9 | 401.5 | 79.5 | 144 |
| 3 | Joey | 14-12 | 0.654 (3) | 53.0 | 50.0 | 85.2 | 79.1 | 100.0 | 21.2/12.5/12.8/7.9/10.0 | 64.38 | 0.0 | 248.3 | 189.0 | 104 |
| 4 | MaKayla | 15-11 | 0.626 (4) | 55.6 | 57.3 | 87.0 | 62.5 | 50.0 | 22.2/14.3/13.0/6.2/5.0 | 60.84 | 41.7 | 270.1 | 72.4 | 86 |
| 5 | Ed | 12-14 | 0.455 (5) | 42.7 | 70.1 | 85.6 | 12.0 | 20.0 | 17.1/17.5/12.8/1.2/2.0 | 50.66 | 121.4 | 253.4 | -283.7 | 44 |
| 6 | Collin | 10-16 | 0.325 (8) | 52.1 | 47.6 | 78.7 | 59.5 | 0.0 | 20.9/11.9/11.8/6.0/0.0 | 50.50 | -13.9 | 185.9 | 54.9 | 40 |
| 7 | Jason | 11-15 | 0.364 (7) | 41.0 | 51.1 | 88.9 | 46.5 | 0.0 | 16.4/12.8/13.3/4.7/0.0 | 47.17 | 6.1 | 296.1 | -19.7 | 138 |
| 8 | Eric | 9-17 | 0.258 (9) | 38.5 | 43.4 | 88.9 | 14.2 | 0.0 | 15.4/10.8/13.3/1.4/0.0 | 40.98 | -37.8 | 295.5 | -255.6 | 81 |
| 9 | Bwalk903 | 11-15 | 0.374 (6) | 37.6 | 50.9 | 70.4 | 7.9 | 0.0 | 15.0/12.7/10.6/0.8/0.0 | 39.11 | 4.9 | 123.1 | -349.2 | 28 |
| 10 | SheriffB | 10-16 | 0.156 (10) | 31.6 | 27.7 | 50.0 | 91.0 | 0.0 | 12.6/6.9/7.5/9.1/0.0 | 36.17 | -136.5 | 0.0 | 329.1 | 4 |

Legacy winner: Ty · unified winner: Ty · changed: False


**Winners.** Unchanged in every season: 2024 Ty (legacy and unified), 2025 Brent (both), 2026-to-date Brent (both,
provisional). **Rank changes** come from what the legacy composite did not measure (it min-max'd raw points
gained from trades/waivers, ignored outgoing players after they left, drafting and future value, and rewarded
record and finish twice):

* 2025 — Kich 7th → 5th and Eric 8th → 6th (both non-playoff: T ≈ 80 and W 81–92 outweigh P = 0, ahead of
  playoff team Ty); Collin 5th → 9th (T 17.8: −249 net surplus from trades); MaKayla 3rd → 4th.
* 2024 — Collin 8th → 6th (non-playoff, 0.16 behind playoff team Ed); Bwalk903 6th → 9th (D 7.9: −349 vs slot
  expectation); SheriffB stays 10th with D 91.0.
* 2026 — Eric 4th → 2nd (T 99.1, W 81.0); MaKayla 3rd → 10th (T 8.8: −70 net surplus after two weeks);
  jstuedle 10th → 5th (W 92.4).

No non-playoff manager reached the top three in 2024 or 2025; the synthetic tests show one can when the formula
places them first.

### 11.3 Sensitivity (counterfactual re-scorings of the same frozen raw measurements)

| perturbation | 2024 | 2025 | 2026 (wk 2) |
|---|---|---|---|
| each weight ±0.05 (others rescaled) | 0/10 winner changes, min τ 0.91 | 0/10, min τ 0.91 | 0/8 (P pending), min τ 0.97 |
| KAPPA 0.25 / 1.0 | no change, τ 0.96 / 0.96 | no change, τ 0.91 / 1.00 | no change, τ 0.94 / 0.94 |
| draft table leave-one-season-out | no change, τ 0.96 | no change, τ 1.00 | (table already out-of-sample) |
| W unobservable weeks imputed at the mean observed charge (1.99–2.38 pts/wk) | no change, τ 1.00 | no change, τ 1.00 | no change, τ 0.97 |
| **proposed repair OD-MOTY-7** (drop trades that moved a future pick from T) | no change, τ 0.96 | no change, **τ 0.73** | **leader → Eric**, τ 0.82 |
| share of T/W credit earned in counted-lineup weeks (OD-MOTY-3) | 58.6% (manager-set lineups) | 94.8% | 89.0% |

The winners are stable to every weight, scale, calibration and imputation perturbation tested. They are **not**
stable to the treatment of future-pick trades — §11.4.

### 11.4 Anti-gaming results and the one pathology found

Real data (Spearman ρ, 2024 / 2025 / 2026):

* **Trade volume does not buy T:** ρ(trade count, T) = 0.41 / −0.14 / −0.31.
* **Waiver volume correlates with W:** ρ(waiver/FA moves, W) = 0.67 / 0.70 / 0.70. A move earns only what its
  player produces above replacement (a no-value move earns exactly 0 — tested), so this is active managers
  finding production, not a per-move bonus. W carries 15%, and the imputation stress does not move a winner.
  Reported, not hidden.
* **Draft position does not buy D:** ρ(mean draft band, D) = 0.25 / −0.01 / −0.01.
* **A vs management:** ρ = 0.93 / 0.62 / 0.32. 2024 is structural: the inaugural roster is built entirely by the
  startup draft, so construction and competition coincide.
* **Unified vs legacy:** ρ = 0.92 / 0.83 / 0.70.

**Pathology (OD-MOTY-7) — exact counterexamples.** With the trade future-value channel unavailable, T is
production-only, so a rebuilding trade is scored on the only side that can be measured:

* **2026, Roy** (0-4 at week 2): 10 window trades, 19 players out / 8 in, **11 future firsts received, 0 sent** →
  T 1.5 (−125.7 net surplus in two weeks); summary "trades that cost value".
* **2025, Jason** (7-19): 99 trades, future picks 76 received / 32 sent (firsts 15 / 7) → T 1.6 (−675 net).
* Mirror image: **2025, Brent** sent 14 future picks (3 firsts), received 3 → T 95.9.

This is what directive §5 forbids ("a rebuilding trade is not penalized because a received pick scored 0
points; a win-now trade is not given full production credit while surrendered future assets vanish"). The
production channel is correct; the defect is scoring T while its future-value half is missing. v1 is frozen,
so the policy is **not** changed here. Proposed repairs, for owner decision:

1. *Exclude future-pick trades from T until the FV-channel is complete* (the replayed repair above): symmetric,
   missing-not-zero; it reshuffles 2025 (τ 0.73), changes the 2026 leader, and does not fully rescue Roy (T 10.8 —
   his player-for-player trades also lost surplus).
2. *Do not score T for a season whose FV-channel is incomplete* (declared season-wide, published as
   `T: unavailable`; the outer formula needs an owner rule for the missing 25%).
3. *Accept v1* with the published partial-coverage label.

2024/2025 can never have decision-time valuations, so repairs 1–2 are the only way their T satisfies §5.
**Recommendation: do not release the live 2026 unified race publicly until OD-MOTY-7 is decided.** Historical
seasons are unaffected either way: their official winners stay legacy.

## 12. Tests and verification

* `tests/public_league/test_manager_of_the_year.py` — 41 tests: normalization (zero → 50, bounded, monotonic,
  symmetric, unscalable → None); non-playoff / below-.500 manager can win; exceptional champion can win;
  championship worth at most 10; no "outside the race" field; all-play independent of the schedule; tie / zero /
  negative / missing-week semantics; no-trade exactly neutral; bad trades negative and mirrored; star for
  excessive capital negative; round trips and re-acquisition cannot manufacture value; trade count earns nothing;
  drop/re-add cycling neutral with unknown weeks counted; no-value pickups earn nothing; expensive vs cheap
  equivalent pickups (same score, distinguished raw cost and summary); dropping a productive player is charged;
  1.01 not automatically best; no picks neutral; traded pick not credited twice; drafted-then-traded player keeps
  D; auction price-rank bands; the channel sum telescopes to `u(R) − u(B0) − E`; best-ball start/sit earns
  nothing; no postseason management weeks; missing history ≠ no trades; inaugural baseline; a stat correction
  changes exactly the affected result; actual-bracket P (same-stage ties, no bye wins, placement games ignored);
  unresolved bracket pending + provisional; final formula; exact ties (management → A → shared; never id/order);
  trade future value (future picks are not zero benefit; both sides valued at the trade's instant; a missing
  valuation → no fake precision; no source → unavailable); every other award byte-identical (League MVP asserted
  by name); completed seasons keep their legacy official winner.
* **Sabotage:** 16 engine/award mutations — gross incoming, re-credited re-acquisition, no slot expectation, pick
  expectation not moved, unobservable as zero, placement tie-breaks, unresolved bracket as zero, owner-id
  tie-break, postseason moves, missing history as no trades, FV ignored, partial FV scored, FAAB converted,
  min-max, MOTY mutating shared data, completed season re-awarded — **16/16 turned the named tests red**. Two
  first-draft mutations were ineffective (they hit redundant code) and were replaced; recorded, not counted.
  Frontend 3/3 (raw metric from the wrong field, breakdown removed, contribution recomputed client-side).
* `frontend/__tests__/components/manager-of-the-year-card.test.jsx` — 6 tests (backend numbers only,
  40/25/15/10/10 contributions, provisional/candidate labels, coverage and unobservable weeks, tied ranks, one
  card beside — not inside — the history button, no GM card).
* Real snapshot: every award other than Manager of the Year is byte-identical to `main` (full-section diff).
* Performance: awards section build (3 seasons, real snapshot) median 0.250 s → 0.306 s (+56 ms), once per
  snapshot generation (heavy-section and contract-bytes caches), never per request. Awards payload +55 KB raw /
  +10 KB gzip.

## 13. Known canonical-owner finding (not changed here)

`metrics.final_regular_season_weeks` admitted the in-progress 2026 week 3 on the evening of 2026-09-28 through
its data-completeness proof (all 12 rosters had non-zero Sunday scores while Monday night was unplayed; host
`last_scored_leg` = 2). Every awards, Luck and Power consumer inherits it; this unit uses the canonical rule
unchanged and replays 2026 from the week-2 snapshot. Owner: `src/public_league/metrics.py` (separate claim).
