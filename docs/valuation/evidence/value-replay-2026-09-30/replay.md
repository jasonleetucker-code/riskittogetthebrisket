# Value replay

- Code revision: `7ef1782cec4b9692167bc092c4f71a0bb2fa71c0` (source tree dirty: False)
- Payload: `exports\latest\dynasty_data_2026-09-30.json` sha256 `69a0f4b4e26486c1…`, scrape `2026-09-30T13:04:04.598312+00:00`
- Flags: {'source_freshness_weighting': True, 'source_family_cap': True, 'te_basis_conversion': True}; outlier filter {'k': 2.75, 'minN': 4, 'minThreshold': 1000.0}; single-source retention 0.3
- 30 source CSVs and 24 freshness-state files hashed in the JSON.

> Counterfactual deltas are single-change sensitivities through a nonlinear pipeline; they are not additive contribution shares.

## Jalen Coker (WR, offense)

Value **3286**, overall rank 156, position rank 45, confidence high. Outlier-dropped: ['ktcCrowdSfTep', 'ktcTradesSfTep']. Blend check: reproduced.

| source | native | rank | contribution | path | applied weight | freshness | family adj | excluded |
|---|---|---|---|---|---|---|---|---|
| ktcCrowdSfTep | 4620 | 83 | 4620 | value_direct | 1.0 | None | None | outlier |
| ktcTradesSfTep | 4184 | 90 | 4493 | value_direct | 1.0 | None | None | outlier |
| pfkDynasty | 991400 | 86 | 3809 | rank_hill | 1.0 | None | 1.0 |  |
| draftSharks | 17 | 119 | 3677 | rank_hill | 1.0 | None | 1.0 |  |
| dynastyDaddySf | 990900 | 91 | 3661 | rank_hill | 1.0 | None | 1.0 |  |
| fantasyCalc | 990800 | 92 | 3632 | rank_hill | 1.0 | None | 1.0 |  |
| otcffbSf | 990300 | 97 | 3496 | rank_hill | 1.0 | None | 1.0 |  |
| fantasyProsSf | 989400 | 106 | 3274 | rank_hill | 0.5 | None | 0.5 |  |
| idpTradeCalc | 3249 | 195 | 3250 | value_direct | 0.9827 | 0.9827 | 1.0 |  |
| flockFantasySf | 987837 | 108 | 3228 | rank_hill | 1.0 | None | 1.0 |  |
| fantasyNavigatorSf | 988900 | 110 | 3183 | rank_hill | 1.0 | None | 1.0 |  |
| dlfSf | 988050 | 114 | 3097 | rank_hill | 1.0 | None | 1.0 |  |
| yahooBoone | 988200 | 118 | 3015 | rank_hill | 1.0 | None | 1.0 |  |
| idpShowCombined | 981500 | 185 | 2965 | rank_hill | 0.0568 | 0.0568 | 1.0 |  |
| fantasyProsFitzmaurice | 987300 | 127 | 2844 | rank_hill | 0.5 | None | 0.5 |  |
| dynastyNerdsSfTep | 985100 | 149 | 2495 | rank_hill | 1.0 | None | 1.0 |  |

Counterfactual sensitivities (value delta, rank after):

- `native_values_as_ranks`: +158 → 3444 (rank 121)
- `hampel_off`: +120 → 3406 (rank 145)
- `leave_out_source:dynastyNerdsSfTep`: +31 → 3317 (rank 157)
- `leave_out_source:pfkDynasty`: -26 → 3260 (rank 157)
- `leave_out_source:draftSharks`: -25 → 3261 (rank 163)
- `leave_out_family:draftSharks`: -25 → 3261 (rank 161)
- `leave_out_source:dynastyDaddySf`: -24 → 3262 (rank 157)
- `leave_out_source:fantasyCalc`: -23 → 3263 (rank 156)
- `leave_out_source:yahooBoone`: +22 → 3308 (rank 156)
- `freshness_weighting_off`: -20 → 3266 (rank 161)
- `leave_out_source:dlfSf`: +18 → 3304 (rank 155)
- `leave_out_family:dlf`: +18 → 3304 (rank 158)
- `leave_out_source:fantasyProsFitzmaurice`: +17 → 3303 (rank 155)
- `leave_out_source:fantasyProsSf`: -15 → 3271 (rank 156)
- `leave_out_source:otcffbSf`: -15 → 3271 (rank 157)
- `leave_out_family:fantasyPros`: +15 → 3301 (rank 158)
- `leave_out_source:fantasyNavigatorSf`: +13 → 3299 (rank 154)
- `leave_out_family:ktcCrowd`: +13 → 3299 (rank 154)
- `leave_out_source:flockFantasySf`: +11 → 3297 (rank 156)
- `leave_out_family:flockFantasy`: +11 → 3297 (rank 156)
- `leave_out_source:draftSharksIdp`: +8 → 3294 (rank 160)
- `leave_out_source:idpTradeCalc`: +3 → 3289 (rank 160)
- `leave_out_source:idpShowCombined`: +2 → 3288 (rank 160)

## Brock Purdy (QB, offense)

Value **6786**, overall rank 28, position rank 11, confidence high. Outlier-dropped: ['pfkDynasty', 'fantasyProsSf']. Blend check: reproduced.

| source | native | rank | contribution | path | applied weight | freshness | family adj | excluded |
|---|---|---|---|---|---|---|---|---|
| fantasyProsSf | 998400 | 16 | 8084 | rank_hill | 1.0 | None | None | outlier |
| pfkDynasty | 998400 | 16 | 8084 | rank_hill | 1.0 | None | None | outlier |
| fantasyCalc | 997900 | 21 | 7540 | rank_hill | 1.0 | None | 1.0 |  |
| flockFantasySf | 997437 | 22 | 7439 | rank_hill | 1.0 | None | 1.0 |  |
| yahooBoone | 997800 | 22 | 7439 | rank_hill | 1.0 | None | 1.0 |  |
| dlfSf | 997050 | 27 | 6962 | rank_hill | 1.0 | None | 1.0 |  |
| ktcTradesSfTep | 6353 | 28 | 6822 | value_direct | 1.0 | None | 1.0 |  |
| fantasyProsFitzmaurice | 997100 | 29 | 6785 | rank_hill | 1.0 | None | 1.0 |  |
| ktcCrowdSfTep | 6740 | 23 | 6740 | value_direct | 0.5 | None | 0.5 |  |
| dynastyDaddySf | 997000 | 30 | 6699 | rank_hill | 1.0 | None | 1.0 |  |
| fantasyNavigatorSf | 997000 | 30 | 6699 | rank_hill | 0.5 | None | 0.5 |  |
| otcffbSf | 997000 | 30 | 6699 | rank_hill | 1.0 | None | 1.0 |  |
| draftSharks | 41 | 25 | 6485 | rank_hill | 1.0 | None | 1.0 |  |
| dynastyNerdsSfTep | 996300 | 37 | 6149 | rank_hill | 1.0 | None | 1.0 |  |
| idpShowCombined | 996700 | 33 | 5997 | rank_hill | 0.0568 | 0.0568 | 1.0 |  |
| idpTradeCalc | 5634 | 53 | 5635 | value_direct | 0.9827 | 0.9827 | 1.0 |  |

Counterfactual sensitivities (value delta, rank after):

- `native_values_as_ranks`: +198 → 6984 (rank 27)
- `leave_out_source:fantasyProsFitzmaurice`: +123 → 6909 (rank 27)
- `leave_out_source:draftSharks`: +116 → 6902 (rank 28)
- `leave_out_family:draftSharks`: +116 → 6902 (rank 28)
- `leave_out_source:dynastyDaddySf`: +106 → 6892 (rank 27)
- `leave_out_source:otcffbSf`: +106 → 6892 (rank 27)
- `leave_out_family:ktcCrowd`: +105 → 6891 (rank 26)
- `leave_out_source:dynastyNerdsSfTep`: +87 → 6873 (rank 27)
- `leave_out_source:fantasyNavigatorSf`: +86 → 6872 (rank 26)
- `hampel_off`: +84 → 6870 (rank 28)
- `leave_out_source:ktcCrowdSfTep`: +84 → 6870 (rank 27)
- `leave_out_source:ktcTradesSfTep`: +69 → 6855 (rank 28)
- `leave_out_source:dlfSf`: +62 → 6848 (rank 28)
- `leave_out_family:dlf`: +62 → 6848 (rank 28)
- `freshness_weighting_off`: -55 → 6731 (rank 31)
- `leave_out_source:idpShowCombined`: +53 → 6839 (rank 28)
- `leave_out_source:fantasyProsSf`: +50 → 6836 (rank 27)
- `leave_out_source:idpTradeCalc`: +50 → 6836 (rank 29)
- `leave_out_source:pfkDynasty`: +50 → 6836 (rank 28)
- `leave_out_family:fantasyPros`: -21 → 6765 (rank 29)
- `leave_out_source:flockFantasySf`: +5 → 6791 (rank 27)
- `leave_out_source:yahooBoone`: +5 → 6791 (rank 29)
- `leave_out_family:flockFantasy`: +5 → 6791 (rank 27)
- `leave_out_source:fantasyCalc`: +4 → 6790 (rank 27)
- `leave_out_source:draftSharksIdp`: +3 → 6789 (rank 28)

## Tua Tagovailoa (QB, offense)

Value **2228**, overall rank 285, position rank 33, confidence medium. Outlier-dropped: none. Blend check: reproduced.

| source | native | rank | contribution | path | applied weight | freshness | family adj | excluded |
|---|---|---|---|---|---|---|---|---|
| idpShowCombined | 979400 | 206 | 2804 | rank_hill | 0.0568 | 0.0568 | 1.0 |  |
| fantasyProsSf | 986500 | 135 | 2707 | rank_hill | 0.5 | None | 0.5 |  |
| fantasyNavigatorSf | 986200 | 137 | 2675 | rank_hill | 0.5 | None | 0.5 |  |
| ktcTradesSfTep | 2473 | 218 | 2656 | value_direct | 1.0 | None | 1.0 |  |
| dlfSf | 984100 | 157 | 2387 | rank_hill | 1.0 | None | 1.0 |  |
| fantasyProsFitzmaurice | 984000 | 160 | 2349 | rank_hill | 0.5 | None | 0.5 |  |
| idpTradeCalc | 2339 | 330 | 2339 | value_direct | 0.9827 | 0.9827 | 1.0 |  |
| flockFantasySf | 980071 | 163 | 2312 | rank_hill | 1.0 | None | 1.0 |  |
| dynastyNerdsSfTep | 983500 | 165 | 2288 | rank_hill | 1.0 | None | 1.0 |  |
| draftSharks | 9 | 306 | 2261 | rank_hill | 1.0 | None | 1.0 |  |
| pfkDynasty | 982600 | 174 | 2185 | rank_hill | 1.0 | None | 1.0 |  |
| otcffbSf | 981300 | 187 | 2051 | rank_hill | 1.0 | None | 1.0 |  |
| ktcCrowdSfTep | 1825 | 317 | 1825 | value_direct | 0.5 | None | 0.5 |  |
| dynastyDaddySf | 977800 | 222 | 1756 | rank_hill | 1.0 | None | 1.0 |  |
| fantasyCalc | 976900 | 231 | 1693 | rank_hill | 1.0 | None | 1.0 |  |
| yahooBoone | 972300 | 277 | 1427 | rank_hill | 1.0 | None | 1.0 |  |

Counterfactual sensitivities (value delta, rank after):

- `native_values_as_ranks`: -168 → 2060 (rank 265)
- `leave_out_source:yahooBoone`: +32 → 2260 (rank 283)
- `leave_out_source:ktcTradesSfTep`: -30 → 2198 (rank 286)
- `leave_out_source:fantasyCalc`: +29 → 2257 (rank 283)
- `freshness_weighting_off`: +27 → 2255 (rank 289)
- `leave_out_source:dynastyDaddySf`: +26 → 2254 (rank 283)
- `leave_out_source:fantasyNavigatorSf`: -25 → 2203 (rank 291)
- `leave_out_source:ktcCrowdSfTep`: +25 → 2253 (rank 281)
- `leave_out_source:draftSharksIdp`: +24 → 2252 (rank 276)
- `leave_out_family:fantasyPros`: -23 → 2205 (rank 292)
- `leave_out_source:dlfSf`: -17 → 2211 (rank 288)
- `leave_out_family:dlf`: -17 → 2211 (rank 293)
- `leave_out_source:idpTradeCalc`: -15 → 2213 (rank 291)
- `leave_out_source:flockFantasySf`: -14 → 2214 (rank 289)
- `leave_out_family:flockFantasy`: -14 → 2214 (rank 288)
- `leave_out_source:dynastyNerdsSfTep`: -13 → 2215 (rank 291)
- `leave_out_source:otcffbSf`: +12 → 2240 (rank 286)
- `leave_out_source:fantasyProsFitzmaurice`: +8 → 2236 (rank 285)
- `leave_out_source:fantasyProsSf`: -7 → 2221 (rank 288)
- `leave_out_source:pfkDynasty`: +6 → 2234 (rank 286)
- `leave_out_family:ktcCrowd`: -3 → 2225 (rank 282)
- `leave_out_source:draftSharks`: +2 → 2230 (rank 306)
- `leave_out_family:draftSharks`: +2 → 2230 (rank 279)
- `leave_out_source:idpShowCombined`: -1 → 2227 (rank 282)

## Cam Ward (QB, offense)

Value **4164**, overall rank 98, position rank 22, confidence high. Outlier-dropped: none. Blend check: reproduced.

| source | native | rank | contribution | path | applied weight | freshness | family adj | excluded |
|---|---|---|---|---|---|---|---|---|
| idpTradeCalc | 4768 | 96 | 4769 | value_direct | 0.9827 | 0.9827 | 1.0 |  |
| yahooBoone | 993800 | 62 | 4707 | rank_hill | 1.0 | None | 1.0 |  |
| ktcTradesSfTep | 4342 | 87 | 4663 | value_direct | 1.0 | None | 1.0 |  |
| idpShowCombined | 993100 | 69 | 4645 | rank_hill | 0.0568 | 0.0568 | 1.0 |  |
| dynastyDaddySf | 993000 | 70 | 4368 | rank_hill | 1.0 | None | 1.0 |  |
| dynastyNerdsSfTep | 992600 | 74 | 4215 | rank_hill | 1.0 | None | 1.0 |  |
| otcffbSf | 992600 | 74 | 4215 | rank_hill | 1.0 | None | 1.0 |  |
| fantasyProsFitzmaurice | 992500 | 75 | 4178 | rank_hill | 0.5 | None | 0.5 |  |
| fantasyProsSf | 992400 | 76 | 4142 | rank_hill | 0.5 | None | 0.5 |  |
| fantasyNavigatorSf | 992100 | 79 | 4037 | rank_hill | 0.5 | None | 0.5 |  |
| pfkDynasty | 992100 | 79 | 4037 | rank_hill | 1.0 | None | 1.0 |  |
| fantasyCalc | 991700 | 83 | 3904 | rank_hill | 1.0 | None | 1.0 |  |
| flockFantasySf | 990700 | 85 | 3840 | rank_hill | 1.0 | None | 1.0 |  |
| draftSharks | 17 | 111 | 3796 | rank_hill | 1.0 | None | 1.0 |  |
| dlfSf | 991367 | 88 | 3749 | rank_hill | 1.0 | None | 1.0 |  |
| ktcCrowdSfTep | 3702 | 110 | 3702 | value_direct | 0.5 | None | 0.5 |  |

Counterfactual sensitivities (value delta, rank after):

- `native_values_as_ranks`: -130 → 4034 (rank 92)
- `leave_out_source:idpTradeCalc`: -60 → 4104 (rank 106)
- `leave_out_source:yahooBoone`: -60 → 4104 (rank 100)
- `leave_out_source:ktcTradesSfTep`: -58 → 4106 (rank 99)
- `leave_out_source:dynastyDaddySf`: -44 → 4120 (rank 99)
- `leave_out_source:dlfSf`: +38 → 4202 (rank 97)
- `leave_out_family:dlf`: +38 → 4202 (rank 99)
- `leave_out_source:dynastyNerdsSfTep`: -37 → 4127 (rank 100)
- `leave_out_source:otcffbSf`: -37 → 4127 (rank 99)
- `freshness_weighting_off`: +36 → 4200 (rank 98)
- `leave_out_source:draftSharks`: +36 → 4200 (rank 100)
- `leave_out_family:draftSharks`: +36 → 4200 (rank 96)
- `leave_out_source:flockFantasySf`: +34 → 4198 (rank 97)
- `leave_out_family:flockFantasy`: +34 → 4198 (rank 97)
- `leave_out_source:fantasyCalc`: +31 → 4195 (rank 95)
- `leave_out_family:ktcCrowd`: +31 → 4195 (rank 95)
- `leave_out_source:draftSharksIdp`: +29 → 4193 (rank 98)
- `leave_out_source:pfkDynasty`: +25 → 4189 (rank 97)
- `leave_out_family:fantasyPros`: -15 → 4149 (rank 99)
- `leave_out_source:fantasyProsFitzmaurice`: -11 → 4153 (rank 98)
- `leave_out_source:fantasyProsSf`: +9 → 4173 (rank 96)
- `leave_out_source:fantasyNavigatorSf`: -7 → 4157 (rank 98)
- `leave_out_source:ktcCrowdSfTep`: +6 → 4170 (rank 96)
- `leave_out_source:idpShowCombined`: -2 → 4162 (rank 98)

## Travis Hunter (WR, offense)

Value **4024**, overall rank 105, position rank 31, confidence low. Outlier-dropped: ['idpTradeCalc', 'idpShowCombined', 'pfkDynasty']. Blend check: reproduced.

| source | native | rank | contribution | path | applied weight | freshness | family adj | excluded |
|---|---|---|---|---|---|---|---|---|
| idpTradeCalc | 5637 | 52 | 5638 | value_direct | 0.9827 | 0.9827 | None | outlier |
| idpShowCombined | 989100 | 109 | 3828 | rank_hill | 0.0568 | 0.0568 | None | outlier |
| flockFantasySf | 986012 | 122 | 2937 | rank_hill | 1.0 | None | 1.0 |  |
| ktcTradesSfTep | 2668 | 184 | 2865 | value_direct | 1.0 | None | 1.0 |  |
| draftSharks | 13 | 205 | 2811 | rank_hill | 1.0 | None | 1.0 |  |
| dlfSf | 986367 | 131 | 2774 | rank_hill | 1.0 | None | 1.0 |  |
| yahooBoone | 985900 | 141 | 2613 | rank_hill | 1.0 | None | 1.0 |  |
| fantasyProsFitzmaurice | 985400 | 146 | 2538 | rank_hill | 0.5 | None | 0.5 |  |
| dynastyNerdsSfTep | 985200 | 148 | 2509 | rank_hill | 1.0 | None | 1.0 |  |
| fantasyNavigatorSf | 983900 | 160 | 2349 | rank_hill | 0.5 | None | 0.5 |  |
| fantasyProsSf | 983100 | 169 | 2241 | rank_hill | 0.5 | None | 0.5 |  |
| ktcCrowdSfTep | 2233 | 258 | 2233 | value_direct | 0.5 | None | 0.5 |  |
| fantasyCalc | 981100 | 189 | 2032 | rank_hill | 1.0 | None | 1.0 |  |
| pfkDynasty | 971800 | 282 | 1403 | rank_hill | 1.0 | None | None | outlier |

Counterfactual sensitivities (value delta, rank after):

- `native_values_as_ranks`: -974 → 3050 (rank 148)
- `leave_out_source:draftSharks`: +447 → 4471 (rank 87)
- `leave_out_source:idpTradeCalc`: -250 → 3774 (rank 122)
- `leave_out_source:draftSharksIdp`: -212 → 3812 (rank 113)
- `leave_out_family:draftSharks`: -212 → 3812 (rank 112)
- `freshness_weighting_off`: +65 → 4089 (rank 100)
- `leave_out_family:dlf`: -50 → 3974 (rank 107)
- `leave_out_source:dlfIdp`: -30 → 3994 (rank 108)
- `leave_out_source:fantasyProsIdp`: -21 → 4003 (rank 107)
- `leave_out_family:fantasyPros`: -21 → 4003 (rank 108)
- `leave_out_source:idpShowCombined`: -3 → 4021 (rank 105)
- `leave_out_source:dlfRookieIdp`: -2 → 4022 (rank 105)

## Michael Mayer (TE, offense)

Value **2507**, overall rank 240, position rank 30, confidence medium. Outlier-dropped: ['draftSharks']. Blend check: reproduced.

| source | native | rank | contribution | path | applied weight | freshness | family adj | excluded |
|---|---|---|---|---|---|---|---|---|
| draftSharks | 16 | 142 | 3721 | rank_hill | 1.0 | None | None | outlier |
| ktcCrowdSfTep | 3343 | 134 | 3343 | value_direct | 0.5 | None | 0.5 |  |
| ktcTradesSfTep | 2945 | 156 | 3163 | value_direct | 1.0 | None | 1.0 |  |
| pfkDynasty | 983600 | 164 | 3047 | rank_hill | 1.0 | None | 1.0 |  |
| fantasyCalc | 981200 | 188 | 2756 | rank_hill | 1.0 | None | 1.0 |  |
| idpTradeCalc | 2503 | 304 | 2754 | value_direct | 0.9827 | 0.9827 | 1.0 |  |
| idpShowCombined | 962800 | 372 | 2735 | rank_hill | 0.0568 | 0.0568 | 1.0 |  |
| dynastyDaddySf | 979500 | 205 | 2584 | rank_hill | 1.0 | None | 1.0 |  |
| otcffbSf | 978700 | 213 | 2510 | rank_hill | 1.0 | None | 1.0 |  |
| fantasyNavigatorSf | 977200 | 227 | 2393 | rank_hill | 0.5 | None | 0.5 |  |
| dlfSf | 977483 | 235 | 2330 | rank_hill | 1.0 | None | 1.0 |  |
| fantasyProsSf | 976400 | 236 | 2323 | rank_hill | 0.5 | None | 0.5 |  |
| flockFantasySf | 973037 | 248 | 2237 | rank_hill | 1.0 | None | 1.0 |  |
| yahooBoone | 978100 | 219 | 1956 | rank_hill | 1.0 | None | 1.0 |  |
| fantasyProsFitzmaurice | 977200 | 228 | 1885 | rank_hill | 0.5 | None | 0.5 |  |
| dynastyNerdsSfTep | 976000 | 240 | 1797 | rank_hill | 1.0 | None | 1.0 |  |

Counterfactual sensitivities (value delta, rank after):

- `native_values_as_ranks`: -116 → 2391 (rank 214)
- `leave_out_source:ktcTradesSfTep`: -61 → 2446 (rank 247)
- `hampel_off`: +57 → 2564 (rank 234)
- `leave_out_source:pfkDynasty`: -56 → 2451 (rank 251)
- `leave_out_source:dynastyNerdsSfTep`: +52 → 2559 (rank 238)
- `leave_out_source:yahooBoone`: +49 → 2556 (rank 238)
- `leave_out_source:ktcCrowdSfTep`: -46 → 2461 (rank 246)
- `leave_out_source:fantasyCalc`: -41 → 2466 (rank 253)
- `leave_out_family:fantasyPros`: +41 → 2548 (rank 236)
- `leave_out_source:fantasyNavigatorSf`: +40 → 2547 (rank 239)
- `leave_out_source:idpTradeCalc`: -40 → 2467 (rank 234)
- `leave_out_source:flockFantasySf`: +34 → 2541 (rank 238)
- `leave_out_family:flockFantasy`: +34 → 2541 (rank 238)
- `leave_out_source:dynastyDaddySf`: -32 → 2475 (rank 249)
- `freshness_weighting_off`: +29 → 2536 (rank 240)
- `leave_out_source:dlfSf`: +29 → 2536 (rank 240)
- `leave_out_family:dlf`: +29 → 2536 (rank 238)
- `leave_out_family:ktcCrowd`: -14 → 2493 (rank 242)
- `leave_out_source:fantasyProsFitzmaurice`: +11 → 2518 (rank 239)
- `leave_out_source:fantasyProsSf`: -10 → 2497 (rank 242)
- `leave_out_source:otcffbSf`: -9 → 2498 (rank 242)

## Aidan Hutchinson (DL, idp)

Value **6411**, overall rank 34, position rank 1, confidence medium. Outlier-dropped: ['idpShowCombined', 'draftSharksIdp']. Blend check: not_applicable.

| source | native | rank | contribution | path | applied weight | freshness | family adj | excluded |
|---|---|---|---|---|---|---|---|---|
| idpTradeCalc | 6444 | 31 | 6445 | value_direct | 0.9827 | 0.9827 | 1.0 |  |
| dlfIdp | 999900 | 31 | 6108 | rank_hill | 1.0 | None | 1.0 |  |
| fantasyProsIdp | 999900 | 31 | 6108 | rank_hill | 1.0 | None | 1.0 |  |
| idpShowCombined | 992900 | 71 | 4592 | rank_hill | 0.0568 | 0.0568 | None | outlier |
| draftSharksIdp | 13 | 186 | 2957 | rank_hill | 1.0 | None | None | outlier |

Counterfactual sensitivities (value delta, rank after):

- `native_values_as_ranks`: -3863 → 2548 (rank 198)
- `leave_out_source:idpTradeCalc`: -2977 → 3434 (rank 147)
- `hampel_off`: -1602 → 4809 (rank 69)
- `leave_out_source:dlfIdp`: -1602 → 4809 (rank 71)
- `leave_out_source:fantasyProsIdp`: -1602 → 4809 (rank 71)
- `leave_out_family:dlf`: -1602 → 4809 (rank 68)
- `leave_out_family:fantasyPros`: -1602 → 4809 (rank 71)
- `leave_out_source:draftSharks`: -203 → 6208 (rank 39)

## Will Anderson (DL, idp)

Value **5928**, overall rank 42, position rank 2, confidence medium. Outlier-dropped: ['idpShowCombined', 'draftSharksIdp']. Blend check: not_applicable.

| source | native | rank | contribution | path | applied weight | freshness | family adj | excluded |
|---|---|---|---|---|---|---|---|---|
| idpTradeCalc | 5963 | 41 | 5964 | value_direct | 0.9827 | 0.9827 | 1.0 |  |
| dlfIdp | 999800 | 41 | 5603 | rank_hill | 1.0 | None | 1.0 |  |
| fantasyProsIdp | 999800 | 41 | 5603 | rank_hill | 1.0 | None | 1.0 |  |
| idpShowCombined | 991300 | 87 | 4225 | rank_hill | 0.0568 | 0.0568 | None | outlier |
| draftSharksIdp | 12 | 226 | 2670 | rank_hill | 1.0 | None | None | outlier |

Counterfactual sensitivities (value delta, rank after):

- `native_values_as_ranks`: -3570 → 2358 (rank 220)
- `leave_out_source:idpTradeCalc`: -2828 → 3100 (rank 167)
- `hampel_off`: -1513 → 4415 (rank 89)
- `leave_out_source:dlfIdp`: -1513 → 4415 (rank 91)
- `leave_out_source:fantasyProsIdp`: -1513 → 4415 (rank 91)
- `leave_out_family:dlf`: -1513 → 4415 (rank 90)
- `leave_out_family:fantasyPros`: -1513 → 4415 (rank 91)
- `leave_out_source:draftSharks`: -144 → 5784 (rank 45)

## Jeremiyah Love (RB, offense)

Value **7819**, overall rank 16, position rank 4, confidence high. Outlier-dropped: none. Blend check: reproduced.

| source | native | rank | contribution | path | applied weight | freshness | family adj | excluded |
|---|---|---|---|---|---|---|---|---|
| flockFantasySf | 998650 | 12 | 8561 | rank_hill | 0.6907 | None | 0.6907 |  |
| pfkDynasty | 998800 | 12 | 8561 | rank_hill | 1.0 | None | 1.0 |  |
| otcffbSf | 998700 | 13 | 8438 | rank_hill | 1.0 | None | 1.0 |  |
| dlfRookieSf | 999886 | 15 | 8199 | rank_hill | 0.5 | None | 0.5 |  |
| fantasyCalc | 998500 | 15 | 8199 | rank_hill | 1.0 | None | 1.0 |  |
| fantasyNavigatorSf | 998500 | 15 | 8199 | rank_hill | 0.5 | None | 0.5 |  |
| flockFantasySfRookies | 999900 | 15 | 8199 | rank_hill | 0.3093 | 0.6493 | 0.6907 |  |
| dynastyDaddySf | 998300 | 17 | 7970 | rank_hill | 1.0 | None | 1.0 |  |
| dynastyNerdsSfTep | 998200 | 18 | 7859 | rank_hill | 1.0 | None | 1.0 |  |
| fantasyProsSf | 998100 | 19 | 7751 | rank_hill | 0.5 | None | 0.5 |  |
| ktcTradesSfTep | 6923 | 17 | 7435 | value_direct | 1.0 | None | 1.0 |  |
| idpTradeCalc | 7369 | 19 | 7370 | value_direct | 0.9827 | 0.9827 | 1.0 |  |
| dlfSf | 997650 | 23 | 7339 | rank_hill | 0.5 | None | 0.5 |  |
| ktcCrowdSfTep | 7244 | 15 | 7244 | value_direct | 0.5 | None | 0.5 |  |
| idpShowCombined | 998400 | 16 | 7218 | rank_hill | 0.0568 | 0.0568 | 1.0 |  |
| fantasyProsFitzmaurice | 997400 | 26 | 7053 | rank_hill | 0.5 | None | 0.5 |  |
| draftSharks | 47 | 18 | 7032 | rank_hill | 1.0 | None | 1.0 |  |
| yahooBoone | 997200 | 28 | 6872 | rank_hill | 1.0 | None | 1.0 |  |

Counterfactual sensitivities (value delta, rank after):

- `native_values_as_ranks`: +222 → 8041 (rank 17)
- `leave_out_source:pfkDynasty`: -65 → 7754 (rank 18)
- `leave_out_source:yahooBoone`: +64 → 7883 (rank 16)
- `leave_out_source:draftSharks`: +62 → 7881 (rank 16)
- `leave_out_family:draftSharks`: +62 → 7881 (rank 16)
- `leave_out_family:flockFantasy`: -60 → 7759 (rank 16)
- `leave_out_source:otcffbSf`: -59 → 7760 (rank 17)
- `freshness_weighting_off`: -51 → 7768 (rank 16)
- `leave_out_source:fantasyNavigatorSf`: -49 → 7770 (rank 17)
- `leave_out_source:fantasyCalc`: -48 → 7771 (rank 18)
- `leave_out_source:dlfRookieSf`: -47 → 7772 (rank 17)
- `leave_out_source:dlfSf`: +45 → 7864 (rank 16)
- `leave_out_source:idpTradeCalc`: +45 → 7864 (rank 16)
- `leave_out_family:fantasyPros`: +45 → 7864 (rank 17)
- `leave_out_source:ktcTradesSfTep`: +43 → 7862 (rank 17)
- `leave_out_family:ktcCrowd`: -40 → 7779 (rank 17)
- `leave_out_source:dynastyDaddySf`: -37 → 7782 (rank 16)
- `leave_out_source:flockFantasySf`: -34 → 7785 (rank 16)
- `leave_out_source:fantasyProsFitzmaurice`: +16 → 7835 (rank 16)
- `leave_out_source:fantasyProsSf`: -15 → 7804 (rank 17)
- `leave_out_source:ktcCrowdSfTep`: +8 → 7827 (rank 17)
- `leave_out_source:dynastyNerdsSfTep`: -6 → 7813 (rank 16)
- `leave_out_source:flockFantasySfRookies`: +5 → 7824 (rank 16)
- `leave_out_source:idpShowCombined`: +2 → 7821 (rank 16)
- `leave_out_family:dlf`: +1 → 7820 (rank 16)

## Fernando Mendoza (QB, offense)

Value **5337**, overall rank 57, position rank 16, confidence high. Outlier-dropped: ['draftSharks']. Blend check: reproduced.

| source | native | rank | contribution | path | applied weight | freshness | family adj | excluded |
|---|---|---|---|---|---|---|---|---|
| fantasyProsFitzmaurice | 996100 | 39 | 6006 | rank_hill | 0.5 | None | 0.5 |  |
| flockFantasySf | 994950 | 46 | 5549 | rank_hill | 0.6907 | None | 0.6907 |  |
| ktcTradesSfTep | 5128 | 57 | 5507 | value_direct | 1.0 | None | 1.0 |  |
| yahooBoone | 995300 | 47 | 5488 | rank_hill | 1.0 | None | 1.0 |  |
| dynastyNerdsSfTep | 995200 | 48 | 5429 | rank_hill | 1.0 | None | 1.0 |  |
| idpTradeCalc | 5397 | 66 | 5398 | value_direct | 0.9827 | 0.9827 | 1.0 |  |
| fantasyProsSf | 995100 | 49 | 5371 | rank_hill | 0.5 | None | 0.5 |  |
| otcffbSf | 995100 | 49 | 5371 | rank_hill | 1.0 | None | 1.0 |  |
| pfkDynasty | 995100 | 49 | 5371 | rank_hill | 1.0 | None | 1.0 |  |
| ktcCrowdSfTep | 5229 | 59 | 5229 | value_direct | 0.5 | None | 0.5 |  |
| fantasyCalc | 994800 | 52 | 5203 | rank_hill | 1.0 | None | 1.0 |  |
| dlfSf | 994683 | 53 | 5150 | rank_hill | 0.5 | None | 0.5 |  |
| dlfRookieSf | 999757 | 56 | 4994 | rank_hill | 0.5 | None | 0.5 |  |
| idpShowCombined | 993900 | 61 | 4871 | rank_hill | 0.0568 | 0.0568 | 1.0 |  |
| dynastyDaddySf | 994100 | 59 | 4847 | rank_hill | 1.0 | None | 1.0 |  |
| fantasyNavigatorSf | 994100 | 59 | 4847 | rank_hill | 0.5 | None | 0.5 |  |
| flockFantasySfRookies | 999700 | 59 | 4847 | rank_hill | 0.3093 | 0.6493 | 0.6907 |  |
| draftSharks | 20 | 90 | 4164 | rank_hill | 1.0 | None | None | outlier |

Counterfactual sensitivities (value delta, rank after):

- `native_values_as_ranks`: -153 → 5184 (rank 55)
- `leave_out_family:ktcCrowd`: +37 → 5374 (rank 55)
- `hampel_off`: -28 → 5309 (rank 56)
- `leave_out_source:draftSharksIdp`: -24 → 5313 (rank 58)
- `freshness_weighting_off`: -23 → 5314 (rank 57)
- `leave_out_source:dynastyDaddySf`: +23 → 5360 (rank 57)
- `leave_out_family:dlf`: +12 → 5349 (rank 56)
- `leave_out_source:flockFantasySf`: -11 → 5326 (rank 58)
- `leave_out_source:ktcTradesSfTep`: -11 → 5326 (rank 58)
- `leave_out_source:fantasyProsSf`: +10 → 5347 (rank 57)
- `leave_out_source:flockFantasySfRookies`: +10 → 5347 (rank 57)
- `leave_out_source:yahooBoone`: -10 → 5327 (rank 57)
- `leave_out_source:fantasyNavigatorSf`: +9 → 5346 (rank 57)
- `leave_out_family:fantasyPros`: -8 → 5329 (rank 56)
- `leave_out_source:dynastyNerdsSfTep`: -7 → 5330 (rank 58)
- `leave_out_source:ktcCrowdSfTep`: +6 → 5343 (rank 56)
- `leave_out_source:fantasyCalc`: +5 → 5342 (rank 57)
- `leave_out_source:idpTradeCalc`: -5 → 5332 (rank 58)
- `leave_out_source:dlfRookieSf`: +4 → 5341 (rank 57)
- `leave_out_source:dlfSf`: -4 → 5333 (rank 58)
- `leave_out_source:fantasyProsFitzmaurice`: -4 → 5333 (rank 58)
- `leave_out_source:otcffbSf`: -4 → 5333 (rank 57)
- `leave_out_source:pfkDynasty`: -4 → 5333 (rank 58)
- `leave_out_source:idpShowCombined`: +1 → 5338 (rank 57)
- `leave_out_family:flockFantasy`: -1 → 5336 (rank 58)

## 2027 Round 1 (PICK, pick)

Value **5643**, overall rank None, position rank None, confidence low. Outlier-dropped: none. Blend check: not_applicable.

| source | native | rank | contribution | path | applied weight | freshness | family adj | excluded |
|---|---|---|---|---|---|---|---|---|

Counterfactual sensitivities (value delta, rank after):

- `leave_out_source:ktcCrowdSfTep`: -323 → 5320 (rank None)
- `leave_out_source:ktcTradesSfTep`: +323 → 5966 (rank None)
- `leave_out_family:ktcCrowd`: -323 → 5320 (rank None)
- `native_values_as_ranks`: -291 → 5352 (rank None)
- `freshness_weighting_off`: +108 → 5751 (rank None)
- `leave_out_source:idpTradeCalc`: -10 → 5633 (rank None)

## Whole-board counterfactual effects

| counterfactual | kind | rows changed | top-200 membership changes |
|---|---|---|---|
| `hampel_off` | diagnostic_patch | 115 | 8 |
| `native_values_as_ranks` | diagnostic_patch | 910 | 34 |
| `freshness_weighting_off` | feature_flag | 768 | 10 |
| `leave_out_source:dlfIdp` | source_override | 161 | 2 |
| `leave_out_source:dlfRookieIdp` | source_override | 29 | 0 |
| `leave_out_source:dlfRookieSf` | source_override | 53 | 0 |
| `leave_out_source:dlfSf` | source_override | 268 | 2 |
| `leave_out_source:draftSharks` | source_override | 631 | 30 |
| `leave_out_source:draftSharksIdp` | source_override | 613 | 24 |
| `leave_out_source:dynastyDaddySf` | source_override | 377 | 2 |
| `leave_out_source:dynastyNerdsSfTep` | source_override | 287 | 4 |
| `leave_out_source:fantasyCalc` | source_override | 383 | 2 |
| `leave_out_source:fantasyNavigatorSf` | source_override | 433 | 4 |
| `leave_out_source:fantasyProsFitzmaurice` | source_override | 279 | 4 |
| `leave_out_source:fantasyProsIdp` | source_override | 234 | 8 |
| `leave_out_source:fantasyProsSf` | source_override | 367 | 2 |
| `leave_out_source:flockFantasySf` | source_override | 399 | 2 |
| `leave_out_source:flockFantasySfRookies` | source_override | 43 | 0 |
| `leave_out_source:idpShowCombined` | source_override | 606 | 2 |
| `leave_out_source:idpTradeCalc` | source_override | 831 | 18 |
| `leave_out_source:ktcCrowdSfTep` | source_override | 519 | 4 |
| `leave_out_source:ktcTradesSfTep` | source_override | 531 | 6 |
| `leave_out_source:otcffbSf` | source_override | 368 | 6 |
| `leave_out_source:pfkDynasty` | source_override | 445 | 2 |
| `leave_out_source:yahooBoone` | source_override | 373 | 4 |
| `leave_out_family:dlf` | source_override | 472 | 6 |
| `leave_out_family:draftSharks` | source_override | 614 | 24 |
| `leave_out_family:fantasyPros` | source_override | 618 | 8 |
| `leave_out_family:flockFantasy` | source_override | 400 | 4 |
| `leave_out_family:ktcCrowd` | source_override | 530 | 4 |

Outlier-filter drops by source: {'draftSharks': 45, 'draftSharksIdp': 22, 'fantasyProsIdp': 13, 'yahooBoone': 13, 'pfkDynasty': 10, 'ktcCrowdSfTep': 10, 'idpShowCombined': 9, 'dlfSf': 7, 'fantasyProsSf': 6, 'dynastyNerdsSfTep': 5, 'idpTradeCalc': 5, 'fantasyNavigatorSf': 4, 'fantasyProsFitzmaurice': 3, 'fantasyCalc': 2, 'ktcTradesSfTep': 2, 'dynastyDaddySf': 2, 'dlfIdp': 1, 'otcffbSf': 1, 'flockFantasySf': 1}.

