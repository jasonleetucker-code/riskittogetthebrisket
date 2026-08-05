# Formula and Mathematical Audit

**Deliverable section 9 of the master site audit.** Every number below is traceable to a
finding id in `docs/master-site-audit/findings.json`, to a file in
`docs/master-site-audit/evidence/`, or to a command re-run against the live tree on branch
`claude/fantasy-football-master-audit-umvex5`. Code observations were taken at the audit
baseline `e96c06ef` (`AUDIT_PROTOCOL.md`); `findings.json` was merged at `ba9f348b`; the
re-runs in this document were executed at `fb4a15a0`, which touches only
`docs/master-site-audit/` and no source file cited below. Measurements marked **(re-run)**
were executed again while writing this document and reproduced to the digit.

| | |
|---|---|
| Primary shard | `docs/master-site-audit/evidence/registry/W30.jsonl` — 22 findings |
| Primary artifact | `docs/master-site-audit/evidence/W30/formula-inventory.csv` — **126 numerical concepts** |
| Numeric proofs | `evidence/W30/{playoff-odds-two-engines,power-two-engines,percentile-helpers,ktc-va-three-ports,rank-to-value-js-vs-py,percentile-train-serve-skew,starter-needs-hardcode-repro,module-reachability}.json` |
| Cross-workstream proofs | W02 (blend), W03/W07/W08 (TE multiplier), W04 (curve fitting + promotion gate), W12/W27 (signal labels), W29 (value-flow scales) |
| Python | `.venv/bin/python` 3.11.15 — CI runs 3.12 |
| Test suite at HEAD | **6,278 passed, 40 skipped, exit 0** (`evidence/test-results-summary.txt`); frontend vitest 1,754 passed |

**Contents.** [9.1 Read this first](#91-read-this-first) · [9.2 Counts](#92-counts) ·
[9.3 The formula inventory](#93-the-formula-inventory) (126 rows — long; skip to 9.4) ·
**[9.4 One concept, many implementations](#94-the-central-section-one-concept-many-implementations)** ·
[9.5 Double counts](#95-double-counts) · [9.6 Wrong units and wrong scales](#96-wrong-units-and-wrong-scales) ·
[9.7 Leakage](#97-leakage) · [9.8 Registry reconciliation](#98-reconciliation-against-docsauditsformula-registryjson) ·
[9.9 Validation](#99-validation-unvalidated-is-not-the-same-as-wrong) ·
[9.10 What is right](#910-what-is-right) · [9.11 Dead and misdescribed math](#911-dead-and-misdescribed-math) ·
[9.12 Live per-league defects](#912-live-per-league-defects-in-the-formulas-themselves) ·
[9.13 Errata](#913-errata-in-the-w30-shard) · [9.14 Repair order](#914-repair-order)

---

## 9.1 Read this first

Three findings, then the detail.

1. **The value spine is sound and reproducible.** One board, one blend path, exactly
   reproducible: a clean-room reimplementation matched `_blendedValueUncapped` on 800/800 rows
   and the served `rankDerivedValue` on 1,092/1,092 rows (W02-F012). The single-source haircut,
   the TE basis conversion and pick tethering all verify exact on the live payload (W02-F013).
2. **The decision layer around it has no authority model.** 126 concepts were inventoried;
   **70 carry a duplicate-of pointer and 32 are verdicted "duplicate or conflicting"**. Six
   classifiers answer "is this team a contender". Five percentile helpers disagree at the
   endpoints. Two playoff-odds engines and two power-ranking engines describe *different
   leagues* on the same page, switched by one settings toggle that defaults to the unvalidated
   engine.
3. **Nothing in the test suite can see any of this.** All 6,278 tests pass. Not one test file
   imports two implementations of the same concept to compare them — verified by grep for the
   power engines, the playoff engines, the replacement-level modules and the three KTC
   Value-Adjustment ports (§9.9.3). The duplication is invisible to CI by construction.

Two prior-audit headline claims about the *mathematics* did not survive adversarial
verification and are corrected in §9.9.1: the Hill promotion gate is **not** contaminated by
its own blend sources (W04-F001, **overturned**), and "no constant was ever tuned against
anything but stability" is **rescoped to P3** — the repo declares a target, enforces it with a
pinned tolerance test, and overrides the stability optimum by name where the two conflict
(W04-F008).

---

## 9.2 Counts

### 9.2.1 The inventory by verdict

126 concepts, one record per concept (not per expression).

| Verdict | Count | Share |
|---|---:|---:|
| Implemented and verified | 66 | 52.4% |
| **Duplicate or conflicting implementation** | **32** | **25.4%** |
| Blocked by data (BDVM projection snapshots absent) | 8 | 6.3% |
| Implemented but defective | 5 | 4.0% |
| Deprecated but still active | 4 | 3.2% |
| Scaffolded only | 4 | 3.2% |
| Missing (concept does not exist in the tree) | 4 | 3.2% |
| Partially implemented | 2 | 1.6% |
| Implemented but disconnected | 1 | 0.8% |
| **Total** | **126** | |

70 of the 126 carry a `duplicate-of` pointer. The gap between 70 and 32 is deliberate: a
pointer records *"this concept has a sibling"*, a verdict of `Duplicate or conflicting`
records *"and they are not reconciled"*. Pointers that resolve to a documented, intentional
divergence (`F-122`/`F-123`, the two trade-engine gates) or to a numerically verified parity
port (`F-130`/`F-131`) keep a clean verdict.

*How to re-run:*
`.venv/bin/python -c "import csv,collections;r=list(csv.DictReader(open('docs/master-site-audit/evidence/W30/formula-inventory.csv')));print(len(r),collections.Counter(x['verdict'] for x in r),sum(1 for x in r if x['duplicate-of'] not in ('-','')))"`
→ `126 Counter({'Implemented and verified': 66, 'Duplicate or conflicting implementation': 32, ...}) 70` **(re-run)**

### 9.2.2 Why 126 and not 562

The prior audit's registry (`docs/audits/decision-intelligence-audit-2026-08-04.registry.json`)
records **562 formula entries across 26 areas**. That is an expression-level census with the
same expression re-recorded in every area that touches it. This inventory is a **concept-level**
census — one row per "who owns this number" — which is the granularity that makes duplication
visible. The two counts are not in conflict and neither supersedes the other.

*How to re-run:*
`.venv/bin/python -c "import json;d=json.load(open('docs/audits/decision-intelligence-audit-2026-08-04.registry.json'));print(len(d), sum(len(a.get('formulas') or []) for a in d))"` → `26 562` **(re-run)**

---

## 9.3 The formula inventory

Full-fidelity machine-readable source:
`docs/master-site-audit/evidence/W30/formula-inventory.csv` (17 columns; the two columns not
rendered below — `possible double-count` and `possible leakage` — are analysed in §9.5 and
§9.7). Verdict abbreviations: **OK** = implemented and verified, **DUP** = duplicate or
conflicting, **DEFECT** = implemented but defective, **PARTIAL**, **SCAFFOLD** = scaffolded
only, **BLOCKED** = blocked by data, **DEPRECATED** = deprecated but still active,
**DISCONNECTED**, **MISSING**.

#### 9.3.1 Board-level value concepts

| ID | Concept | Expression | file:lines | Inputs | Units · scale/range | Consumers | Rationale · assumptions | Tests | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `F-001` | Player value (canonical board) | rankDerivedValue = count_aware_blend(per-source Hill(percentile(rank))) then TE-basis lift -> Hampel -> shrinkage(IDP/picks) -> single-source haircut(0.30) -> corridor clamp(IDP) -> two-way max() -> pick year discount -> pick tethering | `src/api/data_contract.py::_compute_unified_rankings (~5290-6900)` | per-source ranks + value-direct votes from _RANKING_SOURCES; scope master curves | internal value points · 0-9999 (_DISPLAY_SCALE_MAX=9999) | /api/data, /rankings, every trade engine, /terminal, /waivers, /angle, /arbitrage | CLAUDE.md 'Live Value Pipeline'; the one live valuation path — a fixed 500-rank percentile reference; ranks past 500 clamp to the curve tail | tests/api/test_source_overrides.py, tests/api/test_data_contract*.py | **OK** |
| `F-002` | Player value (scraper composite) | _composite / _finalAdjusted / _rawComposite — the pre-canonical scraper blend | `Dynasty Scraper.py (_market_confidence, composite build)` | raw source CSVs | scraper points · site-specific | written into data/dynasty_data_*.json; read by data_contract as INPUT only | legacy scraper scale kept as an input snapshot, not a board — assumed never surfaced as a user-visible value | tests/audit/test_formula_registry.py::test_value_bundle_scale_contract_is_enforced | **DEPRECATED** (dup-of F-001 (different concept, retained)) |
| `F-003` | Fundamental value (BDVM) | to_trade_value(strategy capitals) — surplus over dynamic replacement, CES package math (Sum v^theta)^(1/theta) - C_spot*overflow | `src/bdvm/engine.py::to_trade_value; src/bdvm/trade_math.py:35-38` | projection snapshots under data/bdvm/projections/, league scoring, aging curves | fundamental value points · model-scaled, not 0-9999 | /api/bdvm/values\|roster\|trades\|trade-eval, /bdvm, /rankings Fund-gap col, /draft | docs/research/bdvm-v1/ — an independent value CONCEPT, never merged into F-001 — projections exist; without a snapshot the endpoint says so; absent path: data/bdvm/ | tests/bdvm/ (engine parity vs frozen Appendix-C fixture) | **BLOCKED** |
| `F-004` | Value bundle scale contract | overall/finalAdjusted/displayValue = None unless the row carries canonical stamps; rawComposite passes the scraper number through | `src/api/data_contract.py::_player_value_bundle:8675` | player dict | internal value points · 0-9999 or None | every /api/data row | formula-registry value-bundle-scale — None is rendered as 'unpriced', never as 0 | tests/audit/test_formula_registry.py:157-163 | **OK** |

#### 9.3.2 Rank to value, and the percentile denominators

| ID | Concept | Expression | file:lines | Inputs | Units · scale/range | Consumers | Rationale · assumptions | Tests | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `F-010` | Rank -> value (Hill, backend) | v = 1 + 9998 / (1 + ((rank-1)/HILL_MIDPOINT)^HILL_SLOPE); OFFENSE/GLOBAL/ROOKIE share 65.4/0.91, IDP uses 64.6/0.90 | `src/canonical/player_valuation.py::rank_to_value:287, rank_to_value_for_scope:313` | rank, scope | value points · 1..9999 | src/api/rank_history.py:72, src/api/terminal.py:38 | reconstruction path for history rows that stored a rank but no value — scope routing is a no-op for OFFENSE vs GLOBAL vs ROOKIE at HEAD (measured identical) | tests/api/test_rank_form_frontend_parity.py | **OK** |
| `F-011` | Rank -> value (Hill, frontend) | Math.round(1 + span/(1 + ((r-1)/midpoint)^slope)) with {65.4, 0.91, 9998} | `frontend/lib/value-history.js::valueFromRank:349 (RANK_FORM_CURVE:333)` | rank | value points · 1..9999 | frontend/components/terminal/TeamCommandHeader.jsx, TeamValueChart.jsx | avoids one API call per history point on /terminal — the two constants stay in lockstep — enforced by a test, not by import; the two copies agree numerically at HEAD | tests/api/test_rank_form_frontend_parity.py | **DUP** (dup-of F-010 (verified numerically identical at 15 ranks, W30 rank-to-value-js-vs-py.json)) |
| `F-012` | Value -> rank (closed-form inverse) | r = 1 + midpoint * (span/(v-1) - 1)^(1/slope) | `frontend/lib/value-history.js::rankFromValue:371` | blended value | rank ordinal · >=1 or null outside the invertible domain | frontend/components/PlayerRankHistoryChart.jsx:268 | derives a rank line for snapshots that persisted value but not rank — the board's value came from this exact curve (it did not — F-001 did) | frontend/__tests__ value-history | **OK** (dup-of F-010) |
| `F-013` | Rank -> value (scraper) | _calibrated_rank_to_value / _fallback_sparse_rank_value | `Dynasty Scraper.py (5 references)` | source ranks | scraper points · site-specific | the scraper's own composite (F-002) | separate system predating the canonical engine | scraper tests | **DEPRECATED** (dup-of F-010 (separate system, documented)) |
| `F-014` | Percentile -> value (the live conversion) | percentile_to_value(p, scope) using per-scope (C, S) master constants | `src/canonical/player_valuation.py::percentile_to_value:371` | percentile in [0,1], scope | value points · 0-9999 | src/api/data_contract.py::_compute_unified_rankings | Hill-style masters refit weekly, promoted by hand — the four scopes really are different populations | tests/canonical/, tests/model_registry/ | **OK** |
| `F-015` | Rank -> percentile denominator | p = (rank - 1) / (_PERCENTILE_REFERENCE_N - 1) with _PERCENTILE_REFERENCE_N = 500; ranks past 500 clamp | `src/api/data_contract.py:5303` | combined-pool rank | percentile · 0..1 (clamped) | F-001 | deliberate top-500-board behaviour — every source's pool is comparable to a 500-row reference | tests/api/ | **OK** (dup-of F-016 (train/serve skew)) |
| `F-016` | Rank -> percentile (model-registry holdout) | p = i / (n - 1) over a 400-capped NATIVE pool | `src/model_registry/holdout.py` | per-source native ranks | percentile · 0..1 | scripts/auto_refit_hill_curves.py challenger scoring | holdout scoring measures generalization across markets — the fit's percentile definition matches serving's — it does not | tests/model_registry/ | **DEFECT** (dup-of F-015) |

#### 9.3.3 The consensus blend

| ID | Concept | Expression | file:lines | Inputs | Units · scale/range | Consumers | Rationale · assumptions | Tests | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `F-020` | Consensus blending (count-aware) | n=1 passthrough; n=2 mean; n=3-4 untrimmed mean-median; n>=5 trimmed mean-median | `src/api/data_contract.py::_compute_unified_rankings (aggregation stage 7)` | per-source votes after Hill | value points · 0-9999 | F-001 | CLAUDE.md 'Live Value Pipeline' step 7 — sources are exchangeable peers | tests/api/test_source_overrides.py | **OK** |
| `F-021` | Source weights | every entry in _RANKING_SOURCES carries weight 1.0 by policy | `src/api/data_contract.py::_RANKING_SOURCES:1005` | source registry | unitless weight · 1.0 | F-001, POST /api/rankings/overrides | policy: equal weight until a measured reason exists — config/weights/default_weights.json is documentation only — nothing loads it | tests/api/test_source_registry_parity.py | **OK** |
| `F-022` | Hampel outlier filter | reject \|x - median\| > _HAMPEL_K * 1.4826 * MAD with K=2.75, min_n=4, min_threshold=1000.0 | `src/api/data_contract.py:232-234` | per-source votes | value points · 0-9999 | F-001 pre-blend | robust outlier rejection — MAD is a valid dispersion estimate at n>=4 | tests/api/ | **OK** |
| `F-023` | MAD volatility penalty | value -= _MAD_PENALTY_LAMBDA * MAD (lambda = 0.0 since 2026-04-20) | `src/api/data_contract.py:5429` | sourceSpread | value points · no-op | sourceSpread is stamped as a pure diagnostic | retired; kept for the diagnostic field | tests/api/ | **DEPRECATED** |
| `F-024` | Single-source haircut | non-pick rows resting on one post-Hampel source keep 0.30 of blended value | `src/api/data_contract.py:5443 (_SINGLE_SOURCE_VALUE_RETENTION)` | post-Hampel source count | value points · x0.30 | F-001 | one source is not a consensus — a 70% haircut is the right magnitude — a prior, not a measurement | tests/api/ | **OK** |
| `F-025` | Hierarchical anchor + alpha shrinkage | shrunk = (1-alpha)*group_estimate + alpha*anchor with alpha = 0.10; IDP and picks ONLY (offense takes a flat count-aware mean-median) | `src/api/data_contract.py:5395 (_ALPHA_SHRINKAGE)` | anchor source set (picks widen to include ktcSfTep) | value points · 0-9999 | F-001 step 6 | thin IDP/pick coverage needs an anchor — offense coverage is thick enough not to need it | tests/api/ | **OK** |
| `F-026` | Market corridor clamp (guardrail) | clamp drift to the P90 band per confidence bucket, hard cap _MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS = {'idp': 0.15}; min bucket n = 30 | `src/api/data_contract.py:4670-4690` | market anchor per asset class, confidence bucket | fractional drift · <=0.15 for IDP | F-001 step 10 — IDP rows only; offense is not clamped | contains raw blend drift — stated rationale ('contain the IDP calibration runaway') names a mechanism that no longer exists — the calibration post-pass and config/idp_calibration.json are gone | tests/api/ | **OK** |
| `F-027` | Two-way player boost | rankDerivedValue = max(offense value, alt-position-family value) for _TWO_WAY_PLAYERS = {'Travis Hunter': 'DB'} | `src/api/data_contract.py:5048-5054` | both position families' blended values | value points · 0-9999 | F-001 step 11 — a genuine post-blend override | a two-way player is worth the better of his two markets — hardcoded to exactly one name; a second two-way player needs a code edit | tests/api/ | **OK** |
| `F-028` | Rankings override delta | recompute F-001 with disabled sources filtered and overridden weights, emit only _DELTA_PLAYER_FIELDS keyed by displayName | `src/api/data_contract.py::build_rankings_delta_payload:9619` | siteOverrides map | value points · 0-9999 | POST /api/rankings/overrides?view=delta, frontend mergeRankingsDelta | ~4 MB -> ~1.25 MB uncompressed — every override-sensitive field is in _DELTA_PLAYER_FIELDS | tests/api/test_source_overrides.py::TestBuildRankingsDeltaPayload | **OK** |

#### 9.3.4 TE premium, IDP translation, and the league lens

| ID | Concept | Expression | file:lines | Inputs | Units · scale/range | Consumers | Rationale · assumptions | Tests | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `F-030` | TE premium (basis conversion) | convert_te_value(v, from_basis='base', to_basis='tepp') using KTC's measured uplift curve (1.209 at board top rising toward 2.05); no-op when from==to | `src/league_intel/te_premium.py::convert_te_value:355, tep_uplift:323` | TE row value, source basis | value points · multiplier 1.209..2.05 | F-001 step 5a; ktc/ktcSfTep exempt | ADR-015 docs/league-intelligence/DECISIONS.md; replaced a flat 1.15 — target basis is a CONSTANT, not the league's measured TE demand | tests/audit/test_formula_registry.py::test_te_conversion_double_count_guard_is_structural | **PARTIAL** |
| `F-031` | TE lift scale-ceiling guard | _te_lift_under_ceiling(v) — compresses lifted TE votes under 9999 without collapsing distinct votes | `src/api/data_contract.py (_te_lift_under_ceiling, ref at :6055)` | uncapped lifted TE vote | value points · <9999 | F-030 output | a naive clamp made three distinct Bowers votes identical | tests/audit/test_formula_registry.py::test_te_lift_cannot_collapse_distinct_votes | **OK** |
| `F-032` | TEP-native flat premium | TEP-native sources keep a flat 1.10 multiplier (only base<->tepp is measured) | `src/api/data_contract.py (TE stage)` | TE rows from TEP-native sources | value points · x1.10 | F-001 | no measurement exists for TEP-native -> TE++ — 1.10 is a prior, not a measurement | tests/api/ | **DUP** (dup-of F-030 (different math for the same concept, by source class)) |
| `F-033` | TEP multiplier derivation | _TEP_DERIVATION_SLOPE = 0.30, clamped to [1.0, 2.0] | `src/api/data_contract.py:5909-5911` | league TE scoring bonus | multiplier · 1.0..2.0 | F-001 TE stage | linear in the TE bonus | tests/api/ | **OK** (dup-of F-030) |
| `F-034` | IDP rank translation backbone | translate IDP source ranks onto the shared board ladder before Hill | `src/canonical/idp_backbone.py (341L)` | IDP source ranks | board rank · 1..N | F-001 | IDP sources publish disjoint populations — the IDP ladder is commensurable with offense | tests/canonical/ | **OK** |
| `F-035` | Cross-market comparability (KTC vs IDPTC) | median value ratio 1.000 (p10 0.888, p90 1.054) over 475 shared rows; both boards top out at 9999 so no rescaling is applied | `src/league_intel/cross_market.py (703L)` | ktcSfTep and idpTradeCalc boards | ratio · ~1.0 | src/trade/finder.py per-market gate | measured 2026-07-26 — the measured ratio holds forward | tests/league_intel/ | **OK** |
| `F-036` | League-adjusted valuation (the lens) | adjusted = consensus * total_factor where total_factor is the product of four axes: structural scarcity, scoring fit, reception fit, TE premium | `src/league_intel/adjustment.py::build_adjustment:408 (axes at :211,:261,:312,:371)` | this league's 12 rosters, exact scoring settings | unitless factor · clamped per axis | GET /api/valuation/league-adjusted, and every engine via valuation_mode | positional scarcity is leagueKey-scoped by necessity — the factor is a function of POSITION alone, so it composes against any board | tests/league_intel/test_publish.py, tests/api/test_valuation_mode_threading.py | **OK** |
| `F-037` | Overlay application | adjusted_rows() reprices EVERY row on a shallow copy; ranks re-derived with the same compact_ranks_and_tiers the pipeline uses | `src/league_intel/overlay.py::adjusted_rows:61, adjusted_contract:129` | factors + contract rows | value points · 0-9999 | server.py::_valuation_scoped_contract | serving only ranked rows measured 740 of 1093 — every 2026 pick vanished — latest_contract_data is a shared mutable global and must never be mutated | frontend/__tests__/valuation-overlay.test.js | **OK** |
| `F-038` | Adjusted-board backtest verdict | four framings over 572 players vs realized 2025 scoring: no difference detected, three of four lean negative | `scripts/backtest_adjusted_board.py, docs/adjusted-board-backtest.md` | realized 2025 scoring | correlation / rank metrics | the decision to keep the adjusted board a toggle, not the default | measured decision | - | **OK** |

#### 9.3.5 Replacement level

| ID | Concept | Expression | file:lines | Inputs | Units · scale/range | Consumers | Rationale · assumptions | Tests | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `F-040` | Replacement level (league-intel, value scale) | four thresholds per position — starter / bestBallStarter / roster / waiver — measured from what the exact optimizer actually starts across all rosters | `src/league_intel/replacement.py::compute_replacement_levels (672L)` | this league's rosters, rosValue point estimates, src.ros.lineup solver | dynasty board value points · 0-9999 | src/api/gameplan.py:129-132, src/roster_intel/{engine,profiles,targets,partner}.py | endogenous flex allocation, smoothed bands — KNOWN LIMITATION, self-documented: optimizes on season-long MEANS, so it understates flex demand for high-variance positions (FLEX TE share 0.0% projected vs 10.4% measured on 2025 weekly actuals) | tests/league_intel/ | **DUP** (dup-of F-041, F-042, F-043 — four separate answers to 'replacement level') |
| `F-041` | Replacement level (scoring, points-per-game) | replacement_per_game = mean per-game pace of the FIVE players ranked just below the league's starter cutoff; vorp = points - replacement * games | `src/scoring/replacement_level.py::replacement_per_game, vorp_table (237L)` | PlayerSeasonRow(points, games) from any source; Sleeper roster_positions | fantasy points per game · PPG | src/public_league/awards.py (League MVP / Playoff MVP), IDP scoring-fit pipeline | lifted out of awards.py to be reusable — FLEX splits 1/3 each, SUPER_FLEX 1/4 each, IDP_FLEX 1/3 each — a PREASSIGNED split, the opposite convention to F-040's endogenous one | tests/scoring/ | **DUP** (dup-of F-040, F-042, F-043) |
| `F-042` | Replacement level (BDVM, dynamic flex-aware) | R_g = FPG at rank [league-wide flex-allocated startable slots at g + waiver buffer]; greedy flex allocation, deterministic tie-break on group name | `src/bdvm/replacement.py::ReplacementEngine (155L)` | per-group rank->FPG pools, BdvmLeagueConfig | fantasy points per game · PPG | src/bdvm/engine.py, /api/bdvm/* | replacement does ALL positional-scarcity work in BDVM — no multipliers exist — raises ReplacementUnavailableError rather than fabricating R=0 — the strictest of the four | tests/bdvm/ | **DUP** (dup-of F-040, F-041, F-043) |
| `F-043` | Replacement level (league comparison) | replacement_level = the Nth player's points (e.g. QB24); replacement_adj = average - replacement_level | `src/league_comparison/metrics.py:95-97, :164, :172-174` | top-N points arrays per position | season fantasy points · points | /api/league-comparison, /league-comparison page | measures replacement-end compression between scoring systems — a single rank, not a smoothed band — the exact thing F-040's docstring argues against ('hostage to one player's projection') | tests/league_comparison/ | **DUP** (dup-of F-040, F-041, F-042) |

#### 9.3.6 Lineup solving and team value

| ID | Concept | Expression | file:lines | Inputs | Units · scale/range | Consumers | Rationale · assumptions | Tests | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `F-050` | Best-ball lineup optimizer (backend) | exact best-projected-lineup solve over slot tokens with flex eligibility | `src/ros/lineup.py (516L)` | RosterPlayer pool, league starter slots | ROS points · points | src/roster_intel/marginal.py, src/league_intel/replacement.py, src/api/gameplan.py | the one exact optimizer — point estimates, not weekly spikes | tests/ros/ | **OK** |
| `F-051` | Marginal best-ball contribution | marginal(pos) = S(full) - S(full minus every player at this position); optimal_score(pool, slots) = solve_summary(...).score | `src/roster_intel/marginal.py:136-138 (347L)` | roster pool + slots | ROS points · points | src/roster_intel/{engine,profiles,window}.py, /api/gameplan | THE lineup-constrained team-value definition — leave-one-position-out is the right marginal | tests/roster_intel/ | **OK** (dup-of F-052, F-053 (three legitimately different 'team value' concepts)) |
| `F-052` | Team value (frontend simple sum) | totalValue = sum(player meta values) + sum(resolved pick values) | `frontend/lib/league-analysis.js::buildTeamValueBreakdown` | contract rows + Sleeper team rosters | board value points · 0-9999 summed | /rosters | documented divergence — a portfolio total, not a lineup value | frontend/__tests__/ | **DUP** (dup-of F-051, F-053) |
| `F-053` | Team value (terminal simple sum, picks excluded) | totalValue = sum(p['value'] for p in rosterValues) — EXCLUDES picks | `src/api/terminal.py:1070 (comment at :1204-1221)` | contract rows for the roster | board value points · 0-9999 summed | GET /api/terminal, / (home terminal) | self-documented: 442,936 of pick value vs 1,524,591 of player value on the live snapshot — 22.5% of a portfolio | tests/api/ | **DUP** (dup-of F-051, F-052) |
| `F-054` | Team ROS strength composite | 0.72*starting_lineup_strength + 0.18*best_ball_depth_strength + 0.05*positional_coverage + 0.05*health_availability | `src/ros/team_strength.py:33-36 (269L)` | aggregated ROS player values, league starter slots | composite · 0..1 scaled | GET /api/ros/team-strength, rosPower (F-062), rosPlayoffOdds (F-071), trade-deadline direction (F-081) | spec-defined defaults, hardcoded in PR1 — weights are a prior; the module says they 'can be overridden per-league later' | tests/ros/ | **OK** |
| `F-055` | Lineup fill (frontend) | fillLineup({assets, rosterPositions, positionOf, valueFor}) — greedy slot fill, live host rosterPositions first, registry second, never a literal | `frontend/lib/starter-slots.js` | team roster + sleeper.rosterPositions | board value points · 0-9999 | frontend/lib/league-analysis.js (/rosters), frontend/lib/portfolio-insights.js (/terminal) | consolidated SIX answers, two of which were wrong (audit 2026-07-30) | frontend/__tests__/ | **OK** |
| `F-056` | Roster strength tier score | score = starterValue*0.7 + depthValue*0.2 - pickValue*0.1; tier = top third contender / bottom third rebuilder / middle | `frontend/lib/league-analysis.js:1131-1152` | filled lineup + depth + pick capital | board value points · 0-9999 weighted | /rosters | picks penalized at -10% as a rebuild signal — a tercile split forces exactly 4/4/4 in a 12-team league regardless of spread | frontend/__tests__/ | **DUP** (dup-of F-051, F-054) |

#### 9.3.7 Starter slots and positional need

| ID | Concept | Expression | file:lines | Inputs | Units · scale/range | Consumers | Rationale · assumptions | Tests | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `F-060` | Starter slots (canonical) | config/leagues/registry.json rosterSettings.starters, resolved via src/api/league_registry.py; live sleeper.rosterPositions takes precedence | `config/leagues/registry.json; src/api/league_registry.py` | leagueKey | slot counts · integers | F-055, F-050, F-061, src/bdvm/league_config.py | leagueKey-scoped per CLAUDE.md — operator-maintained and known to drift — hence the live-host precedence rule | tests/api/test_league_registry.py | **OK** |
| `F-061` | Positional need / demand model (trade suggestions) | starter_needs_for_league(key) derives base slots + flex allocation in RB->WR->TE order; dynasty_main {QB2 RB3 WR4 TE2 DL3 LB3 DB3}, dynasty_new {QB2 RB3 WR4 TE1} | `src/trade/suggestions.py:39-58, :64-146` | registry rosterSettings | starter demand counts · integers | POST /api/trade/suggestions | a demand model, not a slot count — superflex wants a second startable QB — the derivation reproduces the old hardcoded constant for dynasty_main | tests/trade/ | **DEFECT** |
| `F-062` | Position need deficit (roster intel) | deficit = replacement-level occupant's contribution - actual contribution; positive means acquire a starter | `src/roster_intel/engine.py::position_needs:137-173` | F-051 marginals + F-040 replacement levels | ROS points · points | /api/gameplan | answers 'am I below replacement here' in lineup-points, not board value — needs F-040 supplied; without it tiers default to developmental | tests/roster_intel/ | **DUP** (dup-of F-061 (different units entirely: points vs slot counts)) |
| `F-063` | Positional scarcity delta (team impact) | per-position starter-vs-replacement scarcity delta for a proposed trade | `src/trade/team_impact.py:476 (516L)` | roster before/after, replacement levels | value points · 0-9999 | POST /api/trade/simulate | — | tests/trade/ | **OK** (dup-of F-062) |

#### 9.3.8 Team classification

| ID | Concept | Expression | file:lines | Inputs | Units · scale/range | Consumers | Rationale · assumptions | Tests | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `F-070` | Team phase (frontend, value x age) | isHighValue = totalValue(top 25) > league median; isYounger = medianAge < league median; high+young=Win-now, high+old=Contender, low+young=Rebuild, else Mixed | `frontend/lib/team-phase.js::classifyPhase:79-92` | rankDerivedValue + age from contract rows, sleeper.teams | labels · 4 categories | /phases | median split forces ~50/50 on each axis regardless of spread | frontend/__tests__/ | **DUP** (dup-of F-071..F-075 — SIX classifiers of the same concept (prior audit claimed three)) |
| `F-071` | Team direction (ROS, 7 labels) | Strong Buyer if playoff>=0.75 AND champ>=0.10; Buyer >=0.60/>=0.05; Selective Buyer 0.45-0.60; Hold 0.35-0.55; Selective Seller 0.20-0.40; Seller <0.25 AND <0.02; Strong Seller <0.10 AND <0.01 AND age-heavy (vetCount>=4) | `src/ros/direction.py::classify_team:53-... (162L)` | F-072 playoff odds, F-076 championship odds, F-054 strength, position-aware veteran ages (QB32 RB26 WR29 TE30 DL30 LB29 DB29) | labels · 7 categories | /api/public/league/rosTradeDeadline, /league trade-deadline tab | spec mapping with deliberately overlapping bands, resolved strongest-first — consumes the odds engine that returns hard 0/1 in preseason (F-072) | tests/ros/ | **DUP** (dup-of F-070, F-072..F-075) |
| `F-072` | Competitive window (5-state softmax) | affinity = -(2.0*(comp - c_anchor)^2 + 1.0*(traj - t_anchor)^2); softmax at temperature 0.18 over 5 anchors | `src/roster_intel/window.py:85-104, :285-300 (compute_window)` | championship-odds percentile (or lineup-score percentile), value-weighted lineup age mapped on [22,32] | probabilities · 5 states summing to 1 | /api/gameplan | softmax rather than thresholds — 'a team one point either side of a cut flips category while its neighbour does not move at all' — ORDERING_CAVEAT: retool vs productive_struggle ordering is explicitly soft | tests/roster_intel/ | **DUP** (dup-of F-070, F-071, F-073..F-075) |
| `F-073` | BDVM direction (capital ratio, league-relative) | rel = (contender_capital/rebuilder_capital) / league median ratio; rel > _CONTEND_RATIO -> contend, rel < _REBUILD_RATIO -> rebuild, else retool | `src/bdvm/roster.py::_directions_relative:63-92, strategy_for_direction:94-95` | BDVM strategy capitals | labels · 3 categories | /api/bdvm/roster, /bdvm | the absolute rule (ratio vs 1.15) saturated — all twelve rosters read 'contend' — documented judgment call; the absolute ratio is still exposed per roster | tests/bdvm/ | **DUP** (dup-of F-070..F-072, F-074, F-075) |
| `F-074` | Player-level strategy tag | rookie or years_exp<=2 -> 'rebuilder'; years_exp>=8 -> 'contender'; else 'neutral' | `src/trade/suggestions.py::_strategy_for_player:803-808` | rookie flag, years_exp | labels · 3 categories | POST /api/trade/suggestions | years_exp is a proxy for age; a 24-year-old 3rd-year WR reads 'neutral' | tests/trade/ | **DUP** (dup-of F-070..F-073, F-075) |
| `F-075` | Roster tier (tercile) | sort by F-056 score; top ceil(n/3) contender, bottom third rebuilder, rest middle | `frontend/lib/league-analysis.js:1146-1152` | F-056 score | labels · 3 categories | /rosters | forces a fixed 4/4/4 split in a 12-team league | frontend/__tests__/ | **DUP** (dup-of F-070..F-074) |

#### 9.3.9 Playoff odds, championship odds, luck

| ID | Concept | Expression | file:lines | Inputs | Units · scale/range | Consumers | Rationale · assumptions | Tests | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `F-080` | Playoff odds v1 (empirical Monte Carlo) | sample each owner's future weekly score from their own empirical scored-week distribution; 10,000 sims; top playoff_spots by (wins, PF) | `src/public_league/playoff_odds.py (build_section)` | PublicLeagueSnapshot weekly scores + posted/inferred schedule | probability · 0..1 | GET /api/public/league/playoffOdds, /league Playoff Odds tab | self-contained, no modelling library, every input explicit — an owner with <2 scored weeks falls back to the league-wide distribution | tests/public_league/ | **DEFECT** (dup-of F-081 (measured live: 7 playoff spots vs 6, 12 owners vs 8, contradicts on 2 teams)) |
| `F-081` | Playoff odds v2 (ROS-blended Monte Carlo) | shifted_mean = empirical_mean * (1 + ROS_BLEND*(ros_strength_z - 1)) with ROS_BLEND=0.20; sd *= 1.10 best-ball variance bump (depth_aware); 2000 sims | `src/ros/playoff_sim.py (1074L; reuses playoff_odds._season_weekly_scores:468 and _posted_future_matchups:550)` | F-054 team strength + empirical distribution + PointsModel | probability · 0..1 | GET /api/public/league/rosPlayoffOdds, /league (settings.useRosPlayoffOdds defaults TRUE) | 'when ROS data is available it provides a forward-looking signal pure history cannot capture' — pointsModelSource == 'fallback-constants' live — no fitted points model exists | tests/ros/ | **DEFECT** (dup-of F-080) |
| `F-082` | Championship odds (ROS bracket MC) | bracket simulation over F-081 seeds; 10,000 sims; emits championship / finals / semifinal odds + contenderTier | `src/ros/championship.py (304L)` | F-081 seed distribution, F-054 | probability · 0..1 | GET /api/public/league/rosChampionship, F-071, F-072 | no v1 equivalent — inherits F-081's degeneracy: live payload shows Roy at playoffOdds 1.0 and championshipOdds 0.0 | tests/ros/ | **DEFECT** |
| `F-083` | Expected wins / luck score | expected wins from all-play win share vs actual wins | `src/public_league/luck.py (378L)` | weekly scores across the league | wins · 0..games | /league Luck tab, F-062 luck_regression component | — | tests/public_league/ | **OK** |

#### 9.3.10 Power rankings

| ID | Concept | Expression | file:lines | Inputs | Units · scale/range | Consumers | Rationale · assumptions | Tests | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `F-090` | Power ranking v1 | power = 100 * (0.50*PPG percentile + 0.25*last-3-game avg percentile + 0.25*all-play win share) | `src/public_league/power.py:45-47, :141` | weekly scored results, per-week active owners | power score · 0..100 | GET /api/public/league/power, /league Power tab | percentiles normalized within each week's active owners — requires scored games; with none it falls back to the last scored season | tests/public_league/ | **DUP** (dup-of F-091) |
| `F-091` | Power ranking v2 (ROS) | weighted sum of 9 components: team_ros_strength .38, ppg .18, recent .12, wl_record .10, all_play .08, streak .05, schedule_adjusted .04, roster_health .03, luck_regression .02; missing components dropped and weights renormalized | `src/ros/power_v2.py:65-75, :99-108 (524L)` | F-054 + season results | power score · 0..100 | GET /api/public/league/rosPower, /league Power tab when settings.useRosPowerRankings (defaults TRUE) | 'coexists with the existing power section; the frontend swaps between them' — in preseason 7 of 9 weights are missing — the live payload runs on team_ros_strength .38 + roster_health .03 only | tests/ros/ | **DUP** (dup-of F-090) |

#### 9.3.11 Percentile helpers

| ID | Concept | Expression | file:lines | Inputs | Units · scale/range | Consumers | Rationale · assumptions | Tests | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `F-100` | Percentile helper (public_league/power) | (below + (equal-1)*0.5) / (n-1); returns 0.5 when n<=1 | `src/public_league/power.py::_percentile_rank:52-61` | population, target | percentile · 0.0 .. 1.0 inclusive | F-090 | midrank tiebreak — reaches a literal 0.0 and 1.0 — the league minimum scores zero | tests/public_league/ | **DUP** (dup-of F-101..F-104) |
| `F-101` | Percentile helper (sharp/score) | (below + 0.5*equal) / n; returns 0.5 on an empty population | `src/sharp/score.py::percentile_rank:191-203` | population, value | percentile · 0.5/n .. (n-0.5)/n | the 0.85 sharp qualification bar (F-110) | 'an all-identical population carries no information and must not read as universally elite' — can never return 0.0 or 1.0 — at n=12 the extremes are 0.0417 and 0.9583 | tests/sharp/ | **DUP** (dup-of F-100, F-102..F-104) |
| `F-102` | Percentile helper (ros/power_v2) | (below + 0.5*same) / len(eligible); returns 0.0 on an empty population | `src/ros/power_v2.py::_percentile:99-108` | population, target | percentile · 0.0 or 0.5/n .. (n-0.5)/n | F-091 | an UNMEASURABLE percentile returns 0.0 (worst in league), where F-100 and F-101 return 0.5 (neutral) | tests/ros/ | **DUP** (dup-of F-100, F-101, F-103, F-104) |
| `F-103` | Percentile helper (roster_intel/window, inline x2) | (below + 0.5*ties) / len(pop) — written out twice inline, not extracted | `src/roster_intel/window.py:228-231 and :238-241` | championship odds map, or lineup scores map | percentile · 0.5/n..(n-0.5)/n | F-072 competitiveness axis | identical to F-101 but duplicated inline rather than imported | tests/roster_intel/ | **DUP** (dup-of F-101) |
| `F-104` | Elite threshold index (roster_intel/profiles) | vals[max(0, round(len(vals) * ELITE_PERCENTILE) - 1)] — banker's rounding index, not a percentile rank | `src/roster_intel/profiles.py:86-89` | position value pool | value point · a pool element | F-062 player tiering | 'elite is a distribution percentile, not a replacement level' — round() is banker's rounding, so the index steps non-monotonically with n | tests/roster_intel/ | **DUP** (dup-of F-100..F-103) |

#### 9.3.12 Trade math

| ID | Concept | Expression | file:lines | Inputs | Units · scale/range | Consumers | Rationale · assumptions | Tests | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `F-110` | KTC Value Adjustment (JS original) | ktcProcessV / ktcReverseAdjust / ktcAdjustPackage — verbatim port of KTC's site.min.js; MAX 10000, T reference 10041, variance 5% | `frontend/lib/trade-logic.js::ktcAdjustPackage` | two arrays of raw values | value points · 0-10000 | /trade TradeMeter | the calculator the users compare against | frontend/__tests__/ | **OK** |
| `F-111` | KTC VA (Python port A) | same algorithm; rounds with Python round() at :116 (ktc_reverse_adjust) and :319 (final value) — BANKER'S ROUNDING | `src/trade/ktc_va.py:116, :146-319, adjusted_pair_totals:322-349` | two value lists | value points · 0-10000 | src/trade/suggestions.py:27, src/trade/angle.py:98, src/trade/monte_carlo.py:153 | 'so /api/angle/find and suggestions do not grade with the legacy V2 formula' — the +/-1 tolerance in its own parity test is exactly the size of the defect it would otherwise catch | tests/trade/test_ktc_va_python_port.py (asserts agreement to +/-1) | **DUP** (dup-of F-110, F-112, F-113 — measured 38/20000 divergences vs F-112, max \|diff\| 1) |
| `F-112` | KTC VA (Python port B) | same algorithm; rounds with _js_round = floor(x+0.5) at :136, :144, :386 | `src/trade/market_value_adjustment.py:33-36, :183-386` | two value lists | value points · 0-10000 | src/trade/finder_value_adjustment.py:16 (installed onto the finder by src/trade/__init__.py:9) | 'line-for-line Python port of the authoritative frontend implementation' | tests/trade/test_finder_value_adjustment.py | **DUP** (dup-of F-110, F-111, F-113) |
| `F-113` | KTC VA (Python port C) | same algorithm; _js_round = floor(x+0.5) at :103-112, :188, :197, :387 | `src/public_league/trade_grading.py:103-112, :225-387` | two value lists | value points · 0-10000 | src/public_league/trade_grading.py:400 (public-league trade grades) | docstring explicitly names the Python-round bug that F-111 still has | tests/fixtures/trade_grade_parity_cases.json | **DUP** (dup-of F-110, F-111, F-112) |
| `F-114` | Trade letter grade | pct thresholds 3 / 8 / 15 / 25 / 40 -> A(fair) A(slight) A A A+ ... down to F | `src/public_league/trade_grading.py:48-76; frontend/lib/league-analysis.js:87-92` | VA-adjusted side totals | letter · A+ .. F | /league Activity tab (Python), /rosters (JS) | registry claims parity pinned by tests/fixtures/trade_grade_parity_cases.json — the JS copy re-states the thresholds as literals rather than importing them | tests/public_league/test_trade_grading.py + the shared fixture | **OK** |
| `F-115` | Trade fairness label (suggestions) | \|gap\| < 256 -> even; < 769 -> lean; else stretch | `src/trade/suggestions.py::_fairness_label:794-801` | VA-adjusted gap | label · 3 categories | POST /api/trade/suggestions | absolute point thresholds on a 0-9999 scale — a 256 gap means something different at the top of the board than at the bottom | tests/trade/ | **DUP** (dup-of F-114 (percentage-based)) |
| `F-116` | Trade Monte Carlo win probability | correlated draws (same_team_rho / same_pos_group_rho scalars) -> winProbA, meanDelta; symmetrized by averaging both directions | `src/trade/monte_carlo.py (387L); src/trade/symmetrize.py (229L)` | per-asset p10/p50/p90 | probability · 0..1 | POST /api/trade/simulate-mc, /trade | 'sim(A,B).winProbA == 1 - sim(B,A).winProbA' enforced by averaging — uniform rho scalars under-capture reality (F-117 is the unused alternative) | tests/trade/ | **OK** |
| `F-117` | Correlation matrix (MC alternative) | rule ladder 1.00/0.55/0.35/0.25/0.15/0.00, ceiling max_rho 0.85, Cholesky-decomposed | `src/trade/correlation_matrix.py (170L)` | player team + position | correlation · 0..0.85 | NONE in production — no caller outside tests | 'an alternative to the two-scalar model' the sampler can consume | tests/trade/ | **SCAFFOLD** (dup-of F-116) |
| `F-118` | Consolidation suggestion | min_target = combined * CONSOLIDATION_MIN_UPGRADE_RATIO (0.70); stretch kept if VA-adjusted gap / give_total <= 0.30 | `src/trade/suggestions.py:167-170, :1146-1212, :1429-1446` | surplus players, target pool | value points · 0-9999 | POST /api/trade/suggestions, /trade | 'prevents consolidation from showing 6 different pairs all targeting Bijan' — 0.70 and 0.30 are priors | tests/trade/ | **OK** (dup-of F-119) |
| `F-119` | Consolidation pricing (BDVM) | package_value = (Sum v^theta)^(1/theta) - roster_spot_cost * overflow; theta > 1 prices consolidation | `src/bdvm/trade_math.py:4, :35-38 (91L)` | per-asset strategy values, theta, C_spot | fundamental value · model-scaled | POST /api/bdvm/trade-eval, GET /api/bdvm/trades | BDVM section 3.13 — a CES aggregator, never a plain sum — theta and C_spot are labelled priors in config/bdvm/params_v1.json | tests/bdvm/test_trade_eval.py | **DUP** (dup-of F-118 (same concept, incompatible math and units)) |
| `F-120` | Roster-spot cost | spot_cost * overflow, subtracted from the CES core | `src/bdvm/trade_math.py:35-38` | config/bdvm/params_v1.json roster_spot_cost | fundamental value · model-scaled | F-119 | the ONLY roster-spot cost in the tree — a prior, not a measurement; absent path: data/bdvm/ | tests/bdvm/ | **BLOCKED** |
| `F-121` | Trade acceptance estimate | trade_acceptance_estimate + acceptanceConfidence, capped below 1.0 while no rejection data exists | `src/roster_intel/partner.py:174-182, :445-478 (see also :15-28)` | completed trades (activity), roster fit, window alignment | plausibility · 0..1, ceiling < 1 | /api/gameplan packages.frontier[].acceptancePlausibility | 'Sleeper records only the numerator (accepted trades) and never the denominator -> an acceptance RATE is statistically unidentifiable' — explicitly never renamed to 'probability'; ships with acceptanceCaveat attached | tests/roster_intel/ | **OK** |
| `F-122` | Arbitrage edge (finder) | board value (rankDerivedValue) vs per-market retail anchor; gate MARKET_TOP_N_FILTER=150 ranked WITHIN each market (ktcSfTep offense+picks, idpTradeCalc IDP) | `src/trade/finder.py:111, :181, :245 (board_values_from_contract)` | canonical board + retail boards | value points · 0-9999 | POST /api/trade/finder, /arbitrage | 'the market number is load-bearing in its arithmetic' — assets the board declines to price are counted in metadata.assetsUnpricedByBoard (202 on a real payload), never dropped silently | tests/test_trade_finder.py | **OK** (dup-of F-123 (deliberately different GATE, same value)) |
| `F-123` | Board quality gate (suggestions) | BOARD_TOP_N_FILTER = 150 against OUR blended board (display_value order) | `src/trade/suggestions.py (_assign_board_ranks)` | canonical board | rank ordinal · 1..150 | POST /api/trade/suggestions | 'suggestions only needs an asset-quality gate, which our own board answers for IDP and picks no retail board covers' | tests/trade/ | **OK** (dup-of F-122 (deliberate divergence)) |

#### 9.3.13 Buy / Sell / Hold and waiver tiers

| ID | Concept | Expression | file:lines | Inputs | Units · scale/range | Consumers | Rationale · assumptions | Tests | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `F-130` | Buy/Sell/Hold (terminal, Python) | priority-ordered boolean rule ladder; highest-priority firing rule owns the signal; default HOLD | `src/api/terminal.py::_evaluate_signal:875` | trend7, trend30, volatility MAD, value, news impact counts | labels · RISK/SELL/MONITOR/STRONG_HOLD/BUY/HOLD | GET /api/terminal, / (home) | shared rule table | tests/api/test_signal_engine_parity.py | **OK** (dup-of F-131 (parity-pinned)) |
| `F-131` | Buy/Sell/Hold (frontend, JS) | same rule ladder, same priorities, same tags | `frontend/lib/signal-engine.js::evaluate (RULES from :47)` | same context object | labels · same 6 | /rankings, /terminal components | — | frontend/__tests__/signal-engine-parity.test.js | **OK** (dup-of F-130) |
| `F-132` | Unified signal engine (news/usage/injury/transaction) | verdict BUY/SELL/HOLD + confidence 0..1 + severity low/medium/high, combining value movement, usage z-scores, injury diffs, transaction activity | `src/news/unified_signal_engine.py` | rank drift, snap/target/carry share z, injury feed diff, league transactions | verdict + confidence · 3 labels, confidence 0..1 | signal alerts sweep | 'single entry point for every BUY/SELL/HOLD decision emitted to users' — the claim of being the single entry point is false — F-130/F-131, F-133, F-134 and F-135 all emit their own | tests/news/ | **DUP** (dup-of F-130, F-131, F-133, F-134, F-135) |
| `F-133` | BDVM market signal | alpha = fundamental - market; STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL / NO_MARKET by alpha bands and market liquidity | `src/bdvm/market.py:307-351` | F-003 fundamental value, value-signal sources only | labels · 6 categories | /api/bdvm/values, /bdvm, /rankings Fund-gap tint, src/api/bdvm_signal_alerts.py | 'appending BDVM labels to the terminal detector's set would merge two different vocabularies' — NO_MARKET is an absence and is never alerted on; absent path: data/bdvm/ | tests/bdvm/, tests/api/test_bdvm_signal_alerts.py | **BLOCKED** (dup-of F-130..F-132) |
| `F-134` | Consensus edge composite | score = 100 * Sum(w_i * c_i) / Sum(w_i) over PRESENT components only (absent components dropped and weights renormalized); label Strong Buy at >= 60 (config strongBuy) | `src/consensus_edge/score.py:34, :155-... , :326-333` | mispricing, fair value, opportunity, sharp flow components | score · -100..100 | GET /api/consensus-edge/*, /consensus-edge | 'an opportunity signal on its own says nothing about mispricing — calling that a Buy would be a category error' (score None without a core component) — feature flag consensus_edge defaults off per ADR-023 | tests/consensus_edge/ | **DISCONNECTED** (dup-of F-130..F-133, F-135) |
| `F-135` | Sharp buy/sell tracker | net add/drop movement across the sharp cohort, per window | `src/sharp/market.py (459L)` | F-140 cohort, normalized platform movements | counts / net · signed integers | GET /api/sharp/market, /market/sharp-tracker | cohort resolved through src/sharp/cohort.py::cohort_members — never a second list | tests/sharp/ | **OK** (dup-of F-130..F-134) |
| `F-136` | Waiver upgrade tier | gap thresholds -> smash / strong / considering; drop confidence classified by the gap to the BEST replacement | `frontend/lib/waiver-logic.js:43-58, :261-263, :268-302, :631-641` | board values of roster player vs best addable FA | value points · 0-9999 gap | /waivers | '2000+ gap means dropping this player nets a starter-tier replacement' — absolute point thresholds on a relative scale | frontend/__tests__/ | **OK** |

#### 9.3.14 Sharp cohort

| ID | Concept | Expression | file:lines | Inputs | Units · scale/range | Consumers | Rationale · assumptions | Tests | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `F-140` | Sharp score | weighted components (win rate, championship rate beta-binomial shrunk, consistency = SHARE of leagues above median, confidence) minus an explicit uncertainty penalty; percentile-normalized within the observed population; qualification bar is itself a percentile (0.85) | `src/sharp/score.py (+ config/sharp/scoring_v2.json)` | src/sharp/platform_records.py evidence; dynasty leagues >= 2 seasons only | score + confidence · 0..1 each | src/sharp/cohort.py::cohort_members -> F-135, F-141, roster_collect, scripts/crawl_sharp_activity.py | docs/intel/SHARP_SCORE.md; every weight lives in config, nothing hardcoded — score and confidence are SEPARATE outputs; a manager must clear BOTH bars | tests/sharp/ | **OK** |
| `F-141` | Sharp roster percentage | unique eligible sharp rosters containing the player / total eligible sharp rosters that COULD contain him (denominator computed PER PLAYER by position family and league format) | `src/sharp/roster_percentage.py` | sharp_rosters / sharp_roster_assets tables, F-140 cohort | percentage · 0..1 | GET /api/sharp/roster-percentage, /market/sharp-roster-percentage | docs/sharp-roster-percentage/METHODOLOGY.md — rosters, not people, are the denominator; formatUnknownRosters is reported rather than silently assumed | tests/sharp/ | **OK** |
| `F-142` | Super sharp score | - | `-` | - | — | - | no such construct exists anywhere in the tree (grep 'super.?sharp' over *.py *.js *.jsx *.md *.json returns nothing) | - | **MISSING** |

#### 9.3.15 Activity and movers

| ID | Concept | Expression | file:lines | Inputs | Units · scale/range | Consumers | Rationale · assumptions | Tests | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `F-150` | Transaction activity ranking | per-window indexed queries; the board sorts on SINGLE-WINDOW volume | `src/intel/service.py (818L)` | platform ledger transactions | counts · integers | GET /api/intel/*, /league/insider-trading | replaced a nested-window sum — absent paths: data/intel/ and the platform ledger DB | tests/audit/test_formula_registry.py::test_nested_windows_are_not_summed_into_the_board_ranking | **BLOCKED** |
| `F-151` | Trade activity alpha (public league) | REPLACED — used to be sum(max(value,1) ** 1.65) per side | `src/public_league/activity.py:47-50 (comment only; the math is gone)` | - | — | - | 'raising to 1.65 inflates a gap — a 10% linear edge is a ~16% alpha' | tests/public_league/ | **DEPRECATED** (dup-of F-114 (replaced by it)) |
| `F-152` | Movement indicators (ticker) | use the contract's stamped rankChange verbatim; null or 0 is 'quiet' and excluded from the ticker | `frontend/lib/market-movers.js` | rankChange stamped per scrape | rank delta · signed integer | / terminal ticker | 'a real per-scrape delta — we use it verbatim rather than recomputing' | frontend/__tests__/ | **OK** (dup-of F-153) |
| `F-153` | Movement indicators (/trending) | computeWindowTrend over rank_history for 1d / 7d / 30d windows; positive rankChange means improved (toward rank #1) | `frontend/lib/movers.js (WINDOW_OPTIONS :19)` | contract rows + rankHistory | rank delta · signed integer | /trending | different window semantics from F-152 (per-scrape delta vs windowed trend) for the same word 'mover' | frontend/__tests__/ | **DUP** (dup-of F-152) |

#### 9.3.16 FAAB

| ID | Concept | Expression | file:lines | Inputs | Units · scale/range | Consumers | Rationale · assumptions | Tests | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `F-160` | FAAB bid recommendation (canonical) | _compute_faab_bid -> (aggressive, reasonable, lowball) as a share of remaining budget scaled by the value gap | `src/trade/waiver.py::_compute_faab_bid:97-103` | player value, roster gap, faab remaining (default 100) | budget % · 0..100 | POST /api/waiver/faab-recommend, /waivers | formula-registry faab-bid | tests/fixtures/faab_bid_parity_cases.json | **OK** (dup-of F-161 (parity port)) |
| `F-161` | FAAB bid (JS parity port) | computeFaabHint — JS port of _compute_faab_bid with roundHalfUp | `frontend/lib/waiver-logic.js:851-873` | same | budget % · 0..100 | /waivers | — | same fixture | **OK** (dup-of F-160) |
| `F-162` | FAAB recommendation (per-pair, v2) | layers on top of F-160: league historical position bids, league median winning bid, KTC crowd bid map, sleeper trending count | `src/trade/faab_recommender.py:43, :187-273, :312 (701L)` | F-160 baseline + F-163 league summary + adapters/ktc_crowd_faab | budget % · 0..100 | POST /api/waiver/faab-recommend | — | tests/trade/ | **OK** (dup-of F-160) |
| `F-163` | League FAAB analytics | summarize_league_faab — walks every season's waiver transactions for settings.waiver_bid, emits median + per-position winning bids | `src/api/faab_analytics.py:188 (331L)` | public-league snapshot transactions | budget % · 0..100 | GET /api/public/league/faabAnalytics -> F-162 | lazy because the walk is O(seasons x weeks) | tests/api/ | **OK** |
| `F-164` | FAAB contention (rival bid estimation) | exp_bid = min(exp_bid, opponent.faabRemaining) per opponent | `src/trade/faab_contention.py:15, :335 (497L)` | opponent rosters, needs, faab remaining | budget % · 0..100 | POST /api/waiver/faab-recommend perOpponent block | FAAB v2 | tests/trade/ | **OK** (dup-of F-162) |

#### 9.3.17 Picks and the draft board

| ID | Concept | Expression | file:lines | Inputs | Units · scale/range | Consumers | Rationale · assumptions | Tests | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `F-170` | Pick value (canonical) | blend -> multiplicative future-year discount (Phase 3a, BEFORE the sort) -> sort -> current-year slot picks tethered to the merged rookie pool (Phase 5.2b, OVERWRITES rankDerivedValue) | `src/api/data_contract.py (pick stages; _PICK_SLOT_RE:4284, discount cache:4295)` | config/weights/pick_year_discount.json, merged offense+IDP rookie pool | value points · 0-9999 | /api/data, /draft, every trade engine | CLAUDE.md 'Live Value Pipeline' steps 12-13 (corrected 2026-07-29) — a tethered current-year pick never carries a discount (year offset 0 -> 1.0) | tests/api/ | **OK** (dup-of F-171, F-172, F-173) |
| `F-171` | Pick value (Sleeper-derived fallback) | _pick_value_from_contract returns None on a miss; unpriced picks are EXCLUDED from the $1200 dollar normalization and emitted with dollarValue null + isUnpriced true | `src/api/draft_capital_fallback.py` | that league's own Sleeper rosters + traded picks, contract pick values | auction dollars · $1200 pool | GET /api/draft-capital (non-default league) | the flat 7000/4000/2000/1200-by-round table was REMOVED (audit finding C1) — coveredPickYears is derived from what was actually priced, not the loop bounds | tests/api/test_draft_capital_fallback.py, tests/api/test_draft_capital_data_not_ready.py | **OK** (dup-of F-170) |
| `F-172` | Pick value (legacy calibration curve) | _pick_curve_value(info, current_year) — a pick curve inside the retired canonical calibration path | `src/canonical/calibration.py:159, called only from :356 inside the same module` | pick name + year | value points · 0-9999 | NONE — zero production references (verified by symbol scan over src/, server.py, scripts/) | legacy | tests/canonical/test_calibration.py | **SCAFFOLD** (dup-of F-170) |
| `F-173` | Pick value (BDVM outcome EV) | pick value = EV over an outcome distribution (hit% / median / ceiling) per draft slot | `src/bdvm/picks.py (125L), config/bdvm pick outcomes` | draft-slot priors | fundamental value · model-scaled | /api/bdvm/values pick rows, /draft 'Fundamental pick values (BDVM)' panel | BDVM section 5.12 / prompt section 9 — a fundamental concept, not a market one — the module itself calls these 'placeholder priors'; absent path: data/bdvm/ | tests/bdvm/ | **BLOCKED** (dup-of F-170) |
| `F-174` | Pick projector (future pick -> slot) | future-pick -> projected-draft-slot mapping from ROS standings projection | `src/ros/pick_projection.py (252L)` | F-081 projected standings | draft slot · 1.01..6.12 | GET /api/ros/pick-projections | inherits F-081's preseason degeneracy | tests/ros/ | **OK** |
| `F-175` | Rookie anchor | _ROOKIE_ANCHOR_LEAGUE_SIZE_DEFAULT = 12, _ROOKIE_ANCHOR_ROUNDS = 6 | `src/api/data_contract.py:5885-5886` | rookie source ladders | rank ordinal · 72 slots | F-170 tethering | hardcoded 12-team / 6-round; dynasty_new is a 10-team league | tests/api/ | **OK** |
| `F-176` | Draft auction power | effective auction power — relative draft-capital concentration lens | `src/api/auction_power.py (170L); frontend/lib/auction-power.js` | per-team pick dollar values | auction dollars · $1200 pool | GET /api/draft-capital, /draft | — | tests/api/ | **OK** |
| `F-177` | Draft board tiering | {key: 'A', label: 'Starter', min: 25} ... letter buckets by value threshold | `frontend/lib/draft-logic.js:76` | rookie board values | letter · A.. | /draft RookieBoard | — | frontend/__tests__/components/DraftBoardSort.test.jsx | **OK** |
| `F-178` | Perfect draft | - | `-` | - | — | - | no such construct exists (grep 'perfect.?draft' over *.py *.js *.jsx: nothing) | - | **MISSING** |

#### 9.3.18 Tiering, confidence, freshness

| ID | Concept | Expression | file:lines | Inputs | Units · scale/range | Consumers | Rationale · assumptions | Tests | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `F-180` | Tier detection (live) | rolling-median gap detection over the sorted value series | `src/canonical/player_valuation.py::detect_tiers:202 (_rolling_median:189)` | sorted values + player ids | tier ids · 1..N | src/api/data_contract.py:2029-2033 (compact_ranks_and_tiers) | — | tests/canonical/ | **OK** (dup-of F-181) |
| `F-181` | Tier detection (effect-size) | _pool_normalized_gap(tier_mean, candidate, pool_sd) with grid-searched thresholds + drift detection | `src/scoring/tiering.py::detect_tiers:201, stamp_tiers_on_players:226, fit_thresholds_grid_search:253, detect_threshold_drift:314` | position rows + fitted thresholds | tier ids · 1..N | scripts/refit_tier_thresholds.py ONLY | the positional_tiers flag is marked NO_GATE in feature_flags.py:410 | tests/scoring/ | **SCAFFOLD** (dup-of F-180 (same function name, different math, different consumers)) |
| `F-182` | Confidence bucket (contract) | _CONFIDENCE_PERCENTILE_HIGH 0.08 / MEDIUM 0.20; _CONFIDENCE_SPREAD_HIGH 30 / MEDIUM 80 | `src/api/data_contract.py:112-118` | cross-source percentile spread | labels · high/medium/low | /api/data every row, F-026 corridor bucketing, /rankings | — | tests/api/ | **OK** (dup-of F-183, F-184) |
| `F-183` | Confidence (source count) | n>=6 high, n>=3 medium, else low | `src/trade/suggestions.py::_confidence_from_sources:811-816` | source count | labels · high/medium/low | POST /api/trade/suggestions | — | tests/trade/ | **DUP** (dup-of F-182 (same three labels, entirely different input)) |
| `F-184` | Market confidence (scraper) | _market_confidence — scraper-side confidence over raw source coverage | `Dynasty Scraper.py::_market_confidence` | raw source presence | labels/score | data/dynasty_data_*.json -> /api/data mirror fields | formula-registry market-confidence, status documented-divergence | tests/api/test_market_confidence_wiring.py | **DUP** (dup-of F-182, F-183) |
| `F-185` | Source-consensus value range (CI) | confidence interval across sources — explicitly NOT a forecast | `src/canonical/confidence_intervals.py (261L)` | per-source votes | value points · 0-9999 band | gated by value_confidence_intervals, which feature_flags.py:409 marks NO_GATE | the flag defaults False AND gates nothing, so the gate is not the control | tests/canonical/ | **SCAFFOLD** |
| `F-186` | Rank-history CI band | rolling rankHistory band for the source-consensus CI | `src/canonical/rank_history_band.py (141L)` | rank history | rank band · ordinals | /api/data/rank-history, PlayerRankHistoryChart | — | tests/canonical/ | **OK** (dup-of F-185) |
| `F-187` | Data freshness guard | is_fresh_for_alerts(week, year, now) — false until Thursday (weekday 3) US/Eastern, after pfr + nflverse republish | `src/nfl_data/freshness.py:_SAFE_WEEKDAY=3 (96L)` | NFL week, year, wall clock in America/New_York | boolean | signal alerts sweep, nfl_data ingest | 'do not trust current-week data until Thursday local NFL day' — one global republish deadline for every nflverse table | tests/nfl_data/ | **OK** (dup-of F-188) |
| `F-188` | Source staleness | _SOURCE_MAX_AGE_HOURS per source; _DEFAULT_SOURCE_ROW_FLOORS; _DEFAULT_TOP50_COVERAGE_FLOORS; _PICK_COUNT_FLOOR 100; _PAYLOAD_SIZE_FLOOR_BYTES 2,000,000 | `src/api/data_contract.py:589, :646, :756, :764, :773` | source CSV mtimes + row counts | hours / rows / bytes | /api/scaffold/status, source-health alerts, /tools/source-health | — | tests/api/ | **OK** (dup-of F-187) |
| `F-189` | Source disagreement flags | _DISAGREEMENT_BASE_THRESHOLD 0.10 (caution), _SUSPICIOUS_PCT_BASE_THRESHOLD 0.20 (anomaly), depth allowance cap 0.25, _SUSPICIOUS_DISAGREEMENT_THRESHOLD 150 ranks | `src/api/data_contract.py:160-162, :191` | per-source rank spread | flags · boolean | /rankings caution badges, /tools/source-health | — | tests/api/ | **OK** |

#### 9.3.19 League features, in-season updating, and the four gaps

| ID | Concept | Expression | file:lines | Inputs | Units · scale/range | Consumers | Rationale · assumptions | Tests | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| `F-190` | Awards / award races | VORP over F-041 replacement, plus per-award rule sets (League MVP, Playoff MVP, …) | `src/public_league/awards.py (2343L)` | Sleeper matchup players_points, F-041 | fantasy points / VORP · points | GET /api/public/league/awards, /league Awards tab | — | tests/public_league/ | **OK** |
| `F-191` | Records | per-category all-time extremes over every scored week in the snapshot | `src/public_league/records.py (488L)` | PublicLeagueSnapshot | points / margins | GET /api/public/league/records, /league Records tab | — | tests/public_league/ | **OK** (dup-of F-192) |
| `F-192` | Streaks / records-in-reach | active streak detection + distance-to-record | `src/public_league/streaks.py (581L)` | same snapshot | counts | GET /api/public/league/streaks | — | tests/public_league/ | **OK** (dup-of F-191) |
| `F-193` | Franchise rankings | per-owner all-time rollup (record, titles, playoff appearances, award shelf) | `src/public_league/franchise.py (299L)` | multi-season snapshot | counts / rates | GET /api/public/league/franchise, /league/franchise/[owner] | 'award shelf placeholder (later prompt wires real awards)' — self-declared placeholder at :11 | tests/public_league/ | **PARTIAL** |
| `F-194` | Superlatives / rivalries | per-pair head-to-head aggregates and league superlatives | `src/public_league/superlatives.py (211L), src/public_league/rivalries.py (210L)` | snapshot matchups | counts | /league Superlatives, /league/rivalry/[pair] | — | tests/public_league/ | **OK** |
| `F-195` | Team assignment (fantasy team -> NFL teams) | tiered point model over the roster (starting QB, skill starters/committee, rookie draft capital, IDP starters); NFL teams scoring >= assignmentMinPoints (15) qualify; max maxTeamsPerOwner (3) per owner, favorite always counts | `src/api/team_assignment.py (510L)` | league rosters + a favorites key | points · >= 15 to qualify | GET /api/public/league/teamAssignment, /league?tab=teamAssignment | the point tiers are priors; debug block carries per-player contributions | tests/api/ | **OK** |
| `F-196` | Injury impact | injury-status -> value impact model (position-based, not league-based) | `src/api/injury_impact.py (336L)` | injury feed status, position | value points · 0-9999 delta | /api/data injury fields, /rankings | CLAUDE.md: injury-impact follows scoring profile, not leagueKey | tests/api/ | **OK** |
| `F-197` | League comparison improvement score | 0.??*... + 0.10*replacement_adj (IMPROVED_WEIGHT_REPL_ADJ) over per-position metrics | `src/league_comparison/metrics.py:13-16, :195, :248-259` | two scoring systems' realized points | score | GET /api/league-comparison, /league-comparison | 'picks up replacement-end compression' | tests/league_comparison/ | **OK** (dup-of F-043) |
| `F-198` | Schedule structure (BDVM) | NFL schedule -> per-team ROS week structures (byes, playoff weeks) | `src/bdvm/schedule.py (112L)` | NFL schedule | week sets · 1..18 | src/bdvm/ros.py, src/bdvm/engine.py | absent path: data/bdvm/ | tests/bdvm/ | **BLOCKED** |
| `F-199` | Schedule optimization | - | `-` | - | — | - | no schedule OPTIMIZER exists. F-198 is schedule structure, F-083 is schedule luck, F-091's schedule_adjusted is a power component. Nothing optimizes a schedule. | - | **MISSING** |
| `F-200` | Money / ROI | - | `-` | - | — | - | no entry fees, payouts, prizes or ROI anywhere. The single 'ROI' string in the tree is a comment in frontend/lib/draft-logic.js:2286 about valueVsFair. | - | **MISSING** |
| `F-201` | In-season posterior blend (BDVM) | w = n_prior/(n_prior + weeks) with n_prior 6 offense / 8 IDP; sigma shrinks by sqrt(w_prior); ROS drops already-played weeks via current_week | `src/bdvm/actuals.py, blend_ros_mu` | nflverse weekly rows scored under the league's exact settings | PPG · PPG | /api/bdvm/* | BDVM section 8.4 — the actuals season is the CALENDAR NFL season, never currentDraftYear; absent path: data/bdvm/ | tests/bdvm/test_inseason.py | **BLOCKED** |
| `F-202` | Auto news -> event confidence | confidence = 0.45 (< 0.5) so effective_impact suppresses every non-sigma channel AND clamps sigma_mult >= 1.0 | `src/bdvm/news_events.py` | aggregated headlines | confidence · 0.45 fixed | data/bdvm/events/<season>.json -> F-003 | 'a headline can widen uncertainty but can NEVER move a mean or narrow sigma' — raising confidence is a human edit; absent path: data/bdvm/ | tests/bdvm/test_news_events.py | **BLOCKED** |

---

## 9.4 The central section: one concept, many implementations

This is the finding of the section. The platform does not have a mathematics problem so much
as an **authority** problem: for most decision-grade numbers, more than one module claims to
produce them, and nothing in the tree reconciles the answers or names which one a user is
reading.

### 9.4.1 Scoreboard — prior claim vs. what this audit counted

The prior audit's summary (`docs/audits/decision-intelligence-audit-2026-08-04.md:42-46`;
restated at `:278` and `:338`) names five duplication counts. Each was independently recounted
at HEAD.

| Concept | Prior audit claimed | **This audit counted** | Do the implementations agree numerically? | Finding |
|---|---:|---:|---|---|
| Replacement level | 4 | **4** — confirmed | **Not comparable.** Three different unit systems (board points, PPG, season points). No conversion exists between them and no test compares any pair. | `F-040`–`F-043` |
| Playoff-odds engines | 2 | **2** (+1 championship engine built on v2) | **No.** Different league: 7 playoff spots vs 6, 12 owners vs 8, two managers flip 0.0 ↔ 1.0. | W30-F001 |
| Power-ranking engines | 2 | **2** — confirmed | **No.** 10 teams vs 12, mean \|Δrank\| 2.8, max 7 (one manager 10th → 3rd). | W30-F003 |
| Team-phase classifiers | 3 | **6** — recount | **No.** Four of the six answer the same question about the same team from four unrelated input families. | W30-F016 |
| BUY/SELL label families | 4 | **5 producers** (W30-F012); **16 emitters, 14 reachable** on the wider census (W12-F003) | **No.** Five threshold sets on the *same* retail-vs-consensus quantity. | W30-F012, W12-F003 |

Duplicated concepts the prior audit did **not** count, found here:

| Concept | Implementations | Agree? | Finding |
|---|---:|---|---|
| Percentile of a value in a population | **5** (one written inline twice) | **No** at the endpoints and on degenerate populations | W30-F007 |
| KTC Value Adjustment | **4** (1 JS original + 3 Python ports) | **Almost** — 38 of 20,000 packages differ, always by exactly 1 | W30-F005 |
| Team total value | **3** (+ a 4th scorer that reuses the terms) | **No** — the two simple sums differ by pick capital, 22.5% of a portfolio | W30-F017 |
| Rank → value (Hill) | **2** (Python + JS mirror) | **Yes** — identical at all 15 probed ranks | `F-010`/`F-011` |
| Rank → percentile denominator | **2** (serving 500, fitting 400) | **No** — same rank, up to 25.4% different value | W30-F008 |
| TE premium | **2 maths for one concept**, selected by source class | **Cannot agree** — the measured curve's range (1.209–2.053) excludes the flat prior (1.10) | W30-F019 |
| `detect_tiers` | **2** functions, same name, different algorithm | Untested against each other; only one is live | W30-F020 |
| Confidence label | **3** (spread-based, source-count, scraper) | Same three labels, unrelated inputs | `F-182`–`F-184` |
| Movement indicator ("mover") | **2** (per-scrape delta, windowed trend) | Different semantics under one word | `F-152`/`F-153` |
| Pick value | **4** (canonical, Sleeper fallback, legacy dead, BDVM EV) | 2 live and consistent, 1 dead, 1 a deliberately different concept | `F-170`–`F-173` |
| Positional need | **2** (starter-slot counts vs ROS-point deficit) | Different units entirely | `F-061`/`F-062` |
| Trade fairness verdict | **2** (percentage bands vs absolute point bands) | Not reconciled | `F-114`/`F-115` |
| Consolidation pricing | **2** (ratio heuristic vs CES aggregator) | Incompatible math and units | `F-118`/`F-119` |

---

### 9.4.2 Playoff odds — two engines, two different leagues

Both are live, both serve `/league`, and `settings.useRosPlayoffOdds` **defaults to `true`** —
so the default view is the newer, unvalidated engine.

| | **v1 — `src/public_league/playoff_odds.py`** | **v2 — `src/ros/playoff_sim.py`** |
|---|---|---|
| Route | `GET /api/public/league/playoffOdds` | `GET /api/public/league/rosPlayoffOdds` |
| Method | Sample each owner's future weekly score from their own empirical scored-week distribution | `shifted_mean = empirical_mean × (1 + 0.20 × (ros_strength_z − 1))`, sd × 1.10 |
| Sims | 10,000 | 2,000 |
| **Playoff spots** | **7** | **6 seeds + 2 byes** |
| **Owners covered** | **12** | **8** |
| Points model | empirical only | `pointsModelSource = "fallback-constants"` — no fitted model exists |
| Version stamp | `public-league/2026-04-18.v1` | none |

Measured live **(re-run)**:

- Four owners present in v1 are absent from v2 entirely: Brent, Kich, Blaine, jstuedle.
- Of the eight owners both cover, **two flip**: Eric `0.0 → 1.0`, MaKayla `0.0 → 1.0`. A user
  flipping one toggle moves a manager from "will miss the playoffs" to "certain to make them".
- Nothing on the page names which engine produced the number.

`src/ros/playoff_sim.py`'s own docstring says "Outputs match the v1 schema so the frontend can
swap data sources without a contract fork." The schemas match; the *leagues* do not
(W30-F001, confirms `PRIOR-A19-F01` and adds the spot-count disagreement).

**Both engines are also degenerate right now** (W30-F002, confirms `PRIOR-A19-F00`). With
`weeksPlayed = 0`, `weeksRemaining = 14` and every owner at `currentWins = 0`, both publish
only `{0.0, 1.0}` — 2 distinct probabilities across 12 owners. v2's convergence gate certifies
it: `converged = true`, `worstPlayoffOddsSe = 0.0`, because every simulation returns the
identical standings and the PF tie-break (all zero) resolves deterministically.
`rosChampionship` inherits it — Roy carries `playoffOdds 1.0`, `medianFinalSeed 3` and
`championshipOdds 0.0` simultaneously. `src/ros/direction.py` consumes these odds, so the
same degeneracy drives a "Strong Seller" trade recommendation.

*How to re-run:*
```bash
# session secret path is given in AUDIT_PROTOCOL.md
SECRET=$(cat "$E2E_SECRET_FILE"); curl -s -c /tmp/audit-cookies.txt -X POST \
  http://127.0.0.1:8000/api/test/create-session -H "Authorization: Bearer $SECRET" >/dev/null
for s in playoffOdds rosPlayoffOdds; do
  curl -s -b /tmp/audit-cookies.txt "http://127.0.0.1:8000/api/public/league/$s" -o /tmp/$s.json
done
.venv/bin/python -c "
import json
v1=json.load(open('/tmp/playoffOdds.json'))['data']; v2=json.load(open('/tmp/rosPlayoffOdds.json'))['data']
print(v1['playoffSpots'], len(v1['owners']), v2['playoffSeeds'], len(v2['playoffOdds']))
print(sorted({r['playoffProbability'] for r in v1['owners']}))"
```
→ `7 12 6 8` and `[0.0, 1.0]`. Artifact: `evidence/W30/playoff-odds-two-engines.json`.

---

### 9.4.3 Power rankings — two engines, and one of them is running on 2 of 9 weights

`settings.useRosPowerRankings` also **defaults to `true`**.

| | **v1 — `src/public_league/power.py:45-47,:141`** | **v2 — `src/ros/power_v2.py:65-75,:99-108`** |
|---|---|---|
| Formula | `100 × (0.50·PPG %ile + 0.25·last-3 %ile + 0.25·all-play win share)` | weighted sum of 9 components; missing components dropped and weights renormalised |
| Weights | 3, all present | `team_ros_strength .38, ppg .18, recent .12, wl_record .10, all_play .08, streak .05, schedule_adjusted .04, roster_health .03, luck_regression .02` |
| **Live effective weights** | 3 of 3 | **2 of 9** — `{team_ros_strength: 0.38, roster_health: 0.03}` |
| Teams ranked | **10** | **12** |

Live divergence over the 10 teams both cover **(re-run)**: mean `|Δrank| = 2.8`, max `7`.

| Manager | v1 rank | v2 rank |
|---|---:|---:|
| Jason | **10** (power 0.0) | **3** (power 80.69) |
| Eric | 9 | 5 |
| Collin | 7 | 4 |
| Kich | 3 | 8 |
| Ty | 4 | 7 |
| Ed | 5 | 9 |
| Roy | 8 | 10 |

In preseason, v2 is a renormalised ROS-strength ranking wearing the label "Power". The payload
reports `missingInputs`, `effectiveWeights` and `preseason: true` honestly — **the data to
render a warning exists and no surface renders it** (W30-F003, partial on `PRIOR-A03-F06`).

**The defaults are documented backwards.** `frontend/app/league/LeagueClient.jsx:100` tells the
reader "Defaults match the registry in components/useSettings.js (rosEnabled true,
useRosPowerRankings false until validated per-user)". `frontend/components/useSettings.js:143`
is `useRosPowerRankings: true` and `:148` is `useRosPlayoffOdds: true`. Every user lands on the
unvalidated v2 engines without opting in (W30-F004, confirms `PRIOR-A03-F07` and adds that the
inversion is also at the *read* site, not only in the `/settings` hint).

*How to re-run:* `grep -n 'useRosPowerRankings\|useRosPlayoffOdds' frontend/components/useSettings.js frontend/app/league/LeagueClient.jsx` **(re-run)**. Artifact: `evidence/W30/power-two-engines.json`.

---

### 9.4.4 Replacement level — four answers, three unit systems, zero comparisons

The prior audit's count of four is **confirmed**. What it did not record is that they are not
merely different implementations — they are **incommensurable**, and its recommendation
("`src/league_intel/replacement.py`; retire the other three",
`decision-intelligence-audit-2026-08-04.md:1081`) is not executable as written, because the
other three produce a quantity the survivor cannot express.

| | `F-040` league-intel | `F-041` scoring | `F-042` BDVM | `F-043` league-comparison |
|---|---|---|---|---|
| Site | `src/league_intel/replacement.py::compute_replacement_levels` (672L) | `src/scoring/replacement_level.py::replacement_per_game, vorp_table` (237L) | `src/bdvm/replacement.py::ReplacementEngine` (155L) | `src/league_comparison/metrics.py:95-97,:164,:172-174` |
| **Units** | **dynasty board value points, 0-9999** | **fantasy points per game** | **fantasy points per game** | **season fantasy points** |
| Definition | 4 thresholds/position (starter / bestBallStarter / roster / waiver) from what the exact optimizer actually starts | mean pace of the **five** players just below the starter cutoff | FPG at the rank of [flex-allocated startable slots + waiver buffer] | the **Nth** player's points (e.g. QB24) |
| Flex handling | **endogenous** — solved | **preassigned** — FLEX 1/3 each, SUPER_FLEX 1/4, IDP_FLEX 1/3 | greedy allocation, deterministic tie-break | n/a |
| Missing-data posture | smoothed bands | — | **raises `ReplacementUnavailableError`** rather than fabricating `R = 0` | — |
| Consumers | `src/api/gameplan.py:129-132`, `src/roster_intel/*` | `src/public_league/awards.py` (League MVP, Playoff MVP), IDP scoring-fit | `src/bdvm/engine.py`, `/api/bdvm/*` | `/api/league-comparison` |

Two of the four contradict each other **in their own docstrings**: `F-040`'s argues against
resting on a single rank ("hostage to one player's projection") — which is precisely what
`F-043` does. `F-041` preassigns flex shares; `F-040` solves for them.

`F-040` also carries a self-documented known limitation worth keeping in view: it optimises on
season-long **means**, so it understates flex demand for high-variance positions — projected
FLEX TE share 0.0% against 10.4% measured on 2025 weekly actuals.

**No test compares any pair.** *How to re-run:*
`grep -rln "league_intel.replacement" tests/ | xargs grep -ln "bdvm.replacement\|scoring.replacement_level"` → no output **(re-run)**.

---

### 9.4.5 Team phase / "contender" — six classifiers, four input families

The prior audit counted three. Recounted at HEAD: **six** (W30-F016, confirms `PRIOR-A18-F00`).

| | Site | Input family | Labels | Surface |
|---|---|---|---|---|
| `F-070` | `frontend/lib/team-phase.js::classifyPhase:79-92` | top-25 board value × median age, **median split** | 4 (Win-now / Contender / Rebuild / Mixed) | `/phases` |
| `F-071` | `src/ros/direction.py::classify_team:53-` | playoff odds + championship odds + position-aware veteran ages | 7 (Strong Buyer … Strong Seller) | `/league` trade-deadline |
| `F-072` | `src/roster_intel/window.py:85-104,:285-300` | championship-odds percentile × value-weighted lineup age, **softmax T = 0.18** | 5 states, **as a probability distribution** | `/api/gameplan` |
| `F-073` | `src/bdvm/roster.py::_directions_relative:63-92` | BDVM contender/rebuilder capital ratio ÷ league median | 3 (contend / retool / rebuild) | `/bdvm` |
| `F-074` | `src/trade/suggestions.py::_strategy_for_player:803-808` | `years_exp` — **per player, not per team** | 3 | `/api/trade/suggestions` |
| `F-075` | `frontend/lib/league-analysis.js:1146-1152` | hard tercile of `F-056` roster score | 3 | `/rosters` |

`F-074` is legitimately a different object (a player tag, not a team classifier). The other
five all answer "what is this team's competitive posture" and share no input, no label count
and no vocabulary. A manager can read *Win-now* on `/phases`, *rebuild* from `/api/gameplan`,
*Strong Seller* on the `/league` deadline tab and *Mid-Tier* on `/rosters` at the same moment.

Two of the six are better than the rest and should be said so: `F-072` publishes a
**distribution** rather than a label and states its own ordering caveat
(`retool` vs `productive_struggle` is explicitly soft); `F-073` documents why it went
league-relative — the absolute rule (ratio vs 1.15) saturated with all twelve rosters reading
"contend".

Two of the six inherit the preseason degeneracy of §9.4.2: `F-071` reads playoff and
championship odds directly, and `F-072` reads a championship-odds percentile.

---

### 9.4.6 Percentile of a value in a population — five definitions

`docs/audits/formula-registry.json` already records this concept with `canonical: "NONE —
five incompatible definitions"`. This audit confirms it and attaches the numbers.

On the population `[10, 20, …, 120]` (n = 12) **(re-run)**:

| Implementation | Formula | min (10) | mid (60) | max (120) | empty pop | singleton |
|---|---|---:|---:|---:|---:|---:|
| `src/public_league/power.py::_percentile_rank:52-61` | `(below + (equal−1)·0.5)/(n−1)` | **0.0** | 0.4545 | **1.0** | 0.5 | 0.5 |
| `src/sharp/score.py::percentile_rank:191-203` | `(below + 0.5·equal)/n` | 0.0417 | 0.4583 | 0.9583 | 0.5 | 0.5 |
| `src/ros/power_v2.py::_percentile:99-108` | `(below + 0.5·same)/len(eligible)` | 0.0417 | 0.4583 | 0.9583 | **0.0** | 0.5 |
| `src/roster_intel/window.py:228-231` and `:238-241` | same as sharp — **written out inline twice, not imported** | 0.0417 | 0.4583 | 0.9583 | — | — |
| `src/roster_intel/profiles.py:86-89` | `vals[max(0, round(n·ELITE_PERCENTILE) − 1)]` — **an index, not a percentile**; `round()` is banker's, so the index steps non-monotonically with n | n/a | n/a | n/a | n/a | n/a |

Two consequences that reach users:

- **The last-place team scores exactly 0.0** on `/league` Power Rankings v1, because
  `power.py` is the only one that reaches a literal zero. Confirmed on the live payload: Jason,
  power `0.0`. That reads as "no measurable strength", not "lowest of twelve".
- **An unmeasurable percentile reads as worst-in-league** in `ros/power_v2.py` — an empty
  population returns `0.0` where the other two return the neutral `0.5`.

Every helper is internally consistent and each is documented at its own site. The defect is
that no shared utility exists, so each subsystem invented its own tie convention and its own
empty-population policy (W30-F007).

*How to re-run:*
```bash
.venv/bin/python -c "
from src.public_league.power import _percentile_rank as a
from src.sharp.score import percentile_rank as b
from src.ros.power_v2 import _percentile as c
p=[10,20,30,40,50,60,70,80,90,100,110,120]
print(a(p,120), b(120,p), c(p,120)); print(a([],5), b(5,[]), c([],5))"
```
→ `1.0 0.9583333333333334 0.9583333333333334` / `0.5 0.5 0.0`. Artifact: `evidence/W30/percentile-helpers.json`.

---

### 9.4.7 KTC Value Adjustment — one algorithm, four maintained copies

| | Site | Rounding | Consumers |
|---|---|---|---|
| `F-110` JS original | `frontend/lib/trade-logic.js::ktcAdjustPackage` | `Math.round` (half-up) | `/trade` TradeMeter |
| `F-111` Python port A | `src/trade/ktc_va.py:116, :319` | **Python `round()` — banker's** | `src/trade/suggestions.py:27`, `src/trade/angle.py:98`, `src/trade/monte_carlo.py:153` → `/api/trade/suggestions`, `/api/angle/*`, `/api/trade/simulate-mc` |
| `F-112` Python port B | `src/trade/market_value_adjustment.py:33-36, :386` | `_js_round = floor(x+0.5)` | `src/trade/finder_value_adjustment.py:16` → `/api/trade/finder`, `/arbitrage` |
| `F-113` Python port C | `src/public_league/trade_grading.py:103-112, :387` | `_js_round = floor(x+0.5)` | public-league trade grades, `/league` Activity |

`trade_grading.py:103-112` states the problem explicitly in a comment — Python's builtin
`round()` is round-half-to-even and gives a different answer than JS — and defines
`_js_round` to avoid it. `market_value_adjustment.py` adopted the same shim. **`ktc_va.py`,
the port behind trade suggestions, the angle finder and the Monte Carlo simulator, did not.**

Measured over 20,000 random packages, seed 11 **(re-run)**:

| Pair | Divergent packages | max \|diff\| |
|---|---:|---:|
| `ktc_va` vs `market_value_adjustment` | **38 / 20,000 (0.19%)** | **1** |
| `ktc_va` vs `trade_grading` | 38 / 20,000 | 1 |
| `market_value_adjustment` vs `trade_grading` | **0** | 0 |
| side / displayed disagreements, any pair | **0** | — |

Worked case from the finding, reproduced exactly: `A = [4581, 6362, 4354]`,
`B = [7181, 3245]` → `ktc_va` **1281**, the other two **1280**.

The magnitude is trivial. The governance fact is not: one algorithm has four maintained copies
and **no test in the tree compares any two of them**. `tests/trade/test_ktc_va_python_port.py`
imports only `src.trade.ktc_va`; `tests/trade/test_finder_value_adjustment.py` imports only
`src.trade.market_value_adjustment`; `trade_grading` is pinned by its own fixture.

> **Correction to the shard.** W30-F005 states that `ktc_va`'s own parity test "asserts
> agreement to ±1, so the test cannot fail on this." That is not what the file says. Its
> tolerances are **RMS < 50** across 139 captured KTC trades
> (`tests/trade/test_ktc_va_python_port.py:39-49`) and **±5** on the pinned cases (`:108`,
> `:133`). The conclusion is unchanged and in fact stronger: a 1-point divergence is two orders
> of magnitude below every tolerance in the file, *and* the test structurally cannot see the
> other ports because it never imports them.

*How to re-run:*
```bash
.venv/bin/python -c "
import random
from src.trade.ktc_va import ktc_adjust_package as A
from src.trade.market_value_adjustment import ktc_adjust_package as B
random.seed(11); n=0
for _ in range(20000):
    a=[random.randint(200,9999) for _ in range(random.randint(1,5))]
    b=[random.randint(200,9999) for _ in range(random.randint(1,5))]
    n += int(A(a,b).value != B(a,b).value)
print(n)"
```
→ `38`. Artifact: `evidence/W30/ktc-va-three-ports.json`.

---

### 9.4.8 Team total value — three definitions, one shared tile

| | Site | Includes picks? | Units |
|---|---|---|---|
| `F-051` marginal best-ball | `src/roster_intel/marginal.py:136-138` | n/a — lineup-constrained leave-one-position-out | **ROS points** |
| `F-052` frontend simple sum | `frontend/lib/league-analysis.js::buildTeamValueBreakdown` | **yes** | board points |
| `F-053` terminal simple sum | `src/api/terminal.py:1070` | **no** | board points |

`terminal.py:1204-1221` documents the divergence in code with a real measurement, and calls it
"a known difference instead of a claimed equivalence". Confirmed at HEAD: **442,936** of pick
value against **1,524,591** of player value on the live 12-team snapshot — **22.5%** of a
portfolio. The Total Value tile on the home terminal and the same team's total on `/rosters`
can therefore differ by nearly a quarter with no note on either surface (W30-F017, confirms
`PRIOR-A18-F10`).

`F-051` is the only one that legitimately claims lineup awareness; it is a genuinely different
concept, correctly recorded as such.

A fourth consumer of the same terms, `F-056` `scoreTeamTiers`
(`frontend/lib/league-analysis.js:1131-1152`), is analysed in §9.5 (double counts).

*How to re-run:* `sed -n '1200,1225p' src/api/terminal.py` **(re-run)**.

---

### 9.4.9 Rank → value — the duplicate that *does* agree

Not every duplicate is a defect, and this audit says so.

| | Site | Constants |
|---|---|---|
| `F-010` Python | `src/canonical/player_valuation.py::rank_to_value:287`, `rank_to_value_for_scope:313` | OFFENSE/GLOBAL/ROOKIE `65.4 / 0.91`; IDP `64.6 / 0.90` |
| `F-011` JS mirror | `frontend/lib/value-history.js::valueFromRank:349` (`RANK_FORM_CURVE:333`) | hardcoded `{65.4, 0.91, 9998}` |

Verified identical at 15 probed ranks (1, 2, 3, 5, 10, 20, 50, 100, 150, 200, 300, 400, 500,
600, 800): `js_minus_OFFENSE = 0` at every one — e.g. rank 100 → 4068 on both, rank 800 → 931
on both. `evidence/W30/rank-to-value-js-vs-py.json`. Lockstep is enforced by
`tests/api/test_rank_form_frontend_parity.py`, not by import — which is the standing risk, but
the numbers agree at HEAD.

Two adjacent notes: the JS also carries a closed-form inverse `F-012`
(`rankFromValue:371`), used to draw a rank line for history snapshots that persisted a value
but no rank. Its assumption — that the board's value came from this exact curve — is false:
the board comes from `F-001`, a different path. A derived rank can be mistaken for a stamped
one on the chart. And the scraper keeps its own third rank→value mapping (`F-013`) inside a
separate system, feeding `canonicalSiteValues`, which the canonical pipeline then re-ranks.

---

### 9.4.10 TE premium — two maths for one concept, plus a live override that bypasses both

`CLAUDE.md` step 5a documents this accurately, and it is still a divergence (W30-F019).

| | Applies to | Multiplier |
|---|---|---|
| `F-030` measured basis conversion | non-TEP sources (11 of them) | **1.209 → 2.053**, a function of the TE's own base value |
| `F-032` flat prior | TEP-native sources (`idpTradeCalc`, `dynastyNerdsSfTep`, `fantasyProsFitzmaurice`, `yahooBoone`, `draftSharks`) | **exactly 1.10** |
| — | `ktc` / `ktcSfTep` | **exempt** — the anchor *is* the TE++ board |

The measured range does not contain 1.10 anywhere on the board, so the two paths cannot agree
at any rank. Two sources ranking the same tight end identically contribute different values
purely because of their declared basis. The cause is honest and stated: **no measurement
exists for TEP-native → TE++**, so the old prior was left in place when the base path was
replaced.

`CLAUDE.md` also states the unresolved second half itself: the target basis is a **constant**,
while TE demand is a `leagueKey` property, and the two live leagues on
`superflex_tep15_ppr1` want different bases.

**The live override is the bigger problem, and it is verified.** `/rankings` and `/trade` both
POST `{"tep_multiplier": 1.15}` on every page load — the `/settings` default — and
`src/api/data_contract.py:6939` gates the entire ADR-015 basis conversion behind
`if not tep_multiplier_is_override:`. An explicit slider value therefore **substitutes the
flat 1.15 that ADR-015 removed for sitting below the entire observed range**:

| Finding | Verification verdict | Measured |
|---|---|---|
| W08-F001 | **upheld** | 129 of 809 players repriced on `/trade` — 79 TEs (every TE in the comparison, all moved *down*) + 50 tethered picks; max −21.2%; empty-body control is a clean 0 |
| W03-F001 | rescoped | 627 of 740 ranks, 654 tiers and 135 values differ from `GET /api/data`, while `rankingsOverride.isCustomized` reports `false` |
| W07-F001 | rescoped | reproduced in a real browser with a virgin `localStorage`; Tyler Conklin 1450 → 1142 (rank 469 → 666); Brevin Jordan 1519 → 1243 |

The W03-F001 verifier sharpened the mechanism: posting **`{}`** returns a byte-identical
board, so the divergence is caused by the **presence of the explicit key, not its value** —
posting the exact number the contract already reports as its own default reprices 786 rows.

What *does* work here is the double-count guard, and it is worth stating plainly (W27-F009,
W02-F013): across 85 TE rows and 781 (TE × source) stamps, **zero** rows carry both
`tepBoostApplied` and `tepNativeCorrectionApplied`; `ktcSfTep` carries neither on all 73 rows
it prices; the league-adjusted overlay reports `tePremium` in `inactiveAxes` so it contributes
no second TE multiplier.

*How to re-run:*
`.venv/bin/python -c "from src.league_intel.te_premium import tep_uplift, load_tep_curve; print(load_tep_curve()); print([(v, round(tep_uplift(v),3)) for v in (9000,3000,1500,600,300)])"`
→ floor 1.209206, ceiling 2.0531; `[(9000, 1.209), (3000, 1.275), (1500, 1.426), (600, 1.76), (300, 2.053)]`.

---

### 9.4.11 BUY / SELL / HOLD — five producers, and the module built to unify them has no importer

`src/news/unified_signal_engine.py:1` opens: *"Unified signal engine — single entry point for
every BUY/SELL/HOLD decision emitted to users."* **Nothing imports it.** The only occurrences
of its name anywhere are four comments (`src/api/feature_flags.py:75,78,332`,
`src/consensus_edge/__init__.py:7`) that describe it as not wired.

Meanwhile five producers ship, with three label vocabularies:

| | Site | Vocabulary | Surface |
|---|---|---|---|
| `F-130`/`F-131` | `src/api/terminal.py::_evaluate_signal:875` + `frontend/lib/signal-engine.js` | RISK / SELL / MONITOR / STRONG_HOLD / BUY / HOLD | `/`, `/rankings` |
| `F-133` | `src/bdvm/market.py:307-351` | STRONG_BUY … STRONG_SELL, NO_MARKET | `/bdvm`, `/rankings` Fund-gap tint |
| `F-134` | `src/consensus_edge/score.py:326-333` | Strong Buy / Buy / Sell / Strong Sell on a −100…100 composite | `/consensus-edge` — **503, flag off by default** |
| `F-135` | `src/sharp/market.py` | cohort net add/drop | `/market/sharp-tracker` |

W12-F003 (**rescoped**, still P1) widened this census: **16 directional emitters, 14 reachable**,
and **five different cutoffs applied to the same retail-vs-consensus quantity** — `> 0`
(backend stamp), `>= 3` (`getPlayerEdge`, powers PlayerPopup and the `/league` Edge Map),
`>= 10` (`marketAction`, powers the `/rankings` Edge column), `sourceRankSpread >= 20 AND
rank <= 250` (`/edge` panels), and `>= 10` on a different source set (`idpMarketAction`).
None of the 14 imports or reads another.

The two arbiter candidates both fail: `src/consensus_edge/*` returns 503 on every route
because its flag defaults off (`F-134`, *implemented but disconnected*), and
`unified_signal_engine.py` has no caller (`F-132`, *scaffolded only*).

What works: the two engines that **are** pinned share
`tests/fixtures/signal_parity_cases.json` and both parity tests exist; BDVM deliberately keeps
a separate label set **and** a separate `user_kv` namespace
(`bdvmSignalAlertStateByLeague`) so the two alert streams cannot collide.

*How to re-run:*
`grep -rn 'unified_signal_engine' --include=*.py . | grep -v __pycache__ | grep -v '^./tests'`
→ 3 hits, all comments, zero imports **(re-run)**.

---

### 9.4.12 The duplicates that are correct, and why

An audit that only lists collisions is misleading. Four pointers resolve to deliberate,
documented divergence and were verdicted clean:

| Pair | Why they differ | Evidence |
|---|---|---|
| `F-122` arbitrage edge vs `F-123` board quality gate | **Same value, deliberately different gate.** `finder.py` must rank against the *retail market per market* (`ktcSfTep` for offense+picks, `idpTradeCalc` for IDP) because the market number is load-bearing in its arithmetic; `suggestions.py` only needs an asset-quality gate, which our own board answers for IDP and picks no retail board covers. Both engines now read the same internal value (`rankDerivedValue`). | `CLAUDE.md` "Trade Engines"; `metadata.valueSource` stamps the scale per run |
| `F-130` vs `F-131` | Two languages, one rule ladder, one shared fixture | `tests/api/test_signal_engine_parity.py`, `frontend/__tests__/signal-engine-parity.test.js` |
| `F-160` vs `F-161` | FAAB parity port | `tests/fixtures/faab_bid_parity_cases.json` |
| `F-010` vs `F-011` | Rank→value parity port, verified identical at 15 ranks | `tests/api/test_rank_form_frontend_parity.py`; `evidence/W30/rank-to-value-js-vs-py.json` |

`F-170` (canonical pick value) vs `F-173` (BDVM pick outcome EV) is likewise a deliberate
market-vs-fundamental split, not a collision.

---

## 9.5 Double counts

Sixteen inventory rows carry a `possible double-count` note. Sorted by what the note actually
records:

| Class | Rows | Meaning |
|---|---:|---|
| **Guard** — the note records *why the double count cannot happen* | 9 (`F-003`, `F-027`, `F-030`, `F-036`, `F-133`, `F-141`, `F-162`, `F-201`, `F-202`) | structural, and three of them verified on live data (§9.10) |
| **Conditional** — would double-count only under a change nobody has made | 2 (`F-001`, `F-002`) | `F-002`: "would double-count if re-blended with `rankDerivedValue`" |
| **Closed defect** — was real, fix in place | 3 (`F-056`, `F-150`, `F-171`) | §9.5.1, §9.5.2 |
| **Open question** — not proven wrong | 1 (`F-116`) | §9.5.1 |
| **Order of operations** | 1 (`F-170`) | §9.5.3 |

**No live double count was proven in this audit.** That is a result, and it is the opposite of
what the `possible double-count` column looks like at a glance.

### 9.5.1 One closed, one open question

| # | Where | What | Status |
|---|---|---|---|
| 1 | `F-056` `frontend/lib/league-analysis.js:1131-1152` | `pickValue` inside `totalValue` was also feeding the `+0.2` depth term while being charged `−0.1` as a pick — a net **positive** coefficient on pick capital in a score that documents itself as penalising it | **Closed at HEAD** — W30-F021 refutes `PRIOR-A03-F00` |
| 2 | `F-116` `src/trade/monte_carlo.py:153` | The KTC consolidation adjustment (`F-111`) is applied **on top of** the p50 draws, so a package is repriced by the VA after the sampler has already priced its pieces | **Open question**, recorded in the inventory; not measured, not proven wrong |

Item 1 is the one prior finding this workstream **refuted**. `PRIOR-A03-F00` claimed
`scoreTeamTiers`' pick term has the wrong net sign — that draft picks *increase* a contender
score by +0.1 per unit while the UI says they are penalised. **Fixed at HEAD**, and the fix
carries its own explanation in place (`:1072-1079`, "math audit 2026-08-04, H5"):

```js
const depthValue = totalValue - starterValue - pickValue;
const score = starterValue * 0.7 + depthValue * 0.2 + (pickValue > 0 ? -pickValue * 0.1 : 0);
```

Net coefficient on a pick dollar: **−0.1**, matching the docstring's "penalized at −10%
(rebuild signal)". Worked: `pickValue = 1000, starterValue = 0, totalValue = 1000` → −100.0
(W30-F021).

### 9.5.2 Fixed, with the fix pinned by a test

| Where | What it was | How it is prevented from returning |
|---|---|---|
| `F-150` `src/intel/aggregate.py::trend_score` | `3·net48h + 2·net7d + 1·net30d` over **nested** windows — one event an hour old contributed 3+2+1 = 6 | Module deleted; `tests/audit/test_formula_registry.py::test_nested_windows_are_not_summed_into_the_board_ranking` forbids any board sort on `trendScore`; the registry keeps `removedMarker: "def trend_score"` |
| `F-171` `src/api/draft_capital_fallback.py` flat per-round table | Invented values for every `current_season + 1` pick were normalised into the same $1,200 pool as real values, diluting every genuine pick and shifting every team's `auctionDollars` — **with a valid contract loaded** | Table removed; `_pick_value_from_contract` returns `None` on a miss; unpriced picks excluded from normalisation and emitted with `dollarValue: null` + `isUnpriced: true`; pinned by `tests/api/test_draft_capital_fallback.py` |

### 9.5.3 Order-of-operations, not a defect

- `F-170`: the multiplicative future-year pick discount runs at **Phase 3a, before the global
  sort**; pick tethering runs at **Phase 5.2b, after it**, and *overwrites* `rankDerivedValue`
  for current-year slot picks. A tethered current-year pick never carries a discount anyway
  (year offset 0 → factor 1.0), but the causal order is load-bearing when reasoning about
  future-year picks.
- `F-001`: the TE lift and the TEP-native flat multiplier both touch TE rows. Guarded
  structurally by the `from == to` no-op, and verified zero on the live payload (§9.4.10).

---

## 9.6 Wrong units and wrong scales

### 9.6.1 Proven wrong

| # | Defect | Magnitude | Finding | Status |
|---|---|---|---|---|
| 1 | **Hill curves fitted on a 400-row percentile denominator, served on a 500-row one.** `src/model_registry/holdout.py:145` maps native rank *i* to `p = i/(n−1)` with `n` capped at `FIT_TOP_N = 400` (denominator 399); `src/api/data_contract.py:5303` serves `p = (rank−1)/(_PERCENTILE_REFERENCE_N − 1)` = `(rank−1)/499`. The same rank lands at a smaller percentile at serve time and therefore a **higher** value than any observation the fit was scored against. | rank 50 **+13.2%**, rank 100 **+18.5%**, rank 200 **+22.7%**, rank 400 **+25.4%** | W30-F008 (P1, confidence *medium*) | open |
| 2 | **IDP-only sources handed a combined-pool percentile, scored on the IDP-slice Hill master.** An IDP-only source's rank is ladder-translated into combined-pool coordinates, the percentile denominator is the combined-pool 500, and `_curve_for_source` (`data_contract.py:6888-6894`) then routes on `scope` to a curve fit on IDP-only percentiles. | ~48% of the anchor's value at the identical effective rank | W02-F001 (P1) | **rescoped** — see below |
| 3 | **"Seller cash-out" compares a 0-9999 board value against a 0-100 ROS index.** `dynastyValue < rosValue × 0.7` with `dynastyValue = row.values?.full ?? row.rankDerivedValue`. Live `max(rosValue) = 86.79`, so the right-hand side maxes at **60.8**; the board's minimum `rankDerivedValue` is **757**. The ranges do not overlap. | **0 of 1,092 rows can ever fire.** The tag has never rendered. The same predicate is duplicated in three places (two JS, one Python). | W29-F005 (P3) | open |
| 4 | **`marketGapDirection` averages raw ordinal ranks across pools of 169–903 rows.** The same module's sibling docstring says this is invalid: "an effective spread of 100 doesn't mean the sources disagree, it means one is on a 1-185 scale and the other is on a 1-600 scale." | Recomputed in percentile space, the direction **flips on 214 of 386 offense rows (55.4%)** and **23 of 24 pick rows (95.8%)**. Calvin Ridley renders BUY on `/rankings` because of it. | W03-F006 (P2) | **rescoped** |
| 5 | **The flat 1.15 TE multiplier substituted for the measured curve on every page load.** §9.4.10. | 129 of 809 players repriced, max −21.2% | W08-F001 (P0) | **upheld** |

**W02-F001, verified position.** The verifier confirmed the mechanism "to the digit" and calls
feeding a combined-pool *p* into an IDP-slice-fit curve "a genuine units error". Three parts of
the author's record were corrected and must not be quoted as filed:

- `blastRadius.playersAffected = 398` is the count of **all** DL/LB/DB rows. Only **281** carry
  an IDP rank-signal vote — the authored figure overstates it by 42%.
- The published reproduction command **does not run as written**; the numbers survive only
  because the verifier rebuilt the measurement independently.
- The prescribed repair ("route to GLOBAL; re-fit is not required") **is not endorsed**. The
  GLOBAL counterfactual returns per-source medians of 0.92, 0.92, 1.29 and 1.32 — a *wider*
  spread than the control band it is compared against. Worse, the verifier found a **second,
  compounding scale defect the finding does not name**: `_percentile_pairs` renormalises the
  IDP slice so the best IDP = 9999, but the live board's best IDP anchor value is **6444**
  (Hutchinson), so the IDP master is fit in units **1.552×** the scale its output is consumed
  in. Correct-coordinate IDP routing would therefore *also* be wrong, by +55% at the top. The
  combined-pool percentile injection is currently deflating an over-scaled curve back toward
  the anchor. Two defects are compounding, and the naive re-route moves affected IDP rows up a
  median 8.9% (p90 42%) with no validation that the new numbers are right.
- Priority **P1 is unchanged and honest.**

**W30-F008's repair is now half-decided by a different workstream.** The finding offers "either
fit at 500 or serve at 400". The W04-F008 verifier tested serving at 400 and measured that
`tests/canonical/test_ktc_reconciliation.py` **fails 9 of 13** at `N = 400`, blowing the pinned
tolerance bands (rank 200 at −20.4pp against a ±10pp band). **Serving at 400 would break the
enforced production calibration gate.** The remaining option is to fit at 500, plus the
assertion W30-F008 asks for: a test that imports `FIT_TOP_N` and `_PERCENTILE_REFERENCE_N` and
requires them to agree. Today they are two independent constants with nothing tying them.

*How to re-run (defect 1):*
```bash
.venv/bin/python -c "
from src.model_registry.holdout import hill, FIT_TOP_N
from src.canonical.player_valuation import HILL_PERCENTILE_C as C, HILL_PERCENTILE_S as S
from src.api.data_contract import _PERCENTILE_REFERENCE_N as R
f=lambda r: hill((r-1)/(FIT_TOP_N-1),C,S); g=lambda r: hill((r-1)/(R-1),C,S)
print([(r, round(f(r),1), round(g(r),1), round(100*(g(r)-f(r))/f(r),2)) for r in (50,100,200,400)])"
```
→ `[(50, 4694.3, 5314.0, 13.2), (100, 2884.2, 3419.0, 18.54), (200, 1573.6, 1931.3, 22.73), (400, 794.3, 995.8, 25.37)]` **(re-run)**.
Artifact: `evidence/W30/percentile-train-serve-skew.json`.

### 9.6.2 Scale hazards that are correctly handled

- **KTC vs IDPTradeCalc are directly comparable** and the code treats them so. Measured over
  475 shared rows: median value ratio **1.000** (p10 0.888, p90 1.054); both boards top out at
  9999, so no rescaling is applied (`F-035`, `src/league_intel/cross_market.py`).
- **The scraper composite runs ~1.131× the board**, and `src/trade/finder.py:485-500` now
  documents both branches' scales in place after a 2026-07-29 correction that found them
  "exactly backwards". `_offenseOnlyFinalAdjusted` is on the **board** scale (median
  `_offenseOnlyFinalAdjusted / rankDerivedValue` = 0.994 over 522 assets), the composite is
  not, and `_score_trade` substitutes one for the other inside a single subtraction — so
  sharing a scale is the correctness requirement, and it is met on the live path.
- **The value-bundle scale contract** (`F-004`): `overall` / `finalAdjusted` / `displayValue`
  are the board value **or `None`** — never seeded from the composite. Pinned by
  `tests/api/test_value_bundle_scale_contract.py` and
  `tests/audit/test_formula_registry.py:157-163`.

### 9.6.3 Absolute thresholds on a relative scale — flagged, not proven wrong

Three formulas apply fixed point cut-offs to a 0-9999 board whose spacing is not uniform:
`F-115` trade fairness (`|gap| < 256` even, `< 769` lean), `F-136` waiver upgrade tier
("2000+ gap means dropping this player nets a starter-tier replacement"), `F-183` confidence.
A 256-point gap means something different at the top of the board than at the bottom. No
measurement of the resulting misclassification rate exists; this is recorded as an assumption,
not a defect.

---

## 9.7 Leakage

"Leakage" here covers three distinct things, and they should not be conflated.

### 9.7.1 Train/serve leakage — one instance, open

W30-F008 (§9.6.1 defect 1) is a train/serve skew: the promotion gate's holdout RMSE (787.84
for the champion) is not a measurement of the served board's error, because the curve is
evaluated outside the coordinate system it was scored in. `docs/audits/formula-registry.json`
already carries this as `percentile-reference` → `"TRAIN/SERVE SKEW, open"` **without a
magnitude**; this audit attaches one.

### 9.7.2 Temporal leakage in the offline backtests — real, zero user surface

W04-F009 (**rescoped** P1 → P2). The archived exports carry the raw scraper composite only, so
every "historical" backtest blends **today's** source CSVs into a weeks-old payload. The
verifier strengthened the proof and then cut the scope:

- The archive's `_canonicalSiteValues` carries exactly **three** keys across all 1,074 players
  (`idpTradeCalc` 814, `ktc` 464, `ktcSfTep` 464). The other 18 voters can only have come from
  `CSVs/site_raw/` at the paths hardcoded at `data_contract.py:279-470`.
- `pfkDynasty.csv` and `fantasyNavigatorSf.csv` were **first added to the tree on 2026-08-03**.
  They could not have contributed to any board served on 2026-07-14, yet they vote in its
  "replay". That is an airtight temporal leak, and all three cited backtest scripts do it.
- **Scope corrected:** the authored blast radius (1,092 players / 100 routes / 38 pages) is a
  category error. No route serves a backtest and no page renders one. The artifacts actually
  affected are 7 files in `reports/`, 3 scripts, 2 source comments, and the tuning *provenance*
  of `alpha = 0.10`, the MAD lambda and `_PERCENTILE_REFERENCE_N`.
- **The authored conclusion "no model in this repository may be described as validated" does
  not follow** — `src/model_registry/board_holdout.py` scores against realized 2025 points.

W04-F010 adds that the caveat is present in **1 of 9** backtest scripts and **0 of 7**
committed reports. `reports/percentile_reference_n_backtest_full.md` still ends at
"**Promote N=400** (+2.01% vs N=500 on the value-weighted metric)" with nothing after it, and
`scripts/backtest_percentile_reference_n.py:212` emits "The design-choice justification (KTC
pool size, retail market scale) is empirically validated" on the N=500 branch — twelve lines
after its own self-refutation.

### 9.7.3 Cross-scale value leakage into a user surface — fixed, with a residual path

`F-002`: the raw scraper composite leaked to `/arbitrage` until 2026-07-27 (WS-J F-6 / audit
finding K). At HEAD the live path reads the canonical board —
`src/trade/finder.py:977` binds `board_values = board_values_from_contract(contract)` and
`:466` branches on it. **The composite-scale branch still exists as a fallback**
(`finder.py:497-504`) for callers that pass no contract, and `_finalAdjusted` is still read at
`:1006` as the composite-scale threshold for the `assetsUnpricedByBoard` count. That is
deliberate and documented in place; it is worth knowing it is there.

### 9.7.4 What is structurally leak-proof, and verified

- **BDVM fundamentals take zero market input.** `src/bdvm/market.py` runs strictly after the
  fundamentals and reads only value-signal sources — never the rank-signal synthetic encodings
  in `canonicalSiteValues`. BDVM never writes `rankDerivedValue` (`F-003`, `F-119`).
- **The league-adjusted lens never mutates the shared contract.** `latest_contract_data` is a
  module global; `overlay.adjusted_rows` reprices a shallow copy, so one league's roster shape
  cannot silently reprice another's board (`F-036`, `F-037`).
- **News-derived events cannot move a mean.** Auto events land at `confidence = 0.45 < 0.5`,
  which suppresses every non-sigma channel and clamps `sigma_mult >= 1.0` — a headline can
  widen uncertainty but never move a mean or narrow σ (`F-202`).

---

## 9.8 Reconciliation against `docs/audits/formula-registry.json`

The registry is enforced by `tests/audit/test_formula_registry.py`, which **passes: 11 tests,
0.03s** at HEAD **(re-run)**.

### 9.8.1 Is it true at HEAD?

**Fourteen of sixteen entries are accurate about the implementations they name.** Every one of
the four spot invariants really is enforced, and the `REMOVED`-disposition check genuinely
catches resurrection (it looks for the construct via `removedMarker`, not merely the file).

Two entries are stale (W30-F010):

| Entry | Registry says | At HEAD |
|---|---|---|
| `starter-slots` → `frontend/lib/league-analysis.js::STARTER_SLOTS` | live divergent duplicate, `DL/LB/DB = 2` | **line 48 is a comment** describing the constant that was removed |
| `starter-slots` → `frontend/lib/portfolio-insights.js::defaultSlots` | live divergent duplicate | **0 matches** — the construct does not exist |

Both were replaced by the shared `frontend/lib/starter-slots.js` (`F-055`), which the registry
does not mention. `test_consumer_and_live_duplicate_paths_resolve` asserts only that the named
**file** exists, so a stale construct name inside a surviving file passes.

*How to re-run:*
`grep -n 'STARTER_SLOTS' frontend/lib/league-analysis.js; grep -c 'defaultSlots' frontend/lib/portfolio-insights.js; .venv/bin/python -m pytest tests/audit/test_formula_registry.py -q`
→ `48: // \`STARTER_SLOTS = …\``, `0`, `11 passed` **(re-run)**.

### 9.8.2 Is it complete?

No. **16 recorded concepts against 126 inventoried; 11 registry entries carry at least one
duplicate; 70 inventory rows carry a duplicate pointer.**

| Concept with ≥2 live implementations | In the registry? |
|---|---|
| Playoff odds (2 engines) | **absent** |
| Championship odds | **absent** |
| Power rankings (2 engines) | **absent** |
| Replacement level (4) | **absent** |
| Contender / rebuilder (6 classifiers) | **absent** |
| `detect_tiers` (2 functions, same name) | **absent** |
| Movement indicators (2) | **absent** |
| Positional need / demand (2, different units) | **absent** |
| Confidence label (3) | partial — only `market-confidence`, with `duplicates: []` |
| Buy / Sell / Hold | present, `duplicates: []` — against 5 producers (W30-F012) and 14 reachable emitters (W12-F003) |
| Team value (3) | **present and correct**, `documented-divergence` — but the 4th consumer of the same terms, `F-056`, is not listed |
| Starter slots | present, and 2 of its 3 duplicates no longer exist (§9.8.1) |

The registry's checks are file-existence plus four spot invariants. **Nothing detects an
unregistered concept**, so the mechanism whose stated value is that "a new duplicate
implementation of an already-owned concept shows up as a diff against this file" cannot see
the duplicates that already exist (W30-F009).

> **Correction to the shard.** W30-F009's `numericProof` records `expected: 16, actual: 5`
> under the formula "concepts recorded / concepts with more than one implementation". That `5`
> is not reconstructible from the finding's own observed text, which names **11** omitted or
> understated concepts, and I could not reproduce it. The defensible figures are the ones in
> this section: 16 / 126 / 11 / 70, each re-run above.

### 9.8.3 What the registry gets right and should keep

- `percentile-helper` already carries `canonical: "NONE — five incompatible definitions"` with
  each variant's tie convention spelled out. This audit only added the numbers.
- `transaction-windows` carries the strongest invariant in the file: *"Nested time windows are
  NEVER summed. Where recency needs a single number, it is a RATIO between windows, which
  cannot double-count because division by a superset cancels shared events."*
- `te-premium` records the **rejected alternative** with its score (rank-space shift, mean abs
  error 0.175 vs the adopted 0.090). Recording what was measured and *not* adopted is rare and
  should be the pattern for the other entries.
- `market-confidence` states its own known debt honestly: divisor 8.0 is "a fossil of the ~10-site
  era", structurally capping confidence at 0.594 under the deliberate 2-source model.

**Required repair (W30-F009, W30-F010):** add the missing concepts, and give every duplicate
entry a marker literal checked the way `REMOVED` entries already are, so a fixed divergence
cannot keep being reported as live.

---

## 9.9 Validation: unvalidated is not the same as wrong

### 9.9.1 Two prior systemic claims, corrected under verification

The prior audit's seven systemic problems open with two claims about the mathematics. Neither
survives as filed.

**"The benchmark that grades the core curves is not independent of them" — OVERTURNED**
(W04-F001, authored P1, final **P3**). The verifier reran the reproduction, confirmed its
literal output, and rejected the conclusion:

- The gate does not read the board. `holdout.py:251-265` loads each holdout board's **raw
  CSV**, converts it to (percentile, `value/top × 9999`) pairs via `_percentile_pairs`
  (`:131-145`) and takes the RMSE of the candidate Hill curve against those pairs
  (`:161-162`). It never reads `rankDerivedValue` or any pipeline output. "The benchmark is not
  independent of the board it grades" is a category error — the thing graded is a *curve*.
- The inference runs backwards. A curve that reproduces FantasyCalc's published value **shape**
  converts FantasyCalc's rank vote into a value closer to what FantasyCalc actually says. That
  is a more faithful translation, not a more circular one.
- The strongest leg is measurably false. `fantasyNavigatorSf` does carry
  `correlation_group = 'ktc'`, but its normalized percentile→value curve is the **furthest from
  KTC's of all nine boards** (RMSE 1933.2) — further than every training board and every other
  holdout — and it is the worst-scoring holdout in every recorded verdict (1185.15 on v1,
  1148.53 on v2). It penalises a KTC-shaped curve rather than smuggling KTC back in.
- The `claimUnderTest` was a straw man. `holdout.py:33-40` says the opposite in its own words:
  *"It does NOT measure accuracy against reality. Every holdout source is another consensus
  market, correlated with the training sources by construction… There is no ground truth."*
  That text is serialised into **every recorded verdict** as `_semantics.doesNotMeasure`.
- **Residual, retained:** a P3 policy asymmetry — `holdout.py:69-73` excludes `ktcSfTep` by name
  for KTC-derivation while including `fantasyNavigatorSf`, which the same repo labels
  `correlation_group='ktc'`. Measured to have no effect on the criterion.

**"Every tuned constant was selected against a stability metric; none against accuracy" —
RESCOPED** (W04-F008, authored P1, final **P3**).

What survives, re-verified: the four constant-tuning reports *do* optimise mean absolute change
in `canonicalConsensusRank`; `backtest_blend_params.md:8` really does say "Lower = more stable
= probably better-calibrated", an unearned inference in a committed report;
`MIN_FULL_COVERAGE_DEPTH = 60` (`src/canonical/idp_backbone.py:304`) really has no backtest;
and there is no forward-looking realized-outcome join for the market board.

What died:

- "Three of five constants do not match their own report's recommendation, with no note
  anywhere saying why" — **false for all three**. `data_contract.py:5375-5395` is an 18-line
  comment naming the α = 0 stability optimum, calling it "product-bad" *verbatim*, and stating
  the chosen cell; `:5402-5429` documents the λ retirement and its reason; `:5297-5303` gives
  the structural reason for `N = 500`.
- "N ships 500 against its own 400 recommendation" — the verifier **tested it**:
  `tests/canonical/test_ktc_reconciliation.py` fails **9 of 13** at N = 400. N = 500 satisfies
  an enforced gate the churn metric does not measure.
- "Stability was adopted as a proxy and then read as if it were the target" — the opposite is
  documented. `docs/architecture/optimization-target.md` declares **market consensus fit** with
  per-rank tolerance bands (±2pp ranks 1-50, ±3pp 100-150, ±10pp 200-400), pinned by the test
  above, and has a section "What this target is NOT optimizing for" whose first bullet is
  "Predictive accuracy on future trades — that would require a labeled trade corpus we don't
  have."

The honest residual: **the constants are unvalidated against outcomes, which the repo says out
loud.** "The constants are wrong" is unsupported.

**A third correction worth carrying:** W04-F003 (**rescoped**, authored P1, final P2) — **four** shipped Hill constants
have no out-of-sample score, not six. The `HILL_ROOKIE` pair is not routed
(`data_contract.py:6889-6893` returns only GLOBAL / IDP / OFFENSE; the contract stamps
`routed: false`), and reverting ROOKIE to v1 changes **0 of 1092 rows**. The
−34.6% / −23.9% / −15.0% figures in that finding are *curve* deltas at fixed percentiles, not
board deltas: rebuilding the live contract with the IDP pair reverted moved **183 of 287** IDP
rows, **mean −2.69%**, with only 25 rows past 10% and a single row at −33.5%. The α = 0.10 IDP
shrinkage damps the top of the board hard.

### 9.9.2 Formulas with no validation at all

Distinguish three states.

**(a) Nothing to validate — the concept does not exist.** Four inventory rows are `Missing`:

| ID | Concept | Evidence of absence |
|---|---|---|
| `F-142` | Super sharp score | `grep 'super.?sharp'` over `*.py *.js *.jsx *.md *.json` returns nothing |
| `F-178` | Perfect draft | `grep 'perfect.?draft'` over `*.py *.js *.jsx` returns nothing |
| `F-199` | Schedule optimization | No optimizer exists. `F-198` is schedule *structure*, `F-083` is schedule *luck*, `F-091`'s `schedule_adjusted` is a power component |
| `F-200` | Money / ROI | No entry fees, payouts, prizes or ROI anywhere; the single "ROI" string in the tree is a comment at `frontend/lib/draft-logic.js:2286` |

**(b) Implemented, and the constants are declared priors — unvalidated, not wrong.** These
carry tests that pin *behaviour*, and no measurement behind the *numbers*:

| ID | Constant / choice | What the code itself says |
|---|---|---|
| `F-024` | single-source haircut retention **0.30** | "a prior, not a measurement" |
| `F-032` | TEP-native flat **1.10** | "no measurement exists for TEP-native → TE++" |
| `F-054` | team ROS strength weights `.72/.18/.05/.05` | "spec-defined defaults, hardcoded in PR1… can be overridden per-league later" |
| `F-118` | consolidation `0.70` min-upgrade ratio, `0.30` stretch tolerance | priors |
| `F-119`/`F-120` | CES `theta`, `roster_spot_cost` | "labelled priors in `config/bdvm/params_v1.json`" |
| `F-173` | pick outcome distribution | the module calls these "placeholder priors" |
| `F-195` | team-assignment point tiers, `assignmentMinPoints = 15` | "the point tiers are priors" |
| `F-115`, `F-136`, `F-183` | absolute thresholds on a relative scale | §9.6.3 |
| — | `MIN_FULL_COVERAGE_DEPTH = 60` | no backtest exists (W04-F008 residual) |
| `F-038` | adjusted-board verdict | **has** a realized-outcome measurement but **no test**: `scripts/backtest_adjusted_board.py`, 572 players vs realized 2025 scoring, four framings all "no difference detected", three of four lean negative — which is exactly why the adjusted board is a toggle and not the default |

**(c) Validated for reproducibility, not for correctness.** Parity fixtures prove two
implementations agree; they say nothing about whether the shared answer is right:
`F-010`/`F-011` (rank→value), `F-130`/`F-131` (buy/sell rules), `F-160`/`F-161` (FAAB), and
`F-114` (trade letter grade — Python and JS against the shared
`tests/fixtures/trade_grade_parity_cases.json`). This is a legitimate and useful class of test
— it must simply not be cited as accuracy.

**What genuine out-of-sample machinery exists** (against the prior audit's "no output has been
validated"):

| Mechanism | What it measures | Honest about it? |
|---|---|---|
| `src/model_registry/holdout.py` | cross-market **shape agreement** of a candidate Hill curve against four boards the fit never reads | **Yes** — the docstring and every serialised verdict say it does not measure accuracy |
| `src/model_registry/board_holdout.py` | scores against **realized 2025 points** | per `CLAUDE.md`, the path the promotion gate runs on |
| `scripts/backtest_adjusted_board.py` | realized 2025 scoring over 572 players | verdict published in `docs/adjusted-board-backtest.md` and acted on |
| `src/api/data_contract.py` calibration gate | market-consensus fit within per-rank tolerance bands | pinned by `tests/canonical/test_ktc_reconciliation.py` |

Three of those four are **script-only** paths (`evidence/W30/module-reachability.json`), which
is correct for a promotion gate but means none of them runs on a request.

*Documentation defect found while checking this:* `data_contract.py:5408` cites
`scripts/backtest_mad_lambda.py` as the source of the λ value. **That file does not exist** —
`ls scripts/backtest_*.py` returns 9 scripts and it is not among them **(re-run)**.

### 9.9.3 The test suite cannot see any of this

All 6,278 Python tests and 1,754 frontend tests pass at HEAD. That is not evidence that the
duplicated concepts agree, because **no test compares them**:

| Concept | Test that imports two implementations |
|---|---|
| Power rankings v1 vs v2 | **none** — no file importing `public_league.power` also imports `ros.power_v2` |
| Playoff odds v1 vs v2 | **none** |
| Replacement level (any pair of the four) | **none** |
| KTC VA (any pair of the three Python ports) | **none** — each port's test imports only itself |
| Percentile helpers | **none** |

*How to re-run:*
```bash
grep -rl "public_league.power" tests/ | xargs grep -l "ros.power_v2"          # empty
grep -rl "public_league.playoff_odds" tests/ | xargs grep -l "ros.playoff_sim" # empty
grep -rln "league_intel.replacement" tests/ | xargs grep -ln "bdvm.replacement\|scoring.replacement_level"  # empty
```
**(re-run — all three produce no output.)**

### 9.9.4 Blocked by data, which is a result, not a gap in the audit

Eight inventory rows are `Blocked by data`: `F-003`, `F-120`, `F-133`, `F-150`, `F-173`,
`F-198`, `F-201`, `F-202`. Seven of the eight are BDVM concepts whose absent path is
`data/bdvm/`; the eighth (`F-150`) needs `data/intel/` and the platform ledger DB. The code is
present and tested against fixtures; what could not be exercised is the live numeric behaviour
on real snapshots. **This is "we could not test it", not "it is broken"**, and it should not be
reported as either a pass or a defect.

---

## 9.10 What is right

An audit that lists only defects is not an audit. These were checked and hold.

| # | Claim | Evidence |
|---|---|---|
| 1 | **The blend is exactly reproducible and deterministic.** A clean-room reimplementation fed only the stamped per-source `valueContribution` values matches `_blendedValueUncapped` on **800/800** rows, `droppedSources` on 800/800, `anchorValue` on 800/800, `subgroupBlendValue` on 800/800; two in-process rebuilds hash identically; the rebuild matches the **served** `rankDerivedValue` on **1,092/1,092** rows. | W02-F012 |
| 2 | **Three `CLAUDE.md` claims fall out of that as proven**: the retired λ·MAD penalty touches nothing, `softFallbackCount` is diagnostics-only, and the pipeline is deterministic. | W02-F012 |
| 3 | **Single-source haircut exact:** 35 rows carry `singleSourceValuePenaltyApplied` and all 35 satisfy `_blendedValueUncapped == round(0.30 × anchorValue)`. No pick row is haircut — correct, picks are exempt. | W02-F013 |
| 4 | **TE basis conversion exact:** 536 non-value-direct TE votes converted; recomputing from the stamped percentile reproduces the stamped contribution on **536/536**. Only 3 votes saturate the 9,999 soft knee and they are genuinely tied. | W02-F013 |
| 5 | **TE premium applied exactly once per source per tight end:** 0 of 781 (TE × source) stamps carry both branches; `ktcSfTep` exempt on all 73 rows; the league-adjusted overlay lists `tePremium` in `inactiveAxes`. | W27-F009 |
| 6 | **Missing data abstains rather than defaulting.** 280 of 1,092 rows publish `rankDerivedValue: null` rather than a floor. The only fabricated values are the 12 synthetic 2029 picks — clones of 2028 rows × 0.53 (2029 Early 1st: 5034 × 0.53 = **2668**, rank 207) — and they are labelled in the payload and rendered as such. | W02-F014 |
| 7 | **Exact scoring is exact.** `score_stat_line` reproduces the Sleeper host on **1,339 of 1,339** player-weeks, max \|delta\| **0.005**, inside the module's own 0.011 tolerance — measured against the 2025 predecessor league's own `players_points`. | W18-F010 |
| 8 | **The one exact lineup optimizer** (`src/ros/lineup.py`) is shared by `marginal.py`, `league_intel/replacement.py` and `api/gameplan.py` — this is what a single authority looks like. | `F-050` |
| 9 | **Starter-slot resolution was already consolidated.** `frontend/lib/starter-slots.js` replaced **six** answers, two of which were wrong (audit 2026-07-30), and resolves live host `rosterPositions` first, registry second, never a literal. | `F-055` |
| 10 | **The trade-engine gate divergence is deliberate and correct**, and both engines now read the same internal value; assets the board declines to price are counted in `metadata.assetsUnpricedByBoard` rather than vanishing. | `F-122`/`F-123` |
| 11 | **A prior finding is refuted at HEAD.** `scoreTeamTiers`' pick term now carries a net −0.1 per pick dollar, matching its docstring, and the fix documents the defect it closed. | W30-F021 (refutes `PRIOR-A03-F00`) |
| 12 | **The nested-window double count cannot return** — module deleted, board sort forbidden by a named test, `removedMarker` pinned in the registry. | `F-150` |
| 13 | **`trade_acceptance_estimate` refuses to overclaim**: capped below 1.0, explicitly never renamed to "probability", ships with `acceptanceCaveat`, because "Sleeper records only the numerator… an acceptance RATE is statistically unidentifiable". | `F-121` |
| 14 | **BDVM's `ReplacementEngine` raises rather than fabricating `R = 0`** — the strictest missing-data posture of the four replacement implementations. | `F-042` |

---

## 9.11 Dead and misdescribed math

Formulas that exist, are documented as live, and are not.

| Finding | Module | Reality at HEAD |
|---|---|---|
| W30-F011 | `src/api/chat.py` | Docstring says "Single private endpoint (`/api/chat`)". No importer; no router; absent from `evidence/openapi.json`; **`GET /api/chat` → 404** on the running server **(re-run)** |
| W30-F012 | `src/news/unified_signal_engine.py` | "single entry point for every BUY/SELL/HOLD decision" — zero importers |
| W30-F013 | `src/api/auction_power.py` | No Python caller. `frontend/lib/auction-power.js:1` calls itself a "JS mirror" of it; the mirror is the original as far as production is concerned |
| W30-F014 | `src/adapters/scraper_bridge_adapter.py` | `CLAUDE.md:895` says "live (server.py)"; no non-test construction. `docs/ONBOARDING.md:44` sends contributors to `src/adapters/scraper_bridge.py`, **which does not exist** |
| W30-F015 | `src/canonical/calibration.py` | **5 of 7 functions have zero production references** — `_parse_pick_info`, `_pick_curve_value`, `_build_legacy_pick_lookup`, `calibrate_canonical_values`, `get_calibration_params`. Only `to_display_value` (3 refs) and `_is_pick` (18) are live **(re-run)** |
| W30-F018 | `src/api/data_contract.py:4670-4690` | The market corridor clamp justifies itself as containing "the IDP calibration runaway". `_apply_idp_calibration_post_pass` and `config/idp_calibration.json` are **both absent from the tree** — the only remaining reference is a test asserting the absence. The clamp still does real work against raw blend drift; its stated reason no longer exists, so a future reader cannot tell whether removing it is safe **(re-run)** |
| W30-F020 | `src/scoring/tiering.py::detect_tiers` | Same function name as the live `src/canonical/player_valuation.py::detect_tiers:202`, different algorithm (pool-normalized effect size with grid-searched thresholds), called only by `scripts/refit_tier_thresholds.py`. The `positional_tiers` flag that nominally chooses between them is listed under `NO_GATE` in `feature_flags.py:410` — it gates nothing |
| `F-117` | `src/trade/correlation_matrix.py` | A rule-ladder correlation model with Cholesky decomposition and no caller outside tests, beside the live two-scalar model |
| `F-185` | `src/canonical/confidence_intervals.py` | Gated by `value_confidence_intervals`, which `feature_flags.py:409` also marks `NO_GATE` — the flag defaults False **and** gates nothing, so the gate is not the control |

The structural context (W30-F022): an AST import closure from `server.py` — absolute, relative
and `importlib.import_module` edges, package `__init__` normalised — reaches **243 of 300**
`src/` modules. **27 are script-only** (legitimate for refit, crawl and fetch tooling) and
**30 are reachable from nothing**. Confidence on that count is *medium*: a module loaded purely
by a runtime string would be a false positive, and the `src/ros/sources/*` family was caught
that way and correctly excluded.

*How to re-run:* `.venv/bin/python -c "import json;d=json.load(open('docs/master-site-audit/evidence/W30/module-reachability.json'));print(d['srcModules'], d['reachableFromServer'], len(d['scriptOnly']), len(d['neither']))"` → `300 243 27 30`.

---

## 9.12 Live per-league defects in the formulas themselves

Two that are not duplication, and are worth separating out because they produce a wrong number
today.

**Starter demand is derived per league and then ignored at three call sites** (W30-F006,
partial on `PRIOR-A14-F07`). `starter_needs_for_league('dynasty_new')` correctly returns
`{QB: 2, RB: 3, WR: 4, TE: 1}` for the 10-team no-IDP league, and `analyze_roster` honours it —
so a 3-TE roster is correctly flagged **TE surplus**. But `_generate_sell_high`
(`suggestions.py:1026`) computes `need = DEFAULT_STARTER_NEEDS.get(pos, 1)` — **2** for TE —
and slices `players[2:]`, so the surplus TE is never a sell candidate in a league that starts
one. `_generate_sell_high` does not even accept a `starter_needs` argument. `rank_score`
(`:882`) and `rank_score_breakdown` (`:921`) carry the same hardcode, so need-severity ranking
uses `dynasty_main`'s demand for every league.

The prior finding claimed "nine other call sites". **Recounted at HEAD:** of ten
`DEFAULT_STARTER_NEEDS` references, three are docstrings, three are legitimate fallbacks
(`:106`, `:146`, `:712`) and exactly **three** (`:882`, `:921`, `:1026`) are unconditional
hardcodes on a live path.

*How to re-run:*
`.venv/bin/python -c "from src.trade import suggestions as S; print(S.starter_needs_for_league('dynasty_new')); print(S.DEFAULT_STARTER_NEEDS['TE'])"`
→ `{'QB': 2, 'RB': 3, 'WR': 4, 'TE': 1}` then `2` **(re-run)**.
Artifact: `evidence/W30/starter-needs-hardcode-repro.json`.

**The rookie anchor is hardcoded to a 12-team, 6-round class** (`F-175`,
`data_contract.py:5885-5886`: `_ROOKIE_ANCHOR_LEAGUE_SIZE_DEFAULT = 12`,
`_ROOKIE_ANCHOR_ROUNDS = 6`), producing exactly 72 current-year slot picks. `dynasty_new` is a
**10-team** league. This is the same 72-row shape that made the now-removed
`draft_capital_fallback` table fire on every next-year pick (§9.5.2).

---

## 9.13 Errata in the W30 shard

Recorded so downstream readers do not propagate them. None changes a verdict.

| Where | Says | Should be |
|---|---|---|
| `formula-inventory.csv` `F-071` `inputs` | "F-072 playoff odds, F-076 championship odds" | **F-081** playoff odds, **F-082** championship odds. `F-072` is the competitive-window softmax; **there is no `F-076`** in the inventory |
| `formula-inventory.csv` `F-054` `consumers` | "rosPower (F-062), rosPlayoffOdds (F-071), trade-deadline direction (F-081)" | rosPower is **F-091**; rosPlayoffOdds is **F-081**; trade-deadline direction is **F-071** — the last two are transposed and the first is wrong |
| `formula-inventory.csv` `F-101` `consumers` | "the 0.85 sharp qualification bar (F-110)" | the sharp score is **F-140**; `F-110` is the KTC VA JS original |
| W30-F005 `observed` | "its own parity test asserts agreement to ±1" | tolerances are **RMS < 50** (`test_ktc_va_python_port.py:39-49`) and **±5** (`:108`, `:133`) — §9.4.7 |
| W30-F009 `numericProof` | `expected: 16, actual: 5` | not reconstructible; the finding's own text names **11** omitted concepts — §9.8.2 |
| W30-F011 `observed` | "absent from `evidence/openapi.json`'s 100 live operations" | the spec carries **99** GET/POST/PUT/PATCH/DELETE operations as counted here; `/api/chat` is absent either way and returns 404 |

---

## 9.14 Repair order

Ordered by (a user reads a wrong number) → (two surfaces contradict) → (a maintainer is
misled). Sizes are the shard's.

| # | Repair | Finding | Size |
|---|---|---|---|
| 1 | Stop `/rankings` and `/trade` sending `tep_multiplier` when the user has not moved the slider — or make an explicit value that equals the default take the measured curve. 129 of 809 players are repriced by up to −21.2% on every page load today. | W08-F001 (upheld), W03-F001, W07-F001 | S |
| 2 | Tie `FIT_TOP_N` and `_PERCENTILE_REFERENCE_N` together with an assertion. **Fit at 500** — serving at 400 breaks `test_ktc_reconciliation.py` (9 of 13). | W30-F008 + W04-F008 verifier | L |
| 3 | Refuse to publish playoff odds when `weeksPlayed == 0`, the posture the codebase already uses for unpriced BDVM players — or seed preseason means from a projection source. Today `/league` tells a manager he has 0% before a snap, and `src/ros/direction.py` turns that into "Strong Seller". | W30-F002 | M |
| 4 | Derive playoff spots and the owner set from one place for both engines, and stamp the producing engine on the payload so the UI can name it. | W30-F001 | L |
| 5 | Decide the `useRosPowerRankings` / `useRosPlayoffOdds` default, then make `useSettings.js:143,148` and `LeagueClient.jsx:100` quote the same answer. Surface `missingInputs` when v2 is running on 2 of 9 weights. | W30-F004, W30-F003 | XS / L |
| 6 | Thread `starter_needs` into `_generate_sell_high`, `rank_score` and `rank_score_breakdown`; make `DEFAULT_STARTER_NEEDS` private to the fallback. | W30-F006 | S |
| 7 | One percentile helper with an explicit empty-population policy, imported everywhere including the two inline copies in `window.py`. Decide whether the league minimum should read 0.0. | W30-F007 | M |
| 8 | Collapse the KTC VA to one port. If deferred: change `ktc_va.py:116,:319` to `floor(x+0.5)` and add a test that imports two ports and compares them. | W30-F005 | M |
| 9 | Nominate one team-phase classifier **per unit family** and have the others consume it. Six classifiers cannot become one — they read four unrelated input families — but four of them can. | W30-F016 | L |
| 10 | Label the Total Value tile "players only", or include picks in both paths. | W30-F017 | M |
| 11 | Either wire `unified_signal_engine.py` or delete it; then record `buy-sell-hold` in the registry with its real duplicate list. | W30-F012, W12-F003 | M |
| 12 | Add the 11 missing concepts to `formula-registry.json`; give every duplicate entry a marker literal checked like `REMOVED` entries; add a test that fails when a module defines a function whose name matches an existing canonical entry. | W30-F009, W30-F010 | M / XS |
| 13 | Measure TEP-native → TE++, or state on the methodology panel that TE values from TEP-native sources carry a prior rather than a measurement. | W30-F019 | M |
| 14 | Re-derive and restate the corridor clamp's justification against raw blend drift, or measure whether it still changes any row. | W30-F018 | XS |
| 15 | Run the module-reachability closure in CI and require a new unreachable module to carry an explicit marker. Fix `CLAUDE.md:895` and `docs/ONBOARDING.md:44`. | W30-F022, W30-F014 | L / XS |
| 16 | Rename one `detect_tiers`; wire the effect-size version or record it in the registry as the deliberate offline tool it is. | W30-F020 | S |
| 17 | Fix the dangling `scripts/backtest_mad_lambda.py` citation at `data_contract.py:5408`, and carry the temporal-leakage caveat into the 8 backtest scripts and 7 reports that lack it. | W04-F008 verifier, W04-F010 | XS |

---

*Sources: `docs/master-site-audit/evidence/registry/W30.jsonl` (22 findings);
`docs/master-site-audit/evidence/W30/formula-inventory.csv` (126 concepts);
`docs/master-site-audit/findings.json` (431 published findings, 24 verified —
5 upheld, 18 rescoped, 1 overturned); `docs/master-site-audit/evidence/prior-index.json`
(531 prior findings from `docs/audits/decision-intelligence-audit-2026-08-04.registry.json`);
`docs/audits/formula-registry.json` (16 concepts). Method and status vocabulary:
`docs/master-site-audit/AUDIT_PROTOCOL.md`. Feature-by-feature status is in
`FEATURE_STATUS_MATRIX.md` and is not duplicated here.*
