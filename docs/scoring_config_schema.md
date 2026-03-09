# Scoring Config Schema

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

