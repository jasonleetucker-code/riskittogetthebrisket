# Sparse-evidence estimator: preregistration (Batch 3 Unit E)

Committed **before** any candidate score was generated. The results file
(`results.json`) records the sha256 of this file; a result whose hash does not
match this commit is not a result of this preregistration.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## What is being replaced

The single-source haircut (`_SINGLE_SOURCE_VALUE_RETENTION = 0.30`): a non-pick
row whose present evidence is one provider family keeps 30% of its blend. The
owner rejected "one family ⇒ 30%". #1571 showed that deleting the haircut
(candidate A below) promotes 51 deep rows ×3.33 (DJ Rogers, TE, Draft Sharks
only: unranked → rank 271).

The haircut confuses two things: **where the value is** (central estimate) and
**how sure we are** (uncertainty). Uncertainty already has one owner,
`src/api/confidence.py`, and a one-family row cannot exceed LOW there. So the
estimator only has to answer the central question honestly.

## Scope (fixed)

- Rows: exactly the incumbent haircut set — non-pick rows whose present families
  (voting + freshness-excluded) number ≤ 1, with a positive observed blend.
- Flag: `sparse_evidence_estimator`, default OFF. OFF is the incumbent.
- Nothing else changes: the filter, freshness, the family cap, the blend for
  every row with ≥ 2 present families, picks.

## Candidates (fixed set)

| id | central estimate | notes |
|---|---|---|
| I | incumbent: 0.30 × observed blend | baseline |
| A | observed blend, unchanged (= #1571 `joint_sparse_limited_evidence`) | passthrough |
| B | shrinkage toward an independent point-in-time prior | **not evaluable** — see below |
| C | censor-aware family bounds (defined below); A when no bound binds | **primary challenger**, implemented behind the flag |
| D | C, but the value is withheld when no censored family is available (`uncorroborated`) | diagnostic only, computed from C's stamps; not implemented |

**B is not built.** No truly independent point-in-time prior exists for these
rows: KTC Market is a descendant of the KTC Crowd/Trades families and is
forbidden from voting; BDVM is a separate concept that may not become canonical
market value; yesterday's board is a descendant of the same observations (and of
the haircut itself); a Hill prior generated from the same observation would
count that observation twice. Fabricating one is out of scope.

## Candidate C, exactly

Let row *r* (position *P*) have observed value *x* > 0 from its one family *F₀*.

**Listed.** A source *s* listed *r* iff `canonicalSiteValues[s]` is present (the
`sourcePresence` rule: non-None for DraftSharks combined-rank keys, > 0
otherwise). Presence counts whether *s* voted, was outlier-dropped,
freshness-excluded, family-superseded, rookie-excluded or withheld for want of a
bridge. A family is listed iff any member listed *r*. Listed families are never
censored.

**Witness.** A source *s* in a non-listed family is a censor witness for *r* only
if ALL of:

1. *s* is active (not disabled by an override);
2. *s* is scope-eligible for *P* (the same `_scope_eligible` test as the
   confidence coverage denominator);
3. *s* is not rookie-only (`needs_rookie_translation`) unless *r* is a rookie;
4. not (`excludes_rookies` and *r* is a rookie);
5. *s*'s registry `game_type` is `DYNASTY`;
6. *s*'s dataset state is measured, health `HEALTHY`, coverage known with
   coverage factor 1.0, and its players subset is `ON_SCHEDULE` (the existing
   top freshness band). Unmeasured / degraded / failed / stale / quarantined /
   unknown coverage ⇒ not a witness;
7. *s* ranked at least one row of position *P* in this build (an unranked
   position is never negative evidence);
8. identity: *s*'s CSV index holds no entry under *r*'s canonical match key (any
   position group) — a name the source published but that did not attach is a
   matching question, not an absence; and *r*'s canonical match key is unique on
   the board and *r* carries no quarantine-level anomaly flag.

Anything else — unknown coverage, failed fetch, inapplicable source, unranked
position, stale data, identity doubt — produces **no** bound, never a negative
one.

**Bound.** For a witness *s*: *Uₛ* = the smallest value contribution *s* stamped
on any row of position *P* in this build. An unlisted player sits beyond *s*'s
published depth, so its contribution under *s*'s monotone transform would be at
most that. A family bound is the loosest (largest) witness bound in the family,
*U_F* = max *Uₛ*; families are counted once, never per member.

**Binding.** *U_F* binds iff *U_F* < *x*. A non-binding bound carries no
information about *r* and is dropped (it is not an observation).

**Central estimate.** The pipeline's own `weighted_count_aware_mean_median_blend`
over `[x] + [U_F for binding F]`, weights: *x* at *F₀*'s capped voting weight;
each *U_F* at the weight *F* would vote with (base × source-level freshness ×
health × coverage of its witnesses, family-capped; base only when freshness
weighting is off). The blend is monotone in its values, so this is the
**largest** blend consistent with the evidence: every binding absent family
placed at its own published cutoff, the most generous place it could be. It is
not an invented last-place rank and not a shrink toward zero: it is the upper
end of the identified set; the lower end is not identified and is published as
such.

**No binding bound ⇒ central = *x*** (state `censor_nonbinding` if witnesses
exist, `uncorroborated` if none).

**Published per row** (additive `sparseEvidence`, only with the flag on): central
estimate; observed value; a **sensitivity interval** `[central, x]` labelled
uncalibrated (not a credible interval — nothing here is calibrated); observation
count; independent (voting) family count; effective family count (sum of the
voting families' capped weights); censored families used (family, bound,
witnesses); non-binding and refused families with reasons; confidence state
copied from `src/api/confidence.py`; state; reason.

Blend integrity: a row's hull includes its binding bounds (they are inputs to
its estimate).

## Inputs (pinned)

- Board: `exports/archive/dynasty_export_20260930_130404.zip` — the #1571 pin —
  rebuilt with `src/api/value_replay.py` from a clean committed tree, local
  `data/leagues` snapshots copied in and hashed.
- One build per candidate; only flags differ. I = flags off; A =
  `joint_sparse_limited_evidence`; C = `sparse_evidence_estimator`.
- H = rows with `singleSourceValuePenaltyApplied` in the I build at this SHA
  (reported against #1571's 51 names).

## Metrics (all reported)

rows changed by asset class; top-50/100/200/400 membership churn; for H: value
ratio distribution (C/I, C/A), state distribution, top-K entries, largest moves;
sparse IDP, rookies; picks changed; the trap; D's withheld count.

## Gates (hard; all must pass)

- **G1 trap.** Through the real `_compute_unified_rankings`: one row with
  3000/3100/3200 at effective weight 0.03 and 4600 at 1.0 (four distinct
  families), the naive weighted filter reproduced by patching the filter to drop
  the three weak observations. I must give 1380 (±1) — the failure reproduced —
  and C must give ≥ 4500.
- **G2 no deep-board explosion** (pinned board, over H):
  - G2a: 0 rows of H enter the top-200;
  - G2b: 0 rows of H enter the top-400;
  - G2c: median(C / I) over H ≤ 2.0 (A is 3.33 by construction).
- **G3 bounded influence.** Every H row: C ≤ A, and C ≥ the minimum of its
  estimator inputs.
- **G4 scope.** 0 non-pick rows outside H change value. A pick may change only
  through the documented rookie-pool tether (a current-year slot pick inherits
  the merged rookie pool's value, and an H rookie is in that pool); every pick
  change must carry `pickValueProvenance` `rookie_pool_tether`, and all are
  reported. Any other pick change fails.
- **G5 OFF identical.** Flag-off board hash at this SHA equals the base commit's,
  and the OFF path never calls the estimator (test).
- **G6 semantics tests** pass: unknown coverage / failed fetch / inapplicable /
  stale / quarantined identity never produce a bound; absences count by family;
  no invented last place; confidence via the owner.

## Decision rule

- Any hard gate fails ⇒ **does not meet gate**.
- All pass, but fewer than half of H have at least one witness family ⇒
  **insufficient evidence** (the censor path is not exercised enough to judge).
- Otherwise ⇒ **meets gate (promotion-eligible pending independent review)**.
  No outcome backtest exists; the sensitivity interval is uncalibrated; that is
  stated with the result and does not change the verdict category.
- D is reported, never selected in this unit. Nothing is promoted or flipped.
