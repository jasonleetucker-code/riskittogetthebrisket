# Owner directive — research a potentially better hybrid Value Adjustment (2026-10-19)

**Recorded verbatim**, with the directive's bullet lists reflowed into sentences; no requirement was
dropped or reworded. Intake: `docs/OWNER_REQUESTED_TODO.md` ("Added 2026-10-19 — Hybrid Value Adjustment research").
Research memo answering it: `docs/valuation/PACKAGE_MODEL_HYBRID_RESEARCH_2026-10-19.md`.

---

OWNER DIRECTIVE — RESEARCH A POTENTIALLY BETTER HYBRID VALUE ADJUSTMENT

Repository: jasonleetucker-code/riskittogetthebrisket · Website: chaseupside.com · Priority: Valuation
research and improvement.

This is an authorized research and challenger-development task. Do not interrupt or delay the existing
site-completion campaign, current Trade Calculator releases, source-voting corrections, or production
verification.

**BACKGROUND.** KeepTradeCut's Value Adjustment is the original methodology I became familiar with. We
subsequently developed and activated our own geometric Value Adjustment: geom_q078_v1, q = 0.78. I
understand why we moved away from KTC's formula, particularly its demonstrated mathematical problems and
substantial preference for consolidation. However, I want to investigate whether combining useful
characteristics of KTC's methodology and our geometric methodology could produce a better overall Value
Adjustment. My initial thought was to average the two adjustments, potentially using a 50/50 split. I am
not committed to that approach. I want an evidence-based investigation to determine whether averaging,
weighting, or developing a different hybrid would produce a demonstrably better methodology. The objective
is to find the best Value Adjustment, not to force two formulas together.

**1. REVIEW OUR EXISTING RESEARCH FIRST.** Examine
docs/valuation/PACKAGE_MODEL_EVALUATION_2026-10-17.md,
docs/valuation/PACKAGE_MODEL_OWNER_ACTIVATION_2026-10-17.md,
docs/valuation/evidence/package_model_2026-10-17/, config/trade/package_model.json,
src/valuation_math/package_model.py, frontend/lib/trade-logic.js, scripts/package_model_benchmark.mjs,
and the dual-Value-Adjustment comparison work in PR #1826. Do not recreate existing research
unnecessarily. Pay particular attention to: KTC's consolidation bias; our geometric model's behavior on
deep packages; monotonicity; scale invariance; side-swap symmetry; existing HYBRID_50 research; actual
historical trade evidence; known mathematical failure cases. Be aware that the previously tested
HYBRID_50 is not an average of KTC and geom_q078_v1. Do not confuse those models.

**2. TEST MY ORIGINAL AVERAGING IDEA.** Evaluate a straightforward 50/50 combination of geom_q078_v1 and
ktc_2026_04. Both must operate on the exact same canonical Chase Upside player values. Do not use native
KeepTradeCut player values for one side of the comparison. For each model, independently calculate the
adjusted totals and signed value gap. For a proposed 50/50 blend: blendedGap = 0.50 * geometricGap +
0.50 * ktcGap. The raw values must remain identical across the models. If representing the blended result
through our existing positive-only Value Adjustment interface, derive the adjustment from the blended
signed gap and the common raw gap. Do not simply add both formulas' bonuses together. Do not create two
independent bonuses that improperly inflate both trade sides. Test additional weights: 75/25, 60/40,
50/50, 40/60, 25/75 (geometric / KTC). These are experimental candidates, not approved production weights.
Determine whether any combination is mathematically valid and empirically useful. Include all previously
documented KTC failure cases. Specifically test A = [7200] B = [6000] versus A = [7200] B = [6000, 1].
Adding a positive asset to B must not make B's result worse. This is a mandatory property for any
recommended production model. If averaging KTC reintroduces known mathematical defects, report that
clearly. Do not conceal those defects because the blended results appear more balanced overall.

**3. EVALUATE MATHEMATICALLY CONSISTENT ALTERNATIVES.** Do not limit the research to averaging KTC and
geometric adjustments. Investigate alternative package-utility approaches that could combine the useful
characteristics of both. Include: the current geometric model, q = 0.78; reasonable geometric
alternatives previously studied; the existing HYBRID_50 challenger; appropriate monotone hybrid utility
models; other justified approaches that preserve consistency. The goal is to balance consolidation value
(receiving one excellent player instead of several lesser assets should sometimes deserve a premium) and
depth value (receiving multiple useful assets should retain meaningful value). We should not
automatically favor the superstar. We should not automatically favor the larger package. We should
recognize that roster limits and actual player usefulness matter. But do not embed roster-fit
assumptions directly into the mathematical package adjustment when those factors already belong to
separate parts of our trade analysis. Avoid double-counting team fit, starting lineup value, roster cuts,
or positional scarcity.

**4. REQUIRED MATHEMATICAL PROPERTIES.** Any model recommended for production must satisfy: (1) adding a
positive-value asset to one side cannot make that side's mathematical result worse; (2) increasing an
existing asset's value cannot make that side's mathematical result worse; (3) swapping trade sides must
reverse the gap without changing the underlying trade evaluation; (4) reordering players within a package
cannot change the result; (5) scaling all player values proportionally should scale the model's results
proportionally; (6) one-for-one trades must not receive an artificial package adjustment; (7) missing or
unpriced assets cannot silently become zero-value observations; (8) the model must behave consistently
across offense, IDP, and draft picks; (9) the implementation must preserve one canonical adjusted gap and
one authoritative fairness classification; (10) the model must not produce arbitrary discontinuities when
a low-value asset is added. Do not compromise mathematical correctness merely to imitate KeepTradeCut's
historical behavior.

**5. TEST DIFFERENT TRADE STRUCTURES.** Evaluate at least 1-for-1, 1-for-2, 1-for-3, 1-for-4, 1-for-6,
1-for-10, 2-for-2, 2-for-3, 2-for-4, 2-for-6, 2-for-10, 3-for-3, 3-for-4, 3-for-6, 4-for-4, 4-for-6,
5-for-10. Include high-value superstar trades, mid-tier starter trades, bench-depth packages, IDP-only
trades, mixed offense/IDP trades, trades involving rookie picks, trades involving future picks, packages
containing very low-value assets, packages containing players with similar values, trades with large
raw-value differences, trades with nearly identical raw totals. Use realistic asset distributions from
our canonical valuation board. Include genuinely held-out cases instead of relying exclusively on
synthetic examples. Do not confuse balanced win percentages with actual accuracy.

**6. DETERMINE WHETHER A HYBRID IS ACTUALLY BETTER.** For every candidate, compare: mathematical property
failures; frequency of favoring fewer assets; frequency of favoring more assets; frequency of favoring
the single highest-valued asset; frequency of reversing the raw-value leader; sensitivity to adding
low-value pieces; behavior on deep packages; sensitivity to trade size; median and extreme value
differences; differences in trade classifications; impact on Trade Finder recommendations; impact on
Trade History; impact on Second Opinions; impact on other consumers of the canonical package model. Run
the existing reproducible benchmark suite. Where available, use historical completed trades with
point-in-time values. Use chronological holdouts and prevent future information from leaking into
earlier valuations. Historical trade acceptance can provide useful evidence, but do not treat an accepted
trade as proof that the adjustment was objectively correct. If enough independent evidence is available,
compare predictive usefulness or calibration. If the historical sample is too small, report that
limitation rather than inventing confidence. A hybrid must show a defensible improvement over the
incumbent. Being numerically halfway between two models is not sufficient evidence of improvement.

**7. PRESERVE THE CURRENT PRODUCTION MODEL.** Until I explicitly approve a replacement: geom_q078_v1
remains the authoritative package Value Adjustment; q remains 0.78; ktc_2026_04 remains the read-only
comparison and rollback method. Do not change the canonical trade verdict, the active fairness
calculation, Trade History valuations, Trade Finder's authoritative values, War Room recommendations,
Second Opinions tallies, or other downstream trade decisions. You may implement experimental challenger
models behind appropriate disabled-by-default controls. Do not expose an experimental hybrid as an
official valuation method. Do not introduce multiple competing verdicts. Do not interrupt PR #1826's
existing side-by-side comparison implementation. Preserve the established distinction between "KTC
adjustment method applied to Chase Upside values" and "KeepTradeCut's own player valuations." These are
not the same thing.

**8. IMPLEMENT A CHALLENGER ONLY IF JUSTIFIED.** If the research identifies a promising candidate,
implement it as a named, versioned, non-voting challenger. Use the existing canonical package-model
architecture. Maintain JavaScript/Python parity. Add comprehensive mathematical property tests. Preserve
source-of-truth configuration. Add rollback support. Ensure the candidate can be evaluated without
affecting current production decisions. If the candidate cannot pass mathematical correctness
requirements, do not recommend it for activation. If the existing geometric model performs best, say so.
I am comfortable keeping the current model if the evidence does not justify replacing it.

**9. PROVIDE A CLEAR OWNER REPORT** explaining: A. whether averaging our Value Adjustment with KTC's is a
good idea; B. whether a weighted average is any better; C. whether another mathematically consistent
hybrid performs better; D. which model handles ordinary 2-for-3 and 1-for-3 trades best; E. which model
handles very large packages best; F. whether the proposed model is supported by actual historical trade
evidence; G. the mathematical and practical trade-offs; H. your recommended model and the evidence
supporting it; I. whether you recommend retaining geom_q078_v1 unchanged; J. exactly what would change in
production if I approved a new model. Use plain English. Show concrete player-value examples rather than
only statistical summaries. Do not recommend a change simply because it produces prettier or more
balanced numbers.

**FINAL OWNER INSTRUCTION.** I want the best possible Value Adjustment for Chase Upside. I am not attached
to KeepTradeCut's formula. I am not attached to averaging two formulas. I am also not opposed to keeping
our current geometric model. My goal is accuracy, consistency, and appropriately valuing both superstars
and depth. Research whether a hybrid can actually improve our trade evaluations. Test my original
averaging idea honestly. Explore mathematically stronger alternatives. Use evidence rather than
assumptions. Keep the existing production model active while doing this work. Do not activate a new Value
Adjustment without my explicit approval. Continue all previously authorized Chase Upside completion work
in parallel. When the evaluation is complete, present your recommendation so I can decide whether to
promote the challenger.
