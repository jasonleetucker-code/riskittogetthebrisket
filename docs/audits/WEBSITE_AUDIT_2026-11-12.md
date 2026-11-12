# Website audit — 2026-11-12

Owner request (session 2026-11-12): a complete functional audit of the site, with repair of confirmed defects and an
evidence-based readiness verdict. Product authority: `docs/EXECUTION_PLAN.md`. This record reuses the existing feature
census (`docs/audits/remediation_2026-11-06/FEATURE_CENSUS.md`: 61 pages, 229 backend routes, 88 bridge routes,
68 flags, 54 jobs); it is not a second inventory. Agent-OS-Receipt: `aa55ed12383caa257a25d28baa6612bc9577347d`.

Scope decision: the 2026-11-08 directives exclude frontend changes. This audit therefore repairs backend and test
defects, and records frontend findings for the frontend lane (none is P0/P1).

## 1. What was exercised

| Layer | Method | Result |
|---|---|---|
| Frontend unit | `npx vitest run` (frontend) | 424 files, 5,503 passed, 3 expected-fail, 0 failed |
| Frontend build | `npm run build` (Next build + bundle budgets + public-bundle privacy) | pass; 19/19 pages under budget |
| Backend formatting | `bash scripts/format_python_changes.sh` | green (Ruff 0.6.9) |
| API contract | `tests/e2e/preflight.py` (contract, lane full) | ok, 0 structural, 0 source-health errors, 5 warnings |
| Backend tests | full serial run was impractical here (8% after 1 h on 4 CPUs; CI shards it), so targeted L1: ~3,700 tests across `tests/nfl_data`, `bdvm`, `ros`, `league_comparison`, `playerctx`, and the touched `tests/api` files | green after the repairs below (see §4) |
| E2E | existing suite, `desktop-1366` + `mobile-chromium`, against a booted local stack | 416 passed, 70 skipped, 1 failed (WA-03, repaired) |
| Page crawl | own Playwright crawler, every page route (62 concrete URLs incl. 13 dynamic), anon + signed-in, 1366 px + 390 px, behind a proxy matching production nginx routing | 248 visits, plus 124 signed-in as a real league member |
| API sweep | every route in the live OpenAPI table (231): GET anon + signed-in, non-GET anon only | no HTTP 500; every 5xx is a named 503 |
| Production (read-only) | health, status, headers, auth gating, 30 public-page browser visits | see §3 |
| Independent oracle | 5,000 random two-sided packages; `U = Σ 0.78^i·v_i` computed with no repository imports | Python and JS package-model owners: 0 cases beyond ±0.5 (the documented whole-unit rounding) |

Not exercised: WebKit / Firefox / Safari (only Chromium is installed here); authenticated production pages (no
credentials); real payments / e-mail / push / Sleeper writes (none attempted, by rule); the on-box timers (no box
access); a full serial backend run (CI's sharded L2 covers it).

## 2. Findings register

| ID | Sev | Where | Finding | Status |
|---|---|---|---|---|
| WA-01 | P1 | `GET /api/status` (+ `/api/admin/diagnostics`) | Async handler ran every probe on the event loop. Production 2026-11-12: 14-18 s per call; a concurrent `/api/leagues` (0.45 s alone) waited 15.9 s. Every status poll (settings, tools pages, monitors) froze the single-worker backend for all users. | **Fixed**: probes run in the threadpool (`_public_status_body`); `_scrape_status_payload` (check-then-set on `scrape_status`) stays on the loop; the `git ls-files` probe (10 s timeout) memoized 30 s via `_disk_probe_memo`. Test `tests/api/test_slow_handlers_off_event_loop.py`. The slow sub-call in production is not identified (no box access): the fix removes the site-wide stall, not the status endpoint's own latency. |
| WA-02 | P2 | `GET /api/sleeper/draft/picks` | Live-draft poll (every 2-3 s) fetched Sleeper on the event loop: each poll stalled the site for the Sleeper round-trip, or its timeout when Sleeper is slow. | **Fixed**: fetch in the threadpool (the fetcher already locks its cache). Same test file. |
| WA-03 | P2 | E2E `journey-settings-overrides.spec.js` | "≥ 27 toggles" assertion raced data load. Non-voting private sources deliberately render their vote state instead of a toggle (`settings/page.jsx`, `lib/source-vote-state.js`): 27 toggles at first paint, 20 settled. The assertion passed only if it counted early. | **Fixed** (test): one row per registered source; every row offers the toggle or states why not; scoped to the Ranking Sources panel; deterministic settle. 6/6 over 3 repeats. |
| WA-04 | P2 | test isolation | `data/nfl_data_cache/` was not covered by `tests/runtime_data_isolation.py`. Once a local server cached the real 2026 schedule, 8 of 29 `tests/api/test_matchup_intel.py` tests failed (`final` vs fixture `pregame`); 29/29 pass on a clean checkout. Violates the 2026-09-23 rule (an ignored runtime file must not change a deterministic test). | **Fixed**: redirected in the isolation owner; proof `test_the_nflverse_cache_at_the_real_path_is_not_read`. Without the redirect: 9 failed; with it: all pass. |
| WA-05 | P1 (ops) | production scraper | Since 2026-11-11 23:27 UTC every run hangs at "Launching browser context", past Playwright's own 180 s launch timeout, until the 2 h run timeout. 6 of 8 runs failed in 24 h; data 19.5 h stale; at failure the service cgroup held 2.6 of 3.0 GiB with no Chromium running. The stall is detected at 900 s but not acted on. | **Not fixed — box action needed** (§5). |
| WA-06 | P3 | `GET /api/player/{id}/realized` | Network fetch + parse on the event loop (8.5 s cold locally). No frontend caller (per its docstring). | Open, recorded. |
| WA-07 | P3 | `POST /api/custom-alerts/run` | SMTP send on the event loop (cron-triggered). | Open, recorded. |
| WA-08 | P3 (a11y) | ~45 private pages | Browser title is the generic "Chase Upside" (WCAG 2.4.2: tabs and history indistinguishable). | Open — frontend lane. |
| WA-09 | P3 (a11y) | `/dfs` | One button without an accessible name. | Open — frontend lane (DFS is owner-paused). |
| WA-10 | P3 (copy) | `/rosters` no-team state | Shows the API's developer message ("Pass ?team=<ownerId>…") to end users. | Open — frontend lane. |
| WA-11 | P3 | `/draft` cold load | Placeholder team "Russini Panini" is requested once before the workspace hydrates (one 400 + console error). Already handled (`PerfectDraftPanel.jsx` follows the real team). | Open — frontend lane. |

Checked and **not** defects: `/api/health` 503 while degraded (the stale-data banner reads the body by design and shows
"Scrape worker stalled" when stalled); `team_required` 400s for a session without a linked team (pages render a
team picker); `/api/waiver/advisor` first-request 400 (documented gate probe); the named 503s for flag-off features,
`trade_ledger_not_built`, missing intel snapshot, push not configured.

## 3. Production (read-only, 2026-11-12 ~10:20 UTC)

- Security: HSTS, `nosniff`, `X-Frame-Options`/CSP `frame-ancestors`, referrer and permissions policies present; no
  server version; private APIs 401; `POST /api/test/create-session` 404; no OpenAPI exposure; no permissive CORS;
  ports 8000/3000 not reachable from this vantage point (may be egress filtering here, so not proof of closure).
- 30 anonymous visits to public pages (desktop + mobile): 0 page errors, 0 error boundaries, 0 horizontal overflow.
- Health: `degraded`, data 19.5 h stale, scrape stalled (WA-05). `/api/status` 14-18 s and blocking (WA-01).
- Running commit `78acecf0`; process started 2026-11-11 12:49 UTC.

## 4. Repairs: evidence

| Repair | Red on old code | Green on new code |
|---|---|---|
| WA-01/02 | 3 of 4 new tests fail, each with `saw_release == [False]` (the concurrent request was frozen) | 4/4 pass |
| WA-03 | 1 failure in the full E2E run (20 < 27) | 6/6 over `--repeat-each=3` |
| WA-04 | 9 fail (proof + 8 matchup tests) with the redirect removed | all pass with the real cache populated |

L1 after the repairs: 395 passed (status / diagnostics / live draft / backup / freshness / auth regressions); 3,224
passed across the nfl_data / bdvm / ros / league_comparison / playerctx suites. The 12 guard errors in that run were the
suite's write-guard catching my own mid-run backend restart; all 12 pass re-run with the server idle.

## 5. Blockers and owner / operator actions

1. **WA-05 (box operator):** restart `dynasty.service` to restore scraping now (a deploy also restarts it), then watch
   the next scheduled run reach `chromium_launch_done`. Investigate the service's memory growth (≈1 GiB locally
   after boot vs 2.6 GiB in production after ~21 h and several scrape cycles). Code hardening worth a reviewed
   follow-up: a Python-side deadline around Playwright driver start and `chromium.launch`, so a wedged driver fails
   the run in minutes instead of 2 h. Not done here: it is the production scraper, and it would not fix the cause.
2. WA-06 … WA-11: backlog for the owning lanes.
3. Full backend suite and WebKit E2E: run by CI on the PR (L2).

## 6. Readiness verdict

**NOT READY** for an "everything verified" claim while WA-05 holds production data 19.5 h stale. Code health on this
branch is good: no crash, no 500, no layout overflow, auth boundaries hold, and the trade package math matches an
independent oracle. After WA-05 is cleared and this PR deploys, the verdict would be **READY WITH NONCRITICAL ISSUES**
(WA-06 … WA-11), subject to production verification of WA-01.
