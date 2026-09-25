# Game Day U7 UI — local evidence (2026-09-25)

**Scope:** local build evidence for the U7 Game Day UI on branch
`claude/game-day-ui`, after merging `claude/game-day-core` (68579b128:
`scoreNow`, `actualLineup.unknownStatePlayerIds`, `beatMedianVerified`) and
`claude/game-day-collector` (U5 collector + `freshness` block).
**Not production evidence** — nothing here was deployed.

## How it was produced

- `npm run build` (Next `--webpack`) of the branch head, served with
  `next start -p 3100`.
- `/api/matchup/intel` answered with the generated payloads in
  `frontend/__tests__/fixtures/game-day/*.json`. `tests/game_day/ui_payloads.py`
  builds them on the production path: the U5 collector ticks over the U4
  replay captures (network clients replaced by the captures), writes a
  generation, and `build_matchup_intel` SERVES it with its `freshness` block.
  `tests/game_day/test_game_day_ui_fixtures.py` pins byte equality. Each file's
  `_fixture.description` names what is a real capture and what is labelled
  synthetic. `/api/leagues` / `/api/auth/status` answered by a local mock;
  everything else 404s (no contract) — the shell's degraded chrome is not
  part of this evidence.
- Team names are replay labels (`Team 8`, `Team 10`), not real managers.
- Playwright + Chromium 145 with `@axe-core/playwright`, WCAG 2.0/2.1 A+AA,
  scan scoped to `main`. Viewports: desktop 1366x900, phone 390x844
  (`isMobile`, touch).

## Results (`results.json`)

| scenario | freshness | desktop 1366 | phone 390 |
|---|---|---|---|
| pregame (synthetic clock over real inputs) | current | axe 0, no h-scroll | axe 0, no h-scroll |
| halftime (real capture) | current | axe 0, no h-scroll | axe 0, no h-scroll |
| overtime (synthetic; win chance withheld) | current | axe 0, no h-scroll | axe 0, no h-scroll |
| mixed slate (synthetic, every game stage) | current | axe 0, no h-scroll | axe 0, no h-scroll |
| week final (synthetic) | current | axe 0, no h-scroll | axe 0, no h-scroll |
| live feed down (ESPN HTTP 403) | **partial** | axe 0, no h-scroll | axe 0, no h-scroll |
| stale (served 2 h after the last tick) | **stale** | axe 0, no h-scroll | axe 0, no h-scroll |

- Keyboard (halftime, both viewports): "Best-ball details" reached with Tab,
  opened with Enter; with it and the GB@ATL player table open, axe 0 and no
  sideways scroll (`halftime-*-details-open.png`, `halftime-*-bestball-open.png`).
- Data info open on the partial state, per-source table visible with the ESPN
  row "error (http_error:403)": axe 0, no sideways scroll
  (`live-feed-down-*-data-info.png`). The first E2E run caught this table
  overflowing the phone (`scrollable-region-focusable`); cells now wrap.

## Committed E2E

`tests/e2e/specs/game-day.spec.js` — the same payloads served through
`page.route` (no network). Run locally against this build
(`E2E_BASE_URL` = local mock backend, `E2E_PAGE_ORIGIN` = `next start`):
**16 passed** on `desktop-1366` and `mobile-chromium` (pregame, halftime,
overtime, live-feed-down, stale, week-final states; keyboard disclosure +
opened detail axe; refresh without blanking — old numbers stay on screen
under "Updating this matchup…", then update in place with the same DOM root,
Data info still open, focus still on Refresh). The webkit phone projects
(`mobile-390`/`mobile-430`) were not run locally (no webkit installed).

## Bundle (first-load = sum of the `<script src>` chunks in each route's prerendered HTML)

| route | base `origin/claude/game-day-core` (pre-U7) | this head |
|---|---|---|
| `/game-day` page chunk | 34.0 KB | 34.8 KB |
| `/game-day` first-load JS | 700.0 KB | 707.4 KB (+7.4 KB) |
| `/trades` first-load JS | 720.8 KB | 720.9 KB |
| budgeted pages | all under budget | all under budget |

Best-ball details, Data info and the per-game player table are code-split
and load on first open.
