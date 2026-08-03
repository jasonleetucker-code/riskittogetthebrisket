# Curated Sharp operations

## Import the attached workbook

The workbook is tracked in the repo, so the import is reproducible:

```bash
python scripts/import_sharp_workbook.py \
  config/sharp/workbooks/dynasty_fantasy_football_sharps_100.xlsx \
  --snapshot config/sharp/curated_universe.json \
  --resolve-verified-sleeper \
  --inspect-sleeper-candidates \
  --sleeper-budget 75 \
  --match-ffpc
```

The import is idempotent. Re-running it updates current fields without duplicating people, aliases, evidence, candidates, verified account ownership, or activity events. Use `--dry-run` to parse and report without committing; run it twice and the counts are identical.

**The import verifies no fantasy identity**, so a first run reports
`totalPositivelyVerifiedOnSleeper: 0` and `totalSuperSharps: 0`. That is the
correct starting state, not a failed import — see the identity-resolution
rules in `CURATED_SHARP_MODEL_AUDIT.md`. Identities become verified only
through `POST /api/sharp/review/{candidateId}` (admin-only), after
`--inspect-sleeper-candidates` has resolved a stable platform user id.

`--resolve-verified-sleeper` re-checks accounts that are **already** verified
for renames and deletions. On a fresh database it correctly does nothing.

## Daily refresh

```bash
python scripts/refresh_curated_sharps.py --sleeper-budget 75
```

Install the daily timer:

```bash
APP_DIR=/home/dynasty/trade-calculator \
VENV_DIR=/home/dynasty/.venvs/trade-calculator \
SERVICE_USER=dynasty \
bash deploy/install-curated-sharps-service.sh
```

The timer runs once daily at 06:20 UTC with a randomized delay and persistent catch-up after downtime.

## Exports

```bash
python scripts/export_curated_sharps.py --output-dir data/intel/sharp_curated
```

It writes CSV and JSON for imported people, verified identities, probable matches, unresolved identities, rejected matches, Super Sharps, source evidence, and the reconciliation report.

## Private APIs

- `GET /api/sharp/people`
- `GET /api/sharp/people/{personId}`
- `GET /api/sharp/review`
- `POST /api/sharp/review/{candidateId}`
- `GET /api/sharp/curated/summary`
- `POST /api/sharp/curated/refresh`

These remain behind the existing private API gate. The public FFPC/Sleeper source data does not make the administrator's review workflow public.

The two **mutating** routes carry an additional allowlisted-admin check on top
of that gate: `POST /api/sharp/review/{candidateId}` is what turns a curated
person into a Super Sharp whose trades vote, and `POST /api/sharp/curated/refresh`
spends a real outbound call budget against Sleeper's public API. Being logged
in is not sufficient for either. The gate fails closed — if the admin helper
cannot be resolved the route returns 503 rather than proceeding.

Registration note: `server.py` calls `_sharp_service._register_http_routes()`
and `_sharp_curated_service._register_http_routes()` **explicitly** after
importing them. Both modules also self-register at import, but that side
effect does not re-run if the module is already in `sys.modules`, which
silently produced 404s with no error logged anywhere. Registration is now a
consequence of the app existing, not of import order.

## Market qualifications

- `all`
- `automated`
- `industry`
- `super`
- `both`
- `curated` (legacy configured FFPC high-stakes identities)
- `provisional` (public FFPC activity not qualified by Sharp Score v2)

## Rollback

The schema is additive. A code rollback can ignore the `sharp_*` tables without affecting the legacy Sleeper/FFPC ledger. Do not drop `manager_identity_links`, which predates this extension and is shared by the platform-neutral model. Before destructive rollback, copy the SQLite database with its WAL/SHM state or use SQLite's backup API.
