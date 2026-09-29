# C8-U2 — Rankings + Player File defects and explainability (2026-09-29)

Branch `claude/ui-rankings-player-reference`, base `origin/main` `72b25f770`.
**Local evidence only — not production proof.** Deployment and production
re-certification remain separate gates (UI ledger).

## Environment

- Backend: `server:app` via uvicorn on `127.0.0.1:8131`, `E2E_TEST_MODE=1`,
  startup scrape forced to fail (empty `PLAYWRIGHT_BROWSERS_PATH`), so the board
  is the committed snapshot: 1,128 rows, 999 board-eligible, scrape
  `2026-09-29T06:16:45Z`.
- Frontend: `next build --webpack` + `next start -p 3131`, `BACKEND_API_URL`
  pointed at 8131. Bundle check: all 14 budgets green; `/rankings` 60.4 KB / 75 KB.
- Browser: Playwright Chromium 1234; axe-core via `@axe-core/playwright`,
  tags wcag2a/2aa/21a/21aa. Viewports 1366x900 (desktop) and 390x844
  (mobile, touch).

## Defects found (before) → state (after)

| # | Defect (measured) | Before | After |
|---|---|---|---|
| D1 | Expanded source-audit row rendered on the legacy dark terminal palette (`source-audit-*` / `rankings-audit-row` in globals.css); card text overflowed columns | axe color-contrast **283** nodes (1366) / **217** (390, mobile chips at opacity 0.5) | **0** violations both viewports; panel on board.module.css tokens |
| D2 | Mobile: Value (primary number) at x=497 on a 390px screen, behind horizontal scroll (Player column 279px) | table 558px in 376px wrap | table 376px, Value at x=315–383, Consensus (diagnostic) hidden below md and kept in the expanded row |
| D3 | Value chain ("How we arrived at Our Value") showed the IDPTC `anchorValue` diagnostic as the whole derivation for OFFENSE rows (flat blend, α=0) | 459/460 offense rows' chain did not end on their value (Josh Allen 9,989 vs 9,978; Gyllenborg 2,242 vs 672) | one "Blended value" stage = published value; IDP/picks keep anchor+α stages; a "Published value" stage reconciles later passes |
| D4 | Retired methodology shown as current: confidence "2+ sources, tight agreement (spread ≤30)", "High conf — 2+ src, tight", Consensus tip "the blend penalized source disagreement" (λ·MAD, retired), methodology step "measured on the backend's spread signal" (read a `confidenceBuckets` key the contract no longer publishes) | stale copy on every board | current rules, from one copy owner + contract `methodology.confidenceGate` |
| D5 | "Last scraped 7m ago" was board BUILD time (`dataFreshness.generatedAt`); the scrape (`scrapeTimestamp`, /api/health `data_age_hours` 6.2) was 6h older | mislabelled | "Board built 7m ago · from the scrape of 7h ago" + freshness explainer |
| D6 | Source breakdown listed non-voting keys under raw names: `ktcSfTep` (historical fallback) and `ktcCrowdTradesSfTep` (KTC Market BENCHMARK) beside the real KTC Crowd/Trades inputs | Josh Allen: 18 entries incl. both | voting sources only (parity-tested against `_NON_VOTING_SOURCE_CSV_KEYS`); KTC Market shown separately as a named benchmark |
| D7 | "none" confidence (no evidence to grade) rendered as a red "Low" badge and counted in the Low tile | ungraded = Low | "None", neutral badge, counted apart ("+N ungraded") |
| D8 | "How rankings work" dialog body not keyboard-scrollable (prose, no focusable) | axe `scrollable-region-focusable` serious, both viewports | **0**; Tab reaches the labelled region, PageDown scrolls (scrollTop 20→598 / 20→595) |
| D9 | Player File presented an off-cap display ordinal as "Overall rank #983" | unlabelled | "display order — not officially ranked" |

Files: `before/results.json`, `after/results.json` (per-page axe + facts),
`after/notes.txt` (keyboard walkthrough + detail axe).

## Keyboard walkthrough (after, both viewports)

- Board row: focus row → Enter expands the audit panel → Enter collapses.
- "What is Our Value?" InfoTip: Enter opens a labelled region; Escape closes and
  returns focus to the trigger.
- "How rankings work": Enter opens the dialog (focus on close button) → Tab →
  labelled body region → PageDown scrolls → Escape returns focus to the trigger.
- Existing `tests/e2e/specs/psi-rankings-player-a11y.spec.js` +
  `mobile-touch-targets.spec.js`: 16/16 pass (desktop-1366 + mobile-chromium)
  against this stack. A first combined run also including `journey-rankings` and
  `rankings-windowing` had 2 first-load failures with backend 502/503 in the
  console under concurrent load; both passed on rerun (reported, not hidden).

## Not verified here (NV)

Production screenshots/behaviour, WebKit/Safari, real screen-reader output,
performance measurement (no before/after timing taken), expanded-row
`aria-expanded` (DataTable-owned, see PR).
