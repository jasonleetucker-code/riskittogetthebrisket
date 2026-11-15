# FAAB integrity verification — CW-10, 2026-11-06

Re-test of five August master-audit findings, plus AMATH-S27 and IST-7, against
the CURRENT canonical owner (`src/trade/faab_engine.py`, config
`config/trade/faab.json`). The audits' stored reproductions were rotted or unsafe
to re-run, so each finding is restated as the **invariant** it violated and
asserted on small synthetic leagues (convex 700-row board, no network, no live
board).

Tests: `tests/trade/test_faab_integrity_invariants.py`,
`tests/trade/test_faab_config_integrity.py`,
`tests/api/test_faab_integrity_surfaces.py`.

## Summary

| Finding | Verdict | Proving tests |
|---|---|---|
| W10-F001 bids ignore remaining budget | **NOT_APPLICABLE** (audited code is /draft's `draft-logic.js`, not FAAB); the FAAB invariant is **FIXED / holds** | `TestW10F001BidsRespectTheBalance`, `TestDeskRoute::test_the_figure_never_exceeds_the_teams_balance` |
| W11-F003 saturation | **FIXED** (formula replaced) | `TestW11F003NoSaturationAtThePoolTop` |
| W11-F004 non-monotonic outputs | **FIXED** as audited; **a narrow, by-design exception is pinned** | `TestW11F004Monotonicity` |
| W11-F005 bids depend on UI/filter state | **FIXED** (client port deleted; server inputs pinned) | `TestW11F005BidsAreNotAFunctionOfDisplayState`, `TestTheClientHoldsNoBidArithmetic` |
| W11-F007 inconsistent dollar figures | **FIXED** (one engine) | `TestW11F007OneEngineOneFigure`, `TestDeskRoute` |
| AMATH-S27 fail-closed config | **STILL_PRESENT, now fixed in this PR** | `test_faab_config_integrity.py`, `TestBrokenConfigIsARefusalAtTheRoute` |
| IST-7 current-week / season phase | **FIXED (verified)** | `TestIST7SeasonPhase` |

No finding other than AMATH-S27 reproduced, so the only engine change is the
config loader. **Measured effect on live recommendations: none.** 150 seeded
scenarios x 40 values (6,000 full `recommend()` payloads: random rivals, balance,
need, posture, week) from `origin/main`'s engine and this branch's engine are
byte-identical as JSON.

## W10-F001 — bids ignore the remaining budget

The finding is about `frontend/lib/draft-logic.js` (the /draft auction ladder:
`myMaxBid`, `myWinningBid`), which is not the FAAB engine and is out of this
lane. The FAAB analogue — *a recommendation may exceed what the team can pay* —
does not hold in the engine:

- every rung satisfies `0 <= conservative <= recommended <= aggressive <=
  maxRational <= max(0, remaining)` for balances `-7, 0, 1, 2, 3, 5, 17, 100,
  250`, all three postures, 13 values from 0 to 9999;
- `maxRational` equals the documented `min(R, floor(max(teamRaw$, team$)))`;
- a broke team gets `$0`, `pctOfRemaining: null` (never 0%), a "no FAAB left"
  warning, and still the market clearing price;
- unknown balance (`None`) falls back to the original budget while a KNOWN `$0`
  stays `$0` (MISSING != 0 in both directions);
- the balance is only a cap: on the dense bid grid (balance <= $40) a larger
  balance never lowers the bid;
- the **objective** block (worth) is identical across balance, need, status,
  posture, rivals, drop side, trending and crowd evidence.

The /draft symptom (`draft-logic.js` ignoring `myRemaining`) is **not** covered
here and was not re-tested; it belongs to the draft lane.

## W11-F003 — saturation at the top of the free-agent pool

The audited formula (`value / max(value, best free agent)` in `waiver.py`) is
gone. The ceiling is anchored to league-format values: replacement is worth `0`,
the all-in line is worth the whole original budget, strictly increasing in
between, and the uncapped raw ceiling keeps separating players above the all-in
line up to `rawCeilingCap`. Pinned: players above the best free agent are priced
distinctly; an elite player out-bids an all-in-line player; a weaker wire never
makes the same player worth less than a stronger one.

## W11-F004 — non-monotonic outputs

The 0.5-weight position blend and trending kicker in `faab_recommender.py` that
produced 8,362 inverted pairs no longer exist. Pinned as promised by the model:

- objective dollars / %, team ceiling and `maxRational` are monotone in value;
- conservative, recommended, aggressive and clearing are monotone in value at a
  $100 balance;
- across 60 seeded random leagues (rivals, needs, posture, crowd, trending, drop
  side, week) the recommendation is monotone at balance >= $8 (an empirical
  regression pin of the shipped calibration, not a stronger promise).

**Where monotonicity is NOT promised** (found by sweep, 5 of 20,000 sampled
recommendations): with a balance of $1-$2 the recommended bid can fall from `$1`
to `$0` as value rises. The recommendation is the cheapest bid within `minEdge`
of the expected-surplus argmax; a hotter player draws rivals who out-bid any
`$1`, so `P(win|$1)` collapses onto `P(win|$0)` and the cheaper claim wins the
argmax. Never above the balance, always a drop to `$0`. Pinned as
`test_recommended_can_fall_to_zero_on_a_nearly_empty_balance_and_that_is_the_model`
rather than "fixed", because forcing monotonicity would contradict the documented
argmax. The docs (`faab-model.md` Stage E) do not claim monotone recommendations.

## W11-F005 / W11-F007 — UI state and surface parity

`computeFaabHint` and the filtered-list `topAddValue` denominator are deleted
(source guards in `TestTheClientHoldsNoBidArithmetic`; the renderer
`WaiverBidFigure.jsx` carries no cap/scale/floor and `waiver-faab.js` is a
verbatim join, also covered by the existing `frontend/__tests__/waiver-faab.test.js`).
Server-side, the only display-shaped inputs are page size, row order and the
`by_family` regrouping; none moves a figure. The engine's signatures take no
filter/sort/page parameter.

Both surfaces call `engine.recommend`: the desk's `standard` / `conservative` /
`aggressive` / `max` equal `bids.recommended` / `conservative` / `aggressive` /
`maxRational`, and a spy over `find_waiver_targets` shows each list figure is the
engine's return capped at the balance, with `clearing`, `maxRational` and
`objectiveDollars` verbatim.

One real residual, documented and NOT changed: `find_waiver_targets` resolves
the replacement anchor from the unrostered pool it is asked about
(`replacementLivePoolRank` / `Weight`), so request parameters that redefine the
pool (`minValue`, `includeKicker`) can move the anchor and with it every bid.
That is the documented live-pool anchor, not display state; the position
dropdown never reaches the backend.

## AMATH-S27 — fail-closed config, inert keys

**Was present**: `load_faab_config` returned `{}` for a missing file; any missing
key silently took an in-code default via `FaabConfig.num`.

**Done here** (`faab_engine.py`): `FaabConfigError`, `validate_faab_config`,
`CONFIG_SCHEMA_VERSION`. The load boundary (cached shipped config, explicit
`path`, and an explicit `FaabConfig(raw)`) refuses a missing file, bad JSON,
non-object, missing section or key, wrong type, out-of-range value
(`unit` in [0,1], `pos` > 0, non-finite, inverted `aggressionClamp`, unknown
`defaultRiskPosture`) and a `schemaVersion` mismatch, naming **every**
`section.key` at once. `server.py::_faab_config_refusal` turns it into
`503 {"error": "faab_config_invalid", "message": ...}` on `/api/waiver/faab-recommend`,
`/api/waiver/suggestions` and `/api/waiver/perfect`; no figure is quoted.

**Inert keys**: the four named in `faab-model.md` §10.8 are already gone
(`regularSeasonWeeks`, `defaultPlayoffWeekStart` deleted; `applyToObjectiveValue`
and `unknownBalanceAssumption` renamed `_invariantNotAToggle_*`). `schemaVersion`
was the one remaining unread key; it is now a validated named invariant. A test
fails if any non-underscore config key is read by nothing, if a read key is not
validated, or if a validated key is absent from the file. The divergent in-code
defaults in §10.7 are already reconciled (`test_faab_config_parity.py`); they are
now also unreachable. `docs/faab-model.md` §10.7-10.9 are partly stale as a result
(left untouched, owner-record doc; follow-up: reconcile).

## IST-7 — current week / season phase

Verified, not changed. `find_waiver_targets` builds `LeagueContext` from
`current_nfl_week(today)` and the league's own `playoff_week_start`, the same
owner functions the desk uses (source guard). Pinned: the season clock at its
boundaries (Wed before kickoff = offseason, Thu after Labor Day = week 1, Tuesday
run resolves to the week just finished, week 18 last, week 19 = offseason); option
value rises through the season with offseason lowest and a league's earlier
playoff start brings the final waiver period earlier; list bids for an elite free
agent satisfy offseason <= week 1 <= final waiver period, and week 1 is not priced
with the offseason factor.
