# Live roster refresh: measured, not justified (2026-11-18)

Task 12 of the owner-authorized audit-remediation program (directive 2026-11-18): "do not add another polling mechanism
unless measurement shows a meaningful problem". **Measured; no code changed; closed as verified unnecessary.**
All data is read-only: production `GET /api/status` (public) and Sleeper's public API. No league ids or user names are
recorded here.

## 1. Where each league's roster timestamp lives

| league | roster source | clock | refresh |
|---|---|---|---|
| `dynasty_main` | the contract's own `sleeper` block, built by `fetch_sleeper_rosters` at the start of each backend scrape (`Dynasty Scraper.py`), stamped `rosterSource` / `rosterFetchedAt` (`_stamp_roster_source`) | `/api/status` `leagues[].source = primary-scrape`, `overlayFetchedAt = null` | backend loop, `SCRAPE_INTERVAL_HOURS = 2`, plus one startup scrape per restart |
| `dynasty_new` | on-demand Sleeper overlay (`src/api/sleeper_overlay.py`, `_CACHE_TTL_SEC = 15 * 60`, request-driven stale-while-revalidate) | `overlayFetchedAt` / `overlayAgeSec` | already at most 15 min old when a user asks |

The N-team trade engine reads roster age through `src/api/roster_freshness.py` (one reader): `current` only when
`rosterSource == "live"` and age <= 6 h (`SCORING_SNAPSHOT_MAX_AGE_HOURS`); a restored `last_good` block or a live block
older than 6 h is `stale`; no provable stamp is `unknown`. `trade_ledger` makes assets on non-`current` rosters
unverifiable (refused), never guessed.

## 2. Roster-age distribution, `dynasty_main`

Method. `/api/status` `last_n_scrapes` (sampled 2026-11-18 ~11:22 UTC) gives four consecutive box scrapes:
completion 04:27, 06:28, 08:33, 10:38 UTC, durations 289 / 306 / 283 / 282 s, all `success`
(`scrape_success_rate_24h` 4/4; `scrape_count` 4, so no restart since ~04:22). The roster fetch runs at scrape start
(module-level load in the scraper) and is published when the run completes, so start-to-start gaps are 2.006, 2.094,
2.088 h (mean 2.06 h) and publish lag is about 0.08 h. At a uniformly random moment the served roster age is uniform on
[lag, gap + lag]; 200,000-draw simulation over those measured values:

| quantity | value |
|---|---|
| p50 roster age | **1.11 h** |
| p95 roster age | **2.04 h** |
| maximum in a healthy cycle | 2.14 h |
| engine refusal threshold | 6 h |

Restarts only help: every deploy boots with an immediate startup scrape (`SCRAPE_CADENCE_MEASUREMENT_2026-11-09.md`
section 2, 6 to 8 per day), which resets the roster clock earlier, never later. The 6 h threshold is therefore crossed
only by about three consecutive failed or missed box scrapes (a failed fetch restores `last_good`, state `stale`).
The repository records no history of box scrape failures (the CI refresh in `scheduled-refresh.yml` is a different
runner and clock: about 6.6 h apart, 3.6 runs/day, and does not set the served roster stamp), so a failure rate cannot
be measured from here beyond the 24 h window above (0 of 4). This is the one number the data cannot supply.

`dynasty_new`: `overlayAgeSec` was 2740 s (46 min) at the sample, because the overlay refreshes on request and nobody
had asked for 31 min after its last refresh; the design bound a user sees is 15 min plus one background rebuild.

## 3. Trade-to-visible windows (real Sleeper trades)

Sleeper `transactions/<week>` for `dynasty_main`, weeks 0 to 18 (2026 season, now week 11): **84 completed trades**,
2026-08-13 to 2026-11-17 (7 in the last 30 days; busiest day 5 on 2026-08-24, 2 clusters of 3 within 4 h in
October). A trade at a uniform random moment becomes visible at the next scrape's roster fetch plus publish lag:

| quantity | value |
|---|---|
| p50 window pre-trade ownership is served | **1.11 h** |
| p95 | **2.04 h** |
| mean | 1.11 h |
| share of wall-clock time with at least one trade pending (84 trades, union of mean windows over 314 days) | **about 1.1 %** |

Two different failure modes, kept separate:

* **Refusal** (`ownership_unverifiable`, `stale`, `asset_not_owned`): fires only on `stale` / `unknown` rosters or an
  asset the snapshot says the sender lacks. Healthy-cycle roster age never exceeds 2.14 h, so the 6 h staleness gate
  does not fire in a healthy cycle. A just-traded asset is NOT refused but **misattributed to its pre-trade team**
  for the window above (for `asset_not_owned`, a user analysing a trade that already happened would be told the
  sender does not hold the asset). Production exposes no counter of these refusals publicly, so the rate is estimated
  as: P(a given analysis hits a pending-trade window) is bounded by the 1.1 % time share, and lower for a user who
  analyses a pair of teams not involved in the pending trade.
* **Staleness refusal**: needs a multi-scrape outage; not observed.

## 4. Sleeper request budget

Sleeper's guidance is about 1,000 requests/minute per IP. One `dynasty_main` scrape issues about 10 to 30 calls
(players/nfl once, then rosters, users, league, drafts and per-draft detail, traded_picks, and a few transactions
weeks), i.e. under 0.3 requests/minute averaged over a 2 h cycle; `dynasty_new` adds one overlay build per 15 min of
traffic (50 to 100 calls cold, per `sleeper_overlay.py`). A hypothetical 10 to 15 min light refresh (rosters +
traded_picks + current-week transactions: 3 calls) adds roughly 12 to 18 calls/hour, about 0.3 requests/minute, which
is 0.03 % of the budget. **The budget is not the obstacle either way**; the cost of a light refresh is new moving
parts (a second writer of the contract's `sleeper` block, atomic swap against the shared `latest_contract_data`,
a stamp that must stay consistent with the board generation), not Sleeper load.

## 5. Decision

**Not justified. Closed as verified unnecessary; nothing implemented.**

* p95 roster age 2.04 h is a third of the 6 h engine threshold; the maximum healthy age is 2.14 h.
* Misattribution after a real trade is bounded by 2.14 h with a median of 1.11 h (about 1.1 % of the time), well above
  the 30 to 60 minute bar the task set as "material" only at the tail, and the 7 trades in the last 30 days are
  low frequency. A user who has just traded can also see the pre-trade state clearly labelled by the roster stamp.
* The one condition that would change the answer, a box scrape outage making rosters `stale`, is better addressed by the
  existing `source_health` / watchdog alerting than by a second poller.

Revisit if any of: (a) production gains a counter of `ownership_unverifiable` / `asset_not_owned` refusals and it shows
a material rate; (b) the backend scrape cadence is relaxed beyond about 4 h (e.g. `conditional_startup_scrape` plus a
longer interval); (c) owners report acting on stale ownership in the first hour after a trade. The cheapest design then
is to reuse the overlay builder for `dynasty_main` and swap the `sleeper` block atomically on a copy (never mutating
`latest_contract_data`), with an explicit `stale` state on failure.

## Reproduce

```bash
curl -s https://chaseupside.com/api/status | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['leagues'],d['last_n_scrapes'])"
# Sleeper: GET /v1/league/<id>/transactions/<week> for week 0..18, filter type=trade, status=complete
```
