# Route Authority & Auth Hardening Audit — 2026-03-20

Skill applied: `reality-check-review` (ruthless runtime truth validation).

## A) Executive conclusion

The live authority is still `server.py` + Static shell. The auth gate is real only on a narrow set of backend HTML entry routes (`/app`, `/rankings`, `/trade`, `/login`, `/index.html`, `/Static/index.html`). Everything else is a mixed surface with meaningful bypass and confusion risk:

- Backend API surfaces are largely unauthenticated (including scrape trigger and data/status endpoints).
- Next routes are not auth-enforced and include a localStorage-only demo login.
- Route ownership is intentionally dual-mode (`FRONTEND_RUNTIME` static/next/auto), which is powerful but easy to misunderstand and misconfigure.
- There is no runtime assertion that blocks demo auth UI from production-exposed Next runtime.

Bottom line: migration should **not** proceed as-is without route-authority hardening guardrails.

## B) Route authority matrix

| Route / Pattern | Real runtime owner | Intended authority status | Auth requirement (actual) | Env sensitivity | Duplicate/shadow implementation |
|---|---|---|---|---|---|
| `/` | `server.py` -> `Static/landing.html` | Backend-authoritative public entry | Public | None | Next also has `/` page in `frontend/app/page.jsx` when `FRONTEND_RUNTIME=next/auto-next` |
| `/league` | `server.py` -> `Static/league.html` | Backend-authoritative public route | Public | None | No equivalent backend alias; static file also directly reachable at `/Static/league.html` |
| `/app` | `server.py` + static/next resolver | Backend-authoritative protected app entry | Requires backend session cookie | `FRONTEND_RUNTIME` decides static vs proxied Next shell | Next has `/` (not `/app`) but `/app` backend can proxy root path to Next |
| `/rankings` | `server.py` + static/next resolver | Backend-authoritative protected route | Requires backend session cookie | `FRONTEND_RUNTIME` | Next has direct `/rankings` page with no backend auth if Next server is directly exposed |
| `/trade` | `server.py` + static/next resolver | Backend-authoritative protected route | Requires backend session cookie | `FRONTEND_RUNTIME` | Next has direct `/trade` page with no backend auth if Next server is directly exposed |
| `/login` | `server.py` + static/next resolver | Backend-authoritative route name but behavior is inverted | Redirects authenticated users away; unauth users get landing redirect flow | `FRONTEND_RUNTIME` | Next has `/login` demo localStorage login page |
| `/index.html` | `server.py` | Protected alias to app shell | Requires backend session cookie | `FRONTEND_RUNTIME` | Mirrors `/app` |
| `/Static/index.html` | `server.py` explicit route (before static mount) | Protected legacy alias | Requires backend session cookie | `FRONTEND_RUNTIME` | Conflicts in appearance with `/Static/*` public mount |
| `/Static/landing.html` `/Static/league.html` | FastAPI static mount | Public static file serving | Public | None | Shadow paths to public entry pages bypassing route-level handlers |
| `/Static/*` other assets | FastAPI static mount | Static asset authority | Public | None | Can cause confusion with protected `/Static/index.html` special-case route |
| `/_next/*` | `server.py` proxy route | Backend pass-through only | Public (no auth check) | Works only when Next reachable/active | Direct Next server can also serve same paths |
| `/api/data` | `server.py` | Live authoritative data API | Public | Data freshness/state dependent | Next route can fallback to local files when backend unavailable |
| `/api/dynasty-data` | `server.py` alias -> `/api/data` | Compatibility alias | Public | None | Shadowed by Next internal API route name (`frontend/app/api/dynasty-data/route.js`) on port 3000 |
| `/api/status` | `server.py` | Live backend status | Public | Runtime state | None |
| `/api/health` | `server.py` | Health probe | Public | Runtime/contract/data health | None |
| `/api/uptime` | `server.py` | Uptime watchdog status | Public | Runtime | None |
| `/api/metrics` | `server.py` | Metrics | Public | Runtime | None |
| `/api/draft-capital` | `server.py` | Backend computation endpoint | Public | External Sleeper/KTC fetch + cache | None |
| `/api/scrape` (POST) | `server.py` | Operational control endpoint | Public (no auth) | Scraper lock/state | None |
| `/api/test-alert` (POST) | `server.py` | Operational alert check | Public (guarded only by env enabled) | ALERT env vars | None |
| `/api/auth/status` | `server.py` | Backend auth status endpoint | Public | Session cookie presence | None |
| `/api/auth/login` | `server.py` | Backend auth entry | Public | Credential env + cookie settings | Separate fake login exists in Next UI |
| `/api/auth/logout` | `server.py` | Backend auth exit | Public | Session cookie presence | Static UI logout uses this endpoint |
| `/logout` | `server.py` | Logout redirect | Public | None | None |
| `/api/scaffold/*` | `server.py` | Scaffold artifact inspection | Public | Data artifact existence | Can be mistaken as production data authority |
| Next `/:3000/` `/rankings` `/trade` `/login` | Next dev/prod runtime | Migration surface only (should not be prod authority) | No backend auth enforcement | Exposure depends on deployment/network | Shadows backend-protected route names |
| Next `/:3000/api/dynasty-data` | Next route handler | Migration helper; non-authoritative | Public | Uses `BACKEND_API_URL`, then local file fallback | Backend has `/api/dynasty-data` alias with different behavior semantics |

## C) Auth boundary findings

1. **`/app` auth enforcement today is backend cookie gate only.**
   - `server.py` checks `_is_authenticated()` and redirects unauthenticated requests to landing with `?jason=1` on `/app`, `/rankings`, `/trade`, `/login`, `/index.html`, and `/Static/index.html`.
2. **Session authority is in-memory only; no persistence and no expiry policy.**
   - Sessions are stored in process memory (`auth_sessions`), created on login, cleared on logout, and can be mass-pruned by count but not TTL-expired.
3. **Backend login is real; Next login is cosmetic.**
   - Static landing uses `/api/auth/login` and `/api/auth/status` for real cookie auth.
   - `frontend/app/login/page.jsx` accepts arbitrary form input and writes only localStorage (`next_auth_session_v1`), with no backend call.
4. **Bypass risk exists if Next runtime is directly reachable.**
   - Next pages (`/rankings`, `/trade`, `/login`) have no middleware or server-side auth checks; layout nav exposes them directly.
5. **API control plane has no auth boundary.**
   - `/api/scrape` and `/api/test-alert` are callable without session checks.

## D) Route ambiguity / migration hazards

1. **Dual ownership by design (`FRONTEND_RUNTIME`) can silently alter authority perception.**
   - Backend route handlers may serve static shell or proxy Next depending on env/runtime availability.
2. **Route-name parity hides different auth models.**
   - `/rankings`, `/trade`, `/login` exist in both backend-gated and Next-ungated surfaces.
3. **`/api/dynasty-data` naming collision creates semantic drift.**
   - Backend alias is direct `/api/data`; Next route with same name can fallback to filesystem snapshots when backend fails.
4. **Static mount vs explicit protected alias is easy to misread.**
   - `/Static/index.html` is protected by explicit route, but `/Static/landing.html` and `/Static/league.html` are public through mount, which can mislead auditors reading only one mechanism.
5. **No hard production guard forbids demo auth surface.**
   - If Next is exposed intentionally or accidentally, demo login is reachable and appears real.

## E) Stale/dead artifact findings

1. **Migration scaffold outputs are archived and discoverable but non-authoritative for live `/api/data`.**
   - `/api/scaffold/*` serves files from `data/raw_sources`, `data/canonical`, `data/league`, etc.; these are observability artifacts, not live app data source.
2. **Export/archive artifacts exist and can mislead “latest data” assumptions.**
   - `exports/archive/*.zip` + `exports/latest/*` provide alternate datasets that are not runtime authority in `server.py` endpoints.
3. **No `.pyc`/`__pycache__` artifacts were found in this checkout during this audit run.**
   - Ground-truth claim about stale bytecode is not currently evidenced in the checked tree.
4. **Orphaned route-adjacent migration code remains high-confusion surface.**
   - Next `app` routes and Next API route are runnable and look complete, but are not primary runtime authority.

## F) Hardening plan by priority

### Immediate must-fix
1. Add backend auth/authorization guard for operational endpoints (`/api/scrape`, `/api/test-alert`, likely `/api/scaffold/*`).
2. Add explicit production runtime assertion: if `FRONTEND_RUNTIME in {next,auto}` and environment is production, fail startup unless a strong auth policy for Next surface is enabled.
3. Add a hard banner/HTTP header marker from backend indicating active frontend runtime (`static` vs `next`) on app-shell responses.
4. Block or remove demo Next login in production builds (`frontend/app/login/page.jsx`) via env-gated route disable/redirect.

### Short-term cleanup
1. Add route-authority tests that verify protected routes redirect when unauthenticated and that operational APIs reject unauthenticated calls.
2. Add CI check for route drift: enumerate backend route map and compare with documented authority matrix.
3. Add `frontend` middleware (or server component guard) so Next route access cannot be unauthenticated when run outside local dev.
4. Add route-level authority comments near each backend route block (public/protected/admin/scaffold).

### Migration-safe follow-ups
1. Introduce a single shared auth contract usable by both static and Next runtimes before any Next cutover.
2. Split “public data APIs” from “operator APIs” into separate prefixes and policies.
3. Add an explicit cutover checklist that requires parity tests for auth boundary behavior before switching `FRONTEND_RUNTIME=next` in prod.
4. Remove or quarantine non-authoritative fallback loaders in Next API route once backend SLA is accepted.

## G) Exact files/tests/docs to change

### Code
- `server.py`
  - Add auth checks on operational endpoints (`/api/scrape`, `/api/test-alert`, likely scaffold endpoints).
  - Add startup assertion for disallowed runtime/auth combinations.
  - Add explicit runtime marker headers on app-shell responses.
- `frontend/app/login/page.jsx`
  - Replace demo localStorage auth with backend auth integration or production-block redirect.
- `frontend/middleware.(js|ts)` (new)
  - Enforce auth boundary for `/rankings`, `/trade`, and any sensitive surfaces when Next is exposed.
- `frontend/app/api/dynasty-data/route.js`
  - Remove/guard filesystem fallback in production to prevent silent authority drift.

### Tests
- `tests/e2e/specs/` (new specs)
  - Unauthenticated access should redirect on protected backend routes.
  - Authenticated cookie should unlock protected routes.
  - Operational endpoints should reject unauthenticated requests.
- Existing `tests/e2e/specs/smoke-api.spec.js`
  - Extend to assert auth boundary behavior (currently API/surface smoke only).

### Docs
- `README.md`
  - Add explicit “auth boundary truth” and “do not expose Next without guard” section.
- `frontend/README.md`
  - Mark Next login as demo/non-production until replaced.
- New: `docs/ROUTE_AUTHORITY.md`
  - Keep canonical route owner matrix in-repo and tie to CI drift check.

## H) Final verdict

**Hardening required first.**

Current state is migration-capable for development experiments, but not authority-safe for continued runtime migration without introducing boundary drift and false-security behavior.
