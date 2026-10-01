# Hill / native-source alignment audit (V2-5), 2026-10-01

**Status:** read-only analysis. This changes no Hill constant, model-registry entry, weight
or `data_contract` code. Any numeric calibration it points to is a **challenger** for the
Hill Autopilot / model registry. This audit does not create one.

## 1. Declared metrics and acceptance criteria

This section was committed **before any candidate was computed** (see git history). The
same declaration is embedded in `scripts/hill_alignment_audit.py::DECLARATION`, and its
sha256 is stamped into `audit.json`.

**Three questions, kept apart:**

1. **Price-scale mismatch.** A value-direct source's native normalized value
   (`raw / site_max × 9999`) is compared with the live Hill master at the source's rank,
   with that rank counted in the **population the master assumes**.
2. **Rank-population mismatch.** Population factor = Hill(population-correct rank) ÷
   Hill(live rank). This explains why the 2026-09-30 replay's `nativeVsHill` (native ÷
   Hill(live rank)) differs from the scale term.
3. **Genuine disagreement.** Measured in rank space, which is scale-free:
   log2(source's players-only rank ÷ players-only rank on a leave-that-source-out board).
   It is never measured against a consensus that contains the source. KTC Crowd and KTC
   Trades are each compared with a board built **without both** KTC families.

**Populations:**

| id | population | curve |
|---|---|---|
| `ktc_live` | board rows the source covers, offense players **and picks interleaved** (Phase 1 offense scope admits PICK) | OFFENSE |
| `ktc_players` | board offense players the source covers: the population every OFFENSE rank voter and holdout is ranked in | OFFENSE |
| `ktc_vendor` | players in the vendor CSV, picks removed. Isolates the board-coverage effect | OFFENSE |
| `idptc_live` | board offense + IDP + picks pool | GLOBAL |
| `idptc_offense` | IDPTC's board offense players | OFFENSE |
| `idptc_idp` | IDPTC's board IDP players | IDP. **Circular**: the IDP master is fit on IDPTC's own IDP slice, so this row is reported but never used for a verdict |
| picks | **non-comparable**: no Hill master prices these sources' pick ranks; picks take the anchor path | — |

**Breakdowns:** position; asset class; rank band on the population-correct rank (1–50,
51–100, 101–200, 201–300, 301–400, 401+); row weight state plus source subset freshness;
independent source count (≤2, 3–4, 5–8, 9+).

**Verdict rules (fixed in advance):**

- *Scale mismatch confirmed:* the population-correct median scale ratio falls outside
  [0.90, 1.10] in at least 3 of the bands 51–100, 101–200, 201–300 and 301–400.
- *Population share:* mean log2(population factor) ÷ mean log2(live ratio) over ranks
  51–400. A share of 0.5 or more means the replay metric was mostly population.
- *Stable:* across at least 5 archive dates, the daily median vendor-population scale
  ratio moves by no more than 0.10 (max − min) in each band.

**Outlier-filter sensitivity.** Absolute floors of 750, 1000 (incumbent), 1250 and 1500;
MAD only with no floor; MAD × 1.4826 with no floor; and filter off. Each variant reports:
observations excluded, rows with any exclusion, KTC Crowd / KTC Trades / both / IDPTC
exclusions, rows changed, and top-200 membership changes.

**Candidates (at most 3):**

| id | definition |
|---|---|
| incumbent | production as built |
| c1 `ktc_scale_map` | Each KTC board's values pass a monotone map V′ = H_off(F_ktc⁻¹(v)). F_ktc is that board's own Hill fit (the fitter's grid, players-only top 400, canonical /499 coordinate) on the **current snapshot only**. H_off is the live OFFENSE master. The map keeps KTC's local spacing around its own curve and applies to every KTC row, including picks. **Circularity:** the target master trains on 6 boards, one of them KTC base (the same crowd). The target is not a consensus containing KTC Crowd as a vote, but it is not KTC-free either |
| c2 `ktc_rank_hill` | KTC Crowd and KTC Trades are removed from `_VALUE_BASED_SOURCES`: the corrected `native_values_as_ranks`, with IDPTC staying value-direct |

**Candidate metrics:**

- rows changed, and median / p90 / max |Δ%| (Hill board-guard definitions);
- top-25 / 50 / 100 / 200 membership kept;
- KTC and total outlier exclusions, reported as a diagnostic and **not an objective**;
- KTC family leverage, |V − V(no KTC)| ÷ V(no KTC), on rows KTC covers;
- sparse rows (≤2 independent families): count changed and median |Δ%|;
- contract structural errors;
- build seconds;
- Coker and the data-chosen contrast set, as regression examples only.

**Gates for a candidate to be "eligible":**

- every rail in `config/model_registry/hill_autopilot_policy.json::boardImpact`;
- no new structural errors;
- KTC leverage p90 at most 1.25× the incumbent's (a candidate may not buy alignment by
  handing KTC more control);
- build time at most 1.5× the incumbent's.

**Never:**

- select or tune toward KTC Market parity (it is reported as context only);
- treat fewer exclusions as success;
- promote anything.

**Holdout.** `exports/archive` zips carry the KTC Crowd / KTC Trades / IDPTC CSVs but not
every voter. A full point-in-time **board** rebuild is therefore out of reach, and none is
manufactured. Instead, the scale ratio and the c1 map are tested forward in time: fit on
day d, scored on day d+7.

## 2. Pins

All pins are content-hashed in [`audit.json`](audit.json). The full tables are in
[`audit.md`](audit.md).

| Pin | Value |
|---|---|
| Code | `6b0bbf2ba`, clean tree (`workingTreeDirty: false`) |
| Payload | `exports/latest/dynasty_data_2026-09-30.json`, sha256 `69a0f4b4e264…`, scrape `2026-09-30T13:04:04Z`. No newer full refresh existed on 2026-10-01 |
| Inputs | 30 source CSVs, 24 freshness-state files, every fetch stamp, 53 `config/` files and the full flag snapshot. DLF and IDP Show refreshed on 2026-10-01, so the CSV pins differ from the 09-30 replay |
| League snapshots | **none**. This is a tracked-inputs-only build (1131 rows), so completed-draft picks are kept |
| Live input | Sleeper league context `roster_count 12`, `bonus_rec_te 0.0` |
| Outputs | incumbent board sha256 `9090458d00c3…` (one per candidate in the JSON); declaration sha256 `543fd3a3b7a5…` |
| Invariants | all pass: rebuild is identical; direct Hill(live rank) equals the pipeline's own rank→Hill stamp on 832/832 KTC rows; an identity CSV override changes 0 rows; the 1000 floor variant equals the incumbent |

## 3. Results

### A. Scale vs population (offense rows; medians by population-correct rank band)

The ratio columns are value ÷ Hill. "pop. factor" is Hill(players-only rank) ÷ Hill(live
rank).

| band | KTC Crowd: live (replay metric) | pop. factor | **scale** | KTC Trades: live | pop. factor | **scale** | IDPTC offense: live | **scale** |
|---|---|---|---|---|---|---|---|---|
| 1–50 | 0.955 | 1.012 | **0.943** | 1.001 | 1.000 | **0.994** | 1.061 | **0.937** |
| 51–100 | 1.153 | 1.039 | **1.087** | 1.226 | 1.025 | **1.187** | 1.161 | **1.076** |
| 101–200 | 1.306 | 1.083 | **1.204** | 1.324 | 1.060 | **1.250** | 1.122 | **1.185** |
| 201–300 | 1.448 | 1.096 | **1.320** | 1.532 | 1.077 | **1.421** | 1.045 | **1.305** |
| 301–400 | 1.302 | 1.097 | **1.185** | 1.592 | 1.092 | **1.457** | 0.873 | **1.153** |

1. **Scale mismatch is confirmed** for all three value sources. Population-correct ratios
   fall outside ±10% in 3 of 4 bands for KTC Crowd and IDPTC offense, and in 4 of 4 for
   KTC Trades. At the very top (ranks 1–50) KTC sits slightly **below** the master.
2. **Population is a minority of the replay's number:**
   - It accounts for 30% (KTC Crowd) and 19% (KTC Trades) of the mean log ratio over ranks
     51–400.
   - The mechanism: Phase 1 puts board **pick rows** into KTC's offense rank pool
     (`data_contract.py:2548`). Here that is 35 picks inside KTC's top 400.
   - Board coverage barely matters: the vendor-population ratios are 1–5% below the board
     ones.
   - The 09-30 figures (14–45% / 22–60%) therefore overstate scale by about 4–10 points
     per band.
3. **The 09-30 IDPTC figure (1.8–5.9×) was an artifact, not population** (error E1 below).
   - Correctly measured, IDPTC's live ratio is 0.87–1.16.
   - On offense players its scale ratio is nearly identical to KTC Crowd's. IDPTC tracks
     KTC (median ratio 1.000 on 475 shared players, per the runbook), so this is
     **not independent spacing evidence**.
   - IDPTC's IDP rows against the IDP master read 0.58–0.86. That comparison is circular
     by construction and is excluded from every verdict.
4. **This is genuine spacing disagreement among value markets, not a pipeline artifact.**
   - Every native-value board was fitted on players only, top 400, with the canonical
     coordinate:

     | board | c | s |
     |---|---|---|
     | KTC Crowd | 0.112 | 0.91 |
     | KTC Trades | 0.130 | 0.935 |
     | KTC base | 0.105 | 0.925 |
     | Dynasty Daddy | 0.056 | 1.21 |
     | Dynasty Nerds | 0.056 | 1.73 |
     | Yahoo/Boone | 0.076 | 1.26 |
     | Fitzmaurice | 0.122 | 1.31 |
     | DraftSharks | 0.028 | 0.83 |
     | FantasyCalc | 0.044 | 1.075 |
     | OTC | 0.041 | 1.01 |
     | PFK | 0.085 | 1.11 |
     | Fantasy Navigator | 0.050 | 1.345 |
     | DLF Values | 0.062 | 1.69 |
     | **live OFFENSE master** | **0.110** | **1.110** |

   - KTC prices the middle and tail of the board higher than every other native board.
     The master sits between KTC and the rest.
5. **Freshness cannot explain it.**
   - KTC's players and picks subsets are both at freshness 1.0 (7 h old, 12 h cadence).
   - IDPTC players are at 0.98, but IDPTC **picks are at 0.059 (`SEVERELY_STALE`, 804 h)**.
     That is recorded here for the pick lane, not acted on.
   - The weight-state and family-count breakdowns are in `audit.md`. Every non-NORMAL cell
     holds 2–31 rows.
6. **TE caveat.** KTC is exempt from the TE basis lift, but rank voters' TE values are
   lifted after Hill. KTC's TE scale ratio (1.22) is therefore measured against a pre-lift
   curve. The rank-space test in B is unaffected.
7. **The pending Autopilot OFFENSE challenger widens the gap.** It is v171, c 0.066 /
   s 1.085, and is currently blocked by the board-impact gate. Under it, KTC Crowd's
   scale ratio would be 1.58 / 1.84 / 2.07 / 1.88 across the four bands.

### B. Disagreement in rank space (leave-that-source-out boards)

Both ranks are counted over the same rows: the offense players the source covers that the
LOO board prices.

1. **KTC's ORDER is the most consensus-consistent of all 18 comparable sources.**
   - Rows whose rank differs by more than 41%: KTC Crowd 5.8%, KTC Trades 4.3%, IDPTC
     5.6%.
   - Rank voters range from 8.1% (PFK) to 17.7% (DraftSharks).
   - The rookie-only lists are non-comparable.
2. **The outlier filter removes KTC for a level gap, and rank voters for an opinion.**
   - The 10 dropped KTC Crowd observations have a median rank ratio of **1.02**: their
     order agrees with the LOO board.
   - Their median scale term is 0.95. Six of the ten are in the top 50, where the absolute
     1000-point floor is only about 12% of the value.
   - Dropped rank-voter observations have median rank ratios of 0.25–0.81, which is
     genuine reordering. PFK (0.98) and IDP Show (1.26) are the exceptions.
3. **Value split**, log2(native ÷ LOO) = scale + order-on-Hill:
   - The scale term is 1.09–1.46 across ranks 51–400.
   - The order term is 0.89–0.97. Part of that is structural: by Jensen's inequality, a
     consensus of noisy ranks on a convex curve sits above Hill of its median rank.

### C. Outlier floor sensitivity

| variant | excluded | KTC Crowd / Trades / both | IDPTC | rows changed | top-200 changes |
|---|---|---|---|---|---|
| 1000 (incumbent) | 161 | 10 / 2 / 1 | 5 | 0 | 0 |
| 750 | 291 | 21 / 11 / 5 | 12 | 135 | 6 |
| 1250 | 86 | 5 / 0 / 0 | 2 | 84 | 6 |
| 1500 | 50 | 3 / 0 / 0 | 1 | 123 | 8 |
| MAD only, no floor | 807 | 61 / 101 / 27 | 91 | 440 | 8 |
| MAD × 1.4826, no floor | 340 | 27 / 37 / 10 | 36 | 263 | 6 |
| off | 0 | 0 | 0 | 163 | 8 |

- An absolute floor is level-dependent: the same relative gap trips it at the top of the
  board and never in the tail.
- No floor value fixes the mixing of two spacing conventions. Each variant only moves
  where the cut lands, and changes 6–8 top-200 memberships.
- Hampel stays a diagnostic (owner decision 2026-09-24). **Tuning the floor is not
  recommended.**

### D. Candidates (full rebuilds; diagnostic patches restored)

| | incumbent | c1 KTC scale map | c2 KTC rank→Hill |
|---|---|---|---|
| rows changed | 0 | 598 | 598 |
| median / p90 / max \|Δ%\| | 0 | 0.7% / 9.8% / 40.5% | 1.3% / 8.4% / 34.1% |
| players only: median / p90 / max | 0 | 0.1% / 6.2% / 40.5% | 0.2% / 6.6% / 31.8% |
| top-25 / 50 / 100 / 200 kept | all | 25 / 48 / 100 / 195 | 25 / 48 / 98 / 195 |
| pick rows: median / max \|Δ\| | 0 | 144 / 557 | 330 / 814 |
| KTC exclusions (Crowd / Trades) | 10 / 2 | 5 / 1 | 6 / 1 |
| KTC leverage p90 | 0.060 | **0.086 (1.43×)** | 0.062 |
| sparse rows (≤2 families) changed | 0 | 2 | 2 |
| structural errors | 0 | 0 | 0 |
| gates | — | **fails leverage** | **passes all** |
| Jalen Coker | 3288 (#155), both KTC dropped | 3372 (#140) | 3443 (#131), both vote |

- c1 is ineligible. It keeps KTC's local spacing and hands KTC more control over the rows
  it covers.
- c2 passes every declared gate. Its largest moves are pick rows, which it prices off the
  OFFENSE curve at KTC's interleaved pick rank. That is a population §1 declared
  non-comparable, so **the c2 board diff is a superset of what the recommendation below
  would change**.
- Coker and the contrast set are regression examples only. Nothing was tuned toward KTC
  Market.

### E. Point-in-time holdout

Window: 22 archive days, 2026-09-09 to 2026-09-30.

- **KTC Crowd's scale ratio is stable**: the per-band range is at most 0.029.
- **KTC Trades is not stable** by the predeclared rule: ranks 301–400 range 0.116.
- c1's map, fit on day d and scored on day d+7 (15 pairs), errs about as much out of
  sample as in sample: median |log2| 0.064 vs 0.067 for Crowd, and 0.042 vs 0.037 for
  Trades.
- **A full point-in-time board backtest was not run: coverage is insufficient.** Archives
  carry 10 site_raw CSVs (KTC ×5, IDPTC, DraftSharks ×4), not every voter. The route for
  one later is `build_api_data_contract(csv_root=…)` over git-materialized CSVs, as
  `src/consensus_edge/panel.py` does.

## 4. Recommendation (one)

**Take KTC Crowd and KTC Trades player rows off the value-direct path. They should vote
their order through the OFFENSE master, at their players-only rank. KTC pick rows stay
value-direct.** This would ship as a default-OFF flag-gated challenger.

Why:

- The mismatch is spacing, not opinion. KTC's order agrees with the field better than any
  other source, while its native spacing is the flattest of 13 native boards.
- Today the blend averages two spacing conventions. A level-dependent outlier floor then
  decides, row by row, which one counts.
- Making the Hill master the single owner of spacing removes that mixing.
- KTC's spacing evidence still reaches the board once, as Hill training evidence, not as
  per-row votes.
- c2 passes every predeclared gate. The only numeric calibration tested (c1) fails one.
  **No numeric calibration is recommended.**

This is a source-role (methodology) change, not a constant. Promotion path:

1. **Owner decision** on the source role. The lead records it in the intake and the
   execution plan.
2. **Precondition, through the Hill Autopilot only** (no hand edits, no
   `--override-scope`):
   - fix E3 (the pick rows in the KTC base trainer);
   - align the OFFENSE trainers with the live value voters, per the 2026-09-24 audit's
     H1/H2;
   - let the registry gates decide any new champion, because this change makes the master
     the sole spacing owner.
3. **Lane C implements it** in `data_contract` behind a default-OFF flag:
   - player-only rank pool for KTC;
   - picks stay value-direct;
   - E2 fixed in the same PR, with RED tests.
4. **Re-run** `scripts/hill_alignment_audit.py` with the flag on, against the same
   predeclared gates, on the then-current snapshot plus forward days.
5. **A human flips the flag.** Rollback is flag off plus restart.

IDPTC shows the same offense-row tilt but is the IDP backbone. It is out of scope here and
recorded as a follow-up.

## 5. Errors found

**E1 — the replay counterfactual (owned by this unit; FIXED in this branch).**

- `native_values_as_ranks` emptied `_VALUE_BASED_SOURCES`. That re-admitted
  `idpTradeCalc` to Phase 1c, which decodes the value as a synthetic rank
  (`data_contract.py:10161`). IDPTC effective ranks became 9900–9992 and every IDPTC row
  voted 1,174.
- Under the old patch the board diff is 980 rows and 36 top-200 changes, against 598 / 10
  for the corrected KTC-only patch.
- `value_replay` now refuses IDPTC re-expression. `native_vs_hill` refuses a rebuild that
  moved the rank.
- **For the lead:** the V2-5 row and §D of the valuation map still cite "IDPTC 1.8–5.9×,
  confounded by its combined-population rank" and "910 rows; 34 top-200 changes". Both
  should cite this erratum. Coker's +158 under that counterfactual was close by
  coincidence; the corrected figure is +155.

**E2 — latent coupling in `data_contract` (not a production defect today).**

- Phase 1c selects cross-market sources whose VALUE gets decoded as a rank by testing
  `not in _VALUE_BASED_SOURCES` (`data_contract.py:10143`), not the source's signal type.
- Any future change that takes IDPTC (or another value-signal cross-market source) off
  the value path would silently price it at the tail.
- **RED test:** with `idpTradeCalc` removed from `_VALUE_BASED_SOURCES`, its
  `effectiveRank` must equal its Phase 1 ordinal (today it is about 9,900). Alternatively,
  refuse at import any value-signal CSV source that would enter Phase 1c.

**E3 — training-population mismatch in the Hill fitter (an implementation error of the
W30-F008 class).**

- `scripts/fit_hill_curve_percentile.py:70` trains OFFENSE on `ktc.csv`.
- `_load_values` keeps every positive row, so 36 pick rows sit inside the top 400 the
  fitter keeps (`:393`).
- Every other OFFENSE trainer, all four holdouts, and every OFFENSE rank voter at serve
  time are players-only.
- KTC base fits c 0.105 / s 0.925 on players only, against 0.111 / 0.875 as the fitter
  reads it.
- **RED test:** no OFFENSE training list (fitter and `holdout.py::OFFENSE_TRAINING_SOURCES`)
  may contain a pick-pattern name.

## 6. Reproduce

```bash
python scripts/hill_alignment_audit.py \
  --json docs/valuation/evidence/hill-alignment-2026-10-01/audit.json \
  --markdown docs/valuation/evidence/hill-alignment-2026-10-01/audit.md
python -m pytest tests/api/test_hill_alignment_audit.py tests/api/test_value_replay.py -q
```

The run takes about 45 s locally: 30 builds plus 44 curve fits.
