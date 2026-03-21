# Runtime Promotion Release Gate

## Objective
Prevent bad scrape/formula runs from being promoted into live runtime payloads.

## Live Promotion Path
Authoritative path is:

1. `Dynasty Scraper.py::run()` produces candidate payload.
2. `server.py::run_scraper()` receives candidate.
3. `server.py::_attempt_runtime_promotion()` runs promotion gates.
4. If gates pass: promote to `/api/data` buffers and persist last-known-good snapshot.
5. If gates fail: keep serving previous live payload, write failure report, mark scrape failed.

## Validation Gates
Implemented in `src/api/promotion_gate.py` and executed by `server.py`.

- `requiredSourcePresence`
- `sourceFreshness`
- `coverageThresholds`
- `mergeIntegrity`
- `regressionTests`
- `formulaSanity`
- `contractValidation`
- `trustPolicy`

Critical sources defaulted for strict protection:
- DynastyNerds
- IDPTradeCalc

Yahoo remains monitored (freshness/coverage/disagreement observability + auto-handling recommendations)
but is non-blocking by default to avoid dead-runtime promotion lockouts when Yahoo extraction times out.

## Trust Policy Semantics
`trustPolicy` converts source-health anomalies from advisory-only warnings into explicit publish decisions:

- `block`
- `allow_with_degrade`
- `allow_with_warning`
- `allow`

Policy now explicitly classifies:

- stale/missing/partial critical sources (blocking unless waived)
- partial required-source degradation (allow with downweight guidance)
- coverage collapse by source + position (critical severe collapse blocks; required non-critical collapse degrades)
- severe disagreement spikes (deterministic block/degrade thresholds)
- overnight swing anomaly bursts (deterministic block/degrade thresholds)

The report includes machine-readable issue buckets:

- `hardFailIssues`
- `degradeIssues`
- `warnOnlyIssues`
- `waivedHardFailIssues`
- `requiredWaiversToUnblock`

This appears in both `gates.trustPolicy` and `operatorReport.policy` for operator visibility.

## Waiver Behavior
Blocking policy issues require an explicit waiver entry to allow publish.
Waivers are configured with `PROMOTION_POLICY_WAIVERS_JSON` as JSON objects:

```json
[
  {
    "ruleId": "critical_source_stale",
    "scope": "source:yahoo",
    "reason": "INC-1234 vendor outage acknowledged",
    "ticket": "OPS-42",
    "expiresAt": "2026-03-21T12:00:00Z"
  }
]
```

`scope` supports exact scope values from issue rows (for example `source:yahoo`) plus `global`/`*` for rule-wide waivers.
Expired or malformed waivers are ignored and reported under `waivers.invalid`.

## Failure Behavior
On gate failure:

- candidate payload is **not** promoted
- current live payload remains active
- scrape run is marked failed with explicit promotion-gate summary
- detailed report is written to:
  - `data/validation/promotion_gate_<timestamp>_fail.json`
  - `data/validation/promotion_gate_latest.json`

API visibility:
- `/api/status` includes promotion gate summary/state
- `/api/validation/promotion-gate` returns latest detailed report

## Last-Known-Good Behavior
On successful promotion:

- candidate is persisted as last-known-good:
  - `data/runtime_last_good.json`
  - `data/runtime_last_good_meta.json`

On startup:

- server prefers `data/runtime_last_good.json`
- if startup cache fails promotion, runtime falls back to last-known-good when available

## League Route Deploy Readiness (Runtime Shell Gate)

Data promotion gates protect payload quality, but League route deploy safety is a separate runtime concern:

- `deploy/verify-deploy.sh` calls `GET /api/runtime/route-authority`
- it validates `deployReadiness.leagueShell`
- default behavior (`STRICT_LEAGUE_SHELL_READINESS=true`) fails deploy verification when:
  - `Static/league/index.html` is missing
  - `Static/league/league.css` is missing
  - `Static/league/league.js` is missing
- strict deploy verify also fails when those League shell assets are present locally but not tracked in git.
- CI deploy validation enforces the same tracked-artifact requirement before remote deploy.

Runtime still has a controlled inline fallback (`public-league-inline-fallback-shell`) to avoid raw 500s,
but deploy verification blocks shipping that degraded state by default.

## Key Environment Controls
- `PROMOTION_REQUIRED_SOURCES`
- `PROMOTION_CRITICAL_SOURCES`
- `PROMOTION_SOURCE_MIN_COUNTS_JSON`
- `PROMOTION_MAX_PAYLOAD_AGE_HOURS`
- `PROMOTION_MAX_SOURCE_AGE_HOURS`
- `PROMOTION_MIN_PLAYER_COUNT`
- `PROMOTION_MIN_ACTIVE_SOURCES`
- `PROMOTION_MIN_CANONICAL_SITE_MAP_COVERAGE`
- `PROMOTION_MAX_UNMATCHED_RATE`
- `PROMOTION_MAX_DUPLICATE_CANONICAL_MATCHES`
- `PROMOTION_MAX_CONFLICTING_POSITIONS`
- `PROMOTION_MAX_CONFLICTING_SOURCE_IDENTITIES`
- `PROMOTION_RUN_REGRESSION_TESTS`
- `PROMOTION_REGRESSION_COMMAND`
- `PROMOTION_REGRESSION_TIMEOUT_SEC`
- `PROMOTION_MIN_TOP_VALUE_BY_POSITION_JSON`
- `PROMOTION_POLICY_DISAGREEMENT_DEGRADE_PLAYER_COUNT`
- `PROMOTION_POLICY_DISAGREEMENT_BLOCK_PLAYER_COUNT`
- `PROMOTION_POLICY_DISAGREEMENT_DEGRADE_SOURCE_SPIKE_COUNT`
- `PROMOTION_POLICY_DISAGREEMENT_BLOCK_CRITICAL_SOURCE_SPIKE_COUNT`
- `PROMOTION_POLICY_OVERNIGHT_SWING_DEGRADE_COUNT`
- `PROMOTION_POLICY_OVERNIGHT_SWING_BLOCK_COUNT`
- `PROMOTION_POLICY_CRITICAL_COVERAGE_COLLAPSE_BLOCK_DROP_PCT`
- `PROMOTION_POLICY_CRITICAL_COVERAGE_COLLAPSE_BLOCK_RATIO`
- `PROMOTION_POLICY_WAIVERS_JSON`

## Regression Runner Portability
- Default regression command now uses the active Python interpreter (`sys.executable`) instead of hardcoded `python`.
- This preserves virtualenv dependency visibility on runtime hosts and avoids false gate failures from interpreter mismatch.

## Semantic Ratchet Baseline
- `scripts/semantic_ratchet_gate.py` blocks deploy validation on regressions above the accepted semantic baseline.
- Current `lowConfidenceActionableCount` threshold is pinned to `420`, matching the checked-in `data/validation/api_contract_validation_latest.json` snapshot generated from the 2026-03-20 payload.
- Lower that threshold only after reducing actionable low-confidence rows and refreshing the accepted baseline.
