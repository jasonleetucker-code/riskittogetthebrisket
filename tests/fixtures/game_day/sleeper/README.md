# Sleeper weekly stat fixtures

`real_2026w3_thu_sleeper_stats.json` is a REAL capture of
`GET https://api.sleeper.app/v1/stats/nfl/regular/2026/3` taken at
20260925T005824Z (end of the 1st quarter of the Thursday game), trimmed to
these entries (positions from the same-time Sleeper projections capture):

- `6804` — QB Jordan Love (GB)
- `8154` — RB (offense, rushing + kick return)
- `7553` — TE (reception bonus keys)
- `13545` — K Trey Smack (GB)
- `6788` — DB Xavier McKinney (GB) — IDP, interception
- `10934` — IDP tackle line
- `12586` — listed with gms_active only (no production yet)
- `GB` — team entry, bare code
- `TEAM_GB` — team entry, TEAM_ prefix

The v1 payload is an object keyed by player id; it carries no
`updated_at`, `game_id` or `team` per row.
