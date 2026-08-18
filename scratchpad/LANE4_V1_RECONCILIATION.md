# Lane 4 — V1-55…V1-65 reconciliation against the live repo

**Measured:** 2026-08-18, at the post-sync head (main merged through `52541f5`).
**Method:** live repo inspection, not a contract snapshot.

> **Contract not found.** `VERSION_1_COMPLETION_CONTRACT.md` does not exist on
> `main` or on any non-archive branch visible to this session, and no file in
> the tree carries the `V1-55`…`V1-65` identifiers. The nearest owner record is
> `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md`. This reconciliation is
> therefore keyed to the **enumerated list as given in the lane instruction**,
> in the order given; the numeric mapping below is inferred from that order and
> should be confirmed by the integration lane before it is quoted as contract
> identifiers.

| # | Item | State | Owner / blocker |
|---|---|---|---|
| V1-55 | FAAB engine verification | **verified** — 526 tests in `tests/trade/` incl. `test_faab_engine`, `test_faab_calibration` (pins the derived all-in line against two managers' stated judgments), `test_faab_config_parity` (no in-code default may drift from `faab.json`) | — |
| V1-56 | FAAB context production verification | **partly blocked** — endpoint contract is pinned (`tests/api/test_faab_recommend_endpoint.py`, 26 tests) and now publishes `crowdMarket` state + `staleInputs`. Verifying the *production* context needs prod access | Claude 5 (prod) |
| V1-57 | Scheduled FAAB bid-history collection | **DONE this pass** — see below | — |
| V1-58 | Sharp cohort production population | **UNVERIFIED, not empty** — blocked on prod auth | Claude 5 (prod) |
| V1-59 | Failing Sharp/bootstrap path | **diagnosed, blocked** — same root cause as V1-58 | Claude 5 (prod) |
| V1-60 | FFPC roster lane: real or explicitly unavailable | **DONE this pass** — see below | — |
| V1-61 | Sharp Roster Percentage | **implemented**; 7/14/30-day + season-to-date windows now published (14-day added earlier this session). Board is top-50 by default, per-player denominators, population-overlap guard | UI surfacing → Claude 6 |
| V1-62 | Sharp Tracker | **verified honest** — per-platform `status` of `disabled` / `degraded` / `no_data` / `ok`, top level `ok` vs `cohort_building`, and FFPC `enabled` derived from the same config the cohort reads (no disagreement between the two surfaces) | — |
| V1-63 | Manager-level Sharp concentration | **verified + 2 defects fixed this pass** — see below | — |
| V1-64 | Sharp add/drop event ledger | **verified honest** — `crawl_coverage` publishes `sharpEligibleLeagues` beside `leaguesCrawled`, so a zero is explained by its own denominator, and `oldestCrawlMs` is `null` rather than 0 | — |
| V1-65 | Insider Trading / cross-league ownership consolidation | components present across `src/intel/*` and `src/sharp/*`; consolidation not assessed | needs scoping |

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
