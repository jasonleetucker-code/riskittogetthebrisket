# V1-51 — L2 production verification, and why a green deploy was not the answer

**#956, feature head `1bea81bca`, merge `4157adfe4`.** Verified by Integration
2026-08-20 against the **deployed** build, not against the merge.

## 1 · Deployed SHA

`cca488cd7765c0e2fc673d02930bee8f3c36e2db` — deploy run `32353505254`. It contains
both `4157adfe4` (the #956 merge) and `1bea81bca` (the feature head); both
ancestries were checked, not assumed.

## 2 · The measurement — same league, same preseason state, 29 minutes apart

Public API, `dynasty_main`, `season 2026`, `weeksPlayed 0` in both captures.

| | BEFORE `09:17:40Z` (build `b5f339d2d`) | AFTER `09:47:17Z` (deployed `cca488cd7`) |
|---|---|---|
| `playoffOdds` | `numSims 0` · `simulated false` · `unsimulable no_scored_weeks_in_league` | identical |
| `rosPlayoffOdds` | `playoffOdds []` · `n_simulations 0` | identical |
| `rosChampionship` | `championshipOdds []` · **`n_simulations 10000`** · no `unsimulable` | `championshipOdds []` · **`n_simulations 0`** · `unsimulable no_scored_weeks_in_league` |

Held constant across both captures, so the change is attributable:
`playoffSpots`/`playoffSeeds 7`, `byeSeeds 1`,
`playoffStructure {playoffTeams 7, byeTeams 1, playoffWeekStart 15, source league_settings}`,
`rosStrengthAvailable true`, `bestBallVarianceMode depth_aware`,
`pointsModelSource fallback-constants`.

**The five truthfulness requirements:**

1. no engine claims simulations that did not run — **holds**;
2. zero simulations reported as zero — **holds**, all three;
3. the championship endpoint no longer reports `n_simulations: 10000` with an empty
   result — **holds**;
4. unsimulable/degraded state explicit and consistent — **holds**, with one residual
   named in §4;
5. no championship-probability methodology changed — **holds**; every methodology
   field above is byte-identical, only the count and the missing-state block moved.

All three engines now answer one state with one number and **one word**,
`no_scored_weeks_in_league` — the invariant `public_league/playoff_odds.py` states in
its own comment (*two engines must not invent different words for one state*).

## 3 · DEPLOYED IS NOT VERIFIED — demonstrated, not asserted

**The deploy of the merge succeeded and production stayed wrong for nineteen more
minutes.**

Deploy `32352065385` shipped `4157adfe4` — the fixed code — and completed **success
at 09:28:55**. At 09:36 production still served `n_simulations: 10000`.

`rosChampionship` is served from `data/ros/sims/latest_championship.json` under a 6 h
TTL (`_SIM_CACHE_TTL_SEC`). That deploy shipped **its own tree's copy** of the
artifact — written `07:32:41` by the **pre-fix** scrape — and copying it reset the
mtime, so the deploy *extended the life of the stale contradiction* rather than
clearing it.

Production corrected only when the **09:21 scheduled refresh** regenerated the
artifact under post-merge code (`computedAt 09:21:47.977371`) and deploy
`32353505254` shipped that. Confirmed independently: the artifact on `main` carried
`n_simulations: 0` plus the `unsimulable` block from 09:21:47, before production
served it.

A merge-plus-green-deploy check would have passed at 09:28:55 with the defect still
live on the public API. That is the whole reason this row required L2 on the
deployed build.

## 4 · Residual, recorded rather than buried

`rosPlayoffOdds` reports `n_simulations: 0` with `playoffOdds: []` — truthful and
non-contradictory — but publishes **no** `unsimulable` block and no `simulated` flag,
so it does not NAME the reason its two siblings now share. Pre-existing, unchanged by
#956, and outside this row's stated close condition (which names
`championship.py:215`). Whether it warrants its own row is an owner call; it is not
folded into this verification.
