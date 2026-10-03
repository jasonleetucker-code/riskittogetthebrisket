# Incident 2026-09-05 — `scheduled-refresh` red for 10 days; and a false P0

**Reported as:** a P0/P1 data-freshness outage — a session health check said
"no successful scrape in 38h" and that `origin/main` was equally stale.

**Actual outcome:** two separate findings, neither of them a data outage.

1. **There was no production freshness incident.** The 38h figure was a
   monitoring artifact. §2.
2. **There was a real, standing defect**, 10 days old and invisible behind a
   permanently-red workflow: `flockFantasySfRookies` had not refreshed since
   2026-08-26 because a row-count guard was calibrated against an assumption
   that stops holding in-season. §3.

Both are repaired here. Nothing about freshness thresholds, staleness policy,
or the `stale != current` / `missing != zero` semantics was weakened, and no
timestamp was hand-minted.

---

## 1. Timeline and evidence

| when | fact | source |
|---|---|---|
| 2026-08-26 16:07:55Z | last successful `flockFantasySfRookies` fetch (83 rows) | `data/scrape_state/flockFantasySfRookies_last_success` |
| 2026-08-31 16:26Z | Flock last updated the PROSPECTS_SF board | vendor `lastUpdated` field |
| 2026-09-05 10:58:20Z | `main`'s contract `scrapeTimestamp`, 1078 players | `origin/main:exports/latest/dynasty_data_2026-09-05.json` |
| 2026-09-05 11:25:06Z | production `last_success_at`; `last_failure_at: null`, `current_step: complete` | `GET https://chaseupside.com/api/status` |
| 2026-09-05 ~12:15Z | session health check reports "no successful scrape in 38h" | `.claude/health-check.sh` |

Runs 1341–1345 of `scheduled-refresh.yml` all ended `conclusion: failure`, and
in every one of them **only step 14 ("Staleness watchdog") failed.** Steps 1–13
and 15 succeeded: run scraper, persist freshness stamps, validate scrape sanity,
prune archives, commit updated data, trigger deploy, assert DLF freshness,
contract coverage watchdog. Acquisition → commit → deploy was green throughout.

In the taxonomy the directive asked for, this is a **health-state bookkeeping
failure** — not acquisition, scheduling, Actions, on-box, commit/push, or
deployment.

---

## 2. The false alarm — `.claude/health-check.sh`

`main_contract_age_h()` attributes a stale checked-out contract by reading what
`origin/main` holds. Its `_git` helper deliberately never fetches (a
SessionStart hook must not wait on the network), so `origin/main` is whatever
**this checkout last saw**.

This session's ref was ~38h old and unfetched, and the working tree sat on a
branch cut at that time. So the probe read a 38h-old contract off a 38h-old ref
and printed:

```
WARNING: no successful scrape in 38h. Check scheduled-refresh workflow.
(origin/main's contract is 38h old too — not a branch artifact.)
```

The second line is the damaging one. It converts "I cannot tell" into a
confident pipeline-outage claim. After `git fetch`, the real ages were 1.6h
(main) and 1.2h (production).

**Repair.** A ref older than the freshness budget is evidence in *neither*
direction, so `main_contract_age_h(limit)` now consults `local_main_ref_age_h()`
first and answers `None` ("cannot tell") when the ref itself is stale or
unreadable. The caller prints an explicit *"Cause NOT attributed … run
`git fetch origin main`"* line rather than silence, so an unexplained warning
never reads like a confirmed outage again.

The file's own stated rule is *"an unproven excuse must never silence a real
alarm."* This is its converse: an unproven ref must not raise a false one.

Pinned by `tests/deploy/test_health_check_stale_ref_guard.py` (behavioural — it
execs the script's own heredoc with a stubbed `_git`; the pre-fix function
returns a confident `38.0` on the exact incident shape, the post-fix one returns
`None`, and a *fresh* ref can still both explain a branch artifact and confirm a
genuine outage).

---

## 3. The real defect — the Flock rookie row-count floor

Step 14's output on run `33961925495`:

```
fail: 1 stale source(s), 0 unmeasurable, 21 fresh.  Stale: flockFantasySfRookies
```

Cause, from the same log:

```
[fetch_flock_fantasy_rookies] row count below floor: 48 < 60
Non-fatal — continuing with stale CSV
```

The fetcher was working correctly. It refused to overwrite good data with a
payload it had been told to distrust, so the CSV kept its 2026-08-26 mtime, so
the watchdog flagged the source, so the workflow went red — **every run, for
about ten days.**

### The payload is real, not truncated

Measured live on 2026-09-05 against `format=PROSPECTS_SF`:

- 48 entries, `averageRank` running **1..48 with no gaps**;
- coherent position mix (WR 20 / RB 12 / TE 9 / QB 7), no IDP, no picks, no
  nulls, every row `isRookie: true` / `isDraftPick: false`;
- vendor's own `lastUpdated` is 2026-08-31 — the board *changed*, it did not
  stop being served;
- the sibling `format=superflex` board is healthy at 500 rows;
- **all 48** prospects also appear on that main board;
- of the 35 rows that left since 2026-08-26, **21 are now on the main board**
  and the other 14 are deep-tail prospects the vendor dropped
  (Chase Roberts, Colbie Young, Roman Hemby, …);
- the main board carries 73 rows flagged `isRookie`.

That is the 2026 rookie class **graduating** from the prospects board onto the
main dynasty board as the season starts. It is normal vendor behaviour.

### Why the guard mis-fired

`_FF_ROOKIE_ROW_COUNT_FLOOR` was 60, and its comment justified that as *"the
PROSPECTS_SF endpoint currently carries ~98 entries (one full rookie class)"*.
That is true only in the pre-draft window. The floor was encoding **"how big
should a rookie class be"**, which is not a question a truncation guard can
answer, and which changes by phase.

### Repair

The floor is re-derived as what it actually is — a **truncation guard** — and
set to **24**: two rounds of a 12-team superflex rookie draft, i.e. the region
this source's within-class rank has to cover for the rookie-ladder translation
to mean anything, with 2x headroom under today's observed 48. A genuinely
broken or truncated response still trips exit 2 (verified: the existing
2-row test still exits 2). The evidence above is recorded in the constant's own
comment so the next reader does not re-derive it.

Verified by running the fetcher for real: exit 0, 48 rows written, CSV mtime
advanced, content genuinely new. `run_fetcher` in `scheduled-refresh.yml` stamps
`*_last_success` on fetcher exit 0, so the watchdog clears on the next scheduled
run **from a real fetch** — no stamp was written by hand here, and the
sandbox-fetched CSV was deliberately **not** committed so that production's
first fresh copy comes from the pipeline.

### What was deliberately NOT done

- **`flockFantasy` was not added to `soft` in `config/source_staleness.json`.**
  That file's own governance says soft is *"A DELAY, NOT AN EXEMPTION"*; it is
  for operator-chore sources like `idpShow`'s hand-minted cookie, and it
  escalates to hard-fail anyway. Quieting an alarm without fixing acquisition is
  the failure mode this repo exists to avoid.
- **No threshold was lowered and no timestamp was minted.**

---

## 4. Owner methodology decision (2026-10-03) — declared seasonal window

> **Supersedes, in place, the open follow-up this section used to carry.** It read: the board will keep
> shrinking, possibly to zero, before the next class; "the vendor no longer publishes a rookie board this
> phase" is a different question from "the fetch broke"; the honest shape is either a declared seasonal
> window or a relative drop guard; "both are new methodology and neither is invented here." The owner chose.
> Tracking issue #1552.

**What happened.** The prediction came true on 2026-09-30: `PROSPECTS_SF` now answers HTTP 200 with
`year: 2026` and an empty `data` list. The fetcher exited 1 ("no rows extracted"), wrote no success stamp,
the 48-row CSV of 2026-09-30 kept voting in the canonical board while aging, and `scheduled-refresh.yml`
went red on every run again. (The scrape-sanity half was fixed separately by #1616.)

**Decision (owner, 2026-10-03): the DECLARED SEASONAL-WINDOW approach**, implemented as a real
phase-dependent source state — not a generic weakening of freshness monitoring.

1. For the graduating 2026 class, an empty `PROSPECTS_SF` response from **October 1, 2026** is an expected
   `seasonally_inactive` state, not a stale-source failure.
2. The fetch keeps running on every normal schedule while inactive. No success timestamp, freshness stamp,
   row or payload is fabricated.
3. A seasonally inactive rookie source contributes **no current vote** — not a zero value, and not
   indefinitely decayed stale authority. The historical CSV/archive stays intact for provenance, replay
   and research.
4. The first valid non-empty `PROSPECTS_SF` response for the next class reactivates the source
   immediately, whatever the date; the normal 24-hour freshness policy and every shape/schema guard then
   apply again.
5. The within-season truncation / row-count guard is kept. The window answers *"is this board expected to
   exist right now?"*; the floor keeps answering *"is this board malformed or truncated?"*.
6. Not added to `soft` — soft is a delayed outage alarm, the wrong semantics for a source that
   legitimately disappears between classes.
7. Configuration-backed and reusable for other genuinely phase-dependent sources; fail-closed for every
   source with no declared policy.

**Implementation** (`claude/flock-rookie-seasonal-window`):

| concern | owner / mechanism |
|---|---|
| policy | `config/sources/seasonal_policy_v1.json` — expected-empty signature (`data == []`, `year` = class year, `format == "PROSPECTS_SF"`), `inactiveFromMonthDay: "10-01"`, `reactivation: first_valid_nonempty_response`. Window per class `Y` is `[Y-10-01, (Y+1)-10-01)` UTC — one declared cycle, no tuned number |
| verdict + state | `src/sources/seasonal_policy.py` (the one owner). State file `data/scrape_state/<key>_seasonal.json` with an explicit `seasonally_inactive` state, `lastInactiveVerifiedAt` (when the empty signature was last re-observed — proof attempts continue, never a success time) and a bounded transition history |
| vocabulary | `src/sources/acquisition_state.py` gains `SEASONALLY_INACTIVE` (acquired, `rowCount` 0, **not usable**) and `SEASONALLY_INACTIVE_EXIT_CODE = 4` (3 is taken by Yahoo Boone's partial scrape). `state_from_exit_code` maps exit 4 to `SEASONALLY_INACTIVE` only for a `source_key` with a declared policy in the owner module; for any other source exit 4 is `UNAVAILABLE` |
| fetcher | exit 4 + state on the declared signature inside the window; exit 1 for every other empty response (wrong/missing year, wrong format, before the cutoff, all rows filtered out); exit 2 for shape / row-floor failures as before; exit 0 writes the CSV, *then* records reactivation (a crash between the two leaves the source excluded) |
| workflow | `run_fetcher` stamps only on exit 0, unchanged; exit 4 is logged as a notice instead of a fetch failure |
| watchdog / alerts | `watchdog_freshness.split_seasonally_inactive` and the alert engine accept the inactive state only while it is re-verified within the source's **normal** threshold (24h); a lapsed re-verification is classified exactly as before (hard-stale on its old stamp) |
| coverage watchdog | `watchdog_contract_coverage` skips a source only when the BOARD BEING CHECKED was built with it inactive — the contract's own `sourceSeasonalState` stamp (`seasonal_policy.contract_inactive_sources`), never the checkout's current state. The live deploy gate (`verify_live_source_coverage.py`, run by `verify-deploy.sh`) reads the served generation's `served_seasonal_inactive` from `/api/status` for the same reason. `scheduled-refresh.yml` builds the board before the Flock fetcher runs, so on the reactivation run the current state is already active while the board (correctly) carries no Flock vote, and on the inactivation run the reverse; comparing a board with today's state turned reactivation into a deterministic red watchdog and a possible deploy auto-rollback (review finding M1). A missing or malformed stamp excuses nothing |
| vote | `data_contract._seasonally_inactive_sources` resolves the state as of the board's own scrape time from the build's state directory; `_compute_unified_rankings` drops the source at the one active-source gate, exactly as a disabled source is dropped, and the per-row source audit no longer lists it as expected (so graduated-class rookies are not reported `partial_coverage`). A payload with no `scrapeTimestamp` gets no seasonal exclusions, mirroring freshness weighting. Stamped on the contract as `sourceSeasonalState` and as `staleness: "seasonally_inactive"` in `dataFreshness.sourceTimestamps` |

**Confidence (B11) decision.** A seasonally inactive source is **not an eligible family**. The existing
rule walks `active_sources` and requires a non-empty source pool, so a vendor publishing no board this phase
is not something that *could* have covered a row — the same treatment a disabled source already gets. It is
also not "present evidence" for the single-source haircut (unlike a freshness-quarantined source, whose
board exists but is old). In practice the `flockFantasy` B10 family stays eligible on every offense row
through `flockFantasySf`, so coverage denominators do not change.

**Measured canonical impact** (`scripts/golden_board.py` on `exports/latest/dynasty_data_2026-10-03.json`,
identical inputs, without vs with the inactive state): Flock rookies voted on 46 rows before, 0 after.
**83 values moved** — 43 are rows Flock rookies voted on and 40 are current-year slot picks (tethered to the
rookie pool, CLAUDE.md pipeline step 13); **0 other rows moved value**. |Δ| p50 0.2%, p90 0.8%, max 2.0%
(Oscar Delp 2369 → 2322); 61 up / 22 down. 96 ranks changed (26 Flock-voted rows, 4 picks, the rest
displaced by them); 1 confidence flip (Germie Bernard medium → high); 0 `isSingleSource` flips; 621
`canonicalTierId` renumberings from the gap-based tierer (tier ids are ordinals, so a boundary that moves
near the top renumbers everything below it; no value moved on those rows).

## 5. Impact

`flockFantasySfRookies` is a registered canonical rank-signal source
(`needs_rookie_translation=True`, ladder-translating onto the `ktcSfTep`
backbone), so for ten days the rookie region of the board voted with
2026-08-26 ranks. Real, but bounded: one voter among many, under a count-aware
blend where a missing row is missing coverage rather than a zero.

**The larger damage was the signal loss.** A workflow that is red on every run
cannot report a new failure. Any genuine acquisition outage between 2026-08-26
and today would have been indistinguishable from this one.

No Week 1 launch row is affected: rookie boards drive dynasty valuation, not
current-season matchups. `docs/season-launch/WEEK_1_LAUNCH_CONTRACT.md` is
unchanged by this incident — no acceptance evidence for any existing row moved.
