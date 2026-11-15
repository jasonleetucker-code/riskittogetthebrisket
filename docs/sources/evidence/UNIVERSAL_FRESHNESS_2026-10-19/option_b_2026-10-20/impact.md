Input `exports/latest/dynasty_data_2026-10-20.json` (sha256 `67f6d56ee023a9b0`), board as of `2026-10-20T12:16:19.868171+00:00`. Before = v1 cadence curve (flag off, byte-identical to main); after = owner step schedule (flag on).

| class | rows priced before | rows changed | median | p90 | p99 | max |
|---|---|---|---|---|---|---|
| offense | 400 | 388 | 0.69% | 3.19% | 15.96% | 40.43% |
| rookie | 86 | 68 | 0.76% | 2.52% | 5.93% | 10.23% |
| idp | 397 | 321 | 1.07% | 4.04% | 9.0% | 11.95% |
| pick | 120 | 113 | 0.22% | 1.7% | 4.83% | 5.21% |
| **all** | 1003 | 890 | 0.71% | 3.45% | 11.26% | 40.43% |

Newly unpriced: Dee Alford, James Pierre, Kyle Dugger. Newly priced: Chris Moore, Jawhar Jordan.

| | entered | left | rank moved | max rank move | median value change | max value change |
|---|---|---|---|---|---|---|
| top50 | 2 | 2 | 21 | 5 | 0.45% | 3.72% |
| top200 | 3 | 3 | 146 | 16 | 0.52% | 7.55% |

| largest movers | before | after | change | what moved it |
|---|---|---|---|---|
| LaJohntay Wester | 648 | 910 | +40.4% | now voting: fantasyNavigatorSf, flockFantasySf; outlier filter no longer drops: flockFantasySf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Sincere McCormick | 553 | 673 | +21.7% | now voting: fantasyNavigatorSf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Josh Reynolds | 625 | 743 | +18.9% | now voting: fantasyNavigatorSf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Curtis Samuel | 791 | 920 | +16.3% | now voting: fantasyNavigatorSf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Johnny Wilson | 727 | 843 | +16.0% | now voting: fantasyNavigatorSf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Zamir White | 735 | 850 | +15.7% | now voting: fantasyNavigatorSf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Jarrett Stidham | 836 | 962 | +15.1% | now voting: fantasyNavigatorSf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Christian Harris | 870 | 766 | -11.9% | no longer voting: fantasyProsIdp; weights: idpTradeCalc 0.7234->0.75 |
| Devin White | 863 | 764 | -11.5% | no longer voting: fantasyProsIdp; weights: idpTradeCalc 0.7234->0.75 |
| Adam Trautman | 1208 | 1344 | +11.3% | now voting: fantasyNavigatorSf; weights: idpTradeCalc 0.7771->0.75, ktcCrowdSfTep 1.0->0.5714 |
| DeMarcus Lawrence | 1365 | 1221 | -10.6% | no longer voting: fantasyProsIdp; weights: idpTradeCalc 0.7234->0.75 |
| Josh Cameron | 1633 | 1466 | -10.2% | now voting: fantasyNavigatorSf; no longer voting: draftSharks; outlier filter now drops: draftSharks; weights: idpTradeCalc 0.7771->0.75, ktcCrowdSfTep 1.0->0.5714 |
| Isaiah Hodgins | 898 | 985 | +9.7% | now voting: fantasyNavigatorSf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Jake Bobo | 944 | 1031 | +9.2% | now voting: fantasyNavigatorSf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Tyrell Shavers | 870 | 950 | +9.2% | now voting: fantasyNavigatorSf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Nick Chubb | 1550 | 1410 | -9.0% | now voting: fantasyNavigatorSf |
| Tyrel Dodson | 1478 | 1345 | -9.0% | no longer voting: fantasyProsIdp; weights: idpTradeCalc 0.7234->0.75 |
| Jason Pinnock | 830 | 757 | -8.8% | no longer voting: fantasyProsIdp; weights: idpTradeCalc 0.7234->0.75 |
| Derius Davis | 804 | 872 | +8.5% | now voting: fantasyNavigatorSf; weights: ktcCrowdSfTep 1.0->0.5714 |
| Jacob Rodriguez | 4583 | 4929 | +7.5% | no longer voting: fantasyProsIdp; weights: idpTradeCalc 0.7234->0.75 |
| Alex Singleton | 1946 | 1800 | -7.5% | no longer voting: fantasyProsIdp; weights: idpTradeCalc 0.7234->0.75 |
| Tyree Wilson | 855 | 795 | -7.0% | no longer voting: fantasyProsIdp; weights: idpTradeCalc 0.7234->0.75 |
| Josh Sweat | 1680 | 1570 | -6.5% | no longer voting: fantasyProsIdp; weights: idpTradeCalc 0.7234->0.75 |
| Jaylin Lane | 1581 | 1478 | -6.5% | now voting: fantasyNavigatorSf; weights: idpTradeCalc 0.7771->0.75, ktcCrowdSfTep 1.0->0.5714 |
| Dallas Turner | 3726 | 3949 | +6.0% | no longer voting: fantasyProsIdp; weights: idpTradeCalc 0.7234->0.75 |

Voting sources per priced player: mean 6.437 -> 6.645. Single-source rows: 58 -> 58.

| source | rows voted (before -> after) | effective weight | mean applied weight | outlier drops |
|---|---|---|---|---|
| `ktcCrowdSfTep` | 493 -> 491 | 1.0 -> 1.0 | 1.0 -> 0.6238 | 5 -> 7 |
| `ktcTradesSfTep` | 497 -> 497 | 1.0 -> 1.0 | 1.0 -> 1.0 | 1 -> 1 |
| `idpTradeCalc` | 893 -> 891 | 0.7771 -> 0.75 | 0.7544 -> 0.75 | 1 -> 3 |
| `dlfSf` | 278 -> 279 | 1.0 -> 1.0 | 0.9299 -> 0.9301 | 7 -> 6 |
| `dlfRookieSf` | 58 -> 58 | 1.0 -> 1.0 | 0.6638 -> 0.6638 | 0 -> 0 |
| `dlfValuesSfTep` | 0 -> 0 | 0.0 -> 0.0 | None -> None | 0 -> 0 |
| `dlfIdp` | 0 -> 0 | 0.0 -> 0.0 | None -> None | 0 -> 0 |
| `dlfRookieIdp` | 0 -> 0 | 0.0 -> 0.0 | None -> None | 0 -> 0 |
| `idpShowCombined` | 0 -> 0 | 0.0 -> 0.0 | None -> None | 0 -> 0 |
| `dynastyNerdsSfTep` | 279 -> 280 | 1.0 -> 1.0 | 1.0 -> 1.0 | 5 -> 4 |
| `fantasyCalc` | 388 -> 388 | 1.0 -> 1.0 | 1.0 -> 1.0 | 1 -> 1 |
| `signalsSf` | 0 -> 0 | 0.0 -> 0.0 | None -> None | 0 -> 0 |
| `signalsIdpDl` | 0 -> 0 | 0.0 -> 0.0 | None -> None | 0 -> 0 |
| `signalsIdpLb` | 0 -> 0 | 0.0 -> 0.0 | None -> None | 0 -> 0 |
| `signalsIdpDb` | 0 -> 0 | 0.0 -> 0.0 | None -> None | 0 -> 0 |
| `otcffbSf` | 455 -> 457 | 1.0 -> 1.0 | 1.0 -> 1.0 | 3 -> 1 |
| `fantasyNavigatorSf` | 0 -> 444 | 0.0 -> 0.75 | None -> 0.438 | 0 -> 3 |
| `pfkDynasty` | 447 -> 448 | 1.0 -> 1.0 | 1.0 -> 1.0 | 2 -> 1 |
| `dynastyDaddySf` | 382 -> 382 | 1.0 -> 1.0 | 1.0 -> 1.0 | 0 -> 0 |
| `fantasyProsSf` | 405 -> 405 | 1.0 -> 1.0 | 0.642 -> 0.7613 | 2 -> 2 |
| `fantasyProsIdp` | 249 -> 0 | 0.1617 -> 0.0 | 0.1617 -> None | 0 -> 0 |
| `fantasyProsFitzmaurice` | 293 -> 293 | 1.0 -> 0.5 | 0.5051 -> 0.335 | 6 -> 6 |
| `flockFantasySf` | 398 -> 399 | 1.0 -> 1.0 | 1.0 -> 1.0 | 5 -> 4 |
| `flockFantasySfRookies` | 0 -> 0 | 0.0 -> 0.0 | None -> None | 0 -> 0 |
| `yahooBoone` | 345 -> 345 | 1.0 -> 1.0 | 1.0 -> 1.0 | 5 -> 5 |
| `draftSharks` | 312 -> 317 | 1.0 -> 1.0 | 1.0 -> 1.0 | 56 -> 51 |
| `draftSharksIdp` | 320 -> 320 | 1.0 -> 1.0 | 1.0 -> 1.0 | 0 -> 0 |

| family | total applied weight before | after |
|---|---|---|
| dlf | 297.0 | 298.0 |
| draftSharks | 632.0 | 637.0 |
| dynastyDaddySf | 382.0 | 382.0 |
| dynastyNerdsSfTep | 279.0 | 280.0 |
| fantasyCalc | 388.0 | 388.0 |
| fantasyPros | 448.26 | 406.5 |
| flockFantasy | 398.0 | 399.0 |
| idpTradeCalc | 673.71 | 668.25 |
| ktcCrowd | 493.0 | 500.75 |
| ktcTrades | 497.0 | 497.0 |
| otcffbSf | 455.0 | 457.0 |
| pfkDynasty | 447.0 | 448.0 |
| yahooBoone | 345.0 | 345.0 |

Confidence bucket transitions: high->medium 8, low->medium 10, low->none 3, medium->high 7, medium->low 122, none->low 2.
Two-way player Travis Hunter: 3599 -> 3599; weight changes fantasyNavigatorSf 0.0->0.4286, fantasyProsFitzmaurice 0.5->0.3333, fantasyProsSf 0.5->0.6667, ktcCrowdSfTep 1.0->0.5714.

Verification (6694 votes): off-schedule factors 0; votes older than 30 days 0; fresh healthy votes below base x family cap 0; voting sources older than 30 days none. **PASS**.
