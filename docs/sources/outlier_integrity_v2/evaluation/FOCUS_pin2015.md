# Focus rows, pin2015: full per-player source tables

Cell = the source's priced vote on that board and its state: ✓ voting; **DROPPED** = removed by the incumbent per-row filter; stale(w=0) = freshness/health zero weight (never a vote); `v2_refused:<reason>` = refused by V2 Layer A before pricing; a bracketed reason is V2's stamp on a vote that still votes (`kept_dissent` = Layer C assessed it as legitimate disagreement and kept it; `voting_name_only_identity` = Layer A could confirm the name only and let it vote). — = no observation. Boards: A production; B DLF IDP restored + incumbent; C DLF IDP restored + V2; D V2 with DLF held; B′/C′ D4 on (incumbent / V2); B″/C″ DLF IDP restored + D4 on (incumbent / V2); Anf/Bnf no per-row filter.

#### Trevin Wallace (LB, NYJ, idp)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 1937 | 342 | low | medium/high/medium/high/low | 3 | - |
| B | 884 | None | low | medium/medium/medium/high/low | 3 | draftSharksIdp |
| C | 1934 | 343 | low | medium/high/medium/high/low | 4 | - |
| D | 1937 | 342 | low | medium/high/medium/high/low | 3 | - |
| B' | 1937 | 342 | low | medium/high/medium/high/low | 3 | - |
| C' | 1937 | 342 | low | medium/high/medium/high/low | 3 | - |
| B'' | 884 | None | low | medium/medium/medium/high/low | 3 | draftSharksIdp |
| C'' | 1934 | 343 | low | medium/high/medium/high/low | 4 | - |
| Anf | 1937 | 342 | low | medium/high/medium/high/low | 3 | - |
| Bnf | 1934 | 343 | low | medium/high/medium/high/low | 4 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfIdp | dlf | exact | 164→601 | 1.0 | — | 1517 ✓ | 1517 ✓ [voting_name_only_identity] | — | — | — | 1517 ✓ | 1517 ✓ [voting_name_only_identity] | — | 1517 ✓ |
| draftSharksIdp | draftSharks | ds_combined_cross_market | 33→196 | 1.0 | 2878 ✓ | 2878 **DROPPED** | 2878 ✓ [voting_name_only_identity] | 2878 ✓ [voting_name_only_identity] | 2878 ✓ | 2878 ✓ [voting_name_only_identity] | 2878 **DROPPED** | 2878 ✓ [voting_name_only_identity] | 2878 ✓ | 2878 ✓ |
| fantasyProsIdp | fantasyPros | exact | 153→576 | 0.1686 | 1558 ✓ | 1558 ✓ | 1558 ✓ | 1558 ✓ | 1558 ✓ | 1558 ✓ | 1558 ✓ | 1558 ✓ | 1558 ✓ | 1558 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 435→436 | 0.0 | 1842 stale(w=0) | 1842 stale(w=0) | 1842 stale(w=0) | 1842 stale(w=0) | 1842 stale(w=0) | 1842 stale(w=0) | 1842 stale(w=0) | 1842 stale(w=0) | 1842 stale(w=0) | 1842 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 809→809 | 0.7701 | 814 ✓ | 814 ✓ | 814 ✓ | 814 ✓ | 814 ✓ | 814 ✓ | 814 ✓ | 814 ✓ | 814 ✓ | 814 ✓ |

Why V2 keeps the votes the incumbent removed in B: draftSharksIdp 2878: incumbent drop in B; in C status=voting, identity=NAME_ONLY, V2 reason=voting_name_only_identity

#### Myles Garrett (DL, LAR, idp)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 3555 | 133 | low | medium/high/medium/high/low | 3 | - |
| B | 5245 | 61 | medium | medium/medium/medium/high/medium | 3 | draftSharksIdp |
| C | 3469 | 137 | low | medium/high/medium/high/low | 4 | - |
| D | 3555 | 133 | low | medium/high/medium/high/low | 3 | - |
| B' | 3555 | 133 | low | medium/high/medium/high/low | 3 | - |
| C' | 3555 | 133 | low | medium/high/medium/high/low | 3 | - |
| B'' | 5245 | 61 | medium | medium/medium/medium/high/medium | 3 | draftSharksIdp |
| C'' | 3469 | 137 | low | medium/high/medium/high/low | 4 | - |
| Anf | 3555 | 133 | low | medium/high/medium/high/low | 3 | - |
| Bnf | 3469 | 137 | low | medium/high/medium/high/low | 4 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfIdp | dlf | exact | 11→116 | 1.0 | — | 3721 ✓ | 3721 ✓ [voting_name_only_identity] | — | — | — | 3721 ✓ | 3721 ✓ [voting_name_only_identity] | — | 3721 ✓ |
| draftSharksIdp | draftSharks | ds_combined_cross_market | 92→412 | 1.0 | 1905 ✓ | 1905 **DROPPED** | 1905 ✓ [kept_dissent] | 1905 ✓ [kept_dissent] | 1905 ✓ | 1905 ✓ [kept_dissent] | 1905 **DROPPED** | 1905 ✓ [kept_dissent] | 1905 ✓ | 1905 ✓ |
| fantasyProsIdp | fantasyPros | exact | 8→66 | 0.1686 | 4726 ✓ | 4726 ✓ | 4726 ✓ | 4726 ✓ | 4726 ✓ | 4726 ✓ | 4726 ✓ | 4726 ✓ | 4726 ✓ | 4726 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 89→89 | 0.0 | 4184 stale(w=0) | 4184 stale(w=0) | 4184 stale(w=0) | 4184 stale(w=0) | 4184 stale(w=0) | 4184 stale(w=0) | 4184 stale(w=0) | 4184 stale(w=0) | 4184 stale(w=0) | 4184 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 68→68 | 0.7701 | 5399 ✓ | 5399 ✓ | 5399 ✓ | 5399 ✓ | 5399 ✓ | 5399 ✓ | 5399 ✓ | 5399 ✓ | 5399 ✓ | 5399 ✓ |

Why V2 keeps the votes the incumbent removed in B: draftSharksIdp 1905: incumbent drop in B; in C status=voting, identity=NAME_ONLY, V2 reason=kept_dissent

#### Aidan Hutchinson (DL, DET, idp)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 4772 | 72 | low | medium/high/medium/high/low | 3 | - |
| B | 6422 | 34 | medium | medium/medium/medium/high/high | 3 | draftSharksIdp |
| C | 4772 | 73 | low | medium/high/medium/high/low | 4 | - |
| D | 4772 | 72 | low | medium/high/medium/high/low | 3 | - |
| B' | 4772 | 71 | low | medium/high/medium/high/low | 3 | - |
| C' | 4772 | 72 | low | medium/high/medium/high/low | 3 | - |
| B'' | 6422 | 34 | medium | medium/medium/medium/high/high | 3 | draftSharksIdp |
| C'' | 4772 | 73 | low | medium/high/medium/high/low | 4 | - |
| Anf | 4772 | 72 | low | medium/high/medium/high/low | 3 | - |
| Bnf | 4772 | 73 | low | medium/high/medium/high/low | 4 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfIdp | dlf | exact | 1→29 | 1.0 | — | 6227 ✓ | 6227 ✓ [voting_name_only_identity] | — | — | — | 6227 ✓ | 6227 ✓ [voting_name_only_identity] | — | 6227 ✓ |
| draftSharksIdp | draftSharks | ds_combined_cross_market | 31→159 | 1.0 | 3200 ✓ | 3200 **DROPPED** | 3200 ✓ [kept_dissent] | 3200 ✓ [kept_dissent] | 3200 ✓ | 3200 ✓ [kept_dissent] | 3200 **DROPPED** | 3200 ✓ [kept_dissent] | 3200 ✓ | 3200 ✓ |
| fantasyProsIdp | fantasyPros | exact | 1→29 | 0.1686 | 6227 ✓ | 6227 ✓ | 6227 ✓ | 6227 ✓ | 6227 ✓ | 6227 ✓ | 6227 ✓ | 6227 ✓ | 6227 ✓ | 6227 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 71→71 | 0.0 | 4592 stale(w=0) | 4592 stale(w=0) | 4592 stale(w=0) | 4592 stale(w=0) | 4592 stale(w=0) | 4592 stale(w=0) | 4592 stale(w=0) | 4592 stale(w=0) | 4592 stale(w=0) | 4592 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 29→29 | 0.7701 | 6444 ✓ | 6444 ✓ | 6444 ✓ | 6444 ✓ | 6444 ✓ | 6444 ✓ | 6444 ✓ | 6444 ✓ | 6444 ✓ | 6444 ✓ |

Why V2 keeps the votes the incumbent removed in B: draftSharksIdp 3200: incumbent drop in B; in C status=voting, identity=NAME_ONLY, V2 reason=kept_dissent

#### CJ Allen (LB, IND, idp)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 3987 | 106 | low | medium/high/medium/high/low | 3 | - |
| B | 2172 | 286 | medium | medium/medium/medium/high/medium | 3 | draftSharksIdp |
| C | 4033 | 104 | low | medium/high/medium/high/low | 4 | - |
| D | 3987 | 108 | low | medium/high/medium/high/low | 3 | - |
| B' | 3987 | 106 | low | medium/high/medium/high/low | 3 | - |
| C' | 3987 | 108 | low | medium/high/medium/high/low | 3 | - |
| B'' | 2172 | 283 | medium | medium/medium/medium/high/medium | 3 | draftSharksIdp |
| C'' | 4033 | 103 | low | medium/high/medium/high/low | 4 | - |
| Anf | 3987 | 108 | low | medium/high/medium/high/low | 3 | - |
| Bnf | 4033 | 104 | low | medium/high/medium/high/low | 4 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfIdp | dlf | exact | 50→230 | 0.5 | — | 2645 ✓ | 2645 ✓ [voting_name_only_identity] | — | — | — | 2645 ✓ | 2645 ✓ [voting_name_only_identity] | — | 2645 ✓ |
| dlfRookieIdp | dlf | rookie_ladder_translation_via_idpTradeCalc | 9→243 | 0.5 | — | 2568 ✓ | 2568 ✓ [voting_name_only_identity] | — | — | — | 2568 ✓ | 2568 ✓ [voting_name_only_identity] | — | 2568 ✓ |
| draftSharksIdp | draftSharks | ds_combined_cross_market | 4→37 | 1.0 | 5790 ✓ | 5790 **DROPPED** | 5790 ✓ [kept_dissent] | 5790 ✓ [kept_dissent] | 5790 ✓ | 5790 ✓ [kept_dissent] | 5790 **DROPPED** | 5790 ✓ [kept_dissent] | 5790 ✓ | 5790 ✓ |
| fantasyProsIdp | fantasyPros | exact | 62→350 | 0.1686 | 2095 ✓ | 2095 ✓ | 2095 ✓ | 2095 ✓ | 2095 ✓ | 2095 ✓ | 2095 ✓ | 2095 ✓ | 2095 ✓ | 2095 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 142→142 | 0.0 | 3383 stale(w=0) | 3383 stale(w=0) | 3383 stale(w=0) | 3383 stale(w=0) | 3383 stale(w=0) | 3383 stale(w=0) | 3383 stale(w=0) | 3383 stale(w=0) | 3383 stale(w=0) | 3383 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 356→356 | 0.7701 | 2129 ✓ | 2129 ✓ | 2129 ✓ | 2129 ✓ | 2129 ✓ | 2129 ✓ | 2129 ✓ | 2129 ✓ | 2129 ✓ | 2129 ✓ |

Why V2 keeps the votes the incumbent removed in B: draftSharksIdp 5790: incumbent drop in B; in C status=voting, identity=NAME_ONLY, V2 reason=kept_dissent

#### T.J. Watt (DL, PIT, idp)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 2394 | 250 | low | medium/high/medium/high/low | 3 | - |
| B | 3436 | 138 | medium | medium/medium/medium/high/high | 3 | draftSharksIdp |
| C | 2415 | 249 | low | medium/high/medium/high/low | 4 | - |
| D | 2394 | 251 | low | medium/high/medium/high/low | 3 | - |
| B' | 2394 | 248 | low | medium/high/medium/high/low | 3 | - |
| C' | 2394 | 249 | low | medium/high/medium/high/low | 3 | - |
| B'' | 3436 | 135 | medium | medium/medium/medium/high/high | 3 | draftSharksIdp |
| C'' | 2415 | 249 | low | medium/high/medium/high/low | 4 | - |
| Anf | 2394 | 251 | low | medium/high/medium/high/low | 3 | - |
| Bnf | 2415 | 249 | low | medium/high/medium/high/low | 4 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfIdp | dlf | exact | 25→151 | 1.0 | — | 3283 ✓ | 3283 ✓ [voting_name_only_identity] | — | — | — | 3283 ✓ | 3283 ✓ [voting_name_only_identity] | — | 3283 ✓ |
| draftSharksIdp | draftSharks | ds_combined_cross_market | 278→647 | 1.0 | 1450 ✓ | 1450 **DROPPED** | 1450 ✓ [kept_dissent] | 1450 ✓ [kept_dissent] | 1450 ✓ | 1450 ✓ [kept_dissent] | 1450 **DROPPED** | 1450 ✓ [kept_dissent] | 1450 ✓ | 1450 ✓ |
| fantasyProsIdp | fantasyPros | exact | 33→177 | 0.1686 | 3033 ✓ | 3033 ✓ | 3033 ✓ | 3033 ✓ | 3033 ✓ | 3033 ✓ | 3033 ✓ | 3033 ✓ | 3033 ✓ | 3033 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 183→183 | 0.0 | 2982 stale(w=0) | 2982 stale(w=0) | 2982 stale(w=0) | 2982 stale(w=0) | 2982 stale(w=0) | 2982 stale(w=0) | 2982 stale(w=0) | 2982 stale(w=0) | 2982 stale(w=0) | 2982 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 166→166 | 0.7701 | 3458 ✓ | 3458 ✓ | 3458 ✓ | 3458 ✓ | 3458 ✓ | 3458 ✓ | 3458 ✓ | 3458 ✓ | 3458 ✓ | 3458 ✓ |

Why V2 keeps the votes the incumbent removed in B: draftSharksIdp 1450: incumbent drop in B; in C status=voting, identity=NAME_ONLY, V2 reason=kept_dissent

#### Josiah Trotter (LB, TB, idp)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 2368 | 257 | low | medium/high/medium/high/low | 3 | - |
| B | 3379 | 144 | low | low/low/medium/medium/medium | 2 | fantasyProsIdp, draftSharksIdp |
| C | 2493 | 239 | low | medium/high/medium/high/low | 4 | - |
| D | 2368 | 257 | low | medium/high/medium/high/low | 3 | - |
| B' | 2368 | 256 | low | medium/high/medium/high/low | 3 | - |
| C' | 2368 | 257 | low | medium/high/medium/high/low | 3 | - |
| B'' | 3379 | 143 | low | low/low/medium/medium/medium | 2 | fantasyProsIdp, draftSharksIdp |
| C'' | 2493 | 239 | low | medium/high/medium/high/low | 4 | - |
| Anf | 2368 | 257 | low | medium/high/medium/high/low | 3 | - |
| Bnf | 2493 | 239 | low | medium/high/medium/high/low | 4 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfIdp | dlf | exact | 27→162 | 0.5 | — | 3171 ✓ | 3171 ✓ [voting_name_only_identity] | — | — | — | 3171 ✓ | 3171 ✓ [voting_name_only_identity] | — | 3171 ✓ |
| dlfRookieIdp | dlf | rookie_ladder_translation_via_idpTradeCalc | 5→151 | 0.5 | — | 3283 ✓ | 3283 ✓ [voting_name_only_identity] | — | — | — | 3283 ✓ | 3283 ✓ [voting_name_only_identity] | — | 3283 ✓ |
| draftSharksIdp | draftSharks | ds_combined_cross_market | 156→511 | 1.0 | 1675 ✓ | 1675 **DROPPED** | 1675 ✓ [voting_name_only_identity] | 1675 ✓ [voting_name_only_identity] | 1675 ✓ | 1675 ✓ [voting_name_only_identity] | 1675 **DROPPED** | 1675 ✓ [voting_name_only_identity] | 1675 ✓ | 1675 ✓ |
| fantasyProsIdp | fantasyPros | exact | 102→426 | 0.1686 | 1868 ✓ | 1868 **DROPPED** | 1868 ✓ | 1868 ✓ | 1868 ✓ | 1868 ✓ | 1868 **DROPPED** | 1868 ✓ | 1868 ✓ | 1868 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 201→201 | 0.0 | 2840 stale(w=0) | 2840 stale(w=0) | 2840 stale(w=0) | 2840 stale(w=0) | 2840 stale(w=0) | 2840 stale(w=0) | 2840 stale(w=0) | 2840 stale(w=0) | 2840 stale(w=0) | 2840 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 174→174 | 0.7701 | 3396 ✓ | 3396 ✓ | 3396 ✓ | 3396 ✓ | 3396 ✓ | 3396 ✓ | 3396 ✓ | 3396 ✓ | 3396 ✓ | 3396 ✓ |

Why V2 keeps the votes the incumbent removed in B: draftSharksIdp 1675: incumbent drop in B; in C status=voting, identity=NAME_ONLY, V2 reason=voting_name_only_identity | fantasyProsIdp 1868: incumbent drop in B; in C status=voting, identity=VERIFIED, V2 reason=voting

#### Will Anderson (DL, HOU, idp)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 4354 | 87 | low | medium/high/medium/high/low | 3 | - |
| B | 5980 | 36 | medium | medium/medium/medium/high/high | 3 | draftSharksIdp |
| C | 4407 | 84 | low | medium/high/medium/high/low | 4 | - |
| D | 4354 | 87 | low | medium/high/medium/high/low | 3 | - |
| B' | 4354 | 86 | low | medium/high/medium/high/low | 3 | - |
| C' | 4354 | 87 | low | medium/high/medium/high/low | 3 | - |
| B'' | 5980 | 36 | medium | medium/medium/medium/high/high | 3 | draftSharksIdp |
| C'' | 4407 | 84 | low | medium/high/medium/high/low | 4 | - |
| Anf | 4354 | 87 | low | medium/high/medium/high/low | 3 | - |
| Bnf | 4407 | 84 | low | medium/high/medium/high/low | 4 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfIdp | dlf | exact | 1→29 | 1.0 | — | 6227 ✓ | 6227 ✓ [voting_name_only_identity] | — | — | — | 6227 ✓ | 6227 ✓ [voting_name_only_identity] | — | 6227 ✓ |
| draftSharksIdp | draftSharks | ds_combined_cross_market | 33→197 | 1.0 | 2870 ✓ | 2870 **DROPPED** | 2870 ✓ [kept_dissent] | 2870 ✓ [kept_dissent] | 2870 ✓ | 2870 ✓ [kept_dissent] | 2870 **DROPPED** | 2870 ✓ [kept_dissent] | 2870 ✓ | 2870 ✓ |
| fantasyProsIdp | fantasyPros | exact | 2→41 | 0.1686 | 5603 ✓ | 5603 ✓ | 5603 ✓ | 5603 ✓ | 5603 ✓ | 5603 ✓ | 5603 ✓ | 5603 ✓ | 5603 ✓ | 5603 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 87→87 | 0.0 | 4225 stale(w=0) | 4225 stale(w=0) | 4225 stale(w=0) | 4225 stale(w=0) | 4225 stale(w=0) | 4225 stale(w=0) | 4225 stale(w=0) | 4225 stale(w=0) | 4225 stale(w=0) | 4225 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 41→41 | 0.7701 | 5963 ✓ | 5963 ✓ | 5963 ✓ | 5963 ✓ | 5963 ✓ | 5963 ✓ | 5963 ✓ | 5963 ✓ | 5963 ✓ | 5963 ✓ |

Why V2 keeps the votes the incumbent removed in B: draftSharksIdp 2870: incumbent drop in B; in C status=voting, identity=NAME_ONLY, V2 reason=kept_dissent

#### Danielle Hunter (DL, HOU, idp)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 2333 | 264 | low | medium/high/medium/high/low | 3 | - |
| B | 3035 | 173 | medium | medium/medium/medium/high/high | 3 | draftSharksIdp |
| C | 2309 | 267 | low | medium/high/medium/high/low | 4 | - |
| D | 2333 | 264 | low | medium/high/medium/high/low | 3 | - |
| B' | 2333 | 263 | low | medium/high/medium/high/low | 3 | - |
| C' | 2333 | 263 | low | medium/high/medium/high/low | 3 | - |
| B'' | 3035 | 173 | medium | medium/medium/medium/high/high | 3 | draftSharksIdp |
| C'' | 2309 | 265 | low | medium/high/medium/high/low | 4 | - |
| Anf | 2333 | 264 | low | medium/high/medium/high/low | 3 | - |
| Bnf | 2309 | 267 | low | medium/high/medium/high/low | 4 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfIdp | dlf | exact | 46→221 | 1.0 | — | 2702 ✓ | 2702 ✓ [voting_name_only_identity] | — | — | — | 2702 ✓ | 2702 ✓ [voting_name_only_identity] | — | 2702 ✓ |
| draftSharksIdp | draftSharks | ds_combined_cross_market | 178→529 | 1.0 | 1641 ✓ | 1641 **DROPPED** | 1641 ✓ [voting_name_only_identity] | 1641 ✓ [voting_name_only_identity] | 1641 ✓ | 1641 ✓ [voting_name_only_identity] | 1641 **DROPPED** | 1641 ✓ [voting_name_only_identity] | 1641 ✓ | 1641 ✓ |
| fantasyProsIdp | fantasyPros | exact | 35→183 | 0.1686 | 2982 ✓ | 2982 ✓ | 2982 ✓ | 2982 ✓ | 2982 ✓ | 2982 ✓ | 2982 ✓ | 2982 ✓ | 2982 ✓ | 2982 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 213→213 | 0.0 | 2755 stale(w=0) | 2755 stale(w=0) | 2755 stale(w=0) | 2755 stale(w=0) | 2755 stale(w=0) | 2755 stale(w=0) | 2755 stale(w=0) | 2755 stale(w=0) | 2755 stale(w=0) | 2755 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 221→221 | 0.7701 | 3068 ✓ | 3068 ✓ | 3068 ✓ | 3068 ✓ | 3068 ✓ | 3068 ✓ | 3068 ✓ | 3068 ✓ | 3068 ✓ | 3068 ✓ |

Why V2 keeps the votes the incumbent removed in B: draftSharksIdp 1641: incumbent drop in B; in C status=voting, identity=NAME_ONLY, V2 reason=voting_name_only_identity

#### Jared Verse (DL, CLE, idp)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 2666 | 211 | medium | medium/high/medium/high/high | 3 | - |
| B | 2666 | 214 | medium | medium/medium/medium/high/high | 3 | dlfIdp |
| C | 2829 | 189 | low | medium/high/medium/high/low | 4 | - |
| D | 2666 | 211 | medium | medium/high/medium/high/high | 3 | - |
| B' | 2666 | 211 | medium | medium/high/medium/high/high | 3 | - |
| C' | 2666 | 211 | medium | medium/high/medium/high/high | 3 | - |
| B'' | 2666 | 214 | medium | medium/medium/medium/high/high | 3 | dlfIdp |
| C'' | 2829 | 189 | low | medium/high/medium/high/low | 4 | - |
| Anf | 2666 | 211 | medium | medium/high/medium/high/high | 3 | - |
| Bnf | 2829 | 189 | low | medium/high/medium/high/low | 4 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfIdp | dlf | exact | 10→68 | 1.0 | — | 4671 **DROPPED** | 4671 ✓ [voting_name_only_identity] | — | — | — | 4671 **DROPPED** | 4671 ✓ [voting_name_only_identity] | — | 4671 ✓ |
| draftSharksIdp | draftSharks | ds_combined_cross_market | 45→271 | 1.0 | 2419 ✓ | 2419 ✓ | 2419 ✓ [voting_name_only_identity] | 2419 ✓ [voting_name_only_identity] | 2419 ✓ | 2419 ✓ [voting_name_only_identity] | 2419 ✓ | 2419 ✓ [voting_name_only_identity] | 2419 ✓ | 2419 ✓ |
| fantasyProsIdp | fantasyPros | exact | 42→212 | 0.1686 | 2762 ✓ | 2762 ✓ | 2762 ✓ | 2762 ✓ | 2762 ✓ | 2762 ✓ | 2762 ✓ | 2762 ✓ | 2762 ✓ | 2762 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 108→108 | 0.0 | 3844 stale(w=0) | 3844 stale(w=0) | 3844 stale(w=0) | 3844 stale(w=0) | 3844 stale(w=0) | 3844 stale(w=0) | 3844 stale(w=0) | 3844 stale(w=0) | 3844 stale(w=0) | 3844 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 242→242 | 0.7701 | 2963 ✓ | 2963 ✓ | 2963 ✓ | 2963 ✓ | 2963 ✓ | 2963 ✓ | 2963 ✓ | 2963 ✓ | 2963 ✓ | 2963 ✓ |

Why V2 keeps the votes the incumbent removed in B: dlfIdp 4671: incumbent drop in B; in C status=voting, identity=NAME_ONLY, V2 reason=voting_name_only_identity

#### Theo Johnson (TE, NYG, offense)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 2186 | 289 | medium | high/high/high/medium/medium | 13 | - |
| B | 2186 | 283 | medium | high/high/high/medium/medium | 13 | - |
| C | 2186 | 288 | medium | high/high/high/medium/medium | 13 | - |
| D | 2186 | 289 | medium | high/high/high/medium/medium | 13 | - |
| B' | 2105 | 308 | medium | high/high/high/medium/medium | 13 | - |
| C' | 2105 | 309 | medium | high/high/high/medium/medium | 13 | - |
| B'' | 2105 | 301 | medium | high/high/high/medium/medium | 13 | - |
| C'' | 2105 | 306 | medium | high/high/high/medium/medium | 13 | - |
| Anf | 2186 | 289 | medium | high/high/high/medium/medium | 13 | - |
| Bnf | 2186 | 288 | medium | high/high/high/medium/medium | 13 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfSf | dlf | direct | 243→243 | 1.0 | 2271 ✓ | 2271 ✓ | 2271 ✓ [voting_name_only_identity] | 2271 ✓ [voting_name_only_identity] | 2271 ✓ | 2271 ✓ [voting_name_only_identity] | 2271 ✓ | 2271 ✓ [voting_name_only_identity] | 2271 ✓ | 2271 ✓ |
| dlfValuesSfTep | dlf | direct | 271→271 | 0.5 | — | — | — | — | 1603 ✓ | 1603 ✓ | 1603 ✓ | 1603 ✓ | — | — |
| draftSharks | draftSharks | ds_combined_cross_market | 164→217 | 1.0 | 3001 ✓ | 3001 ✓ | 3001 ✓ [voting_name_only_identity] | 3001 ✓ [voting_name_only_identity] | 3001 ✓ | 3001 ✓ [voting_name_only_identity] | 3001 ✓ | 3001 ✓ [voting_name_only_identity] | 3001 ✓ | 3001 ✓ |
| dynastyDaddySf | dynastyDaddySf | direct | 290→290 | 1.0 | 1983 ✓ | 1983 ✓ | 1983 ✓ [voting_name_only_identity] | 1983 ✓ [voting_name_only_identity] | 1983 ✓ | 1983 ✓ [voting_name_only_identity] | 1983 ✓ | 1983 ✓ [voting_name_only_identity] | 1983 ✓ | 1983 ✓ |
| dynastyNerdsSfTep | dynastyNerdsSfTep | direct | 250→250 | 1.0 | 1730 ✓ | 1730 ✓ | 1730 ✓ | 1730 ✓ | 1730 ✓ | 1730 ✓ | 1730 ✓ | 1730 ✓ | 1730 ✓ | 1730 ✓ |
| fantasyCalc | fantasyCalc | direct | 324→324 | 1.0 | 1820 ✓ | 1820 ✓ | 1820 ✓ [voting_name_only_identity] | 1820 ✓ [voting_name_only_identity] | 1820 ✓ | 1820 ✓ [voting_name_only_identity] | 1820 ✓ | 1820 ✓ [voting_name_only_identity] | 1820 ✓ | 1820 ✓ |
| fantasyNavigatorSf | ktcCrowd | direct | 236→236 | 0.0 | 2323 stale(w=0) | 2323 stale(w=0) | 2323 stale(w=0) | 2323 stale(w=0) | 2323 stale(w=0) | 2323 stale(w=0) | 2323 stale(w=0) | 2323 stale(w=0) | 2323 stale(w=0) | 2323 stale(w=0) |
| fantasyProsSf | fantasyPros | direct | 246→246 | 1.0 | 2250 ✓ | 2250 ✓ | 2250 ✓ | 2250 ✓ | 2250 ✓ | 2250 ✓ | 2250 ✓ | 2250 ✓ | 2250 ✓ | 2250 ✓ |
| flockFantasySf | flockFantasy | direct | 241→241 | 1.0 | 2286 ✓ | 2286 ✓ | 2286 ✓ [voting_name_only_identity] | 2286 ✓ [voting_name_only_identity] | 2286 ✓ | 2286 ✓ [voting_name_only_identity] | 2286 ✓ | 2286 ✓ [voting_name_only_identity] | 2286 ✓ | 2286 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 377→378 | 0.0 | 2714 stale(w=0) | 2714 stale(w=0) | 2714 stale(w=0) | 2714 stale(w=0) | 2714 stale(w=0) | 2714 stale(w=0) | 2714 stale(w=0) | 2714 stale(w=0) | 2714 stale(w=0) | 2714 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 343→343 | 0.8238 | 2458 ✓ | 2458 ✓ | 2458 ✓ | 2458 ✓ | 2458 ✓ | 2458 ✓ | 2458 ✓ | 2458 ✓ | 2458 ✓ | 2458 ✓ |
| ktcCrowdSfTep | ktcCrowd | direct | 240→240 | 1.0 | 2411 ✓ | 2411 ✓ | 2411 ✓ [voting_name_only_identity] | 2411 ✓ [voting_name_only_identity] | 2411 ✓ | 2411 ✓ [voting_name_only_identity] | 2411 ✓ | 2411 ✓ [voting_name_only_identity] | 2411 ✓ | 2411 ✓ |
| ktcTradesSfTep | ktcTrades | direct | 188→188 | 1.0 | 2727 ✓ | 2727 ✓ | 2727 ✓ [voting_name_only_identity] | 2727 ✓ [voting_name_only_identity] | 2727 ✓ | 2727 ✓ [voting_name_only_identity] | 2727 ✓ | 2727 ✓ [voting_name_only_identity] | 2727 ✓ | 2727 ✓ |
| otcffbSf | otcffbSf | direct | 293→293 | 0.9981 | 1967 ✓ | 1967 ✓ | 1967 ✓ [voting_name_only_identity] | 1967 ✓ [voting_name_only_identity] | 1967 ✓ | 1967 ✓ [voting_name_only_identity] | 1967 ✓ | 1967 ✓ [voting_name_only_identity] | 1967 ✓ | 1967 ✓ |
| pfkDynasty | pfkDynasty | direct | 343→343 | 1.0 | 1741 ✓ | 1741 ✓ | 1741 ✓ | 1741 ✓ | 1741 ✓ | 1741 ✓ | 1741 ✓ | 1741 ✓ | 1741 ✓ | 1741 ✓ |
| yahooBoone | yahooBoone | direct | 261→261 | 1.0 | 1661 ✓ | 1661 ✓ | 1661 ✓ [voting_name_only_identity] | 1661 ✓ [voting_name_only_identity] | 1661 ✓ | 1661 ✓ [voting_name_only_identity] | 1661 ✓ | 1661 ✓ [voting_name_only_identity] | 1661 ✓ | 1661 ✓ |

#### Travis Hunter (WR, JAX, offense)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 3599 | 130 | low | high/high/high/high/low | 11 | idpTradeCalc |
| B | 3493 | 133 | low | high/high/high/high/low | 11 | idpTradeCalc |
| C | 3493 | 136 | low | high/high/high/high/low | 12 | - |
| D | 3599 | 130 | low | high/high/high/high/low | 12 | - |
| B' | 3599 | 130 | low | high/high/high/high/low | 11 | idpTradeCalc |
| C' | 3599 | 130 | low | high/high/high/high/low | 12 | - |
| B'' | 3493 | 132 | low | high/high/high/high/low | 11 | idpTradeCalc |
| C'' | 3493 | 135 | low | high/high/high/high/low | 12 | - |
| Anf | 3599 | 130 | low | high/high/high/high/low | 12 | - |
| Bnf | 3493 | 136 | low | high/high/high/high/low | 12 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfSf | dlf | direct | 141→141 | 1.0 | 2613 ✓ | 2613 ✓ | 2613 ✓ [voting_name_only_identity] | 2613 ✓ [voting_name_only_identity] | 2613 ✓ | 2613 ✓ [voting_name_only_identity] | 2613 ✓ | 2613 ✓ [voting_name_only_identity] | 2613 ✓ | 2613 ✓ |
| dlfValuesSfTep | dlf | direct | 184→184 | 0.5 | — | — | — | — | 2080 ✓ | 2080 ✓ | 2080 ✓ | 2080 ✓ | — | — |
| draftSharks | draftSharks | ds_combined_cross_market | 145→194 | 1.0 | 2893 ✓ | 2893 ✓ | 2893 ✓ [voting_name_only_identity] | 2893 ✓ [voting_name_only_identity] | 2893 ✓ | 2893 ✓ [voting_name_only_identity] | 2893 ✓ | 2893 ✓ [voting_name_only_identity] | 2893 ✓ | 2893 ✓ |
| dynastyNerdsSfTep | dynastyNerdsSfTep | direct | 172→172 | 1.0 | 2207 ✓ | 2207 ✓ | 2207 ✓ | 2207 ✓ | 2207 ✓ | 2207 ✓ | 2207 ✓ | 2207 ✓ | 2207 ✓ | 2207 ✓ |
| fantasyCalc | fantasyCalc | direct | 158→158 | 1.0 | 2375 ✓ | 2375 ✓ | 2375 ✓ [voting_name_only_identity] | 2375 ✓ [voting_name_only_identity] | 2375 ✓ | 2375 ✓ [voting_name_only_identity] | 2375 ✓ | 2375 ✓ [voting_name_only_identity] | 2375 ✓ | 2375 ✓ |
| fantasyNavigatorSf | ktcCrowd | direct | 161→161 | 0.0 | 2337 stale(w=0) | 2337 stale(w=0) | 2337 stale(w=0) | 2337 stale(w=0) | 2337 stale(w=0) | 2337 stale(w=0) | 2337 stale(w=0) | 2337 stale(w=0) | 2337 stale(w=0) | 2337 stale(w=0) |
| fantasyProsFitzmaurice | fantasyPros | direct | 225→225 | 0.5 | 1735 ✓ | 1735 ✓ | 1742 ✓ | 1742 ✓ | 1735 ✓ | 1742 ✓ | 1735 ✓ | 1742 ✓ | 1735 ✓ | 1735 ✓ |
| fantasyProsSf | fantasyPros | direct | 180→180 | 0.5 | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ |
| flockFantasySf | flockFantasy | direct | 125→125 | 1.0 | 2881 ✓ | 2881 ✓ | 2881 ✓ [voting_name_only_identity] | 2881 ✓ [voting_name_only_identity] | 2881 ✓ | 2881 ✓ [voting_name_only_identity] | 2881 ✓ | 2881 ✓ [voting_name_only_identity] | 2881 ✓ | 2881 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 109→109 | 0.0 | 3828 stale(w=0) | 3828 stale(w=0) | 3828 stale(w=0) | 3828 stale(w=0) | 3828 stale(w=0) | 3828 stale(w=0) | 3828 stale(w=0) | 3828 stale(w=0) | 3828 stale(w=0) | 3828 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 147→147 | 0.8238 | 3599 **DROPPED** | 3599 **DROPPED** | 3599 ✓ | 3599 ✓ | 3599 **DROPPED** | 3599 ✓ | 3599 **DROPPED** | 3599 ✓ | 3599 ✓ | 3599 ✓ |
| ktcCrowdSfTep | ktcCrowd | direct | 250→250 | 1.0 | 2275 ✓ | 2275 ✓ | 2275 ✓ [voting_name_only_identity] | 2275 ✓ [voting_name_only_identity] | 2275 ✓ | 2275 ✓ [voting_name_only_identity] | 2275 ✓ | 2275 ✓ [voting_name_only_identity] | 2275 ✓ | 2275 ✓ |
| ktcTradesSfTep | ktcTrades | direct | 213→213 | 1.0 | 2620 ✓ | 2620 ✓ | 2620 ✓ [voting_name_only_identity] | 2620 ✓ [voting_name_only_identity] | 2620 ✓ | 2620 ✓ [voting_name_only_identity] | 2620 ✓ | 2620 ✓ [voting_name_only_identity] | 2620 ✓ | 2620 ✓ |
| otcffbSf | otcffbSf | direct | 167→167 | 0.9981 | 2264 ✓ | 2264 ✓ | 2264 ✓ [voting_name_only_identity] | 2264 ✓ [voting_name_only_identity] | 2264 ✓ | 2264 ✓ [voting_name_only_identity] | 2264 ✓ | 2264 ✓ [voting_name_only_identity] | 2264 ✓ | 2264 ✓ |
| pfkDynasty | pfkDynasty | direct | 180→180 | 1.0 | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ |
| yahooBoone | yahooBoone | direct | 207→207 | 1.0 | 1872 ✓ | 1872 ✓ | 1872 ✓ [voting_name_only_identity] | 1872 ✓ [voting_name_only_identity] | 1872 ✓ | 1872 ✓ [voting_name_only_identity] | 1872 ✓ | 1872 ✓ [voting_name_only_identity] | 1872 ✓ | 1872 ✓ |

Why V2 keeps the votes the incumbent removed in B: idpTradeCalc 3599: incumbent drop in B; in C status=voting, identity=None, V2 reason=voting

