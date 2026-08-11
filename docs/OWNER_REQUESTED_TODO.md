# Owner-Requested To-Do List

This file is the durable repository record for owner-requested live defects, UX requirements, planned products, and explicitly deferred long-term ideas that must not be lost between implementation phases or coding sessions. Items remain open until the linked issue is actually reproduced/researched, implemented where authorized, validated, and closed.

## Added 2026-08-11

| Priority | Issue | Area | Required outcome | Status |
|---|---|---|---|---|
| P0/P1 live defect | #779 | Admin | Fix `/admin` client-side crash: `Can't find variable: fmtPassExpiry`; reproduce on the real page, RED→GREEN it, and verify the mobile/browser path. | TODO |
| P1 owner workflow | #780 | Admin / auth | Repair and verify the existing temporary-password/pass generator. Owner must be able to choose the validity duration in hours, generate a credential that actually works, and have expiry/revocation fail closed. Do not create a duplicate auth system. | TODO |
| P1 owner UX requirement | #781 | Trade Calculator | Keep manual player-value edits visually silent: no yellow highlight, badge, marker, or visible per-player override-reset affordance. Add a discreet top-level **Reset Values** control; removing an edited player must clear that temporary override so re-adding restores the canonical/original value. Temporary edits must not mutate canonical value truth. | TODO |
| Future / cost-gated | #788 | Analyst intelligence / X | Preserve a future ~500-analyst Dynasty X feed using the official API only, with reputation-based curation and cross-media dedupe. Do **not** build while recurring API cost is disproportionate to the site's size/value; re-evaluate economics and policy later. | LONG-TERM |
| Planned product / dependency-gated | #789 | CE-20 Game Day Command Center | Build a Sunday companion that models this league's **exact custom scoring and best-ball lineup semantics**, with calibrated pregame/live final-score projections, best-ball-aware win probability, personalized matchup/event/news context, rooting/leverage guidance, mobile + desktop/TV UX, and a low-cost V1 that does not require paid real-time play-by-play. | PLANNED |

### Binding owner decisions

1. **Admin crash:** this is a real user-facing runtime defect, not cosmetic Admin polish.
2. **Temporary access:** preserve the existing time-limited access concept and make the end-to-end path work; configurable hours are required.
3. **Trade value edits are intentionally discreet:** the calculator may use an owner-entered temporary value without visually disclosing that the number was edited.
4. **No per-player override indicator:** remove the current yellow edited-state treatment and the visible per-player remove/reset-override marker.
5. **One global reset:** place a Reset Values / Reset Edited Values action with the Trade Calculator's top-level controls (near Import / KeepTradeCut / equivalent controls as appropriate to the current UI).
6. **Removal clears edit state:** if an edited asset is X'd/removed from the active trade, its temporary override must be discarded. Re-adding the player starts at the canonical/original calculator value.
7. **Canonical truth stays canonical:** a temporary Trade Calculator edit must not silently rewrite rankings, KTC/raw provider data, the canonical valuation model, Team Strength, or unrelated users' data.
8. **X feed is cost-gated:** keep the concept, but do not pay substantial recurring X API costs for the current small/private site. Official API/authorized integration only; no scraping. Revisit if economics improve or site scale justifies it.
9. **Game Day is now a real planned product:** CE-20 is no longer merely a vague optional dashboard. It should become a best-ball-aware matchup intelligence console once its prerequisites are trustworthy.
10. **Best-ball math must be real:** matchup projections and win probability must consider every still-eligible rostered player who could displace another player's score in the eventual optimal best-ball lineup. A provisionally filled slot is not treated as permanently finished while bench outcomes can still change it.
11. **Exact league scoring is required:** weekly/live projections must translate projected football outcomes into this league's complete scoring system. Unprojected scoring components such as first downs, reception-distance/big-play bands, or complex IDP events must be estimated with defensible historical/conditional models or remain explicitly uncertain; they must not silently become zero.
12. **Prediction accuracy must be measured:** archive pregame and in-game prediction snapshots and evaluate final-score error, best-ball lineup accuracy, and calibrated win probability (including Brier/reliability-style evaluation) without temporal leakage.
13. **Low-cost V1 first:** CE-20 must be useful using existing/legitimate low-cost matchup, projection, scoring, news and status data plus our own simulation. Paid second-by-second play-by-play is an optional later enhancement only if actual usage justifies the recurring cost.
14. **One canonical matchup projection engine:** CE-20 is a consumer/orchestrator. The frontend must not invent a separate win-probability formula, and the product should reuse canonical scoring, lineup assignment, player identity, projections and news/intelligence owners.
15. **Why CE-20 should beat Sleeper for this league:** it should model the actual best-ball outcome under the exact custom scoring rules, continuously update the full outcome distribution, explain what is driving the matchup, and show what matters next rather than merely displaying the current score.

### Game Day Command Center scope summary

The detailed authoritative requirements live in issue #789. At minimum the eventual product should include:

- current Sleeper matchup score/state;
- projected final score and uncertainty range for both teams;
- calibrated live win probability;
- entire-roster best-ball simulation rather than static starters;
- likely final best-ball lineup / player slot-contribution probabilities where useful;
- completed vs in-progress vs not-yet-started player state;
- player-level remaining projection/upside/downside;
- personalized event/news feed for owner, opponent and high-leverage players;
- rooting/leverage guide and late-Sunday/Monday "what do I need?" view;
- exact custom-scoring explanation when affordable event-level data supports it;
- mobile-first `For You | Matchup | Players | Games | News` style navigation;
- desktop/tablet TV mode with large text, auto-refresh and minimal interaction;
- responsible caching/polling and battery/network-conscious mobile behavior;
- backtesting and calibration versus actual final best-ball outcomes.

### Execution ordering

Do not mix these unrelated UI/auth/product requirements into the currently isolated B2 IDP curve-routing root-cause work. Immediate defects (#779-#781) should be picked up at the next safe product-hotfix checkpoint unless one blocks required verification. CE-20/#789 must enter the master dependency plan and should begin only after scoring correctness, canonical best-ball assignment, projection-source/custom-stat modeling and prediction-history foundations are ready. #788 stays long-term/cost-gated.
