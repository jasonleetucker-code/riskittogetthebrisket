# Owner decisions — PR #1833 and the low-value-asset research follow-ups (2026-10-20)

**Recorded verbatim** (the owner's message, unchanged except for list formatting).

Context:
- Final memo: `docs/valuation/LOW_VALUE_ASSET_RESEARCH_2026-10-20.md`.
- Earlier directives:
  - `docs/owner/LOW_VALUE_ASSET_RESEARCH_2026-10-20.md`;
  - `docs/owner/LOW_VALUE_ASSET_FINAL_FOLLOWUP_2026-10-20.md`.

---

OWNER DECISIONS — PR #1833 AND LOW-VALUE-ASSET RESEARCH FOLLOW-UPS

I have reviewed the final low-value-asset research findings.

I approve the following decisions.

## 1. APPROVE R-C — INFORMATIONAL ONLY

Retain `geom_q078_v1` (q = 0.78) and all existing canonical player values.

Do not introduce a blanket low-value haircut or a separate trade-currency adjustment.

I approve the informational-disclosure approach as the research conclusion. Develop an optional, league-aware
disclosure design in a separate workstream.

The disclosure should help managers understand that low-value depth may be treated differently in the trade market,
without implying those assets are worthless.

Do not change trade values, verdicts, or fairness thresholds to implement the disclosure.

For the public calculator, do not reveal proprietary numerical values, replacement anchors, gaps, or formulas. Bring
the exact copy and triggering rules for review before activation.

## 2. AUTHORIZE INVESTIGATION A AND SCOPED CORRECTNESS FIX — HIGH PRIORITY

The forced-drop problem needs to be fixed.

Investigate and correct the mismatch between how the system selects a player to cut and how it charges the receiving
team for that cut.

Specifically:

- Eliminate inappropriate alphabetical selection among sub-waiver players.
- Evaluate the cheapest legal cut while respecting lineup, roster and league rules.
- Correct the treatment of unpriced players without silently assigning them zero value.
- Account for incoming players who would immediately be dropped.
- Compare the documented V1–V4 approaches, including package consistency, rather than automatically selecting V1.
- Prevent double-counting player values, forced-drop costs or package adjustments.
- Preserve consistency across the Trade Calculator, War Room, Trade Finder and trade-history analysis where
  applicable.

Run real-roster replays, adversarial tests, before/after verdict comparisons and independent mathematical review.

Develop this as a separate, isolated PR. If the fix changes served trade recommendations, bring the exact production
impact to me before activating it.

Prioritize this work because the public calculator's current two-team path may inherit the defective forced-drop
behavior.

## 3. AUTHORIZE INVESTIGATION B — IDP REPLACEMENT AND LEAGUE-SPECIFIC SCORING

Investigate why some available defensive players have higher canonical values than players currently starting in our
league.

Review:

- Injured or non-producing free agents being included in replacement anchors.
- Actual availability and eligibility of waiver replacements.
- Our league's specific IDP scoring.
- Defensive positional scarcity and roster requirements.
- The reported 0.45 IDP ranking correlation compared with 0.77 for offense.
- Whether the canonical IDP consensus properly reflects our league's scoring.
- How replacement anchors influence the Trade Calculator, roster-capacity costs, waivers and Trade Finder.

Do not automatically lower IDP player values or change our voting-source weights.

Determine whether this is a replacement-methodology issue, a league-specific valuation issue or both.

Use a separate research workstream and submit an evidence-based recommendation.

## 4. APPROVE MERGING PR #1833

I approve merging #1833 once the latest head passes the required CI and independent review checks.

This is a research-only merge.

It must not activate a new package model, change canonical values, alter source voting or modify live trade
recommendations.

## 5. PUBLIC CALCULATOR CONSISTENCY — IMPORTANT

Audit the difference between the existing two-team public Advisor using Team Context and the new three-/four-team
market-fairness engine.

My intended public product is a neutral FAIR / NOT FAIR / UNABLE TO DETERMINE calculator based on our predetermined
market-fairness methodology.

It should not quietly become a personalized Accept/Decline recommendation based on a manager's roster capacity or
strategic needs.

Ensure the public two-, three- and four-team implementations follow one consistent authoritative fairness
calculation, with no proprietary numerical values exposed.

Keep the separate private calculator and War Room fully roster-aware.

Do not independently activate or modify the public fairness threshold. Preserve the existing owner approval and
validation requirements for fairness_bands_v2.

## 6. EXECUTION

Use isolated worktrees and parallel agents for the forced-drop correction, IDP investigation, disclosure design and
public fairness consistency audit.

Do not interrupt the ongoing multi-team implementation, outlier-integrity-v2, source freshness work or production
stability releases.

Deliver findings, PR links, test evidence and explicit recommendations.

Research is approved. Implementing properly gated candidate fixes is approved. Changing live valuation behavior
remains subject to validation and my explicit approval.

Proceed.
