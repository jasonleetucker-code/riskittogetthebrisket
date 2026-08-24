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
