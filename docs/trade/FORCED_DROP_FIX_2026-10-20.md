# Forced-drop selection and charge — correctness fix (candidate, flag OFF)

**Authority:** owner decision 2026-10-20 §2,
[`docs/owner/LOW_VALUE_ASSET_OWNER_DECISIONS_2026-10-20.md`](../owner/LOW_VALUE_ASSET_OWNER_DECISIONS_2026-10-20.md).
**Status:** IMPLEMENTED behind `forced_drop_cheapest_legal`, **default OFF**. Nothing served changes until the
owner approves the production impact in §8. Diagnosis:
[`docs/valuation/LOW_VALUE_ASSET_RESEARCH_2026-10-20.md`](../valuation/LOW_VALUE_ASSET_RESEARCH_2026-10-20.md) §5.
Evidence: [`evidence/forced_drop_fix_2026-10-20/replay.json`](evidence/forced_drop_fix_2026-10-20/replay.json)
(`scripts/forced_drop_fix_replay.py`; newest committed archive `dynasty_export_20261020_052241`, the research
board).

## 1. The defect (incumbent, file:line on `e1eff9f5f`)

| step | where | what it does |
|---|---|---|
| select | `src/draft/displacement.py:383`, sorted `:455` | ladder order is `(ECC, name)`, `ECC = max(0, base - waiver) x scarcity` |
| unpriced base | `displacement.py:376` | an unpriced player's base is *set* to the waiver value, so his ECC is 0 |
| charge | `src/trade/roster_capacity.py:1282` | `release_cost = base x scarcity` (full value, not surplus) |
| incoming | `roster_capacity.py:1234-1237` | acquired players are cut candidates, but only win on name order |
| War Room | `src/trade/trade_decision.py:444-455` | subtracts `forcedDropReleaseCost`, unpriced drops included, only when `overLimitBefore == 0` |
| Finder | `roster_capacity.py:687` | `forced_drop_cost` **excludes** unpriced drops (labelled lower bound) |

Every sub-waiver player has ECC 0, so on a full roster the cut is whoever sorts first by name and is then charged
everything he is worth. On the research board the first names are often unpriced (`Aaron Donald`,
`Adin Huntington`), so the War Room charged ~1,918 per cut **and** raised the `forced_drop_unpriced` evidence gap
(headline NOT ENOUGH EVIDENCE), while the Trade Finder charged **0** for the same cut. Two surfaces, one trade,
opposite errors.

## 2. Variants compared (45-trade War Room design, 133 asset-only filler flips)

Criteria: **C1** the cut is selected by the quantity it is charged; **C2** unpriced is never zero and never an
artifact value; **C3** no double counting (an acquired piece is not both credited by the package and charged as a
release); **C4** receiver-rational (the charge never exceeds a legal alternative, including releasing the incoming
piece); **C5** unit consistency with the package credit (full value both sides); **C6** one rule every surface can
read.

| variant | C1 | C2 | C3 | C4 | C5 | neutralised / over-corrected / surviving | steps charge > credit | median charge/credit |
|---|---|---|---|---|---|---|---:|---:|
| PROD (incumbent) | no (name order) | War Room: waiver; Finder: **0** | no | no | yes | 85 / 43 / 5 | 127 | 1.65 |
| V1 cheapest legal cut | yes | waiver ceiling | no (acquired at raw value) | partly | yes | 21 / 2 / 110 | 10 | 0.55 |
| V2a prod cuts, unpriced = 0 | no | **zero** | no | no | yes | 60 / 38 / 35 | 95 | 1.25 |
| V2b prod cuts, unpriced = position floor | no | artifact floor | no | no | yes | 64 / 38 / 31 | 97 | 1.29 |
| V3a V1 + V2a | yes | **zero** | no | partly | yes | 5 / 0 / 128 | 2 | 0.00 |
| V3b V1 + V2b | yes | artifact floor | no | partly | yes | 6 / 0 / 127 | 2 | 0.25 |
| V4 package-consistent (floor costs) | yes | artifact floor | yes | yes | yes | 1 / 0 / 132 | 0 | 0.25 |
| **V5 chosen: package-consistent, waiver ceiling** | **yes** | **documented ceiling** | **yes** | **yes** | **yes** | **6 / 0 / 127** | **0** | **0.48** |
| V6 charge surplus over replacement | yes | n/a | n/a | yes | **no** | 0 / 0 / 133 | 0 | 0.00 |
| **flag ON, measured through production** | | | | | | **6 / 0 / 127** | **0** | **0.48** |

The measured flag-ON row equals the in-script V5 recomputation exactly (independent check that the implementation
is the rule). Reproduction of the incumbent: 133 / 85 / 43 / 5, production cut set rebuilt on 135 / 135 steps.

**Why not V1.** It fixes selection but still charges a just-acquired filler its raw value while the package keeps
crediting it (credit `< value` under the geometric model), so receiving-and-releasing a player reads as a net loss.
**Why not V2/V3a/V3b/V4 as written.** V2a/V3a make unpriced free (MISSING IS NEVER ZERO). V2b/V3b/V4 price him at the
board's positional floor, which CLAUDE.md (Perfect Draft) records as an artifact (single-source 375 / 497 rows) and
explicitly rejects as a cut cost because it turns an identity-join miss into a free cut. **Why not V6.** It credits
incoming pieces at full value (the package) but charges releases only over replacement: asymmetric units; on a
full roster it charges ~0 for everything.

## 3. The rule (V5) and its math

For the receiving team, post-trade pool `P = E ∪ A` (surviving roster `E`, acquired players `A`), required releases
`d = overLimitAfter` (worst case under the taxi bracket). Lineup legality is the incumbent's, unchanged: `S` is legal
iff `fill(P \ S) ≥ fill(P)` (exact solver, `src/ros/lineup.py`).

* Release charge of a player: `c(p) = b(p) · m(pos)`, `b(p) = rankDerivedValue` if `> 0`, else `W(pos)` — the
  position's best unrostered value (`assumedWaiver`; no position → the cheapest positional `W`). `m` is the existing
  scarcity multiplier (0.85–1.15). This is the incumbent `release_cost`, unchanged.
* With the trade's package `K` (what the caller's own package math scores) and `G(K) = U_recv − U_send` under the
  active package model (one dispatch, `src/valuation_math/package_model.adjusted_pair_totals`):

  `C(S) = [G(K) − G(K \ (S ∩ A))] + Σ_{p ∈ S ∩ E} c(p)` and `S* = argmin { C(S) : S legal, |S| = d }`.

  Without a package (a caller that publishes no package net): `C(S) = Σ_{p ∈ S} c(p)`.
* Charge: `forcedDropCharge = max(0, C(S*) − C_pre)`, `C_pre` = cheapest legal cleanup the pre-trade roster already
  owed (0 unless over the limit). War Room net `= G(K) − forcedDropCharge`.

**Exactness.** For a fixed acquired subset `J = S ∩ A`, minimising `Σ c` over legal completions from `E` is a
minimum-weight problem on a matroid (the dual of the lineup transversal matroid, contracted by `J`), which the
canonical cut ladder solves greedily — it is called with `order_key = c` and `candidate_ids = J ∪ E`. Enumerating
every `J` (≤ 64 subsets; a trade delivers ≤ 3–4 players) makes `S*` the global optimum. Pinned against brute force
over every legal `d`-subset on 120 random leagues, with and without a package.

**No double counting.** An acquired piece in `S*` is removed from `K` and contributes its *credit forgone*,
`G(K) − G(K \ {f})`, never `c(f)`; so for `overLimitBefore = 0` the net is `G(K \ J) − Σ_{E} c(p)`: the package
counts each remaining piece once, each existing release is charged once, and a piece received and released counts
zero times. Multiple acquired releases split the joint credit by sequential removal (most valuable first); shares sum
to the joint credit. Monotonicity is pinned: adding an incoming piece never lowers the receiver's net (precondition:
the roster fills every slot without him — see §9).

**Unpriced (one rule, both surfaces).** An unpriced player is charged at the `assumedWaiver` ceiling for selection and
charge, and the Finder now counts it (`assumedWaiverDrops`) instead of excluding it as 0. Under `S*` he is released
only when no priced legal option (including the incoming filler) is cheaper, so the assumed value can never push a
charge above a real, priced alternative. On the War Room design, steps whose cleanup contains an unpriced player went
**49 → 0**. An *incoming* unpriced player is not in the package (the market lens never credited him), so releasing
him forgoes 0 credit: `releaseCost 0`, `value null`, still counted in `unpricedForcedDrops`.

**Determinism.** Ties break on player id (then position, then roster position), never on name; renaming every
player and shuffling the roster leaves the cut set and charge unchanged (pinned).

## 4. Consistency across surfaces

| surface | path | flag ON |
|---|---|---|
| Trade Calculator `/api/trade/simulate` | `trade_simulator._capacity_package` → `assess_roster_capacity(package=…)` | V5; `rosterCapacity.forcedDropCharge` / `forcedDropChargeBasis` / `forcedDropSelection`, per-drop `chargeBasis` |
| War Room `/api/trade/analyze` (private) | `analyze_service` → simulate → `trade_decision._objective_value` reads `forcedDropCharge` | same number as the calculator |
| Public advisor (`claude/advisor-public-backend`) | `analyze_service.analyze_trade_n(mode="market_fairness")` with Team Context, roster capacity and posture OFF (public fairness audit, PR #1889) | **none by construction** — the forced-release subtraction exists only in the private decision; nothing here is threaded into public paths |
| Trade Finder (Team Context) | `finder._board_package` → `forced_drop_cost` | same owner, board-value package; unpriced counted |
| Best Offers | `server.py` `capacity_for` → `board_package` | same as Finder |
| Angle, Suggestions, Perfect Waivers, counterparty blocks | `assess_roster_capacity` without a package | V5 selection and unpriced rule; an acquired release is charged its raw `c` (`release_cost_no_package`) — these publish no package net |
| Trade history (`trade_history_asof`, public `/league` grades) | — | **not applicable**: no roster-capacity read anywhere in the history path |
| Perfect Draft `/api/draft/roster-context` | `build_cut_ladder` without `order_key` | **unchanged** (12/12 identical on the board; pinned) |

## 5. Flag and rollback

`src/api/feature_flags.py::forced_drop_cheapest_legal`, default `False`, gate status `LIVE`. With it OFF no new field
is emitted and every path is the incumbent: `tests/trade/test_forced_drop_flag_off_identity.py` compares the
flag-OFF output (default and explicit `0`) byte-for-byte with a corpus generated on `e1eff9f5f` before any code
change (`tests/fixtures/forced_drop_flag_off_reference.json`: 32 capacity blocks in full, sha256 of 16 simulate, 16
War Room and 2 Finder payloads), and requires flag ON to change all three. Enable:
`RISKIT_FEATURE_FORCED_DROP_CHEAPEST_LEGAL=1` + restart. Rollback: `=0` (or unset) + restart.

## 6. Perfect Draft exposure (not changed here)

Perfect Draft's ladder is the same `(ECC, name)` order, and its client charges `releaseCost = base x scarcity`
(`frontend/lib/perfect-draft.js:250`). `consumptionOrder` (`:274`) re-sorts the shipped rungs by `releaseCost`, but
the *set* of rungs the backend ships was chosen by ECC/name, so a cheaper sub-waiver player beyond the shipped rungs
can be skipped the same way. Exposure is real and separate; fixing it changes MaxBid/plan numbers and needs its own
authorization.

## 7. Performance

Simulate with a 3-release 1-for-4 trade: ~35 ms → ~100 ms per call (package subset search). Finder (Team Context,
top 20): +0–10 % per team (3.1–4.1 s either way).

## 8. Exact production impact if activated (owner approval required)

Measured locally on real `dynasty_main` rosters (11 of 12 at or over the 58 cap on this board). Component B (lineup
utility) has no projection snapshot locally, so every packet stops at the evidence gate; headlines below are
decided by the production `decide()` with the utility block in the decision owner's own NOT-APPLICABLE state
(`no_remaining_fantasy_weeks`, the off-season shape) — i.e. Component A + feasibility + posture. On the box Component
B also votes.

**Scope: private surfaces only.** The public advisor runs every public path in `market_fairness` mode with Team
Context, roster capacity and posture OFF (public fairness audit, PR #1889), so its impact is **none by
construction**. The "category" columns below are `trade_decision.public_category_from_decision` applied to the
**private** War Room decision — a private-decision category mapping used here as a compact summary of the verdict,
not a served public category. (The evidence JSON keeps the key name `publicCategoryChanged`; read it as that
mapping.)

**War Room design (45 trades, 180 steps):** forced-drop set changes on 131; private-decision category changes on **112**:
UNFAVORABLE→FAVORABLE 51, UNAVAILABLE→FAVORABLE 45, UNFAVORABLE→APPROXIMATELY_EVEN 11, UNAVAILABLE→APPROXIMATELY_EVEN
3, UNAVAILABLE→STRONGLY_UNFAVORABLE 1, APPROXIMATELY_EVEN→FAVORABLE 1. The `forced_drop_unpriced` evidence gap
disappears on all 49 steps that had it.

**Census (every team; 278 seeded 1-for-2 / 2-for-1 / 1-for-3 trades):** 181 require releases; drop set changes on
174; War Room charge changes on 174 — 159 lower (at or under the cap), **15 higher** (rosters already over the limit,
which the incumbent never charged; now charged the marginal release); median change −1,691 (−3,490 … +1,271).
Private-decision category changes on **140**: UNFAVORABLE→FAVORABLE 56, UNAVAILABLE→FAVORABLE 43,
UNFAVORABLE→APPROXIMATELY_EVEN 17, UNAVAILABLE→APPROXIMATELY_EVEN 15, APPROXIMATELY_EVEN→FAVORABLE 3,
UNAVAILABLE→UNFAVORABLE 3, FAVORABLE→APPROXIMATELY_EVEN 2, UNFAVORABLE→STRONGLY_UNFAVORABLE 1.

**Trade Finder (12 teams, Team Context, top 20):** mean top-20 overlap 0.854; 4 teams identical; candidates carrying a
non-zero forced-drop cost **9 → 66** (the incumbent's alphabetical cut was usually unpriced, which the Finder
excluded as 0, so it charged almost nothing).

**Perfect Draft:** identical, 12/12 (2 teams resolve to neither mode by owner id; same in both).

**Illustrations** (NFL player names only):

| trade (send → receive) | incumbent cut → verdict | flag ON cut → verdict |
|---|---|---|
| Aidan Hutchinson (DL 4,737) → Jordyn Tyson (WR 4,587) + Dohnte Meyers (WR 1,506) | Aaron Donald (DL, unpriced, charged 1,918) → UNAVAILABLE (`forced_drop_unpriced`) | Quan Martin (DB 227) → net +798, FAVORABLE |
| Cedric Gray (LB 4,471) → Jordyn Brooks (LB 3,900) + Deone Walker (DL 373) | Aaron Donald (unpriced, 1,918) → UNAVAILABLE | Quan Martin (227) → net −507, STRONGLY UNFAVORABLE |
| Pat Freiermuth (TE 2,943) → Laiatu Latu (DL 2,696) + Dane Belton (DB 1,226) + Jake Golday (LB 1,892) | Brandon Cisse (257) + Chamarri Conner (DB 1,973) = 2,230 → net −255, UNFAVORABLE | Cisse (257) + Dee Alford (DB 430) = 687 → net +1,288, FAVORABLE |
| Matthew Golden (WR 4,403) → Nick Bolton (LB 4,205) + Zach Ertz (TE 1,728) + Cedric Tillman (WR 1,326) + Chimere Dike (WR 1,628) | Cisse 257 + Tillman (just acquired, charged raw 1,326) + Conner 1,973 = 3,556 → net −786, UNFAVORABLE | Cisse 257 + Alford 430 + Tillman (removed from package, credit 630) = 1,317 → net +1,453, FAVORABLE |
| Chris Olave (WR 6,786) → Colston Loveland (TE 6,501) + Cody White (WR 1,176) | Aaron Donald (unpriced) → UNAVAILABLE | Quan Martin (227) → net +405, FAVORABLE |
| Harold Fannin (TE 5,332) → Tee Higgins (WR 4,911) + Isaiah Williams (WR 1,061) | Aaron Donald (unpriced) → UNAVAILABLE | Quan Martin (227) → net +180, APPROXIMATELY EVEN |
| Kevin Coleman (WR 1,628) → Mike Sainristil (DB 1,484) + Dorian Williams (LB 1,234), roster already 1 over | Amani Hooker (1,475) + Austin Booker (1,818), charged 0 → net +819, FAVORABLE | Deone Walker (373, owed anyway) + James Pierre (DB 440), charged 440 → net +379, FAVORABLE |
| David Bailey (DL 3,475) → Eli Raridon (TE 2,953) + Derek Stingley (DB 1,406), roster already 1 over | Hooker + Booker, charged 0 → net +575, FAVORABLE | Walker + Pierre, charged 440 → net +135, APPROXIMATELY EVEN |

**What the owner is approving:** on team-aware surfaces, filler sweeteners stop being neutralised by an
alphabetical over-charge and become genuine roster gains (§5.3 of the research: a filler worth more than the
receiver's worst legal cut is a real gain); many private War Room verdicts move from UNAVAILABLE or UNFAVORABLE to a
decision, mostly FAVORABLE for the receiver; already-over-limit rosters start paying the marginal release; the
Finder starts ranking on forced-drop cost it previously ignored. R-C (informational disclosure) remains the tool where
market convention differs from the roster answer.

## 9. Limits

* Component B (lineup lens) is not measured locally; box headlines will differ from the A-driven stand-in.
* Scarcity resolves inert locally (multiplier 1.0); on the box it scales every charge 0.85–1.15 and enters selection
  (pinned synthetically).
* The lineup guard protects an incoming player who fills a slot the roster could not; he cannot be the release, so
  in that case receiving him can lower the net (his lineup value is Component B's).
* Taxi-partial certainty: the War Room abstains (`uncertain`) while the Finder charges a lower bound — pre-existing,
  unchanged; `dynasty_main` has no taxi.
* Under the KTC rollback package model (non-monotone) a credit forgone can be negative; the total charge is clamped at
  0.
* Angle / Suggestions / Perfect Waivers hold no package: an acquired release there is charged its raw value
  (labelled).
* UI copy: the War Room text "After the forced cut of X (worth N)" (`frontend/lib/trade-war-room-copy.js:793`) shows
  the charge; for a `package_credit_forgone` release that is the credit, not the player's value. Copy belongs to the
  UI lane.

## 10. UNRESOLVED

* Owner approval of the §8 production impact (activation is owner-gated; nothing is switched on).
* Independent mathematical review (owner §2 requires it) — not performed by the implementer; route to an
  independent reviewer.
* Box-side replay with Component B and real scarcity before activation.
* Perfect Draft exposure (§6): same selection mechanism, separate authorization.
* UI copy for `chargeBasis = package_credit_forgone` (UI lane).
* Optional follow-up: pass a package from Angle / Suggestions if their capacity blocks should net acquired releases.
