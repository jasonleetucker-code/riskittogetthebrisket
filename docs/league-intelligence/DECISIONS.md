# League Intelligence — Architecture Decision Records

## ADR-001: Build on the existing consensus pipeline, not beside it
**Original spec idea:** full parallel valuation system.
**Finding:** the repo already has market anchors (KTC/IDPTC), a 21-source
consensus with normalization, TEP handling, and market guardrails
(`_compute_unified_rankings`). Duplicating it would violate the repo's
"one live path" rule and create drift.
**Decision:** `leagueAdjustedDynastyValue` is computed FROM `consensusValue`
(spec §2.3 already requires this). Consensus/market code paths unchanged.
**Status:** accepted 2026-07-26.

## ADR-002: Fix the stale registry rosterSettings instead of adding a second config
**Original idea:** create a new canonical config and leave registry alone.
**Finding:** `config/leagues/registry.json` rosterSettings contradict the
live Sleeper API on 8 fields (TE, K, DL/LB/DB counts, IDP_FLEX, roster
size, taxi). Existing consumers (ros lineups, FAAB roster analysis) are
modeling a wrong lineup TODAY — leaving it stale means two configs, one
wrong.
**Decision:** the canonical league-intel config (`config/league_intel/`)
is generated from the live API with screenshot cross-validation AND the
registry rosterSettings are corrected in the same PR, with tests on every
consumer. Canonical config is versioned (`configVersion`); registry stays
the lightweight pointer it already is.
**Status:** accepted; implementation in LI-1.

## ADR-003: UI valuation-mode toggle deferred until redesign R2 merges
**Original spec idea:** implement the global toggle now (§31).
**Finding:** the redesign R2 agent currently owns `frontend/app/rankings/`
and `PlayerPopup.jsx` — the two biggest value consumers. Landing toggle
wiring into files being rewritten guarantees conflicts (spec §0 forbids
this).
**Decision:** backend-first. Value schema, versioned snapshots, and the
`getActiveValue()` selector service land now; the header toggle + per-page
adoption land immediately after R2 merges, through the stable R1 shell
(nav-model/TopBar). Until then `leagueAdjustedDynastyValue` ==
`consensusValue` (spec Phase 3 no-op requirement) so no page can show an
unvalidated number.
**Status:** accepted.

## ADR-004: Audit/extend src/ros/lineup.py rather than writing a second optimizer
**Original spec idea:** new exact best-ball optimizer (§16).
**Finding:** `src/ros/lineup.py` already optimizes projected lineups; its
slot definitions come from the (stale) registry, so its correctness must
be re-verified against the live 21-slot structure. CLAUDE.md rule 2:
prefer modifying existing architecture.
**Decision:** LI-3 first audits lineup.py (slot source, eligibility,
algorithm exactness, K/IDP handling). If the algorithm is greedy or
approximate, replace its core with an exact assignment solve behind the
same interface; add brute-force equivalence tests on small fixtures and
historical starter reconstruction vs Sleeper matchup data.
**Status:** accepted; verdict recorded when LI-3 lands.

## ADR-005: Sleeper stat keys are the event vocabulary
**Original idea:** define a custom stat-line schema.
**Finding:** Sleeper's own per-player weekly stats (already used by the
platform to award points) use the same key namespace as scoring_settings.
Scoring golden-validation is therefore a dot-product-with-stacking-rules
over Sleeper keys, and every historical player-week is directly scorable.
**Decision:** the deterministic scorer consumes Sleeper-keyed stat lines
natively; nflverse or projection-source categories map INTO that
vocabulary at the adapter layer (provenance-tracked).
**Status:** accepted; empirical stacking rules to be pinned by LI-2 golden
tests before any downstream use.
