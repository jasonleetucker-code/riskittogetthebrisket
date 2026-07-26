# E2E assertion audit — the "looks correct, checks nothing" family

**Status: inventory only. No fixes applied.** Each finding names the
file:line and the specific input under which the check gives the wrong
answer. One-line fixes are stated but not made, so the queue can decide
what rides an existing follow-up versus what needs its own change.

## Why this sweep happened

Three defects of one shape turned up inside a week:

| Defect | Why it was invisible |
|---|---|
| `waivers-smoke` asserted `/Waivers/i` on `body` | "Waivers" is a nav label on **every** authenticated page |
| `/trades` waited for a loading sentinel R4 had replaced with a skeleton | A negated `waitForFunction` whose sentinel is gone resolves **immediately** |
| `e2e.yml` declared `E2E_PAGE_ORIGIN` twice | Valid YAML to `yaml.safe_load`; GitHub rejects duplicate keys, so the workflow **never once parsed** |

The shape: **the artifact looks correct** — an ARIA attribute, a
`waitFor`, valid YAML — while the check underneath is unfalsifiable.
Standard review does not catch these, because reading the line tells
you what it *intends*.

## Method

Findings below are **measured, not reasoned**. Two probes against a
live stack:

1. **Vacuity probe.** Load the real page, then re-test each regex
   against the page with `<main>` deleted entirely — simulating "the
   page's own content never rendered". If the regex still matches the
   surviving chrome, the assertion cannot detect a blank page.
   (`toContainText` reads `textContent`, which includes hidden nodes.)
2. **Wait probe.** Measure how long each sentinel wait actually
   blocks, and whether the sentinel is ever visible at DOM-content-loaded.

---

## Q1 — Assertions that pass when the thing they name is absent

### A1. `signed-in-smoke.spec.js:47` — `/trade` renders

```js
await expect(authedPage.locator("body")).toContainText(/Trade|Side/i)
```

`Trade` is a top-level nav group label, present in the DOM on every
authenticated page. **Measured: passes with `<main>` removed.**

*Wrong answer under:* `/trade` renders an empty shell, a crashed
component, or the wrong page entirely — all still green.
*One-liner:* `getByRole("heading", { level: 1, name: /Trade Builder/i })`.

### A2. `signed-in-smoke.spec.js:54` — `/rosters` renders
`/Roster|Team/i` — `Roster` is a nav group label. **Measured vacuous.**
*One-liner:* assert the page's `h1` instead.

### A3. `signed-in-smoke.spec.js:61` — `/settings` renders
`/Settings|Notification|Signal/i` — `Settings` appears in the shell.
**Measured vacuous.**
*One-liner:* `getByRole("heading", { level: 1, name: /Settings/i })`, or
reuse the non-vacuous `/Ranking Sources/i` that
`journey-settings-overrides.spec.js:37` already uses (**measured NOT
vacuous** — it is main-content-only).

### A4. `journey-trade.spec.js:61` — `/finder` renders
`/Finder/i`. **Measured vacuous.** The following row assertions
(lines 67-76) are genuinely data-driven, so the *test* still has teeth —
but this line contributes nothing and would not be the assertion that
fails first.

### A5. `journey-news.spec.js:41` — `/news` renders
`/news/i` — `News` is a top-level nav label **and** a mobile tab.
**Measured vacuous.** The follow-up length check (`> 200` chars) is
also satisfied by chrome alone.
*One-liner:* assert the `h1`, or a `data-testid` on the digest list.

### A6. `critical-smoke.spec.js:100-104` — auth-gated routes redirect

```js
expect(url.includes("/login") || body.length > 0).toBeTruthy()
```

**The most serious finding.** The right-hand side of the `||` is true
for any rendered HTML page, so the disjunction is unfalsifiable. A test
named *"auth-gated routes redirect to /login"* **cannot detect an
auth-gate failure.**

*Wrong answer under:* the gate stops redirecting and serves private
pages to anonymous visitors — this test stays green. That is a privacy
regression, and this is the only test claiming to cover it.

*Verified the gate is healthy today* (not a live hole):
`/rankings` and `/settings` both `302 → /login?next=…`.
*One-liner:* drop the `||` and assert `url.includes("/login")`.

### A7. `critical-smoke.spec.js:21` — anonymous `/` renders
`{ path: "/", mustHave: /Brisket/i }` — the brand is chrome on every
route and auth state, so this cannot detect an empty `<main>`. This one
is a **deliberate, documented** trade-off (the check exists to prove the
route responds at all, and I wrote that comment) — listed for
completeness, not as a bug. Note it is strictly weaker than the
`/Risk It/i` it replaced, which at least came from page copy.

### A8. `journey-trade.spec.js:101` — finder returns trades

```js
for (const trade of body.trades.slice(0, 5)) { … }
```

Zero trades ⇒ the loop body never executes ⇒ every assertion inside is
skipped and the test passes. A test named *"returns arbitrage trades for
a real roster"* is green when the engine returns none.

*Wrong answer under:* the exact regression this suite exists to catch —
the finder silently dropping every asset (which **has happened**: the
IDP-market bug fixed in #556).
*One-liner:* add `expect(body.trades.length).toBeGreaterThan(0)` before
the loop.

---

### A9. `--reporter` on the CLI silently unloads every reporter guard

**Found while shipping the fixes in this PR, and it invalidated my own
earlier verification.**

Playwright's `--reporter` flag **replaces** the entire `reporter` array
from `playwright.config.js`. Passing `--reporter=line` therefore
unloads `tests/e2e/stack-death-reporter.js` — the mid-run abort guard —
and nothing warns you. The run looks completely normal.

*How it was caught:* a module-level `process.stderr.write` in the
reporter printed **nothing** with `--reporter=line` and printed
immediately without it. So the guard's module was never even loaded.

*Why it matters beyond the flag:* when I first shipped that guard I
reported "verified: the guard stayed silent on a healthy full run".
That evidence was worthless — my runner scripts all passed
`--reporter=line`, so silence meant *never invoked*, not *invoked and
correctly quiet*. **A guard that is never loaded and a guard that
correctly does nothing produce identical output.** Same shape as the
workflow that never parsed.

*Impact:* none in CI — `npm run e2e` and `.github/workflows/e2e.yml`
do not pass the flag, so the nightly is genuinely guarded (re-verified).
`prod-e2e-smoke.yml:102` does pass it, so the guard is inert there;
that run targets an external stack the guard deliberately skips anyway.

*Fix applied here:* documented as a load-bearing constraint in the
reporter's header. There is no way to force a config reporter to
survive the CLI override, so the durable answer is that entry points
must not pass `--reporter`.

*Lesson for this audit:* verifying a guard requires proving it **ran**,
not observing that it was quiet.

## Q2 — Waits that complete without the condition being met

### B1. `public-league.spec.js:46` and `public-league-visual.spec.js:45`

```js
await page.waitForFunction(
  () => !document.body.innerText.includes("Loading league data..."), …)
```

**This is the `/trades` skeleton bug, still live, in two more places.**
`/league` now server-renders with real data (`app/league/page.jsx:4`
says so explicitly: *"no 'Loading league data…' flash"*), so the
sentinel is **never visible** and the negation is true on first
evaluation.

**Measured:**

| Route | Sentinel visible at DCL | Wait blocked for |
|---|---|---|
| `/league?tab=overview` | false | **132 ms** |
| `/league?tab=records` | false | **95 ms** |
| `/league` | false | **158 ms** |

~100 ms is the polling floor — these waits are **no-ops today**.

*Wrong answer under:* any assertion placed after them that races the
data. `visitLeague`'s optional second wait (`waitForText`) is genuinely
data-driven and is currently the only thing keeping those tests honest;
calls that omit it (`public-league.spec.js:62`, and every
`public-league-visual` case) are unprotected.
*One-liner:* wait for real settled content instead — the same fix
already applied to `/trades` in `journey-trade.spec.js:49-52`.

### B2. `public-league-visual.spec.js:88, 95, 102, 109` — snapshot target

```js
const card = page.locator("section").first();
```

The **first** `<section>` on the page, not the selected tab's card. It
is present regardless of whether the tab's content loaded, and combined
with B1 (no real wait) the pixel baseline may be captured against the
wrong element or a half-rendered one.

*Wrong answer under:* a tab that renders nothing — the snapshot still
matches whatever the first section is.
*Note:* these are `--ignore-snapshots` in CI today, so this is latent
rather than active. Worth fixing before baselines are ever committed.

---

## Q3 — Tests that can be skipped without anyone noticing

Baseline today: **29 skipped / ~149 passed**. A run reporting 140
skipped is still green.

| # | Location | Gate | If the gate silently flips |
|---|---|---|---|
| C1 | `helpers/journey.js:150,158` | project (`desktopOnly`/`mobileOnly`) | Intended; accounts for most of the 29. A project-name change would silently skip a whole layer. |
| C2 | `helpers/auth-fixture.js:27,34` | `E2E_TEST_SECRET` unset **or** endpoint 404 | **Whole signed-in suite skips, run green.** *Mitigated:* `global-setup.js` now hard-fails when `/api/test/create-session` doesn't return 200, so this can no longer pass unnoticed. Keep that guard. |
| C3 | `journey-news.spec.js:27` | `/news` returns 404 → skip | **Now stale and actively harmful.** `/news` shipped in #533; a regression back to 404 would report as a *skip*, not a failure. *One-liner:* delete the branch and assert the route exists. |
| C4 | `journey-trade.spec.js:87` | `sleeper.teams` empty → skip | Masks exactly the documented multi-league failure mode (`sleeperDataReady: false`). Should fail, not skip. |
| C5 | `public-league.spec.js:126, 196, 209` | empty rivalries / matchups / players → skip | An empty public-league pipeline is a regression; these three report it as "nothing to test". |
| C6 | `journey-settings-overrides.spec.js:116` | override endpoint degraded → skip | Mine, and honest — but a *persistent* override failure shows as a permanent skip. Needs a floor on consecutive skips, or removal once the endpoint is reliable. |

**Structural answer (already agreed, held for the #559 follow-up):** a
minimum-executed-tests assertion in the reporter — fail the run if
passed < N or skipped > M. That converts every row above from "silent"
to "loud" without needing each one fixed first.

---

## The two "under watch" failures — resolved

Both were re-run **6× each in isolation against a healthy stack: 6/6
pass, 0 failures.** Neither is a product defect; both are test-side.

### D1. `journey-settings-overrides` — "toggling a source …"

**Verdict: test weakness (budget + incomplete degrade detection).**
Not a product defect. The journey triggers two full blend recomputes
server-side; under load the badge misses its budget. The degrade-skip I
added at line 116 only fires when the app logged its
`falling through to base contract` warning — if the browser-side fetch
simply times out without that warning, the test fails instead of
skipping. *Fix:* detect the degrade from the response/state rather than
the console warning, or widen the budget.

### D2. `public-league` — "franchise deep link via `?owner=`"

**Verdict: under-budgeted wait, collateral from a known product defect.
Not a franchise-feature bug.**

Measured directly:

```
/league?tab=franchise&owner=… → 200 in 15.78 s
```

against `visitLeague`'s `waitForText` budget of **15 s**
(`public-league.spec.js:52-56`). The test sits *below the page's own
render time* and passes only when the route happens to be warm.

This is the `/league` SSR slowness already filed as **#555 item 3**
(7-19 s, exceeding the proxy's 5 s timeout). The test failure is a
symptom of that, surfacing as a franchise-feature failure.
*Fix (test side):* raise the budget above the measured p100. *Real
fix:* #555 item 3.

---

## What shipped with this document

Three fixes only — each a one-liner, each covering a regression class
nothing else covers:

| Finding | Change |
|---|---|
| **A6** auth-gate disjunction | `expect(url).toContain("/login")` — the `\|\|` is gone |
| **C3** `/news` 404 skip | Skip removed; the route existing is now asserted |
| **A8** finder empty array | `expect(body.trades.length).toBeGreaterThan(0)` before the loop |

Plus the structural answer to Q3: a **coverage floor** in
`stack-death-reporter.js`. It fails the run when `passed < 100` or
`skipped > 60`, against the measured baseline of ~149 passed / 29
skipped. A failure, not a warning — a warning inside a green run is
something nobody reads. Overridable via `E2E_MIN_PASSED` /
`E2E_MAX_SKIPPED` when the suite's real size changes.

### Verification

- Floor **fires** on a deliberately tiny run: 1 passed → banner, exit 1.
- Floor **stays silent** on a full run: 145 passed / 30 skipped / 3
  failed, no banner. Both directions checked, because a guard that
  only ever fires is as useless as one that never does.
- The auth-gate fix passes on **all 8** gated routes — the stricter
  assertion found no gaps and introduced no failures.
- Full-suite failures dropped 9 → 3 once the frontend build matched the
  branch; the 6 extra were a stale build, confirmed by rebuilding
  rather than assumed. The remaining 3 are a navigation race
  (`ERR_ABORTED`) and two load-sensitive specs — notably including
  `public-league-visual`, one of the suites whose settling wait is a
  no-op per **B1**.

## Not changed, deliberately

Everything else above is left as findings. The five vacuous
chrome-matching assertions, the `section`-locator snapshot target, and
the remaining skip gates are all real, but they are a **batch of
assertion rewrites** and deserve their own review rather than riding a
PR whose point is the audit.

`/league` SSR performance is explicitly **not** touched here. The
15.78 s measurement belongs to #555 item 3, where that work is filed.
Widening the test's 15 s budget would paper over a real product defect;
the reclassification is worth more than the green.
