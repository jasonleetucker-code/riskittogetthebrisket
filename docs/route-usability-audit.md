# Route usability audit — 2026-07-27

Every Next.js route under `frontend/app` walked as a signed-in user
against a warm backend, looking for hard failures, console errors,
failed network requests, empty-state lies, silent fallbacks, and dead
controls.

Three defects were fixed on `claude/route-usability-sweep`; the rest is
recorded here. Read [Method](#method) first — one finding in this
document (F-1) is the reason two previous agents could not get the
stack up, and one measurement caveat (M-2) invalidates any audit that
skips it.

---

## Method

### Topology — this is the part that matters

Production nginx splits by prefix
(`deploy/nginx/chaseupside-proxy.conf`):

```
location /api/     -> dynasty_backend  (:8000)
location /         -> dynasty_frontend (:3000)
```

`location /api/` is a longer prefix match than `location /`, so **every**
`/api/*` request from the browser goes to the FastAPI backend. The 22
route handlers under `frontend/app/api/**` are never reached in
production.

That matters for auditing because the frontend references 48 distinct
`/api/*` paths client-side, and only 22 have a Next handler. Point a
browser straight at `:3000` and you get 404s on `/api/health`,
`/api/leagues`, `/api/user/state`, `/api/terminal`, `/api/data`, and
`/api/ros/*`. Those endpoints all exist and answer fine — on the
backend, which is where nginx sends them. None of those 404s can happen
in production. An audit run that way reports a dozen phantom defects,
and that is exactly what the first pass of this one did.

The sweep therefore ran against a 40-line Node reverse proxy on `:8080`
reproducing exactly that split, so the browser saw one origin and the
same routing production uses.

### Stack

Booted from the committed snapshot in `exports/latest/`, offline, no
credentials — backend `:8000` (`ALLOW_DEFAULT_LOGIN_DEV=1`,
`E2E_TEST_MODE=1`, `RATE_LIMIT_BYPASS_IPS=127.0.0.1`, scraper browser
path pointed at an empty dir), frontend production build on `:3000`.
Auth via `POST /api/test/create-session`. Verified before walking:

```
/api/status  -> 200, has_data = True, player_count = 1095
/api/data    -> 200 authenticated, 1095 players, 5,602,258 bytes
/api/leagues -> 200, dynasty_main / superflex_tep15_ppr1 / idpEnabled
```

Per route, captured: navigation status, `page.on('pageerror')`,
`page.on('console')`, every response with status >= 400, every `/api/*`
call with its status, and a 1.5s-interval growth curve of rendered text
length + `<tbody> tr` count over a 40s observation window.

Dynamic-route parameters were resolved from the live APIs, never
guessed:

| Route | Parameter | Source |
|---|---|---|
| `/league/player/[playerId]` | `10229` (Rashee Rice) | `/api/public/league/players` |
| `/league/franchise/[owner]` | `1012114412049731584` (Joey) | `sections.franchise.index[0].ownerId` |
| `/league/rivalry/[pair]` | `1012114412049731584-vs-711452264774041600` | `sections.rivalries.pairs[0].ownerIds` |
| `/league/week/[season]/[week]` | `2025/17` | `weeklyRecap.byKey` |
| `/league/weekly/[…]/[matchup]` | `2025/17/1` | `sections.weekly.weeks[0].matchups[].matchupId` |
| `/league/articles/[season]/[week]` | `2025/17` | `/api/league/articles?season=2025&week=17` |
| `/league/articles/…/[matchupId]/[mode]` | `2025/17/1/preview` | same, `mode: "preview"` |
| `/rankings/[position]` | `qb`, `idp`, `picks` | `POSITION_ALIASES` in the route file |

---

## Measurement caveats — read before trusting any number here

**M-1 — `/api/health` returning 503 is normal offline.** Already
documented in `tests/e2e/README.md`. It appears in the console log of
essentially every route in this audit and is not a defect.
`StaleDataBanner` explicitly tolerates it (`if (!res.ok && res.status
!== 503) return`).

**M-2 — settle detection is the whole ballgame.** Four sweeps of this
app produced four different answers, and the first three were wrong.
`/angle` read as a blank page (72 chars) until measured properly, at
which point it settles at 5.3s with 1,916 chars. `/draft` read as
66 chars; it is actually 7,607 chars and 72 rows at 2.1s.

Causes, in the order they bit:
1. A fixed sleep is not enough — the 5.6MB contract lands late.
2. Waiting for the string "Loading" to disappear misses every page
   that uses `SkeletonTable` instead, which is most of them.
3. Early-exiting on "text length stable for 4s" false-positives when a
   page pauses mid-load for an auth round-trip.
4. `networkidle` never fires on pages that poll on an interval.

What worked: observe for a fixed 40s, record the growth curve, judge
from the final state. **Any conclusion in a route audit that is not
backed by a growth curve should be treated as unverified.**

**M-3 — backend contention distorts everything.** `server.py` runs a
single uvicorn worker with no `workers` argument, and every page load
pulls a 5.6MB contract. Running any second probe alongside the sweep
produced a 30s timeout on `POST /api/test/create-session` and a route
that appeared to make zero API calls. Sequential runs only.

**M-4 — `/design` trips skeleton heuristics on purpose.** It is the
design-system gallery and renders `Skeleton` / `SkeletonTable`
components as specimens. `stuck=true` there is a false positive.

**M-5 — three data-dependent surfaces cannot be judged offline.** The
snapshot is a single day, so `/api/data/rank-history` returns
`{"days":30,"history":{}}`, no player carries `rankHistory`, and
`rankChange` is 0 or null for all 1,095. `/trending` ("No movers in
this window"), the `/edge` delta columns, and `/trades` retro grading
are honestly empty here and need a multi-day environment to verify.

---

## Fixed on this branch

### FIX-1 — `/trades` asserted a trade count it did not have

The page header rendered:

```
0 trades in the last 365 days, graded at alpha=1.65.
```

while the contract was still in flight, and again directly above the
red "Couldn't load trade data" banner on the error path. Captured
verbatim from the error path:

```
"LedgerTrade History0 trades in the last 365 days, graded at
 alpha=1.65.Couldn't load trade datanetwork exploded"
```

The count comes from `analyzeSleeperTradeHistory(rawData, rows, ...)`,
which returns an empty analysis when `rawData` is absent — so "0" meant
"nothing loaded", not "no trades exist". The snapshot behind this audit
carries **109 Sleeper trades** and 785 waivers
(`sleeper.trades.length === 109`), so the statement was false.

Fixed in `frontend/app/trades/page.jsx`: the header states what is
happening while loading or failing, and only asserts a count once the
contract is in.

Test: `frontend/__tests__/components/trades-header-honesty.test.jsx`
— 2 of 3 fail before, 3 pass after.

Verified in the browser after rebuilding. Sampled every 700ms while the
28 skeleton elements were still on screen, then read the settled header:

```
early samples (skeleton up -> claims "0 trades"?):
  [{"skel":28,"claims0":false}, x6]
final rows: 22
header: "LEDGER / Trade History / 109 trades in the last 365 days,
         graded at alpha=1.65."
```

109 is exactly `sleeper.trades.length` in the snapshot — the page now
reports the number it actually has.

### FIX-2 — `/tools/source-health` failed silently

`SourceHealthStrip` returned `null` whenever the `/api/status` fetch
failed. That component is the entire body of `/tools/source-health`, so
the route rendered a title, a subtitle, and a legend explaining dot
colours — for dots that were not on the page. Nothing distinguished
"every source is healthy" from "the status endpoint is down".

Reproduced by forcing `/api/status` to 500 in a fresh browser context
(a warm HTTP cache masks it):

```
##### healthy
  strip rendered: true  | alerts: 0
  ... "Sources · 4 · 2h ago · 2 issues" ...
##### status-500
  strip rendered: false | alerts: 0
  ... legend text only, no strip, no error ...
```

Fixed in `frontend/components/SourceHealthStrip.jsx`. The `inline`
variant still hides itself on failure — that behaviour is documented
and deliberate ("we don't want a broken-status card cluttering an
otherwise-functional page") and is unchanged. The `page` variant now
surfaces the failure and distinguishes "couldn't reach `/api/status`"
from "runtime reports no enabled sources". A transient poll failure no
longer blanks a strip that already holds a good payload. Reuses the
existing `.source-health-strip--down` / `.source-health-dot--down`
rules; no CSS touched.

Test: `frontend/__tests__/components/source-health-strip.test.jsx`
— 3 of 5 fail before, 5 pass after.

Verified in the browser after rebuilding, both paths:

```
##### /tools/source-health (healthy)
  strip: true | role: region
  summary: "Sources · 4 · 2h ago · 2 issues"
##### /tools/source-health (status-500)
  strip: true | role: status
  summary: "Source health unavailable — Couldn't reach /api/status (HTTP 500)."
```

### FIX-3 — `/league/phases` was structurally dead

**The highest-value finding in this audit.** The route rendered a
heading and a subtitle and nothing else, on every run, for everyone:

```
/league/phases  http=200  settled=3071ms  len=282  rows=0
```

282 characters is the global nav plus the heading plus the subtitle.
The body was empty.

Root cause: the route's entire body is `<TeamPhasePanel />`, and the
panel read its data from `useApp()`. `AppShell` hard-refuses to hydrate
the private contract on anything under the `/league` prefix:

```js
// components/AppShell.jsx
const PUBLIC_ONLY_ROUTE_PREFIXES = ["/league"];
...
function PublicAppShell({ children, authenticated }) {
  return <InnerAppShell loading={false} rows={[]} rawData={null} ... />;
}
```

So on `/league/phases`, `useApp()` is permanently `{loading: false,
rows: [], rawData: null}`. `analyzeLeaguePhases(null, [])` returns zero
teams, and the panel hit `if (!analysis.teams.length) return null`. The
page could never render its content — it was not slow, not
data-dependent, not a config problem. It was dead.

The fix follows an existing in-repo pattern rather than inventing one:
the sibling route `/league/franchise/[owner]` has the identical problem
and already solves it — `RosterComparePanel` calls `useDynastyData()`
directly instead of `useApp()`, and renders an explicit message for
every state instead of returning `null`. `TeamPhasePanel` now does the
same.

Privacy: `/api/data` is auth-gated, so an anonymous visitor gets a 401
and the explicit "unavailable" message, not leaked data — the same
posture `RosterComparePanel` already has on the public franchise route.
The e2e privacy-isolation assertion in
`tests/e2e/specs/public-league.spec.js` scopes its no-private-endpoints
check to `/league?tab=...`, not to `/league/phases`, so this does not
cross it.

Test: `frontend/__tests__/components/team-phase-panel.test.jsx`
— 3 of 3 fail before (`AssertionError: expected '' not to be ''`,
literally proving the empty render), 3 pass after. The suite pins
`useApp()` to the values AppShell really supplies under `/league/*`, so
a regression back onto `useApp()` fails loudly instead of silently
blanking the page again.

Verified in the browser after rebuilding — signed in, the route now
renders all 12 franchises with real classifications:

```
##### /league/phases (signed in)
  len: 759  rows: 12  pageerrors: 0
  teams:  ["Jason","Joey","Brent","Eric","MaKayla","Collin",
           "Ed","Ty","Kich","Roy","Blaine","jstuedle"]
  phases: ["Win-now","Win-now","Contender","Contender","Contender",
           "Contender","Mixed","Mixed","Mixed","Mixed","Mixed","Mixed"]
  ... "against the league medians (91,362 value · 25.0 age)"
      Jason  Win-now  118,636  23.0
      Brent  Contender 139,097 27.0   ...
```

And anonymous — no leak, no redirect off the public route, explicit
message instead of a blank body:

```
##### /league/phases (anonymous)
  rows: 0 | still on: /league/phases
  "League phases unavailable — no Sleeper rosters in the active
   league's data. Sign in and pick your team on the league page."
```

---

## Reported, not fixed

### F-1 — the documented one-command E2E recipe fails on a clean checkout

**Severity: high.** `tests/e2e/README.md` opens with:

> ```bash
> npm ci && npm --prefix frontend ci && npm run e2e
> ```
> That is the whole recipe. It works offline, needs no credentials, and
> if anything is missing it tells you exactly what to fix.

It does not work, and it does not tell you what to fix. On a clean
checkout:

```
$ python3 tests/e2e/preflight.py
[preflight] Python compile checks passed
Traceback (most recent call last):
  File ".../scripts/validate_api_contract.py", line 92, in <module>
    raise SystemExit(main())
  File ".../scripts/validate_api_contract.py", line 45, in main
    payload, source_file = _load_latest_payload(repo_root)
  File ".../scripts/validate_api_contract.py", line 26, in _load_latest_payload
    raise FileNotFoundError(
FileNotFoundError: No dynasty_data_YYYY-MM-DD.json files found in
repo/data or repo root.
```

Root cause — `tests/e2e/preflight.py::main` runs the steps in the wrong
order:

```python
def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    _compile_python(repo_root)
    _run_contract_validation(repo_root)   # <-- needs data/
    _seed_data_cache(repo_root)           # <-- creates data/
    _check_node_deps(repo_root)
```

`_seed_data_cache` is the step that copies `exports/latest/` into
`data/`, and it runs *after* the validation that requires it.
`scripts/validate_api_contract.py::_load_latest_payload` searches only
`repo_root/data` and `repo_root` — never `exports/latest/` — and
`git ls-files` confirms the only committed snapshot is
`exports/latest/dynasty_data_2026-07-26.json`. Nothing under
`data/dynasty_data_*.json` is tracked.

This is very likely what the README's own "two agents in a row
concluded the stack was broken" note is describing: the first command
in the documented recipe dies with a raw traceback about missing data,
which reads exactly like the "no data" symptom the README then spends a
table telling you to ignore.

Fix: swap two lines so `_seed_data_cache(repo_root)` runs before
`_run_contract_validation(repo_root)`. Optionally also teach
`_load_latest_payload` to fall back to `exports/latest/`.

Not fixed here because `tests/e2e/**` is owned by another agent this
session. Worked around by seeding `data/` by hand before booting.

### F-2 — `/league/activity` can never show trades, but offers a Trades filter

Same root cause as FIX-3, different blast radius, and the fix is a
product decision rather than a mechanical one.

`/league/activity` calls `useApp()` and builds its feed with
`buildActivityEvents(rawData, newsItems)`. Under `/league/*`, `rawData`
is `null`, so the trade and waiver half of the feed is always empty.
Observed:

```
"League activity — Trades + news in one chronological feed. Scope to
 your roster to see only events involving your players.
 Scope [League] [My roster]   Type [All] [Trades] [News]
 88 events · newest first
 NEWS  4m ago  Isaiah Davis added in 10,701 leagues (last 24h)
 NEWS  4m ago  Zavion Thomas added in 7,749 leagues (last 24h)
 ..."
```

Counted in the DOM: **88 events, 80 `NEWS`, 0 `TRADE`.** The contract
for the same league carries 109 trades and 785 waivers.

Clicking the **Trades** filter confirms it is dead, and the empty state
blames the reader for it:

```
[default (All)] events=88  NEWS=80  TRADE=0
[type=Trades]   events=0   NEWS=0   TRADE=0
  "No activity in this view
   Try widening the scope or changing the type filter."
```

Widening the scope cannot help. There is no scope in which this page
has a trade to show.

So:

* the page's own description ("Trades + news in one chronological
  feed") is false;
* the **Trades** type filter is a dead control — it can only ever
  produce an empty feed;
* the **My roster** scope filter is a dead control — it filters on
  `myTeam.players`, and `myTeam` resolves from `rawData.sleeper.teams`,
  which is `null` here.

Why this is not fixed with the FIX-3 one-liner: `/league/phases` is
unambiguously a private feature that was misfiled under a public
prefix, and its whole body was dead. `/league/activity` genuinely
serves both audiences — it renders a real, useful public news feed
today, and switching it to `useDynastyData()` would start pulling the
private contract on a page anonymous visitors actually use. Someone has
to decide whether this route is public-with-news or private-with-
everything. Options:

1. Follow FIX-3 — `useDynastyData()`, private contract, full feed. Cost:
   a 401 round-trip for every anonymous visitor and a private fetch on
   a public-prefix route that is more heavily trafficked than
   `/league/phases`.
2. Keep it public and hide the Trades/My-roster controls when
   `rawData` is null, so the page stops advertising capability it does
   not have. Cheapest honest option.
3. Move the private view to its own prefix and leave a public news
   feed here.

### F-3 — `/api/chat` is dead code

`frontend/app/api/chat/route.js` proxies `POST /api/chat` to
`${BACKEND}/api/chat`. The backend has no `/api/chat` route (72 `/api/*`
routes registered in `server.py`; this is the only Next handler with no
backend counterpart). Nothing in `frontend/app`, `frontend/components`,
or `frontend/lib` calls it. And because nginx routes `/api/` to the
backend, the handler is unreachable in production even if something
did.

Safe to delete. Left alone because deleting it is not a usability fix
and it touches nothing a user can reach.

### F-4 — time-to-usable is the real user-facing problem

Not a correctness defect, but the thing most likely to make the owner
distrust a page that is actually working. Settle times from the clean
sweep, measured as "text length stops growing and no skeletons remain":

| Route | Settled | Final |
|---|---|---|
| `/rankings` | **28.8s** | 18,113 chars, 231 rows |
| `/finder` | 34.9s | 4,036 chars, 59 rows |
| `/idptc-rookies` | 33.2s | 41,628 chars, 114 rows |
| `/angle` | 24.5s | 1,916 chars |
| `/draft-capital` | 24.2s | 5,571 chars, 78 rows |
| `/draft` | 18.5s | 7,545 chars, 72 rows |
| `/edge` | 15.4s | 3,392 chars, 36 rows |
| `/rosters` | 12.3s | 6,389 chars, 12 rows |
| `/league` | 4.5s | 2,784 chars |
| `/more` | 1.6s | 1,230 chars |

`/trade`, `/trades` and `/trending` did not finish inside the 40s
window on the loaded run; re-measured on a quiet backend they settle at
18.3s, ~20s (22 rows) and 5.1s respectively.

Contributors, in rough order:

* `GET /api/data?view=app` is **5,602,258 bytes** uncompressed and is
  fetched per page load.
* `server.py` runs a single uvicorn worker (`uvicorn.run("server:app",
  host=HOST, port=PORT, log_level="info", reload=False)` — no
  `workers`), so concurrent page loads serialise behind one process.
* **Duplicate in-flight fetches.** `/trade` on a quiet backend, with
  timings relative to navigation:

  ```
     529ms 200 /api/leagues
     530ms 200 /api/user/state
   10544ms 200 /api/draft-capital
   12534ms 200 /api/draft-capital?leagueKey=dynasty_main   <-- 2nd
   12543ms 200 /api/dynasty-data
   12543ms 200 /api/dynasty-data                            <-- 2nd
   15400ms 200 /api/rankings/overrides?view=delta
   15401ms 200 /api/rankings/overrides?view=delta           <-- 2nd
   15908ms 200 /api/ros/player-values?limit=2000
   16392ms 200 /api/trade/suggestions
  ```

  The 5.6MB contract is fetched **twice**, the override delta twice,
  and draft-capital twice (once before the league key resolves, once
  after). First paint of real content is at 16.3s. De-duplicating
  these three pairs is the cheapest available win on the heaviest page
  in the app.
* `/api/draft-capital` alone took 10.5s to first byte on an idle
  backend.
* `/tools/trade-coverage` issues **12 sequential** `/api/terminal`
  calls, one per team, after the contract lands (39.3s to settle).

CLAUDE.md lists page-load speed as an explicit priority, so this is
worth a dedicated pass. Cheapest first look: why the base contract is
5.6MB when the delta path already proved ~1.25MB is enough for the
override-sensitive fields.

### F-5 — `/favicon.ico` 404s on every page load

`GET /favicon.ico -> 404`. There is no `frontend/app/favicon.ico`, no
`app/icon.*`, and no `icons` entry in the root layout's `metadata`.
`public/icons/` does ship `icon-192.png`, `icon-512.png`, and
`icon-maskable-512.png`, but those are referenced only by
`app/manifest.js` (the PWA manifest), not as the browser favicon. nginx
routes `location = /favicon.ico` to the frontend, so production 404s
identically.

Cosmetic — browsers degrade gracefully — but it is the only unexplained
console error left in the whole sweep, so it costs a few seconds every
time someone reads the console looking for something real.

Fix is one line: add an `icons` block to the root layout's `metadata`
pointing at the already-shipping `/icons/icon-192.png`, or drop an
`app/icon.png` in. Not done here because `app/layout.jsx` is being
edited on the design branch this session and this is not worth a
conflict.

### F-6 — invisible controls (styling; handed back to the design agent)

The design agent reported an invisible `/login` submit button — a
hardcoded navy fill on near-black that its brand sweep missed because
the colour is not a brand hex. Confirmed the markup side: `login/page.jsx`
carries no inline colours at all, only `className="button login-button"`,
so the fix belongs entirely in the CSS layer (`globals.css`), which is
off-limits to this branch tonight.

A contrast auditor was built for this
(`scratchpad/route-sweep/contrast.js`: composites every ancestor
background, then computes WCAG text-vs-surface, fill-vs-page, and
border-vs-page ratios for every `button`, `a[href]`, `input`, `select`,
`[role=button|tab|menuitem|option]`). It did not get a clean run across
all 38 routes before time ran out — the sweep and the auditor cannot
share the backend (M-3). Recommend running it after the token rewrite
lands; it is the cheap way to catch the whole class rather than the one
button someone happened to look at.

---

## Error inventory — the whole sweep, 38 routes

**Uncaught exceptions / React error boundaries / blank white pages: zero.**
`page.on('pageerror')` fired exactly 0 times across all 38 routes.

Every console error, deduplicated:

| Count | Error | Verdict |
|---|---|---|
| 37 | `503 (Service Unavailable)` on `/api/health` | Expected offline (M-1) |
| 9 | `net::ERR_CONNECTION_RESET` | `https://sleepercdn.com/avatars/thumbs/*` — external CDN, unreachable offline. Not a defect. |
| 1 | `404 (Not Found)` | `/favicon.ico` — F-5 |

Every response with status >= 400, excluding `/api/health`:

| Count | Request | Verdict |
|---|---|---|
| 1 | `503 GET /api/intel/summary?limit=200&leagueKey=dynasty_main` | Honest — backend returns `{"error":"data_not_ready", "message":"No intel snapshot for league 'dynasty_main' yet…"}` and `/intel` renders exactly that. |

`net::ERR_ABORTED` on `…?_rsc=` URLs also appears; that is Next.js
cancelling a route prefetch on navigation, not an error.

---

## Route-by-route

Console-error counts exclude the `/api/health` 503 (M-1). Settle times
are from the loaded sequential sweep and are upper bounds — see M-3.

| Route | Verdict | Evidence |
|---|---|---|
| `/` | PASS | 4,317 chars, settled 4.6s; team/portfolio/signal panels render |
| `/admin` | PASS | 1,149 chars, 10 rows, settled 3.0s |
| `/angle` | PASS | 1,916 chars, settled 5.3s clean / 24.5s loaded; roster picker + market routing |
| `/design` | PASS | 3,872 chars, 5 rows; skeleton specimens are intentional (M-4) |
| `/draft` | PASS | 7,545 chars, 72 rows, settled 2.1s clean / 18.5s loaded |
| `/draft-capital` | PASS | redirects to `/league?tab=draft-capital`; 5,571 chars, 78 rows |
| `/edge` | PASS | 3,392 chars, 36 rows; delta columns need multi-day data (M-5) |
| `/finder` | PASS | 4,036 chars, 59 rows |
| `/idptc-rookies` | PASS | 41,628 chars, 114 rows |
| `/intel` | PASS (honest empty) | `/api/intel/summary` 503 `data_not_ready`; UI says "No intel snapshot yet — the first crawl hasn't run", matching the API's own message |
| `/league` | PASS | 2,784 chars, settled 4.5s — resolves fine on a warm backend; 3 seasons / 12 managers / 190 trades / 1,092 waivers / defending champion all render |
| `/league-comparison` | PASS | 2,399 chars; not caught by the `/league` prefix gate (`"/league-comparison".startsWith("/league/")` is false) |
| `/league/activity` | **DEFECT** (empty-state lie + 2 dead controls) | F-2 — 88 events / 80 NEWS / **0 TRADE** against 109 trades in the contract; the Trades filter returns "No activity in this view" and tells you to widen a scope that cannot help |
| `/league/phases` | **FIXED** | FIX-3 — was 282 chars / empty body / structurally dead; now 759 chars, 12 rows, all 12 franchises classified |
| `/login` | PASS (markup) | form + submit render; invisible-button issue is CSS-layer, F-5 |
| `/more` | PASS | 1,230 chars, settled 1.6s |
| `/news` | PASS | 2,436 chars |
| `/players/compare` | PASS | 402 chars with no `?p1=`/`?p2=`; correctly shows two "No player matched" prompts |
| `/rankings` | PASS (slow) | 18,113 chars, **231 rows**; settled 28.8s — F-4 |
| `/rosters` | PASS | 6,389 chars, 12 rows |
| `/settings` | PASS | 4,504 chars, 21 rows; source registry lists every registered source |
| `/trade` | PASS (slow) | 3,768 chars, settled 18.3s quiet; first real content at 16.3s, with 3 duplicated fetches — F-4 |
| `/trades` | **FIXED** (header) + slow | FIX-1; 22 rows, header now reads "109 trades in the last 365 days" |
| `/trending` | PASS (honest empty) | settled 5.1s; "No movers in this window" — 0/1,095 players carry `rankHistory` or non-zero `rankChange` in a single-day snapshot (M-5) |
| `/waivers` | PASS | 9,686 chars, 93 rows, 4 tables |
| `/tools/ros-data-health` | PASS | 1,219 chars, 17 rows; 5 ROS sources + per-team unmapped counts |
| `/tools/source-health` | **FIXED** | FIX-2; healthy path renders "Sources · 4 · 2h ago · 2 issues" |
| `/tools/trade-coverage` | PASS (slow) | renders after 12 sequential `/api/terminal` calls — F-4 |
| `/rankings/qb` | PASS | redirect to `?pos=QB`; 7,963 chars, 116 rows, settled 35.2s |
| `/rankings/idp` | PASS | redirect to `?pos=idp`; 34,233 chars, **485 rows**, settled 35.3s |
| `/rankings/picks` | PASS | redirect to `?pos=pick`; 5,974 chars, **82 rows**, settled 13.6s (2026 slot picks are deliberately hidden post-draft — `rankings/page.jsx` line 365) |
| `/league/player/[playerId]` | PASS | Rashee Rice: ownership arc, per-manager impact table, transaction timeline |
| `/league/franchise/[owner]` | PASS | cumulative stats, season results, roster-compare panel |
| `/league/rivalry/[pair]` | PASS | head-to-head, memorable meetings, season splits |
| `/league/week/[season]/[week]` | PASS | 2025 wk17 recap headline, superlatives, 4 matchups |
| `/league/weekly/[…]/[matchup]` | PASS | 1,404 chars, 34 rows |
| `/league/articles/[season]/[week]` | PASS | slate renders; preview/recap cards link through |
| `/league/articles/…/[mode]` | PASS | 4,582 chars, full generated article |

No route produced an uncaught `pageerror`, a React error boundary, a
500, or a blank white page. The only genuinely non-functional surface
was `/league/phases`, now fixed.

---

## Suite status on this branch

```
$ python3 -m pytest tests/ -q -m "not livedata"
3927 passed, 325 deselected, 1 warning, 4 subtests passed in 1084.20s (0:18:04)

$ npx vitest run            # frontend, both projects
Test Files  63 passed (63)
     Tests  1219 passed (1219)

$ python3 -m ruff format --check .
538 files already formatted
```

`python -m ruff check` reports 49 findings repo-wide; all pre-existing
(this branch changes no `.py` files, and `pr-validation.yml` lints
changed files only, so the blocking gate has nothing to look at).

---

## Reproducing

```bash
# 1. seed + boot (see F-1 — seed BEFORE preflight)
python3 -c "import shutil;shutil.copy2('exports/latest/dynasty_data_2026-07-26.json','data/')"
UPTIME_CHECK_ENABLED=false ALLOW_DEFAULT_LOGIN_DEV=1 E2E_TEST_MODE=1 \
  E2E_TEST_SECRET=e2e-local-insecure-secret RATE_LIMIT_BYPASS_IPS=127.0.0.1 \
  PLAYWRIGHT_BROWSERS_PATH=$(pwd)/tests/e2e/.no-browsers python3 server.py &
npm --prefix frontend run build:nocheck && npm --prefix frontend run start &

# 2. nginx-equivalent split on :8080 — without this the audit is invalid
node scratchpad/route-sweep/nginx-sim.js &

# 3. walk (sequential only — see M-3)
MAX_WAIT=40000 node scratchpad/route-sweep/walk2.js
```

The walker, reverse proxy, contrast auditor, and network capture live
in the session scratchpad under `route-sweep/`; they are throwaway
instruments, deliberately not committed to `tests/e2e/`.
