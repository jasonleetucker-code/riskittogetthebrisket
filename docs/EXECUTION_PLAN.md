# Chase Upside / Risk It To Get The Brisket — Current Execution Plan

**Status:** CANONICAL SEQUENCING / AUTHORIZATION RECORD
**Last reconciled:** 2026-08-18 (owner directive: **V1 COMPLETION SPRINT AUTHORIZED**, six parallel lanes, superseding the 2026-08-17 feature freeze for V1-required work only — §0)
**Companion:** `docs/MASTER_PRODUCT_PLAN.md` · `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md`

This file answers **what implementation work is authorized right now**, and nothing else. It does not define
long-term product intent — that lives in the Master Product Plan, the Owner Feature Inventory, the Product
Backlog Spec and the feature specs. It does not define scope — that lives in `docs/C_SERIES_SCOPE_MANIFEST.md`.

> **A feature being approved in the long-term plan does not authorize beginning it here.**
> **Being listed in the Scope Manifest does not authorize beginning it here either.**

---

# 0. CURRENT AUTHORIZATION — READ THIS FIRST

## V1 COMPLETION SPRINT — AUTHORIZED BY THE OWNER, 2026-08-18.

**This supersedes the 2026-08-17 feature freeze below, to the extent necessary for V1
completion — and no further.** The freeze text is retained beneath, unedited, as the record of
what it paused and of the conditions it imposed. Where the freeze and this section conflict on
V1-required work, this section governs; everywhere else the freeze still reads correctly.

**What is authorized.** Implementation of the **V1 REQUIRED** denominator in
[`docs/VERSION_1_COMPLETION_CONTRACT.md`](VERSION_1_COMPLETION_CONTRACT.md) §3, together with the
production verification in §9 of that document.

**What this is NOT.** It is **not** blanket permission to implement backlog ideas. An item that
is not in the V1 REQUIRED denominator is not authorized by this section, however small, obvious
or adjacent to authorized work it looks — that is the same "do not expand scope under the label
of repair" rule the freeze states, applied to a larger permitted set rather than replaced.
Genuinely new ideas go to the long-term roadmap. A genuine **omission** from already-approved V1
scope is a denominator change, and a denominator change is an owner decision recorded in the
completion contract §10 — never a silent edit.

**Six parallel lanes are authorized**, with these ownership boundaries. A lane that introduces
another lane's canonical math is rejected or refactored — ONE CONCEPT, ONE CANONICAL OWNER
applies across lanes exactly as it applies across modules.

| lane | owns |
|---|---|
| **1 — Roster Intelligence** | lineup · replacement · meaningful roster core · Team Strength · Team Weakness · Young Core |
| **2 — Trade Intelligence** | package generation · Value Adjustment · capacity / forced drops · trade simulation · team-context trade logic · Analyze Trade |
| **3 — Season / Scoring / Projections** | exact scoring · season models · projections |
| **4 — Market / FAAB / Analyst** | FAAB · market · Sharp · Buy/Sell and analyst systems |
| **5 — Integration Authority** | governance · integration · CI · cross-cutting QA · global source-health semantics · deployment and production verification · the completion ledger |
| **6 — Premium UI / Frontend** | UI · frontend · performance · accessibility |

**Lane assignments deliberately extend past V1.** Each lane owns post-V1 continuation work so
that no lane goes idle after finishing its V1 responsibilities. **That continuation work is not
V1-required and must not be pulled into the denominator** (owner decision, 2026-08-18;
completion contract §1 and §4.2).

**Merge order is governed by V1 dependency and verification, not by lane convenience or by
date.** Lanes do not merge themselves: every lane PR is integrated by lane 5 against the gate in
the completion contract and in this section. **Green CI is necessary and not sufficient** — the
exact diff, the ownership boundary, upstream dependencies, duplicate canonical logic, tests,
exact-head CI and, where material, production behaviour are all checked before a merge.

**`CLOSED-PENDING-PROD` still is not `CLOSED`** (§0.2 below, unchanged). Only `VERIFIED` counts
toward V1, and code existence, a merged PR, unit tests alone or a statement in a document —
**including this one** — do not constitute verification.

**After V1 is genuinely complete:** a stable V1 tag and baseline is established with its proof
preserved; dependency-ready post-V1 work then continues in isolated lanes under the same
integration discipline, without corrupting that baseline. Speculative features are not to be
stuffed into V1 to make it look larger, and V1 is not to be shrunk to make it look finished.

**The target date is 2026-08-25, and it is an absolute latest, not a schedule.** If V1 is
verified earlier, it is declared earlier.

---


## 0.-1 FEATURE FREEZE (2026-08-17) — **SUPERSEDED 2026-08-18 for V1-required work; otherwise still in force.**

> Retained verbatim below. Read it for the conditions it imposes — production proof may not
> be substituted, an unreachable check is `BLOCKED-EXTERNAL` and never a pass, and scope may
> not be expanded under the label of repair. Those conditions survive the supersession and
> bind the V1 sprint too.

## FEATURE FREEZE. The **post-merge C-Series audit and stability gate** is the only authorized work. Owner directive, 2026-08-17 (later the same day).

**This supersedes the continuous-campaign authorization recorded in §0.0.** The owner imposed a
**temporary feature freeze** after the six-unit tranche merged, pending a comprehensive audit of
the actual repository and production behaviour. Read this section before §0.0, which is retained
as the record of what the freeze paused — not as a live authorization.

**Do not begin, under any label:** `C2-U2` · `C2-U3` · `C2-U4` · `C2-U6` · `C1-U7` · any `C3+`
implementation · any new product feature · any new methodology · any new UI surface · any
opportunistic feature lane.

**Do not expand scope under the label of "repair."** The permitted change set is closed:

| permitted | not permitted |
|---|---|
| repair a defect · restore intended behaviour · reconcile a bad merge · restore a canonical invariant · remove a duplicate implementation · fix production wiring · fix an incorrect test · strengthen a regression guard · repair documentation/governance drift · fix a security, privacy, performance, accessibility, data-integrity, provenance or observability defect **in currently implemented functionality** | anything that adds capability, changes methodology, or opens a surface that does not exist today — including when it would be small, obvious, or adjacent to a repair |

**Production proof may not be substituted.** Not by PR-head CI, not by local tests, not by a
staging process, not by an older deployment, and **not by a statement in a document — including
this one**. An unreachable check is recorded `BLOCKED-EXTERNAL`, never as a pass.

**The audit ends in exactly one of `PASS` or `FAIL`**, plus one recommendation. "Basically okay"
is not an outcome. **Even on `PASS`, execution does not resume automatically** — `C2-U2` does not
begin, and the session stops after the report. Resumption is a fresh owner decision recorded here.

> **Consequence for whoever reads this next.** Until that decision is recorded, the answer to
> "what may I build right now?" is **nothing from the campaign queue**. The queue below is
> sequencing state, not permission.

## 0.0 The continuous C-Series campaign — AUTHORIZED 2026-08-17, **PAUSED by the freeze above**

Retained verbatim in substance because the freeze is temporary and this is what resumes.

The owner authorized continuous execution of the entire remaining C-Series and **explicitly
superseded the routine per-unit stop-and-wait checkpoints**. Units were executed in the order below
without asking permission between them.

**One record, one answer** (§7.6 still holds). The single authorized scope was *the campaign*, and
the single current unit was the one named in the queue below. **Both are paused**; §0's freeze is
the operative authorization today.

| question | answer |
|---|---|
| Is B complete? | **Yes.** B4–B11 merged; the B-Series Completion Audit passed (#837, `79f47ff`, 20/20 executable checks) |
| Is the B→C gate cleared? | **Yes.** All nine steps of `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §3 are satisfied; PR #845 merged (`6d9640c7`) |
| **What may I build right now?** | **Under the §0 freeze: nothing from this queue.** Only the audit and its permitted repair set. When the freeze lifts: the current unit below, then the next dependency-eligible one, continuously |
| Which units are CLOSED? | `C1-U1` (retention — `C1-RET-07` honestly STALE) · `C1-U2` (player identity) · `C1-U3` (pick identity) · `C1-U4` (temporal ledger) · `C1-U6` (pick completeness). **Do not reopen any of them** |
| Do I stop at the end of a unit? | **Under the §0 freeze: yes — the audit report is the stopping point.** Under the campaign: no — mark it `CLOSED-PENDING-PROD`, enqueue it, and start the next eligible unit or a parallel-safe lane |
| When *do* I stop and ask? | Only for: a genuine unresolved owner decision · required external authorization · paid-API permission · credentials only the owner holds · an irreversible destructive operation · or a merge that now blocks **every** legitimate dependency-eligible lane |
| Is `CLOSED-PENDING-PROD` closure? | **No.** See §0.2 |
| Is `CANONICAL_V2` activation authorized? | **No** — C1-U2 measured it and deliberately deferred it; separate unit |
| Are `X-01`…`X-07` authorized? | **No.** `X-02` (Money/dues, Constitution, League Media) and `X-07` (general "link any Sleeper account" onboarding) were **restated OWNER-REJECTED on 2026-08-17** and must not be reintroduced from directive boilerplate |

Scope reconciliation for the directive, including the owner-methodology authority findings:
**`docs/C_SERIES_DIRECTIVE_RECONCILIATION_2026-08-17.md`**.

## 0.1 Campaign order — **paused; nothing in this diagram is authorized today**

> **Acceptance criteria bound in advance for `C2-U6` / `C2-U4` (owner addendum #899, 2026-08-18).**
> Recorded here so the units cannot be started against the older wording. **FLEX is an assignment
> rule, not a sortable Team Strength position.** The meaningful-roster core must: solve the actual
> starting lineup from real league configuration; assign dedicated starters; fill each actual
> FLEX / Superflex / IDP-FLEX starter slot from the highest-valued remaining legally eligible
> players; **remove every actual starter from the pools**; and only then take reserve demand as
> `ceil(M × slots) − slots` per dedicated position and `ceil(M × actual FLEX slots) − actual FLEX
> slots` for FLEX. `M` stays the 1.5× V1 champion/PRIOR with its challenger pass. A player used at
> FLEX may not also count as native-position depth; every player counts at most once; 0/1/2/3+
> FLEX configurations must work from league settings; SF and ordinary FLEX may not double-count.
> Reuse the canonical exact assignment machinery (`src/ros/lineup.py`) — per-position greedy lists
> are forbidden. No FLEX column is required. Canonical record:
> `docs/OWNER_FEATURE_ADDENDUM_2026-08-18_FLEX_STARTER_ASSIGNMENT.md`; decision 72 in
> `docs/OWNER_REQUESTED_TODO.md`.

`C1-U7` sits **after `C2-U4`** and not with the rest of C1. It declares `deps C1-U6, C2-U4`
(`docs/C_SERIES_EXECUTION_MAP.md`), because an owned pick's slot distribution is a function of
simulated final standings, hence of Team Strength. Building it earlier would tune it against a
provisional formula — the thing the map's §1 ordering rule exists to prevent. It is deferred by
one dependency, not descoped.

```
C0-R   governance reconciliation  [CLOSED-PEND-PROD] C2-U6  meaningful roster core
C0-U2  performance baselines        ∥ parallel      C2-U4  canonical Team Strength
C1-U5  confidence naming migration                  C1-U7  owned-pick distributions ← unblocked
C1-U8  acquisition / cost basis / lineage           C2-U5 · C2-U7 · C2-U8 · C2-U9 · C2-U10
C1-U9  multi-format source archive                  C3-U1…U9 · C4 · C5 · C6 · C7 · C8 · C9 · C10
C2-U1  one lineup / slot assignment
C2-U2  one replacement level / PAR                  standing parallel lanes when blocked:
C2-U3  exact roster simulation                      C0-U2 · C4-U1 · C8-U1
```

## 0.2 `CLOSED-PENDING-PROD` is not `CLOSED`

A unit reaches **`CLOSED-PENDING-PROD`** on: RED→GREEN, exact-head CI green on its own PR,
evidence document written, duplicate owners retired, required documentation updated, and a named
production-verification checklist. That state authorizes **continuing to the next unit** — nothing
more.

A unit becomes **`CLOSED`** only when its production verification succeeds **against the deployed
merge SHA**. Therefore:

- **`C10` may not count `CLOSED-PENDING-PROD` units as closed;**
- the reserved completion phrase in `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §15 may not
  be used while any required production proof is outstanding;
- PR-head CI is necessary and **not** a substitute for proof on the merged, deployed tree.

## 0.3 Merge queue

Ordered. A unit leaves this queue only when production proof lands on the deployed merge.

| unit | PR | exact head | CI | unlocks | production proof |
|---|---|---|---|---|---|
| `C0-R` | [#875](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/875) | `ad95bd6` | **RED on the inherited `main` defect below, and only that** — run 31987737878: `test_derived_2029_value_uses_measured_year_step` (ratio 0.9857), plus four advisory-lane source-coverage rails on the same nine rows. **Re-measured across three `main` revisions: `b1c6a42a` = 9 of 18 tier cells violating, `85b13689` = 8, `01574f63` = 9 again.** The count OSCILLATES with routine data refreshes while the mechanism sits untouched — the structural cells (Mid 4th/5th/6th) hold at ratio 1.035 throughout, and `Mid 2nd` flips either way on a one-point drift in its 2028 twin. The 8 was therefore noise, and the return to 9 is the measurement that proves it rather than an argument for it. Only a scrape that re-runs the pick anchors can clear this. Its own diff is documentation and standing-invariant tests | every later unit — this is the record that authorizes them | **IN PRODUCTION, CHECKLIST UNEXECUTED** (#875 on `main` @ `4fc7ab22`; the freeze that blocked this cleared at 20:22Z — see below) — checklist in `docs/C_SERIES_DIRECTIVE_RECONCILIATION_2026-08-17.md` §7, **written 2026-08-17 because it was missing**, which was a governance defect in the governance unit |
| `C1-U5` | [#876](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/876) (stacked on #875) | `d33465d` | **GREEN** — run 31991834158 SUCCESS on the exact head | `C2`/`C3`/`C6` confidence consumers — §1's rename-before-new-consumer rule is discharged by this unit | **IN PRODUCTION, CHECKLIST UNEXECUTED** (#876) — checklist in `docs/confidence/C1_U5_CONFIDENCE_NAMING.md` §6, **written 2026-08-17 because it was missing**; the unit had been recorded `CLOSED-PENDING-PROD` without one, which §0.2 does not permit |
| `C1-U8` | [#878](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/878) (stacked on #876) | `ac731c6` | **GREEN** — run 31997754113 SUCCESS on the exact head (05:39:52Z). Earlier head `ab9d31a` was also hard-gate/livedata/contract green (run 31994961129). A post-delivery checklist audit then found **nine defects**, two of them false claims of correctness (a dead-code as-of clock and its vacuous test) — repaired on the same branch rather than duplicated. Board inertness now **measured 0/1111**, not asserted. 106 acquisition tests | `C3-REPLAY-01` (needs `C1-ACQ-02`), `C4-MTL-01`, `C4-WAIV-01`, `C4-INS-01` | **IN PRODUCTION, CHECKLIST UNEXECUTED** (#878) — checklist in `docs/acquisition/C1_U8_ACQUISITION_LEDGER.md` §8 |
| `C1-U9` | (stacked on #878) | see PR | local: 7,782 backend / 2,051 frontend, 0 failures; 23 source tests; board measured inert 0/1111; ruff, coercion, planning and structural-contract gates clean | `C5-ROS-01` (deps `C1-SRC-01`) | **IN PRODUCTION, CHECKLIST UNEXECUTED** (#879) — checklist in `docs/sources/C1_U9_MULTI_FORMAT_SOURCE_ARCHIVE.md` §7 |
| `C2-U1` | [#880](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/880) (stacked on #879) | `066d2517` | **GREEN** — run 32022945892 SUCCESS on the exact head, all 24 steps. **Reported green once prematurely.** An adversarial review then found a CRITICAL defect in the unit's own premise: `/api/data` splices a live Sleeper overlay that rebuilds `sleeper.teams` wholesale, discarding the lineup stamp on the NORMAL path — so the feature worked only while Sleeper was DOWN. Four further real findings followed (a slot-legality name collision, a FALSE RED claim in my own test header, a latent FAAB divide-by-eligibility bug that was a 6th even-split derivation, and two structural guards weaker than claimed). All fixed and regression-pinned; the guards are proven to fire. Board inert **0/1111 values, 0 ranks**, confidence inert **0/1111 rows**, re-measured after every round. The canonical solver was verified against **Sleeper's own awarded lineups, 10/10** before being trusted | `C2-U2` · `C2-U3` · `C2-U4` · `C2-U6` · `C2-U9` · `C5-PLAY-01` — the root of the C2 phase | **IN PRODUCTION, CHECKLIST UNEXECUTED** (#880) — checklist in `docs/lineup/C2_U1_CANONICAL_LINEUP.md` §10, whose step 3a exists because of the critical defect above |
| `C1-U6-D1` | [#883](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/883) | `4e71b8105` | **GREEN** — run 32060480767 SUCCESS on the exact head; local full hard gate 7,924 passed / 0 failed | **UNBLOCKED THE DEPLOY** — and therefore the production proof of all five merged units | **DEPLOYED** — merged `a4007aec4`, Deploy Production run 32062696830 SUCCESS at 20:22Z, first since 00:35Z. Repaired scraper ran end-to-end in production twice (20:10-20:14, 20:21-20:25), both clean. Record: `docs/picks/C1_U6_D1_FABRICATED_FUTURE_YEAR_ANCHORS.md` §8 |

| `C1-U6-D1` verification | [#884](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/884) | `3b829b1eb` | **GREEN** on the exact head | closes the repair's own loop | **DEPLOYED** — merged `5a5f1507f`, Deploy Production run 32075149186 SUCCESS. Verified the committed board **0 of 18** tier-round cells violating, and retired the temporary fixture shim on its own declared condition (it dropped 0 rows on `a58e9d923`) |

## 0.4a EXCLUSIVE INTEGRATION / MERGE AUTHORITY — owner directive, 2026-08-18

**Lanes 1, 2, 3, 4 and 6 no longer merge their own PRs.** The Integration Authority lane owns
everything from `READY FOR INTEGRATION` through merge. This is a division of labour, not a
quality gate on the lanes: it exists so implementation lanes spend essentially all their time
implementing and verifying rather than babysitting a merge queue.

**A lane's responsibility ends at a genuinely ready PR:** implement; keep the branch synchronised
with current `origin/main`; fix lane-owned defects; run the deterministic, integration and
exact-head checks; **document limitations and required post-deploy verification honestly**; mark
it `READY FOR INTEGRATION`; then **immediately take the next dependency-ready unit rather than
waiting for the merge**.

**What this lane independently verifies before merging** — every one of these, every time:

| # | gate |
|---|---|
| 1 | based on sufficiently current `main`, or reconciled against it |
| 2 | **the actual merge tree is what was tested** |
| 3 | required blocking CI green |
| 4 | no lane-owned failure mislabelled as inherited |
| 5 | no unresolved semantic conflict with another open V1 PR |
| 6 | canonical-owner boundaries preserved |
| 7 | missing/unknown not coerced into zero or success |
| 8 | value / rank / board movement **measured** wherever the change can move canonical outputs |
| 9 | no known P0/P1 regression introduced |
| 10 | shared files (`CLAUDE.md`, governance records, the coercion baseline, major shared API owners) **reconciled**, never first-past-the-post |

**`config/coercion_baseline.json` is never trusted because Git found no conflict.** Discovered by
lane 4 and reproduced here on real branches. The file stores a derived `count` beside the list it
counts, and that scalar can go stale through a **clean** merge with nothing to notice:

```
main   retires entry A and writes count 676
a lane retires entry B and writes count 676
the merge keeps BOTH removals; both sides agreed on the scalar, so git reports
no conflict — and the file now claims 676 over 675.
```

Measured 2026-08-18 merging two live lane branches in order: `origin/main` 676/676 OK → `+#914`
673/673 OK → `+#913` **declared 673, actual 670**, both merges reported clean. The old gate
exited **0** on that tree, because it counts entries and never read the scalar.

So whenever an integrated PR touches this file: reconcile the code first, then **regenerate from
the merged tree** with `python scripts/check_decision_coercions.py --write-baseline`, run the gate
against the regenerated result, require declared == actual, and **commit the regenerated
baseline** rather than hand-resolving the number.

It is now **enforced** rather than remembered: the gate refuses a baseline whose declared `count`
disagrees with its own `violations` list, and names the regeneration command. Verified to fire —
injecting a +3 skew gives exit **2** with the remedy, and a consistent tree stays exit **0**.

Regeneration matters even when the merge is clean and the count already agrees. On #911 it swapped
an entry: `main` carried a different coercion text in `frontend/lib/perfect-draft.js`, so the
branch held a stale allowance for the old text and none for the current one — invisible to the
gate, which enforces on changed files and correctly called it "main moved; not this PR's to fix".

**Git-scoped gates must run AFTER the commit exists.** `_changed_files()` is
`git diff --name-only <base>...HEAD`, so an uncommitted edit is outside the enforced scope.
Measured on the same new coercion: **uncommitted → exit 0, "clean: no new coercions"; committed →
exit 1, "NEW (1) — a decision path may not fabricate a number"**. Running such a gate against a
dirty working tree is not a weaker check, it is a different one — and it answers "clean" for work
it cannot see.

**Check formatting with the PINNED ruff, not whatever is on your box.** CI pins
`ruff~=0.6.0` (resolving to 0.6.9); a newer local ruff formats differently and will pass a file
the gate then rejects — which costs a full validation cycle for one line. It has done so twice in
this lane. Create a pinned venv once and use it:

```
python3 -m venv <scratch>/rufenv && <scratch>/rufenv/bin/pip install "ruff~=0.6.0"
<scratch>/rufenv/bin/ruff format --check .
```

The converse trap is just as real: running a NEWER ruff's `format` over a file rewrites hunks the
pinned version never asked for, which lands unrelated churn in your diff. Format only files you
touched, and verify the hunks are yours.

**Merge-ready is not `VERIFIED`, and the two must not be run together.** A capability can be safe
to merge while still owing L3/L4 production proof. It merges, deploys through the normal path, and
stays `IMPLEMENTED_UNVERIFIED` in the contract until the evidence exists. Merging is a statement
about safety; `VERIFIED` is a statement about proof.

**Never merge merely to obtain green, and never weaken, skip, suppress or reclassify a legitimate
gate to make a PR mergeable.** The F-30 episode in this very lane is the cautionary case: a
census error was reclassified into the source-health lane to clear CI, and the taxonomy test that
refused it was right.

**After every merge**, this lane: updates the contract ledger **from evidence**; identifies which
open PRs are now behind or semantically affected; tells those lanes in their PR; requires them to
reconcile with the new `main`; and moves to the next ready PR.

**Escalated to the owner, and nothing else:** genuine product decisions, destructive or data-loss
operations, legal/credential issues, and irreducible conflicts between binding owner decisions.
Routine merges satisfying the frozen contract and the gates above need no approval.

---

## 0.4 V1 six-lane integration order — MEASURED 2026-08-18

**The Integration Authority lane decides the integrated representation of shared files. A lane
may propose a shared-owner change; it does not resolve a shared-owner collision unilaterally.**
Six parallel sessions each resolving `CLAUDE.md` or a gate baseline their own way produces six
subtly different repository instructions, which is the failure this section exists to prevent.

Order, by dependency — **not** by readiness or by who finished first:

```
#910  integration / stability / governance   (this lane)
  └─> #914  canonical roster intelligence     (lane 1)
        └─> #913  roster-dependent trade      (lane 2)
              └─> #912  contract consumers    (lane 6)

  #915 (lane 3) and #911 (lane 4) integrate independently — no shared-owner collision
```

`#910` is first because it carries the F-30 2029-pick repair that every other lane's CI is
currently failing on, plus the governance records the rest are reconciled against.

**Conflicts are measured, not predicted.** All six branches were trial-merged into a scratch
worktree off `main` in the order above:

| shared file | lanes touching it | result |
|---|---|---|
| `server.py` | #910, #911, #912, #913, #914 | **merges clean** |
| `CLAUDE.md` | #911, #913 | **merges clean** — additive, different sections |
| `src/api/feature_flags.py` | #910, #915 | **merges clean** — different regions |
| `tests/e2e/specs/journey-tools-health.spec.js` | #910, #912 | resolved: #910 **withdrew** its version, #912's is correct |
| `config/coercion_baseline.json` | #911, #913, #914 | **the only real conflict** |

The integrated six-lane tree passes `check_planning_integrity`, `check_product_plan_governance`,
`audit_status`, the coercion gate, `py_compile` and `ruff check`.

**Resolution rule for `config/coercion_baseline.json`: regenerate, never hand-merge.** Each lane
recomputed `count` from a different base (677, 676, and `main`'s own 676 over a different set), so
a hand-merge yields a number matching no tree. Run
`python scripts/check_decision_coercions.py --write-baseline` and commit the result; the gate
scopes to changed files, so another lane's drift cannot fail the resolving PR. Measured end state:
**676 → 670**, the six lanes retiring six coercions between them.

**A lane blocked on another lane's merge does not stop.** It takes its next dependency-ready V1
item; when its V1 work is exhausted it continues into explicitly classified post-V1 work, which
does **not** enter the V1 denominator.

---

**Current work: the §0 audit and stability gate. No unit is in flight.**

**The deploy is unblocked and every merged unit's CODE is in production.** All six PRs (#875
C0-R, #876 C1-U5, #877 C1-U6-D1 record, #878 C1-U8, #879 C1-U9, #880 C2-U1) plus the two
repairs (#883, #884) are ancestors of the deployed `5a5f1507f`, and merge integrity was
verified against main's history rather than trusted from GitHub's merged flag.

**That is not production proof, and the distinction is the whole of §0.2.** What changed at
20:22Z is that the *precondition* was met: the code these checklists describe is now the code
production is running. **Not one of the five named checklists has been executed.** Their
remaining blocker is no longer the deploy — it is that each requires an authenticated
production session, which the owner is supplying under the audit (§0). Until a checklist is
run against the deployed SHA and its result recorded, every row above stays in this queue.

**Do not read "IN PRODUCTION" as "verified".** It means the bits shipped. Whether they behave
is the question the audit exists to answer.

**THE PRODUCTION FREEZE — FOUND AND CLEARED 2026-08-17.** Resolved at 20:22Z by #883; the account below is the diagnosis that led there, kept because the mechanism matters.

**THE PRODUCTION FREEZE (found 2026-08-17, while attempting that verification).**
Deploy Production last SUCCEEDED at `8d6930cd6`, **2026-08-17T00:35Z**, and has failed
**12 consecutive times since**. Every failure is the same: `Validate Build Inputs` →
`pytest -x -q -m "not livedata"` → `test_derived_2029_value_uses_measured_year_step`
(ratio 0.985), after which the `Deploy To Production` job is `needs: validate` and reports
`skipped`. `validate_api_contract --lane full` passes; the blocker is unit tests only.

So **production is running the `8d6930cd6` build and none of the six merged units are in
it.** That reorders the campaign: C1-U6-D1 is not merely a canonical-truth defect, it is
*the deploy blocker*, and it gates the closure of all five other units.

**REPAIRED 2026-08-17** — `docs/picks/C1_U6_D1_FABRICATED_FUTURE_YEAR_ANCHORS.md` §7.
Root cause is in `Dynasty Scraper.py`, not the contract: four paths (three sharing an
uncapped, undirected `_nearest_year`, plus an un-yeared `(year, None)` bucket the earlier
diagnosis missed) forced a value for a year the source never published. The builder is
extracted to `src/picks/site_pick_map.py` — byte-parity-proven over 36 source boards /
8,640 keys before any behaviour changed — and RED-tested there, since as closures it had no
test, no fixture and no import seam anywhere in the repo. All **18 of 18** `(tier, round)`
cells now sit strictly below their 2028 equivalent **by derivation, never a clamp**, and no
2029 row stamps `direct_market_blend`.

**Why the queue is red at the bottom and green above it**, which is easy to misread as the
stack being broken: `pull_request` CI validates the **merge ref** — base merged into head.
`C0-R`'s base is `main`, so its validated tree carries `main`'s 2026-08-17 export and the
fabricated anchors with it. The stacked units' bases are branches that predate the
transition, so their validated trees carry the clean 2026-08-16 export and they go green on
their own merits.

Two consequences worth stating rather than rediscovering:

- **The whole queue is gated on the scraper repair**, not on anything in the queued diffs.
  `C0-R` cannot go green while `main` carries the defect, because merging `main` is exactly
  what brings the bad export in.
- **A green stacked PR is not evidence the defect is gone.** It is evidence that the unit's
  own diff is clean against a pre-defect base. Re-basing any of them onto current `main`
  would turn them red without a line changing — measured on `f1e3700` (the 04:27 DLF
  refresh), whose board is byte-identical to `776cfa9`'s: the same 9 of 18 cells, the same
  values. A data refresh that does not re-run the pick scrape does not clear this.

---

# 1. FOUNDATION PROGRAM — COMPLETE

Every unit below is merged into `main` and is an ancestor of `HEAD`. Verified by
`git merge-base --is-ancestor` at the time of reconciliation.

| unit | scope | merge | evidence |
|---|---|---|---|
| **B4** | W30-F023 percentile-tail saturation; canonical boundary 904 | PR #805 | No Hill promotion or refit was authorized or performed. Do not reopen absent new evidence. |
| **B5** | W06 canonical player identity | PR #806 | W06-F001/F004/F007/F009 fixed; W06-F002 refuted by executable evidence — do not re-enable the retired near-name rule to satisfy the old finding |
| **B6** | W18 league-configuration correctness | PR #810, merge `5c699af`, validated head `e453889`, run 31688810982 | Factual `scoringFingerprint` replaces the profile label; unproven identity fails closed both ways. Live: the two leagues fingerprint `sf1:b7ad1575925091f6` vs `sf1:82a5f8ef2bfdb098` under one identical `scoringProfile` label, differing on 35 of 48 shared keys |
| **B7** | Realized-points correctness (W18-F003, W18-F004) | PR #820 (`af761fc`), validated head `0875da5`, run 31738127750 | |
| **B8** | Privacy / distribution / refresh boundary | PR #821 (`053f9e5`), validated head `0cc95b9`, run 31764984203 | W01-F010 and the W22 family closed on **both** distribution channels — HTTP and git |
| **B9a** | `offenseOnlyRankDerivedValue` retired; the 1–9999 scale becomes an enforced contract | PR #824 (`2e0d098c`) | A second full pipeline run whose output three engines substituted per trade: 491 of 507 comparable rows disagreed, up to 21.87%. Canonical board byte-identical after removal; build 0.62 s → 0.49 s. `apply_valuation_factors` deleted after it published 10,160 and 12,471 under `rankDerivedValue` |
| **B9b** | Threshold semantic units | PR #824 (`f0bb846`) | W29-F005 closed — a predicate comparing 0–9999 against 0–100 could not fire for any of 1,093 rows; it now fires for 19. Four thresholds registered with `unit` + `derivedFrom`. Partial by design: four board-relative constants are classified but not converted |
| **B10-T1** | Scraper KTC dedupe | — | **SATISFIED, nothing to remove.** The authorising premise did not describe canonical aggregation |
| **B10-T2** | Declare provenance | PR #825 (`e015814`) | **21 source keys → 13 provider families.** Board provably inert: 0 values moved, 0 ranks changed |
| **B10-T3a** | The market gap stops measuring retail against itself | PR #827 (`2098cad`) | |
| **B10-T3b** | One vote per provider family | PR #831 (`f0ab9e7`) | |
| **B11** | Confidence semantics | PRs #832 (`8428d99`), #833 (`263996d`), #834 (`d50de55`), validated head `70e70ca`, run 31828347707 | The spread statistic is retired and replaced by a five-axis evidence gate whose overall level is the **weakest** axis. The retired statistic could only narrow when an observation was removed, so deleting evidence promoted rows |
| **#828** | Second Opinions basis contract | `c56d0eb` | |
| **#836** | Missing is never zero on display | `62f5a39`, validated head `ef2cfa9`, run 31831875577 | |
| **#837** | **B-Series Completion Audit** | `79f47ff`, validated head `de25a58` | **20/20 executable checks PASS.** 7,548 backend tests passed / 60 skipped; 2,044 frontend tests across 125 files. Live board 1,094 rows, 812 priced in `[1, 9999]`, 282 explicitly unpriced. Verdict: *"PASS — C-Series may begin."* |

## Operational notes carried forward from the B units

These were per-unit notes in the previous version of this file. They are operational truth, not phase status, so
they survive the rewrite. Full per-unit detail is in `docs/master-site-audit/B_SERIES_EXECUTION_LEDGER.md`.

- **B4.** A future nonblocking safeguard remains open: advisory detection when an effective observed source rank
  exceeds the canonical 904 boundary, rather than silently accumulating 905+ saturation.
- **B5.** Ghost-row repair takes effect on the **next scrape**. Do not claim a historical or current board changed
  until that path has actually run.
- **B6 — operational requirement.** `data/leagues/scoring_<sleeperLeagueId>.json` must exist for a league to be
  provably compatible. The post-scrape warm pass writes it every cycle; **on a cold deploy, run
  `scripts/fetch_league_scoring.py` once**, or cross-league requests fail closed until the first scrape.
- **B6 — how to observe it.** Dispatch the read-only `Scoring Snapshot Diagnostics` workflow
  (`.github/workflows/scoring-snapshot-diagnostics.yml`). It exists because the state is otherwise unobservable:
  `data/leagues/` is gitignored and is not force-added by `scheduled-refresh.yml`, and both fail-closed branches
  — "proven different scoring" and "no verified snapshot" — produce byte-identical public responses.
  **The same run reports whether the canonical board-history recorder is scheduled**, which is the only way to
  answer manifest row `C1-RET-02` from outside the production host.
- **B6 — architecture record.** `docs/master-site-audit/evidence/W18/B6_SCORING_IDENTITY_DESIGN.md`.
- **B9b — partial by design.** Four board-relative constants are classified and registered but deliberately not
  converted, because each changes which assets a recommendation surface offers. See
  `docs/valuation/THRESHOLD_UNIT_REGISTRY.md`.

## Four bounded B residuals — carried into C1, not reopened

None of these mutates a canonical value, none has a decision consumer, and none causes irreversible evidence
loss. They are naming and determinism defects. **They do not reopen B methodology, and cleanup does not license
a methodology change.**

| residual | what it actually is | carried to |
|---|---|---|
| Board-history `rankChange` non-determinism | `_stamp_rank_changes` reads a single-slot cache then unconditionally overwrites it, so build N+1 diffs against build N's own output. Keyed by bare `canonicalName` with no asset-class namespacing. The durable history lives in a **different**, append-only log that offline builds never write, so `rankChange` for any past date is reconstructible | `C1-HIST-03` |
| `confidenceBucket: "none"` on 24 priced rows | Current-year slot picks tethered to a real value *after* the confidence loop's rank cap, retaining the row-builder default label `"None — unranked"`. The value is right; the label is wrong | `C1-CONF-01` |
| `identityConfidence` | Means player-id resolution quality, not evidence confidence. Read by nothing that gates | `C1-CONF-01` |
| `marketConfidence` | A bounded site-count + dispersion blend, diagnostic since 2026-07-30, structurally capped at 0.59375 | `C1-CONF-01` |

**Do the renames before any new confidence consumer is built.** Every consumer added first widens the blast
radius of a rename that is otherwise mechanical.

---

# 2. NEXT AUTHORIZED SCOPE

## `C1A` unit 6 — `C1-U6`, pick completeness through 2029. **CLOSED at the owner checkpoint 2026-08-16.**

Scope is exactly manifest rows `C1-PICK-01` (every valid pick through 2029 has a finite canonical
value — provenance stamped, never zero-as-missing, all surfaces agreeing) and `C1-PICK-02` (the
generic ↔ exact-slot transition survives without a second asset). Owner: the `data_contract` pick
pipeline. Deps: C1-U3 (closed). Binding calibration requirement
(`docs/MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md` §3.1, map §17): the future-year discount is a
**PRIOR** — challenger-test discount families against real market evidence; **never `0` for an
unknown future pick**. Execution-map RED: a valid 2029 pick with no finite canonical value.

**The checkpoint decision deliberately selected C1-U6 ahead of C1-U5.** `C1-U5` / `C1-CONF-01` is a
mechanical confidence-label migration with no methodology change; it is **DEFERRED, not cancelled**,
and remains unauthorized. Consequence for C1-U6 (per §1's rename-first rule): C1-U6 must build **no
new confidence consumer** — evidence quality it needs to expose goes through existing canonical
provenance/evidence structures.

**Delivered (2026-08-16).** Five RED classes reproduced on the live payload through the production
build path and closed (`tests/api/test_pick_completeness_red.py` → `test_pick_completeness.py`):
cap-truncated voted picks, vote-less future rounds 5-6, the uncalibrated clone×0.53 (audit
V-12/C-11), the clone's verbatim vendor-anchor asymmetry, and the valueless generic grade. The
year discount was challenger-tested against real market evidence per the calibration policy —
five families over 34 archive dates × two vendor pick markets, leakage-free provider/time
holdouts — and the measured per-cell vendor year-step replaced the incumbent (holdout MAPE
36.7-38.3% → 1.4-1.7%), **still classified PRIOR** because the 2-out→3-out extrapolation is
untestable on today's evidence. Rounds 5-6 derive from the canonical rookie-ladder round step;
rank-less generic-grade rows ("2027 Round 1") give `market_resolution`'s unknown-slot basis a
finite value; every pick row carries `pickValueProvenance`; the census is an ERROR gate in
`validate_api_data_contract`; `src/api/pick_value_resolution.py` is the one reference-class
resolver; the dormant second pick pricer in `src/canonical/calibration.py` is deleted; the two
authorized consumer repairs landed (draft-capital future seasons price at the generic grade,
the simulator's roster-pick labels resolve through identity instead of silently dropping).
Player-value coupling measured and explained (IDPTC backbone re-indexing, p50 ±0.1%; see the
record §8). Full record: `docs/picks/C1_U6_PICK_VALUE_COMPLETENESS.md`.

**MERGED** — PR #871, merge `ce8a8341a` (parents `801bf940d`, an automated data refresh on main,
+ validated head `edc25300d`), merged by the owner 2026-08-16 19:10:41Z.

**Exact-head CI, stated correctly.** `6d7b9dd47` passed run **31964305868 SUCCESS**, and the final
head `edc25300d` — which differs from it only by merging main's automated data-refresh commits —
passed its OWN exact-head run **31965928453 SUCCESS**, concluded 19:08:58Z, one minute and
forty-three seconds before the merge. An earlier version of this section said that run was
cancelled by the merge and never concluded. **That was wrong**, and it is corrected here and in
`docs/picks/C1_U6_PICK_VALUE_COMPLETENESS.md` §13 and §14; the direct post-merge verification that
was performed remains valid evidence, but it was an addition, not a substitute.

**What did fail** was the post-merge tree `ce8a8341a`: its *other* parent brought in a newer scrape
in which KTC had timed out (300 s against a 39-run baseline of ~18.8 s). Deploy Production run
31966802715 failed in validation and `Deploy To Production` was **skipped** — nothing shipped.
A/B on the identical payload reproduced the same contract-health status and the same
13-named / 29-with-subtests failure set on the pre-C1-U6 parent `801bf940d`, zero unique to C1-U6.
Pick completeness held on the merged tree: 162 pick rows, 2029 **24/24** finite, provenance 162/162,
zero census errors.

**STABILIZED** — the bounded repair pass of 2026-08-16 (record:
`docs/ops/STABILIZATION_2026-08-16.md`) separated deterministic code correctness from external
source health in CI, turned on the contract gate that had never once run, added the source-health
lane and the release-candidate discipline, corrected this false CI history everywhere it appeared,
and disposed of all eleven C1-U6 follow-ups (ten fixed, one proven an intentional contract and
pinned).

**CLOSED at the owner checkpoint 2026-08-16.** C1-U6 / `C1-PICK-01` / `C1-PICK-02` are closed. Do
not reopen; a value that moved during stabilization is recorded with its mechanism in the
stabilization record §6, not re-litigated.

**SUPERSEDED 2026-08-17.** This paragraph read: *"No unit beyond C1-U6 is authorized… Reaching this
point is a **STOP**… requires a new explicit owner decision at the §3 checkpoint."* That STOP was
discharged by the owner directive of 2026-08-17, which authorized the continuous campaign in §0 and
superseded the routine per-unit checkpoints. **C1-U6 itself remains CLOSED and must not be
reopened**; what changed is what happens *after* a unit closes, not the closure.

## `C1A` unit 4 — `C1-U4`, one immutable as-of value/provenance ledger. **CLOSED at the owner checkpoint 2026-08-16.**

Owner-authorized 2026-08-16 at the C1-U3 checkpoint; scope was exactly manifest rows `C1-HIST-01`,
`C1-HIST-02`, `C1-HIST-03`.

**Delivered.** The canonical temporal owner (`src/history/` — `keys`/`store`/`asof`/`record`/
`backfill`/`migrate`/`provenance`) now decides as-of lookup, historical fidelity
(`exact` / `nearest-prior` / `reconstructed` (defined, deliberately unproduced — no approved
reconstruction methodology) / `partial` / `unavailable`), missing semantics (machine-readable reasons;
the pre-2026-07-14 gap is PERMANENT, enforced at write and query), rankChange derivation
(ledger-dated comparator, read-only on every build, collision-keyed, `None` never 0 — the retired
`ranks_last.json` cache and its 740-row back-to-back divergence are deleted, closing W03-F010 as a
side effect), and historical player+pick value queries (players by C1-U2 identity, picks by C1-U3
`mpick:*` refs; the 72 rank-less slot-pick rows now record first-class). The census measured **five**
fragmented as-of decision paths (map said 4); five RED classes were reproduced on real retained data
(`tests/history/test_temporal_red.py`) and closed (`test_temporal_ledger.py` — replay determinism,
never-future property, back-to-back build determinism, valuation inertness by full double-build
equality). Archive backfill: 34/34 dates from 2026-07-14, 138,127 observations, deterministic and
idempotent. Deferred with record (manifest's own decomposition): the trade-retro/terminal/value-chart
consumer migrations (C3-U9 / C2-AGE-03). Full record: `docs/history/C1_U4_TEMPORAL_LEDGER.md`.

**MERGED** — PR #869, merge `8b6a9987` (parents `49603291e` + validated head `5940a177f`), exact-head CI
run 31955465747 green (format + lint + coercion gate + finding-drift gate + planning integrity + import
gate + full pytest + contract check + deploy syntax + frontend). The one bounded final review confirmed
and closed two release blockers before the head was validated (design record §15).

**DEPLOYED AND PRODUCTION-PROVEN** — deploy run 31958433677 SUCCESS (16:42 UTC); the read-only
`Temporal Ledger Diagnostics` run 31960075629 then measured the box directly: ledger present with
**169,896 rows across all 34 dates** (2026-07-14 → 2026-08-16; canonical_board 30,357 — board-history
migration 8,932 + rank-history migration 20,613 + the live recorder, which had already recorded the
16:45 post-deploy scrape), corrections 0, pre-boundary probe answering `before_history_boundary`, and
real as-of queries resolving on production: `mpick:2026:r1:s1` @2026-08-16 → `exact` 7,779 with rank
NULL (a canonical historical PICK value through canonical pick identity — C1-HIST-02 live) and
`player:5859` → `exact` 4,947 / rank 72 / tier 10, both stamped `live:server` with the pipeline version.

**Checkpoint outcome (2026-08-16, recorded on PR #869):** the owner reviewed and **ACCEPTED** this
unit's evidence. C1-U4 is CLOSED; the checkpoint decision authorized `C1-U6` (above) and nothing
beyond it, deliberately deferring `C1-U5`. Do not reopen C1-U4.

## `C1A` unit 3 — `C1-U3` / `C1-ID-02`, one pick identity, end to end. **CLOSED at the owner checkpoint 2026-08-16.**

Owner-authorized 2026-08-16 at the C1-U2 checkpoint; scope was exactly manifest row `C1-ID-02`.

**Delivered.** The canonical owner (`src/identity/picks.py`) now defines pick identity end to end: a
league pick's identity is `league_key + season + round + origin franchise` (current owner and realized
slot are STATE — a trade or the draft order landing never mints a new asset); market pick references
carry exactly one of slot/tier/generic grades; the generic→exact transition is a pure state change with
a deterministic `market_resolution()` that answers an unknown slot with the GENERIC grade, never a
fabricated tier or slot. The census measured **97 raw representation records deduplicating to 39 independent
pick-identity definition sites** (vs the map's estimate of 7 — see
`docs/identity/C1_ID_02_CENSUS.md`); six real defect classes were reproduced on live code paths + real league data
(`tests/identity/test_pick_identity_red.py`) — the execution-map RED (same pick, two representations, no
round-trip) among them, plus five real 2027 1sts serializing to one label, wall-clock/rename label drift,
fabricated "Mid" for unknown slots, the intel ledger's origin-stripping asset id, and league-free overlay
shapes. Consumers adapted with **byte-parity**: the contract's pick grammar, the overlay's and scraper's
ownership fold + both label grammars (pickDetails gained an additive canonical `assetId`, fail-closed on
unregistered leagues), draft-capital name formatting, and the intel crawler's persisted generic-grade key
(re-key deferred to C1-U8 with the collision documented at the owner). Board proven byte-inert:
**0 of 1,093 rows moved, 144 picks intact, 0 values, 0 ranks** (`golden_board` + `board_diff
--expect-no-value-change`). Full record: `docs/identity/C1_ID_02_PICK_IDENTITY.md`.

**MERGED** — PR #867, merge `22ce424f` (parents `f7acd646` + validated head `5a221f61`), exact-head CI
run 31938061211 green (format + lint + full pytest + livedata + contract check + frontend). The
coercion-debt ledger shrank 692 → 689 (the canonical fold removed three legacy coercion sites).

**Deliberately deferred, recorded not hidden:** the intel-ledger re-key (C1-U8), the frontend
label-lookup migration (needs C1-U6's generic-grade board rows; held in lockstep by
`tests/identity/test_pick_grammar_frontend_parity.py`), the public-league fold (bespoke multi-season
semantics; origin retained), and every valuation half of C1-PICK-01/-02/-03.

**Checkpoint outcome (2026-08-16):** the owner reviewed and **ACCEPTED** this unit's evidence. C1-U3 is
CLOSED; the checkpoint decision authorized `C1-U4` (above) and nothing beyond it.

## `C1A` unit 2 — `C1-U2` / `C1-ID-01`, one player-identity owner. **CLOSED 2026-08-16.**

Authorized 2026-08-16 by owner decision at the unit-1 checkpoint; scope was exactly manifest row
`C1-ID-01` (pick identity `C1-ID-02` is `C1-U3` and was excluded).

**Delivered and closed.** The canonical owner (`src/identity/resolution.py` +
`src/identity/name_primitives.py`) now decides player identity at both consolidation sites; the scraper's
run()-scope ladder and the contract's inline join cascade are **deleted**, along with their dead machinery
and the cutover flag, so no fallback can override the owner. The staged migration ran in full —
dual-read → compare → cut over → retire — and the production gate passed at both sites with **zero
divergence** (scraper 2,016/2,016 over a full refresh cycle; contract 24,024/24,024). A before/after
rebuild across the cutover differs on **0 of 1,092 rows**. Merge `b0c2f36`; deploy run `31921280237`.

**One thing was deliberately NOT done, on measured evidence:** `CANONICAL_V2` — the repaired semantics — is
implemented and measured but **not served**. The same production cycle showed it is not yet a strict
improvement: it would drop correct identity for four real players in the first-name-variant class
(Matt/Matthew Judon, Matthew/Matt Hibner, Michael/Mike Hall, Nikolas/Nick Martin) and refuse three more
purely because those call sites pass no position. It needs a first-name-variant rung (the repo already owns
the rule, `name_clean.is_first_name_variant`) and a no-position tiebreak. Those are canonical-identity
semantics, so they belong to a **separate authorized unit**, not to C1-U2's closure. The gap is measured
every cycle as `v2WouldChange`. Full record:
`docs/identity/C1_ID_01_IDENTITY_CONSOLIDATION.md` §9.

## `C1A` unit 1 — the irreversible-evidence retention tranche. **CLOSED 2026-08-16.**

**Was authorized as:** manifest rows **`C1-RET-01` … `C1-RET-08`** — the eight rows the Scope Manifest flags
`RET` inside phase C1. Read them from `docs/C_SERIES_SCOPE_MANIFEST.md`; that file is authoritative if this
summary and it ever disagree. Closed at the owner checkpoint; `C1-RET-07` remains honestly STALE (collection
not resumed, watchdog still exits 2 for it) and the observational follow-ups recorded in
`docs/retention/RETENTION_REGISTER.md` are hardening items, not reopeners.

Deployed as merge `47d7d243` (validated head `ef76a425`), deploy run `31869441040` SUCCESS.
Production evidence below is the **strict `ALL` watchdog run `31870347342`**, measured 2026-08-15T06:48:36Z
against the production data directory.

| row | what stops being lost | production state (final, run `31916149679`) | status |
|---|---|---|---|
| `C1-RET-01` | KTC crowd-FAAB rolling window durably retained | `ok`, 2.6 h — 2 accumulator files, **1,128 deduped rows** | **COMPLETE** |
| `C1-RET-02` | canonical board history provably recording | `ok`, 24.0 h — **10,934 rows across 10 dates** | **COMPLETE** |
| `C1-RET-03` | `rank_history.jsonl` stall detectable | `ok`, 24.0 h — 27 snapshots, missingDays=0, staleDays=1 | **COMPLETE** |
| `C1-RET-04` | scoring card at a date (today: overwritten) | `ok`, 0.1 h — **90 observations of 2 distinct cards across 2 leagues** | **COMPLETE** |
| `C1-RET-05` | Sleeper trending adds (today: discarded every 15 min) | `ok`, 0.1 h — **4,500 observations across 45 snapshots** | **COMPLETE** |
| `C1-RET-06` | own-league trade events before the rolling window drops them | `ok`, 0.1 h — **288 transactions, 288 trades, 4 leagues** | **COMPLETE** |
| `C1-RET-07` | per-source raw ingest + identity reports (halted 2026-04-20) | **`stale`, 2,812.2 h** — newest `identity_report_20260420T194828Z.json` | **STALE** — honestly labelled; **collection NOT resumed** |
| `C1-RET-08` | `playerctx` history actually landing | `ok`, 120.0 h — 2 snapshots, **both published to `origin/main` as `7730677eb`** | **COMPLETE** |

**COMPLETE means: recording on production, restored and verified from a backup, and — for `C1-RET-08` —
actually off-box.** The six recording rows are each restored and verified in run `31906622971`; the watchdog
proves they are still being written to. `C1-RET-07` is the one row that is not complete, and it is not
weakened to look like one: its collector has not resumed, the producer is not in the tree, and the strict
`ALL` watchdog still exits **2** because of it.

**The watchdog exited 2**, on a genuinely stale stream. That is the corrected semantics working, and per the
production-checkpoint instruction a stale row is *not* a reason to weaken it. It has not been weakened.

> **The backup + restore proof is green**: run `31906622971`, `RUN_BACKUP=1`, exit 0 — 16 artifacts in the
> generation, **7 retention artifacts restored and verified from the restored copies**. It exercised the deploy
> user's FALLBACK lineage and said so itself.
>
> **The unattended nightly now exists.** It did not: no `riskit-state-backup` unit, neither file under
> `/usr/local/lib/riskit/`, no `/var/backups/riskit-state` — so the seven artifacts were covered by no
> scheduled job. Installed 2026-08-16 through the deploy account's existing sudo allowlist (run
> `31915897174`), timer `enabled`/`active`/`Persistent=yes`, next elapse **02:30 UTC**, `ExecStart` rooted at
> `/usr/local/lib/riskit/`, manual oneshot `Result=success`.
>
> **A manual oneshot is not a nightly firing, and a proven fallback lineage is not a proven root lineage.**
> Both distinctions are kept explicitly in `docs/retention/RETENTION_REGISTER.md`, along with what remains
> unmeasured: the root-owned generation's contents are not readable by the deploy account.
>
> `C1-RET-07` stays **STALE on its own merits**: identity collection has not resumed and the producer is not
> in the tree.
>
> Operational record, with the full backup/restore evidence: `docs/retention/RETENTION_REGISTER.md`.

**Four other rows carry the `RET` flag but are NOT in this tranche** — `C4-FAAB-02`, `C5-GD-02`, `C7-DRAFT-02`
and `C9-UR-02` are flagged so their collection starts as early as their phase allows, but they belong to C4, C5,
C7 and C9 and **are not authorized here**.

### Minimum-substrate boundary

Some retention rows depend on broader C1 owners (`C1-HIST-01` immutable as-of storage, `C1-ACQ-01` transaction
identity, `C1-ID-01`/`C1-ID-02` asset identity). This authorization permits **only the minimum canonical
substrate needed to stop evidence loss safely** — the durable event/snapshot envelope, stable event ids,
schema/version/provenance fields, a minimal append-only storage interface, and bounded adapters or dual-writes.

It is **not** permission to complete those parent owners. If a prerequisite cannot be finished safely inside
C1A, implement the maximum non-throwaway stop-loss and record the remaining dependency — and **do not** mark the
parent owner complete.

### The B→C gate, satisfied

`docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §3 defines nine steps. Steps 1–7 were performed by the post-B
reconciliation. **Steps 8 and 9 — owner review and explicit owner approval — are now complete**, recorded by the
merge of PR #845 (`6d9640c7`) and the owner's authorization of C1A.

---

# 3. QUEUED — NOT AUTOMATIC AUTHORIZATION

The proposed C-Series spine, in dependency order. Full scope per phase is in
`docs/C_SERIES_SCOPE_MANIFEST.md` §4; the phase contract is
`docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §5.

```
C0  Truth freeze, scope manifest, dependency graph        ← this reconciliation
     │
C1  Canonical asset, pick, history and provenance         ← retention starts HERE
     ├──────────────┐
C2  Roster math    C4  Evidence ledgers
     │              │
C3  Trade substrate │        C6  Analyst / manager intelligence
     │              │             │
     ├──── C5  Seasonal engines   │
     │              │             │
     └──────► C7  Decision products ◄────────┘
                    │
C8  Premium migration (no-regret prep runs parallel from C0)
                    │
C9  Public / awards / storytelling
                    │
C10 Closure
```

## `C1A — Canonical asset identity, temporal evidence and retention`

**Units 1–4 are CLOSED. Unit 5 of this list (`C1-U6`) is AUTHORIZED. Unit 4 of this list (`C1-U5`) is
DEFERRED; unit 6 is NOT authorized.** Original rationale in `docs/POST_B_RECONCILIATION_2026-08-14.md` §30.

PR-sized units within C1A, in order:

1. **Retention first** (`C1-RET-01`…`C1-RET-08`) — **CLOSED 2026-08-16** at the owner checkpoint.
2. **CLOSED 2026-08-16.** One player-identity owner (`C1-ID-01` / map unit `C1-U2`). Cut over, legacy
   retired, production gate green at both sites. `CANONICAL_V2` activation deferred on measured evidence —
   see §2.
3. **CLOSED at the owner checkpoint 2026-08-16 as `C1-U4`** (PR #869, merge `8b6a9987`, deploy run
   31958433677 SUCCESS; closure recorded on PR #869). Immutable as-of snapshot/event schema with provenance, model/config version and fidelity labels
   (`C1-HIST-01`), plus the deterministic-replay test that closes `C1-HIST-03`.
4. **DEFERRED — NOT AUTHORIZED** (`C1-U5` / `C1-CONF-01`). Confidence naming migration with aliases and a consumer census.
   The owner deferred it at the C1-U4 checkpoint in favor of C1-U6; §1's rename-first rule holds because
   C1-U6 builds no new confidence consumer.
5. **AUTHORIZED 2026-08-16 as `C1-U6` at the C1-U4 checkpoint.** Pick census through 2029 and the generic ↔ exact-slot invariant (`C1-PICK-01`, `C1-PICK-02`).
6. **NOT AUTHORIZED.** Dual-read adapters for the existing board, rank-history, platform, trade and pick stores.

**C1A deliberately builds no UI.** It unlocks pick valuation, roster math, historical replay, acquisition
history, market ledgers, manager intelligence, waivers and trade consolidation.

---

# 4. PARALLEL LANES

Lane names are referenced by the `lane` column in `docs/C_SERIES_SCOPE_MANIFEST.md`.

**SERIAL — one writer only:** `gov` (this file and the governance set) · `trade` package-engine extraction and VA
consolidation · anything touching `data_contract.py`'s pipeline core · the CE registry.

**PARALLEL-SAFE:** `ret` retention scripts versus everything · `perf` baseline capture (read-only) versus
everything · `psi` no-regret design prep versus all feature work · `id` schema work versus `hist` retention once
the schemas freeze · per-ledger `mkt` collectors behind a frozen schema · per-engine `season` consolidations.

**PARALLEL-CONDITIONAL:** `roster` Team Strength versus Team Weakness *after* the shared roster interface lands ·
`decide` products *after* the C3 generator and constraint-owner interfaces freeze · `psi` route migrations *after*
each route's data contract stabilizes.

**DO NOT PARALLELIZE:** two agents on the CE numbering or the backlog reconciliation — that is exactly what
produced the collision · anything that creates a second package, lineup, replacement or value engine · pick
valuation together with pick-history backfill while pick identity is unsettled · `CLAUDE.md` edits from two
branches · schema migrations on the intel ledger from two workstreams.

---

# 5. ALWAYS-OPEN LANES — not gated by the C authorization

These do not wait for the C gate and never have.

- **Production incidents and owner-reported live defects.** The Admin `fmtPassExpiry` crash (#779), the
  temporary-password path (#780), and any user-visible breakage. Schedule at a safe checkpoint; do not mix
  unrelated product changes into a tightly scoped fix.
- **Source health and freshness operations.** DraftSharks is ~219 h stale against a 24 h threshold with its
  session absent on production, so the watchdog is red every two hours while nine-day-old values still vote in
  every blend. This is operations, not C scope — but it needs an owner decision on disposition (`OD-04`).
- **Security patches and dependency updates.**
- **The retention items in `C1-RET-*` are no longer a grey area** — the owner authorized them as C1A unit 1 on
  2026-08-15, precisely because every day they wait is evidence that cannot be recovered at any price. They are
  now ordinary authorized work under §2, not an exception to this section.

---

# 6. PRODUCT WORK THAT MUST NOT PREEMPT FOUNDATIONS

**Still binding under the campaign.** The 2026-08-17 directive authorized the whole C-Series *in
dependency order*; it did not authorize starting anywhere in it. Every product below is now
scheduled rather than forbidden — reached at its own unit, after the substrate it consumes exists.
Jumping to one early is the same defect it always was.

Do not opportunistically
begin: Best Trade to Send Each Team · LOCK/EXCLUDE · persistent protection · Golden Upgrades · Package Builder ·
Trade Desk · Team Strength/Weakness · Market Trade Ledger · Pick Forecast · Manager Scout · Analyst Intelligence ·
Game Day · Share Renderer · Weekly Report Studio · Public League v3 · Awards v2 · Universal Player Profile
expansion · the AI Front Office family · the CE surfaces · Premium route migration.

They may be read during foundation work to avoid architectural contradictions.

**The dependency reason, not merely the process reason:** every one of those products consumes a substrate that
does not exist or is duplicated today. Best Trade alone needs the shared package generator (4 competing
generators today), the constraint owner (absent), whole-package market coverage (correct but disconnected),
canonical Team Strength (4 competing notions) and one Value Adjustment (5 implementations). Building it first
means building all five wrong and refitting later.

---

# 7. EXECUTION UPDATE RULE

Under the continuous campaign this runs **at every unit boundary**, not only at an owner checkpoint
— that is what replaces the checkpoint. At each boundary:

1. update completed/accepted phase state here;
2. advance §0.3's **current unit** and append the finished unit to the merge queue; a unit leaves
   the queue only when production proof lands on the deployed merge SHA (§0.2);
3. leave later approved product scope in the Master Product Plan and the Scope Manifest rather than copying it
   here;
4. never let a stale phase statement in `ARCHITECTURE_HANDOFF.md`, an old audit roadmap, a planning branch or a
   session capture override this file;
5. if current code or executable evidence disproves this execution state, **reconcile this document before
   beginning another phase**;
6. **this file may state exactly one "next authorized" scope at a time.** The defect this rewrite fixes was a
   §1 that recorded B6 as merged while §2 authorized B6 as next. One record, one answer. Under the
   campaign the single answer is *the campaign*, and §0.3 names the single current unit — so the
   rule is satisfied by there being exactly one **Current unit** line, not by there being one unit
   in flight;
7. when a later section contradicts §0, **mark it superseded in place with the date and the
   reason** rather than deleting it. §2's C1-U6 STOP is the worked example: the closure it records
   is still true, only its forward-looking clause was discharged.
