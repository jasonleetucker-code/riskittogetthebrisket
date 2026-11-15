# 05. Candidate formula library

**Status: every equation is a hypothesis to be tested. None is fitted, none is served.** Coefficients are named, not estimated. `07_EVALUATION_DESIGN.md` decides which survive. Anything touching the frozen IDP prospective study needs its own separate preregistration and may not reuse its evaluation weeks.

## 0. Notation and rules shared by every model

| symbol | meaning |
|---|---|
| `i`, `t`, `g`, `w` | player, team, game, week |
| `y_ikg` | realized count of stat `k` in Sleeper keys |
| `a_ig` | `P(player i is active in game g)` |
| `shrink(x, n; m, kappa)` | `(n*x + kappa*m) / (n + kappa)` |
| `kappa` | Estimated per position and stat from earlier seasons only: `kappa = E[within-player variance] / Var[true player rates]` (Buhlmann credibility) |

**Rules**

1. A model outputs **Sleeper-key stat lines**, plus `a_ig` and dispersion. Points come only from `score_stat_line`, because the league card is a dot product (`src/league_intel/scorer.py`).
2. Expected points are linear in expected stats: `E[Σ c_k X_k] = Σ c_k E[X_k]`. Means need no joint model; variance and simulation do.
3. Shares sum to one within a team-week before stats are computed. Vendor-documented bottom-up models keep this constraint.
4. Missing input means abstain or fall back to the shrunk baseline, with the fallback counted. Never zero.
5. Unconditional forecast: `E[Y] = a_ig * E[Y | active]`. Both factors are scored separately.

## 1. Team volume layer (every position reads this)

**Double-counting rule for H-VOL1, H3 and E4, binding on the first study.** Betting lines may replace a trailing-rate volume input in a model that uses no vendor projection. No candidate in the first study may combine lines with a vendor-informed consensus, so H3 and E4 run there without line features (`07_EVALUATION_DESIGN.md` gate PG1b). Lifting this needs its own preregistered overlap study.

```text
Implied points (nflverse sign: S > 0 favors home)
  I_home = (T + S) / 2        I_away = (T - S) / 2
Fallback when no line is PIT-valid: I_tg = shrink(trailing points per game)

Team plays
  log E[P_tg] = b0 + b1*log(I_tg) + b2*Sbar_tg + b3*pace_t + u_t
Pass rate
  logit(pi_tg) = a0 + a1*PROE_t + a2*Sbar_tg + a3*max(0, wind_g - 15)*outdoor_g + v_t
Volumes
  DB_tg = P_tg * pi_tg           (dropbacks)
  A_tg  = DB_tg * (1 - sackrate_t)
  R_tg  = P_tg * (1 - pi_tg)
Touchdowns
  E[TD_tg] = rho0 + rho1*I_tg      TDpass_tg = E[TD_tg]*phi_t     TDrush_tg = E[TD_tg]*(1-phi_t)
```

`Sbar_tg` is the signed spread from team `t`'s view. `wind` enters only with a threshold: external evidence points to a threshold near 15-20 mph, and that evidence is informal.

| hypothesis | baseline to beat | kill rule |
|---|---|---|
| H-VOL1: market lines beat trailing team rates for next-week plays and points | Shrunk trailing team average | No MAE gain on `P_tg`, `A_tg` over three held-out seasons |
| H-VOL2: `PROE` adds to the spread | Spread only | Gain within noise |
| H-VOL3: wind threshold helps pass volume and kicking | No weather term | Coefficient unstable across seasons |

## 2. Weekly position models

Every position below is an instance of one identity. Availability, participation and share are forecast separately, and each can be evaluated alone:

```text
E[stat_k for player i in game g] = a_ig * TeamVolume_tg * Participation_ig * Share_ig * Efficiency_ik
```

### QB

```text
A_ig = A_tg * starter_share_ig
pass_cmp = A_ig * cp_i          cp_i = shrink(cp, A; team/pos mean, k_cp)
pass_inc = A_ig - pass_cmp
pass_yd  = A_ig * ypa_i         ypa_i = shrink(ypa, A; pos mean, k_ypa)
pass_td  = TDpass_tg * starter_share_ig
pass_int = A_ig * int_i         int_i = shrink(int, A; pos mean, k_int), k_int large
pass_sack= DB_ig * sack_i
rush_att = DB_ig * scramble_i + R_tg * designed_i
rush_yd  = rush_att * ypc_i     ypc_i = shrink(ypc, rush_att; pos mean, k_ypc)
rush_td  = TDrush_tg * qb_goal_share_i
bonus_fd_qb: imputed by src/nfl_data/first_down_rate.py from yards
```

### RB

```text
rush_att_ig = R_tg * c_ig       c_ig: Beta posterior on last 4 weeks of carry share
targets_ig  = A_tg * tg_ig      tg_ig: Beta posterior on target share
Normalize Σ_j c_jg = 1 and Σ_j tg_jg = 1 inside team
rush_yd     = rush_att_ig * ypc_i     k_ypc large (year-over-year YPC r about 0.16 [X])
rec         = targets_ig * cr_i
rec_yd      = rec * ypr_i
rush_td     = TDrush_tg * gl_share_ig
rec_td      = TDpass_tg * rz_target_share_ig
rec_0_4 ... rec_40p = rec * band_share_i      (src/nfl_data/reception_shape_projection.py)
bonus_fd_rb: imputed from yards
```

### WR

```text
rp_ig     = route participation forecast (proxy in-season: snap share on pass plays)
tprr_i    = shrink(targets per route, routes; pos mean, k_tprr)
s_ig      = rp_ig * tprr_i / Σ_j rp_jg * tprr_j
targets_ig= A_tg * s_ig
rec       = targets_ig * cr(aDOT_i)
rec_yd    = targets_ig * cr(aDOT_i) * (aDOT_i + yac_i)
rec_td    = TDpass_tg * rz_target_share_ig
rec_wr_bonus = rec * bonus rate per card
bands, first downs as above
```

### TE

Same as WR, with `rp_ig = snap_share_ig * route_rate_given_snap_i`. `route_rate_given_snap_i` is partly a blocking role, so it is pooled by depth slot, not by position alone. TE samples are smaller, so `kappa` is larger. **`dynasty_main`'s 2026 card pays no TE premium** (`CLAUDE.md`, FAAB section), so TE value in that league comes from volume and slot demand only.

### K

```text
FGA_ig ~ NegBin(mean = exp(c0 + c1*log(I_tg) + c2*drive_stall_t), phi_K)
Distance mix pi_d from team and venue, shrunk to league
logit m_id = alpha_d + k_i + w1*wind_over_15_g*outdoor_g       k_i shrunk hard
fgm_yds = FGA * Σ_d pi_d * m_id * yards_d
fgmiss_d = FGA * pi_d * (1 - m_id)
xpm = TD_tg * (1 - two_pt_rate_t) * xp_make_i
```

Expected signal is low. Kicker holdouts in the repo are noisy, with 53 holdout player-weeks (`docs/league-intelligence/ROS_SCALE_CALIBRATION_RESULTS_2026-10-28.md`). The team total is likely the whole model `[I]`.

### Defensive players, common form

```text
OppPlays_tg = P_(opp)g
snaps_ig    = OppPlays_tg * ds_ig        ds_ig: snap-share forecast with role state
y_ikg | active ~ NegBin(mean = snaps_ig * lambda_ik * x_kg, phi_k)
log lambda_ik = alpha_(group,k) + u_ik     u_ik ~ N(0, tau^2_(group,k))
x_kg defaults to 1; admitted only when it beats the model without it
```

Groups are EDGE, DT, LB, S, CB. **DL on the league card is EDGE plus DT.** When subgroup is unknown, the player falls back to a DL or DB family group rather than a guessed subgroup; the retrospective census found 652 players with unknown subgroup and 218 EDGE-to-LB cases (`docs/research/amath/SITEWIDE_PROJECTIONS_2026-11-01.md`). Position identity comes from the existing `pff_position` and season-roster crosswalk (`src/ros/idp_opportunity/positions.py`). The repo measured that opponent and injury-replacement `x` terms add about nothing or harm, so `x = 1` is the starting point.

| group | stats and exposure |
|---|---|
| **EDGE** | `idp_sack`, `idp_qb_hit`: exposure `snaps_ig * pass_rate_opp`. `idp_tkl_loss`: exposure `snaps_ig * (1 - pass_rate_opp)` plus pressure-to-TFL share |
| **DT** | Same stat forms. Lower sack rate, higher TFL rate as a class is a **hypothesis**: the repo found the TFL rule does not favor DT as a class (`docs/valuation/idp_accuracy/H_RECOMMENDATIONS.md` Q4) |
| **LB** | Tackle-pool share: `TP_g = OppPlays_tg * (1 - inc_rate_opp - sack_rate_opp)`; `tackles_ig = TP_g * tshare_ig`; solo and assist split by stadium-scorer effect (a PFF-mentioned quirk, method undocumented) |
| **S** | Tackle share, `idp_pd` on targets faced; box vs deep alignment is unavailable publicly in-season, so the group is pooled |
| **CB** | `idp_pd = targets_faced_ig * pd_i`. In-season `targets_faced_ig` has no clean public source; the fallback is `opp_pass_attempts * ds_ig * tf_i`. Persistence is very low (DB .11 wk1-6 to wk7-12 `[R]`) |

Sack, TFL and QB-hit co-occur and the scorer stacks them. Per rule 2, means can be estimated per key; variance must come from a play-level or joint model.

**Special teams** (`st_tkl_solo`, `st_ff`, `st_fum_rec`, return yards): vendors do not publish these for most players. Candidate: `st_snaps_ig * rate_group`. Low value; test last.

## 3. Season and rest-of-season

```text
E[Pts_i,ROS] = Σ_(w in remaining) a_iw * m_iw
Var[Pts_i,ROS] = Σ_w [a_iw*v_iw + a_iw*(1 - a_iw)*m_iw^2] + 2*Σ_(w<w') Cov
m_iw  = E[points | active]    v_iw = Var[points | active]
```

Best-ball value is not this sum. It is a difference of expected optimal lineups, computed by simulation through `src/ros/lineup.py`.

**In-season update.** Compare three forms.

```text
U0 (served by BDVM): mu_post = w*mu_prior + (1-w)*ybar_n,  w = n0/(n0+n), n0 = 6 offense / 8 IDP priors
U1: n0 estimated per position and stat family from earlier seasons
U2: update shares and rates, not points, then recompute through section 1
```

H-UPD1: U1 beats U0. H-UPD2: U2 beats U1 for players with changed role. Baseline: U0.

## 4. Rookies

```text
Target: PPG3 = best of first three seasons' points per game; H = 1 if PPG3 >= position startable line

Pre-draft
  logit P(H_i) = a_pos + s1(college_rec_share_i) + s2(breakout_age_i) + s3(draft_age_i)
                 + s4(athleticism_i) + u_conf
Post-draft
  logit P(H_i) = a_pos + b1*log(pick_i) + s1(college_rec_share_i) + s2(breakout_age_i)
                 + b2*vacated_opportunity_t + u_conf
  E[PPG3] = two-part: P(H) * E[PPG3 | H] + (1 - P(H)) * E[PPG3 | not H]
```

College inputs come through CollegeFootballData, the rights-clean route (`02_`). Combine data on nflverse is PFR-sourced and is not admitted for training until findings there are resolved.

| hypothesis | baseline to beat | prior evidence |
|---|---|---|
| H-ROOK1: draft capital carries most of the signal | Slot prior `src/bdvm/baseline.py::build_rookie_prior_records` | Vendor write-ups conflict `[X]`; Massey-Thaler 2013 shows top-pick mispricing in the NFL draft, Brill-Wyner 2026 disputes the utility assumption `[L]` |
| H-ROOK2: college production adds after capital | Capital only | Mixed, mostly small-sample `[X]` |
| H-ROOK3: combine adds little | No combine term | Kuzmits-Adams 2008 found little beyond RB sprints `[L]` |
| H-ROOK4: market rookie price beats all of the above | Market (`src/draft/vendor_comparison.py`) | `[I]` Expect market to be hard to beat near-term |

Sample limit: roughly 15-25 fantasy-relevant rookies per position per draft class `[I]` gives few effective events. Intervals will be wide, and that must be stated.

## 5. Dynasty career and survival

```text
Production aging
  PPG_(i,a) = f_pos(a) + b*role_(i,a) + u_i + e_(i,a)        f_pos: penalized spline
  Survivorship: weight by inverse P(still in league at age a); compare with an unweighted delta curve
Startable-status hazard, discrete time
  logit h_i(a) = alpha_pos(a) + b1*draft_capital_i + b2*career_ppg_i + b3*games_missed_lag_i
                 + b4*role_lag_i
  Competing risks: retired, cut, demoted, injured out
Survival: S_i(H) = Π_(k<=H) (1 - h_i(a_i + k))
Fundamental career value (existing BDVM form)
  CV_i = Σ_h gamma^h * S_i(h) * E[max(0, X_ih - R_ih)]
```

`src/bdvm/survival.py` already implements hazards from priors. This section supplies the empirical challenger. Aging studies show mid-20s RB peaks but are survivorship-biased `[X]`.

**CV is football production value, not market value.** It may be compared with market value and is never merged into it.

| hypothesis | baseline | kill rule |
|---|---|---|
| H-CAR1: a fitted hazard beats the prior hazard for 1- and 2-year startable status | `src/bdvm/survival.py` schedule | Brier not better on held-out draft cohorts |
| H-CAR2: market value alone predicts next-year production as well as CV | Market rank | CV gives no incremental lift |

## 6. Expected fantasy points

```text
xStats per opportunity o: E[Y_k | x_o] for k in Sleeper keys
xPts_ig = Σ_o Σ_k c_k * E[Y_k | x_o]
Baseline features: yardline, down, distance, air yards, target location, goal-to-go
```

Compute expected **stats**, not points, so the league card applies, including reception bands. `ffopportunity` is a fixed-card baseline and is CC-BY-SA.

H-XFP1: trailing xStats predict next-week points better than trailing points. H-XFP2: `xStats` adds nothing once shares are in the model. Expect H-XFP2 to hold for targets but not for TD regression `[I]`.

## 7. Availability

```text
Stage 1  logit P(active_ig) = a_status + b1*practice_g + b2*age_i + b3*pos + b4*missed_share_i
Stage 2  ds_ig | active   = role_state forecast (returning-from-injury state separate)
ROS      P(available in week w) from out-duration model by injury class
```

Training data: nflverse injuries (2009+), file not timestamped, so a separate cohort label. Forward data: `src/nfl_data/injury_history.py`. External note: questionable players played about 53-58% in dated studies `[X]`. Practice status probably carries more signal, though the source for that is a betting guide.

Baseline: `P(active) = 1` for rostered, and status-only rates. Beating status-only rates is required for Brier.

## 8. Correlation-aware simulation

Build only after marginals pass calibration (`07_` stage 2).

```text
Residual z-score per player-game:
  z_ig = l_pos1 * G_g + l_pos2 * T_tg + psi_i * e_ig        G, T, e ~ N(0,1)
  Y_ig = F_ig^-1(Phi(z_ig))
Share conservation: within a team, draw team targets then allocate by Dirichlet shares
```

Factor loadings come from residual pair covariance, following the repo's V3-D4 approach (same-team τ² about 0.0169 vs 0.0088 roster-wide, `SITEWIDE_PROJECTIONS` finding 3). Expected signs: QB and pass-catcher positive; RB and pass-catcher slightly negative; opposing offense plays and defenders' tackles positive.

Baseline: independence. Metric: energy score and team-week CRPS. H-SIM1: a one-factor game model improves team coverage without worsening CRPS.

## 9. Sportsbook-implied inputs and margin removal

```text
Implied raw probability:  q = 100/(o+100) if o > 0,  q = |o|/(|o|+100) if o < 0
Overround:                M = Σ_j q_j
Multiplicative:           p_j = q_j / M
Additive:                 p_j = q_j - (M - 1)/n
Power:                    p_j = q_j^k,  k solved so Σ_j p_j = 1
Shin:                     p_j = [sqrt(z^2 + 4(1-z) q_j^2 / M) - z] / [2(1-z)],  z solved so Σ p_j = 1
```

Arithmetic verified in this session for a -140/+120 two-way market:

| method | favorite | underdog |
|---|---|---|
| Multiplicative | 0.5620 | 0.4380 |
| Additive | 0.5644 | 0.4356 |
| Shin | 0.5644 | 0.4356 |
| Power | 0.5656 | 0.4344 |

Additive and Shin coincide for two outcomes across the four test prices, matching the `implied` package vignette. Power pulls favorites furthest at long prices (+450/-700: 0.1418 vs 0.1534 additive).

**Props to stat means**

```text
Receptions L at price p: solve P(X > L; mu, phi_pos) = p for mu, X ~ NegBin
Yards L: X ~ lognormal(mu, sigma_pos), sigma_pos fixed by position: mu = ln L + sigma_pos * Phi^-1(p)
         implied mean yards = exp(mu + sigma_pos^2 / 2)
Anytime TD (one-sided): lambda = -ln(1 - p), after removing an estimated one-sided margin
```

Rules: several books quoting one market are one family (`docs/PROJECTION_ENSEMBLE_PLAN_2026-08-15.md` §6). Lines must be captured before a stated cutoff. Props history starts 2023-05-03 (`02_`), so training sets are short.

H-MKT1: game lines beat trailing team stats (section 1). H-MKT2: prop-implied means beat vendor projections at QB and WR. H-MKT3: power beats multiplicative for long-shot TD markets (Štrumbelj 2014 reports method choice matters `[L]`).

## 10. Ensembles

```text
E0 equal-family mean:     mu = (1/F) * Σ_f mu_f
E1 family median
E2 constrained regression, shrunk to equal: w = (1-delta)*(1/F) + delta*w_hat, w >= 0, Σ w = 1
E3 stacking of predictive densities: max_w Σ_t log Σ_f w_f p_f(y_t)
E4 residual model: y - mu_E0 = f(x), strongly regularized
```

Combine on stat lines per category where families publish the same keys. Where coverage differs, use the existing vocabulary-aware rule (`src/bdvm/source_vocabulary.py`, `vocabulary_dominated_weight_mult`). Ancestry overlap goes through `projection_source_census.ancestry_overlaps`.

| hybrid | meaning | test order |
|---|---|---|
| **H4 gap fill** | Vendor where vendor projects a category; ours for categories none publish | Already partly live (`first_down_rate`, `reception_shape_projection`). Evaluate as is |
| **H2 family vote** | `brisketInternal` becomes one family in E0 | First real test once two families exist |
| **H3 prior update** | Consensus as prior; in-season evidence updates volume | After H2 |
| **H1 residual** | E4 | Last; highest overfit risk |

Expect E0 to be very hard to beat in means (combination puzzle). E2 needs many weeks of archived forecasts; a season is unlikely to be enough `[I]`.

## 11. Distributions and decision quantities

```text
D0 (served):   max(0, N(mu, max(0.5, mu*cv_pos)))
D1 lognormal:  log(y + 1) = log(mu + 1) + e,  e ~ N(b_pos, s_pos^2)
D2 hurdle:     P(y <= 0.5) = logit^-1(g0 + g1*log mu); positive part as D1
D3 empirical:  y - mu resampled from earlier residuals, stratified by position and projected tier

Decision outputs
  Exceedance:    P(Y_candidate > Y_roster_cut)
  Marginal gain: E[optimal lineup with candidate] - E[optimal lineup without]
  Regret:        realized best action points - realized chosen action points
```

D1-D2 follow `docs/research/amath/SITEWIDE_PROJECTIONS_2026-11-01.md` PoC-1 and are not re-derived here. Decision outputs use the existing exact solver.

## 12. Things deliberately not proposed

| not proposed | reason |
|---|---|
| A new points scale from `rosValue` | Studied elsewhere; the calibration study owns it |
| Opponent multipliers on offense as a default | Team totals carry most of this; DvP evidence is weak |
| Per-player rate models for splash IDP stats without shrinkage | Failure mode noted in `src/nfl_data/reception_shape_projection.py` |
| Any forecast entering `rankDerivedValue` | Prohibited (`docs/REDRAFT_ROS_INTELLIGENCE_SPEC.md` §3) |
| DFS or League Tycoon integration | Owner-paused |
