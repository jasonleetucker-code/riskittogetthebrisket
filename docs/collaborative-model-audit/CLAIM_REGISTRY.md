# Claim registry

Every material claim from the external audit, adjudicated against the tree at
`a6edd364`. Classifications: CONFIRMED · PARTIALLY CONFIRMED · ALREADY FIXED ·
DEAD CODE · REFUTED · DISPUTED · BLOCKED BY MISSING DATA.

---

## A — `rosValue` is a ranking index, not points

**CONFIRMED.** `reviewed_at` 2026-07-27 · `main_sha` a6edd364

`src/ros/parse.py:26-46` is `100·(ln(N+1) − ln(r))/ln(N+1)`; `aggregate.py` blends those
to 0–100. The lineup optimiser (`src/ros/lineup.py`) is an *exact* Kuhn bipartite
matching — genuinely correct — but it maximises Σ of that index, and nothing downstream
converts to points.

Two sub-defects, both verified by direct read and both fixed:

* `src/ros/aggregate.py:146-157` — dead `if`/`else`, byte-identical branches, labelled a
  "PR1 stub". `RankedRow.projection_value` was documented to "override the rank-derived
  score"; it never did. DraftSharks (highest-weighted ROS source, 1.25,
  `is_projection_source`) parses a real projection that `scrape.py` plumbs through and
  this discarded.
* `src/api/gameplan.py:36,847` called it "rest-of-season points".

**Decision:** collapse the branch, correct the docstrings, rename `marginalPoints` →
`marginalStrengthIndex` (alias retained). **Deliberately did not wire projections in** —
that changes every ROS value and needs its own evidence.

**Remaining uncertainty:** whether a projection-weighted lineup would pick different
FLEX entrants is untested. Blocked on finding Q — see below.

---

## C — tier classification promotes ordinary starters to elite

**ALREADY FIXED — do not re-raise.** Fixed before `4f9cb05b` merged.

`src/roster_intel/profiles.py:92-143` uses a top-5% percentile for `elite` and ignores a
non-separating threshold. `bestBallStarter ≤ starter` always, by construction
(`src/league_intel/replacement.py:374-401` — mean of the *k lowest* marginals vs their
median). `tests/roster_intel/test_profiles.py:305-440` pins ordering and reachability as
property tests.

**Residual fixed here:** `PositionProfile.replacement_gap` held the starter replacement
*level*, not a gap — and `partner.py:340` already consumed it as a level. Renamed to
`replacement_level`; `replacementGap` kept as an alias. Note
`ScarcityComponents.replacement_gap` is a genuine difference (`best_ball − waiver`) and
was correctly named — the two fields shared a name and only one was wrong.

---

## D — group-removal marginal conflates strength with dependency

**ALREADY HANDLED.** `src/roster_intel/marginal.py:26-30` states the distinction
explicitly: `marginal_points` = strength, `fragility`/`worst_drop` = dependency,
`entry_rate`/`clogger_value` = utilisation, reported side by side and never blended.
`engine.py:31-36` pre-computes `deficit` specifically to stop consumers deriving
`fragility × marginal` — a mistake a prior agent had already made.

Only the *naming* was wrong; fixed under A.

---

## E — surplus is entry-based, not removal-cost

**CONFIRMED. DEFERRED.**

`profiles.py:329-338`: surplus = priced AND absent from *one* optimal lineup AND
≥ `0.60 × starter`. Because it keys off a single assignment, two equal-value
cross-eligible players split into "starter"/"surplus" arbitrarily via
`_canonicalize_slots` tie-breaking. `tradeable_surplus` then sums raw `ros_value` for
players whose marginal contribution is zero by construction.

**Deferred, not dismissed.** The removal-cost redesign is sound but changes a live
roster-intelligence output and deserves the same before/after treatment F-6 got. F-6 was
the higher-value use of that effort this pass.

---

## F — the TE premium contradictions

**CONFIRMED, and the measurement changed the answer.**

Of 1.592 / 1.320 / 1.12 / 1.36–1.42 / 1.608 / 2.215, **none are live**. The only live
constants are `_TE_BLANKET_NON_NATIVE_MULTIPLIER = 1.15` and
`_TE_BLANKET_NATIVE_MULTIPLIER = 1.10` (`data_contract.py:5551-5552`), applied per source
pre-blend, KTC exempt.

The prompt's suggested interim posture — "describe the existing treatment as source
alignment if that is what it is" — was already the state of the code.

**What measurement added.** KTC publishes the same players with and without a TE premium
(`ktc.csv` vs `ktcSfTep.csv`), so the source-alignment conversion is directly measurable.
73 TEs differ; uplift is rank-dependent, 1.209 at the top to 2.053 at the bottom, median
1.319. **1.15 sits below the entire observed range** — it under-corrects for every tight
end. And the league's own measured TE premium is exactly 1.000 (all TE-touching keys
matched by their WR/RB equivalents, not just `bonus_rec_te`).

**Decision:** build both axes, measure both, wire neither yet. See
`IMPLEMENTATION_STATUS.md`.

---

## G — `lineupScarcity` measures top-heaviness, not scarcity

**DEAD CODE — the question is moot.**

`replacement.py:615-621` computes it correctly. Its only consumer,
`adjustment.py::structural_scarcity_axis`, has **no non-test caller**;
`values.py:59` forces `LEAGUE_ADJUSTED_IS_NOOP = True`; `src/league/__init__.py` is an
empty placeholder ("LAM and scarcity adjustments have been removed"). It never
multiplies a value.

One scarcity multiplier IS live — `targets.py:458-471` — but it uses `waiverScarcity`
and scores trade targets, not player values.

---

## H — competitive-window outputs are called probabilities

**CONFIRMED (terminology).** `window.py:274-293` softmaxes negative *squared* distance
to five hand-placed anchors at `T = 0.18`. Nothing was fitted to outcomes.

Aggravating factor found beyond the prompt: `gameplan.py` **dropped `notes`** from its
league-summary projection, hiding "no state cleared 30%" and the `lineupScoreRank`
proxy stamp from every API consumer.

**Fixed:** `affinities` is now the published key (`probabilities` retained as alias);
`notes` restored to the projection.

---

## I — manager-specific acceptance is unidentifiable

**ALREADY HANDLED — conclusion preserved as instructed.** `partner.py:52-60` states it;
the manager term is gated by `manager_evidence` (requires accept *and* reject data,
which Sleeper does not expose) and contributes exactly zero. Pinned by
`TestManagerEvidenceGate` and `TestLimitationsDeliverable`. No action needed.

---

## J — `tradePartnerFitScore` implies a range it cannot reach

**CONFIRMED.** Computed two ways and reconciled: reachable range **7.24 – 43.12** on a
nominal 0–100 field.

Cause: `DECISION_CALIBRATED` confidence (0.85) is unreachable, so the best attainable is
0.40 — which means `MAX_CONFIDENCE_WITHOUT_DECISION_DATA = 0.45` **never binds**. The
existing guard asserted only `0 ≤ x ≤ 100`.

*(A first closed-form pass gave 47.0 by assuming the 0.45 cap binds. It does not. The
exhaustive sweep figure is correct and the derived constants now match it exactly.)*

**Second, undocumented issue:** `need` and `window` each enter `fit_score` **twice** —
the capped logit path (weight 0.65) and the *uncapped* `structural` term (weight
0.35·confidence). The module's stated budget hierarchy ("fairness strongest at 1.40")
describes the estimate, not the ranking score. On `fit_score`, need outweighs fairness.

**Decision:** publish the reachable bounds with the score (derived from the caps, so they
cannot drift); document the double entry at the assembly site; pin both. Kept the double
entry rather than removing it — the two entries answer different questions, and that is
now written down.

---

## K — the trade finder values assets off a parallel board (WS-J F-6)

**CONFIRMED — the largest real defect in the audit. FIXED.**

`finder.py:302-309` read `_finalAdjusted` → `_rawComposite` → `_rawMarketValue` →
`_composite`. `rankDerivedValue` appeared **zero times**. Every sibling engine and the UI
read the canonical value. The finder arbitraged a board no user could see.

Full result, including the independent reproduction of PR #567's numbers and a
correction to F-6's own prediction: `results/F-6-migration-result.md`.

---

## L — the finder permits a negative internal delta

**PARTIALLY CONFIRMED — latent, not live.** `finder.py:493-495` does admit
`board_delta ≥ −200`, and its comment claimed the opposite of the code it annotated.
`_build_summary` hard-coded a `+` sign, so a −100 delta would have rendered as
*"Slight Edge: you gain -100 board value (+-2%)"*.

**But `finder.py:856` filters `board_delta > 0` before returning**, so nothing in that
band ever reached a caller. Severity MEDIUM, not critical. Fixed the comment and the
formatter anyway — a formatter must not be the thing standing between a loss and a
claimed win.

---

## N — three engines, three mixed-market postures

**CONFIRMED.** `finder.py:536-537` sums KTC-offense and IDPTC-defender values into one
scalar with no flag; `angle.py:786` prices inside one market with an uncertainty band;
`packages.py:544-560` and `partner.py` suppress outright. `angle.py:38-42` documents a
**6.2% overstatement** from exactly the class of sum finder performs and calls sound.

**Deferred.** Fixing it means choosing between three defensible postures for an engine
whose premise needs *a* market number. Recorded, not guessed at.

---

## O — KTC's VA applied to non-KTC values

**DISPUTED — I disagree with my own sub-reviewer.** Reported as significant: KTC's
scale-sensitive VA (`t = KTC_T_REFERENCE = 10041`) applied to `rankDerivedValue` at
`angle.py:778`, `angle.py:1253`, `suggestions.py:690`, where it gates results.

The call sites are real. **The severity is not.** `rankDerivedValue` is on a 1–9999 scale
(`player_valuation.py:140`) against `KTC_MAX_PLAYER_VAL = 10000` / `t = 10041` — the
endpoints are **0.4% apart**, so `(value/t)^1.3` behaves almost identically on either
board. What is genuinely unvalidated is *curvature*, not scale.

**Treatment: documentation, not code change.** Downgraded to LOW.

---

## P — confidence is a raw source count

**CONFIRMED. DEFERRED to measurement.**

`data_contract.py:1895`: `source_count >= 2` is the sole gate to "high". DLF contributes
4 registry entries, FantasyPros 3, Flock 2, DraftSharks 2 — all weight 1.0. A rookie WR
on `dlfSf` + `dlfRookieSf` + `flockFantasySf` + `flockFantasySfRookies` reaches "high"
confidence off **two publishers**, and escapes the
`_SINGLE_SOURCE_VALUE_RETENTION = 0.30` haircut. No notion of source families exists
anywhere in the tree. The team hit this once and hand-fixed it for KTC only
(`data_contract.py:1010-1013`).

**Deferred deliberately.** Changing confidence buckets moves a user-visible field on
every player. The correct first step is measuring pairwise source correlation from the
CSVs already on disk — clusters should be measured, not assumed from publisher names.

---

## Q — no player-week actuals or projections are persisted

**CONFIRMED. Root cause of several other limits.**

`data/nfl_data_cache/` is an evictable TTL cache that does not exist;
`data/source_value_history.jsonl` is gitignored and absent; no relational store. This is
why `EvidenceTier.PROJECTION_CORROBORATED` is unreachable and why finding A's key
experiment cannot run.

---

## S — security

**CONFIRMED, FIXED.** Three items, all verified by direct read before acting:

1. `LOCKSTEP_SETUP.md:37-40` named `178.156.148.92` as the "Current production target"
   with user `dynasty` and an app path. That IP belongs to a third party (the
   `riskittogetthebrisket.org` domain lapsed and was re-registered).
2. `deploy/nginx/chaseupside.com.conf:155-193` served the whole app — including the
   login POST — over plain HTTP on the bare IP with no redirect. Also broken on its own
   terms: `JASON_AUTH_COOKIE_SECURE` is true, so the browser dropped the `Set-Cookie`.
3. Four active runbooks curled the lost domain; two recommended registering it with an
   external uptime monitor.

**Downgraded from the sub-reviewer's report:** `server.py:9223-9230` sets an auth cookie
without `secure=`, but that is `/api/test/create-session`, double-env-gated and 404 in
production. Informational, not a defect.

---

## Raised independently — not in the external audit

### nflverse 2025 weekly-stats URL is stale

**CONFIRMED (MEDIUM).** `nflverse_direct.py:59` builds
`player_stats/player_stats_{year}.csv`. Probed live: 2023 → 200, 2024 → 200,
**2025 → 404**. nflverse renamed the asset; `stats_player/stats_player_week_2025.csv`
→ 200, now carrying the `def_*` columns in the same file. `_fetch_csv` swallows the 404
and returns `[]`.

Not critical: `historical_stats.py:70-110` implements a documented Sleeper fallback for
exactly this case, so the system degrades to a lesser source rather than failing. It
still blocks nflverse-based weekly-actuals work.

### `tests/conftest.py` contradicted the code it isolates

**CONFIRMED, FIXED.** The comment asserted the league has `bonus_rec_te = 0.5`,
contradicting `data_contract.py:5533-5534`'s retraction (2026 value is 0.0). The suite
runs against a fallback context that matches 2026 reality **by coincidence**, and never
exercises the live TEP derivation branch — now stated explicitly.
