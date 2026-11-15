# Production network and security audit, read-only (2026-11-01)

- **Mode:** read-only, run from a developer machine outside the box. No sign-in, no auth
  bypass attempt, no load, no spoofed proxy header, no port scan beyond TCP 8000 and 3000.
  Nothing on production was changed.
- **Target:** `https://chaseupside.com` (resolves to `<box-ip>`; the address is withheld from this public repo), probed
  2026-11-01 15:26-15:28 UTC.
- **Base:** `origin/main` `653bc4448e`.
- **Extends:** [`LAUNCH_GATE_RECOMMENDATIONS_2026-10-28.md`](LAUNCH_GATE_RECOMMENDATIONS_2026-10-28.md)
  §4 (finding P-1) and [`PRIVACY_ABUSE_VERIFICATION.md`](PRIVACY_ABUSE_VERIFICATION.md) §7
  (ops items). This run closes the "direct reachability of `:8000` / `:3000`" question those
  documents left open.
- **Agent-OS-Receipt:** `47a8b19fff9d06da9b1a651aab5fb92f1e16d5f6`

Evidence tags: **[measured]** observed in this run; **[verified]** read in repo code or config.

## 0. Findings in one table

| ID | Severity | Finding | Fix owner |
|---|---|---|---|
| **S-1** | **HIGH** | The FastAPI backend (`:8000`, `server: uvicorn`) and the Next server (`:3000`) answer plain HTTP from the public internet on the box IP. The direct backend port also exposes the API schema. | box operator: loopback bind (D-net) and/or firewall |
| **P-1** (still open) | MEDIUM-LOW | None of the repo-declared nginx security headers are on live responses. | box operator: `deploy/apply_hardening.sh` |
| S-2 | LOW | Version disclosure: `Server: nginx/1.24.0 (Ubuntu)` and `X-Powered-By: Next.js`. | `server_tokens off;` in nginx; `poweredByHeader: false` in Next config |
| S-3 | INFO | `GET /api/public/league?leagueKey=...` echoes the supplied key in its 400 body (JSON-escaped, `application/json`). Without `nosniff` (P-1) this is a reflected-input-in-JSON pattern. | closes with P-1; optionally stop echoing the key |
| S-4 | INFO | `HEAD /api/leagues` answers 405 (GET-only route); `OPTIONS` on the advisor answers FastAPI's default 405 body. No data. | none needed |
| OK | — | CORS: no `Access-Control-Allow-*` header for a foreign `Origin` on a simple GET or a preflight. HTTP redirects to HTTPS. Private routes answer one fixed 401. The advisor answers one fixed 503 `disabled` (flag OFF). | — |

## 1. Probes and results

| # | Request | Result [measured] |
|---|---|---|
| 1 | `HEAD https://chaseupside.com/` | 200; headers: `Server: nginx/1.24.0 (Ubuntu)`, `X-Powered-By: Next.js`, `Cache-Control: s-maxage=60, stale-while-revalidate=...`, `Vary`, `ETag`. **No** `Strict-Transport-Security`, `X-Content-Type-Options`, `Content-Security-Policy`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`. |
| 2 | `HEAD https://chaseupside.com/api/health` | 200; `x-request-id`, `x-trace-id`, `traceparent`, `vary`. Same six security headers absent. |
| 3 | `HEAD http://chaseupside.com/` | 301 to HTTPS. |
| 4 | `HEAD https://<box-ip>/` (no SNI name) | 200, the site is served on the bare IP. |
| 5 | `GET http://<box-ip>:8000/api/health` (one TCP connect, 5 s budget) | **200**, connect 113 ms, `server: uvicorn`, no nginx in path. |
| 6 | `GET http://<box-ip>:3000/api/health` | **404 from the Next server** (port open and answering). |
| 7 | the framework's interactive-docs / schema paths on the direct backend port | **answered 200**: the direct backend port exposes the API schema (specifics reported to the coordinator, not recorded here). Through nginx the same paths are not served (404 / 401). |
| 8 | `GET /api/health` with `Origin: https://evil.example` | 200, **no** `Access-Control-Allow-Origin`. |
| 9 | `OPTIONS /api/public/league/trade-advisor/analyze` preflight from a foreign origin | 405, no `Access-Control-*`. |
| 10 | `GET /api/public/league` with a foreign origin | 200, `public, max-age=60`, no `Access-Control-*` (2.68 MB body; public by contract). |
| 11 | `POST /api/public/league/trade-advisor/analyze` with body `{bad` | 503 `{"error":"advisor_unavailable","message":"The trade advisor is not available.","reason":"disabled"}`. No stack trace, no parser detail. The flag is OFF, so the gate answers before body parsing and the response floor cannot be observed live. |
| 12 | `POST /api/trade/analyze-multi` with body `{bad` (anonymous) | 401 `{"error":"auth_required","message":"Sign-in required."}` |
| 13 | `GET /api/does-not-exist` | 401, the same fixed body (unmatched API paths do not reveal whether a route exists). |
| 14 | `GET /api/public/league?leagueKey=%00'zz` | 400 `{"error":"unknown_league","message":"Unknown leagueKey: \"\\x00'zz\"."}` (S-3). |

## 2. S-1 in detail

**Cause.** [verified] `server.py` binds `HOST = "0.0.0.0"` (line 118) and passes it to
`uvicorn.run`. [inferred from probe 6] The Next service also listens on all interfaces.
[inferred from probes 5-6, not from a rule listing] no host or provider firewall blocks the two ports, so the public interface
answers them. The actual firewall rules need the box (`ufw status`, provider panel).

**What it exposes.**
- The full backend surface without nginx: no TLS, no nginx `client_max_body_size`, no nginx
  timeouts, no server-level headers. A session cookie sent to the direct backend port would cross the
  internet in clear text (a user would have to type the port, so the exposure is mainly to
  scanners).
- The API schema. Auth still gates the private routes (this run did not test that past the
  probes above), but the schema removes the discovery cost for an attacker.
- The Next server on `:3000` directly.

**What it does not expose [verified, not tested live].** The rate limiter keys on
`src/api/client_ip.py::client_ip_from_request`, which honours `X-Real-IP` / `X-Forwarded-For`
only from a trusted peer (loopback nginx or `RATE_LIMIT_TRUSTED_PROXIES`). A direct `:8000`
caller is keyed on its own TCP address, so the direct port is not a header-spoofing bypass of
the advisor's limiter. This run did not send a spoofed header to production to confirm it.

**Recommendation (box operator; no repo change made here).**
1. Bind both services to loopback: `HOST="127.0.0.1"` for uvicorn (make it an env override so
   local dev keeps `0.0.0.0`) and `next start -H 127.0.0.1`. This is the existing **D-net**
   unit in `docs/EXECUTION_PLAN.md`, still unstarted.
2. Until then, or as a second layer, deny the two ports at the host firewall:
   `ufw deny 8000/tcp; ufw deny 3000/tcp` (confirm nginx reaches upstreams over `127.0.0.1`
   first; the systemd timers already call `http://127.0.0.1:8000`).
3. Optionally disable the framework's docs / schema endpoints in production.
4. Re-run probes 5-7: expected connection refused or timeout.

Close S-1 before any public advisor launch. It is independent of the advisor flag.

## 3. P-1 and S-2 in detail

`deploy/nginx/chaseupside.com.conf` declares, at server level with `always`: HSTS
(`max-age=31536000`), `X-Content-Type-Options: nosniff`, `Content-Security-Policy:
frame-ancestors 'self'`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy:
strict-origin-when-cross-origin` and `Permissions-Policy` [verified]. None of them is on the
live responses [measured], the same result as on 2026-10-28. The live nginx therefore does not
run the repo template. `docs/PROD-HARDENING.md` still says "PREPARED, NOT APPLIED".

Recommendation: on the box, `sudo bash deploy/apply_hardening.sh --dry-run`, read the nginx
diff, then apply. The script backs up the site, runs `nginx -t`, and restores the backup if the
test fails. Add `server_tokens off;` at the same time (S-2), and set `poweredByHeader: false` in
the Next config in a normal PR. Re-probe 1 and 2: expected six headers present and no version
string.

## 3a. Source permission evidence (F3, review of `PRIVACY_ABUSE_VERIFICATION.md` §5)

Re-checked on this head [verified]: `config/trade/public_advisor.json::approvedSourcePermissionRecord`
is `null`; `docs/owner/` holds **no** `.json` record of the type
`src/trade/public_advisor_permission.py` validates; no commit to `docs/owner/` since 2026-10-28
adds one. The registry still has 27 keys (the 15 provider groups of §5). Nothing below is
invented; "none" means no repository record of public derived use was found.

| Provider group | Public-use permission evidence? |
|---|---|
| Sleeper (rosters, picks, ownership; no value) | **Partial**: same use as the live public League Hub, and the 2026-09-25 attestation. No explicit public-derived-use record; non-commercial status is the owner's to confirm. |
| Signals (`signalsSf`; IDP keys held) | **None.** Recorded scope stops at "authenticated Calculator displays" (OD-3a). |
| KeepTradeCut (`ktcCrowdSfTep`, `ktcTradesSfTep`) | **None.** Ingestion-only wording (OD-3b). |
| IDP Trade Calculator (`idpTradeCalc`) | **None**, and the records conflict (`F-EXT-02` vs the 2026-09-25 attestation) (OD-3c). |
| DLF (5 keys), DraftSharks (2), IDP Show (`idpShowCombined`), Flock (2) | **None** for public use; 2026-09-25 attestation covers ingestion and project use only (OD-3d). |
| FantasyCalc, Dynasty Nerds, OTC, Fantasy Navigator, PFK, Dynasty Daddy, FantasyPros (3 keys), Yahoo/Boone | **None** for public use; same attestation scope (OD-3d). |

Result: the launch gate stays closed for `source_permission_unrecorded`, which is now the
first failing check now that `responseFloorMs` is set (owner decision 6). Public launch stays
OFF.

## 4. Not done, by design

No authenticated request, no auth bypass, no spoofed `X-Forwarded-For`, no load, no scan of any
port other than 8000 and 3000, no IPv6 probe, no production change. Still open from
`PRIVACY_ABUSE_VERIFICATION.md` §7 and needing the box: `ss -ltnp`, firewall rule listing,
`RATE_LIMIT_TRUSTED_PROXIES` / `RATE_LIMIT_BYPASS_IPS` values, IPv6 `$remote_addr`, and an
on-box measurement of the production `responseFloorMs`.

## Completion result

- **STATUS:** DONE for this read-only audit unit. The fixes are box-operator actions.
- **ACCEPTANCE:** security headers listed against `docs/PROD-HARDENING.md` (§1, §3); direct
  reachability of 8000 and 3000 tested with one connect each (§1 rows 5-7); CORS tested with a
  foreign origin (§1 rows 8-10); error bodies for malformed requests recorded (§1 rows 11-14).
- **EVIDENCE:** `curl` probes in §1, run 2026-11-01 15:26-15:28 UTC.
- **UNRESOLVED:** S-1 and P-1 remain open in production (box operator). The response floor
  cannot be observed live while `brisket_trade_advisor` is OFF.
- **BLOCKERS:** box access.
- **NEXT_ACTION:** box operator runs the loopback bind or firewall rule (S-1), then
  `deploy/apply_hardening.sh` (P-1, S-2), then re-runs §1 probes 1, 2 and 5-7.
