| area | requirement | status | evidence |
|---|---|---|---|
| A | one canonical value per asset; no offense-only second board | PASS | apply_valuation_factors absent=True; second-value keys on 1094 live rows: none |
| A | canonical 1-9999 scale has a single owner | PASS | scale imported from player_valuation (1-9999), not restated: True |
| A | rejected league-adjusted methodology stays withdrawn | PASS | withdrawal stamped at 2 server sites; valuation_factors seam deleted from data_contract=True |
| B | provider families declared | PASS | 21 sources collapse to 13 independent families; 13 sources declared into 5 multi-board providers ['dlf', 'draftSharks', 'fantasyPros', 'flockFantasy', 'ktc'] |
| B | family collapse is a SELECTION, never an average | PASS | no averaging in the collapse: True |
| B | the blend consumes families, not raw keys | PASS | blend calls the collapse |
| C | market gap splits retail/consensus by FAMILY | PASS | retail side expanded across families |
| D | every threshold records unit + derivation | PASS | 17 thresholds, all with unit + derivation: True |
| D | ROS gates are percentiles, not index points | PASS | 4 ROS thresholds; ROS_DEPTH_BAND_LOW_PERCENTILE=percentile, ROS_ELITE_PERCENTILE=percentile, ROS_SELLER_PERCENTILE_GAP=percentilePoints, ROS_STRONG_PERCENTILE=percentile |
| E | Second Opinions declares a value basis; panel ignores display mode | PASS | basis type exists=True; panel CODE free of the display valueMode=True |
| F | the max-minus-min rule and its constants are gone | PASS | old rule + constants gone=True; confidence.py owns it=True |
| F | five axes | PASS | axes=['independence', 'coverage', 'freshness', 'applicability', 'agreement'] |
| F | no frontend confidence math (parameters not mirrored) | PASS | gate parameters absent from the frontend mirror: True |
| F | every gate parameter declares unit + derivation | PASS | 5 parameters, all declared: True |
| F | post-blend overrides re-state confidence | PASS | post-blend override re-states confidence |
| G | unpriced renders as unknown, not zero | PASS | formatBoardValue + unpricedAssetsOnSide exist=True; displayValue nulls=True |
| G | the unpriced predicate has production consumers | PASS | production consumers of isUnpricedBoardRow: ['trade-sections.jsx'] |
| H | the contract validator enforces the canonical scale | PASS | validator enforces the canonical scale |
| H | the live board builds, in range, with confidence axes | PASS | 1094 rows, 812 priced, all in [1,9999]=True; buckets={'none': 306, 'low': 179, 'high': 255, 'medium': 354}; rows with axes=709 |
| H | the board is deterministic across builds | PASS | back-to-back builds differ on: nothing |

TOTAL 20 checks · PASS 20 · FAIL 0
