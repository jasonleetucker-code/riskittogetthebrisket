# CW-52 dead-code census — 2026-11-07

Owner directive 2026-11-07 §5: remove only proven unused or safely superseded code; keep
intentionally disabled or planned features. Report-first. Base: `origin/main` 6f3b0e3b99.

## Method

* **Python.** `vulture 2.16` at `--min-confidence 80` reports only unused variables and
  redundant conditions (11 lines; none are dead functions, left alone). Function/class
  census therefore used a purpose-built AST pass: every undecorated module-level
  `def`/`class` in `src/`, `server.py`, `scripts/`, `Dynasty Scraper.py` whose identifier
  occurs exactly once (its own definition) across every tracked text file outside
  `data/`, `exports/`, `CSVs/` (code, tests, workflows, docs, JSON, string/getattr/importlib
  references included). 46 hits; each then re-grepped across the whole tree including `data/`-free JSON and docs.
* **Frontend.** Exported `function/const/class` in `frontend/lib` + `frontend/components`
  whose name occurs once repo-wide (tests included): 21 hits. File-level orphans: none
  (only `components/ds/index.js` and `components/ui/index.js`, directory barrels, not dead).
  `page.jsx` / `route.js` / `layout.jsx` treated as entry points.
* Removal bar: PROVEN_UNUSED (zero references anywhere, private `_name`, not an entry
  point, not flagged, not DFS / League Tycoon / model-registry / BDVM reference), tests
  green. Public (non-underscore) names are left as candidates: an external caller
  (ops shell, notebook) cannot be excluded from the repo alone.

## Counts

| classification | count |
|---|---|
| PROVEN_UNUSED, removed | 11 |
| PROVEN_UNUSED, deferred (public name / touches server.py / ops hook) | 25 |
| SUPERSEDED (explicit retirement note) removed | 1 (included in the 11: `_provider_status_orig`) |
| PLANNED / UNSURE | 10 (chat.py x5, `extract_tables`, `normalize_crawler_state`, `build_franchise_detail`, `capture_value_source`, `serialise_capture`) |
| INTENTIONALLY_DISABLED | 0 found |
| Frontend unreferenced exports | 21 (all deferred) |

Total candidates: 46 Python + 21 frontend = 67.

## Removed (11, all private or zero-reference, no test references)

| file:symbol | evidence |
|---|---|
| `src/nfl_data/ingest.py:_provider_status_orig` | docstring: "[deprecated] ... No callers today"; zero refs (SUPERSEDED) |
| `src/api/data_contract.py:_extract_last_name` | private, zero refs |
| `src/ros/mapping.py:_candidate_pool` | private, zero refs |
| `src/bridges/ladder.py:_ladder_for` | private one-line wrapper of `_ladders_for`, zero refs |
| `src/ros/power_v2.py:_scored_game_count` | private wrapper of `_scored_game_span`, zero refs |
| `src/pool/builder.py:_reconstruct_split_names` | private, zero refs |
| `src/public_league/franchise.py:_roster_count_for` | private, zero refs |
| `src/packages/construction.py:_HasTradeFields` | private Protocol, zero refs |
| `src/bdvm/pool.py:pools_from_callables` | docstring says "in tests"; no test or module references it |
| `scripts/ros_scale_calibration_study.py:_stat_mae` | private, zero refs |
| `scripts/collect_ktc_va.py:_xpath_lit` | private, zero refs |

Unused imports orphaned by the removals were dropped by `ruff --fix` (`Mapping`, `Protocol`,
`SeasonSnapshot`, `Iterable`). No coercion-baseline entries were touched
(`check_decision_coercions.py`: clean).

## Deferred candidates (zero references; reason kept)

Public API surface (could have an out-of-repo caller; propose removal after owner glance):
`src/snapshots/board_store.py:summary_json`, `src/robust_filter_shadow/idp_challengers.py:group_by`,
`src/api/source_history.py:load_all_player_names` (docstring "not currently wired"),
`src/api/rate_limit.py:login_throttle_snapshot` (observability hook),
`src/public_league/metrics.py:matchup_margin`, `src/public_league/sleeper_client.py:reset_session`
(test hook), `src/intel/platform_ledger.py:latest_ingestion_run`,
`src/ros/game_day_live.py:observed_windows`, `background_status`,
`src/ros/sources/__init__.py:ros_source_keys`, `src/ros/idp_opportunity/evaluate.py:subgroup_known`,
`src/consensus_edge/snapshot.py:distinct_dates`, `src/sources/ktc_market.py:market_raw_value_as_of`
(historical as-of replay helper), `src/sources/rehabilitation.py:plan_for`,
`src/trade/market_trade_archive.py:iter_native_ids`, `src/nfl_data/scoring_coverage.py:scored_keys_for`,
`host_recoverable` (docstring names a reporting use), `src/nfl_data/injury_return_evidence.py:players_needing`,
`src/sharp/service.py:market_audit_payload`, `src/sharp/league_format_capture.py:record_captures`,
`src/adapters/sleeper_trending_history.py:compute_velocity`,
`scripts/idp_accuracy/d_report.py:stat_mean`, `d_data.py:eligibility_tuple`,
`scripts/fetch_yahoo_boone.py:_fetch_one_position` (source-fetch script; ingest path needs owner review).

`server.py:_live_by_name_from_contract` plus its `_LIVE_BY_NAME_CACHE` global: dead, but
server.py is high-risk; remove with its own L2 PR.

UNSURE / PLANNED: `src/api/chat.py` (`build_data_snapshot`, `_get_client`, `reset_client_cache`,
`validate_messages`, `stream_chat_response`: whole chat module appears unrouted; needs an owner
decision on whether chat is planned), `Dynasty Scraper.py:extract_tables` (production scraper,
importlib-loaded), `src/platforms/sleeper.py:normalize_crawler_state` (platform ingest, may be
planned), `src/public_league/franchise.py:build_franchise_detail` (named in the
decision-intelligence audit registry), `src/sources/ktc_value_sources.py:capture_value_source` /
`serialise_capture` (KTC multi-mode capture lane; evidence-gated source work).

Frontend exported but never imported (test or otherwise): `useLeague.invalidateLeaguesCache`,
`useNews.invalidateNewsCache`, `useUserState.invalidateUserState`, `draft-logic.TAG_VALUES`,
`idp-streaming.IDP_STREAMING_FLAG`, `manager-saved.deleteUrl`, `perfect-draft.PRICE_BASES`,
`public-league-data.fetchPublicMatchup/fetchPublicPlayer/fetchPublicPlayersIndex`,
`ros-data.fetchRosStatus/fetchRosPlayerValues/useRosTeamStrength`,
`ros-sources.rosSourceKeys/getRosSource`, `roster-construction.ROSTER_CONSTRUCTION_FLAG/_SCHEMA`,
`source-voting-status.VOTING_STATUS`, `trade-war-room.strategySummary/RECOMMENDATION_TONES`,
`waiver-advisor.WAIVER_ADVISOR_FLAG`. Flag constants and exports of feature-flagged modules are
kept by rule; remaining ones deferred so this PR stays Python-only (no vitest run needed).

## Not examined

Class methods, module-level constants, and Python names referenced only from their own
module are not classified dead by this pass (a self-reference counts as use).
