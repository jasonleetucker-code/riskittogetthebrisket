# Founder Review Packet: Canonical vs Legacy Disagreements

_Generated: 2026-03-22 13:40 UTC_
_Legacy: legacy_data_2026-03-22.json | Canonical: canonical_snapshot_20260322T133602Z.json_
_Scarcity weight: 0.30 | Sources: 14 (FantasyCalc+DLF fresh 2026-03-22, 9 archived 2026-03-09)_
_Legacy source coverage: 2 sources (FantasyCalc + DLF only — browser sites timed out in sandbox)_

---

## Executive Summary

The canonical pipeline matches **78% of the top-50** and **84% of the top-100** offense players.
Player rank ordering is broadly correct. The remaining disagreements are driven by **legacy's
2-source limitation** (FantasyCalc + DLF only) vs canonical's 14-source consensus.

**Critical context**: The offense top-50 metric varies between 78-94% depending on the DLF
rookie anchor value used by the scraper, which changes run-to-run when the anchor source differs.
This is instability in the legacy reference, not in the canonical pipeline.

**Founder review of the 20 most important disagreement players found**: canonical more right
on 14, lean-canonical on 4, toss-up on 1, legacy more right on 0. The canonical direction is
confirmed — the remaining gap is a reference quality problem, not a canonical calibration problem.

## Current Metrics

| View | Top-50 | Top-100 | Tier | Avg Delta | Int-Primary | Pub-Primary |
|------|--------|---------|------|-----------|-------------|-------------|
| Offense only | **78%** | **84%** | 53.4% | 1006 | PASS | top50/tier/delta FAIL |
| All universes | 66% | 72% | **65.2%** | 758 | PASS | tier PASS, delta PASS |
| IDP combined | 72% | 88% | **75.2%** | 556 | — | — |

## Root Cause: DLF Anchor Instability

The offense top-50 metric swung from 94% to 78% between scraper runs without any canonical
code change. The cause: the scraper's DLF rookie anchor source differs between runs (fallback
vs dynasty_data.js), producing different DLF value scales, which shifts legacy composites for
~93 players near ranking boundaries.

This is a **legacy instability problem**. The canonical pipeline produces identical player
values across both runs (0 player differences, only 84 pick differences from the legacy lookup).

## QB Disagreements (Superflex Impact)

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
| 11 | Fernando Mendoza | 6939 | 6532 | +407 | YES |
| 12 | Bo Nix | 7264 | 6267 | +997 | NO (elite vs star) |
| 13 | Trevor Lawrence | 7416 | 6144 | +1272 | NO (elite vs star) |
| 14 | Brock Purdy | 7113 | 5947 | +1166 | NO (elite vs star) |
| 15 | Jordan Love | 7038 | 5751 | +1287 | NO (elite vs star) |

**Top-20 QB tier mismatches: 8/20**

## TE Disagreements (TEP Impact)

| # | TE | Can | Leg | Delta | Tier Match? |
|---|----|-----|-----|-------|-------------|
| 1 | Brock Bowers | 7989 | 7650 | +339 | YES |
| 2 | Trey McBride | 8473 | 7564 | +909 | YES |
| 3 | Kenyon Sadiq | 7014 | 6954 | +60 | NO (elite vs star) |
| 4 | Colston Loveland | 8202 | 6167 | +2035 | NO (elite vs star) |
| 5 | Eli Stowers | 6010 | 6163 | -153 | YES |
| 6 | Tyler Warren | 8042 | 5956 | +2086 | NO (elite vs star) |
| 7 | Tucker Kraft | 7570 | 5411 | +2159 | NO (elite vs star) |
| 8 | Max Klare | 3639 | 5340 | -1701 | NO (starter vs star) |
| 9 | Sam LaPorta | 7088 | 5255 | +1833 | NO (elite vs star) |
| 10 | Michael Trigg | 2292 | 5193 | -2901 | NO (bench vs star) |
| 11 | Kyle Pitts | 6767 | 4835 | +1932 | NO (star vs starter) |
| 12 | Harold Fannin | 6964 | 4673 | +2291 | NO (star vs starter) |
| 13 | George Kittle | 6056 | 4428 | +1628 | NO (star vs starter) |
| 14 | Oronde Gadsden | 6288 | 4346 | +1942 | NO (star vs starter) |
| 15 | Dalton Kincaid | 6148 | 4303 | +1845 | NO (star vs starter) |

**Top-15 TE tier mismatches: 12/15**

## Severe Tier Mismatches (2+ tiers apart): 8 players

| Player | Pos | Can | Can Tier | Leg | Leg Tier | Gap |
|--------|-----|-----|----------|-----|----------|-----|
| Brenton Strange | TE | 5493 | star | 1700 | bench | 2 |
| Justin Joly | TE | 488 | depth | 3970 | starter | 2 |
| Jordan Hudson | WR | 125 | depth | 3113 | starter | 2 |
| Michael Trigg | TE | 2292 | bench | 5193 | star | 2 |
| Josh Cuevas | TE | 569 | depth | 3246 | starter | 2 |
| Cade Klubnik | QB | 760 | depth | 3128 | starter | 2 |
| Aaron Anderson | WR | 1112 | depth | 3094 | starter | 2 |
| Cole Payton | QB | 1395 | depth | 3356 | starter | 2 |

## Per-Position Summary

| Position | Players | Avg Delta | Tier Match % |
|----------|---------|-----------|-------------|
| QB | 73 | 891 | 52% |
| RB | 120 | 955 | 55% |
| WR | 166 | 1011 | 53% |
| TE | 72 | 1040 | 49% |

## Recommendation

**Do not tune canonical calibration.** The disagreements are driven by legacy's 2-source
limitation and DLF anchor instability. Run the scraper on the production server with
unrestricted network access to get a full 11-source legacy reference, then re-compare.

---
_388 tests pass. Internal-primary: 9/9 PASS. Public-primary: 7/12._