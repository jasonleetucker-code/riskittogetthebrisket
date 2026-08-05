# Open modeling decisions — resolved to evidence

**Date:** 2026-07-29, updated 2026-07-30, updated 2026-08-05
**Context:** the 2026-07-29 repository audit
(`docs/audits/complete-codebase-audit-2026-07-30.md`) left three
questions as "requires a product decision". Each was under-specified:
they were stated as choices without the measurements needed to make
them. This document closes that gap. Decision #4 was added by the
2026-08-05 unfalsifiable-number audit on the same terms.

**Status:**

| # | question | outcome |
|---|---|---|
| 1 | apply `coverageWeight`? | **No.** Measured: 297 rows / 221 ranks move for a 3-source input change, with no accuracy evidence either way. Stays DIAGNOSTIC ONLY. |
| 2 | retire the legacy rank-form curves? | **No — re-tuned and kept**, with a tested drift alarm. Migration turned out not to be a live option; the old constants were fit to the wrong target. |
| 3 | re-threshold `low_conf_unstable`? | **No — rule retired.** The metric is structurally capped; no threshold makes it sound. |
| 4 | what width should the Monte Carlo band be? | **Open — deliberately.** The flat ±15% is 4.8× the median measured source disagreement but 0.4× the maximum. Made *visible* (`bandSources` + disclaimer) rather than silently re-tuned. |

#1 and #4 remain reversible-on-new-evidence; #2 and #3 are closed.

---

## 1. Should `coverageWeight` be applied to the blend?

**Status: measured. Recommendation — NO, not without a holdout backtest.**

`/api/data` publishes, under `methodology.idpTranslation.coverageWeight`:

```
effective_weight = declared_weight * min(1, depth / min_full_depth)   # min_full_depth = 60
```

It is computed per source, stamped as `sourceRankMeta.effectiveWeight`,
and never applied. The audit labelled it DIAGNOSTIC ONLY rather than
wiring it in, because nothing had measured what wiring it in would do.

**Reproduce:** `python scripts/measure_coverage_weight_impact.py`
**Results:** `docs/measurements/coverage-weight-impact-2026-07-29.json`

Only **3 of 21** sources are affected — the three rookie lists that
declare a depth under 60 (`dlfRookieSf`, `dlfRookieIdp`,
`flockFantasySfRookies`, all depth 50 → factor 0.8333). Every other
source declares depth ≥ 100 or None and is unchanged.

That small input change is not a small output change:

| metric | value |
|---|---|
| rows moved | **297 of 1094** (27%) |
| ranks changed | **221** (20%) |
| max abs value delta | **1072** points (~11% of the 1–9999 scale) |
| median abs value delta | 0 (most moves are rank-only) |
| board membership | 1 row enters, 1 row leaves |

Movement concentrates in ranks ~500–750 — deep players and rookies,
where coverage is thinnest. **Direction varies per player:**
down-weighting a rookie source raises a player that source was bearish
on and lowers one it was bullish on, so this is not a uniform haircut on
rookies.

**Why not to apply it as-is.** The rationale ("a 50-deep list should
count less than a 500-deep board") is defensible in principle, but:

- it reprices 221 ranks on zero accuracy evidence;
- the three affected sources are rookie lists that already
  ladder-translate into combined-pool space before reaching the blend,
  so part of the depth penalty they would take is arguably handled
  already;
- the effect lands hardest exactly where the board is least certain.

Applying an unvalidated reweighting to a fifth of the board because a
docstring described it is the kind of change this audit exists to
prevent. If it is wanted, it should go through
`src/model_registry/board_holdout.py` the way the adjusted-board lens
did (`docs/adjusted-board-backtest.md`).

**Kept as-is:** the mechanism stays computed and stamped, honestly
labelled diagnostic-only in the contract. The measurement above is now
the answer to "what would it do?", so the next reader does not have to
guess — or "fix" it casually.

---

## 2. Should the legacy rank-form Hill family be brought under the model registry?

**Status: NO — the proposal was wrong. Replaced with a tripwire.**

The audit flagged `HILL_MIDPOINT` / `HILL_SLOPE` /
`IDP_HILL_MIDPOINT` / `IDP_HILL_SLOPE` as a governance gap: outside
`src/model_registry`, refit by a different script than the percentile
scope masters, no out-of-sample gate. The proposed fix was a second
registry model.

**That was based on a false premise.** The registry exists to gate
*automated* promotion — the percentile masters are refit weekly by
`.github/workflows/refit-hill-curves.yml`, which is why they need a
challenger/champion flow. These four are not in that situation:

- `scripts/fit_hill_curve_from_market.py` is **read-only**. It opens
  CSVs, grid-searches, and prints. It contains no write of any kind
  (verified: no `write_text`, no `json.dump`, no regex substitution).
- **Nothing runs it** — no workflow, no systemd timer, no Makefile
  target. Every repo-wide reference is a docstring or a test.
- Its own docstring says "Use the output to update
  `player_valuation.py` constants" — i.e. a human edits them.

There is no automated promotion to gate. Wrapping a hand-edited,
manually-refit pair in challenger/champion machinery would have been
ceremony with no benefit, and would have added a second registry model
that nothing writes to.

**The actual residual risk** is narrower: someone edits these constants
and does not re-check whether the curve still reproduces the board. The
two families drift independently and the drift is *silent* — nothing
fails when the rank-form curve stops matching the percentile-derived
board. Every existing test imports these constants symbolically (right,
so a legitimate refit does not break them) and therefore none notices an
edit.

**Shipped instead:** `tests/canonical/test_rank_form_constants_tripwire.py`
pins the four values, so any change fails with a message pointing at
`scripts/backtest_legacy_rank_curve.py` and this document. A second test
asserts the refit script still does not write — because if it ever gains
that ability, it *does* become an automated promotion path and the
reasoning above has to be revisited rather than silently outgrown.

**RESOLVED 2026-07-30 — re-tuned and kept, with a drift alarm.** The
question above was "retire the rank-form family in favour of the
percentile masters?", and the 2026-07-29 answer was "hard, because the
error profiles are inverted". Re-measuring closed it:

* **Migration is not a live option.** On the current board the percentile
  candidates are 5–8× worse *everywhere* (410 and 692 RMSE against 83.8),
  not better-past-120-and-worse-in-the-top-24. The reason is structural:
  the percentile masters are an **input stage to the blend**, not a model
  of its output, so translating them into rank space cannot answer "what
  does our board pay at rank r".
* **The old constants were fit to the wrong target.** They came from
  `fit_hill_curve_from_market.py`, which fits retail *source* boards.
  Against `rankDerivedValue` the offense pair scored RMSE 821.8 — a ~9×
  error on every reconstructed offense value. Re-tuned to 65.4 / 0.910
  (offense) and 64.6 / 0.900 (IDP), it scores 89.8 / 76.2, which **is**
  the achievable floor for this curve family (83.8 overall vs 83.4 for a
  free fit). No headroom left; the residual is post-blend scatter.
* **The drift surface is now watched, and the alarm is tested.**
  `scripts/check_rank_form_drift.py` +
  `.github/workflows/audit-rank-form-drift.yml` (Tue 07:41 UTC, after
  the refit workflow) measure *excess RMSE over the achievable floor*
  per scope, budget 25.0. It opens an issue rather than a PR, because an
  automated patch that also re-baselined the guard tests would recreate
  precisely the by-construction-green circularity ADR-008 documents.
  `tests/canonical/test_rank_form_drift_check.py` proves the alarm fires.
* **Bonus finding: the real drift driver is percentile-master
  promotion, not market churn.** 16 snapshots over two weeks all refit to
  the same constants; the 2026-07-29 pre-promotion board refit to
  68.8 / 0.929 and the post-promotion board to 65.2 / 0.905. That is why
  the check runs after the refit workflow rather than daily.
* **A third copy existed.** `frontend/lib/value-history.js` still held
  `K = 45, EXP = 1.1, CEIL = 9999` — wrong on all three, with rank 1 at
  10000 instead of 9999 — behind a comment that flagged the risk and
  deferred the fix. Now a single `RANK_FORM_CURVE` object, pinned against
  Python by `tests/api/test_rank_form_frontend_parity.py`.

Full write-up: `docs/legacy-rank-curve-backtest.md` (2026-07-30 addendum).

---

## 3. What is the right `low_conf_unstable` confidence threshold?

**RESOLVED 2026-07-30 — the rule is retired.** The question was wrong:
the metric is structurally capped, and every candidate repair pushes
confidence *away* from the threshold rather than toward it. Kept here
(rather than deleted) because the underlying metric is still broken and
the next person to reach for `marketConfidence` needs to know that.

### The original question

The audit asked whether the 0.35 threshold should move, having observed
that live `marketConfidence` clusters around 0.49 so the rule fires for
~1 player in 1094. Reading the producer explains why, and it is not a
threshold problem.

`Dynasty Scraper.py::_market_confidence`:

```python
cv         = _coeff_var(norm_vals)
site_score = clamp(site_count / 8.0, 0.20, 1.00)          # 65% of the weight
cv_score   = clamp(1.0 - min(cv, 0.35)/0.35, 0.20, 1.00)  # 35%
conf       = clamp(site_score*0.65 + cv_score*0.35, 0.20, 1.00)
```

`site_count` is `len(wNorms)` — and in the live payload `_sites`
(written from the same value) **never exceeds 3**: p10 1, median 2,
p90 3, max 3. So `site_score` is confined to `{0.20, 0.25, 0.375}`, and
the metric's ceiling is:

```
0.375 * 0.65  +  1.00 * 0.35  =  0.59375
```

The observed maximum across 838 players is **0.594**. That is not a
coincidence — it is the structural ceiling. Observed range is
[0.341, 0.594] against a nominal [0.20, 1.00].

**So `marketConfidence` can never express high confidence.** The
dominant term divides a count that never exceeds 3 by 8. Tuning a
threshold against that scale is calibrating against a broken ruler: at
0.35 the rule catches almost nothing, and raising it toward 0.5 would
catch *most of the board* including well-covered players, because the
whole population sits in a narrow band just above it.

### Why `_sites` maxes at 3 (measured 2026-07-30)

The suspicion above — "3 sources is itself suspicious against a
21-source registry" — checks out, and the answer is that `_sites` is not
a registry-coverage count at all.

The composite loop (`Dynasty Scraper.py`, `for name, pdata in
players_json.items()`) accumulates `wNorms` by iterating the *scraper's
own* per-player dash keys. The scraper's `SITES` toggle map has exactly
**two entries enabled** — `KTC: True` and `IDPTradeCalc: True`; the
other ten are `False`, labelled *"disabled in scope reduction"*, with a
matching comment elsewhere reading *"No rank-based sites in the
two-source model"*. Those two scrapers emit three numeric dash keys
between them, confirmed on the live payload:

| dash key | players carrying it | in `_canonicalSiteValues` |
|---|---|---|
| `idpTradeCalc` | 898 | 814 |
| `ktc` | 590 | 464 |
| `ktcSfTep` | 464 | 464 |

So `len(wNorms) ∈ {1,2,3}` by construction. The other 18 registry
sources are fetched by `scripts/fetch_*.py` and merged **downstream** in
`src/api/data_contract.py`, which never recomputes `_sites` or
`_marketConfidence`. `_sites` therefore measures scraper-composite
coverage only, and always did — it was never the board's source count.
(The board's own count is `sourceCount`, from the 21-source blend.)

The `/ 8.0` divisor is a fossil of the pre-scope-reduction era when
~10 `SITES` were on.

### Why no divisor rescues the rule

`scripts/simulate_market_confidence_divisor.py` recomputes confidence
under any divisor without re-scraping, by inverting the live formula
(`cv_score = (conf - site_score*0.65) / 0.35` recovers the second input
exactly from the payload's `_marketConfidence` + `_sites`). Result:

| divisor | confidence range | players below 0.35 |
|---|---|---|
| 8.0 (live) | 0.341 – 0.594 | 1 |
| 5 | 0.356 – 1.000 | **0** |
| 4 | 0.393 – 1.000 | **0** |
| 3 | 0.567 – 1.000 | **0** |

Every correction moves the population *up*, so a rule that fires below
0.35 gets strictly deader, not healthier. There is no divisor at which
this rule becomes well-calibrated.

### The decision

`low_conf_unstable` is removed from both engines
(`src/api/terminal.py::_evaluate_signal` and
`frontend/lib/signal-engine.js`), from the shared parity fixture's rule
registry, and from the alert path. MONITOR is in
`signal_alerts.ACTIONABLE_SIGNALS`, so the rule gated email on a gauge
whose range is an artifact of how many scrapers happen to be enabled —
that is the specific thing worth not shipping.

The confidence *number* survives as a diagnostic on both signal
contexts, so a future rule built on a repaired metric has the plumbing
in place.

Pinned by `tests/api/test_market_confidence_wiring.py`:
`TestConfidenceReachesTheContext` keeps the 2026-07-29 plumbing fixes
honest, and `TestTheRuleIsRetired` asserts that **no** surviving rule's
verdict changes with confidence — so a reinstatement under a different
tag fails a test rather than landing quietly.

### Still open (deliberately not done here)

**The divisor itself is still 8.0.** Correcting it is a separate
decision with a separate risk profile, and it is *not* a board change:
`market_conf` only ever multiplies the scraper's `composite`
(`elite_boost`, `elite_cap`, the single-source discount,
`idp_conf_factor`), never `canonical_site_values`, so
`rankDerivedValue` is untouched by it. What it does move is
`_finalAdjusted`. Measured multiplier shifts on the composite, median
across the population:

| divisor | single-source discount | `idp_conf_factor` | `elite_cap` (offense) |
|---|---|---|---|
| 5 | ×1.056 | ×1.070 | ×1.011 |
| 4 | ×1.093 | ×1.117 | ×1.019 |
| 3 | ×1.155 | ×1.196 | ×1.031 |

The blast radius is narrower than it looks, but it is not zero — be
precise about which `finalAdjusted` a consumer reads:

* `values.finalAdjusted` on a `playersArray` row is **overwritten with
  `rankDerivedValue`** whenever the board priced the row
  (`data_contract.py`, "Stamp rankDerivedValue into the values bundle").
  So `public_activity_valuation.py`, `league_intel/values.py` and
  `/draft`'s fallback chain all see the board value, not the composite.
* The raw legacy key `_finalAdjusted` still carries the scraper
  composite, and `src/trade/finder.py` is the one live reader
  (lines 451 and 946) — both on its **degraded/legacy** path, after
  `finder.py` was moved onto the canonical board on 2026-07-27.

With `low_conf_unstable` gone there is no signal-path pressure to change
the divisor either. Honest status: a fossil constant whose only live
reach is the finder's fallback path, worth fixing when the scraper is
next touched, not worth a speculative re-scrape now.

---

## 4. What width should the Monte Carlo trade band be?

**Status: measured. Recommendation — leave the width alone for now,
but stop calling it a consensus. Added 2026-08-05.**

### The question, as it actually stands

`src/trade/monte_carlo.py` draws each asset's value from a band
`(p10, p50, p90)` and reports the fraction of draws where side A wins.
The output is labelled `consensus_based_win_rate` and carries a
disclaimer — a contract field the UI is *required* to render — saying
the number comes from "the sources' consensus distribution".

That description does not match what runs. Measured on the pinned
2026-07-30 contract:

* **0 of 1093** rows carry a stamped `valueBand`. Phase 4 confidence
  intervals were never wired to the live contract.
* `frontend/components/ui/MonteCarloButton.jsx` therefore synthesizes
  a flat **±15%** band and posts it under the same `valueBand` key a
  real interval would use.

So 100% of live simulations run on a constant, and the backend had no
way to tell — the presence of the key was the only signal, and both
branches set it.

### What the measured disagreement actually looks like

Against `marketDispersionCV` on the 683 priced rows that carry it,
converting a CV to an implied p10..p90 half-width under normality
(`1.2816 × CV`):

| quantile | `marketDispersionCV` | implied band | flat ±15% is |
|---|---|---|---|
| p10 | 0.0000 | ±0.00% | ∞× too wide |
| p25 | 0.0000 | ±0.00% | ∞× too wide |
| median | 0.0243 | ±3.12% | 4.8× too wide |
| p75 | 0.0542 | ±6.95% | 2.2× too wide |
| p90 | 0.0837 | ±10.73% | 1.4× too wide |
| max | 0.2631 | ±33.72% | **0.4× — too NARROW** |

**24 of 683** rows have measured disagreement exceeding ±15%.

### Why the width is not simply "wrong"

Two arguments point in opposite directions and neither is settled by
this repository's data:

* **Too wide.** At the median the band is nearly 5× the disagreement
  the sources actually show. A simulator that inflates uncertainty
  reports win probabilities closer to 50% than they should be, which
  makes lopsided trades look closer than they are.
* **Too narrow, and for the right reason.** Source disagreement is a
  *lower bound* on value uncertainty. It measures how much the boards
  differ today, not how wrong they might all be together. Dropping to
  ±3% would make the simulator absurdly confident — a 2-point edge
  would read as a near-certain win.

There is no backtest in this repository that scores band width against
realized outcomes, so picking a number here would be substituting one
unjustified constant for another.

### What IS wrong, and is fixed

Not the width — the **flatness**, and the **label**.

A flat band cannot express that the board knows some players better
than others. At least a quarter of priced rows have *zero* measured
disagreement and get the same ±15% as the row with 26%. That is
information the contract already carries and the simulator discards.

And the label asserted a measurement that never happened. Fixed on
2026-08-05:

* `TradePlayer.band_source` carries provenance
  (`stamped_value_band` / `synthetic_flat_15pct` / `unknown`), declared
  by the caller rather than inferred from which key was present.
* An undeclared band is `unknown`, **not** assumed measured — the
  flattering default is the one that made this unfalsifiable.
* `simulate_trade` reports the tally as `bandSources`, and the
  disclaimer appends "N of M assets used a synthesized ±15% band
  rather than measured source disagreement, so the spread is an
  assumption, not a measurement" — and only when that is true.

Pinned by `tests/trade/test_monte_carlo_band_integrity.py`, including
the asymmetry (a fully-measured run gets a clean disclaimer), so the
qualification cannot be hardcoded into the string.

### What would settle the width

Stamping the real Phase 4 interval — `src/canonical/confidence_intervals.py`
exists and nothing calls it on the live contract — and then scoring
band-implied win probabilities against realized trade outcomes, the
same shape as `scripts/backtest_adjusted_board.py`. Until one of those
exists, the honest state is a documented assumption that says so on
every response.

### Also fixed alongside (not a modeling question)

The band endpoints were clamped to `[0, 9999]`. 9999 is where the
*board's* normalization tops out; it is not a bound on a quantile.
Because the draw is otherwise exactly unbiased, that clamp was the
simulator's only source of bias, and it landed on the top 12 assets
only — Josh Allen's simulated mean was marked down 520 points (−5.2%),
Brock Bowers 510, Bijan Robinson 404. The ceiling is removed from the
endpoints (the 0 floor stays); the p50 cap in the consolidation shift
stays, since that one is a value on the board scale and is already
reported honestly via `effectiveValue`.
