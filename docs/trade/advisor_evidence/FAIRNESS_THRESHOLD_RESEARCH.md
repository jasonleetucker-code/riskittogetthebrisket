# Public fairness threshold: research memo (owner amendment 2026-10-20)

**Status:** research only. Nothing in the repository was changed. No threshold, band, package
model, q or player value was altered.

- Baseline: `origin/main` @ `1511ca1d08`, in a sparse throwaway worktree
  (`scratchpad/tam/wt-fair`).
- Scripts (read-only, in the scratchpad):
  - `scratchpad/tam/fair_scripts/fairness_research.py`
  - `scratchpad/tam/fair_scripts/mt_rate.py`
  - `scratchpad/tam/fair_scripts/noise.py`
- Raw output:
  - `scratchpad/tam/fair_out/fairness_research.json`
  - `scratchpad/tam/fair_out/mt_rate.json`
  - `scratchpad/tam/fair_out/noise.json`

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

---

## 0. Answer

**The existing threshold should not be adopted as the public, fixed, versioned FAIR / NOT FAIR
threshold as it stands.** The band owner is the right owner, and it already gives a correct
per-team multi-team test. Its numbers and its basis have not been validated, and on real data
they fail three properties a neutral "is this trade fair?" answer needs:

1. **It does not behave the same at every value level.** Fair means a gap under 250 points or
   under 3.5%, whichever is more forgiving.
   - The 250-point floor is what actually decides almost every trade: **97.5% of priced assets**
     are worth less than 7,143, the level where 250 points and 3.5% are equal.
   - A 1-for-1 between two low-value assets stays FAIR up to a **25% gap at 1,000** and a
     **50% gap at 500**. At 9,999 the limit is 3.5%.
   - Below a larger side of 1,389 (30% of assets) the label goes straight from FAIR to
     LOPSIDED.
2. **It favours deep packages.** The gap being measured is in package-utility units, but the
   number it is divided by is the larger *adjusted* side. That side equals
   `max(U) + max(depth discarded)`, so it adds back the depth the package model removed.
   - The effective tolerance therefore grows with piece count: ×1.00 for a 1-for-1, about ×1.36
     at 4 pieces, ×2.13 on a real 9-for-5 trade and ×2.73 at 12 pieces.
   - A stud-for-12 trade that falls 8% short in utility reads FAIR at every stud size tested.
3. **It is officially unvalidated.** `config/trade/fairness_bands.json` says `"status":
   "PROVISIONAL"` and "every number is a PRIOR until validated against a defined target". The
   TC-C workstream records "Validation status: NOT validated, still PROVISIONAL".
   - It lists what is missing: a defined target, a fit with a holdout, more than one board date,
     and Team Context runs.
   - The amendment forbids silently inheriting an unsuitable provisional threshold.

On top of these:

- The League Hub already shows a **second, contradictory "fair" concept**. Trade-history grades
  say "Fair trade" below 3.0%, with no absolute floor. On real trades they disagree with the band
  on 12 of 153 team results.
- The amendment's "all teams fair" rule makes FAIR strictly harder to reach as the team count
  rises. That is the owner's intended semantics, and it should be stated in the public copy.

**What is needed is an owner decision (§8), not an engineering change.** That decision covers:

- which level counts as FAIR TRADE;
- the basis of the denominator;
- the absolute floor;
- the validation target;
- the version id to publish.

Because the private Asset-Only YES / NO also reads the same `fair` level, any change to the shared
owner changes private decisions too. It must be re-measured on every consumer.

---

## 1. The authoritative owner and its provenance

| item | value | where |
|---|---|---|
| Owner | `fairness_bands.classify(gap, larger_side)` | `src/valuation_math/fairness_bands.py:78-104` |
| Config | `fairness_bands_v1`, **PROVISIONAL**, basis `adjusted_package_totals`, absoluteMinimum 250, slight 3.5%, unfair 9%, lopsided 18% | `config/trade/fairness_bands.json` |
| JS mirror | `classifyGap`, constants pinned by test | `frontend/lib/fairness-bands.js`, `tests/valuation_math/test_fairness_bands.py` |
| Rule | fair if \|gap\| < 250 **or** rel < 3.5%; slight if rel < 9%; unfair if rel < 18%; otherwise lopsided. Here rel = \|gap\| / larger ADJUSTED side × 100 | same |
| Gap producer | `equity_verdict` builds `adjusted_pair_totals(sending, receiving)`, then gap = recv_adj − send_adj, base = max(send_adj, recv_adj) | `src/trade/analyze_trade.py:160-193` |
| Decision use | `_objective_value` passes the net gap (minus forced-release cost, Team Context only) to `classify`. In Asset-Only mode `_rule` gives `fair` → NO_TOO_CLOSE, favours → YES, opposes → NO | `src/trade/trade_decision.py:437-473`, `:503-512` |
| Package model | `geom_q078_v1` (ACTIVE), q = 0.78. Under geom, recv_adj − send_adj = U(R) − U(G) | `config/trade/package_model.json`, `src/valuation_math/package_model.py:153-220` |
| Decision record | TC-C owner decision 3 (2026-10-18): "relative difference with an absolute minimum, validated on offense, IDP, picks, consolidation and large packages; numbers provisional until tested" | `docs/OWNER_REQUESTED_TODO.md:1885` |
| Derivation | The KTC-era absolute meter bands 350 / 900 / 1800, divided by a 10,000-point "typical one-star package" to give 3.5% / 9% / 18%. The 250 floor is "the tighter of the two even bands the repo already used (market lens 256, meter 350), rounded" | JSON `_comment` |
| Validation status | "NOT validated, still PROVISIONAL … no validation target exists yet to fit them against" | `docs/trade/TRADE_CALCULATOR_COMPLETION_WORKSTREAM.md` (TC-C §"Fairness-band impact") |
| Prior impact work | `scripts/measure_fairness_band_change.py` measured how much **changed** (old absolute bands vs new) on Best Offers, the Package Builder and suggestions. It does **not** measure suitability against any target | `docs/trade/tc-c-fairness-band-impact/results.json` |

So the threshold is a **declared PRIOR**. It was derived by rescaling KTC-era absolute bands and
has never been calibrated. The 250 floor and the 10,000-point anchor both carry KTC-model history.
The cut points were never re-fit for `geom_q078_v1`.

Other fairness concepts that the public product touches:

- **League Hub trade-history grades.**
  - Owner: `src/public_league/trade_grading.py:54-90`, mirrored in
    `frontend/lib/league-analysis.js::gradeTradeHistorySide`.
  - Rule: "Fair trade" when pct < 3.0, slight at 8%, good at 15%, clear at 25%, robbery at 40%.
  - It has **no absolute floor** and is also a PRIOR ("owner recalibration pending").
  - It uses the same denominator, the larger effective side. It is a separate threshold for the
    same English word "fair", on the same public hub.
- **Second Opinions "even".** Within 1% of the larger adjusted side (TC-C decision 4). Private
  surface only.

---

## 2. Data used and what each can and cannot prove

| data | what it is | label |
|---|---|---|
| Frozen board | Canonical board rebuilt with `build_api_data_contract` from `exports/latest/dynasty_data_2026-10-20.json`: 1,107 rows, 1,003 priced (486 offense, 397 IDP, 120 picks), `currentDraftYear` 2027 | REAL board, current code |
| Own-league completed trades | `data/sleeper_last_good.json`: 107 trades from 2025-10-20 to 2026-10-18 (104 two-team, 3 three-team) | REAL trades |
| Pricing (a): structure study | Each trade priced on the frozen 2026-10-20 board. Players by unique normalized name; picks by `resolve_pick_label_value`. 76 of 107 fully priced; 31 excluded because an asset was off the board, unpriced or ambiguous, never priced as 0 | REAL shapes and current values. **Not** an at-time grade |
| Pricing (b): at-time | Each trade priced from the vendor CSV in the `exports/archive/` zip strictly before the trade, at most 7 days earlier. These are observed numbers on the same 0–9999 scale. IDP Trade Calculator: 24 graded; KTC SF TE++: 16 graded. 67 trades predate the archive (2026-07-14) | REAL, point in time, **vendor** values (not canonical) |
| Synthetic grids | 1-for-1 grid; stud-vs-k-pieces depth grid; random packages drawn from the real board values; random multi-team circles | **SYNTHETIC**, labelled as such |
| Market-trade ledger (Sharp / KTC trade groups) | `data/intel` is box-local. The only copy in this container (`rit-ctm-maturity/data/intel/ledger.sqlite3`) has 0 transactions | **UNAVAILABLE**. Named gap |
| As-of canonical boards | The temporal ledger (`data/temporal_ledger.sqlite`) is not present. Rebuilding old boards would mix today's `CSVs/site_raw` and freshness clock with old payloads, so it was **not done** (CLAUDE.md: never re-derive an old value with today's curve and present it as observed) | **UNAVAILABLE** |

Completed trades are not a fairness target. Both managers accepted them for reasons that include
roster context. They are used here only to show how the band behaves on real shapes and value
levels.

---

## 3. Scale: relative vs absolute gap at low values

### 3a. Derived breakpoints of the current rule (exact)

| larger side L | fair limit | SLIGHT reachable? | UNFAIR reachable? |
|---|---|---|---|
| L < 1,389 | 250 pts (> 18% of L) | no | no. FAIR jumps straight to LOPSIDED |
| 1,389 ≤ L < 2,778 | 250 pts (9–18% of L) | no | yes. FAIR jumps to UNFAIR |
| 2,778 ≤ L < 7,143 | 250 pts (3.5–9% of L) | yes | yes |
| L ≥ 7,143 | 3.5% of L | yes | yes |

### 3b. How much of the board sits in each regime (frozen board, priced rows)

| class | n | median value | p90 | share < 7,143 (floor decides) | share < 2,778 (no SLIGHT) | share < 1,389 (FAIR→LOPSIDED) |
|---|---:|---:|---:|---:|---:|---:|
| offense | 486 | 1,832 | 5,439 | 95.1% | 71.2% | 28.0% |
| IDP | 397 | 1,479 | 2,831 | **100%** | 89.2% | 40.3% |
| picks | 120 | 2,138 | 4,587 | 99.2% | 68.3% | 6.7% |
| all | 1,003 | | | **97.5%** | 78.0% | 30.3% |

Only **25 assets** on the whole board are worth 7,143 or more. For a 1-for-1, the "3.5%
relative band" is therefore in practice a 250-point absolute band for everything outside the top 25.

### 3c. Synthetic 1-for-1 grid: level by larger side and gap

| L \ gap | 3% | 5% | 8% | 10% | 15% | 20% | 25% | 40% | first non-fair gap |
|---|---|---|---|---|---|---|---|---|---|
| 500 | fair | fair | fair | fair | fair | fair | fair | fair | 250 pts = **50%** → lopsided |
| 1,000 | fair | fair | fair | fair | fair | fair | lopsided | lopsided | 250 = **25%** → lopsided |
| 2,000 | fair | fair | fair | fair | unfair | lopsided | lopsided | lopsided | 250 = 12.5% → unfair |
| 3,000 | fair | fair | fair | unfair | unfair | lopsided | lopsided | lopsided | 250 = 8.3% → slight |
| 5,000 | fair | slight | slight | unfair | unfair | lopsided | lopsided | lopsided | 250 = 5.0% → slight |
| 9,999 | fair | slight | slight | unfair | unfair | lopsided | lopsided | lopsided | 350 = 3.5% → slight |

### 3d. Real examples on the frozen board (1-for-1, canonical values)

| gave | got | gap | rel | level |
|---|---|---:|---:|---|
| Brock Bowers 9,985 | Jahmyr Gibbs 9,864 | −121 | 1.2% | fair |
| Drake Maye 8,524 | Ashton Jeanty 8,041 | −483 | 5.7% | **slight** |
| Ollie Gordon 2,698 | Romeo Doubs 2,546 | −152 | 5.6% | **fair** |
| Javon Baker 984 | Tyrell Shavers 870 | −114 | 11.6% | **fair** |

The same 5.6% gap is SLIGHT at the top of the board and FAIR in the middle, and an 11.6% gap at
the bottom is FAIR. **Scale invariance holds only above 7,143**, and the fixture's "scale
invariance above the minimum" test is consistent with that.

### 3e. Real accepted trades at the time (vendor values)

- IDP Trade Calculator, 1-for-1: a trade at L = 1,305 with a **16.1%** gap reads **FAIR**. A
  trade at L = 2,767 with a **10.3%** gap reads **UNFAIR**.
- KTC SF TE++: a 1-for-1 at L = 2,721 with an 8.9% gap reads FAIR.

### 3f. Is the 250 floor explained by value noise?

A proxy check, `noise.py`: the weekly absolute movement of observed vendor values over 14
archive pairs about 7 days apart.

| value bucket | KTC SF TE++ median / p90 weekly move | IDPTC median / p90 |
|---|---|---|
| < 1,500 | 33 / 109 pts | 0 / 17 |
| 1,500–3,000 | 41 / 126 | 0 / 37 |
| 3,000–6,000 | 52 / 208 | 0 / 66 |
| ≥ 6,000 | 60 / 253 | 0 / 111 |

- At low values the 250 floor is about **2.3× the p90 weekly move**, so measured value churn does
  not justify it.
- IDPTC's near-zero movement is its known staleness, not stability.
- This is a proxy. It is vendor data, not canonical board history, which is not available here.

### 3g. Synthetic draws from the real board

Effective FAIR tolerance, expressed as % of the larger package utility, by value level (median
over 400 near-balanced draws each):

| shape | low (< 2,000) | mid (2,000–5,000) | high (≥ 5,000) |
|---|---:|---:|---:|
| 1v1 | **16.6%** | 9.4% | 4.5% |
| 1v2 | 14.2% | 8.5% | 4.4% |
| 2v2 | 8.5% | 6.0% | 3.8% |
| 2v3 | 6.6% | 5.5% | 4.0% |
| 3v3 | 5.5% | 4.4% | 4.0% |

A 4–6% utility gap reads FAIR **100%** of the time in low-value 1v1s and **18%** in high-value
1v1s.

---

## 4. Package size (depth) bias

### 4a. The mechanism (exact algebra under geom)

The geom display gives the side that discarded less depth `|D_A − D_B|`, where `D = raw − U`.
As a result **both** adjusted totals equal `U_side + max(D_A, D_B)`. The band's denominator is
therefore `max(U_A, U_B) + max(D_A, D_B)`, while the numerator is `U_R − U_G`.

The numerator is on the utility scale and the denominator is on the raw scale. The effective
tolerance, measured in utility, is `3.5% × inflation`, where `inflation = larger_adjusted /
max(U)`.

### 4b. Synthetic: stud vs k equal pieces with a fixed utility shortfall x

Inflation and the band's relative % do not depend on stud size (homogeneity). The level does,
through the floor.

| k pieces | inflation | band rel % at x = 3% | x = 5% | x = 8% | level at x = 8% (stud 9,000) |
|---:|---:|---:|---:|---:|---|
| 1 | 1.00 | 3.0 | 5.0 | 8.0 | slight |
| 2 | 1.12 | 2.7 | 4.5 | 7.2 | slight |
| 4 | 1.38 | 2.2 | 3.6 | 5.9 | slight |
| 6 | 1.65–1.68 | 1.8 | 3.0 | 4.9 | slight |
| 8 | 1.96–2.01 | 1.5 | 2.5 | 4.1 | slight |
| 12 | 2.64–2.73 | 1.1 | 1.9 | **3.0** | **fair** |

- At x = 5%, the 1-for-1 is SLIGHT but the 6-, 8- and 12-piece packages read FAIR (stud 6,000
  or 9,000).
- At x = 8%, the 12-piece package reads FAIR at every stud size.

### 4c. Real trades (frozen board): median denominator inflation by category

| category | trades | median inflation | median FAIR tolerance (% of larger utility) |
|---|---:|---:|---:|
| 1-for-1 | 16 | 1.000 | 9.27 (the floor dominates) |
| all | 76 | 1.114 | 4.53 |
| unequal counts | 44 | 1.188 | 4.43 |
| deep (≥ 4 pieces on a side) | 17 | **1.283** | 4.49 |

Worked real case, 2026-08-12, 9-for-5 (Jason ↔ Roy):

- utility gap = **15.4%** of the larger package utility;
- larger adjusted side = 39,771 (inflation 2.13);
- band rel = 7.2%, which reads **SLIGHT**;
- on a utility basis the same trade is **UNFAIR**.

### 4d. Synthetic draws: effective tolerance rises with piece count

High-value stratum:

| 2v2 | 2v3 | 3v3 | 1v4 | 2v5 | 1v6 | 3v8 |
|---:|---:|---:|---:|---:|---:|---:|
| 3.8% | 4.0% | 4.0% | 4.5% | 4.7% | 5.1% | 5.6% |

This bias sits **in the band**, on top of the package model's own documented deep-package
behaviour. The package model's evaluation memo (§4) shows GEOM_78 sides with the stud 99.8% of
the time in deep stud-for-depth trades. That is a model property, and the band does not change it.

---

## 5. Picks and IDP

### 5a. Picks (frozen board, `resolve_pick_label_value`)

| gave | got | gap | rel | level |
|---|---|---:|---:|---|
| 2028 Round 5 (1,557) | 2028 Round 6 (1,426) | −131 | 8.4% | **fair** |
| 2028 Round 4 (1,676) | 2028 Round 6 (1,426) | −250 | 14.9% | **unfair** (exactly at the floor) |
| 2028 Round 3 (2,275) | 2028 Round 4 (1,676) | −599 | 26.3% | lopsided |
| 2028 Round 1 (4,747) | 2028 R2 + 2028 R3 | +90 | 1.7% | fair |
| 2028 Round 1 | 2029 Round 1 (4,136) | −611 | 12.9% | unfair |
| 2027 Pick 1.02 (5,388) | 2027 Pick 1.06 (4,707) | −681 | 12.6% | unfair |
| 2028 R1 + 2029 R1 | 2027 Pick 1.01 (7,234) | −739 | 8.3% | slight |

- Rounds 4–6 sit in a flat 1,230–1,690 region, so the 250 floor alone decides pick-for-pick
  trades there. A one-round swap flips between FAIR and UNFAIR on single points.
- Future picks with no slot are priced at the generic uniform-tier expected value
  (`derived_uniform_tier_ev`, PRIOR). Every 2028 first-round pick prices the same, so fairness
  between generic future picks is decided by that convention.
- A trade label such as "2029 Mid 1st" is legacy display wording for an unknown slot.
  `resolve_pick_label_value` tries the stated tier first. The public flow should send canonical
  pick ids (identity-first) so that the label grammar cannot change the verdict.

### 5b. IDP (frozen board)

All 397 priced IDP rows are below 7,143, so **every** IDP 1-for-1 is judged by the 250 floor.

| gave | got | gap | rel | level |
|---|---|---:|---:|---|
| Fred Warner 4,208 | Edgerrin Cooper 3,998 | −210 | 5.0% | fair |
| Roquan Smith 3,309 | Nik Bonitto 2,979 | −330 | 10.0% | unfair |
| Byron Murphy 2,409 | Kaden Elliss 2,265 | −144 | 6.0% | fair |
| Aidan Hutchinson 4,737 | Brian Burns + Kyle Hamilton (2,825 each) | +291 | 5.2% | slight |

Real current-board IDP-only trades: 4 of 4 are NOT FAIR. Mixed offense + IDP: 1 of 14 FAIR.
These are drifted values, so they say nothing about whether those trades were fair at the time.

---

## 6. Real trades: level distribution

### 6a. Structure study (frozen 2026-10-20 board; worst team level per trade)

| category | trades | fair | slight | unfair | lopsided | FAIR (fair only) | FAIR if fair + slight |
|---|---:|---:|---:|---:|---:|---:|---:|
| all | 76 | 17 | 12 | 15 | 32 | 22% | 38% |
| 1-for-1 | 16 | 5 | 1 | 3 | 7 | 31% | 38% |
| larger side < 3,000 | 10 | 3 | 0 | 2 | 5 | 30% | 30% |
| deep (≥ 4 pieces) | 17 | 5 | 6 | 5 | 1 | 29% | 65% |
| includes picks | 37 | 6 | 7 | 6 | 18 | 16% | 35% |
| includes IDP | 19 | 1 | 5 | 3 | 10 | 5% | 32% |
| multi-team (3) | 1 | 0 | 0 | 0 | 1 | 0% | 0% |

These values have drifted since the trade dates, which inflates the share that reads NOT FAIR.
Use 6b for behaviour at the time of each trade.

### 6b. At-time vendor prices (point in time, at most 7-day lag)

| price source | graded | fair | slight | unfair | lopsided | FAIR (fair only) | FAIR if fair + slight |
|---|---:|---:|---:|---:|---:|---:|---:|
| IDP Trade Calculator | 24 | 11 | 3 | 7 | 3 | 46% | 58% |
| KTC SF TE++ | 16 | 9 | 3 | 1 | 3 | 56% | 75% |

In both price sources, the 1-for-1 trades that read FAIR include the 8.8–16.1% gaps at low L
(the floor). Two "trades" are 0-for-1 or 3-for-0. They most likely carried FAAB or another
consideration that the trade record does not capture. They read LOPSIDED, which correctly signals
"gift-like", but the public Advisor cannot price FAAB.

### 6c. History grade vs band on the same 153 team results (frozen board)

| history grade | band fair | slight | unfair | lopsided |
|---|---:|---:|---:|---:|
| "Fair trade" (< 3.0%) | 22 | 0 | 0 | 0 |
| not "Fair trade" | **12** | 24 | 31 | 64 |

In 12 team results the Advisor would say FAIR TRADE while the League Hub trade history grades the
same quantity as a slight win or overpay.

---

## 7. Multi-team: the per-team test with the same owner

### 7a. Definition: no new formula, one call per team

For each participating team *i*, from one validated routing ledger:

- `G_i` = every asset *i* sends, to any destination;
- `R_i` = every asset routed to *i*, from any sender;
- `(send_adj, recv_adj) = package_model.adjusted_pair_totals(G_i, R_i)`;
- `gap_i = recv_adj − send_adj`, which equals `U(R_i) − U(G_i)` under geom;
- `level_i = fairness_bands.classify(gap_i, max(send_adj, recv_adj))`.

That is exactly `analyze_trade.equity_verdict(G_i, R_i)`. It is what Asset-Only `decide` already
does for one team, and it is what `src/public_league/trade_grading.py::grade_trade_sides` does for
historical N-team trades.

- **Trade FAIR** ⇔ every participating team's `level_i == "fair"` (the amendment's rule).
- **UNABLE TO DETERMINE** when any team's evidence gate fails (unpriced, off-board, unheld or
  unknown-ownership asset).
- For N = 2, `G_A = R_B` and `R_A = G_B`, so both teams get the same |gap| and denominator. The
  per-team rule therefore reduces exactly to today's 2-team band.

### 7b. Worked synthetic ledgers (direction and invariance checked)

| ledger | team results | sum of gaps | overall | order-invariant |
|---|---|---:|---|---|
| 3-team circle, 5,000 each | A, B, C: 0, 0, 0 → fair ×3 | 0 | FAIR | yes |
| 3-team circle 6,000 → B, 5,000 → C, 4,000 → A | A −2,000 lopsided; B +1,000 unfair; C +1,000 lopsided | 0 | NOT FAIR | yes |
| A sends 6,000 → B and 3,000 → C; B sends 7,000 → A; C sends 2,500 → A | A +610 slight (6.4%); B −1,000 unfair; C +500 unfair (16.7%) | **+110** | NOT FAIR | yes |
| 4-team circle 1,200 / 1,000 / 1,100 / 950 | A −250 **lopsided** (20.8%); B +200 **fair** (16.7%); C −100 fair; D +150 fair | 0 | NOT FAIR | yes |
| Gift: A sends 3,000 to B; C does nothing | A lopsided (100%); B lopsided; **C fair (relPct None)** | 0 | NOT FAIR | yes |

What the worked ledgers show:

- **Direction is correct.** In the one-to-many case, C sends 2,500 and receives 3,000 and reads
  as *getting* value. The current JS N-side meter gives C a large loss here (`engine_state.md`
  finding 3). The per-team owner call does not have that defect.
- **Gaps need not sum to zero** (+110 above). Package utility is not conserved when packages are
  regrouped. That is why the trade cannot be collapsed into "two imaginary sides".
- **Low-value discontinuity across teams.** In the 4-team case, B at +16.7% is FAIR and A at
  −20.8% is LOPSIDED. The difference is 200 vs 250 points.
- **A non-participating team classifies FAIR**, because `classify` returns fair when the larger
  side is ≤ 0. Ledger validation must therefore reject a listed team that has no legs. It must
  not let that team pass.

### 7c. The all-teams rule tightens with N (SYNTHETIC random circles, 2 out / 2 in per team)

| asset band | N | per-team fair rate | all teams fair |
|---|---:|---:|---:|
| 800–2,000 | 2 | 0.361 | 0.361 |
| 800–2,000 | 3 | 0.361 | 0.112 |
| 800–2,000 | 4 | 0.360 | 0.037 |
| 2,000–6,000 | 2 | 0.105 | 0.105 |
| 2,000–6,000 | 3 | 0.108 | 0.011 |
| 2,000–6,000 | 4 | 0.108 | 0.001 |

- The per-team test is unchanged by N.
- The trade-level AND rule makes FAIR rarer as more teams take part, and rarer still at higher
  values where the floor no longer helps.
- This is the semantics the owner chose. The public copy should say it plainly, for example "a
  multi-team trade is fair only when it is fair for every team". It is not a defect to "fix" by
  scaling thresholds with N, because that would be a new formula.

---

## 8. Methodology change needed: OWNER DECISION, not implemented

The public answer must come from the shared owner (amendment, and CLAUDE.md "one concept, one
owner"). `fair` already decides the private Asset-Only NO — TOO CLOSE, so any change below also
moves:

- private YES / NO;
- the /trade meter;
- balancers;
- the Analyze market lens and `equity_verdict` (Best Offers, Package Builder);
- the suggestions badge.

It must be re-measured with `scripts/measure_fairness_band_change.py` before it ships. The #1861
design cites a "D8" rule forbidding re-opening the fairness classifications. The 2026-10-20
amendment explicitly asks for validation and an owner decision, so the owner should say which one
governs.

Decisions required, smallest first:

| # | decision | options | evidence here |
|---|---|---|---|
| OD-F1 | Which band level(s) count as **FAIR TRADE** | (a) `fair` only, which matches the private NO — TOO CLOSE definition, so public FAIR equals private "too close to call"; (b) `fair` + `slight` | 6b: fair-only gives 46–56% of accepted trades FAIR; fair + slight gives 58–75% |
| OD-F2 | **Denominator basis** | (a) keep the larger adjusted side (depth-inflated, §4); (b) larger package **utility** `max(U_G, U_R)`, so numerator and denominator share one scale. Identical for 1-for-1 | Counterfactual on 153 real team results: 18 change level, all stricter (10 slight→unfair, 4 unfair→lopsided, **4 fair→slight**, i.e. public FAIR→NOT FAIR) |
| OD-F3 | **Absolute floor** | (a) keep 250; (b) remove it (pure relative): 6 of 153 real team results move fair→slight; (c) a smaller floor justified by measured value uncertainty | §3f: the floor is about 2.3× the p90 weekly vendor move at low values. No canonical-history noise measurement is available in this container |
| OD-F4 | **Validation target** before the label is called validated | owner-labelled fair / unfair set; or point-in-time canonical values on identity-proven market-trade groups (box-local `data/intel` plus the temporal ledger) with a chronological holdout. Precedent: Hill gate 7 | None of these exist in this container |
| OD-F5 | **Version and status to publish** | (a) launch on an explicitly owner-approved declared PRIOR (`fairness_bands_v2`, `status: PRIOR_OWNER_APPROVED`) and validate after launch; (b) hold launch until OD-F4 is met | The amendment requires "fixed, versioned, deterministic, server-owned". The current `PROVISIONAL` status cannot be published silently |
| OD-F6 | **Reconcile the public history grade** (3.0%, no floor) with the Advisor's FAIR | align it to the same owner, or relabel the history grade so it does not say "Fair trade" | §6c: 12 of 153 disagree |

**Engineering recommendation for the owner to accept or reject:**

- **OD-F1** (a): fair only.
- **OD-F2** (b): utility basis. This removes the depth bias with no new constants.
- **OD-F3**: keep 250 only as an explicitly approved PRIOR until a canonical-noise measurement
  exists. Otherwise take (b) and accept that low-value trades read stricter.
- **OD-F5** (a), with OD-F4 as a named post-launch validation item.
- **OD-F6**: align it.

This is a recommendation. None of it is implemented.

---

## 9. Implementation notes for the lanes (no methodology content)

- Server-owned: the public result must stamp `fairness_bands.receipt()` (`version`, `status`) and
  `package_model.receipt()` internally, for the receipt log. Only the category may leave the
  server.
- Python/JS seam: on `NaN`, the JS `classifyGap` returns **fair** and Python `classify` returns
  **lopsided**. Inputs are filtered upstream, so this is inert today. The public path must use
  Python only.
- Boundary semantics: a gap of exactly 250 is **not** fair (`<`). The live pick example (R4 for
  R6, gap 250) sits on this edge.
- Two-team and N-team sit on one path (§7a). `public_category_from_net_band` in `trade_decision.py`
  and #1861's `multi_side.side_flows` / `side_band` must not be the N-team path. Use the per-team
  `equity_verdict` / Asset-Only `decide`.
- Privacy (OD-4 input): a binary FAIR / NOT FAIR answer with a 250 floor leaks pairwise distances
  to ±250 points for 97.5% of the board, if someone runs 1-for-1 probes. A relative basis leaks
  ratios instead. Whichever threshold is chosen sets how finely an attacker can reconstruct
  values. Rate limits alone are not the defence.

---

## Completion

- **STATUS:** DONE (research unit).
- **ACCEPTANCE:**
  - find the owner and its provenance;
  - evaluate it empirically on small trades, deep packages, picks, IDP, mixed and multi-team;
  - analyse scale invariance and package-size bias;
  - define the multi-team per-team test using the same owner;
  - conclude on suitability and state the required owner decision.
- **EVIDENCE:**
  - `fairness_research.json`, `mt_rate.json` and `noise.json` in `scratchpad/tam/fair_out/`;
  - code reads of the owners cited by file:line above;
  - order invariance checked on every worked multi-team ledger.
- **UNRESOLVED:**
  - no point-in-time **canonical** board history (temporal ledger absent);
  - no market-trade ledger (box-local `data/intel` empty here), so no calibration target or
    holdout could be run;
  - the noise proxy uses vendor values, not canonical ones;
  - own-league sample size: 40 trades in the archive window, 3 three-team trades, of which 1 was
    priceable;
  - OD-F1–OD-F6 are owner decisions.
- **BLOCKERS:** owner decisions OD-F1–OD-F6 before a public threshold version can be fixed.
- **NEXT_ACTION:** owner rules on OD-F1–OD-F6. Then run `scripts/measure_fairness_band_change.py`
  against the chosen variant on every consumer, run the on-box market-trade evaluation for OD-F4,
  and implement the version bump in the one owner.
