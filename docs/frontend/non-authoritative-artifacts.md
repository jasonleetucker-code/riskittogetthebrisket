# Frontend Non-Authority Artifact Register

Last updated: 2026-03-19

Purpose: prevent false confidence about route/runtime ownership.

## Runtime Truth (Current)
- `/` -> FastAPI static landing shell
- `/league` and `/league/*` -> FastAPI static League shell
- `/app`, `/rankings`, `/trade` -> auth-gated private shell path in `server.py`
- Next is optional migration runtime, not default authority for League

## Artifact Classification

### Safe to delete
- `frontend/.next`
  - Why: generated build output; not route authority by itself.
- `frontend/tsconfig.tsbuildinfo`
  - Why: generated TypeScript cache; not runtime input.
- Empty placeholder directories that imply routes without implementation:
  - prior `frontend/app/league/*` empty subtree
  - prior empty `frontend/app/calculator`
  - prior empty `frontend/components/*`, `frontend/types`
  - Why: no route/page/component implementation, no runtime wiring.

### Should be clearly marked as non-authoritative
- Any future `frontend/app/league/page.*` files while `server.py` still serves `/league*`.
  - Required: docs and route-authority warnings must explicitly state non-authority.

### Safe to ignore but documented
- `frontend/node_modules/`
  - Why: package install artifacts, not route ownership.

### Remains as future migration path
- Next private surfaces under `frontend/app/*` for non-League migration work.
  - Why: intentional staged migration target; authority cutover not complete.

## Guardrails
- `GET /api/runtime/route-authority` is canonical runtime ownership source.
- Smoke tests assert League route ownership and public accessibility.
- If local `.next` exists, route-authority warnings must label it non-authoritative.
