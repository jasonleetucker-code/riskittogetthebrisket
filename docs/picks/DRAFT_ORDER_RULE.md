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
* `finalWins` / `finalPointsFor`: mean, p10, p50, p90.  `finalWins` is the
  RECORD the order ranks on: wins plus half a win per tied game, including
  ties already on the books;
* at the payload level: `draftOrderRule`, `season`, and
  `regularSeasonProgress` — `weeksFinal` / `weeksTotal` / `complete`, in the
  league's own regular-season WEEKS (`1 .. playoff_week_start - 1`, counted
  final by the canonical finished-week gate).  Unknown length is `null`
  throughout.  Completion is never inferred from an empty remaining schedule:
  future matchups that failed to post also leave it empty.

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
  * `0.5 x (regular-season weeks final / total)`;
  * `1.0` only when every regular-season week is final, because the final
    standings are then observed rather than forecast;
  * `0` when progress is unknown — never read as "early".
* Calibration (`calibrated_confidence`) FITS `c` directly: the value in [0, 1]
  minimising the mean Brier score of the shrunk forecast `P_used` against the
  realized tier.  It is fitted separately per season-progress bucket (quarters
  of the regular season, plus complete), because a week-2 and a week-13
  forecast are different instruments.  A bucket takes over once it holds at
  least 24 forecast/realized pairs (two 12-team classes); ties in the fit go to
  the smaller weight, so a forecast no better than thirds earns none.
* The forecast never hard-switches a pick to its most likely tier.

Every value keeps its explanation (`marketDerivation`):

* KTC Early, Mid and Late values, which KTC key priced each, and their
  generic average;
* when no forecast applies, why (`forecastUnavailableReason`: no slot
  forecast available, a later class, an unmapped originating franchise);
* record, Points For and slot distributions, and tier probabilities;
* confidence and its basis;
* tier weights used, the forecast-weighted value and the final value;
* method version.

## Known follow-ups

* **Pick Projector — DONE (2026-10-04, `pick_projector_v2_draft_order_rule`).**
  `src/ros/pick_projection.py` no longer orders teams by Team Strength rank.  It
  reads the league's fresh cached season simulation (never runs one on a
  request): teams are ordered by EXPECTED rule slot, each carrying its
  `draftSlotDistribution`, and a pick's projected slot follows its ORIGINAL
  team.  Only the class drafted after the simulated season is forecast; every
  later class, a league with no recorded rule, and a missing or stale
  simulation get `projectedSlot: null` with a named
  `slotForecastUnavailableReason` — never a Team-Strength guess, never slot 0.
  Confidence is the simulated probability of landing within one slot of the
  projected one (cut-offs 0.8 / 0.5, a stated PRIOR), still capped by horizon.
* **Forecast capture — partly done.** The weekly pick-forecast snapshot (AL-P4)
  copies the projector output verbatim, so since v2 every capture records each
  pick's `slotDistribution`, the simulation's `regularSeasonProgress`, the
  simulated season and the recorded rule (`rules.draftOrderRule`, no longer an
  "unowned" placeholder).  Still missing: the tier probabilities and `c` that
  `pick_market` used at the time, and a realized-order join.  Until enough
  pairs exist every forecast runs on the provisional `c`.
* **Between rollover and the draft.** Once Sleeper rolls the league to the next
  season, the snapshot holds no games, so the simulation publishes no slot
  forecast, and the upcoming class stays at the plain average.  The previous
  season's FINAL standings fix that order exactly
  (`draft_order_from_standings`), but nothing feeds them in yet.  This fails
  safe toward the prior.
* **Seeding ties.** Playoff seeding in the simulation still starts from wins
  alone (ties on the books are not credited), unlike the standings convention.
  The draft order credits them; seeding is left unchanged here so published
  odds do not move, and is the playoff-simulation owner's to fix.
