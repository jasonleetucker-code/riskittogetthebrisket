# V1-59 — the FFPC Sharp bootstrap crashloop: one cause, three symptoms

**Lane 4 (Market / FAAB / Sharp).  Measured 2026-08-25.  Verification and
operational truthfulness only — no cohort, qualification, scoring or Sharp
semantics change.**

Claude 5 owns reconciliation, merge, deployment and L3 verification.

---

## 1. The reported chain

From production Bootstrap Sharp Records run `32813417583`, with every
non-skipped run failing back through Aug 22:

1. `chaseupside-ffpc-sharp.service` repeatedly hits its 30-minute
   `TimeoutStartSec`;
2. each cycle reports ~29m25–45s of **CPU** — spin, not slow external I/O;
3. ingestion dies at `platform_ledger.register_asset_alias`, via
   `hydrate_sleeper_asset_catalog`, from `scripts/crawl_ffpc_sharp.py`, with
   `sqlite3.OperationalError: database is locked`;
4. `record_ingestion_run` then hits the same lock;
5. so the service can fail without recording its own failed run.

These are not four faults.  They are one fault and its consequences.

## 2. The cause, measured

`register_asset_alias` repairs rows that were ingested before a mapping
existed:

```sql
UPDATE asset_movements
   SET canonical_asset_id=?, asset_id=?
 WHERE platform=? AND source_asset_id=?
```

`asset_movements` carried indexes on `(platform, ts)`,
`(canonical_asset_id, ts)`, `(manager_key, ts)`, `(league_key, ts)` and
unique `(movement_key)` — **none on `(platform, source_asset_id)`**.  SQLite's
own answer, on pristine `origin/main`:

```
SEARCH asset_movements USING INDEX idx_am_platform_ts (platform=?)
```

It can narrow to the platform and must then walk every row of that partition
looking for `source_asset_id`.

`hydrate_sleeper_asset_catalog` issues one such call **per player in
Sleeper's directory** (~11.4k), so the catalog pass costs
**O(players × movements)** and grows every time the ledger ingests anything.
That is answer **A**: the CPU is real work, done pointlessly, and it crossed
the 30-minute budget and stayed there.

Scaling confirms a scan rather than a lookup — cost doubles exactly with
movement count:

| movements | 20,000 | 40,000 | 80,000 | 160,000 |
|---|---|---|---|---|
| hydrate 300 players | 1.48 s | 3.01 s | 5.99 s | 12.08 s |

Answer **B** follows without a second cause.  The catalog pass is **one
transaction** (`connection.commit()` runs once, after the whole loop), so a
hydration that takes half an hour holds the ledger's write lock for half an
hour.  Every other writer — the next service instance, and the crawler's own
reporting — waits out its `busy_timeout` and raises `database is locked`.

Answer **C** is *no*: `register_asset_alias` does not over-commit.  Its
writes are already batched into the caller's single transaction, and its
other three statements (`canonical_assets` upsert, `asset_aliases` upsert,
`unmapped_assets` delete) are all primary-key lookups.  Only the
`asset_movements` repair was unindexed.  The fix is the index, not
restructuring the transaction.

Answer **D** has two halves, both measured on pristine `origin/main` with a
writer holding the ledger:

* `record_ingestion_run` opens its **own** connection, so it queues behind
  the very lock that caused the failure — and waits the full connection
  default, **30.12 s**, before raising.  On a unit already at
  `TimeoutStartSec` that wait is frequently long enough to be SIGKILLed
  mid-wait;
* nothing had claimed the attempt, and `platform_coverage` reports the
  newest run per platform — so with no row for the failed attempt it went on
  reporting the **previous SUCCESS**.  A crashlooping collector read as a
  healthy one.

## 3. The repairs

Three changes, each aimed at one of the above, none of them a workaround.

**`_REQUIRED_PLATFORM_INDEXES` + `ensure_platform_indexes`**
(`src/intel/platform_ledger.py`) — adds
`idx_am_platform_source ON asset_movements(platform, source_asset_id)`.

It sits **outside** the schema-version gate deliberately.
`_platform_schema_ready` checks columns, one table and the triggers, never
indexes, so an index added to `_PLATFORM_SCHEMA` alone reaches new ledgers
and no deployed one.  Bumping `PLATFORM_SCHEMA_VERSION` to deliver it would
re-run the entire platform migration (and its backup) on every deployed
ledger to add an index — the trade `src/sharp/roster_store.py` already
declined for its four additive tables.  Measured: `CREATE INDEX IF NOT
EXISTS` for an index that already exists takes **no write lock** and returns
in ~0 ms even while another connection holds one, so running it on every
connect cannot become a new contention source.  A failure to create is not
swallowed — a silently-missing index leaves the scan in place with no signal.

**`record_ingestion_run(..., busy_timeout_ms=...)`** — bounds how long the
recorder waits.  This does not make the write likelier to land; it makes the
attempt *survivable*, so the caller reaches its own reporting instead of
being killed mid-wait.  Contention still raises; nothing is swallowed.

**The crawler claims its run before the heavy work**
(`scripts/crawl_ffpc_sharp.py`) — a `status="running"` row with
`finished_ms` NULL, upserted by `run_id`, written before hydration.  Every
terminal path upserts over it, so a run that finishes is unaffected; a run
that dies leaves the truthful third state — *something started here and
never reported an outcome* — instead of letting the previous success stand.

## 4. Before / after

Same synthetic ledger, pristine `origin/main` versus this branch.

| | BEFORE | AFTER |
|---|---|---|
| alias-repair query plan | `SEARCH … idx_am_platform_ts (platform=?)` | `SEARCH … idx_am_platform_source (platform=? AND source_asset_id=?)` |
| hydrate 1,500 players / 60k movements | **21.12 s** (14.08 ms/player) | **0.30 s** (0.20 ms/player) — **70×** |
| cost vs movement count | linear (a scan) | flat (a lookup) |
| failure recorder under a held lock | waited **30.12 s**, then raised | waited **2.01 s**, then raised |
| coverage after a locked-out failure | `status='success'` — **FALSE-HEALTHY** | `status='running', finished_ms=None` — truthful |

## 5. What was deliberately NOT done

* **`TimeoutStartSec` is untouched** (1800 s in both service templates), and a
  test fails if it is widened.  Extending it would have hidden the spin.
* **Nothing was globally serialised.**  The contention had a bounded cause
  and a bounded fix; a process-wide lock would have traded a fast ledger for
  a quiet one.
* **No second Sharp ledger, no second staleness or health lane.**  The
  `running` state is an additional value in an existing free-text `status`
  column, not a new vocabulary.
* **No lock failure is swallowed.**  The recorder raises; the crawler logs at
  exception level, exits non-zero, and the `running` row stands as the
  durable statement.

## 6. Residual risk, stated

* The one-time index creation needs the write lock.  If a pre-repair
  instance is mid-hydration when the new code first connects, that creation
  blocks and raises — the same failure the box has today, clearing as soon as
  the old instance exits.  It is a one-time event per ledger.
* Hydration remains a single transaction.  At the post-repair runtime that is
  a lock held for well under a second, but a future catalog large enough to
  matter would want chunked commits.  Not needed at the measured size, and
  chunking would trade atomicity for concurrency without evidence that the
  trade is required.
* `platform_coverage` now surfaces `running`.  Any consumer that treats "not
  `failed`" as healthy would read a stuck run as fine; none in this repo does
  — the field is reported verbatim.
