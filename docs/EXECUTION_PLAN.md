# Chase Upside / Risk It To Get The Brisket — Current Execution Plan

**Status:** CANONICAL SEQUENCING / AUTHORIZATION RECORD
**Last reconciled:** 2026-08-14 (post-B master reconciliation)
**Companion:** `docs/MASTER_PRODUCT_PLAN.md` · `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md`

This file answers **what implementation work is authorized right now**, and nothing else. It does not define
long-term product intent — that lives in the Master Product Plan, the Owner Feature Inventory, the Product
Backlog Spec and the feature specs. It does not define scope — that lives in `docs/C_SERIES_SCOPE_MANIFEST.md`.

> **A feature being approved in the long-term plan does not authorize beginning it here.**
> **Being listed in the Scope Manifest does not authorize beginning it here either.**

---

# 0. CURRENT AUTHORIZATION — READ THIS FIRST

## The B-Series is COMPLETE. No C implementation is authorized.

**Nothing in the C-Series may begin.** The B→C hard gate is reached and its replan has been performed, but the
gate is not cleared: it requires explicit owner approval, and that approval has not been given.

| question | answer |
|---|---|
| Is B complete? | **Yes.** B4–B11 merged; the B-Series Completion Audit passed (#837, `79f47ff`, 20/20 executable checks) |
| Is C authorized? | **No** |
| What is authorized right now? | Owner review of the post-B reconciliation. Plus the always-open lanes in §5. |
| What clears the gate? | Jason + ChatGPT approve the reconciliation PR and the proposed C-Series plan |
| What happens first after that? | `C1A` — see §3 |

**If you are a new session reading this file to decide what to build: the answer is that no C work is
authorized.** Read `docs/POST_B_RECONCILIATION_2026-08-14.md` for why, then stop.

---

# 1. FOUNDATION PROGRAM — COMPLETE

Every unit below is merged into `main` and is an ancestor of `HEAD`. Verified by
`git merge-base --is-ancestor` at the time of reconciliation.

| unit | scope | merge | evidence |
|---|---|---|---|
| **B4** | W30-F023 percentile-tail saturation; canonical boundary 904 | PR #805 | No Hill promotion or refit was authorized or performed. Do not reopen absent new evidence. |
| **B5** | W06 canonical player identity | PR #806 | W06-F001/F004/F007/F009 fixed; W06-F002 refuted by executable evidence — do not re-enable the retired near-name rule to satisfy the old finding |
| **B6** | W18 league-configuration correctness | PR #810, merge `5c699af`, validated head `e453889`, run 31688810982 | Factual `scoringFingerprint` replaces the profile label; unproven identity fails closed both ways. Live: the two leagues fingerprint `sf1:b7ad1575925091f6` vs `sf1:82a5f8ef2bfdb098` under one identical `scoringProfile` label, differing on 35 of 48 shared keys |
| **B7** | Realized-points correctness (W18-F003, W18-F004) | PR #820 (`af761fc`), validated head `0875da5`, run 31738127750 | |
| **B8** | Privacy / distribution / refresh boundary | PR #821 (`053f9e5`), validated head `0cc95b9`, run 31764984203 | W01-F010 and the W22 family closed on **both** distribution channels — HTTP and git |
| **B9a** | `offenseOnlyRankDerivedValue` retired; the 1–9999 scale becomes an enforced contract | PR #824 (`2e0d098c`) | A second full pipeline run whose output three engines substituted per trade: 491 of 507 comparable rows disagreed, up to 21.87%. Canonical board byte-identical after removal; build 0.62 s → 0.49 s. `apply_valuation_factors` deleted after it published 10,160 and 12,471 under `rankDerivedValue` |
| **B9b** | Threshold semantic units | PR #824 (`f0bb846`) | W29-F005 closed — a predicate comparing 0–9999 against 0–100 could not fire for any of 1,093 rows; it now fires for 19. Four thresholds registered with `unit` + `derivedFrom`. Partial by design: four board-relative constants are classified but not converted |
| **B10-T1** | Scraper KTC dedupe | — | **SATISFIED, nothing to remove.** The authorising premise did not describe canonical aggregation |
| **B10-T2** | Declare provenance | PR #825 (`e015814`) | **21 source keys → 13 provider families.** Board provably inert: 0 values moved, 0 ranks changed |
| **B10-T3a** | The market gap stops measuring retail against itself | PR #827 (`2098cad`) | |
| **B10-T3b** | One vote per provider family | PR #831 (`f0ab9e7`) | |
| **B11** | Confidence semantics | PRs #832 (`8428d99`), #833 (`263996d`), #834 (`d50de55`), validated head `70e70ca`, run 31828347707 | The spread statistic is retired and replaced by a five-axis evidence gate whose overall level is the **weakest** axis. The retired statistic could only narrow when an observation was removed, so deleting evidence promoted rows |
| **#828** | Second Opinions basis contract | `c56d0eb` | |
| **#836** | Missing is never zero on display | `62f5a39`, validated head `ef2cfa9`, run 31831875577 | |
| **#837** | **B-Series Completion Audit** | `79f47ff`, validated head `de25a58` | **20/20 executable checks PASS.** 7,548 backend tests passed / 60 skipped; 2,044 frontend tests across 125 files. Live board 1,094 rows, 812 priced in `[1, 9999]`, 282 explicitly unpriced. Verdict: *"PASS — C-Series may begin."* |

## Operational notes carried forward from the B units

These were per-unit notes in the previous version of this file. They are operational truth, not phase status, so
they survive the rewrite. Full per-unit detail is in `docs/master-site-audit/B_SERIES_EXECUTION_LEDGER.md`.

- **B4.** A future nonblocking safeguard remains open: advisory detection when an effective observed source rank
  exceeds the canonical 904 boundary, rather than silently accumulating 905+ saturation.
- **B5.** Ghost-row repair takes effect on the **next scrape**. Do not claim a historical or current board changed
  until that path has actually run.
- **B6 — operational requirement.** `data/leagues/scoring_<sleeperLeagueId>.json` must exist for a league to be
  provably compatible. The post-scrape warm pass writes it every cycle; **on a cold deploy, run
  `scripts/fetch_league_scoring.py` once**, or cross-league requests fail closed until the first scrape.
- **B6 — how to observe it.** Dispatch the read-only `Scoring Snapshot Diagnostics` workflow
  (`.github/workflows/scoring-snapshot-diagnostics.yml`). It exists because the state is otherwise unobservable:
  `data/leagues/` is gitignored and is not force-added by `scheduled-refresh.yml`, and both fail-closed branches
  — "proven different scoring" and "no verified snapshot" — produce byte-identical public responses.
  **The same run reports whether the canonical board-history recorder is scheduled**, which is the only way to
  answer manifest row `C1-RET-02` from outside the production host.
- **B6 — architecture record.** `docs/master-site-audit/evidence/W18/B6_SCORING_IDENTITY_DESIGN.md`.
- **B9b — partial by design.** Four board-relative constants are classified and registered but deliberately not
  converted, because each changes which assets a recommendation surface offers. See
  `docs/valuation/THRESHOLD_UNIT_REGISTRY.md`.

## Four bounded B residuals — carried into C1, not reopened

None of these mutates a canonical value, none has a decision consumer, and none causes irreversible evidence
loss. They are naming and determinism defects. **They do not reopen B methodology, and cleanup does not license
a methodology change.**

| residual | what it actually is | carried to |
|---|---|---|
| Board-history `rankChange` non-determinism | `_stamp_rank_changes` reads a single-slot cache then unconditionally overwrites it, so build N+1 diffs against build N's own output. Keyed by bare `canonicalName` with no asset-class namespacing. The durable history lives in a **different**, append-only log that offline builds never write, so `rankChange` for any past date is reconstructible | `C1-HIST-03` |
| `confidenceBucket: "none"` on 24 priced rows | Current-year slot picks tethered to a real value *after* the confidence loop's rank cap, retaining the row-builder default label `"None — unranked"`. The value is right; the label is wrong | `C1-CONF-01` |
| `identityConfidence` | Means player-id resolution quality, not evidence confidence. Read by nothing that gates | `C1-CONF-01` |
| `marketConfidence` | A bounded site-count + dispersion blend, diagnostic since 2026-07-30, structurally capped at 0.59375 | `C1-CONF-01` |

**Do the renames before any new confidence consumer is built.** Every consumer added first widens the blast
radius of a rename that is otherwise mechanical.

---

# 2. NEXT AUTHORIZED SCOPE

## Owner review of the post-B reconciliation. Nothing else.

The reconciliation PR delivers: the adjudication of both independent audits
(`docs/POST_B_RECONCILIATION_2026-08-14.md`), the zero-loss scope census
(`docs/C_SERIES_SCOPE_MANIFEST.md`), the traceability proof
(`docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md`), the resolved CE namespace (`docs/CE_REGISTRY.md`), the C-Series
completion contract and 24 further owner specifications promoted onto `main`, and this rewrite.

**Approving it authorizes C1A and nothing further.** Each subsequent phase requires its own checkpoint.

### The B→C gate, precisely

`docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §3 defines nine steps. Steps 1–7 — stop, no automatic C1,
plan mode, re-read everything, reconcile, build the dependency graph, produce the proposed plan — are **done**.
Steps 8 and 9 — owner review, explicit owner approval — are **outstanding**.

---

# 3. QUEUED — NOT AUTOMATIC AUTHORIZATION

The proposed C-Series spine, in dependency order. Full scope per phase is in
`docs/C_SERIES_SCOPE_MANIFEST.md` §4; the phase contract is
`docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §5.

```
C0  Truth freeze, scope manifest, dependency graph        ← this reconciliation
     │
C1  Canonical asset, pick, history and provenance         ← retention starts HERE
     ├──────────────┐
C2  Roster math    C4  Evidence ledgers
     │              │
C3  Trade substrate │        C6  Analyst / manager intelligence
     │              │             │
     ├──── C5  Seasonal engines   │
     │              │             │
     └──────► C7  Decision products ◄────────┘
                    │
C8  Premium migration (no-regret prep runs parallel from C0)
                    │
C9  Public / awards / storytelling
                    │
C10 Closure
```

## The first unit, when authorized: `C1A — Canonical asset identity, temporal evidence and retention`

Recommended, not authorized. Rationale in `docs/POST_B_RECONCILIATION_2026-08-14.md` §30.

PR-sized units within C1A, in order:

1. **Retention first** (`C1-RET-01`…`C1-RET-08`) — the only work in the plan that gets permanently harder every
   day it waits. Small, mechanical, no product surface.
2. Stable ids and schemas for players, picks, teams, leagues, sources and transactions (`C1-ID-01`, `C1-ID-02`).
3. Immutable as-of snapshot/event schema with provenance, model/config version and fidelity labels
   (`C1-HIST-01`), plus the deterministic-replay test that closes `C1-HIST-03`.
4. Confidence naming migration with aliases and a consumer census (`C1-CONF-01`).
5. Pick census through 2029 and the generic ↔ exact-slot invariant (`C1-PICK-01`, `C1-PICK-02`).
6. Dual-read adapters for the existing board, rank-history, platform, trade and pick stores.

**C1A deliberately builds no UI.** It unlocks pick valuation, roster math, historical replay, acquisition
history, market ledgers, manager intelligence, waivers and trade consolidation.

---

# 4. PARALLEL LANES

Lane names are referenced by the `lane` column in `docs/C_SERIES_SCOPE_MANIFEST.md`.

**SERIAL — one writer only:** `gov` (this file and the governance set) · `trade` package-engine extraction and VA
consolidation · anything touching `data_contract.py`'s pipeline core · the CE registry.

**PARALLEL-SAFE:** `ret` retention scripts versus everything · `perf` baseline capture (read-only) versus
everything · `psi` no-regret design prep versus all feature work · `id` schema work versus `hist` retention once
the schemas freeze · per-ledger `mkt` collectors behind a frozen schema · per-engine `season` consolidations.

**PARALLEL-CONDITIONAL:** `roster` Team Strength versus Team Weakness *after* the shared roster interface lands ·
`decide` products *after* the C3 generator and constraint-owner interfaces freeze · `psi` route migrations *after*
each route's data contract stabilizes.

**DO NOT PARALLELIZE:** two agents on the CE numbering or the backlog reconciliation — that is exactly what
produced the collision · anything that creates a second package, lineup, replacement or value engine · pick
valuation together with pick-history backfill while pick identity is unsettled · `CLAUDE.md` edits from two
branches · schema migrations on the intel ledger from two workstreams.

---

# 5. ALWAYS-OPEN LANES — not gated by the C authorization

These do not wait for the C gate and never have.

- **Production incidents and owner-reported live defects.** The Admin `fmtPassExpiry` crash (#779), the
  temporary-password path (#780), and any user-visible breakage. Schedule at a safe checkpoint; do not mix
  unrelated product changes into a tightly scoped fix.
- **Source health and freshness operations.** DraftSharks is ~219 h stale against a 24 h threshold with its
  session absent on production, so the watchdog is red every two hours while nine-day-old values still vote in
  every blend. This is operations, not C scope — but it needs an owner decision on disposition (`OD-04`).
- **Security patches and dependency updates.**
- **The retention items in `C1-RET-*` are the one grey area.** They are C1 scope by placement, but every day
  they wait is evidence that cannot be recovered at any price. They are the first thing C1A does, and if the
  owner wants them started before the wider C authorization, that is a defensible exception to make explicitly
  rather than by drift.

---

# 6. PRODUCT WORK THAT MUST NOT PREEMPT FOUNDATIONS

Approved future scope is **not** authorized merely by being approved. In particular, do not opportunistically
begin: Best Trade to Send Each Team · LOCK/EXCLUDE · persistent protection · Golden Upgrades · Package Builder ·
Trade Desk · Team Strength/Weakness · Market Trade Ledger · Pick Forecast · Manager Scout · Analyst Intelligence ·
Game Day · Share Renderer · Weekly Report Studio · Public League v3 · Awards v2 · Universal Player Profile
expansion · the AI Front Office family · the CE surfaces · Premium route migration.

They may be read during foundation work to avoid architectural contradictions.

**The dependency reason, not merely the process reason:** every one of those products consumes a substrate that
does not exist or is duplicated today. Best Trade alone needs the shared package generator (4 competing
generators today), the constraint owner (absent), whole-package market coverage (correct but disconnected),
canonical Team Strength (4 competing notions) and one Value Adjustment (5 implementations). Building it first
means building all five wrong and refitting later.

---

# 7. EXECUTION UPDATE RULE

At every owner-approved checkpoint:

1. update completed/accepted phase state here;
2. record the exact next authorized scope **only after an owner decision**;
3. leave later approved product scope in the Master Product Plan and the Scope Manifest rather than copying it
   here;
4. never let a stale phase statement in `ARCHITECTURE_HANDOFF.md`, an old audit roadmap, a planning branch or a
   session capture override this file;
5. if current code or executable evidence disproves this execution state, **reconcile this document before
   beginning another phase**;
6. **this file may state exactly one "next authorized" scope at a time.** The defect this rewrite fixes was a
   §1 that recorded B6 as merged while §2 authorized B6 as next. One record, one answer.
