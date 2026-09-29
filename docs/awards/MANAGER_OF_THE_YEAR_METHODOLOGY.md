# Unified Manager of the Year — methodology record (VALIDATION TRACK)

**Status:** **VALIDATION TRACK — PARTIAL / NOT PROMOTED.** Implemented and replayed; **not** the official award in
any season (§9). Owner direction 2026-09-29: keep it a validation track until net trade / waiver / draft value
accounting is defensible; do not promote because tests pass; do not tune weights toward a preferred winner.
**Method version:** `moty-unified-v1.1-2026-09-29` (v1 `moty-unified-v1-2026-09-28` + the OD-MOTY-7 rule of §11.5:
T is **unavailable**, not production-only, while its future-value half cannot be measured).
**Owner decision:** 2026-09-28, recorded in `docs/OWNER_REQUESTED_TODO.md` ("ONE unified Manager of the Year").
**Implementation:** `src/public_league/manager_of_the_year.py` (engine), wired through
`src/public_league/awards.py` (the canonical awards owner), rendered by
`frontend/app/league/sections/manager-of-the-year.jsx` beside the existing Manager of the Year card.
**Freeze:** every definition and parameter in §1–§8 was written and committed **before** any season's
Manager of the Year result was computed. The replay (§11) was run afterwards against the frozen code. A change
to anything in §1–§8 is a methodology change and bumps the method version — v1.1 is exactly such a change, made
because the v1 replay exposed OD-MOTY-7 (§11.4), and it was decided from the evidence audit (§11.0), **not** from
who wins (the leaders are unchanged by it in every season).

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
* **Unscored** — any of A/W/D is unmeasurable for that manager (e.g. no finished week yet): the row publishes
  its components and no score. Never 0, never 50.
* **Incomplete** (v1.1) — T is **unavailable** for the season (its future-value half cannot be measured, §5.5 /
  §11.5). No Manager of the Year score exists. Each row publishes `incomplete = {measuredPoints,
  measurablePoints, measuredComponents, unscoredComponents}`: the frozen weights applied to the components that
  **were** measured, out of the points those components can earn (65 while P is pending, 75 once P is final).
  T's 25 points are **missing, not redistributed** — nothing is divided by 0.75. Rows get a *validation* rank on
  `measuredPoints` (same denominator for every manager, because T availability is season-wide), and the
  evaluation publishes `unscoredTradeRange` — every manager the unscored T (up to 25 points) could put first.
* **Promotion** — `promotion: not_promoted` until the owner promotes the method (OD-MOTY-1); `official` is true
  only for a promoted season with complete coverage and a final P.
* **Coverage** — `complete` only when every channel below is fully measurable for the season; otherwise
  `partial`, with machine-readable reasons (§8).
* **Official** — see §9. Every season's unified result is a **validation-track candidate** (PARTIAL / NOT PROMOTED).

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

`T = 0.5 · P-channel + 0.5 · FV-channel` when the FV-channel is complete for the season (the 50/50 candidate).
**Otherwise T is UNAVAILABLE (v1.1)** — `score: null`, `coverage: unavailable`, `unscoredReason:
trade_future_value_{partial|unavailable}` — and the P-channel is published only as labelled context
(`productionScore`), excluded from every total. (v1 used `T = P-channel` here; the replay showed that scores one
side of every exchange — §11.4.) A season with **no** window trades has nothing unmeasured and is complete by
construction (T = 50) whether or not a valuation source is supplied. FAAB moved in trades is reported
(`faabTradedNet`), not converted — and because FAAB has no approved value basis (OD-MOTY-2), a trade that moves
FAAB counts as **unvalued** in the FV-channel (never "valued without its FAAB half"), so a season with one cannot
reach a complete T.
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
| first official season | none (validation track only) | `OFFICIAL_FROM_SEASON = None` |
| T while its FV half is incomplete | **unavailable** (v1.1); nothing redistributed | `_trade_score`, `BASIS_INCOMPLETE` |

## 7. Ties

Full precision. Exact ties are broken by (1) higher combined T/W/D weighted contribution, then (2) higher A; a
tie on all three is an honest shared rank (`tied: true`). Never owner id, name or array order.

## 8. Coverage and uncertainty (published per season and per channel)

* `coverage.status` — `complete` or `partial`; `coverage.reasons` names each gap:
  `trade_future_value_{unavailable|partial}`, `trade_component_unscored` (v1.1), `waiver_future_value_not_implemented`,
  `draft_future_value_not_implemented`, `window_baseline_unavailable`, `ledger_reconciliation_gaps`.
* `coverage.tradeFutureValue` — status, trades, valuedTrades.
* `scoreBasis` — `full` | `incomplete` | `none`; `promotion` — `not_promoted` | `promoted`;
  `unscoredTradeRange` — on an incomplete basis, `{tMaxPoints, couldLeadUnderSomeT, leaderDetermined}`.
* `coverage.reconciliation` — player-weeks the ledger could not explain (held without an acquisition event;
  missing without an exit event), and roster-weeks absent.
* per manager, per channel — `coverage`, `productionScore`, `futureValueScore`, and `unobservedWeeks`.
* model-valued future assets: v1 scores none; when the FV-channel becomes scoreable its inputs are the canonical
  board's as-of values, which carry their own confidence (`src/api/confidence.py`) — v1 does not propagate it
  into the award, and says so here.

## 9. Official vs candidate; historical records

`OFFICIAL_FROM_SEASON = None`. Therefore, in **every** season (v1.1, owner direction 2026-09-29):

* The Manager of the Year **card and race** are the existing method's (the legacy composite,
  `awards._manager_of_the_year_scores` — no playoff or record gate), byte-identical to `main`. Completed seasons
  keep their existing official winner; the live season's race is the existing race. (v1 let the unified
  *provisional* result drive the live 2026 card and race; that presented an unpromoted candidate as the award and
  is withdrawn.)
* The unified evaluation rides **beside** the card as `unifiedCandidate` (award) and the season's
  `managerOfTheYear` block, labelled **"Validation track — PARTIAL / NOT PROMOTED"**, never "Final", never
  "Provisional score", never a score out of 100 while T is unavailable.
* Promotion is a deliberate edit of `OFFICIAL_FROM_SEASON` (and a method-version bump if anything else changes),
  after owner review of this record — never automatic. A season is official only when its coverage is `complete`
  and P is final. `_moty_is_live` is the one switch and is test-pinned.

## 10. Remaining owner decisions

* **OD-MOTY-1 — promotion.** Whether (and from which season) the unified award becomes official, and whether
  2024/2025/2026 may ever be re-awarded under it: under current evidence none of them can reach `complete`
  (§11.0), so under §9 none can become official.
* **OD-MOTY-2 — FAAB.** Keep FAAB as context only (v1), or approve a conversion basis for a scored cost.
* **OD-MOTY-3 — counted vs depth surplus.** v1 credits above-replacement depth weeks; scoring only counted starts
  needs a per-week slot-structure and game-time-holding record the evidence does not have for 2025.
* **OD-MOTY-4 — draft expectation.** The expectation tables are in-sample for 2024/2025; the startup table has no
  comparable history. Accept, or require an external slot-expectation benchmark.
* **OD-MOTY-5 — unobserved surrendered weeks.** Materialize weekly scores for unrostered players (host stat lines
  scored under the league card) so W's charge side is complete, or accept the documented bias (§11.3).
* **OD-MOTY-6 — future-value channels.** Public/private boundary: the FV-channel publishes only derived scores.
  Approve the T FV-channel for scoring once a season has complete decision-time coverage (first possible: 2027 —
  §11.0), and decide whether W/D future value should be built.
* **OD-MOTY-7 — T without its future-value half.** *Interim rule applied in v1.1 (§11.5): T unavailable, measured
  points + validation rank, nothing redistributed.* The owner confirms or replaces it.
* **OD-MOTY-8 — the outer result while T is unavailable (new).** v1.1 publishes **no** Manager of the Year score
  and ranks on measured points out of 65/75. The owner decides whether that validation rank may be shown to the
  league at all (it is labelled and never official, but the top two are within T's 25 points in every replayed
  season, so the evidence does not decide the leader — §11.2), or whether the card should show the components only.
* **OD-MOTY-9 — W and D are still production-only (new).** Their future-value halves are not implemented (§5.6,
  §5.7). v1.1 keeps them scored, labelled `partial`, because unlike a trade their unmeasured side is not the
  counter-consideration of an exchange (a waiver claim's cost is FAAB + a roster spot, reported; a draft pick is
  measured against its own slot's production expectation). A rebuilding manager who drops veterans for stashes is
  still charged in W. The owner decides whether W/D must meet the same "both halves or unavailable" bar as T.
* **OD-MOTY-10 — the card while the method is unpromoted (new).** v1.1 keeps the existing (legacy composite) card
  and race in every season, as on `main`. The owner decides whether that stays, or the card shows "awaiting a
  validated method" instead.

## 11. Data / coverage audit and historical replay

§11.0 is the 2026-09-29 evidence audit behind v1.1 (what historical evidence actually exists, measured). §11.1 is
the Phase 1 audit (evidence inventory; no scores). §11.2–§11.5 are appended after the freeze.

### 11.0 Evidence audit — what can be measured, per season and component (2026-09-29)

Sources: the canonical history owner (`src/history/store.py` — `HISTORY_FLOOR = "2026-07-14"`, permanent: writes
before it are refused; `src/history/asof.py::batch_known_before` — instant-strict, never selects a later
observation, answers `before_history_boundary` / `no_prior_observation`), the as-of trade resolver
(`src/api/public_activity_valuation.build_asof_valuation`, which the MOTY FV-channel reuses verbatim), the public
snapshot (2026-09-26T07:15Z), `exports/archive/`, and the **production** public activity feed
(`GET /api/public/league/activity`, generated 2026-09-29T12:23Z), whose per-side trade grades are exactly
`build_asof_valuation` run against the production temporal ledger — the one place the canonical-board lane can be
measured (that lane is recorded on the production host; the repo holds only the archive's vendor/scraper lanes).

**Evidence items**

| evidence | owner / source | 2024 | 2025 | 2026 |
|---|---|---|---|---|
| historical valuation snapshots | temporal ledger; `exports/archive/` (131 bundles, 77 consecutive dates 2026-07-14 → 2026-09-28, no gaps; raw vendor + scraper-blend values) | none (before floor) | none | from 2026-07-14 only; generic-grade future-pick rows ("2027 Round 1") only from C1-U6 (2026-08-16) |
| trade package value at trade time | `build_asof_valuation` → `asof.batch_known_before` (measured on production) | **0 / 29** trades (all `before_history_boundary`) | **0 / 124** | **25 / 69**: 37 offseason trades (2026-01-06 → 07-13) 0 valued; 32 post-floor: 25 valued, 7 not (2026-07-31 → 08-15, every miss a generic-grade future pick — 36 pick assets); every trade from 2026-08-16 on valued (19 / 19) |
| player value at acquisition time | same | none | none | trades: every post-floor player resolved (0 player misses); waiver/FA adds: 131 of 221 window adds post-floor, ≤ 80 with a prior-day archived vendor value (upper bound; canonical lane not readable offline); 90 pre-floor adds: none |
| pick value at trade time | canonical board pick rows via `MarketPickRef` generic grade | none | none | none before 2026-08-16; resolved after |
| future-pick ownership over time | snapshot trade `draft_picks` moves + `traded_picks` | reconstructable (17 future picks traded) | reconstructable (122) | reconstructable (54) |
| draft outcomes | snapshot drafts + weekly `players_points` | measurable (startup 240 + annual 100) | measurable (annual 70) | measurable (auction 84; 2 finished weeks) |
| draft value at decision time (pick / rookie) | temporal ledger | none | none | none (May auction precedes the floor) |
| waiver acquisition cost / FAAB cost | `settings.waiver_bid` on completed claims | measurable (2,859 spent) | measurable (1,732) | measurable (683) — value conversion: no approved basis (OD-MOTY-2) |
| roster improvement | weekly `players` + `players_points` (RLS, §5.1) | measurable (unobservable weeks counted) | measurable | measurable |
| acquisition efficiency | derivable (surplus per FAAB $) | context only, no validated scoring basis | same | same |

Counts: the feed counts every completed trade filed in a league (2024: 29, 2026: 69 at 2026-09-29); the MOTY
window counts those with `leg < playoff_week_start` in the 2026-09-26 snapshot (2024: 28 — one trade was filed in
the postseason; 2026: 67 — two week-3 trades came later). Either way no valuation exists before the floor.

**Per component** (M = measurable, P = partially measurable, N = not measurable)

| component | 2024 | 2025 | 2026 |
|---|---|---|---|
| A — all-play | **M** (130/130 team-weeks) | **M** (130/130) | **M** (24/24 at week 2) |
| T — production half | **M** (4 unobservable charge weeks) | **M** (102) | **M** (4) |
| T — future-value half | **N** (0/28 window trades; permanent) | **N** (0/124; permanent) | **P → never complete** (25/69; the 44 unvalued are permanent: 37 before the floor + 7 before generic pick grades were recorded) |
| W — waiver / roster | **P**: production M (364 unobservable charge weeks); FAAB reported, not convertible; future value N | **P** (833); FV N | **P** (118); FV partially observable (≤ 80/221 adds), no method |
| D — draft | **P**: production vs slot expectation M (in-sample table); decision-time value N | **P** (in-sample) | **P** (out-of-sample table); decision-time value N |
| P — postseason | **M** (resolved, 5 entrants) | **M** | pending (7 entrants) |

**Conclusion.** No complete, defensible trade value is supported for any replayed season: 2024/2025 have no
decision-time valuations at all and never will (the floor is permanent; today's values may not stand in), and
2026's offseason trades and its pre-2026-08-16 pick trades are permanently unvaluable, so 2026's FV-channel can
never be complete. The first season whose whole window can be valued is **2027** (its window opens after the 2026
championship, after both the floor and C1-U6), subject to OD-MOTY-6. Therefore T is made **unavailable** rather
than scored (§11.5) — the task's "if not supported" branch. No other component changed.

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
| decision-time dynasty valuations (temporal ledger, floor 2026-07-14) | **none** | **none** | 30 of 67 window trades after the floor (timestamp count; measured resolution 25 of 69 — §11.0); the 37 offseason trades and the May auction precede it |
| decision-time pick valuations | none | none | none for the May 2026 draft; post-floor future picks only |
| scoring settings | current card only; `players_points` are the host's scores at the time | same | same |
| winners bracket | resolved, 5 entrants | resolved, 5 entrants | pending (7 entrants) |
| `exports/archive` | starts 2026-07-14 | — | from 2026-07-14 |

**Consequences.** A, P and every production channel are fully computable for all three seasons (with the counted
unobservable weeks). No future-value channel can be scored for 2024 or 2025 — **ever**, with current evidence:
decision-time valuations do not exist and today's rankings may not stand in for them. For 2026 the T FV-channel is
partial (the offseason trades precede the history floor). Every season is therefore `partial`, and no season can
produce a fully comparable official winner under v1.

### 11.2 Historical replay — v1.1 (T unavailable)

Command: `python scripts/replay_manager_of_the_year.py --snapshot data/public_league/snapshot.json` against the
2026-09-26T07:15Z snapshot (so 2026 is exactly the host-finalized weeks 1–2). Offline no valuation source is
supplied, so T's FV-channel reports `unavailable`; the production answer is `unavailable` for 2024/2025 and
`partial` (25/69) for 2026 — both make T unavailable under §11.5, so **the offline replay is the production
result**. Columns: record, legacy composite (legacy rank), component scores 0–100 ("n/s" = not scored), the
production half of T as labelled context, measured points / measurable points, raw nets in
replacement-level-surplus points, unobservable player-weeks. "pend" = P pending. v1's tables (production-only T
scored) are in this file's history at commit `526c6659c`.

#### 2026 — provisional (as of week 2), basis incomplete, not_promoted

| # | manager | rec | legacy (rank) | A | T | T production (context, not scored) | W | D | P | measured / measurable | T net | W net | D net | unobs |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Brent | 3-1 | 0.779 (1) | 95.5 | n/s | 67.6 | 93.5 | 50.0 | pend | 57.20 / 65 | 22.1 | 80.1 | 0.0 | 17 |
| 2 | Joey | 4-0 | 0.763 (2) | 81.8 | n/s | 53.0 | 43.7 | 62.6 | pend | 45.55 / 65 | 3.6 | -7.6 | 15.5 | 4 |
| 3 | Eric | 2-2 | 0.583 (4) | 59.1 | n/s | 99.1 | 81.0 | 50.0 | pend | 40.78 / 65 | 141.6 | 43.5 | 0.0 | 13 |
| 4 | Kich | 2-2 | 0.546 (5) | 63.6 | n/s | 51.0 | 74.1 | 27.2 | pend | 39.29 / 65 | 1.2 | 31.6 | -29.6 | 17 |
| 5 | jstuedle | 1-3 | 0.369 (10) | 50.0 | n/s | 50.0 | 92.4 | 41.2 | pend | 37.98 / 65 | 0.0 | 75.2 | -10.7 | 2 |
| 6 | Jason | 3-1 | 0.511 (6) | 59.1 | n/s | 47.4 | 71.2 | 14.4 | pend | 35.75 / 65 | -3.1 | 27.2 | -53.5 | 6 |
| 7 | MaKayla | 3-1 | 0.610 (3) | 50.0 | n/s | 8.8 | 68.9 | 35.9 | pend | 33.93 / 65 | -70.1 | 23.9 | -17.4 | 25 |
| 8 | Ed | 2-2 | 0.460 (7) | 45.5 | n/s | 34.6 | 54.2 | 46.6 | pend | 30.97 / 65 | -19.1 | 5.0 | -4.1 | 30 |
| 9 | Ty | 2-2 | 0.380 (8) | 40.9 | n/s | 81.0 | 50.0 | 31.0 | pend | 26.97 / 65 | 43.5 | 0.0 | -24.0 | 4 |
| 10 | Blaine | 1-3 | 0.378 (9) | 13.6 | n/s | 80.3 | 91.3 | 35.4 | pend | 22.70 / 65 | 42.3 | 70.8 | -18.0 | 7 |
| 11 | Collin | 1-3 | 0.258 (11) | 27.3 | n/s | 24.9 | 27.9 | 44.3 | pend | 19.53 / 65 | -33.2 | -28.5 | -6.9 | 15 |
| 12 | Roy | 0-4 | 0.145 (12) | 13.6 | n/s | 1.5 | 64.3 | 38.0 | pend | 18.89 / 65 | -125.7 | 17.6 | -14.7 | 2 |

Validation leader: **Brent** (existing method: Brent). Top-two margin 11.66 measured pts < T's 25 unscored pts → **leader not determined by the evidence**; could lead under some T: Brent, Joey, Eric, Kich, jstuedle, Jason, MaKayla.

#### 2025 — final (as of week 13), basis incomplete, not_promoted

| # | manager | rec | legacy (rank) | A | T | T production (context, not scored) | W | D | P | measured / measurable | T net | W net | D net | unobs |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Brent | 21-5 | 0.963 (1) | 83.8 | n/s | 95.9 | 98.5 | 45.4 | 80.0 | 60.81 / 75 | 515.0 | 675.7 | -29.9 | 196 |
| 2 | Ed | 15-11 | 0.764 (2) | 53.0 | n/s | 82.7 | 86.7 | 52.3 | 100.0 | 49.43 / 75 | 254.7 | 304.4 | 15.0 | 137 |
| 3 | MaKayla | 15-11 | 0.654 (3) | 55.6 | n/s | 42.1 | 87.4 | 42.4 | 50.0 | 44.58 / 75 | -51.9 | 315.8 | -49.9 | 84 |
| 4 | Joey | 15-11 | 0.630 (4) | 54.7 | n/s | 72.6 | 77.6 | 49.2 | 50.0 | 43.44 / 75 | 158.2 | 202.1 | -5.0 | 81 |
| 5 | Ty | 15-11 | 0.507 (6) | 47.9 | n/s | 34.5 | 72.5 | 53.0 | 20.0 | 37.32 / 75 | -104.4 | 157.8 | 19.2 | 40 |
| 6 | Collin | 13-13 | 0.513 (5) | 41.0 | n/s | 17.8 | 92.4 | 47.4 | 0.0 | 35.00 / 75 | -249.0 | 405.5 | -17.0 | 68 |
| 7 | Roy | 10-16 | 0.295 (9) | 43.6 | n/s | 29.7 | 85.9 | 45.9 | 0.0 | 34.91 / 75 | -140.0 | 294.2 | -26.7 | 35 |
| 8 | Kich | 11-15 | 0.420 (7) | 47.9 | n/s | 79.9 | 81.3 | 30.8 | 0.0 | 34.42 / 75 | 224.7 | 239.1 | -131.7 | 83 |
| 9 | Eric | 8-18 | 0.341 (8) | 41.0 | n/s | 79.7 | 91.5 | 40.5 | 0.0 | 34.19 / 75 | 222.5 | 386.8 | -62.6 | 130 |
| 10 | Jason | 7-19 | 0.144 (10) | 31.6 | n/s | 1.6 | 84.3 | 35.0 | 0.0 | 28.80 / 75 | -675.1 | 273.9 | -100.5 | 140 |

Validation leader: **Brent** (existing method: Brent). Top-two margin 11.39 measured pts < T's 25 unscored pts → **leader not determined by the evidence**; could lead under some T: Brent, Ed, MaKayla, Joey, Ty.

#### 2024 — final (as of week 13), basis incomplete, not_promoted

| # | manager | rec | legacy (rank) | A | T | T production (context, not scored) | W | D | P | measured / measurable | T net | W net | D net | unobs |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Ty | 21-5 | 0.841 (1) | 81.2 | n/s | 66.1 | 93.9 | 98.3 | 50.0 | 61.39 / 75 | 95.0 | 389.3 | 572.9 | 68 |
| 2 | Roy | 17-9 | 0.785 (2) | 66.7 | n/s | 49.1 | 94.4 | 63.6 | 80.0 | 55.19 / 75 | -4.9 | 401.5 | 79.5 | 144 |
| 3 | Joey | 14-12 | 0.654 (3) | 53.0 | n/s | 50.0 | 85.2 | 79.1 | 100.0 | 51.88 / 75 | 0.0 | 248.3 | 189.0 | 104 |
| 4 | MaKayla | 15-11 | 0.626 (4) | 55.6 | n/s | 57.3 | 87.0 | 62.5 | 50.0 | 46.51 / 75 | 41.7 | 270.1 | 72.4 | 86 |
| 5 | Collin | 10-16 | 0.325 (8) | 52.1 | n/s | 47.6 | 78.7 | 59.5 | 0.0 | 38.61 / 75 | -13.9 | 185.9 | 54.9 | 40 |
| 6 | Jason | 11-15 | 0.364 (7) | 41.0 | n/s | 51.1 | 88.9 | 46.5 | 0.0 | 34.40 / 75 | 6.1 | 296.1 | -19.7 | 138 |
| 7 | Ed | 12-14 | 0.455 (5) | 42.7 | n/s | 70.1 | 85.6 | 12.0 | 20.0 | 33.13 / 75 | 121.4 | 253.4 | -283.7 | 44 |
| 8 | Eric | 9-17 | 0.258 (9) | 38.5 | n/s | 43.4 | 88.9 | 14.2 | 0.0 | 30.14 / 75 | -37.8 | 295.5 | -255.6 | 81 |
| 9 | SheriffB | 10-16 | 0.156 (10) | 31.6 | n/s | 27.7 | 50.0 | 91.0 | 0.0 | 29.25 / 75 | -136.5 | 0.0 | 329.1 | 4 |
| 10 | Bwalk903 | 11-15 | 0.374 (6) | 37.6 | n/s | 50.9 | 70.4 | 7.9 | 0.0 | 26.39 / 75 | 4.9 | 123.1 | -349.2 | 28 |

Validation leader: **Ty** (existing method: Ty). Top-two margin 6.20 measured pts < T's 25 unscored pts → **leader not determined by the evidence**; could lead under some T: Ty, Roy, Joey, MaKayla, Collin.

**Who leads, honestly.** 2024 Ty, 2025 Brent, 2026-to-date Brent — the same managers the existing method names —
but in **no** season does the evidence decide it: the top-two margin (6.2 / 11.4 / 11.7 measured points) is smaller
than T's 25 unscored points, and 5 / 5 / 7 managers could lead for some value of T. The validation rank is a
statement about A, W, D and P only.

**v1 → v1.1.** Removing the one-sided T changes no leader (the v1 counterfactual keeps Ty / Brent / Brent) but
reorders the field (Kendall τ vs v1: 0.87 / 0.64 / 0.82). The OD-MOTY-7 counterexamples no longer carry a trade
penalty: Roy 2026 (T-production 1.5 — context only) is last on A (0-4, all-play 13.6), not on trades; Jason 2025
(T-production 1.6) is last on A (7-19, all-play 31.6); Brent 2025's T-production 95.9 no longer adds ~24 points.

### 11.3 Sensitivity (counterfactual re-scorings of the same frozen raw measurements, v1.1)

| perturbation | 2024 | 2025 | 2026 (wk 2) |
|---|---|---|---|
| each measured weight ±0.05 (others rescaled; T skipped — unscored) | 0/8 leader changes, min τ 0.91 | 0/8, min τ 0.91 | 0/6 (P pending), min τ 0.97 |
| KAPPA 0.25 / 1.0 | no change, τ 1.00 / 0.96 | no change, τ 0.91 / 0.91 | no change, τ 0.97 / 0.97 |
| draft table leave-one-season-out | no change, τ 1.00 | no change, τ 0.96 | no change, τ 1.00 |
| W unobservable weeks imputed at the mean observed charge (2.24 / 2.38 / 1.99 pts/wk) | no change, τ 0.91 | no change, τ 0.96 | no change, τ 0.91 |
| v1 counterfactual (production-only T scored — retired) | same leader, τ 0.87 | same leader, τ 0.64 | same leader, τ 0.82 |
| **any value of the unscored T** (top-two margin vs 25) | **not robust** (6.2) | **not robust** (11.4) | **not robust** (11.7) |
| share of T/W credit earned in counted-lineup weeks (OD-MOTY-3) | 58.6% (manager-set lineups) | 94.8% | 89.0% |

The measured part is stable to every weight, scale, calibration and imputation perturbation tested. The leader is
**not** stable to the unmeasured part, which is exactly why no score is published.

### 11.4 Anti-gaming results and the pathology found in v1

Real data (Spearman ρ, 2024 / 2025 / 2026, v1.1):

* **Trade volume does not buy T-production:** ρ(trade count, T-production) = 0.40 / −0.14 / −0.31 (T itself is
  unscored).
* **Waiver volume correlates with W:** ρ(waiver/FA moves, W) = 0.67 / 0.70 / 0.70. A move earns only what its
  player produces above replacement (a no-value move earns exactly 0 — tested), so this is active managers
  finding production, not a per-move bonus. W carries 15%, and the imputation stress does not move a leader.
  Reported, not hidden.
* **Draft position does not buy D:** ρ(mean draft band, D) = 0.25 / −0.01 / −0.01.
* **A vs management (W + D):** ρ = 0.82 / 0.23 / 0.30. 2024 is structural: the inaugural roster is built entirely
  by the startup draft, so construction and competition coincide.
* **Unified (measured points) vs legacy:** ρ = 0.81 / 0.95 / 0.84.

**Pathology (OD-MOTY-7) — found in the v1 replay.** With the trade future-value channel unavailable, v1 scored T
production-only, i.e. a rebuilding trade on the only side that could be measured:

* **2026, Roy** (0-4 at week 2): 10 window trades, 19 players out / 8 in, **11 future firsts received, 0 sent** →
  v1 T 1.5 (−125.7 net surplus in two weeks); summary "trades that cost value".
* **2025, Jason** (7-19): 99 trades, future picks 76 received / 32 sent (firsts 15 / 7) → v1 T 1.6 (−675 net).
* Mirror image: **2025, Brent** sent 14 future picks (3 firsts), received 3 → v1 T 95.9.

Directive §5 forbids exactly this ("a rebuilding trade is not penalized because a received pick scored 0 points;
a win-now trade is not given full production credit while surrendered future assets vanish"). Repairs weighed:

1. *Exclude future-pick trades from T* — **rejected.** It leaves the same asymmetry in player-for-player trades
   (a young player's future value is unmeasured too: Roy stayed at T 10.8 under it), and it changed the 2026 leader
   by deleting evidence rather than by measuring anything.
2. *Do not score T for a season whose FV-channel is incomplete* — **applied (v1.1, §11.5)**, with the owner rule
   for the missing 25% it needed made explicit and conservative: no score, measured points out of the measurable
   points, nothing redistributed (OD-MOTY-8).
3. *Accept v1* — rejected: it presents a one-sided T as the trade score.

### 11.5 The exact rule (v1.1)

1. **T is scored iff** its production half is measurable **and** the season's T FV-channel is `complete` (every
   window trade valued at its own instant by the canonical as-of resolver; a trade moving FAAB is unvalued) — then
   `T = 0.5·P + 0.5·FV`. A season with zero window trades is complete by construction.
2. **Otherwise T is unavailable**: `score = null`, `coverage = "unavailable"`, `unscoredReason =
   "trade_future_value_<status>"` (or `production_unmeasurable`); `productionScore` and every raw T field stay
   published as context and are excluded from every total. `coverage.reasons` gains `trade_component_unscored`.
3. **Row result.** A, W or D unmeasurable → unscored (unchanged). Else if T is unavailable → `score = null`,
   `earnedOf90 = null`, `contributions.T = null`, `incomplete = {measuredPoints = Σ WEIGHTS[k]·k over the measured
   components (A, W, D, and P once final), measurablePoints = 100·Σ WEIGHTS[k] over the same (65 / 75),
   measuredComponents, unscoredComponents}`. Else the §2 formula.
4. **Ranking.** `scoreBasis = full` ranks on the score; `incomplete` ranks on `measuredPoints` (ties: W+D
   contribution, then A, then a shared rank). The basis is season-wide; the two are never mixed.
5. **Uncertainty.** On an incomplete basis `unscoredTradeRange.couldLeadUnderSomeT` lists every manager within
   (≤) `100·WEIGHTS["T"]` measured points of the leader; `leaderDetermined` is true only when that list has one entry.
6. **Presentation.** `promotion = "not_promoted"`; the unified result never decides the card or race (§9); the UI
   labels it "Validation track — PARTIAL / NOT PROMOTED", shows "X / 65 measured pts" (never "/ 100"), shows T as
   "not scored" with its production half labelled context, and states the undecided range.

## 12. Tests and verification

* `tests/public_league/test_manager_of_the_year.py` — 50 tests. The §14 regressions (v1): normalization (zero →
  50, bounded, monotonic, symmetric, unscalable → None); non-playoff manager can win; exceptional champion can win;
  championship worth at most 10; no "outside the race" field; all-play independent of the schedule; tie / zero /
  negative / missing-week semantics; no-trade exactly neutral; bad trades negative and mirrored; star for excessive
  capital negative; round trips and re-acquisition cannot manufacture value; trade count earns nothing; drop/re-add
  cycling neutral with unknown weeks counted; no-value pickups earn nothing; expensive vs cheap equivalent pickups;
  dropping a productive player is charged; 1.01 not automatically best; no picks neutral; traded pick not credited
  twice; drafted-then-traded player keeps D; auction price-rank bands; the channel sum telescopes to
  `u(R) − u(B0) − E`; best-ball start/sit earns nothing; no postseason management weeks; missing history ≠ no
  trades; inaugural baseline; a stat correction changes exactly the affected result; actual-bracket P; unresolved
  bracket pending + provisional; final formula; exact ties; trade future value (future picks are not zero benefit;
  both sides valued at the trade's instant; no source → unavailable); every other award byte-identical (League MVP
  asserted by name); completed seasons keep their legacy official winner. The trade regressions now pin T's
  **production half** (`productionScore`) — the ledger they always tested — and, where a neutral complete valuation
  source is supplied, the scored T.
  **v1.1 additions:** a missing valuation makes T unavailable (never the production half); T unavailable → no
  score, measured points = 0.40A + 0.15W + 0.10D (+ 0.10P) out of 75 (65 provisional), nothing redistributed,
  validation rank, `unscoredTradeRange` names who could lead, the tie-break carries no T; a rebuilding trade's
  unmeasurable side moves nothing; a FAAB trade is unvalued;
  a no-trade season needs no valuation source; incomplete-basis ties; a **below-.500** manager (0-4 head-to-head,
  verified from the host matchups) is not excluded by record and can win; the unpromoted method never decides the
  card or race in any season, including a fully scored live provisional season; promotion is the one switch.
* **Sabotage (v1.1): 13/13 mutations turned the named tests red** — production-only T scored as T; T production
  counted in measured points; T production in the incomplete tie-break; a FAAB trade valued without its FAAB half; T's weight redistributed (renormalized to /100); no-trade season treated as
  unavailable; promotion reported; unpromoted provisional result decides the live card; a record gate (below .500
  excluded); a playoff gate (non-playoff unscored); UI badges an unpromoted result Final/Provisional; UI shows the
  production half as T; UI shows measured points as a /100 score. (v1's 16 engine/award and 3 frontend mutations
  are recorded in this file's history.)
* `frontend/__tests__/components/manager-of-the-year-card.test.jsx` — 8 tests (validation label and never
  official; measured points / 65 with T not scored and its production half as labelled context; undecided range;
  unpromoted final season beside the official winner; the promoted shape's 40/25/15/10/10 contributions and
  provisional label; coverage and unobservable weeks; tied ranks; the existing method's card with the validation
  breakdown beside — not inside — the history button, no GM card).
* Real snapshot: every award other than Manager of the Year is byte-identical with and without the unified engine,
  and the Manager of the Year card and race are byte-identical to the legacy card in all three seasons (the
  unified result is only the added `unifiedCandidate`).
* Performance: awards section build (3 seasons, real snapshot) 0.19 s (single run; v1 measured median 0.306 s), once per snapshot generation (heavy-section
  and contract-bytes caches), never per request.

## 13. Known canonical-owner finding (not changed here)

`metrics.final_regular_season_weeks` admitted the in-progress 2026 week 3 on the evening of 2026-09-28 through
its data-completeness proof (all 12 rosters had non-zero Sunday scores while Monday night was unplayed; host
`last_scored_leg` = 2). Every awards, Luck and Power consumer inherits it; this unit uses the canonical rule
unchanged and replays 2026 from the week-2 snapshot. Owner: `src/public_league/metrics.py` (separate claim).
PR #1517 ("a week is final only when its NFL games are") repairs it; it was **open, not merged** when v1.1 was
replayed (2026-09-29), so the replay uses the week-2 snapshot and must be re-run once #1517 lands on `main`.
