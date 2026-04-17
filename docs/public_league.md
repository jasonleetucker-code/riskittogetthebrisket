# Public League Experience

A fully-isolated public `/league` page, its backend pipeline, and the
data contract that serves it.  This doc is for the next engineer who
needs to ship, extend, or debug this surface.

## What exists

**Backend** — `src/public_league/`
- `snapshot.py` + `sleeper_client.py` — Sleeper v1 pull, current +
  previous dynasty season (fixed at 2 seasons for now).
- `identity.py` — owner-id-keyed manager registry, team-name aliases,
  `(leagueId, rosterId) -> ownerId` lookup that is season-scoped.
- `metrics.py` — shared helpers (matchup pairing, standings,
  pre-week standings, playoff bracket parsing, chronological walks).
- One module per public section:
  - `history.py`, `rivalries.py`, `awards.py`, `records.py`,
    `franchise.py`, `activity.py`, `draft.py`, `weekly.py`,
    `superlatives.py`, `archives.py`, `overview.py`.
- `public_contract.py` — assembles the full contract, enforces the
  private-field blocklist, versions the payload (`public-league/YYYY-MM-DD.vN`).
- `snapshot_store.py` — persists the snapshot + contract to disk at
  `data/public_league/` so a cold server still serves the page.

**Frontend** — `frontend/app/league/page.jsx`
- Client component.  No `useApp`, no `useDynastyData`, no
  `lib/league-analysis`, no `lib/dynasty-data`.  Only public data
  through `frontend/lib/public-league-data.js → /api/public/league*`.
- 11 tabs: **Home**, History, Rivalries, Awards, Records, Franchises,
  Trades, Draft, Weekly, Superlatives, Archives.
- Cross-links: tab switches trigger navigation from inline "→" buttons
  (e.g., "Full draft center →", "Explore rivalries →").

**Server** — `server.py`
- `GET /api/public/league` — full contract.
- `GET /api/public/league/{section}` — any single section.
- Both set `Cache-Control: public, max-age=60, stale-while-revalidate=300`.
- Both run `assert_public_payload_safe()` before serialization.

## The architectural rules

1. **No private imports.**  `src/public_league/` must not import from
   `src.canonical`, `src.api.data_contract`, `src.trade`, or `src.pool`.
   Enforced by `tests/public_league/test_public_contract.py::ImportSurfaceTests`.

2. **Field-name allowlist.**  Any key matching the private blocklist
   in `public_contract.py::_PRIVATE_FIELD_BLOCKLIST` short-circuits the
   response with a 500.  When you add a field, make sure it doesn't
   collide with that list.

3. **Isolation in the UI.**  `frontend/components/AppShell.jsx` routes
   `/league` through `PublicAppShell` which never calls
   `useDynastyData`.  Do **not** add private imports to `page.jsx` — the
   vitest suite will catch it.

4. **Owner identity is the key.**  Never aggregate by roster_id or
   team name across seasons.  Season-scoped `(leagueId, rosterId) →
   ownerId` is the only safe path.  Orphan-roster handoffs stay split;
   renames merge under one owner with alias history.

## Award engine

`src/public_league/awards.py` is split into:
- Canonical per-season awards (champion, runner-up, top seed, regular-
  season crown, points king / black hole, toilet bowl, high / low
  week).
- Activity-based awards (Trader / Waiver King / Chaos Agent / Most
  Active / Pick Hoarder / Silent Assassin / Weekly Hammer / Playoff
  MVP / Bad Beat / Best Rebuild / Rivalry of the Year).
- Award races for the in-progress season (top 3 per race), surfaced
  on the Home tab's "Hot race" card.

Award descriptions (`AWARD_DESCRIPTIONS`) ride the payload so the UI
never has to hard-code formula copy.

## Data flow (simplified)

```
Sleeper API  →  sleeper_client.fetch_*  →  snapshot.build_public_snapshot
                                                 │
                                                 ▼
                                         PublicLeagueSnapshot
                                                 │
                                                 ▼
       public_contract.build_public_contract  assembles sections
                                                 │
                        assert_public_payload_safe  (final guard)
                                                 │
                                                 ▼
                             /api/public/league response
                                                 │
                                                 ▼
            frontend/lib/public-league-data.js → /league page
```

## Caveats

- Sleeper's public endpoints have no auth, but they DO rate-limit.  A
  single server cold-start pulls ~18 weeks × 2 seasons of matchups +
  transactions + brackets + users + rosters + drafts.  That's
  ~60+ HTTP GETs — batched sequentially today.  The in-process cache
  TTL (`PUBLIC_LEAGUE_CACHE_TTL`, default 300s) + disk snapshot keep
  this tolerable in practice.
- Some per-player scoring (`players_points`) is inconsistent across
  seasons.  Trader / Waiver / Playoff-MVP calculations handle the
  missing case by returning `None` rather than zero — check
  `awards.py::_player_points_in_week_for_roster`.
- `playoff_week_start` is read from league settings and defaults to 15
  if Sleeper does not expose it.
- `best_rebuild` award is FINALIZED only — it requires both the
  current and previous season to be complete.

## Tests

Run:
```
python -m pytest tests/public_league/ -q   # 111 tests
cd frontend && npm test                     # full vitest suite
```

Key files:
- `tests/public_league/fixtures.py` — two-season deterministic fixture
  with renames, orphan handoffs, playoff brackets, trades, waivers,
  rookie drafts, traded picks.
- `tests/public_league/test_public_contract.py` — safety, identity,
  section coverage, import-surface scan.
- `tests/public_league/test_metrics_engines.py` — every metric engine
  against the fixture.
- `tests/public_league/test_awards.py` — every award formula + live
  race ordering + edge cases.
- `tests/public_league/test_overview.py` — overview derived summaries.
- `tests/public_league/test_server_routes.py` — FastAPI TestClient
  integration against the live routes.

## Extending

Adding a new award:
1. Write the scoring helper in `src/public_league/awards.py` (pattern
   after `_chaos_agent_scores`).
2. Add it to `_activity_awards_for_season` for historical output and
   optionally `_current_season_races` for a live leaderboard.
3. Register a description in `AWARD_DESCRIPTIONS`.
4. Add a renderer case in `frontend/app/league/page.jsx::renderAwardValue`.
5. Write a unit test in `tests/public_league/test_awards.py`.

Adding a new section:
1. Create `src/public_league/<section>.py` with a `build_section` fn.
2. Register it in `public_contract.py::_SECTION_BUILDERS`.
3. Add a renderer component in `page.jsx` and a tab entry in
   `SUB_TABS`.
4. Mirror the section key in `frontend/lib/public-league-data.js`.
5. Add a section coverage test.
