# Draft valuation Batch D — preregistered promotion thresholds (2026-10-18)

**Status:** OWNER-APPROVED, 2026-10-18. Owner, verbatim intent: *"Approve Draft
Valuation Batch D with your recommended thresholds."* The recommended
thresholds are the ones below; they are now owner-approved.

**Preregistration.** This file and `config/draft_valuation/promotion_policy.json`
were committed BEFORE any code evaluated a 2027 rookie-class candidate against
them, and before any 2027 candidate output was looked at. The machine-readable
copy is the policy file; its `thresholds` object is checksummed:

```
thresholdsChecksum (sha256 of canonical JSON of "thresholds"):
c90de3ea8d0603b6d1a265dc4625327d9b248ab28b31c885cfa4ac840a95d818
```

The loader refuses the policy if that checksum no longer matches, so a
threshold cannot be edited silently after the fact. Changing a threshold is a
new owner decision and a new policy `version`.

Scope: `dynasty_main` only (12 teams x 6 rounds = 72 picks, $1,200 per class,
whole dollars). Workstream record: `docs/draft/DRAFT_VALUATION_WORKSTREAM.md`
(decision 12).

## 1. Timing gate — `class_window_open`

A class Y candidate may be evaluated only after the NFL Draft for year Y has
completed.

* Config: `nflDraftCompleteOn` per year. For 2027: **`2027-05-01`** (a
  conservative date; the real NFL Draft is late April). The window opens at
  00:00 UTC on that date.
* Before that date, or when no date is configured for Y, the state stays
  `FALLBACK_VERIFIED` with the reason named.

## 2. `source_freshness` — all must hold

* the candidate is built from a canonical contract whose `contractHealth.ok`
  is `true`;
* the contract's age (its own as-of, `scrapeTimestamp`) is **<= 6 hours** —
  the repo's existing staleness budget, `SCRAPE_INTERVAL_HOURS x 3`, read from
  `src.api.league_registry.SCORING_SNAPSHOT_MAX_AGE_HOURS` (no new number);
* none of the 72 entries is `quarantined`;
* every entry has a positive `rankDerivedValue`;
* each of the **top 24** entries (rounds 1-2) has `confidenceBucket` of
  **`medium` or `high`** (the existing B11 owner's output).

## 3. `stability_vs_prior_generation`

A trailing window of **>= 24 hours** of consecutive readiness evaluations
(each a fresh build) in which:

* every evaluation is structurally `CANDIDATE_READY` and passes
  `source_freshness`;
* the 72-identity set is identical;
* every pick's whole-dollar value stays within **+/- $3** of that pick's
  median over the window;
* the total absolute change between the window's first and last evaluation
  is **<= $30**.

Evaluations are persisted append-only so the window can be computed. A gap of
**more than 6 hours** between evaluations resets the window.

## 4. `bounded_variation_vs_fallback` — review band

Compare the candidate's 72 whole dollars with the frozen-fallback curve's
whole dollars, slot by slot. If either holds, the state is
`VALIDATED_NEEDS_REVIEW`: promotion is held and an alert fires, but nothing
else is blocked.

* any slot differs by more than **max($15, 50% of the fallback value)**;
* the picks 1-12 total differs by more than **25%**.

Otherwise the gate passes.

## 5. States and automatic promotion

`FALLBACK_VERIFIED -> CANDIDATE_INCOMPLETE -> CANDIDATE_READY -> VALIDATED
(freshness + stability) -> PROMOTABLE (review band passed) -> ACTIVE`, plus
`VALIDATED_NEEDS_REVIEW`, `ERROR_*` and `ROLLED_BACK`.

* **Automatic promotion:** a class that stays `PROMOTABLE` continuously for
  **48 hours** is promoted to `ACTIVE`. This includes the first switch from
  the frozen fallback.
* Promotion is an atomic generation publish: a new create-only published
  allocation plus a last-good pointer.
* Every failure keeps the previous generation.
* One alert per state transition, never repeated.
* One-command rollback restores the previous generation and records
  `ROLLED_BACK`.
* An operator diagnostic prints the state, the gates and the window.

## 6. Live switch

Live promotion ships enabled in code but guarded by the policy file's
`promotionMode`. It defaults to **`dry_run`**: compute and record states,
alert, never switch. Flipping it to `live` is a one-line config change made
after the PR is deployed and observed in production. `promotionMode` sits
outside the thresholds checksum, so the flip changes no preregistered number.
No class can be eligible before 2027-05-01 anyway.

## 7. Storage

Generated class snapshots, published allocations, the readiness-evaluation
log and the promotion pointer are written create-only and checksummed to the
repo-tracked store under `config/draft_valuation/`, committed by the
scheduled refresh workflow after its fresh build. The box-local store is a
cache only. The rookie board values are already tracked in `exports/`, so this
adds no new exposure; nothing here is served publicly.

## 8. Pre-draft cutoff for the ledger

The ledger's pre-draft cutoff comes from Sleeper's draft `start_time`, never a
constant. Unknown means refuse, with a reason.

## Implementation interlocks (not thresholds)

These are not preregistered numbers and cannot loosen anything above; each
can only HOLD a promotion (the previous generation stays):

* a rolled-back class is held (`ROLLED_BACK`) until an operator resumes it,
  so automatic promotion never silently undoes an operator's rollback;
* the 48-hour clock restarts after every promotion, rollback or resume, so an
  active generation is replaced at most once per 48 hours;
* promotion is held once the league's rookie draft for that class has started
  (or its status cannot be observed), so auction budgets never change during
  a live draft.
