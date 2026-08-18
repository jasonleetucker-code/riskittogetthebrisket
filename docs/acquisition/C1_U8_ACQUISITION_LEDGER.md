# C1-U8 — acquisition history, cost basis and pick lineage

**Unit:** `C1-U8` · **Rows:** `C1-ACQ-01`, `C1-ACQ-02`, `C1-ACQ-03` (CE-18)
**Owner:** `src/acquisition/`
**Delivered:** 2026-08-17 · **Branch:** `claude/c-series-c1-u8` (stacked on `claude/c-series-c1-u5`)
**State:** `CLOSED-PENDING-PROD` — see §8. This is **not** `CLOSED`.

---

## 1. What was ABSENT, measured before anything was written

All three manifest rows read ABSENT, and a survey of every durable transaction seam
confirmed it: **zero acquisition, holding-period or cost-basis implementations** anywhere
in `src/`, `frontend/lib/` or `server.py`.

What did exist were three stores holding overlapping slices of one Sleeper feed, none of
which can answer the three questions:

| store | holds | own league? | why it cannot answer |
|---|---|---|---|
| `data/retention/league_events.sqlite` | **trades only**, payload-verbatim | yes | no asset-level row; its read surface is count-only *by design* |
| `data/intel/ledger.sqlite3` | all tx types at asset grain, `faab_bid` | **no** | members' *other* leagues — wrong population |
| `data/faab/bid_history_*.json` | waiver adds only | yes | no `transaction_id`; whole-file rewrite; skips week 0 and bid-less adds |

And **draft selections — including realized auction prices — were in none of them.** The
live path (`sleeper_overlay.fetch_live_draft_picks`) is a two-second in-memory cache; the
public-league snapshot is a different surface carrying a two-pick stub. Once Sleeper ages
a draft object out, those prices are gone.

That table is in the package docstring too, because *"why not just extend the intel
ledger"* is the first question a later reader will ask.

---

## 2. Two capture gaps, closed at the source

Both were places where evidence was **already being fetched and then dropped**. Neither
needed new plumbing or a single extra HTTP request.

### 2.1 `_build_waivers_block` recorded nothing

Every waiver and free-agent transaction already passed through `_build_trades_block`'s
loop and was `continue`d **one line before** `ledger_batch.append`
(`sleeper_overlay.py:1011-1012` vs `:1027`); the waivers builder then re-read the same
memoised bodies and discarded everything older than `window_days`. The FAAB bid it
computes is the literal cost basis of every non-draft, non-trade addition, and it survived
only inside a rolling window.

**Ordering is load-bearing.** Capture sits *before* the window cutoff and *before* the
`seen` dedupe, for the two reasons the trades path already states at its own append:
`window_days` is OUR cutoff rather than Sleeper's, so the claims it drops are precisely
the ones about to become unreadable; and `seen` exists to stop the UI showing one claim
twice, which the ledger's primary key already handles — deduping ahead of it would hide a
chain member's own copy of the event.

Both builders now flush through one shared `_flush_transaction_ledger`, so there is one
best-effort posture rather than two that drift.

### 2.2 `record_transactions` was called with two kwargs unset

`league_key` and `season` were NULL on **every row ever written**, and both were available
at the call site. Two details worth keeping:

- **`league_key` resolves from the ROOT id, then stamps every chain member.** A previous
  season's Sleeper id is not in the registry, so resolving per member would leave every
  historical row unattributed. The chain *is* that registry league across seasons, which
  is exactly what the column means.
- **`season` resolves per chain member, and stays NULL when unknown.** Deliberately not
  `_league_season`, which falls back to the calendar year: that fallback is right for a
  display path and wrong for retention, because a guessed season is indistinguishable from
  an observed one once it is in the database.

---

## 3. Architecture — a new package, and the two it is not part of

**Not `src/retention/`.** `src/retention/__init__.py` states that *nothing there may be
read by a decision path* — "a value that fed back into the thing it records would make
every measurement taken from it circular". A ledger CE-18 trade trees read **is** a
decision path. So retention stays the raw recorder with a count-only read surface, and
`src/acquisition/` derives from it. One named collector
(`scripts/build_acquisition_ledger.py`) is the only thing that crosses the boundary, and
it reads transaction *payloads* — never a retained value, which is the circularity the
rule is actually about. A structural test pins that no projection module imports
retention.

**Not `src/history/`.** That owns as-of market *value* observations; its `keys.py`
deliberately excludes league picks, and its lanes are about what an asset was worth rather
than who held it. Ownership facts are a different quantity in a different privacy class.

### Three tables, two different idempotence promises

`acquisition_events` is **INSERT-only**. Re-ingesting an identical event is a no-op;
re-ingesting the same key with **different facts** is a conflict that is *reported and not
applied*, because a ledger whose past changes when a collector re-runs is not a ledger.

`holdings` and `pick_lineage` are **pure replay derivations**, rebuilt wholesale per
league. A rebuild from scratch is therefore a valid repair for any derived-table
corruption, and there is no migration to get wrong.

**The event key is natural, not synthesised.** An asset moves at most once inside one
transaction, so `(league_key, source_ref, asset_id)` suffices — and a three-team trade
becomes N rows sharing one `source_ref`, preserving the multi-party shape instead of
flattening it into fictional two-party trades. Draft selections key on the draft's own
identity (`draft:<draft_id>:<pick_no>`), so no synthetic transaction id is minted.

---

## 4. The rules that stop it guessing

### 4.1 Cost basis — `value_known_before`, never `value_as_of`

`value_as_of` is day-granular, so a board built *later on the same calendar day* qualifies.
For a cost basis that is a look-ahead leak: it prices Monday's trade with Monday-evening's
board, which already contains the market's reaction to that trade.

Two further leaks closed explicitly:

- **The clock is an argument, and it decides a real thing.** `market_resolution()` takes the
  current draft year as an INPUT. For a pick whose slot is **known** it answers `exact_slot`
  once that draft year has arrived and `tier_from_slot` while it is still future — so asking
  with today's clock would price a pre-draft trade at the slot the pick eventually landed on.
  That is the `C3-REPLAY-01` class: it measures the methodology rather than the aging.

  Where the slot is genuinely unknown the answer is the GENERIC grade and the clock is not
  consulted — by construction, not by omission. Both cases are exercised.

  > **This was a defect in the first cut and is worth recording rather than quietly fixing.**
  > `basis.py` passed `slot=None` unconditionally, so `market_resolution` never reached the
  > branch that reads the clock — the entire as-of-event mechanism was unreachable, and the
  > test that "proved" it passed vacuously because both clocks collapsed to the same generic
  > ref. The repair carries `realized_slot` onto the event and the holding (slot is STATE, so
  > learning it mints no second asset), and the test now asserts the two grades **differ**.

- **One rollover rule, in one place.** The first cut reimplemented the draft-year rollover
  inside `basis.py` and reached across the package boundary for a private config loader — and
  reproduced only the date-derived fallback, dropping the `currentDraftYear` override. Fixed by
  factoring `data_contract.rookie_draft_year_on(day)` out of `current_rookie_draft_year`'s own
  step 3. The distinction is load-bearing: `current_rookie_draft_year` answers a
  **present-tense** question and its override and observed-year self-roll both beat its `today`
  argument, so calling it with a historical date would silently return today's answer.

- **Before the floor is missing, not cheap.** An acquisition earlier than `HISTORY_FLOOR`
  returns `None` with `before_history_boundary` — never interpolated, never today's value,
  and never the earliest *future* observation, which is the same look-ahead reversed.

- **A genuine `0.0` is a value, not a miss.** The code branches on `is None`, never on
  truthiness, and a test pins it — a refactor to `if not value:` would otherwise reclassify
  every observed zero as `no_prior_observation` with nothing failing.

### 4.2 `IMPORT_UNKNOWN` is fail-closed

An asset on a roster with no explaining event gets `acquired_method = "IMPORT_UNKNOWN"`,
an undated acquisition and `basis_missing_reason = "no_explaining_event"`. Defaulting it
to `FREE_AGENT` because most such assets were free agents is *missing is zero* wearing a
label: it would report a $0 cost basis nobody observed, and every downstream profit figure
would inherit it.

### 4.3 Three distinctions that must never collapse

| pair | why they differ |
|---|---|
| `auction_amount is None` vs `0` | not an auction vs a $0 lot. `src/public_league/draft.py` already draws this line; **the live overlay normaliser collapses both to `0`**, so the ingest reads `metadata.amount` itself rather than through that path |
| `faab_bid is None` vs `0` | not a waiver vs a waiver that cost nothing |
| `occurred_at_ms is None` vs `0` | undated vs dated 1970. `time_fidelity` says which |

### 4.4 Direction comes from the owner field, not the method name

`COMMISSIONER` is in **both** vocabularies on purpose — a commissioner can hand an asset
to a roster or take one off. The replay therefore decides direction from
`after_owner_rid`. A first cut branched on the method name and silently dropped every
commissioner *add*; the failure mode is invisible (the asset simply is not on anyone's
roster afterwards). Found by a test asserting the two vocabularies are disjoint, which was
the wrong assertion about the right thing.

### 4.5 Unorderable history is labelled, not hidden

An undated event cannot be ordered against dated ones. Rather than pretend, undated events
sort first (the conservative reading) and every holding derived in that pass carries
`order_fidelity = "undated_event_present"`. A consumer is never told a
partially-unorderable history is fully ordered.

Roster reconstruction uses the same vocabulary `src/history/asof.py` already uses:
`exact` / `partial` / `unavailable`. The last is the one a caller would otherwise get
wrong — **an empty roster and "no evidence covers this instant" render identically and
mean opposite things.**

---

## 5. Pick lineage (`C1-ACQ-03` / CE-18)

Keyed on `LeaguePickIdentity.canonical_id`, which by construction survives both ownership
transfer and slot realization — owner and slot are STATE, not identity (C1-U3). So a pick
traded A→B→C and then drafted is **one chain of two hops**, not several unrelated assets,
and no acquisition-local pick id is minted anywhere.

Two properties measured on synthetic histories: two same-round picks from different origins
stay distinct (the generic `pick:<season>:<round>` key cannot express this), and replay
after realization does not duplicate the chain.

**Sleeper's `/traded_picks` structurally cannot answer this.** It reports only *current*
ownership, so N appearances across N season snapshots is **not** N trades. That is why
`public_league/draft.py`'s `_most_traded_pick` and `_pick_movement_trail` are C1-U8's
output shape asked of the wrong substrate — recorded in §7, not rewritten here.

---

## 6. Privacy

**PRIVATE**, same class and posture as `league_events.sqlite`: same directory so one env
var redirects both, separate file so "back this up" and "publish this" can never be the
same gesture by accident. Mode 0600, gitignored, added to
`deploy/backup/riskit-state-backup.sh` (guarded, so a host that has not produced one yet
logs `skip (absent)` and the nightly still succeeds).

Blocking tests: no `/api/public/*` or `src/public_league/` module imports the package; the
frontend does not reference the database; `git check-ignore` passes on the path; the
coverage probe emits counts and stamps only — asserted by checking that no asset
identifier appears in its output, because a health surface that echoes private contents
moves the boundary every time someone checks whether the collector is alive.

**No UI and no HTTP route.** `C1-ACQ-02` is satisfied by a library function
(`roster_at`), which keeps the privacy test trivially true. A private authenticated route
is a later, separately-authorized unit.

---

## 6b. The post-delivery audit, and the nine repairs it forced

This unit was reported delivered before a completion report existed. Reconstructing that
report meant auditing the implementation against the owner's checklist rather than against
memory — and the audit found defects, so the honest sequence was **finish, then report.**

Recording it here because "the audit found nothing" and "no audit was run" look identical
from the outside, and because two of these were *false claims of correctness*, which is a
worse failure than an absent feature.

| # | found | resolution |
|---|---|---|
| 1 | the as-of-event clock was **dead code** — `slot=None` meant `market_resolution` never reached the branch that reads it | `realized_slot` now rides the event and the holding; §4.1 |
| 2 | the test that "proved" it was **vacuous** — hardcoded a clock the code disagreed with, and passed because both collapsed to one generic ref | rewritten to assert the two grades **differ**; `test_a_known_slot_is_graded_by_the_clock_at_the_EVENT` |
| 3 | `_draft_year_at` was a **competing owner** of the rollover rule, reaching across the package boundary for a private loader | `data_contract.rookie_draft_year_on` factored out; §4.1 |
| 4 | **no manager identity** — roster ids only, and a roster id means nothing outside one Sleeper league id | `after/before_owner_user_id` on events, `owner_user_id` on holdings and lineage |
| 5 | **startup and supplemental drafts were indistinguishable** from rookie drafts; the collector fetched the draft `type` and discarded it | `draft_kind` carried through; unlabelled stays `None`, never assumed rookie |
| 6 | **board/confidence inertness was prose**, never measured, on a unit stacked on the confidence work | measured **0/1111**, plus four structural guards; §8b |
| 7 | **no test that a real `0.0` basis survives** — the exact failure the module is built around | `test_a_genuine_zero_survives_as_a_value` |
| 8 | `derive_pick_lineage` numbered hops by **caller order**, so a public export was correct for one caller | ordering established inside the derivation; convergence tested |
| 9 | `WORK_CLAIMS.md` claimed the unit consumes `build_pick_ownership`; **it does not** | claim corrected — that fold answers current ownership from `/traded_picks`, which cannot express a chain |

Two pick-lineage cases the owner names were also untested and now are: **A→B→A** (a pick
returning to a prior owner — exactly where an owner-keyed identity would fragment) and a pick
**traversing three rosters inside one multi-party transaction**. The privacy import-scan was
widened from `src/public_league/` to `server.py` and `src/api/`, and the `0600` file mode is
asserted rather than merely applied.

## 7. Deliberately not done, with the measurements

- **The intel-ledger pick re-key.** `crawler.py:243-248` assigns this to C1-U8, and the
  plan required measuring the persisted collision before migrating. **Measured:
  `asset_movements` holds 0 rows on this box** — so a migration would be a no-op *here*,
  and this box therefore cannot establish production's state either way. Deferred **with
  the measurement**, per the rule: migrate only if provably safe and idempotent, and this
  is not provable from an empty table. Re-measure on prod before attempting it.
- **Retiring the six duplicate pick-ownership folds.** `build_pick_ownership` is
  canonical; six other live seed-then-diff folds exist —
  `sleeper_overlay.py:260-328` (already delegates), `draft_capital_fallback.py:280-319`
  (uses **slot as a stand-in for origin roster**, correct only when roster ids equal
  slots), `public_league/draft.py:104-186` / `:231-255` / `:258-286`, and
  `intel/crawler.py:176-249`. This unit **duplicates none of them and retires none of
  them** — it consumes the canonical fold. Retiring them is a bounded follow-up.
- **`_normalize_live_pick`'s `amount` collapse** (`sleeper_overlay.py:1741-1746`) —
  missing-as-zero on a live user-facing feed. Not this unit's business to change; the
  acquisition ingest simply does not read through it.
- No UI, no acquisition grades, no profit/loss cards, no manager grades, no trade-tree
  screens. No FAAB valuation methodology. No canonical value or confidence change.

---

## 8. Why this is `CLOSED-PENDING-PROD` and not `CLOSED`

Everything here is proven on synthetic histories and on this box, where
`data/retention/` does not exist. **Nothing has yet run against real data**, and the
capability's whole point is real data. Production verification, on the deployed merge SHA:

1. `python scripts/build_acquisition_ledger.py --offline --dry-run` — confirm it sees the
   existing retained transactions (288 at last register reading) rather than 0.
2. `python scripts/build_acquisition_ledger.py` for each active league — confirm
   `conflicts` is empty and drafts/rosters are fetched.
3. Run it **twice**; the second run must report `inserted=0`, `conflicts=[]` and identical
   derived-table counts.
4. `python scripts/acquisition_status.py` — non-zero events, and check
   `holdingsImportUnknown` against expectation (a large number means the transaction
   history does not reach back far enough, which is a finding, not a failure).
5. Confirm waiver rows now appear in `league_events` (`transaction_coverage`'s `trades`
   count must stop equalling its `transactions` count — they were identical, i.e. the
   store held trades and nothing else).
6. Confirm the nightly backup picks the file up (`skip (absent)` → a real snapshot).
7. Spot-check one known trade end to end: event → two holding periods → basis → lineage.

Until those are recorded, the unit is implementation-complete and not closed.

### 8a. Verification attempt — 2026-08-18 · **BLOCKED-EXTERNAL, all seven**

Attempted alongside the other four `CLOSED-PENDING-PROD` checklists. Unlike those, **none** of
these seven is reachable from the integration session, and the reason is the one §8 already
states: *"the capability's whole point is real data."*

| what the checks need | availability here |
|---|---|
| `data/retention/league_events.sqlite` | **absent** — the directory does not exist |
| `data/intel/ledger.sqlite3` | **absent** — the directory does not exist |
| running `scripts/build_acquisition_ledger.py` against live Sleeper for each active league | needs the prod host and its credentials |
| the nightly backup picking the file up | needs the prod host |

There is no partial credit available: item 1 exists specifically to confirm the builder sees
**288 existing retained transactions rather than 0**, and on this box it would see 0 for the
uninteresting reason that the store is not here. Running it and recording "0" would be worse
than not running it — it manufactures a measurement out of an absent input, which is the
failure mode this repository keeps finding elsewhere.

Recorded `BLOCKED-EXTERNAL`. Unblocking needs an authenticated production session, not more
work on the unit; the implementation is not what is missing.

---

## 8b. Board and confidence inertness — MEASURED

The first cut asserted this in prose and measured nothing. Both halves now exist.

**Measured**, `scripts/golden_board.py` on the base (`d33465d`) and on this head, then
`scripts/board_diff.py --expect-no-value-change`:

```
rows: 1111 -> 1111 · ranked: 740 -> 740 · priced: 849 -> 849 · picks: 162 -> 162 · idp: 398 -> 398
VALUES: 0 moved, 0 newly priced, 0 newly unpriced
RANKS:  0 changed
ASSERTION OK: no value changed.
```

**Structural**, `tests/acquisition/test_board_inertness.py` — because a diff proves inertness
*on the day it ran*, and for this unit inertness was otherwise true only by accident of
wiring: nothing outside the package imported it, so one future import would have made a
private historical substrate a valuation input and the measurement would still have read zero.

The direction of the rule matters and is stated in the test: this is **not** "acquisition may
not import the pipeline" — it reads value history through `src/history` quite legitimately. It
is the reverse. **The valuation path may not read acquisition**, because ownership history is
downstream of value, and feeding it back makes every measurement taken from the ledger
circular — the same rule `src/retention/__init__.py` states for its own stores.

Four guards: no module in the canonical valuation path imports `src.acquisition`; no module
in the whole `src/` tree does outside the package itself; a fresh interpreter that imports
`data_contract` has no `src.acquisition` in `sys.modules` (which a static scan would miss for
a lazy import); and the C1-U5 confidence vocabularies are unchanged — four levels, no
acquisition-flavoured basis.

## 9. Tests

| file | role |
|---|---|
| `tests/acquisition/test_capture_gaps_red.py` | the RED reproduction of both capture gaps, asserted on RECORDED ROWS rather than statement order — a test that greps for an `append` before an `if` passes when the code is rearranged into something equivalent and wrong |
| `tests/acquisition/test_acquisition_ledger.py` | ingest idempotence, conflict surfacing, order-independence, normalisation, replay, lineage |
| `tests/acquisition/test_cost_basis.py` | the never-future rule and the four refusals |
| `tests/acquisition/test_roster_and_privacy.py` | fidelity labels, `unavailable` ≠ empty, the structural privacy boundary |
| `tests/acquisition/test_end_to_end.py` | one league's whole season, and running it twice changing nothing |
| `tests/acquisition/test_board_inertness.py` | the structural half of §8b — the valuation path cannot reach acquisition history |

**106 tests, all invariants — no absolute counts over live data**, so every one belongs in
the deterministic gate.
