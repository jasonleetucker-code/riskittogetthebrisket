# `/rosters` consumes canonical Team Strength

**Unit:** frontend consumer repair (Lane 6). **Scope:** one page, one
duplicate quantity retired.
**Not in scope:** any backend methodology, any new valuation, the Premium
Sports Intelligence route migration, trade capacity / VA, Sharp, FAAB.

---

## 1 · The defect

`/rosters` is titled **Team Strength**. It answered that question twice,
in two different ways, on one screen:

| surface | quantity | where it came from |
|---|---|---|
| power table `#` | portfolio value under the current asset scope + position filter | `buildAllTeamSummaries`, sorted on `activeTotal` — a client-side sum |
| tier card `#rank` | `0.7 × starterValue + 0.2 × depthValue − 0.1 × pickValue`, cut into contender / mid-tier / rebuilder thirds | `lib/league-analysis.js::scoreTeamTiers` — a client-side **formula** |

The second one is a Team Strength methodology living in the browser.
CLAUDE.md forbids it in as many words — *"There is no frontend ranking
engine, period — not even a fallback"* — and `V1-35` is the owner
decision that the named team quantities *"may not collapse into one team
score"*. Two ranks of the same twelve teams, four hundred pixels apart,
is the visible half of the same defect;
`docs/master-site-audit/PRIOR_AUDIT_RECONCILIATION.md:408` measured them
disagreeing for **10 of 12 teams**.

## 2 · The canonical owner

`src/roster_intel/strength.py` (feature-inventory row 1.1), reached
through `src/api/roster_intelligence.py` and served by
`GET /api/roster/intelligence`. It aggregates canonical values over the
canonical meaningful core; it computes no value of its own.

Consumed fields, all read verbatim:

```
team.strength.total                  THE Team Strength number (meaningful core)
team.strength.starterValue           the split inside that core …
team.strength.reserveValue           … published as diagnostics, not as a second strength
team.strength.byPosition[]           value / counts / leagueRank per group
team.strength.positionOrder          the backend's own display order
team.strength.leagueRank             1 = strongest; null = NOT MEASURED
team.strength.leaguePercentile
team.strength.unpricedCount          players with no canonical value
team.strength.unfilledStarterSlots   slots the core could not fill
team.strength.unfilledReserveSlots
team.strength.isComplete
team.strength.available              false ⇒ the lineup could not be read
team.strength.unavailableReason
team.strength.fullRosterValue        portfolio, named separately (see §6)
leagueContext[]                      ownerId / teamName / strengthTotal / strengthRank
```

Measured on the tracked export archive (`dynasty_data_2026-08-19.json`,
12 teams): totals **55,520 – 146,487**, all twelve ranked, the sampled
team at **79,994** — rank 9 of 12, `unpricedCount 12`,
`unfilledStarterSlots ["K"]`, `isComplete false`.

## 3 · What changed

* **`scoreTeamTiers` is deleted**, not deprecated — an unused export is a
  working second engine one import away. Its eight regression pins go
  with it (they pinned the coefficients).
* **The tier card is gone**, replaced by `components/TeamStrengthCard.jsx`,
  which renders the canonical block and the canonical league ladder.
* **The portfolio table keeps its job and loses its rank.** It is now
  headed *"Roster value portfolio"*, its total column reads *"Portfolio
  value"*, and the `#` ordinal column is **removed** — the order is a
  sort of the column the user chose, and a note says so. There is now
  exactly one `#` on the page and it is `strength.leagueRank`.
* **`lib/roster-intelligence.js`** is the materializer: classify, reshape,
  format. It sums nothing.
* **`components/useJsonEndpoint.js`** is the fetch machinery, extracted
  verbatim from `useBdvmEndpoint` (now a two-line wrapper over it) so the
  two surfaces cannot drift on league threading or abort handling.

## 4 · Distinct quantities deliberately preserved

`V1-35` does **not** say every team metric becomes Team Strength. These
stay separate, separately named, and untouched by this unit:

| quantity | where it lives now |
|---|---|
| dynasty roster **portfolio** value | the /rosters portfolio table (relabelled, kept) |
| **Team Strength** (meaningful core) | the new canonical card |
| starter / reserve split | facets inside the card, labelled as such |
| age & value portfolio / Young Core | `agePortfolio` — untouched, still rendered by the age-curve overlay |
| ROS value / production | `src/ros/` — different lane, untouched |
| playoff / championship odds | untouched |
| terminal portfolio totals | untouched |
| League Edge Map, waiver gems, trade targets | untouched |

## 5 · Failure semantics — no fallback, ever

Seven states render distinctly and **none of them falls back to a
locally computed score**: `auth`, `team_required`, `team_not_found`,
`not_ready`, `league`, `unavailable`, `error`, plus loading and
"neither team nor league returned".

Three absences are carried as absences:

* `available: false` → the backend's reason, and the sentence *"this is
  not a strength of zero"*.
* `leagueRank: null` → **Not measured**, in the position the server put
  it. `rank_team_strengths` excludes unreadable rosters from the ranking
  population rather than ranking them last, and the ladder preserves
  `_league_context_order` rather than re-sorting (a `?? 0` comparator
  reads an absent rank as the best possible one).
* `unpricedCount` / `unfilledStarterSlots` → prose saying the total is a
  statement about the part we could read.

## 6 · API handoff — precise, for Claude 1 / Integration

Nothing here blocked this unit; all three are things the frontend
declines to invent.

1. **`strength.fullRosterValue` is `null` on every live response.**
   `build_team_strength` accepts `full_roster_values=` and
   `build_league_roster_intelligence` does not pass it — while it already
   builds exactly that list two lines below for `build_age_portfolio`
   (`[(pl.player_id, float(pl.ros_value)) for pl in pools[oid] if
   pl.ros_value is not None]`). The module docstring says the portfolio is
   published *"beside `total` so the two can never be read as the same
   number"*; today only one of the two exists. **The card renders the
   facet only when the number is present** rather than printing a
   permanent em-dash. Owner-side one-liner; not a frontend workaround.

2. **No league-wide competitive window.** The contender / rebuilder
   *classification* has a canonical owner — `src/roster_intel/window.py`,
   `COMPETITIVE_STATES` — but it is published **per team** by
   `/api/gameplan` (`src/api/gameplan.py:782`) and not at all by
   `/api/roster/intelligence`. A league-wide tier card therefore cannot be
   rendered from canonical output today, and this unit **did not
   recreate one**. If the product wants the tier labels back, the ask is
   `competitiveWindow` on each `leagueContext[]` entry (or on each team).
   Note it is also currently rendered by **no** frontend surface at all.

3. **`leagueContext[]` cannot explain an unranked team.** It carries
   `strengthRank: null` but no `available` / `unavailableReason`, so the
   ladder can say *"not measured"* for another team but not *why*. Two
   additive fields would close it. Low priority — zero of twelve teams
   are unranked on the live board.

## 7 · Verification

* Structural guard `frontend/__tests__/no-frontend-team-strength-methodology.test.js`
  — RED at `origin/main` (4 of 6 failing), green after.
* `roster-intelligence-lib.test.js` (25) + `team-strength-card.test.jsx` (21),
  both against a fixture **generated by the real backend** over the
  tracked export archive rather than hand-written.
* Five mutations, each turning the guard that names it red — see the PR
  body for the table.
* Full frontend suite 2,108 passed; `next build` clean;
  `/rosters` bundle 25.0 → 34.6 KB, budget re-pinned 30 → 40 with the
  reason recorded in the script.

## 8 · Not claimed

Not production-verified. The end-to-end checks ran against a locally
served build reading the tracked export archive — production-equivalent,
not production. **`V1-35` is not marked verified by this unit**; that is
Integration's call, and the UI half is only one of its halves.
