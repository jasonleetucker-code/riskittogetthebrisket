# Backend memory policy — evidence, options, staged decision package (2026-10-21)

**Status: decision package. Nothing in this PR changes a service limit, a unit, a workflow or production.**
The only runtime-adjacent artifacts are two patch files under `docs/ops/patches/` that are **not applied**.

Authority: this is an operations record. It authorizes nothing; `docs/EXECUTION_PLAN.md` remains the sole
implementation-authorization record, and every limit change below needs the owner/operator to run it.

Evidence labels used throughout: **[M]** measured on the production host (quoted from a public diagnostics
log or unit file), **[D]** arithmetic on measured values, **[I]** inference, **[E]** estimate,
**[U]** unmeasured.

> **Addendum 2026-10-25 — `dynasty-market-trade-ledger` limits changed (PR #1926).** The ledger rebuild was
> stalling under its own `MemoryHigh=768M` (the throttle failure mode of §4.3, on a batch job): a read-only probe
> of `build_ledger()` on the live stores peaked at **858 MiB RSS** [M] at 36,637 observations, growing ~27 MiB/day
> [D], and the 2026-10-24 and 2026-10-25 runs ended `Result=timeout` after 15 min with 71 s of CPU [M]. The unit
> now has **no `MemoryHigh`, `MemoryMax=2G`, `OOMScoreAdjust=500`** (a host OOM takes this batch job before the
> backend). Every number below that includes the ledger's 1,024 MiB ceiling is updated inline and marked
> *(2026-10-25)*. The one that changes a conclusion: under this package's recommendation (backend 3,584M,
> frontend 1G) the **declared-ceiling sum becomes 8,704 MiB, 763 MiB over host RAM**, not 7,680 under it (§5.1),
> and the all-ceilings co-resident margin becomes **−466 MiB** instead of +558 (§4.1). The owner's pending backend
> decision should read those, not the originals.

---

## 1. Bottom line

1. **Memory throttling is no longer "plausible, not established" for 2026-10-21: it is measured.**
   At the watchdog's pre-restart snapshot the backend cgroup sat at 1.023x `memory.high` with
   `memory.events high` rising 63,734 -> 127,174 across the stall, `max = 0`, `oom_kill = 0`, 99.6% of the cgroup
   anonymous, essentially no file cache left, no swap, and memory stall (`full avg10`) at 25-33%. [M]
   For 2026-10-19 the counters did not exist yet, so it stays **circumstantial** (peak 2.6G against a 2.5G
   high; no OOM). [M]/[I]
2. **What is not established:** that throttling is the *only* reason the service stopped answering. No stack dump
   exists (`py-spy` is not installed), and memory stall was 25-33%, not 100%. [M] A rising `high` counter proves
   allocations were being throttled while the service was silent; it does not rule out a second contributor.
3. **The host has room.** 7,941 MiB RAM, no swap. [M] At the moment of the 2026-10-21 wedge the host reported
   4,550 MiB `MemAvailable`. [M] Raising the backend ceiling is survivable on measured usage (section 4.1).
4. **Recommendation:** run **Option C-without-a-High-boundary** (i.e. C + D together: `MemoryMax=3584M`, **no**
   `MemoryHigh`) as a **runtime-only canary first** (no unit-file change, no restart; its `/run` drop-ins must be
   cleaned up afterwards, section 5.3), plus the frontend ceilings from B. The canary may start only after
   unmasked classification (Stage 0a) and periodic report-only sampling (Stage 0b) exist, because several of its
   success criteria are unobservable without them (section 5.2).
   Do **not** keep a "warning" `MemoryHigh`: it does not warn, it throttles (section 4.3). Keep the 3-strike
   watchdog untouched. Defer `MALLOC_ARENA_MAX=2` to its own A/B, defer isolating Chromium (E), and treat
   verification scheduling (F) as a separate, owner-sensitive change.
5. **Removing `MemoryHigh` is not risk-free** (section 4.4), and raising `MemoryMax` is not a fix for the
   underlying heap growth: it changes *how* a runaway fails (seconds, kill + restart) instead of *whether* one can
   occur. The growth source is still unidentified (section 3.6).
6. **Restarts are mostly caused by commits, not by crashes.** 11 of 11 backend stops in 22.9 h were clean deploy
   restarts; 4 of them (36%) were caused by box-side DLF CSV refresh commits that the deploy path filter does not
   ignore. Every restart launches an unconditional scrape with ~720 MiB of Chromium three seconds after boot.
   A minimal decoupling is in section 6. No refresh job is disabled by anything here.

---

## 2. How to reproduce every number (all offline, read-only)

Three scripts were added by this PR. None calls a host, a journal, systemctl or the network.

| Question | Command | Input |
|---|---|---|
| What stopped the backend, and was it throttling? | `python scripts/backend_restart_report.py LOG --high-bytes 2684354560` | The log of the `Production Restart Diagnostics (read-only)` workflow run (`gh run view <id> --log > LOG`), or the stdout of `deploy/diagnostics/prod_restart_diagnostics.sh` |
| Which commits start a deploy? | `python scripts/deploy_trigger_audit.py --ref origin/main --since 2026-10-19T09:55:00Z --until 2026-10-20T09:55:00Z --runs-json runs.json` | A local clone, plus optionally `gh run list --workflow=deploy.yml --limit 100 --json databaseId,createdAt,updatedAt,conclusion,event,displayTitle,headSha` |
| What caused each RESTART? | the same command plus `--restart-log LOG` | A restart-diagnostics log for the same window. Each clean stop is matched to the successful deploy run that completed 0-30 min after it. Commit time does not work for this: a deploy completes 80-110 min after its commit |
| Do the declared ceilings fit the host, and does a proposed usage? | `python scripts/memory_ceiling_budget.py --set dynasty.MemoryMax=3584M --set dynasty.MemoryHigh=none --usage backend=3430 --usage other=727` | `deploy/systemd/*.service[.template]` |

**Masked input fails closed.** GitHub replaces secret values with `***` when it writes a workflow log, including
inside journal TIMESTAMPS (any hour, minute, second or day containing the value, and fractional seconds). In
the two runs above, 17 of 207 and 13 of 122 journal lines were masked this way; an earlier version of the
classifier skipped them silently and, on the raw log of run 39403489430, merged the 03:52Z and 06:20Z restarts.
Now: a timestamp masked only in its fraction is read at one-second precision; any other masked line the
classifier would act on makes the report `input: incomplete` with **exit code 3** (never a pass); masked lines
about other units are counted but do not block. `deploy_trigger_audit.py --restart-log` applies the same rule.
The clean fix is to classify the script's stdout on the runner **before** it is logged:
`docs/ops/patches/prod-restart-diagnostics-classify.PROPOSED.patch` (not applied; `git apply --check` passes,
and the existing workflow tests pass with it applied) captures the stdout to a runner file, prints it as before,
then prints `backend_restart_report.py --format summary` computed on the unmasked file, and keeps the
collection's exit status. Two more masking effects: the backend unit appears as `***.service` (the classifier
finds it from its unmasked description; `--unit` must be given exactly as it appears in the input), and
masked numeric values parse to "unknown", never 0.

**`--high-bytes`** is the configured `MemoryHigh` in bytes. It only fills in an unreadable `memory.high`
reading. Once `MemoryHigh` is `infinity` (Stage 1 onward) omit it: there is no limit left to compare against,
the snapshots read `high=max`, and the report notes that it ignored the flag.

Fixtures of the public logs (hostname replaced, secret-masking restored) are in `tests/deploy/fixtures/`;
`tests/deploy/test_backend_restart_report.py`, `test_deploy_trigger_audit.py` and `test_memory_ceiling_budget.py`
pin the rules.

Source runs: diagnostics `39241251979` (2026-10-19 window), `39403489430` (2026-10-19 09:55 -> 2026-10-20 09:55),
`39568862441` (2026-10-21 07:15 -> 08:10); scrape telemetry `39404821221`; V1 `39221318435`, `39552411042`,
`39561535837`.

---

## 3. Reconstruction from repository evidence

### 3.1 Limits per unit [M — `deploy/systemd/*.template`, confirmed live by `systemctl show` in the diagnostics]

| Unit | `MemoryHigh` | `MemoryMax` | Notes |
|---|---|---|---|
| `dynasty.service` (backend + in-process scrape + Chromium) | 2560M (2,684,354,560 B live) | 3G (3,221,225,472 B live) | `OOMPolicy=stop`, `MemorySwapMax=infinity`, swap total 0; `ManagedOOMMemoryPressure=auto` (no oomd action observed) |
| `dynasty-frontend.service` | 1536M | 2G | measured peaks 93.9 MiB (journal, 2026-10-21), 105.7 MiB (inventory, 2026-09-26), **137.3 MiB** (journal, 2026-10-19 10:04Z, run 39403489430) |
| `dynasty-ktc-trades` | - | 512M | timer :07/:37 |
| `dynasty-market-trade-ledger` | ~~768M~~ none *(2026-10-25)* | ~~1G~~ 2G *(2026-10-25)* | daily 08:52 UTC; `OOMScoreAdjust=500`; measured peak 858 MiB at 36,637 observations (see addendum) |
| `dynasty-pick-forecast-snapshot` | - | 1536M | weekly Tue/Wed/Thu |
| DLF / IDPShow / FFPC / sharp / signals / game-day / edgelab timers | none | none | unbounded and **[U]** (no memory figure recorded) |

Host: 8,326,946,816 B (7,941 MiB), 4 vCPU, swap 0 [M — `docs/performance/evidence/linux-inventory-2026-09-26.json`,
`free -m` in every diagnostics run].

Declared-ceiling arithmetic [D, `scripts/memory_ceiling_budget.py`]: today the bounded units' `MemoryMax` values
sum to **8,192 MiB, 251 MiB above host RAM** before the kernel, nginx or any unbounded timer. The ceilings are
already oversubscribed; that is a statement about what the limits permit, not about use.
*(2026-10-25: with the ledger at `MemoryMax=2G` the sum is **9,216 MiB, 1,275 MiB above host RAM**.)*

### 3.2 The two stalls

| | 2026-10-19 | 2026-10-21 |
|---|---|---|
| Process started | ~08:11Z (deploy `b08f7230d`; startup scrape sampled 08:11:15) [M] | 07:17:58Z (deploy `9e3c52fdc`; clean stop 07:17:35) [M] |
| First liveness failure | 08:28:13Z, process age ~17 min [D] | 07:51:17Z, process age ~33 min [D] |
| Application log silent | zero lines at 08:40 and 08:41; 2-5 lines/min at 08:24-25 and 08:31-34 [M] | zero lines at 07:50, 07:51, 07:52 [M] |
| Watchdog | 1/3, 2/3, *recovered* 08:29:48; 1/3, *recovered* 08:35:02; 1/3, 2/3, 3/3 -> restart 08:42:13 [M] | 1/3, 2/3, 3/3 -> restart 07:53:17 [M] |
| SIGTERM | ignored; `stop-sigterm` timeout 08:42:43, SIGKILL [M] | ignored; timeout 07:53:48, SIGKILL [M] |
| Back serving | startup complete 08:43:04 [M] | startup complete 07:54:20 [M] |
| User-visible outage | ~15 min window containing ~6 min of failed probes (1.6 + 1 + 3 min) | ~3 min silent before the watchdog acted (07:50 -> 07:53:18), ~4.5 min until serving again (07:54:20), because the SIGTERM wait (30 s) and the boot (~30 s) follow the silence |
| systemd memory peak | 2.6G (CPU 16m43s) [M] | 2.5G (CPU 27m) [M] |
| cgroup counters before restart | **none logged** | see below |
| Kernel OOM / oomd lines | none [M] | none [M] |
| V1 browser suite running | 08:14:33 -> 08:44:23 [M] | 07:24:09 -> 07:42:11, then 07:42:48 -> 08:06:18 [M] |

2026-10-21 snapshots [M] (`scripts/backend_restart_report.py` verdict: `memory_high_throttle_confirmed`):

| Snapshot (UTC) | `memory.current` | `memory.high` | `ev_high` | `ev_max` / `ev_oom_kill` | anon | file | mem stall some/full avg10 | host MemAvailable |
|---|---|---|---|---|---|---|---|---|
| 07:51:17 | 2,738,745,344 | 2,684,354,560 | 63,734 | 0 / 0 | 2,728,144,896 | 0 | 26.6 / 24.4 | 4,637,836 kB |
| 07:52:17 | 2,739,773,440 | same | 90,555 | 0 / 0 | 2,729,291,776 | 8,192 | 28.1 / 25.0 | 4,652,916 kB |
| 07:53:17 | 2,744,922,112 | same | 126,849 | 0 / 0 | 2,734,313,472 | 32,768 | 37.2 / 33.0 | 4,658,360 kB |
| 07:53:17.9 (pre-restart) | 2,744,926,208 | same | 127,174 | 0 / 0 | 2,734,313,472 | 135,168 | 37.2 / 33.0 | 4,659,100 kB |

Reading it [I]: the cgroup is pinned ~58 MiB over `memory.high` (2,618 MiB vs 2,560 MiB) for at least 2 minutes
while *growing only ~6 MiB* (throttling suppresses growth), and `high` events accrue at 450-600 per second, so
something inside the process was allocating continuously and being slowed at every attempt. The cgroup's own file
pages (interpreter, libraries) had been evicted (file ~0) and nothing anonymous is reclaimable with no swap, so
every code-page touch is a refault. CPU stall was only 5-6% (some), so this is not CPU saturation.

Two waves on 2026-10-19 (recovery at 08:29:48 and 08:35:02 before the final failure) are consistent with
throttling episodes that sometimes clear [I]; nothing proves the last one would not have.

### 3.3 Restart population [M] (24 h, 2026-10-19 09:55Z -> 2026-10-20 09:55Z)

* **11 backend stops, all clean** (uvicorn shutdown banner, no SIGTERM timeout), 22.9 h from first to last.
  Zero watchdog restarts, zero OOM lines.
* Peak memory of those 11 processes (systemd, one decimal, GiB): 1.6, 2.2, **2.5**, 2.2, 1.4, **2.5**, 2.2, 2.1,
  2.1, 2.0, 2.1 -> median 2.1, max 2.5. Two of eleven stopped with a peak *at* the 2.5 GiB throttle line.
  **Those peaks are censored by `memory.high`**: a process held at the line reports the line, not its demand. [I]
* Attribution of the 11 RESTARTS, each matched to the successful deploy run that completed 3.6-15.9 min after
  the stop (`deploy_trigger_audit.py --restart-log`; pinned by `test_real_restarts_are_7_runtime_0_docs_only_4_dlf`):
  * **7 runtime changes** (the first, at 10:04Z, came from `a9f391880`, committed before the window opened),
  * 0 docs/tests-only,
  * **4 box-side DLF refresh commits** (`chore(dlf): automated refresh`, touching `CSVs/site_raw/*.csv`).

  The COMMITS in the same window read 6 runtime / 1 docs-only / 4 DLF, and that is a different quantity: the
  docs-only commit (`f631607ff`) restarted the backend after the window closed. Selecting by commit time is valid
  for counting push RUNS (11 predicted, 11 created) but not for attributing restarts.
* Over 60 h (2026-10-19 00:00Z -> 2026-10-21 12:00Z), counted by run creation time, **not** a restart count:
  29 push deploys predicted, **29 created**, plus 11 `workflow_dispatch` deploys.

  | | success | cancelled (superseded) | still running when listed | failed |
  |---|---|---|---|---|
  | push | 21 | 6 | 1 | 1 |
  | dispatch | 6 | 1 | 0 | 4 |

  "Cancelled" here means superseded: deploys share the `production-deploy` concurrency group, which keeps one
  pending run, so a newer queued deploy (which ships the same and later commits) displaces an older one. Real
  failures are **5 of 40**, not 13. Successful deploys: **27** = 10.8 per day. Data-driven successes: 5
  box-refresh pushes + 6 dispatches = **11 of 27 (41%)**. A redeploy of the same SHA still proceeds (`deploy.yml`
  "Redeploy: Already at this commit; redeploying the same tree"), and `deploy/deploy.sh` `restart_service` is
  unconditional, so each success restarts the backend. [M]/[I] (dispatch-success restarts are inferred from that
  code path, not read from the journal).
* About 29 backend processes lived in those 60 h (27 deploy restarts + 2 watchdog restarts) and **2 wedged**
  (7%). Of the 13 processes with a known peak (the 11 clean stops and both wedges), 4 reached the 2.5 GiB line and
  2 of those wedged. Small sample. [D]

### 3.4 Startup scraper and Chromium [M — scrape telemetry run 39404821221, 3,002 samples, 28 runs, 2026-10-18 20:18Z -> 2026-10-20 10:58Z]

* `server.py` lifespan: `run_scraper(trigger="startup")` fires 3 s after boot **unconditionally** (no freshness
  skip), inside `dynasty.service`'s cgroup. A second scrape fires every `SCRAPE_INTERVAL_HOURS = 2` from boot.
  Of the 15 scrape starts in the retained event tail, 9 were `startup`, 6 `scheduled`. Because the 2 h timer
  restarts at every boot, a process that lives < 2 h never runs its scheduled scrape.
* Chromium: **700-745 MiB, 6 processes**, in every full run (max sample 744 MiB; the one partial capture of
  466 MiB was cut off mid-run). App RSS during a scrape ranged 864-2,097 MiB. Scrape duration ~4-6 min.
* During the startup scrape of a fresh process, in the sampled runs: cgroup 1.2-1.6 GiB. Aged process (~2 h,
  scheduled scrape): app 1.5-2.1 GiB + Chromium 0.72 GiB -> cgroup 2.0-2.56 GiB.
* **A fresh process can regrow fast.** The process the watchdog started on 2026-10-21 at 07:53:49Z already had
  `MemoryPeak` = **2,508,705,792 B (2,392 MiB, 93% of `MemoryHigh`)** when sampled at 08:23:43Z, ~30 min
  after start (`MemoryCurrent` then 1,626 MiB) [M, run 39568862441]. It started while a V1 browser suite was in
  progress (07:42:48 -> 08:06:18) and ran its own startup scrape, so 2.34 GiB is reachable within half an hour
  under verification load. `memory.peak` carries no timestamp, so whether the peak came from the scrape, from V1,
  or both is **[U]**. Implication for sizing: section 4.1.
* **One scheduled scrape on an aged process hit the line and survived**: run `0ae18b5a58f7`, 2026-10-19
  13:39-13:44Z, app RSS 2,097 MiB, Chromium 738 MiB, cgroup 2,560 MiB, `ev_high` = 781, memory stall <1%. It
  recovered because Chromium exited when the scrape ended and memory fell back under the line. That is the
  counter-example to "any contact with `memory.high` wedges": throttling clears if memory can be released.
  Anonymous heap that is *not* released (the 2026-10-21 shape) does not clear.
* **Chromium was not running at either wedge** as far as the data show: the 2026-10-19 startup scrape ended
  08:15:32Z (wedge from 08:28), and the 2026-10-21 startup scrape began ~07:18 and lasts ~5 min (wedge from
  07:50). The 2026-10-21 samples were **not retrieved** [U], so absence at 07:50 is inferred from the schedule.
  Consequence: isolating Chromium (Option E) would not have prevented either observed wedge. [I]
* All `minMemAvail` values in the sampler parse are unusable: GitHub secret-masking truncated several numbers
  (`3***1***5472`). Values quoted here were checked against the unit's own properties.

### 3.5 Verification (V1) activity [M — workflow runs]

* `v1-authenticated-verification.yml` runs after **every** successful `Deploy Production`
  (`workflow_run`, labelled "TEMP Week-1 proof bridge"), including deploys caused by a data-refresh commit. Its
  browser half is a Playwright suite against production (14-30 min per run).
* It already waits (bounded 300 s) for `/api/health` fast and `scrape_running == false`, so it no longer starts
  during the startup scrape (e.g. 2026-10-21: 07:23:02 -> 07:24:09 wait, then the suite).
* It shares the `production-deploy` concurrency group with deploys, so runs queue serially: on 2026-10-21 one
  run waited 86 min and two suites ran back-to-back for ~42 min (07:24 -> 08:06) starting 6 min after the
  restart. The 2026-10-19 wedge began 14 min into a 30 min suite.
* **V1 is present in both wedges and also in most clean processes** (every one of the 11 clean deploys was
  followed by a V1 run). It is therefore not, by itself, the discriminating factor, and the discriminator is
  **[U]**. W8's note records that one authenticated round of the V1 route set grew module-global state.

### 3.6 Deploy resource use and what has already been fixed

* CI side (no production effect): the `validate` job runs the hard suite, ~77 min and budgeted at 120 min.
  A deploy therefore lands 80-110 min after its commit.
* Box side: `npm ci --prefix frontend`, stage the tested artifact, `restart_service`, then post-deploy smoke from
  the runner. In artifact mode there is no `next build` on the box. Box CPU/memory during a deploy is **[U]**.
* The W8 memory fixes (`58be8d442` three process-lifetime retentions, `48ad3ea09` intel memos / overrides bytes,
  `12258316c`, and the watchdog snapshots `06dec030a`) **were all in the build that wedged on 2026-10-21**
  (`9e3c52fdc` contains each of them). The remaining heap growth (anon 2.6 GiB at 33 min) is therefore **not
  explained by the retentions already fixed**. [M]
* The growth is not linearly extrapolable: the process was throttled, so an unthrottled rate cannot be read from
  it. The only crude figure is ~+1.7 GiB in 33 min if the boot heap was ~0.9 GiB (the value other fresh processes
  show at startup); that is an **[E]** of ~50 MiB/min and is not used for any recommendation below.

### 3.7 What no measurement covers

* Which route or job allocates the growth (no heap profile; W8 used a module-global deep-size scan).
* What the process would reach with no throttle (every observed peak is censored at ~2.5 GiB or is the wedge).
* Box memory during deploys, and any memory figure for the unbounded timers.
* Stack of the wedged process (no `py-spy`).
* Whether SIGKILL or a cgroup OOM kill mid-scrape can leave a half-written data file (not audited here; the
  watchdog already SIGKILLs the process today, and a 3 GiB OOM kill is already possible).

---

## 4. Options

### 4.1 The 3,430 MiB figure and the host margin

3,430 MiB is **not in the repository** and I could not find its derivation. It is reproducible as a sum of
independently *measured maxima*: `2,560 (high) + 744 (Chromium) + 106 (frontend) + 18 (nginx) = 3,428`, or
`2,608 (anon at the wedge) + 744 (Chromium) = 3,352` plus slack. Both are **[E]**: they add maxima that have
**not co-occurred** (the wedge heap appeared 17-33 min after boot; a Chromium scrape coincides with an aged heap
only at the +2 h scheduled scrape), and the first form double counts Chromium, which is already inside the
2,560 MiB cgroup figure. Treat 3,430 as a plausible upper bound, not an observation.

Host margin [D, `scripts/memory_ceiling_budget.py`], host 7,941 MiB, non-backend use **~727 MiB** [D/E]. Derivation
(2026-10-21 08:23Z): `free -m` "used" was 2,315 MiB; "used" excludes page cache (reported under buff/cache), but
the backend's `MemoryCurrent` (1,626 MiB) *includes* the page cache charged to its cgroup. Subtracting
`MemoryCurrent` would therefore remove cache that "used" never contained and understate the rest (an earlier
draft did this and got 689 MiB). The backend's non-cache share is `anon` + `kernel` from its `memory.stat` =
1,660,657,664 + 4,698,112 B = 1,588 MiB, so non-backend non-cache use is 2,315 - 1,588 = **727 MiB** (frontend,
nginx, kernel, other processes). Still one sample, so an estimate:

| Scenario | Co-resident usage | Margin |
|---|---|---|
| Backend at the 3,430 estimate + non-backend 727 | 4,157 MiB | **+3,784 MiB** |
| Backend at proposed ceiling 3,584 + 727 + `ktc-trades` 512 + `market-ledger` 1,024 + `pick-forecast` 1,536 (every bounded timer at its ceiling at once; never observed) | 7,383 MiB | **+558 MiB** |
| *(2026-10-25)* Same, with `market-ledger` at its new 2,048 ceiling | 8,407 MiB | **−466 MiB** |
| Same absurd case at today's 3,072 ceiling | 6,871 MiB | +1,070 MiB |
| Observed at the wedge: host `MemAvailable` | - | 4,550 MiB free with the backend at 2,618 MiB |

So **simultaneous-load margin is not negative** on measured usage, and stays positive (+558 MiB) even in an
unrealistic all-ceilings case. The one place it *is* negative is the **sum of declared ceilings**: +251 MiB over
RAM today, +763 MiB if the backend ceiling were raised to 3,584M with the frontend left at 2G *(2026-10-25,
ledger at 2G: +1,275 today, +1,787 with the backend at 3,584M and the frontend at 2G; and the all-ceilings
co-resident margin above turns negative, −466 MiB — still a never-observed case, but no longer a positive one;
`OOMScoreAdjust=500` on the ledger makes it the host OOM killer's first choice over the backend)*. That is why the
frontend change in B belongs in the same package, and why the unbounded timers (unmeasured) are the residual
risk on the margin.

**Is 3,584M enough? Fast regrowth says: only probably, and not with much room.** Both wedged processes reached
~2.6 GiB within 17-33 min of boot, and the replacement started at 07:53:49Z on 2026-10-21 reached a 2,392 MiB
peak within ~30 min (section 3.4). So a heap of ~2.3-2.6 GiB is a *normal* half-hour state under verification
load, not a tail event. Add one Chromium scrape (~0.72 GiB, the +2 h scheduled scrape, or a startup scrape on a
process that has not reset its heap) and demand is ~3.1-3.35 GiB: inside 3,584 MiB with **only ~230-480 MiB
(7-14%) of room** [D/E]. Every one of those peaks was taken while throttled at 2.5 GiB, so the unthrottled
plateau is unknown; if the heap keeps growing past 30 min, 3,584M will be reached and the process killed.
That is why Stage 1 is a canary with a kill-count rollback trigger and a 3.4 GiB peak trigger, why 3,584M is
not presented as a fix, and why the heap profile of the V1 route set (section 7, item 3) is the real follow-up.
A larger ceiling (4G) still fits measured usage (+46 MiB in the all-ceilings case) but has no evidence base
either; raise it only if Stage 1 shows peaks clustering above ~3.2 GiB with no kills.

**Measurements that contradict or limit the proposals:**

* *Against B alone:* B leaves `MemoryHigh=2560M` in place, and the measured wedge is exactly that throttle.
  Frontend limits reduce declared ceilings by 1,024 MiB but release no memory; the frontend's highest measured
  peak is 137.3 MiB.
  `MALLOC_ARENA_MAX=2` has **no measurement in this repository** (nothing sets or tests it).
* *Against C as worded ("keep a MemoryHigh warning boundary"):* `memory.high` cannot warn; see 4.3.
* *Against D with `MemoryMax=3G` unchanged:* the 2026-10-19 13:39 scrape reached tree RSS 2,814 MiB while the
  cgroup was held at 2,560, and the wedge heap alone was 2,608 MiB. Without the throttle, 3,072 MiB leaves only
  ~260-460 MiB of margin over a heap + Chromium that was never given room to run unthrottled.
* *Supporting C+D:* host `MemAvailable` was 4.5 GiB at the wedge; the cgroup was throttled with 4.5 GiB free
  on the host, i.e. the limit, not the machine, was the constraint.

### 4.2 Options

| | Change | Fixes the measured wedge? | Main risk | Verdict |
|---|---|---|---|---|
| **A** | keep limits | No (2 wedges in ~3 days) | Recurring 3-15 min outages | Reject as the end state; it is the rollback state |
| **B** | `MALLOC_ARENA_MAX=2`; frontend 768M/1G only | No: leaves the throttle; the arena effect is unmeasured | Confounds any later measurement if combined with a limit change | Take the **frontend half now** (5.6x headroom to `MemoryHigh` and 7.5x to `MemoryMax` over the highest measured peak of 137.3 MiB; cuts declared ceilings 1,024 MiB); defer the arena half to its own A/B |
| **C** | `MemoryMax=3584M`, keep `MemoryHigh=2560M` "as a warning" | **No**: the throttle still engages at 2,560M | A throttle presented as a warning | Reject as worded |
| **C'** | `MemoryMax=3584M`, `MemoryHigh` raised near it (e.g. 3328M) | Partly: moves the wedge to 3.25 GiB | A 256 MiB throttle band is a smaller copy of the same trap, and it reproduces the stall for any slow-growth runaway | Reject |
| **D** | remove `MemoryHigh`, keep `MemoryMax=3G` | Removes the stall; converts it into a kill | Only ~260-460 MiB of room: a scrape on an aged heap can OOM-kill mid-scrape | Not alone |
| **C+D** | `MemoryMax=3584M`, **no** `MemoryHigh`, + frontend 768M/1G | Yes for the observed shape; a true runaway ends in a kill + 5 s restart + ~20 s boot (~30 s) instead of 3-15 min | See 4.4 | **Recommended**, as a canary first |
| **E** | scrape in its own unit | No: Chromium was not running at either wedge [I] | Large change: the scraper returns an in-process result dict that the server validates and publishes | Defer; revisit only if Chromium proves to be the discriminator |
| **F** | change V1 scheduling | Reduces load at the vulnerable time; does not remove the cause | V1 is a launch-evidence instrument; thinning it is an owner decision | Separate proposal (section 6.3) |

### 4.3 `MemoryHigh` is a throttle, not a warning

`memory.high` (cgroup v2) is the level at which the kernel starts **reclaiming from, and sleeping, the cgroup's
allocating tasks**. It emits no signal and kills nothing. On a host with no swap, anonymous memory is not
reclaimable, so at the line the kernel can only evict file pages (here: the process's own interpreter and
libraries, `file` ~0) and delay allocations. The evidence in 3.2 is that outcome, not a hypothetical.
A real "warning boundary" must be implemented in userspace: a report-only line in the minutely watchdog (it already
reads `memory.current` and `memory.high` in `cgroup_snapshot`) when `memory.current` crosses a chosen level,
**without** any kernel throttle. That is a change to a root-run script and is therefore proposed, not implemented
(section 5.2, Stage 0b).

### 4.4 What removing `MemoryHigh` costs (not risk-free)

1. **The cliff moves, it does not vanish.** At `memory.max` the kernel reclaims, then OOM-kills. With anonymous
   memory only and no swap, reclaim at the hard line is the same file-page eviction; a slowly creeping heap can
   still thrash briefly just under the max before the kill. Faster than 3-15 min, but not instant. [I]
2. **A leak is permitted to grow to 3.5 GiB before anything reacts**, with the watchdog (liveness only) as the
   sole signal. The throttle was the only per-cgroup "near the limit" counter (`ev_high`); without it,
   `memory.peak` / `memory.current` thresholds in the watchdog are the replacement.
3. **A kill mid-scrape** can take Chromium or the server (`OOMPolicy=stop` then stops the whole unit). Atomicity of
   the scraper's file writes under SIGKILL was not audited **[U]**.
4. **Host exposure grows by the same 512 MiB** as the ceiling (host margin stays positive, section 4.1).
5. **It hides the symptom if used as the fix.** The growth source is unidentified (3.6/3.7). The right companion
   is a heap profile of the V1 route set, not a larger box-wide ceiling.
6. **Peak statistics change meaning.** Peaks were censored at 2.5 GiB; after the change they become real demand
   for the first time. Expect them to read *higher* without anything having got worse.

---

## 5. Decision package

### 5.1 Recommendation

Adopt **C+D** (`MemoryMax=3584M`, no `MemoryHigh` on the backend) and the **frontend half of B**
(`MemoryHigh=768M`, `MemoryMax=1G`), rolled out in stages, with the watchdog and `OOMPolicy` unchanged.
Reasons: the throttle is the measured failure mode; the host has 4.5 GiB free at the stall; a hard kill recovers
in ~30 s, the throttle did not recover in 3-15 min; and the declared-ceiling sum stays under host RAM
(7,680 vs 7,941 MiB). *(2026-10-25: no longer true — with the ledger at `MemoryMax=2G` this package's sum is
8,704 MiB, 763 MiB over host RAM. Ceilings are not usage, but this reason no longer holds as written.)*

Confidence: **high** that the throttle must go; **medium-low** on 3,584M as the right number (it is 154 MiB above
the 3,430 estimate, which is a sum of non-co-occurring maxima, and only ~230-480 MiB above a fast-regrown heap
plus one Chromium scrape; section 4.1); **low** on whether this reduces the underlying growth (it does not).

### 5.2 Stages

**Stage 0 — evidence only (this PR).** Merge the scripts, tests, fixtures and this record. Then, to close the
gaps in 3.7, an operator with approval dispatches the existing **read-only** workflows (this PR does not):
`scrape-telemetry-diagnostics.yml` for 2026-10-21 (is Chromium present at 07:50?) and
`prod-restart-diagnostics.yml` for any later restart. Feed logs to `backend_restart_report.py`.

**Stage 0a — classify unmasked (workflow PR, precondition for Stage 1).** Apply
`docs/ops/patches/prod-restart-diagnostics-classify.PROPOSED.patch`. Every 24 h window contains a 22:xx hour, and
the 22nd of each month is masked whole, so a daily check read from the raw log will regularly be `incomplete`
(exit 3) whenever a backend or watchdog line lands there. Classifying on the runner removes that.

**Stage 0b — periodic report-only sampling (separate PR, not written here; precondition for Stage 1).** Today the
watchdog snapshots ONLY on a liveness failure (`dynasty-healthcheck.sh` around lines 310/319), so a healthy
period produces no samples. Several canary criteria are therefore unobservable while the system is healthy,
which is exactly when they must be shown to hold. Stage 0b: in the same minutely watchdog, every N minutes (e.g.
5) and report-only, log one allowlist-safe numeric line with: backend `memory.current` / `memory.peak` /
`memory.events` (`max`, `oom_kill`), host `MemAvailable`, host memory PSI `some`/`full` `avg10`, and the frontend
cgroup's `memory.events high` / `memory.current`. Add a transition-only `memory_watch` line when backend
`memory.current` crosses 2,560 MiB and 2,944 MiB (the "near the old boundary" signal that removing `MemoryHigh`
takes away). Extend `prod_restart_diagnostics.sh`'s allowlist and `backend_restart_report.py` to read them. It
changes no restart decision.

**Observability of the Stage 1 criteria and triggers, with today's tooling:**

| Criterion / trigger | Observable now? | Source |
|---|---|---|
| zero watchdog restarts; no backend OOM kill, crash or unexplained auto-restart | **yes** | restart diagnostics -> `backend_restart_report.py` (`watchdog_restarts`, `oom_kills`, `crashes`, `auto_restarts_without_cause`, `systemd_initiated`) |
| process peak < 3.2 GiB; trigger >= 3.4 GiB | **at each stop** (one-decimal `Consumed ... memory peak`), and the current process's `MemoryPeak` in the diagnostics' unit-properties section | same; `any_stop_peak_bytes_max` |
| no other unit OOM-killed; no kernel / oomd OOM line | **yes**, for lines that pass the diagnostics' "other units" filter | `other_unit_oom_kills`, `kernel_oom_lines` |
| breaches inside any watchdog snapshot, including recovered liveness failures | **yes, but only when a liveness failure happens** | `trigger_breaches`, `trigger_unknown_snapshots`, `liveness_fail_lines`, `recoveries_without_restart` |
| host `MemAvailable` >= 1.5 GiB | **no** while healthy (one `free -m` per diagnostics run is not a series) | needs Stage 0b |
| host memory stall `full` < 10% *outside a scrape* | **no**: no healthy-time samples, and "outside a scrape" needs the scrape windows | Stage 0b + `scrape-telemetry-diagnostics.yml` (`data/diagnostics/scrape_events.jsonl`) |
| frontend not throttled | **no**: its cgroup counters are never collected | Stage 0b |
| no half-written data file | **no tooling** | manual inspection on a kill; **[U]** |

**Who checks, how often, which command (7-day soak).** The canary owner (whoever runs Stage 1; named in the
work claim) checks once a day at a fixed time and after any page/alert:

```
gh workflow run prod-restart-diagnostics.yml -f since_utc="<D-1> 09:00" -f until_utc="<D> 09:00"
gh run view <run-id> --log      # with Stage 0a: read the printed classification summary
# without Stage 0a (raw, masked log):
gh run view <run-id> --log > day.log
python scripts/backend_restart_report.py day.log      # 0 = complete; 3 = INCOMPLETE -> not a pass
gh workflow run scrape-telemetry-diagnostics.yml      # scrape windows for the PSI criterion
```

A day whose report exits 3, or whose Stage 0b samples are missing, does **not** count toward the 7 days.

**Stage 1 — runtime canary (operator; no unit-file change, no restart; writes runtime drop-ins under `/run` that
last until clean-up or reboot).**

```
sudo systemctl set-property --runtime dynasty.service MemoryMax=3584M MemoryHigh=infinity
systemctl show dynasty.service -p MemoryMax -p MemoryHigh       # 3758096384 / infinity
cat /sys/fs/cgroup/system.slice/dynasty.service/memory.max /sys/fs/cgroup/system.slice/dynasty.service/memory.high
```

`systemctl` is within the deploy user's NOPASSWD scope per `deploy/reconcile-runtime-controls.sh`; whether the
exact `set-property` invocation is permitted is **[U]** (sudoers is not in the repo). Apply the frontend ceilings
the same way (`... set-property --runtime dynasty-frontend.service MemoryHigh=768M MemoryMax=1G`).

**What `--runtime` leaves behind, and why it matters.** `set-property --runtime` applies the values to the live
cgroup *and* writes drop-ins under `/run/systemd/system.control/<unit>.d/` (for these properties
`50-MemoryMax.conf` and `50-MemoryHigh.conf`). Those drop-ins override the unit file **until reboot**: they
survive `daemon-reload`, a deploy's unit rewrite and service restarts. So:

* setting the old values back restores the *values* but leaves the *state*: the unit is still governed by
  runtime drop-ins rather than by its file;
* while they exist, **any later change to the unit file is silently masked**: a Stage 2 deploy (same values,
  harmless) or, worse, a Stage 2 rollback to 3G would not take effect until reboot.

The canary therefore ends with an explicit clean-up (section 5.3), whether it succeeds or not.

Soak: **7 days and at least 20 backend restarts**, including at least two deploys followed by V1 suites.

Preconditions: Stage 0a and Stage 0b are live (otherwise several criteria below cannot be observed; see the
table above).

Success criteria:
* every daily report `input: complete` (exit 0);
* zero `watchdog_restart` stops; `backend_restart_report.py` shows only `clean_stop` over the soak, i.e.
  `oom_kills`, `crashes`, `auto_restarts_without_cause` and `systemd_initiated` all 0. The report counts
  systemd-initiated stops that have no `Stopping` line and finds the backend unit from its description; in a
  GitHub-masked log the unit is `***.service`, so `--unit dynasty.service` would never match there (use the
  unmasked Stage 0a summary, or `--unit '***.service'` on a raw log);
* every process peak < 3.2 GiB (`Consumed ... memory peak`; the first uncensored distribution);
* host memory stall `full` (`h_full_avg10`) < 10% outside scrape windows and host `MemAvailable` >= 1.5 GiB in
  every Stage 0b sample; `kernel_oom_lines` = 0;
* `other_unit_oom_kills` empty and no frontend `memory.events high` increase (Stage 0b).

Rollback triggers (any one): a process peak >= 3.4 GiB (growth is unbounded at the new ceiling); any backend
`oom_kill`; host `MemAvailable` < 1.5 GiB in any snapshot or sample; host memory stall `full` > 10% outside a
scrape; any other unit OOM-killed; an unexplained half-written data file. `backend_restart_report.py` lists every
snapshot that breaches one (`trigger_breaches`) and every snapshot whose trigger inputs were unreadable
(`trigger_unknown_snapshots`, which is not a pass either). Omit `--high-bytes` during the canary: `MemoryHigh` is
`infinity`.

**Stage 2 — persist.** After a clean soak, open one reviewed PR applying
`docs/ops/patches/backend-memory-policy-stage2.PROPOSED.patch` (backend `MemoryMax=3584M` with `MemoryHigh`
removed; frontend 768M/1G; comments record the measurement). **Clear the Stage 1 runtime drop-ins first**
(section 5.3, steps 2-4) so the unit file, not `/run`, governs the unit after the deploy; then deploy normally.
Verify afterwards that `systemctl show dynasty.service -p DropInPaths` lists nothing under
`/run/systemd/system.control/`.

**Stage 3 — `MALLOC_ARENA_MAX=2`, separate A/B (never with a limit change).**
`docs/ops/patches/backend-malloc-arena-stage3.PROPOSED.patch`. Protocol on a non-production Linux machine with the
production contract cached: start `server.py` twice (default vs `MALLOC_ARENA_MAX=2`), replay the same V1 route
set for N rounds (the W8 deep-size scan's route list), sample `VmRSS` and `smaps_rollup` after each round and
p95 latency of `/api/data?view=app` and `/api/trade/analyze`. Adopt only if steady-state RSS is lower by >= 10%
**and** p95 latency does not regress by > 10%. Glibc arenas affect only non-pymalloc allocations (> 512 B) made
from threads, so the gain is plausible but **entirely unmeasured here**.

### 5.3 Rollback

**Stage 1 clean restore** (values first, then state; no service restart). Run for `dynasty.service` and, if the
frontend canary was applied, the same for `dynasty-frontend.service` with `MemoryHigh=1536M MemoryMax=2G`:

```
# 1. restore the values on the live cgroup immediately
sudo systemctl set-property --runtime dynasty.service MemoryMax=3G MemoryHigh=2560M
# 2. see every drop-in that currently shapes the unit
systemctl show dynasty.service -p DropInPaths
ls -l /run/systemd/system.control/dynasty.service.d/
# 3. remove ONLY the runtime control drop-ins the canary created (needs root: rm is
#    not in the deploy user's NOPASSWD set, which is systemctl/journalctl/install/chown)
sudo rm -f /run/systemd/system.control/dynasty.service.d/50-MemoryMax.conf \
           /run/systemd/system.control/dynasty.service.d/50-MemoryHigh.conf
# 4. reload and verify the unit file governs again
sudo systemctl daemon-reload
systemctl show dynasty.service -p DropInPaths -p MemoryMax -p MemoryHigh   # no system.control path; 3221225472 / 2684354560
cat /sys/fs/cgroup/system.slice/dynasty.service/memory.max /sys/fs/cgroup/system.slice/dynasty.service/memory.high
```

Step 1 makes the live values correct without relying on how `daemon-reload` re-applies cgroup attributes; steps
3-4 remove the state. A reboot also clears `/run`.

**On `systemctl revert dynasty.service`.** It removes the unit's drop-ins (runtime control drop-ins included) and
keeps the unit file itself, because `dynasty.service` has no vendor copy under `/usr`. The repository installs
**no** drop-in for `dynasty.service` (no `dynasty.service.d` anywhere in `deploy/`), so on a host built only from
the repo, `revert` equals steps 3-4, and it works within the deploy user's systemctl scope. It is **unverified**
whether hand-made drop-ins exist on the box: operator docs suggest `systemctl edit` drop-ins for other units, and
`revert` would delete any for this one without confirmation. So use `revert` only after step 2 shows that the
only drop-ins are the two `system.control/50-Memory*.conf` files; otherwise use the targeted `rm`.

| Stage | Rollback | Time |
|---|---|---|
| 1 | The clean restore above (values in seconds, state with root). Values alone (step 1) are an acceptable emergency stop, but leave the runtime drop-ins in force until clean-up or reboot. | seconds; no restart |
| 2 | Revert the PR and let the normal deploy reconcile the unit (`deploy/reconcile-runtime-controls.sh` runs on deploy and on `deploy/rollback.sh`). First confirm no `/run/systemd/system.control/dynasty.service.d/` drop-in is left from Stage 1: it would mask the reverted unit file until reboot. | one deploy |
| 3 | Revert the patch; the next restart drops the variable. | one deploy |

Do not edit the unit file by hand on the host: the deploy reconciler overwrites it from the template.

### 5.4 Residual risks the package accepts

The growth source stays unknown; a runaway now ends in a kill rather than a stall; the unbounded timers' memory is
unmeasured; peaks will read higher once uncensored; two wedges in ~29 processes is a small sample.

---

## 6. Is the 2 h data refresh restarting the backend or scraping at peak? (question 3)

**Yes, indirectly, and it is mostly the deploy path, not the refresh jobs.**

1. **Box-side DLF (`:27` every 2 h) and IDPShow (`:32`) commit to `main`** from a dedicated clone
   (`/var/lib/dlf-fetch/repo`, *not* the live tree). A commit that touches `CSVs/site_raw/*.csv` passes
   `deploy.yml`'s `paths-ignore` (`data/**`, `exports/**` only), is pushed with a real key, and starts a full
   deploy. 4 of the 11 restarts in the verified 24 h were these. [M]
2. **`scheduled-refresh.yml` (`:42` every 2 h) pushes with `GITHUB_TOKEN`** (author `github-actions[bot]`), which
   does not start a push run, and then **dispatches `deploy.yml` explicitly** when its last commit says
   `automated data refresh|freshness stamps` (so `source_health` does not freeze). 11 dispatches in 60 h, 6
   successful. [M]
3. **Hill Autopilot evidence commits** (`config/model_registry/**`) are also bot pushes: no push deploy. [M]
4. **Docs/tests-only commits** (`docs/**`, `tests/**`, `*.md`) are not ignored and start a full deploy too. [M]
5. **Every deploy restarts the backend and every boot starts a scrape (Chromium) after 3 s**, with no freshness
   check. A restart also resets the 2 h scheduled-scrape timer. [M]
6. **Data transport is the deploy**: DLF CSVs reach the live tree only through a deploy (the box timer works in a
   separate clone). Of the 40 deploy runs created in 60 h, 7 were cancelled because a newer queued deploy
   superseded them (that newer deploy carries the same data, so these cost latency, not data), 1 was still running
   when listed, and **5 actually failed** (1 push, 4 dispatches). A failed deploy leaves the data waiting for the
   next successful one, so freshness for those data depends on the deploy pipeline staying green. [M]

Peak-hour overlap: the box timers (`:27`, `:32`, ktc `:07/:37`) and the scheduled scrape do not by themselves
approach the limit; the observed pressure came from a freshly restarted process under the V1 suite.

### 6.1 Minimal decoupling that preserves freshness (proposal, not applied)

Keep every refresh job exactly as is. Change only *what a data-only commit costs*:

* **D-1 (smallest; workflow + `deploy.sh`, no application code).** Add a data-only release mode: when the diff
  from the last deployed commit to the target touches only `CSVs/**`, `data/**`, `exports/**`, the deploy (a) skips
  the full hard suite but keeps the blocking API-contract check, (b) syncs only those paths into the live tree,
  and (c) **does not restart** `dynasty.service`. The running process picks the new CSVs up at its next contract
  build (the scrape loop or prime; the source map is `src/api/data_contract.py` lines 457-554) **[I — to be
  verified in the measurement below]**. Latency: today a DLF commit reaches production 80-110 min later (CI +
  restart); under D-1 it reaches the live tree in minutes and is served at the next scheduled scrape (<= 2 h,
  and that timer actually fires once restarts stop resetting it). Average freshness is therefore not worse, and
  the dispatch carrier stops being a single point of failure for data.
* **D-2 (application, optional).** Make the startup scrape conditional: skip it when the last successful
  scrape is younger than a fraction of `SCRAPE_INTERVAL_HOURS` and the contract on disk is current, and schedule
  the first loop scrape at `last_success + interval` rather than `boot + interval`. Removes ~11 Chromium launches
  a day without changing the maximum data age. Needs its own tests (`server.py` lifespan).
* **D-3 (cheap, independent).** Add `docs/**`, `tests/**`, `**/*.md` to `paths-ignore`. Saves restarts that ship
  nothing; costs nothing.

None of these disables a refresh; D-1 and D-3 change deploy classification only, D-2 changes when a scrape starts,
never whether one runs.

### 6.2 Reproducible measurement

**Before / after on commits (offline, exact):**
`python scripts/deploy_trigger_audit.py --ref origin/main --since T0 --until T1 --runs-json runs.json`.
Baseline (this PR): predicted push deploys equal push runs created, 29/29 over 60 h and 11/11 over the verified
24 h (both selected by commit / creation time). For RESTARTS add `--restart-log LOG` (a restart-diagnostics log
of the same window): the 24 h baseline is 11 restarts = 7 runtime + 4 DLF. Acceptance after D-1/D-3:
`box_data_refresh` and `non_runtime_only` causes drop to 0 in the restart attribution while the audit still
reports the same number of refresh commits; restarts per day fall from ~10.8 toward the runtime-change count
(~7 in the baseline day).

**On the host (read-only, existing workflow):** dispatch `Production Restart Diagnostics (read-only)` for a 24 h
window and run `backend_restart_report.py` on the log: `clean_stops` per day, `clean_stop_peak_bytes_*`, and
`watchdog_restarts == 0`.

**Freshness (must not regress):** for each box refresh commit `chore(dlf): automated refresh <T>`, record the
time the live contract first reports that dataset as updated (the per-source dataset-state clock owned by
`src/sources/dataset_state.py`). Today's lag is ~80-110 min; acceptance is a median <= 120 min and no
sample > 4 h across a week. **[U]**: I did not confirm which public field exposes that clock; define it before
D-1 ships.

### 6.3 Scheduling verification (Option F, separate decision)

* V1 already waits for `scrape_running == false`. Remaining knobs: run V1 only when the deploy changed runtime
  files (skip data-only and docs-only deploys); and give it its own concurrency group so a queued V1 cannot hold
  a deploy or stack two suites back-to-back. V1 is a launch-evidence instrument with a "TEMP" trigger; changing
  when it runs is an owner decision, so no patch is attached.

---

## 7. Unresolved

1. Exact mechanism of total non-response during the throttle (no stack; stall < 100%).
2. 2026-10-19 has no cgroup counters; its verdict remains circumstantial.
3. The allocation source behind 2.6 GiB in 33 min after the W8 fixes; needs a heap profile of the V1 route set.
4. Uncensored memory demand; first available once the throttle is lifted.
5. Whether Chromium was present at 2026-10-21 07:50 (telemetry not retrieved).
6. Provenance of 3,430 MiB; reconstructed, not found.
7. Atomicity of scraper writes under SIGKILL/OOM-kill.
8. Whether `systemctl set-property --runtime` is permitted for the deploy user, and whether any hand-made drop-in
   for `dynasty.service` exists on the box (decides whether `systemctl revert` is safe; section 5.3).
9. Box memory during deploys; memory of the unbounded timers.
10. Which field exposes per-source data freshness for the section 6.2 lag measurement.
11. `MALLOC_ARENA_MAX=2` effect: unmeasured.
12. Stage 0a (proposed workflow patch) is not applied and Stage 0b (periodic sampling) is not written; until both
    exist, host `MemAvailable`, host stall outside scrapes and frontend throttling are unobservable while healthy.
13. The 727 MiB non-backend figure is one sample (2026-10-21 08:23Z) and an estimate.
