# V1-53 residual — indirect canonical-write guard

2026-08-22. Claude 3 — Season/Scoring/BDVM. Single test file touched, no
production code changed. V1-53 (`C5-ROS-01`) is already `VERIFIED` at L1;
this closes a named residual from its own row, not a reopen of the row's
gate or a change to the V1 tally.

## The residual, verbatim

`docs/VERSION_1_COMPLETION_CONTRACT.md`'s V1-53 row:

> "the ownership guard (`tests/api/test_canonical_ownership_protections.py`)
> is a static syntax scan that catches subscript/attribute writes but not
> indirect construction — a dict literal `{"displayValue": v}`,
> `dict.update(...)`, or `setattr(...)`. Stated as 'inherited, not
> introduced... a candidate for a later strengthening unit, not a V1-53
> blocker.'"

## What was measured before writing any code

`_CANONICAL_WRITE` in the guard file matches `[...] =` subscript
assignment and `.field =` attribute assignment only, for `rankDerivedValue`
and its three proven-identical aliases (`overall`, `finalAdjusted`,
`displayValue`). It does not match a dict-literal key, `dict.update({...})`
(a dict literal passed as an argument — same syntax), or `setattr(obj,
"field", v)` (no `=` at all). All three can introduce a second canonical
producer with zero test failure today.

Before widening, measured what a naive full widening (all 4 names, both
new forms) would actually hit — the same "measure, don't guess" discipline
the file's own prior V1-53 alias-widening comment used:

- **`setattr(...)` with any of the 4 names: zero hits anywhere in the
  repository.** Safe to close fully — pure future-proofing.
- **`rankDerivedValue` as a dict-literal colon key, production sources
  only: exactly two hits.** `src/api/data_contract.py` (the approved
  producer, already exempt) and `server.py` — inside a docstring (the
  `/api/trade/simulate-mc` endpoint's example request body, not executable
  code). Nowhere else. Safe to close for the bare field name, with one
  narrow, counted exclusion for the documented example.
- **The three aliases as a dict-literal colon key: two real production
  collisions, both false positives, both structurally likely to recur:**
  - `src/scoring/backtest.py` — `"overall": {...}` is an unrelated
    statistics-summary section key. "overall" is too generic a word for
    literal colon-key matching to stay precise without an AST.
  - `src/trade/suggestions.py` — `"displayValue": p.display_value` in
    `_serialize_player`. Verified NOT an independent computation: the
    file's own mapping table and `PlayerAsset` construction confirm
    `display_value` is sourced from `row["rankDerivedValue"]` — a
    legitimate read-through republish into a *different* response schema
    (`/api/trade/suggestions`, not `/api/data`'s `values.*`), the exact
    thing W29-F001 fixed. A blanket file-level exemption (the existing
    `APPROVED_CANONICAL_WRITERS` mechanism) would be far too broad here —
    `suggestions.py` is large and actively developed, and exempting all of
    it to excuse one legitimate line would hide a real future violation
    anywhere else in it.
  - Keyword-argument forms (`.update(field=value)`, `dict(field=value)`):
    zero hits anywhere for any of the 4 names. Not worth a separate
    pattern — the real risk (a dict-literal argument to `.update()`) is
    already covered, and a bare `rankDerivedValue\s*=` pattern with no
    `.`/`[` prefix would collide with ordinary local-variable assignment.
- JS/JSX deliberately out of scope: `setattr`/`dict.update(...)` are
  Python vocabulary, and JS's unquoted object-literal keys are a
  structurally worse collision surface (confirmed: one unrelated hit in
  `frontend/app/rosters/page.jsx`, a client-side chart-data scratch array,
  not a canonical write). Named here as a distinct future residual, not
  silently dropped.

## Fix

`tests/api/test_canonical_ownership_protections.py`:

- `_CANONICAL_INDIRECT_DICT_WRITE` — dict-literal colon key, scoped to
  `rankDerivedValue` only (not the 3 aliases, per the measurement above).
  Applied to `.py` files only.
- `_CANONICAL_SETATTR_WRITE` — `setattr(obj, "<name>", ...)` for all 4
  names (measured zero collision risk).
- `_KNOWN_DOC_EXAMPLE_HITS = {"server.py": 1}` — the one documented,
  verified-harmless docstring occurrence, subtracted by count so a
  *second* real hit in the same file still fails.
- New tests: `test_only_approved_modules_construct_the_canonical_value_field_indirectly`
  (whole-repo offender scan, mirrors the assignment-form test),
  `test_the_indirect_write_scan_is_not_vacuous` (pins both what the new
  patterns catch AND the deliberate alias exclusion on the dict-literal
  form — a verified fact, not an unchecked comment),
  `test_the_doc_example_allowance_is_exact` (catches drift if the doc
  example changes shape), and
  `test_no_seasonal_lane_module_constructs_a_canonical_alias_indirectly`
  (the `src/ros/`-scoped complement of the existing seasonal-lane
  assignment-form test — measured zero hits there today).

No production code changed. `src/api/data_contract.py`,
`src/league_intel/overlay.py`, `src/trade/suggestions.py`, and
`src/scoring/backtest.py` are all unmodified — the latter two were
inspected and confirmed benign, not fixed.

## Mutation proof

Inserted a real dict-literal offender (`{"rankDerivedValue": 1}`) and a
real `setattr(_rogue, "displayValue", 2)` call into `src/scoring/backtest.py`
(an unapproved module):

```
FAILED test_only_approved_modules_construct_the_canonical_value_field_indirectly
  src/scoring/backtest.py: 2 occurrence(s)
```

Both the dict literal and the setattr call were caught in one failure.
Restored (clean diff confirmed) → GREEN.

Separately mutated `_KNOWN_DOC_EXAMPLE_HITS["server.py"]` from 1 to 0:

```
FAILED test_the_doc_example_allowance_is_exact
  server.py: expected exactly 0 ... found 1.
```

Confirms the allowance test is not vacuous either. Restored → GREEN.

Full `tests/api/test_canonical_ownership_protections.py`: 24 passed (18
original + 6 new), 0 regressions. `tests/api/` full suite, `ruff format
--check`, `ruff check`, and `scripts/check_planning_integrity.py` all
clean.

## Scope

Single test file (plus this doc) touched. Does not reopen V1-53's own
`VERIFIED` status or move the V1 tally. Does not widen alias coverage for
the dict-literal form (named, reasoned exclusion above) and does not touch
JS/JSX (named, reasoned exclusion above) — both are real, smaller residuals
left explicitly open for a future unit rather than closed by a change that
would introduce false positives. Does not touch V1-51, V1-52, or any other
lane.
