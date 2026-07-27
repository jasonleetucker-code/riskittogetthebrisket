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

## FR-3 — league TE premium (NEW, not yet wired)

**Version:** `te.league.2026-07-27.v1` · **Unit:** dimensionless multiplier, or `None`

```
OLD   1.0 + bonus_rec_te · _TEP_DERIVATION_SLOPE        (reads ONE key)

NEW   edge(key) = value(TE key) − max(value(WR key), value(RB key))
      no positive edge  →  multiplier = 1.0   (exact)
      any positive edge →  multiplier = None  + the measured edges
```

**Reason:** reading `bonus_rec_te` alone misses both directions. `bonus_fd_te = 1.0`
looks like a TE premium until you notice `bonus_fd_wr` and `bonus_fd_rb` are also 1.0.

**Evidence:** `config/league_intel/sleeper_league_snapshot_2026-07-26.json` — every
`bonus_rec_*` is 0.0 and every `bonus_fd_*` for a pass-catcher is 1.0. The operator's
measured 2026 TE premium is exactly **1.000**, corroborating `data_contract.py`'s own
retraction across all TE-touching keys rather than just the one.

**Why `None` rather than a number** when an edge exists: converting "+0.5 per reception"
into "TEs are worth X% more" needs per-player volume data the repo does not persist
(finding Q). Reporting the edge beats inventing a slope.

---

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
