# Canonical Pipeline — Source Integration Matrix

_Generated: 2026-03-21_
_Context: Execution map for integrating legacy scraper sources into the canonical pipeline._

---

## 1. Source-by-Source Matrix

### Legend

| Column | Meaning |
|--------|---------|
| **Legacy Scraper** | Does `Dynasty Scraper.py` fetch this source? |
| **Canonical Adapter** | Does `src/adapters/` have a working adapter? |
| **Adapter Status** | `functional` / `stub` / `placeholder` / `absent` |
| **Identity Handling** | Can `src/identity/matcher.py` resolve players from this source? |
| **Blending Ready** | Can `src/canonical/transform.py` consume it today? |
| **Safest Input Path** | Lowest-risk way to get data into the canonical pipeline |
| **Missing Tests** | What test coverage gaps exist for this source |
| **Priority** | `P1` (next) / `P2` (soon) / `P3` (later) / `P4` (defer) |

---

### Offense — Veteran Universe

| Source | Legacy Scraper | Canonical Adapter | Adapter Status | Identity Handling | Blending Ready | Safest Input Path | Missing Tests | Priority |
|--------|---------------|-------------------|----------------|-------------------|----------------|-------------------|---------------|----------|
| **DLF Superflex** | Yes — local CSV | `dlf_csv_adapter.py` | **Functional** | Yes — name+team+pos | Yes — rank_raw signal | `dlf_superflex.csv` seed | Covered (Phase A) | **Done** |
| **KTC** | Yes — API intercept + DOM | `ktc_stub_adapter.py` | **Stub** (seed CSV only) | Yes — same matcher | Yes if enabled | Scraper export `exports/latest/site_raw/ktc.csv` | No adapter tests | **P1** |
| **FantasyCalc** | Yes — JSON API | None | **Absent** | Yes — same matcher | No — needs adapter | Scraper export `exports/latest/site_raw/fantasyCalc.csv` (453 rows, `name,value` format) | N/A | **P1** |
| **DynastyDaddy** | Yes — API intercept | None | **Absent** | Yes — same matcher | No — needs adapter | Scraper export `site_raw/dynastyDaddy.csv` | N/A | **P2** |
| **FantasyPros** | Yes — article scrape | None | **Absent** | Yes — same matcher | No — needs adapter | Scraper export `site_raw/fantasyPros.csv` | N/A | **P3** |
| **DraftSharks** | Yes — API + scroll | None | **Absent** | Yes — same matcher | No — needs adapter | Scraper export `site_raw/draftSharks.csv` | N/A | **P3** |
| **Yahoo** | Yes — article scrape | None | **Absent** | Yes — same matcher | No — needs adapter | Scraper export `site_raw/yahoo.csv` | N/A | **P3** |
| **DynastyNerds** | Yes — table scrape (paywalled) | None | **Absent** | Yes — same matcher | No — needs adapter | Scraper export `site_raw/dynastyNerds.csv` | N/A | **P4** |
| **Flock** | Yes — session-based API | None | **Absent** | Yes — same matcher | No — needs adapter | Scraper export `site_raw/flock.csv` | N/A | **P4** |

### IDP Universe

| Source | Legacy Scraper | Canonical Adapter | Adapter Status | Identity Handling | Blending Ready | Safest Input Path | Missing Tests | Priority |
|--------|---------------|-------------------|----------------|-------------------|----------------|-------------------|---------------|----------|
| **DLF IDP** | Yes — local CSV | `dlf_csv_adapter.py` | **Functional** | Yes | Yes | `dlf_idp.csv` seed | Covered (Phase A) | **Done** |
| **IDPTradeCalc** | Yes — Google Sheets + JS | None | **Absent** | Yes — same matcher | No — needs adapter | Scraper export `site_raw/idpTradeCalc.csv` | N/A | **P2** |
| **PFF IDP** | Yes — article scrape | None | **Absent** | Yes — same matcher | No — needs adapter | Scraper export `site_raw/pffIdp.csv` (rank-based) | N/A | **P3** |
| **DraftSharks IDP** | Yes — table scrape | None | **Absent** | Yes — same matcher | No — needs adapter | Scraper export `site_raw/draftSharksIdp.csv` | N/A | **P3** |
| **FantasyPros IDP** | Yes — table + ECR | None | **Absent** | Yes — same matcher | No — needs adapter | Scraper export `site_raw/fantasyProsIdp.csv` (rank-based) | N/A | **P3** |

### Rookie Universe

| Source | Legacy Scraper | Canonical Adapter | Adapter Status | Identity Handling | Blending Ready | Safest Input Path | Missing Tests | Priority |
|--------|---------------|-------------------|----------------|-------------------|----------------|-------------------|---------------|----------|
| **DLF Rookie SF** | Yes — local CSV | `dlf_csv_adapter.py` | **Functional** | Yes | Yes | `dlf_rookie_superflex.csv` seed | Covered (Phase A) | **Done** |
| **DLF Rookie IDP** | Yes — local CSV | `dlf_csv_adapter.py` | **Functional** | Yes | Yes | `dlf_rookie_idp.csv` seed | Covered (Phase A) | **Done** |

---

## 2. Scraper Export Bridge — The Key Insight

The legacy scraper already writes per-site CSVs to `exports/latest/site_raw/{key}.csv` in a simple `name,value` format. This is the **safest, zero-new-scraping path** for getting additional sources into the canonical pipeline:

```
Legacy Scraper (production)
  │
  ├── exports/latest/site_raw/ktc.csv          (name, value)
  ├── exports/latest/site_raw/fantasyCalc.csv  (name, value) ← 453 rows
  ├── exports/latest/site_raw/dynastyDaddy.csv (name, value)
  ├── exports/latest/site_raw/fantasyPros.csv  (name, value)
  └── ...
         │
         ▼
  New "scraper-bridge" adapter reads these CSVs
         │
         ▼
  Canonical pipeline blends them
```

**Critical**: This path does NOT require new website scraping. The legacy scraper already does the scraping. We just need an adapter that reads its CSV output.

### Scraper Export Format

All site_raw CSVs share a common format:
```csv
name,value
Patrick Mahomes,9050
Josh Allen,8800
...
```

- **Value-based sites**: Higher = better (KTC, FantasyCalc, DynastyDaddy, Yahoo, IDPTradeCalc)
- **Rank-based sites**: Lower = better (DynastyNerds, PFF IDP, FantasyPros IDP, DraftSharks, Flock)

The existing `KtcStubAdapter` already handles `name,value` CSV format. A generalized "scraper bridge" adapter could handle ALL exported sites.

---

## 3. Recommended Integration Order

### Phase B1: KTC + FantasyCalc (next — enables meaningful 3-source blending)

| Step | Action | Rationale |
|------|--------|-----------|
| B1.1 | **Promote KTC stub to read scraper export** | Change `ktc_stub_adapter.py` to read `exports/latest/site_raw/ktc.csv` instead of a manual seed. Already mostly works — adapter reads `name,value` CSV. |
| B1.2 | **Build `ScraperBridgeAdapter`** (or adapt KTC stub to be generic) | A single adapter that reads any `name,value` CSV from scraper exports. Parameterized by source_id, universe, and whether the signal is rank-based or value-based. |
| B1.3 | **Add FantasyCalc config** | Point ScraperBridgeAdapter at `exports/latest/site_raw/fantasyCalc.csv`. FantasyCalc has the cleanest API data (JSON API, no scraping fragility) and already exports 453 players. |
| B1.4 | **Enable KTC + FantasyCalc in source config** | Add entries to `dlf_sources.template.json` with appropriate weights. |
| B1.5 | **Validate 3-source blend** | Run canonical pipeline with DLF + KTC + FantasyCalc. Verify blending math produces sensible 0–9999 output. |
| B1.6 | **Write tests for ScraperBridgeAdapter** | Cover: value-based signal, rank-based signal, missing file, empty rows, name normalization. |

**Why FantasyCalc first (alongside KTC)**:
- Cleanest data: JSON API with no scraping fragility
- Already has the largest export (453 rows)
- Value-based signal (same as KTC) — no rank-inversion complexity
- No credentials needed
- One of the highest-signal sources in the legacy composite

### Phase B2: DynastyDaddy + IDPTradeCalc (soon — adds IDP depth)

| Step | Action | Rationale |
|------|--------|-----------|
| B2.1 | **Add DynastyDaddy config** | Point ScraperBridgeAdapter at `site_raw/dynastyDaddy.csv`. Value-based, no special handling. |
| B2.2 | **Add IDPTradeCalc config** | Point at `site_raw/idpTradeCalc.csv`. Value-based. Only source in legacy that covers both offense + IDP in a single map. |
| B2.3 | **Validate 5-source blend** | DLF + KTC + FantasyCalc + DynastyDaddy + IDPTradeCalc. |

**Why IDPTradeCalc in Phase B2**: It's the only non-DLF source providing IDP values. Without it, IDP blending has only 1 source.

### Phase B3: FantasyPros + DraftSharks + Yahoo (later — incremental coverage)

| Source | Notes |
|--------|-------|
| **FantasyPros** | Article-based scraping; data sometimes spotty. Add when 5-source blend is validated. |
| **DraftSharks** | Rank-based signal. Adapter needs rank-inversion (lower rank → higher canonical score). |
| **Yahoo** | Article discovery is fragile in legacy scraper. Worth adding but low marginal signal. |

### Phase B4: Defer — DynastyNerds + Flock + PFF IDP (not now)

| Source | Why Defer |
|--------|-----------|
| **DynastyNerds** | Paywalled. Requires session credentials. Scraper data quality varies. Wait until Phase B1-B3 sources prove the adapter pattern. |
| **Flock** | Session-based, expires frequently. Low reliability. |
| **PFF IDP** | Often fails in legacy scraper. Rank-based with fragile article discovery. |
| **DraftSharks IDP** | Lower priority — IDPTradeCalc covers IDP values. |
| **FantasyPros IDP** | Lower priority — DLF IDP + IDPTradeCalc sufficient for MVP. |

---

## 4. Blockers by Source

| Source | Blocker | Severity | Resolution |
|--------|---------|----------|------------|
| **KTC** | Stub adapter is disabled in config; no pointer to scraper export | Low | Update config + file path |
| **FantasyCalc** | No adapter exists | Medium | Build ScraperBridgeAdapter (reusable for all) |
| **DynastyDaddy** | No adapter exists | Medium | Same ScraperBridgeAdapter |
| **IDPTradeCalc** | No adapter exists; mixed offense+IDP in single CSV | Medium | ScraperBridgeAdapter + universe splitting logic |
| **FantasyPros** | No adapter; data quality variable | Low | ScraperBridgeAdapter once validated |
| **DraftSharks** | No adapter; rank-based signal needs inversion | Low | ScraperBridgeAdapter with `signal_type=rank` |
| **Yahoo** | No adapter; fragile article discovery in legacy | Low | ScraperBridgeAdapter |
| **DynastyNerds** | No adapter; paywalled; session required | Medium | Wait — scraper handles session, export works if scrape succeeds |
| **Flock** | No adapter; session expires frequently | High | Unreliable upstream — defer |
| **PFF IDP** | No adapter; often fails in legacy scraper | High | Unreliable upstream — defer |
| **ALL sources** | Source weights are all 1.0 — founder decision needed | **Blocking** | Founder must set relative weights before production use |
| **ALL sources** | `server.py` does not consume canonical output | **Blocking** | Phase D wiring required before any of this reaches production |

---

## 5. Architecture: ScraperBridgeAdapter (Recommended)

Rather than writing N separate adapters, build one generic adapter:

```python
class ScraperBridgeAdapter:
    """Reads per-site CSV exports from the legacy scraper."""

    def __init__(
        self,
        source_id: str,
        source_bucket: str,    # offense_vet, idp_vet, etc.
        signal_type: str,      # "value" (higher=better) or "rank" (lower=better)
        format_key: str = "dynasty_sf",
    ): ...

    def load(self, file_path: Path) -> AdapterResult:
        # Reads name,value CSV
        # Normalizes names
        # Sets rank_raw or value_raw based on signal_type
        ...
```

**Why one adapter, not many**:
- All scraper exports share the same `name,value` format
- Differences are only: source_id, universe, and whether signal is rank vs value
- Fewer adapters = less code to test and maintain
- New sources just need a config entry, not new code

---

## 6. What This Does NOT Cover

- **No new website scraping** — all sources come through the legacy scraper's existing exports
- **No production wiring** — `server.py` changes are Phase D, not Phase B
- **No weight tuning** — founder decision (blocked)
- **No IDP-specific scarcity/replacement math** — Phase C (league engine)
- **No pick/draft capital integration** — separate concern (FantasyCalc exports include picks, but pick handling needs its own adapter path)

---

## 7. Test Coverage Gaps by Source

| Source | Existing Tests | Needed |
|--------|---------------|--------|
| DLF (all 4 universes) | 25+ tests (Phase A complete) | Sufficient for now |
| KTC stub | **None** | Need: seed CSV load, missing file, empty rows, value+rank signals, name normalization |
| ScraperBridgeAdapter | **N/A (doesn't exist)** | Need: value-based signal, rank-based signal, missing file, empty rows, name normalization, signal_type validation |
| Identity with multi-source | 14+ tests (Phase A complete) | Need: cross-source same-player merge with value+rank signals |
| Canonical blend with 3+ sources | 2 tests (Phase A) | Need: 3+ source blend validation, source weight sensitivity, universe isolation |

---

## 8. Decision Log

| Decision | Rationale |
|----------|-----------|
| Use scraper exports, not new scraping | Zero new scraping risk. Legacy scraper already works. Bridge adapter just reads its output. |
| FantasyCalc before DynastyDaddy | Cleaner API data, largest export, highest reliability in legacy scraper. |
| IDPTradeCalc in Phase B2 | Only non-DLF IDP source. Critical for IDP blending depth. |
| Defer DynastyNerds/Flock/PFF | Unreliable upstream scraping. Low marginal signal vs fragility risk. |
| One ScraperBridgeAdapter, not N adapters | All exports share format. Config-driven is simpler. |
| Rank-based sources need explicit signal_type | DraftSharks, DynastyNerds, PFF use rank (lower=better). Adapter must invert for canonical scoring. |

---

_End of source integration matrix._
