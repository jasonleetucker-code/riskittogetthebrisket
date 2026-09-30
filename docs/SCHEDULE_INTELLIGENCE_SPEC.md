# Schedule Intelligence — specification

**Status:** canonical feature record · Milestone A implemented (#1530) · later milestones per the portfolio below
**Owner directive:** 2026-09-29 (Schedule Intelligence implementation directive)
**Authorization:** `docs/EXECUTION_PLAN.md` §0 "Schedule Intelligence — owner directive, 2026-09-29"
**Portfolio / Calculator Ideas:** issue #1530 · `docs/OWNER_REQUESTED_TODO.md`

> **Not the removed schedule generator (X-01).** Schedule Intelligence is read-only,
> retrospective analysis of games already played. It never creates, publishes,
> recommends for adoption or writes a schedule to Sleeper.
> `docs/OWNER_FEATURE_INVENTORY.md` X-01 stands unchanged.

## 1. The question

> How good were this team's performances, what actually happened, and how differently
> could those same performances have turned out under another defensible schedule?

- Credit real wins.
- Explain schedule effects.
- Never erase standings, never imply that all randomness is schedule luck, and never
  present a retrospective counterfactual as a forecast.

## 2. Concepts kept separate

| | Concept | Owner |
|---|---|---|
| A | **Actual results.** Official outcomes under the actual schedule. | `metrics` (host record, median included) |
| B | **Equal-opponent baseline.** How the team scored against its eligible peers in each finalized week. | `schedule_impact` (`equal_opponent_v1`, exact) |
| C | **League-valid alternative schedules.** Joint calendars satisfying the declared real-league constraints. | Milestone B |
| D | **Timing-only alternatives.** The actual opponent allocation is preserved; only legally movable timing changes. | Milestone B/D |
| E | **Future projections.** | The existing prospective engines (`playoff_odds`, `ros.playoff_sim`), never this module |

"Expected wins" is never used without naming its baseline.

## 3. Model `equal_opponent_v1` (Milestone A)

- **Fixed:** every team's weekly score, points for, median / league-average results,
  and which weeks each team played a head-to-head game.
- **Varies:** the head-to-head opponent in each finalized week.
- **Distribution:** in each finalized week, each other team that played a
  head-to-head game that week is equally likely.
- **Method:** exact and analytic. No sampling, no seed, no Monte Carlo error.
- **Unit:** one conventional head-to-head game per team-week. Anything else
  (a team in two games in a week, a self-matchup) is reported as `unsupported`
  rather than computed as if the format were simpler.

The formulas:

```
c(a, b)          = 1 (a > b) · 0.5 (a == b) · 0 (a < b)
eligible(w)      = teams that played a head-to-head game in finalized week w
allPlayRate(i,w) = mean_{j in eligible(w), j != i} c(s_iw, s_jw)
equalOpponentExpectedH2HCredits(i) = Σ_w allPlayRate(i, w)
actualH2HCredits(i)                = Σ_w c(s_iw, s_opp(i,w))
scheduleImpact(i | equal_opponent_v1) = actual − expected
```

- **Sign:** positive means the schedule helped; negative means it cost wins.
- **Byes:** a bye team scored but played no game. It has no head-to-head row that
  week and is not an eligible opponent. Under symmetric win/tie credit, league-wide
  expected credits equal actual credits equal the number of games, so schedule
  impact sums to zero.

**Why this is also exact over round-robin calendars.** Under the uniform
distribution *over* all labelled single round-robin calendars, each team's week-w
opponent is uniform (permuting week labels maps calendars onto each other). So the
mean actual credits across all such calendars equals `Σ_w allPlayRate`. Weekly
independence is not required. Any one calendar on its own is not uniform; the
claim is about the average over the calendar space.

The test oracle checks this by full enumeration: every labelled calendar of a
6-team league (6 one-factorizations × 5! = 720). It never calls the module's
formula.

**Lab fixture.** An 8-team, 7-week single round robin has 6,240 unordered round
partitions × 7! = 31,449,600 calendars. The partition count is verified by
enumeration in CI; the 31.4M calendars are not. In that complete league,
expected credits equal all-play wins divided by 7 (a consistency check of the
stated identity, not oracle evidence). The lab's other percentages,
team count, length and tiebreaks are not generalized to real leagues.

## 4. Median games and official records

- Changing a head-to-head opponent while scores stay fixed cannot change a
  median result, so median results pass through every schedule-only analysis
  unchanged and are never attributed to schedule.
- The official record is the host's (median included).
- The median component is published only when both hold:
  1. `official games = H2H games × (2 with the median game, 1 without)` over the
     same finalized weeks;
  2. host record − head-to-head record equals the median results derived from
     the fixed scores (each score against the median of every score posted that
     week: `>` win, `<` loss, `==` tie), every part within `0..H2H games`, with no
     excluded game.
- Otherwise it is `unavailable` with a reason:
  - `official_record_unaligned`;
  - `official_record_inconsistent`;
  - `median_setting_unknown`;
  - `official_record_missing`.
- A disagreement (stat correction, commissioner edit, tie rule) is never
  attributed to the median game.
- Player-contribution counterfactuals (Milestone E) are different: they change
  a team score and therefore the median, which must be recalculated.

## 5. Contract (`schedule_impact.season_contract`)

Every surface reads this contract. None recomputes it.

Contract fields:
- `state`: `complete` | `partial` | `unavailable` | `unsupported`;
- `issues`, `reason`, `teamsWithoutEvaluableGames`;
- `season`, `leagueId`, `cutoffWeek`, `finalizedWeeks`;
- `model` (id, baseline, fixed, varies, distribution, method, notA);
- `algorithmVersion`, `scoreHash`, `configHash` (median flag, team count);
- `generationId` (covers algorithm, model, league, season, scores, config and official records);
- `teams[]`;
- `weeks[]` (available from `season_contract`; not published until a surface renders it).

Each `teams[]` row has:
- identity: `teamKey`, `ownerId` (null for an orphan roster), `rosterId`, `orphanRoster`, `displayName`, `teamName`;
- head-to-head: `games`, `h2hWins`/`h2hLosses`/`h2hTies`, `actualH2HCredits`;
- all-play: `allPlayWins`/`allPlayLosses`/`allPlayTies`, `allPlayRate`;
- expectation and impact: `equalOpponentExpectedH2HCredits`, `scheduleImpact`;
- points and opponent strength: `pointsFor`, `pointsFaced`, `pointsFacedVsField`, `avgOpponentScorePercentile`;
- records: `officialRecord`, `medianComponent`;
- coverage: `byeWeeks`, `excludedWeeks`.

Each `weeks[]` row has:
- `week`, `teamKey`, `score`, `opponentKey`, `opponentScore`;
- `h2hResult`, `h2hCredit`;
- `allPlayWins`/`allPlayTies`/`allPlayLosses`, `allPlayRate`;
- `scheduleImpact`, `opponentScorePercentile`, `pointsFacedVsField`.

Opponent difficulty compares the opponent actually faced against the other teams
this team could have faced that week:

```
opponentScorePercentile = (opponents out-scored + ½ ties) / (other eligible opponents)
pointsFacedVsField      = opponent score − mean of this team's eligible opponents' scores
```

**Rules:**
- Finalized weeks only, through `metrics.final_regular_season_weeks`.
- An in-progress week never contributes.
- The adapter groups matchups itself, because `metrics.matchup_pairs` silently
  drops any group that is not exactly two rows:
  - a group of three or more is `unsupported`;
  - a group whose partner row is missing (`unpaired`), and a game with a missing
    score, are left out, marked per team in `excludedWeeks`, and make the state
    `partial`;
  - a scored team with no `matchup_id` is a real bye (`byeWeeks`).
- An ownerless (orphan) roster is a real participant, keyed `roster:<id>`.

**Exposure:** `luck.scheduleImpact = {currentSeason, bySeason}` on the existing
public `luck` section. That is an aggregate league outcome of the same class as
the already-public expected wins. Season summaries only: measured about 24 KB per
league for three seasons. A failure computing it yields `{state: "failed"}` and
never takes the Luck section down.

## 6. Surfaces

| Surface | Milestone | State |
|---|---|---|
| League Hub (Luck tab) sortable table + method disclosure | A | implemented (this PR) |
| Team page compact summary | C1 | implemented: franchise page "Schedule impact" card (record, expected wins with baseline, impact, one reading, link to the league table) |
| Power Rankings context (display only; formula unchanged) | C1 | implemented: "Schedule" column beside Record + a reading in the expanded breakdown labelled "not part of the power score"; ranks/scores pinned identical with and without it |
| Weekly recap / Upside Report statements (templated from the contract; an LLM may only narrate) | C | not started |
| Schedule share card (separate from the full-league rankings card) | C | not started |
| Historical season views (bySeason already in the contract) | C1 / C | team page season-results "Schedule" column per past season (C1); league-wide historical view not started |
| Hard Luck statistical distinction | C | not started (coordinate with the awards claim) |
| Schedule Multiverse (read-only) | B | not started |
| Valid schedule-slot swaps, retrospective playoff sensitivity | D | not started |
| `scheduleNeutralRealizedWAR` → MVP candidate (shadow) | E | blocked on C5-WAR-01 |

## 7. Supported formats and limitations (A)

| League | Teams | Median game | Divisions | Weeks | A support |
|---|---|---|---|---|---|
| `dynasty_main` | 12 | on | 3 | 14 | supported (the equal-opponent baseline ignores divisions by definition; a division-aware valid-calendar model is B) |
| `dynasty_new` | 10 | off | none | 14 | supported |

Limits of the equal-opponent baseline:
- It is not a league-valid calendar model. Repeat opponents, divisions and fixed
  structure are Milestone B, under separate model ids.
- It produces no record distributions, percentiles, finishing positions or
  qualification odds. Those need a declared calendar distribution (B).
- Multiple games per team-week are `unsupported`.

## 8. Gates

- The official Power Rankings and MVP formulas are unchanged.
- League MVP eligibility stays the actual playoff field **and** a .500-or-better
  official record (exactly .500 counts). It uses official standings, never
  schedule-neutral wins.
- Unified Manager of the Year has no record or playoff gate.
- Schedule impact never alters dynasty values, Hill curves, consensus weights,
  pick values or trade prices.

## 9. Evidence (Milestone A)

**Reconciled on production data** (public Sleeper snapshots, 2026-09-29) against
the live Luck section, an independent implementation.

Across both leagues × 2024–2026:
- actual head-to-head credits are identical;
- expected credits agree within Luck's 2-decimal rounding (≤ 0.0045), except
  `dynasty_new` 2024 (see below);
- impact sums to zero;
- the score-derived median rule matches the host for every team in
  `dynasty_main` 2026 (12/12) and 2024 (10/10).

**`dynasty_main` 2025's median component is withheld.** The host record disagrees
with the score reconstruction for 8 of 10 teams by about one game (for example 21-5
official vs 22-4 from scores). Neither a median nor a mean rule reconciles it;
likely causes are post-final stat corrections or commissioner edits. So that
season's median component is `unavailable: official_record_inconsistent` rather
than blamed on the median game. Schedule impact itself is unaffected, because it
uses head-to-head games only.

**`dynasty_new` 2024 disagrees by up to 0.68.** That season has two orphan
rosters. `luck.py` drops them from all-play rivals but counts games against them
in actual wins, so its expected and actual cover different game sets. This
module keeps them as participants. This is a pre-existing `luck.py` defect,
recorded in #1530.

**Tests:** `tests/public_league/test_schedule_impact.py` (exhaustive 6-team
oracle; invariants, byes, ties, missing, unsupported, relabelling, orphan rosters,
adapter grouping, median cross-check, generation id, failure isolation) and
`frontend/__tests__/components/schedule-impact.test.jsx`. Six sabotages go red and
restore green:
- reversed sign;
- self as opponent;
- a bye team counted as an opponent;
- a median record derived from misaligned totals;
- broken matchups dropped silently;
- a median record published by subtraction alone.
