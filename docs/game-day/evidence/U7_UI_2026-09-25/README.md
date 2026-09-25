# Game Day U7 UI — local evidence (2026-09-25)

**Scope:** local build evidence for the U7 Game Day UI on branch
`claude/game-day-ui`, code commits `092b03a91` + `2ddc6d76c`. **Not production evidence** —
nothing here was deployed; production verification remains a separate gate.

## How it was produced

- `npm run build` (Next `--webpack`) of `2ddc6d76c`, served with
  `next start -p 3100`.
- A local mock backend answered `/api/matchup/intel` with the generated
  replay payloads in `frontend/__tests__/fixtures/game-day/*.json` (built from
  the U4 replay captures by `tests/game_day/ui_payloads.py`; each file's
  `_fixture.description` says which inputs are real captures and which are
  labelled synthetic), `/api/leagues` with one league (`dynasty_main`) and
  `/api/auth/status` as authenticated. Everything else 404s (no contract,
  no user state) — the shell's degraded chrome is not part of this evidence.
- Team names are replay labels (`Team 8`, `Team 10`), not real managers.
- Playwright + Chromium 145 with `@axe-core/playwright`, WCAG 2.0/2.1 A+AA
  tags, scan scoped to `main`. Viewports: desktop 1366x900, phone 390x844
  (`isMobile`, touch).

## Results (`results.json`)

| scenario | desktop 1366 | phone 390 |
|---|---|---|
| pregame (synthetic clock over real inputs) | axe 0, no h-scroll | axe 0, no h-scroll |
| halftime (real capture) | axe 0, no h-scroll | axe 0, no h-scroll |
| overtime (synthetic, win chance withheld) | axe 0, no h-scroll | axe 0, no h-scroll |
| mixed slate (synthetic, every game stage) | axe 0, no h-scroll | axe 0, no h-scroll |
| week final (synthetic) | axe 0, no h-scroll | axe 0, no h-scroll |
| live feed down (real capture, feed failure) | axe 0, no h-scroll | axe 0, no h-scroll |

Keyboard (halftime, both viewports): the "Best-ball details" disclosure is
reached with Tab, opens with Enter (`aria-expanded="true"`); with it and the
GB@ATL player table open, axe is still 0 and the page still does not scroll
sideways (`*-details-open.png`, `*-bestball-open.png`).

First run of this harness found, and the commit fixed: the legacy global
`th` style painting a dark sticky background behind the scoreboard headers
(11–15 contrast failures), and a 5-column scoreboard / per-game table pushing
the phone layout to 543 px. The screenshots then showed the live-feed-down
state reading "Score now 0.0 · No players have played yet" beside Sleeper's
26.8 (the canonical current lineup seats only observed-begun players);
`2ddc6d76c` shows the labelled Sleeper total instead.

## Bundle (same machine; first-load = sum of the `<script src>` chunks in each route's prerendered HTML)

| route | base `origin/claude/game-day-core` | this commit |
|---|---|---|
| `/game-day` page chunk | 34.0 KB | 32.0 KB |
| `/game-day` first-load JS | 700.0 KB | 704.6 KB (+4.6 KB) |
| `/trades` first-load JS | 720.8 KB | 720.9 KB |
| budgeted pages | all under budget | all under budget |

Best-ball details, Data info and the per-game player table are code-split
and load on first open.
