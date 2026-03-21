# League Page Data Availability Matrix

## Evidence basis
- Authoritative runtime payload inspected: `data/dynasty_data_2026-03-12.json`.
- Live ingestion path inspected: `Dynasty Scraper.py` + `src/api/data_contract.py` + `server.py`.
- Supporting artifact checked: `data/scoring_history_player_week.csv`.

## Domain-level audit

Legend:
- `available`: present and usable from current authoritative system.
- `partial`: some relevant data exists but not enough for full feature truth.
- `missing`: no authoritative data path currently present.

| Data domain | Exists now | Evidence in current system | Recommended path | Phase 1 suitability |
| --- | --- | --- | --- | --- |
| Seasons | partial | Trade timestamps show 2025-2026; `empiricalLAM.seasons=[2025]`; no canonical season table | Derive limited now, backfill full season index later | limited |
| Standings by year | missing | No standings fields in `sleeper.teams[]` payload shape | Backfill from league rosters/settings history pull | no |
| Matchups by year | missing | No matchup arrays in runtime payload | Backfill from Sleeper matchup pulls by week/season | no |
| Weekly team scores | missing | Not in runtime payload | Backfill from matchup pulls | no |
| Weekly player scores | partial | `data/scoring_history_player_week.csv` exists (season 2025 only) but is not league-ownership aware | Backfill league-specific weekly player outcomes + ownership linkage | no for official awards |
| Roster history by week | missing | Only current rosters are stored; no week-by-week ownership timeline | Backfill via high-effort transaction reconstruction | not realistic in Phase 1 |
| Current roster data | available | `sleeper.teams[].players/playerIds` | Use as-is | yes |
| Trade history | partial | `sleeper.trades` exists, rolling window (`tradeWindowDays=365`), two league ids observed | Use as-is for recent; backfill for full history | yes (recent-only) |
| Trade asset details | available | Each trade side includes `got`/`gave` arrays with player/pick labels | Use as-is | yes |
| Rookie draft history | missing | No historical draft-pick result store in runtime payload | Backfill from draft endpoints/pulls | no |
| Pick ownership history | partial | `teams[].pickDetails` currently contains future pick holdings (2026-2028 observed), not full historical trail | Use as-is for current board; backfill for history | yes (future board only) |
| Payouts / winnings history | missing | No dues/payout ledger in runtime payload | Manual commissioner entry | yes (manual-first) |
| League messages / chat counts | missing | No chat/message ingestion path found in code or payload | Not realistically supported right now without new ingestion R&D | no |
| Transactions / waivers / FAAB | partial | League transactions endpoint used but filtered to completed trades; KTC waivers exist but are external crowd data, not league-specific | Backfill by expanding league transaction ingestion types | limited |
| Constitution text / rules text | missing | No constitution store in current runtime payload | Manual commissioner entry | yes (manual-first) |
| Franchise name history | partial | Current team names exist; trade-side team names appear in recent trade records | Derive limited history + manual correction | limited |
| Franchise logo history | missing | No logo/avatar fields stored in runtime payload | Manual-first; API feasibility unverified in current system | limited |

## Feature-area matrix (public League Page nav)

| Feature area | Data readiness | Can ship in Phase 1? | Truthful Phase 1 scope | Blocked until later |
| --- | --- | --- | --- | --- |
| Home | ready | yes | League identity + freshness/status + scoped summaries | deep historical totals |
| Standings | partial | conditional | Current standings only if ingested; else explicit provisional state | season-by-season standings history |
| Franchises | partial-ready | yes | Current rosters, future picks, recent trade activity | full historical franchise timelines |
| Awards | missing-critical | no (methodology only) | Publish methodology and data-gate criteria | official formula awards outputs |
| Draft | partial-ready | yes | Future pick board and pick ownership snapshot | rookie draft history/results |
| Trades | partial-ready | yes | Recent trade feed with explicit time-window label | full all-time trade archive |
| Records | missing-critical | no (manual subset optional) | Optional manual headline records only | computed historical records |
| Money | missing-runtime/manual path | yes (manual-first) | Manual ledger metrics (winnings/dues/net/ROI) | automated historical money pipeline |
| Constitution | missing-runtime/manual path | yes (manual-first) | Rules text + amendment log from manual store | full admin CMS |
| History | missing-critical | no (placeholder only) | Explicitly scoped placeholder | complete league history timeline |
| League Media | missing-runtime/manual path | yes (manual-first) | Manual posts + archive + commissioner notes | automated preview/review generation |

## Classification summary
- Use as-is now: current rosters, trade asset details, limited recent trade feed, future pick board snapshot.
- Derivable now (limited): recent season coverage, partial franchise naming context.
- Backfillable from pulls (non-trivial): standings history, matchups, weekly team/player outcomes, rookie draft history, richer transaction history.
- Manual commissioner entry required: money ledger, constitution/rules, media archive, seeded championship/playoff history.
- Not realistically supported right now: trusted chat/message counts and robust week-level roster ownership history in Phase 1.
