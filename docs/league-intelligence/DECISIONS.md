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

## ADR-007: lineup.py was greedy-correct-by-accident; Sleeper eligibility is `fantasy_positions`
**Context:** ADR-004 required auditing `src/ros/lineup.py` before
replacing it.  Verdict below; implemented in LI-3.

**Audit findings**
1. *Slot source* — `starter_slots` comes from the registry via
   `src/ros/scrape.py::_flatten_starter_slots`, with a duplicate
   implementation in `src/ros/playoff_sim.py::_load_starter_slots`.
   Both were feeding the STALE 15-slot lineup; LI-1 fixed the data, so
   they now produce the correct 21 slots (K included, IDP 3/3/3, no
   IDP_FLEX).  The duplication remains — flagged for LI-8.
2. *Algorithm* — slot-ordered greedy ("walk slots most-restrictive
   first, take the best eligible unused player").  Its docstring
   claimed optimality "because per-slot decisions are independent",
   which is **false in general**.  It is optimal only while the slot
   eligibility sets form a *laminar* family (pairwise nested or
   disjoint).  That happens to hold for this league today
   (QB ⊂ SUPER_FLEX; RB/WR/TE ⊂ FLEX ⊂ SUPER_FLEX; DL/LB/DB ⊂
   IDP_FLEX; K disjoint) — so it was **correct by an unstated,
   unenforced precondition**.  One non-laminar slot (a WR/TE-only flex
   beside the RB/WR/TE FLEX) breaks it silently: no error, just a
   quietly suboptimal lineup.
3. *Double-use* — correctly prevented via a `used` player-id set.  It
   did NOT guard against the same player appearing twice in the input
   roster; now it does.
4. *K and IDP 3/3/3* — handled by the generic
   `pos == slot` fallback and the `_IDP_FAMILIES` alias map.  Fine.
   BUT `_positional_coverage` still hardcodes QB/RB/WR/TE targets and
   ignores K and all nine IDP starters — see "known gap" below.
5. **The real bug (bigger than exactness):** eligibility was checked
   against a player's single `position` string.  **Sleeper evaluates
   slot eligibility against `fantasy_positions`**, which is routinely
   wider — a pass-rushing LB ships as `position="DL"` with
   `fantasy_positions=["DL","LB"]` and is legal in either slot.  The
   live ROS path threw this away: `_hydrate_overlay_players` reads the
   NFL player dump (which carries `fantasy_positions`) and kept only
   `position`.  Every hybrid IDP was therefore locked out of half its
   legal slots, understating team strength.  Measured on real Sleeper
   best-ball weeks, position-only eligibility under-fills the optimal
   lineup on multiple team-weeks.

**Decision:** replace the core with an exact maximum-weight assignment
(weight-descending matroid greedy with augmenting paths — exact for
ANY eligibility structure, dependency-free, O(P·S·E)) behind the
unchanged `optimize_lineup` interface, and wire `fantasy_positions`
end-to-end (`scrape.py` → `team_strength.py` → `RosterPlayer`).
`RosterPlayer.fantasy_positions` defaults empty and falls back to
`position`, so existing callers are unaffected.

A canonicalization pass picks the intuitive representative among
equally-optimal lineups (higher values in more restrictive slots) so
slot LABELS stay stable for the UI; it only permutes players between
slots, never changes the multiset started, so optimality is preserved
by construction.  The two pre-existing `tests/ros/test_team_strength.py`
slot-labelling tests pass unmodified.

**Validation:** brute-force equivalence on randomized rosters, an
explicit non-laminar counterexample, and historical reconstruction
against real Sleeper best-ball weeks — **10/10 team-weeks reproduce the
host's awarded total exactly**; 8/10 pick the identical starter set,
and the 2 that differ score identically (equal-value ties).  That also
**resolves the SETTINGS_AUDIT tie-handling open question**: ties exist
and are real, and both Sleeper and the optimizer are free to break them
differently without affecting totals.

**Known gap (deliberately NOT changed):** `_positional_coverage` is a
0-100 heuristic feeding 5% of the team-strength composite and still
scores only QB/RB/WR/TE depth — in a league that starts nine IDP and a
kicker, a team with no linebackers can still score full coverage.
Fixing it changes live team-strength numbers for every team, which
needs its own before/after measurement, so it is deferred to LI-5/LI-8
rather than smuggled into an exactness PR.
**Status:** accepted 2026-07-26; ADR-004 discharged.

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
**Status:** accepted; **verdict recorded in ADR-007** (LI-3 landed
2026-07-26 — greedy was optimal only under an unstated laminarity
precondition, and eligibility ignored Sleeper's `fantasy_positions`).

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
