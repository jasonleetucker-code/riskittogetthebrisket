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
because `ros/team_strength.py:123` drops rows with `rosValue <= 0` before
writing the snapshot these adapters then read. That lossy hop is no longer on
the roster-intelligence path at all — see §8 — so the adapter's honest-missing
behaviour is now reachable rather than theoretical.

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
| `ros/team_strength.py` skips every row with `rosValue <= 0` when writing | unpriced roster membership was **deleted before any consumer saw it**, so `unpricedIds` was structurally empty and missing-is-never-zero was unenforceable downstream |

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
   neither calibrated.
2. **The Young Core Index weighting is uncalibrated.** §9 discharges #838's
   real-league validation requirement for *behaviour*; the specific weighting
   has not been fitted against outcomes.
3. **The SF-into-QB fold is an owner prior, not a measurement** — see §5.
4. **Not verified in production.** Everything above is measured against the
   tracked export archive, which is production-equivalent but not production.
   Live verification belongs to Claude 5.
5. **`roster_intel`'s only prior production consumer was `/api/gameplan`.** This
   adds a second. The package's live exposure is still narrow.
6. **`/api/gameplan` still reads the ROS snapshot**, so its `roster_intel`
   outputs (marginals, profiles, window) run on the 0-100 production index
   rather than canonical value. That endpoint is not this lane's to change —
   see §11.

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

Alternatively the ROS snapshot writer (`src/ros/team_strength.py:123`) could
stop dropping `rosValue <= 0` rows and emit them with an explicit null — but
that changes a different lane's canonical methodology and should not be done
casually.
