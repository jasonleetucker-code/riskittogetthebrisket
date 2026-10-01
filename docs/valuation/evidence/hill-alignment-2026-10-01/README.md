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

## 2. Results

*Filled in after the run. See the next commit.*
