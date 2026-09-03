# V1-125 promotion evidence — 2026-09-03

## Claim under test

`V1-125` is the V1-required L2 claim **Duplicate owners retired (every `retires` line zero)** / `C10-CLOSE-02`.

This packet does not change the V1 denominator, ownership methodology, auth, canonical identity/value/lineup semantics, or the contract status by itself. It records the evidence needed for Integration to decide the existing L2 row without collapsing MERGED into VERIFIED.

## Frozen acceptance posture

The contract defines:

- L1: RED→GREEN deterministic test at exact head **plus green CI on the merge tree**.
- L2: L1 plus a measured statement of effect on the live board or contract — exact rows or zero.
- Missing/unmeasured evidence is not a pass.

The reconciled V1-applicable retirement population is exactly nine families: C1-U2, C1-U3, C1-U4, C2-U1, C2-U2, C2-U4, C2-U5, C3-U1, and C3-U2. C6-U1 remains explicitly POST-V1 and is not added to the denominator.

## Deterministic gate now on main

PR #1229 added `scripts/v1_125_zero_second_owner.py` and `tests/audit/test_v1_125_zero_second_owner.py`.

The production-code-independent acceptance test calls the composite gate with `run_commands=True` and requires BOTH:

1. return code `EXIT_OK`; and
2. the exact measured message:

`MEASURED: 0 live second owners across 9 V1-applicable retirement families`

The gate fails closed if a reconciliation row is missing, a classification is unresolved/decision-required/unmeasured, C6-U1's POST-V1 exclusion is not explicit, or any delegated canonical-owner guard fails.

The nine delegated checks are the already-settled identity, history, lineup, replacement, Team Strength, Team Weakness, package-construction, and Value Adjustment guards. The composite introduces no new ownership methodology.

## Exact-head / merge-tree CI evidence

PR #1229 final feature head: `e129dad3e820e2491177c16ad1fcc185205b30e7`.

PR Validation run `33728801980` concluded SUCCESS. The validation job checked out GitHub's PR merge ref, not merely the feature branch. The job log identified the tested synthetic merge as:

- synthetic merge SHA: `5eef08dd7363ab04a76bcc0ebb35e36d481343a4`
- base: `c0c87e3d6c7af70f0d027b20aa09b833ebd8ce11`
- feature head: `e129dad3e820e2491177c16ad1fcc185205b30e7`

The hard unit-test phase passed (`10602 passed, 21 skipped, 330 deselected, 398 subtests passed`), which includes `tests/audit/test_v1_125_zero_second_owner.py`. Because that test can pass only if the composite execution returns `EXIT_OK` and emits the exact zero-owner measurement, this is a non-vacuous measured zero, not a prose assertion.

The release-candidate step explicitly reported that the validated tree was the tree expected to merge at that base.

## Actual integration and drift reconciliation

PR #1229 merged as `1e3fe97bee0f36e7c1f41823fde344a07823f1b2` with parents:

- `d99d31b0dc24d41fdb2e13559d89c5f7661324db` (then-current main)
- `e129dad3e820e2491177c16ad1fcc185205b30e7` (validated feature head)

The feature's changed files are only:

- `scripts/v1_125_zero_second_owner.py`
- `tests/audit/test_v1_125_zero_second_owner.py`

The current main at this evidence capture is `9f21eed63d9d4e447107643f10c69ae81aded805`. Comparing the actual merge `1e3fe97...` to current main shows current main is exactly one commit ahead, and the only changed path is `data/ops/sharp-production-smoke.json`. No V1-125 gate, reconciliation, delegated owner guard, canonical implementation, workflow, or test changed after the merge.

Therefore the post-merge movement is operational evidence-state data only; it cannot alter the deterministic zero-second-owner result. This statement is intentionally narrow and does not treat unrelated deployment status as V1-125 evidence.

## L2 measured effect

The measured effect for this row is:

**0 live second owners across 9 V1-applicable retirement families.**

This is the contract effect the row exists to measure. V1-125 retires duplicate ownership; it does not authorize value, rank, lineup, scoring, auth, or methodology changes. The gate is an orchestration/acceptance check over existing canonical-owner guards, and PR #1229 itself changed no production implementation.

No production deployment is asserted as a requirement here: V1-125's required level is L2, not L3. Inventing an L3 deployment requirement would change the frozen verification methodology rather than strengthen the existing L2 evidence.

## Promotion conclusion

Evidence is sufficient to present V1-125 to the canonical completion contract for `NOT STARTED` → `VERIFIED` at L2, subject to the normal exact-head PR/integration guard on the contract-status edit itself.

This packet does **not** self-promote the row and does not count it before the contract status edit lands.
