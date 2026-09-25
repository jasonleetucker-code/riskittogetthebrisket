# Research-to-portfolio reconciliation — adopted 2026-09-25

**Status:** SUPPORTING EVIDENCE + PROPOSED PORTFOLIO AMENDMENT. **Not implementation authorization.**
Authorization stays in `docs/EXECUTION_PLAN.md` §0. The live intake pointer is `docs/OWNER_REQUESTED_TODO.md`,
under "Added 2026-09-25 — research-to-portfolio reconciliation adopted".

## What this is

The owner adopted (2026-09-25, explicit, in writing) a completed reconciliation. It maps 70 external-research
recommendations onto the existing Calculator portfolio. This directory preserves that crosswalk verbatim as
evidence, so its mappings, dispositions, supersessions, verified gaps, dependency findings and acceptance
requirements stay durable and traceable.

**Identity rule.** Native Calculator IDs and owners remain authoritative: C-Series manifest rows, CE IDs, OD rows,
issue and PR numbers. `R01`–`R70` are evidence and cross-reference IDs only. They are never manifest rows,
never work units, and never a second ledger. Work continues to be claimed, tracked and closed under native IDs.

## Files (verbatim, UTF-8, LF)

| file | content |
|---|---|
| `recommendation_reconciliation.csv` | 70-row crosswalk: native IDs, current evidence, canonical owner, active claim/PR, exact remaining outcome, disposition, dependency impact, acceptance, uncertainty, sources |
| `duplicate_and_supersession_receipt.csv` | 14 consolidation/supersession facts |
| `pr_inventory.csv` | Open/merged PR inventory at research time (head SHAs are that snapshot, not current) |
| `bounded_next_batch_acceptance.csv` | Game Day next-batch acceptance gates A–H |

The HTML renderings of the same package (`Calculator_Reconciliation_Report.html`, `Recommendation_Details.html`)
are not committed. The CSVs are the machine-readable source they were generated from.

## Disposition census

| disposition | count | meaning here |
|---|---|---|
| EXTEND | 39 | Adds acceptance or method detail to an existing native row/owner. No new owner. |
| KEEP | 9 | Existing native work already covers it. Preserve. |
| CONSOLIDATE | 9 | Folded into an existing owner/PR (see the receipt). No duplicate engine. |
| REFRAME | 6 | Native scope stays; the research framing is narrowed or corrected. |
| NEW CANDIDATE | 6 | No native owner row. **Candidate only.** See the admission check below. |
| DEFER | 1 | R60 salary-cap/contract leagues. Explicitly unadopted adjacency. |

EXTEND/KEEP/CONSOLIDATE/REFRAME rows change **no** owner decision and grant **no** new authorization. They are
acceptance evidence for work that must still be authorized through §0.

## Consolidations into existing work (from the supersession receipt)

- **R03** → #1415 / C3-CALC-01. #1441 (generic quantity) is merged; pick lifecycle stays #1442. No second
  quantity serializer.
- **R04** → C2-LINE/WEAK plus FAAB/trade consumers (#1436 merged). Deliberate fractional FAAB allocation is an
  owner decision (2026-09-24), not a defect.
- **R05** → C2-GP / C5-PLAY / C5-GD (#1435 merged). Live-state remaining-production acceptance stays with #1445.
- **R24** → C6-ANA-01 (#1437 merged persistence/as-of). Only the missing live extraction and consumer
  acceptance remain.
- **R27 / R54** → Lane 6 (#1438 merged; #1446 active). No second PSI programme; fixture screenshots are not a
  completion claim.
- **R12 / R70** → #1346 ↔ #1445/#1446. This is the approved narrow Game Day transfer: single-flight, atomic
  write, refresh-in-place. The broader prepared rollout stays with #1346, default-off.
- **R29** → C5-POW. #1398 supersedes #1381's frozen-current-share UI.
- **R38** → the existing DLF gate. #1411 and #1430 supersede #1406's blocker; the multi-capture question is
  #1444.
- **R36 / R65** → #1173: one scenario/lineup owner, not two bench models.
- **R42** → C7-AI-02 Roster Path Optimizer.
- **R45 / R55** → CE-17: one scorer, one experiment owner.
- **R10 / R58** → source ancestry and confidence explanation.
- **R61** → C6-POD / YT / X plus the prospect scopes, which stay distinct.
- **R62** → C7-GATE-01 / CE-11. The autonomy exclusion is not a gateway rejection.

## NEW CANDIDATE admission check (performed before admission, as the owner required)

The owner's approval named six candidates. The final crosswalk's six NEW CANDIDATE rows match on five and
differ on one:

| owner's list | crosswalk row | disposition in crosswalk | result |
|---|---|---|---|
| private decision/offer journal | R14 | NEW CANDIDATE | admitted as CANDIDATE |
| value-movement attribution | R39 | NEW CANDIDATE | admitted as CANDIDATE |
| **value-of-information / action-deadline intelligence** | **R40** | **EXTEND** of `C7-ALERT-01` / CE-29 ("new prioritization policy needs explicit approval") | **NOT admitted; discrepancy** |
| robust-regret / action frontier | R41 | NEW CANDIDATE | admitted as CANDIDATE |
| player-research queue | R64 | NEW CANDIDATE | admitted as CANDIDATE |
| offer-expiry / option value | R67 | NEW CANDIDATE | admitted as CANDIDATE |
| *(not on the owner's list)* | **R44** Personalized decision-quality feedback | NEW CANDIDATE, native `CE-28 feedback / OD-06; C1-HIST-01` | **NOT admitted; discrepancy** |

**Slot 6 is held pending the owner** because each choice has a consequence:

- **Option 1: R40 stays EXTEND** under C7-ALERT-01 / CE-29, as the crosswalk says. It then needs no candidate
  slot, but its new VOI prioritization policy still requires explicit approval before it is built.
- **Option 2: R44 is admitted instead.** Its native anchor, CE-28, is registered as **NOT OWNER-APPROVED**
  (`docs/CE_REGISTRY.md`). Promoting it is manifest decision row `OD-06` ("approve as scope, or drop"), so
  admitting R44 would silently prejudge OD-06. Nothing was substituted.

Admission means **recorded as a candidate** in the owner intake. It does not mean authorized, scheduled, claimed
or assigned a manifest row. No new native IDs were minted, and the manifest row count is unchanged.

## What was not done (explicitly outside the approval)

- Not implementing all 70 recommendations.
- Not creating 70 issues.
- Not changing any owner decision.
- Not promoting any model or source candidate.
- Not activating paid or default-off sources.
- Not reducing approved scope, including R60's DEFER: that is a proposal about new adjacency, not a deferral of
  existing outcomes.
- Not admitting every idea.

## Game Day next-batch gates (A–H)

These are adopted as acceptance evidence for #1445 / #1446, and are in `bounded_next_batch_acceptance.csv`.
Gates D (stat correction propagates to a rebuilt generation, preserving as-known history) and G (cold or
no-generation requests) are the ones in progress at adoption time. **G does not relax any route latency
budget.** A degraded compute-on-request fallback is an explicit residual, not an SLO change.
