# V1-105 / C0-PERF-01 — pre-feature performance baseline audit

**Row:** `docs/VERSION_1_COMPLETION_CONTRACT.md` V1-105, canonical id `C0-PERF-01`, level L2,
status `NOT STARTED`. Manifest acceptance (`C_SERIES_SCOPE_MANIFEST.md:190`): *"p95 baselines for
`/rankings`, `/trade`, `/league`, sharp pages, mobile"*, evidence type *"recorded measurements"*.
Its own stated reason for existing: *"a baseline captured after the work cannot show what the work
cost."*

`C0-PERF-01` is a hard `deps` entry for `C8-PSI-02` (PSI route migration), `C8-PERF-01` (mobile
payload), `C8-PERF-03` (rankings windowing — **just merged**, PR #1003, head `5f4dfd166`, merge
`dda306cf`), `C8-PERF-04` (Sharp Tracker) and `C8-PERF-05` (public league payload).

This audit answers one question honestly: **does a valid pre-feature-work baseline exist for any
of that, and if not, what does?** No new baseline is fabricated. Nothing is backdated.

## Timeline that matters

| date | event |
|---|---|
| 2026-08-04 / 08-05 | `docs/master-site-audit/PERFORMANCE_AUDIT.md` §2 page-timing measurements taken (single run, `page-probe.json` / `W26/page-ux-probe.json`) |
| 2026-08-12 | `docs/GLOBAL_PERFORMANCE_STANDARD.md` owner-approved — this is when the "time to useful state" metric this row is judged against was even defined |
| 2026-08-17 | `PERFORMANCE_AUDIT.md` + its evidence files committed to `main` (commit `24759f8a2`) — a writeup of the 08-04/05 measurements, not a new capture |
| 2026-08-18 | `frontend/scripts/measure-route-baselines.mjs` written (commit `35a7ba351`, message: *"A probe for the baselines C0-PERF-01 says do not exist"*) — the correct p95/cold-warm/useful-state instrument, built explicitly to document the ABSENCE, not to backfill a before-state |
| 2026-08-18 | Rankings row windowing lands on `main` (commit `a9136e13e`, "6.8 → 35.6 FPS") |
| 2026-08-20 | `#984` merges — Premium Sports Intelligence migration of `/rankings` + new `/players/[playerId]` |
| 2026-08-20 | `#1003` merges — V1-106 committed windowing regression evidence (no runtime change) |

**The instrument that can actually produce an acceptance-grade baseline (p95, cold vs warm, a
declared useful-state marker per route — `measure-route-baselines.mjs`) did not exist until the
same day windowing had already landed on `main`.** By construction, nothing it produces today can
be a "before windowing" or "before PSI" measurement for `/rankings` — the feature work is already
in the tree it would measure.

## Classification of every candidate source

| source | date / attribution | covers | classification |
|---|---|---|---|
| `PERFORMANCE_AUDIT.md` §2 (`page-probe.json`, `W26/page-ux-probe.json`) | 2026-08-04/05, predates windowing (08-18) and PSI (08-20) by 2+ weeks | `/rankings`, `/trade`, `/`, `/league` (as the shell-fetch-exempt control), 12 other pages, desktop+mobile | **VALID_PRE_FEATURE_BASELINE in TIME, but SUB-ACCEPTANCE in METHOD** — explicitly single-run (*"Everything is single-run… treat the <10 ms band as fast, not as a benchmark"*), generic nav/FCP/load rather than a declared per-route useful-state marker, and `settleMs` is documented as broken. A "p95" cannot be computed from n=1. Directional evidence only — see below. |
| `docs/master-site-audit/evidence/route-probe.json` | committed 2026-08-17 (merge `24759f8a2`), underlying capture undated precisely but co-located with the above audit | API-level status/ms/bytes, not page-level useful-state | **UNATTRIBUTABLE** to a specific pre/post-feature code state at page level; it measures API routes, not the metric this row asks for |
| `docs/master-site-audit/evidence/C0-PERF-01/` (pre-existing dir) | — | — | **MISSING** — the directory exists (created 2026-08-18) but was empty and untracked; nothing was ever committed there before this PR |
| Any run of `measure-route-baselines.mjs` (including the one this PR adds) | 2026-08-20, after both windowing and PSI merged | `/rankings`, `/trade`, `/league`, `/`, cold+warm, p95, useful-state marker | **POST_FEATURE_MEASUREMENT for `/rankings`.** Methodologically correct (this IS what C0-PERF-01 asks for), but it can only describe the board *after* windowing and PSI — it cannot retroactively become a "before" |
| Prior PR measurements (#760's own evidence table) | 2026-08-05 (PR body) / 2026-08-18 (merged commit `a9136e13e`) | `/rankings` only, and **it measures the WITH/WITHOUT-windowing states within the same feature branch** | **POST_FEATURE_MEASUREMENT** relative to `main` at merge time — its own "before" arm (22 FPS, "Show all" without windowing) is real and dated, but it is an A/B pair captured *inside* the feature PR, not a baseline recorded on `main` *before* the PR started. Useful corroborating color, not the canonical row's evidence. |
| Production metrics with attributable SHA | none found | — | **MISSING** — no APM/RUM pipeline exists in this repo; `docs/ops/` has no production latency dashboard to query |

## The honest bottom line, per route

**`/rankings` — structurally unrecoverable as literally written.** Two rounds of feature work
(windowing PR #760/merge `a9136e13e` 2026-08-18; PSI migration #984, 2026-08-20) have already
shipped to `main`. No acceptance-grade (p95, useful-state-marker) measurement exists from before
either one — the correct instrument wasn't built until the day windowing landed, and by its own
account was built specifically because the baseline was already gone. The 2026-08-04/05 audit
predates both and covers the right route, but is single-run and uses different metrics, so it
cannot itself satisfy a "p95 baseline" claim. **There is no way to go back and measure the
pre-windowing, pre-PSI `/rankings` page today; that page no longer exists to measure.**

**`/trade`, `/league`, sharp pages, mobile in general — NOT yet touched by any C8 perf/PSI feature
work.** `C8-PERF-04` (Sharp Tracker) and `C8-PERF-05` (public league payload) are both still
"PERF-INCOMPLETE" / un-fixed; `C8-PSI-02` names Rankings as only the *first* PSI route. For these,
a baseline captured **today, before their own feature work begins**, is not a retroactive fabrication
— it is exactly the kind of prospective, pre-work baseline this row exists to require, captured at
the earliest point it is still possible to be honest about.

## What this PR adds (not a synthesized "before")

`2026-08-20-current-state-post-c8.json` — a real run of the existing, correct instrument
(`frontend/scripts/measure-route-baselines.mjs --runs 3 --viewport both --routes
/rankings,/trade,/league,/`), against `main` at `8be59e267` (includes #1003/#984), local backend +
production Next build, `E2E_TEST_MODE=1`. Two mobile routes (`/league`, `/`) hit test-session-mint
rate limiting on the first combined pass and were re-measured separately 20s later — recorded
honestly in the file's own `note` field rather than silently merged as if from one run.

Headline (p95, ms):

| route | viewport | cold useful | warm useful |
|---|---|---:|---:|
| `/rankings` | desktop | 2968 | 2654 |
| `/rankings` | mobile | 1098 | 1158 |
| `/trade` | desktop | 999 | 1914 |
| `/trade` | mobile | 1035 | 477 |
| `/league` | desktop | 318 | 202 |
| `/league` | mobile | 497 | 923 |
| `/` | desktop | 497 | 386 |
| `/` | mobile | 3652 | 394 |

This is labelled and stored as **CURRENT-STATE evidence, dated 2026-08-20, post-#1003/#984** — it
is explicitly NOT offered as C0-PERF-01's required "before" evidence for `/rankings` (that would be
exactly the substitution this row's own rationale warns against). For `/trade`, `/league` and `/`,
it stands as a legitimate prospective pre-work baseline for whatever their own C8 perf items turn
out to require, should the owner accept that framing (see below).

**Not measured** (consistent with the earlier V1-106 planning pass's finding): `/waivers`,
`/market/sharp-tracker`, `/market/sharp-roster-percentage`. Their readiness markers depend on data
(`data/faab/`, the sharp cohort ledger) that only production's scheduled timers populate — a local
run against these three routes times out on every navigation rather than producing a number, so no
measurement is reported for them here (**BLOCKED_EXTERNAL**, not a synthesized pass).

## The actual decision this needs

The row as literally written cannot be closed for `/rankings` — that evidence does not exist and
cannot be produced after the fact. Two paths forward, and choosing between them is a scope call,
not an engineering one:

1. **Accept that `/rankings`'s true pre-feature baseline is permanently unavailable**, record that
   explicitly against the row (rather than leaving it silently "NOT STARTED" forever), and let
   `C0-PERF-01` close on the *remaining* routes (`/trade`, `/league`, sharp pages, mobile) with a
   baseline captured now, before their own feature work starts.
2. **Keep `/rankings` open against this row indefinitely** until some other evidence (e.g. the
   08-04/05 audit, explicitly caveated as sub-acceptance-grade) is owner-approved as sufficient
   despite not meeting the stated "p95" bar.

Neither is an engineering decision I'm authorized to make unilaterally — it changes what the
canonical row's acceptance actually requires. Reporting it, not resolving it.

---

**OWNER_DECISION_REQUIRED.** No fabricated baseline. `/trade`, `/league`, `/` (and, pending
opportunity, sharp pages) now have real 2026-08-20 measurements available to serve as a genuine
prospective C0-PERF-01 baseline for their own not-yet-started feature work, if the owner accepts
that scope. `/rankings`'s pre-windowing/pre-PSI state is gone and cannot be recovered by any
harness run today.
