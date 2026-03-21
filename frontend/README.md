# Next.js Frontend

This folder contains the React + Next.js frontend migration for the dynasty trade calculator.

Detailed shell notes:
- `../docs/frontend/frontend-target-architecture.md`
- `../docs/RUNTIME_ROUTE_AUTHORITY.md`

## Run

```powershell
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

Available routes:
- `/`
- `/rankings`
- `/trade`
- `/login`

Route authority note:
- Public League routes (`/league`, `/league/*`) are backend-owned static routes served by `server.py` from `Static/league/index.html`.
- Presence of `frontend/.next` build artifacts does not make Next authoritative for League paths.
- `frontend/app/league/*` route scaffolding is intentionally absent in this runtime phase to avoid false ownership assumptions.

Non-authoritative local artifacts:
- `frontend/.next` (generated build output)
- `frontend/tsconfig.tsbuildinfo` (generated TypeScript incremental cache)

## Data source

The frontend reads your latest scraper output through:

- `GET /api/dynasty-data`

Default policy is backend contract only:

1. backend API (`BACKEND_API_URL`, default `http://127.0.0.1:8000/api/data?view=app`)
2. if backend is unavailable, `/api/dynasty-data` returns `503` (no silent downgrade to raw files)

Optional emergency fallback (explicit opt-in only):

- set `NEXT_ALLOW_RAW_DYNASTY_FALLBACK=1` to allow local raw file fallback:
  - newest `dynasty_data_YYYY-MM-DD.json` in `../data/`
  - newest `dynasty_data_YYYY-MM-DD.json` in `../`
  - `../dynasty_data.js` or `../data/dynasty_data.js`

Operational visibility for raw fallback health:
- `GET /api/status` -> `frontend_runtime.raw_fallback_health`
- `GET /api/health` -> `frontend_raw_fallback`
- Home console (`/`) shows a runtime warning card when skipped raw fallback files are detected

Cleanup / remediation:
- Dry-run audit: `python ../scripts/quarantine_invalid_raw_fallback.py`
- Quarantine invalid fallback files: `python ../scripts/quarantine_invalid_raw_fallback.py --apply`

## Environment

Copy `.env.example` to `.env.local` and adjust as needed:
- `BACKEND_API_URL`
- `NEXT_ALLOW_RAW_DYNASTY_FALLBACK` (`0`/unset recommended, `1` for local emergency fallback)
- `FRONTEND_DATA_REVALIDATE_SECONDS`
- `FRONTEND_BACKEND_TIMEOUT_MS`
