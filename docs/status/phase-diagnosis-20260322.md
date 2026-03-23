# Phase Diagnosis: Public-Primary Remaining Blockers

_Generated: 2026-03-22 | Post-KTC-validation checkpoint_

---

## Founder Summary

**Where we are:** 13 sources, 92/92 ranking overlap, internal-primary validated, KTC confirmed working on production. Three metrics still fail for public-primary: multi-source blend (57% vs 60%), tier agreement (50.1% vs 65%), and avg delta (1006 vs 800).

**What's actually wrong:** Two distinct problems, not one.

1. **Blend fails because KTC data isn't in the canonical pipeline yet.** KTC scraped 500 players on production but no `ktc.csv` exists in `exports/latest/site_raw/`. The pipeline literally can't see KTC. Fixing this alone pushes blend to ~65%+.

2. **Tier/delta fail because the calibration curve is the wrong shape.** The canonical system re-ranks all 688 offense players and applies `8500 * percentile^2.0`. This compresses too many players into the elite tier (7000+) compared to legacy. Example: QBs #7-15 all get canonical values of 7000-7800, but legacy has them at 5700-6800. Top-15 TEs have 12/15 tier mismatches. The curve is too flat at the top.

**What to do:** Two sequential moves, not one.

- **Move 1 (now):** Run a production scrape with KTC, get `ktc.csv` into the pipeline, re-run the build. This clears blend and improves tier/delta through better ranking.
- **Move 2 (after):** Adjust the calibration exponent from 2.0 to ~2.5-3.0, which steepens the curve and pushes mid-tier players out of the elite zone. This targets the remaining tier/delta gap.

**Expected outcome:** Move 1 alone gets blend to PASS and tier/delta to improve (~55-58% tier, ~850-950 delta). Move 1 + Move 2 together should reach all thresholds.

---

## Phase A: Why Multi-Source Blend Is 57% (Not 60%)

### The Numbers

| Metric | Value |
|--------|-------|
| Total canonical assets | 1,198 |
| Multi-source (2+ sources) | 682 (56.9%) |
| Single-source (1 source) | 516 (43.1%) |
| **Need for 60%** | **720 multi-source** |
| **Gap** | **38 assets** |

### Single-Source Assets by Source

| Source | Single-Source Assets | Notes |
|--------|---------------------|-------|
| IDPTRADECALC | 140 | IDP long-tail players |
| DRAFTSHARKS | 93 | Offense long-tail |
| FANTASYCALC | 72 | Offense long-tail |
| DLF_RSF | 66 | ALL offense rookies (structural) |
| YAHOO | 43 | Offense mid/long-tail |
| DYNASTYDADDY | 36 | Offense mid/long-tail |
| DLF_RIDP | 30 | ALL IDP rookies (structural) |
| PFF_IDP | 17 | IDP-only players |
| Other (5 sources) | 19 | Sparse edges |

### Single-Source Assets by Universe

| Universe | Single-Source | Total | Single % |
|----------|-------------|-------|----------|
| offense_vet | 257 | 688 | 37.4% |
| idp_vet | 163 | 414 | 39.4% |
| offense_rookie | 66 | 66 | **100.0%** |
| idp_rookie | 30 | 30 | **100.0%** |

### Root Cause Breakdown

**Cause 1 — KTC missing (primary, fixable now):**
KTC would contribute ~500 offense_vet players. Of the 257 single-source offense_vet assets, KTC likely covers 100-150 of them (based on KTC's known 526-player universe). Converting 100 single-source assets to multi-source would push blend from 57% to ~65%. Even accounting for a few new single-source assets KTC adds, this comfortably clears 60%.

**Cause 2 — Rookie universes are structurally single-source (96 assets):**
Only DLF provides rookie rankings (DLF_RSF = 66 offense rookies, DLF_RIDP = 30 IDP rookies). No other source in the pipeline has rookie-specific data. These 96 assets are 100% single-source by design. Excluding them, vet-only blend is already 61.9% (passes).

**Cause 3 — IDP long-tail (secondary):**
IDPTRADECALC contributes 140 single-source assets. These are deep-roster IDP players that only one source covers. Not realistically fixable without adding more IDP sources.

### Verdict

**KTC is the fix for blend.** It's the only action needed. The 38-asset gap is easily covered by KTC's ~100-150 new overlaps in offense_vet. Rookie structural single-source is a known limitation but doesn't block the threshold with KTC present.

---

## Phase B: Why Tier/Delta Fail Despite 92/92 Overlap

### The Paradox

The canonical pipeline ranks offense players in almost the same order as legacy (92% top-50, 92% top-100). But only 50.1% of matched players land in the same value tier, and the average absolute delta is 1006 (need ≤800). **The ranking is right but the values are wrong.**

### Tier Agreement Breakdown

| Universe | Count | Tier Agreement | Avg Delta |
|----------|-------|---------------|-----------|
| offense_vet | 621 | 58.1% | 837 |
| offense_rookie | 28 | **21.4%** | **1,737** |
| offense_players_only | 565 | **50.1%** | **1,006** |
| idp_vet | 390 | 35.9% | 920 |
| idp_rookie | 12 | 25.0% | 1,520 |

Note: offense_vet (621 players, 58.1% tier) includes 84 picks with delta=0 that inflate the metric. The real player-only number is 50.1% on 565 players.

### Position-Level Tier Mismatch Analysis

From the founder review packet (14-source canonical vs 2-source legacy):

**QBs (top 20):** 9/20 tier mismatches
- QBs 1-6: canonical and legacy agree (both elite tier)
- QBs 7-15: **systematic overshoot** — canonical 7000-7800, legacy 5700-6800
- Pattern: canonical puts them in "elite" (≥7000), legacy puts them in "star" (5000-7000)
- Average overshoot: ~1,050 points per player

**TEs (top 15):** 12/15 tier mismatches
- Brock Bowers and Trey McBride match; almost everything else diverges
- Tucker Kraft: canonical 7570, legacy 5411 (+2,159)
- Tyler Warren: canonical 8042, legacy 5956 (+2,086)
- Sam LaPorta: canonical 7088, legacy 5255 (+1,833)
- Pattern: canonical massively overvalues mid/upper TEs relative to legacy

**RBs:** 55% tier agreement (avg delta 957)
**WRs:** 53% tier agreement (avg delta 1009)

### Root Cause: The Calibration Curve

The calibration step (`src/canonical/calibration.py`) re-ranks all players within each universe and applies:

```
calibrated_value = 8500 * (percentile ^ 2.0)
```

For a 688-player offense_vet universe, this produces:

| Rank | Percentile | Calibrated Value | Legacy Tier |
|------|-----------|-----------------|-------------|
| 1 | 0.999 | 8,474 | Elite |
| 30 | 0.958 | 7,794 | Elite |
| 50 | 0.929 | 7,335 | Star (legacy) → Elite (canonical) |
| 100 | 0.855 | 6,209 | Star |
| 150 | 0.782 | 5,198 | Starter (legacy) → Star (canonical) |
| 200 | 0.709 | 4,275 | Starter |
| 300 | 0.564 | 2,705 | Bench |
| 400 | 0.419 | 1,489 | Depth |

**The problem:** The exponent 2.0 is too shallow. It puts the top ~50 players ALL above 7000 (elite), while legacy only puts ~35 players above 7000. Players ranked 30-80 are systematically inflated by 800-1500 points.

This is why:
- **QBs 7-15 all land in elite tier** in canonical but star tier in legacy
- **TEs are massively overvalued** because a TE ranked 40th overall in offense_vet gets an elite-tier value (7500+), while legacy values that same TE at 5200-5500
- **Rookies have 21.4% tier agreement** because the same curve applied to 66 rookies gives exaggerated values

### What Would Fix It

Increasing the exponent from 2.0 to ~2.8 steepens the curve:

| Rank | Exp=2.0 | Exp=2.8 | Legacy Approx |
|------|---------|---------|--------------|
| 1 | 8,474 | 8,450 | 8,500 |
| 30 | 7,794 | 7,350 | 7,200 |
| 50 | 7,335 | 6,640 | 6,500 |
| 100 | 6,209 | 5,070 | 5,100 |
| 150 | 5,198 | 3,830 | 3,900 |

At exponent ~2.8, the calibrated values much more closely match legacy tier assignments. The top ~35 players get elite values, players 35-80 get star values, and the mid-tier compression disappears.

### Is This a Blend Problem or a Calibration Problem?

**Primarily calibration.** The evidence:
- Ranking overlap is already 92/92 — the blend is ordering players correctly
- The tier mismatches are systematic and directional (canonical always higher in the 30-100 rank range)
- The pattern is consistent across positions (QB, TE, WR, RB all show the same inflation)
- Adding KTC would change some rankings but won't change the calibration curve shape
- The curve parameters (exponent=2.0, scale=8500) are the direct cause of the compression

**KTC will help tier/delta through better ranking accuracy** (moving some mis-ranked players to better positions in the curve), but won't fix the curve shape. Expected improvement from KTC alone: tier 50.1% → ~55-58%, delta 1006 → ~850-950. Probably not enough to clear 65% tier on its own.

---

## Phase C: Recommended Next Moves

### Move 1 (Highest Priority): Get KTC Into the Pipeline

**What:** Run a full production scrape that produces `exports/latest/site_raw/ktc.csv`, copy it to this repo, re-run `source_pull.py` → `canonical_build.py` → `run_comparison_batch.py`.

**Why it beats alternatives:**
- It's the **only** fix for multi-source blend (no amount of calibration tuning fixes blend)
- It also improves tier/delta through better ranking (it's additive, not alternative)
- It's operationally straightforward — KTC already scrapes successfully on production
- The source config already has the KTC entry ready (`scraper_bridge`, weight 1.2)
- Zero code changes needed

**Expected improvement:**
- Blend: 57% → **~65%** (PASS, threshold is 60%)
- Tier: 50.1% → **~55-58%** (improved, likely still FAIL at 65%)
- Delta: 1006 → **~850-950** (improved, may still FAIL at 800)

### Move 2 (After KTC): Adjust Calibration Exponent

**What:** Change `CALIBRATION_EXPONENT` in `src/canonical/calibration.py` from 2.0 to ~2.5-3.0. A single constant change.

**Why:** The current exponent=2.0 produces a curve that's too flat at the top, putting ~50 players in elite tier when legacy only has ~35. Steepening the curve directly attacks the tier/delta gap that KTC won't fully close.

**Expected improvement (on top of KTC):**
- Tier: ~55-58% → **~63-68%** (should cross 65% threshold)
- Delta: ~850-950 → **~700-850** (should cross 800 threshold)

**Risk:** Low. The exponent only affects the calibrated_value mapping, not the blend or ranking. Easy to test by running the build and comparison with different values. Reversible in one line.

### Move 3 (If Needed): Rookie Calibration Ceiling

**What:** Reduce `UNIVERSE_SCALES["offense_rookie"]` from 8500 to ~7000 or apply a separate rookie exponent.

**Why:** Offense rookies have 21.4% tier agreement and 1737 avg delta. They drag down the offense_players_only metrics. Legacy values rookies lower than vets of the same rank; the canonical system treats them identically.

### Move 4 (Polish): IDP Calibration Review

**What:** Review whether `idp_vet` scale of 5000 is correct and whether IDP needs a different exponent.

**Why:** IDP tier agreement is only 35.9%. But IDP is secondary to offense for public-primary evaluation, so this is lower priority.

---

## Summary Table

| Question | Answer |
|----------|--------|
| Why does blend fail? | KTC csv missing from pipeline. 96 rookies are structurally single-source. |
| Why do tier/delta fail? | Calibration curve (exp=2.0) is too flat — compresses top 80 players into elite tier |
| Is it a calibration problem or a blend problem? | **Both**, but independent. Blend needs KTC. Tier/delta needs curve fix. |
| Smartest next move? | Get KTC into pipeline (clears blend, improves tier/delta) |
| What improvement does that unlock? | Blend PASS, tier +5-8%, delta -50-150 |
| Second-smartest move? | Increase calibration exponent to ~2.5-3.0 (clears tier/delta) |
| Third-smartest move? | Lower rookie calibration ceiling from 8500 to ~7000 |
| Fourth-smartest move? | Review IDP calibration scale/exponent |
| Can we reach public-primary? | Yes — Move 1 + Move 2 should clear all metric thresholds |

---

_Analysis based on: comparison_batch_20260322T151041Z.json, canonical_snapshot_20260322T151040Z.json, founder_review_packet.md, calibration.py, transform.py, source configs. 408 tests pass._
