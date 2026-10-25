# Board tables, pin2015

Payload sha256 `3ef54acda8c1062f96d02692fc22ea8ebc7e8f9bc38168359efac60675119199`. Status: pre_freeze_provisional_thresholds_no_history (V2 thresholds `provisional_stage1`, history lane `override_empty`).

## Comparison summary

Exclusion changes count other sources' observations only; the DLF boards' own added votes are listed in the next section.

| pair | what it isolates | exclusion changes | offense moves: rows / p90 / max | IDP moves: rows / p90 / max | pick moves: rows / max | confidence bucket changes | rank change ≥ 25 | material rows |
|---|---|---|---|---|---|---|---|---|
| B vs A | DLF IDP restored, incumbent filter (the documented defect) | voting -> filter_dropped: 31 | 1 / 0.0% / 2.9% | 180 / 4.0% / 54.4% | 39 / 7.4% | 55 | 32 | 43 |
| C vs A | DLF IDP restored + V2 vs production | filter_dropped -> voting: 99; freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 1; voting -> v2_refused:identity_unresolved:team_only_mismatch: 4 | 190 / 0.9% / 34.6% | 180 / 2.8% / 6.7% | 51 / 4.7% | 60 | 18 | 25 |
| C vs B | V2 vs incumbent, both with DLF IDP restored | filter_dropped -> voting: 131; freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 1; voting -> v2_refused:identity_unresolved:team_only_mismatch: 4 | 189 / 0.9% / 34.6% | 31 / 0.0% / 118.8% | 40 / 8.1% | 29 | 22 | 32 |
| D vs A | V2 alone, DLF IDP still held (isolates the filter change) | filter_dropped -> voting: 99; freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 1; voting -> v2_refused:identity_unresolved:team_only_mismatch: 4 | 189 / 0.9% / 34.6% | 0 / 0.0% / 0.0% | 25 / 3.1% | 14 | 4 | 7 |
| B' vs A | D4 on, incumbent (the D4 defect) | filter_dropped -> voting: 11; voting -> filter_dropped: 20 | 306 / 1.2% / 4.8% | 0 / 0.0% / 0.0% | 43 / 2.2% | 24 | 3 | 3 |
| C' vs A | D4 on + V2 vs production | filter_dropped -> voting: 99; freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 1; voting -> v2_refused:identity_unresolved:team_only_mismatch: 4 | 351 / 1.6% / 34.6% | 0 / 0.0% / 0.0% | 50 / 4.1% | 28 | 6 | 9 |
| C' vs B' | V2 vs incumbent, both with D4 on | filter_dropped -> voting: 109; freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 1; voting -> v2_refused:identity_unresolved:team_only_mismatch: 6 | 194 / 1.1% / 34.6% | 0 / 0.0% / 0.0% | 25 / 2.4% | 18 | 6 | 9 |
| B'' vs A | DLF IDP restored + D4 on, incumbent | filter_dropped -> voting: 11; voting -> filter_dropped: 51 | 307 / 1.2% / 4.8% | 180 / 4.0% / 54.4% | 64 / 7.4% | 79 | 35 | 45 |
| C'' vs A | DLF IDP restored + D4 on + V2 vs production | filter_dropped -> voting: 99; freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 1; voting -> v2_refused:identity_unresolved:team_only_mismatch: 4 | 352 / 1.7% / 34.6% | 180 / 2.8% / 6.7% | 66 / 4.7% | 74 | 19 | 26 |
| C'' vs B'' | V2 vs incumbent, both with DLF IDP restored + D4 on | filter_dropped -> voting: 141; freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 1; voting -> v2_refused:identity_unresolved:team_only_mismatch: 6 | 194 / 1.1% / 34.6% | 31 / 0.0% / 118.8% | 43 / 7.7% | 33 | 22 | 32 |
| C vs D | DLF IDP activation impact with V2 already on | none | 1 / 0.0% / 2.9% | 180 / 2.8% / 6.7% | 38 / 4.7% | 46 | 13 | 17 |
| C' vs D | D4 activation impact with V2 already on | none | 302 / 1.1% / 4.4% | 0 / 0.0% / 0.0% | 43 / 1.5% | 16 | 2 | 2 |
| C'' vs D | DLF IDP + D4 activation impact with V2 already on | none | 303 / 1.1% / 4.4% | 180 / 2.8% / 6.7% | 65 / 4.7% | 62 | 15 | 19 |
| C vs Bnf | V2 vs no per-row filter (same flags): every V2 refusal/drop | freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 1; voting -> v2_refused:identity_unresolved:team_only_mismatch: 4 | 124 / 0.1% / 3.8% | 0 / 0.0% / 0.0% | 11 / 0.1% | 2 | 1 | 1 |
| D vs Anf | V2 vs no per-row filter (DLF held) | freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 1; voting -> v2_refused:identity_unresolved:team_only_mismatch: 4 | 124 / 0.1% / 3.8% | 0 / 0.0% / 0.0% | 12 / 0.1% | 2 | 1 | 1 |
| C' vs B'nf | V2 vs no per-row filter (D4 on) | freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 1; voting -> v2_refused:identity_unresolved:team_only_mismatch: 6 | 124 / 0.1% / 3.8% | 0 / 0.0% / 0.0% | 13 / 0.1% | 1 | 1 | 1 |
| C'' vs B''nf | V2 vs no per-row filter (DLF restored + D4 on) | freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 1; voting -> v2_refused:identity_unresolved:team_only_mismatch: 6 | 124 / 0.1% / 3.8% | 0 / 0.0% / 0.0% | 13 / 0.1% | 1 | 1 | 1 |

## Flag-added observations (the DLF boards' own votes)

* B vs A: dlfIdp 171 (filter_dropped: 1, voting: 170); dlfRookieIdp 29 (voting: 29)
* C vs A: dlfIdp 171 (voting: 171); dlfRookieIdp 29 (voting: 29); dlfValuesSfTep 2 (v2_refused:identity_unresolved:team_only_mismatch: 2)
* D vs A: dlfValuesSfTep 2 (v2_refused:identity_unresolved:team_only_mismatch: 2)
* B' vs A: dlfValuesSfTep 319 (filter_dropped: 1, voting: 318)
* C' vs A: dlfValuesSfTep 319 (v2_refused:identity_unresolved:team_only_mismatch: 2, voting: 317)
* B'' vs A: dlfIdp 171 (filter_dropped: 1, voting: 170); dlfRookieIdp 29 (voting: 29); dlfValuesSfTep 319 (filter_dropped: 1, voting: 318)
* C'' vs A: dlfIdp 171 (voting: 171); dlfRookieIdp 29 (voting: 29); dlfValuesSfTep 319 (v2_refused:identity_unresolved:team_only_mismatch: 2, voting: 317)

## The 31 regression votes: dropped in B 31/31; retained in C 31/31, C″ 31/31, D 31/31

Layer C distance `u` is V2's own coordinate (ln(10 + 500·p)); a vote is a Layer C drop candidate only beyond τ_C (provisional ln 6 = 1.792; grid floor ln 4 = 1.386). `< ln 2` = another provider within 2x, so not even dissent.

| row | source | vote | A row | B row (vote) | C row (vote) | C″ | identity (Layer A) | V2 reason | Layer C nearest-provider distance (u) | nearest other vote, ln value |
|---|---|---|---|---|---|---|---|---|---|---|
| Aidan Hutchinson | draftSharksIdp | 3200 | 4772.0 | 6422.0 (DROPPED (incumbent)) | 4772.0 (voting) | voting | NAME_ONLY | kept_dissent | 0.9248 | 0.6657 |
| Alex Singleton | fantasyProsIdp | 3283 | 1949.0 | 1817.0 (DROPPED (incumbent)) | 1836.0 (voting) | voting | VERIFIED | voting | < ln 2 | 0.5138 |
| Anthony Hill | fantasyProsIdp | 1794 | 2649.0 | 2774.0 (DROPPED (incumbent)) | 2765.0 (voting) | voting | VERIFIED | voting | < ln 2 | 0.2331 |
| Barrett Carter | draftSharksIdp | 3721 | 2884.0 | 2047.0 (DROPPED (incumbent)) | 2893.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.5932 |
| CJ Allen | draftSharksIdp | 5790 | 3987.0 | 2172.0 (DROPPED (incumbent)) | 4033.0 (voting) | voting | NAME_ONLY | kept_dissent | 1.0216 | 0.7835 |
| Carson Schwesinger | draftSharksIdp | 6945 | 6219.0 | 5584.0 (DROPPED (incumbent)) | 6249.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.2087 |
| Chase Young | idpTradeCalc | 3200 | 2534.0 | 2118.0 (DROPPED (incumbent)) | 2533.0 (voting) | voting | none (value-direct source) | voting | < ln 2 | 0.4019 |
| Danielle Hunter | draftSharksIdp | 1641 | 2333.0 | 3035.0 (DROPPED (incumbent)) | 2309.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.4987 |
| David Bailey | fantasyProsIdp | 2051 | 3482.0 | 3631.0 (DROPPED (incumbent)) | 3616.0 (voting) | voting | VERIFIED | voting | < ln 2 | 0.4936 |
| DeMarvion Overshown | draftSharksIdp | 3383 | 2774.0 | 2040.0 (DROPPED (incumbent)) | 2719.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.2909 |
| Dillon Thieneman | draftSharksIdp | 4353 | 3690.0 | 3205.0 (DROPPED (incumbent)) | 3759.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.2879 |
| Edgerrin Cooper | draftSharksIdp | 4645 | 3987.0 | 3293.0 (DROPPED (incumbent)) | 3983.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.317 |
| Jacob Rodriguez | fantasyProsIdp | 1578 | 4624.0 | 4961.0 (DROPPED (incumbent)) | 4932.0 (voting) | voting | VERIFIED | kept_dissent | 1.1726 | 1.0302 |
| Jihaad Campbell | draftSharksIdp | 4996 | 4217.0 | 3547.0 (DROPPED (incumbent)) | 4254.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.3263 |
| Jordyn Brooks | fantasyProsIdp | 5096 | 3905.0 | 3726.0 (DROPPED (incumbent)) | 3752.0 (voting) | voting | VERIFIED | voting | < ln 2 | 0.2652 |
| Josiah Trotter | fantasyProsIdp | 1868 | 2368.0 | 3379.0 (DROPPED (incumbent)) | 2493.0 (voting) | voting | VERIFIED | voting | < ln 2 | 0.1091 |
| Josiah Trotter | draftSharksIdp | 1675 | 2368.0 | 3379.0 (DROPPED (incumbent)) | 2493.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.1091 |
| Myles Garrett | draftSharksIdp | 1905 | 3555.0 | 5245.0 (DROPPED (incumbent)) | 3469.0 (voting) | voting | NAME_ONLY | kept_dissent | 0.7553 | 0.6695 |
| Nick Bolton | draftSharksIdp | 4698 | 4138.0 | 3588.0 (DROPPED (incumbent)) | 4141.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.2632 |
| Nick Emmanwori | draftSharksIdp | 4517 | 4020.0 | 3544.0 (DROPPED (incumbent)) | 4009.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.2264 |
| Nick Herbig | idpTradeCalc | 2999 | 2118.0 | 1553.0 (DROPPED (incumbent)) | 2137.0 (voting) | voting | none (value-direct source) | voting | < ln 2 | 0.4016 |
| Patrick Queen | draftSharksIdp | 3262 | 2623.0 | 1975.0 (DROPPED (incumbent)) | 2630.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.4842 |
| Quay Walker | draftSharksIdp | 4618 | 3905.0 | 3099.0 (DROPPED (incumbent)) | 3866.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.308 |
| Quincy Williams | fantasyProsIdp | 3171 | 2184.0 | 2065.0 (DROPPED (incumbent)) | 2082.0 (voting) | voting | VERIFIED | voting | < ln 2 | 0.3706 |
| Robert Spillane | fantasyProsIdp | 3294 | 2187.0 | 2054.0 (DROPPED (incumbent)) | 2073.0 (voting) | voting | VERIFIED | voting | < ln 2 | 0.4137 |
| Roquan Smith | fantasyProsIdp | 5165 | 3323.0 | 3143.0 (DROPPED (incumbent)) | 3169.0 (voting) | voting | VERIFIED | voting | < ln 2 | 0.3588 |
| Sonny Styles | fantasyProsIdp | 2901 | 5029.0 | 5236.0 (DROPPED (incumbent)) | 5218.0 (voting) | voting | VERIFIED | voting | < ln 2 | 0.3636 |
| T.J. Watt | draftSharksIdp | 1450 | 2394.0 | 3436.0 (DROPPED (incumbent)) | 2415.0 (voting) | voting | NAME_ONLY | kept_dissent | 0.789 | 0.738 |
| Trevin Wallace | draftSharksIdp | 2878 | 1937.0 | 884.0 (DROPPED (incumbent)) | 1934.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.6137 |
| Trey Hendrickson | idpTradeCalc | 2927 | 2086.0 | 1513.0 (DROPPED (incumbent)) | 2082.0 (voting) | voting | none (value-direct source) | voting | < ln 2 | 0.4237 |
| Will Anderson | draftSharksIdp | 2870 | 4354.0 | 5980.0 (DROPPED (incumbent)) | 4407.0 (voting) | voting | NAME_ONLY | kept_dissent | 0.8769 | 0.669 |

## D4 regression set by rule (B′ vs A): 20 votes on 14 rows; retained in C′ 20/20, C″ 20/20

| row | source | vote | A row | B′ row | DLF Values vote | C′ row (status, V2 reason) | C″ status |
|---|---|---|---|---|---|---|---|
| Ashton Jeanty | ktcCrowdSfTep | 6971 | 8080.0 | 8163.0 | 8199 | 8041.0 (voting, voting_name_only_identity) | voting |
| Brock Purdy | idpTradeCalc | 6439 | 7466.0 | 7455.0 | 7859 | 7473.0 (voting, voting) | voting |
| Brock Purdy | yahooBoone | 8561 | 7466.0 | 7455.0 | 7859 | 7473.0 (voting, voting_name_only_identity) | voting |
| CeeDee Lamb | idpTradeCalc | 7343 | 8402.0 | 8435.0 | 8561 | 8263.0 (voting, voting) | voting |
| Courtland Sutton | draftSharks | 3453 | 2412.0 | 2357.0 | 2387 | 2385.0 (voting, voting_name_only_identity) | voting |
| Dak Prescott | yahooBoone | 7146 | 5845.0 | 5775.0 | 6223 | 5912.0 (voting, voting_name_only_identity) | voting |
| Evan Engram | draftSharks | 3109 | 2165.0 | 2082.0 | 1916 | 2117.0 (voting, voting_name_only_identity) | voting |
| Harold Fannin | yahooBoone | 4441 | 5368.0 | 5426.0 | 5845 | 5369.0 (voting, voting_name_only_identity) | voting |
| Isaiah Likely | ktcCrowdSfTep | 5773 | 4774.0 | 4674.0 | 4027 | 4773.0 (voting, voting_name_only_identity) | voting |
| Jalen Coker | ktcCrowdSfTep | 4761 | 3788.0 | 3750.0 | 3369 | 3791.0 (voting, voting_name_only_identity) | voting |
| Joe Burrow | draftSharks | 9486 | 8015.0 | 8066.0 | 8438 | 8014.0 (voting, voting_name_only_identity) | voting |
| Joe Burrow | fantasyProsSf | 9345 | 8015.0 | 8066.0 | 8438 | 8014.0 (voting, voting) | voting |
| Joe Burrow | idpTradeCalc | 7080 | 8015.0 | 8066.0 | 8438 | 8014.0 (voting, voting) | voting |
| Joe Burrow | ktcCrowdSfTep | 6833 | 8015.0 | 8066.0 | 8438 | 8014.0 (voting, voting_name_only_identity) | voting |
| Josh Cameron | draftSharks | 2633 | 1608.0 | 1531.0 | 1389 | 1611.0 (voting, voting_name_only_identity) | voting |
| Oscar Delp | draftSharks | 3218 | 2289.0 | 2264.0 | 1581 | 2289.0 (voting, voting_name_only_identity) | voting |
| Patrick Mahomes | fantasyProsFitzmaurice | 8687 | 7558.0 | 7662.0 | 7540 | 7548.0 (voting, voting) | voting |
| Patrick Mahomes | idpTradeCalc | 6402 | 7558.0 | 7662.0 | 7540 | 7548.0 (voting, voting) | voting |
| Patrick Mahomes | ktcCrowdSfTep | 6329 | 7558.0 | 7662.0 | 7540 | 7548.0 (voting, voting_name_only_identity) | voting |
| Puka Nacua | idpTradeCalc | 8033 | 9081.0 | 9107.0 | 9076 | 8973.0 (voting, voting) | voting |

## Original 30 %+ movers

| row | A | B | B vs A | C | C vs A | C″ | D | dropped in B | dropped in C |
|---|---|---|---|---|---|---|---|---|---|
| Trevin Wallace | 1937.0 | 884.0 | -54.4% | 1934.0 | -0.1% | 1934.0 | 1937.0 | draftSharksIdp | - |
| Myles Garrett | 3555.0 | 5245.0 | +47.5% | 3469.0 | -2.4% | 3469.0 | 3555.0 | draftSharksIdp | - |
| CJ Allen | 3987.0 | 2172.0 | -45.5% | 4033.0 | +1.1% | 4033.0 | 3987.0 | draftSharksIdp | - |
| T.J. Watt | 2394.0 | 3436.0 | +43.5% | 2415.0 | +0.9% | 2415.0 | 2394.0 | draftSharksIdp | - |
| Josiah Trotter | 2368.0 | 3379.0 | +42.7% | 2493.0 | +5.3% | 2493.0 | 2368.0 | fantasyProsIdp, draftSharksIdp | - |
| Will Anderson | 4354.0 | 5980.0 | +37.3% | 4407.0 | +1.2% | 4407.0 | 4354.0 | draftSharksIdp | - |
| Aidan Hutchinson | 4772.0 | 6422.0 | +34.6% | 4772.0 | +0.0% | 4772.0 | 4772.0 | draftSharksIdp | - |
| Danielle Hunter | 2333.0 | 3035.0 | +30.1% | 2309.0 | -1.0% | 2309.0 | 2333.0 | draftSharksIdp | - |

## Every V2 refusal / hold (any layer) on the V2 boards

| board | row | row team | source | V2 status / reason | category | vendor team | without V2 (status, vote) | row value no-filter → V2 |
|---|---|---|---|---|---|---|---|---|
| C | Byron Murphy | SEA | idpShowCombined | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | freshness_or_health_zero_weight, 2603 | 2503.0 → 2503.0 |
| C | Cole Payton | PHI | flockFantasySf | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | voting, 1527 | 1082.0 → 1041.0 |
| C | Jarquez Hunter | NO | dlfValuesSfTep | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIA | not_observed, None | 1273.0 → 1269.0 |
| C | Jarquez Hunter | NO | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIA | voting, 1473 | 1273.0 → 1269.0 |
| C | Jerome Ford | ARI | dlfValuesSfTep | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIN | not_observed, None | 1240.0 → 1241.0 |
| C | Joe Milton | PHI | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | DAL | voting, 1473 | 1435.0 → 1388.0 |
| C | Justin Jefferson | MIN | draftSharksIdp | refused / identity_contradicted:position_group | invalid_player_identity | - | not_observed, None | 7885.0 → 7885.0 |
| C | Justin Jefferson | MIN | idpShowCombined | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | freshness_or_health_zero_weight, 7531 | 7885.0 → 7885.0 |
| C | Kaytron Allen | MIA | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | WAS | voting, 1735 | 1799.0 → 1800.0 |
| C | Marvin Harrison | HOU | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | ARI | voting, 3118 | 3682.0 → 3691.0 |
| D | Byron Murphy | SEA | idpShowCombined | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | freshness_or_health_zero_weight, 2603 | 2417.0 → 2417.0 |
| D | Cole Payton | PHI | flockFantasySf | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | voting, 1527 | 1082.0 → 1041.0 |
| D | Jarquez Hunter | NO | dlfValuesSfTep | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIA | not_observed, None | 1273.0 → 1269.0 |
| D | Jarquez Hunter | NO | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIA | voting, 1473 | 1273.0 → 1269.0 |
| D | Jerome Ford | ARI | dlfValuesSfTep | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIN | not_observed, None | 1240.0 → 1241.0 |
| D | Joe Milton | PHI | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | DAL | voting, 1473 | 1435.0 → 1388.0 |
| D | Justin Jefferson | MIN | draftSharksIdp | refused / identity_contradicted:position_group | invalid_player_identity | - | not_observed, None | 7885.0 → 7885.0 |
| D | Justin Jefferson | MIN | idpShowCombined | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | freshness_or_health_zero_weight, 7531 | 7885.0 → 7885.0 |
| D | Kaytron Allen | MIA | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | WAS | voting, 1735 | 1799.0 → 1800.0 |
| D | Marvin Harrison | HOU | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | ARI | voting, 3118 | 3682.0 → 3691.0 |
| C' | Byron Murphy | SEA | idpShowCombined | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | freshness_or_health_zero_weight, 2603 | 2417.0 → 2417.0 |
| C' | Cole Payton | PHI | flockFantasySf | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | voting, 1527 | 1082.0 → 1041.0 |
| C' | Jarquez Hunter | NO | dlfValuesSfTep | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIA | voting, 1245 | 1269.0 → 1269.0 |
| C' | Jarquez Hunter | NO | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIA | voting, 1473 | 1269.0 → 1269.0 |
| C' | Jerome Ford | ARI | dlfValuesSfTep | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIN | voting, 1257 | 1232.0 → 1241.0 |
| C' | Joe Milton | PHI | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | DAL | voting, 1473 | 1435.0 → 1388.0 |
| C' | Justin Jefferson | MIN | draftSharksIdp | refused / identity_contradicted:position_group | invalid_player_identity | - | not_observed, None | 7881.0 → 7881.0 |
| C' | Justin Jefferson | MIN | idpShowCombined | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | freshness_or_health_zero_weight, 7531 | 7881.0 → 7881.0 |
| C' | Kaytron Allen | MIA | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | WAS | voting, 1735 | 1798.0 → 1799.0 |
| C' | Marvin Harrison | HOU | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | ARI | voting, 3118 | 3673.0 → 3681.0 |
| C'' | Byron Murphy | SEA | idpShowCombined | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | freshness_or_health_zero_weight, 2603 | 2503.0 → 2503.0 |
| C'' | Cole Payton | PHI | flockFantasySf | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | voting, 1527 | 1082.0 → 1041.0 |
| C'' | Jarquez Hunter | NO | dlfValuesSfTep | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIA | voting, 1245 | 1269.0 → 1269.0 |
| C'' | Jarquez Hunter | NO | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIA | voting, 1473 | 1269.0 → 1269.0 |
| C'' | Jerome Ford | ARI | dlfValuesSfTep | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIN | voting, 1257 | 1232.0 → 1241.0 |
| C'' | Joe Milton | PHI | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | DAL | voting, 1473 | 1435.0 → 1388.0 |
| C'' | Justin Jefferson | MIN | draftSharksIdp | refused / identity_contradicted:position_group | invalid_player_identity | - | not_observed, None | 7881.0 → 7881.0 |
| C'' | Justin Jefferson | MIN | idpShowCombined | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | freshness_or_health_zero_weight, 7531 | 7881.0 → 7881.0 |
| C'' | Kaytron Allen | MIA | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | WAS | voting, 1735 | 1798.0 → 1799.0 |
| C'' | Marvin Harrison | HOU | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | ARI | voting, 3118 | 3673.0 → 3681.0 |

## The incumbent's own drops on A (99) and their fate under V2 (board D)

98 of 99 have another voting source within 2x (ln 2) on board D. Largest distances first (top 15; full list in the JSON):

| row | source | vote | V2 status / reason | nearest other vote (source, value, ln distance) | row A → D |
|---|---|---|---|---|---|
| LaJohntay Wester | flockFantasySf | 1889 | voting / kept_dissent | otcffbSf 900 (0.7414) | 648.0 → 872.0 |
| Reggie Virgil | draftSharks | 2084 | voting / voting_name_only_identity | fantasyCalc 1150 (0.5945) | 957.0 → 983.0 |
| Barion Brown | draftSharks | 2696 | voting / voting_name_only_identity | idpTradeCalc 1708 (0.4564) | 1244.0 → 1275.0 |
| Brenen Thompson | draftSharks | 2496 | voting / voting_name_only_identity | idpTradeCalc 1611 (0.4378) | 1370.0 → 1409.0 |
| Chris Brazzell | draftSharks | 3151 | voting / voting_name_only_identity | ktcTradesSfTep 2162 (0.3767) | 1745.0 → 1788.0 |
| Michael Penix | draftSharks | 5603 | voting / voting_name_only_identity | yahooBoone 3872 (0.3695) | 3388.0 → 3423.0 |
| Sam Roush | draftSharks | 2813 | voting / voting_name_only_identity | fantasyProsSf 1967 (0.3577) | 1690.0 → 1719.0 |
| Jaxson Dart | draftSharks | 3796 | voting / voting_name_only_identity | idpTradeCalc 5413 (0.3549) | 5956.0 → 5875.0 |
| Sam Darnold | draftSharks | 6703 | voting / voting_name_only_identity | yahooBoone 4799 (0.3341) | 3966.0 → 4024.0 |
| Malik Benson | draftSharks | 2304 | voting / voting_name_only_identity | idpTradeCalc 1661 (0.3272) | 1221.0 → 1274.0 |
| KaVontae Turpin | pfkDynasty | 2362 | voting / voting | draftSharks 1733 (0.3097) | 1159.0 → 1226.0 |
| Jaxon Smith-Njigba | draftSharks | 6861 | voting / kept_dissent | ktcTradesSfTep 9322 (0.3065) | 9645.0 → 9620.0 |
| Charlie Kolar | draftSharks | 2958 | voting / voting_name_only_identity | pfkDynasty 2182 (0.3043) | 1859.0 → 1895.0 |
| Nate Boerkircher | draftSharks | 2850 | voting / voting_name_only_identity | pfkDynasty 2119 (0.2964) | 1748.0 → 1789.0 |
| Brock Bowers | draftSharks | 6537 | voting / kept_dissent | fantasyProsSf 8757 (0.2924) | 9984.0 → 9917.0 |

## Two-way (Travis Hunter)

| board | published | alt (DB) family value | primary (offense) value | alt sources considered | alt-panel drops | row drops |
|---|---|---|---|---|---|---|
| A | 3599.0 | 3599 | 2323 | idpTradeCalc | - | idpTradeCalc |
| Anf | 3599.0 | 3599 | 2365 | idpTradeCalc | - | - |
| B | 3493.0 | 3493 | 2323 | dlfIdp, idpTradeCalc | - | idpTradeCalc |
| B' | 3599.0 | 3599 | 2306 | idpTradeCalc | - | idpTradeCalc |
| B'' | 3493.0 | 3493 | 2306 | dlfIdp, idpTradeCalc | - | idpTradeCalc |
| B''nf | 3493.0 | 3493 | 2331 | dlfIdp, idpTradeCalc | - | - |
| B'nf | 3599.0 | 3599 | 2331 | idpTradeCalc | - | - |
| Bnf | 3493.0 | 3493 | 2365 | dlfIdp, idpTradeCalc | - | - |
| C | 3493.0 | 3493 | 2365 | dlfIdp, idpTradeCalc | - | - |
| C' | 3599.0 | 3599 | 2331 | idpTradeCalc | - | - |
| C'' | 3493.0 | 3493 | 2331 | dlfIdp, idpTradeCalc | - | - |
| D | 3599.0 | 3599 | 2365 | idpTradeCalc | - | - |

## Picks

* B vs A: 39 pick rows move, by provenance {'rookie_pool_tether': 39}, max |Δ| 7.4% (largest: 2027 Pick 2.01 3947.0→3653.0, 2027 Pick 1.06 4709.0→4961.0, 2027 Pick 2.03 3569.0→3389.0, 2027 Pick 2.06 3354.0→3225.0)
* C vs A: 51 pick rows move, by provenance {'rookie_pool_tether': 51}, max |Δ| 4.7% (largest: 2027 Pick 1.06 4709.0→4932.0, 2027 Pick 2.04 3482.0→3616.0, 2027 Pick 1.05 5029.0→5199.0, 2027 Pick 1.01 7238.0→7462.0)
* C vs B: 40 pick rows move, by provenance {'rookie_pool_tether': 40}, max |Δ| 8.1% (largest: 2027 Pick 2.01 3653.0→3947.0, 2027 Pick 2.03 3389.0→3653.0, 2027 Pick 2.04 3379.0→3616.0, 2027 Pick 2.06 3225.0→3354.0)
* D vs A: 25 pick rows move, by provenance {'rookie_pool_tether': 25}, max |Δ| 3.1% (largest: 2027 Pick 1.01 7238.0→7462.0, 2027 Pick 6.01 1748.0→1788.0, 2027 Pick 6.02 1745.0→1783.0, 2027 Pick 5.08 1806.0→1841.0)
* C' vs A: 50 pick rows move, by provenance {'rookie_pool_tether': 50}, max |Δ| 4.1% (largest: 2027 Pick 1.01 7238.0→7536.0, 2027 Pick 6.01 1748.0→1789.0, 2027 Pick 6.02 1745.0→1785.0, 2027 Pick 5.10 1783.0→1807.0)
* C'' vs A: 66 pick rows move, by provenance {'rookie_pool_tether': 66}, max |Δ| 4.7% (largest: 2027 Pick 1.06 4709.0→4932.0, 2027 Pick 1.01 7238.0→7536.0, 2027 Pick 2.04 3482.0→3616.0, 2027 Pick 1.05 5029.0→5199.0)

