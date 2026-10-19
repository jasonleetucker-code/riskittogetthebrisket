# Signals IDP: collection health, native-value probe and family rollback

Owner directive 2026-10-19 ("Get Signals Fantasy IDP Fully Voting"; the
verbatim record is filed under `docs/owner/` by release train 13 and is not
duplicated here). Plan units **PR-H**, **PR-P** and **PR-RB**. None of them
moves a served value, lifts a vote hold or changes a default that votes.

## 1. Per-family collection truth (PR-H)

Owner: `src/sources/signals.py::collect_value_dataset`.

| Before | Now |
|---|---|
| One release-wide `asOf` was stamped as every family's upstream clock | Each family's clock is the newest vendor stamp on **its own** rows. A family without stamps has an unknown clock (`None`), never a sibling's. A family clock can only be older than the old release-wide stamp, never fresher. |
| `_last_success` written for every family key whenever the release published | Written only for boards actually verified this run (under the default rule this is unchanged: all or none). |
| A quarantine reported one dataset outcome | Every outcome carries `boardStatus` per registry key: `accepted`, `quarantined` (with `below_floor` / `row_collapse` / `empty`), `withheld_by_sibling`, `withheld_by_release`, `not_collected`; rows, floor, last good rows and the board's own clock. Also persisted in `fetch_state.json` (`lastBoardStatus`) and the collector marker (`boardStatus`). |

**Family-scoped quarantine** — flag `signals_idp_family_quarantine`, default
**OFF**. Off: one family failing its own floor or collapse check withholds the
whole IDP release (the incumbent rule). On: only that family is withheld. Its
CSV, clock and `_last_success` are untouched. Its last good rows are carried
verbatim in `latest.json`, so `latest.json` stays the exact source of every
CSV and the next collapse check still compares against the last good count.
The outcome is `partially_quarantined`. It is not a success: the run is not
`ok`, `consecutiveFailures` grows, and the CLI exits 2.

- A release-level error (game type, schema, duplicate) always quarantines the
  whole release, flag or not.
- Any internal error while planning the family-scoped path falls back to
  release-level quarantine and is stamped `familyQuarantineFallback`.
- Offense publication is identical whatever the flag (pinned by test).
- The collector unit has no `EnvironmentFile`, so on the box the registry
  default governs this flag. Turning it on is a reviewed default change.

## 2. Health mode (PR-H)

`scripts/verify_signals_health.py` (logic in `src/sources/signals_health.py`),
run by `.github/workflows/signals-health-probe.yml` with `mode: health`.

It reports the collector, renewal and alert-sweep units; the session health
class; whether the last service run was a min-interval skip
(`skippedByMinInterval`); the quarantine census by scope. Per family it
reports:

- whether the CSV equals `render_board_csv` of `latest.json`, and of that
  family's last **good** release;
- whether `_last_success` agrees with the last publication or verification
  (never newer, never present without one);
- dataset health, upstream and stamp ages;
- the freshness, health and coverage factors, through `src.sources.freshness`;
- the would-fire source-health alerts, through
  `source_health_alerts.detect_content_alerts`.

It also reports the served Signals flags and `served_private_absent_by_design`
from local `/api/status`, and `MemAvailable`.

## 3. Native league-value probe (PR-P)

`scripts/probe_signals_native.py`, plan §3.3. The decision rule (§3.4) is the
`DECISION_RULE` constant, fixed before any run; its sha256 is pinned by
`tests/scripts/test_probe_signals_native.py`. Changing it is a new
preregistration, not an edit.

| Mode | Where | What |
|---|---|---|
| `native-bundle` | CI runner, no credentials | Tier 0: at most 40 GETs and 32 MB of the public web-app bundle. Publishes operation counts, booleans and host classes. Operation names and exact hosts are never printed. |
| `native-probe` | box, deployed script, `main` only | P → 0 → P → 1b (≤ 15) → [1c (≤ 8)] → wait ≥ 120 s → P → 2 (≤ 15). At most 30 AppSync requests and 10 minutes. |

**Safety (§3.2).** `NonRecordingAppSync` never renews, never denies and never
records a failure. Any refusal is a stop and nothing else happens. The token
is read only through `signals_auth.peek_fresh_access_token`, which works only
if the token is already fresh for the whole window; it never writes and takes
no lock. Mutation and subscription documents are refused before sending.

**Preflight (P), re-checked between tiers.** The auth store must be owned by
the runner. Both Signals timers must be more than 15 minutes from firing, and
both services idle. Any failure is `BLOCKED` (exit 3) and nothing is sent.

**Tier 1c** (a league-list read that widens the authenticated footprint) runs
only with `allow_league_footprint` (owner decision 6) and an operator-authored
private `data/sources/signals/reports/native_probe_ops.json`.

**Review-only conditions.** Decision conditions 6–8 (dynasty value rather than
projection, lineage, licence) can only be supplied in
`data/sources/signals/reports/native_probe_review.json` as `PASS` / `FAIL`.
Without them the verdict is at best `INSUFFICIENT`.

## 4. Family rollback (PR-RB)

`.github/workflows/signals-idp-family-rollback.yml` with
`deploy/diagnostics/signals_idp_family_rollback.sh`, in the V1-49 style.

| family | .env key | gate | withheld |
|---|---|---|---|
| `dl` / `lb` / `db` | `RISKIT_FEATURE_SIGNALS_IDP_{DL,LB,DB}_VOTE` | `signals_idp_{dl,lb,db}_vote` (registered by PR-I) | that family's board |
| `all-idp` | `RISKIT_FEATURE_SIGNALS_IDP_SHARED_MARKET` | `signals_idp_shared_market` | all three IDP boards |
| `all-signals` | `RISKIT_FEATURE_SIGNALS_ACTIVE_SOURCE` | `signals_active_source` | offense and IDP |

- **Rollback** always writes `0`, then restarts the service and verifies the
  served board through `/api/status`: the gate reads disabled and every
  withheld key is in `served_private_absent_by_design`.
- **A rollback that does not verify is left off** (the safe direction) and
  exits 2 for a human.
- **Restore** puts back exactly the raw `.env` state captured before a given
  rollback.
- **Preflight refuses** when the gate is not registered on the deployed build.
  The per-family gates do not exist until PR-I deploys.
- `main` only, `confirm: true`, `expected_sha` required, and the
  `production-deploy` concurrency group.

## 5. Exact dispatches (none has been run; no on-box result is claimed)

All run after the PR is merged **and deployed**, from `main`, one at a time
(they share the `signals-onbox-verification` group). Read evidence from the
artifact.

1. Tier 0, off-box: `signals-health-probe.yml`, `mode: native-bundle`.
2. Health: `signals-health-probe.yml`, `mode: health`.
3. Native probe: `signals-health-probe.yml`, `mode: native-probe`,
   `allow_league_footprint: false`. Dispatch it about 5 minutes after a
   renewal run (renewal runs at `00/6:47` UTC plus 0–300 s; the collector at
   `01/6:17` UTC plus 0–600 s). A `BLOCKED` result names its reason.
4. Rollback rehearsal, only once PR-I is deployed (the gate must be
   registered): `signals-idp-family-rollback.yml`, `action: rollback`, a
   family that is not voting, `confirm: true`, `expected_sha` set to the
   deployed SHA. Then `action: restore` with that run id.
