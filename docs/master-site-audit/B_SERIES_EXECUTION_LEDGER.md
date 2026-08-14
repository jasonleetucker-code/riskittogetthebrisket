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
| 0 | **B7.0** — residual B6 evidence closure + preflight | **COMPLETE** (merged in #819) |
| 1 | B7 — realized-points correctness (RED commit → GREEN head) | **MERGED AND VERIFIED** (#820, `af761fc`) |
| 2 | B8 — privacy / distribution / refresh boundary | **MERGED** (#821, `053f9e5`) |
| 3 | B9a — one canonical value + the scale contract | **MERGED** (#824, `2e0d098`) |
| 5 | B9b — threshold unit registry | **MERGED** (#824, partial by design — §B9b) |
| 6 | B10-T1 — scraper KTC dedupe | **SATISFIED, nothing to remove** — §B10-T2 |
| 7 | B10-T2 — declare provenance (board byte-identical) | **MERGED** (#825, `e015814`) |
| 8 | B10-T3 — family-aware aggregation | **MERGED** (T3a #827 `2098cad`, T3b #831 `f0ab9e7`) |
| 9 | B11 — confidence axes | **NOT COMPLETE** — one consistency fix landed, §B11 |

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

---

# B7 — Realized-points correctness · **MERGED AND VERIFIED**

| | |
|---|---|
| findings | `W18-F003`, `W18-F004`, new `B7-N1`…`B7-N7` |
| RED | `f740d81` — 13 failed / 5 passed; retained as branch provenance, never merged alone (ruling R3) |
| validated head | `0875da5344113c7b0b975101423f50cebda15b5f` |
| validation | PR Validation run **31738127750**, job **94574620384**, SUCCESS |
| local regression | **7144 passed / 18 skipped / 0 failed** (whole repo) |
| merge commit | `af761fc394ae37316b64b3ebf8d84dd36beae57c` |
| parents | `037865c` + `0875da5` — second parent **is** the validated head |
| main advancement at merge | 6 commits, data/exports/CSVs only, **zero file overlap** |

**Root cause.** Two scorers with inverted validation: `score_stat_line` was host-validated
(1,339 player-weeks, max |Δ| 0.0050) with one non-test caller, while `compute_weekly_points`
reached every consumer with **no host-truth test at all**.

**Repairs.** Renamed nflverse columns via candidate tuples (18.00-pt swing — penalties never
charged); first-down bonus over-charging by exactly each player's TD count; the coverage auditor
that probed the engine's vocabulary instead of the feed's; player special teams misclassified as
an unvalued asset class; kicker scoring (`0.000` → **11.48** on a real week, with `fgm_50p`
summing two feed bands); the Sleeper fallback writing combined tackles into the solo slot.

**Architecture (ruling R4).** `compute_weekly_points` is now **normalize → `score_stat_line`**.
The normalizer is deliberately scoring-independent — that separation is what removes the drift
*class*, because an allow-list keyed on vendor columns cannot distinguish "column missing" from
"rule scores nothing". Competing scorers left alone per the scope amendment; the goal is one
**active** canonical scorer.

**W18-F004** shipped with it by necessity: `players_dir` read two keys the contract never
carried, so every request answered `unmapped_player`; and scoring came from the *loaded* contract
rather than the requested league (the W18-F002 shape on a route B6 did not enumerate).

**Refused a false closure.** The audit drift gate reported C29's signature gone. The defect was
untouched — my refactor respelled its probe string. Signature updated, status left **OPEN**.

**Coverage effect.** `dynasty_main` scored 34 → 46, unscorable 8 → 11, gaps 0 *earned*;
`dynasty_new` 13 → 22 and now discloses its unscorable rules (previously: nothing).

---

# B8 — Privacy / distribution / refresh boundary · **MERGED**

Merged 2026-08-14T03:09:30Z as `053f9e5` (#821). Validated head `0cc95b9`,
PR Validation run **31764984203** — SUCCESS.

## Section classification, decided on measured content

| section | verdict | measured anonymously on prod |
|---|---|---|
| `rosTeamStrength` | **private** | 61,654 B — per-owner `benchDepthScore`, `positionalCoverageScore`, `healthAvailabilityScore`, full `startingLineup` |
| `faabAnalytics` | **private** | 87,967 B — `teamAggression`, `recentWins`, `playerHistory`; **only consumer is the private `/waivers`** |
| `rosTradeDeadline` | **private** | 19,400 B — per-owner buy/sell/rebuild + strategy text |
| `rosChampionship` | public | 178 B — odds + seeds, no `ownerId` |
| `rosPlayoffOdds` | public | 251 B — odds + seeds |
| `rosPower` | public | 5,580 B — ranking + weights, zero private markers |
| `playoffOdds` | public | 1,686 B — owners + odds, zero private markers |

`ownerId` alone is **not** the test — it is the team identifier already in public standings. The
private thing is the decomposition attached to it. `rosTradeDeadline` currently answers
"Insufficient evidence" only because it is **preseason**; it populates real per-manager calls at
week 1, so it is closed now rather than when the data arrives.

## Repairs

- **One predicate**, `public_contract.is_private_intelligence_section`, enforced by both the JSON
  and `.csv` routes — an alternate representation is the same payload, and a boundary enforced on
  one door is not a boundary.
- **League scoping.** `/{section}` took no `leagueKey` and always resolved the default, so a
  request for one league was answered with another's, byte-identical, unstamped. Unknown keys now
  400; a known-but-not-public league gets an explicit `league_not_public` refusal rather than a
  silent substitution. `_public_league_id(league_key)` makes the identity nameable.
- **Force refresh.** `force_refresh=bool(refresh)` carried two defects: `bool("0")` is `True`, so
  `?refresh=0` forced a rebuild; and nothing checked who was asking. Now one honest flag parser
  plus a session check across **9 call sites**. An anonymous `?refresh=1` is *ignored*, not
  refused — the public page keeps working. The future authenticated **Sync Sleeper / Refresh
  League Data** action is exactly the caller this admits, and is test-pinned.
- **Git channel.** `data/ros/team_strength/{latest,dynasty_new}.json` — 78 KB per league of the
  same payload the HTTP route now gates — were republished every 2 h because
  `scheduled-refresh.yml` force-adds `data/ros/` and `git add -f` overrides `.gitignore`.
  Untracked (kept on disk), `.gitignore` narrowed, and the force-add now unstages them. Safe on
  prod: `deploy.sh` uses `git reset --hard`, which leaves untracked files alone, and the ROS
  pipeline keeps rewriting them. `.gitkeep` preserves the layout a fresh checkout needs.

## Named exception — NOT silently narrowed

Three tracked files carry real per-manager payloads and are **deliberately committed audit
provenance**, not a live feed:

```
docs/master-site-audit/evidence/W17/sec-rosTeamStrength.json     63,686 B
docs/master-site-audit/evidence/W11/faab-analytics.json          86,899 B
docs/master-site-audit/findings.json                          2,021,317 B  (numericProof.inputs.ownerId)
```

Editing them changes an **audit record**, not a product surface — a judgement about the audit
rather than a code fix. They are named in `KNOWN_STATIC_EVIDENCE` and a second test fails if any
*new* documentation file starts carrying real per-manager payloads, so the carve-out is bounded
and visible. **Backlog item for owner decision.**

---

## SUPERSEDED — the `KNOWN_STATIC_EVIDENCE` carve-out above

The section immediately preceding this one describes an allowlist that named three tracked
captures and accepted them. **The owner rejected that resolution**, and it is not what shipped.
The ruling: *public Git audit provenance does not get an exception from the B8 privacy boundary*,
and *`KNOWN_STATIC_EVIDENCE` is not sufficient resolution if it merely blesses known privacy
leaks.*

What shipped instead: `scripts/sanitize_audit_evidence.py` owns one contract in one place —

* **C1 (values)** no manager identity bound to a private per-manager QUANTITY
* **C2 (records)** no manager identity bound to a private per-manager STRUCTURE

Identity becomes a deterministic non-reversible pseudonym; private quantities are nulled **with
their keys kept**, because the field's presence is what the findings assert and its magnitude is
the intelligence. Nulling matters even after pseudonymization: rank, playoff odds and championship
odds are public, so a raw decomposition table can be re-identified by joining on them.

Evidence survives — W20-F002 still reads exactly as recorded, a team at ROS strength percentile
100% labelled *Seller*, with no real person attached. Verified key-path-identical and
player-names-intact on the three largest captures (101,305 / 3,091 / 2,373 paths).

Scope was measured: a first pass banned every manager id in the audit tree, pulled in 40+ files
including 5.8 MB player-board captures, and had no privacy content. The shipped contract clears
W19 award labels and W22 trade grades — an `ownerId` beside a `label` is public league fact —
while catching all **14** real violations, 11 more than the allowlist named.

`tests/api/test_tracked_artifacts_privacy.py` drops the allowlist and asserts the contract over
every tracked file.

---

# #822 — Canonical value uniformity · **MERGED AND SERVER-VERIFIED**

An out-of-band incident that interrupted the B-series: **player values differed between mobile
and desktop.**

**Root cause.** A device-local `localStorage` setting selected a non-canonical methodology, and
that methodology **wrote the canonical field**. Three mechanisms had to line up.

**RED provenance** — `04b8b6d`, retained. A neutral GitHub runner reproduced the mechanism from a
clean checkout.

**Correction to the record.** `9,991 → 12,489` was a **synthetic `1.25` worst-case fixture**, not
observed production behaviour. Measured live: QB factor **1.018366**, Josh Allen **9,991 →
~10,175**, with finding W07-F008 independently recording 10,171. The ±25% cap has never bound on
live data. The defect was real; its magnitude was overstated in an earlier checkpoint.

**Methodology decision: C — no trustworthy league-aware canonical methodology yet.** Rejected on
seven measured defects (current-roster-state input, ordinal log-rank driver, arbitrary 0.5
reference, position-wide scalars, no scale renormalisation, no staleness detection, no
double-count guard against already-Superflex/TE++ sources) *and* on the absence of the required
outcome evidence. Full record: `docs/valuation/LEAGUE_AWARE_METHODOLOGY_REJECTION.md`.

**Device-local paths closed** — four, not the two originally reported: `valuationMode`,
`siteWeights`, `tepMultiplier`, `tepNativeMultiplier`. The latter two were found by the audit.
Three further settings (`rosSourceOverrides`, `rosTepBoost`, `leagueFormat`) have **no consumer
anywhere** — dead, recorded.

**Consumer audit** — `docs/valuation/CANONICAL_VALUE_CONSUMER_AUDIT.md`. Zero ambiguous active
consumers. Canonical aliases (`values.overall` / `finalAdjusted` / `displayValue`) confirmed exact
on 1,092 rows and now pinned.

**Protections** — invariants A–H in `test_canonical_ownership_protections.py` +
`test_canonical_value_invariance.py`.

**Evidence**

| item | value |
|---|---|
| validated head | `dfe03bf` |
| CI run / check | 31759842909 / 94643642809 — SUCCESS |
| merge commit | `daa711e` (second parent = `dfe03bf`) |
| main advancement | automated data/export refreshes only; zero source overlap |
| backend | 7432 passed / 43 skipped / 0 failed |
| frontend | 2025 passed / 123 files |
| focused | 691 passed |
| production | backend restarted 01:44:59Z (after the 01:32Z merge); `/api/health` ok, `contract_ok` true; `/league` 200; `/rankings` 307→login; `/api/data` 401 |

**Verification boundary, stated rather than papered over.** Server-side canonical uniformity is
merged, deployed and production-verified. The **authenticated rendered desktop/mobile parity
check remains owner-verifiable** because this execution environment lacks login credentials. The
stronger architectural invariant is already proven at the authority layer: clients cannot obtain
different canonical boards from the server based on the retired device-local settings. If rendered
values are ever reported to still differ, that is a **new** client/cache/bundle-version finding,
not a reopening of #822.

**Deferred** — `board_history` league/scoring-fingerprint enrichment · build/revision diagnostics ·
manual `CACHE_VERSION` residual hole · a future outcome-validated league-aware canonical
methodology · a future properly non-canonical Custom Mix redesign.

**New standing requirement recorded for B9:** every valid dynasty rookie draft pick **through the
2029 class** must have a real canonical value, derived from the canonical pick methodology, with
missing ≠ zero, cross-surface parity, and automated completeness regression. Not yet audited.

---

# B9 — Canonical player value semantics · **MERGED**

PR **#824**, merged 2026-08-14 as `2e0d098`, second parent `f0bb846` — the exact
CI-validated head (PR Validation run **31787773048**, job 94734341688, SUCCESS).
Local on that head: backend **7476 passed / 60 skipped / 0 failed**, frontend
**2025 passed / 123 files**. Main advanced only by automated data refreshes; no source
overlap.

Two merge units, both GREEN at merge. Findings closed: `W29-F001`, `W29-F002` (overlay half
closed earlier by #822), `W29-F005`.

## B9a-1 — one canonical dynasty value per asset

**Root cause.** `build_api_data_contract` ran `_compute_unified_rankings` a **second time**
with every IDP-scoped source disabled and stamped the result on each row as
`offenseOnlyRankDerivedValue`. Three engines substituted it whenever the trade in front of
them contained no defender: `suggestions.py` into `displayValue`, `finder.py` into
`modelValue`, `trade_simulator.py` into the resolved asset value **and the manager's entire
untraded roster**.

The switch was **per trade, not per league** (`trade_simulator.py:209`), so one player
carried two unlabelled numbers in one league on one day.

**Measured before removal** (2026-08-14 contract, 1,093 rows): 605 rows carried it, 507
comparable, **491 disagreeing**, up to **21.87%**. Picks moved most — 2026 Pick 2.06:
3,224 → 2,519 — because `idpTradeCalc` is a full-roster calculator, so dropping it changes
the count-aware blend, the Hampel filter, the single-source haircut and the pick anchor set
for **every** row. The mechanism was never "exclude IDP calibration from IDP-free trades";
it was a wholesale second board.

**Correction to the recorded finding.** W29-F001 and `VALUE_FLOW_MAP.md` §4 both attribute
Travis Hunter's spread to the offense-only board "never seeing the two-way boost". It saw
it. `_apply_two_way_player_boost` runs on the pre-pass; what degrades is its *input* — the
alt-position ladder needs ≥3 priced IDP rows, and on an IDP-disabled board there are none,
so the boost collapses to its single-source `idpTradeCalc` branch. 5,637 is a one-source
alt-family value; 4,401 is the multi-source blend.

**Repair.** Removed, not deprecated — a ready-made second canonical board on every row is
what let three engines wire it in without anyone deciding to. An IDP-free view **filters the
asset universe or names its lens; it does not reprice the assets**.
`suggestions._trade_is_idp_free` survives as exactly that, a universe predicate, and says so.

**Evidence.** Canonical board **byte-identical** — 0 values moved, 0 ranks changed
(`board_diff.py --expect-no-value-change`). Contract build **0.62 s → 0.49 s** median: a
duplicate pipeline pass gone.

## B9a-2 — the scale is a contract, and it is enforced

**Root cause.** #822 ruled the rejected league-aware methodology may not own a canonical
field, and closed the engine gate. One path was left: `POST /api/rankings/overrides?view=delta`
with `valuation_mode: "leagueAdjusted"` handed factors to `build_rankings_delta_payload`,
whose `apply_valuation_factors` multiplied them into `rankDerivedValue`. The ±25% bound is
on the **factor**, never on the **product**.

| factor | max canonical value on the wire | rows > 9999 |
|---|---|---|
| 1.018366 (the real measured set) | 10,160 | 2 |
| 1.25 (the cap) | 12,471 | 16 |

9,999 is the Hill **asymptote** — numbers the curve defining the scale cannot produce.

**Repair.** Ignored, not refused (the engine gate's convergence rule).
`apply_valuation_factors` and the `valuation_factors` parameter **deleted**, so there is no
seam to re-thread. Two consequences, both improvements: asking for the lens no longer
narrows scope (no 503 on league mismatch), and the response is cacheable again.

**Enforcement.** `methodology.formula` published `scaleMin`/`scaleMax` and nothing verified
them. `validate_api_data_contract` now checks `rankDerivedValue` **and the `values.*`
aliases** against `DISPLAY_SCALE_MIN`/`MAX`, imported from `src/canonical/player_valuation.py`
rather than restated — so the block that publishes the range and the check that enforces it
read one constant. An **error**, not a warning, because `scripts/validate_api_contract.py`
gates on `ok`; whole array, not the `[:1000]` prefix, because a ceiling breach lands at the
top of the board. Verified non-vacuous: injecting 12,471 into one row, or one alias, turns
the gate red.

## B9b — threshold semantic units

Full classification: `docs/valuation/THRESHOLD_UNIT_REGISTRY.md`.

**The defect class.** A threshold is a number *plus a scale*; drop the scale and the number
keeps working while its meaning drifts.

**W29-F005, and it was worse than recorded.** The "Seller cash-out" predicate compared a
0–9999 board value against a 0–100 ROS index (`dynastyValue < rosValue * 0.7`): RHS maxes at
60.8, the board's floor is 1,134, so **0 of 1,093 rows** could fire and the tag had never
rendered. Its unit test passed — on `dynasty_value=40`, an input the board cannot produce.
*A test with no unit discipline validated a predicate with an empty solution set.*

The undocumented half: the same classifier gated "strong"/"elite" on `rosValue >= 60`/`>= 80`
as if the index were a percentile. Measured across **all 893 historical aggregates
(2026-04-28 → 2026-08-14)**, that index has median 9.15 and p99 **59.41** — so `>= 60` sat
above the 99th percentile, selecting 0.87%, and its complement labelled **99.13%** of the
pool "Injury/bye cover".

**Repair.** Four thresholds registered in `config/thresholds.json` with `unit` +
`derivedFrom`, converted to percentile units. Measured effect:

| tag | before | after |
|---|---|---|
| Seller cash-out | **0** (unreachable) | 19 (1.84%) |
| Injury/bye cover | 99.13% | 55.87% |
| Contender upgrade | 2 players | 47 (4.56%) |

Structural, because triplication is what let it survive review three times: `rosPercentile`
stamped server-side over the **whole** pool (the endpoint truncates to `limit`, so a client
standing would be a standing within the top half); `canonicalPercentile` stamped on contract
rows for the same reason; **one** classifier in `frontend/lib/ros-index.js` mirroring
`src/ros/tags.py`, with the parity test a JS comment had promised as "PR-future" and that was
never written. All nine tags now have a reachability test.

**Not closed, and specified rather than attempted:** four BOARD-RELATIVE constants
(`MIN_RELEVANT_VALUE`, `MIN_ACTIONABLE_VALUE`, `MIN_WAIVER_VALUE`, the `>= 7000` contender
gate) are classified and registered but not converted — each changes which assets a
recommendation surface offers, which needs its own before/after measurement.

---

# Deferred defect ledger — additions

| id | defect | disposition |
|---|---|---|
| — | `inferValueBundle` coerces an unpriced row to **0** (`frontend/lib/dynasty-data.js`). The rationale on the function is sound as far as it goes — it replaced a fallback that put a *composite-scale* number into board-scale sums — and 0 is neutral **in a sum**. It is not neutral in a sort, minimum, average or display, where it asserts "worth nothing". `MISSING IS NEVER ZERO` wants `null`. Blast radius: trade sums, portfolio, movers, team-phase, CSV export. | **must-fix-before-C candidate** — measure, then convert |
| — | The consolidation search still restricts all-offense give-pairs to offense targets. Its only stated justification was avoiding a value-scale flip, which no longer exists. Removing it widens the recommendation universe — a product decision. | owner decision |
| — | KTC-native constants duplicated across `src/trade/market_value_adjustment.py` and `src/trade/ktc_va.py` — one concept, two owners. | backlog |

---

# B10 — reconnaissance only, NOT started

Recorded because it **corrects the authorising premise**, which should not be discovered
twice.

**The "ktc ≈ 1.3 + ktcSfTep ≈ 1.0 → 2.3 vs IDPTC 1.0" double-count does not exist on
current main.** Measured on `_RANKING_SOURCES`: there is **no `ktc` source key**. There is
one KTC-family entry, `ktcSfTep`, at weight **1.00**, and **all 21 sources are 1.00** —
consistent with CLAUDE.md's "all 1.0 by policy". Any B10 plan resting on the 2.3 figure is
resting on a stale reading.

**The real structure**, and it is still a genuine independence problem:

* `correlationGroup` is **`None` on all 21 sources** — no provider family is declared
  anywhere, so nothing downstream *can* deduplicate by family.
* Providers contributing more than one source key: **DLF ×4**, **FantasyPros ×3**,
  **Flock ×2**, **DraftSharks ×2**.
* The nested-consensus case the owner ruled on is live and measurable:
  `fantasyProsSf` (544 players, an expert **consensus**) and `fantasyProsFitzmaurice`
  (299 players, **one expert inside that panel**) are both `overall_offense`, both weight
  1.00. Measured: Fitzmaurice is **100% contained** in the consensus board, Pearson
  **r = 0.9297**, median |rank diff| 12. Declarative provenance, not inferred from the
  correlation: the source's own display name is "FantasyPros / Pat Fitzmaurice SF-TEP".

Per the owner's ruling, family lineage must be **declarative**, so the correlation above is
corroboration, not the basis. B10-T2 (declare provenance, board byte-identical) is the next
unit and has not been started.

---

# B10-T2 — Declare provider families · **MERGED**

Declares which sources share a provider. Changes nothing about how they are counted —
that is T3, and keeping the two apart is what makes each reviewable: a declaration with a
provably nil board effect is reviewed on whether it is TRUE, an aggregation change on what
it MOVES.

## What was undeclared

19 of 21 sources declared no `correlation_group`, so `correlation_group_for` defaulted each
to its own key and every one counted as an independent opinion. Measured on the tracked
2026-08-14 CSVs:

| provider | boards | rows it votes on more than once |
|---|---|---|
| FantasyPros | `fantasyProsSf`, `fantasyProsIdp`, `fantasyProsFitzmaurice` | **299** |
| Flock Fantasy | `flockFantasySf`, `flockFantasySfRookies` | 70 |
| DLF | `dlfSf`, `dlfRookieSf`, `dlfIdp`, `dlfRookieIdp` | 52 |

**21 source keys → 13 independent provider families.**

FantasyPros is the owner's nested-consensus ruling made concrete: `fantasyProsSf` is a
544-player expert **consensus** and `fantasyProsFitzmaurice` is **one expert inside that
panel** — 299 players, **100% contained**, Pearson **r = 0.9297**, median |rank diff| 12.

Lineage is **declarative**: the source's own `display_name` is "FantasyPros / Pat
Fitzmaurice SF-TEP". The correlation corroborates and is not the basis, per the rule that
family ownership must never be inferred from output similarity.

## Inertness

* `board_diff.py --expect-no-value-change`: **0 values moved, 0 ranks changed**
* **structural** — a test asserts `_compute_unified_rankings`' source contains neither
  `correlation_group` nor `expand_correlation_groups`, so the blend cannot start consulting
  families as a side effect of declaring one more provider
* **live output** — the only consumers are leave-one-out and Consensus Edge, and
  `consensus_edge` defaults `False` (`src/api/feature_flags.py:296`)

## Correction to the authorising premise — do not re-derive

B10 was scoped around "ktc ≈1.3 + ktcSfTep ≈1.0 → ≈2.3 vs IDPTC 1.0". That does not
describe canonical aggregation on this tree:

* no `ktc` entry in `_RANKING_SOURCES`; the KTC family votes canonically **once**, through
  `ktcSfTep`, at weight **1.00**;
* **all 21 sources are weight 1.00**;
* the `1.3` is real but is `LEGACY_COMPOSITE_SITE_WEIGHTS` in `Dynasty Scraper.py`, scoped
  by its own docstring to `_composite` and pick-row blending;
* `ktc` appears in `canonicalSiteValues` (464 rows, the same rows as `ktcSfTep`) but is not
  a registered source, so it casts no vote — verified, not taken from the docstring.

**B10-T1 (scraper KTC dedupe) is therefore satisfied for canonical aggregation**: there is
no canonical KTC double-vote to remove. The `1.3` still shapes `_composite`, which reaches
users only through the UI's explicit "Raw" value mode and the finder's legacy no-contract
path — recorded, not absorbed.

## Test changed, not weakened

`test_fair_value.py::test_an_independent_source_expands_to_only_itself` named `dlfSf` as
its independent example. That **stopped being true** rather than stopped being tested. It
now names `fantasyCalc`, and a companion test covers the direction that does not fail
closed: a declared member must expand to the whole family.

## Validation

| gate | result |
|---|---|
| board inertness | 0 values moved, 0 ranks changed |
| backend, whole repo | **7483 passed / 60 skipped / 0 failed** |
| frontend | **2025 passed / 123 files** |
| ruff | clean |

---

# B11 — reconnaissance, measured on current main (2026-08-14)

Read-only. Not started as a merge unit.

## The computation, in full

`data_contract._compute_confidence_bucket(source_count, source_rank_spread, percentile_spread)`
reads **exactly two things**: how many sources ranked the row, and how far apart they are.

```
source_count >= 2 and percentile_spread <= 0.08  -> high
source_count >= 2 and percentile_spread <= 0.20  -> medium
source_count >= 1                                -> low
otherwise                                        -> none
```

Not inputs, at all: **freshness**, **coverage**, **independence** (it counts raw source
keys, so a provider contributing three keys counts as three votes — B10's defect leaking
into B11), **missingness**, **degraded state**, **staleness**.

## Live distribution (1,093 rows)

| bucket | rows |
|---|---|
| low | 441 |
| none | 305 |
| medium | 243 |
| high | 104 |

305 rows carry `none`; **24 of them are PRICED**. A priced row with `none` confidence is
the "unknown rendered as a confidence level" case — the label is
`"None — unranked"` on a row that is, in fact, ranked and priced. 18 more carry
`"None — generic tier suppressed in favor of slot-specific picks"`, which is a *suppression*
state wearing the same word as *no evidence*.

## The monotonicity defect — CONFIRMED, and it is strict

Rebuilt the whole board with one source disabled and compared buckets row by row:

| source removed | confidence ROSE | fell | unchanged |
|---|---|---|---|
| `dlfSf` | **26** | **0** | 1,067 |
| `fantasyProsSf` | 20 | 9 | 1,064 |
| `yahooBoone` | 13 | 6 | 1,074 |

`dlfSf` is the pure case: deleting a source **can only help**. Examples — A.J. Brown
`medium → high`, Cam Ward `medium → high`, Blake Corum `low → medium`, all by *removing*
evidence.

The mechanism is immediate from the formula: the bucket is decided on the **spread** of the
sources that remain, so dropping a disagreeing source narrows the spread and promotes the
row. Nothing in the calculation knows that the evidence base got smaller.

`B.J. Hill` goes `none → low` when `fantasyProsSf` or `yahooBoone` is removed — a row
gaining a confidence label because a source disappeared.

**Note on the authorising figure.** The prompt records "192 of 683 rows". Today's
measurement is smaller (26 of 1,093 for the cleanest case). The *direction and mechanism
are identical and confirmed*; the magnitude is not, and should not be quoted as 192 without
re-measuring.

## Not yet measured

- The staleness claim ("feeds ~186.9 h old still accounted for 76 of 102 High rows").
  `dataFreshness` on the built contract did not expose a per-source `stale` map in the shape
  probed, so the coupling was not tested. Freshness is definitionally not an input to the
  bucket, so the *structural* claim holds regardless; the row count does not.
- Which decision engines consume `confidenceBucket` as a gate. The owner ruling requires
  those to be re-gated deliberately against the new named dimensions, not silently moved by
  a presentation change.
- `identityConfidence` / `marketConfidence` — the misleading-name half of the ruling.

---

# B11 — Defensible confidence · **NOT COMPLETE** (one consistency fix landed)

## What landed

`_compute_confidence_bucket` now receives `independentSourceCount` (post-Hampel,
post-family-collapse) instead of the raw post-Hampel key count. Its `n >= 2` gate is a
corroboration statement — "more than one opinion agrees" — so it must count opinions the
way the blend does after B10-T3b. Before this, the two disagreed on **512 rows**, including
**59 of the 102 HIGH rows**, which claimed more independent corroboration than the board
had actually used.

**Measured effect: none. 0 values, 0 ranks, 0 labels.** Recorded as such rather than
implied to be a repair.

## Why it is inert, and why that matters more than the fix

I predicted 11 `high → medium` demotions and got zero. Chasing the discrepancy is what
produced the real shape of B11:

**The count is used ONLY as a `>= 2` gate.**

```
n >= 2  ->  percentile_spread decides high / medium
n >= 1  ->  low
n == 0  ->  none
```

So going from 14 keys to 12 families changes nothing; only a row dropping from 2 keys to
1 family could move, and there is exactly **1** such non-pick row on the live board.

**What actually decides the bucket is the spread — and the spread is still measured across
correlated sources on 478 of 893 non-pick rows.** Two members of one family agreeing
inflates apparent agreement, and agreement is the whole signal. That is the substantive
defect, and it will move labels when fixed.

The fix is kept anyway: it removes a live contradiction between B10 and B11 (blend counts
families, confidence counted keys), it is provably harmless, and leaving it would make the
next pass rediscover it.

## What B11 still owes

| item | status |
|---|---|
| spread measured over correlated sources (478 rows) | **not started** — the substantive one |
| freshness as an input | **not an input at all** |
| coverage as an input | **not an input at all** |
| missing / degraded / stale / conflicting as distinct states | **not started** — all collapse to `low`/`none` |
| `none` on a PRICED row (24 rows) | **not started** — "unranked" label on a ranked row |
| rename `identityConfidence` (means "player id resolved") | **not started** |
| rename/remove `marketConfidence` (a bounded dispersion metric) | **not started** |
| deliberate re-gating of any decision engine consuming confidence | **not started** |

## Monotonicity — still open, re-measured post-T3b

Removing `dlfSf` raises the bucket on **26 rows and lowers it on 0**; removing
`fantasyProsSf` raises 23 and lowers 11. Deleting evidence can still only help, because the
bucket is decided on the spread of whatever sources remain and nothing knows the evidence
base got smaller.

The authorising figure of "192 of 683" remains larger than anything measurable today and
should not be quoted without re-measuring.

## B11 — the spread cannot be fixed by re-basing it (measured, reverted)

The obvious next step after the count fix was to compute the percentile spread over
independent evidence too — one member per provider family — since the spread is what
actually decides HIGH vs MEDIUM and it was being measured across correlated sources on
478 of 893 non-pick rows.

**It was implemented, measured, and reverted.** The measurement is why.

| effect | measured |
|---|---|
| rows flipping bucket | **60** |
| direction | **PROMOTIONS** — e.g. A.J. Brown `medium → high` |

The cause is structural, not a bug in the attempt. The spread is `max − min`, so **removing
any source can only narrow it**. Dropping a family's duplicate members therefore *tightens*
the apparent agreement and promotes the row — which is precisely the monotonicity defect
B11 exists to cure, reproduced by the fix meant to address it.

**The statistic is the defect, not its input.** `max − min` measures the width of whatever
set it is handed; it cannot distinguish "these sources genuinely agree" from "there are
fewer sources left to disagree". Re-basing it onto independent evidence makes confidence
*more* wrong, not less: 60 rows would have gained HIGH on strictly less evidence.

So the remaining B11 work is a **redesign, not a patch**, and it matches the owner ruling
directly: HIGH must require *sufficient independent family evidence* AND *acceptable
freshness* AND *tight agreement* AND *adequate coverage* — a multi-axis gate where the
evidence count constrains the ceiling, rather than a single spread threshold behind an
`n >= 2` door.

A dispersion measure that does not shrink when you delete data (a variance or IQR-style
statistic normalised by n, rather than a range) is likely part of the answer, but choosing
one is model work with its own validation burden and is not attempted here.

Recorded rather than shipped: nothing merged from this attempt. The board is byte-identical
to the post-#832 state (0 values, 0 ranks, 0 labels).

---

# B11 — RESOLVED. The multi-axis confidence gate

The redesign the section above said was needed. Implemented, measured, shipped.

## What was wrong, restated precisely

Confidence was `max(percentile) − min(percentile)` over a row's contributing sources,
bucketed at 0.08 / 0.20, behind an `n >= 2` count gate. Two faults:

1. **A range can only narrow when an observation is removed.** Under "narrower ⇒ more
   confident", deleting evidence promoted a row. That is the monotonicity failure, and
   re-basing the same statistic onto independent evidence reproduced it (60 rows, wrong
   direction, A.J. Brown `medium → high`).
2. **One axis wearing two hats** — a count and a dispersion — with nothing asking whether
   the evidence was independent, current, applicable to this board's format, or anywhere
   near complete. A large source count silently compensated for all four.

## The replacement

`src/api/confidence.py` is the single owner. Five axes over **B10 provider families**,
combined by **bottleneck** — the overall level is the weakest axis. Nothing averages, so a
strong axis cannot buy a weak one. That is the owner ruling ("a huge source count must not
compensate for poor freshness / applicability / independent-family coverage / severe
disagreement") written as arithmetic instead of as a weighting.

| axis | question | HIGH requires |
|---|---|---|
| independence | how many B10 correlation-group heads voted | ≥ 5 families |
| coverage | how many of the **eligible** families actually did | ≥ 75% |
| freshness | how many of those are inside their `maxAgeHours` budget | ≥ 75% |
| applicability | how many reached the row without approximation, on this board's TE basis | ≥ 75% |
| agreement | how many price within 15% relative of `rankDerivedValue` | ≥ 75% |

Every parameter is in `config/confidence/gate_v1.json` with a unit and a derivation; the
module contains no numeric literal that decides a level.

## Every number is derived from something already declared

- **5 / 3 families** — the count-aware blend's OWN rungs. `_mean_median_blend` trims one
  extreme per side at k ≥ 5, so five families is the smallest panel where the published
  value is robust to a single outlying opinion in either direction; n = 3-4 is the
  untrimmed rung, n = 2 a plain mean, n = 1 a passthrough. Two families therefore cannot
  exceed LOW, which is the owner ruling on "excellent agreement between only one or two
  evidence families" enforced structurally.
- **0.75 / 0.50** — one sufficiency ladder for all four share axes rather than four
  separately-invented cutoffs. A stated prior, recorded as one. Distribution check on the
  live board puts it inside the body of all four (coverage p25 0.750 / median 0.917;
  freshness p25 0.750 / median 0.909; agreement p25 0.636 / median 0.800).
- **0.15 relative value** — the board's existing declared line for a MATERIAL relative
  value gap (`PREMIUM_SUMMARY_VALUE_RATIO`, p70 of `|marketGapValueRatio|`), measured with
  the SAME symmetric mean normalisation `_compute_market_gap` uses so it means the same
  size of disagreement in both places. Its own registry entry so the two can diverge
  deliberately rather than by accident.

## Why the monotonicity invariants hold

- **Duplicates cannot create confidence, and removing them cannot promote (invariants 1
  and 2)** — an exact IDENTITY, not a bound. Every axis is computed over family heads, so
  a second observation from a represented family is not an input to anything.
  `assess_confidence` **refuses** a duplicate family rather than averaging or ignoring it,
  because both of those are ways for a duplicate to matter after all. This is the A.J.
  Brown case: he is HIGH whether or not FantasyPros also published a Fitzmaurice row.
- **Removing real evidence cannot pay (invariant 3)** — `coverage`'s DENOMINATOR is what
  COULD have been observed, not what was. A family that stops covering a row stays
  eligible, so its silence is registered as missing evidence permanently. MISSING IS NEVER
  ZERO applied to confidence: an absent eligible source is explicit missingness, not a
  neutral non-event. Confidence can still rise when the departed evidence was stale or
  inapplicable — the ruling permits that — and the reason is then on the row.
- **No axis is a range.** Pinned by a test that moves an interior family while holding the
  extremes, which a range cannot notice.

## Agreement moved from rank space to value space, and that is load-bearing

A family agrees when its `valueContribution` is within 15% relative of the published value.
Value is the right currency for the same reason it was right for the market gap: it is what
the blend itself compares sources in.

Checked for the opposite bias before adopting — value-space agreement could have become
mechanically easier where the Hill curve flattens. It does not: the within-tolerance share
FALLS with depth (median 1.000 in the top 100, 0.917 at 101-200, 0.750 at 201-800).

It also catches disagreement the percentile statistic structurally could not. Jalen Carter
(DL, rank 239) has a percentile spread of **0.0412** — comfortably inside the retired HIGH
band — while `draftSharksIdp` prices him **26% below** consensus. He is now LOW, limited by
agreement, with the disagreement named on the row.

## A defect this change created, found and fixed

`_apply_two_way_player_boost` runs AFTER the ranking loop and replaces `rankDerivedValue`
with the alt-position family's value. The retired rule never read the value, so this
coupling is **new with the gate**. Travis Hunter's boost lifts him from the offense blend's
~2,900 to 4,758, leaving all eleven of his families 24-56% BELOW the published number while
the pre-boost stamp still claimed high agreement.

Fixed by `_restate_confidence_after_override`, written as a general guard over "did the
value move since the gate ran" rather than as a special case for the boost table, so any
future post-blend pass inherits it. Travis Hunter now reads
`Low — limited by agreement · 0 of 11 families price within 15% of the published value`,
which is an honest description of a deliberate override no source published.

## Picks

Picks keep their own coefficient-of-variation gate — rank spread on picks is dominated by
the flat-value regions in R3-R6 — but it is now **family-aware**: `dlfSf` and `dlfIdp` are
one declared family and were counted as two corroborating opinions. Measured before
changing it: **0 of 144 live pick rows** carry two members of one family, so this closes
the hole rather than moving a number, and it is pinned so it cannot open again quietly.

**Named boundary, not an exemption that leaked:** 24 pick rows are HIGH on 2 evidence
families. Picks' eligible population only HAS 2-4 families (KTC + IDPTC are the two real
pick markets), so the 5-family bar — derived from the *player* blend's trimming rung — does
not apply to them.

## OLD vs NEW distribution

Full audit and the reproducing script:
`docs/master-site-audit/evidence/B11/confidence-distribution.md` + `audit.py`.

Both sides measured over the **same pinned payload** — the 2026-08-14T17:41 export — with
the OLD side built from a worktree at the pre-B11 commit. Pinning it is the point: a
scheduled refresh landed mid-review, and comparing across refreshed inputs would have
measured the scrape rather than the gate. (For the record: on the earlier 16:32 export the
same code gives 257 / 354 / 177 / 306, so the shape is a property of the gate and the
counts move by a handful of rows with the data, as they should.)

| bucket | OLD | NEW | delta |
|---|---:|---:|---:|
| high | 102 | 253 | +151 |
| medium | 245 | 357 | +112 |
| low | 441 | 178 | −263 |
| none | 306 | 306 | 0 |

upgraded **428** · downgraded **77** · unchanged **589**

The OLD board was saturated, and the shape shows it. By depth (high/medium/low):

| band | OLD | NEW |
|---|---|---|
| 001-100 | 61/38/1 | 79/20/1 |
| 101-200 | 10/65/25 | 58/35/7 |
| 201-400 | 15/41/144 | 72/106/22 |
| 401-800 | 16/101/223 | 44/196/100 |

Ranks 101-200 carried 10% HIGH against the top 100's 61% — a cliff with no evidentiary
basis, produced by the percentile spread growing mechanically with depth. NEW declines
monotonically with depth, which is what "confidence in a value" should do.

Checks the ruling asked for specifically:

- rows upgraded with fewer than 3 independent families: **0**
- PLAYER rows reaching HIGH with fewer than 5 independent families: **0** (structurally
  impossible — the independence axis caps them)
- rows upgraded that are missing at least one eligible family: 196 — all constrained by the
  coverage axis, all with the gap named on the row
- 77 rows were downgraded; every one names its binding axis. The clearest are the OLD
  board's own defects: Ashton Gillotte (DL, rank 672) was HIGH on **1 family and 20%
  coverage**; RJ Maryland (TE, rank 509) was HIGH on 2 families.

## Downstream consumers — a deliberate widening, stated

`frontend/lib/edge-helpers.js` gates four surfaces on `confidenceBucket === "high"`
(Consensus asset label, /edge consensus section, arbitrage eligibility). Those surfaces now
see 253 qualifying rows instead of 102. That is the intended consequence of the OLD gate
being saturated rather than an accidental blast radius, and no threshold in
`edge-helpers.js` was touched to compensate — re-aiming a display filter to preserve its
old row count would be tuning the answer to the previous wrong question.

## Board integrity

`rankDerivedValue` moved on **0 of 1094 rows**; `canonicalConsensusRank` moved on **0**;
**no non-confidence field changed at all**. Confidence is not value, verified on the whole
board rather than asserted.

Payload cost: production delta 3.864 → 4.136 MB raw, **314.3 → 334.1 KB over the wire**
(+6.3%) for the axes and reasons. `confidenceMetrics` was deliberately left OFF the payload
to hold it there — the reasons already carry its numbers in readable form.

Observed and **not** caused by this change: `rankChange` differs between two back-to-back
builds of identical code on 740 rows. The rank-history recorder writes a snapshot each
build and the next build diffs against it. Named here because it is the one thing a
board-diff of this change shows, and it would otherwise read as B11 movement.

## What B11 no longer owes

| item | status |
|---|---|
| spread measured over correlated sources | **resolved** — the statistic is retired, not re-based |
| freshness as an input | **shipped** — its own axis |
| coverage as an input | **shipped** — its own axis, denominated on eligible families |
| applicability as an input | **shipped** — its own axis |
| missing / stale / conflicting as distinct states | **shipped** — distinct axes + published reasons |
| duplicate evidence cannot inflate confidence | **shipped** — an identity, pinned |
| removing evidence cannot promote for mechanical reasons | **shipped** — coverage denominator |
| explainable rather than a bare score | **shipped** — `confidenceAxes` + `confidenceReasons` |
| one canonical owner, no frontend confidence math | **shipped** — gate parameters are deliberately NOT mirrored to `thresholds.js` |

Still open, and deliberately out of B11's scope — naming rather than fixing, because each
is a rename with its own consumer blast radius:

| item | status |
|---|---|
| `none` on a PRICED row (24 rows) | **open** — "unranked" label on a ranked row |
| rename `identityConfidence` (means "player id resolved") | **open** |
| rename/remove `marketConfidence` (a bounded dispersion metric) | **open** |

## A stale B10 guard, found by B11 and repaired

`test_source_provenance.py::test_the_canonical_blend_does_not_read_correlation_group`
asserted that `_compute_unified_rankings` contains no mention of `correlation_group`. That
was the right guard for **B10-T2**, whose entire reviewability rested on declaring families
while moving no value.

**B10-T3b retired that property on purpose** — 455 values moved, with its own before/after
envelope — and the guard did not notice, because T3b reached the family through a helper:
`collapse_to_independent_families` calls `correlation_group_for` internally, so the literal
string never appeared in the caller. It stayed green for two merges while describing a
property that had stopped holding.

B11 tripped it only because the confidence gate needs a family per source and resolves the
map inline. Replaced with the property that is actually true and worth pinning: **family
membership is resolved through the declared owner and nowhere else**, and no provider
family is named as a literal inside the blend. A guard that survives the change it was
written to catch is worse than no guard — it reads as evidence.

---

# `inferValueBundle` missing-as-zero — RESOLVED

The last must-review-before-C item. Reviewed as its own unit, as required.

## What the coerced zero actually is

`inferValueBundle` maps a missing board value to `0`, and both materializers stamp
`values.full = Math.round(backendValue || 0)`. On the live board **282 of 1,094 rows** carry
`rankDerivedValue: null` — the backend says so explicitly and even publishes the count as
`rowsUnpricedByBoard: 282`.

Every semantic use, traced:

| use | verdict |
|---|---|
| `sideTotal` / Value Adjustment arithmetic | **legitimate.** 0 is a neutral element here, and dropping the row instead would shrink the piece count VA is a function of — a different and worse distortion |
| `displayValue` → trade search result, "Our Value" tile, value-chain header | **defect.** Rendered `0`, which claims we priced the asset and found it worthless |
| value-override input placeholder | **defect.** Suggested `0` as the number to beat |
| multi-team incoming-asset meta | **defect.** Same |
| side total → gap → verdict → TradeMeter | **defect of omission.** The arithmetic was defensible; publishing the verdict without saying which pieces contributed nothing because nobody priced them was not |
| waiver add pool (`buildCandidatePool`) | **clean** — filters `rowValue <= 0` |
| waiver DROP list (`rosterRows`) | **clean** — same filter, so an unvalued player is never recommended as a cut |
| draft rookie-pool sort (`readBlendedValue`) | **clean enough** — 0 sinks the row and reaches no label |
| ranking surfaces | **not reachable** — unpriced rows carry no `canonicalConsensusRank`, so they are off the ranked board entirely |

## The finding that mattered most

`isUnpricedBoardRow` was added for exactly this (audit finding W08-F006) and its own
docstring says unpriced rows "are labelled instead, at the chip".

**It had no production consumer at all.** Only the test directory imported it. The predicate
shipped; the label never did. An audit finding can be closed by a function that is never
called, and nothing in the suite notices — the tests exercised the predicate directly.

## The repair

Missingness preserved **separately from** the arithmetic, which is the shape the governance
rule permits — not a blanket replacement of every `|| 0`:

- `effectiveValue` still returns 0, and now says in its docstring that this is the bounded
  neutral element and where the missingness lives instead;
- `displayValue` returns **`null`** for an unpriced row, and `formatBoardValue` is the one
  formatter that turns it into an em dash, so "not priced" cannot render as "0" on one
  surface and "—" on another;
- `unpricedAssetsOnSide` drives an explicit **"Incomplete — N unpriced"** line on the side
  total, naming the assets in its tooltip;
- the override placeholder and the multi-team asset meta say "—" / "not priced";
- the player popup reads "not priced" rather than "0", and its value chain says "no value"
  rather than "how we got 0";
- a manual `customValue` makes an asset priced again — the board has no number, the user
  supplied one, and reporting that as missing would be its own lie.

Pinned by `frontend/__tests__/unpriced-is-not-zero.test.js`, including the sort case the
ruling asked for by name: an unpriced asset sorts last because it is **unknown**, not
because it lost a comparison to 12. A `0` produces the same order there by accident and the
wrong one the moment a low-valued priced row exists.

Frontend suite: 125 files, 2044 tests, green.

## Boundary, stated

Prettier reports pre-existing style warnings on all three touched files on `main` as well;
the repo runs no prettier gate, and reformatting them would bury this diff in unrelated
churn. Not touched.

---

# B-SERIES COMPLETION AUDIT — PASS

Run against `main` @ `460c9f9` and production after the `62f5a39` deploy. Full matrix:
[`B_SERIES_COMPLETION_AUDIT.md`](B_SERIES_COMPLETION_AUDIT.md). Executable checks:
`evidence/B-completion/audit.py` (20 checks, all PASS), output in `results.md`.

Worth recording about the audit itself: **its first run reported five failures, and all five
were the checks being wrong.** A substring search matched the comment documenting a removal;
a stamp was looked for in `data_contract.py` when it correctly lives in `server.py`; a
memorised family count was stale; a unit assertion would have failed the very discipline
B9b established (`percentilePoints` is right for a gap between percentiles); and a
`valueMode` match landed on a comment saying the component deliberately takes none. The
corrections are in the script. An audit that reports false failures is worse than no audit.

**Verdict: PASS — C-Series may begin.**

One PARTIAL, stated rather than waved through: the board-history recorder is
non-deterministic (`rankChange` differs on 740 rows between two builds of identical code).
Pre-existing, reproduces on `main` before B11, touches no decision surface, does not block C.

Three naming defects are left open **deliberately** — `confidenceBucket: "none"` on 24
priced rows, `identityConfidence`, `marketConfidence`. Each is a rename with its own consumer
blast radius and none changes a number; folding them into a confidence-methodology change
would have been the silent scope drift the ruling forbids.
