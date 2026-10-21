# Material rows, pin2015

Every row with |value change| ≥ 5 % or |rank change| ≥ 25 (or gaining / losing a value or a rank), per comparison, with the source-level attribution: every vote whose status changed (with its value), and the largest vote VALUE changes (> 0.5 %) on votes that kept voting. For comparisons against A, `logSteps` decomposes the move into (1) standing the incumbent filter down, (2) the DLF flag change with no filter, (3) the filter under test; the three log-steps sum to the total log change.

## B vs A: 43 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| Trevin Wallace | idp/LB | 1937.0→884.0 | -54.4% | 342→None | low->low | dlfIdp 1517: not_observed → voting; draftSharksIdp 2878: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.002, Bnf->B -0.783 |
| Myles Garrett | idp/DL | 3555.0→5245.0 | +47.5% | 133→61 | low->medium | dlfIdp 3721: not_observed → voting; draftSharksIdp 1905: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.025, Bnf->B +0.413 |
| CJ Allen | idp/LB | 3987.0→2172.0 | -45.5% | 106→286 | low->medium | dlfIdp 2645: not_observed → voting; dlfRookieIdp 2568: not_observed → voting; draftSharksIdp 5790: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.011, Bnf->B -0.619 |
| T.J. Watt | idp/DL | 2394.0→3436.0 | +43.5% | 250→138 | low->medium | dlfIdp 3283: not_observed → voting; draftSharksIdp 1450: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.009, Bnf->B +0.353 |
| Josiah Trotter | idp/LB | 2368.0→3379.0 | +42.7% | 257→144 | low->low | dlfIdp 3171: not_observed → voting; dlfRookieIdp 3283: not_observed → voting; draftSharksIdp 1675: voting → DROPPED (incumbent); fantasyProsIdp 1868: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.051, Bnf->B +0.304 |
| Will Anderson | idp/DL | 4354.0→5980.0 | +37.3% | 87→36 | low->medium | dlfIdp 6227: not_observed → voting; draftSharksIdp 2870: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.012, Bnf->B +0.305 |
| Aidan Hutchinson | idp/DL | 4772.0→6422.0 | +34.6% | 72→34 | low->medium | dlfIdp 6227: not_observed → voting; draftSharksIdp 3200: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.000, Bnf->B +0.297 |
| Danielle Hunter | idp/DL | 2333.0→3035.0 | +30.1% | 264→173 | low->medium | dlfIdp 2702: not_observed → voting; draftSharksIdp 1641: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.010, Bnf->B +0.273 |
| Barrett Carter | idp/LB | 2884.0→2047.0 | -29.0% | 183→315 | low->medium | dlfIdp 1982: not_observed → voting; draftSharksIdp 3721: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.003, Bnf->B -0.346 |
| Trey Hendrickson | idp/DL | 2086.0→1513.0 | -27.5% | 312→524 | low->low | dlfIdp 1878: not_observed → voting; idpTradeCalc 2927: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.002, Bnf->B -0.319 |
| Nick Herbig | idp/DL | 2118.0→1553.0 | -26.7% | 308→504 | low->low | dlfIdp 2007: not_observed → voting; idpTradeCalc 2999: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.009, Bnf->B -0.319 |
| DeMarvion Overshown | idp/LB | 2774.0→2040.0 | -26.5% | 195→317 | low->low | dlfIdp 1884: not_observed → voting; draftSharksIdp 3383: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.020, Bnf->B -0.287 |
| Patrick Queen | idp/LB | 2623.0→1975.0 | -24.7% | 218→329 | low->medium | dlfIdp 2010: not_observed → voting; draftSharksIdp 3262: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.003, Bnf->B -0.286 |
| Quay Walker | idp/LB | 3905.0→3099.0 | -20.6% | 111→169 | low->medium | dlfIdp 2933: not_observed → voting; draftSharksIdp 4618: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.010, Bnf->B -0.221 |
| Edgerrin Cooper | idp/LB | 3987.0→3293.0 | -17.4% | 105→149 | low->medium | dlfIdp 3337: not_observed → voting; draftSharksIdp 4645: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.001, Bnf->B -0.190 |
| Chase Young | idp/DL | 2534.0→2118.0 | -16.4% | 229→296 | low->medium | dlfIdp 1916: not_observed → voting; idpTradeCalc 3200: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.000, Bnf->B -0.179 |
| Jihaad Campbell | idp/LB | 4217.0→3547.0 | -15.9% | 91→128 | low->medium | dlfIdp 3095: not_observed → voting; draftSharksIdp 4996: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.009, Bnf->B -0.182 |
| Nick Bolton | idp/LB | 4138.0→3588.0 | -13.3% | 98→126 | medium->medium | dlfIdp 3394: not_observed → voting; draftSharksIdp 4698: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.001, Bnf->B -0.143 |
| Dillon Thieneman | idp/DB | 3690.0→3205.0 | -13.1% | 120→159 | low->low | dlfIdp 2574: not_observed → voting; dlfRookieIdp 2982: not_observed → voting; draftSharksIdp 4353: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.018, Bnf->B -0.159 |
| Nick Emmanwori | idp/DB | 4020.0→3544.0 | -11.8% | 104→129 | medium->low | dlfIdp 3007: not_observed → voting; draftSharksIdp 4517: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.003, Bnf->B -0.123 |
| Carson Schwesinger | idp/LB | 6219.0→5584.0 | -10.2% | 34→47 | medium->medium | dlfIdp 5165: not_observed → voting; draftSharksIdp 6945: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.005, Bnf->B -0.113 |
| 2027 Pick 2.01 | pick/PICK | 3947.0→3653.0 | -7.4% | None→None | low->low | - | - | A->Anf +0.000, Anf->Bnf +0.000, Bnf->B -0.077; pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| Jacob Rodriguez | idp/LB | 4624.0→4961.0 | +7.3% | 77→70 | low->medium | dlfIdp 4726: not_observed → voting; dlfRookieIdp 5165: not_observed → voting; fantasyProsIdp 1578: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf +0.065, Bnf->B +0.006 |
| Alex Singleton | idp/LB | 1949.0→1817.0 | -6.8% | 337→386 | medium->medium | dlfIdp 1964: not_observed → voting; fantasyProsIdp 3283: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.060, Bnf->B -0.010 |
| Robert Spillane | idp/LB | 2187.0→2054.0 | -6.1% | 288→312 | medium->medium | dlfIdp 1962: not_observed → voting; fantasyProsIdp 3294: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.053, Bnf->B -0.009 |
| Josh Sweat | idp/DL | 1671.0→1575.0 | -5.8% | 461→497 | low->low | dlfIdp 1513: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.059, Bnf->B +0.000 |
| Dexter Lawrence | idp/DL | 1793.0→1895.0 | +5.7% | 400→360 | medium->low | dlfIdp 2621: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.055, Bnf->B +0.000 |
| Quincy Williams | idp/LB | 2184.0→2065.0 | -5.5% | 290→307 | medium->medium | dlfIdp 1982: not_observed → voting; fantasyProsIdp 3171: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.048, Bnf->B -0.008 |
| Roquan Smith | idp/LB | 3323.0→3143.0 | -5.4% | 151→165 | low->medium | dlfIdp 3371: not_observed → voting; fantasyProsIdp 5165: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->Bnf -0.048, Bnf->B -0.008 |
| 2027 Pick 1.06 | pick/PICK | 4709.0→4961.0 | +5.3% | None→None | low->low | - | - | A->Anf +0.000, Anf->Bnf +0.046, Bnf->B +0.006; pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| Abdul Carter | idp/DL | 3646.0→3838.0 | +5.3% | 125→109 | low->low | dlfIdp 4811: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.051, Bnf->B +0.000 |
| 2027 Pick 2.03 | pick/PICK | 3569.0→3389.0 | -5.0% | None→None | low->low | - | - | A->Anf +0.000, Anf->Bnf +0.023, Bnf->B -0.075; pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| Quinnen Williams | idp/DL | 1847.0→1936.0 | +4.8% | 381→340 | medium->low | dlfIdp 2557: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.047, Bnf->B +0.000 |
| Kam Curl | idp/DB | 1919.0→1831.0 | -4.6% | 348→382 | medium->low | dlfIdp 1513: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.047, Bnf->B +0.000 |
| Jessie Bates | idp/DB | 1722.0→1653.0 | -4.0% | 437→467 | low->low | dlfIdp 1778: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.041, Bnf->B +0.000 |
| Braden Fiske | idp/DL | 1281.0→1332.0 | +4.0% | 674→642 | low->low | dlfIdp 1789: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.039, Bnf->B +0.000 |
| Leo Chenal | idp/LB | 1332.0→1287.0 | -3.4% | 643→671 | low->low | dlfIdp 1516: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.034, Bnf->B +0.000 |
| Travon Walker | idp/DL | 1866.0→1921.0 | +2.9% | 372→346 | medium->medium | dlfIdp 2074: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.029, Bnf->B +0.000 |
| Kobie Turner | idp/DL | 1871.0→1925.0 | +2.9% | 371→342 | medium->medium | dlfIdp 2041: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.029, Bnf->B +0.000 |
| Calijah Kancey | idp/DL | 1453.0→1491.0 | +2.6% | 566→540 | low->medium | dlfIdp 1833: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.026, Bnf->B +0.000 |
| Zach Sieler | idp/DL | 1458.0→1493.0 | +2.4% | 563→538 | medium->low | dlfIdp 1787: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.024, Bnf->B +0.000 |
| Jaquan Brisker | idp/DB | 1413.0→1380.0 | -2.3% | 589→617 | medium->medium | dlfIdp 1578: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.024, Bnf->B +0.000 |
| Kayden McDonald | idp/DL | 1183.0→1183.0 | +0.0% | None→740 | low->low | - | - | A->Anf +0.000, Anf->Bnf +0.000, Bnf->B +0.000; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |

## C vs A: 25 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| LaJohntay Wester | offense/WR | 648.0→872.0 | +34.6% | None→None | low->low | flockFantasySf 1889: DROPPED (incumbent) → voting | - | A->Anf +0.297, Anf->Bnf +0.000, Bnf->C +0.000 |
| Jacob Rodriguez | idp/LB | 4624.0→4932.0 | +6.7% | 77→68 | low->medium | dlfIdp 4726: not_observed → voting; dlfRookieIdp 5165: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.065, Bnf->C +0.000 |
| Jared Verse | idp/DL | 2666.0→2829.0 | +6.1% | 211→189 | medium->low | dlfIdp 4671: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.059, Bnf->C +0.000 |
| Alex Singleton | idp/LB | 1949.0→1836.0 | -5.8% | 337→384 | medium->medium | dlfIdp 1964: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.060, Bnf->C +0.000 |
| KaVontae Turpin | offense/WR | 1159.0→1226.0 | +5.8% | None→707 | medium->low | pfkDynasty 2362: DROPPED (incumbent) → voting | - | A->Anf +0.056, Anf->Bnf +0.000, Bnf->C +0.000 |
| Josh Sweat | idp/DL | 1671.0→1575.0 | -5.8% | 461→500 | low->low | dlfIdp 1513: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.059, Bnf->C +0.000 |
| Dexter Lawrence | idp/DL | 1793.0→1895.0 | +5.7% | 400→364 | medium->low | dlfIdp 2621: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.055, Bnf->C +0.000 |
| Josiah Trotter | idp/LB | 2368.0→2493.0 | +5.3% | 257→239 | low->low | dlfIdp 3171: not_observed → voting; dlfRookieIdp 3283: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.051, Bnf->C +0.000 |
| Abdul Carter | idp/DL | 3646.0→3838.0 | +5.3% | 125→114 | low->low | dlfIdp 4811: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.051, Bnf->C +0.000 |
| Robert Spillane | idp/LB | 2187.0→2073.0 | -5.2% | 288→313 | medium->medium | dlfIdp 1962: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.053, Bnf->C +0.000 |
| Quinnen Williams | idp/DL | 1847.0→1936.0 | +4.8% | 381→342 | medium->low | dlfIdp 2557: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.047, Bnf->C +0.000 |
| Kam Curl | idp/DB | 1919.0→1831.0 | -4.6% | 348→387 | medium->low | dlfIdp 1513: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.047, Bnf->C +0.000 |
| Malik Benson | offense/WR | 1221.0→1274.0 | +4.3% | 712→678 | medium->low | draftSharks 2304: DROPPED (incumbent) → voting | fantasyProsFitzmaurice 1544→1555 | A->Anf +0.042, Anf->Bnf +0.000, Bnf->C +0.001 |
| Jessie Bates | idp/DB | 1722.0→1653.0 | -4.0% | 437→470 | low->low | dlfIdp 1778: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.041, Bnf->C +0.000 |
| Braden Fiske | idp/DL | 1281.0→1332.0 | +4.0% | 674→643 | low->low | dlfIdp 1789: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.039, Bnf->C +0.000 |
| Marlin Klein | offense/TE | 1779.0→1841.0 | +3.5% | 408→382 | medium->medium | draftSharks 3061: DROPPED (incumbent) → voting | - | A->Anf +0.033, Anf->Bnf +0.000, Bnf->C +0.001 |
| Leo Chenal | idp/LB | 1332.0→1287.0 | -3.4% | 643→672 | low->low | dlfIdp 1516: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.034, Bnf->C +0.000 |
| Joe Milton | offense/QB | 1435.0→1388.0 | -3.3% | 576→612 | low->low | fantasyProsFitzmaurice 1473: voting → v2_refused:identity_unresolved:team_only_mismatch | - | A->Anf +0.000, Anf->Bnf +0.000, Bnf->C -0.033 |
| Kobie Turner | idp/DL | 1871.0→1925.0 | +2.9% | 371→346 | medium->medium | dlfIdp 2041: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.029, Bnf->C +0.000 |
| Brenen Thompson | offense/WR | 1370.0→1409.0 | +2.9% | 623→593 | medium->medium | draftSharks 2496: DROPPED (incumbent) → voting | fantasyProsFitzmaurice 1544→1555 | A->Anf +0.027, Anf->Bnf +0.000, Bnf->C +0.001 |
| Zavion Thomas | offense/WR | 1391.0→1428.0 | +2.7% | 610→584 | low->low | draftSharks 2512: DROPPED (incumbent) → voting | - | A->Anf +0.026, Anf->Bnf +0.000, Bnf->C +0.000 |
| Calijah Kancey | idp/DL | 1453.0→1491.0 | +2.6% | 566→541 | low->medium | dlfIdp 1833: not_observed → voting | - | A->Anf +0.000, Anf->Bnf +0.026, Bnf->C +0.000 |
| Jaquan Brisker | idp/DB | 1413.0→1380.0 | -2.3% | 589→619 | medium->medium | dlfIdp 1578: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.024, Bnf->C +0.000 |
| Akeem Davis-Gaither | idp/LB | 1411.0→1385.0 | -1.8% | 590→616 | medium->medium | dlfIdp 1502: not_observed → voting | - | A->Anf +0.000, Anf->Bnf -0.019, Bnf->C +0.000 |
| Oluwafemi Oladejo | idp/DL | 1185.0→1185.0 | +0.0% | 740→None | low->low | - | - | A->Anf +0.000, Anf->Bnf +0.000, Bnf->C +0.000; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |

## C vs B: 32 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| Trevin Wallace | idp/LB | 884.0→1934.0 | +118.8% | None→343 | low->low | draftSharksIdp 2878: DROPPED (incumbent) → voting | - |  |
| CJ Allen | idp/LB | 2172.0→4033.0 | +85.7% | 286→104 | medium->low | draftSharksIdp 5790: DROPPED (incumbent) → voting | - |  |
| Barrett Carter | idp/LB | 2047.0→2893.0 | +41.3% | 315→183 | medium->low | draftSharksIdp 3721: DROPPED (incumbent) → voting | - |  |
| Trey Hendrickson | idp/DL | 1513.0→2082.0 | +37.6% | 524→312 | low->low | idpTradeCalc 2927: DROPPED (incumbent) → voting | - |  |
| Nick Herbig | idp/DL | 1553.0→2137.0 | +37.6% | 504→297 | low->low | idpTradeCalc 2999: DROPPED (incumbent) → voting | - |  |
| LaJohntay Wester | offense/WR | 648.0→872.0 | +34.6% | None→None | low->low | flockFantasySf 1889: DROPPED (incumbent) → voting | - |  |
| Myles Garrett | idp/DL | 5245.0→3469.0 | -33.9% | 61→137 | medium->low | draftSharksIdp 1905: DROPPED (incumbent) → voting | - |  |
| DeMarvion Overshown | idp/LB | 2040.0→2719.0 | +33.3% | 317→207 | low->low | draftSharksIdp 3383: DROPPED (incumbent) → voting | - |  |
| Patrick Queen | idp/LB | 1975.0→2630.0 | +33.2% | 329→216 | medium->low | draftSharksIdp 3262: DROPPED (incumbent) → voting | - |  |
| T.J. Watt | idp/DL | 3436.0→2415.0 | -29.7% | 138→249 | medium->low | draftSharksIdp 1450: DROPPED (incumbent) → voting | - |  |
| Will Anderson | idp/DL | 5980.0→4407.0 | -26.3% | 36→84 | medium->low | draftSharksIdp 2870: DROPPED (incumbent) → voting | - |  |
| Josiah Trotter | idp/LB | 3379.0→2493.0 | -26.2% | 144→239 | low->low | draftSharksIdp 1675: DROPPED (incumbent) → voting; fantasyProsIdp 1868: DROPPED (incumbent) → voting | - |  |
| Aidan Hutchinson | idp/DL | 6422.0→4772.0 | -25.7% | 34→73 | medium->low | draftSharksIdp 3200: DROPPED (incumbent) → voting | - |  |
| Quay Walker | idp/LB | 3099.0→3866.0 | +24.8% | 169→113 | medium->low | draftSharksIdp 4618: DROPPED (incumbent) → voting | - |  |
| Danielle Hunter | idp/DL | 3035.0→2309.0 | -23.9% | 173→267 | medium->low | draftSharksIdp 1641: DROPPED (incumbent) → voting | - |  |
| Edgerrin Cooper | idp/LB | 3293.0→3983.0 | +20.9% | 149→108 | medium->low | draftSharksIdp 4645: DROPPED (incumbent) → voting | - |  |
| Jihaad Campbell | idp/LB | 3547.0→4254.0 | +19.9% | 128→89 | medium->low | draftSharksIdp 4996: DROPPED (incumbent) → voting | - |  |
| Chase Young | idp/DL | 2118.0→2533.0 | +19.6% | 296→231 | medium->low | idpTradeCalc 3200: DROPPED (incumbent) → voting | - |  |
| Dillon Thieneman | idp/DB | 3205.0→3759.0 | +17.3% | 159→117 | low->low | draftSharksIdp 4353: DROPPED (incumbent) → voting | - |  |
| Nick Bolton | idp/LB | 3588.0→4141.0 | +15.4% | 126→97 | medium->low | draftSharksIdp 4698: DROPPED (incumbent) → voting | - |  |
| Nick Emmanwori | idp/DB | 3544.0→4009.0 | +13.1% | 129→107 | low->low | draftSharksIdp 4517: DROPPED (incumbent) → voting | - |  |
| Carson Schwesinger | idp/LB | 5584.0→6249.0 | +11.9% | 47→34 | medium->low | draftSharksIdp 6945: DROPPED (incumbent) → voting | - |  |
| 2027 Pick 2.01 | pick/PICK | 3653.0→3947.0 | +8.1% | None→None | low->low | - | - | pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| 2027 Pick 2.03 | pick/PICK | 3389.0→3653.0 | +7.8% | None→None | low->low | - | - | pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| 2027 Pick 2.04 | pick/PICK | 3379.0→3616.0 | +7.0% | None→None | low->low | - | - | pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| Jared Verse | idp/DL | 2666.0→2829.0 | +6.1% | 214→189 | medium->low | dlfIdp 4671: DROPPED (incumbent) → voting | - |  |
| KaVontae Turpin | offense/WR | 1159.0→1226.0 | +5.8% | None→707 | medium->low | pfkDynasty 2362: DROPPED (incumbent) → voting | - |  |
| Malik Benson | offense/WR | 1221.0→1274.0 | +4.3% | 711→678 | medium->low | draftSharks 2304: DROPPED (incumbent) → voting | fantasyProsFitzmaurice 1544→1555 |  |
| Joe Milton | offense/QB | 1435.0→1388.0 | -3.3% | 577→612 | low->low | fantasyProsFitzmaurice 1473: voting → v2_refused:identity_unresolved:team_only_mismatch | - |  |
| Brenen Thompson | offense/WR | 1370.0→1409.0 | +2.9% | 621→593 | medium->medium | draftSharks 2496: DROPPED (incumbent) → voting | fantasyProsFitzmaurice 1544→1555 |  |
| Kayden McDonald | idp/DL | 1183.0→1183.0 | +0.0% | 740→None | low->low | - | - | no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| Oluwafemi Oladejo | idp/DL | 1185.0→1185.0 | +0.0% | 739→None | low->low | - | - | no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |

## D vs A: 7 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| LaJohntay Wester | offense/WR | 648.0→872.0 | +34.6% | None→None | low->low | flockFantasySf 1889: DROPPED (incumbent) → voting | - | A->Anf +0.297, Anf->D +0.000 |
| KaVontae Turpin | offense/WR | 1159.0→1226.0 | +5.8% | None→707 | medium->low | pfkDynasty 2362: DROPPED (incumbent) → voting | - | A->Anf +0.056, Anf->D +0.000 |
| Malik Benson | offense/WR | 1221.0→1274.0 | +4.3% | 712→678 | medium->low | draftSharks 2304: DROPPED (incumbent) → voting | fantasyProsFitzmaurice 1544→1555 | A->Anf +0.042, Anf->D +0.001 |
| Joe Milton | offense/QB | 1435.0→1388.0 | -3.3% | 576→614 | low->low | fantasyProsFitzmaurice 1473: voting → v2_refused:identity_unresolved:team_only_mismatch | - | A->Anf +0.000, Anf->D -0.033 |
| Brenen Thompson | offense/WR | 1370.0→1409.0 | +2.9% | 623→593 | medium->medium | draftSharks 2496: DROPPED (incumbent) → voting | fantasyProsFitzmaurice 1544→1555 | A->Anf +0.027, Anf->D +0.001 |
| Zavion Thomas | offense/WR | 1391.0→1428.0 | +2.7% | 610→583 | low->low | draftSharks 2512: DROPPED (incumbent) → voting | - | A->Anf +0.026, Anf->D +0.000 |
| Oluwafemi Oladejo | idp/DL | 1185.0→1185.0 | +0.0% | 740→None | low->low | - | - | A->Anf +0.000, Anf->D +0.000; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |

## B' vs A: 3 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| Josh Cameron | offense/WR | 1608.0→1531.0 | -4.8% | 491→516 | low->medium | dlfValuesSfTep 1389: not_observed → voting; draftSharks 2633: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B'nf +0.002, B'nf->B' -0.051 |
| Jack Strand | offense/QB | 1207.0→1260.0 | +4.4% | 721→683 | low->low | dlfValuesSfTep 1357: not_observed → voting | - | A->Anf +0.000, Anf->B'nf +0.043, B'nf->B' +0.000 |
| Tez Johnson | offense/WR | 1483.0→1446.0 | -2.5% | 541→572 | low->medium | dlfValuesSfTep 1293: not_observed → voting | - | A->Anf +0.000, Anf->B'nf -0.025, B'nf->B' +0.000 |

## C' vs A: 9 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| LaJohntay Wester | offense/WR | 648.0→872.0 | +34.6% | None→None | low->low | flockFantasySf 1889: DROPPED (incumbent) → voting | - | A->Anf +0.297, Anf->B'nf +0.000, B'nf->C' +0.000 |
| Malik Benson | offense/WR | 1221.0→1298.0 | +6.3% | 712→664 | medium->low | dlfValuesSfTep 1277: not_observed → voting; draftSharks 2304: DROPPED (incumbent) → voting | fantasyProsFitzmaurice 1544→1555 | A->Anf +0.042, Anf->B'nf +0.019, B'nf->C' +0.001 |
| KaVontae Turpin | offense/WR | 1159.0→1226.0 | +5.8% | None→707 | medium->low | pfkDynasty 2362: DROPPED (incumbent) → voting | - | A->Anf +0.056, Anf->B'nf +0.000, B'nf->C' +0.000 |
| Jack Strand | offense/QB | 1207.0→1260.0 | +4.4% | 721→685 | low->low | dlfValuesSfTep 1357: not_observed → voting | - | A->Anf +0.000, Anf->B'nf +0.043, B'nf->C' +0.000 |
| Brenen Thompson | offense/WR | 1370.0→1422.0 | +3.8% | 623→586 | medium->medium | dlfValuesSfTep 1478: not_observed → voting; draftSharks 2496: DROPPED (incumbent) → voting | fantasyProsFitzmaurice 1544→1555 | A->Anf +0.027, Anf->B'nf +0.009, B'nf->C' +0.001 |
| Joe Milton | offense/QB | 1435.0→1388.0 | -3.3% | 576→611 | low->low | fantasyProsFitzmaurice 1473: voting → v2_refused:identity_unresolved:team_only_mismatch | - | A->Anf +0.000, Anf->B'nf +0.000, B'nf->C' -0.033 |
| Zavion Thomas | offense/WR | 1391.0→1436.0 | +3.2% | 610→575 | low->low | dlfValuesSfTep 1432: not_observed → voting; draftSharks 2512: DROPPED (incumbent) → voting | - | A->Anf +0.026, Anf->B'nf +0.006, B'nf->C' +0.000 |
| Tez Johnson | offense/WR | 1483.0→1446.0 | -2.5% | 541→572 | low->medium | dlfValuesSfTep 1293: not_observed → voting | - | A->Anf +0.000, Anf->B'nf -0.025, B'nf->C' +0.000 |
| Oluwafemi Oladejo | idp/DL | 1185.0→1185.0 | +0.0% | 740→None | low->low | - | - | A->Anf +0.000, Anf->B'nf +0.000, B'nf->C' +0.000; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |

## C' vs B': 9 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| LaJohntay Wester | offense/WR | 648.0→872.0 | +34.6% | None→None | low->low | flockFantasySf 1889: DROPPED (incumbent) → voting | - |  |
| KaVontae Turpin | offense/WR | 1159.0→1226.0 | +5.8% | None→707 | medium->low | pfkDynasty 2362: DROPPED (incumbent) → voting | - |  |
| Josh Cameron | offense/WR | 1531.0→1611.0 | +5.2% | 516→486 | medium->low | draftSharks 2633: DROPPED (incumbent) → voting | - |  |
| Brenen Thompson | offense/WR | 1371.0→1422.0 | +3.7% | 621→586 | medium->medium | draftSharks 2496: DROPPED (incumbent) → voting | fantasyProsFitzmaurice 1544→1555 |  |
| Malik Benson | offense/WR | 1255.0→1298.0 | +3.4% | 689→664 | low->low | draftSharks 2304: DROPPED (incumbent) → voting | fantasyProsFitzmaurice 1544→1555 |  |
| Joe Milton | offense/QB | 1435.0→1388.0 | -3.3% | 575→611 | low->low | fantasyProsFitzmaurice 1473: voting → v2_refused:identity_unresolved:team_only_mismatch | - |  |
| Marlin Klein | offense/TE | 1758.0→1814.0 | +3.2% | 417→391 | medium->medium | draftSharks 3061: DROPPED (incumbent) → voting | - |  |
| Zavion Thomas | offense/WR | 1400.0→1436.0 | +2.6% | 600→575 | low->low | draftSharks 2512: DROPPED (incumbent) → voting | - |  |
| Oluwafemi Oladejo | idp/DL | 1185.0→1185.0 | +0.0% | 740→None | low->low | - | - | no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |

## B'' vs A: 45 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| Trevin Wallace | idp/LB | 1937.0→884.0 | -54.4% | 342→None | low->low | dlfIdp 1517: not_observed → voting; draftSharksIdp 2878: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.002, B''nf->B'' -0.783 |
| Myles Garrett | idp/DL | 3555.0→5245.0 | +47.5% | 133→61 | low->medium | dlfIdp 3721: not_observed → voting; draftSharksIdp 1905: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.025, B''nf->B'' +0.413 |
| CJ Allen | idp/LB | 3987.0→2172.0 | -45.5% | 106→283 | low->medium | dlfIdp 2645: not_observed → voting; dlfRookieIdp 2568: not_observed → voting; draftSharksIdp 5790: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.011, B''nf->B'' -0.619 |
| T.J. Watt | idp/DL | 2394.0→3436.0 | +43.5% | 250→135 | low->medium | dlfIdp 3283: not_observed → voting; draftSharksIdp 1450: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.009, B''nf->B'' +0.353 |
| Josiah Trotter | idp/LB | 2368.0→3379.0 | +42.7% | 257→143 | low->low | dlfIdp 3171: not_observed → voting; dlfRookieIdp 3283: not_observed → voting; draftSharksIdp 1675: voting → DROPPED (incumbent); fantasyProsIdp 1868: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.051, B''nf->B'' +0.304 |
| Will Anderson | idp/DL | 4354.0→5980.0 | +37.3% | 87→36 | low->medium | dlfIdp 6227: not_observed → voting; draftSharksIdp 2870: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.012, B''nf->B'' +0.305 |
| Aidan Hutchinson | idp/DL | 4772.0→6422.0 | +34.6% | 72→34 | low->medium | dlfIdp 6227: not_observed → voting; draftSharksIdp 3200: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.000, B''nf->B'' +0.297 |
| Danielle Hunter | idp/DL | 2333.0→3035.0 | +30.1% | 264→173 | low->medium | dlfIdp 2702: not_observed → voting; draftSharksIdp 1641: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.010, B''nf->B'' +0.273 |
| Barrett Carter | idp/LB | 2884.0→2047.0 | -29.0% | 183→313 | low->medium | dlfIdp 1982: not_observed → voting; draftSharksIdp 3721: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.003, B''nf->B'' -0.346 |
| Trey Hendrickson | idp/DL | 2086.0→1513.0 | -27.5% | 312→522 | low->low | dlfIdp 1878: not_observed → voting; idpTradeCalc 2927: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.002, B''nf->B'' -0.319 |
| Nick Herbig | idp/DL | 2118.0→1553.0 | -26.7% | 308→502 | low->low | dlfIdp 2007: not_observed → voting; idpTradeCalc 2999: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.009, B''nf->B'' -0.319 |
| DeMarvion Overshown | idp/LB | 2774.0→2040.0 | -26.5% | 195→317 | low->low | dlfIdp 1884: not_observed → voting; draftSharksIdp 3383: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.020, B''nf->B'' -0.287 |
| Patrick Queen | idp/LB | 2623.0→1975.0 | -24.7% | 218→327 | low->medium | dlfIdp 2010: not_observed → voting; draftSharksIdp 3262: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.003, B''nf->B'' -0.286 |
| Quay Walker | idp/LB | 3905.0→3099.0 | -20.6% | 111→169 | low->medium | dlfIdp 2933: not_observed → voting; draftSharksIdp 4618: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.010, B''nf->B'' -0.221 |
| Edgerrin Cooper | idp/LB | 3987.0→3293.0 | -17.4% | 105→149 | low->medium | dlfIdp 3337: not_observed → voting; draftSharksIdp 4645: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.001, B''nf->B'' -0.190 |
| Chase Young | idp/DL | 2534.0→2118.0 | -16.4% | 229→296 | low->medium | dlfIdp 1916: not_observed → voting; idpTradeCalc 3200: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.000, B''nf->B'' -0.179 |
| Jihaad Campbell | idp/LB | 4217.0→3547.0 | -15.9% | 91→128 | low->medium | dlfIdp 3095: not_observed → voting; draftSharksIdp 4996: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.009, B''nf->B'' -0.182 |
| Nick Bolton | idp/LB | 4138.0→3588.0 | -13.3% | 98→126 | medium->medium | dlfIdp 3394: not_observed → voting; draftSharksIdp 4698: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.001, B''nf->B'' -0.143 |
| Dillon Thieneman | idp/DB | 3690.0→3205.0 | -13.1% | 120→159 | low->low | dlfIdp 2574: not_observed → voting; dlfRookieIdp 2982: not_observed → voting; draftSharksIdp 4353: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.018, B''nf->B'' -0.159 |
| Nick Emmanwori | idp/DB | 4020.0→3544.0 | -11.8% | 104→129 | medium->low | dlfIdp 3007: not_observed → voting; draftSharksIdp 4517: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.003, B''nf->B'' -0.123 |
| Carson Schwesinger | idp/LB | 6219.0→5584.0 | -10.2% | 34→47 | medium->medium | dlfIdp 5165: not_observed → voting; draftSharksIdp 6945: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.005, B''nf->B'' -0.113 |
| 2027 Pick 2.01 | pick/PICK | 3947.0→3653.0 | -7.4% | None→None | low->low | - | - | A->Anf +0.000, Anf->B''nf -0.007, B''nf->B'' -0.070; pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| Jacob Rodriguez | idp/LB | 4624.0→4961.0 | +7.3% | 77→71 | low->medium | dlfIdp 4726: not_observed → voting; dlfRookieIdp 5165: not_observed → voting; fantasyProsIdp 1578: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.065, B''nf->B'' +0.006 |
| Alex Singleton | idp/LB | 1949.0→1817.0 | -6.8% | 337→386 | medium->medium | dlfIdp 1964: not_observed → voting; fantasyProsIdp 3283: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.060, B''nf->B'' -0.010 |
| Robert Spillane | idp/LB | 2187.0→2054.0 | -6.1% | 288→310 | medium->medium | dlfIdp 1962: not_observed → voting; fantasyProsIdp 3294: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.053, B''nf->B'' -0.009 |
| Josh Sweat | idp/DL | 1671.0→1575.0 | -5.8% | 461→495 | low->low | dlfIdp 1513: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.059, B''nf->B'' +0.000 |
| Dexter Lawrence | idp/DL | 1793.0→1895.0 | +5.7% | 400→359 | medium->low | dlfIdp 2621: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.055, B''nf->B'' +0.000 |
| Quincy Williams | idp/LB | 2184.0→2065.0 | -5.5% | 290→307 | medium->medium | dlfIdp 1982: not_observed → voting; fantasyProsIdp 3171: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.048, B''nf->B'' -0.008 |
| Roquan Smith | idp/LB | 3323.0→3143.0 | -5.4% | 151→163 | low->medium | dlfIdp 3371: not_observed → voting; fantasyProsIdp 5165: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf -0.048, B''nf->B'' -0.008 |
| 2027 Pick 1.06 | pick/PICK | 4709.0→4961.0 | +5.3% | None→None | low->low | - | - | A->Anf +0.000, Anf->B''nf +0.046, B''nf->B'' +0.006; pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| Abdul Carter | idp/DL | 3646.0→3838.0 | +5.3% | 125→109 | low->low | dlfIdp 4811: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.051, B''nf->B'' +0.000 |
| Quinnen Williams | idp/DL | 1847.0→1936.0 | +4.8% | 381→340 | medium->low | dlfIdp 2557: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.047, B''nf->B'' +0.000 |
| Josh Cameron | offense/WR | 1608.0→1531.0 | -4.8% | 491→516 | low->medium | dlfValuesSfTep 1389: not_observed → voting; draftSharks 2633: voting → DROPPED (incumbent) | - | A->Anf +0.000, Anf->B''nf +0.002, B''nf->B'' -0.051 |
| Kam Curl | idp/DB | 1919.0→1831.0 | -4.6% | 348→381 | medium->low | dlfIdp 1513: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.047, B''nf->B'' +0.000 |
| Jack Strand | offense/QB | 1207.0→1260.0 | +4.4% | 721→684 | low->low | dlfValuesSfTep 1357: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.043, B''nf->B'' +0.000 |
| Jessie Bates | idp/DB | 1722.0→1653.0 | -4.0% | 437→466 | low->low | dlfIdp 1778: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.041, B''nf->B'' +0.000 |
| Braden Fiske | idp/DL | 1281.0→1332.0 | +4.0% | 674→642 | low->low | dlfIdp 1789: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.039, B''nf->B'' +0.000 |
| Leo Chenal | idp/LB | 1332.0→1287.0 | -3.4% | 643→671 | low->low | dlfIdp 1516: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.034, B''nf->B'' +0.000 |
| Travon Walker | idp/DL | 1866.0→1921.0 | +2.9% | 372→346 | medium->medium | dlfIdp 2074: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.029, B''nf->B'' +0.000 |
| Kobie Turner | idp/DL | 1871.0→1925.0 | +2.9% | 371→342 | medium->medium | dlfIdp 2041: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.029, B''nf->B'' +0.000 |
| Calijah Kancey | idp/DL | 1453.0→1491.0 | +2.6% | 566→538 | low->medium | dlfIdp 1833: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.026, B''nf->B'' +0.000 |
| Tez Johnson | offense/WR | 1483.0→1446.0 | -2.5% | 541→573 | low->medium | dlfValuesSfTep 1293: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.025, B''nf->B'' +0.000 |
| Zach Sieler | idp/DL | 1458.0→1493.0 | +2.4% | 563→536 | medium->low | dlfIdp 1787: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.024, B''nf->B'' +0.000 |
| Jaquan Brisker | idp/DB | 1413.0→1380.0 | -2.3% | 589→616 | medium->medium | dlfIdp 1578: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.024, B''nf->B'' +0.000 |
| Kayden McDonald | idp/DL | 1183.0→1183.0 | +0.0% | None→740 | low->low | - | - | A->Anf +0.000, Anf->B''nf +0.000, B''nf->B'' +0.000; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |

## C'' vs A: 26 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| LaJohntay Wester | offense/WR | 648.0→872.0 | +34.6% | None→None | low->low | flockFantasySf 1889: DROPPED (incumbent) → voting | - | A->Anf +0.297, Anf->B''nf +0.000, B''nf->C'' +0.000 |
| Jacob Rodriguez | idp/LB | 4624.0→4932.0 | +6.7% | 77→67 | low->medium | dlfIdp 4726: not_observed → voting; dlfRookieIdp 5165: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.065, B''nf->C'' +0.000 |
| Malik Benson | offense/WR | 1221.0→1298.0 | +6.3% | 712→664 | medium->low | dlfValuesSfTep 1277: not_observed → voting; draftSharks 2304: DROPPED (incumbent) → voting | fantasyProsFitzmaurice 1544→1555 | A->Anf +0.042, Anf->B''nf +0.019, B''nf->C'' +0.001 |
| Jared Verse | idp/DL | 2666.0→2829.0 | +6.1% | 211→189 | medium->low | dlfIdp 4671: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.059, B''nf->C'' +0.000 |
| Alex Singleton | idp/LB | 1949.0→1836.0 | -5.8% | 337→383 | medium->medium | dlfIdp 1964: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.060, B''nf->C'' +0.000 |
| KaVontae Turpin | offense/WR | 1159.0→1226.0 | +5.8% | None→707 | medium->low | pfkDynasty 2362: DROPPED (incumbent) → voting | - | A->Anf +0.056, Anf->B''nf +0.000, B''nf->C'' +0.000 |
| Josh Sweat | idp/DL | 1671.0→1575.0 | -5.8% | 461→499 | low->low | dlfIdp 1513: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.059, B''nf->C'' +0.000 |
| Dexter Lawrence | idp/DL | 1793.0→1895.0 | +5.7% | 400→363 | medium->low | dlfIdp 2621: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.055, B''nf->C'' +0.000 |
| Josiah Trotter | idp/LB | 2368.0→2493.0 | +5.3% | 257→239 | low->low | dlfIdp 3171: not_observed → voting; dlfRookieIdp 3283: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.051, B''nf->C'' +0.000 |
| Abdul Carter | idp/DL | 3646.0→3838.0 | +5.3% | 125→114 | low->low | dlfIdp 4811: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.051, B''nf->C'' +0.000 |
| Robert Spillane | idp/LB | 2187.0→2073.0 | -5.2% | 288→313 | medium->medium | dlfIdp 1962: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.053, B''nf->C'' +0.000 |
| Quinnen Williams | idp/DL | 1847.0→1936.0 | +4.8% | 381→342 | medium->low | dlfIdp 2557: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.047, B''nf->C'' +0.000 |
| Kam Curl | idp/DB | 1919.0→1831.0 | -4.6% | 348→385 | medium->low | dlfIdp 1513: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.047, B''nf->C'' +0.000 |
| Jack Strand | offense/QB | 1207.0→1260.0 | +4.4% | 721→687 | low->low | dlfValuesSfTep 1357: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.043, B''nf->C'' +0.000 |
| Jessie Bates | idp/DB | 1722.0→1653.0 | -4.0% | 437→469 | low->low | dlfIdp 1778: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.041, B''nf->C'' +0.000 |
| Braden Fiske | idp/DL | 1281.0→1332.0 | +4.0% | 674→643 | low->low | dlfIdp 1789: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.039, B''nf->C'' +0.000 |
| Brenen Thompson | offense/WR | 1370.0→1422.0 | +3.8% | 623→587 | medium->medium | dlfValuesSfTep 1478: not_observed → voting; draftSharks 2496: DROPPED (incumbent) → voting | fantasyProsFitzmaurice 1544→1555 | A->Anf +0.027, Anf->B''nf +0.009, B''nf->C'' +0.001 |
| Leo Chenal | idp/LB | 1332.0→1287.0 | -3.4% | 643→673 | low->low | dlfIdp 1516: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.034, B''nf->C'' +0.000 |
| Joe Milton | offense/QB | 1435.0→1388.0 | -3.3% | 576→609 | low->low | fantasyProsFitzmaurice 1473: voting → v2_refused:identity_unresolved:team_only_mismatch | - | A->Anf +0.000, Anf->B''nf +0.000, B''nf->C'' -0.033 |
| Zavion Thomas | offense/WR | 1391.0→1436.0 | +3.2% | 610→577 | low->low | dlfValuesSfTep 1432: not_observed → voting; draftSharks 2512: DROPPED (incumbent) → voting | - | A->Anf +0.026, Anf->B''nf +0.006, B''nf->C'' +0.000 |
| Kobie Turner | idp/DL | 1871.0→1925.0 | +2.9% | 371→346 | medium->medium | dlfIdp 2041: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.029, B''nf->C'' +0.000 |
| Calijah Kancey | idp/DL | 1453.0→1491.0 | +2.6% | 566→539 | low->medium | dlfIdp 1833: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.026, B''nf->C'' +0.000 |
| Tez Johnson | offense/WR | 1483.0→1446.0 | -2.5% | 541→574 | low->medium | dlfValuesSfTep 1293: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.025, B''nf->C'' +0.000 |
| Zach Sieler | idp/DL | 1458.0→1493.0 | +2.4% | 563→537 | medium->low | dlfIdp 1787: not_observed → voting | - | A->Anf +0.000, Anf->B''nf +0.024, B''nf->C'' +0.000 |
| Jaquan Brisker | idp/DB | 1413.0→1380.0 | -2.3% | 589→618 | medium->medium | dlfIdp 1578: not_observed → voting | - | A->Anf +0.000, Anf->B''nf -0.024, B''nf->C'' +0.000 |
| Oluwafemi Oladejo | idp/DL | 1185.0→1185.0 | +0.0% | 740→None | low->low | - | - | A->Anf +0.000, Anf->B''nf +0.000, B''nf->C'' +0.000; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |

## C'' vs B'': 32 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| Trevin Wallace | idp/LB | 884.0→1934.0 | +118.8% | None→343 | low->low | draftSharksIdp 2878: DROPPED (incumbent) → voting | - |  |
| CJ Allen | idp/LB | 2172.0→4033.0 | +85.7% | 283→103 | medium->low | draftSharksIdp 5790: DROPPED (incumbent) → voting | - |  |
| Barrett Carter | idp/LB | 2047.0→2893.0 | +41.3% | 313→183 | medium->low | draftSharksIdp 3721: DROPPED (incumbent) → voting | - |  |
| Trey Hendrickson | idp/DL | 1513.0→2082.0 | +37.6% | 522→311 | low->low | idpTradeCalc 2927: DROPPED (incumbent) → voting | - |  |
| Nick Herbig | idp/DL | 1553.0→2137.0 | +37.6% | 502→296 | low->low | idpTradeCalc 2999: DROPPED (incumbent) → voting | - |  |
| LaJohntay Wester | offense/WR | 648.0→872.0 | +34.6% | None→None | low->low | flockFantasySf 1889: DROPPED (incumbent) → voting | - |  |
| Myles Garrett | idp/DL | 5245.0→3469.0 | -33.9% | 61→137 | medium->low | draftSharksIdp 1905: DROPPED (incumbent) → voting | - |  |
| DeMarvion Overshown | idp/LB | 2040.0→2719.0 | +33.3% | 317→206 | low->low | draftSharksIdp 3383: DROPPED (incumbent) → voting | - |  |
| Patrick Queen | idp/LB | 1975.0→2630.0 | +33.2% | 327→216 | medium->low | draftSharksIdp 3262: DROPPED (incumbent) → voting | - |  |
| T.J. Watt | idp/DL | 3436.0→2415.0 | -29.7% | 135→249 | medium->low | draftSharksIdp 1450: DROPPED (incumbent) → voting | - |  |
| Will Anderson | idp/DL | 5980.0→4407.0 | -26.3% | 36→84 | medium->low | draftSharksIdp 2870: DROPPED (incumbent) → voting | - |  |
| Josiah Trotter | idp/LB | 3379.0→2493.0 | -26.2% | 143→239 | low->low | draftSharksIdp 1675: DROPPED (incumbent) → voting; fantasyProsIdp 1868: DROPPED (incumbent) → voting | - |  |
| Aidan Hutchinson | idp/DL | 6422.0→4772.0 | -25.7% | 34→73 | medium->low | draftSharksIdp 3200: DROPPED (incumbent) → voting | - |  |
| Quay Walker | idp/LB | 3099.0→3866.0 | +24.8% | 169→113 | medium->low | draftSharksIdp 4618: DROPPED (incumbent) → voting | - |  |
| Danielle Hunter | idp/DL | 3035.0→2309.0 | -23.9% | 173→265 | medium->low | draftSharksIdp 1641: DROPPED (incumbent) → voting | - |  |
| Edgerrin Cooper | idp/LB | 3293.0→3983.0 | +20.9% | 149→108 | medium->low | draftSharksIdp 4645: DROPPED (incumbent) → voting | - |  |
| Jihaad Campbell | idp/LB | 3547.0→4254.0 | +19.9% | 128→89 | medium->low | draftSharksIdp 4996: DROPPED (incumbent) → voting | - |  |
| Chase Young | idp/DL | 2118.0→2533.0 | +19.6% | 296→231 | medium->low | idpTradeCalc 3200: DROPPED (incumbent) → voting | - |  |
| Dillon Thieneman | idp/DB | 3205.0→3759.0 | +17.3% | 159→117 | low->low | draftSharksIdp 4353: DROPPED (incumbent) → voting | - |  |
| Nick Bolton | idp/LB | 3588.0→4141.0 | +15.4% | 126→97 | medium->low | draftSharksIdp 4698: DROPPED (incumbent) → voting | - |  |
| Nick Emmanwori | idp/DB | 3544.0→4009.0 | +13.1% | 129→106 | low->low | draftSharksIdp 4517: DROPPED (incumbent) → voting | - |  |
| Carson Schwesinger | idp/LB | 5584.0→6249.0 | +11.9% | 47→34 | medium->low | draftSharksIdp 6945: DROPPED (incumbent) → voting | - |  |
| 2027 Pick 2.03 | pick/PICK | 3391.0→3653.0 | +7.7% | None→None | low->low | - | - | pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| 2027 Pick 2.01 | pick/PICK | 3653.0→3920.0 | +7.3% | None→None | low->low | - | - | pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| 2027 Pick 2.04 | pick/PICK | 3379.0→3616.0 | +7.0% | None→None | low->low | - | - | pick provenance rookie_pool_tether -> rookie_pool_tether; no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| Jared Verse | idp/DL | 2666.0→2829.0 | +6.1% | 214→189 | medium->low | dlfIdp 4671: DROPPED (incumbent) → voting | - |  |
| KaVontae Turpin | offense/WR | 1159.0→1226.0 | +5.8% | None→707 | medium->low | pfkDynasty 2362: DROPPED (incumbent) → voting | - |  |
| Josh Cameron | offense/WR | 1531.0→1611.0 | +5.2% | 516→486 | medium->low | draftSharks 2633: DROPPED (incumbent) → voting | - |  |
| Brenen Thompson | offense/WR | 1371.0→1422.0 | +3.7% | 619→587 | medium->medium | draftSharks 2496: DROPPED (incumbent) → voting | fantasyProsFitzmaurice 1544→1555 |  |
| Joe Milton | offense/QB | 1435.0→1388.0 | -3.3% | 576→609 | low->low | fantasyProsFitzmaurice 1473: voting → v2_refused:identity_unresolved:team_only_mismatch | - |  |
| Kayden McDonald | idp/DL | 1183.0→1183.0 | +0.0% | 740→None | low->low | - | - | no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |
| Oluwafemi Oladejo | idp/DL | 1185.0→1185.0 | +0.0% | 739→None | low->low | - | - | no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering |

## C vs D: 17 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| Jacob Rodriguez | idp/LB | 4624.0→4932.0 | +6.7% | 78→68 | low->medium | dlfIdp 4726: not_observed → voting; dlfRookieIdp 5165: not_observed → voting | - |  |
| Jared Verse | idp/DL | 2666.0→2829.0 | +6.1% | 211→189 | medium->low | dlfIdp 4671: not_observed → voting | - |  |
| Alex Singleton | idp/LB | 1949.0→1836.0 | -5.8% | 337→384 | medium->medium | dlfIdp 1964: not_observed → voting | - |  |
| Josh Sweat | idp/DL | 1671.0→1575.0 | -5.8% | 461→500 | low->low | dlfIdp 1513: not_observed → voting | - |  |
| Dexter Lawrence | idp/DL | 1793.0→1895.0 | +5.7% | 402→364 | medium->low | dlfIdp 2621: not_observed → voting | - |  |
| Josiah Trotter | idp/LB | 2368.0→2493.0 | +5.3% | 257→239 | low->low | dlfIdp 3171: not_observed → voting; dlfRookieIdp 3283: not_observed → voting | - |  |
| Abdul Carter | idp/DL | 3646.0→3838.0 | +5.3% | 126→114 | low->low | dlfIdp 4811: not_observed → voting | - |  |
| Robert Spillane | idp/LB | 2187.0→2073.0 | -5.2% | 288→313 | medium->medium | dlfIdp 1962: not_observed → voting | - |  |
| Quinnen Williams | idp/DL | 1847.0→1936.0 | +4.8% | 381→342 | medium->low | dlfIdp 2557: not_observed → voting | - |  |
| Kam Curl | idp/DB | 1919.0→1831.0 | -4.6% | 349→387 | medium->low | dlfIdp 1513: not_observed → voting | - |  |
| Jessie Bates | idp/DB | 1722.0→1653.0 | -4.0% | 437→470 | low->low | dlfIdp 1778: not_observed → voting | - |  |
| Braden Fiske | idp/DL | 1281.0→1332.0 | +4.0% | 674→643 | low->low | dlfIdp 1789: not_observed → voting | - |  |
| Leo Chenal | idp/LB | 1332.0→1287.0 | -3.4% | 643→672 | low->low | dlfIdp 1516: not_observed → voting | - |  |
| Kobie Turner | idp/DL | 1871.0→1925.0 | +2.9% | 372→346 | medium->medium | dlfIdp 2041: not_observed → voting | - |  |
| Calijah Kancey | idp/DL | 1453.0→1491.0 | +2.6% | 566→541 | low->medium | dlfIdp 1833: not_observed → voting | - |  |
| Jaquan Brisker | idp/DB | 1413.0→1380.0 | -2.3% | 589→619 | medium->medium | dlfIdp 1578: not_observed → voting | - |  |
| Akeem Davis-Gaither | idp/LB | 1411.0→1385.0 | -1.8% | 590→616 | medium->medium | dlfIdp 1502: not_observed → voting | - |  |

## C' vs D: 2 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| Jack Strand | offense/QB | 1207.0→1260.0 | +4.4% | 722→685 | low->low | dlfValuesSfTep 1357: not_observed → voting | - |  |
| Tez Johnson | offense/WR | 1483.0→1446.0 | -2.5% | 541→572 | low->medium | dlfValuesSfTep 1293: not_observed → voting | - |  |

## C'' vs D: 19 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| Jacob Rodriguez | idp/LB | 4624.0→4932.0 | +6.7% | 78→67 | low->medium | dlfIdp 4726: not_observed → voting; dlfRookieIdp 5165: not_observed → voting | - |  |
| Jared Verse | idp/DL | 2666.0→2829.0 | +6.1% | 211→189 | medium->low | dlfIdp 4671: not_observed → voting | - |  |
| Alex Singleton | idp/LB | 1949.0→1836.0 | -5.8% | 337→383 | medium->medium | dlfIdp 1964: not_observed → voting | - |  |
| Josh Sweat | idp/DL | 1671.0→1575.0 | -5.8% | 461→499 | low->low | dlfIdp 1513: not_observed → voting | - |  |
| Dexter Lawrence | idp/DL | 1793.0→1895.0 | +5.7% | 402→363 | medium->low | dlfIdp 2621: not_observed → voting | - |  |
| Josiah Trotter | idp/LB | 2368.0→2493.0 | +5.3% | 257→239 | low->low | dlfIdp 3171: not_observed → voting; dlfRookieIdp 3283: not_observed → voting | - |  |
| Abdul Carter | idp/DL | 3646.0→3838.0 | +5.3% | 126→114 | low->low | dlfIdp 4811: not_observed → voting | - |  |
| Robert Spillane | idp/LB | 2187.0→2073.0 | -5.2% | 288→313 | medium->medium | dlfIdp 1962: not_observed → voting | - |  |
| Quinnen Williams | idp/DL | 1847.0→1936.0 | +4.8% | 381→342 | medium->low | dlfIdp 2557: not_observed → voting | - |  |
| Kam Curl | idp/DB | 1919.0→1831.0 | -4.6% | 349→385 | medium->low | dlfIdp 1513: not_observed → voting | - |  |
| Jack Strand | offense/QB | 1207.0→1260.0 | +4.4% | 722→687 | low->low | dlfValuesSfTep 1357: not_observed → voting | - |  |
| Jessie Bates | idp/DB | 1722.0→1653.0 | -4.0% | 437→469 | low->low | dlfIdp 1778: not_observed → voting | - |  |
| Braden Fiske | idp/DL | 1281.0→1332.0 | +4.0% | 674→643 | low->low | dlfIdp 1789: not_observed → voting | - |  |
| Leo Chenal | idp/LB | 1332.0→1287.0 | -3.4% | 643→673 | low->low | dlfIdp 1516: not_observed → voting | - |  |
| Kobie Turner | idp/DL | 1871.0→1925.0 | +2.9% | 372→346 | medium->medium | dlfIdp 2041: not_observed → voting | - |  |
| Calijah Kancey | idp/DL | 1453.0→1491.0 | +2.6% | 566→539 | low->medium | dlfIdp 1833: not_observed → voting | - |  |
| Tez Johnson | offense/WR | 1483.0→1446.0 | -2.5% | 541→574 | low->medium | dlfValuesSfTep 1293: not_observed → voting | - |  |
| Zach Sieler | idp/DL | 1458.0→1493.0 | +2.4% | 563→537 | medium->low | dlfIdp 1787: not_observed → voting | - |  |
| Jaquan Brisker | idp/DB | 1413.0→1380.0 | -2.3% | 589→618 | medium->medium | dlfIdp 1578: not_observed → voting | - |  |

## C vs Bnf: 1 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| Joe Milton | offense/QB | 1435.0→1388.0 | -3.3% | 578→612 | low->low | fantasyProsFitzmaurice 1473: voting → v2_refused:identity_unresolved:team_only_mismatch | - |  |

## D vs Anf: 1 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| Joe Milton | offense/QB | 1435.0→1388.0 | -3.3% | 576→614 | low->low | fantasyProsFitzmaurice 1473: voting → v2_refused:identity_unresolved:team_only_mismatch | - |  |

## C' vs B'nf: 1 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| Joe Milton | offense/QB | 1435.0→1388.0 | -3.3% | 576→611 | low->low | fantasyProsFitzmaurice 1473: voting → v2_refused:identity_unresolved:team_only_mismatch | - |  |

## C'' vs B''nf: 1 material rows

| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |
|---|---|---|---|---|---|---|---|---|
| Joe Milton | offense/QB | 1435.0→1388.0 | -3.3% | 578→609 | low->low | fantasyProsFitzmaurice 1473: voting → v2_refused:identity_unresolved:team_only_mismatch | - |  |

