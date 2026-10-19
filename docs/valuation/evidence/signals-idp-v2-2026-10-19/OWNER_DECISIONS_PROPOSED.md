# Signals IDP round 2: owner decisions needed for activation (proposed)

**Proposed text, not a decision.** Nothing here is in force until the owner answers. The
preregistration (`PREREGISTRATION.md`) and its gates are frozen independently of these
answers; an answer selects a disposition the preregistration already allows, it never edits a
threshold.

Starting the work needs nothing: the audit, the native-value probe, the preregistration,
default-off implementation and on-box runs are authorized by the 2026-10-19 directive
(`docs/owner/SIGNALS_IDP_VOTING_2026-10-19.md`). Activation needs the decisions below. Without
an answer, the affected family stays in shadow with that reason recorded.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## Proposed `ODR-SIGNALS-IDP` text (pending owner decision 4)

Today the register row reads "no threshold, timestamp or denominator changes" without limiting
that to Candidate A. Proposed replacement for the decision column:

> **Hold maintained per family until each family's round-2 gates pass.** Candidate A FAILED
> round 1 and is never redefined or activated. Round 2 is preregistered
> (`docs/valuation/evidence/signals-idp-v2-2026-10-19/`): Candidate F
> (`signals-idp-F-coverage-aligned-v1`) is the only promotable candidate; the October 17
> thresholds stay binding in the served configuration; no threshold or timestamp changes. The
> one instrument change is the corrected 6b panel (voting observations only, at least two
> other sources), always printed beside the round-1 panel. Each family (DL, LB, DB) activates
> independently, only after its gates pass on two qualifying releases (R1 and R2), an
> independent review, and the owner decisions that apply to it. Deadline for R1: 2026-11-16,
> then BLOCKED with evidence.

Proposed "next step" column: "on-box D1 diagnosis (pinned to release `6ec7bff6bd11`), then E1
on R1 and E2 on R2; per-family activation decisions 1-3".

## The decisions, each the smallest exact question

1. **The borrowed level.** Signals has no cross-family level opinion (its IDP values are
   normalised within each family). Under F its votes carry the IDP Trade Calculator's DL/LB/DB
   level, which double-counts that calculator's minority LB/DB placement. Choose one:
   * **(a)** accept a borrowed-level vote: signed-bias gates (G6b) do not apply to a source
     without a level; gate the consequences instead (G4-X, G6-shift, confidence); and decide
     whether such a vote earns B11 agreement credit; or
   * **(b)** keep G6b binding, which in practice keeps LB and DB in shadow until a non-bridge
     level source exists.
2. **DL haircut flips.** About 15–18 DL rows would jump ×3.33 under the literal single-source
   haircut rule when a second family votes. Wait for #1817's haircut finding, or accept the
   flips explicitly for Signals DL?
3. **Activation without positive independent validation.** If the information verdict against
   Draft Sharks IDP is NEUTRAL, NEGATIVE or INSUFFICIENT, and completed trades are INSUFFICIENT,
   is "engineering PASS; valuation quality not independently established" enough to vote?
4. **Register supersession.** Acknowledge the corrected-panel measurement change (the proposed
   `ODR-SIGNALS-IDP` text above), or keep G6b on the round-1 panel?
5. **Settings action (owner only):** restrict the `production` environment to `main`. A
   production workflow has succeeded from a `claude/*` branch, so branch code could reach the
   production SSH key and the paid session. Every on-box run of this round uses merged `main`
   code regardless.
6. **Licence scope:** confirm that the attestation covers (a) canonical-derived public
   aggregates (for example tethered pick dollars that a Signals vote would move) and (b) probe
   calls beyond the collector's own queries (the league list, extra fields).
7. **Conditional:** a roster-dependent native value would need an architecture decision. The
   prior is low (Tier 0 found no league-specific value store in the data schema).
8. **Owner action:** reconnect Signals when the refresh token expires (Cognito's default
   lifetime would put that around early November; inference, not measured).
