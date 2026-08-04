# Audit Protocol — read this before producing any finding

This file is the shared contract for every workstream in the master site audit.
It exists so 26 independent agents produce one mergeable, falsifiable document
instead of 26 essays.

## The stack is RUNNING. Use it.

| | |
|---|---|
| Backend | `http://127.0.0.1:8000` — FastAPI, booted from `data/dynasty_data_2026-08-04.json` (1,074 raw players → 1,092-row contract) |
| Pages | `http://127.0.0.1:3000` — Next.js 16.2.12 production build. **Read the topology rule below before loading any page in a browser.** |

### ⚠ Browser page loads MUST re-route `/api/*` to the backend

`deploy/nginx/chaseupside-proxy.conf` routes `location /api/` to FastAPI and
`location /` to Next. Next itself has only **36 bridge routes for 100 backend
routes**, so a browser pointed straight at `:3000` gets a **Next 404 that production
never produces** for `/api/health`, `/api/leagues`, `/api/user/state`,
`/api/terminal`, `/api/movers`, `/api/data/rank-history`, `/api/ros/player-values`
and more.

**Do it with Playwright request interception** — the browser keeps talking to Next
for pages, and only `/api/*` is redirected:

```python
async def route(r):
    u = r.request.url
    if "/api/" in u and u.startswith("http://127.0.0.1:3000"):
        await r.continue_(url=u.replace("http://127.0.0.1:3000", "http://127.0.0.1:8000"))
    else:
        await r.continue_()
await ctx.route("**/*", route)
```

Measured proof that this is the only method that works — same two pages, three ways:

| method | `/rankings` HTML | `<h1>` | table rows |
|---|---|---|---|
| plain `:3000` | large, but **222 console errors / 261 failed requests** across 41 pages | present | present |
| hand-rolled HTTP proxy on `:3001` | **5,895 b — dead pre-hydration shell** | `None` | **0** |
| **request interception (use this)** | **593,422 b** | `Rankings` | **230** |

A hand-rolled proxy was tried and **abandoned**: it returns byte-identical HTML on
curl yet the app never hydrates behind it. `evidence/page-probe-direct-next-INVALID.json`
and `evidence/page-probe-via-proxy-INVALID.json` are both retained and both invalid.
**Any page-level observation not taken through request interception is void** — in
particular the `[dynasty-data] buildRows … zero backend rank stamps` console error and
the mass of 404s in the first capture are topology artifacts, not product defects.
| Repo | `/home/user/riskittogetthebrisket`, branch `claude/fantasy-football-master-audit-umvex5`, HEAD `e96c06ef` |
| Python | `.venv/bin/python` (3.11.15 — note CI uses 3.12; stamp this on any test-derived claim) |
| Session secret | `/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/e2e_secret.txt` |

Mint an authenticated cookie (the API 401s anonymously on most routes):

```bash
SECRET=$(cat /tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/e2e_secret.txt)
curl -s -c /tmp/audit-cookies.txt -X POST http://127.0.0.1:8000/api/test/create-session \
  -H "Authorization: Bearer $SECRET"
curl -s -b /tmp/audit-cookies.txt "http://127.0.0.1:8000/api/data?view=app" | head -c 400
```

The test user is `e2e-test-user` and is deliberately **not** in the admin
allowlist, so `/api/admin/*` returns 403 for it. That is correct behavior, not a
finding.

## READ-ONLY. Non-negotiable.

- **Never** call `POST /api/scrape`, and never run `Dynasty Scraper.py` or any
  `scripts/fetch_*.py` / `scripts/crawl_*.py`. `run_scraper` is monkeypatched to a
  no-op in the running server; do not undo that.
- **Never** modify a tracked file. The only writes allowed are under
  `docs/master-site-audit/` and the scratchpad.
- Outbound network: read-only `GET` to `api.sleeper.app` is permitted. Nothing else.
- Prefer GET probes. A POST route may be probed with a realistic body **only** if
  it is a pure read (`/api/trade/*`, `/api/angle/*`, `/api/waiver/*`,
  `/api/rankings/overrides` are computation endpoints and safe). Do not POST to
  `/api/user/*`, `/api/custom-alerts`, `/api/admin/*`, `/api/*/refresh`, or
  `/api/*/run`.

## Pre-declared NON-FINDINGS

These are artifacts of the audit harness or documented deliberate design. Reporting
one as a defect gets the finding rejected. If you believe one is genuinely a defect
*in production*, you must prove it with deploy-side evidence, not container state.

| Observation | Why it is not a finding here |
|---|---|
| `/api/health` returns 503 "degraded" | `last_success_at` is null because the startup scrape is suppressed by the audit harness. `tests/e2e/global-setup.js` documents this exact trap. |
| Most `/api/*` return 401 anonymously | Correct auth behavior. Only report a route that leaks data it shouldn't. |
| `/api/consensus-edge/*` returns 503 | `consensus_edge` flag defaults **off** per ADR-023 (`docs/consensus-edge/DECISIONS.md`). Reachability is the claim to test, not the 503. |
| `/api/intel/*` returns 503 | `data/intel/` and the platform ledger DB do not exist in this container → **Blocked by data**, not Missing. |
| `/api/bdvm/*` may report no projection snapshot | `data/bdvm/` does not exist in this container → **Blocked by data**. |
| `nfl_data_py` is not importable | Deliberately excluded from `requirements.txt` (documented in-file). The `nflverse_direct` fallback is the live path. |
| `data/dynasty_data_2026-08-04.json` was seeded from `exports/latest/` | `tests/e2e/preflight.py` is the sanctioned mechanism; a clean checkout has no `data/` snapshot by design. |
| `npm` warns `EBADENGINE` (node 22 vs `>=20 <21`) | Container toolchain, not repo state. Worth one note, not a per-workstream finding. |
| `Sleeper API ... Connection reset by peer` in the backend log | Container egress behavior. Only report the *code's handling* of the failure (does it degrade honestly or fabricate?), never the failure itself. |
| 404s on `/api/*` when a page is loaded from **:3000** | Wrong topology — see the warning above. Re-measure on :3001. Production's nginx routes `/api/` to the backend. |
| `buildRows received a payload with zero backend rank stamps` in the browser console on :3000 | Downstream of the same artifact: the data fetch 404'd, so the materializer correctly hit its fail-fast path. Only a finding if it reproduces on :3001. |
| `sleepercdn.com` avatar images failing | External CDN is not reachable from this container. |

## Status vocabulary — use these EXACT strings

`Implemented and verified` · `Implemented but defective` · `Implemented but disconnected` ·
`Partially implemented` · `Scaffolded only` · `Reference-only` · `Mocked or hard-coded` ·
`Missing` · `Blocked by data` · `Blocked by credentials or licensing` ·
`Deprecated but still active` · `Duplicate or conflicting implementation` · `Unverifiable`

Three distinctions that will otherwise be got wrong at scale:

- **Missing** — no code exists.
- **Scaffolded only** — code exists and is never called by anything reachable.
- **Blocked by data** — code exists, IS called, and returns empty/degraded because an
  input file or directory is absent. **Name the exact absent path.**

And: `Implemented and verified` requires a reproduction command that you ran and that
passed. A positive claim with no runtime proof is `Unverifiable`, not verified.

## Finding record schema (emit JSONL, one object per line)

```json
{
  "id": "W09-F003",
  "workstream": "W09",
  "promptSections": [14, 15],
  "title": "one sentence, specific, falsifiable",
  "status": "<exact label from the vocabulary>",
  "priority": "P0|P1|P2|P3",
  "size": "XS|S|M|L|XL",
  "subsystem": "Trade finder",
  "surface": {"routes": ["/api/trade/finder"], "pages": ["/arbitrage"], "flags": []},
  "codeRefs": [{"path": "src/trade/finder.py", "lines": "412-437"}],
  "claimUnderTest": "what the docs/code claim",
  "observed": "what actually happens",
  "reproduction": {
    "command": "exact shell command another person can re-run",
    "expected": "...", "actual": "...",
    "artifact": "docs/master-site-audit/evidence/W09/finder-scale.json"
  },
  "numericProof": {"inputs": {}, "formula": "", "expected": 0, "actual": 0, "tolerance": 0},
  "userImpact": "what a user does wrong because of this",
  "blastRadius": {"playersAffected": 0, "routesAffected": 0, "pagesAffected": 0},
  "confidence": "high|medium|low",
  "priorFinding": {"match": "PRIOR-A14-F07|null",
                   "relation": "confirmed|refuted|not-reproducible|superseded|new|partial",
                   "note": ""},
  "whatWorks": "", "rootCause": "", "requiredRepair": "", "dependencies": ""
}
```

Rules the merge step enforces:

1. Every finding needs a `reproduction.command` that a reader can re-run. Evidence that
   is only a code comment, a doc, or a prior audit's assertion is not evidence.
2. Every numeric claim needs `numericProof` with inputs, formula and tolerance.
3. **P0 is reserved for**: a user acts on a wrong number today, on a page they can reach,
   with no warning shown. Name the page, the number, and the wrong action. Everything
   else is P1 or lower.
4. Severity without `blastRadius` is rejected.
5. Do your OWN analysis first. Only then open your slice of `evidence/prior-index.json`
   and assign `priorFinding.relation`. Paraphrasing a prior finding is not a finding.

## Prior-audit cross-reference

`docs/master-site-audit/evidence/prior-index.json` holds all **531** findings from
`docs/audits/decision-intelligence-audit-2026-08-04.md` (26 areas, 807 systems, 562
formulas), given deterministic IDs `PRIOR-A{area}-F{finding}` — the source registry has
no IDs of its own. That audit is a **claim set, not evidence**. Reproduce or refute;
never inherit.

## Shared evidence already captured

| Artifact | What it is |
|---|---|
| `evidence/openapi.json` | 100 live route operations from the running app (authoritative census — grep misses the 2 imperatively-registered sharp routes) |
| `evidence/route-probe.json` | Every GET route, anon + authenticated: status, latency, bytes, payload shape |
| `evidence/page-probe.json` | Every Next page in a real browser, anon + authenticated: status, redirects, console errors, failed requests, timings |
| `evidence/prior-index.json` | The 531 prior findings with synthetic IDs |
| `evidence/pytest-full.txt` | Full Python suite run |
| `evidence/vitest.txt` | Frontend suite: 104 files / 1,754 tests, all passing |
| `evidence/frontend-build.txt` | Production Next build + bundle-budget gate |
| `evidence/source-corpus-mtimes-BEFORE.txt` | mtimes of `exports/`, `CSVs/`, `data/raw*` — re-checked at the end to prove the audit wrote nothing |

## If you write a `.py` evidence script, it must pass the repo's lint gates

`pyproject.toml`'s `[tool.ruff] extend-exclude` covers `data`, `exports`, `.next`,
`node_modules`, `frontend` and the frozen BDVM reference — **not `docs/`**. So a
throwaway script under `docs/master-site-audit/evidence/` is held to the same standard
as production code, and `pr-validation.yml` runs `ruff format --check .` and
`ruff check .` as **whole-repo blocking** gates. The audit's own first push failed both.

Before you finish, run:

```bash
.venv/bin/python -m ruff format docs/master-site-audit/
.venv/bin/python -m ruff check --fix docs/master-site-audit/
```

Do **not** propose widening the exclude list — that is a production config change this
audit is not permitted to make.

## Repo-local skills

`.agents/skills/` contains audit methodologies written for this codebase. Read the one
matching your workstream before starting: `value-pipeline-auditor`,
`reality-check-review`, `blueprint-auditor`, `performance-optimizer`, `scraper-ops`,
`design-taste-director`.
