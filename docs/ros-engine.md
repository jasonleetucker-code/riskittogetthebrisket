# Rest-of-Season (ROS) Rankings Engine

## What it does

Surfaces a separate **short-term contender layer** for power rankings,
playoff/championship odds, buyer/seller recommendations, and contextual
UI labels.  It answers questions like:

- Who is strongest right now?
- Who has the best playoff odds?
- Who should buy / who should sell at the deadline?
- Which players are short-term contender pieces vs best-ball depth?

## What it explicitly does NOT do

- Re-rank dynasty players
- Change dynasty values
- Change trade-calculator math
- Change market values
- Change rookie pick values

These are dynasty concerns and live in a completely separate codepath
(`src/api/data_contract.py` + `frontend/lib/trade-logic.js`).  The ROS
engine never mutates either.  An automated isolation test
(`tests/ros/test_isolation.py`) snapshots the dynasty contract before
and after importing every `src/ros/*` module and asserts byte-identical
output — if the boundary is ever crossed, that test fails loudly.

## High-level flow

```
   ┌────────────────────┐                              ┌─────────────────────┐
   │  scheduled-refresh │ ── every 2h ──>│  Dynasty scrapers   │
   │  GitHub Actions    │                              │  (existing)          │
   └────────────────────┘                              └─────────────────────┘
                │                                                          │
                v                                                          │
        ┌──────────────────┐                                            │
        │ src/ros/scrape   │                                            │
        │ orchestrator     │                                            │
        └──────────────────┘                                            │
                │                                                          │
        ┌────────┼────────┐                                              │
        │       │       │                                                  │
        v       v       v                                                  │
    fantasypros DS-ROS  …  (one adapter per source)                  │
        │       │       │                                                  │
        └───┬───┴───┴───┘                                              │
            v                                                              │
    data/ros/sources/<key>.csv                                       │
    data/ros/runs/<key>__<ts>.json                                  │
            │                                                              │
            v                                                              │
    aggregate.py  (rank → score, weighted blend, confidence)        │
            │                                                              │
            v                                                              │
    data/ros/aggregate/latest.json                                    │
            │                                                              │
            v                                                              │
    team_strength.py + lineup.py (best lineup, depth, coverage)     │
            │                                                              │
            v                                                              │
    data/ros/team_strength/latest.json                                │
            │                                                              │
            v                                                              │
    /api/ros/team-strength  ───>  /league → ROS Strength tab        │
                                                                          │
    NEVER touches:  CSVs/site_raw/* ─────────────────────────────────────┘
                    src/api/data_contract.py
                    frontend/lib/trade-logic.js
```

## Source list (PR 1)

| Source                              | Type           | Weight | Auth |
|-------------------------------------|----------------|--------|------|
| FantasyPros Dynasty SF (ROS proxy)  | dynasty_proxy  | 0.85   | none |
| Draft Sharks ROS Superflex          | ros            | 1.25   | reads existing dynasty CSV (already authenticated by `scripts/fetch_draftsharks.py`) |

PR 2-5 add: PFN/PFSN ROS SF, CBS ROS, FantasyPros IDP, Draft Sharks IDP
(separate ROS scrape), RotoBaller, Fantasy Nerds, SportsKeeda, FFC 2QB
ADP, ESPN/Mike Clay, IDP Guru, PFF IDP, Fantasy In Frames IDP,
Footballguys IDP.

## Source weight formula

Per the spec:

```
effective_source_weight =
    base_source_weight
    * format_match_multiplier      (1.15 SF+TEP / 1.10 SF / 1.05 IDP / 0.95 / 0.85 dynasty proxy)
    * freshness_multiplier         (1.00 today / 0.90 1d / 0.75 2-3d / 0.50 4-7d / 0.25 older)
    * completeness_multiplier      (1.00 ≥200 players / 0.85 partial / 0.70 sparse)
    * availability_multiplier      (1.00 ok / 0.50 partial or stale-cache / 0.00 failed-no-cache)
```

Implementation: `src/ros/parse.py::effective_source_weight`.

## Rank-to-value conversion

```
rank_score = 100 * ((ln(N + 1) - ln(r)) / ln(N + 1))
```

Top-heavy logarithmic curve.  `r=1` → ~99.  `r=N` → ~0.2 (asymptotic).

Implementation: `src/ros/parse.py::rank_to_score`.

## Aggregated player value

```
ros_value     = weighted_average(per-source rank_scores)
confidence    = 0.45 * source_count_factor (saturates at 4 sources)
                + 0.35 * agreement_factor    (1 - stddev/30)
                + 0.20 * freshness_factor    (% non-stale contributors)
ros_rank_overall, ros_rank_position, tier, sourceCount, etc.
```

Implementation: `src/ros/aggregate.py::aggregate`.

## Team strength composite

```
team_ros_strength
    = 0.72 * starting_lineup_strength
    + 0.18 * best_ball_depth_strength
    + 0.05 * positional_coverage_score
    + 0.05 * health_availability_score
```

Implementation: `src/ros/team_strength.py::compute_team_strength` +
`src/ros/lineup.py::optimize_lineup`.

The lineup optimizer is **best-ball-aware** (depth meaningfully
contributes via decay-weighted bench credit) but starting strength
still dominates per the spec.

## Data freshness rules

- Each source declares `stale_after_hours` in the registry.
- A source older than that threshold has its `availability_multiplier`
  reduced from 1.0 → 0.5 (when a previous valid CSV exists).
- A source with no valid cache and a failed scrape has multiplier 0.0
  (excluded from blend).
- The previous CSV is **never deleted** when today's scrape fails —
  the orchestrator preserves it on disk so the aggregate continues
  with last-known-good values.

`tests/ros/test_scrape_failure_resilience.py` pins this guarantee.

## How to add a new source

1. Implement `src/ros/sources/<key>.py` exposing
   `scrape(*, src_meta) -> ScrapeResult`.
2. Add an entry to `ROS_SOURCES` in `src/ros/sources/__init__.py`.
3. Mirror the entry in `frontend/lib/ros-sources.js`.
4. Add a fixture-based parser test under
   `tests/adapters/test_<key>_scraper.py`.
5. Run `pytest tests/ros/test_sources_registry_parity.py` to confirm
   the Python ↔ JS registries stay in lockstep.

## How to disable a source

Two paths:

- **Per-deploy**: flip `enabled: False` in the registry entry.
- **Per-user**: set `settings.rosSourceOverrides[<key>].enabled = false`
  on `/settings`.  The orchestrator and aggregator both consult the
  override map.

## How to manually refresh

- **Local dev**: `python -m src.ros.scrape`
- **Production admin**: `POST /api/ros/refresh` (admin-session-gated)
- **CI**: every 2h via `.github/workflows/scheduled-refresh.yml`

## How to debug failed scrapes

1. `data/ros/runs/index.json` — most-recent run pointer per source.
2. `data/ros/runs/<key>__<ts>.json` — full per-run metadata: status,
   error, scrape timing, player count.
3. `/api/ros/status` — same data over HTTP.
4. `/league` → "ROS Strength" tab → "Unmapped (no ROS read)" expandable
   for player-mapping failures.

## Storage layout

```
data/ros/
  sources/<key>.csv                    # latest scrape per source
  runs/<key>__<iso>.json               # per-run metadata
  runs/index.json                      # most-recent-run pointer
  aggregate/latest.json                # aggregated player values
  aggregate/history/<iso>.json         # rolling 30-day archive
  team_strength/latest.json            # per-team snapshot
  sims/playoff_<iso>.json              # PR3 Monte Carlo outputs
  mapping_overrides.json               # manual name overrides (committed)
```

Everything except `mapping_overrides.json` is gitignored — the file
tree is committed via `.gitkeep` so a fresh checkout has the layout
in place.

## Confirmation: dynasty/trade values are isolated

- `tests/ros/test_isolation.py` — automated guarantee that the
  `_RANKING_SOURCES`, `_SOURCE_CSV_PATHS`, `_VALUE_BASED_SOURCES`, and
  `_SOURCE_MAX_AGE_HOURS` constants in `src/api/data_contract.py` are
  byte-identical before vs after importing every `src/ros/*` module.
- `tests/ros/test_isolation.py::TestTradeLogicNonRegression` — pins
  the KTC native VA fixture to ≤50 RMS so frontend trade-calc math
  can't drift unnoticed.
- ROS adapters write only to `data/ros/*` — never `CSVs/site_raw/*`,
  `data/exports/*`, or any path the dynasty pipeline reads.
- The new `LeagueConfig.best_ball` field defaults to `False` — existing
  registry JSON files keep working with no edits.

If any of these guarantees is broken in a future change, fix the
change rather than relax the test.
