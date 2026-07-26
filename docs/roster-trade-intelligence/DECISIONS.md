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

**The guard cannot fail.** Three independent reasons, any one
sufficient:

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
* *The guard is not even run.* `tests/conftest.py` auto-marks
  `test_ktc_reconciliation.py` as `livedata`, and the refit workflow's
  regression step is `pytest tests/ -q -m "not livedata"`. Verified:
  that command deselects all 13 of the guard's tests. The refit
  rewrites the guard's expectations and then skips the guard.

So the constants reach production, and trigger a deploy, with no check
of any kind — not a weak check, none.

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

The training and holdout objectives **disagree in direction**: moving
to `s=1.37` makes the training mean worse (774.4 → 796.8) while making
the holdout mean better (849.8 → 758.2). A rubber stamp cannot
disagree with what it stamps, so this is the evidence that the gate is
real.

**The champion is off the mean-holdout optimum — but the claim must be
stated narrowly.** A first pass recorded "~200 points off optimum at
`c=0.098`". Re-measuring per board rather than on the mean showed that
figure to be both too strong and too specific, so it is corrected here
rather than quietly dropped:

| board | role | RMSE @ champion | best on grid | best `c` |
|---|---|---|---|---|
| FantasyCalc | holdout | 852.6 | 321.2 | 0.080 |
| FantasyNavigator | holdout | 1185.2 | 401.5 | 0.080 |
| OTCFFB | holdout | 1104.9 | 395.8 | 0.080 |
| PFKDynasty | holdout | 256.7 | 240.3 | 0.112 |
| KTC | train | 816.6 | 172.6 | 0.144 |
| Fitzmaurice | train | 1116.3 | 514.8 | 0.180 |
| DynastyNerds | train | 1026.2 | 257.4 | 0.096 |
| DraftSharks | train | 683.2 | 359.5 | 0.080 |

Three findings follow, and the first two disqualify the original claim:

1. **The holdout boards do not agree.** At `c=0.098`, three improve by
   287–304 points and PFKDynasty gets **worse** by 80.5. PFKDynasty is
   also the board the champion already fits best — 256.7 against a
   best-possible 240.3, i.e. the live curve is within ~16 points of
   *that* board's optimum. The mean improvement is three boards
   outvoting one, not a consensus.
2. **The mean-holdout "optimum" is a boundary solution.** Three of four
   holdout boards bottom out at `c=0.080`, the edge of the search grid,
   so the grid does not bracket a minimum. Reporting `c=0.098` as "the
   optimum" was wrong: it is merely a point that scores better than the
   champion.
3. **The training boards disagree at least as much** (KTC wants 0.144,
   Fitzmaurice 0.180, DraftSharks 0.080). The champion at 0.118 sits
   near the training mean optimum (`c=0.104, s=1.15`, 750.8 vs the
   champion's 774.4) and far from the holdout mean optimum. That is
   consistent with the fit tracking its own sources — which is what a
   holdout is for.

**What is and is not supported.** Supported: *the mean criterion over
these four boards improves substantially at lower `c`, driven by three
of them.* Not supported: *the champion is wrong.* The holdout boards
may share a curve shape the fit sources do not, in which case the
"optimum" moves with that shared bias rather than toward accuracy.
Distinguishing the two needs evidence outside all ten boards, and none
exists here — the same limit already stated for the criterion itself.

**Nothing is acted on.** `src/canonical/player_valuation.py` is
byte-identical on this branch, and `model_registry.py apply --dry-run`
reports the shipped champion already matches the live constants (exit
1, no change). Any curve change is a live valuation change requiring
its own downstream verification and is explicitly out of scope here.

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

That removes all three defects: the constants stop being rewritten
unreviewed, the guard stops being rewritten at all, and the gate that
does run is one the fit never saw — so `-m "not livedata"` no longer
skips the only thing checking it.

**Status:** accepted 2026-07-26; implementation in `src/model_registry/`.
