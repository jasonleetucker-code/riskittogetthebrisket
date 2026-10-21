# Low-value depth disclosure: shadow counters (LVA-P4)

**Status: implemented dormant. The flag is OFF and held OFF by the deploy gate.**
Nothing here displays a note, adds a payload field or changes a value, a verdict or a ranking.

**Authority:** owner decision 2026-10-21, LVA Package 4, "approved for shadow measurement only"
(`docs/owner/LVA_OWNER_DECISIONS_2026-10-21.md`). It chose V4:
- private only, with no public disclosure;
- rule A-guarded, with the guard kept;
- the floor threshold;
- picks included;
- calculator and War Room first;
- War Room Team Context held until #1890 is settled.

**Design:** `docs/trade/LOW_VALUE_DEPTH_DISCLOSURE_DESIGN_2026-10-20.md` §2–§3 (rule) and gate G3 in §10.

## What runs when the flag is ON

Flag: `low_value_depth_disclosure_shadow` (default OFF; `RISKIT_FEATURE_LOW_VALUE_DEPTH_DISCLOSURE_SHADOW`).

1. `server.py::_build_trade_simulation` finishes the simulation for `/api/trade/simulate` (surface
   `calculator`) or `/api/trade/analyze` (surface `war_room`). It then passes the finished result to
   `src/trade/depth_disclosure_shadow.record_evaluation`. The response does not read the return value,
   and the payload is byte-identical with the flag ON or OFF (`tests/trade/test_depth_disclosure_shadow.py`).
2. The owner module `src/trade/depth_disclosure.py` evaluates both teams:
   - `self` receives the simulation's `receiving` package;
   - `partner` receives its `sending` package.
3. The owner module reads every input from an existing owner:
   - **lines:** `waiver_values_by_position` (R_pos), the contract's optimal-lineup starters (S_pos),
     and `faab_engine.resolve_anchors(...).v_repl` (R_\*);
   - **fairness result:** `analyze_trade.equity_verdict` (the market lens's own definition), banded by
     `fairness_bands`;
   - **evaluability:** `trade_decision.asset_evidence_gaps`.
4. It refuses when it cannot decide. Missing lines, an unknown or stale piece, or a non-geom package
   model are counted as `not_evaluated` with their reason. They are never guessed.
5. It adds counts to `data/trade/depth_disclosure_shadow/<leagueKey>.json`. The store is box-local and
   gitignored, kept per UTC day and per surface, and retained for 180 days (`config/trade/depth_disclosure.json`).

**The store holds no player name, value, gap or line.** A test asserts this.

## Counters

| key | meaning |
|---|---|
| `trade.trades` / `trades.anyFire` / `trades.bothFire` / `trades.notEvaluated` | per evaluated trade |
| `<self\|partner>.evaluations` | team-sides evaluated |
| `outcome:shown` | the note would fire |
| `outcome:not_shown:no_low_value_depth` | no low-value extras received |
| `outcome:not_shown:result_does_not_depend` | extras present, but removing them does not change the region (correct suppression) |
| `outcome:not_shown:only_low_value_pieces` | dependence fired; the guard suppressed it |
| `outcome:not_evaluated:<reason>` | `lines_unavailable:*`, `unknown_piece:<gate>`, `result_unavailable:<gate>`, `one_sided`, `package_model_unavailable` |
| `candidates` | sides with low-value extras: the denominator for the false-positive proxies |
| `transition:<real>><without>` | fairness region with and without the extras (`against` / `fair` / `favour`), over candidates |
| `bandPair:<real>><without>` | band levels with and without the extras; `fair>slight` is a band-edge cliff fire |
| `fire.pieces:<offense\|idp\|pick>`, `fire.mix:*`, `fire.extraCount:*`, `fire.shape:<rcv>for<gv>`, `fire.transition:*`, `fire.bandPair:*` | composition of the fires |
| `bandVersions` | the fairness-band version each evaluation ran under |

**False positives can only be measured as proxies.** No user or outcome evidence exists. The proxies are:
- fires against candidates, which gives specificity;
- the guard-suppressed count;
- the band-edge share of fires (`fire.bandPair:fair>slight`);
- fires whose real result is already not fair (`fire.transition:favour>*`).

## How the counters are read once the owner enables the flag

Turning the flag on is the owner's G3 shadow-window decision.
`scripts/verify_owner_held_flags.py` fails a deploy whose live process has it ON, and
`tests/api/test_depth_disclosure_shadow_hold_locked.py` locks the default. To activate, one reviewed PR
carrying the owner's approval must:
1. move the required state in `scripts/verify_owner_held_flags.py` to ON;
2. update the lock test;
3. set the env var on the box.

Then the counters are read privately:

```
GET /api/trade/depth-disclosure-shadow?leagueKey=dynasty_main[&days=N]
```

The route has these access rules:
- **404** while the flag is OFF, the same answer as an unknown route;
- **401** without a session;
- **403** unless the session is an allowlisted admin;
- **403** (`league_membership_required`) unless the session's team is on a roster of the requested
  league in the loaded contract. Unprovable membership is refused.

The route is not under `/api/public`, and the frontend has no bridge route for it. The response
carries the per-day blocks and a `totals` roll-up per surface. On the box, the JSON file can also be
read directly.

## Not done here (named follow-ups)

- **War Room Team Context integration:** held until #1890 is settled (OD-9).
- **Trade Finder, Trade History and `analyze-multi`:** not counted. The owner chose calculator and
  War Room first.
- **Analyze in-flight sharing:** identical in-flight Analyze requests share one computation, so they
  count once.
- **Display:** the display decision is separate and not authorized (G4/G5).
