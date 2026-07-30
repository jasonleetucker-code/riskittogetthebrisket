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

### The wiring — LANDED 2026-07-26

The five-step plan below was the original scope. It landed as a single
driver rather than five CLI calls chained in YAML; the differences are
recorded because the plan was written before the code existed.

Original plan:

1. Refit emits challenger params instead of writing them.
2. `model_registry.py evaluate --champion --record`
3. `model_registry.py register --params challenger.json`
4. `model_registry.py validate <n>` — exit 0 promotes, 1 rejects.
5. Commit **only** `config/model_registry/*.json`.

What actually shipped, and why it differs:

* **Steps 1–4 collapsed into `scripts/auto_refit_hill_curves.py`.**
  Chaining four CLI calls through workflow steps means passing a
  params file and a version number between shell steps, and every hand-
  off is a place for the gate to be skipped by an `if:` condition. One
  driver with one exit-code contract has no such seam.
* **Exit codes are richer than "0 promotes, 1 rejects".** The plan's
  binary conflates two very different outcomes. Shipped contract:
  `0` champion stands (no drift, or the challenger missed the margin —
  the ordinary weekly result), `1` promotable, `2` error, `3`
  regression alarm.
* **Added: the champion must match what is deployed.** The driver
  refuses to run if the registry's champion params differ from the
  constants in `player_valuation.py`. Not in the plan, and necessary —
  comparing a challenger against a champion that is not live yields a
  correct-looking verdict about the wrong incumbent.
* **Added: the workflow self-tests the gate before trusting it**
  (`pytest tests/model_registry/`, ~2s).
* **Added: an issue is opened when a human must act** (promotable, or
  alarm).
* **Removed: the full `pytest -m "not livedata"` step.** It existed to
  check code the refit had just rewritten. The refit rewrites nothing
  now, so there is nothing for a full sweep to regress — and running
  it weekly for 15 minutes to check an unchanged tree is the kind of
  ritual that makes a real signal easy to ignore.

**Reason 3 was NOT fixed by un-marking the guard.**
`test_ktc_reconciliation.py` keeps its `livedata` marking; that marking
exists because a yahooBoone row-count dip once stalled every PR, and it
is still correct. The gate moved out of pytest entirely instead. A gate
invoked through pytest can be deselected by a filter; a gate invoked as
a function call cannot. `TestTheLivedataMarkingIsPreserved` fails if
anyone "fixes" it the other way.

The guard itself is left in place and is no longer rewritten, so its
pins are now a real tripwire: if the constants change and the pins are
not re-baselined by hand, it fails — which is the behaviour its
docstring always claimed.

### What happens on rejection

Stated explicitly, because "nothing reported red because nothing ran"
is the failure class this whole change exists to remove.

| Outcome | Constants | Registry | Workflow | Human notified |
|---|---|---|---|---|
| No drift | untouched | unchanged | green | no |
| Rejected within margin | untouched | challenger recorded as `rejected` | green | no |
| **Promotable** | untouched | challenger recorded | green | **issue opened** |
| **Regression alarm** | untouched | challenger recorded as `rejected` | **red** | **issue opened** |
| Error | untouched | unchanged | **red** | workflow failure email |

Two deliberate choices in that table:

* **Routine rejection does not page anyone.** It is the expected weekly
  outcome; alerting on it trains people to ignore the alert, which is
  how a deliberate decision became an invisible hole the first time.
  It is still *recorded* — every run leaves a dated registry entry.
* **A promotable challenger DOES page.** Otherwise improvements never
  land and the system quietly becomes a no-op — the same "nothing
  happened and nobody noticed" shape, just with the sign flipped.

The registry is the audit trail, and its absence is itself the signal:
a week with no new entry means the workflow did not run.

**Status:** accepted 2026-07-26; registry in `src/model_registry/`,
wiring landed in `scripts/auto_refit_hill_curves.py` +
`.github/workflows/refit-hill-curves.yml`.

---

## ADR-009: the rookie auction has no per-team slot limit, and the optimizer treats `k` as a free variable

**Original spec idea:** strip the slot UI from `/draft`.

**Finding:** the slot model was not a display concern. `draft-logic.js`
carried `DEFAULT_INITIAL_SLOTS = 6` and used it in three load-bearing
places: `effectiveBudgetFor` reserved $1 per unfilled slot and returned
**0** once a team's picks were "used"; `phaseMultiplier` scaled every
MaxBid by up to 1.5x as slots drained; and `mdv` divided a budget by the
number of openings. A team missing from the draft-capital feed got 0
slots and therefore vanished from `topCompetitorMax` entirely — modelled
as unable to bid while holding real money.

None of it describes this league. Rookie picks are *valued* into
`teamTotals[].auctionDollars`; the auction itself places no cap on how
many rookies a team may buy. The doc comment claiming the constant was
only a pre-fetch placeholder was also false — `mergeDraftCapitalTeams`
applied `Math.min(feedSlots, 6)`, so a team owning nine picks was
silently clamped.

**Decision:** remove the slot dimension outright. Effective budget is
remaining dollars; `topCompetitorMax` is the richest rival's actual
remaining. `phaseMultiplier` is **deleted, not replaced** — its
legitimate job was "I am rich, bid up", and `budgetAdvantage` already
does that, more meaningfully now that budgets are no longer slot-shrunk.
Removing a term beats inventing one. `draftProgress` is denominated by
the rookie pool, and the "Spend up" chip keys on board progress plus
budget advantage instead of slot pressure and $-per-slot.

This changes MaxBid numbers and breaks parity with the owner's
`Inflation` spreadsheet. That was accepted explicitly: the spreadsheet
encodes the same wrong assumption.

Roster **capacity** (58 in `dynasty_main`) is a real constraint and is
kept — but it lives in the optimizer, where it belongs, as
`openRosterSpots`. It caps how many rookies you can hold without cutting,
not how many you may draft.

**Status:** accepted 2026-07-30; pinned by the "no per-team slot limit"
block in `frontend/__tests__/draft-logic.test.js`.

---

## ADR-010: Perfect Draft measures both sides over replacement, and solves the whole budget at once

**Original spec idea:** `Net Value Added = Rookie Value − Displaced Player
Value`, maximized subject to a budget.

**Finding:** taken literally that objective is degenerate. Rookie board
values and the $1200 dollar ladder both come from the same convex Hill
curve (`server.py::_rookie_dollars_from_values`), so value-per-dollar
rises roughly **30x** from the top of the rookie ladder to the 72nd —
#1 Jeremiyah Love at 7587/$135 versus #72 at 1721/$1. A raw
`max Σ value s.t. Σ price ≤ B` therefore does not analyse a market; it
reads the shape of the price curve back out and recommends buying thirty
$1 dart throws.

A second measured problem: the roster tail is not a value. 19 players sit
at exactly 497 and 19 more at exactly 375, nearly all single-source with
no position — `src/league_intel/replacement.py` calls it "the noisiest
number in the league (deep dart throws, and any identity-join miss lands
there)". Costing a cut at that number turns an identity-join miss on a
real asset into a cheap-cut recommendation.

**Decision:** measure both sides over replacement, using one primitive.

```
waiverValue(pos)  = best unrostered player at that position
surplus(rookie)   = max(0, boardValue − waiverValue(pos))
ECC(player)       = max(0, base − waiverValue(pos)) × (0.85 + 0.30·waiverScarcity)
   base           = boardValue, or waiverValue when unranked ("assumedWaiver")
NetValue(S)       = Σ surplus − D(|S|)
```

An empty roster spot is worth waiver level, not zero — that symmetry is
what makes the objective mean something. The scarcity multiplier is taken
verbatim from `src/roster_intel/targets.py::_scarcity_multiplier`, and
uses `waiverScarcity` alone for the reason that file gives. Only the
three `*Scarcity` fields are dimensionless; `replacementGap`,
`eliteSeparation` and `starterSeparation` are in `rosValue` units and are
never mixed with a `rankDerivedValue` core.

Because the cut ladder is cheapest-first and independent of *which*
rookies are bought, total displacement `D(k)` is a function of `k` alone.
That decomposes the problem into one cardinality-constrained 0/1
knapsack, solved exactly — and it is a theorem, not an approximation:
legal cut-sets are the independent sets of the dual of a transversal
matroid, where greedy is optimal and successive minimum-weight sets nest.
Droppability is therefore validated by re-running the real assignment
solver (`src/ros/lineup.py::solve_optimal_assignment`) after each rung, not
by a per-position count — with FLEX and SUPER_FLEX slots, whether a player
is droppable depends on who else is being dropped.

One solve yields every cardinality, so the star-focused and depth-focused
alternatives are the ends of the same frontier rather than a second
algorithm, and nothing is manufactured when the pool supports only one
shape.

**Max bid is an indifference price**, not a converted value:
`planMaxBid(i) = max{ q : bestNetWith(i at q) ≥ bestNetWithout(i) }`. The
tempting `price + (netWith − netWithout)` adds a value quantity to a
dollar quantity and invents an exchange rate this codebase refuses to
invent anywhere else. It is named `planMaxBid` because the board already
shows five max-bid concepts and a sixth that silently disagreed would be
a UI failure.

**Confidence** is the share of bootstrap scenarios in which the
recommended plan still wins, over the frontier *plus* the per-rookie
pivot plans. The pivots are load-bearing: the frontier keeps one winner
per cardinality, so two genuinely tied plans of the *same size* are
invisible without them, and the UI would name one of two coin-flips.

**Status:** accepted 2026-07-30. Engine in `src/draft/` +
`frontend/lib/perfect-draft.js`; the matroid claim is checked against
brute force in `tests/draft/test_displacement.py`, and the
greedy-loses-to-exact instance is pinned in
`frontend/__tests__/perfect-draft.test.js`.

---

## ADR-011: the Perfect Draft solve runs on the client, the roster context on the server

**Original spec idea:** a backend engine with a POST endpoint, matching
the BDVM family.

**Finding:** the `/draft` board is a client-side application. Every input
that moves during a draft — team budgets, recorded picks, live prices,
the inflation model — lives in `localStorage` and never reaches the
server. There is no server-side store of budgets or picks at all. A
backend solve would mean POSTing the entire draft workspace on every
recorded pick, mid-auction, to run a knapsack that takes single-digit
milliseconds.

**Decision:** split on what actually changes.

*Server, once per draft, cached* — `GET /api/draft/roster-context`:
rosters joined to canonical `rankDerivedValue`, per-position waiver
levels, and the feasibility-checked cut ladder. All static for the whole
draft, all requiring the ~4 MB contract, the lineup solver and league
scarcity, none of which belong in the browser.

*Client* — the knapsack, against live workspace state.

This does not breach the "no frontend ranking engine, period" rule: the
optimizer recomputes no player value and consumes backend stamps exactly
as `draft-logic.js` already consumes `rookieKtcValue`. `rookieBoardValue`
was added to `/api/draft-capital` for the same reason — the dollar ladder
is not invertible, so a client holding only dollars cannot recover board
value. It is redacted for public callers alongside the other rookie
fields.

The cache key carries **team identity**; every number in the payload is
roster-specific, so a key without it would serve one manager's cut ladder
to another. An unresolvable team is a 400, never a silent fallback to
whichever team sorted first.

Scoping: the league-match gate is what confines the feature to the league
whose rosters are loaded. A league served only by the Sleeper-derived
draft-capital fallback has no genuine rookie pool, fails that gate, and
the panel vanishes rather than optimizing against the hardcoded
placeholder rookie list. That is data-driven rather than a hardcoded
league key, so it starts working on its own if the fallback is ever
fixed.

**Status:** accepted 2026-07-30. Flag `perfect_draft` (LIVE, default on);
rollback `RISKIT_FEATURE_PERFECT_DRAFT=0` **and restart** — flag reads are
cached per process.
