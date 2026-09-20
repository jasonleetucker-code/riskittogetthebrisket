# Scrape telemetry — reading the evidence

**Status: diagnostic instrumentation. It changes no resource behaviour.**
Shipped 2026-09-17 after two attempted fixes for the KTC-phase production
outage both failed, on the owner's direction to stop guessing and make the
next occurrence self-diagnosing.

## The incident this exists to explain

Production goes **completely silent** — `curl` exit 28, zero bytes, on
`/api/health`, `/api/status` and login alike — for ~3 minutes, always
during the scrape's `source_start` / KTC phase, then returns 502s briefly,
then recovers. The process restarts and a fresh `trigger=startup` scrape
begins, which can hit the same wall again.

**The ordering is the clue.** Silence comes FIRST; 502s appear only at the
END. A clean cgroup OOM-kill of the dynasty process alone cannot produce
that: nginx is alive with `proxy_connect_timeout 5s`, so a dead upstream
answers 502 *immediately*, not after three minutes of nothing. Silence
first is what you see when **nginx itself is starved too**, with the 502s
arriving only once dynasty died and released enough resource for nginx to
answer at all.

That is a hypothesis, not a finding. It is the reason the sampler measures
**system-wide** state from a process that is **not** dynasty — because
dynasty may be the victim here, and a dead process reports nothing.

## What is captured, and where

Two files under `data/diagnostics/`, both JSONL, both untracked:

| File | Writer | Contents |
|---|---|---|
| `scrape_events.jsonl` | dynasty (in-process) | every scrape phase, KTC sub-step + duration, Chromium launch/close timestamps, scrape start/end/failure |
| `scrape_samples.jsonl` | detached sampler (out-of-process) | ~5s resource samples (~2s during browser/KTC), system-wide + per-tree |
| `scrape_phase.json` | dynasty | current phase, so the sampler can stamp each sample |

### Why `data/diagnostics/` and not `data/scrape_state/`

Load-bearing, not cosmetic. `scheduled-refresh.yml` runs
`git add -f data/scrape_state/` **from the GitHub Actions runner**. A file
written there becomes *tracked* — and `deploy/deploy.sh` uses
`git reset --hard`, which overwrites tracked files. The next deploy would
replace the box's real telemetry with the runner's copy. The evidence
would destroy itself. `data/diagnostics/` is in no force-add list, so it
stays untracked, survives deploys, and stays local to the box.

### Survivability

The sampler is a separate process, so it keeps writing after dynasty is
killed and records **the exact sample in which dynasty's PID vanished** —
the one observation nothing inside the dying process can make.

Honest limit: it lives in dynasty's systemd cgroup. The unit sets
`MemoryMax=3G` but **no `OOMPolicy=`**, so `memory.oom.group` stays 0 and
the kernel kills the single highest-badness task — never a ~10 MB stdlib
sampler. It should survive. It is not guaranteed to: if the unit ever
gains `OOMPolicy=kill`, the whole group dies together. Even then every
flushed line survives, which is strictly more than existed before.

Writes are `flush()`ed but deliberately **not** `fsync()`ed: the threat is
process death, not power loss, and flushed bytes already belong to the
kernel.

## Retrieving it

The files are untracked and local, so they never reach the repo. Either:

```bash
# On the box
tail -n 400 data/diagnostics/scrape_samples.jsonl
tail -n 400 data/diagnostics/scrape_events.jsonl
```

or, from a logged-in allowlisted browser session:

```
GET /api/admin/scrape-telemetry?limit=400
```

Admin-gated on purpose — PIDs, RSS figures and cgroup limits are
operational internals that help time a resource attack. Not league data,
but not public either.

Log markers also reach `journalctl -u dynasty` (the unit sets no
`StandardOutput`, so it defaults to journald).

## Reading it — signature to cause

Work the sample stream around the silent window. These are the owner's
six candidate causes and what each looks like in the data.

| Candidate cause | Signature to look for |
|---|---|
| **cgroup / OOM memory pressure** | `memory.events.oom_kill` **increments** — this settles it outright, no inference needed. Expect `memory.current` approaching `memory.max` (3 GB) beforehand, and `target_alive` flipping to `false` at that moment. |
| **CPU saturation** | `cpu_util_pct` pinned near 100 and `load1` far above core count, while `mem_available_pct` stays healthy and `oom_kill` never moves. `psi_cpu.some_avg10` high. |
| **Combined resource pressure** | Both of the above partially: memory tight but no `oom_kill`, CPU high, `psi_memory` **and** `psi_cpu` both elevated. Swap climbing (`swap_used_pct`) is the classic tell — the box thrashing rather than cleanly dying. |
| **Blocking I/O / process hang** | `target_alive` stays **true** across the whole silent window, RSS and CPU flat, `psi_io` elevated. Nothing died; something stopped. The KTC sub-step markers name which operation it stopped in. |
| **nginx / upstream starvation** | The distinguishing case, and the reason the sampler is out-of-process: `target_alive: true` and dynasty's own numbers look unremarkable, yet the site answered nothing. Look for system-wide `MemAvailable` collapsing or `psi_memory.full_avg10` high — pressure the *box* felt but dynasty did not cause. |
| **Something else** | `oom_kill` flat, CPU moderate, PSI quiet, `target_alive` true throughout — then the cause is not resource exhaustion at all and the KTC sub-step timings are the next thread to pull. |

Two cross-checks worth doing every time:

1. **Correlate with the probe.** Line the sample timestamps up against the
   minute the site went silent. A cause that does not move *during that
   window* is not the cause.
2. **Chromium vs app split.** `chromium_rss_kb` versus `app_rss_kb`
   answers "is the browser eating it, or the app?" — which no aggregate
   number can, and which decides whether the fix belongs in the scraper
   or in the server.

## Switching it off

`RISKIT_SCRAPE_TELEMETRY=0` (and restart) disables every write and the
sampler spawn. The instrumentation never raises — a monitoring helper
that can break the thing it monitors is worse than none — so switching it
off should never be necessary to keep a scrape running.
