# Historical Gap Audit (League Page)

## Scope
Audit current league-history data realism for the public League Page.  
Goal: identify what is truly present vs missing, and what requires backfill vs manual commissioner entry.

## Evidence basis
- Authoritative runtime payload: `data/dynasty_data_2026-03-12.json`.
- Live ingestion path: `Dynasty Scraper.py` (`fetch_sleeper_rosters` and payload assembly).
- Runtime publication path: `server.py` (`/api/data`).
- Supporting artifact: `data/scoring_history_player_week.csv`.

## Authority boundary
- `complete`: `sleeper` block published via runtime payload for current league state + rolling trade window.
- `partial`: historical slices exist but are limited to current output window or non-league-specific sources.
- `missing`: no authoritative runtime path currently publishes this domain.
- Non-authoritative scaffold artifacts in `data/league/league_snapshot_*.json` are diagnostics only, not League Page truth.

## Domain gap inventory
| Data domain | Status | Evidence now | Gap and impact | Recommended path |
| --- | --- | --- | --- | --- |
| Seasons | partial | Trade timestamps expose 2025-2026; `empiricalLAM.seasons=[2025]` | No canonical season index with league outcomes | Derive short-term, backfill canonical season registry |
| Standings by year | missing | No standings array in runtime `sleeper` payload | Blocks true all-time standings/records pages | Backfill from Sleeper season pulls |
| Matchups by year | missing | No matchup data in runtime payload | Blocks recaps, rivalry chronology, weekly timeline truth | Backfill from Sleeper matchup pulls |
| Weekly team scores | missing | No team-week score table in payload | Blocks scoring records and media recap automation | Backfill from matchup/weekly pulls |
| Weekly player scores | partial | `data/scoring_history_player_week.csv` exists (2025 only) | Not tied to league ownership by week; insufficient for official awards attribution | Backfill league-specific player-week + ownership linkage |
| Roster history by week | missing | Runtime stores current rosters only (`teams[].players/playerIds`) | Blocks retrospective awards attribution and many franchise-history claims | High-effort transaction reconstruction (later phase) |
| Current roster data | complete | `sleeper.teams[]` includes names/roster IDs/players/playerIds | Usable now | Use as-is |
| Trade history | partial | `sleeper.trades` exists; `tradeWindowDays=365`; currently 131 trades, years 2025-2026 | Not all-time; bounded by rolling window | Use recent now, add historical backfill |
| Trade asset details | complete | Each side has `got`/`gave`, player/pick labels | Usable for recent trade pages | Use as-is |
| Rookie draft history | missing | No rookie draft results archive in runtime payload | Blocks historical draft page | Backfill from Sleeper draft endpoints |
| Pick ownership history | partial | `teams[].pickDetails` present for future picks (2026-2028 observed) | Not a historical ownership timeline | Use current/future board now, backfill historical ownership later |
| Payouts / winnings history | missing | No dues/payout ledger fields in runtime | Blocks automated money leaderboards/ROI | Manual commissioner ledger |
| League messages / chat message counts | missing | No message/chat ingestion in scraper/runtime payload | Blocks chat-derived culture metrics | Not realistic now without new ingestion system |
| Transactions / waivers / FAAB | partial | Sleeper transaction fetch currently filters to `trade` + `complete`; KTC waivers are external crowd data, not league-specific | League waiver/FAAB history not presently authoritative | Expand Sleeper transaction ingestion to waiver/add/drop types |
| Constitution text / rules text | missing | No constitution/rules store in runtime | Blocks constitution tab beyond placeholder | Manual commissioner content store |
| Franchise name history | partial | Current team names exist; some names also appear in recent trade sides | No canonical rename timeline | Derive limited history + manual correction |
| Franchise logo history | missing | No historical logo/avatar archive published | Blocks trustworthy branding timeline | Manual-first + API feasibility check |

## Critical blockers for truthful public claims
- Full all-time standings, records, and history chronology.
- Formula awards requiring player-week scoring plus week-level ownership attribution.
- Historical draft outcomes and pick-chain history.
- Automated money metrics without a commissioner ledger.

## Backfill feasibility tiers
| Tier | Domains | Practicality |
| --- | --- | --- |
| Backfillable (high confidence) | standings, matchups, weekly team scores, draft history, richer transactions | Feasible with dedicated Sleeper historical ingestion jobs |
| Backfillable (medium/high effort) | week-level roster ownership timeline, robust pick ownership lineage | Possible but reconstruction-heavy; not Phase 1 practical |
| Manual-first required | payouts/dues/winnings, constitution text, amendment logs, franchise rename/logo history | Commissioner curation required for trustworthy history |
| Not realistic right now | chat/message counts and chat-based historical analytics | Requires net-new integrations beyond current system |

## Phase-1 truth constraints
- Publish only what is currently defensible:
  - current rosters and team identity snapshot,
  - future pick board,
  - clearly labeled recent trade feed (rolling window),
  - commissioner-managed manual modules (money/constitution/media).
- Do not present incomplete historical reconstruction as canonical fact.
