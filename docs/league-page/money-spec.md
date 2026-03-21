# League Page Money Spec

## Scope
Public League Page `Money` section only.

This is a planning/spec document. No UI implementation is included.

## Repo-grounded facts (current state)
- Live runtime payload is published by `server.py` via `/api/data`, backed by `Dynasty Scraper.py` and `src/api/data_contract.py`.
- Sleeper data currently persisted in the runtime payload includes league teams and trades, plus league/scoring settings.
- Sleeper data currently does **not** include playoff outcomes, championship history, weekly matchup history, dues, payouts, or commissioner-entered money ledger fields in the live payload.
- Blueprint notes explicitly call out a future commissioner-managed payouts ledger as missing (`docs/BLUEPRINT_EXECUTION.md`).

## Canonical money methodology

### Required entities
- `franchise_registry`: stable franchise identity across seasons (do not key by Sleeper `roster_id` alone).
- `money_ledger`: one row per franchise per season with dues, payouts, penalties, refunds, notes.
- `season_outcomes`: one row per franchise per season with playoff appearance and championship outcome.

### Metric formulas
- `all_time_winnings`: sum of `payout_total` across all seasons for each franchise.
- `dues_paid_total`: sum of `dues_paid` across all seasons for each franchise.
- `net_profit_loss`: `all_time_winnings - dues_paid_total - penalties_total + refunds_total`.
- `roi`: if `dues_paid_total > 0`, `net_profit_loss / dues_paid_total`; else `null`.
- `dollars_won_per_playoff_appearance`: if `playoff_appearances > 0`, `all_time_winnings / playoff_appearances`; else `null`.
- `dollars_won_per_championship`: if `championships > 0`, `all_time_winnings / championships`; else `null`.

### Tie-break rules
- For leaderboards sorted descending by value:
- Tie-break 1: more championships.
- Tie-break 2: more playoff appearances.
- Tie-break 3: alphabetical franchise display name.

## Feasibility by requested item

| Item | Feasibility | Why |
| --- | --- | --- |
| All-time winnings leaderboard | Requires manual historical entry | No payouts ledger exists in live payload or data store. |
| Dues paid | Requires manual historical entry | No dues field exists in Sleeper payload ingestion or repo data schema. |
| Net profit/loss | Partially feasible | Formula is straightforward once manual dues/payout ledger exists; source data missing today. |
| ROI | Partially feasible | Derivable from net and dues; both currently require manual ledger data. |
| Dollars won per playoff appearance | Requires manual historical entry | No playoff appearance history is currently ingested into runtime payload. |
| Dollars won per championship | Requires manual historical entry | No championship history is currently ingested into runtime payload. |

## Recommended storage (fits current repo architecture)
- `data/league/manual/franchise_registry.csv`
- `data/league/manual/money_ledger.csv`
- `data/league/manual/season_outcomes.csv`
- `data/league/manual/README.md` (field definitions + edit policy)

CSV-first is aligned with the current repo pattern (JSON/CSV artifacts, no live DB authority).

## Data quality controls
- Enforce one money ledger row per `franchise_id + season`.
- Enforce one season outcomes row per `franchise_id + season`.
- Validate `dues_paid >= 0` and payout fields numeric.
- Preserve an immutable audit column set: `entered_by`, `entered_at_utc`, `source_note`.
- Keep adjustment rows explicit (never overwrite prior values silently).

## Public-safe output contract for Money tab
- Expose only aggregated money metrics and season ledger lines intended for public display.
- Do not expose private trade-calculator internals, valuation diagnostics, or private account/session fields.

