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

| WA-17 | Mechanism established (process heap past `memory.high` → throttling → watchdog restart); recurred at 15:42 UTC on the #2190 build. Mitigations and on-box heap report merged and deployed (#2193: glibc arenas capped at 2, WA-20); production split read (#2194): the post-restart climb is live Python objects (+4.8 M blocks, about 345 MiB) plus about 206 MiB of freed glibc heap; periodic heap release and census trigger merged (#2195). At 21:07 UTC a transient burst of about 19 M Python objects took RSS to 2,151 MiB and throttled the service (2,799 `memory.high` events, no restart); after it, Python's allocator kept about 1 GB (§7.12). The peak census (#2196) names the producer: the Sharp cohort build held all 1,138,004 ledger season rows at once; this PR streams them (§7.13). Open until production shows no burst and no new `memory.high` events | #2193, #2194, #2195, #2196, this PR | Unplanned backend restart 13:32 UTC on the same commit: §7.9, §7.11, §7.12 |
| WA-18 | Fixed, merged, deployed, verified (new, monitoring) | #2191 | `box_resources.chromium_processes` read 0 while Chromium ran: the kernel keeps 15 characters of a process name (`chrome-headless`), the list held the 16-character `chrome-headless-` |
| WA-20 | Fixed, merged, deployed, verified (new, memory) | #2193 | `python server.py` executed server.py's module body twice: once as `__main__`, then again when `uvicorn.run("server:app")` imported it as `server`. The `__main__` copy was never served but kept its own module state, including a second 44 MiB public-league snapshot. Production deep census after deploy: no `__main__` copy. §7.11, §7.12 |
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
| 1 | Memory across cycles (WA-17) | the heap passed `memory.high` under load twice on 2026-11-12 (§7.9, §7.10), and a 21:07 burst throttled it again without a restart (§7.12). The peak census names the burst: the Sharp cohort build held every `manager_seasons` row at once (§7.13) | after this PR deploys, read `prod-heap-report.yml`: no `Row` burst at high RSS, and the `memory.high` counter flat. If a burst remains, read its census and fix that producer; measure `PYTHONMALLOC=malloc` only as a fallback | yes, until production shows the heap staying below `memory.high`: about 6-minute API outages, twice on 2026-11-12 |
| 2 | Signed-in production checks | no production credentials here; the public advisor is disabled | owner signs in and checks `/trade` with 2029 Mid 5th / Mid 6th (no withheld side) once #2190 deploys | no |
| 3 | Owned future picks: browser Mid row vs engine generic row (TC-22) | up to 2.5% on the preliminary meter only; the deferred frontend label-lookup migration | `docs/picks/DERIVED_PICK_QUARANTINE_2026-11-12.md` §Adjacent gap | no |
| 4 | Raw ports from the internet | only probed from this egress | box-side `ss -ltnp` / firewall check by the operator | no |
| 5 | `/api/admin/diagnostics` health half | `_health_content` still on the loop (fast in production) | optional; same pattern if it ever slows | no |

### 7.8 Verdict

**READY WITH ISSUES (one reliability defect open).** Production runs #2189 (`45c25008`, deployed 14:35 UTC): scrapes succeed, health is
`ok`, `/api/status` no longer stalls the site, the new tab titles and diagnostics are live, and every page loads
cleanly. The trade-calculator quarantine defect (WA-19) is merged (#2190) and verified on the merged code with the
latest production export; its live check needs a signed-in session. The open item that matters is WA-17: the
backend's heap still passes `memory.high` under load, and the API was unavailable for about 6 minutes twice on
2026-11-12 (13:27-13:33 and 15:36-15:42 UTC) until the watchdog restarted it (§7.7 #1, §7.10).

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

### 7.10 Second watchdog restart and the memory experiments (WA-17)

**15:42 UTC, from the box journal** (`prod-restart-diagnostics.yml`, read-only, window 15:15-15:45): the same
signature as 13:32. Five liveness failures, a watchdog restart, a SIGKILL after the SIGTERM timeout, and no OOM. Traffic
was 40-85 requests a minute until 15:36. The 2-minute public samples on the #2190 build (`4b47329c`, started 15:19:58)
read: process RSS 1,584 MiB at 15:21 (during the startup scrape) → 1,820 → 2,029 at 15:35; heap 1,983 MiB; `memory.high`
events 465 (15:31) → 1,678 (15:35); `/api/status` no longer answered from 15:37; the process restarted at 15:42:13.

Cycles differ a lot in how fast they grow: 2 minutes after a restart the process held 661 MiB at 14:35 but 1,584-1,658
MiB at 13:32 and 15:20 (the latter two came right after an outage or a deploy, when every open client reconnects).
Today's code changes do not explain it: the 13:32 cycle on the previous build grew the same way.

**Local experiments** (committed board, same code; read-only GETs only):

| Experiment | Result |
|---|---|
| 4 rounds of authenticated GETs over all 103 GET routes | 531 → 761 MiB in round 1 (caches), then 761 / 761 / 761: repeated reads do not grow memory |
| Rankings overrides with distinct inputs | not a factor: custom source weighting is disabled, so every request is served the cached canonical board |
| Cold start + 42 concurrent requests to the 14 heaviest routes | 481 → 889 MiB, and it stays (892 after 20 s) |
| Same burst with `MALLOC_ARENA_MAX=2` | 472 → 754 MiB (754 after 20 s): about a third less growth (one run each) |

Reading: concurrent heavy work grows the heap and keeps it; per-thread glibc arenas account for part of that, and
live memory for the rest. What the production heap holds at 2.8 GB is not attributed yet. Raising the limits or
scheduling restarts would only hide it, so neither is proposed. The next step is attribution on the box (§7.7 #1).

### 7.11 Heap attribution on the box, the arena cap and WA-20 (WA-17)

Owner request, 2026-11-12: cap glibc's arenas and attribute the heap on the production box.

**What ships (this PR):**

| Change | Where | Effect |
|---|---|---|
| `MALLOC_ARENA_MAX=2` | `deploy/systemd/dynasty.service.template` (the reconciler installs it on deploy, before the restart) | glibc keeps at most 2 arenas instead of 8 per core |
| Module executed once (WA-20) | `server.py`: a `__main__` guard after the imports runs the module once, as `server`, and serves that | one copy of every module-level load |
| Heap report | `src/diagnostics/heap_report.py`, `server.py` (`heap_report_loop`, `_record_heap_snapshot`, `box_resources.heap_*`), `src/diagnostics/proc_probe.py` (`memory_headroom_mib`) | box-local log `data/diagnostics/heap_reports.jsonl` (bounded to 2 MB): at start and every 15 min (`HEAP_REPORT_INTERVAL_SEC`); plus a light record (RSS only) before each scrape and after each publish's heap release |
| Read-only reader | `deploy/diagnostics/prod_heap_report.sh`, `.github/workflows/prod-heap-report.yml` (dispatch only) | prints the series and the latest census; re-validates every field, so only numbers and code identifiers reach the job log |

Each snapshot records process RSS; glibc's split of the heap into memory in use, memory freed but retained, mmap and
the arena count (`mallinfo2` / `malloc_info`); the largest module-level containers. Every fourth periodic snapshot
and any periodic snapshot taken at RSS ≥ 1,536 MiB also records a type census (live objects by type)
and a deep census (bytes reachable from each module-level object or class, each counted once). Only the deep census
sees `str` / `bytes` payloads, which the garbage collector does not track. `/api/status` `box_resources` gains
`heap_arenas`, `heap_in_use_mib`, `heap_free_mib`, `heap_mmap_mib` and `heap_age_sec`. These are the last
snapshot's figures, with their age: walking glibc's heap holds its arena locks (about 120 ms on a 3 GB heap), so it
is never done per probe.

The diagnostic must not cause the condition it measures. Its costs, from the independent review:
- The deep census's visited-set costs about 100 MiB per million objects while it runs, so it is bounded at
  1.5 million objects and reports `truncated` when it stops early.
- It is skipped (`deep_skipped: low_headroom`) when the service's anonymous memory is within 512 MiB of
  `memory.high`.
- RSS and the glibc figures are read before the censuses, so a record describes the heap, not the census.
- Neither the heap walk nor a census runs on the scrape path: the scrape-point records hold RSS and the heap
  release result only. The event-loop prober tests (`tests/api/test_run_scraper_*`) failed in CI with the census
  there (0.4 s against a 0.35 s bound) and still failed with the walk alone (1.1 s). On a fragmented heap
  (a million free chunks) one walk takes 0.10 s and blocks any thread that allocates meanwhile. The censuses
  yield the GIL every 10,000 objects.

**Local measurements** (committed board, cold start, then 42 concurrent requests to the 14 heaviest routes):

| Build | RSS ready | RSS after burst |
|---|---|---|
| default arenas, module executed twice (§7.10) | 481 | 889 |
| 2 arenas, module executed twice (2 runs) | 549 / 505 | 736 / 742 |
| 2 arenas, module executed once (2 runs) | 431 / 429 | 690 / 664 |

Attribution of the same burst with 2 arenas, after the fix: the heap held 375 MiB in use at the peak and 167 MiB
in use 30 s later, with 215 MiB freed but retained (56% of the 382 MiB arena heap). 188 MiB is reachable from
module-level objects. The largest are the public-league cache (44 MiB), the contract (19 MiB), the overlay response
cache (17 MiB), the served payload bytes (16 + 9 + 7 + 7 + 6 MiB), the player-impact cache (12 MiB) and the draft
workbook cache (12 MiB). Before the fix, the same census also listed `__main__._public_league_cache` (44 MiB): the
unused second copy (WA-20). The type and deep censuses together take 1.5-2.5 s of a worker thread on this heap.
They are pure Python in the threadpool, so the GIL is shared with the event loop.

Reading, locally: after a burst, most of the heap growth that stays is freed memory glibc keeps, not live objects.
Production may differ, since its heap reached 2.8 GB. The report on the box answers that. A heap release after heavy
request work is the evidence-backed next candidate, decided once the production report is read (§7.7 #1).

**WA-18 verified in production** (#2191, `222379b5`): `box_resources.chromium_processes` read 6 during the startup
scrape's `source_start` (16:07 UTC, 74 service pids) and 0 after it.

### 7.12 Production after #2193: verification and first attribution (WA-17, WA-20)

#2193 merged as `b687d109`; Deploy Production restarted the backend at 18:10:15 UTC. Read with `prod-heap-report.yml`
(runs 1 and 2, read-only) and the public `/api/status`:

| Check | Observation |
|---|---|
| Arena cap | `heap_arenas` 2 on every snapshot |
| WA-20 | the production deep census lists no `__main__` copy |
| Start | RSS 497 MiB at 18:10:50 (earlier processes held 661 and 1,584 MiB about 2 minutes in) |
| Startup scrape | succeeded at 18:15 (Chromium 6, then 0); the post-publish heap release took RSS from 639 to 502 MiB |
| Heap report | records at start, every 15 min, and light records around each scrape; `box_resources.heap_*` carry the last snapshot's figures and their age |
| Throttling | `memory.high` events 0 through 19:17 UTC |

| Record (UTC) | Process | RSS | glibc arena (in use / freed) | glibc mmap | Rest of RSS (RSS - arena - mmap) |
|---|---|---|---|---|---|
| 18:11 startup | 1 | 567 | 261 (163 / 98) | 30 | 276 |
| 18:26, 18:41, 18:56 periodic | 1 | 1,061 (flat) | 376 (209 / 166) | 59 | 626 |
| 19:03 startup | 2 | 521 | 246 (144 / 102) | 30 | 245 |

Process 2 started at 19:02 with the regular data-refresh deploy (`e7493cbe`), before process 1's first hourly census.

Reading: a burst of requests right after the restart (18:17, clients reconnecting) took RSS from 509 to 920 MiB, and
it settled at 1,061 MiB.
- glibc's arena and mmap together grew 144 MiB (291 → 435). Of that, 68 MiB is memory glibc keeps after it is
  freed (98 → 166), about half.
- The rest of RSS grew 350 MiB (276 → 626). That part is outside glibc's accounting: Python's own small-object
  allocator (which takes memory straight from the kernel and returns an arena only when it is completely empty),
  thread stacks and mapped code. These records predate the anonymous / file split, so this column still includes
  file-backed memory; the reader's `o_anon` column (below) excludes it.

So the arena cap and `malloc_trim` act on the smaller part of the climb. At startup, 135-171 MiB is reachable from
module-level objects. The largest are the contract (25 MiB), the served payload bytes (about 58 MiB), the startup
data (16 MiB), the public-league cache (8-44 MiB) and Game Day's player cache (9 MiB).

#2194 then added anonymous and file-backed RSS to every snapshot. The reader prints `o_anon` (anonymous RSS minus
glibc's arena and mmap) and Python's allocated block count. `o_anon` is an approximation: glibc's arena figure is
address space it obtained, not only resident pages. After `malloc_trim` returns pages, the arena figure can stay the
same, so `o_anon` can read low or even negative.

**The split, read in production** (`prod-heap-report.yml` run 3, process `935ce654`, 20:09-20:51 UTC, restarted by the
next data-refresh deploy):

| Record (UTC) | RSS | anon | glibc arena (in use / freed) | mmap | `o_anon` | Python blocks |
|---|---|---|---|---|---|---|
| 20:10 startup | 558 | 536 | 235 (201 / 33) | 30 | 271 | 4.05 M |
| 20:14 after scrape and release | 481 | 449 | — | — | — | 2.70 M |
| 20:25 periodic | 1,190 | 1,145 | 470 (231 / 239) | 59 | 616 | 8.83 M |
| 20:40 periodic | 1,207 | 1,161 | 470 (232 / 238) | 59 | 632 | 8.85 M |

From startup to the plateau (+632 MiB RSS):

- **Live Python objects, about 345 MiB.** `o_anon` grew by 345 MiB, and Python's allocated block count by 4.8 million
  (about 75 bytes each, consistent with it). Fifteen minutes later both were unchanged: these objects are still
  referenced, not freed memory Python keeps. Something holds them, most likely caches filled by the burst.
- **Freed glibc heap, about 206 MiB** (33 → 239). This is what `malloc_trim` returns; each post-scrape release in
  production did (580 → 481, 586 → 490, 639 → 502, 569 → 430).
- glibc in use +30 MiB, glibc mmap +29, file-backed +23.

Why the census did not name the objects: it runs on the hourly tick or at RSS ≥ 1,536 MiB. Production restarts the
backend with each data-refresh deploy (every 40-60 min), and the plateau sat at 1,060-1,210 MiB, so neither fired.

**This PR:**
- Census trigger lowered to RSS ≥ 1,024 MiB (`HEAP_REPORT_HIGH_RSS_MIB`).
- The reader's census, container and growth sections follow the process with the highest RSS in the window, so a
  restart no longer hides the climb. Its container growth then reads from records already in the log.
- Periodic heap release: when a snapshot finds ≥ 128 MiB of freed glibc heap (`HEAP_RELEASE_FREE_MIB`, 0 disables),
  the loop returns it with the scrape's own `_release_freed_heap` and logs a light `periodic_trim` record (RSS before
  and after). Expected effect: about 200 MiB less RSS on the plateau. It frees nothing in use. The Python part still
  needs the caches named.

**The peak, read in production** (`prod-heap-report.yml` run 4, process `ab0b5a39`, started 20:51 UTC; the census at
RSS ≥ 1,536 MiB fired under the old trigger):

| Record (UTC) | RSS | anon | glibc in use / freed | `o_anon` | Python blocks | Tracked objects |
|---|---|---|---|---|---|---|
| 20:52 startup | 535 | 507 | 162 / 74 | 241 | 3.47 M | 410 k |
| 21:07 periodic, high RSS | 2,151 | 2,105 | 242 / 175 | 1,629 | about 22.6 M | 2.12 M |
| 21:22 periodic, high RSS | 1,779 | 1,734 | 208 / 209 | 1,258 | 4.32 M | 636 k |

- **The peak is a burst of about 19 million Python objects**, 1.7 M of them containers, live at the same moment.
  It took RSS to 2,151 MiB (anonymous 2,105), within about 400 MiB of `memory.high`. `/api/status` showed 2,799
  `memory.high` events at 21:27. That counter is cumulative over the service's cgroup, so it shows the service was
  throttled again, most likely around this peak, but does not time each event. This time it recovered without a
  restart. The deep census was correctly skipped at 21:07 (headroom 454 MiB < 512).
- **After the burst, Python's allocator kept about 1 GB.** By 21:22 the block count was back near startup (4.3 M
  against 3.5 M), but `o_anon` stayed at 1,258 MiB (241 at startup). Python's small-object allocator returns an
  arena to the kernel only when every block in it is free, so a burst leaves most of its arenas resident. The
  glibc arena cap and `malloc_trim` cannot reach this memory.
- The live caches after the burst are small by comparison: the overlay response cache +50 MiB, player impact +12,
  draft workbook +12, BDVM context and values +20, public contract bytes +7 (deep census at 21:22).

The 21:07 event is consistent with the earlier outages being driven by the same mechanism: a request burst that
briefly builds millions of extra objects (about 19 M more than at startup; 22.6 M in total). The 13:32 and 15:42
restarts predate this report, so they are not shown to be bursts. The memory a burst leaves behind in Python's
allocator stays resident until the next restart, and the next burst starts from that level. This PR makes the
reader print the census taken at the peak, which lists the types the 19 M objects belong to and so points to the code
that built them. That producer is the fix; `PYTHONMALLOC=malloc` is the fallback to measure (§7.7 #1).

### 7.13 The burst's producer: the Sharp cohort build (WA-17)

`prod-heap-report.yml` run 5 (after #2196) printed the census taken at the 21:07:42 peak (process `ab0b5a39`,
2,116,187 tracked objects):

| Type | Count at the peak |
|---|---|
| `sqlite3.Row` | 1,138,004 (52.1 MiB for the row objects alone) |
| `list` | 373,568 |
| `dict` | 138,650 |
| `set` | 66,192 |
| `EvidenceStatus` | 53,124 |
| `ManagerRecord` | 38,573 |

In the server process, `EvidenceStatus` and `ManagerRecord` are built only by
`src/sharp/platform_records.py::build_manager_records` (the other `ManagerRecord` builder, `src/sharp/records.py`,
runs in the records-crawl script), and it is the code that holds `sqlite3.Row` objects next to them. It ran one query over `manager_seasons` (joined to `platform_managers`)
and called `fetchall()`, so every season row in the ledger was alive at once: 1,138,004 rows, each with its own
tuple and about 15 new column values (strings, floats, large integers). Column values are not tracked by the
garbage collector, so the census counts 2.1 M objects while Python's block count was about 22.6 M; the rows
account for the difference (1.14 M x about 18 objects is about 20 M). It then built one `EvidenceStatus` per
manager (53,124) and one `ManagerRecord` per scoreable manager (38,573).

Every Sharp surface reaches it through `cohort.cohort_members` (memoized on the ledger file's
`mtime_ns:size`), and `/api/sharp/cohort`, the curated cohort and the coverage helpers call it directly. Each
restart empties the memo, and every ledger write (the Sharp crawl timers) invalidates it, so the full build runs
again on the next Sharp request. That fits bursts shortly after a restart, but the request that triggered the
21:07 build is not recorded.

**This PR:**
- **Stream and fold.** `build_manager_records` reads the two small per-manager aggregates first, then iterates the
  cursor and folds each eligible row into per-manager running totals (seasons, leagues, wins / losses / ties,
  playoffs, titles, finish percentiles). No row is kept, so memory scales with managers (about 53 k), not rows.
  The query, its row order and the outputs are unchanged.
- **One build at a time per key.** Concurrent cache misses in `cohort_members` wait for the first computation
  and take its result, instead of each building its own copy.

Evidence (`tests/sharp/test_platform_records_streaming.py`):
- Parity: on seeded ledgers that reach every exclusion reason (identity, incomplete, ineligible, missing results,
  stored reasons, FFPC without recent activity, one-team leagues), the streamed builder returns exactly what the
  retired algorithm (kept verbatim in the test as the oracle) returns: same records in the same order, same
  evidence.
- Memory: on a 15,000-row ledger (100 managers x 150 seasons) the traced peak fell from 12.7 MB to 1.06 MB
  (11.9x). The retired build held about 850 bytes per row there; at 1.14 M rows that is about 920 MiB, consistent
  with the burst (`o_anon` +1,388 MiB at the peak, which also includes everything else live at that moment).
- Single-flight: six concurrent misses run one computation, and a failed computation does not block the next
  caller. The concurrency test fails without the change.

Expected in production: the next high-RSS census shows no `Row` burst, the `memory.high` counter stops rising, and
Python's allocator no longer keeps about 1 GB after a build. Production verification follows the deploy.
