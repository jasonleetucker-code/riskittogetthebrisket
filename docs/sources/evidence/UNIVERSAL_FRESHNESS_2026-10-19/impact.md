Input `exports/latest/dynasty_data_2026-10-19.json` (sha256 `b639608f68176b9a`), board as of `2026-10-19T05:23:48.885300+00:00`. Before = v1 cadence curve (flag off, byte-identical to main); after = owner step schedule (flag on).

| class | rows priced before | rows changed | median | p90 | p99 | max |
|---|---|---|---|---|---|---|
| offense | 402 | 391 | 0.79% | 3.27% | 19.21% | 42.86% |
| rookie | 86 | 69 | 0.8% | 2.5% | 5.63% | 9.24% |
| idp | 397 | 321 | 1.28% | 4.33% | 8.8% | 11.95% |
| pick | 144 | 137 | 0.39% | 1.33% | 5.38% | 5.65% |
| **all** | 1029 | 918 | 0.91% | 3.6% | 12.71% | 42.86% |

Newly unpriced: Dee Alford, James Pierre, Kyle Dugger. Newly priced: Chris Moore.

| | entered | left | rank moved | max rank move | median value change | max value change |
|---|---|---|---|---|---|---|
| top50 | 1 | 1 | 23 | 4 | 0.54% | 3.25% |
| top200 | 1 | 1 | 151 | 19 | 0.54% | 7.02% |

| largest movers | before | after | change | what moved it |
|---|---|---|---|---|
| LaJohntay Wester | 651 | 930 | +42.9% | now voting: fantasyNavigatorSf, flockFantasySf; outlier filter no longer drops: flockFantasySf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Travis Homer | 474 | 633 | +33.5% | now voting: fantasyNavigatorSf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Tyrell Shavers | 820 | 1024 | +24.9% | now voting: fantasyNavigatorSf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Jawhar Jordan | 727 | 905 | +24.5% | now voting: fantasyNavigatorSf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Antonio Gibson | 786 | 937 | +19.2% | now voting: fantasyNavigatorSf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Zamir White | 631 | 740 | +17.3% | now voting: fantasyNavigatorSf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Johnny Wilson | 620 | 716 | +15.5% | now voting: fantasyNavigatorSf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Derius Davis | 718 | 825 | +14.9% | now voting: fantasyNavigatorSf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Devin Duvernay | 482 | 548 | +13.7% | now voting: fantasyNavigatorSf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Adam Trautman | 1188 | 1339 | +12.7% | now voting: fantasyNavigatorSf; weights: idpTradeCalc 0.8661->0.75, ktcCrowdSfTep 1.0->0.5714 |
| Austin Hooper | 1351 | 1520 | +12.5% | now voting: fantasyNavigatorSf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Christian Harris | 870 | 766 | -11.9% | no longer voting: fantasyProsIdp; weights: idpTradeCalc 0.8135->0.75 |
| Odell Beckham | 1201 | 1340 | +11.6% | now voting: fantasyNavigatorSf |
| Devin White | 863 | 764 | -11.5% | no longer voting: fantasyProsIdp; weights: idpTradeCalc 0.8135->0.75 |
| Josh Oliver | 1326 | 1463 | +10.3% | now voting: fantasyNavigatorSf; weights: ktcCrowdSfTep 1.0->0.5714 |
| DeMarcus Lawrence | 1352 | 1221 | -9.7% | no longer voting: fantasyProsIdp; weights: idpTradeCalc 0.8135->0.75 |
| Josh Cameron | 1601 | 1453 | -9.2% | now voting: fantasyNavigatorSf; no longer voting: draftSharks; outlier filter now drops: draftSharks; weights: dlfRookieSf 0.9834->1.0, idpTradeCalc 0.8661->0.75, ktcCrowdSfTep 1.0->0.5714 |
| Jason Pinnock | 830 | 757 | -8.8% | no longer voting: fantasyProsIdp; weights: idpTradeCalc 0.8135->0.75 |
| Alex Singleton | 1953 | 1801 | -7.8% | no longer voting: fantasyProsIdp; weights: idpTradeCalc 0.8135->0.75 |
| Tyrel Dodson | 1457 | 1346 | -7.6% | no longer voting: fantasyProsIdp; weights: idpTradeCalc 0.8135->0.75 |
| CJ Allen | 3918 | 4193 | +7.0% | no longer voting: fantasyProsIdp; weights: idpTradeCalc 0.8135->0.75 |
| Tyree Wilson | 855 | 795 | -7.0% | no longer voting: fantasyProsIdp; weights: idpTradeCalc 0.8135->0.75 |
| Jacob Rodriguez | 4617 | 4929 | +6.8% | no longer voting: fantasyProsIdp; weights: idpTradeCalc 0.8135->0.75 |
| Roquan Smith | 3337 | 3117 | -6.6% | no longer voting: fantasyProsIdp; weights: idpTradeCalc 0.8135->0.75 |
| Nick Chubb | 1466 | 1371 | -6.5% | now voting: fantasyNavigatorSf |

Voting sources per priced player: mean 6.309 -> 6.511. Single-source rows: 58 -> 58.

| source | rows voted (before -> after) | effective weight | mean applied weight | outlier drops |
|---|---|---|---|---|
| `ktcCrowdSfTep` | 505 -> 503 | 1.0 -> 1.0 | 1.0 -> 0.6319 | 5 -> 7 |
| `ktcTradesSfTep` | 509 -> 509 | 1.0 -> 1.0 | 1.0 -> 1.0 | 1 -> 1 |
| `idpTradeCalc` | 905 -> 902 | 0.8661 -> 0.75 | 0.8442 -> 0.75 | 2 -> 5 |
| `dlfSf` | 277 -> 278 | 1.0 -> 1.0 | 0.9302 -> 0.9299 | 10 -> 9 |
| `dlfRookieSf` | 57 -> 57 | 0.9834 -> 1.0 | 0.6498 -> 0.6579 | 0 -> 0 |
| `dlfIdp` | 0 -> 0 | 0.0 -> 0.0 | None -> None | 0 -> 0 |
| `dlfRookieIdp` | 0 -> 0 | 0.0 -> 0.0 | None -> None | 0 -> 0 |
| `idpShowCombined` | 0 -> 0 | 0.0 -> 0.0 | None -> None | 0 -> 0 |
| `dynastyNerdsSfTep` | 280 -> 282 | 1.0 -> 1.0 | 1.0 -> 1.0 | 4 -> 2 |
| `fantasyCalc` | 389 -> 389 | 1.0 -> 1.0 | 1.0 -> 1.0 | 1 -> 1 |
| `signalsSf` | 0 -> 0 | 0.0 -> 0.0 | None -> None | 0 -> 0 |
| `signalsIdpDl` | 0 -> 0 | 0.0 -> 0.0 | None -> None | 0 -> 0 |
| `signalsIdpLb` | 0 -> 0 | 0.0 -> 0.0 | None -> None | 0 -> 0 |
| `signalsIdpDb` | 0 -> 0 | 0.0 -> 0.0 | None -> None | 0 -> 0 |
| `otcffbSf` | 443 -> 444 | 1.0 -> 1.0 | 1.0 -> 1.0 | 1 -> 0 |
| `fantasyNavigatorSf` | 0 -> 445 | 0.0 -> 0.75 | None -> 0.438 | 0 -> 2 |
| `pfkDynasty` | 448 -> 449 | 1.0 -> 1.0 | 1.0 -> 1.0 | 2 -> 1 |
| `dynastyDaddySf` | 388 -> 388 | 1.0 -> 1.0 | 1.0 -> 1.0 | 0 -> 0 |
| `fantasyProsSf` | 406 -> 406 | 1.0 -> 1.0 | 0.6453 -> 0.7636 | 2 -> 2 |
| `fantasyProsIdp` | 249 -> 0 | 0.5675 -> 0.0 | 0.5675 -> None | 0 -> 0 |
| `fantasyProsFitzmaurice` | 291 -> 291 | 1.0 -> 0.5 | 0.5052 -> 0.335 | 8 -> 8 |
| `flockFantasySf` | 401 -> 402 | 1.0 -> 1.0 | 1.0 -> 1.0 | 3 -> 2 |
| `flockFantasySfRookies` | 0 -> 0 | 0.0 -> 0.0 | None -> None | 0 -> 0 |
| `yahooBoone` | 344 -> 342 | 1.0 -> 1.0 | 1.0 -> 1.0 | 7 -> 9 |
| `draftSharks` | 316 -> 316 | 1.0 -> 1.0 | 1.0 -> 1.0 | 52 -> 52 |
| `draftSharksIdp` | 320 -> 320 | 1.0 -> 1.0 | 1.0 -> 1.0 | 0 -> 0 |

| family | total applied weight before | after |
|---|---|---|
| dlf | 294.7 | 296.0 |
| draftSharks | 636.0 | 636.0 |
| dynastyDaddySf | 388.0 | 388.0 |
| dynastyNerdsSfTep | 280.0 | 282.0 |
| fantasyCalc | 389.0 | 389.0 |
| fantasyPros | 550.31 | 407.5 |
| flockFantasy | 401.0 | 402.0 |
| idpTradeCalc | 763.99 | 676.5 |
| ktcCrowd | 505.0 | 512.75 |
| ktcTrades | 509.0 | 509.0 |
| otcffbSf | 443.0 | 444.0 |
| pfkDynasty | 448.0 | 449.0 |
| yahooBoone | 344.0 | 342.0 |

Confidence bucket transitions: high->medium 5, low->medium 10, low->none 3, medium->high 8, medium->low 125, none->low 1.
Two-way player Travis Hunter: 3738 -> 3801; weight changes fantasyNavigatorSf 0.0->0.4286, fantasyProsFitzmaurice 0.5->0.3333, fantasyProsSf 0.5->0.6667, ktcCrowdSfTep 1.0->0.5714.

Verification (6723 votes): off-schedule factors 0; votes older than 30 days 0; fresh healthy votes below base x family cap 0; voting sources older than 30 days none. **PASS**.
