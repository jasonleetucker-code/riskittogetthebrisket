# BDVM scoring census (LOCAL)

- census: `bdvm-scoring-census.v1` · generated `2026-10-01T09:12:58.843726+00:00`
- code: `b57bab6f9b5b5a3568e8fc564dcc24fbaec0713d` (dirty=False)
- realized history: 19422 nflverse weekly rows, season 2025 + play-by-play supplement

Weights are the card's own rates; `points` are SIGNED realized 2025 REG points under that card. A partial total is not a lower bound: omitted penalties (negative weights) overstate it.

## dynasty_main (Sleeper 1312006700437352448)

Card fetched `2026-09-26T07:10:26.355538+00:00`, fingerprint `sf1:9e51824690d091f9`, 86 nonzero rules, idpEnabled=True. Classes: {'MAPPING_ERROR': 0, 'UNSUPPORTED_VOCABULARY': 21, 'ABSENT_FIELD': 7, 'SUPPORTED': 21, 'NOT_APPLICABLE': 37}.

| priority | key | weight | class | families | sources | capability | realized pts | affected / eligible | share | silent? |
|---|---|---|---|---|---|---|---|---|---|---|
| 12486.8 | `idp_pass_def` | 5.3 | ABSENT_FIELD | DB,DL,LB | clayIdp:none, idpShow:direct | manualCsv:direct, reconstructedBaseline:direct | 12486.8 | 577 / 1034 | 15.58% | SILENT |
| 10977.4 | `idp_tkl_loss` | 4.24 | ABSENT_FIELD | DB,DL,LB | clayIdp:none, idpShow:direct | manualCsv:direct, reconstructedBaseline:direct | 10977.4 | 642 / 1034 | 13.69% | SILENT |
| 6438.4 | `idp_qb_hit` | 2.12 | ABSENT_FIELD | DB,DL,LB | clayIdp:none, idpShow:direct | manualCsv:direct, reconstructedBaseline:direct | 6438.44 | 531 / 1034 | 8.03% | SILENT |
| 2478.0 | `rec_10_19` | 0.75 | UNSUPPORTED_VOCABULARY | QB,RB,TE,WR | clayOffense:none | manualCsv:none, reconstructedBaseline:direct | 2478 | 391 / 610 | 4.67% | reported |
| 2475.1 | `st_tkl_solo` | 1.33 | UNSUPPORTED_VOCABULARY | DB,DL,LB,QB,RB,TE,WR | clayOffense:none, clayIdp:none, idpShow:none | manualCsv:none, reconstructedBaseline:direct | 2475.13 | 543 / 1644 | 1.86% | reported |
| 1898.0 | `rec_5_9` | 0.5 | UNSUPPORTED_VOCABULARY | QB,RB,TE,WR | clayOffense:none | manualCsv:none, reconstructedBaseline:direct | 1898 | 403 / 610 | 3.58% | reported |
| 1795.6 | `kr_yd` | 0.0333333 | UNSUPPORTED_VOCABULARY | DB,DL,LB,QB,RB,TE,WR | clayOffense:none, clayIdp:none, idpShow:none | manualCsv:direct, reconstructedBaseline:direct | 1795.63 | 166 / 1644 | 1.35% | SILENT |
| 1505.2 | `idp_ff` | 4.24 | ABSENT_FIELD | DB,DL,LB | clayIdp:none, idpShow:direct | manualCsv:direct, reconstructedBaseline:direct | 1505.2 | 258 / 1034 | 1.88% | SILENT |
| 980.0 | `rec_20_29` | 1 | UNSUPPORTED_VOCABULARY | QB,RB,TE,WR | clayOffense:none | manualCsv:none, reconstructedBaseline:direct | 980 | 273 / 610 | 1.85% | reported |
| 964.0 | `fum_lost` | -4 | UNSUPPORTED_VOCABULARY | QB,RB,TE,WR | clayOffense:none | manualCsv:direct, reconstructedBaseline:direct | -964 | 155 / 610 | -1.82% | SILENT |
| 918.3 | `idp_sack_yd` | 0.111111 | UNSUPPORTED_VOCABULARY | DB,DL,LB | clayIdp:none, idpShow:none | manualCsv:direct, reconstructedBaseline:direct | 918.34 | 417 / 1034 | 1.15% | SILENT |
| 749.6 | `idp_fum_rec` | 3.19 | ABSENT_FIELD +baselineMapErr | DB,DL,LB | clayIdp:none, idpShow:direct | manualCsv:direct, reconstructedBaseline:direct | 749.65 | 199 / 1034 | 0.94% | SILENT |
| 536.8 | `rec_0_4` | 0.25 | UNSUPPORTED_VOCABULARY | QB,RB,TE,WR | clayOffense:none | manualCsv:none, reconstructedBaseline:direct | 536.75 | 379 / 610 | 1.01% | reported |
| 536.1 | `idp_int_ret_yd` | 0.111111 | UNSUPPORTED_VOCABULARY | DB,DL,LB | clayIdp:none, idpShow:none | manualCsv:direct, reconstructedBaseline:direct | 536.12 | 151 / 1034 | 0.67% | SILENT |
| 452.0 | `rec_40p` | 2 | UNSUPPORTED_VOCABULARY | QB,RB,TE,WR | clayOffense:none | manualCsv:none, reconstructedBaseline:direct | 452 | 130 / 610 | 0.85% | reported |
| 418.8 | `rec_30_39` | 1.25 | UNSUPPORTED_VOCABULARY | QB,RB,TE,WR | clayOffense:none | manualCsv:none, reconstructedBaseline:direct | 418.75 | 175 / 610 | 0.79% | reported |
| 281.8 | `pr_yd` | 0.0333333 | UNSUPPORTED_VOCABULARY | DB,DL,LB,QB,RB,TE,WR | clayOffense:none, clayIdp:none, idpShow:none | manualCsv:direct, reconstructedBaseline:direct | 281.77 | 68 / 1644 | 0.21% | SILENT |
| 217.3 | `idp_blk_kick` | 5.3 | UNSUPPORTED_VOCABULARY | DB,DL,LB | clayIdp:none, idpShow:none | manualCsv:direct, reconstructedBaseline:direct | 217.3 | 36 / 1034 | 0.27% | SILENT |
| 178.1 | `idp_def_td` | 6.36 | ABSENT_FIELD | DB,DL,LB | clayIdp:none, idpShow:direct | manualCsv:direct, reconstructedBaseline:direct | 178.08 | 27 / 1034 | 0.22% | SILENT |
| 162.0 | `st_td` | 6 | UNSUPPORTED_VOCABULARY | DB,DL,LB,QB,RB,TE,WR | clayOffense:none, clayIdp:none, idpShow:none | manualCsv:direct, reconstructedBaseline:direct | 162 | 21 / 1644 | 0.12% | SILENT |
| 136.0 | `st_ff` | 4.25 | UNSUPPORTED_VOCABULARY | DB,DL,LB,QB,RB,TE,WR | clayOffense:none, clayIdp:none, idpShow:none | manualCsv:none, reconstructedBaseline:direct | 136 | 32 / 1644 | 0.10% | reported |
| 93.9 | `idp_fum_ret_yd` | 0.111111 | UNSUPPORTED_VOCABULARY +baselineMapErr | DB,DL,LB | clayIdp:none, idpShow:none | manualCsv:direct, reconstructedBaseline:direct | 93.88 | 59 / 1034 | 0.12% | SILENT |
| 84.0 | `pass_2pt` | 2 | UNSUPPORTED_VOCABULARY | QB,RB,TE,WR | clayOffense:none | manualCsv:direct, reconstructedBaseline:direct | 84 | 30 / 610 | 0.16% | SILENT |
| 84.0 | `rec_2pt` | 2 | UNSUPPORTED_VOCABULARY | QB,RB,TE,WR | clayOffense:none | manualCsv:direct, reconstructedBaseline:direct | 84 | 39 / 610 | 0.16% | SILENT |
| 82.9 | `st_fum_rec` | 3.19 | UNSUPPORTED_VOCABULARY | DB,DL,LB,QB,RB,TE,WR | clayOffense:none, clayIdp:none, idpShow:none | manualCsv:none, reconstructedBaseline:direct | 82.94 | 26 / 1644 | 0.06% | reported |
| 56.0 | `pass_int_td` | -2 | UNSUPPORTED_VOCABULARY | QB,RB,TE,WR | clayOffense:none | manualCsv:none, reconstructedBaseline:direct | -56 | 24 / 610 | -0.11% | reported |
| 47.7 | `idp_safe` | 5.3 | ABSENT_FIELD | DB,DL,LB | clayIdp:none, idpShow:direct | manualCsv:direct, reconstructedBaseline:direct | 47.7 | 9 / 1034 | 0.06% | SILENT |
| 34.0 | `rush_2pt` | 2 | UNSUPPORTED_VOCABULARY | QB,RB,TE,WR | clayOffense:none | manualCsv:direct, reconstructedBaseline:direct | 34 | 15 / 610 | 0.06% | SILENT |
| 0.0 | `bonus_fd_qb` | 0.4 | SUPPORTED | QB | clayOffense:imputed | manualCsv:direct, reconstructedBaseline:direct | 2282 | 74 / 81 | 21.84% |  |
| 0.0 | `bonus_fd_rb` | 1 | SUPPORTED | RB | clayOffense:imputed | manualCsv:direct, reconstructedBaseline:direct | 2984 | 127 / 151 | 20.04% |  |
| 0.0 | `bonus_fd_te` | 1 | SUPPORTED | TE | clayOffense:imputed | manualCsv:direct, reconstructedBaseline:direct | 1280 | 110 / 137 | 16.56% |  |
| 0.0 | `bonus_fd_wr` | 1 | SUPPORTED | WR | clayOffense:imputed | manualCsv:direct, reconstructedBaseline:direct | 3254 | 207 / 241 | 16.28% |  |
| 0.0 | `bonus_rec_wr` | 0.02 | SUPPORTED | WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | 119.54 | 217 / 241 | 0.60% |  |
| 0.0 | `idp_int` | 5.3 | SUPPORTED | DB,DL,LB | clayIdp:direct, idpShow:direct | manualCsv:direct, reconstructedBaseline:direct | 2014 | 221 / 1034 | 2.51% |  |
| 0.0 | `idp_sack` | 2.92 | SUPPORTED | DB,DL,LB | clayIdp:direct, idpShow:direct | manualCsv:direct, reconstructedBaseline:direct | 3728.84 | 439 / 1034 | 4.65% |  |
| 0.0 | `idp_tkl_ast` | 0.8 | SUPPORTED | DB,DL,LB | clayIdp:direct, idpShow:direct | manualCsv:direct, reconstructedBaseline:direct | 12697.6 | 983 / 1034 | 15.84% |  |
| 0.0 | `idp_tkl_solo` | 1.33 | SUPPORTED | DB,DL,LB | clayIdp:direct, idpShow:direct | manualCsv:direct, reconstructedBaseline:direct | 26020.1 | 984 / 1034 | 32.46% |  |
| 0.0 | `pass_cmp` | 0.37 | SUPPORTED | QB,RB,TE,WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | 4149.18 | 82 / 610 | 7.82% |  |
| 0.0 | `pass_inc` | -0.67 | SUPPORTED | QB,RB,TE,WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | -4167.4 | 86 / 610 | -7.85% |  |
| 0.0 | `pass_int` | -4 | SUPPORTED | QB,RB,TE,WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | -1520 | 63 / 610 | -2.86% |  |
| 0.0 | `pass_sack` | -1 | SUPPORTED | QB,RB,TE,WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | -1286 | 69 / 610 | -2.42% |  |
| 0.0 | `pass_td` | 6 | SUPPORTED | QB,RB,TE,WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | 4866 | 65 / 610 | 9.17% |  |
| 0.0 | `pass_yd` | 0.04 | SUPPORTED | QB,RB,TE,WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | 4894.64 | 82 / 610 | 9.22% |  |
| 0.0 | `rec` | 0.1 | SUPPORTED | QB,RB,TE,WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | 1113 | 461 / 610 | 2.10% |  |
| 0.0 | `rec_td` | 6 | SUPPORTED | QB,RB,TE,WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | 4812 | 261 / 610 | 9.07% |  |
| 0.0 | `rec_yd` | 0.1 | SUPPORTED | QB,RB,TE,WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | 12167.8 | 460 / 610 | 22.93% |  |
| 0.0 | `rush_att` | 0.01 | SUPPORTED | QB,RB,TE,WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | 145.61 | 322 / 610 | 0.27% |  |
| 0.0 | `rush_td` | 6 | SUPPORTED | QB,RB,TE,WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | 3036 | 137 / 610 | 5.72% |  |
| 0.0 | `rush_yd` | 0.1 | SUPPORTED | QB,RB,TE,WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | 6355 | 318 / 610 | 11.98% |  |

NOT_APPLICABLE (37): `blk_kick`, `def_2pt`, `def_3_and_out`, `def_4_and_stop`, `def_forced_punts`, `def_kr_yd`, `def_pr_yd`, `def_st_ff`, `def_st_fum_rec`, `def_st_td`, `def_td`, `fg_ret_yd`, `fgm_yds`, `fgmiss_0_19`, `fgmiss_20_29`, `fgmiss_30_39`, `fgmiss_40_49`, `fgmiss_50_59`, `fgmiss_60p`, `fum_rec`, `fum_rec_td`, `fum_ret_yd`, `int`, `int_ret_yd`, `pts_allow`, `pts_allow_0`, `pts_allow_14_20`, `pts_allow_1_6`, `pts_allow_21_27`, `pts_allow_28_34`, `pts_allow_35p`, `pts_allow_7_13`, `sack_yd`, `safe`, `xpm`, `xpmiss`, `yds_allow`

## dynasty_new (Sleeper 1320092771247222784)

Card fetched `2026-09-26T07:10:29.389066+00:00`, fingerprint `sf1:82a5f8ef2bfdb098`, 41 nonzero rules, idpEnabled=False. Classes: {'MAPPING_ERROR': 0, 'UNSUPPORTED_VOCABULARY': 7, 'ABSENT_FIELD': 0, 'SUPPORTED': 9, 'NOT_APPLICABLE': 25}.

| priority | key | weight | class | families | sources | capability | realized pts | affected / eligible | share | silent? |
|---|---|---|---|---|---|---|---|---|---|---|
| 482.0 | `fum_lost` | -2 | UNSUPPORTED_VOCABULARY | QB,RB,TE,WR | clayOffense:none | manualCsv:direct, reconstructedBaseline:direct | -482 | 155 / 610 | -1.04% | SILENT |
| 114.0 | `st_td` | 6 | UNSUPPORTED_VOCABULARY | QB,RB,TE,WR | clayOffense:none | manualCsv:direct, reconstructedBaseline:direct | 114 | 14 / 610 | 0.24% | SILENT |
| 84.0 | `pass_2pt` | 2 | UNSUPPORTED_VOCABULARY | QB,RB,TE,WR | clayOffense:none | manualCsv:direct, reconstructedBaseline:direct | 84 | 30 / 610 | 0.18% | SILENT |
| 84.0 | `rec_2pt` | 2 | UNSUPPORTED_VOCABULARY | QB,RB,TE,WR | clayOffense:none | manualCsv:direct, reconstructedBaseline:direct | 84 | 39 / 610 | 0.18% | SILENT |
| 34.0 | `rush_2pt` | 2 | UNSUPPORTED_VOCABULARY | QB,RB,TE,WR | clayOffense:none | manualCsv:direct, reconstructedBaseline:direct | 34 | 15 / 610 | 0.07% | SILENT |
| 5.0 | `st_fum_rec` | 1 | UNSUPPORTED_VOCABULARY | QB,RB,TE,WR | clayOffense:none | manualCsv:none, reconstructedBaseline:direct | 5 | 5 / 610 | 0.01% | reported |
| 4.0 | `st_ff` | 1 | UNSUPPORTED_VOCABULARY | QB,RB,TE,WR | clayOffense:none | manualCsv:none, reconstructedBaseline:direct | 4 | 4 / 610 | 0.01% | reported |
| 0.0 | `bonus_rec_te` | 0.5 | SUPPORTED | TE | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | 1433.5 | 122 / 137 | 16.58% |  |
| 0.0 | `pass_int` | -1 | SUPPORTED | QB,RB,TE,WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | -380 | 63 / 610 | -0.82% |  |
| 0.0 | `pass_td` | 4 | SUPPORTED | QB,RB,TE,WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | 3244 | 65 / 610 | 6.97% |  |
| 0.0 | `pass_yd` | 0.04 | SUPPORTED | QB,RB,TE,WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | 4894.64 | 82 / 610 | 10.52% |  |
| 0.0 | `rec` | 1 | SUPPORTED | QB,RB,TE,WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | 11130 | 461 / 610 | 23.92% |  |
| 0.0 | `rec_td` | 6 | SUPPORTED | QB,RB,TE,WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | 4812 | 261 / 610 | 10.34% |  |
| 0.0 | `rec_yd` | 0.1 | SUPPORTED | QB,RB,TE,WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | 12167.8 | 460 / 610 | 26.15% |  |
| 0.0 | `rush_td` | 6 | SUPPORTED | QB,RB,TE,WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | 3036 | 137 / 610 | 6.52% |  |
| 0.0 | `rush_yd` | 0.1 | SUPPORTED | QB,RB,TE,WR | clayOffense:direct | manualCsv:direct, reconstructedBaseline:direct | 6355 | 318 / 610 | 13.66% |  |

NOT_APPLICABLE (25): `blk_kick`, `def_st_ff`, `def_st_fum_rec`, `def_st_td`, `def_td`, `ff`, `fgm_0_19`, `fgm_20_29`, `fgm_30_39`, `fgm_40_49`, `fgm_50p`, `fgmiss`, `fum_rec`, `fum_rec_td`, `int`, `pts_allow_0`, `pts_allow_14_20`, `pts_allow_1_6`, `pts_allow_28_34`, `pts_allow_35p`, `pts_allow_7_13`, `sack`, `safe`, `xpm`, `xpmiss`

