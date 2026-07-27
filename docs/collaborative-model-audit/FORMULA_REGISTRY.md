# Formula registry

Every formula or constant this audit changed, with the evidence that justified it.
Version tags follow the repo convention (`<workstream>.<date>.v<n>`).

---

## FR-1 — ROS projection branch

**Version:** `ros.aggregate.2026-07-27.v1` · **Unit:** unchanged (0–100 index)

```
OLD   if row.projection_value is not None and row.projection_value > 0:
          score = rank_to_score(row.rank, row.total_ranked)
      else:
          score = rank_to_score(row.rank, row.total_ranked)

NEW   score = rank_to_score(row.rank, row.total_ranked)
```

**Reason:** the branches were byte-identical. **No behaviour change** — this is the
point. The branch made a live discard look like a decision the code was already making.

**Evidence:** mutation-tested. Making the first branch actually consume the projection
fails all three behavioural tests in
`tests/ros/test_projection_value_is_not_consumed.py`, proving they are not vacuous.

---

## FR-2 — KTC TE++ uplift curve (NEW, not yet wired)

**Version:** `te.uplift.2026-07-27.v1` · **Unit:** dimensionless ratio, ≥ 1.0
**Config:** `config/weights/te_premium_curve.json` · **Fitter:** `scripts/audit/fit_ktc_tep_curve.py`

```
NEW   uplift(v) = max(floor, 1 + a · v^(−k))
      a = 43.555794   k = 0.632839   floor = 1.2092
```

**Evidence:** 73 TEs appearing on both `CSVs/site_raw/ktc.csv` (base SF) and
`ktcSfTep.csv` (TE++ level 2) — same publisher, same players, same date, so the
difference *is* KTC's TE-premium adjustment with no modelling assumption needed to
identify it. R² 0.941 in log space, median ratio error 0.023.

**Rejected alternatives, recorded because they were tried:**

| form | statistic | why rejected |
|---|---|---|
| additive `tepp − base = c` | CV 0.304 | delta falls from 1133 to 516 across the board |
| multiplicative `tepp/base = c` | CV 0.134 | ratio rises 1.209 → 2.053 |
| log-linear on the ratio | R² 0.82 | **predicts ratio 0.938 at the top** — a TE premium that lowers a TE's value |

The power form was chosen because it is the only candidate that is monotone and bounded
below by 1.0 *by construction*. Constraining the form was worth the R² it cost.

**The floor** is the observed minimum ratio. The unconstrained fit reads 1.146 at the
most valuable TE against an observed 1.209 — a smooth curve through 73 points cannot
also honour its own endpoint. Clamping to the observed minimum is a measured bound.

**Known limitation:** measured within KTC's board. Applying it to another publisher
assumes their TEs sit at a comparable base.

---

## FR-3 — league TE demand (NEW, not yet wired)

**Version:** `te.demand.2026-07-27.v2` · **Returns:** a target *basis*, never a multiplier

```
v1 (WRONG)  edge(key) = TE key - max(WR key, RB key)
            no positive edge -> multiplier = 1.0

v2          required_te = count of TE in roster_positions
            basis   = tepp  if required_te >= 2
                      teppp if required_te >= 3
                      base  otherwise
            scoring edge can RAISE the basis one step; never lower it
```

**Why v1 was wrong.** It measured the scoring *mechanism* and called it the *demand*.
The league starts two mandatory tight ends and allows TE in both FLEX and SUPER_FLEX;
that demand exists whether or not receptions pay extra. v1's answer (premium = 1.000)
implied translating TE values DOWN off a basis they belong on.

**Evidence:** `roster_positions` contains `TE, TE`; `flexEligible` and `sflexEligible`
both include TE. Scoring measured separately and adds nothing here — but is no longer
able to subtract.

**Provenance note:** the "2 required TE → TE++" mapping encodes an operator-supplied
domain fact about what KTC's TE++ setting targets. It is recorded as an assumption, not
dressed up as something this repo measured. The measurable half — the roster requirement
— is read directly from the league.

---

## FR-3b — `convert_te_value` (NEW): the double-count guard

**Version:** `te.convert.2026-07-27.v1`

```
convert_te_value(v, from_basis, to_basis)
    from == to              -> v unchanged        (no-op)
    base -> tepp            -> v * uplift(v)
    tepp -> base            -> numeric inverse of the above
    any other pair          -> raises
    unknown basis           -> raises
```

**Why a basis API rather than a multiplier.** Two multiplications always compound; two
conversions between named bases cannot, because the second call sees `from == to`. The
guard is structural rather than a matter of discipline.

This matters specifically because `ktcSfTep` is *already* on `tepp`. Under a multiplier
API, lifting "all TE sources" would hit it twice. Under this one, asking to put a `tepp`
value on `tepp` returns it untouched.

Unmeasured pairs raise rather than interpolating. Only `base <-> tepp` is fitted, from
KTC's own two boards; inventing an intermediate uplift for `tep` or `teppp` would be the
kind of unmeasured number this audit exists to remove.

**Verified:** `base 8169 -> tepp` gives 9878, matching Brock Bowers' real KTC pair
(8169 / 9878). Round-trip returns the original.

## FR-4 — finder value source (F-6)

**Version:** `finder.value.2026-07-27.v1` · **Unit:** 1–9999 board value (was raw composite)

```
OLD   model = _finalAdjusted ?? _rawComposite ?? _rawMarketValue ?? _composite
      if source_count == 1: model *= 0.88

NEW   model = rankDerivedValue          (from contract playersArray)
      no local haircut — the 0.30 retention arrives baked in
      assets with no board value are DROPPED and counted
```

**Evidence:** `results/F-6-migration-result.md`. Independently reproduced PR #567:
803 paired assets, median ratio k = 0.875.

The legacy path is retained for fixtures and raw-payload callers, and keeps its 0.88 —
renamed `_LEGACY_SINGLE_SOURCE_DISCOUNT` to say so. Deleting it outright, as an earlier
reading of F-6 proposed, would have left single-source assets undiscounted there.

---

## FR-5 — finder thresholds

**Version:** `finder.thresholds.2026-07-27.v1`

| constant | old | new | basis |
|---|---|---|---|
| `MIN_ASSET_VALUE` | 800 | 700 | × k = 0.875 |
| `JUNK_THRESHOLD` | 400 | 350 | × k |
| `ELITE_THRESHOLD` | 7500 | 6600 | × k |
| `MAX_BOARD_LOSS` | −200 | −175 | × k |
| `MIN_MARKET_VALUE` | 500 | **500** | gates market values — not rescaled |

**Percentile-matching was tried and rejected.** Degenerate at the low end:
`MIN_ASSET_VALUE` sits at the 99.25th percentile of the paired pool and
`JUNK_THRESHOLD` at the 100th, so percentile equivalence maps both to ~900 and collapses
two gates with different jobs. It also conflates the scale change with a population
change (composite prices 1077 assets, board 812).

---

## FR-6 — finder summary sign

**Version:** `finder.summary.2026-07-27.v1`

```
OLD   f"{label}: you gain {board_delta:,} board value (+{pct:.0%})"
NEW   verb = "you gain" if board_delta >= 0 else "you give up"
      f"{label}: {verb} {abs(board_delta):,} board value ({pct:+.0%})"
```

**Reason:** a −100 delta rendered as *"you gain -100 board value (+-2%)"*. Unreachable
today (the output filter requires `board_delta > 0`) but the formatter must not be the
only thing preventing a loss from being described as a win.

---

## FR-7 — partner fit reachable bounds (NEW)

**Version:** `partner.bounds.2026-07-27.v1` · **Unit:** same 0–100 field, bounds published

```
NEW   FIT_SCORE_REACHABLE_MIN = 7.24
      FIT_SCORE_REACHABLE_MAX = 43.12
```

**Derived, not declared** — computed from `_EVIDENCE_CONFIDENCE`, the logit caps and
`BASE_ACCEPTANCE_PRIOR`, so moving a cap moves the published range automatically.
Cross-checked against an independent exhaustive sweep in
`tests/roster_intel/test_partner_reachable_range.py`; both give 7.24 / 43.12.

**Reason:** the field is nominally 0–100 and its top 57% is unreachable, because
`DECISION_CALIBRATED` confidence needs rejection data Sleeper does not expose.
`MAX_CONFIDENCE_WITHOUT_DECISION_DATA = 0.45` never binds — the real ceiling is 0.40.

**Not rescaled to 0–100 deliberately.** Rescaling would make a thin-evidence score
*look* strong, which inverts the module's design intent.

---

## FR-8 — window output naming

**Version:** `window.naming.2026-07-27.v1` · **Unit:** normalized affinities (unchanged)

```
OLD   {"probabilities": ...}
NEW   {"affinities": ..., "probabilities": ...}   # alias, one release
```

**Reason:** these are softmaxed negative squared distances to five hand-placed anchors.
Summing to 1 does not make a distribution a probability — no anchor, axis weight or
temperature was fitted to an observed outcome. Arithmetic unchanged; only the claim.

Also restored `notes` to `gameplan.py`'s projection, which had been dropping the
"no state cleared 30%" and proxy-source signals.

---

## Renames (no arithmetic change)

| old | new | why |
|---|---|---|
| `marginalPoints` | `marginalStrengthIndex` | not points; a difference of two lineup solves weighted by a 0–100 rank index |
| `PositionProfile.replacement_gap` | `replacement_level` | held a level; `partner.py` already consumed it as one |
| `SINGLE_SOURCE_DISCOUNT` | `_LEGACY_SINGLE_SOURCE_DISCOUNT` | applies only to the legacy composite path |

All three keep their old key as a deprecated alias for one release.
