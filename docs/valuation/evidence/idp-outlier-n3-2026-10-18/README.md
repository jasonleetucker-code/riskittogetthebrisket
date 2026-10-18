# IDP three-voter outlier challenger: evidence (2026-10-18)

`idp-hampel-n3-v1` (flag `idp_hampel_n3_challenger`, default **OFF**) is the served
per-player outlier filter, unchanged, with min n = 3 on IDP rows only. It was run
exactly as `PREREGISTRATION.md` declares. The preregistration was committed in
`16bdd11370` and is unchanged since.

Authority: owner closeout 2026-10-18, PART 2, Decision 1. **No flag was flipped, nothing
was promoted, and the DLF IDP vote hold stays.**

Every number below comes from archived inputs rebuilt through one replay code revision.
None of it is what production served on that day.

| file | what it is |
|---|---|
| `PREREGISTRATION.md` | frozen; untouched by this unit |
| `ARCHIVE_MANIFEST.json` | the frozen 140 / 105 board set |
| `evaluation_historical_replay.json` | primary, secondary horizons, S1–S8, D1 / D4, per-board census, structural guard |

## Preregistered verdict: INSUFFICIENT

The minimum sample needs three things at h = 7: ≥ 30 evaluable disputed row-origins,
≥ 10 origin days and ≥ 4 week-blocks.

| requirement | needed | observed |
|---|---|---|
| evaluable disputed row-origins | ≥ 30 | 117 |
| origin days | ≥ 10 | 17 |
| week-blocks | ≥ 4 | **3** |

The block requirement fails, so the verdict is **INSUFFICIENT**. PREREGISTRATION §6 says
what follows:

* this experiment is closed;
* the production filter is retained;
* the flag stays OFF;
* no follow-up variant is implied.

Under Decision 1, the DLF IDP voting hold stays.

### Why the sample is thin

The challenger can only disagree with the incumbent on IDP rows with exactly three
voters.

| period | IDP rows with n = 3 | rows with n ≥ 4 | challenger-only drops per board |
|---|---|---|---|
| 2026-08-18 → 08-23 | about 172 | 0 | about 36 |
| 2026-08-24 → 10-11 (the IDP Show combined board voted) | 67–105 | 169–218 | 0–1 |
| 2026-10-12 → 10-18 (IDP Show quarantined, DLF held) | about 225 | 0 | 31–32 |

* The October cluster has no target board 7 days later inside the frozen dataset. The
  newest board is 2026-10-18 11:47Z.
* So the h = 7 evaluation rests on the August cluster: 2026-08-18 → 08-20, plus one row
  per day through 09-03. That is 3 calendar blocks.
* Boards added after the freeze are excluded by the preregistration, so waiting does not
  change this experiment.

### What the numbers say (descriptive; they do not decide)

P1 is the mean of |ln V_ch − T1| − |ln V_inc − T1|. T1 is DLF IDP's own priced vote on
the target board, a holdout that votes in neither build. Positive means the challenger's
published value sits **further** from it.

| reading | n | P1 [95% CI] | blocks |
|---|---|---|---|
| **h = 7 (primary)** | 117 | **+0.1124 [+0.1009, +0.1274]** | 3 |
| h = 3 | 240 | +0.0693 [+0.0252, +0.1144] | 5 |
| h = 14 | 117 | +0.1112 [+0.1009, +0.1274] | 3 |
| h = 21 | 117 | +0.1041 [+0.1009, +0.1274] | 3 |
| S1, all 140 archives | 709 | +0.1241 [+0.1170, +0.1286] | 7 |
| S5, persistence (T1 on the origin board) | 333 | +0.0553 [+0.0230, +0.1139] | 5 |
| S6, T2 (other families' median; circular at n = 3, as declared) | 141 | −0.1045 [−0.1213, −0.0034] | 8 |
| S7, rookies excluded | 94 | +0.1241 | 1 |

Notes on the table:

* 93 of 117 primary units have P1 > 0.
* Every horizon's point estimate is positive. The challenger would not have met
  PROMOTION-ELIGIBLE even with more blocks: that needs P1 upper95 < 0 and P1 < 0 at
  2 of 3 secondary horizons. The direction is against it.
* S1 alone would read NOT BETTER (lower95 > 0). Sensitivities do not decide.
* S6 is negative, as PREREGISTRATION §5 predicted. At n = 3 the "other families" are the
  challenger's own two survivors, so it grades the rule by itself.
* S3 by family at h = 7:

  | family | n | P1 | blocks |
  |---|---|---|---|
  | DL | 70 | +0.1675 | 3 |
  | LB | 35 | +0.0108 | 1 |
  | DB | 12 | +0.0876 | 1 |

* S2 (episode-deduplicated, 46 units): +0.0987, 1 block.
* S8: every evaluable origin falls before the first board on which `idpShowCombined`
  carries zero weight (2026-10-12), so the "after" half is empty.

**D1 drop census.** Challenger-only drops over the 105 complete boards:

| breakdown | counts |
|---|---|
| by source | Draft Sharks IDP 450, IDP Trade Calculator 313, FantasyPros IDP 298 |
| by family | DL 580, LB 355, DB 126 |
| by incumbent consensus rank | 1–200: 535; 201–400: 459; 401–800: 53; unranked: 14 |

**D4.** The largest moves on the newest complete board (`20261018_114711`) reach
−40% / +35%. All 20 are in the JSON. Examples:

* CJ Allen: Draft Sharks dropped, 3,564 → 2,125.
* Abdul Carter: IDP Trade Calculator dropped, 3,960 → 2,494.
* Myles Garrett: Draft Sharks dropped, 3,938 → 5,331.

The filter drops whichever outer vote is asymmetric. Against DLF's later vote, those
drops more often move the row away than toward it.

## Implementation and pins

* **Code.** All 140 records were built at `58161d8e02` with a clean tree, one replay
  code revision, by `scripts/idp_evidence_challengers.py backfill` (two shards). The
  four builds per board are listed under `pins.builds` in each record.
* **Dataset.** All 105 complete manifest boards were recorded; the payload sha256 set is
  listed in the JSON.
  * One manifest board, `dynasty_export_20261004_085141.zip`, had been pruned from the
    working tree by archive retention after the freeze.
  * Its exact bytes were recovered from the commit that added it (`5a380eecb1`) and
    hash-checked against the manifest. It is the same board, not a substitute.
* **Seam.** In `src/api/data_contract.py`: the incumbent `_hampel_filter_per_player`,
  with `min_n = _IDP_HAMPEL_N3_MIN_N` (3) on `assetClass == "idp"` rows when the flag is
  ON. Every other filter challenger takes precedence.
* **Default path byte-identical.** `scripts/golden_board.py` was run on the newest
  archived payload at the base commit `3bc9cbfcec` and at the implementation. Both
  captures have sha256 `3c77f550…`, and
  `scripts/board_diff.py --expect-no-value-change` reports "no value changed".
  `tests/api/test_idp_hampel_n3_challenger.py` pins OFF == incumbent.
* **Structural guard.** On every board, rows outside the scope (non-IDP rows and IDP
  rows with n ≠ 3) must keep identical votes, drops and value. Result: **0
  violations**. The differences that did occur are the documented couplings:

  | coupling | rows (all boards) |
  |---|---|
  | board-wide ordinal fields only (rank, percentile, tier) | 29,239 |
  | current-year slot picks tethered to the merged rookie pool | 1,601 |
  | two-way player boost | 27 |

## Deviations and interpretations (stated so they can be challenged)

* **Structural guard scope.** PREREGISTRATION §3 says the out-of-scope rows must be
  "byte-identical". Taken literally, that cannot hold. Board rank, percentile and tier
  are board-wide ordinals, so any IDP value move re-ranks offense rows. Two documented
  post-blend couplings also carry IDP values onto other rows: the Phase 5.2b rookie-pool
  tether on current-year picks, and the two-way boost.

  The guard was therefore applied to what the rule can actually decide: votes, drops
  and value. The couplings are counted, not hidden. No definition in the decision rule
  changed.
* **The T1 board is chosen at read time.** `dlfIdp` is used, and `dlfRookieIdp` only
  when `dlfIdp` does not list the player. A DLF vote with zero freshness weight still
  carries its priced `valueContribution`, which is computed before the filter, and is
  used.
* **Recovered archive.** See Pins above.
* **The minimum-sample rule was applied as written.** It is not overridden by the large
  n or by the clearly positive point estimate.

## Disposition

* **Verdict: INSUFFICIENT.** The experiment is closed, the production filter is
  retained, and `idp_hampel_n3_challenger` stays OFF.
* **DLF IDP voting hold stays** (Decision 1). The board-impact validation that a PASS
  would have required is therefore not triggered.
* Nothing is promoted. No owner review is requested by the rule.

Reproduce (full git history; about 70 minutes on 2 cores):

```bash
python scripts/idp_evidence_challengers.py backfill --shard 0/2   # and --shard 1/2
python scripts/idp_evidence_challengers.py evaluate-n3 \
    --out docs/valuation/evidence/idp-outlier-n3-2026-10-18/evaluation_historical_replay.json
```

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c
