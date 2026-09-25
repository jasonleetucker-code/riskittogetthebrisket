# Source inventory receipt — 2026-09-25

**Evidence only. Nothing here changes a vote.** This is the output of the canonical inventory tool
(`scripts/source_inventory.py`), which reads the live registries and a built contract rather than
prose. It closes the "source inventory not executed" gap named by the 2026-09-25 research
reconciliation.

| field | value |
|---|---|
| main SHA | `5316fbbef` |
| generatedAt | 2026-09-25T14:41:14Z |
| command | `python scripts/source_inventory.py --json … --markdown …` |
| exit | 0 |
| sources | 30 in total: **22 model inputs (registered voters), 7 non-voting, 1 benchmark (KTC Market)** |

`voted/obs` is rows that voted over rows observed (matched) per position group on the built
board. These counts are **not** unique-player totals and must not be summed across sources. The
tool describes the **dynasty valuation** portfolio only. Seasonal and Game Day weekly projection
sources are recorded separately, in `config/projections/source_capability_census.json`.

| source | provider | role | family | scope | signal | translation | base | QB voted/obs | RB voted/obs | WR voted/obs | TE voted/obs | DL voted/obs | LB voted/obs | DB voted/obs | ROOKIE voted/obs | PICK voted/obs | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `dlfIdp` | Dynasty League Football IDP | model_input | dlf | overall_idp | rank | shared_market_idp | 1.0 | — | — | — | — | 78/78 | 55/55 | 32/33 | 16/16 | — | registered dynasty voter |
| `dlfRookieIdp` | Dynasty League Football Rookie IDP | model_input | dlf | overall_idp | rank | rookie_ladder | 1.0 | — | — | — | — | 14/14 | 11/11 | 5/5 | 30/30 | — | registered dynasty voter |
| `dlfRookieSf` | Dynasty League Football Rookie SF | model_input | dlf | overall_offense | rank | rookie_ladder | 1.0 | 7/7 | 12/12 | 28/28 | 9/9 | — | — | — | 56/56 | — | registered dynasty voter |
| `dlfSf` | Dynasty League Football Superflex | model_input | dlf | overall_offense | rank | direct | 1.0 | 50/50 | 81/83 | 112/114 | 42/42 | — | — | — | 41/42 | — | registered dynasty voter |
| `dlfValuesSfTep` | — | non_voting | — | — | — | — | — | — | — | — | — | — | — | — | — | — | DLF Trade Analyzer Values (native offense value) — acquired, measurement gate pending before it may vote (owner directive 2026-09-24) |
| `dlfValuesSfTepPicks` | — | non_voting | — | — | — | — | — | — | — | — | — | — | — | — | — | — | DLF Trade Analyzer pick values — kept for the pick audit, never a model input |
| `draftSharks` | Draft Sharks Dynasty | model_input | draftSharks | overall_offense | rank | direct | 1.0 | 36/47 | 94/98 | 152/167 | 60/75 | — | — | — | 73/82 | — | registered dynasty voter |
| `draftSharksIdp` | Draft Sharks IDP Dynasty | model_input | draftSharks | overall_idp | rank | direct | 1.0 | — | — | — | — | 121/128 | 64/77 | 111/113 | 49/51 | — | registered dynasty voter |
| `draftSharksRosIdp` | — | non_voting | — | — | — | — | — | — | — | — | — | — | — | — | — | — | rest-of-season (redraft) board — seasonal lane only; barred from dynasty values |
| `draftSharksRosSf` | — | non_voting | — | — | — | — | — | — | — | — | — | — | — | — | — | — | rest-of-season (redraft) board — seasonal lane only; barred from dynasty values |
| `dynastyDaddySf` | Dynasty Daddy Superflex | model_input | dynastyDaddySf | overall_offense | rank | direct | 1.0 | 70/70 | 99/100 | 140/140 | 58/60 | — | — | — | 61/62 | — | registered dynasty voter |
| `dynastyNerdsSfTep` | Dynasty Nerds SF-TEP | model_input | dynastyNerdsSfTep | overall_offense | rank | direct | 1.0 | 45/45 | 83/85 | 115/116 | 47/48 | — | — | — | 48/48 | — | registered dynasty voter |
| `fantasyCalc` | FantasyCalc Dynasty SF | model_input | fantasyCalc | overall_offense | rank | direct | 1.0 | 70/70 | 101/104 | 153/153 | 63/63 | — | — | — | 66/66 | — | registered dynasty voter |
| `fantasyNavigatorSf` | Fantasy Navigator SF | model_input | ktcCrowd | overall_offense | rank | direct | 1.0 | 72/72 | 121/123 | 183/185 | 74/75 | — | — | — | 64/64 | — | registered dynasty voter |
| `fantasyProsFitzmaurice` | FantasyPros / Pat Fitzmaurice SF-TEP | model_input | fantasyPros | overall_offense | rank | direct | 1.0 | 48/50 | 86/86 | 115/115 | 46/46 | — | — | — | 49/49 | — | registered dynasty voter |
| `fantasyProsIdp` | FantasyPros Dynasty IDP | model_input | fantasyPros | overall_idp | rank | shared_market_idp | 1.0 | — | — | — | — | 91/92 | 64/71 | 85/88 | 6/12 | — | registered dynasty voter |
| `fantasyProsSf` | FantasyPros Dynasty Superflex | model_input | fantasyPros | overall_offense | rank | direct | 1.0 | 36/39 | 101/101 | 128/129 | 41/43 | — | — | — | 43/43 | — | registered dynasty voter |
| `flockFantasySf` | Flock Fantasy Superflex | model_input | flockFantasy | overall_offense | rank | direct | 1.0 | 62/63 | 115/115 | 161/164 | 65/66 | — | — | — | 66/67 | — | registered dynasty voter |
| `flockFantasySfRookies` | Flock Fantasy Rookie SF | model_input | flockFantasy | overall_offense | rank | rookie_ladder | 1.0 | 7/7 | 12/12 | 20/20 | 8/8 | — | — | — | 47/47 | — | registered dynasty voter |
| `idpShow` | — | non_voting | — | — | — | — | — | — | — | — | — | — | — | — | — | — | IDP-only cut of idpShowCombined (same vendor board) — voting would double-count IDP Show |
| `idpShowCombined` | The IDP Show — Combined (Adamidp) | model_input | idpShow | overall_idp | rank | direct | 1.0 | 62/63 | 97/99 | 133/134 | 60/61 | 101/103 | 94/95 | 103/103 | 100/100 | — | registered dynasty voter |
| `idpTradeCalc` | IDP Trade Calculator | model_input | idpTradeCalc | overall_idp | value | direct | 1.0 | 66/67 | 118/118 | 176/177 | 73/73 | 143/146 | 107/108 | 122/122 | 119/121 | 84/84 | registered dynasty voter |
| `ktc` | — | non_voting | ktcCrowd | — | — | — | — | — | — | — | — | — | — | — | — | — | KTC Crowd at base (non-TEP) calibration — same crowd opinion, a calibration state not a vote |
| `ktcCrowdSfTep` | KeepTradeCut Crowd SF-TE++ | model_input | ktcCrowd | overall_offense | value | direct | 1.0 | 68/72 | 124/124 | 184/188 | 78/78 | — | — | — | 68/68 | 36/36 | registered dynasty voter |
| `ktcCrowdTradesSfTep` | — | benchmark | — | — | — | — | — | — | — | — | — | — | — | — | — | — | KTC Market — benchmark only (src/sources/ktc_market.py); never a vote |
| `ktcSfTep` | — | non_voting | ktcCrowd | — | — | — | — | — | — | — | — | — | — | — | — | — | mirror of KTC Crowd (TE++ board, identical values) — voting would double-count KTC Crowd |
| `ktcTradesSfTep` | KeepTradeCut Trades SF-TE++ | model_input | ktcTrades | overall_offense | value | direct | 1.0 | 72/72 | 122/124 | 187/188 | 77/78 | — | — | — | 68/68 | 36/36 | registered dynasty voter |
| `otcffbSf` | OTC Fantasy Football SF | model_input | otcffbSf | overall_offense | rank | direct | 1.0 | 65/65 | 100/102 | 140/140 | 60/60 | — | — | — | 61/62 | — | registered dynasty voter |
| `pfkDynasty` | Play for Keeps Dynasty | model_input | pfkDynasty | overall_offense | rank | direct | 1.0 | 68/69 | 123/124 | 182/186 | 79/79 | — | — | — | 63/64 | — | registered dynasty voter |
| `yahooBoone` | Yahoo / Justin Boone SF-TEP | model_input | yahooBoone | overall_offense | rank | direct | 1.0 | 66/71 | 96/96 | 147/148 | 70/73 | — | — | — | 68/68 | — | registered dynasty voter |
