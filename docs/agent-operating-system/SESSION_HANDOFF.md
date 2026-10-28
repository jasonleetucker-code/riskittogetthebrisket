# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-10-28 ~17:15Z.** Agent-OS-Receipt `47a8b19f`. Concurrency limit: four workers. The coordinator's own coding
counts toward the four.

## Mode
- Owner directive 2026-10-28 ("next development cycle"): parallel build mode. The verbatim text is in
  `docs/owner/NEXT_CYCLE_IDP_CALIBRATION_DIRECTIVE_2026-10-28.md`; intake rows NC-A … NC-E; the execution-plan section
  is at the top of `docs/EXECUTION_PLAN.md`.
- The standing merge authorization applies: exact-head green, independent review (delta re-review after any later
  commit), stacked dependencies first.
- Owner-reserved: everything listed in that execution-plan section, including any ROS-calibration promotion, values,
  weights, voting, freshness rules, the DLF IDP hold, flags, advisor gate values, #2006, the `dynasty_new` taxi cap,
  and filing #1985 with GitHub Support.

## Merged this cycle (squash SHAs on main)
| PR | content | merge |
|---|---|---|
| #2009 | directive intake, claims | f64183d4b |
| #2011 | Trade Advisor launch-gate recommendations; War Room value-concept labels (copy only) | f45a27863 |
| #2010 | ROS offense/IDP scale calibration: shadow package, preregistration, results (research only) | 0726dbd09 |
| #2013 | E2E #2000: `/waiver-advisor` a11y route; keyboard typing helper | 0b6316472 |
| #2014 | `sourceAuthorityReasons` per-row diagnostic; IDP Show IDP-only vendor clock (no value change) | cd76ddac5 |
| #2012 | 235 deterministic live-data tests promoted into the hard gate | 099e0dead |

Closed: #1921, superseded by #1995 (per-file comment on the PR).

## Open
- **#2015** WebKit iPhone (mobile-390) suite in the E2E Safety Net. Review fixes:
  - artifact paths;
  - the navigation-abort filter, which rebuilds the text Playwright splits at its first colon, with exact host
    matching;
  - the quick-view scan, which now waits for finite animations to settle.

  The last CI run had one WebKit contrast retry. Re-run pending at `58852aae7`.
- **#2016** Explicit-encoding guard. The 838 offenders are fixed by codemod, with no baseline. Main was merged twice
  and the guard is green on the merged tree. CI is pending at `93c916515`.
- **#2017** Coordinator docs: the #2009 nits and this handoff.
- **#2006** HOLD (owner); unchanged.

## Production
- Serving `f45a27863` (#2011) at 17:05Z.
- Pending deploys carry #2010 (code is inert research), #2013 (tests only) and #2014 (the new contract field).
- Verify with `/api/status .build.commit`.
- **P-1:** the live nginx sends none of the security headers declared in `deploy/nginx/chaseupside.com.conf`
  (HSTS, nosniff, X-Frame-Options, frame-ancestors CSP, Referrer-Policy, Permissions-Policy). The config is applied
  only by hand (`deploy/apply_hardening.sh`), so this needs the box operator.

## Key findings (detail in the linked docs)
- **NC-A, `docs/league-intelligence/ROS_SCALE_CALIBRATION_RESULTS_2026-10-28.md`:**
  - `rosValue` is not a cross-position currency. On one shared scale, IDP is over-valued about 13%
    (D 0.870 [0.797, 0.952]), IDP spread is about 2.5× too wide, and QB is under-valued about 46%.
  - IDP starters carry 48.5% of the live lineup score but earned 44.5% of awarded points.
  - CR, the per-family rank→points curve, is the best challenger (ΔMAE +0.266 [+0.126, +0.404]). Every challenger
    fails G3, single-week offense×IDP pair ordering, by a CI bound just below 0. So under the preregistered rule there
    is no recommendation.
  - The week-8 confirmation fit is frozen (`fits_week8_frozen.json`).
- **NC-B, `docs/sources/IDP_SOURCE_AUTHORITY_2026-10-28.md`:**
  - Retention is 0.378 = (IDPTC 0.303 + IDP Show 0 + FP IDP 0.21 + DraftSharks IDP 1.0) / 4.
  - Every clock is truthful; the vendors themselves are stale. No ingestion bug exists.
- **NC-D, `docs/trade/advisor_evidence/LAUNCH_GATE_RECOMMENDATIONS_2026-10-28.md`:**
  - Response floor: 300 ms, or 250 if the box measures quiet.
  - Keep the admission (2 slots) and all six rate buckets.
  - Write no source-permission record until each source is asked.
  - Waiver Advisor is not ready: list bids use the offseason option value (FAAB-lane fix, unassigned).

## Owner decisions pending (new this cycle)
- **NC-A:** accept the ROS diagnosis; whether to build CR as a separate `rosPointsPerWeek` field behind a
  default-OFF flag after week-8 confirmation; whether G3 is gated on a single week or on the ROS horizon.
- **NC-B D-A:** let IDP Show's IDP-only board (republished 10-08) vote. Gate it on outlier-integrity V2 like DLF?
  Measured effect: median retention 0.378 → 0.565, and 402 rows move.
- **NC-B D-B:** IDPTC cadence, learned 127.9 h vs configured 240 h. This is a freshness-rule change: factor
  0.303 → 0.771, retention → about 0.495.
- **NC-D:**
  - `responseFloorMs` (300 recommended);
  - OD-3 source permissions per group;
  - admission and limiter priors (keep);
  - `/league` odds-page uncalibrated wording;
  - authorizing the FAAB-lane season-phase fix before any Waiver Advisor activation.
- **Carried over:**
  - #2006: the recommended outcome is to restore the rule;
  - #1985: GitHub Support filing, owner account;
  - P-1 nginx headers, box operator.
- Everything in the previous handoff's list that is not resolved above remains open.

## Hazards
- **The encoding guard is in the hard gate once #2016 lands.** New Python must pass `encoding="utf-8"` to text-mode
  `open` / `read_text` / `write_text`.
- **Disk:** the session allowance is tight. Remove merged worktrees: `wt-b`, `wt-c` and `wt-c-nodata` (which has
  uncommitted scratch files and needs `--force`).
- **Playwright on WebKit:** `splitErrorMessage` splits error text at the first `:`. Match on name + message, never
  the message alone.
- **Unchanged from before:**
  - GitHub API quota is shared;
  - never `git stash`;
  - commit explicit paths;
  - only the newest pending `production-deploy` run survives.
