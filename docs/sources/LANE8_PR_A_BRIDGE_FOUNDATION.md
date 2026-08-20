# Lane 8 / PR A — Source-state and cross-position bridge foundation

**Status:** implementation complete; **no production valuation change**.
**Branch:** `claude/cross-position-bridge-v1`
**Base:** `origin/main` @ `65bfca4d285707edfce36baa058d51dd5bed6f12`
**Lane:** Claude 8 / Lane 8 (source acquisition & cross-position bridge). Authorization gap recorded in §7.
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
Full output: `docs/sources/evidence/LANE8_BRIDGE_FOUNDATION/mutation_proof.json`.

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

**RESOLVED 2026-08-20.** The owner chartered **Lane 8** in
`EXECUTION_PLAN.md` §0 and recorded the authorization there. (Lane 7 was the
label this unit first used; it belongs to the Lane Dispatcher, per
`docs/claude-dispatch/LANE_STATUS.json`.) `src/api/data_contract.py`'s pipeline core is additionally
**SERIAL — one writer only** (`EXECUTION_PLAN.md:845`), so PR B must be
scheduled rather than raced.

### Proposed V1 rows (for Claude 5 — not applied here)

| proposed capability | canonical id | level | in V1 because |
|---|---|---|---|
| Multi-bridge cross-position translation — the board may not depend on one source as the only mechanism preventing raw IDP ordinal ranks from entering combined-market space | `LANE8-BRIDGE-01` | L2 | canonical value correctness |
| Truthful bridge loss — no valid bridge yields an explicit unavailable state, never a fabricated value or rank | `LANE8-BRIDGE-02` | L2 | missing is never zero |
| Cross-position raw preservation — rank, positional rank, tier, cardinal value, provenance and freshness survive archival without coercion | `LANE8-SRC-03` | L1 | evidence retention (**this unit**) |
| Source acquisition states — a failed or unauthenticated acquisition cannot report as a healthy empty source | `LANE8-SRC-04` | L1 | false-green repair (**this unit**) |
| Common-mode protection — derivative sources cannot masquerade as independent bridge evidence | `LANE8-SRC-05` | L1 | signal independence (**this unit**) |

## 7a. Research-record correction — Dynasty Dealer

Recorded here rather than by rewriting PR #950, which is frozen research
evidence. **The measurement stands; its interpretation was wrong.**

PR #950 reported that Dynasty Dealer "publishes **0 IDP rows of 723**, so it
cannot be a bridge." Both halves of that measurement are reproducible — the
Supabase `/rest/v1/players` table returns 723 rows with zero IDP, and the
default `/api/player-values` returns 1,000 rows with zero IDP. What was wrong
was the conclusion drawn from them.

The IDP data sits behind an **undocumented query parameter**, recovered from
the site's own JavaScript bundle:

```
GET /api/player-values?includeIdp=true&limit=5000   →  1,338 rows
WR 414 · RB 241 · TE 181 · QB 128 · DB 126 · LB 117 · DL 95 · PICK 36
```

338 IDP rows, carrying `current_value` on the same field as offense. The top
four match the owner-supplied figures exactly: **Myles Garrett 5,121 · Will
Anderson 4,601 · Jack Campbell 4,599 · Aidan Hutchinson 4,584**.

So the durable record is:

> The previously inspected Dynasty Dealer acquisition paths returned zero IDP
> rows because they omitted `includeIdp=true`. That was an **acquisition-path
> limitation, not proof that the source lacks defensive cardinal values.**
> Bridge eligibility now depends on demonstrating that those defensive values
> share the same valuation basis as the offensive `current_value` API.

### CORRECTION 2 (2026-08-20, owner traffic-control): the flags are NOT proof of no adjustment

**The narrow measurement stands. The generalization drawn from it was wrong,
and this section previously carried the wrong one.**

True, and unchanged: *the `isSuperflex` / `isTePremium` query parameters do not
alter the values returned by the documented `/api/player-values` dynasty
endpoint* — 0 of 1,338 change.

**Withdrawn:** that Dynasty Dealer therefore does not adjust dynasty values for
Superflex or TE Premium, and that the board is 1QB. That rested on "QB1 sits
below RB1" — a convention, not evidence. It is the same class of error as
W18-F001, a label deciding a factual question. This lane exists to prevent it
and reproduced it.

**The API's default dynasty board is ALREADY Superflex + TE Premium.** Measured
against the owner's independent observation of the live UI with SF + TE+ on:

| player | owner observed (live UI, SF+TEP) | API default board |
|---|---|---|
| Josh Allen | ~#4 overall, ~9,495 | **#4 overall, 9,495** |
| Brock Bowers | ~#8 overall, high 8,000s | **#8 overall, 8,611** |

Exact agreement on rank and value. The flags are inert on this endpoint because
it serves **one** board — and that board is the one this league wants.

**The parameter is a REDRAFT parameter, and it works there.** The vendor's own
documentation places `sf=true` under redraft mode. Tested:
`?format=redraft&scoring=ppr&sf=false` against `sf=true` changes **623 of 1,000
values** (Carson Wentz 638 → 475). The earlier test exercised a real parameter
against an endpoint it does not apply to.

### How the live UI obtains format-adjusted values

Established from the site's own JavaScript rather than inferred from displayed
values. Against the owner's A–E list this is **C + D**:

* **C — multiple format values in one payload.** Every IDP row carries
  `idp_formats: {tackle, balanced, bigplay}`, each with `value`, `trades` and
  `source`, plus `idp_format: "blended"` and `idp_blended_value`. The served
  `current_value` is the blended one.
* **D — a deterministic client-side transformation** for the non-default
  offense formats. `5269.*.chunk.js` recomputes `value = ge(originalValue,
  position)` in a `useEffect` keyed on `[isSuperflex, isTePremium]`, logging
  `"<name>: <before> -> <after>"`. `6898.*.chunk.js` caches per format key
  (`sf_tep` / `1qb_std` / …) around the same endpoint.

**This does not affect our acquisition.** This league is Superflex + TE Premium,
which is the basis the endpoint already serves, so the client transform is the
path to the formats we do *not* want.

**Limitation, recorded rather than papered over:** the exact coefficients of
that transform were not extracted. Static analysis reached the call site but not
the minified definition, and driving the live UI failed — Chromium reaches the
agent proxy but `www.dynastydealer.com` resets the connection for the browser,
while curl over the same proxy succeeds. No access control was bypassed and none
was attempted. If the transform ever matters, a browser session outside this
sandbox is the way to get it.

### IDP: what the payload settles, and what it does not

| question | answer | evidence |
|---|---|---|
| Cardinal IDP values? | **YES** | 338 rows, `current_value` on the same field as offense |
| Same 0–10,000 axis? | **YES** | offense max 10,000, IDP max 5,121; identical field set plus five `idp_*` fields |
| Do SF / TE+ alter IDP? | **NO** | 0 of 1,338 change — correct, those are offense-format axes |
| Does `includeIdp` alter offense? | **NO** | 0 of 1,000 shared values change; purely additive |
| tackle / balanced / bigplay exposed? | **YES — all three, in one payload** | `idp_formats` on all 338 rows |
| Which variant would we use? | `blended` is served; any is selectable | `idp_format: "blended"`, `idp_blended_value == current_value` |
| Is league sync required? | **NO** | no auth, no league, no cookie — a plain public GET |

Variant provenance is uneven and must travel with any ingestion: `balanced` is
`source: "market"` on 327 of 338 rows, but `bigplay` is `derived` on 230 and
`tackle` on 194. `idp_confidence` is **high 134 / medium 59 / low 145**. 12,104
trades sit behind the IDP values, median 25 per player.

### Bridge status: still `PENDING`, on ONE blocker now, not two

The format blocker is **dissolved**. What remains is temporal:

| | offense | IDP |
|---|---|---|
| distinct `updated_at` | **33**, through 2026-08-20 | **1** — all 2026-07-15 |
| rows carrying votes | 445 / 964 (46.2%) | **0 / 338 (0.0%)** |
| `base_value` vs `current_value` | diverge | identical on every row |

Offense `current_value` is a live, crowd-vote-adjusted number; IDP
`current_value` is a static market blend last moved on 2026-07-15. Joining them
compares a live price with a five-week-old one. Not disqualifying, but not
qualifying either, and whether a static IDP snapshot may bridge against live
offense values is an owner decision.

Also unanswered by the payload: whether the trades behind the IDP blend come
from Superflex/TEP leagues. The offense board's basis is now established; the
IDP board's is asserted only by being served beside it.

**Status — cardinal offense YES · cardinal IDP YES · SF adjustment YES · TEP
adjustment YES · format-adjusted acquisition path ESTABLISHED (the default
payload) · offense↔IDP same-basis PENDING · production voting NOT AUTHORIZED.**

For whoever writes the adapter: offense `min = 0` on 158 of 964 rows. Under
MISSING IS NEVER ZERO those are unpriced, never zero-valued.

Attribution requirement, verbatim from the vendor's own API documentation:
*"free for any use — personal, commercial, or content — on one condition:
display a visible link to dynastydealer.com."* Preserved as source metadata, not
as a one-time research note.


## 8. Next units

**PR B** multi-bridge translation owner (SERIAL; needs the charter above).
**PR C** Dynasty Nerds public ordinal/tier IDP Top-275.
**PR D** Dynasty Dealer acquisition + same-basis qualification — status
`PENDING` on ONE remaining blocker (§7a): its IDP half is a static 2026-07-15
market blend with 0% votes, joined to a daily, 46%-voted offense board. The
format question is settled — the endpoint already serves the Superflex + TE
Premium board this league needs.
**PR E / PR F** IDP Show and Footballguys — both `AUTH_REQUIRED` in this
environment.
