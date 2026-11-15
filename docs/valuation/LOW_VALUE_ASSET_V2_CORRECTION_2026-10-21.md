# Low-value-asset research: `fairness_bands_v2` correction addendum (2026-10-21)

**Status: ADDITIVE ADDENDUM — RESEARCH ONLY.** It adds to `LOW_VALUE_ASSET_RESEARCH_2026-10-20.md` and does not
replace it. The frozen preregistration (`evidence/low_value_assets_2026-10-20/PREREGISTRATION.md`) and every
historical evidence file are untouched; the new evidence is in `evidence/low_value_assets_2026-10-20/v2_correction/`.

**Unchanged:** `geom_q078_v1` (q = 0.78), `fairness_bands_v2` (`src/valuation_math/fairness_bands.py` +
`config/trade/fairness_bands.json`), the canonical values, the source weights and votes, every flag and every
served path. Nothing here activates or promotes anything, and no production code was edited.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## 0. Result in one screen

- **What was wrong.** The filler-flip study (F1 / F2 / F3), its secondary readings, the "naive disclosure" fire rates,
  the real-player level labels and the Trade Finder level histograms were classified against the **larger ADJUSTED
  side** (`fairness_bands_v1`). The approved methodology (`fairness_bands_v2`, owner decision OD-F2, 2026-10-20)
  divides by the **larger PACKAGE UTILITY**. It was not an error when the evidence ran (11:19 UTC; v1 was the active
  owner; v2 was decided that evening and adopted by release train 17 on 2026-10-21). It became **stale** and nothing
  flagged it.
- **What changed.** The research now reads the owner. The old basis is kept, explicitly labelled `v1_legacy`, so the
  recorded numbers can be reproduced; they **are** reproduced exactly (§3).
- **Do the conclusions change? No frozen-rule outcome changes. R-C still holds.** Every figure that moved moved
  toward the same conclusion or by a margin that cannot flip a rule (§6):

| quantity (memo location) | recorded (v1) | corrected (v2, same board) | corrected (v2, current main) | rule it feeds |
|---|---|---|---|---|
| F1 — filler flips removed, best B treatment, offense + mixed (§8) | at most 23.1% (need ≥ 80%) | at most 24.6% | at most 25.2% | R-B: **still fails** |
| F1 — all treatments, all classes (§4, §9) | 13.6–27.8% | 15.7–29.0% | 14.9–29.0% | R-B: still fails |
| F2 — starter-only trades re-levelled, B, offense + mixed (§8) | 37.1–41.7% (need ≤ 2%) | 40.5–45.3% | 39.8–44.8% | R-B: **still fails, by more** |
| F2 — all treatments (§0 Q1, §9) | 30.6–41.7% | 40.5–52.9% | 39.8–53.4% | R-B: still fails |
| F3 — usable-depth flips removed, all treatments (§4) | 7.1–14.4% (need ≤ 25%) | 7.9–15.0% | 7.4–15.0% | passes under both |
| "naive shadow disclosure" fires on depth / starter cases (§11) | 18.7% / 12.8% | 9.9% / 7.2% | 9.8% / 7.2% | informs the R-C design; see §6.4 |
| War Room: filler flips / neutralised / over-corrected / survive (§5.1) | 133 / 85 / 43 / 5 | 133 / 85 / 43 / 5 | 133 / 85 / 43 / 5 | R-B0: **identical** |
| Calculator sample, levels changed by B_currency_replacement (§4) | 657 of 2,000 | 723 | 722 | context |

## 1. Why the discrepancy occurred

1. `scripts/package_model_hybrid_research.py` (Phase 1, 2026-10-19) defined a helper `level(gap, adj_a, adj_b)` that
   calls the owner's `fairness_bands.classify(gap, max(adj_a, adj_b))`. That was the owner's contract at the time:
   v1 divided by the larger adjusted side.
2. Phase 2, Phase 3 and then `scripts/low_value_asset_shadow_replay.py::verdict` reached it through the research
   modules (`S.verdict -> T.gap -> P1.level`). The study built its adjusted totals itself and handed the owner a base
   the owner did not compute.
3. v2 changed the owner's rule; the helper kept passing the old base. The existing guard that polices this
   (`OneDenominatorOwner` in `tests/valuation_math/test_fairness_bands.py`) scans `src/` and `frontend/`, not
   `scripts/`, so nothing failed.
4. The memo says "the shared classifier" and "the fairness bands unchanged", which was literally true when written
   (v1 was the shared classifier) and became misleading once v2 was adopted. The evidence JSON labelled its own basis
   (`fairness_bands_v1 on adjusted totals`), which is what made the discrepancy findable.
5. The served-engine populations (War Room, public category, Trade Finder) were *also* v1 when recorded, because the
   engine itself was; since train 17 they are v2. The forced-drop diagnostic additionally mixed the two: its
   production path read the engine's band (v2 after train 17) while its counterfactual variants were classified
   against the retired `largerAdjustedSide`. The pre-existing 133 / 85 / 43 / 5 reproduction therefore could not have
   been re-run consistently without this fix.

Only the band's **denominator** differs. The numerator (the utility gap), the package model, the treatments, the
sampling, the seeds and every threshold (250 points, 3.5 / 9 / 18%) are unchanged.

## 2. Methodology: original and corrected

| | original (as recorded) | corrected (this addendum) |
|---|---|---|
| gap | `T.gap` = `U_A − U_B` under the treatment | the same |
| band base | `max(adjusted_A, adjusted_B)` through `P1.level`, i.e. v1 | the owner's: incumbent `fairness_bands.classify_packages(gap, values_A, values_B)`; a treatment: `classify(gap, fairness_base((U_A, U_B)))` on **that treatment's own** package utilities. No threshold or denominator is computed in the research |
| engine paths (War Room, public category, Trade Finder) | the engine as it was (v1) | the engine as it is (v2) |
| switch | none | `--band-basis current` (default) / `--band-basis v1_legacy` (reproduction only) |
| board pin | the archive only | the archive **and** the CSV tree the contract build reads (`--archive`, `--csv-rev`) |

For the incumbent the owner builds its own denominator from the two packages under the active model; the guard test checks the research
incumbent's gap against `package_model.geom_utility` and its level against the owner on random trades.

Implementation. `scripts/low_value_asset_shadow_replay.py` and
`scripts/low_value_asset_forced_drop_diagnostic.py` gained the switch and the pin options. One small reusable helper
module was added, `scripts/research_pinned_board.py` (archive load, `--csv-rev` materialisation, a scoped rebind of
`build_api_data_contract(csv_root=...)`, board hash). The disclosure shadow on PR #1887 contains the same idea
inline; this module is the reusable form so a third copy is not pasted. The legacy helper keeps its one home,
`scripts/package_model_hybrid_research.py`, now named `level_v1_legacy` (docstring: LEGACY; `level` stays as an alias
for the frozen Phase 1–3 callers) with a scoped `legacy_v1_denominator()` that makes the production engine read the
v1 base for a reproduction run. A comparison script, `scripts/low_value_asset_v2_correction_summary.py`, reads run
files and computes no band.

## 3. Reproduction first, then correction

Board pin (all runs): archive `exports/archive/dynasty_export_20261020_052241.zip` (sha256 `8e9b826a…198a`), CSV
tree at git revision `1511ca1d08dfffad4b48d113b2ac9a20d7a5de4b` (the revision PR #1887 found to reproduce this
board; tree hash and built-board hash `eed8df11…0833` are recorded in every run file), 1,003 priced assets.

| run | band basis | Hunter held at | file |
|---|---|---|---|
| **R0 reproduction** | `v1_legacy` | 3,738 (its value in the recorded run) | `shadow_replay_v1_reproduction.json` |
| **R1 band effect** | `current` (v2) | 3,738 | `shadow_replay_v2_same_board.json` |
| **R2 current** | `current` (v2) | built value, 3,599 | `shadow_replay_v2_current.json` |
| D0 / D1 | `v1_legacy` / `current` | engine, unmodified | `forced_drop_diagnostic_v1_reproduction.json`, `forced_drop_diagnostic_v2_current.json` |

**Reproduction (R0 against the committed `shadow_replay.json`): 3,395 of 3,465 result leaves equal.**
- Equal in full: the filler-flip study (728 of 729; the one difference is the `design.flip` description string), the
  calculator sample (156 / 156), the mathematical properties (113 / 113), the War Room (229 / 230; the difference is
  elapsed seconds) and the real-player cases (430 / 431; the difference is the `convention` string).
  The bases (2,825), cases (32,180), every flip count and every F1 / F2 / F3 value reproduce.
- Not equal, and **not band effects** (they differ in R0, which is on the v1 basis): Travis Hunter's value in the
  built contract (3,738 → 3,599, PR #1817) moves the WR starter-median anchor 3,480 → 3,410 and the own-league trade
  history by two sides (B_currency_replacement 57 → 55 of 150; that population uses `trade_grading`'s own thresholds
  and is identical in R0 and R1); engine drift since the recorded run adds 3 `UNAVAILABLE` public categories and shifts the star-builder surface of
  the Trade Finder replay (8 result leaves); neither was bisected.
- Forced-drop diagnostic (D0 against the committed file): 596 of 600 leaves equal, 133 / 85 / 43 / 5 and every
  counterfactual count reproduce. The four differences are the explanatory text and three descriptive flags
  (`cheaperAcquiredFillerExistedButNotCut` 37 → 39, `chargeExceedsSumOfIncomingFillerRawValues` 28 → 31,
  `cheaperCandidateLineupProtected` 19 → 22). They are present on the v1 basis, so they are not band effects;
  `roster_capacity.py` changed after the evidence (`d25772c0d`), which is consistent with them but was not bisected.

**Attribution.** Band effect = R1 − R0 (same board, same code, same sampling). Value-drift effect = R2 − R1 (one
value, Hunter). The Hunter effect on the study is small (F1 / F2 / F3 move ≤ 2.5 points in any class; the IDP and
mixed incumbent flip counts move by ≤ 50 of ~2,300–2,900). The engine paths are identical in R1 and R2.

## 4. Results, side by side

All percentages are of the recorded denominators. "v1" = as recorded (reproduced exactly by R0); "v2 sb" = R1; "v2 cur" = R2.

### 4.1 Filler-flip criteria (memo §4 selection; full table in Appendix A)

| class | treatment | F1 filler flips removed, v1 / v2 sb / v2 cur (need ≥ 80%) | F2 starter-only levels changed (need ≤ 2%) | F3 depth flips removed (need ≤ 25%) |
|---|---|---|---|---|
| offense | B_currency_replacement | 21.5 / 22.6 / 23.0 | 37.1 / 40.5 / 40.7 | 12.2 / 12.6 / 12.7 |
| offense | A_curve_market | 27.8 / 29.0 / 29.0 | 33.8 / 47.1 / 46.7 | 14.4 / 15.0 / 15.0 |
| IDP | B_currency_replacement | 18.6 / 19.2 / 19.5 | 35.9 / 42.1 / 40.8 | 9.0 / 9.1 / 10.4 |
| picks | B_currency_replacement | 13.6 / 15.7 / 14.9 | n/a | 7.1 / 7.9 / 7.4 |
| mixed | B_currency_market | 21.2 / 22.5 / 22.3 | 38.9 / 44.5 / 42.5 | 10.0 / 10.6 / 10.9 |

Verdict per cell: **F1 fail, F2 fail, F3 pass in every class, treatment and column** (picks F2 is not applicable).

Incumbent (GEOM_78) filler flips / depth flips, which are what F1 / F3 count against:

| class | v1 | v2 same board | v2 current |
|---|---|---|---|
| offense | 3,017 / 3,047 | 3,002 / 3,029 | 2,999 / 3,029 |
| IDP | 2,249 / 2,320 | 2,249 / 2,320 | 2,216 / 2,288 |
| picks | 1,098 / 1,244 | 1,096 / 1,244 | 1,097 / 1,241 |
| mixed | 2,909 / 2,962 | 2,909 / 2,958 | 2,859 / 2,920 |

"GEOM_78 flips about as often on filler as on depth" survives where it was claimed (offense: 3,002 against 3,029; IDP and mixed
within 3.2%); in picks depth still flips 13% more often than filler, as recorded.

### 4.2 Secondary readings (incumbent, filler sweeteners; B_currency_replacement in brackets)

| class | `verdictChanged` v1 / v2 sb | `winnerFlipped` v1 / v2 sb | `unfairMadeFair` v1 / v2 sb |
|---|---|---|---|
| offense | 3,581 / 3,582 (3,175 / 3,092) | 510 / 553 (239 / 282) | 143 / 121 (370 / 285) |
| IDP | 2,585 / 2,585 (2,285 / 2,176) | 424 / 428 (241 / 261) | 57 / 53 (224 / 187) |
| picks | 1,398 / 1,399 (1,337 / 1,253) | 380 / 388 (152 / 187) | 66 / 56 (179 / 130) |
| mixed | 3,429 / 3,443 (3,059 / 2,959) | 570 / 607 (254 / 286) | 133 / 118 (367 / 304) |

Direction: under v2 the incumbent makes slightly more winner flips and slightly fewer "unfair made fair" cases,
and B_currency_replacement makes fewer of the latter than recorded (e.g. offense 370 → 285). The recorded reading
("B converts more unfair trades to fair than the incumbent does") still holds in every class.

### 4.3 Starter-only base trades (F2), the share B_currency_replacement re-levels

| class | v1 | v2 same board | v2 current | excluding 1-for-1, v1 → v2 sb |
|---|---|---|---|---|
| offense (420 bases) | 37.1% (156) | 40.5% (170) | 40.7% (171) | 52.0% → 56.7% |
| IDP (304) | 35.9% (109) | 42.1% (128) | 40.8% (124) | 50.9% → 59.8% |
| mixed (391) | 41.7% (163) | 45.3% (177) | 44.8% (175) | 54.1% → 58.8% |

### 4.4 The "naive shadow disclosure rule" ("fire when B_currency_replacement would change the verdict")

| sweetener class | cases | fires, v1 | fires, v2 same board | fires, v2 current |
|---|---:|---|---|---|
| filler | 11,140 | 6,586 (59.1%) | 4,400 (39.5%) | 4,364 (39.2%) |
| usable depth | 11,300 | 2,118 (18.7%) | 1,116 (9.9%) | 1,112 (9.8%) |
| genuine starter | 9,740 | 1,249 (12.8%) | 700 (7.2%) | 699 (7.2%) |

The memo's "19% of depth, 13% of starter cases" is **10% and 7%** under v2. Calculator-sample fires: 657 → 723 of
2,000. Trade-history fires: 67 → 65 (band-independent; Hunter).

### 4.5 Real players (memo §4 table; gap unchanged, level re-read; v1 → v2)

| trade | GEOM_78 | B_currency_replacement | A_curve_market |
|---|---|---|---|
| Hurts (5,919) vs Egbuka (5,197) | +722 unfair → unfair | +722 unfair → unfair | +671 unfair → unfair |
| … + Hodgins | +22 fair → fair | +424 slight → slight | +455 slight → **unfair** |
| … + four ~900 fillers | −1,300 unfair → **lopsided** | −179 fair → fair | +41 fair → fair |
| Gibbs vs Smith + Higgins | +1,071 unfair → unfair | +1,309 unfair → unfair | +1,943 unfair → **lopsided** |
| … + four ~1,000 fillers | −674 slight → slight | +497 fair → **slight** | +1,360 slight → **unfair** |
| Gibbs vs Young + Kraft (two starters) | +129 fair → fair | +356 fair → **slight** | +1,072 slight → **unfair** |
| Gibbs vs six ~2,950 starters / depth | −564 fair → **slight** | +871 slight → slight | +1,977 unfair → **lopsided** |
| Wilson vs Ferguson + Kelce | +221 fair → fair | +749 unfair → unfair | +961 unfair → **lopsided** |
| Schwesinger vs Baun + Parsons | +176 fair → fair | +658 slight → **unfair** | +903 unfair → **lopsided** |
| 2027 1.04 vs 1.12 + two 4th-round picks | −791 unfair → unfair | +22 fair → fair | +241 fair → fair |
| Boston (WR) vs Bailey (DL) + two DB fillers | −832 unfair → unfair | +43 fair → fair | +81 fair → fair |

The evidence holds 15 real-player cases; four further rows changed and are not shown (Rookie-pick 1: B 279 fair → slight, A 844 slight → unfair; IDP-depth 1: A 1,150 unfair → lopsided; Love vs picks: A 640 slight → unfair), none for the incumbent. "B fixes pick sweeteners" is therefore weaker for Rookie-pick 1 (fair → slight).

Two memo sentences are therefore reworded: the Hurts + four fillers example is "lopsided the other way" (not
"unfair"), and "B fixes the real filler cases" holds for Hurts, the pick sweeteners and the DB fillers but **not** for
the Gibbs + four ~1,000 fillers case, where B now lands on "slight" rather than "fair". Gibbs vs six starters reads
"slight" for the incumbent itself under v2. The conclusion ("B fixes some filler cases and re-levels legitimate depth")
is unchanged.

### 4.6 Other surfaces (context-free, today's board)

| surface (memo §4 / §9) | recorded (v1) | v2 same board | v2 current |
|---|---|---|---|
| Calculator: levels changed, B / A (2,000 trades) | 622–657 / 827–852 | 723–742 / 964–983 | 722–742 / 965–976 |
| Calculator: incumbent level mix fair / slight / unfair / lopsided | 429 / 485 / 665 / 421 | 386 / 379 / 655 / 580 | 385 / 381 / 654 / 580 |
| Calculator: leader flipped (not a fairness level) | unchanged on all bases | | |
| Trade Finder top-10 overlap, B market: scan / all shapes / best offers / builder | .78 / .34 / .52 / .43 | .78 / .34 / .52 / .43 | .78 / .34 / .52 / .43 |
| Trade Finder top-10 overlap, A market | .56 / .14 / .33 / .32 | .56 / .14 / .33 / .33 | .56 / .14 / .33 / .33 |
| Star-for-pile recommendations, any treatment | 0 | 0 | 0 |
| Trade History grade buckets changed, B / A (150 fully priced sides) | 57 / 84 | band-independent: 55 / 84 | 55 / 84 |
| Public category (shadow), B / A of 180 | 43–45 / 84–92 | 37–40 / 65–76 | 37–40 / 65–76 |

On the package scan, all-shapes finder and best offers, the overlap, lost-sensible-depth and appear / disappear counts are the
finder's own selection and do not move with the band; only the level histograms do (for the incumbent, e.g. best
offers: lopsided 108 → 114). The star-builder surface uses the band in its package selection and moves slightly (overlap
A .317 → .333, B .425 → .433).

### 4.7 War Room and forced-drop diagnostic (investigation A)

War Room (Team Context ON at the 58 cap, 45 samples, 135 sweetened steps): **133 asset-only flips; 85 neutralised, 43
over-corrected, 5 survive — identical under v1, v2 same board and v2 current.** Median release charge 3,128 against a
median filler credit 1,982; ratio 1.65. The counts coincide, consistent with the 250 absolute floor deciding fair / not-fair at these base sizes (below a base of about 7,143, 3.5% is under 250, and the sampled starters sit at 2,500-6,500 with a counterpart at 86-97% of them), so the v1 and v2 denominators cannot move the fair crossing there. This is reasoning, not instrumentation; the public-category shadow
(§4.6), which runs the same engine, does move, so the basis switch is in effect on this path.

Forced-drop counterfactuals (same 133 flips), v1 → v2:

| variant | neutralised | over-corrected | survive |
|---|---|---|---|
| production | 85 → 85 | 43 → 43 | 5 → 5 |
| V1 cheapest legal cut | 21 → 19 | 2 → 4 | 110 → 110 |
| V2a unpriced charged 0 | 60 → 61 | 38 → 38 | 35 → 34 |
| V2b unpriced at board floor | 64 → 67 | 38 → 38 | 31 → 28 |
| V3a V1 + V2a | 5 → 4 | 0 → 1 | 128 → 128 |
| V3b V1 + V2b | 6 → 5 | 0 → 1 | 127 → 127 |
| V4 package-consistent | 1 → 1 | 0 → 0 | 132 → 132 |

Two sentences move. "V1 alone removes 41 of the 43 over-corrections" is **39 of 43** (V1 leaves 4). The attribution
table becomes selection-only 34, either fix 5, both required 3, package-consistent accounting 1 (was 36 / 5 / 2 / 0).
"With the cheapest legal cut, 110 of 133 flips survive" is unchanged.

## 5. Statements in the 2026-10-20 memo that this addendum supersedes

The memo body is not rewritten; read these as corrected.

| memo location | recorded (v1) | corrected (v2; same-board / current main) |
|---|---|---|
| §0 Q1 "re-level 31–42% of starter-only trades" | 31–42% | 40–53% |
| §0 Q1 "each also removes 7–14% of appropriate depth flips" | 7–14% | 7–15% (still ≤ 25%, F3 passes) |
| §0 Q4 Hurts example | "four of them reach −1,300, unfair the other way" | "lopsided the other way" |
| §4 "GEOM_78 flips ... 3,017 filler / 3,047 depth" (offense) | 3,017 / 3,047 | 3,002 / 3,029 (current main: 2,999 / 3,029) |
| §4 Real players table | see §4.5 | see §4.5 |
| §4 calculator "622–657 / 827–852" | 622–657 / 827–852 | 723–742 / 964–983 |
| §4 Public category "43–45 / 84–92 of 180" | 43–45 / 84–92 | 37–40 / 65–76 |
| §5.2 counterfactual table, "41 of 43" | see §4.7 | see §4.7 |
| §8 R-B F1 "at most 23%" | 23.1% | 24.6% / 25.2% (all treatments 29.0%) |
| §8 R-B F2 "37–42%" | 37.1–41.7% | 40.5–45.3% / 39.8–44.8% |
| §9 comparison: F1 A 20–28%, B 14–23% | 20–28 / 14–23 | A 20–29, B 15–25 |
| §9 comparison: F2 A 31–40%, B 36–42% | 31–40 / 36–42 | A 44–53, B 40–45 |
| §11 naive rule "19% of depth cases and 13% of starter cases" | 19% / 13% | 10% / 7% |

Not affected (they use no fairness band): §2 lineup utility, §3 value dynamics, §6 investigation B, §7 the box run
(M1–M4 are signed residuals; the box script classifies no band and its pinned code is the recorded `348313b1c`),
the own-league Trade History grades, and the mathematical properties table (113 / 113 leaves equal).

## 6. Verdict on each frozen rule

### 6.1 R-A — recommend investigating a canonical-curve change: **not met, unchanged**
Its conditions are D (value dynamics), M3 (served-history retention) and U (lineup utility). None reads a fairness
band, and none was re-run: their evidence files do not depend on the denominator. The F-study does not feed R-A.

### 6.2 R-B — recommend a specific B treatment on context-free surfaces: **not met, unchanged**
- F1 (≥ 80%): fails by a wide margin. The best any treatment achieves is 29.0% (A_curve_market, offense), and the
  best B treatment in offense / mixed 24.6% (same board) / 25.2% (current). Recorded: 27.8% / 23.1%.
- F2 (≤ 2%): fails by **more** than recorded (40–53% against 31–42%). The v2 base is the larger package
  UTILITY, which is smaller than the larger adjusted side on a multi-piece trade, so a gap reads as a larger
  percentage and more starter-only trades sit across a cut point when a treatment shifts them.
- F3 (≤ 25%): passes everywhere, as recorded.
- M1 passes, M2 fails, T not demonstrated: none of the three reads a band, so they are unchanged.
The F-study therefore alters **no** frozen-rule outcome; it strengthens the F2 reason for R-B's failure.

### 6.3 R-B0 — Team Context sufficient on team-aware surfaces: **holds, unchanged**
The War Room counts (133 / 85 / 43 / 5) are identical under v1 and v2, so the rule's frozen test is met exactly as
recorded. Investigation A's conclusion (the mis-specified forced-drop charge produces most of the neutralisation)
stands; its counterfactual cells move by at most 3 steps (§4.7), and one sentence changes from 41 to 39 of 43.

### 6.4 R-C — informational only: **still supported**
R-C applies when neither R-A nor R-B is met, or when IDP or picks are insufficient for a class-wide change. R-A and
R-B are still not met, and the IDP (138 graded trades) and pick-only (81) samples are unchanged, so R-C is selected by
the same frozen reasoning. Nothing was forced: the corrected evidence did not move any condition across its line.

Two qualifications, stated plainly rather than smoothed over:
1. The memo's quantitative argument against the *naive* shadow rule was "it fires on 19% of depth cases and 13% of
   starter cases". Under v2 those are **10% and 7%** (and 39% of filler cases). The rule is still a poor disclosure
   trigger: it is keyed to a treatment that itself fails F2, and a trigger that fires on one genuine-starter sweetener
   in fourteen is not a disclosure rule. But the "19% / 13%" numbers should no longer be quoted. The classification-based,
   league-aware trigger recommended in memo §11 does not depend on those numbers.
2. The v1-era reading of B's "fixes" is weaker in one real-player case (Gibbs + four ~1,000 fillers; §4.5). It does not
   change any rule.

PR #1887 (disclosure design) already runs on v2 and is consistent with these corrected figures.

## 7. Preventing recurrence (no competing math owner)

No fairness formula was added. `tests/scripts/test_research_band_basis_guard.py`:
- fails any `scripts/*.py` outside an explicit, annotated allow-list that loads a research module exposing the legacy
  level (`package_model_hybrid_research`, `…phase2…`, `…phase3…`), names `level_v1_legacy` /
  `legacy_v1_denominator`, or passes an adjusted-side / `max(...)` base to an owner band call (it reuses the existing
  `_py_offenders` detector from `test_fairness_bands.py`, one definition);
- fails stale allow-list entries (each must still reach the legacy basis, and carry a reason);
- pins that the legacy helper is marked LEGACY (`FAIRNESS_BAND_BASIS = "v1_legacy"`, docstring) and that
  `legacy_v1_denominator()` is scoped and restores the owner;
- pins that the replay's DEFAULT basis is the owner (declares `FAIRNESS_BAND_BASIS = "current_owner"`), that the
  current verdict never calls the legacy helper, that it equals the owner's `classify_packages` / `fairness_base` +
  `classify`, and that the replay source contains no band threshold literal.

## 8. How to reproduce

```text
E=docs/valuation/evidence/low_value_assets_2026-10-20/v2_correction
A=exports/archive/dynasty_export_20261020_052241.zip
R=1511ca1d08dfffad4b48d113b2ac9a20d7a5de4b
python scripts/low_value_asset_shadow_replay.py --band-basis v1_legacy --archive $A --csv-rev $R --value-override "Travis Hunter=3738" --out $E/shadow_replay_v1_reproduction.json
python scripts/low_value_asset_shadow_replay.py --band-basis current   --archive $A --csv-rev $R --value-override "Travis Hunter=3738" --out $E/shadow_replay_v2_same_board.json
python scripts/low_value_asset_shadow_replay.py --band-basis current   --archive $A --csv-rev $R --out $E/shadow_replay_v2_current.json
python scripts/low_value_asset_forced_drop_diagnostic.py --band-basis v1_legacy --csv-rev $R --out $E/forced_drop_diagnostic_v1_reproduction.json
python scripts/low_value_asset_forced_drop_diagnostic.py --band-basis current   --csv-rev $R --out $E/forced_drop_diagnostic_v2_current.json
python scripts/low_value_asset_v2_correction_summary.py --run v1_reproduction=$E/shadow_replay_v1_reproduction.json --run v2_same_board=$E/shadow_replay_v2_same_board.json --run v2_current=$E/shadow_replay_v2_current.json --reproduction v1_reproduction --out $E/comparison.json
```

Each shadow-replay run takes about 8-10 minutes on a shared 4-CPU host (the Trade Finder replay dominates); the
diagnostics take about a minute. The runs recorded here were produced at base commit `deed0aad0` plus this PR's script
changes (the `codeSha` field in the run files is the base commit; the switch itself is the diff of this PR).

## 9. Limits and what is not claimed

- One board (2026-10-20), exploratory, context-free surfaces: unchanged from the original.
- The CSV revision is the one PR #1887 found to reproduce this board; the original run did not record its tree. The
  reproduction (3,395 of 3,465 leaves, every study count) is the evidence that it is the same board for these purposes.
- On the engine paths the `v1_legacy` basis is a scoped rebind of the owner's base function (`legacy_v1_denominator`)
  over **today's** engine code, not the engine of 2026-10-20. Where the engine itself drifted (3 `UNAVAILABLE` public
  categories, the star-builder surface) those differences are in R0 too and are reported as drift, not band.
- The League-scoped boards, the box run and the prospective population are not re-run: none depends on a band.
- Phase 1–3 package-model research (`PACKAGE_MODEL_*_RESEARCH_*.md`) was also measured on the v1 denominator. It is out
  of scope here and was not re-measured; its conclusions are not asserted either way (§10 UNRESOLVED).
- The forced-drop descriptive flags differ slightly from the recorded file for a reason that is not the band (§3).

## 10. UNRESOLVED

- Whether the Phase 1–3 package-model research (`docs/valuation/PACKAGE_MODEL_{HYBRID,PHASE2,PHASE3}_RESEARCH_*.md`),
  recorded on v1, should be re-measured under v2: an owner / Integration scope decision, not made here.
- The three forced-drop descriptive-flag differences (§3) are consistent with the `roster_capacity.py` change in
  `d25772c0d` but were not bisected.
- Owner review of this addendum; nothing is activated by it.

## Appendix A — full F-study criteria (v1 recorded / v2 same board / v2 current, percent)

| class | treatment | F1 filler flips removed | F2 starter-only levels changed | F3 depth flips removed |
|---|---|---|---|---|
| offense | `B_currency_replacement` | 21.5 / 22.6 / 23.0 | 37.1 / 40.5 / 40.7 | 12.2 / 12.6 / 12.7 |
| offense | `B_currency_market` | 23.1 / 24.6 / 25.2 | 37.4 / 40.5 / 39.8 | 13.1 / 13.7 / 13.6 |
| offense | `A_curve_replacement` | 25.4 / 27.2 / 27.7 | 36.9 / 48.6 / 48.6 | 12.6 / 14.2 / 14.2 |
| offense | `A_curve_market` | 27.8 / 29.0 / 29.0 | 33.8 / 47.1 / 46.7 | 14.4 / 15.0 / 15.0 |
| idp | `B_currency_replacement` | 18.6 / 19.2 / 19.5 | 35.9 / 42.1 / 40.8 | 9.0 / 9.1 / 10.4 |
| idp | `B_currency_market` | 18.4 / 18.8 / 18.9 | 36.2 / 40.8 / 40.8 | 9.0 / 9.0 / 10.5 |
| idp | `A_curve_replacement` | 21.0 / 21.9 / 22.1 | 30.6 / 44.1 / 44.7 | 8.6 / 8.8 / 9.7 |
| idp | `A_curve_market` | 19.7 / 20.4 / 21.0 | 30.6 / 44.4 / 44.7 | 8.5 / 8.5 / 9.7 |
| picks | `B_currency_replacement` | 13.6 / 15.7 / 14.9 | n/a / n/a / n/a | 7.1 / 7.9 / 7.4 |
| picks | `B_currency_market` | 16.9 / 19.8 / 20.0 | n/a / n/a / n/a | 9.1 / 10.1 / 9.3 |
| picks | `A_curve_replacement` | 20.7 / 24.5 / 24.4 | n/a / n/a / n/a | 10.8 / 12.1 / 11.7 |
| picks | `A_curve_market` | 22.5 / 26.7 / 27.1 | n/a / n/a / n/a | 11.7 / 13.0 / 12.2 |
| mixed | `B_currency_replacement` | 20.9 / 21.6 / 21.6 | 41.7 / 45.3 / 44.8 | 10.1 / 10.2 / 10.3 |
| mixed | `B_currency_market` | 21.2 / 22.5 / 22.3 | 38.9 / 44.5 / 42.5 | 10.0 / 10.6 / 10.9 |
| mixed | `A_curve_replacement` | 25.8 / 27.5 / 27.5 | 40.2 / 52.9 / 53.4 | 11.3 / 12.3 / 13.0 |
| mixed | `A_curve_market` | 24.6 / 27.0 / 26.9 | 35.5 / 50.6 / 50.9 | 10.7 / 12.0 / 12.6 |

## Appendix B — fairness-level computation inventory (C1)

Counts (35 rows): production code 14 (0 inconsistent with the band owner; three are differently-named concepts, see the last rows of C1.1), current research
accidentally on the legacy denominator 4 (three places in the replay plus the forced-drop diagnostic; all repaired),
historical research intentionally preserving v1 5, band-independent research 3, tests / fixtures 4 groups,
documentation / evidence 5 groups. Nothing in production code was edited; no production inconsistency was found.

### C1.1 Production code (read-only audit; nothing edited)

| file:line | what it does | classification | action |
|---|---|---|---|
| `src/valuation_math/fairness_bands.py` (whole file; `classify` :246, `larger_package_utility` :218, `classify_packages` :294) | the ONE band owner; base = larger PACKAGE UTILITY | production, owner | none |
| `src/trade/analyze_trade.py:175-176` | market lens: `larger_package_utility` then `classify` | production, consistent with v2 | none |
| `src/trade/trade_decision.py:505` | Component A: `classify(net, larger_utility)`; `larger_utility` = the lens's `largerPackageUtility` | production, consistent | none |
| `src/trade/trade_decision.py:519,638` | publishes `largerAdjustedSide` | production, DISPLAY number only (v1's base, no longer decides anything) | none; research must not read it as the band base |
| `src/trade/trade_decision.py:829` | `classify(net, larger_package_utility(send, recv))` | production, consistent | none |
| `src/trade/decision_engine/terms.py:104,152,165,204` | `larger_package_utility` then `classify`; `largerAdjustedSide` display | production, consistent | none |
| `src/trade/team_verdicts.py:165-221` | reads the lens's band and `largerPackageUtility` (`fairness_base`); `largerAdjustedSide` display | production, consistent | none |
| `src/trade/suggestions.py:1597`, `src/trade/best_offers.py:121-176` | `larger_package_utility` / `ABSOLUTE_MINIMUM` from the owner | production, consistent | none |
| `src/trade/public_advisor.py:810-812` | key allow-list that strips `largerAdjustedSide`, `relativePct` from public output | production, display | none |
| `frontend/lib/fairness-bands.js` | JS mirror, pinned to the owner by `tests/valuation_math/test_fairness_bands.py` | production, mirror | none |
| `frontend/lib/trade-logic.js:938-2515`, `frontend/lib/va-comparison.js:93`, `frontend/app/trade/page.jsx:1275-1278`, `frontend/components/trade/{TradeMeter,TradeFairnessExplanation}.jsx` | `classifyGap(gap, largerUtility)` / `meterVerdict` with `sideTotalsFairnessBase` / `fairnessBase(packageUtilities(...))` | production, consistent (scanned by `OneDenominatorOwner` in `tests/valuation_math/test_fairness_bands.py`) | none |
| `frontend/lib/second-opinions.js:371-381` (`OPINION_EVEN_TOLERANCE_PCT` = 1) | Second Opinions "even" = within 1% of the larger ADJUSTED side | production, a DIFFERENT named concept (TC-C decision 4), not a fairness level | none; noted so it is not mistaken for the band |

| `src/public_league/trade_grading.py:54-58` (`_GRADE_PCT_FAIR` = 3.0, SLIGHT 8, GOOD 15, CLEAR 25, ROBBERY 40; `grade_from_pct`, `grade_trade_sides`) and `frontend/lib/league-analysis.js:93-104,449-470,622-655` (`gradeTradeHistorySide`, `pct < 3`, per-side W/L rule at +/-3) | historical trade grade: percentage of the larger EFFECTIVE side, no 250 floor | production, a DIFFERENT named concept (history grade). **OD-F6 is open** (`docs/OWNER_REQUESTED_TODO.md`, `docs/EXECUTION_PLAN.md`, `docs/WORK_CLAIMS.md`); it is not a `fairness_bands` consumer and is deliberately NOT changed here | none; workstream D measures its effect read-only |

**No production-code inconsistency with the band owner found.** Every production path that produces a fairness level takes its base from the owner.

### C1.2 Research code

| file:line | what it does | classification | action taken |
|---|---|---|---|
| `scripts/package_model_hybrid_research.py:395` (was `level`) | `classify(gap, max(adj_a, adj_b))` | historical research, intentionally v1 (Phase 1, 2026-10-19) | renamed `level_v1_legacy`, docstring marks it LEGACY, `FAIRNESS_BAND_BASIS = "v1_legacy"`; `level` kept as an alias so frozen callers run unchanged |
| `scripts/package_model_phase2_research.py:140,255,280,378` | `P1.level` (v1) | historical research, intentionally v1 | allow-listed with reason |
| `scripts/package_model_phase3_local.py:333,526,580` | `P1.level`, `level=P2.level` (v1) | historical research, intentionally v1 | allow-listed with reason |
| `scripts/package_model_phase3_research.py` | loads Phase 2 module | historical research, v1 by inheritance | allow-listed with reason |
| `scripts/low_value_asset_shadow_replay.py` `verdict()` (was `P1.level`) | LVA verdict: v1 via `S.verdict -> T.gap -> P1.level` | **current research accidentally on the legacy denominator** | fixed: `--band-basis current` (default) reads the owner; `v1_legacy` kept for reproduction |
| `scripts/low_value_asset_shadow_replay.py` `_replay_chunk` (was `level=P2.level`) | Trade Finder replay tags | **current research accidentally on v1** | fixed (same switch) |
| `scripts/low_value_asset_shadow_replay.py` `war_room()` | production engine; at record time the engine was v1, since train 17 it is v2 | **current research; the recorded numbers were v1, the code is now v2** | basis switch wraps the engine in `legacy_v1_denominator()` for reproduction |
| `scripts/low_value_asset_forced_drop_diagnostic.py:111,306-324` (was `largerAdjustedSide`) | counterfactual variants classified against the larger ADJUSTED side while the production path used the engine's band | **current research accidentally on the legacy denominator (internally inconsistent since v2)** | fixed: reads `largerPackageUtility`; same switch |
| `scripts/low_value_asset_box.py` | confirmatory box run; M1-M4 use signed residuals, no band | historical, band-independent | allow-listed (loads the Phase 3 module); no band number to correct |
| `scripts/low_value_asset_{treatments,idp_anomaly,lineup_utility,value_dynamics}.py` | no fairness band | band-independent | none |
| `scripts/measure_fairness_band_change.py:85-162, about 765 (`v1Base`) and about 1104 (`base = max(sendAdjusted, recvAdjusted)`) | measures v1 vs v2 on purpose (`_old_classify`, `relativePct` on the larger adjusted side next to `relativePctUtility`) | historical/measurement research, intentionally preserves v1 | none (it is the v1-vs-v2 comparator) |
| `scripts/package_model_finder_replay.py:77-214` | takes a `level` callable | harness, no band of its own | none |

### C1.3 Tests

| file:line | classification | action |
|---|---|---|
| `tests/valuation_math/test_fairness_bands.py:326-380` (`OneDenominatorOwner`) | test of production code; scans `src/` and `frontend/` | extended in spirit by the new research guard (it reuses its detector) |
| `tests/trade/decision_engine/test_terms_and_policy.py:38` | test fixture: `classify(gap, max(sum(send), sum(recv)))` | holds only because every parametrised case is 1-for-1 (utility = raw total); latent, not wrong. Reported, not edited |
| `tests/trade/test_balancer_uses_adjusted_gap.py:128` | `fairness_bands.is_even(gap, max(give_adj, recv_adj))` while production `src/trade/suggestions.py:1597` uses `larger_package_utility` | latent: agrees on all six `_SHAPES` today (independent review), would diverge on a borderline shape. Reported, not edited |
| `src/trade/symmetrize.py:203` (`ratio > 0.03`, tier impact) | not a fairness level: a raw-delta share | none; noted so it is not mistaken for the band |
| `tests/trade/test_team_verdicts.py:164-187`, `test_analyze_multi_team.py:85-97`, `test_multi_team_*` | fixtures asserting the published display field `largerAdjustedSide` | test fixtures of production display fields | none |
| `tests/scripts/test_package_model_hybrid_research.py`, `test_package_model_phase2_research.py`, `test_low_value_asset_box.py`, `test_research_readonly_guard.py` | load the historical research modules | test fixtures | none |

### C1.4 Documentation and evidence

| file | classification | action |
|---|---|---|
| `docs/valuation/LOW_VALUE_ASSET_RESEARCH_2026-10-20.md` §4, §8, §11 | documentation carrying v1-basis numbers | pointer to the correction addendum added; body not rewritten |
| `docs/valuation/evidence/low_value_assets_2026-10-20/shadow_replay.json`, `forced_drop_diagnostic.json` | historical evidence, v1 | preserved; superseded-by pointer in the addendum; new evidence in `v2_correction/` |
| `docs/valuation/evidence/low_value_assets_2026-10-20/{lineup_utility,value_dynamics,idp_anomaly,production_box_run_2026-10-20}.json` | band-independent evidence | none |
| `docs/valuation/PACKAGE_MODEL_{HYBRID_RESEARCH_2026-10-19,PHASE2_RESEARCH_2026-10-19,PHASE3_RESEARCH_2026-10-20}.md` | historical documentation, v1 | none (out of scope; listed under UNRESOLVED) |
| `docs/owner/BRISKET_TRADE_ADVISOR_DESIGN_2026-10-19.md`, `docs/trade/NTEAM_TRADE_ENGINE_SPEC.md` (v1 passages), `docs/trade/advisor_evidence/FAIRNESS_THRESHOLD_RESEARCH.md`, `docs/trade/TRADE_ADVISOR_MULTITEAM_REPORT.md` | historical documentation naming `fairness_bands_v1` | none; each already says v2 supersedes |
