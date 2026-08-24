# E2E Safety Net — base-vs-branch causality for the two persistent failures

**PR:** #1086 · **Branch head audited:** `21f29ef03` · **Base:** `origin/main` `978bf5178`
**Method:** both builds served from their own `.next`, against **one shared backend** on
`:8000`, run back to back so the only variable is the diff. Branch on `:3000`, base on
`:3100`.

| failure | base (`978bf5178`) | branch | classification |
|---|---|---|---|
| `journey-rankings.spec.js` — global `/` search: `getByLabel(/search players, picks/i)` | **PASS** | **FAIL** | **A — branch regression.** Fixed here. |
| `journey-trade.spec.js` — `/arbitrage`: `getByText(/Pick a team and scan/i)` | **FAIL** | **FAIL** | **B — pre-existing on current main.** Not fixed here. |

Neither is **D (infrastructure)** and neither is flaky: both reproduced on every run, and the
two now behave *identically* on base and branch after the repair below.

---

## Failure 1 — global search: branch regression, FIXED

**Root cause.** `ReferenceError: capabilities is not defined`, thrown by the shell on every
private route.

The V1-131 capability was threaded into `<CommandPalette>` from inside **`InnerAppShell`**
(`frontend/components/AppShell.jsx:428`), but `capabilities` was only a parameter of the
**outer** `AppShell`. `InnerAppShell` never received it, so the identifier was a free
variable. The moment a user pressed `/`, React attempted the render and the shell threw —
the command palette stopped opening app-wide.

**Fixed** by threading the prop down the real chain, mirroring exactly how `authenticated`
already travels: `AppShell` → `PrivateAppShell` / `NoPlayerDataAppShell` → `InnerAppShell` →
`CommandPalette`.

**Why nothing caught it.** This is the part worth keeping:

* the **production build passed** — a free variable is not a build error;
* **2,363 frontend unit tests passed** — and could not have caught it. The component tests
  render `CommandPalette` directly and pass `capabilities` themselves, so the one thing that
  was broken (whether the identifier exists in the enclosing scope of the *real* shell) was
  precisely what they stubbed out.

Only a browser, on a production build, pressing the key, can see this class of defect. So a
guard now exists at that level: **`tests/e2e/specs/nav-capability-shell.spec.js`** asserts
the shell raises no uncaught error, the `/` shortcut opens the palette, the gated
destination is offered only in agreement with the server's published capability, and no
second shell-level request to `/api/consensus-edge/*` was introduced. It passes on
`desktop-1366` and `mobile-chromium`.

**A measurement trap recorded so the next person does not lose an hour to it.** An earlier
run of this comparison produced the *opposite* conclusion — branch failing, `500`s on
`/_next/static/chunks/*`. Those 500s were an artifact of my own harness: a stale
`next-server` still held `:3000` (`EADDRINUSE` in its log, so the intended restart silently
never happened) and was serving chunk hashes from a `.next` that had since been deleted. The
comparison above was re-run only after confirming a clean start with no `EADDRINUSE`, and
after verifying both origins rendered the board identically (28 rows each). **Check the
server log for `EADDRINUSE` before trusting any local base-vs-branch result.**

## Failure 2 — `/arbitrage` empty state: pre-existing, NOT fixed here

`getByText(/Pick a team and scan/i)` never appears — **on base as well as on branch**, from
the same backend, in the same session, on consecutive runs.

Nothing in #1086 touches `/arbitrage`, its page component, or its empty state. The diff's
only relationship to that route is that `/arbitrage` is an ungated entry in the nav model,
and the nav renders it correctly on both sides.

Per the direction, this is **not** folded into #1086: the PR would then carry an unrelated
product repair, and the repair is not the kind that should be made blind — the assertion may
be a genuine defect in the empty state, or a stale expectation after an intentional earlier
product change. Distinguishing those requires the `/arbitrage` owner's intent, not this
lane's. **The assertion has not been weakened, skipped or deleted.**

**Handed to Integration** with the reproduction above: base `978bf5178` fails this spec
standalone, with no #1086 code present.

## What stayed green throughout

`admin-guest-pass` (desktop + mobile), `mobile-pinned-overlap` (desktop + mobile),
`rankings-windowing` (V1-106), `api-view-parity`, `critical-smoke`, `signed-in-smoke`,
`a11y-axe`, the production build and all 14 bundle budgets — **74 passed / 0 failed** on the
focused revalidation batch after the repair.

---

## Addendum — the E2E job now fails BEFORE any test runs (`ed4c0f64c`, 21:42 UTC)

The two journey failures analysed above are no longer what the E2E Safety Net is
reporting. On head `ed4c0f64c` the job died in `npm run regression:preflight`, so **zero
specs executed** — the run uploaded no `playwright-report`, no `test-results`, and no
backend/frontend logs, because none were produced.

```
[contract] ok=False errors=2 warnings=18 players=993
[contract] structuralErrors=1 sourceHealthErrors=1
[contract][error] blend_integrity_violation:1 row(s) hold a value outside the
                  range of their own source contributions (2028 Late 3rd)
##[error]Process completed with exit code 1
```

**This is main's data, not this PR's code.** Established three ways:

1. the PR's diff touches **no** `exports/`, `data/`, `data_contract`, canonical-valuation
   or pick-pricing file — the changed set is frontend shell + `/api/auth/status` +
   `consensus_edge` availability + tests;
2. the snapshot CI validates, `exports/latest/dynasty_data_2026-08-24.json`, is byte-identical
   between this branch and `origin/main` (it arrives via `chore: automated data refresh
   2026-08-24T21:15:54Z`, commit `64f382343`);
3. running the same validator on a **clean `origin/main` worktree with no #1086 code
   present** reproduces it exactly — `structuralErrors=1`, same `2028 Late 3rd` row.

Per `CLAUDE.md`, a blend-integrity violation is a row whose blended value fell outside the
range of its own source contributions — structurally impossible under correct operation.
The system deliberately **does not coerce it**: the row is quarantined and the build-level
validator raises a hard error, because "coercing an impossible number to a plausible one
hides a pipeline fault". That is exactly what is happening, and it is working as designed.

**Consequence, stated plainly: the E2E Safety Net cannot go green from Lane 6.** The fix
belongs to whoever owns the valuation pipeline / the 2028 pick pricing, and the condition
blocks every PR that runs this job while the snapshot stands. **Classification: D —
external/infrastructure blocker, on main.** Not fixed here, not worked around, and the
preflight gate was not weakened.

## Addendum — the PR Validation hard-gate failure at `ed4c0f64c`

Different failure, and this one **is** partly this PR's:

```
tests/api/test_public_league_privacy_boundary.py::TestPrivateSectionsAreClosedToAnonymousCallers
  ::test_the_csv_variant_is_closed_too[rosTeamStrength]
  AssertionError: rosTeamStrength.csv answered 429 anonymously
```

429 is the rate limiter, not an auth defect — the route is fine. `/api/auth/status` and
`/api/auth/login` are both in `server.py::_PUBLIC_API_EXACT`, so they spend from a
**60/min per-IP budget shared by the entire suite**, and under `TestClient` every test is
the same client IP. This PR's two new files add roughly sixty such calls; the suite runs
them alphabetically *before* `test_public_league_*`, and the accumulated budget then runs
out inside an unrelated test, which fails on 429 instead of its real assertion.

The test passes in isolation (9/9) — the failure is purely cumulative.

Repaired at the source of the pressure rather than at the victim: both new test modules
now carry an autouse fixture calling `rate_limit.reset_for_tests()`, the limiter's own
sanctioned test hook. Production rate limiting is unchanged and no assertion anywhere is
weakened; one module's request volume simply stops becoming another module's failure.

---

## The 429 privacy-boundary red: measured cause, base vs branch

**Request under test:** anonymous `GET /api/public/league/rosTeamStrength.csv`
**Test:** `tests/api/test_public_league_privacy_boundary.py::TestPrivateSectionsAreClosedToAnonymousCallers::test_the_csv_variant_is_closed_too[rosTeamStrength]`

*(Traffic control cited this as `tests/guardrails/test_public_league_privacy_boundary.py::test_private_v1_endpoint_is_protected_server_side[rosTeamStrength.csv]`. No `tests/guardrails/` directory and no test of that name exist on this branch or on `origin/main`; the file CI actually names is the one above. Same request, same assertion — recorded only so the citation resolves.)*

### The ordering, from source

`server.py::_private_api_gate` does two things in this order:

1. **rate-limit** — only when `_is_public_api_path(path)`;
2. **blanket 401 auth gate** — only when **NOT** `_is_public_api_path(path)`.

`"/api/public/league"` is in `_PUBLIC_API_PREFIXES`, so this path takes branch 1 and
never takes branch 2. The 401/403/404 the test expects therefore comes from the
**handler's own per-section privacy check**, downstream of the middleware — and a
429 short-circuits before the handler ever runs.

### Measured, in one process, both refs

| | fresh limiter | limiter exhausted | after reset | 429 body |
|---|---|---|---|---|
| **branch `23b3077fc`** | **401** | **429** | **401** | `error`, `message`, `retryAfterSeconds` |
| **base `origin/main` 478d249ef** | **401** | **429** | **401** | `error`, `message`, `retryAfterSeconds` |

**Identical on both.** The budget was exhausted by issuing 120 `/api/auth/status` calls,
which is what a long suite does incidentally.

### Classification

**C — the suite legitimately trips a rate limit before privacy evaluation.** Not **A**:
the ordering is byte-identical on base, and this PR touches no middleware, no
`_PUBLIC_API_*` set, no `_is_public_api_path`, and no limiter code. The *ordering* half is
also **B** (pre-existing, reproduced on clean main); what #1086 contributes is ~60 extra
rate-limited `/api/auth/*` calls earlier in suite order, which is what tips the shared
60/min per-IP budget over before this test runs.

### The privacy invariant HOLDS, and 429 was NOT allowlisted

- With a fresh limiter the boundary answers **401** — fail-closed, correctly.
- The 429 response body carries **only** `error` / `message` / `retryAfterSeconds`. No
  league payload, no section data, no manager intelligence. The private resource does not
  become observable because the response is 429; it becomes *less* reachable.
- No status code was added to any expected-status allowlist, and no assertion was relaxed.

The repair is upstream of the symptom: this PR's two new test modules reset the limiter
they perturb (`rate_limit.reset_for_tests()`, the limiter's own sanctioned hook), so one
module's request volume stops becoming another module's failure. Production rate limiting
is untouched.

### Validation after the repair

`tests/api/test_public_league_privacy_boundary.py` 15 passed / 12 skipped ·
nav-gated + feature-flag reachability + guest-pass evidence + private-auth **116 passed** ·
`tests/api/` end to end (contains both new modules **and** this victim, in CI's ordering)
**2201 passed, 0 failed** · frontend nav/shell + V1-108 route-gate **71 passed** ·
planning integrity, decision coercions, `ruff check .`, `ruff format --check .` all clean.
