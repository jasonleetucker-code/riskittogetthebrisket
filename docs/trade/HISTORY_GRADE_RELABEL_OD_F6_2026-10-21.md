# History trade grade: lowest tier renamed "Evenly valued" (OD-F6 option A)

**Owner decision:** OD-F6 option A, 2026-10-21 (about 12:40 UTC), "approved with a wording safeguard". The record
is `docs/owner/LVA_OWNER_DECISIONS_2026-10-21.md`, Package 2. The authorization is the LVA entry "P2" in
`docs/EXECUTION_PLAN.md`.

**What changed:** the lowest tier of the trade-history grade used to say "Fair trade". It now says **"Evenly
valued"**. The pages now explain what the grade measures, and the 3% criterion is defined in one place. **No grade
changed.** Letters, colours, cut points, `pctGap`, nets, Won/Lost counts and the order of results are all exactly
as before.

## 1. Why the word changed

The advisor, the War Room and the trade meter use "FAIR" (FAIR TRADE / NOT FAIR) for the market-fairness verdict
from `fairness_bands_v2`. That verdict means the gap is under 3.5% of the larger package utility, or the gap is
under the 250-point floor. The history grade used "Fair trade" for a different rule: a gap under 3.0% of the larger
adjusted side, with no floor. So one word meant two things. PR #1900 measured the effect on 153 real sides: the two
rules disagree on 6 of them (3.9%), and all 6 come from the floor
(`docs/trade/HISTORY_VS_PUBLIC_FAIRNESS_ALIGNMENT_2026-10-21.md`). Option A keeps both rules and stops them sharing
a word.

## 2. Which word, and the evidence for it

The owner's safeguard was this: use "Even outcome" only if the grade really measures realized outcomes. If it
measures how the values balanced, use a word like "Evenly valued". The grade was traced through the code:

| Step | Code | What it uses |
|---|---|---|
| Asset values | public `/league`: `src/public_league/activity.py` (at-the-time value from the temporal ledger, and today's board); `/trades`: `frontend/lib/league-analysis.js::analyzeRawTrade` (today's board) and `POST /api/trades/asof-grades` (at the time) | board **values** (`rankDerivedValue` and its history) |
| Package adjustment | `package_model.adjust_pair` / `packageAdjustPair` (`geom_q078_v1`) | a value adjustment for depth |
| Margin | `trade_grading.grade_trade_side` / `gradeTradeSide`: `pctGap = (got − gave + vaNet) / max(adjusted got, adjusted gave, 1) × 100` | the value gap as a share of the larger adjusted side |
| Tier | `grade_from_pct` / `gradeTradeHistorySide` | `abs(pctGap)` against 3 / 8 / 15 / 25 / 40 |

Nothing in this chain reads fantasy points, games, starts, wins, standings or any other realized result. Even the
"Today" grade only revalues the same assets on today's board, so it measures how the **values** compare now, not
what the players did. The grade measures **value balance**. "Even outcome" would claim more than it measures, so
the label is **"Evenly valued"**. It also avoids the word "fair".

## 3. The distinction, as the pages now state it

On `/trades`, above the trade list, and on the public `/league` trade timeline, there is a visible line. The same
text also appears on hover over each grade:

> Trade grades compare the value each side gave and got (board value plus the package adjustment), as a share of
> the larger side. "When traded" uses the latest values recorded before the trade; "Today" uses today's values.
> "Evenly valued" means the gap is under 3% of the larger side. It measures how the values balanced, not how the
> players went on to perform, and it is not the FAIR / NOT FAIR market-fairness verdict of the trade calculator and
> advisor.

On `/league` the line shows only when the feed carries grades.

## 4. One authoritative 3% criterion

- **Owner:** `src/public_league/trade_grading.py::HISTORY_EVEN_PCT` (3.0) and `HISTORY_EVEN_LABEL`.
  `_GRADE_PCT_FAIR` keeps its old name because read-only research scripts read it, but its value is that
  constant.
- **JavaScript mirror:** `frontend/lib/trade-history-grade-policy.js` has `HISTORY_EVEN_PCT`, `HISTORY_EVEN_LABEL`
  and `historyGradeBasisText()`. Every JavaScript use reads it: `gradeTradeHistorySide`, the Won/Lost rule in
  `analyzeSleeperTradeHistory`, and the `/trades` card badge. That replaces the four bare `3` literals.
- **Pinning:** `tests/public_league/test_history_grade_relabel_no_change.py` reads the JavaScript exports and checks
  that they equal the Python ones. It also fails if a bare `3` returns to those paths. The shared parity fixture
  `tests/fixtures/trade_grade_parity_cases.json` states the same cut and word for both languages.

## 5. Proof that no grade changed

`tests/fixtures/history_grade_relabel_reference.json` was written **before** the code change, at `main`
`ce22d5de7`, by the old code itself. It was committed alone, ahead of the change. It contains:

- the grade's output over a 0.001-step scan from 0 to 60%, for winners and losers;
- probes 1e-9 either side of every cut point;
- 600 seeded `grade_trade_side` cases, with every number;
- 200 seeded two-team trades through `grade_trade_sides`, with the active package model.

Both runtimes recompute all of it and must match exactly. The only difference allowed is "Fair trade" becoming
"Evenly valued":

- Python: `tests/public_league/test_history_grade_relabel_no_change.py`
- JavaScript: `frontend/__tests__/history-grade-relabel-no-change.test.js`

The grade depends only on `abs(pctGap)`, its sign and the cut points. `pctGap` is computed by code this change does
not touch. So the scan covers the whole range of the tier function.

**Served payload:** the public `/league` activity feed and `POST /api/trades/asof-grades` serve the grade's
`label`. On the evenly-valued tier, that string now reads "Evenly valued". No other served field changed, and no
new field or flag was added.

## 6. Not changed, and still open

- `fairness_bands_v2` (`src/valuation_math/fairness_bands.py`, `config/trade/fairness_bands.json`),
  `geom_q078_v1` and q = 0.78 are untouched.
- The tiers above the lowest one are unchanged: Slight win, Good win, Clear win, Big win, Slight overpay, Overpay,
  Bad deal, Robbery, Fleeced. The **"win" collision** therefore remains. A 3–8% history "Slight win" can sit beside a
  trade the market calls FAIR. Option A does not resolve that, as #1900 §4 said.
- The `/trades` card still prints `won by N%` as a share of the larger *adjusted* side. The trade meter prints a
  share of the larger *package utility*. The basis line says which one the history uses, but the two percentages
  still differ (#1900 §1.3).
- Re-measuring under the owner's base (option C) still waits for OD-F4 evidence.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c
