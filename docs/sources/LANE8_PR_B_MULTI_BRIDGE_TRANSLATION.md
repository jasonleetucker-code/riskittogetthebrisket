# Lane 8 PR B — the multi-bridge cross-position translation owner

**Status:** `FEATURE_GREEN` / `READY_FOR_INTEGRATION`
**Lane:** 8 (Source Acquisition / Cross-Position Bridge)
**Owner authorization:** `docs/EXECUTION_PLAN.md` §"LANE 8 CHARTERED — OWNER
DECISION, 2026-08-20" — explicitly covers "the multi-bridge translation owner
and the vote-withholding repair"; explicitly does NOT authorize an IDP value
ceiling, a revival of the market corridor, or any post-consensus clamp. None
of those three is present in this PR.
**Depends on:** #954 (Lane 8 PR A — acquisition states, bridge layer, archive
schema v2), merged to `main` as `8d0198ceb` / `31724a8d4`.
**Branch:** `claude/lane8-multi-bridge-translation`, built fresh off current
`main` (the old stacked branch `claude/cross-position-bridge-v1-prb` was 115
files stale after 400+ commits of drift and was abandoned rather than
rebased; its four logical commits cherry-picked cleanly onto fresh `main`
with zero conflicts, confirming PR A's interfaces are unchanged since merge —
`git log 31724a8d4..main -- src/api/data_contract.py` is empty).

## What changed, and why it is production-safe by construction

The single-source dependency measured in #950 (`idpTradeCalc` is the only
source whose value column spans both offense and IDP, so it is the only
thing that can seed the shared-market crosswalk) is replaced by a **bridge
owner** (`src/bridges/`, from PR A) that measures — never declares — which
registered sources can actually translate an IDP-only rank into combined
market space, and combines every QUALIFIED, capable one.

Two changes, deliberately separable:

1. **The vote-withholding repair — unconditional, always on.** A source that
   ranks within the IDP class only, with no usable bridge to translate its
   rank, now casts **no vote** instead of an untranslated one. This fires on
   **0 rows of the healthy board** (measured below) and only changes anything
   when the incumbent bridge is unavailable.
2. **The multi-bridge ladder — behind `multi_bridge_ladder`, OFF by
   default.** With the flag off, `build_bridge_ladder(..., limit=1)` uses
   only the first usable bridge in registry order, which reproduces the
   incumbent single-bridge ladder **integer for integer** — the healthy board
   cannot move merely because a second bridge became *possible*. Flipping it
   on lets every qualified, capable bridge combine (measured separately;
   not part of this PR's live default).

## Board effects — healthy state

Measured against `tests.archive_fixtures.newest_complete_raw_payload()`
(`dynasty_export_20260820_133524.zip`), calling `build_api_data_contract`
directly (no monkeypatching, no simulation harness — the real production
function on the real board):

| metric | value |
|---|---|
| `crossPositionBridges.withheldNoBridge` | `{}` (0 total) |
| `crossPositionBridges.ladder.available` | `True` |
| `crossPositionBridges.ladder.contributors` | `["idpTradeCalc"]` |
| `crossPositionBridges.ladder.depth` | 370 |
| `crossPositionBridges.multiBridgeLadderEnabled` | `False` |
| `idpTradeCalc` bridge state | `QUALIFIED` / `VALID` / usable |
| `draftSharks` bridge state | `QUALIFIED` / `VALID` / usable (present, does not contribute — flag off, registry order) |
| `dynastyDealer` bridge state | `PENDING` / `NOT_COMPARABLE` / **not usable** |
| `contractHealth.ok` | `True` |
| structural errors | 0 |
| source-health errors | 0 |
| blend-integrity violations | 0 |

Zero votes withheld and a single-bridge ladder identical in composition to
the pre-PR-B incumbent is the healthy-state proof: this PR does not
materially distort the healthy board.

## Board effects — degraded state (idpTradeCalc excluded)

Same fixture, `source_overrides={"idpTradeCalc": {"include": False}}` — the
exact scenario #950 measured against the retired single-source design.

| metric | pre-repair (measured in #950) | this PR |
|---|---|---|
| untranslated votes (`method == "fallback"`) | **661** | **0** |
| flagged rows | **310** | **138** |
| top IDP value | **9,999** | **7,032** (Aidan Hutchinson) |
| IDP count in top 100 | **29** | **12** |
| `crossPositionBridges.withheldNoBridge` total | n/a (defect didn't withhold) | **0** |
| `crossPositionBridges.ladder.contributors` | n/a | `["draftSharks"]` |
| `dynastyDealer` | n/a | still `PENDING` / not usable |
| `contractHealth.ok` | n/a | `True` |

None of the four defect numbers is reproduced. Notably, **zero votes needed
to be withheld** in this scenario — Draft Sharks (the second bridge PR A's
family-not-key repair made visible) automatically took over the ladder-seed
role the moment `idpTradeCalc` became unavailable, so IDP-only specialists
kept voting, correctly translated, throughout. `dynastyDealer` stays PENDING
and does not opportunistically vote merely because a gap opened.

## Board effects — fully degraded (idpTradeCalc AND Draft Sharks both excluded)

The scenario with no cardinal bridge at all — proves the fail-closed floor
under invariant 10, beyond what the task required:

| metric | value |
|---|---|
| `crossPositionBridges.ladder.available` | **`False`** |
| `crossPositionBridges.ladder.contributors` | `[]` |
| `crossPositionBridges.withheldNoBridge` | `{"dlfIdp": 168, "idpShow": 347, "fantasyProsIdp": 187}` (702 total) |
| untranslated votes (`method == "fallback"`) | **0** |
| top IDP value | 2,999 (Sonny Styles — an ordinary value, not the display-scale ceiling) |
| IDP count in top 100 | 0 |
| `contractHealth.ok` | `True` |

702 specialist votes are withheld rather than cast untranslated. `0`
untranslated votes reach the board even with every cardinal bridge gone —
the repair holds at the true floor, not merely in the one-bridge-lost case.

## Source-family participation

| bridge key | family | comparability | why |
|---|---|---|---|
| `idpTradeCalc` | `idpTradeCalc` | `QUALIFIED` | one native 0-9999 board, offense+IDP+picks against each other by construction |
| `draftSharks` (offense) + `draftSharksIdp` (IDP) | `draftSharks` | `QUALIFIED` | one league-scored session split by the vendor's own position filter; ratio 0.998 offense/IDP projection-to-value slope (PR A / #950 §12) |
| `dynastyDealer` (offense) + `dynastyDealerIdp` (IDP, not yet registered) | `dynastyDealer` | `PENDING` | format question settled (default endpoint already SF+TEP); one remaining temporal blocker (live-voted offense vs. static un-voted IDP snapshot) |

Draft Sharks' offense and IDP halves are counted as **one** family
throughout — `assess_bridges` dedupes by declared family, so a second bridge
from an already-claimed family reports `DEPENDENT_SOURCE_FAMILY` and does not
vote twice. Dynasty Nerds is not a bridge candidate at all: it carries no
cardinal value (rank/tier only, per PR C / #971), so it is absent from
`config/bridges/bridges_v1.json` by construction rather than refused at
runtime.

## No new methodology decision was required

The task's stop condition — bridge weights, precedence, confidence
arbitration, disagreement treatment, or tie-breaking — was checked against
every design choice in this PR, and none required inventing one:

- **Combining multiple bridges' knots** reuses
  `weighted_count_aware_mean_median_blend`, the same count-aware trimmed
  mean-median the pipeline already uses for its cross-market anchor. Its own
  comment already justifies the choice over a bare mean with a worked
  three-bridge example. No new weighting rule.
- **Which family member counts when two compete** is declared order in
  `config/bridges/bridges_v1.json`, not a runtime decision — deterministic,
  and named as such in `assess_bridges`'s docstring.
- **Disagreement between bridges** is not treated specially; it flows through
  the existing blend, which already has a canonical owner.
- **Tie-breaking within one bridge's ladder** is `idp_backbone`'s existing
  descending-value / lowercased-name rule, unchanged.
- **Monotonicity** (a deeper IDP may never receive a shallower combined rank)
  is a structural correctness constraint on the blend's output, not a policy
  choice about whose opinion counts more.

So this PR proceeds rather than escalating, per the task's own instruction:
*"If no new methodology decision is required, proceed."*

## Mutation proof

Five mutations required by the task, each applied, confirmed RED, then
reverted (verified `git diff` clean before recommitting):

| # | mutation | guarding test(s) | result |
|---|---|---|---|
| 1 | remove the `PENDING` gate in `assess_bridge` | `test_pending_does_not_vote`, `test_a_pending_bridge_is_still_capable_and_still_refused` | RED — 2 failed |
| 2 | remove family-dedup check | `test_a_second_bridge_from_one_family_does_not_count_twice` | RED — 1 failed |
| 3 | coerce a missing/`None`/`0.0` value to `0.0` instead of excluding it | `TestMissingRankOrValueIsNeverCoerced` (3 new tests, this PR) | RED — 3 failed (idp_values 3→4, combined_depth 6→7) |
| 4 | let an untranslated ordinal rank reach the shared-market pool directly | `test_no_idp_only_source_is_ever_priced_on_the_global_master` | RED — reproduced `valueContribution: 9999`, `rawRank: 1`, `method: fallback` verbatim |
| 5 | remove the fail-closed withhold-with-no-bridge branch | `test_with_no_bridge_at_all_the_vote_is_withheld` | RED — same mutation as #4 (one code path serves both invariants); reproduced the exact pre-repair defect signature |

Mutations 4 and 5 are the same code path (the `else: … continue` branch in
`_compute_unified_rankings`'s Phase 1), so breaking it reproduces the
original defect's exact field values on a synthetic fixture — the strongest
form of this proof available.

## CI

- `tests/bridges/`: 18 passed (15 from PR A + 3 new missing-value tests)
- `tests/api/test_curve_routing_coordinate_pool.py`: 17 passed
- `tests/api/test_name_join_hygiene.py`, `tests/consensus_edge/test_fair_value.py`: passed
- `ruff check src/api/data_contract.py`: clean
- Full local suite (`pytest tests/ -q -m "not livedata"`): run against the
  final committed tree; see the PR's CI check run for the authoritative
  result — do not trust a suite run whose working tree changed mid-run (one
  early attempt was killed and discarded for exactly that reason).

## Changed files

```
config/bridges/bridges_v1.json                    (new, from PR A cherry-pick — bridge registry)
src/bridges/ladder.py                              (new — multi-bridge combination)
src/bridges/registry.py                            (new — registry loader)
src/api/data_contract.py                           (Phase 0 backbone selection rewired to the bridge owner;
                                                      vote-withholding branch; crossPositionBridges diagnostics)
src/api/feature_flags.py                           (multi_bridge_ladder flag, default OFF)
tests/api/test_curve_routing_coordinate_pool.py    (TestUntranslatedIdpRankKeepsIdpCurve rewritten)
tests/api/test_name_join_hygiene.py                (fixture given a real offense half)
tests/bridges/test_bridge_capability.py            (TestMissingRankOrValueIsNeverCoerced, new this PR)
tests/consensus_edge/test_fair_value.py            (TestTheGuardIsACapabilityNotAFlag rewritten)
README.md, docs/ARCHITECTURE.md                    (count string fixes, from PR A cherry-pick)
```

## Deliberately NOT in this PR

- The `multi_bridge_ladder` flag is not flipped on. Enabling it is a
  methodology change with measured board movement (337 of 1,111 values on an
  earlier board snapshot) and is an owner decision, not a Lane 8 unilateral
  default.
- No IDP value ceiling, market corridor, or post-consensus clamp — none
  exists anywhere in this diff.
- Dynasty Dealer does not vote. Qualifying it (the remaining temporal
  blocker) is PR D, unstarted.
- Dynasty Nerds is not wired as a bridge candidate — it has no cardinal
  value to offer one.
- No change to `_ALPHA_SHRINKAGE`, `TAIL_SATURATION_RANK`, any Hill constant,
  or any source weight.
- The V1 denominator itself — this document proposes evidence; Claude 5
  records any denominator change under `VERSION_1_COMPLETION_CONTRACT.md`
  §10.

## Handoff to Claude 5

- **Exact head:** see the PR's head commit on `claude/lane8-multi-bridge-translation`.
- **Changed files:** listed above.
- **Board before/after:** healthy-state and both degraded-state tables above.
- **Source-family participation:** table above.
- **PENDING withheld count:** `dynastyDealer` casts 0 votes in every scenario
  measured (comparability gate, not a withheld-vote count — PENDING bridges
  are never assessed as a translation source at all).
- **Untranslated ordinal vote count:** 0 in every scenario measured (healthy,
  one-bridge-lost, fully-degraded).
- **Degraded no-bridge behavior:** 702 votes withheld, ladder unavailable,
  `contractHealth.ok: True` — refuses cleanly rather than crashing or
  fabricating.
- **Mutation proof:** table above, all 5 required mutations confirmed RED.
- **CI:** see table above; PR-level CI status is authoritative.

Frozen after this handoff. `src/api/data_contract.py`'s pipeline core is
SERIAL — one writer only — so no further edits from this lane pending
Integration's review, and class-C data drift on `main` is not a reason to
rebase (`CLAUDE.md`, Release Discipline / HEAD FREEZE).
