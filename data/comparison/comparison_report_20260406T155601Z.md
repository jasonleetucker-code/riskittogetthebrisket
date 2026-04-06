# Canonical vs Legacy Comparison Report

_Generated: 2026-04-06 15:56 UTC_

- **Canonical snapshot**: `canonical_snapshot_20260406T062900Z.json`
- **Legacy data**: `legacy_data_2026-03-22.json`

---

## Bottom Line

The canonical pipeline **diverges significantly** from legacy values. Top-50 overlap is only 10%, tier agreement is 38.5%. This is expected when only 2 of 11+ sources are integrated.

---

## Key Numbers

| Metric | Value |
|--------|-------|
| Players matched | 859 |
| Canonical-only players | 125 |
| Legacy-only players | 310 |
| Average absolute delta | 2188 (out of 9999) |
| Median absolute delta | 1109 |
| 90th percentile delta | 5956 |
| Max delta | 9524 |
| Top-50 player overlap | 5/50 (10%) |
| Top-100 player overlap | 15/100 (15%) |
| Value tier agreement | 38.5% |

### Multi-source vs Single-source Quality

| Source Count | Players | Avg Delta |
|-------------|---------|-----------|
| Multi-source (2+) | 338 | 1107 |
| Single-source (1) | 521 | 2889 |

### Delta Distribution

| Range | Count | Interpretation |
|-------|-------|----------------|
| < 100 | 42 | Very close agreement |
| 100-300 | 72 | Minor difference |
| 300-600 | 147 | Moderate difference |
| 600-1200 | 183 | Significant difference |
| > 1200 | 415 | Major divergence |

### By Position

| Position | Players | Avg Delta |
|----------|---------|-----------|
| K | 23 | 4582 |
| RB | 117 | 3057 |
| P | 1 | 2821 |
| WR | 179 | 2697 |
| TE | 85 | 2241 |
| QB | 63 | 1832 |
| LB | 113 | 1670 |
| DL | 104 | 1643 |
| DB | 119 | 1284 |

---

## Top 15 Risers (canonical values HIGHER than legacy)

| Player | Canonical | Legacy | Delta | % | Sources |
|--------|-----------|--------|-------|---|---------|
| Jahan Dotson | 9849 | 325 | +9524 | +2930.5% | 1 |
| Colby Parkinson | 9684 | 539 | +9145 | +1696.7% | 1 |
| Chris Rodriguez | 9849 | 1340 | +8509 | +635.0% | 1 |
| Terrion Arnold | 9849 | 1577 | +8272 | +524.5% | 1 |
| Noah Gray | 8394 | 227 | +8167 | +3597.8% | 1 |
| Jacoby Brissett | 9849 | 1703 | +8146 | +478.3% | 1 |
| Nathaniel Dell | 9999 | 1941 | +8058 | +415.1% | 1 |
| Shavon Revel | 9347 | 1509 | +7838 | +519.4% | 1 |
| Cedric Tillman | 9999 | 2191 | +7808 | +356.4% | 1 |
| Marquise Brown | 9999 | 2264 | +7735 | +341.7% | 1 |
| Kool-Aid McKinstry | 9347 | 1671 | +7676 | +459.4% | 1 |
| Jaydon Blue | 9999 | 2387 | +7612 | +318.9% | 1 |
| Nate Wiggins | 9180 | 1594 | +7586 | +475.9% | 1 |
| Brashard Smith | 9849 | 2266 | +7583 | +334.6% | 1 |
| Tre Tucker | 9999 | 2506 | +7493 | +299.0% | 1 |

## Top 15 Fallers (canonical values LOWER than legacy)

| Player | Canonical | Legacy | Delta | % | Sources |
|--------|-----------|--------|-------|---|---------|
| Kevin Coleman | 537 | 3125 | -2588 | -82.8% | 1 |
| Barion Brown | 538 | 3116 | -2578 | -82.7% | 1 |
| Caullin Lacy | 419 | 2639 | -2220 | -84.1% | 1 |
| Tyren Montgomery | 421 | 2597 | -2176 | -83.8% | 1 |
| Noah Whittington | 492 | 2639 | -2147 | -81.4% | 1 |
| Rueben Bain | 1670 | 3763 | -2093 | -55.6% | 1 |
| Harrison Wallace | 531 | 2530 | -1999 | -79.0% | 1 |
| Romello Brinson | 404 | 2292 | -1888 | -82.4% | 1 |
| Jamarion Miller | 1153 | 2951 | -1798 | -60.9% | 1 |
| Jamal Haynes | 429 | 2149 | -1720 | -80.0% | 1 |
| Jaleel McLaughlin | 566 | 2240 | -1674 | -74.7% | 1 |
| Phil Mafah | 542 | 2200 | -1658 | -75.4% | 1 |
| Antonio Gibson | 1058 | 2650 | -1592 | -60.1% | 2 |
| Zavion Thomas | 417 | 1970 | -1553 | -78.8% | 1 |
| Anthony Richardson | 1293 | 2845 | -1552 | -54.6% | 1 |

## Top 20 Biggest Mismatches (by absolute delta)

| Player | Canonical | Legacy | Delta | Universe | Sources |
|--------|-----------|--------|-------|----------|---------|
| Jahan Dotson | 9849 | 325 | +9524 | idp_vet | 1 |
| Colby Parkinson | 9684 | 539 | +9145 | idp_vet | 1 |
| Chris Rodriguez | 9849 | 1340 | +8509 | idp_vet | 1 |
| Terrion Arnold | 9849 | 1577 | +8272 | idp_vet | 1 |
| Noah Gray | 8394 | 227 | +8167 | offense_vet | 1 |
| Jacoby Brissett | 9849 | 1703 | +8146 | idp_vet | 1 |
| Nathaniel Dell | 9999 | 1941 | +8058 | idp_vet | 1 |
| Shavon Revel | 9347 | 1509 | +7838 | idp_vet | 1 |
| Cedric Tillman | 9999 | 2191 | +7808 | idp_vet | 1 |
| Marquise Brown | 9999 | 2264 | +7735 | idp_vet | 1 |
| Kool-Aid McKinstry | 9347 | 1671 | +7676 | idp_vet | 1 |
| Jaydon Blue | 9999 | 2387 | +7612 | idp_vet | 1 |
| Nate Wiggins | 9180 | 1594 | +7586 | idp_vet | 1 |
| Brashard Smith | 9849 | 2266 | +7583 | idp_vet | 1 |
| Tre Tucker | 9999 | 2506 | +7493 | idp_vet | 1 |
| Jaylen Wright | 9999 | 2534 | +7465 | idp_vet | 1 |
| Cole Payton | 9515 | 2096 | +7419 | idp_vet | 1 |
| Brandon Dorlus | 9016 | 1604 | +7412 | idp_vet | 1 |
| Jack Bech | 9849 | 2453 | +7396 | idp_vet | 1 |
| Devin Neal | 9849 | 2497 | +7352 | idp_vet | 1 |

---

## Universe-Aware Comparison

Compares like-with-like by filtering to specific universes.

| Universe | Players | Avg Delta | Top-N Overlap | Tier Agreement |
|----------|---------|-----------|---------------|----------------|
| **Offense Players Only** | 285 | 1140 | 37/50 (74%) | 55.8% |
| **Players Only** | 859 | 2188 | 5/50 (10%) | 38.5% |
| **Offense Combined** | 285 | 1140 | 37/50 (74%) | 55.8% |
| **Offense Vet** | 246 | 852 | 44/50 (88%) | 64.6% |
| **Offense Rookie** | 39 | 2953 | 39/39 (100%) | 0.0% |
| **Idp Combined** | 574 | 2708 | 3/50 (6%) | 30.0% |
| **Idp Vet** | 551 | 2607 | 2/50 (4%) | 31.2% |
| **Idp Rookie** | 23 | 5128 | 23/23 (100%) | 0.0% |

_**Offense Players Only** is the most decision-useful view — it measures how well the canonical system ranks actual tradeable players, excluding picks. IDP metrics are secondary._

---

## What This Means

The canonical pipeline currently runs **2 sources** (DLF + FantasyCalc) compared to the legacy scraper's **11+ sources**. 
Divergence is expected and does not indicate a problem. The canonical pipeline is designed to converge with legacy as more sources are added.

**Why values differ:**
- DLF is rank-based (expert curated); many legacy sources are market/crowd-based
- Only offense_vet has 2-source blending; IDP and rookies are DLF-only
- Legacy applies Z-score normalization; canonical uses percentile power curve
- Source weights are all 1.0 (untuned) in canonical

_Report covers 859 matched players across 4 universes._