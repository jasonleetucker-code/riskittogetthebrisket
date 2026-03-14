# Blueprint Gap Analysis

_Generated: 2026-03-14_

---

## Summary

The blueprint (`docs/BLUEPRINT_EXECUTION.md`) defines a five-system stack. This analysis maps every blueprint commitment against implementation reality.

**Completion by system**:
| System | Blueprint Scope | Completion |
|--------|----------------|------------|
| 1. Source Ingestion | Adapters + raw snapshots | ~60% (DLF works, KTC stub, others missing) |
| 2. Identity Mapping | Master IDs + alias resolution | ~70% (logic complete, no tests, no persistent DB) |
| 3. Canonical Value Engine | Normalization + blending | ~50% (transforms work, not wired to production) |
| 4. League Context Engine | Scoring, scarcity, replacement | ~5% (config template only, module empty) |
| 5. Decision UI / API | Calculator, rankings, roster | ~40% (legacy UI works, new API not built) |

**Cross-cutting**:
| Area | Completion |
|------|-----------|
| Scoring adjustment | ~90% (module complete, integrated with legacy) |
| Deploy/CI | ~95% (GitHub Actions, Jenkins, systemd, rollback) |
| Runtime/routing | ~95% (FRONTEND_RUNTIME, auth gate, landing) |
| API contract | ~85% (validated, versioned, multi-mode serving) |

---

## Gap Detail by Blueprint Section

### §3.1 Raw Source Layer
| Requirement | Status | Gap |
|------------|--------|-----|
| `raw_source_snapshots` table/storage | **Implemented** | JSON files in `data/raw_sources/`, not DB tables |
| `raw_source_assets` records | **Implemented** | `RawAssetRecord` dataclass with 44 fields |
| Store exact payloads per source pull | **Implemented** | Manifests, JSONL, parse logs per snapshot |
| Never mutate raw rows | **Implemented** | Immutable snapshot directories |
| Reruns possible without re-scraping | **Implemented** | Seed CSVs preserved in snapshot dirs |

### §3.2 Identity Resolution
| Requirement | Status | Gap |
|------------|--------|-----|
| Master `players` table | **Schema only** | SQL migration exists but no DB is created/used at runtime. In-memory only. |
| `player_aliases` table | **Schema only** | Same — schema defined, not instantiated |
| Map Sleeper/KTC/DLF IDs | **Partial** | Matcher handles normalized names. No Sleeper ID integration in identity layer (Sleeper IDs used in scoring module separately). |
| No value blending until IDs resolved | **Implemented** | `source_pull.py` runs identity after ingest, before canonical |

### §3.3 Canonical Normalization
| Requirement | Status | Gap |
|------------|--------|-----|
| Separate universes (off vet/rookie, IDP vet/rookie, picks) | **Implemented** | `KNOWN_UNIVERSES` in transform.py |
| Rank → percentile → curve | **Implemented** | `percentile_from_rank()` → `percentile_to_canonical()`, power curve `9999 * percentile^0.65` |
| Blend across sources with weights | **Implemented** | `blend_source_values()` with configurable per-source weights |
| `canonical_snapshots` + `canonical_asset_values` (versioned) | **Partial** | JSON snapshots versioned by run_id. No persistent DB. No `value_history` table. |

### §3.4 League Context Engine
| Requirement | Status | Gap |
|------------|--------|-----|
| League settings schema + import | **Config template only** | `default_superflex_idp.template.json` exists. No engine code. |
| Replacement baselines | **Not started** | `src/league/` is empty |
| Scarcity multipliers | **Not started** | |
| Pick discount logic | **Config only** | Template has discount values, no code to apply them |

### §5 Normalization & Blending Rules
| Requirement | Status | Gap |
|------------|--------|-----|
| Percentile transform | **Implemented** | |
| Curve (power/logistic) | **Implemented** (power only) | Logistic option not implemented |
| Blend with coverage/stability weights | **Partial** | Blend works but weights are all 1.0 (equal). No coverage/stability differentiation. |
| League adjustments (scarcity, position factors, rookie optimism, contender dial) | **Not started** | Depends on Phase 4 league engine |
| Trade liquidity (package compression, pick time discount) | **Not started** | Depends on Phase 5 trade engine |

### §6 League Context & Pick Engine
| Requirement | Status | Gap |
|------------|--------|-----|
| Replacement level = (teams × starters) + buffer | **Not started** | |
| Scarcity multiplier per position | **Not started** | |
| Pick model: tiered curve by slot | **Not started** | Config has year discounts only |
| Early/mid/late buckets | **Partial** | Adapter contract supports bucket field. No engine logic. |

### §7 Trade Engine Contract
| Requirement | Status | Gap |
|------------|--------|-----|
| Raw totals per side | **Legacy only** | Frontend sums legacy values. No new trade API. |
| Package adjustment / consolidation premium | **Not started** | |
| Lineup impact | **Not started** | |
| Fairness band verdict + balancing suggestion | **Partial** | Frontend has gap-based verdict (near even/lean/strong lean/major gap). No balancing suggestions. |
| Market mirror vs My board mode | **Not started** | |

### §8 UI Surfaces
| Requirement | Status | Gap |
|------------|--------|-----|
| Calculator | **Complete (legacy)** | Both Static and Next.js versions work |
| Rankings | **Complete (legacy)** | Next.js version with tiers, sorting, filtering, CSV export |
| Team/League view | **Not started** | No page exists |
| Player detail | **Not started** | No page exists |
| Settings | **Partial** | E2E tests reference settings/site matrix in Static app. No Next.js settings page. |

### §9 Jenkins Responsibilities
| Requirement | Status | Gap |
|------------|--------|-----|
| Schedule source pulls | **Implemented** | Jenkinsfile "Ingest" stage |
| Validate unmatched/duplicates/outliers | **Implemented** | `validate_ingest.py` + canonical validation |
| Rebuild canonical snapshots | **Implemented** | `canonical_build.py` in Jenkinsfile |
| Generate ops reports | **Implemented** | `reporting.py` → markdown ops report |
| Audit logs (snapshot IDs, weights) | **Partial** | Snapshots have IDs. No explicit audit log table. |

### §11 Open Decisions
| Decision | Status |
|----------|--------|
| Source list + initial weights | **Unresolved** — DLF only, equal weights |
| League scoring + lineup profile | **Partially resolved** — Sleeper ingest exists in scoring module |
| Package tax multiplier | **Unresolved** |
| Rookie optimism setting | **Unresolved** |
| Contender vs rebuilder heuristics | **Unresolved** |
| Market mirror vs My board | **Unresolved** |
| Pick discount schedule | **Partially resolved** — config has 3-year schedule |

---

## Critical Gaps (Block Further Progress)

1. **League context engine (`src/league/`)** — Empty module. Blocks canonical-fed trade calculator and rankings with scarcity/replacement adjustments.

2. **Canonical → production wiring** — `server.py` reads `dynasty_data_*.json` from legacy scraper. The canonical pipeline writes to `data/canonical/` but nothing reads it for production serving. This is the single biggest integration gap.

3. **Founder decisions** — Source weights, package tax, rookie optimism, contender heuristics remain unresolved per blueprint §11.

---

## Medium Gaps (Reduce Product Value)

4. **No additional source adapters** — Only DLF works. KTC disabled. No Dynasty Nerds, Yahoo, or IDPTradeCalc. Multi-source blending is the core value proposition but has only one source.

5. **No roster/team view or player detail** — Blueprint §8 surfaces 3-5. Only 1-2 exist.

6. **No value history/trend tracking** — Blueprint promises trend charts and regression alerts. No data stored for this.

7. **No unit tests for core pipeline** — Adapters, identity, canonical, name cleaning all untested.

---

## Low Gaps (Polish / Future)

8. **Trade finder / target list** — Phase 7 feature.
9. **Contender/rebuilder toggle** — Phase 7 feature.
10. **Historical charts** — Phase 7 feature.
11. **Logistic curve option** — Power curve works; logistic is a nice-to-have.
12. **Persistent identity DB** — In-memory resolution works; DB would add durability.
