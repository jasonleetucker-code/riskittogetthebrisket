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

**Commit SHA:** *(recorded after commit)*

**PR-ready status:** READY_FOR_INTEGRATION — small, self-contained, fully tested, zero production value change,
no dependency on any other in-flight unit.

---
