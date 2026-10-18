# Draft valuation Batch G — pre-deploy verification evidence (2026-10-18)

Scope: the parts of Batch G (`DRAFT_VALUATION_WORKSTREAM.md`, PROMPT G) that can
be proven before release train 8 (#1809, carrying Batches E #1802 and F #1806)
merges. Production deploy, the desktop 1440 / mobile 375 smoke and the rollback
drill come after the train merges and are NOT part of this record. `dynasty_main`
only (owner scope correction 2026-10-18). Branch `claude/draft-valuation-batch-g`,
stacked on `integration/train-8-2026-10-18`.

## Result

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Independent checker (no production imports) over the pinned golden and every generated class (2027 / 2028 / 2029) | **PASS** — 66 PASS, 0 FAIL; exact whole-dollar parity, no difference | `scripts/check_draft_valuation_independent.py`; `tests/draft_valuation/test_batch_g_independent_checker.py` |
| 2 | Adversarial dataset (ties, missing rookies, < 72 rookies, duplicate names, rising values, stale / unknown class year, malformed workbook, missing spine, traded pick with unknown ownership, refused board, stale-while-revalidate boundaries) | **PASS** — 43 tests; one defect found and fixed (below) | `tests/draft_valuation/test_batch_g_adversarial.py` |
| 3 | As-of replay from the stored ledger + receipts, byte for byte; no future input selectable | **PASS** — 2027 / 2028 / 2029 reproduce byte for byte; a class completed, a record effective, inputs effective and a pointer written after `as_of` are all excluded | `src/draft/rookie_auction/replay.py`, `scripts/draft_valuation_replay.py`; `tests/draft_valuation/test_batch_g_replay.py` (16 tests) |
| 4 | Read-only Sleeper reconciliation of the 216 `dynasty_main` pick ids | **PASS** — live run 2026-10-18T19:51Z, 10 PASS / 0 FAIL against the production board | `scripts/reconcile_draft_capital_sleeper.py`; offline tests `tests/draft_valuation/test_batch_g_sleeper_reconciliation.py` |
| 5 | Dead tests in `tests/api/test_draft_capital.py` | **PASS** — repaired: 15 skipped → 0 skipped, 20 passed | fixture repair below |
| 6 | Staged rollout, exact-head CI of the merged train, deploy, desktop 1440 / mobile 375 smoke, rollback drill | **NOT_TESTED** — post-merge, outside this batch's pre-deploy scope | — |

## 1. Independent checker

`python3 -I scripts/check_draft_valuation_independent.py --production <dump>`
imports only the standard library. Its one code dependency is the Batch A
literal transcription (`tests/draft_valuation/reference_workbook_formulas.py`:
cell-by-cell IEEE doubles with spreadsheet semantics), loaded by file path and
refused if it ever imports anything but `math` / `re` / `fractions`. Everything
else is data: the workbook fixtures, the owner package goldens, and the tracked
snapshots under `config/draft_valuation/`. The production side is a read-only dump
(`scripts/draft_valuation_dump_production.py`, `persist=False`).

What it proves:

* provenance — the fixtures are the owner workbook (sha256 `50d130e5…dce88`); the
  frozen inputs equal column B exactly; the 2024 / 2025 / 2026 completed-class
  snapshots equal workbook columns G / F / H exactly; every snapshot checksum
  recomputes;
* golden — the transcription reproduces the workbook's cached column L and the
  package goldens L and D 72/72; the owner's earlier-pick-first tie rule equals
  the literal sheet rule on the workbook; production's curve over the same
  inputs equals it in half dollars and whole dollars;
* per class (2027 / 2028 / 2029) — its own spine (the three completed classes on
  file before the class: 2024 / 2025 / 2026 for all three today), its own curve
  and whole dollars; production's served half dollars, whole dollars, spine and
  record all equal it exactly; the stored record equals it; the whole dollars are
  the lexicographically largest minimum-deviation answer (a forward DP bounded by
  the step-A deviation finds nothing better); every class $1,200, All Years $3,600;
* double precision — every integer decision clears double noise (floor margin
  and award-cutoff margin > 1e-9); inside the noise would be a FAIL.

**Production vs independent: no difference** on the golden or on any class.
Mutation probes (a dollar moved within a class, a half dollar changed, a wrong
spine, another record's checksum, a golden dollar, a `last_known_good` state)
each make it FAIL and name the check.

## 2. Adversarial dataset

Every case fails closed with an explicit state — never $0, never another year's
curve:

| Case | Explicit state |
|---|---|
| all 72 rookie values tied | deterministic curve, equal to the transcription (a defined answer, not a refusal) |
| tied whole-dollar remainders at the cutoff | earlier pick first (`[3, 3, 2, 2]` for 4 x $2.50 → $10) |
| tied board values, shuffled rows | identical class order every time |
| a missing rookie value | candidate failure "missing is never zero" → that year's `last_known_good`, else `unavailable` (`final_whole_dollars: None`) |
| 71 rookies | same, "expected 72 rookie values, got 71"; class snapshot `NOT_READY insufficient_eligible:71/72`; ladder `inputs_incomplete` |
| zero / missing board value | excluded `no_positive_value`, class `NOT_READY` |
| two records, one name, no id | `NOT_READY duplicate_identity:name:…`, neither chosen |
| same name, distinct player id | a different player (kept) |
| a rising rookie list into the ladder | **was priced** → now refused `inputs_not_ranked:value_rises_at_N` (finding below) |
| a rising input to the formula itself | non-increasing $1,200 curve, equal to the transcription |
| retired class | `unavailable draft_class_retired` |
| class with no spine on file (2026) | `unavailable`, `SpineUnavailableError` named — never 2027's curve |
| candidate for another year | `unavailable draft_year_mismatch:2027!=2028` |
| stored record of another formula version | `unavailable stored_allocation_formula_version_mismatch` |
| unprovable / other class year | excluded (`class_unprovable:*`, `other_class`) |
| unconfigured league | `unavailable league_not_configured:dynasty_new` |
| missing / tampered spine class, tampered baseline | that year's `last_known_good` with the reason, else `unavailable` |
| unreadable workbook | board `error: Draft data workbook not found or empty` |
| workbook dollars not totalling the pool | board `draft_dollars_refused`, `conflict: sum_not_total` |
| `/traded_picks` failed or not a list | board `pick_ownership_unavailable`, no picks, no team totals |
| generation failed, no record | board `draft_dollars_unavailable` with `draftYear` and the receipt |
| generation failed, record on file | board served from that year's `last_known_good`, $1,200 exact |
| stale-while-revalidate | served at exactly the 6 h budget, refused 1 ms later; never another year, a bool / string / missing year, an ownership or Sleeper refusal, or without a last valid board |

**Finding (fixed).** `generation.rookie_ladder` (Batch F) priced ANY order: a
list whose value rises would hand a weaker rookie a stronger pick's dollars. It
now refuses with the position (`inputs_not_ranked:value_rises_at_N`), as the
owner package's caveat asks ("intended new input ranking should be explicitly
sorted") and as `_parse_csv_rookies` already refuses a rising list. The live
pool (`select_rookie_rows`, sorted by value) never trips it: on the pinned
2026-10-18 export the 72-rookie ladder still computes with the same dollars, so
no served value changes. One Batch F test fed the raw column B (16 ascending
pairs) to the ladder as parity evidence; it now feeds a ranked list and is pinned
against the independent transcription, and a new test pins the refusal on the raw
column B. The formula over column B as the sheet holds it stays pinned by
`test_frozen_snapshots.py::test_curve_from_frozen_inputs_reproduces_the_workbook_exactly`.

## 3. As-of replay

`replay_generation(league, year, as_of)` selects only what existed at `as_of`:
the newest verified record effective at or before it; the spine through
`ledger.replay_spine(as_of=…)` (a generated class counts only once its completion
was observed); the frozen inputs only if their effective date (read as 00:00 UTC
— the file states a date) is on or before both `as_of` and the record; a
promotion pointer written at or before `as_of` is refused
(`promoted_generation_replay_not_supported`; none exists today), one written
after is ignored. It verifies every receipt in the record against that evidence,
recomputes through the canonical code over an as-of view of the ledger, rebuilds
the record with the canonical resolver into a temporary store and compares bytes.

* 2028 and 2029 (`source: rookie_auction_curve`): provenance RECOMPUTED (curve id,
  checksums, curve receipt hash) — byte-identical;
* 2027 (workbook-derived seed): provenance carried verbatim after every receipt in
  it (inputs snapshot hash, frozen inputs checksum, spine years and checksums,
  workbook sha256, input class year) verified — byte-identical;
* future inputs: with a 2027 class finalized (completion 2027-05-20) and a later
  2028 record (2027-06-01) on file, 2028 as of 2026-10-18 still replays the seed on
  2024–2026 byte for byte and lists the later record as excluded; as of 2027-06-02
  the later record replays byte for byte on 2025–2027; as of 2027-05-25 the record
  in force was built on a spine that has since rolled — reported `differs` with
  both spines named.

## 4. Sleeper reconciliation (live, read-only)

`python3 -I scripts/reconcile_draft_capital_sleeper.py` — GET only, stdlib only.
Run once, 2026-10-18T19:51Z, against the production served board
(`https://chaseupside.com/api/draft-capital?leagueKey=dynasty_main`) and Sleeper
league `1312006700437352448`:

```
PASS  Sleeper league shape 12 rosters x 6 rounds
PASS  board names three classes
PASS  Sleeper /traded_picks is an observation (a list)
PASS  216 unique identities on the board
PASS  board identities = Sleeper fold
PASS  every current owner = Sleeper fold
PASS  every origin roster = the identity's origin
PASS  isTraded = holder differs from origin
PASS  owner names = Sleeper team names
PASS  no team publishes unavailable pick ownership
INFO  summary  [classes [2027, 2028, 2029]; 216 picks; 83 held by a non-origin roster]
10 PASS, 0 FAIL
```

Production serves `main` (before train 8), whose 2028 / 2029 dollars are still
the interim curve; ownership does not depend on the dollar curve. The same
reconciliation on a board built locally from this branch with live Sleeper:
10 PASS / 0 FAIL, and the Batch E checker (`scripts/check_draft_capital_multi_year.py`)
36 PASS / 0 FAIL on it.

## 5. The 15 skipped tests in `tests/api/test_draft_capital.py`

**Cause: a fixture gap, not retired behaviour.** The suite's conftest configures
no league (no live Sleeper). Since Batches E/F the workbook class is priced only
through the canonical reader for a CONFIGURED league's upcoming class, so
`_fetch_draft_capital` answered `draft_dollars_unavailable`
(`league_not_configured:`, draft year = the calendar year) and each test turned
that error into a skip — reported as "Workbook unavailable" although the workbook
was present (the four parsing tests in the same file pass). Some tests also
stubbed a not-yet-drafted current-year class, which has no spine and no record.

**Repair.** One hermetic harness, `_dynasty_main_league`: the stubbed Sleeper
league maps to `dynasty_main`; no live Sleeper, no live KTC, no stored draft-class
evidence; the league as it is between drafts (this season's rookie draft complete
and rostered, so the workbook class is next season's and the slot map comes from
the completed draft). A builder error is now a FAILURE, not a skip.

* `TestApiOutput` (3), `TestTeamTotalsMirrorSheet` (1): run on the hermetic league.
  One assertion read the flat `total` / `floored` receipt of
  `workbook_class_whole_dollars`, which since Batch F serves only a workbook of
  another size (pinned by `test_draft_capital_all_years.py`); it now reads the
  served record's `validation.apportionment` and verifier.
* `TestSleeperTradeOverlay` (3): the traded-pick test uses the retired-draft model
  (the traded pick is in the upcoming class); the other two needed only the league.
* `TestLiveStandingsOverride` (8): its PF-only premise ("fewest fpts → slot 1") is
  retired — the reshuffle follows the league rule `reverse_record_lower_pf`, pinned
  by `test_draft_capital_multi_year.py::test_standings_to_date_are_a_labelled_forecast_by_the_owner_rule`
  and `::test_verified_final_standings_are_the_rules_order`. What the class still
  owns — slot-bridge consistency under any reshuffle (untraded never flagged
  traded, a trade follows its roster to the new slot, partial / empty / mis-keyed
  bridges and unbridged extra rosters never reshuffle, duplicate display or first
  names) — is current code, so the fixture now supplies records
  (`_reverse_standings`: worst record = roster 12, PF agreeing) and the
  discriminating assertions are unchanged.

Result: 20 passed, 0 skipped (was 5 passed, 15 skipped).

## Gates (committed files)

* `bash scripts/format_python_changes.sh` — GREEN (Ruff 0.6.9)
* `python3 scripts/check_decision_coercions.py` — "clean: no new coercions, no stale allowances in the files this change touches."
* `python3 scripts/check_planning_integrity.py` — clean; `python3 scripts/check_product_plan_governance.py` — "product-plan governance: clean"
* `pytest -n 6 tests/draft_valuation tests/draft tests/auction tests/api/test_draft_capital*.py tests/test_runtime_data_isolation.py -m "not livedata"` — "747 passed, 6 warnings in 60.90s" (0 skipped, 0 failed; includes the 77 new Batch G tests)
* `git status` clean after the runs (no tracked file written)

## UNRESOLVED

* Row 6 (deploy, smoke, rollback drill, exact-head CI of the merged train) — after #1809 merges.
* Replay of a PROMOTED generation (a pointer at or before `as_of`) is refused, not
  reconstructed; no pointer exists today (Batch D ships `dry_run`). Needed before
  the first live promotion if as-of replay must cover it.
* Google Sheets engine — parity is against the Sheets export cache and the literal
  transcription, not a live Google Sheets evaluation (unchanged from Batch A).
