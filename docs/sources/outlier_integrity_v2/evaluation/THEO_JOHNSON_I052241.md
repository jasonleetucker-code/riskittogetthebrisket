# Theo Johnson on the newest I_INDEPENDENT board (incumbent-only rebuild)

Archive `dynasty_export_20261020_052241` (I_INDEPENDENT), payload sha256 `8e9b826a3a148bbb17636aec79b46eefe3e9138940976959c4342dc4774b198a`, inputs pinned to its add commit `d9c3a70209`. Boards built: A (production), B′ (D4 on, incumbent), Anf / B′nf (no per-row filter). **No V2 build was run on this held-out board** (preregistration §16).

#### Theo Johnson (TE, NYG, offense)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 2184 | 292 | medium | high/high/high/medium/medium | 13 | - |
| B' | 2023 | 324 | low | high/high/high/medium/low | 12 | draftSharks |
| Anf | 2184 | 292 | medium | high/high/high/medium/medium | 13 | - |
| B'nf | 2106 | 309 | medium | high/high/high/medium/medium | 13 | - |

| source | family | method | raw→eff rank | applied weight | A | B' | Anf | B'nf |
|---|---|---|---|---|---|---|---|---|
| dlfSf | dlf | direct | 243→243 | 1.0 | 2271 ✓ | 2271 ✓ | 2271 ✓ | 2271 ✓ |
| dlfValuesSfTep | dlf | direct | 271→271 | 0.5 | — | 1603 ✓ | — | 1603 ✓ |
| draftSharks | draftSharks | ds_combined_cross_market | 145→194 | 1.0 | 3182 ✓ | 3182 **DROPPED** | 3182 ✓ | 3182 ✓ |
| dynastyDaddySf | dynastyDaddySf | direct | 288→288 | 1.0 | 1993 ✓ | 1993 ✓ | 1993 ✓ | 1993 ✓ |
| dynastyNerdsSfTep | dynastyNerdsSfTep | direct | 250→250 | 1.0 | 1730 ✓ | 1730 ✓ | 1730 ✓ | 1730 ✓ |
| fantasyCalc | fantasyCalc | direct | 315→315 | 1.0 | 1860 ✓ | 1860 ✓ | 1860 ✓ | 1860 ✓ |
| fantasyNavigatorSf | ktcCrowd | direct | 236→236 | 0.0 | 2323 stale(w=0) | 2323 stale(w=0) | 2323 stale(w=0) | 2323 stale(w=0) |
| fantasyProsSf | fantasyPros | direct | 246→246 | 1.0 | 2250 ✓ | 2250 ✓ | 2250 ✓ | 2250 ✓ |
| flockFantasySf | flockFantasy | direct | 241→241 | 1.0 | 2286 ✓ | 2286 ✓ | 2286 ✓ | 2286 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 377→378 | 0.0 | 2714 stale(w=0) | 2714 stale(w=0) | 2714 stale(w=0) | 2714 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 343→343 | 0.7972 | 2458 ✓ | 2458 ✓ | 2458 ✓ | 2458 ✓ |
| ktcCrowdSfTep | ktcCrowd | direct | 238→238 | 1.0 | 2416 ✓ | 2416 ✓ | 2416 ✓ | 2416 ✓ |
| ktcTradesSfTep | ktcTrades | direct | 188→188 | 1.0 | 2728 ✓ | 2728 ✓ | 2728 ✓ | 2728 ✓ |
| otcffbSf | otcffbSf | direct | 293→293 | 1.0 | 1967 ✓ | 1967 ✓ | 1967 ✓ | 1967 ✓ |
| pfkDynasty | pfkDynasty | direct | 360→360 | 1.0 | 1677 ✓ | 1677 ✓ | 1677 ✓ | 1677 ✓ |
| yahooBoone | yahooBoone | direct | 261→261 | 1.0 | 1661 ✓ | 1661 ✓ | 1661 ✓ | 1661 ✓ |

Pre-filter panel on B′ (votes reaching the filter): dlfSf 2271, dlfValuesSfTep 1603, draftSharks 3182, dynastyDaddySf 1993, dynastyNerdsSfTep 1730, fantasyCalc 1860, fantasyProsSf 2250, flockFantasySf 2286, idpTradeCalc 2458, ktcCrowdSfTep 2416, ktcTradesSfTep 2728, otcffbSf 1967, pfkDynasty 1677, yahooBoone 1661

