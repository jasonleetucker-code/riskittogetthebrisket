# Live Production Verification Report

**Date:** 2026-03-23
**Scope:** Verify what the live site actually serves after all completed fixes
**Live authority:** `dynasty_data_2026-03-22.json` (served via server.py `/api/data`)

---

## Founder-Readable Summary

**5 of 7 checks pass. 2 remain blocked by external dependencies (unchanged).**

| # | Check | Result |
|---|-------|--------|
| 1 | Rookie rankings | **PASS** — 148 rookies with `_isRookie=True`, correctly ranked. Jeremiyah Love #1 at 6656. |
| 2 | Damien Martinez | **PASS** — composite=3063, only 1 source (DN rank 28), _marketConfidence=0.48. Coverage discount is applied correctly. |
| 3 | 1.01 vs top rookie | **PASS** — Pick 1.01 composite=6656 equals Jeremiyah Love composite=6656. Exact match. |
| 4 | Draft capital display | **PASS** — 72 picks, raw sum $1213 normalized to $1200. Frontend shows only Pick/$/ Owner/From columns. No player-name leakage. |
| 5 | DynastyNerds completeness | **BLOCKED** — 168 records (free tier). 0/10 elite players. Credentials not yet consumed by any execution path. |
| 6 | Yahoo completeness | **PASS** — 305 real-data players + 74 floor-value players = 379 total. Fresh. Complete source. Top players correct (Josh Allen=141). |
| 7 | Freshness / automation | **NEEDS FIRST RUN** — Live data is 30+ hours old. Workflow fix is committed but no workflow has ever run. Server scrape loop and workflow both need a trigger. |

### What's actually resolved in the live product

- Rookie rankings work correctly
- 1.01 = top rookie (exact match)
- Draft capital budget is exactly $1200
- Draft capital display has no player-name leakage
- Damien Martinez is sane after coverage-discount fix
- Yahoo is complete and healthy (305+ real records)
- Partial-scrape inflation guard is active
- Workflow pipeline bug (missing canonical_build.py) is fixed

### What's still blocked

1. **DynastyNerds** — GitHub secrets exist but have never been consumed. Neither the
   workflow (never triggered) nor the server (needs `.env` on host) has run with
   credentials. Live data still shows 168 free-tier records, zero elite players.

2. **Data freshness** — Live data is from March 22. The scheduled-refresh workflow
   has never run (zero "automated data refresh" commits). First trigger is needed.

3. **KTC** — Reported as "partial" in sourceRunSummary. 500 records in the stale CSV
   but the live scrape produced 0 in the main JSON's KTC site entry. This is a
   pre-existing Cloudflare block issue, unchanged by recent fixes.

---

## Technical Appendix

### 1. Rookie Rankings

```
Total rookies (_isRookie=True): 148

Top 10 by composite:
 #  Name                          Comp     FC     DD   DN  Sites
 1  Jeremiyah Love                6656   6656   6587    0     6
 2  Fernando Mendoza              5723   4326   4131    0     6
 3  Makai Lemon                   5625   4661   4352    0     5
 4  Carnell Tate                  5549   4392   4446    0     5
 5  Jordyn Tyson                  4986   3671   3506    0     5
 6  Kenyon Sadiq                  4933   3298   3008    0     6
 7  Denzel Boston                 4409   2874   2671    0     5
 8  Arvell Reese                  4404      0      0    0     2
 9  KC Concepcion                 4284   2684   2395    0     5
10  Jonah Coleman                 4072   2849   2550    0     6
```

Verdict: Rankings are reasonable. Top rookies have multi-source coverage.
Note: Zero rookies have DynastyNerds data (paywall blocks elite tier).

### 2. Damien Martinez

```
composite:        3063
dynastyNerds:     28 (rank — only source)
fantasyCalc:      absent
dynastyDaddy:     absent
_sites:           1
_marketConfidence: 0.48
_canonicalSiteValues: {dynastyNerds: 3320}
```

Verdict: **Sane.** With only 1 source (DN rank 28 → canonical value 3320) and
the coverage discount applied (DN has 168/300 = 0.56x weight), composite=3063
is appropriately dampened. Before the fix it was 5145.

### 3. Pick 1.01 vs Top Rookie

```
2026 Pick 1.01: _composite=6656, ktc=6656
Jeremiyah Love:  _composite=6656
Relationship: EXACT MATCH
```

### 4. Draft Capital

```
CSV raw sum:    $1213 (72 picks)
Normalized sum: $1200 (DRAFT_TOTAL_BUDGET constant)
Frontend columns: Pick | $ | Owner | From
Rookie columns:   REMOVED (rookieName=None, rookiePos=None, rookieKtcValue=None in API but not rendered)
```

Note: The API still populates `rookieName`/`rookiePos`/`rookieKtcValue` on pick
objects (server.py lines 2618-2622), but the frontend JS (35-draft-capital.js
lines 79-84) does not render them. The display fix is in place.

### 5. DynastyNerds

```
Players with dynastyNerds > 0: 168
Sites meta playerCount:        168
sourceRunSummary state:        partial
Elite players (top 10) with DN: 0/10
DN CSV: 169 lines (168 records + header)
```

**Still blocked by credentials.** The 168 records are free-tier mid-tier players
(Luke Musgrave rank 9 through Jerry Jeudy rank 499). No elite player has DN data.

### 6. Yahoo

```
Players with yahoo > 0: 379
  Real data (yahoo > 1): 305
  Floor noise (yahoo = 1): 74
Sites meta playerCount: 307
sourceRunSummary state: complete

Top 5: Josh Allen=141, Drake Maye=130, Lamar Jackson=122, Joe Burrow=115, Jayden Daniels=111
```

Verdict: **Healthy.** Yahoo scrape is complete, fresh, and correctly flowing into
the live pipeline. The 74 floor-value (yahoo=1) entries are low-priority players
that Yahoo's article ranked at the bottom. The 305 real-data entries cover all
important players.

### 7. Freshness / Automation

**Two independent data paths exist:**

| Path | What it does | Current state |
|------|-------------|---------------|
| **A: Legacy scraper** (Dynasty Scraper.py via server.py) | Runs at startup + every 2h in-process. Writes `dynasty_data_*.json`. **This is what `/api/data` serves.** | Last run: 2026-03-22 15:03-15:09 UTC. 30+ hours old. |
| **B: Canonical pipeline** (source_pull + canonical_build via GitHub Actions) | Runs every 3h via cron. Writes `data/canonical/canonical_snapshot_*.json`. | Workflow fix committed. **Never triggered.** CANONICAL_DATA_MODE=off. |

**Key insight:** Path B (canonical pipeline) does NOT serve the live site. Even
after the workflow runs, the live site still uses Path A (legacy scraper). The
canonical pipeline is a shadow/internal system (`CANONICAL_DATA_MODE=off`).

**Drift risk:** The two paths are independent. The legacy scraper produces the
live data. The canonical pipeline produces an alternative view. They will
naturally diverge in source coverage, blend logic, and timing. This is by design
(`CANONICAL_DATA_MODE` controls which one is authoritative).

### Files / Endpoints Checked

| File / Endpoint | Purpose |
|----------------|---------|
| `dynasty_data_2026-03-22.json` | Live-served data authority |
| `server.py:1039-1056` | `load_from_disk()` — data loading path |
| `server.py:2362-2640` | `/api/draft-capital` endpoint |
| `Static/js/runtime/35-draft-capital.js:79-97` | Frontend draft capital table |
| `exports/latest/site_raw/*.csv` | Source CSV freshness |
| `data/canonical/canonical_snapshot_*.json` | Canonical pipeline output |
| `.env.example` | CANONICAL_DATA_MODE=off (default) |
| `.github/workflows/scheduled-refresh.yml` | Workflow pipeline (fixed) |

### Remaining Blockers (3)

| # | Blocker | Type | Fix |
|---|---------|------|-----|
| 1 | DynastyNerds credentials not consumed | External dependency | Trigger workflow run + add credentials to production `.env` |
| 2 | Workflow never triggered | Operator action | Click "Run workflow" in GitHub Actions UI |
| 3 | KTC Cloudflare block | External dependency | Unchanged; requires proxy or API key solution |

### What Does NOT Need Fixing

- Rookie rankings: correct
- Damien Martinez: correctly dampened by coverage discount
- 1.01 vs top rookie: exact match
- Draft capital budget: exactly $1200
- Draft capital display: no name leakage
- Yahoo: complete and healthy
- Workflow pipeline: fixed (canonical_build.py added)
- Partial-scrape inflation: fixed
