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
| **D — automated class readiness / promotion** (PROMPT D) | Preregistered owner-approved thresholds (decision 12; `BATCH_D_PREREGISTRATION_2026-10-18.md`, `config/draft_valuation/promotion_policy.json`, thresholds checksummed); policy-driven `src/draft/rookie_auction/promotion.py` on top of the report-only `readiness.py` (`PROMOTION_ENABLED` stays `False` there): timing gate, `source_freshness`, `stability_vs_prior_generation` over an append-only evaluation log, `bounded_variation_vs_fallback` review band, 48 h automatic promotion; atomic generation publish in `published.py` (create-only `promoted_allocations/` + sequence-numbered `promotion_pointers/`, rollback = a pointer back, resolver serves the pointed generation); one alert per transition (`promotion_transitions/`); operator CLI `scripts/draft_valuation.py` (`evaluate` / `status` / `rollback` / `resume`); ledger cutoff `ledger.pre_draft_cutoff_from_sleeper` (draft `start_time`, unknown refuses) + finalization step (live only); scheduled-refresh step after each fresh build, records committed with the data refresh, alerts to a `draft-valuation` issue | A–C | `tests/draft_valuation/test_batch_d_promotion.py` (mocked time: time jump fallback → 2027, every gate failing, stability gap / ±$3 / identity, review band, 48 h promotion, dry run never switches, rollback, no repeated alerts, every failure keeps the previous generation, cutoff); `dynasty_main` draft-capital output byte-identical before/after on 2026-10-18 | dry-run only in its PR; first live switch = the one-line `promotionMode` flip after production observation | `.github/workflows/scheduled-refresh.yml`, existing rolling-issue alert plumbing, `pick_lifecycle` | **MERGED** — #1799 merged via release train 7 #1803 (`24e218205e`, 2026-10-18). Ships `promotionMode: dry_run`; workflow evaluation + commit wired live (records only) |
| **E — multi-year draft capital** (PROMPT E) | Integrate with #1785 (no second ownership resolver or year selector); $1,200 per class for `dynasty_main`; replace #1785's interim generic-market future-class curve with the workbook curve (frozen 2026 inputs + spine for each class until that class's real inputs pass Batch D); draft order = `reverse_record_lower_pf` (`src/public_league/draft_order.py`) for verified final standings, forecasts labelled, later years round-level only; real Sleeper standings and pick ownership for `dynasty_main` | A–C (#1785 merged) | 216 unique 2027–2029 identities for `dynasty_main`; per-class totals exactly $1,200; no 2027 double count in `/trade` | per-year API with `budgetBasis`, `curveId`, `spineYears`, `inputMode`; UI unchanged except labels | **#1785** (open, `claude/draft-capital-all-years`): every Sleeper class on `/league` Draft Capital, `?year=`, per-class $1,200 pool (`budgetPolicy per_class_pool`), canonical ownership fold, refuses an unobserved `/traded_picks`; **#1579** year selector; **#1626** draft-capital correctness / lifecycle; **#1769** canonical public pick ownership; `src/identity/picks.py`, `pick_lifecycle.league_draft_years` | **TESTS GREEN; PR open** (`claude/draft-valuation-batch-e`, not merged) — see "Batch E — evidence" below |
| **F — sitewide integration, automation, monitoring, cache** (PROMPT F) | Consumer census; one `DraftCapitalGeneration` reader; swap `server.py::_rookie_dollars_from_values` and the L2:L73 read onto the canonical curve (same quantity only); keep canonical 0–9999 pick values and the trade package model untouched; receipts (`generationHash`, `curveVersion`, `targetDraftYear`, `actualInputClassYear`, `spineYears`, …); alerts; stale-while-revalidate on the last valid generation | A–E | consumer matrix with exact functions/tests; before/after payloads under pinned data | every consumer of auction dollars reads one generation; no silent value change | `src/api/pick_value_resolution.py` (market values — must stay separate), `src/api/draft_capital_years.py`, `frontend/lib/draft-capital-years.js` | **TESTS GREEN; PR open** (`claude/draft-valuation-batch-f`, stacked on Batch E, not merged) — see "Batch F — consumer census and evidence" below |
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

## Batch E — evidence (2026-10-18)

**What changed.** `src/api/draft_capital_classes.py` prices every later class
(2028, 2029 for `dynasty_main`) on the canonical rookie-auction curve instead
of #1785's interim generic-market curve, which is deleted
(`price_per_class`, `allocate_class_budget`, `canonical_pick_value`):

* **Curve.** Per class: the spreadsheet formula (`curve.compute_curve`) over
  the frozen 2026 provisional inputs (`class_snapshot.frozen_fallback_snapshot`)
  and the three most recent completed classes strictly before it
  (`snapshots.select_spine_years` — 2024/2025/2026 for both 2028 and 2029
  until 2027 completes), handed to `published.resolve_published_allocation`
  for that year: whole dollars with the formula's floors and caps, the
  independent verifier, create-only storage, and that year's last known good
  (or `unavailable`; never another year, never $0).  Batch D's promoted
  generation, when it lands, is served by the resolver ahead of this
  frozen-fallback candidate — Batch E decides no readiness.  Repo seeds:
  `config/draft_valuation/published_allocations/dynasty_main/2028/` and
  `2029/` (effective 2026-10-18).
* **Identical today, by construction.** 2027, 2028 and 2029 have the same
  inputs (frozen baseline) and the same spine, so their 72 whole dollars are
  identical ($135 … $1); each is still a separate record under its own year
  (different checksums).  They diverge when the spine rolls (2027 completes)
  or Batch D promotes a class's real inputs.
* **Slots.** A later class with no Sleeper draft order is ROUND-LEVEL: each
  round keeps its exact curve dollars, shared equally in whole dollars among
  its 12 picks (shares <= $1 apart; the extra dollars go in sha256-of-assetId
  order, so no roster is systematically favoured).  A class whose Sleeper
  draft object carries an order takes slot dollars (`known`).
* **Draft order.** `src/api/draft_capital_order.py` adapts Sleeper standings
  to THE owner (`src/public_league/draft_order.py`, `reverse_record_lower_pf`).
  Verified final standings (league `post_season`/`complete`, every team at
  the full regular-season game count incl. the median game) → the rule's
  order, `slotStatus: "final_standings"`; standings to date → the rule as a
  labelled forecast (`projected`).  A missing win / loss / tie / PF field
  makes the order `unavailable` (reason named in `draftOrder`, existing
  projected order kept); a missing `playoff_week_start` / `start_week` /
  `league_average_match` means "final" is never claimed — nothing is
  defaulted.  This replaces the workbook class's Points-For-only in-season
  reshuffle (not the league's rule).
  `playoff_sim`'s `draftSlotDistribution` is not used (not available cheaply
  in this request; one order is needed, not a distribution).
* **API.** `budgetPolicy.classes[year]` carries `budgetBasis`
  (`per_class_pool`), `curveId`, `spineYears`, `inputMode`, `provisional`,
  `allocationState`, `failedRefresh`, `lastValidAt`, `recordChecksum` — read
  from the SERVED record.  `classCurveMethods` is `workbook_rookie_auction`
  for every priced class; `interimCurveLabel` is `null`;
  `provisionalClasses` / `provisionalCurveLabel` added; top-level
  `draftOrder`.  Per pick: `inputMode`, `roundShareReferenceDollars`,
  `roundShareRule`.  Existing shape kept.  Any league but `dynasty_main`:
  later classes UNPRICED (`league_not_configured`).
* **UI.** `/league` labels only: provisional-curve note, round-share wording,
  the projected note names the rule, a final-standings note.

**Before / after — `dynasty_main`, live Sleeper 2026-10-18** (per-pick
dollars by round; every class $1,200):

| class | before (interim generic market) | after (rookie-auction curve, round-level) |
|---|---|---|
| 2028 | R1 $32, R2 $21, R3 $15, R4 $11, R5 $11, R6 $10 | R1 $69–70, R2 $19–20, R3 $5–6, R4 $2–3, R5 $2, R6 $1 |
| 2029 | R1 $32, R2 $21, R3 $16, R4 $11, R5 $10, R6 $10 | R1 $69–70, R2 $19–20, R3 $5–6, R4 $2–3, R5 $2, R6 $1 |

Team totals 2028, before → after: Chargers Team Doctor 308 → 545, Medical
Murrayjuana 274 → 144, CollinFoz 100 → 100, PorchHonkey 99 → 100, Smoke n fire
100 → 99, Unsolicited Diggs Pics 85 → 94, Queso Fresco 79 → 81, The fags
62 → 16, Pop Trunk 58 → 13, Rage Against The Achane 35 → 8, two teams 0 → 0.
2029: Chargers Team Doctor 185 → 259, Smoke n fire 153 → 190, Rage Against
The Achane 110 → 101, Pop Trunk 100 → 101, PorchHonkey 100 → 100, Unsolicited
Diggs Pics 100 → 100, Queso Fresco 100 → 99, The fags 100 → 99, CollinFoz
90 → 99, Medical Murrayjuana 122 → 46, BA's BJ's 2/1 Special 20 → 3,
JasonTuckerSheepFollower 20 → 3.  The 2027 workbook class moves only through
the draft-order rule (record first, then lower PF, instead of PF alone):
largest change ±$5 (Chargers Team Doctor 366 → 361, Smoke n fire 112 → 117).

**Independent reconciliation.** `python3 -I scripts/check_draft_capital_multi_year.py
--payload <dump>` imports nothing from the repo, fetches Sleeper itself, folds
ownership itself and re-derives the formula from its written definition:
36/36 PASS on the live board — 216 unique identities equal to its fold,
every current owner equal to its fold, each class $1,200 in whole dollars,
All Years $3,600, per-year / All Years / `teamTotals` exact sums, no 2027
double count under /trade's stack rule, the 2028/2029 stored records and the
payload equal to its own re-derivation (and the 2027 workbook class's slot
dollars too).  Mutation probes (a $1 change, a round reshuffle, an owner
swap, a duplicated 2027 pick, a missing `coveredPickYears`) each fail it.

**Named follow-up on this path?** `server.py::_parse_csv_rookies` is not on
the Batch E path (it feeds only the KTC rookie-name fallback, not any pick
dollar) — left for Batch F as recorded below.

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

## Named follow-ups

* ~~**`server.py::_parse_csv_rookies` returns 0 rookies on the current CSV.**~~
  **FIXED in Batch F** (float cells parsed; the `Composite` block read below
  its own header and paired by position, refused on a count mismatch or a
  rising value).
* ~~`server.py::_rookie_dollars_from_values` and the L2:L73 read move onto the
  canonical curve in Batch F~~ — **DONE in Batch F** for the same quantity
  (the upcoming class's dollars; the auction's 72-rookie ladder).  The legacy
  function remains for the vendor partial-list ladders and the out-of-scope
  fallback league only (census rows 6 and 9 below).
* **`scripts/backtest_perfect_draft.py --record-snapshot`** still records the
  pre-draft rookie ladder through the legacy `_rookie_dollars_from_values`
  (a dev snapshot tool, not served; it has no league draft year to give the
  canonical ladder).  Swap it when the backtest is unblocked.
* **The `rookieKtcValue` field name** carries the canonical ladder dollars
  (ours or KTC-derived, `rookieSource` says which), not a KTC value — a
  legacy name kept for /draft; renaming is a coordinated frontend change.

## Batch F — consumer census and evidence (2026-10-18)

**One reader.** `src/draft/rookie_auction/generation.py`:
`read_class_generation(league, year)` (the class's canonical candidate —
spreadsheet formula over the frozen 2026 provisional inputs and THAT class's
spine — resolved by `published.resolve_published_allocation`: current, else
that year's last known good, else unavailable; Batch D's promoted generation
is served ahead of the candidate), `generation_receipt` (the receipt, read
from the SERVED record), `rookie_ladder` (the same formula over a ranked
72-rookie list) and `generation_health` (alert rows).
`draft_capital_classes.resolve_class_curve_allocation` is a thin wrapper over
it (its `class_curve_inputs` seam kept); `resolve_workbook_allocation` is
deleted.

### Consumer matrix

| # | Consumer | Exact function | Quantity | Reads after Batch F | Tests |
|---|---|---|---|---|---|
| 1 | `/api/draft-capital` upcoming (workbook) class — 72 pick dollars | `server.py::_fetch_draft_capital` → `draft_capital_classes.resolve_class_curve_allocation` → `generation.read_class_generation` | auction dollars, same quantity as L2:L73 | **SWAPPED** from the L2:L73 candidate (`resolve_workbook_allocation`, deleted) onto the canonical reader; L2:L73 is `workbookParity` (diagnostic) | `tests/api/test_draft_capital_last_known_good.py`, `test_draft_capital_batch_f.py`, `test_draft_capital_multi_year.py`, `test_draft_capital_all_years.py`, `tests/draft_valuation/test_generation_reader.py` |
| 2 | later classes (2028/2029) `additionalClassPicks` | `draft_capital_classes.resolve_class_curve_allocation` + `price_classes_on_curve` | auction dollars | THE reader (already canonical since Batch E) | `test_draft_capital_multi_year.py` |
| 3 | team budgets `teamTotals[].auctionDollars`, `totalBudget` | `_fetch_draft_capital` (exact sum of owned whole-dollar picks) | derived from #1 | unchanged arithmetic over #1 | `test_draft_capital_last_known_good.py::_assert_reconciled` |
| 4 | per-season / All Years views | `src/api/draft_capital_years.py::attach_year_views` | sums builder dollars | unchanged (no dollars of its own) | `tests/api/test_draft_capital_years.py` |
| 5 | `/draft` per-rookie pre-draft ladder `picks[].rookieKtcValue` (ours) | `_fetch_draft_capital` → `generation.rookie_ladder` | auction dollars over the auction's rookie values (same formula) | **SWAPPED** from `_rookie_dollars_from_values` (float, workbook E cache, flat-spine fallback, any length) onto the canonical curve; exactly 72 rookies or `None`; receipt `rookieDollarLadder` | `test_draft_capital_batch_f.py`, `test_generation_reader.py` |
| 6 | `/draft` vendor ladders `rookieKtcDollar` / `rookieIdpDollar` | `server.py::_vendor_dollars_for_rookies` → `_rookie_dollars_from_values` | a vendor's PARTIAL list stretched over $1,200 (44 KTC / 70 IDPTC rookies on the pinned board) — a DIFFERENT quantity the canonical formula does not define | **LEFT** on the legacy ladder (named in its docstring); its flat `[1.0]` spine fallback now fails closed (`[]` → vendor dollars `None`) | `tests/draft/test_rookie_board_value.py` |
| 7 | `/draft` ladder when the contract is not loaded (`rookieSource: "ktc_fallback"`) | `_fetch_draft_capital` | was RAW KTC values (0-9999) under the dollar field, padded with synthetic "Rookie #N" rows | **CHANGED**: canonical ladder over the first 72 REAL KTC rookies; fewer → `None`; synthetic rows dropped | `test_draft_capital_batch_f.py` |
| 8 | KTC rookie list (inputs to #7) | `server.py::_get_ktc_rookies` → `_fetch_ktc_rookies_live` / `_parse_csv_rookies` → `_ktc_decay_curve` | KTC rookie VALUES (inputs, not dollars) | `_parse_csv_rookies` **FIXED** (was 0 rows) | `test_draft_capital_batch_f.py` (real CSV + synthetic layouts) |
| 9 | non-default league `/api/draft-capital` (Sleeper-derived fallback) + its rookie ladder | `get_draft_capital._compute` → `_rookie_dollars_from_values`; `src/api/draft_capital_fallback.py::build_sleeper_derived` | out of scope (owner scope correction 2026-10-18) | **LEFT** unchanged (legacy ladder); on live data its rookie block is already withheld by the scoring-identity gate | `tests/api/test_draft_capital_fallback*.py` |
| 10 | non-72-pick workbook | `draft_capital_classes.workbook_class_whole_dollars` | not the formula's class (no canonical curve defined) | **LEFT** (integers + exact total, round bounds not applied, receipt says so) | `tests/api/test_draft_capital.py` |
| 11 | auction room budgets | `src/auction/api.py::_draft_capital_payload` → `src/auction/sources.py::join_budgets` | reads `teamTotals` | unchanged dollars; provenance now snapshots `draftValuationGeneration` + `staleWhileRevalidate` | `test_draft_capital_batch_f.py::test_auction_budgets_snapshot_the_generation_receipt` |
| 12 | `/league` Draft Capital tab, year selector, simulator | `frontend/app/league/sections/draft-capital.jsx`, `_trade-simulator.jsx`, `frontend/lib/draft-capital-years.js`, `frontend/lib/draft-capital-budgets.js`, `frontend/lib/auction-power.js` / `src/api/auction_power.py` | renders payload dollars | unchanged (no frontend change) | `frontend/__tests__/draft-capital-*.test.js`, `components/league-draft-capital-*.test.jsx` |
| 13 | `/draft` budgets + rookie pool sync, Perfect Draft | `frontend/app/draft/page.jsx`, `frontend/lib/draft-logic.js`, `draft-feed.js`, `components/useSleeperDraftSync.js`, `frontend/lib/perfect-draft.js` | renders / optimizes over payload dollars | unchanged (reads #3, #5, #6) | `frontend/__tests__/draft-logic.test.js`, `draft-feed.test.js`, `perfect-draft.test.js`, `components/PerfectDraftPanel.test.jsx` |
| 14 | `/trade` stack note | `frontend/lib/pick-stack.js` | informational only (owner directive 2026-09-29) | unchanged | `frontend/__tests__/pick-stack.test.js`, `trade-stack-withdrawn.test.js` |
| 15 | Perfect Draft roster context | `server.py::get_draft_roster_context` → `src/draft/context.py` | board values, not dollars | not a consumer | `tests/draft/test_roster_context.py` |
| 16 | canonical 0-9999 pick values, trade package model, Manager Intel pick pricing | `src/api/pick_value_resolution.py`, contract pick rows, `src/trade/ktc_va.py`, `src/intel/manager_trade_intel.py::league_draft_capital` | market value — a DIFFERENT quantity | untouched | — |
| 17 | BDVM / Pick Projector | `src/bdvm/service.py` (`draft_capital` = NFL draft capital), `src/ros/pick_projection.py` | no auction dollars | not consumers | — |
| 18 | evidence / dev scripts | `scripts/draft_valuation_parity_report.py` (lifts the legacy function), `scripts/backtest_perfect_draft.py` | legacy ladder | unchanged; backtest is a named follow-up | — |

### Receipts, alerts, cache

* **Receipt** on every response, read from the served record:
  `draftValuationGeneration` (upcoming class), the same fields inside
  `draftValuation` and every `budgetPolicy.classes[year]` — `generationHash`
  (served record checksum), `curveVersion`, `targetDraftYear`,
  `actualInputClassYear`, `spineYears`, `inputMode`, `allocationState`.  A
  refused board (`draft_dollars_unavailable`) carries `draftYear` and the
  receipt of what it could not serve.
* **Alerts** through the existing `ops_alerts` sweep (piggybacking
  `/api/signal-alerts/run`): `server._draft_valuation_health` reads every
  configured league's owned classes through `generation_health`;
  `last_known_good` → warning, unexpected `unavailable` → critical, category
  `draft_valuation:<league>:<year>` (4-hour cooldown, one recovery notice);
  "not checked" never counts as recovered.
* **Stale-while-revalidate.** The resolver already serves the SAME year's last
  verified allocation on a failed refresh (Batch A/C).  On top of it the route
  keeps the last valid board per league (untouched by the scrape-promotion
  cache clear) and answers a failed dollars generation (`draft_dollars_*`)
  with it, labelled `staleWhileRevalidate` (served-from time, failure reason,
  `revalidateAfterSec: 60`), only for the SAME draft year and only within 6 h
  (3 x the scrape interval).  Ownership / Sleeper refusals keep refusing.

### Before / after under pinned data

Pinned inputs: the 2026-10-18 export (`exports/latest/dynasty_data_2026-10-18.json`
built into a contract — 72-rookie pool), the real workbook, stubbed Sleeper
(the Batch E harness: 12 teams, trades, 2027 retired; and the correctness
harness: the real workbook's owners), a temporary box store, live KTC off.
Base `67d8f3a5b9` (Batch E) vs this branch, every field diffed:

* **Zero value change** on every consumer: all 72 upcoming-class pick dollars,
  `teamTotals`, the 2028/2029 classes, All Years, `workbookReferenceDollarValue`,
  all 72 `rookieKtcValue` (canonical ladder = legacy float function exactly),
  the vendor ladders (unchanged code).  The canonical 2027 candidate is
  content-identical to the 2027 seed record, so the seed (same checksum)
  keeps serving and nothing new is written.
* **Added:** the receipt fields, `draftValuationGeneration`, `workbookParity`
  (`matches`, 0 of 72 differ), `rookieDollarLadder`.
* **Reworded:** `budgetPolicy.note` "The 2027 class uses the league workbook's
  dollars." → "The 2027 class is the league's upcoming auction."

**Value changes (all off the live path):**

1. *Contract not loaded and live KTC unavailable* (census #7/#8): before, the
   CSV fallback parsed 0 rookies, so every pick had `rookieName: null`; after,
   78 KTC rookies parse and the first 72 get canonical ladder dollars
   (Jeremiyah Love $134, Carnell Tate $102, Fernando Mendoza $92.5 … $1;
   total $1,200).
2. *Contract not loaded, live KTC available* (#7): `rookieKtcValue` was the raw
   KTC value (e.g. 6817 read as $6,817 by /draft) plus synthetic "Rookie #N"
   rows; now ladder dollars over real rookies, or `None` below 72.
3. *A board of fewer than 72 rookies* (#5): was a curve stretched over N picks
   (map §6 scenario E); now `rookieKtcValue: None`, `rookieDollarLadder.state:
   "refused"`.
4. *Workbook unreadable* (#6, #9): the vendor / fallback ladders were computed
   over a flat `[1.0]` spine (map §6 scenario D); now no dollars.
5. *A workbook season with no canonical curve* (e.g. a class whose spine is
   not on file and has no stored allocation): was published with the
   workbook's 2027-built L2:L73 under that year; now refused
   (`draft_dollars_unavailable` with `draftYear`) — never another year's curve.

**`_parse_csv_rookies` and the misaligned rows** (map §3).  The names block
(`W139:Y217`, header "Rank", 78 names; ranks 2 and 77 absent from the
numbering) and the `Composite` block (`Z137` header, `Z138:Z215`, 78 values)
have the same length and the values never rise, so pairing by position under
each block's own header is consistent: Love 6817, Tate 5203, Mendoza 5103.
That is an inference from the sheet's structure (equal counts, monotone
values, header offset = data offset), not an owner statement; any count
mismatch refuses the list.

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
* **Whole or half dollars for the per-rookie ladder?** Batch F keeps
  `rookieKtcValue` at the formula's half-dollar reference precision (zero
  value change).  Owner decision 9 makes `finalWholeDollars` the unit of every
  pick allocation, budget and auction transaction; whether a rookie's
  pre-draft price ESTIMATE on /draft must also be whole dollars is an owner
  call (the canonical ladder already computes both).
* **Google Sheets engine** — parity is against the Sheets export cache (10
  digits) and LibreOffice (full precision); no live Google Sheets evaluation.
