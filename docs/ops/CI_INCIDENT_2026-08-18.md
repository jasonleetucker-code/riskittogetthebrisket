# CI / production-automation incident — 2026-08-18

**Reported:** seven workflows failing.
**Finding:** not seven problems. **Two** were already resolved before the report was
written, **two** are honest detectors reporting real conditions, **one** was a mechanical
bug in the workflow, **one** is a genuine production incident, and **one** is a known
open audit item.

Green is not the goal. Each row below is placed in exactly one legitimate state.

---

## 1. Status

| # | Workflow | Before | After | Root cause | Resolution |
|---|---|---|---|---|---|
| 3 | Scheduled Data Refresh | 🔴 | **🟢** | DraftSharks dynasty fetch had not succeeded for **303.5 h**; the staleness watchdog was the sole failing condition on six consecutive runs | Repaired by #894; production run `32123775865` green at 09:57Z, stamps 303.5 h → 0.03 h, tracking issue #765 auto-closed |
| 4 | PR Validation | 🔴 | **🟢** | Not a repo defect — my own PR #905 tripped the decision-path coercion gate, then a guard's expected wording | Both fixed in #905 (`f922cd77d`, `9f429a475`); the gate did its job |
| 1 | Verify Sharp Production Population | 🔴 | **🟢 (repaired here)** | `git pull --rebase` on a tree the smoke step had just made dirty → exit 128 → the enforce gate never ran | Pull with `--autostash`, **before** the `git add`; guarded + mutation-proven |
| 5 | Audit Rank-Form Curve Drift | 🔴 | **🔴 — CORRECT (Case C)** | The audit ran correctly and detected **real drift** introduced by an approved pipeline change | Constants are obsolete. Rewriting them is an **owner action** under ADR-008 |
| 6 | Retention health (read-only) | 🔴 | **🔴 — CORRECT (Case B)** | Probe reached production and measured `ok=7 stale=1`: identity-resolution reports last written **2026-04-20** (119 days) | A halted collector on the box. Real finding; must not be softened |
| 7 | Bootstrap Sharp Records | 🔴 | **🔴 — EXTERNALLY BLOCKED** | `dynasty-ffpc-sharp.service` is in a **crash-timeout loop** on production | Root cause needs host access; see §5 |
| 2 | E2E Safety Net | 🔴 | 🔴 — known audit item | `journey-settings-overrides` (1 hard) + `journey-rankings` (1 flaky) | Diagnosed in the audit register, F-3a / F-3b |

**No `continue-on-error` was added, no assertion removed, no threshold raised, no trigger
deleted, no test skipped.**

---

## 2. The report's premise, tested

The brief asked whether one shared cause explains all seven. **It does not**, and the
evidence separates them cleanly:

* **Two Sharp workflows fire together** (`workflow_run` ← *Deploy Production*), which is why
  they appear as a pair — but their causes are unrelated: one is a git mechanic, the other a
  runaway service.
* **The cascade hypothesis is disproved.** Scheduled Data Refresh went green at 09:57Z and
  Deploy Production succeeded at 09:57Z; Verify Sharp still failed at 10:14Z, and Retention
  health's stale stream dates from **April**. Downstream failures did not come from upstream
  data.
* **No missing secret explains the set.** The only credential gap is `/api/sharp/*` (§6),
  and it produces a *warning*, not a failure.

---

## 3. Verify Sharp Production Population — repaired

```
error: cannot pull with rebase: You have unstaged changes.
error: Please commit or stash them.
##[error]Process completed with exit code 128.
```

The smoke step rewrites the tracked artifact `data/ops/sharp-production-smoke.json`, so the
tree is dirty when the commit-back step runs. `git pull --rebase` refuses. The **"Enforce
healthy population" gate sits after that step and therefore never executed** — verbatim the
defect the step's own `AUDIT O-4` comment describes one line earlier, recurring.

**The obvious fix is wrong, and this was verified against real git before choosing:**
`--autostash` pops with `git stash apply` semantics and does **not** restore the index. So
"stage first, then pull" returns the artifact **unstaged**, `git diff --cached --quiet`
exits 0, and the step takes its *"No change in smoke result — nothing to commit"* branch —
**green, with the result silently never recorded.** Measured:

| order | staged after pull | `--cached --quiet` | outcome |
|---|---|---|---|
| add, then pull | *(empty)* | 0 | "nothing to commit" — **fake green** |
| pull, then add | `f.txt` | 1 | commits — correct |

Guarded by `tests/deploy/test_sharp_smoke_commit_order.py`, mutation-proven against
stage-before-pull, dropping `--autostash`, and removing the gate's unverifiable branch.

The guard's first version **passed all three mutants** because the step's own comments quote
those commands while explaining them, so the assertions compared prose to prose. It now
strips comment lines. A guard that cannot fail is decoration.

---

## 4. Rank-Form Curve Drift — the audit is right, and it found something real

Reproduced locally: `offense excess +49.5`, `idp excess +100.5` against a threshold of 25.

**It is not data.** Today's code reports the same excess on every archived board from
2026-07-28 to 2026-08-18 (±0.5), including boards that ran green.

**It is not the script or the constants.** Both were introduced together in `52e1dc03b`
(2026-07-30) and neither has changed since.

**It is a pipeline change**, and bisecting names it. The check rebuilds the board through
`build_api_data_contract`, so it measures today's pipeline whatever payload it is given.
Holding the **payload fixed** (the 2026-08-11 board) and varying only the code:

| tree | offense excess | idp excess |
|---|---|---|
| `2449af9ac^` — before B2 | **+7.0 ok** | **+4.0 ok** |
| `2449af9ac` — **B2 (#787), "route the Hill master by the rank's coordinate pool"** | **+44.8 DRIFT** | **+30.0 DRIFT** |
| `8403b093e` — B4 (#805), bound the percentile tail | +35.8 | +81.8 |

B2 changed which Hill master a rank routes to — **step 3 of the live pipeline**, precisely
what this workflow's own header says reshapes the rank→value relation. So this is **Case C**:
the system legitimately changed and the committed rank-form constants are now obsolete.

**Deliberately not fixed here.** ADR-008 prohibits a model autonomously rewriting production
constants, and names the exact trap: an automated fix that patches `player_valuation.py`
*and* re-baselines `test_rank_form_constants_tripwire.py` is a change that cannot fail its own
guard. The workflow already computes the fix and hands it over. **Owner action, §6.**

---

## 5. Bootstrap Sharp Records — a real production incident

Production journal, via the workflow:

```
Starting dynasty-ffpc-sharp.service ...
  (30 minutes later)
dynasty-ffpc-sharp.service: start operation timed out. Terminating.
  Main process exited, code=killed, status=15/TERM
  Failed with result 'timeout'.
  Consumed 29min 53.407s CPU time, 144.9M memory peak
```

Repeating at 06:47, 07:26, 11:14, 11:44, 12:14, 12:44 (host local time).

**Mechanism, exactly.** `Deploy Production` succeeds → `sharp-records-bootstrap.yml` fires on
`workflow_run` → SSHes to prod → `bootstrap-sharp-records.sh::run_ffpc_now` →
`run_oneshot` → `systemctl start dynasty-ffpc-sharp.service`. The unit is `Type=oneshot`, so
`systemctl start` **blocks** for the full `TimeoutStartSec=1800`, is killed, returns non-zero,
and the workflow exits 1. Deploy runs on every 2-hourly data refresh, so this repeats ~12×/day.

**It is compute-bound, not network-bound** — ~29 m 50 s of *CPU* in a 30 m window is ≈100% of a
core, which a crawler sleeping 1.5 s between calls and waiting on 20 s timeouts would not do.

**A second, independent inconsistency** is visible in committed config alone
(`config/sharp/ffpc_sources.json`): `requestBudgetPerRun: 100` × (`timeoutSeconds: 20` ×
(1 + `retryLimit: 2`) + `sleepSecondsBetweenCalls: 1.5`) = **6,150 s worst case against a
1,800 s timeout**. The unit is provisioned to be killed whenever the crawl is not fast.

**A hypothesis I formed and then refuted, recorded so nobody re-runs it.** The startup calls
`platform_ledger.hydrate_sleeper_asset_catalog(players)` over Sleeper's whole directory, which
looked like the CPU sink. Measured on a synthetic 11,400-player directory of the same shape:
**0.3 s cold, 0.3 s repeat (≈38.8k rows/s)**. It is not the cause.

**Disposition: EXTERNALLY BLOCKED.** The remaining question — what in
`scripts/crawl_ffpc_sharp.py --public-only` spins for 30 minutes — needs the production host
and the live FFPC endpoint. Guessing a fix for a runaway production service is exactly what
this incident should not produce. **The workflow is correctly reporting a real failure and
must not be retired, silenced, or made non-fatal.**

---

## 6. Owner actions

1. **`dynasty-ffpc-sharp.service` is burning ~100% of a core for 30 minutes, ~12×/day.**
   Highest priority — this is live resource consumption, not just a red tick. On the box:
   `journalctl -u dynasty-ffpc-sharp -n 500` for the run's own log lines (the workflow only
   surfaces systemd's), then run
   `python scripts/crawl_ffpc_sharp.py --public-only --budget 5 --verbose` by hand to see
   which stage does not return. Consider `systemctl stop dynasty-ffpc-sharp.timer` until
   diagnosed. **Also worth deciding:** whether `bootstrap-sharp-records.sh` should force an
   immediate FFPC pass on *every* deploy when the collector has its own daily timer — that is
   what turns one daily failure into twelve. Not changed here, because removing a trigger to
   quieten alerts is the wrong reflex while the root cause is open.
2. **Rank-form constants are obsolete after B2 (#787).** Apply the values the workflow
   prints — `HILL_MIDPOINT 67.4`, `HILL_SLOPE 0.875`, `IDP_HILL_MIDPOINT 63.4`,
   `IDP_HILL_SLOPE 0.834` — to `src/canonical/player_valuation.py`,
   `frontend/lib/value-history.js`, and the two pinned tests. ADR-008 makes this a human act.
3. **Identity-resolution reports stopped on 2026-04-20** (C1-RET-07, 119 days). Retention
   health stays red until the collector on the box runs again. Note the workflow's own
   warning: `/api/scaffold/identity` serves the newest file, so a halted collector **presents
   a 119-day-old report as current**.
4. **`/api/sharp/*` has no credential for the smoke.** It answers `401` from
   `https://chaseupside.com/api/sharp/cohort` — the site is up, the check simply has no token,
   so population health is **not measured**. Provisioning a token (the workflow names the
   `_SELF_AUTHED_API_EXACT` bearer pattern used by `/api/signal-alerts/run`) turns a warning
   into a real gate. Until then Verify Sharp is green-with-warning, which is honest.

---

## 7. Production data health

* **Refresh pipeline: operating.** Run `32123775865` green 09:57Z; all 24 source CSVs written;
  22 of 22 fetch stamps fresh; contract source-health errors **0**.
* **Deployment: healthy.** `Deploy Production` succeeded 09:57Z on `43d9f9997`.
* **Board: current.** DraftSharks recovered from 12.6 days stale to 0.03 h.
* **Known stale, reported not hidden:** `idpTradeCalc` pick rows byte-identical for 34 days
  (budget 14 d) — the fetch is fresh; the vendor has published nothing. Identity-resolution
  reports, 119 days (§6.3).
* **Sharp records: NOT populated, and not measurable from CI** — the FFPC collector has not
  completed a pass, and the cohort endpoint needs a credential.

---

## 8. Checks actually run for this incident

| check | result |
|---|---|
| `tests/api` (full) | **1884 passed**, 17 skipped |
| `tests/audit tests/scripts tests/docs tests/canonical` | 571 passed → 1 failure found and fixed |
| `tests/deploy/test_sharp_smoke_commit_order.py` (new) | 5 passed, **3 mutants caught** |
| `tests/audit/test_remediation_tooling.py` | 34 passed (2 new cases) |
| `ruff format --check .` / `ruff check .` | clean, 1149 files |
| `scripts/check_decision_coercions.py` | clean |
| `scripts/check_rank_form_drift.py` | reproduced; bisected to `2449af9ac` |
| `git pull --rebase --autostash` index semantics | verified against real git, both orderings |
| `hydrate_sleeper_asset_catalog` at 11.4k rows | 0.3 s — hypothesis refuted |
