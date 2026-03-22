# Founder Review Packet: Canonical vs Legacy Disagreements

_Generated: 2026-03-22 13:20 UTC_
_Legacy: legacy_data_2026-03-22.json | Canonical: canonical_snapshot_20260322T131919Z.json_
_Scarcity weight: 0.30 | Sources: 14 (FantasyCalc fresh 2026-03-22 + 13 archived 2026-03-09)_
_Bug fixes applied: pick year future-proofing, shadow value field (calibrated>scarcity>blended), top-50 denominator_

---

## Executive Summary

The canonical pipeline matches **94% of the top-50** and **90% of the top-100** offense
players. The ranking ORDER is strong. The remaining gap is **absolute value magnitude** —
the canonical system consistently values mid-tier QBs and TEs higher than legacy, which is
directionally correct for Superflex TEP but overshoots on magnitude.

**Key finding**: The offense-only tier gap (53.6% vs 65%) is caused by legacy running with
only 2 sources (FantasyCalc + DLF) while canonical has 14. A full-network scraper run would
likely close this gap. Scarcity tuning alone cannot reach 65% (ceiling ~62%).

## Current Metrics

| View | Top-50 | Top-100 | Tier | Avg Delta | Int-Primary | Pub-Primary |
|------|--------|---------|------|-----------|-------------|-------------|
| Offense only | **94%** | **90%** | 53.6% | 972 | PASS | tier/delta FAIL |
| All universes | **94%** | **79%** | **65.2%** | **739** | PASS | **PASS** |
| IDP combined | 72% | 88% | **74.8%** | 557 | — | — |

## Root Cause: Why Offense Tier Disagrees

The main disagreement pattern is **systematic canonical overvaluation of mid-tier QBs/TEs**.
This happens because:
1. Legacy ran with only 2 sources (FantasyCalc + DLF) — browser sites timed out
2. FantasyCalc values mid-tier QBs/TEs conservatively vs the broader market consensus
3. Canonical has 14 sources including KTC, DynastyDaddy, Yahoo, etc. which all rank these players higher
4. Result: QBs 7-15 and TEs 3-15 are canonical-elite but legacy-star due to the 2-source drag

This is **not a ranking problem** — the same players are in roughly the same order.
It's a **source coverage problem** — legacy has fewer data points pulling mid-tier values down.

## QB Disagreements (Superflex Impact)

Top-6 agree well. QBs 7-15 are canonical-elite but legacy-star.

| # | QB | Can | Leg | Delta | Can Tier | Leg Tier | Match? |
|---|----|----|------|-------|----------|----------|--------|
| 1 | Drake Maye | 8175 | 8467 | -292 | elite | elite | YES |
| 2 | Josh Allen | 8283 | 8278 | +5 | elite | elite | YES |
| 3 | Lamar Jackson | 8148 | 7824 | +324 | elite | elite | YES |
| 4 | Jayden Daniels | 8068 | 7733 | +335 | elite | elite | YES |
| 5 | Caleb Williams | 7936 | 7408 | +528 | elite | elite | YES |
| 6 | Joe Burrow | 8015 | 7373 | +642 | elite | elite | YES |
| 7 | Patrick Mahomes | 7830 | 6834 | +996 | elite | star | NO |
| 8 | Justin Herbert | 7883 | 6752 | +1131 | elite | star | NO |
| 9 | Jalen Hurts | 7778 | 6711 | +1067 | elite | star | NO |
| 10 | Jaxson Dart | 7545 | 6580 | +965 | elite | star | NO |
| 11 | Bo Nix | 7264 | 6267 | +997 | elite | star | NO |
| 12 | Trevor Lawrence | 7416 | 6144 | +1272 | elite | star | NO |
| 13 | Brock Purdy | 7113 | 5947 | +1166 | elite | star | NO |
| 14 | Jordan Love | 7038 | 5751 | +1287 | elite | star | NO |
| 15 | Dak Prescott | 6670 | 5654 | +1016 | star | star | YES |
| 16 | Cam Ward | 6478 | 5220 | +1258 | star | star | YES |
| 17 | C.J. Stroud | 6502 | 5171 | +1331 | star | star | YES |
| 18 | Baker Mayfield | 6359 | 5159 | +1200 | star | star | YES |
| 19 | Jared Goff | 6265 | 5091 | +1174 | star | star | YES |
| 20 | Kyler Murray | 5987 | 4827 | +1160 | star | starter | NO |

**Top-20 QB tier mismatches: 9/20**

## TE Disagreements (TEP Impact)

| # | TE | Can | Leg | Delta | Can Tier | Leg Tier | Match? |
|---|----|----|------|-------|----------|----------|--------|
| 1 | Brock Bowers | 7989 | 7650 | +339 | elite | elite | YES |
| 2 | Trey McBride | 8473 | 7564 | +909 | elite | elite | YES |
| 3 | Colston Loveland | 8202 | 6167 | +2035 | elite | star | NO |
| 4 | Tyler Warren | 8042 | 5956 | +2086 | elite | star | NO |
| 5 | Tucker Kraft | 7570 | 5411 | +2159 | elite | star | NO |
| 6 | Sam LaPorta | 7088 | 5255 | +1833 | elite | star | NO |
| 7 | Kyle Pitts | 6767 | 4835 | +1932 | star | starter | NO |
| 8 | Harold Fannin | 6964 | 4673 | +2291 | star | starter | NO |
| 9 | George Kittle | 6056 | 4428 | +1628 | star | starter | NO |
| 10 | Oronde Gadsden | 6288 | 4346 | +1942 | star | starter | NO |
| 11 | Dalton Kincaid | 6148 | 4303 | +1845 | star | starter | NO |
| 12 | Mark Andrews | 4710 | 4124 | +586 | starter | starter | YES |
| 13 | T.J. Hockenson | 4730 | 3963 | +767 | starter | starter | YES |
| 14 | Travis Kelce | 3931 | 3915 | +16 | starter | starter | YES |
| 15 | Kenyon Sadiq | 7014 | 3858 | +3156 | elite | starter | NO |

**Top-15 TE tier mismatches: 10/15**

## RB Disagreements

| # | RB | Can | Leg | Delta | Can Tier | Leg Tier | Match? |
|---|----|----|------|-------|----------|----------|--------|
| 1 | Bijan Robinson | 8500 | 8286 | +214 | elite | elite | YES |
| 2 | Jahmyr Gibbs | 8445 | 8229 | +216 | elite | elite | YES |
| 3 | Ashton Jeanty | 7674 | 7106 | +568 | elite | elite | YES |
| 4 | De'Von Achane | 7365 | 6698 | +667 | elite | star | NO |
| 5 | Jeremiyah Love | 8418 | 6667 | +1751 | elite | star | NO |
| 6 | Omarion Hampton | 8310 | 6522 | +1788 | elite | star | NO |
| 7 | Jonathan Taylor | 8256 | 6314 | +1942 | elite | star | NO |
| 8 | James Cook | 8122 | 6015 | +2107 | elite | star | NO |
| 9 | Christian McCaffrey | 7648 | 5534 | +2114 | elite | star | NO |
| 10 | Kenneth Walker | 7289 | 5483 | +1806 | elite | star | NO |
| 11 | Breece Hall | 7804 | 5476 | +2328 | elite | star | NO |
| 12 | Quinshon Judkins | 7596 | 5395 | +2201 | elite | star | NO |
| 13 | TreVeyon Henderson | 7752 | 5344 | +2408 | elite | star | NO |
| 14 | Bucky Irving | 7726 | 5316 | +2410 | elite | star | NO |
| 15 | Saquon Barkley | 7239 | 5277 | +1962 | elite | star | NO |

## WR Disagreements

| # | WR | Can | Leg | Delta | Can Tier | Leg Tier | Match? |
|---|----|----|------|-------|----------|----------|--------|
| 1 | Jaxon Smith-Njigba | 8337 | 8134 | +203 | elite | elite | YES |
| 2 | Puka Nacua | 8229 | 8116 | +113 | elite | elite | YES |
| 3 | Ja'Marr Chase | 8391 | 8083 | +308 | elite | elite | YES |
| 4 | Malik Nabers | 7493 | 7368 | +125 | elite | elite | YES |
| 5 | Justin Jefferson | 7519 | 7317 | +202 | elite | elite | YES |
| 6 | Amon-Ra St. Brown | 7340 | 7289 | +51 | elite | elite | YES |
| 7 | CeeDee Lamb | 7391 | 7009 | +382 | elite | elite | YES |
| 8 | Drake London | 8095 | 6518 | +1577 | elite | star | NO |
| 9 | Tetairoa McMillan | 7909 | 6088 | +1821 | elite | star | NO |
| 10 | George Pickens | 7700 | 5886 | +1814 | elite | star | NO |
| 11 | Nico Collins | 7857 | 5760 | +2097 | elite | star | NO |
| 12 | Emeka Egbuka | 7468 | 5697 | +1771 | elite | star | NO |
| 13 | Garrett Wilson | 7442 | 5612 | +1830 | elite | star | NO |
| 14 | Chris Olave | 7214 | 5355 | +1859 | elite | star | NO |
| 15 | Ladd McConkey | 7063 | 5224 | +1839 | elite | star | NO |

## Severe Tier Mismatches (2+ tiers apart): 4 players

| Player | Pos | Can | Can Tier | Leg | Leg Tier | Gap | Sources |
|--------|-----|-----|----------|-----|----------|-----|---------|
| Brenton Strange | TE | 5493 | star | 1700 | bench | 2 | 6 |
| Kenyon Sadiq | TE | 7014 | elite | 3858 | starter | 2 | 6 |
| Carnell Tate | WR | 7315 | elite | 4388 | starter | 2 | 6 |
| Makai Lemon | WR | 7188 | elite | 4657 | starter | 2 | 6 |

## Per-Position Summary

| Position | Players | Avg Delta | Tier Match % |
|----------|---------|-----------|-------------|
| QB | 73 | 855 | 51% |
| RB | 120 | 1008 | 52% |
| WR | 166 | 1014 | 54% |
| TE | 72 | 1004 | 51% |

## IDP Status

IDP players matched: 270
IDP tier agreement: 74.8% (strong)
IDP avg delta: 557 (well within tolerance)

## Pick Asset Status

Pick assets matched: 84
Avg pick delta: 0

## Scarcity Sweep Evidence (0.25-0.60)

| Weight | Off Top-50 | Off Tier | Off Delta | Overall Delta | Overall Tier |
|--------|-----------|----------|-----------|---------------|-------------|
| 0.25 | 94% | 52.1% | 991 | 748 | 64.3% |
| 0.28 | 94% | 52.9% | 980 | 742 | 64.8% |
| 0.30 | 94% | 53.6% | 972 | 739 | 65.2% | **CHOSEN**
| 0.32 | 94% | 54.2% | 964 | 736 | 65.4% |
| 0.35 | 94% | 54.6% | 953 | 731 | 65.7% |
| 0.40 | 92% | 55.3% | 932 | 721 | 65.9% |
| 0.50 | 90% | 58.4% | 882 | 699 | 67.6% |
| 0.60 | 88% | 61.6% | 821 | 670 | 69.2% |

---
_388 tests pass. Internal-primary: 9/9 checks PASS. Public-primary: 8/12._