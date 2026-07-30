# Open modeling decisions — resolved to evidence

**Date:** 2026-07-29
**Context:** the 2026-07-29 repository audit
(`docs/audits/complete-codebase-audit-2026-07-29.md`) left three
questions as "requires a product decision". Each was under-specified:
they were stated as choices without the measurements needed to make
them. This document closes that gap. Two are now decided on evidence;
one is narrowed to a single concrete change that still needs a call.

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

**Still open, and genuinely a product call:** whether to retire the
rank-form family in favour of the percentile masters. Measured in
`docs/legacy-rank-curve-backtest.md` — the candidates have inverted
error profiles (`percentile_global` is far better past rank 120 and
~2× worse in the top 24), and switching moves user-visible history
values. Unchanged by this document.

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
