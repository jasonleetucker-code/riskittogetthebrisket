"""Generate docs/master-site-audit/evidence/W30/dead-code-map.csv (prompt section 44).

INVENTORY ONLY — nothing is deleted, nothing is recommended for deletion without
a disposition column saying so explicitly.
"""

from __future__ import annotations

import csv
import pathlib

COLS = [
    "id",
    "category",
    "item",
    "path",
    "evidence",
    "reachable from",
    "disposition",
    "why",
]

R: list[dict[str, str]] = []


def add(*v):
    assert len(v) == len(COLS), v[0]
    R.append(dict(zip(COLS, v)))


# ── abandoned branches / retired systems ─────────────────────────────
add(
    "D-001",
    "abandoned branch",
    "Offline canonical-build path",
    "src/canonical/transform.py, src/canonical/pipeline.py, scripts/canonical_build.py",
    "all three paths absent; grep CANONICAL_DATA_MODE over *.py *.js returns nothing",
    "nothing",
    "retain (already removed)",
    "CLAUDE.md declares it retired and the tree agrees — this row records the check, "
    "not a defect",
)
add(
    "D-002",
    "abandoned branch",
    "computeUnifiedRanks frontend blend (~280 lines)",
    "frontend/lib/dynasty-data.js",
    "absent; buildRows fails fast instead",
    "nothing",
    "retain (already removed)",
    "the fail-fast replacement is what CLAUDE.md documents",
)
add(
    "D-003",
    "abandoned branch",
    "Backend page routes + _proxy_next",
    "server.py",
    "no page routes registered; a page path on :8000 returns JSON 404",
    "nothing",
    "retain (already removed)",
    "one page auth gate now (frontend/middleware.js)",
)
add(
    "D-004",
    "abandoned branch",
    "src/intel/aggregate.py trend_score",
    "src/intel/aggregate.py",
    "module absent; test forbids any sort on trendScore",
    "nothing",
    "retain (already removed)",
    "the double-counting nested-window sum the registry records as REMOVED",
)
add(
    "D-005",
    "abandoned branch",
    "Flat per-round pick table in the draft-capital fallback",
    "src/api/draft_capital_fallback.py",
    "grep 7000/4000/2000/1200 table absent; registry removedMarker check passes",
    "nothing",
    "retain (already removed)",
    "audit finding C1, fixed",
)

# ── reference code imported into production ──────────────────────────
add(
    "D-010",
    "reference code in production",
    "BDVM frozen reference implementation",
    "docs/research/bdvm-v1/reference/",
    "grep 'from docs' / 'docs.research' over src/, server.py, scripts/ returns only "
    "docstring citations — zero imports",
    "tests/bdvm/test_engine_parity.py only",
    "retain",
    "correctly kept as an acceptance fixture, never imported by src/ — the rule holds",
)

# ── old formulas still executing ─────────────────────────────────────
add(
    "D-020",
    "old formula still executing",
    "Dynasty Scraper composite (_finalAdjusted)",
    "Dynasty Scraper.py",
    "written into every data/dynasty_data_*.json snapshot the server boots from",
    "server.py startup, /api/scrape, scheduled-refresh.yml",
    "adapt",
    "still the INPUT to the canonical engine, so it must run; but it is a second "
    "value concept on a different scale and leaked into /arbitrage until 2026-07-27",
)
add(
    "D-021",
    "old formula still executing",
    "TEP-native flat 1.10 TE premium",
    "src/api/data_contract.py (TE stage)",
    "runs on every TEP-native source's TE rows on every contract build",
    "F-001",
    "replace",
    "the base->tepp path was replaced with a measured curve (ADR-015); the TEP-native "
    "path kept the flat prior, so one concept has two maths by source class",
)
add(
    "D-022",
    "old formula still executing",
    "MAD volatility penalty scaffolding",
    "src/api/data_contract.py:5429 (_MAD_PENALTY_LAMBDA = 0.0)",
    "multiplies by zero on every row of every build",
    "F-001",
    "deprecate",
    "retired 2026-04-20; the constant and its multiply survive to keep sourceSpread "
    "as a diagnostic",
)
add(
    "D-023",
    "old formula still executing",
    "Corridor clamp rationale",
    "src/api/data_contract.py:4688",
    "the clamp runs; its in-code justification names the IDP calibration post-pass",
    "F-001 (IDP rows)",
    "adapt",
    "the mechanism it claims to contain (_apply_idp_calibration_post_pass + "
    "config/idp_calibration.json) no longer exists in the tree",
)

# ── duplicate services and schemas ───────────────────────────────────
add(
    "D-030",
    "duplicate service",
    "Two playoff-odds engines",
    "src/public_league/playoff_odds.py vs src/ros/playoff_sim.py",
    "both served live from /api/public/league/{playoffOdds,rosPlayoffOdds}; 7 vs 6 "
    "playoff spots, 12 vs 8 owners, contradictory answers for 2 teams",
    "/league Playoff Odds tab, toggled by settings.useRosPlayoffOdds (default TRUE)",
    "replace",
    "two answers to one question with no on-page statement of which engine produced " "the number",
)
add(
    "D-031",
    "duplicate service",
    "Two power-ranking engines",
    "src/public_league/power.py vs src/ros/power_v2.py",
    "both served live; 10 vs 12 teams, mean |rank shift| 2.8, max 7",
    "/league Power tab, toggled by settings.useRosPowerRankings (default TRUE)",
    "replace",
    "same as D-030",
)
add(
    "D-032",
    "duplicate service (RE-VERIFIED 2026-08-20, corrected)",
    "Two Python ports of KTC adjustPackage (was three)",
    "src/trade/ktc_va.py, src/public_league/trade_grading.py",
    "src/trade/market_value_adjustment.py is now a pure re-export of ktc_va.py "
    "(0 computation, own docstring says so) -- the rounding-bug port (floor(x+0.5) vs "
    "ktc_va's banker's-rounding original) was collapsed 2026-08-18. trade_grading.py "
    "already uses _js_round (floor(x+0.5), matching ktc_va's now-fixed rounding) and is "
    "guarded by a live cross-implementation parity fixture "
    "(tests/public_league/test_trade_grade_parity.py + "
    "frontend/__tests__/trade-grade-parity.test.js + "
    "tests/fixtures/trade_grade_parity_cases.json), 8 tests / 50 subtests passing "
    "2026-08-20",
    "trade suggestions + angle + MC + arbitrage finder (both via ktc_va.py, port B "
    "collapsed into re-export); public-league grades (trade_grading.py, still separate)",
    "adapt",
    "the ORIGINAL defect (rounding divergence, monkeypatch install, dead V12/V13 "
    "exports) is fixed per CLAUDE.md's trade-engine section and verified here by direct "
    "read + a green parity test. What remains is 2 Python implementations, not 1 -- "
    "same sanctioned-duplication shape as D-039 (a real parity test makes it safe), but "
    "whether trade_grading.py should still collapse into ktc_va.py per C3-VA-01's "
    "stated target (ONE Python port) is a Lane 2 (Claude 9, C3 trade substrate) "
    "methodology call, not decided here",
)
add(
    "D-033",
    "duplicate service",
    "Five percentile helpers",
    "src/public_league/power.py:52, src/sharp/score.py:191, src/ros/power_v2.py:99, "
    "src/roster_intel/window.py:228+238 (twice inline), src/roster_intel/profiles.py:86",
    "at n=12 the extremes read 0.0/1.0 vs 0.0417/0.9583; empty population reads 0.5 " "vs 0.0",
    "F-090, F-140, F-091, F-072, F-062",
    "replace",
    "no canonical definition exists; the registry already calls this "
    "'documented-divergence' but names it as five, not four-plus-an-index",
)
add(
    "D-034",
    "duplicate service",
    "Six contender/rebuilder classifiers",
    "frontend/lib/team-phase.js, src/ros/direction.py, src/roster_intel/window.py, "
    "src/bdvm/roster.py, src/trade/suggestions.py:803, "
    "frontend/lib/league-analysis.js:1146",
    "4, 7, 5, 3, 3 and 3 label sets respectively over four different input families",
    "/phases, /league, /api/gameplan, /bdvm, /trade, /rosters",
    "adapt",
    "some divergence is legitimate (a player-level tag is not a team classifier), but "
    "'contender' means six different things across six surfaces",
)
add(
    "D-035",
    "duplicate service",
    "Four replacement levels",
    "src/league_intel/replacement.py, src/scoring/replacement_level.py, "
    "src/bdvm/replacement.py, src/league_comparison/metrics.py",
    "value points vs PPG vs PPG vs season points; endogenous flex vs preassigned "
    "1/3 split vs greedy allocation vs single-rank",
    "/api/gameplan, awards, /api/bdvm/*, /league-comparison",
    "adapt",
    "different units make three of them genuinely different concepts; the flex "
    "convention split (endogenous vs preassigned) is not",
)
add(
    "D-036",
    "duplicate service",
    "Two detect_tiers",
    "src/canonical/player_valuation.py:202 vs src/scoring/tiering.py:201",
    "identical function name, different math (rolling-median gap vs pool-normalized "
    "effect size)",
    "data_contract.py:2033 (live) vs refit script only",
    "deprecate",
    "the scoring/ copy is behind positional_tiers, which feature_flags.py:410 marks " "NO_GATE",
)
add(
    "D-037",
    "duplicate service",
    "Two 'movers' definitions",
    "frontend/lib/market-movers.js vs frontend/lib/movers.js",
    "per-scrape stamped rankChange vs windowed 1d/7d/30d trend",
    "/ vs /trending",
    "adapt",
    "same product word, different arithmetic, different pages",
)
add(
    "D-038",
    "duplicate schema",
    "Auction power: Python module vs JS mirror",
    "src/api/auction_power.py (170L) vs frontend/lib/auction-power.js",
    "CORRECTED 2026-08-20 (C10-CLOSE-02 audit): tests/api/test_auction_power_parity.py:36 "
    "imports AuctionPowerConstants + effective_auction_power and is a LIVE cross-language "
    "parity guard -- its own docstring (:1-28) states the JS is what users see and the "
    "Python is the documented source of truth, pinning the three tuning constants so drift "
    'fails (:87: "the frontend is the one users see, and the Python file is the one '
    "documented as authoritative. Change both.\"). The prior 'zero Python importers' "
    "evidence checked src/ imports only and missed the test-suite parity guard -- the same "
    "sanctioned-duplication-with-parity-test shape this file already blesses at D-039",
    "both, via the parity test",
    "retain",
    "deleting the Python file destroys the only thing keeping the shipped JS numbers "
    "honest -- same disposition class as D-039",
)
add(
    "D-039",
    "duplicate schema",
    "Source registry mirrored in Python and JS",
    "src/api/data_contract.py::_RANKING_SOURCES vs "
    "frontend/lib/dynasty-data.js::RANKING_SOURCES",
    "tests/api/test_source_registry_parity.py parses the JS and diffs",
    "both",
    "retain",
    "a real parity test makes this safe duplication",
)

# ── obsolete feature flags ───────────────────────────────────────────
add(
    "D-050",
    "obsolete flag",
    "value_confidence_intervals",
    "src/api/feature_flags.py:63, :409",
    "self-declared NO_GATE; src/canonical/confidence_intervals.py has zero production " "importers",
    "nothing",
    "deprecate",
    "a flag that gates nothing over dead code",
)
add(
    "D-051",
    "obsolete flag",
    "positional_tiers",
    "src/api/feature_flags.py:72, :410",
    "self-declared NO_GATE",
    "scripts/refit_tier_thresholds.py",
    "deprecate",
    "same shape as D-050",
)
add(
    "D-052",
    "obsolete flag",
    "unified_id_mapper",
    "src/api/feature_flags.py:44, :411",
    "self-declared NO_GATE",
    "scripts only",
    "deprecate",
    "same shape as D-050",
)
add(
    "D-053",
    "obsolete flag",
    "dynamic_source_weights",
    "src/api/feature_flags.py:118, :412",
    "self-declared NO_GATE; src/backtesting/harness.py has no importer at all",
    "scripts/refit_source_weights.py",
    "deprecate",
    "the flag's own comment points at a harness that nothing calls",
)
add(
    "D-054",
    "obsolete flag",
    "espn_injury_feed / usage_signals",
    "src/api/feature_flags.py:101, :94, :382-383",
    "self-declared UNREACHABLE",
    "nothing",
    "deprecate",
    "the repo already labels these correctly",
)
add(
    "D-055",
    "obsolete flag",
    "depth_chart_validation",
    "src/api/feature_flags.py:108, :389",
    "self-declared SCRIPT_ONLY",
    "scripts only",
    "retain",
    "honestly labelled; a script gate is a legitimate use",
)
add(
    "D-056",
    "stale default vs comment",
    "useRosPowerRankings / useRosPlayoffOdds",
    "frontend/components/useSettings.js:143,:148 vs " "frontend/app/league/LeagueClient.jsx:100",
    "both default TRUE; the comment three lines from the read says "
    "'false until validated per-user'",
    "/league",
    "replace",
    "the comment describes the opposite of the shipped default",
)

# ── generated output treated as source ───────────────────────────────
add(
    "D-060",
    "generated output as source",
    "exports/latest + exports/archive",
    "exports/",
    "140 files tracked in git, including release zips",
    "tests/e2e/preflight.py seeds data/ from exports/latest/",
    "retain",
    "sanctioned mechanism per AUDIT_PROTOCOL; a clean checkout has no data/ snapshot",
)
add(
    "D-061",
    "generated output as source",
    "data/ tracked files",
    "data/",
    "8,198 files tracked; data/ros/ is re-included by .gitignore and "
    "refresh workflows git add -f",
    "runtime reads",
    "adapt",
    "pipeline output living in version control; CLAUDE.md documents it, which makes "
    "it deliberate rather than accidental",
)

# ── mock data reachable in production ────────────────────────────────
add(
    "D-070",
    "mock data",
    "no mock/fixture data path reachable from a live route",
    "-",
    "grep MOCK/FAKE/dummy/sample_data over src/ + server.py excluding tests: "
    "only genuine SQL placeholder helpers and BDVM 'placeholder prior' comments",
    "-",
    "retain",
    "clean — recorded because the absence is the finding",
)
add(
    "D-071",
    "placeholder in production",
    "BDVM pick outcome priors",
    "src/bdvm/picks.py:6, :52",
    "the module calls its own numbers placeholder priors",
    "/api/bdvm/values pick rows, /draft panel",
    "adapt",
    "honestly labelled in code but not on the surface that renders them",
)
add(
    "D-072",
    "placeholder in production",
    "Franchise award shelf",
    "src/public_league/franchise.py:11",
    "'award shelf placeholder (later prompt wires real awards)'",
    "/league/franchise/[owner]",
    "adapt",
    "self-declared placeholder still shipping",
)

# ── unused tables ────────────────────────────────────────────────────
add(
    "D-080",
    "table",
    "21 tables created by CREATE TABLE IF NOT EXISTS",
    "src/intel/ledger.py, src/intel/platform_ledger.py, src/sharp/roster_store.py, "
    "src/consensus_edge/snapshot.py, src/api/user_kv.py",
    "every table name has >=4 non-DDL references; none is orphaned",
    "-",
    "retain",
    "no unused table found",
)
add(
    "D-081",
    "schema versioning gap",
    "sharp roster tables outside the migration",
    "src/sharp/roster_store.py",
    "plain CREATE TABLE IF NOT EXISTS, deliberately NOT wired to "
    "platform_ledger.PLATFORM_SCHEMA_VERSION",
    "sharp roster crawl",
    "retain",
    "documented tradeoff: bumping the version re-runs the whole platform migration "
    "to add four additive tables",
)

# ── unused scheduled jobs ────────────────────────────────────────────
add(
    "D-090",
    "scheduled job",
    "trigger-sharp-now-via-merge.yml / "
    "trigger-sharp-no-environment.yml / force-sharp-production-now.yml / "
    "check-sharp-production-now.yml",
    ".github/workflows/",
    "four one-off manual-trigger workflows for the same " "sharp-production bring-up",
    "GitHub Actions",
    "deprecate",
    "operational scaffolding from one incident, still in the workflow list",
)
add(
    "D-091",
    "scheduled job",
    "refit-hill-curves.yml",
    ".github/workflows/refit-hill-curves.yml",
    "runs weekly; produces a CHALLENGER only — promotion is a human step",
    "config/model_registry/",
    "retain",
    "verified live: championVersion 2 params match the committed constants exactly, "
    "and v3 was correctly rejected for not clearing the 25-point margin",
)

# ── unused source adapters ───────────────────────────────────────────
add(
    "D-100",
    "source adapter",
    "ScraperBridgeAdapter",
    "src/adapters/scraper_bridge_adapter.py",
    "CORRECTED 2026-08-20 (C10-CLOSE-02 audit): the original evidence's own qualifier "
    "('outside tests AND src/adapters/__init__.py') silently discarded the one importer "
    "that makes this live. src/adapters/__init__.py:1 does a top-level "
    "'from .scraper_bridge_adapter import ScraperBridgeAdapter', and server.py:2112,6002 "
    "do 'from src.adapters import sleeper_trending' -- which EXECUTES that __init__.py on "
    "every live request path touching sleeper trending. scripts/audit/"
    "measure_module_reachability.py:56 already lists src.adapters in "
    "DYNAMIC_DISPATCH_HINTS, i.e. the reachability tool already knows this package is "
    "dynamically reached; this row's disposition did not read that signal",
    "production, via package __init__ import-time execution",
    "retain",
    "CLAUDE.md:895's 'live (server.py)' claim was correct; the census's own reachability "
    "check missed the __init__.py import-time path",
)
add(
    "D-101",
    "source adapter",
    "adapters/base.py frozen contract",
    "src/adapters/base.py",
    "imported by tests only — CLAUDE.md says so and it is true",
    "tests",
    "retain",
    "kept deliberately as the interface definition",
)
add(
    "D-102",
    "stale doc path",
    "src/adapters/scraper_bridge.py",
    "docs/ONBOARDING.md:44",
    "the path does not exist",
    "-",
    "replace",
    "onboarding instructs a new contributor to edit a file that is not there",
)

# ── components unreachable from navigation ───────────────────────────
add(
    "D-110",
    "unreachable page",
    "/design",
    "frontend/app/design/page.jsx",
    "not in NAV_MODEL, SYSTEM_MODEL or " "PALETTE_EXTRA_TARGETS",
    "direct URL only",
    "retain",
    "a design-system reference page; deliberate",
)
add(
    "D-111",
    "redirect shim",
    "/finder -> /rankings, /intel -> /league/insider-trading",
    "frontend/app/finder/page.jsx, frontend/app/intel/page.jsx",
    "both are documented permanent redirects with the reasoning in-file",
    "bookmarks",
    "retain",
    "exemplary — each explains what merged into what and why",
)
add(
    "D-112",
    "live redirect target (RE-VERIFIED 2026-08-20, corrected)",
    "/draft-capital",
    "frontend/lib/nav-model.js:391",
    "no frontend/app/draft-capital directory exists, but "
    "frontend/__tests__/nav-model.test.js:25 and public-routes.test.js document + pin "
    "it as a legacy routing-layer 308 redirect declared in next.config.mjs (not a page "
    "directory) that public-routes.test.js explicitly keeps public "
    "(isPublicPath('/draft-capital') === true)",
    "pageTitleFor label lookup only (not paletteTargets); the redirect itself is "
    "routing-layer, not a page component",
    "retain",
    "NOT dead -- a page-directory absence is not evidence of dead code once a route "
    "can be declared outside app/ (next.config.mjs redirects). This is the SECOND row "
    "this same C10 pass found stale on a 'no page directory' assumption (see D-120's "
    "correction) -- neither is safe to act on from this census alone without checking "
    "for a routing-layer or test-pinned reason first",
)
add(
    "D-113",
    "unreachable page",
    "/rankings/[position]",
    "frontend/app/rankings/[position]/page.jsx",
    "not a nav entry; reached as a filter pre-seed from /rankings",
    "in-page links",
    "retain",
    "documented as a filter pre-seed reusing one code path",
)

# ── modules with no production importer ──────────────────────────────
add(
    "D-120",
    "dead module (RE-VERIFIED 2026-08-20, corrected)",
    "src/api/chat.py",
    "src/api/chat.py",
    "still zero production importers, GET/POST /api/chat still absent from server.py -- "
    "but tests/api/test_chat_layers_are_consistently_wired.py (added after this row was "
    "written) is a live, passing guard asserting exactly this: three chat layers "
    "(backend module, frontend proxy, UI caller) must be ALL wired or ALL unwired, and "
    "pins that today's intended state is ALL THREE UNWIRED pending a product decision "
    "on shipping a streaming-LLM feature. Its own docstring says explicitly: 'recorded "
    "rather than deleted -- it becomes valuable the moment the product decision goes "
    "the other way'",
    "nothing",
    "retain",
    "this was ALMOST deleted by this same C10 pass on the strength of the original "
    "'deprecate' disposition -- reading the guard test first is what caught it. NOT a "
    "case for deletion: a newer, more specific decision than this census row already "
    "governs it. The other D-121..D-129 dead-module rows have NOT been re-checked for "
    "a similar deliberate-keep guard and should not be deleted without the same check",
)
add(
    "D-121",
    "dead module",
    "src/news/unified_signal_engine.py",
    "src/news/unified_signal_engine.py",
    "zero importers in src/, server.py or scripts/",
    "nothing",
    "deprecate",
    "its docstring claims to be the 'single entry point for every BUY/SELL/HOLD "
    "decision emitted to users'; four other producers ship and it ships nothing",
)
add(
    "D-122",
    "dead module",
    "src/canonical/confidence_intervals.py + rank_history_band.py",
    "src/canonical/",
    "src/canonical/__init__.py:37 says so itself",
    "tests only",
    "deprecate",
    "self-declared dormant-pending-decision",
)
add(
    "D-123",
    "dead module",
    "src/trade/correlation_matrix.py",
    "src/trade/correlation_matrix.py",
    "no caller outside tests",
    "tests only",
    "adapt",
    "a built, tested improvement to the MC sampler that was never wired in",
)
add(
    "D-124",
    "dead module",
    "src/api/espn_schema_drift.py",
    "src/api/espn_schema_drift.py",
    "only tests/api/test_espn_schema_drift.py",
    "tests only",
    "deprecate",
    "espn_injury_feed is already flagged UNREACHABLE",
)
add(
    "D-125",
    "dead module",
    "src/backtesting/harness.py",
    "src/backtesting/harness.py",
    "CORRECTED 2026-08-20 (C10-CLOSE-02 audit): 'no importer at all, including scripts' "
    "was factually false -- tests/backtesting/test_harness.py:5 imports it. Zero "
    "PRODUCTION importers, so the deprecate disposition still stands; only the evidence "
    "string was wrong",
    "tests only",
    "deprecate",
    "feature_flags.py:406 names it as the thing dynamic_source_weights gates",
)
add(
    "D-126",
    "dead module",
    "src/nfl_data/freshness.py (transitively)",
    "src/nfl_data/freshness.py",
    "only importer is src/news/usage_signals.py, whose only importer is "
    "scripts/audit/measure_usage_signal_rate.py",
    "scripts only",
    "adapt",
    "the 'do not trust current-week data until Thursday' guard is not on any live path",
)
add(
    "D-127",
    "dead function",
    "calibrate_canonical_values + _pick_curve_value + "
    "_build_legacy_pick_lookup + get_calibration_params + _parse_pick_info",
    "src/canonical/calibration.py",
    "symbol scan over src/, server.py, scripts/: 0 production references for 5 of 7 "
    "functions; only to_display_value and _is_pick are live",
    "src/trade/suggestions.py:26 (to_display_value only)",
    "deprecate",
    "the legacy calibration pipeline is held alive entirely by its own tests",
)
add(
    "D-128",
    "dead module",
    "src/league_intel/{sim,twin,calibration}.py",
    "src/league_intel/",
    "no importer from server.py or scripts/",
    "tests only",
    "adapt",
    "league-intel simulation layer built and never wired",
)
add(
    "D-129",
    "dead module",
    "src/roster_intel/roster_source.py, src/ros/tags.py, "
    "src/nfl_data/{opportunity_stats,usage_windows,reception_shape_projection,"
    "injury_feed}.py, src/platforms/sleeper.py, src/bdvm/backtest.py",
    "various",
    "AST import closure from server.py + scripts/ + Dynasty Scraper.py "
    "reaches none of them (evidence/W30/module-reachability.json)",
    "tests only",
    "adapt",
    "30 of 300 src modules are unreachable from any entry point; 27 more are " "script-only",
)
add(
    "D-130",
    "empty placeholder",
    "src/league/",
    "src/league/",
    "contains only .gitkeep, README.md and __init__.py",
    "nothing",
    "retain",
    "CLAUDE.md documents it as an empty placeholder",
)

# ── partially-applied fixes ──────────────────────────────────────────
add(
    "D-140",
    "partially-applied fix",
    "DEFAULT_STARTER_NEEDS hardcode",
    "src/trade/suggestions.py:882, :921, :1026",
    "starter_needs_for_league('dynasty_new') returns TE 1; all three sites read "
    "DEFAULT_STARTER_NEEDS['TE'] = 2",
    "POST /api/trade/suggestions",
    "replace",
    "the per-league derivation landed but three call sites were not converted",
)
add(
    "D-141",
    "stale registry entry",
    "docs/audits/formula-registry.json starter-slots",
    "docs/audits/formula-registry.json",
    "names frontend/lib/league-analysis.js::STARTER_SLOTS (now only a comment) and "
    "frontend/lib/portfolio-insights.js::defaultSlots (absent) as live duplicates",
    "tests/audit/test_formula_registry.py checks FILES exist, not constructs",
    "replace",
    "the registry's file-existence test cannot catch a stale construct name",
)

csv_path = pathlib.Path(__file__).with_name("dead-code-map.csv")
with csv_path.open("w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=COLS, quoting=csv.QUOTE_ALL)
    w.writeheader()
    for row in R:
        w.writerow(row)
print(f"wrote {csv_path} rows={len(R)}")
disp: dict[str, int] = {}
for row in R:
    disp[row["disposition"]] = disp.get(row["disposition"], 0) + 1
for k, v in sorted(disp.items(), key=lambda kv: -kv[1]):
    print(f"  {v:3d}  {k}")
