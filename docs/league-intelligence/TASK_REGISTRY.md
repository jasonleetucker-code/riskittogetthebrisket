# League Intelligence — Task Registry

Update this file when claiming/finishing tasks. Owned paths are exclusive
while a task is in_progress.

| ID | Task | Agent | Owned paths | Depends on | Status | Updated |
|---|---|---|---|---|---|---|
| LI-0 | Coordination docs + settings audit vs live API + screenshots | main orchestrator | docs/league-intelligence/, config/league_intel/sleeper_league_snapshot_* | — | done | 2026-07-26 |
| LI-1 | Canonical config module + registry rosterSettings fix + consumer tests | league-intel agent | src/league_intel/config.py, config/league_intel/, config/leagues/registry.json (coordinated), tests/league_intel/ | LI-0 | done | 2026-07-26 |
| LI-2 | Deterministic scorer + golden validation vs Sleeper-awarded scores | league-intel agent | src/league_intel/scorer.py, tests/league_intel/ | LI-1 | done (see SCORING_VALIDATION.md) | 2026-07-26 |
| LI-3 | Best-ball optimizer audit/exactness (src/ros/lineup.py) + historical starter reconstruction | league-intel agent (next) | src/ros/lineup.py (coordinated), tests/league_intel/ | LI-1, LI-2 | pending | — |
| LI-4 | Value schema + getActiveValue selector + no-op league value | TBD | src/league_intel/values.py, server.py (additive endpoint) | LI-1 | pending | — |
| LI-5 | Replacement/scarcity engine | TBD | src/league_intel/replacement.py | LI-2, LI-3 | pending | — |
| LI-6 | Projection re-scoring through exact scorer + source audit (§7) | TBD | src/league_intel/projections.py, docs DATA_SOURCES.md | LI-2 | pending | — |
| LI-7 | League-adjusted correction + guardrails + TE residual + explanations | TBD | src/league_intel/adjustment.py | LI-4..LI-6 | pending | — |
| LI-8 | Best-ball simulation + League Twin extension + trade deltas | TBD | src/ros/playoff_sim.py (coordinated), src/league_intel/sim.py | LI-2, LI-3 | pending | — |
| LI-9 | UI: global mode toggle + per-page adoption | TBD (after redesign R2 merge) | frontend (via R1 shell) | LI-4, R2 merge | blocked (R2 in flight) | — |

## Other active agents (do not collide)

| Agent | Territory | Status |
|---|---|---|
| Redesign R2 | frontend/app/rankings/, PlayerPopup.jsx, ds/ consumers | building |
| E2E reconcile | tests/e2e/ | building |
| Reviewer (fresh-eyes) | read-only, PR comments | per-PR |
