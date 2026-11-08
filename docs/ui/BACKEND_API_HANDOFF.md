# Backend → frontend API handoff

**Owner:** backend campaign (owner master implementation directive 2026-11-08, §2 and §31). This records ONLY the
backend changes the separate frontend developer needs to know about. It is not a frontend roadmap: frontend work is
theirs, and no backend change here requires editing a frontend file. Every entry is additive and versioned unless it
says otherwise.

| Endpoint | Change | Deployed | Frontend action |
|---|---|---|---|
| `GET /api/public/league/playoffOdds` | Added top-level `divisionOdds` (see below). Owner rows gain `division`, `divisionName` and `divisionChampionProbability` when division odds are available. `playoffStructure` gains `divisionRule` and `leagueRules`. | yes (#2149, production `f8da14ef8`) | Optional. The Power tab already renders a division table (added before the frontend exclusion, #2149). The redesign may restyle or move it, and should keep division-title odds and playoff odds as separate numbers. |
| `GET /api/public/league/rosPlayoffOdds`, `rosChampionship` (canonical forecast) | Rows gain `division`, `divisionName`, `divisionChampionOdds` and `divisionChampionOddsCi` when available. For a league with divisions ON and no recorded rule: `playoffOdds: []` plus `unsimulable.scope: "qualification"`, and a new `regularSeasonOdds` list (`ownerId`, `displayName`, `expectedWins`, `draftSlotDistribution`, `finalWins`, `finalPointsFor`, division fields). | yes (#2149) | Required only if the redesign shows draft slots or division titles for such a league. Read `regularSeasonOdds` when `unsimulable.scope === "qualification"`. No live league is in that state today. |

## `divisionOdds` contract (v1, 2026-11-08)
```json
{
  "state": "available | unavailable | not_applicable",
  "reason": "" ,
  "count": 3,
  "names": {"1": "The Pit", "2": "Sweet Pepper Bacon", "3": "Barbacoa"},
  "championRule": {
    "rule": "best_overall_record_in_division",
    "tiebreakers": ["points_for"],
    "recordBasis": "host_standings_record",
    "affectsPlayoffs": false
  }
}
```

**Unavailable reasons:**
- `division_champion_rule_unrecorded`
- `division_count_conflicts_with_host_setting`
- `roster_division_missing_or_out_of_range`
- `division_has_no_teams`
- `roster_owner_unresolved`
- `division_teams_differ_from_simulated_teams`

`not_applicable` means `no_divisions`.

**Missing is not 0:** when `state` is not `available`, rows carry no division fields. Render nothing, or the reason; never 0%.

**Display semantics:** these are simulated estimates. A simulated 0 or 1 is not a clinch until the season is final, so `frontend/lib/odds-disclosure.js::fmtSimulatedShare` renders "<1%" / ">99%".

**Suggested frontend acceptance tests:**
- a division champion that misses the playoffs shows both numbers;
- `unavailable` renders no 0%;
- `regularSeasonOdds` feeds draft-slot views when qualifying is withheld.

Synthetic fixtures: `tests/public_league/test_playoff_odds_divisions.py`, `tests/ros/test_league_division_rules.py`.

## Team equity and direction concept stamps (2026-11-08)

Backend additions (no values changed); frontend migration is not done.

- `/api/terminal` `teamAggregates` and `portfolio` now carry `valueScope: "players_only"` and `equity`: `{playerValue, pickValue, pricedPickValue, pickCount, pricedPickCount, unpricedPickCount, pickValueState (complete|partial_unpriced|unavailable), pickValueReason, totalAssetValue, totalAssetValueLowerBound}`. `totalValue` is unchanged and still excludes picks.
- **Needed:** any "Total value / portfolio total" display should show `equity.totalAssetValue`, or label `totalValue` as "Players". When `totalAssetValue` is `null`, show `totalAssetValueLowerBound` as "at least" with the reason; never render a missing pick value as 0.
- `/api/bdvm/roster` `meta.directionConcept = "fundamental_horizon_mix"` and `rosTradeDeadline.concept = "deadline_buy_sell_stance"` are NOT the canonical posture (PUSH/HOLD/RETOOL/REBUILD, `/api/gameplan`). Do not present them under the same heading.
- Schema: `docs/roster_intel/TEAM_SEMANTICS_2026-11-08.md`.
