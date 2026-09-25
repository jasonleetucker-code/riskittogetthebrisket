# ESPN scoreboard fixtures

- `real_*` — trimmed REAL capture of the ESPN public NFL scoreboard
  (20260925T005824Z); only STATUS_END_PERIOD and STATUS_SCHEDULED were observed.
- `synthetic_*` — hand-built, NOT provider captures; they exercise status
  names and edge cases (halftime, overtime, delays, postponements,
  unknown names, malformed events) that no real capture has shown yet.
