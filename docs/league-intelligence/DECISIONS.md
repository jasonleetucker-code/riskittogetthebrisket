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

**Per-source calibration survey: exactly ONE source is measurable.**
Every publisher shipping both a standard and a TE-premium variant is
another candidate natural experiment.  Surveyed all 20 site keys on the
live board; only two pairs exist, and only one survives:

| pair | verdict |
|---|---|
| `ktc` / `ktcSfTep` | **USABLE** — cardinal scale (526× dynamic range); controls **byte-identical on all 388 non-TE rows** (69 QB + 134 RB + 185 WR), 0 of 74 TE rows identical |
| `fantasyProsSf` / `fantasyProsFitzmaurice` | **REJECTED** — rank-encoded scale (values 953800-999900, 1.05× dynamic range) |
| all 16 other sources | **no paired variant exists** — not calibratable |

**A methodological trap, caught only on the second pass.**  My first
survey reported the FantasyPros pair as *usable* with a TE premium of
1.0015 — i.e. "Fitzmaurice charges no TE premium despite being flagged
`is_tep_premium: True`".  That was an artifact.  On a rank encoding
every ratio compresses to ~1.0 **including the controls**, so the
"controls at unity" test passes vacuously and then certifies a
meaningless number.  A paired calibration therefore needs two
conditions, not one: controls at unity AND a genuinely cardinal scale.
`src/league_intel/calibration.py` enforces both and returns
`te_premium=None` — never a fallback — when either fails.

Note the KTC control is far stronger than "at unity": the two boards
carry *identical bytes* for every non-TE player, so they are provably
the same file differing only on TE.

**Rule for the 16 uncalibratable sources: do not guess.**  A source of
unknown TE posture must not inherit KTC's 1.368 by analogy.  "TEP-
native" in the registry means TE-premium *scoring*, which is a
different axis from 2-TE *structure* — no evidence links the two.  Such
sources shrink toward the measured value with an interval that widens
with ignorance, and the confidence machinery must show that widening
rather than presenting a borrowed number as measured.

**DESIGN CONSTRAINT: the premium is a live market quantity, so no
shipped code may hardcode it.**  Re-measured on the 2026-07-26 scrape,
three months after the April baseline: the structure replicates
perfectly — controls **byte-identical on all 389 non-TE rows**, depth
profile monotone 1.227 → 1.268 → 1.308 → 1.492 — but the level is
**1.3196, not 1.3682**, a real ~3.6% move.

This is not an observation about one stale file; it is a binding
constraint on the design.  A premium whose *structure* is stable while
its *level* drifts several percent per quarter cannot be captured by a
constant, and that holds regardless of what any future measurement
says.  Anything that ships must therefore:

* **recompute from current source values** at build time, never read a
  baked-in number;
* **stamp the measurement date and the observed value** so a consumer
  can see how old the calibration is;
* **surface the drift** rather than smoothing it away — a premium that
  has moved since the last recompute is information, not noise.

The committed-fixture test pins April's value only so this ADR stays
checkable; the structural assertions are deliberately banded so a
legitimate data refresh is not misread as a regression.

**Rejected: the blend-vs-anchor "TE gap" as a basis for correction.**
Proposal was to measure `blend / ktcSfTep` per player and treat the TE
distribution's excess over the QB/RB/WR distributions as a
self-calibrating correction.

*Primary reason — the quantity is mislabeled, independent of any
measurement.*  The blend already multiplies every non-exempt source's
TE contribution by 1.15 **specifically to align it to KTC's TE++
baseline**.  So `blend / ktcSfTep` measures residual misalignment
**after** that correction: it is a diagnostic of whether 1.15 is the
right constant, not an independent signal about our league.  Worse,
"correcting" the gap to zero would by construction replace blended TE
values with the anchor's — discarding exactly the multi-source
diversification the blend exists to provide — while labelling the
result a league adjustment.  **This objection holds even if every
number below came out clean.**  Numbers can be re-measured; a
mislabeled quantity stays mislabeled.

*Corroborating measurements* (on a contract rebuilt from today's
scrape).  Three property checks were run:

1. *Self-reference* — **not the problem.**  The anchor is a median 7.7%
   of a TE's blend (12-13 live sources per row).  A leave-one-out
   re-aggregation excluding the anchor moves the gap from 0.8785 to
   0.8582 — an attenuation of only 0.020.
2. *Control flatness* — **FAILS.**  Blend/anchor medians are QB 1.0032,
   RB 0.9019, WR 0.9216: a spread of **0.082 across the controls**,
   against a TE signal of ~0.12.  The TE-vs-RB gap is the same order
   as the RB-vs-QB gap, and nobody claims RB is mispriced against QB.
   There is a position-level scale effect between blend and anchor, so
   a TE-specific term is **not isolable** — the same objection that
   killed the rank-encoded calibration.
3. *Depth grading* — **non-monotone**: 1.048, 0.927, 0.803, 0.840.  The
   genuine KTC structural premium rises monotonically; this falls then
   rises, the signature of composition noise rather than structure.

There is also a conceptual objection independent of the numbers: the
blend already multiplies every non-exempt source's TE contribution by
1.15 *specifically to align them to KTC's TE++ baseline*.  So
blend-vs-anchor measures residual misalignment **after** that
correction — a diagnostic of whether 1.15 is the right number, not an
independent league signal.  Closing the gap by construction would
simply replace blended TE values with the anchor's, discarding the
blend's diversification while calling it a league adjustment.

**Verdict: no correction is licensed by this measurement.**  Recorded
because a negative result is a result — and because the failure mode
(controls not flat) is the same one the cardinal-scale guard catches
elsewhere.

**AXIS AMBIGUITY — vendor "TEP" is probably SCORING, not structure.**
Most sites' TEP settings encode a receiving bonus; KTC's slider reads
0 / 0.5 / 1 / 1.5, which is scoring-shaped.  "KTC recommends TE++ for
2-TE leagues" is advice about *when to use* the setting, not evidence
it is *computed from* 2-TE structure.  Our league moved the opposite
way on both axes — removed premium scoring, added a TE slot.

Therefore **KTC and Dynasty Nerds are downgraded from "corroboration"
to "sanity check on magnitude."**  Their measurements may be a
different quantity of similar size, and an earlier claim of
independent corroboration over-reached.  Only our own derivation is
unambiguously structural: it computes replacement at N vs M required
TE starters on our pool, which is the structural effect whatever any
vendor encodes.  It stands alone, and that is now the point.

**Front-loaded so a future reader does not misread a two-way result:**
if Dynasty Nerds' standard array turns out rank-encoded, it registers
as **absent**, not as a disappointing third point — an ordinal
displacement cannot be converted to a comparable premium without DN's
own value curve (see the portability note below).  A two-way result is
the expected strong position, not an incomplete one.

**ASYMMETRIC ENDPOINTS WERE THE DOMINANT ERROR (2026-07-26).**

Read this section before any TE number is quoted.  Two smaller
corrections are recorded below it, but the endpoint asymmetry moved the
premium further than either, and it is the one that produced a false
corroboration.

***THE DOMINANT ERROR: the endpoints were asymmetric.***
The premium compares a 1-TE reference against our 2-TE league.  Every
figure so far measured the league endpoint from data while *assuming*
the reference was 1.0 TE/team.  It is not.  Re-solving the **1-TE
vector over the same weekly scores**: TE won **27.2% of FLEX** slots
and teams started **1.608 TE/team**.

| basis | ref | league | median premium | TE1-12 |
|---|---|---|---|---|
| assumed 1.0 / naive 2.0 | TE12 | TE24 | 1.239 | 1.175 |
| assumed 1.0 / actual 2.215 | TE12 | TE27 | 1.316 | 1.214 |
| assumed 1.0 / rostership 2.71 | TE12 | TE33 | 1.416 | 1.252 |
| **SYMMETRIC actuals 1.608 → 2.215** | **TE19** | **TE27** | **1.121** | **1.082** |
| *KTC measured* | | | *1.320* | *1.227* |

The structural demand change is **1.378×** (2.215/1.608), not 2.215×.
An assumed reference overstates it by **1.61×**.  **Operative
structural premium: ~1.12**, down from every prior figure.

**⚠ NEVER CITE THE 1.316 ROW AS VALIDATION.**  It lands within 0.004 of
KTC's measured 1.320, which looks like striking independent
confirmation and is not.  It pairs a *measured* league endpoint with an
*assumed* reference; the agreement is a direct artifact of the
asymmetry.  This is the **third** false corroboration this workstream
has produced — after the rank-encoded FantasyPros "1.0015 premium"
(an artifact of scale compression) and the naive-cut 1.239 "agreement"
(an artifact of the same asymmetry, in the other direction).  All three
looked like a second independent source landing on our number.  The
standing rule: **an external check that agrees with a number derived
under an assumption is not evidence; it is the assumption reflected
back.**

*A decomposition this enables.*  If the pure structural change warrants
~1.12 and KTC's TE++ charges 1.32, the residual ~1.18× is plausibly the
**scoring** component of KTC's TEP setting.  That is the first
quantitative support for the axis-ambiguity hypothesis, which had lost
its evidence when the earlier divergence turned out to be our own
measurement error.  Suggestive, not established.

**Smaller correction 1 — the projection-path defect is real.**
`measure_endogenous_starters` optimizes on `rosValue`, a season-long
MEAN, and best ball pays for weekly spikes.  Re-solving the current
21-slot vector over actual 2025 weekly scores (158 team-weeks solved,
12 skipped):

| | projection path (rosValue) | weekly actuals |
|---|---|---|
| FLEX TE share | **0.0%** | **10.4%** |
| TE started/team | **2.00** | **2.215** |

"FLEX never takes a TE" was an artifact of point estimates.  The
`replacement.py` module docstring asserted it as a finding and built a
40%/46% mispricing argument on it; both are corrected there so the
artifact is not propagated to the next reader.

**Smaller correction 2 — the 3.79 → 2.28 mapping was invalid.**
**3.79 is not `starters_per_team`.**  It was "marginal-weighted
effective depth" (`sum(mean_marginal_by_rank) / mean_marginal_TE1`)
from the marginal best-ball probe — *how many TEs carry value*, not how
many *start*.  Different quantities; the substitution is not valid.
3.79 was also already retired for a 2.08× churn confound.  What feeds
`replacement.py`'s scarcity path is `starters_per_team`, which for TE
was **2.00** — so the real before/after is **2.00 → 2.215**.

*Roster-era bias — sign settled, magnitude minor.*  Live 2026 rosters
carry 5.42 TE/team against 5.02 in 2025 (+0.40, ~8%).  Direction is UP:
the 2025 pool was slightly thinner, so TEs look scarcer than they now
are and the premium is marginally **overstated**.  My earlier claim of
a downward bias was wrong.  At n=12 the size is within noise.

*Exclusion bias — measured, and it runs the safe way.*  12 of 170
team-weeks failed a 21-slot solve.  Those rosters carry **more** TEs
(6.17) than retained ones (5.02) and are short elsewhere (mean roster
53.6, gaps at K/IDP).  So the retained sample skews TE-*shallow* and TE
demand is if anything **understated** — the opposite of the feared
direction.

*Durable fix — decision:* **calibrate the depth constant from actual
weekly outcomes (option a).**  Depth is a league-structure constant, so
history is the right input, and it avoids stacking a second fitted
layer.  The Gaussian weekly model in `playoff_sim.py` is itself an
approximation; using it to derive a structural constant would embed its
error in the premium.  Option (b) remains the right tool for
forward-looking *per-player* variance work, where no history exists for
the specific player-season.  The constant must still be **recomputed**
rather than frozen, per the drift constraint above.

*Caveats, all structural:* a single season; 2026 rules applied
counterfactually to 2025 rosters; 158/170 team-weeks solved; missing
`players_points` treated as 0; and the reference endpoint assumes KTC's
standard board targets a league like our 2025 one (superflex, 2 FLEX) —
a generic 1-TE league with fewer flex slots would give TEs less flex
opportunity and a lower reference, raising the premium again.  That
assumption is now the largest single lever on the number.

**REPRODUCIBILITY WARNING.**  This measurement depends on the exact
optimizer and the `fantasy_positions` eligibility fix, both of which
exist **only on `claude/league-intel-foundation`** and are not merged
to `main`.  Re-running on `main` today reproduces neither the flex
allocation nor the demand figures.

**REVEALED 2026 ROSTERSHIP SETTLES THE DEPTH QUESTION — and the
axis-ambiguity hypothesis loses its support (2026-07-26).**

The 2025-derived depth figures were measured on rosters built under a
**1-TE** lineup.  The *current* 12 rosters are built under the **2-TE**
format, so counting live rostership measures 2-TE-era behaviour
directly instead of inferring it.

Position table, all 12 current rosters (666 players):

| pos | req | per team | sd | min-max | ×req | % of priced supply |
|---|---|---|---|---|---|---|
| QB | 1 | 5.08 | 1.38 | 2-7 | **5.08** | 91% |
| RB | 2 | 8.50 | 2.25 | 5-12 | 4.25 | 91% |
| WR | 3 | 12.33 | 3.79 | 8-20 | 4.11 | 88% |
| **TE** | **2** | **5.42** | 2.02 | 2-9 | **2.71** | 80% |
| K | 1 | 1.58 | 0.86 | 0-3 | 1.58 | n/a |
| DL | 3 | 6.25 | 1.83 | 4-10 | 2.08 | 66% |
| LB | 3 | 7.92 | 2.56 | 4-13 | 2.64 | 116% |
| DB | 3 | 8.42 | 1.19 | 6-10 | 2.81 | 120% |

**TE is the LEAST-hoarded offensive position relative to requirement**
(2.71× vs QB 5.08×, RB 4.25×, WR 4.11×) — and it is **not supply
constrained**: only 80% of priced TEs are rostered, so 16 remain
available.  Managers *could* roster more TEs and choose not to.  That
makes 2.71 a statement of demand, not of scarcity of bodies.

Premium at each candidate depth:

| definition | TE/team | cut | median | TE1-12 |
|---|---|---|---|---|
| naive (slots only) | 2.00 | TE24 | 1.239 | 1.175 |
| **revealed startable-only** | **2.58** | TE31 | **1.355** | **1.235** |
| **revealed rostership** | **2.71** | TE33 | **1.416** | 1.252 |
| 2025 marginal (churn-confounded) | 3.79 | TE45 | 1.592 | 1.336 |
| max-of-rank (retired) | 4.29 | TE51 | 1.815 | 1.414 |
| *KTC measured* | | | *1.320* | *1.227* |

**This converges with KTC.**  Revealed depth of 2.58-2.71 lands inside
the 2.5-3.0 band predicted from KTC's 1.320, the premium (1.355) sits
within 0.035 of KTC's, and the TE1-12 bands match at 1.235 vs 1.227.

**Consequence — a hypothesis retracted.**  The earlier divergence was
*our measurement error*, not evidence that KTC encodes a different
axis.  Both inflated figures came from confounded statistics, and
removing the confounds moved us onto KTC rather than away.  The
axis-ambiguity reading remains *possible* but has lost its supporting
evidence; the self-serving explanation was wrong and the external
check was right.  **Operative premium: ~1.36-1.42.**

**A SIXTH broken measurement — mine, and it invalidated 1.592.**  The
marginal-value depth ranked each team's TEs over the SEASON-LONG set of
everyone who ever appeared on the roster.  Measured churn is **2.08×**
(median 5 TEs on a roster in any week; 10.3 distinct across a season),
so "TE8" was routinely a two-week waiver add rather than a depth slot.
The statistic therefore partly measured **roster churn and roster
size** rather than depth need.  Diagnosed when a deep-vs-shallow split
came out backwards — TE-deep teams implied 5.81 effective depth against
TE-shallow teams' 2.42, which is mechanical: more rostered TEs create
more depth ranks to sum over.  **1.592 and 3.79 are retired.**

*On the bias direction, both prior claims were wrong.*  I said the
1-TE era biased marginal contribution *down*; the substitution argument
says *up* (a shallow roster has worse next-best alternatives, so each
TE's marginal value is larger).  The substitution reasoning is sound,
but the churn confound dominated it, so neither prediction survived
contact with the split test.  Revealed rostership sidesteps the whole
question by measuring 2-TE-era behaviour directly.

**No historical roster snapshots exist.**  `data/sleeper_last_good.json`
is committed but its git history reaches back only to 2026-07-24 (2
days); `data/public_league/snapshot.json`'s "2025"/"2024" seasons are
synthetic fixtures (`L2025`, 4 rosters, 6 players).  So the
2025-vs-2026 TE-count delta — the cleanest possible measurement of how
managers responded to the format change — **cannot be computed today**.
Accumulation starts now from the committed snapshots.

*Caveats, structural:* rostership encodes manager habit and inattention
as well as valuation, so it is evidence about demand rather than
ground truth about value; supply and demand are jointly determined and
are reported separately rather than resolved; n=12, so the spread
matters as much as the mean (TE ranges 2-9 per team); and IDP supply
shares above 100% (LB 116%, DB 120%) reflect gaps in priced coverage,
not real over-rostering.

**DEPTH DEFINITION MATTERS AS MUCH AS THE PARAMETER (2026-07-26).**
"Deepest TE rank that ever entered an optimal lineup" is a **max over
weeks**, so its mean is outlier-driven — one TE5 spike in week 9 sets a
team's figure to 5 for the season.  Re-derived using **marginal
best-ball value** (spec §16.3-16.4): expected optimal lineup points
with a player minus without, a MEAN of contribution rather than a max
of rank.  824 player-week removals across 170 real 2025 team-weeks,
scored through the exact optimizer.

| TE season rank | mean marginal | median | % weeks > 0 |
|---|---|---|---|
| TE1 | 7.95 | 5.78 | 68.1% |
| TE2 | 5.59 | 2.10 | 58.9% |
| TE3 | 3.69 | 0.05 | 50.0% |
| TE4 | 3.50 | 0.00 | 37.0% |
| TE5 | 1.87 | 0.00 | 29.8% |
| TE6 | 2.66 | 0.00 | 30.9% |
| TE7 | 0.76 | 0.00 | 18.8% |

Marginal-weighted effective depth: **3.79 TE/team**.  Note the medians
hit 0.00 from TE4 down — a deep TE contributes nothing in most weeks
and earns its keep purely through occasional spikes, which is exactly
the variance-capture value the max statistic over-weights.

Premium under all three definitions:

| definition | TE/team | cut | median | TE1-12 | TE13-24 | TE25-40 | TE41+ |
|---|---|---|---|---|---|---|---|
| naive (slots only) | 2.00 | TE24 | 1.239 | 1.175 | 1.292 | 1.364 | 1.680 |
| **marginal value (mean)** | **3.79** | TE45 | **1.592** | 1.336 | 1.562 | 1.701 | 2.309 |
| max-of-rank (outlier-driven) | 4.29 | TE51 | 1.815 | 1.414 | 1.691 | 1.862 | 2.610 |
| *KTC measured (reference)* | | | *1.320* | *1.227* | *1.268* | *1.308* | *1.492* |

**The marginal-value figure (1.592) is the operative one**; the
max-based 1.815 is superseded as inflated.  Sensitivity to the
*definition* (1.24 → 1.59 → 1.82) is comparable to sensitivity to the
parameter, which is why both are shown.

*Noise caveat:* rank-level means are non-monotone at depth (TE6 > TE5,
TE8 > TE7) on small n — the 3.79 aggregate is more stable than any
individual rank.

**HOLD BOTH READINGS OF THE KTC DIVERGENCE.**  At 1.592 vs KTC's 1.320
the gap narrowed but did not close.  Two live explanations, and the
first is self-serving:
1. KTC encodes a *scoring* axis and never measured this quantity, so
   divergence is expected;
2. **our depth parameter is still too aggressive and the premium is
   overstated** — the max-statistic defect was a concrete mechanism for
   exactly that, and correcting it moved us 0.22 toward KTC.
That the refinement moved *toward* KTC is mild evidence for (2).
"The external check measures something else" is the comfortable story
whenever your own number diverges; it is not yet established.

**STRUCTURAL LIMIT OF THE ONLY AVAILABLE DATA (load-bearing, not a
footnote).**  The 2025 source weeks ran a **1-TE lineup**.  Two-slot
logic was applied to rosters built under one-slot incentives, and teams
in a genuine 2-TE league roster differently — likely deeper at TE,
which would *raise* true marginal contribution at depth.  Direction of
the bias is unknown-but-plausibly-downward; magnitude unmeasurable.
This cannot be solved with available data and belongs beside the
headline number.

**BEST BALL CORRECTION — supersedes the 1.239 figure.**  The naive
"2 slots x 12 teams = TE24" replacement cut is wrong for this league
and **biases the premium down**.  In best ball you never set a lineup,
so the slot goes to whoever spiked that week.

*Measured, not assumed* (170 real 2025 team-weeks): a TE ranked deeper
than TE2 took a best-ball TE slot in **74.7%** of team-weeks; the mean
deepest season-rank used was **4.29**, median 4.0, p90 7.

Recomputed derived curve:

| replacement cut | median | TE1-12 | TE13-24 | TE25-40 | TE41+ |
|---|---|---|---|---|---|
| naive 2.0/team (TE24) | 1.239 | 1.175 | 1.292 | 1.364 | 1.680 |
| 3.0/team (TE36) | 1.450 | 1.269 | 1.450 | 1.561 | 2.048 |
| measured median 4.0/team | 1.670 | 1.370 | 1.618 | 1.771 | 2.439 |
| measured mean 4.29/team | 1.815 | 1.414 | 1.691 | 1.862 | 2.610 |
| *(KTC measured, reference)* | *1.320* | *1.227* | *1.268* | *1.308* | *1.492* |

**1.239 is superseded.**  The operative range is **~1.45-1.82**,
directionally certain (every plausible depth raises it) but
magnitude-uncertain, because the premium is highly sensitive to the
depth parameter and deep cuts land in the flat tail of a 74-TE pool
where the derivation is least reliable.  Per the standing discipline,
report the range rather than picking a point.

*Caveats on the 4.29 figure, which is why it is not taken as exact:*
teams rostering more TEs get more chances for a deep one to spike
(selection effect); the 2025 source weeks ran a 1-TE lineup and 2-slot
logic was applied to them; and TE51-of-74 sits in the tail.

**This BREAKS the KTC agreement — and that supports the axis
ambiguity.**  At the naive cut the derivation sat within 0.08 of KTC.
Correcting for best ball moves it to 1.45-1.82 against KTC's 1.32.  If
KTC's TE++ is a scoring premium, it was never measuring the structural
quantity and the earlier agreement was coincidence — exactly the
failure the axis warning predicted.  The two corrections interact, and
the corrected divergence is weak independent evidence that KTC encodes
a different axis.

**A FIFTH broken check — this one in my own gate.**  The rank-encoded
path was reported as having an unsatisfiable "controls at zero
displacement" condition.  On inspection the *signal* was already
difference-in-differences (`TE median − control median`), which is
correctly immune to the zero-sum permutation identity — a ranking is a
permutation, so a real TE gain forces an equal aggregate loss
elsewhere, and subtracting the control median absorbs it.  On the live
KTC pair that shows as TE +72, controls −11, signal 83.

But the **power denominator** was broken.  With controls in perfect
lockstep their dispersion is 0, `signal / 0` returned `None`, and
`detected` read that as **False** — so the *cleanest possible* signal
(TE +80, controls −20 in unison, signal 100) was reported as not
detected.  Zero dispersion is the strongest evidence, not the absence
of it.  Fixed: a non-zero signal with zero control dispersion counts as
detected.

Added alongside it: **control cohesion**, the Spearman correlation of
the controls' own base-vs-comparison ranks.  This is the invariant that
*is* satisfiable — controls may all shift down together (valid) but
must keep their relative order; a board-wide reshuffle (invalid) breaks
it.  KTC scores >0.9; a scrambled control group falls below.

**A third distinct rejection mode: cardinal-but-uncontrolled.**  The DN
value pair passed the cardinal-scale gate (955× dynamic range) yet
failed on control drift of 6.83%, with only 27/240 control rows
identical and movement in both directions.  So DN's two boards differ
in more than the TE axis — they were never a single-variable
experiment the way KTC's are.  Three named failure modes now:
rank-encoded (scale), confounded (controls drift), and insufficient
overlap.

**SHAPE IS CORROBORATED EVEN THOUGH LEVEL IS NOT.**  Levels are not
comparable across KTC, DN and our derivation — different axes,
different universes, different methods.  But all three agree the
premium **grows with TE depth**, and our replacement derivation
produces that monotone shape independently rather than being fitted to
it.  That is the part of the corroboration which survives the
axis-ambiguity objection, and it should be stated separately:
**shape-corroborated, level-uncertain.**

**A fourth vacuous check, caught and recorded.**  The first attempt at
this measured "TE availability" as "the host produced a score", which
is true for *every* rostered player — byes and inactives are scored
0.0.  It returned an availability rate of exactly 1.000 across 170
team-weeks.  Standing rule, now four times validated in one day: **a
test or metric that cannot fail is worse than none, because it
consumes the attention that would otherwise notice the gap.**  A
suspiciously perfect number is a bug report.

**CORROBORATED BY INDEPENDENT DERIVATION (2026-07-26).**  The
paired-board survey came back a clean negative — KTC is the only
automatable publisher with a real paired variant (OTCFFB and
FantasyNavigator reject TE params; FantasyCalc and Dynasty Daddy accept
them and return byte-identical payloads, i.e. silently ignored; DLF and
Dynasty Nerds paywalled; FantasyPros rank-encoded).  So cross-publisher
corroboration is unavailable.

Instead the premium is now **derived from first principles on our own
pool** and cross-checked against KTC.  Two unrelated methods:

| band | derived (our replacement levels) | measured (KTC 2-TE board) | diff |
|---|---|---|---|
| TE1-12 | 1.175 | 1.227 | −0.052 |
| TE13-24 | 1.292 | 1.268 | +0.024 |
| TE25-40 | 1.364 | 1.308 | +0.057 |
| TE41+ | 1.680 | 1.492 | +0.189 |
| median | 1.239 | 1.320 | −0.081 |

Same direction, same monotone depth grading, levels within ~0.08 at the
median.  This is stronger than a second publisher would have been: a
second vendor could be copying the same convention, whereas this is our
own roster requirements (TE demand measured at exactly 2.00/team by the
LI-3 optimizer) run through our own replacement-level code.

**The FORM was decisive, and the obvious one is wrong.**  The natural
VOR ratio

    premium(V) = (V − R_league) / (V − R_reference)

is **rejected**.  Tested against KTC's own paired boards it predicts a
**negative premium (−0.30)** for the TE13-24 band where the true value
is 1.27, because it has a pole at `V == R_reference` (7 TEs sit within
one band of it).  Its hidden premise — value proportional to
value-over-replacement — is empirically false here: the board prices a
replacement-level TE around 2,500, not 0.  This is the same estimator,
failing the same way, that was rejected earlier today when bracketing
an assumed reference; a test now pins the negative prediction so nobody
"simplifies" back into it.

The form used is the additive shift, which carries no such premise:

    premium(V) = 1 + (R_reference − R_league) / V

Doubling required starters lowers replacement by a fixed amount
(813 points on the current board), and a fixed amount is worth
proportionally more to a cheap player — which *reproduces* the observed
depth grading instead of assuming it.

**IDP-invariant by construction, and asserted.**  Only TE values enter
the derivation, so board composition cannot move it: adding IDP rows
cannot change which TE is 12th or 24th.  The function signature takes a
TE-only pool, making the scope leak impossible rather than merely
unlikely, and a test pins it.  Note the corollary — the derivation is
computed on OUR pool, so unlike importing KTC's number it does not
inherit a calibration measured on a board that structurally cannot
contain half our starters.

**Rank displacement is NOT portable across boards.**  A value ratio
transfers between boards of different composition; a rank displacement
does not, because it depends on player density around that value.  The
same value increase crosses far more bodies on our IDP-interleaved
~1000-row board than on KTC's offense-only ~500.  Any application path
must therefore be: measured premium → **value ratio** → *our* board's
displacement through *our* Hill curve at *our* density.  Never import a
displacement directly.  ``measure_rank_displacement`` is consequently a
within-board comparison only.

**APPLICATION POLICY (decided 2026-07-26; applies when the gate opens).**

*Which number is operative:* **ours.**  The derivation is computed on
our actual pool, our actual TE curve, and our measured starter demand
(2.00/team).  KTC's and Dynasty Nerds' figures are market observations
of a **different universe** — offense-only boards that structurally
cannot contain half our starters.  Their agreement with our derivation
validates the *method*; it does not make their *number* more applicable
to our board than our own.  So: our derivation is the operative value,
market measurements are cross-checks, and a divergence between them is
a signal to investigate rather than a reason to switch.

*How it is computed:* **recomputed live, never frozen.**  Per the drift
constraint above, 1.239 is no more permissible as a hardcoded constant
than 1.368 was.  Anything that ships recomputes from current source
values, stamps the measurement date and observed value, and surfaces
movement rather than smoothing it.

*Third data point — pending.*  Dynasty Nerds embeds a `SFLEX` (no TE
premium) array beside `SFLEXTEP` in the same payload already
downloaded.  As of 2026-07-26 the built contract carries
`dynastyNerdsSfTep` (289 rows) but **not** the standard sibling, so the
three-way comparison (derived / KTC-measured / DN-measured) is not yet
possible.  When DN's standard array is captured, run all three; if they
cluster the question is settled, and if DN diverges from KTC that is
itself informative about whether ~1.3 is a market convention or one
vendor's house view.

**TARGET DESIGN (not built — gated on the multi-source survey).**  The
user offered to make the TE premium dynamic, "ever changing based on
whatever factors you deem relevant".  Recorded here so LI-7 builds
toward it, with one part approved and one part explicitly refused.

*Approved in principle: recomputed, never hardcoded.*  The drift
finding above makes a frozen constant indefensible, and the repo
already has the pattern — the Hill curves auto-refit weekly.

*Refused: a richly multi-factor premium.*  The tempting inputs — TE
injury rates, rookie-class strength, this season's TE cliff steepness —
are **already priced into the underlying source values**.  The
premium's job is narrow and structural: re-express a 1-TE-calibrated
board onto a 2-TE footing.  Feeding player-level scarcity signals into
it double-counts what the boards already reflect — the *same* error as
conflating the scoring axis with the structural one, and as reading
blend-vs-anchor as an independent signal.  A sophisticated premium
would look impressive and be wrong.  Keep it narrow.

*Shape, if and only if the survey licenses a correction:*
1. recomputed from the paired-board measurement on a schedule, through
   the existing `calibration.py` validity gates;
2. **smoothed** (EWMA or equivalent) so measurement noise does not
   reach player values — a TE must not move 3% for reasons unrelated
   to the player;
3. **movement-bounded per refresh**, so a bad scrape or a publisher
   methodology change cannot swing the board;
4. **gated with last-good fallback** — a refresh that fails
   controls-at-unity or the cardinal-scale check keeps the previous
   value rather than accepting a number the method just declared
   untrustworthy;
5. **separately attributed** — premium movement surfaces as its own
   category, never blended into player-level movement.  §32 already
   separates toggle movement from weekly movement; this is a third and
   needs its own label or the user sees unexplainable drift.

*The gate.*  The paired-variant survey across publishers decides it.
**One** publisher means a dynamic premium tracks *KTC's methodology
changes* — strictly worse than a constant, because it adds movement
without adding truth.  **Several clustering** near one value means it
tracks something real and it gets built as specified.  **Scatter**
means no correction at all, and there is nothing to make dynamic.

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
