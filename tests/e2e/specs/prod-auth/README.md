# Production-auth verification specs

Playwright specs that run against the **DEPLOYED production site** with a
real authenticated session, closing the "needs a browser + a session"
half of five V1 verification rows. They are the L3/L4 browser evidence
the offline instruments (`scripts/verify_lineup_production.py`, the
recipe docs) explicitly cannot produce.

## What each spec proves

| spec | row | proves, against the deployed SHA |
|---|---|---|
| `v1-131-nav-gating.spec.js` | V1-131 | `/api/auth/status` publishes a boolean `features.consensusEdge.available` that AGREES with the board endpoint, and every nav offer surface (desktop Market menu, mobile drawer at 390×844, command palette, `/more` site map, DOM-wide anchors) honours it — with the negative control that the Market group's ungated entries still render, the network invariant (zero `/api/consensus-edge/*` requests and exactly one `/api/auth/status` on a private-route reload), and direct navigation to `/consensus-edge` still rendering its own `<h1>`. Both branches are implemented; annotations record which one the deployed build exercised. Recipe: `docs/master-site-audit/evidence/V1-131/L3_PRODUCTION_RECIPE.md` steps 4-8. |
| `v1-45-trade-surface.spec.js` | V1-45 | A trade built through the real `/trade` UI (team selected, players added via the page's own search, receiving roster chosen at the league's roster cap when one exists) produces the page's own `POST /api/trade/simulate`, and the rendered Final-roster section matches that response's `finalRosterSimulation` stamps field-for-field under the component's exact formatting — strength before/after/change, promotions/displacements, needs closed/opened, the cleanup (forced-release) count, plus the `rosterCapacity` banner's release count. The three backend states render distinguishably; only states the live league actually produced are asserted, recorded in `states-observed` annotations. Recipe: `docs/trade/V1_45_TRADE_CALCULATOR_L4_EVIDENCE_RECIPE.md` §4. |
| `v1-111-premium-rankings.spec.js` | V1-111 | On `/rankings` (both 1366×768 and 390×844) the `.psi-editorial` premium scope is present **and active** (its token remap measurably applied), the top row is the backend's rank-1 player with the backend's value under the page's own formatting, a sample of rendered rows matches the contract's (rank, name, value) stamps exactly (no client-side re-rank), buildRows' fail-fast never fired, and any visible partial-data row renders its missing state truthfully (annotated honestly when none is visible). |
| `v1-56-waivers-faab-strip.spec.js` | V1-56 | The `/waivers` league-FAAB context strip renders the mean/median from the page's **own** `faabAnalytics` fetch (formatting-aware equality, including a measured `$0` median rendered honestly), and a missing/empty analytics payload renders an explicit `—` unavailable state or no strip — never invented zeros. The state the live payload produced is annotated. |
| `v1-27-lineup-render.spec.js` | V1-27 / C2-U1 §10 item 2 | On the `/` war room, the Portfolio panel's starters list equals the authenticated contract's `sleeper.teams[].optimalLineup` stamp for the displayed team — slot sequence and player set, in the stamp's own order — the split-legend starter count equals the stamp's, unpriced players are excluded from both lists (upper-bound arithmetic when the live stamp has none, annotated rather than faked), and the truth-ladder note is absent iff the stamp came from live `rosterPositions`. On `/rosters`, the "Starters only" scope renders totals with no `starter-slots-unavailable` note exactly when every team is stamped. This is the one item `scripts/verify_lineup_production.py` marks "needs a browser". |

## Env contract

Both variables are **required**; without them every spec skips with an
explicit message (never fails, never silently passes):

| var | meaning |
|---|---|
| `PROD_ORIGIN` | production origin, e.g. `https://chaseupside.com` |
| `PROD_SESSION_COOKIE_FILE` | path to a file containing **only** the VALUE of the `jason_session` cookie, one line |

The cookie value is read by the shared fixture (`helpers.js`), attached
as an `httpOnly`/`secure`/`Lax` cookie on the browser context, verified
live against `/api/auth/status`, and **never logged or included in any
assertion message**. A cookie that fails to authenticate is a loud
FAILURE, not a skip — the workflow supplied credentials and they do not
work.

## Read-only guarantee

Navigation, DOM reads and network observation only. The single POST is
`/api/trade/simulate` — a pure computation endpoint that mutates no
league or user state. Where driving the UI would write user preferences
(the team switcher PUTs `/api/user/state`), the spec intercepts the
write and answers it locally so production state is never touched.

## Excluded from default runs

These specs are **not** part of the default local/CI e2e suite:

* `tests/e2e/playwright.config.js` carries `testIgnore: "**/prod-auth/**"`,
  so the default config's collection is unchanged by this directory;
* they are collected exclusively by **`tests/e2e/prod-auth.config.js`**
  (projects `prod-desktop` 1366×768, `prod-mobile` 390×844; no
  webServer, no global-setup, `retries: 0` so a production finding is
  never retried away), which only the production-verification CI
  workflow invokes:

```bash
npx playwright test --config tests/e2e/prod-auth.config.js
```

Run without the env vars, that command reports every test as skipped —
by design.
