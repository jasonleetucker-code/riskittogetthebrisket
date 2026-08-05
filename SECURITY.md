# Security Policy

This repository powers [chaseupside.com](https://chaseupside.com), a private
dynasty fantasy football valuation and trade-analysis tool for one league.
It is a personal project, not a commercial product, and it has no security
team behind it.

## Reporting a vulnerability

Use GitHub's **private vulnerability reporting**:

> repository → **Security** tab → **Report a vulnerability**

That opens a private advisory visible only to the maintainer. Please use it
rather than a public issue — an issue describing a live hole is a
disclosure, not a report.

If private reporting is not enabled, open an issue that says only that you
have a security finding and asks for a contact address. Do not include the
details.

**Expect a reply within about a week.** One person maintains this in their
spare time; there is no on-call rotation and no bounty.

## What is in scope

The live site and this repository:

- Authentication and session handling (`src/api/session_store.py`, the
  `/api/` default-deny gate in `server.py`, `frontend/middleware.js`)
- The public/private data boundary — anything that lets an unauthenticated
  caller read the private contract, player valuations, trade analysis, or
  BDVM output
- The public league pipeline (`src/public_league/`), which is deliberately
  reachable without a login and must never read the private contract
- Rate limiting (`src/api/rate_limit.py`)
- Deployment and CI (`.github/workflows/`, `deploy/`) — secret handling,
  privilege escalation, anything that turns repository write access into
  production code execution

Findings in the public league surface are worth reporting even though the
data is by design public: the boundary between it and the private pipeline
is the thing being protected, and it has failed before.

## What is out of scope

- Missing hardening headers with no demonstrated impact
- Automated-scanner output without a working proof of concept
- Denial of service, volumetric or otherwise
- Social engineering
- Vulnerabilities in third-party ranking sites this project reads from —
  report those to the sites themselves
- The accuracy of the valuation model. Wrong numbers are a bug; file an
  issue.

## Repository visibility

This repository is currently **public**. That is a deliberate choice by the
owner, made with the exposure understood — the valuation engine, the league
configuration and the tracked snapshots under `data/` and `exports/` are all
readable by anyone. Do not report "the source code is visible" as a finding.

What is *not* intended to be public is anything reachable from
`chaseupside.com` without a session: player valuations, trade tooling,
waiver and draft analysis, and BDVM output are all login-gated, enforced by
the backend's default-deny `/api/` gate and by `frontend/middleware.js`. A
way around either of those is exactly what this policy is for.

### The Sleeper league ID is not a credential

The main league's Sleeper ID appears in **18 tracked files besides this
one** — including `README.md` and `config/leagues/registry.json` — and is
recoverable from the root commit onward. **This is accepted, and it is
not a secret.** Do not report it as one.

(Counted with `git grep -l <id>`, which returns **18**. This file
deliberately does not repeat the literal — writing it here made the
count 19 and the sentence describing it wrong in the same edit.)

* **It is a public resource identifier.** Sleeper's read API takes it as a
  URL path segment and requires no authentication; every Sleeper call in
  this repo is an unauthenticated `GET` with no token or key.
  `src/api/league_registry.py:94-101` says so in its own words — "the
  Sleeper league ID is technically public (anyone can fetch
  `/v1/league/<id>`)". `/api/leagues` withholds it for **API decoupling**,
  so a league-identifier choice is not baked into URL formats — *not* for
  confidentiality. Do not cite that endpoint as evidence the ID is
  sensitive.
* **Rotation is not available.** Sleeper league IDs are immutable
  server-assigned identifiers. There is no rename or migrate; a new ID
  means a new league and the loss of all history. The prior IDs in the
  chain are committed too (`previous_league_id` in the snapshot).
* **Removing it would protect nothing.** The only thing it unlocks is
  reading rosters, transactions and manager *display names* — Sleeper
  exposes no real names — and that same data is already committed here:
  `audit/baseline/public_league_overview.json` carries every manager's
  `ownerId`, `displayName` and `avatar`, and `exports/latest/` carries
  234 `ownerId` fields. Scrubbing the ID from all 18 files would remove
  zero personal information.
* **A history rewrite is off the table.** It is in the **root commit**, so
  removing it changes every SHA in the repository — breaking every open
  PR, ~55 branches including the 17 `archive/*` kept as historical record,
  every existing clone, and the deploy checkout.

The genuine decision this touches is upstream and already recorded above:
whether the repository should be public at all. `OA-01` in
`docs/OWNER_ACTION_AUDIT_2026-07-29.md` covers it, and notes that a
visibility change is not retroactive.

## Credentials

No credential should ever be committed. `.gitignore` excludes `*.env`,
`.env*` (except `.env.example`), `*_session.json` and `.secrets/`.

If you believe a credential has been committed, report it privately as
above — do not open a public issue, and do not include the value.
