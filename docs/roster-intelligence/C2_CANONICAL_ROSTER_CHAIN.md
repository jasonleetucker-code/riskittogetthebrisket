# Canonical Roster Intelligence — the C2 chain

**Date:** 2026-08-18
**Status:** IMPLEMENTATION RECORD
**Covers:** `OWNER_FEATURE_INVENTORY.md` rows 1.1 (Team Strength), 1.2 (Team
Weakness), 1.6 (Age-Value Portfolio), 1.7 (`C2-CORE-01` Meaningful Roster Core);
defect #815.

Binding requirements, in precedence order:

- `docs/OWNER_FEATURE_ADDENDUM_2026-08-18_FLEX_STARTER_ASSIGNMENT.md` (#899) —
  ordering, amending #839;
- `docs/OWNER_FEATURE_ADDENDUM_2026-08-14_AGE_VALUE_PORTFOLIO.md` (#838);
- `docs/MASTER_PRODUCT_PLAN.md` §4.1, which mirrors both.

---

## 1. The chain, and who owns each link

| Link | Owner | Status before this work |
|---|---|---|
| Exact lineup | `src/ros/lineup.py` (C2-U1) | **Existed and was canonical.** Verified, not assumed — see §2 |
| Replacement level | `src/league_intel/replacement.py` | Existed. Designated; see §3 |
| Roster-row adapter | `src/ros/lineup.py::roster_player_from_row` | **Two byte-identical copies** — consolidated, §4 |
| Reserve demand + meaningful core | `src/roster_intel/core.py` | **Absent** — built |
| Team Strength | `src/roster_intel/strength.py` | **Absent as an owner** — built |
| Team Weakness | `src/roster_intel/weakness.py` | **Absent as an owner** — built |
| Age / Young Core | `src/roster_intel/age_portfolio.py` | **Absent** — built |
| Roster simulation | `src/roster_intel/simulation.py` (C2-SIM-01) | **Absent** — built |
| Droppability | `src/draft/displacement.py` (C2-DROP-01) | **Existed and was correct — unreachable.** Adapter built, §12 |
| NFL-franchise exposure | `src/roster_intel/exposure.py` (C2-EXP-01) | **Absent** — built, §13 |
| Consumer interface | `src/roster_intel/__init__.py`, `GET /api/roster/intelligence` | **Absent** — built |

The chain was not broken at its head. It was missing its middle.

---

## 2. Exact lineup — verified, not assumed

`src/ros/lineup.py::assign_lineup` / `solve_optimal_assignment` is the single
production lineup owner. Two claims were re-checked against HEAD rather than
carried forward from the C2-U1 record:

- **The solver is exact and the greedies are gone.** `tests/lineup` = 100
  passed. C2-U1's measurement stands: against Sleeper's own awarded best-ball
  lineups over 10 real team-weeks, the exact solver is 10/10 and the two
  retired production greedies were 0/10 and 5/10.
- **The overlay no longer discards the stamp.** A later audit found the live
  Sleeper overlay rebuilding `sleeper.teams` from scratch, dropping the
  build-time `optimalLineup`. That is **repaired**: `server.py:3782` re-stamps
  via `data_contract.stamp_optimal_lineups` after the overlay runs, and
  re-solves rather than copying — the overlay's rosters are fresher, so a
  copied lineup could start a player dropped ten minutes ago.

No surviving greedy assignment path was found.

---

## 3. Replacement level — a boundary table, not a consolidation

Six things in the tree call themselves "replacement". The brief asked which
should be canonical and warned against creating a sixth.

**They are not six copies of one quantity.** They split cleanly by *unit*, and
merging across units would be the defect, not the fix:

| Module | Unit | Question it answers | Disposition |
|---|---|---|---|
| `src/league_intel/replacement.py` | canonical dynasty value | "What is a startable/rosterable player worth in THIS league?" | **CANONICAL for this lane.** Everything built here consumes it |
| `src/scoring/replacement_level.py` | fantasy points (VORP) | "Points above replacement" | Different quantity. Consumer: `public_league/awards.py` via a shim |
| `src/bdvm/replacement.py` | projected PPG | BDVM's dynamic replacement | Different lane; bound by the frozen Appendix-C parity fixture. **Do not touch** |
| `src/trade/faab_engine.py` (`V_repl`) | board value, *format line* | "What does the league's format make replacement-level?" | Different question, different lane |
| `src/draft/` (`waiverValue`) | board value, *best unrostered* | "What can I sign instead?" | Different question |
| `src/league_comparison/metrics.py` | points | Display-only comparison | Leave |

So the deliverable here is **no new implementation** and no merge — a
designation plus this table, so the next session does not "consolidate" two
different units into one wrong number.

---

## 4. One roster-row adapter

`league_intel.replacement._to_roster_players` and
`roster_intel.marginal.to_roster_players` were byte-identical, and the
second's docstring said it *"mirrors"* the first *"deliberately: the two
modules must agree on how a roster row becomes an optimizer input, or their
numbers stop being comparable."*

Agreement maintained by hand is what ONE CONCEPT, ONE CANONICAL OWNER exists to
replace. `ros/lineup.py` owns `RosterPlayer`, so the adapter lives there and
both copies delegate.

Both also carried `float(row.get("rosValue") or 0.0)` — the exact coercion
C2-U1 retired from `lineup.py`, reintroduced at the adapter, where it hands the
solver a real, assignable, worthless player instead of an unpriced one. Missing
is now `None`; an explicit `0` still passes through as the real value it is.

**Measured before changing:** at the time, this was a no-op on the live path,
because `ros/team_strength.py:123` writes every unmatched row with
`ros_value=0.0` — so the snapshot these adapters read carries no `None` to
preserve. That lossy hop is no longer on the roster-intelligence path at all —
see §8 — so the adapter's honest-missing behaviour is now reachable rather than
theoretical.

---

## 5. Meaningful roster core (C2-CORE-01)

The design is one idea: **reserve demand is just more slots**, so the reserve
pass is the *same exact solver* run a second time over the survivors.

```
starters  = assign_lineup(pool, league_slots)       # exact
remaining = pool − starters
reserves  = assign_lineup(remaining, reserve_slots) # exact, same owner
core      = starters ∪ reserves
```

This is what §3 requires when it demands *"global legality-aware selection
rather than independent greedy lists that can assign the same player twice"*,
and it makes every-player-at-most-once **structural**: the solver enforces one
slot per player, and the second pass cannot see a player the first took.

It also satisfies the acceptance criteria without special-casing them. RB3
seated at FLEX is not in `remaining`, so the RB reserve slot must reach RB4. No
per-position list is consulted anywhere in the module.

### Reserve demand

Per dedicated position `p` and per ordinary/IDP flex slot family:

```
reserve_demand = ceil(M × starters) − starters
```

`M = 1.5`, from `config/roster_intel/meaningful_core.json`, labelled **PRIOR**
with its provenance and the `MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md` §4.3
challenger pass (1.25 / 1.50 / 1.75 / data-derived) named. Not frozen.

### Superflex — the owner decision, and the assumption it carries

`d(QB) = qb_dedicated + sf_slots`, **before** the multiplier. This is the
literal #839 rule and it reproduces the owner's own worked example: 1 QB + 1 SF
⇒ basis 2 ⇒ `ceil(1.5 × 2)` = **3 meaningful QBs**. SF therefore generates no
separate reserve group, so nobody is counted twice.

**The assumption is stated rather than buried.** The *assignment* step makes no
such claim: if the exact solve seats a WR in SUPER_FLEX — legal, and LI-5
measured SF going to a QB in 9 of 12 live rosters, so 3 of 12 went elsewhere —
that WR is a starter and leaves the pool, while QB reserve demand still counts
the SF slot as QB demand. The two remain consistent; the demand side is an
owner prior, not a measurement.

An alternative (each flex family, SF included, gets its own reserve group under
the same formula) was put to the owner and **not** selected. Recorded here so a
later calibration pass can see the fork rather than rediscover it.

---

## 6. Team Strength, Weakness, Age

### Team Strength (row 1.1)

Aggregates canonical values over the core. **Creates no value** — the same
boundary #822 enforced when it rejected the league-aware overlay and ruled it
may not own a canonical field. Pinned by scaling every input by *k* and
asserting the total scales by exactly *k*.

Three neighbouring quantities are deliberately NOT merged:

- `/api/terminal`'s `totalValue` — a raw whole-roster sum (W20-F003), a
  **portfolio** total. Real consumers, so not deleted; published beside the core
  total as `fullRosterValue`, explicitly named, so the two cannot be read as the
  same number.
- `src/ros/` ROS 0-100 strength — rest-of-season **production**. §4.1 is
  explicit that Team Strength "is not Power Ranking, Playoff Odds, or ROS
  production."
- `roster_intel.marginal` — lineup-derived marginal contribution, a diagnostic
  about lineup structure.

Aggregates are uncapped (inventory row 7.5). FLEX contributes without becoming
a column: a FLEX-seated RB sums under RB.

### Team Weakness (row 1.2) — the threshold table is one rule

The owner lists QB1 top 12 / QB2 24, RB1 12 / RB2 24, WR1 12 / WR2 24 / WR3 36,
TE1 12 / TE2 24, and separately says IDP thresholds *"derive from required slots
× league size"*.

**Those are not two rules.** Against `dynasty_main`'s real lineup (QB 1 + SFLEX
1 → demand 2 after the fold, RB 2, WR 3, TE 2) at 12 teams, every listed number
is exactly `k × teamCount`:

| | derived | owner-listed |
|---|---|---|
| QB | 12, 24 | 12, 24 |
| RB | 12, 24 | 12, 24 |
| WR | 12, 24, 36 | 12, 24, 36 |
| TE | 12, 24 | 12, 24 |

So the stated IDP rule is implemented for every position and the offensive table
falls out of it. This is not tidiness: a hard-coded top-12 is silently **wrong**
in the 10-team `dynasty_new`, where `k × teamCount` gives 10 — which is what the
rule always meant.

Rung counts read straight off `ReserveDemand.starter_basis`, so the SF fold
happens once in the lane and weakness cannot drift from the core. A position
takes the level of its **worst** rung, never an average — averaging is what lets
an elite QB1 hide a missing QB2.

### Age-Value Portfolio / Young Core Index (row 1.6)

The addendum's guardrail is the design constraint: this describes roster
construction and must not become a second age-adjusted valuation. Nothing
returns a player value; the index is a percentile of a value-weighted youth
score.

The three failure modes the addendum names, each stopped structurally:

- **low-value youth dominating** — population is the meaningful core, and youth
  is weighted by canonical value;
- **position-blind youth** — youth is a position-relative percentile against the
  league's own *measured* age population; no positional age table, no curve
  constant;
- **missing age read as young** — ageless players leave both sums, coverage is
  published, a zero age is treated as missing (Sleeper carries 0 for unresolved
  records), and no-ages-at-all gives `None`, never 0.0.

Picks are excluded structurally: they are not eligible players and never enter
the core. The index ships labelled **PRIOR** — the addendum requires validation
against real league examples first, and that has not run.

---

## 7. Consumers

- **Python** — `src/roster_intel/__init__.py` re-exports the stable interface.
  This is what Claude 2 (Trade Intelligence) and any future decision product
  should import. Do not reimplement; do not select a roster population with a
  private top-N rule.
- **HTTP** — `GET /api/roster/intelligence?leagueKey=&team=`, via
  `src/api/roster_intelligence.py`. It **computes nothing**, so an importer and
  an HTTP caller get identical numbers by construction. League-scoped through
  the standard `_resolve_league_for_request` gate; 503s `data_not_ready` on a
  foreign-league contract, matching `/api/gameplan`, `/api/terminal` and
  `/api/trade/*`. Rosters come from `data_contract.contract_roster_pools` — see
  §8.
- **Capacity / forced drop** — NOT here. `C3-CAP-01` is trade-owned (#913);
  this lane publishes `simulate_roster_change` and `pool_cut_ladder` for it to
  consume. See §14.
- **Exposure** — `src/roster_intel/exposure.py`, and on every team in the
  endpoint payload as `nflExposure.core` / `nflExposure.fullRoster`. See §13.
- **Droppability** — `src/roster_intel/droppability.py`
  (`team_droppability` / `league_droppability`), also re-exported from the
  package. Opt-in on the HTTP surface: `?droppability=1`. See §12.
- **UI** — none from this lane. Claude 6 owns the frontend.

---

## 8. The roster source, and the two defects it fixed

Rosters come from **the canonical contract**, via
`data_contract.contract_roster_pools` — `sleeper.teams[].players` for
membership, `rankDerivedValue` for value. They previously came from the ROS
team-strength snapshot, which was wrong in two independent ways:

| defect | consequence |
|---|---|
| `rosValue` is "a normalized log-rank index on 0-100 — not points, and not projection-aware" (`src/ros/aggregate.py`) | Team Strength summed a **rest-of-season production** measure while claiming canonical dynasty value. §4.1 says Team Strength "is not Power Ranking, Playoff Odds, or ROS production" |
| `ros/team_strength.py` writes every unmatched row with `ros_value=0.0` | unpriced roster membership arrived **indistinguishable from a real zero**, so `unpricedIds` was structurally empty and missing-is-never-zero was unenforceable downstream |

> **Correction, 2026-08-19 (integration review).** Five places in this branch —
> including the §11 instruction below — said the writer *dropped* those rows. It
> does not: `src/ros/team_strength.py:123-160` appends the player at
> `ros_value=0.0`, and that file's own comment names it as a deliberate
> missing-is-zero boundary. The *consequence* claimed here is unchanged and so
> is the repair on this side, but a coercion and a deletion are fixed
> differently **at the source** — and §11 hands the integration lane a change
> instruction premised on the description, so it had to be right. All five sites
> are corrected.

Not a second loader: `stamp_optimal_lineups` already built exactly this pool
and was its only builder. That block is now `contract_roster_pools` and both
call it, so the lineup stamp and the roster chain cannot disagree.

A third consequence: the endpoint no longer needs the ROS refresh to have run.

**Measured**, newest complete archived scrape, 12 teams: **83 of 660 rostered
players (12.6%) carry no canonical value**, all now reported. An earlier board
the same day showed 49 — the figure moves with scrape health, which is exactly
the signal that was previously invisible.

## 9. Young Core validation (#838 §5)

`scripts/validate_young_core.py` runs the canonical chain over a real board and
asserts four properties. Exit `0` pass · `1` fail · `2` no board (distinct,
because "no data" must never read as "passed"). Result on the newest complete
scrape:

| property | evidence |
|---|---|
| cheap young bench cannot game the index | +20 minimum-value 21-year-olds on the weakest roster → core age Δ **0.0000**, YCI Δ **0.0000**. They never enter the meaningful core |
| core selection matches league config | 21 slots + reserve demand 12 ⇒ ceiling 33; every team's `core + unfilled == 33`, zero duplicates. Demand `{QB 1, RB 1, WR 2, TE 1, FLEX 1, DL 2, LB 2, DB 2}` — QB 1 because SF folds in |
| age never alters canonical value | +5 years on every player → Team Strength changed on **0 of 12** teams; core age moved by exactly **+5.00** on 12/12 |
| ranks are credible | strength ranks a clean 1..12; YCI spans 0.0–100.0; **15 of 66** strength/YCI pair inversions, so youth is a genuinely separate axis and not a restatement of strength |

Hand-checked examples that make the index legible: **Jason** is 1st in strength
*and* youngest (24.42) with YCI 100. **Brent** is 2nd in strength but YCI 9.1 at
26.52 — strong and old, which is the discrimination the index exists to make.
**Kich** is 10th, oldest (28.44), YCI 0.0, and carries the most unpriced players
(17) — an old, thin roster reading as one.

This validates **behaviour, not calibration**. The 0–100 weighting stays a
PRIOR.

## 10. Known limitations

1. **`M = 1.5` and the weakness severity bands are PRIORS.** Both labelled;
   neither calibrated. The §4.3 challenger pass has now been RUN (§16): it rules
   out `M = 1.25` and puts 1.50 inside the defensible band, but does not freeze
   it — the data-derived cutoff moves between 1.05 and 1.70 depending purely on
   where the retention target is drawn.
2. **The Young Core Index weighting is uncalibrated.** §9 discharges #838's
   real-league validation requirement for *behaviour*; the specific weighting
   has not been fitted against outcomes.
3. **The SF-into-QB fold is an owner prior, not a measurement** — see §5.
4. **Not verified in production.** Everything above is measured against the
   tracked export archive, which is production-equivalent but not production.
   Live verification belongs to Claude 5.
5. **`roster_intel`'s only prior production consumer was `/api/gameplan`.** This
   adds a second. Measured reachability is now 15 of 17 modules (§15); the
   remaining gap is the trade half, which waits on `C3-PKG-01`.
6. **`/api/gameplan` still reads the ROS snapshot**, so its `roster_intel`
   outputs (marginals, profiles, window) run on the 0-100 production index
   rather than canonical value. That endpoint is not this lane's to change —
   see §11.
7. **Droppability without scarcity is a bounded approximation, not the same
   number.** The roster-chain surface cannot supply positional scarcity without
   reintroducing the ROS-snapshot dependency limitation 6 describes, so its
   ladder is scarcity-inert. The divergence is bounded (§12) and stamped
   (`scarcityApplied`), but it is real: two candidates within ~1.353x can order
   differently here than on the draft board.
8. **The waiver page's naive drop is untouched.** It is a different lane's
   surface; the exact rewire is handed over in §11.
9. **Capacity's cleanup tolerance is a PRIOR** (§14), and taxi/IR relief is
   structurally unmodellable until per-player taxi assignment and IR
   eligibility are ingested somewhere. Both are stamped, neither is guessed.
10. **Exposure has no consumer surface yet.** It is computed and published on
   every team in `GET /api/roster/intelligence`; rendering it in Simulate
   Impact is Claude 6's, and the trade lane must keep it out of any grade
   (§13).

## 11. Cross-lane dependency for Claude 5

`/api/gameplan` composes `src/roster_intel` (`marginal`, `profiles`, `window`,
`partner`, `targets`, `packages`) over pools built from the ROS team-strength
snapshot. Those pools carry `rosValue`, the 0-100 production index — not
canonical dynasty value. This lane fixed its own endpoint by changing source;
`/api/gameplan` is a different owner and was left alone.

**Exact dependency, if that surface should also read canonical value:**

- **File**: `src/api/gameplan.py::load_league_inputs`
- **Required change**: build `TeamInput.pool` from
  `data_contract.contract_roster_pools(contract)` instead of
  `to_roster_players(row["fullRoster"])`
- **Required output shape**: unchanged — `contract_roster_pools` returns
  `{ownerId: list[RosterPlayer]}`, and `TeamInput.pool` is already
  `tuple[RosterPlayer, ...]`
- **Regression test**: assert a rostered player absent from `playersArray`
  arrives with `ros_value is None` and is reported unpriced, rather than being
  absent from the pool entirely
- **Blast radius to expect**: every gameplan number moves, because the
  objective changes scale (0-100 → 1-9999) and population (unpriced players
  become visible). Marginal *shares* and *ranks* should be broadly stable;
  absolute marginal points will not be.

Alternatively the ROS snapshot writer (`src/ros/team_strength.py:123-160`) could
stop coercing unmatched rows to `ros_value=0.0` and emit `None` instead — but
that changes a different lane's canonical methodology and should not be done
casually. **Its own comment already names this as a decision rather than an
oversight**, and says why it was left: `RosterPlayer.ros_value` is now
`float | None`, so passing `None` would change `health_availability_score` (its
denominator is the starter count) and `unfilled_slots` on the live `/terminal`
team-strength composite. That composite is `C2-U4`'s unit. So this alternative
is not a smaller change than the one above — it moves a live number on a
different unit's authority, which is precisely why the `load_league_inputs`
route is the one written out in full.

### Second dependency — the waiver page's naive drop (C7-WAIV-01)

`frontend/app/waivers/` pairs each add with the lowest raw-value rostered
player. That is wrong in both directions for the reason §12 gives: FLEX and
SUPER_FLEX make droppability *set-dependent*, so "keep at least N at each
position" and "drop the cheapest body" are both unsound. The correct answer is
the matching problem `build_cut_ladder` already solves exactly.

It is a **rewire, not a rewrite** — the owner exists, is correct, and is now
reachable — but the surface belongs to the waiver/decide lane, so it comes to
you as a dependency rather than as a cross-lane edit.

- **File**: whatever computes the paired drop in `frontend/app/waivers/` and
  its backend feed
- **Required change**: consume `GET /api/roster/intelligence?droppability=1`
  (or import `src.roster_intel.team_droppability`) instead of sorting the
  roster by value and taking the tail
- **Required output shape**: already published —
  `droppability.cutLadder.rungs[]` carries `playerId`, `effectiveCutCost`,
  `baseValue`, `valueBasis`, `waiverValue`, `scarcityMultiplier`, `rung`;
  `cutLadder.undroppable[]` carries the players a legal lineup needs. Rungs are
  cheapest-first and nest, so the optimal cut-set of size *k* is the first *k*
  rungs — no re-solve on the client
- **Regression test**: a roster whose WR3 and RB3 are individually droppable
  but not jointly (two FLEX slots absorbing one, not both) must not be offered
  both drops; the naive sort offers both
- **Blast radius to expect**: the recommended drop changes for any roster where
  the cheapest player is lineup-load-bearing, and unpriced players stop
  appearing as free cuts (they arrive stamped `assumedWaiver`)

---

## 12. Droppability (C2-DROP-01) — a reachability fix, not an implementation

The manifest's disposition for this unit is **CONSOLIDATE** with **parity** as
its evidence, and that is exactly what it needed. `src/draft/displacement.py`
was already correct and already the owner.

**What was wrong was reachability.** Its only production caller is
`src/draft/context.py` → `GET /api/draft/roster-context`, which also computes
rookie pools, auction budgets and a dollar ladder, and refuses outright unless
a draft-shaped league resolves. `C3-CAP-01` (forced-drop trade analysis) and
`C7-WAIV-01` (Perfect Waivers) both declare `C2-DROP-01` as a dependency, and
neither is a draft surface. A dependency you can only satisfy by dragging a
draft board behind it is how a fifth implementation gets written.

So `src/roster_intel/droppability.py` is an **adapter** — the same relationship
`Dynasty Scraper.py` has with `src/identity/name_primitives.py`. It contains no
cost arithmetic, constructs no `RosterAsset` of its own, and calls
`build_cut_ladder` exactly once; all three are pinned structurally, and the
guard is mutation-proven (inlining a `max(0, …)` turns it red).

### Parity — measured on the live board, then pinned

| claim | result |
|---|---|
| Cut ladder via the roster chain vs via `/api/draft/roster-context` | **identical on 12 of 12 teams** |
| The two roster joins (`build_roster_assets` vs `contract_roster_pools`) | identical membership, 660 players, **0 value differences, 0 unmatched** |
| The two slot resolvers (`load_league_starter_slots` vs the C2-U1 truth ladder) | identical, all 21 slots |

The join measurement is why the adapter calls `build_roster_assets` rather than
the chain's own pool builder: reusing the owner's join makes the ladder
byte-identical **by construction** instead of by coincidence, and `RosterAsset`
needs two fields (`playerId`, the injury flag) the pool builder does not carry.

### Two inputs are named rather than invented

* **Scarcity is optional and defaults to inert.** The multiplier comes from
  `league_intel.replacement.compute_scarcity`, which reads `rosValue` off the
  ROS team-strength snapshot — the same wrong-quantity dependency this chain
  moved off in §8. Rather than reintroduce it, the caller supplies scarcity or
  does not, and `scarcityApplied` says which happened.

  The resulting divergence is **bounded and stated, not unknown**: the
  multiplier lives in `[0.85, 1.15]` (read from the owner at import time, never
  restated), so scarcity can only reorder two candidates whose inert costs are
  within `1.15 / 0.85 ≈ 1.353`. Beyond that ratio the two ladders agree on
  order whatever the scarcity signals say. Pinned as a property over 25 random
  scarcity draws.
* **`unavailable_keys`** removes players who are not actually signable. The
  draft surface passes the rookies in the live auction; there is no auction
  outside a draft, so it defaults empty. A named input difference, not a second
  rule.

### Cost, and why it is opt-in

Measured on the live 12-team board: the four core outputs cost **69 ms**; the
cut ladder costs a further **710 ms** for the league (it re-runs the exact
solver once per rung per team) and **55 ms** for one team. So it is OFF by
default, on by `?droppability=1`, and the team view computes one ladder rather
than twelve. `droppabilityIncluded` is stamped either way — "you did not ask
for it" and "this team has nothing droppable" must not read the same.

### One coercion removed on the way past

`build_roster_assets` read `float(row.get("rosValue") or 0.0)`. The contract
carries no `rosValue` at all — **0 of 983 rows** on the live board — so it
evaluated to `0.0` every time, and a missing-as-zero was the only thing between
the model and a hole.

It is now an explicit `_FEASIBILITY_OBJECTIVE` constant, because the only
question the cut ladder asks the solver is *how many* starting slots the
surviving roster can fill, and **that count does not depend on the objective**:
`solve_optimal_assignment` is a matroid greedy with augmenting paths, which
never evicts an assigned player, so it returns a maximum-cardinality matching
whatever the weights are. Weights decide who starts, not how many. The property
was pinned (50 random objectives, identical count) rather than assumed — and
the constant is `0.0` and not `None` on purpose, since `None` is UNKNOWN and
would remove from the solve a player who still occupies a body that can legally
fill a slot.

### Boundary that did NOT move

The waiver page still pairs an add with a naive lowest-value drop. That is
`C7-WAIV-01`, a different lane, and the correct answer there is the matching
problem this owner already solves — so it is a rewire, not a rewrite. It comes
to the integration lane as a dependency (§11), not as a cross-lane edit.

---

## 13. NFL-franchise exposure (C2-EXP-01, CE-06)

*"Show value-weighted NFL franchise exposure Before → After, e.g.
`MIN 18.2% → 22.4%`. It is informational, not an automatic trade penalty."*
— `OWNER_PRODUCT_BACKLOG_SPEC.md` §1.6, #786 decision 12.

### Descriptive only, enforced two ways

The manifest's evidence for this unit is a **non-influence test**, and there
are two, because a promise and a property are different things:

* **No verdict exists to influence anything with.** The payload carries no
  flag, grade, penalty, warning or recommendation — asserted over the payload
  keys, the same guard `simulation.py` carries.
* **No edge exists along which it could.** Nothing in `src/trade/`, and nothing
  in the roster chain itself, imports `roster_intel.exposure`; the only
  importers are the package `__init__` and the API assembly. The dependency
  arrow runs **exposure → simulation**, never back, and
  `simulation_exposure_change` takes `Any` rather than annotating
  `RosterSimulation` precisely so the annotation cannot create the edge. Both
  are pinned, and the import guard is mutation-proven (adding one import to
  `src/trade/suggestions.py` turns it red).

That is also how the spec's handcuff carve-out is discharged. *"Intentional
starting-QB + primary-backup handcuffs are purposeful exposure and should not
be flagged as accidental concentration"* is a guard against a flag. The honest
way to satisfy it is not a heuristic that guesses intent — it is to flag
nothing and report the pair. Same-franchise same-position groups appear under
`handcuffPairs` with three keys (`team`, `position`, `playerIds`) and no claim
about why they are there. On the live board this finds real ones: Saquon
Barkley + Tank Bigsby, both PHI RB.

The owner's Minnesota overlay is a **different owner** — user- and
league-scoped, outgoing side of generated packages only, specified in
`docs/trade/TRADE_GENERATION_PREFERENCES_AND_REFINEMENT_SPEC.md`. Nothing here
knows about it.

### `FA` is not a franchise

25 of 660 rostered players on the live board carry `FA` — genuine unsigned free
agents — which **ties the largest franchise by headcount** (HOU, also 25). Only
6 of those 25 are priced, so by value it is small: 0.58% of a roster on
average, 4.8% at the worst, present on 2 of 12 teams.

Both numbers matter and neither makes `FA` a team. Bucketing it as a 33rd
franchise would report the *absence* of a team as an exposure to one — a
different risk, since an unsigned player's outlook depends on a signing that
has not happened. It gets `isFranchise: false`, and `topFranchiseShare` /
`franchiseHHI` are computed over franchises only.

### Two scopes, named separately

Exposure over the **meaningful core** answers "how concentrated is the part of
this roster that plays"; over the **full roster**, "how concentrated is the
capital". They differ materially and neither is quietly chosen:

| team | core top franchise | full-roster top franchise |
|---|---|---|
| Blaine | PHI 17.8% | PHI 16.4% |
| Collin | GB 18.4% | GB 17.1% |
| Ty | HOU 21.8% | — |

Measured across the live 12-team league, core top-franchise share runs
**10.6% – 27.9%** with franchise HHI **584 – 1175**. HHI is published because
"one 25% team" and "five 5% teams" are different rosters that a single top
share cannot tell apart; it carries no threshold, because what counts as
concentrated is a judgement this module does not make.

Before → after, on a real transaction (trading Josh Allen away):

```
BUF 17.5% → 5.6%   (-11.9)
PHI 17.8% → 21.6%  (+3.9)
ATL 10.3% → 11.5%  (+1.3)
```

The change set is the **union** of both sides, so a franchise you exited
(share → 0.0) is as visible as one you entered. Reporting only the after side
would make an exit invisible, which is the direction a diversification story is
most likely to be told badly.

### Missing is never zero, and one place where zero is real

* unpriced → `unpricedIds`, no weight, still counted as roster membership;
* priced but no known NFL team → `unknownTeamIds`, **not** a bucket, because a
  franchise called UNKNOWN would then hold a share of your roster;
* picks have no NFL team and never enter — excluded by the pool builder, not
  bucketed;
* an empty population has `topFranchiseShare: null`, never `0.0`;
* a franchise you own nobody from is **genuinely 0.0%**, and that is the one
  real zero here. It is distinguishable because the missing cases live in their
  own sets rather than in the bucket list.

Cost: **+7 ms** on the live 12-team board (69 → 76 ms). No solver runs, so it
is computed for every team by default rather than made opt-in.

---

## 14. Roster capacity / forced drop (#843) — ruled TRADE-owned, and what this lane publishes for it

**This lane does not own `C3-CAP-01`, and briefly acted as though it did.**

I built `src/roster_intel/capacity.py` as "the roster half" of #843 — capacity,
required cleanup, optimal legal cleanup off the cut ladder, then a re-solve —
on the reasoning that everything left of the spec's `EVALUATE` step is roster
mechanics. Integration ruled against that, correctly:

- `docs/C_SERIES_SCOPE_MANIFEST.md:267` assigns **`C3-CAP-01` (#843) to lane
  `trade`**, as **one row, one lane**. The manifest splits nothing into halves;
  the halving was mine.
- **#913 already ships the same unit** as `src/trade/roster_capacity.py`, in the
  lane the manifest names, and the V1 contract row `V1-39` records it as the
  implementer.

Merging both would have produced two owners of one concept — the invariant this
whole campaign exists to hold, and the one my own lane brief names first. So
`capacity.py`, its tests and its exports are **removed from this branch**. The
cut was clean: nothing inside #914 consumed it.

`simulation.py` **stays**, and that is the intended shape rather than a
compromise: `C2-SIM-01` is lane `roster` in the same table and `C3-CAP-01`
depends on it. The roster lane publishes the exact before → apply → re-solve
primitive; the trade lane builds capacity and forced-drop on top.

### What this lane publishes for #913 to consume

Two primitives, both already here, so the trade lane does not have to re-derive
either:

| need | call | why not roll your own |
|---|---|---|
| before → apply → re-solve → after | `simulate_roster_change` (§ C2-SIM-01) | roster effects are set-dependent; the displaced player is frequently not the one traded |
| the cheapest LEGAL cleanup of size *k* | `roster_intel.droppability.pool_cut_ladder` | the ladder is cheapest-first and its prefixes nest, so the first *k* rungs **are** the optimal legal cut-set of size *k* — no search |

`pool_cut_ladder` takes an arbitrary pool rather than a contract precisely
because a post-trade roster does not exist in the contract. It is the answer to
the shortcut the spec forbids by name — *"do not model it solely as
`package delta - lowest raw player value`"* — and the discrimination is real:
on a roster where `SPARE_WR` (300 over a 100 waiver, cost 200) and `SPARE_TE`
(400 over a 500 waiver, cost **0**) are both legally droppable, raw value cuts
the WR and real marginal loss cuts the **dearer** player.

Two findings from the removed work that are worth carrying into #913 rather than
rediscovering, since they cost measurement to find:

* **An unknown active-roster limit must propagate `None`**, not default to
  "room". `#843` says so explicitly: *"do not silently assume zero open spots,
  zero overage, no forced drop."*
* **Taxi/IR relief is UNAVAILABLE, not zero.** The registry knows `taxiSize`,
  but Sleeper's per-player taxi assignment is ingested nowhere in this codebase
  and IR eligibility is a per-player status no canonical source carries — so
  neither the league rule nor the player eligibility the spec conditions on can
  be established. Assuming relief understates required cuts; assuming none
  overstates them for a league that has it.

---

## 15. `C2-GP-01` — is `src/roster_intel/` reachable? (measured, 2026-08-18)

`C2-GP-01`'s status is **DISCONNECTED** — *"substantial partner/package/need
logic, zero frontend consumers"* — and its acceptance is **"reachable or
removed"**. That is a question about this package, so it is answered here with a
measurement rather than an impression. Its *disposition* is still `MIGRATE` with
a dependency on `C3-PKG-01`, which this lane does not own; what follows is the
half that can be settled now.

**Method.** Direct importers of each `src/roster_intel/*` module from `src/`,
`scripts/` and `server.py` (tests excluded — a test importer is not
reachability), then the transitive closure through intra-package imports.

| module | direct | reachable | reached via |
|---|---|---|---|
| `core` | 2 | ✅ | + `age_portfolio`, `exposure`, `simulation`, `strength`, `weakness` |
| `strength` · `weakness` · `age_portfolio` · `exposure` · `droppability` | 1 each | ✅ | `api/roster_intelligence.py` |
| `simulation` | 0 | ✅ | `exposure` |
| `marginal` | 2 | ✅ | `api/gameplan.py`, `ros/lineup.py` |
| `engine` · `packages` · `targets` | 1–2 | ✅ | `api/gameplan.py`, `consensus_edge/` |
| `partner` | 4 | ✅ | `api/gameplan.py`, `intel/*` |
| `profiles` · `window` | 0 | ✅ | `engine`, `targets` |
| `roster_source` | 0 | ❌ **no** | nothing, directly or transitively |

**Fifteen of sixteen modules are reachable from production.** The "zero
frontend consumers" finding was accurate about the *frontend* and is now
outdated about *production*: `GET /api/roster/intelligence` reaches six of them,
and `partner` / `targets` were already reached from `intel/` and
`consensus_edge/` independently of gameplan.

One exception:

*(The table above was measured before `capacity.py` was removed per the
`C3-CAP-01` lane ruling in §14; it was the other unreachable module, and
removing it settles that row rather than leaving it pending.)*

**`roster_source` is genuinely superseded.** `contract_roster_pools` answers its
question for every consumer in the chain, and its motivating defect is
structurally gone rather than merely avoided: it exists because the ROS
aggregate carries no `fantasy_positions`, which is a property of the source §8
moved off. The contract carries `sleeper.fantasyPositions` — 660 of 660 rostered
players on the live board, 43 of them hybrids — and that behaviour is now pinned
(`test_a_hybrid_idp_keeps_every_slot_he_is_legally_eligible_for`, plus its
negative twin so absent eligibility cannot become *every* slot).

It is **marked superseded in its own docstring and left in place**, because
deleting it is a call for the integration lane, not for me. Exact plan if you
take it:

- **Delete**: `src/roster_intel/roster_source.py`,
  `tests/roster_intel/test_roster_source.py`.
- **Check first**: `tests/roster_intel/test_real_rosters.py` (marked `livedata`)
  imports it to build full-depth real rosters; it needs re-pointing at
  `contract_roster_pools` or deleting with it.
- **Absorbed by**: `data_contract.contract_roster_pools` (join + values +
  eligibility). `hybrid_coverage`/`JoinReport` have no direct equivalent —
  the contract path proves the same property by test rather than by a returned
  report, which is why the pin above was added before this was written down.
- **Regression test**: the two hybrid tests above must stay green; they are the
  absorption claim.
- **Blast radius**: none in production — it has no production importers,
  directly or transitively.

**What is still genuinely disconnected is the trade half**, and it is not this
lane's to move: `partner` / `targets` / `packages` are reached only from
`api/gameplan.py` and `intel/`, and `C2-GP-01`'s migration of them waits on
`C3-PKG-01`.

---

## 16. The §4.3 challenger pass on M — run, and what it does *not* settle

`docs/MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md` §4.3 keeps
`ceil(1.5 × starter demand)` as the approved V1 champion and requires a
challenger pass — 1.25× / 1.50× / 1.75× / a data-derived cutoff, evaluated for
stability across league formats — before it may be frozen as canonical
long-term methodology, with the explicit warning: *"do not tune merely until a
few hand-picked rosters look right."*

`scripts/challenge_core_multiplier.py` runs it. **It promotes nothing**, writes
no config and changes no published number; `config/roster_intel/meaningful_core.json`
keeps `reserveMultiplier: 1.5` whatever it prints. Evaluation is not activation.
Raw output and JSON: `docs/roster-intelligence/evidence/C2_CORE_M_CHALLENGER_2026-08-18.*`.

### What "meaningfully drive roster strength" was measured as

The vague half of the requirement is the important half, so it is made explicit:

```
resilience(S, k) = mean over k-subsets A of starters of optimal_score(S \ A, slots)
retention        = resilience(core, k) / resilience(full roster, k)
```

— the average lineup you can still field when *k* starters are out at once,
solved with the canonical exact solver over the real slot list.

**The first version of this measurement was wrong, and the wrongness is worth
recording.** At `k = 1` retention reads exactly `100.00%` for every candidate
*including M = 1.01*, because one absence needs at most one replacement. A
constant cannot discriminate — the same failure `tests/roster_intel/test_real_rosters.py`
records for `_positional_coverage`. `k = 1` is still printed so the degeneracy
stays visible rather than being quietly dropped; read `k ≥ 2`.

### Results — live 12-team board, four format variants

| format | M | ceiling | mean core | k=2 (worst) | k=3 (worst) |
|---|---|---|---|---|---|
| live (21 slots) | 1.25 | 29 | 27.8 | 99.93% (99.9) | 99.77% (99.6) |
| | **1.50** | **33** | **31.2** | **99.99% (100.0)** | **99.95% (99.9)** |
| | 1.75 | 41 | 37.4 | 100.00% (100.0) | 100.00% (100.0) |
| no IDP (12) | 1.25 → 1.75 | 17 → 23 | 15.8 → 21.0 | 99.90 → 100.00% | 99.67 → 100.00% |
| no SF (20) | 1.25 → 1.75 | 28 → 39 | 26.8 → 35.7 | 99.92 → 100.00% | 99.73 → 100.00% |
| offense 1QB (11) | 1.25 → 1.75 | 16 → 21 | 14.8 → 19.2 | 99.86 → 100.00% | 99.51 → 100.00% |

Retention is **monotone in M in every format**, and 1.50 sits where it should
between the two challengers. Nothing here is anomalous.

### Three findings, one of them uncomfortable

**1 — The criterion does not uniquely determine M; the target line does.**
Data-derived cutoffs at `k = 3`, live format:

| retention target | cutoff M | ceiling |
|---|---|---|
| 99.00% | 1.05 | 29 |
| 99.90% | 1.35 | 33 |
| 99.99% | 1.70 | 41 |
| 100.00% | 1.70 | 41 |

A 99% bar returns M ≈ 1.05; a 100% bar returns M ≈ 1.70. **Both are "data
derived", and they disagree by a factor of 1.6.** Reporting one target would
have made the champion look chosen by evidence when it was chosen by where I
drew the line — which is exactly the tuning the policy warns against. So all
four are published.

What the sweep *does* support: **M = 1.50 is inside the defensible band** for
every format (the 99.9%–99.99% cutoffs land between 1.35 and 1.70), and
**M = 1.25 is below every strict-target cutoff in all four formats**. The
champion beats the low challenger on the stated criterion; it is not shown to be
optimal.

**2 — M = 1.75 buys retention that no ranking notices.** It reaches 100.00% in
every format, but costs **+8 core players** in the live format (ceiling 33 → 41)
and changes **0 of 12** Team Strength seats versus M = 1.50. M = 1.25 changes
**4 of 12**. So the champion is *stable upward and unstable downward* — the risk
of being wrong is concentrated on the low side, which is an argument for not
lowering it and a weak one for raising it.

**3 — No single M is retention-maximal across formats.** The 100% cutoff is
1.70 in the live and no-SF formats but 1.55 in no-IDP. A multiplier that
saturates every format would have to be the maximum of those, and would carry
the +8-player cost above into leagues that do not need it.

### What this pass does NOT discharge

* **It is one league.** Twelve real rosters in four synthetic format variants of
  *their own* slot list is not "stability across league formats" in the sense of
  several real leagues, and the second live league's rosters are not in this
  contract. The format variants are a genuine sensitivity check, not a second
  population.
* **Resilience is not outcome evidence.** It measures what lineup a roster could
  still field, not what it scored. A calibration against realized results is a
  different exercise and needs history this lane does not own (`C1-HIST-01`).
* **`k = 3` is a seeded 120-subset sample** (exhaustive is 1,330 per team per
  candidate), so the third-decimal figures carry sampling noise. The ordering is
  stable; the exact cutoffs are not to that precision.

**M therefore stays 1.50 and stays labelled PRIOR.** The pass narrows the
defensible band and rules out the low challenger; it does not freeze the
champion, and §4.3's bar for freezing is not met by this evidence alone.

---

## 17. Hardening unit — integration's non-blocking findings (stacked on #914)

#914 is frozen for integration. This section records the follow-up unit
delivered on a branch stacked on its head, closing the eight Roster-owned
findings from the integration review. Everything here is *correctness or
ownership*; none of it is cosmetic.

### What changed, and what it was

| # | finding | repair |
|---|---|---|
| F2/F3 | `reserve_demand` re-derived slot demand; needed a private flex table and two private cross-module imports to agree with the owner | consumes `lineup.slot_demand`; `_RESERVE_FLEX_SLOTS` deleted; `ReserveDemand` publishes `flex_slots` / `dedicated_basis` |
| F1 | the league's configured flex eligibility reached no solve | `lineup.configured_slot_eligibility` (the rule) + `data_contract.contract_slot_eligibility` (the plumbing), threaded into the stamp *and* the endpoint |
| F4 | two position vocabularies; **and six spellings eligible for nothing** | one vocabulary in the chain; eligibility decided on token *or* family |
| F5 | `PositionNeed` was two types in one package | different questions → renamed `engine.PositionDeficit`, not merged |
| F6 | the board join keyed by `canonicalName` while the pool keyed by either name | keyed the way the pool keys, one row per player |
| F7 | ~10 sites raised `TypeError` on `ros_value is None` | `lineup.is_priced` / `priced_players`; exclude and report, never coerce |
| F8 | droppability counted the live auction's own rookies as free agents | default resolves them from the contract; `waiverPopulation` stamps it |

### Three things worth reading past the table

**F4 was bigger than the finding said.** Chasing the MLB grouping
mismatch turned up that `NT`, `OLB`, `ILB`, `MLB`, `FS` and `SS` all
resolved to a correct *family* and then matched **no slot at all** —
eligibility was tested on the raw token against the Sleeper-faithful
table. A genuine linebacker listed as `MLB` could not start. Fixed at the
rule (token **or** family), which is strictly a widening; the delta is
frozen in a test at 14 gained pairs and **zero lost**.

**F8's direction is the point.** Counting the auction's own rookies as
free agents *raises* the replacement bar, so every cut looks *cheaper* —
the defect `src/draft/rookie_pool.py` exists to prevent, arriving by a
different door. On defaults the two surfaces now agree 12/12 on both
`waiverValues` and `cutLadder` without being handed matched inputs.

**F5 was not consolidated, on purpose.** The brief's test is whether two
things answer the same question. A rung ladder against `k × teamCount`
and a distance below replacement do not, so they got two names rather
than one implementation.

### The pipeline is proved, not described

180 seeded rosters × 5 league shapes × 4 eligibility configurations —
including a non-laminar flex set and ~12% unpriced players — over the
real chain. No player counted twice (membership, starter/reserve
disjointness, the ceiling, Team Strength's sum and its position
re-sum, weakness rungs, and the Superflex fold as its own case). No
bypass path (one lineup solver, one `math.ceil`, no private top-N, and
every chain output takes a `MeaningfulCore` as its first parameter).

Both double-count guards are mutation-proven: letting the reserve pass
see the full pool turns 3 red, making Team Strength count reserves twice
turns 1 red.

### Boundaries held

* **`C3-CAP-01` stays trade-owned.** Nothing here touches capacity or
  forced-drop accounting; §14 records the ruling and what this lane
  publishes for #913 to consume.
* **`marginal` / `profiles` / `targets` keep the replacement vocabulary.**
  They are the older WS-J engine behind `/api/gameplan` and group for
  replacement-level purposes; re-grouping them would move a different
  owner's live numbers. The vocabulary guard names its exclusions rather
  than quietly covering seven of ten modules.
* **`engine`'s unpriced counter keeps its pre-existing conflation** of a
  real `0.0` with an unpriced player, and `marginal`'s mean-entrant value
  keeps its `0.0`-when-empty convention. Both are published numbers owned
  elsewhere; a hardening unit gets to stop them crashing, not to redefine
  them.
* **One frontend line** — `starter-slots.js`'s `LB_FAMILY` gains `MLB`,
  required by the lockstep guard the moment Python moved. Not
  presentation work.

Live board unchanged throughout: `optimalLineup` stamp hash
`a311593a9b7602ac` before and after every change in this unit.

## 18. The eligibility discard — F1 did not reach the droppability chain

Found in review of the hardening unit and repaired in the same PR.

**F1's claim was too broad.** It threaded the league's configured flex
eligibility into the lineup stamp and `/api/roster/intelligence`, and the
chain doc said the chain consumed it. The *droppability* branch did not.
The parameter was accepted, documented as applied, and discarded:

```python
# src/roster_intel/droppability.py, before
``slot_eligibility`` is accepted and, when supplied, applied by re-running
the owner against the caller's slots — it is not silently dropped.
...
del slot_eligibility  # the owner reads eligibility from the slot names
```

Three lines apart. The comment justifying the `del` was also wrong: the
owner reads `slot_eligibility` when it is given one and falls back to slot
names only when it is `None`.

**The measured chain**, all four hops:

| hop | file | carried it? |
|---|---|---|
| `pool_cut_ladder` | `roster_intel/droppability.py` | accepted, then `del` |
| `build_cut_ladder` | `draft/displacement.py` | **no parameter** |
| `_filled_slot_count` | `draft/displacement.py` | **no parameter** |
| `solve_optimal_assignment` | `ros/lineup.py` | **already accepted it** |

The terminus supported it all along; two intermediate hops dropped it.

**Why it survived F1's review.** `pool_cut_ladder` has no production and no
test caller — it is the entry point `C3-CAP-01` (#913) is built to consume,
and #913 has not consumed it yet. A latent defect in an unconsumed export
is invisible to every test that exercises the live board, which is the same
reason F4's six dead position spellings survived: *the live league does not
exercise the path*. #913 must not consume this entry point until this repair
lands.

### What it would have done

Slots `["RB", "FLEX"]`, roster `RB1`/`RB2`/`WR1`, in a league whose FLEX
admits only WR:

* the WR is the only player who can fill FLEX;
* the discarded rule left the ladder scoring him against the default
  RB/WR/TE FLEX, where `RB2` covers the slot;
* so the engine offered **releasing the one player holding the lineup
  together** as a legal cut.

That is a safety property, not a cosmetic one — the ladder's entire purpose
is to refuse cuts that break the lineup.

### The repair

* `draft/displacement.py` — `_filled_slot_count` and `build_cut_ladder` gain
  and forward `slot_eligibility`. **Plumbing only**: no eligibility table and
  no interpretation lives here, so `src/ros/lineup.py` remains the single
  owner. *(Cross-lane: this file belongs to the Perfect Draft lane. The
  change is an optional keyword defaulting to today's behaviour — flagged for
  integration rather than folded in silently.)*
* `roster_intel/droppability.py` — the `del` is gone and the value is passed
  through; the false docstring paragraph is replaced with what the code does.
* `team_droppability` now derives eligibility from the contract via
  `contract_slot_eligibility(contract) or None`, the same helper the lineup
  stamp and the endpoint use. Without this the cut ladder would score a
  custom-flex league against built-in defaults while `optimalLineup` used the
  configured ones — two answers to "who can fill this slot" inside one league.

`or None` is load-bearing in both places: an empty map means *nothing
configured*, not *no slot admits anything*. Passing `{}` through would empty
every ladder.

### Evidence

* **RED first** — 3 of the 4 new tests fail at the unrepaired head
  (`fd70515`); the fourth is the behaviour-preservation test, which must pass
  on both sides and does.
* **Mutation-proven** — re-introducing the discard turns the adversarial case
  *and* the structural guard red. The guard is an **AST** check for a real
  `Delete` node, not a substring search: the docstring above now quotes the
  retired statement, and a text match would fire on the history note while
  missing a discard written any other way.
* **Inert on the live board** — `league_droppability` over the real contract,
  before and after: **12/12 teams byte-identical** on `cutLadder` and
  `waiverValues` (95,414 bytes, sha256 `ee00e1f6e9f08410` both sides). The
  live league declares no custom flex eligibility —
  `contract_slot_eligibility` returns `{}` — so the derivation resolves to
  `None` and the defaults are unchanged. The repair is provably free for
  today's leagues and correct for a configured one.
* **The hardening unit still holds** — 68 passed across the adversarial,
  demand-chain, vocabulary, unpriced and identity suites; both double-count
  mutations still bite (reserve pass over the full pool → 3 red; Team
  Strength counting reserves twice → 1 red in the adversarial suite plus 4 in
  the strength suite).
