# Production Activation Runbook

> **⚠ STALE — March 2026 runbook for a retired feature.**  The
> `CANONICAL_DATA_MODE=internal_primary` activation step described
> here no longer applies; the env var was removed when the live
> `/api/data` contract became the single source of truth.  Kept
> for historical activation flow only.  See `CLAUDE.md` for the
> retirement note.

_Prepared: 2026-03-22 | Repo commit: 9dff2dc_

This document contains four operational checklists to be run on the production
server (`178.156.148.92`, user `dynasty`, app `/home/dynasty/trade-calculator`).

---

## Part 1: Activate internal_primary

**Goal**: Enable canonical pipeline evaluation on production without changing
the public experience.

### Prerequisites

- [ ] SSH access to production as `dynasty`
- [ ] Repo is up to date: `cd /home/dynasty/trade-calculator && git pull origin main`
- [ ] Canonical snapshot exists: `ls data/canonical/canonical_snapshot_*.json`
- [ ] Tests pass: `python -m pytest tests/ --ignore=tests/e2e -q`

### Activation Steps

```bash
# 1. Set the mode
export CANONICAL_DATA_MODE=internal_primary

# 2. Restart the service
sudo systemctl restart dynasty

# 3. Wait for startup (server loads data + starts initial scrape)
sleep 10
```

To make the setting persist across restarts, add it to the systemd override:

```bash
sudo systemctl edit dynasty
# Add under [Service]:
#   Environment=CANONICAL_DATA_MODE=internal_primary
# Save and exit, then:
sudo systemctl daemon-reload
sudo systemctl restart dynasty
```

### Verification

```bash
# 1. Service is running
sudo systemctl is-active dynasty
# Expected: active

# 2. Mode is correct
curl -s http://127.0.0.1:8000/api/scaffold/mode | python3 -m json.tool
# Expected: canonical_data_mode = "internal_primary"
#           canonical_loaded = true
#           internal_api_available = true
#           public_api_serves = "legacy (always, regardless of mode)"

# 3. Public API still serves legacy (CRITICAL CHECK)
curl -s http://127.0.0.1:8000/api/data | python3 -c "
import json,sys; d=json.load(sys.stdin)
print(f'contractVersion: {d.get(\"contractVersion\")}')
print(f'players: {len(d.get(\"players\",{}))}')
print(f'has canonicalComparison: {\"canonicalComparison\" in d}')
"
# Expected: contractVersion = current, players > 0
#           has canonicalComparison = True (shadow data attached, but not authoritative)

# 4. Scaffold canonical endpoint works
curl -s http://127.0.0.1:8000/api/scaffold/canonical | python3 -c "
import json,sys; d=json.load(sys.stdin)
print(f'mode: {d.get(\"mode\")}')
print(f'player_count: {d.get(\"player_count\")}')
print(f'source_count: {d.get(\"source_count\")}')
"
# Expected: mode = "internal_primary", player_count > 1000, source_count >= 14

# 5. Promotion readiness endpoint
curl -s http://127.0.0.1:8000/api/scaffold/promotion | python3 -c "
import json,sys; d=json.load(sys.stdin)
ip = d.get('internal_primary',{})
print(f'mode: {d.get(\"current_mode\")}')
print(f'internal_primary: passed={ip.get(\"passed\")} failed={ip.get(\"failed\")}')
"
# Expected: passed=9 or 10, failed=0

# 6. External health check
curl -s https://riskittogetthebrisket.org/api/health
# Expected: 200 OK

# 7. Check server logs for canonical load confirmation
sudo journalctl -u dynasty --since "5 min ago" | grep -i canonical | head -5
# Expected: "Canonical snapshot loaded..." and "Canonical data mode: internal_primary"
```

### Rollback

```bash
# Option A: Environment variable
export CANONICAL_DATA_MODE=off
sudo systemctl restart dynasty

# Option B: If using systemd override
sudo systemctl edit dynasty
# Remove the CANONICAL_DATA_MODE line
sudo systemctl daemon-reload
sudo systemctl restart dynasty
```

Verify rollback: `curl -s http://127.0.0.1:8000/api/scaffold/mode` should show
`canonical_data_mode = "off"`.

---

## Part 2: Full Production Scraper Run

**Goal**: Produce a full 11-source legacy reference on the production server
where the browser can render JavaScript-heavy pages.

### Prerequisites

- [ ] Python venv active: `source /home/dynasty/.venvs/trade-calculator/bin/activate`
- [ ] Playwright installed: `python -m playwright install chromium`
- [ ] DLF CSVs are current in repo root:
  - `dlf_superflex.csv`
  - `dlf_idp.csv`
  - `dlf_rookie_superflex.csv`
  - `dlf_rookie_idp.csv`
- [ ] `players.txt` and `rookie_must_have.txt` present in repo root
- [ ] Optional session files for paywalled sources:
  - `dynastynerds_session.json` (DynastyNerds — paywalled, often fails)
  - `flock_session.json` (Flock — session expires frequently)
  - Without these, those sources will fail gracefully

### Environment Variables (Optional)

```bash
# These are optional. The scraper has sensible defaults.
export DN_EMAIL="your-dynastynerds-email"    # Only if you have a subscription
export DN_PASS="your-dynastynerds-password"
export DS_EMAIL="your-draftsharks-email"     # Only if you have a subscription
export DS_PASS="your-draftsharks-password"
```

### Run the Scraper

```bash
cd /home/dynasty/trade-calculator

# Run the scraper directly (NOT through server.py — gives you full stdout)
python "Dynasty Scraper.py" 2>&1 | tee /tmp/scraper-run-$(date +%Y%m%d-%H%M%S).log
```

Expected runtime: 5-15 minutes depending on site responsiveness.

### Source Success/Failure Verification

After the run completes, check the Scrape Health Report in stdout. Look for:

```
SCRAPE HEALTH REPORT
  FantasyCalc             458 players
  KTC                     500+ players
  DynastyDaddy            300+ players
  DraftSharks             400+ players
  FantasyPros             300+ players
  Yahoo                   400+ players
  DynastyNerds            (often low — 10-50, paywalled)
  DLF_SF                  278 players
  DLF_IDP                 185 players
  IDPTradeCalc            300+ players
  PFF_IDP                 200+ players
```

**Success criteria**: `complete=X/13` where X >= 8 (at least 8 of 13 sources).

**Source-specific failure notes**:

| Source | Common Failure | Fix |
|--------|---------------|-----|
| KTC | Timeout, Cloudflare block | Retry. Sometimes needs 2-3 attempts. |
| DynastyNerds | Login required, session expired | Update `dynastynerds_session.json` or set `DN_EMAIL`/`DN_PASS` |
| Flock | Session expired | Re-login manually, save `flock_session.json` |
| PFF_IDP | Google search blocked, article not found | Retry. May need manual article URL. |
| FantasyPros | URL pattern changed for current month | Usually auto-discovers. May need month rollover. |
| IDPTradeCalc | Complex JS rendering, slow | Increase timeout if needed |

### Output Artifact Verification

```bash
# 1. Fresh dynasty_data file was written
ls -la dynasty_data_*.json | tail -1
# Expected: today's date, size > 2MB

# 2. Site raw CSVs were generated
ls -la exports/latest/site_raw/
# Expected: Multiple CSVs with today's date. Key ones:
#   fantasyCalc.csv, ktc.csv, dynastyDaddy.csv, draftSharks.csv,
#   fantasyPros.csv, yahoo.csv, idpTradeCalc.csv, pffIdp.csv

# 3. Count sources that produced data
python3 -c "
import json
d = json.loads(open(sorted(__import__('glob').glob('dynasty_data_*.json'))[-1]).read())
p = d['players']
from collections import Counter
sites = Counter()
for name, pd in p.items():
    if isinstance(pd, dict):
        sites[pd.get('_sites', 0)] += 1
print(f'Players: {len(p)}')
print(f'Site distribution: {dict(sorted(sites.items()))}')
site_keys = ['ktc','fantasyCalc','dynastyDaddy','fantasyPros','draftSharks','yahoo','dynastyNerds','dlfSf','idpTradeCalc']
for sk in site_keys:
    cnt = sum(1 for pd in p.values() if isinstance(pd, dict) and pd.get(sk, 0) > 0)
    if cnt > 0: print(f'  {sk}: {cnt}')
"
# Expected: Most players have 3+ sites. Per-site counts should be non-zero for 6+ sources.

# 4. Copy fresh legacy data to the data directory
cp dynasty_data_$(date +%Y-%m-%d).json data/legacy_data_$(date +%Y-%m-%d).json
echo "Legacy reference updated"
```

---

## Part 3: Post-Run Evaluation

**Goal**: Regenerate the complete evaluation checkpoint against the fresh legacy
reference. Run these commands in order.

### Pipeline Commands

```bash
cd /home/dynasty/trade-calculator

# 1. Export player position map (fast, ~1 second)
python scripts/export_player_map.py
# Expected: "[player_map] Exported N players"

# 2. Pull sources into canonical pipeline (fast, ~2 seconds)
python scripts/source_pull.py
# Expected: "sources=16 records=N" where N > 3000

# 3. Build canonical snapshot (fast, ~3 seconds)
python scripts/canonical_build.py
# Expected: "source_count=14 asset_count=1200+"

# 4. Run comparison batch (fast, ~2 seconds)
python scripts/run_comparison_batch.py
# Expected: Prints comparison summary with matched count, deltas, overlaps

# 5. Check promotion readiness (fast, ~1 second)
python scripts/check_promotion_readiness.py
# Expected: Prints SHADOW / INTERNAL_PRIMARY / PUBLIC_PRIMARY status
```

### Verification

```bash
# 1. Fresh comparison artifact exists with today's timestamp
ls -t data/comparison/comparison_batch_*.json | head -1

# 2. Check offense players-only metrics (the decision-relevant view)
python3 -c "
import json
from pathlib import Path
comp = json.loads(sorted(Path('data/comparison').glob('comparison_batch_*.json'), reverse=True)[0].read_text())
s = comp['stats']
opo = comp['universe_stats'].get('offense_players_only', {})
print('=== OFFENSE PLAYERS ONLY (decision view) ===')
print(f'  Top-50 overlap:    {opo.get(\"top_n_overlap_pct\", \"?\")}%  (need >= 80)')
print(f'  Top-100 overlap:   {opo.get(\"top100_overlap_pct\", \"?\")}%  (need >= 75)')
print(f'  Tier agreement:    {opo.get(\"tier_agreement_pct\", \"?\")}%  (need >= 65)')
print(f'  Avg delta:         {opo.get(\"avg_abs_delta\", \"?\")}     (need <= 800)')
print(f'  Matched:           {opo.get(\"count\", \"?\")}')
print()
print('=== OVERALL ===')
print(f'  Matched:           {s[\"count\"]}')
print(f'  Avg delta:         {s[\"avg_abs_delta\"]}')
print(f'  Tier agreement:    {s[\"verdict_tier_agreement_pct\"]}%')
"

# 3. Readiness check
python scripts/check_promotion_readiness.py --target public_primary
```

### Expected Outcome After Full Scraper Run

With a successful 8+ source scraper run, we expect:
- Legacy player values rise for mid-tier QBs, TEs, and RBs (the 162 "canonical 1 tier higher" cases)
- Offense tier agreement: 53.5% → likely 65%+ (need only 53 of 162 to resolve)
- Offense avg delta: 999 → likely <800 (tier-agreeing players average delta ~569)
- Offense top-50: should remain ≥80%

---

## Part 4: Public-Primary Go / No-Go Checklist

After completing Parts 1-3, use this checklist to decide whether to activate
public-primary.

### Hard Metric Requirements (from config/promotion/promotion_thresholds.json)

| # | Check | Threshold | Actual | Pass? |
|---|-------|-----------|--------|-------|
| 1 | Source count | >= 6 | ___ | |
| 2 | Offense top-50 overlap | >= 80% | ___% | |
| 3 | Offense top-100 overlap | >= 75% | ___% | |
| 4 | Offense tier agreement | >= 65% | ___% | |
| 5 | Offense avg delta | <= 800 | ___ | |
| 6 | Comparison sample size | >= 600 | ___ | |
| 7 | Multi-source blend | >= 60% | ___% | |
| 8 | IDP source count | >= 2 | ___ | |
| 9 | Source weights tuned | Yes | | |
| 10 | All tests pass | Yes | | |
| 11 | League context engine active | Yes | | |

### Data Freshness Requirements

| Check | Criteria | Actual |
|-------|----------|--------|
| Legacy scraper sources | >= 8 of 13 succeeded | ___ / 13 |
| Legacy data date | Today's date | ___ |
| Canonical snapshot date | Today's date | ___ |
| Comparison batch date | Today's date | ___ |

### Manual Approval

| Check | Status |
|-------|--------|
| Founder has reviewed founder_review_packet.md | |
| Founder approves canonical direction | |
| Founder approves public cutover | |

### Decision

**GO** if: All 11 hard metric checks pass AND data is fresh AND founder approves.

**HOLD (stay internal_primary)** if any of:
- Offense tier < 65% — canonical is still too far from legacy on tier boundaries
- Offense delta > 800 — value magnitudes still diverge too much
- Scraper got < 8 sources — legacy reference is still too incomplete
- Founder wants more evaluation time

**NO-GO (revert to off)** if:
- Offense top-50 < 60% — fundamental ranking disagreement
- Offense delta > 2000 — values are wildly divergent
- Tests fail — code quality issue

### "Close But Not Ready" Guidance

If offense tier is 60-64% or offense delta is 800-1000 after a full scraper run:
- This likely means 1-2 more source-specific issues need attention (e.g., a major
  source like KTC failed this run)
- **Re-run the scraper** rather than tuning calibration
- If metrics don't improve after 2-3 full runs with 8+ sources, then consider
  whether the tier threshold should be revised or calibration needs adjustment

---

_408 tests pass. All commands assume the production venv is active._
_Service name: `dynasty`. App path: `/home/dynasty/trade-calculator`._
