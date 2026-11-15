# Source-math diagnosis, 2026-11-08

Priority 6 of the unified directive (`docs/owner/UNIFIED_ENGINEERING_FORECASTING_DIRECTIVE_2026-11-08.md`, row MD-106).
Read-only. No value, weight, flag or file under `src/` changed. `src/api/data_contract.py` is protected methodology, so
any change below needs an owner decision.

**How measured.** `build_api_data_contract` run locally on `exports/latest/dynasty_data_2026-11-08.json`, on the
`origin/main` tree of about 16:15Z. This is one board, built against the CSVs and dataset state of that tree. Counts move
with each refresh.

## 1. IDP anchor weight: the audit's figure did not reproduce

The Top 20 audit reported a measured implied α of 0.55 on 272 IDP rows, against a documented 0.10.

| measure | result |
|---|---|
| IDP rows with an anchor and a subgroup that differ | 265 |
| implied α = (blend − anchor) / (subgroup − anchor), median | 0.100 |
| p10 / p90 | 0.095 / 0.105 |

The code (`center_value = anchor_value + _ALPHA_SHRINKAGE * subgroup_delta`) and the stamped row values agree with the
documentation. The small spread is rounding on integer stamps. The audit's 0.55 may have measured something else, such as
the subgroup's share of voting weight; that was not established.

**Disposition:** no defect in α. The documentation stays as it is.

**The related question that remains.** α is a constant, so the anchor keeps 90% of the blend however stale it becomes.
This is dormant for player rows today: `idpTradeCalc` carried an effective weight of 1.0 on all 259 IDP rows measured. The
gap between anchor and subgroup is large enough to matter if that changes (median 17%, p90 52% of the anchor). Whether α
should fall with anchor staleness is a methodology question.

## 2. Single-source haircut: deliberate design with no expiry

A row that rests on one provider keeps 30% of its value, but a source withheld for staleness counts as present evidence.
So a row with one real vote and one withheld vote skips the haircut.

| measure | result |
|---|---|
| rows with exactly one voter, a withheld source, and no haircut | 28 (the audit counted 13 on an earlier board) |
| position | LB 14, DB 10, DL 4 |
| value range | 758 to 1,917 |
| ranked / best rank | 13 ranked / 345 |
| confidence | all `low` |
| pattern, in the 8 rows inspected | `idpTradeCalc` voting, `idpShowCombined` withheld |

This is intended behavior, not a bug. The comment at the haircut (2026-09-23) explains it: without it, a source crossing
the quarantine line would drop a row's value to 30% in one step, the cliff the freshness curve exists to avoid.

**The real gap is that the rule has no end.** It makes sense for a source that went stale recently. `idpShowCombined` has
been quarantined since its 2026-08-19 update (`docs/sources/REHABILITATION_REVIEW_2026-11-06.md`), so these rows have had
one live opinion for about 80 days and are still priced as if corroborated.

**Options (owner decision, none applied):**
1. Keep it. The rows are already labelled `low`, and the thinness is reported.
2. Let a withheld source stop counting after a fixed horizon, and fade the haircut in over that period so no cliff returns.
3. Leave values alone and stamp these rows as single-opinion, using the existing `limitedEvidence` stamp.

**Recommendation:** option 3 first, because it changes no value and makes the state visible. Consider option 2 after
measuring how many rows it moves and by how much.

## 3. A blend property worth keeping in mind

Lowering every rank-Hill vote cannot raise a row unless the outlier filter keeps a different set of votes, because every
order statistic of a weakly lower vote vector is weakly lower. On 2026-11-08 this was observed directly: under a lower
curve, one row rose from 643 to 696 because a vote the filter had dropped was kept. A challenger curve can therefore change
**who votes** as well as how much each vote is worth. `docs/valuation/methodology_proposals/W30_F008_HILL_DENOMINATOR.md`
reaches the same conclusion from board-level evidence.
