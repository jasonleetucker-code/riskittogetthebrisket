# C7 / PR A — Source-state and cross-position bridge foundation

**Status:** implementation complete; **no production valuation change**.
**Branch:** `claude/cross-position-bridge-v1`
**Base:** `origin/main` @ `65bfca4d285707edfce36baa058d51dd5bed6f12`
**Lane:** Claude 7 (cross-position bridge). Authorization gap recorded in §7.
**Research baseline:** PR #950 /
`docs/sources/CROSS_POSITION_SOURCE_AND_IDP_CEILING_AUDIT_2026-08-20.md`

---

## 1. What this unit is for

The board's offense↔IDP translation rests on one source. `idpTradeCalc` is the
only registered source whose value column spans both pools, so it is the only
thing that can seed the shared-market ladder. Measured with it excluded: **661
votes cast on untranslated ranks, 310 flagged rows, top IDP published at 9,999,
IDP top-100 count 29 against a healthy 8.**

PR A does not repair that. It builds the three things the repair needs and the
tree does not have: a vocabulary for what happened when we tried to acquire a
source, a vocabulary for whether a bridge may translate, and a preservation
record that can hold what the new sources actually publish.

## 2. What shipped

### 2.1 `src/sources/acquisition_state.py` — acquisition outcomes

Eight states: `HEALTHY` · `PARTIAL` · `STALE` · `UNAVAILABLE` · `AUTH_REQUIRED`
· `PARSE_FAILED` · `SCHEMA_CHANGED` · `NO_CROSS_POSITION_COVERAGE`.

**None of this existed.** `grep AUTH_REQUIRED|PARSE_FAILED|SCHEMA_CHANGED|
AcquisitionState|FetchStatus` over `src/ scripts/ config/ .github/` returns
zero hits. The de-facto vocabulary was the fetcher exit-code convention (`0`
success / `1` soft failure / `2` schema regression), stated in every fetcher
docstring and existing nowhere as data — and
`.github/workflows/scheduled-refresh.yml::run_fetcher` branches on `if "$@"`,
so **exit 1 and exit 2 are the same event**: neither stamps
`data/scrape_state/<key>_last_success`. The schema-regression signal the
fetchers take care to raise is discarded before any observer sees it.

The load-bearing invariant is structural, not conventional:

> **A failed acquisition is not a healthy empty source.**

`AcquisitionOutcome.row_count` is `int | None`. `None` means no board arrived;
`0` means a board arrived and was empty. The constructor **raises** if a
failure state carries a row count, and raises if a failure carries no reason.
A corrected value would be indistinguishable from a real one, so nothing is
corrected.

Freshness is *not* re-derived here. `STALE` is an outcome a caller may record;
the rule that decides it stays in `scripts/watchdog_freshness.classify_freshness`,
whose docstring already forbids a second freshness rule.

### 2.2 `src/bridges/` — what a bridge is, and whether it may translate

`states.py` — bridge lifecycle (`VALID` · `STALE` · `PARTIAL` · `UNAVAILABLE`
· `NOT_COMPARABLE` · `INSUFFICIENT_COVERAGE` · `DEPENDENT_SOURCE_FAMILY`) and
comparability (`QUALIFIED` / `DISPROVEN` / `PENDING`, failing closed).

`descriptor.py` — the declared/measured split. A `BridgeDescriptor` declares
identity, family, kind (`CARDINAL` / `ORDINAL`), the offense keys, the IDP
keys and its comparability evidence. A `BridgeCapability` is **measured from
the board that arrived**.

`assess.py` — the policy, ordered by how fundamental the objection is:
comparability → acquisition → freshness → capability → family independence.

Two design decisions carry the unit:

**A bridge is a FAMILY, not a key.** `build_backbone_from_rows` seeds from one
registry key. Draft Sharks publishes offense and IDP on one native scale from
one league-scored pass, but its halves are registered under `draftSharks` and
`draftSharksIdp`. Per key, the IDP half carries **zero** offense values and
produces the identity ladder `[1, 2, 3, …]` — which *is* the fallback the
crosswalk exists to prevent. Per family, it is a real bridge.

**Capability is measured, never declared.** `tests/consensus_edge/
test_fair_value.py::TestTheGuardIsACapabilityNotAFlag` already proves the
existing `is_backbone` flag can be moved onto a source that cannot seed a
ladder, satisfying the guard while leaving the board exactly as broken. And
depth is not a capability test either: `dlfIdp` (163) and `idpShow` (247) both
clear any depth comparison while producing identity ladders. The property that
separates a real ladder from the identity is that **it does not start at 1**.

### 2.3 `src/source_archive/records.py` + schema v2 — preservation

`ArchivedBoard.rows` is `dict[str, float]`: one number per name. It can hold a
rank **or** a value, never both, and cannot hold a positional rank, a tier, a
position, a team or the vendor's own id at all. For the sources this program
acquires that is fatal — Dynasty Nerds' IDP Top-275 is *entirely* rank,
positional rank and tier.

`ArchivedRow` preserves source-native rows: vendor id, Sleeper id, canonical id
(`None` while unresolved), the vendor's own position **beside** our DL/LB/DB
family (`EDGE` is information `DL` discards), team, age, overall rank,
positional rank, tier, value, value unit, and a free-form `native` block.

Every quantity is optional and defaults to `None`. `overall_rank = 0` raises;
`value = 0.0` is preserved as the observation it is; a declared `value_unit`
with no value raises.

**The extension is additive.** Schema v2 adds a nullable `records_json` column
with an idempotent `ALTER TABLE` migration (`CREATE TABLE IF NOT EXISTS` will
not alter an existing table, so a v1 archive would otherwise report
`schema_version = 2` while keeping its old shape). A board with no records
hashes exactly as it did under v1, so re-archiving one stays the no-op it was.
All 69 pre-existing `tests/sources/` tests pass unchanged.

## 3. Measured — the family rule works on the real board

Built from `exports/latest/dynasty_data_2026-08-20.json` at this branch's head.

| bridge | offense values | IDP values | ladder start | depth | capable | state |
|---|---|---|---|---|---|---|
| `idpTradeCalc` (one key, both pools) | 434 | 370 | **29** | 370 | yes | `VALID` |
| `draftSharks` **as a family** | 343 | 180 | **18** | 180 | **yes** | `VALID` |
| `draftSharksIdp` alone (today's rule) | **0** | 143 | **1** | 143 | **no** | `INSUFFICIENT_COVERAGE` |
| a second Draft Sharks descriptor | 343 | 180 | 18 | 180 | yes | `DEPENDENT_SOURCE_FAMILY` |

The third row is the current production rule; the second is the repair. The
fourth is signal independence holding: the duplicate is refused for
*independence*, not for incapability, and the assessment says so.

**Parity with the pipeline's own ladder.** Handed the same universe the
pipeline uses (`_OFFENSE_POSITIONS | {"PICK"}` — picks occupy combined-pool
ranks), `measure_capability` and `build_backbone_from_rows` agree exactly:
**start 34, depth 370** from both. Pinned by
`tests/bridges/test_bridge_pipeline_parity.py`, which asserts the *invariant*
that the two owners agree rather than any particular number.

## 4. Board inertness

Measured by building the contract twice on **the same tree**, once with these
changes stashed:

```
WITH    my changes: 1111 rows  3c19f6de640707cc01d8bd1e607b218a3096f009c207d0958b1b668c33b2e893
WITHOUT my changes: 1111 rows  3c19f6de640707cc01d8bd1e607b218a3096f009c207d0958b1b668c33b2e893
IDENTICAL: True
```

`contractHealth.ok: True`. Nothing in `src/api/` imports `src/bridges/` or
`src/sources/acquisition_state.py`; `src/source_archive/` is still unimported
by the pipeline (the package's own test asserts it).

A same-tree comparison is the only honest one here. This branch is based on a
newer `main` than PR #950's measurements, and the board legitimately differs
from that older capture (1,109 → 1,111 rows) purely from base movement and CSV
refresh — the exact attribution error `scripts/golden_board.py`'s docstring
records ("290 values moved … entirely from CSV churn, and the capture reported
it as though the code had done it").

## 5. Tests

**100 passed** across `tests/sources/` (69 pre-existing + 31 new) and
`tests/bridges/` (19 new, of which 4 run against a real archived board and
skip without one).

The red→green self-check is `tests/bridges/test_bridge_capability.py::
TestTheFamilyRuleIsWhatMakesThisWork`, which asserts **both** halves — that the
single-key rule produces the identity ladder on the fixture, and that the
family rule does not — so the suite cannot pass with or without the repair.

### Mutation proof — 8 applied, 8 caught

Each dangerous behaviour was restored, the guard run, and the tree restored.
Full output: `docs/sources/evidence/C7_BRIDGE_FOUNDATION/mutation_proof.json`.

| # | restored behaviour | result |
|---|---|---|
| M1 | a failure state may carry a row count | 4 failed |
| M2 | fetcher exit 1 and exit 2 collapse | 2 failed |
| M3 | capability is declared, not measured | 1 failed |
| M4 | `PENDING` comparability is allowed to vote | 2 failed |
| M5 | source-family dedup stripped | 1 failed |
| M6 | a missing rank is coerced to zero | 1 failed |
| M7 | a stale bridge counts as current | 1 failed |
| M8 | records dropped from the archive hash | 1 failed |

Every mutation was confirmed **APPLIED** — the runner refuses an anchor that
does not match exactly one site, because a pass over an unapplied mutation
proves nothing.

## 6. Deliberately not in this unit

No production valuation change. No IDP value ceiling, no corridor, no
post-consensus clamp. `TAIL_SATURATION_RANK`, `_ALPHA_SHRINKAGE`, every Hill
constant and every source weight are untouched. `_RANKING_SOURCES` is
unchanged — no source is registered here, and **acquisition and weighting stay
separate decisions**. No fetcher is wired to the new vocabulary yet; that lands
with the adapters it describes.

## 7. Authorization gap — for Claude 5 and the owner

Recorded because it is real and I cannot resolve it myself.

`docs/EXECUTION_PLAN.md:41-48` authorizes six lanes (L1–L6); there is no lane
7, and §0 (`:18-32`) authorizes implementation of the **V1 REQUIRED denominator
only**. A grep for `bridge|cross-position` in that file returns zero
authorizing hits. The nearest denominator row is
`V1-23 | IDP valuation correctness | L5 | IN PROGRESS | L2`.

The owner has decided this work is top-priority V1. Per
`VERSION_1_COMPLETION_CONTRACT.md` §10 the denominator change is an owner
decision recorded by the Integration Authority, and per the lane brief §44 I
prepare proposed rows rather than editing §3. **This unit does not change the
denominator and does not mark anything `VERIFIED`.**

What is still needed before PR B (the production change) merges: either Lane 7
is chartered in `EXECUTION_PLAN.md` §0, or this work is absorbed under Lane 5
alongside `V1-23`. `src/api/data_contract.py`'s pipeline core is additionally
**SERIAL — one writer only** (`EXECUTION_PLAN.md:845`), so PR B must be
scheduled rather than raced.

### Proposed V1 rows (for Claude 5 — not applied here)

| proposed capability | canonical id | level | in V1 because |
|---|---|---|---|
| Multi-bridge cross-position translation — the board may not depend on one source as the only mechanism preventing raw IDP ordinal ranks from entering combined-market space | `C7-BRIDGE-01` | L2 | canonical value correctness |
| Truthful bridge loss — no valid bridge yields an explicit unavailable state, never a fabricated value or rank | `C7-BRIDGE-02` | L2 | missing is never zero |
| Cross-position raw preservation — rank, positional rank, tier, cardinal value, provenance and freshness survive archival without coercion | `C7-SRC-03` | L1 | evidence retention (**this unit**) |
| Source acquisition states — a failed or unauthenticated acquisition cannot report as a healthy empty source | `C7-SRC-04` | L1 | false-green repair (**this unit**) |
| Common-mode protection — derivative sources cannot masquerade as independent bridge evidence | `C7-SRC-05` | L1 | signal independence (**this unit**) |

## 8. Next units

**PR B** multi-bridge translation owner (SERIAL; needs the charter above).
**PR C** Dynasty Nerds public ordinal/tier IDP Top-275.
**PR D** Dynasty Dealer acquisition + same-basis qualification — status
`PENDING` on two measured blockers: its format flags are echo-only (0 of 1,338
values change under `isSuperflex=true&isTePremium=true`) and its IDP half is a
static 2026-07-15 snapshot with 0% votes against daily, 46%-voted offense.
**PR E / PR F** IDP Show and Footballguys — both `AUTH_REQUIRED` in this
environment.
