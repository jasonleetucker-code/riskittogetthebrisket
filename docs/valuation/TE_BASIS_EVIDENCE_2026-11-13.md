# TE basis for a league with no TE reception premium: measured evidence

**Date:** 2026-11-13. **Status:** research only. Nothing here changes a served value, weight, flag or config.
**Decision it serves:** `docs/owner/DECISION_BRIEFS_2026-11-08.md` brief 6 (MD-113), ADR-015 in `docs/league-intelligence/DECISIONS.md`.
**Reproduce:** `python scripts/research/te_basis_pick_market_evidence.py te --out docs/valuation/evidence/te-basis-2026-11-13/evidence.json`
(network refused, every counterfactual restored after its build). Evidence: `docs/valuation/evidence/te-basis-2026-11-13/evidence.json`.
**Input:** `exports/latest/dynasty_data_2026-11-13.json`, sha256 `57c2d2d4...b177a3`, scrape `2026-11-13T07:22Z`, contract rebuilt from today's `CSVs/site_raw`.
This is a rebuild of the board from current inputs, not a comparison against the served production contract (not fetched).

## Four names that are kept apart

| quantity | what it is | where it lives |
|---|---|---|
| starter scarcity | how many TEs a league must start | the league's lineup demand (`src/ros/lineup.py`), a `leagueKey` property |
| scoring premium | points a TE earns per reception beyond a WR | the scoring card, `bonus_rec_te`; `dynasty_main` reads 0.0 |
| market value | what a provider's board prices a TE at | each source, including KTC's TE++ boards |
| team utility | what a TE adds to one roster's lineup | roster-specific, not measured here |

ADR-015's conversion is none of these directly. It is a **basis alignment**: it lifts non-TEP providers' TE votes onto the TE++ basis the
board is anchored on (KTC's own measured base-to-TE++ uplift). The justification in the ADR is structural (two mandatory TE starters), not
scoring. The measurements below keep that distinction.

## 1. What the conversion touches today

| measure | value |
|---|---|
| TE rows on the board | 86 (83 carry a converted vote) |
| converted votes (non-TEP providers, base to TE++) | 546, from 9 sources (pfkDynasty 80, otcffbSf 77, fantasyProsSf 81, fantasyCalc 65, flockFantasySf 65, dynastyDaddySf 64, idpShowCombined 62, dlfSf 42, dlfRookieSf 10) |
| TEP-native votes on the flat 1.10 | 310 votes on 83 rows (not curve-converted) |
| KTC TE++ votes exempt from any TE transform | 158 |
| per-vote lift | min 1.070, p10 1.218, median 1.392, p90 1.523, max 1.596 |

The audit's earlier count (82 rows, 479 votes) was from a different board date; today's inputs give 83 and 546. The stamped per-vote lift
(post `_te_lift_under_ceiling`) spans 1.07 to 1.60, not the ADR's 1.21 to 2.05; the cause was not isolated (the vote values here are Hill-curve contributions, not raw board values).

## 2. Value and rank effect versus no conversion

Four builds from identical inputs:

- `incumbent_adr015`: production default.
- `flat_1_15_pre_adr015`: the retired flat 1.15 (explicit override).
- `no_non_tep_lift`: non-TEP providers unlifted; TEP-native boards keep 1.10.
- `no_te_lift_any_source`: no lift for any non-KTC source.

KTC's TE++ boards stay exempt in all four, so **no variant is a no-premium board**: the KTC Crowd and Trades votes and the KTC Market benchmark still carry KTC's TE++ premium.

| versus incumbent | TE value change, median (min..max) | TE rows changed | TE rank displacement median / p90 / max | pick rows moved (rookie tether) | non-TE offense rows moved |
|---|---|---|---|---|---|
| flat 1.15 | -12.2% (-24.1..0) | 83 | 56 / 161 / 229 | 46 | 0 |
| no non-TEP lift | -20.9% (-34.0..0) | 83 | 102 / 234 / 277 | 59 | 0 |
| no lift, any source | -23.0% (-34.0..-7.3) | 86 | 121 / 241 / 262 | 64 | 0 |

TEs inside the overall rank cutoffs (rank by `canonicalConsensusRank`):

| variant | top 50 | top 100 | top 250 |
|---|---|---|---|
| incumbent | 6 | 12 | 31 |
| flat 1.15 | 5 | 11 | 27 |
| no non-TEP lift | 4 | 10 | 24 |
| no lift, any source | 4 | 9 | 23 |

TE share of summed board value over the rank-250 offense population: incumbent 16.5%, flat 14.7%, no non-TEP lift 12.8%, no lift 12.2%.
The effect is confined to TEs and the current-year slot picks that tether to rookie TEs; no QB, RB or WR row moves by 1 value point.

## 3. TE edge signal (BUY / SELL), rank <= 250, 5% gate

| variant | SELL | BUY | HOLD |
|---|---|---|---|
| incumbent | 18 | 1 | 12 |
| flat 1.15 | 22 | 0 | 5 |
| no non-TEP lift | 23 | 0 | 1 |
| no lift, any source | 23 | 0 | 0 |

The skew toward SELL is **not** produced by the conversion; the conversion reduces it (23 to 18). The reference is KTC Market
(`ktcCrowdTradesSfTep`), which is itself a TE++ board. Removing lift lowers our TE values against a market that still carries the premium, so the
gap widens. The edge signal compares a basis-aligned board to a TE++ benchmark; making the signal league-honest is a benchmark-basis question,
and removing the conversion would worsen the apparent SELL skew, not cure it. The earlier audit's 22 SELL to 1 BUY was on another board
date and is not reproduced exactly here (18 / 1 / 12).

## 4. Starter demand versus board value (resolved through `resolve_league_slot_demand`)

Demand for `dynasty_main` (12 teams): dedicated slots QB 1, RB 2, WR 3, TE 2; with flexes allocated, TE is 2.92 under an even split and 2.0
under whole-slot flex priority. For `dynasty_new` (10 teams): TE 1 dedicated, 1.58 even split, 1.0 flex priority. These are approximations,
named as such; the measured endogenous demand (`league_intel/replacement.measure_endogenous_starters`) needs live rosters and was **not** run.

TE share of offense starter-pool demand against its share of starter-pool value (pool per position = teams x demand, top values at that position):

| league | demand basis | TE demand share | TE value share, incumbent | TE value share, no lift |
|---|---|---|---|---|
| dynasty_main | dedicated | 25.0% | 20.6% | 18.1% |
| dynasty_main | even split | 26.5% | 21.3% | 18.4% |
| dynasty_main | flex priority | 18.2% | 16.5% | 14.4% |
| dynasty_new | dedicated | 14.3% | 14.3% | 12.7% |
| dynasty_new | even split | 15.8% | 15.4% | 13.6% |
| dynasty_new | flex priority | 10.0% | 11.3% | 10.0% |

Reading: for the league with two mandatory TEs, TE value is already **below** its demand share on every basis, and removing the lift widens
the shortfall. For the one-TE league on the same scoring profile the incumbent sits near demand and a one-TE-league overlay would remove a
small part of the lift, not most of it. Value share against demand share is a descriptive screen, not a calibrated test: value is concave in rank,
so equal shares do not mean equal scarcity.

Value at each position's own replacement rank (teams x dedicated slots), incumbent versus no-lift: `dynasty_main` TE24 2964 vs 2353, against RB24 3988 and
WR36 3640; `dynasty_new` TE10 4625 vs 3887, against RB20 4224 and WR30 4118. At replacement, a `dynasty_main` TE is already priced below
RB and WR under the incumbent.

## 5. What a league-aware TE overlay would need

Constraint (CLAUDE.md, ADR-015): the board is scoring-profile scoped and shared; both leagues carry `superflex_tep15_ppr1`
while `dynasty_main` starts two TEs and `dynasty_new` one. So the shared basis cannot follow either league. An overlay must:

1. Live under `leagueKey`, in the existing league-scoped overlay (`src/league_intel/publish.py`, where `tePremium` is a named inactive axis), writing
   `experimental*` fields only and never a canonical field (`LEAGUE_AWARE_METHODOLOGY_REJECTION.md`).
2. Name its axis. Scoring premium comes from the scoring card (fresh `bonus_rec_te`, `scoring_fingerprint`); it is 0.0 for both leagues, so
   it contributes nothing today. Starter scarcity comes from measured endogenous demand. They are separate fields.
3. Not double count. The market already prices positional scarcity for most boards, and replacement level (BDVM, Perfect Draft) already charges it.
   An overlay must net against both: the shared conversion's embedded lift, and any replacement-level surplus a consumer subtracts later.
   ADR-009 requires the netting; this evidence shows its size is about -20% to -23% of TE value for a full removal, which is the quantity to net against.
4. Carry a validation target before activation: nothing here shows which basis predicts TE outcomes. The KTC curve is measured within KTC only
   (`_limitation` in `config/weights/te_premium_curve.json`), and no independent TE outcome target is registered.
5. Fail closed on unproven scoring identity, and say per league which basis it targets.

## 6. Unverified or not measured

- Served-production parity: the rebuild uses today's repo inputs; the live served board was not compared.
- Measured endogenous starter demand (needs live rosters); only the three declared approximations above.
- The overlay's effect on trades, FAAB and Perfect Draft consumers: not run.
- Whether KTC's TE++ premium itself fits a no-premium league: nothing validates it.
- A predictive test that any TE basis is better.

## Options and recommendation (owner decision, brief 6)

- **(a) Keep the shared TE++ board.** No change; the known mismatch for `dynasty_main`'s zero `bonus_rec_te` remains, but the structural two-TE
  demand supports TE++ and the demand table shows TE is not over-weighted against it.
- **(b) Keep the shared board and add a named league-specific TE overlay**, experimental only, validated before it may reach any consumer.
- **(c) Change the shared basis.** Reprices every TE on every surface (median -12% to -23% for TEs here, rank displacement median 56 to 121) and 46 to 64 slot picks via the tether.
- **Recommendation: (a) now, with (b) as the follow-up design.** This evidence does not support (c), and the demand comparison does not show an overpriced TE for the
  two-TE league. If the owner wants the mismatch addressed, authorize (b) in two named parts: a scoring-premium axis (inert today) and a starter-scarcity axis from
  measured demand, each with a registered outcome target. Separately consider basis-matching the TE edge benchmark, since that signal's SELL skew comes from a TE++ market, not
  from our conversion. Methodology authorization is the owner's; this document authorizes nothing.
