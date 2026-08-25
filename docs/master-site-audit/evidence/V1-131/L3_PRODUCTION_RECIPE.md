# V1-131 — L3 production verification recipe

**Row:** "Nav does not offer a page whose endpoints all 503" (audit `F-25`, `C6-EDGE-01`
gating only) · **Level:** L3 · **Lane 6** · **No V1 status column edited.**

L3 = L1 plus the named checklist executed against the **deployed SHA**, evidence recorded.
Everything below runs against production. Record the SHA first; a run against an unknown
build proves nothing.

---

## What the change actually is

`/api/auth/status` — the shell's one existing capability probe — gained an additive,
read-only block:

```json
"features": { "consensusEdge": { "available": false } }
```

`available` is **not** the flag. It is `src/consensus_edge/api.py::is_available()`, the one
canonical predicate, which is `flag_enabled AND contract_loaded` — because the board
handlers 503 on **two** independent conditions (`feature_disabled`, `data_not_ready`), and a
flag-keyed nav would advertise a dead page for the whole window where the flag is on and the
data is not.

The nav gate offers a capability-tagged destination only on `available === true`. Every other
state — missing block, `null`, `{}`, a bare boolean, a truthy non-boolean — is unknown, and
unknown is not offered.

## Recipe

1. **Record the deployed SHA.**
   `curl -s https://<host>/api/status | jq -r '.deployedSha // .version // .'`
   Capture verbatim into the evidence file.

2. **`/api/auth/status` publishes the truthful capability.** As an authenticated user:
   ```bash
   curl -s -b "<session cookie>" https://<host>/api/auth/status | jq '.features'
   ```
   Expect `{"consensusEdge":{"available":<bool>}}`. Assert the value is a **real boolean**,
   and that the block is present. A missing `features` key means an older build is deployed —
   the nav still fails closed, but this step has not been verified.

3. **Establish the production state of the feature.** Confirm what `available` is claiming:
   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' -b "<cookie>" https://<host>/api/consensus-edge/players
   ```
   * `503` → the board is unavailable, so `available` **must** be `false`.
   * `200` → the board serves, so `available` **must** be `true`.
   These must agree. Disagreement is the defect this row exists to prevent, and it is the
   one thing in this recipe that cannot be waved through.
   *(Expected on production today: `503`, because `consensus_edge` defaults off per ADR-023.)*

4. **Load the real shell as an authenticated user.** Sign in and open any private route
   (`/rankings` is fine). Wait for the shell to settle.

5. **The nav does not advertise the unavailable page.** With `available: false`, assert
   **all** of these — one is a half-check, because `NAV_MODEL` feeds five surfaces:
   * desktop top bar: the **Market** menu opens and contains **no** "Consensus Edge" item;
   * mobile drawer (≤768 px): same;
   * command palette (⌘K / `/`): typing `consensus` returns **no** navigation target;
   * `/more` site map: no "Consensus Edge" link;
   * DOM-wide: `document.querySelectorAll('a[href="/consensus-edge"]').length === 0`.

   And the negative control, so this is not passing because the nav is broken generally: the
   **Market** group is still present with "Source Disagreement", "Sharp Tracker" and "Sharp
   Roster Percentage".

6. **No extra shell-level request was introduced.** Open DevTools → Network, hard-reload a
   private route, and filter on `consensus-edge`. Expect **zero** requests. The whole reason
   the capability rides `/api/auth/status` is that a second per-page probe would erode
   `V1-108` (VERIFIED). Also confirm `/api/auth/status` is still requested **once**.

7. **Ordinary auth/admin state is unchanged.** In the same `/api/auth/status` response:
   `authenticated`, `username`, `displayName`, `isAdmin`, `authMethod` all as before; the
   System menu still shows the Ops section for an allowlisted admin and hides it for a
   non-admin; a signed-out response is still exactly `{"authenticated": false}` with no
   `features` block (the logged-out nav filters `/consensus-edge` by
   `isPublicPath` already).

8. **The route itself is still reachable.** Navigate directly to `https://<host>/consensus-edge`.
   It must still load and render its own `<h1>` — gating removes the **offer**, never the
   route, so an operator running with `RISKIT_FEATURE_CONSENSUS_EDGE=1` keeps their
   evaluation path. (With the flag off the page will show its own truthful unavailable state;
   what must not happen is a blank "Chase Upside" header.)

9. **Optional, if an operator can toggle the flag on a staging box:** set
   `RISKIT_FEATURE_CONSENSUS_EDGE=1`, restart (flag reads are process-cached), confirm
   `available` flips to `true` **and** the nav entry appears. This is the only step that
   proves the gate is not simply hardcoded off. If production cannot be toggled, note it —
   `tests/api/test_nav_gated_features.py::test_capability_and_the_board_never_disagree`
   covers both directions deterministically.

10. **Record** the SHA, the `features` block, the board endpoint status, the five nav
    assertions, the network-tab result and the auth/admin comparison into
    `docs/master-site-audit/evidence/V1-131/`.

## What this recipe does NOT cover

`V1-131` is **gating only**. Consensus Edge's methodology, scoring, source weights,
calibration and flag default are all untouched and out of scope; the feature stays post-V1.
A production run that finds the board *working* and the nav *offering it* is a **pass**, not
a failure — the invariant is agreement, not absence.

## Local evidence already recorded (L1/L2)

* Backend `tests/api/test_nav_gated_features.py` — 23 tests: the four-way
  flag × contract availability matrix, capability/router agreement in every combination,
  fail-closed on an unresolvable capability, real-boolean wire shape, the signed-out response
  unchanged, and the documented `/methodology` exception.
* Model `frontend/__tests__/nav-capability-gating.test.js` — 14 tests across all five offer
  surfaces, six not-offered states.
* Chain `frontend/__tests__/components/shell/nav-capability-chain.test.jsx` — 10 tests:
  `useAuth` publishes only authoritative capabilities, the rendered chrome honours it, and a
  structural guard that no shell module fetches a Consensus Edge endpoint.
* Mutation: forcing `available = True` regardless of canonical state → **11 of 23 RED**;
  reading a bare truthy in the frontend gate → **4 RED**; both restored GREEN.
* Live, on a local production build: `features {"consensusEdge":{"available":false}}`,
  board `503`, **0** nav links, **0** shell requests to `/api/consensus-edge/*`.
