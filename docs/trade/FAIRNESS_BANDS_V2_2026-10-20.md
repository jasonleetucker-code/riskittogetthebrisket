# fairness_bands_v2 — implementation and measured impact (2026-10-20)

**Status:** evidence record for `fairness_bands_v2`. It is not authorization —
`docs/EXECUTION_PLAN.md` §0 authorizes. Owner decisions, verbatim:
[`docs/owner/FAIRNESS_V2_DECISIONS_2026-10-20.md`](../owner/FAIRNESS_V2_DECISIONS_2026-10-20.md).

- Raw numbers: [`fairness-bands-v2-impact/results.json`](fairness-bands-v2-impact/results.json).
- Produced by `scripts/measure_fairness_band_change.py --compare v1-v2` (with
  `scripts/measure_fairness_band_meter.mjs` for the /trade meter).

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

---

## 1. What changed

| | v1 (retired) | v2 (active) |
|---|---|---|
| version / status | `fairness_bands_v1` / `PROVISIONAL` | `fairness_bands_v2` / `PRIOR_OWNER_APPROVED_2026-10-20` |
| relative base (denominator) | larger **adjusted** side, `max(sendAdj, recvAdj)` | larger **package utility**, `max(U_A, U_B)` (OD-F2) |
| gap (numerator) | `recvAdj − sendAdj` | unchanged |
| floor | 250 | 250, recorded as an owner-approved prior (OD-F3) |
| cut points | 3.5 / 9 / 18 % | unchanged |
| FAIR TRADE (binary answer) | not defined in the owner | `fairTradeLevels: ["fair"]` (OD-F1) |
| non-finite input | JS → `fair`, Python → `lopsided` on `NaN` | refused in both languages (`FairnessInputError`, code `fairness_input_not_finite`) |
| validation | none | OD-F4 post-launch, recorded as `postLaunchValidation` (`PENDING`) |

Under `geom_q078_v1` the adjusted gap already equals `U_R − U_G`. v1 divided
that utility gap by the larger adjusted side, which equals
`max(U) + max(discarded depth)`. So the effective fair band widened with piece
count. v2 divides by `max(U)`, so both numerator and denominator are on the
utility scale.

A **1-for-1 is byte-identical**: `U = v =` the adjusted total. This is pinned
over a grid in both languages, including 1-for-0.

Under the rollback package model (`ktc_2026_04`) there is no per-package
utility, so the pair's adjusted totals stand in. That is exactly the v1 basis.

### Where the denominator is decided (one owner)

- **Python.** `fairness_bands.package_utilities` / `larger_package_utility` /
  `fairness_base` / `classify_packages`.
  - The market lens (`analyze_trade.equity_verdict`) takes the base from the
    owner and publishes `largerPackageUtility`.
  - The private decision's Component A (`trade_decision._objective_value`)
    re-classifies the net gap on that same base. It no longer reads the
    larger adjusted side.
  - `_a_from_values` (what would change), the suggestions badge and the
    equalizer, and the decision-engine term A all call the owner.
  - Best Offers and the Package Builder consume `equity_verdict`.
- **JS.** `fairness-bands.js::fairnessBase` runs over per-side utilities from
  `trade-logic.js::packageUtilities`, which is the package-model twin. The
  utilities are stamped as `utility` on `adjustedSideTotals`,
  `multiAdjustedSideTotals` and `computeSideFlows`.
  - The /trade meter, sticky tray, balancers (`tradeImbalance.largerUtility`),
    the 3+-team summary, the fairness explanation and the VA comparison all
    read `sideTotalsFairnessBase` / `fairnessBase`.
- **Structural guard.** `tests/valuation_math/test_fairness_bands.py::OneDenominatorOwner`
  fails if any `src/` or frontend call passes a band classifier a base built
  from `max(...)`, `adjusted` or `given`. A positive control proves the guard
  can fire.

**Not changed:**

- `package_model`, q, `geom_q078_v1`, curves and values.
- The League Hub trade-history grade (OD-F6 is still open).
- Every flag.

## 2. Inputs (pinned)

| input | git rev | blob |
|---|---|---|
| `exports/latest/dynasty_data_2026-10-20.json` (board) | `1511ca1d08` (the research memo's baseline) | `0d0e0d862d0b269f2a9292a786122517ce7fb47e` |
| `data/sleeper_last_good.json` (own-league trades) | `1511ca1d08` | `91ff7203c13707da81f163858a71627e1a68ccba` |

The board is rebuilt with `build_api_data_contract` by the code on this branch.
v1 is emulated by swapping only the denominator
(`fairness_bands.larger_package_utility` → max adjusted). That is the one
function every consumer reads its base through. Cut points, floor, gap and the
package model are identical in both runs.

## 3. (a) Real own-league trades — 76 fully priced trades, 153 per-team results

31 trades are excluded because an asset is unpriced, off-board or ambiguous.
They are never priced as 0.

| set | team results | band changed | transitions | Asset-Only headline changed |
|---|---:|---:|---|---|
| all | 153 | **16 (all stricter)** | fair→slight 2, slight→unfair 8, unfair→lopsided 6 | **2** (NO_TOO_CLOSE→YES 1, NO_TOO_CLOSE→NO 1) |
| 1-for-1 | 32 | 0 | — | 0 |
| deep (≥ 4 pieces on a side) | 34 | 12 | fair→slight 2, slight→unfair 6, unfair→lopsided 4 | 2 |
| includes picks | 75 | 12 | fair→slight 2, slight→unfair 4, unfair→lopsided 6 | 2 |
| includes IDP | 39 | 8 | slight→unfair 6, unfair→lopsided 2 | 0 |
| multi-team (3 teams) | 3 | 0 | — | 0 |

- **Trades FAIR for every team:** 15 under v1, 14 under v2.
- **No result became more lenient.**

Examples (the full list is in `results.json` → `realTrades.examples`):

| date | team | shape | gap | v1 base → v2 base | v1 → v2 | Asset-Only |
|---|---|---|---:|---|---|---|
| 2025-10-23 | Jason / Joey | 2>4 / 4>2 | ±430 | 13,435 → 10,303 | fair 3.20% → slight 4.17% | NO_TOO_CLOSE → YES / NO |
| 2026-08-12 | Jason / Roy | 9>5 / 5>9 | ∓2,968 | 39,838 → 18,744 | slight 7.45% → unfair 15.83% | unchanged (NO / YES) |
| 2026-07-31 | Ed / Jason | 5>2 / 2>5 | ∓788 | 10,803 → 7,855 | slight 7.29% → unfair 10.03% | unchanged |
| 2026-09-23 | Ed / Jason | 2>3 / 3>2 | ±575 | 7,172 → 6,024 | slight 8.02% → unfair 9.54% | unchanged |

**Reconciliation with the research memo's counterfactual** (18 changes, 4 of
them fair→slight):

- This run finds **16** changes, **2** of them fair→slight. The trades and the
  pinned board are the same.
- The memo's numbers came from that commit's code and used `U_R − U_G` as the
  numerator. This run uses the shipped gap (`recvAdj − sendAdj`, which is
  integer-rounded) and this branch's board build.
- The direction is the same in both: every change is stricter and 1-for-1 is
  untouched.

## 4. (b) Synthetic grid — SYNTHETIC, seeded (`20261020`)

| set | judged | band changed | transitions | Asset-Only headline changed |
|---|---:|---:|---|---|
| 1-for-1 grid (8 sizes × 12 gaps) | 96 | **0** | — | 0 |
| stud vs k equal pieces (k 2–12, ±0–18% utility shortfall) | 252 | 66 | fair→slight 18, slight→unfair 38, unfair→lopsided 9, slight→lopsided 1 | 18 (NO_TOO_CLOSE→YES 10, →NO 8) |
| board draws, offense (shapes 1v2 … 3v8, near-balanced) | 480 | 28 | fair→slight 5, slight→unfair 8, unfair→lopsided 15 | 5 |
| board draws, IDP | 480 | 29 | fair→slight 1, slight→unfair 4, unfair→lopsided 24 | 1 |
| board draws, mixed offense + IDP + picks | 480 | 29 | fair→slight 4, slight→unfair 11, unfair→lopsided 14 | 4 |
| picks R4–R6 (1v1 … 2v3) | 300 | 18 | slight→unfair 4, unfair→lopsided 14 | 0 |

Every change is stricter, and none is looser.

Examples:

- `[3000]` for `[1407 ×3]`: slight 8.54% → unfair 10.73%.
- `[1644, 5895]` for `[552, 6493]`: fair 3.37% → slight 3.54% (NO — TOO CLOSE → NO).
- picks R4–R6 `[1798]` for `[1117, 1373]`: unfair 17.91% → lopsided 19.87%.

The fixed-shortfall property is pinned by test: a stud against k pieces with
the same utility shortfall now reads the **same level at every k**.

## 5. (c) Live consumers on the same pinned inputs

| consumer | how measured | v1 → v2 |
|---|---|---|
| **Private Asset-Only YES / NO** | real `analyze_trade` → `trade_decision.decide`, Team Context off | real trades: **2 of 153** team results change (both NO — TOO CLOSE → YES/NO, on one 2-for-4 trade); synthetic: 28 of 2,088 (all from NO — TOO CLOSE) |
| **/trade meter** | the frontend library itself under node (`adjustedSideTotals` + `classifyGap`) | real 2-team: **8 of 75** (fair→slight 1, slight→unfair 4, unfair→lopsided 3); synthetic sets match §4 exactly; **JS v2 level = Python v2 level on all 2,163 pairs (0 mismatches)** |
| **Best Offers** (12 teams × 11 opponents, Asset-Only) | existing harness, OLD = v1 base | final cards: **132 of 132 unchanged**. Candidate canonical-win rule: 2,672 candidates newly "win" (all consolidations; a stricter fair band makes a 3.2–3.5% gain a SLIGHT win, `win` = gain ∧ not fair); 0 lost. Qualification: 46,250 qualified under both, 0 added, 0 dropped, 0 ranking changes |
| **Package Builder** (each team's top 3 outgoing) | existing harness | final packages: **378 kept, 3 added, 4 dropped**. 191 candidates no longer accepted: v1 FAIR, now SLIGHT against the seller (3.14–3.50% of v1 base), all consolidations, 82 with IDP |
| **Suggestions badge** | existing harness | 34 suggestions kept (8 change rank), 9 added, 8 dropped; badges relabelled lean→stretch on 4 |

The 3+-team /trade meter base is now the largest utility any side sends
(previously the largest `given`). It was not measured on real data: only 1
priceable 3-team trade exists. The meter's 3+-team path is also being replaced
by the N-team engine (#1882).

## 6. (d) League Hub trade-history grade vs v2 FAIR (OD-F6 input — not changed)

The history grade is "Fair trade" below 3.0% of the larger effective side, with
no floor. It is compared on the same 153 team results:

| | agree | disagree |
|---|---:|---|
| vs v1 `fair` | 145 | **8** |
| vs v2 `fair` | 147 | **6** — all 6 are history "not Fair trade" while v2 says FAIR (the 250 floor and the 3.0 vs 3.5% cut) |

The research memo counted 12 disagreements under v1. That count came from the
same pinned inputs but its own code's board build; see the §3 reconciliation.

v2 removes 2 disagreements and adds none. The remaining 6 are the floor and
cut-point mismatch, which only OD-F6 can resolve: align the grade or relabel
it.

## 7. Tests

- `tests/valuation_math/test_fairness_bands.py` covers:
  - the shared cases on the utility base, including deep packages, picks R4–R6
    and IDP;
  - the 1-for-1 byte-identical grid;
  - the depth-bias-removed property;
  - the shared refusal fixture;
  - JS constant parity;
  - the one-denominator structural scan with a positive control;
  - the KTC rollback stand-in;
  - provenance: version, status, OD keys, OD-F4, retired v1, and the floor
    being absent from the code as a literal.
- `frontend/__tests__/fairness-bands.test.js` covers the same shared fixtures,
  checks that the base comes from the package layer (`adjustedSideTotals` /
  `tradeImbalance` / `computeSideFlows`), and runs the 1-for-1 grid, the
  refusal cases and OD-F1.
- `tests/fixtures/fairness_band_cases.json` was regenerated by an independent
  implementation of the stated formula. It keeps `v1Level` per case.
  `tests/fixtures/fairness_band_refusal_cases.json` is new.
- Regenerated fixtures: `tests/fixtures/decision_engine/*.json` and
  `frontend/__tests__/fixtures/trade-war-room/*.json`. Only the band receipts,
  `relativePct`, `largerPackageUtility` and the "what would change" amounts
  move. No headline changes.

## 8. Unresolved

- **OD-F4.** v2 is an owner-approved prior, not a validated threshold. Its
  validation needs the box-local market-trade ledger and the temporal ledger,
  and neither is available here.
- **OD-F6.** 6 history-grade disagreements remain.
- **Refusal behaviour in the UI.** A non-finite value reaching a band
  classifier now throws instead of reading `fair`. No live producer is known
  to emit one:
  - the /trade page and meter read side totals through `|| 0`;
  - package utilities are always finite (non-positive and `NaN` pieces are
    dropped);
  - asset values arrive from the contract as numbers, and user overrides are
    parsed as finite;
  - Python filters unpriced assets before the package math.
  A non-numeric value string in a contract row is the one remaining way to
  reach the throw in the balancer path, and the throw surfaces it instead of
  calling it fair.
- **Public advisor (#1861).** It must read `fairTradeLevels` /
  `counts_as_fair_trade` from the owner. It is on an unmerged branch and was
  not touched here.
