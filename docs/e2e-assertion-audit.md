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

---
---

# Part 2 — the rewrite batch (2026-07-27)

**Status: fixes applied.** This is the follow-up Part 1 deferred
("*a batch of assertion rewrites … deserve their own review*"). Every
finding below is either a Part 1 item now fixed, or a new finding this
pass turned up.

Branch `claude/e2e-assertion-honesty`, base `57b030b01`.

## P2.0 — The recipe in the README never ran on a clean checkout

Before any assertion could be judged, the suite had to run. It did not.

`npm run e2e` on a clean checkout:

```
[preflight] Python compile checks passed
Traceback (most recent call last):
  File ".../scripts/validate_api_contract.py", line 45, in main
    payload, source_file = _load_latest_payload(repo_root)
  File ".../scripts/validate_api_contract.py", line 26, in _load_latest_payload
    raise FileNotFoundError(
FileNotFoundError: No dynasty_data_YYYY-MM-DD.json files found in repo/data or repo root.
```

`preflight.py::main()` ran `_run_contract_validation()` **before**
`_seed_data_cache()`. The validator hard-fails without
`data/dynasty_data_*.json`; `data/` is gitignored (`.gitignore:45`), so
on a clean checkout there is never one, and the seeding step that would
have supplied it never got to run. Zero specs executed.

It looked fine only on machines already carrying a snapshot from an
earlier local scrape — neither the shared checkout nor a fresh worktree
of `origin/main` had one:

```
$ ls data/dynasty_data_*.json
ls: cannot access 'data/dynasty_data_*.json': No such file or directory
```

**Fixed** — seed first, then validate (so the validation also runs
against the exact file the backend will serve):

```
[preflight] seeded data/dynasty_data_2026-07-26.json from committed exports/latest/ (1077 players)
[contract] ok=True errors=0 warnings=2 players=1095
[preflight] API contract validation passed
[e2e] stack verified — 1095 players served, test sessions enabled, snapshot loaded
Running 178 tests using 2 workers
```

This dominates the rest of the audit: a green nobody can reproduce from
a clean checkout is not a safety net.

## P2.1 — Proving the rewrites are non-vacuous

An assertion is vacuous if it cannot distinguish *"the page I named
rendered"* from *"some other page rendered"*. So each original
assertion and its replacement were run against a **decoy** — a real,
working authed page (`/settings`) carrying the same shell chrome.

* original **passes** on the decoy ⇒ it was matching chrome
* replacement **fails** on the decoy ⇒ it is anchored to the real page

This needs no app-code edits (owned by another agent tonight) and is
deterministic. Harness output, verbatim:

```
Running 10 tests using 1 worker
  ✓  1 › OLD /rosters assertion passes on the DECOY page (=> vacuous) (9.0s)
  ✘  2 › NEW /rosters assertion FAILS on the DECOY page (=> real) (17.7s)
  ✓  3 › OLD /trade assertion passes on the DECOY page (=> vacuous) (10.2s)
  ✘  4 › NEW /trade assertion FAILS on the DECOY page (=> real) (21.7s)
  ✓  5 › OLD home assertion passes on the DECOY page (=> vacuous) (7.2s)
  ✘  6 › NEW home assertion FAILS on the DECOY page (=> real) (15.0s)
  ✓  7 › OLD locator is satisfied WITHOUT opening any tab (=> vacuous) (8.7s)
  ✓  8 › OLD opener silently no-ops on a NONEXISTENT tab (=> vacuous) (9.1s)
  ✘  9 › NEW opener FAILS on a NONEXISTENT tab (=> real) (25.2s)
  ✓ 10 › OLD assertion passes with NO filter applied at all (=> vacuous) (17.7s)
```

Six passes (every "the old assertion is vacuous" demonstration) and four
failures (every "the new assertion is real" demonstration) — exactly the
designed outcome. Sample failure, showing the replacement genuinely
discriminating:

```
1) NEW /rosters assertion FAILS on the DECOY page (=> real)
   Error: expect(locator).toBeVisible() failed
   Locator: getByRole('heading', { name: /Roster Dashboard/i, level: 1 })
   Expected: visible
   Error: element(s) not found
```

The harness was deleted after the run; it is reproduced here rather
than committed.

## P2.2 — What was replaced

| Part 1 ref | File | Change |
|---|---|---|
| A2 | `signed-in-smoke.spec.js` | `/Roster\|Team/i` → page `<h1>` "Roster Dashboard" **+** one ranked row per contract team, every real team name present |
| A1 | `signed-in-smoke.spec.js` | `/Trade\|Side/i` → page `<h1>` "Trade Builder" + player pool loaded + "Clear Trade" control |
| A3 | `signed-in-smoke.spec.js` | `/Settings\|Notification\|Signal/i` → page `<h1>` "Settings" + source-toggle count ≥ the backend registry count |
| — | `signed-in-smoke.spec.js` | home `/…\|Team/i` → dashboard command bar + team switcher listing **exactly** the contract's 12 teams |
| B2 | `public-league-visual.spec.js` | `section`-first locator → tab button hard-asserted, section's own content waited on, per-section data assertions (e.g. Records must list a `(YYYY wk N)` entry) |
| — | `public-league.spec.js` | "archives filter narrows the result set" now actually applies a filter and requires a strictly smaller row count |
| — | `public-league.spec.js` | tab walk no longer sleeps; asserts every tab control exists and the page survives the walk |
| C4 | `journey-trade.spec.js` | `test.skip(teams.length === 0)` → assertion that rosters are present |
| C5 | `public-league.spec.js` | three `test.skip`s (rivalries / matchups / players) → assertions that the data is present |

Two assertions are **kept and documented rather than "fixed"**, because
changing them would trade real signal for cosmetics:

* **A7** — `critical-smoke`'s `/` → `/Brisket/i`. Chrome-matching, but
  the test's load-bearing assertion is "no JS errors on this route",
  and the marker only needs to prove the route responded.
* **`expect.soft` in `attachConsoleGuards`** — soft assertions still
  mark a test failed in Playwright; they only defer the throw. Not an
  optional assertion, correctly used.

## P2.3 — Skip gates: the measured answer

The brief's list was close but not exact. **`journey-news.spec.js` has
no skip** (removed in Part 1), and two cited line numbers are comments.
Verified inventory and, crucially, **which ones actually fired** in a
full run:

| # | Site | Category | Fires? |
|---|---|---|---|
| 1-2 | `journey.js:150,158` `desktopOnly`/`mobileOnly` | project gate | fires on the opposite project only — **29 of the 30 baseline skips** |
| 3-4 | `auth-fixture.js:27,34` | env gate | never here (`playwright.config.js:78` defaults the secret) |
| 5 | `journey-trade.spec.js:87` | data gate | **never** → converted to assertion |
| 6-8 | `public-league.spec.js:126,196,209` | data gate | **never** → converted to assertions |
| 9-10 | visual specs, `SKIP_VISUAL_REGRESSION` | env gate | never in `npm run e2e` |
| 11 | `public-league-visual.spec.js:81` | project gate | fires on mobile only |
| 12 | `journey-settings-overrides.spec.js:116` | conditional escape hatch | **fires** — see below |
| 13-14 | `critical-smoke.spec.js:169,176` | **dead** | never runs |

### Counts

| Category | Count |
|---|---|
| Legitimate project/env gate (kept) | 8 |
| Data gate that never fires (converted to assertions) | 4 |
| Conditional escape hatch (kept, fires in practice) | 1 |
| Dead / unreachable test body | 2 |

### Evidence the four data gates never fire

Against the stack seeded from the committed snapshot:

```
rivalries  len=45
matchups   len=158
players    len=968   sample: {"playerId":"10213","playerName":"Tre Tucker","position":"WR"}
sleeper teams: 12  ['Blaine','Brent','Collin','Ed','Eric','Jason',
                    'Joey','Kich','MaKayla','Roy','Ty','jstuedle']
```

### The actual skip list from the reporter (not inferred)

Baseline run, parsed from the JSON reporter — **30 skipped, and 29 of
them are project gating**:

```
TOTAL SKIPPED: 30
    9  [mobile-chromium] chart-visual-regression.spec.js
    6  [mobile-chromium] journey-rankings.spec.js
    4  [mobile-chromium] journey-trade.spec.js
    4  [mobile-chromium] public-league-visual.spec.js
    3  [desktop-1366]    mobile-smoke.spec.js
    2  [mobile-chromium] journey-settings-overrides.spec.js
    1  [mobile-chromium] journey-news.spec.js
    1  [desktop-1366]    journey-settings-overrides.spec.js   ← NOT a project gate
```

That last row is gate #12, and its recorded reason is:

```
"override endpoint degraded to base-contract fallback on this run
 ([dynasty-data] /api/rankings/overrides request failed: Failed to fetch)
 — round-trip already asserted"
```

So **C6 fires routinely in this environment**, not rarely. It is honest
(the round-trip itself is hard-asserted above it), but Part 1's warning
stands: a *persistent* override failure shows up as a permanent skip.
The root cause is §3.3 below, not the override engine.

### #13/#14 are worse than skips

```js
if (res.status() === 401) {
  test.info().annotations.push({ type: "skip", description: "..." });
  return;
}
```

That is not `test.skip` — Playwright reports the test **passed**. So
these two do not even appear in the skip list above; they are invisible
in both the pass count and the skip count. `/api/terminal` is
permanently 401 anonymous (the test's own comment says it moved to the
auth-gated set), so every assertion below that line is unreachable.
Left in place with the dead-code status recorded here rather than
deleted in the same PR as the rewrites — but they should be deleted or
re-pointed at an authenticated session; they are currently two green
ticks that verify nothing.

## P2.4 — New coverage

The 33-entry selector registry in `helpers/journey.js` is a map of what
the redesign must not break. Only **9** entries were referenced by any
spec:

```
$ grep -rho "SEL\.[a-zA-Z]*" tests/e2e/specs/ | sort | uniq -c | sort -rn
      3 SEL.overlaySheet   2 SEL.searchInput   2 SEL.posSelect
      2 SEL.playerName     2 SEL.boardRow      1 SEL.tradeLedgerEntry
      1 SEL.searchResultName  1 SEL.searchResult  1 SEL.navSearchButton
```

The 25 unused entries name the untested surfaces exactly. Two new spec
files close the highest-value part of that gap — chosen for blast radius
(valuation arithmetic and the diagnostics you'd use to notice a break),
not for count:

**`api-trade-intelligence.spec.js`** — neither endpoint had any e2e
coverage.

* `GET /api/draft-capital`: pick board must be exactly
  `numTeams × draftRounds` (72 = 12 × 6); every pick owned and priced;
  **round-1 mean value must exceed the last round's** — the core pick-
  curve property, and one that survives the nightly snapshot refresh;
  every `isTraded` pick must actually have changed hands.
* `POST /api/trade/suggestions`: asserts `totalSuggestions > 0` *before*
  iterating (the A8 trap — the engine returned 0 with no opponent
  rosters, and a loop over an empty array proves nothing); every asset
  `boardRank ≤ 150`, matching the `boardTopNFilter: 150` the response
  advertises; and **every give-side player must be on the submitted
  roster** — you cannot trade away someone you do not own.

**`journey-tools-health.spec.js`** — `/tools/source-health` appeared in
no spec; `/tools/trade-coverage` appeared only in the anonymous-redirect
list.

* `/tools/source-health`: source names rendered must match
  `source_health.source_runtime.enabled_sources` from `/api/status`.
  Both states are pinned — when the backend reports zero enabled
  sources the strip must render *nothing* (its documented contract at
  `SourceHealthStrip.jsx:129`), rather than the test skipping.
* `/tools/trade-coverage`: exactly one audit row per contract team, all
  12 real names present, the scan counter must reach `12/12`, and every
  team's player count must be a positive integer.

Both files are gated `desktopOnly` and derive every expectation from a
payload fetched inside the test — no hardcoded names, nothing that
breaks when the snapshot refreshes.

## P2.5 — New environment findings (§3)

### §3.1 The suite's page topology is not production's — in both directions

**Corrected after the #578 handoff, which supplied the nginx half.**
My first pass filed this as "`/api/terminal` has no Next proxy route".
That is true but it is the less important half, and read alone it points
at the wrong culprit.

Production nginx (`deploy/nginx/chaseupside-proxy.conf`):

```
location /api/ { proxy_pass http://dynasty_backend;  }
location /     { proxy_pass http://dynasty_frontend; }
```

So in production **`/api/*` never reaches Next at all**. The 22 route
handlers under `frontend/app/api/**` do not serve a single production
request — even `/api/dynasty-data`, which the backend implements itself
(`server.py:3084`).

The suite does the opposite. `global-setup.js:227` and `pageUrl()` send
page navigation to `E2E_PAGE_ORIGIN || http://127.0.0.1:3000` — the Next
origin, with no reverse proxy in front — so a relative `fetch("/api/…")`
from the browser lands on Next. Two consequences, and the second is the
one that matters:

1. **404s at the Next origin are test artifacts, not product bugs.**
   `/api/terminal`, `/api/leagues`, `/api/user/state` and `/api/health`
   have no Next handler, so they 404 here and work fine in production.
   Observed on a signed-in dashboard load:

```
404 http://127.0.0.1:3100/api/health
404 http://127.0.0.1:3100/api/user/state
404 http://127.0.0.1:3100/api/leagues
404 http://127.0.0.1:3100/api/terminal?windowDays=30
502 http://127.0.0.1:3100/api/auth/status
```

   The visible result: the signed-in dashboard renders **"Terminal data
   unavailable"** with `<h1>Pick your team</h1>` and every aggregate
   tile `—`; `/tools/trade-coverage` reports **"FETCH ERRORS 12"**.
   New specs therefore assert contract-derived content and explicitly
   do **not** assert terminal-derived values — stated in the spec
   comments rather than hidden.

2. **Every spec that passes *because* a `frontend/app/api/**` handler
   answered is false comfort.** That code does not run in production.
   It covers `/api/status`, `/api/auth/status`, `/api/rankings/overrides`,
   `/api/dynasty-data`, `/api/draft-capital`, `/api/angle/*`,
   `/api/trade/suggestions` and 15 more. A browser-driven assertion
   against any of them is exercising a routing arrangement that exists
   only in the test harness.

   This is why the new `api-trade-intelligence.spec.js` drives
   `/api/draft-capital` and `/api/trade/suggestions` through
   `page.request` (baseURL = the **backend**, port 8000) rather than
   through a page. That path matches what nginx does in production. It
   was originally chosen to dodge the §3.3 auth-status race; the
   topology argument is the stronger reason and is now the documented
   one.

**Recommended follow-up (not done here — it is a harness change, not an
assertion change):** give the suite a same-origin reverse proxy, so page
navigation and `/api/*` share one origin split the way nginx splits it.
Until then, treat any browser-observed `/api/*` behaviour as unverified
against production.

### §3.2 The suite silently reuses another checkout's stack

`playwright.config.js` sets `reuseExistingServer: true` for both
servers and `server.py` hardcodes `PORT = 8000`. In a multi-agent
container a run therefore tests **whatever build is already up**.
Observed mid-audit:

```
active_data_source.path =
  /home/user/.../worktrees/agent-ac26f9e0ef914b8f6/data/dynasty_data_2026-07-26.json
```

— a different agent's worktree. Every measurement in Part 2 was
re-taken against a frontend built from this branch on an isolated port
(`:3100`) to remove that contamination. The same hazard applies to any
CI runner that leaves a stale stack behind.

### §3.3 Next proxy routes abort at 3s and fall back to a silent null

`app/api/status/route.js` and `app/api/auth/status/route.js` both use a
hard `setTimeout(() => ctl.abort(), 3000)` and return 502 on timeout.
Components treat that as "no data" and render nothing —
`SourceHealthStrip` returns `null`, `useAuth` cannot confirm the
session and the shell renders logged-out chrome.

This is the mechanism behind the "load-sensitive" failures Part 1 filed
as D1/D2, and behind gate #12 firing routinely. It is a product-side
fragility, not a test defect; the new source-health spec spans one 60s
component refresh so it is deterministic rather than load-sensitive.

## P2.6 — Results, and the honest bottom line

### Before

Measured on `origin/main` + the preflight fix (without it, nothing runs
at all), against a frontend built from this branch on an isolated port:

```
  3 failed
  30 skipped
  145 passed (20.2m)
EXIT=1
```

**The suite was already red.** The premise that it was green does not
hold — Part 1 measured the same 145 / 30 / 3. The three failures were
the known load-sensitive pair (D1/D2) plus `/api/data returns 200`.

### After

```
  6 failed
  34 skipped
  146 passed (12.4m)
```

The +4 skips are exactly the two new spec files' four tests gating off
`mobile-chromium` (`desktopOnly`), which is the intended behaviour.

Of the six failures, **one was mine**: the rewritten home-dashboard test
asserted the top-bar team switcher, which is CSS-hidden at 390px where
`MobileChrome` takes over. Genuine viewport coupling, not flake — fixed
by gating that describe block to desktop, matching the existing
convention. Verified after the fix:

```
  ✓ [desktop-1366] home dashboard renders the war-room surface with a real team list (3.0s)
  ✓ [desktop-1366] trade builder renders its own page body, not just the nav link (3.1s)
  ✓ [desktop-1366] rosters page power-ranks every team in the contract (3.3s)
  ✓ [desktop-1366] settings page lists the real ranking-source registry (1.6s)
  - [mobile-chromium] (all four) — skipped, desktop journey
```

### The environment collapsed mid-session — and that is itself evidence

The remaining failures are not attributable to this branch, and the
proof is direct rather than inferred. The backend on `:8000` was booted
by a **different worktree** (§3.2). That worktree was reclaimed and
rebuilt underneath the still-running process:

```
$ ls -la .../worktrees/agent-ac26f9e0ef914b8f6/data/
-rw-r--r--  4096  session_store.sqlite
-rw-r--r--     0  user_kv.sqlite        <-- 0 bytes
(no dynasty_data_*.json at all)
```

A zombie backend: the process survives, its in-memory contract still
serves (`/api/data` → 1095 players, 12 teams), but every disk-backed
endpoint is now broken:

```
$ curl -b cookies http://127.0.0.1:8000/api/user/state
{"error":"internal_error","context":{"errorType":"OperationalError"}}   (a1=500 a2=500 a3=500)

$ curl -b cookies http://127.0.0.1:8000/api/draft-capital
{"error":"Draft data workbook not found or empty","leagueKey":"dynasty_main"}
```

`/api/user/state returns 200` **passed in the before baseline 20 minutes
earlier**, and this branch changes no backend code. Restarting that
process was not available (it belongs to another agent's workstream).

**This turned into the best available demonstration of the PR's point.**
`/api/draft-capital` silently lost its entire pick board. Before this
branch there was **no test on that endpoint at all**, so the regression
would have been completely invisible — a green run over a valuation
endpoint returning nothing. With the new spec:

```
  ✘ api: draft capital valuation › GET /api/draft-capital prices a complete,
    internally consistent pick board (587ms)

    Error: draft-capital returned no picks
    Expected: > 0
    Received:   0
```

That is the entire thesis of this document, observed live and by
accident: the difference between a suite that reports green and a suite
that tells you the truth.

### Is the green check trustworthy now?

**More than it was, and in specific, nameable ways — but not yet fully.**

Trustworthy now:

* The suite **runs at all** from a clean checkout (P2.0).
* The four signed-in page journeys can no longer pass on a blank page —
  proven against a decoy, not asserted (P2.1).
* The four `public-league-visual` tests assert something; previously,
  under the documented run command, they asserted nothing.
* Four permanently-off data gates are now assertions, so an empty
  pipeline fails instead of skipping green.
* Two untested high-blast-radius surfaces (pick valuation, trade
  suggestions) now have invariants that survive the nightly refresh.

Still NOT trustworthy, and these are the honest gaps:

1. **Browser-observed `/api/*` behaviour is unverified against
   production** (§3.1). The suite's page origin routes `/api/*` to Next
   handlers that serve zero production traffic. This is the largest
   remaining hole and it needs a harness change, not an assertion
   change.
2. **`critical-smoke.spec.js:169/176` still report green while executing
   nothing.** Two annotation-and-return blocks over permanently-401
   endpoints. Recorded, deliberately not fixed in the same PR as the
   rewrites.
3. **`/tools/ros-data-health`, `/intel`, `/trending`, `/angle`,
   `/draft`, `/league-comparison`, `/players/compare`, `/more` remain
   uncovered.** 25 of 33 selector-registry entries are still unused. The
   two new files close the highest-value part of the gap, not the gap.
4. **The suite silently reuses whatever stack is on :8000/:3000**
   (§3.2). Tonight that meant testing another worktree's build, and then
   a zombie. Until that is fixed, *any* run's provenance is unproven —
   which is a trust problem at least as large as any individual
   assertion.
5. **`/league` per-tab content is asserted four sections deep, not
   twelve** (§3.4), bounded by real SSR slowness rather than by choice.

### §3.5 The public-league privacy assertion: deliberately scoped

Raised by the #578 handoff, which changed `/league/phases` to fetch
`/api/data`. Verdict: **deliberately scoped, and left as-is.**

`visitLeague`'s `privateHits` listener watches only the page it
navigates to, and every caller navigates to `/league` or
`/league?tab=…`. Sibling routes under `/league/**` are unwatched.

That boundary is the right one. The assertion protects the *anonymous
public hub* — the surface a stranger lands on, which must never touch
the private contract. `/league/phases` fetching `/api/data` is correct:
the endpoint is auth-gated and anonymous visitors get an explicit
sign-in message, not data. Widening the listener to all of `/league/**`
would fail the suite on a feature working as designed, and would blur
what the assertion means.

What that leaves genuinely uncovered, stated plainly rather than
implied: **no test asserts that a `/league/**` sub-route refrains from
rendering private data to an anonymous visitor.** The *response* side is
covered — `multi-league.spec.js` and `critical-smoke.spec.js` both pin
`/api/data` → 401 without a session — so a leak would require the
endpoint's auth gate to fail first, which those tests would catch. The
uncovered case is narrow but real: a sub-route that fetches the private
contract *with* a valid session and renders it on a page reachable
without one. Recorded here rather than papered over.

The reasoning is duplicated in a comment above `visitLeague` so the next
person to widen it has to argue with it first.

### §3.4 `/league` sections hydrate too slowly for a rapid tab walk

Measured 2026-07-27: `/league` SSRs in **7.8s**, and its 2.6 MB payload
exceeds Next's data-cache ceiling, so nothing is cached:

```
Failed to set Next.js data cache for http://127.0.0.1:8000/api/public/league,
items over 2MB can not be cached (2674660 bytes)
```

A 12-tab walk clicking through at ~2.5s intervals reads an **identical
2718-character body for every tab** — the sections have not hydrated.
Per-section content assertions therefore live in
`public-league-visual.spec.js` (one fresh navigation per section, which
the lazy loading does support); the tab-walk test asserts tab presence
and the privacy invariant. Related to #555 item 3.

---


## Part 3 — the 2026-07-31 pass: six failures, one green suite

Part 2 catalogued findings. This part records what a **full local run**
against a booted stack turned up, because the catalogue could not have
found any of it: every one of these is a timing or attribution defect
that only exists when the suite actually runs.

Baseline before the pass: `E2E Safety Net` last ran 2026-07-30 09:07 on
`f90491cbd`, which predates every fix that merged that evening. So CI
could not answer whether #588 was fixed; only running it could.

First full run: **6 failed / 85 passed**. Final: **139 passed, 49
skipped, 0 failed** across `desktop-1366` + `mobile-chromium` with the
exact CI flags (`--ignore-snapshots`, `SKIP_VISUAL_REGRESSION=1`).

### §4.1 Three chart tests — a toggle that renames itself

`_openMethodology` matched the toggle by accessible name and then
polled `aria-pressed` on it. But `rankings/page.jsx:1319` renders
"Methodology charts" while collapsed and **"Hide charts" while
expanded**. The click landed, the panel opened, the name changed, and
the locator stopped resolving — so the poll read an attribute off zero
elements until it timed out, against a panel that is plainly open in
every trace.

Generalisable: **a name-keyed locator is unstable across any state that
renames its own control.** Either match every name the control can
take, or key on something that does not change.

This was self-inflicted — the previous revision wrapped the click in
`try/catch {}` and passed. Replacing a swallowed failure with a
verified one is still the right direction; the verification just has to
be correct.

### §4.2 `/arbitrage` — "idempotent" was wrong

The archives remedy (click *inside* `expect.poll`, so a click lost to
pre-hydration timing is retried) was applied here with the justification
"the handler is idempotent, so re-clicking only re-runs the same scan".

It is not idempotent in the way that matters. `run()` sets
`running: true`, and **both** settled states — the trade cards and the
"No arbitrage found" empty state — are gated on `!running`
(`arbitrage/page.jsx:283,289`). A click fired on the same tick the
previous scan finished tears the result straight back down, and because
the click ran *before* the read, the read always observed zero. It
failed deterministically with 30+ trade cards on screen.

Two rules fall out, and they apply to every retry-click poll:

1. **Read first, click second.** A poll that acts before it observes
   cannot see the state its own action just destroyed.
2. **"Idempotent" means the second click leaves the observable state
   unchanged** — not that it re-runs the same work. A tab selector
   qualifies. A scan button that clears its own results does not.

The `/league` tab helper deliberately keeps click-then-read: there, the
content check *is* the proof the tab switched, so reading first would
pass on the default tab's body.

### §4.3 `/waivers` — read-once-then-branch

```js
const text = await body.innerText();
if (/Select a team/i.test(text)) { … } else { … expect DROP … }
```

The page passes through three distinct bodies while it settles
(signed-out shell → signed-in without team → team picker). A read
landing on the middle one matches neither marker, takes the `else`
branch, and then waits 15s for a "DROP" this session will never render.

Same hydration race as the archives one in a different costume: the
branch is decided on a frame that is not the final frame. **Poll for
whichever settled state arrives; never branch on a single read.**

### §4.4 The flake that moved between runs — guard misattribution

`journey-trade` "/trade renders the builder" failed with a React #418
hydration error whose stack was entirely `127.0.0.1:8000/_next/...`
chunks — from a test that navigates to `:3000`.

`auth-fixture` primed cookies with a bare `page.goto("/")`, resolving
against `baseURL` (the backend page proxy). That document hydrates the
**anonymous shell** against an authenticated client, and React reports
the mismatch *asynchronously*, on the MessagePort scheduler, after
`goto()` has resolved. By then the test body has attached its console
guards — so the fixture's error lands in the next test's bucket.

Whichever authed spec loses the race gets the failure, which is why it
moved between runs and why `journey-tools-health` failed in the full run
and passed in isolation. The fixture now primes through `pageUrl()` like
every other navigation.

That retired the harness guard's only `_GOTO_EXEMPT` entry. Its stated
reason — "'/' is public so it cannot 307" — was true and beside the
point: sound about redirects, silent about hydration. Same
`docs/ORCHESTRATION.md` §6.15 shape the guard file exists to catch.

**The proxy's mismatched shell is a real product defect**, not just a
harness one. It is #555 and is being deleted; §4.4 is only about not
misattributing it.

### §4.5 Two tests that reported PASSED while executing nothing

Flagged in Part 2, fixed here. `critical-smoke.spec.js` held:

```js
if (res.status() === 401) {
  test.info().annotations.push({ type: "skip", description: "…" });
  return;
}
```

`annotations.push({type: "skip"})` is **not** `test.skip()`. It skips
nothing; Playwright reports the test as passed. Both endpoints
(`/api/terminal`, `/api/data/rank-history`) are auth-gated and 401 to an
anonymous request — and this is an anonymous spec — so every assertion
in both bodies was permanently unreachable while the suite counted two
more green tests for it.

Neither was simply deleted. The auth gate was already covered
non-vacuously by `AUTH_GATED_API_ROUTES`; the terminal payload by
`signed-in-smoke`; and the `MAX_SNAPSHOTS` clamp, which had **no other
home**, moved to `signed-in-smoke` where it can execute. It was
tightened on the way: `days <= 365*3` would be satisfied by a clamp
returning 1, so it now pins the exact value and checks both ends of the
`max`/`min` pair.

The endpoint's docstring claimed "max 180" while the code clamps to
1095 — that is the *player-source-history* window, on the next handler
down. Corrected.

### §4.6 The identity allowlist — a guard measuring the wrong thing

Not an E2E finding, but the same shape and it surfaced in the same pass.

`test_the_duplicate_allowlist_only_holds_real_collisions` required every
allowlisted name to be colliding in the **currently committed pool**.
That pool refreshes from external sources every two hours: "Robert
Henry" entered `CSVs/dynasty_full.csv` at 2026-07-30T18:06Z and was gone
by 2026-07-31T04:09Z, failing CI while the exemption was entirely
correct. Left alone the pair churns forever — drop the entry, the next
refresh re-adds the row, the *gate* fails and opens an issue, re-add it.

What justifies an exemption is committed code: the verified
`robert henry -> rob henry` alias. An alias-introduced collision on a
name is only *possible* while something in `CANONICAL_NAME_ALIASES`
targets it, so that is the live/dead test.

The allowlist is now `name -> the exact alias sources verified for it`,
which is **strictly stronger** on the risk that mattered. The old check
said nothing about which names an exemption covers, so a second alias
pointing at "rob henry" would have inherited the carve-out in silence —
the widening it claimed to prevent. Verified failing in both directions.

### What Part 3 does not claim

- **The pixel baselines are still not committed**, so `SKIP_VISUAL_REGRESSION=1`
  in CI means the `toHaveScreenshot` assertions never run there. The
  structural chart assertions do. Unchanged from Part 2.
- **49 of 188 are skipped** in a CI-parity run — mostly `desktopOnly`
  guards on `mobile-chromium` plus the visual block. These are real
  `test.skip()` calls and report as skipped, not as passed.
- **Coverage gaps from Part 2 §3 are untouched.** This pass made the
  suite trustworthy; it did not make it complete.
