# P1-BDVM-INGEST — production closure record

**#946, merge `0155707414ff90a7d0ca8fdd36144940b57a36dc`.** Closed by Integration
2026-08-20. Merge is not deployment, so this records the deployed state
separately, and it separates what was **observed in production** from what is
**deterministically proven** and what remains **unverifiable**.

## 1 · Actual deployed SHA

`0155707414ff90a7d0ca8fdd36144940b57a36dc` — Deploy Production run
**32341590922**, `head_sha` as recorded by the workflow.

Not inferred from "main moved": the run's `Guard against skipping or reversing a
deploy` step passed, and `Run remote deploy script` executed from that head.

**Named limitation.** Unlike #937 — where `AWARDS_UNAVAILABLE_NO_GAMES` was absent
at `5feade0eb^1` and present after, so the payload itself proved the build —
**#946 introduces no publicly visible marker.** Its `cache_only` parameters are
internal to `ingest.py`, and the `/api/status` provider block
(`nfl_data_py_installed`, `nflverse_direct_available`, `active_provider`,
`cache_dir_exists`) is byte-identical before and after. The deployed-SHA claim
therefore rests on run metadata, which is weaker than payload archaeology and is
recorded as such. This is the gap #932 named: no endpoint publishes a build id.

## 2 · Deployment result

**Success**, 07:08:07 → 07:14:50 UTC. Every step green, including the two that
matter:

| step | result |
|---|---|
| Run remote deploy script | success |
| **Post-deploy smoke test** | **success** |
| **Validate live data contract** | **success** |

Post-deploy production health, read from `/api/status`:
`contract.health.ok true` · `structuralErrors 0` · `sourceHealthErrors 0` ·
`normalizationHealth.healthy true` · 22 sources at 0.72–1.97 h ·
`scrape_count 0` (consistent with a clean restart serving the shipped artifact).

`featureFlags.bdvm_engine` reports `{"enabled": true, "gateStatus": "LIVE"}`, so
the repaired request path is the one serving.

## 3 · Post-deploy BDVM interactive request behaviour — UNVERIFIABLE

**Not established, and not claimed.** `/api/bdvm/values`, `/api/bdvm/roster` and
`/api/bdvm/trades` each return **401** to an unauthenticated caller. No
credential exists in this environment, and **that gate must not be relaxed to
make verification easier** — the same wall `docs/lane4/L2_L3_VERIFICATION_PROCEDURES.md`
records for `/api/sharp/*`.

Recorded as `unverifiable_unauthenticated`: not a pass, not a failure.

What *was* observed, and what it is worth: public surfaces are responsive after
the restart — `/api/status` 0.99 / 1.42 / 0.57 s, `/league` 0.78 s (200),
`/api/public/league/metrics` 0.50 s (200). The P1's symptom was the serving
process starving `/api/data` past the Next bridge's 4 s inter-chunk timeout, so
this is **consistent with** no starvation. It is **not proof**: the starvation
was triggered by the FIRST interactive BDVM request, and nobody is known to have
made one since the restart. A quiet process is not an exonerated one.

## 4 · No heavyweight nflverse ingestion on the request path

**Deterministically proven; production half unverifiable (see §3).**

Mutation **MB1**, confirmed APPLIED with the changed line quoted:
`src/api/bdvm_api.py` `fetch_team_weeks(season, cache_only=True)` →
`cache_only=False`, i.e. the request path allowed to fetch again ⇒ RED
`test_a_cold_request_attempts_no_remote_fetch`. Restored: 31 pass.

## 5 · Stale / missing semantics remain truthful

**Deterministically proven.** The design carries three explicit states —
`AUX_AVAILABLE` / `AUX_STALE` / `AUX_MISSING` — and its own comment states that
**none of them means zero**: a missing input degrades the engine to the neutral
priors it already used when a fetch failed. A TTL-expired artifact is still
served and labelled `stale` rather than silently presented as current, and the
cache key and TTL come from `ingest` rather than a second copy, so the two cannot
drift into reporting MISSING for a present artifact.

Mutation **MB2**: `return {"state": AUX_MISSING, "ageSeconds": None}` →
`{"state": AUX_AVAILABLE, "ageSeconds": 0}` ⇒ RED
`test_g_absent_is_missing_and_missing_is_not_zero`.

## 6 · No methodology change

**Deterministically proven.** Mutation **MB3**: adding one extra key
(`payload["meta"]["mutationProbeField"]`) beyond the operational block ⇒ RED
`test_c_the_only_payload_change_is_the_operational_block`. So the *only* payload
delta is `meta.auxiliaryInputs`; no valuation, scoring or strategy output moves.

## Verdict

**CLOSED to the extent the environment permits.** Items 1, 2, 5 and 6 are
established; item 4 is proven deterministically; **item 3 is an auth wall and is
recorded as unverifiable rather than asserted.**

Integration un-paused on that basis. What would close §3 properly: an
authenticated `/api/bdvm/values` read on the deployed host, recording whether
`meta.auxiliaryInputs` reports `available` / `stale` / `missing` and that the
request returns without a remote fetch — plus, ideally, a build identifier on
`/api/status` so §1 stops depending on run metadata.

**A second, bounded attempt was made after traffic control moved #946 to
`DEPLOYED_NOT_VERIFIED`. It reached the same state, and §7 records what was
probed and why each avenue is closed — do not stop reading here.**

---

## 7 · Second, bounded verification attempt — 2026-08-20, post-deploy

Traffic control moved #946 to `DEPLOYED_NOT_VERIFIED` and asked for a bounded
production verification of the specific request-path invariant, with evidence
sufficient to distinguish three outcomes:

1. a cache / materialised read,
2. a stale last-known-good read,
3. a heavyweight remote nflverse ingestion on the request path.

**The attempt was executed and the outcome is unchanged: `unverifiable_unauthenticated`.**
Recording it here so the state is a measured finding rather than a repeated
assertion, and so a credentialed session can close it without redoing the search.

### 7.1 · What was probed

| probe | result |
|---|---|
| `GET /api/bdvm/values` | **401** (1.36 s) |
| `GET /api/bdvm/roster` | **401** (1.06 s) |
| `GET /api/bdvm/trades` | **401** (1.06 s) |
| `POST /api/bdvm/trade-eval` | **401** (0.64 s) |
| `GET /api/data` | **401** (0.95 s) |
| `GET /api/status` → `nflDataProvider` | `feature_flag true`, `active_provider nflverse_direct`, `nfl_data_py_installed false`, `nflverse_direct_available true`, `cache_dir_exists true` |
| `GET /api/status` → `featureFlags.bdvm_engine` | `{"enabled": true, "gateStatus": "LIVE"}` |

### 7.2 · The wall is structural, not incidental

`server.py::_private_api_gate` is, by its own docstring, "the ONLY auth gate in
this process", and it runs **as middleware, ahead of routing**. The allowlists it
consults are:

- `_PUBLIC_API_PREFIXES` = `/api/public/league`, `/api/league/articles`
- `_PUBLIC_API_EXACT` = health / status / uptime / metrics / leagues /
  rankings-sources / auth\* / scaffold-status / draft-capital
- `_SELF_AUTHED_API_EXACT` = signal-alerts, custom-alerts, test-session, push key

**No BDVM path appears on any of them**, and all four BDVM routes
(`server.py:6566/6719/6745/6778`) sit behind the gate. So the production BDVM
request path is not merely returning 401 today — it is **provably unreachable
without a session**. Per the standing rule, that gate must not be relaxed,
allowlisted, or otherwise turned into a pass.

### 7.3 · Why the public surfaces cannot substitute

`fetch_team_weeks` has exactly two call sites in the tree — its own definition
(`src/bdvm/schedule.py:109`) and the repaired request path
(`src/api/bdvm_api.py:102`). **Nothing public reaches it.** So no unauthenticated
request can exercise the invariant even indirectly, and a green public surface is
evidence about a different code path.

`nflDataProvider` reports `cache_dir_exists` and nothing else — no cache ages, no
per-season presence, no file count. It therefore **cannot distinguish outcome 1
from outcome 2**, let alone detect outcome 3. The post-deploy smoke probes
`/api/data`, `/api/health`, `/api/public/league`, `/api/status`; **none of them
touch BDVM**, so deploy-green is not evidence here either — which is precisely
what traffic control instructed must not be inferred.

### 7.4 · Verdict, and what would actually close it

**Not production-verified. Not failed.** No causal defect is routed to Lane 3,
because nothing failed — the invariant was not observable, which is a third state
and is recorded as one.

Deterministic evidence for the repair itself stands unchanged (§4–§6, mutations
MB1/MB2/MB3). What is missing is the *production* half only.

Any ONE of these closes it:

1. **An authenticated read** of `/api/bdvm/values` against the deployed host,
   recording `meta.auxiliaryInputs.state` (`available` / `stale` / `missing`),
   `ageSeconds`, and wall-time — a cold cache-only read returns in-process, an
   ingestion does not.
2. **On-box evidence**: `journalctl -u dynasty` across the first interactive BDVM
   request, plus nflverse cache file mtimes before and after — this is the only
   avenue that observes outcome 3 directly.
3. **Durably** — and the option worth taking, because it removes the blind spot
   rather than working around it once: add a BDVM probe to the post-deploy smoke,
   and a build identifier to `/api/status` (which would also retire §1's
   dependence on run metadata, the gap #932 named).

Options 1 and 2 need credentials this environment does not hold. Option 3 is a
`deploy.yml` change and belongs to the CI/deploy lane, not to Integration acting
unilaterally on a production surface.
