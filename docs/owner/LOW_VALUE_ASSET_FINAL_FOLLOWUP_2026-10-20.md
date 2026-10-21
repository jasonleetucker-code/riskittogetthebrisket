# Owner directive — low-value-asset box run, final follow-up and two targeted investigations (2026-10-20)

**Recorded verbatim** (the owner's two messages of 2026-10-20, unchanged except for list formatting).
The second message governs where the two differ.

Context:
- Program directive: `docs/owner/LOW_VALUE_ASSET_RESEARCH_2026-10-20.md`.
- Final memo: `docs/valuation/LOW_VALUE_ASSET_RESEARCH_2026-10-20.md`.
- Box report: `docs/valuation/evidence/low_value_assets_2026-10-20/production_box_run_2026-10-20.json`.

---

## Message 1

The low-value-asset production research run completed successfully.

Results:

- Exit code: 0
- 18,690 trades
- 11,565 leagues
- 0 prohibited write/process attempts
- M3 and M4 data available
- Peak memory: 1,124.7 MB

I've attached `low-value-asset-box.json`.

Please validate the complete report against the frozen preregistration, including checks M1–M4 and decision rules R-A,
R-B, R-B0 and R-C.

Verify the read-only guard, the 273 refused network calls and the impact of any fallback data.

Finish the full research report, using the new production findings to determine whether low-value assets need a
canonical value adjustment, a trade-currency adjustment, or no adjustment at all.

I'm especially interested in:

1. Whether legitimate roster depth is being unfairly penalized.
2. Whether Team Context is already charging too much for forced drops.
3. The IDP replacement-value anomaly.
4. Whether low-value filler can improperly turn an unfair trade into a fair trade.
5. How the findings affect our upcoming public Fair/Not Fair calculator.

Provide a clear recommendation supported by the evidence, and identify any follow-up investigations that should
proceed separately.

Do not change production values or calculations. Keep GEOM_78 (q = 0.78) active. Continue unrelated authorized work in
parallel.

## Message 2

The production low-value-asset research report is attached as `low-value-asset-box.json`.

Please complete the final Phase 3 follow-up under the existing frozen preregistration.

The production run succeeded with 18,690 graded trades, 11,565 leagues, both M3 and M4 available, and zero refused
write/process operations.

Pay particular attention to these findings:

1. M1: The alternative curves improve agreement with completed trades, but agreement alone cannot establish superior
   valuations.
2. M2: Usable depth has lower median implied extra-piece credit than filler (0.093 versus 0.183). Investigate the
   confounding from pick composition and the classification rules; do not claim a causal effect.
3. M3: The observed low-value assets generally do not show the predicted excess 60-day depreciation. Address missing
   horizons, pipeline-version changes, and any unavailable clustered confidence intervals.
4. M4: Extra package pieces, including filler and usable depth, generally maintained their values over 30 days. Account
   for missing lookups and selection effects.
5. Apply R-A, R-B, R-B0 and R-C exactly as frozen, combining these findings with the previously completed exploratory
   evidence.
6. Verify the 273 blocked network attempts against the earlier offline-parity audit and confirm whether its conclusions
   still apply to this run.
7. Explicitly document that only 138 graded trades involve IDP assets and that the multi-team evidence was excluded.

My preliminary decision is to retain GEOM_78 (q = 0.78), retain existing canonical player values, and introduce no
blanket trade-currency discount.

If the frozen rules support R-C, recommend informational disclosure only. Any actual UI implementation should be
separately reviewed, and the public Fair/Not Fair calculator must continue hiding proprietary numerical values.

Separately, prepare two targeted investigations:

A. Forced-drop valuation: Examine the 57 assumed waiver-value charges for unpriced players and the 43 overcorrected
   filler cases. Determine whether the current roster-capacity system overcharges drops.

B. IDP replacement values: Investigate why positional waiver anchors, including the DB anchor of 2,156, exceed some
   current starting IDP values (DB starter line 1,335). Evaluate whether this reflects roster management, league
   scoring, replacement methodology, or valuation issues.

Do not make production changes through either investigation.

Complete the final owner report, evidence checks, independent review, and PR #1833 validation. Continue the
public/private multi-team calculator and other authorized work independently.

No valuation change, fairness-threshold change, or public activation is authorized.
