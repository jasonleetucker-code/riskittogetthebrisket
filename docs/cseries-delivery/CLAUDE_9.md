# Claude 9 — C-Series Delivery Ledger: Trade Architecture & Decision Products

**Lane:** C-Series mass implementation, C3 Trade substrate (sole/serial writer) + directly-dependent C7 trade
decision products. **Branch:** `claude/cseries-trade-decision-mrwj7r`. **Does not merge its own PRs** — Claude 5
(Integration Authority) owns merge; this ledger hands off bounded units for review.

Authorization basis: `docs/EXECUTION_PLAN.md` §0 (V1 Completion Sprint, 2026-08-18), lane 2 ("Trade Intelligence")
ownership of package generation / Value Adjustment / capacity / trade simulation / team-context trade logic /
Analyze Trade, per `docs/VERSION_1_COMPLETION_CONTRACT.md` §3.3 rows V1-36…V1-47, V1-97, and
`docs/C_SERIES_EXECUTION_MAP.md` §5 (C3-U1…U9) + §9 (C7-U1…U11).

Read-first census performed 2026-08-20 before any code change: `AGENTS.md`, `CLAUDE.md`, `ASSISTANT_COORDINATION.md`,
`docs/EXECUTION_PLAN.md`, `docs/C_SERIES_SCOPE_MANIFEST.md`, `docs/C_SERIES_EXECUTION_MAP.md`,
`docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md`, `docs/MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md`,
`docs/VERSION_1_COMPLETION_CONTRACT.md` §3.2/§3.3, `docs/WORK_CLAIMS.md`.

**Dependency note carried forward from the census:** `C3-PKG-01` (one shared package generator — "the gate for all
of C7") formally depends on `C2-U3` (exact roster simulation, `C2-SIM-01`) and `C2-U4` (canonical Team Strength,
`C2-STR-01`) per `C_SERIES_EXECUTION_MAP.md` §5. `C2-STR-01` exists in `src/ros/team_strength.py` (landed by lane
1's `#914`). `C2-SIM-01` is **NOT STARTED** as of this census (owned by lane 1, `WRONG-OWNER` status — no
`before→apply→re-solve→after` engine exists; `trade_simulator.py` is value-delta only and `team_impact.py`
reimplements the lineup). Per the calibration policy §5.3 / §8 dependency principle: *"do not invent package
premiums before exact roster simulation exists."* Units that need true roster-impact scoring are therefore
genuinely blocked pending lane 1; units that do not (VA consolidation, cross-market wiring, topology, constraints
already done) are not, and are worked first.

---

## Unit log

### Unit 1 — `C3-VA-01`: eliminate the third standalone KTC-VA Python port

**Manifest rows:** `C3-VA-01`. **Status at start:** manifest says "DUPLICATED — 5 implementations, one via
import-time monkeypatch." Re-measured at HEAD rather than trusted: the monkeypatch and 2 of the "5" duplicates were
**already retired on `main`** (dated commentary in `src/trade/finder_value_adjustment.py` and
`frontend/lib/trade-logic.js` shows this happened under an earlier, undocumented pass — `market_value_adjustment.py`
is a pure re-export of `src/trade/ktc_va.py`, and `suggestions.py`/`angle.py`/`monte_carlo.py` all import from the
one owner). **One genuine duplicate remained**: `src/public_league/trade_grading.py::ktc_adjust_package` is a full,
independently-maintained second Python port of `processV`/`reverseAdjust`/`checkEquality`/`adjustPackage` — not a
copy-paste accident but a structural necessity, since `tests/public_league/test_public_contract.py::
ImportSurfaceTests` hard-forbids anything under `src/public_league` from importing `src.trade` (or `src.canonical`,
`src.pool`, `src.api.data_contract`) at all, so it could not delegate to `src.trade.ktc_va` even though the two
files were, function-for-function, the same algorithm with renamed locals (`l`→`guess`, `T`→`big_t`, `V`→`big_v`
for ruff `E741`).

**Owner decision, not invented:** the public/private import boundary is a deliberate governance invariant (§5,
CLAUDE.md — public/private is a semantic boundary, not a field-name denylist) and is not something this unit may
relax. The fix is structural: extract the **pure, stdlib-only** algorithmic core (no imports beyond `math`) into a
new module outside every forbidden prefix, so both `src/trade` and `src/public_league` import the *same* code
without either boundary rule bending.

**Delivered:** `src/valuation_math/ktc_va_core.py` (new) — `js_round`, `process_v`, `reverse_adjust`,
`check_equality`, `build_side_adj`, `adjust_package_raw` (returns a plain `(value, side, displayed)` tuple, the
lowest common shape both callers wrap). Zero dependencies beyond `math`/`dataclasses`/typing.

- `src/trade/ktc_va.py` — `ktc_process_v`, `ktc_reverse_adjust`, `ktc_adjust_package` are now thin wrappers over the
  core; `KtcVAResult` dataclass and every existing public name/signature preserved byte-for-byte (no consumer
  touched: `market_value_adjustment.py`, `finder_value_adjustment.py`, `suggestions.py`, `angle.py`,
  `monte_carlo.py` all unchanged).
- `src/public_league/trade_grading.py` — its private `_ktc_process_v`/`_ktc_reverse_adjust`/`_ktc_check_equality`/
  `_ktc_build_side_adj` are deleted; `ktc_adjust_package` (dict-returning, its existing public shape) now calls
  `adjust_package_raw` from the shared core. `trade_va_net`, `grade_trade_side`, `grade_trade_sides`,
  `sanitize_side_values`, `grade_from_pct` (the grading-specific logic, genuinely not VA duplication) untouched.
  Import is `from src.valuation_math.ktc_va_core import ...` — passes `ImportSurfaceTests` because
  `src.valuation_math` is not in `FORBIDDEN_IMPORT_PREFIXES` and has no transitive import of anything that is.

**Single-owner guard (new):** `tests/valuation_math/test_single_owner.py` — AST-scans `src/public_league/` and
`src/trade/` (excluding `ktc_va.py` and `ktc_va_core.py` themselves) for a re-implementation of the algorithm
(function bodies matching `processV`'s characteristic literals `1.3`, `1.05`, `6`, `0.1` in one call, and
`reverseAdjust`'s `0.025`/`10099` — the KTC-specific magic constants that can only appear in a reimplementation).
Positive control: a decoy module containing a real copy is confirmed to trip the guard before being deleted.

**Verification:**
- `tests/trade/test_ktc_va_python_port.py` + `tests/public_league/test_trade_grade_parity.py` +
  `tests/trade/test_finder_value_adjustment.py`: **30 passed, 50 subtests passed** (byte-identical to the
  pre-change baseline, re-measured before touching anything).
- `tests/trade/` + `tests/public_league/` + `tests/valuation_math/` + `tests/league_intel/` full sweep:
  **1,688 passed**, 0 failed.
- New `tests/valuation_math/test_single_owner.py` — 5 tests, including two positive controls (a synthetic
  `processV`-shaped and a `reverseAdjust`-shaped snippet, each confirmed to trip the scan) and one negative
  control (two shared literals alone must not trip it). **Mutation-proven**: copying a real `processV`-fingerprint
  function into a throwaway `src/trade/_mutation_decoy_ktc_va.py` turned the guard test RED
  (`AssertionError: Found a reimplementation ... ['src/trade/_mutation_decoy_ktc_va.py']`); deleting the decoy
  restored GREEN. So the guard is a real scan over the shipped tree, not a decorative one.
- `ruff format --check` + `ruff check` (pinned `ruff~=0.6.0`, resolved 0.6.9) on every touched file: clean.
- `py_compile` on every touched/consuming module: clean.

**Production impact:** none — pure internal refactor, zero output values change. No canonical value, board, or API
contract touched. The only two call sites whose *arithmetic* moved (`ktc_va.py`, `trade_grading.py`) are proven
identical by the two parity fixtures they were already pinned against, and both fixtures are unmodified.

**Duplicates retired:** 1 (the third standalone Python VA port in `trade_grading.py` — `_ktc_process_v`,
`_ktc_reverse_adjust`, `_ktc_check_equality`, `_ktc_build_side_adj`, and the branch body of `ktc_adjust_package`,
all deleted in favor of `src.valuation_math.ktc_va_core`).

**Dependencies:** none (C3-U2 has no upstream deps per the execution map).

**Blocker:** none. Unit is complete for its declared scope.

**Note on the manifest's "5 implementations" framing:** re-measured at HEAD rather than trusted. Two of the five
(`market_value_adjustment.py`'s prior standalone port, the finder's import-time monkeypatch) were already retired
by an earlier, undocumented pass before this session started — `market_value_adjustment.py` was already a pure
re-export and `finder_value_adjustment.py`'s own docstring records the monkeypatch's retirement date (2026-08-18).
This unit closes the one genuine survivor. `src/trade/ktc_va.py` is now the sole PRIVATE-side Python owner (backed
by the shared stdlib-only core); `src/public_league/trade_grading.py` is the sole PUBLIC-side owner, structurally
unable to diverge because both wrap the same core function. The JS side (`frontend/lib/trade-logic.js`) was
already single-owner with V2/V12/V13 dead code already removed — verified by reading the file, not reused from the
manifest's claim.

**Commit SHA:** `877c8f35`

**PR-ready status:** READY_FOR_INTEGRATION — small, self-contained, fully tested, zero production value change,
no dependency on any other in-flight unit.

---

### Unit 2 — `C2-SIM-01`/`C3-CAP-01` wiring: `/api/trade/simulate` surfaces the final legal roster

**Manifest rows:** `C2-SIM-01` (roster-simulation consumer completeness at the trade-simulate surface); adjacent
to the already-VERIFIED `C3-CAP-01` (V1-39). **Status at start, re-measured at HEAD rather than trusted from the
manifest:** `docs/C_SERIES_SCOPE_MANIFEST.md` records `C2-SIM-01` as "WRONG-OWNER — trade_simulator is
value-delta only; team_impact reimplements the lineup", owned by lane 1, `NOT STARTED` per
`docs/VERSION_1_COMPLETION_CONTRACT.md` V1-42. **Both claims are stale.** Verified directly:

- `src/roster_intel/simulation.py::simulate_roster_change` is a real, tested, correctly-owned primitive (its own
  docstring opens *"Exact before → apply → re-solve → after roster simulation (C2-SIM-01)"*), built by lane 1.
- `src/trade/team_impact.py::project_starters` already calls the canonical exact solver
  (`src.ros.lineup.assign_lineup`) rather than reimplementing it — that manifest charge is also stale (repaired by
  C2-U1, already CLOSED).
- `src/trade/roster_capacity.py::simulate_final_legal_roster` (this lane's own module, already VERIFIED as
  `C3-CAP-01`) already **composes** `simulate_roster_change` correctly, implementing the full
  `before → apply → capacity/overage → optimal cleanup → re-solve → recompute` sequence from
  `docs/MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md` §5.3. Proven independently by
  `tests/trade/test_trade_consumes_roster.py` (9-property structural proof, P1-P9).
- `docs/roster-intelligence/C2_CANONICAL_ROSTER_CHAIN.md` §14 already records this composition as the intended,
  closed shape ("`simulation.py` stays… `C3-CAP-01` depends on it").

**The one genuine, narrow gap — confirmed by grep before writing any code:** `src/api/trade_simulator.py`, the
actual `/api/trade/simulate` HTTP endpoint (squarely this lane's responsibility, not lane 1's), called
`assess_roster_capacity` (a forced-drop **cost estimate** only) but had **zero** occurrences of
`simulate_final_legal_roster` or `simulate_roster_change`. So the live endpoint told a user "you'll need to drop
someone, here's the estimated cost" but never resolved *which* player, never re-solved the final lineup, and never
reported the Team Strength delta — even though every piece to do so already existed, was already owned correctly,
and was already tested elsewhere.

**Delivered:** `simulate_trade()` now captures the `RosterCapacity` object it was already computing (previously
discarded after `.to_dict()`) and, when `capacity.requires_drops` is knowable (`True` or `False` — not the
taxi-bracket-ambiguous `None`), calls `roster_capacity.simulate_final_legal_roster(capacity_context, capacity,
incoming_players=players_in, outgoing_players=players_out)`, publishing the result as a new sibling response field
`finalRosterSimulation` (never nested inside the separately-tested `rosterCapacity` contract). Missing-is-never-zero
discipline: the field is **absent entirely** (not `null`, not `{}`) when `resolved_team` is falsy or the
`rosterCapacity` block itself failed; it degrades to `{"available": False, "unavailableReason":
"capacity_uncertain", ...}` when taxi ambiguity makes the outgoing set itself uncertain (reusing the callee's own
vocabulary rather than inventing a new one); a failure in the simulate call itself is caught in its **own**
try/except so it can never erase an already-successful `rosterCapacity` result. A clean-fitting trade (no forced
drop needed) still gets a populated block with `cleanupApplied: []` — the callee already handles that path for
free, and a clean trade's Team Strength delta is real information too.

**Single-owner discipline preserved, not re-derived:** this unit adds no lineup solver, no Team Strength formula,
no replacement/PAR logic and no new roster-impact methodology of its own — it is pure composition of two
already-owned, already-tested primitives (`simulate_roster_change` at the roster_intel/lane-1 owner,
`simulate_final_legal_roster` at this lane's own `C3-CAP-01` owner) at one call site that was not yet calling them.

**Verification:**
- **RED confirmed before GREEN, by direct reversion rather than write-then-check:** `git stash`d the
  `trade_simulator.py` edit, ran the four new tests against the untouched code — all four failed with
  `KeyError: 'finalRosterSimulation'`, the exact gap this unit closes. Restored the edit (`git stash pop`) — all
  four pass.
- 4 new tests in `tests/api/test_trade_simulator.py`: (1) a roster already at a 6-man cap (fixture mirrors
  `tests/trade/test_trade_consumes_roster.py`'s `TINY_ROSTER`/`TINY_SETTINGS` exactly, so the same forced-drop
  outcome — TE1, the cheapest RB/WR/TE-flex-redundant player — is independently reproduced here) receiving one
  player with none going out: `finalRosterSimulation.cleanupApplied` names the **same** player id(s) as
  `rosterCapacity.forcedDrops` (proving the cleanup is the capacity answer's own drops, not a second,
  independently-chosen selection — mirroring `test_trade_consumes_roster.py::test_a_forced_drop_is_never_also_retained`),
  and the block carries a real `strengthDelta`/`movements`/`isVerdict: False`; (2) no `resolved_team` → both
  `rosterCapacity` and `finalRosterSimulation` genuinely absent from the response, not `null`; (3) a clean 1-for-1
  swap (roster size unchanged) → `available: True`, `cleanupApplied: []`; (4) `roster_settings` carrying no
  `starters` key → `available: False`, `unavailableReason: "starter_slots_unresolved"`, propagated end-to-end from
  the callee's own refusal vocabulary.
- Full regression sweep: `tests/api/test_trade_simulator.py` (22/22) + `tests/api/test_trade_simulate_mc.py` +
  `tests/trade/test_trade_consumes_roster.py` + `tests/trade/` + `tests/roster_intel/` — **1,366 passed, 22
  skipped** (pre-existing, unrelated skips), 0 failed.
- `ruff format --check` + `ruff check` (pinned `ruff~=0.6.0`) on both touched files: clean.

**Production impact:** additive only. Every existing response field (`team`, `before`, `after`, `delta`,
`receiving`, `sending`, `unresolvedIn`, `unresolvedOut`, `equity`, `teamImpact`, `rosterCapacity`) is unchanged in
presence, shape and value — confirmed by the full pre-existing test suite passing unmodified. Old clients ignore
the new `finalRosterSimulation` field. This is an intentional new capability at a live endpoint, not a silent
behavior change; called out explicitly per the reporting requirement.

**Duplicates retired:** 0 (this unit adds no new owner; it wires an existing call site onto existing owners).

**Dependencies:** none blocking — consumes only already-CLOSED/VERIFIED owners (`C2-LINE-01`, the roster_intel
C2-SIM-01 primitive, this lane's own `C3-CAP-01`).

**Blocker:** none. Unit is complete for its declared scope.

**Commit SHA:** `63138600`

**PR-ready status:** READY_FOR_INTEGRATION — small, self-contained, fully tested, zero regression on any existing
field, additive-only production impact.

---

### Unit 3 — Documentation repair: stale `C2-STR-01` / `C2-SIM-01` / `C3-PKG-01` / `C3-VA-01` / `C3-XMKT-01` rows

**Manifest rows:** the canonical-owner map and detailed rows for `C2-STR-01`, `C2-SIM-01`, `C3-PKG-01`,
`C3-VA-01`, `C3-XMKT-01` in `docs/C_SERIES_SCOPE_MANIFEST.md`, plus the mirrored unit descriptions in
`docs/C_SERIES_EXECUTION_MAP.md` §4 (`C2-U4`) and §5 (`C3-U1`, `C3-U2`, `C3-U6`).

**Why:** the deep exploration pass that grounded Units 1/2/4 (three research agents + extensive direct
verification with Grep/Read of exact line numbers, corroborated against `docs/roster-intelligence/
C2_CANONICAL_ROSTER_CHAIN.md` §14, which lane 1 had already written) found that these five rows significantly
**understate** what already exists on `main` — consistent with the campaign's own repeated lesson to re-measure
at HEAD rather than trust the doc. Leaving them stale risks a future session re-verifying or re-building
already-done work, which is exactly the waste this repair prevents.

**What was corrected, and what was deliberately NOT overclaimed:**
- **`C2-STR-01`** (Team Strength): owner cell corrected from `src/ros/team_strength.py` (a legitimately
  distinct ROS 0-100 production composite, still validly imported elsewhere — NOT one of the "4 competing
  notions" this row is about) to `src/roster_intel/strength.py` (built by lane 1's `#914`, self-declared sole
  owner, confirmed on disk and confirmed via its real importers). **Left as `PARTIAL`, not flipped to
  `COMPLETE`** — whether all 4 originally-competing notions have actually been retired in the new owner's favor
  was not independently re-audited by this correction, and overclaiming that would be its own governance
  defect.
- **`C2-SIM-01`** (roster simulation): "WRONG-OWNER... NOT STARTED" corrected to reflect that
  `src/roster_intel/simulation.py::simulate_roster_change` is a real, tested, lane-1-owned primitive, already
  correctly composed by this lane's own `C3-CAP-01` (`roster_capacity.simulate_final_legal_roster`, proven by a
  9-property structural test), and now also surfaced at `/api/trade/simulate` (Unit 2, this session). Status
  changed `WRONG-OWNER` → `PARTIAL` — not `COMPLETE`, since this is formally a lane-1-owned row and its full
  closure checklist is not this lane's call to make.
- **`C3-PKG-01`** (package generator): owner cell corrected from "*(to create)*" to `src/packages/
  construction.py`, which already exists and is already consumed by 3 of 4 historical generators. Status
  changed from "4 independent generators" to `PARTIAL`, explicitly naming which generator is genuinely
  consolidated (`finder.py`, `angle.py`), which is a real remaining gap (`roster_intel/packages.py` — addressed
  by Unit 4 below), and which is deliberately NOT touched this session (`suggestions.py`, carrying tuned,
  in-code-flagged product logic on a live endpoint).
- **`C3-VA-01`** (Value Adjustment): status changed `DUPLICATED` → `COMPLETE`, since this lane's own Unit 1
  closed the one genuine remaining duplicate this session — this is the one row where `COMPLETE` is warranted
  because the work was done and verified in this same session, not merely discovered.
- **`C3-XMKT-01`** (whole-package market coverage): status changed `DISCONNECTED` → `COMPLETE`, confirmed by
  direct grep of `angle.py`'s imports and the existing AST guard test — no implementation work needed, the prior
  "not rewired" claim simply predated the actual wiring.
- Two prose references in the `C7-BEST-TRADE` external-approval discussion (manifest, ~line 368) that repeated
  the stale "`C3-XMKT-01` disconnected" / "`C3-VA-01` five implementations" claims were also corrected to point
  at the manifest rows above, so a reader following the prose doesn't land on outdated framing after finding the
  corrected table.

**Verification:** documentation-only; no executable test changes behavior. Ran `scripts/
check_planning_integrity.py` (PLANNING INTEGRITY: OK — manifest row count, dependency resolution, evidence
presence, source-family/traceability counts all still consistent), `tests/docs/` (22 passed), and
`scripts/check_product_plan_governance.py` (clean) after the edits to confirm no structural/governance
invariant was broken by the corrections.

**Production impact:** none — text only.

**Duplicates retired:** 0 (this unit corrects records of duplicates already retired by Units 1/2 and by lane 1's
own prior work; it creates no new duplicates and retires none itself).

**Dependencies:** none.

**Blocker:** none.

**Commit SHA:** *(recorded after commit)*

**PR-ready status:** READY_FOR_INTEGRATION — documentation-only, governance checks green, no code touched.

---
