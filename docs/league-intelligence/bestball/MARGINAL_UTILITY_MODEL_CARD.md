# Marginal Best-Ball Utility — model card (v1, shadow / offline)

**Status:** library code plus an offline report. **Nothing is served.** No
production module imports `src.bestball` (pinned by
`tests/bestball/test_import_graph.py`). This card does not authorize
promotion, a request-path use, or any change to a canonical value.

**Owner directive:** League Intelligence & Trade Decision Engine (2026-10-19),
§7 "Implement true best-ball player utility".

## 1. What it measures

For one rostered player `p` on roster `R`, under one league's exact starting
slots and best-ball rule:

```
MBU(p) = F(R) − F(R − {p} + {best free claim})
F(X)   = E[ optimal legal weekly lineup score | roster X ]
```

Unit: expected best-ball points per week under the league's exact scoring.
Positive means the roster is better with the player than with the best free
replacement. Negative is allowed: a free agent can be better than a deep bench
player.

It is a **roster-conditional utility**, not a value. It never reads, writes or
adjusts `rankDerivedValue`, and it is not the withdrawn league-adjusted lens.

## 2. How it is computed

Everything goes through the public API of existing owners. Nothing is
re-implemented.

| step | owner |
|---|---|
| weekly draws, exact lineup solve per draw, paired before/after comparison, availability calendar, before-side reuse | `src.roster_intel.best_ball_utility.evaluate_trade_utility` |
| slot eligibility, opened slot families | `src.ros.lineup.precompute_slot_eligibility`, `normalize_slot` |
| who is rostered (league-wide) | `src.draft.context.league_rostered_keys` |
| who is in the live rookie auction | `src.draft.rookie_pool.auction_rookie_keys` |
| free-agent league-scored ppg | `src.roster_intel.best_ball_utility.league_scored_ppg_by_id` |
| weekly variance | `src.league_intel.sim_calibration.PointsModel.draw_from_mean` |

The steps:

1. **Opened slot families.** The removed player's eligible starting slots,
   collapsed to distinct slot names. For example, a WR in dynasty_main opens
   `WR`, `FLEX` and `SUPER_FLEX`.
2. **Candidates.** For each opened family, the top `candidatesPerSlotFamily`
   priced free agents eligible for it. The cap bounds cost only.
3. **The re-solve decides.** Each candidate is simulated as the claim. The
   candidate whose roster scores best is the replacement.
4. **Labelled replacement.** The vacated spot is filled by one of three
   labelled choices:
   - `waiver_free_agent`: the best simulated claim.
   - `internal_promotion_only`: the best claim adds no usable points, so
     rostered depth absorbs the slot.
   - `none_available`: no priced free agent is eligible. The spot is empty, and
     the label says so.
5. **Publish.** `deltaPpg`, `mcStandardError` and
   `precisionOk = mcStandardError ≤ band / 2`.

## 3. Inputs and their status

| input | status today |
|---|---|
| per-player ppg | league-scored full-season ROS ensemble per-game rate (trade path basis). A per-game rate, not a weekly projection |
| weekly variance | `PointsModel`. The calibration artifact `data/league_intel/sim_points_model.json` is not tracked, so a fresh tree uses the **fallback constants**: a Gaussian with per-position CV, truncated at zero. This is a PRIOR, not a fitted predictive distribution |
| availability | optional `weeks` plus per-player week states from `src.ros.availability`. `unavailable` removes a player from that week. `uncertain` stays in the pool and is reported |
| waiver universe | the contract's `playersArray`. A player Sleeper lists with no board row is not offered, which can only make the pool thinner (marginal larger) |
| parameters | `config/bestball/marginal_v1.json`. All values are PRIORs: draws 400 and seed 1173 (inherited, pinned equal to the owner's defaults), 1 candidate per family, materiality 1.0 ppg, test draws 30. The `paramSetId` is a content hash minted at load time |

## 4. Assumptions, stated rather than hidden

- **Independence.** Player weeks are drawn independently. There is no
  same-game, same-team or weather correlation, and no stat-level coherence.
  Best-ball utility of a stack is therefore not represented.
- **Truncated-Gaussian weeks on fallback constants.** No fitted predictive
  distribution exists yet.
- **No predictive uncertainty.** `predictiveBasis` is `unavailable` and
  `predictiveSd` is `null`. `mcStandardError` measures only how precise this
  one estimate is. It is not uncertainty about the player's season, and no
  probability is derived from it anywhere in the package.
- **Materiality band.** `materialityPpg` (1.0) alone. It does not depend on the
  draw count, so more draws tighten precision but can never manufacture a
  material result.
- **Free waiver claim.** `costAssumption: free_waiver_claim_unmodelled_faab`.
  FAAB price and rival claims are not modelled. The team is evaluated in
  isolation (`contested: false`). Joint allocation of contested free agents
  across both sides of a trade is PR-2.
- **Horizon.** Current season only. There is no aging, no multi-season value
  and no dynasty horizon (PR-3).
- **Selection.** Choosing the best of K simulated candidates on the same draws
  is a max over noisy estimates. It slightly favours the replacement, which
  biases `deltaPpg` down (the conservative direction). K is 1-3 per player by
  default.
- **Missing is never zero.**
  - An unprojected player's marginal is `unavailable` (`player_unprojected`),
    never 0.
  - An unprojected free agent is listed `unpriced`, never a candidate at 0.
  - An unpriced waiver pool makes the marginal `partial`, measured against an
    empty spot and labelled as an upper bound.

## 5. Costs (measured, synthetic fixture)

`python scripts/bestball_marginal_report.py` runs one 58-man team of the
synthetic dynasty_main-shaped league (21 slots) at 400 draws. Each player costs
1 before roster plus K candidate after-rosters, and the before roster is reused
across the whole team through the owner's content-addressed cache. First
measurement on a shared dev box:

- 58 players, 103 after-runs (161 rosters including before);
- about 39 s wall clock (16 s CPU);
- about 0.38 s per after-run, which includes the owner's per-run depth
  scenarios.

Re-measure with `--no-reuse` to see the cost without before-side reuse. These
numbers size a future precompute (PR-4). They are not a request-path budget,
and this package is not on a request path.

## 6. Validation status

**None yet. This is a challenger without evidence.** The preregistered primary
metric (promotion-gates outline) is the rank correlation of predicted against
realized forward-week lineup delta from leave-one-out on our own rosters.
Secondary: points-space replacement error per position, compared with the
rosValue-means champion. No holdout has been examined.

## 7. Not in this version (named follow-ups)

- PR-2: `trade_delta`. Two-sided lineup deltas, joint waiver allocation,
  forced releases from `roster_capacity.forced_drop_cost`, and two-level
  predictive draws once a projection-error model exists.
- PR-3: `horizon`. Aging curves, player horizon and team horizon expectation.
- PR-4: provider Protocols plus a precompute artifact spec (box timer, own
  MemoryMax).
- `competitive.championship_delta` stays `unavailable`. The playoff presim
  runs on the rosValue index, not league-scored ppg, and Owner Decision 11 is
  pending.
