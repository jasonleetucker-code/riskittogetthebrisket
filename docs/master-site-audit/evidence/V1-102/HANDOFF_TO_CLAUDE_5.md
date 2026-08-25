# V1-102 (#780) — evidence handoff to Claude 5

> **ADOPTED ON `main` BEFORE THIS BRANCH MERGED.** The recommendation below was carried
> out by the Integration Authority 2026-08-25 (`#1098`): the row now reads
> `IMPLEMENTED_UNVERIFIED` with the reclassification recorded in the row itself.
> §1's "current stale row text" is therefore HISTORICAL — it quotes the pre-`#1098`
> state this document was written against. The clause-by-clause evidence table below
> remains the row's implementation record; the open half is unchanged (L4 needs the
> deployed owner workflow run end-to-end — the same /admin guest-pass action §9b's
> two-grants note names).

**Audited at:** `131abf9f9` (dispatch SHA) · **Lane 6** · **No V1 status column edited.**

**Recommendation: `NOT STARTED` → `IMPLEMENTED_UNVERIFIED`.** Not `VERIFIED` — the row's
target is **L4** and the deployed production-consumer run has not been performed.

---

## 1. Current stale row text (verbatim, line 278)

```
| V1-102 | Temporary-password generator with configurable expiry | `#780` | L6 | `NOT STARTED` | L4 | named V1 scope; owner workflow must work end-to-end |
```

`NOT STARTED` means "no implementation". That is false.

## 2. The acceptance language, and where each clause is met

From `docs/OWNER_FEATURE_INVENTORY.md` §13.6:

> **#780** — repair/verify **configurable-hours** temporary password/pass generation **end to
> end**, including **actual authentication**, **expiry** and **revocation/fail-closed
> semantics**.

| clause | implementation | file:line |
|---|---|---|
| temporary password generator | `guest_passes.create()` | `src/api/guest_passes.py:177` |
| cryptographic generation | `secrets.token_urlsafe(24)` — 32 chars, ~192 bits | `src/api/guest_passes.py:206`, `:50` |
| hash-only persistence | `_hash_token()` SHA-256; plaintext returned once, never stored, never in `list_passes` | `src/api/guest_passes.py:162`, `:207` |
| configurable hours | `duration_hours`, 1 min – 30 day bounds; UI control 1–720 h, default 12 | `src/api/guest_passes.py:177`, `frontend/components/admin/GuestPassPanel.jsx:18,147` |
| create (admin) | `POST /api/admin/guest-pass` | `server.py:12928` |
| list (admin) | `GET /api/admin/guest-passes` | `server.py:12991` |
| revoke (admin) | `POST /api/admin/guest-pass/{id}/revoke` | `server.py:13012` |
| **actual authentication** | `/api/auth/login` fall-through → `_guest_passes.validate` → `_create_auth_session` | `server.py:11704` |
| expiry fail-closed | refused in `validate()`, refused again at login, and re-checked server-side per request in `_get_auth_session` | `src/api/guest_passes.py` `validate()`; `server.py:11705-11712` |
| session bounded by the pass | cookie `max-age = min(remaining, ceiling)` | `server.py:11739` |
| revocation fail-closed | `revoke()` + `validate()` refusal | `src/api/guest_passes.py` |
| no duplicate auth subsystem | one store (`data/guest_passes.sqlite`), one session owner | — |
| production consumer surface | `GuestPassPanel` mounted on `/admin` | `frontend/app/admin/page.jsx:20,354` |

## 3. Tests that already proved it (reused, not duplicated)

`tests/api/test_guest_passes.py` — 16 tests: creation, range rejection, note truncation,
**no plaintext in the SQLite file**, `to_dict` omits the hash, validate accepts fresh /
rejects unknown / expired / revoked, revoke idempotency, list filtering, purge grace.

`tests/api/test_admin_endpoints.py` — create requires admin, create returns a token,
zero-duration rejected, **list returns metadata without tokens**, revoke marks revoked,
**`test_guest_pass_login_creates_time_bounded_session`** (the end-to-end authentication
path), invalid token → 401.

`tests/e2e/specs/admin-guest-pass.spec.js` (added in this PR) — the panel renders a
non-empty pass list on a real **production build** with no client error.

## 4. Tests added — `tests/api/test_guest_pass_v1_102_evidence.py` (16)

Only the clauses nothing deterministic covered:

1. **`test_expired_token_is_refused_at_login`** / **`test_revoked_token_is_refused_at_login`**
   / **`test_revocation_takes_effect_immediately`** — the acceptance names expiry and
   revocation fail-closed semantics *alongside* "actual authentication". The unit tests
   proved `validate()` refuses; nothing proved the door a guest actually uses refuses.
2. **`test_configured_duration_is_honored`** (5 durations) + `test_distinct_durations_...` —
   range-checking is not honouring. A `create()` that ignored its argument and always minted
   12 h passed every pre-existing test.
3. **`test_session_cookie_is_bounded_by_the_pass_not_the_ceiling`** — the existing e2e test
   asserts `expiresAtEpoch` is *present*; presence is not a bound.
   **`test_guest_session_is_not_admin`** — a temporary password cannot mint more of itself.
4. **`test_token_generation_uses_a_csprng`** (AST: `secrets` present, `random` absent) +
   `test_tokens_are_unique_and_high_entropy`. `len(token) >= 20` is satisfied by `"a" * 32`.
5. **`test_admin_endpoints_delegate_to_the_canonical_owner`** and
   **`test_no_second_temp_password_owner_exists`** — recording an implemented capability as
   `NOT STARTED` is precisely what invites someone to build the duplicate auth subsystem the
   row forbids. This fails if one appears.

## 5. Mutation proof — layered, and it found something

| mutation | result |
|---|---|
| expiry check removed from `validate()` | **only the UNIT test** goes RED |
| expiry removed from `validate()` **and** the login handler | **`test_expired_token_is_refused_at_login`** goes RED |
| both restored | **16/16 GREEN** |

The first row is the finding: the login boundary carries its **own** independent expiry
check, so the new test is not a restatement of the unit test — it pins a second line of
defence that nothing previously covered.

## 6. Current achievable evidence level

**L2 reached, locally.** L1 (deterministic RED→GREEN at exact head) plus a measured
statement on real behaviour: 16 new + 16 existing unit + the admin-endpoint suite + a
production-build E2E, all green at `5c7831d6c`.

**L3 and L4 are NOT reached** and are not claimable from here — both require a deployed
SHA, and this session has no path to a deployed authenticated `/admin`.

## 7. The exact L4 recipe

In `docs/master-site-audit/evidence/V1-101/L4_PRODUCTION_RECIPE.md` — one authenticated
`/admin` run on a deployed SHA covers **both V1-101 and V1-102**. It deliberately mints at a
**non-default** duration (3 h): a run at the default 12 would leave a hardcoded 12
indistinguishable from a wired control.

## 8. Drafted replacement row

Paste after the L4 run above succeeds. If it has not been run, use the same text but keep
the status `IMPLEMENTED_UNVERIFIED` and drop the final sentence.

```
| V1-102 | Temporary-password generator with configurable expiry | `#780` | L6 | `IMPLEMENTED_UNVERIFIED` | L4 | named V1 scope; owner workflow must work end-to-end. **Status corrected 2026-08-24 (Lane 6 audit), NOT promoted.** `NOT STARTED` was false: the capability ships as the guest-pass system and the `/admin` panel's own copy calls it "a temporary password". `secrets.token_urlsafe(24)` (`src/api/guest_passes.py:206`), SHA-256-only persistence with the plaintext shown once (`:162`, `:207`), configurable expiry 1 min–30 days / UI 1–720 h (`:177`), create / list / revoke at `server.py:12928` / `:12991` / `:13012`, authentication via the `/api/auth/login` fall-through (`server.py:11704`) with the session cookie bounded by the pass (`:11739`) and expiry re-checked server-side per request. One store, no second session subsystem. Evidence: 16 pre-existing unit tests, the admin-endpoint suite incl. the end-to-end login path, a production-build E2E (`tests/e2e/specs/admin-guest-pass.spec.js`), and 16 added guards (`tests/api/test_guest_pass_v1_102_evidence.py`) closing the clauses nothing covered — fail-closed for expired AND revoked tokens **at the login boundary** (the unit tests only covered `validate()`; the login handler has its own check, so removing both layers is what reddens it), the configured duration actually honoured, the cookie bounded by the pass rather than the ceiling, CSPRNG generation asserted on the AST, endpoint delegation to the canonical owner, and a structural guard that no second temp-password generator exists. **Reaches L2, not L4** — no deployed production-consumer run has been performed. Recipe: `docs/master-site-audit/evidence/V1-101/L4_PRODUCTION_RECIPE.md`. |
```

## 9. Classification recommendation

**`IMPLEMENTED_UNVERIFIED`.** The implementation exists and is now evidenced to L2. Claude 5
may promote to `VERIFIED` after executing the L4 recipe on a deployed SHA — and only then.

**No second temporary-password generator was built, deliberately.** The row's own "no
duplicate auth subsystem" requirement forbids it, and the capability was not missing.
