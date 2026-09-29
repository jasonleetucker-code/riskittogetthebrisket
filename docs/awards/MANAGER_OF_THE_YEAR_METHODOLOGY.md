# Unified Manager of the Year — methodology record (v1 candidate)

**Status:** CANDIDATE METHODOLOGY — implemented, replayed, **not promoted**. Official historical winners are
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
