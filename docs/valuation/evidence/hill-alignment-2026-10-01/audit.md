# Hill / native-source alignment audit — tables

Schema `hill-alignment-audit/v1`; declaration sha256 `543fd3a3b7a56423…`; invariants ok: **True**.

## Pins

- code revision `169f0895dc4a153efe65e782693115b71667a795` (inputs dirty: False; full tracked tree dirty: False)
- payload `exports\latest\dynasty_data_2026-09-30.json` sha256 `69a0f4b4e26486c1…`, scrape 2026-09-30T13:04:04.598312+00:00
- source CSVs: 30 hashed; config files: 53; freshness state files: 24
- local league snapshots: 0 file(s) (gitignored; none = tracked-input build, completed-draft picks kept)
- live league context: [{"args": [], "result": {"roster_count": 12, "bonus_rec_te": 0.0, "fetched_from_sleeper": true}}, {"args": [12], "result": {"roster_count": 12, "bonus_rec_te": 0.0, "fetched_from_sleeper": true}}, {"args": [12], "result": {"roster_count": 12, "bonus_rec_te": 0.0, "fetched_from_sleeper": true}}]
- board rows 1131; incumbent board sha256 `9090458d00c39f5c…`
- invariants: `{"rebuild_is_identical": true, "direct_hill_matches_pipeline_rank_hill": {"agree": 832, "disagree": 0}, "hampel_1000_variant_equals_incumbent": true, "csv_patch_identity_rows_changed": 0, "c3_patch": {"partitionCalls": 2, "rowsRewritten": {"ktcCrowdSfTep": 924, "ktcTradesSfTep": 924}, "outOfRangeRewritten": 0, "restored": 1848, "contributionCheck": {"ktcCrowdSfTep": {"playerRowsMatchHillPlayersOnlyRank": 462, "playerRowsMismatch": 0, "pickRowsUnchanged": 36, "pickRowsChanged": 0}, "ktcTradesSfTep": {"playerRowsMatchHillPlayersOnlyRank": 462, "playerRowsMismatch": 0, "pickRowsUnchanged": 36, "pickRowsChanged": 0}, "publishedSiteValuesDiffering": 0, "ok": true}}, "c3_patch_restored_after_build": true, "dlf_join_probe_board_unchanged": true}`

## A. Scale vs population (offense rows, median ratio, n)

### ktcCrowdSfTep

verdict: `{"bandsOutsideTolerance": ["101-200", "201-300", "301-400"], "scaleMismatchConfirmed": true, "meanLog2Live": 0.3923, "meanLog2PopulationFactor": 0.1167, "populationShare": 0.298}`

| band | ratioLive | populationFactor | ratioPop | ratioVendor | ratioPopChallenger |
|---|---|---|---|---|---|
| 1-50 | 0.955 (n 50) | 1.012 (n 50) | 0.943 (n 50) | 0.943 (n 50) | 1.141 (n 50) |
| 51-100 | 1.153 (n 50) | 1.039 (n 50) | 1.087 (n 50) | 1.079 (n 50) | 1.582 (n 50) |
| 101-200 | 1.306 (n 100) | 1.083 (n 100) | 1.204 (n 100) | 1.184 (n 100) | 1.835 (n 100) |
| 201-300 | 1.448 (n 100) | 1.096 (n 100) | 1.320 (n 100) | 1.269 (n 100) | 2.074 (n 100) |
| 301-400 | 1.302 (n 100) | 1.097 (n 100) | 1.185 (n 100) | 1.125 (n 100) | 1.879 (n 100) |
| 401+ | 0.941 (n 62) | 1.085 (n 62) | 0.868 (n 62) | 0.823 (n 62) | 1.383 (n 62) |

by position (population-correct ratio):

| group | median | p25 | p75 | n |
|---|---|---|---|---|
| QB | 1.098 | 0.945 | 1.303 | 72 |
| RB | 1.147 | 1.019 | 1.291 | 124 |
| TE | 1.221 | 1.111 | 1.308 | 76 |
| WR | 1.147 | 1.013 | 1.285 | 190 |

by row weight state:

| group | median | n |
|---|---|---|
| DEGRADED | 0.898 | 3 |
| NORMAL | 1.155 | 459 |

by independent families:

| group | median | n |
|---|---|---|
| 3-4 | 0.637 | 31 |
| 5-8 | 1.066 | 58 |
| 9+ | 1.198 | 371 |
| <=2 | 0.760 | 2 |

### ktcTradesSfTep

verdict: `{"bandsOutsideTolerance": ["51-100", "101-200", "201-300", "301-400"], "scaleMismatchConfirmed": true, "meanLog2Live": 0.5135, "meanLog2PopulationFactor": 0.0977, "populationShare": 0.19}`

| band | ratioLive | populationFactor | ratioPop | ratioVendor | ratioPopChallenger |
|---|---|---|---|---|---|
| 1-50 | 1.001 (n 50) | 1.000 (n 50) | 0.994 (n 50) | 0.994 (n 50) | 1.190 (n 50) |
| 51-100 | 1.226 (n 50) | 1.025 (n 50) | 1.187 (n 50) | 1.187 (n 50) | 1.711 (n 50) |
| 101-200 | 1.324 (n 100) | 1.060 (n 100) | 1.250 (n 100) | 1.236 (n 100) | 1.908 (n 100) |
| 201-300 | 1.532 (n 100) | 1.077 (n 100) | 1.421 (n 100) | 1.401 (n 100) | 2.230 (n 100) |
| 301-400 | 1.592 (n 100) | 1.092 (n 100) | 1.457 (n 100) | 1.409 (n 100) | 2.311 (n 100) |
| 401+ | 1.158 (n 62) | 1.085 (n 62) | 1.068 (n 62) | 1.031 (n 62) | 1.701 (n 62) |

by position (population-correct ratio):

| group | median | p25 | p75 | n |
|---|---|---|---|---|
| QB | 1.282 | 1.072 | 1.415 | 72 |
| RB | 1.273 | 1.144 | 1.435 | 124 |
| TE | 1.272 | 1.197 | 1.409 | 76 |
| WR | 1.270 | 1.188 | 1.424 | 190 |

by row weight state:

| group | median | n |
|---|---|---|
| DEGRADED | 1.391 | 3 |
| NORMAL | 1.273 | 459 |

by independent families:

| group | median | n |
|---|---|---|
| 3-4 | 1.067 | 31 |
| 5-8 | 1.289 | 58 |
| 9+ | 1.287 | 371 |
| <=2 | 0.651 | 2 |

### idpTradeCalc

verdict: `{"bandsOutsideTolerance": ["101-200", "201-300", "301-400"], "scaleMismatchConfirmed": true, "meanLog2Live": 0.0444, "meanLog2PopulationFactor": -0.2115, "populationShare": -4.759}`

| band | ratioLive | populationFactor | ratioPop | ratioVendor | ratioPopChallenger |
|---|---|---|---|---|---|
| 1-50 | 1.061 (n 50) | 1.136 (n 50) | 0.937 (n 50) | — | 1.132 (n 50) |
| 51-100 | 1.161 (n 50) | 1.048 (n 50) | 1.076 (n 50) | — | 1.542 (n 50) |
| 101-200 | 1.122 (n 100) | 0.972 (n 100) | 1.185 (n 100) | — | 1.807 (n 100) |
| 201-300 | 1.045 (n 100) | 0.805 (n 100) | 1.305 (n 100) | — | 2.045 (n 100) |
| 301-400 | 0.873 (n 100) | 0.759 (n 100) | 1.153 (n 100) | — | 1.830 (n 100) |
| 401+ | 0.685 (n 32) | 0.737 (n 32) | 0.931 (n 32) | — | 1.482 (n 32) |

by position (population-correct ratio):

| group | median | p25 | p75 | n |
|---|---|---|---|---|
| DB | 0.823 | 0.760 | 0.884 | 122 |
| DL | 0.792 | 0.672 | 0.865 | 146 |
| LB | 0.798 | 0.633 | 0.853 | 108 |
| QB | 1.102 | 0.965 | 1.236 | 67 |
| RB | 1.151 | 1.068 | 1.256 | 117 |
| TE | 1.218 | 1.134 | 1.263 | 72 |
| WR | 1.149 | 1.056 | 1.262 | 176 |

by row weight state:

| group | median | n |
|---|---|---|
| DEGRADED | 1.072 | 3 |
| NORMAL | 1.152 | 429 |

by independent families:

| group | median | n |
|---|---|---|
| 3-4 | 0.973 | 14 |
| 5-8 | 1.110 | 53 |
| 9+ | 1.188 | 365 |

IDP rows vs IDP master (CIRCULAR — master fit on this slice):

| band | ratioPop |
|---|---|
| 1-50 | 0.583 (n 50) |
| 51-100 | 0.640 (n 50) |
| 101-200 | 0.775 (n 101) |
| 201-300 | 0.859 (n 99) |
| 301-400 | 0.864 (n 76) |
| 401+ | — |

### Live rank pools

```
{
 "ktcCrowdSfTep": {
  "rowsInPool": 498,
  "byClass": {
   "offense": 462,
   "pick": 36
  },
  "picksInTop400": 35,
  "idpInTop400": 0
 },
 "ktcTradesSfTep": {
  "rowsInPool": 498,
  "byClass": {
   "offense": 462,
   "pick": 36
  },
  "picksInTop400": 35,
  "idpInTop400": 0
 },
 "idpTradeCalc": {
  "rowsInPool": 892,
  "byClass": {
   "idp": 376,
   "offense": 432,
   "pick": 84
  },
  "picksInTop400": 60,
  "idpInTop400": 83
 }
}
```

### Source subset freshness (value sources)

```
{
 "ktcCrowdSfTep": {
  "players": {
   "freshness": 1.0,
   "ageHours": 7.0,
   "expectedCadenceHours": 12.0,
   "state": "ON_SCHEDULE"
  },
  "picks": {
   "freshness": 1.0,
   "ageHours": 7.0,
   "expectedCadenceHours": 12.0,
   "state": "ON_SCHEDULE"
  }
 },
 "ktcTradesSfTep": {
  "players": {
   "freshness": 1.0,
   "ageHours": 7.0,
   "expectedCadenceHours": 12.0,
   "state": "ON_SCHEDULE"
  },
  "picks": {
   "freshness": 1.0,
   "ageHours": 7.0,
   "expectedCadenceHours": 12.0,
   "state": "ON_SCHEDULE"
  }
 },
 "idpTradeCalc": {
  "players": {
   "freshness": 0.9827,
   "ageHours": 159.2,
   "expectedCadenceHours": 135.8,
   "state": "ON_SCHEDULE"
  },
  "picks": {
   "freshness": 0.0589,
   "ageHours": 803.8,
   "expectedCadenceHours": 135.8,
   "state": "SEVERELY_STALE"
  }
 }
}
```

### Native curve shapes (players only, canonical coordinate, top 400)

| board | role | c | s | rmse | n |
|---|---|---|---|---|---|
| ktcCrowdSfTep | live value voter | 0.112 | 0.91 | 201.9 | 400 |
| ktcCrowdSfTep (as the fitter reads it, 35 picks in top 400) | | 0.119 | 0.87 | 181.8 | 400 |
| ktcTradesSfTep | live value voter | 0.13 | 0.935 | 145.0 | 400 |
| ktcTradesSfTep (as the fitter reads it, 35 picks in top 400) | | 0.135 | 0.89 | 125.2 | 400 |
| ktc (base) | OFFENSE trainer; non-voting | 0.105 | 0.925 | 209.0 | 400 |
| ktc (base) (as the fitter reads it, 36 picks in top 400) | | 0.111 | 0.875 | 193.9 | 400 |
| dynastyDaddySf | OFFENSE trainer; rank voter | 0.056 | 1.21 | 304.2 | 381 |
| dynastyNerdsSfTep | OFFENSE trainer; rank voter | 0.056 | 1.73 | 253.8 | 294 |
| yahooBoone | OFFENSE trainer; rank voter | 0.076 | 1.26 | 363.9 | 400 |
| fantasyProsFitzmaurice | OFFENSE trainer; rank voter | 0.122 | 1.31 | 489.0 | 297 |
| draftSharksSf | OFFENSE trainer; rank voter | 0.028 | 0.83 | 186.0 | 360 |
| fantasyCalc | OFFENSE holdout; rank voter | 0.044 | 1.075 | 327.6 | 397 |
| otcffbSf | OFFENSE holdout; rank voter | 0.041 | 1.01 | 191.5 | 370 |
| pfkDynasty | OFFENSE holdout; rank voter | 0.085 | 1.11 | 215.6 | 400 |
| fantasyNavigatorSf | OFFENSE holdout; rank voter (ktcCrowd family) | 0.05 | 1.345 | 366.6 | 400 |
| dlfValuesSfTep | non-voting; measurement gate pending | 0.062 | 1.69 | 266.0 | 323 |

live OFFENSE master: `{'c': 0.11, 's': 1.11}`; pending challenger: `{"version": 171, "status": "rejected", "notes": ["rejected: Hill Autopilot downstream board-impact gate blocked promotion"], "c": 0.066, "s": 1.085}`

### Erratum for the 2026-09-30 replay counterfactual

```
{
 "what": "the 2026-09-30 native_values_as_ranks emptied _VALUE_BASED_SOURCES; IDPTC then entered Phase 1c and its native value was decoded as a rank",
 "idptcEffectiveRankMinMax": [
  9900,
  9992
 ],
 "replayMetricUnderOldPatch": {
  "notComparableRankMoved": 856
 },
 "boardDiffOldPatch": {
  "rowsCompared": 1131,
  "rowsChanged": 980,
  "byGroup": {
   "IDP": {
    "changed": 375,
    "medianAbs": 181,
    "p90Abs": 634,
    "maxAbs": 3863
   },
   "PICK": {
    "changed": 144,
    "medianAbs": 454.0,
    "p90Abs": 754,
    "maxAbs": 843
   },
   "QB": {
    "changed": 72,
    "medianAbs": 73.5,
    "p90Abs": 144,
    "maxAbs": 283
   },
   "RB": {
    "changed": 123,
    "medianAbs": 75,
    "p90Abs": 120,
    "maxAbs": 224
   },
   "TE": {
    "changed": 76,
    "medianAbs": 101.0,
    "p90Abs": 177,
    "maxAbs": 404
   },
   "WR": {
    "changed": 190,
    "medianAbs": 83.0,
    "p90Abs": 152,
    "maxAbs": 974
   }
  },
  "top200MembershipChanges": 36,
  "largestMoves": [
   {
    "asset": "Aidan Hutchinson",
    "group": "IDP",
    "delta": -3863,
    "rankBefore": 34,
    "rankAfter": 198
   },
   {
    "asset": "Will Anderson",
    "group": "IDP",
    "delta": -3570,
    "rankBefore": 42,
    "rankAfter": 221
   },
   {
    "asset": "Myles Garrett",
    "group": "IDP",
    "delta": -3356,
    "rankBefore": 61,
    "rankAfter": 298
   },
   {
    "asset": "Jacob Rodriguez",
    "group": "IDP",
    "delta": -2072,
    "rankBefore": 72,
    "rankAfter": 176
   },
   {
    "asset": "Arvell Reese",
    "group": "IDP",
    "delta": -1858,
    "rankBefore": 67,
    "rankAfter": 147
   }
  ]
 },
 "boardDiffCorrectedPatch": {
  "rowsCompared": 1131,
  "rowsChanged": 598,
  "byGroup": {
   "PICK": {
    "changed": 139,
    "medianAbs": 330,
    "p90Abs": 729,
    "maxAbs": 814
   },
   "QB": {
    "changed": 72,
    "medianAbs": 67.0,
    "p90Abs": 134,
    "maxAbs": 284
   },
   "RB": {
    "changed": 123,
    "medianAbs": 69,
    "p90Abs": 113,
    "maxAbs": 223
   },
   "TE": {
    "changed": 75,
    "medianAbs": 104,
    "p90Abs": 158,
    "maxAbs": 404
   },
   "WR": {
    "changed": 189,
    "medianAbs": 80,
    "p90Abs": 144,
    "maxAbs": 345
   }
  },
  "top200MembershipChanges": 10,
  "largestMoves": [
   {
    "asset": "2029 Late 2nd",
    "group": "PICK",
    "delta": -814,
    "rankBefore": 233,
    "rankAfter": 395
   },
   {
    "asset": "2029 Early 1st",
    "group": "PICK",
    "delta": -788,
    "rankBefore": 84,
    "rankAfter": 111
   },
   {
    "asset": "2028 Late 2nd",
    "group": "PICK",
    "delta": -773,
    "rankBefore": 209,
    "rankAfter": 305
   },
   {
    "asset": "2029 Round 2",
    "group": "PICK",
    "delta": -769,
    "rankBefore": null,
    "rankAfter": null
   },
   {
    "asset": "2029 Mid 2nd",
    "group": "PICK",
    "delta": -768,
    "rankBefore": 211,
    "rankAfter": 311
   }
  ]
 }
}
```

## B. Disagreement against leave-that-source-out boards

KTC Crowd and KTC Trades are each compared with a board built WITHOUT BOTH KTC families (same provider, correlated); IDPTC without IDPTC; every rank voter without itself.

| source | rows | rank ratio 1-50 | 51-100 | 101-200 | 201-300 | 301-400 | share >41% off | outlier drop rate |
|---|---|---|---|---|---|---|---|---|
| ktcCrowdSfTep | 462 | 0.919 | 1.006 | 0.994 | 0.986 | 0.983 | 0.058 | 0.022 |
| ktcTradesSfTep | 462 | 1.023 | 1.015 | 0.989 | 0.993 | 0.959 | 0.043 | 0.004 |
| idpTradeCalc | 432 | 0.961 | 1.000 | 0.985 | 0.944 | 0.977 | 0.056 | 0.007 |
| dlfRookieSf | 0 | — | — | — | — | — | — | — |
| dlfSf | 286 | 0.948 | 0.975 | 0.976 | 1.017 | — | 0.161 | 0.024 |
| draftSharks | 368 | 1.019 | 0.949 | 0.974 | 0.987 | 1.018 | 0.177 | 0.122 |
| dynastyDaddySf | 380 | 1.000 | 0.969 | 0.981 | 0.928 | 1.051 | 0.111 | 0.005 |
| dynastyNerdsSfTep | 294 | 1.000 | 0.951 | 0.952 | 1.034 | — | 0.102 | 0.017 |
| fantasyCalc | 389 | 0.933 | 1.000 | 0.970 | 0.975 | 1.022 | 0.134 | 0.005 |
| fantasyNavigatorSf | 447 | 0.941 | 0.962 | 0.952 | 0.881 | 0.975 | 0.143 | 0.009 |
| fantasyProsFitzmaurice | 297 | 1.000 | 0.947 | 0.936 | 1.008 | — | 0.111 | 0.010 |
| fantasyProsSf | 383 | 0.973 | 0.995 | 0.957 | 0.919 | 1.016 | 0.110 | 0.016 |
| flockFantasySf | 405 | 0.908 | 0.964 | 0.923 | 0.928 | 1.041 | 0.114 | 0.002 |
| flockFantasySfRookies | 0 | — | — | — | — | — | — | — |
| idpShowCombined | 356 | 0.924 | 0.957 | 0.964 | 0.947 | 1.030 | 0.115 | 0.017 |
| otcffbSf | 369 | 0.947 | 0.952 | 0.921 | 0.893 | 1.079 | 0.144 | 0.003 |
| pfkDynasty | 455 | 0.950 | 1.039 | 1.000 | 0.940 | 0.984 | 0.081 | 0.022 |
| yahooBoone | 387 | 0.977 | 1.011 | 0.935 | 0.931 | 1.006 | 0.114 | 0.034 |

Outlier-dropped observations: are they order disagreements or scale gaps?

| source | dropped | median rank ratio | median scale term | median order term |
|---|---|---|---|---|
| ktcCrowdSfTep | 10 | 1.017 | 0.954 | 0.979 |
| ktcTradesSfTep | 2 | 0.776 | 1.167 | 1.122 |
| idpTradeCalc | 3 | 1.222 | 0.932 | 0.971 |
| dlfSf | 7 | 0.634 | — | — |
| draftSharks | 45 | 0.808 | — | — |
| dynastyDaddySf | 2 | 0.580 | — | — |
| dynastyNerdsSfTep | 5 | 0.606 | — | — |
| fantasyCalc | 2 | 0.621 | — | — |
| fantasyNavigatorSf | 4 | 0.616 | — | — |
| fantasyProsFitzmaurice | 3 | 0.250 | — | — |
| fantasyProsSf | 6 | 0.591 | — | — |
| flockFantasySf | 1 | 0.499 | — | — |
| idpShowCombined | 6 | 1.263 | — | — |
| otcffbSf | 1 | 0.600 | — | — |
| pfkDynasty | 10 | 0.980 | — | — |
| yahooBoone | 13 | 0.679 | — | — |

ktcCrowdSfTep: value split, log2(native/LOO) = scale + order-on-Hill (medians)

| band | nativeOverLoo | scaleTerm | orderTermOnHill |
|---|---|---|---|
| 1-50 | 0.956 (n 50) | 0.943 (n 50) | 1.016 (n 50) |
| 51-100 | 1.062 (n 50) | 1.087 (n 50) | 0.963 (n 50) |
| 101-200 | 1.143 (n 100) | 1.204 (n 100) | 0.943 (n 100) |
| 201-300 | 1.209 (n 100) | 1.320 (n 100) | 0.916 (n 100) |
| 301-400 | 1.048 (n 100) | 1.185 (n 100) | 0.891 (n 100) |
| 401+ | 0.744 (n 62) | 0.868 (n 62) | 0.886 (n 62) |

ktcTradesSfTep: value split, log2(native/LOO) = scale + order-on-Hill (medians)

| band | nativeOverLoo | scaleTerm | orderTermOnHill |
|---|---|---|---|
| 1-50 | 0.980 (n 50) | 0.994 (n 50) | 0.986 (n 50) |
| 51-100 | 1.127 (n 50) | 1.187 (n 50) | 0.955 (n 50) |
| 101-200 | 1.184 (n 100) | 1.250 (n 100) | 0.943 (n 100) |
| 201-300 | 1.282 (n 100) | 1.421 (n 100) | 0.905 (n 100) |
| 301-400 | 1.287 (n 100) | 1.457 (n 100) | 0.908 (n 100) |
| 401+ | 0.907 (n 62) | 1.068 (n 62) | 0.887 (n 62) |

idpTradeCalc: value split, log2(native/LOO) = scale + order-on-Hill (medians)

| band | nativeOverLoo | scaleTerm | orderTermOnHill |
|---|---|---|---|
| 1-50 | 0.953 (n 50) | 0.937 (n 50) | 1.014 (n 50) |
| 51-100 | 1.048 (n 50) | 1.076 (n 50) | 0.967 (n 50) |
| 101-200 | 1.098 (n 100) | 1.185 (n 100) | 0.934 (n 100) |
| 201-300 | 1.202 (n 100) | 1.305 (n 100) | 0.925 (n 100) |
| 301-400 | 1.021 (n 100) | 1.153 (n 100) | 0.900 (n 100) |
| 401+ | 0.826 (n 32) | 0.931 (n 32) | 0.887 (n 32) |

## C. Outlier-filter threshold sensitivity

| variant | excluded | rows | KTC Crowd | KTC Trades | both KTC | IDPTC | rows changed | top-200 changes |
|---|---|---|---|---|---|---|---|---|
| incumbent | 161 | 116 | 10 | 2 | 1 | 5 | 0 | 0 |
| floor_750 | 291 | 201 | 21 | 11 | 5 | 12 | 135 | 6 |
| floor_1000_incumbent | 161 | 116 | 10 | 2 | 1 | 5 | 0 | 0 |
| floor_1250 | 86 | 69 | 5 | 0 | 0 | 2 | 84 | 6 |
| floor_1500 | 50 | 44 | 3 | 0 | 0 | 1 | 123 | 8 |
| mad_only_no_floor | 807 | 462 | 61 | 101 | 27 | 91 | 440 | 8 |
| mad_scaled_1p4826_no_floor | 340 | 240 | 27 | 37 | 10 | 36 | 263 | 6 |
| off | 0 | 0 | 0 | 0 | 0 | 0 | 163 | 8 |

incumbent KTC drops by live rank band: `{"401+": 1, "1-50": 6, "51-100": 4, "101-200": 1}`

## D. Candidates

c1 own-curve fits: `{"ktcCrowdSfTep": {"n": 400, "c": 0.112, "s": 0.91, "rmse": 201.9}, "ktcTradesSfTep": {"n": 400, "c": 0.13, "s": 0.935, "rmse": 145.0}}`

| candidate | rows changed | median Δ% | p90 Δ% | max Δ% | top-25/50/100/200 kept | KTC excl. (crowd/trades) | KTC leverage p90 | sparse changed / median Δ% | struct. errors | build s | gates |
|---|---|---|---|---|---|---|---|---|---|---|---|
| incumbent | 0 | 0.000 | 0.000 | 0.000 | 25/50/100/200 | 10/2 | 0.060 | 0 / 0.000 | 0 | 0.677 | — |
| c1_ktc_scale_map | 598 | 0.007 | 0.098 | 0.405 | 25/48/100/195 | 5/1 | 0.086 | 2 / 0.206 | 0 | 1.123 | {"board_impact": true, "no_new_structural_errors": true, "leverage": false, "cost": false} |
| c2_ktc_rank_hill | 598 | 0.013 | 0.084 | 0.341 | 25/48/98/195 | 6/1 | 0.062 | 2 / 0.218 | 0 | 0.741 | {"board_impact": true, "no_new_structural_errors": true, "leverage": true, "cost": true} |
| c3_ktc_players_rank_hill (POST-HOC) | 527 | 0.001 | 0.049 | 0.410 | 25/48/98/198 | 3/1 | 0.053 | 2 / 0.297 | 0 | 0.916 | {"board_impact": true, "no_new_structural_errors": true, "leverage": true, "cost": true} |

Players only (pick rows removed from both boards — a reporting cut):

| candidate | median Δ% | p90 Δ% | max Δ% | top-25 | top-100 | median rank shift | p90 rank shift |
|---|---|---|---|---|---|---|---|
| incumbent | 0.000 | 0.000 | 0.000 | 25 | 100 | 0.0 | 0.0 |
| c1_ktc_scale_map | 0.001 | 0.062 | 0.405 | 25 | 100 | 12.0 | 25.0 |
| c2_ktc_rank_hill | 0.002 | 0.066 | 0.318 | 25 | 99 | 14.5 | 31.0 |
| c3_ktc_players_rank_hill | 0.002 | 0.053 | 0.410 | 25 | 100 | 11.0 | 22.0 |

Pick rows (value units):

| candidate | changed | median abs Δ | max abs Δ |
|---|---|---|---|
| incumbent | 0 | 0 | 0 |
| c1_ktc_scale_map | 139 | 144 | 557 |
| c2_ktc_rank_hill | 139 | 330 | 814 |
| c3_ktc_players_rank_hill | 67 | 41 | 174 |

c3 vs c2: rows changed 555, top-200 membership changes 8; players only `{"rows": 969, "unpricedFraction": 0.0, "medianAbsPctValueChange": 0.0, "p90AbsPctValueChange": 0.017074117190531625, "maxAbsPctValueChange": 0.08391608391608392, "medianAbsRankShift": 9.0, "p90AbsRankShift": 15.0, "top25Overlap": 25, "top100Overlap": 99}`; pick rows `{"changed": 115, "medianAbsDelta": 470, "maxAbsDelta": 814}`

Post-hoc additions (sha256 `c10a02d1a1ae3455…`): `{"addedAt": "independent review of PR #1573, 2026-10-01", "candidates": {"c3_ktc_players_rank_hill": "the README section 4 recommendation as written: KTC Crowd and KTC Trades PLAYER rows vote Hill_OFFENSE(players-only rank) -- the rank among the board's offense players that source covers, picks removed; KTC PICK rows stay value-direct. Phase 1 ordinals (and therefore the rookie ladders that read KTC Crowd's rank) are untouched. Replay-only patch; same metrics and gates as c1/c2."}, "dlf_native": "dlfValuesSfTep gets the Part A scale-band treatment (vendor rank and board players-only rank, OFFENSE master, same verdict rule) and the Part B rank-space treatment against (i) the incumbent (already leave-DLF-Values-out, but holds DLF Rank) and (ii) a board without the whole DLF family; stability from the CSV's git history under the same <= 0.10 rule. The join is the production CSV join, run in one diagnostic build.", "evidentialWeight": "post-hoc: chosen after seeing c2; a pass is weaker evidence than a predeclared pass, a failure is not weakened"}`

Regression examples (value / rank / KTC dropped):

| asset | incumbent | c1_ktc_scale_map | c2_ktc_rank_hill | c3_ktc_players_rank_hill |
|---|---|---|---|---|
| Jalen Coker | 3288 / 155 / ktcCrowdSfTep,ktcTradesSfTep | 3372 / 140 / ktcCrowdSfTep | 3443 / 131 / - | 3447 / 134 / - |
| Ladd McConkey | 5561 / 48 / - | 5519 / 51 / - | 5491 / 50 / - | 5496 / 51 / - |
| Quinshon Judkins | 4908 / 69 / - | 4864 / 69 / - | 4830 / 67 / - | 4839 / 68 / - |
| MarShawn Lloyd | 2497 / 239 / - | 2381 / 246 / - | 2372 / 242 / - | 2378 / 251 / - |
| Travis Hunter | 4024 / 103 / - | 4024 / 101 / - | 4024 / 98 / - | 4024 / 102 / - |
| Michael Mayer | 2470 / 245 / - | 2431 / 237 / - | 2392 / 239 / - | 2436 / 241 / - |
| Aidan Hutchinson | 6411 / 34 / - | 6411 / 34 / - | 6411 / 34 / - | 6411 / 35 / - |
| Will Anderson | 5928 / 42 / - | 5928 / 42 / - | 5928 / 42 / - | 5928 / 42 / - |
| Jeremiyah Love | 7859 / 16 / - | 7869 / 16 / - | 8033 / 17 / - | 8033 / 17 / - |
| Fernando Mendoza | 5332 / 57 / - | 5298 / 58 / - | 5276 / 57 / - | 5282 / 59 / - |
| 2026 Pick 1.01 | 7859 / None / - | 7869 / None / - | 8033 / None / - | 8033 / None / - |
| 2026 Pick 1.02 | 5332 / None / - | 5298 / None / - | 5276 / None / - | 5282 / None / - |
| 2027 Round 1 | 5643 / None / - | 5524 / None / - | 5458 / None / - | 5643 / None / - |

## DLF native values (non-voting; added at review)

non-voting (not in _RANKING_SOURCES); measurement only. Vendor rows 323; joined rows by class `{"offense": 323}`; offense rows on the board 323; CSV sha256 `38284bc9f52a8929…`.

verdict: `{"bandsOutsideTolerance": ["51-100", "101-200", "201-300", "301-400"], "scaleMismatchConfirmed": true, "populationShare": null, "populationShareNote": "undefined: DLF Values has no live rank (it does not vote)"}`

| band | ratioPop | ratioVendor | populationFactor |
|---|---|---|---|
| 1-50 | 0.827 (n 50) | 0.827 (n 50) | 1.000 (n 50) |
| 51-100 | 0.492 (n 50) | 0.492 (n 50) | 1.000 (n 50) |
| 101-200 | 0.183 (n 100) | 0.183 (n 100) | 1.000 (n 100) |
| 201-300 | 0.041 (n 100) | 0.041 (n 100) | 1.000 (n 100) |
| 301-400 | 0.009 (n 23) | 0.009 (n 23) | 1.000 (n 23) |
| 401+ | — | — | — |

by position (population-correct ratio):

| group | median | p25 | p75 | n |
|---|---|---|---|---|
| QB | 0.262 | 0.038 | 0.699 | 57 |
| RB | 0.145 | 0.048 | 0.412 | 91 |
| TE | 0.094 | 0.057 | 0.311 | 47 |
| WR | 0.124 | 0.048 | 0.394 | 128 |

Rank space (DLF family voters disabled for the LOO board: ['dlfIdp', 'dlfRookieIdp', 'dlfRookieSf', 'dlfSf']):

| comparison | rows | rank ratio 1-50 | 51-100 | 101-200 | 201-300 | 301-400 | share >41% off |
|---|---|---|---|---|---|---|---|
| vsIncumbent_containsDlfRank | 323 | 1.000 | 0.965 | 0.946 | 0.984 | 1.039 | 0.056 |
| vsNoDlfFamily | 323 | 1.000 | 0.975 | 0.955 | 0.983 | 1.039 | 0.059 |

vsIncumbent_containsDlfRank: value split, log2(native/board) = scale + order-on-Hill

| band | nativeOverLoo | scaleTerm | orderTermOnHill |
|---|---|---|---|
| 1-50 | 0.837 (n 50) | 0.827 (n 50) | 1.005 (n 50) |
| 51-100 | 0.483 (n 50) | 0.492 (n 50) | 0.987 (n 50) |
| 101-200 | 0.164 (n 100) | 0.183 (n 100) | 0.962 (n 100) |
| 201-300 | 0.039 (n 100) | 0.041 (n 100) | 0.944 (n 100) |
| 301-400 | 0.008 (n 23) | 0.009 (n 23) | 0.927 (n 23) |
| 401+ | — | — | — |

vsNoDlfFamily: value split, log2(native/board) = scale + order-on-Hill

| band | nativeOverLoo | scaleTerm | orderTermOnHill |
|---|---|---|---|
| 1-50 | 0.836 (n 50) | 0.827 (n 50) | 1.011 (n 50) |
| 51-100 | 0.484 (n 50) | 0.492 (n 50) | 0.983 (n 50) |
| 101-200 | 0.165 (n 100) | 0.183 (n 100) | 0.958 (n 100) |
| 201-300 | 0.039 (n 100) | 0.041 (n 100) | 0.946 (n 100) |
| 301-400 | 0.008 (n 23) | 0.009 (n 23) | 0.927 (n 23) |
| 401+ | — | — | — |

### DLF Values stability (git history) — stable: **True**

days (UTC): 20260925, 20260926, 20260927, 20260928, 20260929; distinct content versions: 5

| band | days | min | max | range |
|---|---|---|---|---|
| 51-100 | 5 | 0.492 | 0.502 | 0.01 |
| 101-200 | 5 | 0.182 | 0.183 | 0.001 |
| 201-300 | 5 | 0.041 | 0.042 | 0.001 |
| 301-400 | 5 | 0.009 | 0.009 | 0.0 |

## E. Point-in-time holdout (archive)

dates: 20260909 … 20260930 (22 days)

### ktcCrowdSfTep — stable: **True**

| band | days | min | max | range |
|---|---|---|---|---|
| 51-100 | 22 | 1.081 | 1.096 | 0.015 |
| 101-200 | 22 | 1.203 | 1.232 | 0.029 |
| 201-300 | 22 | 1.318 | 1.331 | 0.013 |
| 301-400 | 22 | 1.167 | 1.195 | 0.028 |

c1 map forward check (15 pairs, d -> d+7): median |log2 error| out-of-sample 0.0637 vs in-sample 0.0673

### ktcTradesSfTep — stable: **False**

| band | days | min | max | range |
|---|---|---|---|---|
| 51-100 | 22 | 1.161 | 1.204 | 0.043 |
| 101-200 | 22 | 1.236 | 1.285 | 0.049 |
| 201-300 | 22 | 1.376 | 1.425 | 0.049 |
| 301-400 | 22 | 1.35 | 1.466 | 0.116 |

c1 map forward check (15 pairs, d -> d+7): median |log2 error| out-of-sample 0.0417 vs in-sample 0.0369
