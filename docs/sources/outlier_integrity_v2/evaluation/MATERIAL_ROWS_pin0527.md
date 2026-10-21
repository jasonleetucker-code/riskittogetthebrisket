# Material rows, pin0527

Every row with |value change| ≥ 5 % or |rank change| ≥ 25 (or gaining / losing a value or a rank), per comparison, with the source-level attribution: every vote whose status changed (with its value), and the largest vote VALUE changes (> 0.5 %) on votes that kept voting. For comparisons against A, `logSteps` decomposes the move into (1) standing the incumbent filter down, (2) the DLF flag change with no filter, (3) the filter under test; the three log-steps sum to the total log change.

## B vs A: 40 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| Trevin Wallace | idp/LB | 1916.0→884.0 | -53.9% | 350→None | low->low | dlfIdp 1517: not_observed → voting; draftSharksIdp 2886: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.002, Bnf->B -0.772 |
| Myles Garrett | idp/DL | 3597.0→5246.0 | +45.8% | 131→61 | low->medium | dlfIdp 3721: not_observed → voting; draftSharksIdp 1905: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.024, Bnf->B +0.401 |
| CJ Allen | idp/LB | 3918.0→2172.0 | -44.6% | 109→287 | low->medium | dlfIdp 2645: not_observed → voting; dlfRookieIdp 2568: not_observed → voting; draftSharksIdp 5741: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.012, Bnf->B -0.602 |
| T.J. Watt | idp/DL | 2418.0→3436.0 | +42.1% | 248→138 | low->medium | dlfIdp 3283: not_observed → voting; draftSharksIdp 1450: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.009, Bnf->B +0.342 |
| Josiah Trotter | idp/LB | 2390.0→3379.0 | +41.4% | 253→144 | low->low | dlfIdp 3171: not_observed → voting; dlfRookieIdp 3283: not_observed → voting; draftSharksIdp 1677: voting → DROPPED (incumbent); fantasyProsIdp 1868: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.051, Bnf->B +0.296 |
| Will Anderson | idp/DL | 4395.0→5980.0 | +36.1% | 84→38 | low->medium | dlfIdp 6227: not_observed → voting; draftSharksIdp 2878: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.012, Bnf->B +0.296 |
| Aidan Hutchinson | idp/DL | 4802.0→6422.0 | +33.7% | 70→34 | low->medium | dlfIdp 6227: not_observed → voting; draftSharksIdp 3181: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.000, Bnf->B +0.291 |
| Danielle Hunter | idp/DL | 2352.0→3035.0 | +29.0% | 261→173 | low->medium | dlfIdp 2702: not_observed → voting; draftSharksIdp 1643: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.010, Bnf->B +0.265 |
| Barrett Carter | idp/LB | 2864.0→2047.0 | -28.5% | 184→314 | low->medium | dlfIdp 1982: not_observed → voting; draftSharksIdp 3721: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.003, Bnf->B -0.339 |
| Trey Hendrickson | idp/DL | 2104.0→1514.0 | -28.0% | 310→522 | low->low | dlfIdp 1878: not_observed → voting; idpTradeCalc 2927: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.001, Bnf->B -0.328 |
| Nick Herbig | idp/DL | 2137.0→1554.0 | -27.3% | 303→500 | low->low | dlfIdp 2007: not_observed → voting; idpTradeCalc 2999: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.009, Bnf->B -0.327 |
| DeMarvion Overshown | idp/LB | 2752.0→2041.0 | -25.8% | 197→315 | low->low | dlfIdp 1884: not_observed → voting; draftSharksIdp 3371: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.020, Bnf->B -0.279 |
| Patrick Queen | idp/LB | 2597.0→1975.0 | -23.9% | 221→329 | low->medium | dlfIdp 2010: not_observed → voting; draftSharksIdp 3241: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.003, Bnf->B -0.277 |
| Quay Walker | idp/LB | 3874.0→3100.0 | -20.0% | 111→171 | low->medium | dlfIdp 2933: not_observed → voting; draftSharksIdp 4592: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.010, Bnf->B -0.213 |
| Chase Young | idp/DL | 2547.0→2118.0 | -16.8% | 226→296 | low->medium | dlfIdp 1916: not_observed → voting; idpTradeCalc 3200: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.000, Bnf->B -0.184 |
| Edgerrin Cooper | idp/LB | 3957.0→3293.0 | -16.8% | 107→149 | low->medium | dlfIdp 3337: not_observed → voting; draftSharksIdp 4618: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.001, Bnf->B -0.183 |
| Jihaad Campbell | idp/LB | 4168.0→3547.0 | -14.9% | 96→130 | low->medium | dlfIdp 3095: not_observed → voting; draftSharksIdp 4932: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.009, Bnf->B -0.170 |
| Nick Bolton | idp/LB | 4167.0→3588.0 | -13.9% | 97→127 | medium->medium | dlfIdp 3394: not_observed → voting; draftSharksIdp 4783: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.001, Bnf->B -0.150 |
| Dillon Thieneman | idp/DB | 3666.0→3204.0 | -12.6% | 124→159 | low->low | dlfIdp 2574: not_observed → voting; dlfRookieIdp 2982: not_observed → voting; draftSharksIdp 4331: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.018, Bnf->B -0.153 |
| Nick Emmanwori | idp/DB | 3973.0→3544.0 | -10.8% | 105→131 | medium->low | dlfIdp 3007: not_observed → voting; draftSharksIdp 4445: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.003, Bnf->B -0.112 |
| Carson Schwesinger | idp/LB | 6246.0→5584.0 | -10.6% | 34→46 | medium->medium | dlfIdp 5165: not_observed → voting; draftSharksIdp 7032: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.005, Bnf->B -0.117 |
| Jacob Rodriguez | idp/LB | 4617.0→4954.0 | +7.3% | 79→70 | low->medium | dlfIdp 4726: not_observed → voting; dlfRookieIdp 5165: not_observed → voting; fantasyProsIdp 1578: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.064, Bnf->B +0.006 |
| Alex Singleton | idp/LB | 1953.0→1821.0 | -6.8% | 336→383 | medium->medium | dlfIdp 1964: not_observed → voting; fantasyProsIdp 3283: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.059, Bnf->B -0.011 |
| Robert Spillane | idp/LB | 2182.0→2049.0 | -6.1% | 289→312 | medium->medium | dlfIdp 1962: not_observed → voting; fantasyProsIdp 3294: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.054, Bnf->B -0.009 |
| Josh Sweat | idp/DL | 1664.0→1569.0 | -5.7% | 463→494 | low->low | dlfIdp 1513: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.059, Bnf->B +0.000 |
| Dexter Lawrence | idp/DL | 1795.0→1896.0 | +5.6% | 395→358 | medium->low | dlfIdp 2621: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.055, Bnf->B +0.000 |
| Quincy Williams | idp/LB | 2179.0→2060.0 | -5.5% | 292→309 | medium->medium | dlfIdp 1982: not_observed → voting; fantasyProsIdp 3171: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.048, Bnf->B -0.009 |
| 2027 Pick 2.01 | pick/PICK | 3918.0→3705.0 | -5.4% | None→None | low->low | - | - | A->Anf +0.000, Anf->Bnf +0.012, Bnf->B -0.068; pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| Roquan Smith | idp/LB | 3337.0→3158.0 | -5.4% | 150→162 | low->medium | dlfIdp 3371: not_observed → voting; fantasyProsIdp 5165: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.047, Bnf->B -0.008 |
| 2027 Pick 2.06 | pick/PICK | 3397.0→3216.0 | -5.3% | None→None | low->low | - | - | A->Anf -0.011, Anf->Bnf +0.000, Bnf->B -0.044; pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| Abdul Carter | idp/DL | 3679.0→3870.0 | +5.2% | 122→108 | low->low | dlfIdp 4811: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.051, Bnf->B +0.000 |
| Quinnen Williams | idp/DL | 1849.0→1938.0 | +4.8% | 376→339 | medium->low | dlfIdp 2557: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.047, Bnf->B +0.000 |
| Kam Curl | idp/DB | 1921.0→1833.0 | -4.6% | 345→380 | medium->low | dlfIdp 1513: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.047, Bnf->B +0.000 |
| Braden Fiske | idp/DL | 1272.0→1323.0 | +4.0% | 679→646 | low->low | dlfIdp 1789: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.039, Bnf->B +0.000 |
| Jessie Bates | idp/DB | 1716.0→1648.0 | -4.0% | 436→467 | low->low | dlfIdp 1778: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.040, Bnf->B +0.000 |
| Leo Chenal | idp/LB | 1332.0→1288.0 | -3.3% | 641→671 | low->low | dlfIdp 1516: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.034, Bnf->B +0.000 |
| Peter Woods | idp/DL | 1403.0→1443.0 | +2.9% | 604→573 | low->low | dlfRookieIdp 1806: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.028, Bnf->B +0.000 |
| Jaquan Brisker | idp/DB | 1412.0→1379.0 | -2.3% | 591→621 | medium->medium | dlfIdp 1578: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.024, Bnf->B +0.000 |
| Boye Mafe | idp/DL | 1758.0→1795.0 | +2.1% | 419→394 | medium->medium | dlfIdp 1808: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.021, Bnf->B +0.000 |
| Gardner Minshew | offense/QB | 1180.0→1180.0 | +0.0% | None→740 | low->low | - | - | A->Anf +0.000, Anf->Bnf +0.000, Bnf->B +0.000; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |

## C vs A: 19 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| LaJohntay Wester | offense/WR | 651.0→883.0 | +35.6% | None→None | low->low | flockFantasySf 1889: DROPPED (incumbent) → voting | - | A->Anf +0.304, Anf->Bnf +0.000, Bnf->C +0.001 |
| Jacob Rodriguez | idp/LB | 4617.0→4924.0 | +6.7% | 79→68 | low->medium | dlfIdp 4726: not_observed → voting; dlfRookieIdp 5165: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.064, Bnf->C +0.000 |
| Jared Verse | idp/DL | 2672.0→2835.0 | +6.1% | 212→189 | medium->low | dlfIdp 4671: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.059, Bnf->C +0.000 |
| Alex Singleton | idp/LB | 1953.0→1841.0 | -5.7% | 336→382 | medium->medium | dlfIdp 1964: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.059, Bnf->C +0.000 |
| Josh Sweat | idp/DL | 1664.0→1569.0 | -5.7% | 463→498 | low->low | dlfIdp 1513: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.059, Bnf->C +0.000 |
| Dexter Lawrence | idp/DL | 1795.0→1896.0 | +5.6% | 395→361 | medium->low | dlfIdp 2621: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.055, Bnf->C +0.000 |
| Robert Spillane | idp/LB | 2182.0→2068.0 | -5.2% | 289→313 | medium->medium | dlfIdp 1962: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.054, Bnf->C +0.000 |
| Abdul Carter | idp/DL | 3679.0→3870.0 | +5.2% | 122→113 | low->low | dlfIdp 4811: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.051, Bnf->C +0.000 |
| Josiah Trotter | idp/LB | 2390.0→2514.0 | +5.2% | 253→234 | low->low | dlfIdp 3171: not_observed → voting; dlfRookieIdp 3283: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.051, Bnf->C +0.000 |
| KaVontae Turpin | offense/WR | 1164.0→1223.0 | +5.1% | None→714 | medium->low | pfkDynasty 2362: DROPPED (incumbent) → voting | - | A->Anf +0.049, Anf->Bnf +0.000, Bnf->C +0.000 |
| Quinnen Williams | idp/DL | 1849.0→1938.0 | +4.8% | 376→342 | medium->low | dlfIdp 2557: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.047, Bnf->C +0.000 |
| Kam Curl | idp/DB | 1921.0→1833.0 | -4.6% | 345→385 | medium->low | dlfIdp 1513: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.047, Bnf->C +0.000 |
| Braden Fiske | idp/DL | 1272.0→1323.0 | +4.0% | 679→648 | low->low | dlfIdp 1789: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.039, Bnf->C +0.000 |
| Jessie Bates | idp/DB | 1716.0→1648.0 | -4.0% | 436→470 | low->low | dlfIdp 1778: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.040, Bnf->C +0.000 |
| Nate Boerkircher | offense/TE | 1671.0→1736.0 | +3.9% | 457→430 | low->low | draftSharks 2850: DROPPED (incumbent) → voting | - | A->Anf +0.038, Anf->Bnf +0.000, Bnf->C +0.000 |
| Leo Chenal | idp/LB | 1332.0→1288.0 | -3.3% | 641→674 | low->low | dlfIdp 1516: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.034, Bnf->C +0.000 |
| Peter Woods | idp/DL | 1403.0→1443.0 | +2.9% | 604→574 | low->low | dlfRookieIdp 1806: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.028, Bnf->C +0.000 |
| Jaquan Brisker | idp/DB | 1412.0→1379.0 | -2.3% | 591→622 | medium->medium | dlfIdp 1578: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.024, Bnf->C +0.000 |
| Eric Rivers | offense/WR | 1183.0→1183.0 | +0.0% | 740→None | low->low | - | - | A->Anf +0.000, Anf->Bnf +0.000, Bnf->C +0.000; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |

## C vs B: 31 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| Trevin Wallace | idp/LB | 884.0→1913.0 | +116.4% | None→352 | low->low | draftSharksIdp 2886: DROPPED (incumbent) → voting | - |  |
| CJ Allen | idp/LB | 2172.0→3964.0 | +82.5% | 287→107 | medium->low | draftSharksIdp 5741: DROPPED (incumbent) → voting | - |  |
| Barrett Carter | idp/LB | 2047.0→2873.0 | +40.4% | 314→185 | medium->low | draftSharksIdp 3721: DROPPED (incumbent) → voting | - |  |
| Trey Hendrickson | idp/DL | 1514.0→2101.0 | +38.8% | 522→306 | low->low | idpTradeCalc 2927: DROPPED (incumbent) → voting | - |  |
| Nick Herbig | idp/DL | 1554.0→2156.0 | +38.7% | 500→294 | low->low | idpTradeCalc 2999: DROPPED (incumbent) → voting | - |  |
| LaJohntay Wester | offense/WR | 651.0→883.0 | +35.6% | None→None | low->low | flockFantasySf 1889: DROPPED (incumbent) → voting | - |  |
| Myles Garrett | idp/DL | 5246.0→3512.0 | -33.1% | 61→135 | medium->low | draftSharksIdp 1905: DROPPED (incumbent) → voting | - |  |
| DeMarvion Overshown | idp/LB | 2041.0→2697.0 | +32.1% | 315→211 | low->low | draftSharksIdp 3371: DROPPED (incumbent) → voting | - |  |
| Patrick Queen | idp/LB | 1975.0→2604.0 | +31.9% | 329→219 | medium->low | draftSharksIdp 3241: DROPPED (incumbent) → voting | - |  |
| T.J. Watt | idp/DL | 3436.0→2440.0 | -29.0% | 138→248 | medium->low | draftSharksIdp 1450: DROPPED (incumbent) → voting | - |  |
| Josiah Trotter | idp/LB | 3379.0→2514.0 | -25.6% | 144→234 | low->low | draftSharksIdp 1677: DROPPED (incumbent) → voting; fantasyProsIdp 1868: DROPPED (incumbent) → voting | - |  |
| Will Anderson | idp/DL | 5980.0→4449.0 | -25.6% | 38→83 | medium->low | draftSharksIdp 2878: DROPPED (incumbent) → voting | - |  |
| Aidan Hutchinson | idp/DL | 6422.0→4802.0 | -25.2% | 34→71 | medium->low | draftSharksIdp 3181: DROPPED (incumbent) → voting | - |  |
| Quay Walker | idp/LB | 3100.0→3835.0 | +23.7% | 171→114 | medium->low | draftSharksIdp 4592: DROPPED (incumbent) → voting | - |  |
| Danielle Hunter | idp/DL | 3035.0→2328.0 | -23.3% | 173→266 | medium->low | draftSharksIdp 1643: DROPPED (incumbent) → voting | - |  |
| Chase Young | idp/DL | 2118.0→2546.0 | +20.2% | 296→227 | medium->low | idpTradeCalc 3200: DROPPED (incumbent) → voting | - |  |
| Edgerrin Cooper | idp/LB | 3293.0→3953.0 | +20.0% | 149→109 | medium->low | draftSharksIdp 4618: DROPPED (incumbent) → voting | - |  |
| Jihaad Campbell | idp/LB | 3547.0→4206.0 | +18.6% | 130→91 | medium->low | draftSharksIdp 4932: DROPPED (incumbent) → voting | - |  |
| Dillon Thieneman | idp/DB | 3204.0→3734.0 | +16.5% | 159→117 | low->low | draftSharksIdp 4331: DROPPED (incumbent) → voting | - |  |
| Nick Bolton | idp/LB | 3588.0→4170.0 | +16.2% | 127→97 | medium->low | draftSharksIdp 4783: DROPPED (incumbent) → voting | - |  |
| Carson Schwesinger | idp/LB | 5584.0→6276.0 | +12.4% | 46→34 | medium->low | draftSharksIdp 7032: DROPPED (incumbent) → voting | - |  |
| Nick Emmanwori | idp/DB | 3544.0→3962.0 | +11.8% | 131→108 | low->low | draftSharksIdp 4445: DROPPED (incumbent) → voting | - |  |
| 2027 Pick 2.03 | pick/PICK | 3403.0→3690.0 | +8.4% | None→None | low->low | - | - | pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| 2027 Pick 2.04 | pick/PICK | 3397.0→3650.0 | +7.4% | None→None | low->low | - | - | pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| 2027 Pick 2.01 | pick/PICK | 3705.0→3964.0 | +7.0% | None→None | low->low | - | - | pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| Jared Verse | idp/DL | 2672.0→2835.0 | +6.1% | 214→189 | medium->low | dlfIdp 4671: DROPPED (incumbent) → voting | - |  |
| KaVontae Turpin | offense/WR | 1164.0→1223.0 | +5.1% | None→714 | medium->low | pfkDynasty 2362: DROPPED (incumbent) → voting | - |  |
| 2027 Pick 4.02 | pick/PICK | 2181.0→2291.0 | +5.0% | None→None | low->low | - | - | pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| Nate Boerkircher | offense/TE | 1671.0→1736.0 | +3.9% | 455→430 | low->low | draftSharks 2850: DROPPED (incumbent) → voting | - |  |
| Eric Rivers | offense/WR | 1183.0→1183.0 | +0.0% | 739→None | low->low | - | - | no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| Gardner Minshew | offense/QB | 1180.0→1180.0 | +0.0% | 740→None | low->low | - | - | no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |

## D vs A: 6 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| LaJohntay Wester | offense/WR | 651.0→883.0 | +35.6% | None→None | low->low | flockFantasySf 1889: DROPPED (incumbent) → voting | - | A->Anf +0.304, Anf->D +0.001 |
| KaVontae Turpin | offense/WR | 1164.0→1223.0 | +5.1% | None→714 | medium->low | pfkDynasty 2362: DROPPED (incumbent) → voting | - | A->Anf +0.049, Anf->D +0.000 |
| Nate Boerkircher | offense/TE | 1671.0→1736.0 | +3.9% | 457→429 | low->low | draftSharks 2850: DROPPED (incumbent) → voting | - | A->Anf +0.038, Anf->D +0.000 |
| Zavion Thomas | offense/WR | 1406.0→1440.0 | +2.4% | 600→574 | low->low | draftSharks 2507: DROPPED (incumbent) → voting | - | A->Anf +0.024, Anf->D +0.000 |
| Rashod Bateman | offense/WR | 1764.0→1803.0 | +2.2% | 417→391 | medium->medium | draftSharks 2769: DROPPED (incumbent) → voting | fantasyProsFitzmaurice 2080→2091 | A->Anf +0.022, Anf->D +0.000 |
| Eric Rivers | offense/WR | 1183.0→1183.0 | +0.0% | 740→None | low->low | - | - | A->Anf +0.000, Anf->D +0.000; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |

## B' vs A: 3 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| Theo Johnson | offense/TE | 2164.0→2053.0 | -5.1% | 295→315 | low->low | dlfValuesSfTep 1597: not_observed → voting | - | A->Anf +0.000, Anf->B'nf -0.053, B'nf->B' +0.000 |
| Xavier Hutchinson | offense/WR | 1389.0→1433.0 | +3.2% | 610→577 | low->low | dlfValuesSfTep 1550: not_observed → voting | - | A->Anf +0.000, Anf->B'nf +0.031, B'nf->B' +0.000 |
| Jalen Tolbert | offense/WR | 1404.0→1363.0 | -2.9% | 601→627 | medium->medium | dlfValuesSfTep 1281: not_observed → voting | - | A->Anf +0.000, Anf->B'nf -0.030, B'nf->B' +0.000 |

## C' vs A: 11 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| LaJohntay Wester | offense/WR | 651.0→883.0 | +35.6% | None→None | low->low | flockFantasySf 1889: DROPPED (incumbent) → voting | - | A->Anf +0.304, Anf->B'nf +0.000, B'nf->C' +0.001 |
| Theo Johnson | offense/TE | 2164.0→2054.0 | -5.1% | 295→315 | low->low | dlfValuesSfTep 1597: not_observed → voting | - | A->Anf +0.000, Anf->B'nf -0.053, B'nf->C' +0.001 |
| KaVontae Turpin | offense/WR | 1164.0→1223.0 | +5.1% | None→713 | medium->low | pfkDynasty 2362: DROPPED (incumbent) → voting | - | A->Anf +0.049, Anf->B'nf +0.000, B'nf->C' +0.000 |
| Nate Boerkircher | offense/TE | 1671.0→1736.0 | +3.9% | 457→427 | low->low | draftSharks 2850: DROPPED (incumbent) → voting | - | A->Anf +0.038, Anf->B'nf +0.000, B'nf->C' +0.000 |
| Malik Benson | offense/WR | 1271.0→1319.0 | +3.8% | 680→652 | low->low | dlfValuesSfTep 1285: not_observed → voting; draftSharks 2304: DROPPED (incumbent) → voting | fantasyProsFitzmaurice 1544→1555 | A->Anf +0.031, Anf->B'nf +0.005, B'nf->C' +0.001 |
| Xavier Hutchinson | offense/WR | 1389.0→1434.0 | +3.2% | 610→578 | low->low | dlfValuesSfTep 1550: not_observed → voting | - | A->Anf +0.000, Anf->B'nf +0.031, B'nf->C' +0.001 |
| Jalen Tolbert | offense/WR | 1404.0→1363.0 | -2.9% | 601→628 | medium->medium | dlfValuesSfTep 1281: not_observed → voting | - | A->Anf +0.000, Anf->B'nf -0.030, B'nf->C' +0.000 |
| Zavion Thomas | offense/WR | 1406.0→1447.0 | +2.9% | 600→566 | low->low | dlfValuesSfTep 1417: not_observed → voting; draftSharks 2507: DROPPED (incumbent) → voting | - | A->Anf +0.024, Anf->B'nf +0.005, B'nf->C' +0.000 |
| Rashod Bateman | offense/WR | 1764.0→1807.0 | +2.4% | 417→391 | medium->medium | dlfValuesSfTep 1749: not_observed → voting; draftSharks 2769: DROPPED (incumbent) → voting | fantasyProsFitzmaurice 2080→2091 | A->Anf +0.022, Anf->B'nf +0.002, B'nf->C' +0.000 |
| Tez Johnson | offense/WR | 1474.0→1438.0 | -2.4% | 549→574 | low->low | dlfValuesSfTep 1305: not_observed → voting | - | A->Anf +0.000, Anf->B'nf -0.025, B'nf->C' +0.000 |
| Eric Rivers | offense/WR | 1183.0→1183.0 | +0.0% | 740→None | low->low | - | - | A->Anf +0.000, Anf->B'nf +0.000, B'nf->C' +0.000; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |

## C' vs B': 6 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| LaJohntay Wester | offense/WR | 651.0→883.0 | +35.6% | None→None | low->low | flockFantasySf 1889: DROPPED (incumbent) → voting | - |  |
| KaVontae Turpin | offense/WR | 1164.0→1223.0 | +5.1% | None→713 | medium->low | pfkDynasty 2362: DROPPED (incumbent) → voting | - |  |
| Nate Boerkircher | offense/TE | 1671.0→1736.0 | +3.9% | 457→427 | low->low | draftSharks 2850: DROPPED (incumbent) → voting | - |  |
| Colby Parkinson | offense/TE | 1873.0→1936.0 | +3.4% | 366→340 | medium->low | draftSharks 3149: DROPPED (incumbent) → voting | fantasyProsFitzmaurice 1812→1826 |  |
| Zavion Thomas | offense/WR | 1413.0→1447.0 | +2.4% | 592→566 | low->low | draftSharks 2507: DROPPED (incumbent) → voting | - |  |
| Eric Rivers | offense/WR | 1183.0→1183.0 | +0.0% | 740→None | low->low | - | - | no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |

## B'' vs A: 45 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| Trevin Wallace | idp/LB | 1916.0→884.0 | -53.9% | 350→None | low->low | dlfIdp 1517: not_observed → voting; draftSharksIdp 2886: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.002, B''nf->B'' -0.772 |
| Myles Garrett | idp/DL | 3597.0→5246.0 | +45.8% | 131→62 | low->medium | dlfIdp 3721: not_observed → voting; draftSharksIdp 1905: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.024, B''nf->B'' +0.401 |
| CJ Allen | idp/LB | 3918.0→2172.0 | -44.6% | 109→283 | low->medium | dlfIdp 2645: not_observed → voting; dlfRookieIdp 2568: not_observed → voting; draftSharksIdp 5741: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.012, B''nf->B'' -0.602 |
| T.J. Watt | idp/DL | 2418.0→3436.0 | +42.1% | 248→136 | low->medium | dlfIdp 3283: not_observed → voting; draftSharksIdp 1450: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.009, B''nf->B'' +0.342 |
| Josiah Trotter | idp/LB | 2390.0→3379.0 | +41.4% | 253→144 | low->low | dlfIdp 3171: not_observed → voting; dlfRookieIdp 3283: not_observed → voting; draftSharksIdp 1677: voting → DROPPED (incumbent); fantasyProsIdp 1868: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.051, B''nf->B'' +0.296 |
| Will Anderson | idp/DL | 4395.0→5980.0 | +36.1% | 84→38 | low->medium | dlfIdp 6227: not_observed → voting; draftSharksIdp 2878: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.012, B''nf->B'' +0.296 |
| Aidan Hutchinson | idp/DL | 4802.0→6422.0 | +33.7% | 70→34 | low->medium | dlfIdp 6227: not_observed → voting; draftSharksIdp 3181: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.000, B''nf->B'' +0.291 |
| Danielle Hunter | idp/DL | 2352.0→3035.0 | +29.0% | 261→173 | low->medium | dlfIdp 2702: not_observed → voting; draftSharksIdp 1643: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.010, B''nf->B'' +0.265 |
| Barrett Carter | idp/LB | 2864.0→2047.0 | -28.5% | 184→312 | low->medium | dlfIdp 1982: not_observed → voting; draftSharksIdp 3721: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.003, B''nf->B'' -0.339 |
| Trey Hendrickson | idp/DL | 2104.0→1514.0 | -28.0% | 310→522 | low->low | dlfIdp 1878: not_observed → voting; idpTradeCalc 2927: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.001, B''nf->B'' -0.328 |
| Nick Herbig | idp/DL | 2137.0→1554.0 | -27.3% | 303→498 | low->low | dlfIdp 2007: not_observed → voting; idpTradeCalc 2999: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.009, B''nf->B'' -0.327 |
| DeMarvion Overshown | idp/LB | 2752.0→2041.0 | -25.8% | 197→313 | low->low | dlfIdp 1884: not_observed → voting; draftSharksIdp 3371: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.020, B''nf->B'' -0.279 |
| Patrick Queen | idp/LB | 2597.0→1975.0 | -23.9% | 221→328 | low->medium | dlfIdp 2010: not_observed → voting; draftSharksIdp 3241: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.003, B''nf->B'' -0.277 |
| Quay Walker | idp/LB | 3874.0→3100.0 | -20.0% | 111→170 | low->medium | dlfIdp 2933: not_observed → voting; draftSharksIdp 4592: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.010, B''nf->B'' -0.213 |
| Chase Young | idp/DL | 2547.0→2118.0 | -16.8% | 226→296 | low->medium | dlfIdp 1916: not_observed → voting; idpTradeCalc 3200: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.000, B''nf->B'' -0.184 |
| Edgerrin Cooper | idp/LB | 3957.0→3293.0 | -16.8% | 107→149 | low->medium | dlfIdp 3337: not_observed → voting; draftSharksIdp 4618: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.001, B''nf->B'' -0.183 |
| Jihaad Campbell | idp/LB | 4168.0→3547.0 | -14.9% | 96→130 | low->medium | dlfIdp 3095: not_observed → voting; draftSharksIdp 4932: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.009, B''nf->B'' -0.170 |
| Nick Bolton | idp/LB | 4167.0→3588.0 | -13.9% | 97→127 | medium->medium | dlfIdp 3394: not_observed → voting; draftSharksIdp 4783: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.001, B''nf->B'' -0.150 |
| Dillon Thieneman | idp/DB | 3666.0→3204.0 | -12.6% | 124→158 | low->low | dlfIdp 2574: not_observed → voting; dlfRookieIdp 2982: not_observed → voting; draftSharksIdp 4331: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.018, B''nf->B'' -0.153 |
| Nick Emmanwori | idp/DB | 3973.0→3544.0 | -10.8% | 105→131 | medium->low | dlfIdp 3007: not_observed → voting; draftSharksIdp 4445: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.003, B''nf->B'' -0.112 |
| Carson Schwesinger | idp/LB | 6246.0→5584.0 | -10.6% | 34→47 | medium->medium | dlfIdp 5165: not_observed → voting; draftSharksIdp 7032: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.005, B''nf->B'' -0.117 |
| Jacob Rodriguez | idp/LB | 4617.0→4954.0 | +7.3% | 79→70 | low->medium | dlfIdp 4726: not_observed → voting; dlfRookieIdp 5165: not_observed → voting; fantasyProsIdp 1578: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.064, B''nf->B'' +0.006 |
| Alex Singleton | idp/LB | 1953.0→1821.0 | -6.8% | 336→383 | medium->medium | dlfIdp 1964: not_observed → voting; fantasyProsIdp 3283: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.059, B''nf->B'' -0.011 |
| Robert Spillane | idp/LB | 2182.0→2049.0 | -6.1% | 289→311 | medium->medium | dlfIdp 1962: not_observed → voting; fantasyProsIdp 3294: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.054, B''nf->B'' -0.009 |
| Josh Sweat | idp/DL | 1664.0→1569.0 | -5.7% | 463→493 | low->low | dlfIdp 1513: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.059, B''nf->B'' +0.000 |
| Dexter Lawrence | idp/DL | 1795.0→1896.0 | +5.6% | 395→357 | medium->low | dlfIdp 2621: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.055, B''nf->B'' +0.000 |
| Quincy Williams | idp/LB | 2179.0→2060.0 | -5.5% | 292→307 | medium->medium | dlfIdp 1982: not_observed → voting; fantasyProsIdp 3171: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.048, B''nf->B'' -0.009 |
| 2027 Pick 2.01 | pick/PICK | 3918.0→3705.0 | -5.4% | None→None | low->low | - | - | A->Anf +0.000, Anf->B''nf +0.005, B''nf->B'' -0.061; pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| 2027 Pick 2.06 | pick/PICK | 3397.0→3214.0 | -5.4% | None→None | low->low | - | - | A->Anf -0.011, Anf->B''nf +0.001, B''nf->B'' -0.046; pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| Roquan Smith | idp/LB | 3337.0→3158.0 | -5.4% | 150→162 | low->medium | dlfIdp 3371: not_observed → voting; fantasyProsIdp 5165: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.047, B''nf->B'' -0.008 |
| Abdul Carter | idp/DL | 3679.0→3870.0 | +5.2% | 122→109 | low->low | dlfIdp 4811: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.051, B''nf->B'' +0.000 |
| Theo Johnson | offense/TE | 2164.0→2053.0 | -5.1% | 295→310 | low->low | dlfValuesSfTep 1597: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.053, B''nf->B'' +0.000 |
| Quinnen Williams | idp/DL | 1849.0→1938.0 | +4.8% | 376→338 | medium->low | dlfIdp 2557: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.047, B''nf->B'' +0.000 |
| Kam Curl | idp/DB | 1921.0→1833.0 | -4.6% | 345→380 | medium->low | dlfIdp 1513: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.047, B''nf->B'' +0.000 |
| Braden Fiske | idp/DL | 1272.0→1323.0 | +4.0% | 679→646 | low->low | dlfIdp 1789: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.039, B''nf->B'' +0.000 |
| Jessie Bates | idp/DB | 1716.0→1648.0 | -4.0% | 436→466 | low->low | dlfIdp 1778: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.040, B''nf->B'' +0.000 |
| Leo Chenal | idp/LB | 1332.0→1288.0 | -3.3% | 641→671 | low->low | dlfIdp 1516: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.034, B''nf->B'' +0.000 |
| Xavier Hutchinson | offense/WR | 1389.0→1433.0 | +3.2% | 610→578 | low->low | dlfValuesSfTep 1550: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.031, B''nf->B'' +0.000 |
| Travon Walker | idp/DL | 1870.0→1924.0 | +2.9% | 367→342 | medium->medium | dlfIdp 2074: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.029, B''nf->B'' +0.000 |
| Peter Woods | idp/DL | 1403.0→1443.0 | +2.9% | 604→571 | low->low | dlfRookieIdp 1806: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.028, B''nf->B'' +0.000 |
| Kobie Turner | idp/DL | 1872.0→1925.0 | +2.8% | 366→341 | medium->medium | dlfIdp 2041: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.028, B''nf->B'' +0.000 |
| Tez Johnson | offense/WR | 1474.0→1438.0 | -2.4% | 549→574 | low->low | dlfValuesSfTep 1305: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.025, B''nf->B'' +0.000 |
| Jaquan Brisker | idp/DB | 1412.0→1379.0 | -2.3% | 591→619 | medium->medium | dlfIdp 1578: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.024, B''nf->B'' +0.000 |
| Boye Mafe | idp/DL | 1758.0→1795.0 | +2.1% | 419→394 | medium->medium | dlfIdp 1808: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.021, B''nf->B'' +0.000 |
| Gardner Minshew | offense/QB | 1180.0→1180.0 | +0.0% | None→740 | low->low | - | - | A->Anf +0.000, Anf->B''nf +0.000, B''nf->B'' +0.000; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |

## C'' vs A: 25 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| LaJohntay Wester | offense/WR | 651.0→883.0 | +35.6% | None→None | low->low | flockFantasySf 1889: DROPPED (incumbent) → voting | - | A->Anf +0.304, Anf->B''nf +0.000, B''nf->C'' +0.001 |
| Jacob Rodriguez | idp/LB | 4617.0→4924.0 | +6.7% | 79→67 | low->medium | dlfIdp 4726: not_observed → voting; dlfRookieIdp 5165: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.064, B''nf->C'' +0.000 |
| Jared Verse | idp/DL | 2672.0→2835.0 | +6.1% | 212→189 | medium->low | dlfIdp 4671: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.059, B''nf->C'' +0.000 |
| Alex Singleton | idp/LB | 1953.0→1841.0 | -5.7% | 336→381 | medium->medium | dlfIdp 1964: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.059, B''nf->C'' +0.000 |
| Josh Sweat | idp/DL | 1664.0→1569.0 | -5.7% | 463→496 | low->low | dlfIdp 1513: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.059, B''nf->C'' +0.000 |
| Dexter Lawrence | idp/DL | 1795.0→1896.0 | +5.6% | 395→362 | medium->low | dlfIdp 2621: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.055, B''nf->C'' +0.000 |
| Robert Spillane | idp/LB | 2182.0→2068.0 | -5.2% | 289→312 | medium->medium | dlfIdp 1962: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.054, B''nf->C'' +0.000 |
| Abdul Carter | idp/DL | 3679.0→3870.0 | +5.2% | 122→113 | low->low | dlfIdp 4811: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.051, B''nf->C'' +0.000 |
| Josiah Trotter | idp/LB | 2390.0→2514.0 | +5.2% | 253→233 | low->low | dlfIdp 3171: not_observed → voting; dlfRookieIdp 3283: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.051, B''nf->C'' +0.000 |
| Theo Johnson | offense/TE | 2164.0→2054.0 | -5.1% | 295→316 | low->low | dlfValuesSfTep 1597: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.053, B''nf->C'' +0.001 |
| KaVontae Turpin | offense/WR | 1164.0→1223.0 | +5.1% | None→713 | medium->low | pfkDynasty 2362: DROPPED (incumbent) → voting | - | A->Anf +0.049, Anf->B''nf +0.000, B''nf->C'' +0.000 |
| Quinnen Williams | idp/DL | 1849.0→1938.0 | +4.8% | 376→340 | medium->low | dlfIdp 2557: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.047, B''nf->C'' +0.000 |
| Kam Curl | idp/DB | 1921.0→1833.0 | -4.6% | 345→384 | medium->low | dlfIdp 1513: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.047, B''nf->C'' +0.000 |
| Braden Fiske | idp/DL | 1272.0→1323.0 | +4.0% | 679→648 | low->low | dlfIdp 1789: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.039, B''nf->C'' +0.000 |
| Jessie Bates | idp/DB | 1716.0→1648.0 | -4.0% | 436→469 | low->low | dlfIdp 1778: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.040, B''nf->C'' +0.000 |
| Nate Boerkircher | offense/TE | 1671.0→1736.0 | +3.9% | 457→428 | low->low | draftSharks 2850: DROPPED (incumbent) → voting | - | A->Anf +0.038, Anf->B''nf +0.000, B''nf->C'' +0.000 |
| Malik Benson | offense/WR | 1271.0→1319.0 | +3.8% | 680→652 | low->low | dlfValuesSfTep 1285: not_observed → voting; draftSharks 2304: DROPPED (incumbent) → voting | fantasyProsFitzmaurice 1544→1555 | A->Anf +0.031, Anf->B''nf +0.005, B''nf->C'' +0.001 |
| Leo Chenal | idp/LB | 1332.0→1288.0 | -3.3% | 641→673 | low->low | dlfIdp 1516: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.034, B''nf->C'' +0.000 |
| Xavier Hutchinson | offense/WR | 1389.0→1434.0 | +3.2% | 610→580 | low->low | dlfValuesSfTep 1550: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.031, B''nf->C'' +0.001 |
| Jalen Tolbert | offense/WR | 1404.0→1363.0 | -2.9% | 601→627 | medium->medium | dlfValuesSfTep 1281: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.030, B''nf->C'' +0.000 |
| Zavion Thomas | offense/WR | 1406.0→1447.0 | +2.9% | 600→569 | low->low | dlfValuesSfTep 1417: not_observed → voting; draftSharks 2507: DROPPED (incumbent) → voting | - | A->Anf +0.024, Anf->B''nf +0.005, B''nf->C'' +0.000 |
| Peter Woods | idp/DL | 1403.0→1443.0 | +2.9% | 604→574 | low->low | dlfRookieIdp 1806: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.028, B''nf->C'' +0.000 |
| Tez Johnson | offense/WR | 1474.0→1438.0 | -2.4% | 549→576 | low->low | dlfValuesSfTep 1305: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.025, B''nf->C'' +0.000 |
| Jaquan Brisker | idp/DB | 1412.0→1379.0 | -2.3% | 591→620 | medium->medium | dlfIdp 1578: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.024, B''nf->C'' +0.000 |
| Eric Rivers | offense/WR | 1183.0→1183.0 | +0.0% | 740→None | low->low | - | - | A->Anf +0.000, Anf->B''nf +0.000, B''nf->C'' +0.000; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |

## C'' vs B'': 30 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| Trevin Wallace | idp/LB | 884.0→1913.0 | +116.4% | None→351 | low->low | draftSharksIdp 2886: DROPPED (incumbent) → voting | - |  |
| CJ Allen | idp/LB | 2172.0→3964.0 | +82.5% | 283→106 | medium->low | draftSharksIdp 5741: DROPPED (incumbent) → voting | - |  |
| Barrett Carter | idp/LB | 2047.0→2873.0 | +40.4% | 312→185 | medium->low | draftSharksIdp 3721: DROPPED (incumbent) → voting | - |  |
| Trey Hendrickson | idp/DL | 1514.0→2101.0 | +38.8% | 522→305 | low->low | idpTradeCalc 2927: DROPPED (incumbent) → voting | - |  |
| Nick Herbig | idp/DL | 1554.0→2156.0 | +38.7% | 498→291 | low->low | idpTradeCalc 2999: DROPPED (incumbent) → voting | - |  |
| LaJohntay Wester | offense/WR | 651.0→883.0 | +35.6% | None→None | low->low | flockFantasySf 1889: DROPPED (incumbent) → voting | - |  |
| Myles Garrett | idp/DL | 5246.0→3512.0 | -33.1% | 62→135 | medium->low | draftSharksIdp 1905: DROPPED (incumbent) → voting | - |  |
| DeMarvion Overshown | idp/LB | 2041.0→2697.0 | +32.1% | 313→210 | low->low | draftSharksIdp 3371: DROPPED (incumbent) → voting | - |  |
| Patrick Queen | idp/LB | 1975.0→2604.0 | +31.9% | 328→218 | medium->low | draftSharksIdp 3241: DROPPED (incumbent) → voting | - |  |
| T.J. Watt | idp/DL | 3436.0→2440.0 | -29.0% | 136→248 | medium->low | draftSharksIdp 1450: DROPPED (incumbent) → voting | - |  |
| Josiah Trotter | idp/LB | 3379.0→2514.0 | -25.6% | 144→233 | low->low | draftSharksIdp 1677: DROPPED (incumbent) → voting; fantasyProsIdp 1868: DROPPED (incumbent) → voting | - |  |
| Will Anderson | idp/DL | 5980.0→4449.0 | -25.6% | 38→83 | medium->low | draftSharksIdp 2878: DROPPED (incumbent) → voting | - |  |
| Aidan Hutchinson | idp/DL | 6422.0→4802.0 | -25.2% | 34→72 | medium->low | draftSharksIdp 3181: DROPPED (incumbent) → voting | - |  |
| Quay Walker | idp/LB | 3100.0→3835.0 | +23.7% | 170→114 | medium->low | draftSharksIdp 4592: DROPPED (incumbent) → voting | - |  |
| Danielle Hunter | idp/DL | 3035.0→2328.0 | -23.3% | 173→266 | medium->low | draftSharksIdp 1643: DROPPED (incumbent) → voting | - |  |
| Chase Young | idp/DL | 2118.0→2546.0 | +20.2% | 296→228 | medium->low | idpTradeCalc 3200: DROPPED (incumbent) → voting | - |  |
| Edgerrin Cooper | idp/LB | 3293.0→3953.0 | +20.0% | 149→108 | medium->low | draftSharksIdp 4618: DROPPED (incumbent) → voting | - |  |
| Jihaad Campbell | idp/LB | 3547.0→4206.0 | +18.6% | 130→92 | medium->low | draftSharksIdp 4932: DROPPED (incumbent) → voting | - |  |
| Dillon Thieneman | idp/DB | 3204.0→3734.0 | +16.5% | 158→117 | low->low | draftSharksIdp 4331: DROPPED (incumbent) → voting | - |  |
| Nick Bolton | idp/LB | 3588.0→4170.0 | +16.2% | 127→96 | medium->low | draftSharksIdp 4783: DROPPED (incumbent) → voting | - |  |
| Carson Schwesinger | idp/LB | 5584.0→6276.0 | +12.4% | 47→34 | medium->low | draftSharksIdp 7032: DROPPED (incumbent) → voting | - |  |
| Nick Emmanwori | idp/DB | 3544.0→3962.0 | +11.8% | 131→107 | low->low | draftSharksIdp 4445: DROPPED (incumbent) → voting | - |  |
| 2027 Pick 2.03 | pick/PICK | 3399.0→3690.0 | +8.6% | None→None | low->low | - | - | pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| 2027 Pick 2.04 | pick/PICK | 3399.0→3650.0 | +7.4% | None→None | low->low | - | - | pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| 2027 Pick 2.01 | pick/PICK | 3705.0→3938.0 | +6.3% | None→None | low->low | - | - | pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| Jared Verse | idp/DL | 2672.0→2835.0 | +6.1% | 213→189 | medium->low | dlfIdp 4671: DROPPED (incumbent) → voting | - |  |
| KaVontae Turpin | offense/WR | 1164.0→1223.0 | +5.1% | None→713 | medium->low | pfkDynasty 2362: DROPPED (incumbent) → voting | - |  |
| Nate Boerkircher | offense/TE | 1671.0→1736.0 | +3.9% | 455→428 | low->low | draftSharks 2850: DROPPED (incumbent) → voting | - |  |
| Eric Rivers | offense/WR | 1183.0→1183.0 | +0.0% | 739→None | low->low | - | - | no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| Gardner Minshew | offense/QB | 1180.0→1180.0 | +0.0% | 740→None | low->low | - | - | no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |

## C vs D: 15 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| Jacob Rodriguez | idp/LB | 4617.0→4924.0 | +6.7% | 79→68 | low->medium | dlfIdp 4726: not_observed → voting; dlfRookieIdp 5165: not_observed → voting | - |  |
| Jared Verse | idp/DL | 2672.0→2835.0 | +6.1% | 212→189 | medium->low | dlfIdp 4671: not_observed → voting | - |  |
| Alex Singleton | idp/LB | 1953.0→1841.0 | -5.7% | 337→382 | medium->medium | dlfIdp 1964: not_observed → voting | - |  |
| Josh Sweat | idp/DL | 1664.0→1569.0 | -5.7% | 465→498 | low->low | dlfIdp 1513: not_observed → voting | - |  |
| Dexter Lawrence | idp/DL | 1795.0→1896.0 | +5.6% | 398→361 | medium->low | dlfIdp 2621: not_observed → voting | - |  |
| Robert Spillane | idp/LB | 2182.0→2068.0 | -5.2% | 290→313 | medium->medium | dlfIdp 1962: not_observed → voting | - |  |
| Abdul Carter | idp/DL | 3679.0→3870.0 | +5.2% | 122→113 | low->low | dlfIdp 4811: not_observed → voting | - |  |
| Josiah Trotter | idp/LB | 2390.0→2514.0 | +5.2% | 254→234 | low->low | dlfIdp 3171: not_observed → voting; dlfRookieIdp 3283: not_observed → voting | - |  |
| Quinnen Williams | idp/DL | 1849.0→1938.0 | +4.8% | 376→342 | medium->low | dlfIdp 2557: not_observed → voting | - |  |
| Kam Curl | idp/DB | 1921.0→1833.0 | -4.6% | 346→385 | medium->low | dlfIdp 1513: not_observed → voting | - |  |
| Braden Fiske | idp/DL | 1272.0→1323.0 | +4.0% | 681→648 | low->low | dlfIdp 1789: not_observed → voting | - |  |
| Jessie Bates | idp/DB | 1716.0→1648.0 | -4.0% | 437→470 | low->low | dlfIdp 1778: not_observed → voting | - |  |
| Leo Chenal | idp/LB | 1332.0→1288.0 | -3.3% | 641→674 | low->low | dlfIdp 1516: not_observed → voting | - |  |
| Peter Woods | idp/DL | 1403.0→1443.0 | +2.9% | 604→574 | low->low | dlfRookieIdp 1806: not_observed → voting | - |  |
| Jaquan Brisker | idp/DB | 1412.0→1379.0 | -2.3% | 594→622 | medium->medium | dlfIdp 1578: not_observed → voting | - |  |

## C' vs D: 4 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| Theo Johnson | offense/TE | 2165.0→2054.0 | -5.1% | 295→315 | low->low | dlfValuesSfTep 1597: not_observed → voting | - |  |
| Xavier Hutchinson | offense/WR | 1389.0→1434.0 | +3.2% | 610→578 | low->low | dlfValuesSfTep 1550: not_observed → voting | - |  |
| Jalen Tolbert | offense/WR | 1405.0→1363.0 | -3.0% | 602→628 | medium->medium | dlfValuesSfTep 1281: not_observed → voting | - |  |
| Tez Johnson | offense/WR | 1474.0→1438.0 | -2.4% | 548→574 | low->low | dlfValuesSfTep 1305: not_observed → voting | - |  |

## C'' vs D: 19 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| Jacob Rodriguez | idp/LB | 4617.0→4924.0 | +6.7% | 79→67 | low->medium | dlfIdp 4726: not_observed → voting; dlfRookieIdp 5165: not_observed → voting | - |  |
| Jared Verse | idp/DL | 2672.0→2835.0 | +6.1% | 212→189 | medium->low | dlfIdp 4671: not_observed → voting | - |  |
| Alex Singleton | idp/LB | 1953.0→1841.0 | -5.7% | 337→381 | medium->medium | dlfIdp 1964: not_observed → voting | - |  |
| Josh Sweat | idp/DL | 1664.0→1569.0 | -5.7% | 465→496 | low->low | dlfIdp 1513: not_observed → voting | - |  |
| Dexter Lawrence | idp/DL | 1795.0→1896.0 | +5.6% | 398→362 | medium->low | dlfIdp 2621: not_observed → voting | - |  |
| Robert Spillane | idp/LB | 2182.0→2068.0 | -5.2% | 290→312 | medium->medium | dlfIdp 1962: not_observed → voting | - |  |
| Abdul Carter | idp/DL | 3679.0→3870.0 | +5.2% | 122→113 | low->low | dlfIdp 4811: not_observed → voting | - |  |
| Josiah Trotter | idp/LB | 2390.0→2514.0 | +5.2% | 254→233 | low->low | dlfIdp 3171: not_observed → voting; dlfRookieIdp 3283: not_observed → voting | - |  |
| Theo Johnson | offense/TE | 2165.0→2054.0 | -5.1% | 295→316 | low->low | dlfValuesSfTep 1597: not_observed → voting | - |  |
| Quinnen Williams | idp/DL | 1849.0→1938.0 | +4.8% | 376→340 | medium->low | dlfIdp 2557: not_observed → voting | - |  |
| Kam Curl | idp/DB | 1921.0→1833.0 | -4.6% | 346→384 | medium->low | dlfIdp 1513: not_observed → voting | - |  |
| Braden Fiske | idp/DL | 1272.0→1323.0 | +4.0% | 681→648 | low->low | dlfIdp 1789: not_observed → voting | - |  |
| Jessie Bates | idp/DB | 1716.0→1648.0 | -4.0% | 437→469 | low->low | dlfIdp 1778: not_observed → voting | - |  |
| Leo Chenal | idp/LB | 1332.0→1288.0 | -3.3% | 641→673 | low->low | dlfIdp 1516: not_observed → voting | - |  |
| Xavier Hutchinson | offense/WR | 1389.0→1434.0 | +3.2% | 610→580 | low->low | dlfValuesSfTep 1550: not_observed → voting | - |  |
| Jalen Tolbert | offense/WR | 1405.0→1363.0 | -3.0% | 602→627 | medium->medium | dlfValuesSfTep 1281: not_observed → voting | - |  |
| Peter Woods | idp/DL | 1403.0→1443.0 | +2.9% | 604→574 | low->low | dlfRookieIdp 1806: not_observed → voting | - |  |
| Tez Johnson | offense/WR | 1474.0→1438.0 | -2.4% | 548→576 | low->low | dlfValuesSfTep 1305: not_observed → voting | - |  |
| Jaquan Brisker | idp/DB | 1412.0→1379.0 | -2.3% | 594→620 | medium->medium | dlfIdp 1578: not_observed → voting | - |  |

## C vs Bnf: 0 material rows

None.

## D vs Anf: 0 material rows

None.

## C' vs B'nf: 0 material rows

None.

## C'' vs B''nf: 0 material rows

None.

