# Scoring Config Schema

> **⚠ STALE — March 2026 snapshot.**  This doc describes the local
> per-league `ScoringConfig` dataclass + scoring-adjustment logic
> that was refactored away when the unified blend in
> `_compute_unified_rankings` became the single math path.  Kept
> for historical context.  For the current scoring-profile-driven
> approach (one ranking pipeline per scoring profile, league-scoped
> overlays for rosters/trades), see `CLAUDE.md` → "Rankings vs.
> league context — the core split".

`ScoringConfig` fields:
- `scoring_version`
- `league_id`
- `season`
- `roster_positions`
- `scoring_map`
- `metadata`

`ScoringRule` (delta map) fields:
- `key`
- `category`
- `baseline_value`
- `league_value`
- `delta`
- `relevant_buckets`
- `rule_type` (`linear` | `threshold` | `event`)

`PlayerScoringAdjustment` fields:
- `baseline_scoring_version`
- `league_scoring_version`
- `league_id`
- `baseline_points_per_game`
- `league_points_per_game`
- `raw_scoring_ratio`
- `shrunk_scoring_ratio`
- `final_scoring_multiplier`
- `final_scoring_delta_points`
- `final_scoring_delta_value`
- `position_bucket`
- `archetype`
- `confidence`
- `sample_size_score`
- `projection_weight`
- `data_quality_flag`
- `scoring_tags`
- `source`
- `rule_contributions`

