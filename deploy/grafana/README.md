# Grafana dashboards

## `public-league-dashboard.json`

One-panel-per-row dashboard that polls
`https://riskittogetthebrisket.org/api/public/league/metrics` every 30s
and surfaces the key snapshot-cache signals:

| Panel                          | Target                                   |
|--------------------------------|------------------------------------------|
| Cache hit ratio                | ≥ 0.85 (green)                           |
| Last rebuild duration          | < 2 s (green), < 5 s (orange)            |
| Contract payload size          | < 2.5 MB (green)                         |
| Totals (rebuilds / hits / …)   | rebuild_failures ≥ 1 turns red           |
| Snapshot freshness             | < 20 min since last rebuild              |

### Import

1. Grafana → **Dashboards → Import**
2. Upload `public-league-dashboard.json`
3. Pick any Infinity-plugin-compatible datasource (the
   [yesoreyeram-infinity](https://grafana.com/grafana/plugins/yesoreyeram-infinity-datasource/)
   plugin polls arbitrary JSON endpoints). Install via:

   ```bash
   grafana-cli plugins install yesoreyeram-infinity-datasource
   ```

4. The `metrics_url` template variable defaults to the production
   URL — override it via Dashboard settings → Variables if pointing
   at a staging instance.

### What "regressed" looks like

- `cache_hit_ratio` dropping below 0.5 for >10 minutes → warmup cron
  probably broken. Check `.github/workflows/public-league-warmup.yml`
  runs.
- `last_rebuild_seconds` > 5 s → Sleeper slow or pool exhausted. Check
  `_POOL_SIZE` in `src/public_league/sleeper_client.py` vs
  `_FETCH_CONCURRENCY` in `snapshot.py`.
- `last_contract_bytes` growing past 5 MB → someone added a big
  payload block; audit the latest section builder change.
- `rebuild_failures` counter moving → check server logs for the
  `public_league_event=rebuild_failed` line right before the failure.
