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

## ADR-006: Sleeper scoring is a pure dot product — there are no stacking rules
**Original idea (ADR-005 wording):** scoring is a
"dot-product-**with-stacking-rules**" over Sleeper keys, implying the
scorer needs per-family logic (does the pick-six `pass_int_td` suppress
`pass_int`? does a distance band replace base `rec`? is `bonus_fd_*`
derived from `rush_fd`/`rec_fd`?).
**Finding (LI-2, empirical):** there are **no stacking rules to encode**.
Sleeper's host awards exactly

    Σ stat_line[k] × scoring_settings[k]   over  k ∈ stat_line ∩ scoring_settings

with zero exclusions, precedence, or de-duplication — verified on
1,415/1,415 rostered player-weeks (2025 weeks 1/8/17) within 0.011, plus
two full team totals.  Every "does X stack with Y" question collapses to
"does the host emit both keys in the payload", and it always does.
Two corrections to earlier assumptions fall out of this:
1. **`bonus_fd_<pos>` is a precomputed STAT key, not a derived bonus.**
   SETTINGS_AUDIT.md originally read it as a bonus applied per first
   down gained (implying the scorer must derive it from `rush_fd` +
   `rec_fd`).  It is not: Sleeper ships `bonus_fd_qb/rb/wr/te` in the
   weekly stat payload already equal to first downs gained
   (`bonus_fd_rb == rush_fd + rec_fd`; the QB variant also counts
   `pass_fd`).  The scorer multiplies it directly.  The generic
   `pass_fd`/`rush_fd`/`rec_fd` keys carry rate 0 in this league and
   contribute nothing.
2. **`idp_blk_kick` and `blk_kick` never co-occur.** Individual
   defenders carry only `idp_blk_kick`; plain `blk_kick` appears
   exclusively on TEAM/DEF pseudo-rows, which this league cannot roster.
   No suppression logic is needed to avoid double-counting.
**Decision:** `src/league_intel/scorer.py` stays a pure dot product.  Do
NOT add per-key special-casing — if a future score fails to reconcile,
the bug is in the stat line or the rates, not in missing stacking logic.
Any downstream consumer (projection re-scoring, replacement levels,
best-ball sim) can treat scoring as linear in the stat vector, which
also makes it trivially differentiable/decomposable for explanations.
**Caveat:** base `rec` had rate 0.0 in the 2025 validation season, so
its stacking with the distance bands is implied by the zero-exception
mechanics rather than directly observed at a nonzero rate.  Re-confirm
after 2026 week 1 scores.
**Status:** accepted 2026-07-26; supersedes the "with-stacking-rules"
phrasing in ADR-005.  Evidence: docs/league-intelligence/SCORING_VALIDATION.md,
tests/league_intel/test_golden_scoring.py.
