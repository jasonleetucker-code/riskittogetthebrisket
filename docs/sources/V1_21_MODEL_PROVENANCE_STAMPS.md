# V1-21 — Model provenance stamps (W04-F011)

**Status: FEATURE_GREEN / READY_FOR_INTEGRATION.** Provenance truthfulness
only — no source weight, bridge qualification, rank-to-value translation,
calibration constant, player value, source voting, or authentication policy
changed by this unit.

## Census: every production model-derived / fallback-model-derived output

| Producer | Endpoint(s) | Provenance today |
|---|---|---|
| BDVM (fundamental valuation) | `/api/bdvm/*` | **Already correctly stamped** — `modelVersion` (`src/bdvm/__init__.py::MODEL_VERSION`), `paramSetId` (content hash, `src/bdvm/params.py::ParamSet`), `configHash`, `asOf` (`src/bdvm/service.py`) |
| Consensus Edge | consensus-edge routes | **Already correctly stamped** — `modelVersion` (`src/consensus_edge/__init__.py::MODEL_VERSION`), `paramSetId` (content hash, `src/consensus_edge/params.py` — its own docstring: *"lifted from `src/bdvm/params.py` deliberately... a second [convention] would be a drift risk, not a feature"*) |
| League-adjusted valuation overlay | `GET /api/valuation/league-adjusted` | Already carries its own `MODEL_VERSION` (`src/league_intel/values.py`) — out of scope for this unit's residual (not cited by W04-F011, not touched) |
| **Canonical board — Hill scope masters** (drives every `rankDerivedValue` on `/api/data`) | `/api/data`, and everything downstream that reads `rankDerivedValue` | **THE RESIDUAL GAP, closed by this unit.** Refit weekly, promoted/rolled-back via `src/model_registry/` (a real, pre-existing champion/challenger/rollback system — `config/model_registry/hill_scope_masters.json`), but that package's own docstring stated it "does not change what any live endpoint returns" — **nothing under `src/api` ever read it.** `hillCurves` stamped the raw `c`/`s` constants and nothing identifying which champion produced them. |
| `rank_to_value_for_scope` (`src/canonical/player_valuation.py`) — a genuinely separate, separately-calibrated **fallback** curve (`HILL_MIDPOINT`/`HILL_SLOPE`, `IDP_HILL_MIDPOINT`/`IDP_HILL_SLOPE` — different constants from the scope masters above) | `src/api/rank_history.py` (legacy log entries that persisted a rank but not a value) and `src/api/terminal.py` (dormant — 0 of 740 rows on the live payload) | **Adjacent, NOT cited by W04-F011, NOT fixed here.** A value reconstructed through this fallback carries no marker distinguishing it from a real stored/live value in either consumer's output shape. Flagged explicitly for Claude 5 as a separate, smaller, currently-dormant gap — fixing it would broaden V1-21 into a second unit the contract does not ask for. |

Inventory item 7.12's own one-line status is the exact scoping signal that
was verified against current code, not assumed: *"BDVM stamps well; the
main board does not (W04-F011)."*

**Canonical provenance vocabulary — reused, not invented.** `modelVersion` /
`paramSetId` / `asOf` is already the established convention across BDVM and
Consensus Edge (`paramSetId` = a content hash of the parameter set, per both
modules' own stated rationale). This unit gives the Hill-master pipeline the
same three fields, sourced from the SAME pre-existing `src/model_registry`
package everyone already trusted to record champion/version history — not a
fourth scheme.

**Residual classification:** (A) a real producer (the canonical board)
omitted required provenance. Not (C)/(D)/(E) — nothing today mislabels a
fallback as native, nothing labels an unavailable result as real, and no
second incompatible vocabulary exists; BDVM/Consensus Edge and this fix
speak the same three-field shape.

## What changed

1. **`src/api/data_contract.py`** — new `_hill_master_provenance()`, wired as
   `hillCurves["provenance"]`. Read-only: loads
   `config/model_registry/hill_scope_masters.json` via the existing
   `ModelRegistry.load()`, compares its recorded CHAMPION's params against
   the live constants actually imported from `player_valuation.py`, and
   reports exactly one of three honest states:
   - `"verified_champion"` — live constants byte-match the champion exactly.
     Stamps the real `modelVersion` (int), `paramSetId` (content hash,
     `hill_scope_masters:<sha256[:16]>`), `asOf` (promoted/fitted date),
     `fittedAt`, `producer`, `qualified`, `confidence` — all read straight
     off the `ModelVersion` dataclass already defined for this purpose.
   - `"unverified"` — constants exist but do NOT match any recorded
     champion (e.g. an edit to `player_valuation.py` that skipped
     `promote()`/`apply()`). `modelVersion`/`paramSetId` are `None`, never a
     stale or guessed version number, with the mismatch named in `reason`.
   - `"unavailable"` — the registry file is missing, corrupt, or has no
     champion at all. Same `None`/`None` shape, reason named. The except
     clause is deliberately broad (`RegistryError`, `OSError`, `ValueError`,
     `KeyError`, `TypeError`) so a malformed registry file degrades this ONE
     diagnostic field rather than crashing the entire `/api/data` build.
2. **`src/model_registry/__init__.py`** — one-paragraph docstring correction:
   the package no longer has zero live-endpoint consumers; the new consumer
   is read-only and stamps metadata only, so the package still computes
   nothing and still owns no valuation math (the load-bearing half of the
   original claim is unchanged).
3. **`src/history/provenance.py`** — companion fix, found during this unit's
   own downstream-consumer trace (not part of the original defect, a
   consequence of fixing it). `pipeline_version()` — the temporal ledger's
   (C1-U4) board-identity keying — hashed the ENTIRE `hillCurves` dict
   verbatim to detect when value-determining Hill constants change (its own
   docstring: *"a version that cannot change is not a version"*). Adding
   `hillCurves["provenance"]` put descriptive metadata (which model
   produced the constants) inside that hash, so a purely cosmetic future
   registry correction (e.g. backfilling champion v2's currently-null
   `appliedAt` — see below) would spuriously move this identity with no
   curve constant changing at all. Fixed by scoping the hash to the four
   known scope-curve keys (`global`/`offense`/`idp`/`rookie`) explicitly,
   excluding `provenance` and any other future non-curve key defensively.
   Not a valuation/calibration change — a bookkeeping fix inside a
   different module's own existing responsibility (history/provenance
   keying, not Hill curves themselves).
4. **`tests/api/test_data_contract.py`** — `TestHillCurvesStamp`'s exact-key
   assertion updated to include the new `"provenance"` key; new
   `TestHillMasterProvenanceStamp` (6 tests): the positive control (real
   board, real champion, real stamp), a `paramSetId` stability check, and
   four negative controls (missing registry, no champion, corrupt file,
   drifted constants) each asserting the honest degraded state rather than
   a fabricated one.
5. **`tests/snapshots/test_board_store.py`** — new
   `test_a_non_curve_metadata_key_does_not_move_the_version`, pinning the
   `pipeline_version()` fix directly: a `hillCurves` block with and without
   a `provenance` sub-key must hash identically.

**Measured live**, against the real committed registry (champion v2,
promoted 2026-07-29): the served stamp today is genuinely
`{"status": "verified_champion", "modelVersion": 2, "paramSetId":
"hill_scope_masters:b131caf5273d88b4", "asOf": "2026-07-29T23:35:35...",
"producer": "scripts/fit_hill_curve_percentile.py @ 3df9cc4", "qualified":
true, "confidence": "measured"}` — the live constants really do match the
registry's recorded champion exactly, so this is not a hypothetical; the
board has real, verifiable provenance today for the first time.

**One pre-existing, separately-flagged observation (not fixed here, out of
scope):** champion v2's own `appliedAt` field is `null` despite its params
being demonstrably live — the `promote()`/`apply()` split was never
recorded as completed for this version, even though it plainly was. Not
remediated here: fabricating an `appliedAt` timestamp would be exactly the
class of coercion this whole unit exists to prevent, and the comparison
this stamp performs (live constants vs. champion params) does not depend on
`appliedAt` being populated. Left for whoever owns `src/model_registry/`'s
data hygiene. (This is also exactly the scenario the `pipeline_version()`
fix above protects the temporal ledger against, should someone backfill it
later.)

## Downstream consumer check (verified, not assumed)

`frontend/components/graphs/HillCurveExplorer.jsx::normalizeCurves` iterates
every key in the `hillCurves` object generically, but every entry — known
or not — passes through `isRenderableCurve`, which requires positive finite
`midpoint`/`slope`. The new `"provenance"` entry has neither, so it is
structurally filtered out before rendering; confirmed by reading the
component's actual filter logic, not assumed. `frontend/app/rankings/page.jsx`
passes the whole `hillCurves` object straight through with no other
consumer. `src/history/provenance.py::pipeline_version()` was a real
consumer that DID need a fix (above). The frontend vitest suite could not
be executed in this sandbox (`node_modules` not installed — an environment
limitation, not something this unit's change caused); the safety property
above was verified by direct code reading instead.

## Required L1 mutation proofs

Both performed on the real file, confirmed RED, reverted, confirmed GREEN
(`git diff --stat` empty afterward each time):

| # | Mutation | Shape | Result |
|---|---|---|---|
| 1 | Removed the `if not matches:` early return in `_hill_master_provenance`, letting drifted constants fall through to the verified-champion branch | "label fallback/drifted output as real" | `test_drifted_constants_report_unverified_not_the_stale_champion` RED (`'verified_champion' != 'unverified'`) |
| 2 | Changed the no-champion branch to return a fabricated `modelVersion: 999` / `paramSetId` / `asOf` instead of `None`/`None`/`None` | "assign model provenance to a genuinely unavailable result" | `test_no_champion_reports_unavailable` RED (`'verified_champion' != 'unavailable'`) |
| 3 (companion fix) | Reverted `pipeline_version()` to hash the whole `hillCurves` dict verbatim | "provenance metadata silently moves an unrelated identity" | `test_a_non_curve_metadata_key_does_not_move_the_version` RED (`'...+d8a0f137' != '...+db1b689f'`) |

Restored after each; `TestHillMasterProvenanceStamp` 6/6 and
`TestPipelineVersion` 5/5 green again.

**Positive control 1 (real model-derived result, survives to the
consumer):** `test_the_live_board_stamps_a_real_verified_champion` —
today's real board, real champion match, real `modelVersion`/`paramSetId`/
`asOf`, confirmed present on the built contract.

**Positive control 2 (genuinely unavailable stays unavailable, never a fake
stamp):** `test_a_missing_registry_reports_unavailable_not_a_guessed_version`,
`test_a_corrupt_registry_file_degrades_to_unavailable_not_a_crash`,
`test_no_champion_reports_unavailable` — all three assert `modelVersion is
None`, never a fabricated or nearest-looking version number.

**Positive control 3 (fallback/drifted stays distinguishable from
native):** `test_drifted_constants_report_unverified_not_the_stale_champion`
— constants that no longer match any registered champion report
`"unverified"`, never the champion's stale version number.

## Verification

- `tests/api/test_data_contract.py` (`TestHillCurvesStamp` +
  `TestHillMasterProvenanceStamp`) — 9/9 passed.
- `tests/snapshots/test_board_store.py` — 14/14 passed (includes the new
  `pipeline_version()` regression test).
- `tests/model_registry/`, `tests/canonical/test_hill_percentile_constants_tripwire.py`,
  `tests/canonical/test_rank_form_constants_tripwire.py`,
  `tests/api/test_rank_form_frontend_parity.py`,
  `tests/api/test_source_registry_parity.py`,
  `tests/api/test_source_overrides.py` — combined with the two files above,
  302 passed.
- `ruff check` on every changed file — clean.
- `scripts/check_decision_coercions.py` — clean, no new coercions.
- `scripts/check_planning_integrity.py` — clean, all invariants hold.
- Full suite `pytest tests/ -q -m "not livedata"`, run once in a clean
  process with no concurrent file edits — see commit for the exact count.
  (An earlier background run, taken while files were still being edited,
  surfaced 2 unrelated `inspect.getsource`-based failures in
  `test_te_basis_conversion.py`/`test_te_premium_invariants.py`; both were
  confirmed, by immediately re-running them standalone, to pass cleanly —
  a stale-import artifact from editing `data_contract.py` while a
  long-running pytest process already held it imported, not a real defect.
  Not present in the final clean run.)

## Deliberately NOT done

No change to source weights, bridge qualification, rank-to-value
translation, calibration constants, player values, source voting, or
authentication policy. No promotion/rollback performed on
`hill_scope_masters` — the champion is read, never written. No fix to the
`rank_to_value_for_scope` fallback-reconstruction gap (flagged above,
separate unit). No edit to `docs/VERSION_1_COMPLETION_CONTRACT.md` (the
canonical V1 ledger) — status promotion is Integration's call. No merge
performed. V1-133/134/135/136, bridge weighting, source weights,
cross-position translation, and Hill calibration are untouched and not
reopened. Issue #958 untouched.

**FEATURE_GREEN / READY_FOR_INTEGRATION. FREEZE.**
