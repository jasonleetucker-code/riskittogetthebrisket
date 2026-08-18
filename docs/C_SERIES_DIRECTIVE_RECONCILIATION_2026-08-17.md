# C-Series Directive Reconciliation — 2026-08-17

**Status:** CANONICAL ACTIVE — the owner-directive → manifest-row proof, and the record of
which rule won where two owner records disagreed
**Created:** 2026-08-17 by unit `C0-R` of the continuous C-Series campaign
**Companions:** `docs/C_SERIES_SCOPE_MANIFEST.md` · `docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md` ·
`docs/EXECUTION_PLAN.md`

> **THIS FILE AUTHORIZES NOTHING.** `docs/EXECUTION_PLAN.md` alone answers "what may I
> build now?". This file records *scope reconciliation* and *methodology authority*.

---

# 1. What this reconciles

On 2026-08-17 the owner issued a full-program directive authorizing continuous execution
of C0→C10 and superseding the routine per-unit stop-and-wait checkpoints. The directive
restates a large amount of product scope — a 104-row feature ledger (its Part XVIII), an
"approved features outside the original 104" list (Part XIX), and detailed methodology
for every phase.

Restated scope is a hazard as well as a gift: a restatement can silently *reintroduce*
something the owner previously rejected, or silently *replace* a validated implementation
with an older description of it. This document exists so that neither can happen quietly.

It answers three questions:

1. does every item in the directive have a destination? (§2, §3)
2. where the directive and an existing owner record disagree, which one governs, on what
   evidence? (§4)
3. what was deliberately **not** done, and why? (§5)

---

# 2. Part XVIII — the 1–104 feature ledger

**This is the same 104-row owner ledger already traced as source family F.**

Verified by identity of endpoints and contiguity: the directive's rows 101–104 are
*Historical Trade Replay*, *Best Trade to Send Each Team*, *Persistent Protection* and
*LOCK / EXCLUDE*, which are exactly the destinations
`docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md` §F records for ledger rows 101, 102, 103 and
104. That section states the count was *"re-verified programmatically: exactly 104,
contiguous 1–104, no gaps, no duplicates"* and maps every band to a manifest row.

**Disposition: already mapped. Unmapped from Part XVIII = 0.** The band-level mapping is
not duplicated here — a second copy of a mapping is a second mapping, and it will drift.
Read §F of the traceability record.

---

# 3. Part XIX — approved features outside the original ledger

| directive item | destination | disposition |
|---|---|---|
| **A.** AI Front Office family — Ask Brisket · Roster Path Optimizer · Edge Alerts · Trade Liquidity & Market Depth · Negotiation Coach · League Truth | `C7-AI-01` · `C7-AI-02` · `C7-ALERT-01` · `C7-AI-03` · `C7-AI-04` · `C7-AI-05` | mapped — six products, six rows; Edge Alerts is its own row, not an AI row |
| **B.** Roster age-value portfolio / Young Core | `C2-AGE-01`, `C2-AGE-02`, `C2-AGE-03` | mapped (#838) |
| **C.** Weekly Report Studio | `C9-WRS-01` | mapped (#829) |
| **D.** FAAB Market Heat | `C4-FAAB-01` | mapped (#830) |
| **E.** Upside Report — Kickoff edition | `C9-UR-01`, `C9-UR-02` | mapped |
| **F.** Sleeper Action Gateway | `C7-GATE-01` (CE-11) | mapped; gated on owner decision `OD-02` |
| **G.** Trade Polls | CE-16, inside `C7-CE-01` | mapped — optional/future, votes descriptive and never authoritative valuation |
| **H.** Chat product reconciliation | `C7-AI-01` | mapped; the row already records the orphan `src/api/chat.py` with no planning record |
| **I.** Usage / opportunity signal engine (`src/api/opportunity_stats.py`) | `X-06` | **SUPERSEDED** — replaced by `src/consensus_edge/opportunity.py`. The directive's own instruction ("wire it only according to its actual purpose") is satisfied by the existing disposition |
| **J.** General Sleeper account onboarding | `X-07` | **OWNER-REJECTED — unchanged.** See §4.5 |

**Unmapped from Part XIX = 0.**

---

# 4. Owner methodology authority reconciliation

Four topics where the directive and an existing repository record could be read as
disagreeing. Each is resolved on cited evidence, never on which rule is easier to build.

| topic | competing rules | source / date | direct owner instruction? | final disposition |
|---|---|---|---|---|
| Meaningful roster core | fixed `QB3/RB3/WR5/TE3/DL5/LB5/DB5` **vs** `ceil(1.5 × real starter demand)` | **A:** `MASTER_PRODUCT_PLAN.md` §4.1, undated, self-labelled "initial" and explicitly not-yet-canonical · **B:** addendum **#839**, 2026-08-14 | **A yes** (initial) · **B yes** (explicit, dated, names A) | **B is canonical. A is superseded.** B ships as V1 champion labelled **PRIOR** |
| FLEX supplement | separate remaining-player supplement **vs** flex folded into dedicated starter demand | `OWNER_REQUESTED_TODO_SPEC_INDEX.md` **T-NEW-19**, "BINDING C-SERIES ROSTER FOUNDATION" | **yes** | **Separate supplement**, `ceil(1.5 × real flex slots)` per flex family; Superflex folded into QB demand *before* 1.5×; each player counted once. **ORDERING SUPERSEDED 2026-08-18 by addendum #899:** the "after dedicated cores" clause no longer holds — actual FLEX/SF/IDP-FLEX **starters** are assigned as part of the starting lineup and removed from every pool *before* reserve/depth selection, so reserve demand is `ceil(M × slots) − slots`. Magnitude and the 1.5× PRIOR are unchanged; only the order is. See `docs/OWNER_FEATURE_ADDENDUM_2026-08-18_FLEX_STARTER_ASSIGNMENT.md` |
| KTC Value Adjustment | directive's four-term constants **vs** the repository's verbatim `processV` port | V12 at `frontend/lib/trade-logic.js:113` (+ its `:78-83` provenance note) · port at `:296-312`, which replaced V12 on 2026-04-26 · `:588-595` marks V12/V13 deprecated and off the live path | directive quotes V12 **and** instructs "read the existing validated implementation for the exact coefficients and constants" | **The validated live `processV` port is the consolidation target.** See §4.3 |
| Future-pick decay | fixed `1.5` exponent **vs** evidence-fitted local decay | `MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md` §3.1 (binding) · challenger record in `docs/picks/C1_U6_PICK_VALUE_COMPLETENESS.md` | policy yes | **Measured per-cell vendor year-step**, promoted 2026-08-16; **still classified PRIOR** because the 2-out→3-out extrapolation is untestable on current evidence |

## 4.1 Meaningful roster core — the provenance, in full

**Rule A** is `docs/MASTER_PRODUCT_PLAN.md` §4.1 ("Canonical roster intelligence → Team
Strength"): *"Owner-approved **initial** roster-value groups: QB top 3 · RB top 3 · WR top
5 · TE top 3 · DL/EDGE top 5 · LB top 5 · DB top 5."* It is a direct owner instruction, and
its own record qualifies it twice — the word "initial", and the `Method status` line
immediately below it: *"product definition approved; implementation **must
prove/consolidate competing existing strength notions before becoming canonical**."*
Rule A was therefore never recorded as frozen canonical methodology.

**Rule B** is owner addendum **#839**, dated **2026-08-14**, promoted to `main` from PRs
#816/#835. It survives in three canonical records:

1. `docs/OWNER_FEATURE_INVENTORY.md` row 1.7 — *"**OWNER DECISION 2026-08-14: BUILD.**
   **Replaces hard-coded QB3/RB3/WR5/TE3/DL5/LB5/DB5 selection** and raw full-roster sums
   with one league-config-derived selector."*
2. `docs/OWNER_REQUESTED_TODO_SPEC_INDEX.md` **T-NEW-19**, status *"BINDING C-SERIES
   ROSTER FOUNDATION"* — the full rule.
3. `docs/C_SERIES_SCOPE_MANIFEST.md` row `C2-CORE-01`.

Three facts establish B as an explicit later owner decision rather than an implementation
convenience:

- it is recorded as an **OWNER DECISION with a date**, not a recommendation;
- it **names Rule A explicitly and states that it replaces it**;
- `docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md` §E3 classifies the #839–#843 cohort as *"the
  newest owner intent in the repository, so under the precedence rule they win over
  anything older they contradict"* — and two other supersessions from that same cohort
  (#841/#842, withdrawing two Best Trade hard rules) were accepted on exactly that basis.

**The 2026-08-15 calibration policy did not originate Rule B.** Its §4.3 says *"**Keep**
`ceil(1.5 × real starter demand)` as the approved V1 champion"* and adds a challenger
obligation. It constrains an owner decision; it does not create one. Attributing Rule B's
authority to the calibration policy would be a category error, and this document exists
partly to prevent that misreading recurring.

### Consequence for C2-U6

Rule B ships as the **V1 champion, labelled PRIOR** — not as empirically discovered truth.
Before it is frozen, `C2-U6` runs the challenger pass the calibration policy requires:
**1.25× · 1.50× · 1.75× · a data-derived marginal-value / replacement-impact cutoff**,
evaluated for stability across league formats. No challenger may displace the champion
without pinned inputs, leakage-safe validation, champion/challenger comparison and an
explicit owner decision.

Rule A is retained in the Master Product Plan as historical context with a supersession
pointer, not deleted — it records owner intent faithfully at a lower resolution.

## 4.2 The FLEX rule — the two records agree once rounding is read from the binding spec

The directive states `F = 1.5 × FlexSlots` and leaves rounding open. **T-NEW-19 supplies
the rounding rule and the same multiplier**, so there is no conflict and nothing to invent:

```
QB_demand      = dedicated_QB_slots + superflex_slots   # Superflex folded in FIRST
core(pos)      = ceil(1.5 × dedicated_slots(pos))       # QB uses QB_demand
flex_core(off) = ceil(1.5 × offensive_flex_slots)       # AFTER dedicated cores
flex_core(idp) = ceil(1.5 × idp_flex_slots)             # AFTER dedicated cores
selection      = highest-valued remaining legally eligible players
invariant      = each player counted at most once
```

T-NEW-19 verbatim: *"Regular offensive FLEX and defensive/IDP FLEX **each create
`ceil(1.5 × real flex slots)` after dedicated cores are selected**, and are filled by the
**highest-valued remaining legally eligible players**. Each player may count once."* and
*"**Superflex is always QB demand:** add real Superflex count to QB starter demand before
applying 1.5×."*

So the owner's flex supplement is preserved as a genuinely separate supplement, Superflex
is never treated as ordinary RB/WR/TE FLEX, and no player is double-counted. An earlier
draft of the campaign plan classified the directive's flex formulation as a CHALLENGER on
suspicion of double-counting; **that classification was wrong and is withdrawn here.**

## 4.3 KTC Value Adjustment — why the directive's constants were not selected

The directive's C3.5 describes nonlinear terms *"such as `(p/v)^8`, `(p/t)^1.3`,
`(p/(v+2000))^1.28`"*. Those are the constants of `ktcRawAdjustment`
(`frontend/lib/trade-logic.js:113`), which that file documents as **V12 — a
regression-fit approximation** of KTC's algorithm (`:78-83`).

`trade-logic.js:296-312` records that V12 was **replaced on 2026-04-26** by `ktcProcessV`,
*"ported verbatim from `site.min.js::processV`"*, and `:588-595` marks the V12/V13 path
deprecated and *"no longer on the live VA path"*. Implementing the quoted constants would
therefore regress from KTC's real algorithm to an older fit of it.

The directive's own instruction resolves this: *"Read the existing validated
implementation for the exact coefficients and constants."* **`C3-U2` consolidates onto the
verbatim `processV` port** (`src/trade/ktc_va.py::ktc_process_v` and its JS twin), freezes
a deterministic fixture corpus before refactoring, proves `VA_before(trade) ==
VA_after(trade)` on every fixture whose semantics are intended to be unchanged, and
retires the stale kernels, the deprecated V12 route, the wrappers and the import-time
monkeypatch where safe.

KTC VA remains a named external-market/package lens and is not "improved" during
consolidation. Alternative package formulas — including the directive's CES
`(Σvᵢ^θ)^(1/θ)` with θ≈1.20 — remain separately labelled CHALLENGER research and never
ship under the KTC label.

## 4.4 Concepts that may not be collapsed

Whatever the meaningful-core methodology, these stay distinct and separately expressible,
in the model and in the UI:

**Total Asset Value** · **Meaningful Roster Strength** · **Exact Starting Lineup** ·
**Depth Value** · **Power Ranking** · **Playoff Probability** · **Championship
Probability**.

A roster may simultaneously hold high total asset value, weak meaningful strength, a poor
current lineup, strong depth and low title odds. T-NEW-19 already requires that *"a
separately labeled full-roster asset-capital total may exist, but must not masquerade as
Team Strength"*, and `MASTER_PRODUCT_PLAN.md` §4.1 already states that Team Strength *"is
**not** Power Ranking, Playoff Odds, or ROS production"*. C2 makes both executable.

## 4.5 `X-02` and `X-07` remain OWNER-REJECTED

The directive's C0.5 and Part XIX-J describe general "link any Sleeper account"
onboarding; its C9.8 and C9.9 describe a Money/dues ledger and a Constitution.

**The owner confirmed on 2026-08-17 that both dispositions stand:**

- **`X-02`** — Money / dues / Constitution / League Media → **OWNER-REJECTED**
- **`X-07`** — general "link any Sleeper account" onboarding → **NOT-PRODUCT-SCOPE /
  OWNER-REJECTED**

These are recorded here because a restatement inside a large directive is exactly how a
rejected item gets silently reintroduced. Neither is to be relitigated unless the owner
explicitly reverses the decision. `C10-U1`'s zero-loss re-audit must confirm both are
still absent from the product, not quietly reintroduced under another name.

---

# 5. Deliberately not done

- **The 104-row band mapping is not copied here.** It lives in traceability §F. A second
  copy is a second mapping.
- **No manifest row was added.** Every directive item resolved to an existing row or an
  existing disposition, so the row count is unchanged at 163.
- **`C1-U7` is not reordered into the C1 block.** It declares `deps C1-U6, C2-U4`, and
  owned-pick slot distributions are a function of simulated standings, hence of Team
  Strength. It runs immediately after `C2-U4`. Recorded in `docs/EXECUTION_PLAN.md`.

---

# 6. Governance defects found while reconciling, and repaired in this unit

1. **Mis-cited provenance for #839.** `docs/OWNER_FEATURE_INVENTORY.md` row 1.7 and
   manifest row `C2-CORE-01` both cited *"owner decisions 47–49 in the intake ledger"*.
   In `docs/OWNER_REQUESTED_TODO.md`, decisions **47–49 are the Weekly Report Studio /
   Manual-External-AI decisions** (#829), and `#839` appears nowhere in that ledger — it
   arrived as a dated addendum on PRs #816/#835, promoted by capability. The citation
   pointed at unrelated rows and would make a future session doubt a decision that is in
   fact well evidenced. Both citations now name the real source: addendum #839,
   2026-08-14, promoted to `OWNER_FEATURE_INVENTORY` 1.7 + `SPEC_INDEX` T-NEW-19, with
   traceability §E3 as the precedence basis.
2. **Superseded-rule census understated.** `docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md` §6
   listed **three** superseded owner rules and had not been updated for the two Best Trade
   supersessions its own §E3 records (#841 `no draft picks`, #841/#842 exact-equal player
   count); the manifest's §5 counts table listed **five** and omitted the fixed-cap
   supersession established in §4.1 above. Both records now say **six** and enumerate the
   same six.

---

# 7. Production verification checklist

Written 2026-08-17 as a **precondition of closure**. `EXECUTION_PLAN.md` §0.2 requires a
named production-verification checklist before a unit may reach `CLOSED-PENDING-PROD`, and
C0-R was queued without one — a governance defect in the governance unit, repaired here
rather than waived.

## 7.1 The honest shape of this one

**C0-R changes no runtime behaviour.** It is planning records plus standing-invariant tests;
its diff touches `docs/`, `PRODUCT_PLAN.md` and `tests/docs/`, and no module the server
imports. So there is **no user-visible surface to probe**, and inventing one — asserting an
API response that this unit cannot affect — would manufacture evidence rather than gather it.

What *can* be verified against the deployed SHA is that the authorization records this unit
repaired are the ones actually shipped, and that the invariants it added still hold on that
tree. That is the whole of the claim, and the checklist is scoped to exactly it.

## 7.2 The checklist

Read the deployed SHA from the prod host's
`/home/dynasty/.deploy-state/trade-calculator.last_successful_deploy_commit` or from the
deploy log's `In production: <sha>` line — `/api/health` exposes no commit. **Do not assume
it.**

| # | check | how | pass condition |
|---|---|---|---|
| 1 | the deployed SHA contains this unit | `git merge-base --is-ancestor <c0r-merge-sha> <deployed-sha>` | ancestor, exit 0 |
| 2 | the deploy was not degraded by it | the deploy run's `Validate Build Inputs` job | success |
| 3 | the authorization record shipped intact | at `<deployed-sha>`: `docs/EXECUTION_PLAN.md` exists and is the single authorization record | `scripts/check_planning_integrity.py` reports *exactly one authorization record* |
| 4 | the governance invariants hold on the deployed tree | `git checkout <deployed-sha>` in a scratch worktree, then `python scripts/check_planning_integrity.py` and `python scripts/check_product_plan_governance.py` | both exit 0 |
| 5 | this unit's own standing tests hold there | `python -m pytest tests/docs/ -q` on that tree | all pass |
| 6 | the repaired census figures are the shipped ones | at `<deployed-sha>`: manifest row count, source-family count, superseded-rule count (**six**) | match §6's repaired values |
| 7 | the reserved completion phrase is still unclaimed | `scripts/check_planning_integrity.py` | reports *reserved completion phrase not claimed* |

## 7.3 What would falsify it

Item 4 or 5 failing on the deployed tree means the records shipped in a state the gates
reject — i.e. something was merged past them, which is the exact drift this unit exists to
prevent. Item 6 failing means a later unit edited a census without updating its declared
count, which `check_planning_integrity.py` is built to catch and which would make this
unit's repair stale rather than wrong.

**Item 7 is a standing obligation, not a one-time check.** Five units are `MERGED — PENDING
PROD PROOF` as of 2026-08-17, so the completion phrase may not be claimed by anyone yet
(§0.2), and this item re-asserts that on every deployed tree.
