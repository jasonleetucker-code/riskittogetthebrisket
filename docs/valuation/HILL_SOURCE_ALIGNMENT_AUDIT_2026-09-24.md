# Hill curve ↔ live source-authority alignment: audit (read-only phase)

**Owner request, 2026-09-24.** Audit whether the Hill refit learns value
spacing from the right evidence, with authority consistent with the live
model, without fabricating values from rank-only sources, without
double-counting correlated evidence, and with a genuinely out-of-sample
holdout. Recorded in `docs/OWNER_REQUESTED_TODO.md` and `docs/EXECUTION_PLAN.md`
§0 (2026-09-24).

**Status: findings only. No Hill code, constant, weight or holdout has been
changed.** The owner sequenced the repair after PR #1427 (family-capped voting),
because Hill must align with the source-family semantics that ship, not a
branch model. Once #1427 is on `main`, the source table (§3) is re-derived from
production truth before any repair is designed.

## 1. What the Hill curve does (verified from code)

* **Rankings say WHO the market prefers.** Native-value boards say **HOW FAR
  APART** the market prices positions. The Hill curve learns that spacing, and
  rank-only sources are converted through it.
* Live path: a source's rank → percentile against a fixed 500-row reference
  (`_PERCENTILE_REFERENCE_N`) → percentile-form Hill master
  (`src/canonical/player_valuation.py`) → a value on 1–9999 → source weighting
  → blend → `rankDerivedValue`.
* Value-signal sources (`_VALUE_BASED_SOURCES`: KTC Crowd, KTC Trades, IDPTC)
  vote `raw / site_max × 9999` directly and do not pass through the curve.
* Scopes: OFFENSE, GLOBAL (cross-market), IDP. ROOKIE is refit-only and not
  routed (rookie sources ladder-translate first).
* Constants move only through the model registry / Hill Autopilot
  (champion ≠ challenger, holdout, board-impact gate, human or gated promotion).
  The refit never writes production.

**A rank-only source cannot teach spacing.** Ranks 1, 2, 3 say nothing about
whether rank 2 is worth 9500 or 7000. Every valid ranking source influences the
rankings; that does NOT make it a Hill trainer. Nothing here proposes
fabricating values for rank-only sources.

## 2. Findings

| # | finding | kind | evidence |
|---|---|---|---|
| **H1** | OFFENSE trains on `ktc.csv`, the non-TEP **base** KTC Crowd board, which **does not vote live**. Live KTC is Crowd TE++ + Trades TE++. | misaligned | `scripts/fit_hill_curve_percentile.py::OFFENSE_SOURCES`; inventory reason for `ktc`: "a calibration state, not a vote" |
| **H2** | **KTC Trades**, a live value voter, is neither a trainer nor a holdout. | missing | same dict; `src/model_registry/holdout.py` |
| **H3** | Five sources that vote as **RANKS** (Dynasty Daddy, Dynasty Nerds, Yahoo/Boone, Fitzmaurice, Draft Sharks) shape the curve through their **native values**. That is a second, indirect channel of influence over every rank source. It is not necessarily wrong, but it is unmeasured. | hidden influence (to measure) | `OFFENSE_SOURCES` vs `_RANKING_SOURCES` signal types |
| **H4** | The scope master is the **unweighted mean** of per-source curves. There is no freshness, health, coverage or family adjustment, so a 34-day-stale board trains at full authority while production gives it ~0.1. | misaligned | `_fit_scope_master` docstring: "V*(p) = mean(V_j(p))" |
| **H5** | **Fantasy Navigator (KTC-derived) is an OFFENSE holdout while KTC trains.** | formal independence finding | `holdout.py::OFFENSE_HOLDOUT_SOURCES`; FN in the `ktcCrowd` family |
| **H6** | **Three of four OFFENSE holdouts share measured lineage or correlation with training evidence**: Fantasy Navigator (KTC-derived), PFK (residual r = +0.45 vs KTC), FantasyCalc (residual r = **+0.677** vs Dynasty Daddy, a trainer). Only OTC (trade-derived, r = +0.33 vs FantasyCalc) is plausibly independent. The current holdout cannot be described as fully independent evidence. | formal independence finding | `docs/audits/decision-intelligence-audit-2026-08-04.registry.json` (`duplicatesOf` residuals) |
| **H7** | **Ranking lineage ≠ curve lineage (measured, §4).** PFK's holdout RMSE is flattered **1.64×** by KTC in training. Fantasy Navigator is NOT flattered: its published value curve differs in shape from KTC's even though its ranks derive from KTC. Voting independence and calibration independence are different questions. | methodology | §4 |
| **H8** | **Two hand-maintained copies of the training list**: `fit_hill_curve_percentile.py::OFFENSE_SOURCES` and `holdout.py::OFFENSE_TRAINING_SOURCES`. No test asserts they agree, and nothing ties either to the live source registry. Source-role changes (KTC split, family caps, DLF Values) can silently leave Hill behind. | second registry | both files; no parity test found |
| **H9** | A refit pins only the **board snapshot** (+sha256). It does not pin dataset-state files, source health, family state or an `asOf`, so authority-weighted training could not be replayed deterministically. | provenance gap | `.github/workflows/refit-hill-curves.yml` "Pin fit snapshot" |

## 3. Source ancestry (training and holdout, OFFENSE)

| board | Hill role today | provider / data ancestry | live role | measured relationship |
|---|---|---|---|---|
| `ktc.csv` (KTC Crowd, base) | TRAIN | KeepTradeCut crowd (Keep/Trade/Cut votes) | non-voting (calibration state) | parent of FN; PFK residual +0.45 |
| Dynasty Daddy | TRAIN | crowd / trade market | rank voter | FantasyCalc residual **+0.677** |
| Dynasty Nerds | TRAIN | expert rankings | rank voter | — |
| Yahoo / Boone | TRAIN | single expert | rank voter | — |
| Fitzmaurice | TRAIN | single expert, also inside FantasyPros | rank voter (fantasyPros family) | nested in FantasyPros consensus |
| Draft Sharks | TRAIN | model / projection-based | rank voter | — |
| FantasyCalc | HOLDOUT | crowd trade market | rank voter | Dynasty Daddy +0.677 |
| OTC | HOLDOUT | trade-derived (354k+ trades) | rank voter | FantasyCalc +0.33 |
| PFK | HOLDOUT | own board, partly KTC-shaped | rank voter | KTC +0.45 |
| Fantasy Navigator | HOLDOUT | KTC-derived (every row carries a KTC id) | rank voter (ktcCrowd family) | KTC lineage |
| KTC Trades TE++ | none | KeepTradeCut trade-based values | **value voter** | ktcTrades family |
| KTC Crowd TE++ | none | KeepTradeCut crowd TE++ | **value voter** | ktcCrowd family |

The production columns (effective authority, freshness, health, coverage,
family adjustment) are re-derived from `main` once #1427 lands (owner
requirement 3).

## 4. Fixed holdout vs leave-one-independent-family-out (measured)

Read-only experiment on committed CSVs using the fitter's own primitives
(`_load_values`, `_percentile_pairs`, `_fit`, `_fit_scope_master`) and
`holdout._rmse`, top 400 per board, same as the fit.

* **A (today):** train on the six fixed trainers, score the four holdouts.
* **B (LOIFO):** each board is scored by a master fitted on every board outside
  its lineage family. Families come from the recorded residuals:
  **ktcLineage** = {KTC, Fantasy Navigator, PFK}, **crowdMarkets** =
  {Dynasty Daddy, FantasyCalc}, every other board alone.

| board | A (fixed) | B (LOIFO) | B/A |
|---|---|---|---|
| FantasyCalc | 649.1 | 591.1 | 0.91 |
| OTC | 631.4 | 530.4 | 0.84 |
| **PFK** | **452.8** | **743.2** | **1.64** |
| Fantasy Navigator | 857.1 | 581.0 | 0.68 |
| KTC | (trainer) | 1461.4 | — |
| Fitzmaurice | (trainer) | 1326.3 | — |
| Dynasty Nerds | (trainer) | 1060.9 | — |
| Draft Sharks | (trainer) | 823.6 | — |
| Dynasty Daddy | (trainer) | 459.1 | — |
| Yahoo / Boone | (trainer) | 426.7 | — |

Median held-out RMSE: A 640.3 (4 boards), B 667.1 (10 boards).

Reading it honestly:

1. **Leakage is real but board-specific.** PFK's best-in-class fixed-holdout
   score depends on KTC being in training (×1.64).
2. **Curve lineage must be measured, not inferred from provider lineage (H7).**
   Fantasy Navigator's value curve differs from KTC's shape, so KTC in training
   does not flatter it.
3. **LOIFO evaluates every board out-of-sample.** The fixed split can never say
   that KTC's own base board is the worst fit to the consensus shape.
4. **Not yet a basis to switch.** B's training sets are larger and differ in
   composition from A's (7–9 boards vs 6), which confounds the comparison. Before
   adopting LOIFO the comparison must also cover multi-day stability and whether
   it changes any historical champion/challenger decision. Families should be
   defined from measured curve-shape correlation.

## 4b. H3 measured: each trainer's marginal influence (leave-one-source-out)

Read-only, same primitives, the committed CSVs at `97c1f84e8`. The scope master
refit from all six trainers is c = 0.069, s = 1.11 (V at p = .10 is 3984). Each
row refits the master without one trainer and reports the shift in V(p):

| trainer removed | live role | p=.05 | p=.10 | p=.30 | p=.50 | p=.90 |
|---|---|---|---|---|---|---|
| KTC (base) | non-voting | −3.4% | −8.2% | −17.5% | −21.6% | −25.8% |
| Dynasty Nerds | rank voter | +0.9% | +4.3% | +12.9% | +17.7% | +23.4% |
| Fitzmaurice | rank voter | −5.8% | −7.7% | −9.1% | −9.1% | −8.7% |
| Draft Sharks | rank voter | +8.2% | +8.9% | +4.4% | +0.8% | −3.9% |
| Dynasty Daddy | rank voter | +1.0% | +2.3% | +5.2% | +6.6% | +8.1% |
| Yahoo / Boone | rank voter | −0.9% | −0.5% | +1.1% | +2.2% | +3.4% |

A master fitted on the one value-voting-lineage trainer (KTC base) alone sits
**+32% at p = .10 and +110% at p = .50** above the six-trainer master. The
indirect channel H3 describes is therefore **not small**. The five rank-voting
trainers' native values set most of the curve's mid and tail shape. A single
expert board (Dynasty Nerds) moves the tail by up to 23%. That is
not a verdict that they should stop training: whether a rank voter's published
native values are valid spacing evidence is repair-contract item 2
(eligibility), decided per source on evidence, not by voting role. It does mean
the choice changes the curve materially, so it must be explicit.

Context: the Autopilot's pending OFFENSE challenger (c = 0.066, s = 1.085;
gates `forward_persistence` and `parameter_stability` still false on
2026-09-24) sits close to this refit, and the live champion is c = 0.110,
s = 1.110. Promotion stays with the Autopilot. This audit neither promotes
nor blocks it.

## 5. Repair contract (sequenced after #1427; owner requirements, 2026-09-24)

1. **One canonical source-metadata model** expresses `model_input`,
   `signal_type`, `family`, `hill_training_eligible`, `hill_validation_eligible`
   and `benchmark_only` per scope. The fitter and holdout read it, retiring H8's
   two dictionaries. A parity test fails on any role drift.
2. **Eligibility is explicit:** verified DYNASTY, real native values, known
   normalization, sufficient coverage, not benchmark-only (KTC Market never
   trains, and has a regression guard), not an exact mirror or derived
   duplicate, approved for calibration. A CSV with a value column is not
   eligibility.
3. **Authority follows production** where mathematically meaningful:
   base × freshness × health × coverage × family adjustment, from the canonical
   owners (no second weighting engine). Weighted per-source loss and a weighted
   scope master are evaluated. Stale or quarantined sources cannot keep full
   calibration authority; a missing source contributes nothing, not zero.
4. **Deterministic, snapshot-relative freshness (H9):** a refit pins its source
   files, dataset-state files, source-health and family state, and `asOf`.
   Same evidence + same state + same `asOf` = same challenger. A replayed fit
   never uses today's freshness on yesterday's snapshot.
5. **Holdout independence (H5–H7):** a holdout must not be training evidence
   under another site's name, or a composite built from it, unless that is
   modelled. LOIFO is compared further (§4.4) before any adoption.
6. **DLF Trade Analyzer Values enter Hill only after** they pass their own
   measurement gate AND become an approved production value signal. Voting
   eligibility and Hill-training eligibility are separate decisions.
7. **Rank-only sources are never forced into training.** Champion/challenger,
   holdout, board-impact gates and rollback are untouched. No constant is
   hand-edited, and the curve is never fitted to our own board.

H3's marginal influence is measured in §4b. Measured next, once #1427 is on
`main`: re-derive §3's production columns, then a current-vs-aligned
curve comparison on the same pinned evidence, with c / s and values at
p = 0, .01, .02, .05, .10, .20, .30, .50, .70, .90 for each routed scope.
