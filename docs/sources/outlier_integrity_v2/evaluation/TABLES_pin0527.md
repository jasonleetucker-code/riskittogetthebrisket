# Board tables, pin0527

Payload sha256 `b639608f68176b9a395527e6e9ea992e324baa75d997b8ea289e587e61eae11c`. Status: pre_freeze_provisional_thresholds_no_history (V2 thresholds `provisional_stage1`, history lane `override_empty`).

## Comparison summary

Exclusion changes count other sources' observations only; the DLF boards' own added votes are listed in the next section.

| pair | what it isolates | exclusion changes | offense moves: rows / p90 / max | IDP moves: rows / p90 / max | pick moves: rows / max | confidence bucket changes | rank change ≥ 25 | material rows |
|---|---|---|---|---|---|---|---|---|
| B vs A | DLF IDP restored, incumbent filter (the documented defect) | voting -> filter_dropped: 31 | 1 / 0.0% / 2.9% | 179 / 4.0% / 53.9% | 39 / 5.4% | 56 | 30 | 40 |
| C vs A | DLF IDP restored + V2 vs production | filter_dropped -> voting: 98; freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 2; voting -> v2_refused:identity_unresolved:team_only_mismatch: 4 | 241 / 1.0% / 35.6% | 179 / 2.7% / 6.7% | 53 / 3.8% | 63 | 11 | 19 |
| C vs B | V2 vs incumbent, both with DLF IDP restored | filter_dropped -> voting: 130; freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 2; voting -> v2_refused:identity_unresolved:team_only_mismatch: 4 | 240 / 1.0% / 35.6% | 31 / 0.0% / 116.4% | 48 / 8.4% | 31 | 20 | 31 |
| D vs A | V2 alone, DLF IDP still held (isolates the filter change) | filter_dropped -> voting: 98; freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 2; voting -> v2_refused:identity_unresolved:team_only_mismatch: 4 | 240 / 1.0% / 35.6% | 0 / 0.0% / 0.0% | 33 / 2.8% | 16 | 3 | 6 |
| B' vs A | D4 on, incumbent (the D4 defect) | filter_dropped -> voting: 12; voting -> filter_dropped: 20 | 301 / 1.2% / 5.1% | 0 / 0.0% / 0.0% | 38 / 1.9% | 22 | 2 | 3 |
| C' vs A | D4 on + V2 vs production | filter_dropped -> voting: 98; freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 2; voting -> v2_refused:identity_unresolved:team_only_mismatch: 4 | 394 / 1.7% / 35.6% | 0 / 0.0% / 0.0% | 54 / 4.2% | 28 | 7 | 11 |
| C' vs B' | V2 vs incumbent, both with D4 on | filter_dropped -> voting: 107; freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 2; voting -> v2_refused:identity_unresolved:team_only_mismatch: 6 | 245 / 1.0% / 35.6% | 0 / 0.0% / 0.0% | 33 / 2.2% | 22 | 3 | 6 |
| B'' vs A | DLF IDP restored + D4 on, incumbent | filter_dropped -> voting: 12; voting -> filter_dropped: 51 | 302 / 1.2% / 5.1% | 179 / 4.0% / 53.9% | 64 / 5.4% | 78 | 34 | 45 |
| C'' vs A | DLF IDP restored + D4 on + V2 vs production | filter_dropped -> voting: 98; freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 2; voting -> v2_refused:identity_unresolved:team_only_mismatch: 4 | 395 / 1.8% / 35.6% | 179 / 2.7% / 6.7% | 69 / 4.2% | 75 | 16 | 25 |
| C'' vs B'' | V2 vs incumbent, both with DLF IDP restored + D4 on | filter_dropped -> voting: 139; freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 2; voting -> v2_refused:identity_unresolved:team_only_mismatch: 6 | 245 / 1.0% / 35.6% | 31 / 0.0% / 116.4% | 47 / 8.6% | 37 | 19 | 30 |
| C vs D | DLF IDP activation impact with V2 already on | none | 1 / 0.0% / 2.9% | 179 / 2.7% / 6.7% | 38 / 3.8% | 47 | 10 | 15 |
| C' vs D | D4 activation impact with V2 already on | none | 301 / 1.0% / 5.1% | 0 / 0.0% / 0.0% | 39 / 1.3% | 14 | 3 | 4 |
| C'' vs D | DLF IDP + D4 activation impact with V2 already on | none | 302 / 1.0% / 5.1% | 179 / 2.7% / 6.7% | 64 / 3.8% | 61 | 13 | 19 |
| C vs Bnf | V2 vs no per-row filter (same flags): every V2 refusal/drop | freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 2; voting -> v2_refused:identity_unresolved:team_only_mismatch: 4 | 175 / 0.1% / 3.7% | 0 / 0.0% / 0.0% | 14 / 0.1% | 6 | 0 | 0 |
| D vs Anf | V2 vs no per-row filter (DLF held) | freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 2; voting -> v2_refused:identity_unresolved:team_only_mismatch: 4 | 175 / 0.1% / 3.7% | 0 / 0.0% / 0.0% | 14 / 0.1% | 6 | 0 | 0 |
| C' vs B'nf | V2 vs no per-row filter (D4 on) | freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 2; voting -> v2_refused:identity_unresolved:team_only_mismatch: 6 | 179 / 0.1% / 3.7% | 0 / 0.0% / 0.0% | 16 / 0.2% | 7 | 0 | 0 |
| C'' vs B''nf | V2 vs no per-row filter (DLF restored + D4 on) | freshness_or_health_zero_weight -> v2_refused:identity_unresolved:ambiguous_in_source: 2; not_observed -> v2_refused:identity_contradicted:position_group: 1; voting -> v2_refused:identity_unresolved:ambiguous_in_source: 2; voting -> v2_refused:identity_unresolved:team_only_mismatch: 6 | 179 / 0.1% / 3.7% | 0 / 0.0% / 0.0% | 16 / 0.2% | 7 | 0 | 0 |

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
| Aidan Hutchinson | draftSharksIdp | 3181 | 4802.0 | 6422.0 (DROPPED (incumbent)) | 4802.0 (voting) | voting | NAME_ONLY | kept_dissent | 0.9319 | 0.6717 |
| Alex Singleton | fantasyProsIdp | 3283 | 1953.0 | 1821.0 (DROPPED (incumbent)) | 1841.0 (voting) | voting | VERIFIED | voting | < ln 2 | 0.5138 |
| Anthony Hill | fantasyProsIdp | 1794 | 2662.0 | 2788.0 (DROPPED (incumbent)) | 2779.0 (voting) | voting | VERIFIED | voting | < ln 2 | 0.2331 |
| Barrett Carter | draftSharksIdp | 3721 | 2864.0 | 2047.0 (DROPPED (incumbent)) | 2873.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.5932 |
| CJ Allen | draftSharksIdp | 5741 | 3918.0 | 2172.0 (DROPPED (incumbent)) | 3964.0 (voting) | voting | NAME_ONLY | kept_dissent | 1.0079 | 0.775 |
| Carson Schwesinger | draftSharksIdp | 7032 | 6246.0 | 5584.0 (DROPPED (incumbent)) | 6276.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.2211 |
| Chase Young | idpTradeCalc | 3200 | 2547.0 | 2118.0 (DROPPED (incumbent)) | 2546.0 (voting) | voting | none (value-direct source) | voting | < ln 2 | 0.4019 |
| Danielle Hunter | draftSharksIdp | 1643 | 2352.0 | 3035.0 (DROPPED (incumbent)) | 2328.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.4975 |
| David Bailey | fantasyProsIdp | 2051 | 3556.0 | 3705.0 (DROPPED (incumbent)) | 3690.0 (voting) | voting | VERIFIED | voting | < ln 2 | 0.4936 |
| DeMarvion Overshown | draftSharksIdp | 3371 | 2752.0 | 2041.0 (DROPPED (incumbent)) | 2697.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.2874 |
| Dillon Thieneman | draftSharksIdp | 4331 | 3666.0 | 3204.0 (DROPPED (incumbent)) | 3734.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.2828 |
| Edgerrin Cooper | draftSharksIdp | 4618 | 3957.0 | 3293.0 (DROPPED (incumbent)) | 3953.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.3112 |
| Jacob Rodriguez | fantasyProsIdp | 1578 | 4617.0 | 4954.0 (DROPPED (incumbent)) | 4924.0 (voting) | voting | VERIFIED | kept_dissent | 1.1588 | 1.02 |
| Jihaad Campbell | draftSharksIdp | 4932 | 4168.0 | 3547.0 (DROPPED (incumbent)) | 4206.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.3134 |
| Jordyn Brooks | fantasyProsIdp | 5096 | 3910.0 | 3731.0 (DROPPED (incumbent)) | 3758.0 (voting) | voting | VERIFIED | voting | < ln 2 | 0.2608 |
| Josiah Trotter | fantasyProsIdp | 1868 | 2390.0 | 3379.0 (DROPPED (incumbent)) | 2514.0 (voting) | voting | VERIFIED | voting | < ln 2 | 0.1079 |
| Josiah Trotter | draftSharksIdp | 1677 | 2390.0 | 3379.0 (DROPPED (incumbent)) | 2514.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.1079 |
| Myles Garrett | draftSharksIdp | 1905 | 3597.0 | 5246.0 (DROPPED (incumbent)) | 3512.0 (voting) | voting | NAME_ONLY | kept_dissent | 0.7553 | 0.6695 |
| Nick Bolton | draftSharksIdp | 4783 | 4167.0 | 3588.0 (DROPPED (incumbent)) | 4170.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.2811 |
| Nick Emmanwori | draftSharksIdp | 4445 | 3973.0 | 3544.0 (DROPPED (incumbent)) | 3962.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.2103 |
| Nick Herbig | idpTradeCalc | 2999 | 2137.0 | 1554.0 (DROPPED (incumbent)) | 2156.0 (voting) | voting | none (value-direct source) | voting | < ln 2 | 0.4016 |
| Patrick Queen | draftSharksIdp | 3241 | 2597.0 | 1975.0 (DROPPED (incumbent)) | 2604.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.4777 |
| Quay Walker | draftSharksIdp | 4592 | 3874.0 | 3100.0 (DROPPED (incumbent)) | 3835.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.3023 |
| Quincy Williams | fantasyProsIdp | 3171 | 2179.0 | 2060.0 (DROPPED (incumbent)) | 2078.0 (voting) | voting | VERIFIED | voting | < ln 2 | 0.3724 |
| Robert Spillane | fantasyProsIdp | 3294 | 2182.0 | 2049.0 (DROPPED (incumbent)) | 2068.0 (voting) | voting | VERIFIED | voting | < ln 2 | 0.4155 |
| Roquan Smith | fantasyProsIdp | 5165 | 3337.0 | 3158.0 (DROPPED (incumbent)) | 3184.0 (voting) | voting | VERIFIED | voting | < ln 2 | 0.3588 |
| Sonny Styles | fantasyProsIdp | 2901 | 4978.0 | 5185.0 (DROPPED (incumbent)) | 5166.0 (voting) | voting | VERIFIED | voting | < ln 2 | 0.3636 |
| T.J. Watt | draftSharksIdp | 1450 | 2418.0 | 3436.0 (DROPPED (incumbent)) | 2440.0 (voting) | voting | NAME_ONLY | kept_dissent | 0.789 | 0.738 |
| Trevin Wallace | draftSharksIdp | 2886 | 1916.0 | 884.0 (DROPPED (incumbent)) | 1913.0 (voting) | voting | NAME_ONLY | voting_name_only_identity | < ln 2 | 0.6165 |
| Trey Hendrickson | idpTradeCalc | 2927 | 2104.0 | 1514.0 (DROPPED (incumbent)) | 2101.0 (voting) | voting | none (value-direct source) | voting | < ln 2 | 0.4237 |
| Will Anderson | draftSharksIdp | 2878 | 4395.0 | 5980.0 (DROPPED (incumbent)) | 4449.0 (voting) | voting | NAME_ONLY | kept_dissent | 0.8737 | 0.6662 |

## D4 regression set by rule (B′ vs A): 20 votes on 13 rows; retained in C′ 20/20, C″ 20/20

| row | source | vote | A row | B′ row | DLF Values vote | C′ row (status, V2 reason) | C″ status |
|---|---|---|---|---|---|---|---|
| Ashton Jeanty | ktcCrowdSfTep | 6983 | 8063.0 | 8147.0 | 8199 | 8026.0 (voting, voting_name_only_identity) | voting |
| Brock Purdy | idpTradeCalc | 6439 | 7467.0 | 7461.0 | 7859 | 7474.0 (voting, voting) | voting |
| Brock Purdy | yahooBoone | 8561 | 7467.0 | 7461.0 | 7859 | 7474.0 (voting, voting_name_only_identity) | voting |
| CeeDee Lamb | idpTradeCalc | 7343 | 8406.0 | 8473.0 | 8561 | 8266.0 (voting, voting) | voting |
| Colston Loveland | flockFantasySf | 7804 | 6666.0 | 6614.0 | 7013 | 6674.0 (voting, voting_name_only_identity) | voting |
| Courtland Sutton | draftSharks | 3429 | 2411.0 | 2353.0 | 2375 | 2382.0 (voting, voting_name_only_identity) | voting |
| Dalton Schultz | draftSharks | 3733 | 2791.0 | 2721.0 | 2571 | 2789.0 (voting, voting_name_only_identity) | voting |
| Evan Engram | draftSharks | 3109 | 2181.0 | 2095.0 | 1965 | 2141.0 (voting, voting_name_only_identity) | voting |
| Harold Fannin | yahooBoone | 4441 | 5374.0 | 5433.0 | 5972 | 5376.0 (voting, voting_name_only_identity) | voting |
| Hunter Henry | draftSharks | 3671 | 2705.0 | 2644.0 | 1990 | 2705.0 (voting, voting_name_only_identity) | voting |
| Joe Burrow | draftSharks | 9486 | 8008.0 | 8065.0 | 8438 | 8007.0 (voting, voting_name_only_identity) | voting |
| Joe Burrow | fantasyProsSf | 9345 | 8008.0 | 8065.0 | 8438 | 8007.0 (voting, voting) | voting |
| Joe Burrow | idpTradeCalc | 7080 | 8008.0 | 8065.0 | 8438 | 8007.0 (voting, voting) | voting |
| Joe Burrow | ktcCrowdSfTep | 6793 | 8008.0 | 8065.0 | 8438 | 8007.0 (voting, voting_name_only_identity) | voting |
| Kenneth Walker | otcffbSf | 8561 | 7409.0 | 7403.0 | 7644 | 7610.0 (voting, voting_name_only_identity) | voting |
| Patrick Mahomes | fantasyProsFitzmaurice | 8687 | 7548.0 | 7587.0 | 7540 | 7543.0 (voting, voting) | voting |
| Patrick Mahomes | idpTradeCalc | 6402 | 7548.0 | 7587.0 | 7540 | 7543.0 (voting, voting) | voting |
| Patrick Mahomes | ktcCrowdSfTep | 6357 | 7548.0 | 7587.0 | 7540 | 7543.0 (voting, voting_name_only_identity) | voting |
| Patrick Mahomes | yahooBoone | 8561 | 7548.0 | 7587.0 | 7540 | 7543.0 (voting, voting_name_only_identity) | voting |
| Trevor Lawrence | draftSharks | 8711 | 7277.0 | 7230.0 | 7242 | 7290.0 (voting, voting_name_only_identity) | voting |

## Original 30 %+ movers

| row | A | B | B vs A | C | C vs A | C″ | D | dropped in B | dropped in C |
|---|---|---|---|---|---|---|---|---|---|
| Trevin Wallace | 1916.0 | 884.0 | -53.9% | 1913.0 | -0.2% | 1913.0 | 1916.0 | draftSharksIdp | - |
| Myles Garrett | 3597.0 | 5246.0 | +45.8% | 3512.0 | -2.4% | 3512.0 | 3597.0 | draftSharksIdp | - |
| CJ Allen | 3918.0 | 2172.0 | -44.6% | 3964.0 | +1.2% | 3964.0 | 3918.0 | draftSharksIdp | - |
| T.J. Watt | 2418.0 | 3436.0 | +42.1% | 2440.0 | +0.9% | 2440.0 | 2418.0 | draftSharksIdp | - |
| Josiah Trotter | 2390.0 | 3379.0 | +41.4% | 2514.0 | +5.2% | 2514.0 | 2390.0 | fantasyProsIdp, draftSharksIdp | - |
| Will Anderson | 4395.0 | 5980.0 | +36.1% | 4449.0 | +1.2% | 4449.0 | 4395.0 | draftSharksIdp | - |
| Aidan Hutchinson | 4802.0 | 6422.0 | +33.7% | 4802.0 | +0.0% | 4802.0 | 4802.0 | draftSharksIdp | - |
| Danielle Hunter | 2352.0 | 3035.0 | +29.0% | 2328.0 | -1.0% | 2328.0 | 2352.0 | draftSharksIdp | - |

## Every V2 refusal / hold (any layer) on the V2 boards

| board | row | row team | source | V2 status / reason | category | vendor team | without V2 (status, vote) | row value no-filter → V2 |
|---|---|---|---|---|---|---|---|---|
| C | Byron Murphy | SEA | idpShowCombined | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | freshness_or_health_zero_weight, 2603 | 2513.0 → 2513.0 |
| C | Cole Payton | PHI | flockFantasySf | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | voting, 1527 | 1111.0 → 1070.0 |
| C | Jarquez Hunter | NO | dlfValuesSfTep | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIA | not_observed, None | 1287.0 → 1283.0 |
| C | Jarquez Hunter | NO | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIA | voting, 1473 | 1287.0 → 1283.0 |
| C | Jerome Ford | ARI | dlfValuesSfTep | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIN | not_observed, None | 1240.0 → 1242.0 |
| C | Joe Milton | PHI | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | DAL | voting, 1473 | 1484.0 → 1460.0 |
| C | Justin Jefferson | MIN | draftSharksIdp | refused / identity_contradicted:position_group | invalid_player_identity | - | not_observed, None | 7882.0 → 7882.0 |
| C | Justin Jefferson | MIN | idpShowCombined | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | freshness_or_health_zero_weight, 7531 | 7882.0 → 7882.0 |
| C | Kaytron Allen | MIA | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | WAS | voting, 1735 | 1776.0 → 1777.0 |
| C | Kyle Williams | NE | otcffbSf | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | voting, 1384 | 1728.0 → 1751.0 |
| C | Marvin Harrison | HOU | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | ARI | voting, 3118 | 3692.0 → 3698.0 |
| D | Byron Murphy | SEA | idpShowCombined | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | freshness_or_health_zero_weight, 2603 | 2427.0 → 2427.0 |
| D | Cole Payton | PHI | flockFantasySf | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | voting, 1527 | 1111.0 → 1070.0 |
| D | Jarquez Hunter | NO | dlfValuesSfTep | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIA | not_observed, None | 1287.0 → 1283.0 |
| D | Jarquez Hunter | NO | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIA | voting, 1473 | 1287.0 → 1283.0 |
| D | Jerome Ford | ARI | dlfValuesSfTep | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIN | not_observed, None | 1240.0 → 1242.0 |
| D | Joe Milton | PHI | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | DAL | voting, 1473 | 1484.0 → 1460.0 |
| D | Justin Jefferson | MIN | draftSharksIdp | refused / identity_contradicted:position_group | invalid_player_identity | - | not_observed, None | 7882.0 → 7882.0 |
| D | Justin Jefferson | MIN | idpShowCombined | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | freshness_or_health_zero_weight, 7531 | 7882.0 → 7882.0 |
| D | Kaytron Allen | MIA | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | WAS | voting, 1735 | 1776.0 → 1777.0 |
| D | Kyle Williams | NE | otcffbSf | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | voting, 1384 | 1728.0 → 1751.0 |
| D | Marvin Harrison | HOU | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | ARI | voting, 3118 | 3692.0 → 3698.0 |
| C' | Byron Murphy | SEA | idpShowCombined | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | freshness_or_health_zero_weight, 2603 | 2427.0 → 2427.0 |
| C' | Cole Payton | PHI | flockFantasySf | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | voting, 1527 | 1111.0 → 1070.0 |
| C' | Jarquez Hunter | NO | dlfValuesSfTep | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIA | voting, 1245 | 1277.0 → 1283.0 |
| C' | Jarquez Hunter | NO | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIA | voting, 1473 | 1277.0 → 1283.0 |
| C' | Jerome Ford | ARI | dlfValuesSfTep | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIN | voting, 1257 | 1233.0 → 1242.0 |
| C' | Joe Milton | PHI | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | DAL | voting, 1473 | 1484.0 → 1460.0 |
| C' | Justin Jefferson | MIN | draftSharksIdp | refused / identity_contradicted:position_group | invalid_player_identity | - | not_observed, None | 7881.0 → 7881.0 |
| C' | Justin Jefferson | MIN | idpShowCombined | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | freshness_or_health_zero_weight, 7531 | 7881.0 → 7881.0 |
| C' | Kaytron Allen | MIA | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | WAS | voting, 1735 | 1776.0 → 1776.0 |
| C' | Kyle Williams | NE | otcffbSf | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | voting, 1384 | 1705.0 → 1742.0 |
| C' | Marvin Harrison | HOU | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | ARI | voting, 3118 | 3684.0 → 3690.0 |
| C'' | Byron Murphy | SEA | idpShowCombined | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | freshness_or_health_zero_weight, 2603 | 2513.0 → 2513.0 |
| C'' | Cole Payton | PHI | flockFantasySf | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | voting, 1527 | 1111.0 → 1070.0 |
| C'' | Jarquez Hunter | NO | dlfValuesSfTep | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIA | voting, 1245 | 1277.0 → 1283.0 |
| C'' | Jarquez Hunter | NO | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIA | voting, 1473 | 1277.0 → 1283.0 |
| C'' | Jerome Ford | ARI | dlfValuesSfTep | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | MIN | voting, 1257 | 1233.0 → 1242.0 |
| C'' | Joe Milton | PHI | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | DAL | voting, 1473 | 1484.0 → 1460.0 |
| C'' | Justin Jefferson | MIN | draftSharksIdp | refused / identity_contradicted:position_group | invalid_player_identity | - | not_observed, None | 7881.0 → 7881.0 |
| C'' | Justin Jefferson | MIN | idpShowCombined | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | freshness_or_health_zero_weight, 7531 | 7881.0 → 7881.0 |
| C'' | Kaytron Allen | MIA | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | WAS | voting, 1735 | 1776.0 → 1776.0 |
| C'' | Kyle Williams | NE | otcffbSf | refused / identity_unresolved:ambiguous_in_source | temporarily_held_by_policy | - | voting, 1384 | 1705.0 → 1742.0 |
| C'' | Marvin Harrison | HOU | fantasyProsFitzmaurice | refused / identity_unresolved:team_only_mismatch | temporarily_held_by_policy | ARI | voting, 3118 | 3684.0 → 3690.0 |

## The incumbent's own drops on A (98) and their fate under V2 (board D)

97 of 98 have another voting source within 2x (ln 2) on board D. Largest distances first (top 15; full list in the JSON):

| row | source | vote | V2 status / reason | nearest other vote (source, value, ln distance) | row A → D |
|---|---|---|---|---|---|
| LaJohntay Wester | flockFantasySf | 1889 | voting / kept_dissent | otcffbSf 932 (0.7065) | 651.0 → 883.0 |
| Reggie Virgil | draftSharks | 2084 | voting / voting_name_only_identity | pfkDynasty 1079 (0.6583) | 951.0 → 968.0 |
| Barion Brown | draftSharks | 2702 | voting / voting_name_only_identity | idpTradeCalc 1708 (0.4587) | 1269.0 → 1298.0 |
| Chris Brazzell | draftSharks | 3132 | voting / voting_name_only_identity | ktcTradesSfTep 2135 (0.3832) | 1726.0 → 1776.0 |
| Sam Roush | draftSharks | 2806 | voting / voting_name_only_identity | fantasyProsSf 1967 (0.3553) | 1660.0 → 1689.0 |
| Jaxson Dart | draftSharks | 3796 | voting / voting_name_only_identity | flockFantasySf 5371 (0.3471) | 5994.0 → 5916.0 |
| Michael Penix | draftSharks | 5391 | voting / voting_name_only_identity | yahooBoone 3872 (0.331) | 3384.0 → 3417.0 |
| Malik Benson | draftSharks | 2304 | voting / voting_name_only_identity | idpTradeCalc 1661 (0.3272) | 1271.0 → 1311.0 |
| Sam Darnold | draftSharks | 6628 | voting / voting_name_only_identity | yahooBoone 4799 (0.3229) | 3988.0 → 4053.0 |
| KaVontae Turpin | pfkDynasty | 2362 | voting / voting | draftSharks 1733 (0.3097) | 1164.0 → 1223.0 |
| Charlie Kolar | draftSharks | 2966 | voting / voting_name_only_identity | pfkDynasty 2182 (0.307) | 1853.0 → 1891.0 |
| Jaxon Smith-Njigba | draftSharks | 6861 | voting / kept_dissent | ktcTradesSfTep 9284 (0.3024) | 9646.0 → 9619.0 |
| Nate Boerkircher | draftSharks | 2850 | voting / voting_name_only_identity | pfkDynasty 2119 (0.2964) | 1671.0 → 1736.0 |
| Brock Bowers | draftSharks | 6597 | voting / kept_dissent | fantasyProsSf 8757 (0.2832) | 9984.0 → 9917.0 |
| Garrett Wilson | draftSharks | 4398 | voting / voting_name_only_identity | yahooBoone 5737 (0.2658) | 6510.0 → 6440.0 |

## Two-way (Travis Hunter)

| board | published | alt (DB) family value | primary (offense) value | alt sources considered | alt-panel drops | row drops |
|---|---|---|---|---|---|---|
| A | 3599.0 | 3599 | 2317 | idpTradeCalc | - | idpTradeCalc |
| Anf | 3599.0 | 3599 | 2371 | idpTradeCalc | - | - |
| B | 3493.0 | 3493 | 2317 | dlfIdp, idpTradeCalc | - | idpTradeCalc |
| B' | 3599.0 | 3599 | 2272 | idpTradeCalc | - | idpTradeCalc |
| B'' | 3493.0 | 3493 | 2272 | dlfIdp, idpTradeCalc | - | idpTradeCalc |
| B''nf | 3493.0 | 3493 | 2325 | dlfIdp, idpTradeCalc | - | - |
| B'nf | 3599.0 | 3599 | 2325 | idpTradeCalc | - | - |
| Bnf | 3493.0 | 3493 | 2371 | dlfIdp, idpTradeCalc | - | - |
| C | 3493.0 | 3493 | 2371 | dlfIdp, idpTradeCalc | - | - |
| C' | 3599.0 | 3599 | 2325 | idpTradeCalc | - | - |
| C'' | 3493.0 | 3493 | 2325 | dlfIdp, idpTradeCalc | - | - |
| D | 3599.0 | 3599 | 2371 | idpTradeCalc | - | - |

## Picks

* B vs A: 39 pick rows move, by provenance {'rookie_pool_tether': 39}, max |Δ| 5.4% (largest: 2027 Pick 2.01 3918.0→3705.0, 2027 Pick 2.06 3397.0→3216.0, 2027 Pick 4.02 2291.0→2181.0, 2027 Pick 2.03 3566.0→3403.0)
* C vs A: 53 pick rows move, by provenance {'rookie_pool_tether': 53}, max |Δ| 3.8% (largest: 2027 Pick 1.05 4978.0→5166.0, 2027 Pick 2.03 3566.0→3690.0, 2027 Pick 1.06 4770.0→4924.0, 2027 Pick 1.01 7228.0→7431.0)
* C vs B: 48 pick rows move, by provenance {'rookie_pool_tether': 48}, max |Δ| 8.4% (largest: 2027 Pick 2.03 3403.0→3690.0, 2027 Pick 2.04 3397.0→3650.0, 2027 Pick 2.01 3705.0→3964.0, 2027 Pick 4.02 2181.0→2291.0)
* D vs A: 33 pick rows move, by provenance {'rookie_pool_tether': 33}, max |Δ| 2.8% (largest: 2027 Pick 1.01 7228.0→7431.0, 2027 Pick 5.09 1776.0→1809.0, 2027 Pick 5.07 1807.0→1835.0, 2027 Pick 5.12 1745.0→1772.0)
* C' vs A: 54 pick rows move, by provenance {'rookie_pool_tether': 54}, max |Δ| 4.2% (largest: 2027 Pick 1.01 7228.0→7529.0, 2027 Pick 5.09 1776.0→1809.0, 2027 Pick 5.12 1745.0→1773.0, 2027 Pick 6.05 1699.0→1721.0)
* C'' vs A: 69 pick rows move, by provenance {'rookie_pool_tether': 69}, max |Δ| 4.2% (largest: 2027 Pick 1.01 7228.0→7529.0, 2027 Pick 1.05 4978.0→5166.0, 2027 Pick 2.03 3566.0→3690.0, 2027 Pick 1.06 4770.0→4924.0)

