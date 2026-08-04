# Sharp Roster Percentage — methodology

**Status:** shipped. No feature flag — it adds a route and a page and
touches no existing output. It is empty until
`scripts/crawl_sharp_rosters.py` has run, and says so rather than
erroring.

```
Sharp Roster Percentage
  = unique ELIGIBLE sharp rosters containing the player
  ÷ eligible sharp rosters whose league can field his position
```

## The pool is the Buy/Sell Tracker's pool

`src/sharp/cohort.py::cohort_members` is the single definition of "who
is a sharp". The Sharp Buy/Sell Tracker (`src/sharp/market.py`), this
board (`src/sharp/roster_percentage.py`), the roster collector
(`src/sharp/roster_collect.py`) and the activity crawl
(`scripts/crawl_sharp_activity.py`) all call it. There is no second
list, and a change to qualification moves every one of them in the same
deploy.

Those definitions used to live inside `market.py`. Extracting them was
the first commit of this feature, specifically so the obvious way to
build a second sharp surface would not be to import a transactions board
to get a manager pool — or, worse, to re-derive one.
`market.py` re-exports every name, so `sharp_market.cohort_members`
still resolves for existing callers and tests.

`tests/sharp/test_roster_percentage.py::test_both_boards_resolve_the_pool_through_the_same_function`
pins the identity, and a companion test greps this module for
qualification vocabulary (`score_managers`, `minScorePercentile`,
`ManagerRecord`) so a fork announces itself.

Qualification itself is unchanged and is documented where it lives:
league gates in `src/intel/league_filter.py` (dynasty only, ≥ 2
seasons), manager gates and scoring in `src/sharp/score.py` +
`config/sharp/scoring_v2.json`.

## Rosters are the denominator, people are not

A sharp with five legitimate dynasty teams contributes **five roster
observations**; a sharp with one contributes one. That is the product
definition — the question is what share of sharp *rosters* hold a
player — and it is also the only version that can be checked against
anything.

Both numbers ship. `transparency.eligibleRosters` counts rosters;
`transparency.uniqueSharpManagers` collapses linked accounts to humans
through `cohort.canonical_manager_ids`, which reads the verified
`manager_identity_links` table. An unlinked account maps to itself
rather than being dropped — an unproven link is not a merge.

## The denominator is per player

A linebacker cannot be rostered in a league with no IDP slots; a kicker
cannot be rostered in a league with no K slot. Dividing every player by
every sharp roster would report ~20% for an IDP who is owned in *every*
league that can roster him, and the number would be an artifact of the
cohort's format mix rather than a fact about the player.

Each player is therefore measured against the rosters whose league is
known to field his position family (`_denominators`,
`_roster_supports_family`). Three consequences worth knowing:

* **A holding roster is always inside its own denominator.** A roster
  that demonstrably holds an IDP proves its league fields IDP, whatever
  the format capture says. Without this rule an unknown-format roster
  could contribute a numerator it was excluded from counting against,
  and a percentage could exceed 100%.
* **Unknown formats are excluded, not assumed.** They are reported in
  `dataQuality.formatUnknownRosters`.
* **`eligibleRosters` is published per row**, because it differs
  between rows on the same board.

## Deduplication is structural

Every counting rule is a primary key in `src/sharp/roster_store.py`, not
a filter a caller could forget:

| Hazard | Mechanism |
|---|---|
| Same roster collected twice, duplicate import, re-snapshot | `sharp_rosters` PK `roster_key` = `"<league_key>#<source_roster_id>"`, upsert in place |
| A player counted twice on one roster | `sharp_roster_assets` PK `(roster_key, canonical_asset_id)` |
| Two sharps in one league | Both resolve to the same `league_key`; each roster is its own `roster_key`, and the league is fetched once |
| Taxi/IR double count | Sleeper's `players` array already contains taxi and reserve ids; those arrays are read only to *label*, never as extra populations |
| **Season chain** — one dynasty league under a new `league_id` each year | `_collapse_season_chains` marks predecessors `superseded_by_later_season` using `previous_league_id`, which rides free in the payload already fetched |
| One manager qualifying by two methods | `_QUALIFICATION_PRIORITY` dedup inside `cohort_members` |
| Unresolvable player names | `AssetResolver` has no fuzzy fallback; unmapped assets are counted, never guessed onto a similar name |

Nothing is silently discarded. An excluded roster stays a row with its
reasons attached (`exclusion_reasons_json`), surfaced at
`exclusions.byReason` and in the page's collapsed panel, so "why is the
denominator smaller than the cohort" always has an answer.

## Trends compare like populations

History is stored as **open intervals** (`sharp_roster_asset_spans`),
not daily copies — dynasty turnover is low, so this is a few rows per
holding instead of one row per holding per day.

A holding covers an instant when it had started by then and had not yet
been *contradicted* (`closed_at_ms > as_of`), **not** when the last
confirming observation was after it. The distinction is load-bearing:
rosters are observed periodically, so a roster seen on day 0 and day 40
has no confirmation at day 10 — yet the player was rostered then,
because nothing had said otherwise. Reading the confirming timestamp
instead silently zeroes every drop that happened between two crawls,
which surfaces as a 30-day trend of exactly 0.0 regardless of what
moved. Pinned by
`test_roster_store.py::test_a_holding_persists_until_the_observation_that_contradicts_it`.

Deltas are measured over the **intersection** of the two roster
populations, and withheld entirely below 80% overlap
(`MIN_TREND_POPULATION_OVERLAP`) with `reason:
"roster_population_changed"`. A cohort that grew between the endpoints
must never read as players gaining ownership. "No change" and "not
comparable" render differently.

Rosters not yet observed at the baseline are **absent** from it, not
present-and-empty — present-and-empty would turn every later discovery
into a fake ownership gain.

## Sample-size policy

| Eligible rosters | Behaviour |
|---|---|
| < 8 | Published with an explicit "below the minimum, not ranked as meaningful" banner |
| 8–39 | Published with "Treat this result as directional because of the limited sample size" |
| ≥ 40 | No banner |

Per-row, a player measured against fewer than 5 rosters is flagged
individually (the IDP-in-a-mostly-offense-cohort case) and marked `*`
in the table. Every row publishes its own `sharpRosters` /
`eligibleRosters`, so no percentage appears without its sample.

## Known limitations

These are real and are not worked around.

1. **There is no general-dynasty roster-percentage feed.** Every ranking
   source this platform ingests publishes values or ranks; Sleeper's
   trending endpoint publishes 24-hour *add counts*, a flow rather than
   a stock. So `marketRosterPct` and `sharpRosterAdvantage` are `null`,
   `marketComparison.available` is `false`, and the page says why.
   `set_market_ownership_provider` is the registration seam for a real
   feed; it is deliberately unregistered rather than fed an estimate.
   **The "sharp vs market" sorts exist and work, but rank nothing until
   a provider is registered.**
2. **FFPC contributes zero rosters today.** The parser
   (`FFPCParser._parse_rosters`) is correct and test-pinned, but all ten
   configured seeds in `config/sharp/ffpc_sources.json` are
   `LeagueHome.aspx` pages, which yield transactions and standings — no
   roster table. `collect_ffpc_rosters` lifts
   `platform_memberships.metadata_json["rosterAssets"]` and that column
   is empty for every FFPC row. The FFPC half activates the moment a
   roster-bearing URL is configured; no code change is needed.
3. **FFPC publishes no taxi/IR marking**, so FFPC assets are stored
   `active`. That is the absence of a distinction, not a claim that none
   are on taxi.
4. **Trends need two collection passes.** The span table starts
   accumulating at first crawl, so every trend reports
   `available: false` until a second run exists. This is why the timer
   is daily rather than weekly — a 7-day column cannot resolve finer
   than the observation cadence.
5. **Contending/rebuilding is derived from the current season's W/L**,
   which rides free in the `/rosters` payload. Before four games are
   played it answers `unknown` rather than defaulting a whole preseason
   board into one bucket. It is deliberately *not* the BDVM
   contend/retool/rebuild classifier (`src/bdvm/roster.py`), which needs
   projections and a league config we do not have for arbitrary
   discovered leagues.
6. **League age is a floor, not an exact value** — inherited from
   `league_filter.league_age_seasons`, which reports 2 for any chained
   league because establishing more costs one request per link.
7. **Sleeper league format is fetched per collection run**, not stored
   by discovery. That is the second of the two calls per league. If
   discovery ever captures `roster_positions`, this pass halves its
   cost.

## Auditing

`scripts/validate_sharp_roster_percentage.py` re-derives every published
number from the raw stored rows using code that shares nothing with the
engine, then diffs. Ten checks, one per audit-list item: numerator,
one-observation-per-roster, denominator, arithmetic bounds, duplicate
rosters, duplicate identity attribution, asset mapping, excluded rosters
never reaching a numerator, filters moving both sides, and agreement
with the Buy/Sell Tracker's own payload.

`GET /api/sharp/roster-percentage/audit?assetId=…` lists every roster
behind one player's count, so a published number is checkable without
database access.

## Not a buy signal

A high roster percentage is mostly a restatement of consensus value —
elite players are rostered almost everywhere. Ownership is also shaped
by league depth, format, acquisition cost, age and positional scarcity.
The informative columns are the comparison ones: advantage over the
market (when a feed exists) and the trend. The page carries this caveat
in the UI, not only here.
