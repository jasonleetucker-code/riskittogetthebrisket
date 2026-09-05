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

## 4. Known follow-up (not fixed here)

This board is expected to keep shrinking as the 2026 class fully graduates,
possibly to zero, before repopulating with the 2027 class. **"The vendor no
longer publishes a rookie board this phase" is a different question from "the
fetch broke,"** and a fixed row-count floor cannot tell them apart — the new
floor is not pretending to. When the board empties, the fetcher will exit 1
("no rows extracted") and the source will go stale again with the same
symptom and a different cause.

The honest shape for that is a source whose *expected coverage is
phase-dependent* — either a declared seasonal window for `flockFantasySfRookies`
in `config/source_staleness.json`, or a relative drop guard measured against the
source's own recent history rather than an absolute count. Both are new
methodology and neither is invented here.

---

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
