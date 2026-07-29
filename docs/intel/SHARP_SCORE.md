# Sharp Score — methodology

**Version:** `sharp-v2` · **Config:** `config/sharp/scoring_v2.json` · **Code:** `src/sharp/score.py`

Every weight and threshold lives in the config. Nothing is hardcoded, every scored manager keeps
its component breakdown, and the methodology version moves with any change to the criteria.

---

## Three gates, widening to narrowing

A league can be good enough to *introduce* managers, good enough to inform *your own league-mates'*
tendencies, and still not good enough to *certify* anyone as sharp. Conflating these throws away
good seeds or admits bad evidence, so they are three separate predicates.

| Gate | Question | Admits | Code |
|---|---|---|---|
| **Discovery** | Can this league introduce us to managers? | Everything, incl. redraft + best-ball | `discovery.discover` |
| **Signal** | May its trades count as dynasty buy/sell? | Dynasty + keeper | `league_filter.is_eligible` |
| **Sharp** | May it certify someone as sharp? | **Dynasty only, ≥ 2 seasons old** | `league_filter.is_sharp_eligible` |

Two things follow that are easy to get wrong:

- **The shipped seed is a redraft league.** The Megalabowl (`872952227344678912`,
  `settings.type = 0`) is discovery-only. A gate that required dynasty *for discovery* would have
  discarded it and the graph would never have started.
- **Keeper counts for Insider Trading but not for Sharp.** Keeper trade behaviour is a hybrid —
  most of the roster resets annually — which is real evidence about a person you can trade with,
  and not clean enough to certify dynasty skill.

### Why leagues must be ≥ 2 seasons old

A first-year dynasty league is startup-draft fallout: enormous early churn, no established market,
and no completed season to judge anyone on. Counting it lets a manager look prolific purely for
having just drafted.

Sleeper chains seasons with `previous_league_id`, and that field ships inside the
`/user/{id}/leagues` payload the crawl already fetches — so **the age-2 check costs zero extra API
calls**, which is exactly why 2 is the default bar. Establishing age ≥ 3 would mean walking the
chain one request per link; nothing currently needs that precision.

---

## Hard eligibility gates

Failing **any** leaves a manager `evaluable: false` **with a reason** — never scored badly, never
silently dropped. These are minimum-viability filters; the percentile bar is what actually sizes
the cohort.

| Gate | Value | Rationale |
|---|---|---|
| `minCompletedSeasons` | 2 | One season is mostly variance. |
| `minDynastyLeagues` | 2 | Multi-league is core. **Keeper does not count.** |
| `minLeagueAgeSeasons` | 2 | See above. |
| `minCompletedGames` | 24 | ~2 full seasons; guards against two partial ones. |
| `minWinPct` | **0.52** | See below. |
| `maxAbandonedRosterRate` | 0.34 | Abandoned rosters are the opposite of sharp. |
| `requireRecentActivityDays` | 400 | A dormant manager is not a live signal. |

### On the win-rate floor

League win% averages **exactly 0.500 by construction** — it is a zero-sum pool. So 0.52 reads as
*"demonstrably above average"*, not *"good"*; over ~24–40 games it sits roughly half a standard
deviation above the mean.

It is deliberately a **viability gate and not the selector**. Set it much higher and it silently
becomes the real cutoff, fighting the percentile bar and making the cohort size unpredictable.

---

## Components

Weighted sum of five components, each percentile-normalized within the evaluable population, plus a
championship bonus, minus an explicit uncertainty penalty.

```
score = 0.36·performance
      + 0.22·rosterQuality
      + 0.22·multiLeagueConsistency
      + 0.12·longevity
      + 0.08·activity
      + championshipBonus        (0 … 0.12)
      − uncertaintyPenalty       (0 … 0.25)
```

- **performance** — win%, playoff rate, championship rate (beta-binomial shrunk toward the
  population base rate, `priorN = 6`), median finish, points-for.
- **rosterQuality** — value **relative to each league's own average**, so a manager in a shallow
  league cannot look sharp on raw value; plus age-, depth-, and pick-capital-adjusted variants.
- **multiLeagueConsistency** — the anti-luck term. Scored as the **share** of leagues finishing
  above median, so adding mediocre leagues *cannot raise it*, then penalized for cross-league
  variance.
- **longevity** — saturating; seasons 1→3 matter far more than 8→10.
- **activity** — sustained participation, **not** raw volume. Capped, so churn cannot buy entry.

### Championship preference

*"Preferably they have won the league before"* — implemented as a **bounded bonus, not a hard
gate**, and always named first in `contributors` when it fires.

| Titles | Bonus |
|---|---|
| 1 | +0.06 |
| 2 | +0.08 |
| 3+ | +0.10, capped at 0.12 |

A hard title requirement would be self-defeating: in a 12-team league only ~1/12 of managers can
win per season, so requiring one cuts the cohort far below a top quarter and bars managers who
consistently make deep runs in strong leagues. The bonus is large enough to be decisive at the
margin; diminishing, because the first title is the one that proves it can happen.

---

## Qualification

A manager joins the cohort only by clearing **both** bars:

- `minScorePercentile` **0.75** — top quartile
- `minConfidence` **0.55**

Score and confidence are **separate outputs, never blended**. "How good" and "how much evidence"
are different questions, and blending them hides exactly the uncertainty that needs surfacing. An
elite-looking record with two seasons has a high score and low confidence, and does **not**
qualify.

### "Top quarter" of *what*

The two readings differ a lot, so **both are reported** rather than one being picked silently:

- `qualifiedShareOfEvaluable` — the bar actually applied. The percentile runs among managers who
  cleared every hard gate, because a percentile over un-gated managers gets dragged around by
  records too thin to judge.
- `qualifiedShareOfObservable` — the same cohort as a fraction of **everyone discovered**. Always
  smaller, because the gates run first.

Tune with `minScorePercentile`: 0.67 for a top-third cohort, 0.85 to tighten.

---

## Measured coverage (live, 2026-07-29)

From the Megalabowl seed, 180 API calls:

| | |
|---|---|
| Managers found | 356 |
| Leagues found | 689 |
| — signal-eligible (dynasty + keeper) | 485 |
| — **sharp-eligible** (dynasty, ≥ 2 seasons) | **344** |

Excluded from sharp: `best_ball` 110, `too_new` 109, `redraft` 77, `keeper` 32, `unknown` 16 —
reported per reason, never silently dropped.

---

## Known limitation

Discovery yields *managers*; the Sharp Score needs *records* — multi-season results, playoff
outcomes, championships, roster values. That is a second crawl pass over `previous_league_id`
chains and `winners_bracket`, and it is the bulk of the remaining Stage 4 work.

Until it exists, `load_manager_records()` returns empty and the endpoint honestly answers
`cohort_building`. It deliberately does **not** synthesise records from transactions alone — the
gates need completed-season history that transactions do not contain, and scoring managers on
partial inputs would qualify people on the wrong evidence.
