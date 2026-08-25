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

## 7a. D3 — the stamp did not survive the SERVING path

Found by an adversarial review of this unit AFTER it was first reported green, by two
independent reviewers, and refuted by none of six refutation attempts. It is the most serious
defect in the unit and it was mine.

`/api/data` splices a live Sleeper overlay over the baked contract and rebuilds
`sleeper.teams` **wholesale** from `sleeper_overlay._build_teams_block` (`server.py`, the
`scrubbed["sleeper"] = overlay_full` seam). That builder emits no `optimalLineup`, and nothing
re-stamped afterwards — so on the **normal** path the stamp was discarded and every frontend
lineup surface failed closed: /terminal's split bar at 0% starters, /rosters reporting
`starterSlotsUnavailable`, and `scoreTeamTiers` ranking all twelve teams on the depth term alone
with nothing on screen saying the starter term was missing.

The overlay is force-warmed after every scrape and cached for 15 minutes, so this was the steady
state. **The feature worked only while Sleeper was DOWN** — the exact inverse of a degradation.

Why every other test missed it: `tests/lineup/test_canonical_lineup.py` proves the solver is
right and `frontend/__tests__/starter-slots.test.js` proves the client renders a stamp
faithfully. Nothing tested that the stamp travels from one to the other. That is
`CLAUDE.md`'s "trace the live execution path end-to-end" rule, and this unit broke it.

**Repaired by re-SOLVING at the seam, not by copying the baked stamp.** The overlay's rosters are
fresher, so a copied lineup could start a player dropped ten minutes ago —
`test_serving_path.py` pins exactly that case. Two hazards the repair had to respect:

* the overlay's teams are entries in a **shared 15-minute cache**, so the stamp is now
  copy-on-write and never mutates the dicts it is given (in-place stamping would leak one
  request's lineup into every later request on the same entry, and on the cross-league path a
  *different league's*);
* some payload views **strip `playersArray`** (`server.py` pops it for the runtime view), so the
  value source is passed explicitly from the baked contract. Values are scoring-profile scoped
  and identical either way, so that is correct as well as safe.

Also repaired alongside it: `_stamp_optimal_lineups` read only the FIRST rung of the truth
ladder (`starter_slots_from_roster_positions`), which made the registry rung unreachable from the
only producer of the stamp — `slotSource: "registry_starters"` was a state the frontend rendered
a message for and the server had no code path to emit. It now calls the owner's
`resolve_starter_slots` with the league's registry settings, as §5 always claimed it did.

`tests/lineup/test_serving_path.py` is the regression, and its structural guards are **proven to
fire**: with the re-stamp removed they fail, and they pass with it restored.

## 7b. What else the adversarial review found

The same review that found §7a raised sixteen candidate findings across six dimensions. Three
survived its refutation panel; I re-checked the rest myself rather than trusting a refutation,
and four more were real:

**A name collision could hand one player another's SLOT LEGALITY.** Flagged independently by
three of the six dimensions. `Dynasty Scraper.py`'s new `fantasy_positions_map` was plain
last-write-wins, while `position_map` ten lines below deliberately DROPS colliding entries ("DJ
Turner WR" vs "DJ Turner II CB"). Eligibility is worse to get wrong than a label: it decides
which slots a player is legal in, so a collision could make a receiver legal at DB. Now the same
drop-on-collision rule, with its own count printed.

**My own RED claim was false.** `tests/lineup/test_c2u1_red.py`'s header said "every test here
failed at `a9be61b`". Checked against the base commit in a worktree:
`TestGreedyEnginesWereMeasurablyWrong`'s host-truth assertion **passes** there — the solver was
already exact and already 10/10. The file as a whole failed to *import* at base
(`assign_lineup` did not exist), which is what a naive "did it pass" check sees, and a collection
error is not evidence an invariant was violated. The header now states which classes were RED and
which are characterization, and why the characterization is kept.

**A latent divide-by-eligibility bug in FAAB demand.** `faab_engine.starter_slots_for_position`
divided a flex slot by `len(eligible)`, and once it read the owner's eligibility SET that became
8 for `IDP_FLEX` (DL/DE/DT/EDGE/LB/DB/CB/S) where the demand keys are 3 families — attributing
1/8 of a slot to DL instead of 1/3. Zero live impact (both leagues start no `IDP_FLEX`) but
wrong. It was also a SIXTH hand-rolled even-split derivation the census missed; it now reads
`slot_demand().even_split`, which keys demand by family precisely so this cannot happen. Verified
identical for both live leagues, and correct on the IDP case (DL 2.0, not 1.375).

**Two of my structural guards were weaker than I claimed.** The eligibility-table guard
fingerprinted only variable NAMES containing "FLEX", so a table called `_ELIGIBLE_BY_SLOT` would
pass; it now also matches dict literals KEYED by flex slot names. The no-fallback-greedy guard
walked only the two functions literally named `solve_optimal_assignment` and `assign_lineup`, so
a helper could carry the fallback; it now walks every function on the assignment path and fails
if any of those names stops existing. Both widenings are proven to fire — a `try/except` planted
in `_augment` now fails the guard, where before it passed.

**Deliberately NOT fixed: `team_strength.py`'s `ros_value=0.0` for unranked players.** It is a
real missing-is-zero coercion and the owner can now express `None` instead. Passing it would
change `health_availability_score` (its denominator is the starter count) and `unfilled_slots` on
the live /terminal composite — and that composite is **C2-U4's** unit, which will redefine it
against its own evidence. Moving a live number on a lineup unit's authority is not this unit's
call. Named in the code as an inherited decision rather than left to be discovered.

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

**One inherited condition observed and NOT acted on, because the lane split already covers it.**
`tests/api/test_launch_readiness.py::test_confidence_distribution_reasonable` asserts an absolute
floor (`high ≥ 6%`) over the LIVE board, and it currently fails: measured, **freshness is the
bottleneck axis on 682 of 740 ranked rows**, and freshness decays with wall-clock time since the
last scrape, so the assertion holds minutes after a refresh and not hours later. It fails on this
branch's **base** as well as its head.

It is **not** a `docs/ops/STABILIZATION_2026-08-16.md` §3d violation, and an earlier draft of this
document said it was. `tests/conftest.py::_LIVEDATA_MODULES` auto-marks the whole module
`livedata`, so it runs in the **advisory** lane, not the hard gate — which is precisely the
tiering §3d prescribes, working as designed. Recorded here as an observation for the confidence
lane (the 6% floor was calibrated before the five-axis gate landed and now describes a board that
no longer exists), not as a defect this unit left behind.

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
3a. **With Sleeper REACHABLE** (the §7a case): `/api/data` teams still carry
   `optimalLineup.available: true`, and /terminal shows a real starter/bench split rather than
   0% — this is the state the defect made unreachable, so verify it explicitly and first.
4. A scrape completes and the board is unchanged (`board_diff --expect-no-value-change`).
5. **After** that scrape: `sleeper.fantasyPositions` is populated, and at least one DL/LB hybrid
   is started in a slot its primary position alone would not have allowed.

### 10a. Verification record — 2026-08-18

`/api/data` and `/api/terminal` are 401 from the integration session, so the payload checks were
run against the **committed export rebuilt through `build_api_data_contract`** — same code path,
same day's real board, real Sleeper block. Real-data evidence (**L2**), not a deployed-production
response (**L3**); the browser-rendering items need a session and are marked blocked rather than
inferred from the payload.

| # | check | result | level | evidence |
|---|---|---|---|---|
| 1 | every team carries `optimalLineup` with `available: true` and `slotSource: "sleeper_roster_positions"` | **PASS** | L2 | 12 of 12 teams, `available: true` × 12, `slotSource: sleeper_roster_positions` × 12 — no other value observed |
| 2 | `/terminal` + `/rosters` render starters from the stamp | **BLOCKED-EXTERNAL** | — | needs an authenticated browser session |
| 3 | `/api/trade/simulate` `starterDelta` unchanged for starter-neutral trades | **BLOCKED-EXTERNAL** | — | 401 without a session |
| 3a | **with Sleeper reachable**, teams still carry `optimalLineup.available: true` | **PASS** | L2 | the rebuild's `sleeper` block is fully populated (`teams`, `rosterPositions`, `scoringSettings`, `fantasyPositions`, `idToPlayer`), and all 12 lineups solved — this is the state the §7a defect made unreachable |
| 4 | scrape completes, board unchanged | **PARTIAL** | — | a post-deploy scrape completed healthy (see `C1_U9` §7a for the same measurement); strict value-inertness needs a pre-deploy production snapshot that was never captured |
| 5 | `fantasyPositions` populated **and** a hybrid started in a slot its primary alone would not allow | **PASS** | L2 | 660 eligibility records; **43** players carry more than one fantasy position, **31** of them are started, and **4** occupy a slot their primary position alone does not permit |

The item-5 hits, named because "at least one" is weaker than what was found:

| player | primary | eligible | started at |
|---|---|---|---|
| T.J. Watt | DL | DL, LB | **LB** |
| Travon Walker | DL | DL, LB | **LB** |
| K'Lavon Chaisson | DL | DL, LB | **LB** |
| Travis Hunter | WR | DB, WR | **DB** |

Travis Hunter is the interesting one: the same two-way player the board applies an explicit
post-blend override to, here starting on the *defensive* side of his eligibility.

**How this measurement was nearly a false pass.** The first run joined assignments to eligibility
by Sleeper player id and reported **0** hits — which reads exactly like "the property does not
hold". It was a join failure: `sleeper.fantasyPositions` and `sleeper.positions` are keyed by
NAME, and `optimalLineup.assignments` carries `player` (a name) with no id at all. The re-run
publishes its own denominator — 240 assignments joined, i.e. 12 teams × 20 slots, all of them —
so the reader can see the check ran rather than take "0" or "4" on trust. A verification that
cannot distinguish "measured and found none" from "matched nothing" is not a verification.

### 10b. The checklist is now executable — 2026-08-24

§10a was run by hand, and its own closing paragraph records that the run
*nearly passed vacuously*. A checklist whose correctness depends on the
operator reproducing that reasoning is not a checklist, so it is now code:
**`scripts/verify_lineup_production.py`**.

```bash
# EVIDENCE-L3 — the deployed SHA. Needs a session cookie.
export ROSTER_VERIFY_COOKIE='session=…'
python scripts/verify_lineup_production.py \
    --base-url "$PROD_PUBLIC_URL" \
    --expect-sha "$DEPLOYED_SHA" \
    --json-out data/ops/lineup-verification.json

# EVIDENCE-L2 — no server, no auth, no network.
python scripts/verify_lineup_production.py --offline
```

Exit codes are the repo convention: `0` measured and passed, `1` measured
a violation, `2` something could not be measured. **`2` is never collapsed
into `0`** — "no data" must not read as "passed".

| §10 item | automated | check |
|---|---|---|
| 1 | yes | `01` stamp `available` + `slotSource` |
| 2 | **no — needs a browser** | see below |
| 3 | yes (transport half) | `03` `starterDelta` on a starter-neutral trade |
| 3a | yes | `03a` Sleeper reachable, lineups still available |
| 4 | **no — needs a pre-deploy snapshot** | see below |
| 5 | yes | `05` hybrid started off primary |
| — | yes (added) | `06` no player occupies two slots |

**What it does not compute.** No lineup. Every check reads what production
published; the solve stays in `src/ros/lineup.py`. An instrument that
recomputes what it checks verifies only that it agrees with itself.

**The two items that stay manual, and why they are not automatable rather
than merely unautomated:**

* **Item 2** (`/terminal` + `/rosters` *render* starters from the stamp)
  needs an authenticated browser session and something looking at the
  page. The server-side half — that the stamp is what the client is
  handed — is pinned offline by `tests/lineup/test_serving_path.py`.
* **Item 4** (a scrape completes and the board is unchanged) needs a
  **pre-deploy** production snapshot. §10a marked this PARTIAL for
  exactly this reason and it cannot be reconstructed after the fact.
  Capture one with `scripts/golden_board.py` **before** the next deploy
  and the item becomes measurable; skip that and it stays PARTIAL forever.

Both are printed by every run under `§10 items this instrument cannot
automate`, so a partial verification cannot quietly read as a complete one.

**Two traps are encoded, both real, both regression-pinned in
`tests/lineup/test_verify_lineup_production.py`:**

1. **The name-vs-id join** (§10a's near-false-pass). Check `05` publishes
   `assignmentsJoined` and returns **UNMEASURABLE — never FAIL** when the
   join resolves zero rows, because "matched nothing" is not "found none".
2. **The vocabulary mismatch**, found when this instrument was first run
   against a real board: `sleeper.positions` carries the raw NFL position
   (`DE`, `DT`) while slots speak the lineup vocabulary (`DL`). Comparing
   them directly counted Myles Garrett — a DE, eligible only at DL,
   started at DL — as "started off his primary", inflating the hybrid
   count **from 3 to 16**. Both sides now normalise through
   `lineup_position`, the canonical owner's own vocabulary function.

   The regression pin for this one is **discriminating, not merely
   named**, and the distinction cost a review round. A single-eligibility
   row like Garrett proves nothing: `len(eligible_set) > 1` drops him
   whether or not the vocabulary is normalised, so a fixture built on him
   passes with the normalisation deleted. The fixture therefore carries a
   **multi-eligible** DT — eligible at DL *and* LB, started at DL — for
   whom only the `DT`→`DL` normalisation decides the answer. Deleting
   either `lineup_position` call turns that test red.

**Offline run at `131abf9f9` (EVIDENCE-L2), the shipping tree:**

| check | result | n |
|---|---|---|
| 01 stamp available + `sleeper_roster_positions` | **PASS** | 12 teams |
| 03a Sleeper reachable, still available | **PASS** | 12 lineups |
| 03 `starterDelta` starter-neutral | UNMEASURABLE | no HTTP offline |
| 05 hybrid started off primary | **PASS** | 240 assignments joined, 0 unjoined |
| 06 no player in two slots | **PASS** | 240 assignments |

240 joined is 12 teams × 20 slots — the same denominator §10a published
after it fixed its join, reproduced independently by code. The hybrids
found were **T.J. Watt** (DL→LB), **Travis Hunter** (WR→DB) and **Uchenna
Nwosu** (DL→LB); the first two are the same players §10a named six days
earlier, which is the cross-check that the instrument measures what the
hand-run measured.

**Item 3's invariant is closed separately, and locally.** §10a marked it
BLOCKED-EXTERNAL on auth, which is true of the HTTP probe and only of the
probe: `starterCount` comes from `project_starters` → `assign_lineup`, all
pure Python. `tests/lineup/test_starter_neutral_trade.py` pins it (4
tests) — including the discriminating case a bench-for-bench swap cannot
catch: a **same-position starter swap**, where value moves through the
starting lineup but the seat count must not. Mutation-proven by rewriting
`team_impact.py`'s `starterDelta` to track `starterValue` instead of
`starterCount`, which turns that test RED. What remains for production is
the transport: that the deployed endpoint returns the block at all.

**Instrument mutation proof.** Reproducing the retired eligibility-blindness
defect — `RosterPlayer.eligible_positions()` made to ignore
`fantasy_positions`, the exact engine behaviour that scored 0/10 against
Sleeper's own awarded lineups — turns check `05` **FAIL** on the real
board with its full 240-assignment denominator (a measured property
failure, correctly distinguished from a join failure) and moves the exit
code 2 → 1. Restored clean.

**One structural hole closed alongside.** `tests/lineup/test_single_owner.py`
scanned `src/` only, so a second assignment engine, private eligibility
table or duplicate slot-demand derivation under `scripts/` was invisible
to the guard enforcing this row's central claim. It now scans both trees.
Every existing script already passed; a decoy script carrying
`_DEFAULT_FLEX_ELIGIBLE` is caught by file and line.

**Widening the scan was not sufficient, and that was the second review
finding.** The existing guards match on *names* — `FLEX`, `SUPER_FLEX`,
`eligible` — so a genuine second assignment engine evades all of them by
calling its slots `SPOT` and `WILD`. Injected into
`scripts/verify_lineup_production.py`, exactly such an engine passed the
widened guard 16/16. `test_no_module_outside_the_owner_defines_a_slot_
to_positions_MAP` closes that by **shape**: a dict literal of ≥2 entries
whose values are all literal position collections, at least one naming ≥2
distinct positions, is a slot→positions eligibility table regardless of
what its keys are called. No false positive anywhere in `src/` +
`scripts/`; the injected engine is caught by file and line.
