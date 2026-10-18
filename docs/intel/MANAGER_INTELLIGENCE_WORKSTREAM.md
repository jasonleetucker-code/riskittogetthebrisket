# Manager Intelligence — Batches B–F workstream (C6-MGR-02)

Owner master implementation addendum, 2026-10-17. It extends Batch A, which shipped as #1762 (`048bcbf8a`).
It sits in the active queue **after** the work already in flight; it does not reorder that work. The
injury/availability fixes (#1772/#1774/#1775), IDP source rehabilitation and the approved Value
Adjustment activation (#1771) keep their positions. Intake: `docs/OWNER_REQUESTED_TODO.md` → "Added
2026-10-17 — Manager Intelligence addendum". Authorization: `docs/EXECUTION_PLAN.md` → "Manager
Intelligence".

The aim: one place where a signed-in user enters a Sleeper username and sees what that manager owns,
what they recently acquired, how they acquired it, what they traded, what they gave up, how those
trades look today, the draft capital they hold, their tendencies, how they compare, and why any of it
matters, with links into the existing trade tools.

## Rules that bind every batch

The rules come from the addendum and from `CLAUDE.md`.

### Reuse only
No second Sleeper pipeline, valuation engine, identity system or package model. Each batch builds on
these existing pieces:

| Concern | Existing owner |
|---|---|
| Sleeper HTTP | `src/public_league/sleeper_client` (classified fetchers) |
| League type | `src/intel/league_filter` |
| League format and slots | `src/sharp/roster_collect` |
| Turning one transaction into asset movements | `src/acquisition/events.py::events_from_transaction` and `events_from_draft_picks` |
| Recorded hand-offs in our own leagues | `src/public_league/ownership` |
| Player values | `roster_percentage.build_player_index` over the live contract |
| Pick values | `src/api/pick_value_resolution.py` (`MarketPickRef` generic / tier / slot) |
| Package-adjusted comparison | `src/valuation_math/package_model` through `src/public_league/trade_grading.grade_trade_sides` (this follows whatever model is active; it never pins KTC or GEOM) |
| Point-in-time grades | `src/api/trade_history_asof.grade_trades_asof` over the canonical temporal ledger |
| Calculator links | `frontend/lib/trade-share.js` |

### Missing is never zero
- No value → `null` plus a reason.
- An unread league or week → an explicit coverage state.
- An undated event stays undated.
- `faab: null` means "not a waiver"; `0` means "a $0 waiver".
- Point-in-time values are shown only when the ledger can resolve every asset strictly before the
  trade. Otherwise the at-time column is "unavailable" with the reason.

### Coverage states
Every league × data-kind reports one of `complete` / `partial` / `none` / `unavailable` /
`rate_limited`.

### Only real evidence
- Never invent a trade, an acquisition date, a current owner or a historical value.
- Pending, rejected and failed transactions are excluded.
- The feed reads only Sleeper transactions with `status == "complete"`, plus completed draft picks.

### Attribution
A transaction belongs to the searched manager when:
1. their roster (as `owner_id` or `co_owners`) is a party to it; and
2. it is not shown to belong to someone else.

What counts as evidence:
- **A recorded hand-off in our own leagues** (`public_league.ownership`) decides.
- **For waiver, free-agent and drop moves,** a `creator` who is neither the owner nor a co-owner of that
  roster today, and not the league commissioner, marks the move `attribution: previous_owner_possible`.
  Such a move is excluded from that manager's acquisitions.
- **For trades,** the counterparty proposing is normal. A trade is flagged `attribution_uncertain` only
  when no party's current owner matches the evidence.

### Bounded, incremental retrieval
- Per-request Sleeper call budget, a small thread pool, and a per-(league, week) memo: a short TTL for
  the current week, a longer one for completed weeks.
- A separate, tighter per-user rate-limit bucket for activity lookups.
- Explicit `truncated` / `budgetExhausted` flags.
- Private, authenticated and read-only.
- No credentials or hidden league data are served.
- Raw Sleeper ids are served only as opaque join keys the private page already receives.

### Design and tests
- Design follows PSI Direction A (`docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md`).
- Every batch ships deterministic, fixture-based tests (no network in CI) plus one read-only probe
  against real Sleeper data. That probe is recorded in the PR and kept separate from the mocked tests.

## Batch B1 — Recent Trades (highest priority)

**Deliverables**
- Completed trades across the manager's in-scope leagues, newest first. Each trade shows:
  - when: date, league, season, week;
  - league format badges;
  - trade partners;
  - for each side: players and picks in and out, plus FAAB sent and received;
  - transaction status;
  - current canonical value of every asset, and incoming / outgoing totals;
  - the package-adjusted comparison under the **active** model, with a `packageModel` receipt;
  - at-the-time and aging figures when the ledger can support them, otherwise "unavailable" with a
    reason;
  - a "Open in Trade Calculator" link.
- Multi-team trades are kept as one trade. Each side is listed; the package adjustment is applied only
  where the active model defines it, and the response says so where it does not.
- Filters: last 7 / 30 / 90 days, this season, an earlier season, league, player or pick acquired,
  player or pick sent.

**Depends on:** Batch A.

**Tests**
- Two-team trade, three-team trade, a trade with picks and FAAB.
- Pending or failed transactions are excluded.
- A co-owned roster.
- Attribution across a hand-off: our own league through `ownership`, and the external-league
  `creator` evidence.
- An unpriced asset gives `null` and a reason.
- An unresolvable at-time value gives "unavailable".
- Calculator link round-trip.
- A rate-limited week makes that league `rate_limited` / `partial`.
- Budget exhaustion is flagged.

**Done when:** a real username shows correct trades in the read-only probe; L1 and L2 are green; the
private gate is enforced.

## Batch B2 — Recently Acquired Players

**Deliverables**
- Every acquisition with its method:
  - trade;
  - waiver, with the FAAB bid;
  - free agent;
  - draft, with round and slot;
  - other (commissioner).
- Only real transaction or draft evidence counts.
- For each acquisition: current value and rank, whether the player is still rostered, current slot
  (starter / bench / taxi / IR), and what was given up (the trade's other side, or the drop paired
  with the add).
- Filters: 7 / 30 / 90 days, this season, a custom range.
- Analytics:
  - most valuable acquisitions;
  - breakdowns by position and by method;
  - adds versus drops;
  - repeat targets (the same player acquired in two or more leagues, or two or more times);
  - rookies and IDP;
  - players later traded away or dropped.
- League-level events plus a player-level summary.

**Depends on:** B1, which uses the same transaction stream.

**Tests**
- Each method.
- A waiver add paired with its drop is one event.
- A draft slot.
- Still-rostered and slot status.
- A player acquired then dropped is "subsequently dropped".
- A repeat target across leagues.
- An undated event stays undated.
- A `creator` mismatch is excluded.

**Done when:** a real username shows correct acquisitions in the probe; tests are green.

## Unified activity feed (ships with B1 and B2)

- One feed covering trades, waiver claims, free-agent adds, drops, draft picks and pick movements.
- An add and its drop inside one transaction are one event.
- Deduplicated by a stable id: `tx:<transaction_id>` or `draft:<draft_id>:<pick_no>`.
- No pending offers.

**Done when:** a dedup test, a mixed-feed ordering test and the probe pass.

## Batch B3 — Draft capital and trade intelligence

**Deliverables**
- Picks held per league:
  - from `traded_picks` folded over default ownership, reusing `picks.traded_picks_observation`;
  - a failed fetch is "unavailable", never "owns no picks".
- Picks valued through `pick_value_resolution`.
- Pick movement history.
- Buy/sell tendencies by position and age, as counts with samples. These are evidence, not labels.

**Depends on:** B1. **Tests:** ownership folds, the unavailable state, pick valuation and its grade.

**As implemented (`src/intel/manager_trade_intel.py`)**
- Served as `draftCapital` and `tendencies` blocks on `GET /api/manager-intel/activity`, not a second
  endpoint, so one request shares one call budget, memo and rate-limit bucket. `/traded_picks` is one
  extra call per league, current season only; coverage reports it as `tradedPicks`.
- Seasons: the canonical `league_draft_years_for` over evidence assembled from this request's own drafts,
  completed-draft picks and rosters (no previous-league hop: no new fetch path). A season whose draft this
  league has already completed is also not held (`draftCompleteSeasons`). This covers startup-only
  leagues, where the canonical lifecycle correctly leaves the class `unknown`. Unknown never drops a season.
- Tendencies leave out uncertain-attribution trades and count them. Ages are current ages, not ages at
  the time of the trade. `TENDENCY_MIN_SAMPLE = 3` and the age buckets are declared PRIORs.

## Batch C — League-wide opponent scouting

**Deliverables**
- For one league, every manager's profile (portfolio, recent activity, draft capital, tendencies),
  bounded by the same budget rules.
- Reuses Manager Scout (`src/intel/manager_scout.py`) for our own registry leagues.

**Depends on:** B1–B3. **Tests:** a league fan-out within budget, partial states.

**As implemented (`src/intel/manager_league.py`)**
- `GET /api/manager-intel/league?leagueId=&window=` — same gates as the other routes (flag, session, guest
  403, validation, no-store) with its own per-user bucket (6 per 10 minutes). Private page
  `/managers/league/[leagueId]`, linked from each league in the /managers Leagues list.
- One league per request, read once through the activity lookup's own machinery (`_read_league_base`,
  `_read_league_activity`, `_league_coverage`, the per-(league, week) memo and a call budget of 80): one
  league + rosters + users + drafts + traded-picks fetch, then every transaction leg and live/complete draft.
- Each roster is folded through the B1/B2 `_Assembler` over a per-roster view of that one read, so the
  attribution rules are unchanged: a possible-previous-owner move is counted apart, and a recorded hand-off
  gives earlier weeks to the outgoing owner.
- Roster value totals are priced-only sums with the unpriced counted. Totals and league ranks (competition
  ranking; unranked is `null`, never last) are published only for a Superflex league with a board loaded,
  otherwise withheld with `canonical_board_is_superflex` / `board_unavailable` (the Batch A posture).
- Registry leagues (resolved through `league_registry`) attach the existing Manager Scout profile per current
  member (`manager_scout.cached_manager_scout`, board gated exactly as `/api/manager-scout` gates it) instead
  of B3 tendencies. Former members appear only as a count; trade sides and creators are not served.

## Batch D — Trade tool integration

**Deliverables**
- From a manager or opponent: open the Trade Calculator, Analyze Trade or Package Builder pre-seeded
  with that roster.
- Everything is valued on the canonical board with the active package model.
- No second valuation.

**Depends on:** B1, C. **Tests:** link and seed round-trips; one model receipt across surfaces.

**As implemented (`frontend/lib/manager-trade-tools.js`, `frontend/app/managers/TradeTools.jsx`)**
- Entry points: every drilldown on `/managers/league/[leagueId]` carries a Trade tools section; each readable
  league in a searched manager's Leagues list links there with `?manager=<user id>`, which opens that
  manager's row on load. One roster source (the Batch C league payload), so no second roster assembly.
- The user picks assets from that roster. Seeds travel only through the tools' existing restore formats:
  `/trade?share=…` (`lib/trade-share.js`, unchanged — side B lists what the scouted manager sends) for the
  Trade Calculator and Analyze Trade (the War Room on `/trade`, which reads once the user adds their side), and
  `/arbitrage?tool=builder&league=&opponent=<owner id>[&target=]` for the Package Builder — the smallest
  restore-from-query in the arbitrage page's own init (`lib/package-builder.js` owns the format; the opponent is
  the permanent owner id, resolved against the loaded league's teams, never a display name).
- No valuation: the backend's board values are displayed; each tool re-values what it receives on the same board.
  The league payload stamps `tradeTools.packageModel` (the ACTIVE receipt) and the seed carries its id as the share
  link's `pm`, so the calculator names any model difference (`describeShareModelChange`).
- Unresolved: a player without a board row name or a board value, or a pick without a board value, is listed with
  its reason and cannot be selected — never seeded, never 0. Roster players now carry `boardName` (backend,
  additive). Unknown pick ownership is stated, never "no picks".
- League scoping: `tradeTools.leagueScoped` is true only for a registry league whose rosters the site has loaded
  (the `GET /api/manager-scout` gate, `manager_scout_api._current_teams`). Only then are Analyze Trade and the
  Package Builder offered and owned picks seeded with their canonical `pick:<leagueKey>:…` ids. Any other league
  (`external_league` / `league_rosters_not_loaded`) offers the generic calculator seed only (picks as generic
  board rows).
- No `/trade` file was changed.

## Batch E — Career, archetypes and comparisons

**Deliverables**
- Multi-season record via the `previous_league_id` chain.
- Archetypes as labelled evidence (for example "acquires rookies"), with samples and thresholds
  declared as a PRIOR, never presented as fact.
- Manager-to-manager comparisons.

**Depends on:** B1–C. **Tests:** chain walk, archetype thresholds, sparse-sample refusal.

**As implemented (`src/intel/manager_career.py`, `src/intel/manager_compare.py`)**
- `GET /api/manager-intel/career?username=&scope=` — same gates (flag, session, guest 403, validation,
  no-store), own per-user bucket (8 per 10 minutes), call budget 360. Each in-scope league is walked by the
  existing `sleeper_client.walk_league_chain_status` (now accepting an optional classified, budgeted league
  fetcher, so a 429 or a refused budget names its cause) up to `MAX_SEASONS_PER_LEAGUE = 6` seasons; a longer
  chain reports `truncated`.
- A season is the manager's only when THAT season's roster names their Sleeper user id (`owner_id` or
  `co_owners`); a season without one is absent (`notHeldSeasons`), never a loss. A roster that could not be read
  is an unread season (`held: null`), not an absent one. Record = the roster's regular-season settings; finish
  from the classified `winners_bracket` read through the public league's bracket helpers
  (`metrics.final_playoff_matchup` / `playoff_placement` / `playoff_teams`): champion / runner-up / playoff /
  missed, `unknown` when the bracket is unread or empty, `in_progress` before the league is `complete`.
  Recorded hand-offs (`public_league.ownership`) mark a season `from_week` / `until_week`; it is shown but left
  out of the totals (the record cannot be split by week).
- Totals count complete, fully-held seasons only, each with `seasonsCovered`: titles (over seasons with a
  decided championship), playoff appearances (over seasons with a known finish), win %, points-for share and a
  points-for index (share × teams; 1.0 = league average). Coverage per league × season plus chain state.
- Archetypes (`evaluate_archetypes`): rookie-focused, consolidator, depth builder, pick hoarder, pick seller,
  active trader, waiver-active, win-now, rebuilding, playoff regular — each a declared rule over existing
  blocks (B3 `tendencies` and `draftCapital.totals`, B2 acquisitions / analytics, the Batch A portfolio
  summary, the career totals), with threshold and minimum sample as named PRIOR constants. States:
  `suggested` / `not_suggested` / `insufficient_sample` / `unavailable`; statements read "Evidence suggests …".
  The activity source is the B1–B3 payload with `window=season` (its per-week memo is shared).
- `GET /api/manager-intel/compare?a=&b=` (and/or `leagueId=`, `window=`) — own, tightest bucket (4 per 10
  minutes). Side by side: each side's portfolio `summary`, season `tendencies` / `analytics` /
  `draftCapital.totals`, career `totals` and `archetypes`, passed through verbatim (the archetypes are
  evaluated over the very payloads shown beside them). A missing side is a 404 naming it. With `leagueId`:
  the manager's team against one league over the Batch C rows (roster value, pick value, picks held,
  trades, transactions, players added), percentile = (below + ½ tied) / (other teams with a value); a team
  matched by its current owner only, a missing value is `null` + the reason.
- Frontend: a Career tab on `/managers` (season table / stacked rows, totals with coverage, archetype chips
  with an evidence drilldown) and the private compare page `/managers/compare?a=&b=&league=`.
- Missing is never zero in the archetypes: a sample that cannot be counted (win-now / rebuilding when the
  paired own-pick sample is below its minimum) reads "not countable", never "0"; unpublished trade-shape
  counts make consolidator / depth builder `unavailable`; waiver adds sum only the methods that were read.
  An unread career is "Not evaluated" in the comparison, never "None".
- `/managers/compare` is in the axe a11y scan (`tests/e2e/specs/a11y-axe.spec.js` static `ROUTES`).

## Batch F — Saved managers, alerts, scoped leaderboards

**Deliverables**
- Saved managers keyed by the permanent Sleeper `user_id`, never the username.
- Alerts on new activity.
- Leaderboards rank only visible populations: the selected league, saved managers or a discovered
  network. Never "all of Sleeper".

**Depends on:** B1–E. **Tests:** rename stability, alert idempotence, population labelling.

## Status

| Batch | Branch / PR | State |
|---|---|---|
| A | #1762 | MERGED (`048bcbf8a`) |
| B1 + B2 + feed | `claude/manager-intel-b` | IMPLEMENTED — PR open; read-only live probe recorded in the PR (jnesselhauf, Aguilar315) |
| B3 | `claude/manager-intel-b3` (stacked on `claude/manager-intel-b`) | IMPLEMENTED — PR pending; read-only live probe (jnesselhauf, Aguilar315) recorded for the PR |
| C | `claude/manager-intel-c` (stacked on `claude/manager-intel-b3`) | IMPLEMENTED — PR pending; read-only live probe (dynasty_main 1312006700437352448, Championship Alleys) recorded for the PR |
| D | `claude/manager-intel-d` | IMPLEMENTED — PR #1797 (link and seed round-trips, model receipt, unresolved handling and the league gate covered by vitest + pytest) |
| E | `claude/manager-intel-e` (on `main`; B1–C merged via release train 5) | IMPLEMENTED — PR #1796 open, not merged; read-only live probe 2026-10-18 (jnesselhauf career 72/360 calls, 26 seasons / 14 counted, one chain truncated at the 6-season bound; compare vs Aguilar315; dynasty_main league percentile) recorded in the PR |
| F | `claude/manager-intel-f` | IMPLEMENTED — PR #1801 (stacked on E) |
