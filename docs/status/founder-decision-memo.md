# Founder Decision Memo

_2026-03-22 — Corrected Checkpoint_

---

## 1. Is internal-primary still justified?

**Yes, clearly.** 9/9 hard checks pass with comfortable margin. The canonical pipeline
produces defensible values with 14 sources and is directionally trusted. Player-by-player
review found canonical more right on 14 of the 20 most important disagreement players.

## 2. What blocks public-primary?

Three things. Only one requires real work:

| Blocker | Type | Gap | Fix |
|---------|------|-----|-----|
| Offense tier agreement | Metric | 53.5% vs 65% (−11.5%) | **Fresh full scraper run** |
| Offense avg delta | Metric | 999 vs ≤800 (+199) | Same — these are the same 162 players |
| Founder approval | Manual | Not given | Your call after the above |

The tier and delta failures are **the same root cause**: 162 offense players where
canonical is exactly 1 tier higher than legacy. This happens because legacy only has
2 sources (FantasyCalc + DLF), while canonical has 14. The missing 9 browser-scraped
sources would raise legacy values for these mid-tier players, resolving the tier boundary
disagreements.

Only 53 of those 162 need to resolve to reach 65% tier. If they do, projected delta
drops to ~569 — well below the 800 threshold.

## 3. Has the canonical direction been strengthened or weakened?

**Strengthened.** The collision fix improved offense top-50 from 78% to 82%, clearing a
blocker that appeared to be a model problem but was actually a comparison-layer bug.
No canonical model logic has been changed. The direction is confirmed by:

- Player-by-player review: canonical right on 14/20 key disagreements
- IDP tier agreement: 74% (strong, no issue)
- No structural misranking — disagreements are value-magnitude, not ordering

## 4. What should you do next?

**Run the scraper on the production server.** This is the single highest-leverage action.

Here is why it beats the alternatives:

| Option | Expected impact | Risk | Recommendation |
|--------|----------------|------|----------------|
| **Full scraper on production** | Likely clears both tier (→65%+) and delta (→<800) | Low — doesn't touch canonical code | **DO THIS** |
| Tune calibration curve | Could close tier gap by 5-8% | Medium — fitting to incomplete reference | Don't |
| Revise thresholds downward | Clears the checks immediately | Medium — reduces quality bar | Don't |
| Hold and wait | No progress | No risk | Only if production scraper not available |

The production server has unrestricted internet and can render the JavaScript-heavy
pages that this sandbox cannot. Run: `python "Dynasty Scraper.py"` then re-run the
comparison pipeline.

## 5. What should you approve next?

In this order:

1. **Activate `internal_primary` on production** — set `CANONICAL_DATA_MODE=internal_primary`
   and restart. Zero public impact. Lets you inspect canonical values via scaffold endpoints.

2. **Run the scraper on production** — produces a full 11-source legacy reference.
   Then re-run `python scripts/run_comparison_batch.py` and `python scripts/check_promotion_readiness.py`.

3. **Review the updated metrics** — if tier ≥65% and delta ≤800 after the full scraper run,
   the only remaining blocker is your explicit approval.

---

_This memo is based on 399 passing tests, 14-source canonical pipeline, and config-driven
promotion thresholds. All artifacts are reproducible from the current commit._
