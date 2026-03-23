# DynastyNerds Post-Secret Activation Verification Report

**Date:** 2026-03-23
**Scope:** Narrow proof pass — verify DN credential propagation after GitHub secret activation

---

## Founder-Readable Summary

**Status: HALF-DONE. GitHub Actions is wired. Production server is NOT yet activated.**

Secrets `DN_EMAIL` and `DN_PASS` have been added to GitHub. The workflow file
correctly references them (lines 52-53). But **the workflow has never run yet** —
zero "automated data refresh" commits exist in the repo. And the production
server has a **separate credential requirement** that is not yet satisfied.

### What's proven

| Check | Result |
|-------|--------|
| `scheduled-refresh.yml` references `secrets.DN_EMAIL` / `secrets.DN_PASS` | YES (lines 52-53) |
| Scraper reads `os.environ.get("DN_EMAIL")` at load time | YES (line 245-246) |
| Credentials never hardcoded/logged/printed | YES |
| systemd service template has `EnvironmentFile` for production `.env` | YES (added in prior commit) |
| Workflow has ever successfully run | **NO** — zero data-refresh commits |
| Production server `.env` has DN_EMAIL/DN_PASS | **UNKNOWN** — no live server accessible |
| Current DN record count | **168** (free-tier, unchanged from March 22) |
| Elite players present in DN data | **0 of 10** |
| Live data reflects credentialed scrape | **NO** — data is still free-tier |

### What this means

The secrets exist in GitHub but nothing has consumed them yet. Two things need to happen:

1. **Trigger the workflow** — either wait for the next cron run (`:42` past every 3rd hour UTC)
   or manually trigger via GitHub Actions "Run workflow" button
2. **Add DN_EMAIL/DN_PASS to production server `.env`** — the server runs its own scraper
   every 2 hours (via `schedule_loop()`) independently of GitHub Actions

### Bottom line

Adding the GitHub secrets was necessary but not sufficient. The data is still the
March 22 free-tier scrape (168 records, zero elite players). Activation requires
**one workflow run** to prove the GitHub path, and **one server restart with
credentials in `.env`** to prove the production path.

---

## Technical Appendix

### Path 1: GitHub Actions (scheduled-refresh.yml)

**Wiring:** Correct.
```yaml
# Line 52-53
env:
  DN_EMAIL: ${{ secrets.DN_EMAIL }}
  DN_PASS: ${{ secrets.DN_PASS }}
```

**Execution:** Never run. Zero "automated data refresh" commits in git history.

**Trigger:** Cron `42 */3 * * *` (every 3 hours at :42 UTC) or manual `workflow_dispatch`.

**Next action:** Trigger manually via GitHub Actions UI and monitor the "Run scraper" step
for `[DynastyNerds] Rankings not visible — logging in...` followed by a record count > 168
in the Report freshness step.

### Path 2: Production Server Runtime (server.py)

**Wiring:** `server.py` imports the scraper module at line 1284 via `importlib`. The scraper
reads `os.environ.get("DN_EMAIL")` at module load time (line 245). The systemd service
template now has `EnvironmentFile=-__APP_DIR__/.env` (line 14).

**Gap:** Unless `DN_EMAIL` and `DN_PASS` are physically written into the production `.env`
file on the server host, the server process will NOT have credentials. Adding GitHub secrets
does NOT flow to the server — these are separate environments.

**Scraper invocation in server:** `server.py:1537` runs `run_scraper(trigger="startup")` on
boot, then `schedule_loop()` (line 1501) runs it every `SCRAPE_INTERVAL_HOURS` hours.

**Next action:** SSH to production host, add to `.env`:
```
DN_EMAIL=<email>
DN_PASS=<password>
```
Then restart: `sudo systemctl restart dynasty`

### Current Data State (BEFORE — unchanged since March 22)

```
DynastyNerds records:        168  (free-tier ceiling)
DynastyNerds CSV lines:      169  (168 + header)
DN site state:               "partial"
DN sourceRunSummary:         valueCount=0, message="DynastyNerds completed (0 mapped values)"
DN sites meta playerCount:   168
```

**Elite players missing from DN:**
```
Josh Allen         dn=0   (composite=9698)
Ja'Marr Chase      dn=0   (composite=8487)
Bijan Robinson     dn=0   (composite=8475)
Jahmyr Gibbs       dn=0   (composite=8354)
Puka Nacua         dn=0   (composite=8388)
Malik Nabers       dn=0   (composite=7421)
Amon-Ra St. Brown  dn=0   (composite=7453)
CeeDee Lamb        dn=0   (composite=7180)
Breece Hall        dn=0   (composite=5334)
A.J. Brown         dn=0   (composite=4891)
```

**Damien Martinez current state:**
```
composite=3063, dynastyNerds=28, fantasyCalc=0, dynastyDaddy=0, _sites=1
_marketConfidence=0.48
```
The coverage-discount fix (from the root-cause correction pass) is correctly applied —
with only 1 source, his composite is appropriately dampened from the raw DN rank signal.

### Expected State (AFTER credentialed scrape)

| Metric | Before | Expected After |
|--------|--------|----------------|
| DN record count | 168 | ~450-550 |
| Elite players in DN | 0/10 | 10/10 |
| DN source state | "partial" | "complete" |
| DN coverage discount | 168/300=0.56x | >300 records = 1.0x (no discount) |
| Damien Martinez _sites | 1 | 1+ (may gain FC/DD if they cover him) |
| Damien Martinez composite | 3063 | Will shift based on recalculated blend |

### Files Inspected

| File | Purpose |
|------|---------|
| `.github/workflows/scheduled-refresh.yml` | Workflow secret consumption (lines 52-53) |
| `Dynasty Scraper.py` (lines 244-246, 5583-5716, 5860-5909) | Credential reading + login flow + scrape |
| `server.py` (lines 1245-1304, 1501-1509, 1534-1537) | Server-side scraper invocation |
| `deploy/systemd/dynasty.service.template` | EnvironmentFile directive |
| `.env.example` (lines 58-61) | DN credential documentation |
| `dynasty_data_2026-03-22.json` | Current production data state |
| `exports/latest/site_raw/dynastyNerds.csv` | Current DN raw export (169 lines) |
| `dynastynerds_session.json` | Expired session (2026-03-22 15:08) |

### Remaining Blockers (2 of 2)

| # | Blocker | Fix | Who |
|---|---------|-----|-----|
| 1 | **Workflow has never run** — secrets exist but haven't been consumed | Trigger manually via GitHub Actions UI "Run workflow" button, or wait for next cron window | Operator |
| 2 | **Production server `.env` likely lacks DN_EMAIL/DN_PASS** | SSH to host, add credentials to `.env`, restart service | Operator |

### Exact Next Actions

```bash
# Action 1: Trigger GitHub Actions workflow
# Go to: GitHub repo → Actions → "Scheduled Data Refresh" → "Run workflow"
# Monitor: "Run scraper" step output for DN login success message

# Action 2: After workflow succeeds, verify the data commit
git pull origin main
python3 -c "
import json
with open('dynasty_data_*.json') as f:
    data = json.load(f)
dn_count = sum(1 for p in data['players'].values() if (p.get('dynastyNerds') or 0) > 0)
print(f'DN records: {dn_count}')
"

# Action 3: Add credentials to production server
ssh production-host
echo 'DN_EMAIL=<email>' >> /path/to/app/.env
echo 'DN_PASS=<password>' >> /path/to/app/.env
sudo systemctl restart dynasty

# Action 4: Verify production server picked up credentials
curl -s https://your-domain/api/status | python3 -c "
import json, sys
data = json.load(sys.stdin)
dn = data.get('source_health', {}).get('source_counts', {}).get('dynastyNerds', 0)
print(f'DN records in live API: {dn}')
state = data.get('source_health', {}).get('source_runtime', {}).get('sources', {}).get('DynastyNerds', {})
print(f'DN state: {state.get(\"state\")}')
"

# Action 5: Run verification script (from repo)
DN_EMAIL=<email> DN_PASS=<password> python3 scripts/verify_dynastynerds_credentials.py
```

### Rollback

No code changes were made in this verification pass. If the credentialed scrape produces
bad data, remove credentials:
- GitHub: Settings → Secrets → delete DN_EMAIL and DN_PASS
- Production: Remove DN_EMAIL/DN_PASS lines from `.env`, restart service
- The scraper gracefully falls back to free-tier (168 records) when credentials are absent
