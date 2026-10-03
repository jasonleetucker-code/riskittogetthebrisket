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


## #1338 expanded performance mandate — owner, 2026-09-26

**Critical-path refinement (2026-09-27):** remain on Rankings/Trade until production
useful-state acceptance passes. Verify #1500 deployment, identify the exact owner
of Rankings' measured 3.20 MB supporting transfer, remove or defer unnecessary
initial bytes/work with semantic parity, and remeasure. Prioritize cold Rankings:
at most five seconds, preferably three; warm one–two seconds, with Trade staying
green. Preserve the stricter existing global acceptance targets and report each
separately rather than converting an intermediate milestone into final acceptance.
Lock demonstrated gains with regression guards before the remaining-route sweep.
No new instrumentation unless existing measurements cannot distinguish the next
owner; no broader campaign work before the first route pair passes.

**Closure priority amendment (2026-09-26):** merge the already-reviewed PR train
as exact-head gates pass. Use the existing measurement framework to fix the largest
measured user-visible owner first: production Rankings/Trade useful state and its
8–14 MB aggregate decoded resource total. That total is not yet an isolated API
payload measurement. Stop expanding diagnostic infrastructure and adjacent source
or operations investigations unless they directly block performance acceptance or
production correctness. Remeasure each material correction, then sweep the remaining
route denominator, fix material failures, complete production/adversarial acceptance
and reconcile #1338. Preserve correctness without an unbounded subsystem audit.

The named performance requirements are a minimum, not an exhaustive checklist.
Actively search the current system for material opportunities across request and
Next.js architecture, Python/JS compute, event-loop/process contention, memory/GC,
serialization/compression, files/SQLite/indexes, algorithms and redundant work,
payloads/HTTP/caches/connections/concurrency, source scheduling/freshness/invalidation,
browser networking/bundles/hydration/rendering/layout/assets/prefetch, auth/settings
waterfalls, background interference, deployment/nginx, observability and regression.
Rank work by user-visible delay × frequency × affected users/routes × severity ×
implementation leverage. Measure → identify owner/materiality → smallest correct
change → prove semantics → before/after measurement → independent review → retain
only demonstrated improvements. Do not pursue insignificant microbenchmarks ahead
of larger user-visible bottlenecks or sacrifice correctness, maintainability,
security or product quality.

After known failures are fixed, a required independent adversarial hunt must find
and resolve worthwhile remaining inefficiencies, or substantiate why residual costs
are negligible, inherent, externally constrained or not worth added complexity.
Production proof and durable regression protection remain mandatory. Existing
#1338 authorization and global budgets are unchanged; execution and evidence live
in `EXECUTION_PLAN.md` §0 and `performance/CURRENT_ARCHITECTURE.md`.

## Permanent parallel Premium UI / locked PSI — owner directive 2026-09-24

**New performance authorization (2026-09-26, #1338).** Finish Calculator's current
performance architecture under `GLOBAL_PERFORMANCE_STANDARD.md`, through protected
implementation, review, merge, deploy and production verification. Current main is
the baseline; #1346 is closed and remains a donor only. Fresh route/POST census and
measurements precede implementation choices. Preserve canonical answers, complete
cache identities, league/scoring and public/private boundaries, freshness/LKG, PSI
UI and the global useful-state budgets. Repair measured server/browser/resource
owners, add durable regression guards, and accept every important current route on
production-shaped desktop/mobile evidence. Do not close #1338 for documentation or
local green. Authorization is recorded in `EXECUTION_PLAN.md` §0; current evidence
and the release sequence live in `performance/CURRENT_ARCHITECTURE.md`. This
supersedes the historical donor record's future-authorization blocker, without
promoting any historical benchmark or restarting the abandoned serving branch.

Binding owner instruction #1421 is incorporated in `docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md`; queue/evidence:
`docs/ui/UI_PARALLEL_LEDGER.md`. This is the live intake pointer, not a second ledger. Existing Lane 6 /
C8-U1/U2/U3 stays active in parallel until genuine UI/product completion. Every substantial
Calculator Ideas batch includes useful UI or names adequate active coverage. A route's
unstable contract blocks its final integration, never all UI. Locked Direction A,
semantic DS/reference reuse, mobile parity, honest data, a11y/performance, desktop/phone
and production proof apply. Backend complete / UI incomplete is product incomplete.

The owner authorizes this bounded governance/enforcement reconciliation and continuation
of already-approved safe UI; `docs/EXECUTION_PLAN.md` records current authority. No
unrelated scope, model/serving activation or denominator change. First safe unit: #1422
`/design`, separate `codex/psi-design-reference` branch/claim; exact dispatch in
`docs/ui/PSI_DESIGN_REFERENCE_HANDOFF.md`. Queued is not running. Integration reconciles
#1416/#1419/#1344 without discarding their work. No deployment/completion is asserted.

## Calculator Ideas shorthand and intake discipline — owner decision 2026-09-24

**Friendly owner-facing name:** **Calculator Ideas**. When the owner says “add this to Calculator Ideas,” “put this on the Calculator list,” “save this idea,” or equivalent durable wording, it routes to this live intake ledger. The owner does not need to choose a repository document.

The operating front door is `docs/BRISKET_IDEAS.md` (issue #1412). It creates **no second backlog** and no implementation authority. It standardizes how new material requests are reconciled:

- dedupe/supersede before creating a new record;
- identify the canonical owner and shared foundation;
- name dependencies and overlap;
- classify planning position **NOW / NEXT / LATER / BLOCKED** (plus PAUSED / DONE / REJECTED where applicable);
- classify safe concurrency as **SAFE_PARALLEL / SERIAL_CANONICAL_OWNER / INTEGRATION_ONLY / DEPENDENCY_BLOCKED**;
- perform a lightweight same-session portfolio check so a new idea is placed coherently rather than appended as an isolated issue;
- prefer one shared foundation that unlocks several requirements over parallel feature-local implementations;
- keep readiness separate from authority: **only `docs/EXECUTION_PLAN.md` authorizes implementation**.

Existing historical rows/status vocabulary are preserved. Normalize an older item when it is next materially reconciled; do not mass-rewrite history merely for naming consistency.

**Durable record:** issue #1412 and `docs/BRISKET_IDEAS.md`. This process instruction is active immediately and does not itself authorize any feature build.

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

## Added 2026-08-17 — continuous C-Series campaign directive

| Priority | Issue | Area | Required outcome | Status |
|---|---|---|---|---|
| P0 execution authorization | Owner 2026-08-17 | C-Series execution model | Execute the remaining C-Series continuously, C0→C10 in dependency order. **Routine per-unit stop-and-wait owner checkpoints are superseded.** Per-unit branches and PRs; a unit reaching RED→GREEN + exact-head CI + evidence + retired duplicates + a named production checklist becomes `CLOSED-PENDING-PROD`, joins an ordered merge queue, and work continues immediately on the next dependency-eligible unit or an approved parallel-safe lane. Stop and ask only for a genuine unresolved owner decision, required external authorization, paid-API permission, owner-held credentials, an irreversible destructive operation, or a merge that blocks every legitimate lane. Recorded in `docs/EXECUTION_PLAN.md` §0; scope reconciliation in `docs/C_SERIES_DIRECTIVE_RECONCILIATION_2026-08-17.md`. | IN PROGRESS |

### Binding owner decisions — 2026-08-17

66. **`CLOSED-PENDING-PROD` is not closure.** It is an intermediate implementation-complete state that authorizes continuing to the next unit and nothing more. A unit is fully `CLOSED` only after its production verification succeeds **against the deployed merge SHA**. C10 may not count pending units as closed, and the reserved completion phrase may not be used while any required production proof is outstanding. PR-head CI is necessary and is not a substitute.
67. **The meaningful-roster-core provenance is settled.** Addendum #839 (2026-08-14) is an explicit later owner decision that names and replaces the fixed `QB3/RB3/WR5/TE3/DL5/LB5/DB5` caps. `ceil(1.5 × real starter demand)` is the V1 production champion, **labelled PRIOR, not empirically discovered truth**, and carries the 1.25× / 1.50× / 1.75× / data-derived challenger pass before it may be frozen. No challenger displaces it without pinned inputs, leakage-safe validation, champion/challenger comparison and an explicit owner decision.
68. **FLEX is a separate supplement, per T-NEW-19.** Superflex is folded into QB demand *before* the 1.5×, and is never treated as ordinary RB/WR/TE FLEX; regular offensive and IDP FLEX each create `ceil(1.5 × real flex slots)`, filled from the highest-valued remaining legally eligible players; each player is counted at most once. **ORDERING AMENDED 2026-08-18 — see decision 72 (#899): the "after the dedicated cores" clause is superseded.** Actual FLEX starters are assigned as part of the starting lineup and removed from the pools *before* any reserve/depth selection.
69. **Total Asset Value, Meaningful Roster Strength, Exact Starting Lineup, Depth Value, Power Ranking, Playoff Probability and Championship Probability stay distinct** in the model and the UI. They may not be collapsed into one generic team score.
70. **KTC Value Adjustment consolidates onto the repository's validated verbatim `processV` port**, not onto the older V12 regression-fit approximation whose constants the directive quotes. Freeze a fixture corpus first, prove `VA_before == VA_after` where semantics are unchanged, retire the stale kernels/deprecated route/wrappers/import-time monkeypatch where safe, and record why V12 was not selected. KTC VA stays a named external-market lens; alternative package formulas stay separately labelled challengers.
71. **`X-02` and `X-07` remain OWNER-REJECTED** — Money/dues ledger, Constitution and League Media; and general "link any Sleeper account" onboarding. They are not to be reintroduced from restated boilerplate, and not relitigated unless the owner explicitly reverses the decision.

72. **FLEX starters are assigned before Team Strength reserve depth (#899, 2026-08-18).** FLEX is an
    **assignment rule** deciding which players belong to the meaningful-roster value pool — it is **not** a
    separate sortable Team Strength position, and no FLEX column is required (sortable groups stay QB / RB / WR /
    TE / DL / LB / DB). Canonical order: solve the **actual starting lineup** from real league configuration →
    assign dedicated starters → fill each actual FLEX / Superflex / IDP-FLEX starter slot from the
    **highest-valued remaining legally eligible players** → **remove every actual starter** → only then compute
    reserve demand. Reserve demand is `ceil(M × dedicated starter slots) − dedicated starter slots` per dedicated
    position and `ceil(M × actual FLEX starter slots) − actual FLEX starter slots` for FLEX, selected globally
    from what remains. `M` stays the **1.5× V1 champion/PRIOR** with its challenger pass — this decision changes
    *when* a player leaves the pool, not the multiplier. A player used at FLEX **cannot** also count as
    native-position depth; every player counts **at most once**. Implement by reusing the canonical exact
    lineup/assignment machinery (`src/ros/lineup.py`), never independent per-position greedy lists. Supersedes the
    "after the dedicated cores" ordering in decision 68 and T-NEW-19. Canonical record:
    `docs/OWNER_FEATURE_ADDENDUM_2026-08-18_FLEX_STARTER_ASSIGNMENT.md`. Tracking/specification only — it does not
    by itself authorize forward C2 implementation.
73. **Hill-curve champion v2 stays for the 2026 season launch (Owner, 2026-09-03).** Do not promote v5
    merely because its offense holdout criterion is better. The owner accepts the measured conclusion in
    `docs/valuation/HILL_CHALLENGER_PROMOTION_ADJUDICATION_2026-08-25.md`: v2 remains the production champion;
    v5 lacks adequate independent validation for the scopes it would change (GLOBAL/IDP ride no OFFENSE-only
    holdout); no override of GLOBAL or IDP validation is authorized; no Hill constant changes merely to close V1.
    V1's bar for `V1-22` is *"a stable, governed, measured Hill-curve champion exists, inadequate challengers
    fail closed, model provenance is explicit, and promotion requires appropriate evidence"* — not proof v2 is
    the mathematically perfect long-term curve. Preserve the challenger registry, the promotion/refusal
    governance gate (`ModelRegistry.promote()`), and existing evidence. Further Hill-curve calibration,
    challenger research and any future promotion are V2/season follow-up work, **re-evaluated after NFL Week 3
    of the 2026 season is complete** using real early-2026 evidence — not before, absent a real production
    defect, and the outcome (keep / recalibrate / promote a challenger / per-scope champions / new validation
    methodology) is not pre-decided.
74. **Admin Guest Access / temporary-password production-admin verification moves to V2 (Owner, 2026-09-03).**
    `V1-101` (`/admin` `fmtPassExpiry` crash repair) and `V1-102` (temporary-password generator, configurable
    expiry) may remain in production as implemented — this is not a request to delete or disable either
    feature. The implementation for both is complete and real (`frontend/lib/guest-pass-format.js`,
    `src/api/guest_passes.py`); only final **L4** production-admin verification (one authenticated `/admin`
    session exercising each surface on a deployed SHA) remains outstanding, and no session in this program has
    had the credentials/access to perform it. That verification is not a season-launch blocker. Carry the exact
    outstanding recipe into V2 rather than silently dropping it; do not mark either row `VERIFIED` on this
    decision. Full record: `docs/VERSION_1_COMPLETION_CONTRACT.md` §4.4.
75. **Future-state verification policy (Owner, 2026-09-03).** A V1-required capability whose implementation is
    complete and carries no known actionable defect may move into explicit V2/season verification debt — never
    `VERIFIED`, and never silently dropped — when ALL of: (1) the required implementation already exists; (2)
    there is no known actionable product defect; (3) every verification possible in the current real-world
    state has already been executed; (4) the only remaining evidence depends on a future natural event or
    future production state that does not exist yet; (5) satisfying the remaining proof today would require
    fabrication, synthetic production evidence, or pretending an unavailable state is valid; (6) the exact
    deferred proof is preserved, with a named recheck trigger, rather than deleted. This is not permission to
    hide an actionable defect — fix a real one before deferring. Applied 2026-09-03 to `V1-49` (item 4:
    historical backtests of the `host_native_scoring` challenger need real 2026 in-season Sleeper stats, which
    do not exist pre-Week-1 — item 3, the authenticated-access question, was actively closed with new evidence
    first, per this policy's own instruction to fix an actionable gap before deferring) and `V1-83` (alert
    cooldown: an on-box production check already found the real `ops_alerts` state empty — no category has
    fired since the fix deployed, so there is nothing yet to measure in either direction). Full record and
    triggers: `docs/VERSION_1_COMPLETION_CONTRACT.md` §4.4.
76. **These three decisions (73-75) were authorized directly by the owner in a 2026-09-03 session directive
    and are durable as of that date**, independent of any later automated Integration/traffic-control pass that
    has not seen this ledger entry. A subsequent process asserting the V1 denominator must stay at its
    pre-2026-09-03 value, or that these reclassifications lack authorization, is working from a stale premise —
    check this entry's date before treating such an assertion as a new owner decision.

## Added 2026-09-10 — two-month owner-intent recovery bridge

**Purpose:** make every recoverable durable owner request discoverable from this one live intake ledger without duplicating the long-form contracts that already exist elsewhere. This section is an index/bridge and status snapshot, not a second roadmap. Detailed specs/issues remain authoritative for their own requirement details. **Nothing in this recovery bridge authorizes implementation; `docs/EXECUTION_PLAN.md` still controls execution.**

The complete reconstruction, provenance, coverage limitations, ambiguous candidates and reverse-audit are recorded in `docs/OWNER_TODO_RECOVERY_AUDIT_2026-09-10.md` and issue #1336.

### Companion intake requirements incorporated here

The following existing `T-NEW-*` requirements in `docs/OWNER_REQUESTED_TODO_SPEC_INDEX.md` are hereby explicitly incorporated into this live intake ledger. A future agent must not require the owner to remember that a separate companion index exists.

| Ref | Requirement | Current disposition / pointer |
|---|---|---|
| T-NEW-01 | Canonical Owned Future Pick Projection & Valuation | PLANNED / companion spec |
| T-NEW-02 | Trade Calculator Generic Pick Quantities | IMPLEMENTED #1441; uniqueness rule SUPERSEDED for the calculator 2026-10-03 — every asset is repeatable (see "Added 2026-10-03" below) |
| T-NEW-03 | Public League Manual Sleeper Sync / Freshness | PLANNED / PARTIAL; companion spec |
| T-NEW-04 | Authenticated Top-Level League Navigation | REPRESENTED; verify live shell before closure |
| T-NEW-05 | `teamAssignment` Missing-Data-as-Zero Correctness | SHIPPED / VERIFIED per current backlog reconciliation |
| T-NEW-06 | Premium Sports Intelligence Migration | PARTIAL; `docs/PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md` |
| T-NEW-07 | The Upside Report | PLANNED; weekly showcase/report specs |
| T-NEW-08 | Canonical Weekly Power Rankings | SHIPPED / VERIFIED; do not reopen without regression evidence |
| T-NEW-09 | Awards & Honors | REPRESENTED; awards/report specs |
| T-NEW-10 | Analyst Intelligence | PARTIAL; claim/stance foundation exists, persistence/query and consumers remain |
| T-NEW-11 | B→C replanning gate | SATISFIED / superseded by current execution model |
| T-NEW-12 | Watchdog infinity false-negative repair | DONE |
| T-NEW-13 | Player Impact / VORP / WAR / WAB / Game Changer | REAL REMAINING work; use canonical replacement-level primitive |
| T-NEW-14 | Trade Calculator real-trade database / market evidence | PLANNED / PARTIAL; `docs/TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md` |
| T-NEW-15 | Canonical pick-value completeness through 2029 | REPRESENTED / PARTIAL |
| T-NEW-16 | C-Series zero-loss deployment/completion contract | REPRESENTED; current execution/verification rules win |
| T-NEW-17 | Historical trade replay / as-of team fit | PLANNED / dependency-gated |
| T-NEW-18 | Roster Age-Value Portfolio / Young Core (#838) | IMPLEMENTED; close only after required acceptance/production proof |
| T-NEW-19 | Meaningful Roster Core (#839), amended by #899 | IMPLEMENTED; latest FLEX ordering is decision 72; close only after required proof |

### Recovered durable owner requirements not previously compactly discoverable here

| Priority | Issue / record | Area | Required outcome | Status |
|---|---|---|---|---|
| Planned trade product | Master plan / trade-generation specs | Best Trade to Send Each Team + generated-package controls | For every other team, generate the best mutually defensible offer using canonical roster benefit and external native coverage; persistent outgoing protection and LOCK/EXCLUDE must be one shared constraint system. **Latest topology wins:** picks are legal when strategically beneficial, never filler; player-count difference may be at most one, picks excluded from that count. | PLANNED |
| Owner personalization | Master plan / trade-generation specs | General outgoing exclusion / untouchables | Preserve the owner's Vikings-outgoing preference as a user/league personalization overlay through one generalized exclusion mechanism consumed by generated-trade/waiver/drop surfaces. It must not mutate league-wide canonical player values. | PLANNED |
| Methodology decision required | #840 | Competitive Posture | Reconcile the owner-requested posture concept with the current continuous/non-hard-label design. Do not silently choose a conflicting methodology. | OWNER DECISION REQUIRED |
| Planned trade behavior | #841 | Posture-aware generated-trade picks | Permit draft picks in generated trades when both teams' strategic positions make them mutually beneficial; never use picks as filler. | REAL REMAINING |
| Planned trade UX | #842 | Use Team Context | Preserve an explicit team-context-aware evaluation mode/toggle using canonical roster/team context rather than page-local approximations. | REAL REMAINING |
| Canonical-owner consolidation | #843 | Roster Capacity / forced-drop economics | Consolidate duplicate roster-capacity/droppability ownership before further extension; preserve forced-drop/open-slot economics through one canonical owner. **Owner consolidation SHIPPED 2026-08-18** (`src/trade/roster_capacity.py`, consumed by `simulate_trade`, `suggestions.py`, `finder.py` and both `angle.py` endpoints — see CLAUDE.md "Roster capacity and forced drops — one owner"); remaining scope is the deeper Analyze Trade integration, dependency-gated on #792. | PARTIAL — canonical owner shipped; remaining scope gated on #792 |
| Source-platform work | `docs/sources/*` | Cross-position source acquisition / IDP ceiling | Preserve raw cross-position evidence; complete authorized Draft Sharks / Dynasty Dealer / Dynasty Nerds discovery and IDP Show / Footballguys lanes as applicable; never manufacture IDP ceilings or treat failed auth/acquisition as healthy empty data. | PARTIAL / some AUTH REQUIRED |
| Future competitive expansion | #985 | DynastyStats-derived expansion | Preserve League Hub/Pulse, Asset Map, Transaction Intelligence and Manager Scout enrichment as POST-V1 / fold-when-natural competitive scope. | LONG-TERM |
| Planned trade intelligence | #1173 | Best-ball roster-conditional utility | Add roster-conditional dynasty best-ball utility to Analyze Trade using exact legal lineup assignment, without changing standalone canonical player values. | PLANNED / dependency-gated on #792 |
| P1 cross-site UX | #1337 | Universal Player Profile / Player File linking | Every actionable player name site-wide should resolve through one identity-safe shared player-link primitive to the canonical Player File / public-safe counterpart where intentionally applicable. Existing partial links are not completion. | TODO |
| Cross-cutting performance architecture | #1338 | Data-heavy performance architecture | Re-authorized 2026-09-26 in `EXECUTION_PLAN.md` §0: current-main implementation through protected production verification. Current census and reviewed Gameplan single-flight correction are recorded in `performance/CURRENT_ARCHITECTURE.md`; archived #1346 remains donor-only. Measured route, browser and Linux acceptance are still required. | IN PROGRESS / NOT ACCEPTED |
| P1 Game Day / global context | #1334 | Global selected team + Game Day matchup + NFL-game impact | One canonical selected fantasy team must drive every team-dependent surface. Game Day must show that team's actual matchup. Keep the NFL slate in real kickoff order while computing selected-side, opponent-side and combined projected fantasy-point impact so higher-impact games are visibly emphasized. | PLANNED |
| P1 Game Day UX | #1335 | Game Day information architecture | Redesign Game Day as a clean live-sports/fantasy command center: compact matchup hero, score/projection/win probability, 3–5 key swing factors, NFL slate as the primary body, progressive disclosure for lineups/best-ball diagnostics/provenance, plain-language states, mobile-first scannability. | PLANNED |
| P1 public awards UX | Owner directive 2026-09-11 / T-NEW-09 | Awards Hub mobile hierarchy + weekly share snapshot | Make live player races the primary story in a deliberate MVP → OPOY/DPOY → OROY/DROY → positional order; move manager/team awards below; keep playoff/championship honors later-season and visually subordinate until relevant; prevent player/team imagery collisions; and provide a polished top-three-per-race snapshot that can be saved or screenshotted weekly on mobile. Preserve the canonical awards data/methodology and public-safe boundary. | FEATURE_GREEN — `codex/awards-mobile-redesign`; integration/deploy and real-iPhone verification pending |
| P0 planning/process integrity | #1336 | Owner-intent zero-loss recovery | Reconcile two months of recoverable chat-derived owner intent into this live intake, preserve provenance/supersession, and prevent future “assistant said added but no durable intake entry” failures. | IN PROGRESS |
| P1 engineering/harness process | Owner directive, 2026-09-12 | Agent-harness external-guidance reconciliation | Reconcile GPT-6 Astra / agent-harness external guidance (official OpenAI Astra post, 15 owner-supplied X posts, owner cost-aware delegation-tree pattern) against current Agent OS/Steward so future agents adopt genuinely new mechanisms once instead of repeatedly rediscovering the same external advice. Full source-by-source matrix, adopted/rejected rationale and deferred work: `docs/engineering/AGENT_HARNESS_EXTERNAL_GUIDANCE_RECONCILIATION_2026-09-12.md`. Built the one concretely missing piece found by the reconciliation, `agent-evals/` (engineering-reliability Priority 8); deferred a small Steward evidence-attribution gap and any CLAUDE.md/skill progressive-disclosure work already owned by PR #1344. **2026-09-30 extension (owner-supplied architecture review + links 16–25):** same record, Part H — source access vs adoption, a code-backed architecture map, the application-architecture queue mapped to engineering-reliability Priorities 1/2/3/6/10 (not authorized), and two confirmed-gap fixes: Steward raw-evidence validation on every insertion path plus structured producer attribution (closes the deferred attribution item; branch `claude/steward-evidence-validation`) and evidence-backed agent-evals grading of changed files against the pinned diff (branch `claude/agent-evals-diff-evidence`). Capture only — does not change `docs/EXECUTION_PLAN.md` authorization. | CAPTURED / PARTIAL (agent-evals/ foundation implemented; 2026-09-30 fixes in PR; test-evidence binding and the application queue open per Part H.5/H.7) |

### Recovered product-family pointers

These durable owner directions were already represented in canonical product/spec records but are made discoverable here so the live intake is actually a usable front door:

- **BDVM / fundamental dynasty evidence + model governance:** preserve an independent football/fundamental evidence lineage, historical snapshots, leakage-safe backtesting, uncertainty, versioning and champion/challenger/rollback discipline. Do not let it silently become another expression of current market value.
- **Podcast / Analyst Intelligence:** preserve the 2026-08-09 source-inventory reset, canonical source/analyst identity, fact/opinion separation, event-aware freshness, cross-media dedupe and personalized roster-aware team brief/podcast goals through the shared analyst-intelligence architecture.
- **Public League Experience:** preserve `Public /league = League Museum + Sports Network + Game Day` and `private app = Front Office + War Room`; public entertainment/history/shareability must not leak private decision intelligence.
- **Trade Calculator expansion:** the 2026-08-13/14 KTC-inspired workflow audit is durably specified in `docs/TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md`; adopt useful workflows through Chase Upside's own canonical identity/value/history/trade systems rather than copying branding or creating parallel engines.
- **Global interactive performance:** `docs/GLOBAL_PERFORMANCE_STANDARD.md` remains the owner-approved performance authority: speed is product correctness, warm useful state targets ~1s, normal production p95 ~2s where feasible, cold supported path ~3s, and 5s is an absolute useful-state failure ceiling; expensive reusable work belongs off the interactive request path.

### Durable capture rule — effective 2026-09-10

For every future model/agent session, if the owner makes a definite/high-confidence statement that a reasonable product/engineering lead would treat as durable future work — even when phrased informally as “add this,” “fix/change this,” “make this better,” “remember/revisit this,” “later,” or “put this on the list” — the agent must ensure the requirement is represented **in this live intake ledger**, directly or through an explicit compact pointer to its detailed issue/spec, before claiming it was “added,” “saved,” or placed “on the TODO.”

A GitHub issue, chat reply, assistant memory, or planning document alone is not enough if this live intake does not make the requirement discoverable. Ambiguous brainstorming should be retained for owner review without being silently promoted into binding scope. Later explicit owner instructions supersede older formulations. **Capture remains separate from implementation authorization.**

### Execution ordering

Do not mix these unrelated UI/auth/product requirements into the currently isolated foundational repair. Immediate defects (#779-#781) should be picked up at the next safe product-hotfix checkpoint unless one blocks required verification. #782-#786 are approved scope but must enter their natural dependency checkpoints. CE-20/#789 must begin only after scoring correctness, canonical best-ball assignment, projection-source/custom-stat modeling and prediction-history foundations are ready. #790 should be audited at the next appropriate trade/model checkpoint; #791 is a small UX addition; #792 is dependency-gated until canonical value/package/Team Strength/Weakness/roster-impact foundations are trustworthy. #800 is a trade-correctness defect for the next safe Trade Calculator checkpoint. **#801 is PAUSED by owner and must not consume spend or engineering time until explicitly resumed. #802 is a scoring-correctness dependency for any exact historical league-scoring claim. #803 follows the canonical scoring/league-configuration foundations and must incorporate #802 before promoting a league-fit signal. #829 belongs at the natural Public League Experience v3 / weekly storytelling / Game Day / share-renderer checkpoint after its canonical weekly data inputs are trustworthy; when that checkpoint begins, Manual External AI is the default and automatic AI-credit spend remains disabled unless the owner later opts in. #830 belongs at the natural FAAB / Waiver Market / CE-19 / Perfect Waivers checkpoint; audit and preserve the already-correct historical normalization and market-layer trending behavior first, then extend external/Sharp market evidence through the same canonical owner.** The 2026-08-15 mathematical calibration policy must be folded into the detailed C-Series unit map before implementation progresses beyond the currently authorized foundational retention work, but it does **not** itself authorize any later C unit. #854 belongs in the detailed C5 seasonal/projection decomposition under `C5-ROS-01`, with source/lineage/schema/archive work scheduled before Game Day and other projection consumers; its archival capture should begin as early as safely authorized because pre-event forecasts are perishable evidence. CE-17–CE-21 remain future competitive expansion after their dependencies. #788 stays long-term/cost-gated.

## Added 2026-09-13 — Live Rookie Auction: dynamic Perfect Draft, bid tracking, roster-aware budget optimization, price sensitivity

**Purpose:** capture a substantial owner-directed extension of Perfect Draft into a live-auction
tool. This is intake and specification only — see the binding detail document and manifest row
below; **`docs/EXECUTION_PLAN.md` is unchanged and no implementation is authorized by this entry.**

| Priority | Issue | Area | Required outcome | Status |
|---|---|---|---|---|
| P1 owner product spec | Owner directive, 2026-09-13 | Perfect Draft / live rookie auction | Extend Perfect Draft so it continuously answers "given my current roster, remaining money, confirmed purchases, active bids, available rookies and price assumptions, what combination should I acquire, what should I pay, and what would I eventually drop." Requires: live bid/lead/outbid state modeling; one shared budget (`F = B − S − C`) reconciled across every active auction; target-price / strategic-maximum / legal-maximum kept as three distinct quantities; a required Mendoza-style what-if acceptance scenario (`Delta(p, price) = V_win − V_pass`); reoptimization on every meaningful state change; and honest solver-status labeling under time pressure. Full binding specification: `docs/OWNER_FEATURE_ADDENDUM_2026-09-13_LIVE_ROOKIE_AUCTION_PERFECT_DRAFT.md`. Manifest `C7-DRAFT-03`, execution unit `C7-U12`. Consolidates existing defect row 3.7 / W10-F001 rather than tracking it separately. | PLANNED |

### Binding owner decisions — 2026-09-13

77. **The acquisition count is never fixed.** Perfect Draft's live-auction extension must not be read as recommending a target number of acquisitions (the owner's five/six examples were illustrative). Fewer players, more players, one expensive player plus cheap ones, or zero further purchases are all legitimate outcomes, exactly as the existing static optimizer already allows (ADR-009).
78. **Plan for ~12 simultaneous active auctions, not ~20, and keep it configurable.** No prior repository document stated a concurrency assumption; this is the first recorded parameter, not a correction of existing text. The real platform's actual concurrency rule must be verified before implementation, and unnominated eligible rookies remain part of the plan regardless of how many auctions are on-screen.
79. **Preserve the existing slow-auction format.** "Live" means immediately responsive to the evolving auction state — it does not authorize redesigning timers, quiet hours, or nomination rules into a different kind of auction event.
80. **Real state and hypothetical scenarios must never blur.** A what-if price entry must never submit a real bid, mark a player won, deduct settled spending, or overwrite official auction state. This is the single highest-risk requirement in the spec and binds every future implementation of it.
81. **A leading bid is an enforceable commitment for budget purposes, but it is not a completed purchase, and it cannot be canceled by the optimizer to manufacture a better plan** unless the actual auction platform's own rules permit release. Confirmed purchases can never be undone or refunded by reoptimization.
82. **One shared budget across every active auction (`F = B − S − C`).** No recommendation set may assume more cash is available than actually remains uncommitted; individual strategic ceilings are conditional on current state and must be labeled as such, not presented as independently achievable.
83. **Target price, strategic maximum, and legal maximum are three different quantities** and must never be collapsed into one number or approximated by adding a fixed percentage to another.
84. **Canonical dynasty value, team-specific recommendation value, and auction price stay separate.** One auction sale must never rewrite canonical player value; auction dollars must never be subtracted directly from dimensionless value scores.
85. **The Mendoza $65→$68 scenario (synthetic — Fernando Mendoza is a real player in this repository's fixtures, but this specific price scenario is illustrative only, not an actual auction event or valuation claim) is a required future acceptance case**, and every one of its nine required outputs (§8.3 of the addendum) must be produced by actually solving the scenario, never fabricated from a template.
86. **This extension consolidates, and does not duplicate, existing defect row 3.7 / W10-F001** ("draft bid respects remaining budget"). It is folded into the addendum's legal-maximum-bid machinery rather than fixed as an isolated patch.
87. **Probability-calibrated price modeling is explicitly later, dependent work (Phase F)** and requires evidence and calibration before any implementation; no precise win probability may be invented, and rival auction outcomes must not be treated as independent when they share the same competing budgets.

### Unresolved (recorded, not decided, per the addendum's own §15)

The live platform's exact simultaneous-auction limit, whether any existing integration exposes
live in-progress bid/lead state versus only completed picks, the exact eligible-player-pool size if
it differs from 72, the manual-vs-imported reconciliation-conflict rule, the authorization/evidence
bar for Phase F probability modeling, and the platform's exact bid-increment/proxy rules all remain
open. See `docs/OWNER_FEATURE_ADDENDUM_2026-09-13_LIVE_ROOKIE_AUCTION_PERFECT_DRAFT.md` §15 for the
full list; none of these are answered by invention here.


### KTC scrape memory-pressure repair — owner directive 2026-09-17

**DONE 2026-09-19** — #1394 merged; #1391 closed POST_DEPLOY_FIX_CONFIRMED; capture-window responsiveness accepted by owner decision, not directly measured (probe PR #1395 closed 2026-09-26 as contrary to that decision). Original directive: continue the open KTC outage repair under issue #1391 and the matching work claim. Use the #1388/#1389 telemetry plus inspection of the actual capture code; preserve all three native source modes and coverage/provenance guards. No MemoryMax/MemoryHigh/systemd changes. Run the full non-livedata suite, pinned formatting contract and sabotage verification before publishing the repair branch; then exact-head PR CI/review, normal merge/deploy and real-cycle production verification. The prior event-loop offload fixed a separate defect but did not eliminate this outage; the launch-flag attempt did not eliminate it either. Do not claim production resolution from unit tests or CI alone.


### Power Rankings PPG/Recent accuracy — owner report 2026-09-19

Owner reported the `/league` Power Rankings PPG/Recent columns were wrong. **Fixed in
full on branch `claude/ppg-recent-accuracy-lhc0x4`**: an in-progress league week was
being counted as a completed game for whichever teams happened to have a Thursday-night
partial score, so different rows divided by different numbers of games inside one table
(PRIOR-A03-F03). Root-caused, fixed, tested against both synthetic fixtures and real
live Sleeper data (2024/2025 completed-season replay byte-identical), documented in
`docs/CANONICAL_WEEKLY_POWER_RANKINGS_SPEC.md` §7.1, and the denominator is now stamped
on the payload so the defect class cannot recur invisibly. No further action needed on
the reported symptom.

Two deferred follow-ups surfaced by the investigation, genuinely out of scope for that
fix and not authorized here:

- **`metrics.scored_weeks` still drives `awards.py` VORP / starter-total / replacement-
  pool computations** (lines ~882, 1188, 1353) on the same disproven "a week is either
  fully real or fully a placeholder" assumption this fix retired for Power/Luck. Awards
  can therefore still drift mid-week on the same class of defect, on a different
  surface. Needs its own authorized unit — folding it into the Power fix would have
  changed award outputs incidentally.
- **No UI signals that a week is currently in progress and excluded from the board.**
  The fix makes an in-progress week invisible (correct — it must not corrupt the
  averages), but a small "Week N in progress — not yet counted" note on Power/Luck would
  make that explicit rather than implicit. Not built here to avoid widening a bug-fix PR
  into a new UI surface; a real product call on whether it's wanted.


### Power Rankings ROS/demonstrated-performance rebalance — owner directive 2026-09-22

Owner reported the Power Rankings blend gave ROS/projection too much influence relative to
demonstrated performance, citing a real regression example (not a forced outcome): a team
~#2 in scoring/all-play/#1 in record sitting behind a team helped mainly by a higher ROS
rank. **Implemented in full on branch `claude/ppg-recent-accuracy-lhc0x4`**: forward/results
target moved 0.40/0.60 → 0.30/0.70, the evidence time constant sped up 4 → 2 games
(deliberately decoupled from the unrelated recent-form window, which stays 4), `all_play`
raised 0.20 → 0.30 (now tied with `team_ros_strength` for the largest individual weight),
and a new within-bucket discount stops `recent` claiming separate credit for evidence
`all_play` already prices in while its trailing window is still the entire season-to-date
sample. Validated against the real live 12-team board (old vs new formula, full
component-contribution breakdown per team) and an isolated synthetic sanity check matching
the owner's described pattern exactly, independent of which real manager it currently
applies to. Documented in `docs/CANONICAL_WEEKLY_POWER_RANKINGS_SPEC.md` §5/§7. No further
action needed on the reported symptom.

One limitation recorded rather than silently skipped: §12 of that spec calls for a full
historical rolling-origin backtest (replay every reconstructable week, rank-correlate
against next-week all-play outcomes) before promoting a formula change. This rebalance was
validated the lighter way the owner explicitly asked for — current-board comparison, per-team
component contributions, a sensitivity check on nearby parameter choices — not that full
predictive backtest. A future formal backtest against §12's protocol remains valuable and is
out of scope here; nothing about this change depends on skipping it forever.


### Dynasty value freshness-aware source weighting + KTC signal separation — owner directive 2026-09-23

Owner directive (definite, durable): overhaul the dynasty value system so source influence responds
automatically to each source's *actual* content freshness, health and coverage rather than manual weight
edits. Binding elements, as approved with the owner's required revision the same day:

- **KTC Crowd and KTC Trades become two separate model inputs** (base weight 1.0 each, separate source
  families). **KTC Market** (KTC's own published Crowd+Trades value) becomes **benchmark-only** — never a
  third KTC vote, never containing any non-KTC source — with one canonical owner every market comparison
  consumes. Fantasy Navigator stays inside KTC lineage so KTC gains no hidden third vote.
- **Fetch time is not data freshness.** Track fetch, any-meaningful-change and broad-dataset-change clocks
  separately; classify each provider's publication style (snapshot / batch / incremental / unknown /
  explicit upstream timestamp) from evidence; players and picks are independent subsets.
- **Freshness is cadence-relative** (age ÷ the source's own expected interval), smooth and deterministic,
  with no universal absolute grace floors; candidate curves compared before constants are fixed; outages
  cannot redefine "normal" cadence; influence recovers automatically after a genuine update.
- `effective weight = base × freshness × health × coverage`; missing ≠ zero; degraded evidence stays
  visible under renormalization; per-player and per-source explainability; alerts for stale valuation
  infrastructure; IDP Trade Calculator, IDP Show and DLF staleness root-caused from evidence.
- Do not tune toward KTC Market; KTC Market is the benchmark, not the target.

Plan of record: branch `claude/peaceful-goodall-3uqtyx`; detail in
`docs/sources/SOURCE_FRESHNESS_WEIGHTING.md`. Authorization recorded in `docs/EXECUTION_PLAN.md` §0.

### Dynasty value overhaul continuation — owner directive 2026-09-24

Owner directive (definite, durable), continuing the 2026-09-23 unit above:

- **Every distinct legitimate signal votes.** Replace "family head wins" with **family-capped
  weighting**: each member of a correlation family votes with its own
  base × freshness × health × coverage weight, and the family's total is capped at one provider's
  authority, so a provider cannot multiply its influence by publishing related datasets. A stale family
  is never renormalized back up. Derived composites (KTC Market) and exact mirrors still do not vote.
- **DLF Trade Analyzer Values** (`/trade-analyzer-values/?l=sf_te_prem`) becomes DLF's offense value
  vote after a production probe and a measurement gate (distribution, identity mapping, Hampel drop
  rate, board diff); DLF IDP stays rank-based; Value and Rank keep separate freshness / health; one
  failing never freezes the other; the trade-page DLF second opinion shows DLF's raw native Value.
- DLF rookie-board audit (independent signal, family member, or mirror; seasonal applicability from
  evidence, never a hard-coded date); authoritative source inventory; participation invariant; IDP Show
  staleness root-caused.
- **Hill-curve / live source-authority alignment** (owner request 2026-09-24): audit whether the Hill
  refit's training evidence and weighting follow the live model's source semantics (native-value
  sources only — rank-only sources cannot teach value spacing; freshness / health / coverage and family
  semantics; KTC Market never a training vote; holdout stays out-of-sample; pinned `asOf` and source
  state), then make the smallest canonical repair. Sequenced after family-capped weighting.

Authorization recorded in `docs/EXECUTION_PLAN.md` §0 (2026-09-24). Record:
`docs/sources/SOURCE_FRESHNESS_WEIGHTING.md`.

**DLF Values normalization — owner decision 2026-09-24 (refines the measurement gate).**
Hampel rejection is a DIAGNOSTIC, not the objective. The chosen transformation must preserve
the information DLF publishes while making it comparable with the 1–9999 model space. Every
candidate is judged on: player ordering; native value SPACING; monotonicity; Hampel rejection;
board impact; stability across captures; interaction with DLF Rank inside the family cap;
whether it is new information or merely duplicates DLF Rank; circular dependence on our own
board; explainability / reproducibility.

* **rank → Hill is the control case.** If DLF Value through rank → Hill carries the same
  information as `dlfSf` Rank, it earns no second meaningful DLF family contribution. That
  would be evidence that the transformation throws away the spacing that is the point of
  acquiring Value, and choosing it anyway needs an explicit reason it beats DLF Rank alone.
* **raw / max × 9999**: measure how faithfully it keeps DLF's relative spacing and whether its
  curve is genuinely incompatible with the aggregation space. **DLF may disagree with KTC**,
  and differing from KTC's curve is not grounds for rejection.
* **quantile mapping**: define the target distribution BEFORE running it. Never map onto the
  current `rankDerivedValue` distribution (our board → DLF translation → DLF votes on our
  board is circular). Any reference must be proven independent and legitimate. Compare DLF's
  curve with KTC Crowd and other native-value sources for understanding only. Never tune DLF
  to KTC; KTC Market is a benchmark, not a truth target.
* If no transformation preserves meaningful DLF value information without pathological
  aggregation behaviour, DLF Values stay acquired, visible and in the DLF second opinion, but
  NON-VOTING, and DLF Rank remains the model signal until a defensible normalization exists.

### Power Rankings pipeline audit + methodology display — owner directive 2026-09-23

Owner reported a League Power Rankings share card showing 10 of 12 teams, "Preseason" in
Week 3, NEW on every row and a suspicious order. **Fixed, merged and deployed in PR #1400**
(`0c156fc`, production-verified 2026-09-23): a half-fetched Sleeper snapshot (current-season
rosters missing) was accepted as healthy, so the engine ranked the previous season's results,
dropped the two 2026-only owners and lost its week. Snapshot ingestion now refuses it, the
engine fails closed, publication refuses partial tables, and the table/share card share one
movement renderer. Follow-up (owner directive, same day): the methodology text is generated
from the canonical effective weights the score was computed with, per season stage, including
0% components that are not yet active. No further action needed on the reported symptoms.

Two items the owner explicitly kept OUT of the Power Rankings fix:

| Priority | Issue | Area | Required outcome | Status |
|---|---|---|---|---|
| P2 correctness | Owner 2026-09-23 | Playoff odds | `src/public_league/playoff_odds.py::_season_weekly_scores` keeps its own per-entry `is_scored` (points > 0) filter over all `regular_season_weeks`: an in-progress week's partial scores enter the score distributions, and a roster that genuinely scored 0.0 in a finished week is dropped. Consume the canonical definition (`luck._season_weekly_scores`: `metrics.final_regular_season_weeks` + `points is None`) with tests for both cases. Its own unit — not part of the Power fix. | TODO |
| Owner decision | Owner 2026-09-23 | Source freshness / value overhaul | The stale-DLF source-health warning seen during #1400 CI (`dlfSf`/`dlfIdp`/`dlfRookieSf`/`dlfRookieIdp` last fetched 2026-09-09) belongs to the separate source-freshness/value overhaul, not to Power Rankings. **Do not fix it by removing DLF.** The freshness system itself must make a broken/stale source lose authority automatically while preserving its last valid values. | DECISION |

## Added 2026-09-24 — restore `/api/health` and `contract_ok` (owner directive, cross-repo mission)

The owner directed (2026-09-23/24) that Brisket's `/api/health` degradation (`contract_ok=false`, first seen
around 22:47Z on 2026-09-23) be diagnosed from production evidence and fixed at the root, before any Market
Edge work. The owner's semantics, verbatim in substance: contract integrity and current ingestion health are
**separate truths**. When a critical source fails or times out while the served generation is valid,
**keep serving the last-known-good generation** (`contract_ok=true`) and refuse the partial run, but overall
health stays **DEGRADED/503** (`source_health_ok=false`) until that source recovers. Do not weaken invariants,
hand-edit production data, or hide a current refresh-unit failure with `reset-failed`.

| Priority | Issue | Area | Required outcome | Status |
|---|---|---|---|---|
| P0 live defect | Owner 2026-09-24 | Scrape promotion / health | Root cause: a critical-source timeout run whose partial values passed the anchor and retention checks was promoted and overwrote `exports/latest` (`partial_run_critical:IDPTradeCalc`). Fixed by PR #1405 (promotion guard refuses critical-partial runs while the served board is structurally valid; `/api/health` reports `contract_ok`/`served_generation_ok`/`source_health_ok` separately). | DONE (code); production verification in PR #1405 |
| P2 ops defect (out of scope) | Owner 2026-09-24 | Refresh units | Failing `dynasty-*` units recorded during the investigation, none in the contract path: `depth-charts-refresh`, `injury-feed-refresh` and `trending-history-refresh` (`ModuleNotFoundError: No module named 'src'`); `sharp-cohort-snapshot` (`EvidenceStatus is not JSON serializable`); `dlf-fetch` (`fetch_dlf.py` non-zero, keeps previous CSVs); `playerctx-refresh` (intentional fail-closed snapCounts schema-regression guard). Classified, not fixed, not reset. | TODO |

## Added 2026-09-24 — Calculator completion campaign (owner directive, multi-lane)

The owner authorized ONE multi-lane Calculator implementation campaign, to begin only after the
#1427 production release and PR #1432 are settled. Authorization: `docs/EXECUTION_PLAN.md` §0
(2026-09-24, "Calculator completion campaign"). Calculator Ideas (`docs/BRISKET_IDEAS.md`) is the
full remaining completion portfolio. Strategy: **build broadly, integrate narrowly** — about four
substantial lanes with focused testing while building, expensive CI at integration boundaries, one
integrated release candidate and one production deploy where practical; no PR per idea, no single
giant PR.

| Lane | Owner requirement | Status |
|---|---|---|
| A — Roster decision foundation | ONE canonical owner each for Team Strength, Meaningful Roster Core, Team Weakness / **Need Priority / lineup demand**, roster capacity and droppability, consumed by Trade / Waivers / Game Day / roster profiles. Retire duplicates; never extend a competing implementation. | TODO |
| A — `classify_need` (decision 2026-09-24) | `faab_engine.classify_need` survives ONLY as a FAAB-specific interpretation. It must not be a second source of roster/lineup need truth: any part that independently derives starter demand, positional need or roster deficiency delegates to the canonical roster owner, and FAAB translates that canonical result into bid categories/urgency. | TODO |
| A — Competitive Posture #840 (decision 2026-09-24) | The posture MODEL stays continuous and evidence-driven. The product may publish PUSH / HOLD / RETOOL / REBUILD, but only as an explained probabilistic classification from the continuous evidence, with confidence and component evidence; no single arbitrary hard threshold; HOLD / low confidence when evidence is balanced or ambiguous. Posture is context, never an automatic veto; Analyze Trade consumes the underlying evidence and marginal effects, not merely the label. | TODO (unblocks #841) |
| A — Team Strength #1340 (decision 2026-09-24) | Re-verify against current production first. If the page still sticks on "Loading league data..." rather than a real result or a truthful unavailable state, repair it early as a roster-foundation/production defect; if not, close/update #1340 with current production evidence. | TODO |
| B — Trade intelligence | Complete Analyze Trade UX, before/after roster impact, final roster simulation, capacity / forced-drop consequences, Team Context, best-ball roster utility, canonical generation constraints where dependency-ready. Exact KTC Value Adjustment stays a market lens, not canonical truth. No frontend business logic duplicating backend owners. | TODO |
| B — Pick lifecycle #1414 (authorized 2026-09-24) | ONE canonical lifecycle rule (never page-local year filters): a rookie-draft class leaves active/current surfaces only when the draft is complete AND roster state proves its rookies were consumed. Immediate case: 2026 pick assets no longer active. Historical identities, trades, snapshots and provenance stay resolvable. | DONE — #1442 (`bfdb238d8`); production pick-horizon verified 2026-09-26; #1416 planning PR closed as superseded |
| B — Asset quantity/identity #1415 (authorized 2026-09-24) | Generic/repeatable assets may have quantity > 1; distinct real picks with similar labels may coexist; the exact same unique owned pick may not be double-counted. Quantity and identity survive math, remove-one, share/persistence/export and mobile/desktop round trips. PR #1416 is planning/intake only: reconcile its useful records with current main, never treat it as implementation or merge stale branch state. | DONE — #1441 (`53109028c`); #1416 planning PR closed as superseded. **Uniqueness half SUPERSEDED 2026-10-03** for the calculator: every asset (players and owned picks included) is repeatable — see "Added 2026-10-03" below |
| C — Freshness + valuation hardening | Reconcile #1423 (T-NEW-21, adaptive staggered freshness orchestration; its planning PR #1425 was closed 2026-09-26 with the owner contract preserved in the issue); weighted-median monotonicity repair; Hill / native-source alignment and rank-form drift; DLF Values normalization gate once enough real captures exist (binding rules in the 2026-09-24 DLF decision above). Never blocks other lanes. | TODO |
| D — Product correctness | Playoff Odds finished-week scoring: the P2 row under "Power Rankings pipeline audit" above (owner amendment 2026-09-24: an early item; consume the canonical definition; regression tests for the in-progress-week and finished-week `0.0` cases; not a Playoff Odds redesign). Also scoring/projection correctness, individual special-teams scoring, projection ensemble, Universal Player File intelligence consumers. | TODO |
| D — Analyst ledger OD-03 (authorized 2026-09-24) | The analyst/intelligence **persistence + as-of query foundation**: the shared substrate for unified Player File intelligence, YouTube/news/podcast ingestion consumers, the homepage intelligence ticker and Weekly Report Studio. Extend the existing `src/intel/` / `src/analyst/` architecture and restore the missing persistence/query layer cleanly from current main; no competing ingestion system. | TODO |
| 6 — Premium UI (permanent) | Every substantial checkpoint includes active UI or names the active UI PR/issue/claim. Locked PSI / Direction A, shared `ds/` primitives, no business logic in UI; move to another stable route when one route's contract is unstable. Continue non-chart PSI work (populated Rankings / Player File accessibility and visual coverage, stable-route migrations). | TODO |
| **PRIORITY — Game Day live best-ball dashboard (owner amendment 2026-09-24)** | The current `/game-day` is rejected as a product: not a restyle and not a diagnostic dump. It is a named campaign deliverable pairing Season/Scoring/Projections with Lane 6. Full contract: issue #1335 comment 5824706487 (reconciles #1334, #789 / CE-20, #854); campaign cross-reference PR #1433 comment 5824708400. **Product:** a normal user immediately sees the selected team vs its actual opponent, score now, projected final best-ball score for both teams, win probability and (where applicable) beat-median probability, the live/upcoming players and NFL games that matter most, and whether the evidence is current, delayed or incomplete. **Inputs:** audit which providers really supply CURRENT-WEEK projections (source family, horizon/week, scoring basis, as-of, K and IDP coverage, cadence); use the #854 ensemble and the exact league-scoring owners; expose uncovered scoring categories; never substitute dynasty values, ranks or preseason per-game averages as weekly forecasts. Wire a legitimate live game-state and scoring source with OBSERVED quarter/clock/status (elapsed wall time since kickoff does not qualify; reconcile the older wall-time fallback explicitly). **Forecast:** provider weekly projections stay distinct from our derived rest-of-game forecast, which updates with scoring, game progress and supported availability evidence. Validate the method and claim no sophistication that is not implemented. Per simulation draw: keep actual production, simulate only the remainder, recompute the exact legal best-ball lineup (completed players can still be displaced), with no double counting of players, points, FLEX eligibility or bench projections. The expected final best-ball total stays distinct from a lineup chosen on individual means. Matchup and median probabilities come from the same coherent league simulation. **Experience:** locked PSI / Direction A. Default hierarchy: compact matchup scoreboard, then 3–5 "What matters now" items, then a compact chronological NFL slate, then expandable lineup/player detail, then collapsed Data info. No walls of repeated eligibility text. Refresh in place: keep same-context content, scroll, focus and expansion; out-of-order or other-context responses never replace the current team/league/week; never blank the page each minute. **Updates:** bounded shared background collection plus cached simulation generations. A live update needs no deploy, full scrape or per-viewer simulation. Measure source-to-screen freshness; a fetch timestamp is not a current projection. Missing stays missing (no zeros, no fabricated odds), but an "unavailable" message is a fallback, not completion. Name exact source-access, permission, coverage or cost blockers. Buy nothing and bypass nothing; keep building while an external dependency is blocked. **Acceptance:** replay/regression evidence for pregame, live, halftime, delay/overtime, final, stat corrections, missing feeds and best-ball displacement; exact league scoring and UI/API agreement; desktop and phone screenshots with real data; refresh without blanking; verified live production behaviour. A mockup, doc update or test proving the old limitation is displayed is not completion. | TODO — PRIORITY |
| Owner decision | #1428 categorical-chart contrast | OWNER UI DECISION REQUIRED: do not invent a palette or weaken accessibility criteria. It does not block the rest of Lane 6. | DECISION |

**Owner decision — draft #1346 must not block Game Day / Trade UI (2026-09-24).** Game Day and the
authorized Trade UI take priority over uninterrupted ownership of overlapping hunks in draft PR
#1346. Do not merge #1346 merely to clear file ownership, and do not build duplicate UI, routes or
components around it. Preserve any #1346 performance/serving behavior actually needed in the
overlapping files. Separable hunks yield temporarily to product work and #1346 reconciles afterward;
inseparable ones are rebased/cherry-picked with proof that both behaviors survive. Do not weaken
#1346's own acceptance criteria, and keep its non-overlapping work moving. Measured overlap and plan:
#1346 comment 5825392001. The `rankings/page.jsx` and `trade/page.jsx` hunks are line-local (nothing
yields); `trade-sections.jsx` is not in #1346. The `GameDayPanel` refresh-in-place logic and the
`game_day_sim` single-flight/atomic cache writes are carried into the Game Day units with their tests,
and #1346 drops them at reconciliation.

**#1346 performance-serving campaign — historical owner intent (2026-09-10..20) and donor-branch
disposition (recorded 2026-09-26).** HISTORICAL RECORD, NOT CURRENT AUTHORIZATION. Preserved so the
intent is not lost when the branch closes:
- 2026-09-10 — owner approved the audited performance modernization plan (producers, prepared
  rankings/trade read models, dependency-aware refresh).
- 2026-09-11 — local acceptance policy: refresh p95 < 75 ms AND (relative increase ≤ 20% OR
  (absolute increase ≤ 15 ms AND p95 ≤ 25 ms)).
- 2026-09-12 — owner paused the campaign and reserved final-release authority to the owner.
- 2026-09-20 — owner terminal completion directive for the campaign.
- 2026-09-26 — owner instruction: use #1346 as a donor, harvest small independent defect fixes onto
  current main with tests, then close it. Harvested on `claude/harvest-1346` (contract raw-input
  immutability, BDVM actuals/context/schedule cache keys, frontend request-scope + missing-value fixes,
  timer `__SERVICE_NAME__` prefix); prepared serving, read models, `src/serving/*`, performance-lab and
  telemetry were deliberately NOT ported.

Donor state is preserved at tag `archive/pr-1346` → `47b90cd41`. Any future serving / read-model work
starts from issue #1338 and must be re-authorized in `docs/EXECUTION_PLAN.md`; **main does not authorize
serving activation.** Future-scope note for #1338 (not implemented): the donor's `/api/gameplan` bundle
single-flight (`src/api/gameplan.py::_BUNDLE_FLIGHTS`, `tests/api/test_gameplan_singleflight.py` at
`47b90cd41`) coalescing concurrent identical bundle builds.

**Owner attestation — source access (2026-09-25, explicit, in writing). Canonical posture: `OWNER_ATTESTED_AUTHORIZED`.**
The owner explicitly attests that permission exists for Calculator's current automated ingestion and
project use of the sources already integrated, or intentionally being integrated, into the existing
source portfolio. That includes, among others: Sleeper, RotoWire, ESPN, IDP Show, Fantasy Nerds,
SportsDataIO, FantasyPros, DraftSharks, IDP Trade Calculator, DLF, FantasyCalc, Dynasty Daddy, Fantasy
Navigator, PFK and related feeds, Flock Fantasy, Yahoo/Boone where currently used, and every other
source already in Calculator's ingestion system. Public terms are not the basis for that permission,
and the repository does not hold or reproduce any private permission correspondence unless it is
separately provided.

- **What changes.** These sources are no longer "owner decision required". They are not treated as
  unauthorized because public terms do not document private permission, and they need no per-source
  re-approval. **The Game Day source-access blocker is removed.**
- **Scope boundary.** A genuinely new provider, or a material expansion of an existing provider into a
  different product, feed or use case, still goes through normal source intake and permission
  verification, and any expansion is recorded. A new permission decision is surfaced only for a new
  provider, a materially out-of-scope mechanism or use, or an owner change or revocation.
- **Credentials.** Keyed or subscription APIs are configured by the owner through environment or
  secrets. Agents never handle credentials.
- **Record.** `docs/game-day/SOURCE_ACCESS_EVIDENCE_2026-09-25.md`, which keeps the public-terms
  research as background context only.

**Game Day scope reaffirmed (owner, 2026-09-25).**

- **Sequence.** Build U4 through U7, then integrated validation, production release, and verification
  during a real live game.
- **Weekly projections.** Use a multi-source weekly ensemble of genuinely independent evidence.
  Record provider, family, ancestry, horizon, week, as-of, fetch time, stat and position coverage,
  native scoring basis and missing state. Never double-count aggregators, representations or horizons.
- **Scoring.** Stat-level projections are rescored through the exact league scorer, covering QB, RB,
  WR, TE, K, DL/EDGE, LB, DB, first downs, yardage bonuses and return/special teams. An uncovered
  category is kept as uncovered, or covered by a validated estimator labelled as OURS; never zero.
- **Live data.** Live state, factual stats, the projection ensemble, scoring, lineup and simulation
  each have one owner. Do not build a single-source dependency.
- **Default page hierarchy.**
  1. Matchup hero: score now, projected final best-ball, margin, win chance, median chance,
     LIVE/UPCOMING/FINAL and freshness.
  2. What matters now.
  3. A chronological NFL slate.
  4. Best-ball details.
  5. Data info.
- **Freshness.** Shared background collection with persisted, versioned generations. Show observed-at,
  fetched-at, computed-at, payload age, degraded state and refresh-in-progress state.
- **Acceptance.** Pregame, live, halftime, second half, overtime, delay or postponement, final, stat
  corrections, negative points, real zero, missing player, missing projection, source outage, K, IDP,
  SF/FLEX displacement, several players competing for one slot, team switching, and stale or
  out-of-order responses. Use real captured fixtures, then production during a live game.
- **Execution (owner clarification, 2026-09-25).**
  - Do NOT wait for Sunday or Tuesday before completing U4–U7.
  - Build deterministic captured-input or synthetic replay fixtures now for the states not yet captured
    naturally: stat corrections; simultaneous games at different stages; one matchup mixing completed,
    live and upcoming players; overtime and delay combinations. Finish the engineering against them.
    The real Thursday ATL@GB capture (end of Q1 → final) already supplies pregame, live, halftime,
    second half and final.
  - The real Sunday multi-game capture and the Tuesday stat-correction window are additional evidence
    required before Game Day is declared fully verified.
- **Fantasy Nerds and SportsDataIO** are integrated now at the adapter and configuration level.
  - Each gets a canonical env/secret name. Keys are never hard-coded, committed, logged or exposed.
  - A missing credential means the source is unavailable, not zero data, and it blocks nothing else.
  - Activation happens through the source-health and capability gates once the owner installs
    credentials.
  - Source-family ancestry is preserved, so they expand the ensemble without double counting.
- **Honest ensemble status.** RotoWire via Sleeper may be the initial usable weekly source, but a
  one-source state is never described as a mature multi-source ensemble. The actual number of
  independent projection families contributing is reported.

**Owner decision — #1414 retirement is separate from the future-pick horizon (2026-09-25).**
The canonical draft-class retirement rule is approved (PR #1442). Retirement must NOT automatically
expand the supported future-pick horizon, so two concepts stay separate:

1. draft-class lifecycle / retirement;
2. the supported future-pick horizon.

Retiring 2026 keeps the existing horizon unchanged: 2027–2029, with no 2030 rows and no induced
rank/tier shifts. The only horizon rule on record is CLAUDE.md step 12 / C1-U6 ("horizon = current +
3, self-rolling", anchored on the active draft year); nothing says retirement advances that anchor.
**Horizon advancement (introducing 2030) is a separate owner decision**, to be brought with evidence
and measured impact.

**Owner decision — FAAB vs Trade flex demand stays as-is (2026-09-24).** Do NOT unify the two yet.
FAAB apportions flex demand fractionally (`even_split`, e.g. QB 1.25 in dynasty_main); Trade assigns
flex slots through the lineup/need owner. Both read the one canonical demand owner (PR #1436), but they
answer "how many does this league start" differently. That is recorded as an explicit
owner-methodology decision. No FAAB bid changes for conceptual symmetry without a measured,
owner-approved methodology change. Status: DECISION (deferred).

**Preserved invariant — Power Rankings methodology ownership (owner 2026-09-24).** PR #1401 fixed
and production-verified the methodology display; do not reopen or duplicate it. The backend/API is
the canonical owner of the effective Power Ranking methodology and weights; the frontend renders the
published weights directly and never reconstructs, rounds or infers the methodology. Any future
Power Rankings work keeps that boundary.

## Added 2026-09-25 — research-to-portfolio reconciliation adopted (owner approval, explicit)

The owner approved adopting the completed research-to-portfolio reconciliation into the canonical planning
records, as **supporting evidence plus a proposed portfolio amendment**. It is not implementation
authorization; `docs/EXECUTION_PLAN.md` §0 stays the sole authorization record.

The full record is `docs/research/calculator-reconciliation-2026-09-25/`: the README plus the verbatim
70-row crosswalk and its receipts.

**Identity.** Native Calculator IDs and owners stay authoritative. `R01`–`R70` are evidence and
cross-reference IDs only: no manifest rows and no second ledger.

**Explicitly not authorized by this approval:**

- implementing all 70 recommendations;
- creating 70 issues;
- changing owner decisions;
- promoting model or source candidates;
- activating paid or default-off sources;
- reducing approved scope;
- admitting every idea.

Disposition census: EXTEND 39, KEEP 9, CONSOLIDATE 9, REFRAME 6, NEW CANDIDATE 6, DEFER 1 (R60, salary-cap
leagues). The consolidations into existing owners are listed in the record's README.

**NEW CANDIDATE admissions.** These were reconciled against the final crosswalk before admission. Status is
CANDIDATE: recorded, not authorized, no native ID minted.

| R-ID | Candidate | Native anchor (crosswalk) | Status |
|---|---|---|---|
| R14 | Prospective private decision and offer journal | extension of `C6-MGR-01` / #985, `C1-HIST-01` | CANDIDATE |
| R39 | Value-movement attribution and normalization audit | consumer of `C1-HIST-03`, source provenance, C8 generation owners | CANDIDATE |
| R41 | Robust action frontier and regret budget | method extension of `C7-DESK-01` / `C7-AI-02` | CANDIDATE |
| R64 | Source-directed player research queue | extension of `C6-UPP-01` / `C6-ANA-01` / `C7-ALERT-01` | CANDIDATE |
| R67 | Offer option value and expiry dashboard | private offer consumer of `C6-MGR-01` / `C7-AI-02` / `C7-DESK-01` | CANDIDATE |
| — | Sixth slot | see below | **OWNER DECISION REQUIRED** |

**Sixth-slot discrepancy (held, not substituted).** The owner's approval listed "value-of-information /
action-deadline intelligence" (R40). The crosswalk classifies R40 as **EXTEND** of `C7-ALERT-01` / CE-29, noting
that a new prioritization policy needs explicit approval. The crosswalk's sixth NEW CANDIDATE is instead
**R44**, "Personalized decision-quality feedback". R44's native anchor is CE-28, which is **NOT OWNER-APPROVED**
and whose promotion is decision row `OD-06`. Admitting R44 would prejudge OD-06, so neither was admitted. The
owner chooses between:

1. R40 remains EXTEND under C7-ALERT-01, with its VOI prioritization policy still needing approval before it is
   built.
2. R44 is admitted, which also means deciding OD-06.

**Train-2 boundary correction (owner, 2026-09-25).**

- #1445 (Game Day backend) and #1446 (Game Day PSI UI) are the bounded next slice. They ship together once
  their own gates pass: exact-head CI, the RC, and research gates A–H as applicable.
- #1442 (pick lifecycle) and #1444 (DLF gate record) proceed in parallel and **must not gate Game Day**.
- #1447 (claims-2) may merge when safe and must not gate Game Day.
- Overlap and ownership rules are unchanged, especially the #1346 handoff: no duplicate engines, registries,
  caches, source owners or UI systems.

**Continuing work named by the approval:**

- **Gate D.** A real stat correction must propagate to a new generation while preserving as-known history.
  Provider corrections stay distinguished from authoritative scoring corrections.
- **Gate G.** Cold or no-generation requests must be immediately useful, with truthful pending/computing
  states. No latency-budget relaxation.
- **Lane 6.** #1446 still needs actual mobile, accessibility, real-data and production acceptance.

**Kept separate.** The finding is `row.confidence or 1.0` in `src/ros/aggregate.py`: a confidence of 0.0 would
be weighted as 1.0. It stays a separate item unless it becomes a demonstrated Game Day dependency.
Reachability is established with a discriminating test before any behaviour changes.

**Owner directive — Game Day switches between every team in the selected league (2026-09-25).**
Extends the Game Day deliverable above (#1335 / #1334, Lane 6); it is not a second Game Day project.
Implementation is authorized by the owner's own handoff. The authorization record is the pointer in
`docs/EXECUTION_PLAN.md` under the Game Day deliverable.

- **Experience.** `/game-day` gets a primary PSI / Direction A team selector near the hero. Any roster
  of the currently selected league can be viewed from its own side, repeatedly, without leaving the page.
  The user's own team stays the default; ownership is never a restriction.
- **League isolation.** Switching never leaves the selected league: no fallback, no substitution, no
  same-name match from another league. Responses carry league and team identity, and the frontend
  rejects a mismatch.
- **Canonical owners reused.** The selection identity is the existing `?team=<ownerId>`. The backend
  composes the chosen side and its opponent out of the SAME league-week render
  (`src/api/matchup_intel.py`), so the perspective reverses rather than being relabelled. There is no
  new engine, simulation, identity scheme or team store, no frontend math, and the global "my team" is
  not rewritten by viewing a rival.
- **URL and races.** Refresh, back/forward and deep links keep the chosen team. A late answer for an
  earlier team never publishes (A → B → C).
- **States.** Loading, computing (PENDING), stale, unsupported, unavailable, failed and true zero stay
  distinct. A newly selected team with no generation shows its known facts at once, while the shared
  background compute fills the forecast.
- **Acceptance.**
  - The discriminating tests enumerated in the directive.
  - Desktop, 390 px phone, keyboard and screen-reader naming, with no horizontal overflow.
  - Production Team A → B → C with an authenticated session, recorded separately from local and CI
    evidence.
- **Not authorized.** A Game Day rewrite, methodology or scoring changes, paid-source activation, a PSI
  redesign, or a new league/team identity owner.


**Owner directive — Game Day Live Median Race (2026-09-26).**
Extends the Game Day deliverable (#1335 / #1334, Lane 6); it is not a second Game Day. Implementation is
owner-approved; the authorization record is the pointer in `docs/EXECUTION_PLAN.md` under Game Day.

- **Experience.** A primary "Live Median Race" section placed directly after the Matchup Hero. The new
  hierarchy is Hero → Median Race → What Matters Now → NFL Slate → Best Ball Details → Data Info.
  - Every roster of the selected league appears once, ranked by beat-median probability.
  - Each row shows score now, projected finish, same-draw median margin, beat-median % and movement.
  - A league-median summary shows current, projected final and 80% range.
  - An objective bubble (probability distance from 50%) names who is fighting around the cutoff.
- **Math reused, never re-derived.** The existing league-wide simulation stays canonical: one draw scores
  every team, M(d) is that draw's own median (host-verified semantics; an exact tie is not a win), and
  P(beat) = P[S(t,d) > M(d)].
  - The projected median distribution comes from the M(d) series.
  - The margin is the paired S(t,d) − M(d).
  - There is no frontend median, no per-team simulation and no fixed cutoff.
- **Truth rules.**
  - Current median only when live scoring is complete; otherwise it is named unavailable.
  - Final week resolves to actual BEAT / MISS / TIE.
  - A median-disabled or unverified league never gets fabricated percentages.
  - Missing is never zero.
- **Live.** Only the existing shared collector and generations. Movement is in percentage points, against
  the previous comparable published generation only, and absent when there is none. No new timer,
  history or archive; the existing generation index retains calibration evidence.
- **Selection.** A row switches Game Day via the existing `?team=` mechanism. The picker stays in sync.
  There is no second team state and no global My Team change.
- **UI.** Locked PSI / Direction A. A dense ranked list on desktop and two-line ruled rows at 390 px. No
  categorical probability colours (#1428 stays separate).
- **Not authorized.** A new engine, simulation, projection, scoring, collector or ML system; playoff or
  season projections.


**Owner directive — Awards: 2026 Waiver King eligibility + Expand standings (2026-09-26).**
Owner-approved; the authorization record is the League Hub Awards pointer in `docs/EXECUTION_PLAN.md`.

- **A. 2026 Waiver King eligibility (season-scoped, one award).**
  - Joel and Blaine may not WIN Waiver King in the 2026 season:
    - Joel: owner `712035316776669184` (Sleeper `jstuedle`, roster 11).
    - Blaine: owner `1303549304882892800` (Sleeper `ughb`, roster 12).
  - The rule is recorded with its provenance in `config/leagues/award_eligibility_overrides.json` and answered only
    by `src/public_league/award_eligibility.py`.
  - Keyed by season and that season's league id, never a date: 2027 starts with no rule, and 2026 viewed in any
    later year keeps it.
  - Their waiver data and metric are unchanged and still published, with metric rank and an "Ineligible for 2026
    award" label. The award goes to the highest-ranked eligible manager.
  - No other award, statistic, standing or consumer is affected.
- **B. Expand standings (durable).**
  - Every current-season award race keeps its concise leaders and publishes `standings`: the award's canonical
    ranking, at most 12 rows, from the same backend rows that decide the award.
  - Entity per award: player, manager, team, NFL franchise, or event (team-week).
  - Fewer qualifying candidates means fewer rows; ties share a rank; awards awaiting evidence publish none.
  - Race-less current-season awards (Regular-Season Crown, Points King, highest/lowest single week) carry
    standings too.
  - Award history stays separate.
  - Explicit exceptions: Champion (decided by the bracket, not a metric), Best Trade and Rivalry of the Year
    (their owners compute only the single best), Best Rebuild (off-season, completed seasons only).
- **Not authorized.** Formula, VORP, scoring or waiver-methodology changes; new or removed awards; a League Hub
  redesign.
- **C. OPOY / DPOY terminology (owner clarification on #1464, 2026-09-26).**
  - `off_mvp` is shown as "Offensive Player of the Year" and `def_mvp` as "Defensive Player of the Year". "League
    MVP" is unchanged.
  - Internal keys are unchanged; formulas and rankings are byte-identical.
  - Applies everywhere the backend label reaches: cards, races, expanded standings and history.
  - OPOY/DPOY do not inherit any League-MVP competition-success gate.
  - **Resolved 2026-09-26 by the owner** (see "League MVP requires team success" below). This bullet had
    recorded the conflict between the clarification (League MVP gated on a playoff-field, above-.500 franchise) and
    the 2026-08-14 amendment (no hard gate). The owner ruled for the gate on League MVP only.

**Owner directive — Schedule Intelligence (2026-09-29).** Calculator Ideas record: issue #1530 (ordered
portfolio A–E with owners, dependencies, surfaces, NOW/NEXT/LATER/BLOCKED) and
`docs/SCHEDULE_INTELLIGENCE_SPEC.md`. One canonical schedule-analysis owner
(`src/public_league/schedule_impact.py`) answers "how good were the performances, what happened, and how
differently could the same performances have turned out under another defensible schedule" across League
Hub, team pages, Power Rankings (context only), recaps, share cards, history, a Hard Luck distinction, the
Schedule Multiverse, swaps, retrospective playoff sensitivity and player impact / MVP (shadow). Read-only
retrospective analysis — NOT the removed schedule generator (X-01). Official Power Rankings and MVP formula
changes stay gated; MVP eligibility (.500 or better) and ungated Unified Manager of the Year are preserved.
Authorization: `docs/EXECUTION_PLAN.md` §0.

**Owner directive — draft-capital stack effect WITHDRAWN from trade totals; informational only (2026-09-29).**
Active; supersedes the two same-day entries directly below (kept for history). The stack effect must not affect
side totals, the verdict, fairness classification, multi-team comparisons, side flows, balancer suggestions, or any
recommendation driven by package totals. Adjusted package total = raw canonical package value + Value Adjustment.
The stack effect stays visible, labelled "experimental, not calibrated. Not included in the totals or verdict." No
zero clamp; no quick recalibration. Implemented by #1527 (guard: `frontend/__tests__/trade-stack-withdrawn.test.js`).
Future rebuild recorded in Calculator Ideas as issue #1529 — planning position **LATER** (depends on a canonical
draft-year universe and canonical pick ownership), **NOT AUTHORIZED**; prerequisites S1-S8 and the validation plan
live there. The league-pool-rate attempt is historical evidence of an insufficient calibration, not an accepted
method. The Rookie Auction Room's dollar ledger is a separate concept and is not affected.

**Owner decision — trade stack effect converts at the league pool rate (2026-09-29).** *(Superseded the same day —
see the directive above.)*
Owner report: the trade meter showed Side A at -2,603 after two 2029 late picks moved to it. Cause: the draft-capital
stack effect converted league-wide auction-dollar premium shifts into board points at the moved picks' OWN rate (a
$1-$2 late pick ~1,000+ points per $ vs ~44 for a first), on whole-dollar-rounded effective power -- flagged in the
2026-08-04 decision-intelligence audit and never fixed. Owner choice (of: league pool rate / remove from the verdict /
cap at the picks' value): **the league pool rate** -- sum of the board values of the draft's own picks divided by the
dollars those picks carry; no pool rate means the stack effect is withheld, never a guessed rate. Premiums are computed
on unrounded effective power (rounding is display-only).
- **Superseding interim (same day), after the #1527 acceptance audit** (the owner required a full decomposition before
  calling it fixed): the audit found the swings driven by data seams, not the rate -- the upcoming draft year differs
  between draft capital (2027) and the board's pick lifecycle (2026); 2027 picks are counted twice in team stacks;
  future-pick auction dollars are synthesized; picks can be "sent" by teams that do not hold them. Under the pool
  rate an early pick from a $0 team still took a side to -963. **Owner decision: the stack effect is OUT of side
  totals, the verdict, side flows and balancer suggestions now**, shown only as a labelled not-calibrated note.
- **Owner principle for its return:** the stack term is an adjustment to package value and must not become the
  dominant source of value merely because low-dollar picks are involved. It returns to the totals only once rebuilt
  as an adjustment scoped to the moved picks' own value, with the seams fixed (draft-year universe, double count,
  unowned picks); future-pick pricing and the conversion rate remain open model work. No arbitrary clamp.

**Owner authorization — preserve pregame weekly projections from the Game Day prune (2026-09-29).**
Authorized now, ahead of the ~2026-10-13 retention deadline (#1519 G1), sequenced after the #1517 → #1518 → #1516
release queue. Smallest correct change: the raw pre-kickoff Sleeper weekly projection evidence must not be destroyed
by the 4-week raw-log prune. Last valid pre-kickoff snapshot per player/game/week; timestamp, season/week, player and
game identity, source/provenance and version preserved; never replaced with a later model; no second projection
owner; bounded retention with measured storage; included in backup/restore; regression proving the prune cannot
delete it. Not a broadening into the other #1519 gaps. Implementation: `docs/game-day/GAME_DAY_WEEK_RESOLVER.md`
("Pregame weekly-projection archive").

**Owner correction — award record eligibility is .500 OR BETTER (2026-09-29).**
Binding; immediate; supersedes the record half of the 2026-09-26 League MVP decision below and every earlier
"above .500" / "strictly greater than .500" / ".500 is not a winning record" statement.
- For any award that ACTUALLY has a record eligibility requirement, the franchise qualifies on record when its
  official regular-season winning percentage is **>= .500** under the league's canonical standings semantics (a tie
  counts as half a win). Exactly .500 counts (6-6, 7-7, 8-8); below .500 does not (6-7, 7-8). Zero decisions never
  qualify from a fabricated .500; missing/unverified standings stay unverified.
- Today only **League MVP** has a record requirement. Its playoff-field requirement is unchanged: in the field +
  .500 or better = eligible; outside the field = ineligible regardless of record.
- **Manager of the Year has no record gate** (and no playoff gate) under the owner's unified Manager of the Year
  direction, which the owner restated in this same 2026-09-29 instruction (first given 2026-09-28): one combined
  award, no separate overall GM award, no playoff-qualification requirement, no winning-record requirement — a
  manager below .500 may win if the complete formula ranks them first. The unified method itself remains a
  validation track (PR #1513, not promoted). This correction must not add a gate. No other award (OPOY, DPOY, ROY, positional, Points King, Trader,
  Waiver King, Champion, Playoff MVP, statistical awards) gains a record gate.
- Reason code `team_record_not_above_500` is retired for `team_record_below_500` (UI: "team below .500"); a .500
  team never receives it. A franchise with no decided games gets `team_record_unavailable` (UI: "no decided games
  yet") — never "below .500". Canonical rule: `docs/BRISKET_HONORS_ELIGIBILITY_SPEC.md` (2026-09-29 banner).
- Replay 2026-09-29: no published League MVP winner changed in either live league (2024, 2025 finalized; the 2026
  live leader is unchanged). Live race MEMBERSHIP widens as intended — .500 teams' players now race (e.g. a 2-2
  team's star moves from "outside the race" into the standings).

**Owner decision — League MVP requires team success (2026-09-26).**
Binding; supersedes the 2026-08-13/14 "player MVP has no hard playoff-field / >.500 gate" rule wherever it appears
(`docs/PLAYER_IMPACT_WAR_MVP_SPEC.md` §7, `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §2, the Honors spec's
2026-08-14 amendment, the spec index, manifest and sync records — all reconciled in the same change).
- **League MVP** = elite player performance on a successful fantasy team. Eligible only when the credited fantasy
  franchise is BOTH in the championship playoff field AND above .500 *(record half superseded 2026-09-29:
  .500 or better — see the correction above)*:
  - **live** — in a qualifying position under the league's real rules if the season ended at the latest
    completed scoring period (canonical standings order × the league's own `playoff_teams`), with an official
    regular-season winning percentage ~~strictly above .500~~ .500 or better (host W/L/T, median games counted as the host counts
    them);
  - **finalized** — actually qualified for the championship playoffs (real bracket) and finished ~~above .500~~ .500 or better.
  - An unknown field is `mvp_eligibility_unverified`; nobody eligible is `no_eligible_mvp_candidate`. Never a
    widened field.
- **Not gated:** Offensive / Defensive Player of the Year (the best individual performances regardless of the
  fantasy team's record), both Rookie of the Year awards, positional awards, Waiver King, Trader of the Year,
  Weekly Hammer, Bad Beat, Top Offense / Defense and every other award unless separately specified. Manager of
  the Year keeps its own validated team-success logic, unchanged.
- **The gate is eligibility, not measurement**: the VORP metric is untouched and the OPOY / DPOY labels stay.
- **Known partial:** the Honors spec §7 per-franchise-week split for traded players is not yet implemented; the
  player is credited to, and gated on, his most recent franchise (the existing award attribution).

**Owner decision — try BALLDONTLIE as a Game Day live-state provider (2026-09-27).**
ESPN's scoreboard refuses us (403) and its block is not to be bypassed. Validate BALLDONTLIE NFL's real
capabilities, build it as an adapter behind the ONE live-state owner (`src/nfl_data/live_game_state.py`), run it
in SHADOW first (no forecast influence), and promote into the selector only on real live-game evidence. The
outcome is classified A (full) / B (partial: score + status, no trustworthy clock) / C (unsuitable) from that
evidence. There is no wall-clock inference; missing stays missing. Sleeper keeps fantasy scoring. SportsDataIO's
adapter is kept and not activated. Nothing is purchased without owner approval. Record and status:
`docs/game-day/BALLDONTLIE_LIVE_STATE_EVALUATION.md`.

## Added 2026-09-26 — Championship / playoff odds methodology: two owner decisions awaiting approval

Recorded by the League Hub championship input-integrity unit (`claude/championship-input-integrity`; claim in
`docs/WORK_CLAIMS.md`). That unit fixes only factual defects: D1 (a failed NFL player download published coin-flip
odds), D4 (live-week matchups frozen as finals) and D5 (a non-default league simulated on the default league's
rosters). The two items below are **methodology**. They are **not changed** and **not authorized**. Each waits for an
explicit owner decision; only `docs/EXECUTION_PLAN.md` can authorize the work.

- **D2 — ROS strength counted twice in the weekly mean.**
  - **Current:** `src/ros/playoff_sim.py::_build_team_distributions` sets the mean to `pre-sim mean × (1 + 0.2z)`.
    The best-ball pre-sim is already drawn from the same ROS roster values, and the ROS z-score multiplier is then
    applied on top.
  - **Observed** (dynasty_main, 2026-09-26, inputs intact):
    - Brent's championship odds are 99.45% with the multiplier and 84.6% with it removed.
    - Weekly log-loss on finalized weeks 1–2 is 0.928, against 0.693 for a coin flip. That is a small sample.
  - **Proposal:**
    - drop the multiplier when the pre-sim supplies the mean;
    - fit the points model to league scoring;
    - add a per-draw team shock.
  - **Validation before any promotion:** run the change as a challenger, scored by weekly log-loss / PIT on
    finalized weeks. Champion ≠ challenger.
- **D3 — median games ignored.**
  - `dynasty_main` sets `league_average_match = 1`, so each week counts as two games: head-to-head plus the
    league median.
  - The median W/L is excluded from both the current record and the simulated weeks. The host's record therefore
    counts twice as many games as the simulator's.
  - Measured 2026-09-26: after two finished weeks the host shows 4-0 where the simulator shows 2-0.
  - Deciding whether and how the median game enters seeding is a methodology decision.

## Added 2026-09-26 — Adaptive Learning / Continuous Model Improvement (owner directive)
The owner wants Calculator to become **empirically self-improving wherever learning is legitimate**: preserve point-in-time observations, forecasts, recommendations, decisions/non-decisions and outcomes; evaluate what happened; run bounded challengers; and promote a different production methodology only when it clears the applicable evidence and governance gates. “Machine learning” is acceptable shorthand, but the product direction is broader: calibration, statistical learning, model selection, behavioral learning, time-series methods and other evidence-based adaptation are all eligible when they fit the question.
This is **not** authorization for a monolithic ML platform or for uncontrolled self-modifying production models. Deterministic facts and rules — scoring arithmetic, league rules, roster legality, canonical identity, ownership, exact lineup eligibility/assignment, provenance, timestamps and missing-vs-zero semantics — remain deterministic.
**Canonical reconciliation.** The existing native governance umbrella is `C10-ML-01` plus the P6 model/methodology acceptance profile. Domain learning stays with its current owner rather than moving to a new ML backlog: `C1-HIST-01` (point-in-time evidence), `C5-GD-02` / Game Day, `C5-ROS-01` / #854 projections, `C5-PLAY-01` playoff calibration, `C5-POW-01` Power validation, `C6-FRESH-01` / #1423 freshness, `C4-FAAB-01/02` + `C4-WAIV-01` FAAB/waiver evidence, `C6-MGR-01` manager behavior, `C6-ANA-01` analyst evidence, `C7-DESK-01` / `C3-REPLAY-01` decision evaluation, `C7-POST-01` posture and `C7-ALERT-01` alerts. No new native ID is minted by this intake.
**Existing precedent.** `src/model_registry/` already provides champion/challenger/rejected/retired model versions, pinned training-input fingerprints, held-out evidence, promotion records and rollback. Hill Autopilot is the existing bounded automatic-promotion example. It is **not** blanket permission for other model families to auto-promote. *Refined 2026-10-01 (owner methodology decision 1, entry "Owner methodology decisions — final" below): Hill Autopilot itself may promote OFFENSE automatically only with at least one genuinely independent validation target; until one exists it is `AUTO_PROMOTION_BLOCKED: no_independent_validation_target`.*
**Operating rule.** Continuous archival capture, deterministic evaluation, shadow challenger refits, drift detection and scorecard updates may eventually be automated where authorized. Production promotion remains gated. Automatic promotion is allowed only when the owner has approved a deterministic, fail-closed promotion policy for that exact model family, with rollback and a durable promotion record.
**First-wave planning priority:**
1. Game Day calibration scorecards over the already-deployed prediction archive;
2. projection-family / ensemble evaluation under #854, beginning with simple independent-family baselines;
3. shadow evaluation of whether content age actually degrades task performance before changing the current freshness policy;
4. rolling-origin Power / playoff validation;
5. FAAB / manager behavioral learning only after enough prospective, censoring-aware evidence exists.
The private decision/offer journal (research R14) remains a **CANDIDATE**, not implementation-authorized scope. It is the clean prospective path for rejected/countered/expired offers and considered-but-not-sent decisions that cannot be inferred from completed trades alone.
**Detailed reconciliation and proposed first batch:** `docs/research/ADAPTIVE_LEARNING_2026-09-26.md`.
**Authority boundary:** this entry authorizes durable planning/reconciliation only. It does **not** change production weights, activate sources, promote challengers, auto-retrain a live model, authorize autonomous roster transactions, decide R40/R44, or alter any existing owner-approved methodology. `docs/EXECUTION_PLAN.md` is unchanged and remains the sole implementation authority.
> **Superseded in part 2026-10-01** by the Adaptive Learning / Continuous Improvement Master Roadmap entry below: the first-wave order above is replaced (Valuation Trust and completed-trade learning first; Game Day and playoff NEXT), and dependency-ready units are now implementation-authorized in `docs/EXECUTION_PLAN.md` §0. The deterministic boundary, the promotion boundary and R14's CANDIDATE status are unchanged. Supersession table: `docs/research/ADAPTIVE_LEARNING_2026-09-26.md` §17.

**Zero-open-PR reconciliation — owner directive 2026-09-26.** Every open PR is merged, or closed with a
harvest receipt; future scope lives here, in native issues or in specs, never in an open PR.
- **#1425** (freshness orchestration planning) → owner contract lives in open issue **#1423** (T-NEW-21):
  24/7 adaptive staggered freshness orchestration; planning NEXT/P1; C4 source-health owner; not authorized.
  Whether to mint a manifest row (`C4-SRC-04` was proposed) is decided when Lane C is authorized.
- **#1419** (unified completion portfolio) → absorbed by #1421 plus the batch-ranking rules harvested into
  `docs/BRISKET_IDEAS.md` §8; issue **#1418** is the durable record.
- **#1395** (#1391 capture probe) → closed; contrary to the owner's 2026-09-19 decision to accept the evidence
  instead of adding probe instrumentation. Reopen only on a new owner request.
- **#1416** (pick lifecycle + asset quantity planning) → implemented by #1442 (`bfdb238d8`) and #1441
  (`53109028c`); its ACTIVE-pick contract/spec wording was harvested with shipped status.
- **#1406** (DLF native-value refusal) → superseded: rank-with-empty-value shipped in #1411, and DLF Values as a
  non-voting board in #1424/#1430; the root cause is recorded in `docs/sources/SOURCE_FRESHNESS_WEIGHTING.md`.
- **#1407** (refresh-unit fixes) → both defects still reproduced on main; the script and test fixes were re-landed
  in the cleanup harvest PR.
- **#1383** (Week-1 fetch scripts) → obsolete; Weeks 1–3 come in through the public-league snapshot.
- **#1344** (harness progressive disclosure) → stale; the startup-script `grep || true` fix was harvested. Moving
  Agent OS sections out needs a fresh audit (the repo-harness-auditor skill), not this branch.
- **#1399**, **#1381** → future scope recorded below.

### League Comparison / scoring lab — live 2026 evidence — owner directive 2026-09-23
Owner requested that the scoring-comparison work begin taking **2026 scoring** into account now, while the season is still in progress. Required outcome: preserve the existing 2022–2025 historical evidence, ingest available 2026 regular-season production through the canonical nflverse→Sleeper fallback, and make the current season influence the combined comparison **without pretending a partial season is a completed year**. The live-season basis/progress must be visible in the payload/UI, and the treatment must converge to ordinary full-season semantics when all 17 modeled weeks are present. Tracked as `LC-2026-LIVE` on `codex/league-comparison-2026-live`.
  - **Status 2026-09-26 (zero-open-PR reconciliation):** NOT implemented on main (`config/league_comparison.json`
    seasons still 2022–2025). Its implementation PR #1399 was closed unmerged:
    - it counted every Sleeper week key as observed, so an in-progress NFL week counted as a full week, and cached a
      week for 7 days;
    - its CI failed.
  - **A correct port must:**
    - count only FINISHED weeks via the canonical host-clock gate (`metrics.final_weeks` / `last_scored_leg`, never raw
      week keys);
    - never cache a week at or beyond that horizon;
    - reuse #1399's explicit-weight combiner (`combine_metrics_weighted` / `_season_evidence_basis`) and payload
      fields (`seasonStatus`, `weeksObserved`, `seasonWeight`);
    - bump the methodology-version pin deliberately.
  - The donor branch is `codex/league-comparison-2026-live`.
  - Awaiting an `EXECUTION_PLAN` authorization pointer.

**Power Rankings — median-aware Sleeper record horizon guard (recorded 2026-09-26, latent, not authorized).**
- **Latent defect.** `src/ros/power_v2.py` (~`:1257`) trusts Sleeper's W-L record with no horizon check.
- **Correct guard.** Games = finished weeks × (2 when `medianGameEnabled`, else 1). Otherwise fall back and flag it.
- **Why not #1381.** PR #1381's equality check (`sleeper_games == scored_games`) would reject every record in a
  median-game league and silently drop median games. It was closed 2026-09-26: its share-card change is contradicted
  by #1398, and its horizon mixing is mostly addressed by the finished-week gate.
- **Status.** Not observed in production (production shows `countedWeeks` [1, 2] with 4-game records). Needs an
  authorization pointer before implementation.

## Added 2026-09-29 — perishable-evidence capture audit (owner directive)
Owner instruction: identify any data that will be impossible to recreate later. When a needed evidence stream is not
being preserved, record it in Calculator Ideas / the canonical backlog with the minimum required capture path.
**Prefer capturing perishable evidence now over reconstructing it later with hindsight.**
- **Durable record:** `docs/BRISKET_IDEAS.md` §13. It holds the preserved-stream table, gaps G1–G8 (owner, what is
  lost, minimum capture path) and the already-lost list. It is not a second backlog.
- **Gaps map to existing native owners; no new ID is minted:**
  - G1 raw Sleeper weekly projections pruned after 4 weeks → `C5-GD-02` / `C5-ROS-01` (#854). This is the only gap
    with a dated loss clock: Week 1 raw logs go at the first collector tick of Week 6, ≈2026-10-13.
  - G2 KTC Trade Database window → `C4-MTL-02`.
  - G3 KTC unselected format variants → `C1-SRC-01`.
  - G4 as-known injury/news → `C6-ANA-01` / `C7-ALERT-01`.
  - G5 draft-time state → `C7-DRAFT-02`.
  - G6 league settings beyond scoring → `C1-RET-04` / `C1-HIST-01`.
  - G7 backup coverage → `docs/retention/RETENTION_REGISTER.md`.
  - G8 served recommendations → the existing R14 / Adaptive Learning record.
- **Planning position:** G1 is NEXT (dated). G7, G3 and G4 are NEXT. G2 and G6 are LATER. G5 is LATER but must land
  before the 2027 rookie auction.
- **Authority:** all gaps are **NOT AUTHORIZED**. Capture is not implementation authorization, and
  `docs/EXECUTION_PLAN.md` is unchanged.

## Added 2026-09-29 — Rookie Auction Room: build it now, mock-first, live-gated (owner directive)

| Priority | Issue | Area | Required outcome | Status |
|---|---|---|---|---|
| P1 owner build directive | Owner directive, 2026-09-29 | Rookie auction room (extends `C7-DRAFT-03` / `C7-U12`) | A native shared slow rookie auction hosted by Chase Upside: 12 seats, rookie-only, six rounds, at most 12 open lots, points-for (lowest first) nomination order supplied by the owner, $0 opening bids and $0 wins, whole-dollar private proxy bidding (A $50 vs B $39 → A at $40), per-seat budgets from current 2027 draft capital with commissioner overrides, 8 AM–9 PM America/New_York activity, early end when all money is spent, persistence across restart/deploy, solo/multiplayer mocks incl. invited non-league testers, notifications (esp. last active hour), live Perfect Draft integration. Official launch stays OFF until separate owner approval. Full contract, binding-vs-proposed rules and milestones: `docs/auction/ROOKIE_AUCTION_ROOM.md`. | MOCK READY — deployed 2026-09-29 (#1523/#1524/#1526/#1528); official launch still owner-gated (see docs/auction/LAUNCH_CHECKLIST.md) |
| P1 owner clarification | Owner, 2026-09-29 | Rookie auction room — money | LEADING BIDS RESERVE MONEY: $50 unspent while leading at $45 ⇒ only $5 available elsewhere; reserve every current winning price, release on a genuine outbid, convert once on winning; private maxima never execute past the currently affordable amount; two simultaneous requests cannot spend the same dollars; enforced server-side, preserved across restarts; Perfect Draft uses the same available balance; $0 bids remain legal; explicit regression tests for the example. Record: `docs/auction/ROOKIE_AUCTION_ROOM.md` §2 "Money". | IMPLEMENTED + deployed: engine reservation (tested incl. the exact $50/$45 example, a thread race and restart) and Perfect Draft uses the same spendable (#1526) |
| P1 owner directive (AUC-002) | Owner, 2026-09-29 | Rookie auction room — notifications | Native standards-based Web Push from the existing server (reuse `src/api/push_delivery.py` / pywebpush + VAPID, `frontend/public/sw.js`, the manifest and the SMTP email owner — ONE transport, no OneSignal/FCM/SMS/paid service), a durable in-app inbox, optional verified-email backup. Device-aware iPhone Home Screen / Android setup, targeted test notification (service-accepted ≠ displayed; tester confirms), status, recovery, preferences. Event set, proxy-truth rule (alerts from the net committed transition — A $50 vs B $39 never alerts A "outbid" then "leading again"), active-hour deadlines + America/New_York quiet hours, deadline-revision-keyed reminders invalidated by extension/settlement/pause, transactional outbox + background worker (never inside the bid transaction), dedup/retry/Retry-After/expired-subscription cleanup, account/device-owned subscriptions with CSRF/SSRF protection, generic lock-screen previews, mocks on a fake transport by default with opt-in labelled [MOCK] pushes. Requires real iPhone Home Screen + Android Chrome device tests reported as simulated / service-accepted / device-observed / user-confirmed. Record: `docs/auction/ROOKIE_AUCTION_ROOM.md` §9 (AUC-002). | IMPLEMENTED + deployed (#1524); production VAPID keys NOT configured yet (owner action); real iPhone/Android delivery not yet observed |

Rules the owner has not yet confirmed for an OFFICIAL room (proposed mock defaults: 65 active-hour
clocks, one-active-hour extension, 13-active-hour nomination timeout with audited pass, earlier-bid
tie rule, withdrawal policy, outage policy, six-rounds = six nomination opportunities) are listed in
`src/auction/rules.py::PROPOSED_RULE_KEYS` and must be confirmed together on the room's
rule-confirmation screen before an official room can start. They do not block mocks.

## Added 2026-09-30 — harness recommendations accepted ("Whatever you recommend")

The owner accepted the recommendations that closed the 2026-09-30 harness reconciliation
(full record: `docs/engineering/AGENT_HARNESS_EXTERNAL_GUIDANCE_RECONCILIATION_2026-09-12.md` Part H;
authorization: `docs/EXECUTION_PLAN.md` "Served build identity — owner authorization, 2026-09-30").

| Item | Disposition |
|---|---|
| Merge the reviewed harness PRs #1536 (Steward evidence validation + record) and #1542 (CI-backed test evidence) once green | DONE — both merged after green CI (2026-09-30) |
| Served build identity: `/api/status` reports the running commit; the deploy smoke test fails on a mismatch (Part H.5 item 1, Priority 3) | DONE — #1543 merged, deployed and production-verified (2026-09-30) |
| Re-run the closed PR #1344 CLAUDE.md/skill progressive-disclosure audit | DEFERRED — high collision with active lanes, low current value; revisit when the active lanes quiet |
| Remaining Part H.5 queue (typed contract slice, provenance views, parser replay, declarative boundaries, request/snapshot identity) | NOT AUTHORIZED — backlog only |
| Pin the box to the guarded SHA on manual deploys (`deploy.yml` passes the raw `deploy_ref`; the box resolves a branch name after its own fetch, so a manual deploy of `main` can ship a newer commit than the guard and validate job judged — found by the build-identity review; the new check now reports it) | AUTHORIZED 2026-10-01 (owner decision C) — Batch 2 Integration unit |

## Added 2026-09-30 — DFS: dedicated daily-fantasy section (owner directive)

| Priority | Issue | Area | Required outcome | Status |
|---|---|---|---|---|
| P1 owner build directive | Owner directive, 2026-09-30 | DFS (new product family; `docs/dfs/`) | A contest-aware DFS decision system inside ChaseUpside for NFL/NBA/NHL/MMA on DraftKings/FanDuel: sport → platform → slate → contest → objective → build N or recommend a count → full manual constraints → Optimal Lineup / Build Portfolio → explanations + uncertainty → valid exports → permitted late swap → results review. Research every supplied website (74), sportsbook (6) and podcast (29) seed; no guaranteed-profit claims; honest capability states; DFS isolated from dynasty valuation; no purchases, wagering, contest entry or account automation. Zero-loss requirement map `docs/dfs/TRACEABILITY.md`; phases `docs/dfs/ROADMAP.md`. | PHASE 1 SLICE BUILT on `claude/dfs-foundation` (NFL DK/FD research mode, owner file imports, MILP baseline, exports); rule/export verification OWNER-BLOCKED (official pages refused automated access 2026-09-30) |
| P1 owner addendum | Owner, 2026-09-30 (Platform / Slate / Contest integration) | DFS — platform & slate ingestion | Platform + slate ingestion becomes first-class: one canonical ChaseUpside slate model fed by platform adapters (licensed feeds such as SportsDataIO where verified; official/user-downloaded DraftKings/FanDuel CSV always; MMA via CSV until a licensed source is verified); never a production dependency on unofficial DK/FD endpoints, scraping or account automation; slate != contest with a canonical contest profile and quick/exact/import creation modes; visible per-class freshness; source-cost registry; failover that never turns failure into zeros; roadmap reordered to Phases A-H (platform/slate first). Traceability `docs/dfs/TRACEABILITY.md` DFS-ADD-01..31. | RECONCILED; Phase A slice in progress on `claude/dfs-contests`. BLOCKED: SportsDataIO key/plan (paid, owner approval), official DK/FD templates |
| P0 PERMANENT owner requirement | Owner, 2026-09-30 (third DFS directive: "zero manual CSV imports") | DFS — automated data | The PRIMARY DFS workflow requires ZERO manual CSV imports: open /dfs → pick platform/sport/slate → players, salaries, positions, teams, games, start times, eligibility, projections, injury/market context already populated with honest per-class freshness → optimize → export. Manual import survives only as emergency fallback / testing / sources with no legitimate automated path / owner override, under "Advanced". Automated acquisition via legitimate sources only (no prohibited scraping, no invented endpoints, no DK/FD private APIs — addendum constraint unchanged), freshness-aware scheduled refresh, slate auto-discovery, identity via the Calculator owner, multi-source raw-stat projections rescored per platform with an independent-family ensemble, sportsbook/prop + injury/role engines as controlled evidence, point-in-time archive of everything, multi-sport shared core, per-source rights/cost records, no spending without approval. Owner acceptance test: DK NFL Main Slate usable with nothing downloaded or uploaded; ultimately DK/FD × NFL/NBA/NHL/MMA. Requirement IDs `docs/dfs/TRACEABILITY.md` DFS-AUTO-01..24. | ACTIVE on `claude/dfs-auto` (stacked on the modelling chain). BLOCKED for upload-ready exports: platform player IDs have no permitted free source — needs a licensed slate feed (owner approval) |
| P3 test-infrastructure debt (non-blocking) | Owner, 2026-09-30 (after #1534 CI) | Test isolation | TEST ISOLATION — identify any test/fixture that mutates shared `server.app`, route tables, module state, environment-derived route registration, or `sys.modules` without restoring state. **Update (same day):** the specific failure that prompted this item is now explained by a deterministic cause, not test-order state — FastAPI 0.141 (CI, `requirements.txt ~=0.141.1`) keeps included routers as an `_IncludedRouter` wrapper without `.path`, so walking `app.routes` sees no included routes; the local 0.135.4 flattened them. Reproduced on 0.141.1 (routes walk → [], `app.openapi()` → the DFS paths); the test now reads `app.openapi()` (#1534). No evidence of shared-state contamination remains from that incident, but it was not the subject of a full audit, so the general item stays open at low priority alongside the related prior leak `docs/python-coverage-audit.md` D-5. Also worth a guard: local environments can drift from CI's pinned FastAPI. Non-blocking unless contamination causes another product test failure, affects production behaviour, or a short deterministic reproduction is found. | OPEN — low priority |

## Added 2026-09-30 — Valuation advancement + comprehensive Signals (owner directive, #1555)

Durable direction: issue #1555 (incorporated into #792), extended 2026-09-30. Requirement map, lead
statuses and next batch: `docs/valuation/VALUATION_ADVANCEMENT_MAP_2026-09-30.md`. Signals record:
`docs/sources/SIGNALS_FANTASY_INTEGRATION.md`. Evidence: `docs/valuation/evidence/value-replay-2026-09-30/`.

| Item | Disposition |
|---|---|
| Keep three capabilities distinct: fundamental dynasty value, market price, roster-specific trade impact (#792) | CAPTURED — map §C |
| Reproducible current-value evidence, Coker first, with contrasts; never hard-code a Coker increase or target KTC/Signals agreement | IMPLEMENTED — pinned replay + evidence (map V1) |
| KeepTradeCut: owner holds permission to scrape all KTC data — record as owner-reported authorization, stop treating as absent, invent no document | RECORDED — spec §19.2, manifest `F-EXT-01` COMPLETE |
| Signals is a comprehensive data-integration workstream aimed at an active validated source (stage 5 where justified), plus a separate product-capability workstream; supersedes the optional/benchmark-only destination while keeping its access/validation/privacy/lineage rules | CAPTURED — permission RESOLVED 2026-10-01 (owner-attested; the permission request is superseded, never sent); collection in Batch 2 Unit A |
| Source-integrity leads (cross-subset freshness, information age, weight-blind outlier filter, lineage, native-vs-rank scale, confidence haircut, ingestion integrity) | TRIAGED — statuses in map §D; V2-1 DONE (#1565, production-verified 2026-10-01); others sequenced in map §G |
| BDVM formula/semantics audit (pick median, malformed timestamps, placeholders, overlapping risks, market dependence) | DOCUMENTED — map §E; timestamp fail-open fixed and pick labels corrected (own PRs) |
| Independent fundamentals baseline, own completed-trade price model, three-part decision UX, evaluation | CAPTURED — map V5–V8; V5 milestone defined |
| Permanent parallel Premium UI each batch | ACTIVE — BDVM truthful labels (Lane 6) |

## Added 2026-10-01 — #1555 Batch 2: authorized Signals integration, valuation reliability, scoring coverage, Lane 6

Owner statement (2026-10-01): *"I have explicit permission to use signals how I see fit."* This is recorded
as owner-attested Signals authorization; no permission document or provider correspondence is invented.
Map: `docs/valuation/VALUATION_ADVANCEMENT_MAP_2026-09-30.md` §G. Signals record:
`docs/sources/SIGNALS_FANTASY_INTEGRATION.md` §1/§2.

| Item | Disposition |
|---|---|
| (A) Build Signals toward an active validated source: real ingestion + truthful second opinion; numeric participation through promotion stages | AUTHORIZED — Unit A |
| (B) Outlier handling + sparse-source confidence are one pipeline problem; "one family ⇒ 30% of the estimate" rejected; express thin coverage as uncertainty | AUTHORIZED — Unit C, disabled/shadow challenger; promotion needs candidate approval |
| (C) Manual-deploy SHA pinning — one resolved immutable commit through validation, build, guard, deploy and verification | AUTHORIZED — Integration unit (supersedes the 2026-09-30 "not authorized" follow-up) |
| (D) Lane 6 active in parallel: information age, provenance, BDVM partial-scoring notice, Signals second opinion | AUTHORIZED — Lane 6 unit |
| (E) Implement, test, independently review, merge and deploy bounded non-promotional units when gates pass; candidate-specific approval for new canonical models/weights stays in force | RECORDED |
| Hill / native-source alignment audit | AUTHORIZED — Unit B (read-only; calibration only as a registry challenger) |
| BDVM scoring-coverage follow-through (census, sign-aware wording, exact mappings only where fields exist) | AUTHORIZED — Unit D |

## Added 2026-10-01 — Signals account connection — passwordless email login (owner directive)

The Signals account signs in with an emailed one-time code, not a password. Owner directive: an
owner-controlled connection — the owner signs in in a dedicated browser context; only the
Signals-specific session is captured and stored outside the checkout on the prod box; renewal is
unattended with one lock-protected renewal owner; revoked/expired credentials stop collection and send
one deduplicated reconnect notice; codes, cookies and tokens are never pasted into chat, issues or
commits and no login email is triggered from code. Permission is already resolved (owner-attested, see
above) and is not reopened. Record: `docs/sources/SIGNALS_ACCOUNT_CONNECTION.md`.

| Item | Disposition |
|---|---|
| Owner-controlled Signals connection: connect / status / reconnect / disconnect / provision / renew; auth health separate from data freshness; fail-safe renewal and failure classes | IMPLEMENTED on `claude/signals-account-connection` (not merged). Owner's first real sign-in, box provisioning and observed renewal still OWNER-PENDING |

## Added 2026-10-01 — Valuation Trust Program / Batch 3 (owner directive)

The owner's highest priority: values he trusts over any single outside source, earned
through evidence, never tuned toward KTC, DLF, FantasyCalc or anyone else. The canonical
market, BDVM fundamentals, the completed-trade market and roster impact remain separate
concepts. Full unit list and promotion policy: `docs/EXECUTION_PLAN.md` →
"Valuation Trust Program — Batch 3".

| Item | Disposition |
|---|---|
| A source trust census, generated from canonical state (no subjective score) | AUTHORIZED, wave 1 |
| Replace "dynamic weights" with a leakage-safe source-quality evaluator; equal-family champion; preregistered challengers | AUTHORIZED, wave 2 |
| Hill trainer / Autopilot substrate repair before any KTC/DLF scale change; then a clean preregistered rerun | AUTHORIZED, wave 1 → 3. *Refined 2026-10-01 (owner methodology decision 1): automatic OFFENSE promotion additionally requires an independent validation target; the dependent-board holdout gates stay required but are necessary, not sufficient (`claude/hill-autopilot-independent-gate`).* |
| Sparse-evidence estimator: central estimate separate from uncertainty; censor-aware coverage; solves 4600→1380 without the deep-board explosion | AUTHORIZED, wave 2 |
| Joint robust filter as a real shadow experiment with an archived ledger | AUTHORIZED, wave 2 |
| Ingestion / lineage integrity sweep across every voting family | AUTHORIZED, wave 2. *Refined 2026-10-01 (owner methodology decision 3): #1599's post-hoc dependence thresholds and labels are descriptive history only, never prospective methodology; the next dependence classification runs under the preregistered `lineage-policy/v1`.* |
| Signals authenticated inventory once the owner session exists (second opinion until comparable and evaluated) | AUTHORIZED, access-dependent |
| Completed-trade market benchmark: KTC Trade Database + Sleeper ledger, dedupe, topology, then a shadow latent-price model | AUTHORIZED, wave 1 (acquisition) |
| BDVM measured fundamental engine: fumble recovery, source vocabulary, reception-distance and first-down components, horizon-aware projection evaluation, prior calibration | AUTHORIZED, waves 1 and 3 |
| Market-vs-fundamental disagreement matrix and source trust scorecard (no single magic score) | AUTHORIZED, wave 3 |
| ADDENDUM 2026-10-01: Sharp-discovered Sleeper league trades (whole qualifying leagues, not only Sharp managers) feed the Market Trade Ledger alongside KTC, IDP as a first-class objective. Reuse the existing Sharp acquisition owner and its cursors. Real per-league format captured from Sleeper. Raw observations kept apart from canonical underlying trades; `MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md` §19 dedupe hierarchy; a shared `underlyingTradeId` so a Sharp trade cannot vote twice; separate reporting of raw / unique / duplicate / probable / possible counts and IDP coverage | AUTHORIZED, Unit I (in progress) |
| ADDENDUM 2026-10-01: every completed trade is format-normalized or excluded from target-league pricing. Target is `dynasty_main`, read from the canonical league/scoring/roster owners (actual scoring card, never the label). One canonical format fingerprint with inspectable per-dimension comparability. Exactly one disposition each: NATIVE_COMPARABLE, VALIDATED_TRANSFORMABLE or TARGET_UNSUPPORTED. Unknown format is not comparable. No global format multiplier. Translators must validate out of sample (paired same-source markets, then cross-format trades, then BDVM as a structural prior only). Later: a format-aware latent-price shadow model with `transactionMarketValueGeneric` vs `transactionMarketValueTargetLeague`; native evidence dominates translated evidence | AUTHORIZED. Unit I builds the fingerprint, dispositions and plumbing; all non-native observations are TARGET_UNSUPPORTED until a translator validates. Translators and the latent-price model follow as shadow challengers *Superseded in part, 2026-10-01 (continuation instructions): four dispositions — BROAD_CONTEXT added for verified-dynasty trades whose material format dimension differs, is unknown, or has no validated translator (`targetPriceAuthority = 0`), TARGET_UNSUPPORTED narrowed to hard insufficiency; its own PR after the bootstrap census (plan §35 T1).* *Superseded further, 2026-10-01 (owner methodology decision 2): NATIVE_COMPARABLE keeps the strict point-in-time bracket; BROAD_CONTEXT has two sub-kinds — timing-limited (later/final settings match the target on every observed material axis, but nothing brackets the format at transaction time) and format mismatch; season-final or post-trade captures never make a trade NATIVE (plan §35 T8).* |

## Added 2026-10-01 — Draft Capital year selector (owner request)

Owner request (2026-10-01): add an "All Years | <years>" selector to the EXISTING Draft Capital page
(`/league?tab=draft-capital`; no new per-year pages). Years are derived from the real pick data, never
hard-coded. The selector changes which picks count, never how they are valued.

| Item | Disposition |
|---|---|
| Year selector on the existing page; default All Years; `?year=` URL state surviving reload/back/forward/direct links; invalid/obsolete year falls back to All Years; legacy `/draft-capital?year=` forwards | IMPLEMENTED — `claude/draft-capital-year-selector` |
| Available years derived from the pick inventory, following each path's existing retirement policy (workbook: completed-draft bump; fallback: `draft_class_evidence` #1414) | IMPLEMENTED — `availableYears` |
| Per-year team capital = SUM of the same canonical per-pick dollars (one $1200 pool, never renormalized per year); All Years unchanged; per-year re-rank, totals, bars, pick lists | IMPLEMENTED — `teamTotalsByYear` / `yearSummaries` (`src/api/draft_capital_years.py`) |
| Unpriced picks stay excluded and visibly counted; an all-unpriced team-year reads "—"/unranked, never $0; zero-pick teams stay with "No {year} picks" | IMPLEMENTED |
| Future picks never imply known slots: Sleeper-derived boards show round only, labelled estimated | IMPLEMENTED |
| Optional compact per-team year breakdown in All Years | IMPLEMENTED (multi-year boards only) |
| Real data does not contain 2029 for either live league (dynasty_main workbook covers 2027 only; dynasty_new fallback covers 2027–2028) although Sleeper reports traded 2028/2029 picks and the canonical board prices generic 2027–2029 rows | OWNER DECISION NEEDED — extending either inventory changes how the $1200 pool is spread (All Years totals would move) |

## Added 2026-10-01 — Adaptive Learning / Continuous Improvement Master Roadmap (owner directive)

Owner directive: Adaptive Learning / Continuous Model Improvement becomes a **permanent architectural capability**
of Calculator. Not "a neural network everywhere": preserve what was known at a point in time, what Calculator
predicted and recommended, what was done or not done, what happened afterward and how accurate each prediction,
recommendation, model and source was; then improve future models through controlled champion/challenger
evaluation (observe → predict → decide → outcome → evaluate → challenger → out-of-sample validation → promote if
better → monitor). **Facts and rules do not learn.** The directive is explicit owner authorization to implement
the dependency-ready foundations and roadmap units. It is not authorization for an unvalidated model to change a
production output; promotion keeps its P6 evidence gates.

**Delivery note:** the message was truncated after the heading "9." Sections 1–8 are recorded. **Sections 9+:
truncated in delivery — pending owner re-send.** Nothing has been inferred about them.
**Update, same day: RECEIVED.** The owner re-sent the full directive; sections 9–31 are recorded in the next
entry and reconciled in plan Part III. The marker above is kept for traceability.

**Detailed record (incorporation pointer):** `docs/research/ADAPTIVE_LEARNING_2026-09-26.md` Part II (§16–§25),
extended in place; no competing plan. Authorization: `docs/EXECUTION_PLAN.md` §0, "Adaptive Learning /
Continuous Improvement — owner directive, 2026-10-01". Governance owner: `C10-ML-01` + P6; no new manifest ID.

| Directive section | Required outcome | Canonical owner | Planning position · authorization |
|---|---|---|---|
| §1 Reconcile into the real roadmap | extend the 2026-09-26 plan; no standalone ML backlog | `C10-ML-01` | DONE (this reconciliation) |
| §2 One shared foundation | common identifiers, contracts and evaluation receipts over native stores (OBSERVATION … DRIFT); versioned feature dictionary; no generic feature store | `src/history/`, `src/model_registry/`, P6 | NOW — AL-0, AUTHORIZED (dependency: #1588) |
| §3 Permanent learning governance | point-in-time, champion/challenger, shadow first, holdouts, uncertainty + shrinkage, no silent self-promotion, six drift classes (drift → reevaluation, never promotion) | P6, `MASTER_PRODUCT_PLAN.md` §3.4/§3.8 | BINDING now |
| §4 Valuation Trust / source learning | learn source utility (unique info, lead/lag, noise, cohorts, correlation, decay, transaction fit); evidence-based base authority with shrinkage toward equal-family; never "accuracy = agreement with KTC"; never wire the old dynamic-weight fitter | Batch 3 (`F-SRC-01`, `C6-FRESH-01`) | NOW — AL-1, AUTHORIZED; maps #1584/#1588/#1589/#1590/#1591/#1592 |
| §5 Completed-trade / IDP market | raw vs unique trades, explicit dedupe states, exact format capture, one disposition per trade, translation hierarchy, shadow format-aware latent price model for `dynasty_main` | `C4-MTL-01/02/03`, `C1-ACQ-01`, `src/sharp/` | NOW — AL-2 after #1586 (format census first), AUTHORIZED |
| §6 BDVM + projection learning | archive every projection before the event; provider × position × stat × horizon × regime evaluation; equal-family ensemble champion; component calibration; MEASURED/MECHANICAL/PRIOR labels | `C5-BDVM-01`, `C5-ROS-01`/#854, Batch 3 J2 | NOW (archive/eval) / NEXT (ensembles, calibration) — AL-3 |
| §7 Game Day learning | archive every generation; Brier/log loss/reliability/MAE/interval coverage by game state; shadow challengers; no promotion on one week | `C5-GD-01/02` | NEXT — AL-4 |
| §8 Playoff / title learning | archive every point-in-time forecast; season-end calibration; calibration challengers before any simulation rebuild | `C5-PLAY-01` | NEXT — AL-5 |
| §9+ | not received at first delivery — **RECEIVED by re-send 2026-10-01** | see the next entry | RECONCILED — next entry ("sections 9–31 + continuation instructions") |

## Added 2026-10-01 — Adaptive Learning master roadmap, sections 9–31 + continuation instructions (owner re-send)

The owner re-sent the full Adaptive Learning / Continuous Improvement Master Roadmap. Sections 1–8 are identical
to the entry above. Sections 9–31 and the accompanying continuation instructions are new, and the continuation
instructions are binding campaign sequencing. **Product vision, verbatim in substance:** Calculator should
accumulate *experience*, not merely features: every week, game, projection, trade, bid, draft, source update and
settled decision should let it evaluate its own assumptions. It is a continuously measured, evidence-driven
Calculator that gets harder to fool, not an opaque AI that changes numbers on its own.

**Detailed record (incorporation pointer):** `docs/research/ADAPTIVE_LEARNING_2026-09-26.md` **Part III (§26–§38)**,
extended in place. Perishable-evidence audit: `docs/BRISKET_IDEAS.md` §13.4. Authorization:
`docs/EXECUTION_PLAN.md` §0, "Adaptive Learning — sections 9–31, Wave 1 and campaign sequencing (owner re-send,
2026-10-01)". Governance owner `C10-ML-01` + P6; no new manifest ID.

| Directive section | Required outcome | Canonical owner | Planning position · authorization |
|---|---|---|---|
| §9 Power | descriptive and predictive objectives kept separate; evaluate components vs future outcomes; never sacrifice the public narrative contract | `C5-POW-01` | Wave 2 — AL-7 |
| §10 Future picks | calibrated slot distribution; prospective evaluation; empirical annual discount curve | `C1-PICK-03` | Wave 2 — AL-6; capture AL-P4 in Wave 1 |
| §11 FAAB / waiver market | clearing-price learning, hierarchical manager → league → market, unseen losing bids never zero, four populations separate | `C4-FAAB-01/02` | Wave 3 — AL-8 |
| §12 Rookie auction | pre-sale state + clearing price; price curves, premiums, nomination and budget effects | `C7-DRAFT-02/03` | Wave 3 — AL-9 |
| §13 Sharp / Manager Scout | Sharp Score weights as champion, validated vs future outcomes; behavioral learning; sparse shrinkage; accepted trades alone cannot calibrate acceptance | `C4-SHARP-01`, `C6-MGR-01` | Wave 3 — AL-10 / AL-11 (R14 stays CANDIDATE) |
| §14 Trade recommendations | decision-time archive; multi-dimension outcome evaluation; never train to reproduce future canonical values | `C7-DESK-01` | Wave 3 — AL-13; capture AL-P5 in Wave 1 |
| §15 Roster utility | solver stays deterministic; learn contribution distributions without a new value engine | `C2-STR-01`, `C2-REPL-01` | Wave 3 — AL-12 |
| §16 Player development | point-in-time role / breakout / survival models vs future usage; may support BDVM, never market observations | `C6-UPP-01`, `C1-RET-08` | Wave 4 — AL-14 |
| §17 Analyst reliability | outcome resolution; reliability by analyst × claim type × horizon; content lineage; no universal score | `C6-ANA-01` | Wave 4 — AL-15 |
| §18 DFS | complete `docs/dfs/ROADMAP.md` Phase H; no second DFS learning system; chronological contest holdouts | `src/dfs/` | Wave 4 — AL-16 (pointer) |
| §19 Alerts | learn actionability, never engagement; fewer, better alerts | `C7-ALERT-01` | Wave 4 — AL-17 |
| §20 Adaptive acquisition | learned scheduling bounded by hard maximum-age floors | freshness owners | Wave 4 — AL-18 |
| §21 Perishable data is a critical path | extend the existing audit; capture first | `docs/BRISKET_IDEAS.md` §13.4 | Wave 1 item 4 — AL-P1…AL-P8 ranked; AUTHORIZED, not yet built |
| §22 Model Lab | backend / internal contract first; no confusing metrics for ordinary users; Lane 6 for user-facing confidence | `C10-ML-01` | Wave 1 item 5 — AL-0b |
| §23 Roadmap order | Waves 1–4, Wave 1 = Valuation Trust, completed trades + KTC + Sharp/Sleeper IDP, format normalization, Wave-1 perishable gaps, shared receipts, BDVM/projection archive | plan §28 | RECORDED |
| §24 Cadence | per family: observation / settlement / evaluation / refit / drift / promotion authority; retrain on evidence, never on a clock | plan §29 | BINDING |
| §25 Rejected challengers | retained as evidence with config, fingerprint, results, why it failed, cohort effects | plan §30 | BINDING (AL-0 / AL-1a) |
| §26 Explanation | learned influence changes carry evidence-generated reasons; Lane 6 displays | plan §31 | BINDING |
| §27 Testing / safety | standing test checklist; random split prohibited where time ordering matters | plan §32 | BINDING |
| §28 Authority | authorizes capture, receipts, evaluation, shadow challengers, scorecards, drift, domain loops, roadmap units; NOT autonomous trades / waivers / DFS entries, hidden recommendation changes, self-promotion, new paid data | `EXECUTION_PLAN.md` §0 | RECORDED |
| §29 Style | small coherent PRs: FOUNDATION / VALUATION / PROJECTIONS-BDVM / INTEGRATION / UI-Lane 6; independent math and privacy review | plan §32 | BINDING |
| §30 Completion standard | four closed loops in code on real data: SOURCE, TRADE, PROJECTION, MODEL GOVERNANCE | plan §34 | BINDING — none closed for a non-Hill family today |
| §31 Session deliverables | reconcile, audit, begin Wave 1, review, PRs, merge non-promotional work, keep challengers shadowed, continue | this reconciliation + campaign | IN PROGRESS |
| Continuation instructions | deploy verification → first KTC capture → bootstrap census → accumulated census after window turnover → BROAD_CONTEXT PR (four dispositions) → IDP inventory → translator readiness table → ≤ 1 preregistered shadow translator → AL-0 after round-two review → AL-1a | plan §37 | AUTHORIZED campaign order |

## Added 2026-10-01 — Owner methodology decisions — final (Hill independent validation, historical league format, lineage thresholds)

Owner decisions received in chat 2026-10-01, **final for the current Calculator valuation / adaptive-learning
program**, recorded verbatim in substance. Detailed record: `docs/research/ADAPTIVE_LEARNING_2026-09-26.md` Part III
§35 (rows T8–T10) and §35.1. Authorization and follow-through units: `docs/EXECUTION_PLAN.md` §0, "Owner methodology
decisions — follow-through (2026-10-01)". Governance owner `C10-ML-01` + P6; no new manifest ID. **No canonical
player value changes merely from recording these decisions** (follow-through item 7).

**Decision 1 — Hill Autopilot: independent validation required (owner choice A).** Automatic OFFENSE Hill
promotion must require at least one genuinely independent validation target. The existing dependent-board
holdout gates remain useful and may remain required, but they are **necessary, not sufficient** for automatic
production promotion. If no eligible independent target exists: `AUTO_PROMOTION_BLOCKED:
no_independent_validation_target`. Challenger fitting, evaluation, persistence counting, shadow runs and evidence
accumulation continue normally; research and refits do not stop because automatic promotion is blocked; the
existing board gates are neither weakened nor removed. A future independent target must be preregistered and must
not derive materially from the same training families. The completed-trade ledger is the leading candidate, but
KTC Trade Database evidence alone is **not** automatically independent validation for a KTC-trained curve; prefer
deduplicated, format-qualified transaction evidence with independent provenance (especially Sharp/Sleeper
observations where applicable); a target mixing dependent and independent provenance must treat independence
explicitly rather than calling the whole target independent. Manual / model-governance review remains separate
from unattended Autopilot promotion; this decision closes the automatic-promotion loophole.

**Decision 2 — historical league format: strict NATIVE + BROAD_CONTEXT (owner choice A + D).** Keep the current
strict point-in-time rule for NATIVE_COMPARABLE: a past trade is NATIVE only when the format in force at the
transaction is established by the canonical point-in-time / bracketed evidence contract. A season-final or
post-trade settings capture does not prove the same format was in force throughout the season, so completed-season
final settings do not retroactively make old trades NATIVE, a matching post-trade capture does not make an earlier
trade NATIVE, and scoring-only before/after evidence is not sufficient while roster structure, team count and the
other axes remain temporally unproven. When BROAD_CONTEXT is implemented these otherwise useful trades are preserved
there:

- NATIVE_COMPARABLE — a pre-trade / in-force capture plus later same-format confirmation brackets the transaction
  under the current timing contract;
- BROAD_CONTEXT, timing-limited — verified dynasty trade whose later/final season settings match the target on all
  observed material axes, but no valid evidence brackets the format at transaction time; the reason is stamped
  (for example `season_final_settings`, `post_trade_capture`, `format_unconfirmed_at_trade`,
  `all_observed_axes_match_target`) and exactness is never implied;
- BROAD_CONTEXT, format mismatch — verified dynasty transaction with known target-format differences and no
  validated translator;
- TARGET_UNSUPPORTED — redraft, keeper for the current dynasty target lane, unverified dynasty state, unusable
  identity/topology, or another hard integrity failure.

The approximately 2026-era trades matching `dynasty_main`'s current axes without a predating/bracketing capture stay
usable as clearly labelled BROAD_CONTEXT, not NATIVE — honest uncertainty over retroactive precision. Earlier owner
definitions still bind: `targetPriceAuthority = 0` until a translator validates; no VALIDATED_TRANSFORMABLE exists
merely because the class exists; the former #1595 verified-dynasty-candidate population maps to BROAD_CONTEXT unless
another hard failure applies.

**Decision 3 — lineage dependence thresholds.** #1599's thresholds and resulting labels are preserved as
**descriptive historical output**; #1599 is not rewritten after its results were seen. The post-hoc thresholds
(measured: residual ≥ +0.30 and ≥ 90% snapshots positive; suspected: +0.10 to +0.30 and ≥ 75% positive) are **not**
permanent prospective methodology. Before the next prospective dependence-classification experiment, the
classification policy is preregistered before its result set is examined, evaluating more than one cutoff where
possible: effect/residual magnitude, consistency across distinct source versions, effective sample size,
bootstrap/uncertainty interval, the estimator's positive floor, rank versus value-spacing dependence, and temporal
autocorrelation — correlated repeated snapshots never masquerade as independent observations. No current major
conclusion changes: OTC's approximately +0.45 dependence on KTC with positive evidence in 21 of 21 measured snapshots
remains sufficient for OTC never to be treated as an independent KTC-family holdout; the borderline Fitzmaurice /
Dynasty Nerds labels remain descriptive in #1599 and do not become production lineage truth; for Hill exclusion and
promotion safety, fail closed whenever independence is not established.

**Supersession (in place).** The 2026-10-01 Batch 3 completed-trade addendum's three-disposition model (already
superseded in part by the continuation instructions) is superseded further by decision 2; the Batch 3 "Hill trainer /
Autopilot substrate repair" and "Ingestion / lineage integrity sweep" rows and the 2026-09-26 Hill Autopilot
precedent sentence carry refinement notes for decisions 1 and 3. No earlier intake entry adopted #1599's thresholds
as methodology: they appeared only as the declared-after-the-fact category rule inside #1599's own evidence record,
which stays immutable.

| Required follow-through (owner) | Disposition |
|---|---|
| 1. Add the independent-target requirement to Hill Autopilot with focused tests | AUTHORIZED — in progress on `claude/hill-autopilot-independent-gate` |
| 2. Do not create a fake independent target merely to restore automatic promotion | BINDING — automatic promotion stays blocked until a preregistered independent target exists |
| 3. Preserve current strict format timing | BINDING — NATIVE_COMPARABLE keeps the bracket rule |
| 4. Fold season-final / post-trade matching dynasty transactions into BROAD_CONTEXT when that fourth disposition lands | AUTHORIZED — in progress on `claude/broad-context-disposition` (AL-2a′) |
| 5. Keep #1599's historical results immutable | BINDING — `docs/sources/integrity/OTC_LINEAGE_REMEASURE_2026-10-01.md` and `OTC_PAIR_SNAPSHOTS_2026-10-01.json` unchanged |
| 6. Create a separately versioned, preregistered prospective lineage-threshold policy before the next such experiment | DONE (policy) — `docs/sources/lineage_policy/LINEAGE_DEPENDENCE_POLICY_v1_PREREGISTRATION.md` (`lineage-policy/v1`), preregistered in its own commit `94e16c4f1a986ecc3045d1b4702ce6efe0d8cc05` (committed 2026-10-02T01:10:52Z, the §14.1 boundary) before any result set was examined under it; normative-block sha256 in the sidecar `.sha256`, pinned by `tests/sources/test_lineage_policy_v1_preregistration.py`. Instrument and vocabulary implementation is a separate reviewed unit |
| 7. No canonical player value changes merely from recording these decisions | BINDING — this record is documentation only |

## Added 2026-10-03 — Flock rookie board: declared seasonal window (owner methodology decision, #1552)

Owner decision received in chat 2026-10-03, recorded verbatim in substance; it supersedes the unresolved choice
in `docs/ops/INCIDENT_2026-09-05_FLOCK_ROOKIE_FLOOR.md` §4 (declared seasonal window vs relative drop guard), and
that section now carries the decision, the implementation map and the measured board impact.

**Decision.** Choose the DECLARED SEASONAL-WINDOW approach for `flockFantasySfRookies`, implemented as a real
phase-dependent source state — not a generic weakening of freshness monitoring.

| Item | Disposition |
|---|---|
| For the graduating 2026 class, an empty `PROSPECTS_SF` response from October 1, 2026 is an expected `seasonally_inactive` state, not a stale-source failure | IMPLEMENTED — `claude/flock-rookie-seasonal-window` (`src/sources/seasonal_policy.py`, `config/sources/seasonal_policy_v1.json`) |
| Keep attempting the fetch on every normal schedule while inactive; never fabricate a success timestamp, freshness stamp, row or payload | IMPLEMENTED — fetcher exit 4 + explicit `<key>_seasonal.json` state; `run_fetcher` still stamps only on exit 0 |
| An inactive rookie source must not keep contributing its old rankings to current canonical values: no current vote — not zero value, not indefinitely decayed stale authority; historical CSV/archive kept intact | IMPLEMENTED — dropped at the active-source gate like a disabled source; CSV untouched |
| First valid non-empty `PROSPECTS_SF` response for the next class reactivates immediately, regardless of date; normal 24h freshness and shape/schema guards then apply | IMPLEMENTED |
| Keep the within-active-season truncation / row-count protections (window = "should a board exist?"; floor = "is it truncated?") | KEPT — floor unchanged |
| Do not add the source to `soft` | HONOURED |
| Configuration-backed and reusable for other phase-dependent sources; fail closed for any source with no declared policy | IMPLEMENTED |
| Tests: empty after cutoff → inactive + workflow green; zero voting authority; no fake stamp; attempts continue; next-class data reactivates; malformed non-empty still fails guards; empty while expected active still fails closed | IMPLEMENTED — `tests/sources/test_seasonal_policy.py`, `tests/scripts/test_flock_rookie_seasonal_window.py`, `tests/api/test_seasonal_source_consumers.py` |
| No change to unrelated source thresholds, weights, Hill methodology or canonical values beyond removing the inactive board from current voting | HONOURED — measured: 83 values moved, all Flock-rookie-voted rows (43) or rookie-tethered 2026 slot picks (40), 0 others |

## Added 2026-10-03 — Trade Calculator: unlimited asset quantity + Early/Mid/Late market picks (owner decision)

Two owner decisions, dated 2026-10-03. **They supersede the T-NEW-02 / #1415 uniqueness rule for the
Trade Calculator** ("the exact same unique owned pick may not be double-counted"; players unique inside
the calculator). The quantity / identity / round-trip half of #1415 stands. Supersession is in place: the
T-NEW-02 companion row and the Lane B #1415 row above carry pointers here; the older wording stays
traceable in `docs/OWNER_REQUESTED_TODO_SPEC_INDEX.md`, `docs/TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md`,
`docs/C_SERIES_SCOPE_MANIFEST.md` (`C3-CALC-01`), `docs/C_SERIES_EXECUTION_MAP.md`,
`docs/OWNER_FEATURE_INVENTORY.md` §2.1 and `docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md` §11, each now
marked superseded in part.

**Principle:** Trade Calculator assets are hypothetical quantities, not inventory-enforced unique objects; real uniqueness remains in ownership records, transaction history, pick identity and roster-aware recommendations.

**Decision 1 — every trade asset is repeatable.** Every selectable asset in the Trade Calculator — players,
generic Early/Mid/Late picks, exact slot picks, owned league picks, future generic picks — can be added any
number of times, to either or both sides. No quantity cap of any kind. Ownership and provenance may be
DISPLAYED but never restrict quantity. Roster-aware suggestion engines (balancers / equalizer, suggestions)
still use real ownership for their own recommendations — never claim a team owns four Jeffersons — through
a separately named function; one function never enforces both.

**Decision 2 — restore Early/Mid/Late future-pick market references.** Searching a year makes that year's
Early/Mid/Late 1st, 2nd, … discoverable for every active future year and round, derived from the data
(never a hardcoded year). These are market-reference assets, separate from owned picks; both may appear
and both may be added. Values come only from the canonical pipeline (`rankDerivedValue` on the board row):
no frontend arithmetic or averaging, and owned picks are not mapped to Mid. An owned unknown-slot pick
keeps its existing label and valuation method.

| Item | Disposition |
|---|---|
| Manual calculator construction never refuses a copy (players, owned picks, the same asset on both sides); `canAddEntry` true for any valid row | IMPLEMENTED — `claude/trade-calc-quantity-tiers` |
| `− N +` on every grouped line; `+` unbounded; `−` removes one copy and removes the line at 1; finger-sized on phones | IMPLEMENTED |
| One entry per copy (no quantity field); totals, VA, flows, destinations, War Room / BDVM / simulator payloads, localStorage, share URL, CSV/JSON export, KTC import all count and preserve copies exactly | IMPLEMENTED — share links run-length-encode copies per line (additive `q`) |
| Equalizer keeps roster-aware ownership via `heldAssetKeysInTrade` / `unusedTeamPickEntries` (recommendation-only) | IMPLEMENTED |
| Early/Mid/Late disappearance: data was present (priced, unsuppressed tier rows); `/trade` search put up to 5 owned picks BEFORE the board rows and the dropdown did not scroll, so on an iPhone with the keyboard open only owned "2027 1st / 2nd" rows were visible | FIXED — market group first, owned picks second, separate limits (`searchCalculatorAssets`), exact-query relevance first, scrollable dropdown |
| Suppressed generic aliases (`pickGenericSuppressed`) stay excluded | UNCHANGED — pinned by test |

## Added 2026-10-03 — Signals must become an ACTIVE offense + IDP source (owner addendum)

Owner addendum of 2026-10-03, confirmed in chat ("Yes, execute both"); the same day the owner chose the
voting path **"Value-ordered rank"** (Signals votes like FantasyCalc / Dynasty Daddy: its own native-value
order is the rank, labelled derived; native values retained and shown). Supersedes the non-voting
second-opinion stage of the 2026-10-01 rows above for the AUTHENTICATED values only — the public positional
boards still never vote. Full record: `docs/sources/SIGNALS_FANTASY_INTEGRATION.md` §9.

| Item | Disposition |
|---|---|
| Signals contributes to canonical values for offense (QB/RB/WR/TE) and IDP, through the existing owners (no parallel blend) | OFFENSE IMPLEMENTED (`signalsSf`, rank signal); IDP COLLECTED + DISPLAYED but HELD from voting — Signals' IDP value is normalised per family, so only a within-family rank is legitimate, and the existing positional path prices it in IDP-local coordinates (independent review of #1627, B1; `docs/sources/SIGNALS_FANTASY_INTEGRATION.md` §9.2). Lifting the hold needs a coordinate decision. Not yet merged or deployed |
| Selection hierarchy: exact-league value > SF/TEP preset value > authenticated rank > public rank; values first, ranks only as fallback; one active Signals observation per player | IMPLEMENTED — exact-league values are client-side (not collected); stored Dynasty SF value votes; cross-position-rank fallback inert (none published); public positional ranks never vote |
| SF / TEP / exact league recorded per observation; no double scoring adjustment | IMPLEMENTED — measured Superflex, not TEP; base → TE++ conversion applied once |
| IDP raw position preserved; DL/LB/DB only via the canonical owner | IMPLEMENTED |
| One Signals family, no independence bonus; keep lineage treatment vs KTC/FantasyCalc/Dynasty Daddy | IMPLEMENTED — `fantasyCalc` B10 family; lineage relation `signals-fantasycalc-app-composition` (suspected) |
| Signals visible in the Rankings source/ranks column (name, rank, native value, VALUE vs RANK, dataset, format, as-of) | IMPLEMENTED — desktop, mobile chip, audit card |
| No private Signals data in public APIs, logs, caches or the repository | IMPLEMENTED — box-local private store; public `/league` guard extended |
| Acceptance 1–17 | 1–16 evidenced in the PR; 15 measured on the production box; 17 is post-deploy |
