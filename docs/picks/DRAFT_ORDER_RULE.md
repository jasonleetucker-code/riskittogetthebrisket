# Rookie-draft order rule and the owned-pick forecast

**Owner decision: 2026-10-04 (canonical for `dynasty_main`).**  Supersedes every
earlier "reverse standings is not established / Max PF?" caveat for this league.

## The rule

1. The worst final **regular-season record** receives the earliest pick.
2. Teams tied on record are ordered by **lower total regular-season Points For**
   first.
3. Applied recursively through every tied group.

Not Max PF, not all-play record, not Team Strength rank, not any other
methodology.  A tied game counts as half a win (the standings convention).

Team Strength, projections, schedule strength, injuries, roster quality and the
season simulation are **inputs that forecast** a team's final record and Points
For.  They never decide draft order themselves.

## One owner

| What | Where |
|---|---|
| The rule (lexicographic: wins ascending, then Points For ascending) | `src/public_league/draft_order.py::draft_order` |
| Which leagues use it | `config/leagues/draft_order_rules.json` (`dynasty_main`: owner-approved; any league absent there is **unknown** and gets no draft-slot forecast) |
| Real final standings → order | `draft_order_from_standings` (a missing record or Points For is refused, never 0) |

The one case the rule does not decide is identical record **and** identical
Points For.  In a simulation it is broken by the caller's random stream, so no
identifier decides it.  For real standings it is reported in `unresolved_ties`
and never silently ordered.

## The forecast

`src/ros/playoff_sim.py` already draws every team's final regular-season wins and
Points For in each simulation.  It applies the rule above to each draw and
publishes, per team:

* `draftSlotDistribution`: `P(slot = i)`;
* `finalWins` / `finalPointsFor`: mean, p10, p50, p90;
* at the payload level: `draftOrderRule`, `season`, and regular-season games
  played and remaining.

The draft-order draws use a cloned random stream, so playoff and championship odds
are byte-identical with or without the rule.  This is pinned in
`tests/ros/test_standings_tiebreak.py`.

The slot distribution is for the class drafted **after the simulated season**
(`season + 1`).  Later classes have no forecast.  A pick's slot follows its
**originating** franchise's finish, not its current holder's.

## Market side for generated trades (`src/trade/pick_market.py`)

For generated-trade comparability only.  It never replaces the canonical pick
value (`src/api/pick_value_resolution.py`), and is never shown as KTC's native
price for a pick.

```
P(tier)        from the slot distribution via identity.picks.slot_tier
P_used(tier) = c x P_forecast(tier) + (1 - c) x 1/3
V_market     = sum over Early/Mid/Late of P_used(tier) x KTC_tier_value
```

* No forecast (`c = 0`) gives exactly the plain average of KTC's native
  Early/Mid/Late values for that year and round, labelled PRIOR.
* `c` is **provisional** until calibrated:
  * `0.5 x (share of the regular season played)`;
  * `1.0` only when the regular season is complete, because the final standings
    are then observed rather than forecast.
* Calibration (`calibrated_confidence`) is the forecast's Brier skill against
  equal thirds over realized drafts.  It takes over once at least 24
  forecast/realized pairs exist (two 12-team classes), and a forecast no better
  than thirds earns no weight.
* The forecast never hard-switches a pick to its most likely tier.

Every value keeps its explanation (`marketDerivation`):

* KTC Early, Mid and Late values, and their generic average;
* record, Points For and slot distributions, and tier probabilities;
* confidence and its basis;
* tier weights used, the forecast-weighted value and the final value;
* method version.

## Known follow-ups

* **Pick Projector.** `src/ros/pick_projection.py` still orders its *projected
  slot* directly by Team Strength rank.  That is a display-only point estimate,
  but this rule says Team Strength must not determine order.  It should read the
  simulation's slot distribution instead.
* **Forecast capture.** Calibration needs the forecasts recorded at the time.
  The weekly pick-forecast snapshot (AL-P4) should capture `draftSlotDistribution`
  and the tier probabilities alongside its existing fields.
