# DLF Trade Analyzer Values: normalization gate, first measurement (2026-09-25)

**Status: measurement record. DLF Values remain NON-VOTING.** Nothing here changes a vote. The
owner's binding gate rules are in `docs/OWNER_REQUESTED_TODO.md` ("DLF Values normalization — owner
decision 2026-09-24"). The candidate that best preserves DLF's independent information wins. Hampel
rejection is a diagnostic, not the objective. DLF may disagree with KTC; there is no tuning to KTC and
no circular target.

## Inputs (pinned)

- **Capture:** `CSVs/site_raw/dlfValuesSfTep.csv`, first captured 2026-09-25 00:28Z (commit
  `b6a962e96`). Later refreshes re-stamped it without a content change. 322 rows (QB 56, RB 91,
  TE 47, WR 128), top 984.7047, minimum 0.0063, 0 file-order inversions, 1 tied value.
- **Repo:** main at `b4a982efd`, with family-capped voting (#1427) live.
- **Board payload:** `dynasty_export_20260925_005406.zip`.
- **Reproduce:** `python scripts/dlf_values_gate.py` (writes a JSON report; changes nothing in the
  repo).

## Candidates

| candidate | keeps from DLF | target / circularity |
|---|---|---|
| raw / max × 9999 | ordering **and** spacing (linear, exact by construction) | none |
| rank → Hill (**control**) | ordering only; spacing from the live OFFENSE Hill master | master is trained on native-value boards, not our board |
| quantile mapping | ordering only | the declared independent target is the Hill master, **which makes it identical to rank → Hill**. Any other target imports another market's spacing or reads our own board (circular), so it is not run separately |

## Results

| criterion | raw / max | rank → Hill |
|---|---|---|
| Ordering vs DLF Rank (288 matched) | identical to the control | Spearman **0.970**, discordant pairs **7.1%**, median rank displacement 13 (p90 40), top-24/50/100/200 overlap 0.875 / 0.90 / 0.91 / 0.945 |
| New vs duplicate | — | control vs DLF Rank's own rank→Hill value: median **8.3%** apart (p90 18.1%, max 34.6%). **Not a duplicate:** DLF's trade-value order differs from its expert-rank order |
| Spacing vs DLF Rank's Hill value | median **−79.6%** (p10 −96.9%, p90 −19.1%) | — |
| Curve shape | DLF's own Hill fit c = 0.062, **s = 1.69**; value at p = .10 / .30 / .50 is 3375 / 442 / **65**, against the live master's 5264 / 2472 / 1570 (c = 0.110, s = 1.110) | master by construction |
| RMSE vs live master | **1741.8**, against other native boards' 495–1952 (Dynasty Nerds, a master trainer, is 1952). Against the pending Autopilot challenger (0.066 / 1.085): 932.8 | — |
| Hampel drop rate (diagnostic) | **0.91** | **0.00** |
| Board impact (1,039 rows) | 50 changed, median −0.6%, max 4.3%, top-50 max 3.1% | 340 changed, median 0.26%, p90 1.31%, max 3.87%, top-50 max 1.53% |
| Family cap with DLF Rank | each member at 0.5 (median `familyAdjustment`) | each member at 0.5 |
| Circularity | none | none |
| Capture stability | **untested** (one content version) | **untested** |

## Reading (evidence only; the vote is an owner decision)

1. **raw / max is pathological in aggregation.** It isn't rejected for disagreeing with KTC. DLF's
   trade-analyzer scale values a median-ranked player at 0.65% of the top player, where the
   consensus says 15.7%, roughly 24× steeper through the middle of the board. So 91% of its votes
   cannot enter the blend at all, and the ones that do pull values down. In practice it does not
   deliver DLF's information to the board.
2. **rank → Hill is the only viable candidate.** It carries genuinely distinct ordering information
   versus DLF Rank but discards DLF's spacing. Inside the family cap it would share DLF's one
   provider weight with DLF Rank.
3. **Capture stability cannot be judged from one capture.** Re-run after several distinct content
   versions.
4. **Recommendation:** keep DLF Values **non-voting** now. After enough captures, the owner decides
   between rank → Hill as a second DLF family member and staying non-voting.

## Side finding for the Hill audit (H3)

Dynasty Nerds, a current OFFENSE master trainer, fits the live master **worse** than DLF Values do
(RMSE 1952 vs 1742) and trains at full authority. See
`docs/valuation/HILL_SOURCE_ALIGNMENT_AUDIT_2026-09-24.md` §4b.
