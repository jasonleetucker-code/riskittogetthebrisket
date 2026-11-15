# Football forecasting research blueprint (2026-11-08)

**Status: research only.** No model was trained, nothing under `src/`, `scripts/`, `config/` or `frontend/` changed, nothing was purchased or scraped. Authority to build remains with `docs/EXECUTION_PLAN.md`. Paused products stay paused.

**Question.** Do independent projections, external consensus, or a hybrid give the best predictions and the best fantasy decisions?

**Answer so far.** A specific hybrid is the best expected design, and it is a hypothesis that this repository cannot yet test. Consensus for offense means. In-house for distributions, IDP coverage, league-card categories and availability. Market value stays a separate named concept. An independent model alone is unlikely to win offense means. External consensus alone leaves IDP, distributions and league-specific categories unaddressed. Today's "consensus" is one weekly model family, so the true test needs a second independent family with archived history.

## Files

| file | content |
|---|---|
| `01_METHODOLOGY_SURVEY.md` | Providers, open-source and statistical methods, what the evidence supports, the answer by target |
| `02_DATA_SOURCE_LICENSING_MATRIX.md` | Per-dataset fields, access, rights, ML permission, findings, URLs |
| `03_PROJECTION_DEPENDENCY_AUDIT.md` | Where external projections, ranks, stats, markets and derived forecasts enter the platform |
| `04_PROPOSED_ARCHITECTURE.md` | Six layers mapped to existing owners; point-in-time guarantees |
| `05_CANDIDATE_FORMULA_LIBRARY.md` | Equations by position and horizon, all labelled hypotheses |
| `06_FEATURE_INVENTORY.md` | Opportunity, efficiency, team, opponent, career features, persistence and leakage |
| `07_EVALUATION_DESIGN.md` | Datasets, baselines, metrics, holdouts, promotion criteria, decision backtests |
| `08_REGRESSION_GOVERNANCE_FEEDBACK.md` | Tests, versioning, weekly cycle, triggers, rollback |
| `09_FEATURE_INTEGRATION_MAP.md` | The 20 product surfaces with cost and feasibility |
| `10_RESEARCH_BACKLOG_AND_HANDOFF.md` | 27 ranked items, known and unknown, approval criteria |

## Five findings that matter most

| # | finding | where |
|---|---|---|
| 1 | Weekly "consensus" is one family (RotoWire via Sleeper), and the preseason ensemble is effectively one family per side. External consensus cannot be evaluated yet | `03_` F1, F2 |
| 2 | Evidence so far favors simple methods. Shrinkage carries the IDP gain. Simple team forecasts score 29-32 CRPS against the served sim's 69. Proxy fundamentals order players worse than the market | `01_` §3 |
| 3 | Rights problems reach live inputs: PFR-derived nflverse snaps, ESPN feeds and the Clay PDF, plus an open Sleeper commercial-use question. A cheap route exists through nflverse PBP and stats, CFBD, The Odds API and NWS | `02_` §C |
| 4 | No non-paused forecast uses market-implied team totals, though free lines exist in nflverse (timing unverified) and they are the leading feature in the closest published analog | `03_` F6, `05_` §1 |
| 5 | Accuracy and decisions diverge. Lower-error shrinkage compressed top-of-board hits on CB, so streaming needs calibrated exceedance probabilities | `01_` §4, `07_` §8 |

Scope limits and unverified items are listed in `10_RESEARCH_BACKLOG_AND_HANDOFF.md` §3 and `02_DATA_SOURCE_LICENSING_MATRIX.md` §D.

Agent-OS-Receipt: aa55ed12383caa257a25d28baa6612bc9577347d
