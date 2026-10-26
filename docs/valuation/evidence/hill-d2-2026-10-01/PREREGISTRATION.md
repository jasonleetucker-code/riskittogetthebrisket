# Batch 3 Unit D2 — clean Hill rerun: preregistration

Owner directive (Batch 3 Section D): repair the Hill trainer/Autopilot first (done: #1588,
merge `9a921c372`), then run a clean preregistered rerun of four arms — **KTC native**,
**KTC c3**, **DLF Rank**, **DLF native spacing**. The open trainer questions H1/H2 (which
KTC board trains) and H3 (whether rank-voter native values train) are arms of this rerun,
not owner questions (session decision recorded in the task).

This document is committed **on its own, before any candidate result is computed**. Every
definition below is frozen. A change after results are seen is reported as a deviation
next to the original rule; the original is never silently replaced.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## 0. This evaluation does NOT authorize promotion

- Nothing here changes a Hill constant, a registry entry, a flag, a source role or a
  served value. No challenger is registered in `config/model_registry/` (an extra entry
  could enter the Autopilot tournament; `HILL_AUTOPILOT_V2.md` defines no sanctioned
  shadow-registration path). D2 is committed evidence only.
- Production Hill constants move only through Hill Autopilot's fail-closed path, or a
  human `scripts/model_registry.py promote` + `apply`. Hill constants are never
  hand-edited and `--override-scope` is never used.
- A BETTER verdict below makes an arm *eligible to be considered*. For c3 that still
  needs an owner source-role decision and a Lane C flag-gated implementation; for a
  trainer variant it needs the manifest change to be made through a reviewed PR and the
  Autopilot gates to pass on their own evidence.

## 1. What was already known when this was written (disclosed exposure)

Not blind. Before this file:

1. **Prior evidence on the same data.** `hill-alignment-2026-10-01` (one snapshot,
   2026-09-30) measured per-board Hill fits — KTC flattest (Crowd c 0.112 / s 0.91),
   OTC c 0.041 / s 1.01, DLF Values steepest (c 0.062 / s 1.69), live master 0.110 /
   1.110 — and recommended c3. `hill-trainer-repair-2026-10-01` reported, on one day's
   3-board split, champion 1108.7 vs repaired refit 555.8 mean RMSE. So the direction of
   Q2 (repaired master vs champion) on the current holdouts was known in advance on one
   day. This rerun's added value is point-in-time replay across ~4.5 months, forward
   targets, an ancestry-safe holdout and a block-bootstrap interval.
2. **Champion selection used OTC.** Champion v2 (c 0.1100 / s 1.110) was promoted
   2026-07-29 on a holdout win that included `OTCFFB` (991.7 RMSE on 2026-07-29 boards).
   The target board was therefore used once to *select* the champion. Sensitivity S3
   (§8) restricts to origins after that date.
3. **Computed while designing (no holdout score of any arm):** CSV history spans
   (git log, §3); the OFFENSE-only manifest hashes in §4; two OFFENSE-only replays
   (cutoffs 2026-05-20 and 2026-09-29) to time the pinned path — they returned M1
   masters (0.074, 1.17) and (0.067, 1.105). No arm was scored against any target.

## 2. Questions and arms (a bounded factorial — no other arm will be added)

Every arm is a **spacing function**: a map from a players-only rank (canonical percentile
coordinate, `PERCENTILE_REFERENCE_N = 500`) to a value on the 0–9999 scale.

| id | arm | spacing function | role |
|---|---|---|---|
| **C0** | champion | production OFFENSE master, c 0.1100 / s 1.110 (registry `hill_scope_masters` v2, `player_valuation.HILL_PERCENTILE_C/S`), constant over time | champion |
| **N1** | **KTC native** (Crowd TE++) | KTC Crowd TE++'s own players-only values, normalized top = 9999, at their own rank — exactly what a value-direct vote contributes | production behaviour for KTC rows |
| **c3** | **KTC c3** | Hill_OFFENSE at KTC's players-only rank (picks stay value-direct and are out of scope here). Under the champion master its spacing **is C0**; under a substrate-v2 master it is that master | challenger to N1 |
| **DLF Rank** | DLF votes rank → Hill | spacing is the master's (C0) | champion side of the DLF pair |
| **DLF native** | DLF Trade Analyzer values | `dlfValuesSfTep` native values | **BLOCKED** (§6) |
| **M1** | substrate-v2 refit, KTC **base** trains, rank-voter natives **on** | the repaired default OFFENSE trainer set | reference for H1/H3 |
| **M2** | KTC base, natives **off** (H3) | KTC base alone | H3 arm |
| **M3** | KTC **Crowd TE++** trains (H1), natives on | Crowd TE++ replaces base (same `ktcCrowd` family: one vote) | H1 arm |
| **M4** | Crowd TE++, natives off | H1 × H3 cell | secondary |
| M5–M8 | KTC **Trades** trains (H2): Trades alone / Crowd TE++ + Trades as two families, natives on/off | | **descriptive only** (§6) |

Factors: KTC trainer ∈ {base, Crowd TE++, Trades, Crowd+Trades} × rank-voter natives ∈
{on, off}. The 2×2 {base, Crowd TE++} × {on, off} is decision-eligible; the Trades levels
are not (history, §6).

**Decisive comparisons (exactly four):**

| id | question | reference | arm |
|---|---|---|---|
| **Q1** | KTC c3 vs KTC native | N1 | c3 under C0 |
| **Q2** | does the repaired substrate beat the champion? | C0 | M1 |
| **Q3** | H1: should Crowd TE++ train instead of base? | M1 | M3 |
| **Q4** | H3: should rank-voter native values stop training? | M1 | M2 |

## 3. Data, point in time

- **Origins** T: every UTC calendar day from **2026-05-15** (first OTC holdout version)
  onward, cutoff `T 23:59:59Z`, inputs from `training_run.commit_at_or_before(cutoff)`
  on `origin/main`. Nothing committed after the cutoff can be read.
- **Target day** T+h: the target board is materialized from
  `commit_at_or_before((T+h) 23:59:59Z)`. An origin is evaluable at h only if that
  commit exists and is on or before the last commit of the target CSV.
- **Fits** (M-arms): `training_run.replay(cutoff=…, manifest=<arm manifest>)` — the
  repaired trainer's pinned path, unchanged. Each run records `challengerHash`,
  `manifestHash`, `codeHash`, `pinsHash`, `evidenceHash`, `inputsCommit`.
- **Native arm N1**: `CSVs/site_raw/ktcSfTep.csv` at the origin commit, read through
  `training_manifest.load_board_values` (players only, positive values, descending).
  `ktcCrowdSfTep.csv` only exists from 2026-09-09; `ktcSfTep` is the historical capture
  of the same TE++ crowd values (lineage relation `ktc-historical-calibration-states`,
  classification proven). **Precondition P1**, checked mechanically before any score:
  on every date 2026-09-09 … 2026-09-30 where both files exist, at least 99% of
  name-matched player rows satisfy |v(ktcSfTep) − v(ktcCrowdSfTep)| ≤ 0.5. If P1
  fails, N1 and the Crowd TE++ trainer (M3/M4) are restricted to dates ≥ 2026-09-09,
  which makes Q1 and Q3 INSUFFICIENT.
- History available (committed CSV versions, distinct UTC days): `ktc` 168 (from
  04-16), `ktcSfTep` 157 (04-27), `ktcCrowdSfTep` 22 (09-09), `ktcTradesSfTep` 22
  (09-09), `dlfValuesSfTep` 7 (09-25), `otcffbSf` 128 (05-15 → 09-29), `fantasyCalc` 141,
  `pfkDynasty` 27 (07-25), `dynastyDaddySf` 168.

## 4. Training manifests (frozen)

Substrate version **2**, manifest schema 1, `FIT_TOP_N` 400. Default full manifest
(production refit): `1f31e6724c2b5a70ac073b44ccdc21ceef4433110beef434abb0053e66229b67`.

D2 fits OFFENSE only (`build_manifest(specs=<OFFENSE specs>)`; the default OFFENSE specs
plus the arm's KTC trainer; holdout specs FC/OTC/PFK/FN kept so their inputs are pinned).
OFFENSE-only manifest hashes against the registry at `3043d12b1`:

| arm | manifest hash | OFFENSE trainers |
|---|---|---|
| M1 | `14aabb24d4cf923663c0d18a0040cb78cd1ece305c190c326bad723e29433adf` | KTC, DynastyDaddy, DynastyNerds, YahooBoone, Fitzmaurice, DraftSharks |
| M2 | `b561959ff76f55e11a25852c16a543711e0f8a42be1692e36fae8bfb7781a85a` | KTC |
| M3 | `9601c948e5ac336e4d092ebf24c8490e8e058739f643bf42cba48884776963c0` | KTC-CrowdTEpp (`ktcSfTep`), + the five above |
| M4 | `d6ff34d460dc97180dc6e5e9934b2e35799e0ab057a389b7ad74e61424e4d7e7` | KTC-CrowdTEpp |
| M5 | `ad601099464afde3357f2f8bf0dfd6a921936ab14b411f69d6de20a8c9cd3576` | KTC-Trades + five |
| M6 | `e6e32c79699dd73d965388a809981d17a33879ba26aa2b5bcd23f1830851e0cb` | KTC-Trades |
| M7 | `79d76a0d1088066630fc34673242e0dd870a4aac44038e4eb7940681ccffa192` | KTC-CrowdTEpp, KTC-Trades + five |
| M8 | `c7876d74d1346894bac1269b51c87a351b79e52ce340f4e6868603dd02dec745` | KTC-CrowdTEpp, KTC-Trades |

`KTC-CrowdTEpp` is `BoardSpec("KTC-CrowdTEpp", "ktcSfTep", "OFFENSE", train, "value")`
with the manifest's own KTC base game-type evidence plus the lineage relation above
(`ktcSfTep` is not in the ranking registry, so the manifest requires cited evidence).
H3 off is `TrainingPolicy(allow_rank_voter_native_values=False)`. The run script asserts
these hashes and refuses to score if any differs.

## 5. Holdout: ancestry-safe, frozen

**Rule.** A board may be a target for a comparison only if no relation in
`config/sources/source_lineage.json` links it to any board whose spacing either compared
arm uses (a trainer of a master, or the native board), where a relation counts when it is
`proven`, `suspected`, or `measured` with a positive dependence in its latest recorded
measurement (the 2026-10-01 integrity sweep refresh). Same B10 family always counts.

| candidate | relation to the arms' spacing sources | status |
|---|---|---|
| PFK | `pfk-ktc-dependence` +0.687 vs KTC Crowd (measured); `pfk-ktc-suspected-ancestry` | **excluded** (every arm uses KTC) |
| FantasyCalc | `fc-dd-dependence` +0.635 vs Dynasty Daddy | **excluded** (DD trains C0, M1, M3) |
| Fantasy Navigator | `ktcCrowd` family; proven KTC data use | **excluded** |
| **OTC** (`otcffbSf`, column `value`) | `otc-fc-dependence` +0.511 is with FantasyCalc, which no arm uses. `otc-ktc-dependence` is recorded but **NOT REPRODUCED** on 2026-10-01 (−0.204 vs Crowd, −0.146 vs Trades; the earlier +0.891 came from a KTC-contaminated instrument). No relation to DD, Nerds, Boone, Fitzmaurice, DraftSharks or DLF | **the only target** |

Strict-reading disclosure: if a recorded-but-not-reproduced relation counted, OTC would
be excluded too and **no** ancestry-safe holdout would remain for any arm. That reading
admits no evaluation; it is stated, not run. The integrity sweep (audit C20) also notes
that OTC still votes in the live blend; that is irrelevant to this curve-level test and
stays OPEN.

## 6. Arms blocked or descriptive-only (decided now, before any result)

- **DLF native spacing — BLOCKED.** (a) `dlfValuesSfTep` has 7 committed days
  (2026-09-25 → 10-01); with ≥ 28-day blocks no interval is possible. (b) It is not in
  `_SOURCE_CSV_PATHS`, so the manifest refuses it as a trainer by construction, and the
  census classifies it non-voting; making it a voter or trainer is a source-role change
  outside D2 (it first needs `docs/sources/DLF_VALUES_GATE_2026-09-25.md` plus a
  registry entry with game-type evidence). Reported descriptively only: its curve RMSE
  vs OTC at h = 0 on the dates both exist, labelled non-decisive.
- **DLF Rank** therefore has no evaluable challenger; its spacing is the master's (C0)
  and it stays as it is. Its "verdict" is *not compared*.
- **H2 (KTC Trades trains; M5–M8) and KTC Trades native (N2) — descriptive only.**
  `ktcTradesSfTep` exists from 2026-09-09 (22 days, < one 28-day block). Their curves are
  fitted/scored on 2026-09-09+ and reported without a verdict.
- **Board-level c3 (leave-family-out future consensus on rebuilt boards) — not run.**
  The KTC Crowd/Trades voters exist only from 2026-09-09, so before then a today's-code
  replay has no KTC vote and N1 ≡ c3 on the board. 22 days cannot support the §7
  uncertainty method. The leave-family-out movement targets of `src/source_quality/`
  (β_gap, consensus lead) measure an observation's ORDER/level; c3 keeps KTC's order
  and changes only rank → value, so they are not applicable to the curve-level test.
- **IDP, picks.** No arm changes IDP spacing (all arms are OFFENSE) and c3 keeps pick
  votes value-direct: both are *not applicable*. Rookies: Q1's player-matched secondary
  (§8 S5) reports a rookie subgroup (`_yearsExp == 0` in the target-day snapshot).

## 7. Metric, horizons, uncertainty, decision rule

- **Primary metric**: the Autopilot holdout quantity on OTC — curve RMSE in value
  points between the arm's spacing function and OTC's players-only top-400 board
  (normalized top = 9999) at the same canonical percentile (`holdout._percentile_pairs`,
  `holdout.hill`). For N1 the function is KTC's own normalized value at the same rank
  index; indices past the shorter board are dropped, identically for both arms of a
  comparison. Per origin and comparison: Δ_t = RMSE_ref,t − RMSE_arm,t (> 0 ⇒ arm closer
  to the independent market's future spacing).
- **Horizons**: primary **h = 7** days; secondary h = 0 and h = 28.
- **Rank bands** (index into OTC's board): 1–50, 51–100, 101–200, 201–400; band RMSE
  differences reported per comparison.
- **Uncertainty**: circular moving-block bootstrap over the calendar series of daily Δ_t,
  block length **28 days** (the #1589 lesson), 4,000 resamples, seed 20261002. Report the
  mean Δ with a **98.75%** percentile interval (Bonferroni over the 4 decisive
  comparisons) and, for reading, the 95% interval.
- **Minimum sample** (else INSUFFICIENT): ≥ 84 evaluable origins at h = 7 spanning
  ≥ 84 calendar days (three block lengths).
- **Materiality margin** m = max(25, 0.05 × mean RMSE_ref) — the Autopilot's own
  `minCurrentImprovementPoints` / `minCurrentImprovementFraction`.
- **Verdict** per decisive comparison (h = 7, OTC):

  | verdict | rule |
  |---|---|
  | **BETTER** | lower98.75 > 0 **and** mean Δ ≥ m **and** mean Δ > 0 at h = 0 and at h = 28 **and** band Δ > 0 in ≥ 3 of 4 bands |
  | **WORSE** | upper98.75 < 0 |
  | **NOT BETTER** | not WORSE and upper98.75 < m (cannot be materially better) |
  | **INCONCLUSIVE** | anything else that meets the minimum sample |
  | **INSUFFICIENT** | minimum sample not met |

  Near-ties keep the reference. BETTER on Q2–Q4 is about the *trainer methodology*, not
  a specific constant pair.

## 8. Prespecified secondary analyses (report; never decide)

| id | analysis |
|---|---|
| S1 | Q1 with the c3 spacing taken from M1 instead of C0 (separates the substrate effect from the c3 effect) |
| S2 | M4 vs M1 (H1 × H3 cell); M2, M3, M4 each vs C0 |
| S3 | All four decisive comparisons restricted to origins T ≥ 2026-07-30 (after OTC was used to select C0) |
| S4 | Q1 on 2026-09-09+ with `ktcCrowdSfTep` itself as N1 (the live voter's own file) — descriptive, < 1 block |
| S5 | Q1 player-matched: for players in both KTC (T) and OTC (T+h), mean \|ln v_arm − ln v_OTC\|, where both arms use the player's KTC players-only rank; subgroups QB/RB/WR/TE (positions from the target-day snapshot `sleeper.positions`, joined by `resolve_canonical_name`) and rookies. TE is basis-confounded (KTC TE++ vs OTC base) and flagged |
| S6 | Descriptive (§6): M5–M8 vs M1 and N2 vs C0 on 2026-09-09+; DLF native vs C0 at h = 0 |

## 9. Reproducibility and verification

- Every M-arm run is re-replayed from its own recorded pins (`inputsCommit`, cutoff,
  arm manifest) and must reproduce the identical `challengerHash` and parameters. Any
  mismatch voids that arm's verdict.
- Compact run summaries (hashes, params, inputs commit, cutoff) are committed as JSONL
  in this directory; full run records are not (size), and every one replays from its
  summary.
- Results JSON records: code SHA and clean-tree flag, this file's sha256 and commit,
  manifest hashes, target blob sha256 per target day, P1 outcome, every verdict input.

## 10. Known limitations, stated in advance

- One target board. Generalization to one independent value market is a narrow
  question; it is not accuracy against reality (no ground truth for dynasty value).
- OTC publishes 0–100 values with ties; normalization to 9999 at its top is the
  holdout module's convention, applied identically to every arm.
- Spacing evaluated on the curve is not the published board: the blend, family cap,
  TE basis lift and tail policy sit downstream and are not replayed here.
- Most of the window is offseason and the NFL draft.
- Commit time bounds availability from above; dataset-state freshness is pinned by the
  run but does not enter the fit.
