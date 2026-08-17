# C2-U1 — one canonical lineup / slot assignment

**Unit:** `C2-U1` · **Row:** `C2-LINE-01` · **Phase root:** every C2 unit consumes this
**Owner:** `src/ros/lineup.py`
**Delivered:** 2026-08-17 · **Branch:** `claude/c-series-c2-u1` (stacked on `claude/c-series-c1-u9`)
**State:** `CLOSED-PENDING-PROD` — see §10.

---

## 1. The census, re-measured at HEAD — and it did not match the plan

`docs/C_SERIES_SCOPE_MANIFEST.md` recorded **"6 competing implementations, 2 of them serving
production"**. Measured at `a9be61b` rather than assumed, the true shape is different in both
directions, and the difference matters:

### Assignment engines — **3**, and **all three served production**

| engine | surface | status |
|---|---|---|
| `src/ros/lineup.py::solve_optimal_assignment` | 9 backend consumers | **canonical, exact — kept** |
| `src/trade/team_impact.py::project_starters` | `/api/trade/simulate` | slot-ordered greedy — **retired** |
| `frontend/lib/starter-slots.js::fillLineup` | `/terminal`, `/rosters` | two-pass greedy — **retired** |
| `src/bdvm/roster.py::_quick_starter_fpg` | `/api/bdvm/roster` | per-group greedy — **retired** |

Three, not six: the frontend's three call sites (`portfolio-insights`, and `league-analysis`
twice) had already been consolidated into one `fillLineup` by the 2026-07-30 audit, and the
manifest still counted them separately. But **three in production, not two** — BDVM's engine
became live when `bdvm_engine` defaulted on (2026-07-28), after the manifest was written.

### Slot-eligibility tables — **7**

The owner plus six private copies: `team_impact` (`_DEFAULT_FLEX_ELIGIBLE` ×3),
`intel/roster_shape._FLEX_ELIGIBLE`, `scoring/replacement_level` (inline),
`bdvm/league_config._FLEX_SLOTS`, `league_intel/config.FLEX_ELIGIBLE` (comment: *"Mirrors
src/ros/lineup.py"* — a mirror maintained by comment), `trade/faab_engine._FLEX_ELIGIBILITY`,
`league_comparison/metrics.FLEX_POSITIONS`.

**The last four were found by the guard, not by the census.** A by-hand sweep missed them; the
structural test in `tests/lineup/test_single_owner.py` did not. That is the argument for the
guard existing at all, and it is recorded here rather than quietly tidied away.

### Slot-demand derivations — **5 duplicates, and 2 that are NOT duplicates**

Duplicated even-split: `lineup._slot_demand`, `team_impact._flex_share`,
`roster_shape._starter_requirements`, `replacement_level.starter_slot_counts`; plus a
*differently-biased* round-robin in `trade/suggestions`.

Deliberately **not** collapsed: `roster_intel/profiles._required_slots` (flex attributed to
nobody) and `league_intel/replacement.measure_endogenous_starters` (the flex allocation
*measured* by running the exact solver over real rosters). These answer different questions, and
LI-5 measured the even split ~40% wrong at QB — SUPER_FLEX went to a QB in 9 of 12 live rosters,
not the 1-in-4 an even split assumes. Averaging them into one number would have re-introduced
that error under a "consolidation" banner.

---

## 2. The owner was verified before it was trusted

Planning named `solve_optimal_assignment` canonical. That is not evidence, so it was checked
against ground truth that is not ours: **Sleeper's own awarded best-ball lineups**, 10 real 2025
team-weeks with real `fantasy_positions`
(`tests/league_intel/fixtures/golden_bestball_lineups.json`).

```
exact solver              10/10 reproduces the host lineup exactly
trade/team_impact greedy   0/10, short 333.66 pts
starter-slots.js greedy    5/10, short  50.14 pts
```

Its correctness argument also holds on inspection: slot eligibility defines a transversal
matroid and each player's weight is slot-independent, so descending-weight admission with
augmenting paths is the matroid greedy — provably optimal for **any** eligibility structure.

**But it carried a real defect** (§3), and the two retired engines fail for *different dominant
reasons*, which the headline numbers hide:

| engine | eligibility blindness | greedy ALGORITHM |
|---|---|---|
| `team_impact` | **238.92 pts** | **2.76 pts** (1 of 10 weeks) |
| `starter-slots.js` | **34.01 pts** | **16.13 pts** (1 of 10 weeks) |

Measured like-for-like: same slots, same eligibility. `team_impact`'s remaining gap to 333.66 is
the `K` slot its `_FILL_ORDER` never named, which did not reach its own reported output.

**The algorithmic residue is the load-bearing number.** It is measured with the canonical
eligibility handed to each greedy, so shipping the frontend better DATA — a JavaScript port of
the eligibility tables — would have left points on the table *and* kept a second implementation
to hold in sync. Correct data does not rescue a greedy. That is why the frontend fix is "the
server assigns, the client renders" and not a port.

---

## 3. The defect in the canonical owner: missing was zero

```python
base = max(0.0, float(player.ros_value or 0.0))
```

Baselined in `config/coercion_baseline.json` — a known missing-to-zero coercion sitting in the
**objective function of the canonical assignment owner**.

It is not cosmetic, and it is not cosmetic in a specific way that made it invisible: an unpriced
player scored 0, and **the total is identical either way**, so nothing that only summed values
could ever have caught it. What it did do:

* reported a slot as **filled by a player nobody can price**;
* divided `health_availability_score` by a starter count that included them;
* counted them as bench depth.

`src/ros/team_strength.py` reaches that state deliberately, for every unranked player, with a
comment saying so.

**Repaired.** `ros_value` is now `float | None`. `0.0` is a real objective — assignable,
contributes nothing. `None` is UNKNOWN — not assignable, reported in
`LineupAssignment.unpriced_ids`, and its slot reported unfilled. Unpriced players are in
**neither** starters nor bench: a third state, because folding "no read" into the bench credits
a roster with depth nobody measured. The baseline entry is deleted, not re-explained.

Visible immediately on the live contract: the `K` slot is now honestly **unfilled on every
team** (the board prices no kickers), where before a kicker was silently started at zero.

---

## 4. Two more defects the consolidation surfaced

**A WR/RB flex accepted tight ends.** `_normalize_slot_name` mapped `WRRB_FLEX` /
`WR_RB_FLEX` / `FLEX_WRRB` → `FLEX`, and `FLEX` accepts TE — so a slot whose entire purpose is
excluding tight ends would have taken one. It is now its own slot with its own eligibility.
`tests/league_intel/test_playoff_sim_li8.py` had **pinned the defect**; that assertion is
inverted, with the reason recorded beside it.

**`WRT` meant two different things.** WR/TE in `starter-slots.js`, WR/RB/TE in
`replacement_level`. Resolved to WR/RB/TE: "W/R/T" is the long-standing fantasy spelling of the
full offensive flex, and it is what two of the three tables said. `REC_FLEX` is now a genuine
two-way WR/TE flex, which is a behaviour change in `starter_slot_counts` (it had split three
ways). Neither live league runs one.

Also declared precisely rather than left as "every defender": `DL_LB` / `DB_LB` / `DL_DB`, which
`starter-slots.js` mapped to the whole IDP pool. A two-family flex is exactly the **non-laminar**
case a greedy fills wrongly.

---

## 5. What the owner now owns

**(A) League slot RULES** — `resolve_starter_slots` (the one truth ladder: live host →
registry → refuse), `flatten_starter_slots`, `starter_slots_from_roster_positions`,
`normalize_slot` + `_SLOT_ALIASES`, `slot_eligible_positions`, `player_eligible_for_slot`,
`lineup_position`, `ordered_positions` / `POSITION_ORDER`, `slot_demand`.

`lineup_position` **existed only in JavaScript**. That asymmetry is precisely why the frontend
had to keep an optimizer: the server could not name a player in the vocabulary its own slots are
written in, so it could not hand the client an assignment to render.

**(B) ASSIGNMENT** — `solve_optimal_assignment` / `assign_lineup`. Exact. **No fallback greedy**
— pinned by an AST test asserting neither function contains exception handling, because a
`try: exact except: greedy` is a second engine that only runs when nobody is looking.

`slot_eligibility` is accepted as an argument because Sleeper lets a league **configure** what
its flex takes (`flexEligible` / `sflexEligible` / `idpFlexEligible` are already in the
registry). It overrides the declared table for named slots only, and the solve stays exact under
it (brute-force pinned).

**The slot-demand contract** publishes three named, distinct quantities — `dedicated`,
`flex_capacity`, `even_split` (flagged `even_split_is_approximation`) and `flex_priority` — plus
a docstring pointer to the *measured* answer. Consumers now choose knowingly instead of each
re-deriving one silently.

---

## 6. Frontend: the server assigns, the client renders

`sleeper.teams[].optimalLineup` carries the solved lineup — assignments in slot order, starters,
bench, **unpriced**, unfilled slots, and which rung of the truth ladder produced the slots.
League-scoped by construction (it hangs off `sleeper.teams`, which
`LEAGUE_SPECIFIC_SLEEPER_FIELDS` already governs).

`fillLineup` is now a materializer: it reads the stamp and **fails closed** when there is none —
`available: false`, no local recompute, no `fallbackSlots` escape hatch. Same posture `buildRows`
already takes with `canonicalConsensusRank`, and for the same reason: a silent recompute is how
two answers to one question survive.

`lineupPosition` survives as the **display** vocabulary and is held in lockstep with
`src/ros/lineup.py::lineup_position` by `tests/lineup/test_single_owner.py`, which parses the JS
and diffs the families both ways — the arrangement `test_source_registry_parity.py` already uses.

---

## 7. Eligibility data: the gap is named, not papered over

`Dynasty Scraper.py` **had** Sleeper's `fantasy_positions` and threw it away, collapsing it to a
single primary token. So the contract carried no multi-position eligibility at all, and every
contract-driven consumer was structurally unable to honour "eligibility is absolute" — worth
238.92 points to `team_impact` alone.

The scraper now keeps it, verbatim, as `sleeper.fantasyPositions` (NFL-wide, alongside
`positions`). It arrives in the same `all_nfl` payload already fetched, so this costs no
request — discarding it was the loss. **It takes effect on the next scrape and changes nothing
until then**; absent means absent, never fabricated.

---

## 8. Inertness — measured, both axes

Captured through `scripts/golden_board.py` on the base and on this head, on one tree state so
the source CSVs are identical:

```
rows 1111 -> 1111 · VALUES: 0 moved, 0 newly priced, 0 newly unpriced · RANKS: 0 changed
ASSERTION OK: no value changed.
```

**Confidence: 0 of 1111 rows changed** — bucket, basis and quarantine flag all identical.
Measured rather than inferred, because this unit is stacked on the C1-U5 confidence work and the
two effects have to be separable.

Expected: this is roster-impact math and touches no pricing path. Worth measuring anyway.

C1-U8 (acquisition semantics) and C1-U9 (source/archive semantics) suites pass unchanged.

---

## 9. Deliberately not done

**Team Strength (C2-U4), replacement level (C2-U2) and roster simulation (C2-U3) are
untouched.** This unit defines who occupies which slot; what that lineup is *worth* is theirs.

`src/api/data_contract._build_site_pick_map` is not touched — the 2029 year-substitution defect
is C1-U6's, recorded in `docs/picks/C1_U6_D1_FABRICATED_FUTURE_YEAR_ANCHORS.md`.

`roster_intel/profiles._required_slots` and `replacement.measure_endogenous_starters` are kept as
they are: different questions, not duplicates (§1).

**One inherited defect found and NOT fixed here, because it is not this unit's.**
`tests/api/test_launch_readiness.py::test_confidence_distribution_reasonable` asserts an absolute
floor (`high ≥ 6%`) over the LIVE board. Measured: **freshness is the bottleneck axis on 682 of
740 ranked rows**, and freshness decays with wall-clock time since the last scrape — so the test
passes minutes after a refresh and fails hours later. It fails on this branch's **base** as well
as its head, and #879's CI was green on all 24 steps, so it is time-dependent rather than
code-dependent. It is a `docs/ops/STABILIZATION_2026-08-16.md` §3d violation (an absolute health
floor over live data in the hard gate) and belongs to the confidence lane, not here.

---

## 10. Why `CLOSED-PENDING-PROD`

Proven on this box; nothing has run against a live scrape. Production verification, on the
deployed merge SHA:

1. `GET /api/data` — every team carries `optimalLineup` with `available: true` and
   `slotSource: "sleeper_roster_positions"`.
2. `/terminal` and `/rosters` render starters from the stamp; the starter/bench split matches
   the server's, and the panel shows the unpriced count rather than benching those players.
3. `/api/trade/simulate` returns a `teamImpact` block whose `starterDelta` is unchanged for
   trades that change no starter.
4. A scrape completes and the board is unchanged (`board_diff --expect-no-value-change`).
5. **After** that scrape: `sleeper.fantasyPositions` is populated, and at least one DL/LB hybrid
   is started in a slot its primary position alone would not have allowed.
