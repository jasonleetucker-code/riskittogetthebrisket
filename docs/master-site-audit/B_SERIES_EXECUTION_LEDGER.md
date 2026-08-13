# B-Series Fast Lane — Execution Ledger

**Status:** IN PROGRESS
**Authorization:** owner approval of the B-Series Fast Lane plan, 2026-08-13, with 17 rulings
(R1–R15 plus execution authorization and the end-of-B rule).
**Companion:** `docs/EXECUTION_PLAN.md` (authorization record), `docs/MASTER_PRODUCT_PLAN.md`
(canonical hierarchy).

This file is the durable record of what was done, what was measured, and what was deferred, across
the continuous B7→B11 pass. It is evidence and governance — **it authorizes nothing.**

## Merge units

Nine, in dependency order. `B7.1`/`B7.2` were collapsed into one unit by owner ruling **R3**: a
knowingly RED head may never merge, so the RED detector is a development commit retained on the
working branch for provenance and only the validated GREEN head merges.

| # | unit | status |
|---|---|---|
| 0 | **B7.0** — residual B6 evidence closure + preflight | IN PROGRESS |
| 1 | B7 — realized-points correctness (RED commit → GREEN head) | not started |
| 2 | B8.1 — mechanical boundary fixes | not started |
| 3 | B8.2 — boundary policy + classification | not started |
| 4 | B9a — overlay ceiling, published formula, one canonical value | not started |
| 5 | B9b — threshold unit registry | not started |
| 6 | B10-T1 — scraper KTC dedupe | not started |
| 7 | B10-T2 — declare provenance (board byte-identical) | not started |
| 8 | B10-T3 — family-aware aggregation | not started |
| 9 | B11 — confidence axes | not started |

---

# B7.0 — Residual B6 evidence closure

Per ruling **R1**, this is preflight evidence closure, **not** a reopening of B6. Confirmation →
record and continue immediately. A genuine contradiction to B6 correctness → stop. A known
intermittent failure whose cause can be demonstrated → not a stop.

## B7.0-1 — B6 classification: MERGED AND VERIFIED

Confirmed against GitHub rather than inherited from the handoff:

| fact | value |
|---|---|
| PR #810 | `closed`, `merged: true`, `draft: false`, merged by the owner |
| merged_at | 2026-08-13T11:16:43Z |
| merge commit | `5c699afe6f325a7dab34f8c413a00f85c0bb7bf6` |
| parents | `cbd898e9940af79e2ba2fef84b9b9e2aa90f7e5e` + `e453889aed0c1f3ca0378c408d7b8b37985e3309` |
| second parent == validated head | **yes** |
| exact-head CI | run 31688810982, job 94411114861, SUCCESS, 24/24 |
| deploy | run 31694791900, SUCCESS |
| diff | 19 files, +3225 / −211, 15 commits |

**Live production evidence (unauthenticated, on the deployed revision).** `/api/draft-capital`'s
rookie block is gated by the same `_scoring_identity_error` as every other cross-league surface
(`server.py:9064`), which makes it the one public window onto the gate:

| | `dynasty_main` | `dynasty_new` |
|---|---|---|
| `rookieSource` | `ours_filtered` | **`none`** |
| picks emitted | 72 | **80** (all real picks intact) |
| priced / unpriced | — | 40 / 40, `unpricedPickYears: [2027]` |
| HTTP | 200 | 200 |

**The refusal is correct on the merits**, proven independently from the live Sleeper API using the
shipped `scoring_fingerprint`:

| | `dynasty_main` | `dynasty_new` |
|---|---|---|
| `scoringProfile` label | `superflex_tep15_ppr1` | `superflex_tep15_ppr1` |
| scoring keys / nonzero | 141 / 85 | 48 / 41 |
| fingerprint | `sf1:b7ad1575925091f6` | `sf1:82a5f8ef2bfdb098` |
| recorded season | 2026 | 2026 (current) |

35 of 48 shared keys differ (`rec` 0.08 vs 1.0, `pass_td` 6 vs 4, `pass_yd` 1/30 vs 0.04,
`pass_int` −4 vs −1, `bonus_rec_te` 0.0 vs 0.5, `fum_lost` −4 vs −2). Both fingerprints reproduce
the pre-merge measurements exactly.

**Stamp ↔ card.** The production-generated board artifact's own `sleeper.scoringSettings` derives
`sf1:b7ad1575925091f6`, identical to the live `dynasty_main` card — the identity is recomputable
from the artifact it describes. `_contract_scoring_fingerprint` implements all five required
branches (card+agreeing stamp → fingerprint; card+no stamp → recompute; card+disagreeing stamp →
`None`; foreign `sf*` version → `None`; stamp with no card → `None` as an explicit decision).

**Fail-closed properties, exercised executably:** `None → None`; `{} → None`; all-zero → `None`;
key order irrelevant; `1 ≡ 1.0`; absent ≡ explicit zero; non-numeric metadata excluded; a real
value change **is** detected.

**Missing-vs-equal.** `fingerprintsComparable` is reported separately from `fingerprintsAgree`, and
agreement is `None` — never a fabricated `false` or `true` — when the question cannot be asked.
This is what the merged head's final commit `e453889` fixed.

**Performance.** The gate takes no synchronous Sleeper call; it reads a disk snapshot refreshed
only off-path. `scoring_fingerprint` measured at **71.2 µs** on the real 141-key live card, which
is exactly the cost `_contract_scoring_fingerprint`'s memo removes.

> **Correction to the handoff:** the performance figures quoted there (≈7.84 / 7.90 / 0.30 µs;
> 0.14 µs same-league, 14.42 µs cross-league) are the *superseded uncontrolled* numbers. PR #810
> states they were taken without controlling for the `public-league-warmup` thread — under that
> contention a bare `Path.stat()` reads 882 µs — and supersedes them with controlled figures:
> evidence state 15.0 µs, league fingerprint 16.6 µs, contract fingerprint 0.6 µs, whole gate
> 31.0 µs.

> **Second correction:** the deploy's own gates do **not** verify W18. "Post-deploy smoke test"
> (`deploy.yml:614`) compares HTTP status codes only; "Validate live data contract" (`:742`) asserts
> `/api/health` `status ∈ {ok, degraded}` and warns on `has_data`. B6's verification rests on the
> evidence above, not on deploy-green.

**W18-F002.** The forbidden state requires a cross-league request that *passes* the F001 gate. No
such pair exists in production today — the only two active leagues are provably incompatible — so
every cross-league `/api/data` 503s at F001 before the F002 merge is reached. F002's defective path
is currently **unreachable in production**; its guarantee rests on the single named owner
`sleeper_overlay.merge_cross_league_sleeper_block` plus its tests. Legitimate ready remains
reachable: `dynasty_main` publishes `sleeperDataReady: true` with all three league-specific fields
complete (141 scoring keys, 58 roster slots, `num_teams: 12`, 12 teams).

## B7.0-2 — The two residual observations, and why they needed new machinery

Two items were **not observable read-only from outside the host**, and the reason is structural,
not incidental:

1. **Which fail-closed branch `dynasty_new` took** — "proven different fingerprints" vs "no verified
   snapshot". Both are correct W18-F001 behaviour and both yield `rookieSource: "none"`, so the
   public response cannot discriminate them.
2. **Whether the canonical board-history recorder is scheduled** (ruling R2).

`data/leagues/` is gitignored **and is not among the paths `scheduled-refresh.yml` force-adds**
(`CSVs/ exports/ data/canonical/ data/raw/ data/raw_sources/ data/identity/ data/player_map/
data/ros/ data/scrape_state/ data/sleeper_last_good.json`) — verified — so the snapshots never
reach git and no HTTP surface exposes them.

**Resolution:** added a read-only production diagnostic, mirroring the accepted `fd-diagnostics`
pattern (SSH from the deploy path, script piped over stdin so it runs before it ships):

- `deploy/diagnostics/scoring_snapshot_inventory.sh`
- `.github/workflows/scoring-snapshot-diagnostics.yml`

Stages 1–3 are read-only. Stage 4 runs `b6_validate.py`, which **refreshes** the snapshots, so it
is opt-in and ordered last — stage 1's pre-read is the authoritative "before" evidence either way.

This also makes B6's own stated operational requirement verifiable for the first time;
`docs/EXECUTION_PLAN.md` previously asserted it with no mechanism.

## B7.0-2b — RESULT: both residuals CLOSED with direct production evidence

Diagnostic run **31725087238** (job 94535586970), SUCCESS, read-only stages only.

**Residual 1 — which fail-closed branch `dynasty_new` takes. ANSWERED: proven-different.**
Both snapshots exist and are **FRESH**, read before anything refreshed them:

| | `dynasty_main` | `dynasty_new` |
|---|---|---|
| mtime (UTC) | 2026-08-13T17:33:17Z | 2026-08-13T17:33Z |
| age vs 6.0 h budget | **0.04 h** | **0.04 h** |
| recorded season | **2026** (current) | **2026** (current) |
| fingerprint | `sf1:b7ad1575925091f6` | `sf1:82a5f8ef2bfdb098` |
| scoring keys | 141 / 85 nonzero | 48 / 41 nonzero |
| verdict | FRESH | FRESH |

So the warm pass **is** writing snapshots on every cycle, and `dynasty_new`'s refusal is the
"**proven different fingerprints**" branch — not "no verified snapshot". Both fingerprints match
the values measured independently from the live Sleeper API earlier in B7.0, from a completely
different vantage point. B6's operational requirement is satisfied on production and now has a
standing verification mechanism.

**Residual 2 — the board-history recorder (ruling R2). ANSWERED: already running.**

```
dynasty-board-snapshot.timer  installed=yes  enabled  active
    LastTriggerUSec = 2026-08-13 09:12:51 CEST   Result=success
    NextElapse      = 2026-08-14 09:11:06 CEST
data/board_history.sqlite     2,846,720 bytes   tables: board_history, meta
    rows = 8,749   days = 8   range 2026-08-06 .. 2026-08-13  (~1,092-1,095/day)
```

(The `.service` unit reading `disabled`/`inactive` is correct for a timer-activated oneshot: the
timer is enabled and active, the service runs on trigger and exits. `Result=success`,
`ExecMainStatus=0`.)

> **Correction to the reconnaissance, and it materially improves B10.** The recon reported
> "`data/board_history.sqlite` does not exist on this checkout" and concluded that **B10-T3 would
> be unfalsifiable against the past**. That was true of the *container's clone* and false of
> *production*: the recorder has been running since at least 2026-08-06 and holds **8 days of
> canonical-scale history**. B10-T3 therefore has a real historical baseline to measure against,
> and R2's "start the recorder" is already satisfied — what remains is capturing the **immutable
> pre-B10 snapshot**, which is now a copy rather than a bootstrap.

**B7.0 verdict: B6 correctness CONFIRMED, not contradicted.** Per ruling R1, recorded and
continuing immediately into B7.

## B7.0-3 — Board-history recorder (ruling R2)

The recorder is **already implemented**: `src/snapshots/board_store.py` +
`scripts/snapshot_board.py` + `deploy/systemd/dynasty-board-snapshot.{service,timer}.template`.
R2 is therefore an *installation* question, not a code one — and `deploy/deploy.sh:687-732` already
carries a missing-timer installer written for exactly the failure `board_store.py`'s docstring
names ("nine timer pairs shipped, two installed, and a deploy that reported success the whole
time"). The B6 deploy succeeded, so the timer is expected to be installed; stage 2 of the
diagnostic verifies it rather than assuming it.

Per R2, B does **not** wait for history to accumulate. B10-T3 will use an immutable pre-change
snapshot plus controlled before/after measurement. One day of history is not long-term validation
and will not be presented as such.

## B7.0-4 — Production E2E Smoke

Dispatched against the post-B6 revision on a warm snapshot (`/api/public/league` warmed 11.9 s →
7.3 s; `/api/health` quiescent: `scrape_running: false`, `current_step: complete`).

**Result — run 31723231994, head `675e2109`: `31 passed, 1 flaky, 0 hard failures`.** The job exits
1 only because this repo deliberately sets `failOnFlakyTests`; Playwright's own status for the run
is *passed, exit 0*, and the harness prints its own banner saying so
("E2E FLAKY — THIS GREEN WAS EARNED ON A RETRY").

The flaky test and its cause, demonstrated rather than assumed:

- Test: `desktop-1366 › public /league page › deep links via ?tab= query param land on the right tab`.
- Failure: `TimeoutError: page.waitForFunction: Timeout 15000ms exceeded` at
  `public-league.spec.js:83` — a 15 s wait for body text after navigating to `/league?tab=…`.
- Cause: the page cannot render that text until `/api/public/league` returns, and that endpoint
  measured **11.9 s cold / 7.3 s warm** from outside on this same revision. A 15 s budget over a
  7–12 s dependency is the flake.
- **Not a B6 regression**, on four independent grounds: B6's `server.py` hunks do not touch the
  public-league handlers (10079–10467); the same test family failed **pre-merge** on `f04ee88`
  (run 31687123688); a **post-B6** scheduled run passed outright (31706782371, head `ce1821fc`,
  13:48Z); and this run had zero hard failures.

Per ruling R1 this is a known intermittent failure whose cause is demonstrated, so it is **not** a
stop. It is recorded as a real pre-existing latency defect — `/api/public/league` at 7–12 s — in
the deferred ledger below.

Prior context, established read-only: the workflow runs **only**
`tests/e2e/specs/public-league.spec.js` — the public `/league` page. B6's `server.py` diff hunks
are at ~1890–2245, 3293–3464, 4039, 8924, 11242–11514, 12313–12457; the public-league handlers live
at 10079–10467 and are **not touched**. The last failure before this dispatch (run 31687123688,
09:33Z) was on the **pre-merge** head `f04ee88` — it cannot be a B6 regression — and was a single
flaky test (`1 failed / 31 passed`: *"archives filter narrows the result set"*) against a visibly
intermittent history. The 7.3 s warm `/api/public/league` is the documented cause of the deep-link
flake family (15 s test budget) and is a pre-existing latency condition.

## B7.0-5 — Documentation reconciliation

`docs/EXECUTION_PLAN.md` still read *"Submitted for owner review"* for B6. Corrected to
**MERGED AND VERIFIED** with the merge/CI/deploy facts and a pointer to this ledger.

---

# Deferred defect ledger

Recorded during the pass, **not** absorbed into it (ruling R15). None is a prerequisite for B
correctness.

| id | defect | disposition |
|---|---|---|
| `W01-F010` | `/api/scaffold/status` publicly allowlisted, returns absolute production filesystem paths, zero callers. Confirmed **still live**. | B8.1 |
| — | `/api/public/league` measured **11.9 s cold / 7.3 s warm**, 2.1 MB. This is the demonstrated cause of the recurring `?tab=` / `?owner=` deep-link E2E flake (15 s test budget over a 7–12 s dependency), and it predates B6. | backlog — a latency defect, not a B-phase correctness defect; do not absorb |
| — | `src/api/rank_history.py:159 _value_from_rank` reconstructs historical values with a *rank-form* Hill family distinct from the live percentile-form masters — mean \|err\| 112.7, max 451 across 740 ranked rows. Feeds trade-history aging and every reconstructed chart. **No phase owns it.** | backlog |
| `W19-F004` | Half-fixed; per-season awards emission has no `weeksScored > 0` gate and the frontend half is unfixed. | backlog — **do not repair Awards inside B** |
| — | `tests/conftest.py:11` asserts production rejects `ALLOW_DEFAULT_LOGIN_DEV=1` "by design"; `startup_validation.py:145-167` runs 8 checks, none covering it, so `/api/health.startupChecks` reads `8/8 ok` on a placeholder-password box. | backlog |
| — | `MULTI_FORMAT_SOURCE_NORMALIZATION_SPEC.md`, `REDRAFT_ROS_INTELLIGENCE_SPEC.md`, `TRADE_HISTORY_AGING_SPEC.md` — cited by CLAUDE.md as governing methodology, **all three absent from the tree**. | flag to owner; **do not author specs inside a foundation PR** |
| — | `docs/adjusted-board-backtest.md`'s verdict was computed on the B7-defective scorer. | re-run when next relied upon |
| — | `docs/master-site-audit/ROUTE_API_JOB_INVENTORY.md:17-20` (99 ops / 36 bridges; actual 106 / 45) and every line reference in `SECURITY_AUDIT.md` are stale (`server.py` grew ~390 lines; the allowlist moved 2743 → 3130). | corrected in B8 |

## Corrections to my own earlier analysis

Recorded because they changed planning decisions:

- **`_VALUE_BASED_SOURCES` is accurate as documented.** I initially read `isRankSignal: false` on
  `draftSharks` / `draftSharksIdp` as doc drift. They are value-signal but exempt via
  `ds_combined_rank_partner`, enforced by an import-time safety rail
  (`data_contract._validate_value_based_sources_invariant`). No B10 work item.
- **The canonical board does not reach 9999 — but the league-adjusted overlay does.** My first
  measurement covered the default board only (max 9991, zero rows ≥ 9999). The overlay's unclamped
  `int(round(base * factor))` reaches **12489** at factor 1.25, with overflow beginning above
  factor 1.0008. That is B9a's highest-value item.
- **The Next bridge cannot bypass B6 in production.** `frontend/app/api/dynasty-data/route.js:239-243`
  answers 200 with a full contract where the backend answers 401/503 and ignores `leagueKey` — but
  nginx routes `location /api/` to the backend (`chaseupside-proxy.conf:54`), and production
  `/api/dynasty-data?leagueKey=dynasty_new` returns FastAPI's 401. Verified. It is a **latent**
  bypass reachable in dev/E2E, fixed in B8.1 on that basis — not a live leak.
