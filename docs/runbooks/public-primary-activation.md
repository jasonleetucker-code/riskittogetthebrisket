# Public-Primary Activation Runbook

_Prepared: 2026-03-22 | Founder approval: GRANTED_

## Activation Summary

**What changes:** Setting `CANONICAL_DATA_MODE=primary` causes `/api/data` to serve
canonical calibrated values (from 14 multi-source pipeline) as the authoritative
player values, overlaid onto the legacy contract structure. Legacy metadata
(position, team, format-fit, scoring) is preserved.

**What doesn't change:** Legacy scraper still runs and provides the contract
skeleton, site-specific raw values, picks, and metadata. Canonical overlay
replaces only the value fields the frontend reads (`_finalAdjusted`,
`_leagueAdjusted`, `_composite`).

**Scale note:** Canonical uses a 0-7800 scale (offense) vs legacy's 0-~10000.
Rankings are 92% identical in top-50, but absolute displayed values will be
lower for top players. This is expected.

---

## Prerequisites

- [ ] SSH access to production: `ssh -i ~/.ssh/brisket_prod_clean root@178.156.148.92`
- [ ] Repo updated: `cd /home/dynasty/trade-calculator && git fetch origin claude/codebase-review-zBumx && git checkout claude/codebase-review-zBumx`
- [ ] Canonical snapshot exists: `ls data/canonical/canonical_snapshot_*.json`
- [ ] KTC CSV exists: `wc -l exports/latest/site_raw/ktc.csv` (expect 400+)
- [ ] Tests pass: `python -m pytest tests/ --ignore=tests/e2e -q`

## Activation Steps

```bash
# 1. Set the mode to primary (canonical-authoritative)
sudo systemctl edit dynasty
# Add under [Service]:
#   Environment=CANONICAL_DATA_MODE=primary
# Save and exit

# 2. Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart dynasty

# 3. Wait for startup
sleep 15
```

## Verification Checklist

```bash
# 1. Service is running
sudo systemctl is-active dynasty
# Expected: active

# 2. Mode is correct
curl -s http://127.0.0.1:8000/api/scaffold/mode | python3 -m json.tool
# Expected: canonical_data_mode = "primary"
#           canonical_loaded = true
#           public_api_serves = "canonical (primary mode...)"

# 3. Public API serves canonical values
curl -s http://127.0.0.1:8000/api/data | python3 -c "
import json,sys; d=json.load(sys.stdin)
print(f'valueAuthority: {d.get(\"valueAuthority\")}')
print(f'canonicalOverlayCount: {d.get(\"canonicalOverlayCount\")}')
print(f'players: {len(d.get(\"players\",{}))}')
# Spot check a known player
allen = d.get('players',{}).get('Josh Allen',{})
print(f'Josh Allen _finalAdjusted: {allen.get(\"_finalAdjusted\")}')
print(f'Josh Allen _valueAuthority: {allen.get(\"_valueAuthority\")}')
"
# Expected: valueAuthority = "canonical"
#           canonicalOverlayCount = ~1056
#           Josh Allen _finalAdjusted = ~7738 (canonical scale)
#           Josh Allen _valueAuthority = "canonical"

# 4. External health check
curl -s https://riskittogetthebrisket.org/api/health
# Expected: 200 OK

# 5. Check logs
sudo journalctl -u dynasty --since "5 min ago" | grep -i "PRIMARY\|canonical" | head -10
# Expected: "[PRIMARY] Canonical overlay applied: ~1056/~1163 players"
```

## Rollback

```bash
# Option A: Back to internal_primary (canonical loaded but not served publicly)
sudo systemctl edit dynasty
# Change Environment=CANONICAL_DATA_MODE=internal_primary
sudo systemctl daemon-reload
sudo systemctl restart dynasty

# Option B: Back to legacy-only (canonical completely off)
sudo systemctl edit dynasty
# Change Environment=CANONICAL_DATA_MODE=off
sudo systemctl daemon-reload
sudo systemctl restart dynasty
```

Verify rollback:
```bash
curl -s http://127.0.0.1:8000/api/scaffold/mode | python3 -c "
import json,sys; d=json.load(sys.stdin)
print(f'mode: {d[\"canonical_data_mode\"]}')
print(f'public_api_serves: {d[\"public_api_serves\"]}')
"
```

## Post-Activation Monitoring

After activation, check these within the first hour:

1. **Frontend loads correctly:** Visit the site, verify player values display
2. **Values are reasonable:** Top QBs should be in the 7000-7800 range, top RBs 6500-7800
3. **Rankings look correct:** Sort by value, verify top players are household names
4. **No 503 errors:** Check `sudo journalctl -u dynasty --since "1 hour ago" | grep -c 503`

---

_Service: `dynasty` | Host: `178.156.148.92` | App: `/home/dynasty/trade-calculator`_
