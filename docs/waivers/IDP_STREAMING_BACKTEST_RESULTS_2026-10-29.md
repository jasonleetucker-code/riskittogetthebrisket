# IDP weekly streaming backtest — RESULTS (2026-10-29)

**Status:** research / shadow.  First results of the harness preregistered in
[`IDP_STREAMING_BACKTEST_PREREGISTRATION_2026-10-29.md`](IDP_STREAMING_BACKTEST_PREREGISTRATION_2026-10-29.md)
(committed alone, before any result).  Nothing here changes a value, a ranking, a FAAB
recommendation or a route.  Harness: `src/waivers/streaming_backtest.py` (isolated, nothing
live imports it).  Machine-readable evidence (anonymous):
[`evidence/idp_streaming/results_2026-10-29.json`](evidence/idp_streaming/results_2026-10-29.json).

**Studied manager:** "manager B" (the league's heaviest defender streamer).  Other teams are
anonymous per-season labels ordered by their hold-baseline lineup points; no Sleeper id or
name appears in any committed artifact.

## 1. Answer

**Yes — manager B's defender streaming is associated with a measurable gain in realized
starting-lineup points.  It is not explained by the offense he released to make room
(baseline 1b, below), but two confounds remain unseparated: injury replacement (the hold
baseline keeps 4.3 non-playing defenders a week in 2026 vs 3.3 in his actual roster) and
extra depth (he carries ~5 more defenders than hold, 32.2 vs 27.0).  The estimate is
"streaming as he practises it", not "churn alone".**

| quantity (manager B, actual − hold, per decision week) | mean | 95% CI | n | verdict |
|---|---|---|---|---|
| **2026** (weeks 2–7; host-awarded best-ball points) | **+19.9** | [+10.1, +30.2] | 6 weeks | gains |
| 2025 (weeks 2–13; optimal-lineup POTENTIAL points, see §3) | +11.5 | [+0.6, +23.5] | 12 weeks | gains |
| pooled (preregistered primary endpoint) — **mixes 2026 awarded points with 2025 potential points** (deviation 1, §7) | +14.3 | [+6.1, +22.9] | 18 weeks | gains |
| pooled, hold that also restores the offense released to make room (baseline 1b) | +15.3 | [+6.7, +24.2] | 18 weeks | gains |

For scale: manager B's 2026 hold lineup averages ~407 points a week, so +19.9 is roughly
+5%.  Every team in the league gains from its own waiver activity on average (2026
+4.6/team-week [+0.7, +8.6], 12 team-seasons); manager B's 2026 gain is about four times the
league's.

**No simple rule reproduces it.**  Paired by week against the same hold reference, manager
B's actual behavior beats every preregistered simple rule (masked pool, S = 3) in 2026:

| rule | B actual − rule, 2026 | pooled 2025+2026 |
|---|---|---|
| 2 previous-week points | +28.7 [+11.7, +46.5] (n 6) | +24.9 [+15.4, +34.3] (n 18) |
| 3 rolling recent production | +22.5 [+5.2, +44.0] (n 6) | +13.1 [−0.0, +26.3] no detectable effect (n 18) |
| 4 single projection provider | +23.2 [+10.0, +37.5] (n 6) | +12.1 [+4.2, +20.4] (n 18) |
| 6 release lowest dynasty value | +29.1 [+15.6, +41.9] (n 6) | 2026 only |

(These paired comparisons were not preregistered; they are exploratory, see §5.)

## 2. What manager B actually does

| | 2026 (weeks 1–7) | 2025 (weeks 1–13) |
|---|---|---|
| defender waiver / free-agent adds (all, incl. add-and-drop inside a week) | **51** (league mean 16.7) | **59** (league mean 26.0) |
| of which before week 1 kickoff | 10 | 18 |
| adds by group DL / LB / DB | 17 / 17 / 17 | 15 / 17 / 27 |
| adds per effective week after week 1 | 5–8 | 2–6 |
| FAAB on defender waiver wins | $64 over 48 wins, 44 of them at $0 | $18 over 49 wins, 43 at $0 |
| ... of which on matchup-visible in-season adds (`moveOutcomes.faabSpent`) | $0 | $3 |
| mean defenders carried, actual vs hold | 32.2 vs 27.0 | 22.8 vs 24.2 |
| defender starter slots filled by a streamed player | 17 of 54 (31%) | 27 of 108 (25%) |
| matchup-visible streaming adds | 37 | 33 |
| added player made the optimal lineup in its first week | 27% (league 32%) | 21% (league 36%) |
| paired with a release: added − released points, next week | +7.3 (league +5.5) | +3.0 (league +2.6) |
| paired: added vs released points over next 3 weeks | 23.4 vs 10.6 | 25.5 vs 20.1 |
| false-positive share (add scored less than its release over 3 weeks) | 13% of 23 (league 28% of 76) | 27% of 22 (league 38% of 76) |
| point-in-time value released / acquired (IDP Trade Calculator, NOT canonical) | 17,334 over 15 valued (8 unvalued) / 14,658 over 14 valued | unavailable (before 2026-07-14) |

**Why `moveOutcomes.faabSpent` ($0 / $3) differs from the activity FAAB ($64 / $18).**  Not a
defect: `activity` counts every defender waiver win processed before the last scored week
ended, while `moveOutcomes` counts only adds that appear as a week-over-week change on the
matchup rosters (weeks 2+).  Traced in the private detail: all four non-zero 2026 claims
($51, $11, $1, $1) were processed before the week-1 kickoff, so those players are part of
the week-1 starting roster and never appear as an in-season change.  2025: $9 was
pre-season (three $3 claims), $3 was matchup-visible ($1 + $2), and one $6 claim re-acquired
a player already on the roster through an earlier add, so the visible change is attributed
to that earlier transaction.

Reading: he churns about three times the league's rate, almost entirely with $0 claims;
most adds never start; but the adds he pairs with a release out-score the release
(13% false positives in 2026 against the league's 28%), and roughly a quarter to a third of
his defender starts come from streamed players.  In 2026 he also carries ~5 more defenders
than the hold baseline would — funded by releasing non-defenders who, measured by baseline
1b, contributed nothing to his best-ball lineups (1b moves the 2026 estimate by 0.0).

## 3. Data and verification

| check | 2026 | 2025 |
|---|---|---|
| league-card rescoring vs host `players_points` (tolerance 0.011) | 4,867 / 4,867 (max Δ 0.004) | 7,021 / 7,021 (max Δ 0.005) |
| exact solver + slots vs host-awarded team totals | **84 / 84** (published slots verified) | **14 / 130** — see below |
| forward transaction reconstruction vs matchup rosters, defenders only | 82 / 84 exact | 114 / 130 exact |
| ... all players | 68 / 84 | 97 / 130 |
| defender roster changes attributed to a transaction | 245 / 247 | 359 / 376 |
| weekly projections present (decision weeks) | weeks 1–7 | weeks 1–13 |
| projection rows stamped `updated_at` AFTER that week's first kickoff | **100%** (4,315) | **100%** (7,915) |

**2025 was not played as best ball.**  The 2025 league object TODAY says best ball, 10 teams
and 17 starters (2 DL / 2 LB / 2 DB), but the host's own 2025 matchups seat 22 starters and
award totals below the optimal lineup on 116 of 130 team-weeks (max shortfall 23.3).  The
harness therefore (a) recovers the 2025 slot list from the host's slot-ordered `starters`
arrays (every host lineup is a legal fill of `QB RB RB WR WR WR TE TE FLEX FLEX FLEX
SUPER_FLEX K DL DL IDP_FLEX LB LB LB DB DB DB`), and (b) labels every 2025 lineup number as
**optimal-lineup POTENTIAL points**, not the awarded score.  The 2025 scoring card is
verified (rescoring is exact).  2026 is the season where the measured quantity is exactly
the host's rule.

**Projections are not point-in-time.**  Every Sleeper/RotoWire weekly projection row fetched
today for a past week carries a provider `updated_at` after that week kicked off (2026 week
3: every row stamped 2026-09-29).  Baselines 4 and 6 therefore read projections that MAY
have been revised after the games; that bias would favor them, and they still show no
detectable gain in 2026.  The point-in-time source (Game Day's pregame archive) exists on
the production box only and was not available here.

**Projection accuracy** (provider of baseline 4, league-card points, player-weeks with a
stat line):

| | DL | LB | DB |
|---|---|---|---|
| 2026 MAE / RMSE / bias (proj − realized) | 4.47 / 6.55 / −1.09 (n 1,575) | 4.84 / 7.31 / −1.35 (n 1,096) | 4.65 / 7.01 / −1.57 (n 1,609) |
| 2025 MAE / RMSE / bias | 4.74 / 7.03 / −1.07 (n 2,822) | 4.75 / 6.85 / −0.49 (n 2,044) | 4.34 / 6.21 / −0.51 (n 3,021) |

The provider under-projects every IDP group under this card, with weekly errors near the
size of a typical defender's score.  (Not decomposed here; a likely contributor is
league-paid IDP keys the provider does not project, which `sleeper_weekly_projections`
reports per player as `uncovered_scoring_keys`.)

**Dynasty value.**  The canonical-board history lane is a production-only store and is absent
here, so no canonical dynasty value is reported.  The named alternate is the vendor-published
IDP Trade Calculator value at the decision instant (temporal ledger rebuilt locally from the
tracked `exports/archive/`, instant-strict).  2025 is entirely before the 2026-07-14 history
floor: unavailable, never today's value.

## 4. Baselines (primary variant: contention-masked pool, S = 3 swaps/week)

Δ = scenario minus baseline 1 (hold), realized lineup points per decision week.

| baseline | season | manager B | league (per team-week; n = team-seasons) | adds / team-week | false-positive share | add made lineup |
|---|---|---|---|---|---|---|
| 1 hold | — | reference | reference | 0 | — | — |
| 2 previous-week points | 2026 | −8.8 [−21.8, +2.2] no detectable effect | −1.6 [−5.8, +2.6] (12) | 3.0 | 0.43 | 0.27 |
| | 2025 | −11.5 [−19.0, −3.0] **loses** | −4.7 [−8.1, −1.1] **loses** (10) | 3.0 | 0.47 | 0.33 |
| 3 rolling production | 2026 | −2.6 [−16.9, +7.5] no detectable effect | +3.1 [−1.6, +7.8] (12) | 2.5 | 0.35 | 0.34 |
| | 2025 | +3.1 [−11.4, +15.9] no detectable effect | −4.9 [−10.0, +0.0] (10) | 2.75 | 0.53 | 0.37 |
| 4 single projection provider | 2026 | −3.3 [−13.3, +7.0] no detectable effect | −3.6 [−8.2, +0.8] (12) | 2.6 | 0.54 | 0.35 |
| | 2025 | +4.9 [−3.3, +14.4] no detectable effect | +3.9 [+0.9, +6.9] gains (10) | 2.9 | 0.49 | 0.58 |
| 5 independent consensus | — | **N/A** — one weekly IDP projection family historically | | | | |
| 6 release lowest dynasty value | 2026 | −9.2 [−18.8, +0.4] no detectable effect | −3.1 [−8.7, +2.9] (12) | 2.8 | 0.51 | 0.35 |
| | 2025 | **N/A** (before history floor) | | | | |
| 7 dynasty-safe optimizer | — | **NOT RUN** — awaiting W4 (§6) | | | | |
| 8 actual behavior | 2026 | **+19.9 [+10.1, +30.2] gains** | +4.6 [+0.7, +8.6] gains (12) | — | — | — |
| | 2025 | +11.5 [+0.6, +23.5] gains | +12.0 [+6.1, +17.3] gains (10) | — | — | — |

Rule FAAB: masked-pool adds cleared waivers unclaimed, so their cost is genuinely $0.
Unmasked variants (an upper bound — the rule would have had to win claims it never bid on)
report FAAB as unknown, never $0.  All 6 variants per rule (masked/unmasked × S = 1/3/5),
pooled cells, and per-rule point-in-time value flows are in the evidence JSON.  The
sensitivity variants do not change the picture: across every rule and variant, manager B's
cell is "no detectable effect" or "loses" except four 2025 cells — rolling production S = 1
(both pools), projection S = 1 masked and S = 3 unmasked — all on 2025 potential points, the
projection ones on projections that are not point-in-time.
Every naive rule releases more point-in-time value than it acquires in 2026 (e.g. manager B
under rule 3: 23,355 released vs 6,890 acquired over the valued players).

## 5. Limitations (read before quoting)

* **Small n.**  Manager B's 2026 cell is 6 weeks; it clears the preregistered minimum but the
  CI is wide.  The pooled endpoint mixes 2026 awarded points with 2025 potential points.
* **Bootstrap coverage at n = 6.**  The percentile bootstrap over six weekly values tends
  to under-cover, and weekly deltas are serially correlated (the same rostered defenders
  carry over), which the week-resampling bootstrap ignores.  The 2026 "gains" verdict for
  manager B rests on this interval; the pooled n = 18 cell and the league cluster bootstrap
  are less exposed, but the same caveat applies in weaker form.
* **Stat corrections.**  Every weekly stat line was fetched today, so earlier weeks include
  corrections the provider published after the week-*w* cutoff.  For SCORING that is the
  right number (the host awards corrected stats); for the DECISION inputs of rules 2 and 3
  it is a small, unmeasured hindsight.
* **Many cells.**  ~70 cells are reported; at 95% a few "gains"/"loses" verdicts outside the
  primary endpoint are expected by chance.  The primary endpoint is manager B's actual − hold.
* **Hold includes injury replacement.**  Baseline 1 keeps injured / inactive defenders; part
  of any waiver gain is replacing them (manager B's hold set averages 4.3 non-playing
  defenders a week in 2026 vs 3.3 actual).  The simple rules never release a defender whose
  metric is unknown (unknown is not zero), so they cannot do injury replacement — one reason
  they trail actual behavior.
* **Others' behavior is fixed.**  Each team is replayed alone against the other teams'
  actual rosters; a held player may sit on another team's actual roster in the same week.
* **Player dump coverage.**  A defender missing from today's dump would count as offense in
  every scenario.  Measured: 0 of 833 (2026) and 0 of 716 (2025) rostered player ids are
  missing, so the matchup-roster side is complete; an unrostered 2025 defender since removed
  from the dump would be absent from the waiver pool (unmeasured).
* **Positions** come from today's Sleeper player dump (a mid-season position change is an
  approximation).  Two-way players are treated as defenders for swap purposes but the exact
  solver may seat them anywhere they are eligible.
* **Not modelled:** waiver priority / FAAB contention for rules (masked pool sidesteps it),
  in-week lineup timing beyond the host's matchup roster, dynasty value in canonical terms.

## 6. Interface for baseline 7 (W4)

`src/waivers/streaming_backtest.py` calls any policy through
`StreamingPolicy.decide(ctx: DecisionContext) -> Sequence[Swap]` and enforces legality
itself (drop must be rostered, add must be in the pool and not already rostered, at most
`ctx.max_swaps` applied, rejects counted).  `DecisionContext` is built only by
`build_decision_context` (the leakage boundary) and carries: `season`, `week`, `cutoff_utc`,
`team_index`, `idp_roster`, `pool`, `positions` (player → swap group DL/LB/DB),
`eligibility` (fantasy positions), `idp_slots`, `realized_before` (weeks < w only),
`projection` (week w, `projection_point_in_time_verified=False`), `dynasty_value` (known
before the cutoff; `dynasty_value_source` names the quantity), `max_swaps`.
`Swap(drop_id, add_id, faab_bid | None)`.  To run baseline 7: add
`("7_full_dynasty_safe_optimizer", <factory returning W4's policy>)` to `RULE_POLICIES` and
re-run; nothing else changes.

## 7. Deviations from preregistration

1. **2025 lineup quantity** — preregistered as best-ball realized lineup; measured to be
   manager-set, so 2025 numbers are optimal-lineup POTENTIAL points with slots recovered
   from host lineups (§3).  2026 is unaffected.
2. **Effective week of a transaction** — the harness first used the week's first kickoff;
   measured against matchup rosters, a move processed before the week's LAST kickoff lands on
   that week's roster.  Reconstruction / attribution use the last kickoff; the DECISION
   cutoff is still the first kickoff.
3. **Dynasty value lookup** is instant-strict on the observation instant but passes no
   `knowledge_cutoff`: a locally rebuilt ledger records every archive row at rebuild time,
   which would hide all of them.  The archive's own timestamp is the point-in-time proof.
4. **Same-week re-add** — a rule may not re-add a defender it released the same week (or
   release one it added that week); such pairs net to a different single swap.
5. **Added, not preregistered:** baseline 1b (hold that also restores the offense released
   in defender-involving streaming transactions) and the paired actual − rule comparisons.
   Both are labelled exploratory.

## 8. Reproduce

```bash
source /home/user/.venv312/bin/activate   # Python 3.12
python scripts/build_temporal_ledger.py --ledger data/research/idp_streaming/temporal_ledger.sqlite --skip-migrations
python -m src.waivers.streaming_backtest --manager "<display name>"
```

Raw Sleeper responses are cached (gzip) under the gitignored `data/research/idp_streaming/raw/`;
named per-move detail goes to the gitignored `data/research/idp_streaming/private_detail.json`.
