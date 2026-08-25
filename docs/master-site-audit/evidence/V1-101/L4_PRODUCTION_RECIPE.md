# V1-101 + V1-102 — audit, and the exact L4 production recipe

**Head audited:** `131abf9f9` (dispatch SHA = `origin/main`)
**Lane:** 6 (Premium UI / Frontend)
**Status changes made here:** none. The V1 contract's status column is Integration's.

Both rows live on one surface — `/admin` → `GuestPassPanel` → the three
`/api/admin/guest-pass*` endpoints → `src/api/guest_passes.py`. **One production run
proves both.**

---

## 1. V1-101 — `fmtPassExpiry` crash. Verified intact; NOT rewritten.

The dispatch's condition was *"do not rewrite the helper unless a real current defect
exists."* No current defect exists. Verified by reading the live tree:

| claim | evidence on `131abf9f9` |
|---|---|
| helper is a proper module export | `frontend/lib/guest-pass-format.js` exports `fmtPassExpiry` |
| both call sites consume it | `GuestPassPanel.jsx:15` imports it; used at `:272` (fresh token) and `:330` (list row) |
| the route mounts the panel | `frontend/app/admin/page.jsx:20` imports, renders at `:354` |
| missing is never zero | `null` / non-numeric / `<= 0` → `"—"`, never a 1970 date |

**What this pass adds: a regression that can actually see the bug.**
`frontend/__tests__/components/admin/GuestPassPanel.test.jsx` passes and is real — but
it *cannot in principle* catch #779. That was a module-scope failure in the **built
client bundle**: an identifier that resolves when jsdom imports the component directly,
and does not exist in the chunk a browser downloads. A test that imports the component
supplies the very scope whose absence was the bug.

Demonstrated, not asserted. Removing the import from `GuestPassPanel.jsx`:

```
frontend production build .............. PASSES, all 14 bundle budgets green
tests/e2e/specs/admin-guest-pass.spec.js  FAILS — /admin renders "Something went wrong"
```

The bundler cannot see it. **That is why this row is L4 and not L2**, and it is why the
new spec runs against `npm run build` + `npm run start`, not jsdom. Restoring the import
→ 4/4 green across `desktop-1366` and `mobile-chromium`, stable over three consecutive
runs.

One incidental defect found and fixed while writing it, recorded because it would have
bitten the next author: the spec's API stub was bypassed once the app's **service
worker** installed (`page.route()` does not intercept service-worker fetches), so the
panel received the real 404 and the test failed on an assertion about something else.
`test.use({ serviceWorkers: "block" })`. Also: a glob route pattern is resolved against
`baseURL`, which in this suite is the API origin while pages come from
`E2E_PAGE_ORIGIN` — the spec uses a `url.pathname` predicate instead.

---

## 2. V1-102 — recorded `NOT STARTED`. **It is fully implemented on `main`.**

The dispatch said to audit whether `NOT STARTED` is still true and, *if still absent*,
to implement it. **It is not absent.** The guest-pass system **is** the
temporary-password generator with configurable expiry — the panel's own user-facing
copy reads:

> "Generate a temporary password to share with someone you want to give private-app
> access."

Requirement-by-requirement against `src/api/guest_passes.py` and `server.py`:

| V1-102 requirement | where it is met on `131abf9f9` |
|---|---|
| uses existing auth/admin canonical owners | falls through `/api/auth/login` → `_create_auth_session`; no second session store |
| configurable expiration | `create(duration_hours=…)`, bounds 1 min – 30 days; UI control 1–720 h, default 12 |
| secure generation | `secrets.token_urlsafe(24)` |
| no plaintext persistence | SHA-256 `token_hash` only; plaintext returned **once**, never recoverable, never in `list_passes` |
| clear expiry semantics | `expires_at_epoch`; cookie max-age capped to remaining life **and** `_get_auth_session` re-checks server-side |
| admin workflow end to end | `POST /api/admin/guest-pass`, `GET /api/admin/guest-passes`, `POST /api/admin/guest-pass/{id}/revoke`, all rendered by `GuestPassPanel` |
| truthful errors | out-of-range duration → `ValueError` → HTTP error; DB unreachable → `RuntimeError`, not a silent empty list |
| no duplicate auth/session subsystem | one store, `data/guest_passes.sqlite`, sister to `session_store.sqlite`; no parallel login path |

Building a second one would have created exactly the duplicate auth subsystem this row
forbids. **So nothing was implemented, deliberately.**

### Proposed row text for Claude 5 / Integration

Drafted, not applied — this lane does not edit the status column.

> `V1-102` | Temporary-password generator with configurable expiry | `#780` | L6 |
> `IMPLEMENTED_UNVERIFIED` | L4 | named V1 scope; owner workflow must work end-to-end.
> **Status corrected 2026-08-24 (Lane 6 audit), NOT promoted.** `NOT STARTED` was
> false: `src/api/guest_passes.py` + the three `/api/admin/guest-pass*` endpoints +
> `GuestPassPanel` are this capability, and the panel's own copy calls it "a temporary
> password". Configurable expiry (1 min – 30 days, UI 1–720 h),
> `secrets.token_urlsafe(24)`, SHA-256-only persistence with the plaintext shown once,
> create/list/revoke, and no second session subsystem. Correction only — the row's
> target is L4 and nothing here is deployed evidence.

---

## 3. The L4 recipe — one run, both rows

L4 = L3 plus proof the intended user-facing surface consumes the canonical
implementation with truthful semantics. Everything below runs against a **deployed
SHA**; record it first.

1. **Record the deployed SHA.** `curl -s https://<host>/api/status | jq .` — capture it
   verbatim into the evidence file. A recipe run against an unknown build proves
   nothing.
2. **Sign in as an allowlisted admin** (a username in `PRIVATE_APP_ALLOWED_USERNAMES`)
   and load `/admin`. Confirm the page renders and the **"Guest access"** section is
   present. If it says "Not authorized", the account is not on the allowlist — stop;
   the run is invalid, not failed.
3. **Mint with a NON-DEFAULT duration.** In the panel set **Duration = 3** and click
   *Generate 3h pass*. Using the default 12 would leave "the control is wired" unproven
   — a hardcoded 12 would pass. Capture the response's `pass.expiresAtEpoch` and the
   once-shown token.
4. **Assert on the deployed page** (this is the V1-101 half):
   - no client-side error boundary — the section renders the form and the table, not
     "Something went wrong";
   - the fresh-token line reads **`Expires in 3h`**;
   - the new pass appears in *Recent passes* with the **same** rendered expiry and
     status `Active`.
   Compare the rendered string against the captured epoch. Agreement is the proof that
   the deployed surface consumes `lib/guest-pass-format.js` — a page that rendered
   "1970" or a raw number would be consuming something else.
5. **Confirm no plaintext leaks.** `GET /api/admin/guest-passes` must contain no token
   field for any row, including the one just minted.
6. **Prove the workflow end to end** (this is the V1-102 half): sign out, sign in with
   the token in the password field, confirm private access; then `Revoke` it as admin
   and confirm a fresh sign-in with the same token is refused.
7. **Prove expiry is real, not cosmetic.** Either mint a 1-minute pass and confirm
   access is refused after it lapses, or confirm the session cookie's max-age does not
   exceed the pass's remaining lifetime. Server-side rejection is the claim; the cookie
   alone is not.
8. **Record** the deployed SHA, the timestamps, the rendered strings and the endpoint
   responses in `docs/master-site-audit/evidence/V1-101/`.

**Not performed by this lane.** This session has no path to a deployed authenticated
`/admin`, so no L4 evidence is claimed and neither row is self-promoted. Steps 1–8 are
written to be executable by whoever does have that path.

---

## 4. Summary for the handoff

| row | on `main` | this pass | remaining |
|---|---|---|---|
| V1-101 | `IMPLEMENTED_UNVERIFIED` (L4) | fix verified intact; production-build regression added and mutation-proved | steps 1–5 above, on a deployed SHA |
| V1-102 | `NOT STARTED` (L4) — **stale** | proven already implemented; corrected row text drafted | steps 1–8 above, on a deployed SHA |

Both are **READY_FOR_PROD_VERIFICATION**. Neither is blocked on engineering.
