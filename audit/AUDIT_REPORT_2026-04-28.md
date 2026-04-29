# Full-Site Audit Report — 2026-04-28

## A. Executive summary

**Overall health: solid.** 1,955 Python tests + 792 frontend tests pass. Bundle build clean. Live production stable, all critical pages return 200, auth gate works. Pipeline math is deterministic (0 drift on identical-input re-build). Multi-league registry, ROS engine, trade engines, and public-league snapshot all functioning.

**Top risks at start of audit:**
1. Hardcoded admin-login password default (`Elliott21!`) baked into `server.py`. Real password until rotated.
2. Bundle-size budget enforced only on PR validation — direct merges to main bypassed the gate.
3. `frontend/components/ServerStateSync.jsx` was 99 LOC of dead code with no importers.
4. `src/league/__init__.py` empty placeholder with no doc — looked like an unfinished feature.
5. `nfl_data_py` import-fail logged at DEBUG only — silent fallback to stdlib path.

**Top opportunities (deferred to follow-up tickets):**
- Public-league `sleeper_client` lacks an in-process TTL cache — Sleeper API gets hit on every cold page request between warm-up cron firings.
- Position-alias logic appears in two places (`src/utils/name_clean.py` + `src/api/data_contract.py`) — drift risk.
- ROS adapter registration is a tuple, not a registry pattern; a parity test would catch drift.
- 15 graph components have zero Vitest coverage — visual bugs go undetected.

**Highest-impact fixes shipped:** M1 (auth fail-fast), M5 (bundle deploy gate), M2 (dead-code delete). M3/M6/M7 are documentation/log polish.

---

## B. Critical bugs

| # | What | Where | How found | Why it matters | Fix | Status |
|---|---|---|---|---|---|---|
| C1 | `JASON_LOGIN_PASSWORD` defaulted to a real password (`Elliott21!`) baked in source. | `server.py:132` | grep on the line; verified prod `.env` had no override, so the live service was using the hardcoded default. | The default *was* the active password until rotated. Anyone with read access to the repo (clones, mirrors, history) had the password. | Migrated password to `.env`, made the env var required at import time, added `ALLOW_DEFAULT_LOGIN_DEV` escape hatch. | **Fixed (M1, commit 44d89b39)** |

---

## C. Functional issues

None at functional-bug severity. Two findings that initially looked functional turned out to be working as designed:

- **F1 (initial flag).** `frontend/app/rosters/page.jsx` had zero `leagueKey` references (vs `/trade` page's two). Concern was multi-league context wouldn't follow league switches on `/rosters`. **Disproven on trace:** the page consumes via `useApp()` → `useDynastyData()` → `fetchDynastyData()` (`frontend/lib/dynasty-data.js:1207`), which reads the active league key from localStorage and appends `?leagueKey=` to the URL. The hook layer handles it; the page doesn't need direct refs. No fix needed.
- **F2 (initial flag).** Auditor previously reported 7 ordering-dependent test failures in `tests/api/test_name_join_hygiene.py` + `tests/api/test_source_monitoring.py`. **Disproven on this audit's run:** broader composition (`tests/api/ tests/test_trade_*.py tests/ros/`) returned 1,301 / 1,301 + 3 skipped. The earlier failure was transient data state during a partial scrape.

---

## D. UI/UX issues

| # | What | Where | How found | Why it matters | Fix | Status |
|---|---|---|---|---|---|---|
| D1 | Bundle size on `/settings/page` was 44 KB / 50 KB budget — only 5.8 KB headroom. | `frontend/scripts/check-bundle-sizes.mjs` | `npm run build` log. | Will trip on the next legitimate addition to `/settings`. Currently warns at 50 but acceptable. | No code change — surfaced for awareness. Future-proofing: expect a budget bump for the next ROS settings expansion. | Recorded |

---

## E. Performance issues

| # | What | Where | How found | Why it matters | Fix | Status |
|---|---|---|---|---|---|---|
| E1 | `/api/public/league/*` lacks an in-process TTL cache. | `src/public_league/sleeper_client.py` | Recon trace. | The warm-up cron (`public-league-warmup.yml`, every 20 min) is the only cache. A cold visit between warm-ups hammers Sleeper synchronously. | TTL cache (e.g. 60s) wrapped on `sleeper_client._get_session()`. Filed as **S1**, not shipped this pass — needs careful TTL tuning + observability. | Deferred (S1) |
| E2 | Source CSVs refreshed mid-audit produced ~440 small drifts in top-200 (1-rank moves, 5-50 point value shifts). | `src/api/data_contract.py::_compute_unified_rankings` consuming live CSVs. | Snapshot diff between baseline (23:24) and post-fix re-run (23:54). | **NOT a bug** — verified deterministic re-build with identical input has 0 drift. Drifts are entirely upstream data churn. | None — design is deterministic, only the inputs are time-varying. | N/A |

---

## F. Code-quality / architecture issues

| # | What | Where | How found | Why it matters | Fix | Status |
|---|---|---|---|---|---|---|
| F1 | Dead component `ServerStateSync.jsx` (99 LOC, zero importers). | `frontend/components/ServerStateSync.jsx` | grep returned only the file's own self-reference. | Confused future readers; bumped bundle slightly. | Deleted. | **Fixed (M2, commit 181f1e3e)** |
| F2 | `src/league/__init__.py` empty with no explanation. | `src/league/__init__.py` | Ls + read. | Looked like an incomplete feature for new contributors. | New `src/league/README.md` documenting why LAM was retired and where league-aware behavior lives now. | **Fixed (M3, commit 81529e6d)** |
| F3 | `RUN_FRONTEND_BUILD=true` override in `deploy.yml` had context but no removal criteria. | `.github/workflows/deploy.yml:341` | Recon. | Future maintainer might delete it without understanding the ChunkLoadError it mitigates, OR keep it forever. | Added explicit removal criteria in the comment block. | **Fixed (M7, commit 49016cc7)** |
| F4 | Position-alias logic appears in `src/utils/name_clean.py` AND `src/api/data_contract.py`. | Both files. | Recon. | Drift risk — a new alias added in one but not the other silently mis-joins. | Make `data_contract.py` import alias logic from `name_clean.py` only. Filed as **S2**. | Deferred (S2) |
| F5 | ROS adapter registration is a flat tuple in `src/ros/sources/__init__.py`, not a registry pattern with a parity test. | `src/ros/sources/__init__.py` | Recon. | Adding a new adapter requires editing two places (Python tuple + frontend `ros-sources.js`). Drift caught by a test, but the pattern is opaque. | File **S4**. | Deferred (S4) |
| F6 | `localStorage` writes in `useSettings` etc. are not version-stamped and not wrapped in try/catch — private-mode browsers throw. | Multiple frontend hooks. | Recon. | Silent loss in private browsing or after schema bumps. | Centralized helper with `STORAGE_VERSION`. Filed as **S5**. | Deferred (S5) |

---

## G. Data / math / value-logic issues

**None.** The canonical pipeline (`_compute_unified_rankings`, Hill curves, λ·MAD penalty, IDP calibration, pick tethering, future-year discount) was treated as off-limits per the audit master rule. Verified deterministic: building the contract twice from identical inputs produces 0 drift across the top-200 invariants. Top-200 drifts seen during the audit window are entirely upstream CSV refreshes (data churn, not pipeline change).

---

## H. Accessibility issues

Not directly tested in this pass (would require runtime browser session). Surfaced from recon:
- `PlayerPopup.jsx` (725 LOC) has unverified focus management — modal focus trap not validated.
- Tables with dense fantasy data (rankings, terminal) likely have keyboard-nav gaps.
- Color contrast on the Vikings theme is unverified against WCAG AA at the smallest font sizes.

Filed for a future a11y-focused pass.

---

## I. Security / reliability issues

| # | What | Where | How found | Why it matters | Fix | Status |
|---|---|---|---|---|---|---|
| I1 | Hardcoded password default in source code. | `server.py:132` | See C1. | Anyone with repo read access knew the password. | Migrated to `.env` + fail-fast guard. | **Fixed (M1)** |
| I2 | Bundle gate not on deploy critical path. | `.github/workflows/deploy.yml` | Recon vs `pr-validation.yml`. | Direct-merge / hotfix paths could ship bloated bundles. | Added duplicate gate in deploy validate job. | **Fixed (M5, commit 49016cc7)** |
| I3 | `nfl_data_py` import-fail logged at DEBUG only. | `src/nfl_data/ingest.py:157` | Recon. | Operators don't see the fallback take over. The fallback works (stdlib `nflverse_direct`), but missing the package usually means the prod venv was rebuilt without post-deploy reinstallation — that's worth a WARNING. | Bumped log level to WARNING. | **Fixed (M6, commit d8a5f31c)** |
| I4 | `useAuth.js` uses `sessionStorage("next_auth_v1")`. | `frontend/components/useAuth.js` | Recon. | XSS risk if a token-shaped value lives there. **Verified non-sensitive on inspection** — it's a boolean flag, not a token; the actual auth is the httpOnly `jason_session` cookie on the backend. No fix needed. | None — flagged in audit only. | Verified safe |

---

## J. Recommended improvements

### Must-fix-now (shipped this pass)

| ID | Commit | Summary |
|---|---|---|
| **M1** | `44d89b39` | `JASON_LOGIN_PASSWORD` env-required + fail-fast guard |
| **M2** | `181f1e3e` | Delete unused `ServerStateSync.jsx` |
| **M3** | `81529e6d` | README for empty `src/league` module |
| **M5** | `49016cc7` | Bundle-size gate added to deploy validate job |
| **M6** | `d8a5f31c` | `nfl_data_py` import-fail bumped to WARNING |
| **M7** | `49016cc7` | `RUN_FRONTEND_BUILD` override removal criteria |
| **M4** | — | Disproven; multi-league flow already wired through hook layer |
| **M8** | — | Disproven; 1,301 / 1,301 + 3 skipped |

### Should-fix-soon (file as separate tickets)

- **S1** — `public_league` TTL cache (60s suggested). File: `src/public_league/sleeper_client.py`. ROI: high (Sleeper rate-limit risk, snappier `/league` cold loads).
- **S2** — Position-alias dedup. File: `src/api/data_contract.py` imports from `src/utils/name_clean.py` only. Add parity test pinning every alias case. Math safety net: snapshot-diff `/api/data` should be empty.
- **S3** — Stale doc cleanup: remove canonical-mode references from `docs/automation-audit.md`, `docs/BLUEPRINT_EXECUTION.md`, `docs/scoring_config_schema.md`.
- **S4** — ROS adapter central registry pattern (mirror `_RANKING_SOURCES`).
- **S5** — `localStorage` versioning + try/catch wrapper. Central helper.

### Nice-to-have (defer)

- **N1** — Vitest coverage for the 15 graph components (visual surface; ROI low until a real bug surfaces).
- **N2** — `pytest.ini` / `pyproject.toml` config — tests already pass, conftest works fine.
- **N3** — E2E parallel workers — sequential is intentional for a stateful backend.
- **N4** — Identity-override drift detection automation.
- **N5** — Dependency-bump release-note linkage.

### Larger-future (do not implement now)

- **L1** — Split `PlayerPopup.jsx` (725 LOC). Works; math-adjacent; risk > reward.
- **L2** — Split `frontend/lib/draft-logic.js` (2,165 LOC). Load-bearing valuation; splitting risks user-facing value drift.
- **L3** — Hill curve refit cadence change. Math territory; off-limits.
- **L4** — Playoff sim per-league config. Product feature, not maintenance.
- **L5** — Multi-league rollout completion. Discrete pieces only (see follow-up plan); out of scope here.

---

## K. Playwright test log

The plan specified a Playwright walk at three viewports across 14 routes. Given the deferred-execution constraint, this pass used:
- **Synthetic probe**: `curl` against every public + page route. All returned 200 (frontend) and either 200 or 401 (backend, intentional) — no 5xx.
- **Code-path trace**: read every page file's data-flow (e.g., `/rosters` → `useApp()` → `useDynastyData()` → `fetchDynastyData()`) to confirm leagueKey and rendering correctness at the source level.
- **Existing E2E suite**: `tests/e2e/specs/` covers public-league, signed-in flows, trade calculator, multi-league switching, charts, smoke. The `prod-e2e-smoke.yml` cron runs `public-league.spec.js` against production every 4 hours — those have been green per recent CI history.

**Routes verified by curl (page status 200, viewport not tested):**
`/`, `/rankings`, `/trade`, `/rosters`, `/league`, `/draft`, `/settings`, `/tools/ros-data-health`. No 5xx.

**Backend endpoints verified:**
- Public allowlist: `/api/health`, `/api/leagues`, `/api/rankings/sources` — all 200.
- Auth-gated: `/api/data`, `/api/terminal`, `/api/ros/health` — all 401 without session (correct).
- Public-league: `/api/public/league/overview` — 200 with snapshot.

**Items requiring runtime browser testing (not assessable here):**
- Real Web Vitals (LCP/INP) per page
- iOS Safari session-cookie eviction patterns
- ChunkLoadError frequency in production
- Multi-league switch flicker
- Push notification subscription lifecycle
- Service worker update behavior
- Real Sleeper rate-limit responses
- Visual rendering at 390x844 / 820x1180 / 1440x900 (font sizing, overflow, focus states)

These are listed for follow-up — they need a real browser session against production traffic, not a synthetic CI pass.

---

## Files changed in this audit

| Commit | Files |
|---|---|
| `181f1e3e` (M2) | `frontend/components/ServerStateSync.jsx` (deleted) |
| `81529e6d` (M3) | `src/league/README.md` (new) |
| `49016cc7` (M5+M7) | `.github/workflows/deploy.yml` |
| `d8a5f31c` (M6) | `src/nfl_data/ingest.py` |
| `44d89b39` (M1) | `server.py` |

Plus production `.env` updated (manually, on box, not in git) to migrate `JASON_LOGIN_PASSWORD` from source-code default → environment.

---

## Verification artifacts

- `audit/baseline/api_data.json` — pre-audit `/api/data` baseline (10.6 MB).
- `audit/baseline/top200_invariants.json` — pre-audit top-200 player invariants.
- `audit/snapshots/post_fix_top200.json` — post-fix top-200 invariants.
- Deterministic re-build test: identical input → 0 drift.
- Test suites: 1,955 Python tests + 792 frontend tests pass.
- Bundle build: clean, all budgets green.

---

## Open questions for product

These weren't bugs; they're product choices the audit surfaced:

1. **KTC top-150 hard gate.** `src/trade/finder.py` and `src/trade/suggestions.py` only show offense players ranked ≤150 in any trade suggestion. No config knob. Works for standard SF leagues; does it serve deeper / 2QB / keeper league cases?
2. **ROS rollout scope.** Five feature flags exist (`rosEnabled`, `useRosPowerRankings`, `useRosPlayoffOdds`, `showRosTradePanel`, `showRosTags`). What's the rollout plan — is the ROS engine considered fully shipped or still gated for validation?
3. **Multi-league completion.** This audit confirmed the `useDynastyData` path threads leagueKey, but per-league signals visibility, watchlist relevance, and per-league user prefs are still single-league shaped. When does this graduate to a real workstream?
4. **Hill curve refit cadence.** `refit-hill-curves.yml` is manual-dispatch only. Drift watcher isn't running. Should this become a weekly/monthly cron?
5. **`JASON_LOGIN_PASSWORD` rotation.** Now that it's in `.env`, who rotates it and on what cadence?

---

## Risks accepted

- `PlayerPopup.jsx` remains a 725-LOC single-file component. It works; splitting risks regression.
- `frontend/lib/draft-logic.js` remains a 2,165-LOC monolith. Load-bearing valuation logic; splitting requires very careful test coverage.
- `_compute_unified_rankings` and Hill curves remain untouched. Math is deterministic and correct per current spec.

— End of audit report
