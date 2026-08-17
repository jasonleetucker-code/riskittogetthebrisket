# Chase Upside / Risk It To Get The Brisket — Current Execution Plan

**Status:** CANONICAL SEQUENCING / AUTHORIZATION RECORD
**Last reconciled:** 2026-08-17 (owner directive: **continuous C0→C10 campaign authorized**; routine per-unit stop-and-wait checkpoints superseded)
**Companion:** `docs/MASTER_PRODUCT_PLAN.md` · `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md`

This file answers **what implementation work is authorized right now**, and nothing else. It does not define
long-term product intent — that lives in the Master Product Plan, the Owner Feature Inventory, the Product
Backlog Spec and the feature specs. It does not define scope — that lives in `docs/C_SERIES_SCOPE_MANIFEST.md`.

> **A feature being approved in the long-term plan does not authorize beginning it here.**
> **Being listed in the Scope Manifest does not authorize beginning it here either.**

---

# 0. CURRENT AUTHORIZATION — READ THIS FIRST

## The **continuous C-Series campaign** is authorized. Owner directive, 2026-08-17.

The owner authorized continuous execution of the entire remaining C-Series and **explicitly
superseded the routine per-unit stop-and-wait checkpoints**. Units are executed in the order below
without asking permission between them.

**One record, one answer** (§7.6 still holds). The single authorized scope is *the campaign*, and
the single current unit is the one named in the queue below.

| question | answer |
|---|---|
| Is B complete? | **Yes.** B4–B11 merged; the B-Series Completion Audit passed (#837, `79f47ff`, 20/20 executable checks) |
| Is the B→C gate cleared? | **Yes.** All nine steps of `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §3 are satisfied; PR #845 merged (`6d9640c7`) |
| **What may I build right now?** | **The current unit in the queue below**, then the next dependency-eligible one, continuously |
| Which units are CLOSED? | `C1-U1` (retention — `C1-RET-07` honestly STALE) · `C1-U2` (player identity) · `C1-U3` (pick identity) · `C1-U4` (temporal ledger) · `C1-U6` (pick completeness). **Do not reopen any of them** |
| Do I stop at the end of a unit? | **No.** Mark it `CLOSED-PENDING-PROD`, enqueue it, and start the next eligible unit or a parallel-safe lane |
| When *do* I stop and ask? | Only for: a genuine unresolved owner decision · required external authorization · paid-API permission · credentials only the owner holds · an irreversible destructive operation · or a merge that now blocks **every** legitimate dependency-eligible lane |
| Is `CLOSED-PENDING-PROD` closure? | **No.** See §0.2 |
| Is `CANONICAL_V2` activation authorized? | **No** — C1-U2 measured it and deliberately deferred it; separate unit |
| Are `X-01`…`X-07` authorized? | **No.** `X-02` (Money/dues, Constitution, League Media) and `X-07` (general "link any Sleeper account" onboarding) were **restated OWNER-REJECTED on 2026-08-17** and must not be reintroduced from directive boilerplate |

Scope reconciliation for the directive, including the owner-methodology authority findings:
**`docs/C_SERIES_DIRECTIVE_RECONCILIATION_2026-08-17.md`**.

## 0.1 Campaign order

`C1-U7` sits **after `C2-U4`** and not with the rest of C1. It declares `deps C1-U6, C2-U4`
(`docs/C_SERIES_EXECUTION_MAP.md`), because an owned pick's slot distribution is a function of
simulated final standings, hence of Team Strength. Building it earlier would tune it against a
provisional formula — the thing the map's §1 ordering rule exists to prevent. It is deferred by
one dependency, not descoped.

```
C0-R   ← governance reconciliation (this unit)      C2-U6  meaningful roster core
C0-U2  performance baselines        ∥ parallel      C2-U4  canonical Team Strength
C1-U5  confidence naming migration                  C1-U7  owned-pick distributions ← unblocked
C1-U8  acquisition / cost basis / lineage           C2-U5 · C2-U7 · C2-U8 · C2-U9 · C2-U10
C1-U9  multi-format source archive                  C3-U1…U9 · C4 · C5 · C6 · C7 · C8 · C9 · C10
C2-U1  one lineup / slot assignment
C2-U2  one replacement level / PAR                  standing parallel lanes when blocked:
C2-U3  exact roster simulation                      C0-U2 · C4-U1 · C8-U1
```

## 0.2 `CLOSED-PENDING-PROD` is not `CLOSED`

A unit reaches **`CLOSED-PENDING-PROD`** on: RED→GREEN, exact-head CI green on its own PR,
evidence document written, duplicate owners retired, required documentation updated, and a named
production-verification checklist. That state authorizes **continuing to the next unit** — nothing
more.

A unit becomes **`CLOSED`** only when its production verification succeeds **against the deployed
merge SHA**. Therefore:

- **`C10` may not count `CLOSED-PENDING-PROD` units as closed;**
- the reserved completion phrase in `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §15 may not
  be used while any required production proof is outstanding;
- PR-head CI is necessary and **not** a substitute for proof on the merged, deployed tree.

## 0.3 Merge queue

Ordered. A unit leaves this queue only when production proof lands on the deployed merge.

| unit | PR | exact head | CI | unlocks | production proof |
|---|---|---|---|---|---|
| `C0-R` | [#875](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/875) | `698280e` | run 31987015120 **orphaned** — never assigned a runner (`updated_at` frozen 4 s after start, zero log bytes, HTTP 404 on the job log) while unrelated runs completed normally. Cancelled and superseded by a fresh run on the next push | every later unit — this is the record that authorizes them | pending |
| `C1-U5` | *(open on push)* | — | local gates green (hard gate + frontend 2,051) | `C2`/`C3`/`C6` confidence consumers — §1's rename-before-new-consumer rule is discharged by this unit | pending |

**Current unit: `C1-U5`.**

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

## `C1A` unit 6 — `C1-U6`, pick completeness through 2029. **CLOSED at the owner checkpoint 2026-08-16.**

Scope is exactly manifest rows `C1-PICK-01` (every valid pick through 2029 has a finite canonical
value — provenance stamped, never zero-as-missing, all surfaces agreeing) and `C1-PICK-02` (the
generic ↔ exact-slot transition survives without a second asset). Owner: the `data_contract` pick
pipeline. Deps: C1-U3 (closed). Binding calibration requirement
(`docs/MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md` §3.1, map §17): the future-year discount is a
**PRIOR** — challenger-test discount families against real market evidence; **never `0` for an
unknown future pick**. Execution-map RED: a valid 2029 pick with no finite canonical value.

**The checkpoint decision deliberately selected C1-U6 ahead of C1-U5.** `C1-U5` / `C1-CONF-01` is a
mechanical confidence-label migration with no methodology change; it is **DEFERRED, not cancelled**,
and remains unauthorized. Consequence for C1-U6 (per §1's rename-first rule): C1-U6 must build **no
new confidence consumer** — evidence quality it needs to expose goes through existing canonical
provenance/evidence structures.

**Delivered (2026-08-16).** Five RED classes reproduced on the live payload through the production
build path and closed (`tests/api/test_pick_completeness_red.py` → `test_pick_completeness.py`):
cap-truncated voted picks, vote-less future rounds 5-6, the uncalibrated clone×0.53 (audit
V-12/C-11), the clone's verbatim vendor-anchor asymmetry, and the valueless generic grade. The
year discount was challenger-tested against real market evidence per the calibration policy —
five families over 34 archive dates × two vendor pick markets, leakage-free provider/time
holdouts — and the measured per-cell vendor year-step replaced the incumbent (holdout MAPE
36.7-38.3% → 1.4-1.7%), **still classified PRIOR** because the 2-out→3-out extrapolation is
untestable on today's evidence. Rounds 5-6 derive from the canonical rookie-ladder round step;
rank-less generic-grade rows ("2027 Round 1") give `market_resolution`'s unknown-slot basis a
finite value; every pick row carries `pickValueProvenance`; the census is an ERROR gate in
`validate_api_data_contract`; `src/api/pick_value_resolution.py` is the one reference-class
resolver; the dormant second pick pricer in `src/canonical/calibration.py` is deleted; the two
authorized consumer repairs landed (draft-capital future seasons price at the generic grade,
the simulator's roster-pick labels resolve through identity instead of silently dropping).
Player-value coupling measured and explained (IDPTC backbone re-indexing, p50 ±0.1%; see the
record §8). Full record: `docs/picks/C1_U6_PICK_VALUE_COMPLETENESS.md`.

**MERGED** — PR #871, merge `ce8a8341a` (parents `801bf940d`, an automated data refresh on main,
+ validated head `edc25300d`), merged by the owner 2026-08-16 19:10:41Z.

**Exact-head CI, stated correctly.** `6d7b9dd47` passed run **31964305868 SUCCESS**, and the final
head `edc25300d` — which differs from it only by merging main's automated data-refresh commits —
passed its OWN exact-head run **31965928453 SUCCESS**, concluded 19:08:58Z, one minute and
forty-three seconds before the merge. An earlier version of this section said that run was
cancelled by the merge and never concluded. **That was wrong**, and it is corrected here and in
`docs/picks/C1_U6_PICK_VALUE_COMPLETENESS.md` §13 and §14; the direct post-merge verification that
was performed remains valid evidence, but it was an addition, not a substitute.

**What did fail** was the post-merge tree `ce8a8341a`: its *other* parent brought in a newer scrape
in which KTC had timed out (300 s against a 39-run baseline of ~18.8 s). Deploy Production run
31966802715 failed in validation and `Deploy To Production` was **skipped** — nothing shipped.
A/B on the identical payload reproduced the same contract-health status and the same
13-named / 29-with-subtests failure set on the pre-C1-U6 parent `801bf940d`, zero unique to C1-U6.
Pick completeness held on the merged tree: 162 pick rows, 2029 **24/24** finite, provenance 162/162,
zero census errors.

**STABILIZED** — the bounded repair pass of 2026-08-16 (record:
`docs/ops/STABILIZATION_2026-08-16.md`) separated deterministic code correctness from external
source health in CI, turned on the contract gate that had never once run, added the source-health
lane and the release-candidate discipline, corrected this false CI history everywhere it appeared,
and disposed of all eleven C1-U6 follow-ups (ten fixed, one proven an intentional contract and
pinned).

**CLOSED at the owner checkpoint 2026-08-16.** C1-U6 / `C1-PICK-01` / `C1-PICK-02` are closed. Do
not reopen; a value that moved during stabilization is recorded with its mechanism in the
stabilization record §6, not re-litigated.

**SUPERSEDED 2026-08-17.** This paragraph read: *"No unit beyond C1-U6 is authorized… Reaching this
point is a **STOP**… requires a new explicit owner decision at the §3 checkpoint."* That STOP was
discharged by the owner directive of 2026-08-17, which authorized the continuous campaign in §0 and
superseded the routine per-unit checkpoints. **C1-U6 itself remains CLOSED and must not be
reopened**; what changed is what happens *after* a unit closes, not the closure.

## `C1A` unit 4 — `C1-U4`, one immutable as-of value/provenance ledger. **CLOSED at the owner checkpoint 2026-08-16.**

Owner-authorized 2026-08-16 at the C1-U3 checkpoint; scope was exactly manifest rows `C1-HIST-01`,
`C1-HIST-02`, `C1-HIST-03`.

**Delivered.** The canonical temporal owner (`src/history/` — `keys`/`store`/`asof`/`record`/
`backfill`/`migrate`/`provenance`) now decides as-of lookup, historical fidelity
(`exact` / `nearest-prior` / `reconstructed` (defined, deliberately unproduced — no approved
reconstruction methodology) / `partial` / `unavailable`), missing semantics (machine-readable reasons;
the pre-2026-07-14 gap is PERMANENT, enforced at write and query), rankChange derivation
(ledger-dated comparator, read-only on every build, collision-keyed, `None` never 0 — the retired
`ranks_last.json` cache and its 740-row back-to-back divergence are deleted, closing W03-F010 as a
side effect), and historical player+pick value queries (players by C1-U2 identity, picks by C1-U3
`mpick:*` refs; the 72 rank-less slot-pick rows now record first-class). The census measured **five**
fragmented as-of decision paths (map said 4); five RED classes were reproduced on real retained data
(`tests/history/test_temporal_red.py`) and closed (`test_temporal_ledger.py` — replay determinism,
never-future property, back-to-back build determinism, valuation inertness by full double-build
equality). Archive backfill: 34/34 dates from 2026-07-14, 138,127 observations, deterministic and
idempotent. Deferred with record (manifest's own decomposition): the trade-retro/terminal/value-chart
consumer migrations (C3-U9 / C2-AGE-03). Full record: `docs/history/C1_U4_TEMPORAL_LEDGER.md`.

**MERGED** — PR #869, merge `8b6a9987` (parents `49603291e` + validated head `5940a177f`), exact-head CI
run 31955465747 green (format + lint + coercion gate + finding-drift gate + planning integrity + import
gate + full pytest + contract check + deploy syntax + frontend). The one bounded final review confirmed
and closed two release blockers before the head was validated (design record §15).

**DEPLOYED AND PRODUCTION-PROVEN** — deploy run 31958433677 SUCCESS (16:42 UTC); the read-only
`Temporal Ledger Diagnostics` run 31960075629 then measured the box directly: ledger present with
**169,896 rows across all 34 dates** (2026-07-14 → 2026-08-16; canonical_board 30,357 — board-history
migration 8,932 + rank-history migration 20,613 + the live recorder, which had already recorded the
16:45 post-deploy scrape), corrections 0, pre-boundary probe answering `before_history_boundary`, and
real as-of queries resolving on production: `mpick:2026:r1:s1` @2026-08-16 → `exact` 7,779 with rank
NULL (a canonical historical PICK value through canonical pick identity — C1-HIST-02 live) and
`player:5859` → `exact` 4,947 / rank 72 / tier 10, both stamped `live:server` with the pipeline version.

**Checkpoint outcome (2026-08-16, recorded on PR #869):** the owner reviewed and **ACCEPTED** this
unit's evidence. C1-U4 is CLOSED; the checkpoint decision authorized `C1-U6` (above) and nothing
beyond it, deliberately deferring `C1-U5`. Do not reopen C1-U4.

## `C1A` unit 3 — `C1-U3` / `C1-ID-02`, one pick identity, end to end. **CLOSED at the owner checkpoint 2026-08-16.**

Owner-authorized 2026-08-16 at the C1-U2 checkpoint; scope was exactly manifest row `C1-ID-02`.

**Delivered.** The canonical owner (`src/identity/picks.py`) now defines pick identity end to end: a
league pick's identity is `league_key + season + round + origin franchise` (current owner and realized
slot are STATE — a trade or the draft order landing never mints a new asset); market pick references
carry exactly one of slot/tier/generic grades; the generic→exact transition is a pure state change with
a deterministic `market_resolution()` that answers an unknown slot with the GENERIC grade, never a
fabricated tier or slot. The census measured **97 raw representation records deduplicating to 39 independent
pick-identity definition sites** (vs the map's estimate of 7 — see
`docs/identity/C1_ID_02_CENSUS.md`); six real defect classes were reproduced on live code paths + real league data
(`tests/identity/test_pick_identity_red.py`) — the execution-map RED (same pick, two representations, no
round-trip) among them, plus five real 2027 1sts serializing to one label, wall-clock/rename label drift,
fabricated "Mid" for unknown slots, the intel ledger's origin-stripping asset id, and league-free overlay
shapes. Consumers adapted with **byte-parity**: the contract's pick grammar, the overlay's and scraper's
ownership fold + both label grammars (pickDetails gained an additive canonical `assetId`, fail-closed on
unregistered leagues), draft-capital name formatting, and the intel crawler's persisted generic-grade key
(re-key deferred to C1-U8 with the collision documented at the owner). Board proven byte-inert:
**0 of 1,093 rows moved, 144 picks intact, 0 values, 0 ranks** (`golden_board` + `board_diff
--expect-no-value-change`). Full record: `docs/identity/C1_ID_02_PICK_IDENTITY.md`.

**MERGED** — PR #867, merge `22ce424f` (parents `f7acd646` + validated head `5a221f61`), exact-head CI
run 31938061211 green (format + lint + full pytest + livedata + contract check + frontend). The
coercion-debt ledger shrank 692 → 689 (the canonical fold removed three legacy coercion sites).

**Deliberately deferred, recorded not hidden:** the intel-ledger re-key (C1-U8), the frontend
label-lookup migration (needs C1-U6's generic-grade board rows; held in lockstep by
`tests/identity/test_pick_grammar_frontend_parity.py`), the public-league fold (bespoke multi-season
semantics; origin retained), and every valuation half of C1-PICK-01/-02/-03.

**Checkpoint outcome (2026-08-16):** the owner reviewed and **ACCEPTED** this unit's evidence. C1-U3 is
CLOSED; the checkpoint decision authorized `C1-U4` (above) and nothing beyond it.

## `C1A` unit 2 — `C1-U2` / `C1-ID-01`, one player-identity owner. **CLOSED 2026-08-16.**

Authorized 2026-08-16 by owner decision at the unit-1 checkpoint; scope was exactly manifest row
`C1-ID-01` (pick identity `C1-ID-02` is `C1-U3` and was excluded).

**Delivered and closed.** The canonical owner (`src/identity/resolution.py` +
`src/identity/name_primitives.py`) now decides player identity at both consolidation sites; the scraper's
run()-scope ladder and the contract's inline join cascade are **deleted**, along with their dead machinery
and the cutover flag, so no fallback can override the owner. The staged migration ran in full —
dual-read → compare → cut over → retire — and the production gate passed at both sites with **zero
divergence** (scraper 2,016/2,016 over a full refresh cycle; contract 24,024/24,024). A before/after
rebuild across the cutover differs on **0 of 1,092 rows**. Merge `b0c2f36`; deploy run `31921280237`.

**One thing was deliberately NOT done, on measured evidence:** `CANONICAL_V2` — the repaired semantics — is
implemented and measured but **not served**. The same production cycle showed it is not yet a strict
improvement: it would drop correct identity for four real players in the first-name-variant class
(Matt/Matthew Judon, Matthew/Matt Hibner, Michael/Mike Hall, Nikolas/Nick Martin) and refuse three more
purely because those call sites pass no position. It needs a first-name-variant rung (the repo already owns
the rule, `name_clean.is_first_name_variant`) and a no-position tiebreak. Those are canonical-identity
semantics, so they belong to a **separate authorized unit**, not to C1-U2's closure. The gap is measured
every cycle as `v2WouldChange`. Full record:
`docs/identity/C1_ID_01_IDENTITY_CONSOLIDATION.md` §9.

## `C1A` unit 1 — the irreversible-evidence retention tranche. **CLOSED 2026-08-16.**

**Was authorized as:** manifest rows **`C1-RET-01` … `C1-RET-08`** — the eight rows the Scope Manifest flags
`RET` inside phase C1. Read them from `docs/C_SERIES_SCOPE_MANIFEST.md`; that file is authoritative if this
summary and it ever disagree. Closed at the owner checkpoint; `C1-RET-07` remains honestly STALE (collection
not resumed, watchdog still exits 2 for it) and the observational follow-ups recorded in
`docs/retention/RETENTION_REGISTER.md` are hardening items, not reopeners.

Deployed as merge `47d7d243` (validated head `ef76a425`), deploy run `31869441040` SUCCESS.
Production evidence below is the **strict `ALL` watchdog run `31870347342`**, measured 2026-08-15T06:48:36Z
against the production data directory.

| row | what stops being lost | production state (final, run `31916149679`) | status |
|---|---|---|---|
| `C1-RET-01` | KTC crowd-FAAB rolling window durably retained | `ok`, 2.6 h — 2 accumulator files, **1,128 deduped rows** | **COMPLETE** |
| `C1-RET-02` | canonical board history provably recording | `ok`, 24.0 h — **10,934 rows across 10 dates** | **COMPLETE** |
| `C1-RET-03` | `rank_history.jsonl` stall detectable | `ok`, 24.0 h — 27 snapshots, missingDays=0, staleDays=1 | **COMPLETE** |
| `C1-RET-04` | scoring card at a date (today: overwritten) | `ok`, 0.1 h — **90 observations of 2 distinct cards across 2 leagues** | **COMPLETE** |
| `C1-RET-05` | Sleeper trending adds (today: discarded every 15 min) | `ok`, 0.1 h — **4,500 observations across 45 snapshots** | **COMPLETE** |
| `C1-RET-06` | own-league trade events before the rolling window drops them | `ok`, 0.1 h — **288 transactions, 288 trades, 4 leagues** | **COMPLETE** |
| `C1-RET-07` | per-source raw ingest + identity reports (halted 2026-04-20) | **`stale`, 2,812.2 h** — newest `identity_report_20260420T194828Z.json` | **STALE** — honestly labelled; **collection NOT resumed** |
| `C1-RET-08` | `playerctx` history actually landing | `ok`, 120.0 h — 2 snapshots, **both published to `origin/main` as `7730677eb`** | **COMPLETE** |

**COMPLETE means: recording on production, restored and verified from a backup, and — for `C1-RET-08` —
actually off-box.** The six recording rows are each restored and verified in run `31906622971`; the watchdog
proves they are still being written to. `C1-RET-07` is the one row that is not complete, and it is not
weakened to look like one: its collector has not resumed, the producer is not in the tree, and the strict
`ALL` watchdog still exits **2** because of it.

**The watchdog exited 2**, on a genuinely stale stream. That is the corrected semantics working, and per the
production-checkpoint instruction a stale row is *not* a reason to weaken it. It has not been weakened.

> **The backup + restore proof is green**: run `31906622971`, `RUN_BACKUP=1`, exit 0 — 16 artifacts in the
> generation, **7 retention artifacts restored and verified from the restored copies**. It exercised the deploy
> user's FALLBACK lineage and said so itself.
>
> **The unattended nightly now exists.** It did not: no `riskit-state-backup` unit, neither file under
> `/usr/local/lib/riskit/`, no `/var/backups/riskit-state` — so the seven artifacts were covered by no
> scheduled job. Installed 2026-08-16 through the deploy account's existing sudo allowlist (run
> `31915897174`), timer `enabled`/`active`/`Persistent=yes`, next elapse **02:30 UTC**, `ExecStart` rooted at
> `/usr/local/lib/riskit/`, manual oneshot `Result=success`.
>
> **A manual oneshot is not a nightly firing, and a proven fallback lineage is not a proven root lineage.**
> Both distinctions are kept explicitly in `docs/retention/RETENTION_REGISTER.md`, along with what remains
> unmeasured: the root-owned generation's contents are not readable by the deploy account.
>
> `C1-RET-07` stays **STALE on its own merits**: identity collection has not resumed and the producer is not
> in the tree.
>
> Operational record, with the full backup/restore evidence: `docs/retention/RETENTION_REGISTER.md`.

**Four other rows carry the `RET` flag but are NOT in this tranche** — `C4-FAAB-02`, `C5-GD-02`, `C7-DRAFT-02`
and `C9-UR-02` are flagged so their collection starts as early as their phase allows, but they belong to C4, C5,
C7 and C9 and **are not authorized here**.

### Minimum-substrate boundary

Some retention rows depend on broader C1 owners (`C1-HIST-01` immutable as-of storage, `C1-ACQ-01` transaction
identity, `C1-ID-01`/`C1-ID-02` asset identity). This authorization permits **only the minimum canonical
substrate needed to stop evidence loss safely** — the durable event/snapshot envelope, stable event ids,
schema/version/provenance fields, a minimal append-only storage interface, and bounded adapters or dual-writes.

It is **not** permission to complete those parent owners. If a prerequisite cannot be finished safely inside
C1A, implement the maximum non-throwaway stop-loss and record the remaining dependency — and **do not** mark the
parent owner complete.

### The B→C gate, satisfied

`docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §3 defines nine steps. Steps 1–7 were performed by the post-B
reconciliation. **Steps 8 and 9 — owner review and explicit owner approval — are now complete**, recorded by the
merge of PR #845 (`6d9640c7`) and the owner's authorization of C1A.

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

## `C1A — Canonical asset identity, temporal evidence and retention`

**Units 1–4 are CLOSED. Unit 5 of this list (`C1-U6`) is AUTHORIZED. Unit 4 of this list (`C1-U5`) is
DEFERRED; unit 6 is NOT authorized.** Original rationale in `docs/POST_B_RECONCILIATION_2026-08-14.md` §30.

PR-sized units within C1A, in order:

1. **Retention first** (`C1-RET-01`…`C1-RET-08`) — **CLOSED 2026-08-16** at the owner checkpoint.
2. **CLOSED 2026-08-16.** One player-identity owner (`C1-ID-01` / map unit `C1-U2`). Cut over, legacy
   retired, production gate green at both sites. `CANONICAL_V2` activation deferred on measured evidence —
   see §2.
3. **CLOSED at the owner checkpoint 2026-08-16 as `C1-U4`** (PR #869, merge `8b6a9987`, deploy run
   31958433677 SUCCESS; closure recorded on PR #869). Immutable as-of snapshot/event schema with provenance, model/config version and fidelity labels
   (`C1-HIST-01`), plus the deterministic-replay test that closes `C1-HIST-03`.
4. **DEFERRED — NOT AUTHORIZED** (`C1-U5` / `C1-CONF-01`). Confidence naming migration with aliases and a consumer census.
   The owner deferred it at the C1-U4 checkpoint in favor of C1-U6; §1's rename-first rule holds because
   C1-U6 builds no new confidence consumer.
5. **AUTHORIZED 2026-08-16 as `C1-U6` at the C1-U4 checkpoint.** Pick census through 2029 and the generic ↔ exact-slot invariant (`C1-PICK-01`, `C1-PICK-02`).
6. **NOT AUTHORIZED.** Dual-read adapters for the existing board, rank-history, platform, trade and pick stores.

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
- **The retention items in `C1-RET-*` are no longer a grey area** — the owner authorized them as C1A unit 1 on
  2026-08-15, precisely because every day they wait is evidence that cannot be recovered at any price. They are
  now ordinary authorized work under §2, not an exception to this section.

---

# 6. PRODUCT WORK THAT MUST NOT PREEMPT FOUNDATIONS

**Still binding under the campaign.** The 2026-08-17 directive authorized the whole C-Series *in
dependency order*; it did not authorize starting anywhere in it. Every product below is now
scheduled rather than forbidden — reached at its own unit, after the substrate it consumes exists.
Jumping to one early is the same defect it always was.

Do not opportunistically
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

Under the continuous campaign this runs **at every unit boundary**, not only at an owner checkpoint
— that is what replaces the checkpoint. At each boundary:

1. update completed/accepted phase state here;
2. advance §0.3's **current unit** and append the finished unit to the merge queue; a unit leaves
   the queue only when production proof lands on the deployed merge SHA (§0.2);
3. leave later approved product scope in the Master Product Plan and the Scope Manifest rather than copying it
   here;
4. never let a stale phase statement in `ARCHITECTURE_HANDOFF.md`, an old audit roadmap, a planning branch or a
   session capture override this file;
5. if current code or executable evidence disproves this execution state, **reconcile this document before
   beginning another phase**;
6. **this file may state exactly one "next authorized" scope at a time.** The defect this rewrite fixes was a
   §1 that recorded B6 as merged while §2 authorized B6 as next. One record, one answer. Under the
   campaign the single answer is *the campaign*, and §0.3 names the single current unit — so the
   rule is satisfied by there being exactly one **Current unit** line, not by there being one unit
   in flight;
7. when a later section contradicts §0, **mark it superseded in place with the date and the
   reason** rather than deleting it. §2's C1-U6 STOP is the worked example: the closure it records
   is still true, only its forward-looking clause was discharged.
