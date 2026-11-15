# SleeperStalker — functional benchmark audit (Manager Intelligence)

**Status:** reference record for the Manager Intelligence directive (owner master prompt 2026-10-16;
intake in `docs/OWNER_REQUESTED_TODO.md`, "Manager Intelligence"). **No product authority.**

## Ground rules (binding, from the directive)

- SleeperStalker is a **functional benchmark only**. No code, copy, branding, layout, icons or
  other interface assets are copied, and nothing behind its login or paywall is accessed.
- Our implementation is native: it composes this repository's canonical owners (Sleeper client,
  league filter, identity, canonical values, trade engines) and follows PSI Direction A.

## What was observable (2026-10-17)

| Source | Result |
|---|---|
| `https://www.sleeperstalker.com/` | HTTP 503 at fetch time |
| `https://sleeperstalker.com/` | Client-rendered app; the server-delivered page contains only the title "Sleeper Stalker — Find Your Sleeper Fantasy Football Leaguemates". No feature text, pricing or navigation is present without executing the app. |

Because the public HTML carries no feature description, **this audit does not enumerate
SleeperStalker features from its site**. The feature list we build against is the owner's own
description in the master prompt (the intake section names it), not anything scraped or inferred.

## Benchmark capabilities (from the owner's prompt) → our batches

| Capability | Our batch | Canonical owner we reuse |
|---|---|---|
| Search any Sleeper username; list their leagues by type | A (this PR) | `sleeper_client` classified fetchers; `intel/league_filter` |
| Cross-league player ownership, exposure, portfolio value | A | `sharp/roster_collect` slot rule + format; `sharp/roster_percentage.build_player_index` (canonical `rankDerivedValue`) |
| Draft capital across leagues | B | `identity/picks` + `api/pick_value_resolution` |
| Trade history and buy/sell tendencies | B | `intel/manager_scout`, acquisition ledger |
| League-wide opponent scouting | C | Manager Scout + roster intelligence |
| Send-to-trade-calculator / trade-tool integration | D | `/trade` canonical engines |
| Career record, archetypes, comparisons | E | public-league history owners |
| Saved managers, alerts, leaderboards | F | signal-alerts sweep; populations limited to what we can see |

## Where we deliberately differ

- **Missing is never zero:** a player the canonical board does not price shows "—"; value totals
  are published only over Superflex leagues (the board's format).
- **Exposure names its denominator:** an IDP player is measured against IDP leagues, a kicker
  against leagues with a K slot.
- **Scopes never mix:** dynasty, keeper and redraft leagues are separate views.
- **Partial answers are labelled:** an unreadable league is listed, never silently dropped.
- **Private:** signed-in users only, rate-limited; the site is non-commercial (owner, 2026-10-17).
