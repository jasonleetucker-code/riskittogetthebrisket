# Roster & Trade Intelligence (WS-J) — Architecture Decision Records

Numbering continues the League Intelligence series in
`docs/league-intelligence/DECISIONS.md` (ADR-001..007) so a reference
like "ADR-008" is unambiguous across both workstreams.

---

## ADR-008: Continuous Improvement — the refit is gated, not trusted

**Directive clause.** *"Do not allow a model to autonomously rewrite
production code. Use controlled retraining, champion–challenger
validation, model versioning, and rollback. Do not present
low-confidence output as precise."*

### Finding: what the refit path actually does today

`.github/workflows/refit-hill-curves.yml` runs weekly (Tue 06:17 UTC).
On drift above 50 RMSE points it invokes
`scripts/auto_refit_hill_curves.py`, which:

1. rewrites the eight `HILL_*_C/S` constants in
   `src/canonical/player_valuation.py` — the live valuation path,
   step 3 of the Final Framework;
2. rewrites `PINNED_DELTAS` in
   `tests/canonical/test_ktc_reconciliation.py`, the only test that
   guards those constants;
3. runs `pytest -m "not livedata"`;
4. commits and pushes to `main`, which triggers `deploy.yml`.

No human sees the diff. That is the "model autonomously rewriting
production code" the directive prohibits, and the prohibition is not
academic: the constants determine every displayed value on the board.

**The guard cannot fail.** Two independent reasons, either sufficient:

* *The pins are recomputed from the challenger.*
  `rebaseline_ktc_reconciliation` computes `ours = _hill(p, c_new,
  s_new)` and writes it as the test's `pinned_ours`, then computes
  `pct_diff` from that same `ours` against the same `ktc.csv` the test
  reads. Both of the test's assertions — the exact
  `ours == pinned_ours` pin and the `abs(actual_pct - pinned_pct) <=
  tolerance_pp` band — therefore have a zero residual by construction,
  for *any* curve. Verified in
  `tests/model_registry/test_refit_path_characterisation.py` by running
  the rebaseline arithmetic for `(c=0.118, s=1.17)` and `(c=0.300,
  s=2.50)`: both pass every pinned rank.
* *KTC is a training source.* `ktc.csv` is in
  `fit_hill_curve_percentile.OFFENSE_SOURCES`, which fits
  `HILL_PERCENTILE_C/S` — precisely the constants
  `percentile_to_value` uses and the test evaluates. Scoring a fit
  against its own training data is ORCHESTRATION.md §2b: the
  assumption reflected back.

The repo already half-knew this. The workflow's own comment says the
pins "are REWRITTEN by this very refit — so gating the refit commit on
them is circular", and uses it to justify *excluding* them from the
blocking gate. The conclusion drawn was "don't gate on the circular
check". The conclusion available was "the check is circular; build one
that isn't".

### Decision

A refit produces a **challenger**, never a champion. Promotion is a
separate, recorded act gated on a criterion the fit never saw.

**Held-out criterion.** Mean per-source RMSE of the OFFENSE master
against four value-publishing dynasty boards that
`fit_hill_curve_percentile.py` does not read: FantasyCalc, OTCFFB,
PFKDynasty, FantasyNavigator. Same metric as the fit's own objective
(top-400, native percentile, top anchored at 9999) so the numbers are
comparable; different data, so the check can fail.

`ktcSfTep` is deliberately **not** treated as held out despite being
absent from the fit's source dict — it is KeepTradeCut's own SF-TEP
board, the same market maker as the `KTC` training source. The
train/holdout split is enforced by **file path**, not label, so
relabelling a training CSV cannot smuggle it back in.

**What the criterion measures — and does not.** It measures
generalization across dynasty markets: whether a curve fitted to six
boards also describes boards it never saw. It does **not** measure
accuracy against reality. Every holdout board is another consensus
market pricing the same players off the same news, and there is no
ground truth for what a dynasty asset is worth. A promotion means the
challenger is less overfitted to its six training boards. It does not
mean the challenger is right. Both statements ship in the payload's
`_semantics` block.

**Promotion margin: 25 points**, measured rather than chosen. Champion
and challenger are always scored on the *same* snapshot, so market
drift is common-mode and cancels. Across 30 real FantasyCalc snapshots
(2026-04-03 → 04-08) the *absolute* criterion moved 584.90–653.04 (sd
19.28) while the *paired* delta between two fixed curves was
near-deterministic — worst sd 1.51, zero sign flips in 29 consecutive
pairs. The noise floor a margin must clear is therefore ~1.5, not ~19;
25 sits ~16× above it. Ties go to the incumbent.

**Unmeasured incumbent blocks promotion.** If the champion has no
out-of-sample score, no challenger can pass it. An unmeasured incumbent
is unknown, not beaten, and promoting past it would reproduce the
autonomous rewrite in a new costume.

**Rollback** is two commands (`rollback` then `apply`), not a hand-edit
of eight floats from a diff. Only a *former champion* is a valid
rollback target; reinstating something never live is an unvalidated
promotion wearing the word.

**Confidence honesty** is structural, not advisory. A version with no
held-out score is `qualified=False` / `confidence="unvalidated"`, and
`status` prints a warning. Buckets are coarse (`unvalidated` /
`provisional` / `measured`) on purpose: a continuous confidence score
here would itself be an unvalidated model.

### Measured result on the shipped champion

The live OFFENSE master (`c=0.118, s=1.17`) scores **849.8** on the
held-out criterion — FantasyCalc 852.6, FantasyNavigator 1185.2,
OTCFFB 1104.9, PFKDynasty 256.7.

A curve at `c=0.098` scores **648.2** on the same boards. **The live
champion is not at the holdout optimum, and the gap is ~200 points.**
This is reported, not acted on: changing it is a live valuation change
requiring its own verification of downstream effects, and this
workstream's constraint was explicitly not to fold that in. Scoped as
follow-up work.

Note also that the training and holdout objectives *disagree in
direction* — moving to `s=1.37` makes the training mean worse
(774 → 797) while making the holdout mean better (850 → 758). That
disagreement is the evidence that the gate is not a rubber stamp for
the fit.

### Not implemented, and why

* **Temporal holdout.** Rejected as currently unbuildable rather than
  built weakly. `data/raw/ktc/2026/` holds 30 snapshots spanning
  2026-04-17 → 04-20 — four days, three months stale. A four-day
  forward window cannot distinguish curve quality from a quiet market,
  and no held-out-in-time evaluation over it would be evidence. If
  snapshot retention is extended to cover a season, this becomes the
  stronger criterion and should replace the cross-source one.
* **Gating IDP / GLOBAL / ROOKIE masters.** Only the OFFENSE master has
  a genuine holdout today; the IDP and GLOBAL scopes are trained on
  IDPTradeCalc and DraftSharks, and the only other IDP value boards in
  the repo (`idpShow`, `footballGuysIdp`) feed the live blend but have
  not been checked for independence from the fit. The registry versions
  all eight constants; the *validation* covers the OFFENSE pair. This
  is stated in the payload rather than papered over.
* **The workflow rewiring itself.** `.github/workflows/refit-hill-curves.yml`
  and `scripts/auto_refit_hill_curves.py` are **untouched** by this
  change. Fixing them is a fix to the existing refit path — production
  automation that currently pushes to `main` and triggers `deploy.yml`
  — and it is scoped separately on purpose rather than folded into the
  change that characterises the defect. Nothing in `src/model_registry/`
  runs on a schedule, imports the valuation pipeline, or alters any
  endpoint. The registry records and gates; today a human drives it.

### Proposed wiring (scoped, not landed here)

The minimal follow-up, for review as its own change:

1. Refit emits challenger params instead of writing them:
   `fit_hill_curve_percentile.py --json-out challenger.json`.
2. `model_registry.py evaluate --champion --record`
3. `model_registry.py register --params challenger.json`
4. `model_registry.py validate <n>` — exit 0 promotes, 1 rejects.
5. Commit **only** `config/model_registry/*.json`. Production constants
   move solely via `promote` + `apply`, run by a human.

That removes both halves of the defect: the constants stop being
rewritten unreviewed, and the guard stops being rewritten at all.

**Status:** accepted 2026-07-26; implementation in `src/model_registry/`.
