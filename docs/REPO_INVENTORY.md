# Repository Inventory — 2026-03-12

## High-level layout
```
.
├── codex_loop_config.example.json
├── codex_loop.py                     # legacy Codex helper
├── debug_loop.py
├── defs_scraper.txt                 # notes on current scraper actions
├── dlf_*.csv                        # manually downloaded DLF data files
├── Dynasty Scraper.py               # legacy scraping script
├── frontend/                        # Next.js + React client
├── funcs_index.txt
├── inspect_dlf_csvs.py              # CSV inspector utility
├── players.txt / rookie_must_have.txt
├── scripts/                         # PowerShell + Python helpers
├── server.py                        # FastAPI/Flask-style backend (serves API + proxies Next)
├── start_*.bat + run_scraper.bat    # Windows helpers
├── Static/                          # legacy static dashboard assets
└── README.md
```

## Legacy components
| Component | Description | Status | Notes |
| --- | --- | --- | --- |
| `Dynasty Scraper.py` | Live scrape + normalization + value-precompute runtime producer. | **Complete (live)** | Authoritative producer for current `/api/data` payload inputs. |
| `server.py` | Live backend API + runtime mode switch + payload publication. | **Complete (live)** | Not a fallback; this is the live authority host today. |
| `frontend/` | Next.js app + backend proxy route. | **Partial (live optional)** | Available when `FRONTEND_RUNTIME=next/auto`, not the default production runtime. |
| `Static/` | Legacy static app shell and runtime JS. | **Complete (live default)** | Default production runtime with `FRONTEND_RUNTIME=static`. |
| `scripts/` | Scaffold pipeline and validation helpers. | **Partial (mixed)** | Some are live diagnostics, canonical/league scripts are scaffold-only. |
| `dlf_*.csv` | Manual source imports. | **Complete (live input)** | Still actively used by the live scraper flow. |

## src/ Runtime Truth
```
src/
  api/data_contract.py     # LIVE: authoritative /api/data contract/value-bundle shaping
  scoring/*                # LIVE: imported by Dynasty Scraper.py (optional import)
  adapters/*               # SCAFFOLD: source-pull pipeline only
  identity/*               # SCAFFOLD: identity-resolve pipeline only
  canonical/*              # SCAFFOLD: canonical-build pipeline only
  league/*                 # SCAFFOLD: league-refresh pipeline only
```

## Runtime authority matrix
| Layer | Current authority status | Live path |
| --- | --- | --- |
| Scrape + source merge | **Complete (authoritative)** | `Dynasty Scraper.py -> result["players"]` |
| Value bundle resolver/contract | **Complete (authoritative)** | `src.api.data_contract.build_api_data_contract` inside `server.py` |
| Static runtime consumption | **Complete (authoritative default)** | `Static/index.html` + `Static/js/runtime/*` + `/api/data` |
| Next runtime consumption | **Partial (optional runtime)** | `frontend/app/api/dynasty-data/route.js` -> backend `/api/data` |
| `src/adapters + identity + canonical + league` pipeline | **Partial (non-authoritative scaffold)** | `scripts/*.py` -> `data/*` artifacts -> `/api/scaffold/*` only |
| `/api/scaffold/*` endpoints | **Complete (diagnostics only)** | Snapshot visibility, not live valuation authority |

## Runtime Authority (Current, Live)
- Authoritative production frontend runtime is now controlled by `FRONTEND_RUNTIME` in `server.py`.
- Current default is `static` unless explicitly overridden.
- Runtime modes:
  - `static`: serves `Static/index.html` intentionally.
  - `next`: proxies Next only; no silent fallback to static.
  - `auto`: tries Next and explicitly falls back to static with status visibility.
- Critical route authority map now lives in `docs/RUNTIME_ROUTE_AUTHORITY.md` and `GET /api/runtime/route-authority`.
- `frontend/.next` artifacts are not route authority by themselves.

## Backend Data Contract (Current, Live)
- `/api/data` now serves a versioned contract from `src/api/data_contract.py::CONTRACT_VERSION` (currently `2026-03-20.v6`).
- Legacy compatibility remains in place (`players` object map, `maxValues`, etc.) for Static app continuity.
- Normalized contract additions include:
  - `playersArray` (stable player list shape)
  - `runtimeAuthority` (explicit architecture truth block)
  - `dataSource` metadata
  - `contractHealth` summary
- Contract validation is enforced via runtime diagnostics (`/api/status`) and CI (`scripts/validate_api_contract.py` in Jenkins).
- Semantic validation output now includes root-cause buckets and high-impact samples for:
  - blank non-pick positions
  - `sourceCount > 0` with no positive canonical site values
  - low-confidence split into actionable vs non-actionable rows

This doc will be kept up to date as we migrate functionality into the new architecture.
