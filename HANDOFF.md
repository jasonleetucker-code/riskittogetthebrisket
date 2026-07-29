# Codebase Handoff: Risk It To Get The Brisket

*Original: 2026-03-21. Replaced 2026-07-29 — see "Why this was rewritten".*

**Live at:** `https://chaseupside.com` (nginx + Let's Encrypt).

> The original `riskittogetthebrisket.org` domain lapsed and was re-registered
> by a third party. Do not probe, link, or deploy to it.
> `deploy/nginx/riskittogetthebrisket.org.conf` is kept only as a reference
> diff against the live config and is marked DO NOT APPLY — its `:443` block
> points at certificate paths that no longer exist, so applying it fails
> `nginx -t` and aborts the reload.

---

## Start here

This file is a **pointer**, not a description. These documents are actively
maintained and checked against the code; read those instead:

| Document | What it answers |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Architecture rules, the valuation pipeline stage by stage, the scoring-profile vs leagueKey split, non-negotiables. **The authority.** |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System map |
| [`docs/ONBOARDING.md`](docs/ONBOARDING.md) | How to add a league, a source, or a feature flag |
| [`README.md`](README.md) | Setup and commands |
| [`UNIMPLEMENTED_BACKLOG.md`](UNIMPLEMENTED_BACKLOG.md) | What was discussed and not built, including things deliberately rejected |

Current manual/owner tasks live in
[`docs/OWNER_ACTION_AUDIT_2026-07-29.md`](docs/OWNER_ACTION_AUDIT_2026-07-29.md).

---

## Why this was rewritten

The previous version was generated on 2026-03-21 and was not maintained. By
July it was not merely out of date — it was **actively misleading**, and its
worst claim was one nobody would think to double-check:

> *"No CI/CD configured — tests run manually. Deployment is manual SSH +
> restart."*

There are **14 workflows**. `pr-validation.yml` gates every pull request and
`deploy.yml` ships every push to `main` to production with health
verification and auto-rollback. Anyone trusting that sentence would have
built a second deployment pipeline beside a working one.

It was wrong about the rest of the stack too. It documented a `Caddyfile`
that is not in the tree (production is nginx), a `Static/` vanilla-JS
frontend that has been removed (`FRONTEND_RUNTIME` is hardcoded to `"next"`
and pinned by `tests/api/test_frontend_migration.py`), a
`scripts/run_canonical_pipeline.py` that does not exist (the offline
canonical path was retired), and `DN_EMAIL` / `DN_PASS` env vars that appear
nowhere in the codebase.

Rather than patch a hundred stale lines into a differently-wrong document,
the body is replaced by the pointer table above. **Two documents describing
one architecture is how this happened**: `CLAUDE.md` was kept true and this
one drifted, with nothing flagging the divergence.

---

## Verified state, 2026-07-29

Checked against live production and the tree on this date. Confirmed, not
assumed.

**Stack.** Python 3.12 FastAPI + Uvicorn on `:8000`; Next.js 15 / React 19 on
`:3000`. Both are systemd units (`dynasty.service`,
`dynasty-frontend.service`). nginx terminates TLS, routes `/api/*` to the
backend and everything else to Next.

**One consequence worth internalising:** because nginx sends `location /`
straight to Next, `server.py`'s page routes are **not** in the production
path. Page protection is `frontend/middleware.js`; the backend's default-deny
`/api/` gate is the real authority.

**Health.** `contract_ok: true`, 1,094 players, all 21 ranking sources
fetched within 3 hours, `scrape_success_rate_24h: 1.0`.

**Sources.** 21 in the `_RANKING_SOURCES` registry
(`src/api/data_contract.py`), and all 21 were live in production on this date.
Ingestion is `Dynasty Scraper.py` plus `scripts/fetch_*.py`, **not** one
adapter per source — `src/adapters/` holds only `base.py` (the frozen
contract, imported by tests), `scraper_bridge_adapter.py`,
`sleeper_trending.py` and `ktc_crowd_faab.py`.

**Tests.** ~5,350 Python (25 skipped, 470 subtests) and ~1,518 frontend.
`make test` locally; `Validate PR` runs the same gates in CI.

---

## Known issues, re-verified 2026-07-29

Only items confirmed against current code. Anything from the March list that
could not be re-confirmed was dropped rather than carried forward on faith.

### Security

1. **No login rate limiting — STILL OPEN.** `src/api/rate_limit.py` is a
   generic per-IP limiter (60/min, 1000/hour) with no login-specific lockout,
   and `server.py` has no failed-attempt counter. Brute-force against the
   single operator account is slowed only by the generic limit.

   *Fixed since March, and no longer issues:* the hardcoded password default
   is gone (`server.py` refuses to start without `JASON_LOGIN_PASSWORD`; CI
   sets `ALLOW_DEFAULT_LOGIN_DEV=1` only to clear the import-time guard on
   runners that never serve auth), and sessions do expire —
   `SESSION_TTL_DAYS` is enforced by `src/api/session_store.py`.

2. **The repository is currently public.** A deliberate owner decision made
   with the exposure understood. It means the tracked snapshots under `data/`
   and `exports/` (~8,000 files), `config/leagues/registry.json` and the
   valuation engine are all world-readable. See `SECURITY.md`.

### Operational

3. **Alert cooldown is global** — one 1h cooldown covers all alert types, so a
   scrape failure and an uptime failure in the same hour send one email.

4. **The scraper's email path is unauthenticated localhost SMTP** —
   `smtplib.SMTP("localhost", 25)`. With no MTA listening it fails and logs
   "alert saved to file only". Distinct from `server.py`'s Gmail path
   (`ALERT_FROM` / `ALERT_PASSWORD`), which is the one that actually delivers.

5. **`KTC_TradeDB` / `KTC_WaiverDB` run partial** — production reports
   *"skipped — no playerID→name mapping available"*, `valueCount: 0`. The map
   is built by regexing `page.content()` for `"playerID": N … "playerName": "X"`
   within a 500-character window (`Dynasty Scraper.py`, in `scrape_ktc`); KTC's
   payload no longer satisfies it. The main KTC board is unaffected (500
   values). Affects the crowd-FAAB path only.

6. **Old data files accumulate** — `data/dynasty_data_*.json` has no retention
   policy.

### Pipeline

7. **`data/ros/aggregate/latest.json` has 6 duplicate player rows** (the same
   player under two naming conventions) and 16 rows with non-lowercase
   `canonicalName`; 40 of 666 rostered players fail to match.

8. **`test_anchor_curve_extrapolation_monotone` fails on `main`** — `Chase
   Young` ties at rank 107 against a strictly-increasing assertion. It is
   `livedata`-marked so CI deselects it: a real failure that is invisible.

See `UNIMPLEMENTED_BACKLOG.md` §9 for the full defect register and §10 for
operator-only items.

---

## Glossary

| Term | Meaning |
|---|---|
| **Contract** | The versioned `/api/data` payload. `src/api/data_contract.py` builds it; it is the single source of truth for live values. |
| **Scoring profile** | Which rules produce a player's value. Shared across leagues with identical scoring. Drives rankings. |
| **League key** | Which league's rosters, teams, managers and draft. Never shared. Drives context. |
| **`rankDerivedValue`** | The canonical blended board value every engine reads. |
| **BDVM** | Brisket Dynasty Valuation Model — the projection-driven *fundamental* value concept in `src/bdvm/`, deliberately never merged into the market board. |
| **Hill curve** | The percentile→value conversion in `src/canonical/player_valuation.py`. Refit weekly as a *challenger*; only a human promotes one. |
| **Scope master** | Per-scope Hill constants (GLOBAL / OFFENSE / IDP / ROOKIE). |
