# Canonical Pipeline — Source Integration Matrix

_Updated: 2026-03-22_
_Previous version: 2026-03-21_
_Context: Current-state matrix of all sources relevant to the canonical pipeline._

---

## 1. What Has Changed Since Last Version

The previous matrix (2026-03-21) was a planning document. Since then:

- **ScraperBridgeAdapter built** — `src/adapters/scraper_bridge_adapter.py` is functional with 21 tests
- **FantasyCalc enabled** — Active in config, producing 452 player records via scraper bridge
- **2-source blending validated** — 264 offense_vet assets now blend DLF_SF + FANTASYCALC
- **Canonical snapshot produced** — `data/canonical/canonical_snapshot_*.json` with 747 assets across 4 universes
- **Shadow comparison wired** — `server.py` can load the snapshot in `CANONICAL_DATA_MODE=shadow`

This revision reflects **ground truth as of 2026-03-22**, not aspirations.

---

## 2. Source-by-Source Matrix

### Legend

| Column | Meaning |
|--------|---------|
| **Legacy Scraper** | Does `Dynasty Scraper.py` scrape this source? |
| **Scraper Export Exists** | Is a CSV present in `exports/latest/site_raw/`? |
| **Canonical Adapter** | Which adapter would consume it? |
| **Adapter Status** | `active` / `ready` / `stub` / `placeholder` |
| **Currently Blending** | Is this source in the latest canonical snapshot? |
| **Signal Type** | `value` (higher=better) or `rank` (lower=better) |
| **Tests** | Test coverage status |
| **Next Action** | What needs to happen for this source |

### Offense — Veteran Universe

| Source | Legacy Scraper | Export Exists | Canonical Adapter | Adapter Status | Currently Blending | Signal | Tests | Next Action |
|--------|:-:|:-:|---|---|:-:|---|---|---|
| **DLF Superflex** | Yes | Yes (279 rows) | `DlfCsvAdapter` | **Active** | **Yes** | rank_avg | 25+ tests | None — done |
| **FantasyCalc** | Yes | **Yes** (453 rows) | `ScraperBridgeAdapter` | **Active** | **Yes** | value | 21 tests | None — done |
| **KTC** | Yes | **No** | `ScraperBridgeAdapter` | **Ready** (needs CSV) | No | value | Covered by bridge tests | **P1**: Need scraper to export `ktc.csv` |
| **DynastyDaddy** | Yes | **No** | `ScraperBridgeAdapter` | **Ready** (needs CSV) | No | value | Covered by bridge tests | **P2**: Need scraper to export `dynastyDaddy.csv` |
| **Yahoo** | Yes | **No** | `ScraperBridgeAdapter` | **Ready** (needs CSV) | No | value | Covered by bridge tests | **P3**: Need scraper to export `yahoo.csv` |
| **FantasyPros** | Yes | **No** | `ScraperBridgeAdapter` | **Ready** (needs CSV) | No | value | Covered by bridge tests | **P3**: Need scraper to export `fantasyPros.csv` |
| **DraftSharks** | Yes | **No** | `ScraperBridgeAdapter` | **Ready** (needs CSV) | No | **rank** | Covered by bridge tests | **P3**: Need scraper to export + rank signal |
| **DynastyNerds** | Yes (paywalled) | **No** | `ScraperBridgeAdapter` | **Ready** (needs CSV) | No | **rank** | Covered by bridge tests | **P4**: Unreliable upstream |
| **Flock** | Yes (session) | **No** | `ScraperBridgeAdapter` | **Ready** (needs CSV) | No | **rank** | Covered by bridge tests | **P4**: Session expires frequently |

### IDP — Veteran Universe

| Source | Legacy Scraper | Export Exists | Canonical Adapter | Adapter Status | Currently Blending | Signal | Tests | Next Action |
|--------|:-:|:-:|---|---|:-:|---|---|---|
| **DLF IDP** | Yes | Yes (186 rows) | `DlfCsvAdapter` | **Active** | **Yes** (single-source) | rank_avg | 25+ tests | None — done |
| **IDPTradeCalc** | Yes | **No** | `ScraperBridgeAdapter` | **Ready** (needs CSV) | No | value | Covered by bridge tests | **P2**: Only non-DLF IDP source |
| **PFF IDP** | Yes | **No** | `ScraperBridgeAdapter` | **Ready** (needs CSV) | No | **rank** | Covered by bridge tests | **P4**: Often fails in scraper |
| **DraftSharks IDP** | Yes | **No** | `ScraperBridgeAdapter` | **Ready** (needs CSV) | No | value | Covered by bridge tests | **P4**: Low marginal signal |
| **FantasyPros IDP** | Yes | **No** | `ScraperBridgeAdapter` | **Ready** (needs CSV) | No | **rank** | Covered by bridge tests | **P4**: Low marginal signal |

### Rookie Universes

| Source | Legacy Scraper | Export Exists | Canonical Adapter | Adapter Status | Currently Blending | Signal | Tests | Next Action |
|--------|:-:|:-:|---|---|:-:|---|---|---|
| **DLF Rookie SF** | Yes | Yes (67 rows) | `DlfCsvAdapter` | **Active** | **Yes** (single-source) | rank_avg | 25+ tests | None — done |
| **DLF Rookie IDP** | Yes | Yes (31 rows) | `DlfCsvAdapter` | **Active** | **Yes** (single-source) | rank_avg | 25+ tests | None — done |

---

## 3. Current Pipeline State (Measured)

```
Sources in canonical pipeline:  5  (DLF_SF, DLF_IDP, DLF_RSF, DLF_RIDP, FANTASYCALC)
Raw records ingested:          1011
Canonical assets produced:      747
Multi-source blended assets:    264 (35.3%) — all in offense_vet
Single-source assets:           483 (64.7%) — IDP + rookies (DLF only)

Blend coverage by universe:
  offense_vet:    264/466 (56.7%) — DLF_SF + FANTASYCALC
  idp_vet:          0/185 (0%)   — DLF_IDP only
  offense_rookie:   0/66  (0%)   — DLF_RSF only
  idp_rookie:       0/30  (0%)   — DLF_RIDP only
```

---

## 4. Adapter Architecture (Implemented)

```
Legacy Scraper (production, live)
  │
  ├── exports/latest/site_raw/fantasyCalc.csv ← 453 rows (ACTIVE)
  ├── exports/latest/site_raw/ktc.csv         ← NOT YET EXPORTED
  ├── exports/latest/site_raw/dynastyDaddy.csv ← NOT YET EXPORTED
  └── ...
         │
         ▼
  ScraperBridgeAdapter (src/adapters/scraper_bridge_adapter.py)
    ├── signal_type="value"  → stores value_raw (higher=better)
    └── signal_type="rank"   → stores rank_raw  (lower=better)
         │
         ▼
  source_pull.py → canonical_build.py → data/canonical/
```

Adding a new source requires **only a config entry** — no new adapter code:

```json
{
  "enabled": true,
  "source": "DYNASTYDADDY",
  "adapter": "scraper_bridge",
  "universe": "offense_vet",
  "file": "exports/latest/site_raw/dynastyDaddy.csv",
  "signal_type": "value"
}
```

Plus a weight entry in `config/weights/default_weights.json`.

---

## 5. Recommended Integration Order

### Completed: DLF (4 universes) + FantasyCalc

Already active. 264 blended assets in offense_vet.

### Phase B2: KTC + DynastyDaddy (next — expand offense_vet depth)

| Source | Why Now | Blocker | Action Required |
|--------|---------|---------|-----------------|
| **KTC** | Highest-signal source in the legacy composite. Same `name,value` format. | Scraper not exporting `ktc.csv` in current run | Ensure legacy scraper exports `site_raw/ktc.csv`; add config entry |
| **DynastyDaddy** | Second-highest-signal value source. API-based in legacy scraper. | Scraper not exporting `dynastyDaddy.csv` in current run | Same as KTC |

**Expected result**: 3-4 source blending for offense_vet. Higher confidence composite values.

**What blocks this is not adapter code** — the ScraperBridgeAdapter already handles both. The blocker is that the legacy scraper's last run did not export these CSVs (it exported only DLF + FantasyCalc in the current `exports/latest/site_raw/` directory). When the scraper next runs successfully with KTC and DynastyDaddy, their CSVs will appear and the pipeline will ingest them automatically.

### Phase B3: IDPTradeCalc (soon — first multi-source IDP)

| Source | Why | Blocker | Action Required |
|--------|-----|---------|-----------------|
| **IDPTradeCalc** | Only non-DLF IDP source. Without it, idp_vet has 0% multi-source blending. | Scraper not exporting `idpTradeCalc.csv` | Config entry + weight. Note: IDPTradeCalc covers both offense+IDP in a single CSV — will need universe assignment decision. |

**Expected result**: First multi-source IDP values. Currently idp_vet is 100% DLF-only.

### Phase B4: FantasyPros + DraftSharks + Yahoo (later — incremental)

| Source | Signal Type | Notes |
|--------|-------------|-------|
| **FantasyPros** | value | Article-based, sometimes spotty in legacy scraper |
| **DraftSharks** | **rank** | First rank-based source to test that signal path end-to-end |
| **Yahoo** | value | Fragile article discovery; low marginal signal |

**Expected result**: 6-7 source blending for offense_vet. Rank-based signal path validated.

### Phase B5: Defer — DynastyNerds + Flock + PFF IDP + IDP secondaries

| Source | Why Defer |
|--------|-----------|
| **DynastyNerds** | Paywalled. Session-dependent. Scraper data quality varies. |
| **Flock** | Session expires frequently. Unreliable upstream. |
| **PFF IDP** | Often fails in legacy scraper. Rank-based with fragile article discovery. |
| **DraftSharks IDP** | IDPTradeCalc covers the IDP need. Low marginal value. |
| **FantasyPros IDP** | DLF IDP + IDPTradeCalc sufficient for MVP. |

---

## 6. Blockers (Current)

| Blocker | Scope | Severity | Resolution Path |
|---------|-------|----------|-----------------|
| **Missing scraper CSVs** | KTC, DynastyDaddy, IDPTradeCalc, all P3/P4 sources | **Primary** | Wait for legacy scraper to run with these sites succeeding, or manually trigger scrape |
| **Source weights all 1.0** | All sources | Medium | Founder decision needed. Equal weights are functional but not tuned. |
| **server.py not consuming canonical output** | All sources | Medium | Shadow mode wired; primary mode requires Phase D work |
| **No position/team data from bridge sources** | FantasyCalc, all future bridge sources | Low | Identity matcher falls to name-only (0.85 confidence). Functional but lower precision. |
| **FantasyCalc picks in offense_vet** | FantasyCalc | Low | FantasyCalc CSV includes "2026 1st", "2026 Pick 1.01" etc. These get asset_type=player since bridge adapter doesn't classify picks. Future enhancement to detect pick names. |

---

## 7. Test Coverage

| Component | Tests | Status |
|-----------|-------|--------|
| DlfCsvAdapter | 25+ | Complete |
| ScraperBridgeAdapter | 21 | Complete — covers value/rank signals, edge cases, real FantasyCalc CSV |
| KtcStubAdapter | 0 | Not needed if bridge adapter replaces it for production use |
| Canonical transform | 40+ | Complete |
| Identity matcher | 28+ | Complete |
| Snapshot integration | 14 | Complete — covers pipeline→snapshot→comparison block |
| Multi-source blending | Covered in transform tests | 2+ source scenarios tested |

---

## 8. Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-21 | Use scraper exports, not new scraping | Zero scraping risk. Legacy scraper handles all website interaction. |
| 2026-03-21 | One ScraperBridgeAdapter for all export sources | All scraper CSVs share `name,value` format. Config-driven, not code-driven. |
| 2026-03-21 | FantasyCalc as first bridge source | Cleanest data (JSON API), largest export (453 rows), already present in exports. |
| 2026-03-22 | KTC + DynastyDaddy as next priority | Highest-signal value sources. Blocked only by missing scraper CSVs, not by code. |
| 2026-03-22 | IDPTradeCalc for first multi-source IDP | Only non-DLF IDP source available. Critical for IDP blending confidence. |
| 2026-03-22 | Defer DynastyNerds/Flock/PFF | Unreliable upstream. Low marginal signal vs fragility. |

---

_End of source integration matrix._
