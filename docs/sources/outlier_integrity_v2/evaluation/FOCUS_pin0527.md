# Focus rows, pin0527: full per-player source tables

Cell = the source's priced vote on that board and its state: ✓ voting; **DROPPED** = removed by the incumbent per-row filter; stale(w=0) = freshness/health zero weight (never a vote); `v2_refused:<reason>` = refused by V2 Layer A before pricing; a bracketed reason is V2's stamp on a vote that still votes (`kept_dissent` = Layer C assessed it as legitimate disagreement and kept it; `voting_name_only_identity` = Layer A could confirm the name only and let it vote). — = no observation. Boards: A production; B DLF IDP restored + incumbent; C DLF IDP restored + V2; D V2 with DLF held; B′/C′ D4 on (incumbent / V2); B″/C″ DLF IDP restored + D4 on (incumbent / V2); Anf/Bnf no per-row filter.

#### Trevin Wallace (LB, NYJ, idp)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 1916 | 350 | low | medium/high/medium/high/low | 3 | - |
| B | 884 | None | low | medium/medium/medium/high/low | 3 | draftSharksIdp |
| C | 1913 | 352 | low | medium/high/medium/high/low | 4 | - |
| D | 1916 | 350 | low | medium/high/medium/high/low | 3 | - |
| B' | 1916 | 348 | low | medium/high/medium/high/low | 3 | - |
| C' | 1916 | 350 | low | medium/high/medium/high/low | 3 | - |
| B'' | 884 | None | low | medium/medium/medium/high/low | 3 | draftSharksIdp |
| C'' | 1913 | 351 | low | medium/high/medium/high/low | 4 | - |
| Anf | 1916 | 350 | low | medium/high/medium/high/low | 3 | - |
| Bnf | 1913 | 351 | low | medium/high/medium/high/low | 4 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfIdp | dlf | exact | 164→601 | 1.0 | — | 1517 ✓ | 1517 ✓ [voting_name_only_identity] | — | — | — | 1517 ✓ | 1517 ✓ [voting_name_only_identity] | — | 1517 ✓ |
| draftSharksIdp | draftSharks | ds_combined_cross_market | 33→195 | 1.0 | 2886 ✓ | 2886 **DROPPED** | 2886 ✓ [voting_name_only_identity] | 2886 ✓ [voting_name_only_identity] | 2886 ✓ | 2886 ✓ [voting_name_only_identity] | 2886 **DROPPED** | 2886 ✓ [voting_name_only_identity] | 2886 ✓ | 2886 ✓ |
| fantasyProsIdp | fantasyPros | exact | 153→576 | 0.1752 | 1558 ✓ | 1558 ✓ | 1558 ✓ | 1558 ✓ | 1558 ✓ | 1558 ✓ | 1558 ✓ | 1558 ✓ | 1558 ✓ | 1558 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 435→436 | 0.0 | 1842 stale(w=0) | 1842 stale(w=0) | 1842 stale(w=0) | 1842 stale(w=0) | 1842 stale(w=0) | 1842 stale(w=0) | 1842 stale(w=0) | 1842 stale(w=0) | 1842 stale(w=0) | 1842 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 810→810 | 0.8135 | 814 ✓ | 814 ✓ | 814 ✓ | 814 ✓ | 814 ✓ | 814 ✓ | 814 ✓ | 814 ✓ | 814 ✓ | 814 ✓ |

Why V2 keeps the votes the incumbent removed in B: draftSharksIdp 2886: incumbent drop in B; in C status=voting, identity=NAME_ONLY, V2 reason=voting_name_only_identity

#### Myles Garrett (DL, LAR, idp)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 3597 | 131 | low | medium/high/medium/high/low | 3 | - |
| B | 5246 | 61 | medium | medium/medium/medium/high/medium | 3 | draftSharksIdp |
| C | 3512 | 135 | low | medium/high/medium/high/low | 4 | - |
| D | 3597 | 131 | low | medium/high/medium/high/low | 3 | - |
| B' | 3597 | 131 | low | medium/high/medium/high/low | 3 | - |
| C' | 3597 | 131 | low | medium/high/medium/high/low | 3 | - |
| B'' | 5246 | 62 | medium | medium/medium/medium/high/medium | 3 | draftSharksIdp |
| C'' | 3512 | 135 | low | medium/high/medium/high/low | 4 | - |
| Anf | 3597 | 131 | low | medium/high/medium/high/low | 3 | - |
| Bnf | 3512 | 135 | low | medium/high/medium/high/low | 4 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfIdp | dlf | exact | 11→116 | 1.0 | — | 3721 ✓ | 3721 ✓ [voting_name_only_identity] | — | — | — | 3721 ✓ | 3721 ✓ [voting_name_only_identity] | — | 3721 ✓ |
| draftSharksIdp | draftSharks | ds_combined_cross_market | 93→412 | 1.0 | 1905 ✓ | 1905 **DROPPED** | 1905 ✓ [kept_dissent] | 1905 ✓ [kept_dissent] | 1905 ✓ | 1905 ✓ [kept_dissent] | 1905 **DROPPED** | 1905 ✓ [kept_dissent] | 1905 ✓ | 1905 ✓ |
| fantasyProsIdp | fantasyPros | exact | 8→66 | 0.1752 | 4726 ✓ | 4726 ✓ | 4726 ✓ | 4726 ✓ | 4726 ✓ | 4726 ✓ | 4726 ✓ | 4726 ✓ | 4726 ✓ | 4726 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 89→89 | 0.0 | 4184 stale(w=0) | 4184 stale(w=0) | 4184 stale(w=0) | 4184 stale(w=0) | 4184 stale(w=0) | 4184 stale(w=0) | 4184 stale(w=0) | 4184 stale(w=0) | 4184 stale(w=0) | 4184 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 68→68 | 0.8135 | 5399 ✓ | 5399 ✓ | 5399 ✓ | 5399 ✓ | 5399 ✓ | 5399 ✓ | 5399 ✓ | 5399 ✓ | 5399 ✓ | 5399 ✓ |

Why V2 keeps the votes the incumbent removed in B: draftSharksIdp 1905: incumbent drop in B; in C status=voting, identity=NAME_ONLY, V2 reason=kept_dissent

#### Aidan Hutchinson (DL, DET, idp)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 4802 | 70 | low | medium/high/medium/high/low | 3 | - |
| B | 6422 | 34 | medium | medium/medium/medium/high/high | 3 | draftSharksIdp |
| C | 4802 | 71 | low | medium/high/medium/high/low | 4 | - |
| D | 4802 | 70 | low | medium/high/medium/high/low | 3 | - |
| B' | 4802 | 71 | low | medium/high/medium/high/low | 3 | - |
| C' | 4802 | 71 | low | medium/high/medium/high/low | 3 | - |
| B'' | 6422 | 34 | medium | medium/medium/medium/high/high | 3 | draftSharksIdp |
| C'' | 4802 | 72 | low | medium/high/medium/high/low | 4 | - |
| Anf | 4802 | 70 | low | medium/high/medium/high/low | 3 | - |
| Bnf | 4802 | 71 | low | medium/high/medium/high/low | 4 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfIdp | dlf | exact | 1→29 | 1.0 | — | 6227 ✓ | 6227 ✓ [voting_name_only_identity] | — | — | — | 6227 ✓ | 6227 ✓ [voting_name_only_identity] | — | 6227 ✓ |
| draftSharksIdp | draftSharks | ds_combined_cross_market | 31→161 | 1.0 | 3181 ✓ | 3181 **DROPPED** | 3181 ✓ [kept_dissent] | 3181 ✓ [kept_dissent] | 3181 ✓ | 3181 ✓ [kept_dissent] | 3181 **DROPPED** | 3181 ✓ [kept_dissent] | 3181 ✓ | 3181 ✓ |
| fantasyProsIdp | fantasyPros | exact | 1→29 | 0.1752 | 6227 ✓ | 6227 ✓ | 6227 ✓ | 6227 ✓ | 6227 ✓ | 6227 ✓ | 6227 ✓ | 6227 ✓ | 6227 ✓ | 6227 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 71→71 | 0.0 | 4592 stale(w=0) | 4592 stale(w=0) | 4592 stale(w=0) | 4592 stale(w=0) | 4592 stale(w=0) | 4592 stale(w=0) | 4592 stale(w=0) | 4592 stale(w=0) | 4592 stale(w=0) | 4592 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 29→29 | 0.8135 | 6444 ✓ | 6444 ✓ | 6444 ✓ | 6444 ✓ | 6444 ✓ | 6444 ✓ | 6444 ✓ | 6444 ✓ | 6444 ✓ | 6444 ✓ |

Why V2 keeps the votes the incumbent removed in B: draftSharksIdp 3181: incumbent drop in B; in C status=voting, identity=NAME_ONLY, V2 reason=kept_dissent

#### CJ Allen (LB, IND, idp)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 3918 | 109 | low | medium/high/medium/high/low | 3 | - |
| B | 2172 | 287 | medium | medium/medium/medium/high/medium | 3 | draftSharksIdp |
| C | 3964 | 107 | low | medium/high/medium/high/low | 4 | - |
| D | 3918 | 110 | low | medium/high/medium/high/low | 3 | - |
| B' | 3918 | 109 | low | medium/high/medium/high/low | 3 | - |
| C' | 3918 | 110 | low | medium/high/medium/high/low | 3 | - |
| B'' | 2172 | 283 | medium | medium/medium/medium/high/medium | 3 | draftSharksIdp |
| C'' | 3964 | 106 | low | medium/high/medium/high/low | 4 | - |
| Anf | 3918 | 110 | low | medium/high/medium/high/low | 3 | - |
| Bnf | 3964 | 107 | low | medium/high/medium/high/low | 4 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfIdp | dlf | exact | 50→230 | 0.5 | — | 2645 ✓ | 2645 ✓ [voting_name_only_identity] | — | — | — | 2645 ✓ | 2645 ✓ [voting_name_only_identity] | — | 2645 ✓ |
| dlfRookieIdp | dlf | rookie_ladder_translation_via_idpTradeCalc | 9→243 | 0.5 | — | 2568 ✓ | 2568 ✓ [voting_name_only_identity] | — | — | — | 2568 ✓ | 2568 ✓ [voting_name_only_identity] | — | 2568 ✓ |
| draftSharksIdp | draftSharks | ds_combined_cross_market | 4→38 | 1.0 | 5741 ✓ | 5741 **DROPPED** | 5741 ✓ [kept_dissent] | 5741 ✓ [kept_dissent] | 5741 ✓ | 5741 ✓ [kept_dissent] | 5741 **DROPPED** | 5741 ✓ [kept_dissent] | 5741 ✓ | 5741 ✓ |
| fantasyProsIdp | fantasyPros | exact | 62→350 | 0.1752 | 2095 ✓ | 2095 ✓ | 2095 ✓ | 2095 ✓ | 2095 ✓ | 2095 ✓ | 2095 ✓ | 2095 ✓ | 2095 ✓ | 2095 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 142→142 | 0.0 | 3383 stale(w=0) | 3383 stale(w=0) | 3383 stale(w=0) | 3383 stale(w=0) | 3383 stale(w=0) | 3383 stale(w=0) | 3383 stale(w=0) | 3383 stale(w=0) | 3383 stale(w=0) | 3383 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 356→356 | 0.8135 | 2129 ✓ | 2129 ✓ | 2129 ✓ | 2129 ✓ | 2129 ✓ | 2129 ✓ | 2129 ✓ | 2129 ✓ | 2129 ✓ | 2129 ✓ |

Why V2 keeps the votes the incumbent removed in B: draftSharksIdp 5741: incumbent drop in B; in C status=voting, identity=NAME_ONLY, V2 reason=kept_dissent

#### T.J. Watt (DL, PIT, idp)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 2418 | 248 | low | medium/high/medium/high/low | 3 | - |
| B | 3436 | 138 | medium | medium/medium/medium/high/high | 3 | draftSharksIdp |
| C | 2440 | 248 | low | medium/high/medium/high/low | 4 | - |
| D | 2418 | 249 | low | medium/high/medium/high/low | 3 | - |
| B' | 2418 | 248 | low | medium/high/medium/high/low | 3 | - |
| C' | 2418 | 249 | low | medium/high/medium/high/low | 3 | - |
| B'' | 3436 | 136 | medium | medium/medium/medium/high/high | 3 | draftSharksIdp |
| C'' | 2440 | 248 | low | medium/high/medium/high/low | 4 | - |
| Anf | 2418 | 249 | low | medium/high/medium/high/low | 3 | - |
| Bnf | 2440 | 248 | low | medium/high/medium/high/low | 4 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfIdp | dlf | exact | 25→151 | 1.0 | — | 3283 ✓ | 3283 ✓ [voting_name_only_identity] | — | — | — | 3283 ✓ | 3283 ✓ [voting_name_only_identity] | — | 3283 ✓ |
| draftSharksIdp | draftSharks | ds_combined_cross_market | 278→647 | 1.0 | 1450 ✓ | 1450 **DROPPED** | 1450 ✓ [kept_dissent] | 1450 ✓ [kept_dissent] | 1450 ✓ | 1450 ✓ [kept_dissent] | 1450 **DROPPED** | 1450 ✓ [kept_dissent] | 1450 ✓ | 1450 ✓ |
| fantasyProsIdp | fantasyPros | exact | 33→177 | 0.1752 | 3033 ✓ | 3033 ✓ | 3033 ✓ | 3033 ✓ | 3033 ✓ | 3033 ✓ | 3033 ✓ | 3033 ✓ | 3033 ✓ | 3033 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 183→183 | 0.0 | 2982 stale(w=0) | 2982 stale(w=0) | 2982 stale(w=0) | 2982 stale(w=0) | 2982 stale(w=0) | 2982 stale(w=0) | 2982 stale(w=0) | 2982 stale(w=0) | 2982 stale(w=0) | 2982 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 166→166 | 0.8135 | 3458 ✓ | 3458 ✓ | 3458 ✓ | 3458 ✓ | 3458 ✓ | 3458 ✓ | 3458 ✓ | 3458 ✓ | 3458 ✓ | 3458 ✓ |

Why V2 keeps the votes the incumbent removed in B: draftSharksIdp 1450: incumbent drop in B; in C status=voting, identity=NAME_ONLY, V2 reason=kept_dissent

#### Josiah Trotter (LB, TB, idp)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 2390 | 253 | low | medium/high/medium/high/low | 3 | - |
| B | 3379 | 144 | low | low/low/medium/medium/medium | 2 | fantasyProsIdp, draftSharksIdp |
| C | 2514 | 234 | low | medium/high/medium/high/low | 4 | - |
| D | 2390 | 254 | low | medium/high/medium/high/low | 3 | - |
| B' | 2390 | 252 | low | medium/high/medium/high/low | 3 | - |
| C' | 2390 | 253 | low | medium/high/medium/high/low | 3 | - |
| B'' | 3379 | 144 | low | low/low/medium/medium/medium | 2 | fantasyProsIdp, draftSharksIdp |
| C'' | 2514 | 233 | low | medium/high/medium/high/low | 4 | - |
| Anf | 2390 | 254 | low | medium/high/medium/high/low | 3 | - |
| Bnf | 2514 | 234 | low | medium/high/medium/high/low | 4 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfIdp | dlf | exact | 27→162 | 0.5 | — | 3171 ✓ | 3171 ✓ [voting_name_only_identity] | — | — | — | 3171 ✓ | 3171 ✓ [voting_name_only_identity] | — | 3171 ✓ |
| dlfRookieIdp | dlf | rookie_ladder_translation_via_idpTradeCalc | 5→151 | 0.5 | — | 3283 ✓ | 3283 ✓ [voting_name_only_identity] | — | — | — | 3283 ✓ | 3283 ✓ [voting_name_only_identity] | — | 3283 ✓ |
| draftSharksIdp | draftSharks | ds_combined_cross_market | 156→510 | 1.0 | 1677 ✓ | 1677 **DROPPED** | 1677 ✓ [voting_name_only_identity] | 1677 ✓ [voting_name_only_identity] | 1677 ✓ | 1677 ✓ [voting_name_only_identity] | 1677 **DROPPED** | 1677 ✓ [voting_name_only_identity] | 1677 ✓ | 1677 ✓ |
| fantasyProsIdp | fantasyPros | exact | 102→426 | 0.1752 | 1868 ✓ | 1868 **DROPPED** | 1868 ✓ | 1868 ✓ | 1868 ✓ | 1868 ✓ | 1868 **DROPPED** | 1868 ✓ | 1868 ✓ | 1868 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 201→201 | 0.0 | 2840 stale(w=0) | 2840 stale(w=0) | 2840 stale(w=0) | 2840 stale(w=0) | 2840 stale(w=0) | 2840 stale(w=0) | 2840 stale(w=0) | 2840 stale(w=0) | 2840 stale(w=0) | 2840 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 174→174 | 0.8135 | 3396 ✓ | 3396 ✓ | 3396 ✓ | 3396 ✓ | 3396 ✓ | 3396 ✓ | 3396 ✓ | 3396 ✓ | 3396 ✓ | 3396 ✓ |

Why V2 keeps the votes the incumbent removed in B: draftSharksIdp 1677: incumbent drop in B; in C status=voting, identity=NAME_ONLY, V2 reason=voting_name_only_identity | fantasyProsIdp 1868: incumbent drop in B; in C status=voting, identity=VERIFIED, V2 reason=voting

#### Will Anderson (DL, HOU, idp)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 4395 | 84 | low | medium/high/medium/high/low | 3 | - |
| B | 5980 | 38 | medium | medium/medium/medium/high/high | 3 | draftSharksIdp |
| C | 4449 | 83 | low | medium/high/medium/high/low | 4 | - |
| D | 4395 | 84 | low | medium/high/medium/high/low | 3 | - |
| B' | 4395 | 84 | low | medium/high/medium/high/low | 3 | - |
| C' | 4395 | 84 | low | medium/high/medium/high/low | 3 | - |
| B'' | 5980 | 38 | medium | medium/medium/medium/high/high | 3 | draftSharksIdp |
| C'' | 4449 | 83 | low | medium/high/medium/high/low | 4 | - |
| Anf | 4395 | 84 | low | medium/high/medium/high/low | 3 | - |
| Bnf | 4449 | 83 | low | medium/high/medium/high/low | 4 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfIdp | dlf | exact | 1→29 | 1.0 | — | 6227 ✓ | 6227 ✓ [voting_name_only_identity] | — | — | — | 6227 ✓ | 6227 ✓ [voting_name_only_identity] | — | 6227 ✓ |
| draftSharksIdp | draftSharks | ds_combined_cross_market | 33→196 | 1.0 | 2878 ✓ | 2878 **DROPPED** | 2878 ✓ [kept_dissent] | 2878 ✓ [kept_dissent] | 2878 ✓ | 2878 ✓ [kept_dissent] | 2878 **DROPPED** | 2878 ✓ [kept_dissent] | 2878 ✓ | 2878 ✓ |
| fantasyProsIdp | fantasyPros | exact | 2→41 | 0.1752 | 5603 ✓ | 5603 ✓ | 5603 ✓ | 5603 ✓ | 5603 ✓ | 5603 ✓ | 5603 ✓ | 5603 ✓ | 5603 ✓ | 5603 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 87→87 | 0.0 | 4225 stale(w=0) | 4225 stale(w=0) | 4225 stale(w=0) | 4225 stale(w=0) | 4225 stale(w=0) | 4225 stale(w=0) | 4225 stale(w=0) | 4225 stale(w=0) | 4225 stale(w=0) | 4225 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 41→41 | 0.8135 | 5963 ✓ | 5963 ✓ | 5963 ✓ | 5963 ✓ | 5963 ✓ | 5963 ✓ | 5963 ✓ | 5963 ✓ | 5963 ✓ | 5963 ✓ |

Why V2 keeps the votes the incumbent removed in B: draftSharksIdp 2878: incumbent drop in B; in C status=voting, identity=NAME_ONLY, V2 reason=kept_dissent

#### Danielle Hunter (DL, HOU, idp)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 2352 | 261 | low | medium/high/medium/high/low | 3 | - |
| B | 3035 | 173 | medium | medium/medium/medium/high/high | 3 | draftSharksIdp |
| C | 2328 | 266 | low | medium/high/medium/high/low | 4 | - |
| D | 2352 | 261 | low | medium/high/medium/high/low | 3 | - |
| B' | 2352 | 260 | low | medium/high/medium/high/low | 3 | - |
| C' | 2352 | 260 | low | medium/high/medium/high/low | 3 | - |
| B'' | 3035 | 173 | medium | medium/medium/medium/high/high | 3 | draftSharksIdp |
| C'' | 2328 | 266 | low | medium/high/medium/high/low | 4 | - |
| Anf | 2352 | 261 | low | medium/high/medium/high/low | 3 | - |
| Bnf | 2328 | 266 | low | medium/high/medium/high/low | 4 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfIdp | dlf | exact | 46→221 | 1.0 | — | 2702 ✓ | 2702 ✓ [voting_name_only_identity] | — | — | — | 2702 ✓ | 2702 ✓ [voting_name_only_identity] | — | 2702 ✓ |
| draftSharksIdp | draftSharks | ds_combined_cross_market | 179→528 | 1.0 | 1643 ✓ | 1643 **DROPPED** | 1643 ✓ [voting_name_only_identity] | 1643 ✓ [voting_name_only_identity] | 1643 ✓ | 1643 ✓ [voting_name_only_identity] | 1643 **DROPPED** | 1643 ✓ [voting_name_only_identity] | 1643 ✓ | 1643 ✓ |
| fantasyProsIdp | fantasyPros | exact | 35→183 | 0.1752 | 2982 ✓ | 2982 ✓ | 2982 ✓ | 2982 ✓ | 2982 ✓ | 2982 ✓ | 2982 ✓ | 2982 ✓ | 2982 ✓ | 2982 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 213→213 | 0.0 | 2755 stale(w=0) | 2755 stale(w=0) | 2755 stale(w=0) | 2755 stale(w=0) | 2755 stale(w=0) | 2755 stale(w=0) | 2755 stale(w=0) | 2755 stale(w=0) | 2755 stale(w=0) | 2755 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 221→221 | 0.8135 | 3068 ✓ | 3068 ✓ | 3068 ✓ | 3068 ✓ | 3068 ✓ | 3068 ✓ | 3068 ✓ | 3068 ✓ | 3068 ✓ | 3068 ✓ |

Why V2 keeps the votes the incumbent removed in B: draftSharksIdp 1643: incumbent drop in B; in C status=voting, identity=NAME_ONLY, V2 reason=voting_name_only_identity

#### Jared Verse (DL, CLE, idp)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 2672 | 212 | medium | medium/high/medium/high/high | 3 | - |
| B | 2672 | 214 | medium | medium/medium/medium/high/high | 3 | dlfIdp |
| C | 2835 | 189 | low | medium/high/medium/high/low | 4 | - |
| D | 2672 | 212 | medium | medium/high/medium/high/high | 3 | - |
| B' | 2672 | 211 | medium | medium/high/medium/high/high | 3 | - |
| C' | 2672 | 212 | medium | medium/high/medium/high/high | 3 | - |
| B'' | 2672 | 213 | medium | medium/medium/medium/high/high | 3 | dlfIdp |
| C'' | 2835 | 189 | low | medium/high/medium/high/low | 4 | - |
| Anf | 2672 | 212 | medium | medium/high/medium/high/high | 3 | - |
| Bnf | 2835 | 189 | low | medium/high/medium/high/low | 4 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfIdp | dlf | exact | 10→68 | 1.0 | — | 4671 **DROPPED** | 4671 ✓ [voting_name_only_identity] | — | — | — | 4671 **DROPPED** | 4671 ✓ [voting_name_only_identity] | — | 4671 ✓ |
| draftSharksIdp | draftSharks | ds_combined_cross_market | 45→271 | 1.0 | 2419 ✓ | 2419 ✓ | 2419 ✓ [voting_name_only_identity] | 2419 ✓ [voting_name_only_identity] | 2419 ✓ | 2419 ✓ [voting_name_only_identity] | 2419 ✓ | 2419 ✓ [voting_name_only_identity] | 2419 ✓ | 2419 ✓ |
| fantasyProsIdp | fantasyPros | exact | 42→212 | 0.1752 | 2762 ✓ | 2762 ✓ | 2762 ✓ | 2762 ✓ | 2762 ✓ | 2762 ✓ | 2762 ✓ | 2762 ✓ | 2762 ✓ | 2762 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 108→108 | 0.0 | 3844 stale(w=0) | 3844 stale(w=0) | 3844 stale(w=0) | 3844 stale(w=0) | 3844 stale(w=0) | 3844 stale(w=0) | 3844 stale(w=0) | 3844 stale(w=0) | 3844 stale(w=0) | 3844 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 242→242 | 0.8135 | 2963 ✓ | 2963 ✓ | 2963 ✓ | 2963 ✓ | 2963 ✓ | 2963 ✓ | 2963 ✓ | 2963 ✓ | 2963 ✓ | 2963 ✓ |

Why V2 keeps the votes the incumbent removed in B: dlfIdp 4671: incumbent drop in B; in C status=voting, identity=NAME_ONLY, V2 reason=voting_name_only_identity

#### Theo Johnson (TE, NYG, offense)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 2164 | 295 | low | high/high/high/medium/low | 13 | - |
| B | 2164 | 288 | low | high/high/high/medium/low | 13 | - |
| C | 2165 | 292 | low | high/high/high/medium/low | 13 | - |
| D | 2165 | 295 | low | high/high/high/medium/low | 13 | - |
| B' | 2053 | 315 | low | high/high/high/medium/low | 13 | - |
| C' | 2054 | 315 | low | high/high/high/medium/low | 13 | - |
| B'' | 2053 | 310 | low | high/high/high/medium/low | 13 | - |
| C'' | 2054 | 316 | low | high/high/high/medium/low | 13 | - |
| Anf | 2164 | 295 | low | high/high/high/medium/low | 13 | - |
| Bnf | 2164 | 292 | low | high/high/high/medium/low | 13 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfSf | dlf | direct | 242→242 | 1.0 | 2278 ✓ | 2278 ✓ | 2278 ✓ [voting_name_only_identity] | 2278 ✓ [voting_name_only_identity] | 2278 ✓ | 2278 ✓ [voting_name_only_identity] | 2278 ✓ | 2278 ✓ [voting_name_only_identity] | 2278 ✓ | 2278 ✓ |
| dlfValuesSfTep | dlf | direct | 272→272 | 0.5 | — | — | — | — | 1597 ✓ | 1597 ✓ | 1597 ✓ | 1597 ✓ | — | — |
| draftSharks | draftSharks | ds_combined_cross_market | 163→216 | 1.0 | 3009 ✓ | 3009 ✓ | 3009 ✓ [voting_name_only_identity] | 3009 ✓ [voting_name_only_identity] | 3009 ✓ | 3009 ✓ [voting_name_only_identity] | 3009 ✓ | 3009 ✓ [voting_name_only_identity] | 3009 ✓ | 3009 ✓ |
| dynastyDaddySf | dynastyDaddySf | direct | 348→348 | 1.0 | 1722 ✓ | 1722 ✓ | 1722 ✓ [voting_name_only_identity] | 1722 ✓ [voting_name_only_identity] | 1722 ✓ | 1722 ✓ [voting_name_only_identity] | 1722 ✓ | 1722 ✓ [voting_name_only_identity] | 1722 ✓ | 1722 ✓ |
| dynastyNerdsSfTep | dynastyNerdsSfTep | direct | 250→250 | 1.0 | 1730 ✓ | 1730 ✓ | 1730 ✓ | 1730 ✓ | 1730 ✓ | 1730 ✓ | 1730 ✓ | 1730 ✓ | 1730 ✓ | 1730 ✓ |
| fantasyCalc | fantasyCalc | direct | 314→314 | 1.0 | 1865 ✓ | 1865 ✓ | 1865 ✓ [voting_name_only_identity] | 1865 ✓ [voting_name_only_identity] | 1865 ✓ | 1865 ✓ [voting_name_only_identity] | 1865 ✓ | 1865 ✓ [voting_name_only_identity] | 1865 ✓ | 1865 ✓ |
| fantasyNavigatorSf | ktcCrowd | direct | 236→236 | 0.0 | 2323 stale(w=0) | 2323 stale(w=0) | 2323 stale(w=0) | 2323 stale(w=0) | 2323 stale(w=0) | 2323 stale(w=0) | 2323 stale(w=0) | 2323 stale(w=0) | 2323 stale(w=0) | 2323 stale(w=0) |
| fantasyProsSf | fantasyPros | direct | 246→246 | 1.0 | 2250 ✓ | 2250 ✓ | 2250 ✓ | 2250 ✓ | 2250 ✓ | 2250 ✓ | 2250 ✓ | 2250 ✓ | 2250 ✓ | 2250 ✓ |
| flockFantasySf | flockFantasy | direct | 241→241 | 1.0 | 2286 ✓ | 2286 ✓ | 2286 ✓ [voting_name_only_identity] | 2286 ✓ [voting_name_only_identity] | 2286 ✓ | 2286 ✓ [voting_name_only_identity] | 2286 ✓ | 2286 ✓ [voting_name_only_identity] | 2286 ✓ | 2286 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 377→378 | 0.0 | 2714 stale(w=0) | 2714 stale(w=0) | 2714 stale(w=0) | 2714 stale(w=0) | 2714 stale(w=0) | 2714 stale(w=0) | 2714 stale(w=0) | 2714 stale(w=0) | 2714 stale(w=0) | 2714 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 343→343 | 0.8661 | 2458 ✓ | 2458 ✓ | 2458 ✓ | 2458 ✓ | 2458 ✓ | 2458 ✓ | 2458 ✓ | 2458 ✓ | 2458 ✓ | 2458 ✓ |
| ktcCrowdSfTep | ktcCrowd | direct | 241→241 | 1.0 | 2399 ✓ | 2399 ✓ | 2399 ✓ [voting_name_only_identity] | 2399 ✓ [voting_name_only_identity] | 2399 ✓ | 2399 ✓ [voting_name_only_identity] | 2399 ✓ | 2399 ✓ [voting_name_only_identity] | 2399 ✓ | 2399 ✓ |
| ktcTradesSfTep | ktcTrades | direct | 189→189 | 1.0 | 2721 ✓ | 2721 ✓ | 2721 ✓ [voting_name_only_identity] | 2721 ✓ [voting_name_only_identity] | 2721 ✓ | 2721 ✓ [voting_name_only_identity] | 2721 ✓ | 2721 ✓ [voting_name_only_identity] | 2721 ✓ | 2721 ✓ |
| otcffbSf | otcffbSf | direct | 345→345 | 1.0 | 1733 ✓ | 1733 ✓ | 1737 ✓ [voting_name_only_identity] | 1737 ✓ [voting_name_only_identity] | 1733 ✓ | 1737 ✓ [voting_name_only_identity] | 1733 ✓ | 1737 ✓ [voting_name_only_identity] | 1733 ✓ | 1733 ✓ |
| pfkDynasty | pfkDynasty | direct | 344→344 | 1.0 | 1737 ✓ | 1737 ✓ | 1737 ✓ | 1737 ✓ | 1737 ✓ | 1737 ✓ | 1737 ✓ | 1737 ✓ | 1737 ✓ | 1737 ✓ |
| yahooBoone | yahooBoone | direct | 261→261 | 1.0 | 1661 ✓ | 1661 ✓ | 1661 ✓ [voting_name_only_identity] | 1661 ✓ [voting_name_only_identity] | 1661 ✓ | 1661 ✓ [voting_name_only_identity] | 1661 ✓ | 1661 ✓ [voting_name_only_identity] | 1661 ✓ | 1661 ✓ |

#### Travis Hunter (WR, JAX, offense)

| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |
|---|---|---|---|---|---|---|
| A | 3599 | 130 | low | high/medium/high/high/low | 10 | idpTradeCalc |
| B | 3493 | 132 | low | high/medium/high/high/low | 10 | idpTradeCalc |
| C | 3493 | 136 | low | high/high/high/high/low | 11 | - |
| D | 3599 | 130 | low | high/high/high/high/low | 11 | - |
| B' | 3599 | 130 | low | high/medium/high/high/low | 10 | idpTradeCalc |
| C' | 3599 | 130 | low | high/high/high/high/low | 11 | - |
| B'' | 3493 | 132 | low | high/medium/high/high/low | 10 | idpTradeCalc |
| C'' | 3493 | 136 | low | high/high/high/high/low | 11 | - |
| Anf | 3599 | 130 | low | high/high/high/high/low | 11 | - |
| Bnf | 3493 | 136 | low | high/high/high/high/low | 11 | - |

| source | family | method | raw→eff rank | applied weight | A | B | C | D | B' | C' | B'' | C'' | Anf | Bnf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlfSf | dlf | direct | 138→138 | 1.0 | 2659 ✓ | 2659 ✓ | 2659 ✓ [voting_name_only_identity] | 2659 ✓ [voting_name_only_identity] | 2659 ✓ | 2659 ✓ [voting_name_only_identity] | 2659 ✓ | 2659 ✓ [voting_name_only_identity] | 2659 ✓ | 2659 ✓ |
| dlfValuesSfTep | dlf | direct | 179→179 | 0.5 | — | — | — | — | 2132 ✓ | 2132 ✓ | 2132 ✓ | 2132 ✓ | — | — |
| draftSharks | draftSharks | ds_combined_cross_market | 145→193 | 1.0 | 2901 ✓ | 2901 ✓ | 2901 ✓ [voting_name_only_identity] | 2901 ✓ [voting_name_only_identity] | 2901 ✓ | 2901 ✓ [voting_name_only_identity] | 2901 ✓ | 2901 ✓ [voting_name_only_identity] | 2901 ✓ | 2901 ✓ |
| dynastyNerdsSfTep | dynastyNerdsSfTep | direct | 172→172 | 1.0 | 2207 ✓ | 2207 ✓ | 2207 ✓ | 2207 ✓ | 2207 ✓ | 2207 ✓ | 2207 ✓ | 2207 ✓ | 2207 ✓ | 2207 ✓ |
| fantasyCalc | fantasyCalc | direct | 162→162 | 1.0 | 2324 ✓ | 2324 ✓ | 2324 ✓ [voting_name_only_identity] | 2324 ✓ [voting_name_only_identity] | 2324 ✓ | 2324 ✓ [voting_name_only_identity] | 2324 ✓ | 2324 ✓ [voting_name_only_identity] | 2324 ✓ | 2324 ✓ |
| fantasyNavigatorSf | ktcCrowd | direct | 161→161 | 0.0 | 2337 stale(w=0) | 2337 stale(w=0) | 2337 stale(w=0) | 2337 stale(w=0) | 2337 stale(w=0) | 2337 stale(w=0) | 2337 stale(w=0) | 2337 stale(w=0) | 2337 stale(w=0) | 2337 stale(w=0) |
| fantasyProsFitzmaurice | fantasyPros | direct | 225→225 | 0.5 | 1735 ✓ | 1735 ✓ | 1742 ✓ | 1742 ✓ | 1735 ✓ | 1742 ✓ | 1735 ✓ | 1742 ✓ | 1735 ✓ | 1735 ✓ |
| fantasyProsSf | fantasyPros | direct | 180→180 | 0.5 | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ |
| flockFantasySf | flockFantasy | direct | 125→125 | 1.0 | 2881 ✓ | 2881 ✓ | 2881 ✓ [voting_name_only_identity] | 2881 ✓ [voting_name_only_identity] | 2881 ✓ | 2881 ✓ [voting_name_only_identity] | 2881 ✓ | 2881 ✓ [voting_name_only_identity] | 2881 ✓ | 2881 ✓ |
| idpShowCombined | idpShow | csv_combined_cross_market | 109→109 | 0.0 | 3828 stale(w=0) | 3828 stale(w=0) | 3828 stale(w=0) | 3828 stale(w=0) | 3828 stale(w=0) | 3828 stale(w=0) | 3828 stale(w=0) | 3828 stale(w=0) | 3828 stale(w=0) | 3828 stale(w=0) |
| idpTradeCalc | idpTradeCalc | direct | 147→147 | 0.8661 | 3599 **DROPPED** | 3599 **DROPPED** | 3599 ✓ | 3599 ✓ | 3599 **DROPPED** | 3599 ✓ | 3599 **DROPPED** | 3599 ✓ | 3599 ✓ | 3599 ✓ |
| ktcCrowdSfTep | ktcCrowd | direct | 260→260 | 1.0 | 2166 ✓ | 2166 ✓ | 2166 ✓ [voting_name_only_identity] | 2166 ✓ [voting_name_only_identity] | 2166 ✓ | 2166 ✓ [voting_name_only_identity] | 2166 ✓ | 2166 ✓ [voting_name_only_identity] | 2166 ✓ | 2166 ✓ |
| ktcTradesSfTep | ktcTrades | direct | 213→213 | 1.0 | 2603 ✓ | 2603 ✓ | 2603 ✓ [voting_name_only_identity] | 2603 ✓ [voting_name_only_identity] | 2603 ✓ | 2603 ✓ [voting_name_only_identity] | 2603 ✓ | 2603 ✓ [voting_name_only_identity] | 2603 ✓ | 2603 ✓ |
| pfkDynasty | pfkDynasty | direct | 180→180 | 1.0 | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ | 2121 ✓ |
| yahooBoone | yahooBoone | direct | 207→207 | 1.0 | 1872 ✓ | 1872 ✓ | 1872 ✓ [voting_name_only_identity] | 1872 ✓ [voting_name_only_identity] | 1872 ✓ | 1872 ✓ [voting_name_only_identity] | 1872 ✓ | 1872 ✓ [voting_name_only_identity] | 1872 ✓ | 1872 ✓ |

Why V2 keeps the votes the incumbent removed in B: idpTradeCalc 3599: incumbent drop in B; in C status=voting, identity=None, V2 reason=voting

