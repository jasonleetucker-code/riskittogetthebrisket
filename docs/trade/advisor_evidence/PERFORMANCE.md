# Lane E-4: multi-team trade analysis performance (local only)

**Date:** 2026-10-20
**Code measured:** `650bea6147`, the Lane D head. It contains Lane A #1882 (`44960d624c`), Lane C #1861 (`82ca5fa984`) and main `ca53209110`. It was checked out as a throwaway sparse worktree, which has since been removed.
**Contract:** the real checked-out board `exports/latest/dynasty_data_2026-10-20.json` (1,095 players), with the real `dynasty_main` rosters for 12 teams.
**Never against production.** Every request went to `127.0.0.1` on a locally booted `server.py`. Nothing was merged or deployed. No flag default or committed config was changed.

## 1. Answer

### Recommended response floor

**Recommended `responseFloorMs`: `200`, a single value.**

How it was derived, following the method in spec §6.3 (P1):
- The method takes the p99 of the worst-case valid request in `market_fairness` mode: N = maxTeams, maxLegs = 128, every asset priced, cold snapshot memo.
- I measured that p99 in three independent cold replicates for N = 2, 3 and 4.
- The largest replicate p99 was **155.9 ms**.
- 200 ms is the smallest 50 ms step at or above that.

Results at 200 ms in the largest raw-sample run (C3; 1,197 worst-case 4-team samples):
- 0.42% of worst-case 4-team requests exceeded the floor.
- 0% of 2-team and 3-team requests exceeded it.
- At 250 ms the exceedance was 0%.

A per-team-count table, `{"2":150,"3":200,"4":200}`, also works and was verified. It saves 50 ms only for 2-team trades. I recommend the single value because it is simpler. The table is a valid alternative if the owner prefers it.

### Status of the other controls

- **Floor:** behaves as specified.
- **Single-flight:** behaves as specified.
- **Limiter:** behaves as specified.
- **Body cap:** behaves as specified.
- **Error-path timing:** behaves as specified.

### Memory

Memory is not a constraint:
- No OOM kill and no limit hit in any run.
- The peak cgroup usage was 1.97 GB against a 2.56 GB hard cap, with a production-like 1.8 GB baseline.

### CPU and the GIL

CPU, and specifically Python's GIL, is the binding constraint.

**There is no admission or concurrency bound on either analyze route, and no compute timeout.**
- Public worst-case throughput saturates at about 12–14 requests per second on one core.
- Above that, requests queue, latency rises roughly in proportion to concurrency, and unrelated routes slow down. `/api/health` went from 19 ms to 0.7–1.4 s at 32 concurrent public requests, and up to 10 s at 32 concurrent private requests.
- The rate limiter's global bucket allows a burst of up to 3,000 requests, so a burst well above saturation is possible.

This is the main finding for launch readiness (§6). It goes to Lane C for the public route and Lane A for the private route.

## 2. Method

### Harness and scripts

All of these are in the scratchpad and run locally only:
- `<session-scratchpad>/tam/e4/harness/run_backend.py` boots `server.py`. In that process only it:
  - turns both trade flags on;
  - opens the launch gate (its owner inputs stay null in committed config);
  - turns the scrape scheduler off.
  
  It also stamps the checked-out rosters "live, fetched now", as the E-3 harness does. Without that stamp every team is honestly UNABLE (SD-7) and the engine never runs its FAIR / NOT FAIR path. Optional knobs:
  - `E4_FLOOR_MS`: the floor to apply;
  - `E4_COLD_MEMO=1`: clears the ledger snapshot memo and the public index memo before every `snapshot_for` call;
  - `E4_BALLAST_MB`: production-like resident memory;
  - `E4_NO_LIMIT=1`: limiter capacities ×1e6, keeping the same code path;
  - `E4_GIL_HOG=N`: in-process Python CPU threads;
  - `E4_TRACEMALLOC=1`;
  - `E4_TIMING_LOG`: a per-`analyze_trade_n` log of wall and CPU ms.
- `.../e4/harness/start.sh` boots that process inside fresh cgroup-v1 memory and CPU groups. `systemd-run` is unavailable here because PID 1 is not systemd. Enforcement was verified directly:
  - a 3 GB allocation was OOM-killed under a 2,560 MB limit;
  - the CPU quota throttled 30 of 31 periods.
- `.../e4/harness/measure.py` covers the scenario catalogue, sequential latency, concurrency with a parallel `/api/health` probe, memory sampling (RSS plus cgroup usage every 20 ms), single-flight, floor and limiter checks. `phase1.sh` to `phase4.sh`, `phase2b.sh` and `phase3.sh` are the exact sequences that were run.
- `.../e4/harness/clean_assets.py` classifies each asset with the private engine's own per-asset evidence (`quarantined`, `valueFreshness`), so the worst-case trades use only clean assets.
- Raw outputs are in `.../e4/out/`:
  - `seq_*.json` (C3 includes raw samples);
  - `conc.jsonl`, `flight.jsonl`;
  - `floorcheck_F*.json`, `limits_F.json`;
  - `timing_*.jsonl`, `cg_*.txt`;
  - `phase*.log`.

### Resource configurations (approximating the production backend unit)

| config | memory | CPU | other | stands for |
|---|---|---|---|---|
| **A** | 2,560 MB hard cap (prod `MemoryHigh`; prod `MemoryMax` is 3 G, so this is stricter) | 1.0 CPU (cfs quota) | 1,350 MB ballast, giving a baseline RSS of about 1.80–1.84 GB. Production web RSS is 1,838 MB per `docs/performance/evidence/linux-inventory-2026-09-26.json`. | quiet production |
| **B** | as A | **0.5** CPU | — | box busy (scrape and frontend on the same 4 vCPU) |
| **H** | as A | 1.0 CPU | **one in-process pure-Python CPU thread** (`E4_GIL_HOG=1`), cold memo | in-process scrape or post-publish rebuild competing for the GIL. This is a pessimistic upper bound. |

Production is a single uvicorn worker, so one Python process (one GIL) serves every route. That is why a 1-CPU quota is the relevant constraint and not the box's 4 vCPU.

### Scenarios (real rosters)

**Representative** (real assets, so real UNABLE outcomes are included):

| scenario | shape |
|---|---|
| `rep2_1v1` | 2 teams, 1-for-1 |
| `rep2_3v2` | 2 teams, 3-for-2 mixed |
| `rep3_cycle2` | 3-team cycle, 2 assets each |
| `rep4_cycle2` | 4-team cycle, 2 assets each |
| `rep4_mixed3` | 4-team fan-out, 3 assets each |

**Worst-case valid**: maxLegs = 128 legs, every asset priced and clean, every team sending and receiving (public `send_and_receive`):

| scenario | shape | outcome |
|---|---|---|
| `worst2_128` | 68 / 60 | FAIR / FAIR |
| `worst3_128` | 43 / 43 / 42, cycle | FAIR ×3 |
| `worst4_128_cycle` | 32 ×4, cycle | NOT_FAIR ×4 |
| `worst4_128_fanout` | 32 ×4, each team spread over the other three | 2 FAIR, 2 NOT_FAIR |
| `worst4_128_skew` | one team sends 85 to one receiver; 43 legs close the loop | NOT_FAIR ×4 |

All of these were confirmed through the full success path, not an evidence gate.

### Timing and noise

- Client-side wall time was measured over loopback, direct to the backend with no nginx or Next in between. Engine time is from the timing log.
- For a 128-leg body, cost scales with team count, not leg count. `worst2_128` (about 34 ms p50) is cheaper than `rep4_cycle2` (about 46 ms p50).
- **Noise:** the sandbox is a shared 4-vCPU Xeon at 2.30 GHz running other lanes' stacks. The load average during runs was 1.2–12.8. Wall-clock p99 is inflated by host noise; engine CPU p99 is the deterministic part (§3.3). Production per-core speed relative to this sandbox is not known (§7).

## 3. Results

### 3.1 Public `market_fairness`: sequential, config A (ms, client wall time)

| scenario | warm p50 | warm p99 | cold p50 (Acold / C2 / C3) | **cold p99 (Acold / C2 / C3)** |
|---|---|---|---|---|
| rep2_1v1 | 26.8 | (201.8)\* | 31.9 / – / 28.9 | (229.0)\* / – / 45.4 |
| rep2_3v2 | 25.0 | 39.4 | 30.7 / – / – | 75.4 |
| rep3_cycle2 | 34.9 | 57.3 | 40.7 / – / 40.1 | 72.4 / – / 58.4 |
| rep4_cycle2 | 45.7 | 77.4 | 50.2 / – / 54.6 | 136.1 / – / 86.4 |
| rep4_mixed3 | 45.5 | 73.9 | 55.0 | 114.2 |
| **worst2_128** | 33.7 | 57.9 | 39.2 / 42.5 / 38.6 | **73.8 / 123.5 / 61.5** |
| **worst3_128** | 44.0 | 72.2 | 55.3 / 48.9 / 51.1 | **155.9 / 85.3 / 82.6** |
| **worst4_128_cycle** | 55.4 | 90.2 | 62.1 / 60.0 / 60.4 | **133.3 / 102.5 / 97.0** |
| **worst4_128_fanout** | 55.0 | 96.4 | 57.9 / 60.7 / 60.6 | **95.8 / 99.2 / 104.4** |
| **worst4_128_skew** | 53.8 | 82.9 | 59.2 / 58.5 / 61.4 | **93.2 / 139.9 / 100.3** |

\* `rep2_1v1` was the first scenario run after boot. Its p99 includes the process's start-up background work (the public-league warm-up), not the advisor. With a settle period first (C3) it is 45 ms.

- Sample sizes: n = 299 per cell; C3 used n = 399.
- The cold memo costs about 5 ms at p50 (snapshot build).

**Floor inputs.** The worst-case cold p99 maximum across replicates was:
- N = 2: 123.5 ms
- N = 3: 155.9 ms
- N = 4: 139.9 ms

That gives 155.9 ms overall, so **200 ms**.

C3 raw samples:
- N = 4 (n = 1,197): p99 102 ms, p99.9 210 ms, max 222 ms; exceeding 150 ms 0.75%, 200 ms 0.42%, 250 ms 0%.
- N = 3: max 190 ms.
- N = 2: max 174 ms.

### 3.2 Public under contention

- **Config B (0.5 CPU), worst4 skew, sequential:** p50 141 ms, p99 233 ms.
- **Config H (GIL hog, cold memo):**

  | scenario | p50 (ms) | p99 (ms) |
  |---|---|---|
  | rep2 | 104 | 222 |
  | rep4 | 165 | 287 |
  | worst2 | 185 | 482 |
  | worst3 | 183 | 458 |
  | worst4 | 191–213 | 470–623 |

  While in-process CPU work holds the GIL, a 200 ms floor is exceeded on most worst-case requests. The `exceeded the floor` warning (`public_trade_advisor_api._apply_floor`) records this. A floor large enough to cover that window would be about 650 ms on every public answer. I do not recommend that without the owner weighing it (§5).

### 3.3 Engine-only time (`analyze_trade_n`, from the timing log; config A warm / cold)

| mode | 2 teams, 128 legs | 3 teams, 128 legs | 4 teams, 128 legs |
|---|---|---|---|
| market_fairness: CPU p50 / p99 | 27 / 48 | 37 / 64 | 47 / 82 |
| asset_only: CPU p50 / p99 | 135 / 180 | 176 / 304 | 208 / 398 |
| team_context: CPU p50 / p99 | 108 / 232 | 150 / 265 | 195 / 396 |

Public `market_fairness` costs about a quarter of the private modes. That matches spec §2.11: it skips capacity, final roster, utility and posture.

### 3.4 Private `/api/trade/analyze-multi`: sequential, config A warm (ms)

| scenario | asset_only p50 / p99 | team_context p50 / p99 |
|---|---|---|
| rep2_1v1 | 77 / 193 | 91 / 202 |
| rep3_cycle2 | 119 / 228 | 128 / 245 |
| rep4_cycle2 | 152 / 273 | 176 / 314 |
| worst2_128 | 157 / 208 | 128 / 250 |
| worst3_128 | 200 / 330 | 174 / 291 |
| worst4_128 (cycle / fanout / skew) | 231 / 355 · 219 / 354 · 325 / 685 | 214 / 342 · 201 / 351 · 314 / 525 |

Cold memo adds noise more than cost: the worst4 skew cold p99 for team_context was 883 ms, with n = 59.

`team_context` locally is a **lower bound**:
- Real posture inputs and BDVM projections are not available on this box.
- Every private headline here was NOT_ENOUGH_EVIDENCE or NO_TOO_CLOSE (quarantined or stale assets, see §7). So production's cold posture-bundle build was not exercised.
- Comparables are computed only at N = 2 and are included in the 2-team private numbers. At N ≥ 3 they are stamped `not_computed_multi_team` (SD-12), so they cost nothing there. This lane did not measure their cost at N ≥ 3.

### 3.5 Concurrency (config A unless noted; worst4 skew; "distinct" means a different ledger per request, so single-flight cannot merge)

| run | concurrency | throughput (rps) | latency p50 / p99 (ms) | `/api/health` p50 / max during run (ms) | codes |
|---|---|---|---|---|---|
| public, distinct | 1 | 15.7 | 59 / 74 | 20 / 28 | 200 ×30 |
| public, distinct | 4 | 11.8 | 304 / 479 | 97 / 160 | 200 ×32 |
| public, distinct | 8 | 13.8 | 529 / 734 | 152 / 511 | 200 ×64 |
| public, distinct | 16 | 12.4 | 1,239 / 1,560 | 274 / 826 | 200 ×128 |
| public, distinct | 32 | 11.6 | 2,243 / 3,379 | 737 / 1,420 | 200 ×128 |
| public, **identical** (single-flight) | 16 | **51.3** | 172 / 529 | 66 / 443 | 200 ×128 |
| public mix (rep2, rep3, rep4, worst3, worst4-fanout) | 8 | 21.0 | 355 / 651 | 58 / 319 | 200 ×200 |
| B (0.5 CPU), public, distinct | 8 / 16 | 6.7 / 6.0 | 1,121 / 1,577 · 2,504 / 3,613 | 269 / 578 · 735 / 1,562 | all 200 |
| H (GIL hog, cold), public, distinct | 8 | 8.0 | 839 / 1,410 | 241 / 575 | all 200 |
| private team_context, distinct | 8 | 2.0 | 3,653 / 4,753 | 187 / 1,279 | all 200 |
| private team_context, distinct | 32 | 2.3 | 13,047 / 13,977 | 614 / **9,665** | all 200 |
| private asset_only, distinct | 32 | 2.2 | 13,575 / 15,972 | 1,332 / **10,662** | all 200 |
| public 8 **plus** private team_context 4, at once | 8 + 4 | 5.6 + 1.5 | public 1,425 / 2,374; private 2,705 / 4,372 | 406 / 1,035 | all 200 |

Every request succeeded: no 5xx, no timeouts, no OOM. The process is GIL-bound, so throughput does not grow with concurrency; latency grows instead, and it spills onto every other route.

### 3.6 Memory

- **Per call** (`tracemalloc` peak of Python allocations, sequential, cold memo):

  | mode | peak, 2–4 teams | retained after the call (the result object) |
  |---|---|---|
  | market_fairness | 1.7–2.0 MB | ≤ 0.43 MB |
  | asset_only | 4.2–4.8 MB | ≤ 0.84 MB |
  | team_context | 4.2–4.8 MB | ≤ 0.84 MB |

  The snapshot memo stays bounded at LRU 2, as does the public index memo.
- **Under concurrency:**
  - public, 32-way: RSS rose by at most 15 MB;
  - private, 32-way: about 70 MB;
  - RSS returned near its baseline after each run.
- **cgroup peak:** max usage per run was 1.87–1.97 GB against the 2,560 MB cap.
  - `failcnt`: 0 in every run.
  - `oom_kill`: 0 in every run.
  
  Headroom against production's `MemoryHigh` is about 580 MB at the worst measured point.

## 4. Controls verified (config A with the real limiter, floor 200)

| control | result |
|---|---|
| **Floor on every outcome** (`floorcheck_F.json`) | 30 requests per class. Every class came back in 203–215 ms:<br>• 200, rep2 and worst4;<br>• 400 schema, invalid JSON, `too_many_assets`;<br>• 409 not owned;<br>• 413 for a 20 KB body;<br>• 415 content type.<br>No class is distinguishable by latency; minima were 203.3–204.0 ms. |
| Floor as a per-team-count table `{"2":150,"3":200,"4":200}` (`floorcheck_FT.json`) | A 2-team request was held at about 154 ms (including 400 `too_many_assets` and 409, since the team count parsed). A worst4 request was held at about 205 ms. An unparsable request (schema, invalid JSON, 413, 415) used the table maximum, about 204 ms, as designed. |
| Floor is a non-blocking sleep | Held requests consume no worker thread. Under 8-way concurrency every response exceeded the floor (489–792 ms) and each was logged (`exceeded the floor`, 14 lines). The log works as a production mis-measurement signal. |
| **Single-flight** (`flight.jsonl`) | 8 identical worst4 ledgers sent at once from 4 different perspectives produced **1 engine call** and 8 × 200, all with the same result. 16 identical rep4 ledgers also produced 1 engine call. Merging across perspectives, and no merging across different ledgers, both match spec §2.11. |
| **Limiter** (`limits_F.json`) | One client: requests 1–40 returned 200 and request 41 returned **429** with `Retry-After` (7, then 6). The 429 is also held to the floor (about 204 ms). A different client was unaffected (200). |
| Body cap | A 20 KB body gives 413 before parsing, and it is held to the floor. |
| Client abort | 20 requests aborted at 30 ms:<br>• those that disconnected before their body was read never reached the engine (11 of 20);<br>• those already computing ran to completion (the thread cannot be cancelled; single-flight runs it as its own task).<br>The server stayed healthy (`/api/health` 200 in 46 ms). |
| First request after boot | 0.4–0.8 s, from first-use module and index warm-up. It exceeds the floor once per process start, and is logged. |
| **Compute timeout** | **None** on the public or private analyze route. The only bound is nginx `proxy_read_timeout 300s` (`deploy/nginx/chaseupside-proxy.conf`). The browser client (`frontend/lib/trade-advisor-client.js`) has no timeout. It aborts only on edit, and retries once on 502/504, which is a second limiter charge. |
| **Concurrency or admission bound** | **None.** Every analyze runs on the shared AnyIO thread pool (40 tokens) with no per-route semaphore. |

## 5. Recommendations

1. **Set `responseFloorMs: 200`** in `config/trade/public_advisor.json` when the owner opens the launch gate.
   - This is one of the gate's inputs. It does not by itself open the gate: the fairness version, source permission and flag stay owner-reserved.
   - This lane did not edit the committed config. Lane C owns that file, and the spec requires the value to be a measured input.
   - Per-team-count alternative: `{"2":150,"3":200,"4":200}`.
   - Re-measure with this harness whenever the engine path changes.
2. **Add an admission bound to the public analyze route** (Lane C; a new limit, so it needs owner confirmation).
   - Measured fact: one process saturates at about 12–14 worst-case public analyses per second. Beyond that, latency and every other route degrade linearly. The rate limiter's buckets still allow bursts far above that rate:
     - global capacity 3,000 per hour, allowed as an immediate burst;
     - neighbourhood 200;
     - per-key 40.
   - Smallest consistent design:
     - an `asyncio.Semaphore` around the threadpool call, sized to a small declared prior (for example 2);
     - a bounded wait;
     - on overflow, a fixed-copy 503 `advisor_unavailable` held to the floor.
   - The number is a prior to be declared. This lane does not set it.
3. **Apply the same treatment to the private `/api/trade/analyze-multi`** (Lane A).
   - It is authenticated, but 32 concurrent private analyses pushed `/api/health` to about 10 s.
   - The minutely healthcheck could then misread a busy process as a hung one.
4. **Optional:** add one internal `market_fairness` evaluation to the startup / post-publish warm pass (Lane C or A). This removes the 0.4–0.8 s first-request cost and its floor-exceeded log line.
5. **Optional:** add a client-side timeout in `trade-advisor-client.js` (Lane D), for example about 15 s, mapped to the existing "unknown / try again" state.
6. **Owner tradeoff to state, not decide here.** During in-process scrape or rebuild contention, a 200 ms floor is exceeded on most worst-case requests (H: p99 470–623 ms). In that window, latency again carries information about the path taken.
   - The public result itself depends only on the trade, not on who asks. So what leaks is coarse (roughly team count and which path ran), not values.
   - Covering the window would need a floor of about 650 ms on every request.
   - Keep 200 ms and watch the exceedance log after launch, unless the owner prefers the longer floor.

## 6. Launch-gate items this lane covers (directive §13 and §16 item 7)

| item | status |
|---|---|
| Measure representative and worst-case 2/3/4-team requests, public and private | **Done** locally under constraints (§3) |
| Public floor from the existing method | **Measured: 200 ms recommended.** Not yet written to config; owner-reserved gate input. |
| Concurrent public requests under memory and CPU limits | **Done.** Memory OK; CPU/GIL saturation and cross-route starvation found (§3.5). |
| Single-flight, limits, body cap, floor on every outcome | **Verified** (§4) |
| Timeouts and admission bound | **Gap:** no compute timeout and no concurrency bound on either route (§4, §5.2–5.3) |

## 7. Limitations and incidental findings

- **Host noise.** The sandbox was shared with other lanes (load average up to 12.8). p99 varied between replicates: worst3 cold p99 ranged 82.6–155.9 ms. The recommendation takes the maximum over replicates to cover this.
- **Production per-core speed is unknown.**
  - This sandbox is a 2.30 GHz Xeon; the production VPS's per-core speed was not measured.
  - Running this harness against the production process is out of bounds.
  - The production check is the `public advisor response exceeded the floor` warning rate after launch.
  - If that rate goes above about 1%, re-measure on a staging copy of the box.
- **Production baseline was approximated with ballast.** The resident memory of real production caches and their fragmentation is not reproduced. The approximation used 1.80–1.84 GB local RSS against production's 1,838 MB.
- **Private `team_context` is a lower bound.** Posture and projections were unavailable locally (§3.4).
- **Incidental product/contract finding, for Lanes C and D (not a performance issue).** On the real board, 175 of 858 assets that the public asset list marks `evaluable: true` carry the engine's `quarantined_values` or `stale_values` evidence gate. Any trade containing one returns UNABLE `evaluation_unavailable`. Four of the five representative real trades here hit this:
  - `rep2_3v2`: both teams UNABLE;
  - `rep4_mixed3`: all four teams UNABLE;
  - `rep3_cycle2`: two of three teams UNABLE;
  - `rep4_cycle2`: three of four teams UNABLE.
  
  `evaluable` reflects "priced" only, so the public UI lets a user build a trade that is certain to be UNABLE. Whether `evaluable` should also reflect these gates is a contract question for Lane C, with the UX for Lane D. It may raise disclosure considerations, since quarantine status is model evidence.
- **Cleanup.** The throwaway worktree is removed. No backend processes remain, and the cgroups are deleted. The harness and raw outputs are kept in `.../tam/e4/`.
