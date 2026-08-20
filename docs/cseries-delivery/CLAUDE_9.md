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

**Commit SHA:** `2a550f02`

**PR-ready status:** READY_FOR_INTEGRATION — documentation-only, governance checks green, no code touched.

---

### Unit 4 — `C3-PKG-01` first real slice: LOCK/EXCLUDE wired into `roster_intel/packages.py`

**Manifest rows:** `C3-PKG-01` (partial progress — the fourth generator's remaining gap). **Status at start,
re-measured at HEAD:** of the four historical package generators, `finder.py` and `angle.py` already fully
consume the shared `src/packages/construction.py` substrate; `roster_intel/packages.py` consumed only the
`package_key` identity helper — **zero** `src.trade.constraints` (LOCK/EXCLUDE, persistent protection)
integration, and a private `_check_legality` duplicating capacity logic `src/trade/roster_capacity.py` already
owns. `suggestions.py` (the live `/api/trade/suggestions` endpoint) is a deliberately separate, larger, deferred
unit — see "Explicitly not touched" below.

**Scoped narrowly and verified safe before writing any code:**
- `TradeAsset` (the type `generate_packages` already uses for `our_assets`) exposes `.asset_id`, `.name`,
  `.position` — exactly what `TradeConstraints._keys_for`'s non-Mapping branch reads
  (`src/trade/constraints.py:129-160`). Zero shape adaptation needed.
- `src/api/gameplan.py`'s only call site (line 1030) passes no `constraints` kwarg today. Making the new
  parameter default to `None` — which `partition_sendable` treats as an unconditional no-op
  (`constraints.py:306-320`) — means the existing caller's output is byte-identical **by construction**, not
  merely by inspection; proven directly by a new golden-comparison test (below), not just asserted.
  `enumerate_packages`'s own `outgoing_policy` mechanism (what `finder.py`/`angle.py` use) was considered and
  rejected for this file: `roster_intel/packages.py` does not call `enumerate_packages` at all — it has its own
  staged 3-stage near-miss search directly over `TradeAsset` lists — so the applicable seam is the simpler
  `partition_sendable`/`blocked_outgoing` (REPORTING + filtering) pair, applied once to `our_assets` before
  stage 1, which every later stage's closures see automatically.

**Delivered:** `generate_packages` gains `constraints: TradeConstraints | None = None`. At function entry,
`our_assets, blocked_outgoing = partition_sendable(our_assets, constraints)` — filtered BEFORE stage 1, so no
later stage's near-miss expansion can ever reintroduce a blocked player (matching the spec's "applied during
generation, before scoring" requirement, never a post-hoc filter of an already-built frontier). The response gains
`constraintsBlockedOutgoing` (count) and `constraintsBlockedReasons` (sorted distinct reasons), naming
consistently with `finder.py`'s existing C3-CON-01 fields for cross-generator consistency. Only the OUTGOING side
is constrained — `their_assets` is untouched, so a protected player on the OTHER roster stays a valid acquisition
target, per spec §2.2.

**A pre-existing test had to be repaired to make this possible, and the repair is itself scoped and justified,
not a side effect absorbed silently:** `tests/roster_intel/test_packages.py::TestCrossMarketIntegration::
test_does_not_depend_on_the_pre_fix_trade_engines` asserted the blunt claim `"src.trade" not in
inspect.getsource(packages)` — a substring ban on the ENTIRE `src.trade` namespace. Its own docstring names a
narrower concern ("finder.py was silently offense-only until recently"), i.e. guarding against depending on the
pre-fix, offense-only trade VALUATION engines (`finder`/`suggestions`/`angle`) — not `src.trade.constraints`,
a different, later-built (2026-08-18), cross-cutting canonical owner that `finder.py` and `angle.py` themselves
already import. Narrowed to an AST import scan checking specifically for `src.trade.finder` /
`src.trade.suggestions` / `src.trade.angle` — the modules the docstring actually names — rather than the whole
package. **Mutation-proven, not merely asserted correct:** temporarily reintroducing a real
`from src.trade.finder import find_trades` line into `packages.py` turned the narrowed guard RED with the exact
offending import named in the failure message; reverting restored GREEN. This is a "fix an incorrect test"
repair, explicitly permitted, not a relaxation of a real invariant — the test still catches the actual defect
class it was written for, proven by the mutation.

**Verification:**
- **RED confirmed before GREEN, by direct reversion:** `git stash`d `packages.py`, ran the four new
  `TestConstraintsWiring` tests against the untouched code — all four failed with
  `TypeError: generate_packages() got an unexpected keyword argument 'constraints'`. Restored — all four pass.
- 4 new tests in `tests/roster_intel/test_packages.py::TestConstraintsWiring`: (1) **golden-fixture inertness
  proof** — `generate_packages(..., constraints=None)` produces a dict `==` to calling without the parameter at
  all, not merely "close" or "shaped the same" (this is the concrete evidence for the "byte-identical by
  construction" claim above, not a restatement of it); (2) a persistently-protected player's id never appears in
  any `send` side across `frontier` + `rejected`; (3) `constraintsBlockedOutgoing`/`constraintsBlockedReasons`
  correctly report the block and its reason (`protected_individual`); (4) protecting a player on the OPPONENT's
  roster leaves every `receive`-side id in `frontier` unchanged between the constrained and unconstrained runs —
  proving the outgoing-only asymmetry the spec requires.
- Full regression: `tests/roster_intel/test_packages.py` — **55 passed** (51 pre-existing + 4 new), 0 failed, 0
  skipped. Broader sweep across `tests/roster_intel/`, `tests/trade/`, `tests/league_intel/`, `tests/api/` run to
  confirm zero cross-package regression (see commit for exact count).
- `ruff format --check` + `ruff check` (pinned `ruff~=0.6.0`) on all three touched files: clean.

**Explicitly NOT touched this session, and why (per the plan's risk assessment, confirmed rather than assumed):**
- `_check_legality`'s cap arithmetic (duplicate of `roster_capacity.py`'s job) — replacing it needs two-sided
  `CapacityContext`s and a `generate_packages` signature change (raw contract/league_key/team, not pre-built
  pools): real surface growth, not a call-site swap, and it raises a live methodology question
  (`roster_capacity.py`'s own docstring: should a generator's hard reject become "accept, report forced-drop
  cost" like the simulator does?) that is a product decision, not composition. Deferred as a separate,
  larger, explicitly-flagged unit.
- The staged 3-stage near-miss search itself, and any migration onto `enumerate_packages`/`PackageShape` — this
  is deliberate, documented product logic (avoiding the expensive lineup re-solve on combinations that cannot
  close the value gap), not behaviorally equivalent to eager enumeration. A migration needs a zero-diff proof
  against the existing 51-test suite at minimum; not attempted here since it is orthogonal to the LOCK/EXCLUDE
  gap this unit closes.
- `suggestions.py` (the LIVE `/api/trade/suggestions` endpoint) — carries deep, tuned, already-shipped product
  logic in its four generator functions (`_generate_sell_high`/`_generate_buy_low`/`_generate_consolidation`/
  `_generate_positional_upgrades`), one of which (`_generate_consolidation`) was read in full and contains an
  in-code comment explicitly flagging a DEFERRED OWNER DECISION (an IDP-universe restriction). Touching this
  live surface without reading all four functions and getting an explicit owner ruling on that flagged decision
  would risk silently relitigating it as a side effect of "consolidation" — forbidden by the no-invented-
  methodology / no-silent-behavior-change constraints. Remains a separate, larger, owner-reviewed unit.

**Production impact:** near-zero, and provably so rather than merely argued. The only production caller
(`src/api/gameplan.py`) passes no `constraints` argument today (confirmed by reading the call site) and the
route itself has zero frontend consumers (confirmed disconnected, per the manifest and direct route-reachability
check). The golden-fixture inertness test makes "near-zero" a proven property of the code, not a claim about it.

**Duplicates retired:** 0 new duplicates created; closes a real gap (missing constraint enforcement) rather than
retiring an existing owner.

**Dependencies:** none blocking — consumes only the already-VERIFIED `C3-CON-01` (V1-34/V1-130) and the
already-existing `src/packages` substrate.

**Blocker:** none. Unit is complete for its declared, narrow scope.

**Commit SHA:** *(recorded after commit — see git log)*

**PR-ready status:** READY_FOR_INTEGRATION — small, self-contained, fully tested (including a mutation-proven
test repair), near-zero production risk proven by a golden-fixture equality test.

**Follow-up — broader cross-package sweep result (completed after commit):** `tests/roster_intel/` +
`tests/trade/` + `tests/league_intel/` + `tests/api/` — **4,180 passed, 43 skipped (all pre-existing), 582
subtests passed, 0 failed**, 518.89s. Zero regressions anywhere in the four directories most plausibly touched
by this unit's change.

---

## Candidate next units (scoped, not started)

Investigated briefly while the Unit 4 regression sweep ran, so the next session (or this one, if it continues)
doesn't have to re-derive the scoping:

- **`C3-TOPO-01`** (generated-trade topology constraint). The mechanical rule
  (`abs(playersA-playersB) <= 1`, picks excluded) is already enforced by `src/packages/construction.py`'s
  `enumerate_packages` for every caller — `enforce_topology` defaults `True` and is never overridden anywhere in
  `src/` (confirmed by grep: the only two occurrences of `enforce_topology` in the whole tree are the parameter's
  own definition and its enforcement site). **But** the manifest's own row asks for something larger than a
  compliance check: it names specific allowed shapes up to `3v2`/`2v3`, and no current generator's `max_per_side`
  reaches 3 — so 3-for-2 packages are not violated, they are simply never *generated*. Closing this row for real
  is a PRODUCT capability change (raising `max_per_side` and wiring the new shapes through at least one live
  generator), not a verification-only unit, and touches `finder.py`/`angle.py`'s live search space — bigger and
  riskier than this session's remaining scope. A genuine near-term slice: a topology-compliance regression test
  proving no *existing* generator can produce a shape violating the rule (this would be verification-only, safe,
  and closes the "topology test" evidence column even before 3v2 capability lands) — not attempted this session,
  named here so it isn't rediscovered from scratch.
- **`_check_legality` → `roster_capacity.py` migration** in `roster_intel/packages.py` — deferred explicitly in
  Unit 4 (see above): needs a two-sided `CapacityContext` and raises a live methodology question about whether a
  generator should reject or report-and-cost an over-cap package.
- **`suggestions.py`'s full `C3-PKG-01` migration** — deferred explicitly in Unit 4: the live endpoint's four
  generator functions need to be read in full (only `_generate_consolidation` has been) and the in-code-flagged
  IDP-universe deferred owner decision needs an explicit ruling before any behavioral change.
- **`C3-CTX-01`** (team-context toggle, V1-41, `NOT STARTED`) and **`C7-DESK-01`** (Analyze Trade, V1-43,
  `NOT STARTED`) remain the next-largest named rows in this lane's scope once the above are resolved or
  deliberately left for a dedicated unit.

---

### Unit 5 — Documentation repair: `C3-TOPO-01`'s mechanism/product split

**Manifest row:** `C3-TOPO-01` in `docs/C_SERIES_SCOPE_MANIFEST.md`.

**Why:** while scoping candidate next units (see above), found `tests/packages/test_construction.py` already
contains a rigorous, complete topology test suite: `test_the_manifest_topology_table_verbatim` pins the exact
9-cell table this manifest row's own `final` column specifies (1v1/2v1/1v2/3v2/2v3 allowed;
3v1/1v3/4v2/2v4 disallowed), plus dedicated tests for the pick-exclusion rule (both directions of the trap —
`test_counting_assets_instead_of_players_gets_two_of_those_backwards`) and `enumerate_packages`'s own
enforcement + refusal reporting. The manifest's `ABSENT` status was therefore conflating two genuinely different
claims into one: the MECHANISM (built, and about as rigorously tested as this codebase gets) vs. the PRODUCT
capability of any live generator actually *offering* a 3-a-side package (verified absent — `finder.py`'s shape
list is hard-capped at `PackageShape(2,1)`/`PackageShape(1,2)`, read directly from the source).

**Correction:** split the row's owner/status text to state both halves precisely, rather than either
overclaiming completion or leaving the already-done mechanism work invisible to the next session. Deliberately
did **not** claim `angle.py` never reaches a 3-a-side shape — its `enumerate_sides` call takes a caller-driven
size, and auditing every call site for whether it can ever reach 3 was out of scope for a documentation
correction; said so explicitly rather than guessing.

**Verification:** documentation-only. `scripts/check_planning_integrity.py` (OK), `tests/docs/` (22 passed).

**Production impact:** none — text only.

**Duplicates retired:** 0.

**Dependencies:** none.

**Blocker:** none.

**Commit SHA:** `bf0de63e`

**PR-ready status:** READY_FOR_INTEGRATION — documentation-only, governance checks green.

---

## Investigation, not a unit: `V1-97` / `C3-REPLAY-01` (Historical Trade Replay does not leak hindsight)

`V1-97` is in the V1 REQUIRED denominator (`docs/VERSION_1_COMPLETION_CONTRACT.md` §3.3, `NOT STARTED`) and its
one dependency, `C1-HIST-01` (the temporal ledger), is CLOSED — so on paper this looked like the next
dependency-ready, in-lane unit after Unit 5. Traced the actual live code before writing anything, and stopped
short of implementing, for a reason worth recording precisely so a future session (or this one, continuing)
does not re-walk the same ground.

**Two genuinely different surfaces exist, and the manifest's description ("current values for missing history,
earliest-known for pre-coverage trades, current pick values; a divergent Hill form back-derives old values")
does not cleanly describe either of them on its own:**

1. **Public activity feed** (`src/api/public_activity_valuation.py` → `src/public_league/activity.py::
   _apply_trade_grades`) — grades EVERY historical trade in the public `/league` timeline using the SAME
   valuation callable built from `latest_contract_data`, i.e. **today's** canonical values, regardless of when
   the trade happened. Confirmed by reading `_apply_trade_grades` and `build_valuation_from_contract` in full:
   there is no date-awareness anywhere in this path. **But** this may not be the defect the manifest names — the
   grade is presented as a plain `{grade, color, label}` badge, not labelled "at-the-time" or "how it aged", so
   it may be a legitimate, honestly-unlabelled "Current Grade" (one of CLAUDE.md's three explicitly legitimate
   questions) rather than a hindsight leak. Did not find where/whether the frontend presents this badge in a way
   that implies contemporaneous judgment — that determination needs a frontend trace this session didn't do.
2. **Private `/trades` page "How It Aged"** (`frontend/lib/trade-retro-value.js` + `frontend/lib/
   value-history.js`, wired in at `frontend/app/trades/page.jsx:405,422-432`) — this is a much closer match to
   the manifest's description. Its own docstring documents that it **previously** broke exactly the four rules
   the manifest complains about (future-observation fallback, missing-as-current substitution, picks priced at
   today's number, incomplete totals compared to complete ones) and states each was fixed. It also states
   explicitly, in its own words: *"That module [`src/history/asof.py`, C1-U4] is also where this computation
   BELONGS... this is a second implementation of the same question. Migrating it is Trade History work, which is
   not currently authorized; refusing to overstate in the meantime is not."* — i.e. the JS module's author
   already identified the real fix (migrate to the canonical `src/history.asof` ledger, which even has a
   docstring naming this exact use case: `value_known_before`'s docstring reads *"Instant-strict as-of lookup for
   at-the-time analyses (C3-U9)"*) and left it undone because C1-U4 wasn't closed yet when it was written. It now
   is. The remaining known-divergent piece is `value-history.js::valueFromRank`'s fallback — an approximate
   frontend Hill-curve reimplementation used only when a historical snapshot has a `rank` but no stamped `val` —
   which is exactly the "divergent Hill form back-derives old values" phrase in the manifest.

**Why this was not attempted as a unit this session:** closing it properly means (a) determining with certainty
whether the public feed's un-labelled current-value grade is or isn't the described defect (needs a frontend
trace not yet done), and, more substantially, (b) for the private `/trades` page, building a new backend
endpoint wrapping `src.history.asof.value_known_before`/`batch_as_of` for a trade's two sides, then rewiring
`trades/page.jsx` off its current `useRankHistory` → `rank_history.jsonl`-sourced `historyLookup` — a real
architecture change to a live, user-facing page, not a bounded wiring fix like Units 2/4. Both need more
certainty than a code trace alone can give before touching a live surface; the risk of guessing wrong here is
real in a way it wasn't for the units actually delivered. Recorded per the campaign's "stop only the affected
unit, continue elsewhere" rule rather than forced through.

**What a real Unit 6 would need, precisely, to pick this up cleanly:**
1. Trace how the public activity `grade` badge is actually rendered/labelled on `/league` to settle question (1)
   above.
2. If (2) is confirmed as the real target: design a small new endpoint (or extend an existing trade-history
   route) that calls `src.history.asof.batch_as_of`/`value_known_before` for a trade's sides at the trade's
   timestamp, returning the same fidelity vocabulary `trade-retro-value.js` already expects
   (`no_prior_observation` / `pick_history_not_recorded` / `undated_trade`, plus the ledger's own `exact`/
   `nearest-prior`/`partial`/`unavailable` labels).
3. Rewire `trades/page.jsx` to consume it instead of `useRankHistory`+`buildHistoryLookup`, preserving
   `gradeRetro`'s existing, already-correct internal logic (its four rules do not need to change — only where
   its `historyLookup` data comes from).
4. A no-hindsight test at the new endpoint (a trade dated before a value moved must never see the post-move
   value) plus a frontend integration test that the page's rendered "aged" badges match the endpoint's fidelity
   labels.

---
