# Evidence Log

Every measurement in this audit, the command that produced it, and where the raw output
lives. If a claim elsewhere in `docs/master-site-audit/` is not traceable to something on
this page or to a `file:line`, treat it as unsupported.

- Repo: `/home/user/riskittogetthebrisket`, branch `claude/fantasy-football-master-audit-umvex5`
- Audited commit: `e96c06ef` (audit artifacts committed on top of it)
- Dates: 2026-08-04 / 2026-08-05 UTC

## Why this audit could measure things the previous ones could not

The 2026-08-04 decision-intelligence audit states its own residual gap plainly: *"no running
server, no production filesystem, no `pytest`, and no historical data."* Every prior audit in
this repository is static analysis. This one starts by removing that constraint.

| | Prior audits | This audit |
|---|---|---|
| Backend running | no | yes, :8000, seeded contract, 1,092 rows |
| Frontend running | no | yes, :3000, production build |
| `pytest` | not installed | full suite executed |
| Live API responses | none | all 100 route operations probed |
| Browser page loads | none | all 41 pages, anon + authenticated |

## The harness

### Bring-up (mirrors `.github/workflows/e2e.yml`, which does this in CI)

```bash
bash scripts/setup.sh                       # .venv from requirements-dev.txt
npm install --no-audit --no-fund            # root Playwright harness
npm --prefix frontend ci --no-audit --no-fund
npm run regression:preflight                # seeds data/ from exports/latest, validates contract
npm --prefix frontend run build             # production build + bundle-size gate
```

`tests/e2e/preflight.py` is the repo's own sanctioned seed: a clean checkout has no
`data/dynasty_data_*.json`, which is what `server.py::load_from_disk` (`server.py:2065`) boots
from. It validated and seeded `data/dynasty_data_2026-08-04.json` (1,074 raw players), which
`build_api_data_contract` expands to a 1,092-row contract.

### Backend, with the scrape neutralised

`server.py`'s lifespan (`server.py:2568`) unconditionally fires `initial_scrape()` three seconds
after boot, and `schedule_loop()` every two hours. Both resolve `run_scraper` from module
globals at call time, so replacing that global before `uvicorn.run` is a complete interception.
The launcher lives outside the repo (scratchpad, `audit_launcher.py`) and is never imported by
production code:

```python
import server
async def _no_scrape(trigger="manual"):
    print(f"[audit-launcher] SUPPRESSED scrape attempt (trigger={trigger!r})")
    return server.latest_data
server.run_scraper = _no_scrape
uvicorn.run(server.app, host="127.0.0.1", port=server.PORT)
```

Launched with CI's environment belt (`UPTIME_CHECK_ENABLED=false`, `ALLOW_DEFAULT_LOGIN_DEV=1`,
`E2E_TEST_MODE=1`, `E2E_TEST_USERNAME=e2e-test-user`, `E2E_TEST_SECRET=$(openssl rand -hex 24)`,
`RATE_LIMIT_BYPASS_IPS=127.0.0.1`, `PLAYWRIGHT_BROWSERS_PATH=/tmp/no-pw-browsers` as a second
line of defence — the scraper's first network action is a browser launch).

**Proof the suppression held**: the backend log carries exactly one
`[audit-launcher] SUPPRESSED scrape attempt (trigger='startup')` per boot and no
scraping-target hostname. Readiness is `/api/status` reporting `has_data: true` — deliberately
not `/api/health`, which stays 503 "degraded" precisely because the scrape never ran.

**Proof the audit wrote nothing**: `evidence/source-corpus-mtimes-BEFORE.txt` records 2,686
file mtimes and sizes across `exports/`, `CSVs/`, `data/raw` and `data/raw_sources`, re-checked
at the end. `git status` carries nothing but `docs/master-site-audit/`.

### The topology correction

The first page capture was wrong, and the correction is worth stating because it would have
produced a large number of false findings.

`deploy/nginx/chaseupside-proxy.conf` routes `location /api/` to FastAPI and `location /` to
Next. Next has bridge routes for only **36 of the 100** backend operations. A browser pointed
straight at `:3000` therefore 404s on `/api/health`, `/api/leagues`, `/api/user/state`,
`/api/terminal`, `/api/movers` and more — 404s **production never produces**. The fix is
Playwright request interception, redirecting only `/api/*` to `:8000`.

Same two pages, three ways:

| method | `/rankings` HTML | `<h1>` | table rows |
|---|---|---|---|
| plain `:3000` | 222 console errors / 261 failed requests across 41 pages | present | present |
| hand-rolled HTTP proxy on `:3001` | 5,895 b — dead pre-hydration shell | `None` | 0 |
| **request interception** | **593,422 b** | `Rankings` | **230** |

The two invalid captures are retained as `evidence/page-probe-direct-next-INVALID.json` and
`evidence/page-probe-via-proxy-INVALID.json` rather than deleted. The
`buildRows … zero backend rank stamps` console error and the mass of 404s in the first capture
are artifacts of the wrong topology, and `AUDIT_PROTOCOL.md` pre-declares them as non-findings
so no workstream could report them as defects.

## Measurements

| Artifact | What it holds | How to re-run |
|---|---|---|
| `evidence/openapi.json` | 100 live route operations, 97 unique paths, from the running app | `curl -s localhost:8000/openapi.json` |
| `evidence/route-probe.json` | Every GET/HEAD route, anonymous and authenticated: status, latency, bytes, payload shape | `scratchpad/probe_routes.py` |
| `evidence/page-probe.json` | All 41 pages in Chromium, anon + auth, through request interception | `scratchpad/probe_pages.py` |
| `evidence/pytest-full.txt` | **6,278 passed, 40 skipped, 0 failed, 496 subtests, 1,929.98 s** | `.venv/bin/python -m pytest tests/ -q --tb=short -rf` |
| `evidence/vitest.txt` | **104 files, 1,754 tests, 0 failed, 32.38 s** | `npm --prefix frontend test` |
| `evidence/frontend-build.txt` | Production build; all 14 measured page bundles under budget | `npm --prefix frontend run build` |
| `evidence/perf/api-data-payload-sizes.txt` | `/api/data` 11,953,535 b raw / 1,176,182 b gzip; `?view=app` 5,818,304; `?view=compact` 7,363,760 | see the file header |
| `evidence/test-results-summary.txt` | Both suites plus the static skip-marker census | — |
| `evidence/prior-index.json` | The 531 prior findings with synthetic ids | `tools/build_prior_index.py` |
| `evidence/registry/*.jsonl` | 31 workstream shards, 432 raw findings | — |
| `evidence/verify/verdicts-*.jsonl` | Adversarial verification verdicts | — |
| `findings.json` | The merged, validated, verdict-corrected registry | `tools/merge_registry.py` |
| `FEATURE_STATUS_MATRIX.md` | Generated per-requirement matrix | `tools/build_matrix.py` |

Toolchain caveat, stamped on every test-derived claim: the suites ran on **Python 3.11.15**
while `.python-version` and CI pin **3.12**, and on **Node 22.22.2** while `frontend/package.json`
pins `>=20 <21` (`npm` warns `EBADENGINE`). Both are container facts, not repo defects.

## Method

31 workstreams covering brief sections 3–45, each required to trace the live execution path,
prove claims against the running stack, and only afterwards open its slice of the prior-audit
index to assign a relation. All findings use one closed status vocabulary and one JSON schema,
validated at merge: **0 schema violations across 432 records**, and every record carries a
re-runnable reproduction command.

### Adversarial verification

Findings are proposals until something tries to kill them. The highest-impact findings went to
independent refuters — batched across workstreams so no verifier reviewed one author's set —
instructed to default to refuted when uncertain and to check the inferential step, not just the
number.

Wave 1, 24 findings: **5 upheld · 18 rescoped · 1 overturned.** Severity drift: 4× P0→P1,
1× P0→P2, 4× P1→P2, 2× P1→P3. `merge_registry.py` applies the verifier's corrected priority
over the author's and keeps `authoredPriority` beside it, so the correction is visible rather
than laundered.

That an 18-in-24 rescope rate exists is itself a finding about the method: unverified audit
severities in this codebase — including, by implication, those of its predecessors — run hot.

### The refuted finding

`W04-F001` claimed, in agreement with the prior audit's second systemic claim, that the
benchmark grading the Hill curves is not independent of the boards it grades, because all four
"held-out" boards are registered live blend sources. The reproduction was correct; the
conclusion was not. `src/model_registry/holdout.py:251-265` loads each holdout board's raw CSV,
converts it to (percentile, value) pairs, and takes the RMSE of the candidate curve against
*that source's own published value shape*. It never reads the blended board. A curve that
reproduces FantasyCalc's shape translates FantasyCalc's rank vote more faithfully, not more
circularly — and the overfitting the gate exists to catch stays detectable regardless of
registry membership.

It publishes with `published: false` and the argument that killed it. Deleting a refuted
finding would repeat exactly the documentation-drift failure this audit reports.

## What could not be measured here, and what would settle it

| Gap | Consequence | What unblocks it |
|---|---|---|
| `data/bdvm/` absent | BDVM numeric correctness is **Blocked by data**; reachability and isolation were still provable | run `scripts/bdvm_build_baseline.py` on a host with nflverse access |
| `data/intel/` and the platform ledger DB absent | Insider Trading numeric claims **Blocked by data** | the intel refresh on a host with the ledger |
| No sharp roster/records database | Sharp cohort denominators **Blocked by data** | the three staggered sharp crawls |
| No historical snapshot store | No claim of model validation is reproducible — see `HISTORICAL_DATA_GAPS.md` | a snapshot store, which does not exist today |
| Production host, systemd, secrets | Every deploy-side claim is static-only | deployment access |
| Rate limiting | Bypassed on the shared stack by `RATE_LIMIT_BYPASS_IPS` | a separate un-bypassed backend, which `SECURITY_AUDIT.md` used |
| iOS/webkit viewports | Mobile coverage is Chromium-only | webkit browsers, not installed |

Two external calls were made beyond the sanctioned Sleeper reads, and both are disclosed rather
than buried: `GET /api/news` triggered the backend's own news fetch (which logged
`news provider fantasypros raised: HTTP Error 404`), and `/api/draft-capital` attempted a
Sleeper lookup for team names that the container reset. Both are read-only GETs made by the
application under test, not by the audit directly.
