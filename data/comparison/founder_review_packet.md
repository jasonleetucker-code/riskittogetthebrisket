# Founder Review Packet: Canonical vs Legacy Disagreements

_Generated: 2026-03-22 14:10 UTC_
_Post-fix truth checkpoint: all three collision-safe consumers verified consistent_
_Legacy: legacy_data_2026-03-22.json (2-source: FantasyCalc + DLF)_
_Canonical: canonical_snapshot_20260322T140908Z.json (14 sources, scarcity=0.30)_

---

## Executive Summary

After all collision fixes, the canonical pipeline matches **82% of the top-50** offense
players (passing the 80% public-primary threshold). All three data consumers now agree on
collision resolution (higher value wins, 1165 unique assets from 1239 raw).

**Public-primary status: 8/12 pass, 3 hard fails**
- Offense tier: 53.5% (need 65%) — gap of 11.5%
- Offense delta: 999 (need ≤800) — gap of 199
- Founder approval: pending

**Root cause**: Legacy has 2 sources; canonical has 14. A full production scraper
run is the highest-leverage next action. Do not tune canonical calibration downward.

## Corrected Metrics

| View | Top-50 | Top-100 | Tier | Avg Delta |
|------|--------|---------|------|-----------|
| Offense only | **82%** | **84%** | 53.5% | 999 |
| All universes | 72% | 73% | 64.8% | 764 |
| IDP combined | 68% | 87% | **74.0%** | 584 |

## QB Top-15

| # | QB | Can | Leg | Delta | Tier Match? |
|---|----|-----|-----|-------|-------------|
| 1 | Drake Maye | 8175 | 8467 | -292 | YES |
| 2 | Josh Allen | 8283 | 8278 | +5 | YES |
| 3 | Lamar Jackson | 8148 | 7824 | +324 | YES |
| 4 | Jayden Daniels | 8068 | 7733 | +335 | YES |
| 5 | Caleb Williams | 7936 | 7408 | +528 | YES |
| 6 | Joe Burrow | 8015 | 7373 | +642 | YES |
| 7 | Patrick Mahomes | 7830 | 6834 | +996 | NO (elite vs star) |
| 8 | Justin Herbert | 7883 | 6752 | +1131 | NO (elite vs star) |
| 9 | Jalen Hurts | 7778 | 6711 | +1067 | NO (elite vs star) |
| 10 | Jaxson Dart | 7545 | 6580 | +965 | NO (elite vs star) |
| 11 | Fernando Mendoza | 7261 | 6532 | +729 | NO (elite vs star) |
| 12 | Bo Nix | 7264 | 6267 | +997 | NO (elite vs star) |
| 13 | Trevor Lawrence | 7416 | 6144 | +1272 | NO (elite vs star) |
| 14 | Brock Purdy | 7113 | 5947 | +1166 | NO (elite vs star) |
| 15 | Jordan Love | 7038 | 5751 | +1287 | NO (elite vs star) |

**Top-20 QB tier mismatches: 9/20**

## TE Top-15

| # | TE | Can | Leg | Delta | Tier Match? |
|---|----|-----|-----|-------|-------------|
| 1 | Brock Bowers | 7989 | 7650 | +339 | YES |
| 2 | Trey McBride | 8473 | 7564 | +909 | YES |
| 3 | Kenyon Sadiq | 7745 | 6954 | +791 | NO (elite vs star) |
| 4 | Colston Loveland | 8202 | 6167 | +2035 | NO (elite vs star) |
| 5 | Eli Stowers | 6010 | 6163 | -153 | YES |
| 6 | Tyler Warren | 8042 | 5956 | +2086 | NO (elite vs star) |
| 7 | Tucker Kraft | 7570 | 5411 | +2159 | NO (elite vs star) |
| 8 | Max Klare | 4310 | 5340 | -1030 | NO (starter vs star) |
| 9 | Sam LaPorta | 7088 | 5255 | +1833 | NO (elite vs star) |
| 10 | Michael Trigg | 2671 | 5193 | -2522 | NO (bench vs star) |
| 11 | Kyle Pitts | 6767 | 4835 | +1932 | NO (star vs starter) |
| 12 | Harold Fannin | 6964 | 4673 | +2291 | NO (star vs starter) |
| 13 | George Kittle | 6056 | 4428 | +1628 | NO (star vs starter) |
| 14 | Oronde Gadsden | 6288 | 4346 | +1942 | NO (star vs starter) |
| 15 | Dalton Kincaid | 6148 | 4303 | +1845 | NO (star vs starter) |

**Top-15 TE tier mismatches: 12/15**

## Severe Tier Mismatches (2+ tiers): 7

| Player | Pos | Can | Leg | Gap |
|--------|-----|-----|-----|-----|
| Brenton Strange | TE | 5493 (star) | 1700 (bench) | 2 |
| Josh Cuevas | TE | 569 (depth) | 3246 (starter) | 2 |
| Michael Trigg | TE | 2671 (bench) | 5193 (star) | 2 |
| Jordan Hudson | WR | 861 (depth) | 3113 (starter) | 2 |
| Cade Klubnik | QB | 1032 (depth) | 3128 (starter) | 2 |
| Aaron Anderson | WR | 1112 (depth) | 3094 (starter) | 2 |
| Cole Payton | QB | 1395 (depth) | 3356 (starter) | 2 |

## Per-Position Summary

| Position | Players | Avg Delta | Tier Match % |
|----------|---------|-----------|-------------|
| QB | 73 | 891 | 51% |
| RB | 120 | 957 | 55% |
| WR | 167 | 1009 | 53% |
| TE | 72 | 1021 | 49% |

---
_408 tests pass. Internal-primary: 9/9 PASS. Public-primary: 8/12._