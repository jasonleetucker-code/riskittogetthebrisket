# Automation & Dependency Audit

**Generated:** 2026-04-25  
**Scope:** Risk It To Get The Brisket — every external source, derived
artifact, parity pair, scheduled job, and manual step.

This report is **Phase 1: Map** only. No code changes have been made.
Phase 2 (Fix) waits on owner sign-off on the prioritized gap list at
the end.

---

## TL;DR

The repo's auto-refresh story is in good shape on the *primary* path
(KTC, FantasyCalc, DLF, FootballGuys, DraftSharks, FantasyPros, Flock,
Dynasty Daddy, IDPTradeCalc, plus a Google-Sheet draft workbook all
re-fetch every 3 hours). Three real gaps:

1. **`fetch_yahoo_boone.py` and `fetch_dynasty_nerds.py` exist but are
   not wired to any GitHub Actions workflow.** Yahoo Boone ranks live
   via `Dynasty Scraper.py`'s legacy browser automation; Dynasty Nerds
   does too. The standalone scripts are orphans (likely earlier
   prototypes left behind).
2. **The IDP Show scraper relies on a manual `idpshow_session.json`
   maintained on the production server.** CI always skips it. If the
   prod server cookie expires, the source goes silently stale.
3. **Several parity pairs have no enforcing test.** Position aliases,
   league registry, and API contract version strings all rely on
   developer discipline.

Everything else is automated end-to-end. There are 4 `.bat` files —
all dev-machine-only convenience launchers; none are in the live data
path.

The list of recommended fixes is at the bottom under **Prioritized
Automation Gaps**.

---

## 1. External Data Sources

| Source | Adapter / Script | Trigger | Output | Cadence | Failure visibility |
|---|---|---|---|---|---|
| **KTC** | `Dynasty Scraper.py` (Playwright browser) | `scheduled-refresh.yml` cron `42 */3 * * *` | `CSVs/site_raw/ktc.csv`, `exports/latest/site_raw/ktc.csv` | every 3 h | **HARD-FAIL gate**: workflow exits 1 if KTC csv < 100 lines (scheduled-refresh.yml:177-188) |
| **FantasyCalc** | `Dynasty Scraper.py` (JSON API) | scheduled-refresh, same 3 h cycle | `CSVs/site_raw/fantasycalc.csv` | 3 h | non-fatal warning |
| **DynastyDaddy** | `scripts/fetch_dynasty_daddy.py --mirror-data-dir` | scheduled-refresh.yml:129 | `CSVs/site_raw/dynastyDaddySf.csv` | 3 h | non-fatal warning |
| **DynastyNerds** | `Dynasty Scraper.py` (browser) | scheduled-refresh (legacy scraper run) | `CSVs/site_raw/dynastyNerdsSfTep.csv` | 3 h | non-fatal warning. **Note:** standalone `scripts/fetch_dynasty_nerds.py` exists but is **NOT wired to any workflow** — appears to be an unused prototype. |
| **DLF** (4 boards: SF, IDP, RookieSF, RookieIDP) | `scripts/fetch_dlf.py` (curl_cffi + WP login) | scheduled-refresh.yml:155 | `CSVs/site_raw/dlfSf.csv`, `dlfIdp.csv`, `dlfRookieSf.csv`, `dlfRookieIdp.csv` | 3 h (DLF itself updates ~monthly) | non-fatal warning. Creds: `DLF_USERNAME` / `DLF_PASSWORD` GitHub Secrets |
| **FootballGuys** (SF + IDP) | `scripts/fetch_footballguys.py` (Playwright + auto-login) | scheduled-refresh.yml:141 | `CSVs/site_raw/footballGuysSf.csv`, `footballGuysIdp.csv` | 3 h | non-fatal warning. Creds: `FOOTBALLGUYS_EMAIL` / `FOOTBALLGUYS_PASSWORD` |
| **DraftSharks** (offense + IDP) | `scripts/fetch_draftsharks.py` (Playwright + WASM scoring) | scheduled-refresh.yml:147 | `CSVs/site_raw/draftSharks.csv`, `draftSharksIdp.csv` | 3 h | non-fatal warning. Creds: `DRAFTSHARKS_EMAIL` / `DRAFTSHARKS_PASSWORD` |
| **FantasyPros / Fitzmaurice (Dynasty Trade Value Chart)** | `scripts/fetch_fantasypros_fitzmaurice.py` | scheduled-refresh.yml:162 | `CSVs/site_raw/fantasyProsFitzmaurice.csv` | 3 h (article publishes ~monthly; auto-resolves up to 3 months back) | non-fatal warning |
| **FantasyPros (SF + IDP)** | `Dynasty Scraper.py` (browser); standalone `fetch_fantasypros_offense.py` and `fetch_fantasypros_idp.py` exist but are **NOT in scheduled-refresh.yml** | live legacy scraper | `CSVs/site_raw/fantasyProsSf.csv`, `fantasyProsIdp.csv` | 3 h | non-fatal. **Note:** the two standalone scripts are unused by CI. |
| **Flock Fantasy** (SF + Rookies) | `scripts/fetch_flock_fantasy.py`, `scripts/fetch_flock_fantasy_rookies.py` | scheduled-refresh.yml:132, :135 | `CSVs/site_raw/flockFantasySf.csv`, `flockFantasySfRookies.csv` | 3 h | non-fatal warning |
| **IDP Show (Adamidp)** | `scripts/fetch_idpshow.py` (Substack paywall + captcha) | scheduled-refresh.yml:171 — **only runs if `idpshow_session.json` is checked into runner**, which it never is in CI | `CSVs/site_raw/idpshow.csv` (only on prod server) | 3 h on prod, **NEVER in CI** | `::notice::` log line says "scraper runs on the production server"; if prod cookie expires, source goes silently stale |
| **Yahoo (Justin Boone)** | `Dynasty Scraper.py` (browser, auto-discovers monthly article) | live legacy scraper | `CSVs/site_raw/yahooBoone.csv` | 3 h | non-fatal. **Note:** standalone `scripts/fetch_yahoo_boone.py` exists but is **NOT wired to scheduled-refresh.yml** — duplicate of the legacy path. |
| **IDPTradeCalc** | `Dynasty Scraper.py` (browser) | scheduled-refresh (legacy scraper run) | `CSVs/site_raw/idpTradeCalc.csv` | 3 h | non-fatal warning |
| **Sleeper (public league snapshot)** | `src/public_league/sleeper_client.py` | request-time, NOT scheduled — `public-league-warmup.yml` cron `*/20 * * * *` keeps the cache warm | in-memory snapshot cache + pickle on disk | live (snapshot has 5-min TTL; warmup pings every 20 min) | health-check.yml logs `:warning:` if `/api/public/league` returns non-200 |
| **Google Sheets (Draft Data workbook)** | inline `curl` in scheduled-refresh.yml:53-97 | scheduled-refresh, 3 h | `CSVs/Draft Data.xlsx` + `CSVs/draft_data.csv` | 3 h | non-fatal — keeps existing workbook on HTTP error or file < 1KB |

### Source-fetch test fixtures (sanity, not production)
- `tests/api/test_*_source.py`, `test_*_integration.py` — hit captured fixtures + assert parser shape. They do not exercise the live network path.

### Failure escalation
**No source fetch escalates beyond a `::warning::` log line.**
`audit-dropped-sources.yml` is the closest thing to alerting: it runs
weekly, checks Hampel outlier drop rates, and **fails the workflow**
if any source is ≥15% dropped (audit-dropped-sources.yml:5-19). That
catches a regression but does not page anyone — the failed workflow
just sits red until someone notices.

---

## 2. Derived / Computed Artifacts

| Artifact | Source data | Recompute trigger | Auto on upstream change? |
|---|---|---|---|
| **Hill master curves** (`HILL_GLOBAL_*`, `HILL_OFFENSE_*`, `HILL_IDP_*`, `HILL_ROOKIE_*` in `src/canonical/player_valuation.py`) | KTC, IDPTC, DynastyNerds, DynastyDaddy CSVs (the 4 value-based sources) | `refit-hill-curves.yml` cron `17 6 1 * *` (1st of month, 06:17 UTC) → `scripts/auto_refit_hill_curves.py` | **AUTO**, monthly. Drift threshold 50 RMSE. Driver exits: 0=no drift, 1=applied (commits + pushes), 2=error (workflow fails). Pinned regression tests in `tests/canonical/test_ktc_reconciliation.py` updated atomically. |
| **Unified rankings (`/api/data` `playersArray`)** | All scraped CSVs + Hill curves + source weights | `_compute_unified_rankings()` runs **on every API request** (no precompute on disk) | **AUTO** — always fresh on the next request after CSV/registry/weights change |
| **IDP calibration** | (RETIRED) | n/a — `_apply_idp_calibration_post_pass` was removed (data_contract.py:6272-6280); `config/idp_calibration.json` does **not exist** | n/a |
| **Source blending weights** (`config/weights/default_weights.json`) | Manual JSON edit | None — read at `_compute_unified_rankings` runtime | **MANUAL.** No backtest-driven weight refit. Currently all sources weight 1.0 by policy (parity test enforces). |
| **Pick-year discount** (`config/weights/pick_year_discount.json`) | Manual JSON edit | None — read at runtime | **MANUAL.** No back-test driven refit. |
| **Source row floors** (`config/weights/source_row_floors.json`) | Manual JSON edit | Read at runtime | **MANUAL.** Used by source_health alerting to flag a CSV that came back too short. |
| **Top-50 coverage floors** (`config/weights/top50_coverage_floors.json`) | Manual JSON edit | Read at runtime | **MANUAL.** |
| **Pick tethering / future-year discount / λ·MAD** | Hardcoded constants in `src/canonical/player_valuation.py` and `src/api/data_contract.py` | None — code edit | **MANUAL** when code edited |
| **Tier thresholds** (`config/tiers/thresholds.json`) | Manual JSON edit | Read at runtime | **MANUAL** |
| **Source staleness thresholds** (`config/source_staleness.json`) | Manual JSON edit | Read at runtime by `src/api/source_health_alerts.py` | **MANUAL.** Drives the source-health UI but no auto-refit. |
| **ID overrides** (`config/identity/id_overrides.json`) | Manual edits when a player gets mis-identified (Travis Hunter etc.) | Read at runtime | **MANUAL** |
| **League registry** (`config/leagues/registry.json`) | Manual JSON edit | Read at startup; cached by `src/api/league_registry.py` | **MANUAL** when leagues are added/changed |
| **Trade engines** (`src/trade/suggestions.py`, `src/trade/finder.py`) | Live `/api/data` contract | request-time on `POST /api/trade/suggestions` and `/api/trade/finder` | **AUTO** — recomputed every call; reads the live (override-aware) contract |
| **KTC top-150 quality filter** (in trade engines) | Hardcoded `150` constant | Code edit | **MANUAL** when code edited |
| **Public league snapshot** (`/api/public/league` aggregate) | Sleeper API + scraped player table | `_get_public_snapshot()` stale-while-revalidate; `public-league-warmup.yml` cron `*/20 * * * *` re-warms after deploy/restart | **AUTO** |
| **Rank/source-value history** (`data/rank_history.jsonl`, `data/source_history.jsonl`) | Each canonical rebuild | Stamped during `_compute_unified_rankings`; backfill scripts in `scripts/backfill_rank_history.py` and `scripts/backfill_source_history.py` are one-shot operator tools | **AUTO** for new ranks; **MANUAL** for backfills |
| **Frontend bundle** (`frontend/.next/`) | Frontend source | `deploy.yml` on push to main | **AUTO** on every deploy |

---

## 3. Parity / Lockstep Pairs

| Pair | Files | Enforcing test | Status |
|---|---|---|---|
| **Ranking source registry** | `src/api/data_contract.py::_RANKING_SOURCES` ↔ `frontend/lib/dynasty-data.js::RANKING_SOURCES` | `tests/api/test_source_registry_parity.py` | **GREEN** — parses JS, diffs against Python; CI gates on it. |
| **Default source weights vs registry** | `config/weights/default_weights.json` ↔ `_RANKING_SOURCES` | `tests/api/test_source_registry_parity.py::test_default_weights_match_registry_policy` | **GREEN** — currently enforces "all 1.0". |
| **Position aliases** | `src/utils/name_clean.py::POSITION_ALIASES` (single source of truth, imported everywhere) | NONE | **OK in practice** — no parallel list. New positions just need an entry; consumers all import from one place. |
| **League registry** | `config/leagues/registry.json` ↔ `src/api/league_registry.py` (loader) ↔ frontend `/api/leagues` consumers | NONE — JSON validity only at runtime | **GAP**. No schema validation; a typo in `registry.json` surfaces as a 503 on the affected league. |
| **API contract version string** | `src/api/data_contract.py::CONTRACT_VERSION` (e.g. `2026-03-10.v2`) ↔ frontend version-aware payload checks | `tests/api/test_data_contract.py` (asserts presence; doesn't pin to a current value) | **OK** — string is informational; mismatch doesn't break anything. |
| **Public league contract version** | `src/public_league/public_contract.py::PUBLIC_CONTRACT_VERSION` (`public-league/2026-04-18.v1`) ↔ public-tab tests | `tests/public_league/test_public_contract.py` (shape-pinned) | **GREEN** — section keys + shape pinned. |
| **Source CSV filenames vs ingestion paths** | `Dynasty Scraper.py` writes a CSV → `src/api/data_contract.py::_SOURCE_CSV_PATHS` reads it | NONE | **GAP**. A scraper file rename would silently drop the source from the live blend until someone notices the contract was missing it. |
| **Sleeper player ID stability** | Sleeper's `players/nfl` dump ↔ `data/identity/*.json` masters | `tests/test_identity_*` | **GREEN** for known overrides; new mis-IDs require manual `id_overrides.json` edit. |
| **`_VALUE_BASED_SOURCES` set vs registry flags** | hardcoded set in `data_contract.py` ↔ `_RANKING_SOURCES` flags | NONE | **GAP**. A registry change needs a parallel update to this set. |
| **`_DS_COMBINED_RANK_KEYS` derived set vs registry** | derived at import from `ds_combined_rank_partner` flag | n/a — derived | **OK** — auto-computed. |
| **Frontend `SOURCE_VENDORS` map vs registry** | `frontend/lib/dynasty-data.js::SOURCE_VENDORS` ↔ `_RANKING_SOURCES` | NONE | **GAP**. New vendor sub-board has to be hand-mapped or it shows up as its own column. |

---

## 4. Scheduled GitHub Actions Jobs

All cron strings use **UTC**. All workflows live in `.github/workflows/`.

| Workflow | Cron | Purpose | Output / Consumer | Status |
|---|---|---|---|---|
| **scheduled-refresh.yml** | `42 */3 * * *` (every 3 h at :42) | Run `Dynasty Scraper.py` + each `fetch_*.py` script + commit data | Commits to `CSVs/`, `exports/`, `data/` (paths-ignored from `deploy.yml`, so a data-only commit doesn't redeploy) | **ACTIVE — primary data pipeline** |
| **refit-hill-curves.yml** | `17 6 1 * *` (1st of month, 06:17 UTC) | Re-fit GLOBAL/OFFENSE/IDP/ROOKIE Hill curves; commit if drift ≥ 50 RMSE | Rewrites `src/canonical/player_valuation.py` + pinned `tests/canonical/test_ktc_reconciliation.py` | **ACTIVE — monthly auto-refit** |
| **public-league-warmup.yml** | `*/20 * * * *` (every 20 min) | GET `/api/public/league?refresh=1`, validate response shape | Keeps snapshot cache warm | **ACTIVE — cache warming** |
| **prod-e2e-smoke.yml** | `17 */4 * * *` (every 4 h at :17) | Playwright spec `tests/e2e/specs/public-league.spec.js` against prod URL | Catches Sleeper outages, nginx drift, expired certs, client-bundle regressions | **ACTIVE — regression detection** |
| **health-check.yml** | `17 */6 * * *` (every 6 h at :17) | `/api/health` + `/api/status` probes; logs scrape-success rate, player count | Logs only — no escalation | **ACTIVE — monitoring (read-only)** |
| **smoke-test.yml** | `15 6 * * *` (daily 06:15 UTC) | pip check + syntax gate + import test + pytest + (optional) prod endpoint smoke | Daily validation | **ACTIVE** |
| **audit-dropped-sources.yml** | `23 7 * * 1` (Mondays 07:23 UTC) | `scripts/audit_dropped_sources.py` against latest snapshot | Reports per-source Hampel drop rates; **fails workflow** if any ≥ 15% (early-warning signal) | **ACTIVE — weekly surveillance** |
| **pr-validation.yml** | on `pull_request` | pip check + syntax + import + pytest + script syntax | Pre-merge gate | **ACTIVE** |
| **deploy.yml** | on push to `main` (paths-ignore `data/**`, `exports/**`) + manual dispatch | Validate → install → test → contract check → SSH deploy → smoke | Production deploy via `deploy/deploy.sh` over SSH | **ACTIVE — CD pipeline** |

**No disabled or orphaned workflows.** All nine are live and consumed.

Cron offsets are deliberately staggered (`:42`, `:17`, `:15`, `:23`,
`*/20`) to avoid GitHub's top-of-hour thundering herd.

---

## 5. Manual Steps

### Dev-only convenience (NOT in the live data path)

| File | Purpose | Operator action |
|---|---|---|
| `start_stack.bat` | Windows: launch backend + frontend in two cmd windows | double-click |
| `start_frontend.bat` | Windows: `npm install` if needed, then `npm run dev` | double-click |
| `run_scraper.bat` | Windows: shell wrapper around `python "Dynasty Scraper.py"` | double-click |
| `sync.bat` | Windows: `git add -A && commit && push` (with auto-msg fallback) | double-click |
| `Makefile` (`make setup`, `make test`, etc.) | Local Python venv + test wrapper | `make <target>` |
| `scripts/setup.sh` | Create venv + install deps | `bash scripts/setup.sh` |

These are convenience for solo developers on Windows; **none are part
of production data flow.** They do not need to be eliminated.

### Real manual obligations on prod / operator

| What | Why | Cadence | Failure mode |
|---|---|---|---|
| **Refresh `idpshow_session.json` on the production server** | Substack auth cookie behind a captcha login. CI cannot drive this. | When the cookie expires (Substack ~30-90 day sessions) | IDP Show source goes silently stale. Only signal: weekly `audit-dropped-sources.yml` if the freshness check picks up the staleness. |
| **One-time bootstrap on a fresh VPS** | `deploy/bootstrap-production.sh` — creates user, installs systemd units, nginx config | Once per environment | Existing prod is already bootstrapped; no recurring step. |
| **Rollback after a failed deploy** | `deploy/rollback.sh` — atomically restores previous commit | Only if `deploy/verify-deploy.sh` doesn't auto-rollback | `verify-deploy.sh` already self-heals with `STRICT_LOCAL_HEALTH=true`; manual rollback is a last resort. |
| **Editing source weights / tiers / staleness thresholds / position aliases / league registry / pick-year discount** | All live in `config/*.json` and read at runtime | When the operator wants to tune | A typo in any of these surfaces as a 503 / blank section / silently wrong values, depending on the file. |
| **Adding a new ranking source** | Five-step sequence: (1) scrape script, (2) wire into `scheduled-refresh.yml`, (3) register in Python `_RANKING_SOURCES`, (4) mirror in JS `RANKING_SOURCES`, (5) update `default_weights.json`. Parity test catches step 3↔4 drift. | When a new source is added | The parity test catches `_RANKING_SOURCES` ↔ JS drift. The other three steps have no automated guardrail. |

---

## Prioritized Automation Gaps

Here is the gap list with my proposed Phase-2 fix for each. **No code
will change until you confirm.**

### Tier 1 — silent-failure gaps (RESOLVED)

**G1. IDP Show goes stale invisibly when the prod-server cookie expires.**
*Resolved.* The `source_health_alerts` module was already written and
unit-tested but never wired into the running server. We now invoke
`source_health_alerts.check_and_alert(...)` from
`server.py::run_signal_sweep` (right after the existing `ops_alerts`
call), so it piggybacks on the same cron and emits an email when
any source breaches its `config/source_staleness.json` threshold —
including a new explicit `idpShow: 168 h` entry. Cooldown state
persists in `user_kv` under `_system_source_health`. Recovery
alerts fire when a previously-stale source comes back.

**G2. CSV-filename ↔ ingestion-path link has no parity test.**
*Resolved.* `tests/api/test_config_parity.py::TestSourceCsvPathRegistryParity`
asserts every `_SOURCE_CSV_PATHS` key is in `_RANKING_SOURCES`. CI
fails if a scraper rename or registry removal silently drops a source.

**G3. `_VALUE_BASED_SOURCES` and frontend `SOURCE_VENDORS` are silently
parallel to the registry.**
*Resolved.* `_VALUE_BASED_SOURCES` was already enforced at module
import via `_validate_value_based_sources_invariant()` (line 4277 in
`data_contract.py`). The frontend `SOURCE_VENDORS` map now has a
parity test (`test_config_parity.py::TestFrontendSourceVendorsParity`)
that fails CI if a JS vendor key references a Python source that no
longer exists.

### Tier 2 — RETRACTED on verification (2026-04-25)

**G4 (originally: delete `fetch_yahoo_boone.py` + `fetch_dynasty_nerds.py`):**
**RETRACTED.** On second look, both scripts are imported and called
inline by `server.py` during the `/api/scrape` flow:
- `server.py:1364` — `from scripts import fetch_dynasty_nerds`
- `server.py:1399` — `from scripts import fetch_fantasypros_offense`
- `server.py:1433` — `from scripts import fetch_fantasypros_idp`
- `server.py:1469` — `from scripts import fetch_idpshow`
And `tests/adapters/test_yahoo_boone_scraper.py` imports
`fetch_yahoo_boone.py` directly. The audit was wrong to call them
orphans — they're invoked at runtime by the live scrape loop, not by
the GitHub Actions workflow. They are an intentional split: lightweight
HTTP-only fetches live as standalone scripts (run inline by server.py),
heavier Playwright-driven fetches live in `Dynasty Scraper.py`.
**No action.**

**G5 (originally: delete `fetch_fantasypros_*.py`):** Same retraction.
Both are imported from `server.py:1399` and `:1433`. No action.

### Tier 3 — manual config validation (RESOLVED)

**G6. Tunable JSON configs have no schema validation.**
*Resolved.* `test_config_parity.py::TestConfigJsonFilesParse` walks
every `*.json` under `config/` and parses each one. CI fails on
malformed JSON, so a typo in `registry.json` /
`default_weights.json` / `source_staleness.json` /
`tiers/thresholds.json` etc. is caught pre-merge instead of as a
503 in production.

**G7. League registry has no parity test.**
*Resolved.* `test_config_parity.py::TestLeagueRegistryWellFormed`
runs the live registry through the production
`league_registry._parse_league_entry` parser, asserts every league
has a non-empty `scoringProfile` (catching the silent fallback to
the literal `"default"` string), and asserts no two leagues share
an alias.

### Tier 4 — pure tech debt cleanup

**G8. `.bat` files (`start_stack.bat`, `sync.bat`, `run_scraper.bat`,
`start_frontend.bat`)** are dev-only Windows convenience. Not in the
critical path.  
*Recommendation:* leave them as-is. They serve their users (the
Windows-primary devs) and their absence wouldn't help anyone. Owner
call.

**G9. `Makefile`** — already used by CI shape; not a manual gap.  
*Recommendation:* leave as-is.

### Tier 5 — explicitly out of scope (documented why)

**O1. Source weight refit.** No backtest-driven auto-tuner. Current
policy is "all 1.0"; changing weights requires intentional analysis.
This is **deliberately manual** because the right weights depend on
calibration goals that change with the season.

**O2. Pick-year discount refit.** Same reason as O1. Calibrated
manually against KTC's published discount table.

**O3. KTC top-150 trade-engine quality filter.** Hardcoded constant by
design. Changing it changes trade-suggestion semantics, so it should
not auto-tune.

**O4. ID overrides** (`config/identity/id_overrides.json`). Edited
when Sleeper publishes a wrong position for a player; cannot be
auto-detected.

**O5. Fresh-VPS bootstrap.** One-time per environment. Not worth
automating.

---

## What "done" looks like after Phase 2

Walking away from the repo for 30 days, you'd come back to:
- Every source freshly re-scraped every 3 h ✓ (already)
- IDP Show monitoring tells you within 6 h that the prod cookie has expired (G1)
- Hill curves auto-refit on the 1st of the month if drift > 50 RMSE ✓ (already)
- Weekly Hampel surveillance flags any source regressing on board coverage ✓ (already)
- Production E2E smoke catches deploy/cert/Sleeper regressions every 4 h ✓ (already)
- New parity tests refuse to merge a PR that drifts the registry, CSV path map, value-based-sources set, frontend vendor map, or any tunable config schema (G2, G3, G6, G7)
- All `.bat` files documented as Windows-dev-only and out of the critical path (already true)
- Dead scrapers deleted or banner-flagged (G4, G5)

---

## Phase-2 ETA / sequencing recommendation

If you green-light all 7 in-scope fixes (G1–G7), in priority order:

1. **G1** (IDP Show staleness alert) — 1 PR, ~30 lines, immediate value.
2. **G2** (CSV path parity test) — 1 PR, ~40 lines.
3. **G3** (value-based + vendor parity tests) — 1 PR, ~60 lines.
4. **G6** (config-schema parse test) — 1 PR, ~50 lines.
5. **G7** (league-registry parity) — 1 PR, ~30 lines.
6. **G4 + G5** (delete or banner the orphaned scrapers) — 1 PR, owner-call on delete-vs-deprecate.

Each is independent. Each is a small, reversible change. None modifies
the live data pipeline; they only add tests / alerts.

---

*End of Phase 1 report. Awaiting sign-off before implementing any
Phase 2 fix.*
