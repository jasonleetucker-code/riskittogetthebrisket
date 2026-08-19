# #913 → finalized Roster mainline — reconciliation map (PHASE A)

> **Measured 2026-08-19 against exact heads.** `main` `c400fec` · #922 `d5539f8`
> (open, **not** an ancestor of main) · #913 `c2153eb` (frozen) · #914 **merged**
> as `37d4c5f`. Reconciliation tree built at `d007ce3` =
> `main + #922 + #913`, coercion baseline regenerated.
>
> **Nothing in this document has been committed to #913 or #929.** It is an
> audit. No compatibility shim is proposed for Phase A, because the only
> guaranteed-correct one (the import rename) is worth nothing on its own — the
> tree still fails #922's ownership guard until the ladder call moves too, and
> those two belong in one commit.

---

## 0. Headline

**`src/trade` imports `src.roster_intel` nowhere.** The name appears in eight
places across `src/trade/` and `src/packages/`, and every one is a comment or a
docstring. There is no Trade→Roster consumption path on #913 today; there is one
to *build*, and #914 §14 names exactly which two calls it is.

Consequences that follow, and that decide the shape of Phase B:

* Q5 has a short answer — **no Trade test skips or mocks the Roster consumption
  path**, because there is no path to mock.
* Q6 therefore cannot be "unskip test X". The proving test has to be **added**,
  and its value is that it fails on the tree as it stands.
* Measured: of the 18 assertions in the rehearsal's proving test, **6 already
  hold and 12 fail** on `main + #922 + #913`. The 6 that hold are the pure
  "no second owner" name guards. Every assertion about Trade *consuming*
  Roster fails.

---

## 1 · Which Roster outputs Trade should consume

`docs/roster-intelligence/C2_CANONICAL_ROSTER_CHAIN.md` §14 is the authority.
It rules `C3-CAP-01` **trade-owned** (one row, one lane — #914's own
`src/roster_intel/capacity.py` was deleted for that reason) and names the two
primitives the roster lane publishes for #913:

| need | canonical call | why Trade must not roll its own |
|---|---|---|
| before → apply → re-solve → after | `roster_intel.simulate_roster_change` | roster effects are **set-dependent**; the displaced player is frequently not the one traded |
| the cheapest LEGAL cleanup of size *k* | `roster_intel.pool_cut_ladder` | the ladder is cheapest-first and its prefixes nest, so the first *k* rungs **are** the optimal legal cut-set — no search, and it is the answer to the shortcut the spec forbids by name (`package delta − lowest raw player value`) |

Two more that Trade needs and that are **not** in §14 because they are lineup-
owner concerns rather than roster-chain ones:

| need | canonical call |
|---|---|
| the league's CONFIGURED flex rule (the rule) | `ros.lineup.configured_slot_eligibility(roster_settings)` |
| the same, resolved from a contract (the plumbing) | `api.data_contract.contract_slot_eligibility(contract)` |

`roster_intel` publishes 36 names. Trade should consume **four** of them, and
should keep consuming zero of `build_meaningful_core` / `build_team_strength` /
`build_team_weakness` / `build_position_ranks` **directly** — those arrive
through `simulate_roster_change`, which already composes them. Reaching past it
to call them itself would be a second population-selection path, which is the
thing `MeaningfulCore`-as-first-parameter exists to prevent.

---

## 2 · Which #913 adapters become unnecessary

Exactly one, and it is a *door*, not a duplicate implementation:

| #913 today | after reconciliation | note |
|---|---|---|
| `from src.draft.displacement import build_cut_ladder` → called directly | `from src.roster_intel import pool_cut_ladder` | both reach ONE owner, so this is not a second ladder — but #922 threaded `slot_eligibility` through the **adapter only**, and #914's guard asserts an exact three-file caller set that a direct call breaks |

Everything else #913 consumes stays, and stays correct:

* `draft.context.build_roster_assets`, `_league_scarcity`, `_norm` — contract→asset plumbing, unchanged
* `draft.displacement.RosterAsset`, `waiver_values_by_position` — unchanged, and `waiver_values_by_position` has no `roster_intel` door to move to
* `ros.lineup.flatten_starter_slots`, `load_league_starter_slots` — unchanged
* `roster_capacity`'s own `_surviving_keys` / `_outgoing_held` / taxi bracketing / forced-drop accounting — **trade-owned by the manifest**, not adapters, and not superseded

**No adapter is deleted.** The reconciliation is additive plus one door swap.

---

## 3 · Names and signatures that changed

Audited every `src/trade` import of a Roster-owned module against the
reconciled tree. **17 imported names; 16 resolve; 1 does not.**

### Breaking — exactly one

```
src/trade/roster_capacity.py:103
    from src.draft.context import _index_contract_rows   ← gone
                                  index_contract_rows    ← #914 made it public
```
The merged tree **does not import at all** until this is fixed. One line, plus
its single call site.

### Additive — nothing to do, but this is what became available

| symbol | #913's base `960ac24` | reconciled |
|---|---|---|
| `displacement.build_cut_ladder` | *(no `slot_eligibility`)* | `+ slot_eligibility: Mapping[str, Collection[str]] \| None = None` (keyword-only, defaulted) |
| `lineup.configured_slot_eligibility` | absent | `(roster_settings)` |
| `lineup.is_priced` / `priced_players` | absent | new |
| `data_contract.contract_slot_eligibility` | absent | `(contract)` |
| `roster_intel.pool_cut_ladder` | file absent | `(pool, starter_slots, waiver_values, *, scarcity, slot_eligibility, max_rungs)` |
| `roster_intel.simulate_roster_change` | file absent | `(pool, starter_slots, *, incoming, outgoing_ids, ranks, team_count, slot_eligibility, config)` |
| `roster_intel.build_meaningful_core` / `build_team_strength` / `build_team_weakness` / `reserve_demand` | file absent | new |

Every added parameter is keyword-only with a default, so **no existing #913
call site breaks on signature grounds**. The one break is the rename.

---

## 4 · Is roster capacity's ownership boundary still clean?

**Yes, and it is measured rather than asserted.** Six structural guards pass on
the reconciled tree with #913 exactly as it is:

| guard | result |
|---|---|
| no `src/trade` module DEFINES any of 12 `ros.lineup` names | PASS |
| no `src/trade` module DEFINES any of 16 `roster_intel` names | PASS |
| no `src/trade` module DEFINES any of 8 cut-ladder / replacement names | PASS |
| no `src/trade` module holds a private slot→positions table | PASS |
| an unknown roster limit stays UNKNOWN | PASS |
| an unpriced forced drop stays `null`, counted separately | PASS |

The boundary is clean in the *negative* direction — Trade has not reimplemented
anything. It is empty in the *positive* direction — Trade consumes none of the
new owners either. Those are different facts and only the first is currently
true of the code.

One genuine boundary violation exists and is Trade-owned, found while
rehearsing (F1): **`team_impact.project_starters` calls
`assign_lineup(pool, slots)` with no `slot_eligibility`** while holding
`roster_settings`. So `teamImpact` on `/api/trade/simulate` is modelled under
the *declared default* flex rule while the capacity path (after the door swap)
uses the *configured* one — two Trade modules disagreeing about one roster the
moment a league narrows a flex. Same defect class as the one #922 repaired at
the ladder. A second instance (F2): `suggestions._starter_needs` builds a
private two-entry override map from `flexEligible` / `idpFlexEligible`,
**omitting `sflexEligible`** — and C2-U1's own `configured_slot_eligibility`
docstring names that module as the "two-entry variant" it exists to replace.

---

## 5 · Which tests currently skip or mock the Roster consumption path

**None.**

* 22 tests skip across `tests/roster_intel tests/lineup tests/trade tests/packages tests/draft`. **All 22 are in `tests/roster_intel/test_real_rosters.py`**, gated on `nfl player dump not present in this checkout` — a missing data file in the Roster lane, unrelated to Trade and not unskipped by this reconciliation.
* **Zero Trade tests skip.**
* The only `monkeypatch` in a Trade test that touches anything nearby is `tests/trade/test_roster_capacity.py::test_league_caps_fall_back_to_the_registry`, which stubs `league_registry.get_league_by_key` — a **config lookup**, not a Roster owner. Legitimate; leave it.

The honest framing: the consumption path is not mocked away, it is **absent**.

---

## 6 · The exact tests that must be unskipped / must go green

Two, and neither is currently satisfiable:

1. **`tests/roster_intel/test_droppability.py::test_the_cut_ladder_owner_has_exactly_two_callers`** — #922's own guard. It asserts the caller set is exactly `{draft/displacement.py, draft/context.py, roster_intel/droppability.py}`. On `main + #922 + #913` it is **RED** with a fourth entry, `src/trade/roster_capacity.py`. This is the single test that proves the door swap happened; it goes green when and only when Trade stops calling `build_cut_ladder` directly.

2. **`tests/trade/test_trade_consumes_roster.py`** — must be ADDED, unskipped, not `livedata`. 18 assertions over nine properties. Measured on the reconciled tree with #913 as-is: **6 pass, 12 fail.**

   | property | status on raw #913 |
   |---|---|
   | P2/P3/P4 no-second-owner name guards (×3) | PASS |
   | P2 no private slot→positions table | PASS |
   | P6 unknown limit stays UNKNOWN | PASS |
   | P7 unpriced drop stays null | PASS |
   | P1 configured flex reaches the cut path (×3) | **FAIL** |
   | P4 the ladder is reached via the adapter | **FAIL** |
   | P1b configured flex reaches `team_impact` | **FAIL** |
   | P1c no trade module reads the registry's flex keys | **FAIL** |
   | P5 a forced drop is never also retained (×2) | **FAIL** |
   | P8 before→apply→re-solve→after order, and the cascade (×4) | **FAIL** |

   P9 is discharged separately by `scripts/rehearsal_prove_trade_consumes_roster.py`, which breaks each seam in place and requires RED: **12/12 mutations caught.**

---

## 7 · The Phase B change set, in commit order

Rehearsed and green on `claude/v1-trade-roster-rehearsal-2` (`2c59f18`), which
is **evidence only — no PR, never a merge candidate**. Replay onto the
reconciled #913 rather than merging that branch's ancestry.

| # | change | file | why it is not optional |
|---|---|---|---|
| W0 | `_index_contract_rows` → `index_contract_rows` | `roster_capacity.py` | the tree does not import without it |
| W1 | `build_cut_ladder` → `pool_cut_ladder`; `CapacityContext.slot_eligibility` resolved via `contract_slot_eligibility` | `roster_capacity.py` | turns #922's guard green AND is the only route that carries the flex rule |
| W2 | thread `configured_slot_eligibility` into `team_impact.project_starters` / `_needed_at`; replace `suggestions`' private override map | `team_impact.py`, `suggestions.py` | F1 / F2 above |
| W3 | `simulate_final_legal_roster` — apply the required cleanup, re-solve via `simulate_roster_change` | `roster_capacity.py` | the last two steps of C3-CAP-01's own sequence; §14's first primitive |
| — | the proving test + the mutation harness | `tests/`, `scripts/` | P9 |

**W0 and W1 must land in one commit.** W0 alone leaves #922's guard red, so a
tree with only W0 is not a valid stopping point.

---

## 8 · Blockers and non-blockers

**Blocking Phase B:** #922 is open and not merged. Everything above is measured
against `main + #922`, so any change to #922 before it lands re-opens §3.

**Not blocking, already resolved:** the `config/coercion_baseline.json` conflict.
Both lanes deleted **disjoint** sets from a generated census — ancestor 674,
main 670 (#914's 4), #913 668 (its own 6), merged tree **664**. Regenerate with
`python scripts/check_decision_coercions.py --write-baseline` (the flag is
`--write-baseline`; `--rebuild` is unrecognized and exits 2). Verified twice, on
two different mains, both giving 664. No content decision required.

**Named, not fixed:** `team_impact.lineup_displacement` is a **second**
before/apply/re-solve/after diff beside `roster_intel.simulation`. Not a
duplicate solver — both call `assign_lineup` — and on a fixture they agree on
the fact, but `roster_intel`'s is strictly richer and nothing holds them in
lockstep. Consolidation is `V1-42` / `C7-DESK-01` territory and is outside
`C3-CAP-01`'s authorization.

**Owner-lane observation, not compensated for locally:**
`lineup.slot_eligible_positions(slot)` accepts no configured override, so
`team_impact._positions_for` answers "which positions can this league start"
from the declared defaults. That belongs to the lineup owner.
