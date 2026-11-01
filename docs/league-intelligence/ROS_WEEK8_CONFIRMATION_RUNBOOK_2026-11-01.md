# ROS calibration — frozen Week 8 confirmation runbook (NC-A)

**Status: NOT RUN / RESEARCH ONLY.** This runbook executes the prospective confirmation already requested in ROS_SCALE_CALIBRATION_RESULTS_2026-10-28.md §7 and docs/EXECUTION_PLAN.md NC-A. It is not a new valuation or activation authorization.

## Purpose

The 2026 Week 5–7 rolling holdout under PR #2010 showed a measurable offense/IDP scale problem; CR improved MAE but did **not** pass the preregistered G3 gate. Week 8 is the first planned prospective confirmation using coefficients fitted only on Weeks 1–7, committed before the Week 8 games were final.

The existing evaluate command **recalculates** rolling models and the frozen artifact. Do not use it to claim an independent Week 8 confirmation.

## How to run

On an authorized runner with the normal ROS study dependencies and access to required as-of snapshots and public Sleeper/nflverse data:

    python -m pytest tests/ros_calibration/test_week8_confirmation.py -q
    python scripts/ros_scale_week8_confirmation.py

For already populated and verified caches:

    python scripts/ros_scale_week8_confirmation.py --offline

The runner loads the saved fits_week8_frozen.json **byte-for-byte**, checks its pinned Git blob identity (cbed086e21deca852f8db9abf3ef1de26656158d), reconstructs the stored parameters, and predicts Week 8 from the existing as-of roster snapshot. It refuses an incomplete Week 8, missing eligible data, score mismatches versus Sleeper and altered frozen parameters.

Its only research output is docs/league-intelligence/evidence/ros_scale_calibration/week8_confirmation.json. Do not commit a result unless the snapshot, code SHA, scoring fingerprint and host reconciliation are reproducible and independently reviewed. The runner does not write a live board or adjust any feature flag.

## Required interpretation

1. Report C0/CG/CF/CR/F observed MAE, group calibration, cross-group pair ordering, and team/lineup results **as they were**. Do not quietly change model fits, score cards or sample exclusions after observing the outcome.
2. A single week provides **only 12 team-weeks** in this league: it cannot satisfy the original G6 minimum of 36. G3 may still be underpowered. The output deliberately reports gates.status = NOT_RERUN.
3. Preserve the original preregistered G3 failure. Prospective evidence can inform the owner's next study but cannot retroactively turn that failed gate into a pass.
4. Reconcile the Week 8 snapshot and presence of the newly available draftSharksRosIdp board. Describe source-composition differences rather than attributing all shifts to model quality.
5. Any decision to add a separate points/week field, promote CR, change ROS rankings, mix IDP/offense team contributions or change simulations belongs to a **separate owner-approved methodology proposal**.

## Independent verification and release

Before merging: require independent code review; Python formatter/linter; targeted ROS calibration tests and planning integrity checks; CI on the exact head. Re-run if any shared calculation dependency changed.

**No deployment activation is part of this PR.** This is a read-only research runner and reproducibility test, not confirmation that Week 8 has been evaluated.

Traceability: NC-A in docs/OWNER_REQUESTED_TODO.md, docs/EXECUTION_PLAN.md §0; PR #2010; results §7.
