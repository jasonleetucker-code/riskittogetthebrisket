# ONBOARDING — Common "how do I..." tasks

Short recipes for the most common tweaks. Read `ARCHITECTURE.md`
for the big picture first.

## How do I add a league?

1. Find the Sleeper league ID:
   ```
   https://sleeper.com/leagues/<LEAGUE_ID>/
   ```

2. Add to `config/leagues/registry.json`:
   ```json
   {
     "key": "my_new_league",
     "displayName": "My League",
     "sleeperLeagueId": "1234567890",
     "scoringProfile": "superflex_tep15_ppr1",
     "idpEnabled": false,
     "active": true,
     "defaultTeamMap": {}
   }
   ```

3. Set `PRIVATE_APP_ALLOWED_USERNAMES` in the systemd env file to
   include any Sleeper handles that need to sign in and use this
   league.

4. Deploy. The league auto-appears in the switcher; Sleeper overlay
   warms on first request. If your username is in the league, the
   auto-resolver picks your team on first load (no registry edit
   needed).

## How do I add a new ranking source?

1. Copy an existing source config from `config/sources/` (e.g.,
   `ktc.json`).

2. Add a fetcher in `src/adapters/` that conforms to the
   `Adapter` base class in `src/adapters/base.py`. Emit
   `RawAssetRecord` objects.

3. Wire the new source into the scraper bridge (`src/adapters/scraper_bridge.py`).

4. Add the source key to the canonical registry in
   `src/api/data_contract.py::_RANKING_SOURCES` AND the frontend
   mirror at `frontend/lib/dynasty-data.js::RANKING_SOURCES`.
   The parity test in `tests/api/test_source_registry_parity.py`
   will fail if the two drift.

5. Set an initial weight in `config/weights/default.json`. The
   monthly refit (when dynamic weights flag is on) will tune it.

## How do I flip a feature flag?

1. Check the current defaults in `src/api/feature_flags.py::_DEFAULTS`.

2. Flip via systemd env file on the VPS:
   ```
   # /etc/systemd/system/dynasty.service.d/env.conf
   Environment="RISKIT_FEATURE_VALUE_CONFIDENCE_INTERVALS=1"
   ```

3. Reload + restart: `systemctl daemon-reload && systemctl restart dynasty`.

4. Verify on `/api/status.featureFlags` — the flag should show
   `true`.

## How do I deploy a local change?

1. Push to main:
   ```
   git add ...
   git commit -m "descriptive message"
   git push origin main
   ```

2. GitHub Actions auto-deploys. Watch with:
   ```
   gh run watch --exit-status
   ```

3. Smoke-test:
   ```
   curl -s -o /dev/null -w "%{http_code}\n" https://riskittogetthebrisket.org/api/health
   ```

## How do I add a test?

- **Backend unit:** add a file to `tests/<module>/test_*.py`.
  Follow the existing pattern — use `pytest` fixtures and
  `monkeypatch`. Run: `python3 -m pytest tests/<module>/ -q`.
- **Frontend unit:** add a `*.test.js` to `frontend/__tests__/`.
  Run: `cd frontend && npx vitest run`.
- **E2E public:** add a spec to `tests/e2e/specs/`. Public
  routes only — no session needed.
- **E2E signed-in:** use the `authedPage` fixture from
  `tests/e2e/helpers/auth-fixture.js`. Requires `E2E_TEST_MODE=1`
  + `E2E_TEST_SECRET` set on both the server and the test runner.

## How do I run the stack locally?

```
# terminal 1: backend
cd /home/dynasty/trade-calculator
uvicorn server:app --reload --port 8000

# terminal 2: frontend
cd /home/dynasty/trade-calculator/frontend
npm run dev

# open http://localhost:3000
```

## How do I debug a signal that's not firing?

1. Check `/api/status.featureFlags` — is the signal type (usage,
   injury) flag on?
2. Check the signal alert run logs in the server log. Each sweep
   emits a line `signal alert delivered for <user>: <summary>`.
3. Force a run: `curl -X POST https://.../api/signal-alerts/run -H "Authorization: Bearer $SIGNAL_ALERT_CRON_TOKEN"`.
4. Check user's `signalAlertStateByLeague` in `user_kv.sqlite` to
   see if a cooldown is blocking.

## How do I find what changed recently?

```
git log --oneline -20
```

For a specific file:
```
git log --oneline -5 <path>
```

For endpoint surface changes:
```
git log --oneline -S "@app.post\|@app.get" -- server.py
```

## How do I restore user_kv from backup?

```
/home/dynasty/trade-calculator/deploy/backup_user_kv.sh --restore-test
# Then to actually restore (⚠️ destructive):
systemctl stop dynasty
gunzip -c /var/backups/riskit/daily/user_kv.YYYY-MM-DD.sqlite.gz > /home/dynasty/trade-calculator/data/user_kv.sqlite
systemctl start dynasty
```
