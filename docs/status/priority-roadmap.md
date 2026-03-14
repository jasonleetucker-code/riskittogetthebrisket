# Priority Roadmap — Recommended Execution Order

_Generated: 2026-03-14_

---

## Sequencing Rationale

Work is ordered by **dependency chain** and **product impact**. The canonical engine cannot replace the legacy scraper until the league context engine exists and canonical values are wired to production. Everything flows from that critical path.

---

## Phase A: Foundation Hardening (No new features — reduce risk)

**Goal**: Test what exists, fix security, update docs.

| # | Task | Ref | Est. Complexity | Depends On |
|---|------|-----|----------------|------------|
| A1 | Write unit tests for `src/utils/name_clean.py` | VG-4 | Low | — |
| A2 | Write unit tests for `src/adapters/dlf_csv_adapter.py` | VG-1 | Low | — |
| A3 | Write unit tests for `src/identity/matcher.py` | VG-2 | Medium | — |
| A4 | Write unit tests for `src/canonical/transform.py` | VG-3 | Medium | — |
| A5 | Move default password out of source code | TD-1 | Low | — |
| A6 | Set cookie secure flag for production | TD-2 | Low | — |
| A7 | Update `BLUEPRINT_EXECUTION.md` §10 checkboxes | TD-3 | Low | — |
| A8 | Fix `src/README.md` description of `src/api/` | TD-4 | Low | — |

---

## Phase B: Second Source + Identity Confidence (Enable multi-source blending)

**Goal**: Get ≥2 real sources flowing through the canonical pipeline.

| # | Task | Ref | Est. Complexity | Depends On |
|---|------|-----|----------------|------------|
| B1 | Enable KTC adapter — either live scraping or reliable seed CSV | H-1 | Medium | A2 (adapter tests) |
| B2 | Enable KTC in `config/sources/dlf_sources.template.json` | H-1 | Low | B1 |
| B3 | Set meaningful source weights (founder decision) | CB-3 | Low (config) | Founder input |
| B4 | Validate canonical pipeline end-to-end with 2 sources | — | Medium | B1, B2, B3 |

---

## Phase C: League Context Engine (The critical missing piece)

**Goal**: Implement `src/league/` so canonical values have league-specific adjustments.

| # | Task | Ref | Est. Complexity | Depends On |
|---|------|-----|----------------|------------|
| C1 | Resolve founder decisions: replacement math, rookie optimism, contender heuristics | CB-3 | Decision | Founder input |
| C2 | Implement replacement baseline calculator | CB-2 | High | C1 |
| C3 | Implement scarcity multiplier engine | CB-2 | High | C2 |
| C4 | Implement pick curve + time discount application | CB-2 | Medium | C1 |
| C5 | Implement rookie optimism dial | CB-2 | Low | C1 |
| C6 | Replace `scripts/league_refresh.py` stub with real implementation | TD-5 | Medium | C2-C5 |
| C7 | Write unit tests for league engine | — | Medium | C2-C5 |

---

## Phase D: Canonical → Production Wiring (Make the new engine live)

**Goal**: `server.py` consumes canonical pipeline output. Production values come from new engine.

| # | Task | Ref | Est. Complexity | Depends On |
|---|------|-----|----------------|------------|
| D1 | Define cutover criteria and document | M-8 | Low | — |
| D2 | Add canonical data loading path in `server.py` alongside legacy | CB-1 | High | Phase C |
| D3 | Build A/B comparison mode (legacy vs canonical values) | — | Medium | D2 |
| D4 | Validate canonical values match or exceed legacy quality | — | High | D3 |
| D5 | Switch production default to canonical pipeline | — | Low (config) | D4 |
| D6 | Update `/api/data` contract if needed for canonical fields | — | Medium | D2 |

---

## Phase E: Trade Engine Upgrade (Blueprint §7)

**Goal**: New trade API with package adjustment, lineup impact, fairness bands.

| # | Task | Ref | Est. Complexity | Depends On |
|---|------|-----|----------------|------------|
| E1 | Resolve package tax multiplier (founder decision) | CB-3 | Decision | Founder input |
| E2 | Implement package adjustment / consolidation premium logic | H-2 | High | E1, Phase C |
| E3 | Implement lineup impact service (per-team roster profile) | H-2 | High | Phase C, Sleeper roster |
| E4 | Implement fairness band + balancing suggestion engine | H-2 | Medium | E2 |
| E5 | Build REST endpoint for trade evaluation | H-2 | Medium | E2-E4 |
| E6 | Wire frontend trade page to new trade API | — | Medium | E5 |

---

## Phase F: New UI Surfaces (Blueprint §8)

**Goal**: Roster/team view, player detail, settings in Next.js.

| # | Task | Ref | Est. Complexity | Depends On |
|---|------|-----|----------------|------------|
| F1 | Build roster/team view page + API | H-3 | High | Phase D |
| F2 | Build player detail page with source breakdown | H-4 | Medium | Phase D |
| F3 | Implement value history tracking + trend API | M-5 | High | Phase D |
| F4 | Add trend charts to player detail | — | Medium | F3 |
| F5 | Build settings page in Next.js | M-6 | Medium | — |
| F6 | Wire Next.js auth to server.py auth | H-6 | Medium | — |

---

## Phase G: Source Expansion + IDP Maturity

**Goal**: More sources, stronger IDP support.

| # | Task | Ref | Est. Complexity | Depends On |
|---|------|-----|----------------|------------|
| G1 | Dynasty Nerds adapter | M-1 | Medium | Phase B patterns |
| G2 | Yahoo values adapter | M-2 | Medium | Phase B patterns |
| G3 | IDPTradeCalc adapter | M-3 | Medium | Phase B patterns |
| G4 | IDP-specific scarcity/replacement in league engine | M-4 | Medium | Phase C |
| G5 | IDP filtering in Next.js rankings | — | Low | G4 |

---

## Phase H: Advanced Features (Phase 7 of blueprint)

| # | Task | Ref | Est. Complexity | Depends On |
|---|------|-----|----------------|------------|
| H1 | Trade finder / target list | L-1 | High | Phase E |
| H2 | Contender vs rebuilder toggle | L-2 | Medium | Phase C |
| H3 | Historical value charts + regression alerts | L-3 | High | F3 |
| H4 | Mobile navigation + touch improvements | M-7 | Medium | — |

---

## Dependency Graph (Simplified)

```
Phase A (tests, security)  ← can start immediately
     ↓
Phase B (2nd source)       ← needs founder decision on weights
     ↓
Phase C (league engine)    ← needs founder decisions; CRITICAL PATH
     ↓
Phase D (canonical wiring) ← needs league engine
     ↓
Phase E (trade engine)     ← needs canonical wiring + founder decisions
Phase F (new UI surfaces)  ← needs canonical wiring
Phase G (more sources)     ← can start after Phase B patterns established
Phase H (advanced)         ← needs most of above
```

**Phases A, B, F5, F6, H4 can run in parallel** — they have no dependencies on the critical path.

**Critical path**: A → B → C → D → E/F

---

## Quick Wins (Can Ship This Week)

1. **A5**: Remove hardcoded password (10 min)
2. **A6**: Set secure cookie flag (5 min)
3. **A7**: Update blueprint checkboxes (30 min)
4. **A8**: Fix src/README.md (5 min)
5. **A1**: name_clean unit tests (1-2 hours)
