# Lane 8 — PR #983's CI failure: DLF fixture repair (test-only, no production change)

**Status: FEATURE_GREEN / READY_FOR_INTEGRATION.** Test-only slice. Zero production
code touched. Claude 5 owns reconciliation with PR #983, which does not itself
touch `tests/api/test_dlf_source.py` and did not introduce this failure.

## The failure was real, and it was not #983's

`tests/api/test_dlf_source.py::TestDlfParticipatesInUnifiedRankings` had three
tests failing on `main` (post-#993) independent of #983 — reproduced directly
against current `main` with no #983 changes present:

- `test_dlf_ranks_alongside_idptradecalc`
- `test_dlf_disagreement_with_idptradecalc_blends_not_overrides`
- `test_dlf_only_player_still_gets_ranked_via_overall_idp_scope`

`dlfIdp` was absent from `sourceRanks`/`sourceRankMeta` entirely (`KeyError`),
not mistranslated.

## Root cause (evidence, not assumption)

PR #993 moved `idpTradeCalc`'s cross-position bridge capability from a
**declared** flag (`is_backbone`) to a **measured** one
(`src/bridges/descriptor.py::measure_capability` — `spans_both_pools =
offense_values > 0 AND idp_values > 0`, evaluated from the rows actually
present in that specific `_compute_unified_rankings` call).

All three failing fixtures constructed an all-IDP universe (DL/LB/DB rows
only, via the `_row()` helper's `idp=`/`dlf=` kwargs) with **zero offense
rows**. Confirmed by direct execution — `idpTradeCalc` measures as having no
offense-side coverage in that specific invocation, so it cannot prove
`spans_both_pools` there, so the unconditional vote-withholding repair
correctly withholds `dlfIdp`'s vote (it needs shared-market translation and,
*in that fixture*, no usable bridge is measurable).

The fourth, already-passing test in the same class,
`test_dlf_rank_is_mapped_through_shared_market_when_offense_present`, already
carries ten offense rows each stamped with an `idpTradeCalc` value — giving
`idpTradeCalc` genuine dual-pool coverage. It was not in the failing list.
That is the tell: these are pre-bridge-measurement fixtures that never had to
account for what a real board's offense population looks like, because
capability used to be declared unconditionally true for `idpTradeCalc`
regardless of what the fixture contained.

Independently verified, not assumed:
- `config/bridges/bridges_v1.json` has no `dlfIdp` entry — DLF has no
  offense counterpart of its own and never has. It is a specialist that
  requires someone else's bridge, exactly like `idpShow`/`fantasyProsIdp`.
- `idpTradeCalc`'s bridge descriptor declares `offenseKeys: ["idpTradeCalc"]`,
  `idpKeys: ["idpTradeCalc"]`, `comparability: QUALIFIED`, evidenced at
  "434 positive offense values and 370 positive IDP values under one key"
  on the real 2026-08-20 board — a genuine, usable bridge exists on any real
  board. The fixtures were the degenerate case, not the production path.
- `tests/api/test_curve_routing_coordinate_pool.py::
  TestUntranslatedIdpRankKeepsIdpCurve::test_with_no_bridge_at_all_the_vote_is_withheld`
  already independently pins the true no-bridge case and continues to pass
  unmodified — the withholding guard itself was never in question.

## Conclusion: Option A's fixture-staleness variant

Neither "no usable bridge → DLF withholding is correct on real boards" (there
IS a usable bridge on real boards) nor "a bridge exists but is
mis-registered" (nothing is mis-registered) applies cleanly. The actual
finding: these three fixtures do not represent a real board's shape, and the
fix is to give them the same realistic offense-row pattern the passing
sibling test already uses — restoring what these tests were written to
verify (DLF's ordinal evidence blends into the unified board through a real,
measured bridge) rather than accepting a degenerate all-IDP universe's
incidental withholding as the new "correct" assertion.

## What changed

**One file, test-only:** `tests/api/test_dlf_source.py`. Zero production
code touched (`git diff --stat` against `src/` is empty for this slice).

1. Added 10 offense rows (`idp=`/`ktc_sf=`, mirroring the passing sibling
   test exactly) to the three failing fixtures, giving `idpTradeCalc` a
   genuine, measurable dual-pool bridge. All three now pass, with the
   predicted combined-pool ranks (11/12/13) matching the pipeline's actual
   output exactly on the first run — confirming the diagnosis, not just a
   green result reached by trial and error.
2. Added a new **negative control**,
   `test_dlf_is_withheld_not_untranslated_when_no_bridge_is_measurable`: the
   *same* agreeing dl1/lb1/db1 fixture with the offense rows removed again,
   asserting `dlfIdp` is absent from both `sourceRanks` and `sourceRankMeta`
   on every row, and that `rankDerivedValue` stays below 9,999 (no
   fabricated cardinal value from an untranslated rank). This colocates the
   positive (bridge present → DLF participates) and negative (no bridge →
   DLF withheld) cases directly in the DLF consumer's own test file, rather
   than relying solely on the generic curve-routing test file for that
   guarantee.

## Mutation proofs (both performed on the real file, confirmed RED, then
restored — confirmed via `git diff --stat` returning empty)

| # | Mutation | Result |
|---|---|---|
| 1 | Replace the `continue` in the vote-withholding branch (`data_contract.py:8595-8597`) with `rank_pool = RANK_POOL_SHARED_MARKET` (let it vote anyway) | `test_with_no_bridge_at_all_the_vote_is_withheld` and `test_no_idp_only_source_is_ever_priced_on_the_global_master` (both pre-existing, `tests/api/test_curve_routing_coordinate_pool.py`) go RED |
| 2 | Same mutation | The new negative control `test_dlf_is_withheld_not_untranslated_when_no_bridge_is_measurable` goes RED (`dlfIdp` unexpectedly present in `sourceRanks`) |

Both prove: forcing untranslated DLF through without a usable bridge is
caught. Rank cannot masquerade as value.

## Tests run

- `tests/api/test_dlf_source.py` — 14/14 passed (was 3 failing).
- `tests/bridges/`, `tests/consensus_edge/test_fair_value.py`,
  `tests/api/test_curve_routing_coordinate_pool.py`,
  `tests/api/test_source_registry_parity.py` — 92/92 passed.
- `scripts/check_decision_coercions.py` — clean, no new coercions on changed
  files.
- `ruff check tests/api/test_dlf_source.py` — clean.
- Full suite, `pytest tests/ -q -m "not livedata"` — see commit for exact
  count (run to completion before this doc's final commit).

Not run here: PR #983's own new test files
(`tests/api/test_bridge_consumer_boundary.py`,
`tests/api/test_disabled_source_does_not_vote.py`) — those exist only on
#983's own branch (`claude/v1-pending-does-not-vote`), which this slice does
not check out or modify. Reconciliation between this fix and #983's branch is
explicitly Claude 5's job, not self-merged here.

## #983's permanent post-#993 invariant (correction, not a new decision)

#983's own working assumption pre-dated PR B and does not survive it
unmodified. The invariant is **not** "zero production consumers translate
through a bridge." It is:

- exactly one approved canonical production bridge-consumption path
  (`_compute_unified_rankings`'s Phase 1 translation branch);
- no second consumer;
- `PENDING` comparability never votes;
- `ORDINAL` evidence never masquerades as `CARDINAL`;
- no usable bridge ⇒ the specialist's evidence is withheld / fails closed,
  proven above by both the pre-existing generic test and the new colocated
  negative control.

#983's own "zero production consumers" census assumption (from its own PR
description, predating PR B) should be read against that corrected statement
when Claude 5 reconciles the two — not decided here.

## Deliberately NOT in this slice

- No production code change (`src/bridges/*`, `src/api/data_contract.py`,
  `config/bridges/bridges_v1.json` all untouched).
- No new bridge for DLF — confirmed it has none and should have none.
- No capability declared instead of measured.
- No relaxation of `PENDING`/ordinal protections.
- No bridge weight, precedence, confidence, or tie-break methodology change.
- No merge or edit of PR #983's own branch/files.
- No `multi_bridge_ladder` activation.

## Handoff

- **Exact head:** this commit, branch `claude/lane8-v1-136-idpshow-audit`
  (see commit for SHA).
- **Exact fixture changes:** `tests/api/test_dlf_source.py` only, described
  above.
- **Positive case:** three repaired fixtures with realistic offense rows,
  DLF translates and participates (14/14 passing).
- **Negative case:** new colocated negative control, DLF withheld when no
  bridge is measurable.
- **Mutation result:** both RED, confirmed, then reverted (empty diff).
- **Confirmation:** production code did not change for this slice
  (`git diff --stat` against everything outside `tests/` and this doc is
  empty).

**FEATURE_GREEN / READY_FOR_INTEGRATION. Then FREEZE #983** — Claude 5 owns
reconciliation and merge.
