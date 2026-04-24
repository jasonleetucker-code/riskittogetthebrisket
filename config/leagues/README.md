# League registry

Source of truth for every dynasty league the app knows about.

The app was originally built around one Sleeper league (the ID lived in
`SLEEPER_LEAGUE_ID` env var). That env var still works — if
`registry.json` is missing or empty, the code falls back to reading
the env var and synthesising a one-league registry. Once you drop a
`registry.json` in this directory, the env var is ignored.

## Files

- `registry.json` — the active registry. Edited by operators,
  loaded at process start. Schema: `{ schemaVersion, defaultLeagueKey,
  leagues: [...] }`.
- `default_superflex_idp.template.json` — legacy roster-settings
  template kept around for reference; not loaded at runtime.

## Schema

```jsonc
{
  "schemaVersion": 1,                   // bump if the shape changes
  "defaultLeagueKey": "dynasty_main",   // which league unauthenticated
                                        // users see on landing
  "leagues": [
    {
      "key": "dynasty_main",            // stable internal id — NEVER
                                        // reuse once assigned, even
                                        // if the league is deleted.
                                        // Used in URLs + storage paths.
      "displayName": "Dynasty Main (Superflex + TEP + IDP)",
      "sleeperLeagueId": "1312006700437352448",
      "scoringProfile": "superflex_tep15_ppr1",  // marker; actual
                                        // scoring still lives in
                                        // data_contract.py. Shared
                                        // between leagues when the
                                        // scoring matches.
      "idpEnabled": true,               // gates the IDP tab + IDP
                                        // sources for this league
      "active": true,                   // false hides from switcher
                                        // but lookups still work
      "aliases": ["main", "idp"],       // alternate keys accepted by
                                        // get_league_by_key() —
                                        // useful for URL shortforms
      "rosterSettings": {               // free-form dict; callers
                                        // pull the fields they care
                                        // about. No schema enforcement.
        "teamCount": 12,
        "rosterSize": 30,
        "starters": { "QB": 1, "RB": 2, "WR": 3, "TE": 1, ... }
      },
      "defaultTeamMap": {               // username → default team
                                        // lookup for auto-selection
                                        // on fresh devices
        "jasonleetucker": {
          "ownerId": "",                // optional Sleeper user_id
          "teamName": "Rossini Panini"
        }
      }
    }
  ]
}
```

## Adding a third league

1. Get the Sleeper league ID from the URL:
   `https://sleeper.com/leagues/<this-is-the-id>/...`

2. Edit `config/leagues/registry.json` and add an entry:

   ```json
   {
     "key": "dynasty_bestball",
     "displayName": "Best-ball Dynasty",
     "sleeperLeagueId": "9876543210",
     "scoringProfile": "bestball_ppr1",
     "idpEnabled": false,
     "active": true,
     "aliases": ["bestball"],
     "rosterSettings": {
       "teamCount": 10,
       "rosterSize": 20,
       "starters": { "QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 2, "SFLEX": 1 }
     },
     "defaultTeamMap": {}
   }
   ```

3. Restart the backend (or call the admin reload endpoint if added):

   ```
   sudo systemctl restart dynasty
   ```

4. Verify it loaded:

   ```
   curl -s http://127.0.0.1:8000/api/leagues | jq
   ```

## Rules for `key`

- Lowercase snake_case: `dynasty_main`, `best_ball_12`, etc.
- **Never reuse a key.** If you delete a league, the key is retired
  forever — storage paths, URL bookmarks, and user state are all
  keyed on it.
- **Never change a key** for a live league. If you must rename,
  leave the old key as an alias and introduce a new canonical key:

  ```json
  "key": "dynasty_main_v2",
  "aliases": ["dynasty_main", "main", "idp"]
  ```

## What changes when you flip `idpEnabled: false`

Today: the registry stores the flag but callers haven't been wired
up to consume it yet. That's deliberate — this first refactor adds
the registry as the source of truth without changing ranking
behavior. Once Phase 1 of the multi-league plan ships, callers will:

- gate IDP-source registration on `idpEnabled`
- hide the IDP rankings tab in the UI
- skip the IDP backbone build in the ranking pipeline
- drop the "IDP" bucket from portfolio summaries

Until then, `idpEnabled` is advisory — the IDP pipeline runs for all
leagues regardless. Document-only until the downstream wiring lands.

## What `scoringProfile` does

Today: marker string; no behavior hangs off it yet. The plan is to
add `config/scoring/<profile>.json` files defining PPR / TEP /
superflex / etc. and have the ranking pipeline pick up the profile
matching the league being rendered. Two leagues that share scoring
can point at the same profile — which is why scoring lives on the
league, not the scoring profile.

## Testing your changes

Run the registry unit tests:

```
python3 -m pytest tests/api/test_league_registry.py -v
```

And the full suite to make sure nothing downstream blew up:

```
python3 -m pytest tests/ -q
```
