# Owner-Requested To-Do List

**Status:** ACTIVE — **THE LIVE OWNER INTAKE LEDGER** (reclassified 2026-08-14 by the post-B master
reconciliation). New owner instructions land here first and are durable the moment they are written.

> This file was previously listed as historical/superseded while carrying **65 binding owner decisions**,
> including the two newest sets in the repository (#829 decisions 47–55, #830 decisions 56–65, both
> 2026-08-14). The governance index was telling readers not to trust the file where the newest owner intent
> lived. That inversion is fixed: see `docs/PLANNING_DOCUMENT_STATUS.md` §2 for the intake → canonical record
> → manifest row → authorization workflow, which `scripts/check_planning_integrity.py` enforces in CI.
>
> **Recording an instruction here does not authorize building it.** Only `docs/EXECUTION_PLAN.md` does that.
> Every numbered decision below is mapped in `docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md` §C.

This file is the durable repository record for owner-requested live defects, UX requirements, planned products, and explicitly deferred long-term ideas that must not be lost between implementation phases or coding sessions. Items remain open until the linked issue is actually reproduced/researched, implemented where authorized, validated, and closed.

## Added 2026-08-11

*(Rows #829 and #830 and binding decisions 47–65 were added 2026-08-14 under this same heading.)*

| Priority | Issue | Area | Required outcome | Status |
|---|---|---|---|---|
| P0/P1 live defect | #779 | Admin | Fix `/admin` client-side crash: `Can't find variable: fmtPassExpiry`; reproduce on the real page, RED→GREEN it, and verify the mobile/browser path. | TODO |
| P1 owner workflow | #780 | Admin / auth | Repair and verify the existing temporary-password/pass generator. Owner must be able to choose the validity duration in hours, generate a credential that actually works, and have expiry/revocation fail closed. Do not create a duplicate auth system. | TODO |
| P1 owner UX requirement | #781 | Trade Calculator | Keep manual player-value edits visually silent: no yellow highlight, badge, marker, or visible per-player override-reset affordance. Add a discreet top-level **Reset Values** control; removing an edited player must clear that temporary override so re-adding restores the canonical/original value. Temporary edits must not mutate canonical value truth. | TODO |
| Planned intelligence / staged | #782 | YouTube dynasty intelligence | Build a reputable dynasty-YouTube intelligence pipeline, targeting roughly 50 high-quality sources while deduping any YouTube representation already covered by Podcast Intelligence. Reuse canonical analyst/source identity, transcript/take extraction, independence and provenance, and feed appropriate outputs into Consensus Edge, player intelligence, Buy/Sell, selected-team intelligence and the personalized weekly team podcast/brief. **Transcript storage and active-signal freshness are separate:** retain source material/provenance, but make extracted takes event-aware, season-aware, type-aware, decaying/expiring signals so stale pregame, injury, role and usage opinions cannot keep voting after newer games/news supersede them. | PLANNED |
| Planned product / staged | #783 | Universal Player Profile / intelligence | Add one canonical player-specific intelligence/news feed combining Podcast Intelligence, future YouTube Intelligence and canonical fantasy-news pools such as Sleeper, RotoWire, RotoBaller and other ingested sources. Preserve fact vs opinion, provenance, freshness and dedupe; use concise attributed excerpts, summaries or a hybrid rather than raw copyrighted duplication. | PLANNED |
| P1 owner UX / market intelligence | #784 | Homepage / Consensus Edge | Make the homepage stock-market-style buy/sell ticker consume canonical Buy/Sell/Consensus output. BUY items may be global; **SELL items must only be players rostered by the selected fantasy team**. The ticker is presentation, never a second signal algorithm. | TODO |
| P1 methodology audit | #785 | Tight-end premium / valuation | Deep-audit the exact two-TE/TE-premium methodology against real league settings and every source's TE basis. Measure standard→TEP/TE++ uplift curves where available, prevent double counting, search out stale blanket multipliers such as legacy `1.15`, and validate TE values versus cross-position scoring/scarcity evidence rather than merely forcing parity with KTC. | TODO |
| Planned trade UX / methodology | #786 | Trade Simulator / NFL-team exposure | Add **value-weighted NFL-team exposure before vs after** a proposed trade, with raw counts secondary. Informational only: it must not affect trade grade/recommendation unless separately authorized. Reuse the same canonical exposure primitive as CE-06 Portfolio. | PLANNED |
| Future / cost-gated | #788 | Analyst intelligence / X | Preserve a future ~500-analyst Dynasty X feed using the official API only, with reputation-based curation and cross-media dedupe. Do **not** build while recurring API cost is disproportionate to the site's size/value; re-evaluate economics and policy later. | LONG-TERM |
| Planned product / dependency-gated | #789 | CE-20 Game Day Command Center | Build a Sunday companion that models this league's **exact custom scoring and best-ball lineup semantics**, with calibrated pregame/live final-score projections, best-ball-aware win probability, personalized matchup/event/news context, rooting/leverage guidance, mobile + desktop/TV UX, and a low-cost V1 that does not require paid real-time play-by-play. | PLANNED |
| P1 methodology audit | #790 | Trade Calculator / Monte Carlo | Re-audit current-HEAD Monte Carlo end to end: canonical center values, TEP/IDP/pick/override propagation, uncertainty bands, package adjustment, correlations, symmetry/convergence/provenance, and the exact meaning of its win percentage. | TODO |
| P1 owner UX | #791 | Trade Calculator / Second Opinions | Add an immediate independent-vendor tally such as **Side A 5 · Side B 3 · Even 1 · 2 incomplete**, without counting canonical-value imputation as an independent external vote. | TODO |
| Planned decision product / dependency-gated | #792 | Trade Calculator / CE-05 Trade Desk | Add one canonical **Analyze Trade** recommendation that synthesizes unique-information dimensions into MAKE / LEAN MAKE / TOO CLOSE / LEAN PASS / PASS with confidence and reasons, without double-counting overlapping source/value signals. | PLANNED |
| P1 live trade correctness | #800 | Trade Calculator / equalizer suggestions | When the calculator suggests a player/asset from a team to make a trade even, rank candidates by the **post-Value-Adjustment** gap produced by the same active package/VA math the calculator displays. Do not compare only raw sums, do not double-apply VA, and preserve picks, IDP/TEP, temporary overrides and side symmetry. | TODO |
| Future paid source / owner-paused | #801 | Rankings / Establish The Run | Preserve the researched ETR Dynasty SF/TEP source plan, but **do not purchase access, implement the source, or spend additional work on it until the owner explicitly resumes it**. If resumed, use one ETR dynasty lineage, authorized paid access, native SF/TEP semantics, provenance, and pre-production board-impact validation. | PAUSED |
| P0/P1 scoring correctness | #802 | League scoring / individual special teams | Fix player-level special-teams scoring so `kr_yd`, `pr_yd`, and supported `st_*` categories are credited to the actual RB/WR/DB/etc. rather than incorrectly treated as non-player DST scoring. Distinguish player ST from `def_*` DST keys, source historical return/ST data, preserve explicit UNSCORABLE/MISSING states, and rerun 2025 realized-points/league-adjusted backtests. | TODO |
| P1 valuation methodology | #803 | League-specific player fit / college translation | Complete validated **player-specific** league-scoring fit from historical NFL performance versus a versioned standard-market baseline, then investigate college/prospect translation from the same statistical profile—including kick/punt return production—without directly converting raw college fantasy points into dynasty value. Use stability/shrinkage/OOS validation, separate scoring fit from scarcity/market value, and preserve provenance/confidence. | TODO |
| Planned product / cost-control | #829 | Weekly Report Studio / pregame + postgame + graphics | Make **Manual External AI** the default weekly-report generation path: site prepares one complete deterministic pregame or postgame package, owner copies it into ChatGPT/Claude, imports the versioned structured response, validates/previews, then publishes. No manual report writing and **zero site-side LLM/API calls** in the default mode. Preserve optional explicit On-Demand API and disabled-by-default Automatic API modes through the same schema/validator/renderer. Weekly graphics use deterministic Premium Sports Intelligence templates rather than routine generative-image calls. Detailed binding design: `docs/WEEKLY_REPORT_STUDIO_MANUAL_AI_ARCHITECTURE_2026-08-14.md`. | PLANNED |
| Planned FAAB market intelligence / audit | #830 | FAAB / Waivers / CE-19 | Extend the **existing canonical FAAB market layer** with bounded Sleeper Most Added/Most Dropped `Market Heat`, normalized external/Sharp-league winning-bid evidence, and strict percent-of-original-budget normalization. Own-league, Sharp-league, broad-market and platform-trending populations remain distinct; all comparable bids can be rendered on the current $100 scale. Do not create another FAAB formula or let popularity alter objective player worth. Detailed binding design: `docs/FAAB_MARKET_SIGNAL_NORMALIZATION_2026-08-14.md`. | PLANNED |
| P1 methodology / C-Series calibration | Owner 2026-08-15 | Math / decision models | Fold the binding `docs/MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md` into the detailed C-Series decomposition: calibrate future-pick discount/distributions in C1; lineup/replacement-aware Team Strength, meaningful-core multiplier challengers and position-relative Young Core math in C2; scale-aware internal trade fairness, true roster-impact consolidation and empirical Monte Carlo uncertainty/correlation in C3; preserve exact KTC VA and the current five-axis confidence architecture; validate TE-demand mapping under #785; require a C10 census of surviving numerical priors. **Do not overhaul the canonical consensus board without a proven challenger.** | PLANNED |
| Planned projection intelligence / C5 | #854 | Weekly / ROS / season projections | Build the binding multi-source projection ensemble in `docs/PROJECTION_ENSEMBLE_PLAN_2026-08-15.md`: collect multiple genuinely independent projection/model families across weekly, ROS and full-season horizons; target CBS, NFL Fantasy, FantasyPros, DraftSharks and Mike Clay/ESPN for offense plus IDP Show, FantasyPros and DraftSharks for IDP; treat CBS/NFL Fantasy/FantasyPros/DraftSharks permission as owner-reported, verify the exact technical path, and verify subscription/automation rights for IDP Show and the Mike Clay/ESPN path; prefer raw projected football stats and rescore them through exact league scoring; preserve ancestry so consensus products cannot double-count constituent models; archive forecasts before outcomes; backtest family-level mean/median/robust ensembles before learned weighting; keep all seasonal projection evidence separate from canonical dynasty value. Primary C-Series home: `C5-ROS-01`, with C1 history/provenance dependencies and downstream Game Day/Playoff/Power/Pick Forecast/Lineup/Profile consumers. | PLANNED |
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
16. **Exact league scoring is required:** weekly/live projections must translate projected football outcomes into this league's complete scoring system. Unprojected scoring components such as first downs, reception-distance/big-play bands, return yards, or complex IDP/special-teams events must be estimated with defensible historical/conditional models or remain explicitly uncertain; they must not silently become zero.
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
33. **Transcript retention is not signal validity:** Podcast/YouTube transcripts, metadata and provenance may be retained for historical intelligence, auditing and player-profile context, but episode age alone must never determine whether a take is still allowed to influence Consensus Edge or another current recommendation surface.
34. **Freshness is take-type-aware:** extracted takes must be classified (injury/availability, role/depth-chart, game-specific projection, postgame usage, current buy/sell/value take, durable dynasty thesis, historical/background) and receive an appropriate decay/expiry policy instead of one universal seven-day TTL.
35. **Freshness is event-aware:** a material game, injury update, transaction, depth-chart change, inactive/active decision or other assumption-breaking event can invalidate or sharply downweight a take immediately even if the transcript is only hours old. Pregame and matchup-specific takes expire at the relevant kickoff/game boundary rather than surviving because they are still inside a calendar window.
36. **No universal Sunday/Monday reset:** freshness boundaries should follow the affected player's/team's actual event timeline and next/most-recent game, not a league-wide weekly reset. A Monday-night player's pregame information must not be expired Sunday night merely because another team's week is complete.
37. **Season-aware volatility modes:** use faster decay during high-volatility periods (regular season/playoffs, training camp/preseason, roster cuts, free-agency opening, NFL Draft/immediate aftermath), moderate decay during normal active offseason periods, and slower decay during genuinely quiet offseason periods.
38. **Freshness modifies a signal; it is not another vote:** Consensus Edge should apply freshness/supersession after canonical identity, dedupe and independence resolution. The same analyst repeating the same thesis across podcast, YouTube, clips or syndicated appearances is one lineage, not multiple votes, and freshness must not multiply duplicated signal.
39. **Older intelligence can remain visible without voting:** Universal Player Profile and historical/research views may surface older useful analysis as `Recent Analysis` or `History` after it stops contributing to current Consensus Edge. Personalized team podcasts/briefs should prioritize active intelligence while using older theses only as clearly labeled background.
40. **Discovery window and voting window are separate:** a roughly seven-day retrieval/discovery window is a reasonable regular-season starting point for finding podcast/YouTube episodes, with wider windows during quieter offseason periods, but retrieval eligibility must not grant seven days of voting rights to every extracted take.
41. **Trade equalizer suggestions must use the active Value Adjustment:** when the calculator offers a player/asset to make the trade even, candidate ranking must minimize the gap **after** the same active KTC-style Value Adjustment/package math used by the calculator. Raw-value closeness is not sufficient, and the adjustment must not be applied twice.
42. **Establish The Run is paused by owner:** preserve the research and authorized-acquisition notes, but do not buy Pro access, implement the source, or continue work on #801 until the owner explicitly resumes it.
43. **Player special-teams production is real asset scoring:** `kr_yd`, `pr_yd`, and supported individual `st_*` events belong to actual rostered players and must not be discarded as non-tradeable DST scoring. Keep `def_*` team-defense special teams separate.
44. **League-specific player fit must become genuinely player-specific where evidence supports it:** score historical player performance under both this league and a transparent/versioned standard-market baseline, isolate stable differential fit from generic position generosity, and use sample-size/stability/shrinkage/forward-validation guards. Do not manufacture a per-player multiplier where the data says only a position-level effect is trustworthy.
45. **College production is a prospect scoring-style signal, not direct dynasty value:** for prospects, score the same college production under standard and Brisket rules—including returns when available—to measure profile fit, but only promote that signal if historical drafted-player cohorts show it transfers to NFL league-fit or future production without temporal leakage.
46. **Keep value lineages separate:** generic dynasty market value, Superflex/roster scarcity, exact league-scoring fit, college/prospect fit, scouting/draft capital and later roster marginal impact are related inputs with different meanings; do not collapse or double-count them as independent votes.
47. **Weekly Report Studio defaults to Manual External AI:** preparing an eligible week must not automatically call an LLM. The default path is deterministic package preparation -> external AI generation by the owner -> structured import -> validation -> preview -> publish.
48. **No manual report writing is required:** the manual part is only triggering/copying/importing the AI generation; the owner should not have to compose the prose.
49. **Manual External AI means zero site-side AI credits:** while that mode is selected, no report scheduler, readiness event, background job, or page action other than an explicitly selected API mode may invoke a paid site-side LLM.
50. **One logical generation per stage:** a full eligible week should normally be represented by one pregame package and one postgame package, not six separate matchup workflows. Deterministic chunking is allowed only when provider context limits require it.
51. **Provider-neutral structured import is mandatory:** ChatGPT, Claude, or another external provider should return the same versioned report schema. Wrong-week, wrong-stage, malformed, duplicate, or unsafe imports fail closed before publication.
52. **All generation modes share one pipeline:** optional On-Demand API and future Automatic API must use the same canonical data package, structured output schema, validator, preview, renderer, and publish path as Manual External AI; API modes may not become parallel report engines.
53. **Automatic API is disabled by default:** scheduled generation and recurring credit spend require an explicit later owner enablement. Report eligibility alone is never authorization to spend AI credits.
54. **Routine weekly graphics are deterministic templates, not generative images:** use the Premium Sports Intelligence/share-rendering system for layout and branding; AI may provide bounded headline/subheadline/storyline/caption fields only.
55. **AI narrates canonical facts; it does not own league truth:** standings, scores, projections, best-ball/custom-scoring outputs, rivalry/history, playoff context and other facts come from canonical site owners. Imported narrative copy cannot mutate canonical factual state.
56. **FAAB normalization uses original starting budget:** every own-league or external observed bid must first be expressed as a percentage of that league/season's original FAAB budget, then may be translated to the current Brisket $100 scale for display/comparison. Remaining manager balance is never the normalization denominator.
57. **Preserve historical budget reality:** the current history code already records this league at $1,000 in 2024, $200 in 2025 and $100 in 2026; preserve percentage-equivalent semantics across those seasons instead of comparing raw dollars.
58. **Zero FAAB bids are real; missing budgets are not:** a completed $0 bid remains a valid 0% observation. An unknown original starting budget is unavailable/not comparable and must not silently default to $100 for external-market normalization.
59. **Sleeper Most Added is acquisition pressure, not player worth:** use add volume/velocity/acceleration as bounded evidence that competition may be increasing. It may affect recommended bid / clearing-price estimates only and must never raise canonical value or objective FAAB ceiling.
60. **Sleeper Most Dropped is weaker/asymmetric context:** broad drops are noisy across redraft, shallow rosters, byes, injuries and format differences. Give drop activity materially less negative power than add activity and prefer explanatory warnings over automatic bid cuts.
61. **Market Heat stays bounded and evidence-gated:** an initial design target is roughly no more than ~10% upward movement in the pre-heat recommended bid from Sleeper heat alone absent validation supporting more. The exact production transform must be backtested; no unbounded multiplier stack may return.
62. **External and Sharp-league FAAB may be used:** where completed bid data and trustworthy original budget/settings are available, ingest normalized observations from eligible external Sleeper leagues, including the existing Sharp cohort, through CE-19 / the canonical market layer.
63. **Own league, Sharps, broad market and platform trends remain separate populations:** do not silently pool or double-count them. Own-league bidding culture is most directly relevant; Sharp behavior is a distinct curated lens; broad market provides scale; Sleeper trending measures attention rather than clearing price.
64. **Budget normalization is necessary but not sufficient for comparability:** external evidence must preserve/consider dynasty vs redraft, SF/1QB, TEP/two-TE, IDP, team count, roster depth, waiver rules and season timing. Sharp status does not override a material format mismatch.
65. **One FAAB owner / one waiver-market ledger:** #830 extends the current FAAB engine and CE-19. It must not create a second recommender, frontend multiplier, separate Sharp-FAAB formula or duplicate market database.

### Podcast / YouTube intelligence freshness and expiration policy

The eventual shared Podcast + YouTube intelligence owner must implement freshness at the **extracted-take level**, not by deleting or blindly ignoring whole transcripts after a fixed number of days.

Recommended starting defaults (subject to later backtesting/calibration):

| Take type | Regular season / playoffs | Quiet offseason | Required event behavior |
|---|---:|---:|---|
| Injury / availability / active-status | ~6–24 hours | ~2–5 days | Supersede immediately on newer official/credible status change; game-specific status expires at the relevant game boundary. |
| Depth-chart / role change | ~2–4 days | ~7–14 days | Re-evaluate after a game, transaction, practice-role change or newer depth-chart evidence. |
| Upcoming-game matchup / start-sit | Until kickoff | N/A | Hard-expire at kickoff; never remain a current vote after the game starts. |
| Expected workload / usage for a specific game | Through that game only | N/A | Expire when the game ends; postgame usage becomes separate evidence. |
| Postgame snap/share/opportunity reaction | Strongest for ~3 days; normally no later than next game | N/A | Decay quickly as the next practice/injury/game context arrives. |
| Buy/sell/value take driven by current circumstances | ~7 days with decay | ~14–21 days with decay | Can expire earlier when its stated/implicit assumptions are broken. |
| Durable dynasty/player-development thesis | ~10–14 days active | ~30 days active | Slow decay; newer contradictory thesis/evidence may supersede it sooner. |
| Historical/background analysis | Context only | Context only | Never becomes a current Consensus Edge vote solely because it was retrieved. |

Implementation requirements:

- Prefer **decay + hard expiry + supersession**, not hard cutoffs alone.
- Store enough lineage to explain why an old take stopped voting and what superseded it.
- Suggested fields include `publishedAt`, `extractedAt`, `takeType`, `playerId`, `teamId`, `eventAnchor`, `freshnessHalfLife`, `hardExpiry`, `supersededBy`, `assumptions`, `freshnessStatus`, `sourceId`, `analystId`, `contentId`, `network/independenceGroup`, and provenance pointers.
- A material completed game is a major freshness boundary for pregame role, health, workload and matchup assumptions. Postgame evidence should not merely coexist with stale pregame assumptions at equal weight.
- Consensus Edge should conceptually treat the active contribution as something like `source/analyst strength × independence × extraction confidence × freshness × supersession validity`, with lineage preventing duplicated cross-media observations from becoming separate votes.
- Do not silently convert `expired`, `superseded`, `stale` or `insufficiently current` into zero-quality evidence. Preserve the state explicitly for audit/history even when the active vote is removed.
- Player Profile intelligence, news blurbs, team-specific intelligence and the personalized podcast may use older non-voting material as context when clearly labeled; current recommendation surfaces must use only currently valid active intelligence.
- The exact time constants are defaults to validate, not sacred hard-coded truths. The architecture must make them configurable by take type and season/volatility mode so evidence can later refine them without rebuilding ingestion.

### Weekly Report Studio / manual external AI scope summary

The authoritative design is `docs/WEEKLY_REPORT_STUDIO_MANUAL_AI_ARCHITECTURE_2026-08-14.md` and issue #829.

The eventual product must use the canonical flow:

`DATA -> PACKAGE -> EXTERNAL AI -> IMPORT -> VALIDATE -> RENDER -> PUBLISH`

At minimum:

- **Manual External AI is the default** and makes zero site-side LLM/API calls;
- one pregame package can produce the week overview, Game of the Week, all matchup previews, players/storylines to watch, public-safe standings/playoff/rivalry context and graphic copy;
- one postgame package can produce the weekly recap, Game of the Week recap, all matchup recaps, superlatives, upset/bad-beat/miracle stories, standings/playoff movement and graphic copy;
- the site precomputes objective facts from canonical owners rather than asking AI to rediscover league truth;
- external output uses a strict versioned provider-neutral structured schema, preferably JSON;
- import validates identity/schema/required IDs/field constraints and fails closed before publication;
- preview and publication are separate; imported drafts cannot partially corrupt the currently published week;
- On-Demand API is optional and explicit; Automatic API is optional, disabled by default, and requires later owner enablement;
- every mode uses the same package/schema/validator/render/publish pipeline;
- weekly graphics are rendered deterministically through the Premium Sports Intelligence/share-rendering system rather than routine generative-image calls;
- existing weekly/narrative/report code must be reconciled and reused where appropriate so this becomes one coherent report system rather than a parallel stack.

### FAAB Market Heat / normalized external market scope summary

The authoritative design is `docs/FAAB_MARKET_SIGNAL_NORMALIZATION_2026-08-14.md` and issue #830.

At minimum:

- preserve the current objective-ceiling vs recommended-bid separation;
- preserve own-league historical normalization to percent of original starting budget;
- translate normalized observations to the current $100 scale only for display/comparison, never by assuming all source leagues started at $100;
- use Sleeper Most Added/add velocity as bounded acquisition-pressure evidence in the market layer only;
- use Most Dropped as weaker contextual evidence;
- extend CE-19 to ingest eligible normalized external winning bids, including Sharp-league observations where transaction/budget/format metadata is trustworthy;
- keep own-league, Sharp, broad-market and Sleeper-trending populations separately identifiable and provenance-rich;
- account for material format mismatch instead of treating budget normalization as full equivalence;
- retain $0 bids and fail closed when the original budget is unknown;
- backtest any new weighting against actual Brisket clearing prices and guard against correlated/double-counted demand signals.

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

### Mathematical / decision-model calibration scope summary — added 2026-08-15

The authoritative design is `docs/MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md`. It is a binding refinement of existing C-Series capabilities, not a new parallel engine.

At minimum:

- classify every consequential tunable as **MEASURED / VALIDATED**, **MECHANICALLY REQUIRED**, or **PRIOR / HEURISTIC**;
- keep the canonical consensus player-value board as champion unless a properly validated challenger wins;
- keep equal weighting of independent source families unless evidence justifies another weighting without overfit;
- C1: empirically calibrate future-pick discounting and preserve owned-pick outcome distributions/uncertainty rather than only point estimates;
- C2: make Team Strength exact-lineup/replacement-aware with diminishing marginal depth, consolidate replacement level, challenger-test the `ceil(1.5 × starter demand)` meaningful-core multiplier, and validate continuous position-relative age curves for Young Core;
- C3: replace fixed raw-point internal fairness thresholds with a scale-aware challenger, preserve exact KTC VA as a separate market lens, judge consolidation through true final-roster marginal impact, and calibrate Monte Carlo uncertainty/correlation from retained history where feasible;
- #785: preserve measured TE source-basis conversion but validate the league-demand-to-TE-basis mapping against starter count, scoring, flex eligibility, scarcity and comparable-market evidence;
- preserve the five-axis confidence bottleneck architecture unless a later evidence-backed challenger specifically beats it;
- C10: perform a full prior census so consequential magic numbers are validated, explicitly retained with bounds, or removed.

### Execution ordering

Do not mix these unrelated UI/auth/product requirements into the currently isolated foundational repair. Immediate defects (#779-#781) should be picked up at the next safe product-hotfix checkpoint unless one blocks required verification. #782-#786 are approved scope but must enter their natural dependency checkpoints. CE-20/#789 must begin only after scoring correctness, canonical best-ball assignment, projection-source/custom-stat modeling and prediction-history foundations are ready. #790 should be audited at the next appropriate trade/model checkpoint; #791 is a small UX addition; #792 is dependency-gated until canonical value/package/Team Strength/Weakness/roster-impact foundations are trustworthy. #800 is a trade-correctness defect for the next safe Trade Calculator checkpoint. **#801 is PAUSED by owner and must not consume spend or engineering time until explicitly resumed. #802 is a scoring-correctness dependency for any exact historical league-scoring claim. #803 follows the canonical scoring/league-configuration foundations and must incorporate #802 before promoting a league-fit signal. #829 belongs at the natural Public League Experience v3 / weekly storytelling / Game Day / share-renderer checkpoint after its canonical weekly data inputs are trustworthy; when that checkpoint begins, Manual External AI is the default and automatic AI-credit spend remains disabled unless the owner later opts in. #830 belongs at the natural FAAB / Waiver Market / CE-19 / Perfect Waivers checkpoint; audit and preserve the already-correct historical normalization and market-layer trending behavior first, then extend external/Sharp market evidence through the same canonical owner.** The 2026-08-15 mathematical calibration policy must be folded into the detailed C-Series unit map before implementation progresses beyond the currently authorized foundational retention work, but it does **not** itself authorize any later C unit. #854 belongs in the detailed C5 seasonal/projection decomposition under `C5-ROS-01`, with source/lineage/schema/archive work scheduled before Game Day and other projection consumers; its archival capture should begin as early as safely authorized because pre-event forecasts are perishable evidence. CE-17–CE-21 remain future competitive expansion after their dependencies. #788 stays long-term/cost-gated.