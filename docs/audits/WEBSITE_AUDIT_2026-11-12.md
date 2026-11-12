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
| WA-00 | **P0** | Deploy Production hard gate | Every Deploy Production run since 2026-11-11 18:09 UTC failed on one test: `test_idp_hampel_n3_challenger.py::test_on_changes_the_drop_decision_only_on_three_voter_idp_rows` (`assert changed > 0`; 1 failed, 6,324 passed in shard 4/8). It asserted that an asymmetric three-voter IDP row exists on the newest archived board, a live-data claim the hard gate may not make (CLAUDE.md "CI has two lanes"). The 2026-11-11 18:06 archive cut IDP triples from 239 to 72 with none asymmetric enough, so no `main` commit could deploy, production stayed on `78acecf0`, and no deploy restarted the hung scraper (WA-05). | **Fixed**: the existence claim is replaced by an exact per-row oracle (ON drops exactly what the unit-tested rule drops from each row's three votes). Verified on the 8 newest archives: 0 mismatches, both where 37 rows change and where none do. Fails, naming the row, when the challenger is made inert. |
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

0. **WA-00:** merging this PR unblocks Deploy Production. The first green deploy also restarts the backend, which
   should clear WA-05's hung run; verify with `/api/health` (`scrape_stalled: false`, falling `data_age_hours`).
1. **WA-05 (box operator):** restart `dynasty.service` to restore scraping now (a deploy also restarts it), then watch
   the next scheduled run reach `chromium_launch_done`. Investigate the service's memory growth (≈1 GiB locally
   after boot vs 2.6 GiB in production after ~21 h and several scrape cycles). Code hardening worth a reviewed
   follow-up: a Python-side deadline around Playwright driver start and `chromium.launch`, so a wedged driver fails
   the run in minutes instead of 2 h. Not done here: it is the production scraper, and it would not fix the cause.
2. WA-06 … WA-11: backlog for the owning lanes.
3. Full backend suite and WebKit E2E: run by CI on the PR (L2).

## 6. Readiness verdict

**NOT READY** today: production cannot deploy (WA-00), and its data is 19.5 h stale (WA-05). Code health on this
branch is good: no crash, no 500, no layout overflow, auth boundaries hold, and the trade package math matches an
independent oracle. Once this PR merges and deploys and scraping recovers, the verdict would be **READY WITH
NONCRITICAL ISSUES** (WA-06 … WA-11), subject to production verification of WA-00, WA-01 and WA-05.

## 7. Second pass — owner follow-up, 2026-11-12

The owner authorized finishing every repair, including the four frontend findings (overriding the 2026-11-08 frontend
exclusion for exactly these items). PR #2188 (WA-00 … WA-04) merged as `1ac74809` after green PR Validation (8 shards),
E2E Safety Net (Chromium + WebKit), Receipt and L0, and an independent review (approve; its two non-blocking notes are
WA-14 below and a remark that `/api/admin/diagnostics` still computes `_health_content` on the loop, which is fast).

### 7.1 Status of every finding

| ID | Status | Where fixed | Evidence |
|---|---|---|---|
| WA-00 | Fixed, merged | #2188 | shard 4/8 green on the PR; production deploy: see §7.4 |
| WA-01 | Fixed, merged | #2188 | red/green test; production check: see §7.4 |
| WA-02 | Fixed, merged | #2188 | red/green test |
| WA-03 | Fixed, merged | #2188 | E2E Safety Net green (Chromium + WebKit) |
| WA-04 | Fixed, merged | #2188 | 9 fail without the redirect, all pass with it |
| WA-05 | Fixed, merged, deployed | #2189 | §7.2; production scrapes succeed (12:42, 13:38, 14:39 UTC; on the #2189 build Chromium launched in 2 s) |
| WA-06 | Fixed, merged, deployed | #2189 | `tests/api/test_more_handlers_off_event_loop.py`: 2 fail on `main`, 6/6 pass |
| WA-07 | Fixed, merged, deployed | #2189 | same file (custom-alerts sweep incl. SMTP and push in the threadpool) |
| WA-08 | Fixed, merged, deployed | #2189 | 48 per-segment server `layout.js` + `lib/page-metadata.js` (labels from `nav-model.js`); `__tests__/page-titles.test.js` walks every page |
| WA-09 | Not a defect | — | the crawl's hit is "Import slate" inside a closed `<details>`: `innerText` is empty there, the accessible name is correct; no icon-only unnamed button in `components/dfs` |
| WA-10 | Fixed, merged, deployed | #2189 | `team_required` copy on `/rosters` and the same leak on `/phases` (`TeamPhasePanel`) |
| WA-11 | Fixed, merged, deployed | #2189 | `/draft` requests roster context only once the league's workspace has hydrated (`isWorkspaceReady`) |
| WA-12 | Fixed, merged, deployed (new) | #2189 | monitoring gap: `box_resources` did not show `memory.high`, so throttling was invisible |
| WA-13 | Fixed, merged, deployed (new) | #2189 | stale-data banner promised "should land soon" while refreshes were failing |
| WA-14 | Fixed, merged, deployed (new) | #2189 | WA-00 oracle could flip on an integer-rounding boundary (1 of 1,578 rows inside the margin over 8 archives) |
| WA-15 | Fixed, merged, deployed (new) | #2189 | `/draft` first visit (no saved workspace) still keyed Perfect Draft on the seed team "Russini Panini" (400), and "my team" fell back to row 0 (another manager); the readiness gate could also wait forever if `/api/leagues` failed (independent review) |
| WA-16 | Fixed, merged, deployed (new, P2) | #2189 | Perfect Draft vanished for 11 of 12 `dynasty_main` teams: draft-capital names teams by Sleeper team name, `match_team` knew only display names (`unknown_team`); now 12 of 12 resolve; a team name two teams share resolves to neither. Delta review: a real team equal to a seed row ({Ed, $71}) could be overridden as "my team" and was not sent by name; fixed |

| WA-17 | Mechanism established (process heap past `memory.high` → throttling → watchdog restart); heap lower on #2189 for the one cycle observed; open, monitored | — | Unplanned backend restart 13:32 UTC on the same commit: §7.9 |
| WA-18 | Fixed in PR, pending deploy (new, monitoring) | #2191 | `box_resources.chromium_processes` read 0 while Chromium ran: the kernel keeps 15 characters of a process name (`chrome-headless`), the list held the 16-character `chrome-headless-` |
| WA-19 | Fixed, merged (new, P1 for trades) | #2190 | 35 pick rows priced by approved C1-U6 derivations or the rookie tether were quarantined (`no_valid_source_values`), withholding every trade verdict that touched one (e.g. "2029 Mid 5th (received, quarantined)"). Record: `docs/picks/DERIVED_PICK_QUARANTINE_2026-11-12.md` |

### 7.2 WA-05 root cause: the scraper hang

- `deploy/systemd/dynasty.service.template` sets `MemoryHigh=2560M`, `MemoryMax=3G`. Production read
  `cgroup_memory_current_mib` 2571-2607 throughout the failure: above `memory.high`, where the kernel throttles every
  process in the cgroup (forced reclaim, sleep penalties) instead of killing one. The first launch failure (23:27 UTC)
  came ~10.5 h after the process started (12:49 UTC).
- Chromium launch and the Playwright driver start had no Python-side deadline. Playwright's 180 s launch timeout is
  enforced by its Node driver, so a throttled driver never fires it: each run sat at `browser/launch` until the 2 h
  run timeout. Reproduced through the real `run()` with a stalled driver: the original code hung until the outer cap;
  the bounded code raised `TimeoutError` at the configured deadline.
- **Fixes:** Python-side deadlines on the driver start (120 s) and the launch (240 s, past Playwright's own 180 s;
  env-tunable), pinned by `tests/api/test_scraper_launch_deadline.py` (fails on the old file, naming both calls);
  `malloc_trim(0)` before each run and after each publish (§7.3); the new diagnostics fields (WA-12).

### 7.3 Memory investigation

Measured locally by replaying the publish path (`_prime_latest_payload`) with the committed board, each cycle on a
fresh thread, as production does:

| Experiment | Result |
|---|---|
| Re-import the scraper module 6x | one live module object every time; RSS plateau ~236 MB: ruled out |
| 14 publish cycles, default malloc | live Python objects constant at 330,466 from cycle 2; threads back to 1; RSS 393 -> 684 MB, plateau from cycle 10 |
| 14 cycles, `malloc_trim(0)` after each | objects constant; RSS plateau 498 MB (-186 MB, -27 %) |
| 8 cycles, `MALLOC_ARENA_MAX=2` (first harness, serving flag unset: not comparable) | RSS 277-474 MB vs 291-557 MB default in the same harness; not pursued |
| tracemalloc without the serving flag | `trade-analysis-warm` threads accumulated while waiting on `_SERVING_STARTED`: an artifact of the harness, gone once the flag is set |

Conclusion: no reference leak in the publish path; RSS growth is allocator high-water, which a trim reduces. The
production split between process RSS, page cache and Chromium is not observable from outside; `process_rss_mib` and
`cgroup_memory_high_mib` (WA-12) make it observable once deployed. Not done: changing `MemoryHigh` / `MemoryMax` or
adding scheduled restarts (both would hide, not fix).

### 7.4 Production verification (2026-11-12, read-only)

| Check | Observation |
|---|---|
| Deployed commit | `1ac74809` (#2188), Deploy Production #3844 **success**; process started 12:37:12 UTC; the next automated deploy (#3845) ran normally |
| `/api/status` latency | 0.65-0.90 s (was 14-18 s) |
| Event loop | concurrent `/api/leagues` 0.52-0.82 s during a status call (0.58 s alone; was 15.9 s) |
| Scraper | startup run: browser launched in ~3 s, KTC 27 s, IDPTradeCalc ~2 min; `scrape_succeeded 1091 players, 2/2 sites, 294.8 s` at 12:42:50 UTC; no critical source failures; 0 Chromium processes left |
| Health | `status: ok` (HTTP 200; was 503 degraded), `data_age_hours` 0.0, `source_health_ok` true, `contract_ok` true |
| Memory | cgroup 628 MiB at startup, 1,277 MiB right after the scrape (12:42:56), 2,323 MiB at 12:53 with nothing scraping (was 2,571-2,607 above `MemoryHigh` 2,560 before the restart). The state backup runs in its own unit, so its file cache is not charged here. Whether the growth is process heap or reclaimable page cache is unknown until the follow-up adds `cgroup_memory_anon_mib` / `cgroup_memory_file_mib` / `process_rss_mib` |
| Security (from outside) | unchanged from §3: headers present, private APIs 401, test endpoint 404, no OpenAPI, no permissive CORS |

Not verified in production: signed-in pages (no credentials), WA-06 … WA-16 (follow-up PR not yet deployed), memory over
days. One `/api/status` read returned all-null `box_resources` (the bounded probe timed out once); earlier reads were
populated.

### 7.5 Feature verification matrix

Environments: L = local stack on the follow-up branch (committed board, signed in as a real `dynasty_main` manager via
the test-session endpoint); CI = GitHub Actions on the PR head; P = production, read-only.

| Feature | Test | Env | Result | Limits |
|---|---|---|---|---|
| Every page renders | crawler: 62 URLs x anon/signed-in x 1366/390 px (248) | L | 0 page errors, 0 error boundaries, 0 overflow, 0 NaN/undefined | — |
| Tab titles | crawler + `page-titles.test.js` + SSR read | L | 0 generic; 58 distinct of 62 (rankings positions share "Rankings") | — |
| Public league pages | 30 visits | P | 0 page errors / overflow | anonymous only |
| Auth boundary | 231 routes: private GET + all mutating anon -> 401 | L | holds | — |
| League isolation | `/api/data`, `/api/terminal`, `/api/roster/intelligence` for `dynasty_new` | L | refuse (`data_not_ready`), never the other league's rosters; unknown key `unknown_league` | second league has no contract locally |
| Rankings | E2E `journey-rankings` (6), `rankings-windowing` | CI | pass | — |
| Trade calculator math | independent oracle, 5,000 random packages, Python + JS owners | L | 0 beyond ±0.5 | — |
| Trade analysis (route) | `POST /api/trade/analyze` 1-for-2 vs hand arithmetic from board values | L | exact: raw gap 8301, VA +1962, adjusted 11960 / 18299 | one trade |
| Trade builder / War Room | E2E `journey-trade`, `trade-war-room`, `trade-multi-team*`, `trade-tce`, `trade-tcd2` | CI | pass | — |
| Settings persistence | E2E `journey-settings-overrides` (toggle round-trip) | CI + L | pass | — |
| Draft / Perfect Draft | E2E `journey-perfect-draft`; first-visit probe; 12 team names -> roster context | CI + L | pass; own team loads; 12/12 resolve | live auction not exercised |
| Waivers / advisor | E2E `waivers-smoke`, `waiver-advisor-streaming` | CI | pass | — |
| Game Day | E2E `game-day` (7) | CI | pass | live NFL scoring not exercised |
| DFS | E2E `dfs-workspace` (3) | CI | pass | owner-paused feature |
| Roster construction | E2E `roster-construction` (4) | CI | pass | flag default OFF |
| Public league hub | E2E `public-league` (16) | CI | pass | — |
| Multi-league | E2E `multi-league` (8) | CI | pass | — |
| Freshness banner | `stale-data-banner-states.test.jsx` (10 states incl. production-shaped payload) | L | pass | — |
| Scraper | stalled-driver demo; production run | L + P | bounded failure; production success | one production cycle observed |

### 7.6 Test report

| Suite | Env | Result |
|---|---|---|
| Frontend vitest | L (follow-up) | 426 files; 5,533 passed, 3 expected-fail, 0 failed (277 in the touched draft files after the last fixes) |
| Next build + bundle budgets | L (follow-up) | pass, 19/19 pages under budget |
| Backend hard gate (8 shards) | CI on #2188 | pass (shard 4/8 included the WA-00 test) |
| E2E Safety Net (Chromium desktop + mobile, WebKit iPhone) | CI on #2188 | pass |
| E2E full run (desktop + mobile-chromium) | L (before fixes) | 416 passed, 70 skipped, 1 failed (WA-03, fixed) |
| Targeted backend L1 | L | 3,224 + 395 + 265 + 92 + 52 + 36 + 28 + 9 + 6 + 5 passed |
| Full backend suite | L | not executed serially (CPU-bound here); CI's sharded gate is the authority |
| Skipped | — | 70 E2E skips are the suite's declared desktop-only / flag-gated cases; none counted as passed |

### 7.7 Remaining action register

| # | Item | Why open | Next step | Blocks readiness? |
|---|---|---|---|---|
| 1 | Memory across many cycles (WA-17) | on the #2189 build one cycle is observed: process RSS 661 → 1,337 peak → 1,230-1,294 MiB, no `memory.high` events; before it the heap reached 2.8 GiB and the watchdog restarted the backend | watch `process_rss_mib` / `cgroup_memory_anon_mib` / `cgroup_memory_high_events` over several 2 h cycles; if the heap still climbs, attribute it per post-scrape warm pass (tracemalloc on the box) | no, monitored; a regression shows as `memory.high` events |
| 2 | Signed-in production checks | no production credentials here; the public advisor is disabled | owner signs in and checks `/trade` with 2029 Mid 5th / Mid 6th (no withheld side) once #2190 deploys | no |
| 3 | Owned future picks: browser Mid row vs engine generic row (TC-22) | up to 2.5% on the preliminary meter only; the deferred frontend label-lookup migration | `docs/picks/DERIVED_PICK_QUARANTINE_2026-11-12.md` §Adjacent gap | no |
| 4 | Raw ports from the internet | only probed from this egress | box-side `ss -ltnp` / firewall check by the operator | no |
| 5 | `/api/admin/diagnostics` health half | `_health_content` still on the loop (fast in production) | optional; same pattern if it ever slows | no |

### 7.8 Verdict

**READY WITH MINOR ISSUES.** Production runs #2189 (`45c25008`, deployed 14:35 UTC): scrapes succeed, health is
`ok`, `/api/status` no longer stalls the site, the new tab titles and diagnostics are live, and every page loads
cleanly. The trade-calculator quarantine defect (WA-19) is merged (#2190) and verified on the merged code with the
latest production export; its live check follows its deploy. The open item that matters is WA-17: the heap is
markedly lower on #2189 but has been watched for one cycle only (§7.7 #1).

### 7.9 Production after #2189 (2026-11-12, read-only)

**The 13:32 restart (WA-17), from the box journal** (`prod-restart-diagnostics.yml`, read-only, window 12:35-13:40):
at the first failed liveness probe (13:29:42) the service cgroup held 2,806 MiB against `memory.high` 2,560 MiB, with
`memory.events high` 82,914 rising to 100,198, `anon` 2,792 MB and `file` 0, and memory pressure `full avg10` ~38%.
After three failed one-minute probes the healthcheck watchdog restarted the service (13:31:42). The wedged process
ignored SIGTERM and was SIGKILLed at 13:32:14. No kernel OOM; `memory.max` (3 GiB) was never reached. systemd reported a
2.5-2.6 GiB peak for each of the day's three process lifetimes. So the growth was process heap, not page cache, and the
outage was throttling at `memory.high`, not a kill.

**#2189 deployed** (`45c25008`, process started 14:35:16 UTC):

| Check | Observation |
|---|---|
| New diagnostics (WA-12) | `cgroup_memory_high_mib` 2560, `cgroup_memory_high_events` 0, `cgroup_memory_anon_mib` / `file_mib` / `process_rss_mib` populated |
| Heap release | `scrape_prelaunch_heap_release`: RSS 479 → 424 MiB before launch |
| Scraper (WA-05) | Chromium up in 2 s, KTC 24 s; `scrape_succeeded 1090 players, 2/2 sites, 247.9 s` at 14:39:52 |
| Memory, first cycle | RSS 661 (scraping) → 708 → 1,108 → 1,337 (peak, 14:45) → 1,230 flat for 10 min → 1,294 at 14:58; anon 1,185-1,249; file ~940 (reclaimable); `memory.high` events 0 |
| Health | `ok`, data 0.3 h old, source health and contract OK |
| Titles (WA-08) | `/login` and every private page's redirect read "Sign in — Chase Upside" |

**#2190** (WA-19) merged as `4b47329c`. Rebuilding the latest production export (`exports/latest`, scrape 10:22 UTC)
with the merged code: 0 of 138 pick rows quarantined (was 35), values unchanged, `2029 Mid 5th` 1471 / `Mid 6th` 1347 /
`Round 5` 1478 / `Round 6` 1354 all `quarantined: false`, confidence `low`.
