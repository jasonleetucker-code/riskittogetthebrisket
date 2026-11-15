# Team semantics: one concept, one owner (2026-11-08)

Owner master directive 2026-11-08 section 20, Priority 15. Phase 1: census, canonical schema, guard tests.
This record carries no product authority; it names what each existing surface measures.

## 1. Census (backend)

| Surface | Concept it actually measures | Inputs | Consumers | Names its concept? |
|---|---|---|---|---|
| `roster_intel/window.py::competitive_posture` | **Competitive posture** PUSH/HOLD/RETOOL/REBUILD (CANONICAL) | competitive window: title/playoff-odds percentile (else lineup-score rank), lineup-entrant age trajectory, season timing | `/api/gameplan`, trade Analyze (`strategicPosture`), simulator, finder pick packages, waivers | yes |
| `ros/direction.py::classify_team` + `trade_deadline.py` | **Deadline buy/sell stance** (7 labels) | playoff odds, title odds, vet count (strength percentile only in summary text) | `rosTradeDeadline` section (a PRIVATE_INTELLIGENCE_SECTIONS member, `public_contract.py`), frontend deadline views | now: section `concept`, module `CONCEPT` |
| `ros/championship.py::_contender_tier` | **Title-odds presentation tier** (Favorite ... Rebuilder / Seller) | title odds, playoff odds | public championship section | label is presentation only |
| `bdvm/roster.py::_directions_relative` | **Fundamental horizon mix** contend/retool/rebuild (now vs future asset capital, league-median relative) | BDVM contender vs rebuilder capital ratio | `/api/bdvm/roster`, /bdvm | now: `meta.directionConcept` |
| `roster_intel/strength.py` | Starting-lineup + best-ball strength by position group | canonical lineup assignment | gameplan | yes |
| `ros/team_strength.py`, `ros/power_v2.py` | ROS strength / power rank | projections, results | power rankings, deadline strength percentile | yes |
| `api/terminal.py` `teamAggregates.totalValue`, `portfolio.totalValue` | **Priced-player value only** (picks excluded) | board `rankDerivedValue` of rostered players | /terminal, portfolio summary | now: `valueScope: players_only` + `equity` block |
| `intel/manager_trade_intel.py::draft_capital_totals` | Draft capital held (priced / unpriced reported) | owned picks | manager intel | yes (unknown reported) |
| `roster_intel/age_portfolio.py` | Age portfolio | ages x values | gameplan | yes |

## 2. Pinned 12-team comparison (`tests/roster_intel/team_semantics_fixture.py`)

| Team | Posture (canonical) | Deadline stance | Contender tier | BDVM horizon | All agree |
|---|---|---|---|---|---|
| t01 | PUSH | Strong Buyer | Favorite | contend | yes |
| t02 | PUSH | Strong Buyer | Serious Contender | retool | no |
| t03 | PUSH | Buyer | Dangerous Playoff Team | contend | yes |
| t04 | PUSH | Buyer | Dangerous Playoff Team | rebuild | no |
| t05 | PUSH | Selective Buyer | Dangerous Playoff Team | retool | no |
| t06 | PUSH | Selective Buyer | Dangerous Playoff Team | contend | yes |
| t07 | RETOOL | Hold / Evaluate | Fringe Playoff Team | rebuild | no |
| t08 | HOLD | Selective Seller | Fringe Playoff Team | retool | no |
| t09 | RETOOL | Seller | Long Shot | rebuild | no |
| t10 | REBUILD | Seller | Long Shot | contend | no |
| t11 | RETOOL | Seller | Rebuilder / Seller | rebuild | no |
| t12 | REBUILD | Seller | Rebuilder / Seller | retool | no |

3 of 12 agree (9 disagree, matching the audit). **Why:** the three odds-based classifiers
never take opposite poles (guard test); their differences are vocabulary and
thresholds (HOLD / RETOOL vs "Seller" is a stance gradation, not a contradiction).
Nearly all remaining disagreement is the BDVM column, which measures a different
concept (horizon of asset capital, e.g. t10: an old roster is "contend" by capital
while odds say REBUILD; t04: young capital, strong odds). The defect was that it
reused the posture vocabulary without naming its concept; it is now labelled.
The deadline stance ignores strength except in its summary text (known limit, not changed).

## 3. Canonical schema

| Concept | ONE canonical owner | Unknown handling | Picks |
|---|---|---|---|
| Current starting-lineup strength | `src/roster_intel/strength.py` over `src/ros/lineup.py` | unpriced players excluded and listed, never 0 | excluded |
| Best-ball depth | `src/roster_intel/best_ball_utility.py` | same | excluded |
| ROS strength | `src/ros/team_strength.py` (power: `power_v2.py`) | no projection = unknown | excluded |
| Dynasty player equity | board `rankDerivedValue` summed by `team_equity.decompose_team_equity` (`playerValue`) | unpriced players excluded | excluded |
| Draft capital | `src/api/pick_value_resolution.py` via `team_equity` (`pickValue`) | unobserved ownership = `None`; unpriced pick = `partial_unpriced`, counted, never 0 | included here only |
| Total asset equity | `src/roster_intel/team_equity.py::totalAssetValue` = player + pick | `None` unless picks observed AND all priced; `totalAssetValueLowerBound` labelled | included |
| Competitive posture | `src/roster_intel/window.py::competitive_posture` | no evidence = HOLD | `own_first_round_pick_held` component only |
| Replacement-level advantage | `src/draft/displacement.py`, `src/league_intel/replacement.py` | per owner | n/a |
| Team needs | `src/roster_intel/weakness.py` | per owner | n/a |
| Acquisition fit | `src/roster_intel/partner.py`, `packages.py` | per owner | n/a |
| Deadline buy/sell stance | `src/ros/direction.py` (NOT posture) | unmeasurable team = "Insufficient evidence" | none |
| Fundamental horizon mix | `src/bdvm/roster.py` (NOT posture) | unpriced assets listed | `pickCount` None when unobserved |

Rule: a surface using another concept's vocabulary must carry a `concept` /
`valueScope` stamp; a field named "total" must be player + pick or state its scope.

## 4. Changes in this phase (all additive; no canonical value changes)

- `team_equity.decompose_team_equity` (new, arithmetic only; reuses the pick resolver).
- `/api/terminal`: `teamAggregates.valueScope`, `teamAggregates.equity`, `portfolio.valueScope`, `portfolio.equity`. `totalValue` is byte-identical.
- `/api/bdvm/roster` `meta.directionConcept`; `rosTradeDeadline.concept` (private intelligence section).

## 5. Remaining consolidation plan

1. Frontend migrates the terminal "Total" to `equity.totalAssetValue` / shows scope (handoff entry).
2. Collapse the deadline stance onto posture inputs (needs owner decision on the user-facing vocabulary).
3. Inventory `src/trade/finder.py`, `team_impact.py`, `trade_decision.py` consumers of the posture labels (read posture, not re-derive).
4. Add a `concept` stamp to `/api/gameplan` windows and `/api/ros/team-strength` rows.
