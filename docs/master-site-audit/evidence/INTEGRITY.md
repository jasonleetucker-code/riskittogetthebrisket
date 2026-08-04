# Audit integrity record — what this audit did and did not touch

Written so a reader can check the audit's own read-only claim rather than take it.

## Verified untouched

| Corpus | Check | Result |
|---|---|---|
| `exports/`, `CSVs/`, `data/raw/`, `data/raw_sources/` — 2,686 files | mtime+size snapshot before vs after | **byte-identical**, `evidence/source-corpus-mtimes-BEFORE.txt` |
| All git-tracked files | `git status --porcelain` | clean apart from `docs/master-site-audit/` |
| Third-party scraping targets (KTC, IDPTradeCalculator, DLF, FantasyPros, …) | `run_scraper` monkeypatched to a recording no-op before uvicorn started | **1 suppression logged (`trigger='startup'`), 0 scrape-target hosts contacted** |

## Written, deliberately

- `.venv/`, `frontend/node_modules/` — gitignored toolchain.
- `data/dynasty_data_2026-08-04.json` — seeded from `exports/latest/` by the repo's own
  `tests/e2e/preflight.py`, which exists for exactly this case.
- `docs/master-site-audit/` — the audit itself.

## Written as a side effect of running the server — disclosed, not hidden

Booting the backend is what produced most of this audit's evidence, and a running server
writes runtime state. All of it is under gitignored `data/` and none of it is production:

| Path | What happened |
|---|---|
| `data/snapshots/ranks_last.json` | **Rewritten by ordinary `/rankings` page loads.** This is not incidental — it *is* finding W03-F010: `POST /api/rankings/overrides` writes the shared canonical rank snapshot whenever `source_overrides` normalizes to empty, which the stock frontend body does. The audit reproduced the defect by browsing. |
| `data/intel/ledger.sqlite3` (+ `.pre-platform-v2-auto.bak`) | **Created by the server on first use.** Note this corrects a premise given to workstream W16: the intel ledger file did not exist at audit start but does now. `/api/intel/*` still answers `503 data_not_ready`, so the block is on *content* (no crawl has run), not on the file. |
| `data/public_league/{snapshot,contract,identity,nfl_players}.json` | Public-league warmup thread, triggered at boot as designed. |
| `data/nfl_data_cache/`, `data/league_comparison_cache/` | Response caches populated by the audit's own route probes. |
| `data/session_store.sqlite`, `data/validation/` | Session persistence and the contract validator run by preflight. |

## Measurement corrections made mid-audit

Recording these because an audit that silently fixes its own bad measurements is not
auditable either.

1. **Page probe topology.** The first page sweep loaded pages from Next directly on
   `:3000`. Production's nginx (`deploy/nginx/chaseupside-proxy.conf`) routes `/api/` to
   the backend, and Next has only 36 bridge routes for 100 backend routes — so that sweep
   recorded 314 resource 404s and a `buildRows … zero backend rank stamps` console error
   that **production never produces**. The capture is retained as
   `page-probe-direct-next-INVALID.json` and superseded by `page-probe-via-proxy.json`,
   taken through an nginx-equivalent edge proxy on `:3001`. Any page-level finding
   measured on `:3000` is invalid.
2. **`_finalAdjusted` in the arbitrage finder.** An early read suggested `src/trade/finder.py`
   still prices assets off the raw scraper composite, contradicting CLAUDE.md. Reading the
   surrounding branch showed the primary path reads `board_values_from_contract` and the
   `_finalAdjusted` reads sit in an explicit legacy `else:` branch plus a deliberate
   composite-scale counter. Recorded as **partial/refuted for the live path** (W00-F006)
   rather than as the defect it first appeared to be.
3. **Latency vs settle time.** The page probe's `settleMs` hit its own 25 s `networkidle`
   ceiling on 41 of 41 pages, which is a property of the probe, not the pages. Real
   DOM-ready time is `navMs` — median 68 ms, max 695 ms. No page-load finding cites
   `settleMs`.

## Toolchain divergence from CI

Stamped on every test-derived claim: this container runs **Python 3.11.15** (CI and
`.python-version` pin **3.12**) and **Node 22.22.2** (`frontend/package.json` requires
`>=20 <21`; `npm ci` emits `EBADENGINE`). `/usr/bin/python3.12` and `/opt/node20` are both
present, so a re-run on the CI toolchain is possible and would be the first thing to do
before treating any test result as conclusive.
