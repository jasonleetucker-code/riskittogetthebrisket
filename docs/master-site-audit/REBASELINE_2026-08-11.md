# Re-baseline at HEAD — 2026-08-11

`NEXT_STEPS.md` was written at the close of PR #722 and is still the live directive for
*what to repair next*. This file records what changed about the **measurements** underneath
it, because the registry was generated at a commit that no longer sits on `main` and several
of its verdicts no longer describe HEAD.

Measured on `claude/dynasty-audit-consolidation-e75vdy` at `4ac9b22` (== `origin/main`).

## Test baseline — the wave-D verification debt is PAID

`NEXT_STEPS.md` opened with "run the full suite; this is the one thing I would not skip",
because repair wave D shipped without one. Both suites are now measured on a quiescent tree:

| suite | result | previous figure |
|---|---|---|
| `pytest tests/ -q` | **7,001 passed / 0 failed** / 25 skipped / 633 subtests, 583s | 6,553 passed (post wave C) |
| `vitest run` (frontend) | **119 files / 2,003 tests passed / 0 failed** | 1,866–1,870 |

Toolchain: python 3.11.15 in `.venv` via `scripts/setup.sh` (CI-parity preflight green),
node 22.22.2, vitest 4.1.10. No failures anywhere, so wave D's ten unvalidated commits are
retroactively clean. The later figures in this file (120 files / 2,004) include this
session's own additions.

## The clone was shallow, and it mattered

A fresh checkout arrives with 50 commits (boundary `764ebbb`). Every audit SHA — including
`8b88623f`, which generated `findings.json` — was unresolvable, which reads exactly like the
squash having destroyed them. After `git fetch --unshallow` (4,878 commits):

- all 85 claiming commits resolve again;
- `origin/claude/fantasy-football-master-audit-umvex5` survives on the remote and contains
  every one of them, `8b88623f` included;
- `8b88623f` is confirmed **not** an ancestor of `main` — the squash is real, and
  `origin/main..HEAD` genuinely carries no trailers.

So the claim signal was never recoverable from `main`, and the fix is
`claims-frozen-2026-08-05.json` + the amended `verify_closure.py` (see that commit). Anyone
re-running audit tooling on a fresh clone must unshallow first or every git-derived signal
lies.

## W31-F001 — REFUTED AS PRESCRIBED, re-scoped

`NEXT_STEPS.md` flagged this as "one open defect worth fixing early" with the repair given as
`git rm --cached` on `data/sleeper_last_good.json` and `data/scrape_state/`. **Do not do
that.** The tracking is deliberate and load-bearing:

- `.github/workflows/scheduled-refresh.yml:489` force-adds `data/scrape_state/` every 2h in a
  step that runs even when the scrape fails, precisely so per-fetcher freshness stamps survive
  partial failures;
- `:562` syncs `data/sleeper_last_good.json` in the data-refresh commit loop;
- `:605` dispatches the deploy on `automated data refresh|freshness stamps`, so untracking
  these files freezes production's `source_health` on the previous deploy's timestamps — the
  "44h-stale-everywhere" outage the hardening was written for.

An untrack would also be undone within 2h by the next `git add -f`.

The *observation* stands — a deployed checkout goes dirty within minutes of boot and
`git pull --ff-only` fails there. The root cause is that the **prod backend** writes to paths
CI owns. The real repair is to reroute the running server's runtime writes to an untracked
location (or teach the deploy to reset those paths), which is M-sized and touches `server.py`
— currently claimed by the live `claude/bridge-timeout-root-cause` session, so it is deferred
rather than attempted.

## Registry corrections found this session

Verified at HEAD by reading the code, not by trusting a status field:

| finding | registry says | HEAD says |
|---|---|---|
| W08-F004 | claimed closed by `00a3ce2c` | **was still live** — all four `/^2026\b/` sites present. `00a3ce2c` is on the audit branch whose code half never reached `main` (PR #745 lifted only the docs). Now genuinely fixed and re-claimed. |
| W11-F006 | open | **live and confirmed**, now fixed. |
| W10-F003 | "Missing: there is no perfect-draft optimizer" | `src/draft/` + `frontend/lib/perfect-draft.js` contain a full budget-knapsack optimizer with displacement and cut ladders; `CLAUDE.md` documents it at length. Needs re-verification against the spec's requirements, not a from-scratch build. |
| W26-F004 | open-unsafe-to-rerun | mechanism (nflverse actuals fetched then discarded) is fixed at HEAD by the snapshot guard in `src/api/bdvm_api.py:178-182`. |
| W31-F001 | open, fix = `git rm --cached` | prescribed fix refuted (above). |

The general lesson, and the reason the spec insists on it: **the registry is stale in both
directions.** `00a3ce2c`'s claims are the sharpest case — a commit whose code half was
abandoned still marks findings closed. Verify per finding at HEAD before scheduling any repair.

## New defect found this session — /trade was broken for 3+ teams

Not in `findings.json`, because it postdates the audit's reconnaissance: the owner hit it in
production during this engagement. Full write-up in
`evidence/W08/TRADE_MULTI_TEAM_CRASH.md`; the short version:

`frontend/app/trade/page.jsx` called `defaultDestination` at nine sites without importing it.
`49e005b2a` (2026-07-26, "Redesign R4", #552) deleted the import together with the one call site
it had just removed, and missed the other nine. Because an un-imported free variable compiles to
a global lookup rather than a link error, `/trade` loaded fine and two-team trades worked
perfectly — the `ReferenceError` fired only on the 3+-team paths, so the whole multi-team
feature had been dead for two and a half weeks under green CI.

Two things this says about the test estate, beyond the one-line fix:

- **No E2E spec exercises a multi-team trade.** `journey-trade.spec.js` and the mobile specs are
  two-team only. That gap is precisely what let a fully broken feature ship.
- **A production build proves nothing about free variables.** `npm run build` was green before
  and after; a bundler cannot tell a forgotten import from an intended global.

Reproduced RED and verified GREEN in Chromium at the mobile viewport against the real production
build (`evidence/W08/trade_multiteam_browser_check.mjs`). WebKit — the owner's actual browser —
is not installable in this container, so that exact path stays labelled unverified rather than
claimed.

## Not done here

- `verify_closure.py --rerun` over the 338 safe reproductions. It needs the full stack
  (156 commands hit `127.0.0.1:8000`; 35 hardcode a scratchpad path from a dead session) and
  the tool does **not** diff output against `expected`, so every rerun needs manual
  adjudication. That is the next session's first job.
- The 77 unsafe-to-rerun reproductions still need the hand-checked worklist
  `REPAIR_PROTOCOL.md` calls for.
- The C01–C43 and U01–U06 trackers under `docs/audits/` remain unmapped to W-ids.
