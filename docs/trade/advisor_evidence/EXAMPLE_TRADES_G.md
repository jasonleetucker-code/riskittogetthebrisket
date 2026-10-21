### G1 — 2 teams · offense  (`S01`)

Ledger: Jason → Roy: `p:8137`; Roy → Jason: `p:8154`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | George Pickens 6,068→Roy | Brian Robinson 2,265←Roy | 6,068 / 2,265 | 0 / 0 | 6,068 / 2,265 | -3,803 (62.67%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | NO · STRONGLY_UNFAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Roy (7) | Brian Robinson 2,265→Jason | George Pickens 6,068←Jason | 2,265 / 6,068 | 0 / 0 | 2,265 / 6,068 | 3,803 (62.67%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | YES · STRONGLY_FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |

All-team summary lines (asset-only): Jason: Strongly unfavorable. Roy: Strongly favorable.  Overall fairness: `NOT_FAIR` (`not_all_teams_fair`). Conservation: 2 assets, raw 8,333 = 8,333, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **NOT FAIR** — The trade falls outside our fairness threshold for at least one team.

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Roy (7) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |

### G2 — 3 teams · circular  (`S02`)

Ledger: Jason → Collin: `p:12508`; Collin → Roy: `p:8150`; Roy → Jason: `p:11597`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | Jaxson Dart 5,921→Collin | Theo Johnson 2,184←Roy | 5,921 / 2,184 | 0 / 0 | 5,921 / 2,184 | -3,737 (63.11%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | NO · STRONGLY_UNFAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Collin (4) | Kyren Williams 5,668→Roy | Jaxson Dart 5,921←Jason | 5,668 / 5,921 | 0 / 0 | 5,668 / 5,921 | 253 (4.27%) | slight | NOT_FAIR (`outside_fairness_threshold`) | YES · FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Roy (7) | Theo Johnson 2,184→Jason | Kyren Williams 5,668←Collin | 2,184 / 5,668 | 0 / 0 | 2,184 / 5,668 | 3,484 (61.47%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | YES · STRONGLY_FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |

All-team summary lines (asset-only): Jason: Strongly unfavorable. Collin: Favorable. Roy: Strongly favorable.  Overall fairness: `NOT_FAIR` (`not_all_teams_fair`). Conservation: 3 assets, raw 13,773 = 13,773, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **NOT FAIR** — The trade falls outside our fairness threshold for at least one team. _A trade with more than two teams is fair only when it is fair for every team._

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Collin (4) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Roy (7) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |

### G3 — 4 teams · circular  (`S03`)

Ledger: Jason → Collin: `p:6797`; Collin → Roy: `p:8155`; Roy → Ty: `p:12524`; Ty → Jason: `p:11584`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | Justin Herbert 5,853→Collin | Bucky Irving 5,012←Ty | 5,853 / 5,012 | 0 / 0 | 5,853 / 5,012 | -841 (14.37%) | unfair | NOT_FAIR (`outside_fairness_threshold`) | NO · STRONGLY_UNFAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Ty (3) | Bucky Irving 5,012→Jason | Shedeur Sanders 1,988←Roy | 5,012 / 1,988 | 0 / 0 | 5,012 / 1,988 | -3,024 (60.34%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | NO · STRONGLY_UNFAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Collin (4) | Breece Hall 5,578→Roy | Justin Herbert 5,853←Jason | 5,578 / 5,853 | 0 / 0 | 5,578 / 5,853 | 275 (4.7%) | slight | NOT_FAIR (`outside_fairness_threshold`) | YES · FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Roy (7) | Shedeur Sanders 1,988→Ty | Breece Hall 5,578←Collin | 1,988 / 5,578 | 0 / 0 | 1,988 / 5,578 | 3,590 (64.36%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | YES · STRONGLY_FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |

All-team summary lines (asset-only): Jason: Strongly unfavorable. Ty: Strongly unfavorable. Collin: Favorable. Roy: Strongly favorable.  Overall fairness: `NOT_FAIR` (`not_all_teams_fair`). Conservation: 4 assets, raw 18,431 = 18,431, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **NOT FAIR** — The trade falls outside our fairness threshold for at least one team. _A trade with more than two teams is fair only when it is fair for every team._

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Ty (3) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Collin (4) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Roy (7) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |

### G4 — IDP (DL/LB/DB for LB/DB)  (`S07a`)

Ledger: Jason → Collin: `p:13377`; Jason → Collin: `p:8339`; Collin → Jason: `p:10880`; Collin → Jason: `p:11739`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | Arvell Reese 5,090→Collin, Kyle Hamilton 2,825→Collin | Jack Campbell 5,416←Collin, Evan Williams 1,847←Collin | 7,915 / 7,263 | 0 / 215 | 7,915 / 7,478 | -437 (5.52%) | slight | NOT_FAIR (`outside_fairness_threshold`) | NO · UNFAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Collin (4) | Jack Campbell 5,416→Jason, Evan Williams 1,847→Jason | Arvell Reese 5,090←Jason, Kyle Hamilton 2,825←Jason | 7,263 / 7,915 | 215 / 0 | 7,478 / 7,915 | 437 (5.52%) | slight | NOT_FAIR (`outside_fairness_threshold`) | YES · FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |

All-team summary lines (asset-only): Jason: Unfavorable. Collin: Favorable.  Overall fairness: `NOT_FAIR` (`not_all_teams_fair`). Conservation: 4 assets, raw 15,178 = 15,178, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **NOT FAIR** — The trade falls outside our fairness threshold for at least one team.

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Collin (4) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |

### G5 — Picks only (3-team cycle, 2027 1sts)  (`S09`)

Ledger: Jason → Collin: `pick:dynasty_main:2027:r1:o10`; Collin → Roy: `pick:dynasty_main:2027:r1:o4`; Roy → Jason: `pick:dynasty_main:2027:r1:o1`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | 2027 Mid 1st (from Kich) 4,707→Collin | 2027 Mid 1st (from Jason) 4,707←Roy | 4,707 / 4,707 | 0 / 0 | 4,707 / 4,707 | 0 (0.0%) | fair | FAIR (`within_fairness_threshold`) | NO_TOO_CLOSE · APPROXIMATELY_EVEN | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Collin (4) | 2027 Mid 1st (own) 4,707→Roy | 2027 Mid 1st (from Kich) 4,707←Jason | 4,707 / 4,707 | 0 / 0 | 4,707 / 4,707 | 0 (0.0%) | fair | FAIR (`within_fairness_threshold`) | NO_TOO_CLOSE · APPROXIMATELY_EVEN | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Roy (7) | 2027 Mid 1st (from Jason) 4,707→Jason | 2027 Mid 1st (own) 4,707←Collin | 4,707 / 4,707 | 0 / 0 | 4,707 / 4,707 | 0 (0.0%) | fair | FAIR (`within_fairness_threshold`) | NO_TOO_CLOSE · APPROXIMATELY_EVEN | NOT_ENOUGH_EVIDENCE (roster_unknown) |

All-team summary lines (asset-only): Jason: Approximately even. Collin: Approximately even. Roy: Approximately even.  Overall fairness: `FAIR` (`all_teams_fair`). Conservation: 3 assets, raw 14,121 = 14,121, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **FAIR TRADE** — The trade is within our fairness threshold for every team. _A trade with more than two teams is fair only when it is fair for every team._

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | FAIR FOR THIS TEAM | This trade is within our fairness threshold for this team. | — |
| Collin (4) | FAIR FOR THIS TEAM | This trade is within our fairness threshold for this team. | — |
| Roy (7) | FAIR FOR THIS TEAM | This trade is within our fairness threshold for this team. | — |

### G6 — Mixed players + pick, one team to two destinations  (`S04`)

Ledger: Jason → Collin: `p:6794`; Jason → Roy: `p:12514`; Collin → Jason: `p:11564`; Roy → Jason: `pick:dynasty_main:2027:r1:o1`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | Emeka Egbuka 5,197→Roy, Justin Jefferson 7,915→Collin | Drake Maye 8,524←Collin, 2027 Mid 1st (from Jason) 4,707←Roy | 13,112 / 13,231 | 0 / 108 | 13,112 / 13,339 | 227 (1.7%) | fair | FAIR (`within_fairness_threshold`) | NO_TOO_CLOSE · APPROXIMATELY_EVEN | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Collin (4) | Drake Maye 8,524→Jason | Justin Jefferson 7,915←Jason | 8,524 / 7,915 | 0 / 0 | 8,524 / 7,915 | -609 (7.14%) | slight | NOT_FAIR (`outside_fairness_threshold`) | NO · UNFAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Roy (7) | 2027 Mid 1st (from Jason) 4,707→Jason | Emeka Egbuka 5,197←Jason | 4,707 / 5,197 | 0 / 0 | 4,707 / 5,197 | 490 (9.43%) | unfair | NOT_FAIR (`outside_fairness_threshold`) | YES · STRONGLY_FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |

All-team summary lines (asset-only): Jason: Approximately even. Collin: Unfavorable. Roy: Strongly favorable.  Overall fairness: `NOT_FAIR` (`not_all_teams_fair`). Conservation: 4 assets, raw 26,343 = 26,343, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **NOT FAIR** — The trade falls outside our fairness threshold for at least one team. _A trade with more than two teams is fair only when it is fair for every team._

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | FAIR FOR THIS TEAM | This trade is within our fairness threshold for this team. | — |
| Collin (4) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Roy (7) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |

### G7 — Benefits more than one team (asset-only: two YES)  (`S07b`)

Ledger: Jason → Collin: `p:12514`; Collin → Roy: `p:5332`; Collin → Roy: `p:6124`; Roy → Jason: `p:9757`; Roy → Jason: `p:12639`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | Emeka Egbuka 5,197→Collin | Malachi Moore 1,897←Roy, Kendre Miller 1,787←Roy | 5,197 / 3,684 | 393 / 0 | 5,590 / 3,684 | -1,906 (34.1%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | NO · STRONGLY_UNFAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Collin (4) | Foyesade Oluokun 2,950→Roy, Montez Sweat 1,913→Roy | Emeka Egbuka 5,197←Jason | 4,863 / 5,197 | 0 / 421 | 4,863 / 5,618 | 755 (13.44%) | unfair | NOT_FAIR (`outside_fairness_threshold`) | YES · STRONGLY_FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Roy (7) | Malachi Moore 1,897→Jason, Kendre Miller 1,787→Jason | Foyesade Oluokun 2,950←Collin, Montez Sweat 1,913←Collin | 3,684 / 4,863 | 28 / 0 | 3,712 / 4,863 | 1,151 (23.67%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | YES · STRONGLY_FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |

All-team summary lines (asset-only): Jason: Strongly unfavorable. Collin: Strongly favorable. Roy: Strongly favorable.  Overall fairness: `NOT_FAIR` (`not_all_teams_fair`). Conservation: 5 assets, raw 13,744 = 13,744, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **NOT FAIR** — The trade falls outside our fairness threshold for at least one team. _A trade with more than two teams is fair only when it is fair for every team._

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Collin (4) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Roy (7) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |

### G8 — Clearly disadvantages one team (elite for depth)  (`S12`)

Ledger: Jason → Roy: `p:11604`; Roy → Jason: `p:12505`; Roy → Jason: `p:12718`; Roy → Jason: `p:4950`; Roy → Jason: `p:5848`; Roy → Jason: `p:11569`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | Brock Bowers 9,985→Roy | Jarquez Hunter 1,313←Roy, Jalen Royals 1,510←Roy, Konata Mumpfield 1,454←Roy, Christian Kirk 1,407←Roy, Marquise Brown 1,317←Roy | 9,985 / 7,001 | 2,390 / 0 | 12,375 / 7,001 | -5,374 (43.43%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | NO · STRONGLY_UNFAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Roy (7) | Jarquez Hunter 1,313→Jason, Jalen Royals 1,510→Jason, Konata Mumpfield 1,454→Jason, Christian Kirk 1,407→Jason, Marquise Brown 1,317→Jason | Brock Bowers 9,985←Jason | 7,001 / 9,985 | 0 / 2,390 | 7,001 / 12,375 | 5,374 (43.43%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | YES · STRONGLY_FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |

All-team summary lines (asset-only): Jason: Strongly unfavorable. Roy: Strongly favorable.  Overall fairness: `NOT_FAIR` (`not_all_teams_fair`). Conservation: 6 assets, raw 16,986 = 16,986, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **NOT FAIR** — The trade falls outside our fairness threshold for at least one team.

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Roy (7) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |

### G9 — Cannot be evaluated reliably (unpriced rostered player)  (`S15`)

Ledger: Jason → Collin: `p:12514`; Collin → Roy: `p:11539`; Roy → Jason: `p:13307`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | Emeka Egbuka 5,197→Collin | Marlin Klein 1,797←Roy | 5,197 / 1,797 | 0 / 0 | 5,197 / 1,797 | -3,400 (65.42%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | NO · STRONGLY_UNFAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Collin (4) | Jake Bates null→Roy | Emeka Egbuka 5,197←Jason | 0 / 5,197 | 0 / 0 | 0 / 5,197 | null | — | UNABLE (`asset_not_evaluable`) | NOT_ENOUGH_EVIDENCE · UNAVAILABLE · missing: unpriced_assets | NOT_ENOUGH_EVIDENCE (unpriced_assets,roster_unknown) |
| Roy (7) | Marlin Klein 1,797→Jason | Jake Bates null←Collin | 1,797 / 0 | 0 / 0 | 1,797 / 0 | null | — | UNABLE (`asset_not_evaluable`) | NOT_ENOUGH_EVIDENCE · UNAVAILABLE · missing: unpriced_assets | NOT_ENOUGH_EVIDENCE (unpriced_assets,roster_unknown) |

All-team summary lines (asset-only): Jason: Strongly unfavorable. Collin: Unavailable — insufficient evidence. Roy: Unavailable — insufficient evidence.  Overall fairness: `NOT_FAIR` (`not_all_teams_fair`). Conservation: 3 assets, raw 6,994 = 6,994, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **NOT FAIR** — The trade falls outside our fairness threshold for at least one team. _A trade with more than two teams is fair only when it is fair for every team._

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Collin (4) | UNABLE TO DETERMINE | One or more assets this team sends or receives can't be valued right now. | ['p:11539'] |
| Roy (7) | UNABLE TO DETERMINE | One or more assets this team sends or receives can't be valued right now. | ['p:11539'] |

### G10 — Cannot be evaluated reliably (2028/2029 unknown-slot picks: generic rows quarantined)  (`S16`)

Ledger: Roy → Collin: `pick:dynasty_main:2029:r1:o1`; Roy → Collin: `pick:dynasty_main:2028:r2:o1`; Collin → Roy: `p:6804`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Collin (4) | Jordan Love 5,849→Roy | 2028 Mid 2nd (from Jason) 3,063←Roy, 2029 Mid 1st (from Jason) 4,136←Roy | 5,849 / 7,199 | 674 / 0 | 6,523 / 7,199 | null | — | UNABLE (`evaluation_unavailable`) | NOT_ENOUGH_EVIDENCE · UNAVAILABLE · missing: quarantined_values | NOT_ENOUGH_EVIDENCE (quarantined_values,roster_unknown) |
| Roy (7) | 2028 Mid 2nd (from Jason) 3,063→Collin, 2029 Mid 1st (from Jason) 4,136→Collin | Jordan Love 5,849←Collin | 7,199 / 5,849 | 0 / 674 | 7,199 / 6,523 | null | — | UNABLE (`evaluation_unavailable`) | NOT_ENOUGH_EVIDENCE · UNAVAILABLE · missing: quarantined_values | NOT_ENOUGH_EVIDENCE (quarantined_values,roster_unknown) |

All-team summary lines (asset-only): Collin: Unavailable — insufficient evidence. Roy: Unavailable — insufficient evidence.  Overall fairness: `UNABLE` (`evidence_insufficient`). Conservation: 3 assets, raw 13,048 = 13,048, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **UNABLE TO DETERMINE** — There isn't enough reliable information to judge this whole trade.

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Collin (4) | UNABLE TO DETERMINE | This trade can't be evaluated reliably right now. | — |
| Roy (7) | UNABLE TO DETERMINE | This trade can't be evaluated reliably right now. | — |

### G11 — 4 teams · offense + IDP + picks (partly unevaluable)  (`S19`)

Ledger: Jason → Ty: `p:8137`; Jason → Roy: `p:12578`; Ty → Collin: `p:8138`; Ty → Jason: `pick:dynasty_main:2028:r1:o3`; Collin → Jason: `p:6804`; Collin → Ty: `p:13340`; Roy → Collin: `p:12509`; Roy → Ty: `pick:dynasty_main:2028:r2:o1`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | Carson Schwesinger 6,229→Roy, George Pickens 6,068→Ty | Jordan Love 5,849←Collin, 2028 Mid 1st (own) 4,747←Ty | 12,297 / 10,596 | 0 / 291 | 12,297 / 10,887 | null | — | UNABLE (`evaluation_unavailable`) | NOT_ENOUGH_EVIDENCE · UNAVAILABLE · missing: quarantined_values | NOT_ENOUGH_EVIDENCE (quarantined_values,roster_unknown) |
| Ty (3) | James Cook 6,784→Collin, 2028 Mid 1st (own) 4,747→Jason | Rueben Bain 2,324←Collin, George Pickens 6,068←Jason, 2028 Mid 2nd (from Jason) 3,063←Roy | 11,531 / 11,455 | 540 / 0 | 12,071 / 11,455 | null | — | UNABLE (`evaluation_unavailable`) | NOT_ENOUGH_EVIDENCE · UNAVAILABLE · missing: quarantined_values | NOT_ENOUGH_EVIDENCE (quarantined_values,roster_unknown) |
| Collin (4) | Rueben Bain 2,324→Ty, Jordan Love 5,849→Jason | Tre' Harris 2,387←Roy, James Cook 6,784←Ty | 8,173 / 9,171 | 14 / 0 | 8,187 / 9,171 | 984 (10.73%) | unfair | NOT_FAIR (`outside_fairness_threshold`) | YES · STRONGLY_FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Roy (7) | Tre' Harris 2,387→Collin, 2028 Mid 2nd (from Jason) 3,063→Ty | Carson Schwesinger 6,229←Jason | 5,450 / 6,229 | 0 / 525 | 5,450 / 6,754 | null | — | UNABLE (`evaluation_unavailable`) | NOT_ENOUGH_EVIDENCE · UNAVAILABLE · missing: quarantined_values | NOT_ENOUGH_EVIDENCE (quarantined_values,roster_unknown) |

All-team summary lines (asset-only): Jason: Unavailable — insufficient evidence. Ty: Unavailable — insufficient evidence. Collin: Strongly favorable. Roy: Unavailable — insufficient evidence.  Overall fairness: `NOT_FAIR` (`not_all_teams_fair`). Conservation: 8 assets, raw 37,451 = 37,451, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **NOT FAIR** — The trade falls outside our fairness threshold for at least one team. _A trade with more than two teams is fair only when it is fair for every team._

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | UNABLE TO DETERMINE | This trade can't be evaluated reliably right now. | — |
| Ty (3) | UNABLE TO DETERMINE | This trade can't be evaluated reliably right now. | — |
| Collin (4) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Roy (7) | UNABLE TO DETERMINE | This trade can't be evaluated reliably right now. | — |

### G12 — Exceeds roster limits (forced drop; fairness unaffected)  (`S17`)

Ledger: Jason → Roy: `p:12508`; Jason → Roy: `p:12490`; Roy → Jason: `p:8154`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | Bhayshul Tuten 4,604→Roy, Jaxson Dart 5,921→Roy | Brian Robinson 2,265←Roy | 10,525 / 2,265 | 0 / 1,013 | 10,525 / 3,278 | -7,247 (68.86%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | NO · STRONGLY_UNFAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Roy (7) | Brian Robinson 2,265→Jason | Bhayshul Tuten 4,604←Jason, Jaxson Dart 5,921←Jason | 2,265 / 10,525 | 1,013 / 0 | 3,278 / 10,525 | 7,247 (68.86%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | YES · STRONGLY_FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |

Roster capacity, Jason: `{"rosterLimit": 58, "sizeBefore": 58, "sizeAfter": 57, "overLimitAfter": 0, "requiresDrops": false, "forcedDropValue": 0.0}`; forced drops `[]`

Roster capacity, Roy: `{"rosterLimit": 58, "sizeBefore": 58, "sizeAfter": 59, "overLimitAfter": 1, "requiresDrops": true, "forcedDropValue": 1737.0}`; forced drops `[['Anthony Richardson', 1737.0]]`

All-team summary lines (asset-only): Jason: Strongly unfavorable. Roy: Strongly favorable.  Overall fairness: `NOT_FAIR` (`not_all_teams_fair`). Conservation: 3 assets, raw 12,790 = 12,790, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **NOT FAIR** — The trade falls outside our fairness threshold for at least one team.

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Roy (7) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |

### G13 — Stale roster ownership (fails closed everywhere)  (`S20-stale`)

Ledger: Jason → Collin: `p:12508`; Collin → Roy: `p:8150`; Roy → Jason: `p:11597`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | Jaxson Dart 5,921→Collin | Theo Johnson 2,184←Roy | 5,921 / 2,184 | 0 / 0 | 5,921 / 2,184 | null | — | UNABLE (`ownership_unverifiable`) | NOT_ENOUGH_EVIDENCE · UNAVAILABLE · missing: ownership_unverifiable,roster_unknown | NOT_ENOUGH_EVIDENCE (ownership_unverifiable,roster_unknown) |
| Collin (4) | Kyren Williams 5,668→Roy | Jaxson Dart 5,921←Jason | 5,668 / 5,921 | 0 / 0 | 5,668 / 5,921 | null | — | UNABLE (`ownership_unverifiable`) | NOT_ENOUGH_EVIDENCE · UNAVAILABLE · missing: ownership_unverifiable,roster_unknown | NOT_ENOUGH_EVIDENCE (ownership_unverifiable,roster_unknown) |
| Roy (7) | Theo Johnson 2,184→Jason | Kyren Williams 5,668←Collin | 2,184 / 5,668 | 0 / 0 | 2,184 / 5,668 | null | — | UNABLE (`ownership_unverifiable`) | NOT_ENOUGH_EVIDENCE · UNAVAILABLE · missing: ownership_unverifiable,roster_unknown | NOT_ENOUGH_EVIDENCE (ownership_unverifiable,roster_unknown) |

All-team summary lines (asset-only): Jason: Unavailable — insufficient evidence. Collin: Unavailable — insufficient evidence. Roy: Unavailable — insufficient evidence.  Overall fairness: `UNABLE` (`evidence_insufficient`). Conservation: 3 assets, raw 13,773 = 13,773, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **UNABLE TO DETERMINE** — There isn't enough reliable information to judge this whole trade. _A trade with more than two teams is fair only when it is fair for every team._

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | UNABLE TO DETERMINE | We couldn't confirm who owns every asset this team sends or receives. | ['p:11597', 'p:12508'] |
| Collin (4) | UNABLE TO DETERMINE | We couldn't confirm who owns every asset this team sends or receives. | ['p:12508', 'p:8150'] |
| Roy (7) | UNABLE TO DETERMINE | We couldn't confirm who owns every asset this team sends or receives. | ['p:11597', 'p:8150'] |
