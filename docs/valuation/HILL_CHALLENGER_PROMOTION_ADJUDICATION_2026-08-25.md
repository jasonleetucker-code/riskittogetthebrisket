# Hill scope masters — challenger promotion adjudication, 2026-08-25

**Verdict: REFUSED. Champion stays v2. No constant in
`src/canonical/player_valuation.py` was changed by this work.**

This closes the standing owner-decision item "promote the Hill challenger"
with a measurement and a dated refusal, rather than leaving it open as an
unanswered question. It also closes a live governance defect found while
measuring: the gate that should have refused this promotion existed, was
tested, and **had no caller**.

Everything below was measured on this tree. Nothing here is inference.

---

## 1. What was asked

`config/model_registry/hill_scope_masters.json` carries champion **v2** and
two open challengers, **v4** and **v5**. Every version's held-out criterion
(lower is better) beats the champion's:

| version | status | criterion | vs champion |
|---|---|---|---|
| 1 | retired | 819.7 | — |
| **2** | **champion** | **787.8** | — |
| 3 | rejected | 775.0 | −1.6% |
| 4 | challenger | 758.2 | −3.8% |
| 5 | challenger | 683.1 | **−13.3%** |

On that number alone v5 is a clear promotion. The question is whether that
number licenses the promotion, and the answer is no — twice over, for two
independent reasons.

## 2. Reason one — the criterion scores one scope; a promotion moves four

This is not a new observation; the repo states it in three places and then
never enforced it.

- `src/model_registry/hill_masters.py`: `VALIDATED_PARAMS` is literally
  `("HILL_PERCENTILE_C", "HILL_PERCENTILE_S")`, commented *"only these two
  of the eight have a genuine out-of-sample check today"*.
- `src/model_registry/holdout.py`: the evaluator reads offense boards only,
  and says explicitly that it measures generalization across markets, **not**
  accuracy against reality — every holdout source is another consensus
  market correlated with the training sources by construction.
- `src/model_registry/scope_validation.py`, first line: *"A scope must not
  ride another scope's validation into production."*

Running that module's own classifier over the real registry:

| challenger | GLOBAL | OFFENSE | IDP | ROOKIE |
|---|---|---|---|---|
| v3 | UNCHANGED | VALIDATED_EXTERNAL_HOLDOUT | **UNVALIDATED_NO_HOLDOUT** | NOT_ROUTED |
| v4 | **UNVALIDATED_NO_HOLDOUT** | VALIDATED_EXTERNAL_HOLDOUT | **UNVALIDATED_NO_HOLDOUT** | NOT_ROUTED |
| v5 | **UNVALIDATED_NO_HOLDOUT** | VALIDATED_EXTERNAL_HOLDOUT | **UNVALIDATED_NO_HOLDOUT** | NOT_ROUTED |

v5's unscored moves are large — `IDP_HILL_PERCENTILE_C` 0.083 → 0.038
(−54%), `IDP_HILL_PERCENTILE_S` 1.110 → 0.870 (−22%),
`HILL_GLOBAL_PERCENTILE_C` 0.112 → 0.089 (−21%). The 13.3% criterion
improvement is evidence about **two** of the six numbers that moved.

## 3. Reason two — measured blast radius

`scripts/measure_hill_version_board.py` (added by this work, evaluation
only) prices the real board through the real `build_api_data_contract` with
one version's params substituted, and emits a `golden_board.py` capture.
Both captures in each pair share identical `inputSha256`, `sourceCsvSha256`
and `freshnessSha256`, so `board_diff.py` is reporting curve effect and
nothing else. Full output: `evidence/HILL_V2_TO_V5_BOARD_DIFF_2026-08-25.txt`
and `evidence/HILL_V2_TO_V4_BOARD_DIFF_2026-08-25.txt`.

**v2 → v5**, over 1,111 rows / 849 priced:

| quantity | measured |
|---|---|
| values moved | **741** (87% of priced rows) |
| median / p90 / max absolute move | 15.4% / 25.7% / **32.1%** |
| ranks changed | **758** |
| newly unpriced | **36** (all offense) |
| newly priced | 36 (34 IDP, 2 offense) |
| `canonicalTierId` flips | 738 |
| rows voting differently | 264 |

By asset class (median move): offense **−22.99%**, IDP **−9.42%**, picks
0.00% on 72 of 144 (the rest down to −22.32%). The top-25 membership is
**not** preserved.

The finding that decides it is the confidence movement. The B11 agreement
axis (`src/api/confidence.py`) measures how many provider families price
within 15% of the published `rankDerivedValue` — i.e. how well the board
agrees with its own evidence. Under v5:

- **300** `confidenceBucket` flips, **205 worse against 95 better**
  (offense 143 worse / 50 better; IDP 62 worse / 45 better);
- **367** `confidenceLabel` flips, the representative one being
  `A.J. Brown: High — every axis high → Medium — limited by agreement`.

So the challenger that describes six external boards better than the
champion simultaneously agrees **worse** with the eleven source families
actually voting on our board, on a net 110 rows. Those two statements are
not contradictory — they are what happens when a criterion is fitted on one
scope and applied to four — but together they are not a promotion case.

For contrast, **v2 → v4** moves 771 values at p50 **0.8%** / max 4.1%,
3 newly unpriced, no comparable confidence movement. v4 is a small
recalibration; v5 is a different board.

## 4. What was NOT concluded

- **v5 is not rejected as a model.** `reject()` records that a challenger
  lost; nothing here establishes that. The honest state is "unpromotable on
  current evidence", which is `challenger` — its existing status. It is left
  untouched.
- **No claim that v2 is correct.** `holdout.py` is explicit that no
  instrument here can establish that, and V1-22 stays `IN PROGRESS`
  accordingly.
- **No tolerance, gate or validator was weakened**, and no constant,
  source weight, bridge rule, or clamp was touched. `git diff` over
  `src/canonical/`, `config/weights/` and `config/model_registry/` is empty.

## 5. The governance defect this found, and the repair

`ModelRegistry.promote()` did not consult `scope_validation` at all.
`assert_promotable` and `classify_scopes` had **zero callers** outside
`tests/model_registry/test_governance_hardening.py`; the `scopeValidation`
field existed on `ModelVersion`, was serialized, and was `{}` on all five
recorded versions; and `scripts/model_registry.py` carried a comment saying
so — *"`cmd_promote` has NO holdout gate, so this verdict is the only thing
between a human and `promote` + `apply`"*.

Measured consequence, before the repair: `promote(3)`, `promote(4)` and
`promote(5)` all **succeeded**. The refusals in §2 were available and were
not asked for.

Repaired here:

- `ModelRegistry.promote()` runs `assert_promotable` and records the
  resulting states into the promoted version's `scopeValidation`.
- Evidence is **derived, never asserted by the caller**: OFFENSE counts as
  externally validated exactly when the challenger carries a holdout record,
  because `evaluate_offense_master` is the only out-of-sample evaluator that
  exists. No other scope is ever auto-validated. Letting a caller pass
  `validated_scopes` would hand back the laundering the module forbids.
- The owner escape hatch is `override_scopes` + a mandatory
  `override_reason` (CLI: `--override-scope` / `--override-reason`), which
  records `OVERRIDDEN_BY_OWNER` — a decision, never a `VALIDATED_*` state.
  It exists because GLOBAL and IDP may never get an external holdout and a
  permanently unpromotable model is its own failure mode.
- `rollback()` is deliberately **not** gated: reinstating a former champion
  returns production to a state it already ran, and gating it would block
  the documented undo.

Pinned by `tests/model_registry/test_promote_scope_gate.py` (10 tests),
including a parametrized case asserting that all three standing challengers
are refused against the live registry — so if that ever starts passing,
either real per-scope evidence arrived or the gate was weakened, and a
reader is forced to notice which.

RED-before / GREEN-after: with the wiring reverted, the refusal tests fail
with `Failed: DID NOT RAISE RegistryError` — the promotion goes through.
Restored, 10/10 pass and the full `tests/model_registry/` suite is 167/167.

## 6. What would change this verdict

Not a re-run and not a better criterion. Either:

1. **Per-scope out-of-sample evidence for GLOBAL and IDP** — a value-
   publishing board for each that the fit does not already train on. None
   exists today; `holdout.py` says why (every IDP-covering source votes).
   `src/model_registry/board_holdout.py` is the nearest starting point.
2. **An explicit owner override** with a recorded reason, accepting that
   GLOBAL and IDP move on OFFENSE's evidence. That is now expressible
   (`--override-scope GLOBAL --override-scope IDP --override-reason "…"`)
   and is an owner action, not an engineering one. §3's numbers are the
   blast radius that decision would be accepting.

Under either route the promotion is `promote` → `apply` → re-baseline the
two pinned reconciliation tests → full board diff → deploy — and, given
§3, a re-baseline of `tests/canonical/test_ktc_reconciliation.py` would be
rewriting pins across 741 rows. That is not a side effect to absorb inside
a promotion; it is its own reviewed change.
