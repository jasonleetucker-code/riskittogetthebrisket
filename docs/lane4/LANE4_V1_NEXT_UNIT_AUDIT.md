# Lane 4 — what is actually left, and what to do next

**Audit date 2026-08-19, against `main` @ `d7b126d6d` (post-#920 reconciliation).
No code changed from this document.** The proposal at the end is a proposal; it
is not authorized and not implemented.

---

## 1. The shape of the problem

Fourteen V1 REQUIRED rows carry lane **L4**:

| status | count | rows |
|---|---|---|
| `VERIFIED` | 2 | V1-26, V1-55 |
| `IMPLEMENTED_UNVERIFIED` | **9** | V1-56, 57, 58, 60, 61, 63, 64, 65, 129 |
| `IN PROGRESS` | 2 | V1-59, V1-62 |
| `BLOCKED` | 1 | V1-89 |

**Nine of fourteen are `IMPLEMENTED_UNVERIFIED`.** That is the whole finding.
The code exists and has been reviewed; what is missing is *evidence*, and for
almost all of them the evidence is production-side.

Sorting those nine by what is actually blocking them:

| blocker | rows |
|---|---|
| an authenticated production read | V1-58, V1-60, V1-61, V1-129 (and half of V1-57, V1-59) |
| a production **filesystem** read (gitignored `data/`) | V1-57, V1-129 |
| a **UI consumer** proof (L4) | V1-56, V1-61, V1-62 |
| nothing — deterministic, and satisfied at #927's head | V1-63, V1-64 |

**Writing more Lane 4 code moves almost none of this.** The scarce resource is
not implementation, it is admissible evidence.

---

## 2. The two `IN PROGRESS` rows, measured rather than assumed

### V1-59 — "Sharp bootstrap stops failing" (L3)

Contract note: *"FFPC timeouts + SQLite locking."*

**The SQLite half looks already addressed, and the note appears stale.** Every
sharp store reaches SQLite through one connection owner:
`roster_store.ensure_roster_schema` → `platform_ledger.ensure_platform_schema` →
`ledger.connect`, and that owner sets

* `sqlite3.connect(..., timeout=30.0)` plus `PRAGMA busy_timeout=30000`
  (`src/intel/ledger.py:467-468`), and
* `PRAGMA journal_mode=WAL` + `synchronous=NORMAL` at schema application
  (`_apply_schema`, `:290-291`) — and `journal_mode` is persistent in the
  database file, so one application covers every later connection.

`ledger.py` also already distinguishes a routine `database is locked`
`OperationalError` from corruption (`:353-354`), which is the specific mistake
that used to escalate a lock into a rebuild.

The FFPC half has bounded HTTP (`timeoutSeconds: 20`, `retryLimit: 2`,
`requestBudgetPerRun: 100` in `config/sharp/ffpc_sources.json`).

**What this does NOT establish:** that the bootstrap now succeeds. Whether these
protections are sufficient in production is a `journalctl` question about the
04:20 → 04:50 → 05:50 chain, and that is L3 evidence, not code. **So V1-59's
remaining work is evidence, not engineering** — it sits behind the same wall as
V1-58, and shipping more code here would be guessing at a failure nobody has
measured recently.

### V1-62 — "Sharp Tracker" (L4)

Contract note: *"live but W15-F017 no memoization."* Confirmed: the only
`lru_cache` in `src/sharp/market.py` is on `_local_asset_catalog` (`:65`), a
display-metadata helper. `market_payload` recomputes the cohort, re-queries the
ledger for **every window**, and re-aggregates on each request.

Real, and worth fixing — but it is a **performance** defect, and the row's level
is **L4**, which needs a production-consumer proof. Memoizing would not move the
row's status by itself.

---

## 3. Proposed next unit

> ### A bearer-gated, read-only Lane 4 verification endpoint
>
> One change that converts **four rows directly and three partially** from
> permanently unverifiable into measurable.

### The problem it solves

Every recorded attempt to verify the Sharp rows ends the same way:

```
data/ops/sharp-production-smoke.json
  status: "unverifiable_unauthenticated"
  errors: [ ..., "401 from https://chaseupside.com/api/sharp/cohort" ]
```

Measured in the workflow's own comment: **80/80 attempts 401 across 79 runs.**
`/api/sharp/*` is session-gated, correctly, and
`tests/sharp/test_public_api_allowlist.py` pins that it is not public. **That
gate must not be relaxed.** So the rows cannot be verified by any automated
caller, and they have sat at `IMPLEMENTED_UNVERIFIED` for as long as they have
existed.

### Why this is provisioning, not bypassing

The repo already names the answer, in
`.github/workflows/verify-sharp-production.yml`:

> *"Provision a token for the smoke (see `_SELF_AUTHED_API_EXACT` in server.py
> for the bearer pattern used by `/api/signal-alerts/run`) to turn this into an
> enforcing gate."*

That pattern is live on three endpoints (`/api/signal-alerts/run`,
`/api/custom-alerts/run`, and the intel refresh): an env-configured shared
secret, compared with `hmac.compare_digest`, **empty means disabled** so it fails
closed with nothing configured. Adding a credential path is the opposite of
removing a gate.

### Scope, and the constraints that keep it small

* **Verdicts only, never data.** The endpoint returns the counts, states and
  booleans `scripts/verify_lane4_production.py` already computes — cohort size,
  `cohortCoveragePct`, `crowdMarket` state and census, the person-consensus
  semantic checks, timer artifact freshness. **No player, manager, roster or
  league identity crosses it.** A bearer token is a weaker credential than an
  admin session, so it must see strictly less; that is what makes the exposure
  acceptable rather than merely convenient.
* **Read-only.** No mutation, no trigger, no refresh.
* **Fails closed.** No token configured → the endpoint is not authenticated →
  401, the same answer as today. Nothing regresses if it is never provisioned.
* **Reuses the existing owner.** `_SELF_AUTHED_API_EXACT` plus the
  `hmac.compare_digest` check, not a fourth auth mechanism.
* **The verifier is already written.** `scripts/verify_lane4_production.py`
  computes every verdict; this unit exposes them, and adds no second definition
  of what "verified" means.

### What it unblocks

| row | effect |
|---|---|
| V1-58 Sharp cohort populated | **directly** — cohort size becomes readable by an automated caller |
| V1-60 FFPC lane honest | **directly** — `cohortCoveragePct` null-vs-zero measurable |
| V1-129 crowd comparability | **directly** — `crowdMarket` state and census measurable |
| V1-65 Insider / cross-league | **directly** — the L2 measured statement |
| V1-57 FAAB history timer | partly — artifact presence and age |
| V1-59 Sharp bootstrap | partly — crawl-coverage state; `journalctl` still needed |
| V1-61 Roster Percentage | partly — L4 still needs the UI consumer proof |

### Why not the alternatives

* **V1-62 memoization** — self-contained and shippable, but performance rather
  than correctness, and being L4 it cannot reach `VERIFIED` on a memoization
  commit. **This is the fallback** if the owner does not want an auth-surface
  change.
* **More V1-129 hardening** — the comparability owner is already the single
  owner and #927 closes the label defect. More code there measures nothing.
* **V1-59 engineering** — per §2, its protections are already in place; without
  a fresh production failure to point at, changes would be speculative.

### The one thing that needs sign-off before it starts

This touches the **authentication surface**, which is Lane 5/6 territory rather
than mine. It should not begin without Claude 5 agreeing to the shape —
specifically that a bearer credential may read verdicts, and that the
verdicts-only boundary is where the line sits.

---

## 4. Explicitly not proposed

* **Relaxing `/api/sharp/*`'s session gate**, or adding those paths to the public
  allowlist. The gate is correct.
* **Manufacturing a cohort, ledger, scoring card or crowd row** to close
  V1-58/V1-59. A manufactured population verifies the manufacture.
* **#804 / #921** — post-V1, flag **OFF**, cadence awaiting an owner decision
  (`docs/lane4/LANE4_804_CAPTURE_CADENCE_DECISION.md`). Nothing here changes the
  V1 percentage.
