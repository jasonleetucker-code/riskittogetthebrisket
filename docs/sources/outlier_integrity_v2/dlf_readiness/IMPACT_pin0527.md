# Expected activation impact: pin0527

Exact for this frozen input (identical payload, CSVs, data, weights, configuration; only the DLF flags and the per-row filter differ). V2 at provisional thresholds, NO-HISTORY. Every row whose value or confidence changes is listed in `impact_values_pin0527.csv` (every change, rank-only cascades included, in `impact_all_pin0527.csv.gz`) with its source-level attribution.

| scenario | class | priced rows | value moved (up/down) | median |Δ| of moved | p90 | max | ≥5 % | ≥10 % | rank Δ≥25 | confidence changes |
|---|---|---|---|---|---|---|---|---|---|---|
| S1 (D vs A) | offense | 488 | 240 (206/34) | 0.12 % | 1.89 % | 35.64 % | 2 | 1 | 3 | {'medium->high': 4, 'high->medium': 7, 'low->medium': 3, 'medium->low': 2} |
|  | idp | 397 | 0 (0/0) | 0.0 % | 0.0 % | 0.0 % | 0 | 0 | 0 |  |
|  | pick | 120 | 33 (30/3) | 0.29 % | 1.29 % | 2.81 % | 0 | 0 | 0 |  |
| S2 (C vs A) | offense | 488 | 241 (206/35) | 0.12 % | 2.03 % | 35.64 % | 2 | 1 | 1 | {'medium->high': 4, 'high->medium': 7, 'low->medium': 3, 'medium->low': 2} |
|  | idp | 397 | 179 (99/80) | 1.33 % | 4.02 % | 6.65 % | 8 | 0 | 10 | {'low->medium': 27, 'medium->low': 20} |
|  | pick | 120 | 53 (43/10) | 0.93 % | 2.31 % | 3.78 % | 0 | 0 | 0 |  |
| S3 (C' vs A) | offense | 488 | 394 (210/184) | 0.24 % | 1.81 % | 35.64 % | 3 | 1 | 7 | {'medium->high': 7, 'high->medium': 10, 'low->medium': 6, 'medium->low': 5} |
|  | idp | 397 | 0 (0/0) | 0.0 % | 0.0 % | 0.0 % | 0 | 0 | 0 |  |
|  | pick | 120 | 54 (36/18) | 0.23 % | 0.97 % | 4.16 % | 0 | 0 | 0 |  |
| S4 (C'' vs A) | offense | 488 | 395 (210/185) | 0.24 % | 1.81 % | 35.64 % | 3 | 1 | 6 | {'medium->high': 7, 'high->medium': 10, 'low->medium': 6, 'medium->low': 5} |
|  | idp | 397 | 179 (99/80) | 1.33 % | 4.02 % | 6.65 % | 8 | 0 | 10 | {'low->medium': 27, 'medium->low': 20} |
|  | pick | 120 | 69 (47/22) | 0.52 % | 2.35 % | 4.16 % | 0 | 0 | 0 |  |
| I1 (C vs D) | offense | 488 | 1 (0/1) | 2.95 % | 2.95 % | 2.95 % | 0 | 0 | 0 |  |
|  | idp | 397 | 179 (99/80) | 1.33 % | 4.02 % | 6.65 % | 8 | 0 | 10 | {'low->medium': 27, 'medium->low': 20} |
|  | pick | 120 | 38 (28/10) | 0.7 % | 2.3 % | 3.78 % | 0 | 0 | 0 |  |
| I2 (C' vs D) | offense | 488 | 301 (108/193) | 0.22 % | 1.32 % | 5.13 % | 1 | 0 | 3 | {'low->medium': 3, 'medium->low': 3, 'high->medium': 4, 'medium->high': 4} |
|  | idp | 397 | 0 (0/0) | 0.0 % | 0.0 % | 0.0 % | 0 | 0 | 0 |  |
|  | pick | 120 | 39 (20/19) | 0.11 % | 0.65 % | 1.32 % | 0 | 0 | 0 |  |
| I3 (C'' vs C) | offense | 488 | 301 (108/193) | 0.22 % | 1.32 % | 5.13 % | 1 | 0 | 3 | {'low->medium': 3, 'medium->low': 3, 'high->medium': 4, 'medium->high': 4} |
|  | idp | 397 | 0 (0/0) | 0.0 % | 0.0 % | 0.0 % | 0 | 0 | 0 |  |
|  | pick | 120 | 39 (20/19) | 0.11 % | 0.66 % | 1.32 % | 0 | 0 | 0 |  |
| I4 (C'' vs C') | offense | 488 | 1 (0/1) | 2.95 % | 2.95 % | 2.95 % | 0 | 0 | 0 |  |
|  | idp | 397 | 179 (99/80) | 1.33 % | 4.02 % | 6.65 % | 8 | 0 | 11 | {'low->medium': 27, 'medium->low': 20} |
|  | pick | 120 | 40 (29/11) | 0.65 % | 2.61 % | 3.78 % | 0 | 0 | 0 |  |

## S1: V2 only (DLF IDP held, D4 off) — board D vs A

* top-100 membership: entered none; left none
* top-200 membership: entered ['Michael Mayer']; left ['Braelon Allen']

| row | class | pos | before | after | Δ % | rank | confidence | attribution |
|---|---|---|---|---|---|---|---|---|
| LaJohntay Wester | offense | WR | 651 | 883 | 35.64 | None → None | low → low | flockFantasySf 1889: filter_dropped -> voting; otcffbSf vote 930 -> 932 |
| KaVontae Turpin | offense | WR | 1164 | 1223 | 5.07 | None → 714 | medium → low | otcffbSf vote 1062 -> 1065; pfkDynasty 2362: filter_dropped -> voting |
| Justin Herbert | offense | QB | 5751 | 5981 | 4.0 | 41 → 37 | medium → medium | draftSharks 7898: filter_dropped -> voting; yahooBoone 7644: filter_dropped -> voting |
| Baker Mayfield | offense | QB | 3858 | 4011 | 3.97 | 113 → 105 | medium → high | dlfSf 5203: filter_dropped -> voting; draftSharks 5238: filter_dropped -> voting |
| Deshaun Watson | offense | QB | 2445 | 2541 | 3.93 | 244 → 228 | medium → medium | fantasyProsFitzmaurice vote 2080 -> 2091; yahooBoone 3470: filter_dropped -> voting |
| Nate Boerkircher | offense | TE | 1671 | 1736 | 3.89 | 457 → 429 | low → low | draftSharks 2850: filter_dropped -> voting |
| Cole Payton | offense | QB | 1111 | 1070 | -3.69 | None → None | medium → medium | fantasyProsFitzmaurice vote 1872 -> 1880; flockFantasySf 1527: voting -> absent |
| Javonte Williams | offense | RB | 5173 | 4990 | -3.54 | 61 → 64 | high → high | dlfSf 3779: filter_dropped -> voting; draftSharks 3304: filter_dropped -> voting |
| Amon-Ra St. Brown | offense | WR | 8921 | 8625 | -3.32 | 9 → 10 | high → high | draftSharks 6167: filter_dropped -> voting; ktcCrowdSfTep 7534: filter_dropped -> voting |
| Malik Benson | offense | WR | 1271 | 1311 | 3.15 | 680 → 658 | low → low | draftSharks 2304: filter_dropped -> voting; fantasyProsFitzmaurice vote 1544 -> 1555; flockFantasySf vote 1065 -> 1068 |
| Marlin Klein | offense | TE | 1790 | 1845 | 3.07 | 397 → 380 | medium → medium | draftSharks 2877: filter_dropped -> voting; flockFantasySf vote 1811 -> 1815; otcffbSf vote 1794 -> 1798 |
| Chris Brazzell | offense | WR | 1726 | 1776 | 2.9 | 430 → 412 | medium → medium | draftSharks 3132: filter_dropped -> voting; fantasyProsFitzmaurice vote 1848 -> 1856 |
| 2027 Pick 1.01 | pick | PICK | 7228 | 7431 | 2.81 | None → None | low → low | rookie_pool_tether (Jeremiyah Love) |
| Jeremiyah Love | offense | RB | 7228 | 7431 | 2.81 | 24 → 21 | high → high | flockFantasySf 8814: filter_dropped -> voting; otcffbSf 8318: filter_dropped -> voting |
| Colby Parkinson | offense | TE | 1919 | 1968 | 2.55 | 346 → 334 | low → low | draftSharks 3149: filter_dropped -> voting; fantasyProsFitzmaurice vote 1812 -> 1826; otcffbSf vote 1729 -> 1733 |

## S2: V2 + DLF IDP + DLF Rookie IDP (§9 primary target) — board C vs A

* top-100 membership: entered none; left none
* top-200 membership: entered ['Anthony Hill', 'Jared Verse', 'Laiatu Latu', 'Nick Bosa']; left ['2029 Mid 2nd', 'Braelon Allen', 'DeMarvion Overshown', 'Emmett Johnson']

| row | class | pos | before | after | Δ % | rank | confidence | attribution |
|---|---|---|---|---|---|---|---|---|
| LaJohntay Wester | offense | WR | 651 | 883 | 35.64 | None → None | low → low | flockFantasySf 1889: filter_dropped -> voting; otcffbSf vote 930 -> 932 |
| Jacob Rodriguez | idp | LB | 4617 | 4924 | 6.65 | 79 → 68 | low → medium | dlfIdp 4726: absent -> voting; dlfRookieIdp 5165: absent -> voting |
| Jared Verse | idp | DL | 2672 | 2835 | 6.1 | 212 → 189 | medium → low | dlfIdp 4671: absent -> voting |
| Alex Singleton | idp | LB | 1953 | 1841 | -5.73 | 336 → 382 | medium → medium | dlfIdp 1964: absent -> voting |
| Josh Sweat | idp | DL | 1664 | 1569 | -5.71 | 463 → 498 | low → low | dlfIdp 1513: absent -> voting |
| Dexter Lawrence | idp | DL | 1795 | 1896 | 5.63 | 395 → 361 | medium → low | dlfIdp 2621: absent -> voting |
| Robert Spillane | idp | LB | 2182 | 2068 | -5.22 | 289 → 313 | medium → medium | dlfIdp 1962: absent -> voting |
| Abdul Carter | idp | DL | 3679 | 3870 | 5.19 | 122 → 113 | low → low | dlfIdp 4811: absent -> voting |
| Josiah Trotter | idp | LB | 2390 | 2514 | 5.19 | 253 → 234 | low → low | dlfIdp 3171: absent -> voting; dlfRookieIdp 3283: absent -> voting |
| KaVontae Turpin | offense | WR | 1164 | 1223 | 5.07 | None → 714 | medium → low | otcffbSf vote 1062 -> 1065; pfkDynasty 2362: filter_dropped -> voting |
| Quinnen Williams | idp | DL | 1849 | 1938 | 4.81 | 376 → 342 | medium → low | dlfIdp 2557: absent -> voting |
| Quincy Williams | idp | LB | 2179 | 2078 | -4.64 | 292 → 312 | medium → medium | dlfIdp 1982: absent -> voting |
| Kam Curl | idp | DB | 1921 | 1833 | -4.58 | 345 → 385 | medium → low | dlfIdp 1513: absent -> voting |
| Roquan Smith | idp | LB | 3337 | 3184 | -4.58 | 150 → 160 | low → medium | dlfIdp 3371: absent -> voting |
| Micah Parsons | idp | DL | 3427 | 3578 | 4.41 | 142 → 133 | low → low | dlfIdp 5096: absent -> voting |

## S3: V2 + D4 (DLF IDP held) — board C' vs A

* top-100 membership: entered none; left none
* top-200 membership: entered ['Michael Mayer']; left ['2029 Mid 2nd']

| row | class | pos | before | after | Δ % | rank | confidence | attribution |
|---|---|---|---|---|---|---|---|---|
| LaJohntay Wester | offense | WR | 651 | 883 | 35.64 | None → None | low → low | flockFantasySf 1889: filter_dropped -> voting; otcffbSf vote 930 -> 932 |
| Theo Johnson | offense | TE | 2164 | 2054 | -5.08 | 295 → 315 | low → low | dlfValuesSfTep 1597: absent -> voting; otcffbSf vote 1733 -> 1737 |
| KaVontae Turpin | offense | WR | 1164 | 1223 | 5.07 | None → 713 | medium → low | otcffbSf vote 1062 -> 1065; pfkDynasty 2362: filter_dropped -> voting |
| Deshaun Watson | offense | QB | 2445 | 2553 | 4.42 | 244 → 226 | medium → medium | dlfValuesSfTep 2440: absent -> voting; fantasyProsFitzmaurice vote 2080 -> 2091; yahooBoone 3470: filter_dropped -> voting |
| 2027 Pick 1.01 | pick | PICK | 7228 | 7529 | 4.16 | None → None | low → low | rookie_pool_tether (Jeremiyah Love) |
| Jeremiyah Love | offense | RB | 7228 | 7529 | 4.16 | 24 → 20 | high → high | dlfValuesSfTep 8084: absent -> voting; flockFantasySf 8814: filter_dropped -> voting; otcffbSf 8318: filter_dropped -> voting |
| Justin Herbert | offense | QB | 5751 | 5975 | 3.89 | 41 → 37 | medium → medium | dlfValuesSfTep 6699: absent -> voting; draftSharks 7898: filter_dropped -> voting; yahooBoone 7644: filter_dropped -> voting |
| Nate Boerkircher | offense | TE | 1671 | 1736 | 3.89 | 457 → 427 | low → low | draftSharks 2850: filter_dropped -> voting |
| DeMario Douglas | offense | WR | 1607 | 1545 | -3.86 | 486 → 504 | low → low | dlfValuesSfTep 1413: absent -> voting; fantasyProsFitzmaurice vote 1352 -> 1370; flockFantasySf vote 1234 -> 1238 |
| Malik Benson | offense | WR | 1271 | 1319 | 3.78 | 680 → 652 | low → low | dlfValuesSfTep 1285: absent -> voting; draftSharks 2304: filter_dropped -> voting; fantasyProsFitzmaurice vote 1544 -> 1555; flockFantasySf vote 1065 -> 1068 |
| Cole Payton | offense | QB | 1111 | 1070 | -3.69 | None → None | medium → medium | fantasyProsFitzmaurice vote 1872 -> 1880; flockFantasySf 1527: voting -> absent |
| Javonte Williams | offense | RB | 5173 | 4993 | -3.48 | 61 → 64 | high → high | dlfSf 3779: filter_dropped -> voting; dlfValuesSfTep 4178: absent -> voting; draftSharks 3304: filter_dropped -> voting |
| Amon-Ra St. Brown | offense | WR | 8921 | 8614 | -3.44 | 9 → 10 | high → high | dlfValuesSfTep 9076: absent -> voting; draftSharks 6167: filter_dropped -> voting; ktcCrowdSfTep 7534: filter_dropped -> voting |
| Baker Mayfield | offense | QB | 3858 | 3990 | 3.42 | 113 → 105 | medium → high | dlfSf 5203: filter_dropped -> voting; dlfValuesSfTep 4215: absent -> voting; draftSharks 5238: filter_dropped -> voting |
| Ja'Tavion Sanders | offense | TE | 2018 | 1950 | -3.37 | 323 → 336 | medium → medium | dlfValuesSfTep 1538: absent -> voting; flockFantasySf vote 2071 -> 2077; otcffbSf vote 1815 -> 1820 |

## S4: V2 + DLF IDP + DLF Rookie IDP + D4 (everything) — board C'' vs A

* top-100 membership: entered none; left none
* top-200 membership: entered ['Anthony Hill', 'Jared Verse', 'Laiatu Latu', 'Michael Mayer', 'Nick Bosa']; left ['2029 Mid 2nd', 'Braelon Allen', 'DeMarvion Overshown', 'Emmett Johnson', "Wan'Dale Robinson"]

| row | class | pos | before | after | Δ % | rank | confidence | attribution |
|---|---|---|---|---|---|---|---|---|
| LaJohntay Wester | offense | WR | 651 | 883 | 35.64 | None → None | low → low | flockFantasySf 1889: filter_dropped -> voting; otcffbSf vote 930 -> 932 |
| Jacob Rodriguez | idp | LB | 4617 | 4924 | 6.65 | 79 → 67 | low → medium | dlfIdp 4726: absent -> voting; dlfRookieIdp 5165: absent -> voting |
| Jared Verse | idp | DL | 2672 | 2835 | 6.1 | 212 → 189 | medium → low | dlfIdp 4671: absent -> voting |
| Alex Singleton | idp | LB | 1953 | 1841 | -5.73 | 336 → 381 | medium → medium | dlfIdp 1964: absent -> voting |
| Josh Sweat | idp | DL | 1664 | 1569 | -5.71 | 463 → 496 | low → low | dlfIdp 1513: absent -> voting |
| Dexter Lawrence | idp | DL | 1795 | 1896 | 5.63 | 395 → 362 | medium → low | dlfIdp 2621: absent -> voting |
| Robert Spillane | idp | LB | 2182 | 2068 | -5.22 | 289 → 312 | medium → medium | dlfIdp 1962: absent -> voting |
| Abdul Carter | idp | DL | 3679 | 3870 | 5.19 | 122 → 113 | low → low | dlfIdp 4811: absent -> voting |
| Josiah Trotter | idp | LB | 2390 | 2514 | 5.19 | 253 → 233 | low → low | dlfIdp 3171: absent -> voting; dlfRookieIdp 3283: absent -> voting |
| Theo Johnson | offense | TE | 2164 | 2054 | -5.08 | 295 → 316 | low → low | dlfValuesSfTep 1597: absent -> voting; otcffbSf vote 1733 -> 1737 |
| KaVontae Turpin | offense | WR | 1164 | 1223 | 5.07 | None → 713 | medium → low | otcffbSf vote 1062 -> 1065; pfkDynasty 2362: filter_dropped -> voting |
| Quinnen Williams | idp | DL | 1849 | 1938 | 4.81 | 376 → 340 | medium → low | dlfIdp 2557: absent -> voting |
| Quincy Williams | idp | LB | 2179 | 2078 | -4.64 | 292 → 311 | medium → medium | dlfIdp 1982: absent -> voting |
| Kam Curl | idp | DB | 1921 | 1833 | -4.58 | 345 → 384 | medium → low | dlfIdp 1513: absent -> voting |
| Roquan Smith | idp | LB | 3337 | 3184 | -4.58 | 150 → 160 | low → medium | dlfIdp 3371: absent -> voting |

## I1: increment: DLF IDP given V2 — board C vs D

* top-100 membership: entered none; left none
* top-200 membership: entered ['Anthony Hill', 'Jared Verse', 'Laiatu Latu', 'Nick Bosa']; left ['2029 Mid 2nd', 'DeMarvion Overshown', 'Emmett Johnson', 'Michael Mayer']

| row | class | pos | before | after | Δ % | rank | confidence | attribution |
|---|---|---|---|---|---|---|---|---|
| Jacob Rodriguez | idp | LB | 4617 | 4924 | 6.65 | 79 → 68 | low → medium | dlfIdp 4726: absent -> voting; dlfRookieIdp 5165: absent -> voting |
| Jared Verse | idp | DL | 2672 | 2835 | 6.1 | 212 → 189 | medium → low | dlfIdp 4671: absent -> voting |
| Alex Singleton | idp | LB | 1953 | 1841 | -5.73 | 337 → 382 | medium → medium | dlfIdp 1964: absent -> voting |
| Josh Sweat | idp | DL | 1664 | 1569 | -5.71 | 465 → 498 | low → low | dlfIdp 1513: absent -> voting |
| Dexter Lawrence | idp | DL | 1795 | 1896 | 5.63 | 398 → 361 | medium → low | dlfIdp 2621: absent -> voting |
| Robert Spillane | idp | LB | 2182 | 2068 | -5.22 | 290 → 313 | medium → medium | dlfIdp 1962: absent -> voting |
| Abdul Carter | idp | DL | 3679 | 3870 | 5.19 | 122 → 113 | low → low | dlfIdp 4811: absent -> voting |
| Josiah Trotter | idp | LB | 2390 | 2514 | 5.19 | 254 → 234 | low → low | dlfIdp 3171: absent -> voting; dlfRookieIdp 3283: absent -> voting |
| Quinnen Williams | idp | DL | 1849 | 1938 | 4.81 | 376 → 342 | medium → low | dlfIdp 2557: absent -> voting |
| Quincy Williams | idp | LB | 2179 | 2078 | -4.64 | 292 → 312 | medium → medium | dlfIdp 1982: absent -> voting |
| Kam Curl | idp | DB | 1921 | 1833 | -4.58 | 346 → 385 | medium → low | dlfIdp 1513: absent -> voting |
| Roquan Smith | idp | LB | 3337 | 3184 | -4.58 | 151 → 160 | low → medium | dlfIdp 3371: absent -> voting |
| Micah Parsons | idp | DL | 3427 | 3578 | 4.41 | 142 → 133 | low → low | dlfIdp 5096: absent -> voting |
| Anthony Hill | idp | LB | 2662 | 2779 | 4.4 | 213 → 199 | low → low | dlfIdp 3050: absent -> voting; dlfRookieIdp 3050: absent -> voting |
| Greg Rousseau | idp | DL | 2854 | 2979 | 4.38 | 188 → 175 | low → low | dlfIdp 3315: absent -> voting |

## I2: increment: D4 given V2 — board C' vs D

* top-100 membership: entered none; left none
* top-200 membership: entered ['Braelon Allen']; left ['2029 Mid 2nd']

| row | class | pos | before | after | Δ % | rank | confidence | attribution |
|---|---|---|---|---|---|---|---|---|
| Theo Johnson | offense | TE | 2165 | 2054 | -5.13 | 295 → 315 | low → low | dlfValuesSfTep 1597: absent -> voting |
| DeMario Douglas | offense | WR | 1607 | 1545 | -3.86 | 486 → 504 | low → low | dlfValuesSfTep 1413: absent -> voting |
| Ja'Tavion Sanders | offense | TE | 2019 | 1950 | -3.42 | 323 → 336 | medium → medium | dlfValuesSfTep 1538: absent -> voting |
| Xavier Hutchinson | offense | WR | 1389 | 1434 | 3.24 | 610 → 578 | low → low | dlfValuesSfTep 1550: absent -> voting |
| Darren Waller | offense | TE | 2223 | 2154 | -3.1 | 283 → 293 | medium → low | dlfValuesSfTep 1833: absent -> voting |
| Jalen Tolbert | offense | WR | 1405 | 1363 | -2.99 | 602 → 628 | medium → medium | dlfValuesSfTep 1281: absent -> voting |
| Tez Johnson | offense | WR | 1474 | 1438 | -2.44 | 548 → 574 | low → low | dlfValuesSfTep 1305: absent -> voting |
| Cole Kmet | offense | TE | 1944 | 1900 | -2.26 | 339 → 358 | medium → medium | dlfValuesSfTep 1543: absent -> voting |
| Tyrone Tracy | offense | RB | 1774 | 1734 | -2.25 | 414 → 428 | medium → medium | dlfValuesSfTep 1700: absent -> voting |
| Brandon Aiyuk | offense | WR | 1565 | 1531 | -2.17 | 500 → 511 | low → medium | dlfValuesSfTep 1442: absent -> voting |
| Jalon Daniels | offense | QB | 1864 | 1904 | 2.15 | 370 → 356 | low → low | dlfValuesSfTep 1949: absent -> voting |
| Jalen Milroe | offense | QB | 1621 | 1587 | -2.1 | 482 → 491 | medium → medium | dlfValuesSfTep 1510: absent -> voting |
| Kalif Raymond | offense | WR | 1601 | 1631 | 1.87 | 490 → 480 | medium → high | dlfValuesSfTep 1735: absent -> voting |
| Jalen Nailor | offense | WR | 1672 | 1641 | -1.85 | 460 → 473 | medium → medium | dlfValuesSfTep 1394: absent -> voting |
| Evan Engram | offense | TE | 2181 | 2141 | -1.83 | 291 → 299 | low → low | dlfValuesSfTep 1965: absent -> voting |

## I3: increment: D4 given V2 + DLF IDP — board C'' vs C

* top-100 membership: entered none; left none
* top-200 membership: entered ['Michael Mayer']; left ["Wan'Dale Robinson"]

| row | class | pos | before | after | Δ % | rank | confidence | attribution |
|---|---|---|---|---|---|---|---|---|
| Theo Johnson | offense | TE | 2165 | 2054 | -5.13 | 292 → 316 | low → low | dlfValuesSfTep 1597: absent -> voting |
| DeMario Douglas | offense | WR | 1607 | 1545 | -3.86 | 486 → 505 | low → low | dlfValuesSfTep 1413: absent -> voting |
| Ja'Tavion Sanders | offense | TE | 2019 | 1950 | -3.42 | 323 → 335 | medium → medium | dlfValuesSfTep 1538: absent -> voting |
| Xavier Hutchinson | offense | WR | 1389 | 1434 | 3.24 | 608 → 580 | low → low | dlfValuesSfTep 1550: absent -> voting |
| Darren Waller | offense | TE | 2223 | 2154 | -3.1 | 281 → 292 | medium → low | dlfValuesSfTep 1833: absent -> voting |
| Jalen Tolbert | offense | WR | 1405 | 1363 | -2.99 | 602 → 627 | medium → medium | dlfValuesSfTep 1281: absent -> voting |
| Tez Johnson | offense | WR | 1474 | 1438 | -2.44 | 551 → 576 | low → low | dlfValuesSfTep 1305: absent -> voting |
| Cole Kmet | offense | TE | 1944 | 1900 | -2.26 | 337 → 359 | medium → medium | dlfValuesSfTep 1543: absent -> voting |
| Tyrone Tracy | offense | RB | 1774 | 1734 | -2.25 | 413 → 430 | medium → medium | dlfValuesSfTep 1700: absent -> voting |
| Brandon Aiyuk | offense | WR | 1565 | 1531 | -2.17 | 500 → 512 | low → medium | dlfValuesSfTep 1442: absent -> voting |
| Jalon Daniels | offense | QB | 1864 | 1904 | 2.15 | 371 → 357 | low → low | dlfValuesSfTep 1949: absent -> voting |
| Jalen Milroe | offense | QB | 1621 | 1587 | -2.1 | 483 → 491 | medium → medium | dlfValuesSfTep 1510: absent -> voting |
| Kalif Raymond | offense | WR | 1601 | 1631 | 1.87 | 492 → 480 | medium → high | dlfValuesSfTep 1735: absent -> voting |
| Jalen Nailor | offense | WR | 1672 | 1641 | -1.85 | 461 → 472 | medium → medium | dlfValuesSfTep 1394: absent -> voting |
| Evan Engram | offense | TE | 2181 | 2141 | -1.83 | 289 → 297 | low → low | dlfValuesSfTep 1965: absent -> voting |

## I4: increment: DLF IDP given V2 + D4 — board C'' vs C'

* top-100 membership: entered none; left none
* top-200 membership: entered ['Anthony Hill', 'Jared Verse', 'Laiatu Latu', 'Nick Bosa']; left ['Braelon Allen', 'DeMarvion Overshown', 'Emmett Johnson', "Wan'Dale Robinson"]

| row | class | pos | before | after | Δ % | rank | confidence | attribution |
|---|---|---|---|---|---|---|---|---|
| Jacob Rodriguez | idp | LB | 4617 | 4924 | 6.65 | 78 → 67 | low → medium | dlfIdp 4726: absent -> voting; dlfRookieIdp 5165: absent -> voting |
| Jared Verse | idp | DL | 2672 | 2835 | 6.1 | 212 → 189 | medium → low | dlfIdp 4671: absent -> voting |
| Alex Singleton | idp | LB | 1953 | 1841 | -5.73 | 335 → 381 | medium → medium | dlfIdp 1964: absent -> voting |
| Josh Sweat | idp | DL | 1664 | 1569 | -5.71 | 462 → 496 | low → low | dlfIdp 1513: absent -> voting |
| Dexter Lawrence | idp | DL | 1795 | 1896 | 5.63 | 398 → 362 | medium → low | dlfIdp 2621: absent -> voting |
| Robert Spillane | idp | LB | 2182 | 2068 | -5.22 | 288 → 312 | medium → medium | dlfIdp 1962: absent -> voting |
| Abdul Carter | idp | DL | 3679 | 3870 | 5.19 | 122 → 113 | low → low | dlfIdp 4811: absent -> voting |
| Josiah Trotter | idp | LB | 2390 | 2514 | 5.19 | 253 → 233 | low → low | dlfIdp 3171: absent -> voting; dlfRookieIdp 3283: absent -> voting |
| Quinnen Williams | idp | DL | 1849 | 1938 | 4.81 | 375 → 340 | medium → low | dlfIdp 2557: absent -> voting |
| Quincy Williams | idp | LB | 2179 | 2078 | -4.64 | 289 → 311 | medium → medium | dlfIdp 1982: absent -> voting |
| Kam Curl | idp | DB | 1921 | 1833 | -4.58 | 345 → 384 | medium → low | dlfIdp 1513: absent -> voting |
| Roquan Smith | idp | LB | 3337 | 3184 | -4.58 | 149 → 160 | low → medium | dlfIdp 3371: absent -> voting |
| Micah Parsons | idp | DL | 3427 | 3578 | 4.41 | 142 → 133 | low → low | dlfIdp 5096: absent -> voting |
| Anthony Hill | idp | LB | 2662 | 2779 | 4.4 | 213 → 200 | low → low | dlfIdp 3050: absent -> voting; dlfRookieIdp 3050: absent -> voting |
| Greg Rousseau | idp | DL | 2854 | 2979 | 4.38 | 187 → 175 | low → low | dlfIdp 3315: absent -> voting |

