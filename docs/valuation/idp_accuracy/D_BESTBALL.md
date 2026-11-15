# IDP accuracy — Deliverable D: best-ball volatility by archetype

**Lane:** D. **Authority:** `docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md` §8 (best-ball
value) and §13 (production safety), nothing wider. **Status:** `RESEARCH_EVIDENCE_NOT_FOR_PROMOTION`.
No served value, rank, flag, weight, source, threshold or verdict is read or written by this lane.
Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

Every results table below is generated from `evidence/bestball_archetypes.json` by
`scripts/idp_accuracy/d_tables.py`; a test re-renders them and fails if this page drifts from the
evidence. Prose numbers are copied from those tables.

## Answer in brief

**Does best ball raise the value of volatile big-play defenders relative to stable ones?** Yes in
the sense the lineup makes precise, and the effect is real but modest, model-dependent in size, and
**not** a property of a "big-play defender" label.

The league starts the best 3 of each team's ~10 DL, LB and DB every week, so a defender's weekly
spread is worth expected lineup points whenever his mean sits near the cut line. That value (the
*volatility premium* `J`, defined in Method) is a Jensen gap: never negative, zero for a sure
starter. Measured on the 12 real rosters, 2026 weeks 1-6, scored with the verified league card:

<!-- table:headline -->
| population | n | volatility premium J, lineup ppg [95% CI] | J / ppg [95% CI] | J / ppg, plug-in | J per 1 ppg of weekly SD [95% CI] |
|---|---|---|---|---|---|
| IDP (six archetypes) | 264 | 1.23 [1.11, 1.34] | 11.9% [10.7%, 13.0%] | 9.8% | 0.153 [0.141, 0.167] |
| Offense (QB/RB/WR/TE) | 244 | 0.75 [0.66, 0.82] | 7.0% [6.2%, 7.9%] | 6.0% | 0.095 [0.085, 0.105] |
<!-- /table:headline -->

* **IDP players earn about 4.8 percentage points more premium than offensive players**, as a share
  of their own ppg (difference [3.4, 6.4]; Bonferroni interval [2.9, 6.8] excludes zero). The sign
  holds under all six weekly-distribution models, but independent-Poisson events shrink it to
  +0.4 pp; the data reject that model for IDP (observed weekly score variance is ~1.9x the
  independent Poisson variance).
* **It follows the slot economy, not the label.** DL (13.9%) and DB (12.8%) carry more than LB
  (7.9%): DL minus LB +6.1 pp [3.1, 8.9] and CB minus ILB +7.0 pp [3.1, 10.3] both survive the
  Bonferroni correction on J / ppg. CB minus ILB is positive under all six models; DL minus LB under
  five (it turns slightly negative only under the unfiltered 2025 shape). **EDGE versus DT is not
  distinguishable** (+1.5 pp [-2.8, 5.6]; the sign flips across models), and CB versus S (+3.4 pp
  [-0.7, 7.0]) is positive in all six models but not clear under the player-level data.
* **The "explosive half" of an archetype does not reliably earn more.** Splitting each archetype at
  its median big-play share of points, CB (+5.5 pp [0.1, 11.2]) and S, ILB lean positive, EDGE and
  DT lean negative, RB is negative; no split survives the Bonferroni correction for nine
  comparisons.
* **Size of the dose.** Holding a player's mean fixed, each extra 1 ppg of weekly SD is worth
  about 0.28 lineup ppg locally for IDP (0.22 offense) and 0.153 [0.141, 0.167] on average from
  zero spread (offense 0.095 [0.085, 0.105]).

**Does the best-ball marginal rank players differently from mean ppg?** Barely for most slots,
materially for DBs and kickers. Rank correlation inside a slot class between ppg and the best-ball
marginal over a free-agent replacement: RB 0.991, QB 0.986, WR 0.985, TE 0.983, DL 0.976, LB 0.972,
DL/LB hybrids 0.963, **DB 0.927**, K 0.913. Compared with the same marginal in a deterministic-ppg
lineup, best ball adds reordering of +0.041 [0.006, 0.123] for DB and +0.036 [0.008, 0.109] for
DL/LB hybrids; 34% of DBs [16%, 47%] move by at least 10% of the class, against 2-12% for offense.
In dense ppg bands one lineup point moves a player 10-20 places, so read the table in ppg, not rank.

**How sure?** Existence and sign: high (mathematical, replicated). The IDP-over-offense gap of ~4-5
pp: medium (positive under all six distribution models, 0.4 to 7.1 pp, and under the availability,
bye and injured-player variants; all in-sample on six weeks). Within-IDP orderings (EDGE vs DT, CB vs S) and any
player-level premium: low (player-level volatility is partly noise: half-season CV reliability
0.37 for EDGE and 0.39 for DT, 0.63-0.73 for ILB/CB/S; year over year 0.28-0.53). **Absolute
"value over replacement" is fragile**: the best-ball marginal moves by up to ~2 lineup ppg with the
identity of the replacement free agent (see "The marginal level"), so this lane publishes ranks and the
premium, not a dynasty value. No horizon, aging, market or 1-9999 conversion is attempted here.

## Method

**One simulated week.** A week is drawn uniformly from the league's remaining fantasy weeks (7-17).
The nflverse schedule says which NFL teams are on a bye that week, and the whole team sits out
together. Each remaining player is active with the share of his non-bye weeks he actually appeared
in (the host's `gp`/snap fields; a team that played while he did not is a real DNP and best ball
pays it 0.0). If active, his score comes from the distribution model. Players are independent
within the week.

**One lineup.** The league's 21 starting slots, solved exactly (a transversal-matroid greedy with
Hall's condition, vectorized over weeks). The solver is pinned to `src.ros.lineup`
(`solve_optimal_assignment`, best-ball basis) on random weeks that include DL/LB and DB/LB hybrids
and negative scores, and the whole marginal is pinned to `src.bestball.marginal` under the
library's own Gaussian week model: all differences sit inside the library's Monte-Carlo error
(`tests/idp_accuracy/test_bestball_archetypes.py`). Eligibility is read from the owner
(`precompute_slot_eligibility`), never tabulated here.

**Contexts.** The 12 live rosters of `dynasty_main`, exactly as Sleeper listed them. A player's
marginal is averaged over all 12 contexts (his own team with him removed, the other eleven with him
added), so rank comparisons are not distorted by who happens to own him. The published artifact
contains only these 12-context averages, never a team, a manager or a per-roster number.

**Marginal.** `M(p) = E[F(R + p) - F(R + c)]`, `F` the optimal weekly lineup total, `R` a roster
without `p`, `c` the replacement. The replacement is a free agent from the production-qualified
pool (unrostered, healthy by the host's status, at least two appearances and one in weeks 4-6): the
median-scoring roster among the rank-1..5 free agents for each slot family `p` can fill. Free
agents are claimed at no cost and uncontested; each context is evaluated alone.

**Volatility premium.** `J(p) = E[F(R + p)] - E[F(R + p*)]`, where `p*` has the same mean in every
week he is active and no spread. Everything else (his availability, byes, every other player's
spread) is untouched. Lineup value is convex in each player's score, so `J >= 0` by Jensen's
inequality (pinned by a test), and it is zero for a sure starter. It is measured in lineup points
per week and does not depend on the replacement at all. The dose-response uses the same device at
+50% spread. `J / ppg` is the ratio of group sums.

**Distribution models.** `E` the player's own appearances (the pre-specified primary); `Ec` the same
with the `n/(n-1)` variance correction; `S` the player's own level with the 2025 archetype shape
(rescored under the 2026 card, shape only; matched to roster-relevant players: >= 10 appearances,
> 5 ppg); `Su` the same shape unfiltered; `P` a gamma with the archetype CV; `Q` independent
Poisson event counts at the player's own observed rates, multiplied by the league card.

**Uncertainty.** A nested bootstrap: each outer replicate (40) resamples every player's own non-bye
weeks and re-runs the whole pipeline (new distributions, new free-agent ranking, new marginals); an
inner step resamples players within the group, 20 times. Resampling the weeks of an n = 6 sample
shrinks every spread by about (n-1)/n, so the replicates sit below the plug-in. For levels, ratios
and spreads the headline is therefore the **bias-corrected** estimate (`plug-in - bootstrap bias`)
with the matching basic (reverse-percentile) 95% interval, and the plug-in is published beside it;
the independent `Ec` run corrects the same bias a different way and lands in the same place
(IDP 11.3% against 11.9%). Rank agreements and shares are reported as the plug-in with the
percentile interval of the replicates. Contrasts also carry a Bonferroni interval over their family.

## Deviations from the pre-specification

The definitions that were fixed before any result was computed are pinned in
`tests/idp_accuracy/test_bestball_archetypes.py` (archetype rules, evaluated universe, free-agent
qualification, remaining weeks, bootstrap size, group membership). Four things changed after seeing
results, each disclosed here and each leaving the headline `J` unchanged or bracketed:

1. **Replacement rule.** Specified as the library's rule (best re-solve among the top-ranked free
   agents). A smoke run showed the marginal moving 2-3 ppg with *which* free agent was best (ILB:
   -2.75 for the first free agent, +0.40 for the third), because a free agent's own small-sample
   volatility is worth as much as the premium. The primary became the median-scoring of five; the
   best-of and rank-1/3/5 variants are published. `J` does not depend on the replacement.
2. **Shape reference.** The first 2025 pool included fringe players with far larger spread than the
   rostered population. A matched pool (>= 10 appearances, > 5 ppg) is `S`; the first one is kept
   as `Su`.
3. **Interval method.** Percentile intervals sat below the estimate (the (n-1)/n effect above), so
   levels use bias-corrected basic intervals; the earlier version is not published.
4. **Additions after seeing the first run:** the `Ec` and `Q` models, the slot-class grouping of
   rank comparisons (hybrids were distorting the "LB" family), and the corrected scorer component
   keys of the profile table (`idp_pd`, `idp_hit`; the first draft silently dropped pass defenses and
   QB hits from every event-mix share, now pinned by a test).

## Inputs and provenance

| input | value |
|---|---|
| league | `dynasty_main`, Sleeper `1312006700437352448`, season 2026, `in_season`, best ball |
| scoring fingerprint | `sf1:9e51824690d091f9` (identical to Lane A's pinned card) |
| scorer | host-native `compute_weekly_points(source="sleeper")`; Lane A reconciled it 3,710 / 3,710 within 0.01 of Sleeper's awarded points (2026 wk 1-6) |
| statistics | 2026 REG weeks 1-6 (week 7 in progress, excluded); 2025 weeks 1-18 rescored under the 2026 card, used for SHAPE only |
| slots | QB, RB x2, WR x3, TE x2, FLEX x2, SUPER_FLEX, K, DL x3, LB x3, DB x3 (21); 12 teams, 58 roster spots |
| fine positions | nflverse `rosters/roster_{2026,2025}.csv` `depth_chart_position`; byes from nflverse `schedules/games.csv` |
| datasets | Sleeper and nflverse bodies hashed in the evidence file (`provenance.datasets`) |
| simulation | 1,200 weeks per scenario, seed 20261026, 40 bootstrap replicates x 20 player resamples |

Population: 696 roster entries; 92 excluded as unavailable for the foreseeable future (Out, IR, PUP,
Sus, Inactive), 31 with no appearance in weeks 1-6, 7 with no stat line, 1 two-way DB/WR player
(his eligibility spans the offense and IDP lineups, out of scope). 565 enter the pools; **529 with
at least 3 appearances are evaluated**; 593 qualified free agents supply the replacement.

## Archetypes and fine positions

Fine positions are derived, not assumed. Join order: Sleeper id, GSIS id, unique name + team (2026
rookies are in the nflverse roster without a Sleeper id), then Sleeper's own depth chart only where
nflverse is silent. A generic nflverse `LB`/`DB`/`DL` or an ambiguous name is UNKNOWN. Archetype
rules use provenance fields only (an archetype function has no stat argument; a test pins that):
`EDGE` = nflverse DE, or an OLB the host also lists at DL; `DT` = DT/NT; `OLB` = the remaining
outside backers; `ILB` = ILB/MLB; `CB`; `S` = FS/SS. Offense is labelled by position.

<!-- table:fine -->
| join (players with a 2026 appearance) | count |
|---|---|
| UNKNOWN:nflverse_generic_position:FB | 1 |
| UNKNOWN:no_nflverse_roster_match | 1 |
| name_team | 85 |
| sleeper_depth_chart | 4 |
| sleeper_id | 830 |
| cross-check: nflverse vs Sleeper depth chart agree / disagree | 751 / 132 (85.1%) |
<!-- /table:fine -->

No evaluated player is UNKNOWN. The two sources disagree on 15% of the players both name (132 of
883); about half of that is the DE/DT line (68: 61 players nflverse calls DT whom Sleeper's depth
chart calls DE, interior linemen in a base-end slot), a quarter is ILB versus OLB (34), and the rest
nickel S versus CB (15) and OLB versus DE (14). **The EDGE-versus-DT
contrast is therefore the one most exposed to label provenance.**

<!-- table:population -->
| group | n | appearances (of 6) | ppg | ppg when active | weekly SD | SD / ppg | active share |
|---|---|---|---|---|---|---|---|
| EDGE | 72 | 5.6 | 9.69 | 9.95 | 7.91 | 0.80 | 96.30% |
| DT | 29 | 5.5 | 9.77 | 10.12 | 7.13 | 0.70 | 96.60% |
| DL (EDGE+DT) | 101 | 5.6 | 9.71 | 10.00 | 7.69 | 0.77 | 96.30% |
| ILB | 59 | 5.5 | 11.45 | 11.93 | 6.21 | 0.52 | 95.00% |
| OLB | 8 | 5.5 | 8.05 | 8.41 | 5.08 | 0.60 | 95.80% |
| LB (ILB+OLB) | 67 | 5.5 | 11.04 | 11.51 | 6.07 | 0.53 | 95.10% |
| CB | 50 | 5.4 | 10.46 | 11.09 | 7.68 | 0.69 | 94.50% |
| S | 46 | 5.5 | 10.37 | 10.95 | 6.43 | 0.59 | 94.20% |
| DB (CB+S) | 96 | 5.5 | 10.42 | 11.02 | 7.09 | 0.64 | 94.40% |
| IDP (all six) | 264 | 5.5 | 10.31 | 10.75 | 7.06 | 0.66 | 95.30% |
| QB | 33 | 5.2 | 17.41 | 19.00 | 10.85 | 0.57 | 89.30% |
| RB | 63 | 5.4 | 10.70 | 11.12 | 5.99 | 0.54 | 92.50% |
| WR | 98 | 5.5 | 9.56 | 10.02 | 6.44 | 0.64 | 94.10% |
| TE | 50 | 5.5 | 7.72 | 8.11 | 6.25 | 0.77 | 94.70% |
| K | 21 | 5.8 | 9.95 | 9.95 | 4.54 | 0.46 | 100.00% |
| Offense (QB/RB/WR/TE) | 244 | 5.4 | 10.54 | 11.13 | 6.88 | 0.62 | 93.20% |
<!-- /table:population -->

The labels in the brief do and do not show up in the points. Verified event rates and their share of
each archetype's points (2026 weeks 1-6, evaluated players only):

<!-- table:profile -->
| group | n | tackles /g | TFL /g | sacks /g | QB hits /g | PD /g | tackle pts | TFL pts | pass-rush pts | coverage pts | other pts |
|---|---|---|---|---|---|---|---|---|---|---|---|
| EDGE | 72 | 2.52 | 0.50 | 0.39 | 1.02 | 0.15 | 31% | 20% | 35% | 8% | 7% |
| DT | 29 | 3.06 | 0.57 | 0.32 | 0.81 | 0.22 | 36% | 22% | 28% | 11% | 4% |
| DL (EDGE+DT) | 101 | 2.67 | 0.52 | 0.37 | 0.96 | 0.17 | 32% | 20% | 33% | 9% | 6% |
| ILB | 59 | 6.46 | 0.39 | 0.12 | 0.32 | 0.24 | 56% | 12% | 8% | 11% | 13% |
| OLB | 8 | 5.02 | 0.25 | 0.06 | 0.16 | 0.11 | 63% | 9% | 5% | 4% | 19% |
| LB (ILB+OLB) | 67 | 6.29 | 0.37 | 0.12 | 0.30 | 0.23 | 57% | 12% | 8% | 10% | 14% |
| CB | 50 | 4.21 | 0.23 | 0.05 | 0.09 | 0.72 | 47% | 8% | 3% | 38% | 4% |
| S | 46 | 5.30 | 0.18 | 0.06 | 0.17 | 0.45 | 55% | 6% | 4% | 27% | 7% |
| DB (CB+S) | 96 | 4.73 | 0.21 | 0.06 | 0.13 | 0.59 | 51% | 7% | 4% | 32% | 5% |
| IDP (all six) | 264 | 4.33 | 0.37 | 0.19 | 0.49 | 0.34 | 45% | 13% | 16% | 18% | 8% |
<!-- /table:profile -->

CB is the big-play archetype by the data (38% of points from pass defenses and interceptions); ILB/OLB
are tackle-volume (57%); S is mixed (55% tackles, 27% coverage). **EDGE and DT are not very different
in composition**: both are about half tackles and tackles-for-loss, with pass rush 35% and 28% of
points (the card's stacking of sack, TFL and QB hit on one play lifts DT too). OLB has 8 players and is
reported but not interpreted.

## Result 1 — the volatility premium

<!-- table:premium -->
| group | n | ppg | volatility premium J, lineup ppg [95% CI] | J / ppg [95% CI] | J / ppg, plug-in | J per 1 ppg of weekly SD [95% CI] | local slope at +50% spread |
|---|---|---|---|---|---|---|---|
| EDGE | 72 | 9.69 | 1.40 [1.14, 1.68] | 14.4% [11.4%, 17.0%] | 12.1% | 0.157 [0.134, 0.180] | 0.301 |
| DT | 29 | 9.77 | 1.26 [0.91, 1.58] | 12.9% [9.6%, 15.7%] | 10.5% | 0.158 [0.128, 0.187] | 0.276 |
| DL (EDGE+DT) | 101 | 9.71 | 1.36 [1.12, 1.57] | 13.9% [11.6%, 16.2%] | 11.6% | 0.157 [0.137, 0.177] | 0.294 |
| ILB | 59 | 11.45 | 0.85 [0.63, 1.04] | 7.4% [5.6%, 9.1%] | 6.2% | 0.120 [0.090, 0.151] | 0.233 |
| OLB | 8 | 8.05 | 0.96 [0.27, 1.41] | 11.9% [5.0%, 17.1%] | 9.3% | 0.173 [0.099, 0.243] | 0.304 |
| LB (ILB+OLB) | 67 | 11.04 | 0.87 [0.69, 1.05] | 7.9% [6.0%, 9.6%] | 6.5% | 0.126 [0.100, 0.157] | 0.239 |
| CB | 50 | 10.46 | 1.51 [1.14, 1.82] | 14.5% [11.2%, 17.3%] | 11.8% | 0.173 [0.140, 0.204] | 0.281 |
| S | 46 | 10.37 | 1.14 [0.91, 1.37] | 11.1% [9.1%, 13.0%] | 9.2% | 0.159 [0.135, 0.184] | 0.285 |
| DB (CB+S) | 96 | 10.42 | 1.33 [1.13, 1.51] | 12.8% [11.1%, 14.5%] | 10.5% | 0.166 [0.146, 0.186] | 0.282 |
| IDP (all six) | 264 | 10.31 | 1.23 [1.11, 1.34] | 11.9% [10.7%, 13.0%] | 9.8% | 0.153 [0.141, 0.167] | 0.277 |
| QB | 33 | 17.41 | 1.15 [0.81, 1.46] | 6.6% [4.2%, 8.5%] | 5.5% | 0.091 [0.068, 0.115] | 0.202 |
| RB | 63 | 10.70 | 0.49 [0.34, 0.62] | 4.5% [2.6%, 5.9%] | 4.0% | 0.070 [0.047, 0.093] | 0.185 |
| WR | 98 | 9.56 | 0.74 [0.61, 0.85] | 7.7% [6.1%, 9.1%] | 6.5% | 0.103 [0.082, 0.119] | 0.236 |
| TE | 50 | 7.72 | 0.84 [0.67, 1.00] | 10.8% [8.4%, 13.1%] | 9.2% | 0.119 [0.099, 0.142] | 0.246 |
| K | 21 | 9.95 | 0.54 [0.34, 0.69] | 5.4% [3.3%, 7.0%] | 4.7% | 0.106 [0.080, 0.130] | 0.227 |
| Offense (QB/RB/WR/TE) | 244 | 10.54 | 0.75 [0.66, 0.82] | 7.0% [6.2%, 7.9%] | 6.0% | 0.095 [0.085, 0.105] | 0.217 |
<!-- /table:premium -->

`J / ppg` is the premium as a share of the player's own ppg. The plug-in column is the number the
pre-specified `E` model gives on the observed weeks; the bias correction adds about 2 pp for IDP and
1 pp for offense.

### Contrasts (family of five, Bonferroni-adjusted)

<!-- table:contrasts -->
| contrast (A minus B) | n A / n B | J / ppg difference [95% CI] | Bonferroni (5) interval | excludes 0 | J per SD difference [95% CI] | excludes 0 (Bonf.) |
|---|---|---|---|---|---|---|
| EDGE minus DT | 72 / 29 | 1.5% [-2.8%, 5.6%] | [-4.1%, 6.7%] | no | -0.001 [-0.039, 0.037] | no |
| CB minus S | 50 / 46 | 3.4% [-0.7%, 7.0%] | [-1.8%, 8.1%] | no | 0.014 [-0.029, 0.055] | no |
| DL (EDGE+DT) minus LB (ILB+OLB) | 101 / 67 | 6.1% [3.1%, 8.9%] | [2.2%, 9.7%] | yes | 0.031 [-0.008, 0.064] | no |
| CB minus ILB | 50 / 59 | 7.0% [3.1%, 10.3%] | [1.9%, 11.8%] | yes | 0.052 [0.005, 0.101] | no |
| IDP (all six) minus offense (QB/RB/WR/TE) | 264 / 244 | 4.8% [3.4%, 6.4%] | [2.9%, 6.8%] | yes | 0.058 [0.042, 0.077] | yes |
<!-- /table:contrasts -->

The same contrasts under each distribution model (point estimates):

<!-- table:contrastModels -->
| contrast of J / ppg (A minus B), point estimate | E (own weeks) | Ec (own weeks, n/(n-1) variance correction) | S (2025 archetype shape, matched) | Su (2025 archetype shape, unfiltered) | P (gamma, archetype CV) | Q (Poisson events) |
|---|---|---|---|---|---|---|
| EDGE minus DT | 1.6% | 1.9% | -0.6% | -1.4% | -1.2% | -0.9% |
| CB minus S | 2.6% | 3.0% | 2.0% | 3.6% | 2.1% | 1.7% |
| DL (EDGE+DT) minus LB (ILB+OLB) | 5.1% | 5.9% | 4.0% | -0.5% | 2.8% | 1.2% |
| CB minus ILB | 5.6% | 6.3% | 5.1% | 5.2% | 4.5% | 3.5% |
| IDP (all six) minus offense (QB/RB/WR/TE) | 3.8% | 4.2% | 5.0% | 7.1% | 5.3% | 0.4% |
<!-- /table:contrastModels -->

### Is the explosive half worth more?

<!-- table:profileSplit -->
| archetype | n explosive / stable half | median big-play share | SD/ppg explosive / stable | J/ppg explosive / stable | difference [95% CI] | Bonferroni interval |
|---|---|---|---|---|---|---|
| EDGE | 36 / 36 | 49% | 0.75 / 0.86 | 11.2% / 13.3% | -2.4% [-7.7%, 3.1%] | [-9.8%, 5.0%] |
| DT | 14 / 15 | 42% | 0.62 / 0.82 | 9.6% / 11.7% | -1.8% [-7.1%, 4.1%] | [-9.7%, 6.3%] |
| ILB | 29 / 30 | 28% | 0.59 / 0.44 | 7.2% / 5.0% | 3.1% [-0.1%, 6.1%] | [-1.2%, 7.0%] |
| CB | 25 / 25 | 45% | 0.74 / 0.63 | 13.6% / 9.5% | 5.5% [0.1%, 11.2%] | [-2.6%, 13.2%] |
| S | 23 / 23 | 37% | 0.63 / 0.53 | 10.7% / 7.1% | 4.2% [-0.1%, 8.5%] | [-2.5%, 10.1%] |
| QB | 16 / 17 | 12% | 0.72 / 0.48 | 7.7% / 4.3% | 4.1% [-0.5%, 8.4%] | [-2.7%, 10.4%] |
| RB | 31 / 32 | 18% | 0.52 / 0.58 | 3.3% / 5.5% | -3.2% [-6.3%, -0.2%] | [-7.5%, 1.7%] |
| WR | 48 / 49 | 19% | 0.65 / 0.64 | 6.0% / 7.1% | -1.3% [-4.2%, 1.8%] | [-5.3%, 3.0%] |
| TE | 25 / 25 | 24% | 0.78 / 0.76 | 9.0% / 9.3% | -1.3% [-6.1%, 3.7%] | [-7.6%, 5.1%] |
<!-- /table:profileSplit -->

Split at the median big-play share of points (pass rush, coverage and turnover points; tackles and
TFL excluded). A high big-play share does not mean a high CV: the explosive EDGE half has the *lower*
SD / ppg because it contains the better, higher-volume rushers.

### Where the premium lives

In lineup points the premium rises with ppg inside an IDP class (top-third DL 1.85, DB 1.93) because
good IDP talent is spread thin across 12 teams and even a top-third defender competes for the third
slot. Offensive skill positions behave differently: the top third are sure starters and the premium
collapses (RB 1.7% of ppg, WR 3.9%, QB 3.8%) while the middle third carries 8-17%. Low-mean players
keep a large share of ppg (they are bench depth that occasionally starts) but little in points:

<!-- table:tiersPpg -->
| slot class | tier | n | ppg range | mean ppg | J [95% CI] | J / ppg [95% CI] | SD / ppg |
|---|---|---|---|---|---|---|---|
| DL | top third | 19 | 11.3 to 19.2 | 14.36 | 1.85 [1.37, 2.26] | 12.9% [9.5%, 15.9%] | 0.66 |
| DL | middle third | 20 | 6.6 to 11.3 | 8.84 | 1.22 [0.80, 1.55] | 13.7% [9.6%, 17.2%] | 0.73 |
| DL | bottom third | 19 | 1.4 to 6.0 | 3.99 | 0.47 [0.23, 0.68] | 12.0% [7.5%, 16.4%] | 1.00 |
| LB | top third | 21 | 14.4 to 22.7 | 16.73 | 1.09 [0.72, 1.39] | 6.5% [3.8%, 8.4%] | 0.52 |
| LB | middle third | 23 | 9.0 to 14.3 | 11.59 | 1.09 [0.69, 1.38] | 9.5% [6.1%, 11.9%] | 0.49 |
| LB | bottom third | 21 | 0.2 to 8.7 | 4.45 | 0.37 [0.07, 0.56] | 8.4% [3.1%, 12.1%] | 0.63 |
| DB | top third | 31 | 12.4 to 19.8 | 14.76 | 1.93 [1.49, 2.33] | 13.1% [9.8%, 15.9%] | 0.61 |
| DB | middle third | 31 | 8.6 to 12.0 | 10.48 | 1.49 [1.09, 1.81] | 14.2% [10.5%, 17.1%] | 0.65 |
| DB | bottom third | 31 | 0.8 to 8.2 | 6.06 | 0.64 [0.39, 0.84] | 10.5% [7.4%, 13.4%] | 0.71 |
| DL/LB | top third | 15 | 11.3 to 27.4 | 16.61 | 1.90 [1.26, 2.52] | 11.2% [5.6%, 15.7%] | 0.70 |
| DL/LB | middle third | 15 | 8.8 to 11.3 | 9.90 | 1.88 [1.23, 2.38] | 18.8% [13.2%, 23.9%] | 0.85 |
| DL/LB | bottom third | 15 | 1.3 to 8.3 | 5.77 | 0.95 [0.60, 1.25] | 16.2% [11.4%, 20.6%] | 0.97 |
| QB | top third | 11 | 23.1 to 31.7 | 26.91 | 1.03 [0.47, 1.41] | 3.8% [1.5%, 5.3%] | 0.40 |
| QB | middle third | 11 | 12.6 to 23.1 | 17.42 | 1.48 [0.76, 2.08] | 8.5% [3.9%, 12.0%] | 0.59 |
| QB | bottom third | 11 | 1.9 to 12.2 | 7.90 | 0.94 [0.31, 1.38] | 11.6% [3.5%, 17.4%] | 0.98 |
| RB | top third | 21 | 11.4 to 36.3 | 20.12 | 0.36 [0.03, 0.62] | 1.7% [-0.3%, 3.1%] | 0.44 |
| RB | middle third | 21 | 5.6 to 11.2 | 8.51 | 0.72 [0.49, 0.92] | 8.5% [5.8%, 10.7%] | 0.59 |
| RB | bottom third | 21 | 0.2 to 5.5 | 3.46 | 0.39 [0.17, 0.55] | 11.4% [6.9%, 15.3%] | 0.91 |
| WR | top third | 32 | 12.0 to 31.7 | 16.83 | 0.67 [0.37, 0.89] | 3.9% [1.9%, 5.3%] | 0.54 |
| WR | middle third | 34 | 5.7 to 11.0 | 8.52 | 1.06 [0.83, 1.25] | 12.5% [9.7%, 14.7%] | 0.70 |
| WR | bottom third | 32 | 0.0 to 5.6 | 3.40 | 0.46 [0.29, 0.60] | 13.5% [9.1%, 17.0%] | 1.00 |
| TE | top third | 16 | 9.5 to 19.4 | 12.85 | 0.90 [0.58, 1.19] | 6.9% [3.8%, 9.4%] | 0.63 |
| TE | middle third | 18 | 5.5 to 9.2 | 7.30 | 1.24 [0.87, 1.54] | 17.0% [12.1%, 21.6%] | 0.89 |
| TE | bottom third | 16 | 0.7 to 5.3 | 3.05 | 0.33 [0.17, 0.46] | 11.1% [7.2%, 14.2%] | 1.02 |
<!-- /table:tiersPpg -->

By volatility tier (SD / ppg), at constant position:

<!-- table:tiersCv -->
| slot class | tier | n | SD / ppg (active) range | mean ppg | J [95% CI] | J / ppg [95% CI] | SD / ppg |
|---|---|---|---|---|---|---|---|
| DL | top third | 19 | 0.9 to 1.9 | 5.85 | 1.14 [0.65, 1.54] | 19.3% [14.1%, 24.3%] | 1.12 |
| DL | middle third | 20 | 0.7 to 0.9 | 10.23 | 1.58 [1.15, 1.97] | 15.3% [11.0%, 19.0%] | 0.78 |
| DL | bottom third | 19 | 0.2 to 0.6 | 11.03 | 0.83 [0.53, 1.08] | 7.6% [5.2%, 9.6%] | 0.49 |
| LB | top third | 21 | 0.7 to 2.2 | 7.59 | 1.08 [0.63, 1.45] | 14.1% [8.4%, 19.0%] | 0.86 |
| LB | middle third | 23 | 0.4 to 0.7 | 12.37 | 1.04 [0.75, 1.30] | 8.3% [5.9%, 10.5%] | 0.54 |
| LB | bottom third | 21 | 0.1 to 0.4 | 12.75 | 0.46 [0.30, 0.58] | 3.5% [2.3%, 4.5%] | 0.31 |
| DB | top third | 31 | 0.7 to 1.6 | 9.09 | 2.01 [1.45, 2.46] | 22.1% [16.9%, 26.6%] | 0.93 |
| DB | middle third | 31 | 0.5 to 0.7 | 10.57 | 1.28 [0.95, 1.54] | 12.1% [9.3%, 14.6%] | 0.63 |
| DB | bottom third | 31 | 0.1 to 0.5 | 11.65 | 0.78 [0.56, 0.95] | 6.7% [5.0%, 8.3%] | 0.42 |
| DL/LB | top third | 15 | 0.9 to 1.7 | 7.52 | 1.93 [1.17, 2.57] | 25.0% [17.5%, 32.5%] | 1.14 |
| DL/LB | middle third | 15 | 0.7 to 0.9 | 10.07 | 1.77 [1.28, 2.21] | 17.3% [12.5%, 22.0%] | 0.81 |
| DL/LB | bottom third | 15 | 0.5 to 0.7 | 14.68 | 1.01 [0.53, 1.43] | 6.8% [3.1%, 9.9%] | 0.60 |
| QB | top third | 11 | 0.7 to 2.6 | 11.29 | 1.72 [0.82, 2.37] | 15.0% [7.2%, 20.4%] | 0.99 |
| QB | middle third | 11 | 0.5 to 0.7 | 16.01 | 1.06 [0.58, 1.45] | 6.6% [3.2%, 9.2%] | 0.60 |
| QB | bottom third | 11 | 0.1 to 0.5 | 24.93 | 0.64 [0.31, 0.89] | 2.5% [1.3%, 3.6%] | 0.32 |
| RB | top third | 21 | 0.8 to 1.9 | 4.73 | 0.78 [0.45, 1.05] | 16.4% [11.2%, 20.5%] | 1.01 |
| RB | middle third | 21 | 0.5 to 0.8 | 10.42 | 0.51 [0.34, 0.67] | 4.7% [2.6%, 6.6%] | 0.60 |
| RB | bottom third | 21 | 0.1 to 0.5 | 16.94 | 0.17 [-0.01, 0.33] | 1.0% [-0.2%, 1.9%] | 0.35 |
| WR | top third | 32 | 0.9 to 2.2 | 5.02 | 0.97 [0.67, 1.21] | 19.4% [15.1%, 23.3%] | 1.06 |
| WR | middle third | 33 | 0.6 to 0.8 | 10.44 | 0.83 [0.58, 1.04] | 7.8% [5.2%, 10.0%] | 0.69 |
| WR | bottom third | 32 | 0.2 to 0.6 | 13.49 | 0.43 [0.30, 0.55] | 3.2% [2.0%, 4.2%] | 0.45 |
| TE | top third | 16 | 1.0 to 2.0 | 5.03 | 1.01 [0.59, 1.39] | 19.9% [12.6%, 26.4%] | 1.18 |
| TE | middle third | 18 | 0.7 to 1.0 | 6.93 | 1.02 [0.71, 1.27] | 14.7% [10.2%, 18.4%] | 0.84 |
| TE | bottom third | 16 | 0.3 to 0.7 | 11.29 | 0.46 [0.23, 0.66] | 3.8% [1.5%, 5.8%] | 0.54 |
<!-- /table:tiersCv -->

The most volatile third of each IDP class earns 14-25% of ppg against 3.5-7.6% for the most stable
third. They are also much lower-mean players (DL: 5.9 ppg against 11.0), so in lineup points the
gap is smaller (DL 1.14 against 0.83) and the middle third, with both mean and spread, is highest
(1.58).

## Result 2 — mean-ppg rank versus best-ball rank

<!-- table:ranks -->
| slot class | n | rank corr: ppg vs best-ball marginal [95% CI] | ppg vs deterministic lineup | gap (extra reordering from best ball) | share ranked materially differently | top-third overlap |
|---|---|---|---|---|---|---|
| DL | 58 | 0.976 [0.927, 0.986] | 0.999 [0.968, 1.000] | 0.023 [-0.002, 0.070] | 16% [5%, 38%] | 85% [75%, 100%] |
| LB | 65 | 0.972 [0.931, 0.990] | 0.996 [0.979, 0.999] | 0.023 [-0.002, 0.065] | 11% [2%, 31%] | 96% [77%, 100%] |
| DB | 93 | 0.927 [0.863, 0.962] | 0.968 [0.938, 0.997] | 0.041 [0.006, 0.123] | 34% [16%, 47%] | 90% [71%, 97%] |
| DL/LB | 45 | 0.963 [0.890, 0.985] | 0.999 [0.981, 1.000] | 0.036 [0.008, 0.109] | 13% [4%, 44%] | 93% [73%, 100%] |
| QB | 33 | 0.986 [0.927, 0.995] | 0.998 [0.982, 1.000] | 0.012 [-0.001, 0.065] | 6% [0%, 33%] | 91% [73%, 100%] |
| RB | 63 | 0.991 [0.968, 0.996] | 1.000 [0.995, 1.000] | 0.009 [0.002, 0.031] | 2% [-0%, 18%] | 100% [86%, 100%] |
| WR | 98 | 0.985 [0.964, 0.992] | 0.999 [0.993, 0.999] | 0.015 [0.005, 0.034] | 7% [1%, 18%] | 97% [85%, 100%] |
| TE | 50 | 0.983 [0.948, 0.992] | 0.998 [0.992, 1.000] | 0.015 [0.005, 0.051] | 12% [2%, 30%] | 88% [76%, 100%] |
| K | 21 | 0.913 [0.731, 0.992] | 0.992 [0.958, 1.000] | 0.080 [-0.002, 0.266] | 29% [0%, 62%] | 86% [57%, 100%] |
<!-- /table:ranks -->

Rank agreement is computed inside slot classes (identical eligibility, so the players actually
compete for the same slots; a DL/LB hybrid is neither a lineman nor a linebacker). The percentile
interval sits below the estimate because resampling six weeks adds noise to both rankings.

Who moves most (best-ball rank against ppg rank, inside the class):

<!-- table:movers -->
| slot class | n | best-ball gains the most ranks | best-ball loses the most ranks |
|---|---|---|---|
| DL | 58 | Mason Graham (DT, 11.3 ppg, CV 0.79, +10); Levi Drake Rodriguez (DT, 5.5 ppg, CV 1.25, +8); Keldric Faulk (EDGE, 4.0 ppg, CV 1.80, +8); Josh Sweat (EDGE, 7.4 ppg, CV 1.01, +7) | Jared Verse (EDGE, 7.6 ppg, CV 0.21, -10); Tommy Togiai (DT, 6.6 ppg, CV 0.42, -8); Maxx Crosby (EDGE, 12.3 ppg, CV 0.54, -6); Cameron Heyward (DT, 11.3 ppg, CV 0.44, -6) |
| LB | 65 | Eric Wilson (ILB, 11.2 ppg, CV 1.16, +18); Kaden Elliss (ILB, 8.2 ppg, CV 0.22, +15); Christian Elliss (ILB, 10.9 ppg, CV 0.79, +7); Roquan Smith (ILB, 14.6 ppg, CV 0.67, +6) | Akeem Davis-Gaither (ILB, 11.8 ppg, CV 0.32, -11); Alex Singleton (ILB, 15.9 ppg, CV 0.23, -8); Quay Walker (ILB, 11.4 ppg, CV 0.43, -8); Robert Spillane (ILB, 9.0 ppg, CV 0.35, -7) |
| DB | 93 | Minkah Fitzpatrick (S, 8.7 ppg, CV 0.99, +22); Nick Emmanwori (S, 11.1 ppg, CV 1.01, +21); James Pierre (CB, 8.6 ppg, CV 1.01, +20); Keith Abney II (CB, 5.0 ppg, CV 1.37, +20) | Kam Curl (S, 8.8 ppg, CV 0.48, -20); Devon Witherspoon (CB, 12.0 ppg, CV 0.35, -19); Kamari Lassiter (CB, 13.8 ppg, CV 0.28, -18); L'Jarius Sneed (CB, 12.4 ppg, CV 0.18, -17) |
| DL/LB | 45 | Jermaine Johnson II (EDGE, 8.8 ppg, CV 1.18, +11); Alex Highsmith (EDGE, 10.0 ppg, CV 1.21, +7); Za'Darius Smith (EDGE, 9.3 ppg, CV 1.05, +6); Nick Herbig (EDGE, 10.8 ppg, CV 1.30, +5) | K'Lavon Chaisson (EDGE, 10.2 ppg, CV 0.47, -11); Jaishawn Barham (ILB, 9.7 ppg, CV 0.60, -6); Odafe Oweh (EDGE, 10.5 ppg, CV 0.71, -4); Khalil Mack (EDGE, 10.9 ppg, CV 0.69, -4) |
| QB | 33 | Drake Maye (QB, 21.9 ppg, CV 0.99, +4); Matthew Stafford (QB, 23.1 ppg, CV 0.71, +3); Jared Goff (QB, 31.6 ppg, CV 0.22, +2); Caleb Williams (QB, 12.9 ppg, CV 0.83, +2) | Kirk Cousins (QB, 24.4 ppg, CV 0.22, -5); Cam Ward (QB, 12.2 ppg, CV 0.61, -2); Brock Purdy (QB, 31.7 ppg, CV 0.32, -2); Geno Smith (QB, 16.7 ppg, CV 0.69, -1) |
| RB | 63 | Tyrone Tracy Jr. (RB, 5.3 ppg, CV 1.45, +9); Zonovan Knight (RB, 3.4 ppg, CV 1.89, +5); RJ Harvey (RB, 9.9 ppg, CV 0.61, +5); Saquon Barkley (RB, 4.6 ppg, CV 0.74, +4) | Woody Marks (RB, 11.2 ppg, CV 0.23, -6); Kenny Gainwell (RB, 7.2 ppg, CV 0.36, -5); Kendre Miller (RB, 5.8 ppg, CV 0.68, -4); Omarion Hampton (RB, 11.1 ppg, CV 0.53, -3) |
| WR | 98 | Jordan Addison (WR, 7.6 ppg, CV 1.03, +17); Kevin Coleman Jr. (WR, 3.7 ppg, CV 1.76, +15); Konata Mumpfield (WR, 5.0 ppg, CV 1.68, +14); Chris Bell (WR, 4.4 ppg, CV 1.28, +12) | Kayshon Boutte (WR, 5.7 ppg, CV 0.27, -14); Rome Odunze (WR, 10.1 ppg, CV 0.46, -10); Khalil Shakir (WR, 9.7 ppg, CV 0.43, -9); Makai Lemon (WR, 5.5 ppg, CV 0.61, -8) |
| TE | 50 | Tyler Higbee (TE, 8.8 ppg, CV 1.18, +8); Noah Fant (TE, 5.5 ppg, CV 1.30, +7); Kenyon Sadiq (TE, 6.5 ppg, CV 1.61, +6); Dallas Goedert (TE, 8.2 ppg, CV 0.82, +4) | Pat Freiermuth (TE, 10.8 ppg, CV 0.63, -6); Brenton Strange (TE, 10.8 ppg, CV 0.54, -5); Cade Otton (TE, 7.4 ppg, CV 0.41, -5); AJ Barner (TE, 6.1 ppg, CV 0.71, -4) |
<!-- /table:movers -->

Winners are volatile, mid-ppg players (Fitzpatrick S, Emmanwori S, Pierre CB, Higbee TE); losers are
stable players in the same band (Witherspoon CB 0.35 CV, Lassiter CB 0.28, Sneed CB 0.18). Treat the
size of a move with care: in the dense middle of a class a lineup point is 10-20 places.

### The marginal level, and why it is not published as a value

<!-- table:levels -->
| group | n | best-ball marginal vs replacement (lineup ppg) | same marginal, deterministic ppg lineup | difference |
|---|---|---|---|---|
| EDGE | 72 | 0.70 | 1.11 | -0.41 |
| DT | 29 | 0.15 | 0.62 | -0.47 |
| DL (EDGE+DT) | 101 | 0.55 | 0.97 | -0.42 |
| ILB | 59 | -0.53 | 1.22 | -1.75 |
| OLB | 8 | -2.04 | -0.08 | -1.96 |
| LB (ILB+OLB) | 67 | -0.71 | 1.07 | -1.77 |
| CB | 50 | -0.37 | 0.21 | -0.58 |
| S | 46 | -0.60 | 0.43 | -1.03 |
| DB (CB+S) | 96 | -0.48 | 0.32 | -0.79 |
| IDP (all six) | 264 | -0.14 | 0.76 | -0.90 |
| QB | 33 | 7.11 | 6.19 | 0.92 |
| RB | 63 | 4.47 | 4.16 | 0.31 |
| WR | 98 | 3.22 | 2.87 | 0.34 |
| TE | 50 | 2.68 | 1.99 | 0.69 |
| K | 21 | 0.66 | 0.67 | -0.01 |
| Offense (QB/RB/WR/TE) | 244 | 3.96 | 3.47 | 0.48 |
<!-- /table:levels -->

Best ball lowers the IDP marginal against replacement relative to a deterministic-ppg lineup (-0.90
lineup ppg) and raises the offense one (+0.48). The reason is the replacement: the wire is full of
volatile players near the cut line whose own premium is large, so the stable starter's edge over
them shrinks. The level depends on which free agent is the replacement:

<!-- table:sensitivityM -->
| archetype (mean marginal vs replacement, lineup ppg) | base | replacement = best of FA ranks 1-2 | replacement = FA rank 1 only | replacement = third-best FA | replacement = fifth-best FA |
|---|---|---|---|---|---|
| EDGE | 0.70 | -1.04 | -1.04 | 0.71 | -0.37 |
| DT | 0.15 | -1.29 | -1.29 | 0.16 | -0.92 |
| ILB | -0.53 | -1.51 | -1.25 | 1.74 | -0.63 |
| CB | -0.37 | -0.84 | -0.37 | 0.32 | 0.89 |
| S | -0.60 | -1.18 | -0.71 | 0.07 | 0.51 |
| QB | 7.11 | 5.91 | 6.40 | 6.97 | 7.48 |
| RB | 4.47 | 3.02 | 3.51 | 4.03 | 4.58 |
| WR | 3.22 | 2.01 | 2.50 | 3.08 | 3.53 |
| TE | 2.68 | 1.36 | 1.65 | 2.41 | 2.30 |
<!-- /table:sensitivityM -->

ILB moves from -1.51 to +1.74 lineup ppg across defensible choices. The rank order barely moves:

<!-- table:sensitivityRho -->
| archetype (rank corr: ppg vs best-ball marginal) | base | replacement = best of FA ranks 1-2 | replacement = FA rank 1 only | replacement = third-best FA | replacement = fifth-best FA | availability forced to 100% | no bye weeks | injured / out players kept at historical availability |
|---|---|---|---|---|---|---|---|---|
| EDGE | 0.970 | 0.973 | 0.973 | 0.970 | 0.970 | 0.963 | 0.969 | 0.967 |
| DT | 0.956 | 0.956 | 0.956 | 0.956 | 0.956 | 0.961 | 0.932 | 0.931 |
| ILB | 0.964 | 0.965 | 0.966 | 0.965 | 0.966 | 0.968 | 0.957 | 0.952 |
| CB | 0.922 | 0.921 | 0.922 | 0.922 | 0.920 | 0.913 | 0.915 | 0.918 |
| S | 0.934 | 0.931 | 0.931 | 0.934 | 0.910 | 0.954 | 0.929 | 0.923 |
| QB | 0.986 | 0.986 | 0.986 | 0.986 | 0.986 | 0.971 | 0.980 | 0.976 |
| RB | 0.991 | 0.991 | 0.991 | 0.991 | 0.991 | 0.984 | 0.990 | 0.990 |
| WR | 0.985 | 0.985 | 0.985 | 0.985 | 0.985 | 0.984 | 0.983 | 0.981 |
| TE | 0.983 | 0.983 | 0.983 | 0.983 | 0.982 | 0.983 | 0.979 | 0.982 |
<!-- /table:sensitivityRho -->

A winner's-curse check on 2025 (below) says the free-agent pool as a group keeps its means; it is
the *selection of the best one* that is lucky, which is why the median-of-five is the primary.

## Verified event rates versus provisional variance assumptions

**Verified** (observed counts, scorer-checked): events per appearance, the card's points per event,
appearance and bye records. **Provisional** (assumed, and varied): everything about the *spread*:
that a player's own six weeks are his distribution (E), that the 2025 archetype shape applies (S),
that two moments suffice (P), that events are independent (Q), that players are independent within a
week, that free-agent claims are free and uncontested, and that availability is the observed share.

The event counts themselves are close to Poisson; the score is not:

<!-- table:variance -->
| group | players | observed / Poisson score variance (median) | sack dispersion | TFL dispersion | QB-hit dispersion | PD dispersion | solo-tackle dispersion |
|---|---|---|---|---|---|---|---|
| EDGE | 72 | 2.41 | 0.96 | 1.05 | 1.13 | 1.03 | 1.04 |
| DT | 29 | 1.98 | 0.94 | 0.94 | 1.12 | 1.17 | 1.00 |
| DL (EDGE+DT) | 101 | 2.38 | 0.95 | 1.01 | 1.13 | 1.09 | 1.02 |
| ILB | 58 | 1.35 | 0.93 | 1.02 | 1.08 | 1.02 | 1.34 |
| OLB | 7 | 1.93 | 1.07 | 0.85 | 1.17 | 1.05 | 1.61 |
| LB (ILB+OLB) | 65 | 1.45 | 0.96 | 0.98 | 1.10 | 1.03 | 1.39 |
| CB | 50 | 1.83 | 1.03 | 1.02 | 1.06 | 1.12 | 1.30 |
| S | 45 | 1.46 | 0.94 | 1.11 | 0.97 | 1.05 | 1.21 |
| DB (CB+S) | 95 | 1.60 | 0.97 | 1.07 | 1.00 | 1.10 | 1.26 |
| IDP (all six) | 261 | 1.86 | 0.96 | 1.01 | 1.12 | 1.09 | 1.23 |
<!-- /table:variance -->

Sacks, TFL and pass defenses have a dispersion index near 1.0 (QB hits 1.1, solo tackles 1.0-1.4), yet the
weekly score has about 1.9 times the variance of independent Poisson events (2.4 for EDGE, 1.35 for
ILB). The gap is co-movement between event types (the card pays a sack, a TFL and a QB hit on one play;
tackles ride on snaps) plus yardage and touchdown components the Poisson model holds fixed. It was
not decomposed further. This is why `Q` roughly halves the IDP premium and why independent-event
reasoning is not safe for this scoring card.

What the shipped best-ball model assumes about spread (`PointsModel`; this checkout has no fitted
artifact, so these are its documented fallback constants):

<!-- table:library -->
| position family | n | library assumed CV | observed SD/ppg (2026 wk 1-6) | prior-season pooled SD/ppg | observed / assumed |
|---|---|---|---|---|---|
| DL | 58 | 0.55 | 0.73 | 0.87 | 1.34 |
| LB | 65 | 0.45 | 0.52 | 0.73 | 1.17 |
| DB | 93 | 0.50 | 0.65 | 0.75 | 1.29 |
| DL/LB | 45 | 0.55 | 0.80 | n/a | 1.45 |
| QB | 33 | 0.32 | 0.57 | 0.72 | 1.78 |
| RB | 63 | 0.55 | 0.54 | 0.69 | 0.98 |
| WR | 98 | 0.60 | 0.64 | 0.72 | 1.07 |
| TE | 50 | 0.65 | 0.77 | 0.71 | 1.19 |
| K | 21 | 0.55 | 0.46 | 0.52 | 0.83 |
<!-- /table:library -->

The fallback understates the measured spread for DL, DB and especially QB. A box-local fitted
artifact would replace it and was not visible here; this is a finding about the fallback, not about
production.

## Sensitivity: distribution, availability, byes, injuries

<!-- table:models -->
| group (J / ppg) | E (own weeks) | Ec (own weeks, n/(n-1) variance correction) | S (2025 archetype shape, matched) | Su (2025 archetype shape, unfiltered) | P (gamma, archetype CV) | Q (Poisson events) |
|---|---|---|---|---|---|---|
| EDGE | 12.1% | 14.0% | 13.0% | 14.5% | 11.8% | 6.0% |
| DT | 10.5% | 12.1% | 13.6% | 15.9% | 13.0% | 6.9% |
| DL (EDGE+DT) | 11.6% | 13.5% | 13.2% | 14.9% | 12.1% | 6.3% |
| ILB | 6.2% | 7.2% | 8.8% | 14.9% | 8.9% | 5.0% |
| OLB | 9.3% | 10.8% | 13.1% | 20.8% | 13.0% | 5.7% |
| LB (ILB+OLB) | 6.5% | 7.5% | 9.2% | 15.4% | 9.3% | 5.1% |
| CB | 11.8% | 13.5% | 13.9% | 20.1% | 13.4% | 8.5% |
| S | 9.2% | 10.5% | 11.9% | 16.6% | 11.3% | 6.8% |
| DB (CB+S) | 10.5% | 12.1% | 13.0% | 18.4% | 12.4% | 7.7% |
| IDP (all six) | 9.8% | 11.3% | 12.0% | 16.3% | 11.5% | 6.5% |
| QB | 5.5% | 6.6% | 8.8% | 9.1% | 6.4% | n/a |
| RB | 4.0% | 4.8% | 5.0% | 6.8% | 4.9% | n/a |
| WR | 6.5% | 7.7% | 7.1% | 10.1% | 6.5% | n/a |
| TE | 9.2% | 10.6% | 7.9% | 11.4% | 6.8% | n/a |
| K | 4.7% | 5.3% | 6.7% | 6.5% | 6.6% | n/a |
| Offense (QB/RB/WR/TE) | 6.0% | 7.2% | 7.1% | 9.2% | 6.1% | n/a |
<!-- /table:models -->

`E` is the plug-in and understates (n = 6); `Ec` and `S` and `P` agree at 11-12% for IDP. `Su`
treats everyone like a fringe player and is an upper bound. `Q` is a lower bound that the data
reject. The headline 11.9% sits among the corrected models.

<!-- table:sensitivity -->
| group (J / ppg) | base | availability forced to 100% | no bye weeks | injured / out players kept at historical availability |
|---|---|---|---|---|
| EDGE | 12.1% | 12.6% | 13.6% | 13.1% |
| DT | 10.5% | 10.9% | 11.6% | 10.9% |
| DL (EDGE+DT) | 11.6% | 12.1% | 13.0% | 12.5% |
| ILB | 6.2% | 6.4% | 7.2% | 7.0% |
| OLB | 9.3% | 9.6% | 10.3% | 10.1% |
| LB (ILB+OLB) | 6.5% | 6.7% | 7.4% | 7.3% |
| CB | 11.8% | 12.4% | 12.8% | 12.1% |
| S | 9.2% | 9.7% | 10.2% | 9.3% |
| DB (CB+S) | 10.5% | 11.1% | 11.6% | 10.8% |
| IDP (all six) | 9.8% | 10.3% | 11.0% | 10.4% |
| QB | 5.5% | 7.2% | 6.4% | 6.4% |
| RB | 4.0% | 4.7% | 4.7% | 4.6% |
| WR | 6.5% | 7.3% | 7.6% | 7.3% |
| TE | 9.2% | 10.0% | 10.8% | 10.5% |
| K | 4.7% | 4.7% | 5.3% | 4.9% |
| Offense (QB/RB/WR/TE) | 6.0% | 7.0% | 7.1% | 6.9% |
<!-- /table:sensitivity -->

Removing byes raises the premium by about 1 pp (nobody is out for a known reason); forcing 100%
availability raises it by 0.5-1 pp; keeping Out/IR players at their historical availability moves it
by 0.6 pp. None changes an ordering.

## Sample size, reliability and role change

Six weeks are a small sample, and the data say how small:

<!-- table:reliability -->
| archetype | players (2025) | ppg split-half r | CV split-half r | CV full-season reliability (Spearman-Brown) | CV year-over-year r | ppg year-over-year r | first-6-game SD / full-season SD (median) |
|---|---|---|---|---|---|---|---|
| EDGE | 139 | 0.71 | 0.37 | 0.54 | 0.28 | 0.61 | 0.91 |
| DT | 115 | 0.67 | 0.39 | 0.56 | 0.42 | 0.66 | 1.02 |
| ILB | 94 | 0.87 | 0.73 | 0.84 | 0.53 | 0.66 | 0.83 |
| OLB | 28 | 0.88 | 0.70 | 0.82 | 0.56 | 0.80 | 0.83 |
| CB | 127 | 0.77 | 0.68 | 0.81 | 0.45 | 0.51 | 0.87 |
| S | 113 | 0.80 | 0.63 | 0.77 | 0.47 | 0.69 | 0.86 |
| QB | 25 | 0.29 | 0.17 | 0.28 | -0.38 | 0.33 | 0.93 |
| RB | 81 | 0.91 | 0.46 | 0.63 | 0.49 | 0.82 | 0.81 |
| WR | 139 | 0.84 | 0.55 | 0.71 | 0.42 | 0.74 | 0.90 |
| TE | 73 | 0.83 | 0.59 | 0.74 | 0.57 | 0.82 | 0.95 |
| K | 28 | 0.40 | 0.07 | 0.12 | -0.25 | 0.17 | 0.95 |
<!-- /table:reliability -->

A 6-game weekly SD is a median 0.81-1.02 of the full-season SD by archetype (EDGE 0.91, ILB 0.83,
RB 0.81; DT 1.02), the source of the bias correction. Mean ppg is reliable at half-season length
(split-half r 0.67-0.91 outside QB and K). **Pass-rusher spread is not**: the split-half correlation
of CV is 0.37 for EDGE and 0.39 for DT against 0.63-0.73 for ILB, CB and S, and the year-over-year
correlation is 0.28 for EDGE. A player-level "explosive EDGE" label at six games is mostly noise; an
archetype-level statement survives, a player-level one does not.

Role changes: 107 of 486 players compared moved their snap share by at least 15 points between
weeks 1-3 and 4-6.

<!-- table:role -->
| slot class | n | ppg weeks 1-3 vs 4-6 (rank corr) | best-ball marginal 1-3 vs 4-6 | volatility premium 1-3 vs 4-6 |
|---|---|---|---|---|
| DL | 55 | 0.40 | 0.28 | -0.16 |
| LB | 60 | 0.51 | 0.44 | 0.14 |
| DB | 87 | 0.11 | 0.12 | 0.05 |
| DL/LB | 43 | 0.13 | 0.25 | 0.08 |
| QB | 27 | 0.30 | 0.20 | 0.20 |
| RB | 56 | 0.73 | 0.74 | 0.09 |
| WR | 87 | 0.57 | 0.54 | 0.06 |
| TE | 47 | 0.24 | 0.25 | -0.15 |
<!-- /table:role -->

<!-- table:roleWindow -->
| archetype | n | J / ppg, weeks 1-3 | J / ppg, weeks 4-6 |
|---|---|---|---|
| EDGE | 69 | 9.4% | 9.9% |
| DT | 27 | 6.3% | 8.1% |
| ILB | 54 | 5.3% | 3.8% |
| OLB | 8 | 5.6% | 9.0% |
| CB | 48 | 8.5% | 8.9% |
| S | 42 | 7.0% | 6.0% |
| QB | 27 | 3.2% | 2.6% |
| RB | 56 | 2.7% | 3.4% |
| WR | 87 | 4.8% | 5.2% |
| TE | 47 | 6.9% | 5.8% |
| K | 21 | 4.3% | 3.4% |
<!-- /table:roleWindow -->

Early-versus-late rank agreement of ppg is low for DBs (0.11) and DL/LB hybrids (0.13), so a DB's
six-week ppg and best-ball marginal are role-dependent; the player-level premium does not persist
between windows (rank correlation -0.16 to +0.20), while the archetype-level share stays within
about 2 pp (plug-in values; three-game windows shrink the spread further, so these sit below the
headline).

2025 winner's curse (weeks 1-6 band against weeks 7-18): the replacement band (ranks 37-116) kept its
mean in IDP (regression -0.15 to +0.26 ppg), while the top 36 fell 1.5-4.2 ppg
(`reliability.replacementBandWinnersCurse2025`).

In-sample face validity (not a forward test): on the six actual weeks, the model marginal and the
realized-weeks marginal agree at rank correlation 0.97-0.99 in every slot class, better than ppg does
for DBs:

<!-- table:realized -->
| slot class | n | model marginal vs realized-weeks marginal (rank corr) | ppg vs realized-weeks marginal |
|---|---|---|---|
| DL | 58 | 0.98 | 0.96 |
| LB | 65 | 0.98 | 0.97 |
| DB | 93 | 0.98 | 0.92 |
| DL/LB | 45 | 0.99 | 0.96 |
| QB | 33 | 0.97 | 0.96 |
| RB | 63 | 0.99 | 0.99 |
| WR | 98 | 0.99 | 0.98 |
| TE | 50 | 0.98 | 0.97 |
<!-- /table:realized -->

## Limitations

* **In-sample, six weeks.** Nothing here is a forward prediction and nothing is called out-of-sample.
  The directive's independent forward validation is untouched.
* Player-level volatility is partly noise (above). The E model understates spread; the corrected and
  pooled models bracket it.
* Players are independent within a week; shared game environments and event stacking across players
  are not modelled.
* Free agents are claimed free and uncontested, one context at a time; the league-wide competition for
  the same wire player is not simulated.
* Out and IR players are excluded (13% of roster entries); a returning star is not in any pool.
* Fine positions come from two public sources that disagree on 15% of players; the DE/DT line is the
  weakest.
* The 2025 shape is rescored from Sleeper stat lines under the 2026 card; Lane A reconciled the 2026
  host-native scorer, not 2025.
* Not a dynasty value: no horizon, aging, role security, rookie uncertainty, discounting, market
  comparison or 1-9999 conversion. Nothing here says IDPs are over- or under-priced.

## What this does and does not support

* **No multiplier.** The premium depends on the slot economy and on how near the cut line a player is;
  there is no flat IDP, DL or "big-play" uplift in this evidence, and none is proposed.
* A future shadow lineup-utility model should carry weekly distributions through the exact lineup
  solver (this lane's engine is the parity-tested reference) rather than rank by ppg. The place it
  changes answers is DBs and DL/LB hybrids.
* The shipped best-ball `PointsModel` fallback CVs sit below the measured spread for DL (0.55 against
  0.73), DB (0.50 against 0.65) and QB (0.32 against 0.57). If production runs on the fallback, its
  best-ball utility understates IDP and QB volatility value. Separate owner-gated check; not changed.
* Report the marginal as a rank or with its replacement sensitivity, not as a point value.
* Owner approval: none required for this research artifact. Any use in a served value, verdict,
  threshold or source weight needs the directive's evidence package and explicit owner approval.
  Rollback: revert the PR; no data, flag or config was written.

## Reproduce

```bash
python scripts/idp_accuracy/d_run.py --draws 1200 --boots 40 --workers 8   # resumable; writes the evidence JSON
python scripts/idp_accuracy/d_tables.py --write                              # refresh the tables on this page
python -m pytest tests/idp_accuracy/test_bestball_archetypes.py tests/bestball \
    tests/league_valuation/test_isolation.py -q
bash scripts/format_python_changes.sh
```

Public Sleeper and nflverse GETs are cached once under the gitignored `data/idp_accuracy/cache/` and
hashed into the evidence file. The pinned bodies are the reference: a stat correction or a republished
nflverse file can change a re-run.

## UNRESOLVED

* No forward (out-of-sample) test of any statement here; the six-week window is the whole sample.
* Whether production's best-ball model runs on the fallback CVs or a fitted artifact (box-local).
* Which of E, Ec, S, P is the right spread model for the IDP premium; the corrected and pooled ones
  agree at 11-12%, the plug-in says 9.8%, and the unfiltered shape says 16%.
* The DE/DT label boundary between nflverse and Sleeper's depth chart (EDGE versus DT).
* The source of the ~1.9x score-over-Poisson variance (co-movement versus yardage and touchdowns).
* Any conversion of the premium into dynasty trade value; out of this lane's authority.
