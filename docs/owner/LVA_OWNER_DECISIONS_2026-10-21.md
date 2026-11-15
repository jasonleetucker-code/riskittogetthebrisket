# Owner decisions: the five low-value-asset decision packages (2026-10-21, about 12:40 UTC)

**Recorded verbatim.** This is the owner's message, unchanged except for Markdown list formatting. It answers
the five packages in `docs/owner/LVA_INTEGRATION_REPORT_AND_DECISIONS_2026-10-21.md` §J.

**What this record does and does not do.** Capture is not implementation authorization. `docs/EXECUTION_PLAN.md`
(the 2026-10-21 LVA owner-decisions entry) records what is authorized. The owner separates two kinds of
permission: (1) developing code, and merging it while it is dormant, and (2) activating production behaviour.
**No package below activates anything.** Every new or existing flag named here stays OFF until the owner decides
otherwise, separately and with evidence.

Intake: `docs/OWNER_REQUESTED_TODO.md` "Added 2026-10-21 (~12:40 UTC)".

---

Here are my decisions on all five packages from `docs/owner/LVA_INTEGRATION_REPORT_AND_DECISIONS_2026-10-21.md`,
Section J.

## PACKAGE 1 — APPROVED WITH CONDITIONS

1. Select V5-R (`roster_rational`) as the preferred forced-drop selection mode.
2. Approve the dormant merge of PR #1890, provided its exact head passes required CI, independent review and merge
   checks.
3. Keep `forced_drop_cheapest_legal` OFF.
4. Once merged and deployed dormant, I authorize the pinned, read-only production-box replay described in the
   runbook, executed as the service user, producing aggregate-only results.
5. Measure real scarcity, Component B, both anomaly directions, and the changes to trade recommendations.
6. Investigate V5-R's documented non-monotonic behavior, including situations where adding a better player worsens
   the calculated result. Include these findings in the final activation recommendation.

I am NOT authorizing activation. Bring the replay results, production impact and corrected War Room copy back for
approval before turning the feature on.

## PACKAGE 2 — APPROVED WITH A WORDING SAFEGUARD

Select OD-F6 Option A: separate the historical grading label from the public market-fairness verdict without
changing numerical grades.

Relabel the historical tier and state its calculation basis, defining the existing 3% criterion in one authoritative
place.

Before using "Even outcome," verify that the term accurately describes what is measured. If the metric measures
valuation balance rather than realized performance, use an accurate label such as "Evenly valued" and document the
distinction.

Also approve re-measuring Package VA Phases 1–3 under `fairness_bands_v2`, as low-priority research only. Preserve
the original historical evidence.

Do not change `geom_q078_v1`, q = 0.78, or the approved fairness methodology.

## PACKAGE 3 — APPROVED

Approve the LI-5 recommendations from PR #1899:

- D1: A, with B retained as a shadow lens.
- D2: Yes. Implement P1–P2 now; P3 only after #1890 merges.
- D3: Yes.
- D4: Retain the ranks 1–3 replacement band.
- D5: Use the recommended candidate eligibility and availability handling. Preserve explicit uncertainty rather than
  treating unknown information as healthy, available or zero.
- D6: Preserve rostered and auction-rookie populations.
- D7: Follow the recommended phased sequencing.
- D8: Keep scarcity inert at 1.0.

Implement behind a default-OFF flag. No served replacement-level, IDP valuation, voting or scarcity changes are
authorized.

Provide measured before-and-after evidence before requesting activation.

## PACKAGE 4 — APPROVED FOR SHADOW MEASUREMENT ONLY

Select V4:

- Private-only design.
- No public disclosure.
- Rule A-guarded.
- Floor threshold.
- Include picks.
- Use the revised disclosure copy.
- Preserve the guard.
- Calculator and War Room first.
- Hold the War Room Team Context integration until #1890 is settled.

Authorize implementation of the hidden shadow counters behind a default-OFF flag, with appropriate private access
protections.

No user-facing display or public probing functionality is authorized.

Measure realistic firing frequencies and false positives, then return for a separate display decision.

## PACKAGE 5 — PARTIALLY APPROVED

### 5A — Chase Trade Market Q2

My original intent was to hold out entire leagues and use chronological separation to prevent training and
evaluation leakage.

I have not approved a permanent 20% manager-lineage reserve or the proposed five-way allocation.

Do not manufacture verbatim wording for Q2.

Keep its status `PROPOSED_PENDING_OWNER_Q2`. Do not draw, persist or expose the locked reserve.

First perform the permitted read-only census of actual eligible manager-lineage components. Return the real
component sizes, concentration, coverage and proposed allocation, with alternatives and trade-offs.

I'll choose the reserve policy after that evidence is available.

### 5B — PR #1884

The owning session is authorized to reconcile the research with current main and revalidate it.

Prioritize extracting durable research records and the separately reviewed identity prerequisites needed for the
November 4 deadline.

Do not merge the entire experimental V2/V2.1 implementation merely because its flags are OFF.

Keep every existing vote and activation hold unchanged.

### 5C — PR #1873

Keep #1873 open and unmerged for now.

Prepare the pinned manual research command for the prospective evaluation in early November, but do not execute it
on the production box without separate authorization.

Do not duplicate research already completed.

## GENERAL INSTRUCTIONS

Continue independent, authorized work in parallel. Coordinate with the other Claude session so branches, PRs and
documentation owners do not conflict.

Record these decisions in the appropriate authoritative owner-decision documents.

Distinguish authorization to develop or merge dormant code from authorization to activate production behavior.

Do not ask for additional approval on routine implementation details already covered by these decisions.

After the approved work, report what merged, what deployed, what was actually verified, and what still requires a
production activation decision.

Our objective remains accurate, league-specific fantasy trade recommendations—not simply more features or more
changed verdicts.
