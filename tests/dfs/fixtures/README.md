# DFS test fixtures — SYNTHETIC

Every file here is **synthetic**: invented team codes (AAA..FFF), invented
"Syn …" names, random salaries and projections from a fixed seed. They exist
to exercise parsers and the solver. They are not real players, not real
salaries, not real projections, and must never be loaded as live data.

Official platform templates, when the owner supplies them, go in
`templates/` and are the only files that may mark an export format verified.

**Exception — recorded schedule data.** `espn_scoreboard_nhl_2026-10-07.json` and
`espn_scoreboard_nba_2026-10-21.json` are ESPN public scoreboard responses recorded on
2026-10-07 and trimmed to the fields `src/dfs/auto/league_schedule.parse` reads (event id, start
time, season year/type, status, team abbreviations, `timeValid`). They are factual schedule data
only — no player, salary or projection content. Daily Fantasy Fuel pages are never committed
(redistribution rights not established); tests synthesise DFF rows in the observed row shape.
