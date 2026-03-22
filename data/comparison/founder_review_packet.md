# Founder Review Packet: Canonical vs Legacy Disagreements

_Generated: 2026-03-22 13:55 UTC_
_Corrected checkpoint: collision fix applied, config-driven thresholds active_
_Legacy: legacy_data_2026-03-22.json (2-source: FantasyCalc + DLF)_
_Canonical: canonical_snapshot_20260322T135454Z.json (14 sources, scarcity=0.30)_

---

## Executive Summary

After the collision fix, the canonical pipeline now matches **82% of the top-50** offense
players (passing the 80% public-primary threshold). Player rank ordering is broadly correct.

**What still fails public-primary**:
- Offense tier agreement: 53.5% (need 65%) — gap of 11.5%
- Offense avg delta: 999 (need ≤800) — gap of 199
- Founder approval: not yet given

**Root cause unchanged**: Legacy has 2 sources; canonical has 14. The disagreement
is driven by the incomplete legacy reference, not canonical miscalibration.
Founder review of the 20 most important players found canonical more right on 14/20.

## Corrected Metrics (post-collision-fix)

| View | Top-50 | Top-100 | Tier | Avg Delta |
|------|--------|---------|------|-----------|
| Offense only | **82%** | **84%** | 53.5% | 999 |
| All universes | 72% | 73% | **64.8%** | 764 |
| IDP combined | 68% | 87% | **74.0%** | 584 |

## What Changed from Collision Fix

| Metric | Before Fix | After Fix | Change |
|--------|-----------|-----------|--------|
| Offense top-50 | 78% | **82%** | **+4% (now passes 80%)** |
| Offense top-100 | 84% | 84% | unchanged |
| Offense tier | 53.4% | 53.5% | +0.1% |
| Offense delta | 1006 | 999 | -7 |
| Matched count | 477 | 477 | same |

## QB Top 15

| # | QB | Can | Leg | Delta | Tier Match? |
|---|---|-----|-----|-------|-------------|
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

**Top-15 tier mismatches: 9/15**

## TE Top 15

| # | TE | Can | Leg | Delta | Tier Match? |
|---|---|-----|-----|-------|-------------|
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

**Top-15 tier mismatches: 12/15**

## RB Top 10

| # | RB | Can | Leg | Delta | Tier Match? |
|---|---|-----|-----|-------|-------------|
| 1 | Bijan Robinson | 8500 | 8286 | +214 | YES |
| 2 | Jahmyr Gibbs | 8445 | 8229 | +216 | YES |
| 3 | Ashton Jeanty | 7674 | 7106 | +568 | YES |
| 4 | De'Von Achane | 7365 | 6698 | +667 | NO (elite vs star) |
| 5 | Jeremiyah Love | 8500 | 6667 | +1833 | NO (elite vs star) |
| 6 | Omarion Hampton | 8310 | 6522 | +1788 | NO (elite vs star) |
| 7 | Jonathan Taylor | 8256 | 6314 | +1942 | NO (elite vs star) |
| 8 | James Cook | 8122 | 6015 | +2107 | NO (elite vs star) |
| 9 | Jadarian Price | 6793 | 5854 | +939 | YES |
| 10 | Jonah Coleman | 5964 | 5657 | +307 | YES |

**Top-10 tier mismatches: 5/10**

## WR Top 10

| # | WR | Can | Leg | Delta | Tier Match? |
|---|---|-----|-----|-------|-------------|
| 1 | Jaxon Smith-Njigba | 8337 | 8134 | +203 | YES |
| 2 | Puka Nacua | 8229 | 8116 | +113 | YES |
| 3 | Ja'Marr Chase | 8391 | 8083 | +308 | YES |
| 4 | Malik Nabers | 7493 | 7368 | +125 | YES |
| 5 | Justin Jefferson | 7519 | 7317 | +202 | YES |
| 6 | Amon-Ra St. Brown | 7340 | 7289 | +51 | YES |
| 7 | CeeDee Lamb | 7391 | 7009 | +382 | YES |
| 8 | Drake London | 8095 | 6518 | +1577 | NO (elite vs star) |
| 9 | Carnell Tate | 8244 | 6503 | +1741 | NO (elite vs star) |
| 10 | Jordyn Tyson | 7993 | 6489 | +1504 | NO (elite vs star) |

**Top-10 tier mismatches: 3/10**

## Severe Tier Mismatches (2+ tiers apart): 7

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
_399 tests pass. Internal-primary: 9/9 PASS. Public-primary: 8/12 (3 hard fails)._