# Security & Access-Control Audit

Deliverable §14 of the master site audit. Audited commit `e96c06ef`, dates 2026-08-04/05.

Primary evidence: workstream **W22** (9 findings), the shared anonymous-vs-authenticated route
probe (`evidence/route-probe.json`, 66 GET/HEAD operations, each fired twice), the W22 probe
transcript (`evidence/W22/probe-transcript.md`, 14 numbered probes) and the W22 anonymous sweep
(`evidence/W22/anon-get-sweep.json`). Supporting findings from W00, W01, W09, W10, W16, W19 and
W26 are cited by id.

**Verification status — read this before quoting a severity.** Of the nine W22 findings, exactly
one (**W22-F002**, the rate-limiter key) was selected for adversarial re-verification.
`evidence/verify/W22-F002.json` returns **verdict: upheld**, priority P1 sustained, with the
author's blast radius corrected *upward* — the author wrote `routesAffected: 12`; the verifier
counted 12 exact + 2 prefix families + 5 self-authed entries ≈ **19 path families**, and the
merged record carries the corrected number with `authoredBlastRadius` preserved. The other eight
W22 findings are authored, schema-validated and merged with a re-runnable reproduction, but were
**not independently attacked**. No W22 finding drifted in priority under verification.

**Rate-limiting caveat, stated once and applying to the whole document.** The shared audit stack
on `:8000` boots with `RATE_LIMIT_BYPASS_IPS=127.0.0.1`. Every quantitative limiter claim below
comes from a **second backend on `:8001`, booted without that variable** (`evidence/W22/probe-transcript.md`
header). Any limiter number taken from `:8000` alone is void, and none is printed here.

Cookie for the authenticated half of every probe:

```bash
SECRET=$(cat /tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/e2e_secret.txt)
curl -s -c /tmp/audit-cookies.txt -X POST http://127.0.0.1:8000/api/test/create-session \
  -H "Authorization: Bearer $SECRET"
```

---

## 1. Urgent — four findings that need a fix before anything else here

| # | Finding | What it is | Size |
|---|---|---|---|
| 1 | **W22-F001** P1 | `/login?next=/\evil.com` is a working post-authentication open redirect on the real domain. Driven end to end in Chromium against the real login form, the browser navigated to `http://evil.com/` immediately after a successful login. | XS |
| 2 | **W22-F002** P1 *(verified upheld)* | The rate limiter keys on unvalidated client-supplied `X-Forwarded-For`. Rotating one header defeats it on ~19 public path families — including `/api/auth/login`. | S |
| 3 | **W22-F003** P1 | Login has no throttle of its own, no lockout, no backoff. 200 wrong-password attempts landed at **223 req/s with zero 429**, against a **single shared credential with no second factor**. | M |
| 4 | **W00-F001** P1 | `/api/draft-capital` returns **HTTP 200 and 72 per-pick dollar values from the operator's private workbook curve** to an unauthenticated caller. | — |

Findings 1–3 compose into one attack: a link on the genuine domain harvests the operator's
password (F001), the only credential that exists can be attacked without limit (F003), and the
limiter that was supposed to bound it is bypassable by header (F002). Fixing F001 and F002 is
roughly twenty lines between them.

### 1.1 The open redirect (W22-F001)

`server.py::_sanitize_next_path` (lines 738-748) is a **denylist of four dangerous prefixes**.
It correctly coerces `//host`, `http://host`, `https://host` and CR/LF to `/`. It does not reject
a backslash. `/\evil.com` survives verbatim, `frontend/app/login/page.jsx:25` re-checks only
`next.startsWith("/")` — which `/\evil.com` satisfies — and `router.push()` hands it to the
WHATWG URL parser, which normalises `\` → `/` inside a special scheme. `new URL('/\evil.com', location.href)`
is `http://evil.com/`.

| `next=` | `redirect` returned by `/api/auth/login` |
|---|---|
| `/\evil.com` | `/\evil.com` — **passes** |
| `/\/evil.com` | `/\/evil.com` — **passes** |
| `//evil.com` | `/` (blocked) |
| `https://evil.com` | `/` (blocked) |
| `\evil.com` | `/` (blocked) |

9 candidates tested, 3 blocked by the guard, 6 passed, **2 resolve off-origin** against an
expected 0 (`W22-F001.numericProof`).

Re-run (header-only check, no browser):

```bash
curl -s -X POST http://127.0.0.1:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"x","password":"y","next":"/\\evil.com"}'
```

Full browser reproduction: `.venv/bin/python docs/master-site-audit/evidence/W22/open-redirect-repro.py`
(needs a backend on `:8001` with `ALLOW_DEFAULT_LOGIN_DEV=1`). Transcript: `evidence/W22/probe-transcript.md#11-open-redirect`.

Repair per the finding: replace the prefix denylist with `urlsplit` + parse-and-compare, after
normalising backslashes; pin `/\evil.com`, `/\/evil.com`, `/%5Cevil.com`, `/\t/evil.com`.

### 1.2 The anonymous draft-capital board (W00-F001, W10-F010, W26-F008)

Three findings, one route, three axes — all reproduce at HEAD.

* **Exposure (W00-F001, P1).** Anonymous `GET /api/draft-capital` → `200`, 15,989 bytes,
  measured cold at **13,188 ms** in the shared route probe. Every other value-bearing route
  (`/api/data`, `/api/movers`, `/api/terminal`, `/api/valuation/league-adjusted`) correctly 401s.
* **What is and is not redacted (W10-F010, P3).** The redaction *works*: 5 fields
  (`rookieName`, `rookiePos`, `rookieKtcValue`, `rookieKtcDollar`, `rookieIdpDollar`) are stripped
  from 72/72 picks and `rookieBoardRedacted: true` is stamped. What survives is
  `dollarValue` / `adjustedDollarValue` / `originalDollarValue` and `teamTotals.auctionDollars`,
  which come from column L of `CSVs/Draft Data.xlsx` — a hand-maintained curve the operator wrote.
  The allowlist comment justifies the route as "public Sleeper data … already viewable on Sleeper";
  **Sleeper publishes no such figure**. Two of the three named field groups are public, the third is not.
* **Cost (W26-F008, P2).** Redaction happens *after* the build, so an anonymous poller forces the
  full workbook parse + KTC live fetch + Sleeper calls on every 300 s TTL expiry — 775 server-seconds
  per day per league at the measured 2.692 s cold time. A failing KTC fetch is never negative-cached,
  so the cost recurs forever.

Re-run:

```bash
for i in 1 2 3; do curl -s -o /dev/null -w 'anon %{http_code} %{size_download}b %{time_total}s\n' \
  http://127.0.0.1:8000/api/draft-capital; done
curl -s http://127.0.0.1:8000/api/draft-capital | head -c 200   # rookieBoardRedacted / no rookieName
```

Evidence: `evidence/W22/draft-capital-anon.json`, `evidence/W22/draft-capital-auth.json`.

---

## 2. What is actually solid

Stated plainly, because a list of only defects is not an audit. Every item here was probed live.

| Area | Result | Evidence |
|---|---|---|
| **The auth gate itself** | **44 of 66 probed GET/HEAD operations return 401 anonymously** with `{"error":"auth_required"}`. **Zero private-contract fields reached an anonymous caller** on any route. | `evidence/route-probe.json`; `evidence/W22/anon-get-sweep.json` |
| **Gate-bypass attempts** | 12 path-mangling variants (case flips, `..`, `..%2f`, `%2e%2e`, `//api`, `/api//`, trailing slash, `%00`) — **no bypass**. `/api/data%00` still 401s; traversal into `/api/data` from `/api/news/..` still 401s. | transcript §3 |
| **Public-league field blocklist** | `assert_public_payload_safe` walks every dict key at every depth against a 39-name blocklist. **0 hits across ten anonymous endpoints totalling 2.6 MB.** Independently re-scanned by W19: recursive key scan of the 2,081,957-byte payload against the blocklist plus a value/recommendation regex → **0 private fields**. | transcript §4; W19-F011 |
| **`/api/admin/*` allowlist** | All 6 routes enforce `_require_admin_session` as their **first statement**. 5 fired live: **401 anonymous, 403 `admin_required` to a non-admin session**. The 6th (`force-logout-all`) was not fired — destructive if the guard failed — and uses the identical first statement (server.py:11038). | transcript §8 |
| **Cron bearer routes** | `/api/signal-alerts/run`, `/api/custom-alerts/run`, `/api/intel/refresh`: **401 anonymous and 401 on a guessed bearer**. `hmac.compare_digest`, short-circuit before touching cookies when the token is unset, and `auth_method == "password"` required on the session fallback — which excludes guest and e2e sessions. | transcript §9; W16-F011 |
| **Session cookie** | HttpOnly + Secure + SameSite=Lax, 30-day max-age **matching the server-side TTL**. Session ids are `uuid.uuid4().hex` (122 bits from `os.urandom`). | W22-F003 `whatWorks` |
| **Guest passes** | 24-byte `secrets.token_urlsafe`, SHA-256 at rest, plaintext shown once, 30-day creation cap, revocation, opportunistic purge, and a server-side `expires_at_epoch` **re-checked on every request** so a stretched cookie cannot outlive the pass. Not brute-forceable. | W22-F003, W22-F007 `whatWorks` |
| **SSRF** | **Verified negative.** `POST /api/trade/import-ktc` validates only `"keeptradecut.com" in url`, which is trivially satisfiable — but `resolve_trade_url` **never fetches the supplied URL**. It parses `teamOne`/`teamTwo` out of the query string and fetches the hardcoded `_KTC_CALCULATOR_URL` (`src/trade/ktc_import.py:88`). Every other outbound call site takes a module constant or a registry-resolved Sleeper league id. | transcript §13 |
| **Error bodies** | The global exception handler **never returns a traceback** — `errorType` only, trace logged server-side. 13 anonymous probes with traversal, null-byte, negative and overflow inputs produced **zero raw exception text**. | W22-F005 `whatWorks` |
| **Logs** | **0 log statements emit session ids, cookies, passwords or tokens.** The bearer-rejection log is rate-limited to one line per 60 s and leaks only a length-**equality** boolean. | transcript §14; W16-F011 |
| **Test-only endpoint** | `/api/test/create-session` returns **404, not 401**, unless `E2E_TEST_MODE` *and* a matching `E2E_TEST_SECRET` are both set — confirmed 404 in a clean process both with and without a bearer. It fails closed on a third variable too: `E2E_TEST_USERNAME` has **no default**, because an earlier revision fell back to the operator's real admin-capable account. | transcript §9; server.py:10930-10979 |
| **Page auth gate** | `frontend/middleware.js` is genuinely the single gate now that `server.py` registers no page routes — `curl :8000/rankings` returns a JSON 404. **All 18 private pages 307 to `/login?next=<encoded original>`**; the 4 public ones 200; `/draft-capital` 308s to its new home. Neither anonymous 200's HTML contains any private-board token. | transcript §10; W22-F006 `whatWorks` |
| **`/api/draft-capital` redaction mechanics** | Applied per-response **on a copy**, so the shared 300 s TTL cache is not poisoned — verified by fetching anonymously then authenticated inside one TTL window and confirming the authenticated response still carried all five private fields. | W10-F010, W26-F008 |
| **Rate-limiter arithmetic** | Correct and thread-safe. 60 requests pass, the 61st returns 429 with a sane `Retry-After`, refill is proportional to elapsed time, `_MAX_TRACKED_IPS` eviction bounds memory, and it **fails open** around a raising `should_rate_limit`. Nothing is wrong with it except the key. | transcript §5; W22-F002 |

Two configuration observations, stated from the files rather than from a finding (no workstream
filed either, and neither is claimed here as a defect):

* **No CORS middleware is registered.** `grep -n 'CORSMiddleware\|allow_origins' server.py` returns
  nothing; the only middleware added is `GZipMiddleware` (server.py:2670). Cross-origin browser
  reads are therefore blocked by default.
* **Security headers are declared at the nginx server level**, not in the shared proxy snippet —
  HSTS, `X-Content-Type-Options: nosniff`, `frame-ancestors 'self'`, `X-Frame-Options: SAMEORIGIN`,
  `Referrer-Policy`, `Permissions-Policy` (`deploy/nginx/chaseupside.com.conf:122-131, 200-204`).
  A full application CSP exists but is **commented out** (line 141, `Content-Security-Policy-Report-Only`).
  The audit container has no nginx, so **none of this was measured against a live edge** — see §11.

---

## 3. Unauthenticated exposure matrix

All 66 GET/HEAD operations in `evidence/route-probe.json`, each fired anonymously and with a
session. Classification: **correctly-public** (nothing sensitive), **correctly-401**, **leaks**.

### 3.1 Summary

| Anonymous status | Count | Authenticated outcome |
|---|---|---|
| **200** | 20 (19 GET routes + 1 HEAD) | 200 — see 3.2 |
| **401** | 44 | 28 → 200 · 8 → 503 (feature off / no data) · 5 → 400 (missing param) · 2 → 404 (no snapshot) · 1 → 403 (admin allowlist) |
| **400** | 1 | 400 — `/api/league/articles/{season}/{week}/{matchup_id}/{mode}`, param validation |
| **503** | 1 | 503 — `/api/push/public-key`, VAPID key absent |

Re-run:

```bash
.venv/bin/python -c "
import json,collections
d=[x for x in json.load(open('docs/master-site-audit/evidence/route-probe.json')) if 'skipped' not in x]
print(len(d), collections.Counter((x['anon']['status'], x['auth']['status']) for x in d))"
```

The 44 anonymous 401s are **correct behaviour, not a finding** (`AUDIT_PROTOCOL.md` pre-declared
non-findings). The 8 `401 → 503` routes are `consensus-edge` (flag off per ADR-023) and `intel`
(no ledger DB in this container) — reachability confirmed, not exposure.

### 3.2 The 19 anonymously-reachable GET routes, classified

| Route | Anon bytes | Verdict | Note |
|---|---|---|---|
| `/api/leagues` | 808 | **correctly-public** | Honours the documented invariant exactly — **0 `sleeperLeagueId` occurrences** while still serving roster settings |
| `/api/uptime` | 167 | **correctly-public** | Nothing sensitive |
| `/api/metrics` | 309 | **correctly-public** | Nothing sensitive |
| `/api/auth/status` | 23 | **correctly-public** | Anonymous body is `{"authenticated":false}`. Cache-header defect only — W22-F009 |
| `/api/news` | 46,474 | **correctly-public** | No league-private data |
| `/api/league/articles` | 1,383 | **correctly-public** | Public league media |
| `/api/rankings/sources` | 7,709 | **correctly-public** | Source registry (published methodology) |
| `/api/public/league` | 2,081,957 | **public by design, two qualifications** | Blocklist clean (0 hits). But: 393 derived trade grades (W22-F008 P3) and raw Sleeper league + owner IDs (W19-F011 P3) |
| `/api/public/league/players` | 63,323 | **public by design** | |
| `/api/public/league/matchups` | 14,672 | **public by design** | |
| `/api/public/league/matchup/{…}` | 17,006 | **public by design** | |
| `/api/public/league/player/{id}` | 19,176 | **public by design** | |
| `/api/public/league/metrics` | 795 | **public by design** | |
| `/api/public/league/{section}` | 15,229 | **public by design** | |
| `/api/public/league/{section}.csv` | 192 | **public by design** | No UI link anywhere — W01-F012 |
| **`/api/draft-capital`** | 15,989 | **LEAKS (P1)** | 72 per-pick dollar values off the operator's private workbook curve — W00-F001, W10-F010 |
| **`/api/status`** | 7,477 | **LEAKS (P2)** | 2 × `sleeperLeagueId`, 2 absolute deploy paths, 15 feature flags with `gateStatus`, all 21 source names with row counts, `source_health.source_failures` free text, `run_events`, payload byte sizes — W22-F005 |
| **`/api/health`** | 2,259 | **LEAKS (P2)** | `startupChecks` array: 3 absolute directory paths, 2 SQLite filenames, league-registry keys, `env:PRIVATE_APP_ALLOWED_USERNAMES → "missing (optional)"`, 3 vendor session filenames, per-breaker `lastError`, `memberInMemorySessions: 42`, `sessions.persistedCount`, `backup_health.newestBackupPath` — W22-F005 |
| **`/api/scaffold/status`** | 756 | **LEAKS (P2)** | 4 `_meta()` blocks stamping `str(path)` — absolute snapshot paths with timestamps. **Zero callers of any kind** (no UI, no bridge, no ops, no test), so removing it from the allowlist breaks nothing — W22-F005, W01-F010 |

Re-run the three leaking metadata routes:

```bash
curl -s http://127.0.0.1:8000/api/status | grep -o '"sleeperLeagueId": "[0-9]*"'
curl -s http://127.0.0.1:8000/api/health | grep -o 'PRIVATE_APP_ALLOWED_USERNAMES.\{0,60\}'
curl -s http://127.0.0.1:8000/api/scaffold/status | grep -o '/home/[^"]*'
curl -s http://127.0.0.1:8000/api/leagues | grep -c sleeperLeagueId   # 0
```

Confirmed at HEAD while writing this document: 2 `sleeperLeagueId` hits on `/api/status`, absolute
paths `…/data/dynasty_data_2026-08-04.json` and `…/data/rank_history.jsonl`, the
`PRIVATE_APP_ALLOWED_USERNAMES … "missing (optional)"` row on `/api/health`, and `0` on `/api/leagues`.

**The `env:PRIVATE_APP_ALLOWED_USERNAMES → "missing (optional)"` row is the sharpest single item
in this table**: it tells a stranger the allowlist variable is unset, and therefore that the admin
username is the in-code default.

**A prior claim, corrected.** PRIOR-A23-F16 says the leaked Sleeper league IDs enable "direct
enumeration of rosters, transactions and drafts via Sleeper's open API". W22 confirms the
mechanism and **refutes the stated impact**: the incremental exposure is **zero**, because
`config/leagues/registry.json` is a **tracked file in a public repository** carrying both ids, and
`SECURITY.md` explicitly accepts that. The real defect is narrower and still worth fixing — the
`/api/leagues` invariant CLAUDE.md documents is applied to one public route and contradicted by a
sibling on the same allowlist. The absolute-path half is confirmed unqualified.

### 3.3 Discrepancy worth knowing

`evidence/W22/probe-transcript.md` §1 summarises its own sweep as "67 GET operations … 42 × 401,
13 × 200 public, 4 × 404, 1 × 503". The artifact it points at, `evidence/W22/anon-get-sweep.json`,
contains **65 entries: 44 × 401, 17 × 200, 3 × 404, 1 × 503**. The artifact is authoritative; the
prose summary is miscounted. The route-probe's 19 anon-200 GET routes vs. the sweep's 17 is a
parameter difference, not a disagreement — the sweep passed a bad `{section}` and got two 404s
where the route probe passed a valid one.

```bash
.venv/bin/python -c "
import json,collections
d=json.load(open('docs/master-site-audit/evidence/W22/anon-get-sweep.json'))
print(len(d), collections.Counter(x['status'] for x in d))"
```

---

## 4. Public / private page boundary

**The gate holds in both directions, and no data leaks.** What is broken is the guarantee that it
will keep holding.

Measured anonymously on `:3000` (transcript §10):

| Outcome | Pages |
|---|---|
| **307 → `/login?next=<encoded>`** (18) | `/admin` `/tools/ros-data-health` `/tools/source-health` `/tools/trade-coverage` `/rankings` `/trade` `/settings` `/league/insider-trading` `/trades` `/intel` `/market/sharp-tracker` `/market/sharp-roster-percentage` `/design` `/phases` `/more` `/news` `/edge` `/consensus-edge` |
| **200** (4) | `/` `/login` `/league` `/league/activity` |
| **308** (1) | `/draft-capital` → `/league?tab=draft-capital` |

Neither anonymous 200's HTML contains any private-board token.

### 4.1 W22-F006 (P3) — four consumers of a three-consumer contract

`frontend/lib/public-routes.js` states in its own header that it exists because
"middleware.js, AppShellWrapper.jsx, robots.js … used to disagree". There is a **fourth**
consumer that does not import it: `frontend/app/sitemap.js` hardcodes its own static list
containing **`/trades`** — the one route whose privacy the module's header spends a paragraph
explaining. So `sitemap.xml` publishes `https://chaseupside.com/trades` while middleware 307s that
exact path and robots disallows it. 1 of 812 sitemap URLs fails `isPublicPath()`.

Separately, the `/league/insider-trading` exception was applied to `isPublicPath` only.
`robots.js` spreads `PUBLIC_PREFIXES` and ignores `PRIVATE_EXCEPTIONS`, so the emitted
`robots.txt` is `Allow: /league/` + `Disallow: /` with **no** `Disallow: /league/insider-trading`
— under longest-match precedence, exactly the condition the exception was written to end.
`robots.js` also omits `PUBLIC_EXACT`, so the legitimately-public `/draft-capital` shim is
disallowed (2 of 3 `PUBLIC_EXACT` entries allowed).

```bash
curl -s http://127.0.0.1:3000/sitemap.xml | grep -o '<loc>[^<]*trades</loc>'
curl -s -o /dev/null -D- http://127.0.0.1:3000/trades | grep -i '^location'
curl -s http://127.0.0.1:3000/robots.txt
grep -n 'public-routes' frontend/app/sitemap.js || echo 'sitemap.js: NO IMPORT'
```

No data leaks today. The failure is that the next private page added to `sitemap.js`'s static
list repeats the incident with nothing to catch it.

### 4.2 W22-F008 (P3) — the derived-value channel the blocklist cannot see

`assert_public_payload_safe` is a **name** blocklist, so it is structurally blind to a value
derived from a blocked field and stored under an unblocked name.

`/api/public/league` serves **191 graded trades / 393 graded sides** anonymously. Each side
carries its full received and sent asset lists **and** a grade letter that is a five-band
quantisation of `package_value(received)/package_value(sent)` at cut points 3/8/15/25/40 percent,
where the values come from the private contract's `displayValue`/`rankDerivedValue`. That is 393
published inequality constraints over a few hundred assets — roughly 2.32 bits each about a ratio
of private board values, obtainable with no session.

Distribution served anonymously: `A+ 114 · F 60 · A 55 · D 53 · B+ 41 · B 25 · A- 23 · C 22`.

```bash
curl -s http://127.0.0.1:8000/api/public/league | .venv/bin/python -c "
import json,sys,collections
d=json.load(sys.stdin); f=d['sections']['activity']['feed']
g=[s for t in f for s in (t.get('sides') or []) if isinstance(s,dict) and s.get('grade')]
print(len(f),'trades',len(g),'graded sides')
print(collections.Counter(s['grade']['grade'] for s in g))"
```

Evidence: `evidence/W22/public-trade-grade-census.json`. Confidence on this finding is
**medium**, and the author is explicit that it is a **product decision, not a bug**: the
isolation docstring reads as an absolute ("The raw values that drive the grade never leave the
backend"), and the literal claim is true. Either the docstring and `SECURITY.md` should record
that a bounded derived signal is deliberately published, or the anonymous path should pass
`activity_valuation=None` — mirroring `_redact_draft_capital_for_public`, which W22 calls out as
the same problem solved properly.

---

## 5. Admin allowlist enforcement

**Two authorization tiers exist (session-present, allowlist) and only the `/api/admin/*` prefix is
wired to the second one.** Route placement, not route capability, decided which tier applied.

### 5.1 Where the allowlist works

| Route | Anonymous | Non-admin session |
|---|---|---|
| `GET /api/admin/guest-passes` | 401 | **403 `admin_required`** |
| `POST /api/admin/nfl-data/flush` | 401 | **403** |
| `POST /api/admin/signal-state/migrate` | 401 | **403** |
| `POST /api/admin/guest-pass` | 401 | **403** |
| `POST /api/admin/guest-pass/{id}/revoke` | 401 | **403** |
| `POST /api/admin/sessions/force-logout-all` | not fired (destructive if the guard failed) | identical `_require_admin_session` first statement, server.py:11038 |

Guest-pass sessions carry the literal username `"guest"`, which the allowlist rejects — so the
docstring's promise ("a guest can browse the private surface but cannot trigger admin actions")
holds **for these six routes**.

### 5.2 Where it does not (W22-F007, P2 — confirms PRIOR-A06-F08)

Operator-grade actions outside the `/api/admin/*` prefix have **no allowlist check at all**;
session presence is their entire authorization.

| Surface | Gate found | Consequence for a guest-pass holder |
|---|---|---|
| `POST /api/scrape` (`trigger_scrape`) | session only — never calls `_require_admin_session` | Starts a full production scrape: minutes of Playwright work plus outbound traffic to every ranking site |
| `POST /api/test-alert` (`async def test_alert()`) | **takes no `Request` parameter at all**, so it structurally cannot check anything | Fires the configured email alert |
| `POST /api/intel/refresh` | `if not is_cron and not session: 401` + a 600 s per-user cooldown | Starts the multi-minute budgeted Sleeper crawl; `?leagueKey=all` walks **every active registry league** — W16-F011 |
| `/admin`, `/tools/source-health`, `/tools/ros-data-health`, `/tools/trade-coverage` | `middleware.js` checks cookie **presence** only | **All four returned 200** to the non-admin `e2e-test-user` session |

`/admin`'s "Not authorized" branch is **unreachable**: its sole load-time fetch is `/api/status`,
which is on the public allowlist. This is why gating `/api/status` (§3.2) fixes the page with no
page change — the two findings share one repair.

`0 of 3` operator-grade handlers outside `/api/admin/*` call `_require_admin_session`, against an
expected 3 (`W22-F007.numericProof`).

```bash
SECRET=$(cat .../e2e_secret.txt)
curl -s -c /tmp/c -X POST http://127.0.0.1:8000/api/test/create-session -H "Authorization: Bearer $SECRET"
for p in /admin /tools/source-health /tools/ros-data-health /tools/trade-coverage; do
  curl -s -b /tmp/c -o /dev/null -w "$p %{http_code}\n" http://127.0.0.1:3000$p; done
grep -n 'async def trigger_scrape' -A3 server.py
grep -n 'async def test_alert' -A2 server.py
```

### 5.3 The shared guest identity

Every guest-pass session is created with username `"guest"`, while `user_kv.user_state` has
`username TEXT PRIMARY KEY`. **All guests share one row.** Watchlist, `activeLeagueKey`,
`selectedTeam`, `siteWeights`, dismissed signals and `customAlerts` are overwritten guest-by-guest
— and a guest's `customAlerts` rules are executed by the daily sweep. Repair per the finding:
namespace as `guest:{guest_pass_id}`.

### 5.4 Navigation surfaces (W01-F004, P2 — confirms PRIOR-A06-F07)

`nav-model.js` states the rule outright: "Ops surfaces are ADMIN-ONLY in the nav … Offering a
door that is always locked is worse than not showing the door." **2 of 4 navigation surfaces
enforce it.** `TopBar.jsx:58` and `MobileChrome.jsx:106` call `systemItemsFor({isAdmin})`;
`frontend/app/more/page.jsx` maps `group.items` unfiltered, and `CommandPalette.jsx:42` calls
`paletteTargets()`, which has no `isAdmin` argument available. Fetched live with a session whose
`/api/auth/status` returns `isAdmin: false`, the `/more` HTML contains `Source Health`,
`ROS Data Health`, `Trade Coverage` and `>Admin<` **with their hrefs**. Not a hydration flash —
no code path in either component ever filters. `4` admin-only entries leaked on `2` surfaces.

---

## 6. Authentication and session handling

### 6.1 What holds

Repeated from §2 because it is the load-bearing half: HttpOnly + Secure + SameSite=Lax cookie,
30-day max-age matching the server TTL, `uuid.uuid4().hex` session ids (122 bits), guest passes
hashed at rest with a server-side `expires_at_epoch` re-checked per request, `hmac.compare_digest`
on both cron bearer tokens, constant-time-by-construction guest-pass validation (hashed-token
table lookup, plaintext never stored).

### 6.2 W22-F003 (P1) — the login endpoint has no login-specific defence

`HANDOFF.md` says there is no login rate limiting. The code's position is the opposite —
`/api/auth/login` is in `_PUBLIC_API_EXACT`, so the 60/min public limiter does cover it. **Both
are half right and the net effect is HANDOFF.md's.** The generic limiter is the only throttle:
`auth_login` has no attempt counter, no per-account lockout, no backoff, no delay.

Measured on the limiter-live `:8001` backend:

| Run | Result |
|---|---|
| 120 wrong-password POSTs, single IP, no XFF | `{401: 18, 429: 102}` |
| 200 wrong-password POSTs, rotating `X-Forwarded-For` | **`{401: 200}` in 0.9 s = 223 attempts/second, zero 429** |

Three compounding facts: there is exactly **one** credential (`JASON_LOGIN_USERNAME` /
`JASON_LOGIN_PASSWORD`), there is **no second factor**, and **nothing anywhere records or alerts
on a burst of failures** — not the logs, not `/api/status`, not the alert path. A leaked or
reused password gets confirmed instantly and silently.

Note also that sharing the limiter is itself a defect in the other direction: 60 requests to
`/api/public/league` in one minute lock the operator out of their own login.

Two smaller items in the same finding: `password == JASON_LOGIN_PASSWORD` at server.py:9838 is a
plain `==` where the bearer paths use `hmac.compare_digest`. (Observed while writing this doc and
not filed as a finding: `post_test_create_session` also uses `provided != expected`, server.py:10954
— it is 404-gated in production, so this is a consistency note, not an exposure.)

Reproduction: see `W22-F003.reproduction.command` — a 200-iteration urllib loop against `:8001`.
Transcript: `evidence/W22/probe-transcript.md#6-login-brute-force`.

### 6.3 W22-F004 (P2) — `ALLOW_DEFAULT_LOGIN_DEV` and the `.env.example` placeholder

`tests/conftest.py:11` says "production rejects `ALLOW_DEFAULT_LOGIN_DEV=1` by design", and
server.py:174-176 says "this guard prevents a misconfigured restart from silently shipping a known
password." **Neither is true.** The branch is `if not password: if _env_bool('ALLOW_DEFAULT_LOGIN_DEV', False): password = 'changeme'`.
Nothing consults an environment name, a hostname, `JASON_AUTH_COOKIE_SECURE`, or anything else.

Proven live on `:8001` with `JASON_LOGIN_PASSWORD` unset:

```
POST /api/auth/login {"username":"jasonleetucker","password":"changeme"}  → 200
GET  /api/auth/status  → {"username":"jasonleetucker", …, "isAdmin":true}
GET  /api/admin/guest-passes  → 200
```

The only signal is one WARNING at import time, which scrolls out of `journalctl`.
`startup_validation.run_all()` checks **8** things and **0** of them is the login password or this
flag — so `/api/health.startupChecks` reports `total: 8, ok: 8, failed: 0` on a box running the
placeholder password. **0 runtime surfaces report it.**

The second failure mode is independent and unguarded: `.env.example:52` ships
`JASON_LOGIN_PASSWORD=changeme` (confirmed at HEAD), so an operator who copies it verbatim gets
the same outcome **with the flag off**, because the import-time guard fires only on UNSET, never
on weak.

```bash
cd /home/user/riskittogetthebrisket && env -u JASON_LOGIN_PASSWORD ALLOW_DEFAULT_LOGIN_DEV=1 \
  .venv/bin/python -c "import sys;sys.path.insert(0,'.');import server;from fastapi.testclient import TestClient;c=TestClient(server.app);print(c.post('/api/auth/login',json={'username':'jasonleetucker','password':'changeme'}).status_code);print(c.get('/api/auth/status').json())"
grep -n 'JASON_LOGIN_PASSWORD' .env.example
```

**What works here:** the import-time `RuntimeError` for the fully-unset case is real and correct.
`EnvironmentFile=-.../.env` means a missing `.env` produces a **crash loop** rather than a silent
weak-password boot — that is the right failure.

### 6.4 W22-F009 (P3) — auth-varying bodies without `Vary: Cookie`

`/api/draft-capital` returns two different bodies for the same URL depending on the session cookie
(5 rookie fields + `rookieBoardRedacted`), and stamps `Cache-Control: private, max-age=60,
stale-while-revalidate=300` with `Vary: Accept-Encoding` **only**. A browser that loaded the public
`/league` draft tab and then signed in serves the redacted body from its private cache for up to
**360 s** (60 + 300), so `/draft` renders with every rookie name blank. Confined to one browser
profile — a correctness defect, not a disclosure one.

`/api/auth/status` returns username, `authMethod` and `isAdmin` with **no `Cache-Control` header at
all** — the only session-identity endpoint without `no-store`, while `/api/user/state` and
`/api/leagues` both set it.

The shared-cache half of the invariant holds: nginx attaches `proxy_cache` only to `/_next/static/`,
and `private` would bar a shared cache regardless. No `/api/*` response set both `Set-Cookie` and a
cacheable directive.

```bash
for u in /api/draft-capital /api/auth/status /api/user/state; do echo "-- $u"; \
  curl -s -o /dev/null -D- -b /tmp/audit-cookies.txt "http://127.0.0.1:8000$u" \
  | grep -iE '^(cache-control|vary):' | tr -d '\r'; done
```

### 6.5 Session cookie forwarding (W09-F007, P1 — confirms PRIOR-A06-F10)

Not an exposure, but it is an auth-plumbing defect: of four Next trade/angle bridge routes,
`suggestions/route.js` is the **only one** that does not forward `request.headers.get('cookie')`.
The identical request returning 200 against `:8000` returns **401 `auth_required`** through
`:3000`. 3 of 4 bridges forward correctly.

---

## 7. Rate limiting

**Every number in this section comes from the `:8001` backend booted without
`RATE_LIMIT_BYPASS_IPS`.** The shared audit stack on `:8000` has `127.0.0.1` bypassed, so it
cannot answer a limiter question about the loopback client.

### 7.1 The limiter works

```
70 × GET /api/health from one IP  →  60 × 200, then 10 × 429   (with Retry-After)
```

Token-bucket arithmetic, refill proportional to elapsed time, `_MAX_TRACKED_IPS` eviction,
fail-open on a raising `should_rate_limit`. All correct.

### 7.2 The key is attacker-chosen (W22-F002, P1 — **verified upheld**)

`server.py::_client_ip_from_request` (2906-2916) returns the **first** comma-separated entry of
`X-Forwarded-For` whenever the header is present, with no trusted-proxy check and no preference
for `request.client.host`. `src/api/rate_limit.py:78-109` buckets on that string verbatim.

nginx sets `X-Forwarded-For $proxy_add_x_forwarded_for`, which **appends** `$remote_addr` to
whatever the client sent — so in production the leftmost entry is entirely attacker-controlled.

```
burn the bucket for the real client IP → 429 confirmed
immediately, 20 × GET with rotating X-Forwarded-For: 203.0.113.N → 20 × 200
```

Expected 20 × 429, actual 0 (`W22-F002.numericProof`).

**Verifier's position** (`evidence/verify/W22-F002.json`, verdict `upheld`, `reran: true`): the
mechanism reproduces live. The verifier explicitly **did not run the author's verbatim command**
and flagged the substitution — they ran a probe on the audited `:8000` stack instead, where a
constant spoofed header produces the 60-then-429 sequence, proving both halves at once (the
bucket arithmetic is real *and* its key is the header). The verifier adds a consequence the
author did not state: `_BYPASS_IPS` is checked **against the same spoofable string**, so a
forged value defeats the bypass list too.

Blast radius, per the verifier: 12 entries in `_PUBLIC_API_EXACT` (server.py:2743-2778, including
`/api/auth/status` and `/api/auth/logout`, which the author omitted) + 2 prefix families
(server.py:2799-2808) + the 5-entry `_SELF_AUTHED_API_EXACT` set (server.py:2783-2798) ≈ **19 path
families**. The author's `12` was an undercount. P1 sustained; the verifier notes P0 was correctly
**not** claimed, since this is an abuse/security defect rather than a wrong number on a page.

Repair, per both author and verifier: prefer `X-Real-IP` (nginx **overwrites** it from
`$remote_addr`, so it is not client-controlled — and it is already set on all four locations,
so **no deploy change is needed**), fall back to `request.client.host`, and consult
`X-Forwarded-For` only after stripping a configured trusted-hop count from the **right**. Note
that while the key is attacker-chosen, `_MAX_TRACKED_IPS` eviction is also a memory-exhaustion
lever.

---

## 8. Input validation

**No leak found.** 12 traversal / encoding variants against the auth gate (§2) and a further set
against parameterised routes:

| Probe | Result |
|---|---|
| `/api/league/articles/../../../../etc/1/1/recap` | 404 |
| `/api/public/league/..%2Fetc%2Fpasswd.csv` | 404 |
| `/api/public/league/player/..%2F..%2Fetc%2Fpasswd` | 404 |
| `?limit=-1`, `?limit=999…` (overflow), `%00`, `%FF%FE` | all handled, no exception text |
| `player_id="' OR 1=1--"` | reflected into the JSON error body, **inert** — `Content-Type: application/json` |

Route-level parameter validation is real and visible in the probe matrix: 5 authenticated routes
answer **400 with a named error** rather than guessing (`/api/data/player-source-history` →
`Missing required 'name' query param`, `/api/gameplan` → `team_required`, `/api/playerctx/player`
→ `missing_param`, both `*/audit` routes → `assetId required`).

Transcript: `evidence/W22/probe-transcript.md#12-input-validation`.

---

## 9. Secrets in committed files

**Clean at HEAD.** Scan results (transcript §14):

| Check | Result |
|---|---|
| High-signal key patterns (AWS / Anthropic / OpenAI / GitHub / Slack, PEM blocks, JWTs) | **0 tracked hits** |
| Tracked `.env` files | **only `.env.example`**, all placeholders — confirmed at HEAD with `git ls-files \| grep -i '\.env'` |
| Log statements emitting session ids, cookies, passwords or tokens | **0** |

### 9.1 The prior admin-password claim — **does not reproduce at HEAD**

The 2026-07-29 audit reported the real admin password spelled out in five committed documents.
**Remediated.** At HEAD, **3 files** carry the marker `«REDACTED — see audit/AUDIT_REPORT_2026-04-28.md C1»`
and **0 files carry a literal**.

```bash
git grep -l 'REDACTED — see audit/AUDIT_REPORT_2026-04-28.md C1' -- .
# audit/AUDIT_REPORT_2026-04-28.md
# docs/status/master-implementation-audit.md
# docs/status/remaining-work-inventory.md
```

(The two other hits are this audit's own evidence files, which quote the marker.)

**But the class of defect that produced it is still open**, one layer down: `.env.example:52`
ships `JASON_LOGIN_PASSWORD=changeme` (§6.3). That is not a real secret, and it is not the prior
finding reproducing — it is a placeholder that becomes a live admin password on a verbatim copy,
because the boot guard fires on *unset* and never on *weak*.

### 9.2 Deliberate, documented, accepted

`config/leagues/registry.json` is tracked and carries both real Sleeper league ids. This is
**intentional** — `SECURITY.md` states "the league configuration … is readable by anyone" and the
repository is public. W22 verified the ids do unlock the second league via `api.sleeper.app`, and
concluded the **incremental** exposure through `/api/status` is zero (§3.2).

---

## 10. Error and log leakage

| Surface | Result |
|---|---|
| Global exception handler | Emits `errorType` only; the traceback is logged server-side and never returned |
| 13 anonymous hostile probes (traversal, null byte, negative, overflow) | **0 raw exception text** |
| Log statements | **0** emit session ids, cookies, passwords or tokens |
| Bearer rejection logging | Rate-limited to one line per 60 s; leaks only a length-**equality** boolean |
| `/api/status`, `/api/health` | **This is where the leakage is** — not tracebacks, but structured operational metadata served anonymously (§3.2, W22-F005). `source_health.source_failures` carries free-text failure reasons and per-breaker `lastError` strings |
| `x-request-id` | Present on responses (`x-request-id: 0vGpexIQDX7Z` observed live), opaque, no correlation with session |

---

## 11. What was NOT tested — results, not omissions

These are unmeasured, and saying so is different from saying they pass.

| Item | Why |
|---|---|
| **Production edge behaviour** | The audit container has no nginx. The security headers in `deploy/nginx/chaseupside.com.conf:122-131` (HSTS, nosniff, `frame-ancestors 'self'`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`) were read from the file and **never observed on a live response**. The full application CSP at line 141 is commented out; whether that is deliberate was not established. |
| **The limiter on the real path** | Every limiter number here is from a loopback socket on `:8001`. The behaviour behind nginx, with a real `$proxy_add_x_forwarded_for` chain, was not observed — though the code path is unambiguous from the two files. |
| **`POST /api/admin/sessions/force-logout-all`** | Not fired. Destructive if the guard had failed. Static evidence only: identical `_require_admin_session(request)` first statement at server.py:11038. |
| **Every POST/mutating route** | The read-only protocol forbade POSTing to `/api/user/*`, `/api/custom-alerts`, `/api/admin/*`, `/api/*/refresh` and `/api/*/run`. `/api/scrape` and `/api/test-alert` were assessed **by code reading**, not by firing them — the finding is that the handlers contain no admin check, which is a source-level fact. |
| **CSRF** | No finding, and no probe. The cookie is `SameSite=Lax`, which blocks cross-site POST by default, and no CORS middleware is registered — but no CSRF token mechanism was located and none was tested. Treat this as **unknown**, not as clean. |
| **Password strength / credential reuse** | The single operator credential's actual strength is unobservable. W22-F003's 223 req/s figure bounds the *attack rate*, not the search space. |
| **`X-Forwarded-For` handling anywhere other than the limiter** | Only the rate-limit key was traced. Whether any other code path trusts the header was not enumerated. |

---

## 12. Finding index

All nine W22 findings plus the cross-workstream security findings cited above. Priorities are the
merged (post-verification) values.

| id | P | Status | Title |
|---|---|---|---|
| W22-F001 | P1 | Implemented but defective | Backslash open redirect via `_sanitize_next_path` |
| W22-F002 | P1 | Implemented but defective | Rate limiter keys on unvalidated `X-Forwarded-For` — **verified upheld** |
| W22-F003 | P1 | Partially implemented | No login throttle, lockout or backoff; 223 attempts/s, one credential, no MFA |
| W00-F001 | P1 | Implemented but defective | `/api/draft-capital` serves real pick dollar values anonymously (13.2 s cold) |
| W09-F007 | P1 | Implemented but defective | The trade-suggestions Next bridge drops the session cookie → 401 from the browser |
| W22-F004 | P2 | Implemented but defective | `ALLOW_DEFAULT_LOGIN_DEV=1` → `changeme` is a full admin password, no prod guard, invisible on health/status |
| W22-F005 | P2 | Implemented but defective | `/api/status`, `/api/health`, `/api/scaffold/status` leak deploy paths, env-var presence, flags, source inventory, session counts |
| W22-F007 | P2 | Implemented but defective | Operator actions and pages gated on session presence, not the admin allowlist |
| W01-F004 | P2 | Implemented but defective | `/more` and the command palette ignore `adminOnly` (2 of 4 nav surfaces) |
| W01-F010 | P2 | Implemented but defective | `/api/scaffold/status` is publicly allowlisted, leaks absolute paths, and has zero callers |
| W26-F008 | P2 | Implemented but defective | Anonymous callers force a full draft-capital rebuild every 300 s; failing KTC never negative-cached |
| W22-F006 | P3 | Duplicate or conflicting implementation | `sitemap.js` is an unwired 4th consumer of the public/private split; `robots.js` misses `PRIVATE_EXCEPTIONS` |
| W22-F008 | P3 | Partially implemented | 393 anonymous trade grades encode bracketed private-board value ratios |
| W22-F009 | P3 | Implemented but defective | Auth-varying `/api/draft-capital` without `Vary: Cookie`; `/api/auth/status` without `no-store` |
| W10-F010 | P3 | Partially implemented | The anonymous draft board's dollar curve is the operator's, not Sleeper's — the allowlist comment is wrong |
| W16-F011 | P3 | **Implemented and verified** | `/api/intel/refresh` auth is correct (constant-time bearer, 401s, cooldown); residual is "any user", not admin |
| W19-F011 | P3 | Partially implemented | Public contract leaks no private valuation (0 blocklist hits over 2.08 MB); raw Sleeper ids do go out |

## 13. Suggested repair order

Ordered by (risk removed ÷ size), not by severity label.

1. **W22-F001** (XS) — parse-and-compare in `_sanitize_next_path`. Self-contained, one function.
2. **W22-F002** (S) — prefer `X-Real-IP`, fall back to `request.client.host`. No deploy change:
   nginx already sets it on all four locations.
3. **W22-F004** (S) — `.env.example` → `JASON_LOGIN_PASSWORD=` (empty), gate the dev flag on an
   explicit non-production marker, and add the two `startup_validation` checks so the condition is
   visible on `/api/health`. Emit the **check name only**, never the value — `/api/health` is
   anonymous (§3.2).
4. **W22-F005 + W22-F007 + W01-F010** (S–M, one coherent change) — move `/api/status` and
   `/api/scaffold/status` behind the session gate (the latter has zero callers). This makes
   `/admin`'s existing 403 branch fire with no page change, which is half of W22-F007.
5. **W22-F007 remainder** (M) — `_require_admin_session` on `trigger_scrape`, `test_alert` (which
   needs a `Request` parameter first) and `post_intel_refresh`'s non-cron branch; namespace guest
   `user_kv` rows per pass id.
6. **W22-F003** (M) — per-username failure counter with exponential backoff, keyed independently
   of IP so header spoofing cannot reset it, plus a log line and alert on N failures. Depends on
   step 2: the IP-side half is worthless until the key is trustworthy.
7. **W00-F001 / W10-F010 / W26-F008** — one owner decision on whether the pick dollar curve is
   public. If not: gate the route. If yes: correct the allowlist comment and add negative caching.
8. **W22-F006, W22-F009, W01-F004** (XS each) — import `isPublicPath` in `sitemap.js`; add
   `Vary: Cookie` and `no-store`; call `systemItemsFor` in `/more` and the palette.
9. **W22-F008** — needs an intent decision before code.
