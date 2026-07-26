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

## ADR-009 (AUDIT, pre-LI-7): the league deleted its TE premium; consensus still charges for it
**Status:** finding recorded 2026-07-26 — **no code change yet.**  This
is the §22 "audit the existing TEP pipeline first" step.  The residual
model itself lands in LI-7.

**What consensus already embeds.**  `_compute_unified_rankings`
applies TE-only, value-level multipliers during the blend:
* non-TEP-native sources (DLF, FantasyPros, Flock, …): TE
  contributions × `tep_multiplier`, default 1.15, operator slider
  clamped [1.0, 1.5]
* TEP-native sources (Dynasty Nerds SF-TEP, IDPTC): × 1.10
* KTC / `ktcSfTep` exempt — its TE++ board is the reference everyone
  else is aligned to

So a TE's `consensusValue` already carries a ~10-15% premium
calibrated for a "TEP-1.5" league.

**What this league actually scores in 2026: nothing extra for TE.**
From the canonical config, `bonus_rec_te = 0.0` and `bonus_fd_te =
1.0` — identical to `bonus_fd_wr`.  Receptions, yards and TDs are
position-independent keys.  Verified empirically through the LI-2
scorer: the same receiving line scores **21.55 as a TE and 21.55 as a
WR**.  The TE scoring premium is exactly zero.

**It used to exist and was removed.**  The 2025 season had
`bonus_rec_te = 0.35` and `bonus_fd_te = 1.35`; the identical line
scored **25.05 as a TE vs 21.55 as a WR — a +16.2% premium**.  The
commissioner deleted it for 2026.

**Consequence — the scoring-axis TE residual is negative.**  Consensus
boosts TEs ~15% for a premium this league no longer grants, so on the
scoring axis alone the league-adjusted correction is roughly
`1 / 1.15 ≈ 0.87` against non-native contributions.

**A wrong inference was encoded at the derivation site, and is now
retracted.**  `_TE_BLANKET_NON_NATIVE_MULTIPLIER` carried this
justification in `src/api/data_contract.py`:

> "Sleeper's API does not expose `bonus_rec_te` for these leagues
> (always 0.0), so the 'non-TEP fallback' is in practice the platform
> default and must reflect TEP-1.5, not a generic 1.25."

The author read an exposed zero as *missing data* and hardcoded a
premium to compensate.  The scorer disproves it: the API reports
`bonus_rec_te` faithfully and the value is a real 0.0.  The comment has
been replaced with the empirical finding, the 2025-vs-2026 numbers, and
a pointer to the golden fixtures — a wrong inference in a comment is
worse than no comment, because it persuades the next reader not to
check.  **The constant itself is deliberately unchanged at 1.15**:
moving it shifts live consensus values on the default board for every
league sharing the profile, which is a product decision.

**Profile name: verified cosmetic, do not re-raise.**  The registry
still labels this `superflex_tep15_ppr1`, now wrong on the TEP axis.
Every consumer was checked: `scoring_profile` is used only as an opaque
identifier for equality comparison and response stamping — nothing
parses `"tep15"` to derive behavior.  The staleness is documentary, not
functional, and renaming would orphan profile-keyed history for
cosmetic gain.  Leave it.

**The structural reference is MEASURED, not assumed (2026-07-26 update).**
The user confirms they removed the TE scoring premium deliberately and
separately moved to starting 2 TEs, intending to account for scarcity
structurally.  KTC publishes its **TE++ board specifically for 2-TE
leagues** — so `ktcSfTep`, already our market anchor, is a
2-TE-calibrated board.  That turns an unmeasurable assumption into an
observable: `ktc` (standard) and `ktcSfTep` (TE++) are the same board
differing on exactly this axis.

Measured across the live board:

| position | n | median `ktcSfTep / ktc` |
|---|---|---|
| QB | 69 | **1.0000** |
| RB | 134 | **1.0000** |
| WR | 185 | **1.0000** |
| TE | 74 | **1.3682** |

The two boards are byte-identical for every non-TE position, so there
is no board-scale term to control for and **the measured 2-TE
structural premium is ×1.368**.  The sensitivity bracket collapses:
controlling on WR, RB, QB, their median, or nothing at all all give
1.3682 — the estimate is invariant to the control choice, unlike the
earlier assumption-based attempt.

The premium is **depth-graded, not flat** — exactly the VOR shape one
would predict when required starters double from 12 to 24:

| TE band | measured premium |
|---|---|
| TE1-12 | 1.287 |
| TE13-24 | 1.319 |
| TE25-40 | 1.349 |
| TE41+ | 1.512 |

**Superseded: the earlier assumption-based estimate was unidentifiable
AND badly conditioned.**  Bracketing an unmeasurable "typical league"
gave a mid-TE residual spanning [−20.1, 3.08].  Root cause was a pole
in the multiplicative form `(V − R_ours)/(V − R_ref)` at `V = R_ref`,
not merely wide uncertainty — an estimator defect.  It is discarded in
favour of the market-measured calibration above.  Recorded because the
failure is instructive: a multiplicative residual against a replacement
level is ill-conditioned for players near that level.

**Consequence for the existing multipliers — right size, wrong reason.**
The blend gives non-TE++ sources ×1.15 and TEP-native ×1.10, justified
as a *scoring* premium that does not exist.  The market says the real,
structural need is ~1.29–1.51 depending on depth.  So the constants are
in the right neighbourhood by luck, are **flat where the market is
depth-graded**, and rest on a retracted rationale.  Changing them moves
live consensus for every league on this profile — a product decision,
deliberately not taken here.

**Market anchor is CLEAN — verified in code, not from the comment.**
`ktcSfTep` embeds the 2-TE premium already, so if it also received the
+10% native multiplier that would be a live double-count on the anchor
itself.  It does not: `data_contract.py` line ~6701 reads
`if row_is_te and source_key not in _TE_BLANKET_KTC_EXEMPT_KEYS:` and
that single guard wraps **both** multiplier branches, with both `ktc`
and `ktcSfTep` in the exempt set.  Pinned by
`tests/league_intel/test_te_premium_invariants.py`, which also fails if
a refactor moves either branch outside the guard.  No action needed —
recorded plainly so this is not re-raised.

**Partially offset by structure, which must NOT be double-counted.**
The league starts **2 dedicated TE slots**, and LI-5's endogenous
measurement shows TE demand is exactly 2.00/team — TE never wins a
FLEX slot.  That is a real, structural TE premium that scoring-based
reasoning alone would miss.  The LI-7 residual is therefore the NET of
a negative scoring-axis term and a positive structural term, computed
against what consensus already embeds — never applied on top of it.
The spec's non-duplication test exists precisely to pin this.

## ADR-008: replacement levels use endogenous flex allocation, and scarcity stays six numbers
**Context:** LI-5 (spec §19) needs replacement levels per position.
The conventional shortcut is to preassign flex slots by an even split
across eligible positions (a FLEX contributes 1/3 to each of RB/WR/TE).

**Finding — the shortcut is badly wrong for this league.**  Now that
the optimizer is exact (ADR-007), the actual fill rates are directly
measurable.  On the live 12-team pool:

| slot | who actually fills it (12 teams) |
|---|---|
| FLEX ×2 | WR 12, RB 12, **TE 0** |
| SUPER_FLEX | **QB 9**, RB 2, WR 1 |

Endogenous vs even-split starters per team: **QB 1.75 vs 1.25
(understated 40%)**, **TE 2.00 vs 2.92 (overstated 46%)**, RB 3.17 vs
2.92, WR 4.08 vs 3.92.  A preassigned model would misprice the two
positions the format most distorts — precisely the ones a superflex
TE-premium league exists to distort.  Hybrid IDPs also move real
volume: 5 LBs start in DL slots and 4 CBs in DB slots.

**Decision:** starter thresholds are measured by running the exact
optimizer over every real roster and recording what it started —
never by preassigning flex.  ``measure_endogenous_starters`` returns
starters-per-team, each team's *marginal* (weakest) starter per
position, and the raw slot→position fill counts for audit.

Four tiers, each answering a different question: ``starter`` (median
of team marginals — the typical last starter), ``bestBallStarter``
(the deepest anyone dips — the honest "startable" floor when there is
no set lineup), ``roster``, ``waiver``.  Rank-indexed tiers read a
smoothed band (±2 ranks) rather than a single rank, so no threshold is
hostage to one player's projection; the starter tiers are smoothed by
averaging across teams instead.

**Scarcity stays six separate numbers** (lineupScarcity,
rosterScarcity, waiverScarcity, eliteSeparation, starterSeparation,
replacementGap).  Collapsing them destroys the distinction between
"this position is top-heavy" and "there is nothing on waivers" — those
call for opposite roster moves.  On live data QB shows
waiverScarcity 0.75 against RB's 0.21, which is the single most
important scarcity fact about a superflex league; a blended score
would bury it.

**Two deviations from a naive reading of the spec, both deliberate:**
1. *Unpriced players are excluded from the level pools.*  Teams carry
   unranked dart throws; reading the roster tier off the literal last
   body returns 0.0 for most positions and collapses every downstream
   ratio.  They still appear in ``rosteredCount`` (vs ``pricedCount``).
2. *``waiverScarcity`` is measured against the best-ball starter floor,
   not the last rostered player.*  The roster tail is the noisiest
   number in the league and absorbs every identity-join miss, while
   the decision it informs — "if I lose a starter, how far do I fall?"
   — is about the startable floor.
**Status:** accepted 2026-07-26.

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

**Known gap (deferred at LI-3, FIXED in LI-5):** `_positional_coverage`
scored only QB/RB/WR/TE depth against a hardcoded table.  Measured on
the live pool it returned **exactly 100.00 for all 12 teams** — not
merely IDP-blind but a *constant*, contributing a flat 5 points to
every composite and discriminating nothing.  LI-5 replaced it with a
slot-derived, demand-weighted, eligibility-aware score (see the
before/after in the LI-5 PR body).  Callers that don't pass
`starter_slots` keep the historical offense-only behavior, so nothing
outside ROS shifts silently.
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
