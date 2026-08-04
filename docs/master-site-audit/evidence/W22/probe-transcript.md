# W22 — live probe transcript (security / auth / public-private boundary)

Stack: backend `:8000` (audit harness, `RATE_LIMIT_BYPASS_IPS=127.0.0.1`),
pages `:3000`. A **second backend on `:8001`** was booted from
`scratchpad/w22_launcher.py` with `RATE_LIMIT_BYPASS_IPS` unset (same
`run_scraper` neutralisation) for every rate-limit / login test. It was
stopped at the end of the workstream and the 16 admin sessions it minted in
`data/session_store.sqlite` (gitignored) were deleted.

## 1. Anonymous GET sweep — 67 GET operations

`anon-get-sweep.json`. Result: 42 × 401, 13 × 200 public, 4 × 404, 1 × 503.
Zero private-contract fields reached an anonymous caller.

Public 200s: `/api/auth/status` `/api/draft-capital` `/api/health`
`/api/league/articles` `/api/leagues` `/api/metrics` `/api/news`
`/api/public/league*` (7) `/api/rankings/sources` `/api/scaffold/status`
`/api/status` `/api/uptime`.

## 2. `/api/draft-capital` redaction — WORKS

```
anon pick keys:  adjustedDollarValue currentOwner dollarValue isExpansion isTraded
                 originalDollarValue originalOwner overallPick pick pickInRound round
auth pick keys:  … + rookieName rookiePos rookieKtcValue rookieKtcDollar rookieIdpDollar
auth-only:       ['rookieIdpDollar','rookieKtcDollar','rookieKtcValue','rookieName','rookiePos']
anon top-level:  rookieBoardRedacted: true          auth: null
```
72/72 picks redacted; the shared TTL cache is not poisoned (redaction copies).

## 3. Auth-gate bypass attempts — GATE HOLDS

| path (curl --path-as-is) | status |
|---|---|
| `/api/data` | 401 |
| `/api/DATA` | 401 |
| `/API/data` | 404 (route miss, no body) |
| `/api/public/league/../../data` | 404 |
| `/api/public/league/..%2f..%2fdata` | 404 |
| `/api/public/league/%2e%2e/%2e%2e/data` | 404 |
| `//api/data` | 404 |
| `/api//data` | 401 |
| `/api/data/` | 401 |
| `/api/data%00` | 401 |
| `/api/news/../data` | 401 |
| `/api/health/../data` | 401 |

## 4. Public-league payload guard — WORKS

`assert_public_payload_safe` blocklist grepped against the raw bytes of ten
anonymous public endpoints (2.08 MB + 9 others): **0 hits** for
`rankDerivedValue|canonicalConsensusRank|canonicalSiteValues|sourceRanks|`
`edgeSignals|edgeScore|ourValue|siteValues|tradeSuggestions|arbitrageScore|`
`confidenceBucket|marketGap`.

## 5. Rate limiting (:8001, limiter live)

```
70 × GET /api/health, one IP → 60 × 200 then 10 × 429      (limiter works)
burn bucket → 2 × 429 confirmed
immediately, 20 × GET with rotating X-Forwarded-For: 203.0.113.N → 20 × 200
```

## 6. Login brute force (:8001)

```
200 wrong-password POSTs, rotating X-Forwarded-For  → {401: 200} in 0.9 s = 223 req/s, no 429
120 wrong-password POSTs, single IP, no XFF          → {401: 18, 429: 102}
```
No account lockout, no failure counter, no backoff, single shared credential.

## 7. `ALLOW_DEFAULT_LOGIN_DEV=1` (:8001, `JASON_LOGIN_PASSWORD` unset)

```
POST /api/auth/login {"username":"jasonleetucker","password":"changeme"} → 200
GET  /api/auth/status → {"username":"jasonleetucker", … "isAdmin":true}
GET  /api/admin/guest-passes → 200 {"passes":[]}
```
Only signal: one WARNING at import. Not in `/api/health.startupChecks`,
not in `/api/status`.

## 8. Admin allowlist (:8001)

| route | anon | non-admin session (`e2e-test-user`) |
|---|---|---|
| `GET /api/admin/guest-passes` | 401 | 403 `admin_required` |
| `POST /api/admin/nfl-data/flush` | 401 | 403 |
| `POST /api/admin/signal-state/migrate` | 401 | 403 |
| `POST /api/admin/guest-pass` | 401 | 403 |
| `POST /api/admin/guest-pass/999999/revoke` | 401 | 403 |

`POST /api/admin/sessions/force-logout-all` was NOT fired live (destructive if
the guard failed); it uses the identical `_require_admin_session(request)` as
its first statement (server.py:11038).

## 9. Self-authed cron routes (:8001)

| route | anon | `Authorization: Bearer guess` |
|---|---|---|
| `/api/signal-alerts/run` | 401 | 401 |
| `/api/custom-alerts/run` | 401 | 401 |
| `/api/intel/refresh` | 401 | 401 |
| `/api/test/create-session` | 404 | 404 |

`E2E_TEST_MODE` unset in a clean process → 404 both with and without a bearer.

## 10. Page gate (`:3000`, anonymous)

307 → `/login?next=…`: `/admin` `/tools/ros-data-health` `/tools/source-health`
`/tools/trade-coverage` `/rankings` `/trade` `/settings`
`/league/insider-trading` `/trades` `/intel` `/market/sharp-tracker`
`/market/sharp-roster-percentage` `/design` `/phases` `/more` `/news` `/edge`
`/consensus-edge`.  200: `/` `/login` `/league` `/league/activity`.
308: `/draft-capital` → `/league?tab=draft-capital`.
Neither anonymous 200 HTML contains any private-board token.

With a NON-ADMIN session: `/admin` 200, all three `/tools/*` 200.

## 11. Open redirect (Chromium, real login form, :8001 via request interception)

```
GET /login?next=%2F%5Cevil.com
browser resolves /\evil.com -> http://evil.com/
after submitting jasonleetucker/changeme:
  offsite requests: ['http://evil.com/']
  frame trail: [ …/login?next=%2F%5Cevil.com, …, chrome-error://chromewebdata/ ]
```
Backend echo test:

| `next=` | `redirect` returned |
|---|---|
| `/\evil.com` | `/\evil.com`  ← **passes** |
| `/\/evil.com` | `/\/evil.com` ← **passes** |
| `//evil.com` | `/` (blocked) |
| `https://evil.com` | `/` (blocked) |
| `\evil.com` | `/` (blocked) |

## 12. Input validation / traversal — no leak found

`/api/league/articles/../../../../etc/1/1/recap` 404 ·
`/api/public/league/..%2Fetc%2Fpasswd.csv` 404 ·
`/api/public/league/player/..%2F..%2Fetc%2Fpasswd` 404 ·
`?limit=-1` / `?limit=999…` / `%00` / `%FF%FE` all handled.
User input is reflected into JSON error bodies (`player_id="' OR 1=1--"`) but
`Content-Type: application/json` makes that inert.

## 13. SSRF — none

`POST /api/trade/import-ktc` validates only `"keeptradecut.com" in url`, which
is trivially satisfiable — but `resolve_trade_url` **never fetches the supplied
URL**. It parses `teamOne`/`teamTwo` out of the query string and fetches the
hardcoded `_KTC_CALCULATOR_URL` (`src/trade/ktc_import.py:88`). Every other
outbound call site takes a module constant or a registry-resolved Sleeper
league id. Verified negative.

## 14. Secret scan at HEAD — clean

- High-signal patterns (AWS/Anthropic/OpenAI/GitHub/Slack keys, PEM blocks, JWTs): **0** tracked hits.
- `.env` files tracked: only `.env.example`, all placeholders.
- The 2026-07-29 audit's "real admin password spelled out in five committed
  documents" is **remediated**: 3 files carry
  `«REDACTED — see audit/AUDIT_REPORT_2026-04-28.md C1»`, 0 carry a literal.
- Log statements: 0 emit session ids, cookies, passwords or tokens.
- The tracked `config/leagues/registry.json` DOES carry both real Sleeper league
  ids — deliberate, documented in `SECURITY.md` ("the league configuration … is
  readable by anyone", repo is public).
