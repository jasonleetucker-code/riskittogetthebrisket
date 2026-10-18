# Draft valuation automation — spreadsheet → canonical engine (workstream record)

**Status:** AUTHORIZED, IN PROGRESS. Owner master execution directive and
addendum of 2026-10-18 (summary below), owner implementation package of
2026-10-17 (`START_HERE_OWNER_DECISIONS_AND_CURRENT_QUEUE.md`, the forensic
audit, PROMPT 0 and A–G, the 72-pick goldens). The package's START_HERE
decisions are final and supersede the open questions recorded in its audit and
prompts.

**This is an addition to the active queue, not a stop-work directive.**
Release trains, the Trade Calculator TC lanes, Manager Intelligence, IDP and
source work, player availability / playoff simulation and every other
authorized lane continue. Merges and deploys keep their existing gates; the
owner's approval of the $1,200-per-class rule does not approve any PR's merge
(including #1785).

Authorization: `docs/EXECUTION_PLAN.md` → "Draft valuation automation".
Intake: `docs/OWNER_REQUESTED_TODO.md` → "Added 2026-10-18 — Draft valuation
automation (spreadsheet → canonical engine)". Claim: `docs/WORK_CLAIMS.md`.
Workbook map and parity evidence: `docs/draft/DRAFT_DATA_WORKBOOK_MAP.md`.

## Final owner decisions (binding)

| # | Decision | Source |
|---|---|---|
| 1 | **$1,200 per eligible rookie draft class for `dynasty_main`**, every year, indefinitely (scope corrected 2026-10-18 — see below; the earlier "both leagues" wording is superseded). Never divide one $1,200 across 2027–2029; with three complete future classes `All Years` is $3,600 nominal. Distinct from trade-market pick values and from any separately labelled discounted present-value analytic. The old "annual vs pooled" question in PROMPT 0 / PROMPT E is **RESOLVED** | START_HERE §1; directive 2026-10-18 |
| 2 | `dynasty_main` is 12 teams × 6 rounds = 72 picks per class. Any other league is out of scope (scope correction below) | START_HERE §2, corrected by owner 2026-10-18 |
| 3 | The workbook's existing 2026 values are the approved **provisional** rookie-value fallback: freeze them with provenance and an effective snapshot date; keep column B (rookie inputs) distinct from column H (the historical 2026 dollar curve); never relabel a reconstruction as an original pre-draft observation; daily value changes never rewrite the frozen fallback; never reactivate retired 2026 pick assets | START_HERE §3; directive |
| 4 | Spine = the three most recent **completed** rookie drafts: 2024/2025/2026 for 2027; roll to 2025/2026/2027 only on verified 2027 draft completion; never invent a completed class; immutable snapshots (year, inputs + provenance, 72 dollars, spine years, formula version, league config, timestamps, validation receipt, checksum) | START_HERE §4; directive |
| 5 | Preserve the 60/40 spreadsheet formula exactly; each annual pool reconciles to **exactly** $1,200 in money units | START_HERE §5 |
| 6 | Automatic rollover: scheduled readiness checks over approved offense + IDP rookie sources, stable class identity, full coverage and validation before staged promotion; keep the last verified generation and alert on failure; no manual Google Sheet maintenance or mutation | START_HERE §6 |
| 7 | **Whole dollars only** for the `dynasty_main` auction: 72 integer pick values totalling exactly $1,200, so every manager budget is the exact integer sum of owned picks. The 60/40 formula, spine, decay, caps and floors are unchanged; the half-dollar L curve stays the mathematical reference and the whole-dollar allocation is a separately identified final step (`apportion.apportion_whole_dollars`: floor, residual to the largest remainders with ties to the earlier pick, verify or refuse) | owner, 2026-10-18 |
| 9 | **Two values per completed class**, both immutable with receipts: `referenceDollars` (the spreadsheet curve at its original precision) builds the three-year spine, as the F/G/H formula was designed around; `finalWholeDollars` (the published integers) is used for every pick allocation, manager budget, draft-capital display and auction transaction. Fractional dollars are never published as spendable budget. Ledger, snapshots and receipts carry exactly these names; spreadsheet-imported 2024-2026 classes carry `finalWholeDollars: null` with a reason (their published allocation is not in the workbook) | owner, 2026-10-18 |
| 10 | **Constraint-aware whole dollars before refusal.** Step A (largest remainder) is used unchanged whenever it satisfies every constraint, so existing outputs (incl. the 2027 workbook) never move. Only if it breaks one, Step B solves exactly: minimise Σ\|d_i − r_i\| subject to integer d, Σd = $1,200, per-pick floors/caps (never weakened), non-increasing; ties → lexicographically largest allocation (earlier picks first). Exact windowed DP (window doubled until lossless). Refuse only on genuine infeasibility (proven by monotone bounds, binding constraint named), missing/bad data, or failed verification. No last-known-good store in the module: a refusal propagates and #1785 refuses the board with `draft_dollars_refused`. Evidence: `docs/draft/WHOLE_DOLLAR_RECOVERY_EVIDENCE_2026-10-18.md` | owner, 2026-10-18 |
| 11 | **Last-known-good safety.** The newest independently verified, complete 72-pick whole-dollar allocation per draft year is preserved (append-only, create-only, checksummed records; "current" is derived, never a mutable copy). A failed refresh (missing inputs, infeasible constraints, verifier failure, formula change) serves that SAME year's last verified allocation as `last_known_good` with `failedRefresh{at, reason}` and `lastValidAt`; with none it is `unavailable` with a named reason. Never zero budgets, never another year's curve, never ownership (dollars by draft position only; ownership is joined by the consumer from the live Sleeper fold). A retired class or a formula-version change makes a stored allocation stale → refused | owner addendum, 2026-10-18 |
| 8 | **K-step tie rule:** tied remainders at the award cutoff go to the earlier draft position, so the half-dollar curve always totals exactly $1,200 (the literal sheet would publish e.g. $1,206). A departure from the literal sheet only in that case; unchanged on the real workbook. Resolves the former cutoff-tie open question | owner, 2026-10-18 |
| 12 | **Batch D promotion thresholds — owner-approved and preregistered** ("Approve Draft Valuation Batch D with your recommended thresholds"). Timing gate `class_window_open` (`nflDraftCompleteOn` per year; 2027 → `2027-05-01`); `source_freshness` (`contractHealth.ok`, contract age ≤ 6 h = `SCRAPE_INTERVAL_HOURS × 3`, no quarantined entry, every `rankDerivedValue` positive, top 24 `confidenceBucket` medium/high); `stability_vs_prior_generation` (≥ 24 h of consecutive fresh evaluations, identical 72-identity set, every pick within ±$3 of its window median, first→last total absolute change ≤ $30, a gap > 6 h resets); `bounded_variation_vs_fallback` review band (any slot off by > max($15, 50% of fallback) or picks 1–12 total off by > 25% → `VALIDATED_NEEDS_REVIEW`, held + alert); automatic promotion after 48 h continuously `PROMOTABLE`, including the first switch from the frozen fallback; atomic create-only generation publish + last-good pointer, one alert per transition, one-command rollback; live switch behind `promotionMode` (default `dry_run`); repo-tracked create-only checksummed storage under `config/draft_valuation/` committed by the scheduled refresh (resolves the storage UNRESOLVED); ledger pre-draft cutoff from Sleeper's draft `start_time`, unknown → refuse. Record: `docs/draft/BATCH_D_PREREGISTRATION_2026-10-18.md`; machine copy `config/draft_valuation/promotion_policy.json` (`status: OWNER_APPROVED_2026-10-18`, thresholds checksummed) | owner, 2026-10-18 |
| — | One canonical owner per concept; package Value Adjustment never applies to pick auction dollars; MISSING IS NEVER ZERO; independent verification, never a test that copies production logic | directive |

## Scope correction — owner 2026-10-18

Binding; supersedes every earlier instruction that extended the $1,200
approval to both leagues. The canonical owner-intake and plan text is on
PR #1785's branch (`docs/OWNER_REQUESTED_TODO.md`, `docs/EXECUTION_PLAN.md`);
this section does not restate it.

* **`dynasty_main` ("Risk It to Get the Brisket") is the only league in
  scope.** Batches B–G implement and accept against it alone: 12 teams,
  6 rounds, 72 picks, $1,200 per class independently, 2027/2028/2029, the
  approved spreadsheet formula, offense and IDP rookie valuations, the
  rolling three-year completed-class spine, real Sleeper standings / draft
  order (reverse record, then lower Points For) and pick ownership.
* **Any other league is "not configured" and fails closed** — never adapted.
  The engine does not assume any other league uses the formula
  (`src/draft/rookie_auction/league_scope.py`: snapshots, class candidates,
  readiness and the ledger all refuse an unconfigured league).
* The **40-pick `dynasty_new` adaptation is OUT OF SCOPE** by owner
  correction 2026-10-18 — not an open decision, not designed for.
* Nothing about `dynasty_new` is deleted: its records, configuration and
  data stay as they are; there is simply no new feature work for it.

## Batches

Status vocabulary: AUTHORED → TESTS GREEN → PR → MERGED → DEPLOYED →
PRODUCTION-VERIFIED (each a separate claim).

| Batch | Deliverables | Depends on | Tests / evidence | Completion criteria | Already satisfied by existing code / PRs | Status |
|---|---|---|---|---|---|---|
| **A — spreadsheet parity** (PROMPT A) | Forensic map (`DRAFT_DATA_WORKBOOK_MAP.md`); golden fixtures (workbook cells + cached values, inputs, owner package goldens, LibreOffice recalc, RANK-tie cases); pure versioned allocator `src/draft/rookie_auction/curve.py` (Decimal / Fraction, integer half-dollar units, every intermediate column, receipts via `curve_receipt`); independent literal transcription `tests/draft_valuation/reference_workbook_formulas.py`; legacy comparison `scripts/draft_valuation_parity_report.py` | — | 72/72 on C/D/E/I/J/K/L vs cache and vs package goldens; LibreOffice C within 5e-13; reference vs cache incl. grid, Q, owners, team totals, M123; 250 random cases production = reference; 10 formula mutations detected; RANK-tie suite | all of the above green; no production value changed; no Sheet write | the formula already ran in `server.py::_rookie_dollars_from_values` (matches 72/72 when fed the sheet's own B) — kept, not reused, because it is float, tolerates < 72 inputs, falls back to a flat spine and tie-breaks by row | **TESTS GREEN; PR #1786 open** (not merged — needs owner approval). Includes the owner's whole-dollar final step and K-step tie rule (2026-10-18) |
| **B — canonical rookie values + frozen fallbacks** (PROMPT B) | Frozen 2026 provisional baseline `config/draft_valuation/frozen_inputs/2026_spreadsheet_baseline.json` + checksum-refusing loader `src/draft/rookie_auction/snapshots.py` (**done**); then a `RookieClassSnapshot` contract (target vs actual input class, mode `actual` / `frozen_fallback`, league, scoring fingerprint, IDP eligibility, generation hash, 72 entries with stable IDs, coverage, missing reasons); class-identity states (`class_eligible_for_curve` / `rosterable_on_sleeper` / `unsupported_class_identity`); sorted, de-duplicated top-72 from canonical `rankDerivedValue`; read-only readiness detector | A | frozen-snapshot tests (checksum pinned, edits refused, relabel refused, 2027 spine, curve from frozen inputs = workbook 72/72); later: class-identity, IDP / non-IDP, duplicate-alias, 72-uniqueness, stale-evidence tests | stable 72 ordered values or explicit NOT_READY; frozen fallback never mutates; no premature 2027 promotion | `src/draft/rookie_pool.py::select_rookie_rows` (the one "who is in this auction" owner — reuse; note it proves `rookie` + Sleeper id, not class year); `src/api/draft_class_evidence.py` | **TESTS GREEN** on PR #1786: frozen baseline; `class_snapshot.py` (class identity, sorted top 72, hashes, frozen template); report-only `readiness.py` (`PROMOTION_ENABLED = False`; measured 2026-10-18: 2027 class 0/72 eligible → `FALLBACK_VERIFIED`) |
| **C — historical spine snapshots + rollover** (PROMPT C) | Completed-class curves 2024/2025/2026 as spreadsheet-sourced snapshots (**done**, unknown inputs/spine/formula/completion `null` with reasons); `select_spine_years` (**done**); then an append-only ledger of generated class curves keyed by (league, class, formula version, cutoff), written only on verified completion + roster consumption, idempotent, with an as-of replay command | A, B | spine selection 2027 → {2024, 2025, 2026}, 2028 → {2025, 2026, 2027} only once 2027 exists; later: completed-not-rostered, two jobs, reopened draft, supersession, failed write | dynamic last-three resolver; immutable ledger; no hindsight substitution; 2024 retained after leaving the window | `src/identity/pick_lifecycle.py` (completion AND roster consumption — the #1414 rule), `src/api/draft_class_evidence.py`, `src/history/` (temporal ledger conventions) | **TESTS GREEN** on PR #1786: published allocations with last-known-good safety (`published.py`, runtime verifier `verify.py`); imported curves under `historical_curves/dynasty_main/`, `ledger.finalize_completed_class` (create-only, verified completion via `pick_lifecycle`, pre-draft cutoff, idempotent, conflict-refusing), `replay_spine` + CLI. Not wired to any job (Batch D) |
| **D — automated class readiness / promotion** (PROMPT D) | Preregistered owner-approved thresholds (decision 12; `BATCH_D_PREREGISTRATION_2026-10-18.md`, `config/draft_valuation/promotion_policy.json`, thresholds checksummed); policy-driven `src/draft/rookie_auction/promotion.py` on top of the report-only `readiness.py` (`PROMOTION_ENABLED` stays `False` there): timing gate, `source_freshness`, `stability_vs_prior_generation` over an append-only evaluation log, `bounded_variation_vs_fallback` review band, 48 h automatic promotion; atomic generation publish in `published.py` (create-only `promoted_allocations/` + sequence-numbered `promotion_pointers/`, rollback = a pointer back, resolver serves the pointed generation); one alert per transition (`promotion_transitions/`); operator CLI `scripts/draft_valuation.py` (`evaluate` / `status` / `rollback` / `resume`); ledger cutoff `ledger.pre_draft_cutoff_from_sleeper` (draft `start_time`, unknown refuses) + finalization step (live only); scheduled-refresh step after each fresh build, records committed with the data refresh, alerts to a `draft-valuation` issue | A–C | `tests/draft_valuation/test_batch_d_promotion.py` (mocked time: time jump fallback → 2027, every gate failing, stability gap / ±$3 / identity, review band, 48 h promotion, dry run never switches, rollback, no repeated alerts, every failure keeps the previous generation, cutoff); `dynasty_main` draft-capital output byte-identical before/after on 2026-10-18 | dry-run only in its PR; first live switch = the one-line `promotionMode` flip after production observation | `.github/workflows/scheduled-refresh.yml`, existing rolling-issue alert plumbing, `pick_lifecycle` | **TESTS GREEN; PR open** (`claude/draft-valuation-batch-d`, not merged — owner approval required). Ships `promotionMode: dry_run`; workflow evaluation + commit wired live (records only) |
| **E — multi-year draft capital** (PROMPT E) | Integrate with #1785 (no second ownership resolver or year selector); $1,200 per class for `dynasty_main`; replace #1785's interim generic-market future-class curve with the workbook curve (frozen 2026 inputs + spine for each class until that class's real inputs pass Batch D); draft order = `reverse_record_lower_pf` (`src/public_league/draft_order.py`) for verified final standings, forecasts labelled, later years round-level only; real Sleeper standings and pick ownership for `dynasty_main` | A–C (#1785 merged) | 216 unique 2027–2029 identities for `dynasty_main`; per-class totals exactly $1,200; no 2027 double count in `/trade` | per-year API with `budgetBasis`, `curveId`, `spineYears`, `inputMode`; UI unchanged except labels | **#1785** (open, `claude/draft-capital-all-years`): every Sleeper class on `/league` Draft Capital, `?year=`, per-class $1,200 pool (`budgetPolicy per_class_pool`), canonical ownership fold, refuses an unobserved `/traded_picks`; **#1579** year selector; **#1626** draft-capital correctness / lifecycle; **#1769** canonical public pick ownership; `src/identity/picks.py`, `pick_lifecycle.league_draft_years` | NOT STARTED (waits on #1785) |
| **F — sitewide integration, automation, monitoring, cache** (PROMPT F) | Consumer census; one `DraftCapitalGeneration` reader; swap `server.py::_rookie_dollars_from_values` and the L2:L73 read onto the canonical curve (same quantity only); keep canonical 0–9999 pick values and the trade package model untouched; receipts (`generationHash`, `curveVersion`, `targetDraftYear`, `actualInputClassYear`, `spineYears`, …); alerts; stale-while-revalidate on the last valid generation | A–E | consumer matrix with exact functions/tests; before/after payloads under pinned data | every consumer of auction dollars reads one generation; no silent value change | `src/api/pick_value_resolution.py` (market values — must stay separate), `src/api/draft_capital_years.py`, `frontend/lib/draft-capital-years.js` | NOT STARTED |
| **G — end-to-end verification + release** (PROMPT G) | Independent checker (no production imports) over pinned goldens and generated classes; adversarial dataset; as-of replay; read-only Sleeper reconciliation (216 ids); staged rollout, exact-head CI, deploy, desktop 1440 / mobile 375 smoke; rollback drill | A–F | PASS / FAIL / BLOCKED / NOT_TESTED report | production proof, not self-consistency | Batch A's reference transcription and fixtures are the start of the independent checker | NOT STARTED |

## API for PR #1785

```python
from src.draft.rookie_auction.published import (
    AllocationCandidate, CandidateFailure, PublishedAllocation, resolve_published_allocation,
)
resolve_published_allocation(
    league_key: str, draft_year: int, *,
    candidate: AllocationCandidate | CandidateFailure | None = None,
    lifecycle: ClassLifecycle | None = None,          # pick_lifecycle verdict; retired -> unavailable
    store_dirs: Sequence[Path] | None = None,         # default: repo store, then box-local store
    write_dir: Path | None = None,                    # default: box-local store
    persist: bool = True,
) -> PublishedAllocation
```

* `AllocationCandidate(draft_year, reference_dollars, effective_at, provenance,
  formula_version=FORMULA_VERSION)` — the workbook path passes its 72 L values
  (exact strings / Decimals / Fractions; floats are refused) plus provenance;
  `AllocationCandidate.from_curve(result, ...)` for a computed curve.
* `CandidateFailure(draft_year, reason, at)` — a refresh that produced no curve.
* `PublishedAllocation`: `allocation_state` (`current` / `last_known_good` /
  `unavailable`), `final_whole_dollars` (72 ints or `None`), `picks`
  (`"1.01"`…`"6.12"`), `dollars_by_slot()` (raises when unavailable),
  `reference_dollars`, `effective_at`, `last_valid_at`, `failed_refresh`
  (`{at, reason}`), `unavailable_reason`, `warning`, `record_checksum`,
  `receipt` (formula version, provenance, apportionment + verifier receipts),
  `to_dict()`. No ownership field exists.
* Whole-dollar primitive (unchanged path/signature):
  `src.draft.rookie_auction.apportion.apportion_whole_dollars(values, total, *, floors=None, caps=None)`;
  the result object gained `method`, `step_a_dollars`, `step_a_violations`,
  `repairs`, `total_deviation`, `max_deviation`, `binding_constraints`.

**Promoted generations (Batch D).** `resolve_published_allocation(...,
promotion_root=None)` additionally reads the promotion pointer
(`config/draft_valuation/promotion_pointers/<league>/<year>/NNNNNN.json`,
create-only, checksummed): when it names a promoted generation (a record
under `promoted_allocations/`), that generation is served as `current`
(note `promoted_generation:<seq>`) and the workbook candidate is not used.
No pointer — the state of every class today — leaves resolution exactly as
below. A caller that passes its own `store_dirs` and no `promotion_root`
reads no pointer.

**Where allocations live.** Repo-tracked
`config/draft_valuation/published_allocations/<league>/<year>/` holds the
workbook-derived allocation (seeded: 2027, effective 2026-10-17, the workbook's
72 whole dollars). Production-computed allocations are written by the resolver
to the box-local, gitignored `data/draft_valuation/published_allocations/` —
the same open storage/privacy question as the ledger (see UNRESOLVED).

## Coordination

* **PR #1785** (`claude/draft-capital-all-years`, worktree `/home/user/rit-dc`)
  owns `src/api/draft_capital_fallback.py`, `src/api/draft_capital_classes.py`,
  `src/api/draft_capital_years.py`, `server.py::_fetch_draft_capital`,
  `frontend/app/league/sections/draft-capital.jsx`,
  `frontend/lib/draft-capital-years.js`. This workstream does not edit them
  until Batch E.
* This branch adds only new files (`src/draft/rookie_auction/`,
  `config/draft_valuation/`, `tests/draft_valuation/`, two scripts, these
  docs) plus records rows.

## Named follow-ups (recorded, not fixed here)

* **`server.py::_parse_csv_rookies` returns 0 rookies on the current CSV.**
  The scheduled export writes `1.0` / `5103.0`, and the parser calls
  `int()` on them, so every row is skipped and the KTC-rookie CSV fallback in
  `_get_ktc_rookies` is dead. The same rows are also misaligned in the sheet
  (`Composite` two rows above the names; map §3). Not fixed in `server.py`
  here: PR #1785 owns that area. Fix when Batch F swaps the rookie path.
* `server.py::_rookie_dollars_from_values` and the L2:L73 read move onto the
  canonical curve in Batch F (map §6 lists the measured divergences).

## UNRESOLVED

* **No pre-draft 2026 rookie inputs exist in evidence.** Column B is frozen as
  the owner-approved provisional baseline, labelled not-a-pre-draft
  observation; any later "original 2026 class" claim needs archival evidence.
* **Spreadsheet-sourced curves** 2024/2025/2026 have no recorded inputs, spine,
  formula version or published whole-dollar allocation; recorded as `null`
  with reasons rather than reconstructed.
* **Storage — RESOLVED by decision 12 (2026-10-18).** Generated class
  snapshots, promoted allocations, the readiness-evaluation log, the
  transition log and the promotion pointer are create-only, checksummed and
  repo-tracked under `config/draft_valuation/`, committed by the scheduled
  refresh. The box-local `data/draft_valuation/published_allocations/` store
  (workbook-path allocations) remains a cache only.
* **Pre-draft cutoff — RESOLVED by decision 12.** `ledger.pre_draft_cutoff_from_sleeper`
  reads Sleeper's draft `start_time` for the rookie draft(s) the completion
  verdict named; unknown refuses.
* **Observed NFL season for automated class identity.** The scheduled
  evaluation passes Sleeper `/state/nfl` `season` to the yearsExp-based class
  identity (unknown → no candidate, never a guess). How Sleeper's `years_exp`
  rolls in May relative to that season has not been observed for a 2027
  class yet; the first window-open evaluations (dry run) are the evidence.
* **Ledger finalization of a class served from the frozen fallback.** The
  frozen snapshot's `effectiveSnapshotDate` is a date without a time zone,
  which the ledger refuses as an inputs timestamp; such a finalization is
  reported refused with that reason rather than given an invented time.
* **Google Sheets engine** — parity is against the Sheets export cache (10
  digits) and LibreOffice (full precision); no live Google Sheets evaluation.
