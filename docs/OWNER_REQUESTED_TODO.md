# Owner-Requested To-Do List

This file is the durable repository record for owner-requested live defects, UX requirements, planned products, and explicitly deferred long-term ideas that must not be lost between implementation phases or coding sessions. Items remain open until the linked issue is actually reproduced/researched, implemented where authorized, validated, and closed.

## Added 2026-08-11

| Priority | Issue | Area | Required outcome | Status |
|---|---|---|---|---|
| P0/P1 live defect | #779 | Admin | Fix `/admin` client-side crash: `Can't find variable: fmtPassExpiry`; reproduce on the real page, RED→GREEN it, and verify the mobile/browser path. | TODO |
| P1 owner workflow | #780 | Admin / auth | Repair and verify the existing temporary-password/pass generator. Owner must be able to choose the validity duration in hours, generate a credential that actually works, and have expiry/revocation fail closed. Do not create a duplicate auth system. | TODO |
| P1 owner UX requirement | #781 | Trade Calculator | Keep manual player-value edits visually silent: no yellow highlight, badge, marker, or visible per-player override-reset affordance. Add a discreet top-level **Reset Values** control; removing an edited player must clear that temporary override so re-adding restores the canonical/original value. Temporary edits must not mutate canonical value truth. | TODO |
| Planned intelligence / staged | #782 | YouTube dynasty intelligence | Build a reputable dynasty-YouTube intelligence pipeline, targeting roughly 50 high-quality sources while deduping any YouTube representation already covered by Podcast Intelligence. Reuse canonical analyst/source identity, transcript/take extraction, independence and provenance, and feed appropriate outputs into Consensus Edge, player intelligence, Buy/Sell, selected-team intelligence and the personalized weekly team podcast/brief. | PLANNED |
| Planned product / staged | #783 | Universal Player Profile / intelligence | Add one canonical player-specific intelligence/news feed combining Podcast Intelligence, future YouTube Intelligence and canonical fantasy-news pools such as Sleeper, RotoWire, RotoBaller and other ingested sources. Preserve fact vs opinion, provenance, freshness and dedupe; use concise attributed excerpts, summaries or a hybrid rather than raw copyrighted duplication. | PLANNED |
| P1 owner UX / market intelligence | #784 | Homepage / Consensus Edge | Make the homepage stock-market-style buy/sell ticker consume canonical Buy/Sell/Consensus output. BUY items may be global; **SELL items must only be players rostered by the selected fantasy team**. The ticker is presentation, never a second signal algorithm. | TODO |
| P1 methodology audit | #785 | Tight-end premium / valuation | Deep-audit the exact two-TE/TE-premium methodology against real league settings and every source's TE basis. Measure standard→TEP/TE++ uplift curves where available, prevent double counting, search out stale blanket multipliers such as legacy `1.15`, and validate TE values versus cross-position scoring/scarcity evidence rather than merely forcing parity with KTC. | TODO |
| Planned trade UX / methodology | #786 | Trade Simulator / NFL-team exposure | Add **value-weighted NFL-team exposure before vs after** a proposed trade, with raw counts secondary. Informational only: it must not affect trade grade/recommendation unless separately authorized. Reuse the same canonical exposure primitive as CE-06 Portfolio. | PLANNED |
| Future / cost-gated | #788 | Analyst intelligence / X | Preserve a future ~500-analyst Dynasty X feed using the official API only, with reputation-based curation and cross-media dedupe. Do **not** build while recurring API cost is disproportionate to the site's size/value; re-evaluate economics and policy later. | LONG-TERM |
| Planned product / dependency-gated | #789 | CE-20 Game Day Command Center | Build a Sunday companion that models this league's **exact custom scoring and best-ball lineup semantics**, with calibrated pregame/live final-score projections, best-ball-aware win probability, personalized matchup/event/news context, rooting/leverage guidance, mobile + desktop/TV UX, and a low-cost V1 that does not require paid real-time play-by-play. | PLANNED |
| P1 methodology audit | #790 | Trade Calculator / Monte Carlo | Re-audit current-HEAD Monte Carlo end to end: canonical center values, TEP/IDP/pick/override propagation, uncertainty bands, package adjustment, correlations, symmetry/convergence/provenance, and the exact meaning of its win percentage. | TODO |
| P1 owner UX | #791 | Trade Calculator / Second Opinions | Add an immediate independent-vendor tally such as **Side A 5 · Side B 3 · Even 1 · 2 incomplete**, without counting canonical-value imputation as an independent external vote. | TODO |
| Planned decision product / dependency-gated | #792 | Trade Calculator / CE-05 Trade Desk | Add one canonical **Analyze Trade** recommendation that synthesizes unique-information dimensions into MAKE / LEAN MAKE / TOO CLOSE / LEAN PASS / PASS with confidence and reasons, without double-counting overlapping source/value signals. | PLANNED |
| Approved competitive expansion | CE-17–CE-21 | Dynasty Daddy-derived additions | Preserve approved League Format / Utilization Lab, Trade Trees / Asset Lineage, Waiver Market / FAAB Market Ledger, Game Day Command Center and Dynasty Season Recap / Wrapped, plus recorded enrichments to CE-03/04/06/09/11/12/13/14A/15 and Universal Player Profile. Reconcile through canonical owners rather than competitor-copy engines. | PLANNED |

### Binding owner decisions

1. **Admin crash:** this is a real user-facing runtime defect, not cosmetic Admin polish.
2. **Temporary access:** preserve the existing time-limited access concept and make the end-to-end path work; configurable hours are required.
3. **Trade value edits are intentionally discreet:** the calculator may use an owner-entered temporary value without visually disclosing that the number was edited.
4. **No per-player override indicator:** remove the current yellow edited-state treatment and the visible per-player remove/reset-override marker.
5. **One global reset:** place a Reset Values / Reset Edited Values action with the Trade Calculator's top-level controls (near Import / KeepTradeCut / equivalent controls as appropriate to the current UI).
6. **Removal clears edit state:** if an edited asset is X'd/removed from the active trade, its temporary override must be discarded. Re-adding the player starts at the canonical/original calculator value.
7. **Canonical truth stays canonical:** a temporary Trade Calculator edit must not silently rewrite rankings, KTC/raw provider data, the canonical valuation model, Team Strength, or unrelated users' data.
8. **YouTube intelligence must share the Podcast Intelligence architecture:** dedupe by canonical analyst/source/content identity so a podcast episode, its YouTube upload and a clip/repost cannot become independent votes. Target roughly 50 reputable dynasty sources, excluding channels already represented as podcasts where the content is duplicative.
9. **Unified Player Profile intelligence:** player profiles should consume one canonical intelligence/news feed across podcasts, future YouTube and all canonical news pools. Facts and opinions remain distinct, duplicated/syndicated content is collapsed, freshness/provenance is visible, and the surface should summarize or quote selectively rather than republish full articles/transcripts.
10. **Consensus ticker selected-team SELL rule:** BUY can surface relevant players broadly; SELL is only meaningful for players on the selected team's roster. The homepage ticker must consume canonical output and not invent another Buy/Sell calculation.
11. **TE premium must be evidenced, not guessed:** this two-mandatory-TE league requires a full source-basis/scoring/scarcity audit. KTC TE++ is an important diagnostic for a two-TE market but not an automatic truth target. Native TEP sources must not be premium-adjusted twice, and stale blanket multipliers must be justified or removed.
12. **Trade NFL-team exposure is descriptive only:** use canonical-value-weighted before/after exposure plus optional counts; picks have no NFL-team exposure; missing values stay explicit. Do not let concentration silently influence trade recommendations.
13. **X feed is cost-gated:** keep the concept, but do not pay substantial recurring X API costs for the current small/private site. Official API/authorized integration only; no scraping. Revisit if economics improve or site scale justifies it.
14. **Game Day is now a real planned product:** CE-20 is no longer merely a vague optional dashboard. It should become a best-ball-aware matchup intelligence console once its prerequisites are trustworthy.
15. **Best-ball math must be real:** matchup projections and win probability must consider every still-eligible rostered player who could displace another player's score in the eventual optimal best-ball lineup. A provisionally filled slot is not treated as permanently finished while bench outcomes can still change it.
16. **Exact league scoring is required:** weekly/live projections must translate projected football outcomes into this league's complete scoring system. Unprojected scoring components such as first downs, reception-distance/big-play bands, or complex IDP events must be estimated with defensible historical/conditional models or remain explicitly uncertain; they must not silently become zero.
17. **Prediction accuracy must be measured:** archive pregame and in-game prediction snapshots and evaluate final-score error, best-ball lineup accuracy, and calibrated win probability (including Brier/reliability-style evaluation) without temporal leakage.
18. **Low-cost V1 first:** CE-20 must be useful using existing/legitimate low-cost matchup, projection, scoring, news and status data plus our own simulation. Paid second-by-second play-by-play is an optional later enhancement only if actual usage justifies the recurring cost.
19. **One canonical matchup projection engine:** CE-20 is a consumer/orchestrator. The frontend must not invent a separate win-probability formula, and the product should reuse canonical scoring, lineup assignment, player identity, projections and news/intelligence owners.
20. **Why CE-20 should beat Sleeper for this league:** it should model the actual best-ball outcome under the exact custom scoring rules, continuously update the full outcome distribution, explain what is driving the matchup, and show what matters next rather than merely displaying the current score.
21. **Monte Carlo is an uncertainty lens, not the final trade oracle:** revalidate current math and provenance before using its percentage in a final recommendation. Its current value-distribution win rate must not be presented as a literal probability that the trade will succeed in real life.
22. **Value Adjustment must be explicit:** current Monte Carlo can apply the KTC-style consolidation adjustment, but exact KTC parity remains a secondary/advisory lens and must stay distinct from the future canonical site package methodology.
23. **Second Opinions needs a one-glance tally:** summarize independent vendor directions immediately, but distinguish native coverage from rows completed using our own value. Imputation does not become independent corroboration.
24. **Analyze Trade should be actionable but not falsely certain:** the final decision contract may say MAKE / LEAN MAKE / TOO CLOSE / LEAN PASS / PASS and must include confidence, strongest reasons for/against, and material uncertainty/disagreement.
25. **No signal double counting in Analyze Trade:** canonical value, the external sources contributing to that value, Monte Carlo centered on that value, KTC VA, and roster analyses that reuse that value are related descendants, not five independent votes. Synthesize by unique information/lineage rather than naïvely weighting every visible panel.
26. **Roster marginal impact is the major genuinely incremental trade dimension:** when the canonical before→apply→rerank→after Team Strength/Weakness architecture is ready, use promotions/displacements and needs changes as separate roster information rather than simply subtracting outgoing player value.
27. **One canonical trade-decision owner:** the `/trade` Analyze action and future CE-05 Trade Desk must consume the same decision contract; do not create separate recommendation formulas per page.
28. **Do not claim we already have a superior proprietary Value Adjustment:** the current exact KTC VA implementation is the trusted market-parity/consolidation benchmark. The separate site-specific canonical package methodology is not yet a proven replacement scalar and must not be described as "better than KTC" without evidence.
29. **Keep KTC VA, do not throw it away:** the owner explicitly values KTC's adjustment and wants it preserved. Future canonical package/roster methodology should be compared against KTC and can use KTC as a market benchmark/reference, while remaining methodologically separate. Do not silently alter KTC's non-monotonic behavior in KTC-parity mode.
30. **Do not invent an 'Our VA' merely to have one:** first determine whether the canonical product even needs a second scalar value-adjustment number. A preferred architecture may be canonical raw/package equity + exact KTC VA as the market consolidation lens + separate canonical roster marginal impact. Only introduce a proprietary scalar package premium if a clearly defined target and validation show it adds information.
31. **Any future proprietary package adjustment must earn its place:** if proposed, define the target, test common trade topologies (1-for-1, 2-for-1, 3-for-1, picks, elite consolidation, offense/IDP), benchmark against KTC and contemporaneous market/trade evidence, test monotonicity and pathological cases, and avoid temporal leakage or tuning until examples merely "look right."
32. **Dynasty Daddy competitive scope is approved but canonical-first:** CE-17–CE-21 and the recorded feature enrichments remain required future scope, but must extend existing owners rather than create separate competitor-copy engines.

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

### Trade decision synthesis scope summary

The authoritative design is in `docs/trade/TRADE_DECISION_SYNTHESIS_PLAN_2026-08-11.md` and issues #790-#792. The eventual Analyze Trade layer should reason over **unique-information dimensions** rather than over raw UI panels:

- canonical asset/package equity;
- independent market corroboration/disagreement with coverage and lineage;
- revalidated uncertainty/risk from Monte Carlo or its successor;
- canonical roster marginal impact (Team Strength/Weakness, promotions/displacements, construction);
- validated future/window context;
- later real trade comps, Sharp/Insider/Consensus/news/manager context only when genuinely incremental;
- explicit owner constraints/untouchables where applicable.

### Execution ordering

Do not mix these unrelated UI/auth/product requirements into the currently isolated B2 IDP curve-routing root-cause work. Immediate defects (#779-#781) should be picked up at the next safe product-hotfix checkpoint unless one blocks required verification. #782-#786 are approved scope but must enter their natural dependency checkpoints rather than interrupt B2. CE-20/#789 must enter the master dependency plan and should begin only after scoring correctness, canonical best-ball assignment, projection-source/custom-stat modeling and prediction-history foundations are ready. #790 should be audited at the next appropriate trade/model checkpoint; #791 is a small UX addition but should still avoid interrupting B2; #792 is dependency-gated until canonical value/package/Team Strength/Weakness/roster-impact foundations are trustworthy. CE-17–CE-21 remain future competitive expansion after their dependencies. #788 stays long-term/cost-gated.
