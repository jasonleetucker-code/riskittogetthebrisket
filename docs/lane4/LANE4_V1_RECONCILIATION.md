# Lane 4 — V1-55…V1-65 reconciliation against the live repo

**Measured:** 2026-08-18, at the post-sync head (main merged through `52541f5`).
**Method:** live repo inspection, not a contract snapshot.

> ## ⚠️ HEADER CORRECTED 2026-08-24 — read this before quoting the table below
>
> **The original "Contract not found" disclaimer is now false, and the table
> under it predates the real contract.**
>
> This file opened by saying `VERSION_1_COMPLETION_CONTRACT.md` "does not exist
> on `main`", so its row numbering was *inferred from the order of a lane
> instruction* rather than read from an owner record. The contract now exists on
> `main` and is canonical. Re-checked at `131abf9f9`, the inferred numbering
> happens to line up with the real identifiers — but that is a coincidence this
> file cannot claim credit for, and it does **not** make the *verdicts* current.
>
> **Three verdicts below contradict the live contract and must not be quoted:**
>
> | this file says | live contract at `131abf9f9` says |
> |---|---|
> | V1-57 "**DONE this pass**" | `IMPLEMENTED_UNVERIFIED`, required level **L3** |
> | V1-60 "**DONE this pass**" | `IMPLEMENTED_UNVERIFIED`, required level **L2** |
> | V1-62 "**verified honest**" | `IN PROGRESS`, required level **L4** |
>
> None of those three is wrong about the *code* — the implementations are real
> and were measured. They are wrong about the **evidence level**: this file was
> written before the contract set a required level per row, so "done" here means
> "implemented and locally verified", which is L1. It is not L2/L3/L4, and the
> gap in every case is production evidence nobody in this lane can obtain
> without credentials.
>
> `VERSION_1_COMPLETION_CONTRACT.md` is the canonical status record. Where this
> file and the contract disagree, **the contract wins.** See
> §"Lane-4 V1 status at 2026-08-24" at the foot of this document for the
> current measured state of all ten open rows.

| # | Item | State (as measured 2026-08-18 — see header correction) | Owner / blocker |
|---|---|---|---|
| V1-55 | FAAB engine verification | **verified** — 526 tests in `tests/trade/` incl. `test_faab_engine`, `test_faab_calibration` (pins the derived all-in line against two managers' stated judgments), `test_faab_config_parity` (no in-code default may drift from `faab.json`) | — |
| V1-56 | FAAB context production verification | **advanced — the context number is correct and the canonical doc said it wasn't** — see below. Verifying the *running* production instance still needs prod access | Claude 5 (prod half) |
| V1-57 | Scheduled FAAB bid-history collection | **DONE this pass** — see below | — |
| V1-58 | Sharp cohort production population | **UNVERIFIED, not empty** — blocked on prod auth | Claude 5 (prod) |
| V1-59 | Failing Sharp/bootstrap path | **diagnosed, blocked** — same root cause as V1-58 | Claude 5 (prod) |
| V1-60 | FFPC roster lane: real or explicitly unavailable | **DONE this pass** — see below | — |
| V1-61 | Sharp Roster Percentage | **implemented**; 7/14/30-day + season-to-date windows now published (14-day added earlier this session). Board is top-50 by default, per-player denominators, population-overlap guard | UI surfacing → Claude 6 |
| V1-62 | Sharp Tracker | **verified honest** — per-platform `status` of `disabled` / `degraded` / `no_data` / `ok`, top level `ok` vs `cohort_building`, and FFPC `enabled` derived from the same config the cohort reads (no disagreement between the two surfaces) | — |
| V1-63 | Manager-level Sharp concentration | **verified + 2 defects fixed this pass** — see below | — |
| V1-64 | Sharp add/drop event ledger | **verified honest** — `crawl_coverage` publishes `sharpEligibleLeagues` beside `leaguesCrawled`, so a zero is explained by its own denominator, and `oldestCrawlMs` is `null` rather than 0 | — |
| V1-65 | Insider Trading / cross-league ownership consolidation | **assessed — already consolidated; vocabulary boundary now pinned** — see below | — |

## V1-57 — reconciled before implementing, as instructed

The requirement and the deployed reality only partly overlap, and conflating
them would have produced a duplicate scheduler:

| | script | scope | state |
|---|---|---|---|
| `dynasty-crowd-faab` | `scripts/fetch_crowd_faab.py` | what **other** leagues pay | **already deployed**, 3-hourly, `install_simple_timer "crowd-faab"` |
| *(none)* | `scripts/fetch_faab_history.py` | what **this** league pays | **no timer, no workflow, no cron** anywhere in the repo |

The engine fits its market priors — median / p75 / p90, zero-bid share, and
per-manager aggression — from the *second*. Without the file it falls back to
configured priors and says so in `contention.notes`, so the absence has always
been reported and never fixed. The script's own docstring says "run this on a
cadence"; there was none.

Added `dynasty-faab-history.{service,timer}.template` + one
`install_simple_timer` line. Daily 07:40 UTC. Daily rather than hourly because
waivers process weekly while the walk is one request per league-week across the
whole chain — and, unlike the crowd feed's five-day rolling window, **nothing
expires unrecorded**: Sleeper retains transactions indefinitely, so a missed
run costs freshness and no data. That asymmetry is the whole reason crowd-faab
needs 3-hourly and this one does not.

`tests/deploy/test_all_timers_are_wired.py` failed on the templates before the
installer line existed — the guardrail working, and the exact failure that hid
crowd-faab, sharp-activity and board-snapshot until 2026-08-05.

## V1-60 — the silent zero was real, and there were three of them

Every counter on `CollectResult` is `0` in two different situations: the lane
ran and found nothing, and the lane never ran. A bare `CollectResult()`
serialises identically to a real empty pass — `"0 rosters, 0 errors"` — which
reads downstream as a healthy platform with an empty wire.

Three paths produced one: `skip_sleeper`, `skip_ffpc`, and
`collect_ffpc_rosters` when no cohort member has an `ffpc:` key.

`CollectResult` now carries `status` + `unavailableReason`:

- `skipped_by_caller` for the two `--skip` flags;
- `no_cohort_managers_on_platform` when nobody in the cohort plays there — a
  fact about the **cohort**, not about FFPC's health, and the reason says so
  rather than leaving a consumer to infer it from a zero.

An empty pass that really ran still reports `ok`. The distinction only works if
both directions hold.

## V1-63 — verified, and two defects found underneath

The concentration design is sound and was confirmed rather than changed:
raw counts (`buys`, `uniqueManagers`) are kept as evidence descriptions while
the **capped** weights (`weightedBuys`…) are what `strength` is computed from,
bounded at 0.34 per manager and per league, with `concentrationCapped` flagging
when the cap actually bit.

Two real defects sat under it, both the lane's own semantic:

**1. An explicit zero quality voted at full weight.**
`consensus.py` read `quality = float(person["quality"] or 1.0)`. A manager
scored **0.0** — the lowest possible quality — was promoted to **1.0**, the
highest, so a worthless vote carried full weight into both the consensus and
the concentration cap. The default already happens upstream
(`quality_by_manager.get(key, 1.0)`), so this second one could only ever
overwrite a real measurement. Now only a non-numeric value defaults; the
upstream default is preserved and tested.

**2. `networkConcentration` published `0.0` for an undefined ratio.**
It is a *share of weighted volume*; with no weighted volume there is no share
to hold, and `0.0` is the one value that reads as the exact opposite — "no
single network dominates". Now `None`, matching what `roster_percentage`
already publishes for `cohortCoveragePct` in the same situation. The field had
**no consumers**, so the correction is free.

## V1-65 — the consolidation already happened; what was missing was a guarantee

Assessed rather than rebuilt. The two products are **already** consolidated
onto shared infrastructure, and correctly:

| layer | module | role |
|---|---|---|
| substrate | `src/intel/ledger.py` | normalized movement rows + indexed window queries, under **both** products; neither product's logic lives there |
| metrics | `src/intel/signals.py` | window-safe primitives shared by both; recency is a **ratio** between windows, never a sum, so it is arithmetically incapable of double-counting |
| products | `src/intel/service.py` (league-scoped) / `src/sharp/market.py` (global cohort) | the two questions |

The predecessor's `trendScore = 3·net48h + 2·net7d + 1·net30d` summed **nested**
windows, so one movement an hour old counted six times. It is retired, and the
replacement cannot reproduce the fault by construction.

### The boundary that mattered, and was unguarded

The evidence bars are deliberately different:

- **Sharp** — dynasty only, league age ≥ 2 seasons (`SHARP_ELIGIBLE_TYPES`). It
  is a claim about SKILL.
- **Insider** — dynasty *and keeper* (`ELIGIBLE_TYPES`), no age floor, because a
  keeper league is real evidence about a real person you can trade with.

So a manager can be legitimate Insider Trading evidence while carrying no sharp
qualification at all. Labelling that population "sharp" would assert a claim
the source never made — the lane brief's §9 rule.

**It held only by absence.** The three insider modules emit no sharp vocabulary
anywhere; the only occurrences are two docstring lines explaining the boundary.
Nothing stopped a future change from adding a "sharp" badge to the insider
board.

Added `tests/intel/test_insider_never_claims_sharp.py`: an AST scan asserting no
**non-docstring** string literal in `service.py` / `leads.py` / `lead_service.py`
contains "sharp", with a positive control so the scan cannot pass by silently
matching nothing, and a negative control so docstrings stay allowed. The gate
asymmetry itself was already pinned by
`tests/sharp/test_sharp_gates.py::test_keeper_is_not_sharp_eligible_even_with_history`,
so this adds the half that was missing rather than duplicating it.

## V1-56 — the FAAB context strip is correct; CLAUDE.md said it was not

"FAAB context" is the `/waivers` league-FAAB strip, served from
`/api/public/league/faabAnalytics` (`src/api/faab_analytics.py`) through the
lazy public-league envelope.

Its headline field, `leagueMedianWinningBid`, is **correct**:
`faab_analytics.py` keeps $0 bids and computes both mean and median over the
full set, pinned by
`tests/api/test_faab_analytics.py::test_zero_bid_free_agents_are_counted`.

**CLAUDE.md still said the opposite**, in the canonical FAAB section:

> `src/api/faab_analytics.py` gates its median on `bid > 0` … `faab_analytics.py`
> is unchanged and still powers the history panel, so anything reading
> `leagueMedianWinningBid` is reading a nonzero-only median.

That claim is stale and was actively misleading: it told a reader to distrust
a number that is now right, and to prefer `faab_history.py` for market-facing
use on grounds that no longer hold. Corrected under CLAUDE.md's own precedence
rule — *live code or executable evidence can prove a status claim in any
document, including this one, stale.*

Why it mattered enough to be worth writing down twice: 41-77% of adds cost
nothing per season, so a nonzero-only median reports ~2% of budget where the
truth is 0% — about a **200x** overstatement of the single most important
number in the market model. On a representative bid set the two readings are
`0.0` and `8.5`.

**This edit touches `CLAUDE.md`, a shared governance file — flagged for Claude
5 rather than treated as a lane-local change.**

## V1-58 / V1-59 — blocked on production access, and honestly so

`data/ops/sharp-production-smoke.json` has **never** recorded a verified
population. The last nine runs:

```
08-18 14:50  deploy_failed                  cohort=0  ffpc=0
08-18 14:29  unverifiable_unauthenticated   cohort=0  ffpc=0
08-18 14:28  unverifiable_unauthenticated   cohort=0  ffpc=0
   … 12:40–13:57 all unverifiable_unauthenticated
```

Locally `cohort_members()` returns 0 members with a fully populated coverage
block naming each contributing pool as 0 (automated / curated / provisional).

**This is the correct behaviour, not the defect.** The repo already treats
`unverifiable_unauthenticated` as *insufficient evidence, not bad news*
(`tests/deploy/test_sharp_smoke_commit_order.py:94`), and the coverage block
explains a zero rather than asserting one. So the semantics V1-59 asks for are
already in place; what is missing is **production authentication**, without
which no code change in this lane can prove population.

Handing to Claude 5 as an ops dependency. Writing a bootstrap that fabricates
or assumes a cohort would defeat the very reporting that is working.

## Carried forward, not built (per instruction)

- **#804 correlated sources** — analysis preserved in
  `LANE4_804_CORRELATED_SOURCE_STATUS.md`. Its own evidence says a defensible
  new correlation grouping needs retained longitudinal rank digests that do not
  exist (24 sources live, 3 archived, 0 of 176 bundles carry more). The
  rank-digest retention proposal (+31 KB/bundle vs +155 KB for full CSVs) is a
  **perishable-evidence/ops decision for Claude 5**, not lane work. No weights
  or families invented.
- **Central Buy/Sell reconciler** — inventory preserved in
  `LANE4_SIGNAL_EMITTER_INVENTORY.md`. Not built; C6-SIG-01/02 sit post-V1
  unless Claude 5 reclassifies.
- **UI** — `crowdMarket`, `status`/`unavailableReason` and the 14-day sharp
  window are published as truthful API state. Rendering is Claude 6's.

---

# Lane-4 V1 status at 2026-08-24

**Measured at `main` = `131abf9f9a1c014c77ac4bb80b346d5f9dc2ccac`.** Canonical
ledger read live: 88 / 136 VERIFIED. Lane ownership is the contract's `lane`
column, not its `level` column — V1-45 (Trade calculator) is lane **L2** and is
not Lane 4's row, notwithstanding that this lane reported its defect.

## The ten open rows, and the one thing they have in common

| row | required level | contract status | blocker |
|---|---|---|---|
| V1-56 FAAB league context panel | L4 | `IMPLEMENTED_UNVERIFIED` | authenticated session |
| V1-57 FAAB bid-history scheduled | L3 | `IMPLEMENTED_UNVERIFIED` | VPS shell |
| V1-58 Sharp cohort populated | L3 | `IMPLEMENTED_UNVERIFIED` | authenticated session |
| V1-59 Sharp bootstrap stops failing | L3 | `IN PROGRESS` | VPS shell |
| V1-60 FFPC roster lane truthful | L2 | `IMPLEMENTED_UNVERIFIED` | authenticated session |
| V1-61 Sharp Roster Percentage | L4 | `IMPLEMENTED_UNVERIFIED` | authenticated session + VPS shell |
| V1-62 Sharp Tracker | L4 | `IN PROGRESS` | authenticated session (see §3) |
| V1-65 Insider population distinction | L2 | `IMPLEMENTED_UNVERIFIED` | VPS shell |
| V1-89 DraftSharks staleness | L3 | `BLOCKED` | owner decision `OD-04` (see §2) |
| V1-129 crowd-FAAB comparability | L2 | `IMPLEMENTED_UNVERIFIED` | VPS shell |

**Every open Lane-4 row is externally blocked.** The two prerequisites are
singular and unchanged: **one authenticated session cookie for
`chaseupside.com`, and VPS shell access.** No amount of further local work
moves any of these rows, and the recorded production smoke
(`data/ops/sharp-production-smoke.json`, `lastObservedAt`
`2026-08-24T09:44:17Z`) still reads `status: unverifiable_unauthenticated`,
`measured: false`, `401 from https://chaseupside.com/api/sharp/cohort`.

That smoke is itself the point worth escalating: **the dedicated CI smoke
workflow's own credentialed attempt gets 401.** This is not a sandbox
limitation. It is a credential-provisioning gap upstream of every verification
lane, and it is the single highest-leverage thing an owner can fix for this
lane's numerator.

## §1 — Feature-flag posture: no Lane-4 surface can be silently switched off

V1 requires, for every relevant surface, proof that *a flag-off surface cannot
masquerade as implemented*. For Lane 4 that requirement is discharged
**structurally**, and this is a stronger result than a calibration:

**Zero `is_enabled` call sites exist anywhere under `src/sharp/`, or in
`faab_engine.py` / `faab_recommender.py` / `faab_comparability.py` /
`faab_history.py` / `faab_contention.py` / `faab_analytics.py`.** There is no
flag to switch off. Every Sharp and FAAB surface is unconditionally reachable in
the intended production configuration.

Measured with `src/api/flag_reachability.py` (the caller-graph resolver built
for V1-88, PR #991), which resolves flag → gate call site → enclosing function →
transitive callers → route handler.

One flag *transitively* reaches `/api/sharp/roster-percentage`:
`te_basis_conversion`. That is correct and must not be "fixed" — it is a
canonical-value flag (Lane 5's TE-premium basis conversion), it defaults `True`
with `gate_status == LIVE`, and it is **not referenced anywhere in
`src/sharp/`**. The board reaches it by consuming canonical board values.
Forbidding that would be forbidding the Sharp board from reading the board.

**Guarded, not merely recorded.** `tests/api/test_feature_flag_endpoint_reachability.py`
gains three tests so this stays true rather than being a snapshot:

- an `is_enabled` gate appearing in Lane-4 code on an **unregistered** flag fails;
- a Lane-4 gate on a flag that **defaults `False`** fails — that is the
  masquerade case exactly: the board vanishes while its V1 row still claims the
  capability ships;
- a **non-vacuity control**, because both assertions currently pass over an
  empty set and "no gates found" is indistinguishable from "scanner broken"
  otherwise. It asserts the scanner resolves the known real gate in
  `src/api/gameplan.py`.

Both guards are mutation-proven against the real tree: injecting a gate into
`src/sharp/market.py` on `unified_id_mapper` (default `False`) turns the
defaults-off guard RED naming the exact module, function and flag; changing that
to an unregistered name turns the registration guard RED instead.
`src/sharp/market.py` was restored byte-identical afterwards.

## §2 — V1-89: the `OD-04` premise no longer holds

`OD-04` asks the owner to re-mint, accept degradation, or retire DraftSharks. It
was raised on a specific measured condition:

> ~219 h stale against a 24 h threshold, the production session file absent, the
> watchdog red every two hours, and nine-day-old values still voting in every
> blend.

**Measured at `main` `131abf9f9`, from tracked `data/scrape_state/*_last_success`:**

| key | age |
|---|---|
| `draftSharks` | **0.9 h** |
| `draftSharksIdp` | **0.9 h** |
| `draftSharksRos` | **0.9 h** |

All 28 registered sources are ≤ 3.0 h old. `main` carries
`exports/latest/dynasty_data_2026-08-24.json` with `scrapeTimestamp`
`2026-08-24T17:26:50Z`. The acute condition `OD-04` was raised for has cleared,
which is consistent with its own recommended option (a) — *re-mint the session
and repair the dynasty scrape* — having already happened operationally.

**Bounded honestly, and the bound is load-bearing.** `config/source_staleness.json`
states in its own header comment that the stamp tracks *"fetch succeeded"*, not
*"vendor published new content"*. So this measurement proves the **watchdog
condition** has cleared. It does **not** prove content freshness, and content
staleness is a genuinely different question that stays part of V1-89's L3
production check. A fresh fetch stamp over unchanged vendor content is exactly
the case `CLAUDE.md`'s content-staleness section documents.

**Recommended disposition — for the owner, not decided here:** re-put `OD-04` as
*"confirm option (a) already happened, then close"* rather than as a live
re-mint / accept / retire choice. Retiring a provider family that is currently
fetching cleanly would change the blend on every row for no measured cause.

## §3 — V1-62's stated blocker points at a projection, not a live defect

V1-62's contract note reads *"live but W15-F017 no memoization"*.

`W15-F017` is real in shape: `cohort_members()` is genuinely unmemoized (only
`load_ffpc_config` carries an `lru_cache` in `src/sharp/cohort.py`) and
`src/sharp/market.py` calls it from three sites (`:394`, `:517`, `:593`).

But `docs/master-site-audit/PERFORMANCE_AUDIT.md` classifies it **P3** and says
of it directly:

> W15-F017's O(N log N) rebuild is **invisible at the current 0 rows**. The
> scale at which it becomes the slowest surface on the site is **a projection,
> not a measurement.**

…with its recorded blocker being *"No populated platform ledger"* — the same
populated-production-ledger blocker as V1-58, V1-60 and V1-61.

**Consequence for planning: V1-62 is not available implementation work.** Adding
a TTL memo now would be an optimization whose benefit cannot be measured (0
rows) and whose risk is concrete: a memoized cohort can serve a **stale**
membership, and `stale != current` is one of this programme's hard truthfulness
rules. It would also not advance the row, whose required level is **L4** —
actual user-facing consumption — which needs the authenticated surface either
way.

Recorded so that a future session reading "no memoization" does not mistake a
deferred P3 projection for an open defect it should go and fix.
