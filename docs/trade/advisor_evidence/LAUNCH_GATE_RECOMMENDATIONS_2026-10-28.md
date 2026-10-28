# Trade Advisor launch gates: owner decision package (2026-10-28)

- **Mode:** recommendations only. No flag, config value, committed launch input, fairness
  version, package model, `trade_decision.decide()`, or canonical value was changed. The flag
  `brisket_trade_advisor` stays OFF; `waiver_advisor` stays OFF.
- **Base:** `origin/main` `12b0f3209c`. **Production build tested:** `c32b1a732426e75ad6059da04ef4d5282b1fec9b`
  (from `GET /api/status` `build.commit`, 2026-10-28 13:36 UTC; data-refresh commits only
  separate it from `main`).
- **Supersedes nothing.** Extends [`BUILD_MODE_GATES_2026-10-27.md`](BUILD_MODE_GATES_2026-10-27.md),
  [`PERFORMANCE.md`](PERFORMANCE.md) and [`PRIVACY_ABUSE_VERIFICATION.md`](PRIVACY_ABUSE_VERIFICATION.md).
- **Agent-OS-Receipt:** `47a8b19fff9d06da9b1a651aab5fb92f1e16d5f6`

Evidence tags: **[measured]** observed in this lane; **[verified]** read in code or config;
**[cited]** taken from an earlier evidence document; **[inferred]** reasoned from the others.

## 0. Decisions in one table

| Gate | Owner decision needed | Recommendation | Key numbers |
|---|---|---|---|
| `responseFloorMs` | pick the value | **300 ms, single value** (250 ms only if an on-box run shows worst-case cold p99 at or below about 215 ms) | quiet-lab worst-case cold p99 215.6 ms [cited]; shared-host worst-case cold p99 230-300 ms (279-300 at 3-4 teams), max 333 ms [measured]; floor adds about 200-250 ms to a typical success |
| Source permission (OD-3a-d) | one yes/no per provider group | **No record written.** Ask in order: Signals (narrowest recorded scope), IDPTC (stale record), KTC, then the 12 other providers; `reviewBy` about 90 days | 15 providers, 27 voting sources, 0 permission records |
| Admission | confirm sizes | **Keep** `maxConcurrent` 2 and 5 s (public), 2 and 30 s (private) | saturation 12-14 worst-case analyses/s; GIL flat from 1 to 32 concurrent |
| Rate limits | confirm priors | **Keep** all six buckets; they are privacy parameters, not capacity ones | global ceiling 3,000/h = 0.83/s = 7% of saturation; flood CPU about 5% of one core |
| Ops | box operator | close **P-1**: live nginx emits none of the repo-declared security headers | see §4 |

---

## 1. The response floor

### 1.1 What it is and where it is enforced [verified]

- **Config:** `config/trade/public_advisor.json::responseFloorMs`. Today `null`. It may be a
  positive integer, or a per-team-count table `{"2": ms, "3": ms, "4": ms}`. Anything else parses
  as unset (`_parse_floor`).
- **Launch gate:** `_launch_gate_reason()` (`src/api/public_trade_advisor_api.py:541`) returns
  `response_floor_unset` while it is `null`, so every advisor route answers `503
  advisor_unavailable` regardless of the flag.
- **Enforcement:** `_apply_floor(started, team_count)` (lines 770-785) is awaited in the
  `finally` of `POST /api/public/league/trade-advisor/analyze` (line 954). `started` is taken after
  the launch gate and before the limiter charge. The handler `asyncio.sleep`s the remainder, so a
  held request occupies **no worker thread** and no admission slot. A response that already took
  longer than the floor is not shortened and logs `public advisor response exceeded the floor`.
- **Scope:** every outcome after the gate: 200, 400 schema, 409 `asset_not_owned`, 413, 415,
  429, 503 `busy` / `timeout` / `not_ready`. An unparsed request uses the table maximum so a
  malformed request is never faster than a valid one. It is **not** applied to the two GET list
  routes (`teams`, `teams/{id}/assets`) or to the pre-gate 503s.
- **Pinned by tests:** `tests/api/test_public_trade_advisor_privacy.py::test_floor_*`
  (every outcome held; nothing held before the limiter charge; table behaviour).

### 1.2 What it protects against

The design record is explicit. Spec §4.3 / §6.3 and design §3.1 ("Accepted: counterfactual
timing -> `counterfactuals=False` plus a constant response floor set from measurement") name the
threat: **response latency that encodes which code path ran**, readable by any caller, i.e. a
timing side channel (privacy channel C7). Concretely the floor is meant to hide:

1. **Early-exit class.** Validation errors, ownership refusals (409), 413 / 415 / 429 return in
   about 3 ms; a decided analysis takes 25-100 ms. Without a floor a caller separates "my ledger
   reached the engine" from "it was refused early" in one sample (AUC 0.996, [cited] E-2 §4).
2. **Counterfactual-search timing** (design A3: 0.05-29 ms spread). The search is switched off
   for the public path (`counterfactuals=False`), so this part is closed by construction, not by
   the floor.
3. **Cold snapshot / single-flight signals.** A request that rebuilds the ledger snapshot costs
   about 10-25 ms more (measured below); an identical concurrent ledger joins an in-flight
   computation and returns earlier than the originator would have [inferred from
   `AsyncSingleFlight`]. Both are cross-user signals ("the board just refreshed", "someone is
   analysing the same trade right now").
4. **Future code paths.** Any later branch (a new evidence gate, a new refusal) inherits the
   same latency without a new audit.

It is **not** a rate-control mechanism. Pacing is the limiter's job, and the floor sleeps
without holding resources, so it adds no abuse protection of its own.

### 1.3 Does the floor close the leak it targets?

**Largely yes for what it names; with three limits.**

- **Closed [cited]:** with a 50 / 65 / 110 ms illustrative table, decided-vs-4xx AUC fell from
  0.996 to 0.445 (chance), p50 of a schema error rose from 2.7 ms to 113.7 ms, and every outcome
  class landed in a 203-215 ms band at a 200 ms floor (PERFORMANCE.md §4).
- **Was never a measurable leak [cited, confirmed here]:** FAIR vs NOT FAIR AUC 0.486 and decided
  vs UNABLE 0.443 even with **no** floor, because all three outcomes run the same
  `market_fairness` path. The floor therefore guards the early-exit class (whose bodies already
  state the refusal) and future paths, not the verdict itself. Honest reading: today the
  floor is defence in depth with a small, measurable user cost.
- **Limit 1: it is a minimum.** When a request exceeds it the extra time is visible. In the
  repeated runs below about 1% of samples land at 225-330 ms **for every shape, including a
  5-leg 2-team trade**, so the tail tracks host noise and load, not the path taken. It does leak
  coarse server load to a caller. [measured]
- **Limit 2: contention windows.** The scrape (about 250 s every 2 h, [measured] from
  `/api/status`) and publish step run in the same single-GIL process. In that window (about 3.5%
  of wall-clock time) a 200 ms floor is exceeded by most worst-case requests (PERFORMANCE.md
  config H: p50 183-213 ms, p99 470-623 ms [cited]). Combined, the expected share of
  above-floor requests is about 1% at 300 ms. That is the alert threshold in §3.4.
- **Limit 3: not covered by any floor:** gzip response size by outcome (F-6, negligible),
  and slow value reconstruction through repeated queries (a rate-limit question).

### 1.4 Latency measured now [measured]

`scripts/measure_trade_analyze_multi.py --public-route --skip-route --skip-engine` on the
archived board `dynasty_export_20261028_090226.zip`, at `12b0f3209c`, in-process TestClient,
flag ON and gate opened in the process only, **no floor applied**, limits reset outside the timed
window, every non-loopback connect refused. Machine: 4 vCPU Xeon 2.8 GHz **shared with three
other workers' test runs** (load average 1.7-5.5 during the runs), Python 3.12.3, Linux. Two
replicates: cold = 250 samples, warm = 50 samples each (n per cell shown); a third earlier
150 + 150 run agrees. "Cold" clears the snapshot memo and best-ball roster cache before every
sample. Process warm-up (first request after import): 100-110 ms.

Cold, ms (replicate 1 / replicate 2):

| N | shape | legs | p50 | p95 | p99 | max |
|---|---|---|---|---|---|---|
| 2 | representative | 2-5 | 52.9 / 58.1 | 75.4 / 88.7 | 225.6 / 241.2 | 252.8 / 265.8 |
| 3 | representative | 3-8 | 69.9 / 66.1 | 102.5 / 100.7 | 248.5 / 242.8 | 265.1 / 318.3 |
| 4 | representative | 4-11 | 85.1 / 93.3 | 129.6 / 155.1 | 263.1 / 290.5 | 305.6 / 319.0 |
| 2 | worst case | 103 | 68.9 / 70.4 | 99.0 / 108.6 | 230.1 / 241.0 | 286.9 / 331.9 |
| 3 | worst case | 128 | 90.1 / 93.6 | 128.8 / 143.6 | 279.1 / 287.7 | 303.7 / 323.6 |
| 4 | worst case | 128 | 102.6 / 104.4 | 152.3 / 156.5 | **290.5 / 299.9** | 310.8 / 333.1 |

Warm, ms (n = 50, so the tail is a rough maximum): p50 40-91, p95 64-130, p99 96-272.

Reading:
- **Typical cost** is a p50 of 53-104 ms and a p95 of 75-157 ms. The typical-case gap between
  cold and warm is 10-25 ms. These are higher than the quiet-lab figures in BUILD_MODE_GATES
  (p50 40-83, worst-case cold p99 172-216 ms [cited]) because this host was shared.
- **The p99 is 2-3x the p95 in every cell and does not depend on shape or team count**: it is
  host noise. The uncontended worst-case cold p99 [cited] was 215.6 ms; the shared-host value
  is 230-241 ms at 2 teams and 279-300 ms at 3-4 teams. The spec method (p99 of the worst-case valid request, 50 ms step, maximum
  over replicates, as PERFORMANCE.md did) gives **250 ms** for the quiet host and **300 ms**
  for the shared one.
- Neither number is the production box's. Per-core speed there is unknown and the scrape shares
  its process. The final value needs the same script run on the box.

### 1.5 What the floor costs users

- A typical successful analysis completes in about 53-104 ms of server time. A floor `F` makes
  every analysis take `F`: **+200 to +250 ms at F = 300**, +150 to +200 ms at F = 250. For
  reference, the 20 production probes in §4 took 0.39-0.72 s each end to end from this host for
  a trivial 503, so the floor roughly adds one more network round trip of delay.
- The effect is one wait per Analyze click, not per keystroke (the public advisor is a submit
  flow). The two list GETs are unaffected.
- Errors cost the same wait. That is the point, but it also delays a "your trade is invalid"
  answer by about 300 ms.
- No capacity cost: the sleep holds no thread. At saturation (12 req/s) the floor keeps about
  3-4 sleeping requests open.
- The browser client deadline (15 s analyze) and the server deadline (5 s) are far above
  `F + p99`, so the floor cannot trip a timeout.

### 1.6 Alternatives

Separation figures for the early-exit class use the cited E-2 AUCs and this lane's tail
measurements; the bucketed and jitter rows are [inferred].

| Option | Early-exit separation | Tail leak | Typical cost vs no floor | Verdict |
|---|---|---|---|---|
| **No floor** | AUC 0.996 (one sample suffices) | n/a | 0 | Rejected: cheap defence is available and the gate requires a measured value |
| **Lower floor (150-200)** | closed for fast outcomes | exceeded by about 2-5% of 3- / 4-team worst cases (their p95 is 129-157 ms) and 1-3% of everything under noise: heavy trades become identifiable | +100-150 ms | Rejected: the exceedance log would fire constantly |
| **250 ms** | closed | about 1-3% above floor on the shared host; about 0% on a quiet host [cited: 0 of 1,200 samples] | +150-200 ms | Acceptable only if the box measures quiet |
| **300 ms (recommended)** | closed | about 0.3-1% above floor on the shared host (max 333 ms) | +200-250 ms | **Recommended** |
| **Per-team-count table** (`{"2":.., "3":.., "4":..}`) | closed; the count is the caller's own, so it is not a leak | same tail; the 2-team tail is as heavy as the 4-team tail here | saves 50-100 ms on 2- and 3-team trades only | Valid but low value: the 2-team p99 under noise (230-241 ms) is already above 200 |
| **Floor only on cache hits / joiners** | does not close early exits | n/a | 0 for misses | Moot: there is no analyze-result cache (privacy M11); would hide joiners only |
| **Bucketing** (round up to the next 100 ms) | partly re-opens: decided 3- / 4-team requests (p50 about 90-104 ms) fall into the 200 ms bucket, errors stay at 100 ms | bucket index reveals "heavy" | average about +60-100 ms | Rejected: re-creates a heavy-vs-light signal |
| **Random jitter** on top | does not hide a 25-100 ms mean gap against a 3 ms error path | none | +50 ms average | Rejected: noise does not substitute for a floor |
| **Rate limiting instead** | none: one sample separates the classes | none | 0 | Complementary only: limits bound probe count, not single-probe information |
| **Always run worst-case compute** | closed | none | about 2x CPU, halves saturation | Rejected: GIL-bound process |

### 1.7 Recommendation

1. **`responseFloorMs`: `300`** (single value). It is the smallest 50 ms step at or above the
   maximum-over-replicates worst-case cold p99 on a loaded host (299.9 ms), and it keeps the
   exceedance log near 1%. If the on-box run (the same script, no load, scrape idle) shows
   worst-case cold p99 at or below about 215 ms, **250** is the defensible lower value.
2. Keep it **one value**; use the table only if the owner wants 2- and 3-team answers faster
   after the box measurement shows a distinct, stable gap.
3. **Before launch:** run `scripts/measure_trade_analyze_multi.py --public-route --skip-engine
   --skip-route --cold-samples 250` on the box (idle and during a scrape window), and record
   both. **After launch:** alert if `exceeded the floor` lines exceed 1% of analyze requests.
4. State in the launch note that the floor is defence in depth: it does not hide the tail
   (load) and the verdict itself had no timing signal even without it.

---


## 2. Source permissions (OD-3): state and recommendation

### 2.1 Current state (verified on this head)

- `config/trade/public_advisor.json::approvedSourcePermissionRecord` is `null`. No record
  exists under `docs/owner/`, and none was written or inferred here.
- The validator (`src/trade/public_advisor_permission.py`) refuses anything short of: exact
  `recordType` / `schemaVersion` / `scope`, a named approver, `approvedAt <= today <= reviewBy`,
  and every voting source covered by its own or its provider's `approved` entry with no `denied`
  or `unknown`. `python scripts/advisor_permission_checklist.py` lists **15 providers /
  27 voting sources**; production `/api/status` (build below) lists the same 27 registered
  sources, 20 of them with data today.
- What is exposed publicly if the advisor launches: **no source value, rank or source name**
  (the public contract is value-free, scanned recursively by
  `tests/api/test_public_advisor_privacy_multi.py`; the 2026-10-20 audit scanned 212 bodies with
  0 floats and 0 value-like keys). What *is* exposed is a derived FAIR / NOT FAIR / UNABLE verdict
  that depends on every voting source through the one canonical blend. Parity forbids a
  public-only subset (directive §10), so each provider's answer is "confirm public derived use"
  or "do not launch".
- Reconstruction is slow but real: a patient caller could recover a public-derived estimate of a
  hidden board value to about 1.8% median error with ~20k queries (E-2 §3). The licensing question
  is therefore about *derived* use, not about displaying a source's numbers.

### 2.2 Permission and licensing evidence on file, per provider

"Evidence" means a repository record. Nothing below is a public-derived-use permission.

| Provider (voting sources) | What the repo records | Gap for public derived use |
|---|---|---|
| keepTradeCut (`ktcCrowdSfTep`, `ktcTradesSfTep`) | `F-EXT-01` COMPLETE: owner-reported authorization to scrape all KTC data (decision 2026-09-30, #1555). Explicitly "not a formula disclosure" and "does not extend to other providers" | ingestion authorization only; **OD-3b** |
| idpTradeCalculator (`idpTradeCalc`) | `C_SERIES_SCOPE_MANIFEST.md` `F-EXT-02` still says "ABSENT: no record of any kind", conflicting with a 2026-09-25 attestation; the E-2 audit called the manifest row stale and asked for a record repair | a clean record, then **OD-3c** |
| signalsFantasy (`signalsSf`; IDP boards held from voting) | `docs/sources/SIGNALS_FANTASY_INTEGRATION.md` §2: owner-attested 2026-10-01; scope "authorized now: read-only collection, normalization, private retention, analysis, and **authenticated Calculator displays**"; no raw paid data in public endpoints | the public advisor is a public readout of a blend containing Signals; **OD-3a** is a scope extension, not a re-confirmation |
| DLF (5 keys), DraftSharks (2), IDP Show (1), Flock (2) | `F-EXT-03`: 7+ keys behind credentials, "zero recorded authorization" beyond the 2026-09-25 attestation of ingestion/project use; raw boards are already committed to the public repo (pre-existing) | **OD-3d** |
| FantasyCalc, Dynasty Nerds, OTC, Fantasy Navigator, PFK, Dynasty Daddy, FantasyPros (3), Yahoo/Boone | 2026-09-25 attestation (ingestion and project use) | **OD-3d** |
| Sleeper (rosters, picks, ownership; no value) | public `/league` already shows the same rosters | none new; non-commercial status is the owner's to confirm |

### 2.3 Recommendation (owner decision, not made here)

1. **Do not write or commit a permission record on the owner's behalf.** The checklist's
   `--template` form is unanswered by design and is refused by the validator.
2. **Ask the owner one yes/no per provider group, in this order of risk:** Signals (3a, the only
   group whose recorded scope is narrower than the use), IDPTC (3c, plus repair the stale
   `F-EXT-02` row), KTC (3b), then everything else (3d).
3. **Set `reviewBy` deliberately short for the first record** (suggest 90 days). The validator
   treats the voting set as part of the record: any added source makes it uncovered by
   construction, so the record is a living gate.
4. **If any provider is "no":** the advisor does not launch with a smaller source set. The
   alternatives are an explicit owner decision to waive parity for the public path (not
   recommended: the public verdict would diverge from the private board), or to remove that
   provider from the canonical vote, which is a valuation change outside this workstream.
5. **Signals (3a)** is the one group that may be a quick confirmation: the 2026-10-01
   attestation is the owner's own and records that he holds the permission; the open question
   is only whether it extends from "authenticated Calculator displays" to a public derived
   verdict.

## 3. Admission limits and rate limits: defaults against measured capacity

All values are **declared priors pending owner confirmation**; nothing is changed here.

### 3.1 Current defaults

| Control | Value | Where |
|---|---|---|
| Admission (public analyze) | `maxConcurrent` 2, caller deadline 5 s | `config/trade/analyze_admission.json` |
| Admission (private `analyze-multi`) | `maxConcurrent` 2, caller deadline 30 s | same |
| Per key (client IPv4 / IPv6 /64) | 40 per 600 s, 400 per day | `config/trade/public_advisor.json` |
| Per neighbourhood (/24, /48) | 200 per 600 s, 1,000 per day | same |
| Per region (/16, /32) | 2,000 per day | same |
| Global ceiling | 3,000 per hour (never evicted) | same |
| Body cap / legs / teams | 16 KiB / 128 / 4 | same |
| Tracked keys | 20,000 | same |

### 3.2 Measured capacity (PERFORMANCE.md §3.3–§3.5, re-checked in §1.4 here)

- The analyze work is pure Python and GIL-bound; one process saturates at **12–14 worst-case
  public analyses per second**, about 21 per second on a representative mix, and throughput does
  not rise with concurrency (15.7 rps at 1, 11.8 at 4, 13.8 at 8, 12.4 at 16, 11.6 at 32).
- Engine CPU for the public `market_fairness` mode: p50 27 / 37 / 47 ms and p99 48 / 64 / 82 ms
  at 2 / 3 / 4 teams (128 legs). End to end through the route: p50 about 40–100 ms (§1.4).
- Memory per call: peak 1.7–2.0 MB, retained 0.43 MB or less; 32-way concurrency raised RSS by at
  most 15 MB. Memory is not a constraint.
- Production runs one uvicorn worker, so one GIL serves every route. A scrape (about 250 s every
  2 h: `/api/status` shows 248–259 s runs at 10:30 and 12:30 UTC today) and the publish step run
  in the same process, so about 3.5% of wall-clock time is a contended window (config H in
  PERFORMANCE.md: worst-case p99 470–623 ms).

### 3.3 Headroom math

Let C = 12 worst-case analyses/s (conservative end of the measured saturation range).

| Question | Arithmetic | Reading |
|---|---|---|
| Does the global ceiling protect CPU? | 3,000 per hour = 0.83 per s = **7% of C** | The ceiling sits about 14x below CPU saturation; it is not what protects the process. Admission is. |
| Worst CPU a ceiling-sized flood can burn | 3,000 x about 60 ms = 180 CPU-s per hour = **5% of one core** averaged over the hour | Acceptable. Even a full token bucket (3,000 valid worst-case requests at once) drains in 250 s of one core, with at most 2 requests in flight. |
| Daily worst case | 3,000 x 24 = 72,000 requests = 72,000 x 0.06 s = 4,320 CPU-s = **1.2 core-hours** | Under 5% of a single core's day. |
| One abusive key | 400 per day x 60 ms = **24 CPU-s per day** | Negligible. |
| One region (/16) | 2,000 per day x 60 ms = **2 CPU-minutes per day** | Negligible. |
| Do 2 slots waste anything? | GIL: throughput is flat from concurrency 1 to 32 | 2 slots hide thread-hop latency; more slots add queueing only. Keep 2. |
| Is a 5 s deadline safe? | worst measured p99: 0.29 s here, 0.62 s under a GIL hog, 3.4 s only at 32-way | 5 s is 8x the worst contended p99 with two slots; a deadline hit means a stuck worker, which is when a retryable 503 is right. |
| Cheap invalid requests | charged to the limiter before validation (correct), cost about 3 ms of CPU, held 250 ms by the floor with a sleeping task and no thread | Draining the global ceiling costs the attacker no server CPU (F-4). |
| Open connections held by the floor | 12 req/s x 0.25 s = about 3 concurrent sleeping requests at saturation | Negligible against nginx upstream keepalive. |

### 3.4 Recommendations

1. **Admission: keep `maxConcurrent` 2 and the 5 s public deadline.** Capacity does not rise
   above 1 slot, so 2 is already generous; a deadline hit should be rare and is retryable.
   Keep the private route at 2 / 30 s (private worst-case p50 200–330 ms; 32-way private runs
   pushed `/api/health` to about 10 s *before* admission existed).
2. **Per-key and neighbourhood limits: keep.** They are privacy parameters, not capacity ones: the
   +/-5% reconstruction needs about 19.7k queries, which is 49 days at 400 per day from one IPv4.
   Raising `perKeyDaily` shortens that attack linearly. A legitimate user needs far fewer than
   40 analyses in 10 minutes.
3. **Global ceiling: keep 3,000 per hour for launch, and treat it as the F-4 trade-off it is.** It
   is 14x below CPU saturation, so its only remaining job is bounding aggregate reconstruction
   speed and it doubles as a lockout lever. The measured alternative is to raise it only after
   launch if the 429 rate shows real users being locked out; the `regionDaily` cap already stops
   one address block from spending most of it. Pair it with alerting (below).
4. **Alerting is part of the recommendation.** Alert on: 429 share of analyze requests above 1%,
   `busy` 503 share above 0.5%, and `exceeded the floor` log lines above 1% of analyze requests
   (the existing mis-measurement signal).
5. **Do not conflate admission with the floor.** A `busy` refusal is held to the floor like every
   other outcome, so a flooded server does not answer faster to refused callers.


## 4. Production network checks (read-only; flag OFF)

**Method.** Plain HTTPS GETs and a few harmless POSTs with `{}` or `x` bodies from this sandbox
on 2026-10-28 13:36–13:40 UTC, about 25 requests in total, one pass, no retries, no credentials,
no cookies, no load. Every POST to the advisor was answered before the limiter charge (the flag
check runs first), so none consumed advisor rate-limit capacity. Request ids and trace ids are
redacted.

**Build tested.** `GET /api/status` -> `build.commit` =
`c32b1a732426e75ad6059da04ef4d5282b1fec9b` (`commit_source: detached_head`, process started
2026-10-28T10:30:26Z). That commit is `chore: automated data refresh 2026-10-28T09:05:43Z`; the
five commits between it and current `main` (`12b0f3209`) are automated data refreshes. It contains
`src/trade/public_advisor.py`, `src/waivers/advisor.py` and `src/api/chase_upside_mcp.py` (the
release-train content). Public `featureFlags` in the same payload:
`brisket_trade_advisor` **false**, `trade_multi_team_analysis` **false**, `waiver_advisor` **false**.

| # | Request | Status | Relevant response facts |
|---|---|---|---|
| 1 | `GET /api/public/league/trade-advisor/teams` (also with `?leagueKey=dynasty_main`) | **503** | `cache-control: no-store`; body `{"error":"advisor_unavailable","message":"The trade advisor is not available.","reason":"disabled"}` (99 bytes: fixed copy, no data, no rosters) |
| 2 | `GET .../teams/1/assets?sort=position_alpha` | **503** | same body and `no-store` |
| 3 | `POST .../analyze` with `{}` (`application/json`) | **503** | same body; the flag gate precedes validation, so no schema detail leaks |
| 4 | `POST .../analyze` with `text/plain` body `x` | **503** | same body (the gate precedes the content-type check) |
| 5 | `GET .../analyze` (wrong method) | 405 | FastAPI's default `{"detail":"Method Not Allowed"}`; no `cache-control`, no data |
| 6 | `OPTIONS .../analyze` with `Origin: https://evil.example`, `Access-Control-Request-Method: POST` | 405 | **no `Access-Control-*` headers**: cross-origin browsers cannot call it |
| 7 | `POST /api/trade/analyze-multi` anonymous | **401** | `{"error":"auth_required","message":"Sign-in required."}`, `cache-control: no-store` |
| 8 | `POST /api/trade/analyze`, `/api/trade/suggestions`, `/api/waiver/advisor` anonymous | **401** | identical fixed body |
| 9 | `GET /api/data?view=app`, `/api/gameplan`, `/api/terminal`, `/api/admin/diagnostics` anonymous | **401** | identical fixed body |
| 10 | `GET /docs` | 307 | `location: /login?next=%2Fdocs` (the Next auth gate; not the FastAPI docs) |
| 11 | `GET /openapi.json` | 404 | an HTML 404 from the Next app, not the 148 KB FastAPI route schema |
| 12 | `GET /trade` anonymous | 307 | `location: /login?next=%2Ftrade` |
| 13 | `GET /league` and `/league?tab=trade-advisor` | 200 | public Hub shell, `cache-control: private, no-cache, no-store`; the advisor tab is not enabled while the flag is off |
| 14 | `GET /api/status` | 200 | `cache-control: private, max-age=15, stale-while-revalidate=30`; public diagnostics v1 with paths/ids/env "withheld" |
| 15 | `GET http://chaseupside.com/` | 301 | `location: https://chaseupside.com/` |

**Reading.**
- While the flag is off the three advisor routes answer one fixed 503 body with `no-store` and
  nothing else; the public gate leaks no roster, no id and no value.
- All private trade, waiver and data routes refuse anonymous callers with the same fixed 401, and
  `/docs` and `/openapi.json` are not exposed through the proxy (the E-2 `:8000` exposure of
  `/docs` and `/openapi.json` is not visible from outside; direct-port reachability remains an
  ops check).
- No CORS headers on any probed route.
- **Finding P-1 (ops, MEDIUM-LOW): none of the repo-declared nginx security headers are present
  on live responses.** `deploy/nginx/chaseupside.com.conf` declares `Strict-Transport-Security`,
  `X-Content-Type-Options: nosniff`, `Content-Security-Policy: frame-ancestors 'self'`,
  `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy` and `Permissions-Policy` (server-level,
  `always`). None appeared on `/league`, `/login`, `/api/health`, `/api/status`, a static CSS
  file, the advisor 503s or the 401s. The rendered nginx therefore does not match the repo
  template (this is the "rendered nginx equals the repo templates" ops check in PRIVACY_ABUSE
  §7). It is independent of the launch flag but should be closed before a public advisor launch:
  the Hub page will carry a form that sends trade ledgers. Needs the box operator
  (`nginx -T | grep add_header`, then reload).
- **Finding P-2 (INFO):** `/api/status` is public and lists feature-flag states and the 27
  source registry keys with per-source freshness. That is the existing public-diagnostics
  contract; it means the flag-off state of the advisor is publicly observable.
- A 405 on `GET analyze` and `OPTIONS` carries FastAPI's default body, not advisor fixed copy
  and not `no-store`. It carries no data. E-2 recorded the same for an unmatched
  public-league path.
- `x-request-id`, `x-trace-id` and `traceparent` are returned on API responses (no
  `Server-Timing`).

Not done, by design: no load test, no authenticated request, no attempt to bypass the auth gate,
no probe of any non-HTTPS port. Direct reachability of `:8000` / `:3000` still needs the box
(`ss -ltnp`, external port scan from outside, firewall rules).


## 5. Four value concepts: what the advisor and War Room say, and what changed

Four different quantities surround a trade. They must not read as one number.

| Concept | Source of the number | Where it is shown | Labelled before this change? | Now |
|---|---|---|---|---|
| **Dynasty market value** (long-term) | `rankDerivedValue`; package totals raw + Value Adjustment = adjusted (`lenses.market`) | War Room "Trade value" row, package table; public advisor verdict | Row said "Trade value" with "board value" in Methodology. The public advisor already says "using our league's dynasty market" and that it does not consider roster needs, lineup or plans (`_advisor-result.jsx`) | Methodology now also states: "Trade value is long-term dynasty market value, not this season's expected points" |
| **Roster utility** (fit, capacity, forced cuts) | `roster_capacity.py`, cut ladder, lineup solver (`lenses.feasibility`) | "Does it fit your roster?" row, "How the roster fit was checked" | Yes, its own row and notes; forced cuts shown separately from value | unchanged |
| **Expected points** (rest of season) | ROS projections rescored through the league scoring card, simulated best-ball lineup (`lenses.roster`, `ppg`) | "Impact on your team" row: "Your projected lineup scores about N more/fewer points per week" | The sentence said "projected" and Methodology said "full-season projection per game", but the headline row never said it is **this season** and **not dynasty value** | Row now carries: "Expected points for the rest of this season, from projections. It is not long-term dynasty value, and it does not include playoff or title odds." (single- and multi-team War Rooms) |
| **Playoff / championship impact** | Not computed by the trade analyzer. `currentSeasonEquity` is a named UNAVAILABLE dimension (`counterfactual_not_wired`); team direction (posture) is read from the same playoff-odds family and is context, never a vote | "Not included yet" list; "Team direction (context, not a vote)" | Listed as not included, with no mention that the underlying simulator is uncalibrated | Both places and the help text now say playoff and title odds come from an experimental, uncalibrated season simulator (not validated against this league's results) |

**Why "uncalibrated".** `docs/league-intelligence/SIM_CALIBRATION_V3_RESULTS_2026-10-27.md`
records sim v1 as measured failing (its 80% intervals covered 1 of 12 week-7 team-weeks) and V3
as experimental and not activated; owner constraint IDPM-10 says championship-probability changes
may not justify premiums while the simulator is uncalibrated. No calibration-state descriptor
exists in code yet (C3 design item 1), so the label is a fixed caveat string in
`frontend/lib/trade-war-room-copy.js::SEASON_ODDS_CAVEAT`, shown only where playoff or title
odds are mentioned. Nothing in the advisor presents a playoff or title probability number.

**IDP / offense ROS caveat (Worker A's finding).** The lineup simulation scores offense and IDP
players from different ROS projection families. The V3 preregistration records the IDP snapshot
drift (as-of / preseason ROS value ratios of about 1.6 for LB, 1.28 for DL, 1.2-1.3 for DB) and
a fit-window over-prediction that is largest where R-squared is lowest (IDP). When any DL/LB/DB player appears in the
player-by-player lineup detail, the "Impact on your team" row now adds: "Defensive (IDP)
projections come from different sources than offense, and their point scale has not been
confirmed to match offense, so treat a lineup that mixes them as a rough estimate." Label only;
no math, no weights and no fixture numbers changed. Worker A's calibration research should
replace this wording with its measured statement when it lands.

**Where it is still unlabelled (not changed here).**
- Public `/league` pages that show playoff and championship odds (`ros-championship.jsx`,
  `ros-power.jsx`, `PlayoffOddsChart`, franchise pages) carry no "experimental / uncalibrated"
  note. C3 design item 4 proposes factual public wording ("the weekly score model is not yet
  validated against this league's results") but item 5 reserves the wording to the owner and
  a default-OFF flag to the coordinator. Not in the advisor path, so left alone and listed under
  owner decisions.
- The Waiver Advisor already labels this (`championship_probability_premium:
  not_used_sim_uncalibrated`, and "lineup impact is on the canonical dynasty board, not a weekly
  points projection" on every candidate).

## 6. Waiver Advisor readiness (`waiver_advisor`, #1994, default OFF)

**Verdict: built and gated correctly; NOT ready to activate. One known mis-pricing is labelled
but unfixed, and activation is owner-only.**

| # | Item | State | Evidence |
|---|---|---|---|
| 1 | Flag registered, default OFF, LIVE gate status | DONE | `src/api/feature_flags.py` (`"waiver_advisor": False`, gate `LIVE`); production `/api/status` -> `waiver_advisor.enabled: false` |
| 2 | Route is private and flag-gated first | DONE | `POST /api/waiver/advisor` returns `503 feature_disabled` first when OFF; production anonymous request -> **401** (auth precedes the flag) |
| 3 | League scoping, team required, no silent default | DONE | `_resolve_league_for_request`, `team_required` 400, `tests/api/test_waiver_advisor_endpoint.py` |
| 4 | Advice only; no claim is submitted | DONE | module docstring; no write path |
| 5 | Missing is never zero | DONE | every absent quantity is `None` + state/reason (`src/waivers/advisor.py`) |
| 6 | No championship-probability premium | DONE | `championship_probability_premium: not_used_sim_uncalibrated` |
| 7 | Lineup impact basis labelled (dynasty board, not weekly points) | DONE | labelled on every candidate |
| 8 | Forced-drop cost is reported, never applied | DONE (held) | `forced_drop_cheapest_legal` owner-held OFF; `FORCED_DROP_APPLICATION = "reported_not_applied"` |
| 9 | **List bids ignore season phase** | **OPEN BLOCKER (FAAB lane)** | `find_waiver_targets` (`src/trade/waiver.py` ~L423) builds `LeagueContext` without `current_week` / `in_season`, so the engine prices every list bid with the **offseason** option value 0.45. Today (NFL week 7, in season) the per-pair bid desk uses 0.68 (`season_option_value` reproduced locally: 0.45 vs 0.6806). The payload states both (`faab.seasonOption.listBids` vs desk, finding id `list_bid_season_phase`) and the page shows "Season option value: x0.45 on these list bids". Not fixed: `find_waiver_targets` also feeds live `/api/waiver/perfect`, so the fix changes live numbers outside the flag |
| 10 | Ceiling-only bids when no rival model ran | LABELLED | page shows a "Ceiling-only bids" banner |
| 11 | Frontend page | DONE, unlinked | `/waiver-advisor`, bridge `app/api/waiver/advisor/route.js`, bundle budget row; not in navigation |
| 12 | Tests | DONE | see §8 |
| 13 | Owner activation | **OWNER-ONLY** | enabling the flag is an owner launch decision |

**Minimal fix for blocker 9 (recommend, do not apply in this lane):** give `find_waiver_targets`
optional `current_week`, `in_season` and `playoff_week_start` parameters, default `None`/`False`
(today's behaviour), and have the two server routes (`/api/waiver/advisor`,
`/api/waiver/perfect`) pass `current_nfl_week()` and the Sleeper `playoffWeekStart` exactly as
`/api/waiver/faab-recommend` does at `server.py` ~L8342-8463. Add one regression test that a
list bid in week 7 uses the in-season factor. Because it moves live Perfect Waivers dollars, it
should ship through the FAAB lane with before/after evidence, not inside the advisor change.

**Also true but not blocking:** the advisor has no weekly-points basis (labelled), and the
competitive-status input to the engine is a fixed `"bubble"` for every team in the list path
(posture is shown beside it and changes no number).

## 7. Housekeeping dispositions

- **PR #1921** (`codex/chase-upside-private-mcp`): closed as superseded after a file-by-file
  comparison against `origin/main`; comment posted with the per-file table. Nothing in it is
  missing from main.
- **#1985 / GitHub Support:** an owner account action. Not touched.


## 8. What changed in code (display copy only) and the tests

| File | Change |
|---|---|
| `frontend/lib/trade-war-room-copy.js` | New `LINEUP_BASIS_NOTE`, `idpProjectionCaveat`, `lineupBasisNotes`, `SEASON_ODDS_CAVEAT` |
| `frontend/components/trade/TradeWarRoom.jsx` | Basis note(s) under "Impact on your team"; trade-value-is-dynasty sentence in Methodology; experimental / uncalibrated caveat on the playoff and title odds "Not included yet" line and on the Team direction note |
| `frontend/components/trade/MultiTeamWarRoom.jsx` | Same basis note(s) under "Impact on the lineup" for every team |
| `frontend/components/help/TradeVerdictHelpBody.jsx` | One sentence: playoff and title odds are experimental and uncalibrated |
| `frontend/__tests__/components/trade-war-room-concepts.test.jsx` | New: 5 tests (copy, IDP caveat present only with a defender, rendering in the War Room, caveat on the not-included line) |

No number, weight, threshold, fixture, backend payload, verdict, band or flag changed.

Tests run:
- `npx vitest run __tests__/components __tests__/trade-war-room-plain.test.js
  __tests__/trade-war-room-posture.test.js __tests__/trade-war-room-availability.test.js`:
  **209 files, 2,040 tests passed** (includes the new file and every existing War Room, multi-team,
  help and explanation test).
- `python -m pytest tests/waivers/test_advisor.py tests/api/test_waiver_advisor_endpoint.py
  tests/api/test_public_trade_advisor_privacy.py tests/api/test_public_trade_advisor_validation.py
  tests/api/test_public_trade_advisor_contract.py tests/trade/test_war_room_ui_fixtures.py`:
  **200 passed**.

## 9. UNRESOLVED and owner decisions

UNRESOLVED:
- **Production floor not measured on the box.** This lane measured locally only (shared host).
  The recommended 300 ms is the shared-host answer; the box value may be 250.
- **OD-3a-d** unresolved; no record exists. **OD-8** limiter and admission priors remain
  declared priors pending owner confirmation, as do the F-1 (hidden quarantine set) and slow
  value-refinement residuals.
- **P-1:** live nginx emits none of the repo-declared security headers. Needs the box
  operator. Direct `:8000` / `:3000` reachability, firewall and CDN checks are still ops items.
- **Waiver Advisor list-bid season phase** (0.45 offseason vs 0.68 in season) is labelled but
  unfixed; the fix touches live `/api/waiver/perfect` numbers and belongs to the FAAB lane.
- **Public `/league` playoff / championship odds pages** carry no experimental / uncalibrated
  label. C3 design item 5 reserves the wording to the owner.
- **WebKit mobile E2E** for the advisor and cross-generation differencing are still not runnable
  locally.
- **Wording to revisit:** whether the IDP caveat wording should be replaced by Worker A's
  measured ROS-scale statement when that research lands.

Owner decisions needed:
1. `responseFloorMs` (recommend 300; 250 if the box measures quiet).
2. OD-3a-d, one yes/no per provider group (order in §2.3), with a short `reviewBy`.
3. Confirm admission and limiter priors (recommend keep all).
4. Wording for the experimental / uncalibrated note on public `/league` odds pages (or decline).
5. Authorize the FAAB-lane fix for list-bid season phase before any Waiver Advisor activation.
6. Launch approval (gate 11) remains yours; both flags stay OFF.
