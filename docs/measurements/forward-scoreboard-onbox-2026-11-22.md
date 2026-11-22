# Forward validation scoreboard: first on-box run, 2026-11-22

**Question.** Top-10 dynasty item #1: does the served canonical board predict the market's later moves?
**Directive:** owner, 2026-11-21 (intake DYN10).

**Run details.**
- Workflow: `forward-scoreboard-onbox.yml` (#2307), run 45040989830, dispatched 2026-11-22 15:55 UTC.
- Code: production build `9e991616`.
- Input: a backup-API copy of the box temporal ledger (`canonical_board` lane plus the market lanes).
- Output: aggregates only. No player, league or id appears here.

**Status.** This is a measurement, not a methodology change. Nothing here alters a value, a source weight or a flag.

**Masking caveat.** The job log masks the `DEPLOY_PORT` secret (`22`), which mangled some printed numbers.
- Every figure quoted below was checked against the log. None of them contains a masked digit, and every verdict sentence is intact.
- #2313 uploads the summary as an unmasked artifact, so future runs will carry exact figures.

## Panel

- **Dates:** 132 dates, 2026-07-14 → 2026-11-22. The served board is present on 126 of them.
- **Market lanes:** idpTradeCalc 132 dates; KTC 131; KTC SF TEP 131; KTC Market (Crowd + Trades) 74.
- **Design:** folds are non-overlapping and anchored at 2026-07-14, with origins 07-14, 08-13, 09-12 and 10-12.
- **Outcome:** the cohort-excess change in the market's own price.
- **Momentum control:** each gap is controlled for the market's own prior move (partial rank correlation).

## Result: served board vs the market's later moves, net of momentum

**30-day horizon, 3 usable origins.** The 07-14 origin is unusable, because the board has no observation that day.

| Group | Mean partial ρ (net of momentum) | Origins positive | Verdict |
|---|---|---|---|
| ALL | +0.016 | 1 / 3 | no effect detected |
| QB | −0.077 | 0 / 3 | **negative and consistent** |
| RB | +0.038 | 2 / 3 | no effect detected |
| WR | −0.065 | 1 / 3 | inconsistent |
| TE | +0.054 | 2 / 3 | inconsistent |
| IDP | +0.031 | 3 / 3 | no effect detected |
| PICK | — | — | no verdict (1 origin with a momentum control) |

- **60-day horizon:** 1 origin, so no verdict in any group.
- **90-day horizon:** unavailable. The ledger history starts 2026-07-14.

### Benchmarks (30 days, ALL)

| Benchmark | Folds where the board beat it | Benchmark mean Spearman |
|---|---|---|
| Market value | 3 | −0.037 |
| Random | 1 | 0.006 |

**Attrition per fold** (assets that leave the market board before the horizon):

| Origin | Dropped | Rate |
|---|---|---|
| 07-14 | 18 | 1.9% |
| 08-13 | 99 | 10.3% |
| 09-12 | 70 | 7.9% |
| 10-12 | 38 | 4.2% |

### Per source (30 days, ALL, net of momentum)

| Source | Verdict |
|---|---|
| idpTradeCalc | no effect detected (−0.027, 3 origins) |
| KTC | underpowered (−0.031, 2 origins) |
| KTC SF TEP | underpowered (+0.010, 2 origins) |
| KTC Crowd, KTC Trades, KTC Market, Signals SF | no verdict (fewer than 2 origins with a momentum control) |

## Reading

1. **No measurable edge yet.** Where the served board disagrees with the market, the market does not later move toward the board, once its own momentum is controlled. Mean partial ρ is +0.016, positive in only 1 of 3 origins. A gap in either direction carries no forward information at 30 days.
2. **QB is the one consistent signal, and it points the wrong way.**
   - In all three origins, when the board disagreed with the market on a QB, the market moved further away from the board (−0.077).
   - Treat this as a research lead, not a finding to act on. The evidence is three origins, and any QB valuation change is an owner-reserved methodology decision.
3. **In-sample caveat.**
   - KTC Crowd, KTC Trades and idpTradeCalc vote in the served board, and KTC Market is the blend of Crowd and Trades. So "board vs market" is not an independent test of the votes.
   - It is still a fair test of whether the board's deviations from the market carry information.
4. **Still an unregistered candidate.** `independentValidationCandidate`: `couldQualifyAsIs: false`, `registered: false`. This does not satisfy Hill Autopilot gate 7.
5. **Next measurement.**
   - 60-day verdicts need a second origin.
   - 90-day verdicts need about two more months of ledger history.
   - Re-dispatch monthly, away from the :27/:32 refresh windows.
