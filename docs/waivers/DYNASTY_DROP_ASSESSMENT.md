# Dynasty drop assessment — may weekly streaming release this player?

Owner: `src/waivers/drop_assessment.py`. Parameters:
`config/waivers/streaming_protection.json` (every value a labelled **PRIOR**; a
missing or malformed file **refuses** — there is no code default). Tests:
`tests/waivers/test_drop_assessment.py`.

For every player on one team's roster this answers: may the streaming optimizer
release him, and at what stated dynasty cost? It is a **classifier over inputs
other owners compute**. It derives no value, replacement level, lineup or
protection of its own, and it never writes `rankDerivedValue`.

## 1. Contract (what the streaming solver consumes)

`assess_team_drops(contract, *, league_key, owner_id=None, roster_id=None,
team_name=None, constraints=None, weekly_starter_ids=None, config_path=None,
now=None, player_context_snapshot=<disk>, draft_rows=<cache>, history_path=None,
injury_status=None, unavailable_keys=None) -> TeamDropAssessment`

* Raises `TeamNotInLeague` (unknown team), `DropAssessmentConfigError` (PRIORs
  unreadable), `ValueError("league_mismatch…")` (contract `meta.leagueKey`
  differs from `league_key`).
* `constraints` is a resolved `src.trade.constraints.TradeConstraints`. A
  `resolution_failed` set protects **every** player. `None` is stamped
  `summary.locksState = "not_supplied"` — a route must pass the user's resolved
  constraints.
* `weekly_starter_ids` — Sleeper ids the caller's weekly lineup starts.

`TeamDropAssessment.to_dict()`: `contractVersion`, `leagueKey`, `team`
(`ownerId`/`rosterId`/`teamName`), `asOf`, `configVersion`, `configHash`
(sha256 of the config bytes), `replacementValues` (per position),
`waiverPopulation`, `summary` (`counts` per class, `unpriced`, `locked`,
`locksState`, `weeklyRoleState`, `usageSnapshot`, `temporalLedger`,
`draftCapitalSource`, `inputCoverage`), `assessments`, `notes`.
`TeamDropAssessment.by_player_id()` indexes the frozen assessments.

`DynastyDropAssessment.to_dict()`:

| field | meaning |
|---|---|
| `playerId`, `name`, `position` | position is the family DL/LB/DB/QB/RB/WR/TE/K (`""` unknown) |
| `dropClass` | `protected` / `conditional` / `churn` |
| `dynastyValue` | `rankDerivedValue`; `null` when unpriced |
| `replacementValue` | waiver level at his position (best equivalent free agent) |
| `valueAboveReplacement` | signed `dynastyValue − replacementValue`; `null` if either is |
| `dynastyCost` | `max(0, valueAboveReplacement)` via `displacement.effective_cut_cost` (scarcity inert); full `dynastyValue` when replacement is unknown; `null` when unpriced |
| `confidence` | `confidenceBucket` |
| `reasons` | `[{code, detail, evidence}]`, deciding reason first |
| `inputs` | every input, each `{state, value, …}` with `state` ∈ `available` / `unavailable` / `stale` / `not_supplied` |
| `locks` | `[{reason, source}]` — user protection |
| `developmentFlags` | see §3 |
| `rosterRole` | `weekly_starter` / `bench` (caller-supplied) or `unknown` |
| `recoveryRisk` | always `{state: "unmeasured", reason}` — see §5 |

### Why `dynastyCost` is value above replacement, and the two rules that follow

Releasing a player who is at or below the best free agent at his position loses
nothing the wire cannot give back today; charging his full board value would
make every deep-bench release look expensive and push the solver off moves that
cost no dynasty value. So the cost is the canonical cut-cost owner's
`max(0, V − W)`. `dynastyValue` is kept beside it for a conservative budget.

1. **The replacement is ONE player.** Every churn/conditional player at a
   position is measured against the same best free agent. Two releases at one
   position cannot both be charged against him — the second release's true
   replacement is the second-best free agent.
2. **No double credit.** The cost is already net of a replacement, so the solver
   must not also credit the added streamer's dynasty value against it (the same
   trap Perfect Draft's ladder documents).

## 2. Inputs (consumed, never re-derived)

| input | owner / source | when missing |
|---|---|---|
| value, confidence, quarantine | contract row: `rankDerivedValue`, `confidenceBucket`, `retainedAuthority`, `quarantined` | unpriced → protected |
| replacement level | `src/roster_intel/droppability.py::team_droppability` → `waiverValues` | `replacement_level_unavailable` → conditional at full value |
| roster join | `src/draft/context.py::build_roster_assets` (the ladder's own join) | unjoined → unpriced → protected |
| user locks | `src/trade/constraints.py::TradeConstraints.block_reason` | `not_supplied` stamped |
| age, years of experience | contract row `age`, `yearsExp` | `age_unknown` blocks churn |
| snap share / trend / depth | playerctx snapshot (`src/playerctx/service.py::load_playerctx`), joined by `sleeperIndex` | `unavailable` (absent is never zero usage); older than `usageSnapshotMaxAgeDays` → `stale`, not used |
| draft capital | cached nflverse id map (`src/nfl_data/ingest.fetch_id_map(cache_only=True)`); score `src/bdvm/context.py::draft_capital_score` | `unavailable` |
| value trend (30 / 60 d) | `src/history/asof.py::value_as_of` (`player:<id>`, canonical lane, `max_age_days` bounded) | `unavailable`; never a future observation |
| weekly role | caller | `not_supplied`, `rosterRole: unknown` |
| injury | caller (`injury_status`) — reported only | `not_supplied` |
| lineup required alone | cut ladder `undroppable` — reported only | — |

**Draft-capital identity.** The id map is joined exactly through the playerctx
record's GSIS id. Without it the name-keyed `build_player_context` is used
behind an identity guard (position family and career length must agree; a
cross-family IDP listing — Sleeper DL vs nflverse LB — is accepted only when the
career length agrees). Measured on the 2026-10-29 board, the name map alone
returns a cornerback for one star wide receiver and a linebacker for another;
the guard refuses both. 640 of 694 rostered players joined by GSIS, 45 by
guarded name, 9 unavailable.

**Not used.** `src/nfl_data/usage_windows.py`, `depth_charts.py` and
`injury_feed.py` have no persisted artifact or reader (the same finding
`src/consensus_edge/opportunity.py` records); the persisted usage/depth signal
is the playerctx snapshot. Injury is reported, not classified: long-term injury
is already in the canonical value, and weekly availability is the caller's
lineup input.

## 3. Rules (strict priority order)

1. **User lock** → `protected` (`user_lock`). Absolute: evaluated before value.
2. **Unpriced** (no `rankDerivedValue`, or not on the board) → `protected`
   (`unpriced_never_auto_drop`). An unknown value is never cheap.
3. **Quarantined value** → `protected` (`value_quarantined_never_auto_drop`).
4. **No replacement level at his position** → `conditional`
   (`replacement_level_unavailable`), charged full board value.
5. **gap ≥ `protectGapMin`** → `protected` (`meaningful_dynasty_asset`).
6. **A protecting development flag** → `protected` (`development_upside`) —
   unless gap ≤ `clearlyBelowGapMax` AND an OBSERVED snap record shows no usage,
   then `conditional` (`development_flag_overridden_no_usage`).
7. Otherwise `churn` only if gap ≤ `churnGapMaxByConfidence[confidence]`, no
   churn-blocking flag, and not a caller-supplied weekly starter; else
   `conditional` (`confidence_not_churn_eligible` / `above_replacement_band` /
   `churn_blocked_by_signal` / `weekly_starter`).

`gap = (V − W) / mean(V, W)` — the board's symmetric-mean convention
(`marketGapValueRatio`, confidence `AGREEMENT_VALUE_RATIO`).

Development flags (which protect and which only block churn is config):

| flag | condition | role |
|---|---|---|
| `young_rising_usage` | age ≤ `youngAgeMax`, ≥ `minGamesForTrend` games, snap trend ≥ `risingSnapTrendMinPts` | protects |
| `young_established_usage` | age ≤ `youngAgeMax`, season snap share ≥ `establishedSnapPctMin` | protects |
| `high_draft_capital_recent` | yearsExp ≤ `recentDraftMaxYearsExp`, overall pick ≤ `highDraftCapitalMaxOverall` | protects |
| `value_trending_up` | 30-day value change ≥ `valueTrendUpMinRatio` | blocks churn only (momentum is not evidence of value) |
| `young_usage_unknown` | young, usage unavailable or stale | blocks churn |
| `recent_draft_capital_unknown` | recent draftee, draft capital unavailable | blocks churn |
| `age_unknown` | no age | blocks churn |

Age alone grants nothing, and age alone condemns nothing: a young player with no
usage and no draft capital can be churn; a veteran is churn only when the board
values him at replacement.

## 4. PRIORs

| entry | value | rationale (abridged — full text in the config) |
|---|---|---|
| `churnGapMaxByConfidence` | high 0.15, medium 0.15, low 0.0 | the board's agreement band; low confidence must be at or below replacement; any other bucket never churn |
| `protectGapMin` | 0.40 | ≈ 1.5× the best free agent, well outside the band |
| `clearlyBelowGapMax` | −0.40 | mirror; only lifts a development flag when usage is observed as none |
| `youngAgeMax` | 24 | |
| `risingSnapTrendMinPts` | 5.0 | a third of consensus_edge's 15-pt saturation |
| `minGamesForTrend` | 3 | playerctx recent window is 3 games |
| `establishedSnapPctMin` | 60 | |
| `noUsageSnapPctMax` | 10 | season AND recent |
| `highDraftCapitalMaxOverall` | 64 | rounds 1-2 |
| `recentDraftMaxYearsExp` | 2 | |
| `valueTrendWindowDays` | 30 | |
| `valueTrendUpMinRatio` | 0.15 | |
| `trendMaxObservationAgeDays` | 7 | |
| `usageSnapshotMaxAgeDays` | 10 | weekly refresh + one miss |

None is calibrated. Changing one is an owner-visible methodology change.

## 5. Limits, stated

* **`recoveryRisk` is unmeasured.** No owner measures how often a released player
  is claimed by a rival in this league (`src/trade/faab_history.py` records
  bids, not post-release claims). No probability is invented.
* **Replacement is one free agent** (§1). Multi-release cost at one position is
  understated if the solver ignores it.
* **The waiver population** is `team_droppability`'s default (contract
  auction-rookie keys excluded, 144 keys on 2026-10-29). In-season those keys
  include undrafted 2026 rookies who are signable, so the level is, if anything,
  LOW — which makes releases look more expensive (the protective direction).
* **Kickers are unpriced on this board** (21 of 21 rostered K), so every
  kicker is `protected`; K streaming needs an owner decision, not a guessed
  value.
* **IDP values are compressed** against their replacement levels: on
  2026-10-29 an elite edge rusher sits at gap ≈ 0.28–0.33 and is `conditional`
  (cost ≈ 680–810), not `protected`. That is the board's view; the user's
  dynasty-loss budget decides.
* A low ranking alone does not prove low upside — hence the development flags —
  but the flags only see snaps, draft capital and value trend. Route
  participation, target share and coaching signals do not exist in this repo.
* Locally, the temporal ledger is absent, so `valueTrend*` is `unavailable` for
  every player in the evidence below; production has the ledger.

## 6. Evidence — `dynasty_main`, live contract 2026-10-29

Contract built from `exports/latest/dynasty_data_2026-10-29.json`; playerctx
snaps from the retained 2026-10-27 snapshot (no depth block in the retained
projection); nflverse id map from the cache; no constraints, no weekly lineup,
no ledger. Teams by their index in `sleeper.teams`.

| team | roster | protected | conditional | churn | unpriced |
|---|---|---|---|---|---|
| T00 | 58 | 33 | 10 | 15 | 5 |
| T01 | 58 | 28 | 11 | 19 | 3 |
| T02 | 57 | 29 | 9 | 19 | 3 |
| T03 | 57 | 37 | 8 | 12 | 8 |
| T04 | 58 | 43 | 9 | 6 | 1 |
| T05 | 58 | 36 | 6 | 16 | 1 |
| T06 | 58 | 27 | 9 | 22 | 8 |
| T07 | 58 | 24 | 10 | 24 | 8 |
| T08 | 58 | 39 | 7 | 12 | 3 |
| T09 | 58 | 21 | 14 | 23 | 4 |
| T10 | 58 | 25 | 14 | 19 | 2 |
| T11 | 58 | 23 | 12 | 23 | 5 |
| **all** | **694** | **365** | **119** | **210** | **51** |

Deciding reasons: churn `replaceable_by_free_agent` 210; conditional
`above_replacement_band` 111, `churn_blocked_by_signal` 7,
`development_flag_overridden_no_usage` 1; protected `meaningful_dynasty_asset`
213, `development_upside` 95, `unpriced_never_auto_drop` 51,
`value_quarantined_never_auto_drop` 6. Replacement levels: QB 1405, RB 1610,
WR 1419, TE 2027, DL 2078, LB 2108, DB 1738 (no K).

Representative examples (V = value, W = replacement, snaps season/recent %):

| class | team | pos | age / yrsExp / pick | V / W / cost | conf | snaps | flags | reason |
|---|---|---|---|---|---|---|---|---|
| protected | T00 | WR | 26 / 3 / 55 | 4393 / 1419 / 2974 | high | 62/55 | — | meaningful_dynasty_asset |
| protected | T00 | DB | 23 / 1 / 93 | 1657 / 1738 / 0 | low | 69/77 (+7.8) | young_rising, young_established | development_upside |
| protected | T09 | DB | 21 / 0 / 48 | 564 / 1738 / 0 | low | 50/68 (+18.7) | high_draft_recent, young_rising | development_upside |
| protected | T00 | DL | 25 / 3 / 116 | — / 2078 / — | none | 45/65 | — | unpriced_never_auto_drop |
| protected | T02 | DB | 25 / 3 / 24 | 416 / 1738 / 0 | low | 97/100 | — | value_quarantined_never_auto_drop |
| conditional | T02 | LB | 26 / 3 / 90 | 3103 / 2108 / 995 | low | 74/74 | — | above_replacement_band |
| conditional | T01 | DB | 26 / 3 / 119 | 2002 / 1738 / 264 | low | 92/92 | — | above_replacement_band |
| conditional | T00 | DB | 25 / 3 / 95 | 1749 / 1738 / 11 | low | 98/96 | — | above_replacement_band (low confidence) |
| conditional | T03 | WR | 23 / 1 / 108 | 1493 / 1419 / 74 | medium | — | young_usage_unknown | churn_blocked_by_signal |
| conditional | T10 | DL | 22 / 1 / 17 | 1228 / 2078 / 0 | low | 8/8 | high_draft_recent | development_flag_overridden_no_usage |
| churn | T00 | DB | 32 / 10 / 5 | 1313 / 1738 / 0 | low | 100/100 | — | replaceable_by_free_agent |
| churn | T00 | LB | 32 / 11 / UDFA | 1842 / 2108 / 0 | low | 100/100 | — | replaceable_by_free_agent |
| churn | T00 | DL | 31 / 9 / 17 | 1347 / 2078 / 0 | low | 64/62 | — | replaceable_by_free_agent |
| churn | T02 | TE | 25 / 3 / 175 | 1664 / 2027 / 0 | low | 46/50 | — | replaceable_by_free_agent |
| churn | T04 | RB | 23 / 0 / 198 | 1710 / 1610 / 100 | medium | 7/8 | — | replaceable_by_free_agent |

(a) Young ascending defender → protected: T00's 23-year-old second-year DB
(snaps 69 → 77, value just below the DB replacement level) and T09's 21-year-old
second-round rookie DB (value 564, snaps 50 → 68) — a low board value alone does
not condemn them. (b) Low-value veteran → churn: T00's 32-year-old DB (value
1313 against a 1738 free agent). Every-down veterans are churn on DYNASTY value
only; the caller's weekly lineup (`weekly_starter_ids`) moves a starter to
`conditional`. The last churn row is a seventh-round rookie with no usage and no
draft capital — youth alone does not protect.
