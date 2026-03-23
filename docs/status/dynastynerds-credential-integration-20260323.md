# DynastyNerds Credential Integration & Verification Report

**Date:** 2026-03-23
**Scope:** Narrow credential wiring + verification pass for DynastyNerds paywall unblock

---

## Founder-Readable Summary

DynastyNerds is paywalled. Without credentials, the scraper gets **168 records** —
all mid-tier players (Luke Musgrave rank 9 through Jerry Jeudy rank 499). Every
elite player (Josh Allen, Ja'Marr Chase, Bijan Robinson, etc.) is **missing**.

The credential wiring was **95% complete**. Two gaps were found and fixed:

1. **Systemd service template** — production server process had no way to receive
   `DN_EMAIL`/`DN_PASS` from the host environment. Fixed by adding `EnvironmentFile`
   directive pointing to the app's `.env` file.

2. **`.env.example`** — `DN_EMAIL`/`DN_PASS` were not documented. Added with
   clear descriptions.

Everything else was already correct:
- Scraper reads `DN_EMAIL`/`DN_PASS` from env vars (line 245-246)
- Login flow handles WordPress auth, session persistence, cookie verification
- GitHub Actions workflow passes `secrets.DN_EMAIL`/`secrets.DN_PASS` to scraper step
- Credentials are never hardcoded, logged, or written to output files
- `/api/status` correctly reports DynastyNerds as "partial" with current data

### What's needed to activate

1. Add `DN_EMAIL` and `DN_PASS` as GitHub repository secrets
2. On the production server, add `DN_EMAIL` and `DN_PASS` to `/path/to/app/.env`
3. Run the verification script: `python3 scripts/verify_dynastynerds_credentials.py`
4. Restart the server (or wait for next scheduled scrape)

### Expected impact

| Metric | Before (free tier) | After (credentialed) |
|--------|-------------------|---------------------|
| DynastyNerds records | 168 | ~450-550 |
| Elite players (top 20) | 0 | ~20 |
| Source weight in blend | 0.8 (standard) | 0.8 (standard) |
| Coverage discount applied | Yes (168/300 = 0.56x) | No (>300 records) |
| Composite accuracy | Missing DN signal for all elite players | Full DN signal |

---

## Technical Appendix

### Credential Path Trace

| Path | Component | Status |
|------|-----------|--------|
| `Dynasty Scraper.py:245-246` | `DYNASTYNERDS_EMAIL = os.environ.get("DN_EMAIL", "")` | Correct |
| `Dynasty Scraper.py:5583-5716` | `_dynastynerds_login()` — WordPress login flow | Correct |
| `Dynasty Scraper.py:5870-5881` | Credential gate in `scrape_dynastynerds()` | Correct |
| `.github/workflows/scheduled-refresh.yml:52-53` | `DN_EMAIL: ${{ secrets.DN_EMAIL }}` | Correct |
| `server.py:1284` | Imports scraper module (reads env vars at import time) | Correct |
| `deploy/systemd/dynasty.service.template` | **FIXED**: Added `EnvironmentFile=-__APP_DIR__/.env` | Was missing |
| `.env.example` | **FIXED**: Added `DN_EMAIL`/`DN_PASS` documentation | Was missing |

### Credential Safety Audit

| Check | Result |
|-------|--------|
| Credentials hardcoded in source files | NO — only `os.environ.get()` |
| Credentials printed/logged | NO — only "Login successful/failed" messages |
| Credentials in git history | NO — `.env` is gitignored pattern |
| Credentials in output JSON | NO — player entries have rank values only |
| Credentials in session file | NO — `dynastynerds_session.json` stores cookies, not credentials |
| Credentials in CSV exports | NO |

### Source Health Reporting

`/api/status` correctly surfaces DynastyNerds state:

```json
{
  "source_counts": { "dynastyNerds": 168 },
  "source_runtime": {
    "partial_sources": ["DynastyNerds"],
    "sources": {
      "DynastyNerds": {
        "state": "partial",
        "valueCount": 0,
        "message": "DynastyNerds completed (0 mapped values)"
      }
    }
  }
}
```

**Note:** There is a pre-existing reporting discrepancy. `valueCount: 0` in
`sourceRunSummary` but 168 player entries DO have `dynastyNerds` values. This
is because the JSON builder (line 8965-8976) reads from `FULL_DATA` with its
own name resolution, while `valueCount` is computed from the parallel runner's
return dict. This is cosmetic and does not affect data quality.

### Before State (production 2026-03-22, free tier)

```
Total players: 1163
DynastyNerds records: 168
DynastyNerds elite players: 0

Name                     composite  dynastyNerds  fantasyCalc  dynastyDaddy  _sites
Josh Allen                    9698             0        10492         10200       6
Ja'Marr Chase                 8487             0         9582         10113       5
Bijan Robinson                8475             0        10066         10200       6
Damien Martinez               3063            28            0             0       1
Amon-Ra St. Brown             7453             0         7216          7531       5
Garrett Wilson                5571             0         4295          4441       5
Travis Kelce                  3202            78         1498          1367       7
Saquon Barkley                5182             0         3628          3638       6
Jahmyr Gibbs                  8354             0         9491          9916       6
Breece Hall                   5334             0         3690          3998       6
```

### Expected After State (with valid credentials)

- DynastyNerds records: ~450-550
- All elite players present with accurate consensus ranks
- Damien Martinez: DN rank ~28 stays, but composite recalculated with full
  coverage (no more 0.56x coverage discount since records > 300)
- `_sites` count increases by 1 for all players now covered by DN
- Source health shows "complete" instead of "partial"

### Files Changed

| File | Change |
|------|--------|
| `deploy/systemd/dynasty.service.template` | Added `EnvironmentFile=-__APP_DIR__/.env` |
| `.env.example` | Added `DN_EMAIL`/`DN_PASS` documentation |
| `scripts/verify_dynastynerds_credentials.py` | **NEW** — verification script |
| `docs/status/dynastynerds-credential-integration-20260323.md` | **NEW** — this report |

### Secrets/Variables Required

| Name | Where | Description |
|------|-------|-------------|
| `DN_EMAIL` | GitHub repo secret + production `.env` | DynastyNerds account email |
| `DN_PASS` | GitHub repo secret + production `.env` | DynastyNerds account password |

### Validation Commands

```bash
# 1. Verify credential wiring (no actual scrape)
python3 -c "
import os, sys, importlib.util
os.environ['DN_EMAIL'] = 'test@test.com'
os.environ['DN_PASS'] = 'test'
spec = importlib.util.spec_from_file_location('DS', 'Dynasty Scraper.py')
s = importlib.util.module_from_spec(spec)
sys.modules['DS'] = s
spec.loader.exec_module(s)
assert s.DYNASTYNERDS_EMAIL == 'test@test.com'
print('Credential wiring OK')
"

# 2. Run full credential verification (requires real credentials)
DN_EMAIL=your@email.com DN_PASS=yourpassword python3 scripts/verify_dynastynerds_credentials.py

# 3. Check /api/status after server restart
curl -s http://localhost:8000/api/status | python3 -m json.tool | grep -A5 dynastyNerds
```

### Rollback Instructions

```bash
# Revert service template change:
git checkout HEAD -- deploy/systemd/dynasty.service.template

# Revert .env.example change:
git checkout HEAD -- .env.example

# Remove verification script:
rm scripts/verify_dynastynerds_credentials.py

# Remove this report:
rm docs/status/dynastynerds-credential-integration-20260323.md
```

### Known Limitations

1. **Cannot verify live scrape without credentials.** The `DN_EMAIL`/`DN_PASS`
   env vars are not set in the current development environment. The verification
   script is ready to run when credentials are provided.

2. **Session file expired.** The `dynastynerds_session.json` expired on
   2026-03-22 15:08. A fresh login with valid credentials will create a new
   session automatically.

3. **sourceRunSummary valueCount discrepancy.** The parallel runner reports
   `valueCount: 0` even though 168 values appear in the final output. This is a
   pre-existing reporting issue in the parallel runner's count logic vs the JSON
   builder's FULL_DATA-based population.
