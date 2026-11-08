# 10. Research backlog and implementation-ready handoff

**Status:** research record, 2026-11-08. Tags: **research** can run offline without new authority, new served code or spending. **authorization-pending** needs an owner decision, a credential, spending, or a change outside `docs/`. Ranking is by expected decision value per unit of cost `[I]`. Several research items also need a script in a future worktree. Writing that script is a separate approved unit, and this document does not authorize it.

## 1. Ranked backlog

| rank | id | item | tag | depends on | effort | acceptance |
|---|---|---|---|---|---|---|
| 1 | A01 | Licensing decision register: PFR-derived nflverse, ESPN and Clay, Sleeper commercial status, FTN share-alike | authorization-pending | none | Owner plus counsel | One recorded decision per dataset in `02_`, by intended use |
| 2 | R01 | Baseline ladder B0-B3 by position on host-scored history | research | none | S | Published table with intervals; B3 defined |
| 3 | R02 | Power analysis and minimum detectable effect by position | research | R01 | S | MDE table; each planned study labelled confirmatory or screen |
| 4 | R03 | Timing audit of nflverse `spread_line` and `total_line` | research | none | S | Opening vs closing determined, or the data labelled unverified |
| 5 | R04 | H-VOL1: lines vs trailing team rates for plays, attempts, points | research | R03 | S | Preregistered comparison |
| 6 | R05 | Estimate `kappa` and `n0` per position and stat family | research | R01 | S | Fitted values compared with BDVM `n_prior_*`, analysis only |
| 7 | R06 | Dispersion from the pregame archive (D1, D2 vs D0) | research | DS-C weeks | S | Overlaps AM-PROJECTIONS-01; do not duplicate |
| 8 | A02 | Activate a second independent weekly family, recording rights first | authorization-pending | A01, credential | S once authorized | Adapter ON, ancestry independent, archive growing |
| 9 | R07 | Offense bottom-up hierarchical GLM (volume x share x efficiency) | research | R01, R04 | M | Beats B3 at PG3 on validation seasons, or is retired |
| 10 | R08 | Availability two-stage model | research | R01 | M | Brier vs status-only |
| 11 | R09 | Gap-fill evaluation for reception bands and first downs | research | R01 | S | Category error vs realized by position |
| 12 | R10 | ROS: leave-one-source-out and removal of dynasty proxies | research | DS-E | S | ROS-horizon prereg separate from frozen H1 |
| 13 | R11 | Exceedance vs mean ranking in `streaming_backtest` | research | R06 | M | Decision utility with intervals |
| 14 | A03 | Odds capture or The Odds API key | authorization-pending | A01, spending | S | PIT game and prop archive begins |
| 15 | R12 | Team-points study v2 (owned by that study) | research | Its own prereg | S | Prereg before the clean weeks |
| 16 | R13 | Residual correlation factor estimation | research | R06 | S | Energy score vs independence |
| 17 | R14 | Label sensitivity: nflverse path vs host for training labels | research | none | S | Ranking of which seasons or positions change |
| 18 | R15 | Fitted hazard vs `src/bdvm/survival.py` schedule | research | R01 | M | Brier on held-out cohorts |
| 19 | R16 | Aging spline with survivorship correction | research | R01 | M | Compared with delta method |
| 20 | R17 | Card-aware expected stats vs `ffopportunity` | research | R01 | M | Next-week MAE ablation |
| 21 | A04 | Rookie model with CFBD (key needed) | authorization-pending | A01 | L | Beats slot prior on pooled classes |
| 22 | A05 | Register `brisketInternal` family policy and feature dictionary entries | authorization-pending | R07 passes | S | Family policy in `promotion_gates`; dictionary lock |
| 23 | A06 | Shadow weekly forecast job with frozen receipts | authorization-pending | A05 | M | Forecasts frozen before kickoff for a full season |
| 24 | A07 | Attribution audit and CC-BY compliance | authorization-pending | A01 | S | Every data-using surface carries required credit |
| 25 | A08 | Exceedance output served in streaming behind a default-OFF flag | authorization-pending | R11, PG gates | M | Owner approval |
| 26 | R18 | IDP model extensions, after the frozen study reports | research | Frozen study | M | Separate preregistration, separate weeks |
| 27 | R19 | One-year production forecast vs market for dynasty | research | Multi-season | L | Incremental lift over market |

## 2. Implementation-ready handoff

### What is known

| fact | source |
|---|---|
| Exact league scoring exists and matches the host on 3,710 of 3,710 player-weeks (one league, six weeks, in-sample) | `SCORING_PARITY_TAXONOMY_2026-11-08.md` |
| The exact lineup solver reproduces Sleeper's best-ball awards | `CLAUDE.md`, `docs/lineup/C2_U1_CANONICAL_LINEUP.md` |
| The served team distribution is badly scaled and over-spread | `TEAM_POINTS_CALIBRATION_RESULTS_2026-11-08.md` |
| Simple forecasts outperform the served sim at team level on CRPS and MAE; no challenger passed all gates | Same |
| Proxy fundamentals order players worse than the market | `docs/valuation/idp_accuracy/G_ACCURACY.md` |
| Shrinkage carries the IDP gain over naive means | `IDP_OPPORTUNITY_CHALLENGERS_RESULTS_2026-11-01.md` |
| Weekly external forecasts are one family | `03_` F1 |
| Point-in-time vendor history starts at 2026 week 8 | `03_` F8 |
| Clean, inexpensive data routes exist | `02_` finding 7 |

### What is hypothesis

| hypothesis | source |
|---|---|
| A specific hybrid beats independent or consensus alone | `01_` §4 |
| Team totals are the largest cheap unused signal | `05_` §1 |
| Offense efficiency terms add little after shrinkage | `06_` §2 |
| An in-house IDP model adds decision value through coverage | `01_` §3 |
| Calibrated distributions improve decisions more than better means | `01_` §4 |
| Fitted hazards beat priors | `05_` §5 |

### What data is missing

| gap | effect | path |
|---|---|---|
| Second independent weekly family | No true consensus test | A02 |
| Multi-season archived vendor forecasts | No historical external comparison | Accumulate; DS-I for ranks |
| PIT game lines and props | Market features unproven | R03, A03 |
| As-known injuries before the log began | Availability cohort caveat | Forward capture |
| Routes in-season; CB targets; pass-rush snaps | Model simplifications | Offseason training; paid data only if a gap is shown |
| Completed-season playoff outcomes | No title-odds calibration until January 2027 | Calendar |

### Next experiments (in order)

1. A01 decisions, so later work does not train on barred inputs.
2. R01, R02: build the ladder and power table.
3. R03, R04: establish whether lines are usable and how much they add.
4. R05, R06, R09: shrinkage parameters, dispersion, gap fill.
5. R07: first offense challenger, only if R01-R04 leave room.
6. R11: decision replay.

### What counts as approval to build

All of the following must exist. A green test run does not count, and neither does this document.

| requirement | where recorded |
|---|---|
| Unit named as authorized | `docs/EXECUTION_PLAN.md` |
| Owner intake item | `docs/OWNER_REQUESTED_TODO.md` |
| Rights decision for every input | `config/projections/source_capability_census.json` and A01 |
| Preregistration committed before outcomes | `docs/research/forecasting/` |
| Work claim | `docs/WORK_CLAIMS.md` |
| Default-OFF flag and rollback named | `src/api/feature_flags.py` |
| Family policy before any promotion | `src/model_registry/promotion_gates.py` |
| Owner sign-off to promote | Model registry record |

Items that would still be out of scope: DFS, League Tycoon, Sleeper writes, frontend work under the current backend directive, #1938, any change to `rankDerivedValue`, and any modification of the frozen IDP or ROS H1 preregistrations.

## 3. UNRESOLVED

- Whether Chase Upside is commercial for licensing purposes.
- Legal effect of upstream terms on CC-BY redistributed data. Needs counsel.
- Actual performance of any proposed model. None was fitted.
- Box-local state: archive contents, flag overrides, calibrated points model.
- Source pages listed as unverifiable in `02_` §D.
- The intake ledger (`docs/OWNER_REQUESTED_TODO.md`) and `docs/WORK_CLAIMS.md` were not edited, because this unit was limited to `docs/research/forecasting/`. The coordinator should record intake and claim state.
