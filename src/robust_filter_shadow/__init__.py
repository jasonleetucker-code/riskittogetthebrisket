"""Shadow ledger for the joint robust filter (Batch 3 Unit F).

The #1571 filter half (``joint_outlier_sparse_challenger``) runs beside the
incumbent per-player Hampel filter on every board, in SHADOW. Nothing here
writes a served value, flips a flag or promotes anything; it records what the
two filters decided and, later, what became of the evidence they disagreed on.

Modules:

* :mod:`.record`   -- build a board both ways and extract the per-board shadow
  record (disagreements, weights, families, values/ranks before and after) plus
  the compact observation panel the outcome evaluation reads.
* :mod:`.ledger`   -- append-only, idempotent JSONL ledger and write-once panels.
* :mod:`.outcomes` -- the preregistered evaluation
  (``docs/valuation/evidence/joint-filter-shadow-2026-10-01/PREREGISTRATION.md``).
* :mod:`.adversarial` -- constructed trap / stale-cluster / correlated-family /
  broken-scale cases on real rows.
"""
