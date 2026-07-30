# Audit — Sharp Tracker vs Insider Trading

**Date:** 2026-07-29 · **Scope:** `src/intel/`, `/api/intel/*`, `/intel`, and every
other Sleeper-transaction consumer in the repo.

Method: nine parallel readers over the subsystems, every defect claim then handed to an
independent adversarial verifier instructed to *refute* it and to default to "refuted"
when it could not reproduce the evidence itself. 13 claims survived; 7 were refuted or
materially corrected. The corrections are recorded here too, because two of them changed
what the fix should be.

---

## 1. The headline: one feature wearing two product names

`src/intel/__init__.py` opens with:

> `"""Sleeper league-mate intelligence ("Sharp Tracker", Phase 5).`

`crawler.py` states the cohort plainly:

> `Pool = the active league's members (``member_ids``).`

The nav has exactly one entry (`frontend/lib/nav-model.js:79`):

> `{ href: "/intel", label: "Sharp Tracker", hint: "What league-mates buy/sell across their leagues" }`

So the shipped feature took **Sharp Tracker's name and board UI** and pointed it at
**Insider Trading's cohort**. The consequence is that *neither* product exists:

- **Sharp Tracker does not exist.** Nothing anywhere in `src/intel/` filters, scores, or
  ranks managers by skill. There is no discovery beyond one league's members, no
  eligibility model, no Sharp Score, no qualification snapshot. The name was borrowed
  from PlayForKeepsDynasty, where "sharp" means a curated pool of proven winners. Ours
  means *"the other eleven people in your league"* — including, structurally, the least
  sophisticated manager in it.
- **Insider Trading does not exist.** The string `insider` appears **zero times** in the
  entire repository. There is no sell mode, no buy mode, no current-owner analysis, no
  positional-need join, no value-matched assets, no trade construction, no lead scoring.

What *does* exist is a genuinely good acquisition layer, and the audit's main surprise is
how much of the reported problem was **not** where it was expected.

---

## 2. What was reported vs. what is actually true

The brief suspected transaction double-counting of the form *"1 add in 30 days + 1 add in
90 days = 2 adds"*. That specific failure **does not occur**. Two mechanisms already
prevent it, and both are test-pinned:

- **Dedup is sound.** Every event carries a deterministic
  `eventId = {tx_id}:{owner}:{action}:{asset_id}[:discriminator]`, rejected at extraction
  (`crawler.py:265-270`) and again on merge (`store.py:193-202`), with the crawler's
  `known_event_ids` seeded from the persisted snapshot (`crawler.py:435-439`). Re-ingesting
  identical source data is a genuine no-op.
- **Windows are overlapping views, not additive buckets.** `aggregate.py:128-130`
  increments each window whose span contains the event. Edge semantics are pinned to the
  millisecond by existing tests.
- **Identity is already correct.** Everything keys on Sleeper's global `owner_id`, never
  username.

These were preserved rather than rewritten.

### The real defect is one layer up

**`trend_score` (`aggregate.py:41-42`)** — `3·net48h + 2·net7d + 1·net30d` — is the
board's headline column *and* its sort key, with the formula printed to users
(`page.jsx:283-284`).

The verifier correctly pushed back on calling this a "double count": the windows are
nested, so the effective weight is a monotone step-decay — 6 inside 48h, 3 from 48h–7d,
1 from 7d–30d, 0 beyond. That is a defensible recency-weighting scheme, and it is
test-pinned as intentional.

It is still replaced, for three reasons that survive that correction:

1. **The disclosed coefficients are wrong by 2× at the top of the curve.** Users are told
   `3·net48h`; a 48-hour-old event actually carries weight 6.
2. **It ranks thin-and-fresh above broad-and-sustained.** One buy today (score 6) outranks
   five buys ten days ago (score 5) — precisely the failure the brief names when it says a
   1-buy asset must not read as strong as a 40-buy one.
3. **It is a sum of overlapping windows**, which the brief rules out explicitly.

The `14d` window is computed and displayed while contributing nothing to the score.

---

## 3. The systematic inversion (most damaging finding)

Three separate defects compose into one that is worse than any of them alone.

**(a) `txType` is captured and then thrown away.** `crawler.py:240` admits
`("trade", "waiver", "free_agent")`; `crawler.py:280` stamps `txType` on every event. No
consumer anywhere in the repo ever reads it — not `aggregate.py`, not `service.py`, not
`server.py`, not the frontend. `aggregate.py:127` buckets purely on direction:

```python
bucket = "buys" if event["action"] == "add" else "sells"
```

So every waiver claim and free-agent pickup is reported to users as a **buy**, and every
drop as a **sell**.

**(b) Waiver moves are single-sided; trades are two-sided.** A waiver add emits one event
(+1 net). A trade inside the tracked pool emits a paired add *and* drop, netting to
**exactly zero**.

**(c) The seed league is in every member's league list**, so every trade in your own
league is guaranteed to have both counterparties tracked.

Composed: **waiver churn always scores, real trades cancel to nothing.** The board is
structurally inverted — it surfaces the noise and suppresses the signal it exists to show.

A related asymmetry, confirmed by the verifier: the same acquisition scores `net 0` when
the counterparty happens to be tracked and `net +1` when they are not, so the number
depends on crawl coverage rather than on market behaviour.

---

## 4. Confirmed defect register

| # | Defect | Location | Status |
|---|---|---|---|
| D1 | `txType` stamped but never read — waiver/FA adds counted as trade buys | `crawler.py:240,280`; `aggregate.py:127` | **Fixed** |
| D2 | `trendScore` sums nested windows; disclosed weights wrong by 2× | `aggregate.py:41`; `page.jsx:283` | **Fixed** (retired) |
| D3 | `leagueCount` unions *held* and *traded* leagues — a widely-rostered player looks widely-traded | `aggregate.py:146` | **Fixed** |
| D4 | Net shown without volume; 1-buy and 40/39 both render "+1" | `page.jsx:330-346` | **Fixed** |
| D5 | No unique-manager / unique-league counts, no confidence indicator | `aggregate.py:143-153` | **Fixed** |
| D6 | No position filter, buy/sell filter, sort control, search, or underlying trade list | `page.jsx:253-271` | **Fixed** |
| D7 | No dynasty/redraft filter — redraft and best-ball leagues feed a dynasty board | `crawler.py:499` | **Fixed** |
| D8 | 45-day retention makes 90-day and season windows unanswerable | `store.py:42` | **Fixed** (400d) |
| D9 | Pick holdings seeded unconditionally for 3 future seasons off a wall-clock year, even when `/traded_picks` is empty | `crawler.py:190-198,563` | **Fixed** |
| D10 | `movement_id` embeds *attributed* owner, rebuilt per run from live `/rosters`; a co-ownership change can re-key the same transaction | `crawler.py:155-158,265` | Open — see §7 |
| D11 | `faab_contention.load_intel_snapshot` called unwrapped in an async handler (blocking I/O on the event loop) | `server.py:5140` | **Fixed** |
| D12 | `build_player_payload` re-aggregates the entire event log per request | `service.py:404-410` | **Fixed** (ledger) |
| D13 | Any signed-in session can POST `/api/intel/refresh` unthrottled | `server.py:12105` | **Fixed** (cooldown) |

### Claims that were refuted or corrected

Recorded because they changed the plan:

- **"Events are appended without a dedup key."** False — see §2.
- **"`trendScore` is a double count."** Corrected to "recency decay whose disclosed
  coefficients are wrong and which is a sum of nested windows" (§2).
- **"Intra-pool trades netting to zero is a double-count bug."** Corrected — it is
  documented, test-pinned, and internally coherent. The real defect is the *asymmetry*
  in §3, which is why the fix reports volume and unique buyers/sellers separately rather
  than changing how netting works.
- **"FAAB in trades is silently mis-ingested."** Corrected — trade-leg FAAB
  (`tx.waiver_budget`) is simply not ingested at all, consistently across the repo.

---

## 5. Duplicate and competing implementations

There are **five** independent Sleeper `/transactions/{week}` fetchers, each with its own
chain depth, week loop, timestamp field, type filter, and dedup set:

| Fetcher | Chain depth | Types | Timestamp |
|---|---|---|---|
| `Dynasty Scraper.py` | 4 | trades only | `created` |
| `src/api/sleeper_overlay.py` (`_build_trades_block` + `_build_waivers_block` — two siblings over the same feed) | 2 | split | `status_updated or created` |
| `src/public_league/sleeper_client.py::fetch_transactions` | — | both | — |
| `src/intel/crawler.py` | 1-hop star | all three | `status_updated or created` |

On top of the public snapshot sit **five** separate per-manager trade/waiver counters
(`activity.py::_by_manager_counts`, `superlatives.py::_activity_counts`,
`franchise.py::_trade_waiver_counts`, `records.py`, `overview.py`) — two of which are
logically byte-identical — plus a sixth client-side one in
`frontend/lib/league-analysis.js::analyzeTradeTendencies`.

Consolidating these is real work and is **deliberately not in this PR** — they are live,
independently tested, and unifying them alongside a storage migration would make the diff
unreviewable. The ledger is the eventual convergence point. Tracked as follow-up.

Relevant overlap for Insider Trading: `src/public_league/activity.py::_partner_pairs`
already computes completed-trade counts per `(ownerA, ownerB)` pair and is live on
`/api/public/league/activity` — and `roster_intel/partner.py`'s `pair_trades_completed`
input was designed to consume exactly that number.

---

## 6. Sleeper API capabilities and limits (verified live, not assumed)

The entire official surface is one page — <https://docs.sleeper.com/> — 18 read-only
endpoints, no auth, and **no global directory of any kind**. Every read starts from a
known `user_id`, `username`, `league_id`, or `draft_id`.

- **There is no "list all users" and no "list all leagues" endpoint.** Confirmed against
  the docs. Global discovery is impossible; outward graph traversal is the only option.
- **Traversal works and is public.** `GET /v1/user/{user_id}/leagues/nfl/{season}` returns
  any user's leagues unauthenticated — verified live against this repo's own league (5
  members → 9 distinct 2026 leagues, ~270 ms/call). This is what makes a growing
  first-party cohort viable.
- **Rate policy is one sentence**: *"stay under 1000 API calls per minute, otherwise you
  risk being IP-blocked."* No quota headers, no quota endpoint; 429 is documented. A
  50-call burst returned 50×200.
- **`previous_league_id` chains seasons** — verified 3 deep (2026 → 2025 → 2024), which is
  how multi-season history becomes derivable.
- **`winners_bracket`** returns played results with `w`/`l` roster ids and `p: 1` marking
  the championship game — so championships and playoff appearances are derivable.
- **Trades carry `draft_picks` and `waiver_budget` (FAAB) legs**, a stable snowflake
  `transaction_id`, and `status: "complete"`.

Every input the Sharp Score needs is therefore obtainable. The binding constraint is
call budget and crawl breadth, not API capability.

---

## 7. Note on D10 (the one dedup hole)

`movement_id` inherits the crawler's `eventId`, which embeds the **attributed** owner —
and attribution prefers a pool co-owner when the primary owner is not in the pool
(`crawler.py:155-158`), recomputed each run from live `/rosters`. If co-ownership changes,
the same underlying transaction can produce a different key and be counted twice.

This is narrow (it needs a co-ownership change on an already-crawled transaction) and is
**not** fixed in this PR, because changing the key shape requires a coordinated
re-migration. The ledger's schema makes the eventual fix cheap: `tx_id` is already a
column, so a canonical re-key can be applied with a single `UPDATE ... GROUP BY` pass.
Tracked as follow-up; called out here rather than left to be discovered.

---

## 8. Target architecture

```
Sleeper ingestion (shared, one crawler)
        │
        ▼
Normalized SQLite ledger  ──  transactions / asset_movements / users / leagues
        │
        ├──────────────────────────┬──────────────────────────
        ▼                          ▼
  Sharp Tracker              Insider Trading
  global qualified cohort    the selected league's members
  /market/sharp-tracker      /league/insider-trading
  aggregate market signal    individual trade leads
```

Shared below the line. **Completely separate product logic above it** — separate routes,
services, queries, empty states, copy, and tests.
