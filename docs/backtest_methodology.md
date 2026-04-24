# Backtest Methodology — Dynamic Source Weights

**Status:** Shipped 2026-04-24 (Phase 10 of the 2026-04 upgrade).
Behind feature flag `dynamic_source_weights` — currently **OFF**
by default.

## Goal

Replace the static per-source weights in `config/weights/` with
weights fit against each source's historical rank-accuracy, so
sources that predict well earn more influence in the blend and
sources that predict poorly earn less.

## Ground-truth definition

We use **end-of-season realized fantasy points in each league's
scoring format** as the realized-accuracy signal. For dynasty,
this is imperfect (dynasty value is multi-season), but it's the
most objective signal we have available and is consistent with
how the redraft and dynasty fantasy analytics literature (FFA-R,
nflverse) measures source accuracy.

**Alternative signals considered, not used:**
- End-of-season PFF dynasty rank — proprietary, not reliably
  fetchable.
- Final DLF Dynasty ADP — circular (one of our input sources).
- Change in canonical consensus rank — also circular.

The choice is documented here rather than embedded in code so
the rationale survives future code rewrites.

## Pipeline

1. **Inputs per evaluation cycle:**
   - `source_ranks_by_source`: `{source: {player_id: rank}}`
   - `realized_points`: `{player_id: total_fantasy_points}`
     — computed from `src/nfl_data/realized_points.py` aggregated
     across the season.

2. **Score per source** (`src/backtesting/correlation.py`):
   - Spearman rho between `-rank` and `points` across players
     present in both.
   - Top-50 hit rate (fraction of source's top-50 that ended in
     realized top-50).
   - Minimum `n_players = 40` to avoid a source with sparse
     coverage earning a big weight.

3. **Propose weights**
   (`src/backtesting/dynamic_weights.propose_weights`):
   - Raw weights via shifted softmax on Spearman rho.
   - Floor at 0.05 per source — no source goes to zero without a
     human decision.
   - Smooth with 4-week EMA (`alpha=0.25`) against the prior
     `dynamic_source_weights.json`.
   - **Approval gate:** if any single source's weight drift
     > 15%, return `status="pending_approval"` and DO NOT
     overwrite the live weights. The monthly-refit cron opens
     a PR at this point instead.

4. **Consumption at serve time:**
   - `dynamic_source_weights` flag OFF → existing static weights
     in `config/weights/` are used verbatim.
   - Flag ON → blend layer reads
     `config/weights/dynamic_source_weights.json`. Absence of
     this file silently falls back to static.

## Cadence

- **Monthly refit** (cron): compute new weights, write JSON if
  auto-approved, open PR if drift exceeds gate.
- **Manual refit** for explicit events (mid-season pivot,
  source shutdown, etc.): same script, manual invocation.
- **No in-season weekly refit** for now — weekly noise is high
  enough that month-over-month smoothing is appropriate.

## Risk + mitigations

| Risk | Mitigation |
|---|---|
| Ground-truth definition is debatable | Locked in this doc; change requires an ADR |
| Weights swing wildly month-to-month | 4-week EMA + 15% approval gate |
| Brand-new source dominates on first refit | `_MIN_N_PLAYERS = 40` gate |
| Source weight going to zero accidentally | `floor = 0.05` per source |
| Backtest data is incomplete | Score_source returns (0.0, 0.0) + logs; never crashes |
| Weights update silently in prod | Feature flag + PR-gated deploy |

## Flag flip plan

1. Land the code. Flag OFF. (Phase 10 of 2026-04 upgrade — this PR.)
2. Run refit script offline monthly for 2–3 cycles. Review the
   proposed weights vs. static weights. Verify outputs look
   sensible (Spearman rho above noise floor, no source crushed).
3. Flip flag ON in staging. A/B rankings delta between static vs
   dynamic via `tools/rankings-diff` (to be built if it doesn't
   exist yet). If delta is small + in expected direction, ship
   to prod with flag ON.
4. Monitor `/api/status` for the `dynamic_source_weights.meta`
   section post-flip to confirm the weights loaded are the
   intended ones.

## Reversibility

Setting `RISKIT_FEATURE_DYNAMIC_SOURCE_WEIGHTS=0` at the
systemd unit level reverts to static weights on the next
process bounce. No code rollback required.
