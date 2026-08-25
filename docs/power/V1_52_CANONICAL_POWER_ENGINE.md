# V1-52 — one canonical weekly power-rankings engine

Status: **Steps 1-5 landed.** Step 5 (the retirement) shipped differently
from what this document originally scoped for it -- see "Step 5,
corrected" below, appended rather than rewritten in place so the reasoning
trail that led to the corrected design stays legible.

Companion to `docs/playoffs/V1_51_CANONICAL_PLAYOFF_BRACKET.md`, which
established the precondition this unit builds on.

## What was actually wrong

Two engines answer "how strong is this team this week", and the site
publishes both. The audit capture
`docs/master-site-audit/evidence/W30/power-two-engines.json` records
them on the same week:

| engine | n | Jason |
|---|---|---|
| `public_league/power.py` | 10 | rank **10 of 10**, score 0.00 |
| `ros/power_v2.py` | 12 | rank **3 of 12**, score 80.69 |

mean \|rank shift\| 2.8, max 7.

That capture is usually quoted for the rank shift. Reading its
`effectiveWeights` is more damning, and it is what this unit turned on:

```json
"v2": { "preseason": true,
        "effectiveWeights": {"team_ros_strength": 0.38, "roster_health": 0.03} }
```

So the comparison is **one week of last season's scoring percentiles**
against **pure roster strength**. The two engines were not disagreeing
about the answer — they were answering different questions, and nothing
on either surface said so.

Note also `n`: **10 against 12**. `power.py`'s `currentRanking` is the
last *single week*'s ranking, so any owner who did not play that week is
absent from the published power ranking entirely.

## What the toggle actually did

`settings.useRosPowerRankings` decides which engine renders the Power
tab, and it **defaults to `true`** — so the public `/league` Power tab
already shows `power_v2`. A comment in `LeagueClient.jsx` claimed the
opposite ("false until validated per-user") until 2026-08-19; that
mattered, because anyone reasoning about which ranking the site shows
got the answer backwards.

A toggle that picks an *implementation* is a champion/challenger switch
left permanently in the UI. The destination is a toggle that picks a
**lens** — a legitimate question about what to measure.

## Steps landed

### 1-2 — two lenses, and one trend

`LENS_FORWARD_LOOKING` / `LENS_RESULTS_ONLY`. They are **not two
formulas**: results-only is the same `WEIGHTS` vector with
`team_ros_strength` declared missing and renormalised by the machinery
that already handles an absent team-strength file, so every
retrospective component keeps its weight *relative to the others*.

The per-week trend moved into the canonical engine and runs through the
same `_score_state` as the headline. A second scoring implementation for
the series is how a chart ends up being a different quantity from the
number printed beside it.

The trend is **results-only at every point, including the last**.
`team_ros_strength` is a single current snapshot with no per-week
history, so back-filling it is the as-of defect and splicing it into
only the final point is worse — the line would jump at the end for a
reason unrelated to how the team played, and no reader could tell that
from a real move.

### 3 — refuse to rank when no component survives

Renormalisation has a floor nobody had put in. When *every* component is
dropped, `active_weights` is empty, `weight_total` fell back to `1.0`
against an empty numerator, every owner scored exactly `0.0`, and the
sort — stable over equal keys — handed out ranks `1..N` in `owner_ids`
order. **An identifier ordering, published as a power ranking.**

Reachable structurally, not rarely: results-only drops
`team_ros_strength` by definition and preseason dropped all seven
historical components, so the state was guaranteed for the whole
offseason.

On the committed dev snapshot it was visible and self-contradicting:
five owners, every score `0.0`, and the published order **disagreed with
the components printed beside it** — `owner-B` led `owner-A` on five of
seven components and was ranked below it.

Same family as the playoff-odds defect fixed in V1-51, where a
placeholder made every matchup a tie and the third tiebreak (the
`ownerId` string) became the answer. The coercion baseline had already
registered the mechanism as debt — `weight_total = sum(...) or 1.0` —
so this was a recorded hazard coming true, and the gate reports that
entry retired.

Now: no surviving component, no ranking. `powerScore` and `rank` are
`None` — never `0.0`, which is a score a team can earn, and never
`1..N`. An `unrankable` block names the reason and the missing inputs;
the owners and their raw components are still listed. Same posture
`playoff_structure` takes for an unknown bracket. The UI renders it as a
named state rather than the "not ready, the next scrape will populate
this" copy, which would promise numbers that are not coming.

### 4 — the preseason suppression belongs to one lens

`_is_preseason` dropped all seven historical-results components, and its
docstring gave the reason: they "describe a finished year and don't
project the upcoming one ... so the score reflects only forward-looking
inputs". Correct for the **forward-looking** lens. Exactly backwards for
the retrospective one, whose entire subject matter *is* the finished
year.

Step 1 added the results-only lens and it inherited a suppression
written for the other one. The consequence was total: results-only
already drops `team_ros_strength`, so preseason left it with nothing —
the every-component-missing state above — while the completed seasons it
is made of sat in the accumulators untouched.

Repaired, and visible in one row on the dev snapshot: `owner-B`, ranked
2nd on an all-zero score under the defect, is now 1st at 86.61.
Forward-looking still refuses there, correctly — preseason with no
team-strength file has genuinely nothing to look forward to.

Mutation-checked in both directions: applying the suppression to both
lenses again, and removing it entirely, each turn tests RED. The second
is what stops the repair being "delete the rule".

## Do the two engines agree? Measured

With the lens working correctly, `power.py` versus the canonical engine
under results-only:

| fixture | mean \|rank shift\| | max | note |
|---|---|---|---|
| committed dev snapshot (real) | **0.00** | 0 | identical order on the 4 common owners; v2 also covers a 5th that v1 drops |
| 12 owners, 6 weeks, monotone strength ladder | 0.33 | 1 | weak evidence by construction — a ladder makes most formulas agree |
| adversarial: great scores, 0-6 record (schedule luck) | 0.67 | 1 | v1 has **no** W/L or streak component; v2 weights them 0.10 + 0.05 |

So the retrospective quantities substantially agree, and the large
real-world divergence in the W30 capture is the **forward-looking
input** — which is exactly what the lens distinction names. That is the
evidence that these are one engine's two lenses rather than two engines.

**Limitation, stated rather than glossed:** two of those three fixtures
are synthetic, and the one real artifact is a small dev snapshot. A
comparison on the production league needs its snapshot plus the ROS
team-strength file, neither of which exists in this environment
(`data/` is gitignored). That measurement belongs with the retirement.

## Step 5 — the retirement, and why it is not a shim

`power.py` must stop being an engine. The obvious minimal move — make
`build_section` an adapter that delegates to the canonical engine and
renames fields — **does not work**, and it is worth recording why so it
is not attempted again:

`power.jsx` renders `components.pointsPerGame`, `components.recentAvg`
and `components.allPlayWinPctThisWeek` as **raw values**. The canonical
engine publishes `components.ppg` and `components.recent` as
**percentiles**. An adapter cannot recover a raw PPG from a percentile,
so it would have to compute one — which is a second owner again, one
layer down, which is the defect this unit exists to remove.

Shape differences, for the record:

| | `power.py` | `power_v2.py` |
|---|---|---|
| series location | `weeks`, `seriesByOwner` (top level) | `trend.weeks`, `trend.seriesByOwner` |
| `seriesByOwner` | list of `{ownerId, displayName, points[]}` | dict keyed by ownerId |
| score field | `power` | `powerScore` |
| per-row extras | `teamName`, `record`, `games`, `weekRankDelta` | `rosStrengthPercentile`, `weightsApplied` |

So the retirement is **one renderer, one engine, the toggle selecting a
lens**: `ros-power.jsx` absorbs the trend chart, `power.jsx` and
`power.py` retire together. That changes what the Power tab *displays*
for users on the v1 path — percentile component bars instead of raw
PPG columns — which is a deliberate, user-visible change and needs the
production measurement above alongside it.

## Prerequisites fixed along the way

* **Playoff odds published alphabetical order as certainty** — a flat
  `[100.0]` placeholder made every matchup a tie, so the `ownerId`
  string tiebreak decided the standings. The seven `1.0`s on the
  committed production artifact are exactly the lexically-first seven
  Sleeper user ids. (Shipped with V1-51, #919.)
* **Roster health was double-counted** — once as its own 0.03 weight and
  again inside `team_ros_strength`. Folded in (0.38 → 0.41).

## A note on fixtures

`_make_snapshot` never populated `roster_to_owner`, which
`luck._season_weekly_scores` needs to attribute a matchup row to an
owner — it **skips** rows it cannot resolve, so zero weeks scored, every
component fell back to its neutral default, and every owner scored an
identical `33.64` across three weeks of deliberately different points.

Two of this unit's own lens tests were asserting shape while measuring
nothing. Repaired at the shared helper, with the reason recorded there,
because this trap cost three separate measurements in this lane before
it was named.

## Not claimed

Nothing here is deployed. The refusal and the lens repair both change
live public `/league` output the moment they ship — the refusal replaces
a fabricated order with an honest empty state, and the lens repair gives
the retrospective view real numbers all offseason where it previously
had none. Both should be observed in production rather than assumed.

## Step 5, corrected

The claim above -- "an adapter cannot recover a raw PPG from a percentile,
so it would have to compute one, which is a second owner again" -- does
not survive reading `_score_state` itself. `inputs[oid]["ppg"]` and
`inputs[oid]["recent"]` (the exact raw magnitudes power.py's own
`pointsPerGame`/`recentAvg` are, from the same `career`/`recent`
accumulators) are computed as an unavoidable intermediate step *before*
`_percentile(...)` converts them into `components.ppg`/`components.recent`.
The adapter framing was never tested against the code: this is not
"recompute a raw value from a percentile" (the thing that really would be
a second engine) — it is "stop discarding a local this one function
already built." `components.allPlayWinPctThisWeek` was already correctly
identified elsewhere (V1-52 item D, #996) as never having been a
percentile in `power_v2` at all; this closes the other two of the three
supposedly-unrecoverable fields the same way.

What actually shipped, once that was corrected:

* `_score_state` gains `components.pointsPerGame`/`components.recentAvg`
  (raw), additive alongside the existing `components.ppg`/`components.recent`
  (percentile) — present on headline rows, every `trend.weeks[].rankings`
  row, and the refuse-to-rank rows. Display-only: excluded from `WEIGHTS`
  by construction, so `powerScore` cannot move.
* `ros-power.jsx` gains the week-selector table and the power-score line
  chart `power.jsx` had — both built from `trend.weeks`/`trend.seriesByOwner`,
  data the canonical engine already publishes. No second computation on
  the frontend.
* The retirement is NOT "the toggle selecting a lens" as originally
  scoped. `settings.useRosPowerRankings` is deleted outright, not left as
  an inert toggle — it had already defaulted to `true` since 2026-04-29,
  so `power.py`/`power.jsx` were reachable only via explicit opt-out, and
  there is no longer an alternative for a toggle to select between.
  `src/public_league/power.py`, `frontend/app/league/sections/power.jsx`,
  and the `_SECTION_BUILDERS["power"]` eager registry entry are deleted,
  not deprecated.
* The Playoff Odds card `power.jsx` embedded (a separate feature from
  power rankings, fetching `/api/public/league/playoffOdds`) had no other
  frontend consumer anywhere on `/league` — deleting `power.jsx` outright
  would have silently dropped it. Ported into `ros-power.jsx` unchanged,
  same v1 data source, zero methodology change; the dormant ROS-blended
  `rosPlayoffOdds` section (built server-side, never consumed) is left
  untouched, since activating it is a separate, bigger decision than
  retiring the power-ranking engine.
* The shape differences table above is now fully closed except `games`
  (dropped — not rendered by `power.jsx`'s table and recoverable from
  `record` by any future consumer that needs it) and `weekRankDelta`
  (superseded, not reproduced — see below).

`weekRankDelta` is not reintroduced under that name. `ros-power.jsx`
already computed an equivalent (`trendDelta`, prior-vs-last-two-weeks rank
change from `trend.seriesByOwner`, always within the results-only lens so
it never mixes with the headline lens's forward-looking rank) since #979.
It already returns `null` rather than `0` when fewer than two trend points
exist or a compared week was unrankable — the same "unknown stays `None`"
posture `power.py`'s own `weekRankDelta` violated (`(prior - rank) if
prior else 0`, an anti-pattern documented and NOT reproduced when
`overview.currentPowerLeader` was redirected in #996). The week-selector's
own `weekDelta` helper generalizes the same function to any two adjacent
trend weeks rather than only the last two, preserving the identical
null-propagation semantics — no new field was invented to replace it.
