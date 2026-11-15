# Expected activation impact: pin2015

Exact for this frozen input (identical payload, CSVs, data, weights, configuration; only the DLF flags and the per-row filter differ). V2 at provisional thresholds, NO-HISTORY. Every row whose value or confidence changes is listed in `impact_values_pin2015.csv` (every change, rank-only cascades included, in `impact_all_pin2015.csv.gz`) with its source-level attribution.

| scenario | class | priced rows | value moved (up/down) | median |Δ| of moved | p90 | max | ≥5 % | ≥10 % | rank Δ≥25 | confidence changes |
|---|---|---|---|---|---|---|---|---|---|---|
| S1 (D vs A) | offense | 488 | 189 (155/34) | 0.14 % | 2.49 % | 34.57 % | 2 | 1 | 4 | {'high->medium': 6, 'medium->low': 6, 'low->medium': 1, 'medium->high': 1} |
|  | idp | 397 | 0 (0/0) | 0.0 % | 0.0 % | 0.0 % | 0 | 0 | 0 |  |
|  | pick | 120 | 25 (23/2) | 0.41 % | 1.94 % | 3.09 % | 0 | 0 | 0 |  |
| S2 (C vs A) | offense | 488 | 190 (155/35) | 0.15 % | 2.57 % | 34.57 % | 2 | 1 | 5 | {'high->medium': 6, 'medium->low': 6, 'low->medium': 1, 'medium->high': 1} |
|  | idp | 397 | 180 (100/80) | 1.27 % | 4.01 % | 6.66 % | 8 | 0 | 13 | {'low->medium': 26, 'medium->low': 20} |
|  | pick | 120 | 51 (41/10) | 0.69 % | 2.43 % | 4.74 % | 0 | 0 | 0 |  |
| S3 (C' vs A) | offense | 488 | 351 (167/184) | 0.31 % | 1.94 % | 34.57 % | 3 | 1 | 6 | {'high->medium': 8, 'medium->low': 8, 'low->medium': 8, 'medium->high': 4} |
|  | idp | 397 | 0 (0/0) | 0.0 % | 0.0 % | 0.0 % | 0 | 0 | 0 |  |
|  | pick | 120 | 50 (35/15) | 0.17 % | 1.14 % | 4.12 % | 0 | 0 | 0 |  |
| S4 (C'' vs A) | offense | 488 | 352 (167/185) | 0.31 % | 1.94 % | 34.57 % | 3 | 1 | 6 | {'high->medium': 8, 'medium->low': 8, 'low->medium': 8, 'medium->high': 4} |
|  | idp | 397 | 180 (100/80) | 1.27 % | 4.01 % | 6.66 % | 8 | 0 | 13 | {'low->medium': 26, 'medium->low': 20} |
|  | pick | 120 | 66 (46/20) | 0.57 % | 2.35 % | 4.74 % | 0 | 0 | 0 |  |
| I1 (C vs D) | offense | 488 | 1 (0/1) | 2.95 % | 2.95 % | 2.95 % | 0 | 0 | 0 |  |
|  | idp | 397 | 180 (100/80) | 1.27 % | 4.01 % | 6.66 % | 8 | 0 | 13 | {'low->medium': 26, 'medium->low': 20} |
|  | pick | 120 | 38 (29/9) | 0.52 % | 2.43 % | 4.74 % | 0 | 0 | 0 |  |
| I2 (C' vs D) | offense | 488 | 302 (111/191) | 0.21 % | 1.26 % | 4.39 % | 0 | 0 | 2 | {'medium->low': 3, 'high->medium': 2, 'low->medium': 8, 'medium->high': 3} |
|  | idp | 397 | 0 (0/0) | 0.0 % | 0.0 % | 0.0 % | 0 | 0 | 0 |  |
|  | pick | 120 | 43 (25/18) | 0.11 % | 0.59 % | 1.47 % | 0 | 0 | 0 |  |
| I3 (C'' vs C) | offense | 488 | 302 (111/191) | 0.21 % | 1.26 % | 4.39 % | 0 | 0 | 2 | {'medium->low': 3, 'high->medium': 2, 'low->medium': 8, 'medium->high': 3} |
|  | idp | 397 | 0 (0/0) | 0.0 % | 0.0 % | 0.0 % | 0 | 0 | 0 |  |
|  | pick | 120 | 42 (24/18) | 0.11 % | 0.59 % | 1.41 % | 0 | 0 | 0 |  |
| I4 (C'' vs C') | offense | 488 | 1 (0/1) | 2.95 % | 2.95 % | 2.95 % | 0 | 0 | 0 |  |
|  | idp | 397 | 180 (100/80) | 1.27 % | 4.01 % | 6.66 % | 8 | 0 | 13 | {'low->medium': 26, 'medium->low': 20} |
|  | pick | 120 | 37 (28/9) | 0.69 % | 2.43 % | 4.58 % | 0 | 0 | 0 |  |

## S1: V2 only (DLF IDP held, D4 off) — board D vs A

* top-100 membership: entered none; left none
* top-200 membership: entered ['Dalton Schultz', 'Michael Mayer']; left ['2029 Mid 2nd', 'Woody Marks']

| row | class | pos | before | after | Δ % | rank | confidence | attribution |
|---|---|---|---|---|---|---|---|---|
| LaJohntay Wester | offense | WR | 648 | 872 | 34.57 | None → None | low → low | flockFantasySf 1889: filter_dropped -> voting |
| KaVontae Turpin | offense | WR | 1159 | 1226 | 5.78 | None → 707 | medium → low | pfkDynasty 2362: filter_dropped -> voting |
| Malik Benson | offense | WR | 1221 | 1274 | 4.34 | 712 → 678 | medium → low | draftSharks 2304: filter_dropped -> voting; fantasyProsFitzmaurice vote 1544 -> 1555; flockFantasySf vote 1068 -> 1071 |
| Cole Payton | offense | QB | 1082 | 1041 | -3.79 | None → None | low → low | fantasyProsFitzmaurice vote 1872 -> 1880; flockFantasySf 1527: voting -> absent |
| Deshaun Watson | offense | QB | 2451 | 2544 | 3.79 | 242 → 227 | medium → low | fantasyProsFitzmaurice vote 2080 -> 2091; yahooBoone 3470: filter_dropped -> voting |
| Javonte Williams | offense | RB | 5148 | 4967 | -3.52 | 61 → 66 | high → high | dlfSf 3904: filter_dropped -> voting; draftSharks 3315: filter_dropped -> voting |
| Marlin Klein | offense | TE | 1779 | 1841 | 3.49 | 408 → 384 | medium → medium | draftSharks 3061: filter_dropped -> voting; flockFantasySf vote 1811 -> 1815 |
| Michael Mayer | offense | TE | 2722 | 2816 | 3.45 | 203 → 191 | medium → low | draftSharks 3924: filter_dropped -> voting; fantasyProsFitzmaurice vote 2203 -> 2214 |
| Justin Herbert | offense | QB | 5787 | 5985 | 3.42 | 41 → 37 | medium → medium | draftSharks 7898: filter_dropped -> voting; yahooBoone 7644: filter_dropped -> voting |
| Baker Mayfield | offense | QB | 3884 | 4014 | 3.35 | 112 → 106 | high → high | dlfSf 5097: filter_dropped -> voting; draftSharks 5352: filter_dropped -> voting |
| Amon-Ra St. Brown | offense | WR | 8924 | 8630 | -3.29 | 9 → 10 | high → high | draftSharks 6227: filter_dropped -> voting; ktcCrowdSfTep 7523: filter_dropped -> voting |
| Joe Milton | offense | QB | 1435 | 1388 | -3.28 | 576 → 614 | low → low | fantasyProsFitzmaurice 1473: voting -> absent; flockFantasySf vote 1124 -> 1128 |
| 2027 Pick 1.01 | pick | PICK | 7238 | 7462 | 3.09 | None → None | low → low | rookie_pool_tether (Jeremiyah Love) |
| Jeremiyah Love | offense | RB | 7238 | 7462 | 3.09 | 24 → 21 | high → high | flockFantasySf 8814: filter_dropped -> voting; otcffbSf 8318: filter_dropped -> voting |
| Kenneth Walker | offense | RB | 7368 | 7580 | 2.88 | 20 → 18 | medium → high | fantasyCalc 8814: filter_dropped -> voting; otcffbSf 8944: filter_dropped -> voting; pfkDynasty 8687: filter_dropped -> voting |

## S2: V2 + DLF IDP + DLF Rookie IDP (§9 primary target) — board C vs A

* top-100 membership: entered ['Makai Lemon']; left ['Fred Warner']
* top-200 membership: entered ['Anthony Hill', 'Dalton Schultz', 'Jared Verse', 'Laiatu Latu', 'Michael Mayer', 'Nick Bosa']; left ['2029 Mid 2nd', 'Braelon Allen', 'DeMarvion Overshown', 'Emmett Johnson', 'Tremaine Edmunds', 'Woody Marks']

| row | class | pos | before | after | Δ % | rank | confidence | attribution |
|---|---|---|---|---|---|---|---|---|
| LaJohntay Wester | offense | WR | 648 | 872 | 34.57 | None → None | low → low | flockFantasySf 1889: filter_dropped -> voting |
| Jacob Rodriguez | idp | LB | 4624 | 4932 | 6.66 | 77 → 68 | low → medium | dlfIdp 4726: absent -> voting; dlfRookieIdp 5165: absent -> voting |
| Jared Verse | idp | DL | 2666 | 2829 | 6.11 | 211 → 189 | medium → low | dlfIdp 4671: absent -> voting |
| Alex Singleton | idp | LB | 1949 | 1836 | -5.8 | 337 → 384 | medium → medium | dlfIdp 1964: absent -> voting |
| KaVontae Turpin | offense | WR | 1159 | 1226 | 5.78 | None → 707 | medium → low | pfkDynasty 2362: filter_dropped -> voting |
| Josh Sweat | idp | DL | 1671 | 1575 | -5.75 | 461 → 500 | low → low | dlfIdp 1513: absent -> voting |
| Dexter Lawrence | idp | DL | 1793 | 1895 | 5.69 | 400 → 364 | medium → low | dlfIdp 2621: absent -> voting |
| Josiah Trotter | idp | LB | 2368 | 2493 | 5.28 | 257 → 239 | low → low | dlfIdp 3171: absent -> voting; dlfRookieIdp 3283: absent -> voting |
| Abdul Carter | idp | DL | 3646 | 3838 | 5.27 | 125 → 114 | low → low | dlfIdp 4811: absent -> voting |
| Robert Spillane | idp | LB | 2187 | 2073 | -5.21 | 288 → 313 | medium → medium | dlfIdp 1962: absent -> voting |
| Quinnen Williams | idp | DL | 1847 | 1936 | 4.82 | 381 → 342 | medium → low | dlfIdp 2557: absent -> voting |
| 2027 Pick 1.06 | pick | PICK | 4709 | 4932 | 4.74 | None → None | low → low | rookie_pool_tether (Jacob Rodriguez) |
| Quincy Williams | idp | LB | 2184 | 2082 | -4.67 | 290 → 311 | medium → medium | dlfIdp 1982: absent -> voting |
| Roquan Smith | idp | LB | 3323 | 3169 | -4.63 | 151 → 162 | low → medium | dlfIdp 3371: absent -> voting |
| Kam Curl | idp | DB | 1919 | 1831 | -4.59 | 348 → 387 | medium → low | dlfIdp 1513: absent -> voting |

## S3: V2 + D4 (DLF IDP held) — board C' vs A

* top-100 membership: entered none; left none
* top-200 membership: entered ['Dalton Schultz', 'Michael Mayer']; left ['2029 Mid 2nd', 'Woody Marks']

| row | class | pos | before | after | Δ % | rank | confidence | attribution |
|---|---|---|---|---|---|---|---|---|
| LaJohntay Wester | offense | WR | 648 | 872 | 34.57 | None → None | low → low | flockFantasySf 1889: filter_dropped -> voting |
| Malik Benson | offense | WR | 1221 | 1298 | 6.31 | 712 → 664 | medium → low | dlfValuesSfTep 1277: absent -> voting; draftSharks 2304: filter_dropped -> voting; fantasyProsFitzmaurice vote 1544 -> 1555; flockFantasySf vote 1068 -> 1071 |
| KaVontae Turpin | offense | WR | 1159 | 1226 | 5.78 | None → 707 | medium → low | pfkDynasty 2362: filter_dropped -> voting |
| Jack Strand | offense | QB | 1207 | 1260 | 4.39 | 721 → 685 | low → low | dlfValuesSfTep 1357: absent -> voting |
| Deshaun Watson | offense | QB | 2451 | 2556 | 4.28 | 242 → 226 | medium → medium | dlfValuesSfTep 2427: absent -> voting; fantasyProsFitzmaurice vote 2080 -> 2091; yahooBoone 3470: filter_dropped -> voting |
| 2027 Pick 1.01 | pick | PICK | 7238 | 7536 | 4.12 | None → None | low → low | rookie_pool_tether (Jeremiyah Love) |
| Jeremiyah Love | offense | RB | 7238 | 7536 | 4.12 | 24 → 20 | high → high | dlfValuesSfTep 8084: absent -> voting; flockFantasySf 8814: filter_dropped -> voting; otcffbSf 8318: filter_dropped -> voting |
| Brenen Thompson | offense | WR | 1370 | 1422 | 3.8 | 623 → 586 | medium → medium | dlfValuesSfTep 1478: absent -> voting; draftSharks 2496: filter_dropped -> voting; fantasyProsFitzmaurice vote 1544 -> 1555; flockFantasySf vote 1348 -> 1352 |
| Cole Payton | offense | QB | 1082 | 1041 | -3.79 | None → None | low → low | fantasyProsFitzmaurice vote 1872 -> 1880; flockFantasySf 1527: voting -> absent |
| Michael Mayer | offense | TE | 2722 | 2825 | 3.78 | 203 → 191 | medium → low | dlfValuesSfTep 2584: absent -> voting; draftSharks 3924: filter_dropped -> voting; fantasyProsFitzmaurice vote 2203 -> 2214 |
| Theo Johnson | offense | TE | 2186 | 2105 | -3.71 | 289 → 309 | medium → medium | dlfValuesSfTep 1603: absent -> voting |
| Javonte Williams | offense | RB | 5148 | 4967 | -3.52 | 61 → 66 | high → high | dlfSf 3904: filter_dropped -> voting; dlfValuesSfTep 4178: absent -> voting; draftSharks 3315: filter_dropped -> voting |
| Amon-Ra St. Brown | offense | WR | 8924 | 8615 | -3.46 | 9 → 10 | high → high | dlfValuesSfTep 8944: absent -> voting; draftSharks 6227: filter_dropped -> voting; ktcCrowdSfTep 7523: filter_dropped -> voting |
| Darnell Washington | offense | TE | 2120 | 2049 | -3.35 | 305 → 317 | low → low | dlfValuesSfTep 1559: absent -> voting; fantasyProsFitzmaurice vote 1698 -> 1711; flockFantasySf vote 1794 -> 1798 |
| Justin Herbert | offense | QB | 5787 | 5980 | 3.34 | 41 → 37 | medium → medium | dlfValuesSfTep 6699: absent -> voting; draftSharks 7898: filter_dropped -> voting; yahooBoone 7644: filter_dropped -> voting |

## S4: V2 + DLF IDP + DLF Rookie IDP + D4 (everything) — board C'' vs A

* top-100 membership: entered none; left none
* top-200 membership: entered ['Anthony Hill', 'Dalton Schultz', 'Jared Verse', 'Laiatu Latu', 'Michael Mayer', 'Nick Bosa']; left ['2029 Mid 2nd', 'Braelon Allen', 'DeMarvion Overshown', 'Tremaine Edmunds', "Wan'Dale Robinson", 'Woody Marks']

| row | class | pos | before | after | Δ % | rank | confidence | attribution |
|---|---|---|---|---|---|---|---|---|
| LaJohntay Wester | offense | WR | 648 | 872 | 34.57 | None → None | low → low | flockFantasySf 1889: filter_dropped -> voting |
| Jacob Rodriguez | idp | LB | 4624 | 4932 | 6.66 | 77 → 67 | low → medium | dlfIdp 4726: absent -> voting; dlfRookieIdp 5165: absent -> voting |
| Malik Benson | offense | WR | 1221 | 1298 | 6.31 | 712 → 664 | medium → low | dlfValuesSfTep 1277: absent -> voting; draftSharks 2304: filter_dropped -> voting; fantasyProsFitzmaurice vote 1544 -> 1555; flockFantasySf vote 1068 -> 1071 |
| Jared Verse | idp | DL | 2666 | 2829 | 6.11 | 211 → 189 | medium → low | dlfIdp 4671: absent -> voting |
| Alex Singleton | idp | LB | 1949 | 1836 | -5.8 | 337 → 383 | medium → medium | dlfIdp 1964: absent -> voting |
| KaVontae Turpin | offense | WR | 1159 | 1226 | 5.78 | None → 707 | medium → low | pfkDynasty 2362: filter_dropped -> voting |
| Josh Sweat | idp | DL | 1671 | 1575 | -5.75 | 461 → 499 | low → low | dlfIdp 1513: absent -> voting |
| Dexter Lawrence | idp | DL | 1793 | 1895 | 5.69 | 400 → 363 | medium → low | dlfIdp 2621: absent -> voting |
| Josiah Trotter | idp | LB | 2368 | 2493 | 5.28 | 257 → 239 | low → low | dlfIdp 3171: absent -> voting; dlfRookieIdp 3283: absent -> voting |
| Abdul Carter | idp | DL | 3646 | 3838 | 5.27 | 125 → 114 | low → low | dlfIdp 4811: absent -> voting |
| Robert Spillane | idp | LB | 2187 | 2073 | -5.21 | 288 → 313 | medium → medium | dlfIdp 1962: absent -> voting |
| Quinnen Williams | idp | DL | 1847 | 1936 | 4.82 | 381 → 342 | medium → low | dlfIdp 2557: absent -> voting |
| 2027 Pick 1.06 | pick | PICK | 4709 | 4932 | 4.74 | None → None | low → low | rookie_pool_tether (Jacob Rodriguez) |
| Quincy Williams | idp | LB | 2184 | 2082 | -4.67 | 290 → 310 | medium → medium | dlfIdp 1982: absent -> voting |
| Roquan Smith | idp | LB | 3323 | 3169 | -4.63 | 151 → 161 | low → medium | dlfIdp 3371: absent -> voting |

## I1: increment: DLF IDP given V2 — board C vs D

* top-100 membership: entered ['Makai Lemon']; left ['Fred Warner']
* top-200 membership: entered ['Anthony Hill', 'Jared Verse', 'Laiatu Latu', 'Nick Bosa']; left ['Braelon Allen', 'DeMarvion Overshown', 'Emmett Johnson', 'Tremaine Edmunds']

| row | class | pos | before | after | Δ % | rank | confidence | attribution |
|---|---|---|---|---|---|---|---|---|
| Jacob Rodriguez | idp | LB | 4624 | 4932 | 6.66 | 78 → 68 | low → medium | dlfIdp 4726: absent -> voting; dlfRookieIdp 5165: absent -> voting |
| Jared Verse | idp | DL | 2666 | 2829 | 6.11 | 211 → 189 | medium → low | dlfIdp 4671: absent -> voting |
| Alex Singleton | idp | LB | 1949 | 1836 | -5.8 | 337 → 384 | medium → medium | dlfIdp 1964: absent -> voting |
| Josh Sweat | idp | DL | 1671 | 1575 | -5.75 | 461 → 500 | low → low | dlfIdp 1513: absent -> voting |
| Dexter Lawrence | idp | DL | 1793 | 1895 | 5.69 | 402 → 364 | medium → low | dlfIdp 2621: absent -> voting |
| Josiah Trotter | idp | LB | 2368 | 2493 | 5.28 | 257 → 239 | low → low | dlfIdp 3171: absent -> voting; dlfRookieIdp 3283: absent -> voting |
| Abdul Carter | idp | DL | 3646 | 3838 | 5.27 | 126 → 114 | low → low | dlfIdp 4811: absent -> voting |
| Robert Spillane | idp | LB | 2187 | 2073 | -5.21 | 288 → 313 | medium → medium | dlfIdp 1962: absent -> voting |
| Quinnen Williams | idp | DL | 1847 | 1936 | 4.82 | 381 → 342 | medium → low | dlfIdp 2557: absent -> voting |
| 2027 Pick 1.06 | pick | PICK | 4709 | 4932 | 4.74 | None → None | low → low | rookie_pool_tether (Jacob Rodriguez) |
| Quincy Williams | idp | LB | 2184 | 2082 | -4.67 | 290 → 311 | medium → medium | dlfIdp 1982: absent -> voting |
| Roquan Smith | idp | LB | 3323 | 3169 | -4.63 | 151 → 162 | low → medium | dlfIdp 3371: absent -> voting |
| Kam Curl | idp | DB | 1919 | 1831 | -4.59 | 349 → 387 | medium → low | dlfIdp 1513: absent -> voting |
| Micah Parsons | idp | DL | 3382 | 3535 | 4.52 | 144 → 134 | low → low | dlfIdp 5096: absent -> voting |
| Greg Rousseau | idp | DL | 2840 | 2966 | 4.44 | 187 → 176 | low → low | dlfIdp 3315: absent -> voting |

## I2: increment: D4 given V2 — board C' vs D

* top-100 membership: entered none; left none
* top-200 membership: entered none; left none

| row | class | pos | before | after | Δ % | rank | confidence | attribution |
|---|---|---|---|---|---|---|---|---|
| Jack Strand | offense | QB | 1207 | 1260 | 4.39 | 722 → 685 | low → low | dlfValuesSfTep 1357: absent -> voting |
| Theo Johnson | offense | TE | 2186 | 2105 | -3.71 | 289 → 309 | medium → medium | dlfValuesSfTep 1603: absent -> voting |
| Darnell Washington | offense | TE | 2121 | 2049 | -3.39 | 306 → 317 | low → low | dlfValuesSfTep 1559: absent -> voting |
| Darren Waller | offense | TE | 2234 | 2170 | -2.86 | 281 → 291 | medium → low | dlfValuesSfTep 1855: absent -> voting |
| Tez Johnson | offense | WR | 1483 | 1446 | -2.49 | 541 → 572 | low → medium | dlfValuesSfTep 1293: absent -> voting |
| Ryan Flournoy | offense | WR | 1780 | 1737 | -2.42 | 411 → 427 | low → medium | dlfValuesSfTep 1653: absent -> voting |
| Evan Engram | offense | TE | 2167 | 2117 | -2.31 | 295 → 308 | medium → medium | dlfValuesSfTep 1916: absent -> voting |
| Colby Parkinson | offense | TE | 2035 | 1992 | -2.11 | 322 → 328 | low → low | dlfValuesSfTep 1383: absent -> voting |
| Jalen Milroe | offense | QB | 1614 | 1581 | -2.04 | 490 → 497 | medium → medium | dlfValuesSfTep 1516: absent -> voting |
| Cedric Tillman | offense | WR | 1329 | 1302 | -2.03 | 647 → 662 | medium → medium | dlfValuesSfTep 1309: absent -> voting |
| Malik Benson | offense | WR | 1274 | 1298 | 1.88 | 678 → 664 | low → low | dlfValuesSfTep 1277: absent -> voting |
| Chris Godwin | offense | WR | 2516 | 2471 | -1.79 | 232 → 238 | medium → low | dlfValuesSfTep 2400: absent -> voting |
| Tyquan Thornton | offense | WR | 1579 | 1551 | -1.77 | 498 → 506 | low → low | dlfValuesSfTep 1313: absent -> voting |
| Isaiah Bond | offense | WR | 1490 | 1464 | -1.74 | 538 → 554 | low → low | dlfValuesSfTep 1326: absent -> voting |
| Jalen Nailor | offense | WR | 1662 | 1633 | -1.74 | 468 → 478 | medium → medium | dlfValuesSfTep 1398: absent -> voting |

## I3: increment: D4 given V2 + DLF IDP — board C'' vs C

* top-100 membership: entered ['Fred Warner']; left ['Makai Lemon']
* top-200 membership: entered ['Emmett Johnson']; left ["Wan'Dale Robinson"]

| row | class | pos | before | after | Δ % | rank | confidence | attribution |
|---|---|---|---|---|---|---|---|---|
| Jack Strand | offense | QB | 1207 | 1260 | 4.39 | 722 → 687 | low → low | dlfValuesSfTep 1357: absent -> voting |
| Theo Johnson | offense | TE | 2186 | 2105 | -3.71 | 288 → 306 | medium → medium | dlfValuesSfTep 1603: absent -> voting |
| Darnell Washington | offense | TE | 2121 | 2049 | -3.39 | 301 → 317 | low → low | dlfValuesSfTep 1559: absent -> voting |
| Darren Waller | offense | TE | 2234 | 2170 | -2.86 | 278 → 289 | medium → low | dlfValuesSfTep 1855: absent -> voting |
| Tez Johnson | offense | WR | 1483 | 1446 | -2.49 | 545 → 574 | low → medium | dlfValuesSfTep 1293: absent -> voting |
| Ryan Flournoy | offense | WR | 1780 | 1737 | -2.42 | 413 → 428 | low → medium | dlfValuesSfTep 1653: absent -> voting |
| Evan Engram | offense | TE | 2167 | 2117 | -2.31 | 293 → 302 | medium → medium | dlfValuesSfTep 1916: absent -> voting |
| Colby Parkinson | offense | TE | 2035 | 1992 | -2.11 | 322 → 329 | low → low | dlfValuesSfTep 1383: absent -> voting |
| Jalen Milroe | offense | QB | 1614 | 1581 | -2.04 | 490 → 496 | medium → medium | dlfValuesSfTep 1516: absent -> voting |
| Cedric Tillman | offense | WR | 1329 | 1302 | -2.03 | 647 → 662 | medium → medium | dlfValuesSfTep 1309: absent -> voting |
| Malik Benson | offense | WR | 1274 | 1298 | 1.88 | 678 → 664 | low → low | dlfValuesSfTep 1277: absent -> voting |
| Chris Godwin | offense | WR | 2516 | 2471 | -1.79 | 233 → 240 | medium → low | dlfValuesSfTep 2400: absent -> voting |
| Tyquan Thornton | offense | WR | 1579 | 1551 | -1.77 | 497 → 507 | low → low | dlfValuesSfTep 1313: absent -> voting |
| Isaiah Bond | offense | WR | 1490 | 1464 | -1.74 | 542 → 556 | low → low | dlfValuesSfTep 1326: absent -> voting |
| Jalen Nailor | offense | WR | 1662 | 1633 | -1.74 | 466 → 477 | medium → medium | dlfValuesSfTep 1398: absent -> voting |

## I4: increment: DLF IDP given V2 + D4 — board C'' vs C'

* top-100 membership: entered none; left none
* top-200 membership: entered ['Anthony Hill', 'Jared Verse', 'Laiatu Latu', 'Nick Bosa']; left ['Braelon Allen', 'DeMarvion Overshown', 'Tremaine Edmunds', "Wan'Dale Robinson"]

| row | class | pos | before | after | Δ % | rank | confidence | attribution |
|---|---|---|---|---|---|---|---|---|
| Jacob Rodriguez | idp | LB | 4624 | 4932 | 6.66 | 78 → 67 | low → medium | dlfIdp 4726: absent -> voting; dlfRookieIdp 5165: absent -> voting |
| Jared Verse | idp | DL | 2666 | 2829 | 6.11 | 211 → 189 | medium → low | dlfIdp 4671: absent -> voting |
| Alex Singleton | idp | LB | 1949 | 1836 | -5.8 | 337 → 383 | medium → medium | dlfIdp 1964: absent -> voting |
| Josh Sweat | idp | DL | 1671 | 1575 | -5.75 | 461 → 499 | low → low | dlfIdp 1513: absent -> voting |
| Dexter Lawrence | idp | DL | 1793 | 1895 | 5.69 | 402 → 363 | medium → low | dlfIdp 2621: absent -> voting |
| Josiah Trotter | idp | LB | 2368 | 2493 | 5.28 | 257 → 239 | low → low | dlfIdp 3171: absent -> voting; dlfRookieIdp 3283: absent -> voting |
| Abdul Carter | idp | DL | 3646 | 3838 | 5.27 | 126 → 114 | low → low | dlfIdp 4811: absent -> voting |
| Robert Spillane | idp | LB | 2187 | 2073 | -5.21 | 286 → 313 | medium → medium | dlfIdp 1962: absent -> voting |
| Quinnen Williams | idp | DL | 1847 | 1936 | 4.82 | 381 → 342 | medium → low | dlfIdp 2557: absent -> voting |
| Quincy Williams | idp | LB | 2184 | 2082 | -4.67 | 287 → 310 | medium → medium | dlfIdp 1982: absent -> voting |
| Roquan Smith | idp | LB | 3323 | 3169 | -4.63 | 150 → 161 | low → medium | dlfIdp 3371: absent -> voting |
| Kam Curl | idp | DB | 1919 | 1831 | -4.59 | 349 → 385 | medium → low | dlfIdp 1513: absent -> voting |
| 2027 Pick 1.06 | pick | PICK | 4716 | 4932 | 4.58 | None → None | low → low | rookie_pool_tether (Jacob Rodriguez) |
| Micah Parsons | idp | DL | 3382 | 3535 | 4.52 | 144 → 134 | low → low | dlfIdp 5096: absent -> voting |
| Greg Rousseau | idp | DL | 2840 | 2966 | 4.44 | 187 → 177 | low → low | dlfIdp 3315: absent -> voting |

