# OWNER DECISION — PR #1831: OPTION B (2026-10-20), verbatim

Received 2026-10-20 ~12:25 UTC. Intake: `docs/OWNER_REQUESTED_TODO.md` "Added 2026-10-20 (~12:25 UTC)" (FS-B1..FS-B10). Authorization: `docs/EXECUTION_PLAN.md` §0 (2026-10-20 ~12:25 UTC entry).

---

Merge the universal freshness schedule with `source_freshness_schedule_v2` OFF by default, after resolving current conflicts and passing the required release checks.
I approve the implementation and the previously established freshness percentages. I am NOT approving activation yet.
The 918 value changes and LaJohntay Wester's +42.9% movement warrant caution because the existing outlier filter can remove legitimate source votes when the voting population changes. This overlaps with the defect outlier-integrity-v2 is intended to fix.
Requirements:

1. Set the feature-flag default to OFF. Ensure no production environment override activates it.
2. Rebase or reconcile #1831 against current main, which now includes #1817.
3. Recalculate the flag-off board impact against the current main. Confirm existing values remain unchanged.
4. Keep the approved freshness schedule and its tests intact.
5. Preserve source-voting status and diagnostic improvements wherever they can safely operate without activating the new weighting.
6. Add the affected rows, particularly LaJohntay Wester and the newly unpriced IDP cases, to the outlier-integrity-v2 regression and integration tests.
7. Once V2 is validated, conduct a combined impact analysis with the intended DLF voting changes and freshness schedule enabled in shadow mode.
8. Report changes to source participation, player values, IDP coverage, newly unpriced players, and outlier exclusions. Do not treat legitimate source disagreement as corruption.
9. Keep freshness activation, DLF IDP activation, and D4 activation reserved for my explicit approval.
10. Do not delay unrelated authorized development, including Release Train 16, production stability improvements, and the public/private multi-team calculators.

Do not introduce the optional DEGRADED-health or coverage-factor rule changes, or pick-specific freshness exemptions, without separate evidence and approval.
Once all gates pass, merge the safely disabled implementation through the normal release process. Do not activate the schedule as part of that merge.
