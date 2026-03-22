# KTC Production Validation Runbook

_Prepared: 2026-03-22 | Commit: c1559d4 | Phase: KTC validation_

**Host:** `178.156.148.92` (Hetzner VPS)
**App path:** `/home/dynasty/trade-calculator`
**SSH:** `ssh -i C:\Users\jason\.ssh\brisket_prod_clean root@178.156.148.92`

---

## Pre-flight (already done in this session)

These steps were completed during the current SSH session:

- [x] SSH'd in with key-based auth
- [x] Marked `/home/dynasty/trade-calculator` as safe directory
- [x] Fetched and checked out `claude/codebase-review-zBumx` at `c1559d4`
- [x] Created venv at `/home/dynasty/venv` with playwright + chromium
- [x] Ran `peek_ktc.py` — confirmed KTC serves 526 players via `playersArray`

---

## Phase A — Validate KTC Health

```bash
cd /home/dynasty/trade-calculator
source /home/dynasty/venv/bin/activate

# Quick connectivity test
python3 scripts/check_ktc_health.py
# Expected: "OK: KTC responded with status 200"

# Full extraction test
python3 scripts/check_ktc_health.py --full
# Expected: "playersArray: 526 players"
#           "OK: KTC data extraction confirmed (526 players)"
# Exit code 0 = PASS
echo "Exit code: $?"
```

**Definition of done:** Exit code 0, player count > 400.

**If it fails:** Capture the exact output and paste it back. Possible failure modes:
- `BLOCKER: cloudflare_challenge` — retry in 2 minutes
- `BLOCKER: timeout` — check DNS/firewall
- `playersArray not found` + `__NEXT_DATA__ not found` — KTC changed format again

---

## Phase B — Full Production Scrape

Only proceed if Phase A exits 0.

```bash
cd /home/dynasty/trade-calculator
source /home/dynasty/venv/bin/activate

# Install remaining scraper dependencies
pip install requests beautifulsoup4 openpyxl aiohttp 2>/dev/null

# Run the full scraper (captures log)
python3 "Dynasty Scraper.py" 2>&1 | tee /tmp/scraper-run-$(date +%Y%m%d-%H%M%S).log
```

Expected runtime: 5-15 minutes.

### Verify KTC specifically

```bash
# 1. KTC freshness line in scraper output
grep -i "KTC" /tmp/scraper-run-*.log | tail -10
# Look for: "[KTC Status] FRESH — N players scraped"
# NOT:      "[KTC Status] BLOCKED"

# 2. KTC CSV exists with meaningful rows
wc -l exports/latest/site_raw/ktc.csv 2>/dev/null
# Expected: 400+ lines

# 3. Source success count
grep "complete=" /tmp/scraper-run-*.log | tail -1
# Expected: complete=10/13 or better (KTC must be in the success list)
```

### Verify overall scrape

```bash
# Fresh dynasty_data file
ls -la dynasty_data_*.json | tail -1
# Expected: today's date, size > 2MB

# Source distribution
python3 -c "
import json, glob
d = json.loads(open(sorted(glob.glob('dynasty_data_*.json'))[-1]).read())
p = d['players']
site_keys = ['ktc','fantasyCalc','dynastyDaddy','fantasyPros','draftSharks','yahoo','dynastyNerds','dlfSf','idpTradeCalc']
print(f'Total players: {len(p)}')
for sk in site_keys:
    cnt = sum(1 for pd in p.values() if isinstance(pd, dict) and pd.get(sk, 0) > 0)
    if cnt > 0: print(f'  {sk}: {cnt}')
"
# Expected: ktc: 400+ players
```

**Definition of done:** KTC CSV has 400+ rows, scraper reports KTC FRESH, `complete >= 8/13`.

**Distinguish:**
- **Truly fresh KTC** = `[KTC Status] FRESH` + ktc.csv has 400+ rows today
- **Fallback/archive KTC** = `[KTC Status] BLOCKED` but old ktc.csv exists
- **Failed KTC** = `[KTC Status] BLOCKED` + no ktc.csv or 0 rows

---

## Phase C — Re-run Evaluation Pipeline

Only proceed if Phase B confirms KTC is truly fresh.

```bash
cd /home/dynasty/trade-calculator
source /home/dynasty/venv/bin/activate

# 1. Pull sources into canonical pipeline
python3 scripts/source_pull.py

# 2. Build canonical snapshot
python3 scripts/canonical_build.py

# 3. Run comparison batch
python3 scripts/run_comparison_batch.py

# 4. Check promotion readiness
python3 scripts/check_promotion_readiness.py
python3 scripts/check_promotion_readiness.py --target public_primary
```

### Capture the KTC impact

```bash
# Offense players-only metrics (the decision-relevant view)
python3 -c "
import json
from pathlib import Path
comp = json.loads(sorted(Path('data/comparison').glob('comparison_batch_*.json'), reverse=True)[0].read_text())
opo = comp['universe_stats'].get('offense_players_only', {})
print('=== OFFENSE PLAYERS ONLY (decision view) ===')
print(f'  Top-50 overlap:    {opo.get(\"top_n_overlap_pct\", \"?\")}%  (need >= 80)')
print(f'  Top-100 overlap:   {opo.get(\"top100_overlap_pct\", \"?\")}%  (need >= 75)')
print(f'  Tier agreement:    {opo.get(\"tier_agreement_pct\", \"?\")}%  (need >= 65)')
print(f'  Avg delta:         {opo.get(\"avg_abs_delta\", \"?\")}     (need <= 800)')
print(f'  Matched:           {opo.get(\"count\", \"?\")}')
print()
s = comp['stats']
print('=== OVERALL ===')
print(f'  Multi-source blend: {s[\"multi_source_count\"]}/{s[\"count\"]} = {round(s[\"multi_source_count\"]/s[\"count\"]*100,1)}%  (need >= 60)')
print(f'  Avg delta:         {s[\"avg_abs_delta\"]}')
print(f'  Tier agreement:    {s[\"verdict_tier_agreement_pct\"]}%')
"
```

### Before/After comparison table

Fill in after running:

| Metric | Before (no KTC) | After (with KTC) | Threshold | Pass? |
|--------|-----------------|-------------------|-----------|-------|
| Offense top-50 | 92% | ___% | >= 80% | |
| Offense top-100 | 92% | ___% | >= 75% | |
| Offense tier | 50.1% | ___% | >= 65% | |
| Offense delta | 1006 | ___ | <= 800 | |
| Multi-source blend | 57% | ___% | >= 60% | |
| Source count | 13 | ___ | >= 6 | |
| Matched players | 1051 | ___ | >= 600 | |

**Definition of done:** All 7 metrics filled in, clear pass/fail for each.

---

## Phase D — Decision Framework

After filling in the table above:

### If all metrics PASS:
- KTC is confirmed as a reliable core production source
- Multi-source blend should jump from 57% to ~65%+ (KTC adds source #12 for ~500 players)
- Tier and delta should improve as KTC anchors the market-standard reference
- **Next steps:**
  1. Activate `internal_primary` on production (`export CANONICAL_DATA_MODE=internal_primary`)
  2. Monitor for 48h with KTC included
  3. Begin founder review for `public_primary` approval

### If tier and delta STILL fail with KTC:
- KTC is fresh but not sufficient alone
- Check which players still disagree: canonical 1-tier-higher cases
- Consider whether calibration adjustment is needed
- **Next steps:**
  1. Stay at `internal_primary`
  2. Analyze the specific disagreement players
  3. Test calibration adjustments

### If KTC fails on production:
- Document the failure mode
- Check if Cloudflare is blocking headless Chrome
- Try with `--full` flag for detailed diagnosis
- **Next steps:**
  1. Try updating the user agent string
  2. Consider using a residential proxy for KTC specifically
  3. Test at different times of day (Cloudflare may rate-limit)

---

## What Was Actually Executed vs. Prepared

| Action | Status |
|--------|--------|
| KTC health check code updated for `playersArray` | **EXECUTED** — committed as c1559d4 |
| Scraper DOM strategy updated for `playersArray` | **EXECUTED** — committed as c1559d4 |
| Scraper page-source strategy updated for `playersArray` | **EXECUTED** — committed as c1559d4 |
| Production peek test (526 players confirmed) | **EXECUTED** by operator on VPS |
| `check_ktc_health.py --full` on production | **PREPARED** — not yet run with updated code |
| Full scraper run on production | **PREPARED** — not yet run |
| Evaluation pipeline re-run | **PREPARED** — not yet run |
| Metrics comparison | **PREPARED** — template ready |

---

_This runbook is complete and self-contained. All commands are copy-pasteable._
_Repo: claude/codebase-review-zBumx @ c1559d4_
