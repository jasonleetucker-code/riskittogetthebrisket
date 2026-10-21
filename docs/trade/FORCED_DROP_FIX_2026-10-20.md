# Forced-drop selection and charge — correctness fix (candidate, flag OFF)

**Authority:** owner decision 2026-10-20 §2,
[`docs/owner/LOW_VALUE_ASSET_OWNER_DECISIONS_2026-10-20.md`](../owner/LOW_VALUE_ASSET_OWNER_DECISIONS_2026-10-20.md).
**Status:** IMPLEMENTED behind `forced_drop_cheapest_legal`, **default OFF**. Nothing served changes until the
owner approves the production impact in §8 **and** decides the selection mode in §3a (V5 default vs V5-R). Revised
2026-10-20 after the independent mathematical review (verdict ACCEPT WITH FIXES: optimiser exact, flag-off identical);
fixes A–F are recorded in §3a, §3, §9 and §10. Diagnosis:
[`docs/valuation/LOW_VALUE_ASSET_RESEARCH_2026-10-20.md`](../valuation/LOW_VALUE_ASSET_RESEARCH_2026-10-20.md) §5.
Evidence: [`evidence/forced_drop_fix_2026-10-20/replay.json`](evidence/forced_drop_fix_2026-10-20/replay.json)
(`scripts/forced_drop_fix_replay.py --csv-rev d5236546f`; the research board: archive
`dynasty_export_20261020_052241` **and** the `CSVs/`, `data/scrape_state`, `config/weights` tree of `d5236546f`, both
pinned — §0).

**Verdict-change analysis (LOCAL replay):** why the verdicts move, how much of it is correction vs modelling assumption
vs sensitivity, who is affected, the overstatement test and the scarcity / anchor sensitivity —
[`FORCED_DROP_VERDICT_CHANGE_ANALYSIS_2026-10-21.md`](FORCED_DROP_VERDICT_CHANGE_ANALYSIS_2026-10-21.md)
(aggregates: [`evidence/forced_drop_fix_2026-10-20/verdict_change_analysis.json`](evidence/forced_drop_fix_2026-10-20/verdict_change_analysis.json)).
Production-box replay (prepared, **not run**, needs owner authorization):
[`FORCED_DROP_BOX_REPLAY_RUNBOOK_2026-10-21.md`](FORCED_DROP_BOX_REPLAY_RUNBOOK_2026-10-21.md).

## 0. Re-measured 2026-10-21 on main@7f35463ef after train 17 (fairness_bands_v2); pre-train-17 figures superseded

Every number in §2, §3a, §7 and §8 now describes the merged tree that would ship (code `17765f0b6` = this branch
merged with `main@7f35463ef`, train 17: `fairness_bands_v2` is THE classifier, gap / larger PACKAGE UTILITY). The
2026-10-20 figures were measured on `d5236546f` before train 17 and are superseded.

**Board pinned, and proven the same board.** The archive alone does not pin the board: the contract build also reads
`CSVs/`, `data/scrape_state` and `config/weights` from the working tree, and the 2-hourly refreshes have moved them
(an unpinned rebuild today moves 844 of 1,003 values). The replay now takes `--csv-rev` and stamps the CSV-tree revision,
its content hash and a hash of the built name → value board (`replay.json` → `board`). The original runs (`87b061787`,
`cc2272418`, `d5236546f`, `3eee173cb`) all share one CSV tree; the re-run uses `d5236546f`'s. Built with the
original code, that board hashes `01f8d09f…`; with today's code, 1,002 of 1,003 values are identical and the one
difference is **Travis Hunter 3,738 → 3,599**, a code change (#1817, two-way boost follows the row-level evidence
rules). The original code re-run on this pinned tree reproduces every committed number. The band version is read from
the band owner and stamped (`replay.json` → `fairnessBands.version` = `fairness_bands_v2`).

| headline (V5 default · V5-R alternative) | pre-train-17 | re-measured | cause |
|---|---|---|---|
| War Room filler flips (133): neutralised / over-corrected / surviving, V5 | 6 / 0 / 127 | 6 / 0 / 127 | — |
| … V5-R | 18 / 1 / 114 | **17 / 2 / 114** | v2 band (one flip now over-corrected) |
| War Room steps with charge > filler credit; median charge / credit | 0, 0.48 · 6, 0.52 | same | — |
| War Room 180 steps: cut set changes vs OFF | 131 · 131 | 131 · 131 | — |
| War Room private-decision category changes vs OFF | 112 · 108 | **109 · 105** | `stale_values` 3 · 2; v2 band 0 · 1 |
| War Room forward anomalies / acquired-piece selections | 49 / 65 · 0 / 20 | same | — |
| War Room reverse anomalies / selections | 0 / 134 · 0 / 134 | same | — |
| `forced_drop_unpriced` gap removed (War Room steps) | 49 · 49 | 49 · 49 | — |
| Census 278 trades: cut set changes / charge changes vs OFF | 174 / 174 · 174 / 174 | same | — |
| Census charge change: median (min … max) | −1,691 (−3,490 … +1,271) · −1,664 (−3,490 … +1,354) | same | — |
| Census charge down / up | 159 / 15 · 159 / 15 | same | — |
| Census private-decision category changes vs OFF | 140 · 139 | **125 · 127** | `stale_values` 14 · 12; v2 band 1 · 0 |
| Census forward anomalies / selections; reverse | 36 / 70, 0 / 167 · 0 / 34, 0 / 175 | same | — |
| V5 vs V5-R: different cut set (War Room / census); V5-R charges more | 49 / 36; 49 / 36 | same | — |
| V5 vs V5-R: private-decision category differs (War Room / census) | 22 / 9 | **20 / 9** | `stale_values` / v2 band |
| Trade Finder (12 teams, top 20): mean overlap; identical teams; trades charged OFF → ON | 0.854; 4; 9 → 66 | same | — |
| Trade Finder V5-R vs V5 | identical 12 / 12 | same | — |
| Perfect Draft identical (comparable teams) | 11 / 11 | 11 / 11 | — |
| Shadow variants (§2) V1 · V2a · V2b · V3a · V3b | 21/2/110 · 60/38/35 · 64/38/31 · 5/0/128 · 6/0/127 | **19/4/110 · 61/38/34 · 67/38/28 · 4/1/128 · 5/1/127** | shadows re-based onto the v2 band base |
| Simulate, 3-release 1-for-4, latency ratio to flag OFF (same machine): V5 · V5-R | ≈ 2.9x · — | ≈ 2.4x (author) / 4.5–6x (independent review) · ≈ 1x | machine- and load-dependent; V5-R has no package search (§7) |

**What moved and why** (attributed on the pinned board with Travis Hunter held at 3,738, so every delta is code; then
the shipping run with 3,599):

* **No capacity or charge number moved** — cut sets, charges, the charge distribution, both anomaly censuses, the
  Finder and Perfect Draft are identical, consistent with the flag-off reference, where only the War Room digests moved.
* **`stale_values` (the decision owner's evidence gate, unchanged):** the D2–D5 source-independence closeout on `main`
  (first visible at `b9801b583`) changed the confidence freshness axis on this board (at this tree: 233 rows high →
  medium, 16 IDP rows → `low`).
  A traded asset whose freshness reads `low` raises `stale_values`, which withholds the headline (UNAVAILABLE) with
  the flag OFF **and** ON — so the forced-drop fix can no longer change those trades' category. War Room 3 steps (V5) /
  2 (V5-R); census 14 (V5) / 12 (V5-R); in the census 7 trades now read `forced_drop_unpriced,stale_values → stale_values`.
* **fairness_bands_v2:** Component A is now banded against the larger package utility (a smaller base than the larger
  adjusted side once a package is deeper than one piece), so a given net reads one band stronger more often: War Room
  Component A moves modest → large on 5 flag-OFF / 11 V5 / 10 V5-R steps, and fair → slight on 2 V5-R steps. It
  changes a category count twice (V5-R War Room −1, V5 census −1), relabels a few ON categories that still differ from
  OFF, and moves one V5-R filler flip from neutralised to over-corrected. The in-script shadows (§2) are now classified on the same base the production
  decision reads (`largerPackageUtility` from the flag-OFF asset-only objective); measured and recomputed rows still
  agree exactly (6/0/127 and 17/2/114).
* **Travis Hunter 3,738 → 3,599:** changes 2 of the 45 sampled War Room trades (the sampler's value windows; he is
  the sender in one and the receiver in the other) and the value in 1 census trade. Every count is identical with and
  without it; one War Room category transition is relabelled per mode (UNFAVORABLE → APPROXIMATELY_EVEN becomes
  UNFAVORABLE → FAVORABLE).
* The private 5-level category is now read from `team_verdicts.team_category` (the same table;
  `trade_decision.public_category_from_decision` was removed upstream by the N-team advisor work).

**V5-R is still the recommended mode.** The mode comparison is unchanged where it decides the question: V5 still
names 85 of 135 cuts no rational manager makes (49 / 65 War Room, 36 / 70 census) and V5-R none; V5-R still costs 49 /
36 trades a higher charge, now with 20 / 9 category differences (was 22 / 9); the Finder is still identical.

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
piece); **C5** one currency for SELECTION (every candidate cut, existing or incoming, compared on the same quantity);
**C6** one rule every surface can read.

*Correction (review fix A).* The first version of this table defined C5 as "unit consistency with the package credit
(full value both sides)" and marked V5 **yes**. That was false: V5 costs an acquired piece at its package credit
forgone (the third piece of a geometric package is credited ~0.61x its value, no scarcity) and an existing player at
`base x scarcity`, so its SELECTION compares two different units. C5 is restated as the selection-currency question
and V5 now reads **no**. V5-R (§3a) is the variant that satisfies it.

| variant | C1 | C2 | C3 | C4 | C5 | neutralised / over-corrected / surviving | steps charge > credit | median charge/credit |
|---|---|---|---|---|---|---|---:|---:|
| PROD (incumbent) | no (name order) | War Room: waiver; Finder: **0** | no | no | yes | 85 / 43 / 5 | 127 | 1.65 |
| V1 cheapest legal cut | yes | waiver ceiling | no (acquired at raw value) | partly | yes | 19 / 4 / 110 | 10 | 0.55 |
| V2a prod cuts, unpriced = 0 | no | **zero** | no | no | yes | 61 / 38 / 34 | 95 | 1.25 |
| V2b prod cuts, unpriced = position floor | no | artifact floor | no | no | yes | 67 / 38 / 28 | 97 | 1.29 |
| V3a V1 + V2a | yes | **zero** | no | partly | yes | 4 / 1 / 128 | 2 | 0.00 |
| V3b V1 + V2b | yes | artifact floor | no | partly | yes | 5 / 1 / 127 | 2 | 0.25 |
| V4 package-consistent (floor costs) | yes | artifact floor | yes | yes | yes | 1 / 0 / 132 | 0 | 0.25 |
| **V5 package-consistent, waiver ceiling (default mode)** | **yes** | **documented ceiling** | **yes** | **yes** | **no** (mixed units) | **6 / 0 / 127** | **0 †** | **0.48** |
| **V5-R roster-rational (alternative mode)** | **yes** | **documented ceiling** | **yes** | partly (cut by `c`, not by charge) | **yes** | **17 / 2 / 114** | 6 | 0.52 |
| V6 charge surplus over replacement | yes | n/a | n/a | yes | n/a (units differ from package) | 0 / 0 / 133 | 0 | 0.00 |
| **flag ON, V5, measured through production** | | | | | | **6 / 0 / 127** | **0 †** | **0.48** |
| **flag ON, V5-R, measured through production** | | | | | | **17 / 2 / 114** | 6 | 0.52 |

† **Zero by construction, not evidence** (review fix F). Releasing the fillers themselves is always a legal option
charged exactly their package credit, and V5 minimises the charge, so V5 can never charge more than the filler credit.
The column says nothing about whether V5 is better than V1; for V5-R (which selects by `c`) it is a measurement.

Both measured flag-ON rows equal their in-script recomputations exactly (V5 and V5-R; independent check that the
implementation is the rule). Reproduction of the incumbent: 133 / 85 / 43 / 5, production cut set rebuilt on 135 / 135 steps.
Every row is classified by the band owner (`fairness_bands_v2`) on the base the production decision reads, the larger
package utility of the full package (§0); under v1 the shadows read V1 21 / 2 / 110, V2a 60 / 38 / 35, V2b
64 / 38 / 31, V3a 5 / 0 / 128, V3b 6 / 0 / 127, V5-R 18 / 1 / 114.

**Why not V1.** It fixes selection but still charges a just-acquired filler its raw value while the package keeps
crediting it (credit `< value` under the geometric model), so receiving-and-releasing a player reads as a net loss.
**Why not V2/V3a/V3b/V4 as written.** V2a/V3a make unpriced free (MISSING IS NEVER ZERO). V2b/V3b/V4 price him at the
board's positional floor, which CLAUDE.md (Perfect Draft) records as an artifact (single-source 375 / 497 rows) and
explicitly rejects as a cut cost because it turns an identity-join miss into a free cut. **Why not V6.** It credits
incoming pieces at full value (the package) but charges releases only over replacement: asymmetric units; on a
full roster it charges ~0 for everything.

## 3. The rule (V5, default mode) and its math

For the receiving team, post-trade pool `P = E ∪ A` (surviving roster `E`, acquired players `A`), required releases
`d = overLimitAfter` (worst case under the taxi bracket). Lineup legality is the incumbent's, unchanged: `S` is legal
iff `fill(P \ S) ≥ fill(P)` (exact solver, `src/ros/lineup.py`).

* Release charge of a player: `c(p) = b(p) · m(pos)`, `b(p) = rankDerivedValue` if `> 0`, else `W(pos)` — the
  position's best unrostered value (`assumedWaiver`; no position → the cheapest positional `W`). `m` is the existing
  scarcity multiplier (0.85–1.15). This is the incumbent `release_cost`, unchanged.
* With the trade's package `K` (what the caller's own package math scores) and `G(K) = U_recv − U_send` under the
  active package model (one dispatch, `src/valuation_math/package_model.adjusted_pair_totals`):

  `C(S) = [G(K) − G(K \ (S ∩ A))] + Σ_{p ∈ S ∩ E} c(p)` and `S* = argmin { C(S) : S legal, |S| = d }`.

  An acquired piece the package did not credit (`A_u`, unpriced or unresolved) also adds its own `c(p)`:
  `+ Σ_{p ∈ S ∩ A_u} c(p)` (review fix D, below).

  Without a package (a caller that publishes no package net): `C(S) = Σ_{p ∈ S} c(p)`.
* Charge: `forcedDropCharge = max(0, C(S*) − C_pre)`, `C_pre` = cheapest legal cleanup the pre-trade roster already
  owed (0 unless over the limit). War Room net `= G(K) − forcedDropCharge`.
* **Signed marginal (review fix C).** The clamp hides relief: a roster one over the limit that sends two and receives
  one is spared a cut it owed (`C(S*) − C_pre < 0`). The signed value is now published as
  `rosterCapacity.forcedDropMarginal` (and in the feasibility lens detail); the charge stays clamped at 0 and the basis
  carries `signedMarginal` + `marginalClamp: "conservative_clamp"` whenever the clamp binds — relief is reported, never
  credited to the trade. Also computed when the trade returns the roster to legal size (no post-trade drops at all).
  Flag ON only.

**Exactness.** For a fixed acquired subset `J = S ∩ A`, minimising `Σ c` over legal completions from `E` is a
minimum-weight problem on a matroid (the dual of the lineup transversal matroid, contracted by `J`), which the
canonical cut ladder solves greedily — it is called with `order_key = c` and `candidate_ids = J ∪ E`. Enumerating
every `J` (≤ 64 subsets; a trade delivers ≤ 3–4 players) makes `S*` the global optimum. Pinned against brute force
over every legal `d`-subset (coverage below).

**Search bound, explicit (review F2).** The subset count is `Σ_{j ≤ min(d, |A|)} C(|A|, j)`. Above 64 (e.g. 7 incoming
with `d = 4` is 99) V5 used to skip the package step silently, i.e. switch to raw charging — a different currency
presented under the V5 rule id. It now (a) publishes `forcedDropSelection.searchBound` (64) and
`searchBoundExceeded`, (b) uses the **V5-R selection with package charging** instead (exact and polynomial: one
ladder, no subset search; a just-acquired release is still netted out of the package), (c) publishes the roster-rational
rule id (what actually ran) and a note. At or below the bound nothing changes and `searchBoundExceeded` is `false`. **Discontinuity at the bound:** the V5-R charge can exceed the true V5 minimum (up to about 0.9 in adversarial 7-9-piece trades in the final review's sweep), so a 7-piece trade is priced a little differently from a 6-piece one. The Finder's widest shape is 3 incoming, so this reaches only hand-built simulate trades of 7 or more players.
Pinned: `test_search_bound_exceeded_is_explicit_and_uses_package_charging_review_f2`,
`test_at_or_below_the_search_bound_nothing_changes`, `test_search_bound_is_published_in_the_capacity_block`.

**No double counting.** An acquired piece in `S*` is removed from `K` and contributes its *credit forgone*,
`G(K) − G(K \ {f})`, never `c(f)`; so for `overLimitBefore = 0` the net is `G(K \ J) − Σ_{E} c(p)`: the package
counts each remaining piece once, each existing release is charged once, and a piece received and released counts
zero times. Multiple acquired releases split the joint credit by sequential removal (most valuable first); shares sum
to the joint credit. **Net-monotonicity holds for V5 ONLY** (independent review F1): adding a CREDITED incoming piece
never lowers the V5 receiver's net, because V5 can always undo the extra piece by releasing it at the credit it
forgoes (preconditions: the roster fills every slot without him, and the package credits him — see §9). **V5-R does
not have this property** (§3a, §9): its cut set is chosen in a different currency, so a free credited extra piece can
lower its net.

**Unpriced (one rule, both surfaces).** An unpriced player is charged at the `assumedWaiver` ceiling for selection and
charge, and the Finder now counts it (`assumedWaiverDrops`) instead of excluding it as 0. Under `S*` he is released
only when no priced legal option (including the incoming filler) is cheaper, so the assumed value can never push a
charge above a real, priced alternative. On the War Room design, steps whose cleanup contains an unpriced player went
**49 → 0**.

*Unpriced incoming (review fix D).* The first version charged an *incoming* unpriced player 0 when released (the
package never credited him, so the credit forgone is 0) and did not count him in `assumedWaiverDrops` — which made him
the free first cut every time and turned an identity-join miss into a free cut (the Perfect Draft hazard in
CLAUDE.md). Now an incoming piece the package did not credit (unpriced or unresolved; matched label by label, k-th
incoming player with a label ↔ k-th package entry with that label) is costed and charged its own `c` at the
`assumedWaiver` ceiling, labelled `chargeBasis: "release_value_uncredited"`, and counted. Consequence for monotonicity
(§9): receiving an *uncredited* extra piece can lower the net by up to the cheapest legal cut.

*Basis state (review fix D).* `forcedDropChargeBasis.state` is no longer `exact` when the charge rests on an assumed
value: `assumed` (`bound: "upper"` — the waiver level is the unpriced player's documented ceiling) when an assumed drop
is in the post-trade cleanup only; `lower_bound` (reason `pre_trade_cleanup_assumed_waiver`) when only in the pre-trade
cleanup it is netted against; `mixed_bound` when both or combined with another lower-bound reason. A drop owed both
before and after the trade cancels out of the marginal and does not taint it. The War Room objective carries the same
state (`objectiveValue.forcedReleaseChargeState`) as the Finder's `rankingFactors.forcedDropCostBasis.state`, because
both read `roster_capacity.forced_drop_cost`.

*Taxi-unknown lower bound (review F3).* When taxi membership is invisible the charge covers only the releases
guaranteed under every assignment (`over_limit_after_min`, capped at the roster's growth). It used to be the cheapest
`k` drops of the *worst-case* cleanup — a legal `k`-set but not always the cheapest one (the lineup guard and the
package step couple the choices): in 23 of 462 random cases a different legal `k`-set was strictly cheaper (e.g. 261
against 335), so the label `lower_bound` was not guaranteed. The bound is now RE-SELECTED at the guaranteed count with
the charge-minimising (V5) selection whichever mode is served (the V5-R set minimises `Σ c`, not the charge, so its
cost at a smaller count is not a lower bound), and is pinned equal to the brute-force minimum over every lineup-legal
`k`-set on 240 seeded cases. **Over-cap caveat (final review):** that holds when the roster is not over the cap before the trade. A roster already over the cap owes a cleanup under any taxi occupancy and the guaranteed post-trade releases are not netted against it, so there the published bound is 0 (reason `pre_trade_overage_not_netted_taxi_unknown`), the only bound the marginal cannot undercut.

*Incomplete or undeterminable cleanups (re-review findings 1, 3; flag-ON code only).* A cleanup that stops short of
legal size is never reported as exact: `forcedDropMarginal` is `null` when either the post-trade ladder
(`ladderExhausted`) or the pre-trade cleanup is exhausted; exhaustion is checked *before* the "trade adds no release
cost" return, so an exhausted post-trade ladder with a netted marginal ≤ 0 reads `lower_bound`
(`cut_ladder_exhausted`), never `none`; an exhausted pre-trade cleanup understates what the roster owed, so the
marginal is an upper bound — `upperBoundReasons: ["pre_trade_cleanup_exhausted"]`, state `assumed` (or `mixed_bound`
with any lower-bound reason). With no waiver-level values at all, an `assumedWaiver` release on either side of the
marginal would have base 0, so the charge is `null` with `{state: "unknown", reason: "waiver_values_unavailable"}`
(never 0). The flag-OFF path is untouched (§11 names its pre-existing behaviour as a follow-up).

**Determinism.** Ties break on player id (then position, then roster position), never on name; renaming every
player and shuffling the roster leaves the cut set and charge unchanged (pinned).

**Exactness coverage (review fixes B, F).** Both modes are pinned against brute force over every legal `d`-subset on
100 random leagues each × {with, without package}: 40 plain (QB/RB/WR/TE/FLEX), 30 with **real scarcity multipliers
drawn in 0.85–1.15 per position** (mixed incoming/existing candidates, so the one-sided-scarcity question is exercised),
and 30 SUPER_FLEX + IDP leagues (`QB, RB, WR, TE, SUPER_FLEX, DL, LB, DB, IDP_FLEX`, 11-man roster, 1–4 incoming,
**d up to 4**). Plus the identity `charge(V5) ≤ charge(V5-R)` and `Σc(V5-R cut) ≤ Σc(V5 cut)` on the same 100.

## 3a. OWNER DECISION — selection mode: V5 (trade-consistent) vs V5-R (roster-rational)

**The mismatch (review finding A).** V5 compares an acquired piece at its *package credit forgone* with an existing
player at `base x scarcity`. Under the geometric package model a third piece is credited well below its own value, so
V5 can release a more valuable incoming player and keep a less valuable existing one. Synthetic, pinned: receive
[5000, 1000, 1000] with an existing 700 the cheapest roster player → V5 releases a 1,000 incoming piece charged ~608;
V5-R releases the 700. Real board, V5: **Dru Phillips (DB, 1,293) released while Jonathan Allen (DL, 1,197) is kept;
Keisean Nixon (DB, 1,427) / LeQuint Allen (RB, 1,487) released while Jonathan Allen is kept; Avieon Terrell (DB, 565)
released while Dee Alford (DB, 430) is kept.**

**V5-R (implemented, a sub-option of the same flag).** Choose the cut set by `c(p) = base x scarcity` uniformly across
existing AND incoming players (the true cheapest legal roster cut — exact, the same ladder with no package step), then
charge an acquired cut its package credit forgone (no double count) and an existing cut `c(p)`. Switch:
`src/trade/forced_drop_selection.py::SELECTION_MODE` (`package_consistent` | `roster_rational`), a reviewed constant
rather than an environment read, because switching it changes served verdicts. Published rule ids
`cheapest_legal_package_consistent_v1` / `cheapest_legal_roster_rational_v1`.

**Currency anomaly**, measured in both directions by a single lineup-legal swap (exact lineup solver), with
`c = base x scarcity`: **forward** — an acquired piece released while a cheaper existing player, who could legally
have been released instead, is kept; **reverse** — an existing player released while a cheaper *acquired* piece, who
could legally have been released instead, is kept (re-review finding 2: reachable under V5 whenever a piece's package
credit exceeds its `c`, e.g. scarcity < 1 shrinks `c` but not the credit). Measured on the flag-ON production path:

| measure (same board, same designs) | V5 (default) | V5-R |
|---|---:|---:|
| War Room filler flips (133): neutralised / over-corrected / surviving | 6 / 0 / 127 | 17 / 2 / 114 |
| War Room steps with charge > filler credit | 0 (by construction) | 6 |
| median charge / filler credit | 0.48 | 0.52 |
| War Room 180 steps: private-decision category changes vs OFF | 109 | 105 |
| War Room: forward anomalies / selections releasing an acquired piece | **49 / 65** | **0 / 20 ‡** |
| War Room: reverse anomalies / selections releasing an existing player while keeping an acquired one | 0 / 134 § | 0 / 134 ‡ |
| Census 278 trades: private-decision category changes vs OFF | 125 | 127 |
| Census: forward anomalies / selections releasing an acquired piece | **36 / 70** | **0 / 34 ‡** |
| Census: reverse anomalies / selections releasing an existing player while keeping an acquired one | 0 / 167 § | 0 / 175 ‡ |
| Census charge change vs OFF: n, median (min … max) | 174, −1,691 (−3,490 … +1,271) | 174, −1,664 (−3,490 … +1,354) |
| V5 vs V5-R: steps with a different cut set (War Room / census) | — | 49 / 36 |
| … of which V5-R charges more / less | — | 49 / 0 ; 36 / 0 |
| … of which the private-decision category differs | — | 20 / 9 |
| Trade Finder (12 teams, top 20): mean overlap vs OFF; teams identical | 0.854; 4 | 0.854; 4 |
| Trade Finder: V5-R vs V5 | — | identical on 12 / 12 |

‡ **Zero by construction, not evidence** (same status as V5's † in §2). V5-R's cut set is the minimum-`Σc` legal set
(exact; pinned against brute force), so no single legal swap can lower `Σc` — in either direction. The V5-R anomaly
cells confirm the implementation is the rule; they are not a measured advantage.

§ **Zero locally because scarcity is inert here (1.0), not by construction.** At scarcity 1.0 a piece's package credit
under the geometric model never exceeds its own value, so it never exceeds `c` and V5 has no reason to keep a cheaper
acquired piece. On the box (scarcity 0.85–1.15) it can; **the box replay with real scarcity must report both
directions** (`currencyAnomaly.currencyAnomalies` and `.reverseCurrencyAnomalies`, §10 item 3).

(The review counted 14 of 86 package-step selections under a different definition; this record uses the single-swap
definition above, which is mechanical and reproducible from `replay.json` → `currencyAnomaly`.)

**What each one optimises.** V5 is *trade-consistent*: it maximises the very net the War Room publishes,
`G(K \ J) − Σ_E c`, so the receiver's verdict is the best the package lens allows; its "cut" can be a player the
manager would never actually release. V5-R is *roster-rational*: the cut shown is the cheapest real roster cut in one
currency, and the charge is then the honest accounting of that cut; its net is never above V5's (by construction) and
is lower on exactly the anomalous selections (by `c(acquired) − credit` there).

**V5-R is NOT net-monotone, and V5-R's net is dominated by V5's (review F1).** V5 minimises the charge, so on any
instance V5's net `G(K \ J) − Σ c` is at least V5-R's (pinned as an identity). The two differ in 77 of 545 randomly
generated instances with a cut-set difference, and in every one V5-R charges more (median +80). V5-R also gives up
the monotonicity V5 has: in 63 of 767 random cases a *free credited extra* incoming piece LOWERED V5-R's net, by up to
1,298; V5 had 0 violations. Minimal reproducer (pinned by
`tests/trade/test_forced_drop_selection.py::test_v5r_net_is_not_monotone_in_a_free_credited_extra_piece_v5_is`): a
roster at the cap whose cheapest player is a 900 bench player; trade 1 sends [3,000] and receives [3,000] (net 0);
trade 2 is the same plus a free 1,000 — V5 releases the 1,000 it just received at its package credit (780), net 0;
V5-R cuts the 900 bench player (900 > 780), net −120. This is the price of the roster-rational cut, not a regression:
V5-R keeps more raw roster value (it never trades a more valuable real player for a cheaper-looking package credit),
at the cost of a net that can fall when a free piece is added. The test exists so this is never mistaken for one.

**Filler-flip outcome.** V5-R neutralises more sweetener flips (17 vs 6; V1 neutralised 19) and over-corrects two,
because a sweetener whose package credit is below its value is no longer the convenient cut. The research verdict
(§5.3: a filler worth more than the receiver's worst legal cut is a genuine gain) holds under both; V5-R simply does
not let the package discount make the incoming filler look cheaper than it is.

**Recommendation: V5-R**, but the shipped default stays **V5** until the owner chooses (the evidence does not *clearly*
favour V5-R on outcomes — there is no realized-outcome ground truth for either — it favours V5-R on correctness of the
displayed cut). Reasoning: (1) the War Room and Finder SHOW the cut by name; under V5, 85 of 135 real selections that
release an acquired piece name a cut no rational manager makes ("release Dru Phillips 1,293, keep Jonathan Allen
1,197"); (2) V5's advantage — a higher receiver net — comes entirely from exploiting the package model's depth
discount inside a roster-spot calculation, and that discount already prices part of the roster-spot cost, so V5 leans
on it twice in the receiver's favour; (3) the cost of V5-R is bounded and visible: 49 of 180 / 36 of 278 trades are
charged more, 20 / 9 change category, and the Finder is unchanged. (Re-confirmed on the post-train-17 tree, §0.) **Owner decision (2026-10-21, LVA Package 1,
`docs/owner/LVA_OWNER_DECISIONS_2026-10-21.md`): V5-R.** `SELECTION_MODE` is now `roster_rational`. It is read only
while the flag is ON, and the flag stays OFF, so served output is unchanged. V5 remains implemented, tested and
measured by the replay. The owner also asked that V5-R's non-monotonicity (§3a, "a free better player lowered the
net") be investigated and included in the activation recommendation.

## 4. Consistency across surfaces

| surface | path | flag ON |
|---|---|---|
| Trade Calculator `/api/trade/simulate` | `trade_simulator._capacity_package` → `assess_roster_capacity(package=…)` | the selected mode; `rosterCapacity.forcedDropCharge` / `forcedDropChargeBasis` / `forcedDropMarginal` / `forcedDropSelection`, per-drop `chargeBasis` (`release_value` \| `package_credit_forgone` \| `release_value_uncredited` \| `release_value_no_package`) |
| War Room `/api/trade/analyze` (private) | `analyze_service` → simulate → `trade_decision._objective_value` reads `forcedDropCharge` | same number as the calculator; `objectiveValue.forcedReleaseChargeBasis` (`release_value` \| `package_credit_forgone` \| `mixed`) and `forcedReleaseChargeState` (the capacity basis state) |
| Public advisor (`claude/advisor-public-backend`) | `analyze_service.analyze_trade_n(mode="market_fairness")` with Team Context, roster capacity and posture OFF (public fairness audit, PR #1889) | **none by construction** — the forced-release subtraction exists only in the private decision; nothing here is threaded into public paths |
| Trade Finder (Team Context) | `finder._board_package` → `forced_drop_cost` | same owner, board-value package; unpriced counted |
| Best Offers | `server.py` `capacity_for` → `board_package` | same as Finder |
| Angle, Suggestions, Perfect Waivers, counterparty blocks | `assess_roster_capacity` without a package | cheapest-legal selection and unpriced rule (both modes agree without a package); an acquired release is charged its raw `c` (`release_value_no_package`) — these publish no package net |
| Trade history (`trade_history_asof`, public `/league` grades) | — | **not applicable**: no roster-capacity read anywhere in the history path |
| Droppability ladder (`src/roster_intel/droppability.py`) | `build_cut_ladder` without `order_key` | **unchanged**: ECC order with the flag ON, like Perfect Draft; it is not a forced-drop charge |
| Perfect Draft `/api/draft/roster-context` | `build_cut_ladder` without `order_key` | **unchanged** (11 of 11 comparable teams identical on the board; the 12th raises `ValueError` in both modes and is excluded; pinned synthetically) |

**Which surfaces pass the trade's package (review F8).** The charge function is one (`forced_drop_cost`), but only the
surfaces that hand `assess_roster_capacity` a `PackageSides` read a charge with an acquired release netted out of it:
the War Room and Trade Calculator (`/api/trade/analyze`, `/api/trade/simulate`), the Trade Finder and Best Offers.
Angle, Suggestions, Perfect Waivers and the counterparty block read the same function without a package (an acquired
release at its raw `c`); the droppability ladder and Perfect Draft stay on ECC order with the flag ON. "One number
across surfaces" therefore holds between the first group, not across the two.

## 5. Flag and rollback

`src/api/feature_flags.py::forced_drop_cheapest_legal`, default `False`, gate status `LIVE`. With it OFF no new field
is emitted and every path is the incumbent: `tests/trade/test_forced_drop_flag_off_identity.py` compares the
flag-OFF output (default and explicit `0`) byte-for-byte with a corpus generated on `e1eff9f5f` before any code
change (re-recorded 2026-10-21 on pure `main@7f35463ef`, which still lacks this fix, after train 17 moved the 16 War
Room digests; the capacity, simulate and Finder digests did not move) (`tests/fixtures/forced_drop_flag_off_reference.json`: 32 capacity blocks in full, sha256 of 16 simulate, 16
War Room and 2 Finder payloads), and requires flag ON to change all three. The identity test is unchanged by the
review fixes and still passes. Enable: `RISKIT_FEATURE_FORCED_DROP_CHEAPEST_LEGAL=1` + restart. Rollback: `=0` (or
unset) + restart. The selection mode (§3a) is a code constant, `SELECTION_MODE`, read only when the flag is ON.

## 6. Perfect Draft exposure (not changed here)

Perfect Draft's ladder is the same `(ECC, name)` order, and its client charges `releaseCost = base x scarcity`
(`frontend/lib/perfect-draft.js:250`). `consumptionOrder` (`:274`) re-sorts the shipped rungs by `releaseCost`, but
the *set* of rungs the backend ships was chosen by ECC/name, so a cheaper sub-waiver player beyond the shipped rungs
can be skipped the same way. Exposure is real and separate; fixing it changes MaxBid/plan numbers and needs its own
authorization.

## 7. Performance

Latency is reported as **ratios to the flag-OFF path on the same machine in the same run**, not as milliseconds:
absolute times move with machine, load and the train-17 analyze work (the OFF baseline itself roughly doubled between
the two measurements), and the two independent measurements below disagree on the V5 ratio.

| path (simulate, 3-release 1-for-4) | author, 2026-10-21 | independent review, shared machine |
|---|---:|---:|
| flag OFF | 1.0x | 1.0x |
| V5 (package subset search; the shipped default) | ≈ 2.4x | **≈ 4.5–6x** |
| V5-R (one ladder, no subset search) | ≈ 0.9x | ≈ 0.9x |

Read this as: V5 costs a small multiple of OFF (the subset search runs one ladder per acquired subset, at most 64 —
beyond that V5-R's single ladder is used, §3), and V5-R costs about the same as OFF. The earlier "2.4x" is the low end
of what was measured, not a bound. Trade Finder (Team Context, top 20, 12 teams): per-team time is dominated by
candidate generation; the median is within noise of OFF in all three paths (ratios ≈ 1.0x · 1.0x · 0.9x). No latency
budget is claimed; the box replay (runbook) should record the same ratios on production hardware.

## 8. Exact production impact if activated (owner approval required)

Measured locally on real `dynasty_main` rosters (11 of 12 at or over the 58 cap on this board). Component B (lineup
utility) has no projection snapshot locally, so every packet stops at the evidence gate; headlines below are
decided by the production `decide()` with the utility block in the decision owner's own NOT-APPLICABLE state
(`no_remaining_fantasy_weeks`, the off-season shape) — i.e. Component A + feasibility + posture. On the box Component
B also votes.

**Scope: private surfaces only.** The public advisor runs every public path in `market_fairness` mode with Team
Context, roster capacity and posture OFF (public fairness audit, PR #1889), so its impact is **none by
construction**. The "category" columns below are `team_verdicts.team_category` (formerly
`trade_decision.public_category_from_decision`, same table) applied to the
**private** War Room decision — a private-decision category mapping used here as a compact summary of the verdict,
not a served public category. (The evidence JSON keeps the key name `publicCategoryChanged`; read it as that
mapping.)

All numbers below are the **default mode (V5)**; the V5-R alternative is in the §3a table (War Room 105 category changes,
census 127, Finder identical to V5). Re-run after the review fixes: every V5 number is unchanged (the unpriced-incoming
fix D never binds on this board — no unpriced incoming piece was a cheapest cut). **Re-measured 2026-10-21 on the
post-train-17 tree (§0)**; the pre-train-17 figures (112 / 140 category changes) are superseded.

**War Room design (45 trades, 180 steps):** forced-drop set changes on 131; private-decision category changes on **109**:
UNFAVORABLE→FAVORABLE 51, UNAVAILABLE→FAVORABLE 45, UNFAVORABLE→APPROXIMATELY_EVEN 8, UNAVAILABLE→APPROXIMATELY_EVEN
3, UNAVAILABLE→STRONGLY_UNFAVORABLE 1, APPROXIMATELY_EVEN→FAVORABLE 1. The `forced_drop_unpriced` evidence gap
disappears on all 49 steps that had it; 3 steps keep `stale_values` (an IDP asset with freshness `low`) and stay
UNAVAILABLE in both modes of the flag.

**Census (every team; 278 seeded 1-for-2 / 2-for-1 / 1-for-3 trades):** 181 require releases; drop set changes on
174; War Room charge changes on 174 — 159 lower (at or under the cap), **15 higher** (rosters already over the limit,
which the incumbent never charged; now charged the marginal release); median change −1,691 (−3,490 … +1,271).
Private-decision category changes on **125**: UNFAVORABLE→FAVORABLE 52, UNAVAILABLE→FAVORABLE 39,
UNFAVORABLE→APPROXIMATELY_EVEN 16, UNAVAILABLE→APPROXIMATELY_EVEN 14, APPROXIMATELY_EVEN→FAVORABLE 1,
UNAVAILABLE→UNFAVORABLE 1, FAVORABLE→APPROXIMATELY_EVEN 1, UNFAVORABLE→STRONGLY_UNFAVORABLE 1. The
`forced_drop_unpriced` gap disappears on 61 trades; on 7 of them `stale_values` remains and withholds the headline.

**Trade Finder (12 teams, Team Context, top 20):** mean top-20 overlap 0.854; 4 teams identical; candidates carrying a
non-zero forced-drop cost **9 → 66** (the incumbent's alphabetical cut was usually unpriced, which the Finder
excluded as 0, so it charged almost nothing).

**Perfect Draft:** identical on **11 of 11** comparable teams. The 12th team's roster context raises `ValueError` in
both modes and is excluded rather than counted identical (the first version reported "12/12", counting the two error
payloads as a match; the review's "2 teams" read the error counter, which counted one team once per mode).

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
* Scarcity resolves inert locally (multiplier 1.0), so **every replay number in §3a and §8 is at scarcity 1.0**. On the
  box it scales every existing player's `c` by 0.85–1.15 while an acquired piece's package credit carries no scarcity
  (review finding B: the multiplier is one-sided under V5's charge, and under V5-R it enters selection on both sides
  but only existing cuts' charges). Exactness under real multipliers is pinned synthetically (§3); **a box replay with
  real scarcity is required before activation** (§10).
* The lineup guard protects an incoming player who fills a slot the roster could not; he cannot be the release, so
  in that case receiving him can lower the net (his lineup value is Component B's).
* **"Lineup-legal" means rank-preserving, nothing more (review F5).** A cut set `S` is legal iff the number of filled
  starting slots after releasing it is at least the number before (`fill(P \ S) ≥ fill(P)`, the exact assignment
  solver). It does not ask whether the cut changes WHO starts, by how much, or whether a starter is hurt; and
  injury status plays no part in selection or charge — the contract's rows carry no `injured` field, so the
  `RosterPlayer.injured` the ladder is built with is never set on this path. A cut can therefore release a healthy
  low-value player the roster would rather keep over an injured starter it cannot use, and cannot release one the
  guard needs. Lineup effects of the trade (starter changes, depth, injury) are Component B's (the roster-utility
  lens), not this charge's; selection stays a pure roster-value cost.
* Receiving an *uncredited* (unpriced/unresolved) extra piece can lower the net by up to the cheapest legal cut: he
  takes a spot with no package credit and is never a free cut (review fix D). Monotonicity is pinned for credited
  pieces only, **and for V5 only**: V5-R's net is non-monotone (63 of 767 random cases lowered by a free credited
  piece, up to 1,298; reproducer pinned, §3a) and is dominated by V5's net on the 77 of 545 instances where the two cut
  sets differ.
* `forcedReleaseChargeBasis` summarises every forced drop, including ones an over-limit roster owed anyway, so it can
  read `mixed` when the marginal itself is all package credit.
* **`forcedDropReleaseCost` is GROSS (review F6).** The evidence field of that name (feasibility lens detail, the
  decision's `feasibility` / `roster_construction` evidence, the capacity block) is the sum of every modelled release
  at its charge, including releases an over-limit roster owed before the trade; the number the objective subtracts is
  `forcedDropCharge` (marginal, clamped at 0). Flag ON now labels it
  (`forcedDropReleaseCostBasis: "gross_post_trade_cleanup_including_pre_owed"`) and publishes `forcedDropCharge` and the
  signed `forcedDropMarginal` beside it in the decision evidence (650 gross against a 350 charge in the pinned
  example). Flag OFF packets are unchanged.
* Duplicate incoming labels: the package removes by label and multiplicity, so with two incoming players sharing a
  label the credited/uncredited match is positional. Not reachable with distinct player names.
* Taxi-partial certainty: the War Room abstains (`uncertain`) while the Finder charges a lower bound — pre-existing,
  unchanged; `dynasty_main` has no taxi.
* **Credit clamp (review F4).** A released just-acquired set is charged the package credit forgone, clamped to
  `[0, Σ c]` of its credited pieces **only** when (a) the kept side would be empty (the credit is then the whole
  received side, not bounded by the geometric discount, and can exceed the piece's own `base x scarcity` — e.g. a sole
  incoming piece at scarcity 0.85) or (b) the active package model is not geometric (the KTC rollback `ktc_2026_04`
  is non-monotone: a piece's credit can be negative — 210 of 3,000 random packages had a negative total, hidden by the
  total's clamp at 0 — which would reward cutting him). The clamp is applied inside the selection (so V5 still
  minimises the charge actually made) and publishes `forcedDropSelection.packageCreditClamp`
  (`reasons`, `rawCredit`, `charged`) and a note; with a geometric model and other pieces remaining nothing changes
  (`packageCreditClamp` is `null`). Pinned: `test_sole_incoming_release_credit_is_clamped_to_its_release_value_review_f4`,
  `test_ktc_rollback_negative_credit_is_clamped_at_zero_and_published_review_f4`,
  `test_credit_is_not_clamped_while_other_pieces_remain_in_a_geometric_package`; the brute-force oracle applies the same
  rule written from this paragraph. At scarcity 1.0 the clamp binds only when the credit and `c` differ; the §0 / §8
  replay figures were measured before it and are not re-measured here (named in §11).
* Angle / Suggestions / Perfect Waivers hold no package: an acquired release there is charged its raw value
  (labelled).
* UI copy: see the activation blocker in §10.

## 10. Activation checklist (every item blocks activation)

1. ~~**Owner decision — selection mode**~~ **DECIDED 2026-10-21: V5-R** (`roster_rational`, now the constant's value;
   `docs/owner/LVA_OWNER_DECISIONS_2026-10-21.md` Package 1). The dormant merge and the read-only box replay are
   authorized. Activation is not: it needs items 2-4 and 6-13.
2. **Owner approval of the §8 production impact** for the chosen mode.
3. **Box replay with real scarcity and Component B** (`scripts/forced_drop_fix_replay.py` on the box, both modes):
   every number here is at scarcity 1.0 with Component B in its not-applicable state. It must report the currency
   anomaly in BOTH directions (forward and reverse, §3a) — the reverse direction is structurally 0 at scarcity 1.0.
4. **UI copy (UI lane, not this PR).** `frontend/lib/trade-war-room-copy.js:793` renders
   "After the forced cut of X (worth N)" from `objectiveValue.forcedReleaseCost`. For a just-acquired release N is the
   package credit forgone, not the player's value, so "worth N" is false. The backend now publishes
   `objectiveValue.forcedReleaseChargeBasis` (and per-drop `chargeBasis`). Proposed copy:
   * `release_value` (unchanged): "After the forced cut of X (worth N), you …"
   * `package_credit_forgone`: "After releasing X, whom this trade sends you (the package credited him N), you …"
   * `mixed`: "After the forced cuts of X and Y (N of trade value given up), you …"
   * and when `forcedReleaseChargeState` is `assumed` / `mixed_bound`, append "(N is an upper estimate — X has no
     board value)"; `lower_bound`: "(at least N)".
5. Independent re-review of the review fixes (A–F) — performed by the reviewer, not the implementer.

**Added 2026-10-21 by the independent review of the V5-R default (both reviews agree V5-R and the dormant merge).**
Every item below also blocks activation:

6. **V5-R exact-tie behaviour.** ~~Ties between an existing and an incoming player on exactly equal `c` were broken by
   player id, which moved the charge by up to the incoming piece's depth discount (220 points in the reviewer's
   construction) for identical final rosters.~~ **FIXED in the follow-up PR.** Among cut sets with the minimum
   `sum c`, the lowest charge now wins (`Selection.tie_break`, published as `forcedDropSelection.tieBreak`). Against
   the old code, an id-relabelling property test failed on 26 of 60 seeds; it now passes on all 60. Activation still
   needs the box tie census (runbook §5a); a non-zero `player_id_search_bound` count must be explained.
7. **The cheap single-source tail.** In the stress variant, favourable census verdicts fall from 111 to 12 (V5) and
   from 103 to 9 (V5-R). The owner decides whether single-source values of 226-440 are real cut costs; until then
   class A is not established.
8. **Unpriced rostered players** (the 49-54 evidence-gate lifts). Either clean the roster feed of dead roster spots,
   or accept charging them the waiver ceiling. The box `unpricedRosterCensus` sizes the question.
9. **Non-monotonicity statement.** The activation note must say, in plain words, that "a depth sweetener can lower the
   displayed net by up to its depth discount when it displaces a rostered player worth more than its credit". The
   reviewer traced it to the credit-vs-full-value currency, not to selection: 313 of 3,000 synthetic trades under
   V5-R against 6 under V5. Fixing it would change the accounting (an owner decision), not the mode.
10. **Copy and backend publishes** (extends item 4). Never "worth" for a charge. The backend must publish
    `chargedInMarginal` per drop, so the sentence names only charged cuts. `chargeBasis` must stay distinct for
    uncredited and no-package releases, and `forcedReleaseChargeBasis` must be computed over charged drops only.
    Per-player numbers for released incoming players must not be shown: the sequential-removal split can exceed a
    piece's own value.
11. **V5-R production impact**, approved by the owner for V5-R specifically. The §8 tables are V5 headline numbers.
12. **Over-cap marginal-charge policy** (class D) accepted or rejected.
13. **Perfect Draft** stays a separate authorization (same selection flaw, untouched here).

## 11. UNRESOLVED

* The activation checklist (§10) — every item open; nothing is switched on.
* Perfect Draft exposure (§6): same selection mechanism, separate authorization.
* Optional follow-up: pass a package from Angle / Suggestions if their capacity blocks should net acquired releases.
* **Named follow-up (pre-existing, flag-OFF, needs its own authorization):** `src/draft/displacement.py::_waiver_value_for`
  returns 0 when the league has no waiver-level values, so an unpriced (`assumedWaiver`) cut is costed 0 on the
  incumbent trade path and on Perfect Draft / `/api/draft/roster-context` alike. Not changed here (flag-OFF byte
  identity). Under the flag the forced-drop charge refuses such a number instead (`forcedDropChargeBasis`
  `{state: "unknown", reason: "waiver_values_unavailable"}`, `forcedDropMarginal: null`). The War Room objective
  still treats any `null` charge as uncharged (pre-existing posture for `unknown`), so (review F7, flag-ON path only)
  the decision now raises the explicit evidence gap `forced_drop_charge_unavailable` — `evidence.reason` /
  `.state` from the charge basis — whenever a release is required (`requiresDrops` true) and the charge is `null`
  (skipped when `forced_drop_unpriced` already withholds the headline). The headline is withheld, never read as a
  free cut. No frontend mapping exists for the new code: the backend sentence is plain and is shown as-is
  (UI lane may word it). Pinned: `test_a_required_release_with_an_undeterminable_charge_is_an_evidence_gap_review_f7`.
