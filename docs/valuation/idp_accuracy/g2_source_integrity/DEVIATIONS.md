# G2 deviations log

Every change made after the held-out read of `dynasty_export_20261020_173527` (run at evaluator commit `9622ea48e`).
None of them touches a gate, a threshold or the registered held-out record. That record is committed exactly as it
was produced: `evidence/heldout_20261020_173527.json`.

| id | what | why | effect on gates |
|---|---|---|---|
| **D1** | Added `vendor_join_coverage()` and `--exploratory`. They measure how much of each vendor's own IDP list joined no board row, by vendor-order band. Output: `evidence/exploratory_D1_heldout_20261020_173527.json` | The assignment asks whether any DYNASTY-lane source shows a rank-basis **or coverage** discontinuity like ROS PR #1997. B2 registered the rank-basis half only | none: exploratory, never a gate. Known over-count: `matchedName` can carry the board's alias for a vendor name. Every name used in RESULTS was checked against the vendor CSV and the board one by one |
| **D2** | Post-hoc adjudication of every B1 defect, the one extreme vote, and the coverage examples, against the vendor CSVs at refresh `c2b44022f0` and in-process rebuilds of the held-out board | Preregistration §4 says a B-gate failure is a finding to explain, never a reason to tune | none: verdicts stay as registered. Adjudication is reported beside them |
| **D3** | Evaluator limitation found during D2, **not fixed**. B1 treats a missing `sleeper.fantasyPositions` entry as "eligible for the row's own family only". Four held-out B1 findings (Harold Landry, Baron Browning, Oluwafemi Oladejo, Tyree Wilson) have no entry, so their league eligibility is UNKNOWN rather than known-single-family | Changing the rule after the held-out read would be a decision-affecting change | none: B1 stays FAIL as registered. RESULTS labels these four "eligibility unverifiable". A successor registration should treat unknown eligibility as ABSTAIN (unknown is not false) |
