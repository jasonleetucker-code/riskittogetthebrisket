# Package VA research Phases 1–3: `fairness_bands_v2` re-measurement addendum (2026-10-21)

**Status: ADDITIVE ADDENDUM — RESEARCH ONLY.** It adds to the three phase memos and replaces none of them:

- Phase 1: `PACKAGE_MODEL_HYBRID_RESEARCH_2026-10-19.md`
- Phase 2: `PACKAGE_MODEL_PHASE2_RESEARCH_2026-10-19.md` (and its preregistration)
- Phase 3: `PACKAGE_MODEL_PHASE3_RESEARCH_2026-10-20.md` (and its preregistration)

Every original evidence file is untouched. The new evidence is in
`evidence/package_model_v2_remeasure_2026-10-21/`.

**Unchanged:** `geom_q078_v1` (q = 0.78), `fairness_bands_v2` (`src/valuation_math/fairness_bands.py` +
`config/trade/fairness_bands.json`), the canonical values, every flag and every served path. No production code,
config or flag was edited. Nothing is activated or promoted.

Authority: owner decision of 2026-10-21, Package 2 (`docs/owner/LVA_OWNER_DECISIONS_2026-10-21.md`): "approve
re-measuring Package VA Phases 1–3 under `fairness_bands_v2`, as low-priority research only. Preserve the
original historical evidence." Precedent: PR #1898, the same correction for the low-value-asset research
(`LOW_VALUE_ASSET_V2_CORRECTION_2026-10-21.md`).

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## 0. Result in one screen

- **What was stale.** Every fairness *level* in Phases 1–3 was classified against the larger **adjusted** side
  (`fairness_bands_v1`). The approved methodology (`fairness_bands_v2`, owner decision OD-F2, 2026-10-20)
  divides by the larger **package utility**. The numerator, the package models, the samples, the seeds and the
  cut points (250 points; 3.5 / 9 / 18%) are the same. Only the denominator changed.
- **Reproduced first.** The recorded v1 numbers are reproduced **exactly** for every band-dependent section on
  its pinned board, except the two Trade Finder replays: Phase 2 matches 442 of 443 leaves, the one miss a
  band-free count; Phase 3 matches 710 of 822, all engine drift present on v1 too (§3).
- **Does any KEEP conclusion change? No.** Phase 1, Phase 2 and Phase 3 each still recommend **KEEP
  `geom_q078_v1` with q = 0.78**. Every finding that decided those recommendations is either band-independent
  (mathematical properties, market residuals, the value-level decomposition, the Finder's recommendation lists)
  or moves without crossing a decision rule (§5).
- **What does move.** v2 has a smaller denominator on any multi-piece package, so verdicts get stricter. Fewer
  deep trades are "fair", more are "slight" or "lopsided". Two recorded statements read differently (§5):
  - Phase 2: the two star-for-pile Finder recommendations that EFD_78 and HYBRID_50 added (rated "slight") are
    rated "unfair" under v2, so they no longer count as star-for-pile. Those challengers still fail
    preregistered C6 on its other leg (they drop sensible multi-starter trades the incumbent keeps). That leg
    reads no band.
  - Phase 2 / 3: the incumbent's "six or ten genuine starters for a superstar is roughly even" becomes "slight"
    (still near even, no longer the "fair" level).

| quantity (memo location) | recorded (v1) | re-measured (v2) | decides |
|---|---|---|---|
| P1 §2 mathematical properties | GEOM_78 0 failures; KTC / blends fail | identical (no band) | A, B: **still No** |
| P1 §4 "same fairness level as ours", ordinary / deep: BLEND 50/50 | 48.7% / 62.5% | 56.9% / 76.9% | §5 impact size |
| P1 §4 same, KTC | 38.7% / 53.4% | 46.1% / 72.9% | context |
| P1 §4 same, FGEOM_70_20 | 95.4% / 87.1% | 95.6% / 91.7% | C: still "indistinguishable" |
| P1 §4 same, HYBRID_50 | 71.4% / 27.4% | 70.5% / 28.8% | context |
| P1 §5 Trade History grade changes vs ours (of 38): BLEND 50/50 / 75/25 / HYBRID_50 / FGEOM_70_20 | 13 / 7 / 8 / 1 | 12 / 6 / 9 / 1 | C: FGEOM still changes 1 of 38 |
| P1 §6 completed-trade residuals, holdout, bootstrap | as recorded | identical (no band) | F, H: unchanged |
| P2 §A.4 market residuals (1,121 trades) | as recorded | identical (no band) | Q1, Q4: unchanged |
| P2 §C.2 Gibbs vs six ~2,950 starters / ten ~2,170 starters (GEOM_78) | −556 fair / +768 fair | −556 **slight** / +768 **slight** | Q7 wording only |
| P2 §E star-for-pile recommendations added: EFD_78 / HYBRID_50 / GEOM_78 | 1 / 2 / 0 | **0 / 0 / 0** | C6 leg 1 |
| P2 §E incumbent's sensible-depth trades lost (EFD_78, all four surfaces) | 72 / 10 / 17 / 55 | identical (no band) | C6 leg 2: **still fails** |
| P3 §8.1 flag "superstar beats legitimate starters", of 9: GEOM_78 / LP_150 / LP_175 | 0 / 6 / 6 | 0 / 6 / **9** | "LP_150 over-charges starters": holds |
| P3 §8.1 flag "decisive verdict on a raw near-even trade": GEOM_78 / LP_125 / LP_150 | 1 / 1 / 6 | **3** / 2 / 6 | narrows GEOM_78's edge (§4.3) |
| P3 §8.1 flag "filler tips the verdict": GEOM_78 / LP_150 | 1 / 0 | 1 / 0 | GEOM_78's one weakness: holds |
| P3 §8.2 levels changed vs GEOM_78 on 2,000 trades: LP_150 / LP_175 / KTC | 520 / 680 / 1,227 | 409 / 655 / 1,041 | "about a quarter" → about a fifth |
| P3 §8.2 favoured side flipped vs GEOM_78 | as recorded | identical (no band) | context |
| P3 §8.3 Finder star-for-pile, every model and surface | 0 | 0 | holds |
| P3 §6 / §9 production ledger (18,690 trades), selections, confirmation | as recorded | **not re-run (box-only)**; classifies no band | KEEP basis: unchanged |

## 1. Why the levels were stale

Phase 1 defined a research helper `level(gap, adj_a, adj_b)` that called the owner's
`fairness_bands.classify(gap, max(adj_a, adj_b))`. That was the owner's contract on 2026-10-19 (v1). Phases 2
and 3 reached it through the research modules. v2 changed the owner's rule on 2026-10-20 and the helper kept
passing the old base. PR #1898 renamed the helper `level_v1_legacy`, kept `level` as an alias for these frozen
scripts and added a guard test. It did not re-measure the package phases. This addendum does.

## 2. Methodology

| | recorded | re-measured |
|---|---|---|
| gap | each model's adjusted A − adjusted B | the same |
| band base, incumbent | `max(adjusted)` | the owner: `fairness_bands.classify_packages(gap, A, B)` |
| band base, KTC | `max(adjusted)` | the owner's own rule for a model with no package utility: `larger_package_utility(A, B, model_id=ktc_2026_04)` (its adjusted totals), so v1 = v2 by construction |
| band base, any other utility model (GEOM_q, FGEOM, ZIPF, LP, HYBRID_50, EFD, GP, VG) | `max(adjusted)` | `classify(gap, fairness_base((U_A, U_B)))` on **that model's own** package utilities (the #1898 rule for a comparator) |
| band base, BLEND (a weighted signed gap, no utility) | `max(adjusted)` | the owner's utility-less rule (adjusted totals stand in), so v1 = v2 by construction |
| thresholds | owner | owner; the research computes none (test-pinned) |

**Implementation.**
- The three phase scripts now classify through one package-aware helper,
  `package_model_hybrid_research.band_level(model, gap, A, B)`.
  - Its basis is scoped by `band_basis("v1_legacy" | "current")`.
  - The module default stays `v1_legacy`, so each frozen script's own `main` still reproduces its committed file.
  - Phase 2's `level(gf, A, B)` (the Finder tag) is unchanged; the driver re-tags the replayed trades instead.
- `scripts/package_model_v2_remeasure.py` is the driver. It runs every band-dependent section twice, once on
  each basis, on the same board with the same seeds, and compares the v1 run leaf by leaf with the committed
  evidence.
  - The Finder, Best Offers and Package Builder engines read no band denominator. Each model's replay is run
    once and its trades are tagged on both bases with `FR.classify`'s preregistered rule.
  - The re-tag on v1 reproduces the replay's own tags with 0 differences (`retagV1SelfCheckChangedTags`).
- `scripts/package_model_v2_remeasure_extract.py` rebuilds a recorded board or Finder replay with the code **at
  the recorded revision** (§3).
- Tests: `tests/scripts/test_package_model_v2_remeasure.py`.
  - v1 equals the retired helper on every Phase 1–3 model.
  - v2 equals the owner.
  - every model has a band rule; the scope restores; no threshold is computed.
  - the driver refuses to write into an original evidence directory.
  - the re-tag self-check passes.
  - The #1898 guard (`test_research_band_basis_guard.py`) allow-lists the two new scripts with reasons.

## 3. Reproduction first

| phase | board pin | how | v1 reproduction (leaves equal / compared) |
|---|---|---|---|
| 1 | raw payload `exports/latest/dynasty_data_2026-10-19.json` (sha256 `b639608f…e11c`, at `9668165`) | board **and** the own-league trade rows rebuilt by the pipeline at `79c322828` (the recorded Phase 2 commit, no `src/` / `CSVs/` / `config/` / `data/` difference from `9668165`; the Phase 1 script was uncommitted at `9668165`); 1,029 priced assets; trade census identical (38 graded) | worked examples **208 / 208**; Trade History level changes **89 / 89**; matrix aggregates **5,370 / 5,370** |
| 2 | the same payload | the same extracted board; the Finder replay of all 6 models run by the code at `79c322828` | large-package tables **293 / 293**, **180 / 180**; real examples **291 / 291**; Finder comparison **442 / 443** |
| 3 | archive `exports/archive/dynasty_export_20261019_235843.zip` (sha256 `a8839a65…b1ae`), CSV tree at `6dbfc5aa` | today's code, Travis Hunter held at his recorded 3,738 (the #1898 precedent; PR #1817 moved him to 3,599) | real examples **1,850 / 1,850**; fairness sample **369 / 369**; Finder comparison 710 / 822 (current engine; see below) |

- **Why Phases 1–2 needed the old code.** Rebuilt by today's pipeline, the same payload prices 1,005 assets
  (24 fewer picks) and gives Hunter a different value. Every sampled trade therefore shifts.
  - That attempt reproduced the matrix on 2,180 of 5,370 leaves.
  - The trade history graded only 30 of the 38 trades.
  - It is kept out of the evidence. Building on the recorded revision's own code closes the gap completely.
- **The one Phase 2 Finder difference.** `FGEOM_70_20.star_builder.keptButReordered` is 163 recorded and 165
  re-run. It is an ordering count with no band.
- **Phase 3's Finder** was replayed with today's engine, not extracted. Its 112 differing leaves are engine and
  value drift (appearance and overlap counts), present on the v1 basis too.
  - Only 29 of them are level-dependent. They are level histograms, which the memo does not report.
  - The memo's band-dependent Finder claim, 0 star-for-pile, is the same on both bases.
  - The v1 → v2 comparison runs on one replay, so the attribution to the band is exact.
- **Box-only inputs were not touched.** Nothing ran on the production box.

## 4. Results, side by side

All "v2" figures come from the same board, code and sampling as the reproduced v1 figures. Only the band
denominator differs.

### 4.1 Phase 1

**Real-player worked examples (memo §3).** Gap unchanged; level v1 → v2. Only changed cells are listed.

| trade | GEOM_78 | HYBRID_50 | FGEOM_70_20 |
|---|---|---|---|
| IDP 1-for-3: Schwesinger for Landman + Ezeiruaku + Starks (+1,215 / +957 / +1,288) | unfair → **lopsided** | unfair (same) | unfair → **lopsided** |
| 1-for-10: Gibbs for ten ~1,100 players (+5,279 / +1,874 / +4,823) | lopsided (same) | unfair → **lopsided** | lopsided (same) |

Every other worked-example level (Gibbs 1-for-2 / 1-for-3 / 2-for-3 / 1-for-6; KTC and every blend) is unchanged.

**Bias matrix (memo §4), near-balanced window: same fairness level as ours.** Every non-level metric
(fewer-pieces wins, raw leader reversed, median move) is identical on both bases. That was checked for every
model.

| model | ordinary v1 → v2 | deep v1 → v2 |
|---|---|---|
| RAW | 33.5 → 34.4 | 28.7 → 34.0 |
| KTC | 38.7 → 46.1 | 53.4 → 72.9 |
| BLEND 75/25 | 65.0 → 72.6 | 75.9 → 79.9 |
| BLEND 50/50 | 48.7 → 56.9 | 62.5 → 76.9 |
| BLEND 25/75 | 41.7 → 49.6 | 56.4 → 74.5 |
| GEOM_85 | 70.8 → 69.5 | 50.5 → 58.5 |
| HYBRID_50 | 71.4 → 70.5 | 27.4 → 28.8 |
| FGEOM_70_20 | 95.4 → 95.6 | 87.1 → 91.7 |
| GEOM_70 | 72.1 → 72.1 | 68.2 → 73.1 |
| LP_150 | 63.0 → 63.9 | 69.6 → 77.2 |
| ZIPF_100 | 49.7 → 51.3 | 62.6 → 72.4 |

**Trade History (memo §5), grade changes vs ours, of 38:**

| model | v1 | v2 |
|---|---:|---:|
| KTC | 20 | 18 |
| BLEND 25/75 / 40/60 / 50/50 / 60/40 / 75/25 | 18 / 14 / 13 / 10 / 7 | 16 / 12 / 12 / 9 / 6 |
| GEOM_85 | 6 | 9 |
| HYBRID_50 | 8 | 9 |
| FGEOM_70_20 / FGEOM_75_15 | 1 / 2 | 1 / 4 |
| ZIPF_75 | 12 | 12 |
| RAW | 16 | 15 |

**What it means.**
- Under v2 the incumbent's own verdicts move toward KTC's (both get stricter on deep packages; KTC was already
  strict). So KTC and the blends agree with ours more often.
- That does not rescue them. The reasons Phase 1 rejected them read no band:
  - the add-an-asset and continuity failures (§2);
  - extra star bias on ordinary trades (§4 fewer-pieces wins);
  - a worse fit on completed trades (§6).
- Memo §5's "a 50/50 blend would regrade about **half** of ordinary package trades" becomes about **43%**
  (ordinary) and **23%** (deep).
- FGEOM_70_20 is still effectively identical to ours: 1 of 38 grades, ~96% / 92% the same level. Answers A–J
  are unchanged.

### 4.2 Phase 2

**Depth vs filler, synthetic star = 9,000 (memo §C.1).** Only changed cells are listed.

| package | model | gap | v1 → v2 |
|---|---|---:|---|
| six starters (30% each) | GEOM_78 | −509 | fair → **slight** |
| ten starters (25% each) | GEOM_78 | −375 | fair → **slight** |
| ten starters (25% each) | FGEOM_70_20 | −1,331 | slight → unfair |
| six bench (20% each) | EFD_78 | +1,009 | slight → unfair |

**Real players, Gibbs (memo §C.2).** Only changed cells are listed.

| Gibbs for … | model | gap | v1 → v2 |
|---|---|---:|---|
| six ~2,950 starters | GEOM_78 | −556 | fair → **slight** |
| ten ~2,170 | GEOM_78 | +768 | fair → **slight** |
| six ~1,775 bench | EFD_78 | +1,989 | unfair → lopsided |
| four ~3,250 | EFD_78 | −456 | fair → slight |
| IDP: Schwesinger for four ~2,050 IDP starters | EFD_78 | −277 | fair → slight |
| offense + IDP depth (5) | EFD_78 / FGEOM_70_20 | −1,292 / +356 | slight → unfair / fair → slight |

Unchanged:
- three ~3,900 starters (GEOM_78 slight);
- three firsts (fair);
- every filler case (lopsided);
- every KTC and HYBRID_50 cell.

**Asymmetric shapes (memo §C.3).**
- GEOM_78: 4v8 useful +3,811 unfair → **lopsided**; 3v6 filler-heavy −747 fair → slight.
- EFD_78: 2v5 filler-heavy fair → slight; 3v6 filler-heavy and 4v8 useful slight → unfair.

**Trade Finder replay (memo §E), recorded-revision engine.**

| | v1 | v2 |
|---|---|---|
| star-for-pile added: EFD_78 / HYBRID_50 (Finder, all shapes) | 1 / 2 | **0 / 0** |
| star-for-pile: GEOM_78, FGEOM, BLEND, KTC, every other surface | 0 | 0 |
| incumbent's sensible-depth trades lost: EFD_78 / HYBRID_50 / FGEOM_70_20 (package scan / all shapes / best offers / star builder) | 72/10/17/55 · 69/6/16/53 · 25/1/4/15 | identical |
| replaced, top-10 overlap, user's raw gain | as recorded | identical (no band) |

- The star-for-pile trade (Cam Skattebo + Denzel Boston + Sam Darnold → Josh Allen + Terrel Bernard, and
  HYBRID_50's Boston + Makai Lemon + Darnold variant) has gaps of +1,155 / +1,074 / +1,198.
- Under v2 they classify "unfair", not "slight". The preregistered definition requires fair or slight, so they
  no longer count.

**Is C6 still failed?** Yes. C6 says a challenger may neither add star-for-pile recommendations **nor drop
sensible multi-starter trades the incumbent keeps**.
- Under v2 the first leg no longer fires for EFD_78 or HYBRID_50.
- The second leg is band-free and unchanged: 10–72 and 6–69 lost trades per surface.
- KTC and the blends still rewrite 70–97% of recommendations and fail C1.

**Unchanged by construction:**
- §A market residuals;
- §B break-even multiples;
- §D properties;
- the scorecard rows C1, C2, C3, C5, C7–C9.

**Answers to the owner's four questions are unchanged.** One wording changes. Q2 said the incumbent produced
zero star-for-pile recommendations and the challengers produced 1 and 2. Under v2 all produce 0, so this is no
longer a point in the incumbent's favour. The KEEP rests on Q1 (market) and Q3 (Finder replacement and
sensible-depth loss), which read no band.

### 4.3 Phase 3

**Real players (memo §8.1).** Only changed cells are listed.

| trade | model | gap | v1 → v2 |
|---|---|---:|---|
| Garrett Wilson vs Jake Ferguson + Travis Kelce (1-for-2 near-even) | GEOM_78 | +254 | fair → **slight** |
| Gibbs vs six ~2,950 starters | GEOM_78 | −557 | fair → **slight** |
| Gibbs vs ten ~2,170 starters | GEOM_78 | +730 | fair → slight |
| 2-for-3 near-even | GEOM_78 | +1,035 | slight → **unfair** |
| 2-for-4 near-even | GEOM_78 | +2,121 | unfair → lopsided |
| top rookie vs 1 first + 2 rookies | GEOM_78 | +777 | slight → **unfair** |
| Jeremiyah Love vs 2027 1.10 + 2028 Late 1st | LP_150 | +695 | slight → unfair |
| 1-for-3 near-even | LP_150 | +1,706 | unfair → lopsided |
| Gibbs vs 2 starters + 4 filler | LP_150 | +1,115 | slight → unfair |
| most LP_175 / GP_078_150 cases vs genuine starters | LP_175, GP_078_150 | — | one step stricter (full list in `phase3.json`) |

Unchanged:
- the filler sweetener ladder: Hurts vs Egbuka, Egbuka + Hodgins is fair (+60); four fillers is unfair the
  other way (−1,263);
- Gibbs vs Young + Kraft (GEOM_78 fair / LP_150 unfair);
- Schwesinger vs Baun + Parsons (fair / unfair);
- every filler-only case (lopsided).

**Flag counts, of the full example set:**

| flag | GEOM_78 | LP_125 | LP_150 | LP_175 | LP_200 / LP_250 / GP / KTC |
|---|---|---|---|---|---|
| superstar beats legitimate starters by a large margin (of 9) | 0 → 0 | 0 → 0 | 6 → 6 | 6 → **9** | 9 → 9 |
| decisive verdict on a raw near-even trade | 1 → **3** | 1 → 2 | 6 → 6 | 6 → 6 | 6 → 6 |
| filler alone tips the verdict | 1 → 1 | 1 → 1 | 0 → 0 | 0 → 0 | 0 → 0 |

**What the flags mean.**
- Under v2, GEOM_78's lead over LP_150 on "decisive verdict on a raw near-even trade" narrows from 6 vs 1 to 6 vs 3.
- LP_125 now ties or beats GEOM_78 on every flag (0 / 2 / 1 against GEOM_78's 0 / 3 / 1).
- This does not change the KEEP. Phase 3's recommendation never rested on these flag counts. It rests on §6 / §9:
  - the market's own package shape, q ≈ 0.80–0.85 once the value-level effect is separated;
  - the preregistered selections and confirmation.
  Both are band-free. LP_125 was never a selected or confirmed candidate.
- It is recorded here so that "GEOM_78 is the least decisive model on near-even trades" is not quoted from the
  v1 table.

**Fairness sample of 2,000 trades (memo §8.2), levels changed vs GEOM_78:**

| model | v1 | v2 |
|---|---:|---:|
| LP_125 | 511 | 529 |
| LP_150 | 520 | 409 |
| LP_175 | 680 | 655 |
| LP_200 | 821 | 772 |
| LP_250 | 907 | 867 |
| GP_078_150 / GP_090_175 | 795 / 796 | 784 / 757 |
| KTC | 1,227 | 1,041 |
| VG_078_1500 / VG_078_2000 (diagnostics) | 741 / 891 | 1,070 / 1,146 |

- "Favoured side flipped" and the gap shift toward the fewer-pieces side are identical: they read no band.
- GEOM_78's own level distribution moves from fair / slight / unfair / lopsided 423 / 495 / 667 / 415 to
  389 / 382 / 657 / 572.

**Trade Finder (memo §8.3).** 0 star-for-pile on every surface for every model, on both bases. Overlap, dropped
depth trades and board edge read no band.

**Production ledger (memo §2, §6, §9).** `production_phase3_run_2026-10-20.json` and
`production_ledger_run_2026-10-20.json` contain no fairness level, and `scripts/package_model_phase3_research.py`
classifies none. Their residuals, the value-level decomposition, the S1 / S2 selections and the league-disjoint
confirmation are band-independent, so `fairness_bands_v2` cannot change them. They were not re-run here (box
only): a fresh re-run is **EVIDENCE_PENDING (box-only)** and is not needed for this question.

## 5. Do the conclusions change?

| phase | recorded recommendation | after v2 | why |
|---|---|---|---|
| 1 | KEEP `geom_q078_v1`, q = 0.78; do not average with KTC; do not activate HYBRID_50; no new challenger | **unchanged** | the rejections rest on properties, star bias and completed-trade fit, none of which reads a band; FGEOM_70_20 is still indistinguishable |
| 2 | KEEP; no alternative fixes a demonstrated weakness | **unchanged** | the market evidence (Q1) is band-free; C6 still fails on its sensible-depth leg; the "1 and 2 star-for-pile" contrast disappears (all 0) |
| 3 | KEEP; LP_150's gain is a value-level effect; GEOM_78's one weakness is filler tipping a near-even verdict | **unchanged** | §6 / §9 are band-free; LP_150 still flags 6 of 9 superstar cases (LP_175 now 9 of 9); GEOM_78 still 0; the filler ladder is identical |

As the phase reports said, the package-model KEEP does not depend on the fairness denominator. The re-measurement
confirms it.

Read-outs that change, for whoever quotes these memos later:
- Under v2 the incumbent rates large genuine-depth packages against a star (six or ten starters at 1.8–2.2× raw)
  **slight**, not fair. Two near-even consolidation cases in Phase 3 (2-for-3, rookie vs first + two rookies)
  move to unfair.
- That is the approved methodology being stricter on depth, not a change to the package model.

## 6. Reproduce

```bash
git worktree add --detach <tmp>/old 79c322828
cd <tmp>/old && python -I <repo>/scripts/package_model_v2_remeasure_extract.py <tmp>/old board --trades --out <x>/board_p1p2.json
cd <tmp>/old && python -I <repo>/scripts/package_model_v2_remeasure_extract.py <tmp>/old finder --models GEOM_78,EFD_78 --out <x>/finder2_GEOM_78.json
#   (likewise HYBRID_50,FGEOM_70_20 and BLEND_G50_K50,KTC)
python scripts/package_model_v2_remeasure.py --phase 1 --board-json <x>/board_p1p2.json          # ~21 min
python scripts/package_model_v2_remeasure.py --phase 2 --board-json <x>/board_p1p2.json --finder-json <x>/finder2_*.json
python scripts/package_model_v2_remeasure.py --phase 3 --finder --workers 3                      # ~30 min
python -m pytest tests/scripts/test_package_model_v2_remeasure.py tests/scripts/test_research_band_basis_guard.py
```

The extracted inputs are recorded by sha256 in each `phaseN.json → board` / `finder.replaySource`. They are not
committed: the Finder replays carry team names.
- The checkout must use a short path on Windows; a deep path fails checkout.
- The extracted board is sha256 `2d599239…4002`.
- The extract records the payload's sha256 as `d5c5f9e4…`, not the pinned `b639608f…`. This is not a different
  payload: the Windows checkout converts the JSON to CRLF. The git blob is `b639608f`, and the reproduction is
  exact.

## Completion result

- `STATUS: DONE` (research addendum; no production change).
- `ACCEPTANCE:`
  - v1 reproduced first on pinned boards;
  - every band-dependent Phase 1–3 section re-measured on `fairness_bands_v2`;
  - the original evidence untouched;
  - box-only cells marked;
  - explicit KEEP verdict per phase.
- `EVIDENCE:`
  - `evidence/package_model_v2_remeasure_2026-10-21/phase{1,2,3}.json`;
  - `tests/scripts/test_package_model_v2_remeasure.py` and `test_research_band_basis_guard.py`;
  - the existing Phase 1–3 script tests and `tests/valuation_math`, all green locally.
- `UNRESOLVED:`
  1. The production-ledger results were not re-run (box-only). They classify no band, so this is
     EVIDENCE_PENDING only for a fresh run, not for this question.
  2. Phase 3's Finder replay used today's engine (Phase 3's harness needs `fork`). Its band-free counts drift
     from the record (710 / 822 leaves). The v1 → v2 attribution is exact because one replay is tagged both ways.
  3. Phase 1's box-only `--market-ledger` mode has never run. If it is ever run, its Trade History level
     changes would come out on the frozen module's default `v1_legacy` basis unless it is wrapped in
     `band_basis("current")`.
- `BLOCKERS:` none.
- `NEXT_ACTION:` none required. The owner may cite §5.
