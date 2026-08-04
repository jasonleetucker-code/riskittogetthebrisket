# W01 — Wiring: 36 Next bridge routes vs 99 backend operations

## What a "bridge" actually is here

Every one of the 36 `frontend/app/api/**/route.js` handlers is a thin proxy
to the identical path on the FastAPI backend. **All 36 have a backend
counterpart** — there is no orphan bridge pointing at a route that does not
exist (checked by path-template normalisation across both sets).

They are **dev-only**. `deploy/nginx/chaseupside-proxy.conf` declares:

```
location /api/ { proxy_pass http://dynasty_backend; }
location /     { proxy_pass http://dynasty_frontend; }
```

so in production **no** `/api/*` request ever reaches Next. The repo says
so itself, in `frontend/app/api/dynasty-data/route.js`:

> NOTE ON DEPLOYMENT SCOPE: in production, nginx routes every `/api/*`
> request … straight to the Python backend … This Next route only handles
> the dev flow (no nginx in front).

## The consequence nobody wired

`frontend/next.config.mjs` declares `distDir`, `turbopack.root` and one
`redirects()` entry. It declares **no `rewrites()`**. `npm run dev` is
`next dev -p 3000` with nothing in front of it.

So in local development, only the 36 bridged paths resolve. The other
**63** backend operations 404 at the Next dev server — including **40 that
the client actually calls**.

Measured on the running stack (auth cookie on all three):

```
route                              :3000   :3001   :8000
                                  (Next)  (edge)  (API)
/api/health                          404     200     200
/api/leagues                         404     200     200
/api/user/state                      404     200     200
/api/terminal                        404     200     200
/api/movers                          404     200     200
/api/data/rank-history               404     200     200
/api/ros/player-values               404     200     200
/api/custom-alerts                   404     200     200
/api/data                            404     200     200
/api/dynasty-data                    200     200     200   <- bridged
```

`/api/data` is the load-bearing one: `frontend/app/draft/page.jsx`,
`frontend/app/league/page.jsx`, `AppShell.jsx` and `StaleDataBanner.jsx`
fetch `/api/data` directly, while `lib/dynasty-data.js` fetches the bridged
alias `/api/dynasty-data`. Two paths to the same contract, one bridged and
one not.

This is not theoretical: the audit harness had to stand up a **separate
edge proxy on :3001** to get correct page behaviour, because the first
`page-probe.json` capture against :3000 was full of `/api/*` 404s and a
`buildRows received a payload with zero backend rank stamps` console error
that does not occur in production.

## The 40 client-called backend routes with no Next bridge

```
POST /api/admin/guest-pass                 GET  /api/public/league/matchups
POST /api/admin/guest-pass/{id}/revoke     GET  /api/public/league/players
GET  /api/admin/guest-passes               GET  /api/push/public-key
POST /api/admin/nfl-data/flush             POST /api/push/subscribe
POST /api/admin/sessions/force-logout-all  POST /api/push/unsubscribe
POST /api/admin/signal-state/migrate       GET  /api/ros/health
POST /api/auth/login                       GET  /api/ros/player-values
GET  /api/custom-alerts                    POST /api/ros/refresh
PUT  /api/custom-alerts                    GET  /api/ros/sources
GET  /api/data                             GET  /api/ros/status
GET  /api/data/player-source-history       GET  /api/ros/team-strength
GET  /api/data/rank-history                GET  /api/terminal
GET  /api/health                           POST /api/trade/export-ktc
POST /api/intel/leads                      POST /api/trade/simulate
GET  /api/intel/player                     POST /api/trade/simulate-mc
GET  /api/intel/summary                    POST /api/user/signals/dismiss
GET  /api/leagues                          POST /api/user/signals/restore
GET  /api/movers                           GET  /api/user/state
GET  /api/player/{sleeper_id}/realized     PUT  /api/user/state
GET  /api/playerctx/player                 POST /api/waiver/faab-recommend
```

## Bridges that proxy a route nothing calls

Four bridge routes exist for backend routes with **no UI caller at all** —
dev plumbing for a dead endpoint:

| bridge | backend route | why it is dead |
|---|---|---|
| `frontend/app/api/angle/find/route.js` | `POST /api/angle/find` | `/angle` POSTs only to `/api/angle/packages` |
| `frontend/app/api/consensus-edge/health/route.js` | `GET /api/consensus-edge/health` | `/consensus-edge` reads `players` + `methodology` only |
| `frontend/app/api/rankings/sources/route.js` | `GET /api/rankings/sources` | zero references outside the bridge itself |
| `frontend/app/api/sharp/roster-percentage/audit/route.js` | `GET /api/sharp/roster-percentage/audit` | operator-only, no UI entry point |

## One behavioural divergence worth knowing

`frontend/app/api/dynasty-data/route.js` is 264 lines — it adds a
**disk-snapshot fallback**, a per-chunk idle abort, and header
pass-through filtering that the backend does not have. None of that runs
in production, because nginx never routes to it. So the dev path is
strictly *more* fault-tolerant than the production path, which is the
wrong way round for a resilience feature: a fallback exercised only in dev
is a fallback that is never really tested where it would matter.
